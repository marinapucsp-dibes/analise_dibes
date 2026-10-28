"""Armazenamento do histórico mensal (um registro por unidade e mês).

Usa o banco indicado em DIBES_DATABASE_URL (ex.: Postgres do Supabase, para uso
na nuvem). Sem essa variável, grava num arquivo SQLite local (dados/dibes.db).
"""

from __future__ import annotations

import os
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import pandas as pd
from sqlalchemy import Column, Float, MetaData, String, Table, create_engine, delete, inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

from . import importador
from .config import CAMPOS

ARQUIVO_PADRAO = Path(os.environ.get("DIBES_BANCO", Path(__file__).resolve().parent.parent / "dados" / "dibes.db"))

metadados = MetaData()
registros = Table(
    "registros", metadados,
    Column("mes", String(7), primary_key=True),
    Column("unidade", String(200), primary_key=True),
    Column("tipo", String(20), nullable=False),
    Column("sas", String(200)),
    *[Column(c, Float) for c in CAMPOS],
    Column("arquivo", String(500)),
    Column("importado_em", String(19)),
)

# Concessões em situações de emergência (enchentes, incêndios...), feitas pelo CPAS, fora das cotas das SAS:
# por mês, só o n.º de ocorrências e o de cestas
emergencias = Table(
    "emergencias_mes", metadados,
    Column("mes", String(7), primary_key=True),
    Column("ocorrencias", Float),
    Column("cestas", Float),
    Column("arquivo", String(500)),
    Column("importado_em", String(19)),
)

# Monitoramento Anual DIBES: um valor por mês, atividade e indicador (lançado mês a mês)
atividades = Table(
    "atividades", metadados,
    Column("mes", String(7), primary_key=True),
    Column("atividade", String(100), primary_key=True),
    Column("indicador", String(200), primary_key=True),
    Column("valor", Float),
    Column("atualizado_em", String(19)),
)


def url_padrao() -> str:
    url = os.environ.get("DIBES_DATABASE_URL")
    if url:
        # o Supabase/Neon fornecem "postgres://" ou "postgresql://"; usamos o driver psycopg 3
        return url.replace("postgres://", "postgresql://", 1).replace("postgresql://", "postgresql+psycopg://", 1)
    ARQUIVO_PADRAO.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{ARQUIVO_PADRAO}"


def conectar(url: str | Path | None = None) -> Engine:
    return _engine(str(url) if url else url_padrao())


@lru_cache(maxsize=None)
def _engine(url: str) -> Engine:
    """Engine do banco; cria a tabela na primeira vez. Aceita URL ou caminho de arquivo SQLite."""
    if "://" not in url:
        Path(url).parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{url}"
    engine = create_engine(url, pool_pre_ping=True)
    metadados.create_all(engine)
    # bancos criados antes da coluna SAS existir
    if "sas" not in {c["name"] for c in inspect(engine).get_columns("registros")}:
        with engine.begin() as con:
            con.execute(text("ALTER TABLE registros ADD COLUMN sas VARCHAR(200)"))
    _migrar_emergencias(engine)
    return engine


def _migrar_emergencias(engine: Engine):
    """A tabela antiga guardava uma linha por ocorrência (com o nome): passa a valer o resumo do mês."""
    if "emergencias" not in inspect(engine).get_table_names():
        return
    try:
        with engine.begin() as con:
            antigas = con.execute(text("SELECT mes, COUNT(*) AS n, SUM(cestas) AS cestas, MAX(arquivo) AS arquivo, "
                                       "MAX(importado_em) AS em FROM emergencias GROUP BY mes")).all()
            ja = {r[0] for r in con.execute(select(emergencias.c.mes))}
            novas = [{"mes": m, "ocorrencias": float(n), "cestas": c, "arquivo": a, "importado_em": em}
                     for m, n, c, a, em in antigas if m not in ja]
            if novas:
                con.execute(emergencias.insert(), novas)
            con.execute(text("DROP TABLE IF EXISTS emergencias"))
    except DBAPIError:
        # o outro app (Cestas Básicas ou Monitoramento Anual) fez a conversão ao mesmo tempo
        if "emergencias" in inspect(engine).get_table_names():
            raise


def salvar(df: pd.DataFrame, arquivo: str = "", url: str | None = None, substituir_meses: bool = False,
           apagar_meses: tuple[str, ...] = ()) -> int:
    """Grava (ou substitui) os registros de cada unidade/mês. Retorna a quantidade gravada.

    Com substituir_meses=True, apaga antes tudo o que existe dos meses presentes em df (para corrigir
    uma importação errada sem deixar sobrar unidades antigas). apagar_meses esvazia também outros meses.
    Tudo numa única transação: se algo falhar, nada é alterado."""
    agora = datetime.now().isoformat(timespec="seconds")
    linhas = [
        {"mes": r.mes, "unidade": r.unidade.strip(), "tipo": r.tipo, "arquivo": arquivo, "importado_em": agora,
         "sas": (str(r.sas).strip() or None) if pd.notna(r.sas) else None,
         **{c: None if pd.isna(getattr(r, c)) else float(getattr(r, c)) for c in CAMPOS}}
        for r in df.itertuples(index=False)
    ]
    with conectar(url).begin() as con:
        meses = set(apagar_meses) | ({l["mes"] for l in linhas} if substituir_meses else set())
        for mes in meses:
            con.execute(delete(registros).where(registros.c.mes == mes))
        for l in linhas:
            con.execute(delete(registros).where(registros.c.mes == l["mes"], registros.c.unidade == l["unidade"]))
        if linhas:
            con.execute(registros.insert(), linhas)
    return len(linhas)


def carregar(url: str | None = None) -> pd.DataFrame:
    consulta = select(registros).order_by(registros.c.mes, registros.c.tipo, registros.c.unidade)
    with conectar(url).connect() as con:
        return pd.read_sql(consulta, con)


def mapa_sas(url: str | None = None) -> dict[str, str]:
    """SAS de cada unidade, segundo a importação mais recente que a informou."""
    df = carregar(url)
    df = df[df["sas"].notna() & (df["tipo"] != "SAS")].sort_values("mes")
    return dict(zip(df["unidade"].str.upper(), df["sas"]))


def excluir_mes(mes: str, url: str | None = None) -> int:
    """Apaga o mês inteiro (unidades e emergências). Retorna quantos registros de unidades saíram."""
    with conectar(url).begin() as con:
        con.execute(delete(emergencias).where(emergencias.c.mes == mes))
        return con.execute(delete(registros).where(registros.c.mes == mes)).rowcount


def salvar_emergencias(df: pd.DataFrame, arquivo: str = "", url: str | None = None,
                       meses: tuple[str, ...] = ()) -> int:
    """Grava o n.º de ocorrências e de cestas de cada mês, substituindo o que havia nesse mês.
    `meses` permite esvaziar um mês. Retorna quantos meses foram gravados."""
    agora = datetime.now().isoformat(timespec="seconds")
    resumo = importador.resumir_emergencias(df.dropna(subset=["mes"]))
    linhas = [{"mes": r.mes, "arquivo": arquivo, "importado_em": agora,
               "ocorrencias": None if pd.isna(r.ocorrencias) else float(r.ocorrencias),
               "cestas": None if pd.isna(r.cestas) else float(r.cestas)}
              for r in resumo.itertuples(index=False) if not (pd.isna(r.ocorrencias) and pd.isna(r.cestas))]
    with conectar(url).begin() as con:
        for mes in set(meses) | set(resumo["mes"]):
            con.execute(delete(emergencias).where(emergencias.c.mes == mes))
        if linhas:
            con.execute(emergencias.insert(), linhas)
    return len(linhas)


def carregar_emergencias(url: str | None = None) -> pd.DataFrame:
    consulta = select(emergencias).order_by(emergencias.c.mes)
    with conectar(url).connect() as con:
        return pd.read_sql(consulta, con)


def excluir_unidade(mes: str, unidade: str, url: str | None = None) -> int:
    with conectar(url).begin() as con:
        return con.execute(delete(registros).where(registros.c.mes == mes, registros.c.unidade == unidade)).rowcount


def salvar_atividades(mes: str, df: pd.DataFrame, url: str | None = None) -> int:
    """Grava os lançamentos do mês (colunas atividade, indicador, valor), substituindo os que existiam."""
    agora = datetime.now().isoformat(timespec="seconds")
    linhas = {}
    for r in df.itertuples(index=False):
        indicador = str(r.indicador).strip()
        if indicador and pd.notna(r.valor):
            chave = (str(r.atividade), indicador.upper())
            anterior = linhas.get(chave, {}).get("valor", 0)
            linhas[chave] = {"mes": mes, "atividade": str(r.atividade), "indicador": indicador,
                             "valor": float(r.valor) + anterior, "atualizado_em": agora}
    with conectar(url).begin() as con:
        con.execute(delete(atividades).where(atividades.c.mes == mes))
        if linhas:
            con.execute(atividades.insert(), list(linhas.values()))
    return len(linhas)


def carregar_atividades(url: str | None = None) -> pd.DataFrame:
    consulta = select(atividades).order_by(atividades.c.mes, atividades.c.atividade, atividades.c.indicador)
    with conectar(url).connect() as con:
        return pd.read_sql(consulta, con)
