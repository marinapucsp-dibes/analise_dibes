"""Relatório mensal em PDF, pronto para imprimir (A4 paisagem)."""

from __future__ import annotations

import io
from datetime import datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import A4, landscape  # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import cm  # noqa: E402
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate,  # noqa: E402
                                Spacer, Table, TableStyle)

from . import analise  # noqa: E402
from .config import CAMPOS, MESES_PT, rotulo_mes  # noqa: E402
from .graficos import COR_CAMPO, COR_TIPO  # noqa: E402

TINTA = colors.HexColor("#0b0b0b")
TINTA_2 = colors.HexColor("#52514e")
LINHA = colors.HexColor("#c3c2b7")
FUNDO_CAB = colors.HexColor("#e9f1fb")
FUNDO_TOTAL = colors.HexColor("#f0efec")
ROTULO_CURTO = {
    "cota_disponivel": "Cota\nDisponível", "quantidade_solicitada": "Quantidade\nSolicitada",
    "demanda_registrada": "Demanda\nRegistrada", "atendimento_social": "Atendimento\nSocial",
    "recibos_emitidos": "Recibos\nEmitidos", "cestas_concedidas": "Cestas\nConcedidas",
}

estilos = getSampleStyleSheet()
TITULO = ParagraphStyle("titulo", parent=estilos["Title"], fontSize=18, leading=22, alignment=0, spaceAfter=2)
SUBTITULO = ParagraphStyle("sub", parent=estilos["Normal"], fontSize=11, textColor=TINTA_2, spaceAfter=10)
SECAO = ParagraphStyle("secao", parent=estilos["Heading2"], fontSize=13, spaceBefore=10, spaceAfter=6)
TEXTO = ParagraphStyle("texto", parent=estilos["Normal"], fontSize=9, leading=12)
CELULA = ParagraphStyle("celula", parent=TEXTO, fontSize=8, leading=10)


# ------------------------------------------------------------------ formatação

def num(v, casas: int = 0, sufixo: str = "") -> str:
    if v is None or pd.isna(v):
        return "—"
    return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".") + sufixo


def var(atual, anterior) -> str:
    v = analise.variacao(atual, anterior)
    return "—" if v is None else num(v, 1, "%").replace("-", "−") if v < 0 else "+" + num(v, 1, "%")


def mes_extenso(mes: str) -> str:
    ano, m = mes.split("-")
    return f"{MESES_PT[int(m) - 1]} de {ano}"


def tabela(dados: list[list], larguras: list[float], linhas_total: tuple[int, ...] = ()) -> Table:
    t = Table(dados, colWidths=larguras, repeatRows=1)
    estilo = [
        ("FONT", (0, 0), (-1, -1), "Helvetica", 8.5),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8),
        ("TEXTCOLOR", (0, 0), (-1, -1), TINTA),
        ("BACKGROUND", (0, 0), (-1, 0), FUNDO_CAB),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, LINHA),
        ("LINEBELOW", (0, 1), (-1, -1), 0.3, LINHA),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    for i in linhas_total:
        estilo += [("BACKGROUND", (0, i), (-1, i), FUNDO_TOTAL), ("FONT", (0, i), (-1, i), "Helvetica-Bold", 8.5)]
    t.setStyle(TableStyle(estilo))
    return t


# --------------------------------------------------------------------- gráficos

def _figura(fig) -> Image:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    largura_pt, altura_pt = fig.get_size_inches() * 72
    return Image(buf, width=largura_pt, height=altura_pt)


def _eixos(ax):
    for lado in ("top", "right", "left"):
        ax.spines[lado].set_visible(False)
    ax.spines["bottom"].set_color("#c3c2b7")
    ax.tick_params(colors="#52514e", labelsize=8, length=0)
    ax.yaxis.grid(True, color="#e1e0d9", linewidth=0.6)
    ax.set_axisbelow(True)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: num(v)))


def grafico_unidades(df_mes: pd.DataFrame) -> Image:
    campos = ["cota_disponivel", "demanda_registrada", "cestas_concedidas"]
    d = df_mes.sort_values(["tipo", "unidade"])
    fig, ax = plt.subplots(figsize=(10.5, 3.3))
    largura = 0.8 / len(campos)
    x = range(len(d))
    for i, c in enumerate(campos):
        ax.bar([p + (i - 1) * largura for p in x], d[c], width=largura * 0.92, color=COR_CAMPO[c], label=CAMPOS[c])
    ax.set_xticks(list(x), d["unidade"], fontsize=8)
    _eixos(ax)
    ax.legend(frameon=False, fontsize=8, ncol=3, loc="upper left", bbox_to_anchor=(0, 1.15))
    return _figura(fig)


def grafico_evolucao(total: pd.DataFrame) -> Image:
    campos = ["cota_disponivel", "demanda_registrada", "quantidade_solicitada", "cestas_concedidas"]
    fig, ax = plt.subplots(figsize=(10.5, 2.7))
    rotulos = [rotulo_mes(m) for m in total["mes"]]
    for c in campos:
        ax.plot(rotulos, total[c], color=COR_CAMPO[c], linewidth=2, marker="o", markersize=4, label=CAMPOS[c])
    _eixos(ax)
    ax.legend(frameon=False, fontsize=8, ncol=4, loc="upper left", bbox_to_anchor=(0, 1.18))
    return _figura(fig)


def grafico_tipos(tipos: pd.DataFrame) -> Image:
    fig, ax = plt.subplots(figsize=(10.5, 2.2))
    meses = sorted(tipos["mes"].unique())
    base = pd.Series(0.0, index=meses)
    for tipo in ["CRAS", "CREAS"]:
        valores = tipos[tipos["tipo"] == tipo].set_index("mes")["cestas_concedidas"].reindex(meses).fillna(0)
        ax.bar([rotulo_mes(m) for m in meses], valores, bottom=base, color=COR_TIPO[tipo], label=tipo,
               width=0.6, edgecolor="white", linewidth=1)
        base += valores
    _eixos(ax)
    ax.legend(frameon=False, fontsize=8, ncol=2, loc="upper left", bbox_to_anchor=(0, 1.2))
    return _figura(fig)


# -------------------------------------------------------------------- relatório

def gerar_pdf(df: pd.DataFrame, mes: str, meses_historico: int = 12) -> bytes:
    """Relatório do mês escolhido, com comparação ao mês anterior e evolução recente."""
    df = df[df["mes"] <= mes]
    meses = sorted(df["mes"].unique())
    anterior = analise.mes_anterior(meses, mes)
    df_mes = analise.por_unidade(df[df["mes"] == mes])
    total = analise.total_sas(df)
    tipos = analise.por_tipo(df)
    t_mes = total[total["mes"] == mes].iloc[0]
    t_ant = total[total["mes"] == anterior].iloc[0] if anterior else None

    corpo = [
        Paragraph("Relatório Mensal — Concessão de Cestas Básicas", TITULO),
        Paragraph(f"Secretaria de Assistência Social · Total SAS, CRAS e CREAS · <b>{mes_extenso(mes)}</b>", SUBTITULO),
    ]

    # 1. Resumo Total SAS
    corpo.append(Paragraph("1. Resumo do mês — Total SAS", SECAO))
    cab = ["Campo", rotulo_mes(mes)] + ([rotulo_mes(anterior), "Variação"] if anterior else [])
    linhas = [cab]
    for c, rotulo in CAMPOS.items():
        linha = [rotulo, num(t_mes[c])]
        if anterior:
            linha += [num(t_ant[c]), var(t_mes[c], t_ant[c])]
        linhas.append(linha)
    resumo = tabela(linhas, [5.5 * cm, 3 * cm] + ([3 * cm, 3 * cm] if anterior else []))

    ind = [["Indicador", "Total SAS", "CRAS", "CREAS"]]
    tipos_mes = tipos[tipos["mes"] == mes].set_index("tipo")
    for chave, rotulo in analise.INDICADORES.items():
        pct = "%" in rotulo
        valores = [t_mes[chave]] + [tipos_mes[chave].get(t) if t in tipos_mes.index else None for t in ("CRAS", "CREAS")]
        ind.append([rotulo.replace(" (%)", ""), *[num(v, 1 if pct else 0, "%" if pct else "") for v in valores]])
    indicadores = tabela(ind, [5.5 * cm, 2.6 * cm, 2.6 * cm, 2.6 * cm])
    corpo.append(Table([[resumo, indicadores]], colWidths=[15 * cm, 13.5 * cm],
                       style=[("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    corpo.append(Paragraph(
        f"No mês foram concedidas <b>{num(t_mes['cestas_concedidas'])}</b> cestas para uma cota de "
        f"<b>{num(t_mes['cota_disponivel'])}</b> ({num(t_mes['uso_cota'], 1, '%')} de uso) e uma demanda registrada de "
        f"<b>{num(t_mes['demanda_registrada'])}</b> ({num(t_mes['atendimento_demanda'], 1, '%')} atendida). "
        f"Unidades informantes: {int(t_mes['unidades'])}.", ParagraphStyle("p", parent=TEXTO, spaceBefore=8)))

    # 2. Por unidade
    corpo.append(Paragraph(f"2. CRAS e CREAS — {rotulo_mes(mes)}", SECAO))
    cab = ["Unidade", *[ROTULO_CURTO[c] for c in CAMPOS], "Uso da\ncota", "Atend. da\ndemanda"]
    linhas, totais = [cab], []

    def linha_de(nome, r):
        return [nome, *[num(r[c]) for c in CAMPOS], num(r["uso_cota"], 1, "%"), num(r["atendimento_demanda"], 1, "%")]

    for tipo in ["CRAS", "CREAS"]:
        parte = df_mes[df_mes["tipo"] == tipo].sort_values("unidade")
        if parte.empty:
            continue
        for _, r in parte.iterrows():
            linhas.append(linha_de(r["unidade"], r))
        linhas.append(linha_de(f"Total {tipo}", tipos_mes.loc[tipo]))
        totais.append(len(linhas) - 1)
    linhas.append(linha_de("Total SAS", t_mes))
    totais.append(len(linhas) - 1)
    corpo.append(tabela(linhas, [6 * cm] + [2.55 * cm] * 6 + [2.2 * cm, 2.2 * cm], tuple(totais)))
    corpo.append(Spacer(1, 8))
    corpo.append(KeepTogether([Paragraph("Cota × Demanda × Cestas concedidas por unidade", TEXTO),
                               grafico_unidades(df_mes)]))

    # 3. Evolução
    recentes = meses[-meses_historico:]
    if len(recentes) > 1:
        corpo.append(PageBreak())
        corpo.append(Paragraph(f"3. Evolução mensal — {rotulo_mes(recentes[0])} a {rotulo_mes(recentes[-1])}", SECAO))
        t_rec = total[total["mes"].isin(recentes)]
        corpo.append(Paragraph("Total SAS", TEXTO))
        corpo.append(grafico_evolucao(t_rec))
        corpo.append(Paragraph("Cestas concedidas — CRAS e CREAS", TEXTO))
        corpo.append(grafico_tipos(tipos[tipos["mes"].isin(recentes)]))
        cab = ["Mês", *[ROTULO_CURTO[c] for c in CAMPOS], "Uso da\ncota"]
        linhas = [cab] + [[rotulo_mes(r["mes"]), *[num(r[c]) for c in CAMPOS], num(r["uso_cota"], 1, "%")]
                          for _, r in t_rec.iterrows()]
        corpo.append(KeepTogether([Spacer(1, 6), Paragraph("Total SAS mês a mês", TEXTO),
                                   tabela(linhas, [3 * cm] + [2.8 * cm] * 6 + [2.4 * cm])]))

    # 4. Alertas
    alertas = analise.alertas(df, mes)
    corpo.append(Paragraph(f"{4 if len(recentes) > 1 else 3}. Alertas de conferência", SECAO))
    if alertas.empty:
        corpo.append(Paragraph("Nenhuma inconsistência encontrada no mês.", TEXTO))
    else:
        linhas = [["Gravidade", "Unidade", "Regra", "Detalhe"]] + [
            [a.Gravidade, Paragraph(a.Unidade, CELULA), Paragraph(a.Regra, CELULA), Paragraph(a.Detalhe, CELULA)]
            for a in alertas.itertuples(index=False)]
        t = tabela(linhas, [2.5 * cm, 4.5 * cm, 7 * cm, 13.5 * cm])
        t.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "LEFT")]))
        corpo.append(t)

    emitido = datetime.now().strftime("%d/%m/%Y %H:%M")

    def rodape(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(TINTA_2)
        canvas.drawString(1.5 * cm, 1 * cm, f"Concessão de Cestas Básicas · {mes_extenso(mes)} · emitido em {emitido}")
        canvas.drawRightString(landscape(A4)[0] - 1.5 * cm, 1 * cm, f"Página {doc.page}")
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=1.5 * cm, rightMargin=1.5 * cm,
                            topMargin=1.3 * cm, bottomMargin=1.6 * cm,
                            title=f"Cestas Básicas - {rotulo_mes(mes)}", author="Secretaria de Assistência Social")
    doc.build(corpo, onFirstPage=rodape, onLaterPages=rodape)
    return buf.getvalue()
