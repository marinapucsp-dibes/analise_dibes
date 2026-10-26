"""Definições dos campos analisados e apelidos aceitos na importação."""

# Campo interno -> rótulo exibido
CAMPOS = {
    "cota_disponivel": "Cota Disponível",
    "quantidade_solicitada": "Quantidade Solicitada",
    "demanda_registrada": "Demanda Registrada",
    "atendimento_social": "Atendimento Social",
    "recibos_emitidos": "Recibos Emitidos",
    "cestas_concedidas": "Cestas Concedidas",
}

# Apelidos (já normalizados: minúsculas, sem acento) que identificam cada coluna.
# A busca é feita por "contém", na ordem: o primeiro apelido encontrado vence.
APELIDOS = {
    "cota_disponivel": ["cota disponivel", "cota"],
    "quantidade_solicitada": ["quantidade solicitada", "qtd solicitada", "qtde solicitada", "solicitad"],
    "demanda_registrada": ["demanda registrada", "demanda"],
    "atendimento_social": ["atendimento social", "atendimentos sociais", "atendimento"],
    "recibos_emitidos": ["quantidade de recibos", "recibos emitidos", "recibo"],
    "cestas_concedidas": ["cestas concedidas", "quantidade de cestas", "concedid"],
}

APELIDOS_UNIDADE = ["unidade", "cras/creas", "equipamento", "servico", "territorio", "local", "nome", "cras", "creas"]
APELIDOS_MES = ["mes", "competencia", "referencia", "periodo"]

# Linhas de total que não são unidades (são recalculadas pelo sistema)
PALAVRAS_TOTAL = ["total", "sas", "soma", "geral"]

TIPOS = ["CRAS", "CREAS"]

MESES_PT = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho",
            "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
MESES_ABREV = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def rotulo_mes(mes: str) -> str:
    """'2026-03' -> 'Mar/2026'."""
    ano, m = mes.split("-")
    return f"{MESES_ABREV[int(m) - 1].capitalize()}/{ano}"
