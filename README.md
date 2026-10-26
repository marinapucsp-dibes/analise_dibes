# 🧺 Análise das Concessões de Cestas Básicas — SAS / CRAS / CREAS

Sistema para automatizar o monitoramento **mensal** das concessões de cestas básicas do município,
com gráficos, indicadores e alertas de conferência.

## Campos analisados

| Campo | Observação |
|---|---|
| Cota Disponível | |
| Quantidade Solicitada | |
| Demanda Registrada | |
| Atendimento Social | |
| Quantidade de Recibos Emitidos | |
| Quantidade de Cestas Concedidas | |

Todos os campos são analisados em três níveis: **Total SAS** (soma de todas as unidades),
**Total CRAS / Total CREAS** e **cada unidade** (CRAS ou CREAS individualmente).

## Como instalar e abrir

Requer Python 3.10 ou mais recente.

```bash
pip install -r requirements.txt
streamlit run app.py
```

O painel abre no navegador (http://localhost:8501). O histórico fica salvo em `dados/dibes.db`
(SQLite) — faça cópia de segurança desse arquivo. Para usar outro local, defina a variável `DIBES_BANCO`.

## Importação dos dados (📥 Importar dados)

Formatos aceitos:

- **Excel** (`.xlsx`, `.xls`, `.ods`) — pode ter **uma aba por mês** (ex.: “Março 2026”); cada aba é lida separadamente.
- **CSV** (separador `;`, `,` ou tabulação; números no padrão brasileiro `1.234,5`).
- **PDF** — tabelas do documento; se o PDF não tiver tabela desenhada, as linhas de texto são lidas.
- **HTML** — envie o arquivo `.html` ou **cole o código** (página inteira ou só a `<table>`).
- **Digitação manual** — tabela já preenchida com as unidades cadastradas.

O sistema localiza sozinho a linha de cabeçalho e reconhece variações de nome
(“Qtd Solicitada”, “Recibos”, “CRAS/CREAS”, “Equipamento”…). Também aceita planilhas
**transpostas** (campos nas linhas e unidades nas colunas).

- O **mês** é obtido do nome do arquivo, do nome da aba, do título do documento ou de uma coluna “Mês/Competência”.
  Se não houver, usa o mês escolhido na tela.
- O **tipo** (CRAS/CREAS) é deduzido do nome da unidade e pode ser corrigido na prévia.
- Linhas de **total** (“Total”, “Total SAS”) não são gravadas: o sistema recalcula o total e
  **avisa se a soma das unidades não bate** com o total informado no arquivo.
- Antes de salvar, a **prévia é editável**. Reimportar um mês substitui os dados das mesmas unidades.

## Páginas

- **📊 Painel do mês** — os seis campos com variação em relação ao mês anterior, indicadores, ranking das
  unidades, comparativo Cota × Demanda × Concedidas e resumo CRAS × CREAS × Total SAS.
- **📈 Evolução mensal** — linhas mês a mês por recorte, indicadores (SAS × CRAS × CREAS),
  participação de CRAS e CREAS no total e mapa de calor por unidade.
- **⚠️ Alertas** — conferência automática: concessão acima da cota, recibos ≠ cestas,
  demanda maior que a cota, concedidas acima do solicitado, unidade sem dados, baixo uso da cota
  e variação forte em relação ao mês anterior.
- **🗂️ Histórico e relatório** — tabela completa, exclusão de meses/unidades e download do
  **relatório em Excel** (abas Total SAS, CRAS x CREAS, Por unidade e Alertas) e dos dados em CSV.

### Indicadores calculados

| Indicador | Fórmula |
|---|---|
| Uso da cota (%) | Cestas concedidas ÷ Cota disponível |
| Atendimento da demanda (%) | Cestas concedidas ÷ Demanda registrada |
| Atendimento das solicitações (%) | Cestas concedidas ÷ Quantidade solicitada |
| Saldo da cota | Cota disponível − Cestas concedidas |
| Demanda reprimida | Demanda registrada − Cestas concedidas (mínimo 0) |
| Recibos − cestas | Recibos emitidos − Cestas concedidas (deve ser 0) |

## Arquivos de exemplo

A pasta `exemplos/` tem dados **fictícios** de jan–set/2026 em todos os formatos
(Excel com uma aba por mês, CSV, HTML e PDF). Para gerá-los de novo: `python scripts/gerar_exemplos.py`.

## Estrutura

```
app.py                 # interface (Streamlit)
dibes/config.py        # campos e nomes de coluna reconhecidos
dibes/importador.py    # leitura de Excel, CSV, PDF e HTML
dibes/banco.py         # histórico mensal (SQLite)
dibes/analise.py       # totais, indicadores e alertas
dibes/graficos.py      # gráficos (Plotly)
dibes/relatorio.py     # relatório em Excel
tests/                 # testes automáticos (pytest)
```

Para reconhecer outros nomes de coluna usados pela Secretaria, acrescente-os em `APELIDOS`
no arquivo `dibes/config.py`.
