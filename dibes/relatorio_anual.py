"""Relatórios do Monitoramento Anual DIBES: Excel e PDF (A4 paisagem)."""

from __future__ import annotations

import io
from datetime import datetime

import pandas as pd
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer

from . import anual
from .relatorio_pdf import CELULA, SECAO, SUBTITULO, TEXTO, TINTA_2, TITULO, num, tabela

FORMATO_EXCEL = {"n": "#,##0", "R$": '"R$" #,##0.00', "%": '0.0"%"'}


def valor_texto(v, unidade: str) -> str:
    if v is None or pd.isna(v):
        return "—"
    if unidade == "R$":
        return "R$ " + num(v, 2)
    if unidade == "%":
        return num(v, 1, "%")
    if unidade == "n2":
        return num(v, 2)
    return num(v)


def gerar_excel_anual(quadro: pd.DataFrame, ano: str, por_sas: pd.DataFrame, por_unidade: pd.DataFrame,
                      lancamentos: pd.DataFrame) -> bytes:
    meses = anual.MESES_COLUNAS
    q = quadro.rename(columns={i + 1: m for i, m in enumerate(meses)})
    q = q.rename(columns={"atividade": "Atividade", "indicador": "Indicador"})
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xl:
        q[["Atividade", "Indicador", *meses, "Total"]].to_excel(xl, sheet_name="Quadro anual", index=False)
        aba = xl.sheets["Quadro anual"]
        for linha, unidade in enumerate(quadro["unidade"], start=2):
            for col in range(3, 3 + len(meses) + 1):
                aba.cell(row=linha, column=col).number_format = FORMATO_EXCEL.get(unidade, "#,##0")
        if not por_sas.empty:
            por_sas.rename(columns={i + 1: m for i, m in enumerate(meses)}).reset_index() \
                .rename(columns={"sas": "SAS"}).to_excel(xl, sheet_name="Cestas por SAS", index=False)
        if not por_unidade.empty:
            por_unidade.rename(columns={i + 1: m for i, m in enumerate(meses)}) \
                .rename(columns={"sas": "SAS", "unidade": "Unidade", "tipo": "Tipo"}) \
                .to_excel(xl, sheet_name="Cestas por unidade", index=False)
        lanc = lancamentos[lancamentos["mes"].str.startswith(ano)].copy()
        lanc["indicador"] = lanc["indicador"].map(lambda i: anual.ROTULO.get(i, i))
        lanc.rename(columns={"mes": "Mês", "atividade": "Atividade", "indicador": "Indicador", "valor": "Valor"}) \
            [["Mês", "Atividade", "Indicador", "Valor"]].sort_values(["Mês", "Atividade"]) \
            .to_excel(xl, sheet_name="Lançamentos", index=False)
        for aba in xl.sheets.values():
            for coluna in aba.columns:
                largura = max(len(str(c.value or "")) for c in coluna)
                aba.column_dimensions[coluna[0].column_letter].width = min(max(9, largura + 2), 55)
            aba.freeze_panes = "C2" if aba.title == "Quadro anual" else "A2"
    return buf.getvalue()


def gerar_pdf_anual(quadro: pd.DataFrame, ano: str, por_sas: pd.DataFrame) -> bytes:
    meses = anual.MESES_COLUNAS
    larguras = [5.2 * cm] + [1.6 * cm] * 12 + [2.2 * cm]
    corpo = [Paragraph(f"Monitoramento Anual DIBES — {ano}", TITULO),
             Paragraph("Atividades lançadas mês a mês · Benefícios Eventuais, SIGRC, SEI, PBF e outras ações",
                       SUBTITULO)]
    for atividade in [*anual.CATALOGO, anual.OUTROS]:
        parte = quadro[quadro["atividade"] == atividade]
        if parte.empty:
            continue
        linhas = [["Indicador", *meses, "Total"]]
        destaque = []
        for _, r in parte.iterrows():
            # em R$, a unidade vai no nome do indicador para o valor caber na coluna do mês
            rotulo = r["indicador"] + (" (R$)" if r["unidade"] == "R$" else "")
            nome = Paragraph(("<i>%s</i>" if r["calculado"] else "%s") % rotulo, CELULA)
            unidade = "n2" if r["unidade"] == "R$" else r["unidade"]
            linhas.append([nome, *[valor_texto(r[m], unidade) for m in range(1, 13)],
                           valor_texto(r["Total"], unidade)])
            if r["calculado"]:
                destaque.append(len(linhas) - 1)
        t = tabela(linhas, larguras, tuple(destaque))
        t.setStyle([("FONTSIZE", (0, 0), (-1, -1), 7), ("FONT", (-1, 1), (-1, -1), "Helvetica-Bold", 7)])
        corpo.append(KeepTogether([Paragraph(atividade, SECAO), t, Spacer(1, 4)]))
    corpo.append(Paragraph("Linhas em itálico e destacadas são calculadas a partir dos valores lançados. As cestas "
                           "concedidas pelas SAS/unidades e em emergências vêm do sistema de Cestas Básicas.",
                           TEXTO))
    if not por_sas.empty:
        corpo.append(PageBreak())
        corpo.append(Paragraph(f"Cestas concedidas por SAS — {ano}", SECAO))
        linhas = [["SAS", *meses, "Total"]]
        for sas, r in por_sas.iterrows():
            linhas.append([Paragraph(sas, CELULA), *[num(r[m]) for m in range(1, 13)], num(r["Total"])])
        totais = por_sas.sum(min_count=1)
        linhas.append(["Total", *[num(totais[m]) for m in range(1, 13)], num(totais["Total"])])
        t = tabela(linhas, larguras, (len(linhas) - 1,))
        t.setStyle([("FONTSIZE", (0, 0), (-1, -1), 7)])
        corpo.append(t)

    emitido = datetime.now().strftime("%d/%m/%Y %H:%M")

    def rodape(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(TINTA_2)
        canvas.drawString(1.5 * cm, 1 * cm, f"Monitoramento Anual DIBES · {ano} · emitido em {emitido}")
        canvas.drawRightString(landscape(A4)[0] - 1.5 * cm, 1 * cm, f"Página {doc.page}")
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                            topMargin=1.3 * cm, bottomMargin=1.6 * cm, title=f"Monitoramento Anual DIBES {ano}")
    doc.build(corpo, onFirstPage=rodape, onLaterPages=rodape)
    return buf.getvalue()
