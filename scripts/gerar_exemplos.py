"""Gera arquivos de exemplo (CSV, Excel, HTML e PDF) com dados fictícios.

Uso:  python scripts/gerar_exemplos.py
"""

from pathlib import Path
import random

import pandas as pd

PASTA = Path(__file__).resolve().parent.parent / "exemplos"
UNIDADES = ["CRAS Centro", "CRAS Norte", "CRAS Sul", "CRAS Leste", "CRAS Oeste", "CREAS I", "CREAS II"]
COTAS = [180, 150, 160, 120, 140, 60, 50]
COLUNAS = ["Unidade", "Cota Disponível", "Quantidade Solicitada", "Demanda Registrada",
           "Atendimento Social", "Quantidade de Recibos Emitidos", "Quantidade de Cestas Concedidas"]
MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro"]


def mes_ficticio(n: int, rnd: random.Random) -> pd.DataFrame:
    linhas = []
    for unidade, cota in zip(UNIDADES, COTAS):
        demanda = int(cota * rnd.uniform(0.8, 1.35) * (1 + n * 0.02))
        solicitada = int(demanda * rnd.uniform(0.85, 1.0))
        concedidas = min(solicitada, int(cota * rnd.uniform(0.75, 1.0)))
        if rnd.random() < 0.06:
            concedidas = cota + rnd.randint(1, 8)  # para gerar alerta
        recibos = concedidas if rnd.random() > 0.15 else concedidas - rnd.randint(1, 5)
        atendimento = int(demanda * rnd.uniform(1.3, 2.2))
        linhas.append([unidade, cota, solicitada, demanda, atendimento, recibos, concedidas])
    df = pd.DataFrame(linhas, columns=COLUNAS)
    total = ["Total SAS", *df.iloc[:, 1:].sum().tolist()]
    return pd.concat([df, pd.DataFrame([total], columns=COLUNAS)], ignore_index=True)


def main():
    PASTA.mkdir(exist_ok=True)
    rnd = random.Random(42)
    meses = {f"2026-{i + 1:02d}": mes_ficticio(i, rnd) for i in range(len(MESES))}

    # Excel: uma aba por mês (Jan a Jun)
    with pd.ExcelWriter(PASTA / "cestas_1o_semestre_2026.xlsx", engine="openpyxl") as xl:
        for i, (mes, df) in enumerate(list(meses.items())[:6]):
            df.to_excel(xl, sheet_name=f"{MESES[i]} 2026", index=False, startrow=2)
            xl.sheets[f"{MESES[i]} 2026"]["A1"] = f"Concessão de Cestas Básicas - {MESES[i]}/2026"

    # CSV (padrão brasileiro: ponto e vírgula) — Julho
    meses["2026-07"].to_csv(PASTA / "cestas_2026-07.csv", sep=";", index=False, encoding="utf-8-sig")

    # HTML — Agosto
    html = meses["2026-08"].to_html(index=False, border=1)
    (PASTA / "cestas_agosto_2026.html").write_text(
        f"<html><body><h2>Relatório de Cestas Básicas - Agosto/2026</h2>{html}</body></html>", encoding="utf-8")

    # PDF — Setembro
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

    df = meses["2026-09"]
    cabecalho = ["Unidade", "Cota\nDisponível", "Quantidade\nSolicitada", "Demanda\nRegistrada",
                 "Atendimento\nSocial", "Recibos\nEmitidos", "Cestas\nConcedidas"]
    tabela = Table([cabecalho, *df.astype(str).values.tolist()])
    tabela.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey)]))
    doc = SimpleDocTemplate(str(PASTA / "cestas_setembro_2026.pdf"), pagesize=landscape(A4))
    doc.build([Paragraph("Concessão de Cestas Básicas - Setembro/2026", getSampleStyleSheet()["Title"]), tabela])
    print(f"Exemplos gravados em {PASTA}")


if __name__ == "__main__":
    main()
