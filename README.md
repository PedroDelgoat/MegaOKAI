# MegaOKAI

Uma empresa fictícia de investimento, com **600€ virtuais (por mês)**, paper trading e três bots (Analista, Operações, Gestor) a tentar gerir o portfolio.

Este repo **não mexe na corretora**. Serve para guardar a config, um script que vai buscar preços e notícias, e o histórico semanal. A carteira, as ordens e o email semanal ficam noutro sítio (conta prática da Trading 212 + os bots).

Nenhum dinheiro real. **Não é aconselhamento financeiro** — é uma experiência para ver como uma equipa de agentes se porta.

## O que há neste repo

| Ficheiro / pasta | Para que serve |
| --- | --- |
| `script_semanal.py` | Vai buscar preços (Yahoo), atualiza o benchmark e apanha notícias (Google News RSS) |
| `config.json` | Data de início, tickers, montante do benchmark e pesquisas de notícias |
| `.github/workflows/semanal.yml` | Corre o script no GitHub Actions e faz commit do que saiu em `dados/` |
| `dados/` | O output: `precos.csv`, `benchmark.csv`, `noticias.csv`, `estado.json` |

O script não fala com a Trading 212, não decide o que comprar e não manda emails.

## Como funciona

1. No `config.json` estão os tickers do Yahoo e o ETF de benchmark (`VWCE.DE`, 600€ a partir da `data_inicio`).
2. O GitHub Actions corre o script (de momento todos os dias às 08:00 UTC). Também podes ir a **Actions → Recolha semanal → Run workflow** e disparar à mão.
3. O script escreve em `dados/` e o workflow só faz commit dessa pasta.
4. Quem lê os dados (o Analista, por exemplo) começa pelo `dados/estado.json`. Se a `data_referencia` tiver mais de quatro dias ou houver `avisos`, o snapshot está velho ou falhou qualquer coisa.


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
- `benchmark.ticker_yahoo` / `benchmark.montante_eur` — a referência automática (não é a carteira dos bots)
- `instrumentos` — tickers Yahoo (`.DE` = Xetra, `.AS` = Amesterdão, `.MI` = Milão)
- `noticias.pesquisas` — o que procurar no Google News (última semana)

Se a empresa passar a acompanhar um instrumento novo, mete-o aqui. Senão o script ignora-o.

## O que sai em `dados/`

| Ficheiro | O que tem |
| --- | --- |
| `dados/precos.csv` | Último fecho, variação da semana e desde o início, por ticker |
| `dados/benchmark.csv` | Uma linha por data: quanto valeriam 600€ em VWCE |
| `dados/noticias.csv` | Artigos recentes por pesquisa |
| `dados/estado.json` | Quando correu pela última vez, a data de referência e avisos |

Preços vêm do Yahoo (não ajustados). Se o instrumento não estiver em euros, isso aparece no campo `nota`.

## Regras da simulação (versão curta)

Isto está definido nos prompts dos bots; o script só calcula o benchmark:

- 600€ virtuais, sem reforços a não ser que o dono diga
- Pelo menos 80% em ETFs de índices amplos, no máximo 20% em ações / ETFs temáticos
- Compras à segunda, 10h–16h Lisboa
- Vendas só com ok explícito do dono
- **Só** conta prática da Trading 212

## Licença

MIT — podes usar o repo como está, copiar, e fazer o teu próprio fork.

O original (este repositório) é meu: só eu mexo aqui. Se alterares a tua cópia, essa versão passa a ser tua responsabilidade; eu não a mantenho nem sou responsável pelo que fizeres com ela. Sem garantia, como diz o `LICENCE`.
