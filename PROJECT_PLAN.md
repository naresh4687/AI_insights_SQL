# InsightSQL — Project Plan

Status legend: ✅ done · 🔄 in progress · ⬜ not started

| Phase | Scope | Status |
|-------|-------|--------|
| 1 | Inspect workspace, set up dependencies and skeleton, confirm app starts | ✅ |
| 2 | SQLite schema, initialization, deterministic seed script, DB tests | ✅ |
| 3 | SQL safety layer, read-only execution, unit tests | ✅ |
| 4 | Demo Mode questions routed through the same safety layer | ✅ |
| 5 | Streamlit dashboard: table, charts, explanation, history | ✅ |
| 6 | Optional AI SQL generation (mockable, all output validated) | ✅ |
| 7 | Integration + Playwright E2E tests, AI-assisted test design workflow | ✅ |
| 8 | Full test run, clean-env check, README, .gitignore review, demo script | ✅ |

## Architecture decisions

- **Two requirements files.** `requirements.txt` holds runtime dependencies only (used by
  Streamlit Community Cloud). `requirements-dev.txt` adds pytest and Playwright.
- **`src/config.py`** (not in the original structure) centralises environment loading so
  the UI, services, and tests read settings the same way.
- **SQL safety is layered** (planned for Phase 3):
  1. Parse with `sqlglot` into an AST; accept exactly one `SELECT` statement (CTEs allowed),
     reject anything else, and reject if parsing fails.
  2. Allow only known tables (`products`, `sales`); block `query_history` and SQLite
     internals.
  3. Execute on a read-only connection (`file:...?mode=ro`) with `PRAGMA query_only=ON`.
  4. SQLite `set_authorizer` callback denies any non-read action at the engine level.
  5. Progress-handler timeout and a row cap on returned results.
- **Demo Mode and AI Mode share one pipeline:** question → SQL candidate → guard →
  read-only execution → result processing. Only the SQL source differs.

## Phase log

### Phase 1 — Setup
- Workspace contained only an empty `.venv` (Python 3.12.3); reused it.
- Installed: streamlit 1.65.0, pandas 3.0.6, python-dotenv 1.2.4, sqlglot 30.22.0,
  pytest 9.1.1, playwright 1.63.0.
- Playwright's Chromium binary is not yet downloaded (`playwright install chromium`, Phase 7).
- Added a Streamlit `AppTest` smoke test confirming the app script runs in Demo Mode.

### Phase 2 — Database
- `src/database.py`: schema (FK + CHECK constraints, indexes), read-write and read-only
  (`mode=ro`) connections, `seed_sample_data()` (rebuilds from scratch),
  `ensure_database()` (seeds on first run, since the `.db` file is git-ignored), and
  query-history helpers (`add_history`, `recent_history`).
- `src/sample_data.py` (not in the original structure): deterministic generator —
  12 products, 4 categories, 4 regions, 600 sales across 2025, seed 42. Sales carry a
  0/5/10% discount so `sales.unit_price` genuinely differs from the catalogue price.
  Kept in `src/` so tests can import it; `scripts/seed_database.py` is a thin CLI.
- `tests/test_database.py`: 21 tests (schema, constraints, seeding determinism, revenue vs.
  an independent Python oracle, golden values, read-only connection, history).
- Mutation check: disabling FK enforcement and removing discounts made 3 tests fail as
  intended.

### Phase 3 — SQL safety and query execution
- `src/sql_guard.py`:
  - `validate_sql()` — sqlglot AST checks: non-empty, ≤ 5000 chars, parses, exactly one
    statement, root is a `Query` (SELECT/UNION/CTE), no write/DDL/PRAGMA/ATTACH/Command
    nodes anywhere, no recursive CTEs, no table-valued functions or schema-qualified
    names, tables limited to `products`/`sales` (+ CTE names). Returns SQL regenerated
    from the AST without comments, so what runs is what was validated.
  - `ReadOnlyAuthorizer` — SQLite `set_authorizer` callback: allows only `SELECT`, reads
    of `products`/`sales`, and an allowlist of functions; denies everything else
    (e.g. `sqlite_master`, `query_history`, `pragma_*`, `load_extension`, `zeroblob`).
- `src/query_service.py`: `run_query()` — validate → `mode=ro` connection →
  `PRAGMA query_only` → value-length limit → authorizer → progress-handler timeout (3 s)
  → fetch at most `max_rows + 1` (1000 default) to flag truncation → DataFrame.
  Errors become `QueryError(message, status)` with status `rejected` (unsafe) or `error`;
  only a short allowlist of SQLite messages (e.g. "no such column") is shown verbatim.
- Probing showed sqlglot parses non-SQL like `hello world` (as an alias) and falls back to
  a generic `Command` for `VACUUM`/`REPLACE`, which is why validation requires the root
  to be a `Query` rather than just "parsed successfully".
- Tests: `tests/test_sql_guard.py`, `tests/test_query_service.py`. Suite: 91 passed.
- Mutation check: disabling the parser layer → 40 failures, but the authorizer still
  blocked `DELETE` and `query_history` reads end-to-end; disabling the authorizer →
  8 failures (engine-level tests incl. `zeroblob`, which the parser layer allows).

### Phase 4 — Demo Mode
- `src/demo_queries.py`: 5 predefined questions → SQL; `lookup_sql()` ignores case,
  spacing, and punctuation; `UnsupportedQuestionError` for anything else.
- `src/query_service.py`: `answer_question(db_path, question, generate_sql, source)` —
  the shared pipeline for Demo and AI Mode. Rejects empty / >500-char questions (not
  recorded), sends every SQL candidate through `run_query()`, records history
  (validated SQL on success, `NULL` otherwise), and never lets a history-write failure
  break an answer. Returns `Answer(question, sql, data, truncated, source)`.
- `tests/test_demo_mode.py`: 29 tests; expected values come from an independent Python
  oracle over the generated rows; sockets are blocked to prove Demo Mode makes no
  network calls. Suite: 120 passed.

### Phase 5 — Dashboard
- `src/insights.py`: `choose_chart()` — bar (sorted, horizontal) for label + one numeric
  column, line when labels are periods (`YYYY-MM[-DD]`), none for empty / single-row /
  >50-row / multi-measure / duplicate-label / non-numeric results. `explain()` —
  deterministic summary using only values in the result (highest, lowest, period range,
  ties, truncation); no AI, no trend or causal claims.
- `app.py`: question form, 5 example buttons, "Advanced: run your own read-only SQL"
  expander (added beyond the spec so the safety layer is visible in Demo Mode), spinner,
  SQL source label, explanation, SQL preview, chart + table, errors ("Request rejected" /
  "Query failed"), and the 10 most recent history entries. Keyed containers (`answer`,
  `error`, `history`) give Playwright stable selectors. The DB is created on first run.
- Tests: `tests/test_insights.py` (37), `tests/test_app_ui.py` (11, Streamlit AppTest).
  `tests/test_app_smoke.py` was folded into `test_app_ui.py` so no test touches the real DB.

### Phase 6 — AI Mode (local Ollama)
- Provider: a local Ollama server (no API key, no data leaves the machine). Settings in
  `src/config.py`: `OLLAMA_BASE_URL` (http/https only), `OLLAMA_MODEL` (default
  `qwen2.5:3b`), `OLLAMA_TIMEOUT_SECONDS` (default 60). `ai_configured()` was removed.
- `src/ollama_service.py`: `generate_sql()` calls `/api/chat` with temperature 0 and a JSON
  schema (`{"sql": ...}`); the system prompt is built from the real schema of the allowed
  tables and the guard's function allowlist. `extract_sql()` accepts JSON, a code fence,
  or SQL after prose, but never trims extra statements, so the guard still sees them.
  `check_status()` checks `/api/tags` for the model. Standard-library HTTP only; responses
  capped at 1 MB. `OllamaError` (a `SqlGenerationError`) carries a user-safe message.
- The model only proposes SQL: it goes through the same `answer_question()` →
  `run_query()` path as Demo Mode. The prompt is not treated as a security boundary.
- `app.py`: Demo / AI Mode radio; AI Mode shows the model name and a cached (15 s)
  connection status; answers are labelled "AI-generated SQL".
- Tests use `FakeOllama` (`tests/conftest.py`), a real HTTP server on 127.0.0.1, so the
  production HTTP code runs without Ollama. `test_ai_mode.py` sends malicious model output
  through the pipeline with each safety layer disabled in turn. Suite: 258 passed.
- Not done: no real Ollama model was run (Ollama is not installed on this machine).

### Phase 7 — Automated testing
- `tests/test_app_e2e.py`: 14 Playwright tests (marker `e2e`) against a live Streamlit
  server with a temporary DB and the fake Ollama. Uses bundled Chromium if present,
  otherwise system Chrome; skips with the reason if neither starts.
- Covers the main flow, errors (must be red alerts), AI Mode with spinner, malicious model
  output, Ollama down, per-session mode, and a 375 px layout with screenshots.
- `TESTING.md`: run commands, test layers, AI-assisted test design workflow, traceability.
- Mutation check: 4 planted bugs; 2 were missed at first (error styling, overflow inside
  `stMain`), and the tests were fixed. Suite: 272 passed.
- Open: example buttons cut off their text at desktop width.

### Phase 8 — Documentation and final verification
- Clean-environment check: committable files only, new venv, `pip install -r
  requirements-dev.txt`, seed, full suite (272 passed), live server (HTTP 200).
- `.gitignore` and secrets scan: nothing sensitive would be committed.
- `README.md` rewritten in full; `DEMO.md` demo script with verified figures.
- Open (user): example-button layout, first git commit, real-model check, deployment.

### Change — AI Mode on Hugging Face (replaces Ollama)
- Ollama could not be installed; the user chose the Hugging Face hosted API.
- `src/hf_service.py` replaces `src/ollama_service.py`; `HF_TOKEN` / `HF_MODEL` /
  `HF_TIMEOUT_SECONDS` / `HF_BASE_URL` replace the `OLLAMA_*` settings.
- Token: environment/.env only, HTTPS only, never logged or shown; only the question and
  schema are sent. Suite: 299 passed. Real-model check pending the user's token.

