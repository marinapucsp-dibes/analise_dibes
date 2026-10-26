"""Cálculos: totais (SAS, por tipo, por unidade), indicadores e alertas."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import CAMPOS, rotulo_mes

CAMPOS_L = list(CAMPOS)

INDICADORES = {
    "uso_cota": "Uso da cota (%)",
    "atendimento_demanda": "Atendimento da demanda (%)",
    "atendimento_solicitacao": "Atendimento das solicitações (%)",
    "saldo_cota": "Saldo da cota",
    "demanda_reprimida": "Demanda reprimida",
    "recibos_sem_cesta": "Recibos − cestas concedidas",
}


def _div(a, b):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(b > 0, a / b * 100, np.nan)
    return r


def com_indicadores(df: pd.DataFrame) -> pd.DataFrame:
    """Acrescenta as colunas de indicadores a uma tabela com os seis campos."""
    d = df.copy()
    d["uso_cota"] = _div(d["cestas_concedidas"], d["cota_disponivel"])
    d["atendimento_demanda"] = _div(d["cestas_concedidas"], d["demanda_registrada"])
    d["atendimento_solicitacao"] = _div(d["cestas_concedidas"], d["quantidade_solicitada"])
    d["saldo_cota"] = d["cota_disponivel"] - d["cestas_concedidas"]
    d["demanda_reprimida"] = (d["demanda_registrada"] - d["cestas_concedidas"]).clip(lower=0)
    d["recibos_sem_cesta"] = d["recibos_emitidos"] - d["cestas_concedidas"]
    return d


def total_sas(df: pd.DataFrame) -> pd.DataFrame:
    """Total da Secretaria (todas as unidades) por mês."""
    t = df.groupby("mes", as_index=False)[CAMPOS_L].sum(min_count=1)
    t["unidades"] = df.groupby("mes")["unidade"].nunique().values
    return com_indicadores(t)


def por_tipo(df: pd.DataFrame) -> pd.DataFrame:
    """Totais de CRAS e de CREAS por mês."""
    t = df.groupby(["mes", "tipo"], as_index=False)[CAMPOS_L].sum(min_count=1)
    return com_indicadores(t)


def por_unidade(df: pd.DataFrame) -> pd.DataFrame:
    return com_indicadores(df)


def variacao(atual: float, anterior: float) -> float | None:
    if anterior is None or pd.isna(anterior) or anterior == 0 or pd.isna(atual):
        return None
    return (atual - anterior) / anterior * 100


def mes_anterior(meses: list[str], mes: str) -> str | None:
    ordenados = sorted(meses)
    i = ordenados.index(mes)
    return ordenados[i - 1] if i > 0 else None


def alertas(df: pd.DataFrame, mes: str, limite_variacao: float = 30.0) -> pd.DataFrame:
    """Regras automáticas de conferência para o mês escolhido."""
    atual = com_indicadores(df[df["mes"] == mes])
    lista = []

    def add(gravidade, unidade, tipo, regra, detalhe):
        lista.append({"Gravidade": gravidade, "Unidade": unidade, "Tipo": tipo, "Regra": regra, "Detalhe": detalhe})

    for r in atual.itertuples(index=False):
        if pd.notna(r.cota_disponivel) and pd.notna(r.cestas_concedidas) and r.cestas_concedidas > r.cota_disponivel:
            add("Crítico", r.unidade, r.tipo, "Concessão acima da cota",
                f"{r.cestas_concedidas:.0f} cestas concedidas para uma cota de {r.cota_disponivel:.0f}.")
        if pd.notna(r.recibos_emitidos) and pd.notna(r.cestas_concedidas) and r.recibos_emitidos != r.cestas_concedidas:
            add("Atenção", r.unidade, r.tipo, "Recibos diferentes das cestas concedidas",
                f"{r.recibos_emitidos:.0f} recibos para {r.cestas_concedidas:.0f} cestas.")
        if pd.notna(r.demanda_registrada) and pd.notna(r.cota_disponivel) and r.demanda_registrada > r.cota_disponivel:
            add("Atenção", r.unidade, r.tipo, "Demanda maior que a cota",
                f"Demanda de {r.demanda_registrada:.0f} para cota de {r.cota_disponivel:.0f} "
                f"(faltam {r.demanda_registrada - r.cota_disponivel:.0f}).")
        if pd.notna(r.quantidade_solicitada) and pd.notna(r.cestas_concedidas) and \
                r.cestas_concedidas > r.quantidade_solicitada:
            add("Atenção", r.unidade, r.tipo, "Concedidas acima do solicitado",
                f"{r.cestas_concedidas:.0f} concedidas para {r.quantidade_solicitada:.0f} solicitadas.")
        if pd.notna(r.uso_cota) and r.uso_cota < 50:
            add("Informativo", r.unidade, r.tipo, "Baixo uso da cota",
                f"Apenas {r.uso_cota:.0f}% da cota foi utilizada.")

    anterior = mes_anterior(df["mes"].unique().tolist(), mes)
    if anterior:
        ant = df[df["mes"] == anterior].set_index("unidade")
        for r in atual.itertuples(index=False):
            if r.unidade in ant.index:
                v = variacao(r.cestas_concedidas, ant.loc[r.unidade, "cestas_concedidas"])
                if v is not None and abs(v) >= limite_variacao:
                    add("Informativo", r.unidade, r.tipo, "Variação forte nas concessões",
                        f"{v:+.0f}% em relação a {rotulo_mes(anterior)}.")
        for unidade in sorted(set(ant.index) - set(atual["unidade"])):
            add("Atenção", unidade, ant.loc[unidade, "tipo"], "Unidade sem dados no mês",
                f"Havia dados em {rotulo_mes(anterior)}, mas não em {rotulo_mes(mes)}.")

    ordem = {"Crítico": 0, "Atenção": 1, "Informativo": 2}
    res = pd.DataFrame(lista, columns=["Gravidade", "Unidade", "Tipo", "Regra", "Detalhe"])
    return res.sort_values(by="Gravidade", key=lambda s: s.map(ordem), kind="stable").reset_index(drop=True)
