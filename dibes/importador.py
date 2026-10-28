"""Leitura das planilhas de concessão de cestas básicas.

Aceita Excel (.xlsx/.xls), CSV, PDF e HTML (arquivo ou código colado).
Todos os formatos são convertidos numa "grade" (lista de linhas de texto) e
passam pela mesma rotina de reconhecimento: localizar a linha de cabeçalho,
mapear as colunas para os campos analisados e converter os números.
"""

from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass, field

import pandas as pd

from .config import (APELIDOS, APELIDOS_MES, APELIDOS_SAS, APELIDOS_UNIDADE, CAMPOS, IGNORAR_COLUNAS,
                     MESES_ABREV, PALAVRAS_TOTAL)

COLUNAS = ["mes", "sas", "unidade", "tipo", *CAMPOS]
COLUNAS_EMERGENCIA = ["mes", "ocorrencias", "cestas"]


def _sem_emergencias() -> pd.DataFrame:
    return pd.DataFrame(columns=COLUNAS_EMERGENCIA)


@dataclass
class ResultadoImportacao:
    dados: pd.DataFrame
    avisos: list[str] = field(default_factory=list)
    # Totais que vieram escritos no próprio arquivo (linha "Total"), por mês
    totais_informados: dict[str, dict[str, float]] = field(default_factory=dict)
    # Concessões em emergências (localidade/ocorrência e quantidade de cestas), por mês
    emergencias: pd.DataFrame = field(default_factory=_sem_emergencias)


# ---------------------------------------------------------------- utilidades

def normalizar(texto) -> str:
    """Minúsculas, sem acentos e com espaços simples."""
    if texto is None or (isinstance(texto, float) and pd.isna(texto)):
        return ""
    s = unicodedata.normalize("NFKD", str(texto))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip().lower()


def para_numero(valor) -> float | None:
    """Converte valores no formato brasileiro ('1.234', '1.234,5', '12,0') em número."""
    if valor is None:
        return None
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        return None if pd.isna(valor) else float(valor)
    s = str(valor).strip().replace("\xa0", "").replace(" ", "")
    s = s.replace("R$", "").replace("%", "")
    if s in ("", "-", "--", "—", "–"):
        return None
    if not re.fullmatch(r"-?[\d.,]+", s):
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


_PADROES_MES = [
    (re.compile(r"(20\d{2})[-/_.](0?[1-9]|1[0-2])(?!\d)"), lambda m: (int(m[1]), int(m[2]))),
    (re.compile(r"(?<![\d/.-])(0?[1-9]|1[0-2])[-/_.](20\d{2})"), lambda m: (int(m[2]), int(m[1]))),
    (re.compile(r"\b(jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez)[a-zç]*\.?[\s/_\-de]*((?:20)?\d{2})(?!\d)"),
     lambda m: (int(m[2]) + 2000 if len(m[2]) == 2 else int(m[2]), MESES_ABREV.index(m[1]) + 1)),
]


def detectar_mes(texto: str) -> str | None:
    """Procura uma competência ('março/2026', '03/2026', '2026-03', 'mar-26') no texto.
    Vale a que aparece primeiro (o título vem antes de datas de rodapé)."""
    t = normalizar(texto)
    achados = [(m.start(), converter(m)) for padrao, converter in _PADROES_MES for m in [padrao.search(t)] if m]
    if not achados:
        return None
    ano, mes = min(achados)[1]
    return f"{ano}-{mes:02d}"


def inferir_tipo(unidade: str) -> str:
    n = normalizar(unidade)
    if n == "sas" or n.startswith("sas ") or n.startswith("supervisao"):
        return "SAS"
    if "creas" in n:
        return "CREAS"
    if "centro pop" in n or n.startswith("pop "):
        return "Centro POP"
    if "cras" in n:
        return "CRAS"
    return "Outro"


def eh_linha_total(unidade: str) -> bool:
    n = normalizar(unidade)
    return any(n == p or n.startswith(p + " ") or n.startswith(p + ":") for p in PALAVRAS_TOTAL)


# ---------------------------------------------------- reconhecimento da grade

def _campo_do_cabecalho(texto: str) -> tuple[str | None, int]:
    """Retorna (campo, força do casamento) para um texto de cabeçalho."""
    n = normalizar(texto)
    melhor, forca = None, 0
    if any(i in n for i in IGNORAR_COLUNAS):
        return None, 0
    for campo, apelidos in APELIDOS.items():
        for a in apelidos:
            if a in n and len(a) > forca:
                melhor, forca = campo, len(a)
    return melhor, forca


def _mapear_cabecalho(linha: list) -> dict[str, int]:
    """Mapeia campo -> índice de coluna a partir de uma linha de cabeçalho."""
    candidatos = []
    for i, celula in enumerate(linha):
        campo, forca = _campo_do_cabecalho(celula)
        if campo:
            candidatos.append((forca, i, campo))
    mapa: dict[str, int] = {}
    usados: set[int] = set()
    for forca, i, campo in sorted(candidatos, reverse=True):
        if campo not in mapa and i not in usados:
            mapa[campo] = i
            usados.add(i)
    return mapa


def _limpar_grade(grade: list[list]) -> list[list]:
    linhas = []
    for linha in grade:
        celulas = ["" if c is None or (isinstance(c, float) and pd.isna(c)) else c for c in linha]
        if any(str(c).strip() for c in celulas):
            linhas.append(celulas)
    largura = max((len(l) for l in linhas), default=0)
    return [l + [""] * (largura - len(l)) for l in linhas]


def _transpor_se_preciso(grade: list[list]) -> list[list]:
    """Planilhas com os campos nas linhas e as unidades nas colunas são transpostas."""
    if not grade:
        return grade
    campos_na_primeira_coluna = {(_campo_do_cabecalho(l[0])[0]) for l in grade} - {None}
    melhor_linha = max(len(_mapear_cabecalho(l)) for l in grade)
    if len(campos_na_primeira_coluna) >= 3 and len(campos_na_primeira_coluna) > melhor_linha:
        return [list(col) for col in zip(*grade)]
    return grade


def interpretar_grade(grade: list[list], mes_padrao: str | None = None,
                      origem: str = "") -> ResultadoImportacao:
    """Transforma uma grade de células no formato padronizado do sistema."""
    avisos: list[str] = []
    grade = _transpor_se_preciso(_limpar_grade(grade))
    if not grade:
        return ResultadoImportacao(pd.DataFrame(columns=COLUNAS), [f"{origem}: nenhum dado encontrado."])

    # 1) linha de cabeçalho = a que reconhece mais campos (nas primeiras 40 linhas)
    idx_cab, mapa = -1, {}
    for i, linha in enumerate(grade[:40]):
        m = _mapear_cabecalho(linha)
        if len(m) > len(mapa):
            idx_cab, mapa = i, m
    if len(mapa) < 2:
        return ResultadoImportacao(pd.DataFrame(columns=COLUNAS), [
            f"{origem}: não encontrei o cabeçalho com os campos (Cota Disponível, Quantidade "
            "Solicitada, Demanda Registrada, Atendimento Social, Recibos Emitidos, Cestas Concedidas)."])
    cabecalho = grade[idx_cab]
    faltando = [CAMPOS[c] for c in CAMPOS if c not in mapa]
    if faltando:
        avisos.append(f"{origem}: campos não encontrados (ficarão em branco): {', '.join(faltando)}.")

    # 2) coluna da unidade e (opcional) do mês
    usados = set(mapa.values())
    col_mes = next((i for i, c in enumerate(cabecalho) if i not in usados
                    and any(normalizar(c).startswith(a) for a in APELIDOS_MES)), None)
    col_unid = next((i for i, c in enumerate(cabecalho) if i not in usados and i != col_mes
                     and any(a in normalizar(c) for a in APELIDOS_UNIDADE)), None)
    col_sas = next((i for i, c in enumerate(cabecalho) if i not in usados and i not in (col_mes, col_unid)
                    and any(re.search(rf"\b{a}\b", normalizar(c)) for a in APELIDOS_SAS)), None)
    if col_unid is None:
        # primeira coluna com texto não numérico nas linhas de dados
        for i in range(len(cabecalho)):
            if i in usados or i in (col_mes, col_sas):
                continue
            valores = [l[i] for l in grade[idx_cab + 1:] if str(l[i]).strip()]
            if valores and sum(para_numero(v) is None for v in valores) > len(valores) / 2:
                col_unid = i
                break
    if col_unid is None:
        return ResultadoImportacao(pd.DataFrame(columns=COLUNAS),
                                   [f"{origem}: não encontrei a coluna com o nome das unidades (CRAS/CREAS)."])

    # 3) linhas de dados
    registros, totais = [], {}
    mes_corrente = mes_padrao
    for linha in grade[idx_cab + 1:]:
        unidade = re.sub(r"\s+", " ", str(linha[col_unid])).strip()
        valores = {c: para_numero(linha[i]) for c, i in mapa.items()}
        if not unidade:
            continue
        if all(v is None for v in valores.values()):
            # cabeçalho repetido ou subtítulo; um subtítulo "MARÇO/2026" muda a competência
            novo_mes = detectar_mes(unidade)
            if novo_mes and col_mes is None:
                mes_corrente = novo_mes
            continue
        mes = mes_corrente
        if col_mes is not None and str(linha[col_mes]).strip():
            mes = detectar_mes(str(linha[col_mes])) or mes_padrao
        if eh_linha_total(unidade):
            totais[mes or ""] = {c: v for c, v in valores.items() if v is not None}
            continue
        tipo = inferir_tipo(unidade)
        sas = unidade if tipo == "SAS" else (str(linha[col_sas]).strip() if col_sas is not None else "")
        registros.append({"mes": mes, "sas": sas or None, "unidade": unidade, "tipo": tipo, **valores})

    df = pd.DataFrame(registros, columns=COLUNAS)
    if df.empty:
        avisos.append(f"{origem}: cabeçalho encontrado, mas nenhuma linha de unidade com valores.")
    return ResultadoImportacao(df, avisos, totais)


def _juntar(resultados: list[ResultadoImportacao]) -> ResultadoImportacao:
    validos = [r.dados for r in resultados if not r.dados.empty]
    dados = pd.concat(validos, ignore_index=True) if validos else pd.DataFrame(columns=COLUNAS)
    avisos = [a for r in resultados for a in r.avisos]
    totais: dict = {}
    for r in resultados:
        totais.update(r.totais_informados)
    emerg = [r.emergencias for r in resultados if not r.emergencias.empty]
    emerg = resumir_emergencias(pd.concat(emerg, ignore_index=True)) if emerg else _sem_emergencias()
    return ResultadoImportacao(dados, avisos, totais, emerg)


def _eh_contagem(texto: str) -> bool:
    """Cabeçalho de quantidade de ocorrências (ex.: 'N.º de ocorrências'), e não do nome da ocorrência."""
    return "ocorrencia" in texto and "localidade" not in texto and (
        texto.startswith(("n.", "n ", "no ", "numero", "qtd", "quant", "total")) or "ocorrencias" in texto)


def ler_emergencias(grade: list[list], mes_padrao: str | None) -> pd.DataFrame:
    """Emergências por mês: n.º de ocorrências e de cestas concedidas.

    Aceita a lista de ocorrências ('Localidade / Ocorrência' + 'Qtd. de Cestas', cada linha conta uma
    ocorrência; os nomes não são guardados) ou o resumo mensal ('Mês', 'N.º de ocorrências', 'Cestas')."""
    grade = _limpar_grade(grade)
    for i, linha in enumerate(grade[:40]):
        textos = [normalizar(c) for c in linha]
        col_n = next((j for j, t in enumerate(textos) if _eh_contagem(t)), None)
        col_oc = next((j for j, t in enumerate(textos) if j != col_n
                       and any(p in t for p in ("ocorrencia", "localidade", "emergencia"))), None)
        col_qt = next((j for j, t in enumerate(textos) if j not in (col_oc, col_n)
                       and any(p in t for p in ("qtd", "quantidade", "cestas"))), None)
        if col_qt is None or (col_oc is None and col_n is None):
            continue
        # coluna "Ocorrências" só com números: é a contagem, não o nome
        if col_n is None and all(para_numero(l[col_oc]) is not None for l in grade[i + 1:] if str(l[col_oc]).strip()):
            col_n, col_oc = col_oc, None
        col_mes = next((j for j, t in enumerate(textos) if j not in (col_oc, col_qt, col_n)
                        and any(t.startswith(a) for a in APELIDOS_MES)), None)
        linhas = []
        for l in grade[i + 1:]:
            cestas = para_numero(l[col_qt])
            if col_oc is not None:
                nome = re.sub(r"\s+", " ", str(l[col_oc])).strip()
                if not nome or eh_linha_total(nome):
                    continue
                n = 1
            else:
                n = para_numero(l[col_n])
                if col_mes is not None and eh_linha_total(str(l[col_mes])):
                    continue
            if cestas is None and n is None:
                continue
            mes = (detectar_mes(str(l[col_mes])) if col_mes is not None and str(l[col_mes]).strip() else None)
            if mes is None and col_mes is not None and hasattr(l[col_mes], "strftime"):
                mes = l[col_mes].strftime("%Y-%m")
            linhas.append({"mes": mes or mes_padrao, "ocorrencias": n, "cestas": cestas})
        return resumir_emergencias(pd.DataFrame(linhas, columns=COLUNAS_EMERGENCIA))
    return _sem_emergencias()


def resumir_emergencias(emerg: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por mês, somando ocorrências e cestas (mês ainda indefinido fica numa linha própria)."""
    if emerg.empty:
        return _sem_emergencias()
    return (emerg.groupby(emerg["mes"].fillna(""), as_index=False)
            .agg(ocorrencias=("ocorrencias", lambda v: v.sum(min_count=1)),
                 cestas=("cestas", lambda v: v.sum(min_count=1)))
            .assign(mes=lambda d: d["mes"].replace("", None))[COLUNAS_EMERGENCIA])


# --------------------------------------------------------- leitores por formato

def ler_excel(conteudo: bytes, nome: str, mes_padrao: str | None) -> ResultadoImportacao:
    planilhas = pd.read_excel(io.BytesIO(conteudo), sheet_name=None, header=None, dtype=object)
    resultados = []
    for aba, df in planilhas.items():
        grade = df.values.tolist()
        mes = detectar_mes(aba) or _mes_no_topo(grade) or mes_padrao
        r = interpretar_grade(grade, mes, origem=f"{nome} [aba {aba}]")
        r.emergencias = ler_emergencias(grade, mes)
        if r.dados.empty and (len(planilhas) > 1 or not r.emergencias.empty):
            r.avisos = []  # abas sem tabela (gráficos, notas) ou só de emergências: sem aviso
        resultados.append(r)
    return _juntar(resultados)


def ler_csv(conteudo: bytes, nome: str, mes_padrao: str | None) -> ResultadoImportacao:
    for codificacao in ("utf-8-sig", "latin-1"):
        try:
            texto = conteudo.decode(codificacao)
            break
        except UnicodeDecodeError:
            continue
    primeira = texto.splitlines()[0] if texto else ""
    sep = max([";", ",", "\t", "|"], key=primeira.count)
    df = pd.read_csv(io.StringIO(texto), sep=sep, header=None, dtype=str, keep_default_na=False,
                     engine="python", on_bad_lines="skip")
    grade = df.values.tolist()
    mes = _mes_no_topo(grade) or mes_padrao
    r = interpretar_grade(grade, mes, origem=nome)
    r.emergencias = ler_emergencias(grade, mes)
    if r.dados.empty and not r.emergencias.empty:
        r.avisos = []
    return r


def grade_do_html(codigo: str) -> list[list[list[str]]]:
    """Extrai todas as tabelas (<table>) de um código HTML como grades de texto."""
    from bs4 import BeautifulSoup

    sopa = BeautifulSoup(codigo, "html.parser")
    tabelas = []
    for tabela in sopa.find_all("table"):
        grade = []
        for tr in tabela.find_all("tr"):
            linha = []
            for celula in tr.find_all(["td", "th"]):
                texto = celula.get_text(" ", strip=True)
                linha.extend([texto] * int(celula.get("colspan", 1) or 1))
            grade.append(linha)
        tabelas.append(grade)
    return tabelas


def ler_html(codigo: str, nome: str, mes_padrao: str | None) -> ResultadoImportacao:
    r = _ler_html_principal(codigo, nome, mes_padrao)
    emerg = [ler_emergencias(g, None) for g in grade_do_html(codigo)]
    emerg = [e for e in emerg if not e.empty]
    if emerg:
        mes = r.dados["mes"].dropna().iloc[0] if not r.dados.empty and r.dados["mes"].notna().any() else None
        r.emergencias = pd.concat(emerg, ignore_index=True)
        r.emergencias["mes"] = r.emergencias["mes"].fillna(mes or _mes_da_pagina(codigo) or mes_padrao)
        r.emergencias = resumir_emergencias(r.emergencias)
        if r.dados.empty:
            r.avisos = []
    return r


def _mes_da_pagina(codigo: str) -> str | None:
    from bs4 import BeautifulSoup

    sopa = BeautifulSoup(codigo, "html.parser")
    for marca in sopa(["style", "script"]):
        marca.decompose()
    return detectar_mes(sopa.get_text("\n")[:3000])


def _ler_html_principal(codigo: str, nome: str, mes_padrao: str | None) -> ResultadoImportacao:
    from bs4 import BeautifulSoup

    sopa = BeautifulSoup(codigo, "html.parser")
    for marca in sopa(["style", "script"]):
        marca.decompose()
    texto_pagina = sopa.get_text("\n")
    mes = detectar_mes(texto_pagina[:3000]) or mes_padrao

    # Painéis HTML costumam trazer os dados em listas JavaScript e montar a tabela no navegador
    listas = ler_listas_js(codigo, nome, mes)
    if listas is not None:
        return listas
    tabelas = grade_do_html(codigo)
    if not tabelas:
        return _ler_texto_livre(texto_pagina, nome, mes)
    resultados = [interpretar_grade(g, mes, origem=f"{nome} [tabela {i + 1}]") for i, g in enumerate(tabelas)]
    com_dados = [r for r in resultados if not r.dados.empty]
    if not com_dados:
        return _juntar(resultados)
    return _juntar(com_dados)


_RE_LISTA = re.compile(r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*\[(.*?)\]\s*;", re.S)
_RE_OBJETO = re.compile(r"\{([^{}]*)\}")
_RE_PAR = re.compile(r"""([A-Za-z_$][\w$]*|"[^"]*"|'[^']*')\s*:\s*("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|-?\d+(?:\.\d+)?)""")


def grades_js(codigo: str) -> dict[str, list[list]]:
    """Listas de objetos JavaScript (const dados = [{nome:"...", cotas:10}, ...]) como grades."""
    grades = {}
    for nome_lista, corpo in _RE_LISTA.findall(codigo):
        if "[" in corpo:
            continue  # listas dentro de listas (ex.: histórico por mês de cada SAS) não são tabela de unidades
        objetos = []
        for obj in _RE_OBJETO.findall(corpo):
            pares = {}
            for chave, valor in _RE_PAR.findall(obj):
                chave = chave.strip("\"'")
                if valor[:1] in "\"'":
                    valor = valor[1:-1].replace("\\'", "'").replace('\\"', '"')
                else:
                    valor = float(valor)
                pares[chave] = valor
            if pares:
                objetos.append(pares)
        if not objetos:
            continue
        chaves = list(dict.fromkeys(k for o in objetos for k in o))
        # "cestasRecebidas" -> "cestas Recebidas", para casar com os apelidos das colunas
        cabecalho = [re.sub(r"(?<=[a-z])(?=[A-Z])", " ", k) for k in chaves]
        grades[nome_lista] = [cabecalho, *[[o.get(k, "") for k in chaves] for o in objetos]]
    return grades


def _cabecalho_html(codigo: str) -> list[str]:
    """Títulos da tabela da página (ex.: 'Cestas Solicitadas'), mesmo que a tabela venha vazia."""
    for tabela in grade_do_html(codigo):
        for linha in tabela[:3]:
            if len(_mapear_cabecalho(linha)) >= 3:
                return linha
    return []


def _completar_chaves(cabecalho: list[str], titulos: list[str]) -> list[str]:
    """Troca chaves abreviadas da lista JavaScript (ex.: 'sol') pelo título da coluna na mesma posição
    da tabela da página — só quando as chaves já reconhecidas estão nas mesmas posições dos títulos."""
    if not titulos:
        return cabecalho
    campos_chave = [_campo_do_cabecalho(c)[0] for c in cabecalho]
    campos_titulo = [_campo_do_cabecalho(t)[0] for t in titulos]
    alinhado = all(c is None or (i < len(campos_titulo) and campos_titulo[i] == c)
                   for i, c in enumerate(campos_chave))
    if not alinhado or sum(c is not None for c in campos_chave) < 2:
        return cabecalho
    return [titulos[i] if c is None and i < len(titulos) and campos_titulo[i] else cabecalho[i]
            for i, c in enumerate(campos_chave)]


def ler_listas_js(codigo: str, nome: str, mes: str | None) -> ResultadoImportacao | None:
    resultados = []
    titulos = _cabecalho_html(codigo)
    for nome_lista, grade in grades_js(codigo).items():
        grade = [_completar_chaves(grade[0], titulos), *grade[1:]]
        r = interpretar_grade(grade, mes, origem=f"{nome} [{nome_lista}]")
        if not r.dados.empty:
            resultados.append(r)
    if not resultados:
        return None
    return _juntar(resultados)


def deduzir_sas(r: ResultadoImportacao) -> None:
    """Em cada mês com linhas de SAS e unidades sem SAS, descobre a SAS de cada unidade."""
    df = r.dados
    for mes, parte in df.groupby(df["mes"].fillna("")):
        unidades, sas = parte[parte["tipo"] != "SAS"], parte[parte["tipo"] == "SAS"]
        if unidades.empty or sas.empty or unidades["sas"].notna().any():
            continue
        grupos, acertos = atribuir_sas(unidades, sas)
        if grupos is None:
            continue
        df.loc[unidades.index, "sas"] = grupos
        if acertos < 0.8:
            r.avisos.append(f"{mes or 'Arquivo'}: a SAS de algumas unidades foi deduzida com pouca segurança "
                            "(as somas não batem com os totais das SAS). Confira a coluna SAS na prévia.")


_PALAVRAS_GENERICAS = {"sas", "cras", "creas", "centro", "pop", "de", "do", "da", "dos", "das", "ii", "iii"}


def _palavras(nome: str) -> set[str]:
    return {p for p in re.split(r"[^a-z0-9]+", normalizar(nome)) if len(p) > 1} - _PALAVRAS_GENERICAS


def atribuir_sas(unidades: pd.DataFrame, sas: pd.DataFrame) -> tuple[list[str] | None, float]:
    """Descobre a SAS de cada unidade quando o arquivo lista as SAS e, separadamente, as unidades
    na mesma ordem (sem dizer a qual SAS cada unidade pertence).

    Divide a lista de unidades em blocos consecutivos — um por SAS — de modo que a soma de cada
    bloco fique o mais próxima possível dos valores da SAS. Retorna a SAS de cada unidade e a
    fração de SAS cujo bloco bate exatamente em pelo menos 4 dos 6 campos.
    """
    import numpy as np

    u = unidades[list(CAMPOS)].fillna(0).to_numpy(float)
    alvo = sas[list(CAMPOS)].to_numpy(float)
    peso = (~np.isnan(alvo)).astype(float)  # campo ausente na SAS (ex.: coluna cortada) não conta
    alvo = np.nan_to_num(alvo)
    n, k = len(u), len(alvo)
    if n < k:
        return None, 0.0
    acumulado = np.vstack([np.zeros(len(CAMPOS)), np.cumsum(u, axis=0)])
    # desempate pelo nome: unidades zeradas na fronteira entre duas SAS ficam com a de nome parecido
    nomes_sas = [_palavras(x) for x in sas["unidade"]]
    nomes_unid = [_palavras(x) or {""} for x in unidades["unidade"]]
    sem_nome = np.array([[0.01 * (1 - len(nu & ns) / len(nu)) for nu in nomes_unid] for ns in nomes_sas])
    pena = np.hstack([np.zeros((k, 1)), np.cumsum(sem_nome, axis=1)])
    custo = np.full((k + 1, n + 1), np.inf)
    custo[0, 0] = 0
    corte = np.zeros((k + 1, n + 1), dtype=int)
    for j in range(1, k + 1):
        for i in range(j, n - (k - j) + 1):
            inicio = np.arange(j - 1, i)
            c = (custo[j - 1, inicio]
                 + (np.abs(acumulado[i] - acumulado[inicio] - alvo[j - 1]) * peso[j - 1]).sum(axis=1)
                 + pena[j - 1, i] - pena[j - 1, inicio])
            melhor = int(np.argmin(c))
            custo[j, i], corte[j, i] = c[melhor], inicio[melhor]
    grupos, fim, exatos = [""] * n, n, 0
    nomes = sas["unidade"].tolist()
    for j in range(k, 0, -1):
        inicio = corte[j, fim]
        grupos[inicio:fim] = [nomes[j - 1]] * (fim - inicio)
        iguais = (np.isclose(acumulado[fim] - acumulado[inicio], alvo[j - 1]) * peso[j - 1]).sum()
        exatos += iguais >= min(4, peso[j - 1].sum())
        fim = inicio
    return grupos, exatos / k


def ler_pdf(conteudo: bytes, nome: str, mes_padrao: str | None) -> ResultadoImportacao:
    import pdfplumber

    grade, texto = [], []
    with pdfplumber.open(io.BytesIO(conteudo)) as pdf:
        for pagina in pdf.pages:
            texto.append(pagina.extract_text() or "")
            for tabela in pagina.extract_tables():
                grade.extend(tabela)
        texto_total = "\n".join(texto)
        mes = detectar_mes(texto_total[:1000]) or mes_padrao
        # PDFs impressos de páginas web: monta a tabela pela posição das palavras
        posicional = _ler_pdf_posicional(pdf, nome, mes)
    if posicional is not None:
        return posicional
    if grade:
        r = interpretar_grade(grade, mes, origem=nome)
        if not r.dados.empty:
            return r
    return _ler_texto_livre(texto_total, nome, mes)


# palavras (normalizadas) que identificam o título de cada coluna num PDF
_TITULOS_PDF = {
    "cota_disponivel": {"cota", "cotas"},
    "quantidade_solicitada": {"solicitada", "solicitadas", "recebidas"},
    "demanda_registrada": {"demanda"},
    "atendimento_social": {"atendimento", "atendimentos", "tecnico"},
    "recibos_emitidos": {"recibos", "validos", "emitidos"},
    "cestas_concedidas": {"concedidas", "entregues"},
}


def _linhas_pdf(pagina, tolerancia: float = 3) -> list[list[dict]]:
    linhas: list[list[dict]] = []
    for w in sorted(pagina.extract_words(), key=lambda w: (round(w["top"]), w["x0"])):
        if linhas and abs(w["top"] - linhas[-1][0]["top"]) <= tolerancia:
            linhas[-1].append(w)
        else:
            linhas.append([w])
    return linhas


def _cabecalho_pdf(linhas: list[list[dict]]) -> tuple[dict[str, tuple[float, float]], float] | None:
    """Procura o título da tabela (pode ocupar 2 ou 3 linhas). Retorna campo -> (x0, x1) e o fim do título."""
    for i, linha in enumerate(linhas):
        if any(para_numero(w["text"]) is not None for w in linha) or len(linha) > 10:
            continue
        bloco = [l for l in linhas[max(0, i - 2):i + 3] if abs(l[0]["top"] - linha[0]["top"]) <= 20
                 and not any(para_numero(w["text"]) is not None for w in l)]
        colunas: dict[str, tuple[float, float]] = {}
        for w in (w for l in bloco for w in l):
            n = normalizar(w["text"]).strip(".:")
            for campo, titulos in _TITULOS_PDF.items():
                if n in titulos:
                    x0, x1 = colunas.get(campo, (w["x0"], w["x1"]))
                    colunas[campo] = (min(x0, w["x0"]), max(x1, w["x1"]))
        if len(colunas) >= 3:
            return colunas, max(w["bottom"] for l in bloco for w in l)
    return None


def _ler_pdf_posicional(pdf, nome: str, mes: str | None) -> ResultadoImportacao | None:
    """Lê tabelas de PDFs impressos do navegador, em que o nome da unidade pode quebrar em várias
    linhas (acima e abaixo dos números) e colunas podem ter sido cortadas na margem."""
    colunas = None
    linhas_tabela: list[list] = []
    for pagina in pdf.pages:
        linhas = _linhas_pdf(pagina)
        achado = _cabecalho_pdf(linhas)
        inicio = -1.0
        if achado:
            colunas, inicio = achado
        if not colunas:
            continue
        centros = {c: (x0 + x1) / 2 for c, (x0, x1) in colunas.items()}
        ordenados = sorted(centros.values())
        folga = min((b - a for a, b in zip(ordenados, ordenados[1:])), default=60) / 2
        limite_nome = min(x0 for x0, _ in colunas.values()) - 2

        def coluna_do_numero(w):
            cx = (w["x0"] + w["x1"]) / 2
            for c, (x0, x1) in colunas.items():
                if x0 - 2 <= cx <= x1 + 2:
                    return c
            c, centro = min(centros.items(), key=lambda kv: abs(kv[1] - cx))
            return c if abs(centro - cx) <= folga else None  # número fora das colunas (ex.: coluna cortada)

        com_numeros, so_nome = [], []
        for linha in linhas:
            if linha[0]["top"] <= inicio:
                continue
            valores, partes = {}, []
            for w in linha:
                v = para_numero(w["text"])
                if v is not None and w["x0"] >= limite_nome:
                    c = coluna_do_numero(w)
                    if c and c not in valores:
                        valores[c] = v
                elif w["x1"] <= limite_nome + 1:
                    partes.append(w["text"])
            if len(valores) >= 3:
                com_numeros.append({"top": linha[0]["top"], "partes": [(linha[0]["top"], " ".join(partes))],
                                    "valores": valores})
            elif partes and len(partes) == len(linha) and re.search(r"[A-Za-zÀ-ÿ]", " ".join(partes)):
                so_nome.append((linha[0]["top"], " ".join(partes)))
        # pedaços de nome acima/abaixo dos números pertencem à linha de números mais próxima
        for top, texto in so_nome:
            if com_numeros:
                alvo = min(com_numeros, key=lambda r: abs(r["top"] - top))
                if abs(alvo["top"] - top) <= 20:
                    alvo["partes"].append((top, texto))
        for r in com_numeros:
            nome_unid = " ".join(t for _, t in sorted(r["partes"]) if t).strip()
            if nome_unid:
                linhas_tabela.append([nome_unid, *[r["valores"].get(c) for c in colunas]])
    if not linhas_tabela:
        return None
    titulo = ["Unidade", *[CAMPOS[c] for c in colunas]]
    r = interpretar_grade([titulo, *linhas_tabela], mes, origem=nome)
    if len(colunas) < len(CAMPOS):
        r.avisos.append(f"{nome}: alguma coluna pode ter sido cortada na impressão do PDF. Se a página tiver "
                        "o painel por CRAS/CREAS, importe os dois PDFs juntos: os campos que faltarem nas SAS "
                        "serão somados a partir das unidades. Outra opção é colar o código HTML do painel.")
    return r


def _ler_texto_livre(texto: str, nome: str, mes: str | None) -> ResultadoImportacao:
    """Último recurso (PDF sem tabela desenhada): cada linha 'Nome  n1 n2 ... n6'."""
    linhas = [l.strip() for l in texto.splitlines() if l.strip()]
    grade = []
    padrao = re.compile(r"^(.*?[A-Za-zÀ-ÿ].*?)\s+((?:-?[\d.,]+|-)(?:\s+(?:-?[\d.,]+|-))+)\s*$")
    cabecalho = None
    for l in linhas:
        if cabecalho is None and sum(_campo_do_cabecalho_parcial(l, c) for c in APELIDOS) >= 3:
            cabecalho = l
            continue
        m = padrao.match(l)
        if m:
            numeros = m.group(2).split()
            extras = len(numeros) - len(CAMPOS)
            if extras > 0:  # números que fazem parte do nome ("CRAS 2 Centro ...")
                nome_unid = " ".join([m.group(1), *numeros[:extras]])
                numeros = numeros[extras:]
            else:
                nome_unid = m.group(1)
            grade.append([nome_unid, *numeros])
    if not grade:
        return ResultadoImportacao(pd.DataFrame(columns=COLUNAS), [f"{nome}: nenhuma tabela encontrada."])
    ordem = _ordem_campos_no_texto(cabecalho) if cabecalho else list(CAMPOS)
    largura = max(len(g) for g in grade)
    titulo = ["Unidade", *[CAMPOS[c] for c in ordem]][:largura]
    r = interpretar_grade([titulo, *grade], mes, origem=nome)
    r.avisos.append(f"{nome}: tabela lida a partir do texto do documento — confira os valores na prévia.")
    return r


def _campo_do_cabecalho_parcial(texto: str, campo: str) -> bool:
    n = normalizar(texto)
    return any(a in n for a in APELIDOS[campo])


def _ordem_campos_no_texto(texto: str) -> list[str]:
    n = normalizar(texto)
    posicoes = []
    for campo, apelidos in APELIDOS.items():
        achados = [n.find(a) for a in apelidos if a in n]
        if achados:
            posicoes.append((min(achados), campo))
    return [c for _, c in sorted(posicoes)] or list(CAMPOS)


def _mes_no_topo(grade: list[list]) -> str | None:
    """Procura a competência nas primeiras linhas (título da planilha)."""
    for linha in grade[:6]:
        for celula in linha:
            if isinstance(celula, pd.Timestamp) or hasattr(celula, "strftime"):
                try:
                    return celula.strftime("%Y-%m")
                except ValueError:
                    continue
            mes = detectar_mes(str(celula)) if isinstance(celula, str) else None
            if mes:
                return mes
    return None


def importar_arquivo(conteudo: bytes, nome: str, mes_padrao: str | None = None) -> ResultadoImportacao:
    """Ponto de entrada: escolhe o leitor pela extensão do arquivo."""
    ext = nome.lower().rsplit(".", 1)[-1]
    mes_padrao = detectar_mes(nome) or mes_padrao
    if ext in ("xlsx", "xlsm", "xls", "ods"):
        r = ler_excel(conteudo, nome, mes_padrao)
    elif ext in ("csv", "txt", "tsv"):
        r = ler_csv(conteudo, nome, mes_padrao)
    elif ext == "pdf":
        r = ler_pdf(conteudo, nome, mes_padrao)
    elif ext in ("html", "htm"):
        r = ler_html(conteudo.decode("utf-8", errors="replace"), nome, mes_padrao)
    else:
        raise ValueError(f"Formato não suportado: .{ext}")
    return finalizar(r)


def importar_html_colado(codigo: str, mes_padrao: str | None = None) -> ResultadoImportacao:
    return finalizar(ler_html(codigo, "Código HTML", mes_padrao))


def finalizar(r: ResultadoImportacao) -> ResultadoImportacao:
    """Ajustes comuns: agrega unidades repetidas e confere o total informado no arquivo."""
    df = r.dados
    if df.empty:
        return r
    deduzir_sas(r)
    if df["mes"].isna().any():
        r.avisos.append("Algumas linhas estão sem mês de referência: informe o mês antes de salvar.")
    chave = df["mes"].fillna("") + "|" + df["unidade"].str.upper()
    if chave.duplicated().any():
        r.avisos.append("Unidades repetidas no mesmo mês foram somadas.")
        df = df.assign(_ord=range(len(df)), _chave=chave)
        agg = {c: "sum" for c in CAMPOS} | {k: "first" for k in ("mes", "sas", "unidade", "tipo", "_ord")}
        df = (df.groupby("_chave").agg(agg).sort_values("_ord").drop(columns="_ord")
              .reset_index(drop=True)[COLUNAS])
    for mes, total in r.totais_informados.items():
        parte = df if not mes else df[df["mes"] == mes]
        # o total do arquivo corresponde à soma das SAS, quando elas existem; senão, à das unidades
        parte = parte[parte["tipo"] == "SAS"] if (parte["tipo"] == "SAS").any() else parte
        for campo, valor in total.items():
            soma = parte[campo].sum()
            if abs(soma - valor) > 0.5:
                r.avisos.append(f"{mes or 'Arquivo'}: o total informado de {CAMPOS[campo]} ({valor:,.0f}) "
                                f"difere da soma das linhas ({soma:,.0f}).".replace(",", "."))
    r.dados = df
    return r
