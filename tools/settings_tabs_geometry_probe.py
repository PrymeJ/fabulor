"""Report each Settings tab's real vertical geometry from the RUNNING app.

Follows tags_geometry_probe.py's pattern exactly (see its own docstring for why):
builds the real MainWindow, opens Settings through its real entry path, switches
to each tab in turn, and prints what Qt actually allocated for each — not an
offscreen reconstruction.

Specifically checks: does any tab's content sizeHint() exceed the shared
QTabWidget content area's actual height? If so, that tab's natural vertical
rhythm (settings_header's margin-top, inter-group spacing) cannot all be
honored at once — Qt has to compress something to fit, which is the
"Look tab looks tighter than its own numbers suggest" question this exists to
settle with real measurements instead of guessing further from static code.

Run with a real platform plugin (NOT QT_QPA_PLATFORM=offscreen):

    source fabulorenv/bin/activate
    LD_PRELOAD=/usr/lib64/libstdc++.so.6 python tools/settings_tabs_geometry_probe.py

Prints measurements only. Whether anything LOOKS right is the user's call, always.
"""
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from PySide6.QtWidgets import QApplication, QLabel
from PySide6.QtCore import QTimer


def main():
    app = QApplication(sys.argv)
    from fabulor.app import MainWindow

    mw = MainWindow()
    mw.show()

    def report():
        tabs = mw.tabs
        content_area_height = tabs.height() - tabs.tabBar().height()
        print("=" * 70)
        print(f"settings_panel height        : {mw.settings_panel.height()}")
        print(f"tabs (QTabWidget) height     : {tabs.height()}")
        print(f"tabBar height                : {tabs.tabBar().height()}")
        print(f"shared content area height   : {content_area_height}")
        print("=" * 70)

        for i in range(tabs.count()):
            tab_name = tabs.tabText(i)
            page = tabs.widget(i)
            layout = page.layout()
            hint_h = page.sizeHint().height()
            actual_h = page.height()
            # The page's position WITHIN the QTabWidget's internal QStackedWidget — if this
            # differs between tabs, every header on that page is offset by the same amount
            # regardless of what's correct inside the page's own layout. This is what a
            # visual overlay comparing two tabs' first header would actually be measuring.
            page_pos_in_stack = page.pos()
            page_pos_in_tabs = page.mapTo(tabs, page.rect().topLeft())
            page_pos_in_panel = page.mapTo(mw.settings_panel, page.rect().topLeft())

            headers = page.findChildren(QLabel, "settings_header")
            # First header's ABSOLUTE position within settings_panel — this is the number
            # that's directly comparable across tabs, unlike each header's y() (relative to
            # its own page, which is meaningless if the pages themselves aren't aligned).
            header_ys = []
            for h in headers:
                abs_pos = h.mapTo(mw.settings_panel, h.rect().topLeft())
                header_ys.append((h.text(), h.y(), h.height(), abs_pos.y()))

            print(f"\n--- Tab: {tab_name!r} ---")
            print(f"  sizeHint height   : {hint_h}")
            print(f"  actual height     : {actual_h}")
            print(f"  overflow (hint-actual): {hint_h - actual_h}")
            print(f"  page.pos() (in stack)     : {page_pos_in_stack.x()}, {page_pos_in_stack.y()}")
            print(f"  page top-left in tabs     : {page_pos_in_tabs.x()}, {page_pos_in_tabs.y()}")
            print(f"  page top-left in settings_panel: {page_pos_in_panel.x()}, {page_pos_in_panel.y()}")
            if layout is not None:
                m = layout.contentsMargins()
                print(f"  layout margins (t/b)  : {m.top()} / {m.bottom()}")
                print(f"  layout spacing        : {layout.spacing()}")
            print(f"  header count      : {len(headers)}")
            for text, y, h, abs_y in header_ys:
                print(f"    {text!r:35s} y={y:4d} h={h}  ABS_Y(in settings_panel)={abs_y}")

            # Dump every top-level layout item's geometry (header widget or button-row
            # sub-layout) in order, so the real pitch can be read off actual numbers
            # instead of reconstructed from margin-top/spacing constants by hand.
            if layout is not None:
                print(f"  --- top-level layout items ({tab_name!r}) ---")
                for idx in range(layout.count()):
                    item = layout.itemAt(idx)
                    w = item.widget()
                    if w is not None:
                        print(f"    [{idx}] WIDGET {type(w).__name__}({w.objectName()!r}, text={getattr(w, 'text', lambda: '')()!r}) y={w.y()} h={w.height()}")
                    else:
                        r = item.geometry()
                        sub = item.layout()
                        kind = type(sub).__name__ if sub is not None else "SPACER"
                        print(f"    [{idx}] {kind} y={r.y()} h={r.height()}")

        print("\n" + "=" * 70)
        print("Done.")
        QTimer.singleShot(100, app.quit)

    # Open Settings through its real entry path (right-click drag area, per panels.py),
    # switching through each tab so every page has actually been laid out once.
    def open_and_report():
        mw.panel_manager._open_settings_flow()

        def after_open():
            for i in range(mw.tabs.count()):
                mw.tabs.setCurrentIndex(i)
                app.processEvents()
            report()

        QTimer.singleShot(500, after_open)

    QTimer.singleShot(300, open_and_report)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
