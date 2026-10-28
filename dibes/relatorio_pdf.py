"""Relatório mensal em PDF, pronto para imprimir (A4 paisagem)."""

from __future__ import annotations

import io
import re
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
from .graficos import COR_CAMPO, COR_TIPO, ORDEM_TIPOS  # noqa: E402

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
        ("TOPPADDING", (0, 0), (-1, -1), 3 if len(dados) <= 25 else 1.6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3 if len(dados) <= 25 else 1.6),
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


def nome_curto(sas: str) -> str:
    """'SAS FREGUESIA/BRASILÂNDIA - FB' -> 'FREGUESIA/BRASILÂNDIA'."""
    return re.sub(r"\s+-\s+\S{1,3}$", "", re.sub(r"^SAS\s+", "", str(sas))).strip()


def grafico_barras(nomes: list[str], dados: pd.DataFrame) -> Image:
    """Cota × Demanda × Cestas concedidas, um grupo de barras por SAS ou unidade."""
    campos = ["cota_disponivel", "demanda_registrada", "cestas_concedidas"]
    fig, ax = plt.subplots(figsize=(10.5, 3.4))
    largura = 0.8 / len(campos)
    x = range(len(nomes))
    for i, c in enumerate(campos):
        ax.bar([p + (i - 1) * largura for p in x], dados[c], width=largura * 0.92, color=COR_CAMPO[c],
               label=CAMPOS[c])
    muitos = len(nomes) > 10
    ax.set_xticks(list(x), nomes, fontsize=6.5 if muitos else 8, rotation=60 if muitos else 0,
                  ha="right" if muitos else "center", rotation_mode="anchor")
    ax.set_xlim(-0.6, len(nomes) - 0.4)
    _eixos(ax)
    ax.legend(frameon=False, fontsize=8, ncol=3, loc="upper left", bbox_to_anchor=(0, 1.15))
    return _figura(fig)


def grafico_evolucao(total: pd.DataFrame) -> Image:
    campos = ["cota_disponivel", "quantidade_solicitada", "demanda_registrada", "cestas_concedidas"]
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
    for tipo in ORDEM_TIPOS:
        valores = tipos[tipos["tipo"] == tipo].set_index("mes")["cestas_concedidas"].reindex(meses).fillna(0)
        if not valores.any():
            continue
        ax.bar([rotulo_mes(m) for m in meses], valores, bottom=base, color=COR_TIPO[tipo], label=tipo,
               width=0.6, edgecolor="white", linewidth=1)
        base += valores
    _eixos(ax)
    ax.legend(frameon=False, fontsize=8, ncol=4, loc="upper left", bbox_to_anchor=(0, 1.2))
    return _figura(fig)


# -------------------------------------------------------------------- relatório

def gerar_pdf(df: pd.DataFrame, mes: str, emergencias: pd.DataFrame | None = None,
              meses_historico: int = 12) -> bytes:
    """Relatório do mês escolhido, com comparação ao mês anterior e evolução recente."""
    df = df[df["mes"] <= mes]
    meses = sorted(df["mes"].unique())
    anterior = analise.mes_anterior(meses, mes)
    com_sas = analise.tem_sas(df[df["mes"] == mes])
    total = analise.total_geral(df)
    tipos = analise.por_tipo(df)
    t_mes = total[total["mes"] == mes].iloc[0]
    t_ant = total[total["mes"] == anterior].iloc[0] if anterior else None
    tipos_mes = tipos[tipos["mes"] == mes].set_index("tipo")
    secao = iter(range(1, 10))

    corpo = [
        Paragraph("Relatório Mensal — Concessão de Cestas Básicas", TITULO),
        Paragraph(f"Total Geral, SAS, CRAS e CREAS · <b>{mes_extenso(mes)}</b>", SUBTITULO),
    ]

    # Resumo do Total Geral
    corpo.append(Paragraph(f"{next(secao)}. Resumo do mês — Total Geral", SECAO))
    cab = ["Campo", rotulo_mes(mes)] + ([rotulo_mes(anterior), "Variação"] if anterior else [])
    linhas = [cab]
    for c, rotulo in CAMPOS.items():
        linha = [rotulo, num(t_mes[c])]
        if anterior:
            linha += [num(t_ant[c]), var(t_mes[c], t_ant[c])]
        linhas.append(linha)
    resumo = tabela(linhas, [4.6 * cm, 2.4 * cm] + ([2.4 * cm, 2.2 * cm] if anterior else []))

    colunas_ind = ["Total Geral", *[t for t in ("CRAS", "CREAS", "Centro POP") if t in tipos_mes.index]]
    ind = [["Indicador", *colunas_ind]]
    for chave, rotulo in analise.INDICADORES.items():
        pct = chave in analise.PERCENTUAIS
        valores = [t_mes[chave]] + [tipos_mes.loc[t, chave] for t in colunas_ind[1:]]
        ind.append([rotulo.replace(" (%)", " (%)"), *[num(v, 1 if pct else 0, "%" if pct else "") for v in valores]])
    indicadores = tabela(ind, [6.2 * cm] + [1.9 * cm] * len(colunas_ind))
    corpo.append(Table([[resumo, indicadores]], colWidths=[12.2 * cm, 14.5 * cm],
                       style=[("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    corpo.append(Paragraph(
        f"No mês foram concedidas <b>{num(t_mes['cestas_concedidas'])}</b> cestas para uma cota de "
        f"<b>{num(t_mes['cota_disponivel'])}</b> ({num(t_mes['uso_cota'], 1, '%')} de uso), com demanda registrada de "
        f"<b>{num(t_mes['demanda_registrada'])}</b> e <b>{num(t_mes['atendimento_social'])}</b> atendimentos "
        f"({num(t_mes['atendimento_tecnico'], 1, '%')} da demanda). Recibos sem registro de atendimento social: "
        f"<b>{num(t_mes['recibos_sem_atendimento'])}</b>. Cestas em estoque (solicitadas − concedidas): "
        f"<b>{num(t_mes['estoque'])}</b>{' (uso de estoque de meses anteriores)' if t_mes['estoque'] < 0 else ''}. "
        f"Unidades informantes: {int(t_mes['unidades'])}.",
        ParagraphStyle("p", parent=TEXTO, spaceBefore=8)))

    def linha_de(nomes, r):
        return [*nomes, *[num(r[c]) for c in CAMPOS], num(r["estoque"]), num(r["uso_cota"], 1, "%")]

    # Por SAS
    if com_sas:
        sas_mes = analise.por_sas(df[df["mes"] == mes])
        corpo.append(PageBreak())
        corpo.append(Paragraph(f"{next(secao)}. Por SAS — {rotulo_mes(mes)}", SECAO))
        linhas = [["SAS", *[ROTULO_CURTO[c] for c in CAMPOS], "Cestas em\nestoque", "Uso da\ncota"]]
        linhas += [linha_de([r["sas"]], r) for _, r in sas_mes.iterrows()]
        linhas.append(linha_de(["Total Geral"], t_mes))
        corpo.append(tabela(linhas, [7 * cm] + [2.35 * cm] * 6 + [2.1 * cm, 1.9 * cm], (len(linhas) - 1,)))
        corpo.append(PageBreak())
        corpo.append(KeepTogether([Paragraph("Cota × Demanda × Cestas concedidas por SAS", TEXTO),
                                   grafico_barras([nome_curto(x) for x in sas_mes["sas"]], sas_mes)]))

    # Por unidade
    und = analise.por_unidade(df[df["mes"] == mes])
    und = und.assign(_t=und["tipo"].map({t: i for i, t in enumerate(ORDEM_TIPOS)}))
    und = und.sort_values(["sas", "_t", "unidade"] if com_sas else ["_t", "unidade"])
    corpo.append(PageBreak())
    corpo.append(Paragraph(f"{next(secao)}. CRAS, CREAS e demais unidades — {rotulo_mes(mes)}", SECAO))
    cab = (["SAS"] if com_sas else []) + ["Unidade", *[ROTULO_CURTO[c] for c in CAMPOS], "Cestas em\nestoque",
                                          "Uso da\ncota"]
    linhas, totais = [cab], []
    for _, r in und.iterrows():
        linhas.append(linha_de(([Paragraph(nome_curto(r["sas"]), CELULA)] if com_sas else [])
                               + [Paragraph(r["unidade"], CELULA)], r))
    for tipo in ORDEM_TIPOS:
        if tipo in tipos_mes.index:
            linhas.append(linha_de(([""] if com_sas else []) + [f"Total {tipo}"], tipos_mes.loc[tipo]))
            totais.append(len(linhas) - 1)
    larguras = ([4.3 * cm] if com_sas else []) + [5.2 * cm if com_sas else 8 * cm] + [2.1 * cm] * 6 \
        + [1.9 * cm, 1.7 * cm]
    corpo.append(tabela(linhas, larguras, tuple(totais)))
    if not com_sas and len(und) <= 30:
        corpo.append(Spacer(1, 8))
        corpo.append(KeepTogether([Paragraph("Cota × Demanda × Cestas concedidas por unidade", TEXTO),
                                   grafico_barras(und["unidade"].tolist(), und)]))

    # Evolução
    recentes = meses[-meses_historico:]
    if len(recentes) > 1:
        corpo.append(PageBreak())
        corpo.append(Paragraph(f"{next(secao)}. Evolução mensal — {rotulo_mes(recentes[0])} a "
                               f"{rotulo_mes(recentes[-1])}", SECAO))
        t_rec = total[total["mes"].isin(recentes)]
        corpo.append(Paragraph("Total Geral", TEXTO))
        corpo.append(grafico_evolucao(t_rec))
        corpo.append(Paragraph("Cestas concedidas por tipo de unidade", TEXTO))
        corpo.append(grafico_tipos(tipos[tipos["mes"].isin(recentes)]))
        cab = ["Mês", *[ROTULO_CURTO[c] for c in CAMPOS], "Cestas em\nestoque", "Uso da\ncota"]
        linhas = [cab] + [linha_de([rotulo_mes(r["mes"])], r) for _, r in t_rec.iterrows()]
        corpo.append(KeepTogether([Spacer(1, 6), Paragraph("Total Geral mês a mês", TEXTO),
                                   tabela(linhas, [3 * cm] + [2.7 * cm] * 6 + [2.4 * cm, 2 * cm])]))

    # Emergências
    if emergencias is not None and not emergencias.empty:
        e_mes = emergencias[emergencias["mes"] == mes]
        recentes_e = analise.emergencias_por_mes(emergencias[emergencias["mes"].isin(meses[-meses_historico:])])
        if not e_mes.empty or not recentes_e.empty:
            bloco = [Paragraph(f"{next(secao)}. Emergências — {rotulo_mes(mes)}", SECAO),
                     Paragraph("Concessões em situações de emergência (enchentes, incêndios, desabamentos…), "
                               "realizadas pelo CPAS. Não entram nos totais das SAS.",
                               ParagraphStyle("e", parent=TEXTO, spaceAfter=6))]
            if e_mes.empty:
                bloco.append(Paragraph("Nenhuma emergência registrada no mês.", TEXTO))
            else:
                linhas = [["N.º de ocorrências", "N.º de cestas concedidas"],
                          [num(e_mes["ocorrencias"].sum()), num(e_mes["cestas"].sum())]]
                bloco.append(tabela(linhas, [5 * cm, 5 * cm]))
            if len(recentes_e) > 1:
                linhas = [["Mês", "Ocorrências", "Cestas"]]
                linhas += [[rotulo_mes(r.mes), num(r.ocorrencias), num(r.cestas)] for r in recentes_e.itertuples()]
                bloco += [Spacer(1, 8), Paragraph("Emergências mês a mês", TEXTO),
                          tabela(linhas, [3.5 * cm, 3 * cm, 3 * cm])]
            corpo.append(PageBreak())
            corpo.extend(bloco)

    # Alertas
    alertas = analise.alertas(df, mes)
    corpo.append(PageBreak())
    corpo.append(Paragraph(f"{next(secao)}. Alertas de conferência", SECAO))
    if alertas.empty:
        corpo.append(Paragraph("Nenhuma inconsistência encontrada no mês.", TEXTO))
    else:
        resumo_alertas = alertas.groupby(["Gravidade", "Regra"], sort=False).size()
        corpo.append(Paragraph("; ".join(f"{regra}: <b>{n}</b>" for (_, regra), n in resumo_alertas.items()) + ".",
                               ParagraphStyle("r", parent=TEXTO, spaceAfter=6)))
        listados = alertas[alertas["Gravidade"] != "Informativo"]
        if len(listados) < len(alertas):
            corpo.append(Paragraph("Abaixo, os alertas críticos e de atenção; os informativos estão no painel "
                                   "(página Alertas) e no relatório em Excel.", ParagraphStyle("n", parent=TEXTO,
                                                                                               spaceAfter=6)))
        linhas = [["Gravidade", "Unidade", "SAS", "Regra", "Detalhe"]] + [
            [a.Gravidade, Paragraph(a.Unidade, CELULA), Paragraph(nome_curto(a.SAS), CELULA),
             Paragraph(a.Regra, CELULA), Paragraph(a.Detalhe, CELULA)]
            for a in listados.itertuples(index=False)]
        t = tabela(linhas, [2.1 * cm, 5 * cm, 4 * cm, 5.2 * cm, 10.4 * cm])
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
                            title=f"Cestas Básicas - {rotulo_mes(mes)}", author="Assistência Social")
    doc.build(corpo, onFirstPage=rodape, onLaterPages=rodape)
    return buf.getvalue()
