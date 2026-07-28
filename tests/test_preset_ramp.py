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
import pytest

from fabulor.themes import _RAMP_MAX_MIX, _RAMP_MIN_MIX, preset_ramp_rgb

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
    first = _rgb(THEME, 0, 6)
    bg = (0x1A, 0x00, 0x2E)
    assert first != bg
    # ...but it is much closer to the background than to the accent.
    accent = (0xD4, 0x20, 0x20)
    d_bg = sum(abs(a - b) for a, b in zip(first, bg))
    d_ac = sum(abs(a - b) for a, b in zip(first, accent))
    assert d_bg < d_ac


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


def test_ramp_span_matches_the_old_alpha_range():
    # Guards the visual regression: the old ramp ran alpha 75..255 out of 255, and
    # the mix ratios must reproduce that span or the buttons visibly change.
    assert _RAMP_MIN_MIX == pytest.approx(75 / 255)
    assert _RAMP_MAX_MIX == 1.0


def test_no_alpha_channel_is_emitted():
    # The whole point: three channels, never four. A fourth would reintroduce the
    # bleed-through this fix removes.
    assert len(preset_ramp_rgb(THEME, 3, 6).split(",")) == 3
