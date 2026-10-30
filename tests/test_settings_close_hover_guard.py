"""No theme hover preview may land once a Settings close has started.

Live 2026-10-30 06:04:42-44 (fabulor.log): the close flow stopped the hover debounce at entry,
but a swatch enter in the 150ms settle gap re-armed it; it fired mid-slide, queued behind the
panel animation, and applied after Settings had closed, leaving the main window on the
previewed theme. See review/Spec_261030_settings_close_hover_leak.md.

Primary guard: _fire_pending_hover. Backstop: _on_theme_changed (via _hover_call_is_stale).
Stand-ins replace Qt objects; tripwires go to the temp file conftest.py redirects to."""
import pytest
from PySide6.QtCore import QAbstractAnimation, QPoint
from PySide6.QtWidgets import QApplication

from fabulor.ui.panels import PanelManager
from fabulor.ui.theme_manager import ThemeManager


@pytest.fixture(autouse=True)
def qapp():
    yield QApplication.instance() or QApplication([])


class _Anim:
    def __init__(self, running=False, end_x=0):
        self._running, self._end = running, QPoint(end_x, 56)

    def state(self):
        return (QAbstractAnimation.State.Running if self._running
                else QAbstractAnimation.State.Stopped)

    def endValue(self):
        return self._end


class _Panel:
    def __init__(self, visible):
        self._visible = visible

    def isVisible(self):
        return self._visible


# (visible, close_pending, animation running, animation end x) -> accepts hover previews
STATES = {
    "open_idle":     ((True,  False, False, 0),    True),
    "opening_slide": ((True,  False, True,  0),    True),
    "close_pending": ((True,  True,  False, 0),    False),
    "slide_out":     ((True,  False, True,  -270), False),
    "hidden":        ((False, False, False, -270), False),
}


def _panel_manager(visible, close_pending, running, end_x):
    pm = PanelManager.__new__(PanelManager)
    pm.settings_panel = _Panel(visible)
    pm.settings_panel_animation = _Anim(running, end_x)
    if close_pending:
        pm._settings_close_pending = True
    return pm


def _theme_manager(state):
    tm = ThemeManager.__new__(ThemeManager)
    tm.main_window = type("MW", (), {})()
    tm.main_window.panel_manager = _panel_manager(*STATES[state][0])
    tm.config = type("Cfg", (), {"get_theme_fade_duration": lambda self: 750})()
    tm._pending_hover_theme = "Yellow Wallpaper"
    tm._hover_seen_at = None
    tm._kbdnav_swatch_pos = None
    tm.calls = []
    tm._on_theme_changed = lambda *a, **k: tm.calls.append((a, k))
    return tm


@pytest.mark.parametrize("state", list(STATES), ids=list(STATES))
def test_predicate(state):
    args, expected = STATES[state]
    assert _panel_manager(*args).settings_accepts_hover_preview() is expected


@pytest.mark.parametrize("state", ["close_pending", "slide_out", "hidden"],
                         ids=["close_pending", "slide_out", "hidden"])
def test_debounce_cannot_fire_a_preview_once_settings_is_closing(state, _isolated_tripwires):
    tm = _theme_manager(state)
    ThemeManager._fire_pending_hover(tm)
    assert tm.calls == []
    assert "[HOVER-PREVIEW-DROPPED-SETTINGS-CLOSING]" in _isolated_tripwires.read_text()


@pytest.mark.parametrize("state", ["open_idle", "opening_slide"], ids=["open_idle", "opening_slide"])
def test_debounce_still_fires_while_settings_is_open(state, _isolated_tripwires):
    tm = _theme_manager(state)
    ThemeManager._fire_pending_hover(tm)
    assert len(tm.calls) == 1 and tm.calls[0][1].get("hover") is True
    assert not _isolated_tripwires.exists()


def test_queued_hover_replay_is_dropped_once_settings_is_closing(_isolated_tripwires):
    tm = _theme_manager("hidden")
    del tm._on_theme_changed                      # the real method, not the recorder
    ThemeManager._on_theme_changed(tm, "Yellow Wallpaper", save=False, fade_ms=375, hover=True)
    # Returned before any branch: none of the stand-in-less state it would touch was needed.
    assert "[HOVER-REPLAY-DROPPED-SETTINGS-CLOSING]" in _isolated_tripwires.read_text()


@pytest.mark.parametrize("state", list(STATES), ids=list(STATES))
def test_backstop_never_stops_a_real_selection_or_snapback(state, _isolated_tripwires):
    tm = _theme_manager(state)
    assert ThemeManager._hover_call_is_stale(tm, "Anomander", hover=False) is False
    assert not _isolated_tripwires.exists()


@pytest.mark.parametrize("state", ["open_idle", "opening_slide"], ids=["open_idle", "opening_slide"])
def test_backstop_lets_a_hover_through_while_settings_is_open(state, _isolated_tripwires):
    tm = _theme_manager(state)
    assert ThemeManager._hover_call_is_stale(tm, "Yellow Wallpaper", hover=True) is False
    assert not _isolated_tripwires.exists()
