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


def montar_contexto(df: pd.DataFrame, mes: str, emergencias: pd.DataFrame | None = None) -> str:
    """Resumo dos dados do mês (e do anterior) em texto, para enviar ao modelo."""
    meses = sorted(df["mes"].unique())
    anterior = analise.mes_anterior(meses, mes)
    escopo = df[df["mes"].isin([m for m in (mes, anterior) if m])]
    campos = list(CAMPOS)
    ind = ["estoque", "recibos_sem_atendimento", "pct_recibos_sem_atendimento", "uso_cota",
           "atendimento_tecnico", "demanda_reprimida"]
    partes = [f"Mês analisado: {rotulo_mes(mes)}" + (f" (mês anterior: {rotulo_mes(anterior)})" if anterior else "")]

    total = analise.total_geral(escopo)
    partes.append("## Total Geral por mês\n" + _csv(total.assign(mes=total["mes"].map(rotulo_mes)),
                                                    ["mes", *campos, *ind]))
    tipos = analise.por_tipo(escopo)
    partes.append("## Por tipo de unidade\n" + _csv(tipos.assign(mes=tipos["mes"].map(rotulo_mes)),
                                                    ["mes", "tipo", *campos, *ind]))
    do_mes = df[df["mes"] == mes]
    if analise.tem_sas(do_mes):
        sas = analise.por_sas(escopo)
        partes.append("## Por SAS\n" + _csv(sas.assign(mes=sas["mes"].map(rotulo_mes)),
                                            ["mes", "sas", *campos, *ind]))
    und = analise.por_unidade(do_mes).sort_values(["sas", "unidade"])
    partes.append(f"## Unidades em {rotulo_mes(mes)}\n" + _csv(und, ["sas", "unidade", "tipo", *campos, *ind]))
    if emergencias is not None and not emergencias.empty:
        e = emergencias[emergencias["mes"].isin([m for m in (mes, anterior) if m])]
        if not e.empty:
            partes.append("## Emergências (CPAS)\n" + e.assign(mes=e["mes"].map(rotulo_mes))
                          .rename(columns={"mes": "Mês", "ocorrencia": "Localidade/Ocorrência",
                                           "cestas": "Cestas"})[["Mês", "Localidade/Ocorrência", "Cestas"]]
                          .to_csv(index=False, sep=";"))
    alertas = analise.alertas(df, mes)
    alertas = alertas[alertas["Gravidade"] != "Informativo"]
    if not alertas.empty:
        partes.append("## Alertas automáticos (críticos e de atenção)\n" + alertas.to_csv(index=False, sep=";"))
    return "\n\n".join(partes)


def analisar(df: pd.DataFrame, mes: str, pedido: str, api_key: str,
             emergencias: pd.DataFrame | None = None) -> Iterator[str]:
    """Envia os dados ao Claude e devolve o texto da análise aos poucos (streaming)."""
    client = anthropic.Anthropic(api_key=api_key)
    conteudo = f"<dados>\n{montar_contexto(df, mes, emergencias)}\n</dados>\n\n{pedido.strip() or ROTEIRO_PADRAO}"
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
