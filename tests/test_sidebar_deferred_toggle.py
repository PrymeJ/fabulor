"""A sidebar click deferred during a slide must not open the sidebar over a panel.

Live-traced 2026-10-30 (fabulor.log 15:56:44-15:57:19): Library was chosen from the sidebar,
so the sidebar slid closed to hand off. A second right-click 243ms into that slide was
deferred by `_toggle_sidebar` as "end up open"; its replay ran after the Library finished
opening and slid the sidebar in over it. Pryme hits this with an accidental double click,
which can't be produced on demand, so this drives the same decision sequence with
stand-in animation/timer objects and the real `_toggle_sidebar`."""
import pytest
from PySide6.QtCore import QAbstractAnimation
from PySide6.QtWidgets import QApplication

from fabulor.ui.panels import PanelManager


@pytest.fixture(autouse=True)
def qapp():
    yield QApplication.instance() or QApplication([])


class _Anim:
    def __init__(self):
        self.running = False
        self.starts = 0

    def state(self):
        return (QAbstractAnimation.State.Running if self.running
                else QAbstractAnimation.State.Stopped)

    def setStartValue(self, v): self._start = v
    def setEndValue(self, v): self._end = v
    def startValue(self): return self._start
    def endValue(self): return self._end

    def start(self):
        self.starts += 1


class _Stub:
    def __getattr__(self, name):
        return lambda *a, **k: 70 if name == "width" else None


def _pm(panel_open):
    pm = PanelManager.__new__(PanelManager)
    pm.main_window = type("MW", (), {})()
    pm.sidebar = _Stub()
    pm._sidebar_idle_poll_timer = _Stub()
    pm.sidebar_animation = _Anim()
    pm.sidebar_expanded = False          # the in-flight slide is CLOSING the sidebar
    pm._sidebar_pending_target = None
    pm._sidebar_toggle_queued = False
    pm._sidebar_opened_via = "right_click"
    pm._waiters = []
    pm.call_when_panels_settled = pm._waiters.append
    pm.is_overlay_open_or_committed = lambda: panel_open[0]
    return pm


def _second_click_during_close_slide(panel_opens_meanwhile):
    panel_open = [False]
    pm = _pm(panel_open)
    pm.sidebar_animation.running = True
    pm._toggle_sidebar()                  # the stray second click: deferred
    assert pm._sidebar_pending_target is True and len(pm._waiters) == 1
    pm.sidebar_animation.running = False  # close slide finished
    panel_open[0] = panel_opens_meanwhile # the handoff opened the Library (or not)
    pm._waiters.pop()()                   # everything settled: the replay runs
    return pm


def test_deferred_open_is_dropped_once_a_panel_took_over():
    pm = _second_click_during_close_slide(panel_opens_meanwhile=True)
    assert pm.sidebar_expanded is False
    assert pm.sidebar_animation.starts == 0


def test_deferred_open_still_applies_with_no_panel():
    # The 2026-07-28 behavior this must keep: a click during a slide is not lost.
    pm = _second_click_during_close_slide(panel_opens_meanwhile=False)
    assert pm.sidebar_expanded is True
    assert pm.sidebar_animation.starts == 1
