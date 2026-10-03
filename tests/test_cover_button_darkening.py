"""darken_accent_pair + get_player_stylesheet's cover-art-only button-color
darkening (pure, headless).

THE BUG, AND THE TWO REVERTED ATTEMPTS BEFORE THIS ONE (live, 2026-10-03).
The main transport speed button (and other player-view QPushButtons) use a
flat text/accent chain, deliberately untouched by button_text_for_accent —
see get_player_stylesheet's own QPushButton comment for the full history.
On a cover-art theme (cover_theme.build_cover_theme, unseeded per-launch
jitter), the HOVER state specifically (QPushButton:hover's accent_light
background) could collapse contrast against that same flat text far below
the resting state's — live-measured across real library covers: resting
median contrast 1.76-2.40 vs. hover median consistently 0.5-0.66 LOWER.

Two earlier fixes were tried and reverted the same session:
1. Route the flat text through button_text_for_accent (resting and/or
   hover) — rejected: "the dullest way possible... loses its character."
2. Blend accent_light back toward accent (same shape as safe_ramp_hover_
   factor). Respected "don't flatten text," but on covers where accent
   ITSELF has only marginal contrast against text (confirmed live: "The
   Beam," "Counter-Clock World," "Under the Volcano" — accent and text
   sharing a hue at a similarly high value), the blend search had to go
   almost all the way back to accent to reach target, making the "tamed"
   hover color nearly indistinguishable from the resting background —
   "Hover is gone."

THIS FIX (darken_accent_pair): darkens accent AND accent_light TOGETHER, by
the same HSV-value amount, preserving the gap between them — buying
contrast for both states while keeping the hover highlight visibly
distinct from rest throughout. Confirmed live acceptable by Pryme pointing
at a real example's resting-state buttons (Revolutionary Road's teal) and
explicitly sanctioning touching the button's own color once attempts 1/2
were ruled out: "Subtle highlight is acceptable, but you can also nudge the
button colors a bit... there is not much room to make the text legible [any
other way]." Before shipping, checked against many of Pryme's own real
library covers (not just contrast numbers) for earthy/olive-tone drift —
confirmed acceptable: "A bit but not too bad, I think. Legibility issue is
gone."

These tests use synthetic (accent, accent_light, text) triples shaped like
real cover-theme output — real resolved hex values captured live during the
2026-10-03 investigation on "The Beam (Season One)" (BAD) and "Augustus"
(GOOD) — rather than loading actual cover images (this file stays pure/
headless, no QPixmap/QApplication).
"""
import colorsys

from fabulor.themes import (
    _COVER_BUTTON_HOVER_TARGET_CONTRAST,
    _wcag_contrast,
    darken_accent_pair,
    get_player_stylesheet,
)


def _rgb(hexcolor):
    h = hexcolor.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


# Real resolved (accent, accent_light, text) triples captured live.
BAD_TRIPLE = ("#90B24A", "#AAD458", "#E0EEC6")   # The Beam, a bad roll — accent/text share a hue
GOOD_TRIPLE = ("#B9654E", "#D1744E", "#F2DCC9")  # Augustus, always comfortable


def test_bad_triple_reproduces_the_live_bug_before_darkening():
    accent, accent_light, text = BAD_TRIPLE
    before = _wcag_contrast(_rgb(accent_light), _rgb(text))
    assert before < _COVER_BUTTON_HOVER_TARGET_CONTRAST, "fixture should reproduce a genuinely low hover contrast"


def test_darken_accent_pair_recovers_a_bad_triple():
    accent, accent_light, text = BAD_TRIPLE
    new_accent, new_accent_light = darken_accent_pair(accent, accent_light, text)
    after = _wcag_contrast(_rgb(new_accent_light), _rgb(text))
    assert after >= _COVER_BUTTON_HOVER_TARGET_CONTRAST - 0.05


def test_darken_accent_pair_preserves_the_hover_vs_rest_distinction():
    # THE BUG the earlier "blend toward accent" attempt had: the tamed hover
    # color collapsed to within single-digit RGB units of the resting
    # background — a technically-higher-contrast but functionally invisible
    # hover highlight. darken_accent_pair must keep a REAL visible gap.
    accent, accent_light, text = BAD_TRIPLE
    new_accent, new_accent_light = darken_accent_pair(accent, accent_light, text)
    distance = sum(abs(a - b) for a, b in zip(_rgb(new_accent_light), _rgb(new_accent)))
    assert distance >= 30, f"hover color only {distance} RGB units from rest — highlight would read as invisible"


def test_darken_accent_pair_leaves_an_already_good_triple_untouched():
    accent, accent_light, text = GOOD_TRIPLE
    before = _wcag_contrast(_rgb(accent_light), _rgb(text))
    assert before >= _COVER_BUTTON_HOVER_TARGET_CONTRAST, "fixture should already be comfortable"
    new_accent, new_accent_light = darken_accent_pair(accent, accent_light, text)
    assert (new_accent, new_accent_light) == (accent, accent_light), (
        "an already-safe pair must come back byte-for-byte unchanged"
    )


def test_darken_accent_pair_preserves_hue():
    # Darkening must move along VALUE only — hue (and therefore the color
    # family: teal stays teal, olive stays olive) must not drift. This is
    # what distinguishes "a deeper shade of the same color" from "a
    # different, unrelated color."
    accent, accent_light, text = BAD_TRIPLE
    new_accent, new_accent_light = darken_accent_pair(accent, accent_light, text)
    orig_h, _, _ = colorsys.rgb_to_hsv(*(c / 255 for c in _rgb(accent)))
    new_h, _, new_v = colorsys.rgb_to_hsv(*(c / 255 for c in _rgb(new_accent)))
    orig_v = colorsys.rgb_to_hsv(*(c / 255 for c in _rgb(accent)))[2]
    assert abs(new_h - orig_h) < 0.01, f"hue drifted from {orig_h:.3f} to {new_h:.3f}"
    assert new_v < orig_v, "darkening should strictly reduce value when it engages"


def test_darken_accent_pair_never_reaches_pure_black():
    accent, accent_light, text = BAD_TRIPLE
    new_accent, new_accent_light = darken_accent_pair(accent, accent_light, text)
    assert _rgb(new_accent) != (0, 0, 0)
    assert _rgb(new_accent_light) != (0, 0, 0)


def test_get_player_stylesheet_named_theme_is_byte_for_byte_unchanged():
    from fabulor.themes import _resolve_theme
    t = _resolve_theme("Melnibonéan")
    s = get_player_stylesheet("Melnibonéan")
    assert f"background: {t['accent']};" in s
    assert f"background-color: {t['accent_light']};" in s


def test_get_player_stylesheet_cover_theme_routes_through_darken_accent_pair():
    theme_dict = {
        "bg_main": "#1A2A0F",
        "accent": BAD_TRIPLE[0],
        "accent_light": BAD_TRIPLE[1],
        "text": BAD_TRIPLE[2],
    }
    s = get_player_stylesheet(theme_dict)
    expected_accent, expected_accent_light = darken_accent_pair(*BAD_TRIPLE)
    assert f"background: {expected_accent};" in s
    assert f"background-color: {expected_accent_light};" in s
    # Confirm this fixture actually exercises darkening, not a no-op.
    assert expected_accent != BAD_TRIPLE[0]


def test_get_player_stylesheet_cover_theme_text_color_is_unaffected():
    # The text color (the thing that was tried and reverted twice) must stay
    # the plain flat chain for cover themes too — only background darkens.
    theme_dict = {
        "bg_main": "#1A2A0F",
        "accent": BAD_TRIPLE[0],
        "accent_light": BAD_TRIPLE[1],
        "text": BAD_TRIPLE[2],
    }
    s = get_player_stylesheet(theme_dict)
    assert f"color: {BAD_TRIPLE[2]};" in s
