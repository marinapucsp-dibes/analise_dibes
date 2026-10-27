"""Monitoramento Anual DIBES: atividades lançadas mês a mês e consolidação do ano.

As cestas concedidas pelas SAS/unidades e em emergências vêm do sistema de cestas (mesmo banco).
Para meses que não estão lá, podem ser digitadas no lançamento do mês.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import analise
from .config import MESES_ABREV

ALIMENTACAO = "Benefício Eventual Alimentação"
PASSAGENS = "Benefício Eventual Passagens"
SIGRC = "SIGRC"
SEI = "SEI"
PBF = "Programa Bolsa Família (PBF)"
OUTROS = "Outros"

# atividade -> [(indicador, rótulo, unidade)]; unidade "R$" = valor em reais
CATALOGO: dict[str, list[tuple[str, str, str]]] = {
    ALIMENTACAO: [
        ("cestas_concedidas_sas", "Cestas concedidas (SAS/unidades)", "n"),
        ("cestas_emergencias", "Cestas concedidas em emergências", "n"),
        ("cestas_compradas", "Cestas compradas", "n"),
        ("valor_cestas", "Valor gasto com cestas", "R$"),
    ],
    PASSAGENS: [
        ("solicitacoes", "Solicitações", "n"),
        ("solicitacoes_atendidas", "Solicitações atendidas", "n"),
        ("pessoas_beneficiadas", "Pessoas beneficiadas", "n"),
        ("passagens_compradas", "Passagens compradas", "n"),
        ("passagens_nao_utilizadas", "Passagens não utilizadas", "n"),
        ("valor_passagens", "Valor gasto com passagens", "R$"),
    ],
    SIGRC: [("protocolos_respondidos", "Protocolos respondidos", "n")],
    SEI: [("processos_respondidos", "Processos SEI respondidos", "n")],
    PBF: [
        ("manutencoes_lote", "Manutenções realizadas em lote", "n"),
        ("manutencoes_manuais", "Manutenções realizadas manualmente", "n"),
    ],
}
# vêm do sistema de cestas; só são digitadas para meses que não estão lá
AUTOMATICOS = {"cestas_concedidas_sas", "cestas_emergencias"}

ROTULO = {ind: rot for itens in CATALOGO.values() for ind, rot, _ in itens}
UNIDADE = {ind: u for itens in CATALOGO.values() for ind, _, u in itens}
ATIVIDADE_DO = {ind: atv for atv, itens in CATALOGO.items() for ind, _, _ in itens}

# indicadores calculados: (rótulo, numerador, denominador, tipo) — tipo "%" ou "R$"
DERIVADOS = {
    ALIMENTACAO: [("Total de cestas concedidas", ("cestas_concedidas_sas", "cestas_emergencias"), None, "n"),
                  ("Custo médio por cesta comprada", "valor_cestas", "cestas_compradas", "R$")],
    PASSAGENS: [("Taxa de atendimento das solicitações", "solicitacoes_atendidas", "solicitacoes", "%"),
                ("Passagens não utilizadas (% das compradas)", "passagens_nao_utilizadas", "passagens_compradas", "%"),
                ("Custo médio por passagem", "valor_passagens", "passagens_compradas", "R$"),
                ("Custo médio por pessoa beneficiada", "valor_passagens", "pessoas_beneficiadas", "R$")],
    PBF: [("Total de manutenções", ("manutencoes_lote", "manutencoes_manuais"), None, "n")],
}

MESES_COLUNAS = [m.capitalize() for m in MESES_ABREV]


def cestas_do_sistema(registros: pd.DataFrame, emergencias: pd.DataFrame) -> pd.DataFrame:
    """Cestas concedidas (Total Geral das SAS) e em emergências, por mês, a partir do sistema de cestas."""
    partes = []
    if not registros.empty:
        t = analise.total_geral(registros)[["mes", "cestas_concedidas"]]
        partes.append(t.rename(columns={"cestas_concedidas": "valor"}).assign(indicador="cestas_concedidas_sas"))
    if not emergencias.empty:
        e = analise.emergencias_por_mes(emergencias)[["mes", "cestas"]]
        partes.append(e.rename(columns={"cestas": "valor"}).assign(indicador="cestas_emergencias"))
    if not partes:
        return pd.DataFrame(columns=["mes", "atividade", "indicador", "valor"])
    return pd.concat(partes, ignore_index=True).assign(atividade=ALIMENTACAO)


def lancamentos(atividades: pd.DataFrame, sistema: pd.DataFrame) -> pd.DataFrame:
    """Todos os valores por mês: o sistema de cestas prevalece sobre o que foi digitado para o mesmo mês."""
    digitado = atividades[["mes", "atividade", "indicador", "valor"]].copy()
    if not sistema.empty:
        chave_sis = set(zip(sistema["mes"], sistema["indicador"]))
        digitado = digitado[[(m, i) not in chave_sis for m, i in zip(digitado["mes"], digitado["indicador"])]]
        digitado = pd.concat([digitado, sistema[["mes", "atividade", "indicador", "valor"]]], ignore_index=True)
    return digitado


def _por_mes(base: pd.DataFrame, ano: str) -> pd.DataFrame:
    """Linhas = (atividade, indicador), colunas = 1..12 (meses do ano)."""
    d = base[base["mes"].str.startswith(ano)].copy()
    d["num_mes"] = d["mes"].str[5:7].astype(int)
    tabela = d.pivot_table(index=["atividade", "indicador"], columns="num_mes", values="valor", aggfunc="sum")
    return tabela.reindex(columns=range(1, 13))


def _soma(linhas: pd.DataFrame, chaves) -> pd.Series:
    chaves = (chaves,) if isinstance(chaves, str) else chaves
    presentes = [linhas.loc[k] for k in chaves if k in linhas.index]
    if not presentes:
        return pd.Series(np.nan, index=list(range(1, 13)) + ["Total"])
    return pd.concat(presentes, axis=1).sum(axis=1, min_count=1)


def quadro_anual(base: pd.DataFrame, ano: str) -> pd.DataFrame:
    """Quadro do ano: uma linha por indicador (com Total) e os indicadores calculados de cada atividade.

    Colunas: atividade, indicador (rótulo), unidade, 1..12, Total."""
    tabela = _por_mes(base, ano)
    linhas = []
    atividades_ordem = [*CATALOGO, OUTROS]
    for atividade in atividades_ordem:
        if atividade == OUTROS:
            itens = sorted(i for a, i in tabela.index if a == OUTROS)
            fixos = [(i, i, "n") for i in itens]
        else:
            fixos = CATALOGO[atividade]
        valores = {}
        for indicador, rotulo, unidade in fixos:
            serie = tabela.loc[(atividade, indicador)] if (atividade, indicador) in tabela.index else \
                pd.Series(np.nan, index=range(1, 13))
            serie = serie.copy()
            serie["Total"] = serie.sum(min_count=1)
            valores[indicador] = serie
            linhas.append({"atividade": atividade, "indicador": rotulo, "unidade": unidade, "calculado": False,
                           **serie.to_dict()})
        quadro_atv = pd.DataFrame(valores).T
        for rotulo, num, den, tipo in DERIVADOS.get(atividade, []):
            numerador = _soma(quadro_atv, num)
            if den is None:
                serie = numerador
            else:
                denominador = _soma(quadro_atv, den)
                with np.errstate(divide="ignore", invalid="ignore"):
                    serie = numerador / denominador.where(denominador > 0)
                if tipo == "%":
                    serie = serie * 100
            linhas.append({"atividade": atividade, "indicador": rotulo, "unidade": tipo, "calculado": True,
                           **serie.to_dict()})
    quadro = pd.DataFrame(linhas)
    return quadro.reindex(columns=["atividade", "indicador", "unidade", "calculado", *range(1, 13), "Total"])


def meses_lancados(atividades: pd.DataFrame, ano: str) -> dict[int, int]:
    """Quantos indicadores foram digitados em cada mês do ano (para mostrar o que falta lançar)."""
    d = atividades[atividades["mes"].str.startswith(ano)]
    return d.groupby(d["mes"].str[5:7].astype(int))["indicador"].count().to_dict()


def cestas_por_sas_no_ano(registros: pd.DataFrame, ano: str) -> pd.DataFrame:
    """Cestas concedidas por SAS × mês do ano (com Total)."""
    d = registros[registros["mes"].str.startswith(ano)]
    if d.empty or not analise.tem_sas(d):
        return pd.DataFrame()
    s = analise.por_sas(d)
    s["num_mes"] = s["mes"].str[5:7].astype(int)
    tabela = s.pivot_table(index="sas", columns="num_mes", values="cestas_concedidas", aggfunc="sum")
    tabela = tabela.reindex(columns=range(1, 13))
    tabela["Total"] = tabela.sum(axis=1, min_count=1)
    return tabela


def cestas_por_unidade_no_ano(registros: pd.DataFrame, ano: str) -> pd.DataFrame:
    """Cestas concedidas por unidade × mês do ano (com SAS, tipo e Total)."""
    d = registros[registros["mes"].str.startswith(ano)]
    if d.empty:
        return pd.DataFrame()
    u = analise.unidades(d)
    u["num_mes"] = u["mes"].str[5:7].astype(int)
    tabela = u.pivot_table(index=["sas", "unidade", "tipo"], columns="num_mes", values="cestas_concedidas",
                           aggfunc="sum").reindex(columns=range(1, 13))
    tabela["Total"] = tabela.sum(axis=1, min_count=1)
    return tabela.reset_index()
