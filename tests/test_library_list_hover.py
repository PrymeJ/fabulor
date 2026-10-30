"""List view's hover: a stronger alpha than 1-per-row, and a trail whose length depends on the
Look setting only, not on the theme's hover alpha."""
import pytest
from PySide6.QtWidgets import QApplication

from fabulor.ui.library import BookDelegate


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def _delegate(alpha):
    return BookDelegate(theme={"library_item_hover_color": "#C05151",
                               "library_item_hover_alpha": alpha})


@pytest.mark.parametrize("alpha", [0.15, 0.33, 0.95], ids=["low", "fire_and_blood", "capped"])
def test_list_hover_is_boosted_and_one_per_row_is_not(qapp, alpha):
    d = _delegate(alpha)
    list_alpha = min(1.0, alpha + BookDelegate._LIST_HOVER_ALPHA_BOOST)
    assert d._hover_bg_color.alpha() == int(alpha * 255)
    assert d._list_hover_bg_color.alpha() == int(list_alpha * 255)
    if alpha == 0.95:
        assert d._list_hover_bg_color.alpha() == 255


def _fade_ticks(d):
    d._hover_fade = {"/book": d._list_hover_bg_color.alpha()}
    d._list_hovered_path = ""
    ticks = 0
    while d._hover_fade:
        d._advance_hover_fade()
        ticks += 1
    return ticks


@pytest.mark.parametrize("mode", ["Slow", "Normal", "Fast"])
def test_trail_length_does_not_depend_on_hover_alpha(qapp, mode):
    durations = []
    for alpha in (0.10, 0.15, 0.33, 0.50):
        d = _delegate(alpha)
        d._hover_fade_mode = mode
        durations.append(_fade_ticks(d) * BookDelegate._HOVER_FADE_TICK_MS)
    expected = BookDelegate._HOVER_FADE_OUT_MS[mode]
    for ms in durations:
        assert abs(ms - expected) <= 2 * BookDelegate._HOVER_FADE_TICK_MS, (mode, durations)
