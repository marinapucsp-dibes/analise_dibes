"""Exportação do relatório consolidado em Excel."""

from __future__ import annotations

import io

import pandas as pd

from . import analise
from .config import CAMPOS, rotulo_mes

ROTULOS = {"mes": "Mês", "unidade": "Unidade", "tipo": "Tipo", "unidades": "Nº de unidades",
           **CAMPOS, **analise.INDICADORES}


def _formatar(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    if "mes" in d:
        d["mes"] = d["mes"].map(rotulo_mes)
    for c in ("uso_cota", "atendimento_demanda", "atendimento_solicitacao"):
        if c in d:
            d[c] = d[c].round(1)
    return d.rename(columns=ROTULOS)


def gerar_excel(df: pd.DataFrame) -> bytes:
    meses = sorted(df["mes"].unique())
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xl:
        _formatar(analise.total_sas(df)).to_excel(xl, sheet_name="Total SAS", index=False)
        _formatar(analise.por_tipo(df)).to_excel(xl, sheet_name="CRAS x CREAS", index=False)
        colunas = ["mes", "tipo", "unidade", *CAMPOS, *analise.INDICADORES]
        _formatar(analise.por_unidade(df)[colunas]).to_excel(xl, sheet_name="Por unidade", index=False)
        alertas = [analise.alertas(df, m).assign(**{"Mês": rotulo_mes(m)}) for m in meses]
        if alertas:
            todos = pd.concat(alertas, ignore_index=True)
            todos[["Mês", *todos.columns[:-1]]].to_excel(xl, sheet_name="Alertas", index=False)
        for aba in xl.sheets.values():
            for coluna in aba.columns:
                largura = max(len(str(c.value or "")) for c in coluna)
                aba.column_dimensions[coluna[0].column_letter].width = min(max(10, largura + 2), 60)
            aba.freeze_panes = "A2"
    return buf.getvalue()
