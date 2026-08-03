# Investigation: settings-panel-open hover-preview inconsistency (cases 1/2/3)

**Date:** 2026-08-03  **Branch:** `investigate/restyle-cost-depth-and-narrowing`  **Status:**
Root cause identified for the structural question (no "check cursor on settle" mechanism exists);
case 1 explained with high confidence; case 3's exact live transient not reproduced in this session's
synthetic harness — flagged explicitly as unresolved, not glossed over. **Investigation and root
cause only, per the task — no fix proposed or implemented.**

---

## Summary of the answer, upfront

**There is no code anywhere in this app that checks "is the cursor currently over a swatch" at
panel-open-settle time and triggers a preview.** Every hover preview, without exception, is driven
by Qt's own `ThemeItem.enterEvent`/`leaveEvent` — genuine, Qt-delivered mouse-tracking events. There
is no cursor-position poll anywhere in the hover-trigger path (confirmed by exhaustive grep across
`theme_manager.py`, `panels.py`, `title_bar.py`, `main_window_builders.py` — every `QCursor.pos()`
call site is enumerated below and none of them serve this purpose).

This means **case 2's "success" is not this app doing the right thing on purpose — it is Qt/the
Wayland compositor sometimes, but not reliably, delivering a fresh Enter event when a widget becomes
visible under an already-resting cursor.** Case 1's "failure" is not stale state left over from a
previous session at all — it is the SAME missing mechanism, just landing on the "Qt didn't redeliver
Enter" side of a platform-dependent coin flip instead of the "it did" side. **Cases 1 and 2 are not
two different code paths; they are the same code path (or rather, the same ABSENCE of a code path)
producing two different observed outcomes because the thing case 2 relies on for its "success" was
never something this codebase controls or guarantees.**

Case 3 is very likely a genuinely separate, additional mechanism (a stale `_pending_panel_sheet`
catch-up race), but this session's synthetic harness could not reproduce it under any timing window
tried — see the dedicated section below for what was ruled out and what remains open.

---

## Step 1 — every piece of "what theme is currently hovered/previewed" state

All in `theme_manager.py` unless noted:

- **`_active_display_theme_internal` / `_is_hover_active`** — the sole ground truth for "what theme
  is currently painted, and was it a hover," written ONLY by `_mark_theme_applied` (line 654),
  called synchronously right after a real `_apply_stylesheets` call. This is the state my earlier
  fix tonight (`Report_260803_snapback_stuck_theme_fix.md`) found being read too early by the no-op
  guard.
- **`_pending_hover_theme`** — the debounce-coalescing slot `_on_theme_hovered` writes and
  `_fire_pending_hover` (the 80ms-later timer callback) consumes. Purely a "which name was last
  entered" buffer; cleared by `_on_theme_unhovered` too.
- **`_last_swatch_pos`** — written only by `_on_theme_hovered`, at the moment of a genuine enter;
  read only by `_on_themes_tab_left`'s jitter-suppression logic (deciding whether a leave is real or
  a blur-grab synthetic). Not a "where is the cursor now" query — a "where was it at last genuine
  enter" reference.
- **`_pending_panel_sheet`** (dict, keyed by `objectName()`) — the settings/speed/sleep stylesheet
  catch-up stash. Written **unconditionally on every single `_apply_stylesheets` call**
  (`theme_manager.py:1701`, inside the try/finally that also sets the spurious-enter guard), covering
  ALL THREE panels regardless of which is visible. Read by `apply_pending_panel_sheet(panel)`, called
  from every `_start_*_entry` before `show()`. This is the mechanism-C-adjacent state examined in
  detail for case 3 below — it is a DIFFERENT stash from `_panels_settled_waiters` (tonight's earlier
  mechanism-C fix) and was not touched by that fix.
- **`PanelManager._panels_settled_waiters`** — tonight's earlier fix target. Cross-referenced: this
  investigation's case 3 hover call DID route through it in one tested timing window (panel-open
  animation still running at hover time) and was correctly coalesced away by the `coalesce_key` fix —
  see the "Is this related to mechanism C?" section below for the full reasoning.
- **`_fade_anim` / `_fade_overlay` / `_fade_in_flight`** — the shared preview/snapback fade object,
  same as tonight's earlier investigation. `snap_theme_forward`'s `.stop()` on this is what makes
  "fade was Running at close time" not strand anything by itself, confirmed live in this session.
- **`ThemeItem._last_leave_pos` / `_last_leave_was_synthetic`** (title_bar.py) — per-widget, used
  only by the spurious-enter/blur-grab-synthetic-leave guards inside `enterEvent`/`leaveEvent`
  themselves. Not consulted by anything outside those two methods.
- **`_swatch_leave_backstop_timer` / `_check_swatch_still_hovered`** — the 2026-08-03 jitter-guard
  backstop (separate investigation, same day). **This is the only cursor-position POLL anywhere in
  the hover system**, and it answers a different question in the opposite direction: it is armed
  ONLY while `_is_hover_active` is already `True` (line 2194, `_mark_theme_applied`'s True↔False
  transition arms/disarms it), and exists to catch the cursor LEAVING a swatch while a preview is
  already showing (a corrective backstop for a suppressed leaveEvent). It is structurally incapable
  of ever firing "cursor is already on a swatch, panel just became hoverable" — by the time it could
  run, no hover is active yet, so it isn't armed.

---

## Step 5 (answered first, since it settles the shape of the whole investigation) — does a
"settled, now check the cursor" mechanism exist?

**No — confirmed by exhaustive grep, not assumed.** Every `QCursor.pos()` / `mapFromGlobal` /
`underMouse()` / `childAt()` call site in the relevant files:

| Site | Purpose |
|---|---|
| `title_bar.py:114` (`ThemeItem.enterEvent`) | Compare current pos against `_last_leave_pos` to detect the spurious-restyle-cascade Enter |
| `title_bar.py:161` (`ThemeItem.leaveEvent`) | Record the leave position for the above check |
| `theme_manager.py:2018` (`_on_theme_hovered`) | Record `_last_swatch_pos` at genuine-enter time, for `_on_themes_tab_left`'s later leave-classification |
| `theme_manager.py:2140/2155` (`_on_themes_tab_left`) | Classify a leave as real vs. blur-grab-synthetic |
| `theme_manager.py:2216` (`_check_swatch_still_hovered`) | The jitter backstop — detects the cursor LEAVING an already-hovered swatch, armed only while a hover is already active |

None of these fire on panel-open-settle, and none of them ask "what widget is the cursor over right
now" as a way to START a preview — they all either react to an event that already fired, or check
containment to decide whether an already-active hover should END. **The mechanism the task's framing
assumes should exist ("open the panel; once settled, evaluate where the cursor currently is; if it's
over a swatch, trigger that swatch's hover-preview") does not exist in the current code at all.** It
is not being skipped or short-circuited by leftover state — there was never a code path that does
this, for any case, including case 2.

---

## Steps 2-4 — why case 2 "succeeds" and case 1 "fails": the same absence, two outcomes

**Case 2's mechanism, precisely:** `settings_panel.show()` (`panels.py:740`) makes the panel, and
every `ThemeItem` swatch inside it (built once at startup —
`main_window_builders.py:701`/`718`, never rebuilt per open), visible for the first time this
session. If the cursor is later moved ONTO a swatch (the ordinary, most common real-world gesture —
open the panel, THEN move the mouse to browse themes), Qt's normal mouse-tracking machinery delivers
a completely ordinary, real `enterEvent` the instant the cursor crosses the widget's boundary. This
is case 2 working exactly as intended, via the exact same `enterEvent` path as every other hover in
the app — nothing special about it.

**Case 1's mechanism, precisely:** the cursor was ALREADY resting over the swatch's screen position
*before* the panel (and its already-visible-in-widget-tree-but-hidden-window `ThemeItem` children)
became hoverable again. For Qt to trigger a preview here, something would need to either (a) hit-test
the cursor against the newly-shown widget tree and manufacture a synthetic Enter, or (b) have an
explicit poll checking cursor-vs-swatch-rect at settle time. Per Step 5, **(b) does not exist**, and
(a) is NOT something Qt guarantees — a widget/window becoming visible under a stationary cursor does
not, by Qt's own event model, automatically synthesize an `Enter` event unless the platform's own
input-event delivery independently re-evaluates hover state on that stacking change (which is
compositor-dependent, not a Qt-level guarantee). **Case 1 is not "stale state blocking a working
mechanism" — it is the complete absence of any mechanism, on the specific side of the platform's own
non-deterministic behavior where no fresh Enter gets redelivered.**

This directly explains why Pryme reports the SAME gesture (cursor resting on a swatch, panel
re-opens) producing DIFFERENT outcomes across attempts: whether KDE/Wayland's compositor happens to
re-deliver an Enter on that particular stacking-order change is not something this codebase (or Qt
itself) controls or promises — it is exactly the same class of platform inconsistency already
documented twice elsewhere in this file (the spurious-enterEvent-on-restyle-cascade bug, and the
`QComboBox` popup pseudo-state bug in CLAUDE.md, both confirmed live on this exact desktop). Case 1 is
reliably reproducible in Pryme's testing likely because the specific gesture he used (close via Esc
while genuinely still hovering, cursor never moving even a pixel, then reopen) is precisely the
scenario where the compositor has the LEAST reason to re-evaluate hit-testing — no cursor motion
event ever arrives to trigger a re-check. Case 2, in ordinary use, almost always involves the cursor
MOVING after the panel opens (browsing behavior), which produces a normal, guaranteed `enterEvent`
regardless of platform quirks — so case 2's apparent reliability is coincidental to how people
naturally use the panel, not evidence of a working mechanism.

**This is confirmed to be a genuinely missing mechanism, not a bug in existing code that regressed.**
Nothing in `git log` history for this file suggests a "check cursor on settle" step ever existed and
was removed — the hover system has always been purely event-driven, back to its original design.

---

## Case 3 — investigated live, mechanism identified but NOT reproduced; explicitly flagged as open

Case 3's described symptom (a stale, previously-hovered-but-never-fully-shown theme briefly applies
on reopen before correcting) most closely matches `_pending_panel_sheet`'s stash mechanism: this dict
is written **unconditionally on every `_apply_stylesheets` call, last-write-wins**, and
`apply_pending_panel_sheet` blindly applies whatever it holds to a panel right before that panel's
`show()`. If the interrupted hover call's `_apply_stylesheets` were to complete and stash the hover
theme, and the corrective unhover/snapback call's `_apply_stylesheets` were to NOT run (or run and
fail to re-stash) before the panel is hidden, the stash would be left holding the wrong theme,
producing exactly the reported symptom on the next open.

**This session traced three distinct timing windows for "interrupt the hover, then close," live,
with direct instrumentation on `_pending_panel_sheet`'s contents after every write, and in every
window tried, the unhover/snapback's own `_apply_stylesheets` call ran to completion and correctly
re-stashed `_pending_panel_sheet['settings_panel']` back to the active theme before the panel was
ever hidden:**

1. **Hover interrupted before its 80ms debounce even fires** (`_apply_stylesheets` for the hover
   never runs at all) — trivially correct, nothing to go wrong.
2. **Hover's `_on_theme_changed` call itself deferred via `PanelManager.call_when_panels_settled`**
   (panel-open `blur_animation` still running at hover time) — the deferred hover call is correctly
   superseded by the unhover's own deferred call via tonight's earlier `coalesce_key="theme_change"`
   fix, so the hover's `_apply_stylesheets` **never runs at all** in this window either.
3. **Hover's `_apply_stylesheets` runs synchronously to completion** (panel-open animation already
   settled), genuinely stashing the hover theme, **then** the fade is closed while `_fade_anim.state()
   == Running` (confirmed via direct polling, genuinely mid-fade) — `_close_settings_flow`'s
   unconditional `_on_theme_unhovered()` → `snap_theme_forward()` → the unhover's own
   `_on_theme_changed`/`_apply_stylesheets` call runs synchronously and re-stashes correctly before
   `settings_panel.hide()` is ever reached.

In all three, `_pending_panel_sheet['settings_panel']` was confirmed (by direct identification
against `get_settings_stylesheet(theme)`'s known output for each candidate theme) to read back
correctly as the active theme by the time the panel was reopened, at every polling granularity tried
(immediately after `_open_settings_flow()` returns, after one `processEvents()`, after 50ms, after
full settle).

**This does not mean case 3 doesn't exist — Pryme's live report (screenshots, real usage) is ground
truth per this project's own standing rule, and a synthetic harness failing to reproduce a live
symptom is evidence of a harness gap, not evidence the bug is imaginary.** The most likely candidates
for what this session's script could not recreate:

- **Genuine overlapping asynchronous work this session's serialized `pump()`-per-step script cannot
  interleave the way real wall-clock, real-compositor timing does** — in particular, the
  transport-bar blur grab's own ~200ms hide/show cycle (confirmed running throughout this session's
  script too, via `[TIMER-TRACE] refresh_dirty` lines) synthesizes its own `leaveEvent`/`enterEvent`
  pairs on `ThemeItem` widgets independent of genuine mouse movement — a real close arriving in the
  narrow window between one of THOSE synthetic events and the next could plausibly interact with the
  stash differently than this script's clean, single-threaded event ordering ever produced.
- **A real mouse gesture involves continuous small position deltas** (a "sweep" across several
  swatches before settling, which `_on_theme_hovered`'s debounce is explicitly built to coalesce) —
  this session tested a single clean `enterEvent` per case, not a rapid multi-swatch sweep landing at
  an awkward moment relative to the close click.
- **This session's script cannot drive a real OS-level cursor at all** (`QCursor.setPos()` is a
  documented no-op on this Wayland session — confirmed directly: cursor position read back as
  `(0, 0)` after every attempted `setPos()` call) — every case-3 attempt here delivered a REAL
  `QEnterEvent` directly to the widget's `enterEvent` method (which runs the actual production guard
  logic), but this cannot recreate whatever a genuine mouse-driven Enter/Leave SEQUENCE looks like
  under real compositor timing, only a single isolated event at a chosen instant.

**Root-causing case 3's exact live transient precisely would require live instrumentation on the
running app (per this project's own established practice for this bug class — see the
swatch-leave-jitter investigations' own methodology) rather than a synthetic harness. That is
flagged here as the next step, not performed in this session.**

---

## Is this related to tonight's mechanism-C fix (`Report_260803_snapback_stuck_theme_fix.md`)?

**Partially related, but NOT the same bug, and NOT fixed by that work already landing.**

- The `_panels_settled_waiters` FIFO/coalescing mechanism DOES matter here: in one of the three
  timing windows traced for case 3 above (hover call deferred because the panel-open animation was
  still running), tonight's earlier `coalesce_key="theme_change"` fix is what correctly prevented the
  hover's stale call from surviving — confirmed live, `_on_theme_changed(theme_name='Rose Code',
  hover=True, ...) ENTRY any_animating=True` followed by the unhover's own call correctly replacing
  it in the queue. **Without tonight's earlier fix, this specific timing window would very likely
  have reproduced a version of case 3** (the hover's stale call surviving to apply after the correct
  one) — but this is a hypothesis about what the OLD code would have done, not a live-confirmed
  before/after on this exact scenario, and is not the same as claiming today's residual case-3 reports
  ARE this mechanism.
- Cases 1 and 2 are **entirely unrelated** to mechanism C or `_panels_settled_waiters` — they involve
  no `_on_theme_changed` call being deferred or queued at all; the failure (case 1) is that no hover
  call is ever even ATTEMPTED, because no `enterEvent` ever fires. Mechanism C only matters once a
  hover call exists to be queued.
- **`_pending_panel_sheet`** (the case-3 candidate mechanism examined in detail above) is a
  completely separate stash from `_panels_settled_waiters`, written and read by different methods,
  and was not touched by tonight's earlier fix at all.

**Conclusion: cases 1/2 are a single, independent, previously-undiagnosed structural gap (no
cursor-check-on-settle mechanism exists, full stop) — unrelated to mechanism C. Case 3 remains open,
plausibly touches the SAME `_panels_settled_waiters` queue tonight's earlier fix already improved for
one sub-window, but is not confirmed to be fully explained or resolved by that fix, and was not
reproduced live in this session to confirm or rule out further.**

---

## What this investigation does NOT do (explicitly, per the task)

No fix is proposed. In particular, a timer-based backstop (polling cursor-vs-swatch-rect on some
cadence after panel-open-settle, structurally similar to `_check_swatch_still_hovered` but for the
opposite direction) is the obvious next design candidate given the confirmed absence of any such
mechanism today — but per the task's explicit instruction, that design is deliberately not attempted
here. Case 3 in particular needs live reproduction before any fix targeting it could be trusted; per
this project's own standing rule (`_do_fade_with_slider_animation`'s pytest-vs-harness lesson earlier
tonight, and the general "verify once is not verified" lesson), a fix designed against an
unreproduced symptom risks fixing the wrong thing.
