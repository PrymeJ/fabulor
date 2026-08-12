"""Follow-up to history_hover_kbd_conflict_probe.py — covers the two gaps
found live after the first fix (2026-08-12):

1. Mouse hovers row A (real enterEvent, stays "physically" there — an arrow
   key doesn't move the cursor). Keyboard then navigates to row B. Row A's
   hover-X must clear even though row A.underMouse() stays True the whole
   time (this is why set_keyboard_selected(False)'s guard can't be reused
   for this direction — force_idle_from_hover() bypasses it deliberately).

2. _trash_btn must have Qt.FocusPolicy.NoFocus — clicking it (arming a
   delete confirmation) must not steal real Qt focus from BookDetailPanel,
   or Up/Down never reach _move_history_selection at all and instead
   fall through to native QScrollArea arrow-key scrolling.

Run with a real platform plugin:
    LD_PRELOAD=/usr/lib64/libstdc++.so.6 python tools/history_hover_kbd_conflict_probe2.py
"""
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from PySide6.QtCore import Qt, QTimer, QPointF
from PySide6.QtGui import QEnterEvent
from PySide6.QtWidgets import QApplication


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

            print("=" * 62)
            print("TEST 1: real mouse hover on row[0], then keyboard navigates to row[1]")
            ev = QEnterEvent(QPointF(5, 5), QPointF(5, 5), QPointF(5, 5))
            app.sendEvent(rows[0], ev)
            print(f"  after mouse enters row[0]: row[0]._state={rows[0]._state!r}  "
                  f"underMouse={rows[0].underMouse()}")

            panel._move_history_selection(1)  # -1 -> 0
            panel._move_history_selection(1)  # 0 -> 1
            hover_rows = [i for i, r in enumerate(rows) if r._state == 'hover']
            print(f"  after 2x Down-arrow: _history_selected_index={panel._history_selected_index}")
            print(f"  hover-state rows = {hover_rows}")
            print(f"  row[0]._state={rows[0]._state!r}  row[1]._state={rows[1]._state!r}")
            test1_pass = hover_rows == [1]
            print(f"  TEST 1 PASS (only row[1] in hover): {test1_pass}")

            print("-" * 62)
            print("TEST 2: _trash_btn focus policy")
            trash_btn = rows[0]._trash_btn
            policy = trash_btn.focusPolicy()
            print(f"  rows[0]._trash_btn.focusPolicy() = {policy}")
            test2_pass = policy == Qt.FocusPolicy.NoFocus
            print(f"  TEST 2 PASS (NoFocus): {test2_pass}")

            print("=" * 62)
            print(f"ALL PASS: {test1_pass and test2_pass}")

            app.quit()

        QTimer.singleShot(500, do_test)

    QTimer.singleShot(600, report)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
