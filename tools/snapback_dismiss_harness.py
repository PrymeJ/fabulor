#!/usr/bin/env python
"""Gutter-dismiss-during-snapback timing harness (investigate/restyle-cost-depth-and-narrowing).

Automated, independently-verified test for whether a theme correctly reverts to the
active theme when the gutter is clicked to dismiss Settings while a hover-preview
snapback fade is still in flight.

REDESIGN (batch 3, 2026-08-02): batches 1-2 swept a wall-clock delay between
_on_theme_unhovered() and hide_all_panels(), on the theory that the delay
controlled whether the 200ms snapback fade was still in flight when
snap_theme_forward's _fade_overlay.isVisible() fallback checked it. That theory
was wrong: _close_settings_flow (panels.py:1379) calls _on_theme_unhovered() and
snap_theme_forward() back-to-back, SYNCHRONOUSLY, with no event-loop turn between
them. The wall-clock delay before hide_all_panels() therefore never changes the
gap between THOSE two calls — it was sweeping a variable that doesn't control
that particular race. 72 trials across two batches correctly found nothing,
because there was nothing there to find with that variable. Batch 3 dropped the
delay axis and instead snapshotted _fade_anim.state()/_fade_overlay.isVisible()
directly, which found the real batch-3 mechanism: a SECOND _on_theme_unhovered()
call (this harness's own trial structure at the time) getting stashed then
drained by snap_theme_forward — a different, already-understood, working-as-
designed mechanism (see review/Investigation_260802_double_fire_reentrancy.md).

REDESIGN 2 (2026-08-03, fallback-necessity investigation): the delay axis is
reintroduced, but placed correctly this time. The earlier delay attempts put the
wait INSIDE the do_trial call between _on_theme_unhovered() and hide_all_panels()
-- which cannot matter, per the structural fact above (those two calls in
_close_settings_flow are adjacent with no gap to widen). The REAL scenario this
batch targets is different: a genuine leave-triggered hover-out starts the real
200ms snapback fade (via _on_themes_tab_left -> _on_theme_unhovered(), the
SWATCH-LEAVE path, not the dismiss path), and the user's dismiss CLICK arrives
some time later, while that fade may STILL be running. The delay that actually
controls whether the fade is mid-flight is the one BETWEEN the hover-out and the
dismiss call -- inserted here as a real pump() between tm._on_theme_unhovered()
(simulating the genuine leave) and mw.panel_manager.hide_all_panels() (the
dismiss). This is a structurally different placement from both earlier delay
attempts, chosen because it is the only point in the real call sequence where a
gap can exist at all.

Buckets concentrate inside the 200ms fade window specifically (20/50/80/110/
140/170ms), per the task's request to catch the fade genuinely still running at
dismiss time, plus 0ms and 250ms as before/after-window controls.

METHODOLOGY (do not weaken any of these without updating this docstring):

1. GROUND TRUTH IS NEVER AN INTERNAL FLAG FOR THE FINAL VERDICT. Two independent
   checks per trial:
   - STYLESHEET-STRING CHECK: read the LIVE mw.styleSheet() after the trial settles
     and diff it, byte-for-byte, against get_base_stylesheet(expected_active_theme)
     computed fresh from the theme name. This catches "wrong/stale sheet applied."
   - PIXEL CHECK: grab the actual composited MainWindow and sample a real pixel,
     compare against the expected theme's known flat RGB. This catches "correct
     sheet applied but didn't actually render" (a repaint/compositing miss).
   These are reported SEPARATELY, never collapsed into one verdict. Internal state
   (_fade_anim.state(), _fade_overlay.isVisible()) IS read this batch, but only as
   MECHANISM INSTRUMENTATION explaining why a verdict came out the way it did —
   never as a substitute for either ground-truth check above.

2. MECHANISM TRACING IS OBSERVATIONAL, NOT INFERRED. A second `finished` slot is
   attached to the real `_fade_anim` (Qt supports multiple slots per signal; this
   does not alter the connection the app itself relies on) to observe whether the
   snapback fade's own completion signal fired. `_apply_stylesheets` is wrapped
   (call-through, not replaced) to count real invocations per trial, with each
   call's real caller captured via traceback so a fallback-triggered apply can be
   distinguished from the normal fade-start apply by WHERE it was called from,
   not just how many times.

3. THE REAL SIGNAL PATH IS USED THROUGHOUT. Hover-out is driven via the real
   `_on_theme_unhovered()` entry point (the same one a genuine swatch leaveEvent
   calls via _on_themes_tab_left), and dismissal is driven via the real
   `hide_all_panels()` -> `_close_settings_flow()` call chain. `_on_theme_changed`
   is never bypassed. Bypassing it previously produced a misleading "double-fire"
   false lead (see review/Investigation_260802_restyle_cost_depth_and_narrowing.md).

Run live, on-screen — QT_QPA_PLATFORM must NOT be set to offscreen. This is a
compositing/timing bug class; see CLAUDE.md's "Pre-screen visual changes... but
never in place of Pryme's eyes" and the standing rule that live geometry/paint
issues are not reproducible in a headless harness.

Usage:
    source fabulorenv/bin/activate
    LD_PRELOAD=/usr/lib64/libstdc++.so.6 python tools/snapback_dismiss_harness.py

Runs ONE batch (all delay-bucket x theme combinations, one trial each) and
exits. Does NOT loop. Re-invoke manually for the next batch.
"""
import sys
import os
import csv
import time
import itertools
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("FABULOR_LOG_LEVEL", "WARNING")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, QEventLoop, QPoint, Qt, QAbstractAnimation
from PySide6.QtGui import QCursor

app = QApplication.instance() or QApplication([])

from fabulor.app import MainWindow
from fabulor import themes

# Themes swept this batch: multiple FLAT (non-gradient) themes, confirmed via
# THEMES dict inspection, so pixel sampling stays unambiguous across all of them.
ACTIVE_THEME = "Alzabo"
SWEEP_HOVER_THEMES = ["Blindsight", "Rose Code", "Slow Regard"]
for _n in [ACTIVE_THEME] + SWEEP_HOVER_THEMES:
    assert "gradient_bg_start" not in themes.THEMES[_n], f"{_n} is a gradient theme"

_HOVER_DEBOUNCE_MS = 80
_SNAPBACK_FADE_MS = 200  # mirrors theme_manager._SNAPBACK_FADE_MS


def pump(ms):
    """Run the real Qt event loop for `ms` milliseconds — NOT time.sleep(), which
    would starve the event loop and prevent the real QTimers (hover debounce, fade
    animation) from ever firing."""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def expected_rgb_for(theme_name):
    t = themes._resolve_theme(theme_name)
    hexcolor = t['bg_main'].lstrip('#')
    return tuple(int(hexcolor[i:i+2], 16) for i in (0, 2, 4))


def main():
    mw = MainWindow()
    mw.show()
    app.processEvents()
    pump(300)
    # Extra settle margin before trial 1: MainWindow() construction can leave panel-
    # animation-adjacent state (blur grab warmup, idle-preload scheduling) still
    # settling for longer than 300ms on a cold start, which was observed (2026-08-03)
    # to make trial 1 specifically retry its first hover 2-3 times via
    # complete_main_fade's any_panel_animating resume before the panel actually
    # became visible -- a real cold-start variance, not a bug in the mechanism under
    # test. Extra margin here, once, costs nothing (paid before any trial is timed).
    pump(1000)

    tm = mw.theme_manager

    apply_call_log = []
    fade_finished_log = []

    _real_apply = tm._apply_stylesheets

    def _counting_apply(theme_name, hover=False, force_all_panels=False):
        t0 = time.perf_counter()
        import traceback
        caller = traceback.extract_stack()[-2]
        result = _real_apply(theme_name, hover=hover, force_all_panels=force_all_panels)
        apply_call_log.append({
            "t": t0, "theme_name": theme_name if isinstance(theme_name, str) else "<dict/cover>",
            "hover": hover,
            "caller": f"{caller.name}:{caller.lineno}",
        })
        return result

    tm._apply_stylesheets = _counting_apply

    def _on_fade_finished_observer():
        fade_finished_log.append(time.perf_counter())

    tm._fade_anim.finished.connect(_on_fade_finished_observer)

    def reset_to_active():
        apply_call_log.clear()
        fade_finished_log.clear()
        tm._current_theme_name = ACTIVE_THEME
        tm._on_theme_changed(ACTIVE_THEME, save=False, fade_ms=0, hover=False,
                              bypass_panel_open_guard=True)
        app.processEvents()
        pump(50)

    def open_settings_panel():
        pm = mw.panel_manager
        if not pm.settings_panel.isVisible():
            pm._open_settings_flow()
            app.processEvents()
            pump(400)

    def snapshot_fade_state():
        state = tm._fade_anim.state()
        _state_names = {
            QAbstractAnimation.State.Stopped: "Stopped",
            QAbstractAnimation.State.Paused: "Paused",
            QAbstractAnimation.State.Running: "Running",
        }
        return {
            "fade_anim_state": _state_names.get(state, str(state)),
            "fade_overlay_visible": tm._fade_overlay.isVisible() if hasattr(tm, "_fade_overlay") else None,
            "fade_in_flight": getattr(tm, "_fade_in_flight", None),
        }

    def do_trial(hover_theme, delay_ms):
        reset_to_active()
        open_settings_panel()

        # Real hover: enter one swatch, wait past the 80ms debounce so a genuine
        # preview actually applies and starts nothing yet (hover fade, not the
        # snapback fade) -- confirmed via apply_call_log below, not assumed.
        tm._on_theme_hovered(hover_theme)
        pump(_HOVER_DEBOUNCE_MS + 20)  # past the 80ms debounce; preview fade now starting

        # Preview fade duration is config.get_theme_fade_duration() * 0.5 -- NOT a
        # hardcoded 375ms. Found live (2026-08-03): this machine's PERSISTED
        # QSettings value is 1500ms (not the code's 750ms default), making the real
        # preview fade 750ms, not 375ms -- a hardcoded pump(500) silently left the
        # preview running every single trial, so hover-out's _on_theme_changed call
        # collided with an IN-FLIGHT PREVIEW fade (stashed via the _fade_running
        # guard, drained later by snap_theme_forward's UNRELATED stash-drain path)
        # instead of cleanly starting a fresh snapback fade against a settled
        # preview -- a completely different, already-understood mechanism (see
        # review/Investigation_260802_double_fire_reentrancy.md), not the one this
        # harness targets. Read the REAL live value and poll for actual settle
        # instead of guessing a fixed wait, so this can't silently drift again if
        # the persisted config changes.
        real_preview_fade_ms = int(tm.config.get_theme_fade_duration() * 0.5)
        settle_deadline_ms = real_preview_fade_ms + 400  # generous margin
        waited_ms = 0
        while waited_ms < settle_deadline_ms:
            pump(50)
            waited_ms += 50
            if snapshot_fade_state()["fade_anim_state"] == "Stopped":
                break
        _preview_settled = snapshot_fade_state()
        if _preview_settled["fade_anim_state"] != "Stopped":
            print(f"  !!! preview fade (real duration {real_preview_fade_ms}ms) not "
                  f"settled after {waited_ms}ms wait: {_preview_settled}")

        pre_unhover_apply_count = len(apply_call_log)

        # Real hover-out (the genuine-leave path, same call _on_themes_tab_left
        # makes) -- this is what starts the real 200ms SNAPBACK fade.
        _t_unhover_call_start = time.perf_counter()
        tm._on_theme_unhovered()
        _t_unhover_call_end = time.perf_counter()
        snap_at_unhover = snapshot_fade_state()
        post_unhover_apply_count = len(apply_call_log)

        # THE DELAY THAT ACTUALLY MATTERS: real wall-clock wait, via the real Qt
        # event loop, between the genuine hover-out (fade start) and the dismiss
        # click -- landing inside, at, or past the 200ms fade window depending on
        # the bucket. This is the gap _close_settings_flow's own two adjacent
        # calls structurally cannot have; this harness creates it by inserting the
        # dismiss LATER, exactly as a real user's separately-timed leave-then-click
        # gesture would.
        pump(delay_ms)
        snap_before_dismiss = snapshot_fade_state()
        pre_dismiss_apply_count = len(apply_call_log)

        # Real dismiss path.
        mw.panel_manager.hide_all_panels()
        snap_after_dismiss_call = snapshot_fade_state()
        post_dismiss_apply_count = len(apply_call_log)
        app.processEvents()

        pump(700)
        app.processEvents()

        final_apply_count = len(apply_call_log)
        fade_finished_during_trial = len(fade_finished_log)
        dismiss_window_records = apply_call_log[pre_dismiss_apply_count:final_apply_count]

        # ---- Ground truth check A: live stylesheet string ----
        expected_sheet = themes.get_base_stylesheet(ACTIVE_THEME)
        live_sheet = mw.styleSheet()
        stylesheet_ok = (live_sheet == expected_sheet)
        if not stylesheet_ok:
            # Find where the two strings first diverge, for direct diagnosis.
            _min_len = min(len(live_sheet), len(expected_sheet))
            _diverge_at = next((i for i in range(_min_len) if live_sheet[i] != expected_sheet[i]), _min_len)
            print(f"    [stylesheet diff] live_len={len(live_sheet)} expected_len={len(expected_sheet)} "
                  f"first_diverge_at={_diverge_at}\n"
                  f"    live[...]={live_sheet[max(0,_diverge_at-40):_diverge_at+80]!r}\n"
                  f"    expected[...]={expected_sheet[max(0,_diverge_at-40):_diverge_at+80]!r}\n"
                  f"    internal _active_display_theme_internal={getattr(tm, '_active_display_theme_internal', None)!r}")

        # ---- Ground truth check B: actual rendered pixel ----
        pix = mw.grab()
        img = pix.toImage()
        sample_x, sample_y = 15, 400
        px_color = img.pixelColor(sample_x, sample_y)
        actual_rgb = (px_color.red(), px_color.green(), px_color.blue())
        expected_rgb = expected_rgb_for(ACTIVE_THEME)
        pixel_ok = all(abs(a - e) <= 4 for a, e in zip(actual_rgb, expected_rgb))

        applies_in_dismiss_window = post_dismiss_apply_count - pre_dismiss_apply_count
        applies_total_after_delay = final_apply_count - pre_dismiss_apply_count

        return {
            "hover_theme": hover_theme,
            "delay_ms": delay_ms,
            "stylesheet_ok": stylesheet_ok,
            "pixel_ok": pixel_ok,
            "checks_agree": (stylesheet_ok == pixel_ok),
            "actual_rgb": actual_rgb,
            "expected_rgb": expected_rgb,
            "fade_state_at_unhover": snap_at_unhover["fade_anim_state"],
            "overlay_visible_at_unhover": snap_at_unhover["fade_overlay_visible"],
            "fade_state_before_dismiss": snap_before_dismiss["fade_anim_state"],
            "overlay_visible_before_dismiss": snap_before_dismiss["fade_overlay_visible"],
            "fade_state_after_dismiss_call": snap_after_dismiss_call["fade_anim_state"],
            "overlay_visible_after_dismiss_call": snap_after_dismiss_call["fade_overlay_visible"],
            "fade_was_running_before_dismiss": snap_before_dismiss["fade_anim_state"] == "Running",
            "applies_in_dismiss_window": applies_in_dismiss_window,
            "applies_total_after_delay": applies_total_after_delay,
            "fade_finished_count": fade_finished_during_trial,
            "dismiss_window_callers": [rec.get("caller") for rec in dismiss_window_records],
            "unhover_call_duration_ms": (_t_unhover_call_end - _t_unhover_call_start) * 1000,
        }

    # ---- Sweep definition: concentrated inside the 200ms fade window ----
    delay_buckets_ms = [0, 20, 50, 80, 110, 140, 170, 250]
    trials_per_bucket = 6  # x3 themes x8 buckets = 144 trials total, meaningful per-bucket N

    results = []
    trial_num = 0
    total_trials = len(delay_buckets_ms) * len(SWEEP_HOVER_THEMES) * trials_per_bucket
    print(f"Running ONE batch: {total_trials} trials "
          f"({len(delay_buckets_ms)} delay buckets x {len(SWEEP_HOVER_THEMES)} themes x "
          f"{trials_per_bucket} repeats). Live, on-screen. No auto-repeat.")

    for delay_ms, hover_theme, _rep in itertools.product(
            delay_buckets_ms, SWEEP_HOVER_THEMES, range(trials_per_bucket)):
        trial_num += 1
        r = do_trial(hover_theme, delay_ms)
        r["trial_num"] = trial_num
        r["batch_timestamp"] = datetime.now().isoformat()
        results.append(r)
        ok = r["stylesheet_ok"] and r["pixel_ok"]
        print(
            f"[{trial_num:3d}/{total_trials}] delay={delay_ms:4d}ms theme={hover_theme:12s} "
            f"stylesheet={'OK' if r['stylesheet_ok'] else 'FAIL'}  "
            f"pixel={'OK' if r['pixel_ok'] else 'FAIL'}  "
            f"fade_running_before_dismiss={r['fade_was_running_before_dismiss']}  "
            f"applies_in_dismiss_window={r['applies_in_dismiss_window']}  "
            f"unhover_call_ms={r['unhover_call_duration_ms']:.1f}  "
            f"{'OK' if ok else '*** MISMATCH ***'}"
        )

    out_path = os.path.join(os.path.dirname(__file__), "..", "review",
                             "fallback_necessity_harness_results.csv")
    file_exists = os.path.exists(out_path)
    fieldnames = ["batch_timestamp", "trial_num", "hover_theme", "delay_ms",
                  "stylesheet_ok", "pixel_ok", "checks_agree", "actual_rgb", "expected_rgb",
                  "fade_state_at_unhover", "overlay_visible_at_unhover",
                  "fade_state_before_dismiss", "overlay_visible_before_dismiss",
                  "fade_state_after_dismiss_call", "overlay_visible_after_dismiss_call",
                  "fade_was_running_before_dismiss", "applies_in_dismiss_window",
                  "applies_total_after_delay", "fade_finished_count", "dismiss_window_callers",
                  "unhover_call_duration_ms"]
    with open(out_path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            w.writeheader()
        for r in results:
            w.writerow({k: r.get(k) for k in fieldnames})

    # ---- Aggregate report ----
    print("\n=== AGGREGATE (this batch only) ===")
    print(f"Total trials: {len(results)}")
    fails = [r for r in results if not r["stylesheet_ok"] or not r["pixel_ok"]]
    print(f"Trials with ANY check failing: {len(fails)}")
    disagreements = [r for r in results if not r["checks_agree"]]
    print(f"Trials where the two independent checks DISAGREED: {len(disagreements)}")
    if disagreements:
        for r in disagreements:
            print(f"  trial {r['trial_num']}: stylesheet_ok={r['stylesheet_ok']} pixel_ok={r['pixel_ok']}")

    print("\n-- Per-delay-bucket table --")
    print(f"{'delay_ms':>9} {'trials':>7} {'mismatches':>11} {'rate':>7} {'fade_running_before_dismiss (n)':>32}")
    for delay_ms in delay_buckets_ms:
        bucket = [r for r in results if r["delay_ms"] == delay_ms]
        bfails = [r for r in bucket if not r["stylesheet_ok"] or not r["pixel_ok"]]
        running_count = sum(1 for r in bucket if r["fade_was_running_before_dismiss"])
        rate = (len(bfails) / len(bucket) * 100) if bucket else 0.0
        print(f"{delay_ms:>9} {len(bucket):>7} {len(bfails):>11} {rate:>6.1f}% {running_count:>32}")

    print("\n-- Mismatches: mechanism attribution --")
    for r in fails:
        print(f"  trial {r['trial_num']} (delay={r['delay_ms']}ms theme={r['hover_theme']}): "
              f"fade_state_before_dismiss={r['fade_state_before_dismiss']} "
              f"overlay_visible_before_dismiss={r['overlay_visible_before_dismiss']} "
              f"applies_in_dismiss_window={r['applies_in_dismiss_window']} "
              f"callers={r['dismiss_window_callers']}")
    if not fails:
        print("  (no mismatches this batch)")

    print(f"\nResults appended to {out_path}")
    print("Batch complete. Re-invoke manually for the next batch — no auto-loop.")

    mw.close()


if __name__ == "__main__":
    main()
