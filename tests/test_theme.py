"""UI theme (redesign): exact palette, light and dark tokens, config.toml in step with theme.py,
WCAG contrast of every text and control pair, CSS for both themes, the dark-mode switch and its
script, logo colours, accessibility preferences, chart colours.

The switch's behaviour in a real browser is tested in tests/test_app_e2e.py."""

import re
import tomllib
from pathlib import Path

import pytest

from src.ui import charts, theme

ROOT = Path(__file__).resolve().parent.parent
CONFIG = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text())["theme"]
OLD_DARK_THEME = ("#8B5CF6", "#22D3EE", "#0B1020", "#141B2E", "#A78BFA", "#F472B6", "#080C18")


def luminance(colour: str) -> float:
    channels = [int(colour.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_contrast_helper_matches_known_values():
    assert contrast("#000000", "#FFFFFF") == pytest.approx(21.0)
    assert contrast("#4A70A9", "#FFFFFF") == pytest.approx(5.02, abs=0.01)


# --- Palette ---------------------------------------------------------------------------

def test_palette_is_exactly_the_four_requested_colours():
    assert theme.PALETTE == {"off_white": "#EFECE3", "soft_blue": "#8FABD4", "primary": "#4A70A9",
                             "black": "#000000"}


def test_palette_roles():
    assert theme.LIGHT["bg"] == "#EFECE3" and theme.LIGHT["text"] == "#000000"
    assert theme.LIGHT["primary"] == theme.DARK["primary"] == "#4A70A9"
    assert theme.LIGHT["soft"] == theme.DARK["soft"] == "#8FABD4"
    assert theme.DARK["text"] == "#EFECE3" and theme.DARK["accent_text"] == "#8FABD4"
    assert theme.CHART_COLORS[0] == "#4A70A9"


def test_light_is_the_default_base_theme():
    assert CONFIG["base"] == "light"


# --- config.toml and theme.py agree -----------------------------------------------------

CONFIG_KEYS = {
    "backgroundColor": "bg", "secondaryBackgroundColor": "surface", "textColor": "text",
    "primaryColor": "primary", "linkColor": "accent_text", "borderColor": "widget_border",
    "dataframeBorderColor": "widget_border", "dataframeHeaderBackgroundColor": "table_header",
    "dataframeHeaderTextColor": "table_header_text", "codeBackgroundColor": "surface", "codeTextColor": "code_text",
    "greenColor": "success", "greenTextColor": "success", "yellowColor": "warning", "yellowTextColor": "warning",
    "redColor": "error", "redTextColor": "error", "blueColor": "primary", "blueTextColor": "accent_text",
    "violetColor": "primary", "violetTextColor": "accent_text",
    "greenBackgroundColor": "success_bg", "yellowBackgroundColor": "warning_bg", "redBackgroundColor": "error_bg",
    "blueBackgroundColor": "info_bg", "violetBackgroundColor": "info_bg",
}


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_config_matches_tokens(mode):
    section, tokens = CONFIG[mode], theme.THEMES[mode]
    for key, token in CONFIG_KEYS.items():
        assert section[key].upper() == tokens[token].upper(), (mode, key)
    assert section["sidebar"] == {"backgroundColor": tokens["sidebar"], "secondaryBackgroundColor": tokens["sidebar_surface"]}
    assert section["chartCategoricalColors"] == theme.CHART_COLORS


def test_no_colour_of_the_old_dark_theme_remains():
    sources = [ROOT / ".streamlit" / "config.toml", *sorted((ROOT / "src" / "ui").glob("*.py"))]
    for path in sources:
        text = path.read_text().upper()
        for old in OLD_DARK_THEME:
            assert old not in text, f"{old} still in {path.name}"


def test_ui_code_has_no_hard_coded_colours_outside_the_theme():
    for path in sorted((ROOT / "src" / "ui").glob("*.py")):
        if path.name == "theme.py":
            continue
        found = set(re.findall(r"#[0-9A-Fa-f]{6}\b", path.read_text())) - {"#FFFFFF"}  # pie gap, reset by CSS
        assert not found, f"{path.name}: {found}"


# --- Contrast (WCAG 2.1: text 4.5:1, controls and chart marks 3:1) ----------------------

TEXT_ON = {"text": ("bg", "surface", "sidebar", "sidebar_surface"), "muted": ("bg", "surface", "sidebar"),
           "accent_text": ("bg", "surface", "sidebar"), "success": ("bg", "surface"), "warning": ("bg", "surface"),
           "error": ("bg", "surface"), "chart_label": ("bg", "surface"), "code_text": ("surface",),
           "table_header_text": ("table_header",)}


@pytest.mark.parametrize("mode", ["light", "dark"])
@pytest.mark.parametrize("token, backgrounds", TEXT_ON.items())
def test_text_contrast(mode, token, backgrounds):
    tokens = theme.THEMES[mode]
    for background in backgrounds:
        assert contrast(tokens[token], tokens[background]) >= 4.5, (mode, token, background)


@pytest.mark.parametrize("mode", ["light", "dark"])
@pytest.mark.parametrize("status, text", [("success", "success"), ("warning", "warning"), ("error", "error"),
                                          ("info", "accent_text")])
def test_alert_and_badge_text_on_their_backgrounds(mode, status, text):
    t = theme.THEMES[mode]
    assert contrast(t[text], t[f"{status}_bg"]) >= 4.5  # the coloured status text
    assert contrast(t["text"], t[f"{status}_bg"]) >= 4.5  # the message itself


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_controls_contrast(mode):
    t = theme.THEMES[mode]
    assert contrast(t["on_primary"], t["primary"]) >= 4.5  # button text
    assert contrast(t["primary"], t["bg"]) >= 3  # primary buttons, focus rings, selected states
    for background in ("bg", "surface"):
        assert contrast(t["widget_border"], t[background]) >= 3, (mode, background)  # input outlines


@pytest.mark.parametrize("colour", theme.CHART_COLORS)
def test_chart_colours_are_visible_on_both_themes(colour):
    assert contrast(colour, theme.LIGHT["bg"]) >= 3
    assert contrast(colour, theme.DARK["bg"]) >= 3


def test_primary_button_hover_darkens_in_both_themes():
    # A hover mixed towards the (light) dark-theme text colour would wash out the white label.
    assert "color-mix(in srgb, var(--isql-primary) 86%, black)" in theme.CSS
    hover = "#" + "".join(f"{round(int(theme.PALETTE['primary'][i:i + 2], 16) * .86):02X}" for i in (1, 3, 5))
    assert contrast("#FFFFFF", hover) >= 4.5


def test_light_text_on_white_glass_cards():
    for token in ("text", "muted", "accent_text", "success", "warning", "error"):
        assert contrast(theme.LIGHT[token], "#FFFFFF") >= 4.5, token


# --- CSS -------------------------------------------------------------------------------

def test_css_defines_every_token_for_both_themes():
    css = theme.css("light")
    for mode, tokens in theme.THEMES.items():
        block = re.search(rf':root\[data-isql-theme="{mode}"\] \{{(.*?)\}}', css).group(1)
        for name, value in tokens.items():
            assert f"--isql-{name.replace('_', '-')}: {value};" in block, (mode, name)


@pytest.mark.parametrize("initial", ["light", "dark"])
def test_until_the_script_runs_the_theme_python_saw_applies(initial):
    first = re.search(r":root \{(.*?)\}", theme.css(initial)).group(1)
    assert f"--isql-bg: {theme.THEMES[initial]['bg']};" in first
    assert "--isql-radius-md: .75rem;" in first and "--isql-blur: 14px;" in first


def test_css_rules_use_tokens_not_colours():
    rules = theme.CSS
    assert not re.findall(r"#[0-9A-Fa-f]{3,6}\b", rules)
    assert not re.findall(r"rgba?\(", rules)


def test_reduced_motion_is_respected():
    assert "prefers-reduced-motion: reduce" in theme.CSS


def test_theme_script_marks_the_page_and_follows_changes():
    script = theme.THEME_SCRIPT
    assert "data-isql-theme" in script and "MutationObserver" in script


def test_theme_script_switches_without_reload_or_network():
    script = theme.THEME_SCRIPT
    for forbidden in ("fetch(", "XMLHttpRequest", "WebSocket", "reload(", "location.href =", "eval("):
        assert forbidden not in script, forbidden
    # Uses Streamlit's own theme items, and stores only the theme choice.
    assert "stMainMenuItem-theme-" in script
    keys = set(re.findall(r"localStorage\.setItem\(([^,]+),", script))
    assert keys == {"KEY", "'stActiveTheme-' + p + '-v2'"}
    assert f"const KEY = '{theme.THEME_STORAGE_KEY}';" in script


def test_first_visit_defaults_to_light():
    # Anything but a saved "dark" choice means light.
    assert "choose(saved() === 'dark' ? 'dark' : 'light')" in theme.THEME_SCRIPT


def test_theme_toggle_is_an_accessible_switch(monkeypatch):
    rendered = []
    monkeypatch.setattr(theme.st, "html", rendered.append)
    theme.theme_toggle()
    (markup,) = rendered
    assert '<button type="button"' in markup and 'role="switch"' in markup
    assert 'aria-checked="false"' in markup  # light outside a running app
    assert ">Dark mode</span>" in markup and "data-isql-theme-toggle" in markup
    assert '<span class="isql-theme-toggle-track" aria-hidden="true">' in markup


def test_streamlit_menu_is_available_to_the_switch_but_hidden():
    config = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text())
    assert config["client"]["toolbarMode"] == "viewer"  # "minimal" has no theme items
    assert '[data-testid="stMainMenu"], [data-testid="stMainMenuPopover"] { display: none !important; }' in theme.CSS


def test_accessibility_preferences_are_respected():
    css = theme.CSS
    assert "prefers-reduced-transparency: reduce" in css and "--isql-blur: 0px" in css
    assert "prefers-contrast: more" in css and "forced-colors: active" in css
    assert ":focus-visible" in css


def composite(rgba: str, background: str) -> str:
    """An rgba() colour drawn over a solid background, as #RRGGBB."""
    *rgb, alpha = (float(x) for x in re.findall(r"[\d.]+", rgba))
    base = [int(background.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(f"{round(c * alpha + b * (1 - alpha)):02X}" for c, b in zip(rgb, base))


@pytest.mark.parametrize("mode", ["light", "dark"])
@pytest.mark.parametrize("layer", ["glass", "glass_strong", "popover"])
def test_text_on_glass_layers(mode, layer):
    t = theme.THEMES[mode]
    for under in ("bg", "surface"):  # whatever the glass floats over
        fill = composite(t[layer], t[under])
        for token in ("text", "muted", "accent_text"):
            assert contrast(t[token], fill) >= 4.5, (mode, layer, under, token)


# --- Logo and icon ---------------------------------------------------------------------

@pytest.mark.parametrize("name", ["logo.svg", "icon.svg"])
def test_logo_uses_only_the_palette(name):
    svg = (ROOT / "assets" / name).read_text().upper()
    assert set(re.findall(r"#[0-9A-F]{6}", svg)) <= {c.upper() for c in theme.PALETTE.values()}
    assert not any(old in svg for old in OLD_DARK_THEME)


def test_logo_text_is_readable_on_both_sidebars():
    fill = re.search(r'<text [^>]*fill="(#[0-9A-Fa-f]{6})"', (ROOT / "assets" / "logo.svg").read_text()).group(1)
    for mode in ("light", "dark"):
        assert contrast(fill, theme.THEMES[mode]["sidebar"]) >= 3  # 20 px bold: large text


def test_current_mode_defaults_to_light_outside_a_running_app():
    assert theme.current_mode() == "light"


# --- Charts ----------------------------------------------------------------------------

@pytest.mark.parametrize("mode", ["light", "dark"])
def test_chart_config_follows_the_theme(mode):
    config, tokens = theme.chart_config(mode), theme.THEMES[mode]
    assert config["axis"]["labelColor"] == tokens["chart_label"]
    assert config["axis"]["gridColor"] == tokens["chart_grid"]
    assert config["title"]["color"] == tokens["text"]
    assert config["range"]["category"] == theme.CHART_COLORS


def test_charts_use_the_shared_chart_colours():
    assert charts.PRIMARY == "#4A70A9" and charts.SECONDARY in theme.CHART_COLORS
