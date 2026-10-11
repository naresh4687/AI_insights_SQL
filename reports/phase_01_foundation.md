# Phase 01 — Foundation

| Item | Value |
|------|-------|
| Phase | 01 — Foundation |
| Date | 2026-10-11 |
| Approved by | User, after Phase 00 report ("yes proceed to phase 01") |
| Baseline | 468 passed (Phase 00, `reports/phase_00_baseline.md`) |
| Result | **545 tests: 544 passed, 1 failed once (intermittent browser test, passed on 5 later runs)** — see §7 |
| Final status | **COMPLETE** — awaiting approval |

---

## 1. Scope and acceptance criteria

Behind-the-scenes groundwork only: **no UI change and no change in behaviour** for existing
features. Approved decisions used: D2/D3 (separate `app.db` and `datasets.db`), D5 (guard scope).

| # | Acceptance criterion | Met? | Evidence |
|---|----------------------|------|----------|
| AC1 | `altair` pinned (risk R7) | Yes | `requirements.txt`; `pip check` clean |
| AC2 | Config for the new storage paths and log level, documented | Yes | `src/config.py`, `.env.example`, README; P01-T40…T43 |
| AC3 | Logging with secret redaction for **all** log output | Yes | `src/core/logging_setup.py`; P01-T20…T39 |
| AC4 | Core models for datasets, tables, columns, statuses | Yes | `src/core/models.py`; P01-T01…T13 |
| AC5 | App metadata DB with versioned, atomic migrations | Yes | `src/storage/app_db.py`; P01-T56…T59 |
| AC6 | Dataset catalog; demo data registered as a built-in dataset; internal tables excluded | Yes | `src/catalog.py`; P01-T14…T19, P01-T44…T55 |
| AC7 | Guard **scope**: both layers enforce a per-request table allowlist; default unchanged | Yes | `sql_guard.py`, `query_service.py`; P01-T60…T78 |
| AC8 | Test infrastructure: isolated storage per test; logging reset per test | Yes | `tests/conftest.py`; P01-T42 |
| AC9 | All earlier tests still pass; Demo Mode and AI Analyst unchanged | Yes (1 intermittent e2e failure, §7.3) | §7, §8 |

Out of scope (later phases): any UI, importing data, writing to `datasets.db`, wiring the
catalog into the AI Analyst (Phase 03), audit events (Phase 08).

---

## 2. Test plan (written before implementation)

| Area | Planned checks |
|------|----------------|
| Guard scope | Default scope = today's two tables; explicit scope allows only its tables; demo and internal tables (`query_history`) blocked through joins, `UNION`, subqueries, CTEs; empty scope refused, never widened; case-insensitive; engine layer enforces scope even with the parser switched off |
| Models | Invalid ids and table names (uppercase, spaces, quotes, `;`, too long) refused; no tables/columns refused; duplicate tables refused |
| Catalog | Round trip; duplicates refused with nothing partially written; built-in dataset cannot be registered, replaced or removed; idempotent start-up; cascade delete; persistence; never touches the demo DB; survives reseeding |
| Migrations | Idempotent; failed migration fully rolled back; newer DB refused and left byte-identical; numbering enforced |
| Logging | Known key formats, URL passwords, `key=value` and JSON pairs, configured secret values redacted; ordinary SQL/messages unchanged; works across all loggers, in tracebacks, with bad format args; idempotent |
| Regression | Full suite (unit, integration, AppTest, browser); live server start |
| Test quality | Mutation check: plant bugs in a copy and confirm the new tests fail |

---

## 3. Files created, modified, deleted

**Created**

| File | Purpose |
|------|---------|
| `src/core/__init__.py`, `src/core/models.py` | `SourceType`, `Storage`, `QualityStatus`, `RefreshStatus`, `ColumnInfo`, `TableInfo`, `Dataset` (validated identifiers; `table_names` = query scope) |
| `src/core/logging_setup.py` | `redact()`, `configure_logging()`: log-record factory that redacts secrets from every record and traceback |
| `src/storage/__init__.py`, `src/storage/app_db.py` | `data/app.db` connection and append-only, atomic migrations (migration 1: `datasets`, `dataset_tables`) |
| `src/catalog.py` | `DatasetCatalog` (register, get, list, update_status, remove, scope, ensure_builtin); `demo_dataset()` built from the real schema |
| `tests/test_query_scope.py` (19), `tests/test_catalog.py` (33), `tests/test_logging_setup.py` (25) | 77 new tests |
| `reports/phase_01_foundation.md` | This report |

**Modified**

| File | Change |
|------|--------|
| `src/sql_guard.py` | `table_scope()`; `validate_sql(sql, allowed_tables=ALLOWED_TABLES)`; `ReadOnlyAuthorizer(allowed_tables=ALLOWED_TABLES)` |
| `src/query_service.py` | `run_query(..., allowed_tables=ALLOWED_TABLES)` passes the scope to both layers |
| `src/config.py` | `get_app_db_path()`, `get_datasets_db_path()`, `get_log_level()`; shared `_project_path()` |
| `app.py` | Calls `configure_logging()` once at start (3 lines) |
| `requirements.txt` | `altair==6.3.0` |
| `.env.example`, `README.md`, `TESTING.md` | New settings, structure, test counts, fixtures |
| `tests/conftest.py` | Autouse fixtures `_isolated_storage` and `_restore_logging` |
| `tests/test_ai_mode.py` | One test helper's stub signature (see §9, bug 1). **No assertion changed.** |

**Deleted:** none. No user data was migrated, modified or deleted; `data/` still holds only
`insightsql.db` (the catalog is not wired into the running app until Phase 03, so no
`app.db` is created yet).

---

## 4. Features implemented

1. **Query scope.** A request can be limited to an explicit set of tables. Both the parser
   layer and the engine authorizer enforce it independently. The default is exactly the
   previous allowlist (`products`, `sales`), so every existing caller behaves as before.
   An empty scope raises an error instead of falling back to a wider one.
2. **Dataset catalog** in `data/app.db`, separate from the demo database (which reseeding
   deletes, risk R2). The demo data is the built-in dataset `demo_sales`; its columns are
   read from `database.SCHEMA_SQL`, and `query_history` can never be part of a dataset.
3. **Migrations**: each applied once, in order, in its own transaction; a database from a
   newer app version is refused without modification.
4. **Secret-safe logging**: redaction is applied when each log record is created, so it
   covers every logger and handler (app, Streamlit, libraries), formatted arguments and
   exception tracebacks. `INSIGHTSQL_LOG_LEVEL` controls the app's own log level (default
   `WARNING`, as before).

---

## 5. Tests executed

Test IDs map to test functions (parametrised cases share an ID range). All were executed.

| IDs | File :: tests | Expected | Actual | Status |
|-----|---------------|----------|--------|--------|
| P01-T01–T06 | `test_catalog.py::test_invalid_dataset_ids_are_refused` (6 cases) | `ValueError` | raised | PASS |
| P01-T07–T11 | `::test_invalid_table_names_are_refused` (5) | `ValueError` | raised | PASS |
| P01-T12 | `::test_dataset_needs_name_tables_and_columns` | 4 refusals | as expected | PASS |
| P01-T13 | `::test_table_names_is_the_query_scope` | scope = table names | as expected | PASS |
| P01-T14 | `::test_demo_dataset_matches_the_real_schema` | columns, types, nullability = `PRAGMA table_info` | equal | PASS |
| P01-T15 | `::test_demo_dataset_scope_equals_the_guard_default_and_excludes_history` | `{products, sales}` | equal | PASS |
| P01-T16 | `::test_demo_scope_from_catalog_runs_demo_queries` | 600 sales | 600 | PASS |
| P01-T17 | `::test_register_get_and_list_round_trip` | identical after reload | identical | PASS |
| P01-T18 | `::test_unknown_dataset_has_no_scope` | `CatalogError` | raised | PASS |
| P01-T19 | `::test_duplicate_id_or_name_is_refused` | refused; 1 dataset stored | as expected | PASS |
| P01-T44 | `::test_builtin_dataset_cannot_be_registered_replaced_or_removed` | 3 refusals | as expected | PASS |
| P01-T45 | `::test_ensure_builtin_is_idempotent` | one entry | one | PASS |
| P01-T46 | `::test_remove_deletes_dataset_and_its_tables` | 0 table rows left | 0 | PASS |
| P01-T47 | `::test_update_status` | statuses persisted | as expected | PASS |
| P01-T48 | `::test_catalog_persists_across_instances` | found | found | PASS |
| P01-T49 | `::test_catalog_does_not_touch_the_demo_database` | demo DB byte-identical | identical | PASS |
| P01-T50 | `::test_reseeding_demo_data_leaves_the_catalog_intact` | entry kept | kept | PASS |
| P01-T56 | `::test_migrate_creates_schema_and_is_idempotent` | versions 1..n once | as expected | PASS |
| P01-T57 | `::test_failed_migration_is_rolled_back_completely` | version 1, no partial table | as expected | PASS |
| P01-T58 | `::test_newer_database_is_refused_not_modified` | refused; file byte-identical | as expected | PASS |
| P01-T59 | `::test_migrations_must_be_numbered_without_gaps` | refused | refused | PASS |
| P01-T40 | `::test_storage_paths_default_to_data_folder` | `data/app.db`, `data/datasets.db` | equal | PASS |
| P01-T41 | `::test_storage_paths_are_separate_from_the_demo_database` | 3 distinct paths | 3 | PASS |
| P01-T42 | `::test_tests_use_isolated_storage` | paths under `tmp_path` | yes | PASS |
| P01-T20–T29 | `test_logging_setup.py::test_known_secret_formats_are_redacted` (10) | secret absent, `[REDACTED]` present | as expected (after bug 2 fix) | PASS |
| P01-T30 | `::test_configured_secret_values_are_redacted` | both values gone | gone | PASS |
| P01-T31 | `::test_short_configured_values_do_not_redact_ordinary_words` | unchanged | unchanged | PASS |
| P01-T32–T35 | `::test_ordinary_messages_are_unchanged` (4) | unchanged (incl. `max_output_tokens=2048`) | unchanged | PASS |
| P01-T36 | `::test_redaction_applies_to_every_logger_and_handler` | 3 redactions, no secrets | as expected | PASS |
| P01-T37 | `::test_redaction_applies_to_tracebacks` | key absent, `RuntimeError` kept | as expected | PASS |
| P01-T38 | `::test_bad_format_arguments_do_not_lose_the_record` | record kept | kept | PASS |
| P01-T39 | `::test_configure_logging_is_idempotent_and_sets_level` | 1 handler, INFO | as expected | PASS |
| P01-T43 | `::test_log_level_setting` (4) + `::test_uninstall_restores_the_original_factory` | as named | as expected | PASS |
| P01-T60–T61 | `test_query_scope.py::test_default_scope_is_the_demo_tables`, `::test_run_query_default_scope_rejects_other_tables` | old behaviour | unchanged | PASS |
| P01-T62 | `::test_explicit_scope_allows_its_table` | sum 100.0 | 100.0 | PASS |
| P01-T63–T69 | `::test_explicit_scope_excludes_demo_and_internal_tables` (7: plain, join, `UNION` with `query_history`, CTE, subquery) | rejected | rejected | PASS |
| P01-T70 | `::test_cte_name_cannot_shadow_a_table_outside_the_scope` | reads only the CTE | as expected | PASS |
| P01-T71 | `::test_scope_is_case_insensitive` | 2 rows counted | 2 | PASS |
| P01-T72–T75 | `::test_empty_scope_is_refused_never_widened` (4) | `ValueError` in all 3 entry points | raised | PASS |
| P01-T76 | `::test_authorizer_enforces_scope_when_parser_is_disabled` | rejected by engine layer | rejected | PASS |
| P01-T77 | `::test_authorizer_scope_directly` | OK / DENY / default OK | as expected | PASS |
| P01-T78 | `::test_scope_does_not_mutate_the_default` | default unchanged | unchanged | PASS |
| P01-R01 | Full suite `pytest -q` (545 tests) | all pass | **544 passed, 1 failed** | FAIL (intermittent, §7.3) |
| P01-R02 | Re-run of the failed test, 3× alone | pass | 3/3 passed | PASS |
| P01-R03 | Browser suite `pytest -m e2e`, 2× | 24/24 | 24/24 both times | PASS |
| P01-R04 | Non-browser suite after the stub fix | all pass | 444 passed | PASS |
| P01-R05 | Mutation check (§7.2) | each planted bug caught | 6/6 caught; unmutated copy 77/77 | PASS |
| P01-R06 | `pip check` | clean | "No broken requirements found." | PASS |
| P01-R07 | Live server: health + 6 URLs | `ok`, 200 | `ok`, all 200; no errors in server log | PASS |

**Totals.** New tests written and executed: **77 (77 passed)**. Checks: 7 (6 PASS, 1 FAIL
explained in §7.3). No test BLOCKED, SKIPPED or NOT RUN. Full collected suite: **545**
(468 earlier + 77 new).

---

## 6. Commands

```bash
.venv/bin/pytest -q -m "not e2e"                                   # P01-R04
.venv/bin/pytest -q tests/test_query_scope.py tests/test_catalog.py tests/test_logging_setup.py
.venv/bin/pytest -q                                                # P01-R01
.venv/bin/pytest -q tests/test_app_e2e.py::test_empty_question_shows_error_without_history   # P01-R02 ×3
.venv/bin/pytest -q -m e2e                                         # P01-R03 ×2
bash scratchpad/mutate.sh <copy>                                   # P01-R05 (copy of the project, deleted afterwards)
.venv/bin/pip check                                                # P01-R06
.venv/bin/streamlit run app.py --server.headless true --server.port 8599 ; curl …   # P01-R07
```

---

## 7. Evidence

### 7.1 Results

| Run | Output (last line) |
|-----|--------------------|
| New tests, first run | `1 failed, 76 passed` (bug 2) → after fix `77 passed in 2.19s` |
| Non-browser, first run after the scope change | `12 failed, 432 passed, 24 deselected` (bug 1) → after fix `444 passed, 24 deselected in 89.79s` |
| Full suite | `1 failed, 544 passed in 203.07s` — `FAILED tests/test_app_e2e.py::test_empty_question_shows_error_without_history` |
| Failed test alone ×3 | `1 passed in 11.22s`, `1 passed in 10.47s`, `1 passed in 13.77s` |
| Browser suite ×2 | `24 passed, 521 deselected in 116.94s`, `24 passed, 521 deselected in 104.91s` |
| Collection | `545 tests collected` |

### 7.2 Mutation check (each bug planted in a temporary copy; the new tests run against it)

| Planted bug | Result |
|-------------|--------|
| Authorizer ignores the scope (uses the default list) | 5 failed |
| Parser ignores the scope | 4 failed |
| Empty scope silently widened to the default | 4 failed |
| Failed migration committed instead of rolled back | 1 failed |
| Tracebacks not redacted | 1 failed |
| Demo dataset includes `query_history` | 1 failed |
| No change (control) | 77 passed |

The first attempt ran no tests (`no tests ran`): zsh did not split the test-file list. It was
rerun with bash; the table shows the second run.

### 7.3 The intermittent browser failure

`test_empty_question_shows_error_without_history` failed once in the full run, then passed 5
times (3 alone, 2 in full browser runs). The failure message was **not captured** (only the
summary line was kept), so the cause is not confirmed. The test types into the chat box,
the SQL Explorer and the history page; it does not use the scope, the catalog or the new
storage, and those code paths are covered by passing AppTest tests. Most likely a browser
timing issue. Recorded as an open issue (§10).

---

## 8. Regression results

| Area | Result |
|------|--------|
| Demo Mode | `test_demo_mode.py` 29/29; Demo flows in AppTest and browser tests passed |
| AI Analyst | `test_ai_mode.py` 43/43, `test_gemini_ai_mode.py` 45/45 (incl. each safety layer switched off) |
| SQL guard | `test_sql_guard.py` 56/56 unchanged |
| All pages | AppTest 66/66; browser 24/24 (2 full runs); live server 200 on all pages |

---

## 9. Bugs found and fixed

1. **12 existing security tests failed after the scope change.** Root cause (confirmed from
   the traceback, `TypeError: <lambda>() takes 1 positional argument but 2 were given`): a
   test helper switches off the parser by replacing `validate_sql` with `lambda sql: sql`;
   `run_query` now also passes the scope. Fix: the stand-in accepts it
   (`lambda sql, *scope: sql`). Assertions unchanged; the tests still switch off the parser
   and still prove the engine layer blocks writes.
2. **Redaction missed JSON-style secrets** (`"api_key": "…"`), found by a new test. Root cause:
   the pattern did not allow a quote between the name and the colon. Fixed in
   `logging_setup.py`; the test was not changed.
3. **Prevented, not shipped:** `configure_logging()` runs inside app tests and changes global
   logging state. Left in place, redaction and the `WARNING` level could make the existing
   "key is never logged" tests pass without checking anything. `_restore_logging` resets it
   after every test.

---

## 10. Data integrity and security findings

- The demo database, `query_history` (11 rows) and `.env` were not modified. No new files
  are written to `data/` by the app in this phase.
- `query_history` is excluded from every dataset scope; both guard layers refuse it even with
  an explicit scope (P01-T63–T69, P01-T76).
- Identifier rules (`^[a-z_][a-z0-9_]{0,62}$`) mean dataset and table names never need quoting
  in SQL, which removes an injection route for imported table names in later phases.
- The catalog stores no secrets; `extra` is documented as non-secret settings only. Credential
  storage is designed in Phase 05.

## 11. Known limitations and open issues

| # | Issue |
|---|-------|
| L1 | One intermittent browser-test failure (§7.3); cause not confirmed. Will capture the error if it recurs. |
| L2 | Two small behaviour changes, both stricter or safer: the authorizer now compares table names case-insensitively (SQLite table names are case-insensitive; all real names are lower-case), and an **empty** `INSIGHTSQL_DB_PATH` now falls back to the default instead of the project folder. |
| L3 | Migration SQL is split on `;`, so a migration must not contain `;` inside a string literal (documented in the module). |
| L4 | Pattern-based redaction cannot recognise every secret format; configured secret values are always redacted. |
| L5 | `PROJECT_PROGRESS.md` is still out of date (risk R6); new reports are in `reports/`. |
| L6 | Nothing committed to git yet for this phase. |

## 12. Final status

**COMPLETE.**

## 13. Next phase proposed for approval

**Phase 02 — CSV/Excel import, validation and preprocessing.** Adds `openpyxl`, a new
"Import data" page (upload → original preview → profile → validation report →
configurable cleaning → before/after preview → transformation summary → confirm), storage
of the original file unchanged and the cleaned table in `data/datasets.db`, and registration
in the catalog. Limits (file size, rows, columns) will be configurable. Imported data will
**not** yet be queryable from the AI Analyst; that is Phase 03.
