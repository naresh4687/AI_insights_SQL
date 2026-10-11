# Phase 06 — Refresh and Synchronisation

| Item | Value |
|------|-------|
| Phase | 06 — Refresh and synchronisation |
| Date | 2026-10-11 |
| Approved by | User, after the Phase 05 report ("next") |
| Baseline | 1,018 tests (Phase 05) |
| Result | **1,070 tests collected. Full run: 1,067 passed, 0 failed**; the 3 tests added afterwards from the mutation check were run on their own: 3 passed |
| Final status | **COMPLETE** — awaiting approval |

---

## 1. Scope and acceptance criteria (prompt §5.G)

| # | Requirement | Met? | Evidence |
|---|-------------|------|----------|
| AC1 | Manual refresh | Yes | Datasets page → **Refresh now**; `sync.refresh`; P06-A01–A03, P06-U02, P06-E01 |
| AC2 | Scheduled refresh | Yes | Schedule per dataset; `scripts/refresh_worker.py` (cron/systemd); P06-A20–A24 |
| AC3 | Incremental sync where reliable identifiers / change tracking exist | Yes, **database tables only** | Unique key + growing cursor column; P06-D01–D03 |
| AC4 | Streaming / CDC only where genuinely supported | **Not implemented** | No source here supports it; polling is described as polling (page, README, worker) |
| AC5 | Refresh status, timestamps, job logs | Yes | Catalog status/last refresh; `refresh_runs` log; history table |
| AC6 | Retries with sensible limits | Yes | Temporary failures only; 3 attempts; growing wait; P06-A13–A15 |
| AC7 | Failure handling and consistency safeguards | Yes | Atomic swap / single-transaction upsert; locks; checks before writing; P06-A04–A12, P06-D07–D10 |
| AC8 | Never overwrite the last valid dataset with incomplete or failed results | Yes | Every failure path tested and the data compared before/after |
| AC9 | Duplicate prevention, repeated runs, partial failures | Yes | P06-A03, P06-D02, P06-A10 (failure mid-swap) |

---

## 2. How a refresh works

1. Take the dataset's **lock** (one refresh at a time; a crashed run's lock expires after 30 min). Log the run.
2. Fetch again with the stored source (connection, table/columns or endpoint).
3. Run the same **quality checks** and the **cleaning options approved at import**.
4. Check the result has **the same columns and types**; if the source structure changed, stop.
5. Write:
   - **full**: build `<table>__refresh`, then drop the old table and rename, in **one transaction**;
   - **incremental**: delete the fetched keys and insert the fetched rows in **one transaction**,
     then check the key is still unique (else roll back).
6. Update the catalog (rows, quality, refresh status, time) and the run log; keep the fetched data
   as `uploads/<id>/latest.*` (the original import file is never changed).
7. Temporary failures (timeouts, unreachable, rate limits, HTTP 5xx) are retried; anything else fails
   at once. Every failure leaves the data exactly as it was and is recorded with a reason.

**Incremental refresh** fetches rows whose cursor is **≥** the last value seen (so rows sharing the
last value are not missed) and replaces them by key. Rows fetched again unchanged are not counted as
changed. Rows deleted at the source are not detected (stated on the page; use full refresh). It is
allowed only when the cleaning rules work row by row (no duplicate or outlier removal, no
average/median/most-common fills), because those would give different results on a partial batch.

---

## 3. Files created, modified, deleted

**Created**

| File | Purpose |
|------|---------|
| `src/sync/__init__.py`, `src/sync/state.py`, `src/sync/refresh.py` | Settings, run log, locks; the refresh routine |
| `scripts/refresh_worker.py` | Runs due scheduled refreshes (`--once` / `--loop`) |
| `src/ui/datasets.py`, `views/datasets.py` | Datasets page |
| `tests/test_refresh.py` (25), `tests/test_refresh_databases.py` (20, Docker), `tests/test_datasets_ui.py` (6) | New tests |
| `reports/phase_06_refresh.md` | This report |

**Modified**

| File | Change |
|------|--------|
| `src/storage/app_db.py` | Migration 3: `refresh_settings`, `refresh_runs`, `refresh_locks` |
| `src/ingest/store.py` | Shared transaction helper; `swap_table`, `upsert_rows`, `row_count`; `raw_headers` stored with imports |
| `src/catalog.py` | `replace()` to update an existing dataset's metadata |
| `src/connectors/databases.py` | Incremental fetch (`since`), typed cursor values, time-zone flag per column |
| `src/connectors/profiles.py`, `databases.py`, `rest.py` | `ConnectorError.retryable` for temporary failures |
| `src/config.py`, `.env.example` | `INSIGHTSQL_REFRESH_MAX_ATTEMPTS`, `INSIGHTSQL_REFRESH_RETRY_SECONDS` |
| `app.py`, `src/ui/session.py` | Data → Datasets page |
| `README.md`, `TESTING.md` | Datasets page, scheduled refreshes, structure, counts |
| `tests/servers.py` | Fake API data changeable per test |
| `tests/test_app_e2e.py` | Datasets heading; 1 new browser test |

**Deleted:** none. Migration 3 only adds tables.

---

## 4. Tests executed

| IDs | Tests | Result |
|-----|-------|--------|
| P06-A01–A03 | full refresh replaces data and metadata (original kept, latest saved); questions see refreshed data; 3 refreshes → no duplicates | PASS |
| P06-A04–A06 | bad new data (API returns nothing; field removed; type changed) → failed, data byte-identical, status FAILED, run logged | PASS |
| P06-A07–A09 | cleaning rules re-applied; new source fields reported; deleted connection explained | PASS |
| P06-A10 | failure **inside** the swap transaction → old table intact, no staging table left | PASS |
| P06-A11–A12 | file datasets cannot be refreshed; API datasets full only | PASS |
| P06-A13–A15 | temporary failures retried with waits 5 s, 10 s; permanent failures not retried; retries stop at the limit | PASS |
| P06-A16–A19 | lock prevents a second refresh; crashed lock expires; unexpected error closes the run and releases the lock; invalid settings (3) | PASS |
| P06-A20–A24 | schedule due/not due; disabled with a leftover time never due; worker runs due refreshes, reschedules from now, exit codes 0/1 | PASS |
| P06-D01–D03 | (PostgreSQL and MySQL) incremental: 1 new + 1 changed applied, cursor stored; 3 runs → no duplicates, unchanged rows not counted; id as cursor | PASS |
| P06-D04 | full refresh removes rows deleted at the source | PASS |
| P06-D05–D07 | incremental needs a unique key, row-by-row cleaning, a growing cursor type | PASS |
| P06-D08–D10 | too many new rows, source schema change, emptied source → failed, data kept | PASS |
| P06-U01–U06 | page list and sources; Refresh now result and history; failure message and data kept; schedule saved and shown; API full only; file datasets explained | PASS |
| P06-E01 | Chrome: Datasets → choose dataset → Refresh now → "Replaced with 3 rows", checked on disk | PASS (2/2) |
| P06-F01 | full suite | `1067 passed in 304.93s` — PASS |

**Totals:** 52 new tests (25 + 20 + 6 + 1 browser): all PASS. 58 of the 1,070 tests use Docker.
FAIL / BLOCKED / SKIPPED / NOT RUN: 0. Containers left after runs: 0. `data/` unchanged.

---

## 5. Commands

```bash
.venv/bin/pytest -q tests/test_refresh.py tests/test_datasets_ui.py
.venv/bin/pytest -q tests/test_refresh_databases.py            # Docker
.venv/bin/pytest -q tests/test_app_e2e.py -k refresh_now        # ×2
.venv/bin/pytest -q                                            # full suite
bash test-results/mutate6.sh test-results/mutation             # throwaway copy, deleted
```

---

## 6. Evidence

### 6.1 Runs

| Run | Result |
|-----|--------|
| `test_refresh.py` | `1 failed, 23 passed` (unclear message for an empty API, §8.1) → `24 passed` → `25 passed` |
| `test_refresh_databases.py` | `2 failed, 16 passed` (misleading "changed" count, §8.2) → `18 passed` → `20 passed` |
| `test_datasets_ui.py` | `1 failed, 5 passed` (stale list after saving, §8.3) → `6 passed` |
| Browser | `1 passed` ×2 |
| Full suite | `1067 passed in 304.93s` |

### 6.2 Mutation check (21 bugs planted one at a time)

| Planted bug | Result |
|-------------|--------|
| Swap not atomic (old table dropped first) | 11 failed |
| Schema change not checked | 1 failed |
| Empty API response replaces the data | 1 failed |
| Cleaning rules not re-applied | 1 failed |
| No retries / permanent errors retried / backoff not growing | 2 / 1 / 1 failed |
| Lock ignored / stale lock never expires / lock not released | 1 / 1 / 2 failed |
| Next run computed from the old time (pile-up) | 1 failed |
| Disabled schedule still due | first not caught (equivalent: disabling clears the time) → test with a leftover time added → 1 failed |
| Failure recorded as OK | 3 failed |
| Incremental ignores the cursor / cursor not saved | 2 / 4 failed |
| Upsert keeps old rows (no delete) | 6 failed |
| Key uniqueness not checked | 2 failed |
| Non-row-by-row cleaning allowed for incremental | 2 failed |
| Unchanged rows counted as changed | 4 failed |
| Quality errors ignored | 30 passed: **equivalent** for today's sources — the only quality error a snapshot can have is "no rows", which the cleaning step also refuses; the check is kept as a second layer |

20 of 20 non-equivalent mutations caught.

---

## 7. Regression results

All 1,018 earlier tests pass in the full run. The import save path was refactored to a shared
transaction helper; its 25 storage tests, 12 page tests and the Phase 02 mutation-relevant tests pass.

## 8. Bugs found and fixes

1. **Empty API response gave a misleading message** ("Fields are missing: id, amount, …"); now
   "The API returned no records, so there is nothing to replace the data with."
2. **Incremental counts were misleading**: rows fetched again at the cursor boundary were counted as
   "changed". The upsert now compares old and new values and counts only real changes.
3. **The Datasets list showed the old schedule after saving** (drawn before the save in the same
   run); the page now redraws after saving.
4. Code clean-ups made during the work: a name clash (`profile`) in the refresh routine was resolved
   by renaming, not worked around; an unnecessary `scripts/__init__.py` was removed after checking the
   worker tests pass without it.

## 9. Data integrity and security findings

- No failure path changes data: checks run before any write; writes are single transactions; a
  failure injected inside the swap transaction left the table intact (P06-A10).
- One refresh per dataset at a time (lock), so the UI and the worker cannot interleave writes.
- Refreshes use the cleaning options the user confirmed at import, including destructive ones; the
  number of rows they removed is reported in the run message.
- The worker needs `INSIGHTSQL_SECRET_KEY`; secrets are decrypted only for the request.
- Scheduled runs are rescheduled from the time they finish, so downtime does not cause a burst of runs.

## 10. Known limitations and open issues

| # | Issue |
|---|-------|
| L1 | No streaming / change data capture (no supported source here); scheduling is polling. |
| L2 | Incremental refresh: database tables only; does not detect deletions; needs a unique key and a growing cursor. |
| L3 | The worker must be scheduled by the operator (cron/systemd); deployment set-up is Phase 09. |
| L4 | Structure changes at the source stop the refresh; adopting a new structure means importing a new dataset. |
| L5 | File-imported datasets are not refreshable (re-import instead). |
| L6 | Only the latest fetched snapshot is kept besides the original import (no history of snapshots). |
| L7 | Earlier items remain (no user accounts until Phase 08; `PROJECT_PROGRESS.md` outdated; Phases 01–06 not committed). |

## 11. Final status

**COMPLETE.**

## 12. Next phase proposed for approval

**Phase 07 — Dashboard Studio.** Create, rename, duplicate and delete dashboards; add charts from
AI Analyst answers (the validated SQL, dataset and chart type are saved, never the AI call);
arrange widgets (order and width controls; Streamlit has no native drag-and-resize grid — decision
from Phase 00, your answer to the drag-and-drop question is still open); date, category and number
filters applied to compatible charts through the same validated, dataset-scoped query path;
refresh dashboard data; export (CSV of each chart's data, and a JSON definition of the dashboard).
