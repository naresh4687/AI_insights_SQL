# Phase 08 — User accounts and access

| Item | Value |
|------|-------|
| Phase | 08 — User accounts and access |
| Date | 2026-10-11 |
| Approved by | User ("continue the development"), after the Phase 07 proposal |
| Decision taken | §9.3-1 (Phase 00) answered: **public internet / company login** → sign-in with Google or Microsoft (OpenID Connect, Streamlit's `st.login`) — decision D9 |
| Baseline | 1,122 tests (Phase 07) |
| Result | **1,188 tests passed** (66 new), 0 failed, 0 skipped, 4 min 44 s |
| Final status | **COMPLETE** — awaiting approval |

---

## 1. Scope and acceptance criteria

| # | Requirement | Met? | Evidence |
|---|-------------|------|----------|
| AC1 | Sign-in with a company/Google/Microsoft account; no passwords stored by the app | Yes | `src/ui/auth.py` (OIDC via `st.login`, Authlib 1.8.0); real-server smoke test redirected to Google with the configured client id |
| AC2 | Fails closed: on the internet, missing or wrong sign-in settings never let anyone in | Yes | `INSIGHTSQL_AUTH=oidc` + incomplete `[auth]` → setup message naming what is missing (never values), no pages; `test_without_sign_in_settings_…`, `test_incomplete_settings_…` |
| AC3 | Only allowed people: administrators, invited emails, or allowed emails/domains | Yes | `UserStore.sign_in`; uninvited, unverified email, disabled account and "same email from another identity" (takeover) are refused and audited |
| AC4 | Roles viewer / editor / admin | Yes | Access matrix (11 cases); pages per role (viewers get no Import / Connections; only admins get Users & Audit); every page checks again |
| AC5 | Per-user dashboards, connections and datasets | Yes | Owner recorded on create; private until the owner shares (datasets, dashboards: read-only); connections never shared |
| AC6 | Secrets kept per user | Yes | A connection (with its encrypted password/token) is listed and usable only by its owner (and admins) |
| AC7 | Per-user query history | Yes | `history_users` table; each person sees only their own questions |
| AC8 | Audit log of changes | Yes | `audit_log` (append-only: UPDATE/DELETE refused by triggers): sign-ins and refusals, invites, roles, enable/disable, datasets, connections, dashboards, refreshes, ownership transfers |
| AC9 | Nothing changes for an app without sign-in | Yes | `INSIGHTSQL_AUTH=none` (default): one local admin user; all 1,122 earlier tests pass unchanged except one table list (§7) |

---

## 2. How access works

1. **Gate** (`auth.require_user`, before any page): `none` → local user (full rights). `oidc` → check
   the `[auth]` settings → not signed in: sign-in screen only → signed in: `UserStore.sign_in` links
   the provider identity (`iss` + `sub`, hashed) to an account, or refuses with a reason.
2. The account is **looked up again on every click**, so disabling someone or changing a role takes
   effect immediately.
3. **One rule set** (`accounts.can_view` / `can_change`) used by the data layer, not only the pages:
   - `data_access.target(…, user)` treats a dataset the user may not read exactly like one that does
     not exist — so the AI Analyst, SQL Explorer, history reruns and dashboard charts all inherit it.
   - `dashboards.run(…, user)` checks the **chart's dataset** with the viewer's account, so a shared
     dashboard never reveals a dataset that is not shared too.
   - `ConnectionStore.list(user)`, `DashboardStore.list(user)` filter by owner/sharing.
4. **Unowned items** (made before sign-in was on): visible to administrators only, until an admin gives
   them to an account on **Users & Audit**.
5. **Administrators** are named in `INSIGHTSQL_ADMIN_EMAILS` (re-applied at each sign-in) or promoted
   by another admin. At least one active admin always remains; nobody can disable themselves.

---

## 3. Files created, modified, deleted

**Created**

| File | Purpose |
|------|---------|
| `src/accounts.py` | Users, roles, sign-in rules, access rules, admin actions, unowned-item transfer |
| `src/audit.py` | Append-only audit log (recording never breaks the action) |
| `src/ui/auth.py` | Sign-in gate, settings check, sign-in screen, sidebar account and Sign out |
| `src/ui/users.py`, `views/users.py` | Users & Audit page (admins) |
| `.streamlit/secrets.toml.example` | Sign-in settings template (Google; Microsoft commented) |
| `tests/test_accounts.py` (45), `tests/test_auth_ui.py` (21) | New tests |
| `reports/phase_08_accounts_access.md` | This report |

**Modified**

| File | Change |
|------|--------|
| `src/storage/app_db.py` | Migration 5: `users`, `audit_log` (+ triggers), `owner`/`shared` columns; a migration may be a tuple of statements (trigger bodies contain `;`) |
| `src/config.py` | `INSIGHTSQL_AUTH`, `INSIGHTSQL_ADMIN_EMAILS`, `INSIGHTSQL_ALLOWED_SIGNINS`, `INSIGHTSQL_DEFAULT_ROLE` (never `admin`) |
| `src/core/models.py`, `src/catalog.py` | `Dataset.shared`; `set_shared` |
| `src/data_access.py` | `datasets(user)`, `target(…, user)`, `visible()` |
| `src/dashboards.py` | Owner and sharing; INSERTs name their columns; `list(user)`, `set_shared`, `run(…, user)`, `add_widget(…, user)` |
| `src/connectors/profiles.py` | Owner; `list(user)`; an update keeps the owner |
| `src/ingest/store.py` | `save_import(owner=…)` |
| `src/database.py`, `src/query_service.py` | `history_users`; `add_history`/`answer_question(user_id=…)`; `recent_history(user_id=…)` |
| `app.py` | Gate first; pages by role; account in the sidebar |
| `src/ui/session.py` | `current_user()`, `signed_in()`, `history_user()`, `record()`, `visible_datasets()`; lookups pass the user |
| `src/ui/studio.py`, `components.py`, `datasets.py`, `connections.py`, `import_data.py`, `history.py`, `dashboard.py`, `settings.py`, `theme.py` | Per-user lists, owner-only controls, sharing toggles, audit records, role checks |
| `requirements.txt` | `Authlib==1.8.0` |
| `.env.example`, `README.md`, `TESTING.md` | Sign-in setup, roles, deployment notes, tests |
| `tests/conftest.py` | Sign-in settings from `.env` never reach a test |
| `tests/test_ai_mode.py` | Expected demo-database tables include `history_users` |

**Deleted:** none. Migration 5 only adds tables and columns; existing rows become unowned and private.

---

## 4. Tests executed

| Area | Tests | Result |
|------|-------|--------|
| Settings | auth mode, lists normalised, default role never admin | PASS |
| Sign-in | admin email; uninvited refused (audited); allowed domain; exact email (not suffix); look-alike domain; invite linked on first sign-in; same email from another identity / provider refused; email change to a taken address; no email / no subject; unverified email; disabled; admin email re-applied | PASS |
| Administration | only admins; last-admin protection; self-disable refused; audited invites/roles; unowned items transfer (built-in stays everyone's) | PASS |
| Access | 11-case matrix; private/shared datasets; same error as "does not exist"; un-sharing; dashboards private until shared; shared dashboard does not reveal a private dataset; charts cannot be added from unreadable datasets; connections per owner; import owner | PASS |
| History | per user; without sign-in shows all | PASS |
| Audit | UPDATE/DELETE refused; `_`/`%` in filters literal; failure never breaks the action | PASS |
| UI (AppTest) | gate closed without settings; problems named without values; sign-in screen only; no access; disabled on next click; sidebar account; no change without sign-in; pages by role; viewer has no "Add to dashboard"; dataset selector per user; history per user; shared dashboard read-only; sharing a dashboard / dataset (audited); viewer cannot share; invite and role change; admin cannot disable self; unowned items | PASS |
| Real server | `INSIGHTSQL_AUTH=oidc`, dummy Google client: only the sign-in screen, no sidebar; button redirects to `accounts.google.com` with the client id | PASS (manual smoke test) |
| Full suite | 1,188 passed, 0 failed, 0 skipped (284 s) | PASS |

---

## 5. Commands

```bash
.venv/bin/pytest -q tests/test_accounts.py tests/test_auth_ui.py
.venv/bin/pytest -q                                   # full suite
```

---

## 6. Mutation check

19 bugs planted one at a time in a throwaway copy (deleted afterwards):

| Planted bug | Caught |
|-------------|--------|
| Viewer can see private items | Yes |
| Editor can change others' items | Yes |
| Disabled accounts keep access | Yes |
| Uninvited people let in | Yes |
| Email takeover allowed (another identity, same email) | Yes |
| Unverified email accepted | Yes |
| Last admin can be removed | Yes |
| Non-admin manages users | Yes |
| Allowed-email check matches by suffix | **Missed at first** → `test_allowed_email_must_match_exactly` → Yes |
| Dataset lookup ignores the user | Yes |
| Dashboard chart runs without the user check | Yes |
| Dashboard list unfiltered | Yes |
| Connections listed for everyone | Yes |
| History not filtered | Yes |
| Gate open with missing settings | Yes |
| Viewers get the Import page | Yes |
| Audit log editable | Yes |
| Share toggle shown to non-owners | Yes |
| Import owner not recorded | Yes |

19 of 19 caught after the fix.

---

## 7. Bugs found and fixes

1. **Dashboard INSERTs listed no columns** (`VALUES (?, ?, ?, ?, ?)`); adding columns would have broken
   creating and duplicating dashboards. They now name their columns.
2. **Migration runner split on every `;`**, which breaks trigger bodies; a migration can now be a tuple
   of statements (older migrations unchanged).
3. **Settings showed the total history count of all users**; now only to administrators.
4. One earlier test listed the demo database's tables exactly; it now includes `history_users`.

---

## 8. Data integrity and security findings

- No passwords are stored; identities are keyed by a hash of provider + subject, never by email
  alone, so a second provider account with the same email cannot take over a user.
- Fails closed: `oidc` with missing settings lets nobody in; an invalid `INSIGHTSQL_AUTH` value stops
  the app. `INSIGHTSQL_DEFAULT_ROLE` can never grant admin.
- Access is enforced in the data layer (`data_access`, `dashboards.run`, store `list`), not only by
  hiding pages; a dataset a user may not read gives the same error as one that does not exist.
- Audit entries hold names and ids only (no data, SQL results or secrets) and cannot be changed.
- Connections and their secrets stay with their owner. Administrators can see and use every
  connection (they are trusted with the whole app).

---

## 9. Known limitations and open issues

| # | Issue |
|---|-------|
| L1 | Names of datasets, dashboards and connections are unique across all users; a taken name is refused ("already exists"), which reveals that the name exists. Per-user names need a table rebuild — proposed for later. |
| L2 | The real Google/Microsoft round trip is not automated (tests replace the provider). **Please try it once** with your own provider settings (README → User accounts). |
| L3 | Accounts can be disabled, not deleted (their items and audit entries stay). |
| L4 | History entries made before sign-in was turned on are shown only without sign-in. |
| L5 | Sign-in session length is Streamlit's cookie lifetime; there is no "sign out everywhere". |
| L6 | The scheduled refresh worker runs as the system (it refreshes any due dataset, using its owner's connection). |
| L7 | Earlier items remain: drag-and-drop layout (L1, Phase 07); Phases 01–08 not committed to git; `PROJECT_PROGRESS.md` outdated. |

---

## 10. Final status

**COMPLETE.**

## 11. Next phase proposed for approval

**Phase 09 — Deployment.** Docker image and Compose file with a persistent volume for `data/`,
HTTPS through a reverse proxy, health check, backups of `app.db` / `datasets.db`, the refresh worker
as a second container, and a production checklist (sign-in on, secrets outside the image).
