"""Importação de planilhas (Excel/CSV) e PDFs para o Monitoramento Anual DIBES.

Formatos reconhecidos:
- quadro anual: indicadores nas linhas e meses nas colunas (Jan..Dez) — o modelo, o Excel e o PDF do sistema;
- meses nas linhas e indicadores nas colunas;
- lista: colunas Mês, Indicador e Valor (e, opcional, Atividade);
- formulário de um mês: indicador e valor (o mês vem do arquivo ou da tela).
Linhas calculadas (totais, custos médios, taxas) são ignoradas; o sistema recalcula.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

import pandas as pd

from . import anual
from .config import MESES_ABREV
from .importador import detectar_mes, normalizar, para_numero

COLUNAS = ["mes", "atividade", "indicador", "valor"]

# nome da atividade (normalizado) que aparece como título de seção ou na coluna "Atividade"
SECOES = {
    anual.ALIMENTACAO: ["alimentacao", "cesta"],
    anual.PASSAGENS: ["passage"],
    anual.SIGRC: ["sigrc"],
    anual.SEI: ["sei"],
    anual.PBF: ["pbf", "bolsa familia"],
    anual.OUTROS: ["outros", "outras"],
}

# apelidos dos indicadores; vence o apelido mais longo contido no texto
APELIDOS = {
    "cestas_concedidas_sas": ["cestas concedidas (sas", "cestas concedidas sas", "cestas concedidas pelas sas",
                              "cestas concedidas por sas", "concedidas pelas unidades", "cestas concedidas"],
    "cestas_emergencias": ["emergencia"],
    "cestas_compradas": ["cestas compradas", "cestas adquiridas"],
    "valor_cestas": ["valor gasto com cestas", "valor das cestas", "valor cestas", "gasto com cestas"],
    "solicitacoes": ["solicitacoes", "solicitacao", "pedidos"],
    "solicitacoes_atendidas": ["solicitacoes atendidas", "atendidas"],
    "pessoas_beneficiadas": ["pessoas beneficiadas", "beneficiad"],
    "passagens_compradas": ["passagens compradas", "passagens adquiridas"],
    "passagens_nao_utilizadas": ["nao utilizad"],
    "valor_passagens": ["valor gasto com passagens", "valor das passagens", "valor passagens",
                        "gasto com passagens"],
    "protocolos_respondidos": ["protocolos respondidos", "protocolos", "sigrc"],
    "processos_respondidos": ["processos sei respondidos", "processos respondidos", "processos sei",
                              "processos", "sei"],
    "manutencoes_lote": ["em lote", "lote"],
    "manutencoes_manuais": ["manualmente", "manuais", "manual"],
}
# termos genéricos que dependem da seção em que aparecem
GENERICOS = {
    "valor": {anual.ALIMENTACAO: "valor_cestas", anual.PASSAGENS: "valor_passagens"},
    "gasto": {anual.ALIMENTACAO: "valor_cestas", anual.PASSAGENS: "valor_passagens"},
    "compradas": {anual.ALIMENTACAO: "cestas_compradas", anual.PASSAGENS: "passagens_compradas"},
    "adquiridas": {anual.ALIMENTACAO: "cestas_compradas", anual.PASSAGENS: "passagens_compradas"},
}
# linhas calculadas ou de total: o sistema recalcula
CALCULADOS = ["custo medio", "taxa de", "total de", "% das", "(%)", "percentual"]
CABECALHOS = ["indicador", "atividade", "descricao", "item"]


@dataclass
class ResultadoAnual:
    dados: pd.DataFrame
    avisos: list[str] = field(default_factory=list)


def _vazio() -> pd.DataFrame:
    return pd.DataFrame(columns=COLUNAS)


def mes_da_coluna(texto, ano: str | None) -> str | None:
    """'Jan', 'Janeiro', 'jan/2026', '01/2026', '2026-01' -> 'AAAA-MM' (com o ano do arquivo, se faltar)."""
    if texto is None or (isinstance(texto, float) and pd.isna(texto)):
        return None
    if hasattr(texto, "strftime"):
        return texto.strftime("%Y-%m")
    completo = detectar_mes(str(texto))
    if completo:
        return completo
    n = normalizar(texto).strip(" .:")
    m = re.fullmatch(r"(jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez)[a-zç]*\.?", n)
    if m and ano:
        return f"{ano}-{MESES_ABREV.index(m[1]) + 1:02d}"
    return None


def secao_do_texto(texto: str) -> str | None:
    n = normalizar(texto)
    for atividade, chaves in SECOES.items():
        if any(re.search(rf"\b{re.escape(c)}", n) for c in chaves):
            return atividade
    return None


def indicador_do_texto(texto: str, secao: str | None) -> str | None:
    """Indicador do catálogo para um rótulo; None se não reconhecer ou se for linha calculada."""
    n = normalizar(texto).replace("n.º", "").replace("nº", "")
    if not n or any(c in n for c in CALCULADOS):
        return None
    candidatos = []
    for indicador, apelidos in APELIDOS.items():
        for a in apelidos:
            if a in n:
                candidatos.append((len(a), anual.ATIVIDADE_DO[indicador] == secao, indicador))
    for termo, por_secao in GENERICOS.items():
        if re.search(rf"\b{termo}\b", n) and secao in por_secao:
            candidatos.append((len(termo), True, por_secao[secao]))
    if not candidatos:
        return None
    # mais longo vence; no empate, o da seção atual
    return max(candidatos)[2]


def _limpar(grade: list[list]) -> list[list]:
    linhas = []
    for linha in grade:
        celulas = ["" if c is None or (isinstance(c, float) and pd.isna(c)) else c for c in linha]
        if any(str(c).strip() for c in celulas):
            linhas.append(celulas)
    largura = max((len(l) for l in linhas), default=0)
    return [l + [""] * (largura - len(l)) for l in linhas]


def _ano_do_texto(texto: str) -> str | None:
    m = re.search(r"(?<!\d)(20\d{2})(?!\d)", str(texto))
    return m[1] if m else None


class _Coletor:
    """Acumula valores reconhecidos e o que não foi reconhecido."""

    def __init__(self):
        self.linhas: list[dict] = []
        self.desconhecidos: set[str] = set()

    def add(self, mes, rotulo, secao, valor, atividade_coluna=None):
        if mes is None or valor is None:
            return
        secao = secao_do_texto(atividade_coluna) if atividade_coluna else secao
        # na seção "Outros" o nome é livre: não tenta casar com os indicadores fixos
        indicador = None if secao == anual.OUTROS else indicador_do_texto(rotulo, secao)
        if indicador:
            self.linhas.append({"mes": mes, "atividade": anual.ATIVIDADE_DO[indicador], "indicador": indicador,
                                "valor": valor})
        elif not any(c in normalizar(rotulo) for c in CALCULADOS):
            nome = re.sub(r"\s+", " ", str(rotulo)).strip(" :")
            if secao != anual.OUTROS:
                self.desconhecidos.add(nome)
            self.linhas.append({"mes": mes, "atividade": anual.OUTROS, "indicador": nome, "valor": valor})


def interpretar_grade(grade: list[list], ano_padrao: str | None, mes_padrao: str | None,
                      origem: str = "") -> ResultadoAnual:
    grade = _limpar(grade)
    if not grade:
        return ResultadoAnual(_vazio(), [f"{origem}: nenhum dado encontrado."])
    texto_topo = " ".join(str(c) for l in grade[:5] for c in l)
    ano = _ano_do_texto(texto_topo) or ano_padrao
    col = _Coletor()

    # 1) cabeçalho com meses nas colunas (quadro anual)
    for i, linha in enumerate(grade[:30]):
        meses = {j: mes_da_coluna(c, ano) for j, c in enumerate(linha) if not isinstance(c, (int, float))}
        meses = {j: m for j, m in meses.items() if m}
        if len(meses) >= 2:
            cab = [normalizar(c) for c in linha]
            col_atv = next((j for j, c in enumerate(cab) if c.startswith("atividade")), None)
            col_rot = next((j for j, c in enumerate(cab) if j not in meses and j != col_atv
                            and any(c.startswith(h) for h in CABECALHOS)), None)
            secao = None
            ignorar = False
            for l in grade[i + 1:]:
                outros_meses = [j for j, c in enumerate(l) if mes_da_coluna(c, ano) and not isinstance(c, (int, float))]
                if len(outros_meses) >= 2:
                    # novo cabeçalho de tabela; a de cestas por SAS/unidade não é lançamento
                    ignorar = normalizar(l[0]).startswith(("sas", "unidade"))
                    continue
                if ignorar:
                    continue
                rotulo_idx = col_rot if col_rot is not None else next(
                    (j for j, c in enumerate(l) if j not in meses and str(c).strip()
                     and para_numero(c) is None and j != col_atv), None)
                if rotulo_idx is None:
                    continue
                rotulo = str(l[rotulo_idx]).strip()
                valores = {meses[j]: para_numero(l[j]) for j in meses}
                if all(v is None for v in valores.values()):
                    secao = secao_do_texto(rotulo) or secao  # título de seção
                    continue
                for mes, valor in valores.items():
                    col.add(mes, rotulo, secao, valor, l[col_atv] if col_atv is not None else None)
            return _resultado(col, origem)

    # 2) meses nas linhas e indicadores nas colunas
    for i, linha in enumerate(grade[:30]):
        indicadores = {j: indicador_do_texto(c, None) for j, c in enumerate(linha)}
        indicadores = {j: ind for j, ind in indicadores.items() if ind}
        if len(indicadores) >= 2:
            col_mes = next((j for j, c in enumerate(linha) if normalizar(c).startswith(("mes", "competencia",
                                                                                           "periodo"))), 0)
            for l in grade[i + 1:]:
                mes = mes_da_coluna(l[col_mes], ano)
                for j in indicadores:
                    col.add(mes, linha[j], None, para_numero(l[j]))
            return _resultado(col, origem)

    # 3) lista Mês / Indicador / Valor (Atividade opcional)
    for i, linha in enumerate(grade[:30]):
        cab = [normalizar(c) for c in linha]
        col_ind = next((j for j, c in enumerate(cab) if c.startswith(("indicador", "descricao", "item"))), None)
        col_val = next((j for j, c in enumerate(cab) if c.startswith(("valor", "quantidade", "qtd", "total"))), None)
        if col_ind is not None and col_val is not None:
            col_mes = next((j for j, c in enumerate(cab) if c.startswith(("mes", "competencia", "periodo"))), None)
            col_atv = next((j for j, c in enumerate(cab) if c.startswith("atividade")), None)
            secao = None
            for l in grade[i + 1:]:
                mes = mes_da_coluna(l[col_mes], ano) if col_mes is not None else mes_padrao
                valor = para_numero(l[col_val])
                if valor is None:
                    secao = secao_do_texto(str(l[col_ind])) or secao
                    continue
                col.add(mes or mes_padrao, l[col_ind], secao, valor, l[col_atv] if col_atv is not None else None)
            return _resultado(col, origem)

    # 4) formulário de um mês: rótulo e um número por linha
    mes = detectar_mes(texto_topo) or mes_padrao
    secao = None
    for l in grade:
        textos = [c for c in l if str(c).strip() and para_numero(c) is None]
        numeros = [para_numero(c) for c in l if para_numero(c) is not None]
        if textos and not numeros:
            secao = secao_do_texto(" ".join(map(str, textos))) or secao
        elif textos and numeros:
            col.add(mes, " ".join(map(str, textos)), secao, numeros[-1])
    return _resultado(col, origem)


def _resultado(col: _Coletor, origem: str) -> ResultadoAnual:
    avisos = []
    if col.desconhecidos:
        avisos.append(f"{origem}: não reconheci {len(col.desconhecidos)} item(ns), que entraram como 'Outros' — "
                      "confira na prévia: " + "; ".join(sorted(col.desconhecidos)) + ".")
    dados = pd.DataFrame(col.linhas, columns=COLUNAS)
    if dados.empty:
        avisos.append(f"{origem}: nenhum valor reconhecido.")
    return ResultadoAnual(dados, avisos)


# ------------------------------------------------------------ formatos de arquivo

def ler_pdf(conteudo: bytes, nome: str, ano: str | None, mes: str | None) -> ResultadoAnual:
    """PDF com o quadro anual (meses nas colunas): monta a grade pela posição das palavras."""
    import pdfplumber

    grade: list[list] = []
    texto = []
    with pdfplumber.open(io.BytesIO(conteudo)) as pdf:
        for pagina in pdf.pages:
            texto.append(pagina.extract_text() or "")
            linhas: list[list[dict]] = []
            for w in sorted(pagina.extract_words(), key=lambda w: (round(w["top"]), w["x0"])):
                if linhas and abs(w["top"] - linhas[-1][0]["top"]) <= 3:
                    linhas[-1].append(w)
                else:
                    linhas.append([w])
            colunas = None
            for linha in linhas:
                if linha[0]["top"] > pagina.height - 50:
                    continue  # rodapé (data de emissão, número da página)
                meses = [(w, mes_da_coluna(w["text"], ano or "2000")) for w in linha]
                meses = [(w, m) for w, m in meses if m]
                if len(meses) >= 3:
                    colunas = [((w["x0"] + w["x1"]) / 2, w["text"]) for w, _ in meses]
                    extra = [w for w in linha if normalizar(w["text"]) == "total"]
                    colunas += [((w["x0"] + w["x1"]) / 2, "Total") for w in extra]
                    esquerda = " ".join(w["text"] for w in linha if w["x1"] < colunas[0][0] - 25)
                    grade.append([esquerda or "Indicador", *[t for _, t in colunas]])
                    continue
                if not colunas:
                    grade.append([" ".join(w["text"] for w in linha)])
                    continue
                inicio = min(x for x, _ in colunas) - 25
                rotulo = " ".join(w["text"] for w in linha if (w["x0"] + w["x1"]) / 2 < inicio)
                valores = [""] * len(colunas)
                for w in linha:
                    cx = (w["x0"] + w["x1"]) / 2
                    if cx < inicio:
                        continue
                    k = min(range(len(colunas)), key=lambda k: abs(colunas[k][0] - cx))
                    valores[k] = (valores[k] + " " + w["text"]).strip()
                grade.append([rotulo, *valores])
    topo = " ".join(texto)[:500]
    r = interpretar_grade(grade, _ano_do_texto(topo) or ano, detectar_mes(topo) or mes, origem=nome)
    return r


def importar_arquivo(conteudo: bytes, nome: str, ano: str | None = None, mes: str | None = None) -> ResultadoAnual:
    ext = nome.lower().rsplit(".", 1)[-1]
    ano = _ano_do_texto(nome) or ano
    mes = detectar_mes(nome) or mes
    if ext == "pdf":
        return ler_pdf(conteudo, nome, ano, mes)
    if ext in ("xlsx", "xlsm", "xls", "ods"):
        planilhas = pd.read_excel(io.BytesIO(conteudo), sheet_name=None, header=None, dtype=object)
        partes = []
        for aba, df in planilhas.items():
            if normalizar(aba).startswith(("cestas por", "lancamentos")):
                continue  # abas do relatório do sistema que não são lançamentos
            r = interpretar_grade(df.values.tolist(), _ano_do_texto(aba) or ano, detectar_mes(aba) or mes,
                                  origem=f"{nome} [aba {aba}]")
            if not r.dados.empty or len(planilhas) == 1:
                partes.append(r)
        return juntar(partes)
    if ext in ("csv", "txt"):
        texto = None
        for cod in ("utf-8-sig", "latin-1"):
            try:
                texto = conteudo.decode(cod)
                break
            except UnicodeDecodeError:
                continue
        import csv

        inicio = "\n".join(texto.splitlines()[:20])
        sep = max([";", ",", "\t"], key=inicio.count)
        # linhas com quantidades diferentes de colunas (título, seções) são aceitas
        grade = list(csv.reader(io.StringIO(texto), delimiter=sep))
        return interpretar_grade(grade, ano, mes, origem=nome)
    raise ValueError(f"Formato não suportado: .{ext}")


def juntar(partes: list[ResultadoAnual]) -> ResultadoAnual:
    dados = [p.dados for p in partes if not p.dados.empty]
    dados = pd.concat(dados, ignore_index=True) if dados else _vazio()
    # o mesmo indicador repetido no mesmo mês (ex.: duas abas): fica o último
    dados = dados.drop_duplicates(["mes", "atividade", "indicador"], keep="last").reset_index(drop=True)
    return ResultadoAnual(dados, [a for p in partes for a in p.avisos])


def modelo_excel(ano: str) -> bytes:
    """Planilha modelo: uma linha por indicador e uma coluna por mês, pronta para preencher e importar."""
    linhas = [{"Atividade": atv, "Indicador": rot, **{m: None for m in anual.MESES_COLUNAS}}
              for atv, itens in anual.CATALOGO.items() for _, rot, _ in itens]
    linhas += [{"Atividade": anual.OUTROS, "Indicador": "(nome da atividade)",
                **{m: None for m in anual.MESES_COLUNAS}}]
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xl:
        pd.DataFrame(linhas).to_excel(xl, sheet_name=f"Monitoramento {ano}", index=False)
        aba = xl.sheets[f"Monitoramento {ano}"]
        aba.column_dimensions["A"].width = 32
        aba.column_dimensions["B"].width = 40
        aba.freeze_panes = "C2"
    return buf.getvalue()
