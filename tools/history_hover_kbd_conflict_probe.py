"""Verify keyboard-selecting a History row, then moving the mouse onto a
DIFFERENT row, leaves exactly one row in '_state == hover' — not two.
Reported live, 2026-08-12: arrow-selecting a row then hovering a different
one with the mouse showed two simultaneous X icons (three when a delete
confirmation was also armed on a third row).

Run with a real platform plugin:
    LD_PRELOAD=/usr/lib64/libstdc++.so.6 python tools/history_hover_kbd_conflict_probe.py
"""
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, QEvent, QPointF
from PySide6.QtGui import QEnterEvent


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
            if len(rows) < 3:
                print("Not enough rows to test — need at least 3.")
                app.quit()
                return

            # Keyboard-select row index 2 (arrow down twice from -1).
            panel._move_history_selection(1)
            panel._move_history_selection(1)
            print(f"After 2x Down-arrow: _history_selected_index={panel._history_selected_index}")
            print(f"  row[2]._state = {rows[2]._state!r}")

            # Simulate real mouse entering row 0 (a DIFFERENT row).
            ev = QEnterEvent(QPointF(5, 5), QPointF(5, 5), QPointF(5, 5))
            app.sendEvent(rows[0], ev)

            hover_rows = [i for i, r in enumerate(rows) if r._state == 'hover']
            print(f"After mouse enters row[0]: hover-state rows = {hover_rows}")
            print(f"  row[0]._state = {rows[0]._state!r}")
            print(f"  row[2]._state = {rows[2]._state!r}")
            print(f"  _history_selected_index = {panel._history_selected_index}")

            print("-" * 62)
            print(f"EXACTLY ONE ROW IN HOVER STATE: {len(hover_rows) == 1}")

            app.quit()

        QTimer.singleShot(500, do_test)

    QTimer.singleShot(600, report)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
