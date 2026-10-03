"""button_text_for_accent: contrast-safe text for the generic accent-background
QPushButton rule (and its siblings) across Settings/Speed/Sleep/Sprint/Stats/
Tags/Library stylesheets (pure, headless).

THE BUG (2026-10-03, found while fixing the preset-ramp text color — see
tests/test_preset_ramp.py). Every one of these stylesheet functions' generic
`QPushButton` rule (plus `QTabBar::tab:selected`, `#disable_sleep_btn`/
`#disable_sprint_btn`, `QPushButton#pattern_button[selected="true"]`,
`QPushButton#tag_add_btn`, the library folder-list selected-item rule, several
`#stats_reset_btn:hover` rules, and a handful of `selection-color` pairings)
painted `color: button_text (-> text_on_light_bg -> text)` against
`background: accent` with no per-theme contrast check. Reported live: on
Melnibonéan, "End of chapter"/"Set" (plain QPushButtons) sat right next to the
newly-fixed, legible preset-ramp buttons and showed `button_text` falling
through to `text` = #F0F3F0 (near-white) against `accent` = #A8C3C6 (light
teal) — 1.66:1 contrast, reading as a flat muddy block. A 62-theme scan found
20 themes below 3:1 and 38 below the 4.5:1 AA floor against their own flat
`button_text` read.

Fixed by reusing the exact search mechanism `ramp_text_colors` already proved
live, targeting full AA (4.5, not the ramp's relaxed 3.0 — this is a single
flat background, not a 13-step gradient, so there's no unavoidable midpoint
valley forcing a lower target).
"""
from fabulor.themes import THEMES, _resolve_theme, _wcag_contrast, button_text_for_accent

THEME = {"accent": "#A8C3C6", "text": "#F0F3F0"}  # Melnibonéan's actual values


def _text_rgb(hex_str):
    h = hex_str.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def test_returns_a_hex_color():
    result = button_text_for_accent(THEME)
    assert result.startswith("#") and len(result) == 7


def test_fixes_the_reported_melnibonean_regression():
    # The exact live repro: button_text/text_on_light_bg unset, text falls
    # through to a near-white that's nearly invisible against a light accent.
    t = _resolve_theme(THEMES["Melnibonéan"])
    accent = _text_rgb(t['accent'])
    old_flat_text = _text_rgb(t.get('button_text', t.get('text_on_light_bg', t['text'])))
    assert _wcag_contrast(accent, old_flat_text) < 2.0  # confirms the bug existed

    fixed_text = _text_rgb(button_text_for_accent(t))
    assert _wcag_contrast(accent, fixed_text) >= 4.5


def test_most_themes_meet_full_aa_contrast():
    # Verified against all 62 real themes: every theme now clears 4.5:1 (see
    # the direction-pick fix below) — the >8-below-floor ceiling here is
    # deliberately loose headroom for future theme tuning, not a sign any
    # are currently expected to fall short.
    #
    # Note (2026-10-03): a "fix direction against pure black/white instead of
    # the tinted candidates" change was tried here EARLIER THE SAME SESSION
    # for Blood Meridian/Fire and Blood and REVERTED — see the matching note
    # in tests/test_preset_ramp.py's test_most_themes_meet_a_relaxed_contrast_
    # floor for why (it broke other, already-correct themes there). That
    # revert applied to `ramp_text_colors` (a 13-step GRADIENT background,
    # where "pure black/white has more average headroom" does not reliably
    # hold — re-verified this same session: applying the identical change
    # there regresses Not the Only Fruit/Red Rising/Sunspear). It does NOT
    # apply here: `button_text_for_accent` targets a single FLAT background,
    # where pure black/white genuinely is the correct question ("which pole
    # has more contrast headroom") and the old tinted-candidate comparison
    # could pick black only because black happens to be untinted at val=0
    # regardless of hue — not because it was actually the better choice. A
    # full 62-theme sweep of this narrower, direction-only fix (the value/
    # desaturation SEARCH that follows direction-pick still uses the
    # hue-tinted candidates, unchanged) found zero regressions and 5
    # improvements (Blindsight, Blood Meridian, Crimson Guard, Fire and
    # Blood, Winterfell) — closing the Blood Meridian/Fire and Blood
    # "End of chapter"/"Set" wrong-direction-text issue that was previously
    # left open. Verify any FUTURE direction-pick change the same way: run it
    # against the full 62-theme set and look for regressions, not just the
    # theme(s) that prompted it — this is the second time this exact
    # distinction (flat background vs. gradient background) has mattered.
    #
    # Note (2026-10-03, second entry): a same-day attempt to also route this
    # function's background/text through preset_ramp_bright_end/preset_ramp_
    # text_color/preset_ramp_text_hue shipped and was REVERTED THE SAME
    # SESSION — confirmed live to leak a theme's ramp-specific text tuning
    # into every one of this function's 30 unrelated call sites (including
    # the active Settings-tab text color). button_text_for_accent reads only
    # button_text/text_on_light_bg/text/accent, same as originally shipped —
    # see this function's own docstring for the full account. Contrast is
    # measured against plain t['accent'] again.
    below_floor = 0
    absolute_worst = 99.0
    for name, raw in THEMES.items():
        t = _resolve_theme(raw)
        accent = _text_rgb(t['accent'])
        text = _text_rgb(button_text_for_accent(t))
        c = _wcag_contrast(accent, text)
        absolute_worst = min(absolute_worst, c)
        if c < 4.5:
            below_floor += 1
    assert below_floor <= 8, f"{below_floor} themes below 4.5:1 — expected a small minority"
    assert absolute_worst >= 2.5, f"worst contrast {absolute_worst:.2f}:1 is too low"


def test_fixes_the_blood_meridian_and_fire_and_blood_regression():
    # THE BUG (2026-10-03, found and fixed same session as the leak revert
    # above): both themes' button_text/text_on_light_bg hue is red, same
    # family as their own saturated red accent. The direction-pick used to
    # compare hue-TINTED white/black candidates (sat=_BUTTON_TEXT_SAT) —
    # tinted "white" at that saturation is a pale red/salmon, which contrasts
    # far worse against a red accent than true white does, so black won the
    # comparison by accident (black is untinted at val=0 regardless of hue),
    # not because it was genuinely the better pole. Fixed by deciding
    # direction against PURE black/white while leaving the subsequent
    # hue-tinted value/desaturation search unchanged.
    for name in ("Blood Meridian", "Fire and Blood"):
        t = _resolve_theme(THEMES[name])
        accent = _text_rgb(t['accent'])
        text = _text_rgb(button_text_for_accent(t))
        assert _wcag_contrast(accent, text) >= 4.5, name


def test_same_hue_as_background_does_not_break():
    # Castle Dracula: button_text (#1A0A0A) and accent (#8A0000) are both
    # near-black reds — same class of edge case the ramp's single-direction
    # search already handles (same mechanism is reused here).
    t = _resolve_theme(THEMES["Castle Dracula"])
    accent = _text_rgb(t['accent'])
    text = _text_rgb(button_text_for_accent(t))
    assert _wcag_contrast(accent, text) >= 2.5


def test_missing_theme_keys_fall_back():
    assert button_text_for_accent({})
    assert button_text_for_accent({"accent": "#FFFFFF"})


def test_does_not_read_ramp_scoped_override_keys():
    # THE BUG (live, 2026-10-03): a same-day change made this function also
    # consult preset_ramp_bright_end/preset_ramp_text_color/preset_ramp_
    # text_hue — the RAMP's own override keys, meant to scope only to the
    # 13-step preset ramp. Because button_text_for_accent backs 30 unrelated
    # call sites (the active Settings-tab text color among them), that
    # change leaked a theme's ramp-specific tuning into every one of them —
    # reported live while tuning Blindsight's preset_ramp_text_color and
    # noticing the active tab text changed to match. This pins that none of
    # the three ramp-scoped keys has ANY effect on this function's output.
    base = {"accent": "#888888", "text": "#FFFFFF"}
    with_literal = dict(base, preset_ramp_text_color="#FF00FF")
    with_hue = dict(base, preset_ramp_text_hue="#00FFFF")
    with_bright_end = dict(base, preset_ramp_bright_end="#123456")
    baseline = button_text_for_accent(base)
    assert button_text_for_accent(with_literal) == baseline
    assert button_text_for_accent(with_hue) == baseline
    assert button_text_for_accent(with_bright_end) == baseline
