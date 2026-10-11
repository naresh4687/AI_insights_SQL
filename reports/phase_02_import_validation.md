# Phase 02 — CSV/Excel Import, Validation and Preprocessing

| Item | Value |
|------|-------|
| Phase | 02 — CSV/Excel import, validation and preprocessing |
| Date | 2026-10-11 |
| Approved by | User, after the Phase 01 report ("next") |
| Baseline | 545 tests collected after Phase 01 |
| Result | **712 tests: 712 passed, 0 failed** (545 earlier + 167 new) |
| Final status | **COMPLETE** — awaiting approval |

---

## 1. Scope and acceptance criteria

| # | Acceptance criterion | Met? | Evidence |
|---|----------------------|------|----------|
| AC1 | Upload CSV (.csv, .txt) and Excel (.xlsx, .xlsm) | Yes | `readers.py`; P02-R*, P02-UI03, P02-E01 |
| AC2 | Original-data preview, exactly as in the file | Yes | UI step 2; P02-UI02 |
| AC3 | Structural and data-quality profiling | Yes | `profiling.py`; P02-PV* |
| AC4 | Validation results: errors, warnings, passed checks | Yes | `validation.py`; 17 problem types in P02-PV |
| AC5 | Configurable preprocessing (all items in prompt §5.C) | Yes | `preprocess.py`; P02-PP* |
| AC6 | Cleaned-data preview | Yes | UI step 5; P02-UI02, P02-UI06 |
| AC7 | Transformation summary with affected rows, columns, values | Yes | UI step 6; `Step` records; P02-PP row-accounting tests |
| AC8 | Explicit confirmation (and for destructive changes, a separate confirmation) | Yes | P02-S08, P02-UI05, P02-E01 |
| AC9 | Safe storage and dataset registration | Yes | `store.py`; P02-S* |
| AC10 | Availability in the AI Analyst | **Deferred to Phase 03 (as planned)** | Phase 01 plan; imported tables are deliberately **not** reachable yet (P02-S21) |
| AC11 | Error handling for every listed problem file | Yes | §5 table "Problem inputs" |
| AC12 | Demo data and internal tables untouched; earlier tests pass | Yes | P02-S20, P02-E01, full suite |

### Rules from the prompt (§5.C) and how they are enforced

| Rule | How |
|------|-----|
| Never silently discard records or columns | Only completely empty rows are removed by default, and that is listed as a step. Rows with extra values are a **blocking error** (never truncated). Blank lines skipped are reported. Row-accounting test: rows in file − rows removed by steps = rows saved, for 5 option sets (P02-PP07–11). |
| Flag outliers, do not delete by default | Default `outliers="flag"`; removal is a separate, destructive choice (P02-PP32). |
| Before/after previews | Steps 2 and 5. |
| Confirm destructive transformations | Steps that remove rows/columns or replace values are `destructive`; Save stays disabled until the confirmation box is ticked; `save_import` also refuses without it (UI and service both enforce it). |
| Preserve the original upload unchanged | Stored byte-for-byte, checked by byte comparison (P02-S01, P02-S03, P02-E01). |
| Report affected row and column counts | Each `Step` has `rows`, `columns`, `cells`; shown in step 6 and stored in the catalog. |
| Keep imports apart from demo data and internal tables | Separate `data/datasets.db`; reserved ids; demo DB byte-identical after import (P02-S18). |
| Reproducible processing | Options serialise to JSON (`to_dict`/`from_dict`) and are stored with the dataset; same input + options → identical output (P02-PP03). |

---

## 2. Test plan (written before the tests)

| Area | Planned checks |
|------|----------------|
| Reading | Exact text; delimiters (auto + 4); BOM; UTF-16; non-UTF-8 reported (not guessed); explicit encodings; empty, binary, broken quotes; header-only; ragged rows with line numbers; duplicate/empty headers; no-header option; row, column and size limits; unsupported types incl. `.xls`; Excel cell conversion, sheets, row limit, damaged files, zip bomb, XML entity attack |
| Detection/profiling/validation | Each type; ambiguous day/month; mostly-numeric and invalid dates stay text; conversion failure counts; outlier rules; profile counts; raw table unchanged; one test per validation problem |
| Cleaning | Defaults; raw unchanged; reproducibility; row accounting; each option; destructive flags; name normalisation and validation; required columns; invalid fills; invalid options |
| Storage | Table + original + catalog; STRICT types; Excel; id collisions and reserved names; hostile file names; confirmation; blocking errors; all-or-nothing on 3 failure points; leftover folders; demo DB untouched; scope isolation; 100,000-row import |
| UI (AppTest) | Each step shown; errors; encoding option; blocking errors hide Save; confirmation then save; column options; markers; invalid names; duplicate dataset names; Excel sheet switch; Demo Mode still works |
| Browser | Full import in Chrome; phone width without horizontal scroll |
| Quality of tests | Mutation check (§7.2) |

---

## 3. Files created, modified, deleted

**Created**

| File | Purpose |
|------|---------|
| `src/ingest/__init__.py` | Package and flow description |
| `src/ingest/readers.py` | CSV/Excel → text table; encodings, delimiters, limits, zip-bomb check, defusedxml requirement |
| `src/ingest/types.py` | Type detection (all values must match) and strict conversion with failure counts |
| `src/ingest/profiling.py` | Column and dataset profile; missing markers; Tukey outliers |
| `src/ingest/validation.py` | Errors / warnings / passed checks |
| `src/ingest/preprocess.py` | `CleanOptions`, `ColumnOptions`, `clean()`, `Step` records, name normalisation |
| `src/ingest/store.py` | All-or-nothing save: original file, STRICT table, catalog entry |
| `src/ui/import_data.py`, `views/import_data.py` | Import Data page (7 steps + dataset list) |
| `tests/test_ingest_readers.py` (33), `tests/test_ingest_profile.py` (44), `tests/test_ingest_preprocess.py` (51), `tests/test_ingest_store.py` (25), `tests/test_import_ui.py` (12) | 165 new tests |
| `reports/phase_02_import_validation.md` | This report |

**Modified**

| File | Change |
|------|--------|
| `app.py` | "Data → Import Data" navigation entry |
| `src/ui/session.py` | Page path for the new page |
| `src/config.py` | `get_uploads_dir()`, import limits (`INSIGHTSQL_IMPORT_MAX_MB/ROWS/COLUMNS`) |
| `requirements.txt` | `openpyxl==3.1.5`, `defusedxml==0.7.1` |
| `.streamlit/config.toml` | `[server] maxUploadSize = 25` |
| `.gitignore` | `data/uploads/` |
| `.env.example`, `README.md`, `TESTING.md` | New page, settings, structure, limitations |
| `tests/conftest.py` | Uploads folder also isolated per test |
| `tests/test_app_e2e.py` | Live server uses temporary app/datasets/uploads paths; `Import Data` heading; 2 new browser tests; `import sqlite3`. No existing test or assertion changed. |

**Deleted:** none from the project. A stray `data/app.db` (containing only the built-in demo
catalog entry) created by a manual AppTest check that I ran without temporary paths was
removed afterwards; see §9, item 8.

---

## 4. Features implemented

**Import Data page** (sidebar → Data → Import Data), in seven steps:

1. **Choose a file**, with read options: encoding (automatic UTF-8/UTF-16 or explicit
   Windows-1252, Latin-1…), delimiter (automatic or chosen), header row on/off.
2. **Original data**: first 100 rows exactly as in the file; worksheet selector for Excel.
3. **Data quality**: error/warning/passed counts, every problem in plain language, passed
   checks, and a column profile (detected type, empty, distinct, min/max/mean, outliers, examples).
4. **Cleaning options**: trim spaces, remove empty rows/columns, remove duplicates, outliers
   (flag or remove), text to treat as empty (only markers found in the file are offered);
   per column: keep, rename, type, date format, text case, empty-value handling (keep,
   remove rows, fill with value/average/median/most common), required.
5. **Cleaned data** preview and the final column types.
6. **Summary of changes**: each step with counts, marked "Safe change" or "Removes or replaces data".
7. **Save**: dataset name and description; confirmation when needed.

**Storage**: original in `data/uploads/<id>/original.<ext>`; cleaned table as a STRICT SQLite
table in `data/datasets.db`; catalog entry with source file, size, SHA-256, read and cleaning
options, column types, change steps and validation counts.

---

## 5. Tests executed

All tests below were executed. IDs map to test functions; parametrised cases share a range.

### Reading (`test_ingest_readers.py`, 33)

| IDs | Tests | Result |
|-----|-------|--------|
| P02-R01 | values kept exactly as text | PASS |
| P02-R02–05 | delimiters: auto `;`, semicolon, tab, pipe | PASS |
| P02-R06–07 | UTF-8 BOM removed; UTF-16 detected | PASS |
| P02-R08–10 | invalid UTF-8 reported with advice; explicit cp1252 reads; wrong explicit encoding is an error | PASS |
| P02-R11–14 | empty, whitespace-only, binary (NUL), unclosed quote | PASS |
| P02-R15–18 | header-only = 0 rows; ragged rows by file line; duplicate/empty headers kept by position; no-header option | PASS |
| P02-R19–21 | row limit, column limit, size limit | PASS |
| P02-R22–25 | `.xls`, `.json`, no extension, `.exe` refused | PASS |
| P02-R26–28 | Excel cell text (dates, datetimes, numbers, booleans, empty, trailing column); sheet choice; row limit | PASS |
| P02-R29 | damaged / fake workbooks | PASS |
| P02-R30 | zip bomb (25 MB expanding, ~25 KB file) refused before parsing | PASS |
| P02-R31 | control: rebuilt workbook without attack reads | PASS |
| P02-R32–33 | XML entity declaration in workbook part and worksheet part refused; cause checked to be defusedxml `EntitiesForbidden` | PASS |

### Detection, profiling, validation (`test_ingest_profile.py`, 44)

| IDs | Tests | Result |
|-----|-------|--------|
| P02-PV01–11 | detection: integer, float, >64-bit, boolean, ISO date, day-first date, datetime, text, leading zeros, 0/1, empty | PASS |
| P02-PV12–14 | ambiguous day/month reported; month-first detected; mostly-numeric and invalid dates stay text with examples | PASS |
| P02-PV15–20 | conversion failure counts (integer, float, boolean, date, overflow, exact big integer) | PASS |
| P02-PV21 | outliers: Tukey fences, minimum 8 values, no spread | PASS |
| P02-PV22–23 | profile counts; raw table unchanged | PASS |
| P02-PV24 | clean file: no warnings, 5 passed checks | PASS |
| P02-PV25–41 | each problem reported at the right level: no rows, long rows (error); short rows, blank lines, duplicate header, empty header, duplicate rows, empty rows, empty column, missing values, missing marker, mixed types, invalid dates, ambiguous dates, leading zeros, whitespace, outliers (warning) | PASS |
| P02-PV42–44 | errors first and blocking; duplicate column names labelled uniquely; long rows list file lines | PASS |

### Cleaning (`test_ingest_preprocess.py`, 51)

| IDs | Tests | Result |
|-----|-------|--------|
| P02-PP01–04 | defaults (typed, only empty rows removed, no destructive steps); raw unchanged; reproducible; options round-trip | PASS |
| P02-PP05–11 | row accounting for 5 option sets; every row removal except empty rows is destructive | PASS |
| P02-PP12–20 | trim; markers; duplicates; remove/rename columns; empty columns | PASS |
| P02-PP21–30 | name normalisation (10 cases incl. reserved words, digits, accents, Tamil, length, `rowid`) | PASS |
| P02-PP31–39 | duplicate headers numbered; invalid user names (5); automatic names give way to user names; user name clash | PASS |
| P02-PP40–44 | text case; explicit conversion reports failures; date format choice and ISO output; invalid dates need explicit conversion; datetime format must match type | PASS |
| P02-PP45–51 | fills (value, mean, median, mode); integer mean rounded; invalid fills block (3); date fill in any format; outliers flagged vs removed; required columns; nothing left = error; invalid options raise | PASS |

### Storage (`test_ingest_store.py`, 25)

| IDs | Tests | Result |
|-----|-------|--------|
| P02-S01–03 | table + byte-identical original + catalog metadata; STRICT and NOT NULL enforced by SQLite; Excel recorded as Excel | PASS |
| P02-S04–08 | id collisions (incl. demo table name `sales`); reserved names (4); hostile file name `../../etc/passwd.csv` never used as a path | PASS |
| P02-S09–15 | confirmation required; validation errors (2) and cleaning errors block; invalid names (3); duplicate name | PASS |
| P02-S16–19 | catalog failure, unexpected error, and mid-insert failure leave nothing behind; leftover folders never overwritten | PASS |
| P02-S20–22 | demo DB byte-identical; imported table **not** reachable with the default query scope; readable only with its own scope, not another dataset's | PASS |
| P02-S23 | 100,000 rows × 4 columns imported (≈1 s, limit asserted < 60 s) | PASS |

### Import page (`test_import_ui.py`, 12) and browser (`test_app_e2e.py`, +2)

| IDs | Tests | Result |
|-----|-------|--------|
| P02-UI01–12 | empty start; all 7 steps; unreadable file; encoding option; blocking error hides Save; confirm then save (uploader reset, list updated); column options persist across column switches; markers change type; invalid name blocks; duplicate dataset name; Excel sheet switch; Demo Mode answers after an import | PASS |
| P02-E01 | Chrome: upload → warnings → remove duplicates → Save disabled → confirm → saved → listed; stored rows, original bytes and demo data checked on disk | PASS |
| P02-E02 | Chrome at 375 px: no horizontal scroll, no console errors | PASS |

### Problem inputs required by the prompt

| Problem | Handled as | Test |
|---------|-----------|------|
| Empty file | error "The file is empty." | P02-R11–12 |
| Malformed file | unclosed quote → error with line; damaged xlsx → error | P02-R14, R29 |
| Invalid encoding | error with advice; never guessed | P02-R08, R10 |
| Duplicate headers | warning; numbered names | P02-PV29, PP31 |
| Missing values | warning per column; fill/drop/keep | P02-PV34, PP45–48 |
| Duplicate rows | warning; optional destructive removal | P02-PV31, PP14 |
| Empty columns | warning; optional removal | P02-PV33, PP20 |
| Inconsistent types | warning; stays text unless converted (failures counted) | P02-PV36, PP41 |
| Invalid dates | warning with examples; explicit conversion only | P02-PV37, PP43 |
| Large inputs | limits (size, rows, columns, zip expansion); 100k rows in ≈1 s | P02-R19–21, R30, S23 |

### Totals

| Status | Count |
|--------|------:|
| New tests written and executed | 167 (165 + 2 browser) |
| PASS | 167 |
| FAIL / BLOCKED / SKIPPED / NOT RUN | 0 |
| Full suite (`pytest -q`) | **712 passed** in 128.65 s |

---

## 6. Commands

```bash
.venv/bin/pip install openpyxl==3.1.5 defusedxml==0.7.1 ; .venv/bin/pip check
.venv/bin/pytest -q tests/test_ingest_readers.py tests/test_ingest_profile.py \
    tests/test_ingest_preprocess.py tests/test_ingest_store.py tests/test_import_ui.py
.venv/bin/pytest -q tests/test_app_e2e.py -k import
.venv/bin/pytest -q                               # full suite
bash test-results/mutate2.sh test-results/mutation   # mutation check on a throwaway copy (deleted)
```

---

## 7. Evidence

### 7.1 Runs

| Run | Last line |
|-----|-----------|
| Readers | `33 passed in 0.51s` (after fixing the attack test, §9.3) |
| Profile/validation | `44 passed in 0.49s` |
| Cleaning | first `…failed…` (test mistakes, §9.4) → `51 passed in 1.07s` |
| Storage | first `4 failed, 21 passed` → `1 failed, 24 passed` (real bug, §9.2) → `25 passed in 2.72s` |
| Import page | first `7 failed, 5 passed` (lookup method) → `1 failed, 11 passed` (message, §9.6) → `56 passed` (with profile tests) |
| Browser import | `2 passed, 24 deselected in 10.31s` |
| Full suite | `712 passed in 128.65s (0:02:08)`; `712 tests collected` |
| `pip check` | `No broken requirements found.` |

### 7.2 Mutation check (bugs planted one at a time in a throwaway copy; the 165 import tests run against each)

| Planted bug | Result |
|-------------|--------|
| Control (no change) | 165 passed |
| Leading-zero codes become numbers | 3 failed |
| A column gets a type when only 80 % of values match | 2 failed |
| Rows with extra values not reported | 5 failed |
| Markers always treated as empty | 1 failed |
| Duplicate removal not marked destructive | 1 failed |
| Conversion failures hidden | 2 failed |
| Save without the confirmation check | 1 failed |
| No rollback after a catalog failure | 1 failed |
| Table created outside the transaction | 22 failed |
| User's file name used as the storage path | 4 failed (first attempt was a no-op mutation and was redone) |
| Zip-bomb check removed | 1 failed |
| Unreadable encoding silently decoded as Latin-1 | 2 failed |
| Demo table names not reserved | 2 failed |

13 of 13 real mutations were caught.

### 7.3 Visual check

Screenshots from the browser tests were reviewed: `test-results/e2e/import-saved.png`
(desktop, after saving) and `test-results/e2e/import-375.png` (phone width, all seven steps).
The phone screenshot showed "1 rows"; captions were changed to use correct singular/plural.

---

## 8. Regression results

| Area | Result |
|------|--------|
| Demo Mode | `test_demo_mode.py` 29/29; P02-UI12 (Demo question answered after an import) |
| AI Analyst | `test_ai_mode.py` 43/43, `test_gemini_ai_mode.py` 45/45 |
| SQL guard, scope, catalog | 56 + 19 + 33, all passed |
| Existing pages | AppTest 66/66; browser 24/24 earlier tests, plus 2 new |
| Earlier intermittent failure (Phase 01, L1) | Did not recur in the browser runs of this phase |

---

## 9. Bugs found and fixed

1. **Leftover storage folder blocked saving** (found by P02-S19). If an upload folder with
   the dataset's id already existed (e.g. after a crash), saving failed with "Storage for this
   dataset already exists". Fix: ids already used by folders are skipped, and the existing
   folder is left untouched. The test was also strengthened (it had an "or" that made it weak).
2. **A failed import could leave an empty table** (found by P02-S18). Root cause, confirmed:
   in Python's default sqlite3 mode `CREATE TABLE` is not part of the transaction, so an
   insert failure rolled back only the rows. Fix: explicit `BEGIN IMMEDIATE … COMMIT/ROLLBACK`.
3. **The XML-attack test was not testing anything at first.** It inserted the attack after
   an XML declaration that openpyxl does not write, so nothing was planted. It failed rather
   than passed, the cause was found, and the test now asserts the attack is planted, checks
   that the refusal comes from defusedxml (`EntitiesForbidden`), and has a control case.
4. **Test mistakes in the cleaning tests**: single-column samples with empty values (which a
   CSV cannot distinguish from blank lines), a wrong row count and index, too few values for
   outlier detection. Corrected in the tests; no code change. The single-column case is listed
   as a limitation.
5. **When the user explicitly chose the date type**, the format was not found if fewer than 80 %
   of values were valid dates. Fix: `best_format` is used for explicit conversions.
6. **Duplicate-header message used the lower-cased name**; it now shows the header as written.
7. **Validation message mixed an f-string with `.format`** (would have shown "0_2"); fixed
   before any test run.
8. **Process issue:** while inspecting AppTest internals I ran the app once without temporary
   paths, which created `data/app.db` with only the built-in demo entry (no imports, uploads or
   datasets). I removed it. Automated tests never touch `data/` (`_isolated_storage` fixture,
   and the browser server now gets temporary paths).
9. **Browser test details**: the dataset list is drawn on a canvas, so its text is read through
   the grid's accessible table; opening `/import` directly produces two harmless 404s from
   Streamlit (it probes `/import/_stcore/…` first; this happens on every page, not only this one),
   so the phone test navigates through the sidebar.

---

## 10. Data integrity and security findings

- Demo database byte-identical after imports (P02-S20, P02-E01 checks 600 sales).
- Imported tables live only in `datasets.db`; the default query scope and other datasets'
  scopes cannot read them (P02-S21–22). The AI Analyst does not see them yet.
- Original uploads are stored under a fixed name; user file names are metadata only
  (path traversal test P02-S08 and mutation check).
- Excel: zip-bomb size check before parsing; defusedxml required and verified; formulas are not
  evaluated (cached values only).
- STRICT tables: SQLite rejects values of the wrong type even if the cleaning code had a bug.
- No secrets involved in this phase; uploaded files are git-ignored (`data/uploads/`).

## 11. Known limitations and open issues

| # | Issue |
|---|-------|
| L1 | Imported datasets cannot be asked about in the AI Analyst yet (Phase 03). |
| L2 | No delete or rename of imported datasets in the UI yet (dataset management is later). |
| L3 | `.xls` is not supported; one worksheet per import; formulas give their last saved values. |
| L4 | In a one-column CSV, an empty value looks like a blank line and is skipped (reported as a warning). |
| L5 | Non-ASCII headers (e.g. Tamil) become `column_N`; users can rename them, but only to ASCII names. |
| L6 | The whole file is read into memory; limits default to 25 MB / 200,000 rows / 200 columns. |
| L7 | Numbers with thousands separators (`1,234`) or decimal commas stay text (reported as text); they can be converted only if they match the standard format. |
| L8 | Direct links to any page (e.g. `/import`) make Streamlit log two harmless 404s in the browser console. |
| L9 | `PROJECT_PROGRESS.md` is still outdated; phase reports are in `reports/`. |
| L10 | Phases 01 and 02 are not committed to git yet. |

## 12. Final status

**COMPLETE.**

## 13. Next phase proposed for approval

**Phase 03 — Dataset integration.** A dataset selector in the AI Analyst (and SQL Explorer);
questions about an imported dataset use that dataset's schema in the AI prompt and its table
as the only allowed scope, executed on `datasets.db` through the same `run_query` path;
history records which dataset was used; Demo Mode stays on the demo data. Tests will prove a
question about one dataset cannot read another dataset, the demo tables or internal tables,
including through prompt injection in column names or values.
