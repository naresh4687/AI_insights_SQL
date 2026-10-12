# UI Theme Redesign — Phase 00: Baseline

| Item | Value |
|------|-------|
| Phase | 00 — Inspect the existing codebase (no theme changes) |
| Date | 2026-10-11 |
| Commit inspected | `561ec74` (branch `main`, working tree clean before this phase) |
| Report location | `reports/theme/` — `reports/phase_00_baseline.md` already exists (the original project baseline) and is left unchanged |
| Code changed in this phase | **None.** Only this report and a copy of screenshots in `test-results/theme_baseline/` (git-ignored) |
| Status | **COMPLETE** — awaiting approval of Phase 01 and of the decisions in §8 |

---

## 1. Framework and architecture (verified)

| Item | Finding |
|------|---------|
| Framework | **Streamlit 1.65.0**, Python 3.12.3. Server-rendered Python; no separate frontend project, no JS build |
| Entry point | `app.py`: page config, sign-in gate (`src/ui/auth.py`), `st.navigation` with role-based pages, sidebar |
| Pages | `views/<page>.py` (one line each) → `src/ui/<page>.py` (UI code) |
| Shared UI | `src/ui/theme.py` (tokens, custom CSS, chart config), `src/ui/components.py` (answer body, badges, add-to-dashboard), `src/ui/charts.py` (Altair/Vega-Lite builders) |
| Business logic | `src/` (query pipeline, SQL guard, AI providers, ingest, connectors, sync, dashboards, accounts, audit) — **out of scope for this redesign** |
| Assets | `assets/logo.svg`, `assets/icon.svg` (violet/cyan gradient) |

### Existing theme mechanism

Two layers, both **dark-only** today:

1. **`.streamlit/config.toml` `[theme]`** — Streamlit's native theme: `base = "dark"`, navy background
   `#0B1020`, violet primary `#8B5CF6`, cyan links, Inter font, radii, status colours, chart palette,
   sidebar colours. Styles every native widget, including data tables (drawn on a canvas, so they
   **cannot** be restyled with CSS — only through this config).
2. **`src/ui/theme.py`** — `COLORS` dict (mirrors config.toml) → CSS variables `--isql-*` injected once
   per run (`inject_css()`), styling only the app's own elements: page header gradient title, status
   badges, keyed cards (`st-key-kpi_*`, `chart_*`, `hist_*`, `card_*`), empty states, sidebar status
   and account blocks. Also `chart_config()` → Vega-Lite colours for every chart.

Hard-coded colours found: `src/ui/theme.py` 30, `.streamlit/config.toml` 26, `src/ui/dashboard.py` 2
(chart bar colours), `src/ui/charts.py` uses `COLORS[...]` 13 times, `assets/*.svg` 12.

### Streamlit 1.65 theme capabilities (verified in the installed package)

| Capability | Finding |
|------------|---------|
| Light **and** dark themes in config | **Yes**: `[theme.light]`, `[theme.dark]` (+ `.sidebar`) sections — 283 theme options |
| Python can read the active theme | **Yes**: `st.context.theme.type` (`"light"`/`"dark"`); documented caveat: may be wrong on first load and during a change (Streamlit issue #11920) |
| Python can **set** the theme | **No** API |
| Built-in theme switcher | In the ⋮ main menu → Settings. **Hidden in this app**: `client.toolbarMode = "minimal"`; a browser check found no main menu (`stMainMenu` count 0) |
| Persistence | Streamlit stores the choice in the browser's `localStorage` (`stActiveTheme-/-v2`); current value seen: `"System"` (follow the OS) |
| JavaScript in pages | `st.html(..., unsafe_allow_javascript=True)` exists; custom components v1 and v2 exist |

---

## 2. Feature inventory (all must be preserved)

| Area | Pages / elements |
|------|------------------|
| Shell | Logo, sidebar navigation (Analyze / Data / Inspect / App groups, role-based), Mode radio (Demo / AI), Dataset selector, AI status card, version, signed-in account + Sign out |
| Sign-in (only with `INSIGHTSQL_AUTH=oidc`) | Sign-in screen, "No access" screen, setup-error screen |
| Dashboard | Page header, Demo badge, 4 KPI cards, 4 charts (line + 3 bar), Recent activity cards, buttons |
| AI Analyst | Header + badges, New chat, chat messages, example question buttons, chat input, answer: status badge, summary, tabs (Results / Visualization / SQL / …), data table, chart type picker, CSV download, Add to dashboard popover, follow-up buttons, errors with hints |
| Dashboard Studio | Dashboard selector, filters (multiselect, slider, date range), toolbar (refresh, sync, Edit layout toggle, JSON export), chart cards in rows, edit controls, Manage expander, sharing toggle |
| Import Data | File uploader, read options, profile tables, validation results, cleaning options (many selects), change summary, save with confirmation, imported list |
| Connections | Saved list, editor form (text, number, password, selects), test, delete with confirmation, table/endpoint browser, import |
| Datasets | Table of datasets, details, column tables, refresh settings (radio, selects), refresh now, history table, sharing toggle |
| Query History | Search, status segmented control, dataset filter, entry cards with badges, expanders, Ask again / Open in Explorer |
| SQL Explorer | SQL editor (text area), run, result (same answer body as Analyst) |
| Settings & About | AI provider status check, database info, about |
| Users & Audit (admin, sign-in only) | People table, invite form, role/enable controls, unowned items, audit log table with filters |
| Cross-cutting | Success / warning / error / info alerts, spinners, expanders, popovers, tooltips, badges (icon + word), empty states, card hover and fade-in animations (`prefers-reduced-motion` respected) |

---

## 3. Baseline tests (actually run)

| Command | Result |
|---------|--------|
| `.venv/bin/pytest -q -ra` (started 2026-10-11T13:22:42Z) | **1,188 passed, 0 failed, 0 skipped** in 291 s |
| — of which browser tests (`-m e2e`, Playwright + Chromium) | 31 collected — ran and passed |
| — of which Docker tests (`-m docker`, PostgreSQL 17 / MySQL 8.4) | 58 collected — ran and passed (Docker available) |

- **No existing test checks colours, CSS classes or the theme**; the redesign cannot break a test by
  changing a colour, but also has no visual safety net yet (Phase 06 adds one).
- Pre-existing failures: **none**. Environment limitations: none observed.

### Visual baseline (evidence)

`test-results/theme_baseline/` (25 PNGs, git-ignored): the 17 screenshots written by this run's
browser tests (desktop, 768 px, 375 px; dashboard, analyst, import, explorer, connections, datasets,
studio) and 8 full-page 390 px screenshots of every main page taken earlier today against the running
app. **Not covered by screenshots:** Settings at desktop width, Users & Audit, the sign-in screens.

---

## 4. Palette contrast check (WCAG 2.1, calculated)

| Pair | Ratio | Normal text (4.5) | Large text / UI (3.0) |
|------|-------|-------------------|-----------------------|
| `#000000` on `#EFECE3` | 17.78 | Pass | Pass |
| `#4A70A9` on `#EFECE3` | **4.25** | **Fail** | Pass |
| `#4A70A9` on `#FFFFFF` | 5.02 | Pass | Pass |
| `#FFFFFF` on `#4A70A9` (button text) | 5.02 | Pass | Pass |
| `#000000` on `#8FABD4` | 8.94 | Pass | Pass |
| `#8FABD4` on `#EFECE3` | **1.99** | Fail | **Fail** |
| `#4A70A9` on `#000000` | **4.18** | **Fail** | Pass |
| `#8FABD4` on `#000000` | 8.94 | Pass | Pass |

Consequences: primary-blue **link text** directly on the off-white page needs a white glass card behind it
or a slightly darker derived blue; soft blue is decorative only (input borders need a darker derived
shade for 3:1); in dark mode, text-level accents should use `#8FABD4`, while `#4A70A9` stays for
buttons and fills (white text on it passes).

---

## 5. Known issues and risks

| # | Risk | Mitigation |
|---|------|------------|
| R1 | **No Python API to switch the theme**; Streamlit's own switcher is hidden in this app | See decision T2 |
| R2 | First-time default: with both themes defined, Streamlit starts in **"System"** (OS setting), so a visitor whose OS is dark gets dark — the brief requires **light** by default | To verify in Phase 01: force light on first visit (decision T3) |
| R3 | Data tables are canvas-drawn: only config.toml colours apply; a CSS-only theme would leave tables in the wrong colours | Use native `[theme.light]`/`[theme.dark]` (T1) |
| R4 | `st.context.theme.type` may be stale on first load / during a switch → charts or custom CSS could briefly use the other theme | Write the custom CSS with variables for both themes where possible; verify in Phase 01 |
| R5 | Glass blur needs something behind it; on a flat background `backdrop-filter` shows nothing and costs GPU | Subtle background gradient; blur only on cards; `prefers-reduced-transparency` fallback (Phase 05) |
| R6 | Reloading the page to change theme would **lose session state** (chat, results, filters) — violates the brief | Any toggle must switch without a reload |
| R7 | Status colours (success / warning / error) are not in the 4-colour palette | Keep derived status colours with icon + word (T5) |
| R8 | Logo and icon use the old violet/cyan gradient | Recolour in Phase 02 (T6) |

---

## 6. Files inspected

`app.py`, `.streamlit/config.toml`, `src/ui/theme.py`, `src/ui/charts.py`, `src/ui/dashboard.py`,
`src/ui/components.py`, all `src/ui/*.py` (colour search), `assets/*.svg`, `pytest.ini`,
`tests/*.py` (styling search), the installed Streamlit package (`config` options,
`runtime/context.py`, frontend bundle for the theme storage key).

## 7. Commands executed

```bash
git status --short; git log --oneline -3
.venv/bin/pytest -q -ra -p no:cacheprovider                 # baseline: 1,188 passed
.venv/bin/pytest -q --collect-only -m e2e | -m docker       # 31 / 58
python: streamlit.config options, inspect.signature(st.html), contrast ratios
playwright (scratchpad probe): main menu presence, localStorage theme key
```

---

## 8. Proposed approach and decisions for your approval

| # | Decision | Recommendation |
|---|----------|----------------|
| T1 | Where the theme lives | **Native**: `[theme.light]` + `[theme.dark]` in `config.toml` with your palette (all widgets and data tables follow), plus `theme.py` tokens for both modes (custom CSS, glass cards, charts) |
| T2 | The toggle | **Option A (recommended):** a visible "Dark mode" switch in the sidebar that drives Streamlit's own theme switch in the browser — no reload, nothing lost, saved by the browser. Needs a small script (`st.html` with JavaScript) that uses Streamlit's built-in switcher; it depends on Streamlit's page structure, so it gets its own browser tests, and if it cannot be done reliably I will report that rather than ship a fragile hack. **Option B (fallback, no script):** show Streamlit's ⋮ menu again (`toolbarMode = "viewer"`), where Settings → Light / Dark / System switches live and is remembered; less visible |
| T3 | Light by default | Only when no choice is saved: set the browser's choice to Light on the very first visit (verified in a browser with the OS set to dark) |
| T4 | Contrast fixes | Derived shades only where a pair fails (§4): a slightly darker blue for link text on off-white, a darker soft-blue for input borders; `#8FABD4` for accent text in dark mode |
| T5 | Status colours | Keep separate success / warning / error colours (adjusted for both modes), always with icon + word |
| T6 | Logo | Recolour `logo.svg` / `icon.svg` to the blue palette in Phase 02 |

### Phase boundaries (as in your plan, adapted to the findings)

| Phase | Scope |
|-------|-------|
| 01 Theme system | Tokens for the four colours + derived shades; `[theme.light]`/`[theme.dark]` in config.toml; `theme.py` light/dark tokens, typography, spacing, radii, borders, shadows, focus; chart config for both modes. Toggle not yet visible (Streamlit default "System" until Phase 02). Tests: config loads, app starts in both modes, all 1,188 tests |
| 02 Shell + toggle | Sidebar, navigation, header, logo; the toggle (T2); light default (T3); persistence; no rerun of queries/AI when switching |
| 03 Pages + components | Glass cards, buttons, inputs, selects, tables, popovers, expanders, alerts, empty/loading/disabled states on every page in §2 |
| 04 Analyst, SQL, charts | Chat, input, SQL panels, result tabs, all chart types (axes, legends, tooltips) in both modes |
| 05 Responsive + accessibility | 375 / 768 / desktop in both modes, contrast measured in the browser, keyboard focus, reduced motion / transparency |
| 06 Regression + verification | Full suite, new UI tests (default, switching, persistence, navigation, Demo and AI workflows), screenshot comparison with `test-results/theme_baseline/`, diff review |
| 07 Optional polish | Only with approval |

**Next step:** approve Phase 01 (and T1–T6, or tell me what to change). No commits or pushes will be
made without your explicit permission.
