"""Design tokens, the custom CSS, and the chart theme — for the light and the dark theme.

Palette (exact, from the design brief): warm off-white ``#EFECE3`` (light background), soft blue
``#8FABD4`` (surfaces, borders, accents), primary blue ``#4A70A9`` (actions, active and selected
states, focus) and black ``#000000`` (text). Other values are derived from these only where a
pair would not be readable (WCAG contrast, checked in ``tests/test_theme.py``).

Two layers, kept in step by tests:

1. ``.streamlit/config.toml`` ``[theme.light]`` / ``[theme.dark]`` — Streamlit's own widgets,
   including data tables (drawn on a canvas, so CSS cannot recolour them).
2. This module — CSS variables for the app's own elements (``isql-*`` classes and keyed
   containers), and the Vega-Lite chart config.

Streamlit switches theme in the browser without re-running Python, so the CSS cannot rely on the
theme Python saw. A small script (``THEME_SCRIPT``) marks ``<html data-isql-theme="light|dark">``
from the app's actual background and updates it the moment the theme changes; the CSS keys off
that attribute. Before the script runs, the theme Python saw (``st.context.theme.type``) applies.

The sidebar "Dark mode" switch (``theme_toggle``) changes the theme through Streamlit's own theme
setting, in the browser only: no reload and no rerun, so nothing on the page is lost or run again.
The choice is remembered by the browser; the first visit is light whatever the system setting.
"""

import html

import streamlit as st

PALETTE = {"off_white": "#EFECE3", "soft_blue": "#8FABD4", "primary": "#4A70A9", "black": "#000000"}

LIGHT = {
    "bg": PALETTE["off_white"],
    "surface": "#FAF9F6",            # inputs, code blocks (Streamlit secondary background)
    "sidebar": "#DADEE0",            # 22 % soft blue over the off-white
    "sidebar_surface": "#F3F4F4",
    "text": PALETTE["black"],
    "muted": "#55534D",              # secondary text, 6.5:1 on the background
    "primary": PALETTE["primary"],   # buttons, active navigation, focus, selected states
    "on_primary": "#FFFFFF",         # text on primary fills, 5.0:1
    "accent_text": "#3B5D8F",        # links and blue text, 5.7:1 (primary itself is 4.25:1 here)
    "soft": PALETTE["soft_blue"],    # decorative accents only (2.0:1 on the background)
    "border": "rgba(74, 112, 169, .20)",   # quiet card and divider borders
    "widget_border": "#75869F",      # input outlines, 3.5:1
    "glass": "rgba(255, 255, 255, .55)",
    "glass_strong": "rgba(255, 255, 255, .78)",
    "glass_border": "rgba(255, 255, 255, .70)",
    "shadow": "0 1px 2px rgba(17, 30, 54, .06), 0 10px 28px -14px rgba(17, 30, 54, .22)",
    "shadow_hover": "0 2px 4px rgba(17, 30, 54, .08), 0 16px 32px -14px rgba(74, 112, 169, .35)",
    "success": "#146B3E",
    "warning": "#8A5300",
    "error": "#B3261E",
    "success_bg": "#DCEBE1",          # alert and badge backgrounds; their text is 5:1 or more on them
    "warning_bg": "#F3E6CF",
    "error_bg": "#F6DEDA",
    "info_bg": "#DCE4EF",
    "chart_label": "#3F3E3A",
    "chart_grid": "rgba(0, 0, 0, .08)",
    "code_text": "#1F3A63",
    "table_header": "#E4E6E6",
    "table_header_text": "#33322E",
    "popover": "rgba(250, 249, 246, .92)",     # menus, popovers, chart tooltips: glass but readable
    "glow_1": "rgba(143, 171, 212, .30)",      # soft background light behind the glass
    "glow_2": "rgba(74, 112, 169, .10)",
}

DARK = {
    "bg": "#0F1520",
    "surface": "#18202E",
    "sidebar": "#0B1019",
    "sidebar_surface": "#151C29",
    "text": PALETTE["off_white"],
    "muted": "#A9B3C4",
    "primary": PALETTE["primary"],
    "on_primary": "#FFFFFF",
    "accent_text": PALETTE["soft_blue"],   # 7.8:1; primary blue as text would be 3.6:1 here
    "soft": PALETTE["soft_blue"],
    "border": "rgba(143, 171, 212, .16)",
    "widget_border": "#66779A",
    "glass": "rgba(255, 255, 255, .045)",
    "glass_strong": "rgba(255, 255, 255, .08)",
    "glass_border": "rgba(143, 171, 212, .18)",
    "shadow": "0 1px 2px rgba(0, 0, 0, .35), 0 10px 28px -14px rgba(0, 0, 0, .6)",
    "shadow_hover": "0 2px 4px rgba(0, 0, 0, .4), 0 16px 32px -14px rgba(74, 112, 169, .45)",
    "success": "#3DD68C",
    "warning": "#F5B841",
    "error": "#F87171",
    "success_bg": "#12301F",
    "warning_bg": "#33280F",
    "error_bg": "#3A1A1C",
    "info_bg": "#1A2740",
    "chart_label": "#C9CFDA",
    "chart_grid": "rgba(239, 236, 227, .10)",
    "code_text": "#C9D7EC",
    "table_header": "#151C29",
    "table_header_text": "#C9CFDA",
    "popover": "rgba(24, 32, 46, .94)",
    "glow_1": "rgba(74, 112, 169, .22)",
    "glow_2": "rgba(143, 171, 212, .07)",
}

THEMES = {"light": LIGHT, "dark": DARK}

# Chart marks: readable (3:1 or more) on both backgrounds, so a theme switch never needs a redraw.
CHART_COLORS = ["#4A70A9", "#2E8A87", "#B4693C", "#7A5BA6", "#5E8C3A", "#B04F6E"]

# Shared, theme-independent tokens.
SCALE = {
    "font": "Inter, system-ui, -apple-system, 'Segoe UI', sans-serif",
    "radius_sm": ".5rem", "radius_md": ".75rem", "radius_lg": "1rem", "radius_pill": "999px",
    "space_1": ".25rem", "space_2": ".5rem", "space_3": ".75rem", "space_4": "1rem", "space_5": "1.5rem",
    "blur": "14px",
    "focus_width": "2px",
    "ease": "cubic-bezier(.2, .8, .2, 1)",
}


def current_mode() -> str:
    """The theme Python sees ('light' or 'dark'); light if unknown (e.g. in tests)."""
    try:
        mode = st.context.theme.type
    except Exception:
        mode = None
    return mode if mode in THEMES else "light"


def _variables(tokens: dict) -> str:
    return " ".join(f"--isql-{name.replace('_', '-')}: {value};" for name, value in tokens.items())


def _token_css(initial: str) -> str:
    scale = " ".join(f"--isql-{k.replace('_', '-')}: {v};" for k, v in SCALE.items())
    return (f":root {{ {scale} {_variables(THEMES[initial])} }}\n"
            f':root[data-isql-theme="light"] {{ {_variables(LIGHT)} }}\n'
            f':root[data-isql-theme="dark"] {{ {_variables(DARK)} }}\n')


CSS = """
/* Page header */
.isql-eyebrow { color: var(--isql-accent-text); font-size: .78rem; font-weight: 600;
  letter-spacing: .08em; text-transform: uppercase; margin: 0 0 .35rem; }
.isql-title { font-size: clamp(1.6rem, 2.6vw, 2.15rem); font-weight: 700; line-height: 1.2;
  margin: 0 0 .4rem; letter-spacing: -.01em; color: var(--isql-text); }
.isql-title-accent { color: var(--isql-accent-text); }
.isql-subtitle { color: var(--isql-muted); font-size: .98rem; max-width: 46rem; margin: 0; }

/* Status badges: icon + word, never colour alone */
.isql-badge { display: inline-flex; align-items: center; gap: .35rem; padding: .18rem .6rem;
  border-radius: var(--isql-radius-pill); font-size: .78rem; font-weight: 600; border: 1px solid;
  white-space: nowrap; }
.isql-badge--ok { color: var(--isql-success); border-color: color-mix(in srgb, var(--isql-success) 40%, transparent);
  background: var(--isql-success-bg); }
.isql-badge--warn { color: var(--isql-warning); border-color: color-mix(in srgb, var(--isql-warning) 40%, transparent);
  background: var(--isql-warning-bg); }
.isql-badge--error { color: var(--isql-error); border-color: color-mix(in srgb, var(--isql-error) 40%, transparent);
  background: var(--isql-error-bg); }
.isql-badge--info { color: var(--isql-accent-text); border-color: color-mix(in srgb, var(--isql-primary) 45%, transparent);
  background: var(--isql-info-bg); }
.isql-badge--muted { color: var(--isql-muted); border-color: var(--isql-border); background: transparent; }
.isql-meta { color: var(--isql-muted); font-size: .82rem; }

/* Cards: KPI, chart and list containers (keys start with kpi_, chart_, hist_, card_) */
[class*="st-key-kpi_"], [class*="st-key-chart_"], [class*="st-key-hist_"], [class*="st-key-card_"] {
  background: var(--isql-glass-strong);
  -webkit-backdrop-filter: blur(var(--isql-blur)); backdrop-filter: blur(var(--isql-blur));
  border-color: var(--isql-border) !important;
  box-shadow: var(--isql-shadow);
  transition: border-color .2s var(--isql-ease), transform .2s var(--isql-ease), box-shadow .2s var(--isql-ease);
  animation: isql-rise .35s var(--isql-ease) both;
}
[class*="st-key-kpi_"]:hover, [class*="st-key-hist_"]:hover, [class*="st-key-card_"]:hover {
  border-color: color-mix(in srgb, var(--isql-primary) 55%, transparent) !important; transform: translateY(-2px);
  box-shadow: var(--isql-shadow-hover);
}
[class*="st-key-kpi_"] { border-top: 2px solid var(--isql-primary) !important; }

/* Chat turns fade in */
[class*="st-key-turn_"] { animation: isql-rise .3s var(--isql-ease) both; }

/* Empty states */
.isql-empty { text-align: center; padding: 2.2rem 1rem; color: var(--isql-muted);
  border: 1px dashed var(--isql-widget-border); border-radius: var(--isql-radius-md); }
.isql-empty strong { display: block; color: var(--isql-text); font-size: 1.02rem; margin-bottom: .3rem; }

/* Sidebar status card and account */
.isql-status { border: 1px solid var(--isql-border); border-radius: var(--isql-radius-md); padding: .7rem .8rem;
  background: var(--isql-glass); font-size: .82rem; color: var(--isql-muted); line-height: 1.5; }
.isql-status b { color: var(--isql-text); font-weight: 600; }
.isql-version { color: var(--isql-muted); font-size: .75rem; margin-top: .5rem; }
.isql-account { font-size: .82rem; color: var(--isql-muted); line-height: 1.6; margin-bottom: .4rem;
  overflow-wrap: anywhere; }
.isql-account b { color: var(--isql-text); font-weight: 600; }
.isql-account-email { display: block; }

/* Focus: visible on the app's own focusable elements (Streamlit widgets use the primary colour) */
.isql-header a:focus-visible, .isql-status a:focus-visible, .isql-empty a:focus-visible {
  outline: var(--isql-focus-width) solid var(--isql-primary); outline-offset: 2px; border-radius: 4px; }

/* Charts (Vega-Lite SVG): text and lines follow the theme live; CSS overrides the SVG attributes */
.vega-embed svg .role-axis-label text, .vega-embed svg .role-axis-title text,
.vega-embed svg .role-legend-label text, .vega-embed svg .role-legend-title text,
.vega-embed svg .role-title-text text { fill: var(--isql-chart-label); }
.vega-embed svg .role-axis-grid path, .vega-embed svg .role-axis-grid line { stroke: var(--isql-chart-grid); }
.vega-embed svg .role-axis-domain path, .vega-embed svg .role-axis-domain line,
.vega-embed svg .role-axis-tick path, .vega-embed svg .role-axis-tick line { stroke: var(--isql-widget-border); }
.vega-embed svg .mark-arc path { stroke: var(--isql-bg); }

/* Chart hover and tooltips (the tooltip is added to the page body by Vega) */
.vega-embed svg .mark-rect path, .vega-embed svg .mark-arc path { transition: opacity .15s var(--isql-ease); }
.vega-embed svg .mark-rect path:hover, .vega-embed svg .mark-arc path:hover { opacity: .82; }
#vg-tooltip-element.vg-tooltip { background: var(--isql-popover); color: var(--isql-text);
  border: 1px solid var(--isql-border); border-radius: var(--isql-radius-sm); box-shadow: var(--isql-shadow);
  -webkit-backdrop-filter: blur(var(--isql-blur)); backdrop-filter: blur(var(--isql-blur));
  font-family: var(--isql-font); font-size: .8rem; padding: .45rem .6rem; }
#vg-tooltip-element.vg-tooltip td.key { color: var(--isql-muted); font-weight: 500; }
#vg-tooltip-element.vg-tooltip td.value { color: var(--isql-text); font-weight: 600; }

/* --- Application shell -------------------------------------------------------------- */

/* Soft light behind the glass (a flat background would leave the blur nothing to show) */
.stApp { background-image: radial-gradient(60rem 36rem at 100% -10%, var(--isql-glow-1), transparent 70%),
  radial-gradient(48rem 30rem at -10% 110%, var(--isql-glow-2), transparent 70%);
  background-attachment: fixed; }
[data-testid="stHeader"] { background: transparent;
  -webkit-backdrop-filter: blur(var(--isql-blur)); backdrop-filter: blur(var(--isql-blur)); }
[data-testid="stSidebar"] { border-right: 1px solid var(--isql-border); }

/* Navigation: rounded items, quiet hover, the current page marked by a blue bar and tint */
[data-testid="stNavSectionHeader"] { color: var(--isql-muted); letter-spacing: .06em; }
[data-testid="stSidebarNavLink"] { border-radius: var(--isql-radius-sm);
  transition: background-color .15s var(--isql-ease), box-shadow .15s var(--isql-ease); }
[data-testid="stSidebarNavLink"]:hover { background: color-mix(in srgb, var(--isql-primary) 9%, transparent); }
[data-testid="stSidebarNavLink"][aria-current="page"] {
  background: color-mix(in srgb, var(--isql-primary) 16%, transparent);
  box-shadow: inset 3px 0 0 var(--isql-primary); }
[data-testid="stSidebarNavLink"][aria-current="page"] p { color: var(--isql-text); font-weight: 600; }
[data-testid="stSidebarNavLink"][aria-current="page"] [data-testid="stIconMaterial"] { color: var(--isql-accent-text); }

/* Streamlit's own menu stays hidden (as before); the theme switch below drives it */
[data-testid="stMainMenu"], [data-testid="stMainMenuPopover"] { display: none !important; }

/* The "Dark mode" switch in the sidebar */
.isql-theme-toggle { display: flex; align-items: center; justify-content: space-between; gap: .75rem; width: 100%;
  margin-top: .75rem; padding: .55rem .75rem; font: inherit; font-size: .88rem; font-weight: 500;
  color: var(--isql-text); background: var(--isql-glass); border: 1px solid var(--isql-border);
  border-radius: var(--isql-radius-md); cursor: pointer;
  transition: border-color .15s var(--isql-ease), background-color .15s var(--isql-ease); }
.isql-theme-toggle:hover { border-color: color-mix(in srgb, var(--isql-primary) 55%, transparent); }
.isql-theme-toggle-label { display: inline-flex; align-items: center; gap: .5rem; }
.isql-theme-toggle-label::before { content: ""; width: 1rem; height: 1rem; background: var(--isql-accent-text);
  -webkit-mask: var(--isql-moon) center / contain no-repeat; mask: var(--isql-moon) center / contain no-repeat; }
:root { --isql-moon: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cpath d='M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z'/%3E%3C/svg%3E"); }
.isql-theme-toggle-track { position: relative; flex: none; width: 2.25rem; height: 1.25rem;
  border-radius: var(--isql-radius-pill); border: 1px solid var(--isql-widget-border);
  background: color-mix(in srgb, var(--isql-widget-border) 22%, transparent);
  transition: background-color .2s var(--isql-ease), border-color .2s var(--isql-ease); }
.isql-theme-toggle-thumb { position: absolute; top: 50%; left: .15rem; width: .85rem; height: .85rem;
  border-radius: 50%; background: var(--isql-widget-border); transform: translateY(-50%);
  transition: transform .2s var(--isql-ease), background-color .2s var(--isql-ease); }
.isql-theme-toggle[aria-checked="true"] .isql-theme-toggle-track { background: var(--isql-primary);
  border-color: var(--isql-primary); }
.isql-theme-toggle[aria-checked="true"] .isql-theme-toggle-thumb { background: var(--isql-on-primary);
  transform: translate(1rem, -50%); }
:root[data-isql-theme-switch="unavailable"] .isql-theme-toggle { display: none; }

/* --- Components --------------------------------------------------------------------- */

/* Buttons: glass secondary buttons, primary buttons in the primary blue with a soft lift */
[data-testid="stBaseButton-secondary"], [data-testid="stBaseButton-secondaryFormSubmit"],
[data-testid="stPopoverButton"], [data-testid="stDownloadButton"] button {
  background: var(--isql-glass-strong); border-color: var(--isql-widget-border);
  transition: border-color .15s var(--isql-ease), color .15s var(--isql-ease), box-shadow .15s var(--isql-ease); }
[data-testid="stBaseButton-secondary"]:hover:not(:disabled), [data-testid="stBaseButton-secondaryFormSubmit"]:hover:not(:disabled),
[data-testid="stPopoverButton"]:hover:not(:disabled), [data-testid="stDownloadButton"] button:hover:not(:disabled) {
  border-color: var(--isql-primary); color: var(--isql-accent-text); box-shadow: var(--isql-shadow); }
[data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primaryFormSubmit"] {
  box-shadow: 0 6px 16px -8px var(--isql-primary);
  transition: background-color .15s var(--isql-ease), box-shadow .15s var(--isql-ease), transform .15s var(--isql-ease); }
[data-testid="stBaseButton-primary"]:hover:not(:disabled), [data-testid="stBaseButton-primaryFormSubmit"]:hover:not(:disabled) {
  background: color-mix(in srgb, var(--isql-primary) 86%, black); color: var(--isql-on-primary);  /* darker in both themes */
  transform: translateY(-1px); }
button:disabled { cursor: not-allowed; }

/* Inputs and selects: a soft blue ring around the focused field */
[data-baseweb="input"], [data-baseweb="select"] > div, [data-baseweb="textarea"] {
  transition: box-shadow .15s var(--isql-ease), border-color .15s var(--isql-ease); }
[data-baseweb="input"]:focus-within, [data-baseweb="select"] > div:focus-within, [data-baseweb="textarea"]:focus-within {
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--isql-primary) 28%, transparent); }

/* Segmented controls and pills: the selected option tinted, its text in the readable blue */
[data-testid="stBaseButton-segmented_controlActive"], [data-testid="stBaseButton-pillsActive"] {
  color: var(--isql-accent-text); background: color-mix(in srgb, var(--isql-primary) 14%, transparent); }
[data-testid="stBaseButton-segmented_controlActive"] p, [data-testid="stBaseButton-pillsActive"] p { font-weight: 600; }

/* Tabs: the selected tab in blue text */
[data-testid="stTabs"] button[role="tab"] { transition: color .15s var(--isql-ease); }
[data-testid="stTabs"] button[role="tab"]:hover, [data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
  color: var(--isql-accent-text); }
[data-testid="stTabs"] button[role="tab"][aria-selected="true"] p { font-weight: 600; }

/* Expanders, chat messages, code, tables and the file drop zone: glass panels */
/* No blur on expanders: most sit inside a blurred card, and a second blur layer turns them grey */
[data-testid="stExpander"] details { background: var(--isql-glass); border-color: var(--isql-border);
  border-radius: var(--isql-radius-md); }
[data-testid="stExpander"] summary:hover { color: var(--isql-accent-text); }
[data-testid="stChatMessage"] { background: var(--isql-glass); border: 1px solid var(--isql-border);
  border-radius: var(--isql-radius-lg); padding: var(--isql-space-4); }
[data-testid="stChatInput"] > div { background: var(--isql-glass-strong); border-color: var(--isql-widget-border);
  -webkit-backdrop-filter: blur(var(--isql-blur)); backdrop-filter: blur(var(--isql-blur));
  transition: box-shadow .15s var(--isql-ease); }
[data-testid="stChatInput"] > div:focus-within { box-shadow: 0 0 0 3px color-mix(in srgb, var(--isql-primary) 28%, transparent); }
[data-testid="stCode"] pre { border: 1px solid var(--isql-border); border-radius: var(--isql-radius-md); }
[data-testid="stDataFrame"] { border-radius: var(--isql-radius-sm); }
[data-testid="stFileUploaderDropzone"] { background: var(--isql-glass); border: 1px dashed var(--isql-widget-border);
  border-radius: var(--isql-radius-md); transition: border-color .15s var(--isql-ease), background-color .15s var(--isql-ease); }
[data-testid="stFileUploaderDropzone"]:hover { border-color: var(--isql-primary);
  background: color-mix(in srgb, var(--isql-primary) 6%, var(--isql-glass)); }
[data-testid="stForm"] { border-color: var(--isql-border); border-radius: var(--isql-radius-lg); }  /* usually inside a card */

/* Alerts: rounded, with a coloured edge (the icon and text still say what kind of message it is) */
[data-testid="stAlertContainer"] { border-radius: var(--isql-radius-md); border: 1px solid color-mix(in srgb, currentColor 22%, transparent); }

/* Popovers and select menus float above the page as solid-enough glass */
[data-testid="stPopoverBody"], [data-baseweb="popover"] [role="listbox"] { background: var(--isql-popover);
  -webkit-backdrop-filter: blur(var(--isql-blur)); backdrop-filter: blur(var(--isql-blur)); }

/* KPI values: never cut off ("$283,700.56" fits four cards on a laptop) */
[data-testid="stMetricValue"] { font-size: clamp(1.3rem, .9rem + 1vw, 1.75rem); }
[data-testid="stMetricValue"] > div { overflow: visible; text-overflow: clip; }
[data-testid="stMetricLabel"] p { color: var(--isql-muted); }

/* Keyboard focus: one visible ring everywhere */
.stApp a:focus-visible, .stApp button:focus-visible, .stApp summary:focus-visible, .stApp [role="tab"]:focus-visible,
.isql-theme-toggle:focus-visible {
  outline: var(--isql-focus-width) solid var(--isql-primary); outline-offset: 2px; }

@keyframes isql-rise { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition: none !important; }
}

/* Less transparency requested: solid surfaces, no blur */
@media (prefers-reduced-transparency: reduce) {
  :root, :root[data-isql-theme] { --isql-glass: var(--isql-surface); --isql-glass-strong: var(--isql-surface);
    --isql-popover: var(--isql-surface); --isql-blur: 0px; }
  .stApp { background-image: none; }
}

/* More contrast requested: firmer borders */
@media (prefers-contrast: more) {
  :root, :root[data-isql-theme] { --isql-border: var(--isql-widget-border); --isql-glass-border: var(--isql-widget-border); }
}

/* Windows high-contrast mode: the switch keeps a visible outline and state */
@media (forced-colors: active) {
  .isql-theme-toggle-track { border-color: CanvasText; }
  .isql-theme-toggle[aria-checked="true"] .isql-theme-toggle-track { background: Highlight; }
  .isql-theme-toggle-thumb { background: CanvasText; }
}
"""

# Runs in the page (Streamlit does not re-run Python when the theme changes in the browser):
# 1. marks <html data-isql-theme> from the app's real background and keeps it current;
# 2. keeps the "Dark mode" switch (theme_toggle) in step with the theme;
# 3. switches the theme by choosing Light or Dark in Streamlit's own (hidden) main menu, so
#    nothing reloads and no Python code, query or AI request runs;
# 4. remembers the choice in this browser (THEME_STORAGE_KEY), and starts in light the first time.
#    Streamlit's own saved choice is per start page, so it is written for every page in the
#    navigation too: a later visit to any page then starts in the chosen theme without a flash.
THEME_STORAGE_KEY = "isql-theme"
THEME_SCRIPT = """<script>
(() => {
  const doc = document, root = doc.documentElement;
  const app = doc.querySelector('.stApp');
  if (!app) return;
  const KEY = '%(key)s';
  const mode = () => {
    const rgb = (getComputedStyle(app).backgroundColor.match(/[\\d.]+/g) || [255, 255, 255]).map(Number);
    const lum = (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255;
    return lum < 0.5 ? 'dark' : 'light';
  };
  const sync = () => {
    const m = mode();
    if (root.getAttribute('data-isql-theme') !== m) root.setAttribute('data-isql-theme', m);
    doc.querySelectorAll('[data-isql-theme-toggle]').forEach((t) => t.setAttribute('aria-checked', String(m === 'dark')));
    root.setAttribute('data-isql-theme-switch', doc.querySelector('[data-testid=stMainMenu] button') ? 'ready' : 'unavailable');
  };
  const saved = () => { try { return localStorage.getItem(KEY); } catch (e) { return null; } };
  const remember = (m) => {
    try {
      localStorage.setItem(KEY, m);
      const value = JSON.stringify(m === 'dark' ? 'Dark' : 'Light');
      const links = [...doc.querySelectorAll('[data-testid=stSidebarNavLink]')].map((a) => new URL(a.href).pathname);
      new Set([location.pathname, ...links]).forEach((p) => localStorage.setItem('stActiveTheme-' + p + '-v2', value));
    } catch (e) { /* storage blocked: the choice lasts for this visit only */ }
  };
  const later = (find, then, tries = 40) => {
    const found = find();
    if (found) then(found); else if (tries > 0) requestAnimationFrame(() => later(find, then, tries - 1));
  };
  const choose = (m, focusBack) => {
    const menu = doc.querySelector('[data-testid=stMainMenu] button');
    if (!menu) return;
    if (mode() === m) { remember(m); return; }
    menu.click();
    later(() => doc.querySelector('[data-testid=stMainMenuItem-theme-' + (m === 'dark' ? 'Dark' : 'Light') + ']'), (item) => {
      item.click();
      later(() => !doc.querySelector('[data-testid=stMainMenuPopover]') || mode() === m, () => {
        if (doc.querySelector('[data-testid=stMainMenuPopover]')) menu.click();
        remember(m);
        sync();
        if (focusBack) focusBack.focus();
      });
    });
  };
  sync();
  if (!root.isqlTheme) {
    root.isqlTheme = true;
    new MutationObserver(sync).observe(app, {attributes: true, attributeFilter: ['class', 'style']});
    // A rerun can redraw the switch with the theme Python saw (which may be stale): correct it.
    let queued = false;
    new MutationObserver(() => {
      if (queued) return;
      queued = true;
      requestAnimationFrame(() => {
        queued = false;
        const dark = String(root.getAttribute('data-isql-theme') === 'dark');
        doc.querySelectorAll('[data-isql-theme-toggle]').forEach((t) => {
          if (t.getAttribute('aria-checked') !== dark) t.setAttribute('aria-checked', dark);
        });
      });
    }).observe(doc.body, {childList: true, subtree: true});
    doc.addEventListener('click', (event) => {
      const toggle = event.target.closest && event.target.closest('[data-isql-theme-toggle]');
      if (toggle) choose(toggle.getAttribute('aria-checked') === 'true' ? 'light' : 'dark', toggle);
    });
    later(() => doc.querySelector('[data-testid=stMainMenu] button'), () => { sync(); choose(saved() === 'dark' ? 'dark' : 'light'); });
  }
})();
</script>""" % {"key": THEME_STORAGE_KEY}

def theme_toggle() -> None:
    """The "Dark mode" switch (sidebar). Clicking it switches the theme in the browser only:
    no rerun, so answers, filters and other session state stay as they are."""
    checked = "true" if current_mode() == "dark" else "false"
    st.html(f'<button type="button" class="isql-theme-toggle" role="switch" aria-checked="{checked}" '
            f'data-isql-theme-toggle title="Switch between the light and the dark theme">'
            f'<span class="isql-theme-toggle-label">Dark mode</span>'
            f'<span class="isql-theme-toggle-track" aria-hidden="true"><span class="isql-theme-toggle-thumb"></span></span>'
            f'</button>')


def css(initial: str | None = None) -> str:
    """The complete style block; ``initial`` is the theme to assume until the script runs."""
    return f"<style>\n{_token_css(initial or current_mode())}{CSS}</style>"


def inject_css() -> None:
    """Add the styles and the theme marker script to the page (call once per run)."""
    st.html(css())
    st.html(THEME_SCRIPT, unsafe_allow_javascript=True)


BADGE_STYLES = {
    "success": ("ok", "✓", "Success"),
    "rejected": ("warn", "⛔", "Rejected"),
    "error": ("error", "✕", "Failed"),
    "info": ("info", "●", ""),
    "muted": ("muted", "○", ""),
    "warning": ("warn", "!", ""),
}


def badge(kind: str, text: str | None = None) -> str:
    """HTML for a status badge. ``text`` is escaped; the icon makes status readable without colour."""
    style, icon, default = BADGE_STYLES[kind]
    label = html.escape(text if text is not None else default)
    return f'<span class="isql-badge isql-badge--{style}"><span aria-hidden="true">{icon}</span>{label}</span>'


def page_header(eyebrow: str, title: str, subtitle: str, badge_html: str = "") -> None:
    """Consistent page heading. Text is escaped; ``badge_html`` comes from ``badge()``."""
    st.html(
        f'<div class="isql-header"><p class="isql-eyebrow">{html.escape(eyebrow)}</p>'
        f'<h1 class="isql-title">{html.escape(title)}</h1>'
        f'<p class="isql-subtitle">{html.escape(subtitle)}</p>'
        f'{f"<div style=margin-top:.7rem>{badge_html}</div>" if badge_html else ""}</div>'
    )


def empty_state(title: str, body: str) -> None:
    st.html(f'<div class="isql-empty"><strong>{html.escape(title)}</strong>{html.escape(body)}</div>')


def chart_config(mode: str | None = None) -> dict:
    """Vega-Lite config matching the theme Python sees. Text and line colours are also set by CSS
    (``CSS`` above), so they follow a theme switch in the browser without a redraw."""
    t = THEMES[mode or current_mode()]
    return {
        "background": "transparent",
        "font": "Inter, sans-serif",
        "view": {"stroke": "transparent"},
        "title": {"color": t["text"], "fontSize": 14, "fontWeight": 600, "anchor": "start", "offset": 12},
        "axis": {
            "labelColor": t["chart_label"], "titleColor": t["chart_label"], "gridColor": t["chart_grid"],
            "domainColor": t["widget_border"], "tickColor": t["widget_border"], "labelFontSize": 12,
            "titleFontSize": 12, "titleFontWeight": 500, "labelLimit": 180,
        },
        "legend": {"labelColor": t["chart_label"], "titleColor": t["chart_label"]},
        "range": {"category": CHART_COLORS},
    }
