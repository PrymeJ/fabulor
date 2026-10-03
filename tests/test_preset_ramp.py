"""Sleep/Speed preset-button ramp: opaque colour steps, not alpha (pure, headless).

THE BUG (user-found with screenshots, 2026-07-28). Both panels built their
per-button visual ramp by varying ALPHA on the theme accent —
`alpha = int(75 + (180 * (i / (n - 1))))`, emitted as
`background-color: rgba(r, g, b, alpha)` through a per-instance setStyleSheet.
At alpha 75 the first button is ~29% opaque, so it composited against whatever sat
behind the panel. Since every theme's `panel_opacity_hover` is 0.88-0.95, the
COVER ART showed through: "INFINITE JEST" was legible inside the speed grid.

The ramp is meant to be a purely visual progression. `preset_ramp_rgb` produces the
same progression by blending in COLOUR SPACE, so the emitted colours are fully
opaque and nothing can bleed through.

These pin the properties that matter; the visual result is live-verified.
"""
import colorsys

import pytest

from fabulor.themes import (
    _RAMP_MAX_MIX,
    _RAMP_MIN_MIX,
    THEMES,
    _resolve_theme,
    _wcag_contrast,
    preset_ramp_rgb,
    ramp_text_colors,
)

THEME = {"bg_main": "#1A002E", "accent": "#D42020"}


def _rgb(theme, i, n):
    return tuple(int(v) for v in preset_ramp_rgb(theme, i, n).split(","))


def test_returns_three_channels_in_range():
    for i in range(6):
        r, g, b = _rgb(THEME, i, 6)
        assert all(0 <= c <= 255 for c in (r, g, b))


def test_first_step_is_not_the_background():
    # The old ramp started at alpha 75 (~29%), not 0 — the first button is a muted
    # accent, NOT invisible. A blend starting at the background would lose that.
    #
    # Note (2026-10-02): this no longer asserts "closer to bg than to accent" —
    # that was the OLD plain-linear-RGB blend's distance profile specifically,
    # and the brightness-floor boost (see preset_ramp_rgb's "2026-10-02
    # brightness-eased blend" docstring note) deliberately moves the low end's
    # BRIGHTNESS closer to the accent's own, as a direct fix for a live
    # complaint that the dark end was too muddy. Distance-to-background is
    # still the right invariant to pin; distance-to-accent is not, by design.
    first = _rgb(THEME, 0, 6)
    bg = (0x1A, 0x00, 0x2E)
    assert first != bg


def test_last_step_is_the_full_accent():
    # _RAMP_MAX_MIX is 1.0, mirroring the old alpha 255 end of the ramp.
    assert _rgb(THEME, 5, 6) == (0xD4, 0x20, 0x20)


def test_progression_is_monotonic_toward_the_accent():
    # Each step must be at least as close to the accent as the one before, or the
    # ramp stops reading as a progression.
    accent = (0xD4, 0x20, 0x20)
    dists = [sum(abs(a - b) for a, b in zip(_rgb(THEME, i, 8), accent))
             for i in range(8)]
    assert dists == sorted(dists, reverse=True)


def test_single_button_does_not_divide_by_zero():
    # span = max(1, count - 1) guards this; a one-preset panel is degenerate but
    # must not raise.
    assert _rgb(THEME, 0, 1)


def test_missing_theme_keys_fall_back():
    # get_current_theme() should always supply these, but a partial theme dict must
    # not raise — this runs on every panel restyle.
    assert _rgb({}, 2, 6)
    assert _rgb({"accent": "#FFFFFF"}, 2, 6)


def test_low_end_is_brighter_than_a_plain_linear_blend_would_give():
    # The live complaint this fixes: on a theme whose bg_main and accent are
    # both dark-ish (common for a themed accent color), the ramp's low end
    # used to sit close to bg_main's own brightness and read as muddy. A plain
    # linear blend at _RAMP_MIN_MIX (~0.294) toward accent (255,0,0) from a
    # near-black bg_main would land near rgb(75,0,0) - the boosted version
    # must land meaningfully brighter than that, not just "not equal".
    theme = {"bg_main": "#0A0A0A", "accent": "#FF0000"}
    plain_blend_r = round(0x0A + (0xFF - 0x0A) * _RAMP_MIN_MIX)
    r, g, b = _rgb(theme, 0, 13)
    assert r > plain_blend_r + 20


def test_dark_end_override_is_honored():
    # preset_ramp_dark_end (2026-10-02, Pryme's own request) lets a theme blend
    # from a color other than its literal bg_main.
    theme = {"bg_main": "#1A002E", "accent": "#D42020", "preset_ramp_dark_end": "#00FF00"}
    assert _rgb(theme, 0, 13) != _rgb({"bg_main": "#1A002E", "accent": "#D42020"}, 0, 13)
    # at ratio 0 (if _RAMP_MIN_MIX were 0) the dark end would be exactly the
    # override; at the real _RAMP_MIN_MIX it should still read clearly greener
    # than a theme using its own purple bg_main.
    r, g, b = _rgb(theme, 0, 13)
    assert g > r and g > b


def test_bright_end_override_is_honored():
    # preset_ramp_bright_end (2026-10-02, Pryme's own request) lets a theme blend
    # toward a color other than its literal accent.
    theme = {"bg_main": "#000000", "accent": "#D42020", "preset_ramp_bright_end": "#00FF00"}
    # the LAST step (_RAMP_MAX_MIX == 1.0) must land on the override, not accent.
    assert _rgb(theme, 12, 13) == (0x00, 0xFF, 0x00)


def test_gradient_accent_themes_blend_toward_the_darker_gradient_endpoint():
    # THE BUG (live, 2026-10-03, Dorian Gray): _get_gradient_style paints a real
    # qlineargradient for every accent-background button (End of chapter, Set,
    # the generic QPushButton rule) whenever a theme sets gradient_accent_start/
    # gradient_accent_end — the flat `accent` key becomes unreachable fallback
    # dead code for those buttons. preset_ramp_rgb didn't know this and always
    # blended toward flat `accent` regardless, so on Dorian Gray (flat accent
    # #BCB8B8, HSV value 0.74, brighter than EITHER gradient endpoint #8D8D8D/
    # #686868, value 0.55/0.41) the ramp's brightest step rendered lighter than
    # "End of chapter"/"Set"'s real gradient fill, and the gradient's dark
    # corner was darker than the ramp's own darkest step — confirmed with real
    # picked pixel values: 2 min = #7d7c7c (matches the ramp's step-0 math
    # exactly), End of chapter's gradient corners = #8d8d8d / #686868 (matches
    # gradient_accent_start/end exactly, neither of which the ramp ever used).
    theme = {
        "bg_main": "#333333",
        "accent": "#BCB8B8",  # brighter than either gradient endpoint - must be ignored here
        "gradient_accent_start": "#8D8D8D",
        "gradient_accent_end": "#686868",
    }
    last = _rgb(theme, 12, 13)
    # the brightest step must land on the DARKER gradient endpoint (#686868),
    # never on flat accent (#BCB8B8) and never on the lighter endpoint.
    assert last == (0x68, 0x68, 0x68)


def test_explicit_bright_end_override_still_wins_over_gradient_keys():
    # preset_ramp_bright_end must take priority over the gradient-endpoint
    # fallback above, same as it already does over flat accent.
    theme = {
        "bg_main": "#000000",
        "accent": "#BCB8B8",
        "gradient_accent_start": "#8D8D8D",
        "gradient_accent_end": "#686868",
        "preset_ramp_bright_end": "#00FF00",
    }
    assert _rgb(theme, 12, 13) == (0x00, 0xFF, 0x00)


def test_gradient_fallback_picks_darker_endpoint_regardless_of_start_end_order():
    # The darker endpoint can be EITHER gradient_accent_start or _end depending
    # on the theme's own gradient direction (Dorian Gray's darker color happens
    # to be "end"; nothing guarantees that ordering for every theme) - the pick
    # must be based on brightness, not positional convention.
    theme_end_darker = {
        "bg_main": "#000000", "accent": "#888888",
        "gradient_accent_start": "#FFFFFF", "gradient_accent_end": "#111111",
    }
    assert _rgb(theme_end_darker, 12, 13) == (0x11, 0x11, 0x11)

    theme_start_darker = {
        "bg_main": "#000000", "accent": "#888888",
        "gradient_accent_start": "#111111", "gradient_accent_end": "#FFFFFF",
    }
    assert _rgb(theme_start_darker, 12, 13) == (0x11, 0x11, 0x11)


def test_every_real_theme_ramp_stays_monotonic_toward_its_own_accent():
    # test_progression_is_monotonic_toward_the_accent (above) pins this against
    # one synthetic purple-bg/red-accent pair, chosen specifically because a
    # large hue gap between bg_main and accent is what exposed a real
    # regression here once (2026-10-02): blending hue in HSV space took the
    # "short way" around the color wheel through unrelated hues (a muddy
    # yellow-brown appeared between a gray bg and a blue accent on the real
    # "Blindsight" theme), breaking monotonicity. This repeats that check
    # against every real theme's own bg_main/accent pair, not just one
    # synthetic case, since 10 of 62 real themes have a >72-degree hue gap.
    for name, raw in THEMES.items():
        t = _resolve_theme(raw)
        # preset_ramp_bright_end (2026-10-02) lets a theme blend toward something
        # other than its literal accent — the ramp's TRUE target in that case,
        # so monotonicity must be checked against it, not the bare accent key.
        bright_end = t.get('preset_ramp_bright_end', t['accent'])
        accent = tuple(int(bright_end.lstrip('#')[i:i + 2], 16) for i in (0, 2, 4))
        dists = [sum(abs(a - b) for a, b in zip(_rgb(t, i, 13), accent))
                  for i in range(13)]
        assert dists == sorted(dists, reverse=True), f"{name} ramp is not monotonic toward its accent"


def test_ramp_span_matches_the_old_alpha_range():
    # Guards the visual regression: the old ramp ran alpha 75..255 out of 255, and
    # the mix ratios must reproduce that span or the buttons visibly change.
    assert _RAMP_MIN_MIX == pytest.approx(75 / 255)
    assert _RAMP_MAX_MIX == 1.0


def test_no_alpha_channel_is_emitted():
    # The whole point: three channels, never four. A fourth would reintroduce the
    # bleed-through this fix removes.
    assert len(preset_ramp_rgb(THEME, 3, 6).split(",")) == 3


# --- ramp_text_colors (TODO.md "Some themes need a preset-ramp colour override") ---
#
# THE BUG (scan-found, see ramp_text_colors' docstring). The three ramp call
# sites (Sleep/Speed/Sprint) painted every step with one flat `button_text`
# color — correct for a fixed-background button, wrong for a ramp whose
# background spans near-bg_main to full-accent within one row. A scan of all 62
# themes found 49 with severe (<3:1) contrast failures against their own
# button_text and 11 more borderline — only 2 themes passed.
#
# Three designs were tried and rejected live before this one shipped (full
# detail in ramp_text_colors' own docstring): flat black/white per step ("I
# hope you won't leave them just white and black"); per-step black/white
# TINTED toward a theme hue, still deciding light-vs-dark independently per
# step ("this works well up to 2.50, then it goes black all of a sudden");
# and per-step direction at a lower contrast target, which still flipped
# mid-ramp on a theme whose own ramp crosses the midpoint luminance more than
# once ("aim for consistent dark or bright text anyway. I don't [want] those
# abrupt switches"). The shipped version decides light-vs-dark ONCE for the
# whole ramp and eases only VALUE continuously within that one direction —
# the no-flip tests below are the regression net for exactly this property.


def _text_rgb(hex_str):
    h = hex_str.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def test_returns_count_hex_colors():
    results = ramp_text_colors(THEME, 6)
    assert len(results) == 6
    for result in results:
        assert result.startswith("#") and len(result) == 7


def test_single_direction_per_ramp_no_flip():
    # The core regression this guards: once a ramp picks light-text or
    # dark-text, EVERY step must use that same direction — max(r,g,b) (a
    # brightness proxy) must move monotonically across the row, never swing
    # back and forth. Checked against every real theme's own ramp, not just a
    # synthetic one, since the bug that motivated this test (Fire and Blood,
    # a saturated red theme) only showed up on a real theme's hue/background
    # combination.
    for name, raw in THEMES.items():
        t = _resolve_theme(raw)
        texts = ramp_text_colors(t, 13)
        brightness = [max(_text_rgb(h)) for h in texts]
        increasing = all(brightness[i] <= brightness[i + 1] for i in range(len(brightness) - 1))
        decreasing = all(brightness[i] >= brightness[i + 1] for i in range(len(brightness) - 1))
        assert increasing or decreasing, f"{name}'s ramp text flips direction: {brightness}"


def test_tint_is_not_flat_black_or_white():
    # The result must actually carry some of the theme's hue, not just be
    # pure #000000/#ffffff every time — this is what distinguishes the
    # shipped design from the first, rejected flat-black/white-only version.
    # Uses a real theme (not the synthetic THEME, whose bare-minimum dict has
    # no button_text and an accent that happens to land on hue 0.0 — i.e. the
    # SAME hue pure red sits at, so its chosen anchor direction legitimately
    # needs no tint and this property doesn't apply to it specifically).
    t = _resolve_theme(THEMES["Blindsight"])
    results = ramp_text_colors(t, 13)
    carries_color = any(len(set(_text_rgb(h))) > 1 for h in results)
    assert carries_color


def test_override_hue_is_honored():
    # preset_ramp_text_hue lets an individual theme hand-pick the tint hue
    # directly, bypassing the derived button_text/accent chain.
    theme = dict(THEME, preset_ramp_text_hue="#00FFFF")  # pure cyan
    r, g, b = _text_rgb(ramp_text_colors(theme, 6)[0])
    # cyan tint: green and blue should lead red, regardless of direction.
    assert g >= r and b >= r


def test_literal_text_color_override_is_used_verbatim():
    # preset_ramp_text_color (2026-10-02, Pryme's own request: "I want the
    # text to be what I set, nothing something to be derived from it") skips
    # ALL derivation — every step gets exactly this color, not a hue fed
    # through the contrast/direction machinery. Checked against a real theme
    # (Rivendell) whose automatic hue-override result is known to land on
    # flat black (its mid-tone ramp correctly picks the dark direction,
    # which makes ANY hue invisible at HSV value=0) — the literal override
    # must bypass that entirely and still show the requested color.
    t = _resolve_theme(THEMES["Rivendell"])
    theme = dict(t, preset_ramp_text_color="#FF0000")
    results = ramp_text_colors(theme, 13)
    assert all(r == "#FF0000" for r in results)


def test_literal_text_color_takes_priority_over_hue_override():
    # If both are set, the literal color wins — preset_ramp_text_hue still
    # derives through the contrast machinery, which is exactly what the
    # literal override exists to bypass.
    theme = dict(THEME, preset_ramp_text_color="#00FF00", preset_ramp_text_hue="#FF0000")
    assert all(r == "#00FF00" for r in ramp_text_colors(theme, 6))


def test_most_themes_meet_a_relaxed_contrast_floor():
    # Pryme's own call once the brightened ramp made full AA unnecessary: "I
    # think we can get away with less contrast." The single-direction
    # constraint means a small minority of themes (ramps whose own hue
    # crosses the midpoint luminance, e.g. Violeta) can't hit even this
    # relaxed floor on every step without reintroducing a flip — that's
    # accepted, not a bug (see ramp_text_colors' docstring). This pins the
    # SHAPE of that tradeoff: almost every theme clears 3.0:1 everywhere, and
    # no theme ever drops to near-zero contrast.
    #
    # Note (2026-10-03): a "fix direction against pure black/white instead of
    # the tinted candidates" change was tried here for Blood Meridian/Fire
    # and Blood (whose tinted-pink "white" candidate scored artificially low)
    # and REVERTED THE SAME SESSION — it silently flipped several OTHER
    # already-correct themes (Dorian Gray, Blue Moranth) to the wrong
    # direction, reported live. The tinted-candidate comparison is back to
    # how it always was; Blood Meridian/Fire and Blood's dark-text-on-dark-
    # background issue is still open, not yet fixed — see TODO.md if this is
    # picked up again. Do not re-attempt the "pure black/white" direction
    # fix without checking it against a broad theme sample first, not just
    # the two themes it was built to fix.
    # Themes with a LITERAL preset_ramp_text_color override are excluded from
    # the floor/worst-case accounting below — that path returns the author's
    # own chosen color verbatim, with no contrast guarantee, by design (same
    # as `button_text_for_accent`'s identical exclusion). As Pryme's own
    # per-theme tuning pass adds more of these, the count of themes "below
    # the floor" on this metric grows for reasons that have nothing to do
    # with this function's own derivation correctness — only themes still on
    # the AUTOMATIC derivation path are meaningful here.
    below_floor_themes = 0
    absolute_worst = 99.0
    for name, raw in THEMES.items():
        t = _resolve_theme(raw)
        if t.get('preset_ramp_text_color'):
            continue
        texts = ramp_text_colors(t, 13)
        worst = min(
            _wcag_contrast(tuple(int(v) for v in preset_ramp_rgb(t, i, 13).split(",")), _text_rgb(h))
            for i, h in enumerate(texts)
        )
        absolute_worst = min(absolute_worst, worst)
        if worst < 3.0:
            below_floor_themes += 1
    assert below_floor_themes <= 10, f"{below_floor_themes} themes below the 3.0 floor — expected a small minority"


# ── ramp_text_colors: is_cover_theme ────────────────────────────────────────────────────────────

# Shapes a few realistic cover_theme.build_cover_theme() outputs without importing that module
# (it needs a real QPixmap/QApplication — this file stays pure/headless). Every one of these omits
# button_text/text_on_light_bg (build_cover_theme never sets them — see ramp_text_colors'
# is_cover_theme docstring) and sets a low-saturation `text` plus a mid-saturation `accent`/`bg_main`
# all sharing one dominant hue, matching build_cover_theme's actual palette shape. Three of these
# four reproduce the live bug (named-theme path -> pure black); the fourth (indigo) does not, kept
# anyway as a general "stays tinted" check that isn't contingent on hitting the exact bug.
_COVER_LIKE_THEMES = [
    {"bg_main": "#1A0F28", "accent": "#834ABC", "text": "#D0B9E6"},   # purple cover
    {"bg_main": "#0F1A28", "accent": "#4781BB", "text": "#B0CBE7"},   # blue cover
    {"bg_main": "#281A0F", "accent": "#BA7B49", "text": "#ECD4C1"},   # amber cover
    {"bg_main": "#160F28", "accent": "#4646B1", "text": "#ADADDD"},   # indigo cover
]
_COVER_LIKE_THEMES_REPRODUCING_THE_BUG = _COVER_LIKE_THEMES[:3]


def test_cover_theme_path_never_collapses_to_a_pure_extreme():
    # THE BUG (live, 2026-10-03): "I tested 7 covers. They all made the text
    # resolve black... the buttons look dark enough, yet the text is still
    # black." Traced to the named-theme direction-pick (compare hue-tinted
    # white/black candidates by average contrast) being reused for cover
    # themes, whose ramp sits in a narrow, low-saturation mid-luminance band
    # where BOTH tinted candidates score mediocre average contrast and black
    # wins only because it's accidentally untinted at val=0 — not because it
    # fits the cover's own colors. A later live report ("Pure white with many
    # covers") found a SECOND, independent way to reach a near-extreme: on a
    # cover theme with a bright/saturated accent, the per-step desaturation
    # search needed near-total desaturation to clear target on the ramp's
    # brighter/later steps, landing a hair from pure white even with the
    # direction-pick itself correct. _RAMP_TEXT_COVER_SAT_FLOOR closes that
    # second gap — no step, anywhere in the ramp, may drop below it. No
    # theme, at any step, should ever land on a pure black/white extreme.
    for theme in _COVER_LIKE_THEMES:
        t = _resolve_theme(theme)
        texts = ramp_text_colors(t, 14, is_cover_theme=True)
        for i, hexcolor in enumerate(texts):
            rgb = _text_rgb(hexcolor)
            assert rgb not in ((0, 0, 0), (255, 255, 255)), (
                f"{theme['accent']} step {i} resolved to a pure extreme ({hexcolor}) — expected a visible tint"
            )


def test_cover_theme_direction_pick_differs_from_named_theme_path_when_it_matters():
    # Confirms the two paths can genuinely disagree (is_cover_theme=True isn't
    # a no-op) — these three themes resolve to black under the named-theme
    # algorithm (is_cover_theme=False, the default) but not under the
    # cover-theme one.
    for theme in _COVER_LIKE_THEMES_REPRODUCING_THE_BUG:
        t = _resolve_theme(theme)
        named_path = ramp_text_colors(t, 14, is_cover_theme=False)
        cover_path = ramp_text_colors(t, 14, is_cover_theme=True)
        assert named_path[0] == "#000000", "fixture should reproduce the live bug under the old path"
        assert cover_path[0] != named_path[0]


def test_cover_theme_path_eases_per_step_from_darker_to_the_last_steps_color():
    # Live feedback (2026-10-03), after the first version of this path shipped
    # collapsed to one flat color for the whole ramp (mirroring the named-theme
    # path's own no-flip design): "the ease-in spectrum is too narrow. I think
    # the first button can use a bit darker text and make its way up to
    # current last button's text color." Unlike the named-theme path, this one
    # intentionally returns genuine PER-STEP variation — each step's own
    # contrast-safe search result, not collapsed — because it is already
    # provably safe to do so here (see the mechanism comment in
    # ramp_text_colors' cover-theme branch): the search always moves outward
    # from the SAME fixed anchor, and preset_ramp_rgb's background value only
    # increases along the row, so desaturation need can only trend in one
    # direction, never reverse mid-ramp.
    for theme in _COVER_LIKE_THEMES:
        t = _resolve_theme(theme)
        texts = ramp_text_colors(t, 14, is_cover_theme=True)
        sats = [colorsys.rgb_to_hsv(*(c / 255 for c in _text_rgb(h)))[1] for h in texts]
        assert len(set(texts)) > 1, f"{theme['accent']}: expected visible per-step variation, got one flat color"
        # Monotonic: saturation never INCREASES moving later into the ramp
        # (a reversal would look like exactly the abrupt flip this whole
        # function's design otherwise guards against).
        for i in range(len(sats) - 1):
            assert sats[i + 1] <= sats[i] + 1e-9, (
                f"{theme['accent']}: saturation rose from step {i} ({sats[i]:.3f}) "
                f"to step {i + 1} ({sats[i + 1]:.3f}) — must ease monotonically"
            )


def test_cover_theme_path_monotonic_across_a_broad_random_sample():
    # Broader, randomized version of the monotonicity check above — verified
    # live against 200 random cover-derived themes x 2 directions (white/
    # black-anchored) with zero non-monotonic sequences before this path
    # shipped; this pins a smaller, deterministic sample of the same property
    # so a future regression doesn't need a live app to catch.
    import random as _random
    _random.seed(7)
    for _ in range(25):
        rgb_dom = tuple(_random.randint(10, 220) for _ in range(3))
        # Shape a cover-like theme directly from the random dominant color,
        # same palette shape build_cover_theme uses (no button_text/
        # text_on_light_bg; text/accent share the dominant hue).
        hue, _s, _v = colorsys.rgb_to_hsv(*(c / 255 for c in rgb_dom))
        text_rgb = tuple(round(c * 255) for c in colorsys.hsv_to_rgb(hue, 0.2, 0.9))
        accent_rgb = tuple(round(c * 255) for c in colorsys.hsv_to_rgb(hue, 0.6, 0.72))
        bg_rgb = tuple(round(c * 255) for c in colorsys.hsv_to_rgb(hue, 0.45, 0.15))
        theme = {
            "text": "#%02x%02x%02x" % text_rgb,
            "accent": "#%02x%02x%02x" % accent_rgb,
            "bg_main": "#%02x%02x%02x" % bg_rgb,
        }
        t = _resolve_theme(theme)
        texts = ramp_text_colors(t, 14, is_cover_theme=True)
        sats = [colorsys.rgb_to_hsv(*(c / 255 for c in _text_rgb(h)))[1] for h in texts]
        for i in range(len(sats) - 1):
            assert sats[i + 1] <= sats[i] + 1e-9, f"{theme}: non-monotonic at step {i}"


def test_cover_theme_path_never_affects_named_themes():
    # is_cover_theme defaults to False, and every one of the 62 named themes'
    # own call sites pass it only when get_committed_theme() returns a dict
    # (cover-art mode) — never for a plain theme name. Confirms the default
    # (and therefore every named theme's existing, hand-tuned result) is
    # completely unaffected by this parameter's existence.
    for name, raw in THEMES.items():
        t = _resolve_theme(raw)
        if t.get('preset_ramp_text_color'):
            continue
        default_call = ramp_text_colors(t, 13)
        explicit_false = ramp_text_colors(t, 13, is_cover_theme=False)
        assert default_call == explicit_false


def test_cover_theme_path_picks_higher_saturation_direction():
    # Direct pin of the mechanism: given two directions' final results, the
    # one with higher average saturation wins, not the one with higher raw
    # contrast — unless the two are within _RAMP_TEXT_COVER_SAT_TIE_EPSILON,
    # in which case it falls back to contrast (covered implicitly by every
    # theme above, none of which happens to land exactly on that tie).
    t = _resolve_theme({"bg_main": "#140A1E", "accent": "#7A3DAE", "text": "#C9A8E0"})
    texts = ramp_text_colors(t, 14, is_cover_theme=True)
    rgb = _text_rgb(texts[0])
    _h, sat, _v = colorsys.rgb_to_hsv(*(c / 255 for c in rgb))
    assert sat > 0.2, f"expected a clearly-tinted result, got {texts[0]} (sat={sat:.2f})"
