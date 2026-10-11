# Phase 07 — Dashboard Studio

| Item | Value |
|------|-------|
| Phase | 07 — Dashboard Studio |
| Date | 2026-10-11 |
| Approved by | User ("continue the process of the development"), after the Phase 06 proposal |
| Baseline | 1,070 tests (Phase 06) |
| Result | **1,122 tests passed** (52 new), 0 failed, 9 min 43 s |
| Final status | **COMPLETE** — approved ("continue the development") |

---

## 1. Scope and acceptance criteria

| # | Requirement | Met? | Evidence |
|---|-------------|------|----------|
| AC1 | Create, rename, duplicate, delete dashboards | Yes | `DashboardStore`; `test_create_get_list_and_positions`, `test_duplicate_…`, `test_delete_…`, `test_rename_duplicate_delete` (UI) |
| AC2 | Add charts from AI Analyst answers; save validated SQL, dataset and chart type — never the AI call | Yes | **Add to dashboard** popover under every answer; `test_stored_sql_is_the_validated_form`, `test_answers_are_added_with_their_chart_type` |
| AC3 | Arrange widgets | Yes — order and width controls (**Edit layout**: move earlier/later, full / half / one-third width, title, chart type). Streamlit has no native drag-and-resize grid; the drag-and-drop question from Phase 00 is still open | `test_layout_fills_rows`, `test_move_update_and_remove_…`, `test_layout_editing` |
| AC4 | Date, category and number filters applied to compatible charts through the same validated, dataset-scoped query path | Yes | Filters wrap the stored SQL as `SELECT * FROM (<sql>) WHERE …` with **bound parameters**; the wrapped SQL is validated and run with the dataset scope; charts without the column are left alone and say so | `test_date_filter_…` (checked against pandas), `test_category_and_number_filters`, `test_filter_values_are_parameters_not_sql`, `test_compatibility` |
| AC5 | Refresh dashboard data | Yes | **Refresh data** re-runs every query; **Refresh source data** first fetches from the connections the charts use (Phase 06 refresh) | `test_refresh_source_data` |
| AC6 | Export | Yes | CSV of each chart's data; JSON definition (charts, SQL, filters — no data, no secrets) | `test_export_has_the_definition_and_no_data`, `test_exports_are_offered` |

---

## 2. How a dashboard is shown

1. Each widget's stored SQL is run through `run_query` **again**, with its own dataset's scope —
   so altered stored SQL, or a dataset that was removed, gives a clear error on that chart only.
2. Filter choices (categories, date and number ranges) come from the unfiltered data of the charts
   the filter fits.
3. When a filter is set, compatible charts run the wrapped, parameterised query; others are unchanged.
4. If the saved chart type no longer suits the data (e.g. after a filter), the best fitting type is
   used and a note says so.
5. Charts are laid out in rows of 6 units (full = 6, half = 3, third = 2), in their saved order.

---

## 3. Files created, modified, deleted

**Created**

| File | Purpose |
|------|---------|
| `src/dashboards.py` | Store (dashboards, widgets, filters), layout, filters, running charts, JSON export |
| `src/ui/studio.py`, `views/studio.py` | Dashboard Studio page |
| `tests/test_dashboards.py` (42), `tests/test_studio_ui.py` (9) | New tests |
| `reports/phase_07_dashboard_studio.md` | This report |

**Modified**

| File | Change |
|------|--------|
| `src/storage/app_db.py` | Migration 4: `dashboards`, `dashboard_widgets`, `dashboard_filters` (cascade delete, unique names, unique filter column per dashboard) |
| `src/query_service.py` | `run_query(params=…)` — bound parameters for filter values |
| `src/ui/components.py` | **Add to dashboard** under each answer (existing or new dashboard, title, width) |
| `src/catalog.py` | Edited at 17:01, after the previous session's full run (1,119 passed at 16:52). The change was not written down and cannot be diffed (the file is not committed); this phase's full run covers it |
| `app.py`, `src/ui/session.py` | Analyze → Dashboard Studio page |
| `README.md`, `TESTING.md` | Dashboard Studio usage, structure, tests |
| `tests/test_app_e2e.py` | 1 browser test: answer → dashboard → Studio |

**Deleted:** none. Migration 4 only adds tables.

---

## 4. Tests executed

| Area | Tests | Result |
|------|-------|--------|
| Storage | create/get/list, unique names, duplicate copies independently, delete cascades, positions stay contiguous after move/remove, limits (24 charts, 6 filters), invalid chart type / width / title | PASS |
| Safety | unsafe SQL refused when added; tampered stored SQL rejected when shown (`query_history`, `DELETE`, `sqlite_master`); imported dataset stays in its scope; filter values are parameters, never SQL; column names quoted | PASS |
| Filters | date (months, days, datetimes — whole last day included) checked against pandas; category and number; unset filters change nothing; choices from chart data; numbers sorted numerically | PASS |
| Robustness | removed dataset → error on that chart only; chart type falls back with a note | PASS |
| Export | JSON has exactly the definition fields and no result data | PASS |
| UI (AppTest) | empty state + create; answers added with chart type; category and month filters; layout editing; rename / duplicate / delete (with confirmation); exports offered; removed dataset; refresh source data | PASS |
| Browser | answer → Add to dashboard → Studio shows the chart (screenshot `test-results/e2e/studio.png`) | PASS |
| Full suite | 1,122 passed, 0 failed (583 s) | PASS |

---

## 5. Commands

```bash
.venv/bin/pytest -q tests/test_dashboards.py tests/test_studio_ui.py
.venv/bin/pytest -q tests/test_app_e2e.py -k dashboard
.venv/bin/pytest -q                                   # full suite
```

---

## 6. Mutation check

13 bugs planted one at a time in a throwaway copy (deleted afterwards):

| Planted bug | Caught |
|-------------|--------|
| Adding a chart skips SQL validation | Yes |
| Charts run without their dataset scope | Yes |
| Category values written into the SQL text | Yes |
| Filters applied to charts without the column | Yes |
| Layout row overflow | Yes |
| Numbers sorted as text in category choices | Yes |
| Duplicate name check ignores case | Yes |
| Removing a filter does not update the dashboard time | Yes |
| Duplicate drops charts | Yes |
| Column-name quotes not escaped | Yes |
| Export adds an extra field | **Missed at first** → export test now checks the exact fields → Yes |
| Chart limit off by one | Yes |
| Delete works without the confirmation tick | Yes |

13 of 13 caught after the fix.

---

## 7. Bugs found and fixes

1. **Category choices on number columns sorted as text** (1, 10, 11, 2 …); now numeric order.
2. **Removing a chart used two transactions** (delete, then renumber); now one.
3. **Removing a filter did not update the dashboard's "updated" time**; now it does.
4. **Duplicate failed the second time** ("… (copy)" already existed); the page now picks a free
   name ("… (copy) (2)").
5. **Export test too loose** (found by the mutation check); now checks the exact fields.

---

## 8. Data integrity and security findings

- Dashboards store SQL, never AI calls or data; each chart is re-validated on every view.
- Filter values are always bound parameters; column names are quoted.
- A chart can read only its own dataset's tables (both guard layers), even if the stored SQL is edited.
- Export contains no data and no secrets.

---

## 9. Known limitations and open issues

| # | Issue |
|---|-------|
| L1 | No drag-and-drop layout (Streamlit limit); order and width controls instead. Your answer on drag-and-drop is still open. |
| L2 | A dashboard JSON can be exported but not imported yet. |
| L3 | Charts on a dashboard run when the page is shown (no result cache); a dashboard of many large charts loads slower. |
| L4 | Dashboards are shared by everyone using this app (no user accounts until Phase 08). |
| L5 | Earlier items remain (Phases 01–07 not committed to git; `PROJECT_PROGRESS.md` outdated). |

---

## 10. Final status

**COMPLETE.**

## 11. Next phase proposed for approval

**Phase 08 — User accounts and access.** Sign-in, per-user dashboards, connections and datasets,
roles (viewer / editor / admin), secrets kept per user, and an audit log of changes.
