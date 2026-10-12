# UI Theme Redesign — Phase 01: Centralized Theme System

| Item | Value |
|------|-------|
| Phase | 01 — Create the centralized theme system |
| Date | 2026-10-11 |
| Approved by | User: "approve Phase 01" (decisions T1–T6 of Phase 00 accepted) |
| Baseline | 1,188 passed, 0 failed, 0 skipped (Phase 00) |
| Result | **1,235 passed** (47 new), **0 failed, 0 skipped**, 298 s |
| Status | **COMPLETE** — awaiting approval of Phase 02 |

---

## 1. Scope completed

| Task | Done | Notes |
|------|------|-------|
| Centralized tokens for the exact four colours | Yes | `theme.PALETTE` = `#EFECE3`, `#8FABD4`, `#4A70A9`, `#000000` (test asserts exact values) |
| Light and dark theme definitions | Yes | `theme.LIGHT`, `theme.DARK`; `.streamlit/config.toml` `[theme.light]`, `[theme.dark]` (+ sidebars), generated from the tokens and checked equal by tests |
| Typography, spacing, radii, borders, shadows, focus | Yes | `theme.SCALE` (font stack, radii sm/md/lg/pill, spacing 1–5, blur, focus width, easing); shadows and glass values per theme; focus outline in primary blue for the app's own focusable elements (Streamlit widgets already use the primary colour) |
| Reuse existing conventions | Yes | Same two layers as before (config.toml for Streamlit widgets; `theme.py` for `isql-*` classes and keyed cards); same CSS selectors; no new dependency |
| No unintended overrides of component behaviour | Yes | CSS only recolours; no event handlers, layout or widget behaviour changed |

Not in this phase (by plan): the visible toggle and forced light default (Phase 02), glass styling of
every component (Phase 03), tooltips and chart polish (Phase 04).

---

## 2. What was verified before building (throwaway app in the scratchpad, not in the project)

| Question | Finding |
|----------|---------|
| First visit, OS in dark mode | Dark theme (Streamlit default "System") — confirms R2; light default is Phase 02 work |
| Does switching theme re-run Python? | **No.** Colours change instantly; session state kept (`runs=1`) |
| Is the choice remembered? | Yes, after a reload (`localStorage` `stActiveTheme-/-v2` = `"Light"`) |
| Does `st.context.theme.type` follow a switch? | Only on the next run (it still said "dark" right after switching to Light) |
| Can CSS know the theme? | Not by itself (no class or attribute on `<html>`/`<body>`) |
| Script in `st.html(..., unsafe_allow_javascript=True)` | Runs in the page (no iframe); a `MutationObserver` on `.stApp` saw every switch live, kept the mark after reruns and reloads |
| Menu items for a future toggle | Stable test ids `stMainMenuItem-theme-Light / -Dark / -System` (menu shown only with `toolbarMode = "viewer"`) |
| Chart axis text with Streamlit's chart theme | Fixed `#808495` in light mode, not configurable — so the app keeps its own chart config and sets chart text by CSS |

### Resulting design

- `THEME_SCRIPT` marks `<html data-isql-theme="light|dark">` from the app's actual background and updates
  it the moment the theme changes; the CSS defines every token under `:root[data-isql-theme=…]`.
- Until the script runs, `:root` carries the theme Python saw (`st.context.theme.type`, light if unknown).
- Chart marks use `CHART_COLORS`, chosen to be ≥ 3:1 on **both** backgrounds, so a switch never needs a
  redraw; chart text, grid and axis lines are set by CSS and follow the switch.

---

## 3. Files created or modified

| File | Change |
|------|--------|
| `src/ui/theme.py` | Rewritten: palette, light/dark tokens, scale, chart colours, CSS using tokens only, theme script, `css()`, `current_mode()`, `chart_config(mode)`. Badge, header, empty-state helpers unchanged in behaviour; the header title is now solid text (the old violet/cyan gradient is gone) |
| `.streamlit/config.toml` | `[theme]` keeps shared settings with `base = "light"`; new `[theme.light]`, `[theme.light.sidebar]`, `[theme.dark]`, `[theme.dark.sidebar]`; old dark-only colours removed. `[server]` and `[client]` unchanged |
| `src/ui/charts.py` | Colours from `CHART_COLORS` (`PRIMARY`, `SECONDARY`) instead of the old violet/cyan |
| `src/ui/dashboard.py` | Two hard-coded bar colours → `charts.SECONDARY` / `charts.PRIMARY` |
| `tests/test_theme.py` (new, 45 tests) | Palette, config ↔ tokens, contrast, CSS, script, charts |
| `tests/test_app_e2e.py` | `_open(color_scheme=…)` (default light, as before); new `test_theme_follows_the_system_setting[light|dark]` |
| `README.md`, `TESTING.md` | Theme description and test layer |
| `reports/theme/phase_01_theme_system.md` | This report |

No file outside `src/ui/`, `.streamlit/config.toml`, docs and tests changed; no business logic, queries,
AI prompts, schemas or data handling. Diff reviewed (`git diff`): only colour sources changed in
`charts.py` / `dashboard.py`.

---

## 4. Derived colours (only where an exact palette pair is unreadable)

| Token | Light | Dark | Why |
|-------|-------|------|-----|
| Link / blue text | `#3B5D8F` (5.65:1) | `#8FABD4` (palette, 7.79:1) | `#4A70A9` as text is 4.25:1 on `#EFECE3`, 3.6:1 on dark |
| Secondary text | `#55534D` (6.51:1) | `#A9B3C4` | — |
| Input outlines | `#75869F` (3.52:1) | `#66779A` | `#8FABD4` is 1.99:1 on `#EFECE3` |
| Success / warning / error | `#146B3E` / `#8A5300` / `#B3261E` | `#3DD68C` / `#F5B841` / `#F87171` | Status needs its own hues (always with icon + word) |
| Dark background / surface / sidebar | — | `#0F1520` / `#18202E` / `#0B1019` | Complementary navy-black, not an inversion |
| Chart marks | `#4A70A9` + 5 hues | same | ≥ 3:1 on both backgrounds |

Primary buttons: white on `#4A70A9` = 5.02:1 in both themes.

---

## 5. Tests executed

| Command | Result |
|---------|--------|
| `.venv/bin/pytest -q tests/test_theme.py` | 45 passed |
| `.venv/bin/pytest -q tests/test_app_e2e.py -k theme_follows` | 2 passed (light, dark) |
| `.venv/bin/pytest -q -ra` (full) | **1,235 passed, 0 failed, 0 skipped** (298 s) |

| Group | Status |
|-------|--------|
| Theme configuration loads (TOML parses; Streamlit started in both modes) | PASS |
| Palette exact; config ↔ tokens identical (light, dark, sidebars, chart colours) | PASS |
| Contrast: every text token on its backgrounds ≥ 4.5 (both themes, and on white glass); controls and chart marks ≥ 3 | PASS |
| No old dark-theme colour left in `config.toml` or `src/ui/`; no hex colours in UI code outside `theme.py` | PASS |
| Browser, OS light: `data-isql-theme=light`, background `#EFECE3`, text black, glass card, blue accent text, chart labels themed, no console errors | PASS |
| Browser, OS dark: same checks with the dark tokens | PASS |
| All earlier tests (Demo Mode, AI Mode, analyst, dashboards, import, connectors, refresh, accounts, 31 browser tests) | PASS (unchanged from baseline) |
| Live switch inside the app | NOT RUN — no toggle yet (Phase 02); verified only in the scratch probe (§2) |

### Evidence

- `test-results/theme_phase01/theme-light-dashboard.png`, `theme-dark-dashboard.png` (browser tests),
  `p1-light-dashboard.png`, `p1-dark-dashboard.png` (manual probe, 1280 px).
- Baseline for comparison: `test-results/theme_baseline/desktop-dashboard.png`.

---

## 6. Remaining issues and limitations

| # | Issue | Plan |
|---|-------|------|
| L1 | Logo text ("Insight") is white in the SVG and nearly invisible on the light sidebar | Phase 02 (T6, logo recolour) |
| L2 | No visible toggle; Streamlit's menu is still hidden, so users follow their OS setting | Phase 02 |
| L3 | First-time visitors with a dark OS see dark (brief: light default) | Phase 02 (T3) |
| L4 | Pages look consistent in both themes, but glass styling of inputs, tabs, expanders, popovers and alerts is not done yet | Phase 03 |
| L5 | Chart tooltips still use Vega's default style | Phase 04 |
| L6 | "$283,70…" is cut off in the first KPI card at 1280 px — **already so in the baseline** (`theme_baseline/desktop-dashboard.png`), not caused by this phase | Phase 05 (responsive) |
| L7 | The theme script relies on `.stApp` and its background colour (Streamlit markup); covered by the browser test so a Streamlit upgrade that breaks it fails a test | — |

---

## 7. Next phase proposed for approval

**Phase 02 — Application shell and theme toggle.** Visible "Dark mode" switch in the sidebar that drives
Streamlit's own theme switch (no reload, no rerun, choice remembered by the browser); light on the
first visit; sidebar, navigation and header styling; logo and icon in the blue palette; browser tests
for default, switching both ways, persistence after reload, navigation, and no queries or AI calls on a
switch.
