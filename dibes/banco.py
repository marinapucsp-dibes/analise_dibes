"""Armazenamento do histórico mensal em SQLite (um registro por unidade e mês)."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

from .config import CAMPOS

CAMINHO_PADRAO = Path(os.environ.get("DIBES_BANCO", Path(__file__).resolve().parent.parent / "dados" / "dibes.db"))


def conectar(caminho: Path | str = CAMINHO_PADRAO) -> sqlite3.Connection:
    Path(caminho).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(caminho)
    colunas = ", ".join(f"{c} REAL" for c in CAMPOS)
    con.execute(f"""
        CREATE TABLE IF NOT EXISTS registros (
            mes TEXT NOT NULL,
            unidade TEXT NOT NULL,
            tipo TEXT NOT NULL,
            {colunas},
            arquivo TEXT,
            importado_em TEXT,
            PRIMARY KEY (mes, unidade)
        )""")
    return con


def salvar(df: pd.DataFrame, arquivo: str = "", caminho: Path | str = CAMINHO_PADRAO) -> int:
    """Grava (ou substitui) os registros de cada unidade/mês. Retorna a quantidade gravada."""
    agora = datetime.now().isoformat(timespec="seconds")
    linhas = [
        (r.mes, r.unidade.strip(), r.tipo, *[None if pd.isna(getattr(r, c)) else float(getattr(r, c)) for c in CAMPOS],
         arquivo, agora)
        for r in df.itertuples(index=False)
    ]
    marcadores = ", ".join("?" * (len(CAMPOS) + 5))
    with conectar(caminho) as con:
        con.executemany(f"INSERT OR REPLACE INTO registros (mes, unidade, tipo, {', '.join(CAMPOS)}, arquivo, "
                        f"importado_em) VALUES ({marcadores})", linhas)
    return len(linhas)


def carregar(caminho: Path | str = CAMINHO_PADRAO) -> pd.DataFrame:
    with conectar(caminho) as con:
        df = pd.read_sql_query("SELECT * FROM registros ORDER BY mes, tipo, unidade", con)
    return df


def excluir_mes(mes: str, caminho: Path | str = CAMINHO_PADRAO) -> int:
    with conectar(caminho) as con:
        return con.execute("DELETE FROM registros WHERE mes = ?", (mes,)).rowcount


def excluir_unidade(mes: str, unidade: str, caminho: Path | str = CAMINHO_PADRAO) -> int:
    with conectar(caminho) as con:
        return con.execute("DELETE FROM registros WHERE mes = ? AND unidade = ?", (mes, unidade)).rowcount
