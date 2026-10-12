# Phase 09 — Deployment: Inspection and Plan

| Item | Value |
|------|-------|
| Phase | 09 — Deployment (step 1: inspect and plan; **no code changed**) |
| Date | 2026-10-12 |
| Commit inspected | `628bb18` (`main`) |
| Status | **Awaiting approval** of the decisions in §4 |

---

## 1. What the app needs to run (verified)

| Need | Finding |
|------|---------|
| Runtime | Python 3.12, `requirements.txt` (pinned: Streamlit 1.65, pandas, SQLAlchemy, psycopg, PyMySQL, cryptography, Authlib, google-genai) |
| Start command | `streamlit run app.py` (port 8501) |
| Health check | Streamlit's `/_stcore/health` (already used by the browser tests) |
| Configuration | Environment variables only (`src/config.py`; `.env` supported). No setting is hard-coded to this computer |
| Data | Four locations, all set by environment: `insightsql.db` (demo data), `app.db` (catalog, accounts, history, dashboards, audit), `datasets.db` (imported data), `uploads/` (original files) |
| First start | The demo database is created automatically if missing (`database.ensure_database`) — no seeding step needed |
| Secrets | `.env`: `INSIGHTSQL_SECRET_KEY` (encrypts saved connection passwords), `GEMINI_API_KEY` / `HF_TOKEN`. `.streamlit/secrets.toml`: sign-in client secrets and cookie secret |
| Scheduled refresh | `scripts/refresh_worker.py --loop` — a separate process by design (Streamlit cannot run background jobs) |
| Uploads | Up to 25 MB (`[server] maxUploadSize`) — a reverse proxy must allow bodies of that size |
| Sign-in | `st.login` (OIDC). The provider's redirect address must be **https** for anything but localhost |
| Docker on this computer | Docker 29.8.1, Compose v5.1.3 — available, so everything can be built and tested here |
| Existing deployment files | **None** (no Dockerfile, Compose file, `.dockerignore`, backup script) |

## 2. Risks found

| # | Risk | Mitigation (proposed) |
|---|------|-----------------------|
| R1 | Secrets baked into the image (`.env`, `secrets.toml`, `data/*.db` are in the project folder) | `.dockerignore` excludes them; a test inspects the built image for them |
| R2 | Data lost when the container is replaced | All four data locations on one named volume (`/data`); a test restarts the stack and checks data survives |
| R3 | App and worker both write `app.db` / `datasets.db` | Same host, same volume (not a network share). SQLite's locking handles this; Python's 5-second lock wait already covers the short writes. Tested with both running |
| R4 | Copying a live SQLite file can produce a corrupt backup | Backups use SQLite's online backup API, then an integrity check; a test restores one |
| R5 | Running publicly with sign-in off (`INSIGHTSQL_AUTH=none` gives every visitor full rights) | Production checklist, plus a loud startup warning when sign-in is off in the production setup |
| R6 | Streamlit needs WebSockets; some proxies break them | Use a proxy that supports them by default (D2), tested through the proxy |
| R7 | Running as root inside the container | Non-root user; a test checks it |
| R8 | Losing `INSIGHTSQL_SECRET_KEY` makes saved connection passwords unreadable | Checklist: keep a copy of the key **outside** the server; backups do not contain it |

## 3. What will be built (if approved)

| File | Purpose |
|------|---------|
| `Dockerfile` | `python:3.12-slim`, pinned requirements, non-root user, health check, data in `/data` |
| `.dockerignore` | Keeps secrets, databases, tests, `.venv`, reports out of the image |
| `compose.yaml` | Three services: **app** (Streamlit), **worker** (scheduled refresh + daily backup), **proxy** (HTTPS); one data volume, one backup folder; restart policies |
| `deploy/Caddyfile` | Reverse proxy: HTTPS, WebSockets, 25 MB uploads |
| `scripts/backup.py` | Online backup of the three databases + uploads into a dated folder, integrity check, keeps the last N |
| `DEPLOYMENT.md` | Step-by-step guide (simple, copy-paste commands) and the production checklist |
| `tests/test_deployment.py` | Unit tests (backup/restore, config files) and Docker tests (marked `docker`, like the existing ones) |

No change to business logic, queries, AI prompts, the UI or data handling.

## 4. Decisions for your approval

| # | Decision | Recommendation |
|---|----------|----------------|
| D1 | Image | `python:3.12-slim`, non-root, same pinned versions as now |
| D2 | HTTPS / reverse proxy | **Caddy** — gets and renews a free HTTPS certificate automatically when you give it a domain name, supports WebSockets with no extra setup. Without a domain it serves `http://localhost` only. (Alternative: nginx + certbot — more steps to maintain) |
| D3 | Where it will run | Built and tested **here with Docker**, and written to work unchanged on any Linux server with Docker (for example a small VPS). **Question for you:** do you already have a server and a domain name? It does not block this phase — the guide covers both cases |
| D4 | Backups | Daily at 02:00 (server time) by the worker container, kept 7 days in `./backups` on the host; manual backup and restore commands in the guide |
| D5 | Sign-in in production | Checklist requires `INSIGHTSQL_AUTH=oidc` for a public server; the app logs a clear warning at start if it is off in the production setup (it does **not** refuse to start, so a private/local install still works) |
| D6 | Secrets | `.env` passed to the containers at run time; `secrets.toml` mounted read-only; nothing secret in the image |
| D7 | Refresh worker | Separate container from the same image, running `refresh_worker.py --loop --interval 60` |

## 5. How it will be verified

1. Image builds; contains no `.env`, `secrets.toml` or `.db`; runs as non-root.
2. `docker compose up`: all three services healthy; app reachable through the proxy; WebSockets work (a real browser test runs a Demo Mode question through the proxy).
3. Data survives `docker compose down` / `up`.
4. Worker: refreshes a due dataset; app and worker writing at the same time without lock errors.
5. Backup: created, passes the integrity check, and **restoring it** gives back the same data; old backups pruned.
6. Upload of a file near 25 MB through the proxy.
7. Full existing test suite (currently 1,268 passed) still passes.

**Next step:** approve D1–D7 (or tell me what to change) and answer D3 if you can. Nothing will be
committed or pushed without your permission.

---

# Phase 09 — Result (approved: "approve Phase 09", D1–D7 as proposed)

| Item | Value |
|------|-------|
| Date | 2026-10-12 |
| Status | **COMPLETE** |

## Built

| File | What it does |
|------|--------------|
| `Dockerfile` | `python:3.12-slim` + tzdata, pinned requirements, user `insightsql` (uid 1000), health check, data in `/data`; starts with `scripts/preflight.py` |
| `.dockerignore` | Keeps `.env`, `secrets.toml`, databases, backups, tests, `.git` out of the image |
| `compose.yaml` | `app` (not published), `worker` (refresh + daily backup), `proxy` (Caddy, ports 80/443); volume `data`, folder `./backups`; settings file and backup folder can be changed (`INSIGHTSQL_ENV_FILE`, `BACKUP_DIR`) |
| `compose.signin.yaml` | Adds `.streamlit/secrets.toml` read-only when sign-in is on |
| `deploy/Caddyfile` | HTTPS for `SITE_ADDRESS` (automatic certificate), 26 MB uploads, security headers, WebSockets |
| `src/backup.py`, `scripts/backup.py` | Online SQLite backup + integrity check + uploads + manifest; keep N; list; restore (checks every database first, needs `--yes`) |
| `scripts/refresh_worker.py` | `--backup-at HH:MM --backup-dir --backup-keep`: once a day after that time (a manual backup earlier in the day does not cancel it); a failed backup is reported, never stops refreshes |
| `src/preflight.py`, `scripts/preflight.py` | Start-up checks: errors stop the start (bad settings, sign-in on but not set up, unwritable data folder); warnings (sign-in off, no encryption key, http redirect). Creates the databases on a new install |
| `DEPLOYMENT.md` | Step-by-step guide, everyday commands, restore, production checklist |

## Verified (real containers on this computer)

| Check | Result |
|-------|--------|
| Image: no `.env`, `secrets.toml` or `.db`; runs as uid 1000; time zones work | PASS |
| All services start; app healthy; reachable **only** through the proxy; security headers | PASS |
| Browser through the proxy: dashboard, AI Analyst Demo answer, dark-mode switch, no console errors (WebSockets work) | PASS |
| 23 MB CSV uploaded through the proxy and read by the app; a 25.2 MB file is refused by Streamlit's own limit | PASS |
| App and worker writing 600 rows at the same time + a backup in between: no lock errors, all rows kept | PASS |
| Backup → change data → restore: data back to the backup (1 → 3 → 1); restore refused without `--yes` | PASS |
| `down` / `up` with a rebuilt image: data kept | PASS |
| Worker makes the scheduled backup by itself | PASS |
| Sign-in on without settings: the app does not start and says why | PASS |

## Problems found and fixed during this phase

1. A manual backup before 02:00 would have cancelled that day's scheduled backup → rule is now "no backup since today's time".
2. An unreadable backup folder would have crashed the worker → reported instead.
3. On a new install the demo database appeared only after the first visit, so an early backup missed it → created at start.
4. **My mistake while writing tests:** the test setup does not isolate the demo database, so a first run of the new tests wrote two test rows ("before backup", #26 and #27) into the real `data/insightsql.db`. Found at once, removed exactly those two rows (no linked rows), and the tests now always use their own copy; a byte comparison confirmed `data/insightsql.db` unchanged by every later run.

## Notes

- This computer has two Docker engines (Docker Desktop is the CLI default; `docker compose` used the system engine). The tests use only `docker compose`, so the image and containers are always on the same engine. Docker Desktop cannot mount `/tmp`, so the Docker test keeps its backup folder under `test-results/` and deletes it afterwards.
- Image size is about 920 MB (pandas / pyarrow, pulled in by Streamlit).
- Not tested here: a real domain with a real HTTPS certificate (needs a public server). Caddy does this itself once `SITE_ADDRESS` is a domain pointing at the server.

## Tests

`tests/test_deployment.py` 30 passed · `tests/test_deployment_docker.py` 5 passed · full suite: see the final message.
