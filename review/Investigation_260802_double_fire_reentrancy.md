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

## Batch 2 results: identical shape, 0/36 failures, `BOTH` still never observed

Re-run of the same 36-trial sweep, same corrected harness, no code changes between batches.
Result: **0/36 failures, 0 disagreements**, and `mechanism` again split cleanly into `NEITHER`
(dwell=40ms, 18/18) / `ONE_APPLY` (dwell=120ms, 18/18) across every delay bucket and swatch-count.
`BOTH` did not occur in this batch either — 72 trials total across two batches, zero reproductions.

### This is now a reportable gap, not just an inconclusive first batch

`_SNAPBACK_FADE_MS = 200` (theme_manager.py:58) is the fade duration the hover-revert path uses.
The harness's `delay_ms=0` bucket dismisses immediately after `_on_theme_unhovered()` returns — the
condition that should be *most* likely to catch the 200ms fade still in flight when `.stop()` runs
inside the dismiss chain, which is the fallback's actual precondition
(`_fade_overlay.isVisible()` still `True` at that instant). That this bucket *also* never produced
`BOTH`, across two full runs, means the harness's wall-clock delay model does not reliably line up
with the fade's real internal state at the moment `.stop()` is called — plausible causes include
Qt animation start latency, event-loop scheduling jitter between `pump()`'s `QEventLoop` and the
real animation's own `QTimer`-driven ticks, or the fade genuinely completing faster under this
harness's synthetic drive than the delay buckets assume. None of these has been checked yet; this
is flagged as the specific next question, not resolved here.

The 10/12 real-session reproduction rate stands — it was observed via organic (non-harness-driven)
usage and timestamped log cross-referencing, not invalidated by this sweep's failure to reproduce it.
The gap is in this harness's ability to hit the same precondition on demand, not in whether the bug
is real.

## What this investigation is NOT

Not a fix for the `snap_theme_forward` fallback double-apply. Not a claim that the double-apply
bug doesn't exist — it's precisely traced to source and reproduced 10/12 times in a real session log
before this harness existed; two full sweeps (72 trials) simply didn't hit it under either batch's
timing parameters. Not a complete sweep — batches are intentionally spaced across sessions to sample
timing-sensitive behavior broadly.

## Batch 3 (redesigned): the root cause claimed earlier in this document is WRONG — retracted here

**Retraction, per the standing rule on correcting a claim explicitly rather than letting it stand:**
the root-cause section above says the double-apply comes from `snap_theme_forward`'s
`_fade_overlay.isVisible()` fallback (lines 444-448 of `theme_manager.py`), never cleared because
`.stop()` emits no `finished`. **That mechanism was never observed to fire, in any batch, and is not
what batch 3 found.** The claim was built on a plausible reading of a code comment (line 346's
"the settings-close snap-back starts a real 750ms fade") without tracing the actual call stack that
produces the extra apply — exactly the kind of unchecked inference CLAUDE.md's methodology section
warns against, and it went unnoticed for two full batches because those batches' verdicts (pixel +
stylesheet) were correct regardless of which internal mechanism produced them.

### Redesign and what it changed

Batches 1-2 swept a wall-clock delay between `_on_theme_unhovered()` and `hide_all_panels()`. That
delay cannot matter: `_close_settings_flow` (panels.py:1379) calls `_on_theme_unhovered()` and
`snap_theme_forward()` back-to-back with no event-loop turn between them, regardless of how long the
harness waited beforehand — confirmed by re-reading `snap_theme_forward`'s own comment ("this method
runs immediately after `_on_theme_unhovered()`, in the same call stack with no intervening
event-loop turn"). The delay axis was dropped. In its place, the harness now snapshots
`_fade_anim.state()`, `_fade_overlay.isVisible()`, and `_fade_in_flight` directly at two checkpoints
— immediately after `_on_theme_unhovered()` returns, and immediately after `hide_all_panels()`
returns — plus records each `_apply_stylesheets` call's real caller via `traceback.extract_stack()`,
rather than only counting calls.

### What batch 3 (6 trials, swatch-count × dwell-bucket only) actually found

- **6/6 pass on both ground-truth checks.** Same clean result as batches 1-2.
- **dwell=40ms (3 trials):** no preview ever applied (no-op guard, as expected) → 0 applies, nothing
  to snap back from.
- **dwell=120ms (3 trials, the real exercise):** exactly 1 `_apply_stylesheets` call in all 3, and
  the state snapshots plus the call's own traceback settle the mechanism precisely:
  1. `_on_theme_unhovered()` (called directly by the harness) starts the real 200ms snapback fade —
     confirmed by the snapshot immediately after it: `fade_state=Running, overlay_visible=True`.
  2. `hide_all_panels()` → `_close_settings_flow()` calls `_on_theme_unhovered()` a **second time**
     (the harness's own call chain re-invokes the same method `_close_settings_flow` calls). With a
     fade genuinely `_fade_running`, this second call hits the `elif _fade_running and not
     _hover_may_interrupt:` branch (theme_manager.py:989) and **stashes itself into
     `_pending_fade_call`** — it does not apply anything itself.
  3. `_close_settings_flow` then calls `snap_theme_forward()`, which stops the running animation
     (clearing `_fade_in_flight`, confirmed by the post-checkpoint snapshot: `fade_state=Stopped`),
     finds `_pending_fade_call is not None`, and **drains it** via the stash-drain branch
     (theme_manager.py:402-432) — a full re-call to `_on_theme_changed(..., fade_ms=0, ...)`.
  4. That re-call, with `fade_ms=0`, takes the plain synchronous branch (theme_manager.py:1176-1181)
     and calls `_apply_stylesheets` at **line 1180** — confirmed directly via the wrapped call's own
     recorded caller (`caller=_on_theme_changed:1180`) in all 3 dwell=120ms trials, and independently
     corroborated by exactly 3 `[SNAP-DRAIN-TRACE] snap_theme_forward DRAINING pending_fade_call`
     log lines appearing in the raw session log — matching the 3 trials exactly.

**The `_fade_overlay.isVisible()` fallback branch (line 444) never fired in any observed trial.**
Its own precondition (`isVisible()` still `True` when `snap_theme_forward` checks it) was never
actually tested by this harness, because the stash-drain branch (which runs earlier in
`snap_theme_forward`, at line 402, before the `isVisible()` check at line 444) already produced a
result and the method's flow does not prevent both from firing in principle — but in every observed
trial, the stash was present, so the drain always ran, and no evidence exists here about what the
`isVisible()` fallback does independently of it.

### What this means for the original "root cause"

The **symptom** (a redundant, cost-only second `_apply_stylesheets` call on gutter-dismiss-while-hovering)
is still real and still consistent with the 10/12 organic-session log observation reported earlier.
What was wrong is the **named mechanism**. The actual mechanism, confirmed by direct observation in
this batch: a **second, harness-internal call to `_on_theme_unhovered()`** (from
`_close_settings_flow`'s own call to it, arriving while the first, harness-driven call's fade is
still running) gets correctly stashed, then correctly drained by `snap_theme_forward` — which is
**exactly the intended, working behavior** documented in
`review/Investigation_260720_snap_drain_deferred_gap.md` (the stash-drain mechanism was built and
shipped specifically to fix a prior bug where a stashed call was NOT drained and left a stale theme
showing). In other words: **this harness's own trial structure (`_on_theme_unhovered()` called
directly, then `hide_all_panels()` which calls it again) manufactures the exact stash/drain sequence
that Fabulor's real single-click dismiss path was built to handle correctly** — and it does handle
it correctly, landing on the right final theme every time (confirmed by both ground-truth checks,
6/6).

**Open question, now correctly scoped:** does a REAL user's single gutter click ever produce this
same stash — i.e. does `PanelManager._close_settings_flow`'s own first `_on_theme_unhovered()` call
(not a harness-injected second one) ever land while an independent fade is already running from some
other trigger (e.g. an auto-rotation, or a hover that hadn't yet settled)? That is a materially
different question from what this harness's trial structure tests, and it has not been answered by
any batch so far. The 10/12 organic-log observation may reflect this real single-call case, the
harness's double-call artifact (if the organic session also happened to call
`_on_theme_unhovered()` twice in close succession, e.g. via a rapid re-hover), or something else
entirely — not yet distinguished.

## Next step

Per standing instruction: hold for explicit signal. If a fourth batch is run, it should test the
SINGLE-call case directly (hover once, dismiss once, no harness-injected second
`_on_theme_unhovered()` call) to determine whether the stash/drain sequence — now confirmed to be
the real mechanism, not the `isVisible()` fallback — can arise from ordinary single-click usage, or
only from a double-call pattern this harness's own structure introduced.
