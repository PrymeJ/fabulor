#!/usr/bin/env python
"""Live check: does switching Settings tabs (Themes -> Look/Library/Audio/Controls)
while hovering a Themes-tab swatch correctly and promptly revert to the committed
theme, now that the dismiss-settle predicate fix has shipped (review/Design_260805_
snapback_timing_v2.md) — or does it still need a dedicated tab-bar
click-interception mechanism?

RESULT (2026-08-05, 5/5 trials, both immediate and paused switches): STILL BROKEN.
Hovering, then switching tabs, leaves _is_hover_active stuck True and the main
window's chrome on the hovered theme for the full 2s observation window, every
trial. Root cause confirmed via signal-chain instrumentation (not inferred):
neither _on_themes_tab_left nor _on_theme_unhovered is ever called at all —
Qt does not deliver a leaveEvent to swatch_box when QTabWidget.setCurrentIndex()
hides its containing tab, so the mechanism the dismiss-settle fix improved is never
even entered on this path. This confirms the tab-bar click-interception mechanism
(intercept the click, run the snapback, then call setCurrentIndex once settled)
is still needed — not implemented here, investigation only.

Re-run this after any future tab-switch fix lands to confirm it actually closes
the gap.

Run live, on-screen — QT_QPA_PLATFORM must NOT be offscreen.

Usage:
    source fabulorenv/bin/activate
    LD_PRELOAD=/usr/lib64/libstdc++.so.6 python tools/tab_switch_snapback_check.py
"""
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("FABULOR_LOG_LEVEL", "WARNING")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, QEventLoop

app = QApplication.instance() or QApplication([])

from fabulor.app import MainWindow
from fabulor import themes

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

    # Instrument the real leaveEvent/on_themes_tab_left call chain to see WHY,
    # not just THAT, tab-switch fails to revert.
    leave_log = []
    _real_on_themes_tab_left = tm._on_themes_tab_left

    def _instrumented_on_themes_tab_left(tab_widget):
        leave_log.append(("_on_themes_tab_left called", time.perf_counter()))
        return _real_on_themes_tab_left(tab_widget)

    tm._on_themes_tab_left = _instrumented_on_themes_tab_left

    _real_on_theme_unhovered = tm._on_theme_unhovered

    def _instrumented_on_theme_unhovered():
        leave_log.append(("_on_theme_unhovered called", time.perf_counter()))
        return _real_on_theme_unhovered()

    tm._on_theme_unhovered = _instrumented_on_theme_unhovered

    N_TRIALS = 5
    results = []

    for trial in range(1, N_TRIALS + 1):
        leave_log.clear()
        reset_to_active()
        open_settings_and_settle()
        assert mw.tabs.currentIndex() == 0
        assert mw.settings_panel.isVisible()

        # Hover a swatch via the real signal path (mirrors a genuine enterEvent).
        tm._on_theme_hovered(HOVER_THEME)
        pump(200)  # past the hover debounce, preview genuinely applied

        hover_engaged = (tm._is_hover_active and tm._active_display_theme_internal == HOVER_THEME)

        # Switch tabs WITHOUT closing Settings and WITHOUT the hover ending naturally
        # first -- the exact scenario in question. Try both an immediate switch and,
        # on alternating trials, a short pause first to probe any timing edge.
        if trial % 2 == 0:
            pump(50)  # deliberately test a short pause before switching
        t_switch = time.perf_counter()
        mw.tabs.setCurrentIndex(1)  # Library tab (or whichever is index 1)
        app.processEvents()

        # Watch for up to 2s: does the displayed/committed state correctly and
        # promptly revert?
        settled, waited_ms = pump_until(
            lambda: (not tm._is_hover_active
                     and tm._active_display_theme_internal == tm.get_committed_theme()),
            timeout_ms=2000, step_ms=10
        )
        revert_duration_ms = (time.perf_counter() - t_switch) * 1000

        live_sheet = mw.styleSheet()
        expected_sheet = themes.get_base_stylesheet(ACTIVE_THEME)
        chrome_correct = (live_sheet == expected_sheet)

        results.append({
            "trial": trial,
            "hover_engaged": hover_engaged,
            "reverted": settled,
            "revert_duration_ms": revert_duration_ms if settled else None,
            "chrome_correct_after_wait": chrome_correct,
            "final_is_hover_active": tm._is_hover_active,
            "final_displayed": tm._active_display_theme_internal,
        })
        print(f"  trial {trial} ({'paused' if trial % 2 == 0 else 'immediate'} switch): "
              f"hover_engaged={hover_engaged}  reverted={settled} "
              f"({revert_duration_ms:.1f}ms)  chrome_correct={chrome_correct}  "
              f"final _is_hover_active={tm._is_hover_active}  "
              f"leave_log={[e[0] for e in leave_log]}")

        # Switch back to Themes tab before next trial.
        mw.tabs.setCurrentIndex(0)
        app.processEvents()
        pump(50)

    print("\n=== SUMMARY ===")
    all_hover_engaged = all(r["hover_engaged"] for r in results)
    all_reverted = all(r["reverted"] for r in results)
    all_chrome_correct = all(r["chrome_correct_after_wait"] for r in results)
    print(f"Hover genuinely engaged before switch, every trial: {all_hover_engaged}")
    print(f"Reverted to committed state after tab switch, every trial: {all_reverted}")
    print(f"Chrome (main window stylesheet) correct after wait, every trial: {all_chrome_correct}")
    if all_reverted:
        durations = [r["revert_duration_ms"] for r in results]
        print(f"Revert durations (ms): {durations}")
    print(f"\nVERDICT: {'TAB-SWITCH ALREADY WORKS CORRECTLY' if (all_hover_engaged and all_reverted and all_chrome_correct) else 'TAB-SWITCH STILL BROKEN'}")

    mw.close()


if __name__ == "__main__":
    main()
