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
    "cota_disponivel": ["cota disponivel", "cotas", "cota"],
    "quantidade_solicitada": ["quantidade solicitada", "qtd solicitada", "qtde solicitada", "solicitad",
                              "cestas recebidas", "recebidas"],
    "demanda_registrada": ["demanda registrada", "demanda pelo beneficio", "demanda"],
    "atendimento_social": ["atendimento social", "registros de atendimento tecnico", "registros de atend",
                           "atendimento tecnico", "atend. tecnico", "atendimentos sociais", "atendimento"],
    "recibos_emitidos": ["quantidade de recibos", "recibos emitidos", "recibos validos", "recibo"],
    "cestas_concedidas": ["cestas concedidas", "quantidade de cestas", "cestas entregues", "entregues", "concedid"],
}

# Colunas calculadas nos relatórios de origem, que o sistema recalcula (não são importadas)
IGNORAR_COLUNAS = ["sem registro", "estoque", "taxa", "%"]

APELIDOS_UNIDADE = ["unidade", "cras/creas", "equipamento", "servico", "territorio", "local", "nome", "name",
                    "cras", "creas"]
APELIDOS_SAS = ["sas", "supervisao"]
APELIDOS_MES = ["mes", "competencia", "referencia", "periodo"]

# Linhas de total que não são unidades (são recalculadas pelo sistema)
PALAVRAS_TOTAL = ["total", "soma", "geral"]

# "SAS" = linha de uma Supervisão de Assistência Social (soma das suas unidades)
TIPOS = ["SAS", "CRAS", "CREAS", "Centro POP", "Outro"]
TIPOS_UNIDADE = TIPOS[1:]
SEM_SAS = "(sem SAS)"

MESES_PT = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho",
            "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
MESES_ABREV = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]


def rotulo_mes(mes: str) -> str:
    """'2026-03' -> 'Mar/2026'."""
    ano, m = mes.split("-")
    return f"{MESES_ABREV[int(m) - 1].capitalize()}/{ano}"
