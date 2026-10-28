"""Análise dos dados do mês pelo Claude (API da Anthropic).

A chave da API fica nos Secrets do Streamlit (ANTHROPIC_API_KEY); veja o README.
"""

from __future__ import annotations

from collections.abc import Iterator

import anthropic
import pandas as pd

from . import analise
from .config import CAMPOS, rotulo_mes

MODELO = "claude-opus-5-5"

SISTEMA = """Você é analista de políticas de assistência social e apoia a equipe que monitora, mês a mês, \
as concessões do Benefício Eventual Auxílio Alimentação (cestas básicas) de um município. A rede é \
organizada em SAS (Supervisões de Assistência Social), cada uma com seus CRAS, CREAS e Centros POP.

Significado dos campos:
- Cota Disponível: cestas pré-estabelecidas para a SAS/unidade no mês.
- Quantidade Solicitada: cestas recebidas do almoxarifado no mês.
- Demanda Registrada: pessoas registradas no pré-atendimento com demanda principal de auxílio alimentação \
(não necessariamente atendidas).
- Atendimento Social: atendimentos técnicos com avaliação favorável à concessão.
- Recibos Emitidos: recibos válidos (sem duplicidade).
- Cestas Concedidas: cestas entregues (pode haver mais de uma cesta por recibo/família).
- Cestas em estoque = Quantidade Solicitada − Cestas Concedidas (negativo = uso de estoque de meses anteriores).
- Recibos sem atendimento = Recibos − Atendimento Social: indica emissão de recibo fora do fluxo \
(sem registro de atendimento social). Acima de 10% dos recibos é ponto crítico.
- Concessão abaixo de 10% da cota também é ponto crítico.
- Emergências: cestas concedidas pelo CPAS em situações de emergência (enchentes, incêndios, desabamentos), \
por localidade/ocorrência; não entram nos totais das SAS.

Como responder:
- Escreva em português do Brasil, em Markdown, para gestores e técnicos (sem jargão estatístico).
- Use somente os números fornecidos; não invente dados. Cite SAS e unidades pelo nome, com os números.
- Quando houver mês anterior, comente as variações relevantes.
- Seja objetivo: priorize o que exige ação."""

ROTEIRO_PADRAO = """Faça a análise técnica do mês com estas seções:
1. **Visão geral** — principais números do Total Geral e variação em relação ao mês anterior.
2. **Recibos sem registro de atendimento social** — SAS e unidades mais críticas (acima de 10%).
3. **Estoque e uso da cota** — onde sobram cestas, onde há uso de estoque anterior e unidades que \
concederam menos de 10% da cota.
4. **Demanda × atendimento** — onde a demanda não está sendo atendida.
5. **Emergências** — se houver, volume e ocorrências principais (em uma ou duas frases).
6. **Destaques positivos.**
7. **Recomendações** — ações práticas e priorizadas para a gestão."""

ROTEIRO_PERIODO = """Faça a análise técnica comparando os meses selecionados ({meses}), com estas seções:
1. **Visão geral do período** — evolução dos principais números do Total Geral mês a mês e tendência.
2. **Recibos sem registro de atendimento social** — SAS e unidades mais críticas (acima de 10%) e quem \
melhorou ou piorou ao longo dos meses.
3. **Estoque e uso da cota** — tendência do estoque, uso de estoque anterior e unidades que concederam \
menos de 10% da cota de forma recorrente.
4. **Demanda × atendimento** — evolução e onde a demanda não está sendo atendida.
5. **Emergências** — se houver, volume por mês e ocorrências principais (em poucas frases).
6. **Destaques positivos.**
7. **Recomendações** — ações práticas e priorizadas para a gestão."""

# acima disto, a tabela de unidades leva só as colunas principais (para não encarecer a análise)
MESES_UNIDADES_COMPLETAS = 3


def _csv(df: pd.DataFrame, colunas: list[str]) -> str:
    d = df[colunas].copy()
    for c in d.columns:
        if pd.api.types.is_float_dtype(d[c]):
            d[c] = d[c].round(1)
            if (d[c].dropna() % 1 == 0).all():
                d[c] = d[c].astype("Int64")
    nomes = {**CAMPOS, **analise.INDICADORES, "sas": "SAS", "unidade": "Unidade", "tipo": "Tipo",
             "mes": "Mês", "pct_recibos_sem_atendimento": "% recibos sem atendimento"}
    return d.rename(columns=nomes).to_csv(index=False, sep=";")


def montar_contexto(df: pd.DataFrame, meses: str | list[str], emergencias: pd.DataFrame | None = None) -> str:
    """Resumo dos dados dos meses escolhidos em texto, para enviar ao modelo.

    Com um único mês, inclui também o mês anterior para comparação."""
    if isinstance(meses, str):
        anterior = analise.mes_anterior(sorted(df["mes"].unique()), meses)
        meses = [m for m in (anterior, meses) if m]
        cabecalho = f"Mês analisado: {rotulo_mes(meses[-1])}" + (
            f" (mês anterior, para comparação: {rotulo_mes(anterior)})" if anterior else "")
    else:
        meses = sorted(meses)
        cabecalho = "Meses selecionados para a análise: " + ", ".join(rotulo_mes(m) for m in meses)
    ultimo = meses[-1]
    escopo = df[df["mes"].isin(meses)]
    campos = list(CAMPOS)
    ind = ["estoque", "recibos_sem_atendimento", "pct_recibos_sem_atendimento", "uso_cota",
           "atendimento_tecnico", "demanda_reprimida"]
    partes = [cabecalho]

    def com_mes(d):
        return d.sort_values("mes").assign(mes=d.sort_values("mes")["mes"].map(rotulo_mes))

    total = analise.total_geral(escopo)
    partes.append("## Total Geral por mês\n" + _csv(com_mes(total), ["mes", *campos, *ind]))
    tipos = analise.por_tipo(escopo)
    partes.append("## Por tipo de unidade\n" + _csv(com_mes(tipos), ["mes", "tipo", *campos, *ind]))
    if analise.tem_sas(escopo):
        sas = analise.por_sas(escopo)
        partes.append("## Por SAS\n" + _csv(com_mes(sas), ["mes", "sas", *campos, *ind]))
    und = analise.por_unidade(escopo).sort_values(["sas", "unidade", "mes"])
    if len(meses) <= MESES_UNIDADES_COMPLETAS:
        colunas_und = ["mes", "sas", "unidade", "tipo", *campos, *ind]
    else:
        colunas_und = ["mes", "sas", "unidade", "cota_disponivel", "quantidade_solicitada", "atendimento_social",
                       "recibos_emitidos", "cestas_concedidas", "estoque", "pct_recibos_sem_atendimento"]
    und = und.assign(mes=und["mes"].map(rotulo_mes))
    partes.append("## Unidades por mês\n" + _csv(und, colunas_und))
    if emergencias is not None and not emergencias.empty:
        e = emergencias[emergencias["mes"].isin(meses)].sort_values("mes")
        if not e.empty:
            partes.append("## Emergências (CPAS)\n" + e.assign(mes=e["mes"].map(rotulo_mes))
                          .rename(columns={"mes": "Mês", "ocorrencias": "Ocorrências", "cestas": "Cestas"})
                          [["Mês", "Ocorrências", "Cestas"]].to_csv(index=False, sep=";"))
    # alertas detalhados do último mês; nos demais, só a contagem por regra
    alertas = analise.alertas(df, ultimo)
    alertas = alertas[alertas["Gravidade"] != "Informativo"]
    if not alertas.empty:
        partes.append(f"## Alertas automáticos de {rotulo_mes(ultimo)} (críticos e de atenção)\n"
                      + alertas.to_csv(index=False, sep=";"))
    if len(meses) > 1:
        contagem = pd.concat([analise.alertas(df, m).assign(Mês=rotulo_mes(m)) for m in meses])
        contagem = contagem[contagem["Gravidade"] != "Informativo"].groupby(["Mês", "Regra"], sort=False).size()
        if not contagem.empty:
            partes.append("## Quantidade de alertas por mês e regra\n"
                          + contagem.rename("Quantidade").reset_index().to_csv(index=False, sep=";"))
    return "\n\n".join(partes)


def estimar_custo(contexto: str) -> tuple[int, float]:
    """Estimativa grosseira: (mil tokens enviados, custo em US$ com ~3 mil tokens de resposta)."""
    tokens = len(contexto) / 3.2
    return round(tokens / 1000), tokens / 1e6 * 4 + 3000 / 1e6 * 20


def analisar(df: pd.DataFrame, meses: str | list[str], pedido: str, api_key: str,
             emergencias: pd.DataFrame | None = None) -> Iterator[str]:
    """Envia os dados ao Claude e devolve o texto da análise aos poucos (streaming)."""
    client = anthropic.Anthropic(api_key=api_key)
    if isinstance(meses, list) and len(meses) > 1:
        roteiro = ROTEIRO_PERIODO.format(meses=", ".join(rotulo_mes(m) for m in sorted(meses)))
    else:
        meses = meses[0] if isinstance(meses, list) else meses
        roteiro = ROTEIRO_PADRAO
    conteudo = f"<dados>\n{montar_contexto(df, meses, emergencias)}\n</dados>\n\n{pedido.strip() or roteiro}"
    with client.beta.messages.stream(
        model=MODELO,
        max_tokens=16000,
        system=SISTEMA,
        output_config={"effort": "medium"},
        # se o filtro de segurança recusar, a própria API tenta de novo com o modelo recomendado
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{"role": "user", "content": conteudo}],
    ) as stream:
        yield from stream.text_stream
        final = stream.get_final_message()
    if final.stop_reason == "refusal":
        yield "\n\n_A IA não concluiu esta análise. Tente reformular o pedido._"
    elif final.stop_reason == "max_tokens":
        yield "\n\n_A análise foi interrompida por ser longa demais. Peça um recorte menor._"
