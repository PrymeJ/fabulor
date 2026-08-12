"""Verify _move_history_selection's arrow-key navigation keeps the History
tab's scroll position aligned to ROW_H (via _HistoryScrollArea.scroll_to_row,
not the default ensureWidgetVisible) — reported live, 2026-08-12: after a long
Down-arrow run, the first visible row's y-position had visibly shifted
compared to before navigating, meaning the scrollbar had landed off a row
boundary.

Same "read the real widget tree after a real show()" shape as the other
tools/history_*_probe.py scripts.

Run with a real platform plugin:
    LD_PRELOAD=/usr/lib64/libstdc++.so.6 python tools/history_keyboard_nav_probe.py
"""
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer


def main():
    app = QApplication(sys.argv)
    from fabulor.app import MainWindow
    from fabulor.ui.book_detail_panel import _HistoryRow

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
            print("No book with listening sessions found in this DB — cannot probe.")
            app.quit()
            return
        book_path = row[0]
        mw.panel_manager.open_book_detail({"path": book_path}, tab="history")

        def do_nav_test():
            panel = mw.book_detail_panel
            scroll = panel._history_scroll
            bar = scroll.verticalScrollBar()
            h = _HistoryRow.ROW_H
            n_rows = len(panel._history_rows)

            print("=" * 62)
            print(f"ROW_H={h}  row count={n_rows}  bar min/max={bar.minimum()}/{bar.maximum()}")
            print(f"initial bar value={bar.value()}  (value % h = {bar.value() % h})")

            misaligned = []
            # Walk all the way down, one Down-arrow at a time.
            for i in range(n_rows - 1):
                panel._move_history_selection(1)
                v = bar.value()
                aligned = (v % h == 0)
                if not aligned:
                    misaligned.append((i, v, v % h))

            print(f"after walking all {n_rows - 1} Down-arrows: bar value={bar.value()}")
            print(f"misaligned steps (index, value, remainder): {misaligned[:10]}"
                  f"{' ...' if len(misaligned) > 10 else ''}")
            print(f"total misaligned steps: {len(misaligned)} / {n_rows - 1}")

            # Now walk back up, one Up-arrow at a time, checking again.
            misaligned_up = []
            for i in range(n_rows - 1):
                panel._move_history_selection(-1)
                v = bar.value()
                aligned = (v % h == 0)
                if not aligned:
                    misaligned_up.append((i, v, v % h))

            print(f"after walking all the way back up: bar value={bar.value()} "
                  f"(should be back to 0)")
            print(f"misaligned steps on the way up: {len(misaligned_up)} / {n_rows - 1}")

            print("-" * 62)
            print(f"ALL DOWN-STEPS ALIGNED: {len(misaligned) == 0}")
            print(f"ALL UP-STEPS ALIGNED:   {len(misaligned_up) == 0}")
            print(f"RETURNED TO 0:          {bar.value() == 0}")

            app.quit()

        QTimer.singleShot(500, do_nav_test)

    QTimer.singleShot(600, report)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
