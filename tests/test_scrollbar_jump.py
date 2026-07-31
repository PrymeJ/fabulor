"""Right-click-to-jump on scrollbars (ui/scrollbar_jump.py).

Pins the value mapping and, just as importantly, what the filter must NOT touch:
left-click paging and any non-scrollbar widget. The filter is installed on the
QApplication, so a regression here would silently change mouse behaviour
app-wide rather than in one panel.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QScrollBar, QSlider

from fabulor.ui.scrollbar_jump import ScrollBarJumpFilter


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def jump_filter():
    return ScrollBarJumpFilter()


def _bar(app, orientation=Qt.Orientation.Vertical, maximum=626, page=312, length=312):
    bar = QScrollBar(orientation)
    bar.setRange(0, maximum)
    bar.setPageStep(page)
    if orientation == Qt.Orientation.Vertical:
        bar.resize(8, length)
    else:
        bar.resize(length, 8)
    bar.show()
    app.processEvents()
    return bar


def _press(app, widget, filt, x, y, button=Qt.MouseButton.RightButton):
    """Send a press through the filter exactly as QApplication would."""
    event = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress, QPointF(x, y),
        widget.mapToGlobal(QPoint(int(x), int(y))),
        button, button, Qt.KeyboardModifier.NoModifier)
    if filt.eventFilter(widget, event):
        return True          # consumed; widget never sees it
    app.sendEvent(widget, event)
    return False


def test_right_click_midpoint_jumps_to_middle(app, jump_filter):
    bar = _bar(app)
    _press(app, bar, jump_filter, 4, 156)
    # Handle-centred mapping, so the midpoint lands mid-range (not exact: the
    # handle's length is subtracted from the usable span).
    assert 280 < bar.value() < 350


def test_right_click_reaches_both_extremes(app, jump_filter):
    bar = _bar(app)
    _press(app, bar, jump_filter, 4, 0)
    assert bar.value() == bar.minimum()
    _press(app, bar, jump_filter, 4, 311)
    assert bar.value() == bar.maximum()


def test_right_click_is_monotonic_down_the_groove(app, jump_filter):
    bar = _bar(app)
    seen = []
    for y in range(0, 312, 20):
        _press(app, bar, jump_filter, 4, y)
        seen.append(bar.value())
    assert seen == sorted(seen), seen


def test_right_click_is_consumed(app, jump_filter):
    """Must return True so the native context menu never opens."""
    bar = _bar(app)
    assert _press(app, bar, jump_filter, 4, 100) is True


def test_context_menu_event_is_suppressed(app, jump_filter):
    """The native menu rides on QEvent.ContextMenu, NOT on the mouse press.

    This is the gap the first version shipped with: the press was consumed, the
    handle jumped correctly, and the system menu still appeared. A regression
    here is invisible to every other test in this file."""
    from PySide6.QtGui import QContextMenuEvent

    bar = _bar(app)
    event = QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse, QPoint(4, 100),
        bar.mapToGlobal(QPoint(4, 100)))
    assert jump_filter.eventFilter(bar, event) is True


def test_context_menu_on_other_widgets_is_untouched(app, jump_filter):
    """Text fields have their own themed Cut/Copy/Paste menu — suppressing
    ContextMenu app-wide instead of per-scrollbar would silently kill it."""
    from PySide6.QtGui import QContextMenuEvent
    from PySide6.QtWidgets import QLineEdit

    field = QLineEdit()
    field.resize(120, 24)
    field.show()
    app.processEvents()
    event = QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse, QPoint(20, 12),
        field.mapToGlobal(QPoint(20, 12)))
    assert jump_filter.eventFilter(field, event) is False


def test_left_click_is_not_intercepted(app, jump_filter):
    """Gutter left-click keeps its page-step behaviour."""
    bar = _bar(app)
    bar.setValue(0)
    consumed = _press(app, bar, jump_filter, 4, 250, button=Qt.MouseButton.LeftButton)
    assert consumed is False
    assert bar.value() == bar.pageStep()  # paged, not jumped


def test_rangeless_bar_is_consumed_without_crashing(app, jump_filter):
    """A bar whose handle fills the groove has nowhere to jump; still consume,
    since every entry of the menu it suppresses would no-op there anyway."""
    bar = _bar(app, maximum=0)
    assert _press(app, bar, jump_filter, 4, 50) is True
    assert bar.value() == 0


def test_horizontal_bar_maps_on_x(app, jump_filter):
    bar = _bar(app, orientation=Qt.Orientation.Horizontal,
               maximum=500, page=100, length=300)
    _press(app, bar, jump_filter, 150, 4)
    assert 200 < bar.value() < 300


def test_non_scrollbar_widgets_are_untouched(app, jump_filter):
    """QSlider is a sibling QAbstractSlider — the filter must not claim it, or
    right-click behaviour changes on widgets that never had this menu."""
    slider = QSlider(Qt.Orientation.Vertical)
    slider.setRange(0, 100)
    slider.resize(20, 200)
    slider.show()
    app.processEvents()
    event = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress, QPointF(10, 100),
        slider.mapToGlobal(QPoint(10, 100)),
        Qt.MouseButton.RightButton, Qt.MouseButton.RightButton,
        Qt.KeyboardModifier.NoModifier)
    assert jump_filter.eventFilter(slider, event) is False
