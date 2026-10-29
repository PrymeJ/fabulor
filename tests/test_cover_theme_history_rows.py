"""
build_cover_theme must derive its own session_history_row_one/two, not
silently inherit The Color Purple's literal #22003D/#170129.

THE BUG (found 2026-10-03 during the named-theme investigation, fixed for
cover-art themes 2026-10-29): build_cover_theme never set these two keys,
so _resolve_theme's base-copy (which only excludes keys listed in
_NO_BASE_INHERIT_KEYS) silently inherited The Color Purple's own hardcoded
purple — completely disconnected from the cover's actual derived palette.
Confirmed live at the time via a synthetic green-palette cover dict that
resolved to the same literal purple regardless of the cover's real colors.

The fix derives both keys from the SAME bg_main-relative formula reverse-
engineered from the ~38 hand-tuned named themes in the 2026-10-03 session
(see TODO_ARCHIVE.md / SESSION.md for that derivation): row1 tracks
bg_main's own hue/saturation with a slight value lift, row2 a further
darken, with a floor-flip (both lift instead) when bg_main is already
near-black. Anchored on bg_main's OWN already-jittered tuple (not a fresh
shift from the cover's dominant color), so the two rows always agree with
whatever bg_main this specific call actually produced.
"""
import colorsys

from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication

from fabulor.themes import _resolve_theme
from fabulor.ui.cover_theme import build_cover_theme

_PURPLE_ROW_ONE = "#22003D"
_PURPLE_ROW_TWO = "#170129"


def _ensure_app():
    return QApplication.instance() or QApplication([])


def _solid_pixmap(r, g, b):
    pm = QPixmap(64, 64)
    pm.fill(QColor(r, g, b))
    return pm


def _hsv(hex_color):
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)


_TEST_COLORS = [
    ("deep_red", (80, 10, 10)),
    ("forest_green", (20, 90, 30)),
    ("near_black", (5, 5, 8)),
    ("bright_blue", (60, 90, 200)),
    ("warm_tan", (180, 140, 90)),
]


def test_build_cover_theme_sets_both_history_row_keys():
    _ensure_app()
    for _name, rgb in _TEST_COLORS:
        theme_dict = build_cover_theme(_solid_pixmap(*rgb))
        assert "session_history_row_one" in theme_dict
        assert "session_history_row_two" in theme_dict


def test_build_cover_theme_never_falls_back_to_purple_literal():
    _ensure_app()
    for name, rgb in _TEST_COLORS:
        theme_dict = build_cover_theme(_solid_pixmap(*rgb))
        row1 = theme_dict["session_history_row_one"]
        row2 = theme_dict["session_history_row_two"]
        assert row1 != _PURPLE_ROW_ONE, f"{name}: row1 fell back to Purple's literal"
        assert row2 != _PURPLE_ROW_TWO, f"{name}: row2 fell back to Purple's literal"


def test_resolve_theme_preserves_the_cover_dicts_own_value():
    # _resolve_theme must not re-override a dict-type (cover-art) theme's own
    # explicitly-set keys with The Color Purple's base-copy value.
    _ensure_app()
    theme_dict = build_cover_theme(_solid_pixmap(20, 90, 30))
    resolved = _resolve_theme(theme_dict)
    assert resolved["session_history_row_one"] == theme_dict["session_history_row_one"]
    assert resolved["session_history_row_two"] == theme_dict["session_history_row_two"]


def test_history_rows_track_bg_mains_hue_and_saturation():
    # Same invariant the named-theme derivation relies on: row1/row2 keep
    # bg_main's own hue/sat, only the value (brightness) channel differs.
    _ensure_app()
    for name, rgb in _TEST_COLORS:
        theme_dict = build_cover_theme(_solid_pixmap(*rgb))
        bg_h, bg_s, _ = _hsv(theme_dict["bg_main"])
        row1_h, row1_s, _ = _hsv(theme_dict["session_history_row_one"])
        row2_h, row2_s, _ = _hsv(theme_dict["session_history_row_two"])
        assert abs(row1_h - bg_h) < 0.02, f"{name}: row1 hue drifted from bg_main"
        assert abs(row2_h - bg_h) < 0.02, f"{name}: row2 hue drifted from bg_main"
        assert abs(row1_s - bg_s) < 0.02, f"{name}: row1 saturation drifted from bg_main"
        assert abs(row2_s - bg_s) < 0.02, f"{name}: row2 saturation drifted from bg_main"


def test_row_two_is_darker_than_row_one_except_near_black_floor():
    _ensure_app()
    for name, rgb in _TEST_COLORS:
        theme_dict = build_cover_theme(_solid_pixmap(*rgb))
        _, _, bg_v = _hsv(theme_dict["bg_main"])
        _, _, row1_v = _hsv(theme_dict["session_history_row_one"])
        _, _, row2_v = _hsv(theme_dict["session_history_row_two"])
        if bg_v <= 0.09:
            # Floor case: both rows lift instead of row2 darkening below row1.
            assert row1_v >= bg_v and row2_v >= bg_v, f"{name}: floor case didn't lift"
        else:
            assert row2_v < row1_v, f"{name}: row2 should be darker than row1"
