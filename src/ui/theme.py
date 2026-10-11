"""Design tokens, the small amount of custom CSS, and the chart theme.

Most of the theme (colours, fonts, radii, borders, sidebar) is set natively in
``.streamlit/config.toml``. The CSS here only styles elements the app itself creates:
it targets the ``st-key-<key>`` classes Streamlit adds to keyed containers and widgets,
and InsightSQL's own ``isql-*`` classes — not Streamlit's internal markup.
"""

import html

import streamlit as st

# Mirrors .streamlit/config.toml.
COLORS = {
    "bg": "#0B1020",
    "surface": "#141B2E",
    "surface_raised": "#18213A",
    "border": "#252E4A",
    "text": "#E6E8F2",
    "muted": "#9AA3BC",
    "violet": "#8B5CF6",
    "violet_soft": "#A78BFA",
    "cyan": "#22D3EE",
    "success": "#34D399",
    "warning": "#FBBF24",
    "error": "#F87171",
}

CSS = """
<style>
:root {
  --isql-surface: %(surface)s; --isql-raised: %(surface_raised)s; --isql-border: %(border)s;
  --isql-text: %(text)s; --isql-muted: %(muted)s; --isql-violet: %(violet)s;
  --isql-violet-soft: %(violet_soft)s; --isql-cyan: %(cyan)s;
  --isql-success: %(success)s; --isql-warning: %(warning)s; --isql-error: %(error)s;
  --isql-ease: cubic-bezier(.2, .8, .2, 1);
}

/* Page header */
.isql-eyebrow { color: var(--isql-cyan); font-size: .78rem; font-weight: 600;
  letter-spacing: .08em; text-transform: uppercase; margin: 0 0 .35rem; }
.isql-title { font-size: clamp(1.6rem, 2.6vw, 2.15rem); font-weight: 700; line-height: 1.2;
  margin: 0 0 .4rem; letter-spacing: -.01em;
  background: linear-gradient(90deg, var(--isql-text) 0%%, var(--isql-violet-soft) 60%%, var(--isql-cyan) 100%%);
  -webkit-background-clip: text; background-clip: text; color: transparent; }
.isql-subtitle { color: var(--isql-muted); font-size: .98rem; max-width: 46rem; margin: 0; }

/* Status badges: icon + word, never colour alone */
.isql-badge { display: inline-flex; align-items: center; gap: .35rem; padding: .18rem .6rem;
  border-radius: 999px; font-size: .78rem; font-weight: 600; border: 1px solid; white-space: nowrap; }
.isql-badge--ok { color: var(--isql-success); border-color: rgba(52,211,153,.35); background: rgba(52,211,153,.08); }
.isql-badge--warn { color: var(--isql-warning); border-color: rgba(251,191,36,.35); background: rgba(251,191,36,.08); }
.isql-badge--error { color: var(--isql-error); border-color: rgba(248,113,113,.35); background: rgba(248,113,113,.08); }
.isql-badge--info { color: var(--isql-violet-soft); border-color: rgba(139,92,246,.4); background: rgba(139,92,246,.1); }
.isql-badge--muted { color: var(--isql-muted); border-color: var(--isql-border); background: transparent; }
.isql-meta { color: var(--isql-muted); font-size: .82rem; }

/* Cards: KPI, chart and list containers (keys start with kpi_, chart_, hist_, card_) */
[class*="st-key-kpi_"], [class*="st-key-chart_"], [class*="st-key-hist_"], [class*="st-key-card_"] {
  background: linear-gradient(180deg, var(--isql-raised) 0%%, var(--isql-surface) 100%%);
  box-shadow: 0 1px 2px rgba(0,0,0,.25), 0 8px 24px -12px rgba(0,0,0,.5);
  transition: border-color .2s var(--isql-ease), transform .2s var(--isql-ease), box-shadow .2s var(--isql-ease);
  animation: isql-rise .35s var(--isql-ease) both;
}
[class*="st-key-kpi_"]:hover, [class*="st-key-hist_"]:hover, [class*="st-key-card_"]:hover {
  border-color: rgba(139,92,246,.55); transform: translateY(-2px);
  box-shadow: 0 1px 2px rgba(0,0,0,.25), 0 14px 28px -14px rgba(139,92,246,.35);
}
[class*="st-key-kpi_"] { border-top: 2px solid rgba(139,92,246,.7) !important; }

/* Chat turns fade in */
[class*="st-key-turn_"] { animation: isql-rise .3s var(--isql-ease) both; }

/* Empty states */
.isql-empty { text-align: center; padding: 2.2rem 1rem; color: var(--isql-muted);
  border: 1px dashed var(--isql-border); border-radius: .75rem; }
.isql-empty strong { display: block; color: var(--isql-text); font-size: 1.02rem; margin-bottom: .3rem; }

/* Sidebar status card */
.isql-status { border: 1px solid var(--isql-border); border-radius: .75rem; padding: .7rem .8rem;
  background: rgba(20,27,46,.6); font-size: .82rem; color: var(--isql-muted); line-height: 1.5; }
.isql-status b { color: var(--isql-text); font-weight: 600; }
.isql-version { color: var(--isql-muted); font-size: .75rem; margin-top: .5rem; }
.isql-account { font-size: .82rem; color: var(--isql-muted); line-height: 1.6; margin-bottom: .4rem;
  overflow-wrap: anywhere; }
.isql-account b { color: var(--isql-text); font-weight: 600; }
.isql-account-email { display: block; }

@keyframes isql-rise { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition: none !important; }
}
</style>
""" % COLORS


def inject_css() -> None:
    """Add the custom styles to the page (call once per run)."""
    st.html(CSS)


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


def chart_config() -> dict:
    """Vega-Lite config for a dark, readable chart that matches the app theme."""
    c = COLORS
    return {
        "background": "transparent",
        "font": "Inter, sans-serif",
        "view": {"stroke": "transparent"},
        "title": {"color": c["text"], "fontSize": 14, "fontWeight": 600, "anchor": "start", "offset": 12},
        "axis": {
            "labelColor": c["muted"], "titleColor": c["muted"], "gridColor": "#1E2640",
            "domainColor": c["border"], "tickColor": c["border"], "labelFontSize": 12,
            "titleFontSize": 12, "titleFontWeight": 500, "labelLimit": 180,
        },
        "legend": {"labelColor": c["muted"], "titleColor": c["muted"]},
        "range": {"category": [c["violet"], c["cyan"], "#F472B6", c["success"], c["warning"], "#60A5FA"]},
    }
