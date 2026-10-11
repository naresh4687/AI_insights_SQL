# Phase 00 — Discovery and Baseline

| Item | Value |
|------|-------|
| Phase | 00 — Discovery and baseline |
| Date | 2026-10-11 |
| Repository | `~/projects/insightsql`, branch `main`, HEAD `41255b9` (pushed to `github.com/naresh4687/AI_insights_SQL`) |
| Code changes in this phase | **None.** Only this report was added. |
| Final status | **COMPLETE** — awaiting approval |

---

## 1. Scope and acceptance criteria

Inspect the real project and establish a baseline before any expansion. No features implemented.

| # | Acceptance criterion | Met? |
|---|----------------------|------|
| AC1 | Verified file and directory inventory | Yes — §3 |
| AC2 | Architecture and dependency summary | Yes — §4 |
| AC3 | Existing features with their locations | Yes — §5 |
| AC4 | Existing tests listed | Yes — §6 |
| AC5 | Baseline test results actually executed | Yes — §7 |
| AC6 | Risks and unknowns | Yes — §9 |
| AC7 | Proposed architecture and phase plan | Yes — §10, §11 |

**The project is not empty.** It is a working Streamlit application (v1.1.0) with 468 passing tests.
All work from Phase 01 onwards must therefore extend it without regressions.

---

## 2. Files created, modified, deleted

| Change | File |
|--------|------|
| Created | `reports/phase_00_baseline.md` (this report) |
| Modified | none |
| Deleted | none |

The database was opened **read-only** only. The seed script was not run.

---

## 3. Verified inventory

Source: `git ls-files` + `wc -l` (56 tracked files, 7,498 lines). Ignored, present locally:
`.env` (holds the Gemini key), `.venv/`, `data/insightsql.db`, caches, `test-results/`.

| Area | Files (lines) |
|------|---------------|
| Entry point | `app.py` (61) — page config, theme, navigation, sidebar mode selector |
| Page shims | `views/{dashboard,analyst,history,explorer,settings}.py` (5 each) — call `src/ui/*.render()` |
| UI code | `src/ui/`: `dashboard.py` 118, `analyst.py` 88, `history.py` 72, `explorer.py` 54, `settings.py` 95, `session.py` 127, `components.py` 73, `charts.py` 62, `theme.py` 145 |
| Core services | `src/query_service.py` 168, `src/sql_guard.py` 128, `src/database.py` 120, `src/analytics.py` 97, `src/insights.py` 116, `src/demo_queries.py` 62, `src/sample_data.py` 60, `src/config.py` 95 |
| AI | `src/ai_providers.py` 42, `src/ai_prompt.py` 98, `src/gemini_service.py` 192, `src/hf_service.py` 200 |
| Scripts | `scripts/seed_database.py` 26, `scripts/check_ai_mode.py` 142 |
| Tests | `tests/` — 11 test files + `conftest.py` 288 (see §6) |
| Config | `requirements.txt`, `requirements-dev.txt`, `pytest.ini`, `.env.example`, `.gitignore`, `.streamlit/config.toml` |
| Assets | `assets/logo.svg`, `assets/icon.svg` |
| Docs | `README.md` 169, `DEMO.md` 95, `TESTING.md` 100, `PROJECT_PLAN.md` 148, `PROJECT_PROGRESS.md` 1185 |

There is no `reports/` directory before this phase; it was created for this report.

---

## 4. Architecture and dependencies

### 4.1 Current architecture (modular monolith, verified by reading the code)

```
Streamlit (app.py → st.navigation → views/*.py → src/ui/*.render())
        │
        ▼
src/ui/session.run(text, source)          one entry point for every request
        │   source = "demo" | "ai" | "sql"
        ▼
query_service.answer_question()           question checks, history recording
        │   generate_sql = demo_queries.lookup_sql | ai_providers.generate_sql | identity
        ▼
query_service.run_query()                 the only path that executes SQL
        ├─ sql_guard.validate_sql()       sqlglot AST: one SELECT, ALLOWED_TABLES, no DDL/DML
        ├─ database.connect_readonly()    SQLite mode=ro + PRAGMA query_only
        ├─ sql_guard.ReadOnlyAuthorizer   engine-level allowlist of tables and functions
        └─ 3 s timeout, 1,000-row cap, 1 MB value limit
        ▼
pandas DataFrame → insights.choose_chart / explain → ui/charts (Altair) → UI
```

Dashboard figures (`src/analytics.py`) also run through `run_query`, without history.

### 4.2 Storage

One SQLite file, `data/insightsql.db` (git-ignored; created on first run by `ensure_database`):

| Table | Rows now | Role |
|-------|---------:|------|
| `products` | 12 | Demo data (deterministic, seed 42) |
| `sales` | 600 | Demo data |
| `query_history` | 11 | Internal — **user data**; denied to queries by the guard and authorizer |

`PRAGMA integrity_check` → `ok`.

### 4.3 Dependencies (pinned; `pip check` → "No broken requirements found.")

| Package | Version | Use |
|---------|---------|-----|
| streamlit | 1.65.0 | UI framework |
| pandas | 3.0.6 | Results |
| sqlglot | 30.22.0 | SQL parsing (guard) |
| python-dotenv | 1.2.4 | `.env` |
| google-genai | 2.29.0 | Gemini (default AI provider) |
| altair | 6.3.0 | Charts — **imported directly but not listed in `requirements.txt`** (comes in via Streamlit) |
| httpx | 0.28.1 | Hugging Face provider; Gemini SDK transport |
| pytest / playwright | 9.1.1 / 1.63.0 | Tests (dev) |

Not installed: SQLAlchemy, Plotly, openpyxl, psycopg, PyMySQL, cryptography, APScheduler.

### 4.4 Environment

Ubuntu 24.04.5 LTS · Python 3.12.3 · Docker available (`/usr/local/bin/docker`) · MySQL
client present · `psql` not installed · Google Chrome used for browser tests (Playwright's own
Chromium not downloaded).

---

## 5. Existing features (must be preserved)

| # | Feature | Location | Behaviour |
|---|---------|----------|-----------|
| F1 | **Demo Mode** | `src/demo_queries.py`, `session.SQL_SOURCES["demo"]` | 5 predefined questions → hand-written SQL; case/punctuation-insensitive; other questions rejected with guidance; offline |
| F2 | **AI Analyst Mode** | `src/ai_providers.py`, `gemini_service.py`, `hf_service.py`, `ai_prompt.py` | Question → Gemini (default) or Hugging Face → JSON `{"sql": …}` → guard → run. Only schema (no data) is sent |
| F3 | AI Analyst chat page | `src/ui/analyst.py`, `components.py` | Chat history, suggestion buttons, per-answer table, chart, SQL, summary, timing |
| F4 | SQL safety (3 layers) | `src/sql_guard.py`, `query_service.run_query` | AST validation, engine authorizer, read-only connection, timeout, row cap |
| F5 | Chart selection | `src/insights.choose_chart`, `src/ui/charts.py` | Line for period columns, horizontal bar otherwise; none when unsuitable |
| F6 | Result explanations | `src/insights.explain` | Factual summary from the result only (highest/lowest, ties, periods, truncation) |
| F7 | Dashboard | `src/ui/dashboard.py`, `src/analytics.py` | KPIs, month-over-month change, monthly revenue, revenue by region/category, top products, recent activity |
| F8 | Query History | `src/ui/history.py`, `database.recent_history` | Search, status filter, SQL view, rerun in current mode |
| F9 | SQL Explorer | `src/ui/explorer.py` | User SQL through the same guard; load last AI SQL |
| F10 | Settings & About | `src/ui/settings.py` | AI provider status, database facts |
| F11 | Sidebar mode switch + live status | `app.py` | Demo / AI Mode (provider name), cached status check |
| F12 | Theme | `.streamlit/config.toml`, `src/ui/theme.py` | Dark theme, badges, accessible status colours |
| F13 | Scripts | `scripts/seed_database.py`, `scripts/check_ai_mode.py` | Rebuild demo DB; live AI accuracy check |

---

## 6. Existing tests

Collected with `.venv/bin/pytest --co -q`:

| File | Tests | Covers |
|------|------:|--------|
| `test_sql_guard.py` | 56 | Guard: allowed/forbidden SQL, injection forms |
| `test_query_service.py` | 13 | Execution, limits, errors |
| `test_database.py` | 21 | Schema, seed determinism, history |
| `test_demo_mode.py` | 29 | Demo answers vs independent Python calculation |
| `test_insights.py` | 37 | Chart choice, explanations |
| `test_ai_mode.py` | 43 | AI path with Hugging Face fake server |
| `test_hf_service.py` | 68 | Hugging Face provider |
| `test_gemini_service.py` | 66 | Gemini provider (fake server) |
| `test_gemini_ai_mode.py` | 45 | AI path with Gemini, malicious-output cases |
| `test_app_ui.py` | 66 | Streamlit AppTest page flows |
| `test_app_e2e.py` | 24 | Playwright + Chrome against a live server (`-m e2e`) |
| **Total** | **468** | |

An autouse fixture in `conftest.py` removes real AI keys, so tests never call a real AI service.

---

## 7. Tests executed in this phase

| ID | Description | Expected | Actual | Status |
|----|-------------|----------|--------|--------|
| P00-T01 | Full test suite | All pass | `468 passed in 203.41s (0:03:23)` | PASS |
| P00-T02 | Test collection by file | Counts recorded | Table in §6 (sum 468) | PASS |
| P00-T03 | Dependency consistency | No conflicts | `No broken requirements found.` | PASS |
| P00-T04 | Live DB integrity (read-only connection) | `ok`, expected counts | `ok`; products 12, sales 600, query_history 11 | PASS |
| P00-T05 | App server start + all 5 pages | Health `ok`, HTTP 200 | Health `ok`; `/`, `/dashboard`, `/analyst`, `/history`, `/explorer`, `/settings` → 200; server stopped | PASS |
| P00-T06 | Secrets in tracked files | None found | Real Gemini key value not found in any tracked file; no `AIza…`/`ghp_…`/`hf_…` patterns | PASS |
| P00-T07 | Working tree clean before report | No changes | `git status --short` → 0 lines | PASS |

**Totals:** 7 checks — 7 PASS, 0 FAIL, 0 BLOCKED, 0 SKIPPED, 0 NOT RUN.
(P00-T01 itself contains 468 automated tests: 468 passed.)

Not checked in this phase: a live Gemini request (not needed for a baseline; last verified 2026-10-10 per `PROJECT_PROGRESS.md`).

### Regression baseline

| Area | Baseline evidence |
|------|-------------------|
| Demo Mode | `test_demo_mode.py` 29/29, Demo UI and e2e flows in P00-T01 |
| AI Analyst | `test_gemini_ai_mode.py` 45/45, `test_ai_mode.py` 43/43, UI and e2e flows in P00-T01 |

Every later phase must keep these 468 tests passing (or document any intentional, approved change).

---

## 8. Commands used

```bash
git ls-files | xargs wc -l | sort -k2
.venv/bin/pip list ; .venv/bin/pip check
.venv/bin/pytest -q                       # P00-T01
.venv/bin/pytest --co -q                  # P00-T02
.venv/bin/python -c "sqlite3 … mode=ro … PRAGMA integrity_check"   # P00-T04
.venv/bin/streamlit run app.py --server.headless true --server.port 8599 ; curl …   # P00-T05
git ls-files -z | xargs -0 grep -lF/-lE …   # P00-T06 (key value read from .env, never printed)
git status --short                         # P00-T07
```

---

## 9. Findings, risks and unknowns

### 9.1 Data-integrity and security findings

| ID | Finding | Severity | Recommendation |
|----|---------|----------|----------------|
| R1 | **No authentication.** Anyone who can reach the server can use it. | High once data is imported | Keep local-only (`localhost`) until Phase 08 auth is in place |
| R2 | `seed_sample_data()` **deletes the whole DB file** (`database.py:72`), which also wipes `query_history`. | Medium | Never store imported data or app metadata in this file; keep separate stores (§10) |
| R3 | `ALLOWED_TABLES` is a **global constant** used by both guard layers and the AI prompt. Imported datasets cannot be queried without changing it. | Design constraint | Make the allowlist a per-request *scope* with today's value as the default (Phase 01/03) |
| R4 | AI prompt schema comes from the static `SCHEMA_SQL` string. | Design constraint | Build it from the dataset catalog for the selected dataset (Phase 03) |
| R5 | Secrets exposed in chat on 2026-10-10/11 (Gemini key, GitHub password). | High (account) | User to rotate both; not a code issue |

### 9.2 Engineering risks

| ID | Risk | Impact |
|----|------|--------|
| R6 | `PROJECT_PROGRESS.md` is out of date: records 416 tests (app_ui 24, e2e 14); actual is 468 (app_ui 66, e2e 24). The page redesign (`views/`, `src/ui/`) is not documented there. | Docs mislead reviewers; new reports go in `reports/` |
| R7 | `altair` used directly but not pinned. | A Streamlit upgrade could change charts silently |
| R8 | Streamlit reruns per user session; it has **no reliable background scheduler**. | Scheduled refresh needs a separate worker process (Phase 06) |
| R9 | Streamlit has **no native drag-and-resize grid**. | Phase 07 needs a third-party component or ordered-grid controls |
| R10 | Streamlit Community Cloud has **ephemeral disk**. | Unsuitable once users import data; needs a VM/container with a volume (Phase 09) |
| R11 | Full suite takes ~3.4 min; e2e depends on installed Google Chrome. | Slower feedback; CI needs Chrome |
| R12 | Large uploads are held in memory (Streamlit default 200 MB upload limit). | Need explicit size/row limits (Phase 02) |

### 9.3 Unknowns (need your input or later verification)

1. Target deployment: single user on your laptop, a small team, or public internet? This decides authentication and storage choices.
2. Which PostgreSQL/MySQL/REST sources you will actually connect (for realistic tests).
3. Whether dashboard drag-and-drop is a must-have or reorder/resize controls are acceptable.

---

## 10. Proposed architecture (extends the current code; no framework change)

Keep **Streamlit**, the **single `run_query` execution path**, and all three guard layers.
Add modules alongside the existing ones:

```
src/
  core/        models.py (Dataset, Column, SourceType, statuses), logging_setup.py (secret redaction)
  storage/     app_db.py (metadata DB + numbered migrations), repositories (datasets, dashboards, jobs)
  catalog/     dataset registry: register, list, schema, permissions; demo data registered as built-in
  ingest/      readers (CSV/Excel), profiling, validation, preprocessing pipeline (Phase 02)
  connectors/  postgres.py, mysql.py, rest_api.py (Phase 05)
  sync/        refresh jobs, scheduler worker (Phase 06)
  dashboards/  dashboard model and rendering (Phase 07)
existing: query_service, sql_guard (gains a scope parameter), ai_* (schema from catalog), ui/
```

### Key decisions for approval (recommendation first)

| ID | Decision | Recommendation | Why | Alternative |
|----|----------|----------------|-----|-------------|
| D1 | Framework | **Keep Streamlit** | 468 tests and all features depend on it | Rewrite (rejected: no technical need) |
| D2 | Where imported/synced data lives | **New SQLite file `data/datasets.db`**; demo DB unchanged | Same engine ⇒ existing guard and authorizer apply unchanged; demo data isolated (R2) | DuckDB: faster analytics but **no authorizer hook**, so one security layer would be lost |
| D3 | App metadata (catalog, connections, dashboards, jobs, audit) | **New SQLite file `data/app.db`** with versioned migrations | Separate from both data stores; `query_history` stays where it is (no migration of user data) | Put it in `insightsql.db` (rejected: R2) |
| D4 | PostgreSQL/MySQL access model | **Snapshot into `datasets.db`** (manual/scheduled/incremental refresh) | One validated SQL dialect; no AI-generated SQL ever reaches your production DB | Live querying: fresher, but each dialect needs its own guard and a read-only account; could be added later |
| D5 | Guard allowlist | Per-request **scope** object; default = `{products, sales}` | Lets a question see only the selected, authorized dataset; fully backward compatible | — |
| D6 | Charts | **Keep Altair** (already used) | Supports bar, line, area, pie/donut, scatter, histogram, box plot; no new dependency | Plotly (adds a dependency; consider only if Altair falls short) |
| D7 | Credentials | **Fernet encryption** (`cryptography`) with key from `INSIGHTSQL_SECRET_KEY` env; never logged | Secrets never stored in plaintext | Store only env-var names per connection (simpler, less convenient) |
| D8 | Scheduling | **Separate worker** (`scripts/refresh_worker.py`) run by systemd timer/cron | Streamlit cannot run reliable background jobs (R8) | APScheduler inside Streamlit (rejected) |
| D9 | Authentication | Decide in Phase 08 after your answer to §9.3-1; candidate: Streamlit's built-in OIDC login (to be verified for 1.65) | — | Reverse-proxy auth |
| D10 | Deployment | Docker on an Ubuntu VM, persistent volume, HTTPS via reverse proxy | Persistent storage (R10) | Streamlit Community Cloud (demo only) |

New dependencies, added only in the phase that needs them: `openpyxl` (02), `SQLAlchemy`,
`psycopg`, `PyMySQL`, `cryptography` (05). `altair` will be pinned in Phase 01 (R7).

---

## 11. Phase plan

| Phase | Scope (summary) | Report |
|-------|-----------------|--------|
| **01 Foundation** | Pin `altair`; config for new paths and limits; logging with secret redaction; core models; `data/app.db` + migration runner; dataset catalog with the demo dataset registered as built-in; guard **scope** parameter (default = today's behaviour); isolated temp-storage fixtures; docs. **No UI or behaviour change.** All 468 tests must still pass. | `phase_01_foundation.md` |
| 02 Import | CSV/Excel upload → preview → profile → validate → preprocess → before/after → confirm → store in `datasets.db` | `phase_02_import_validation.md` |
| 03 Integration | Dataset selector; AI prompt and guard scoped to the chosen dataset; cross-dataset isolation tests | `phase_03_dataset_integration.md` |
| 04 AI Analyst | More chart types, recommendations, trends, statistics, SQL/error explanations, follow-ups, export | `phase_04_ai_analyst.md` |
| 05 Connectors | PostgreSQL, MySQL (Docker test containers), REST (mock server, SSRF protection) | `phase_05_connectors.md` |
| 06 Refresh | Manual, scheduled worker, incremental where supported; atomic swap keeps last valid data | `phase_06_refresh.md` |
| 07 Dashboard Studio | Saved dashboards, layout, filters, refresh, export | `phase_07_dashboard_studio.md` |
| 08 Security | Auth, authorization, audit, limits, security test pass | `phase_08_security.md` |
| 09 Deployment | Ubuntu/Docker setup, HTTPS, backups, monitoring, smoke tests | `phase_09_deployment.md` |

---

## 12. Known limitations of this phase

- No new tests were written (none were in scope); only existing tests and checks were run.
- The live AI path was not called.
- Phase 01+ estimates of effort depend on the decisions in §10 and unknowns in §9.3.

## 13. Final status

**COMPLETE.** Next proposed phase: **Phase 01 — Foundation** (scope in §11), after approval
of the decisions D1–D8.
