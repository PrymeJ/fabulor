"""Full real-path repro: mouse-click _trash_btn to arm a confirmation, THEN
send a real QKeyEvent (not a direct _move_history_selection() call) to
whatever widget actually holds focus at that point — closer to what a real
user does than history_confirm_focus_probe.py (which only checked
focusWidget() identity, never actually sent a key).

Run with a real platform plugin:
    LD_PRELOAD=/usr/lib64/libstdc++.so.6 python tools/history_confirm_then_key_probe.py
"""
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from PySide6.QtCore import Qt, QTimer, QEvent
from PySide6.QtGui import QMouseEvent, QKeyEvent
from PySide6.QtWidgets import QApplication


def _row_h(rows):
    from fabulor.ui.book_detail_panel import _HistoryRow
    return _HistoryRow.ROW_H


def main():
    app = QApplication(sys.argv)
    from fabulor.app import MainWindow

    mw = MainWindow()
    mw.show()

    def report():
        db = mw.db
        with db._get_conn() as conn:
            row = conn.execute(
                "SELECT book_path, COUNT(*) as n FROM listening_sessions "
                "GROUP BY book_path ORDER BY n DESC LIMIT 1"
            ).fetchone()
        if row is None:
            print("No book with listening sessions found — cannot probe.")
            app.quit()
            return
        mw.panel_manager.open_book_detail({"path": row[0]}, tab="history")

        def do_test():
            panel = mw.book_detail_panel
            rows = panel._history_rows
            if len(rows) < 2:
                print("Not enough rows.")
                app.quit()
                return

            row0 = rows[0]
            btn = row0._trash_btn
            center = btn.rect().center()
            press = QMouseEvent(QMouseEvent.Type.MouseButtonPress, center,
                                 btn.mapToGlobal(center),
                                 Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                                 Qt.KeyboardModifier.NoModifier)
            release = QMouseEvent(QMouseEvent.Type.MouseButtonRelease, center,
                                   btn.mapToGlobal(center),
                                   Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
                                   Qt.KeyboardModifier.NoModifier)
            app.sendEvent(btn, press)
            app.sendEvent(btn, release)
            print(f"Armed row0: state={row0._state!r}  "
                  f"confirming_row is row0={panel._confirming_history_row is row0}")

            bar = panel._history_scroll.verticalScrollBar()
            print(f"Scrollbar value BEFORE key: {bar.value()}")
            print(f"panel._history_selected_index BEFORE key: {panel._history_selected_index}")

            fw = app.focusWidget()
            print(f"focusWidget() before key = {fw}")

            # Send several REAL Down key events to whatever holds focus, via app.sendEvent —
            # this goes through the full Qt dispatch, unlike calling
            # _move_history_selection() directly. Walk past the armed row to see if
            # something breaks further along, not just on the first step.
            h = _row_h(rows)
            for i in range(8):
                key_press = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down,
                                       Qt.KeyboardModifier.NoModifier)
                handled = app.sendEvent(fw, key_press)
                idx = panel._history_selected_index
                v = bar.value()
                hover_rows = [j for j, r in enumerate(rows) if r._state == 'hover']
                print(f"step {i+1}: sendEvent returned={handled}  selected_index={idx}  "
                      f"scrollbar={v} (v%h={v % h if h else 'n/a'})  hover_rows={hover_rows}")

            print("-" * 62)
            print("Now Left arrow (should cycle tab):")
            fw2 = app.focusWidget()
            key_press = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Left,
                                   Qt.KeyboardModifier.NoModifier)
            handled = app.sendEvent(fw2, key_press)
            print(f"sendEvent(Left) returned={handled}  current tab={panel.tabs.tabText(panel.tabs.currentIndex())}")

            app.quit()

        QTimer.singleShot(500, do_test)

    QTimer.singleShot(600, report)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
