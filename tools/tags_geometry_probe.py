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

        # --- horizontal: row right edge vs scrollbar, compared with Stats ---
        bar = scroll.verticalScrollBar()
        print("-" * 62)
        print("HORIZONTAL (tags)")
        print(f"  panel width          : {tm.width()}")
        print(f"  scroll x / width     : {scroll.x()} / {scroll.width()}")
        print(f"  viewport width       : {scroll.viewport().width()}")
        print(f"  scrollbar visible    : {bar.isVisible()}  width={bar.width()}")
        lm = layout.contentsMargins()
        print(f"  container width      : {container.width()}")
        print(f"  layout margins (l/r) : {lm.left()} / {lm.right()}")
        if rows:
            r = rows[0]
            rx = r.mapTo(tm, r.rect().topLeft()).x()
            print(f"  row x / width        : {rx} / {r.width()}")
            print(f"  row right edge (x)   : {rx + r.width()}")
            if bar.isVisible():
                bx = bar.mapTo(tm, bar.rect().topLeft()).x()
                print(f"  scrollbar x          : {bx}")
                print(f"  GAP row->scrollbar   : {bx - (rx + r.width())}")
                print(f"  scrollbar right      : {bx + bar.width()}")
                print(f"  panel edge - sb right: {tm.width() - (bx + bar.width())}")

        sp = mw.stats_panel
        ssc = getattr(sp, '_month_scroll', None)
        if ssc is not None:
            sbar = ssc.verticalScrollBar()
            srows = [ssc.widget().layout().itemAt(i).widget()
                     for i in range(ssc.widget().layout().count())
                     if ssc.widget().layout().itemAt(i).widget() is not None]
            print("HORIZONTAL (stats month, for comparison)")
            print(f"  panel width          : {sp.width()}")
            print(f"  viewport width       : {ssc.viewport().width()}")
            print(f"  scrollbar visible    : {sbar.isVisible()}  width={sbar.width()}")
            if srows and sbar.isVisible():
                sr = srows[0]
                srx = sr.mapTo(sp, sr.rect().topLeft()).x()
                sbx = sbar.mapTo(sp, sbar.rect().topLeft()).x()
                print(f"  row right edge (x)   : {srx + sr.width()}")
                print(f"  scrollbar x          : {sbx}")
                print(f"  GAP row->scrollbar   : {sbx - (srx + sr.width())}")
                print(f"  panel edge - sb right: {sp.width() - (sbx + sbar.width())}")
        print("=" * 62)
        app.quit()

    # Open Stats first (Month tab, for the horizontal comparison), let it
    # populate, close it, then open Tags and measure. Both through their real
    # flows -- a panel measured without being opened the way the app opens it
    # is a different render, which is the whole reason this probe exists.
    QTimer.singleShot(400, lambda: mw.panel_manager._open_stats_flow())
    QTimer.singleShot(900, lambda: mw.stats_panel.stats_tabs.setCurrentIndex(4))
    QTimer.singleShot(1600, lambda: mw.panel_manager.hide_all_panels())
    QTimer.singleShot(2200, lambda: mw.panel_manager._open_tags_flow())
    QTimer.singleShot(3600, report)
    app.exec()


if __name__ == "__main__":
    main()
