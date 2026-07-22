# Investigation: hover-on-hover should interrupt, not stash-then-discard

**Date:** 2026-07-21  **Branch:** `blur-composited-overlay`  **Status:** diagnosis only, no fix
implemented. Confirms a real, reproducible usability regression introduced by tonight's earlier
hover-confinement fix (discard hover-flagged stashes at drain time) — that fix was correct for the
bug it targeted (transient cursor pass-overs reaching panels) but has the side effect described
below for GENUINE, post-debounce hovers.

---

## 1. Where the debounce lives, and its relationship to the stash/discard path

`_HOVER_DEBOUNCE_MS = 60` — no, confirmed by direct read: **`_HOVER_DEBOUNCE_MS = 80`**
(`theme_manager.py:60`), exactly 80ms as the user recalled, not 90. Single global `QTimer`
(`self._hover_debounce_timer`, `theme_manager.py:146-149`), NOT per-swatch — one shared instance
on `ThemeManager`, restarted on every `enterEvent`.

Mechanism, traced fully:
- `_on_theme_hovered(theme_name)` (`theme_manager.py:1432-1437`): stores `theme_name` in
  `self._pending_hover_theme`, restarts the single-shot timer. Called on every swatch `enterEvent` —
  a fast sweep across many swatches just keeps restarting the same timer with a new pending name,
  coalescing the sweep.
- `_fire_pending_hover()` (`theme_manager.py:1439-1452`): the timer's `timeout` handler. Fires ONLY
  if 80ms elapsed with no newer `enterEvent`. This is the SOLE call site that produces a genuine,
  debounce-cleared `_on_theme_changed(theme_name, hover=True)` call from the swatch-sweep path
  (line 1452).

**Confirmed: the debounce is fully upstream and has zero further role once `_fire_pending_hover`
calls `_on_theme_changed`.** By the time a `hover=True` call reaches `_on_theme_changed`'s body —
including the stash/discard logic — debounce has already done 100% of its filtering job. There is
no re-entry into the debounce timer from anywhere inside `_on_theme_changed`, the stash branch, or
either discard site. The debounce and the stash/discard logic are sequential and independent, exactly
as assumed in the task framing — confirmed, not assumed.

**One second, separate hover-trigger path exists**, worth flagging precisely since the task asked
whether ANY path could reach the stash logic without debounce: `_on_cover_pool_btn_hovered()`
(`theme_manager.py:1626-1634`) calls `_on_theme_changed(self._cover_theme, ..., hover=True)`
directly, with NO debounce timer involved at all — it fires immediately on the cover-pool button's
own hover signal. This is not a bypass of the swatch-sweep debounce (it's a structurally different
target — a single fixed button, not one of many swept theme names — so coalescing a "sweep" was
never a design need there). It reaches the exact same stash/discard logic as the debounced path.
This does not change the safety analysis for the proposed fix (the interrupt logic keys off
`hover=True` status of BOTH the incoming call and the in-flight fade, not off how the incoming call
was triggered), but is reported here as requested, since it's a second real path into the same code.

## 2. Can a hover call reach stash/discard without having passed debounce?

**No**, for the swatch-sweep path — every `_on_theme_changed(hover=True)` call from that path is
provably post-debounce (line 1452 is the only site, reached only from the timer's `timeout`).
The cover-pool-button path (above) has no debounce by design, not as a gap — it was never subject
to a sweep-coalescing need. Touching the stash/discard interrupt logic does not risk affecting
"fast pass-overs" from the swatch sweep, since fast pass-overs never produce a call that reaches
this logic in the first place (they never survive to fire `_fire_pending_hover` at all — a new
`enterEvent` restarts the timer before the old one elapses, so the pending name is simply
overwritten in `_pending_hover_theme`, no `_on_theme_changed` call is ever made for it).

## 3. Debounce timer scope

Confirmed **single global timer**, not per-swatch/per-target (`self._hover_debounce_timer`,
constructed once in `__init__`, `theme_manager.py:146`). At any instant there is at most one
"pending hover" (`self._pending_hover_theme`) and at most one in-flight fade
(`self._fade_anim`/`self._fade_in_flight`). This means "a new genuine hover on B arrived while A's
fade is still running" is unambiguous at the point an interrupt would fire — there is only ever one
current fade and one newly-arrived call to reconcile, never multiple candidates.

## 4. Exact stash site, and what it does NOT distinguish today

`_on_theme_changed`, the `elif _fade_running:` branch — **`theme_manager.py:682-694`**:

```python
elif _fade_running:
    ...
    self._pending_fade_call = (theme_name, save, fade_ms, hover, user_initiated)
    return
```

`_fade_running = getattr(self, '_fade_in_flight', False)` (line 650), checked with zero regard for
WHAT kind of call started the currently-running fade, and zero regard for whether the INCOMING call
is a hover or a genuine selection. Every combination (hover-interrupts-hover,
hover-interrupts-genuine-selection, genuine-selection-interrupts-hover,
genuine-selection-interrupts-genuine-selection) hits this exact same branch today, with identical
handling: stash, return. The only place behavior currently diverges by `hover` is DOWNSTREAM, at
drain time (tonight's earlier fix) — never at arrival time.

## 5. Explicit confirmation: hover-interrupts-hover and hover-interrupts-genuine-selection are THE SAME CODE PATH today

The task asked to check, not assume, whether these are already handled differently. **They are not
— confirmed by the code above.** `_fade_in_flight` (`theme_manager.py:759`, `929` — the two
`= True` write sites, themes-tab-overlay-fade branch and slider-animated-fade branch respectively)
is a plain boolean with no memory of what kind of call set it. The ONLY way to know, at the moment a
new call arrives, whether the currently-running fade was itself a hover preview is
`self._is_hover_active` — which (per tonight's earlier `_mark_theme_applied` fix) correctly reflects
the hover state of whatever was last GENUINELY applied, i.e. the call that started the currently-running
fade (since `_mark_theme_applied` is called at the point that fade's own `_apply_stylesheets` ran,
before the fade animation itself necessarily finishes).

So: **the same `elif _fade_running:` branch, with no changes to its trigger condition, already has
everything needed to distinguish the four cases** — `hover` (the incoming call's flag, already a
parameter) and `self._is_hover_active` (the in-flight fade's origin, already correctly maintained).
No new state needs to be introduced to make this distinction; it already exists, just unused at this
decision point today.

**What SHOULD happen for genuine-selection-fade-interrupted-by-hover, per the task's explicit
requirement not to assume:** the user's fix request scopes the interrupt-and-restart behavior to
"ONLY when the in-flight fade being interrupted is itself hover-driven." Per the trace above, if
`self._is_hover_active` is `False` at the moment a hover call arrives (meaning a genuine selection's
settle-fade is still running), the CURRENT stash-then-discard behavior would apply: the hover call
gets stashed, then discarded at drain time (correct, since a hover preview should never interrupt a
genuine selection's settle-fade — the user only asked for hover-cancels-hover). This sub-case's
current behavior is NOT something this investigation is proposing to change, and per the trace, the
existing code's `_fade_running` branch already produces exactly that outcome without needing to be
touched for this sub-case — the ONLY new behavior needed is for the `self._is_hover_active == True`
sub-case (in-flight fade is itself a hover), which currently produces the same
stash-then-discard (now confirmed as the actual complaint) but should instead interrupt-and-restart.

## 6. Existing fade-stop mechanism, confirmed reusable

`theme_manager.py:707-708`, inside `_on_theme_changed` itself, immediately AFTER the stash checks
(lines 669-694) and immediately BEFORE the three-way apply branch:

```python
if self._fade_anim.state() == QPropertyAnimation.Running:
    self._fade_anim.stop()
```

This is the exact same `if state == Running: stop()` pattern used identically at four other sites
(`abort_theme_fade` line 217-218, `snap_theme_forward` line 284-285, `complete_main_fade` line
996-997) — a simple, already-proven-safe mechanism, not something that needs inventing. Critically:
**this line is currently UNREACHABLE for any call that hits the `elif _fade_running:` stash branch**,
because that branch `return`s before execution ever reaches line 707. The interrupt fix, in shape,
is: for the specific sub-case (incoming `hover=True` AND `self._is_hover_active == True`), do NOT
take the `elif _fade_running:` branch's stash-and-return path — instead fall through to the same
stop-and-apply flow every non-fade-running call already takes, which already correctly stops the
old fade (line 707-708) and starts a fresh one for the new theme. No new stop mechanism needs to be
written; the fix is about which calls are ALLOWED to reach the code that already exists at line 707
onward, not about adding a new way to stop a fade.

## Summary — fix shape, not yet implemented

At the `elif _fade_running:` check (`theme_manager.py:682`), before stashing: if `hover` (the
incoming call) is `True` AND `self._is_hover_active` (the in-flight fade's origin) is also `True`,
do not stash — fall through to the normal stop-and-apply path instead (which already exists,
already stops the old fade via the mechanism at line 707-708, and already starts a fresh fade for
the new theme via the existing three-way branch). Every other combination (hover interrupting a
genuine-selection fade; a genuine selection interrupting anything) keeps today's exact behavior —
stash, and (per tonight's earlier fix) drain-time replay-or-discard based on the STASHED call's own
hover flag, unchanged. This does not touch the debounce (confirmed fully upstream and independent)
and does not touch the drain-time discard logic (`_on_fade_finished`/`snap_theme_forward`/
`complete_main_fade`) — those remain correct and unmodified for every case except the one now
short-circuited before ever reaching a stash at all.

No code changes made in this investigation, per instruction.
