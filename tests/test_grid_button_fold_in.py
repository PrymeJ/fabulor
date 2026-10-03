"""_resolve_ramp_grid_button_style + End of chapter/Set's fold-in to the
preset ramp's own background (pure, headless).

THE BUG, two independent causes (live-reported with 5 theme screenshots,
2026-10-03: Sunspear, Driftmark, Dorian Gray, Camorr, Fire and Blood):

1. End of chapter/Set used the generic QPushButton rule's `accent_style`
   (`_get_gradient_style`), which paints a REAL GRADIENT whenever a theme
   sets `gradient_accent_start`/`gradient_accent_end` — while the preset
   ramp sitting right next to them (`preset_ramp_rgb`) is always a flat
   blended color, never a gradient. A theme with gradient keys therefore
   showed a gradiented button beside a flat one. Confirmed discordant on
   Sunspear and Dorian Gray (both have gradient keys); confirmed fine on
   Driftmark (Pryme explicitly wanted to KEEP that gradient there) and
   acceptable on Fire and Blood.

2. A SEPARATE cause on themes with NO gradient keys at all: a theme's
   `preset_ramp_bright_end` override only ever fed the ramp's own background
   and `button_text_for_accent` — never these two buttons, which kept
   painting flat `accent` regardless. Found live on "Gravity's Rainbow"
   (accent=#00FF00, preset_ramp_bright_end=#E4DA42 — a genuine color
   mismatch, no gradient involved at all).

Fixed by folding both buttons' background into `_resolve_ramp_bright_end`'s
own resolution (the SAME chain the ramp's own brightest step already uses:
override, then darker gradient endpoint, then flat accent) — reusing it
rather than inventing a second resolution, so the two can never drift apart
again (same "sync" concern `_resolve_ramp_bright_end`'s own extraction note
documents). `preset_ramp_grid_buttons_keep_default` opts a theme OUT,
checked live theme-by-theme by Pryme: Gravity's Rainbow, Shade of the
Evening, Driftmark — each judged to look BETTER with the old accent_style
there than folded in.

THE MISSED PANEL (same day, found live): the first version of this fix
added the rule to `get_settings_stylesheet` and `get_sprint_stylesheet` —
but `get_settings_stylesheet` styles the SETTINGS TAB's own panel, not
Sleep's. Sleep has its OWN dedicated `get_sleep_stylesheet` function
(`theme_manager.py`'s `'sleep_panel': get_sleep_stylesheet(theme_name)`),
which was missed entirely — confirmed live when Dorian Gray/Sunspear/
Camorr's Sleep panel still showed the old, un-folded-in background after
the first fix shipped ("Nope. The screenshots I gave is with your most
recent changes" — ruled out staleness, traced to the wrong function). Fixed
by adding the identical rule to `get_sleep_stylesheet` too. Tests below
check `get_sleep_stylesheet` (the function that actually matters for the
live Sleep panel) and `get_sprint_stylesheet`; `get_settings_stylesheet` is
checked separately only because it happens to share the same rule (Settings
tab has no End of chapter/Set of its own, so this is incidental, not load-
bearing for the live bug).
"""
from fabulor.themes import (
    THEMES,
    _resolve_ramp_bright_end,
    _resolve_ramp_grid_button_style,
    _resolve_theme,
    get_sleep_stylesheet,
    get_sprint_stylesheet,
)

FOLDED_IN_THEMES = ["Sunspear", "Dorian Gray", "Camorr", "Fire and Blood"]
OPTED_OUT_THEMES = ["Gravity's Rainbow", "Shade of the Evening", "Driftmark"]


def test_opted_out_themes_are_flagged():
    for name in OPTED_OUT_THEMES:
        assert THEMES[name].get("preset_ramp_grid_buttons_keep_default") is True, name


def test_folded_in_themes_are_not_flagged():
    for name in FOLDED_IN_THEMES:
        assert not THEMES[name].get("preset_ramp_grid_buttons_keep_default"), name


def test_resolve_ramp_grid_button_style_folds_in_by_default():
    t = _resolve_theme("Sunspear")
    accent_style = "qlineargradient(...)"  # arbitrary placeholder — must be ignored when folding in
    result = _resolve_ramp_grid_button_style(t, accent_style)
    assert result == _resolve_ramp_bright_end(t)
    assert result != accent_style


def test_resolve_ramp_grid_button_style_opt_out_returns_accent_style_unchanged():
    t = _resolve_theme("Driftmark")
    accent_style = "qlineargradient(some, specific, gradient, string)"
    result = _resolve_ramp_grid_button_style(t, accent_style)
    assert result == accent_style


def test_gravitys_rainbow_mismatch_is_fixed_when_not_opted_out():
    # Direct repro of the SECOND cause (no gradient keys at all): confirms
    # that WITHOUT the opt-out, Gravity's Rainbow's own accent (#00FF00)
    # would have diverged from its preset_ramp_bright_end override
    # (#E4DA42) — proving the fold-in fixes a real mismatch, not a
    # hypothetical one, which is why Pryme was asked to confirm the opt-out
    # was deliberate rather than assumed necessary.
    raw = THEMES["Gravity's Rainbow"]
    t = _resolve_theme("Gravity's Rainbow")
    assert raw.get("gradient_accent_start") is None, "fixture assumption: no gradient keys"
    assert t["accent"] != _resolve_ramp_bright_end(t), (
        "accent and the ramp's own bright end must genuinely differ for this test to mean anything"
    )


def test_get_sleep_stylesheet_eoc_set_rule_matches_ramp_bright_end_for_folded_in_themes():
    # get_sleep_stylesheet is the function that actually backs the live
    # Sleep panel (theme_manager.py: 'sleep_panel': get_sleep_stylesheet(...))
    # — this is the function the original fix MISSED, see the module
    # docstring's "THE MISSED PANEL" section.
    for name in FOLDED_IN_THEMES:
        t = _resolve_theme(name)
        s = get_sleep_stylesheet(name)
        expected = _resolve_ramp_bright_end(t)
        assert f"background: {expected};" in s, f"{name}: expected EOC/Set background {expected} not found"


def test_get_sleep_stylesheet_eoc_set_rule_preserves_accent_style_for_opted_out_themes():
    from fabulor.themes import _get_gradient_style
    for name in OPTED_OUT_THEMES:
        t = _resolve_theme(name)
        s = get_sleep_stylesheet(name)
        expected = _get_gradient_style(t, "accent", t['accent'])
        assert f"background: {expected};" in s, f"{name}: expected unchanged accent_style not found"


def test_get_sprint_stylesheet_mirrors_sleep_stylesheet():
    for name in FOLDED_IN_THEMES + OPTED_OUT_THEMES:
        t = _resolve_theme(name)
        sleep_s = get_sleep_stylesheet(name)
        sprint_s = get_sprint_stylesheet(name)
        import re
        pattern = r"QPushButton#panel_grid_eoc_btn, QPushButton#panel_grid_set_btn \{[^}]*background: ([^;]+);"
        m1 = re.search(pattern, sleep_s)
        m2 = re.search(pattern, sprint_s)
        assert m1 and m2, name
        assert m1.group(1) == m2.group(1), f"{name}: Sleep and Sprint disagree on EOC/Set background"


def test_fold_in_is_byte_for_byte_a_no_op_for_themes_with_no_relevant_keys():
    # A theme with neither gradient_accent_* nor preset_ramp_bright_end nor
    # the opt-out flag should fold in to plain accent — i.e. look identical
    # to before this fix existed (accent_style's own flat-accent fallback).
    candidates = [
        name for name, raw in THEMES.items()
        if not raw.get("gradient_accent_start")
        and not raw.get("preset_ramp_bright_end")
        and not raw.get("preset_ramp_grid_buttons_keep_default")
    ]
    assert candidates, "expected at least one theme with none of these keys set"
    name = candidates[0]
    t = _resolve_theme(name)
    s = get_sleep_stylesheet(name)
    assert f"background: {t['accent']};" in s
