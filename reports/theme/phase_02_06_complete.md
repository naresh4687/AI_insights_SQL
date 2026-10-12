# UI Theme Redesign — Phases 02–06: Switch, Components, Charts, Accessibility, Verification

| Item | Value |
|------|-------|
| Phases | 02 Shell + toggle · 03 Pages + components · 04 Analyst, SQL, charts · 05 Responsive + accessibility · 06 Regression + verification |
| Date | 2026-10-12 |
| Approved by | User: "approve to complete all the continuesly no phase by phase" (Phase 07, optional polish, not included) |
| Before | 1,235 passed (Phase 01) — baseline 1,188 (Phase 00) |
| Result | **1,256 passed, 0 failed, 0 skipped** (628 s); theme browser tests then run twice more: 9/9 passed both times |
| Status | **COMPLETE** — nothing committed or pushed |

---

## 1. Phase 02 — Application shell and the "Dark mode" switch

| Requirement | Done | How |
|-------------|------|-----|
| Visible toggle | Yes | "Dark mode" switch at the bottom of the sidebar (`theme.theme_toggle()`, called in `app.py`): a real `<button role="switch" aria-checked>` with a moon icon and a track/thumb |
| No reload, nothing lost | Yes | The switch chooses Light/Dark in **Streamlit's own theme menu** (now enabled by `toolbarMode = "viewer"`, kept hidden by CSS). Verified: **0 messages** sent to the server while switching (so no rerun, no query, no AI request); the AI Analyst answer and chart stay on screen; history count unchanged |
| Light by default | Yes | With no saved choice the script selects Light — tested with the OS set to dark and to light |
| Remembered | Yes | `localStorage["isql-theme"]`; Streamlit's own per-page key is also written for every page, so reloads, page changes and **new tabs on any page** start in the chosen theme with no light flash (tested frame by frame) |
| Keyboard | Yes | Space and Enter toggle; focus returns to the switch; visible focus ring |
| Sidebar, navigation, header | Yes | Current page: blue tint + blue left bar + bold text; hover tint; quieter section headings; header is transparent glass; sidebar border |
| Logo and icon (L1) | Yes | Blue palette only (`#4A70A9` mark, off-white and soft-blue bars). Wordmark in `#4A70A9`: 3.7:1 on the light sidebar, 3.8:1 on the dark one (large bold text needs 3:1) |
| If Streamlit changes | Handled | If the menu is ever missing, the switch hides itself (`data-isql-theme-switch="unavailable"`) instead of doing nothing; a browser test would fail first |

Investigated first (scratch app, not the project): Streamlit 1.65 has no Python or URL API to set the theme;
its host-message route needs configured allowed origins (rejected as fragile); clicking the hidden menu items
works with the menu hidden, closes cleanly, and does not rerun the script.

## 2. Phase 03 — Glass components on every page

Buttons (secondary glass, primary blue with lift and darker hover), text/number/select/text-area inputs (blue
focus ring), segmented controls and pills (selected option tinted with readable blue text — fixed a 3.6:1
contrast issue in dark), tabs, expanders, forms, chat messages and chat input, code blocks, file drop zone,
alerts, popovers and select menus (more opaque "popover" glass), KPI/chart/history cards (blur added), subtle
background glow so the glass has something to show.

**KPI cut-off (L6) fixed:** `$283,700.56` now fits in all four cards at 1280 px (responsive font size, no clipping).

## 3. Phase 04 — Analyst, SQL and charts

Chart tooltips styled as theme glass (key in muted text, value in bold); bar/arc hover feedback; chart text,
grid and axis lines follow a switch live (Phase 01); chat and SQL panels styled as above. Chart marks keep
`CHART_COLORS` (≥ 3:1 on both backgrounds), so no redraw is needed on a switch.

## 4. Phase 05 — Responsive and accessibility

| Check | Result |
|-------|--------|
| 1280 / 768 / 375 px, every page, dark | No sideways scrolling, no console errors (browser test) |
| Same widths, light | Covered by the existing layout tests |
| Text contrast incl. text **on glass** (composited over both backgrounds) | ≥ 4.5:1 for text, muted and blue text in both themes |
| `prefers-reduced-motion` | Animations and transitions off |
| `prefers-reduced-transparency` | Solid surfaces, no blur, no background glow |
| `prefers-contrast: more` | Firmer borders |
| Windows high contrast (`forced-colors`) | Switch keeps a visible outline and state |
| Focus | One visible blue ring on links, buttons, tabs, expanders and the switch |

## 5. Phase 06 — Tests

| Command | Result |
|---------|--------|
| `.venv/bin/pytest -q -ra` (full) | **1,256 passed, 0 failed, 0 skipped** |
| `pytest tests/test_theme.py` | 59 passed (14 new) |
| `pytest tests/test_app_e2e.py -k "theme or dark or first_visit or remembered"` ×3 | 9 passed each time |

New browser tests: first visit light (OS light and dark) · every themed layer in both themes · switching keeps
the answer and sends nothing to the server (mouse, Space, Enter) · remembered after reload, navigation and in a
new tab without a light flash · every page in dark at 1280 / 768 / 375 px.

New unit tests: script has no reload/network calls and stores only the theme keys · first visit light · switch
markup is an accessible switch · Streamlit menu available but hidden · accessibility media queries · text on
glass layers · logo uses only the palette and is readable on both sidebars.

One test changed meaning: Phase 01's "theme follows the system setting" no longer holds (the first visit is now
always light, as the brief requires); it became `test_every_themed_layer_uses_the_theme_colours`.

Evidence: `test-results/e2e/theme-*.png`, `dark-{1280,768,375}-*.png` (git-ignored); compare with
`test-results/theme_baseline/`.

## 6. Files changed in these phases

| File | Change |
|------|--------|
| `src/ui/theme.py` | Popover/glow tokens; shell, component, chart-tooltip and accessibility CSS; theme script (switching, memory, light default, switch sync); `theme_toggle()` |
| `.streamlit/config.toml` | `toolbarMode = "viewer"` (menu hidden by CSS), with a comment why |
| `app.py` | One line: the switch in the sidebar |
| `assets/logo.svg`, `assets/icon.svg` | Blue palette |
| `tests/test_theme.py`, `tests/test_app_e2e.py` | Tests above |
| `README.md`, `TESTING.md` | Themes, switch and test layer |

No business logic, queries, AI prompts, schemas or data handling changed.

## 7. Known limitations

| # | Limitation |
|---|------------|
| K1 | The switch relies on Streamlit's menu test ids (`stMainMenu`, `stMainMenuItem-theme-Light/Dark`). A Streamlit upgrade that renames them hides the switch and fails the browser tests — re-check after upgrading Streamlit |
| K2 | Very first visit with the OS in dark mode: a brief dark frame before light is applied (only once; later visits start in the saved theme) |
| K3 | Opening a page's address directly makes Streamlit request `/<page>/_stcore/health` and `/host-config` first (two 404s in the console). This comes from Streamlit's own address lookup, not from the theme code; the tests allow exactly these two and fail on any other 404 |
| K4 | Data tables are drawn on a canvas: themed through `config.toml` only, no glass |
| K5 | Logo wordmark meets the large-text ratio (3:1), not the normal-text ratio (4.5:1) — one colour cannot reach 4.5:1 on both sidebars |
