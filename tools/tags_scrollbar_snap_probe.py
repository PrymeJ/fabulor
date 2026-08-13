"""Verify Tags panel's right-click scrollbar jump snaps to a row boundary,
now that scrollbar_jump.register_snap is wired for _tag_scroll (2026-08-12).
Same "read the real widget tree after a real show()" shape as
tools/tags_geometry_probe.py and the history_*_probe.py scripts.

Run with a real platform plugin:
    LD_PRELOAD=/usr/lib64/libstdc++.so.6 python tools/tags_scrollbar_snap_probe.py
"""
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer


def main():
    app = QApplication(sys.argv)
    from fabulor.app import MainWindow
    from fabulor.ui.tag_manager import _TAG_ROW_PITCH

    mw = MainWindow()
    mw.show()

    def report():
        mw.panel_manager._open_tags_flow()

        def check():
            tm = mw.tags_panel
            bar = tm._tag_scroll.verticalScrollBar()
            print("=" * 62)
            print(f"_TAG_ROW_PITCH={_TAG_ROW_PITCH}")
            print(f"scrollbar min/max = {bar.minimum()}/{bar.maximum()}")

            if bar.maximum() <= bar.minimum():
                print("No scroll range (not enough tags to overflow) — cannot test jump.")
                app.quit()
                return

            # Simulate what ScrollBarJumpFilter.eventFilter computes: a value roughly
            # mid-range, deliberately NOT aligned to the pitch, then run it through the
            # registered snap fn directly (same call the filter makes).
            from fabulor.ui import scrollbar_jump
            raw_value = bar.minimum() + (bar.maximum() - bar.minimum()) // 3 + 4  # off-pitch on purpose
            snap = scrollbar_jump._snap_fns.get(bar)
            print(f"registered snap fn present: {snap is not None}")
            if snap is None:
                print("FAIL: no snap fn registered for this scrollbar.")
                app.quit()
                return

            snapped = snap(raw_value)
            print(f"raw_value={raw_value}  snapped={snapped}  "
                  f"snapped % pitch = {snapped % _TAG_ROW_PITCH}")
            print(f"PASS (snapped is pitch-aligned): {snapped % _TAG_ROW_PITCH == 0}")

            # Also apply it via setValue and confirm the actual scrollbar lands aligned.
            bar.setValue(snapped)
            print(f"bar.value() after setValue = {bar.value()}  "
                  f"(% pitch = {bar.value() % _TAG_ROW_PITCH})")

            app.quit()

        QTimer.singleShot(400, check)

    QTimer.singleShot(600, report)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
