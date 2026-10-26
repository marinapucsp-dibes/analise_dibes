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

    total = analise.total_sas(df)
    tipos = analise.por_tipo(df)
    soma_tipos = tipos.groupby("mes")["cestas_concedidas"].sum().values
    assert (total["cestas_concedidas"].values == soma_tipos).all()
    assert total["uso_cota"].between(0, 200).all()

    alertas = analise.alertas(df, "2026-09")
    assert set(alertas.columns) == {"Gravidade", "Unidade", "Tipo", "Regra", "Detalhe"}
    assert "Recibos diferentes das cestas concedidas" in set(alertas["Regra"])

    xlsx = relatorio.gerar_excel(df)
    abas = pd.read_excel(io.BytesIO(xlsx), sheet_name=None)
    assert {"Total SAS", "CRAS x CREAS", "Por unidade", "Alertas"} <= set(abas)

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
