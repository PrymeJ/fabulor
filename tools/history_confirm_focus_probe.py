"""Trace exactly what holds Qt focus after arming a History row's delete
confirmation via a real mouse click on _trash_btn. Reported live, 2026-08-12:
after arming via mouse, Up/Down scrolled the list (no X, partial rows again)
and Left/Right stopped switching tabs — both symptoms point at
BookDetailPanel.keyPressEvent not being reached at all, i.e. focus is
somewhere else, despite _trash_btn already being set to NoFocus.

Run with a real platform plugin:
    LD_PRELOAD=/usr/lib64/libstdc++.so.6 python tools/history_confirm_focus_probe.py
"""
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from PySide6.QtCore import Qt, QTimer, QPoint
from PySide6.QtGui import QMouseEvent
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
            if not rows:
                print("No rows to test.")
                app.quit()
                return

            row0 = rows[0]
            print("=" * 62)
            print(f"BEFORE click: focusWidget() = {app.focusWidget()}")
            print(f"  panel.hasFocus() = {panel.hasFocus()}")

            # Real mouse press+release on the trash button, same as a genuine click.
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

            print(f"AFTER click on _trash_btn: row0._state = {row0._state!r}")
            print(f"  panel._confirming_history_row is row0: "
                  f"{panel._confirming_history_row is row0}")
            fw = app.focusWidget()
            print(f"  focusWidget() = {fw}")
            print(f"  focusWidget() is panel: {fw is panel}")
            print(f"  panel.hasFocus() = {panel.hasFocus()}")
            if fw is not None:
                print(f"  focusWidget().focusPolicy() = {fw.focusPolicy()}")
                print(f"  focusWidget() parent chain: ", end="")
                w = fw
                chain = []
                while w is not None:
                    chain.append(type(w).__name__)
                    w = w.parent()
                print(" -> ".join(chain))

            app.quit()

        QTimer.singleShot(500, do_test)

    QTimer.singleShot(600, report)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
