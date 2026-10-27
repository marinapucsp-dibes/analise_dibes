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
