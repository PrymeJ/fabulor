#!/usr/bin/env python
"""Live check for the SWATCH-LEAVE-SUSPECT correction fix (2026-08-05, see
review/Design_260805_swatch_leave_suspect_correction.md).

Confirms, against a real ThemeManager/swatch_box with REAL geometry (not a fake
rect) but a STUBBED QCursor.pos() (never moves the real OS mouse pointer — that
would be a live, visible side effect on whatever session happens to be running,
which this harness deliberately avoids):
1. The SUSPECT condition (hidden, cursor genuinely outside swatch_box's real,
   live rect) now calls _on_theme_unhovered() and corrects _is_hover_active
   promptly.
2. The genuinely-synthetic case (hidden, cursor still inside swatch_box's real
   rect) remains completely unaffected — no correction, _is_hover_active stays
   engaged exactly as before this fix.

Run live, on-screen — QT_QPA_PLATFORM must NOT be offscreen.

Usage:
    source fabulorenv/bin/activate
    LD_PRELOAD=/usr/lib64/libstdc++.so.6 python tools/swatch_leave_suspect_correction_check.py
"""
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("FABULOR_LOG_LEVEL", "WARNING")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, QEventLoop, QPoint

app = QApplication.instance() or QApplication([])

from fabulor.app import MainWindow
import fabulor.ui.theme_manager as theme_manager_module

ACTIVE_THEME = "Alzabo"
HOVER_THEME = "Blindsight"


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def pump_until(predicate, timeout_ms, step_ms=10):
    waited = 0
    while waited < timeout_ms:
        pump(step_ms)
        waited += step_ms
        if predicate():
            return True, waited
    return False, waited


class _StubCursor:
    """Drop-in for QCursor with a fixed .pos() -- never touches the real OS
    pointer. Swapped into fabulor.ui.theme_manager's QCursor reference for the
    duration of one _on_themes_tab_left call, then restored."""

    def __init__(self, pos):
        self._pos = pos

    def pos(self):
        return self._pos


def _call_with_stubbed_cursor(fn, cursor_pos):
    original = theme_manager_module.QCursor
    theme_manager_module.QCursor = _StubCursor(cursor_pos)
    try:
        fn()
    finally:
        theme_manager_module.QCursor = original


def main():
    mw = MainWindow()
    mw.show()
    app.processEvents()
    pump(1200)

    tm = mw.theme_manager
    pm = mw.panel_manager

    def reset_to_active():
        tm._cover_theme_active = False
        tm._cover_theme = None
        tm._current_theme_name = ACTIVE_THEME
        tm._on_theme_changed(ACTIVE_THEME, save=False, fade_ms=0, hover=False,
                              bypass_panel_open_guard=True)
        app.processEvents()
        pump(80)

    def open_settings_and_settle():
        if not pm.settings_panel.isVisible():
            pm._open_settings_flow()
            app.processEvents()
            pump(400)
        pump_until(lambda: not pm._any_panel_animating(), timeout_ms=3000, step_ms=20)

    swatch_box = tm.swatch_box

    class _HiddenProxy:
        """isVisible()=False (mirrors an ancestor hidden by the blur grab), but
        real live geometry delegated to the real swatch_box -- exercises the
        actual mapFromGlobal/rect() calls _on_themes_tab_left makes, not a fake
        rect."""

        def isVisible(self):
            return False

        def rect(self):
            return swatch_box.rect()

        def mapFromGlobal(self, point):
            return swatch_box.mapFromGlobal(point)

    # ================================================================
    # PART 1: SUSPECT condition (hidden, cursor genuinely outside) -> corrects
    # ================================================================
    print("=" * 70)
    print("PART 1: hidden + cursor genuinely outside swatch_box -> must correct")
    print("=" * 70)

    n_trials = 5
    part1_results = []
    for trial in range(1, n_trials + 1):
        reset_to_active()
        open_settings_and_settle()
        assert mw.tabs.currentIndex() == 0

        tm._on_theme_hovered(HOVER_THEME)
        pump(200)
        hover_engaged = tm._is_hover_active

        # Real swatch_box geometry, mapped to global, then a point far outside it.
        rect = swatch_box.rect()
        global_top_left = swatch_box.mapToGlobal(rect.topLeft())
        far_outside_global = QPoint(global_top_left.x() - 500, global_top_left.y() - 500)

        _call_with_stubbed_cursor(
            lambda: tm._on_themes_tab_left(_HiddenProxy()), far_outside_global
        )

        corrected, waited_ms = pump_until(lambda: not tm._is_hover_active, timeout_ms=2000, step_ms=10)
        part1_results.append({
            "trial": trial,
            "hover_engaged": hover_engaged,
            "corrected": corrected,
        })
        print(f"  trial {trial}: hover_engaged={hover_engaged}  "
              f"corrected={corrected} ({waited_ms}ms)")

    print("\n-- Part 1 summary --")
    p1_engaged = all(r["hover_engaged"] for r in part1_results)
    p1_corrected = all(r["corrected"] for r in part1_results)
    print(f"Hover engaged every trial: {p1_engaged}")
    print(f"Corrected (is_hover_active cleared) every trial: {p1_corrected}")
    part1_pass = p1_engaged and p1_corrected
    print(f"PART 1 VERDICT: {'PASS' if part1_pass else 'FAIL'}")

    # ================================================================
    # PART 2: genuinely-synthetic case (hidden, cursor still inside) -> untouched
    # ================================================================
    print("\n" + "=" * 70)
    print("PART 2: hidden + cursor still inside swatch_box -> must stay UNAFFECTED")
    print("=" * 70)

    part2_results = []
    for trial in range(1, n_trials + 1):
        reset_to_active()
        open_settings_and_settle()
        assert mw.tabs.currentIndex() == 0

        tm._on_theme_hovered(HOVER_THEME)
        pump(200)
        hover_engaged = tm._is_hover_active

        rect = swatch_box.rect()
        center_global = swatch_box.mapToGlobal(rect.center())

        _call_with_stubbed_cursor(
            lambda: tm._on_themes_tab_left(_HiddenProxy()), center_global
        )
        pump(200)

        still_engaged = tm._is_hover_active
        part2_results.append({
            "trial": trial,
            "hover_engaged": hover_engaged,
            "still_engaged_after": still_engaged,
        })
        print(f"  trial {trial}: hover_engaged={hover_engaged}  "
              f"still_engaged_after={still_engaged}")

    print("\n-- Part 2 summary --")
    p2_engaged = all(r["hover_engaged"] for r in part2_results)
    p2_untouched = all(r["still_engaged_after"] for r in part2_results)
    print(f"Hover engaged every trial: {p2_engaged}")
    print(f"Hover STILL engaged after (untouched) every trial: {p2_untouched}")
    part2_pass = p2_engaged and p2_untouched
    print(f"PART 2 VERDICT: {'PASS' if part2_pass else 'FAIL'}")

    print("\n" + "=" * 70)
    print(f"OVERALL: {'PASS' if (part1_pass and part2_pass) else 'FAIL'}")
    print("=" * 70)

    mw.close()


if __name__ == "__main__":
    main()
