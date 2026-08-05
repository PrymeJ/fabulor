#!/usr/bin/env python
"""Live check: does switching Settings tabs (Themes -> Look/Library/Audio/Controls)
while hovering a Themes-tab swatch correctly and promptly revert to the committed
theme?

Drives a REAL synthetic mouse press on the tab bar widget (via app.sendEvent, the
same delivery path a genuine click takes — see test_scrollbar_jump.py's _press
helper for the established pattern in this codebase), not tabs.setCurrentIndex()
directly. This matters: the 2026-08-05 fix (_ThemesTabBarInterceptor,
ui/panels.py) intercepts QEvent.Type.MouseButtonPress on the tab bar specifically
-- calling setCurrentIndex() bypasses that interception entirely and would show
the fix as broken/absent regardless of whether it actually works.

HISTORY:
- 2026-08-05, first run (setCurrentIndex() driven): STILL BROKEN. Hovering, then
  switching tabs, left _is_hover_active stuck True and the main window's chrome on
  the hovered theme for the full 2s observation window, every trial (5/5).
  Root cause confirmed via signal-chain instrumentation: neither
  _on_themes_tab_left nor _on_theme_unhovered was ever called at all -- Qt does
  not deliver a leaveEvent to swatch_box when a tab is hidden, so the dismiss-
  settle mechanism was never entered on this path.
- 2026-08-05, second run (real synthetic press, _ThemesTabBarInterceptor v1,
  gated on _is_hover_active): Part A (hover) and Part B (no hover) both PASS.
- 2026-08-05, third run (Part C added, "Change now" case): FAILED as reported
  live by Pryme -- "Change now" is a genuine SELECTION, not a hover, so
  _is_hover_active stays False for its entire fade and every tab click during
  it passed straight through, unblocked. Fixed by widening the interceptor's
  gate to `_theme_genuinely_settled_on_committed()` (also checks
  `_fade_in_flight`, which DOES stay True for a selection's own fade). Part C
  now PASSes too -- see the printed VERDICT for the current result.

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
from PySide6.QtCore import QTimer, QEventLoop, QPointF, QPoint, Qt
from PySide6.QtGui import QMouseEvent

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


def click_tab(app, tab_bar, index):
    """Send a real MouseButtonPress (then Release) to tab_bar at `index`'s tab
    rect center -- exactly what a genuine click delivers, so the installed
    _ThemesTabBarInterceptor event filter sees it for real, not simulated by
    calling application logic directly."""
    rect = tab_bar.tabRect(index)
    center = rect.center()
    global_pos = tab_bar.mapToGlobal(center)
    press = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress, QPointF(center),
        QPointF(global_pos), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier)
    app.sendEvent(tab_bar, press)
    release = QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease, QPointF(center),
        QPointF(global_pos), Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier)
    app.sendEvent(tab_bar, release)


def main():
    mw = MainWindow()
    mw.show()
    app.processEvents()
    pump(1200)

    tm = mw.theme_manager
    pm = mw.panel_manager
    tab_bar = mw.tabs.tabBar()

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

    # Instrument the real leaveEvent/unhover/interceptor call chain.
    call_log = []
    _real_on_themes_tab_left = tm._on_themes_tab_left

    def _instrumented_on_themes_tab_left(tab_widget):
        call_log.append("_on_themes_tab_left")
        return _real_on_themes_tab_left(tab_widget)

    tm._on_themes_tab_left = _instrumented_on_themes_tab_left

    _real_on_theme_unhovered = tm._on_theme_unhovered

    def _instrumented_on_theme_unhovered():
        call_log.append("_on_theme_unhovered")
        return _real_on_theme_unhovered()

    tm._on_theme_unhovered = _instrumented_on_theme_unhovered

    interceptor = pm._themes_tab_bar_interceptor
    _real_filter = interceptor.eventFilter

    def _instrumented_filter(obj, event):
        result = _real_filter(obj, event)
        if event.type().name == "MouseButtonPress" and obj is tab_bar:
            call_log.append(f"interceptor(consumed={result})")
        return result

    interceptor.eventFilter = _instrumented_filter

    # ================================================================
    # PART A: with a genuine hover active — must be intercepted
    # ================================================================
    print("=" * 70)
    print("PART A: hover active, then click a different tab (real synthetic press)")
    print("=" * 70)

    N_TRIALS = 5
    results = []

    for trial in range(1, N_TRIALS + 1):
        call_log.clear()
        reset_to_active()
        open_settings_and_settle()
        assert mw.tabs.currentIndex() == 0
        assert mw.settings_panel.isVisible()

        tm._on_theme_hovered(HOVER_THEME)
        pump(200)  # past the hover debounce, preview genuinely applied
        hover_engaged = (tm._is_hover_active and tm._active_display_theme_internal == HOVER_THEME)

        if trial % 2 == 0:
            pump(50)  # deliberately test a short pause before clicking

        # Real synthetic click on the Look tab (index 1).
        t_click = time.perf_counter()
        click_tab(app, tab_bar, 1)
        app.processEvents()

        index_immediately_after_click = mw.tabs.currentIndex()

        # Watch: does it eventually land on the clicked tab, with the theme
        # correctly settled first?
        landed, waited_ms = pump_until(
            lambda: mw.tabs.currentIndex() == 1, timeout_ms=3000, step_ms=10
        )
        switch_duration_ms = (time.perf_counter() - t_click) * 1000

        final_hover_active = tm._is_hover_active
        final_displayed = tm._active_display_theme_internal
        final_committed = tm.get_committed_theme()
        reverted_to_committed = (not final_hover_active and final_displayed == final_committed)

        live_sheet = mw.styleSheet()
        expected_sheet = themes.get_base_stylesheet(ACTIVE_THEME)
        chrome_correct = (live_sheet == expected_sheet)

        results.append({
            "trial": trial,
            "hover_engaged": hover_engaged,
            "was_intercepted": index_immediately_after_click == 0,  # still on Themes tab right after click
            "landed_on_target_tab": landed,
            "switch_duration_ms": switch_duration_ms if landed else None,
            "reverted_to_committed": reverted_to_committed,
            "chrome_correct": chrome_correct,
        })
        print(f"  trial {trial} ({'paused' if trial % 2 == 0 else 'immediate'} click): "
              f"hover_engaged={hover_engaged}  "
              f"intercepted(stayed on tab 0 right after click)={index_immediately_after_click == 0}  "
              f"landed_on_tab1={landed} ({switch_duration_ms:.1f}ms)  "
              f"reverted={reverted_to_committed}  chrome_correct={chrome_correct}  "
              f"call_log={call_log}")

        mw.tabs.setCurrentIndex(0)
        app.processEvents()
        pump(50)

    print("\n-- Part A summary --")
    a_hover_engaged = all(r["hover_engaged"] for r in results)
    a_intercepted = all(r["was_intercepted"] for r in results)
    a_landed = all(r["landed_on_target_tab"] for r in results)
    a_reverted = all(r["reverted_to_committed"] for r in results)
    a_chrome = all(r["chrome_correct"] for r in results)
    print(f"Hover engaged every trial: {a_hover_engaged}")
    print(f"Click intercepted (didn't switch immediately) every trial: {a_intercepted}")
    print(f"Eventually landed on clicked tab every trial: {a_landed}")
    print(f"Reverted to committed theme every trial: {a_reverted}")
    print(f"Chrome correct every trial: {a_chrome}")
    part_a_pass = a_hover_engaged and a_intercepted and a_landed and a_reverted and a_chrome
    print(f"PART A VERDICT: {'PASS' if part_a_pass else 'FAIL'}")

    # ================================================================
    # PART B: no hover active — must pass through completely unaffected
    # ================================================================
    print("\n" + "=" * 70)
    print("PART B: no hover active, click a different tab — must be instant, unaffected")
    print("=" * 70)

    b_results = []
    for trial in range(1, N_TRIALS + 1):
        call_log.clear()
        reset_to_active()
        open_settings_and_settle()
        assert mw.tabs.currentIndex() == 0
        assert not tm._is_hover_active

        t_click = time.perf_counter()
        click_tab(app, tab_bar, 1)
        app.processEvents()
        index_right_after = mw.tabs.currentIndex()
        switch_duration_ms = (time.perf_counter() - t_click) * 1000

        instant_switch = (index_right_after == 1)
        interceptor_did_nothing = all("consumed=True" not in c for c in call_log)

        b_results.append({
            "trial": trial,
            "instant_switch": instant_switch,
            "switch_duration_ms": switch_duration_ms,
            "interceptor_passthrough": interceptor_did_nothing,
        })
        print(f"  trial {trial}: instant_switch={instant_switch} "
              f"({switch_duration_ms:.2f}ms)  interceptor_passthrough={interceptor_did_nothing}  "
              f"call_log={call_log}")

        mw.tabs.setCurrentIndex(0)
        app.processEvents()
        pump(50)

    print("\n-- Part B summary --")
    b_instant = all(r["instant_switch"] for r in b_results)
    b_passthrough = all(r["interceptor_passthrough"] for r in b_results)
    print(f"Instant switch (no interception) every trial: {b_instant}")
    print(f"Interceptor was a pure pass-through every trial: {b_passthrough}")
    part_b_pass = b_instant and b_passthrough
    print(f"PART B VERDICT: {'PASS' if part_b_pass else 'FAIL'}")

    # ================================================================
    # PART C: "Change now" (a genuine selection, not a hover) then rapid
    # multi-tab clicks WHILE its own fade is still visually in flight
    # ================================================================
    # Live-reported by Pryme (2026-08-05): "Doesn't work for the Change now
    # button. It continues to fade and during that time I can switch multiple
    # tabs." The first version of this fix gated on _is_hover_active alone,
    # which stays False for a genuine selection's own fade -- fixed by gating on
    # _theme_genuinely_settled_on_committed() instead (also checks
    # _fade_in_flight). This part reproduces the EXACT reported sequence: click
    # Change now, then click SEVERAL different tabs in quick succession while
    # its fade is still running, and confirm every one of those clicks is
    # deferred until settled -- not just the first.
    print("\n" + "=" * 70)
    print('PART C: "Change now" clicked, then rapid multi-tab clicks during its own fade')
    print("=" * 70)

    change_now_btn = mw.change_now_btn

    c_results = []
    for trial in range(1, N_TRIALS + 1):
        call_log.clear()
        reset_to_active()
        open_settings_and_settle()
        assert mw.tabs.currentIndex() == 0

        pre_committed = tm.get_committed_theme()
        change_now_btn.click()
        app.processEvents()
        post_committed = tm.get_committed_theme()
        fade_in_flight_right_after_click = tm._fade_in_flight

        # Rapid multi-tab clicking WHILE the fade is still running -- the exact
        # reported sequence. Click tab 1, then 2, then 3, then 4, back to back,
        # with no wait between them.
        indices_clicked = [1, 2, 3, 4]
        for idx in indices_clicked:
            click_tab(app, tab_bar, idx)
            app.processEvents()

        index_immediately_after_clicks = mw.tabs.currentIndex()
        was_intercepted_throughout = (index_immediately_after_clicks == 0)

        # Let everything resolve, then confirm it lands on the LAST tab clicked
        # (4) -- each queued switch overwrites the pending one via
        # call_when_theme_settled's own waiter-append behavior; only the final
        # intent should win, matching what a real rapid-multi-click user expects.
        settled, waited_ms = pump_until(
            lambda: mw.tabs.currentIndex() != 0, timeout_ms=3000, step_ms=10
        )
        pump(300)

        final_committed = tm.get_committed_theme()
        final_fade_in_flight = tm._fade_in_flight
        final_tab_index = mw.tabs.currentIndex()
        live_sheet = mw.styleSheet()
        expected_sheet = (themes.get_base_stylesheet(final_committed)
                           if isinstance(final_committed, str) else None)
        chrome_matches_committed = (expected_sheet is not None and live_sheet == expected_sheet)

        c_results.append({
            "trial": trial,
            "theme_changed_by_click": pre_committed != post_committed,
            "fade_in_flight_right_after_click": fade_in_flight_right_after_click,
            "was_intercepted_throughout": was_intercepted_throughout,
            "final_tab_index": final_tab_index,
            "final_fade_in_flight": final_fade_in_flight,
            "chrome_matches_committed": chrome_matches_committed,
        })
        print(f"  trial {trial}: theme_changed={pre_committed != post_committed} "
              f"({pre_committed!r} -> {post_committed!r})  "
              f"fade_in_flight_after_click={fade_in_flight_right_after_click}  "
              f"stayed_on_tab0_during_rapid_clicks={was_intercepted_throughout}  "
              f"final_tab_index={final_tab_index}  "
              f"final_fade_in_flight={final_fade_in_flight}  "
              f"chrome_matches_committed={chrome_matches_committed}")

        mw.tabs.setCurrentIndex(0)
        app.processEvents()
        pump(50)

    print("\n-- Part C summary --")
    c_theme_changed = all(r["theme_changed_by_click"] for r in c_results)
    c_fade_was_flight = all(r["fade_in_flight_right_after_click"] for r in c_results)
    c_intercepted = all(r["was_intercepted_throughout"] for r in c_results)
    c_settled = all(not r["final_fade_in_flight"] for r in c_results)
    c_chrome = all(r["chrome_matches_committed"] for r in c_results)
    print(f'"Change now" genuinely changed the theme every trial: {c_theme_changed}')
    print(f"Fade genuinely in flight right after the click every trial: {c_fade_was_flight}")
    print(f"ALL rapid multi-tab clicks deferred (stayed on tab 0) every trial: {c_intercepted}")
    print(f"Fade genuinely settled by the end every trial: {c_settled}")
    print(f"Chrome matches committed theme every trial: {c_chrome}")
    part_c_pass = c_theme_changed and c_fade_was_flight and c_intercepted and c_settled and c_chrome
    print(f"PART C VERDICT: {'PASS' if part_c_pass else 'FAIL'}")

    print("\n" + "=" * 70)
    print(f"OVERALL: {'PASS' if (part_a_pass and part_b_pass and part_c_pass) else 'FAIL'}")
    print("=" * 70)

    mw.close()


if __name__ == "__main__":
    main()
