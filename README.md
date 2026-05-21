# GitHub-Hosted Stock Research and Alert Agent

This repo is a human-in-the-loop investing research assistant. It monitors a portfolio, watchlist, recent news, price action, and similar-stock research ideas, then generates:

- `output/latest_report.json`
- `output/dashboard.html`
- sanitized public Pages artifacts in `public/`
- an optional daily Discord alert through the `DISCORD_WEBHOOK_URL` GitHub Secret
- a GitHub Pages deployment from the sanitized `public/` folder

It never executes trades, never stores broker credentials, and never hardcodes API keys or webhook URLs.

## What It Does

- Pulls best-effort current prices and price history from public Stooq CSV endpoints.
- Pulls recent headlines from Yahoo Finance and Google News RSS.
- Calculates current value, unrealized gain/loss, percentage gain/loss, and position weight.
- Flags holdings as `sell watch`, `hold`, `add watch`, or `research only`.
- Scores each holding and research candidate using:
  - price momentum
  - news sentiment
  - downside from cost basis
  - earnings proximity
  - sector trend
  - thesis risk
  - valuation caution
- Produces 3-5 discovery ideas as research candidates, not automatic buys.
- Uses optional GPT-powered event analysis for only the most important filtered events.
- Tracks signal history, paper learning records, and accuracy by signal type.
- Sends a concise Discord message when `DISCORD_WEBHOOK_URL` is configured.

## Local Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m src.main --skip-discord
```

On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m src.main --skip-discord
```

Open `output/dashboard.html` for the private full-detail view, or `public/dashboard.html` for the sanitized public Pages view.

## Discord Setup

Create a Discord webhook for the channel where alerts should post, then add it to the GitHub repo:

1. Go to GitHub repo settings.
2. Open **Secrets and variables** -> **Actions**.
3. Add a repository secret named `DISCORD_WEBHOOK_URL`.

The webhook URL is read only from the environment. Do not place it in source files.

## OpenAI API Setup

GPT event analysis is optional and controlled by `config/settings.yaml`.

Create an OpenAI API key, then add it to GitHub:

1. Go to GitHub repo settings.
2. Open **Secrets and variables** -> **Actions**.
3. Add a repository secret named `OPENAI_API_KEY`.

The code reads only the `OPENAI_API_KEY` environment variable. Do not commit API keys.

The default model is `gpt-5-nano`, which OpenAI describes as its fastest, most cost-efficient GPT-5 option and suitable for summarization/classification tasks. You can change it in `config/settings.yaml`:

```yaml
openai:
  gpt_enabled: true
  rules_only_mode: false
  model: gpt-5-nano
  max_gpt_calls_per_day: 4
  max_articles_per_run: 8
  max_events_per_call: 3
  max_tokens_per_call: 450
  max_daily_gpt_budget_estimate: 0.05
```

To disable GPT entirely and use the rules-only fallback:

```yaml
openai:
  gpt_enabled: false
```

Or temporarily force fallback behavior:

```yaml
openai:
  rules_only_mode: true
```

### Cost Guidance

The default budget is intentionally tiny. With `gpt-5-nano` pricing configured at `$0.05` per 1M input tokens and `$0.40` per 1M output tokens, a normal run should be well under a cent unless many events pass the filter. The report logs estimated calls, tokens, and cost in `gpt_analysis.usage`.

If `OPENAI_API_KEY` is missing, limits are reached, the budget estimate is exceeded, or the API call fails, the agent falls back to rules-based summaries.

### GPT Filtering

The agent does not send every headline to GPT. It first filters and de-duplicates events using:

- earnings and guidance tags
- analyst upgrades/downgrades
- legal/regulatory issues
- product launches and partnerships
- sector-wide AI, datacenter, semiconductor, or automation news
- price moves greater than the configured threshold
- high risk or sentiment scores
- high-priority holdings and thesis-risk signals

Low-quality fetch errors, duplicated URLs/headlines, and low-relevance headlines stay rules-only.

## Private Portfolio Data

This repository is safe to make public only if exact personal portfolio figures are kept out of tracked files. The committed `data/portfolio.json` uses normalized placeholder figures so the app can run as a public demo.

For real daily alerts, add a GitHub Actions secret named `PORTFOLIO_JSON` containing your full private portfolio JSON. The workflow reads that secret at runtime and still deploys only sanitized files from `public/`.

Optional: add `WATCHLIST_JSON` as a secret too if you want the watchlist to be private.

For local private runs, keep your real JSON in `data/portfolio.private.json` and run:

```powershell
$env:PORTFOLIO_JSON = Get-Content data/portfolio.private.json -Raw
python -m src.main --skip-discord
```

## GitHub Pages Setup

The workflow deploys the generated `public/` folder using GitHub Pages Actions. The `public/` files redact exact shares, cost basis, dollar values, and exact prices.

1. In GitHub, open **Settings** -> **Pages**.
2. Set **Source** to **GitHub Actions**.
3. Run the workflow manually once from the **Actions** tab.

The default dashboard URL in the workflow is:

```text
https://OWNER.github.io/REPO/dashboard.html
```

For this repo, the expected dashboard URL is:

```text
https://kevintaylormccaffrey-debug.github.io/AI-Trader/dashboard.html
```

If your Pages URL is different, set `DASHBOARD_URL` in the workflow or `config/settings.yaml`.

## Running the Agent

Generate outputs without Discord:

```bash
python -m src.main --skip-discord
```

Generate outputs and send Discord alert when the webhook secret exists:

```bash
python -m src.main
```

Evaluate historical signal accuracy:

```bash
python scripts/evaluate_signals.py
```

## Data Files

- `data/portfolio.json` stores holdings, cost basis, thesis, horizon, max-loss rules, and discovery preferences.
- In the public-safe version, `data/portfolio.json` contains normalized placeholder figures. Use `PORTFOLIO_JSON` for real private data.
- `data/watchlist.json` stores research-only tickers to monitor.
- `config/settings.yaml` stores source settings, scoring weights, output paths, and alert behavior.
- `output/` stores private full-detail generated files.
- `public/` stores sanitized generated files for GitHub Pages.
- `data/signals_history.json` stores signal outcomes and accuracy statistics.
- `data/paper_trades.json` stores simulated learning records only; no real trades are executed.

## Signal Learning

Each run records signals such as `sell watch`, `add watch`, `risk elevated`, and `research opportunity`. After the configured evaluation window, the agent compares later price action with the original signal and updates:

- best-performing signals
- worst-performing signals
- accuracy by signal type
- pending versus evaluated signals
- simulated paper learning records

These metrics are experimental. They are meant to improve review discipline, not to automate trading.

## Safety Notes

This is not financial advice. It is a research workflow for human review. The agent can be wrong because public prices can lag, news feeds can miss context, and valuation/thesis quality requires deeper analysis. Treat `sell watch`, `add watch`, and `research only` as prompts to review, not instructions to trade.

## Troubleshooting

- **No GPT summaries:** confirm `OPENAI_API_KEY` is set, `gpt_enabled` is true, and `rules_only_mode` is false.
- **Too many GPT calls:** lower `max_articles_per_run` or `max_gpt_calls_per_day`.
- **Budget hit:** raise `max_daily_gpt_budget_estimate` slightly or keep the rules-only fallback.
- **Discord is too long:** lower `alerts.max_discord_chars`; GPT event notes are already capped to the most important events.
- **Pages shows exact figures:** stop and check that the workflow deploys `public/`, not `output/`.
- **Signal history is not changing:** make sure the workflow has `contents: write` permission and the `Persist learning history` step succeeds.

## Extending Data Sources

The default implementation uses public no-key sources so the repo runs immediately. For production-grade market data, add a provider in `src/data_sources.py` that reads credentials from GitHub Secrets or environment variables. Keep secrets out of committed files.
