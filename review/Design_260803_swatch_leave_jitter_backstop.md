# Design: backstop for the swatch-boundary snapback-suppression bug

**Date:** 2026-08-03  **Branch:** `investigate/restyle-cost-depth-and-narrowing`  **Status:**
Design only. No source files touched. Written per Pryme's explicit task: design a fix for the bug
documented in `review/Investigation_260802_swatch_leave_jitter_suppression.md`, do not implement it.

---

## Required first step: the jitter guard's full prior history, in my own words

Read in full before any design work: CLAUDE.md's "Only `swatch_box.leaveEvent` may call
`_on_themes_tab_left`" section (lines 655-720) and "The theme-hover-active region is `swatch_box`
only" (722-734), plus `tests/test_hover_interrupts_snapback.py`'s BUG 3 section
(lines 194-288), which pins the current, shipped behavior against both historical regressions.

### The bug this guard was built to fix (2026-07-22)

With blur enabled, `transport_bar_blur._grab_and_blur` hides `settings_panel` (an ancestor of
`swatch_box`) roughly every ~65-200ms while a book plays, then re-shows it, to grab a frame for the
blur effect. That hide/show cycle fires a **synthetic** `leaveEvent`/`enterEvent` pair on every
descendant widget in between — including `swatch_box` and (at the time) `pool_container`. Before
this guard existed, ANY leave — synthetic or real — called `_on_theme_unhovered()`, which stops the
hover debounce timer unconditionally. If a synthetic leave landed inside a swatch's 80ms debounce
window (likely, given the ~65-200ms grab cadence), it killed the debounce before the genuine hover
could ever convert into an applied preview. Symptom: a deliberately-still hover on a theme swatch
could silently never show a preview at all.

### Attempt 1 (2026-07-28): position vs. the last genuine ENTER, ignoring visibility

Compared the leave's reported cursor position against `_last_swatch_pos` (set only by
`_on_theme_hovered`, i.e. the last genuine enter), with no visibility check at all. **Failure mode:**
this design **consumed the reference on every leave it classified as genuine** — after one real
leave fired a snapback, the reference was gone (or reset to `None`/the leave position, depending on
exactly how it was implemented at the time), so every SUBSEQUENT synthetic leave (still arriving
~15/sec from the blur grab) had no valid anchor to compare against, fell through a `None`-handling
fallback, and was itself classified as genuine — firing ~70 spurious snapbacks in 5 seconds with the
cursor completely frozen at one position. The regression is specifically about **what happens after
the first real leave**, not about the first classification being wrong.

### Attempt 2 (2026-07-28, same day): position vs. the last LEAVE, a rolling reference

Fixed the consuming-the-reference bug by rolling the anchor forward to the position of the
**previous leave** (not the previous enter) each time, so the anchor was never exhausted to `None`.
**Failure mode:** this broke the comparison's actual purpose. Consecutive synthetic leaves from the
blur grab are only ~65ms apart; if the cursor is genuinely moving (not frozen) during that window —
e.g. sweeping across the swatch grid while hovering — it travels 4-14px between two consecutive
synthetic leaves, which is well past `_MOUSE_JITTER_PX` (2). So every synthetic leave during cursor
motion now read as "genuine" relative to the immediately-preceding one, and each one called
`_on_theme_unhovered()` → `_hover_debounce_timer.stop()`, killing the 80ms debounce ~15x/sec.
Previews silently never fired while the cursor was in motion — this is **the original 2026-07-22
bug, reopened by a different mechanism** (rolling-reference position comparison instead of
unconditional-leave-triggers-unhover).

### The shared root error, and the shipped fix

Both attempts tried to infer "did the user genuinely leave?" from a **cursor-position delta between
two leave-adjacent samples**, when the widget's own Qt-reported `isVisible()` already answers the
question directly and with zero observed counterexamples (6/6 real mouse-outs measured `visible=True`
in a full live session; 12/12 leaves-while-hidden were synthetic). The shipped, current design
(`theme_manager.py:2047-2093`) uses **visibility as the PRIMARY and sufficient discriminator** — a
leave while hidden is unconditionally synthetic, full stop, no position check at all in that branch.
Position/jitter comparison against the last genuine ENTER (never the last leave, and never
consumed/rolled forward) survives only as a **secondary** guard for the one case visibility cannot
distinguish: a leave delivered while the widget IS visible, with the cursor not actually having
moved (a stylesheet-cascade repaint artifact). `_MOUSE_JITTER_PX = 2` was sized for that narrow
case — sub-pixel reporting noise on a genuinely-stationary cursor — not for a real, deliberate,
short-distance boundary crossing.

### Why the 2026-08-02 bug is a NEW failure mode of this same secondary guard, not a reopening of either historical one

Both prior regressions were about the **hidden-widget branch** misfiring under blur — they are
about visibility/blur-grab timing. The 2026-08-02 bug (both repros) hit the sibling
**visible-widget jitter branch**, confirmed by the exact log lines: `vis=True` on the leave event,
and the suppression log itself says `"visible but cursor unmoved"`. Confirmed structurally
independent of blur/backdrop mode (see the investigation doc's addendum) — Pryme reproduced it
identically with blur on and off. So this is a third, distinct failure mode of the SAME jitter
constant, not a resurgence of either documented regression: a genuine boundary crossing at a swatch
sitting near `swatch_box`'s own edge can report a leave position within 2px of the swatch's own
enter position, purely from the geometry of a shallow-angle or short-distance exit — not from the
cursor failing to move and not from any blur-grab synthetic timing.

**Consequence for this design:** the design below does NOT touch the jitter guard's condition,
constant, or reference semantics (enter-anchored, never consumed, never rolled). Per the task's own
instruction, this is treated as a component to backstop, not redesign — doing otherwise would need
to independently re-derive visibility as sufficient and re-verify against both historical
regressions from scratch, which is out of scope for what Pryme asked for here.

---

## The two cases, restated precisely

1. **Dwell case** (both confirmed repros): the cursor leaves the swatch, the leave gets suppressed,
   and the cursor then sits in the gutter/elsewhere for a noticeable duration (7s and ~34s in the
   two repros) before the user does anything else. During that whole window, the UI shows a
   preview theme that was never selected and the user believes they've moved past. A periodic
   re-check with a reasonable interval (hundreds of ms) would catch this well within the dwell time.
2. **Fast case** (Pryme's stated constraint, not yet directly repro'd but real by construction): the
   cursor leaves the swatch, the leave gets suppressed, and the user clicks to dismiss
   **immediately** — faster than any periodic timer's interval could fire. A periodic re-check
   alone cannot bound this case; the dismiss action itself must not trust that hover state is
   already correct.

## Finding that reframes the design: case 2 is already handled by existing, shipped code

`PanelManager._close_settings_flow` (`panels.py:1379-1383`) already calls, unconditionally, on
every dismiss of the Settings panel, regardless of any leave-event or timer history:

```python
self.main_window.theme_manager._on_theme_unhovered()
self.main_window.theme_manager.snap_theme_forward()
```

`_on_theme_unhovered()` does not read `_last_swatch_pos`, does not consult whether a leave was
suppressed, and does not depend on any timer having ticked — it unconditionally issues
`_on_theme_changed(<active theme>, hover=False, fade_ms=_SNAPBACK_FADE_MS,
bypass_panel_open_guard=True)`. This is confirmed, not assumed, by both repro logs: in each one,
the dismiss click produced exactly this direct `_on_theme_changed` call (`'Goldfinch'` in repro 1,
`'Rivendell'` in repro 2), and it correctly restored the right theme both times, no matter how long
the stuck preview had been showing beforehand. **The theme was never wrong AFTER a dismiss in
either repro — it was wrong DURING the dwell, up until the dismiss.**

This means: **case 2 (fast edge-out-then-immediate-click) cannot produce a wrong FINAL state at all
under the current code**, because `_close_settings_flow` forces correction unconditionally on every
dismiss, independent of timing. There is no race to lose here — dismiss doesn't need new
verification logic layered on top; it already re-asserts the correct theme every single time it
runs, and it always runs before the panel is considered closed (it's the first thing the method
does, before the animation-guard early-return at line 1393).

**What IS still wrong, and is the actual bug to fix:** the WINDOW between the suppressed leave and
the eventual dismiss, during which the UI visibly shows a theme the user believes they've already
moved past. That window can be arbitrarily long (unbounded dwell) and is what both repros actually
exhibit as the reported symptom. Fixing this is the dwell case (1) above — case (2) is not a
separate bug requiring separate machinery; it was already closed by existing code before this
investigation started.

**This is the load-bearing correction to the task's own framing.** The task asks the design to
cover "dismiss itself must not trust that hover state is already correct — it should independently
verify/force-correct... regardless of whether any timer tick or leave event fired beforehand." That
requirement is met, in full, by `_close_settings_flow`'s existing two-line call — nothing needs to
be added there. The design's job is narrower than originally scoped: **only the dwell-time backstop
(case 1) needs new machinery.** I want this stated plainly rather than silently building unneeded
dismiss-time code to satisfy the letter of the task — the mechanism asked for already exists and was
independently confirmed working in both repro logs.

---

## Design: a periodic re-check, scoped and justified

### Why a periodic re-check is the right shape for the dwell case, and why it doesn't share either historical failure mode

Both historical regressions were about **inferring genuineness from a position delta between two
event-driven samples** (leave-vs-enter, or leave-vs-previous-leave). A periodic re-check is a
structurally different mechanism: it does not classify any individual `leaveEvent` at all. It runs
on a `QTimer`, independent of whether any Qt leave/enter event fires, and asks a single, simple,
absolute question — **is the cursor currently outside `swatch_box`'s bounds, given the widget is
visible?** This is exactly the same check the hidden-widget branch already uses for its
falsification probe (`SWATCH-LEAVE-SUSPECT`, lines 2062-2073: `tab_widget.mapFromGlobal(pos)` /
`tab_widget.rect().contains(local)`), just run on a timer instead of only inside the already-existing
leave handler. It does not touch `_last_swatch_pos`, does not consume or roll any reference, and
does not change what counts as a "genuine leave" for the purposes of the existing jitter guard — it
is a wholly separate, additive check that reaches the same conclusion (call `_on_theme_unhovered()`)
via absolute position containment, never via a delta between two samples.

This sidesteps both regressions structurally, not by coincidence:
- Attempt 1's failure was about a reference being **consumed** and then unavailable for later
  synthetic leaves. A periodic check has no reference to consume — it reads `_last_swatch_pos`
  (unchanged, still enter-anchored, still never written elsewhere) only to decide whether a hover
  is currently believed active, not to compute a delta.
- Attempt 2's failure was about comparing consecutive **leave events** that are inherently close in
  time (~65ms apart) during real cursor motion, making genuine movement indistinguishable from
  jitter. A periodic check at a MUCH longer interval (proposed: 400-600ms, matched below) never
  compares two temporally-close samples against each other — it compares one absolute cursor
  position against one absolute widget rect, once per tick.

### Where it lives

`ThemeManager` (`theme_manager.py`), not `main_window_builders.py` — the standing architecture rule
that `main_window_builders.py` is pure wiring (widget construction/layout only, no logic) applies
here exactly as it does to the existing `swatch_box.leaveEvent = lambda _: ...` wiring, which is
itself the ONE line `main_window_builders.py` is allowed to own for this mechanism (per the "never
add a second bare `_on_theme_unhovered()` lambda" rule — this new mechanism must not add a second
lambda anywhere, it lives entirely inside `ThemeManager`).

New method: `ThemeManager._check_swatch_still_hovered(self)` (name illustrative; exact name is an
implementation detail). Logic, restated as pseudocode rather than code (per "design only, no
implementation"):

1. Early-return if no hover is currently believed active — i.e. mirror the exact condition
   `_on_theme_changed`'s own no-op guard already uses (`self._is_hover_active` is `False`, or
   there is no live `_pending_hover_theme`/applied hover theme to revert). This makes the timer's
   own tick cost negligible in the overwhelming common case (Settings not even open, or open but
   not hovering anything) — a boolean check and return, no cursor/geometry work at all.
2. If a hover IS currently believed active, look up `swatch_box` (via the same attribute path
   `_on_themes_tab_left` already receives as `tab_widget` — needs a stored reference or an
   attribute lookup through `main_window.settings_panel`/`tabs`, mirroring how `themes_tab_active`
   is already computed elsewhere in this file) and check: is it visible, and is the CURRENT cursor
   position (not a delta, not compared to any remembered position) outside its rect?
3. If both true (visible AND outside), call the existing `_on_theme_unhovered()` directly — the
   exact same call the jitter guard's genuine-leave branch already makes. No new revert logic; this
   only decides WHETHER to call something that already exists and is already correct.
4. If the widget is hidden (blur grab mid-cycle) or the cursor is still inside the rect, do nothing
   — leave the existing per-event mechanism as the sole authority for those cases. This backstop
   never runs instead of the event-driven path; it only catches what that path already missed.

### Timer ownership, lifecycle, and interval

- A single `QTimer` on `ThemeManager`, e.g. `self._swatch_leave_backstop_timer`, created once
  (mirroring `self._hover_debounce_timer`'s and `self._panel_guard_timer`'s existing construction
  pattern in this same class — no new pattern introduced).
- **Armed, not free-running.** It should start only when a hover preview is genuinely applied (the
  same moment `_is_hover_active` becomes `True` — i.e. hook it into wherever `_fire_pending_hover`
  or the hover-apply branch of `_on_theme_changed` already flips that flag) and stop unconditionally
  whenever a hover ends by ANY path: a genuine leave firing `_on_theme_unhovered()` normally, the
  backstop firing it itself, or the Settings panel closing (`_close_settings_flow`'s existing
  `_on_theme_unhovered()` call). This means the timer is only ever ticking while a preview is
  actually showing — not for the entire time Settings/the Themes tab is open, and never while no
  book is loaded or Settings is closed.
- **Interval:** propose 500ms. Reasoning: it must be short enough that the dwell window feels
  bounded/responsive (both repro dwells were 7s and 34s — 500ms is a small fraction of either,
  correcting the visible symptom promptly), but long enough to (a) stay well clear of the ~65-200ms
  blur-grab hide/show cadence so it never fires mid-cycle in a way that could misread a
  currently-hidden widget as a real leave (mitigated anyway by the visibility check in step 2, but
  worth keeping the margin wide), and (b) keep the tick's own work — an early-return boolean check
  in the common case, or one `mapFromGlobal`/`rect().contains()` pair in the active-hover case —
  negligible relative to its own interval. This is a proposal for Pryme to react to, not a measured
  optimum; no interval was live-tested for this design.

### Cost analysis for the periodic re-check

The tick body in the common case (no hover active — Settings closed, or open but nothing hovered)
is a single attribute read and an `if`, no different in cost class from the existing
`_hover_debounce_timer`'s own idle cost. This is NOT in the ~430-620ms `_apply_stylesheets` cost
category at all — it never calls `_apply_stylesheets` itself; it only conditionally calls
`_on_theme_unhovered()`, which is the SAME call the existing jitter guard already makes when it
correctly detects a genuine leave. In other words: this backstop does not introduce a new
expensive operation — it only widens WHEN the existing (already-paid-for-when-needed) revert
operation can trign, from "only on a correctly-classified Qt leave event" to "also on a periodic
absolute-position check." The revert itself is exactly as expensive as it already is today when the
jitter guard gets it right; this doesn't change that cost, it only closes a gap in when it fires.

### Why this doesn't make every dismiss pay full restyle cost

It doesn't touch dismiss at all. `_close_settings_flow` is unchanged in this design (see the
"already handled" finding above) — it already pays exactly one `_on_theme_unhovered()` +
`snap_theme_forward()` call per dismiss, exactly as it does today, whether or not the backstop timer
ever fired during that Settings session. The backstop's entire effect is on the DWELL window before
dismiss, not on dismiss itself. A dismiss that happens to follow a backstop-corrected hover pays
IDENTICAL cost to a dismiss that follows a normally-corrected hover — in both cases,
`_active_display_theme_internal` already equals the active theme and `_is_hover_active` is already
`False` by the time `_close_settings_flow` runs its `_on_theme_unhovered()` call, so THAT call hits
`_on_theme_changed`'s existing cheap no-op guard (line 816-817) and returns near-instantly instead
of paying a real restyle. The expensive restyle only happens once, whenever correction is genuinely
needed — either by the backstop (mid-dwell) or, absent this fix, by dismiss itself (as both repros
showed) — never twice for the same correction.

---

## Summary of what changes and what doesn't

**Changes (new code only):**
- A new, timer-driven method on `ThemeManager` that periodically checks absolute cursor-vs-rect
  containment while (and only while) a hover preview is genuinely active, and calls the existing
  `_on_theme_unhovered()` if the cursor has left `swatch_box` and the leave was apparently never
  caught.
- A `QTimer` instance, started when a hover preview applies, stopped whenever hover ends by any
  path (normal leave, this backstop, or Settings-panel dismiss).

**Explicitly NOT changed:**
- `_on_themes_tab_left`'s jitter guard — condition, constant, and enter-anchored/never-consumed
  reference semantics are all left exactly as shipped.
- `_close_settings_flow` — its existing unconditional `_on_theme_unhovered()` +
  `snap_theme_forward()` pair already satisfies the "dismiss must not trust prior state" requirement;
  confirmed by both repro logs, not assumed.
- `main_window_builders.py` — no new wiring lambda; the one existing
  `swatch_box.leaveEvent = lambda _: mw.theme_manager._on_themes_tab_left(swatch_box)` line is
  untouched, and this design adds no second lambda anywhere in that hierarchy.
- Any narrowing of `_MOUSE_JITTER_PX` or the jitter comparison's logic, per the task's explicit
  instruction and the "why 2026-08-02 doesn't justify touching it" reasoning above.

**Open items for Pryme to react to before implementation, if this direction is approved:**
- The proposed 500ms interval is a starting guess, not a measured value — happy to test a couple of
  values live once built, or take a different number now if preferred.
- Where exactly `swatch_box` should be looked up from inside `ThemeManager` for the timer tick
  (a stored reference captured once at Themes-tab construction time, vs. a fresh attribute-chain
  lookup on each tick) is an implementation detail not resolved here — both are cheap; the design
  doesn't require picking one yet.
- Whether the timer should also stop when the Themes tab itself is switched away from (leaving
  Settings open but on a different tab) — `_on_themes_tab_left`'s own hover-active-region rule
  already reverts on leaving `swatch_box`, which includes switching tabs, so this may already be
  covered by the existing leave-then-backstop interaction without special-casing it; worth
  confirming live rather than designing in a special case preemptively.
