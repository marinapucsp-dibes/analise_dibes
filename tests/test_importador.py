import io
from pathlib import Path

import pandas as pd
import pytest

from dibes import analise, banco, importador, relatorio

EXEMPLOS = Path(__file__).resolve().parent.parent / "exemplos"


@pytest.mark.parametrize("texto,esperado", [
    ("1.234", 1234), ("1.234,5", 1234.5), ("12,0", 12), ("150", 150), (" 98 ", 98),
    ("-", None), ("", None), ("abc", None), (42, 42), (3.5, 3.5),
])
def test_para_numero(texto, esperado):
    assert importador.para_numero(texto) == esperado


@pytest.mark.parametrize("texto,esperado", [
    ("Março/2026", "2026-03"), ("cestas_2026-07.csv", "2026-07"), ("03/2026", "2026-03"),
    ("Relatório de Setembro de 2026", "2026-09"), ("dez-25", "2025-12"), ("CRAS Norte", None),
])
def test_detectar_mes(texto, esperado):
    assert importador.detectar_mes(texto) == esperado


def test_html_colado_com_total_divergente():
    codigo = """<table>
      <tr><th>CRAS/CREAS</th><th>Cota Disponível</th><th>Qtd Solicitada</th><th>Demanda Registrada</th>
          <th>Atendimento Social</th><th>Recibos Emitidos</th><th>Cestas Concedidas</th></tr>
      <tr><td>CRAS Vila Nova</td><td>100</td><td>90</td><td>110</td><td>200</td><td>85</td><td>85</td></tr>
      <tr><td>CREAS Regional</td><td>40</td><td>30</td><td>35</td><td>60</td><td>30</td><td>30</td></tr>
      <tr><td>TOTAL</td><td>140</td><td>120</td><td>145</td><td>260</td><td>115</td><td>999</td></tr>
    </table>"""
    r = importador.importar_html_colado(codigo, "2026-05")
    assert list(r.dados["unidade"]) == ["CRAS Vila Nova", "CREAS Regional"]
    assert list(r.dados["tipo"]) == ["CRAS", "CREAS"]
    assert r.dados["cestas_concedidas"].sum() == 115
    assert any("Cestas Concedidas" in a and "difere" in a for a in r.avisos)


def test_planilha_transposta_csv():
    csv = ("Campo;CRAS A;CRAS B;CREAS\n"
           "Cota Disponível;10;20;5\nQuantidade Solicitada;8;18;4\nDemanda Registrada;12;25;6\n"
           "Atendimento Social;30;40;9\nRecibos Emitidos;8;18;4\nCestas Concedidas;8;18;4\n")
    r = importador.importar_arquivo(csv.encode(), "planilha.csv", "2026-01")
    assert r.dados.set_index("unidade")["cota_disponivel"].to_dict() == {"CRAS A": 10, "CRAS B": 20, "CREAS": 5}


def test_texto_livre_com_numero_no_nome():
    texto = ("Unidade Cota Disponível Quantidade Solicitada Demanda Registrada Atendimento Social "
             "Recibos Emitidos Cestas Concedidas\nCRAS 2 Centro 100 90 95 150 80 80\n")
    r = importador._ler_texto_livre(texto, "doc.pdf", "2026-02")
    assert r.dados.iloc[0]["unidade"] == "CRAS 2 Centro"
    assert r.dados.iloc[0]["cota_disponivel"] == 100


@pytest.mark.parametrize("arquivo,meses", [
    ("cestas_1o_semestre_2026.xlsx", 6), ("cestas_2026-07.csv", 1),
    ("cestas_agosto_2026.html", 1), ("cestas_setembro_2026.pdf", 1),
])
def test_exemplos(arquivo, meses):
    r = importador.importar_arquivo((EXEMPLOS / arquivo).read_bytes(), arquivo)
    assert r.dados["mes"].nunique() == meses
    assert len(r.dados) == 7 * meses
    assert not r.avisos  # o total informado bate com a soma das unidades


def test_banco_analise_e_relatorio(tmp_path):
    caminho = tmp_path / "t.db"
    for f in sorted(EXEMPLOS.iterdir()):
        banco.salvar(importador.importar_arquivo(f.read_bytes(), f.name).dados, f.name, caminho)
    df = banco.carregar(caminho)
    assert df["mes"].nunique() == 9
    # reimportar não duplica
    f = EXEMPLOS / "cestas_2026-07.csv"
    banco.salvar(importador.importar_arquivo(f.read_bytes(), f.name).dados, f.name, caminho)
    assert len(banco.carregar(caminho)) == len(df)

    total = analise.total_geral(df)
    tipos = analise.por_tipo(df)
    soma_tipos = tipos.groupby("mes")["cestas_concedidas"].sum().values
    assert (total["cestas_concedidas"].values == soma_tipos).all()
    assert total["uso_cota"].between(0, 200).all()

    alertas = analise.alertas(df, "2026-09")
    assert set(alertas.columns) == {"Gravidade", "Unidade", "Tipo", "SAS", "Regra", "Detalhe"}
    assert "Demanda maior que a cota" in set(alertas["Regra"])

    xlsx = relatorio.gerar_excel(df)
    abas = pd.read_excel(io.BytesIO(xlsx), sheet_name=None)
    assert {"Total Geral", "CRAS x CREAS", "Por unidade", "Alertas"} <= set(abas)

    assert banco.excluir_mes("2026-09", caminho) == 7


def test_relatorio_pdf(tmp_path):
    from dibes import relatorio_pdf

    caminho = tmp_path / "t.db"
    for f in sorted(EXEMPLOS.iterdir()):
        banco.salvar(importador.importar_arquivo(f.read_bytes(), f.name).dados, f.name, caminho)
    df = banco.carregar(caminho)
    pdf = relatorio_pdf.gerar_pdf(df, "2026-09")
    assert pdf.startswith(b"%PDF")
    # o primeiro mês não tem mês anterior nem evolução: também precisa funcionar
    assert relatorio_pdf.gerar_pdf(df, "2026-01").startswith(b"%PDF")


# Painel HTML no formato da Secretaria: tabela vazia, dados em listas JavaScript (SAS e unidades na
# mesma ordem, sem dizer a qual SAS cada unidade pertence). Valores fictícios.
PAINEL_JS = """<html><head><title>Dashboard SAS - Auxílio Alimentação - Março/2026</title>
<style>.x{grid-template-columns:repeat(auto-fit,minmax(300px,1fr))}</style></head><body>
<table class="data-table"><thead><tr><th>Unidade SAS</th><th>Cotas</th><th>Cestas Recebidas</th>
<th>Demanda pelo Benefício</th><th>Registros de Atend. Técnico</th><th>Recibos Válidos</th>
<th>Cestas Entregues</th><th>Fam. Sem Registro de Atend. Social</th><th>Cestas em Estoque</th></tr></thead>
<tbody id="tableBody"></tbody></table>
<p>Período 01/01/2026 a 31/01/2026</p>
<script>
const sasData = [
  {name:"SAS NORTE - NO",cotas:100,cestasRecebidas:90,demanda:80,atendimento:70,recibosValidos:75,entregues:78},
  {name:"SAS VILA SUL - VS",cotas:50,cestasRecebidas:50,demanda:40,atendimento:30,recibosValidos:30,entregues:33},
  {name:"SAS VILA LESTE",cotas:60,cestasRecebidas:0,demanda:20,atendimento:20,recibosValidos:20,entregues:20}
];
const crasData = [
  {name:"CRAS NORTE",cotas:70,cestasRecebidas:60,demanda:60,atendimento:50,recibosValidos:55,entregues:57},
  {name:"CRAS NORTE II",cotas:30,cestasRecebidas:30,demanda:20,atendimento:20,recibosValidos:20,entregues:21},
  {name:"CREAS NORTE",cotas:0,cestasRecebidas:0,demanda:0,atendimento:0,recibosValidos:0,entregues:0},
  {name:"CRAS VILA SUL",cotas:50,cestasRecebidas:50,demanda:38,atendimento:30,recibosValidos:30,entregues:33},
  {name:"CENTRO POP VILA SUL",cotas:0,cestasRecebidas:0,demanda:2,atendimento:0,recibosValidos:0,entregues:0},
  {name:"CREAS VILA SUL",cotas:0,cestasRecebidas:0,demanda:0,atendimento:0,recibosValidos:0,entregues:0},
  {name:"CRAS M'BOI LESTE",cotas:0,cestasRecebidas:0,demanda:20,atendimento:20,recibosValidos:20,entregues:20}
];
function populateTable(data){ data.forEach(item=>{}); }
</script></body></html>"""


def test_painel_html_com_listas_js():
    r = importador.importar_html_colado(PAINEL_JS)
    d = r.dados
    assert not r.avisos
    assert set(d["mes"]) == {"2026-03"}  # o título, e não o período do rodapé
    assert d["tipo"].value_counts().to_dict() == {"SAS": 3, "CRAS": 4, "CREAS": 2, "Centro POP": 1}
    sas = d.set_index("unidade")["sas"]
    # as unidades zeradas na fronteira ficam com a SAS de nome parecido
    assert sas["CREAS NORTE"] == "SAS NORTE - NO"
    assert sas["CREAS VILA SUL"] == "SAS VILA SUL - VS"
    assert sas["CRAS M'BOI LESTE"] == "SAS VILA LESTE"
    assert d.set_index("unidade").loc["CRAS NORTE II", "quantidade_solicitada"] == 30  # "Cestas Recebidas"


def test_totais_usam_valor_informado_da_sas():
    d = importador.importar_html_colado(PAINEL_JS).dados
    total = analise.total_geral(d).iloc[0]
    # a cota de 60 da SAS VILA LESTE não foi distribuída à unidade, mas entra no total
    assert total["cota_disponivel"] == 210
    assert total["unidades"] == 7
    assert total["recibos_sem_atendimento"] == 5
    por_sas = analise.por_sas(d).set_index("sas")
    assert por_sas.loc["SAS VILA LESTE", "cota_disponivel"] == 60
    assert analise.por_tipo(d).set_index("tipo").loc["CRAS", "cestas_concedidas"] == 131
    regras = set(analise.alertas(d, "2026-03")["Regra"])
    assert "SAS diferente da soma das unidades" in regras
    assert "Recibos sem registro de atendimento social" in regras


def test_banco_antigo_ganha_coluna_sas(tmp_path):
    import sqlite3

    caminho = tmp_path / "antigo.db"
    with sqlite3.connect(caminho) as con:
        con.execute("CREATE TABLE registros (mes TEXT, unidade TEXT, tipo TEXT, cota_disponivel REAL, "
                    "quantidade_solicitada REAL, demanda_registrada REAL, atendimento_social REAL, "
                    "recibos_emitidos REAL, cestas_concedidas REAL, arquivo TEXT, importado_em TEXT, "
                    "PRIMARY KEY (mes, unidade))")
        con.execute("INSERT INTO registros VALUES ('2026-01','CRAS A','CRAS',1,1,1,1,1,1,'x','y')")
    df = banco.carregar(caminho)
    assert "sas" in df.columns and len(df) == 1
    novo = importador.importar_html_colado(PAINEL_JS).dados
    banco.salvar(novo, "painel", caminho)
    assert banco.mapa_sas(caminho)["CREAS NORTE"] == "SAS NORTE - NO"


def test_estoque():
    d = importador.importar_html_colado(PAINEL_JS).dados
    total = analise.total_geral(d).iloc[0]
    assert total["estoque"] == 140 - 131  # quantidade solicitada (cestas recebidas) − concedidas
    und = analise.por_unidade(d).set_index("unidade")
    assert und.loc["CRAS NORTE II", "estoque"] == 9
    assert und.loc["CRAS M'BOI LESTE", "estoque"] == -20  # usou estoque do mês anterior
    regras = analise.alertas(d, "2026-03").groupby("Regra")["Unidade"].apply(set)
    assert "CRAS NORTE II" in regras["Cestas em estoque"]
    assert "CRAS M'BOI LESTE" in regras["Uso de estoque do mês anterior"]


def _pdf_impresso(caminho, linhas, cortar_ultima=False):
    """PDF como o 'Imprimir > Salvar como PDF' do navegador: título em 3 linhas, nomes quebrados
    acima e abaixo dos números e, opcionalmente, a última coluna cortada na margem."""
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(caminho), pagesize=(595, 842))
    c.setFont("Helvetica", 9)
    c.drawString(24, 826, "26/10/2026, 15:51 Dashboard SAS - Análise de Cestas Básicas")
    c.drawString(73, 800, "Mês: Fevereiro/2026")
    xs = [173, 216, 280, 342, 421, 474]
    titulos = [("", "Cotas", ""), ("Cestas", "", "Recebidas"), ("", "Demanda", ""), ("", "Atendimento", ""),
               ("Recibos", "", "Válidos"), ("Cestas", "", "Entregues")]
    if cortar_ultima:
        titulos[-1] = ("C", "", "E")
    for x, partes in zip(xs, titulos):
        for dy, t in zip((0, 8, 16), partes):
            c.drawString(x, 700 - dy, t)
    c.drawString(73, 692, "Unidade")
    y = 660
    for nome, valores in linhas:
        partes = nome.split(" ", 1)
        if len(partes) == 2:
            c.drawString(73, y + 9, partes[0])
            c.drawString(73, y - 9, partes[1])
        else:
            c.drawString(73, y, nome)
        for x, v in zip(xs, valores):
            c.drawString(x, y, str(v)[:1] if cortar_ultima and x == xs[-1] else str(v))
        y -= 54
    c.drawString(73, y - 40, "Análise Técnica Detalhada")
    c.drawString(73, y - 52, "Taxa de Recebimento: 80.6% das cotas foram recebidas (5.930 de 7.357)")
    c.save()


def test_pdf_impresso_do_navegador(tmp_path):
    sas = [("SAS NORTE - NO", [100, 90, 80, 70, 75, 78]), ("SAS VILA SUL - VS", [50, 50, 40, 30, 30, 33])]
    und = [("CRAS NORTE", [70, 60, 60, 50, 55, 57]), ("CREAS NORTE", [30, 30, 20, 20, 20, 21]),
           ("CRAS VILA SUL", [50, 50, 38, 30, 30, 33]), ("CREAS VILA SUL", [0, 0, 2, 0, 0, 0])]
    _pdf_impresso(tmp_path / "sas.pdf", sas, cortar_ultima=True)
    _pdf_impresso(tmp_path / "cras.pdf", und)
    partes = [importador.importar_arquivo((tmp_path / f).read_bytes(), f) for f in ("sas.pdf", "cras.pdf")]
    r = importador.finalizar(importador._juntar(partes))
    d = r.dados.set_index("unidade")
    assert set(d["mes"]) == {"2026-02"}  # e não 10/2026, a data da impressão
    assert d.loc["CRAS VILA SUL", "sas"] == "SAS VILA SUL - VS"  # nome quebrado em duas linhas
    assert d.loc["CREAS NORTE", "cestas_concedidas"] == 21
    assert pd.isna(d.loc["SAS NORTE - NO", "cestas_concedidas"])  # coluna cortada: não lê o "7"
    assert any("cortada" in a for a in r.avisos)
    total = analise.total_geral(r.dados).iloc[0]
    assert total["cestas_concedidas"] == 111  # vem da soma das unidades
    assert total["estoque"] == 140 - 111


def test_grafias_diferentes_entre_meses_viram_um_nome():
    linhas = [
        ("2026-01", "SAS JAÇANÃ/TREMEMBÉ - JT", "SAS", "SAS JAÇANÃ/TREMEMBÉ - JT"),
        ("2026-01", "CREAS SÃO MIGUEL PAULISTA", "CREAS", "SAS SÃO MIGUEL - MP"),
        ("2026-01", "CRAS CIDADE ADEMAR", "CRAS", "SAS CIDADE ADEMAR - CD"),
        ("2026-01", "CRAS CIDADE ADEMAR II", "CRAS", "SAS CIDADE ADEMAR - CD"),
        ("2026-02", "SAS JAÇÃNA/TREMEMBÉ - JT", "SAS", "SAS JAÇÃNA/TREMEMBÉ - JT"),
        ("2026-02", "CREAS SÃO MIGUEL", "CREAS", "SAS SÃO MIGUEL - MP"),
        ("2026-02", "CRAS CIDADE ADEMAR", "CRAS", "SAS CIDADE ADEMAR - CD"),
        ("2026-02", "CRAS CIDADE ADEMAR II", "CRAS", "SAS CIDADE ADEMAR - CD"),
        ("2026-03", "SAS SANTO AMARO - AS", "SAS", "SAS SANTO AMARO - AS"),
        ("2026-04", "SAS SANTO AMARO - SA", "SAS", "SAS SANTO AMARO - SA"),
    ]
    df = pd.DataFrame(linhas, columns=["mes", "unidade", "tipo", "sas"])
    mapa = analise.mapa_nomes(df)
    assert mapa == {"SAS JAÇÃNA/TREMEMBÉ - JT": "SAS JAÇANÃ/TREMEMBÉ - JT",
                    "CREAS SÃO MIGUEL": "CREAS SÃO MIGUEL PAULISTA",
                    "SAS SANTO AMARO - SA": "SAS SANTO AMARO - AS"}
    u = analise.unificar_nomes(df)
    assert u.loc[4, "sas"] == "SAS JAÇANÃ/TREMEMBÉ - JT"
    assert u["unidade"].nunique() == 5  # CIDADE ADEMAR e CIDADE ADEMAR II continuam separadas


def _unidades(**campos):
    base = {"mes": "2026-05", "sas": "SAS X", "tipo": "CRAS", "cota_disponivel": 100,
            "quantidade_solicitada": 100, "demanda_registrada": 50, "atendimento_social": 50,
            "recibos_emitidos": 50, "cestas_concedidas": 50}
    return pd.DataFrame([{**base, "unidade": nome, **valores} for nome, valores in campos.items()])


def test_destaques_recibos_e_baixa_concessao():
    df = _unidades(**{"CRAS A": {"recibos_emitidos": 60, "cestas_concedidas": 60},   # 16,7% sem atendimento
                      "CRAS B": {"recibos_emitidos": 52, "cestas_concedidas": 52},   # 3,8%
                      "CRAS C": {"cestas_concedidas": 5, "recibos_emitidos": 5, "atendimento_social": 5},
                      "CRAS D": {}})
    rec = analise.destaque_recibos(df, "2026-05").set_index("unidade")
    assert list(rec.index) == ["CRAS A", "CRAS B"]
    assert round(rec.loc["CRAS A", "pct_recibos_sem_atendimento"], 1) == 16.7
    assert list(analise.destaque_baixa_concessao(df, "2026-05")["unidade"]) == ["CRAS C"]
    alertas = analise.alertas(df, "2026-05").set_index(["Unidade", "Regra"])["Gravidade"]
    assert alertas[("CRAS A", "Recibos sem registro de atendimento social")] == "Crítico"
    assert alertas[("CRAS B", "Recibos sem registro de atendimento social")] == "Atenção"
    assert alertas[("CRAS C", "Concessão abaixo de 10% da cota")] == "Crítico"
    assert ("CRAS C", "Baixo uso da cota") not in alertas.index


def test_analise_por_ia_monta_o_pedido(monkeypatch):
    from dibes import ia

    enviado = {}

    class StreamFalso:
        text_stream = iter(["Análise ", "pronta."])

        def __enter__(self):
            return self

        def __exit__(self, *erro):
            return False

        def get_final_message(self):
            return type("Msg", (), {"stop_reason": "end_turn"})()

    class ClienteFalso:
        def __init__(self, api_key):
            enviado["api_key"] = api_key
            self.beta = type("Beta", (), {"messages": self})()

        def stream(self, **kwargs):
            enviado.update(kwargs)
            return StreamFalso()

    monkeypatch.setattr(ia.anthropic, "Anthropic", ClienteFalso)
    d = importador.importar_html_colado(PAINEL_JS).dados
    texto = "".join(ia.analisar(d, "2026-03", "", "sk-ant-teste"))
    assert texto == "Análise pronta."
    assert enviado["model"] == "claude-opus-5-5"
    assert enviado["fallbacks"] == "default" and enviado["betas"] == ["server-side-fallback-2026-07-01"]
    pedido = enviado["messages"][0]["content"]
    assert "SAS NORTE - NO" in pedido and "CRAS NORTE II" in pedido and "Recomendações" in pedido


def test_reimportar_substitui_e_nao_soma(tmp_path):
    caminho = tmp_path / "t.db"
    errado = _unidades(**{"CRAS A": {"cestas_concedidas": 999}, "CRAS ERRADO": {}})
    banco.salvar(errado, "abril errado", caminho)
    certo = _unidades(**{"CRAS A": {"cestas_concedidas": 40}})
    # reimportar sem substituir o mês: troca os valores da unidade, mas a unidade errada sobra
    banco.salvar(certo, "abril certo", caminho)
    df = banco.carregar(caminho).set_index("unidade")
    assert df.loc["CRAS A", "cestas_concedidas"] == 40 and "CRAS ERRADO" in df.index
    # substituindo o mês inteiro, sobra só o que veio no arquivo novo
    banco.salvar(certo, "abril certo", caminho, substituir_meses=True)
    assert list(banco.carregar(caminho)["unidade"]) == ["CRAS A"]
    # correção manual que move a linha para outro mês esvazia o mês original
    banco.salvar(certo.assign(mes="2026-06"), "correção manual", caminho, apagar_meses=("2026-05",))
    assert list(banco.carregar(caminho)["mes"]) == ["2026-06"]
