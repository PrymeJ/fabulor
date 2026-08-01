"""Report the Tags panel's real vertical geometry from the RUNNING app.

Why this exists: the Stats viewport work (2026-08-01) tried an offscreen
reconstruction of a panel's layout and got a number that failed an obvious
sanity check (same viewport height with a sibling section shown and hidden,
plus a propagateSizeHints() warning from the offscreen plugin). Reconstructing
a layout offscreen is a DIFFERENT render; reading geometry off the real widget
tree after a real show() is not.

So this builds the actual MainWindow, opens the Tags panel through its real
entry path, and prints what Qt actually allocated. Run it with a real platform
plugin (i.e. NOT QT_QPA_PLATFORM=offscreen) if you want numbers you can act on:

    LD_PRELOAD=/usr/lib64/libstdc++.so.6 python tools/tags_geometry_probe.py

It prints measurements only. It cannot tell you whether anything LOOKS right —
that is the user's call, always.
"""
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer


def main():
    app = QApplication(sys.argv)
    from fabulor.app import MainWindow

    mw = MainWindow()
    mw.show()

    def report():
        tm = mw.tags_panel
        scroll = tm._tag_scroll
        container = tm._tag_list_container
        layout = tm._tag_list_layout

        rows = [layout.itemAt(i).widget() for i in range(layout.count())
                if layout.itemAt(i).widget() is not None]

        print("=" * 62)
        print(f"tags_panel height      : {tm.height()}")
        print(f"scroll area height     : {scroll.height()}")
        print(f"viewport height        : {scroll.viewport().height()}")
        print(f"container height       : {container.height()}")
        print(f"container sizeHint     : {container.sizeHint().height()}")
        print(f"layout spacing         : {layout.spacing()}")
        m = layout.contentsMargins()
        print(f"layout margins (t/b)   : {m.top()} / {m.bottom()}")
        print(f"row count              : {len(rows)}")

        if rows:
            h = rows[0].height()
            sp = layout.spacing()
            pitch = h + sp
            vp = scroll.viewport().height()
            print(f"row height             : {h}")
            print(f"row pitch (h+spacing)  : {pitch}")
            # N rows occupy N*h + (N-1)*spacing -- the last row has NO trailing
            # gap. Testing `vp % pitch == 0` instead counts a gap that is not
            # there and reports a 5px-too-tall viewport as perfect; that is
            # exactly what it did, and the top and bottom rows came out clipped.
            n_fit = (vp + sp) // pitch
            exact = n_fit * h + (n_fit - 1) * sp if n_fit else 0
            print(f"rows fully visible     : {n_fit}")
            print(f"height for {n_fit} rows      : {exact}   (N*h + (N-1)*spacing)")
            print(f"viewport - that        : {vp - exact}   <-- 0 means exact fit")
            # y of each row relative to the container, to expose uneven pitch
            ys = [r.y() for r in rows[:6]]
            print(f"first row y positions  : {ys}")
            deltas = [b - a for a, b in zip(ys, ys[1:])]
            print(f"y deltas               : {deltas}   <-- must all equal pitch")

        # Where the scroll area sits inside the panel, i.e. what is above it
        print(f"scroll y within panel  : {scroll.mapTo(tm, scroll.rect().topLeft()).y()}")
        print("=" * 62)
        app.quit()

    # Open Tags through its real flow, then measure once laid out.
    QTimer.singleShot(600, lambda: mw.panel_manager._open_tags_flow())
    QTimer.singleShot(2200, report)
    app.exec()


if __name__ == "__main__":
    main()
