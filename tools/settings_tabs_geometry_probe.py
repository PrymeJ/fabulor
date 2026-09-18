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

            headers = page.findChildren(QLabel, "settings_header")
            header_ys = [(h.text(), h.y(), h.height()) for h in headers]

            print(f"\n--- Tab: {tab_name!r} ---")
            print(f"  sizeHint height   : {hint_h}")
            print(f"  actual height     : {actual_h}")
            print(f"  overflow (hint-actual): {hint_h - actual_h}")
            if layout is not None:
                m = layout.contentsMargins()
                print(f"  layout margins (t/b)  : {m.top()} / {m.bottom()}")
                print(f"  layout spacing        : {layout.spacing()}")
            print(f"  header count      : {len(headers)}")
            for text, y, h in header_ys:
                print(f"    {text!r:35s} y={y:4d} h={h}")

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
