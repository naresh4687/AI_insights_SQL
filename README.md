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

InsightSQL has a sidebar-based interface in a light theme (warm off-white with blue accents)
and a matching dark theme. The sidebar holds the page links, the
**Mode** selector (Demo Mode or AI Mode), the **Dataset** selector (the demo sales data or
any imported dataset; used by the AI Analyst and SQL Explorer), a status card showing
whether the selected mode is ready, and the **Dark mode** switch. Switching theme is instant and
keeps everything on the page (answers, filters, chat); the browser remembers the choice, and the
first visit is always light. On a phone the sidebar starts collapsed; open it with the arrow at top left.

| Page | What it does |
|------|--------------|
| **Dashboard** | Total revenue, total sales, products and average sale value, calculated live from the database; revenue over time (with the latest month compared with the month before), by region, by category, and the top five products; recent questions. |
| **AI Analyst** | A chat. Click a suggested question or type your own and press Enter. Each answer shows a factual summary and four tabs: **Results** (table and **Download CSV**), **Visualization** (the best chart first, plus a **Chart type** picker: bar, column, line, area, pie, donut, scatter, histogram, box plot, or KPI cards for a single row), **SQL** (the validated query and *What this query does*), and **Insights** (period-over-period changes, shares, outliers and statistics, all computed from the result). Follow-up questions appear under the latest answer; errors come with a hint. **Add to dashboard** saves the answer's validated SQL, dataset and chosen chart type to a dashboard. The conversation is kept while you move between pages; **New chat** clears it. |
| **Dashboard Studio** | Your own dashboards built from saved answers: create, rename, duplicate and delete them; **Edit layout** to move charts, change their width (full, half, one third), title and chart type; add **date, category and number filters** that narrow every chart showing that column; **Refresh data** (re-run the queries) or **Refresh source data** (fetch from connections first); download each chart's data as CSV and the dashboard definition as JSON. Every chart re-runs its validated query on its own dataset, so a dashboard can read only what the AI Analyst could. |
| **Query History** | Every question with its outcome (Success, Rejected or Failed), searchable and filterable. **Ask again** re-asks the question in the current mode; **Open in SQL Explorer** puts the stored SQL in the editor. Stored SQL is never run directly. |
| **SQL Explorer** | Run your own single read-only `SELECT` on `products` and `sales` (try `DROP TABLE sales` to see it rejected), or load the last AI-generated SQL. |
| **Import Data** | Upload a CSV or Excel (.xlsx) file and follow seven steps: original preview → data-quality checks (errors, warnings, passed) → cleaning options → cleaned preview → summary of changes → save. Changes that remove or replace data must be confirmed. The original file is kept unchanged in `data/uploads/`, the cleaned table goes to `data/datasets.db`, and the dataset is listed in the catalog. Choose the saved dataset in the sidebar to ask about it. |
| **Connections** | Save a PostgreSQL, MySQL or REST API connection (passwords and tokens are stored encrypted and never shown again), test it, browse tables (or call an endpoint with pagination), preview, and **Fetch for import**: the snapshot then goes through the same quality checks, cleaning and save steps as an uploaded file. Connections are read-only and questions never run on your server. Needs `INSIGHTSQL_SECRET_KEY`. |
| **Datasets** | Every dataset with its source, columns, quality and refresh status. For datasets from a connection: **Refresh now**, refresh mode (full, or incremental by key and cursor column for database tables), a schedule, and the refresh history. A failed refresh never replaces the last good data. |
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
   The allowed tables are a per-request *scope* (`allowed_tables`): the selected dataset's
   own tables (`products` and `sales` for the demo data), resolved through the dataset
   catalog by `src/data_access.py`. A question about one dataset cannot read another
   dataset, the demo tables or internal tables. Imported data is in a separate file
   (`data/datasets.db`), so demo tables are not even present there.
2. **Engine-level authorizer**: a SQLite callback that allows only reads of those two
   tables and a list of safe functions.
3. **Read-only connection** (`mode=ro`) with `PRAGMA query_only`.
4. **Limits**: 3-second timeout, 1,000 rows, 1 MB per value.

Tests switch off each layer in turn and show that the others still block writes.

**Connections** (PostgreSQL, MySQL, REST): only public addresses unless a host is allow-listed
(SSRF protection; every resolved address is checked, metadata endpoints always refused);
database sessions are read-only on the server with timeouts; only tables the server lists
outside system schemas can be read, through SQLAlchemy-built queries; APIs must use https,
never follow redirects, keep next-page links on the same host, ignore proxy settings, and are
limited in size, pages and records. Secrets are Fernet-encrypted and redacted from logs.
For imported datasets the AI prompt lists only that dataset's column names and types: never
data values, and never the dataset's name or description (free text that could carry
instructions).
Error messages shown to users never include internal details.

## Configuration

All settings are optional environment variables (or `.env`, see `.env.example`):

| Variable | Default | Purpose |
|----------|---------|---------|
| `INSIGHTSQL_DB_PATH` | `data/insightsql.db` | SQLite database path (demo data and query history) |
| `INSIGHTSQL_APP_DB_PATH` | `data/app.db` | App metadata: the dataset catalog (separate, because reseeding deletes the demo database) |
| `INSIGHTSQL_DATASETS_DB_PATH` | `data/datasets.db` | Imported and synchronised datasets (used from the data-import phase) |
| `INSIGHTSQL_UPLOADS_DIR` | `data/uploads` | Original uploaded files, kept unchanged |
| `INSIGHTSQL_IMPORT_MAX_MB` | `25` | Largest file accepted; also raise `[server] maxUploadSize` in `.streamlit/config.toml` |
| `INSIGHTSQL_IMPORT_MAX_ROWS` | `200000` | Most data rows per file |
| `INSIGHTSQL_IMPORT_MAX_COLUMNS` | `200` | Most columns per file |
| `INSIGHTSQL_SECRET_KEY` | *(none)* | Encrypts saved connection secrets. Create with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`; keep a copy |
| `INSIGHTSQL_ALLOWED_PRIVATE_HOSTS` | *(none)* | Private/local servers connections may reach, e.g. `localhost:5432,db.internal:3306` (cloud metadata addresses are always blocked) |
| `INSIGHTSQL_CONNECTOR_TIMEOUT_SECONDS` | `15` | Connect and read timeout for databases and APIs |
| `INSIGHTSQL_AUTH` | `none` | `oidc` turns on sign-in (see **User accounts**); `none` is for an app only this computer can reach |
| `INSIGHTSQL_ADMIN_EMAILS` | *(none)* | Accounts that are always administrators |
| `INSIGHTSQL_ALLOWED_SIGNINS` | *(none)* | Emails or `@domains` that may sign in without an invitation |
| `INSIGHTSQL_DEFAULT_ROLE` | `viewer` | Role for people let in by `INSIGHTSQL_ALLOWED_SIGNINS` (`viewer` or `editor`) |
| `INSIGHTSQL_LOG_LEVEL` | `WARNING` | Log level for the app's own messages; secrets are always redacted |
| `AI_PROVIDER` | `gemini` | AI service for AI Mode: `gemini` or `huggingface` |
| `GEMINI_API_KEY` | *(none)* | Gemini API key; AI Mode (Gemini) is unavailable without it |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Any current Gemini text model ([list](https://ai.google.dev/gemini-api/docs/models)) |
| `GEMINI_TIMEOUT_SECONDS` | `30` | How long to wait for Gemini |
| `GEMINI_BASE_URL` | `https://generativelanguage.googleapis.com` | API address; must be https |
| `HF_TOKEN` | *(none)* | Hugging Face access token (only with `AI_PROVIDER=huggingface`) |
| `HF_MODEL` | `Qwen/Qwen2.5-Coder-32B-Instruct` | Any chat model offered by Inference Providers (e.g. `meta-llama/Llama-3.3-70B-Instruct`) |
| `HF_TIMEOUT_SECONDS` | `30` | How long to wait for the model |
| `HF_BASE_URL` | `https://router.huggingface.co/v1` | API address; must be https (the token is sent with each request) |

## User accounts

Without sign-in (`INSIGHTSQL_AUTH=none`, the default) the app has one local user with full
rights. **Do not make such an app reachable from other computers.** For a team or the
internet, turn on sign-in with Google or Microsoft (OpenID Connect, through Streamlit's
`st.login`); InsightSQL never stores passwords.

1. Register a web application with your provider and add the redirect address
   `https://<your-app>/oauth2callback` (`http://localhost:8501/oauth2callback` for testing).
2. Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and fill in the
   client id, client secret and a random `cookie_secret`.
3. In `.env`: `INSIGHTSQL_AUTH=oidc` and `INSIGHTSQL_ADMIN_EMAILS=you@example.com`.
4. Restart the app and sign in. Invite others on **Users & Audit**, or let a whole domain in
   with `INSIGHTSQL_ALLOWED_SIGNINS=@example.com`.

If the sign-in settings are incomplete, the app shows what is missing and lets nobody in.

| Role | Can |
|------|-----|
| Viewer | Ask questions about the demo data and anything shared with everyone; view shared dashboards |
| Editor | Also import data, save connections, build dashboards; change only their own |
| Admin | Everything, for every user; manage users; read the audit log |

Datasets and dashboards are private to their owner until the owner shares them (read-only)
with everyone who signs in; a chart on a shared dashboard is shown only to people who may read
its dataset. Connections are never shared (they hold the owner's password or token). Each
person sees only their own query history. Items made before sign-in was turned on belong to
no one until an administrator gives them to an account (**Users & Audit**). The audit log
records sign-ins (including refused ones), user and role changes, and every create, change,
share and delete; it cannot be edited from the app.

## Tests

```bash
pip install -r requirements-dev.txt
pytest                      # all 1,188 tests, about 5–10 minutes
pytest -m "not docker"      # without the PostgreSQL/MySQL container tests (they need Docker)
pytest -m "not e2e"         # skip the browser tests (about 1.5 minutes)
```

Tests never use the internet, a real AI model, or your database. Browser tests need
Chromium (`playwright install chromium`) or Google Chrome; without either they are
skipped and the reason is shown. See [TESTING.md](TESTING.md) for the test design and
requirement traceability.

## Project structure

```
app.py                  Page setup, sidebar (mode + status) and navigation
views/                  One small file per page; each calls src/ui/<page>.py
.streamlit/config.toml  Light (default) and dark themes (palette, fonts, radii, chart colours)
assets/                 Logo and icon (SVG)
src/
  ui/                   Interface only: theme.py (light/dark tokens, CSS, chart theme), charts.py (Altair),
                        components.py, session.py (state; the UI's one call into the
                        query pipeline), dashboard.py, analyst.py, history.py,
                        explorer.py, settings.py
  core/                 models.py (Dataset, TableInfo, statuses), logging_setup.py
                        (secret redaction for all log output)
  storage/app_db.py     App metadata database and its versioned migrations
  catalog.py            Dataset catalog: registered datasets and their query scope
  data_access.py        Resolves a dataset to its database file and allowed tables
  ingest/               Data import: readers.py (CSV/Excel → text), types.py (type detection),
                        profiling.py, validation.py, preprocess.py (cleaning options and
                        change summary), store.py (all-or-nothing save)
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
  insights.py           Default chart choice and the one-line explanation
  analysis.py           Chart options, statistics, facts and follow-up questions (from the result only)
  sql_explain.py        Plain-language SQL explanations and error hints (no AI call)
  export.py             CSV export with spreadsheet-formula protection
  dashboards.py         Dashboard Studio: saved dashboards, layout, filters (parameterised), running charts
  accounts.py           Users, roles, sign-in rules and the access rules (view / change)
  audit.py              Append-only audit log
  ui/auth.py            Sign-in gate (runs before any page); ui/users.py: Users & Audit page
  connectors/           network.py (SSRF policy), profiles.py (saved connections), databases.py
                        (PostgreSQL/MySQL), rest.py (REST APIs), snapshot.py (to an import)
  core/secrets.py       Encryption of saved connection secrets
  sync/                 refresh.py (full and incremental refresh, retries, locks), state.py
                        (settings, run log, locks)
scripts/refresh_worker.py Runs scheduled refreshes (cron / systemd timer)
scripts/seed_database.py  Rebuild the sample database
scripts/check_ai_mode.py  Compare the real AI model's answers with Demo Mode
tests/                  Unit, integration, app (AppTest) and browser (Playwright) tests
reports/                Phase reports (baseline, foundation, …)
DEMO.md                 Step-by-step demo script
TESTING.md              Testing approach and traceability
```

## Scheduled refreshes

Streamlit cannot run reliable background jobs, so scheduled refreshes run in a separate
process. Run it every few minutes, with the same `.env` as the app:

```bash
# crontab -e
*/5 * * * *  cd /path/to/insightsql && .venv/bin/python scripts/refresh_worker.py --once
```

It refreshes the datasets whose schedule is due (Datasets page) and exits with 1 if any
refresh failed. This is periodic polling, not real-time streaming. Incremental refresh adds
new rows and replaces changed ones by a unique key; rows deleted at the source are removed
only by a full refresh.

## Deploying

On Streamlit Community Cloud, point the app at `app.py`; `requirements.txt` holds the
runtime dependencies. To enable AI Mode there, add `GEMINI_API_KEY = "..."` under
**Settings → Secrets** (top-level secrets become environment variables); never put the
token in the repository. Without it, the deployed app runs in Demo Mode.

For sign-in there, paste the `[auth]` sections of your `secrets.toml` into the same Secrets
box and add `INSIGHTSQL_AUTH = "oidc"` and `INSIGHTSQL_ADMIN_EMAILS = "you@example.com"`.
Community Cloud's disk is temporary: accounts, imported data and dashboards are lost when the
app restarts, so use a server with a persistent disk for real use.

## Deployment

Run it on a server with Docker: the app, a worker for scheduled refreshes and daily backups, and an HTTPS proxy. Step-by-step guide and production checklist: [DEPLOYMENT.md](DEPLOYMENT.md).

## Known limitations

- A small local model can write SQL that is safe but wrong (for example, a wrong
  grouping). The SQL is always shown so it can be checked. AI Mode has been tested only
  in the automated tests against a fake API server; `scripts/check_ai_mode.py` checks the
  real model.
- At desktop width, the example question buttons cut off long questions with "…".
- Summaries and follow-up questions are computed from the result, not written by the AI:
  an AI-written summary would require sending result data to the AI service.
- CSV export contains only the rows shown (at most 1,000).
- Browser tests run in Chromium/Chrome only.
- Import: only `.csv`/`.txt` and `.xlsx`/`.xlsm` (not old `.xls`); one worksheet per import;
  Excel formulas are read as their last saved values. In a one-column CSV an empty value is
  indistinguishable from a blank line, so such lines are skipped (and reported).
- Non-English column names become `column_N` (rename them on the Import page).
- Dataset, dashboard and connection names are unique across all users, so a name another user
  already took is refused ("already exists").
- Sign-in is tested with a stand-in for the identity provider; the real Google/Microsoft
  round trip is not part of the automated tests.
