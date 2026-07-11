"""Behavior contract for StatsPanel.keyPressEvent (Day/Week/Month Left/Right nav).

StatsPanel is granted real Qt focus while open (PanelManager._claim_panel_focus — it isn't
in panel_tab_widgets, so the panel root itself is the claim target), so its own
keyPressEvent is where Left/Right must be handled, same shape as ChapterList's own
keyPressEvent. The hard requirement is REUSE: Left/Right on the Day/Week/Month tabs must
call the exact same `_day_prev`/`_day_next`/`_week_prev`/`_week_next`/`_month_prev`/
`_month_next` methods the mouse `‹`/`›` buttons already use — no new nav math.

Standing up a real StatsPanel needs a DB + the full widget tree, so — following the
pattern in test_panel_exclusion.py — this binds the REAL unbound `keyPressEvent` to a tiny
fake supplying only `tabs` (for `tabText`/`currentIndex`) and the six nav methods.
"""
import pytest
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QKeyEvent

from fabulor.ui.stats_panel import StatsPanel


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeTabs:
    def __init__(self, text):
        self._text = text

    def currentIndex(self):
        return 0

    def tabText(self, index):
        return self._text


class _FakeStatsPanel(StatsPanel):
    """A real StatsPanel SUBCLASS (so keyPressEvent's zero-arg super() call, which resolves
    via __class__=StatsPanel at compile time and requires isinstance(obj, StatsPanel), works
    correctly) whose __init__ deliberately skips the heavy DB-dependent UI build — supplies
    only what keyPressEvent actually reads: tabs + the six nav methods."""
    def __init__(self, active_tab):
        QWidget.__init__(self)   # bypass StatsPanel.__init__ (needs db/config, builds UI)
        self.tabs = _FakeTabs(active_tab)
        self.calls = []

    def _day_prev(self):   self.calls.append("day_prev")
    def _day_next(self):   self.calls.append("day_next")
    def _week_prev(self):  self.calls.append("week_prev")
    def _week_next(self):  self.calls.append("week_next")
    def _month_prev(self): self.calls.append("month_prev")
    def _month_next(self): self.calls.append("month_next")


def _press(obj, key):
    ev = QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
    obj.keyPressEvent(ev)


@pytest.mark.parametrize("tab,left_method,right_method", [
    ("Day", "day_prev", "day_next"),
    ("Week", "week_prev", "week_next"),
    ("Month", "month_prev", "month_next"),
])
def test_left_right_call_the_matching_tabs_nav_methods(qapp, tab, left_method, right_method):
    fake = _FakeStatsPanel(active_tab=tab)
    _press(fake, Qt.Key.Key_Left)
    assert fake.calls == [left_method]
    _press(fake, Qt.Key.Key_Right)
    assert fake.calls == [left_method, right_method]


@pytest.mark.parametrize("tab", ["Overall", "Timeline", "⚙"])
def test_left_right_no_op_on_tabs_without_nav(qapp, tab):
    # Overall/Timeline/Options have no prev/next concept; Left/Right must not call
    # any of the six nav methods (falls through to super().keyPressEvent instead).
    fake = _FakeStatsPanel(active_tab=tab)
    _press(fake, Qt.Key.Key_Left)
    _press(fake, Qt.Key.Key_Right)
    assert fake.calls == []


def test_other_keys_are_untouched(qapp):
    # Only Left/Right are intercepted; anything else must not call a nav method.
    fake = _FakeStatsPanel(active_tab="Day")
    _press(fake, Qt.Key.Key_Up)
    _press(fake, Qt.Key.Key_Space)
    assert fake.calls == []
