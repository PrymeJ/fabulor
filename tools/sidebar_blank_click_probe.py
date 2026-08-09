"""One-shot check for the corner-hotspot sidebar plan (Plan_260809): does a click on the
sidebar's own blank area (not a nav button) already dismiss it today, via the EXISTING
right-click-open path and MainWindow.mousePressEvent's click-away, with no hotspot code
written yet?

Builds the real MainWindow (real db/config, same as every other tool in this directory),
opens it, synthesizes a right-click on visual_area (the same call _on_drag_area_pressed
makes), confirms the sidebar opened, then synthesizes a left-click on a blank point
inside the sidebar's own rect (below the last button, inside its margins) and reports
whether sidebar_expanded flipped back to False.

Run with a real platform plugin, matching tags_geometry_probe.py's own convention —
this is a click-ROUTING question (event delivery / geometry.contains() logic), not a
sub-pixel real-input hit-test quirk, so a synthesized QMouseEvent exercising the real
code path is adequate here (unlike the row-hittest last-pixel bug, which was proven
offscreen-blind specifically for real platform input at an exact boundary pixel).

    LD_PRELOAD=/usr/lib64/libstdc++.so.6 python tools/sidebar_blank_click_probe.py
"""
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from PySide6.QtCore import QPoint, QPointF, Qt, QTimer, QEvent
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication


def _click(widget, pos, button):
    press = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(pos), QPointF(widget.mapToGlobal(pos)),
                         button, button, Qt.KeyboardModifier.NoModifier)
    release = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(pos), QPointF(widget.mapToGlobal(pos)),
                           button, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, press)
    QApplication.sendEvent(widget, release)


def main():
    app = QApplication(sys.argv)
    from fabulor.app import MainWindow

    mw = MainWindow()
    mw.show()

    def step1_right_click_open():
        pm = mw.panel_manager
        print(f"[before right-click] sidebar_expanded={pm.sidebar_expanded} "
              f"book_count={mw.db.get_book_count()}")
        center = mw.visual_area.rect().center()
        _click(mw.visual_area, QPoint(center.x(), center.y()), Qt.MouseButton.RightButton)
        QTimer.singleShot(400, step2_check_opened)

    def step2_check_opened():
        pm = mw.panel_manager
        print(f"[after right-click] sidebar_expanded={pm.sidebar_expanded} "
              f"sidebar_pos={mw.sidebar.pos()} sidebar_size={mw.sidebar.size()}")
        if not pm.sidebar_expanded:
            print("RESULT: sidebar did not open via right-click (book_count likely 0 or "
                  "guard blocked it) — cannot proceed with the blank-click check.")
            QTimer.singleShot(100, app.quit)
            return
        QTimer.singleShot(100, step3_click_blank_area)

    def step3_click_blank_area():
        pm = mw.panel_manager
        # A point inside the sidebar's own rect, below its last real button, inside its
        # own margins/spacing gaps — i.e. NOT on any QPushButton child.
        sb = mw.sidebar
        w = sb.width()
        h = sb.height()
        # sidebar_layout has 10,10,2,10 margins; last widget is sleep_cancel_btn overlay
        # near the sleep button. Bottom strip of the sidebar (near its bottom edge, inset
        # from the right/left margins) should be blank layout space.
        blank_pt_local = QPoint(int(w * 0.5), h - 5)
        global_pt = sb.mapToGlobal(blank_pt_local)
        # Deliver to the top-level window using window coordinates, exactly as real input
        # would arrive at MainWindow's own mousePressEvent (via child propagation or the
        # window itself if the child doesn't accept it).
        window_pt = mw.mapFromGlobal(global_pt)
        print(f"[blank click] sidebar-local={blank_pt_local} window-local={window_pt} "
              f"sidebar_geom={sb.geometry()}")
        child = sb.childAt(blank_pt_local)
        print(f"[blank click] child widget under point: {child!r}")
        _click(mw, window_pt, Qt.MouseButton.LeftButton)
        QTimer.singleShot(400, step4_report)

    def step4_report():
        pm = mw.panel_manager
        print(f"[after blank click] sidebar_expanded={pm.sidebar_expanded}")
        if pm.sidebar_expanded:
            print("RESULT: sidebar STAYED OPEN after blank-area click — new dismiss code IS needed.")
        else:
            print("RESULT: sidebar CLOSED after blank-area click — already free, no new code needed for this case.")
        QTimer.singleShot(100, app.quit)

    QTimer.singleShot(500, step1_right_click_open)
    app.exec()


if __name__ == "__main__":
    main()
