"""Monitoramento Anual DIBES — atividades lançadas mês a mês e consolidadas no ano.

Execute com:  streamlit run monitoramento_anual.py
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from dibes.config import MESES_PT, rotulo_mes
from dibes.ui import exigir_senha, fmt, fmt_reais, fmt_reais_curto, usar_banco_dos_secrets

st.set_page_config(page_title="Monitoramento Anual DIBES", page_icon="📅", layout="wide")
usar_banco_dos_secrets()

from dibes import analise, anual, banco, graficos, importador_anual, relatorio_anual  # noqa: E402

exigir_senha("📅 Monitoramento Anual DIBES")


# ------------------------------------------------------------------ dados

@st.cache_data(show_spinner=False, ttl=60)
def carregar_atividades() -> pd.DataFrame:
    return banco.carregar_atividades()


@st.cache_data(show_spinner=False, ttl=60)
def carregar_cestas() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Registros (com grafias unificadas) e emergências do sistema de Cestas Básicas."""
    return analise.unificar_nomes(banco.carregar()), banco.carregar_emergencias()


def recarregar():
    carregar_atividades.clear()
    carregar_cestas.clear()


def base_completa() -> pd.DataFrame:
    registros, emergencias = carregar_cestas()
    return anual.lancamentos(carregar_atividades(), anual.cestas_do_sistema(registros, emergencias))


def anos_disponiveis() -> list[str]:
    base = base_completa()
    anos = set(base["mes"].str[:4]) | {str(date.today().year)}
    return sorted(anos, reverse=True)


def texto(v, unidade: str) -> str:
    if unidade == "R$":
        return fmt_reais(v)
    if unidade == "%":
        return fmt(v, 1, "%")
    return fmt(v)


def tabela_exibicao(quadro: pd.DataFrame) -> pd.DataFrame:
    """Quadro com os valores já formatados (R$, %, números), meses Jan..Dez e Total."""
    linhas = []
    for _, r in quadro.iterrows():
        nome = f"↳ {r['indicador']}" if r["calculado"] else r["indicador"]
        linhas.append({"Indicador": nome, **{m: texto(r[i + 1], r["unidade"])
                                             for i, m in enumerate(anual.MESES_COLUNAS)},
                       "Total": texto(r["Total"], r["unidade"])})
    return pd.DataFrame(linhas)


def serie(quadro: pd.DataFrame, atividade: str, rotulo: str) -> pd.Series:
    linha = quadro[(quadro["atividade"] == atividade) & (quadro["indicador"] == rotulo)]
    return linha.iloc[0][list(range(1, 13))] if not linha.empty else pd.Series(dtype=float)


def grafico(series: dict, titulo: str, **kw):
    if any(s.notna().any() for s in series.values()):
        st.plotly_chart(graficos.barras_por_mes(series, titulo, **kw), width="stretch", theme=None)


# --------------------------------------------------------------- páginas

def pagina_painel():
    st.header("📊 Painel anual")
    ano = st.selectbox("Ano", anos_disponiveis())
    quadro = anual.quadro_anual(base_completa(), ano)
    total = quadro.set_index(["atividade", "indicador"])["Total"]

    def t(atividade, rotulo):
        return total.get((atividade, rotulo))

    A, P = anual.ALIMENTACAO, anual.PASSAGENS
    def reais(coluna, rotulo, valor):
        coluna.metric(rotulo, fmt_reais_curto(valor), border=True, help=f"Valor exato: {fmt_reais(valor)}")

    st.markdown(f"**🧺 {A}**")
    c = st.columns(4)
    c[0].metric("Cestas concedidas (SAS + emergências)", fmt(t(A, "Total de cestas concedidas")), border=True)
    c[1].metric("Cestas compradas", fmt(t(A, "Cestas compradas")), border=True)
    reais(c[2], "Valor gasto com cestas", t(A, "Valor gasto com cestas"))
    reais(c[3], "Custo médio por cesta", t(A, "Custo médio por cesta comprada"))
    st.markdown(f"**🚌 {P}**")
    c = st.columns(4)
    c[0].metric("Solicitações atendidas", fmt(t(P, "Solicitações atendidas")), border=True)
    c[1].metric("Passagens compradas", fmt(t(P, "Passagens compradas")), border=True)
    reais(c[2], "Valor gasto com passagens", t(P, "Valor gasto com passagens"))
    reais(c[3], "Custo médio por passagem", t(P, "Custo médio por passagem"))
    st.markdown("**📨 Demais atividades**")
    c = st.columns(4)
    c[0].metric("Protocolos SIGRC respondidos", fmt(t(anual.SIGRC, "Protocolos respondidos")), border=True)
    c[1].metric("Processos SEI respondidos", fmt(t(anual.SEI, "Processos SEI respondidos")), border=True)
    c[2].metric("Manutenções no PBF", fmt(t(anual.PBF, "Total de manutenções")), border=True)
    outros = quadro[quadro["atividade"] == anual.OUTROS]["Total"].sum(min_count=1)
    c[3].metric("Outras ações", fmt(outros), border=True)

    lancados = anual.meses_lancados(carregar_atividades(), ano)
    situacao = " · ".join(f"{'✅' if lancados.get(i + 1) else '⬜'} {m}" for i, m in enumerate(anual.MESES_COLUNAS))
    st.caption(f"Meses com lançamentos em {ano}: {situacao}")

    abas = st.tabs(["🧺 Alimentação", "🚌 Passagens", "📨 SIGRC e SEI", "👨‍👩‍👧 PBF", "➕ Outros", "📋 Quadro completo"])
    with abas[0]:
        grafico({"Concedidas (SAS/unidades)": serie(quadro, A, "Cestas concedidas (SAS/unidades)"),
                 "Concedidas em emergências": serie(quadro, A, "Cestas concedidas em emergências"),
                 "Compradas": serie(quadro, A, "Cestas compradas")}, "Cestas por mês", eixo_y="Cestas")
        grafico({"Valor gasto com cestas": serie(quadro, A, "Valor gasto com cestas")}, "Valor gasto com cestas",
                reais=True)
        st.dataframe(tabela_exibicao(quadro[quadro["atividade"] == A]), hide_index=True, width="stretch")
        st.caption("Cestas concedidas pelas SAS/unidades e em emergências vêm do sistema de Cestas Básicas "
                   "(ou do lançamento do mês, quando o mês não foi importado lá).")
        registros, _ = carregar_cestas()
        por_sas = anual.cestas_por_sas_no_ano(registros, ano)
        if not por_sas.empty:
            with st.expander("Cestas concedidas por SAS"):
                st.dataframe(por_sas.rename(columns={i + 1: m for i, m in enumerate(anual.MESES_COLUNAS)})
                             .rename_axis("SAS").reset_index(), hide_index=True, width="stretch",
                             column_config={c: st.column_config.NumberColumn(format="%.0f")
                                            for c in [*anual.MESES_COLUNAS, "Total"]})
            with st.expander("Cestas concedidas por unidade"):
                por_und = anual.cestas_por_unidade_no_ano(registros, ano)
                filtro = st.selectbox("SAS", ["Todas as SAS", *sorted(por_und["sas"].unique())], key="anual_sas")
                if filtro != "Todas as SAS":
                    por_und = por_und[por_und["sas"] == filtro]
                st.dataframe(por_und.rename(columns={i + 1: m for i, m in enumerate(anual.MESES_COLUNAS)})
                             .rename(columns={"sas": "SAS", "unidade": "Unidade", "tipo": "Tipo"}),
                             hide_index=True, width="stretch",
                             column_config={c: st.column_config.NumberColumn(format="%.0f")
                                            for c in [*anual.MESES_COLUNAS, "Total"]})
    with abas[1]:
        grafico({"Solicitações": serie(quadro, P, "Solicitações"),
                 "Solicitações atendidas": serie(quadro, P, "Solicitações atendidas"),
                 "Pessoas beneficiadas": serie(quadro, P, "Pessoas beneficiadas")}, "Solicitações e atendimento")
        grafico({"Passagens compradas": serie(quadro, P, "Passagens compradas"),
                 "Passagens não utilizadas": serie(quadro, P, "Passagens não utilizadas")}, "Passagens")
        grafico({"Valor gasto com passagens": serie(quadro, P, "Valor gasto com passagens")},
                "Valor gasto com passagens", reais=True)
        st.dataframe(tabela_exibicao(quadro[quadro["atividade"] == P]), hide_index=True, width="stretch")
    with abas[2]:
        grafico({"Protocolos SIGRC respondidos": serie(quadro, anual.SIGRC, "Protocolos respondidos"),
                 "Processos SEI respondidos": serie(quadro, anual.SEI, "Processos SEI respondidos")},
                "SIGRC e SEI")
        st.dataframe(tabela_exibicao(quadro[quadro["atividade"].isin([anual.SIGRC, anual.SEI])]),
                     hide_index=True, width="stretch")
    with abas[3]:
        grafico({"Em lote": serie(quadro, anual.PBF, "Manutenções realizadas em lote"),
                 "Manuais": serie(quadro, anual.PBF, "Manutenções realizadas manualmente")},
                "Manutenções no PBF", empilhar=True)
        st.dataframe(tabela_exibicao(quadro[quadro["atividade"] == anual.PBF]), hide_index=True, width="stretch")
    with abas[4]:
        outros_q = quadro[quadro["atividade"] == anual.OUTROS]
        if outros_q.empty:
            st.info("Nenhuma outra atividade lançada neste ano. Use ✍️ Lançar mês → Outros.")
        else:
            grafico({r["indicador"]: r[list(range(1, 13))] for _, r in outros_q.iterrows()}, "Outras ações",
                    empilhar=True)
            st.dataframe(tabela_exibicao(outros_q), hide_index=True, width="stretch")
    with abas[5]:
        for atividade in [*anual.CATALOGO, anual.OUTROS]:
            parte = quadro[quadro["atividade"] == atividade]
            if not parte.empty:
                st.markdown(f"**{atividade}**")
                st.dataframe(tabela_exibicao(parte), hide_index=True, width="stretch")
        st.caption("↳ = indicador calculado a partir dos valores lançados.")


def seletor_mes(chave: str = "lanc") -> str:
    hoje = date.today()
    padrao_ano, padrao_mes = (hoje.year, hoje.month - 1) if hoje.month > 1 else (hoje.year - 1, 12)
    c1, c2 = st.columns([2, 1])
    mes = c1.selectbox("Mês", range(1, 13), index=padrao_mes - 1, format_func=lambda m: MESES_PT[m - 1],
                       key=f"{chave}_m")
    anos = list(range(hoje.year - 5, hoje.year + 1))
    ano = c2.selectbox("Ano", anos, index=anos.index(padrao_ano), key=f"{chave}_a")
    return f"{ano}-{mes:02d}"


def pagina_lancar():
    st.header("✍️ Lançar mês")
    if "salvo" in st.session_state:
        st.success(st.session_state.pop("salvo"), icon="✅")
    st.caption("Preencha os números do mês e salve. Para corrigir, escolha o mês de novo: os valores já "
               "lançados aparecem nos campos. Campo em branco = sem informação.")
    mes = seletor_mes()
    atividades = carregar_atividades()
    do_mes = atividades[atividades["mes"] == mes]
    existente = {(r.atividade, r.indicador): r.valor for r in do_mes.itertuples()}
    registros, emergencias = carregar_cestas()
    sistema = anual.cestas_do_sistema(registros, emergencias)
    sistema = dict(zip(sistema[sistema["mes"] == mes]["indicador"], sistema[sistema["mes"] == mes]["valor"]))

    with st.form(f"lancar_{mes}"):
        valores: dict[tuple[str, str], float | None] = {}
        for atividade, itens in anual.CATALOGO.items():
            st.subheader(atividade)
            colunas = st.columns(3)
            for i, (indicador, rotulo, unidade) in enumerate(itens):
                coluna = colunas[i % 3]
                if indicador in anual.AUTOMATICOS and indicador in sistema:
                    coluna.metric(rotulo, fmt(sistema[indicador]), help="Vem do sistema de Cestas Básicas.")
                    continue
                atual = existente.get((atividade, indicador))
                ajuda = ("Este mês não está no sistema de Cestas Básicas; digite o total se tiver."
                         if indicador in anual.AUTOMATICOS else None)
                if unidade == "R$":
                    valores[(atividade, indicador)] = coluna.number_input(
                        f"{rotulo} (R$)", min_value=0.0, step=0.01, format="%.2f", help=ajuda,
                        value=None if atual is None else float(atual), key=f"{mes}_{indicador}")
                else:
                    valores[(atividade, indicador)] = coluna.number_input(
                        rotulo, min_value=0, step=1, help=ajuda,
                        value=None if atual is None else int(atual), key=f"{mes}_{indicador}")
        st.subheader("Outros")
        st.caption("Nome da atividade e n.º de ações. Inclua linhas no fim da tabela.")
        outros = do_mes[do_mes["atividade"] == anual.OUTROS][["indicador", "valor"]]
        outros = outros.rename(columns={"indicador": "Atividade", "valor": "Nº de ações"}).reset_index(drop=True)
        if outros.empty:
            outros = pd.DataFrame({"Atividade": pd.Series(dtype=str), "Nº de ações": pd.Series(dtype=float)})
        outros_editado = st.data_editor(
            outros, num_rows="dynamic", width="stretch", hide_index=True, key=f"outros_{mes}",
            column_config={"Atividade": st.column_config.TextColumn(width="large"),
                           "Nº de ações": st.column_config.NumberColumn(min_value=0, step=1)})
        salvar = st.form_submit_button("💾 Salvar mês", type="primary")

    if salvar:
        linhas = [{"atividade": a, "indicador": i, "valor": v} for (a, i), v in valores.items() if v is not None]
        for r in outros_editado.itertuples(index=False):
            if isinstance(r[0], str) and r[0].strip() and pd.notna(r[1]):
                linhas.append({"atividade": anual.OUTROS, "indicador": r[0].strip(), "valor": r[1]})
        n = banco.salvar_atividades(mes, pd.DataFrame(linhas, columns=["atividade", "indicador", "valor"]))
        recarregar()
        st.session_state["salvo"] = f"{rotulo_mes(mes)}: {n} valores salvos."
        st.rerun()


def pagina_importar():
    st.header("📥 Importar Excel, CSV ou PDF")
    if "salvo_imp" in st.session_state:
        st.success(st.session_state.pop("salvo_imp"), icon="✅")
    st.markdown("""
Formatos aceitos:
- **Quadro anual** — indicadores nas linhas e meses nas colunas (Jan a Dez). É o formato do **modelo** abaixo
  e também do Excel e do PDF que este sistema gera.
- **Formulário de um mês** — nome do indicador e valor (o mês vem do arquivo ou do seletor abaixo).
- **Lista** — colunas *Mês*, *Indicador* e *Valor*.
- **Meses nas linhas** — uma linha por mês e uma coluna por indicador.
""")
    c1, c2 = st.columns([1, 2])
    ano_modelo = c1.selectbox("Ano do modelo", [str(a) for a in range(date.today().year + 1, date.today().year - 4,
                                                                         -1)], index=1, key="ano_modelo")
    c2.write("")
    c2.download_button("⬇️ Baixar modelo de planilha", importador_anual.modelo_excel(ano_modelo),
                       file_name=f"modelo_monitoramento_anual_{ano_modelo}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    with st.container(border=True):
        st.caption("Mês de referência para arquivos que não informam o mês (ex.: formulário de um mês). "
                   "O ano também é usado quando as colunas trazem só o nome do mês.")
        mes_padrao = seletor_mes("imp")
    arquivos = st.file_uploader("Arquivos", type=["xlsx", "xls", "xlsm", "ods", "csv", "txt", "pdf"],
                                accept_multiple_files=True)
    if arquivos and st.button("Ler arquivos", type="primary"):
        partes = []
        for arq in arquivos:
            try:
                partes.append(importador_anual.importar_arquivo(arq.getvalue(), arq.name, mes_padrao[:4],
                                                                mes_padrao))
            except Exception as erro:  # arquivo corrompido, formato inesperado...
                partes.append(importador_anual.ResultadoAnual(pd.DataFrame(columns=importador_anual.COLUNAS),
                                                              [f"{arq.name}: não foi possível ler ({erro})."]))
        previa = importador_anual.juntar(partes)
        # cestas concedidas (SAS/emergências) de meses que já estão no sistema de Cestas Básicas não são gravadas
        registros, emergencias = carregar_cestas()
        sistema = anual.cestas_do_sistema(registros, emergencias)
        no_sistema = set(zip(sistema["mes"], sistema["indicador"]))
        ja_tem = [(m, i) in no_sistema for m, i in zip(previa.dados["mes"], previa.dados["indicador"])]
        if any(ja_tem):
            previa.dados = previa.dados.loc[[not x for x in ja_tem]].reset_index(drop=True)
            previa.avisos.append(f"{sum(ja_tem)} valores de cestas concedidas foram ignorados: esses meses já "
                                 "vêm do sistema de Cestas Básicas.")
        st.session_state["previa_anual"] = previa

    previa = st.session_state.get("previa_anual")
    if previa is None:
        return
    st.subheader("Prévia")
    for aviso in previa.avisos:
        st.warning(aviso, icon="⚠️")
    if previa.dados.empty:
        st.error("Nenhum valor reconhecido. Use o modelo de planilha ou confira se o arquivo tem os nomes dos "
                 "indicadores e os meses.")
        return
    tabela = previa.dados.assign(indicador=previa.dados["indicador"].map(lambda i: anual.ROTULO.get(i, i)))
    tabela = tabela.sort_values(["mes", "atividade"]).reset_index(drop=True)
    editado = st.data_editor(
        tabela, num_rows="dynamic", width="stretch", hide_index=True, key=f"prev_anual_{id(previa)}",
        column_config={
            "mes": st.column_config.TextColumn("Mês (AAAA-MM)", validate=r"^20\d{2}-(0[1-9]|1[0-2])$",
                                               required=True),
            "atividade": st.column_config.SelectboxColumn("Atividade", options=[*anual.CATALOGO, anual.OUTROS],
                                                          required=True),
            "indicador": st.column_config.TextColumn("Indicador", required=True, width="large"),
            "valor": st.column_config.NumberColumn("Valor", min_value=0),
        })
    editado = editado.dropna(subset=["mes", "indicador", "valor"])
    meses = sorted(editado["mes"].unique())
    st.caption(f"{len(editado)} valores · meses: {', '.join(rotulo_mes(m) for m in meses)}")

    # rótulo exibido -> chave do indicador (nas atividades fixas)
    chave_do_rotulo = {(atv, rot): ind for atv, itens in anual.CATALOGO.items() for ind, rot, _ in itens}
    invalidos = [f"{r.atividade}: {r.indicador}" for r in editado.itertuples()
                 if r.atividade != anual.OUTROS and (r.atividade, r.indicador) not in chave_do_rotulo]
    if invalidos:
        st.error("Estes indicadores não existem na atividade escolhida (troque a atividade para 'Outros' ou "
                 "corrija o nome): " + "; ".join(invalidos))

    substituir = st.checkbox("Substituir os meses por inteiro (apaga o que já estava lançado nesses meses)",
                             value=False, help="Desmarcado: os valores do arquivo completam ou atualizam o que já "
                                               "foi lançado, sem apagar os demais indicadores do mês.")
    c1, c2 = st.columns([1, 4])
    if c1.button("💾 Salvar", type="primary", disabled=bool(invalidos)):
        atividades = carregar_atividades()
        for mes in meses:
            novos = editado[editado["mes"] == mes].assign(indicador=lambda d: [
                chave_do_rotulo.get((a, i), i) for a, i in zip(d["atividade"], d["indicador"])])
            if not substituir:
                antigos = atividades[atividades["mes"] == mes]
                chaves = set(zip(novos["atividade"], novos["indicador"].str.upper()))
                antigos = antigos.loc[[(a, i.upper()) not in chaves for a, i in zip(antigos["atividade"],
                                                                                 antigos["indicador"])]]
                novos = pd.concat([antigos[["atividade", "indicador", "valor"]], novos], ignore_index=True)
            banco.salvar_atividades(mes, novos[["atividade", "indicador", "valor"]])
        recarregar()
        st.session_state.pop("previa_anual", None)
        st.session_state["salvo_imp"] = f"{len(editado)} valores salvos em {len(meses)} mês(es)."
        st.rerun()
    if c2.button("Descartar"):
        st.session_state.pop("previa_anual", None)
        st.rerun()


def pagina_relatorios():
    st.header("🖨️ Relatórios")
    ano = st.selectbox("Ano", anos_disponiveis(), key="rel_ano")
    base = base_completa()
    quadro = anual.quadro_anual(base, ano)
    registros, _ = carregar_cestas()
    por_sas = anual.cestas_por_sas_no_ano(registros, ano)
    por_und = anual.cestas_por_unidade_no_ano(registros, ano)
    c1, c2 = st.columns(2)
    c1.download_button("🖨️ Relatório anual (PDF)", relatorio_anual.gerar_pdf_anual(quadro, ano, por_sas),
                       file_name=f"monitoramento_anual_dibes_{ano}.pdf", mime="application/pdf", type="primary",
                       width="stretch")
    c2.download_button("⬇️ Planilha anual (Excel)",
                       relatorio_anual.gerar_excel_anual(quadro, ano, por_sas, por_und, base),
                       file_name=f"monitoramento_anual_dibes_{ano}.xlsx", width="stretch",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    st.caption("PDF: quadro do ano por atividade (Jan a Dez e Total) e cestas por SAS. Excel: quadro anual, "
               "cestas por SAS e por unidade e todos os lançamentos.")


# ---------------------------------------------------------------- navegação

PAGINAS = {"📊 Painel anual": pagina_painel, "✍️ Lançar mês": pagina_lancar, "📥 Importar": pagina_importar,
           "🖨️ Relatórios": pagina_relatorios}

with st.sidebar:
    st.title("📅 Monitoramento Anual DIBES")
    st.caption("Atividades da DIBES lançadas mês a mês e consolidadas no ano.")
    escolha = st.radio("Navegação", list(PAGINAS), label_visibility="collapsed")

PAGINAS[escolha]()
