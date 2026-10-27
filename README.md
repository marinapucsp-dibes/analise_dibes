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

Também são aceitos os nomes usados no painel mensal da Secretaria: *Cotas*, *Cestas Recebidas*
(= Quantidade Solicitada), *Demanda pelo Benefício*, *Registros de Atend. Técnico* (= Atendimento Social),
*Recibos Válidos* e *Cestas Entregues* (= Cestas Concedidas).

Os campos são analisados em quatro níveis: **Total Geral** (município), **cada SAS** (Supervisão de
Assistência Social), **Total CRAS / CREAS / Centro POP** e **cada unidade**. Quando o arquivo informa o
valor da SAS, ele é usado nos totais (pode incluir cota ainda não distribuída às unidades); senão, as
unidades são somadas.

## Como instalar e abrir

Requer Python 3.10 ou mais recente.

```bash
pip install -r requirements.txt
streamlit run app.py
```

O painel abre no navegador (http://localhost:8501). Sem configuração, o histórico fica salvo em
`dados/dibes.db` (SQLite) — faça cópia de segurança desse arquivo.

## Publicar na internet (Streamlit Community Cloud + Supabase)

Assim a equipe acessa por um link, sem instalar nada, e o histórico fica num banco na nuvem.

**1. Criar o banco (Supabase, gratuito)**
1. Crie uma conta em https://supabase.com e clique em **New project** (região: *South America (São Paulo)*).
   Anote a senha do banco.
2. No projeto, clique em **Connect** (no topo) e copie a *connection string* do tipo **URI**
   em **Session pooler**. Troque `[YOUR-PASSWORD]` pela senha anotada.
   A tabela é criada automaticamente na primeira vez que o painel abrir.

**2. Publicar o painel (Streamlit Community Cloud, gratuito)**
1. Entre em https://share.streamlit.io com a conta do GitHub.
2. **Create app** → repositório `analise_dibes`, branch principal, arquivo `app.py`.
3. Em **Advanced settings → Secrets**, cole (veja `.streamlit/secrets.toml.exemplo`):
   ```toml
   DIBES_DATABASE_URL = "postgresql://postgres.xxxx:SUA_SENHA@aws-0-sa-east-1.pooler.supabase.com:5432/postgres"
   SENHA = "uma-senha-para-a-equipe"
   ```
4. **Deploy**. O link fica no formato `https://<nome>.streamlit.app`.

`SENHA` é opcional: se existir, o painel pede a senha antes de abrir. Os *Secrets* nunca devem ir
para o GitHub (o arquivo `.streamlit/secrets.toml` já está no `.gitignore`).

> Apps gratuitos do Streamlit "dormem" após alguns dias sem acesso; basta abrir o link e clicar em
> *Yes, get this app back up* (leva cerca de 1 minuto). Os dados ficam no Supabase e não se perdem.

## Importação dos dados (📥 Importar dados)

Formatos aceitos:

- **Excel** (`.xlsx`, `.xls`, `.ods`) — pode ter **uma aba por mês** (ex.: “Março 2026”); cada aba é lida separadamente.
- **CSV** (separador `;`, `,` ou tabulação; números no padrão brasileiro `1.234,5`).
- **PDF** — inclusive o painel salvo pelo navegador (*Imprimir → Salvar como PDF*): a tabela é montada pela
  posição das palavras, juntando nomes quebrados em várias linhas. Se a impressão cortar uma coluna, o
  sistema avisa; enviando juntos o PDF por SAS e o PDF por CRAS/CREAS, os campos que faltarem nas SAS
  são somados a partir das unidades.
- **HTML** — envie o arquivo `.html` ou **cole o código** (página inteira ou só a `<table>`). Também lê
  painéis cujos dados ficam em listas JavaScript (`const sasData = [...]`, `const crasData = [...]`),
  como o painel mensal da Secretaria. Quando o painel lista as SAS e, separadamente, as unidades na mesma
  ordem, o sistema descobre a SAS de cada unidade pelas somas (e pelo nome, nos empates).
- **Digitação manual** — tabela já preenchida com as unidades cadastradas.

O sistema localiza sozinho a linha de cabeçalho e reconhece variações de nome
(“Qtd Solicitada”, “Recibos”, “CRAS/CREAS”, “Equipamento”…). Também aceita planilhas
**transpostas** (campos nas linhas e unidades nas colunas).

- O **mês** é obtido do nome do arquivo, do nome da aba, do título do documento ou de uma coluna “Mês/Competência”.
  Se não houver, usa o mês escolhido na tela.
- O **tipo** (SAS, CRAS, CREAS, Centro POP) é deduzido do nome e pode ser corrigido na prévia, assim como
  a **SAS** de cada unidade. Unidades sem SAS no arquivo recebem a SAS da importação anterior.
- Linhas de **total** (“Total”, “Total Geral”) não são gravadas: o sistema recalcula o total e
  **avisa se a soma não bate** com o total informado no arquivo.
- **Grafias diferentes** do mesmo nome entre meses (ex.: “JAÇANÃ” × “JAÇÃNA”, “SANTO AMARO - AS” × “- SA”,
  “CREAS SÃO MIGUEL” × “CREAS SÃO MIGUEL PAULISTA”) são unificadas automaticamente, para não quebrar a
  comparação mês a mês. Nomes que aparecem juntos num mesmo mês nunca são unidos.
- Antes de salvar, a **prévia é editável**.
- **Reimportar um mês substitui, não soma.** Se o mês já existe, a opção “Substituir o mês por inteiro”
  (marcada por padrão) apaga o que estava salvo daquele mês antes de gravar, para corrigir uma importação
  errada. Desmarque só quando o arquivo complementa o mês (ex.: PDF por CRAS enviado depois do PDF por SAS).
- Para ajustar poucos números, use **Histórico e relatório → ✏️ Corrigir dados salvos**: a tabela do mês
  pode ser editada direto (alterar, incluir ou apagar linhas).

## Emergências

Concessões do Auxílio Alimentação em situações de emergência (enchentes, incêndios, desabamentos…),
realizadas pelo CPAS, por **localidade/ocorrência**. Ficam separadas dos totais das SAS.

- **Junto com o painel HTML:** a tabela "Emergências" do painel mensal é lida automaticamente.
- **Lançar ou corrigir qualquer mês:** *Importar dados → 🚨 Emergências* — escolha o mês no seletor do topo,
  edite a tabela e salve (a lista do mês substitui a anterior).
- **Vários meses de uma vez:** importe na aba *Arquivo* uma planilha (Excel/CSV) com as colunas **Mês**,
  **Localidade / Ocorrência** e **Qtd. de Cestas**.

Aparecem no Painel do mês, na Evolução mensal, no PDF, no Excel e na análise por IA.

## Páginas

- **📊 Painel do mês** — os seis campos com variação em relação ao mês anterior e indicadores, para o
  Total Geral, uma SAS, um tipo de unidade ou uma unidade; ranking e comparativo entre SAS ou entre
  unidades (com filtro por SAS); resumo por tipo e tabelas por SAS e por unidade.
- **📈 Evolução mensal** — linhas mês a mês por recorte, indicadores (Total Geral × CRAS × CREAS),
  participação de cada tipo de unidade e comparativo **Recibos emitidos × Atendimento social** (mês a mês
  e por SAS/unidade, em vermelho onde mais de 10% dos recibos não têm atendimento).
- **⚠️ Alertas** — destaques em vermelho das unidades com **mais de 10% dos recibos sem atendimento
  social** (em laranja, até 10%) e das que **concederam menos de 10% da cota**; e conferência automática de SAS e unidades: concessão acima da cota, mais recibos que
  cestas, recibos sem registro de atendimento social, demanda maior que a cota, concessões sem cota na
  unidade, SAS diferente da soma das unidades, unidade sem dados, baixo uso da cota e variação forte.
- **🤖 Análise por IA** — o Claude (modelo `claude-opus-5-5`, da Anthropic) lê os números dos **meses que você
  escolher** (um mês, comparado com o anterior, ou vários meses, seguidos ou não, com atalhos para os
  últimos 3/6 meses, o ano ou todo o histórico) e escreve uma análise técnica com tendências e
  recomendações, ou responde a uma pergunta sua. A tela mostra o custo estimado antes de gerar. Só números agregados são enviados (nenhum dado pessoal); cada análise custa poucos
  centavos de dólar na sua conta da API. Para ativar, crie uma chave em https://console.anthropic.com →
  **API Keys** e acrescente nos Secrets: `ANTHROPIC_API_KEY = "sk-ant-..."`.
- **🗂️ Histórico e relatório** — **relatório mensal em PDF para impressão**, tabela completa,
  exclusão de meses/unidades e download do **relatório em Excel** (abas Total Geral, Por SAS,
  CRAS x CREAS, Por unidade e Alertas) e dos dados em CSV.

### Relatório para impressão (PDF)

Botão **🖨️ Relatório do mês (PDF)** no Painel do mês e em Histórico e relatório. A4 paisagem, com:
1. Resumo do Total Geral com comparação ao mês anterior e indicadores por tipo de unidade;
2. Tabela e gráfico por SAS;
3. Tabela de todas as unidades (com a SAS) e subtotais por tipo;
4. Evolução dos últimos 12 meses (gráficos e tabela);
5. Alertas de conferência do mês (críticos e de atenção).

### Indicadores calculados

| Indicador | Fórmula |
|---|---|
| Uso da cota (%) | Cestas concedidas ÷ Cota disponível |
| Concessão sobre a demanda (%) | Cestas concedidas ÷ Demanda registrada |
| Atendimento técnico sobre a demanda (%) | Atendimento social ÷ Demanda registrada |
| Saldo da cota | Cota disponível − Cestas concedidas |
| Cestas em estoque | Quantidade solicitada − Cestas concedidas (negativo = uso de estoque de meses anteriores) |
| Demanda reprimida | Demanda registrada − Cestas concedidas (mínimo 0) |
| Recibos sem registro de atendimento | Recibos − Atendimento social (mínimo 0) |
| Cestas sem recibo | Cestas concedidas − Recibos (mínimo 0) |

## Arquivos de exemplo

A pasta `exemplos/` tem dados **fictícios** de jan–set/2026 em todos os formatos
(Excel com uma aba por mês, CSV, HTML e PDF). Para gerá-los de novo: `python scripts/gerar_exemplos.py`.

## 📅 Monitoramento Anual DIBES (segundo app)

App separado (`monitoramento_anual.py`), no mesmo repositório e no **mesmo banco**, para lançar mês a mês
as atividades da DIBES e acompanhar o ano (Jan a Dez + Total):

| Atividade | Indicadores |
|---|---|
| Benefício Eventual Alimentação | Cestas concedidas pelas SAS/unidades e em emergências (**automático**, do sistema de Cestas Básicas; digitável para meses que não estão lá), cestas compradas, valor gasto |
| Benefício Eventual Passagens | Solicitações, solicitações atendidas, pessoas beneficiadas, passagens compradas, passagens não utilizadas, valor gasto |
| SIGRC | Protocolos respondidos |
| SEI | Processos SEI respondidos |
| Programa Bolsa Família (PBF) | Manutenções em lote e manuais |
| Outros | Nome livre da atividade e n.º de ações |

Indicadores calculados: total de cestas concedidas, custo médio por cesta comprada, taxa de atendimento
das passagens, % de passagens não utilizadas, custo médio por passagem e por pessoa, total de manutenções.

Páginas: **📊 Painel anual** (cartões, gráficos por atividade, quadro anual, cestas por SAS e por unidade),
**✍️ Lançar mês** (formulário; para corrigir, escolha o mês de novo) e **🖨️ Relatórios** (PDF e Excel).

**Publicar:** no Streamlit Cloud, **Create app** com o mesmo repositório e branch, *Main file path*
`monitoramento_anual.py`, e em **Advanced settings → Secrets** os mesmos `DIBES_DATABASE_URL` e `SENHA`
do app de Cestas Básicas.

## Estrutura

```
app.py                 # painel de Cestas Básicas (Streamlit)
monitoramento_anual.py # painel do Monitoramento Anual DIBES (Streamlit)
dibes/config.py        # campos e nomes de coluna reconhecidos
dibes/importador.py    # leitura de Excel, CSV, PDF e HTML
dibes/banco.py         # histórico mensal (SQLite local ou Postgres/Supabase)
dibes/analise.py       # totais, indicadores e alertas
dibes/graficos.py      # gráficos (Plotly)
dibes/relatorio.py     # relatório em Excel
dibes/relatorio_pdf.py # relatório mensal em PDF (impressão)
dibes/ia.py            # análise por IA (Claude)
dibes/anual.py         # atividades do Monitoramento Anual e consolidação do ano
dibes/relatorio_anual.py # PDF e Excel do Monitoramento Anual
dibes/ui.py            # senha, Secrets e formatação comuns aos dois apps
tests/                 # testes automáticos (pytest)
```

Para reconhecer outros nomes de coluna usados pela Secretaria, acrescente-os em `APELIDOS`
no arquivo `dibes/config.py`.
