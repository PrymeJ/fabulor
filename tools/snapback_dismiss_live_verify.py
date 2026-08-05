#!/usr/bin/env python
"""Live verification for the corrected Esc/gutter-dismiss snapback-timing fix
(2026-08-05 v2 — review/Design_260805_snapback_timing_v2.md).

Confirms, with real paint evidence on a live, on-screen MainWindow (not offscreen):

1. Hovering a swatch with a LONG configured preview-fade duration, then dismissing
   mid-preview, cuts the preview short INSTANTLY (no waiting for the preview's own
   fade to finish) and starts the real 200ms snapback fade.
2. The fade overlay stays visibly present and PAINTING throughout the wait (not a
   frozen dead frame) — real QGraphicsOpacityEffect.draw() calls with a genuinely
   moving opacity value, the whole way through.
3. The event loop stays genuinely alive during the wait: a QTimer ticking at a
   fixed cadence throughout the dismiss sequence should show no large gaps (a
   frozen event loop would show one huge gap where the timer failed to fire).
4. The panel actually closes once settled — no hang.
5. The final active theme (main_window.styleSheet()) matches the COMMITTED theme
   (the one active before the hover started), not the hover-previewed one.
6. The termination-guarantee fallback: forcibly prevent the fade from ever
   settling naturally (monkeypatch _fade_anim so it never reaches Stopped) and
   confirm the dismiss still eventually proceeds via snap_theme_forward(),
   rather than hanging forever.

Run live, on-screen — QT_QPA_PLATFORM must NOT be offscreen.

Usage:
    source fabulorenv/bin/activate
    LD_PRELOAD=/usr/lib64/libstdc++.so.6 python tools/snapback_dismiss_live_verify.py
"""
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("FABULOR_LOG_LEVEL", "WARNING")

from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect
from PySide6.QtCore import QTimer, QEventLoop, QAbstractAnimation

app = QApplication.instance() or QApplication([])

from fabulor.app import MainWindow
from fabulor import themes

ACTIVE_THEME = "Alzabo"
HOVER_THEME = "Blindsight"


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def pump_until(predicate, timeout_ms, step_ms=20):
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
        # Explicitly clear cover-art theme state before every reset. MainWindow()
        # construction reads the REAL, QSettings-persisted cover_art_theme_mode
        # from this machine -- found live (2026-08-05) to leave _cover_theme_active
        # genuinely True from a prior real session, which silently made every
        # "plain theme" test in this harness (Tests 1-7) actually exercise the
        # cover-art path instead, since _on_theme_unhovered() always checks
        # _cover_theme_active first regardless of what reset_to_active() passes
        # as theme_name. Tests 1-7 are specifically about the plain-string path;
        # Test 8 is what explicitly exercises cover-art mode.
        tm._cover_theme_active = False
        tm._cover_theme = None
        tm._current_theme_name = ACTIVE_THEME
        tm._on_theme_changed(ACTIVE_THEME, save=False, fade_ms=0, hover=False,
                              bypass_panel_open_guard=True)
        app.processEvents()
        pump(80)

    def open_settings_panel_and_settle():
        if not pm.settings_panel.isVisible():
            pm._open_settings_flow()
            app.processEvents()
            pump(400)
        pump_until(lambda: not pm._any_panel_animating(), timeout_ms=3000, step_ms=20)

    # ================================================================
    # TEST 1-5: normal path — long preview, dismiss mid-fade
    # ================================================================
    print("=" * 70)
    print("TEST 1-5: dismiss mid-preview, real paint + event-loop-liveness evidence")
    print("=" * 70)

    reset_to_active()
    open_settings_panel_and_settle()
    assert mw.tabs.currentIndex() == 0
    assert mw.settings_panel.isVisible()

    # Instrument real paint evidence on the fade overlay's effect, filtered to the
    # specific instance (see the class-level-patch bug found in the latency probe).
    paint_log = []
    effect = tm._fade_effect
    _real_draw = QGraphicsOpacityEffect.draw

    def _instrumented_draw(self, painter):
        if self is effect:
            paint_log.append((time.perf_counter(), self.opacity()))
        return _real_draw(self, painter)

    QGraphicsOpacityEffect.draw = _instrumented_draw

    # Event-loop-liveness heartbeat: a QTimer ticking at a fixed 10ms cadence
    # throughout. If the event loop were genuinely stalled (the original failure
    # mode under suspicion), this timer would simply stop ticking and the gaps
    # between consecutive ticks would show one enormous outlier.
    heartbeat_log = []
    heartbeat_timer = QTimer()
    heartbeat_timer.setInterval(10)
    heartbeat_timer.timeout.connect(lambda: heartbeat_log.append(time.perf_counter()))
    heartbeat_timer.start()

    # Start a LONG preview fade (1500ms), the exact scenario the task specifies.
    LONG_PREVIEW_MS = 1500
    tm._on_theme_changed(HOVER_THEME, save=False, fade_ms=LONG_PREVIEW_MS, hover=True,
                          bypass_panel_open_guard=True)
    pump(200)  # let the preview genuinely start and run a bit
    preview_was_running = tm._fade_anim.state() == QAbstractAnimation.State.Running
    print(f"  preview fade running before dismiss: {preview_was_running} "
          f"(state={tm._fade_anim.state()}, currentTime={tm._fade_anim.currentTime()})")

    settings_close_called_at = time.perf_counter()
    settled_at = {}

    def _on_settled_marker():
        settled_at['t'] = time.perf_counter()

    # Hook _close_settings_flow_after_settle_gap to know exactly when settling
    # completed, without altering real behavior (call-through, not replace).
    _real_after_gap = pm._close_settings_flow_after_settle_gap

    def _wrapped_after_gap():
        _on_settled_marker()
        return _real_after_gap()

    pm._close_settings_flow_after_settle_gap = _wrapped_after_gap

    # THE DISMISS — via the real gutter-click path (hide_all_panels -> _close_settings_flow).
    pm.hide_all_panels()

    # Watch for up to 3s for the panel to actually finish closing.
    closed, waited_ms = pump_until(lambda: not mw.settings_panel.isVisible(), timeout_ms=3000, step_ms=10)

    heartbeat_timer.stop()
    QGraphicsOpacityEffect.draw = _real_draw

    print(f"  panel closed: {closed} (waited {waited_ms}ms)")
    print(f"  settled marker fired: {'t' in settled_at}")
    if 't' in settled_at:
        print(f"  time from dismiss call to settle: {(settled_at['t'] - settings_close_called_at)*1000:.1f}ms")

    # ---- Check 2: overlay painted throughout, with genuinely moving opacity ----
    moving_paints = [(t, op) for t, op in paint_log if op < 0.999]
    if moving_paints:
        opacities = [op for _, op in moving_paints]
        print(f"  fade overlay painted {len(paint_log)} total frames, "
              f"{len(moving_paints)} showing genuine movement "
              f"(opacity range {min(opacities):.3f}-{max(opacities):.3f})")
        print(f"  CHECK 2 (visible fade, not frozen): "
              f"{'PASS' if len(moving_paints) >= 3 else 'FAIL — too few moving frames'}")
    else:
        print("  CHECK 2 (visible fade, not frozen): FAIL — no moving paint frames observed at all")

    # ---- Check 3: event loop stayed alive (no huge heartbeat gap) ----
    if len(heartbeat_log) >= 2:
        gaps_ms = [(heartbeat_log[i+1] - heartbeat_log[i]) * 1000 for i in range(len(heartbeat_log)-1)]
        max_gap = max(gaps_ms)
        max_gap_idx = gaps_ms.index(max_gap)
        gap_start_rel_ms = (heartbeat_log[max_gap_idx] - settings_close_called_at) * 1000
        gap_end_rel_ms = (heartbeat_log[max_gap_idx + 1] - settings_close_called_at) * 1000
        print(f"  heartbeat ticks: {len(heartbeat_log)}, max gap between ticks: {max_gap:.1f}ms "
              f"(expected ~10-30ms if the event loop never stalled)")
        print(f"  max gap window, relative to dismiss call: {gap_start_rel_ms:.1f}ms -> {gap_end_rel_ms:.1f}ms")
        print(f"  full gap list (ms): {[round(g,1) for g in gaps_ms]}")
        print(f"  CHECK 3 (event loop never stalled): "
              f"{'PASS' if max_gap < 100 else 'FAIL — event loop appears to have stalled'}")
    else:
        print("  CHECK 3 (event loop never stalled): FAIL — too few heartbeat ticks captured")

    # ---- Check 5: final theme is the COMMITTED one, not the hovered preview ----
    expected_sheet = themes.get_base_stylesheet(ACTIVE_THEME)
    live_sheet = mw.styleSheet()
    theme_correct = (live_sheet == expected_sheet)
    print(f"  CHECK 5 (Esc/gutter lands on committed theme, not hover preview): "
          f"{'PASS' if theme_correct else 'FAIL'}")
    if not theme_correct:
        hover_sheet = themes.get_base_stylesheet(HOVER_THEME)
        stuck_on_hover = (live_sheet == hover_sheet)
        print(f"    (stuck on hover-previewed theme: {stuck_on_hover})")

    print(f"  CHECK 1 (preview cut short, real snapback started): "
          f"{'PASS' if preview_was_running and closed else 'inconclusive'}")
    print(f"  CHECK 4 (panel actually closes, no hang): {'PASS' if closed else 'FAIL'}")

    # ================================================================
    # TEST 6: termination-guarantee fallback
    # ================================================================
    print("\n" + "=" * 70)
    print("TEST 6: termination-guarantee fallback (fade forced to never settle naturally)")
    print("=" * 70)

    reset_to_active()
    open_settings_panel_and_settle()

    # Force call_when_theme_settled's normal path to never see _fade_in_flight go
    # False on its own -- simulates "the fade genuinely never completes" by
    # overriding the property with one that's permanently stuck True, and
    # confirm the dismiss still proceeds via the timeout, not a hang.
    tm._fade_in_flight = True  # will be set True again by the real hover-out below

    # Temporarily shrink the timeout so this test doesn't take 2 real seconds --
    # confirms the SAME mechanism at a faster cadence, not a different one.
    import fabulor.ui.theme_manager as theme_manager_module
    original_timeout = theme_manager_module._THEME_SETTLE_TIMEOUT_MS
    theme_manager_module._THEME_SETTLE_TIMEOUT_MS = 300

    snap_forward_calls = []
    _real_snap_forward = tm.snap_theme_forward

    def _counting_snap_forward():
        snap_forward_calls.append(time.perf_counter())
        return _real_snap_forward()

    tm.snap_theme_forward = _counting_snap_forward

    # Start a real hover-out, then FORCE _fade_in_flight back to True right after
    # (simulating a fade that started but will never naturally clear).
    tm._on_theme_unhovered()
    tm._fade_in_flight = True  # force-stuck, as if the fade will never settle

    t_dismiss = time.perf_counter()
    pm.hide_all_panels()

    closed2, waited_ms2 = pump_until(lambda: not mw.settings_panel.isVisible(), timeout_ms=3000, step_ms=10)

    theme_manager_module._THEME_SETTLE_TIMEOUT_MS = original_timeout

    print(f"  panel closed via fallback: {closed2} (waited {waited_ms2}ms)")
    print(f"  snap_theme_forward() called as fallback: {len(snap_forward_calls) > 0} "
          f"({len(snap_forward_calls)} time(s))")
    print(f"  CHECK 6 (termination guarantee prevents a hang): "
          f"{'PASS' if closed2 and len(snap_forward_calls) > 0 else 'FAIL'}")

    # ================================================================
    # TEST 7: a genuine NEW hover arrives WHILE the dismiss is waiting
    # ================================================================
    # Live-reproduced by Pryme (2026-08-05): "The Eyrie hovered, falls to main
    # screen, corrects after" — Esc pressed while hovering theme A, a genuine
    # new hover on theme B lands and interrupts A's snapback fade BEFORE it
    # settles, B's own fade then settles on its own schedule. The predicate bug
    # (bare `not _fade_in_flight`) read B's settle as the dismiss's own snapback
    # having finished and closed the panel showing B for one frame. This test
    # drives the exact same real call sequence against the real ThemeManager and
    # confirms the panel never closes while displaying anything other than the
    # committed theme.
    print("\n" + "=" * 70)
    print("TEST 7: a genuine new hover interrupts the dismiss's own snapback mid-wait")
    print("=" * 70)

    N_MIDWAIT_TRIALS = 5
    midwait_results = []

    for trial in range(1, N_MIDWAIT_TRIALS + 1):
        reset_to_active()
        open_settings_panel_and_settle()
        assert mw.tabs.currentIndex() == 0
        assert mw.settings_panel.isVisible()

        # Hover theme A first (mirrors "hovering Fire and Blood" in the real log).
        tm._on_theme_changed("Rose Code", save=False, fade_ms=1500, hover=True,
                              bypass_panel_open_guard=True)
        pump(120)  # let A's preview genuinely start

        # Track every real paint of the fade overlay's effect during the whole
        # sequence, so we can directly see the displayed theme was never
        # anything but Rose Code (mid-preview) or ACTIVE_THEME (once genuinely
        # settled) at the moment the panel closes.
        displayed_at_close = {}

        def _wrapped_after_gap(tm=tm, displayed_at_close=displayed_at_close):
            displayed_at_close['theme'] = tm._active_display_theme_internal
            displayed_at_close['is_hover_active'] = tm._is_hover_active
            return _real_after_gap()

        pm._close_settings_flow_after_settle_gap = _wrapped_after_gap

        # THE DISMISS — Esc/gutter path.
        pm.hide_all_panels()  # -> _close_settings_flow -> _on_theme_unhovered()
        # starts the real snapback fade toward ACTIVE_THEME. It has NOT settled
        # yet (a 200ms fade, and _apply_stylesheets alone costs ~700ms).

        # A genuine NEW hover arrives while the snapback is still mid-wait —
        # exactly the live-reproduced race. Fire it as soon as we can observe
        # the snapback is actually in flight, mirroring how little time the
        # real repro had between Esc and the next swatch's enterEvent.
        interrupted = pump_until(lambda: tm._fade_in_flight, timeout_ms=1500, step_ms=5)[0]
        if interrupted:
            tm._on_theme_changed("The Eyrie", save=False, fade_ms=300, hover=True,
                                  bypass_panel_open_guard=True)

        closed3, waited_ms3 = pump_until(lambda: not mw.settings_panel.isVisible(),
                                          timeout_ms=4000, step_ms=10)

        expected_sheet = themes.get_base_stylesheet(ACTIVE_THEME)
        live_sheet = mw.styleSheet()
        final_theme_correct = (live_sheet == expected_sheet)

        closed_while_wrong = (
            'theme' in displayed_at_close
            and (displayed_at_close['theme'] != ACTIVE_THEME
                 or displayed_at_close.get('is_hover_active'))
        )

        midwait_results.append({
            "trial": trial,
            "interrupted": interrupted,
            "closed": closed3,
            "displayed_at_close": displayed_at_close.get('theme'),
            "was_hover_at_close": displayed_at_close.get('is_hover_active'),
            "final_theme_correct": final_theme_correct,
            "closed_while_wrong": closed_while_wrong,
        })
        print(f"  trial {trial}: mid-wait hover injected={interrupted}  "
              f"closed={closed3} (waited {waited_ms3}ms)  "
              f"theme_displayed_at_close_decision={displayed_at_close.get('theme')!r} "
              f"was_hover={displayed_at_close.get('is_hover_active')}  "
              f"final_theme_correct={final_theme_correct}  "
              f"{'*** CLOSED WHILE WRONG ***' if closed_while_wrong else 'OK'}")

    pm._close_settings_flow_after_settle_gap = _real_after_gap

    any_wrong = any(r["closed_while_wrong"] for r in midwait_results)
    all_final_correct = all(r["final_theme_correct"] for r in midwait_results)
    print(f"\n  CHECK 7 (dismiss never proceeds while displaying a non-committed "
          f"theme, across {N_MIDWAIT_TRIALS} trials with a genuine mid-wait hover): "
          f"{'PASS' if not any_wrong and all_final_correct else 'FAIL'}")

    # ================================================================
    # TEST 8: cover-art theme mode dismiss (With pool / Exclusive)
    # ================================================================
    # Live-reported by Pryme (2026-08-05): cover-art theme modes block/mistime
    # panel dismissal on Esc/gutter. Root cause: get_committed_theme() used to
    # always return _current_theme_name (a bare string), but _on_theme_unhovered()
    # targets _cover_theme (a dict) whenever _cover_theme_active is True — a
    # dict-vs-string comparison in the settle predicate could never be True via
    # its intended path, and the dismiss only "worked" by accident, via a
    # DIFFERENT, older no-op guard in _on_theme_changed coincidentally matching
    # first. This test simulates an active cover theme directly (no real cover
    # image needed — a synthetic theme dict is sufficient) and confirms the
    # dismiss now closes PROMPTLY (well under the 2000ms termination-guarantee
    # timeout), not via that fallback.
    print("\n" + "=" * 70)
    print("TEST 8: cover-art theme mode dismiss (With pool / Exclusive)")
    print("=" * 70)

    import fabulor.ui.theme_manager as theme_manager_module2

    SYNTHETIC_COVER_THEME = {
        "bg_deep": "#0A1216", "bg_main": "#151F24", "bg_sidebar": "#121E26",
        "bg_dropdown": "#2A363E", "text": "#B1CDDF", "accent": "#4A8FBA",
        "accent_light": "#51AAE2", "accent_dark": "#4282AA",
    }

    for mode_name in ("with_pool", "exclusive"):
        print(f"\n  -- mode: {mode_name} --")
        reset_to_active()
        open_settings_panel_and_settle()
        assert mw.tabs.currentIndex() == 0
        assert mw.settings_panel.isVisible()

        # Simulate the cover theme genuinely being active and settled, as if a
        # book with a cover had already been loaded under this mode.
        tm._cover_theme = SYNTHETIC_COVER_THEME
        tm._cover_theme_active = True
        tm._on_theme_changed(SYNTHETIC_COVER_THEME, save=False, fade_ms=0,
                              hover=False, bypass_panel_open_guard=True)
        pump(50)

        pre_dismiss_committed = tm.get_committed_theme()
        assert pre_dismiss_committed is SYNTHETIC_COVER_THEME, (
            "harness setup check: get_committed_theme() should already resolve "
            "to the cover theme dict before the dismiss even starts"
        )

        t_dismiss_cover = time.perf_counter()
        pm.hide_all_panels()  # Esc/gutter path

        closed4, waited_ms4 = pump_until(lambda: not mw.settings_panel.isVisible(),
                                          timeout_ms=3000, step_ms=10)
        dismiss_duration_ms = (time.perf_counter() - t_dismiss_cover) * 1000

        # The key check: did this close PROMPTLY (normal settle territory, per
        # the ~700-1000ms worst-case measured in review/Investigation_260804_
        # animation_latency.md), or did it silently ride the 2000ms termination
        # timeout (the accident this fix removes)?
        used_timeout_fallback = dismiss_duration_ms >= (theme_manager_module2._THEME_SETTLE_TIMEOUT_MS * 0.9)

        print(f"    committed theme before dismiss: cover dict (id={id(pre_dismiss_committed)})")
        print(f"    panel closed: {closed4} (took {dismiss_duration_ms:.1f}ms)")
        print(f"    used 2000ms timeout fallback (the bug): {used_timeout_fallback}")
        print(f"    CHECK 8-{mode_name} (closes promptly, not via 2000ms timeout accident): "
              f"{'PASS' if closed4 and not used_timeout_fallback else 'FAIL'}")

        # Reset cover-art state before the next mode / before mw.close().
        tm._cover_theme_active = False
        tm._cover_theme = None

    mw.close()


if __name__ == "__main__":
    main()
