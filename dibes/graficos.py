"""Gráficos (Plotly) usados no painel."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from .analise import INDICADORES, PERCENTUAIS
from .config import CAMPOS, rotulo_mes

# Paleta categórica em ordem fixa (validada para daltonismo nos pares adjacentes)
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
COR_CAMPO = dict(zip(CAMPOS, SERIES))
COR_TIPO = {"CRAS": SERIES[0], "CREAS": SERIES[1], "Centro POP": SERIES[2], "Outro": SERIES[3],
            "SAS": SERIES[0], "Total Geral": SERIES[6]}
ORDEM_TIPOS = ["SAS", "CRAS", "CREAS", "Centro POP", "Outro"]
SEQUENCIAL = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
TINTA_MUDA = "#898781"
GRADE = "rgba(137,135,129,0.25)"


def _layout(fig: go.Figure, titulo: str = "", altura: int = 420, eixo_y: str = "") -> go.Figure:
    fig.update_layout(
        title=dict(text=titulo, x=0, font=dict(size=16)),
        height=altura,
        separators=",.",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="system-ui, -apple-system, Segoe UI, sans-serif", size=13),
        margin=dict(l=10, r=10, t=60 if titulo else 20, b=10),
        legend=dict(orientation="h", yref="container", yanchor="bottom", y=0.0, xanchor="left", x=0, title=None),
        hoverlabel=dict(font_size=13),
        bargap=0.25,
    )
    fig.update_xaxes(automargin=True, showgrid=False, linecolor=TINTA_MUDA, tickfont=dict(color=TINTA_MUDA), title=None)
    fig.update_yaxes(automargin=True, tickformat=",~f", gridcolor=GRADE, zeroline=False, tickfont=dict(color=TINTA_MUDA),
                     title=dict(text=eixo_y, font=dict(color=TINTA_MUDA)) if eixo_y else None)
    return fig


def _eixo_meses(meses) -> list[str]:
    return [rotulo_mes(m) for m in meses]


def evolucao_campos(total: pd.DataFrame, campos: list[str] | None = None, titulo: str = "") -> go.Figure:
    """Linhas mês a mês dos campos escolhidos (uma série por campo)."""
    campos = campos or list(CAMPOS)
    fig = go.Figure()
    x = _eixo_meses(total["mes"])
    for c in campos:
        fig.add_trace(go.Scatter(
            x=x, y=total[c], name=CAMPOS[c], mode="lines+markers",
            line=dict(color=COR_CAMPO[c], width=2), marker=dict(size=8),
            hovertemplate=f"{CAMPOS[c]}: %{{y:,.0f}}<extra></extra>",
        ))
    fig.update_layout(hovermode="x unified")
    return _layout(fig, titulo, eixo_y="Quantidade")


def evolucao_indicador(series: dict[str, pd.DataFrame], indicador: str, titulo: str = "") -> go.Figure:
    """Um indicador ao longo dos meses para Total Geral, CRAS e CREAS."""
    fig = go.Figure()
    pct = indicador in PERCENTUAIS
    for nome, df in series.items():
        if df.empty:
            continue
        fig.add_trace(go.Scatter(
            x=_eixo_meses(df["mes"]), y=df[indicador], name=nome, mode="lines+markers",
            line=dict(color=COR_TIPO.get(nome, SERIES[3]), width=2), marker=dict(size=8),
            hovertemplate=f"{nome}: %{{y:,.1f}}{'%' if pct else ''}<extra></extra>",
        ))
    if pct:
        fig.add_hline(y=100, line=dict(color=TINTA_MUDA, width=1, dash="dot"))
    fig.update_layout(hovermode="x unified")
    return _layout(fig, titulo, eixo_y=INDICADORES[indicador])


def barras_unidades(df_mes: pd.DataFrame, campo: str, titulo: str = "") -> go.Figure:
    """Ranking das unidades num campo (ou indicador), colorido por tipo."""
    d = df_mes.sort_values(campo, ascending=True)
    rotulo = CAMPOS.get(campo) or INDICADORES.get(campo, campo)
    pct = "%" in rotulo
    fig = go.Figure()
    for tipo in ORDEM_TIPOS:
        parte = d[d["tipo"] == tipo]
        if parte.empty:
            continue
        fig.add_trace(go.Bar(
            y=parte["unidade"], x=parte[campo], name=tipo, orientation="h",
            marker=dict(color=COR_TIPO[tipo], cornerradius=4),
            text=parte[campo].map(lambda v: "" if pd.isna(v) else (f"{v:.0f}%" if pct else f"{v:,.0f}".replace(",", "."))),
            textposition="outside", cliponaxis=False, textfont=dict(color=TINTA_MUDA),
            hovertemplate=f"%{{y}}<br>{rotulo}: %{{x:,.{1 if pct else 0}f}}{'%' if pct else ''}<extra>{tipo}</extra>",
        ))
    fig.update_yaxes(categoryorder="array", categoryarray=d["unidade"].tolist(), gridcolor="rgba(0,0,0,0)")
    fig.update_xaxes(gridcolor=GRADE, showgrid=True)
    fig.update_layout(barmode="overlay")
    return _layout(fig, titulo, altura=max(320, 34 * len(d) + 120))


def comparativo_unidades(df_mes: pd.DataFrame, campos: list[str], titulo: str = "") -> go.Figure:
    """Barras agrupadas por unidade comparando alguns campos (ex.: cota × demanda × concedidas)."""
    d = df_mes.sort_values(["tipo", "unidade"])
    fig = go.Figure()
    for c in campos:
        fig.add_trace(go.Bar(
            x=d["unidade"], y=d[c], name=CAMPOS[c], marker=dict(color=COR_CAMPO[c], cornerradius=4),
            hovertemplate=f"%{{x}}<br>{CAMPOS[c]}: %{{y:,.0f}}<extra></extra>",
        ))
    fig.update_layout(barmode="group", bargroupgap=0.08)
    return _layout(fig, titulo, altura=460, eixo_y="Quantidade")


def mapa_calor(df: pd.DataFrame, campo: str, titulo: str = "") -> go.Figure:
    """Unidades × meses, intensidade = valor do campo."""
    tabela = df.pivot_table(index="unidade", columns="mes", values=campo, aggfunc="sum")
    tabela = tabela.loc[sorted(tabela.index)]
    rotulo = CAMPOS.get(campo) or INDICADORES.get(campo, campo)
    fig = go.Figure(go.Heatmap(
        z=tabela.values, x=_eixo_meses(tabela.columns), y=tabela.index,
        colorscale=[[i / (len(SEQUENCIAL) - 1), c] for i, c in enumerate(SEQUENCIAL)],
        xgap=2, ygap=2, colorbar=dict(title=None, thickness=12, outlinewidth=0),
        hovertemplate=f"%{{y}} · %{{x}}<br>{rotulo}: %{{z:,.0f}}<extra></extra>",
    ))
    fig.update_yaxes(autorange="reversed", showgrid=False)
    return _layout(fig, titulo, altura=max(320, 30 * len(tabela) + 120))


def tipo_mensal(tipos: pd.DataFrame, campo: str, titulo: str = "") -> go.Figure:
    """Barras empilhadas por tipo de unidade, por mês (a altura total é a soma das unidades)."""
    fig = go.Figure()
    for tipo in ORDEM_TIPOS:
        parte = tipos[tipos["tipo"] == tipo]
        if parte.empty:
            continue
        fig.add_trace(go.Bar(
            x=_eixo_meses(parte["mes"]), y=parte[campo], name=tipo,
            marker=dict(color=COR_TIPO[tipo], line=dict(width=2, color="rgba(252,252,251,1)")),
            hovertemplate=f"{tipo}: %{{y:,.0f}}<extra></extra>",
        ))
    fig.update_layout(barmode="stack", hovermode="x unified")
    return _layout(fig, titulo, eixo_y=CAMPOS[campo])


def perfil_mes(linha: pd.Series, titulo: str = "") -> go.Figure:
    """Os seis campos de um mês lado a lado (Total Geral, uma SAS, um tipo ou uma unidade)."""
    campos = list(CAMPOS)
    fig = go.Figure(go.Bar(
        x=[CAMPOS[c] for c in campos], y=[linha[c] for c in campos],
        marker=dict(color=[COR_CAMPO[c] for c in campos], cornerradius=4),
        text=[("" if pd.isna(linha[c]) else f"{linha[c]:,.0f}".replace(",", ".")) for c in campos],
        textposition="outside", cliponaxis=False, textfont=dict(color=TINTA_MUDA),
        hovertemplate="%{x}: %{y:,.0f}<extra></extra>",
    ))
    return _layout(fig, titulo, altura=380)


def recibos_x_atendimento(tabela: pd.DataFrame, limite: float = 10.0, titulo: str = "") -> go.Figure:
    """Recibos emitidos × atendimentos sociais registrados, por SAS ou unidade.

    Ordena pelo percentual de recibos sem atendimento; acima do limite, o rótulo fica em vermelho."""
    d = tabela[(tabela["recibos_emitidos"].fillna(0) > 0) | (tabela["atendimento_social"].fillna(0) > 0)]
    d = d.sort_values(["pct_recibos_sem_atendimento", "recibos_sem_atendimento"], ascending=True,
                      na_position="first")
    fig = go.Figure()
    for campo in ["atendimento_social", "recibos_emitidos"]:
        fig.add_trace(go.Bar(
            y=d["unidade"], x=d[campo], name=CAMPOS[campo], orientation="h",
            marker=dict(color=COR_CAMPO[campo], cornerradius=3),
            hovertemplate=f"%{{y}}<br>{CAMPOS[campo]}: %{{x:,.0f}}<extra></extra>",
        ))
    for r in d.itertuples(index=False):
        dif = (r.recibos_emitidos or 0) - (r.atendimento_social or 0)
        if dif <= 0:
            continue
        pct = r.pct_recibos_sem_atendimento
        acima = pct > limite
        fig.add_annotation(
            x=max(r.recibos_emitidos, r.atendimento_social), y=r.unidade, xanchor="left", showarrow=False,
            xshift=6, text=f"{'⚠ ' if acima else ''}+{dif:,.0f} sem atendimento ({pct:.0f}%)".replace(",", "."),
            font=dict(size=11, color="#d03b3b" if acima else TINTA_MUDA),
        )
    fig.update_yaxes(categoryorder="array", categoryarray=d["unidade"].tolist(), gridcolor="rgba(0,0,0,0)")
    fig.update_xaxes(gridcolor=GRADE, showgrid=True)
    fig.update_layout(barmode="group", bargap=0.3, bargroupgap=0.05)
    fig = _layout(fig, titulo, altura=max(340, 30 * len(d) + 140))
    fig.update_layout(margin=dict(r=190))
    return fig


def emergencias_mensal(por_mes: pd.DataFrame, titulo: str = "") -> go.Figure:
    """Cestas concedidas em emergências, por mês (colunas mes, cestas, ocorrencias)."""
    fig = go.Figure(go.Bar(
        x=_eixo_meses(por_mes["mes"]), y=por_mes["cestas"], marker=dict(color=SERIES[7], cornerradius=4), width=0.5,
        text=por_mes["cestas"].map(lambda v: f"{v:,.0f}".replace(",", ".")), textposition="outside",
        cliponaxis=False, textfont=dict(color=TINTA_MUDA), customdata=por_mes["ocorrencias"],
        hovertemplate="%{x}<br>Cestas: %{y:,.0f}<br>Ocorrências: %{customdata}<extra></extra>",
    ))
    return _layout(fig, titulo, altura=340, eixo_y="Cestas")


def barras_por_mes(series: dict[str, pd.Series], titulo: str = "", eixo_y: str = "", reais: bool = False,
                   empilhar: bool = False) -> go.Figure:
    """Barras de janeiro a dezembro, uma série por indicador (séries indexadas por 1..12)."""
    from .config import MESES_ABREV

    meses = [m.capitalize() for m in MESES_ABREV]
    fig = go.Figure()
    for i, (nome, serie) in enumerate(series.items()):
        valores = [serie.get(m) for m in range(1, 13)]
        fig.add_trace(go.Bar(
            x=meses, y=valores, name=nome, marker=dict(color=SERIES[i % len(SERIES)], cornerradius=3),
            hovertemplate=f"%{{x}} · {nome}: {'R$ %{y:,.2f}' if reais else '%{y:,.0f}'}<extra></extra>",
        ))
    fig.update_layout(barmode="stack" if empilhar else "group", hovermode="x unified" if len(series) > 1 else None)
    fig = _layout(fig, titulo, altura=360, eixo_y=eixo_y)
    if reais:
        fig.update_yaxes(tickprefix="R$ ")
    if len(series) == 1:
        fig.update_layout(showlegend=False)
    return fig
