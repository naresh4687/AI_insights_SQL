# Phase 03 — Dataset Integration

| Item | Value |
|------|-------|
| Phase | 03 — Dataset integration |
| Date | 2026-10-11 |
| Approved by | User, after the Phase 02 report ("next") |
| Baseline | 712 passed (Phase 02) |
| Result | **766 tests: 766 passed, 0 failed — two consecutive full runs** (712 earlier + 54 new) |
| Final status | **COMPLETE** — awaiting approval |

---

## 1. Scope and acceptance criteria

| # | Acceptance criterion | Met? | Evidence |
|---|----------------------|------|----------|
| AC1 | Approved imports exposed through the shared data-access layer | Yes | `src/data_access.py` (`target()`, `datasets()`); P03-I01–02 |
| AC2 | AI Analyst can answer questions about imported data via the existing authorized path | Yes | Same `answer_question → run_query` path with the dataset's scope; P03-I03, P03-I30, P03-U03 |
| AC3 | A question about one dataset cannot read other datasets, demo tables or internal tables | Yes | 21 SQL attack cases + engine-only layer + prompt injection; P03-I07–I32, P03-I37–I40 |
| AC4 | The AI prompt describes only the selected dataset and never sends data | Yes | P03-I33–I36 |
| AC5 | History records which dataset was used | Yes | P03-I04, P03-U07–U08 |
| AC6 | Demo Mode and AI Analyst behaviour for the demo data unchanged | Yes | Demo prompt byte-identical to the pre-phase snapshot; all earlier tests pass |
| AC7 | No existing user data migrated or transformed | Yes | Side table added; `query_history` not altered; P03-I42 |

---

## 2. Test plan (written before implementation)

| Area | Planned checks |
|------|----------------|
| Resolution | Demo → main DB, `{products, sales}`; import → `datasets.db`, its own table; unknown id refused |
| Answering | Correct results on an imported table; history written to the main DB with the dataset id; Demo Mode refused for imports; missing data file reported safely |
| Isolation | From one dataset: other datasets, demo tables, `query_history`, `history_datasets`, `sqlite_master/sqlite_schema`, schema-qualified, quoted, upper-case, `UNION`, subquery, CTE, join, table-valued function, `ATTACH`, writes, stacked statements; engine layer alone; each dataset reads only itself |
| AI prompt | Demo prompt unchanged; dataset prompt lists only its columns, with type facts; free-text name/description never included; Gemini request carries schema but no data; injected questions that make the model return other tables are rejected; Hugging Face uses the same prompt |
| History storage | Existing DB gains the side table without changing rows or `query_history` columns; entry and dataset written atomically |
| UI | Sidebar selector; Demo Mode explanation and disabled input; AI answer about an import; rejected cross-dataset AI SQL; columns shown; Explorer scope; history label, filter and "Ask again" switching; removed dataset fallback; dashboard stays on demo data |
| Browser | Select an imported dataset, run SQL on it, and see demo tables rejected |
| Test quality | Mutation check |

---

## 3. Files created, modified, deleted

**Created**

| File | Purpose |
|------|---------|
| `src/data_access.py` | `Target` (dataset, database file, scope), `target()`, `datasets()`, `catalog()` |
| `tests/test_dataset_integration.py` (43) | Service-level integration, isolation, prompt and history tests |
| `tests/test_dataset_ui.py` (10) | AppTest tests for the dataset selector on every page that uses it |
| `reports/phase_03_dataset_integration.md` | This report |

**Modified**

| File | Change |
|------|--------|
| `src/core/models.py` | `DEMO_DATASET_ID` constant (moved from `catalog.py`, still re-exported there) |
| `src/database.py` | `history_datasets` side table (CREATE IF NOT EXISTS); `add_history(..., dataset_id)` in one transaction; `recent_history` returns `dataset_id`; `ensure_database` adds missing tables to an existing DB |
| `src/query_service.py` | `answer_question(..., target=None)`: runs on the target's DB with its scope; refuses Demo Mode for imports; `Answer.dataset_id` (defaults to demo) |
| `src/ai_prompt.py` | `build_system_prompt(dataset=None)`; dataset prompt from catalog columns; shared rules text (demo prompt unchanged) |
| `src/gemini_service.py`, `src/hf_service.py`, `src/ai_providers.py` | Optional `dataset` argument passed to the prompt |
| `src/ui/session.py` | Selected dataset, `current_target()`, pending dataset hand-over, `Turn.dataset_name`, dataset-aware SQL source |
| `app.py` | Sidebar **Dataset** selector (falls back to the demo data if a dataset disappears) |
| `src/ui/analyst.py` | Dataset badge; dataset welcome text; column list; Demo Mode explanation and disabled input for imports |
| `src/ui/explorer.py` | Dataset badge, scope-specific description and example; "load last AI SQL" only from the same dataset |
| `src/ui/history.py` | Dataset per entry; dataset filter; "Ask again" / "Open in SQL Explorer" switch to the entry's dataset (disabled if it no longer exists) |
| `src/ui/components.py` | Answer caption names the dataset |
| `src/ui/settings.py`, `src/ui/import_data.py` | Security text; catalog via `data_access` |
| `README.md`, `TESTING.md` | Dataset selector, isolation, structure, counts |
| `tests/test_ai_mode.py` | Expected demo-DB table set now includes `history_datasets` (the check that malicious SQL cannot add or drop tables is unchanged in strength) |
| `tests/test_app_e2e.py` | `go()` waits for the chat input on the AI Analyst page (see §9.2); 1 new browser test with a helper that imports into the live server's temporary storage |

**Deleted:** none. Temporary copies made for the investigation in §9.2 were removed after the
originals were restored and checked.

---

## 4. Features implemented

- **Sidebar → Dataset**: choose the demo sales data or any imported dataset. The AI Analyst
  and SQL Explorer use it; the Dashboard keeps showing the demo data.
- **AI Analyst on imported data** (AI Mode): the model receives the dataset's tables, columns,
  types and simple facts (date formats, yes/no columns), and its SQL may read only that
  dataset. The column list is shown in the page. Each answer is labelled "Dataset: …".
- **Demo Mode with an imported dataset**: a clear explanation, no demo suggestions, and the
  input is disabled (demo SQL is never run against other data).
- **SQL Explorer** on the selected dataset, with the allowed table named in the description.
- **Query History**: dataset per entry, a dataset filter, and re-asking or reopening an entry
  with its own dataset selected.

### History storage decision (data-safety rule 10)

`query_history` holds user data. Instead of altering it, a **new side table**
`history_datasets(history_id, dataset_id)` is created with `CREATE TABLE IF NOT EXISTS`.
Existing entries are not changed or copied; entries without a side-table row are treated as
questions about the demo data, which all earlier entries were. Because no existing row or
column is modified, no backup step was needed. P03-I42 checks this on a database built with
the old schema.

---

## 5. Tests executed

| IDs | Test (file) | Expected | Result |
|-----|-------------|----------|--------|
| P03-I01–02 | targets resolve; unknown dataset refused (integration) | as named | PASS |
| P03-I03 | question on an imported table returns correct rows | `[[Acme, 27.25], [Zebra-42, 10.5]]` | PASS |
| P03-I04 | history: dataset id recorded, history only in the main DB | as named | PASS |
| P03-I05 | Demo Mode refused for an imported dataset, recorded as rejected | as named | PASS |
| P03-I06 | missing dataset file → "not available" | as named | PASS |
| P03-I07–I27 | 21 forbidden statements from the Orders dataset (other dataset, demo tables, internal tables, catalog tables, qualified/quoted/upper-case names, UNION, subquery, CTE, join, table function, ATTACH, writes, stacked) | rejected; data files unchanged; history "rejected" with dataset | PASS |
| P03-I28–I30 | parser switched off: other dataset and `sqlite_master` denied by the authorizer; demo table not even in the file | rejected / error | PASS |
| P03-I31 | demo questions cannot read imported tables (either file) | rejected | PASS |
| P03-I32 | each dataset reads only itself | as named | PASS |
| P03-I33 | demo prompt identical with/without the demo dataset | identical | PASS |
| P03-I34 | dataset prompt: only its columns and facts; no other tables, data values | as named | PASS |
| P03-I35 | dataset name/description containing instructions never reach the prompt | absent | PASS |
| P03-I36 | Gemini request: dataset system prompt, no data values | as named | PASS |
| P03-I37–I40 | model "persuaded" by an injected question returns SQL for `staff`, `query_history`, `products`, `sqlite_master` | rejected | PASS |
| P03-I41 | Hugging Face request uses the same dataset prompt; demo unchanged | as named | PASS |
| P03-I42 | old-schema DB gains the side table; existing entry unchanged; `query_history` columns unchanged | as named | PASS |
| P03-I43 | history entry and dataset written atomically | no orphan entry on failure | PASS |
| P03-U01 | selector lists Demo sales, Orders, Staff; demo selected (UI) | as named | PASS |
| P03-U02 | Demo Mode + import: explanation, disabled input, no demo suggestions, dataset badge | as named | PASS |
| P03-U03 | AI Mode + import: answer, caption, prompt, history | as named | PASS |
| P03-U04 | AI answer reading another dataset rejected | rejected | PASS |
| P03-U05 | dataset columns listed | as named | PASS |
| P03-U06 | Explorer: own table works; other dataset, demo table, history rejected | as named | PASS |
| P03-U07 | History shows dataset; "Ask again" selects it and answers | as named | PASS |
| P03-U08 | History dataset filter | as named | PASS |
| P03-U09 | removed dataset → selector falls back to demo | as named | PASS |
| P03-U10 | Dashboard shows demo data while an import is selected | 600 sales | PASS |
| P03-E01 | Chrome: select imported dataset, run SQL on it, `SELECT * FROM sales` rejected, demo data unchanged | as named | PASS |
| P03-R01 | Demo prompt and Hugging Face request byte-identical to snapshots taken before the change | identical | PASS |
| P03-R02 | Full suite, run 1 | all pass | `766 passed in 164.81s` — PASS |
| P03-R03 | Full suite, run 2 | all pass | `766 passed in 154.78s` — PASS |
| P03-R04 | Mutation check (§7.2) | caught | 11/11 caught, 1 equivalent — PASS |
| P03-R05 | `pip check`; `data/` unchanged | clean; only `insightsql.db` | PASS |

**Totals:** 54 new tests written and executed: 54 PASS. Checks P03-R01–R05: 5 PASS.
FAIL / BLOCKED / SKIPPED / NOT RUN: 0. (Test IDs I37–I40 above are the four cases of one
parametrised test; I07–I27 the 21 cases of another.)

---

## 6. Commands

```bash
.venv/bin/python -c "…build_system_prompt()…"  > test-results/phase03/prompt_before.txt  # before any change
.venv/bin/pytest -q tests/test_dataset_integration.py tests/test_dataset_ui.py
.venv/bin/pytest -q tests/test_app_e2e.py -k "selected_dataset"
.venv/bin/pytest -q tests/test_app_e2e.py -k "sidebar_navigation"     # ×3, ×6, ×8, ×8 (§9.2)
.venv/bin/pytest -q                                                   # ×2
bash test-results/mutate3.sh test-results/mutation                    # throwaway copy, deleted afterwards
```

---

## 7. Evidence

### 7.1 Runs

| Run | Last line |
|-----|-----------|
| Non-browser suite after the pipeline change | `1 failed` (expected-table set, §9.1) → `686 passed, 26 deselected` |
| Demo prompt / HF request vs snapshots | `identical: True`, `hf identical: True` |
| Integration tests | `1 failed, 42 passed` (§9.3) → `43 passed in 6.38s` |
| UI tests | `10 passed in 5.76s` |
| Browser test | selectbox text check removed (§9.4) → `1 passed, 26 deselected` |
| Full suite | `766 passed, 1 error` ×2 (§9.2) → after the fix `766 passed in 164.81s`, `766 passed in 154.78s` |

### 7.2 Mutation check (12 bugs planted one at a time; 74 tests run against each)

| Planted bug | Result |
|-------------|--------|
| Control (no change) | 74 passed |
| Scope ignored (default tables used) | 10 failed |
| Scope = every imported and demo table | 17 failed |
| Query runs on the demo DB instead of the dataset's | 10 failed |
| Demo Mode allowed on imported data | 1 failed |
| Dataset not recorded in history | 27 failed |
| Prompt always uses the demo schema | 3 failed |
| Dataset name and description put in the prompt | 1 failed |
| Prompt lists every dataset's tables | 3 failed |
| Gemini ignores the dataset | 2 failed |
| "Ask again" keeps the current dataset | 1 failed |
| Existing database not upgraded | 1 failed |
| Removed dataset not handled in the sidebar | 74 passed: **equivalent** — Streamlit itself resets a selectbox whose value is no longer an option to the first option (the demo data), so the explicit guard duplicates that. It is kept so the behaviour does not depend on Streamlit internals. |

11 of 11 non-equivalent mutations caught.

### 7.3 Visual check

`test-results/e2e/explorer-imported-dataset.png`: sidebar "Dataset: E2E Staff", Explorer
description naming the `e2e_staff` table, and "Request rejected: Table 'sales' is not
available. Allowed tables: e2e_staff."

---

## 8. Regression results

| Area | Result |
|------|--------|
| Demo Mode | `test_demo_mode.py` 29/29; prompt byte-identical; P03-U10 dashboard |
| AI Analyst (demo data) | `test_ai_mode.py` 43/43, `test_gemini_ai_mode.py` 45/45, `test_gemini_service.py`, `test_hf_service.py` all passed |
| Import (Phase 02) | 165 tests passed |
| Pages | AppTest 66 + 12 + 10; browser 27/27 in both full runs |

---

## 9. Bugs found and fixes

1. **Expected demo-database tables** (`tests/test_ai_mode.py`): the test that proves malicious
   SQL does not create or drop tables compares the table set with a constant. The new
   internal table `history_datasets` was added to that constant; the check keeps its strength.
2. **Intermittent browser console error — existed before this project phase; now fixed.**
   The navigation test failed ~1 time in 3–6 with Streamlit's chat-input audio component
   logging `Recording error: Error: Container not found` (wavesurfer). Investigation:
   - with this phase's code: 1 of 3 runs, then 1 of 6 with the *previous* `analyst.py`;
   - with the previous `analyst.py` **and** `app.py` (the code from the first commit): 3 of 8.
   So it was not caused by this phase. It happens when the test leaves the AI Analyst page
   before the chat input has mounted. Fix (test only): `go()` waits for the chat input on that
   page. After the fix: 8 of 8 clean runs alone and two clean full runs. The console-error
   check was not weakened (no message is ignored). This is probably also the unconfirmed
   intermittent failure recorded in Phase 01 (L1).
3. **Test expectation**: with the parser switched off, `SELECT * FROM products` from an
   imported dataset fails with "no such table" (status `error`), not a scope rejection, because
   the demo tables are not in the datasets file. Not a leak; the test now states the expected
   status per case.
4. **Browser test**: the selected value of a selectbox is not exposed as container text;
   the test instead checks the Explorer description, which names the selected dataset's table.
   A weak `… or …` assertion I had first written was replaced with an exact row comparison.

---

## 10. Data integrity and security findings

- Isolation is enforced three ways: (1) the parser allows only the dataset's tables;
  (2) the engine authorizer allows only reads of those tables; (3) imported data is in a
  separate file, so demo and history tables are physically absent from it. Each was tested
  on its own (P03-I07–I31) and by mutation.
- The prompt for imported data contains only identifier-safe table/column names and types.
  Free text (dataset name, description) and data values are never sent (P03-I34–I36, mutation).
  A suggestive column name can appear in the prompt, but the guard decides what runs (P03-I35, I37–I40).
- `query_history` was not altered; old entries remain intact (P03-I42).
- Demo Mode never runs demo SQL on imported data (P03-I05, P03-U02).
- `data/` was not touched by any test (checked after both full runs).

## 11. Known limitations and open issues

| # | Issue |
|---|-------|
| L1 | Questions use one dataset at a time; there are no joins across datasets (by design, for isolation). |
| L2 | Demo Mode has predefined answers only for the demo data; imported data needs AI Mode or the SQL Explorer. |
| L3 | No user accounts yet: every user of a running app can see every dataset (Phase 08). The `owner` field is reserved for this. |
| L4 | Imported datasets cannot yet be renamed or deleted from the UI (dataset management, later phase). |
| L5 | Live Gemini answers on imported data were not tested in this phase (automated tests use the fake server only; no API call was made). |
| L6 | The 404s on direct page links (Phase 02, L8) remain; Streamlit behaviour. |
| L7 | `PROJECT_PROGRESS.md` is still outdated; Phases 01–03 are not committed to git. |

## 12. Final status

**COMPLETE.**

## 13. Next phase proposed for approval

**Phase 04 — AI Analyst enhancements.** More chart types (line/area, bar/column, pie/donut,
scatter, histogram, box plot, KPI cards) chosen from the result's column types, with a manual
chart picker; factual result summaries (totals, period-over-period change, rankings,
descriptive statistics, outlier flags) computed from the actual result only; SQL explanation
and clearer error explanations; suggested follow-up questions (still validated like any
question); and controlled CSV export of results (with protection against spreadsheet formula
injection). The existing question → SQL → chart → SQL flow stays as it is.
