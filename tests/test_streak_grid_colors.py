"""StreakGrid colors: six optional theme keys, each derived when unset (StreakGrid.apply_theme)."""
import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from fabulor.themes import THEMES, _NO_BASE_INHERIT_KEYS, _resolve_theme
from fabulor.ui.stats_panel import StreakGrid

_KEYS = ("no_listening_cell", "regular_streak_cell", "longest_streak_cell",
         "longest_streak_outline", "regular_streak_dot", "longest_streak_dot")


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def _grid(theme):
    g = StreakGrid()
    g.apply_theme(theme)
    return g


def _position(bg, color, target):
    """Where target's L* sits between bg (0) and color (1)."""
    lb, lc = StreakGrid._lstar(bg), StreakGrid._lstar(color)
    return (StreakGrid._lstar(target) - lb) / (lc - lb)


def test_every_override_is_used_as_is(qapp):
    values = ["#101010", "#202020", "#303030", "#404040", "#505050", "#606060"]
    theme = {"accent": "#C05151", "bg_main": "#1A1A1A", **dict(zip(_KEYS, values))}
    g = _grid(theme)
    got = [g._empty, g._regular_cell, g._longest_fill, g._longest_outline,
           g._finished_dot, g._longest_dot]
    assert [c.name() for c in got] == values


@pytest.mark.parametrize("accent, bg", [("#C05151", "#1E1212"), ("#00FF00", "#2A0050"),
                                        ("#2E7A6A", "#D8E0DC")])   # last: light theme
def test_fallbacks(qapp, accent, bg):
    g = _grid({"accent": accent, "bg_main": bg})
    a, b = QColor(accent), QColor(bg)
    assert g._regular_cell.name() == a.name()
    assert g._longest_outline.name() == a.name()
    assert _position(b, a, g._empty) == pytest.approx(StreakGrid._EMPTY_POS, abs=0.03)
    assert _position(b, a, g._longest_fill) == pytest.approx(StreakGrid._LONGEST_POS, abs=0.03)
    lift = StreakGrid._lstar(g._finished_dot) - StreakGrid._lstar(a)
    assert lift == pytest.approx(min(StreakGrid._DOT_LIFT, 97.0 - StreakGrid._lstar(a)), abs=1.0)
    assert g._longest_dot.name() == g._finished_dot.name()


@pytest.mark.parametrize("cell", ["#FFFFFF", "#00FFFF"])
def test_dot_on_a_near_white_cell_goes_darker(cell):
    dot = StreakGrid._light_dot(QColor(cell))
    assert StreakGrid._lstar(QColor(cell)) - StreakGrid._lstar(dot) == pytest.approx(
        StreakGrid._DOT_LIFT, abs=1.0)


def test_derived_colors_follow_an_overridden_regular_cell(qapp):
    g = _grid({"accent": "#C05151", "bg_main": "#1E1212", "regular_streak_cell": "#5161C0"})
    assert g._longest_fill.hue() == QColor("#5161C0").hue()
    assert g._finished_dot.hue() == QColor("#5161C0").hue()


def test_switching_themes_drops_the_previous_overrides(qapp):
    g = _grid(_resolve_theme("Red Rising"))
    jade = _resolve_theme("Jade City")                    # sets no longest_streak_cell
    g.apply_theme(jade)
    expected = StreakGrid._between(QColor(jade["bg_main"]), QColor(jade["accent"]),
                                   StreakGrid._LONGEST_POS)
    assert g._longest_fill.name() == expected.name()


def _cell_pixel(g, bg, day_index):
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QWidget
    img = QImage(g.size(), QImage.Format.Format_ARGB32)
    img.fill(bg)
    g.render(img, QPoint(0, 0), renderFlags=QWidget.RenderFlag.DrawChildren)
    r, c = divmod(day_index, StreakGrid.N_COLS)
    x = StreakGrid.GUTTER_W + c * (StreakGrid.CELL + StreakGrid.GAP) + 2
    y = StreakGrid.TOP_PAD + r * (StreakGrid.CELL + StreakGrid.GAP) + 2
    return img.pixelColor(x, y)


def test_days_before_the_first_listening_day_are_not_no_listening_days(qapp):
    from datetime import date, timedelta
    today = date(2026, 10, 30)
    iso = lambda i: (today - timedelta(days=i)).isoformat()
    cache = {iso(i): 0 for i in range(364)}
    cache[iso(10)] = 1                      # the first (oldest) listening day
    cache[iso(0)] = 1
    bg = QColor("#1E1212")
    g = _grid({"accent": "#C05151", "bg_main": bg.name()})
    g.set_data(cache, {"current": 1, "longest": 1}, set(), today)

    skipped = _cell_pixel(g, bg, 5)         # after history started: a real no-listening day
    before = _cell_pixel(g, bg, 40)         # before the first listening day
    assert skipped.name() == g._empty.name()
    assert before.name() != g._empty.name()
    assert max(abs(before.red() - bg.red()), abs(before.green() - bg.green()),
               abs(before.blue() - bg.blue())) <= 12          # nearly background


def test_no_listening_at_all_shows_no_no_listening_days(qapp):
    from datetime import date, timedelta
    today = date(2026, 10, 30)
    cache = {(today - timedelta(days=i)).isoformat(): 0 for i in range(364)}
    bg = QColor("#1E1212")
    g = _grid({"accent": "#C05151", "bg_main": bg.name()})
    g.set_data(cache, {"current": 0, "longest": 0}, set(), today)
    assert _cell_pixel(g, bg, 3).name() != g._empty.name()


def test_old_key_names_are_gone_and_new_ones_never_inherit():
    for name, theme in THEMES.items():
        assert "streak_grid_outline" not in theme and "streak_grid_dot" not in theme, name
    for k in _KEYS:
        assert k in _NO_BASE_INHERIT_KEYS
