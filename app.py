"""Painel de análise das concessões de cestas básicas — SAS / CRAS / CREAS.

Execute com:  streamlit run app.py
"""

from __future__ import annotations

import hmac
import os
from datetime import date

import pandas as pd
import streamlit as st

from dibes.config import CAMPOS, MESES_PT, TIPOS, rotulo_mes

st.set_page_config(page_title="Cestas Básicas · SAS", page_icon="🧺", layout="wide")


def segredo(nome: str) -> str | None:
    """Lê um valor de .streamlit/secrets.toml (ou dos Secrets do Streamlit Cloud)."""
    try:
        return st.secrets.get(nome)
    except Exception:  # nenhum arquivo de secrets configurado
        return None


# Na nuvem, o endereço do banco (Supabase/Neon) vem dos Secrets
if segredo("DIBES_DATABASE_URL"):
    os.environ.setdefault("DIBES_DATABASE_URL", segredo("DIBES_DATABASE_URL"))

from dibes import analise, banco, graficos, importador, relatorio, relatorio_pdf  # noqa: E402


def exigir_senha():
    """Se houver SENHA nos Secrets, pede a senha antes de mostrar o painel."""
    senha = segredo("SENHA")
    if not senha or st.session_state.get("autenticado"):
        return
    st.title("🧺 Cestas Básicas")
    digitada = st.text_input("Senha de acesso", type="password")
    if digitada:
        if hmac.compare_digest(digitada, str(senha)):
            st.session_state["autenticado"] = True
            st.rerun()
        st.error("Senha incorreta.")
    st.stop()


exigir_senha()


# ------------------------------------------------------------------ apoio

def fmt(v, casas: int = 0, sufixo: str = "") -> str:
    if v is None or pd.isna(v):
        return "—"
    texto = f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return texto + sufixo


def fmt_delta(atual, anterior, pct: bool = False) -> str | None:
    if anterior is None or pd.isna(anterior) or pd.isna(atual):
        return None
    if pct:
        return f"{fmt(atual - anterior, 1, ' p.p.')}"
    v = analise.variacao(atual, anterior)
    base = fmt(atual - anterior)
    return f"{'+' if atual - anterior > 0 else ''}{base}" + (f" ({fmt(v, 1, '%')})" if v is not None else "")


@st.cache_data(show_spinner=False, ttl=60)  # ttl: vê em até 1 min o que outra pessoa importou
def carregar_dados() -> pd.DataFrame:
    return banco.carregar()


def dados() -> pd.DataFrame:
    return carregar_dados()


def recarregar():
    carregar_dados.clear()
    pdf_do_mes.clear()


def seletor_mes(rotulo: str, chave: str, padrao: str | None = None) -> str:
    hoje = date.today()
    padrao = padrao or f"{hoje.year}-{hoje.month:02d}"
    ano_p, mes_p = map(int, padrao.split("-"))
    c1, c2 = st.columns([2, 1])
    mes = c1.selectbox(rotulo, range(1, 13), index=mes_p - 1, format_func=lambda m: MESES_PT[m - 1],
                       key=f"{chave}_m")
    anos = list(range(hoje.year - 6, hoje.year + 2))
    ano = c2.selectbox("Ano", anos, index=anos.index(ano_p) if ano_p in anos else len(anos) - 2, key=f"{chave}_a")
    return f"{ano}-{mes:02d}"


def escolher_mes_existente(df: pd.DataFrame, chave: str, rotulo="Mês de referência") -> str:
    meses = sorted(df["mes"].unique(), reverse=True)
    return st.selectbox(rotulo, meses, format_func=rotulo_mes, key=chave)


def escolher_recorte(df: pd.DataFrame, chave: str) -> str:
    unidades = sorted(df["unidade"].unique(), key=lambda u: ("CREAS" in u.upper(), u))
    return st.selectbox("Recorte", ["Total SAS", "Total CRAS", "Total CREAS", *unidades], key=chave)


def serie_do_recorte(df: pd.DataFrame, recorte: str) -> pd.DataFrame:
    """Tabela mensal (uma linha por mês) com campos e indicadores do recorte escolhido."""
    if recorte == "Total SAS":
        return analise.total_sas(df)
    if recorte in ("Total CRAS", "Total CREAS"):
        tipo = recorte.split()[1]
        return analise.por_tipo(df).query("tipo == @tipo").reset_index(drop=True)
    return analise.por_unidade(df[df["unidade"] == recorte]).sort_values("mes").reset_index(drop=True)


@st.cache_data(show_spinner="Gerando relatório…", ttl=60)
def pdf_do_mes(mes: str) -> bytes:
    return relatorio_pdf.gerar_pdf(carregar_dados(), mes)


def botao_pdf(mes: str, chave: str):
    pdf = pdf_do_mes(mes)
    st.download_button("🖨️ Relatório do mês (PDF)", pdf,
                       file_name=f"relatorio_cestas_{mes}.pdf", mime="application/pdf",
                       key=f"pdf_{chave}", width="stretch")


def sem_dados():
    st.info("Ainda não há dados no histórico. Vá em **📥 Importar dados** para carregar o primeiro mês.")
    st.stop()


def tabela_bonita(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    if "mes" in d:
        d["mes"] = d["mes"].map(rotulo_mes)
    return d.rename(columns=relatorio.ROTULOS)


CONFIG_NUMEROS = {
    **{rot: st.column_config.NumberColumn(rot, format="%.0f") for rot in CAMPOS.values()},
    **{rot: st.column_config.NumberColumn(rot, format="%.1f%%") for k, rot in analise.INDICADORES.items()
       if "%" in rot},
}


# --------------------------------------------------------------- páginas

def pagina_importar():
    st.header("📥 Importar dados do mês")
    st.caption("Envie a planilha mensal em **Excel, CSV, PDF ou HTML**, ou cole o código HTML da tabela. "
               "O sistema reconhece as colunas automaticamente; confira a prévia antes de salvar.")

    df_hist = dados()
    padrao = None
    if not df_hist.empty:
        ultimo = max(df_hist["mes"])
        a, m = map(int, ultimo.split("-"))
        padrao = f"{a + (m == 12)}-{(m % 12) + 1:02d}"

    with st.container(border=True):
        mes_escolhido = seletor_mes("Mês de referência (quando o arquivo não informar)", "imp", padrao)
        forcar = st.checkbox("Usar este mês para todas as linhas, mesmo que o arquivo indique outro")

    aba_arq, aba_html, aba_manual = st.tabs(["Arquivo", "Colar código HTML", "Digitar manualmente"])
    resultado = None
    with aba_arq:
        arquivos = st.file_uploader("Arquivos", type=["xlsx", "xls", "xlsm", "ods", "csv", "txt", "pdf", "html", "htm"],
                                    accept_multiple_files=True, label_visibility="collapsed")
        if arquivos and st.button("Ler arquivos", type="primary"):
            partes = []
            for arq in arquivos:
                try:
                    partes.append(importador.importar_arquivo(arq.getvalue(), arq.name, mes_escolhido))
                except Exception as erro:  # arquivo corrompido, formato inesperado...
                    partes.append(importador.ResultadoImportacao(pd.DataFrame(columns=importador.COLUNAS),
                                                                 [f"{arq.name}: não foi possível ler ({erro})."]))
            resultado = importador.finalizar(importador._juntar(partes))
            st.session_state["origem"] = ", ".join(a.name for a in arquivos)
    with aba_html:
        codigo = st.text_area("Cole aqui o código HTML (página inteira ou apenas a <table>)", height=220)
        if codigo.strip() and st.button("Ler código HTML", type="primary"):
            resultado = importador.importar_html_colado(codigo, mes_escolhido)
            st.session_state["origem"] = "código HTML colado"
    with aba_manual:
        st.write("Começa com as unidades já cadastradas; acrescente linhas no fim da tabela se precisar.")
        if st.button("Abrir tabela para digitação"):
            unidades = (df_hist.drop_duplicates("unidade")[["unidade", "tipo"]] if not df_hist.empty
                        else pd.DataFrame({"unidade": ["CRAS "], "tipo": ["CRAS"]}))
            base = unidades.assign(mes=mes_escolhido, **{c: None for c in CAMPOS})[importador.COLUNAS]
            resultado = importador.ResultadoImportacao(base.reset_index(drop=True))
            st.session_state["origem"] = "digitação manual"

    if resultado is not None:
        if forcar:
            resultado.dados["mes"] = mes_escolhido
        else:
            resultado.dados["mes"] = resultado.dados["mes"].fillna(mes_escolhido)
        st.session_state["previa"] = resultado

    previa: importador.ResultadoImportacao | None = st.session_state.get("previa")
    if previa is None:
        return
    st.subheader("Prévia")
    for aviso in previa.avisos:
        st.warning(aviso, icon="⚠️")
    if previa.dados.empty:
        st.error("Nenhum dado reconhecido. Verifique se a tabela tem os nomes das colunas "
                 "(Cota Disponível, Quantidade Solicitada, Demanda Registrada, Atendimento Social, "
                 "Recibos Emitidos, Cestas Concedidas) e uma coluna com os nomes dos CRAS/CREAS.")
        return

    editado = st.data_editor(
        previa.dados, num_rows="dynamic", width="stretch", hide_index=True, key=f"editor_{id(previa)}",
        column_config={
            "mes": st.column_config.TextColumn("Mês (AAAA-MM)", validate=r"^20\d{2}-(0[1-9]|1[0-2])$", required=True),
            "unidade": st.column_config.TextColumn("Unidade", required=True),
            "tipo": st.column_config.SelectboxColumn("Tipo", options=TIPOS, required=True),
            **{c: st.column_config.NumberColumn(r, min_value=0, step=1) for c, r in CAMPOS.items()},
        },
    )
    editado = editado.dropna(subset=["unidade"])
    editado = editado[editado["unidade"].astype(str).str.strip() != ""]
    meses = sorted(editado["mes"].dropna().unique())
    resumo = editado.groupby("tipo")["unidade"].count().to_dict()
    st.caption(f"{len(editado)} unidades · " + " · ".join(f"{k}: {v}" for k, v in resumo.items())
               + f" · mês(es): {', '.join(rotulo_mes(m) for m in meses)}")

    existentes = set(df_hist["mes"]) & set(meses) if not df_hist.empty else set()
    if existentes:
        st.info(f"Já existem dados de {', '.join(rotulo_mes(m) for m in sorted(existentes))}. "
                "Ao salvar, as unidades com o mesmo nome serão substituídas.", icon="ℹ️")
    c1, c2 = st.columns([1, 4])
    if c1.button("💾 Salvar no histórico", type="primary", disabled=editado["mes"].isna().any()):
        n = banco.salvar(editado, st.session_state.get("origem", ""))
        st.session_state.pop("previa", None)
        recarregar()
        st.success(f"{n} registros salvos.")
        st.balloons()
    if c2.button("Descartar"):
        st.session_state.pop("previa", None)
        st.rerun()


def pagina_painel():
    df = dados()
    if df.empty:
        sem_dados()
    st.header("📊 Painel do mês")
    c1, c2 = st.columns(2)
    with c1:
        mes = escolher_mes_existente(df, "painel_mes")
    with c2:
        recorte = escolher_recorte(df, "painel_recorte")

    serie = serie_do_recorte(df, recorte)
    linha = serie[serie["mes"] == mes]
    if linha.empty:
        st.warning(f"{recorte} não tem dados em {rotulo_mes(mes)}.")
        return
    linha = linha.iloc[0]
    ant_mes = analise.mes_anterior(serie["mes"].tolist(), mes)
    ant = serie[serie["mes"] == ant_mes].iloc[0] if ant_mes else None

    c1, c2 = st.columns([3, 1])
    c1.subheader(f"{recorte} · {rotulo_mes(mes)}")
    with c2:
        botao_pdf(mes, "painel")
    if ant_mes:
        st.caption(f"Variações em relação a {rotulo_mes(ant_mes)}.")
    colunas = st.columns(6)
    for col, (campo, rotulo) in zip(colunas, CAMPOS.items()):
        col.metric(rotulo, fmt(linha[campo]), fmt_delta(linha[campo], None if ant is None else ant[campo]),
                   border=True)
    colunas = st.columns(4)
    for col, ind in zip(colunas, ["uso_cota", "atendimento_demanda", "saldo_cota", "demanda_reprimida"]):
        pct = "%" in analise.INDICADORES[ind]
        col.metric(analise.INDICADORES[ind], fmt(linha[ind], 1 if pct else 0, "%" if pct else ""),
                   fmt_delta(linha[ind], None if ant is None else ant[ind], pct=pct),
                   delta_color="inverse" if ind == "demanda_reprimida" else "normal", border=True)

    st.plotly_chart(graficos.perfil_mes(linha, "Os seis campos no mês"), width="stretch", theme=None)

    st.divider()
    st.subheader(f"CRAS e CREAS em {rotulo_mes(mes)}")
    df_mes = analise.por_unidade(df[df["mes"] == mes])
    c1, c2 = st.columns([1, 3])
    opcoes = {**CAMPOS, **analise.INDICADORES}
    campo = c1.selectbox("Campo do ranking", list(opcoes), index=list(opcoes).index("cestas_concedidas"),
                         format_func=opcoes.get)
    c2.plotly_chart(graficos.barras_unidades(df_mes, campo, f"{opcoes[campo]} por unidade"),
                    width="stretch", theme=None)
    comparar = st.multiselect("Comparar por unidade", list(CAMPOS), format_func=CAMPOS.get,
                              default=["cota_disponivel", "demanda_registrada", "cestas_concedidas"])
    if comparar:
        st.plotly_chart(graficos.comparativo_unidades(df_mes, comparar[:8]), width="stretch", theme=None)

    tipos = analise.por_tipo(df[df["mes"] == mes])
    total = analise.total_sas(df[df["mes"] == mes]).assign(tipo="Total SAS").drop(columns="unidades")
    resumo = pd.concat([tipos, total], ignore_index=True)
    st.dataframe(tabela_bonita(resumo[["tipo", *CAMPOS, *analise.INDICADORES]]), hide_index=True,
                 width="stretch", column_config=CONFIG_NUMEROS)
    with st.expander("Tabela completa das unidades"):
        st.dataframe(tabela_bonita(df_mes[["tipo", "unidade", *CAMPOS, *analise.INDICADORES]]),
                     hide_index=True, width="stretch", column_config=CONFIG_NUMEROS)


def pagina_evolucao():
    df = dados()
    if df.empty:
        sem_dados()
    st.header("📈 Evolução mensal")
    meses = sorted(df["mes"].unique())
    if len(meses) > 1:
        ini, fim = st.select_slider("Período", options=meses, value=(meses[0], meses[-1]), format_func=rotulo_mes)
        df = df[(df["mes"] >= ini) & (df["mes"] <= fim)]
    c1, c2 = st.columns([1, 2])
    with c1:
        recorte = escolher_recorte(df, "evo_recorte")
    with c2:
        campos = st.multiselect("Campos", list(CAMPOS), default=list(CAMPOS), format_func=CAMPOS.get)
    serie = serie_do_recorte(df, recorte)
    if campos:
        st.plotly_chart(graficos.evolucao_campos(serie, campos, f"{recorte} · campos mês a mês"),
                        width="stretch", theme=None)

    st.subheader("Indicadores: Total SAS × CRAS × CREAS")
    ind = st.selectbox("Indicador", list(analise.INDICADORES), format_func=analise.INDICADORES.get)
    tipos = analise.por_tipo(df)
    series = {"Total SAS": analise.total_sas(df), "CRAS": tipos[tipos["tipo"] == "CRAS"],
              "CREAS": tipos[tipos["tipo"] == "CREAS"]}
    st.plotly_chart(graficos.evolucao_indicador(series, ind), width="stretch", theme=None)

    st.subheader("Participação de CRAS e CREAS no total")
    campo = st.selectbox("Campo", list(CAMPOS), index=5, format_func=CAMPOS.get, key="evo_tipo")
    st.plotly_chart(graficos.tipo_mensal(tipos, campo), width="stretch", theme=None)

    st.subheader("Mapa de calor por unidade")
    campo_mapa = st.selectbox("Campo", list(CAMPOS), index=5, format_func=CAMPOS.get, key="evo_mapa")
    st.plotly_chart(graficos.mapa_calor(df, campo_mapa), width="stretch", theme=None)

    with st.expander(f"Tabela mensal — {recorte}"):
        cols = ["mes", *CAMPOS, *analise.INDICADORES]
        st.dataframe(tabela_bonita(serie[cols]), hide_index=True, width="stretch",
                     column_config=CONFIG_NUMEROS)


def pagina_alertas():
    df = dados()
    if df.empty:
        sem_dados()
    st.header("⚠️ Alertas e conferência")
    c1, c2 = st.columns(2)
    with c1:
        mes = escolher_mes_existente(df, "alerta_mes")
    limite = c2.slider("Destacar variação de concessões acima de (%)", 10, 100, 30, step=5)
    tabela = analise.alertas(df, mes, limite)
    icones = {"Crítico": "🔴 Crítico", "Atenção": "🟠 Atenção", "Informativo": "🔵 Informativo"}
    cont = tabela["Gravidade"].value_counts()
    cols = st.columns(3)
    for col, g in zip(cols, icones):
        col.metric(icones[g], int(cont.get(g, 0)), border=True)
    if tabela.empty:
        st.success("Nenhuma inconsistência encontrada neste mês. ✅")
        return
    tabela["Gravidade"] = tabela["Gravidade"].map(icones)
    filtro = st.multiselect("Mostrar", list(icones.values()), default=list(icones.values()))
    st.dataframe(tabela[tabela["Gravidade"].isin(filtro)], hide_index=True, width="stretch")
    with st.expander("Como os alertas são calculados"):
        st.markdown("""
- 🔴 **Concessão acima da cota** — cestas concedidas maiores que a cota disponível.
- 🟠 **Recibos diferentes das cestas concedidas** — cada cesta deve ter um recibo.
- 🟠 **Demanda maior que a cota** — indica necessidade de ampliar a cota da unidade.
- 🟠 **Concedidas acima do solicitado** — possível erro de digitação.
- 🟠 **Unidade sem dados no mês** — a unidade informou no mês anterior e não neste.
- 🔵 **Baixo uso da cota** — menos de 50% da cota utilizada.
- 🔵 **Variação forte nas concessões** — mudança acima do limite escolhido em relação ao mês anterior.
""")


def pagina_dados():
    df = dados()
    if df.empty:
        sem_dados()
    st.header("🗂️ Histórico e relatório")
    meses = sorted(df["mes"].unique())
    st.caption(f"{len(meses)} meses · {df['unidade'].nunique()} unidades · {len(df)} registros")
    with st.container(border=True):
        st.markdown("**🖨️ Relatório mensal para impressão (PDF)**")
        st.caption("Resumo do Total SAS com comparação ao mês anterior, tabela de CRAS e CREAS, "
                   "evolução dos últimos 12 meses e alertas de conferência.")
        c1, c2 = st.columns([2, 1])
        with c1:
            mes_pdf = escolher_mes_existente(df, "pdf_mes", "Mês do relatório")
        with c2:
            st.write("")
            botao_pdf(mes_pdf, "historico")
    c1, c2 = st.columns(2)
    c1.download_button("⬇️ Relatório completo (Excel)", relatorio.gerar_excel(df),
                       file_name=f"relatorio_cestas_{meses[0]}_a_{meses[-1]}.xlsx", type="primary",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    c2.download_button("⬇️ Dados brutos (CSV)", df.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig"),
                       file_name="historico_cestas.csv", mime="text/csv")

    filtro = st.multiselect("Filtrar meses", meses, format_func=rotulo_mes)
    vista = df[df["mes"].isin(filtro)] if filtro else df
    st.dataframe(tabela_bonita(vista[["mes", "tipo", "unidade", *CAMPOS, "arquivo", "importado_em"]])
                 .rename(columns={"arquivo": "Arquivo de origem", "importado_em": "Importado em"}),
                 hide_index=True, width="stretch", column_config=CONFIG_NUMEROS)

    with st.expander("🗑️ Excluir dados"):
        c1, c2, c3 = st.columns([2, 3, 1])
        mes = c1.selectbox("Mês", meses, format_func=rotulo_mes, key="del_mes")
        unidades = ["(todas as unidades do mês)", *sorted(df[df["mes"] == mes]["unidade"])]
        unidade = c2.selectbox("Unidade", unidades, key="del_unid")
        c3.write("")
        if c3.button("Excluir", type="secondary"):
            if unidade == unidades[0]:
                n = banco.excluir_mes(mes)
            else:
                n = banco.excluir_unidade(mes, unidade)
            recarregar()
            st.success(f"{n} registro(s) excluído(s).")
            st.rerun()


# ---------------------------------------------------------------- navegação

PAGINAS = {
    "📊 Painel do mês": pagina_painel,
    "📈 Evolução mensal": pagina_evolucao,
    "⚠️ Alertas": pagina_alertas,
    "📥 Importar dados": pagina_importar,
    "🗂️ Histórico e relatório": pagina_dados,
}

with st.sidebar:
    st.title("🧺 Cestas Básicas")
    st.caption("Monitoramento mensal das concessões · Total SAS, CRAS e CREAS")
    inicial = 0 if not dados().empty else list(PAGINAS).index("📥 Importar dados")
    escolha = st.radio("Navegação", list(PAGINAS), index=inicial, label_visibility="collapsed")
    d = dados()
    if not d.empty:
        st.divider()
        st.caption(f"Histórico: {rotulo_mes(d['mes'].min())} a {rotulo_mes(d['mes'].max())} · "
                   f"{d['unidade'].nunique()} unidades")

PAGINAS[escolha]()
