#!/usr/bin/env python
"""Measure real interrupt-clear and animation-start latency for the theme fade
overlay, live, on-screen — not assumed, not offscreen (investigate/restyle-cost-
depth-and-narrowing, latency-before-sequencing-fix task).

Pryme's claim under test (predates the reverted snapback-blocking fix): stopping
an in-flight animation doesn't clear it promptly, and starting a new one carries
its own ~500ms-ish latency regardless of configured duration. If true, any future
sequencing fix built on "stop() and start() take effect immediately" is unsound.

METHODOLOGY — real paint evidence, not call-return timing:

1. INTERRUPT-CLEAR LATENCY: start a real preview fade (long configured duration,
   so it's still running), then interrupt it (._fade_anim.stop(), the same call
   snap_theme_forward()/_on_theme_changed's stash-supersede path makes). Measure
   elapsed time from the stop() call to the LAST real paintEvent on the fade
   overlay showing an in-progress (non-zero, non-final) opacity. A QLabel with a
   QGraphicsOpacityEffect repaints via the effect's own draw() on every animated
   frame — hooking QGraphicsOpacityEffect.draw (the real composition path, not
   valueChanged, which can fire without a paint if the widget is not exposed) on
   the fade overlay gives real paint evidence, not an inferred one.

2. ANIMATION-START LATENCY: trigger a real _on_theme_changed(..., fade_ms=X) for
   X in {0, 200, 1500}, from a clean (non-fading) state. Measure elapsed time
   from the trigger call to the FIRST real paintEvent showing the NEW animation
   actually progressing (first draw() call on the overlay after start(), or for
   fade_ms=0's synchronous no-overlay path, the first repaint of main_window
   itself reflecting the new stylesheet).

3. Both are measured across multiple trials, reported in RAW CHRONOLOGICAL order
   (per this project's own measurement discipline — sorting to take a median is
   only valid for i.i.d. samples, and a first-call-in-process effect is exactly
   the kind of thing this task is trying to catch or rule out).

Run live, on-screen — QT_QPA_PLATFORM must NOT be offscreen.

Usage:
    source fabulorenv/bin/activate
    LD_PRELOAD=/usr/lib64/libstdc++.so.6 python tools/animation_latency_probe.py
"""
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("FABULOR_LOG_LEVEL", "WARNING")

from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect
from PySide6.QtCore import QTimer, QEventLoop, QAbstractAnimation, QObject, QEvent

app = QApplication.instance() or QApplication([])

from fabulor.app import MainWindow
from fabulor import themes

ACTIVE_THEME = "Alzabo"
OTHER_THEME = "Blindsight"


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def pump_until(predicate, timeout_ms, step_ms=5):
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
    pump(1200)  # cold-start settle margin, same rationale as snapback_dismiss_harness.py

    tm = mw.theme_manager

    # ---- Real paint-event instrumentation on the fade overlay's actual draw path ----
    # QGraphicsOpacityEffect.draw() is called by Qt exactly when the effect composites
    # a frame to screen -- this is the real paint evidence the task requires, not an
    # inference from valueChanged (which can fire without a corresponding paint if the
    # widget isn't currently exposed) and not from the animation's own state() (which
    # only reflects Qt's animation-clock bookkeeping, not compositing).
    paint_log = []  # list of (perf_counter_ts, opacity_at_paint)

    effect = tm._fade_effect
    _real_draw = QGraphicsOpacityEffect.draw

    def _instrumented_draw(self, painter):
        # QGraphicsOpacityEffect.draw is patched at the CLASS level -- every
        # QGraphicsOpacityEffect instance in the whole running app (sliders,
        # other panel effects, anything else using one) calls through here, not
        # just the fade overlay's own effect. Filter to `effect` (tm._fade_effect)
        # specifically, or paint_log conflates unrelated widgets' repaints with
        # the fade overlay's — this was found live: an early run's "stray paints"
        # after stop() showed two interleaved near-1.0 value series, which is
        # exactly what conflating two different effects' opacity looks like.
        if self is effect:
            paint_log.append((time.perf_counter(), self.opacity()))
        return _real_draw(self, painter)

    QGraphicsOpacityEffect.draw = _instrumented_draw

    def reset_to_active():
        paint_log.clear()
        tm._current_theme_name = ACTIVE_THEME
        tm._on_theme_changed(ACTIVE_THEME, save=False, fade_ms=0, hover=False,
                              bypass_panel_open_guard=True)
        app.processEvents()
        pump(80)

    def open_settings_panel():
        pm = mw.panel_manager
        if not pm.settings_panel.isVisible():
            pm._open_settings_flow()
            app.processEvents()
            pump(400)
        # CRITICAL: wait for the settings-panel-open BLUR-IN animation to fully
        # settle before returning. _on_theme_changed's _any_animating guard
        # (theme_manager.py ~1085) treats blur_animation.state()==Running as "a
        # panel animation is in flight" and DEFERS the whole call via
        # call_when_panels_settled until it clears -- this is a real, already-
        # documented mechanism in this codebase (panels.py ~1189: "the first
        # hover after opening Settings took ~2.1s to preview, every time").
        # Found live in this investigation: triggering immediately after a
        # pump(400) open left the 1500ms blur-in still running, so the
        # "animation-start latency" this harness measured was actually just
        # "how much of the blur-in settle window was left" -- a real but
        # DIFFERENT mechanism than the one under test. Waiting here isolates
        # animation-start latency from panel-open settle time.
        found_settled, waited = pump_until(
            lambda: not pm._any_panel_animating(), timeout_ms=3000, step_ms=20)
        if not found_settled:
            print(f"      [DEBUG WARNING] blur-in/panel animation still running after "
                  f"{waited}ms wait -- trigger will be deferred by _any_animating guard")

    # ===================================================================
    # PART 1 — interrupt-clear latency
    # ===================================================================
    print("=" * 70)
    print("PART 1: interrupt-clear latency (stop() -> last in-progress paint)")
    print("=" * 70)

    open_settings_panel()

    interrupt_results = []
    N_INTERRUPT_TRIALS = 5

    for trial in range(1, N_INTERRUPT_TRIALS + 1):
        reset_to_active()

        # Start a long fade so it's still genuinely running when we interrupt it.
        # themes_tab_active path required for the overlay-fade branch (not the
        # slider-color-animation branch) -- confirm Settings + Themes tab visible.
        assert mw.tabs.currentIndex() == 0, "Themes tab must be active for the overlay path"
        assert mw.settings_panel.isVisible()

        LONG_FADE_MS = 3000
        paint_log.clear()
        tm._on_theme_changed(OTHER_THEME, save=False, fade_ms=LONG_FADE_MS, hover=True,
                              bypass_panel_open_guard=True)
        # Let it genuinely run for a bit so we interrupt mid-flight, not at t=0.
        pump(150)
        running = tm._fade_anim.state() == QAbstractAnimation.State.Running
        if not running:
            print(f"  trial {trial}: SKIPPED -- fade not running after 150ms "
                  f"(state={tm._fade_anim.state()})")
            continue

        paints_before_stop = len(paint_log)

        # THE INTERRUPT -- the same call snap_theme_forward()/the stash-supersede
        # path makes.
        t_stop_call = time.perf_counter()
        tm._fade_anim.stop()
        t_stop_returned = time.perf_counter()

        # Now watch real paint events for up to 1000ms to see if the overlay
        # keeps painting in-progress frames after stop() returns.
        deadline = time.perf_counter() + 1.0
        while time.perf_counter() < deadline:
            pump(5)
        paints_after_stop = paint_log[paints_before_stop:]

        # Find the LAST paint that shows a genuinely in-progress opacity -- i.e.
        # real evidence the old animation was still being composited after stop()
        # was called. Use an epsilon well clear of float noise (an idle window-
        # expose repaint of a settled value can read 0.996-0.999, not exactly
        # 1.0) -- 0.02 is far larger than any float-precision artifact and far
        # smaller than a genuinely still-animating step.
        _EPS = 0.02
        opacity_at_stop = paint_log[paints_before_stop - 1][1] if paints_before_stop else 1.0
        stray_paints = [(t, op) for (t, op) in paints_after_stop if abs(op - opacity_at_stop) > _EPS]
        if stray_paints:
            last_stray_t = stray_paints[-1][0]
            clear_latency_ms = (last_stray_t - t_stop_call) * 1000
        else:
            clear_latency_ms = 0.0  # no stray paint at all -- clears within this trial's resolution

        call_overhead_ms = (t_stop_returned - t_stop_call) * 1000

        interrupt_results.append({
            "trial": trial,
            "call_overhead_ms": call_overhead_ms,
            "stray_paint_count": len(stray_paints),
            "clear_latency_ms": clear_latency_ms,
            "opacity_at_stop_moment": paint_log[paints_before_stop - 1][1] if paints_before_stop else None,
        })
        print(f"  trial {trial}: stop() call overhead={call_overhead_ms:.3f}ms  "
              f"stray in-progress paints after stop={len(stray_paints)}  "
              f"clear_latency={clear_latency_ms:.1f}ms")

        # Clean up before next trial.
        tm._fade_overlay.hide()
        tm._fade_effect.setOpacity(0.0)
        tm._fade_in_flight = False

    print("\n-- Part 1 raw chronological results --")
    for r in interrupt_results:
        print(f"  trial {r['trial']}: clear_latency={r['clear_latency_ms']:.1f}ms "
              f"(call_overhead={r['call_overhead_ms']:.3f}ms, "
              f"stray_paints={r['stray_paint_count']})")

    # ===================================================================
    # PART 2 — animation-start latency, across 3 configured durations
    # ===================================================================
    print("\n" + "=" * 70)
    print("PART 2: animation-start latency (trigger -> first new-animation paint)")
    print("=" * 70)

    DURATIONS_MS = [0, 200, 1500]
    N_START_TRIALS = 5

    start_results = {d: [] for d in DURATIONS_MS}

    for duration_ms in DURATIONS_MS:
        for trial in range(1, N_START_TRIALS + 1):
            reset_to_active()
            open_settings_panel()
            reset_to_active()  # extra warmup settle -- trial 1 was previously seen with a
            # stale anim_duration/opacity from panel-open's own construction-time state
            assert mw.tabs.currentIndex() == 0
            assert mw.settings_panel.isVisible()

            paint_log.clear()

            if duration_ms == 0:
                # fade_ms=0 path never touches the overlay at all (see
                # _on_theme_changed's `else:` branch -- hide + apply_stylesheets
                # synchronously, no animation object involved). First-frame
                # evidence here is main_window's own next real Paint event showing
                # the new stylesheet. MainWindow does NOT override paintEvent (grep
                # confirmed) -- monkeypatching type(mw).paintEvent is therefore a
                # no-op against Qt's C++-side virtual dispatch and would silently
                # observe nothing. An installed QObject event filter catching
                # QEvent.Paint is the correct, override-independent way to see a
                # real paint regardless of whether the widget defines its own
                # paintEvent.
                mw_paint_log = []

                class _PaintWatcher(QObject):
                    def eventFilter(self, obj, event):
                        if event.type() == QEvent.Type.Paint:
                            mw_paint_log.append(time.perf_counter())
                        return False

                _watcher = _PaintWatcher()
                mw.installEventFilter(_watcher)

                t_trigger = time.perf_counter()
                tm._on_theme_changed(OTHER_THEME, save=False, fade_ms=0, hover=True,
                                      bypass_panel_open_guard=True)
                t_trigger_returned = time.perf_counter()

                deadline = time.perf_counter() + 1.0
                while time.perf_counter() < deadline and not mw_paint_log:
                    pump(5)

                mw.removeEventFilter(_watcher)

                if mw_paint_log:
                    first_paint_t = mw_paint_log[0]
                    start_latency_ms = (first_paint_t - t_trigger) * 1000
                else:
                    start_latency_ms = None  # no repaint observed within 1s
            else:
                # Use ONE continuous QEventLoop for the whole observation window,
                # with a QTimer sampling inside it -- NOT a tight Python loop of
                # pump(5) calls, each of which constructs/tears down its own
                # QEventLoop. That construction/teardown churn was found (this
                # session) to itself distort Qt's unified animation timer: a
                # poll trace built from pump(5)-in-a-loop showed the fade frozen
                # at its start value for ~950ms before ever moving, which does
                # not match a real running app. A single sustained event loop is
                # the faithful way to observe an animation actually running.
                poll_log = []
                sample_timer = QTimer()
                sample_timer.setInterval(4)

                def _sample():
                    poll_log.append((time.perf_counter(),
                                      tm._fade_anim.state(), tm._fade_effect.opacity(),
                                      tm._fade_anim.currentTime()))

                sample_timer.timeout.connect(_sample)

                obs_loop = QEventLoop()
                QTimer.singleShot(2000, obs_loop.quit)

                t_trigger = time.perf_counter()
                sample_timer.start()
                tm._on_theme_changed(OTHER_THEME, save=False, fade_ms=duration_ms, hover=True,
                                      bypass_panel_open_guard=True)
                t_trigger_returned = time.perf_counter()
                obs_loop.exec()
                sample_timer.stop()

                if paint_log:
                    # The FIRST paint at opacity==1.0 is just the overlay's static
                    # starting frame (painted synchronously during _apply_stylesheets,
                    # before _fade_anim.start() is even reached) -- not evidence the
                    # animation itself is progressing. Real animation-start evidence is
                    # the first paint showing opacity strictly LESS than 1.0, i.e. the
                    # animation clock has actually ticked at least once.
                    first_paint_t, first_opacity = paint_log[0]
                    moving_paints = [(t, op) for (t, op) in paint_log if op < 1.0]
                    if moving_paints:
                        first_moving_t, first_moving_op = moving_paints[0]
                        start_latency_ms = (first_moving_t - t_trigger) * 1000
                    else:
                        start_latency_ms = None
                else:
                    start_latency_ms = None

            call_overhead_ms = (t_trigger_returned - t_trigger) * 1000

            start_results[duration_ms].append({
                "trial": trial,
                "start_latency_ms": start_latency_ms,
                "call_overhead_ms": call_overhead_ms,
            })
            sl = f"{start_latency_ms:.1f}ms" if start_latency_ms is not None else "NEVER PAINTED (1-2s timeout)"
            print(f"  duration={duration_ms:5d}ms trial {trial}: "
                  f"call_overhead={call_overhead_ms:.3f}ms  start_latency={sl}")

            # Let any fade in flight fully settle before the next trial.
            pump(max(duration_ms, 100) + 200)
            tm._fade_overlay.hide()
            tm._fade_effect.setOpacity(0.0)
            tm._fade_in_flight = False

    print("\n-- Part 2 raw chronological results, per configured duration --")
    for duration_ms in DURATIONS_MS:
        print(f"\n  configured duration = {duration_ms}ms:")
        for r in start_results[duration_ms]:
            sl = f"{r['start_latency_ms']:.1f}ms" if r['start_latency_ms'] is not None else "NEVER"
            print(f"    trial {r['trial']}: start_latency={sl}")

    print("\n" + "=" * 70)
    print("SUMMARY (raw, unsorted, chronological within each group)")
    print("=" * 70)
    print("\nInterrupt-clear latency (ms), in trial order:")
    print("  " + ", ".join(f"{r['clear_latency_ms']:.1f}" for r in interrupt_results))
    for duration_ms in DURATIONS_MS:
        vals = [r['start_latency_ms'] for r in start_results[duration_ms]]
        vals_str = ", ".join(f"{v:.1f}" if v is not None else "NEVER" for v in vals)
        print(f"\nAnimation-start latency @ configured {duration_ms}ms, in trial order:")
        print(f"  {vals_str}")

    mw.close()


if __name__ == "__main__":
    main()
