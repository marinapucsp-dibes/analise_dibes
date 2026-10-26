"""Cálculos: totais (geral, por SAS, por tipo, por unidade), indicadores e alertas.

Os registros têm dois níveis:
- linhas de SAS (tipo "SAS"), quando o arquivo traz o total de cada Supervisão;
- linhas de unidades (CRAS, CREAS, Centro POP...), cada uma com a sua SAS.
Quando a SAS veio informada no arquivo, os totais usam esse valor (ele pode incluir cotas
ainda não distribuídas às unidades); senão, somam as unidades.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd

from .config import CAMPOS, SEM_SAS, rotulo_mes

CAMPOS_L = list(CAMPOS)

INDICADORES = {
    "uso_cota": "Uso da cota (%)",
    "atendimento_demanda": "Concessão sobre a demanda (%)",
    "atendimento_tecnico": "Atendimento técnico sobre a demanda (%)",
    "saldo_cota": "Saldo da cota",
    "demanda_reprimida": "Demanda reprimida",
    "recibos_sem_atendimento": "Recibos sem registro de atendimento",
    "cestas_sem_recibo": "Cestas sem recibo",
}
PERCENTUAIS = {k for k, v in INDICADORES.items() if "%" in v}


def _div(a, b):
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(b > 0, a / b * 100, np.nan)


def com_indicadores(df: pd.DataFrame) -> pd.DataFrame:
    """Acrescenta as colunas de indicadores a uma tabela com os seis campos."""
    d = df.copy()
    d["uso_cota"] = _div(d["cestas_concedidas"], d["cota_disponivel"])
    d["atendimento_demanda"] = _div(d["cestas_concedidas"], d["demanda_registrada"])
    d["atendimento_tecnico"] = _div(d["atendimento_social"], d["demanda_registrada"])
    d["saldo_cota"] = d["cota_disponivel"] - d["cestas_concedidas"]
    d["demanda_reprimida"] = (d["demanda_registrada"] - d["cestas_concedidas"]).clip(lower=0)
    d["recibos_sem_atendimento"] = (d["recibos_emitidos"] - d["atendimento_social"]).clip(lower=0)
    d["cestas_sem_recibo"] = (d["cestas_concedidas"] - d["recibos_emitidos"]).clip(lower=0)
    return d


def unidades(df: pd.DataFrame) -> pd.DataFrame:
    """Só as unidades (sem as linhas de total das SAS), com a SAS preenchida."""
    u = df[df["tipo"] != "SAS"].copy()
    u["sas"] = u["sas"].fillna(SEM_SAS).replace("", SEM_SAS)
    return u


def tem_sas(df: pd.DataFrame) -> bool:
    """Indica se há informação de SAS (linhas de SAS ou unidades com SAS)."""
    return (df["tipo"] == "SAS").any() or (unidades(df)["sas"] != SEM_SAS).any()


def _por_sas_bruto(df: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por mês e SAS: o valor informado da SAS ou, na falta, a soma das unidades."""
    informadas = df[df["tipo"] == "SAS"].assign(sas=lambda d: d["unidade"])
    informadas = informadas.groupby(["mes", "sas"], as_index=False)[CAMPOS_L].sum(min_count=1)
    u = unidades(df)
    somadas = u.groupby(["mes", "sas"], as_index=False)[CAMPOS_L].sum(min_count=1)
    chave = set(zip(informadas["mes"], informadas["sas"]))
    faltantes = somadas[[(m, s) not in chave for m, s in zip(somadas["mes"], somadas["sas"])]]
    return pd.concat([informadas, faltantes], ignore_index=True).sort_values(["mes", "sas"])


def por_sas(df: pd.DataFrame) -> pd.DataFrame:
    t = _por_sas_bruto(df)
    t["unidades"] = t.apply(lambda r: ((df["sas"] == r["sas"]) & (df["mes"] == r["mes"])
                                       & (df["tipo"] != "SAS")).sum(), axis=1) if not t.empty else []
    return com_indicadores(t.reset_index(drop=True))


def total_geral(df: pd.DataFrame) -> pd.DataFrame:
    """Total do município por mês (soma das SAS)."""
    t = _por_sas_bruto(df).groupby("mes", as_index=False)[CAMPOS_L].sum(min_count=1)
    contagem = unidades(df).groupby("mes")["unidade"].nunique()
    t["unidades"] = t["mes"].map(contagem).fillna(0).astype(int)
    return com_indicadores(t)


def por_tipo(df: pd.DataFrame) -> pd.DataFrame:
    """Totais de CRAS, CREAS e demais tipos de unidade por mês."""
    t = unidades(df).groupby(["mes", "tipo"], as_index=False)[CAMPOS_L].sum(min_count=1)
    return com_indicadores(t)


def por_unidade(df: pd.DataFrame) -> pd.DataFrame:
    return com_indicadores(unidades(df))


def variacao(atual: float, anterior: float) -> float | None:
    if anterior is None or pd.isna(anterior) or anterior == 0 or pd.isna(atual):
        return None
    return (atual - anterior) / anterior * 100


def mes_anterior(meses: list[str], mes: str) -> str | None:
    ordenados = sorted(meses)
    i = ordenados.index(mes)
    return ordenados[i - 1] if i > 0 else None


def alertas(df: pd.DataFrame, mes: str, limite_variacao: float = 30.0) -> pd.DataFrame:
    """Regras automáticas de conferência para o mês escolhido (SAS e unidades)."""
    do_mes = df[df["mes"] == mes]
    atual = com_indicadores(pd.concat([do_mes[do_mes["tipo"] == "SAS"], unidades(do_mes)]))
    lista = []

    def add(gravidade, r, regra, detalhe):
        sas = "" if r.tipo == "SAS" else (r.sas if r.sas != SEM_SAS else "")
        lista.append({"Gravidade": gravidade, "Unidade": r.unidade, "Tipo": r.tipo, "SAS": sas,
                      "Regra": regra, "Detalhe": detalhe})

    def ok(*v):
        return all(pd.notna(x) for x in v)

    for r in atual.itertuples(index=False):
        if ok(r.cota_disponivel, r.cestas_concedidas) and r.cota_disponivel > 0 \
                and r.cestas_concedidas > r.cota_disponivel:
            add("Crítico", r, "Concessão acima da cota",
                f"{r.cestas_concedidas:.0f} cestas concedidas para uma cota de {r.cota_disponivel:.0f}.")
        if ok(r.recibos_emitidos, r.cestas_concedidas) and r.recibos_emitidos > r.cestas_concedidas:
            add("Crítico", r, "Mais recibos do que cestas",
                f"{r.recibos_emitidos:.0f} recibos para {r.cestas_concedidas:.0f} cestas (cada recibo tem ao menos 1 cesta).")
        if ok(r.recibos_emitidos, r.atendimento_social) and r.recibos_emitidos > r.atendimento_social:
            add("Atenção", r, "Recibos sem registro de atendimento social",
                f"{r.recibos_emitidos - r.atendimento_social:.0f} recibos a mais que os atendimentos registrados "
                f"({r.recibos_emitidos:.0f} × {r.atendimento_social:.0f}).")
        if ok(r.demanda_registrada, r.cota_disponivel) and r.cota_disponivel > 0 \
                and r.demanda_registrada > r.cota_disponivel:
            add("Atenção", r, "Demanda maior que a cota",
                f"Demanda de {r.demanda_registrada:.0f} para cota de {r.cota_disponivel:.0f} "
                f"(faltam {r.demanda_registrada - r.cota_disponivel:.0f}).")
        if ok(r.cota_disponivel, r.cestas_concedidas) and r.cota_disponivel == 0 and r.cestas_concedidas > 0 \
                and r.tipo != "SAS":
            add("Informativo", r, "Concessões sem cota na unidade",
                f"{r.cestas_concedidas:.0f} cestas concedidas sem cota registrada para a unidade.")
        if ok(r.uso_cota) and r.uso_cota < 50:
            add("Informativo", r, "Baixo uso da cota", f"Apenas {r.uso_cota:.0f}% da cota foi utilizada.")

    # SAS informada × soma das suas unidades
    sas_inf = do_mes[do_mes["tipo"] == "SAS"].set_index("unidade")
    if not sas_inf.empty:
        soma = unidades(do_mes).groupby("sas")[CAMPOS_L].sum()
        for nome, linha in sas_inf.iterrows():
            if nome not in soma.index:
                continue
            dif = [f"{CAMPOS[c]}: SAS {linha[c]:.0f} × unidades {soma.loc[nome, c]:.0f}"
                   for c in CAMPOS_L if pd.notna(linha[c]) and abs(linha[c] - soma.loc[nome, c]) > 0.5]
            if dif:
                add("Informativo", SimpleNamespace(unidade=nome, tipo="SAS", sas=nome),
                    "SAS diferente da soma das unidades", "; ".join(dif) + ".")

    anterior = mes_anterior(df["mes"].unique().tolist(), mes)
    if anterior:
        do_ant = df[df["mes"] == anterior]
        ant = pd.concat([do_ant[do_ant["tipo"] == "SAS"], unidades(do_ant)]).set_index("unidade")
        for r in atual.itertuples(index=False):
            if r.unidade in ant.index:
                v = variacao(r.cestas_concedidas, ant.loc[r.unidade, "cestas_concedidas"])
                if v is not None and abs(v) >= limite_variacao:
                    add("Informativo", r, "Variação forte nas concessões",
                        f"{v:+.0f}% em relação a {rotulo_mes(anterior)}.")
        for nome in sorted(set(ant.index) - set(atual["unidade"])):
            linha = ant.loc[nome]
            add("Atenção", SimpleNamespace(unidade=nome, tipo=linha["tipo"], sas=linha["sas"]),
                "Sem dados no mês", f"Havia dados em {rotulo_mes(anterior)}, mas não em {rotulo_mes(mes)}.")

    ordem = {"Crítico": 0, "Atenção": 1, "Informativo": 2}
    res = pd.DataFrame(lista, columns=["Gravidade", "Unidade", "Tipo", "SAS", "Regra", "Detalhe"])
    return res.sort_values(by="Gravidade", key=lambda s: s.map(ordem), kind="stable").reset_index(drop=True)
