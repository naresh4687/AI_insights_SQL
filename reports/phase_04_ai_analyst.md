# Phase 04 — AI Analyst Enhancements

| Item | Value |
|------|-------|
| Phase | 04 — AI Analyst enhancements |
| Date | 2026-10-11 |
| Approved by | User, after the Phase 03 report ("next") |
| Baseline | 766 passed (Phase 03) |
| Result | **875 tests: 875 passed, 0 failed — three consecutive full runs** (766 earlier + 109 new) |
| Final status | **COMPLETE** — awaiting approval |

---

## 1. Scope and acceptance criteria

| # | Requirement (prompt §5.E) | Met? | How / evidence |
|---|---------------------------|------|----------------|
| AC1 | Keep question → SQL → execution → visualization → displayed SQL | Yes | Same pipeline; same first three tabs; same default chart (P04-A01–05, all earlier tests) |
| AC2 | Bar/column, line/area, pie/donut, scatter, histogram, box plot, KPI cards, tables, time series | Yes | `analysis.chart_options`, `charts.build`; P04-C* |
| AC3 | Chart recommendations from result columns | Yes | Best chart first, then the other suitable types in a **Chart type** picker; unsuitable types never offered (P04-A06–15) |
| AC4 | Trend and period-over-period analysis | Yes | First → last change, latest vs previous, largest increase/decrease (P04-A18–20) |
| AC5 | Group comparisons and rankings | Yes | Share of top item, top-3 share, ratio of first to second (P04-A21–22) |
| AC6 | Aggregations and descriptive statistics | Yes | Count, empty, total, mean, median, min, max, std. dev. (P04-A16–17) |
| AC7 | Outlier indicators | Yes | Tukey fences, named rows (P04-A29) |
| AC8 | Result summaries | Yes — **computed, not AI-written** (see §4.1) | Insights tab |
| AC9 | SQL explanations | Yes | "What this query does" (P04-X01–07) |
| AC10 | Safe follow-up questions | Yes | Asked through the normal validated pipeline (P04-U09–11) |
| AC11 | Query error explanations | Yes | Hints for 8 error kinds (P04-X08–20, P04-U12–14) |
| AC12 | Controlled export | Yes | CSV of the rows shown only, formula-injection safe (P04-X21–33, P04-E01) |
| AC13 | No invented insights; dataset and SQL always shown | Yes | Every number in the facts traced to the result (P04-A23–27); caption shows dataset and SQL source |

---

## 2. Test plan (before implementation)

| Area | Planned checks |
|------|----------------|
| Charts | Default unchanged for all 5 demo questions; options per result shape; pie limits; KPI; scatter; box by group; unique options; nothing for unchartable data; each chart builds with the right mark |
| Facts | Statistics equal pandas; period order; zero base; share/ratio wording; integer formatting; **every number traceable**; no causal/forecast words; outliers named; truncation note; unusual data never fails |
| Follow-ups | Demo: next unasked demo questions; AI: from columns; none for typed SQL; no repeats; validated when clicked |
| SQL explanation | Demo query; WHERE, DISTINCT, GROUP/HAVING, CTE, UNION ALL; unparsable/unsafe SQL |
| Error hints | Each error kind; messages that need no hint |
| Export | 6 formula prefixes; numbers and ordinary text unchanged; headers; missing values; BOM; safe file names |
| UI | Picker options and switching; KPI cards; Insights/SQL tabs; download button; follow-ups (demo and AI); error hints |
| Browser | Pie switch, Insights, SQL explanation, real CSV download, follow-ups |

---

## 3. Files created, modified, deleted

**Created**

| File | Purpose |
|------|---------|
| `src/analysis.py` | `chart_options`, `statistics`, `period_changes`, `facts`, `follow_ups` |
| `src/sql_explain.py` | `explain_sql`, `explain_error` |
| `src/export.py` | `to_csv` (formula-safe), `file_name` |
| `tests/test_analysis.py` (45), `tests/test_explain_export_charts.py` (48), `tests/test_analyst_features_ui.py` (15) | New tests |
| `reports/phase_04_ai_analyst.md` | This report |

**Modified**

| File | Change |
|------|--------|
| `src/ui/components.py` | `answer_body`: download button (CSV made on click), chart picker, KPI cards, SQL explanation, **Insights** tab (4th), follow-up buttons; error hints |
| `src/ui/charts.py` | `column`, `area`, `pie`/donut, `scatter`, `histogram`, `box`, `build` (existing `bar`, `line`, `result_chart`, `show` unchanged) |
| `src/ui/analyst.py` | Follow-ups under the latest answer only |
| `src/ui/session.py` | `Turn.dataset_id`; `session.dataset()` |
| `src/insights.py` | Public `is_period_column` (old private name kept) |
| `README.md`, `TESTING.md` | Features, structure, limitations, counts |
| `tests/test_app_e2e.py` | 1 new browser test (no existing test changed) |

**Deleted:** none.

---

## 4. Features implemented

- **Visualization tab**: the existing default chart first; a **Chart type** picker with only the
  types that suit the result (e.g. Bar · Column · Pie · Donut for 4 regions; Line · Area ·
  Column · Histogram · Box plot for months; Scatter for two measures; Box plot by category for
  repeated categories; **KPI cards** for a single row).
- **Insights tab** (new, 4th): facts and a statistics table, computed from the returned rows.
- **SQL tab**: "What this query does", step by step (tables, joins, filters, grouping,
  calculations, sorting, row limit).
- **Results tab**: **Download CSV** of the rows shown.
- **Follow-up questions** under the latest answer: in Demo Mode the next unasked demo questions;
  in AI Mode questions built from the result's columns. Clicking asks through the normal pipeline.
- **Error hints**: e.g. "There is no column named revenu. Available columns: …".

### 4.1 Decision: computed summaries instead of AI-written ones

The prompt lists "AI-generated result summaries". An AI-written summary would require sending
result **data** to the AI service; the app's documented privacy rule is that only the question
and the schema are sent. Summaries are therefore computed locally from the result, which also
guarantees they cannot invent figures (P04-A23–27 check every number). An opt-in AI summary
could be added later if you want it; it would need a visible warning that data leaves the machine.

---

## 5. Tests executed

| IDs | Tests | Result |
|-----|-------|--------|
| P04-A01–05 | default chart unchanged for each demo question | PASS |
| P04-A06–15 | option sets per shape; pie limits (3); KPI; scatter; box by category; empty/unchartable (3); uniqueness | PASS |
| P04-A16–17 | statistics vs pandas; single value has no std. dev. | PASS |
| P04-A18–20 | period order and zero base; real monthly facts (percent and largest increase recomputed); none for non-periods | PASS |
| P04-A21–22 | share facts on real region result; integers as whole numbers | PASS |
| P04-A23–27 | every number in the facts traced to the result (5 demo questions) | PASS |
| P04-A28 | no causal or forecast words (5 questions) | PASS |
| P04-A29–30 | outliers named; truncation note | PASS |
| P04-A31–35 | unusual results never fail (5) | PASS |
| P04-A36–39 | follow-ups: demo, AI, none for SQL/unsuitable, no repeats | PASS |
| P04-X01–07 | SQL explanations (demo query, 5 shapes) and 4 unexplainable inputs | PASS |
| P04-X08–20 | error hints (10) and messages without hints (3) | PASS |
| P04-X21–33 | export: 6 formula prefixes (exact), numbers/text, headers, missing values, 3 file names | PASS |
| P04-C01–14 | each chart type builds with the right mark (10); donut hole; KPI/unknown kind; period order | PASS |
| P04-U01–15 | UI: picker options and 3 switches; time picker; KPI cards; Insights; SQL tab; download; demo follow-ups; AI follow-up (sent to the AI and validated); none after error; 3 error hints | PASS |
| P04-E01 | Chrome: bar → pie (arc marks), Insights, SQL explanation, real CSV download (name, BOM, header, 4 rows), follow-ups | PASS |
| P04-R01–03 | full suite ×3 | `875 passed` ×3 — PASS |
| P04-R04 | mutation check (§7.2) | 16/16 caught (+1 equivalent) — PASS |

**Totals:** 109 new tests (45 + 48 + 15 + 1 browser) executed: 109 PASS. FAIL / BLOCKED /
SKIPPED / NOT RUN: 0.

---

## 6. Commands

```bash
.venv/bin/pytest -q tests/test_analysis.py tests/test_explain_export_charts.py tests/test_analyst_features_ui.py
.venv/bin/pytest -q tests/test_app_e2e.py -k "chart_type_switch or new_question"   # ×3 after the download fix
.venv/bin/pytest -q                                                                # ×3
bash test-results/mutate4.sh test-results/mutation                                 # throwaway copy, deleted
```

---

## 7. Evidence

### 7.1 Runs

| Run | Result |
|-----|--------|
| Existing UI tests after wiring | `88 passed` (before any new test was written) |
| `test_analysis.py` | `2 failed` (test extracted digits from product names) → `45 passed` |
| `test_explain_export_charts.py` | `48 passed`; weak assertion found and made exact → `7 passed` (formula cases) |
| `test_analyst_features_ui.py` | `15 passed` |
| Browser test | role fix → `1 passed` |
| Full suite | `1 failed` ×2 (§9.1) → `875 passed`, then `1 error` once (§9.2) → after the fix `875 passed` ×3 |

### 7.2 Mutation check (17 bugs planted one at a time; 145 tests run against each)

| Planted bug | Result |
|-------------|--------|
| Control | 145 passed |
| Default chart changed | 9 failed |
| Pie allowed with negative values | 1 failed |
| Periods not sorted | 1 failed |
| Share computed from the wrong total | 7 failed |
| Percentage from a zero base not guarded | 1 failed |
| Truncation not mentioned | 1 failed |
| Follow-ups repeat asked questions | 3 failed |
| Follow-ups offered for typed SQL | 1 failed |
| `@` formula prefix not neutralised | 1 failed |
| Column headers not neutralised | 1 failed |
| File name not sanitised | 3 failed |
| Sort direction described the wrong way | 1 failed |
| Error hint lists no columns | 2 failed |
| Donut drawn without a hole | 1 failed |
| KPI cards show the wrong column | 1 failed |
| Follow-up asked in the wrong mode | **first not caught** (test only checked "rejected"); test strengthened to check it is sent to the AI service with the question → 1 failed |
| Numbers passed through the neutraliser | 145 passed: **equivalent** (it only changes text, so numbers are unaffected) |

### 7.3 Visual check

`test-results/e2e/analyst-pie.png`: picker (Bar, Column, **Pie**, Donut), pie with a sorted
legend in the theme colours, follow-up buttons below the answer.

---

## 8. Regression results

| Area | Result |
|------|--------|
| Default charts | `insights.choose_chart` unchanged; first option = old chart for all demo questions; existing tests checking exactly one bar/line chart pass |
| Tabs | First three tabs still Results, Visualization, SQL (existing test) |
| Single-value result | Still no Vega chart and the "not suited to a simple chart" caption (existing test); KPI cards added |
| Demo Mode / AI Mode / Import / Datasets | All earlier tests pass (766) |

---

## 9. Bugs found and fixes

1. **Widget keys collided with an existing test selector.** New keys like `turn_0_chart_type`
   matched an existing browser test's `[class*=st-key-turn_]` count (failed 2/2 runs). Keys were
   renamed to put the turn last (`charttype_turn_0`, `download_turn_0`, `followup_turn_0_…`), also
   avoiding the theme's `chart_` card style. The existing test was not changed.
2. **Download button 404 (real app bug, intermittent).** The CSV was registered as a temporary
   media file on every rerun; after reruns the browser could request a file Streamlit had already
   deleted ("Download Button source error - 404"). Fix: the file is generated only when the button
   is clicked (callable `data`, supported by Streamlit 1.65). This also avoids building CSVs on every
   rerun. Verified by 3 runs of the download/turn tests and 3 clean full runs; the browser test
   checks the downloaded content.
3. **Wording/format issues found while checking real output**: integers shown with decimals
   ("7,332.00 units"); "share of the total" now says "in this result" (important for "lowest 5"
   results); clumsy follow-up grammar; pie slices capped at the 6 theme colours.
4. **SQL explanation details**: sqlglot 30 stores `WITH`/`FROM` under `with_`/`from_` (CTE step was
   missing); "smallest first" for text/dates replaced by ascending/descending; trailing period in
   column hints; `*` shown as "all columns".
5. **Test-quality fixes**: digits inside product names were counted as figures; a weak `… or …`
   assertion in the formula test was made exact; the follow-up test was strengthened (§7.2).

---

## 10. Data integrity and security findings

- No new path to the database: charts, facts, explanations and export use the already-returned
  DataFrame or the already-validated SQL text. Follow-ups are questions, validated like any other.
- No data is sent to the AI service by any new feature (summaries are local; §4.1).
- Export: only the rows shown (≤ 1,000); formula injection neutralised for values and headers;
  file names cannot contain paths.

## 11. Known limitations and open issues

| # | Issue |
|---|-------|
| L1 | Summaries are computed, not AI-written (decision §4.1). |
| L2 | Charts use at most one category and one or two measures; no multi-series or stacked charts yet. |
| L3 | Statistics and facts describe the rows returned (≤ 1,000), stated when a result was cut off. |
| L4 | The chart choice is not remembered after "New chat" or in history (planned with Dashboard Studio, Phase 07). |
| L5 | SQL explanations describe structure, not meaning ("Calculates revenue as ROUND(SUM(…))"). |
| L6 | Earlier open items remain: page deep links log harmless 404s; `PROJECT_PROGRESS.md` outdated; Phases 01–04 not committed. |

## 12. Final status

**COMPLETE.**

## 13. Next phase proposed for approval

**Phase 05 — Server connections (PostgreSQL, MySQL, REST APIs).** Connection profiles with
encrypted credentials (key from `INSIGHTSQL_SECRET_KEY`), connection testing, discovery of
schemas/tables/columns or API endpoints, choosing permitted tables, preview, and registering a
**snapshot** as a dataset (decision D4: AI-written SQL never reaches your server). REST: HTTPS,
authentication, pagination, rate limits, timeouts, response validation and SSRF protection.
Tests use PostgreSQL and MySQL in Docker containers (Docker is installed) and a local mock API;
no real credentials. New dependencies: SQLAlchemy, psycopg, PyMySQL, cryptography.
