"""Report the Book Detail Panel's History tab real vertical geometry from the
RUNNING app — same shape as tools/tags_geometry_probe.py (read the real widget
tree after a real show(), no offscreen reconstruction; see that file's
docstring for why).

Investigation-only: prints measurements so we can compute whether ROW_H (27)
divides the scroll viewport's real height evenly, and if not, what the
remainder is. Does NOT judge whether anything looks right — that's the user's
call, always.

Run with a real platform plugin:
    LD_PRELOAD=/usr/lib64/libstdc++.so.6 python tools/history_tab_geometry_probe.py
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
        # Find the book with the most listening_sessions rows, matching what
        # the screenshot showed (many rows, enough to overflow the viewport).
        with db._get_conn() as conn:
            row = conn.execute(
                "SELECT book_path, COUNT(*) as n FROM listening_sessions "
                "GROUP BY book_path ORDER BY n DESC LIMIT 1"
            ).fetchone()
        if row is None:
            print("No book with listening sessions found in this DB — cannot probe.")
            app.quit()
            return
        book_path, n_sessions = row[0], row[1]
        print(f"Using book: {book_path}  ({n_sessions} sessions)")

        # load_book() self-heals a bare {'path': ...} dict via db.get_book() when
        # 'duration' is missing (book_detail_panel.py load_book, ~line 759) — no
        # need to pre-fetch the full Book row here.
        mw.panel_manager.open_book_detail({"path": book_path}, tab="history")

        def report_geometry():
            panel = mw.book_detail_panel
            scroll = panel._history_scroll
            container = panel._history_container
            layout = panel._history_layout
            rows = panel._history_rows

            print("=" * 62)
            print(f"panel height            : {panel.height()}  (expected 564-32=532)")
            print(f"tabs height             : {panel.tabs.height()}")
            print(f"scroll area height      : {scroll.height()}")
            print(f"viewport height         : {scroll.viewport().height()}")
            print(f"container height        : {container.height()}")
            print(f"container sizeHint      : {container.sizeHint().height()}")
            print(f"row count               : {len(rows)}")
            print(f"ROW_H (class constant)  : {_HistoryRow.ROW_H}")

            if rows:
                h = rows[0].height()
                vp = scroll.viewport().height()
                # No inter-row spacing in this widget (layout.setSpacing(0)) —
                # unlike tags_geometry_probe's pitch = h + spacing, here
                # pitch == h exactly, confirmed by _history_layout.setSpacing(0)
                # at construction (book_detail_panel.py ~line 453).
                n_fit = vp // h
                exact = n_fit * h
                print(f"rows fully visible      : {n_fit}")
                print(f"height for {n_fit} rows       : {exact}")
                print(f"viewport - that         : {vp - exact}   <-- 0 means exact fit, "
                      f"nonzero means a partial row is visible")
                ys = [r.y() for r in rows[:8]]
                print(f"first row y positions   : {ys}")
                deltas = [b - a for a, b in zip(ys, ys[1:])]
                print(f"y deltas                : {deltas}   <-- must all equal {h}")

            print(f"scroll y within panel   : "
                  f"{scroll.mapTo(panel, scroll.rect().topLeft()).y()}")
            print(f"scrollbar policy         : "
                  f"{scroll.verticalScrollBarPolicy()}  (ScrollBarAlwaysOff expected)")

            app.quit()

        QTimer.singleShot(400, report_geometry)  # let the slide-in animation land

    QTimer.singleShot(600, report)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
