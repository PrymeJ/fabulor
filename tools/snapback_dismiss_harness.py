#!/usr/bin/env python
"""Gutter-dismiss-during-snapback timing harness (investigate/restyle-cost-depth-and-narrowing).

Automated, independently-verified test for whether a theme correctly reverts to the
active theme when the gutter is clicked to dismiss Settings while a hover-preview
snapback fade is still in flight.

METHODOLOGY (do not weaken any of these three without updating this docstring):

1. GROUND TRUTH IS NEVER AN INTERNAL FLAG. Two independent checks per trial:
   - STYLESHEET-STRING CHECK: read the LIVE mw.styleSheet() after the trial settles
     and diff it, byte-for-byte, against get_base_stylesheet(expected_active_theme)
     computed fresh from the theme name. This catches "wrong/stale sheet applied."
   - PIXEL CHECK: grab the actual composited MainWindow and sample a real pixel,
     compare against the expected theme's known flat RGB. This catches "correct
     sheet applied but didn't actually render" (a repaint/compositing miss).
   These are reported SEPARATELY, never collapsed into one verdict. If they
   disagree with each other or with what the internal state believes, that
   disagreement is itself the finding.

2. MECHANISM TRACING IS OBSERVATIONAL, NOT INFERRED. A second `finished` slot is
   attached to the real `_fade_anim` (Qt supports multiple slots per signal; this
   does not alter the connection the app itself relies on) to observe whether the
   snapback fade's own completion signal fired. `_apply_stylesheets` is wrapped
   (call-through, not replaced) to count real invocations per trial. Two
   `_apply_stylesheets` calls in one trial means both the synchronous fade-start
   path AND snap_theme_forward's `_fade_overlay.isVisible()` fallback ran; one
   call means the fallback did not fire.

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

Runs ONE batch (all delay x swatch-count x dwell-time combinations, one trial
each) and exits. Does NOT loop — per Pryme's instruction, batches are meant to be
spaced 5-10 minutes apart across sessions to sample whatever is causing the
~2x baseline cost drift observed 2026-08-02. Re-invoke manually for the next batch.
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
from PySide6.QtCore import QTimer, QEventLoop, QPoint, Qt
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
        result = _real_apply(theme_name, hover=hover, force_all_panels=force_all_panels)
        apply_call_log.append({
            "t": t0, "theme_name": theme_name if isinstance(theme_name, str) else "<dict/cover>",
            "hover": hover,
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

    def do_trial(delay_ms, swatch_count, dwell_ms):
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

        # Real hover-out path.
        tm._on_theme_unhovered()
        app.processEvents()

        # Controlled delay between hover-out and dismiss.
        pump(delay_ms)

        # Real dismiss path: hide_all_panels() -> _close_settings_flow(), same call
        # chain _on_drag_area_pressed uses (that method's own book-count/mouse-event
        # wrapper is not under test here).
        mw.panel_manager.hide_all_panels()
        app.processEvents()

        # Let the panel slide-out animation and any pending fade/fallback fully
        # settle before sampling ground truth. 700ms covers the 200/375/750ms fade
        # variants plus the ~300ms slide with margin.
        pump(700)
        app.processEvents()

        post_dismiss_apply_count = len(apply_call_log)
        fade_finished_during_trial = len(fade_finished_log)

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
            "delay_ms": delay_ms,
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
        }

    # ---- Sweep definition (per task spec) ----
    delay_buckets_ms = [0, 50, 100, 150, 180, 250]  # 250 = control, after 200ms settle
    swatch_counts = [1, 2, 4]
    dwell_buckets_ms = [40, 120]  # below and above the 80ms debounce

    results = []
    trial_num = 0
    total_trials = len(delay_buckets_ms) * len(swatch_counts) * len(dwell_buckets_ms)
    print(f"Running ONE batch: {total_trials} trials "
          f"({len(delay_buckets_ms)} delays x {len(swatch_counts)} swatch-counts x "
          f"{len(dwell_buckets_ms)} dwell buckets). Live, on-screen. No auto-repeat.")

    for delay_ms, swatch_count, dwell_ms in itertools.product(
            delay_buckets_ms, swatch_counts, dwell_buckets_ms):
        trial_num += 1
        r = do_trial(delay_ms, swatch_count, dwell_ms)
        r["trial_num"] = trial_num
        r["batch_timestamp"] = datetime.now().isoformat()
        results.append(r)
        print(
            f"[{trial_num:3d}/{total_trials}] delay={delay_ms:4d}ms swatches={swatch_count} "
            f"dwell={dwell_ms:3d}ms  stylesheet={'OK' if r['stylesheet_ok'] else 'FAIL'}  "
            f"pixel={'OK' if r['pixel_ok'] else 'FAIL'}  "
            f"agree={r['checks_agree']}  mechanism={r['mechanism']}  "
            f"actual_rgb={r['actual_rgb']} expected_rgb={r['expected_rgb']}"
        )

    # ---- Write results, append (never overwrite) so multi-session batches accumulate ----
    out_path = os.path.join(os.path.dirname(__file__), "..", "review",
                             "snapback_dismiss_harness_results.csv")
    file_exists = os.path.exists(out_path)
    fieldnames = ["batch_timestamp", "trial_num", "delay_ms", "swatch_count", "dwell_ms",
                  "stylesheet_ok", "pixel_ok", "checks_agree", "applies_this_trial",
                  "fade_finished_count", "mechanism", "actual_rgb", "expected_rgb",
                  "internal_active_theme", "internal_fade_overlay_visible"]
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

    print("\n-- Fail rate by delay bucket --")
    for delay_ms in delay_buckets_ms:
        bucket = [r for r in results if r["delay_ms"] == delay_ms]
        bfails = [r for r in bucket if not r["stylesheet_ok"] or not r["pixel_ok"]]
        print(f"  delay={delay_ms:4d}ms: {len(bfails)}/{len(bucket)} failed")

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

    print("\n-- On FAILED trials, which mechanism(s) ran? --")
    for r in fails:
        print(f"  trial {r['trial_num']} (delay={r['delay_ms']}ms swatches={r['swatch_count']} "
              f"dwell={r['dwell_ms']}ms): mechanism={r['mechanism']} "
              f"fade_finished_count={r['fade_finished_count']}")
    if not fails:
        print("  (no failures this batch)")

    print(f"\nResults appended to {out_path}")
    print("Batch complete. Re-invoke manually for the next batch — no auto-loop.")

    mw.close()


if __name__ == "__main__":
    main()
