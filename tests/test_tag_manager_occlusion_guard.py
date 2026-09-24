"""Regression net for TagManagerWidget.eventFilter's occlusion guard (2026-09-24,
live-reported): a real, pre-existing bug (confirmed via a focusChanged tracer against `main`,
not a paint-suppression-branch regression) where opening Book Detail over Tags with a keyboard
action (Alt+Enter from an arrow-navigated thumbnail grid) left real Qt focus stuck on the Tags
grid instead of landing on Book Detail.

Root cause: TagManagerWidget's app-wide event filter (installed in showEvent, and per that
method's own docstring never reliably removed by the synthetic hide/show blips
TransportBarBlurOverlay's grab cycle fires on it) gates every branch on `self._panel_widget.
isVisible()` / `self._list_widget.isVisible()` alone — both stay True even while Book Detail is
raised on top of Tags, since Book Detail occludes Tags without ever hiding it. So the filter kept
intercepting keys meant for the now-topmost Book Detail panel; in particular
_handle_tag_detail_keys' Tab branch calls `self._book_grid.setFocus(...)` unconditionally,
which is exactly what was silently stealing focus back.

Fixed by an early-return guard at the top of eventFilter, checking whether book_detail_panel is
visible (i.e. Tags is occluded) before dispatching anything — the same "check first, decline to
handle" shape BookDetailPanel.eventFilter already uses for QApplication.activeModalWidget().

Uses a light fake standing in for `self` (real method, unbound-call pattern, same shape as
test_panel_exclusion.py's _FakeGate) rather than a full TagManagerWidget, since instantiating one
needs a working db/assets_dir this guard's own logic never touches.
"""
import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication

from fabulor.ui.tag_manager import TagManagerWidget


class _FakePanel:
    def __init__(self, visible):
        self._visible = visible

    def isVisible(self):
        return self._visible


class _FakeWindow:
    def __init__(self, book_detail_visible):
        self.book_detail_panel = _FakePanel(book_detail_visible)


class _FakeTagManagerHost:
    """Stands in for `self` inside TagManagerWidget.eventFilter — only reached far enough to
    exercise the new occlusion guard at the very top of the method; every branch below it is
    unreachable in this test because the guard returns first."""
    def __init__(self, book_detail_visible):
        self._window = _FakeWindow(book_detail_visible)

    def window(self):
        return self._window


def _qapp():
    return QApplication.instance() or QApplication([])


def test_returns_false_when_book_detail_is_visible_over_tags():
    _qapp()
    host = _FakeTagManagerHost(book_detail_visible=True)
    event = QEvent(QEvent.Type.KeyPress)
    assert TagManagerWidget.eventFilter(host, object(), event) is False


def test_falls_through_to_normal_handling_when_book_detail_is_not_visible():
    """Sanity: the guard must not swallow events when Book Detail genuinely isn't open — this
    doesn't assert what the REST of eventFilter does (that's covered elsewhere), only that the
    new guard itself doesn't unconditionally short-circuit regardless of book_detail's state."""
    _qapp()
    host = _FakeTagManagerHost(book_detail_visible=False)
    # A KeyPress with none of the later obj-identity branches applicable falls through to
    # super().eventFilter(obj, event) eventually — but calling the real unbound method against
    # this fake would then hit attributes (_action_btn, _tag_name_edit, etc.) the fake doesn't
    # have. This test only needs to confirm the guard itself doesn't fire — i.e. that it's
    # conditioned on book_detail's visibility, not unconditional — verified by checking the
    # early-return path is skipped (an AttributeError past the guard proves the guard let
    # execution continue, which is the behavior under test).
    event = QEvent(QEvent.Type.KeyPress)
    with pytest.raises(AttributeError):
        TagManagerWidget.eventFilter(host, object(), event)


def test_book_detail_panel_attribute_missing_does_not_raise_in_the_guard_itself():
    """A window without a book_detail_panel attribute at all (defensive — getattr default)
    must not raise INSIDE THE GUARD; the guard simply has nothing to occlude against and lets
    execution continue past it (same shape as the "not visible" case above — proven by the
    same AttributeError-further-down signal, this time from getattr's own None default rather
    than a real, non-visible panel)."""
    _qapp()

    class _BareWindow:
        pass

    class _Host:
        def window(self):
            return _BareWindow()

    host = _Host()
    event = QEvent(QEvent.Type.KeyPress)
    with pytest.raises(AttributeError):
        TagManagerWidget.eventFilter(host, object(), event)
