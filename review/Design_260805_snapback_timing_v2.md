# Design v2: corrected snapback timing for Esc/gutter-dismiss — three corrections in one day

**Date:** 2026-08-05  **Branch:** `investigate/restyle-cost-depth-and-narrowing`  **Status:**
Esc/gutter-dismiss implemented and live-verified. The two remaining `get_displayed_theme()`-migration
deletion steps (`check_cursor_on_settle()`, `clear_stale_hover_state()`) re-verified against current
code and landed the same day. Settings-internal tab-switch remains open — confirmed BROKEN via two
distinct triggers (hover, and "Change now") — deliberately deferred as a structurally different
follow-up (see TODO.md).

## Context

This supersedes `review/Design_260804_snapback_timing.md`, whose implementation (`2abeab5`/
`9650a1f`) was reverted the same session (`0396f5b`) on Pryme's explicit instruction: the fix
appeared to freeze the UI for ~700-800ms before jumping to the correct colors, with no visible
fade — the opposite of what was requested. Before re-attempting, Pryme required a live latency
investigation first (see `review/Investigation_260804_animation_latency.md`): interrupt-clear is
genuinely instant (0.0ms), but animation-start latency is a real, unavoidable ~680-810ms
(`_apply_stylesheets` running synchronously before `_fade_anim.start()`), constant regardless of
configured duration. That investigation is what made a *correct* re-attempt possible.

Three corrections landed the same day, each found via a live report from Pryme, each traced to its
exact mechanism before being fixed — no reactive patching.

## Correction 1: `_close_settings_flow` was killing the very animation it needed to wait for

**Root cause, confirmed by reading the reverted diff, not re-guessed:** `_close_settings_flow`
called `_on_theme_unhovered()` then `snap_theme_forward()` synchronously, back-to-back — exactly
the shape of the code it was replacing. `snap_theme_forward()` immediately `.stop()`s whatever fade
`_on_theme_unhovered()` just started and force-applies it INSTANTLY (`fade_ms=0`), so by the time
`call_when_theme_settled` checked `_fade_in_flight`, it was already `False` and the wait branch was
never entered. The visible "freeze" was `_apply_stylesheets`'s own ~700-810ms synchronous cost
running with no animation on screen at all — not, as first suspected, the wait mechanism itself
blocking Qt's event loop (`call_when_theme_settled` is a `QTimer`-based predicate re-check, same
shape as `PanelManager.call_when_panels_settled`, and never stalls painting).

**Correctness check before implementing:** would simply deleting the `snap_theme_forward()` call
reopen the bug that call was originally added to prevent? Traced `snap_theme_forward()`'s three
jobs at this call site: (1) force-clear a stuck `_fade_in_flight` if a fade genuinely never
settles — a real termination guarantee; (2) drain `_pending_fade_call` — already covered by
`_on_fade_finished`'s own natural-completion drain, redundant here; (3) reach the deferred-restyle
batch instantly rather than waiting for the fade to finish — also redundant, since letting the fade
complete naturally reaches the same batch via `_on_fade_finished` → `_run_deferred_restyle`.
Confirmed via `_run_deferred_restyle`'s own docstring that it correctly defers itself while
`_fade_in_flight` is `True` and is re-invoked by `_on_fade_finished` — no gap. Only job (1) needed
preserving.

**The fix:** dropped the unconditional `snap_theme_forward()` call. `_on_theme_unhovered()` alone
starts the real, animated 200ms snapback fade (confirmed instant-interrupt of any in-flight preview
fade via `_snapback_in_progress`, mirroring `_selection_in_progress`'s existing pattern —
`_hover_may_interrupt` widened to `hover or _is_selection or _is_snapback`). `_close_settings_flow`
waits on `call_when_theme_settled` for that fade to genuinely finish; during the wait, Qt's event
loop runs normally, so the overlay stays visible and the fade visibly plays. Job (1) is preserved as
`call_when_theme_settled`'s own internal **termination-guarantee timeout**:
`_THEME_SETTLE_TIMEOUT_MS = 2000` — roughly double the ~1010ms worst-case measured normal settle
(`~810ms _apply_stylesheets` + `200ms` fade, per the latency investigation), generous enough to
never false-trigger on legitimate slow hardware, short enough that a genuinely stuck fade doesn't
hang a dismiss for long. `snap_theme_forward()` is now reachable ONLY from that timeout path, never
called unconditionally.

A re-entrancy guard (`_settings_close_pending`) was added during implementation, not in the
original spec: `active_full_panel()` still reports "settings" as open throughout the settle-wait
(the slide genuinely hasn't started), so a spammed Esc/gutter-click would re-enter
`_close_settings_flow` without it. Plain no-op on re-entry, cleared unconditionally once the slide
actually starts.

## Correction 2: the settle predicate couldn't tell "my snapback settled" from "an unrelated later hover settled"

**Live-reproduced by Pryme, twice, with real timestamps** ("Camorr... falls to main screen,
corrects" and, after retracting an initial wrong diagnosis of the first report, "The Eyrie hovered,
falls to main screen, corrects after"). The first report was misdiagnosed by me as a
`[SWATCH-LEAVE-SUSPECT]` leaveEvent-misclassification issue — Pryme corrected this directly ("I
press Esc... mouse doesn't leave the swatch"), which redirected the trace to the real mechanism,
found via new `[CLOSE-SETTINGS-TRACE]` logging added at `_close_settings_flow`'s own call sites
rather than continuing to infer from unrelated log lines.

**Root cause:** `call_when_theme_settled`'s predicate was bare `not self._fade_in_flight` — true
whenever *any* fade clears, not specifically the dismiss's own snapback. Sequence that reproduces
it: Esc pressed while hovering theme A → `_on_theme_unhovered()` starts the snapback fade toward the
committed theme → **before that fade settles**, the cursor is still over the still-open Themes tab
and genuinely hovers theme B → B's hover correctly interrupts A's in-flight snapback (per
`_hover_may_interrupt` — a genuine hover always interrupts) and starts its own fade → B's fade
settles on its own schedule → the bare `_fade_in_flight` check reads that as "settled" and closes
the panel showing B for one frame before a later, unrelated correction
(`_on_settings_hidden`'s `clear_stale_hover_state()`) silently fixes it back.

**The fix:** `_theme_genuinely_settled_on_committed()` — `not _fade_in_flight and
_active_display_theme_internal == get_committed_theme() and not _is_hover_active` — used by both
`call_when_theme_settled` and its watch-tick, replacing the bare flag check. A hover on any other
theme (or even the same theme name, since it would still carry `_is_hover_active=True`) now
correctly fails this check and keeps the wait alive.

**Naming confirmation, done explicitly before building on it** (per Pryme's instruction, given this
session's history of naming mix-ups causing exactly this class of bug): traced
`get_committed_theme()`'s implementation directly — it returns `self._current_theme_name`, the
identical field the new predicate reads. Not a different, similarly-named field.

## Correction 3: `get_committed_theme()` never accounted for cover-art theme mode

**Live-reported by Pryme:** cover-art theme modes ("With pool" / "Exclusive") block or mistime
panel dismissal on Esc/gutter.

**Root cause:** `_on_theme_unhovered()` targets `self._cover_theme` — a DICT — whenever
`self._cover_theme_active` is `True`, exactly mirroring `get_displayed_theme()`'s own existing
`_cover_theme_active` check a few lines above `get_committed_theme()`. But `get_committed_theme()`
unconditionally returned `self._current_theme_name` (a plain string), never checking
`_cover_theme_active` at all. So Correction 2's predicate — `_active_display_theme_internal ==
get_committed_theme()` — compared a dict against a string in cover-art mode, which can never be
`True` via its intended path. Confirmed by direct log trace (not inferred): the dismiss only
"worked" by accident, via a completely different, older no-op guard in `_on_theme_changed`
(`_active_display_theme_internal == theme_name and _is_hover_active == hover`) coincidentally
matching first and returning before `_fade_in_flight` was ever touched. Without that accidental
match — e.g. if a hover had dirtied the state first — the dismiss would have silently fallen through
to the 2000ms termination-guarantee timeout instead of closing promptly, masking the bug as
"closes 2 seconds late" rather than surfacing it as broken.

**Pre-implementation safety check, done explicitly before widening the accessor's return type**:
checked all five current call sites of `get_committed_theme()` (`library.py` x2 —
`_resolve_theme_colors`, `_refresh_search_match_state`; `sleep_timer.py`'s
`_apply_preset_ramp_colors`; `speed_controls.py`'s equivalent; `app.py`'s
`_reload_excluded_books`) for whether any assumes a bare string. All five route the return value
straight into `themes._resolve_theme()` before doing anything else with it, and that function
already has an explicit `isinstance(theme_name, dict)` branch — confirmed necessary, since
`get_displayed_theme()` already returns cover-theme dicts whenever a hover happens to be live in
cover-art mode, so this code path was already exercised today for a different caller. None of the
five break.

**The fix:** `get_committed_theme()` now checks `_cover_theme_active`/`_cover_theme` first, exactly
mirroring `get_displayed_theme()`'s own shape — returns the cover-theme dict when active and set,
else falls back to `_current_theme_name`. One-method change, no new state, no call-site changes
needed (all five already handle a dict).

## Verification

**Unit tests, 477/477 (baseline 469 + 8 new):**
- `tests/test_theme_settle_resume.py` (+9 net, replacing/extending the prior 6): predicate-driven
  resume shape (fires immediately / defers / never restarts a running timer / re-arms while
  fading / drains once settled / drains multiple waiters); termination-guarantee timeout (not
  reached too early / forces via `snap_theme_forward()` / re-arms if forcing somehow didn't
  settle); the Correction-2 regression case
  (`test_call_when_theme_settled_waits_through_a_hover_that_interrupts_the_snapback`, modeling the
  exact live sequence step-by-step) plus its same-name edge case; three Correction-3 cases
  (fires immediately when the cover dict is already settled, waits for a genuine fade in cover-art
  mode, and a direct demonstration that the pre-fix dict-vs-string comparison could never have
  matched).
- `tests/test_write_path_confinement.py` (+3): `get_committed_theme()` returns the cover dict when
  cover-art mode is active; falls back to the plain string when `_cover_theme_active` is `True` but
  `_cover_theme` is `None` (mid-transition edge case, named in `get_displayed_theme()`'s own
  equivalent check); the hover-confinement guarantee holds in cover-art mode too (a swatch hover
  never leaks into the answer even when the underlying committed value is a dict).
- `tests/test_close_settings_flow_blocks_on_snapback.py` (unchanged 4, `snap_forward_calls`
  assertions flipped from `== 1` to `== 0` at the two non-timeout-path sites, confirming
  Correction 1 holds).
- `tests/test_hover_interrupts_snapback.py` (+2, reinstated from the reverted attempt unchanged —
  this half of that attempt was correct): a genuine snapback interrupts an in-flight preview fade;
  the marker defaulting `False` doesn't let every non-hover call interrupt.

**Live verification**, `tools/snapback_dismiss_live_verify.py` (new harness, drives the real
`ThemeManager`/`PanelManager` against a live, on-screen `MainWindow`):
- Tests 1-5 (dismiss mid-1500ms-preview): preview cut short instantly, overlay paints ~22-30 real
  frames with genuinely moving opacity (not frozen), panel closes, final theme matches committed —
  run 5 times.
- Test 6 (termination-guarantee fallback, timeout shrunk to 300ms for the test): fires and closes
  rather than hanging — confirmed via a forced-stuck `_fade_in_flight`.
- Test 7 (Correction 2's regression, live): 5 trials per run x 3 runs = 15 total, injecting a
  genuine hover interruption mid-wait each time — 15/15 correctly waited through it and closed only
  on the committed theme.
- Test 8 (Correction 3, live): both "With pool" and "Exclusive" modes, simulated via a synthetic
  cover-theme dict (no real cover image needed) — both close in ~335-340ms, well under the 2000ms
  fallback threshold, confirming genuine settle rather than the timeout accident. Run 3 times.

**One harness bug found and fixed mid-verification, not glossed over:** a second live run showed
Tests 5-7 apparently regressing. Traced to the harness itself, not the fix: `MainWindow()`
construction reads the REAL, `QSettings`-persisted `cover_art_theme_mode` from this machine, which
was genuinely left active from earlier testing — silently making Tests 1-7 (meant to test the
plain-theme path) exercise the cover-art path instead. Fixed by having `reset_to_active()`
explicitly clear `_cover_theme_active`/`_cover_theme` before every reset. This is itself a useful
confirming data point, not just a nuisance: it demonstrates the bug Correction 3 fixes was reachable
via ordinary persisted state, not a contrived scenario.

**A separate false lead, corrected by Pryme directly rather than re-derived:** a live question
about whether the mute icon needed adding to `get_base_stylesheet` (it "usually didn't change color
other than in Razorgirl" during this session's testing) led to tracing `_reload_button_icons` →
confirmed the icon IS already theme-driven correctly (every theme defines a distinct
`slider_vol_fill`, no caching bug, called on every `_apply_stylesheets` pass). The real explanation
for why it was visible every time, given by Pryme directly: the harness's separate `MainWindow`
window accidentally received a stray `m` keypress meant for something else Pryme was typing,
muting it for the rest of the session — not a rare-visibility coincidence as first guessed. No code
change was needed; this is recorded because it's exactly the "report about what Pryme did is data,
not a competing theory" pattern this project's own CLAUDE.md names.

## Steps 5-6: deleting the two superseded mechanisms (same day, follow-up task)

Once the dismiss fix above landed and was verified, the two remaining deletion steps of the
`get_displayed_theme()` migration (`review/Design_260804_hover_state_computed_read_path.md`, steps
5-6) were re-examined — explicitly re-verified against CURRENT code rather than trusting that
design's snapshot, since significant new code (the containment fix, `get_committed_theme()`, the
settle predicate, the cover-art fix) had landed since it was written.

**`check_cursor_on_settle()` — deleted.** Its one job: on Settings-panel-open settle, if the cursor
is already resting on a swatch, synthetically fire `.hovered.emit(...)` to start a preview (working
around Qt not guaranteeing `enterEvent` redelivery under a stationary cursor). Re-confirmed the
native `QPushButton#theme_item:hover` QSS rule (themes.py:3730) is unchanged and fully independent
of this method — Qt applies it purely from cursor-over-widget geometry, no signal involved. Traced
fresh: nothing added since the original design reads or depends on this method firing; it lived
entirely on the hover-START side, while everything built this session (the settle predicate,
`get_committed_theme()`, the cover-art fix) lives on the hover-END/settle side. Deleted the method
and its sole call site (`_on_settings_slide_finished`).

**`clear_stale_hover_state()` — deleted.** Its job: force `_is_hover_active`/
`_active_display_theme_internal` back to the active theme whenever Settings becomes hidden, as a
backstop for the case where a hover completes but the swatch's leaveEvent gets misclassified as a
blur-grab synthetic (the same class of bug `[SWATCH-LEAVE-SUSPECT]` still detects-but-doesn't-correct
today). The task's own instruction was explicit: if this method was providing ANY accidental
backstop coverage for that still-open gap, report it rather than deleting silently. Traced fresh and
found it was not: `_close_settings_flow` is confirmed the sole path to hiding Settings (all three
triggers — Esc, gutter/dismiss-all, right-click — route through it; `is_overlay_open_or_committed()`
blocks every other panel's open flow while Settings is open, so nothing can force it closed via a
different path), and it unconditionally calls `_on_theme_unhovered()` before `_on_settings_hidden`
can ever fire — the settle predicate (`_theme_genuinely_settled_on_committed`) guarantees
`_is_hover_active` is `False` by the time the slide starts, in BOTH the genuine-settle and
2000ms-timeout-fallback paths. So the dismiss path is self-healing regardless of whether
`[SWATCH-LEAVE-SUSPECT]`'s gap fired earlier in the session — the stuck state it would have
corrected is always already fixed by the dismiss's own fresh snapback before this method would run.
Also independently confirmed `get_displayed_theme()` never reads either field this method corrected,
closing the original 7-runtime-call-site read leak this method was built for regardless. Deleted the
method, its call site (`PanelManager._on_settings_hidden`), and its 4 dedicated tests in
`tests/test_get_current_theme_hover_safety.py` (kept the 3 tests covering `get_current_theme()`/
`get_active_theme()`'s own unrelated hover-safety).

Verified one deletion at a time, not both before checking: 477/477 → 477/477 (step 1, pure deletion)
→ 473/473 (step 2, 4 tests removed). Live spot-check after both: the full 8-check dismiss-
verification suite (`tools/snapback_dismiss_live_verify.py`) passes identically to before either
deletion.

## Step 3: tab-switch — confirmed still broken, via two distinct triggers

Investigated live, not implemented, per the task's explicit instruction.

**Trigger 1 — hover a swatch, then switch tabs.** 5/5 live trials (both immediate and paused
switches): never reverts. `_is_hover_active` stays stuck `True` and the main window's chrome stays
on the hovered theme for the full 2-second observation window, every trial. Root cause confirmed via
signal-chain instrumentation (wrapping the real `_on_themes_tab_left`/`_on_theme_unhovered` to log
every call), not inferred from reading alone: **neither method is ever called at all** —
`leave_log=[]` in every trial. Qt does not deliver a `leaveEvent` to `swatch_box` when
`QTabWidget.setCurrentIndex()` hides its containing tab, so the entire mechanism the dismiss fix
improved (the settle predicate, the interrupt marker) is never even entered on this path — there is
nothing for it to help with, because nothing triggers it. New diagnostic tool,
`tools/tab_switch_snapback_check.py`, kept for re-running once the tab-bar-interception fix lands.

**Trigger 2 — click "Change now" (a genuine selection, not a hover), then immediately switch tabs —
raised separately by Pryme after reviewing trigger 1's findings.** Live-tested 5x: this is
structurally DIFFERENT from trigger 1, confirmed rather than assumed identical. `_do_rotate` sets
`_current_theme_name` (so `get_committed_theme()`) synchronously, before `_on_theme_changed` even
runs — so the committed value is correct from the instant of the click, regardless of any later tab
switch. The fade/overlay/committed-theme internal state also all resolve correctly after ~1.5s in
every trial (`_fade_anim` settles to `Stopped`, `_fade_overlay` hides, `get_committed_theme()`
matches the live chrome) — nothing gets stuck, no wrong committed theme survives. The actual defect
is narrower and purely visual: `_fade_overlay` is a child of `main_window`, not of `themes_tab`/
`swatch_box`, confirmed by reading its construction (`QLabel(self.main_window)`) — so a tab switch
never hides it, and the fade keeps animating on top of whatever tab is now showing instead of
finishing where it started. The panel-occlusion mask this overlay uses is also computed once, at
fade-start, from whichever panels are open at that instant — it does not change per-tab within the
same Settings panel, so the overlay's masking stays geometrically consistent through the switch; the
only issue is that it is visible/playing on the wrong tab's content at all. Pryme's stated
preference, verbatim: *"I prefer the fade finishes where it starts."* Not a correctness bug (no
stuck state, no wrong final theme) — a scoping/containment preference for where the fade is visually
permitted to play.

**Both triggers need the same underlying mechanism** (a tab-bar click-interception event filter:
consume the click, run/await the relevant settle, then call `setCurrentIndex` once resolved) since
`QTabWidget.currentChanged` fires AFTER the tab has already switched, with no pre-change signal to
veto from. Neither is implemented — both are recorded in TODO.md as the scope for that future work.

## Remaining scope

Settings-internal tab switch (both triggers above) is unimplemented, structurally different from the
dismiss fix (no Qt pre-change signal to block a `currentChanged` from), and deliberately deferred as
its own follow-up per Pryme's explicit call — see TODO.md.
