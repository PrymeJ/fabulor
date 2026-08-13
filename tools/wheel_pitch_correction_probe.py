"""Verify the new wheel-scroll pitch-correction fix for Library and Stats
(2026-08-12): a manually-dragged scrollbar handle can rest off the row
pitch; native wheel scrolling only applies a relative delta and never
self-corrects. Tags' own scrollbar already snapped on every wheel tick
(tag_manager.py's _tag_rows_wheel); Library/Stats did not.

Simulates: force the scrollbar to an off-pitch value (as if manually
dragged), synthesize a real QWheelEvent, and confirm the resulting value
lands on a pitch multiple after the deferred correction runs.

Run with a real platform plugin:
    LD_PRELOAD=/usr/lib64/libstdc++.so.6 python tools/wheel_pitch_correction_probe.py
"""
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from PySide6.QtCore import Qt, QTimer, QPointF, QPoint
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication


def _send_wheel(app, widget, down=True):
    ev = QWheelEvent(
        QPointF(10, 10), QPointF(10, 10),
        QPoint(0, 0), QPoint(0, -120 if down else 120),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase, False,
    )
    app.sendEvent(widget, ev)


def main():
    app = QApplication(sys.argv)
    from fabulor.app import MainWindow
    from fabulor.ui.library import ITEM_DIMENSIONS

    mw = MainWindow()
    mw.show()

    def report():
        print("=" * 62)
        print("TEST: Library panel wheel pitch correction")
        mw.panel_manager._open_library_flow() if hasattr(mw.panel_manager, "_open_library_flow") \
            else mw.panel_manager._start_library_entry()

        def library_test():
            lp = mw.library_panel
            view = lp._list_view
            bar = view.verticalScrollBar()
            mode = lp._delegate._view_mode
            h = ITEM_DIMENSIONS.get(mode, ITEM_DIMENSIONS["3 per row"])["h"]
            print(f"  view_mode={mode!r}  row_h={h}  scrollbar min/max={bar.minimum()}/{bar.maximum()}")

            if bar.maximum() <= bar.minimum():
                print("  No scroll range — need more books in the library to test.")
                stats_test()
                return

            # Simulate a manual drag landing off-pitch.
            off_pitch = bar.minimum() + h // 2 + 3
            bar.setValue(off_pitch)
            print(f"  forced off-pitch value = {bar.value()} (% h = {bar.value() % h})")

            _send_wheel(app, view.viewport(), down=True)

            def after_correction():
                v = bar.value()
                print(f"  after wheel + deferred correction: value={v}  (% h = {v % h})")
                print(f"  LIBRARY PASS (aligned to h): {v % h == 0}")
                stats_test()

            QTimer.singleShot(100, after_correction)

        QTimer.singleShot(500, library_test)

    def stats_test():
        print("-" * 62)
        print("TEST: Stats Day tab wheel pitch correction")
        from fabulor.ui.stats_panel import _STATS_ROW_HEIGHT
        mw.panel_manager._open_stats_flow() if hasattr(mw.panel_manager, "_open_stats_flow") \
            else mw.panel_manager._start_stats_entry()

        def do_stats_test():
            sp = mw.stats_panel
            sp.refresh_all()
            # Try Day, Week, then Month — whichever has scroll range in this DB.
            candidates = [
                ("Day", getattr(sp, "_day_list_view", None)),
                ("Week", getattr(sp, "_week_list_view", None)),
                ("Month", getattr(sp, "_month_list_view", None)),
            ]
            view = None
            label = None
            for lbl, v in candidates:
                if v is not None and v.verticalScrollBar().maximum() > v.verticalScrollBar().minimum():
                    view, label = v, lbl
                    break
            for lbl, v in candidates:
                if v is not None:
                    m = v.model()
                    print(f"  [{lbl}] rowCount={m.rowCount() if m else None}  "
                          f"viewport_h={v.viewport().height()}  "
                          f"scrollbar_max={v.verticalScrollBar().maximum()}")
            if view is None:
                # Natural overflow didn't occur in this synthetic flow (the panel may not be
                # fully laid out without a real user-driven show/resize cycle) — force a scroll
                # range directly on the Month view (18 rows, most content) to isolate and test
                # just the wheelEvent override's correction logic, independent of whether real
                # overflow happens to occur here.
                view = sp._month_list_view
                label = "Month (forced range)"
                bar = view.verticalScrollBar()
                bar.setRange(0, 500)
                print(f"  falling back: forced scrollbar range on Month = "
                      f"{bar.minimum()}/{bar.maximum()}")
            print(f"  using tab: {label}")
            bar = view.verticalScrollBar()
            h = _STATS_ROW_HEIGHT
            print(f"  row_h={h}  scrollbar min/max={bar.minimum()}/{bar.maximum()}")

            off_pitch = bar.minimum() + h // 2 + 3
            bar.setValue(off_pitch)
            print(f"  forced off-pitch value = {bar.value()} (% h = {bar.value() % h})")

            _send_wheel(app, view.viewport(), down=True)

            def after_correction():
                v = bar.value()
                print(f"  after wheel + deferred correction: value={v}  (% h = {v % h})")
                print(f"  STATS PASS (aligned to h): {v % h == 0}")
                app.quit()

            QTimer.singleShot(100, after_correction)

        QTimer.singleShot(500, do_stats_test)

    QTimer.singleShot(600, report)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
