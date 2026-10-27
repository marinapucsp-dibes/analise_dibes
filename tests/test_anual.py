import io

import pandas as pd

from dibes import anual, banco, relatorio_anual

A, P = anual.ALIMENTACAO, anual.PASSAGENS


def _lancar(caminho, mes, valores, outros=()):
    linhas = [{"atividade": anual.ATIVIDADE_DO[i], "indicador": i, "valor": v} for i, v in valores.items()]
    linhas += [{"atividade": anual.OUTROS, "indicador": n, "valor": v} for n, v in outros]
    return banco.salvar_atividades(mes, pd.DataFrame(linhas), caminho)


def test_quadro_anual_com_sistema_de_cestas_e_digitado(tmp_path):
    caminho = tmp_path / "t.db"
    _lancar(caminho, "2026-01", {"cestas_compradas": 5000, "valor_cestas": 750000.5, "cestas_concedidas_sas": 1,
                                 "solicitacoes": 100, "solicitacoes_atendidas": 80, "passagens_compradas": 90,
                                 "passagens_nao_utilizadas": 9, "valor_passagens": 9000, "pessoas_beneficiadas": 75,
                                 "manutencoes_lote": 300, "manutencoes_manuais": 20},
            outros=[("Capacitações", 3)])
    _lancar(caminho, "2026-02", {"cestas_concedidas_sas": 4800, "protocolos_respondidos": 12},
            outros=[("Capacitações", 2), ("Visitas técnicas", 5)])
    registros = pd.DataFrame([{"mes": "2026-01", "sas": "SAS X", "unidade": "SAS X", "tipo": "SAS",
                               "cota_disponivel": 1, "quantidade_solicitada": 1, "demanda_registrada": 1,
                               "atendimento_social": 1, "recibos_emitidos": 1, "cestas_concedidas": 5298}])
    emerg = pd.DataFrame({"mes": ["2026-01"], "ocorrencia": ["ENCHENTE"], "cestas": [199.0]})
    base = anual.lancamentos(banco.carregar_atividades(caminho), anual.cestas_do_sistema(registros, emerg))
    q = anual.quadro_anual(base, "2026").set_index(["atividade", "indicador"])

    concedidas = q.loc[(A, "Cestas concedidas (SAS/unidades)")]
    assert concedidas[1] == 5298  # o sistema de cestas prevalece sobre o digitado (1)
    assert concedidas[2] == 4800  # mês fora do sistema: vale o digitado
    assert q.loc[(A, "Total de cestas concedidas"), "Total"] == 5298 + 199 + 4800
    assert round(q.loc[(A, "Custo médio por cesta comprada"), 1], 2) == 150.0
    assert q.loc[(P, "Taxa de atendimento das solicitações"), "Total"] == 80
    assert q.loc[(P, "Passagens não utilizadas (% das compradas)"), 1] == 10
    assert q.loc[(P, "Custo médio por pessoa beneficiada"), 1] == 120
    assert q.loc[(anual.PBF, "Total de manutenções"), "Total"] == 320
    assert q.loc[(anual.OUTROS, "Capacitações"), "Total"] == 5
    assert q.loc[(anual.OUTROS, "Visitas técnicas"), 2] == 5
    assert anual.meses_lancados(banco.carregar_atividades(caminho), "2026") == {1: 12, 2: 4}

    quadro = anual.quadro_anual(base, "2026")
    xlsx = relatorio_anual.gerar_excel_anual(quadro, "2026", pd.DataFrame(), pd.DataFrame(), base)
    abas = pd.read_excel(io.BytesIO(xlsx), sheet_name=None)
    assert {"Quadro anual", "Lançamentos"} <= set(abas)
    assert relatorio_anual.gerar_pdf_anual(quadro, "2026", pd.DataFrame()).startswith(b"%PDF")


def test_relancar_mes_substitui(tmp_path):
    caminho = tmp_path / "t.db"
    _lancar(caminho, "2026-03", {"processos_respondidos": 40}, outros=[("Reuniões", 4)])
    _lancar(caminho, "2026-03", {"processos_respondidos": 42})  # correção: 'Reuniões' foi apagada
    d = banco.carregar_atividades(caminho)
    assert d[["indicador", "valor"]].values.tolist() == [["processos_respondidos", 42.0]]


# ------------------------------------------------------------------ importação

from dibes import importador_anual  # noqa: E402


def _valores(r):
    return {(m, i): v for m, i, v in r.dados[["mes", "indicador", "valor"]].itertuples(index=False)}


def _quadro_exemplo(tmp_path):
    caminho = tmp_path / "t.db"
    _lancar(caminho, "2026-01", {"cestas_compradas": 5000, "valor_cestas": 750000.5, "solicitacoes": 100,
                                 "solicitacoes_atendidas": 80, "passagens_compradas": 90, "valor_passagens": 9000,
                                 "protocolos_respondidos": 30, "manutencoes_lote": 300},
            outros=[("Visitas a processos", 3)])
    _lancar(caminho, "2026-02", {"cestas_compradas": 4000, "processos_respondidos": 55})
    base = anual.lancamentos(banco.carregar_atividades(caminho), anual.cestas_do_sistema(pd.DataFrame(),
                                                                                         pd.DataFrame()))
    return base, anual.quadro_anual(base, "2026")


ESPERADO = {("2026-01", "cestas_compradas"): 5000, ("2026-01", "valor_cestas"): 750000.5,
            ("2026-01", "solicitacoes"): 100, ("2026-01", "solicitacoes_atendidas"): 80,
            ("2026-01", "passagens_compradas"): 90, ("2026-01", "valor_passagens"): 9000,
            ("2026-01", "protocolos_respondidos"): 30, ("2026-01", "manutencoes_lote"): 300,
            ("2026-01", "Visitas a processos"): 3, ("2026-02", "cestas_compradas"): 4000,
            ("2026-02", "processos_respondidos"): 55}


def test_reimporta_o_excel_e_o_pdf_gerados_pelo_sistema(tmp_path):
    base, quadro = _quadro_exemplo(tmp_path)
    xlsx = relatorio_anual.gerar_excel_anual(quadro, "2026", pd.DataFrame(), pd.DataFrame(), base)
    r = importador_anual.importar_arquivo(xlsx, "monitoramento_anual_dibes_2026.xlsx")
    assert _valores(r) == ESPERADO and not r.avisos  # linhas calculadas ignoradas; 'Outros' não vira SEI
    pdf = relatorio_anual.gerar_pdf_anual(quadro, "2026", pd.DataFrame(
        {1: [10.0], 2: [12.0], "Total": [22.0]}, index=["SAS NORTE"]).reindex(columns=[*range(1, 13), "Total"]))
    r = importador_anual.importar_arquivo(pdf, "monitoramento_anual_dibes_2026.pdf")
    assert _valores(r) == ESPERADO, r.avisos  # sem rodapé nem tabela de cestas por SAS


def test_modelo_preenchido(tmp_path):
    modelo = pd.read_excel(io.BytesIO(importador_anual.modelo_excel("2026")))
    modelo.loc[modelo["Indicador"] == "Cestas compradas", "Mar"] = 6000
    modelo.loc[modelo["Indicador"] == "Passagens não utilizadas", "Mar"] = 7
    modelo.loc[modelo["Indicador"] == "(nome da atividade)", ["Indicador", "Mar"]] = ["Capacitações", 2]
    arquivo = tmp_path / "modelo_2026.xlsx"
    modelo.to_excel(arquivo, index=False)
    r = importador_anual.importar_arquivo(arquivo.read_bytes(), arquivo.name)
    assert _valores(r) == {("2026-03", "cestas_compradas"): 6000, ("2026-03", "passagens_nao_utilizadas"): 7,
                           ("2026-03", "Capacitações"): 2}


def test_formulario_de_um_mes_e_lista_e_meses_nas_linhas():
    formulario = ("Relatório de atividades - Abril/2026\n"
                  "BENEFÍCIO EVENTUAL PASSAGENS;\nN.º de solicitações;40\nValor gasto;R$ 1.234,56\n"
                  "SIGRC;\nN.º de protocolos respondidos;18\n")
    r = importador_anual.importar_arquivo(formulario.encode(), "atividades.csv", "2026", "2026-01")
    assert _valores(r) == {("2026-04", "solicitacoes"): 40, ("2026-04", "valor_passagens"): 1234.56,
                           ("2026-04", "protocolos_respondidos"): 18}

    lista = "Mês;Indicador;Valor\nmai/2026;Cestas compradas;100\nmai/2026;Processos SEI respondidos;7\n"
    r = importador_anual.importar_arquivo(lista.encode(), "lista.csv")
    assert _valores(r) == {("2026-05", "cestas_compradas"): 100, ("2026-05", "processos_respondidos"): 7}

    linhas = "Mês;Manutenções em lote;Manutenções manuais\n06/2026;300;12\n07/2026;280;9\n"
    r = importador_anual.importar_arquivo(linhas.encode(), "pbf.csv")
    assert _valores(r) == {("2026-06", "manutencoes_lote"): 300, ("2026-06", "manutencoes_manuais"): 12,
                           ("2026-07", "manutencoes_lote"): 280, ("2026-07", "manutencoes_manuais"): 9}


def test_mes_sem_lancamentos_nao_quebra_filtros():
    vazio = pd.DataFrame(columns=["mes", "atividade", "indicador", "valor"])
    sistema = pd.DataFrame({"mes": ["2026-01"], "atividade": [A], "indicador": ["cestas_concedidas_sas"],
                            "valor": [10.0]})
    base = anual.lancamentos(vazio, sistema)
    assert list(base.columns) == ["mes", "atividade", "indicador", "valor"] and len(base) == 1
