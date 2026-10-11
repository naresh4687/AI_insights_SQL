# Phase 05 — Server Connections (PostgreSQL, MySQL, REST APIs)

| Item | Value |
|------|-------|
| Phase | 05 — Server connections |
| Date | 2026-10-11 |
| Approved by | User, after the Phase 04 report ("next"); paused and resumed by the user ("pause the process", "continue") |
| Baseline | 875 passed (Phase 04) |
| Result | **1,018 tests collected; last full run 1,013 passed, 0 failed** (before the 5 tests added from the mutation check, which were run separately: all pass) |
| Final status | **COMPLETE** — awaiting approval |

---

## 1. Scope and acceptance criteria (prompt §5.F)

| # | Requirement | Met? | Evidence |
|---|-------------|------|----------|
| AC1 | Separate connection management for PostgreSQL, MySQL, REST | Yes | `connectors/profiles.py`; Connections page |
| AC2 | Connection profiles | Yes | Saved in `app.db` (migration 2); P05-S20–S27 |
| AC3 | Connection testing | Yes | Read-only check + server version; P05-D01, P05-U07 |
| AC4 | Secure credential handling | Yes | Fernet encryption with `INSIGHTSQL_SECRET_KEY`; secret never displayed, stored in plaintext, logged or put in URLs; P05-S16–S21, P05-R03, P05-D11, P05-U02 |
| AC5 | Discovery (schemas, tables, columns / endpoints) | Yes | Tables and views outside system schemas; columns with server types; API endpoint preview; P05-D02–D03 |
| AC6 | User selection of permitted data | Yes | Table and columns chosen by the user; only listed tables/columns can be read; P05-D06–D10, P05-D16–D19 |
| AC7 | Data previews | Yes | First 100 rows / first page; P05-D04, P05-R25 |
| AC8 | Type mapping and schema validation | Yes | Server types → InsightSQL types, preset as explicit column types so non-fitting values are reported; P05-D03, P05-D21 |
| AC9 | Dataset registration | Yes | Snapshot → same import review and all-or-nothing save; source recorded (no secrets); P05-D21, P05-R26, P05-U05, P05-U08 |
| AC10 | Clear connection errors | Yes | Mapped, user-safe messages; P05-D11–D14, P05-R13–R20 |
| AC11 | Manual refresh, configurable synchronisation | **Deferred to Phase 06** (as planned) | Everything needed to refresh is stored with each dataset (`extra.source`) |
| AC12 | Read-only, least privilege | Yes | Server-side read-only sessions even for admin accounts (P05-D15); read-only account recommended in the UI |
| AC13 | REST: HTTPS, auth, pagination, rate limits, timeouts, response validation, SSRF protection | Yes | §4.2; P05-R* |
| AC14 | No plaintext credentials in source, Git, reports or logs | Yes | Only encrypted tokens stored; tests use throwaway test passwords; key redacted from logs |
| AC15 | Tests without production credentials | Yes | PostgreSQL/MySQL in throwaway Docker containers, local fake API |

---

## 2. Decisions

| ID | Decision | Why |
|----|----------|-----|
| D4 (approved in Phase 00) | **Snapshots, not live queries** | AI-written SQL never reaches the user's server; one validated SQL dialect |
| P05-1 | Snapshots reuse the Phase 02 import review | Same quality checks, cleaning, confirmation and atomic save; no second code path |
| P05-2 | Private networks blocked by default; exact `host`/`host:port` allow-list | Prompt §5.F (SSRF). Local databases need e.g. `INSIGHTSQL_ALLOWED_PRIVATE_HOSTS=localhost:5432` |
| P05-3 | Cloud metadata always blocked, even if allow-listed | Never a legitimate data source |
| P05-4 | Tables above the row limit are refused, not cut | "Never silently discard records" |
| P05-5 | Binary columns are not importable and are listed as skipped | They cannot be represented in the text pipeline; skipping is shown to the user |
| P05-6 | Timestamps kept to the second and converted to UTC (stated on the page) | The dataset type is `YYYY-MM-DD HH:MM:SS` |

---

## 3. Files created, modified, deleted

**Created**

| File | Purpose |
|------|---------|
| `src/core/secrets.py` | Fernet encryption of connection secrets |
| `src/connectors/__init__.py`, `network.py`, `profiles.py`, `databases.py`, `rest.py`, `snapshot.py` | SSRF policy, saved connections, PostgreSQL/MySQL, REST, snapshot → import |
| `src/ui/connections.py`, `views/connections.py` | Connections page |
| `tests/servers.py` | Docker database servers and the fake REST API |
| `tests/test_connector_security.py` (62), `tests/test_connector_rest.py` (34), `tests/test_connector_databases.py` (37), `tests/test_connections_ui.py` (8) | New tests |
| `reports/phase_05_connectors.md` | This report |

**Modified**

| File | Change |
|------|--------|
| `src/storage/app_db.py` | Migration 2: `connections` table |
| `src/config.py` | `get_secret_key`, `get_allowed_private_hosts`, `get_connector_timeout` |
| `src/ingest/store.py` | `source` metadata; source types for PostgreSQL, MySQL, REST |
| `src/ui/import_data.py` | Review steps reusable for any source (`review_table`); fix for saving from another page |
| `app.py`, `src/ui/session.py` | Data → Connections page |
| `requirements.txt` | SQLAlchemy 2.1.4, psycopg[binary] 3.3.6, PyMySQL 1.2.3, cryptography 50.0.2 |
| `.env.example`, `README.md`, `TESTING.md`, `pytest.ini` (`docker` marker) | Settings and documentation |
| `tests/conftest.py` | Real `INSIGHTSQL_SECRET_KEY`/allow-list values from `.env` are removed for every test |
| `tests/test_catalog.py` | Two migration tests used the hard-coded next number `2`; they now compute it (same checks); 1 new upgrade test |
| `tests/test_app_e2e.py` | Live server gets a test-only key and allows 127.0.0.1 (for the fake API); 1 new browser test |

**Deleted:** none. No user data migrated; migration 2 only adds a table (P05-C01).

---

## 4. Features implemented

### 4.1 Connections page (Data → Connections)

1. **Saved connections** list (name, type, address, last test — never secrets).
2. **Add or change a connection**: PostgreSQL/MySQL (host, port, database, user, SSL mode,
   password) or REST (base address, authentication: none / bearer token / API-key header /
   basic). The secret field is a password field, empty when editing ("leave empty to keep the
   saved one"). Save, Test connection, Delete (with confirmation; imported datasets keep their data).
3. **Choose data to import**: databases — load tables, choose a table and columns, see server
   types and InsightSQL types, preview, fetch; APIs — endpoint path, parameters, records
   location, pagination (page number, offset/limit, next link) with page limit, preview, fetch.
4. The snapshot then continues with the Import Data review steps (quality, cleaning, summary,
   confirmation, save).

### 4.2 Security controls

| Control | Where |
|---------|-------|
| SSRF: every resolved address checked; private, loopback, link-local, shared, multicast, reserved refused; numeric/IPv6-mapped forms normalised; metadata always refused | `network.check` |
| Database connection made to the checked address (`hostaddr` for PostgreSQL; IP for MySQL without TLS) | `databases._engine` |
| Server-side read-only sessions + statement timeout; the test fails the connection if read-only cannot be confirmed | `databases._connect`, `databases.test` |
| Only listed tables (non-system schemas) and their importable columns; SQLAlchemy-built queries | `databases.fetch` |
| API: https unless allow-listed; secret only in headers; no redirects; next links same origin; proxies from the environment ignored; TLS verified; size, page and record limits; polite retries on 429/503 | `rest.py` |
| Secrets Fernet-encrypted; key redacted from logs; errors never include secrets | `core/secrets.py`, `profiles.py` |

---

## 5. Tests executed

Test servers: **PostgreSQL 17 (postgres:17-alpine) and MySQL 8.4 (mysql:8.4)** in throwaway
Docker containers on random 127.0.0.1 ports, seeded with typed columns, NULLs, a +05:30
timestamp (reader account set to Asia/Kolkata), a binary column, a table name with a space,
a view, a table the reader may not read, 1,500 rows, and formula-like text. Fake REST API:
local HTTP server with every pagination style, three auth types and failure modes.

| IDs | Tests | Result |
|-----|-------|--------|
| P05-S01–S17 | 17 private/local address forms refused (incl. `2130706433`, `0x7f000001`, `017700000001`, `::ffff:127.0.0.1`) | PASS |
| P05-S18–S23 | 6 metadata forms refused even when allow-listed | PASS |
| P05-S24–S27 | allow-list exact; every resolved address checked; public allowed; IPv4-mapped public allowed | PASS |
| P05-S28–S34 | 7 invalid/unknown hosts | PASS |
| P05-S35–S38 | secrets: round trip, no plaintext, missing/invalid key, changed key | PASS |
| P05-S39–S46 | profiles: encrypted-only storage (raw file checked), keep/replace secret, required secret, no secret for open APIs, duplicates, no key → nothing stored, delete and test status | PASS |
| P05-S47–S62 | 15 invalid settings; http only for allow-listed hosts; key never in logs | PASS |
| P05-R01–R03 | bearer in header only; API-key header and basic auth; wrong credentials not leaked | PASS |
| P05-R04–R08 | page, offset and next-link pagination return every record once; parameters sent; too many pages / records are errors | PASS |
| P05-R09–R20 | redirects never followed; next links to metadata / other host refused; 7 endpoint-path tricks refused with no request made; private API refused; proxies ignored | PASS |
| P05-R21–R30 | 8 bad responses explained (429, 500, 404, HTML, bad JSON, no list, scalars, timeout); retry after 429; size limit | PASS |
| P05-R31–R34 | nested records flattened without loss; preview = first page only; API snapshot → dataset → query (3 paid orders, 18.0) | PASS |
| P05-D01–D05 | (each on PostgreSQL and MySQL) read-only test; tables without system schemas; type mapping; values to text incl. NULLs and UTC; quoted names | PASS |
| P05-D06–D10 | injected table/column names, unreadable table, binary column, no columns → refused | PASS |
| P05-D11–D15 | system tables (`information_schema`) refused even though readable; admin session is read-only (write refused, data unchanged); wrong password not leaked; unknown database; closed port | PASS |
| P05-D16–D21 | local server refused without allow-list; row limit refused not cut; database snapshot → dataset → query (3 rows, 30.5, 2025-01-05) | PASS |
| P05-C01 | existing version-1 `app.db` upgrades to version 2 keeping its datasets | PASS |
| P05-U01–U08 | page: key warning and empty state; secret never shown after save; no key → explained, nothing stored; invalid settings; API preview → fetch → import; API errors; test, failed test, delete; PostgreSQL browse → import (Docker) | PASS |
| P05-E01 | Chrome: create REST connection, fetch, save dataset; token never in page HTML; every request carried the bearer header | PASS (3/3 runs) |
| P05-F01 | Full suite | `1013 passed in 213.67s` — PASS |

**Totals:** 143 new tests (62 + 34 + 37 + 8 + 1 catalog + 1 browser) written and executed: all
PASS. 38 of the 1,018 tests need Docker (marker `docker`); none were skipped in these runs.
FAIL / BLOCKED / SKIPPED / NOT RUN: 0.

**Not tested** (needs real infrastructure): TLS/SSL connections with real certificates
(`require`, `verify-full`); servers on the public internet; DNS rebinding (residual risk, §10).

---

## 6. Commands

```bash
docker pull postgres:17-alpine ; docker pull mysql:8.4
.venv/bin/pip install "sqlalchemy==2.1.4" "psycopg[binary]==3.3.6" "pymysql==1.2.3" "cryptography==50.0.2"
.venv/bin/pytest -q tests/test_connector_security.py tests/test_connector_rest.py
.venv/bin/pytest -q tests/test_connector_databases.py tests/test_connections_ui.py      # Docker
.venv/bin/pytest -q tests/test_app_e2e.py -k api_connection                            # ×3
.venv/bin/pytest -q                                                                    # full suite
docker ps -aq --filter name=insightsql-test-                                            # 0 left after every run
```

---

## 7. Evidence

### 7.1 Runs

| Run | Result |
|-----|--------|
| Network policy probe | 15 local/private/metadata forms refused, public hosts allowed, allow-list exact |
| Security tests | `1 failed` (port 0 bug, §9.1) → `61 passed` → `62 passed` after the added test |
| REST tests | `1 failed` (next-link bug, §9.2) → `34 passed` |
| Database tests | seed failures in my test helper (§9.5) → `2 failed` (§9.3) → `33 passed` → `37 passed` |
| Connections page tests | `5 failed` (1 app bug §9.4, 4 test issues) → `8 passed` |
| Browser test | 3 test-locator fixes → `1 passed` ×3 |
| Full suite | `2 failed, 1010 passed` ×2 (migration tests, §9.6) → `1013 passed` |

### 7.2 Mutation check (bugs planted one at a time in a throwaway copy)

| Planted bug | Result |
|-------------|--------|
| Private addresses allowed | 20 failed |
| Metadata allowed when listed | 5 failed |
| Only the first resolved address checked | 1 failed |
| Allow-list ignores the port | 1 failed |
| Secret stored in plaintext | 37 failed |
| http allowed for any API | 1 failed |
| Redirects followed | 1 failed |
| Next-link host not checked | 2 failed |
| Endpoint path not validated | 7 failed (first attempt did not apply: my quoting; redone) |
| Proxy settings trusted | 1 failed |
| No response size limit | 1 failed |
| Page limit silently stops | 1 failed |
| PostgreSQL session not read-only | 2 failed |
| MySQL session not read-only | 2 failed |
| Unlisted tables readable | **first not caught** (other checks also blocked every case) → test added for readable system tables → 4 failed |
| Time zones not converted | **first not caught** (test server ran in UTC) → reader account set to +05:30 → 1 failed |
| Row limit silently cuts | 2 failed |
| IPv4-mapped address not unwrapped | not caught: **equivalent** on Python 3.12 (it already evaluates mapped addresses by their IPv4 part); kept for safety on other versions; a test for a mapped public address was added |

17 of 17 non-equivalent mutations caught.

### 7.3 Visual check

`test-results/e2e/connections-imported.png`: saved connection listed by address; the token
field is empty with "Leave empty to keep the saved one"; success message for the imported dataset.

---

## 8. Regression results

All 875 earlier tests pass in the full run (Demo Mode, AI Mode, import, datasets, analyst
features, browser tests). The import page refactor kept its 12 tests unchanged.

---

## 9. Bugs found and fixed

1. **Port 0 was silently replaced by the default port** (`0` is "falsy"). Now only a missing port gets the default.
2. **Next-page links lost their query string**: passing an empty parameter dict made httpx drop
   `?after=3`, so the same page was fetched until the page limit stopped it. Fixed (`params=None`).
3. **A refused destination escaped as an unhandled error** for databases (the engine was created
   outside the error handling), which would have crashed the page. Now a clear `ConnectorError`.
4. **Saving from the Connections page crashed** (`upload_nonce` existed only after visiting Import Data).
5. **Test helper issues (not app code)**: the MySQL seed's retry loop re-ran a half-applied seed and
   hid the real error (MySQL's 1,000-step recursion limit); a container that failed to start was not
   removed. The helper now waits for readiness, seeds once, and always removes failed containers.
   Leftover containers from those runs (2) were removed; every later run left 0.
6. **Two Phase 01 migration tests assumed the next migration would be number 2**; they now compute it.
7. Browser-test locator issues (labels also matching help icons; a dropdown closed by a rerun) fixed in the test helpers.

---

## 10. Data integrity and security findings

- Secrets: only encrypted tokens are stored (raw `app.db` checked); never shown, logged, put in
  URLs, or saved in dataset metadata. Without `INSIGHTSQL_SECRET_KEY`, saving is refused.
  **If the key is lost, saved secrets cannot be recovered** (users re-enter them).
- Server data is never modified: read-only sessions even for admin accounts.
- Residual risk: **DNS rebinding** for APIs (the name could resolve differently between the check
  and the request). Mitigated by re-checking on every request, no redirects and same-origin
  pagination; database connections use the checked address. Full protection would need a custom
  connection layer that pins the checked IP.
- MySQL with TLS connects by host name (needed for certificate checks), so the pinned-address
  protection does not apply to that case.
- Snapshot originals are stored in `data/uploads/` (git-ignored); API originals are the raw JSON pages.

## 11. Known limitations and open issues

| # | Issue |
|---|-------|
| L1 | Refresh and synchronisation are Phase 06 (the source is stored for it). |
| L2 | TLS with real certificates not tested (no certificate infrastructure here). |
| L3 | MySQL `BOOLEAN` is `TINYINT(1)`, so it is imported as a whole number (0/1). |
| L4 | Binary columns are skipped; time precision is one second. |
| L5 | REST: GET with JSON only; no OAuth flows, XML or POST-based APIs. |
| L6 | Tables larger than `INSIGHTSQL_IMPORT_MAX_ROWS` (200,000) are refused, not partially imported. |
| L7 | No user accounts yet: anyone using a running app can use saved connections (Phase 08). |
| L8 | Earlier items remain (`PROJECT_PROGRESS.md` outdated; Phases 01–05 not committed to git). |

## 12. Final status

**COMPLETE.**

## 13. Next phase proposed for approval

**Phase 06 — Refresh and synchronisation.** Manual **Refresh** for datasets imported from a
connection (re-fetch with the stored source and cleaning options); scheduled refresh by a
separate worker (`scripts/refresh_worker.py`, run by cron or a systemd timer, decision D8);
incremental sync where a reliable key or timestamp column exists; refresh status, timestamps,
job log and limited retries. A refresh is built in a new table and swapped in only when it fully
succeeds, so a failed or partial refresh never replaces the last good data. Streaming is not
claimed: periodic polling is described as polling.
