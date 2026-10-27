"""Funções de tela comuns aos dois painéis (Cestas Básicas e Monitoramento Anual)."""

from __future__ import annotations

import hmac
import os

import pandas as pd
import streamlit as st


def segredo(nome: str) -> str | None:
    """Lê um valor de .streamlit/secrets.toml (ou dos Secrets do Streamlit Cloud)."""
    try:
        return st.secrets.get(nome)
    except Exception:  # nenhum arquivo de secrets configurado
        return None


def usar_banco_dos_secrets():
    """Na nuvem, o endereço do banco (Supabase/Neon) vem dos Secrets."""
    if segredo("DIBES_DATABASE_URL"):
        os.environ.setdefault("DIBES_DATABASE_URL", segredo("DIBES_DATABASE_URL"))


def exigir_senha(titulo: str):
    """Se houver SENHA nos Secrets, pede a senha antes de mostrar o painel."""
    senha = segredo("SENHA")
    if not senha or st.session_state.get("autenticado"):
        return
    st.title(titulo)
    digitada = st.text_input("Senha de acesso", type="password")
    if digitada:
        if hmac.compare_digest(digitada, str(senha)):
            st.session_state["autenticado"] = True
            st.rerun()
        st.error("Senha incorreta.")
    st.stop()


def fmt(v, casas: int = 0, sufixo: str = "") -> str:
    if v is None or pd.isna(v):
        return "—"
    texto = f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return texto + sufixo


def fmt_reais(v) -> str:
    return "—" if v is None or pd.isna(v) else "R$ " + fmt(v, 2)


def fmt_reais_curto(v) -> str:
    """Valor em reais resumido para cartões: R$ 927,7 mil · R$ 1,2 mi."""
    if v is None or pd.isna(v):
        return "—"
    if abs(v) >= 1e6:
        return "R$ " + fmt(v / 1e6, 1, " mi")
    if abs(v) >= 1e3:
        return "R$ " + fmt(v / 1e3, 1, " mil")
    return fmt_reais(v)
