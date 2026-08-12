"""Verify _HistoryScrollArea.wheelEvent snaps to whole ROW_H steps, by
synthesizing real QWheelEvents and reading the scrollbar value after each —
same "read the real widget tree after a real show()" shape as
tools/tags_geometry_probe.py and tools/history_tab_geometry_probe.py.

Run with a real platform plugin:
    LD_PRELOAD=/usr/lib64/libstdc++.so.6 python tools/history_wheel_probe.py
"""
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent


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

        def do_wheel_test():
            panel = mw.book_detail_panel
            scroll = panel._history_scroll
            bar = scroll.verticalScrollBar()
            h = _HistoryRow.ROW_H

            print("=" * 62)
            print(f"ROW_H={h}  scrollbar min={bar.minimum()} max={bar.maximum()}")
            print(f"initial value={bar.value()}")

            # One notch is angleDelta().y() == 120 on most mice.
            results = []
            for i in range(6):
                ev = QWheelEvent(
                    QPointF(10, 10), QPointF(10, 10),
                    QPoint(0, 0), QPoint(0, -120),
                    Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                    Qt.ScrollPhase.NoScrollPhase, False,
                )
                app.sendEvent(scroll.viewport(), ev)
                v = bar.value()
                results.append(v)
                print(f"after notch {i+1} (scroll down): value={v}  "
                      f"value % {h} = {v % h}")

            print("-" * 62)
            print("Now scrolling back up:")
            for i in range(6):
                ev = QWheelEvent(
                    QPointF(10, 10), QPointF(10, 10),
                    QPoint(0, 0), QPoint(0, 120),
                    Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                    Qt.ScrollPhase.NoScrollPhase, False,
                )
                app.sendEvent(scroll.viewport(), ev)
                v = bar.value()
                print(f"after notch {i+1} (scroll up): value={v}  "
                      f"value % {h} = {v % h}")

            all_aligned = all(v % h == 0 for v in results)
            print("-" * 62)
            print(f"ALL scroll-down values aligned to ROW_H: {all_aligned}")

            app.quit()

        QTimer.singleShot(500, do_wheel_test)

    QTimer.singleShot(600, report)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
