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

from .config import APELIDOS, APELIDOS_MES, APELIDOS_UNIDADE, CAMPOS, MESES_ABREV, PALAVRAS_TOTAL

COLUNAS = ["mes", "unidade", "tipo", *CAMPOS]


@dataclass
class ResultadoImportacao:
    dados: pd.DataFrame
    avisos: list[str] = field(default_factory=list)
    # Totais que vieram escritos no próprio arquivo (linha "Total SAS"), por mês
    totais_informados: dict[str, dict[str, float]] = field(default_factory=dict)


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


def detectar_mes(texto: str) -> str | None:
    """Procura uma competência ('março/2026', '03/2026', '2026-03', 'mar-26') no texto."""
    t = normalizar(texto)
    if not t:
        return None
    m = re.search(r"(20\d{2})[-/_.](0?[1-9]|1[0-2])(?!\d)", t)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    m = re.search(r"(?<!\d)(0?[1-9]|1[0-2])[-/_.](20\d{2})", t)
    if m:
        return f"{m.group(2)}-{int(m.group(1)):02d}"
    nomes = r"(jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez)[a-zç]*"
    m = re.search(nomes + r"\.?[\s/_\-de]*((?:20)?\d{2})(?!\d)", t)
    if m:
        ano = m.group(2)
        ano = int(ano) + 2000 if len(ano) == 2 else int(ano)
        return f"{ano}-{MESES_ABREV.index(m.group(1)) + 1:02d}"
    return None


def inferir_tipo(unidade: str) -> str:
    return "CREAS" if "creas" in normalizar(unidade) else "CRAS"


def eh_linha_total(unidade: str) -> bool:
    n = normalizar(unidade)
    return any(n == p or n.startswith(p + " ") or n.startswith(p + ":") for p in PALAVRAS_TOTAL)


# ---------------------------------------------------- reconhecimento da grade

def _campo_do_cabecalho(texto: str) -> tuple[str | None, int]:
    """Retorna (campo, força do casamento) para um texto de cabeçalho."""
    n = normalizar(texto)
    melhor, forca = None, 0
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
    if col_unid is None:
        # primeira coluna com texto não numérico nas linhas de dados
        for i in range(len(cabecalho)):
            if i in usados or i == col_mes:
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
        registros.append({"mes": mes, "unidade": unidade, "tipo": inferir_tipo(unidade), **valores})

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
    return ResultadoImportacao(dados, avisos, totais)


# --------------------------------------------------------- leitores por formato

def ler_excel(conteudo: bytes, nome: str, mes_padrao: str | None) -> ResultadoImportacao:
    planilhas = pd.read_excel(io.BytesIO(conteudo), sheet_name=None, header=None, dtype=object)
    resultados = []
    for aba, df in planilhas.items():
        grade = df.values.tolist()
        mes = detectar_mes(aba) or _mes_no_topo(grade) or mes_padrao
        r = interpretar_grade(grade, mes, origem=f"{nome} [aba {aba}]")
        if r.dados.empty and len(planilhas) > 1:
            r.avisos = []  # abas sem tabela (gráficos, notas) são ignoradas em silêncio
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
    return interpretar_grade(grade, _mes_no_topo(grade) or mes_padrao, origem=nome)


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
    from bs4 import BeautifulSoup

    texto_pagina = BeautifulSoup(codigo, "html.parser").get_text("\n")
    mes = detectar_mes(texto_pagina[:2000]) or mes_padrao
    tabelas = grade_do_html(codigo)
    if not tabelas:
        return _ler_texto_livre(texto_pagina, nome, mes)
    resultados = [interpretar_grade(g, mes, origem=f"{nome} [tabela {i + 1}]") for i, g in enumerate(tabelas)]
    com_dados = [r for r in resultados if not r.dados.empty]
    if not com_dados:
        return _juntar(resultados)
    return _juntar(com_dados)


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
    if grade:
        r = interpretar_grade(grade, mes, origem=nome)
        if not r.dados.empty:
            return r
    return _ler_texto_livre(texto_total, nome, mes)


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
    if df["mes"].isna().any():
        r.avisos.append("Algumas linhas estão sem mês de referência: informe o mês antes de salvar.")
    chave = df["mes"].fillna("") + "|" + df["unidade"].str.upper()
    if chave.duplicated().any():
        r.avisos.append("Unidades repetidas no mesmo mês foram somadas.")
        df = df.assign(_ord=range(len(df)), _chave=chave)
        agg = {c: "sum" for c in CAMPOS} | {"mes": "first", "unidade": "first", "tipo": "first", "_ord": "first"}
        df = (df.groupby("_chave").agg(agg).sort_values("_ord").drop(columns="_ord")
              .reset_index(drop=True)[COLUNAS])
    for mes, total in r.totais_informados.items():
        parte = df if not mes else df[df["mes"] == mes]
        for campo, valor in total.items():
            soma = parte[campo].sum()
            if abs(soma - valor) > 0.5:
                r.avisos.append(f"{mes or 'Arquivo'}: o total informado de {CAMPOS[campo]} ({valor:,.0f}) "
                                f"difere da soma das unidades ({soma:,.0f}).".replace(",", "."))
    r.dados = df
    return r
