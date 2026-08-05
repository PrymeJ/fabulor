# Design: correct SWATCH-LEAVE-SUSPECT instead of only detecting it

**Date:** 2026-08-05  **Branch:** `investigate/restyle-cost-depth-and-narrowing`  **Status:** Design
only, per explicit instruction — no source changes in this pass.

## Context

Confirmed today from real session logs (not assumed): `[SWATCH-LEAVE-SUSPECT]` fires 150 times in
the current log, and several of those hits produce genuine, multi-minute stuck windows (62s, 80s,
106s, 125s, 277s observed within single running sessions) where `_is_hover_active` stays `True`
with nothing correcting it, starving `transport_bar_blur.py`'s `hover_active_gate` for the entire
window. This is not new information invented today — it re-confirms a finding already on record
from **2026-08-03** (TODO.md: *"`[SWATCH-LEAVE-SUSPECT]` fired live, for real... this falsifies
`_on_themes_tab_left`'s 'leave-while-hidden is always synthetic' premise... needs its own
investigation into why a real leave can fire while hidden"*) — that TODO entry has sat open and
unaddressed since, and this design is that follow-up.

## 1. Why detect-only was the original choice — and why it no longer applies

**This was not a deliberately conservative design choice made with today's fix in mind — it
predates the falsifying evidence entirely.** Reading `_on_themes_tab_left`'s own docstring
("FINAL FORM", 2026-07-28) and `Design_260803_swatch_leave_jitter_backstop.md` in full: the hidden
branch was built and shipped on the explicit, stated premise that **a real mouse-out never arrives
while `swatch_box` is hidden** — "Measured over a full live session: 6 real mouse-outs, all
`visible=True`... and zero real mouse-outs while hidden," and separately, "12/12 leaves-while-hidden
were synthetic." Given that premise, the hidden branch had nothing to correct — every leave
delivered while hidden was, by the evidence available at the time, unconditionally a blur-grab
synthetic, and calling `_on_theme_unhovered()` for a synthetic leave was already known to be
actively harmful (that is the exact 2026-07-22 bug this whole branch exists to prevent: an
unconditional revert-on-every-leave killing the 80ms hover debounce ~15x/sec while blur is
grabbing).

`SWATCH-LEAVE-SUSPECT` was added specifically as **a falsification probe for that premise**, not as
a partial fix awaiting completion — its own comment says so explicitly: *"this branch's whole
premise is 'a real mouse-out never arrives while hidden'. If that is wrong, the symptom is a
suppressed leave whose cursor has left `swatch_box`'s bounds entirely... A non-zero count falsifies
the premise; do NOT patch around it, bring the lines back."* The instruction was never "silently
correct and move on" — it was "notice if this ever happens, because if it does, the branch's core
assumption is wrong and needs to be revisited," which is a materially different task than "add a
one-line fix." The premise **was** falsified, on 2026-08-03, and flagged in TODO.md — but the
"needs its own investigation" step never happened until today's log analysis, which is what this
design now closes out.

**Was it ever measured to have a real false-positive risk?** No — and by construction, it cannot.
The check is `not tab_widget.isVisible() and cursor_position_outside(tab_widget.rect())`. The
second half of that is not a heuristic inference about user intent (unlike the sibling jitter guard,
which infers "did the cursor move enough to count as leaving" from a position delta and has a real,
documented history of two false-positive regressions from exactly that kind of inference). It is a
direct geometric fact, read live from `QCursor.pos()` at the instant the check runs: **is the
cursor, right now, inside or outside this rectangle.** If it is outside, the cursor is not over the
swatch grid, full stop — there is no live hover state for anything to protect, regardless of *why*
`swatch_box` happens to be hidden at that moment (checked directly: nothing in the codebase calls
`swatch_box.hide()`/`setVisible(False)` itself; its visibility is entirely inherited from ancestors,
and the blur grab hiding `settings_panel` is the only mechanism that does so today). The only
genuinely uncertain part of the original heuristic was *why the widget was hidden* (blur-grab vs.
some other cause) — and that uncertainty is irrelevant to the correction, since the correction only
depends on where the cursor demonstrably is, not on why the widget's paint state changed.

**Conclusion for item 1:** there is no false-positive risk to weigh, and no reason "always correct
on SUSPECT" needs to stay conservative. The one thing worth naming as residual, not risk: the
`try/except Exception: outside = False` wrapper around the geometry read (existing code, unchanged
by this design) means a genuine SUSPECT condition could theoretically be silently swallowed by an
exception during `mapFromGlobal`/`rect()` — but that already defaults to the SAFE side (no
correction fires) rather than an unsafe one, so it does not introduce a new risk either.

## 2. The exact hook point, and whether `_on_theme_unhovered()` is safe to call from here

**Hook point:** inside `_on_themes_tab_left`'s hidden-widget branch (`theme_manager.py`, currently
~line 2544-2574), in the `if outside:` arm — the exact branch that already computes
`outside = not tab_widget.rect().contains(local)` and already logs `[SWATCH-LEAVE-SUSPECT]`. The
fix is one call added directly after (or in place of) that log line:

```python
if outside:
    logger.warning(
        f"[SWATCH-LEAVE-SUSPECT] suppressed a leave while hidden, but the "
        f"cursor is OUTSIDE swatch_box — this may be a real mouse-out that "
        f"was eaten. pos={(pos.x(), pos.y())} local={(local.x(), local.y())} "
        f"rect={tab_widget.rect()}"
    )
    self._on_theme_unhovered()   # <-- the one line this design adds
else:
    ...
```

No other change to the branch. The `else` arm (genuinely synthetic — hidden, cursor still inside the
rect) is untouched; it still just logs at DEBUG and returns.

**Is `_on_theme_unhovered()` safe to call from this exact context?** Yes, confirmed by direct
reading, not assumed by analogy. `_on_theme_unhovered()`'s full signature is `def
_on_theme_unhovered(self):` — it takes no arguments, reads no event object, and has no dependency on
*how* it was invoked. Its body: stops the hover debounce timer, clears `_pending_hover_theme`, sets
`_snapback_in_progress = True` for the duration of one `_on_theme_changed(...)` call (in a
`try/finally`, so an exception cannot strand the flag), then clears it. None of this reads or
requires anything about the calling context — timing, event shape, or widget state. This is already
proven in production by the fact that it is called today from **three structurally different
contexts**: `_on_themes_tab_left`'s own genuine-leave branch (event-driven, this same method, a
different arm), `_check_swatch_still_hovered`'s periodic `QTimer` backstop (not event-driven at
all — a polled tick), and `PanelManager._close_settings_flow` (an unconditional call on every
dismiss, regardless of any leave history). A fourth call site — this design's hidden-branch
correction — introduces no new precondition and is not meaningfully different from the second of
those three: `_check_swatch_still_hovered` already calls `_on_theme_unhovered()` from a non-genuine-
leave-event context, based on the identical geometric check, and has been shipped and live-verified
since 2026-08-03 (`1a82c11`) with no reported issue.

**No additional guard is needed beyond what the branch already computes.** The `outside` boolean is
already exactly the correctness condition; there is nothing further to check.

## 3. Interaction with everything built today

**Does this need any deleted mechanism back?** No.
- `clear_stale_hover_state()` (deleted): its job was to force-correct
  `_is_hover_active`/`_active_display_theme_internal` and repaint stuck surfaces whenever Settings
  became hidden. This design corrects the flag at the moment the suppression is detected, which is
  strictly earlier and more precise than waiting for a panel-hide event — after this fix, there is
  no "stuck until Settings closes" window left for that method's job to matter, for the same reason
  its deletion was confirmed safe: `_close_settings_flow` already unconditionally calls
  `_on_theme_unhovered()` before hiding, so by the time Settings closes, the flag is correct either
  via a genuine leave, this fix, the periodic backstop, or the dismiss's own call. No regression risk
  from its absence.
- `check_cursor_on_settle()` (deleted): unrelated axis entirely (hover-*start* on panel-open settle,
  not hover-*end* correction). Not implicated by this design at all.

**Does this correctly feed into the same, already-verified settle infrastructure, or is it a new
parallel mechanism?** It is not new. `_on_theme_unhovered()` is the single, existing entry point
every other correction path already calls — this design adds a fourth caller of that exact same
method, with zero new state, zero new timers, and zero new predicates. Downstream of that call,
everything is identical to today: `_on_theme_changed(..., hover=False, bypass_panel_open_guard=True)`
runs through the same `_hover_may_interrupt`/no-op-guard/fade pipeline as every other snapback,
`_mark_theme_applied` sets `_is_hover_active=False` and `_active_display_theme_internal` to the
committed value exactly as it does for a genuine leave, and — critically for today's two other
fixes — `_theme_genuinely_settled_on_committed()` (the Esc/gutter dismiss and tab-switch
interceptor's shared settle predicate) sees exactly the same state transition it already knows how
to wait for. Nothing about `call_when_theme_settled()`, `get_committed_theme()`, or
`_ThemesTabBarInterceptor` needs to change or even be aware that this fourth caller exists — from
their perspective, a hover simply ended slightly earlier than it otherwise would have.

**Does this make either of today's two fixes' own SUSPECT-adjacent behavior redundant or
conflicting?** No conflict, and a slight strengthening of both, checked explicitly:
- The Esc/gutter dismiss fix is unconditional regardless of this design (`_close_settings_flow`
  always calls `_on_theme_unhovered()` on its own) — this fix just means that call is more often
  already a no-op by the time dismiss runs, because the correction happened earlier. No behavior
  change to the dismiss path itself.
- The tab-switch interceptor reads `_theme_genuinely_settled_on_committed()` at the moment of a tab
  click. Today, if a SUSPECT-suppressed leave happened moments before the click, the interceptor
  would already correctly detect "not settled" and correct via its own call to
  `_on_theme_unhovered()` — so the interceptor already has full coverage for this case at the moment
  of a tab click specifically. What this design adds is coverage for the window **before** any
  dismiss or tab click happens at all — i.e., the case Pryme's original question was really about:
  the transport-bar blur staying stale for minutes while the user does neither of those two actions.

## 4. Cost

**This adds exactly one function call, gated behind a condition that is already being evaluated
today.** `SWATCH-LEAVE-SUSPECT`'s geometry check (`mapFromGlobal`, `rect().contains()`) already runs
today, unconditionally, every time a leave is delivered while `swatch_box` is hidden — this design
does not add a new check, a new timer, or new polling of any kind. It only changes what happens in
the branch that was already computed and already true: today it logs and returns; after this
change, it logs and then calls a method that itself does nothing else expensive unless a real
correction is genuinely due (and if one is due, that correction was already going to happen anyway,
just later — at the next dismiss, tab-switch, or unrelated theme change, per the "no wrong FINAL
state" reasoning `Design_260803_swatch_leave_jitter_backstop.md` already established for the
sibling backstop). This fix does not change the cost of the common, overwhelming case at all: when
the widget is hidden and the cursor genuinely is still inside the rect (the true blur-grab-synthetic
case), `outside` is `False`, the `if outside:` branch is never entered, and nothing about this design
executes.

## Summary of what changes and what doesn't

**Changes:** one line, `self._on_theme_unhovered()`, added inside `_on_themes_tab_left`'s existing
`if outside:` arm (the `SWATCH-LEAVE-SUSPECT` branch), immediately after the existing warning log.

**Explicitly not changed:**
- The `SWATCH-LEAVE-SUSPECT` detection logic itself (the `outside` computation) — it is already
  correct and is the thing being acted on, not replaced.
- `_check_swatch_still_hovered` / the periodic backstop timer — unrelated, already-shipped mechanism
  for a different gap (the visible-widget jitter dwell case); left exactly as-is.
- `_MOUSE_JITTER_PX`, the jitter guard's condition/reference semantics, or anything about the
  visible-widget branch of `_on_themes_tab_left`.
- Any of today's other three fixes (Esc/gutter dismiss, `get_committed_theme()`, the tab-switch
  interceptor) — this design's correction feeds into their shared infrastructure without requiring
  any change to it.
- No new state, no new timer, no new predicate, no deleted mechanism restored.

**Verification plan for the implementation pass (not done here):** `grep -c "SWATCH-LEAVE-SUSPECT"`
over a real session's log will still be non-zero (the detection is unchanged and will keep firing
whenever the underlying misclassification happens) — the thing to verify post-fix is that no
`hover_active_gate` decline run following a SUSPECT hit extends past roughly one tick's worth of
latency, i.e., confirm live that the multi-minute stuck windows measured today no longer occur,
using the same log-gap-measurement approach already used to find them.
