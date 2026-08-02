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
them (snap_theme_forward's own comment: "this method runs immediately after
_on_theme_unhovered(), in the same call stack with no intervening event-loop
turn"). The wall-clock delay before hide_all_panels() therefore never changes
the gap between those two calls — it was sweeping a variable that doesn't
control the race. 72 trials across two batches correctly found nothing, because
there was nothing there to find with that variable.

This batch instead directly SNAPSHOTS the real state the fallback branch reads —
_fade_anim.state() and _fade_overlay.isVisible() — at the instants that matter
(immediately after _on_theme_unhovered() returns, and immediately after
snap_theme_forward() returns), rather than inferring them from wall-clock delay.
This answers "did the fallback's precondition actually hold" as an observed fact
per trial instead of a guess. The swatch-count/dwell-bucket axes are kept
(they exercise different real code paths: the no-op guard vs. a real fade start);
the delay axis is dropped, since it doesn't reach the mechanism under test.

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
   (call-through, not replaced) to count real invocations per trial. Two
   `_apply_stylesheets` calls in one trial means both the synchronous fade-start
   path AND snap_theme_forward's `_fade_overlay.isVisible()` fallback ran; one
   call means the fallback did not fire. NEW this batch: direct snapshots of
   `_fade_anim.state()` and `_fade_overlay.isVisible()` at the two checkpoints
   named above, logged per trial, so "did the fallback's own precondition hold"
   is answered directly rather than inferred from apply-count alone.

3. THE REAL SIGNAL PATH IS USED THROUGHOUT. Hover is driven via the real
   `_on_theme_hovered` entry point and the real 80ms debounce QTimer (not a direct
   call to `_fire_pending_hover` — the timer is allowed to fire on its own), and
   dismissal is driven via the real `hide_all_panels()` -> `_close_settings_flow()`
   call chain. `_on_theme_changed` is never bypassed. Bypassing it previously
   produced a misleading "double-fire" false lead (see
   review/Investigation_260802_restyle_cost_depth_and_narrowing.md).

Run live, on-screen — QT_QPA_PLATFORM must NOT be set to offscreen. This is a
compositing/timing bug class; see CLAUDE.md's "Pre-screen visual changes... but
never in place of Pryme's eyes" and the standing rule that live geometry/paint
issues are not reproducible in a headless harness.

Usage:
    source fabulorenv/bin/activate
    LD_PRELOAD=/usr/lib64/libstdc++.so.6 python tools/snapback_dismiss_harness.py

Runs ONE batch (all swatch-count x dwell-time combinations, one trial each) and
exits. Does NOT loop — per Pryme's instruction, batches are meant to be spaced
across sessions. Re-invoke manually for the next batch.
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

# Two FLAT (non-gradient) themes, confirmed via THEMES dict inspection (2026-08-02):
# gradient themes make single-pixel sampling ambiguous near stop boundaries, so the
# test deliberately picks themes with no gradient_bg_start/gradient_bg_end key.
ACTIVE_THEME = "Alzabo"
HOVER_THEME = "Blindsight"

assert "gradient_bg_start" not in themes.THEMES[ACTIVE_THEME]
assert "gradient_bg_start" not in themes.THEMES[HOVER_THEME]

_HOVER_DEBOUNCE_MS = 80  # mirrors theme_manager._HOVER_DEBOUNCE_MS; kept independent
                          # on purpose so a future change to the real constant doesn't
                          # silently change what this harness believes it's testing


def pump(ms):
    """Run the real Qt event loop for `ms` milliseconds — NOT time.sleep(), which
    would starve the event loop and prevent the real QTimers (hover debounce, fade
    animation) from ever firing. This is what makes hover/fade/dismiss run through
    their REAL asynchronous machinery instead of being faked."""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def expected_rgb_for(theme_name):
    """The known flat background colour a FLAT theme's mainwindow paints, per
    get_base_stylesheet's own main_bg_style resolution for the no-gradient case."""
    t = themes._resolve_theme(theme_name)
    hexcolor = t['bg_main'].lstrip('#')
    return tuple(int(hexcolor[i:i+2], 16) for i in (0, 2, 4))


def main():
    mw = MainWindow()
    mw.show()
    app.processEvents()
    pump(300)  # let startup settle (idle preload timers, initial paint) before trials

    tm = mw.theme_manager

    # ---- Instrumentation: observational only, no behaviour change ----
    apply_call_log = []          # list of dicts per real _apply_stylesheets call
    fade_finished_log = []       # list of perf_counter() timestamps

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

    # Second slot on the REAL signal — does not touch the app's own connection to
    # _on_fade_finished (theme_manager.py:243). Qt supports multiple slots per signal.
    tm._fade_anim.finished.connect(_on_fade_finished_observer)

    def reset_to_active():
        """Set the fixture's baseline WITHOUT bypassing the real apply path: routes
        through _on_theme_changed like a genuine non-hover apply would, then waits
        for it to fully settle before starting the next trial."""
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
            pump(400)  # let the slide-in + blur (if enabled) fully settle

    def hover_swatch(theme_name, dwell_ms):
        """Real path: _on_theme_hovered arms the debounce timer; we pump for dwell_ms
        so the REAL QTimer decides whether to fire _fire_pending_hover (>=80ms) or
        get superseded by the next hover in the sequence (<80ms)."""
        tm._on_theme_hovered(theme_name)
        pump(dwell_ms)

    def snapshot_fade_state(label):
        """Direct observation of the exact state snap_theme_forward's fallback
        branch reads (_fade_anim.state(), _fade_overlay.isVisible()), plus the
        themes_tab_active inputs that decide which of the three fade-start
        branches in _on_theme_changed actually ran. Printed and returned, never
        used to compute the pass/fail verdict — verdict stays pixel+stylesheet
        only (see METHODOLOGY item 1)."""
        state = tm._fade_anim.state()
        _state_names = {
            QAbstractAnimation.State.Stopped: "Stopped",
            QAbstractAnimation.State.Paused: "Paused",
            QAbstractAnimation.State.Running: "Running",
        }
        state_name = _state_names.get(state, str(state))
        overlay_visible = tm._fade_overlay.isVisible() if hasattr(tm, "_fade_overlay") else None
        tabs = getattr(mw, "tabs", None)
        settings_visible = mw.settings_panel.isVisible() if hasattr(mw, "settings_panel") else None
        tab_index = tabs.currentIndex() if tabs is not None else None
        themes_tab_active = (tabs is not None and tab_index == 0 and settings_visible)
        rec = {
            "label": label,
            "fade_anim_state": state_name,
            "fade_overlay_visible": overlay_visible,
            "fade_in_flight": getattr(tm, "_fade_in_flight", None),
            "themes_tab_active": themes_tab_active,
            "tab_index": tab_index,
            "settings_panel_visible": settings_visible,
        }
        return rec

    def do_trial(swatch_count, dwell_ms):
        reset_to_active()
        open_settings_panel()

        # Hover `swatch_count` distinct themes in sequence, each dwelling `dwell_ms`.
        # The last one hovered is HOVER_THEME so the harness's expectations are fixed;
        # earlier ones are drawn from other flat themes so a real multi-swatch sweep
        # is exercised, not just a repeat of the same name.
        flat_themes = [n for n, t in themes.THEMES.items()
                       if "gradient_bg_start" not in t and n not in (ACTIVE_THEME, HOVER_THEME)]
        sequence = (flat_themes[:max(0, swatch_count - 1)] + [HOVER_THEME])[-swatch_count:]
        for name in sequence:
            hover_swatch(name, dwell_ms)

        # Whether the LAST hover actually fired a real preview apply depends on the
        # real debounce timer (dwell_ms vs _HOVER_DEBOUNCE_MS) — this is observed,
        # not asserted, via apply_call_log below.
        pre_dismiss_apply_count = len(apply_call_log)

        # Real hover-out path. This is the call that starts the 200ms snapback fade
        # (fade_ms=_SNAPBACK_FADE_MS, hover=False) IF a preview was actually applied
        # (i.e. dwell_ms cleared the debounce) — the no-op guard at the top of
        # _on_theme_changed returns before starting anything if the active theme +
        # hover flag already match, which is the dwell=40ms case.
        tm._on_theme_unhovered()
        snap_after_unhover = snapshot_fade_state("immediately after _on_theme_unhovered()")
        apply_count_after_unhover = len(apply_call_log)

        # Real dismiss path: hide_all_panels() -> _close_settings_flow(), same call
        # chain _on_drag_area_pressed uses (that method's own book-count/mouse-event
        # wrapper is not under test here). _close_settings_flow calls
        # _on_theme_unhovered() then snap_theme_forward() itself, synchronously — so
        # calling hide_all_panels() here re-invokes _on_theme_unhovered() a SECOND
        # time (harmless: idempotent no-op on an already-unhovered state) before
        # snap_theme_forward() runs for real inside the same call. No event-loop
        # turn is inserted here on purpose — that mirrors the real click path, where
        # nothing runs between hover-out and the click that dismisses the panel.
        mw.panel_manager.hide_all_panels()
        snap_after_dismiss_call = snapshot_fade_state("immediately after hide_all_panels() returns")
        apply_count_after_dismiss_call = len(apply_call_log)
        app.processEvents()

        # Let the panel slide-out animation and any pending fade/fallback fully
        # settle before sampling ground truth. 700ms covers the 200/375/750ms fade
        # variants plus the ~300ms slide with margin.
        pump(700)
        app.processEvents()

        post_dismiss_apply_count = len(apply_call_log)
        fade_finished_during_trial = len(fade_finished_log)
        applies_this_trial_records = apply_call_log[pre_dismiss_apply_count:post_dismiss_apply_count]

        # ---- Ground truth check A: live stylesheet string ----
        expected_sheet = themes.get_base_stylesheet(ACTIVE_THEME)
        live_sheet = mw.styleSheet()
        stylesheet_ok = (live_sheet == expected_sheet)

        # ---- Ground truth check B: actual rendered pixel ----
        # Sample the mainwindow's own bg_main background, away from any child
        # widget. (15, 15) was tried first and rejected: live pixel-grid dumping
        # (2026-08-02) showed it lands on a title-bar control glyph, reading
        # (75, 55, 83) on EVERY Alzabo trial regardless of correctness — a
        # constant false failure, not a real one. (15, 400) is confirmed clean
        # against a 40-point grid covering the full window (title bar, content
        # container, and every corner) for both Alzabo and Blindsight.
        pix = mw.grab()
        img = pix.toImage()
        sample_x, sample_y = 15, 400
        px_color = img.pixelColor(sample_x, sample_y)
        actual_rgb = (px_color.red(), px_color.green(), px_color.blue())
        expected_rgb = expected_rgb_for(ACTIVE_THEME)
        # Allow a small tolerance for anti-aliasing at the rounded corner.
        pixel_ok = all(abs(a - e) <= 4 for a, e in zip(actual_rgb, expected_rgb))

        # ---- Mechanism classification ----
        applies_this_trial = post_dismiss_apply_count - pre_dismiss_apply_count
        fallback_relevant_fades = fade_finished_during_trial
        if applies_this_trial == 0:
            mechanism = "NEITHER"
        elif applies_this_trial == 1:
            mechanism = "ONE_APPLY (fade-path OR fallback, not both)"
        elif applies_this_trial >= 2:
            mechanism = f"BOTH ({applies_this_trial} applies)"
        else:
            mechanism = "UNKNOWN"

        return {
            "swatch_count": swatch_count,
            "dwell_ms": dwell_ms,
            "stylesheet_ok": stylesheet_ok,
            "pixel_ok": pixel_ok,
            "checks_agree": (stylesheet_ok == pixel_ok),
            "applies_this_trial": applies_this_trial,
            "fade_finished_count": fallback_relevant_fades,
            "mechanism": mechanism,
            "actual_rgb": actual_rgb,
            "expected_rgb": expected_rgb,
            "internal_active_theme": getattr(tm, "_active_display_theme_internal", None),
            "internal_fade_overlay_visible": tm._fade_overlay.isVisible() if hasattr(tm, "_fade_overlay") else None,
            # NEW this batch — direct state snapshots, mechanism instrumentation only:
            "snap_after_unhover_fade_state": snap_after_unhover["fade_anim_state"],
            "snap_after_unhover_overlay_visible": snap_after_unhover["fade_overlay_visible"],
            "snap_after_unhover_fade_in_flight": snap_after_unhover["fade_in_flight"],
            "snap_after_unhover_themes_tab_active": snap_after_unhover["themes_tab_active"],
            "snap_after_unhover_tab_index": snap_after_unhover["tab_index"],
            "snap_after_unhover_settings_visible": snap_after_unhover["settings_panel_visible"],
            "snap_after_dismiss_fade_state": snap_after_dismiss_call["fade_anim_state"],
            "snap_after_dismiss_overlay_visible": snap_after_dismiss_call["fade_overlay_visible"],
            "snap_after_dismiss_fade_in_flight": snap_after_dismiss_call["fade_in_flight"],
            "applies_this_trial_records": applies_this_trial_records,
            "applies_count_after_unhover": apply_count_after_unhover - pre_dismiss_apply_count,
            "applies_count_after_dismiss_call": apply_count_after_dismiss_call - pre_dismiss_apply_count,
        }

    # ---- Sweep definition (redesigned batch 3) ----
    # Delay axis dropped — see the module docstring's REDESIGN note: _close_settings_flow
    # calls _on_theme_unhovered() then snap_theme_forward() synchronously with no
    # event-loop turn between them, so a wall-clock delay BEFORE hide_all_panels()
    # never changes the gap the fallback race actually depends on. Swatch-count and
    # dwell-bucket are kept — they exercise genuinely different code paths (whether
    # a preview was actually applied before hover-out, via the real 80ms debounce).
    swatch_counts = [1, 2, 4]
    dwell_buckets_ms = [40, 120]  # below and above the 80ms debounce

    results = []
    trial_num = 0
    total_trials = len(swatch_counts) * len(dwell_buckets_ms)
    print(f"Running ONE batch: {total_trials} trials "
          f"({len(swatch_counts)} swatch-counts x {len(dwell_buckets_ms)} dwell buckets). "
          f"Live, on-screen. No auto-repeat. (delay axis dropped this batch — see docstring)")

    for swatch_count, dwell_ms in itertools.product(swatch_counts, dwell_buckets_ms):
        trial_num += 1
        r = do_trial(swatch_count, dwell_ms)
        r["trial_num"] = trial_num
        r["batch_timestamp"] = datetime.now().isoformat()
        results.append(r)
        print(
            f"[{trial_num:3d}/{total_trials}] swatches={swatch_count} "
            f"dwell={dwell_ms:3d}ms  stylesheet={'OK' if r['stylesheet_ok'] else 'FAIL'}  "
            f"pixel={'OK' if r['pixel_ok'] else 'FAIL'}  "
            f"agree={r['checks_agree']}  mechanism={r['mechanism']}  "
            f"actual_rgb={r['actual_rgb']} expected_rgb={r['expected_rgb']}\n"
            f"          [after unhover] fade_state={r['snap_after_unhover_fade_state']} "
            f"overlay_visible={r['snap_after_unhover_overlay_visible']} "
            f"fade_in_flight={r['snap_after_unhover_fade_in_flight']} "
            f"themes_tab_active={r['snap_after_unhover_themes_tab_active']} "
            f"(tab_index={r['snap_after_unhover_tab_index']}, "
            f"settings_visible={r['snap_after_unhover_settings_visible']})\n"
            f"          [after dismiss call] fade_state={r['snap_after_dismiss_fade_state']} "
            f"overlay_visible={r['snap_after_dismiss_overlay_visible']} "
            f"fade_in_flight={r['snap_after_dismiss_fade_in_flight']}\n"
            f"          [apply_stylesheets calls this trial's dismiss window] "
            + (", ".join(f"theme={rec['theme_name']!r} hover={rec['hover']} "
                         f"caller={rec.get('caller')}"
                         for rec in r["applies_this_trial_records"]) or "(none)")
            + f"\n          [apply count: right after _on_theme_unhovered()="
            f"{r['applies_count_after_unhover']}, right after hide_all_panels() returns="
            f"{r['applies_count_after_dismiss_call']}]"
        )

    # ---- Write results, append (never overwrite) so multi-session batches accumulate ----
    # NEW FILE this batch, deliberately NOT appended to snapback_dismiss_harness_results.csv:
    # this redesign drops the delay_ms column and adds the state-snapshot columns, so the
    # column set no longer matches that file's existing header (written by batches 1-2).
    # Appending mismatched columns under an old header would silently corrupt it. If a
    # future batch keeps this same redesigned schema, resume appending to THIS file instead.
    out_path = os.path.join(os.path.dirname(__file__), "..", "review",
                             "snapback_dismiss_harness_results_batch3_redesign.csv")
    file_exists = os.path.exists(out_path)
    fieldnames = ["batch_timestamp", "trial_num", "swatch_count", "dwell_ms",
                  "stylesheet_ok", "pixel_ok", "checks_agree", "applies_this_trial",
                  "fade_finished_count", "mechanism", "actual_rgb", "expected_rgb",
                  "internal_active_theme", "internal_fade_overlay_visible",
                  "snap_after_unhover_fade_state", "snap_after_unhover_overlay_visible",
                  "snap_after_unhover_fade_in_flight", "snap_after_unhover_themes_tab_active",
                  "snap_after_unhover_tab_index", "snap_after_unhover_settings_visible",
                  "snap_after_dismiss_fade_state", "snap_after_dismiss_overlay_visible",
                  "snap_after_dismiss_fade_in_flight"]
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
    print(f"Trials where the two independent checks DISAGREED with each other: {len(disagreements)}")
    if disagreements:
        print("  -> THIS IS A FINDING, not resolved by this harness. Reported as-is:")
        for r in disagreements:
            print(f"     trial {r['trial_num']}: stylesheet_ok={r['stylesheet_ok']} "
                  f"pixel_ok={r['pixel_ok']} mechanism={r['mechanism']}")

    print("\n-- Fail rate by swatch-count --")
    for sc in swatch_counts:
        bucket = [r for r in results if r["swatch_count"] == sc]
        bfails = [r for r in bucket if not r["stylesheet_ok"] or not r["pixel_ok"]]
        print(f"  swatches={sc}: {len(bfails)}/{len(bucket)} failed")

    print("\n-- Fail rate by dwell bucket (relative to 80ms debounce) --")
    for dw in dwell_buckets_ms:
        bucket = [r for r in results if r["dwell_ms"] == dw]
        bfails = [r for r in bucket if not r["stylesheet_ok"] or not r["pixel_ok"]]
        rel = "below" if dw < _HOVER_DEBOUNCE_MS else "above"
        print(f"  dwell={dw:3d}ms ({rel} 80ms debounce): {len(bfails)}/{len(bucket)} failed")

    print("\n-- On FAILED trials, which mechanism(s) ran, and what did the state snapshots show? --")
    for r in fails:
        print(f"  trial {r['trial_num']} (swatches={r['swatch_count']} "
              f"dwell={r['dwell_ms']}ms): mechanism={r['mechanism']} "
              f"fade_finished_count={r['fade_finished_count']}\n"
              f"      after-unhover: fade_state={r['snap_after_unhover_fade_state']} "
              f"overlay_visible={r['snap_after_unhover_overlay_visible']} "
              f"themes_tab_active={r['snap_after_unhover_themes_tab_active']}\n"
              f"      after-dismiss-call: fade_state={r['snap_after_dismiss_fade_state']} "
              f"overlay_visible={r['snap_after_dismiss_overlay_visible']}")
    if not fails:
        print("  (no failures this batch)")

    print("\n-- Fallback precondition check, EVERY trial (not just failures) --")
    print("  Does _fade_overlay.isVisible() ever read True at either checkpoint?")
    any_overlay_true = [r for r in results
                         if r["snap_after_unhover_overlay_visible"] or r["snap_after_dismiss_overlay_visible"]]
    print(f"  Trials where overlay_visible was True at some checkpoint: {len(any_overlay_true)}/{len(results)}")
    if not any_overlay_true:
        print("  -> If this is 0/N, the fallback's own precondition never held in this "
              "harness at all, on EITHER checkpoint — that is itself the answer to why "
              "mechanism=BOTH never appeared in batches 1-2, independent of any delay value.")
    for r in results:
        print(f"    trial {r['trial_num']} (swatches={r['swatch_count']} dwell={r['dwell_ms']}ms): "
              f"after_unhover.overlay_visible={r['snap_after_unhover_overlay_visible']} "
              f"fade_state={r['snap_after_unhover_fade_state']}  |  "
              f"after_dismiss.overlay_visible={r['snap_after_dismiss_overlay_visible']} "
              f"fade_state={r['snap_after_dismiss_fade_state']}")

    print(f"\nResults appended to {out_path}")
    print("Batch complete. Re-invoke manually for the next batch — no auto-loop.")

    mw.close()


if __name__ == "__main__":
    main()
