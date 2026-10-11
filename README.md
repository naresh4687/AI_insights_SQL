# InsightSQL — AI-Powered SQL Data Analyst

Ask business questions about sales data in plain English. InsightSQL turns the question
into a SQL query, checks that the query is safe, runs it read-only against a SQLite
database, and shows the SQL, a results table, a chart, and a short explanation.

- **Demo Mode** (default): 5 example questions with hand-written SQL. No AI, no network.
- **AI Mode**: Google's [Gemini](https://ai.google.dev) (`gemini-3.5-flash-lite` by
  default) writes the SQL for any question. Only the question and the table structure are
  sent, never the sales data. Hugging Face can be used instead (`AI_PROVIDER=huggingface`).

Whoever writes the SQL (Demo Mode, the AI, or you in the "Advanced" box) it goes through
the same safety checks before it runs.

## Quick start

Tested with Python 3.12 on Linux.

```bash
git clone <this repository> insightsql && cd insightsql
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt    # use requirements-dev.txt to also run the tests
cp .env.example .env               # optional; the defaults work
streamlit run app.py
```

Open http://localhost:8501. The database (`data/insightsql.db`) is created and filled
with sample data on first run. To rebuild it: `python scripts/seed_database.py`.

### Optional: AI Mode

1. Create a Gemini API key at https://aistudio.google.com/apikey.
2. Put it in `.env`: `GEMINI_API_KEY=...` (`.env` is git-ignored; never commit the key).
3. Restart the app and select **AI Mode (Gemini)**.

A green message confirms the key is accepted and the model exists; a warning explains
what to fix if the key is missing or invalid or the model name is wrong. Demo Mode keeps
working either way. Usage counts against your Gemini API quota (a free tier is available;
see https://ai.google.dev/gemini-api/docs/pricing); if it runs out, AI Mode shows a clear
quota message.

To check the real model against the Demo Mode answers:
`python scripts/check_ai_mode.py --repeat 2`.

To use Hugging Face instead, set `AI_PROVIDER=huggingface` and `HF_TOKEN` (a token with
the permission "Make calls to Inference Providers"; requires Inference Providers credit).

## Using the app

InsightSQL has a dark, sidebar-based interface. The sidebar holds the page links, the
**Mode** selector (Demo Mode or AI Mode) and a status card showing whether the selected
mode is ready. On a phone the sidebar starts collapsed; open it with the arrow at top left.

| Page | What it does |
|------|--------------|
| **Dashboard** | Total revenue, total sales, products and average sale value, calculated live from the database; revenue over time (with the latest month compared with the month before), by region, by category, and the top five products; recent questions. |
| **AI Analyst** | A chat. Click a suggested question or type your own and press Enter. Each answer shows a factual summary, then **Results**, **Visualization** and **SQL** tabs, with a status badge, row count and measured run time. The conversation is kept while you move between pages; **New chat** clears it. |
| **Query History** | Every question with its outcome (Success, Rejected or Failed), searchable and filterable. **Ask again** re-asks the question in the current mode; **Open in SQL Explorer** puts the stored SQL in the editor. Stored SQL is never run directly. |
| **SQL Explorer** | Run your own single read-only `SELECT` on `products` and `sales` (try `DROP TABLE sales` to see it rejected), or load the last AI-generated SQL. |
| **Settings & About** | Current mode, AI provider and model, whether a key is configured (never the key itself), a **Test connection** button, database status and setup steps. |

## The data

Deterministic sample data (seed 42), the same on every machine:

| Table | Rows | Columns |
|-------|-----:|---------|
| `products` | 12 | `product_id`, `product_name`, `category` (4), `unit_price` |
| `sales` | 600 | `sale_id`, `product_id`, `sale_date` (2025), `region` (4), `quantity`, `unit_price` (after a 0/5/10 % discount) |

Revenue is `SUM(sales.quantity * sales.unit_price)`. A third table, `query_history`, stores
the history and cannot be read by queries.

## How queries are kept safe

The AI prompt asks for read-only SQL, but the prompt is **not** treated as a security
boundary. Every query passes through:

1. **Parser check** (`src/sql_guard.py`, using sqlglot): exactly one statement, which must
   be a `SELECT` (CTEs allowed); no writes, DDL, `PRAGMA`, `ATTACH` or recursive CTEs;
   only the `products` and `sales` tables. The SQL that runs is regenerated from the parsed
   tree, so comments and hidden extras are dropped.
2. **Engine-level authorizer**: a SQLite callback that allows only reads of those two
   tables and a list of safe functions.
3. **Read-only connection** (`mode=ro`) with `PRAGMA query_only`.
4. **Limits**: 3-second timeout, 1,000 rows, 1 MB per value.

Tests switch off each layer in turn and show that the others still block writes.
Error messages shown to users never include internal details.

## Configuration

All settings are optional environment variables (or `.env`, see `.env.example`):

| Variable | Default | Purpose |
|----------|---------|---------|
| `INSIGHTSQL_DB_PATH` | `data/insightsql.db` | SQLite database path |
| `AI_PROVIDER` | `gemini` | AI service for AI Mode: `gemini` or `huggingface` |
| `GEMINI_API_KEY` | *(none)* | Gemini API key; AI Mode (Gemini) is unavailable without it |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Any current Gemini text model ([list](https://ai.google.dev/gemini-api/docs/models)) |
| `GEMINI_TIMEOUT_SECONDS` | `30` | How long to wait for Gemini |
| `GEMINI_BASE_URL` | `https://generativelanguage.googleapis.com` | API address; must be https |
| `HF_TOKEN` | *(none)* | Hugging Face access token (only with `AI_PROVIDER=huggingface`) |
| `HF_MODEL` | `Qwen/Qwen2.5-Coder-32B-Instruct` | Any chat model offered by Inference Providers (e.g. `meta-llama/Llama-3.3-70B-Instruct`) |
| `HF_TIMEOUT_SECONDS` | `30` | How long to wait for the model |
| `HF_BASE_URL` | `https://router.huggingface.co/v1` | API address; must be https (the token is sent with each request) |

## Tests

```bash
pip install -r requirements-dev.txt
pytest                      # all 416 tests, about 1.5 minutes
pytest -m "not e2e"         # skip the browser tests (about 25 seconds)
```

Tests never use the internet, a real AI model, or your database. Browser tests need
Chromium (`playwright install chromium`) or Google Chrome; without either they are
skipped and the reason is shown. See [TESTING.md](TESTING.md) for the test design and
requirement traceability.

## Project structure

```
app.py                  Page setup, sidebar (mode + status) and navigation
views/                  One small file per page; each calls src/ui/<page>.py
.streamlit/config.toml  Dark theme (colours, fonts, radii, chart palette)
assets/                 Logo and icon (SVG)
src/
  ui/                   Interface only: theme.py (CSS + chart theme), charts.py (Altair),
                        components.py, session.py (state; the UI's one call into the
                        query pipeline), dashboard.py, analyst.py, history.py,
                        explorer.py, settings.py
  analytics.py          Dashboard KPIs and chart data (fixed SQL through run_query)
  config.py             Settings from environment / .env
  database.py           Schema, connections, seeding, query history
  sample_data.py        Deterministic sample data
  sql_guard.py          SQL validation + SQLite authorizer
  query_service.py      answer_question() / run_query(): the one pipeline for every query
  demo_queries.py       Demo Mode questions and SQL
  ai_providers.py       Chooses the AI service (AI_PROVIDER)
  ai_prompt.py          Shared prompt (real schema) and reply parsing
  gemini_service.py     AI Mode with Gemini (official google-genai SDK; never runs SQL)
  hf_service.py         AI Mode with Hugging Face (optional; never runs SQL)
  insights.py           Chart choice and factual explanations
scripts/seed_database.py  Rebuild the sample database
scripts/check_ai_mode.py  Compare the real AI model's answers with Demo Mode
tests/                  Unit, integration, app (AppTest) and browser (Playwright) tests
DEMO.md                 Step-by-step demo script
TESTING.md              Testing approach and traceability
```

## Deploying

On Streamlit Community Cloud, point the app at `app.py`; `requirements.txt` holds the
runtime dependencies. To enable AI Mode there, add `GEMINI_API_KEY = "..."` under
**Settings → Secrets** (top-level secrets become environment variables); never put the
token in the repository. Without it, the deployed app runs in Demo Mode.

## Known limitations

- A small local model can write SQL that is safe but wrong (for example, a wrong
  grouping). The SQL is always shown so it can be checked. AI Mode has been tested only
  in the automated tests against a fake API server; `scripts/check_ai_mode.py` checks the
  real model.
- At desktop width, the example question buttons cut off long questions with "…".
- Charts are drawn only for results with one label column and one numeric column.
- Browser tests run in Chromium/Chrome only.
