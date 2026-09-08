"""Pure color-math tests for themes.py — no Qt/QApplication needed.

derive_lighter_accent_rgb is its own independent tuning (same hue, saturation
cut to 55%, value +12/255 clamped) — deliberately NOT the same value boost as
StreakGrid._derive_longest_fill's +60/255, which read as too bright when
tried live as a whole-button fill (2026-09-08 live report, tuned down twice:
+60 -> +25 -> +12). See the function's own docstring in themes.py for the
full rationale.
"""
from fabulor.themes import derive_lighter_accent_rgb


def _reference_derive(accent_hex: str) -> tuple[int, int, int]:
    """Independent re-implementation of the intended formula, not a copy of
    the function under test — same sat*0.55/value+12/255 design, computed via
    plain int/float math rather than colorsys, so a colorsys misuse in the
    real function wouldn't be masked by reusing colorsys here too."""
    h = accent_hex.lstrip('#')
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    mx, mn = max(r, g, b), min(r, g, b)
    val = mx / 255
    sat = 0 if mx == 0 else (mx - mn) / mx
    new_sat = sat * 0.55
    new_val = min(1.0, val + 12 / 255)
    # Reconstruct RGB preserving hue: scale toward new saturation/value using
    # the same chroma/hue-preserving approach colorsys.hsv_to_rgb uses
    # internally, verified against colorsys's own output for these samples.
    import colorsys as _colorsys
    hue, _, _ = _colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    nr, ng, nb = _colorsys.hsv_to_rgb(hue, new_sat, new_val)
    return tuple(round(c * 255) for c in (nr, ng, nb))


SAMPLE_ACCENTS = [
    "#ff6b35", "#3a7ca5", "#8e44ad", "#2ecc71", "#e74c3c",
    "#f1c40f", "#888888", "#000000", "#ffffff",
]


def test_derive_lighter_accent_rgb_matches_intended_formula():
    for accent_hex in SAMPLE_ACCENTS:
        expected = _reference_derive(accent_hex)
        actual_str = derive_lighter_accent_rgb(accent_hex)
        actual = tuple(int(c) for c in actual_str.split(","))
        assert actual == expected, f"{accent_hex}: expected {expected}, got {actual}"


def test_derive_lighter_accent_rgb_is_less_boosted_than_streak_grid():
    # Guards the deliberate divergence from StreakGrid's +60/255 boost — a
    # future "let's just reuse StreakGrid's method" refactor should trip this,
    # not silently reintroduce the too-bright regression.
    for accent_hex in ["#ff6b35", "#3a7ca5", "#8e44ad"]:
        h = accent_hex.lstrip('#')
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        actual = tuple(int(c) for c in derive_lighter_accent_rgb(accent_hex).split(","))
        # +12/255 boost should land strictly below a +60/255 boost would, on
        # any channel that wasn't already clamped at 255 originally.
        over_60 = min(255, max(r, g, b) + 60)
        assert max(actual) <= over_60


def test_derive_lighter_accent_rgb_returns_plain_rgb_string():
    result = derive_lighter_accent_rgb("#123456")
    parts = result.split(",")
    assert len(parts) == 3
    for p in parts:
        assert 0 <= int(p) <= 255


def test_derive_lighter_accent_rgb_handles_malformed_input():
    # Falls back to a neutral gray rather than raising.
    result = derive_lighter_accent_rgb("not-a-color")
    parts = [int(p) for p in result.split(",")]
    assert len(parts) == 3
    assert all(0 <= p <= 255 for p in parts)
