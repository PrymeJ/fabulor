"""Regression net for StatsPanel.eventFilter's occlusion guard (2026-09-25).

Added while investigating why Stats-sourced Book Detail opens cost more than Library-/Tags-
sourced ones (see NOTES.md, "Why Stats-sourced Book Detail opens cost more") — not a live-reported
correctness bug like the same-shaped Tags fix this mirrors (TagManagerWidget.eventFilter's own
OCCLUSION GUARD, tests/test_tag_manager_occlusion_guard.py).

StatsPanel installs a QApplication-wide event filter in showEvent, removed only in hideEvent.
Because Book Detail occludes (raises above) rather than hides Stats, this filter stays fully
installed and fully live for the whole time Book Detail is open on top of it — taxing every
single Qt event anywhere in the app, including all of Book Detail's own internally-generated
events, even though the filter's entire job (dismissing the "Reset all stats" 7s confirmation on
a stray key/click) can never legitimately fire while Stats is occluded and Book Detail holds real
Qt focus.

Checked before adding (not assumed safe): the confirmation this filter dismisses already has an
independent hard-timeout QTimer (_on_reset_stats's 7000ms singleShot -> _cancel_reset_stats) that
fires regardless of this filter, so silencing the filter while occluded cannot strand the
confirmation permanently.

Fixed with the same "check first, decline to handle" early-return shape as the Tags fix.

Uses a light fake standing in for `self` (real method, unbound-call pattern), same shape as
test_tag_manager_occlusion_guard.py, since instantiating a real StatsPanel needs a working
db/config this guard's own logic never touches.
"""
import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication

from fabulor.ui.stats_panel import StatsPanel


class _FakePanel:
    def __init__(self, visible):
        self._visible = visible

    def isVisible(self):
        return self._visible


class _FakePanelManager:
    def __init__(self, book_detail_visible):
        self.book_detail_panel = _FakePanel(book_detail_visible)


class _FakeStatsPanelHost:
    """Stands in for `self` inside StatsPanel.eventFilter — only reached far enough to exercise
    the new occlusion guard at the very top of the method; every branch below it is unreachable
    in this test because the guard returns first."""
    def __init__(self, book_detail_visible=None, has_panel_manager=True):
        if has_panel_manager:
            self._panel_manager = _FakePanelManager(book_detail_visible)


def _qapp():
    return QApplication.instance() or QApplication([])


def test_returns_false_when_book_detail_is_visible_over_stats():
    _qapp()
    host = _FakeStatsPanelHost(book_detail_visible=True)
    event = QEvent(QEvent.Type.KeyPress)
    assert StatsPanel.eventFilter(host, object(), event) is False


def test_falls_through_to_normal_handling_when_book_detail_is_not_visible():
    """Sanity: the guard must not swallow events when Book Detail genuinely isn't open — this
    doesn't assert what the REST of eventFilter does (that's covered elsewhere), only that the
    new guard itself doesn't unconditionally short-circuit regardless of book_detail's state.
    Reaching further into the method hits self._reset_confirm_label, which this fake doesn't
    have — that AttributeError is the proof execution continued past the guard."""
    _qapp()
    host = _FakeStatsPanelHost(book_detail_visible=False)
    event = QEvent(QEvent.Type.KeyPress)
    with pytest.raises(AttributeError):
        StatsPanel.eventFilter(host, object(), event)


def test_missing_panel_manager_does_not_raise_in_the_guard_itself():
    """A host with no _panel_manager attribute at all (defensive — getattr default, matches the
    existing getattr(getattr(self, '_panel_manager', None), 'book_detail_panel', None) pattern
    already used elsewhere in stats_panel.py) must not raise INSIDE THE GUARD; it simply has
    nothing to occlude against and lets execution continue past it (proven the same way as the
    "not visible" case above — a later AttributeError from a real branch, not from the guard)."""
    _qapp()
    host = _FakeStatsPanelHost(has_panel_manager=False)
    event = QEvent(QEvent.Type.KeyPress)
    with pytest.raises(AttributeError):
        StatsPanel.eventFilter(host, object(), event)
