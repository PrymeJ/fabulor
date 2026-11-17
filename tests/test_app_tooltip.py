"""In-window tooltip (ui/app_tooltip.py): placement arithmetic and the
ToolTip-event path, offscreen. Says nothing about how it LOOKS — that is a
live check."""
import pytest
from PySide6.QtCore import QEvent, QPoint
from PySide6.QtGui import QHelpEvent
from PySide6.QtWidgets import QApplication, QPushButton, QToolTip, QWidget

from fabulor.ui import app_tooltip
from fabulor.ui.app_tooltip import place_tip

W, H = 300, 564


def test_fits_below_right_of_cursor():
    pos = place_tip(QPoint(50, 100), 120, 40, W, H)
    assert pos.x() >= 50 and pos.y() > 100          # below, never over the cursor


def test_slides_left_to_stay_on_one_line():
    pos = place_tip(QPoint(250, 100), 200, 40, W, H)
    assert pos.x() + 200 <= W - 4
    assert pos.y() > 100                            # still below, just slid


def test_flips_above_near_bottom():
    pos = place_tip(QPoint(100, 540), 120, 60, W, H)
    assert pos.y() + 60 < 540                       # entirely above the cursor


def test_never_leaves_window():
    for cx in (0, 150, 299):
        for cy in (0, 282, 563):
            pos = place_tip(QPoint(cx, cy), 180, 70, W, H)
            assert 0 <= pos.x() and pos.x() + 180 <= W
            assert 0 <= pos.y() and pos.y() + 70 <= H


@pytest.fixture
def window(qapp=None):
    app = QApplication.instance() or QApplication([])
    win = QWidget()
    win.resize(W, H)
    win.show()
    tip = app_tooltip.install(app, win)
    yield win, tip
    app.removeEventFilter(tip._filter)
    win.close()
    app_tooltip._instance = None


def test_tooltip_event_shows_in_window_label(window):
    win, tip = window
    btn = QPushButton("x", win)
    btn.setGeometry(240, 100, 40, 20)
    btn.setToolTip("Folders are named like 'Author - Title' (e.g. 'Stephen King - The Shining')")
    btn.show()
    gp = btn.mapToGlobal(QPoint(10, 10))
    ev = QHelpEvent(QEvent.Type.ToolTip, QPoint(10, 10), gp)
    QApplication.sendEvent(btn, ev)
    assert tip.isVisible()
    assert not QToolTip.isVisible()
    g = tip.geometry()
    assert g.x() >= 0 and g.x() + g.width() <= W
    assert g.y() >= 0 and g.y() + g.height() <= H


def test_long_text_wraps_inside_window(window):
    win, tip = window
    app_tooltip.show_text("/home/someone/" + "very/long/path/" * 20, win, win.mapToGlobal(QPoint(20, 20)))
    assert tip.width() <= W - 8
    assert tip.wordWrap()


def test_grab_guard_ignores_panel_hide(window):
    win, tip = window
    panel = QWidget(win)
    panel.setGeometry(0, 0, 270, 500)
    btn = QPushButton("x", panel)
    btn.setToolTip("Right-click to set as default")
    panel.show()
    QApplication.sendEvent(btn, QHelpEvent(QEvent.Type.ToolTip, QPoint(5, 5), btn.mapToGlobal(QPoint(5, 5))))
    assert tip.isVisible()
    with app_tooltip.suppress_for_grab():
        panel.hide()
        assert not tip.isVisible()          # not photographed
        panel.show()
    assert tip.isVisible()                  # and not closed by the grab's Hide
    panel.hide()                            # a real hide does close it
    assert not tip.isVisible()


def test_own_wake_shows_without_qt_tooltip_event(window):
    """With the blur grab running, Qt never sends ToolTip; our own hover
    delay must show the tooltip from an Enter alone."""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QEnterEvent, QCursor
    win, tip = window
    btn = QPushButton("x", win)
    btn.setGeometry(100, 100, 40, 20)
    btn.setToolTip("Right-click to set as default")
    btn.show()
    QCursor.setPos(btn.mapToGlobal(QPoint(10, 10)))
    local = QPointF(10, 10)
    QApplication.sendEvent(btn, QEnterEvent(local, local, QPointF(btn.mapToGlobal(QPoint(10, 10)))))
    tip._filter._wake.timeout.emit()   # fire the delay without waiting
    assert tip.isVisible()
    assert tip.text() == "Right-click to set as default"


def test_grab_enter_does_not_arm_wake(window):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QEnterEvent
    win, tip = window
    btn = QPushButton("x", win)
    btn.setToolTip("t")
    btn.show()
    local = QPointF(5, 5)
    with app_tooltip.suppress_for_grab():
        QApplication.sendEvent(btn, QEnterEvent(local, local, local))
    assert tip._filter._pending is None


def test_hover_event_on_a_qwindow_does_not_raise(window):
    """Enter/Hover events also reach QWindow objects (not QWidgets); with a
    hover delay pending, that used to make isAncestorOf() raise."""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QEnterEvent
    win, tip = window
    btn = QPushButton("x", win)
    btn.setToolTip("t")
    btn.show()
    local = QPointF(5, 5)
    QApplication.sendEvent(btn, QEnterEvent(local, local, local))
    assert tip._filter._pending is not None
    qwin = win.windowHandle()
    assert qwin is not None
    tip._filter._on_hover(qwin, QEnterEvent(local, local, local))  # must not raise
    assert tip._filter._pending is not None
