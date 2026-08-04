# Design: corrected snapback timing — Esc/gutter-dismiss blocks on the revert visibly settling

**Date:** 2026-08-04  **Branch:** `investigate/restyle-cost-depth-and-narrowing`  **Status:**
Esc/gutter-dismiss implemented and verified same day. Settings-internal tab-switch investigated,
confirmed structurally different, deliberately deferred as a separate follow-up per Pryme's
explicit call.

## Context

Confirmed live: hover a swatch, dismiss Settings (Esc or gutter-click) WITHOUT the hover ever
naturally ending first. The hover-styled chrome (main window, base stylesheet) could remain showing
the hovered theme after Settings was gone — correct that chrome needs live hover styling while a
preview is active, wrong that nothing forced the revert to visibly complete before the dismiss
proceeded.

## Required-first-step trace (before any code changed)

**1. Did a hover-out already cancel an in-flight preview fade, or wait for it?** Traced
`_on_theme_changed`'s `_hover_may_interrupt` predicate directly: `bool(hover or _is_selection)` —
a snapback (`_on_theme_unhovered`'s call) is `hover=False` and not a selection, so it evaluated
`False`. Combined with `elif _fade_running and not _hover_may_interrupt:` → **a snapback arriving
while the original preview's own fade was still running got STASHED behind it**, resumed only when
that fade's `finished` fires (`_on_fade_finished`). With a user-configured preview-fade duration up
to 1500ms, this is exactly the "waits for the wrong thing" bug the spec described. Item 1 of the
spec was **false** before this fix.

**2. Was `_close_settings_flow`'s call ordering itself the problem?** No — confirmed via a prior
same-day investigation that gutter-click and Esc both dispatch to the identical
`_close_settings_flow`, which calls `_on_theme_unhovered()`/`snap_theme_forward()` as the very first
thing, before any animation setup. `snap_theme_forward()` is independently documented (and
battle-tested against exactly this race by two 2026-07-20/21 incidents) to complete synchronously —
`fade_ms=0` forces an instant `_apply_stylesheets` with no animation left running. The ordering in
code was already correct; the gap was entirely in trace 1 above (a stashed snapback doesn't apply at
all until its blocking fade finishes, regardless of how correctly the calling code is ordered).

**3. Backstop-timer double-fire risk (mandatory check).** `_swatch_leave_backstop_timer` is armed/
disarmed only in `_mark_theme_applied` (theme_manager.py), the sole writer of `_is_hover_active`, on
its False↔True transitions. Given trace 1's finding, a real window existed BEFORE this fix: a
stashed snapback leaves `_is_hover_active` unchanged (still `True`) until the original fade's
`finished` eventually drains it — during that window the backstop timer stays armed and could tick,
find the cursor outside `swatch_box`, and call `_on_theme_unhovered()` a SECOND time. Traced the
consequence: a second call would also stash (identical arguments), so the practical effect was
benign (last-write-wins onto an identical stash), not a visible bug — but it was a real, confirmed
race, not an assumed-safe one. **Fixing trace 1 closes this window as a side effect**: the snapback
now interrupts and calls `_apply_stylesheets`/`_mark_theme_applied` SYNCHRONOUSLY, in the same call
stack as `_on_theme_unhovered()`, before any fade duration elapses — confirmed by reading the
overlay-fade branch directly (`_apply_stylesheets`/`_mark_theme_applied` run at lines ~1478-1479,
before `_fade_anim.start()` at 1480). `_is_hover_active` flips to `False` and the backstop timer
stops before `_on_theme_unhovered()` even returns, so there is no window left for it to tick in
between "snapback issued" and "state settled."

## The fix

**Item 1 — snapback interrupts an in-flight preview fade.** Added `_snapback_in_progress`
(theme_manager.py), mirroring `_selection_in_progress`'s existing pattern exactly (same try/finally
shape, same "mark only for the duration of this one call" scope). `_on_theme_unhovered()` sets it
around its own `_on_theme_changed` call. `_hover_may_interrupt` widened from
`bool(hover or _is_selection)` to `bool(hover or _is_selection or _is_snapback)`. An ordinary
non-hover call (rotation/idle-timer) is NOT marked and still stashes exactly as before — this does
not widen interruption to every `hover=False` call, only to the one that represents a genuine hover
ending.

**Item 5 — Esc/gutter-dismiss blocks on the snapback visibly settling, not just the call returning.**
Added `ThemeManager.call_when_theme_settled(callback)`, mirroring `PanelManager.
call_when_panels_settled`'s shape exactly: predicate-driven (re-checks `_fade_in_flight` every 16ms
tick via `_theme_settled_watch_timer`), never restarts a running timer (absolute deadline, not
retriggerable), fires synchronously and immediately when nothing is in flight. Deliberately NOT a
bare `_fade_anim.finished` subscription — this codebase's own documented history
(`QPropertyAnimation.stop()` does not emit `finished`) means a signal-based resume would be silently
dropped exactly when a newer interrupting call stops the fade being waited on.

`PanelManager._close_settings_flow` now checks `_fade_in_flight` immediately after calling
`_on_theme_unhovered()`/`snap_theme_forward()`: if a fade was genuinely started (a real hover-out),
the rest of the close (previously the method's entire remaining body) is deferred via
`call_when_theme_settled` to `_finish_close_settings_flow_with_gap`; if nothing was hovered, it
proceeds immediately, unchanged, with truly zero added delay — the check happens before
`call_when_theme_settled`'s own immediate-vs-deferred branch, so the ordinary case (the overwhelming
majority of dismisses) never even constructs a "zero-delay wait."

**Item 4/7 — small settle gap.** `_SNAPBACK_SETTLE_GAP_MS = 150` (panels.py), a `QTimer.singleShot`
between the snapback settling and the panel actually starting its slide — paid ONLY on the path where
a genuine snapback ran, per Pryme's own framing ("open to ~100-200ms," tune by feel, not fixed by
measurement).

**Re-entrancy guard, added while implementing (not in the original spec, found necessary during
implementation):** `_settings_close_pending`. `active_full_panel()` still reports "settings" as open
throughout the new settle-wait window (the slide animation genuinely hasn't started yet, so
`_is_closing("settings")` is correctly `False`) — a spammed Esc/gutter-click during that window WILL
re-enter `_close_settings_flow` without a guard (verification item 11). The guard is a plain no-op on
re-entry, not a queue, and is cleared unconditionally in `_close_settings_flow_after_settle_gap` so it
can never strand `True` and permanently block future dismisses.

## Item 3/6 — Settings-internal tab switch: investigated, deliberately deferred

Confirmed via exhaustive grep: `main_window.tabs.currentChanged` (`panels.py`) is the ONLY connection
to Settings' own tab-change signal anywhere in the codebase, and it only refreshes the transport-bar
blur overlay — no revert call exists on this path at all. This is case (a) from the original
investigation task, not (b) or (c): tab-switch doesn't bypass `_close_settings_flow` due to a timing
issue, it was never wired to anything equivalent in the first place, because switching tabs never
closes Settings.

**Genuinely blocking a tab switch is structurally different from blocking a dismiss.** Qt's
`QTabWidget.currentChanged` fires AFTER the tab has already switched — there is no
`currentAboutToChange` signal to veto from. Implementing the spec literally ("block the tab-change
until the snapback completes") requires a new mechanism: an event filter on the tab bar that
intercepts the mouse click before Qt processes it, consumes it while a hover is active, runs the
snapback, and only calls `setCurrentIndex` once settled. This is meaningfully more invasive than the
dismiss fix (a new interception point on every tab-bar click, vs. one already-existing method's own
internal sequencing) and was NOT implemented this session.

**Pryme's explicit call, verbatim in effect:** confirm Esc/gutter's fix on its own, verified clean,
before touching tab-switch — treat the tab-bar-interception mechanism as its own separate follow-up,
so a regression in one is never conflated with a regression in the other. Recorded in TODO.md.

## Verification

- 12 new synthetic tests, three files:
  - `tests/test_hover_interrupts_snapback.py` (+2): a snapback (`_snapback_in_progress=True`)
    interrupts a running preview fade; the marker defaulting to `False` does not accidentally let
    every non-hover call interrupt.
  - `tests/test_theme_settle_resume.py` (+6): `call_when_theme_settled` mirrors
    `call_when_panels_settled`'s full test matrix (fires synchronously / defers and arms / doesn't
    re-arm a running timer / re-arms while still fading / drains once settled / drains multiple
    waiters in order).
  - `tests/test_close_settings_flow_blocks_on_snapback.py` (+4): ordinary dismiss proceeds
    immediately with zero added delay; a genuine hover-out defers via `call_when_theme_settled` and
    only proceeds once that callback fires; a second dismiss while the first is pending is a
    provable no-op (item 11); the guard clears so a later, independent dismiss works normally.
- Suite: 465/465 (453 baseline + 12 new), matching baseline throughout each incremental step.
- Live smoke test: clean startup, no exceptions, ordinary playback/UI sync unaffected.
- Full live verification of the "hover with a long configured fade duration, dismiss mid-preview,
  confirm total dismiss-to-slide time is ~200ms + settle gap regardless of the preview's own
  duration" scenario (task item 8) is Pryme's to confirm live — not something this session's tools
  can observe (requires watching real animation timing, not log content).
