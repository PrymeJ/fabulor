# Investigation: gutter-dismiss-during-snapback double-fire, and its test harness

**Date:** 2026-08-02  **Branch:** `investigate/restyle-cost-depth-and-narrowing`  **Status:**
Root cause found and precisely traced. Automated harness built, one bug in the harness itself
found and fixed, batch 1 run clean (0/36 failures). No fix implemented — investigation only, per
branch instruction. Follow-on to `review/Investigation_260802_restyle_cost_depth_and_narrowing.md`.

---

## Background: what this supersedes

The prior investigation's live testing of the (disproven, reverted) base-sheet-only narrowing patch
surfaced a report of a "double-fire-before-settle" symptom during gutter-dismiss-while-hovering.
Investigating it required first confirming the experimental patch was fully reverted (`git diff`
empty, confirmed) — the patch itself bypassed `_on_theme_changed` entirely and had zero re-entrancy
protection of its own, so testing against it would have produced a false lead. It did, once: an
early back-to-back-`APPLY` grep flagged 3 instances, all of which turned out on closer inspection to
be unrelated interactions 44+ seconds apart with a normal `GUARD-MASK-TRACE EARLY-RETURN` between
them — corrected before being reported as a finding.

## Root cause, traced precisely (not inferred from names)

On **stock code** (patch reverted), `_on_theme_changed`'s own re-entrancy guards work correctly.
Live DEBUG trace confirmed: every repeat call while a fade is in flight and hover can't interrupt
(`elif _fade_running and not _hover_may_interrupt:`) is correctly stashed into `_pending_fade_call`
and drained exactly once, at the right time.

The real bug is narrower and lives in `snap_theme_forward()`'s **fallback branch**
(`theme_manager.py`, gated on `self._fade_overlay.isVisible()`). That flag is cleared in exactly one
place: `_on_fade_finished`, the slot connected to `_fade_anim.finished`
(`theme_manager.py:243`). `QPropertyAnimation.stop()` does **not** emit `finished` — confirmed
empirically this session, and already documented in CLAUDE.md from three earlier incidents against
`_fade_anim` itself. So any code path that calls `.stop()` on the fade (which
`_close_settings_flow`'s gutter-dismiss path does, via `_on_theme_unhovered()` →
`snap_theme_forward()`) can leave `_fade_overlay.isVisible()` still `True` after the stop, because
the only clearing site never ran.

Consequence: `snap_theme_forward`'s fallback sees a visible overlay it believes still needs
resolving and issues a **second**, genuinely redundant `_apply_stylesheets` call — on top of the one
the synchronous snapback path already made. Confirmed via a timestamp-windowed cross-reference of
`SNAPBACK_FADE_START` / `APPLY` / `FADE_FINISHED` log lines in a real session: **10 of 12** gutter-dismiss
occurrences showed this exact double-apply pattern.

**Severity, precisely scoped:** this is a **cost-only bug, not a wrong-final-state bug**. The
fallback always applies the same theme the synchronous path already applied — it is redundant work
(one extra ~500ms-class `_apply_stylesheets` call), not incorrect output. No other trigger path
reaches `snap_theme_forward`'s fallback branch outside the gutter-dismiss-while-hovering sequence.

This finding was reported live in chat when found; this document is its first durable write-up.

---

## The independently-verified test harness

Built per a detailed task spec requiring: ground truth from live pixel + stylesheet checks only
(never internal flags), mechanism tracing that's observational (not inferred from method names),
the real signal path throughout (`_on_theme_changed` never bypassed), a delay/swatch-count/dwell-time
sweep, live on-screen execution, and a hard stop after one batch.

`tools/snapback_dismiss_harness.py`:

- **Ground truth, two independent checks per trial, never collapsed into one verdict:**
  - Stylesheet-string check: live `mw.styleSheet()` diffed byte-for-byte against a freshly computed
    `get_base_stylesheet(ACTIVE_THEME)`.
  - Pixel check: `mw.grab()` sampled at a real screen coordinate, compared against the active
    theme's known flat `bg_main` RGB.
- **Mechanism tracing:** a second `finished` slot attached to the real `_fade_anim` (Qt supports
  multiple slots per signal; doesn't touch the app's own connection), plus a call-through wrapper
  around `_apply_stylesheets` counting real invocations. 0 applies = `NEITHER`; 1 = `ONE_APPLY`; 2+ =
  `BOTH` (the double-fire signature).
- **Real signal path:** hover via the real `_on_theme_hovered` + the real 80ms debounce `QTimer`
  (via `pump()`, a real `QEventLoop` spin — never `time.sleep()`, which would starve the timers this
  test depends on); dismissal via the real `hide_all_panels()` → `_close_settings_flow()` chain.
- **Sweep:** 6 delay buckets (0/50/100/150/180/250ms) × 3 swatch-counts (1/2/4) × 2 dwell buckets
  (40ms — below the 80ms hover debounce, 120ms — above it) = 36 trials, one batch, no auto-loop.
  The 40ms dwell bucket is a deliberate negative control: below the debounce threshold, no hover in
  the sequence survives long enough to fire a real preview, so `_on_theme_unhovered()` correctly
  finds nothing to revert and `mechanism=NEITHER` — proving the harness can detect "nothing happened"
  rather than just reporting `NEITHER` as a checking-logic bug.

### A harness bug, found before results were trustworthy

The first execution of the full 36-trial sweep returned **100% pixel-check failures**, with the
exact same `actual_rgb=(75, 55, 83)` on every single trial regardless of delay, swatch-count, dwell,
or mechanism. That constancy — identical failure across an entire parameter sweep, including trials
where the mechanism differed — was itself the tell that this was a harness defect, not a real,
universal app bug: a genuine race would be expected to show *some* variance across 36 different
timing conditions, not a perfectly uniform result.

Traced live (not guessed): the original sample point, `(15, 15)`, was checked against a 40-point grid
covering the whole 300×564 window (title bar, content container, all four corners) for both
`Alzabo` and `Blindsight`. **`(15, 15)` was the only point in the entire grid that didn't match its
theme's expected `bg_main`** — every other sampled coordinate, including `(2, 2)` and `(15, 60)`
immediately adjacent to it, matched exactly. `(15, 15)` sits inside `TitleBar`'s 32px-tall region,
which paints `bg_deep` via its own separate stylesheet (`get_title_bar_stylesheet`,
`themes.py:3198`) — not `bg_main` — and the actually-observed `(75, 55, 83)` doesn't match either
`Alzabo`'s `bg_deep` (`43, 8, 83`) or a blend with anything obvious, consistent with the sample
landing on a title-bar child glyph rather than the bar's own flat background.

Fixed by moving the sample to `(15, 400)`, re-verified clean against both themes with a live pixel
read before re-running the sweep.

### Batch 1 results (corrected harness): 0/36 failures

Both ground-truth checks passed on every trial, across the full sweep — every delay bucket,
every swatch-count, both dwell buckets. Zero disagreements between the stylesheet and pixel checks.

**Mechanism observed: `NEITHER` (dwell=40ms, 18/18 trials) or `ONE_APPLY` (dwell=120ms, 18/18
trials). `BOTH` — the double-fire signature root-caused above — did not occur even once in this
sweep.** This does not contradict the root-cause finding; it means this batch's specific
delay/swatch/dwell combinations didn't happen to hit the precondition that makes
`snap_theme_forward`'s fallback see a stale `isVisible()` flag. The real trigger condition (a
`.stop()` call landing while `_fade_overlay` is genuinely still shown, ahead of the drain) may need
a different delay window or a different point in the fade's own lifecycle than this sweep covered —
that is an open question for the next batch, not a resolved one.

### Data provenance note — the results CSV

`review/snapback_dismiss_harness_results.csv` is append-only by design (so multi-session batches
accumulate). Its **first 36 rows are from the pre-fix harness run** and show the uniform false
failure described above (`pixel_ok=False`, `actual_rgb=(75, 55, 83)` on every row) — they are a
record of the harness bug, not real trial failures, and must not be read as evidence of an app
defect. Rows from `2026-08-02T22:05:07` onward are the corrected, trustworthy batch.

---

## What this investigation is NOT

Not a fix for the `snap_theme_forward` fallback double-apply. Not a claim that the double-apply
bug doesn't exist — it's precisely traced to source and reproduced 10/12 times in a real session log
before this harness existed; this batch simply didn't hit it under its specific sweep parameters.
Not a complete sweep — batches are intentionally spaced across sessions to sample timing-sensitive
behavior broadly; this is one of several planned.

## Next step

A second batch, per standing instruction: **hold for explicit signal before running it.** Consider
narrowing the sweep toward conditions closer to the fallback's actual trigger window (e.g. delays
timed against the fade's own duration constants rather than fixed round numbers) since batch 1's
fixed buckets didn't reproduce `BOTH` at all.
