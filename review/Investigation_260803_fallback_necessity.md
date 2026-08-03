# Investigation: is `snap_theme_forward`'s fallback still necessary post-backstop-timer?

**Date:** 2026-08-03  **Branch:** `investigate/restyle-cost-depth-and-narrowing`  **Status:**
Complete. Temporary fallback-disable patch fully reverted (`git diff` confirmed empty) before this
document was written. **Finding: the fallback is still necessary, and reachable at high frequency
under realistic timing — this is NOT a rare/low-priority race.**

---

## Background

`snap_theme_forward`'s fallback branch (`theme_manager.py`, gated on
`hasattr(self, '_fade_overlay') and self._fade_overlay.isVisible()`) historically covered two
distinct mechanisms:
1. The jitter-guard dwell-suppression bug — fixed 2026-08-03 by the periodic backstop timer
   (`review/Design_260803_swatch_leave_jitter_backstop.md`, `1a82c11`).
2. A genuinely-started-then-interrupted snapback fade — root-caused earlier but never fixed
   (`.stop()` doesn't emit `finished`, so `_fade_overlay.isVisible()` is stale by construction).

This investigation isolates whether mechanism 2 alone still makes the fallback necessary, and at
what frequency, now that mechanism 1 is closed.

## Method

Temporarily short-circuited only the fallback branch (commented out its body, logged what it would
have done) — the backstop timer, jitter guard, and normal snapback fade path were left completely
untouched. `tools/snapback_dismiss_harness.py` was rebuilt around a corrected understanding of
where a controllable delay can actually exist in the real call sequence (see "A structural
correction" below), then swept across delay buckets concentrated inside and around the 200ms
snapback fade window, with ground truth from two independent checks per trial (live stylesheet
string vs. `get_base_stylesheet(ACTIVE_THEME)`, and a real composited pixel sample) — never from
internal flags.

### A structural correction to the sweep design, made before running anything meaningful

The original task described inserting a delay between `_on_theme_unhovered()` and
`hide_all_panels()` inside a single dismiss sequence. That placement cannot work: `_close_settings_flow`
(`panels.py:1379-1383`) calls `_on_theme_unhovered()` and `snap_theme_forward()` back-to-back,
synchronously, with zero code between them — there is no gap there to widen, which is exactly what
killed the delay axis in the earlier `double_fire_reentrancy` investigation's batches 1-2.

The real, reachable scenario is different: a genuine leave-triggered hover-out (via
`_on_themes_tab_left` → `_on_theme_unhovered()`) starts the real 200ms snapback fade at one point in
time, and the user's dismiss **click** arrives independently, later. The delay that actually controls
whether the fade is mid-flight at dismiss time is the gap **between that genuine hover-out and the
later dismiss** — a real gap a human's separately-timed leave-then-click gesture naturally has. The
harness places its swept delay there: `tm._on_theme_unhovered()` (simulating the leave) → `pump(delay_ms)`
→ `mw.panel_manager.hide_all_panels()` (the dismiss).

### A second, more consequential correction — the first full run was invalid

The first full 144-trial run reported 0/144 mismatches. Before trusting that, the mechanism trace
(`_apply_stylesheets` call count plus a direct `themes_tab_active` inputs trace added for this
investigation) was checked, and it showed every single trial hitting `snap_theme_forward`'s
**stash-drain** path (`[SNAP-DRAIN-TRACE] ... DRAINING pending_fade_call`) — the already-understood,
working-as-designed mechanism from `review/Investigation_260802_double_fire_reentrancy.md`, not
mechanism 2 under test here.

Root cause: the harness waited a fixed `pump(500)` for the hover-preview fade to settle before
issuing hover-out, based on the CODE DEFAULT assumption that the preview fade is
`get_theme_fade_duration() * 0.5` = 375ms (using the 750ms code default). Checked directly — this
machine's live, PERSISTED `QSettings` value for `theme_fade_duration` is **1500ms**, not 750ms,
making the real preview fade **750ms**, not 375ms. The fixed 500ms wait therefore left the preview
fade genuinely still running every single time; the subsequent hover-out call collided with that
still-in-flight PREVIEW fade (got stashed via the ordinary `_fade_running` guard) instead of
starting a fresh SNAPBACK fade against a settled preview — a completely different, already-solved
race, not the one this task investigates. Verified directly: `fade_finished_count=0` across all 144
trials in that run — the fade's own `finished` signal never fired naturally even once, confirming
it never ran to natural completion at all in that run.

Fixed by reading `tm.config.get_theme_fade_duration()` live and polling for actual settle
(`fade_anim_state == "Stopped"`) rather than guessing a fixed wait. The corrected harness's own
preview-settle step confirmed clean (no `!!! preview fade not settled` warnings) before the real
sweep was trusted.

## Results — corrected sweep, 144 trials, 3 themes × 8 delay buckets × 6 repeats

| delay_ms | trials | mismatches | rate | fade genuinely running before dismiss (n) |
|---|---|---|---|---|
| 0 | 18 | 18 | **100.0%** | 0 |
| 20 | 18 | 18 | **100.0%** | 0 |
| 50 | 18 | 18 | **100.0%** | 0 |
| 80 | 18 | 18 | **100.0%** | 0 |
| 110 | 18 | 14 | 77.8% | 4 |
| 140 | 18 | 5 | 27.8% | 13 |
| 170 | 18 | 5 | 27.8% | 13 |
| 250 | 18 | 0 | 0.0% | 18 |

**Total: 96/144 mismatches (66.7%).** Every one of the 96 mismatches is a `stylesheet_ok=False,
pixel_ok=True` disagreement between the two independent ground-truth checks — never the reverse,
never both failing. This is a real, checked fact, confirmed by diffing the live stylesheet string
directly rather than trusting the summary flags: a representative mismatch showed
`mw.styleSheet()` containing `background: #141414` (the hover theme `Blindsight`'s `bg_main`) where
`#200425` (the active theme `Alzabo`'s `bg_main`) was expected, and `_active_display_theme_internal`
itself reading `'Blindsight'` — the app's own belief about its active theme was wrong, not merely a
transient paint lag.

### Mechanism attribution — traced, not assumed

Every mismatch's `_apply_stylesheets` caller (captured via `traceback.extract_stack()`, not
inferred) is `_do_fade_with_slider_animation:1382`. Tracing why: at short delays, the SNAPBACK
fade's own `_on_theme_changed` call lands at a moment when `themes_tab_active` evaluates `False`
(the Settings/Themes-tab-visible precondition for the overlay-fade branch), so it falls through to
the `elif fade_ms > 0:` branch — `_do_fade_with_slider_animation` — instead of the themes-tab
overlay branch. That method DOES call `self._apply_stylesheets(theme_name, hover=hover)`
synchronously (line 1382) and DOES start a real `_fade_anim`, so the theme should be applied
correctly on that path in isolation — but with the fallback disabled, nothing corrects the state
if this fade is itself interrupted or the timing around it leaves `_active_display_theme_internal`
pointing at the wrong theme by the time ground truth is sampled. `fade_finished_count=0` at every
failing delay bucket (0-80ms) confirms the fade's own `finished` signal never fires naturally in
these trials either — consistent with mechanism 2's core description (a fade that starts, but
whose natural completion is never reached before something else needs the corrected state).

This is a different specific code path (`_do_fade_with_slider_animation`) than the investigation's
original framing anticipated (which expected the themes-tab-overlay branch, per
`_on_theme_unhovered`'s own `_SNAPBACK_FADE_MS=200` call under `themes_tab_active=True`), but it is
still squarely mechanism 2 as scoped: a real fade that starts, is not the stash-drain path, and is
not naturally completed before the dismiss's ground truth would need it to be.

## Direct recommendation

**The fallback fix is NOT low-priority.** At 0-80ms between a genuine hover-out and the dismiss
click — well within normal human timing for "leave a swatch, then immediately click to close" —
the failure rate is 100% across three different themes. The failure is a genuine internal
state corruption (`_active_display_theme_internal` stuck on the wrong theme), not just a cosmetic
pixel lag, and is fully consistent with, and now precisely explains, the "fallback fires and
correctly recovers" behavior documented as load-bearing in this exact code region. Disabling or
removing the fallback without first fixing mechanism 2 by some other means would very likely
surface as a live, frequently-reproducible "wrong theme after dismissing Settings while a preview
was recently active" bug.

## What this investigation is NOT

Not a fix. The fallback's own mechanism (checking `_fade_overlay.isVisible()`, which is stale by
construction after `.stop()`) is left exactly as-is; this investigation only establishes that it is
currently load-bearing and should not be removed or deprioritized. A future fix should specifically
address why `_do_fade_with_slider_animation`'s path can leave the theme stuck, not just special-case
the delay buckets this sweep happened to test.
