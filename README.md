# InsightSQL — AI-Powered SQL Data Analyst

Ask business questions about your data in plain English. InsightSQL turns the question into a
SQL query, checks that the query is safe, runs it **read-only**, and shows the answer as a
summary, a table, a chart and the exact SQL that ran.

This README is the project's only document. It explains everything step by step: what the app
does, how to install and run it (on a laptop, on a phone, on a server), how to use every page,
how to demonstrate it, how it keeps data safe, how it is tested, and how it was built.

---

## Contents

1. [What InsightSQL does](#1-what-insightsql-does)
2. [How it works](#2-how-it-works)
3. [Install and run it (step by step)](#3-install-and-run-it-step-by-step)
4. [Use it on your phone](#4-use-it-on-your-phone)
5. [Using the app, page by page](#5-using-the-app-page-by-page)
6. [Demo script (show and explain the app)](#6-demo-script-show-and-explain-the-app)
7. [AI Mode (Gemini or Hugging Face)](#7-ai-mode-gemini-or-hugging-face)
8. [Your own data: import, connections, refresh](#8-your-own-data-import-connections-refresh)
9. [User accounts and sign-in](#9-user-accounts-and-sign-in)
10. [How queries and data are kept safe](#10-how-queries-and-data-are-kept-safe)
11. [The sample data](#11-the-sample-data)
12. [Configuration (all settings)](#12-configuration-all-settings)
13. [Put it online (deployment)](#13-put-it-online-deployment)
14. [Backups and restore](#14-backups-and-restore)
15. [Testing](#15-testing)
16. [Project structure](#16-project-structure)
17. [Project history](#17-project-history)
18. [Known limitations](#18-known-limitations)
19. [Questions you may get](#19-questions-you-may-get)

---

## 1. What InsightSQL does

| Feature | In one sentence |
|---------|-----------------|
| **Ask in plain English** | Type "Which five products generated the highest revenue?" and get the answer, a chart and the SQL. |
| **Demo Mode** (default) | Five example questions with hand-written SQL: no AI, no internet, no key needed. |
| **AI Mode** | Google Gemini (or Hugging Face) writes the SQL for any question; only the question and the table structure are sent, never your data. |
| **Safety first** | Whoever writes the SQL (Demo Mode, the AI, or you), it passes four safety layers and can only read. |
| **Dashboard** | Live revenue, sales and product figures with four charts. |
| **Import your data** | Upload CSV or Excel, check its quality, clean it, and ask questions about it. |
| **Connections** | Read data from PostgreSQL, MySQL or a REST API; refresh it on a schedule. |
| **Dashboard Studio** | Save answers as charts on your own dashboards, with filters. |
| **Accounts** | Optional sign-in with Google or Microsoft; viewer / editor / admin roles; audit log. |
| **Light and dark theme** | A "Dark mode" switch; works on desktop, tablet and phone. |
| **Deployment** | Docker setup with HTTPS, a refresh worker and daily backups. |

---

## 2. How it works

```
 Your question
      │
      ▼
 SQL is written by ── Demo Mode (predefined SQL) ── or ── AI Mode (Gemini / Hugging Face)
      │                                                    or ── you (SQL Explorer)
      ▼
 Safety layer 1: SQL parser check (one read-only SELECT, allowed tables only)
 Safety layer 2: database-engine authorizer (reads of allowed tables and safe functions only)
 Safety layer 3: read-only database connection
 Safety layer 4: limits (3 seconds, 1,000 rows)
      │
      ▼
 Result → summary · table · chart · SQL · insights · saved in Query History
```

- The AI only **proposes** SQL. It never touches the database, and its prompt is not relied on
  for safety: everything it writes goes through the same checks.
- Summaries, charts, insights and follow-up questions are computed from the real result, not
  written by the AI, so they never state a number that is not in the data.

Built with **Python 3.12** and **Streamlit 1.65**; data in **SQLite**; charts with **Altair**;
SQL parsing with **sqlglot**.

---

## 3. Install and run it (step by step)

Tested with Python 3.12 on Linux.

**Step 1 — Get the code**

```bash
git clone https://github.com/naresh4687/AI_insights_SQL.git insightsql
cd insightsql
```

**Step 2 — Create a virtual environment and install**

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt    # use requirements-dev.txt to also run the tests
```

**Step 3 — (Optional) settings**

```bash
cp .env.example .env               # the defaults work; see section 12 for every setting
```

**Step 4 — Start the app**

```bash
streamlit run app.py
```

**Step 5 — Open it:** http://localhost:8501

The demo database (`data/insightsql.db`) is created and filled with sample data on the first
run. **Stop** the app with `Ctrl+C` in the terminal.

To rebuild the sample data: `python scripts/seed_database.py`. Note: this also **empties the
Query History**.

**Run it with Docker instead** (the same setup as a server, see section 13):

```bash
mkdir -p backups
docker compose up -d --build
docker compose ps        # wait until the app shows "healthy"
```

Open http://localhost. Stop with `docker compose down` (your data is kept). If port 80 is
busy, add `HTTP_PORT=8088` to `.env` and open http://localhost:8088.

---

## 4. Use it on your phone

InsightSQL is a **web app**: on a phone it opens in the browser (Chrome or Safari). There is
nothing to install from the Play Store or App Store.

**On the same Wi-Fi as your laptop**

1. Start the app on the laptop so other devices can reach it:

   ```bash
   streamlit run app.py --server.address 0.0.0.0
   ```

2. Find the laptop's address: `hostname -I` (Linux) or `ipconfig` (Windows), for example
   `192.168.1.20`.
3. On the phone (same Wi-Fi), open `http://192.168.1.20:8501`.
4. Tap **☰** (top left) for the menu: pages, Mode, Dataset and **Dark mode**.

If the phone cannot open it, allow the port in the laptop's firewall (Linux:
`sudo ufw allow 8501`).

**Add an icon to the home screen** (opens the app in one tap):
Android Chrome: ⋮ menu → **Add to Home screen**. iPhone Safari: Share → **Add to Home Screen**.
It works while the laptop runs the app and the phone is on the same Wi-Fi.

**From anywhere** (without your laptop): the app must run on a server with a web address
(section 13).

> With sign-in off (the default), anyone on the same Wi-Fi who knows the address can use the
> app. That is fine for a demo; stop it afterwards (`Ctrl+C`).

---

## 5. Using the app, page by page

The **sidebar** holds the page links, the **Mode** selector (Demo Mode or AI Mode), the
**Dataset** selector (the demo sales data or any imported dataset; used by the AI Analyst and
SQL Explorer), a status card that says whether the selected mode is ready, and the
**Dark mode** switch. On a phone the sidebar starts closed; open it with the arrow or **☰** at
the top left.

**Theme.** A light theme (warm off-white `#EFECE3`, soft blue `#8FABD4`, primary blue
`#4A70A9`, black text) and a matching dark theme. Switching is instant and keeps everything on
the page (answers, filters, chat); nothing is reloaded or run again. The browser remembers the
choice, and the first visit is always light.

| Page | What it does |
|------|--------------|
| **Dashboard** | Total revenue, total sales, products and average sale value, calculated live from the database; revenue over time (the latest month compared with the month before), by region, by category, and the top five products; recent questions. |
| **AI Analyst** | A chat. Click a suggested question or type your own and press Enter. Each answer shows a factual summary and four tabs: **Results** (table and **Download CSV**), **Visualization** (the best chart first, plus a **Chart type** picker: bar, column, line, area, pie, donut, scatter, histogram, box plot, or KPI cards for a single row), **SQL** (the validated query and *What this query does*), and **Insights** (period-over-period changes, shares, outliers and statistics, all computed from the result). Follow-up questions appear under the latest answer; errors come with a hint. **Add to dashboard** saves the answer to a dashboard. The conversation is kept while you move between pages; **New chat** clears it. |
| **Dashboard Studio** | Your own dashboards built from saved answers: create, rename, duplicate and delete them; **Edit layout** to move charts and change their width (full, half, one third), title and chart type; add **date, category and number filters** that narrow every chart showing that column; **Refresh data** (re-run the queries) or **Refresh source data** (fetch from connections first); download each chart's data as CSV and the dashboard definition as JSON. Every chart re-runs its validated query on its own dataset. |
| **Import Data** | Upload a CSV or Excel (.xlsx) file and follow the steps: original preview → data-quality checks (errors, warnings, passed) → cleaning options → cleaned preview → summary of changes → save. Changes that remove or replace data must be confirmed. The original file is kept unchanged; the cleaned table is saved as a dataset you can choose in the sidebar. |
| **Connections** | Save a PostgreSQL, MySQL or REST API connection (passwords and tokens are stored encrypted and never shown again), test it, browse tables (or call an endpoint, with pagination), preview, and **Fetch for import**: the snapshot then goes through the same checks, cleaning and save steps as an uploaded file. Needs `INSIGHTSQL_SECRET_KEY`. |
| **Datasets** | Every dataset with its source, columns, quality and refresh status. For datasets from a connection: **Refresh now**, refresh mode (full, or incremental by key and cursor column), a schedule, and the refresh history. A failed refresh never replaces the last good data. |
| **Query History** | Every question with its outcome (Success, Rejected or Failed), searchable and filterable. **Ask again** re-asks the question in the current mode; **Open in SQL Explorer** puts the stored SQL in the editor. Stored SQL is never run directly. |
| **SQL Explorer** | Run your own single read-only `SELECT` (try `DROP TABLE sales` to see it rejected), or load the last AI-generated SQL. |
| **Settings & About** | Current mode, AI provider and model, whether a key is configured (never the key itself), a **Test connection** button, database status and setup steps. |
| **Users & Audit** | (Admins, with sign-in on.) Invite people, change roles, disable accounts, give unowned items an owner, read the audit log. |

---

## 6. Demo script (show and explain the app)

About 8 minutes; a short version is at the end. The figures come from the fixed sample data,
so they are the same on every machine. Use **Demo Mode**: it needs no internet and no key, so
nothing can go wrong during the demo.

**Ways to show it:** share your screen on a video call (easiest), show it on a laptop in the
room and let people open it on their own phone over the Wi-Fi (section 4), or send them a link
to a deployed copy (section 13).

### Before the demo

```bash
source .venv/bin/activate
python scripts/seed_database.py     # optional: fresh data and an EMPTY Query History
streamlit run app.py                # open http://localhost:8501
```

For part 4 (AI Mode), set `GEMINI_API_KEY` in `.env` before starting. Without a key or
internet, show part 4b instead.

### 1. The problem (30 s)

> "Business users have questions about their sales data but can't write SQL. InsightSQL lets
> them ask in plain English and shows the answer, the SQL behind it, and a chart, without
> ever letting a query change the data."

Start on the **Dashboard**: total revenue **$283,700.56**, **600** sales, **12** products,
average sale value **$472.83**, all calculated live, plus four charts. Point out the **Mode**
selector: **Demo Mode** is the default and needs no AI.

### 2. Ask a question (2 min)

1. Click **Ask the AI Analyst**, then **"Which five products generated the highest revenue?"**
2. Walk through the answer:
   - **Badge**: Success, 5 rows, measured run time.
   - **Summary**: *Laptop Pro 14 has the highest revenue (102,900.00) and Noise-Cancelling
     Headphones the lowest (23,796.00)*. It only states figures that are in the result.
   - **SQL source**: predefined SQL, no AI request made.
   - Tabs: **Results** (table), **Visualization** (sorted bars, other chart types),
     **SQL** (the exact query, with a copy button), **Insights**.
3. Open **Suggested questions** → **"What were the monthly sales totals?"** The chart is now a
   line because the labels are months: *highest 44,655.27 in 2025-06, lowest 17,119.37 in
   2025-04*. The first answer stays in the conversation.
4. Open **Query History**: both questions, newest first, marked Success.

### 3. Safety (2 min)

1. In the AI Analyst, type *"Who is our best salesperson?"* → **Request rejected** (Demo Mode
   answers only its suggested questions).
2. In **SQL Explorer**, run `DROP TABLE sales` → **Request rejected**: only one read-only
   SELECT is allowed.
3. Run `SELECT * FROM query_history` → rejected: that table cannot be read.
4. Run `SELECT region, COUNT(*) AS sales FROM sales GROUP BY region` → it works, and the data
   is still there.

> "Every query, whether it comes from Demo Mode, the AI or a user, passes four layers: a SQL
> parser check, a database-engine authorizer, a read-only connection, and time and row
> limits. The tests switch off each layer in turn to prove the others still hold."

### 4. AI Mode (2 min)

1. Select **AI Mode (Gemini)**. A green box confirms the model is available.
2. Ask something that is not an example, such as *"How many units were sold in each region?"*
   A spinner shows while the model works; the answer is labelled **AI-generated SQL —
   validated before running**.
3. Ask *"Delete all the sales data"*. Either the model declines, or its SQL is rejected by the
   safety layer. Nothing is deleted either way.

> "The AI only proposes SQL. It never touches the database directly, and the prompt is not
> relied on for safety."

**4b. Without a key or internet:** select AI Mode; a warning explains how to get a key (or
that the connection failed). Ask a question to show the clear **Query failed** message, then
switch back to Demo Mode to show it still works.

### 5. Your own data and dashboards (1 min)

1. **Import Data**: upload a CSV; show the quality checks and the cleaning summary; save.
2. Choose the new dataset in the sidebar and ask about it.
3. On an answer, **Add to dashboard**; open **Dashboard Studio** to see the chart and its filters.

### 6. Polish and testing (30 s)

Flip **Dark mode**, open the app on a phone, and mention the tests:

> "1,303 automated tests, including tests that drive the real app in Chrome on desktop,
> tablet and phone sizes, in both themes. No test needs the internet or a real AI model; AI
> Mode is tested against a fake Gemini server, including malicious replies. We also planted
> bugs on purpose to check the tests catch them."

### The 5-minute version

Problem (30 s) → Dashboard → one AI Analyst question with its SQL and chart → `DELETE FROM
sales` rejected in SQL Explorer → import a CSV → Dark mode and the phone view.

---

## 7. AI Mode (Gemini or Hugging Face)

**Gemini (default)**

1. Create a Gemini API key at https://aistudio.google.com/apikey.
2. Put it in `.env`: `GEMINI_API_KEY=...` (`.env` is git-ignored; never commit the key).
3. Restart the app and select **AI Mode (Gemini)**.

A green message confirms the key is accepted and the model exists; a warning explains what to
fix if the key is missing or invalid, or the model name is wrong. Demo Mode keeps working
either way. Usage counts against your Gemini quota (a free tier is available:
https://ai.google.dev/gemini-api/docs/pricing); if it runs out, AI Mode shows a clear quota
message. The default model is `gemini-3.5-flash-lite`.

To compare the real model's answers with Demo Mode: `python scripts/check_ai_mode.py --repeat 2`.

**Hugging Face (alternative):** set `AI_PROVIDER=huggingface` and `HF_TOKEN` (a token with the
permission "Make calls to Inference Providers"; needs Inference Providers credit).

**What is sent to the AI:** only the question and the table structure (column names and
types). Never data values, and never a dataset's name or description (free text that could
carry instructions).

---

## 8. Your own data: import, connections, refresh

**Import (CSV / Excel).** Import Data → choose a file (up to 25 MB, 200,000 rows, 200 columns)
→ review the quality checks → choose cleaning options → check the change summary → save. The
original file is kept unchanged in `data/uploads/`; the cleaned table goes to
`data/datasets.db`. Choose the dataset in the sidebar to ask about it.

**Connections (PostgreSQL, MySQL, REST APIs).**

1. Set `INSIGHTSQL_SECRET_KEY` in `.env` (it encrypts saved passwords and tokens):

   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

   Keep a copy of this key somewhere safe: without it, saved passwords cannot be read.
2. Connections → add a connection → **Test** → browse tables (or call an endpoint) →
   **Fetch for import** → the normal import steps.

Connections may reach only public addresses unless a host is allow-listed in
`INSIGHTSQL_ALLOWED_PRIVATE_HOSTS` (for example `localhost:5432`). Database sessions are
read-only; questions never run on your server, only on the imported snapshot.

**Refresh.** On the **Datasets** page, a dataset from a connection can be refreshed now or on a
schedule, fully or incrementally (new rows added, changed rows replaced by a unique key; rows
deleted at the source are removed only by a full refresh). A failed refresh never replaces the
last good data.

Streamlit cannot run reliable background jobs, so scheduled refreshes run in a separate
process (the Docker setup runs it for you as the `worker` service). Without Docker, run it
every few minutes with the same `.env` as the app:

```bash
# crontab -e
*/5 * * * *  cd /path/to/insightsql && .venv/bin/python scripts/refresh_worker.py --once
```

or keep it running: `python scripts/refresh_worker.py --loop --interval 60`. It exits with 1 if
any refresh failed. This is periodic polling, not real-time streaming.

---

## 9. User accounts and sign-in

Without sign-in (`INSIGHTSQL_AUTH=none`, the default) the app has one local user with full
rights. **Do not make such an app reachable from other computers** except for a short demo on a
private network. For a team or the internet, turn on sign-in with Google or Microsoft (OpenID
Connect, through Streamlit's `st.login`); InsightSQL never stores passwords.

**Step by step**

1. Register a web application with your provider and add the redirect address
   `https://<your-app>/oauth2callback` (`http://localhost:8501/oauth2callback` for testing).
   - Google: https://console.cloud.google.com/apis/credentials → Create credentials → OAuth
     client ID → Web application.
   - Microsoft (Entra ID): https://entra.microsoft.com → App registrations → New
     registration; add the optional `email` claim to the ID token.
2. Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and fill in the client
   id, client secret and a random `cookie_secret`
   (`python -c "import secrets; print(secrets.token_urlsafe(48))"`).
3. In `.env`: `INSIGHTSQL_AUTH=oidc` and `INSIGHTSQL_ADMIN_EMAILS=you@example.com`.
4. Restart the app and sign in. Invite others on **Users & Audit**, or let a whole domain in
   with `INSIGHTSQL_ALLOWED_SIGNINS=@example.com`.

If the sign-in settings are incomplete, the app shows what is missing and lets nobody in.

| Role | Can |
|------|-----|
| Viewer | Ask questions about the demo data and anything shared with everyone; view shared dashboards |
| Editor | Also import data, save connections, build dashboards; change only their own |
| Admin | Everything, for every user; manage users; read the audit log |

Datasets and dashboards are private to their owner until shared (read-only) with everyone who
signs in; a chart on a shared dashboard is shown only to people who may read its dataset.
Connections are never shared (they hold the owner's password or token). Each person sees only
their own query history. Items made before sign-in was turned on belong to no one until an
administrator assigns them (**Users & Audit**). The audit log records sign-ins (including
refused ones), user and role changes, and every create, change, share and delete; it cannot be
edited from the app.

---

## 10. How queries and data are kept safe

The AI prompt asks for read-only SQL, but the prompt is **not** treated as a security
boundary. Every query passes through:

1. **Parser check** (`src/sql_guard.py`, using sqlglot): exactly one statement, which must be a
   `SELECT` (CTEs allowed); no writes, DDL, `PRAGMA`, `ATTACH` or recursive CTEs; only the
   allowed tables. The SQL that runs is regenerated from the parsed tree, so comments and
   hidden extras are dropped. The allowed tables are a per-request *scope*: the selected
   dataset's own tables (`products` and `sales` for the demo data), resolved through the
   dataset catalog (`src/data_access.py`). A question about one dataset cannot read another
   dataset, the demo tables or internal tables. Imported data is in a separate file
   (`data/datasets.db`).
2. **Engine-level authorizer**: a SQLite callback that allows only reads of those tables and a
   list of safe functions.
3. **Read-only connection** (`mode=ro`) with `PRAGMA query_only`.
4. **Limits**: 3-second timeout, 1,000 rows, 1 MB per value.

Tests switch off each layer in turn and show that the others still block writes.

**Connections:** only public addresses unless allow-listed (SSRF protection; every resolved
address is checked; cloud metadata addresses always refused); database sessions are read-only
on the server, with timeouts; only tables the server lists outside system schemas can be read,
through SQLAlchemy-built queries; APIs must use https, never follow redirects, keep next-page
links on the same host, ignore proxy settings, and are limited in size, pages and records.

**Secrets:** saved connection secrets are Fernet-encrypted; keys and tokens are redacted from
all log output and never shown in the app. Error messages shown to users never include
internal details. CSV exports are protected against spreadsheet-formula injection.

---

## 11. The sample data

Deterministic sample data (seed 42), the same on every machine:

| Table | Rows | Columns |
|-------|-----:|---------|
| `products` | 12 | `product_id`, `product_name`, `category` (4), `unit_price` |
| `sales` | 600 | `sale_id`, `product_id`, `sale_date` (2025), `region` (4), `quantity`, `unit_price` (after a 0/5/10 % discount) |

Revenue is `SUM(sales.quantity * sales.unit_price)`. A third table, `query_history`, stores the
history and cannot be read by queries.

---

## 12. Configuration (all settings)

All settings are optional environment variables, usually set in `.env` (copy `.env.example`).

| Variable | Default | Purpose |
|----------|---------|---------|
| `INSIGHTSQL_DB_PATH` | `data/insightsql.db` | Demo data and query history |
| `INSIGHTSQL_APP_DB_PATH` | `data/app.db` | App data: dataset catalog, accounts, dashboards, connections, audit log |
| `INSIGHTSQL_DATASETS_DB_PATH` | `data/datasets.db` | Imported and synchronised datasets |
| `INSIGHTSQL_UPLOADS_DIR` | `data/uploads` | Original uploaded files, kept unchanged |
| `INSIGHTSQL_IMPORT_MAX_MB` | `25` | Largest file accepted; also raise `[server] maxUploadSize` in `.streamlit/config.toml` |
| `INSIGHTSQL_IMPORT_MAX_ROWS` | `200000` | Most data rows per file |
| `INSIGHTSQL_IMPORT_MAX_COLUMNS` | `200` | Most columns per file |
| `INSIGHTSQL_SECRET_KEY` | *(none)* | Encrypts saved connection secrets (section 8); keep a copy |
| `INSIGHTSQL_ALLOWED_PRIVATE_HOSTS` | *(none)* | Private/local servers connections may reach, e.g. `localhost:5432,db.internal:3306` |
| `INSIGHTSQL_CONNECTOR_TIMEOUT_SECONDS` | `15` | Connect and read timeout for databases and APIs |
| `INSIGHTSQL_REFRESH_MAX_ATTEMPTS` | `3` | Attempts per refresh when the source fails temporarily |
| `INSIGHTSQL_REFRESH_RETRY_SECONDS` | `30` | Wait before retrying (doubles each attempt) |
| `INSIGHTSQL_AUTH` | `none` | `oidc` turns on sign-in (section 9) |
| `INSIGHTSQL_ADMIN_EMAILS` | *(none)* | Accounts that are always administrators |
| `INSIGHTSQL_ALLOWED_SIGNINS` | *(none)* | Emails or `@domains` that may sign in without an invitation |
| `INSIGHTSQL_DEFAULT_ROLE` | `viewer` | Role for people let in by `INSIGHTSQL_ALLOWED_SIGNINS` (`viewer` or `editor`) |
| `INSIGHTSQL_LOG_LEVEL` | `WARNING` | Log level for the app's own messages; secrets are always redacted |
| `AI_PROVIDER` | `gemini` | `gemini` or `huggingface` |
| `GEMINI_API_KEY` | *(none)* | Gemini API key; AI Mode (Gemini) is unavailable without it |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Any current Gemini text model ([list](https://ai.google.dev/gemini-api/docs/models)) |
| `GEMINI_TIMEOUT_SECONDS` | `30` | How long to wait for Gemini |
| `GEMINI_BASE_URL` | `https://generativelanguage.googleapis.com` | API address; must be https |
| `HF_TOKEN` | *(none)* | Hugging Face access token (only with `AI_PROVIDER=huggingface`) |
| `HF_MODEL` | `Qwen/Qwen2.5-Coder-32B-Instruct` | Any chat model offered by Inference Providers |
| `HF_TIMEOUT_SECONDS` | `30` | How long to wait for the model |
| `HF_BASE_URL` | `https://router.huggingface.co/v1` | API address; must be https |

**Docker-only settings** (also in `.env`, see section 13):

| Setting | Default | Meaning |
|---------|---------|---------|
| `SITE_ADDRESS` | `http://localhost` | Your domain name (HTTPS automatic) or `http://localhost` |
| `HTTP_PORT` / `HTTPS_PORT` | `80` / `443` | Ports on the server |
| `TZ` | `UTC` | Time zone for the backup schedule, e.g. `Europe/London` |
| `INSIGHTSQL_BACKUP_AT` | `02:00` | Daily backup time |
| `INSIGHTSQL_BACKUP_KEEP` | `7` | How many backups are kept |
| `BACKUP_DIR` | `./backups` | Backup folder on the server |
| `COMPOSE_FILE` | `compose.yaml` | Set to `compose.yaml:compose.signin.yaml` when sign-in is on |

Inside the containers the data paths are fixed (`/data/...`); the paths in `.env` are only for
running without Docker.

---

## 13. Put it online (deployment)

Right now the app runs only where you start it. To make it **live for people anywhere**, choose:

| | **A. Your own server with Docker** (recommended for real use) | **B. Streamlit Community Cloud** (free demo link) |
|---|---|---|
| Cost | A small server (about $5–10 a month) + a domain (about $10 a year) | Free |
| Address | Your own, e.g. `https://insights.example.com` | `https://<name>.streamlit.app` |
| Data people add | Kept, with daily backups | Lost when the app restarts (temporary disk) |
| Scheduled refresh and backups | Yes | No |
| Effort | About an hour, following the steps below | About 15 minutes |

### A. Your own server with Docker

Three services run from `compose.yaml`:

| Service | What it does |
|---------|--------------|
| **app** | The Streamlit app. Checks its settings first and stops with a clear message if one must be fixed |
| **worker** | Scheduled dataset refreshes, and a daily backup (02:00 by default) |
| **proxy** | Caddy: the only part reachable from outside. HTTPS with a free certificate when you give it a domain name |

All data (databases and uploaded files) lives in the Docker volume `insightsql_data`; backups go
to `./backups`. The image contains no secrets or data, and runs as a normal user (uid 1000).

**Step 1 — Get a server and a domain.** Any small Linux VPS with Docker (`docker compose version`
should work), and a domain name.

**Step 2 — Point the domain at the server.** Add a DNS "A" record, for example
`insights.example.com` → the server's IP address.

**Step 3 — Open ports 80 and 443** in the server's firewall (and nothing else to the public).

**Step 4 — Copy the project to the server and set `.env`:**

```bash
git clone https://github.com/naresh4687/AI_insights_SQL.git insightsql && cd insightsql
cp .env.example .env
```

Add to `.env`:

```bash
SITE_ADDRESS=insights.example.com
TZ=Europe/London                 # your time zone: the daily backup follows it
INSIGHTSQL_SECRET_KEY=...        # see section 8 for the command that makes one
```

**Step 5 — Turn on sign-in** (section 9), with the redirect address
`https://insights.example.com/oauth2callback`, and add to `.env`:

```bash
INSIGHTSQL_AUTH=oidc
INSIGHTSQL_ADMIN_EMAILS=you@example.com
COMPOSE_FILE=compose.yaml:compose.signin.yaml   # gives the app secrets.toml (read-only)
```

**Do not run a public server with sign-in off.**

**Step 6 — Start it:**

```bash
mkdir -p backups && sudo chown 1000:1000 backups   # the app runs as user 1000
docker compose up -d --build
docker compose ps                                   # app: "healthy"
```

Caddy gets the HTTPS certificate by itself within a minute; open
**https://insights.example.com**. If a setting is missing, the app does not start, and
`docker compose logs app` says what to fix.

**Everyday commands**

| Task | Command |
|------|---------|
| Status | `docker compose ps` |
| Messages | `docker compose logs -f app` (or `worker`, `proxy`) |
| Update to new code | `git pull` then `docker compose up -d --build` |
| Stop / start | `docker compose down` / `docker compose up -d` |
| Backup now | `docker compose exec worker python scripts/backup.py create` |
| List backups | `docker compose exec worker python scripts/backup.py list` |

Never run `docker compose down -v`: `-v` **deletes the data volume**.

**Production checklist**

- [ ] `INSIGHTSQL_AUTH=oidc`, `INSIGHTSQL_ADMIN_EMAILS` set, `compose.signin.yaml` in `COMPOSE_FILE`
- [ ] `SITE_ADDRESS` is your domain, and the site opens with **https://**
- [ ] `INSIGHTSQL_SECRET_KEY` set, and **a copy kept somewhere other than the server**
      (backups do not contain it)
- [ ] `.env` and `.streamlit/secrets.toml` readable only by you (`chmod 600`), never committed
- [ ] `TZ` set; a backup appears in `./backups` the next day; **copy `./backups` off the server regularly**
- [ ] Restore tried once (section 14)
- [ ] Only ports 80 and 443 open

### B. Streamlit Community Cloud (free demo link)

1. Sign in at https://share.streamlit.io with GitHub and create an app from this repository,
   main file `app.py` (`requirements.txt` holds the runtime dependencies).
2. For AI Mode, add `GEMINI_API_KEY = "..."` under **Settings → Secrets** (never in the
   repository). Without it, the app runs in Demo Mode.
3. For sign-in, paste the `[auth]` sections of your `secrets.toml` into the same Secrets box
   and add `INSIGHTSQL_AUTH = "oidc"` and `INSIGHTSQL_ADMIN_EMAILS = "you@example.com"`.

Community Cloud's disk is temporary: accounts, imported data and dashboards are lost when the
app restarts. Use option A for real use.

---

## 14. Backups and restore

A database that is being written cannot safely be copied byte by byte, so backups use SQLite's
online backup API (consistent even while the app and the worker are running), then an
integrity check. Each backup is one dated folder:

```
backups/20261012-020000/
    insightsql.db  app.db  datasets.db  uploads/  manifest.json
```

The Docker worker makes one every day at `INSIGHTSQL_BACKUP_AT` and keeps the newest
`INSIGHTSQL_BACKUP_KEEP`. A manual backup earlier in the day does not replace the scheduled one;
a failed backup is reported and never stops the refreshes.

**Without Docker**

```bash
python scripts/backup.py create [--dir backups] [--keep 7]
python scripts/backup.py list
python scripts/backup.py restore 20261012-020000 --yes    # stop the app first
```

**Restore with Docker**

```bash
docker compose stop app worker
docker compose run --rm --no-deps worker python scripts/backup.py list
docker compose run --rm --no-deps worker python scripts/backup.py restore 20261012-020000 --yes
docker compose start app worker
```

Restoring checks every database in the backup before changing anything, and needs `--yes`.
The encryption key (`INSIGHTSQL_SECRET_KEY`) is never part of a backup: keep a copy elsewhere.

---

## 15. Testing

### How to run

```bash
pip install -r requirements-dev.txt
pytest                      # everything: 1,303 tests, about 11 minutes
pytest -m "not docker"      # without the Docker tests
pytest -m "not e2e"         # without the browser tests
pytest -m e2e               # browser tests only
```

- **Browser tests** use Playwright's Chromium if installed (`playwright install chromium`),
  otherwise Google Chrome. Set `INSIGHTSQL_E2E_CHANNEL=chrome` or `chromium` to force one.
  Screenshots go to `test-results/e2e/`.
- **Docker tests** (marker `docker`) start real PostgreSQL 17 and MySQL 8.4 containers and the
  full deployment stack. If Docker or the images are missing they are **skipped** and the
  reason is shown (`-ra`), so check for skips before calling a run green. If your computer
  has two Docker engines (for example Docker Desktop and the system engine), point the tests at
  the one with the images: `DOCKER_CONTEXT=default pytest -m docker`.

No test uses the internet, a real AI model, or your real data: every test gets temporary
databases, and AI Mode is tested against `FakeGemini` and `FakeHF` (`tests/conftest.py`), real
HTTP servers on 127.0.0.1 that answer like the Gemini and Hugging Face APIs with dummy keys.
The official Gemini SDK runs unchanged against the fake. Autouse fixtures remove any real AI
keys loaded from `.env` and point every data store at the test's temporary folder.
`scripts/check_ai_mode.py` is a separate, manual check against the real model.

### Test layers

| Layer | Files | What it proves |
|-------|-------|----------------|
| Unit | `test_database.py`, `test_sql_guard.py`, `test_query_scope.py`, `test_catalog.py`, `test_logging_setup.py`, `test_ingest_*.py`, `test_analysis.py`, `test_explain_export_charts.py`, `test_insights.py`, `test_gemini_service.py`, `test_hf_service.py` | Each module on its own: schema and seed data, SQL validation and the authorizer, import (reading, detection, cleaning, all-or-nothing saving), charts and explanations, the AI clients (keys, errors, privacy) |
| Integration | `test_dataset_integration.py`, `test_query_service.py`, `test_demo_mode.py`, `test_ai_mode.py`, `test_gemini_ai_mode.py` | Question → SQL → validation → read-only execution → history, for Demo Mode, typed SQL and AI Mode, including each safety layer switched off in turn |
| Connectors | `test_connector_security.py`, `test_connector_rest.py`, `test_connector_databases.py` (Docker) | SSRF policy, encrypted secrets, read-only sessions, pagination, limits, type mapping, import of snapshots |
| Refresh | `test_refresh.py`, `test_refresh_databases.py` (Docker) | A failed refresh changes no data; no duplicates; correct counts; retries, locks, schedule, worker |
| Dashboards | `test_dashboards.py` | Storage rules, layout, filters checked against pandas, injection through filter values, tampered stored SQL, dataset scope, export without data |
| Accounts and access | `test_accounts.py`, `test_auth_ui.py` | Nobody gets in without an allowed, verified identity; each user reaches only their own and shared items, through every page; append-only audit log |
| Theme | `test_theme.py` + theme section of `test_app_e2e.py` | Exact palette; config and code agree; WCAG contrast of every text and control pair (including text on glass); light on first visit; the Dark mode switch sends nothing to the server and keeps the answer; choice kept after reload and in a new tab; every page in both themes at 1280 / 768 / 375 px |
| Deployment | `test_deployment.py`, `test_deployment_docker.py` (Docker) | Backup and restore, consistent copies during writes, pruning, daily schedule, start-up checks; the real stack: no secrets in the image, non-root, app only through the proxy, worker backup, data survives replacing containers, bad sign-in settings stop the start |
| App (no browser) | `test_app_ui.py`, `test_import_ui.py`, `test_dataset_ui.py`, `test_analyst_features_ui.py`, `test_connections_ui.py`, `test_datasets_ui.py`, `test_studio_ui.py` | `app.py` run by Streamlit's `AppTest` on every page: navigation, KPIs and chart data checked against the database, chat state, history, SQL Explorer security, settings, empty states |
| End-to-end (browser) | `test_app_e2e.py` | The real server in Chrome: navigation, chat with the Enter key, tabs, spinner, error styling, history → Explorer revalidation, separate sessions, phone and tablet layouts, no console errors, screenshots |

### AI-assisted test design workflow

Tests were designed with an AI coding assistant (Claude Code) using the steps below. The
assistant drafts; the checks in steps 3–5 decide whether a test is kept.

1. **Requirements to risks.** For each requirement, list what could go wrong, worst first.
   Example for AI Mode: the model returns `DROP TABLE`; it returns two statements; the question
   contains a prompt injection; the API is unreachable or slow; the key is missing, invalid or
   leaked into a log.
2. **Draft cases for each risk,** including the unhappy paths. A person reviews the list for
   gaps before any code is written.
3. **Independent oracles.** Expected values never come from the code under test: revenue is
   recomputed in plain Python from the generated rows, and explanations may only contain
   figures that appear in the result.
4. **Run and read failures.** A failing test is investigated before either side is changed, and
   the root cause recorded (for example, one failure was a test bug: a number in a product name).
5. **Mutation check.** Deliberately break the code and confirm tests fail. A planted bug that no
   test catches means a test is missing or too weak.
6. **Look at the result.** Screenshots are reviewed by eye, because tests only check what they
   were told to check.

What steps 5 and 6 found (examples):

| Planted bug or review finding | Before | After the fix |
|-------------------------------|--------|---------------|
| Errors shown as plain grey text instead of a red alert | Not caught: tests only checked the text | Tests require the error alert |
| 700 px-wide element on a 375 px screen | Not caught: Streamlit scrolls inside its own container | Overflow check also looks there |
| Example buttons cut long questions with "…" (screenshot review) | No test failed | Recorded as a known limitation |
| A manual backup cancelling the scheduled one; a new install missing its demo database until the first visit (found by the deployment tests) | — | Fixed, with tests |

### Requirements traceability

| Requirement | Tests |
|-------------|-------|
| Seeded sample data with correct revenue | `test_database.py` (oracle, golden values) |
| Only one read-only `SELECT` on allowed tables | `test_sql_guard.py`; `test_query_service.py`; `test_app_ui.py::test_unsafe_sql_is_rejected_and_data_unchanged`; `test_app_e2e.py::test_unsafe_sql_is_rejected_in_the_browser_and_data_unchanged` |
| Defence in depth (each layer alone still blocks writes) | `test_ai_mode.py::test_*_disabled` |
| Demo Mode answers the 5 example questions correctly, offline | `test_demo_mode.py` (network blocked) |
| AI Mode: model SQL validated; malicious output rejected | `test_ai_mode.py`; `test_app_ui.py::test_ai_mode_rejects_malicious_model_output`; `test_app_e2e.py::test_ai_mode_rejects_malicious_model_output` |
| AI failures give clear messages; Demo Mode still works | `test_gemini_service.py`; `test_gemini_ai_mode.py`; `test_hf_service.py`; `test_app_e2e.py::test_gemini_unreachable_shows_help_and_demo_mode_still_works` |
| Key never sent insecurely, logged or shown; no sales data sent | `test_gemini_service.py`, `test_hf_service.py` (`test_insecure_or_invalid_base_url_*`, `test_*_never_appears_*`, `test_request_contains_no_sales_data`) |
| SQL preview, results table, explanation, suitable chart | `test_app_ui.py`; `test_insights.py`; `test_app_e2e.py::test_example_button_shows_sql_table_chart_explanation_and_history`, `test_monthly_question_draws_a_line_chart` |
| Progress indicator while waiting | `test_app_e2e.py::test_ai_mode_shows_spinner_then_ai_answer` |
| Query history; reruns revalidated | `test_app_ui.py::test_history_*`, `test_tampered_history_*`; `test_app_e2e.py::test_history_sql_opens_in_explorer_and_is_revalidated` |
| Dashboard figures are real | `test_app_ui.py::test_kpis_match_the_database`, `test_dashboard_charts_draw_the_query_results` |
| Secrets never displayed | `test_app_ui.py::test_settings_never_shows_the_key_*`; `test_app_e2e.py::test_settings_shows_status_but_never_the_key` |
| Sign-in required and fails closed | `test_auth_ui.py::test_without_sign_in_settings_the_app_stays_closed`, `test_visitor_sees_only_the_sign_in_screen` |
| Only invited / allowed, verified identities | `test_accounts.py::test_uninvited_*`, `test_same_email_from_another_identity_is_refused`, `test_unverified_email_is_refused` |
| Roles and per-user data | `test_accounts.py::test_access_matrix`, `test_private_datasets_are_invisible_to_others`, `test_history_is_kept_per_user`; `test_auth_ui.py::test_pages_follow_the_role` |
| Audit log of changes | `test_accounts.py::test_audit_log_cannot_be_changed`, `test_role_changes_and_invites_are_audited` |
| Works on phone and tablet, in both themes | `test_app_e2e.py::test_narrow_screen_has_no_horizontal_scroll`, `test_every_page_in_both_themes_fits_without_errors` |
| Backups are consistent and restorable; deployment keeps data and secrets safe | `test_deployment.py`; `test_deployment_docker.py` |

### Not covered by automated tests

- The real Gemini model (run `scripts/check_ai_mode.py` with `GEMINI_API_KEY` set). The fake
  proves the app handles any reply safely, not that a real model writes correct SQL.
- Browsers other than Chromium/Chrome.
- The real sign-in round trip with Google or Microsoft (tests replace the provider with fixed
  identity claims). Try it by hand once with your own settings.
- A real domain with a real HTTPS certificate (needs a public server).
- Screen readers (contrast, focus and reduced-motion are tested).

---

## 16. Project structure

```
app.py                  Page setup, sign-in gate, sidebar and navigation
views/                  One small file per page; each calls src/ui/<page>.py
.streamlit/config.toml  Light (default) and dark themes; upload limit
.streamlit/secrets.toml.example   Sign-in settings template (copy to secrets.toml)
assets/                 Logo and icon (SVG)
src/
  ui/                   Interface only: theme.py (light/dark tokens, CSS, Dark mode switch,
                        chart theme), charts.py (Altair), components.py, session.py,
                        auth.py (sign-in gate), users.py (Users & Audit), and one module per page
  core/                 models.py, logging_setup.py (secret redaction), secrets.py (encryption)
  storage/app_db.py     App database and its versioned migrations
  catalog.py            Dataset catalog: registered datasets and their query scope
  data_access.py        Resolves a dataset to its database file and allowed tables
  ingest/               Import: readers, type detection, profiling, validation, cleaning, saving
  connectors/           SSRF policy, saved connections, PostgreSQL/MySQL, REST APIs, snapshots
  sync/                 Refresh: full and incremental, retries, locks, run log
  analytics.py          Dashboard KPIs and chart data
  config.py             Settings from environment / .env
  database.py           Schema, connections, seeding, query history
  sample_data.py        Deterministic sample data
  sql_guard.py          SQL validation + SQLite authorizer
  query_service.py      answer_question() / run_query(): the one pipeline for every query
  demo_queries.py       Demo Mode questions and SQL
  ai_providers.py, ai_prompt.py, gemini_service.py, hf_service.py   AI Mode (never runs SQL)
  insights.py, analysis.py, sql_explain.py   Charts, facts, insights and SQL explanations
  export.py             CSV export with spreadsheet-formula protection
  dashboards.py         Dashboard Studio
  accounts.py, audit.py Users, roles, access rules; append-only audit log
  backup.py             Online backups, pruning and restore
  preflight.py          Start-up checks for a deployed app
scripts/
  seed_database.py      Rebuild the sample database (empties the history)
  check_ai_mode.py      Compare the real AI model's answers with Demo Mode
  refresh_worker.py     Scheduled refreshes (and, with --backup-at, the daily backup)
  backup.py             Backup / list / restore from the command line
  preflight.py          Check the settings before starting
Dockerfile, .dockerignore, compose.yaml, compose.signin.yaml, deploy/Caddyfile   Deployment
requirements.txt        Runtime dependencies; requirements-dev.txt adds the test tools
tests/                  Unit, integration, app (AppTest), browser (Playwright) and Docker tests
```

---

## 17. Project history

The app was built in reviewed phases. Each phase started with an inspection and a plan the
owner approved, ended with the full test suite passing, and was recorded in a phase report
(the detailed reports and progress logs are kept in the git history).

| Phase | What was built | Tests after the phase |
|-------|----------------|-----------------------|
| Original build (phases 1–8) | Setup; SQLite schema and deterministic seed; the SQL safety layer and read-only execution; Demo Mode; the Streamlit dashboard, chat, charts and history; AI SQL generation (all output validated); integration and Playwright browser tests with the AI-assisted test design workflow; README, demo script, clean-environment check | 416 |
| 00 Discovery and baseline | Inspection of the whole app; risks; plan for the next phases | 468 |
| 01 Foundation | App database with migrations, dataset catalog, per-dataset query scope, secret redaction in logs | 545 |
| 02 Import and validation | CSV/Excel import, type detection, data-quality checks, cleaning with a change summary, all-or-nothing save | 712 |
| 03 Dataset integration | Ask questions about imported datasets, isolated from each other and from the demo data | 766 |
| 04 AI Analyst | Chart type picker, insights, plain-language SQL explanations, follow-up questions, CSV export | 875 |
| 05 Connections | PostgreSQL, MySQL and REST APIs; SSRF protection; encrypted secrets; read-only sessions | 1,018 |
| 06 Refresh | Full and incremental refresh, retries, locks, schedules, the refresh worker | 1,070 |
| 07 Dashboard Studio | Your own dashboards with layout editing, filters and exports | 1,122 |
| 08 Accounts and access | Sign-in with Google or Microsoft, roles, private and shared items, audit log | 1,188 |
| UI theme redesign | Light and dark themes in the brand palette, the Dark mode switch, glass styling, logo, accessibility (contrast, focus, reduced motion and transparency), every page tested in both themes at three screen sizes | 1,268 |
| 09 Deployment | Docker image, Compose stack with HTTPS proxy and worker, daily backups and restore, start-up checks | 1,303 |

---

## 18. Known limitations

- An AI model can write SQL that is safe but wrong (for example, a wrong grouping). The SQL is
  always shown so it can be checked.
- At desktop width, the example question buttons cut off long questions with "…".
- Summaries and follow-up questions are computed from the result, not written by the AI (an
  AI-written summary would require sending result data to the AI service).
- CSV export contains only the rows shown (at most 1,000).
- Import: only `.csv`/`.txt` and `.xlsx`/`.xlsm` (not old `.xls`); one worksheet per import;
  Excel formulas are read as their last saved values. In a one-column CSV an empty value cannot
  be told apart from a blank line, so such lines are skipped (and reported).
- Non-English column names become `column_N` (rename them on the Import page).
- Dataset, dashboard and connection names are unique across all users, so a name another user
  already took is refused ("already exists").
- Accounts can be disabled, not deleted; there is no "sign out everywhere".
- The Dark mode switch uses Streamlit's own theme menu: after upgrading Streamlit, run the
  browser tests (they fail if it changes). On the very first visit with a dark system setting,
  the page may show dark for a moment before turning light.
- Community Cloud (deployment option B) loses imported data and accounts on restart.
- Browser tests run in Chromium/Chrome only.

---

## 19. Questions you may get

- **Can the AI be tricked into deleting data?** No. It is tested with malicious model output and
  prompt injection, and with each safety layer disabled in turn.
- **Is the AI's answer always right?** Not guaranteed. A query can be safe but wrong, so the SQL
  is always shown.
- **Does data leave the machine?** Only the question and the table structure are sent to the AI
  service, never the data rows. A test checks this. The key stays in `.env`.
- **Can I use it on my phone?** Yes, in the browser (section 4); it is tested at phone size.
- **Can other people use it?** On your Wi-Fi for a demo, or anywhere once deployed (section 13)
  with sign-in on.
- **What happens if the server breaks?** Data is backed up every day and can be restored with one
  command (section 14).
