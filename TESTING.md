# InsightSQL — Testing

## How to run

```bash
pip install -r requirements-dev.txt
pytest                      # everything (≈ 2 minutes; browser tests take most of it)
pytest -m "not e2e"         # skip browser tests (≈ 25 s)
pytest -m e2e               # browser tests only
```

Browser tests use Playwright's bundled Chromium if it is installed
(`playwright install chromium`), otherwise the system Google Chrome. Set
`INSIGHTSQL_E2E_CHANNEL=chrome` or `chromium` to force one. If neither can start, the
browser tests are **skipped** and the reason is shown in the summary (`-ra`), so check
for skips before calling a run green. Screenshots are saved to `test-results/e2e/`.

No test uses the internet, a real AI model, or `data/insightsql.db`: every test gets a
temporary database, and AI Mode is tested against `FakeGemini` and `FakeHF`
(`tests/conftest.py`): real HTTP servers on 127.0.0.1 that answer like the Gemini and
Hugging Face APIs, with dummy keys. The official Gemini SDK runs unchanged against the
fake (via `GEMINI_BASE_URL`). An autouse fixture removes any real AI keys loaded from
`.env`, so no automated test can use them. Two more autouse fixtures point the app
metadata and dataset stores at each test's temporary folder (never `data/`), and undo
`configure_logging()` after each test so log redaction cannot hide a secret that a test
checks is never logged.
`scripts/check_ai_mode.py` is a separate, manual check against the real model.

## Test layers

| Layer | Files | What it proves |
|-------|-------|----------------|
| Unit | `test_database.py`, `test_sql_guard.py`, `test_query_scope.py`, `test_catalog.py`, `test_logging_setup.py`, `test_ingest_readers.py`, `test_ingest_profile.py`, `test_ingest_preprocess.py`, `test_ingest_store.py` (import: reading, detection, cleaning, all-or-nothing saving), `test_analysis.py`, `test_explain_export_charts.py` (charts, facts, SQL explanations, error hints, CSV export), `test_insights.py`, `test_gemini_service.py`, `test_hf_service.py` | Each module on its own: schema and seed data, SQL validation and the engine-level authorizer, chart choice and explanations, the Gemini and Hugging Face clients (keys, errors, privacy, provider choice) |
| Integration | `test_dataset_integration.py` (imported datasets: scope isolation, AI prompt, history), `test_query_service.py`, `test_demo_mode.py`, `test_ai_mode.py`, `test_gemini_ai_mode.py` | Question → SQL source → validation → read-only execution → history, for Demo Mode, typed SQL and AI Mode, including each safety layer switched off in turn |
| Connectors | `test_connector_security.py`, `test_connector_rest.py` (fake API in `tests/servers.py`), `test_connector_databases.py` (real PostgreSQL 17 and MySQL 8.4 in throwaway Docker containers, marker `docker`; skipped with the reason if Docker or the images are missing) | SSRF policy, encrypted secrets, read-only sessions, pagination, limits, type mapping, import of snapshots |
| Refresh | `test_refresh.py` (fake API: full refresh, failures keep the last good data, retries, locks, schedule, worker), `test_refresh_databases.py` (Docker: incremental and full refresh on PostgreSQL and MySQL) | No failed refresh changes data; no duplicates; correct counts |
| Dashboards | `test_dashboards.py` | Storage rules, layout, filters checked against pandas, injection via filter values, tampered stored SQL, scope of imported datasets, export without data |
| Accounts and access | `test_accounts.py` (sign-in rules, roles, last-admin protection, access matrix, private and shared datasets/dashboards, connections per owner, per-user history, append-only audit log, migration of existing data), `test_auth_ui.py` (AppTest: the sign-in gate fails closed, pages per role, data per user, sharing, Users & Audit) | Nobody gets in without an allowed, verified identity; each user reaches only their own and shared items, through every page |
| Theme | `test_theme.py` (exact palette, light/dark tokens, `config.toml` ↔ `theme.py`, WCAG contrast of every text and control pair including text on glass, CSS for both themes, the switch and its script, logo colours, reduced-motion/transparency/contrast preferences, chart colours); browser (`test_app_e2e.py`, theme section): light on the first visit whatever the system setting, every themed layer in both themes, the "Dark mode" switch (mouse and keyboard) sends nothing to the server and keeps the answer on screen, the choice is kept after reload, navigation and in a new tab (no light flash), every page in dark at 1280 / 768 / 375 px without sideways scrolling or console errors | Both themes use the requested colours and stay readable; switching never loses work or runs anything |
| App (no browser) | `test_app_ui.py`, `test_import_ui.py`, `test_dataset_ui.py`, `test_analyst_features_ui.py`, `test_connections_ui.py`, `test_datasets_ui.py`, `test_studio_ui.py` | `app.py` run by Streamlit's `AppTest` on every page: navigation, KPIs and chart data checked against the database, chat state across reruns and pages, history search/rerun, SQL Explorer security, settings, empty states |
| End-to-end (browser) | `test_app_e2e.py` | The real server in Chrome: sidebar navigation with active-page marking, chat with Enter key, tabs, spinner, error styling, history → Explorer revalidation, separate sessions, 375 px and 768 px layouts, no console errors, screenshots |

## AI-assisted test design workflow

Tests were designed with an AI coding assistant (Claude Code) using the steps below.
The assistant drafts; the checks in steps 3–5 decide whether a test is kept.

1. **Requirements to risks.** For each requirement, list what could go wrong, worst
   first. Example for AI Mode: the model returns `DROP TABLE`; it returns two statements;
   the question contains a prompt injection; the API is unreachable or slow; the token is
   missing, invalid or leaked into a log; the model is not offered.
2. **Draft cases for each risk,** including the unhappy paths. The assistant writes the
   cases; a person reviews the list for gaps before any code is written.
3. **Independent oracles.** Expected values never come from the code under test. Revenue
   figures are recomputed in plain Python from the generated rows (`test_demo_mode.py`),
   and explanations may only contain figures that appear in the result
   (`test_insights.py`).
4. **Run and read failures.** A failing test is investigated before either side is
   changed, and the root cause is recorded (see `PROJECT_PROGRESS.md`, section H of each
   phase). Example: a Phase 5 failure was a test bug (a number in a product name), not an
   app bug.
5. **Mutation check: do the tests catch real bugs?** Deliberately break the code
   (in a temporary copy or with `monkeypatch`) and confirm that tests fail. A planted bug
   that no test catches means a test is missing or too weak. In Phase 7 this found two
   weak browser tests (see below).
6. **Look at the result.** Screenshots are reviewed by eye, because tests only check what
   they were told to check.

### What step 5 and 6 found in Phase 7

| Planted bug | Before | After the fix |
|-------------|--------|---------------|
| Monthly results drawn as bars | Caught (1 test) | — |
| Spinner removed | Caught (1 test) | — |
| Errors shown as plain grey text instead of a red alert | **Not caught**: tests only checked the text | Tests now require the error alert (6 tests fail) |
| 700 px-wide element on a 375 px screen | **Not caught**: Streamlit scrolls inside `stMain`, so the document never overflows | Overflow check now also looks at `stMain` (1 test fails) |

Screenshot review found that on desktop the five example buttons cut their text off
("Which five products generate…"). No test failed, because the full text is still in the
page. This is recorded as an open UI issue.

## Requirements traceability

| Requirement | Tests |
|-------------|-------|
| Seeded sample data with correct revenue | `test_database.py` (oracle, golden values) |
| Only one read-only `SELECT` on allowed tables | `test_sql_guard.py`; `test_query_service.py`; `test_app_ui.py::test_unsafe_sql_is_rejected_and_data_unchanged`; `test_app_e2e.py::test_unsafe_sql_is_rejected_in_the_browser_and_data_unchanged` |
| Defence in depth (each layer alone still blocks writes) | `test_ai_mode.py::test_*_disabled` |
| Demo Mode answers the 5 example questions correctly, offline | `test_demo_mode.py` (network blocked) |
| AI Mode: model SQL is validated; malicious output rejected | `test_ai_mode.py`; `test_app_ui.py::test_ai_mode_rejects_malicious_model_output`; `test_app_e2e.py::test_ai_mode_rejects_malicious_model_output` |
| AI failures give clear messages; Demo Mode still works | `test_gemini_service.py`; `test_gemini_ai_mode.py`; `test_hf_service.py`; `test_ai_mode.py`; `test_app_e2e.py::test_gemini_unreachable_shows_help_and_demo_mode_still_works` |
| Key/token never sent insecurely, logged or shown; no sales data sent | `test_gemini_service.py` and `test_hf_service.py` (`test_insecure_or_invalid_base_url_*`, `test_*_never_appears_*`, `test_request_contains_no_sales_data`, `test_gemini_api_key_is_used_even_when_google_api_key_is_set`) |
| SQL preview, results table, explanation | `test_app_ui.py`; `test_app_e2e.py::test_example_button_shows_sql_table_chart_explanation_and_history` |
| Suitable chart or none | `test_insights.py`; `test_app_ui.py`; `test_app_e2e.py::test_monthly_question_draws_a_line_chart` |
| Progress indicator while waiting | `test_app_e2e.py::test_ai_mode_shows_spinner_then_ai_answer` |
| Query history | `test_app_ui.py::test_history_lists_newest_first`, `test_history_search_and_status_filter`; history checks in `test_app_e2e.py` |
| Dashboard figures are real | `test_app_ui.py::test_kpis_match_the_database`, `test_dashboard_charts_draw_the_query_results`, `test_month_over_month_caption_uses_real_months` |
| History reruns are revalidated | `test_app_ui.py::test_tampered_history_*`; `test_app_e2e.py::test_history_sql_opens_in_explorer_and_is_revalidated` |
| Secrets never displayed | `test_app_ui.py::test_settings_never_shows_the_key_*`, `test_hf_token_never_shown`; `test_app_e2e.py::test_settings_shows_status_but_never_the_key` |
| Clear errors for empty, unsupported and unsafe input | `test_app_ui.py`; `test_app_e2e.py` error tests |
| Sign-in required and fails closed (no settings → no access) | `test_auth_ui.py::test_without_sign_in_settings_the_app_stays_closed`, `test_incomplete_settings_are_named_without_values`, `test_visitor_sees_only_the_sign_in_screen` |
| Only invited / allowed, verified identities; no account takeover by email | `test_accounts.py::test_uninvited_*`, `test_allowed_domain_*`, `test_same_email_from_another_identity_is_refused`, `test_unverified_email_is_refused`, `test_disabled_account_is_refused` |
| Roles (viewer / editor / admin) | `test_accounts.py::test_access_matrix`, `test_only_admins_manage_users`, `test_at_least_one_admin_remains`; `test_auth_ui.py::test_pages_follow_the_role`, `test_viewer_cannot_*` |
| Per-user datasets, dashboards, connections, history | `test_accounts.py::test_private_datasets_are_invisible_to_others`, `test_shared_dashboard_does_not_reveal_a_private_dataset`, `test_connections_are_listed_for_their_owner_only`, `test_history_is_kept_per_user`; `test_auth_ui.py::test_dataset_selector_*`, `test_history_is_per_user` |
| Audit log of changes | `test_accounts.py::test_audit_log_cannot_be_changed`, `test_role_changes_and_invites_are_audited`; `test_auth_ui.py::test_owner_shares_*` |
| Works on a phone-sized screen | `test_app_e2e.py::test_narrow_screen_has_no_horizontal_scroll` + screenshots |

## Not covered

- The real Gemini model (run `scripts/check_ai_mode.py` with `GEMINI_API_KEY` set). The fake proves the app handles
  any reply safely, not that a real model writes correct SQL.
- Browsers other than Chromium/Chrome.
- The real sign-in round trip with Google or Microsoft (`st.login`): tests replace the provider with fixed
  identity claims (`auth.identity`). Try it by hand once with your own provider settings.
- Accessibility (screen readers, contrast) beyond visible text and roles.
