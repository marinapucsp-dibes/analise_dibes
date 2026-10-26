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
from sqlalchemy import Column, Float, MetaData, String, Table, create_engine, delete, select
from sqlalchemy.engine import Engine

from .config import CAMPOS

ARQUIVO_PADRAO = Path(os.environ.get("DIBES_BANCO", Path(__file__).resolve().parent.parent / "dados" / "dibes.db"))

metadados = MetaData()
registros = Table(
    "registros", metadados,
    Column("mes", String(7), primary_key=True),
    Column("unidade", String(200), primary_key=True),
    Column("tipo", String(10), nullable=False),
    *[Column(c, Float) for c in CAMPOS],
    Column("arquivo", String(500)),
    Column("importado_em", String(19)),
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
    return engine


def salvar(df: pd.DataFrame, arquivo: str = "", url: str | None = None) -> int:
    """Grava (ou substitui) os registros de cada unidade/mês. Retorna a quantidade gravada."""
    agora = datetime.now().isoformat(timespec="seconds")
    linhas = [
        {"mes": r.mes, "unidade": r.unidade.strip(), "tipo": r.tipo, "arquivo": arquivo, "importado_em": agora,
         **{c: None if pd.isna(getattr(r, c)) else float(getattr(r, c)) for c in CAMPOS}}
        for r in df.itertuples(index=False)
    ]
    with conectar(url).begin() as con:
        for l in linhas:
            con.execute(delete(registros).where(registros.c.mes == l["mes"], registros.c.unidade == l["unidade"]))
        if linhas:
            con.execute(registros.insert(), linhas)
    return len(linhas)


def carregar(url: str | None = None) -> pd.DataFrame:
    consulta = select(registros).order_by(registros.c.mes, registros.c.tipo, registros.c.unidade)
    with conectar(url).connect() as con:
        return pd.read_sql(consulta, con)


def excluir_mes(mes: str, url: str | None = None) -> int:
    with conectar(url).begin() as con:
        return con.execute(delete(registros).where(registros.c.mes == mes)).rowcount


def excluir_unidade(mes: str, unidade: str, url: str | None = None) -> int:
    with conectar(url).begin() as con:
        return con.execute(delete(registros).where(registros.c.mes == mes, registros.c.unidade == unidade)).rowcount
