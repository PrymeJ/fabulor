# Report: snapback-stuck-theme fix — mechanism, two attempts, final result

**Date:** 2026-08-03  **Branch:** `investigate/restyle-cost-depth-and-narrowing`  **Status:**
Fixed and verified — full 144-trial `tools/snapback_dismiss_harness.py` sweep at **0/144 (0.0%)
mismatches across all delay buckets** (0-250ms), full `pytest tests/ -q` at 435/435 passing.

This report supersedes the mechanism attribution in
`review/Investigation_260803_fallback_necessity.md` (2026-08-03, commit `6ff514d`) without
invalidating that document's headline finding. That investigation correctly established the
fallback in `snap_theme_forward` is reached at high frequency under realistic dismiss timing; this
report identifies what it is *actually* catching, which turns out not to be either of the two
mechanisms previously suspected.

---

## Summary of the whole arc

1. The 2026-08-03 fallback-necessity investigation found `snap_theme_forward`'s fallback is hit at
   ~67% (96/144) under a 0-80ms hover-out-to-dismiss delay, and attributed every failure's
   `_apply_stylesheets` call to `_do_fade_with_slider_animation:1382` via `traceback.extract_stack()`.
2. This task was to precisely trace that mechanism before designing a fix, and to reconcile it
   against the ORIGINAL (earlier, same-day) `.stop()`/`_fade_overlay.isVisible()`/`finished`-gap
   theory. Live reproduction found **neither theory was the real mechanism** — a third, independent
   bug in `PanelManager._panels_settled_waiters` (a plain FIFO queue with no coalescing).
3. A fix was designed and implemented for that FIFO-ordering bug (`coalesce_key` parameter on
   `call_when_panels_settled`).
4. **That fix alone did not work.** A full 144-trial sweep after implementing it still showed 63.2%
   (91/144) mismatches — barely different from the original 66.7%. Live re-tracing found a SECOND,
   related bug: `_on_theme_changed`'s early no-op guard was silently swallowing the unhover/snapback
   call before it ever reached the newly-fixed queue, because the guard compares against
   `_active_display_theme_internal`, which a still-queued call has not yet updated.
5. A second, smaller fix closed that gap (a `has_settled_waiter` query the no-op guard consults).
   The full 144-trial sweep after BOTH fixes landed shows **0/144 mismatches**.

The self-correction in step 4 is the load-bearing part of this report: the first fix was verified
against a single hand-rolled repro (`branch_check4.py`) that happened not to exercise the no-op-guard
interaction, and was initially reported as working on that basis. The full harness sweep is what
caught the gap. This is recorded here explicitly rather than smoothed over, per this branch's
standing rule against confusing "verified once" with "verified."

---

## Mechanism 1 (the real bug): `_panels_settled_waiters` FIFO-ordering

Reproduced live (`LD_PRELOAD` per CLAUDE.md, on-screen): open Settings, hover a theme swatch,
un-hover, dismiss immediately — all while the settings panel's own open animation (`blur_animation`,
400ms measured on this machine) is still running.

- Every `ThemeManager._on_theme_changed` call issued while `PanelManager._any_panel_animating()` is
  `True` — the initial reset-to-active call, the hover preview call, the unhover snapback call, and
  (if dismiss lands inside the window) `_close_settings_flow`'s own redundant unhover call — takes
  the `_any_animating` guard branch (`theme_manager.py`, before `themes_tab_active` is ever computed)
  and defers via `PanelManager.call_when_panels_settled(lambda: self._on_theme_changed(...))`.
- `call_when_panels_settled` appended every such deferred call to one shared list,
  `_panels_settled_waiters` — a plain FIFO list with **no coalescing, no supersession**, unlike
  `_pending_fade_call`'s explicit last-write-wins stash used elsewhere in the same file. The
  settle-watch tick drains the entire list in **issue order**, not intent order.
- Consequence, live-traced exact sequence: the hover's queued call (`Blindsight`, `hover=True`)
  resumed and applied via `_do_fade_with_slider_animation` — the exact call site the earlier
  investigation's traceback capture had found — **after** the unhover's own queued call, which
  performed no apply at all (see mechanism 2 below for why).
- `_fade_anim`/`_fade_overlay` are never touched by this mechanism at all: `fade_state_at_unhover` was
  `Stopped` and `_fade_overlay.isVisible()` was `False` throughout, in both the original sweep's CSV
  (96/96 recorded mismatches) and fresh live reproduction. **`snap_theme_forward`'s existing
  fallback — which guards on `_fade_overlay.isVisible()` — never fires for this mechanism at all.**
  It is a live, previously-unprotected bug.

### Reconciling against the two originally-suspected mechanisms

| | Trigger | Shared state | Caught by the existing fallback? |
|---|---|---|---|
| **A. Original `.stop()`/`finished` gap** | A real overlay fade (`_fade_anim`) genuinely running, `.stop()`-ed before completing | `_fade_anim`/`_fade_overlay`/`_fade_effect` | Yes — this is what the fallback's guard was built for. |
| **B. `_do_fade_with_slider_animation` variant** | Same shape as A, reached via the non-themes-tab fade branch; confirmed to reuse the literal same `_fade_anim`/`_fade_overlay` object | Same triple as A | Yes, same reason as A. |
| **C. `_panels_settled_waiters` FIFO-ordering (the real bug)** | Two-plus `_on_theme_changed` calls deferred while a panel-open/blur animation (NOT a theme fade) is running, replayed in issue order | `PanelManager._panels_settled_waiters` — unrelated to `_fade_anim` | **No** — confirmed live, `_fade_overlay.isVisible()` is `False` throughout. |

**The 144-trial sweep's 96/96 mismatches were all mechanism C, not A/B — despite the traceback
correctly naming `_do_fade_with_slider_animation` as the applying call site.** That attribution was
real but incomplete: it identified *which branch ran*, not *why the wrong call got there in the first
place* (the FIFO queue), nor *why the correcting call never ran at all* (mechanism 2, below).
Mechanism A/B was never actually exercised by that sweep (every trial's `fade_state_at_unhover` was
`Stopped` — no trial ever caught a genuinely-running fade being interrupted). **Whether A/B's
fallback is itself frequently hit is still an open question**, unchanged by anything in this report.

---

## Mechanism 2 (found during verification of the first fix): the early no-op guard swallows the snapback

The first fix (`coalesce_key="theme_change"` on `call_when_panels_settled`, see "Fix implemented"
below) was correct as far as it went, but a full 144-trial re-sweep still showed 91/144 (63.2%)
mismatches — indistinguishable in aggregate from the unfixed 66.7%. Live re-tracing (adding a
`traceback`-based entry/exit trace to `_on_theme_changed` itself, not just `_apply_stylesheets`)
found the unhover call was returning **immediately**, before ever reaching the `_any_animating`
branch the first fix touched — meaning the fix's own coalescing logic was never even invoked for one
side of the race.

Root cause: `_on_theme_changed`'s early no-op guard —

```python
if (getattr(self, "_active_display_theme_internal", None) == theme_name
        and self._is_hover_active == hover):
    ...
    return
```

— compares the incoming call's target against `_active_display_theme_internal`/`_is_hover_active`,
which are **only** written by `_mark_theme_applied`, itself only called from inside a branch that
actually ran `_apply_stylesheets`. The hover call, having taken the deferred `_any_animating` branch,
had **not yet reached that point** — `_active_display_theme_internal` still held `'Alzabo'` (the
theme active before the hover started). The unhover call's own target is *also* `('Alzabo', hover=False)`
— the theme it's trying to restore. These two coincidentally matched, so the guard treated the
unhover as a redundant duplicate of already-applied state and silently returned, **never even
constructing the `call_when_panels_settled` call the first fix's coalescing logic depends on**.
Confirmed via direct trace: `[GUARD-MASK-TRACE] ... theme_name='Alzabo' ... SUSPECT_MASKED_STASH=False`
fired for the unhover call, meaning the guard's own existing "was this a masked stash" heuristic
(comparing against `_theme_ever_applied`) also failed to catch this — that heuristic was built for
`_pending_fade_call`'s stash, not for a call still sitting in `_panels_settled_waiters`.

### Fix implemented (second half)

`PanelManager.has_settled_waiter(coalesce_key)` — a one-line query over `_panels_settled_waiters` —
lets the no-op guard check whether a same-key call is still in flight through the deferred queue
before trusting `_active_display_theme_internal` as ground truth:

```python
_pm = getattr(self.main_window, 'panel_manager', None)
_theme_change_queued = bool(_pm and _pm.has_settled_waiter("theme_change"))
if (not _theme_change_queued
        and getattr(self, "_active_display_theme_internal", None) == theme_name
        and self._is_hover_active == hover):
    ...
```

With this in place, the unhover call correctly reaches the `_any_animating` branch, where the first
fix's `coalesce_key="theme_change"` replaces the hover's still-queued entry — so only the unhover's
intent survives to apply once the panel-open animation genuinely settles.

---

## Fix implemented (first half, restated)

`PanelManager.call_when_panels_settled(callback, coalesce_key=None)`: when a non-`None` key is
given, a later call with the same key **replaces** the earlier queued entry in place, instead of
appending a second FIFO entry. `ThemeManager` passes `coalesce_key="theme_change"` at its one deferred
call site (the `_any_animating` branch). Every other caller of `call_when_panels_settled` passes no
key and is unaffected — today's append-only FIFO behavior is preserved for them.

## Files changed

- `src/fabulor/ui/panels.py` — `_panels_settled_waiters` storage shape (list of
  `(coalesce_key, callback)` tuples instead of bare callables), `call_when_panels_settled`'s
  `coalesce_key` parameter, `_on_settled_watch_tick`'s drain loop, new `has_settled_waiter` method.
- `src/fabulor/ui/theme_manager.py` — the early no-op guard now consults `has_settled_waiter`; the
  `_any_animating` branch's `call_when_panels_settled` call now passes `coalesce_key="theme_change"`.
- `tests/test_panel_settle_resume.py` — updated the `_RecordingPM` test double
  (`coalesce_key`/`has_settled_waiter`) and the direct-seed requeue test for the new tuple storage
  shape; added a new Group D (3 tests) pinning the coalescing behavior itself.
- `tests/test_hover_interrupts_snapback.py` — added `has_settled_waiter` to `_FakePanelManager`.

No changes to `_fade_anim`, `_fade_overlay`, `_do_fade_with_slider_animation`, `snap_theme_forward`,
or `_pending_fade_call` — mechanisms A/B (see the table above) remain completely untouched, on
purpose, since they are a different bug reached through a different queue. Whether their fallback is
itself frequently necessary remains an open question this work does not answer.

## Verification

- `pytest tests/ -q`: 435/435 passing (was 435/435 before this work; two test doubles updated to
  match the new method signatures, three new tests added).
- `tools/snapback_dismiss_harness.py`, three full 144-trial runs, same CSV
  (`review/fallback_necessity_harness_results.csv`), distinguishable by `batch_timestamp`:
  - `2026-08-03T05:48` (pre-fix): 96/144 (66.7%) mismatches — the original investigation's finding.
  - `2026-08-03T15:42` (first fix only): 91/144 (63.2%) mismatches — the insufficient intermediate
    state; kept in the CSV as the historical record of why a second fix was needed, not discarded.
  - `2026-08-03T16:02` (both fixes): **0/144 (0.0%) mismatches**, every delay bucket including 0ms.
- Live spot-check via a standalone script matching the harness's exact 0ms-delay sequence: before
  either fix, `stylesheet_ok: False, _active_display_theme_internal: 'Blindsight'`; after both fixes,
  `stylesheet_ok: True, _active_display_theme_internal: 'Alzabo'`.

## What remains unverified (unchanged from the original investigation)

Whether `snap_theme_forward`'s fallback (`_fade_overlay.isVisible()` guard) is itself frequently
necessary for mechanism A/B — a genuinely-running overlay fade interrupted by `.stop()` — is still
unanswered. No sweep in this arc, before or after either fix, ever recorded a trial with
`fade_state_at_unhover: Running`. A targeted sweep forcing that condition (a longer configured
`theme_fade_duration`, or dismissing immediately after a real theme *selection* rather than a hover)
would be new work, not a rerun of anything here.
