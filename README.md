# MegaOKAI

> **Branches:** `empresa` é o branch de trabalho (é aí que o script corre e grava os dados todos os dias). O `main` fica parado como estado inicial/modelo, para quem quiser reaproveitar o projeto.

Uma empresa fictícia de investimento, com capital virtual desbloqueado aos poucos (**1.200€ em novembro de 2026 e mais 600€ por mês**), paper trading e uma equipa de bots (Gestor, Analista, Operações e Developer, que mantém este repo) a tentar gerir o portfolio.

Este repo **não mexe na corretora**. Serve para guardar a config, um script que vai buscar preços e notícias, e o histórico semanal. A carteira, as ordens e o email semanal ficam noutro sítio (conta prática da Trading 212 + os bots).

Nenhum dinheiro real. **Não é aconselhamento financeiro** — é uma experiência para ver como uma equipa de agentes se porta.

## O que há neste repo

| Ficheiro / pasta | Para que serve |
| --- | --- |
| `script_semanal.py` | Vai buscar fechos oficiais (Yahoo), reconstrói o benchmark e apanha notícias (Google News RSS) |
| `config.json` | Data de início, tickers, montante do benchmark e pesquisas de notícias |
| `.github/workflows/semanal.yml` | Corre o script no GitHub Actions e faz commit do que saiu em `dados/` |
| `dados/` | O output: `precos.csv`, `benchmark.csv`, `benchmark_reforcos.csv`, `noticias.csv`, `estado.json` |
| `semanal.yml` (na raiz) | Cópia antiga do workflow, **não é usada** pelo GitHub (só conta a de `.github/workflows/`) |

O script não fala com a Trading 212, não decide o que comprar e não manda emails.

## Como funciona

1. No `config.json` estão os tickers do Yahoo e o benchmark (`VWCE.DE`, 600€ na `data_inicio` + 600€ por mês).
2. O GitHub Actions corre o script todos os dias às 08:00 UTC. Também podes ir a **Actions → Recolha semanal → Run workflow** e disparar à mão (escolhe o branch `empresa`).
3. O script escreve em `dados/` e o workflow só faz commit dessa pasta.
4. Quem lê os dados (o Analista, por exemplo) começa pelo `dados/estado.json`. Se a `data_referencia` tiver mais de quatro dias ou houver `avisos`, o snapshot está velho ou falhou qualquer coisa.

### Só fechos oficiais

Às 08:00 UTC a bolsa (Xetra, Milão…) já está aberta, por isso o Yahoo devolve para "hoje" um preço a meio da sessão. O script **ignora sempre o dia da execução** (data UTC) e usa só o fecho do último dia de negociação anterior. A data desse fecho fica na coluna `data_fecho`.

### Benchmark com reforços

O benchmark é uma carteira automática só de VWCE que recebe o mesmo capital desbloqueado que a empresa:

- **Tranche inicial:** `montante_inicial_eur` (600€) comprados ao fecho oficial da `data_inicio` (20/10/2026).
- **Reforços:** `reforco_mensal_eur` (600€) no início de cada mês a partir de `inicio_reforcos` (2026-11), cada um comprado ao fecho oficial do primeiro dia de negociação do mês (em novembro de 2026 é 2/11). Em novembro o total entregue passa a 1.200€ (600€ iniciais + 600€ de reforço).
- A reserva de 4.800€ da conta prática **nunca** entra no benchmark.
- O preço de cada compra é o fecho desse dia e não muda depois. Um reforço só aparece quando o fecho do dia de compra já existe (por exemplo, o de 2/11 aparece na execução de 3/11).

O `benchmark.csv` é **reconstruído do zero** em cada execução a partir do histórico do Yahoo (não acumula linhas antigas), por isso é sempre coerente.

### Avisos (`dados/estado.json` → `avisos`)

- Um ticker sem preço no Yahoo aparece em `precos.csv` com os valores vazios e uma nota; nunca é gravado um valor antigo como se fosse atual.
- Se o último fecho de um ticker for anterior ao dia útil anterior à execução, há um aviso com o ticker e a data (feriados também o disparam; é normal).
- Se o benchmark não puder ser calculado, ou se o Yahoo mudar o preço de uma compra já registada, também há aviso.


## Correr localmente

É necessário Python 3.12+ e `requirements.txt` (`yfinance` e `requests`). Sem API keys para preços nem notícias. E não metas aqui chaves da 212, tokens do GitHub nem passwords.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python script_semanal.py
```

Os CSV e o `estado.json` caem em `dados/`.

## Mexer na config

Edita o `config.json`:

- `data_inicio` — primeira segunda-feira da simulação (`YYYY-MM-DD`)
- `benchmark.ticker_yahoo` — o ETF de referência (não é a carteira dos bots)
- `benchmark.montante_inicial_eur` / `benchmark.reforco_mensal_eur` / `benchmark.inicio_reforcos` (`YYYY-MM`) — o capital que o benchmark recebe
- `instrumentos` — **opcional**; tickers Yahoo extra para o `precos.csv` (`.DE` = Xetra, `.AS` = Amesterdão, `.MI` = Milão; o VUAA em EUR é `VUAA.MI`). Sem esta lista o script trata só do ticker do benchmark. As ações do trading diário não precisam de estar aqui.
- `noticias.pesquisas` — o que procurar no Google News (última semana)

O script não lê a conta da Trading 212 nem os registos da empresa: corre no GitHub Actions só com o Yahoo e o Google News.

## O que sai em `dados/`

| Ficheiro | O que tem |
| --- | --- |
| `dados/precos.csv` | Último fecho oficial (`data_fecho`), variação da semana e desde o início, por ticker |
| `dados/benchmark.csv` | Uma linha por dia de negociação desde a `data_inicio`: `data_fecho`, `ticker_yahoo`, `fecho`, `capital_entregue_eur` (capital acumulado até essa data), `unidades` (acumuladas), `valor_eur`, `var_eur` e `var_pct` (face ao capital entregue) |
| `dados/benchmark_reforcos.csv` | Cada compra do benchmark: `data_compra`, `montante_eur`, `preco_compra`, `unidades` |
| `dados/noticias.csv` | Artigos recentes por pesquisa |
| `dados/estado.json` | Quando correu pela última vez, a data de referência e avisos |

Preços vêm do Yahoo (não ajustados). Se o instrumento não estiver em euros, isso aparece no campo `nota`.

## Regras da simulação (versão curta)

Isto está definido nos prompts dos bots; o script só calcula o benchmark:

- Conta prática com 6.000€, mas só conta o capital desbloqueado: 1.200€ em novembro de 2026 (600€ iniciais + 600€ de reforço) e mais 600€ no início de cada mês. O resto é reserva e não entra no valor nem na rentabilidade.
- Cerca de 50% em ETFs de índices amplos (parte segura, de longo prazo: VWCE, VUAA e semelhantes) e cerca de 50% em alto risco com trading ativo (ações individuais, ETFs temáticos)
- Preferência por ETFs UCITS cotados em euros
- Parte segura: no máximo uma sessão de ordens por semana. Alto risco: uma decisão por dia útil, com execução até às 16h de Lisboa
- Limites de risco: no máximo 20% do bolo de alto risco numa só ação, stop-loss aos 8% e nunca capital não desbloqueado nem alavancagem
- O Gestor decide compras e vendas de forma autónoma, sempre com justificação escrita
- Benchmark: VWCE com os mesmos reforços do capital desbloqueado
- **Só** conta prática da Trading 212

## Licença

MIT — podes usar o repo como está, copiar, e fazer o teu próprio fork.

O original (este repositório) é meu: só eu mexo aqui. Se alterares a tua cópia, essa versão passa a ser tua responsabilidade; eu não a mantenho nem sou responsável pelo que fizeres com ela. Sem garantia, como diz o `LICENCE`.
