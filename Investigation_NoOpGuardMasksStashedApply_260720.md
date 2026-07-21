# Investigation: the no-op guard can permanently mask a theme that was SELECTED but never actually APPLIED

**Date:** 2026-07-20  **Branch:** `blur-composited-overlay`  **Status:** diagnosis only, no fix applied.

Third distinct theme-staleness mechanism found tonight — NOT the same as the hover-bleed bug fixed
earlier (state-read bypass, hover-unaware blur grab) and NOT the same as the
`snap_theme_forward()`-doesn't-schedule-the-deferred-pass gap fixed just before this. Confirmed via
direct live log trace, reproduced by the user via a genuine active-theme click (not a hover
preview) — `Waste Lands` → `Anomander`. This is more severe than the previous two: it can leave a
theme's stylesheet **never applied at all**, for the rest of the session, with no self-correction.

---

## The trace

1. `23:22:56,896` — user hovers `Anomander` (`_on_theme_changed(hover=True)`, starts a preview
   fade).
2. `23:22:57,307` — user CLICKS `Anomander` (a genuine active-theme selection, `hover=False`) —
   but `fade_in_flight=True` (the hover-preview fade from step 1 is still running). Per
   `_on_theme_changed`'s `_fade_running` guard branch, this call is **stashed** into
   `_pending_fade_call = ('Anomander', save, fade_ms, False, user_initiated)` and returns
   immediately — `_apply_stylesheets` is NOT called for this invocation.
3. **Critically:** `_active_display_theme_internal = theme_name` (`theme_manager.py` — the
   assignment happens unconditionally, right after `_is_hover_active = hover`, BEFORE the
   `_any_animating`/`_fade_running` guard checks that decide whether to stash) — so
   `_active_display_theme_internal` already reads `'Anomander'` from this moment forward, even
   though the actual stylesheet application for `'Anomander'` has not happened yet.
4. From `23:22:57,612` onward: dozens of `_on_theme_changed: EARLY-RETURN no-op guard
   theme_name='Anomander' _active_display_theme_internal='Anomander' ... _apply_stylesheets NEVER
   CALLED this invocation` lines — this is the (separately tracked, still-open) heartbeat bug
   re-firing `_on_theme_changed('Anomander', hover=False)` repeatedly, and EVERY one of these calls
   correctly no-ops per the guard's own logic (`_active_display_theme_internal == theme_name and
   _is_hover_active == hover` — both already true) — but this is now masking a REAL pending
   application, not skipping a genuine duplicate.
5. Some time between `,307` and `23:22:58,922`, `_pending_fade_call` becomes `None` — but **no
   drain path logs anything**: not `snap_theme_forward`'s `[SNAP-DRAIN-TRACE]` (confirmed — grepped
   the whole window, zero hits), not `complete_main_fade`'s `[BLEED-TRACE] ... RESUMING` (confirmed
   — zero `complete_main_fade` calls exist anywhere in this window before the clean `ENTRY` at
   `,922`), and not a fresh `_on_theme_changed theme_name='Anomander'` `[BLEED-TRACE]` line either
   (which a real re-invocation via `_on_fade_finished`'s drain — `theme_manager.py:245-248` — would
   produce, since that log line fires unconditionally at the top of `_on_theme_changed`, before the
   no-op guard).
6. `23:22:58,922` — `complete_main_fade ENTRY` shows `_pending_fade_call=None`,
   `_active_display_theme_internal='Anomander'`, `_fade_in_flight=False` — everything LOOKS
   settled and correct from the state alone.
7. **Confirmed via full-log grep: `_flush_deferred_restyle_now: ENTRY theme='Anomander'` never
   appears anywhere in the entire session's log.** The deferred pass (Stats/Library/Book-Detail's
   own `setStyleSheet`, the `theme_applied` signal driving Tags/Sleep/Speed's per-button colors —
   see the sibling investigation, `Investigation_SnapDrainDeferredGap_260720.md`, for the full list
   of what depends on this) was never scheduled or run for `Anomander`, at any point.

## The mechanism, stated plainly

`_on_theme_changed`'s no-op guard (`theme_manager.py`, near the top of the method) is:

```python
if (getattr(self, "_active_display_theme_internal", None) == theme_name
        and self._is_hover_active == hover):
    ... EARLY-RETURN, _apply_stylesheets NEVER CALLED ...
    return
```

This guard's implicit assumption is: **"if `_active_display_theme_internal` already equals
`theme_name`, then `_apply_stylesheets` must already have been called for it — so calling it again
would be redundant."** That assumption is FALSE in exactly one case: when the call that set
`_active_display_theme_internal` to `theme_name` was itself stashed (via the `_fade_running`
branch) rather than actually applied. The assignment `_active_display_theme_internal = theme_name`
happens BEFORE the stash decision in the method's control flow — so the field is mutated as a side
effect of a call that may never reach `_apply_stylesheets` at all.

If the stash is later drained via a full re-call to `_on_theme_changed(*pending)` (the correct,
existing pattern — used by `_on_fade_finished`, `complete_main_fade`, and now `snap_theme_forward`
after tonight's fix) — that re-call passes the SAME `theme_name`/`hover` that were already written
to `_active_display_theme_internal`/`_is_hover_active` at stash-time. The no-op guard sees no
difference and returns immediately, WITHOUT ever calling `_apply_stylesheets` or
`_schedule_deferred_restyle` — silently discarding the drain's entire purpose. Confirmed as the
mechanism here: no drain call site logged a `RESUMING`/`DRAINED`/fresh `_on_theme_changed
theme_name=` entry-line for `Anomander` anywhere in this window, which is consistent with a drain
attempt hitting this guard and returning via the DEBUG-only (not WARNING-level `[BLEED-TRACE]`)
no-op path — the dozens of `EARLY-RETURN no-op guard` lines already observed are the visible
symptom, not a separate event.

**This is a pre-existing structural gap in `_on_theme_changed` itself** (the ordering of the
`_active_display_theme_internal` assignment relative to the stash decision), not a defect specific
to `snap_theme_forward()`, `complete_main_fade()`, or `_on_fade_finished()` individually — all
three drain call sites are equally exposed, since all three replay the stashed
`theme_name`/`hover` through the same guard.

## Severity: worse than the two mechanisms already fixed tonight

The two earlier fixes this session (state-read bypass, hover-unaware blur grab) both concerned
TRANSIENT staleness — a wrong color visible for some bounded (if sometimes long) window, until
something eventually corrected it. This one is different in kind: **once `_active_display_theme_internal`
is set to a theme name whose actual application got stashed-then-guard-blocked, `_apply_stylesheets`
and `_schedule_deferred_restyle` may never run for that theme for the rest of the session** — the
only way out is a DIFFERENT theme being selected (temporarily setting
`_active_display_theme_internal` to something else, so the next re-selection of the original theme
name no longer matches the guard). Until then, EVERY surface that depends on the deferred pass
(Stats, Tags, Library, Sleep/Speed's per-button colors — see the sibling investigation for the
full list, all independently confirmed correctly wired) stays on whatever theme was last genuinely
applied, indefinitely — exactly matching what the user described: "some panels have the colors of
that theme, some earlier," with no hover involved at all, a plain active-theme click.

## Correlation with the heartbeat bug (separately tracked, still open)

The heartbeat bug's rapid spurious `enterEvent`/`leaveEvent` cycling is what's actually firing
`_on_theme_changed('Anomander', hover=False)` dozens of times in this window — none of which are
genuine user actions. Each one independently confirms the no-op guard is blocking real work, but
the heartbeat itself is NOT the root cause here — even a single legitimate drain attempt (via
`_on_fade_finished`, with zero heartbeat activity) would hit the exact same guard and produce the
exact same silent failure. The heartbeat makes this more likely to be OBSERVED (many more
re-invocation attempts, all blocked) but is not required to trigger it — a single unlucky
click-during-fade would be sufient on its own.

## What is NOT yet established (escalate before fixing)

- Whether the stash was actually drained by `_on_fade_finished` and silently blocked by the guard
  (most consistent with the evidence: `_fade_in_flight` cleared, `_pending_fade_call` cleared, no
  drain-path logging fired) — or whether some other, not-yet-found code path cleared
  `_pending_fade_call` without going through any of the three known drain sites at all. The former
  is far more likely given `_on_fade_finished` is confirmed to have ZERO logging of its own
  (verified by reading the method) — its silent operation is fully consistent with everything
  observed and requires no unknown mechanism. The latter has not been ruled out with the same
  confidence and would need `_on_fade_finished` to be instrumented (it currently has no log lines
  at all) to confirm definitively which of the two occurred.
- Whether this same guard-masking mechanism ALSO affects `_apply_stylesheets` (the fast-pass
  application) or only `_schedule_deferred_restyle` (the deferred pass) — tracing this specific
  occurrence, `_apply_stylesheets` for `Anomander` was ALSO never called (the guard blocks the
  whole method body, including the fast-pass application), yet the user's earlier reports (and this
  session's fast-pass fix) suggest fast-pass surfaces (main window, sidebar, settings/speed/sleep
  panel-level QSS) DO show current colors reliably. This apparent contradiction is not yet resolved
  — worth checking whether some other code path (e.g. `_apply_transport_bar_blur`'s own grab,
  which captures `main_window`'s LIVE rendered pixels rather than reading
  `_active_display_theme_internal`) is what makes the fast-pass surfaces look correct despite
  `_apply_stylesheets` never having run for `Anomander` specifically — i.e. whether `main_window`'s
  ACTUAL on-screen QSS is still the previous theme too, just not yet visually distinguished by the
  user from `Anomander` in this specific repro, or whether there is some other explanation.

## Files/lines involved

- `src/fabulor/ui/theme_manager.py` — `_on_theme_changed`'s no-op guard (near the top of the
  method) and the `_active_display_theme_internal`/`_is_hover_active` assignment ordering relative
  to the `_any_animating`/`_fade_running` stash decision. `_on_fade_finished` (currently
  zero-logging) is the most likely silent culprit for this specific occurrence.
