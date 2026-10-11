# InsightSQL — Project Progress Report

## Project Summary

| Item | Value |
|------|-------|
| **Project name** | InsightSQL — AI-Powered SQL Data Analyst |
| **Objective** | Let non-technical users ask business questions in natural language; generate or select SQL, validate it for safety, run it read-only against SQLite, and show tables, charts, and result-based explanations. Includes an AI-assisted automated testing workflow (pytest + Playwright). |
| **Current phase** | All 8 phases done; post-project change: AI Mode now uses Google Gemini by default (see the last section) |
| **Current status** | All 8 phases completed and verified, including a clean-environment install and test run. Live Gemini check done 2026-10-10: requests succeed; 3 of 5 demo questions match exactly and the other 2 return correct values with a different row count (see the last section). Open items: example buttons cut off their text on desktop (Phase 7); no git commit yet. |
| **Overall progress** | **100 %** (52 of 52 required phase tasks completed and verified — see weighting below) |
| **Verified automated tests** | **416 passed, 0 failed** (`.venv/bin/pytest -q`, 2026-10-10, after the Gemini change; includes 14 browser tests; baseline before the change: 299 passed) |
| **Outstanding critical issues** | None blocking. No git commits yet (all files untracked). Browser tests use the system Google Chrome (Playwright's own Chromium never downloaded). Live Gemini requests verified (`scripts/check_ai_mode.py`). The API key was pasted into the chat, so it should be replaced. |
| **Next planned action** | User replaces the exposed Gemini key. Pending decisions: whether the 2 differing AI answers need a prompt change; example-button layout; first git commit. |
| **Last updated** | 2026-10-10 |

### Phase tracking

| Phase | Name | Status | Verified Tests | Notes |
|-------|------|--------|----------------|-------|
| 1 | Environment and Setup | Completed | 1 passed (`tests/test_app_smoke.py`) | Reused existing `.venv`; server start confirmed (HTTP 200). Smoke test folded into `tests/test_app_ui.py` in Phase 5 |
| 2 | Database Development | Completed | 21 passed (`tests/test_database.py`) | Deterministic seed; mutation check confirmed tests detect defects |
| 3 | Backend and SQL Safety | Completed | 69 passed (`test_sql_guard.py` 56, `test_query_service.py` 13) | Parser layer + engine-level authorizer + read-only connection |
| 4 | Demo Mode | Completed | 29 passed (`tests/test_demo_mode.py`) | Shared `answer_question()` pipeline; results checked against independent Python calculation; network blocked in tests |
| 5 | Dashboard and UI | Completed | 48 passed (`test_insights.py` 37, `test_app_ui.py` 11) | Workflow verified with Streamlit AppTest + live server; visual screenshot skipped at the user's request (Chromium unavailable) |
| 6 | AI Integration | Completed | 91 new (`test_ollama_service.py` 43, `test_ai_mode.py` 42, `test_app_ui.py` +6) | Local Ollama (`qwen2.5:3b` default) via a fake HTTP server in tests; no real model run |
| 7 | Automated Testing | Completed | 14 new (`test_app_e2e.py`) | Playwright + system Chrome against a live server; mutation check found and fixed 2 weak tests; `TESTING.md` |
| 8 | Documentation and Final Verification | Completed | 272 passed (project and fresh environment) | Full README, `DEMO.md`; secrets scan clean |

### Progress weighting scheme

Phase progress = required tasks **completed and verified** ÷ required tasks listed for that
phase in the reporting instructions (§2). Partially done tasks count as 0 so progress is
never overstated. Overall progress = completed tasks across all phases ÷ total tasks.

| Phase | Required tasks | Completed + verified |
|-------|---------------:|---------------------:|
| 1 | 6 | 6 |
| 2 | 6 | 6 |
| 3 | 6 | 6 |
| 4 | 5 | 5 |
| 5 | 7 | 7 |
| 6 | 6 | 6 |
| 7 | 7 | 7 |
| 8 | 9 | 9 |
| **Total** | **52** | **52 → 100 %** |

### Checks performed when this report was first created (2026-10-10, before Phase 4 was resumed)

These were run when the report was created, to confirm the state at that time rather than
rely on earlier output. Later results are in each phase's section G.

| Check | Command or method | Result | Evidence |
|-------|-------------------|--------|----------|
| File inventory | `find . -type f` (excluding `.venv`, `.git`, caches) | PASS | 22 files, matching the files listed in the phase reports below |
| Git state | `git status --short`, `git log` | Observed | Repo on `main`, **no commits**, all project files untracked; `.venv/` and `data/insightsql.db` not listed (ignored) |
| Dependencies | `.venv/bin/pip check`, `pip list` | PASS | "No broken requirements found."; streamlit 1.65.0, pandas 3.0.6, python-dotenv 1.2.4, sqlglot 30.22.0, pytest 9.1.1, playwright 1.63.0 |
| Full test suite | `.venv/bin/pytest -q` | PASS | `91 passed in 2.30s` |
| Tests per file | `.venv/bin/pytest -v` | Observed | smoke 1, database 21, query_service 13, sql_guard 56 |
| Existing DB (read-only) | `connect_readonly("data/insightsql.db")` | PASS | products 12, sales 600, query_history 0; `PRAGMA foreign_key_check` → `[]`; `PRAGMA integrity_check` → `ok` |
| Demo SQL through the safety layer | `run_query()` on each `lookup_sql()` result (read-only) | PASS (ad hoc) | All 5 ran; first rows: Laptop Pro 14 102900.0; East 78731.9; Stationery 3825; 2025-01 18177.96; Protein Bars (12) 3484.8 |
| App server start | `streamlit run app.py --server.headless true --server.port 8599` + `curl` | PASS | `/_stcore/health` → `ok`; `GET /` → HTTP 200; afterwards port 8599 refused connections (curl exit 7), so the server was stopped |
| `.env` present? | `ls -la .env` | Observed | Not present — the app runs with defaults (Demo Mode) |
| Playwright browsers | `ls ~/.cache/ms-playwright` | Observed | Directory missing — browsers not installed |

No application code was changed while writing this report. The database was only opened read-only; the seed script was not rerun.

---

# Phase 1 — Environment and Project Setup

**Status:** Completed
**Completion date:** 2026-10-10
**Overall progress:** 100 % (6/6 tasks)
**Verified by:** Workspace inspection, package import check, `pip check`, pytest smoke test (1 passed), live Streamlit server health check (HTTP 200)

### A. Phase Objective

Find out what already existed, confirm the toolchain (Python, Git, pip, venv), install
dependencies, create the project skeleton, and confirm the Streamlit app starts.

### B. Tasks Completed

| Task | What was implemented | Where | How verified |
|------|----------------------|-------|--------------|
| Inspect workspace | Listed the workspace; found only an empty `.venv` (Python 3.12.3, pip only), no git repo | — | `ls -la`, `find`, `.venv/pyvenv.cfg`, `.venv/bin/pip list` |
| Verify Python / Git / dependencies | Python 3.12.3 and git 2.43.0 present; system Python lacks streamlit/pandas | — | `python3 --version`, `git --version`, import attempts |
| Set up virtual environment | Reused the existing `.venv` and installed packages into it | `.venv/` | `.venv/bin/python --version` → 3.12.3; all 6 packages import |
| Create folder structure | `src/`, `tests/` created (`scripts/` created in Phase 2) | project root | File listing |
| Create requirements | Runtime and dev requirement files with pinned versions | `requirements.txt`, `requirements-dev.txt` | `pip check` → no broken requirements |
| Confirm app starts | Skeleton dashboard with title, description, mode indicator | `app.py` | AppTest smoke test passed; live server returned HTTP 200 |

### C. Files Created

| File | Purpose |
|------|---------|
| `app.py` | Streamlit skeleton: title, description, AI/Demo Mode indicator |
| `src/__init__.py` | Marks `src` as a package |
| `src/config.py` | Loads `.env`; `get_db_path()`; `ai_configured()` (always `False` until Phase 6) |
| `requirements.txt` | Runtime dependencies: streamlit, pandas, python-dotenv, sqlglot |
| `requirements-dev.txt` | `-r requirements.txt` plus pytest, playwright |
| `.gitignore` | Excludes `.env`, secrets.toml, venvs, caches, `data/*.db`, test artefacts |
| `.env.example` | `INSIGHTSQL_DB_PATH` only; no credentials |
| `pytest.ini` | `testpaths = tests`, `pythonpath = .` |
| `tests/test_app_smoke.py` | AppTest check that the app runs and shows Demo Mode |
| `PROJECT_PLAN.md` | Phase plan, architecture decisions, phase log |
| `README.md` | Stub with quick-start and test commands |

### D. Files Modified

- `tests/test_app_smoke.py`: after the first failing run, changed to build an absolute path to `app.py` (see H).

### E. Technical Implementation

- **Dependencies:** streamlit 1.65.0, pandas 3.0.6, python-dotenv 1.2.4, sqlglot 30.22.0 (runtime); pytest 9.1.1, playwright 1.63.0 (dev). sqlglot was chosen so SQL validation uses a real parser rather than keyword matching.
- **Split requirements:** `requirements.txt` holds only what the deployed app needs (Streamlit Community Cloud installs this file).
- **`src/config.py`** was added beyond the required structure so all modules read configuration the same way.

### F. Commands Executed

| Command | Purpose | Outcome | Errors |
|---------|---------|---------|--------|
| `ls -la`, `find . -maxdepth 3 …`, `python3 --version`, `git --version`, import attempts | Inspect workspace and toolchain | Only `.venv` present; Python 3.12.3; git 2.43.0; streamlit/pandas missing from system Python | None |
| `ls .venv …; cat .venv/pyvenv.cfg; .venv/bin/pip list` | Inspect existing venv | Python 3.12.3 venv with only pip 26.2.1 | None |
| `.venv/bin/pip install streamlit pandas python-dotenv sqlglot pytest playwright` | Install dependencies | All 6 installed | DNS retry warnings while downloading the Playwright wheel; installation still completed |
| `.venv/bin/python -c "import streamlit, pandas, dotenv, sqlglot, pytest, playwright.sync_api"`; `pip check` | Confirm imports despite the warnings | All imported; "No broken requirements found." | None |
| `.venv/bin/pytest` (1st) | Run smoke test | **1 failed** | `FileNotFoundError: AppTest script not found at …/tests/app.py` |
| `.venv/bin/pytest` (2nd) | Rerun after fix | **1 passed** in 0.29s | None |
| `streamlit run app.py --server.headless true --server.port 8599` + `curl` (1st) | Confirm server starts | Not run properly | Log path pointed at a scratchpad directory that did not exist yet, so the server never launched |
| Same, after `mkdir -p` of scratchpad (2nd) | Confirm server starts | Health `ok`; `GET /` → HTTP 200 | Shell exit 144: `pkill -f` matched its own shell; follow-up check confirmed no server left running |

### G. Testing and Verification

| Test or Check | Command or Method | Result | Evidence |
|---------------|-------------------|--------|----------|
| Smoke test | `.venv/bin/pytest` | PASS (after fix) | `1 passed in 0.29s` |
| Package imports | `python -c "import …"` | PASS | Versions printed; "playwright import ok" |
| Dependency consistency | `pip check` | PASS | "No broken requirements found." |
| Live app startup | `streamlit run` + `curl` | PASS | Health `ok`, HTTP 200 |
| Rechecked 2026-10-10 for this report | Same `streamlit run` + `curl` | PASS | Health `ok`, HTTP 200 |

### H. Issues and Fixes

1. **Smoke test could not find `app.py`.** Root cause (confirmed by the error message): `AppTest.from_file` resolves relative paths against the calling test file, not the working directory. Fix: absolute path built from `__file__`. Verified: `1 passed`.
2. **First server check did not run.** Root cause: the scratchpad log directory did not exist. Fix: created it. Verified: HTTP 200 on retry.
3. **Exit code 144 after the server check.** Root cause: `pkill -f` pattern also matched the shell running the command. No project impact; a follow-up check showed no server left running.

### I. Requirements Traceability

| Requirement | Status | Evidence |
|-------------|--------|----------|
| Inspect existing workspace before modifying | Completed | Inspection commands in F |
| Python, Git, dependencies available | Completed | Python 3.12.3, git 2.43.0, `pip check` |
| Folder structure | Completed | `src/`, `tests/` created (`scripts/` in Phase 2) |
| `requirements.txt` | Completed | File present; `pip check` clean |
| Virtual environment | Completed | Existing `.venv` reused |
| App can start | Completed | Smoke test + HTTP 200 |

### J. Remaining Tasks

- Playwright Chromium browser not downloaded — deferred to Phase 7 because the network had DNS failures during install.

### K. Risks and Limitations

- Exact version pins may need updating when deploying to a platform with a different Python version.

### L. Phase Completion Decision

**PASS** — all six tasks implemented and verified (see G).

### M. Next Phase Readiness

Phase 2 could begin: environment working, no known blocking issues.

---

# Phase 2 — Database Development

**Status:** Completed
**Completion date:** 2026-10-10
**Overall progress:** 100 % (6/6 tasks)
**Verified by:** Seed script run, manual SQL checks, 21 database tests passed, deliberate-defect (mutation) check

### A. Phase Objective

Create the SQLite schema (products, sales, query_history), a reproducible sample-data
seeder, and tests proving data integrity and correct revenue values.

### B. Tasks Completed

| Task | What was implemented | Where | How verified |
|------|----------------------|-------|--------------|
| Create SQLite database | `init_db()`, `seed_sample_data()`, `ensure_database()` | `src/database.py` | `data/insightsql.db` created by seed script |
| Implement schema | Tables with PK, FK, NOT NULL, CHECK constraints; indexes on `sales(product_id)` and `sales(sale_date)` | `src/database.py` (`SCHEMA_SQL`) | `test_init_db_creates_expected_tables_and_columns` |
| Create the three tables | products, sales, query_history | `src/database.py` | Column-list assertions; read-only check (3 tables) |
| Sample-data generation | 12 products / 4 categories / 4 regions / 600 sales in 2025, seed 42, 0/5/10 % discounts | `src/sample_data.py`, `scripts/seed_database.py` | Determinism and reseed tests; seed output `12 products, 600 sales` |
| Verify relationships and integrity | FK enforced (`PRAGMA foreign_keys = ON`), quantity > 0 | `src/database.py` | FK and CHECK tests; `foreign_key_check` → `[]` |
| Test representative queries | Revenue by region and product vs. an independent Python calculation; fixed expected top-3 values; sale-level price check | `tests/test_database.py` | 21 passed |

Also implemented: query-history helpers `add_history()` / `recent_history()` (4 tests).

### C. Files Created

| File | Purpose |
|------|---------|
| `src/sample_data.py` | Deterministic sample-data generator (added beyond the required structure so tests can import it) |
| `src/database.py` | Schema, read-write and read-only (`mode=ro`) connections, seeding, query-history helpers |
| `scripts/seed_database.py` | Command-line wrapper: rebuilds the DB and prints row counts |
| `tests/conftest.py` | `seeded_db` fixture: fresh DB in a temporary folder per test |
| `tests/test_database.py` | 21 schema, seeding, revenue, read-only and history tests |
| `data/insightsql.db` | Generated database (git-ignored; recreate with the seed script) |
| `.git/` | Repository initialised with `git init -b main` (user request) |

### D. Files Modified

- `PROJECT_PLAN.md`: Phase 2 marked done; Phase 2 log added.

### E. Technical Implementation

- Revenue = `quantity * sales.unit_price` (the price stored on each sale). Discounts make this genuinely differ from the catalogue price; a test checks this.
- `seed_sample_data()` **deletes and rebuilds** the database so data is always identical.
- `ensure_database()` seeds only when the file is missing (for first deploy; the `.db` is git-ignored).
- History statuses limited to `success`, `rejected`, `error`; timestamps are UTC ISO-8601.

### F. Commands Executed

| Command | Purpose | Outcome | Errors |
|---------|---------|---------|--------|
| `git init -b main && git status --short` | Initialise repo (user request) | Repo created; `.venv/` not listed | None |
| `.venv/bin/python scripts/seed_database.py` | Create and seed DB | `Seeded …/data/insightsql.db: 12 products, 600 sales.` | None |
| Inline Python with aggregate SQL | Sanity-check data | Top: Laptop Pro 14 102900.0; regions East 78731.9 > South 74704.68 > West 68560.31 > North 61703.67; 12 months; 239 discounted sales; FK orphans `[]` | None |
| `.venv/bin/pytest -q` | Run suite | **22 passed** in 1.11s | None |
| Mutation script (1st) | Check tests detect defects | Did not run | `ModuleNotFoundError: No module named 'src'` (script was outside the project) |
| `PYTHONPATH=. … mutate.py` (2nd) | Same | **3 failed, 18 passed** (as intended) | None |
| `.venv/bin/pytest -q`; `git status --short`; `git check-ignore -v data/insightsql.db` | Final check | 22 passed; DB ignored via `.gitignore:15:data/*.db` | None |

### G. Testing and Verification

| Test or Check | Command or Method | Result | Evidence |
|---------------|-------------------|--------|----------|
| Database tests (21) | `.venv/bin/pytest -q` | PASS | `22 passed` overall (21 + smoke) |
| Seed script | `python scripts/seed_database.py` | PASS | 12 products, 600 sales |
| FK integrity | `PRAGMA foreign_key_check` | PASS | `[]` (again on 2026-10-10 for this report) |
| Mutation: FK off + no discounts | Monkeypatched run | PASS (tests failed as intended) | Failed: `test_sales_foreign_key_is_enforced`, `test_top_products_golden_values`, `test_revenue_uses_sale_level_price_not_catalogue_price` |
| DB ignored by git | `git check-ignore -v` | PASS | `.gitignore:15:data/*.db` |

### H. Issues and Fixes

1. **Mutation script failed to import `src`.** Root cause: the script was in the scratchpad, so the project root was not on `sys.path`. Fix: `PYTHONPATH=.`. Verified: script ran.

No issues were found in the application code during this phase's checks.

### I. Requirements Traceability

| Requirement | Status | Evidence |
|-------------|--------|----------|
| products / sales / query_history tables with specified columns | Completed | `test_init_db_creates_expected_tables_and_columns` |
| `sales.product_id` references `products.product_id` | Completed | `test_sales_foreign_key_is_enforced` |
| Revenue = quantity × sale-level unit_price | Completed | Revenue tests + mutation check |
| Synthetic, reproducible data | Completed | `test_generated_sales_are_deterministic`, `test_reseeding_resets_database` |
| Initialisation + seeding script | Completed | `scripts/seed_database.py` output |
| Query history storage | Completed | 4 history tests |

### J. Remaining Tasks

None for this phase. Query history is not yet written by any user flow (Phase 4/5).

### K. Risks and Limitations

- `seed_sample_data()` deletes the database file; running the seed script wipes query history (intended, documented in the script).
- Fixed expected values in tests are tied to seed 42 and must be updated deliberately if the data changes.

### L. Phase Completion Decision

**PASS** — all tasks implemented and verified by tests and the mutation check.

### M. Next Phase Readiness

Phase 3 could begin; read-only connection already available.

---

# Phase 3 — Backend and SQL Safety

**Status:** Completed
**Completion date:** 2026-10-10
**Overall progress:** 100 % (6/6 tasks)
**Verified by:** 69 new tests (91 total passed), probing of sqlglot and SQLite authorizer behaviour, mutation checks disabling each safety layer

### A. Phase Objective

Implement a query service that executes only validated, read-only SQL, with layered defences, timeouts, row limits, and user-safe error messages.

### B. Tasks Completed

| Task | What was implemented | Where | How verified |
|------|----------------------|-------|--------------|
| Query service | `run_query()` → `QueryResult(sql, data, truncated)`; `QueryError(message, status)` | `src/query_service.py` | 13 tests in `test_query_service.py` |
| SQL validation | `validate_sql()`: sqlglot syntax-tree checks, table allowlist, regenerates SQL without comments | `src/sql_guard.py` | Safe (10) and dangerous (25) parametrised cases |
| Read-only execution | `mode=ro` + `PRAGMA query_only` + `ReadOnlyAuthorizer` | `src/query_service.py`, `src/sql_guard.py` | Engine-level authorizer tests (8); data unchanged after rejected queries |
| Reject dangerous SQL / multiple statements | Root must be a SELECT query; forbidden statement types anywhere; one statement only | `src/sql_guard.py` | e.g. `SELECT 1; DROP TABLE sales` rejected |
| Invalid input and DB errors | Empty, non-string, malformed, overlong input; timeout; missing DB; unknown column | both modules | Malformed-input tests (9), timeout, missing-DB, unknown-column tests |
| Unit and integration tests | 56 guard tests + 13 service tests | `tests/` | `91 passed` |

### C. Files Created

| File | Purpose |
|------|---------|
| `src/sql_guard.py` | `validate_sql()`, `UnsafeSQLError`, `ReadOnlyAuthorizer`, table and function allowlists |
| `src/query_service.py` | `run_query()`, `QueryResult`, `QueryError`, translation of SQLite errors into safe messages |
| `tests/test_sql_guard.py` | 56 tests: safe, dangerous, malformed, comment stripping, engine-level authorizer |
| `tests/test_query_service.py` | 13 tests: values, truncation, timeout, rejection, error messages |

### D. Files Modified

- `tests/test_sql_guard.py`: authorizer tests changed to assert on `authorizer.denied_reason` instead of SQLite's error wording (see H).
- `PROJECT_PLAN.md`: Phase 3 marked done; Phase 3 log added.

### E. Technical Implementation

- **Layer 1 — parser (sqlglot):** non-empty, ≤ 5000 chars, parses, exactly one statement, root is a SELECT query, no write/schema/PRAGMA/ATTACH/Command parts, no recursive `WITH`, no table-valued functions or schema-qualified names, tables limited to `products`/`sales` (plus `WITH` names). The SQL that runs is regenerated from the parsed tree, so it is exactly what was validated.
- **Layer 2 — SQLite authorizer:** allows only SELECT, reads of `products`/`sales`, and allowlisted functions. Denies `sqlite_master`, `query_history`, `pragma_*`, `load_extension`, `zeroblob`, writes and ATTACH.
- **Layer 3 — connection limits:** read-only URI, `PRAGMA query_only = ON`, 1 MB value limit, 3 s timeout via progress handler, 1000-row cap with a truncation flag.
- **Errors:** status `rejected` (unsafe) or `error`; only a short allowlist of SQLite messages (e.g. "no such column") is shown; other details are logged, not shown.
- Probing found sqlglot parses `hello world` as an alias and `VACUUM`/`REPLACE` as a generic `Command`, so "parsed successfully" is not treated as safe.

### F. Commands Executed

| Command | Purpose | Outcome | Errors |
|---------|---------|---------|--------|
| Inline Python probing `sqlglot.parse` on 17 inputs | Learn parser behaviour | See E (`hello world` → Alias; `VACUUM`/`REPLACE` → Command; `SELEC 1` → ParseError) | None |
| Inline Python logging authorizer callbacks | Learn engine callbacks | Real table names reported, including through `WITH`; function names reported | None |
| `.venv/bin/pytest -q` (1st) | Run suite | **3 failed, 88 passed** | Authorizer tests expected `not authorized`; actual `access to pragma_table_info.cid is prohibited` |
| `.venv/bin/pytest -q` (2nd) | Rerun after test fix | **91 passed** in 2.07s | None |
| Mutation script (1st version) | Disable each layer | Output unusable | grep caught a log line instead of the summary |
| Simplified mutation script, `no-parser` | Disable parser layer | **40 failed, 29 passed** | None (expected failures) |
| Simplified mutation script, `no-authorizer` | Disable authorizer | **8 failed, 61 passed** | None (expected failures) |
| `.venv/bin/pytest -q`; `git status --short` | Final check | 91 passed in 2.12s | None |

### G. Testing and Verification

| Test or Check | Command or Method | Result | Evidence |
|---------------|-------------------|--------|----------|
| SQL guard unit tests (56) | `.venv/bin/pytest -q` | PASS | Included in `91 passed` |
| Query service integration tests (13) | `.venv/bin/pytest -q` | PASS | Included in `91 passed` |
| Timeout | `test_long_running_query_is_stopped` (3-way cross join, 0.2 s limit) | PASS | "took too long" error |
| Mutation: parser off | Monkeypatched run | PASS (tests failed as intended) | 40 failed; `DELETE` and `query_history` reads **still blocked** by the authorizer |
| Mutation: authorizer off | Monkeypatched run | PASS (tests failed as intended) | 8 failed, including `zeroblob` |
| Rechecked 2026-10-10 for this report | `.venv/bin/pytest -q` | PASS | `91 passed in 2.30s` |

### H. Issues and Fixes

1. **3 authorizer tests failed.** Root cause (confirmed from the output): the queries *were* denied, but SQLite reports denied column reads as `access to X.col is prohibited`, not `not authorized`; the test's `reason` parameter was also unused. Fix: the test now asserts that the authorizer's recorded `denied_reason` contains the expected text. No application code changed. Verified: 91 passed.
2. **First mutation run gave unusable output.** Fix: simplified the script and filtered for the pytest summary line. Verified: clear counts obtained.

### I. Requirements Traceability

| Requirement | Status | Evidence |
|-------------|--------|----------|
| Only the supported read-only subset is allowed | Completed | `test_safe_queries_are_accepted`, `test_dangerous_queries_are_rejected` |
| Reject INSERT/UPDATE/DELETE/DROP/ALTER etc. | Completed | Dangerous-query cases |
| Reject multiple statements | Completed | `SELECT 1; DROP TABLE sales` case |
| Read-only SQLite connection | Completed | `mode=ro`, `query_only`, `test_readonly_connection_rejects_writes` |
| Real parsing, not just keyword matching | Completed | sqlglot syntax tree; `SELECT 'DROP TABLE sales'` accepted as a harmless string |
| Timeouts / execution limits | Completed | `test_long_running_query_is_stopped` |
| Limit result sizes | Completed | Truncation tests |
| Safe, understandable error messages | Completed | `test_missing_database_gives_safe_message` (no path leaked), unknown-column test |
| Reject if it cannot be validated | Completed | Malformed-input tests |
| Tests for dangerous and malformed SQL | Completed | 56 guard tests |

### J. Remaining Tasks

None for this phase. Question handling and history recording belong to Phase 4.

### K. Risks and Limitations

- The timeout is checked every 1000 SQLite instructions, so it is approximate.
- The function allowlist is deliberately small; valid queries using other functions will be rejected.
- Protection depends on SQLite's authorizer and sqlglot behaving as tested with SQLite 3.45.1 and sqlglot 30.22.0.

### L. Phase Completion Decision

**PASS** — all tasks implemented and verified by 69 new tests and the mutation checks.

### M. Next Phase Readiness

Phase 4 could begin; `run_query()` is the single path for executing SQL.

---

# Phase 4 — Demo Mode

**Status:** Completed
**Completion date:** 2026-10-10
**Overall progress:** 100 % (5/5 tasks)
**Verified by:** 29 new automated tests (120 total passed), results compared with an independent Python calculation, sockets blocked during Demo Mode tests, mutation check (3 deliberate defects, all detected)

### A. Phase Objective

Provide predefined business questions with SQL that run through the same validation and
read-only execution path as AI-generated SQL, so the app works without an AI API key, and
record every attempt in query history.

### B. Tasks Completed

| Task | What was implemented | Where | How verified |
|------|----------------------|-------|--------------|
| Predefined questions and SQL | 5 questions → SQL; `lookup_sql()` ignores case, spacing, punctuation; `UnsupportedQuestionError` otherwise | `src/demo_queries.py` | `test_there_are_five_demo_questions`, matching-variant tests (3) |
| Connect questions to the query service | `answer_question(db_path, question, generate_sql, source)` → `Answer`; every SQL candidate goes through `run_query()`; history recorded | `src/query_service.py` | `test_generated_sql_cannot_bypass_validation`, `test_success_is_recorded_with_validated_sql`, `test_answer_reports_demo_source_and_validated_sql` |
| Works without an AI API key | Demo is the default SQL source; no AI code involved | `src/query_service.py`, `src/demo_queries.py` | `test_demo_mode_works_without_api_key_or_network`: API-key variables removed, sockets blocked, all 5 questions answered |
| Accuracy of returned results | — | — | 5 tests compare **every row** with an independent Python calculation from the generated sales; 5 tests confirm the regenerated SQL returns the same rows as the original SQL |
| Unsupported questions and error handling | Unsupported → `rejected` + history; empty / >500 chars → rejected, not recorded; execution errors → `error`; generator crash → generic message; history-write failure does not break the answer | `src/query_service.py` | 11 tests (unsupported, SQL typed as a question, 4 empty inputs, overlong, at-limit, execution error, generator crash, history failure) |

### C. Files Created

| File | Purpose |
|------|---------|
| `src/demo_queries.py` | Demo question → SQL mapping and lookup (written before the pause) |
| `tests/test_demo_mode.py` | 29 Demo Mode integration tests |

### D. Files Modified

- `src/query_service.py`: module docstring updated; added `MAX_QUESTION_LENGTH = 500`, the `Answer` dataclass, `answer_question()`, and `_record_history()`; added imports of `typing.Callable` and `demo_queries`. Existing `run_query()` unchanged.
- `PROJECT_PLAN.md`: Phase 4 marked done; Phase 4 log added.
- `PROJECT_PROGRESS.md`: summary, tracking table, weighting, and this section updated.

### E. Technical Implementation

- **One pipeline for both modes:** `answer_question()` takes the SQL source as a function (`generate_sql`) plus a `source` label. Demo Mode passes `demo_queries.lookup_sql`; Phase 6 will pass an AI function. Tests inject fake generators to simulate bad AI output.
- **Order of checks:** question present → ≤ 500 chars → generate SQL → `run_query()` (parser check, authorizer, read-only connection, timeout, row cap) → record history.
- **History:** stores the validated SQL on success and `NULL` on failure (spec: "validated SQL query, when available"). Writing history uses a separate read-write connection; failures are logged, not raised.
- **Design decisions (assumptions):** empty and overlong questions are not recorded, since there is nothing useful to store. Demo matching is exact apart from case, spacing and punctuation.
- No new dependencies, database changes, or configuration changes.

### F. Commands Executed

| Command | Purpose | Outcome | Errors |
|---------|---------|---------|--------|
| (first session) file write of `src/demo_queries.py` | Create demo questions | Written; work then stopped at the user's request | — |
| Inline Python: `run_query(db, lookup_sql(q))` for each question; `lookup_sql` variant and unsupported checks (during report creation, read-only) | Ad hoc check of demo SQL before the pipeline existed | 5/5 ran (5, 4, 4, 12, 5 rows); variant matched; unsupported raised | None |
| `.venv/bin/pytest -q` | Full suite after adding `answer_question()` and tests | **120 passed** in 3.31s | None |
| `PYTHONPATH=. python mutate_demo.py skip-validation` (scratchpad) | Disable parser check and authorizer | **2 failed, 27 passed** (as intended) | None |
| `… mutate_demo.py wrong-demo-sql` | Lowest-revenue query sorted the wrong way | **1 failed, 28 passed** (as intended) | None |
| `… mutate_demo.py no-history` | History never recorded | **5 failed, 24 passed** (as intended) | None |
| `.venv/bin/pytest -v` (counted per file); `.venv/bin/pytest -q`; `git status --short` | Final check | smoke 1, database 21, demo_mode 29, query_service 13, sql_guard 56; **120 passed** in 3.37s; all files untracked, no commits | None |

### G. Testing and Verification

| Test or Check | Command or Method | Result | Evidence |
|---------------|-------------------|--------|----------|
| Demo Mode tests (29) | `.venv/bin/pytest -q` | PASS | `120 passed` overall; 29 in `test_demo_mode.py` |
| Top 5 / region / category / lowest 5 | Every row vs. Python calculation | PASS | 4 tests |
| Monthly totals (previously unchecked) | All 12 months vs. Python calculation | PASS | `test_monthly_sales_totals` |
| Regenerated SQL keeps results | Original SQL vs. pipeline output for all 5 | PASS | 5 parametrised tests |
| No API key, no network | Env vars removed, `socket.connect` and `create_connection` patched to fail | PASS | `test_demo_mode_works_without_api_key_or_network` |
| Earlier tests unaffected | Full suite | PASS | 91 earlier tests still pass |
| Mutation: validation skipped | Monkeypatched | PASS (detected) | 2 failed. The `DELETE` still changed no data (read-only connection); the test failed on status `error` ≠ `rejected` |
| Mutation: wrong demo SQL | Monkeypatched | PASS (detected) | `test_lowest_revenue_products` failed |
| Mutation: no history | Monkeypatched | PASS (detected) | 5 history-related tests failed |
| Demo Mode in the dashboard | — | NOT RUN | The dashboard flow is Phase 5 scope; `app.py` is still the Phase 1 skeleton |

### H. Issues and Fixes

1. **Development paused mid-phase** at the user's request after `src/demo_queries.py` was written. A partial report was recorded; work resumed on approval. No code issue involved.

No test failures occurred in this phase; all 29 new tests passed on the first run. The mutation check was used to confirm they can fail.

### I. Requirements Traceability

| Requirement | Status | Evidence |
|-------------|--------|----------|
| Predefined questions with corresponding SQL | Completed | `src/demo_queries.py`; 5 questions tested |
| Demo SQL goes through the same validation and execution layers | Completed | `answer_question()` → `run_query()`; `test_generated_sql_cannot_bypass_validation`; mutation check |
| Works without an AI API key | Completed | `test_demo_mode_works_without_api_key_or_network` |
| At least three demo questions return correct results | Completed | All 5 checked row by row |
| Unsupported questions and error handling | Completed | 11 error-handling tests |
| Query history stores question, validated SQL, status, timestamp | Completed | History tests in `test_demo_mode.py` and `test_database.py` |
| Never pretend an AI request occurred | Completed (service level) | `Answer.source == "demo"`; the dashboard label is Phase 5 scope |

### J. Remaining Tasks

- Show Demo Mode in the dashboard (question picker, results, history) — Phase 5.
- `answer_question()` currently treats any generator exception as a generic error; Phase 6 will add specific handling for AI errors (missing key, timeout, quota).

### K. Risks and Limitations

- Demo Mode answers only the 5 questions (ignoring case, spacing and punctuation); other wording is "unsupported".
- Empty and overlong questions leave no history entry (design decision, see E).
- Rejected and failed attempts store `NULL` SQL, so the history does not show which candidate SQL was refused.
- Value comparisons use a ±0.01 tolerance to allow for floating-point summation order.

### L. Phase Completion Decision

**PASS** — all 5 tasks implemented and verified by automated tests, the independent Python calculation, the network-blocked test, and the mutation check.

### M. Next Phase Readiness

- Phase 5 can begin once the user approves.
- Prerequisites: none outstanding. `answer_question()`, `demo_questions()` and `recent_history()` provide what the dashboard needs.
- Known issues: none blocking. Playwright browsers are still not installed (needed in Phase 7).
- Recommended next action: build the Streamlit dashboard (Phase 5).

---

# Phase 5 — Dashboard and User Interface

**Status:** Completed
**Completion date:** 2026-10-10
**Overall progress:** 100 % (7/7 tasks)
**Verified by:** 48 new automated tests (167 total passed): 37 unit tests for chart choice and explanations, 11 dashboard tests that run `app.py` through Streamlit's `AppTest` and click its real widgets; live server check (HTTP 200, no errors logged); mutation check (3 deliberate defects, all detected). **Not verified:** how the page looks in a real browser — the screenshot was skipped at the user's request because Chromium could not be downloaded.

### A. Phase Objective

Build the Streamlit dashboard so a user can ask a question (typed or from examples), see
the SQL used, a results table, a suitable chart, a factual explanation, and recent query
history, with clear messages for unsupported or unsafe requests.

### B. Tasks Completed

| Task | What was implemented | Where | How verified |
|------|----------------------|-------|--------------|
| Build the Streamlit dashboard | Title, description, Demo/AI Mode indicator, wide layout; DB created on first run via `st.cache_resource` | `app.py` | `test_initial_page_shows_title_mode_and_examples`; live server HTTP 200 |
| Natural-language question input | Question form with "Ask" button; 5 example buttons that fill the box and run the question; spinner while running | `app.py` | `test_typed_question_is_answered`, `test_example_button_shows_sql_table_chart_explanation_and_history` |
| SQL preview | "SQL used" code block with the validated SQL; caption naming the SQL source (Demo Mode says "no AI request was made") | `app.py` | Example-button test checks `LIMIT 5` in the code block and the "no AI request was made" caption |
| Results table and suitable charts | `choose_chart()`: sorted horizontal bars for label + value results; line for months/dates; no chart for empty, single-row, single-value, >50-row, multi-measure, duplicate-label or non-numeric results | `src/insights.py`, `app.py` | 5 demo-result chart tests, 10 "no chart" tests, AppTest checks of the chart type in the page (bar for top products and regions, line for monthly totals, none for a single count) |
| Result explanations | `explain()`: highest/lowest, period range, ties, truncation note — only values from the result, no AI | `src/insights.py` | Exact-text tests; every figure in each demo explanation must appear in the data; no trend/causal words |
| Query history | "Recent queries" table (time, question, status, SQL), newest first, 10 rows | `app.py` | `test_history_lists_newest_first`; status `success` / `rejected` shown after the corresponding actions |
| Verify the main user workflow | Ask → answer → chart → explanation → history, plus error paths | `tests/test_app_ui.py` | 11 AppTest tests passed; live server started and stopped cleanly |

Additional (beyond the spec, stated as an assumption before implementation): an
**"Advanced: run your own read-only SQL"** box. In Demo Mode an unsafe *question* is simply
"unsupported" and never reaches the SQL safety layer, so this box is the only way to show
that layer working in the UI. Typed SQL goes through the same `answer_question()` →
`run_query()` path, labelled `source="sql"`.

### C. Files Created

| File | Purpose |
|------|---------|
| `src/insights.py` | `ChartSpec`, `choose_chart()`, `explain()`, `humanize()`, `format_value()` |
| `tests/test_insights.py` | 37 unit tests for chart choice and explanations |
| `tests/test_app_ui.py` | 11 dashboard tests using Streamlit `AppTest`, each with its own temporary database |

### D. Files Modified

- `app.py`: replaced the Phase 1 skeleton (title + mode indicator only) with the full dashboard described in B. The title, caption and mode-indicator text were kept.
- `PROJECT_PLAN.md`: Phase 5 marked done; Phase 5 log added.
- `PROJECT_PROGRESS.md`: summary, tracking table, weighting, and this section.
- **Deleted** `tests/test_app_smoke.py`: its check (app starts, title, Demo Mode label) is now `test_initial_page_shows_title_mode_and_examples`. Reason: the old test ran against the real `data/insightsql.db`; the new one uses a temporary database.

### E. Technical Implementation

- **Separation of concerns:** `app.py` only collects input and draws output. Chart choice and explanations live in `src/insights.py` (pure functions, unit-tested); SQL generation, validation, execution and history stay in `answer_question()`.
- **Chart design** (following the data-visualisation guidance loaded before writing chart code): one series per chart, so one colour and no legend; one axis; bars sorted by value and horizontal so long product names stay readable; built-in hover tooltips; the table is always shown beside the chart.
- **Request flow:** form submit or example button → `session_state.pending` → `run_request()` inside a spinner → `answer` or `error` kept in session state → rendered → history rendered last so it includes the latest entry.
- **Errors:** "Request rejected: …" (unsafe/unsupported) or "Query failed: …"; any unexpected exception is logged and shown as a generic message, never a stack trace.
- **Stable selectors for Phase 7:** containers keyed `answer`, `error`, `history`; example buttons keyed `example_0` … `example_4`; inputs keyed `question` and `custom_sql`.
- No new dependencies, database changes, or configuration changes.

### F. Commands Executed

| Command | Purpose | Outcome | Errors |
|---------|---------|---------|--------|
| Inline Python: `inspect.signature(st.bar_chart / st.line_chart)` + `AppTest.from_string` probe | Check chart options and how AppTest exposes charts | `sort` and `horizontal` supported | `IndexError`: charts appear as `vega_lite_chart`, not `arrow_vega_lite_chart` |
| Second probe with `at.get("vega_lite_chart")` | Same | 2 charts found; bar spec sorted descending by value | Line chart spec has no top-level `encoding` (layered) |
| Third probe printing the line spec | Learn the layered structure | Layers: line + hover points with tooltips | None |
| `rm tests/test_app_smoke.py && .venv/bin/pytest -q` | Full suite with new tests | **1 failed, 166 passed** | `test_explanation_figures_all_come_from_the_data[…lowest revenue?]` (see H) |
| `.venv/bin/pytest -q` | Rerun after test fix | **167 passed** in 11.57s | None |
| `timeout 300 .venv/bin/playwright install chromium` | Get a browser for a screenshot | **Not installed** — reached 30 % of 186.8 MiB before the 300 s limit | Timeout |
| `.venv/bin/playwright install chromium` (background) | Retry without a time limit | **Not installed** — stalled at 0 %; stopped at the user's request | Stalled download |
| `streamlit run app.py --server.headless true --server.port 8599` + `curl`; `kill`; log scan | Live server check | Health `ok`; `GET /` → HTTP 200; after stop → HTTP 000; "no errors in server log" | None |
| `PYTHONPATH=. python mutate_ui.py always-bar / invented-total / chart-everything` (scratchpad) | Check tests detect defects | **3 / 8 / 12 failed** respectively (as intended) | None |
| `.venv/bin/pytest -v` (counted per file); `.venv/bin/pytest -q`; `git status --short` | Final check | ui 11, database 21, demo_mode 29, insights 37, query_service 13, sql_guard 56; **167 passed** in 12.37s; all files untracked | None |

### G. Testing and Verification

| Test or Check | Command or Method | Result | Evidence |
|---------------|-------------------|--------|----------|
| Insights unit tests (37) | `.venv/bin/pytest -q` | PASS | Part of `167 passed` |
| Dashboard AppTest tests (11) | `.venv/bin/pytest -q` | PASS | Part of `167 passed` |
| Main workflow (example button) | AppTest | PASS | SQL contains `LIMIT 5`; table 5 rows, first `["Laptop Pro 14", 102900.0]`; bar chart; explanation names the top product; history row `success` |
| Typed question / monthly line chart | AppTest | PASS | Regions East, South, West, North; 12 rows with a line chart |
| Empty question | AppTest | PASS | "Please enter a question"; no SQL shown; no history entry |
| Unsupported question | AppTest | PASS | "Request rejected … Demo Mode only answers"; history status `rejected` |
| Unsafe SQL in the Advanced box | AppTest | PASS | `DROP TABLE sales` → "Request rejected … read-only SELECT"; sales still 600 rows; `query_history` read rejected |
| Single value → no chart | AppTest | PASS | "The result is sale count: 600."; no chart; "not suited to a simple chart" caption |
| Earlier tests unaffected | Full suite | PASS | All 119 earlier tests still pass (120 minus the folded smoke test) |
| Live server | `streamlit run` + `curl` | PASS | HTTP 200; no errors in log |
| Mutation: monthly drawn as bars | Monkeypatched | PASS (detected) | 3 failed |
| Mutation: explanation adds an invented total | Monkeypatched | PASS (detected) | 8 failed |
| Mutation: chart for every result | Monkeypatched | PASS (detected) | 12 failed |
| Visual check in a real browser (screenshot) | Playwright | **NOT RUN** | Chromium download failed twice; skipped at the user's request |
| Responsive layout on a narrow screen | — | **NOT RUN** | Needs a browser |

### H. Issues and Fixes

1. **AppTest probe used the wrong element name.** Root cause (confirmed): charts are exposed as `vega_lite_chart`. Fix: used that name in the probe and the tests. Verified: charts found.
2. **1 test failed: `test_explanation_figures_all_come_from_the_data[…lowest revenue?]`.** Root cause (confirmed from the output `Extra items: '12'`): the product name "Protein Bars (12)" contains a number in parentheses, which the test's pattern took for a figure. The explanation was correct. Fix: the test now removes label text before extracting figures. No application code changed. Verified: 167 passed.
3. **Chromium could not be downloaded.** First attempt hit the 300 s limit at 30 %; the retry stalled at 0 % and was stopped at the user's request. Root cause not confirmed (the network was also slow and had DNS failures in Phase 1). Impact: no screenshot; Phase 7 browser tests are blocked until Chromium is installed.

### I. Requirements Traceability

| Requirement | Status | Evidence |
|-------------|--------|----------|
| Project title and description | Completed | `test_initial_page_shows_title_mode_and_examples` |
| AI Mode / Demo Mode indicator | Completed | Same test ("Demo Mode" info box); SQL source caption per answer |
| Natural-language question input | Completed | `test_typed_question_is_answered` |
| Example question suggestions | Completed | 5 example buttons tested |
| Submit button and progress indicator | Partial | "Ask" button tested; spinner present in code but not observable in AppTest (no browser check) |
| SQL preview | Completed | Code block content tested |
| Results table | Completed | Table values tested |
| Suitable chart; no meaningless charts | Completed | Chart type tested for all 5 demo results and 10 unsuitable shapes |
| Short explanation based on actual results | Completed | Exact-text and "figures come from the data" tests |
| Query history displayed | Completed | `test_history_lists_newest_first` and status checks |
| Clear errors for unsupported or unsafe questions | Completed | Empty, unsupported, unsafe-SQL and restricted-table tests |
| Simple, responsive layout | Partial | Uses Streamlit's responsive layout; not checked in a browser |

The two Partial rows are display details, not core features. The 7 required Phase 5 tasks in
§2 are complete; these gaps are carried to Phase 7, where browser tests can check them.

### J. Remaining Tasks

- Visual and narrow-screen check in a real browser — deferred to Phase 7 (needs Chromium).
- Show the spinner in a browser test — Phase 7.
- AI Mode in the dashboard — Phase 6 (`config.ai_configured()` still always returns `False`).

### K. Risks and Limitations

- **Chromium unavailable:** Phase 7 browser tests cannot run until `playwright install chromium` succeeds (the user may need to run it on a better connection).
- AppTest runs the real script and widgets but does not render HTML/CSS, so layout problems (overlapping labels, cramped example buttons on small screens) would not be caught.
- The 5 example buttons sit in one row; on narrow screens their text will wrap.
- Charts are drawn only for one label + one number column, so some valid multi-column AI results (Phase 6) will show a table without a chart.
- History shows the 10 most recent entries only.

### L. Phase Completion Decision

**PASS** — all 7 required tasks are implemented and verified by automated tests that run the
real dashboard script and click its widgets, plus a live server check and a mutation check.
Visual rendering in a browser was not checked (skipped at the user's request); this is
recorded above and carried to Phase 7.

### M. Next Phase Readiness

- Phase 6 (AI Integration) can begin once the user approves.
- Prerequisites: choose the AI provider (the spec leaves it open) and confirm whether its SDK may be added to `requirements.txt`. The AI is optional; Demo Mode must keep working without a key.
- Known issues: Chromium not installed (affects Phase 7, not Phase 6). No git commits yet.
- Recommended next action: decide the AI provider, then implement an AI SQL generator that plugs into `answer_question(generate_sql=…, source="ai")`, with mocked tests.

---

# Phase 6 — AI Integration (local Ollama)

**Status:** Completed
**Completion date:** 2026-10-10
**Overall progress:** 100 % (6/6 tasks)
**Verified by:** 91 new automated tests (258 total passed): 43 for the Ollama client, 42 that send AI output through the shared pipeline, and 6 new dashboard tests. AI behaviour is tested against `FakeOllama`, a real HTTP server on 127.0.0.1 that stands in for Ollama. Also checked: a live server (HTTP 200, no errors logged) and a mutation check (2 deliberate defects, both detected). **Not verified:** a run with a real Ollama model, because Ollama is not installed on this machine.

> Note: the code and tests for this phase were written in an earlier session whose command
> log is not available. Everything under F and G was run again in this session.

### A. Phase Objective

Add an optional AI Mode in which a model turns a typed question into SQL. All model output
must go through the same validation and read-only execution as Demo Mode, failures must
give clear messages, and Demo Mode must keep working without AI.

### B. Tasks Completed

| Task | What was implemented | Where | How verified |
|------|----------------------|-------|--------------|
| Connect an AI provider for SQL generation | Local Ollama `/api/chat`, `stream: false`, temperature 0, JSON-schema output `{"sql": ...}`; standard-library HTTP; response capped at 1 MB | `src/ollama_service.py` | `test_returns_sql_from_structured_reply`, `test_request_uses_chat_endpoint_model_and_no_streaming`, `test_oversized_response_is_refused` |
| Prompt built from the schema | Built from the real `CREATE TABLE` statements of the allowed tables only, the guard's function allowlist, the revenue rule (`sales.unit_price`), date format, and read-only rules | `build_system_prompt()` | `test_prompt_contains_the_real_schema_for_allowed_tables_only`, `test_prompt_states_revenue_rule_and_read_only_rules` |
| All AI SQL validated before execution | The model only proposes SQL. `generate_sql` is passed to `answer_question()`, so output goes through `validate_sql()` → authorizer → read-only connection. `extract_sql()` never trims extra statements | `src/ollama_service.py`, `app.py` | 13 malicious-output cases rejected with data unchanged; prompt-injection test; 4 defence-in-depth groups with each layer, then both layers, disabled |
| Configuration without secrets | `OLLAMA_BASE_URL` (http/https only), `OLLAMA_MODEL` (default `qwen2.5:3b`), `OLLAMA_TIMEOUT_SECONDS` (default 60, invalid falls back); no API key | `src/config.py`, `.env.example` | `test_defaults_when_environment_is_unset`, `test_non_http_base_url_is_refused`, `test_invalid_timeout_falls_back_to_default`, `test_model_is_configurable` |
| Clear handling of AI failures | Connection refused (start instructions), timeout, HTTP error, missing model (`ollama pull …`), empty reply, malformed JSON, several queries; each recorded in history as `error` | `src/ollama_service.py`, `query_service.SqlGenerationError` | 11 failure tests in `test_ollama_service.py`; `test_ollama_down_gives_safe_message_and_error_history` |
| AI Mode in the dashboard; Demo Mode kept | Demo / AI Mode radio; model name and connection status (cached 15 s); answers labelled "AI-generated SQL"; example buttons ask the model in AI Mode | `app.py` | 6 AppTest tests, including malicious model output rejected in the UI and Demo Mode working while Ollama is down; `test_demo_mode_never_calls_ollama` |

### C. Files Created

| File | Purpose |
|------|---------|
| `src/ollama_service.py` | `generate_sql()`, `check_status()`, `extract_sql()`, `build_system_prompt()`, `OllamaError` |
| `tests/test_ollama_service.py` | 43 tests: request format, config, prompt, extraction, every failure path, status check |
| `tests/test_ai_mode.py` | 42 tests: AI output through the real pipeline, malicious output, defence in depth, failures, Demo Mode independence |

### D. Files Modified

- `src/config.py`: Ollama settings added; `ai_configured()` (a Phase 1 placeholder) removed.
- `src/query_service.py`: `SqlGenerationError` added. `answer_question()` shows its message and records `error` history.
- `app.py`: mode radio, AI status, `SQL_SOURCES["ai"]`, AI spinner text and source label.
- `tests/conftest.py`: `FakeOllama`, `fake_ollama` and `ollama_down` fixtures.
- `tests/test_app_ui.py`: 6 AI Mode tests.
- `.env.example`: Ollama section.
- `PROJECT_PLAN.md`, `PROJECT_PROGRESS.md`: Phase 6 recorded.

### E. Technical Implementation

- **Why Ollama:** it runs locally, needs no key or account, and keeps the data on the machine. `qwen2.5:3b` is small enough for a CPU-only laptop.
- **Safety stance:** the prompt asks for read-only SQL, but it is not treated as a security boundary. Safety comes from the Phase 3 layers, which the tests show still hold with any single layer disabled.
- **Testing without a model:** `FakeOllama` is a real HTTP server, so the production `urllib` code, timeouts and error handling run unchanged. Tests make no internet calls.

### F. Commands Executed (this session)

| Command | Purpose | Outcome | Errors |
|---------|---------|---------|--------|
| `.venv/bin/pytest -q` | Full suite | **258 passed** in 25.34s | None |
| `.venv/bin/pytest -q --co` (counted per file) | Test counts | ai_mode 42, app_ui 17, database 21, demo_mode 29, insights 37, ollama_service 43, query_service 13, sql_guard 56 | None |
| `which ollama`; `curl localhost:11434/api/tags` | Check for a real Ollama | Not installed; nothing listening | — |
| `pytest -p mut_extract …` (scratchpad plugin: `extract_sql` returns raw content) | Mutation check | **12 failed**, 90 passed (detected) | None |
| `pytest -p mut_nostatus …` (scratchpad plugin: status always "connected") | Mutation check | **5 failed**, 97 passed (detected) | None |
| `streamlit run app.py --server.headless true --server.port 8599` + `curl`; `kill` | Live server | Health `ok`; `GET /` → HTTP 200; 0 error lines in log | None |

### G. Testing and Verification

| Test or Check | Result | Evidence |
|---------------|--------|----------|
| Ollama client tests (43) | PASS | Part of 258 passed |
| AI pipeline tests (42) | PASS | Part of 258 passed |
| AI Mode dashboard tests (6) | PASS | Part of 258 passed |
| Earlier phases unaffected | PASS | All 167 earlier tests pass |
| Mutation checks (2) | PASS (detected) | 12 and 5 failures |
| Live server | PASS | HTTP 200, no errors |
| Real Ollama model answers the demo questions correctly | **NOT RUN** | Ollama not installed |

### H. Issues and Fixes

None found in this session. Issues from the earlier implementation session were not recorded.

### I. Requirements Traceability

| Requirement | Status | Evidence |
|-------------|--------|----------|
| Optional AI SQL generation | Completed | B, rows 1–2 |
| AI output always validated | Completed | Malicious-output and defence-in-depth tests |
| AI mockable in tests; no network | Completed | `FakeOllama` on 127.0.0.1 |
| Clear errors when AI is unavailable | Completed | Failure tests; UI warning test |
| Demo Mode works without AI | Completed | `test_demo_mode_works_while_ollama_is_down`, `test_demo_mode_never_calls_ollama` |
| Quality of SQL from a real model | Not verified | Needs Ollama + `qwen2.5:3b` |

### J. Remaining Tasks

- Run AI Mode against a real model (`ollama pull qwen2.5:3b`) and compare its answers to the 5 demo results. This can be done in Phase 7 or 8 once Ollama is installed.

### K. Risks and Limitations

- A small local model may write wrong but safe SQL (for example, using `products.unit_price` for revenue). The guard blocks unsafe SQL, not incorrect SQL. The SQL is always shown so users can check it.
- On CPU-only machines the first request can be slow while the model loads. The 60 s timeout is configurable.
- Streamlit Community Cloud cannot reach a local Ollama, so a deployed app runs in Demo Mode, and AI Mode shows the "could not connect" warning.

### L. Phase Completion Decision

**PASS.** All 6 tasks are implemented and verified by automated tests against a fake Ollama
server, plus mutation and live-server checks. The output quality of a real model is not
verified; this is recorded in J.

---

# Phase 7 — Automated Testing

**Status:** Completed
**Completion date:** 2026-10-10
**Overall progress:** 100 % (7/7 tasks)
**Verified by:** 14 new Playwright browser tests (272 total passed), run 3 times in full with no flaky failures. Also: a mutation check (4 planted bugs, all caught after 2 weak tests were fixed) and a review of 5 screenshots. **Not verified:** a real Ollama model; browsers other than Chrome.

### A. Phase Objective

Add browser-level end-to-end tests of the real app, cover the browser checks deferred from
Phase 5 (visual check, spinner, narrow screen), and document the AI-assisted test design
workflow with requirement traceability.

### B. Tasks Completed

| Task | What was implemented | Where | How verified |
|------|----------------------|-------|--------------|
| Get a working browser for Playwright | The download of Playwright's Chromium kept stalling; the system Google Chrome 154 is used instead (`channel="chrome"`). Tests try bundled Chromium first, then Chrome, and skip with the reason if neither starts | `tests/test_app_e2e.py` (`browser` fixture) | Launch probe; 14 tests ran in Chrome |
| Live-server test harness | Session-scoped Streamlit server on a free port with a temporary DB (re-seeded before each test) and the fake Ollama; a second server whose Ollama URL refuses connections; a new browser context (Streamlit session) per test; any browser console error fails the test | `tests/test_app_e2e.py`, `tests/conftest.py` (`running_fake_ollama()`, `unused_port()`, `FakeOllama.reset()`) | All tests start and stop servers cleanly |
| E2E main workflow | Example button → SQL, table cells, bar chart SVG, explanation, history; Enter key submits; monthly → line chart; new answer replaces old | `test_app_e2e.py` | 5 tests |
| E2E errors and safety | Empty, unsupported, `DROP TABLE` in the SQL box (DB still has 600 sales), error replaces answer; errors must be shown as red error alerts | `test_app_e2e.py` | 4 tests |
| E2E AI Mode | Spinner seen during a 1.5 s fake model delay, then AI answer; malicious model output rejected with data unchanged; mode kept per browser session; Ollama down → help text, error in history, Demo Mode still works | `test_app_e2e.py` | 4 tests |
| Layout and visual check | 375 × 812 viewport: no sideways scrolling, all example buttons visible, chart and table shown; full-page screenshots (desktop and phone) reviewed | `test_app_e2e.py`, `test-results/e2e/*.png` (git-ignored) | 1 test + screenshot review |
| AI-assisted test design workflow and traceability | Test layers, 6-step workflow (risks → cases → independent oracles → read failures → mutation check → look at screenshots), what it found, requirement → test table, what is not covered | `TESTING.md` | Reviewed against the test files |

### C. Files Created

| File | Purpose |
|------|---------|
| `tests/test_app_e2e.py` | 14 Playwright browser tests (marker `e2e`) |
| `TESTING.md` | How to run tests, test layers, AI-assisted test design workflow, traceability |

### D. Files Modified

- `tests/conftest.py`: fake Ollama start-up moved into `running_fake_ollama()` so a session-wide server can share it; `unused_port()`; `FakeOllama.reset()`. Existing fixtures behave the same.
- `pytest.ini`: `e2e` marker registered.
- `requirements-dev.txt`: Chromium install noted as optional when Chrome is present.
- `README.md`: how to skip browser tests; link to `TESTING.md`.
- `PROJECT_PLAN.md`, `PROJECT_PROGRESS.md`: Phase 7 recorded.
- No application code was changed.

### E. Technical Implementation

- **Selectors:** keyed containers render with the class `st-key-<key>` (`.st-key-answer`, `.st-key-error`, `.st-key-history`, `.st-key-example_0` …), which are stable. Table cells are read from Streamlit's accessible table behind the data grid; chart type from Vega's SVG (`g.mark-rect` = bar, `g.mark-line` = line).
- **Streamlit scrolls inside `[data-testid=stMain]`,** not the document. Both the overflow check and the screenshot helper account for this (see H).
- **Speed:** the full suite takes about 80 s; the browser tests take about 55–60 s of that. `pytest -m "not e2e"` runs the rest in about 25 s.

### F. Commands Executed

| Command | Purpose | Outcome | Errors |
|---------|---------|---------|--------|
| `ls ~/.cache/ms-playwright`; `which google-chrome …` | Find a browser | No Playwright browsers; `/usr/bin/google-chrome` present | — |
| Inline Playwright script: `chromium.launch(channel="chrome")` | Confirm Chrome works with Playwright | Chrome 154.0.8037.92; page rendered | None |
| `probe.py` (scratchpad): live server + Playwright DOM dump | Find stable selectors | `st-key-*` classes, `glide-cell-*` cells, `stVegaLiteChart` SVG | None |
| `pytest -m e2e -x -q` | First run | **14 passed** in 82.6 s | None |
| Screenshot review (desktop) | Visual check | Example buttons cut text off (see H) | Full-page screenshot stopped at the viewport height |
| `pytest -q tests/test_app_e2e.py -k "…"` | After fixing the screenshot helper | 3 passed; full-page screenshots correct | None |
| Mutation runs on a temporary copy (`always-bar`, `no-spinner`, `no-error-shown`, `wide-element`) | Do the browser tests catch bugs? | 1 / 1 / **0** / **0** failures | 2 planted bugs not caught (see H) |
| Same 2 mutations after strengthening the tests | Recheck | **6** / **1** failures (caught) | None |
| `pytest -q -m e2e` | Real app after the test changes | **14 passed** in 59.4 s | None |
| `pytest -q` | Full suite | **272 passed** in 80.7 s | None |

### G. Testing and Verification

| Test or Check | Result | Evidence |
|---------------|--------|----------|
| Browser tests (14) | PASS | Part of 272 passed; 3 full green runs |
| Earlier 258 tests | PASS | Part of 272 passed |
| Spinner visible in a browser (deferred from Phase 5) | PASS | `test_ai_mode_shows_spinner_then_ai_answer` |
| Phone-width layout (deferred from Phase 5) | PASS | Overflow test + `mobile-*.png` |
| Visual check (deferred from Phase 5) | PASS with 1 issue | 5 screenshots reviewed; example buttons cut off on desktop |
| Mutation check (4 planted bugs) | PASS after fixes | 1, 1, 6, 1 failures |
| Real Ollama model | **NOT RUN** | Ollama not installed |
| Firefox / Safari | **NOT RUN** | Only Chrome available |

### H. Issues and Fixes

1. **Playwright's Chromium unavailable.** Fix: use the installed Google Chrome. Verified: tests run.
2. **Screenshots cut short.** Root cause (confirmed): Streamlit scrolls inside `stMain`, so `full_page=True` captured only the viewport. Fix: the helper makes the viewport as tall as `stMain` before the screenshot. Verified by viewing the new screenshots.
3. **Weak test: error styling.** Turning the error alert into plain text was not caught, because the tests only checked the text inside `.st-key-error`. Fix: `error_box()` requires `stAlertContentError`. Verified: the same mutation now fails 6 tests.
4. **Weak test: overflow check could never fail.** Root cause (confirmed): the same internal scrolling; the document is never wider than the window. Fix: also compare `stMain` scroll width with its client width. Verified: a 700 px element now fails the test.
5. **Open UI issue (not fixed):** at desktop width the 5 example buttons cut their text off with "…", so the full question is not readable until clicked. Not changed in this phase because it is a UI design decision; options include showing the examples in 2–3 columns or as a list.

### I. Requirements Traceability

See the table in `TESTING.md`. Every requirement from Phases 2–6 has at least one
automated test, and the user-facing ones have a browser test.

### J. Remaining Tasks

- Decide on the cut-off example buttons (UI issue 5 in H).
- Run AI Mode against a real Ollama model (carried from Phase 6).

### K. Risks and Limitations

- The browser tests rely on Streamlit's internal DOM (`data-testid` names, the grid's accessible table). A Streamlit upgrade may need selector updates; `requirements.txt` should pin Streamlit before deployment.
- Tests share one server; the database is re-seeded before each test, so tests must not run in parallel against it.
- Only Chrome is tested.

### L. Phase Completion Decision

**PASS.** All 7 tasks are implemented and verified. The mutation check found 2 weak tests;
both were fixed and rechecked. One UI issue found by the screenshot review is recorded for a
decision.

---

# Phase 8 — Documentation and Final Verification

**Status:** Completed
**Completion date:** 2026-10-10
**Overall progress:** 100 % (9/9 tasks)
**Verified by:** full suite in the project (272 passed) and in a fresh environment built only from the files git would commit (272 passed); live server check in that environment; secrets scan; demo-script figures checked against the app's output.

### A. Phase Objective

Prove the project installs and works from scratch, finish the documentation, review what
would be committed, and prepare a demo.

### B. Tasks Completed

| Task | What was done | How verified |
|------|---------------|--------------|
| Full test run | `pytest -q` in the project | **272 passed** in 82.8 s |
| Clean-environment check | Copied only the files git would commit to a new folder; new venv; `pip install -r requirements-dev.txt`; seed script; full suite; live server | pip exit 0, `pip check` clean; seeded 12 products / 600 sales; **272 passed** in 86.1 s; HTTP 200, 0 error lines in the log |
| Dependency pins | Runtime and dev requirements already pinned to exact versions | Same versions installed cleanly in the fresh environment |
| `.gitignore` review | Ignored: `.venv/`, `data/` database, caches, `test-results/`, `.env`, `.streamlit/secrets.toml`. No `.env` exists | `git status --ignored`; committable list has 30 files, all intended |
| Secrets and leftovers scan | Searched committable files for keys, tokens, passwords, private keys, emails and home paths; and the code for `print`/`breakpoint` | Only mentions in docs and tests (for example, a test that removes API-key variables); nothing to remove |
| README | Full rewrite: purpose, quick start, AI Mode setup, usage, data, safety design, configuration, tests, structure, deployment, limitations | Commands match those run in the clean-environment check |
| Demo script | `DEMO.md`: 8-minute walkthrough with expected figures, safety demo, AI Mode and a fallback, likely questions | Figures taken from `explain()` on fresh data; the custom SQL in step 3.4 was run (4 regions returned) |
| Testing documentation | `TESTING.md` (Phase 7) linked from the README | — |
| Final progress report | This section and the summary | — |

### C. Files Created

- `DEMO.md`: demo script.

### D. Files Modified

- `README.md`: full documentation (was a stub).
- `PROJECT_PLAN.md`, `PROJECT_PROGRESS.md`: Phase 8 recorded.

### E. Technical Implementation

No code changes. The README states "tested with Python 3.12 on Linux" rather than a
minimum version, because only 3.12 was tested.

### F. Commands Executed

| Command | Purpose | Outcome | Errors |
|---------|---------|---------|--------|
| `cat requirements.txt`; `pip freeze`; `git ls-files --others --exclude-standard`; `git status --ignored` | Review pins and what would be committed | Pinned; 30 files; ignores correct | None |
| `grep` for secrets over committable files (1st) | Secrets scan | **Not run properly** | zsh passed the file list as one argument |
| Same via `xargs -0` (2nd) | Secrets scan | Only mentions in docs and tests | None |
| `cp --parents` of committable files; `python3 -m venv`; `pip install -r requirements-dev.txt`; `pip check` | Clean environment | Installed; no broken requirements | None |
| `python scripts/seed_database.py`; `pytest -q`; `streamlit run` + `curl` (fresh environment) | Clean-environment verification | Seeded; **272 passed**; HTTP 200 | None |
| `answer_question()` + `explain()` for the 5 demo questions; `run_query()` for the demo SQL | Demo-script figures | Figures recorded in `DEMO.md` | None |
| `pytest -q` | Final run | **272 passed** in 82.8 s | None |

### G. Testing and Verification

| Check | Result |
|-------|--------|
| Full suite (project) | PASS — 272 passed |
| Full suite (fresh environment) | PASS — 272 passed |
| App starts in the fresh environment | PASS — HTTP 200 |
| Secrets scan | PASS — nothing found |
| Real Ollama model | **NOT RUN** — Ollama not installed |
| Deployment to Streamlit Community Cloud | **NOT RUN** — needs your account and a pushed repository |

### H. Issues and Fixes

1. The first secrets scan did not run because of how zsh splits words; it was rerun with `xargs`. No other issues.

### I. Requirements Traceability

Final traceability is in `TESTING.md`. Every required task in Phases 1–8 is complete and
verified; the items not verified are listed in G and J.

### J. Remaining Items (need the user)

1. **Example buttons cut off at desktop width** — choose a layout (2–3 columns or a list), or accept it as is.
2. **First git commit** — nothing has been committed yet.
3. **Real-model check (optional)** — `ollama pull qwen2.5:3b`, then compare AI Mode answers with the 5 demo results.
4. **Deployment (optional)** — Streamlit Community Cloud; runs in Demo Mode only.

### K. Risks and Limitations

- Transitive dependencies are not pinned (only direct ones). A fresh install months from now may get different versions of packages such as numpy or altair.
- Browser tests depend on Streamlit's internal page structure; recheck after any Streamlit upgrade.
- Tested on Linux with Python 3.12 and Chrome only.

### L. Phase Completion Decision

**PASS.** The project installs and passes all 272 tests from a clean copy, the
documentation is complete, and nothing sensitive would be committed. The remaining items
in J need the user's decision or tools not available on this machine.

---

# Change after Phase 8 — AI Mode moved from Ollama to Hugging Face

**Date:** 2026-10-10
**Reason:** Ollama could not be installed on the project machine. The user chose the Hugging Face hosted API (Inference Providers) and asked for it to replace Ollama rather than sit alongside it.
**Verified by:** 299 tests passed (41 more than before, net of the removed Ollama tests); a mutation check (4 planted bugs, all caught). **Not verified yet:** the real model, which needs the user's `HF_TOKEN`.

### What changed

| Area | Before | After |
|------|--------|-------|
| Provider | Local Ollama, `qwen2.5:3b` | Hugging Face Inference Providers (`https://router.huggingface.co/v1`, OpenAI-compatible), default `Qwen/Qwen2.5-Coder-32B-Instruct`, chosen from the live model list as a code-focused model that answers without long reasoning text; `HF_MODEL` can be changed |
| Module | `src/ollama_service.py` (deleted) | `src/hf_service.py`: same prompt, extraction and "propose only" design; adds a Bearer token, `<think>` block stripping, and a JSON-in-fence fix |
| Settings | `OLLAMA_*` | `HF_TOKEN`, `HF_MODEL`, `HF_TIMEOUT_SECONDS` (30), `HF_BASE_URL` |
| Errors | Not running, model not pulled | Missing token (setup steps), 401 invalid token, 403 missing permission, 402 credits used up, 429 rate limit, model not offered, 5xx, timeout, no connection |
| UI | "AI Mode (Ollama)" | "AI Mode (Hugging Face)"; states that only the question and table structure are sent |
| Tests | `FakeOllama`, `test_ollama_service.py` (deleted) | `FakeHF`, `test_hf_service.py` (68 tests); AI, app and browser tests updated |
| Docs | Ollama setup | `.env.example`, README (token setup, Streamlit Cloud secrets), DEMO, TESTING |

### Token and privacy safeguards (all tested)

- The token is read only from the environment or `.env` (git-ignored); `.env.example` has an empty value.
- It is sent only over HTTPS. Plain HTTP is refused unless the server is on this machine (used by the tests), and a bad URL is refused before anything is sent.
- It never appears in user messages or logs, even if a server echoes it back (redacted).
- The app's status cache is keyed on whether a token is set, not on the token itself.
- Requests contain the question and schema only; a test checks that no sales values are sent.
- With no token, nothing is sent to the API.

### Commands and results

| Command | Outcome |
|---------|---------|
| `curl https://router.huggingface.co/v1/models` | Reachable; 125 models; Qwen2.5-Coder-32B-Instruct offered by 2 providers, Llama-3.3-70B-Instruct by 5 |
| `pytest -q tests/test_hf_service.py` (1st) | 1 failed, 67 passed: a ```` ```json ```` fenced reply was not unwrapped (fence pattern accepted only sql/sqlite). Fixed the pattern; then 68 passed |
| `pytest -q tests/test_ai_mode.py tests/test_app_ui.py` | 61 passed |
| `pytest -q -m e2e` | 14 passed |
| Mutations: no auth header / any http allowed / no redaction / sales data in prompt | 1 / 2 / 3 / 1 failures (all caught) |
| `pytest -q` | **299 passed** in 91.0 s |

### Real-model check (2026-10-10)

The user added a token to `.env` (git-ignored; confirmed loaded without printing it).
`scripts/check_ai_mode.py --repeat 2` → **every request refused with HTTP 402: "You have no
remaining credits. Purchase pre-paid credits … or subscribe to PRO"**. The token was accepted
(an invalid token gives 401), but the account has no Inference Providers credit, so **the
model never ran and its SQL quality is still unverified.** The status check (`/models`)
succeeded because listing models is free.

What the run showed, and the fixes:

| Finding | Fix | Verified |
|---------|-----|----------|
| The app's 402 message said credits were "used up for this month"; the account had none at all | Message now says the account has no credits left and links to the billing page | `test_http_errors_give_specific_messages`; real run shows the new text |
| The script sent 15 requests that all failed the same way | Stops after the first request if it never reached the model (exit code 3) | Real run: 1 request, exit 3 |
| The script labelled the harmful questions "SAFE" although the model never answered | Labelled "N/A" and counted as not tested; only model replies count as safe | Fake-server run with a declining model: still runs every question and counts them correctly |
| An early version of the stop rule would also have stopped when the model simply declined | Stop only when the request failed before the model answered | Same fake-server run |

Suite after the fixes: **299 passed**.

### Next

The real-model check needs one of:
1. Inference Providers credit on the Hugging Face account (pre-paid credits or PRO); no code change is needed. Then rerun `scripts/check_ai_mode.py --repeat 2`.
2. Running a Hugging Face model locally with `transformers` instead of the hosted API (free, but slower and less accurate; the user would need to choose this).

---

# Change after Phase 8 — Google Gemini as the AI provider

**Date:** 2026-10-10
**Status:** Implemented and verified with automated tests (416 passed) **and with live Gemini requests** (see J).

### A. Objective

Replace the failing Hugging Face integration (HTTP 402, no credits) with Google's Gemini
API, without weakening any security layer, deleting tests, or affecting Demo Mode.

### B. Baseline (before any change)

| Check | Command | Result |
|-------|---------|--------|
| Full suite | `.venv/bin/pytest -q` | **299 passed, 0 failed** in 82.7 s (matches the recorded baseline) |
| Per file | `pytest --co` | ai_mode 43, app_e2e 14, app_ui 18, database 21, demo_mode 29, hf_service 68, insights 37, query_service 13, sql_guard 56 |
| Configuration | `.env` keys (values hidden) | `HF_*` only; no `GEMINI_API_KEY` |
| SDK | `pip list` | No Google SDK installed |

### C. Decisions, verified against official documentation (fetched 2026-10-10)

| Decision | Evidence |
|----------|----------|
| SDK `google-genai` (installed **2.29.0**) | ai.google.dev/gemini-api/docs/libraries: official package `google-genai`; legacy libraries "deprecated as of November 30th, 2025" |
| Model `gemini-3.5-flash-lite` (default, configurable with `GEMINI_MODEL`) | docs/models: Stable, "Fastest, most cost-effective 3.5 model"; docs/pricing: free tier, paid $0.30 input / $2.50 output per 1M tokens (cheapest stable text model listed); docs/thinking: thinking "On (minimal)" by default |
| `client.models.generate_content`, not the newer Interactions API | docs/migrate-to-interactions: "generateContent remains fully supported" (Interactions recommended for new work). Chosen because it is stateless — Interactions stores conversation state server-side by default — and its configuration is fully typed in the SDK |
| `max_output_tokens=2048` | docs/thinking: the limit includes thought tokens, and a too-small limit can give an empty reply |
| Key passed explicitly; `GEMINI_API_KEY` only | docs/api-key: the SDK reads `GEMINI_API_KEY` or `GOOGLE_API_KEY`, and `GOOGLE_API_KEY` wins if both are set. The service never lets the SDK choose |
| Key page `https://aistudio.google.com/apikey` | docs/api-key |
| Hugging Face kept as an optional provider (`AI_PROVIDER=huggingface`) | The instructions said to replace it and also not to delete existing tests; keeping it lets all 299 earlier tests run unchanged in meaning. Gemini is the default |

### D. SDK behaviour observed (probe against a local server, before writing code)

- Request: `POST /v1beta/models/<model>:generateContent`; key in the `x-goog-api-key` header, never in the URL.
- 429 and 400 bad-key errors → `errors.ClientError` with `.code`, `.status`, `.message`.
- Non-JSON body → raw `JSONDecodeError`; blocked prompt → no exception, `text` is `None`, `prompt_feedback.block_reason` set.
- Timeout → `httpx.ReadTimeout`; refused connection → `httpx.ConnectError`. Retries are off unless configured.
- **A `genai.Client` that is not kept in a variable is garbage-collected and closes its connection mid-request** (`RuntimeError: client has been closed`). The service holds the client in a `with` block.

### E. Files

**Created**
- `src/gemini_service.py` — Gemini provider: explicit key, HTTPS-only base URL, timeout, no automatic retries, JSON reply schema, temperature 0; maps every failure to a safe `GeminiError`; key redacted from logs; status check via `models.get` (validates key and model without generating content).
- `src/ai_prompt.py` — prompt from the real schema and reply parsing, moved out of `hf_service.py` and shared by both providers (no rule changes).
- `src/ai_providers.py` — chooses the provider from `AI_PROVIDER` (default `gemini`); an invalid value is reported, not a crash.
- `tests/test_gemini_service.py` (66 tests), `tests/test_gemini_ai_mode.py` (45 tests).

**Modified**
- `src/config.py` — `AI_PROVIDER`, `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_BASE_URL`, `GEMINI_TIMEOUT_SECONDS`; shared HTTPS-URL and timeout helpers (Hugging Face behaviour unchanged).
- `src/hf_service.py` — uses the shared prompt module; adds `DISPLAY_NAME` and `model_name()`. Same behaviour; its 68 tests are unchanged and pass.
- `app.py` — AI Mode label, source label and status come from the selected provider; status cache keyed on non-secret settings only.
- `tests/conftest.py` — `FakeGemini` server and fixtures; Hugging Face fixtures now also set `AI_PROVIDER=huggingface`; **an autouse fixture removes real AI keys loaded from `.env` for every test**.
- `tests/test_app_ui.py` — `_switch_mode` re-renders before switching (see H.1); 6 Gemini tests added.
- `tests/test_app_e2e.py` — the live server now uses Gemini (the default) against `FakeGemini`; its environment is built without any real keys. Same 14 tests.
- `scripts/check_ai_mode.py` — uses the configured provider.
- `requirements.txt` (`google-genai==2.29.0`), `.env.example`, `README.md`, `DEMO.md`, `TESTING.md`.

No test was deleted. No security check was changed.

### F. Commands executed

| Command | Outcome |
|---------|---------|
| `pytest -q` (baseline) | 299 passed |
| WebFetch: docs/models, docs/pricing, docs/thinking, docs/libraries, docs/structured-output, docs/text-generation, docs/migrate-to-interactions, docs/api-key; one web search | Facts in C |
| `pip install google-genai`; `pip check` | 2.29.0; no broken requirements |
| SDK introspection + probe against a local HTTP server (1st) | **Failed**: `RuntimeError: Cannot send a request, as the client has been closed` (D, last item) |
| Same probe holding the client (2nd) | Behaviour in D |
| `pytest -q tests/test_hf_service.py tests/test_ai_mode.py` after moving the prompt code | 111 passed (refactor changed no behaviour) |
| `pytest -q -m "not e2e"` after wiring the app | **6 failed**, 279 passed (H.1) → after the fix 285 passed |
| `pytest -q tests/test_gemini_service.py` (1st) | **2 failed**, 63 passed (H.2) → after fixing the tests 65 passed |
| `pytest -q tests/test_gemini_ai_mode.py` | 45 passed; one test passed for the wrong reason (H.3) and was corrected |
| `pytest -q tests/test_app_ui.py` | 24 passed |
| `pytest -q -m e2e` | 14 passed |
| Mutation check (8 planted bugs, temporary copy) | All caught: SDK picks key 1, retries on 1, no key redaction 3, plain HTTP allowed 1, safety block ignored 2, wrong default provider 6, SQL parser skipped 14, sales data in prompt 2 failures |
| `pytest -q` (1st full run) | **1 failed**, 415 passed (H.4) |
| Same test 3 times after the fix | Passed 3/3, each stopped by the timeout at ~3.1 s |
| `pytest -q` (final) | **416 passed, 0 failed** in 69.0 s |
| `python scripts/check_ai_mode.py` (live attempt) | **No request sent**: "AI Mode needs a Gemini API key…" (exit 2); `GEMINI_API_KEY` not set |
| Fresh environment (committable files only, new venv, `pip install -r requirements-dev.txt`, `pytest -q`) | `.env` not copied; pip exit 0, `pip check` clean, google-genai 2.29.0; **416 passed** in 71.3 s |

### G. Results by requirement

| # | Requirement | Status | Evidence |
|---|-------------|--------|----------|
| 1 | Official SDK; verified cost-effective model | Done | C |
| 2 | Key and model from environment via python-dotenv | Done | `src/config.py`; `test_defaults_when_environment_is_unset`, `test_model_is_configurable` |
| 3 | `.env.example` and dependencies updated; no real key committed | Done | `.env` git-ignored and confirmed not copied in the fresh-environment check; `.env.example` has an empty key |
| 4 | Demo Mode works without key, network or Gemini | Done | `test_demo_mode_works_without_a_key_or_network`, `test_demo_mode_never_calls_gemini`, existing Demo Mode tests |
| 5 | Questions sent to Gemini with the real schema | Done | `test_request_asks_for_json_sql_deterministically` (schema in the system instruction) |
| 6 | Every statement through all security layers | Done | 20 malicious-output cases, prompt injection, each layer disabled in turn, row cap, real 3 s timeout (`test_gemini_ai_mode.py`) |
| 7 | Shared route, history, dashboard, charts, explanations preserved | Done | AppTest and browser tests through Gemini |
| 8 | Missing key, quota, network, malformed, invalid SQL handled | Done | `test_gemini_service.py` failure tests; history status `error`/`rejected` |
| 9 | Mocked tests; no real API call | Done | `FakeGemini`; autouse fixture removes real keys |
| 10 | Full suite; earlier tests preserved | Done | 416 passed (299 earlier + 117 new) |
| 11 | Progress record incl. live result | Done | This section; live request **not** made |

### H. Issues and fixes

1. **6 existing dashboard tests failed** after the label became provider-specific. Root cause (confirmed): the `app` fixture renders before the Hugging Face fixture sets `AI_PROVIDER`, so the page showed "AI Mode (Gemini)". Fix: `_switch_mode` re-renders first (one added line; no assertion changed).
2. **2 new tests failed — both test mistakes.** The prompt contains `CREATE TABLE IF NOT EXISTS products`, not `CREATE TABLE products`; and the "oversized reply" test padded with spaces, which the service correctly strips. Tests corrected; no code change.
3. **A test passed for the wrong reason.** Patching `DEFAULT_TIMEOUT_SECONDS` has no effect because `run_query` binds the default when Python loads it; the query was actually stopped by the real 3 s timeout. The ineffective patch was removed.
4. **That timeout test was then flaky** (216 million rows finished just under 3 s once). Changed to a 4-way join (~130 billion rows); passed 3/3.

### I. Remaining blockers

1. ~~No live Gemini request yet.~~ Done — see J.
2. Free-tier rate limits for `gemini-3.5-flash-lite` were not checked; the app reports 429 errors clearly.
3. Not tested: `google-genai` versions other than 2.29.0.

### J. Live Gemini check (2026-10-10)

**Setup.** The user's first attempt left `.env` without a `GEMINI_API_KEY` line (checked by
variable name and length only; no key was found in any other file). The user then pasted the
key into the chat; it was written to `.env` (git-ignored, mode 600) and confirmed loaded
without printing it. `.env.example` still has an empty key. **Because the key appeared in the
chat, it should be deleted at https://aistudio.google.com/apikey and replaced with a new one.**

**Command:** `python scripts/check_ai_mode.py --repeat 2` (output filtered to hide the key).
Model `gemini-3.5-flash-lite`; temporary database; 15 live requests plus 1 status check.

| Demo question | Result (both tries identical) | Time |
|---------------|-------------------------------|------|
| Five products with the highest revenue | **PASS**: same values, same order | 1.1 s |
| Total revenue by region | **PASS** | 1.2 s |
| Category that sold the most units | Script: FAIL (1 row, expected 4). Gemini used `LIMIT 1` and returned **Stationery, 3825**, which is exactly Demo Mode's top row (checked by running both queries) | 1.0 s |
| Monthly sales totals | **PASS** | 4.3 s, then 1.2 s |
| Products with the lowest revenue | Script: FAIL (10 rows, expected 5). The question gives no number; Gemini used `LIMIT 10`, and its **first 5 rows equal Demo Mode's 5** (checked) | 1.4 s |

**Reading:** every value Gemini returned was correct. The 2 differences are in how many rows
it chose to show, a reasonable reading of each question. The script's strict comparison
counts them as FAIL; the score is kept as reported (6/10 exact), not adjusted.

**Harmful questions (5):** Gemini declined all 5 itself (`{"sql": ""}` → "did not produce a
read-only query"); no SQL reached the guard; data unchanged. The guard's handling of malicious
SQL is covered by the automated tests with a fake server, not by this live run.

**Not checked:** free-tier rate limits over sustained use; other Gemini models.

**Possible follow-up (not done; needs a decision):** add prompt rules such as "for 'which X …
the most', list all X ranked" or "when no number is given, return 5 rows" if Demo Mode's
answer shape is preferred. This would be tuning the prompt to match the demo answers.


**Second live run (2026-10-10, user's choice: same key).** The user tried to replace the
exposed key several times, but `.env` never changed on this machine (same file timestamp,
same key; no other `.env` with a Gemini key under the home folder). The user chose to rerun
with the current key.

| Demo question | Run 1 | Run 2 (both tries identical) |
|---------------|-------|------------------------------|
| Top five products | PASS | PASS |
| Revenue by region | PASS | PASS |
| Category with most units | `LIMIT 1`, correct top row | Same (`LIMIT 1`, correct top row) |
| Monthly totals | PASS | PASS |
| Lowest-revenue products | `LIMIT 10`, first 5 correct | **PASS** (5 rows, exact) |

Score 8/10 exact (run 1: 6/10); 1.0–1.7 s per answer; harmful questions 5/5 declined, data
unchanged. **Finding:** answers can vary between runs even at temperature 0 (lowest-revenue
returned 10 rows in run 1 and 5 in run 2), which supports always validating and showing the
SQL. **Security note:** this run succeeded with the exposed key, so that key is still active;
it should be deleted at https://aistudio.google.com/apikey.
