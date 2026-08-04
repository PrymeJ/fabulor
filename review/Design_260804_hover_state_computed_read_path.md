# Design: replace stored hover-state with a computed, live-derived read path

**Date:** 2026-08-04  **Branch:** `investigate/restyle-cost-depth-and-narrowing`  **Status:**
Design approved. Migration is staged (see §6) — this document covers the full design; each step is
implemented and verified separately, not in one pass.

## Context

Tonight's chain of fixes (`get_current_theme()` confinement gap, two reactive corrections to
`clear_stale_hover_state()`) all patched the same underlying defect: `_is_hover_active` and
`_active_display_theme_internal` are **stored, mutable fields** whose correctness depends on a
`leaveEvent` being correctly delivered and classified. Tonight alone, that exit contract failed via
at least three distinct mechanisms (jitter-guard boundary-crossing misclassification, blur-grab
synthetic-leave suppression, panel-transition synthetic-leave suppression). Every fix built
tonight — `check_cursor_on_settle`, the `_swatch_leave_backstop_timer`, `clear_stale_hover_state` —
tries to catch a failure of this contract *after the fact*. None removes the failure mode, because
the failure mode is structural: entering hover-state is one line; exiting it depends on correctly
recognizing a Qt event with multiple known ways to misfire, on THIS specific app/compositor
(documented repeatedly in CLAUDE.md as a live, recurring class of bug on this codebase).

This design replaces "is hover active, and what theme" as **stored state that can go stale** with
"is hover active, and what theme" as a **question re-asked from scratch on every read**, from facts
that cannot go stale because they are read live from Qt/the OS at the moment of the question:
is Settings visible, is the Themes tab current, is the cursor over a specific swatch right now. If
any of the three is false, there is no hover to report — full stop, no flag to have forgotten to
clear.

**Scope boundary, confirmed by direct code reading, not assumed:** the fade/animation triggering
logic (`_on_theme_changed`'s branches, the 750ms/200ms fade durations, the snapback trigger) is
explicitly out of scope and this design does not touch it. Critically, **this scope boundary is
achievable cleanly** — the one place `_is_hover_active`/`_active_display_theme_internal` are read
*inside* the fade pipeline itself (`_on_theme_changed`'s no-op guard, line ~963-965) is confirmed to
be a **write-side dedup check** ("was this exact `(theme_name, hover)` pair already the last thing
actually painted, so `_apply_stylesheets` can be skipped"), not a "what should an external reader be
told" query. That guard's own history (line ~1169, ~1261: `_is_hover_active` was tried as a
"hover is live right now" signal for a *different* purpose in 2026-07-21/28, found wrong, and
removed — it now only means "what was last painted") already proves the fade pipeline does not, and
must not, treat this pair as a live hover-truth signal. This is the fact that makes a clean split
possible: **the two stored fields stay exactly as they are, privately, for the fade pipeline's own
dedup bookkeeping — untouched by this design — while every external reader is redirected to a new,
separate, computed method that never touches them.**

---

## 1. The new computed read: `get_displayed_theme()`

```python
def get_displayed_theme(self):
    """Live-computed answer to 'what theme should be shown right now', re-derived from
    scratch on every call. Returns a raw theme name (str) or a cover-derived theme
    (dict) — same return shape get_active_theme() has always returned.

    No stored hover-active flag is read or written here. The three facts below are
    read fresh from Qt/the OS on every call; if any is false, there is no live preview
    and the answer is simply the real active theme (or the live cover theme, if one is
    active) — there is no 'stuck' state to reach, because there is no state.
    """
    settings_panel = getattr(self.main_window, 'settings_panel', None)
    tabs = getattr(self.main_window, 'tabs', None)
    swatch_box = getattr(self, 'swatch_box', None)

    if (settings_panel is not None and settings_panel.isVisible()
            and tabs is not None and tabs.currentIndex() == 0
            and swatch_box is not None and swatch_box.isVisible()):
        local = swatch_box.mapFromGlobal(QCursor.pos())
        if swatch_box.rect().contains(local):
            target = swatch_box.childAt(local)
            if isinstance(target, ThemeItem):
                if target is self.cover_pool_btn:
                    if self._cover_theme_active and self._cover_theme is not None:
                        return self._cover_theme
                    # cover-pool entry hovered but no cover theme exists -- falls
                    # through to the real active theme below, same as today's
                    # _on_cover_pool_btn_hovered early-return when _cover_theme is None
                else:
                    return target.theme_name

    if self._cover_theme_active and self._cover_theme is not None:
        return self._cover_theme
    return self._current_theme_name
```

`get_active_theme()` and `get_current_theme()` become thin wrappers:

```python
def get_active_theme(self):
    return self.get_displayed_theme()

def get_current_theme(self) -> dict:
    from ..themes import _resolve_theme
    return _resolve_theme(self.get_displayed_theme())
```

Both existing names are kept (external callers do not change), but neither reads or writes
`_is_hover_active`/`_active_display_theme_internal` anywhere in this chain. `get_displayed_theme()`
is the single source of truth; the other two are pure formatting wrappers over it, matching
tonight's own `_resolve_theme`-wrapping precedent exactly (no new pattern introduced).

This reuses the **exact same geometry-check shape already proven live tonight** in
`check_cursor_on_settle()` and the `SWATCH-LEAVE-SUSPECT` probe:
`mapFromGlobal` → `rect().contains()` → `childAt()` → `isinstance(..., ThemeItem)`. No delta
comparison between two time-adjacent samples anywhere — a single absolute check against live
geometry, which is precisely the property that has kept those two mechanisms clear of the two
2026-07-28 jitter-guard regressions (both of which failed by comparing samples across time, not by
using absolute containment).

### The one case needing explicit handling: the cover-pool entry

`check_cursor_on_settle()` only triggers a preview (routes through `.hovered.emit(...)`, which
dispatches correctly regardless of which handler is wired). A pure read, by contrast, must resolve
what theme the cover-pool entry actually represents itself — verified by reading
`_on_cover_pool_btn_hovered` directly: it previews `self._cover_theme` if one exists, and is a no-op
otherwise. The code above mirrors that exactly: hovering the cover-pool button only counts as "a
preview is showing" if `_cover_theme` actually exists; otherwise it falls through to the real active
theme, matching today's behavior when hovering that button with no cover theme available.

---

## 2. Cost

Per call: `settings_panel.isVisible()` (1 virtual call), `tabs.currentIndex()` (1 virtual call),
`swatch_box.isVisible()` (1 virtual call) — all three O(1) Qt property reads. If Settings isn't
open or the Themes tab isn't current (the overwhelming majority of every call site's real-world
calling context — Library refresh, Sleep/Speed ramp paint, the backdrop frost, book-load's
`_set_bg_suppressed`), the function returns after exactly these three checks, **without ever
calling `mapFromGlobal`/`rect().contains()`/`childAt()`** — the geometry work only runs on the rare
path where Settings is actually open on the Themes tab. This is the same short-circuit shape
`check_cursor_on_settle()` already uses (visibility checks before geometry checks), not a new cost
profile.

When the geometry path does run (Settings open, Themes tab active — the only case where the
distinction between "hovering" and "not" can matter at all): `mapFromGlobal` is a coordinate
transform, `rect().contains()` is a bounds check, `childAt()` is a bounded hit-test over
`swatch_box`'s ~60 children — the exact same three calls `check_cursor_on_settle()` already
performs once per Settings-panel open today, with a documented negligible cost. Nothing here calls
`_apply_stylesheets` or triggers any restyle — this function only ANSWERS a question, it never
paints anything.

**Calling-frequency check across all 9 confirmed call sites (see §5) — the red flag the task asked
me to check for, explicitly:** none of the 9 call sites are in a per-frame or tight-loop context.
The two most frequent are `sleep_timer.py:188`/`speed_controls.py:271`
(`_apply_preset_ramp_colors`, called on Sleep/Speed's own state-change UI actions — user-paced
button clicks, not a timer) and `transport_bar_blur.py:575` (the panel-backdrop frost wash, called
once per blur-grab tick while a panel is open — measured elsewhere in this codebase at roughly
15 ticks/sec while blur is enabled and a panel is visible). **15/sec is the one call-frequency worth
naming explicitly**, but the visibility-short-circuit above means it costs three cheap property
reads unless Settings itself happens to be the open panel with its Themes tab current — and even
then, the geometry check itself is the same cost `check_cursor_on_settle` already pays once per
panel-open with no reported cost concern. No call site approaches anything resembling a hot loop.

---

## 3. Disposition of the five mechanisms

| Mechanism | Disposition | Reason |
|---|---|---|
| `_is_hover_active` | **KEEP, unchanged, private** | Confirmed by direct code reading: read by `_on_theme_changed`'s no-op guard (line ~963-965) as write-side dedup ("was this exact pair already painted"), by `_mark_theme_applied` (its sole writer), and by the two fallback branches (`snap_theme_forward`, `complete_main_fade`) that re-apply "whatever was last painted." All three are fade-pipeline-internal and explicitly out of scope. This field simply stops being read by anything OUTSIDE `theme_manager.py` — its external "leaks" are closed not by fixing the field, but by no external caller ever touching it again. |
| `_active_display_theme_internal` | **KEEP, unchanged, private** | Same reasoning as above — it is the fade pipeline's own "what did we last paint" bookkeeping, read by the identical set of internal-only sites. |
| `check_cursor_on_settle` | **DELETE** | Its entire job — detect a cursor already resting on a swatch when Settings finishes opening, and trigger a preview — is now answered for free by `get_displayed_theme()` on the very next read of "what theme is shown," with no need for a separate settle-triggered check. Confirmed no other responsibility: its only side effect is `target.hovered.emit(...)`, which exists solely to make the swatch's OWN visual preview mechanism trigger — under the read-computed design, no caller needs a *push* notification that a preview should start, since every reader re-asks the live question themselves. See the confirmed-safe check below (native `:hover` QSS). |
| `_check_swatch_still_hovered` (backstop timer) | **KEEP, unchanged, for a reason unrelated to the read-path problem** | Confirmed by direct reading: its job is to re-trigger the SNAPBACK FADE (`_on_theme_unhovered()`) when a genuine leave was wrongly suppressed by the jitter guard. That is a fade-triggering concern — explicitly out of scope to touch — not a "what should a reader see" concern. Even under the new design, if a real mouse-out is misclassified and suppressed, the snapback fade still needs *something* to notice and correct the VISIBLE preview (the swatch's own highlighted/underlined state, the fade overlay) — reads becoming live-computed does not un-suppress a leaveEvent or retrigger a fade. This mechanism's reason to exist is completely orthogonal to the bug this redesign fixes. |
| `clear_stale_hover_state` | **DELETE** | Its entire reason for existing, confirmed by its own docstring history across two same-day corrections: "a LATER `get_current_theme()`/`get_active_theme()` call keeps returning the abandoned hover theme." That is exactly, and only, the read-path bug this design eliminates by construction — under `get_displayed_theme()`, there is no stored value to go stale, so there is nothing for a "clear the stale value" method to do. Its two corrective side effects (repainting Sleep/Speed's ramp, repainting the main window) were themselves reactive patches for the fact that SOME surfaces cache a painted result rather than re-deriving it on every frame — seepage from the same root problem this design solves at the read layer. Once every reader (Library's delegate colors, the ramps, the frost, the main window's own `_apply_stylesheets`-driven paint) calls `get_displayed_theme()`/`get_current_theme()` at the moment it actually needs to know, none of them can be "already painted wrong" in a way this method exists to fix. |

### Checked, not left as an open question: the swatch's own visual hover feedback

The task's own instruction was to flag entanglement rather than assume it away — checked directly
against `themes.py` rather than left open. `QPushButton#theme_item:hover` (themes.py:3730-3734) is a
**plain native Qt pseudo-state selector** — Qt applies `color`/`background` the instant the cursor is
geometrically over the widget, with zero dependency on any signal, property, or the `hovered.emit(...)`
call `check_cursor_on_settle`/a real `enterEvent` fires. The swatch visually looks hovered the moment
the cursor rests on it, regardless of whether `check_cursor_on_settle` exists.

This confirms `check_cursor_on_settle`'s deletion is safe with respect to the swatch's own visual
feedback: the only thing it currently adds beyond native Qt behavior is triggering the APP-WIDE
theme-preview pipeline (repainting Settings/main-window/etc. to reflect the hovered theme) for the
specific case of a cursor already resting on a swatch when Settings finishes opening — and that
becomes unnecessary once every reader re-asks `get_displayed_theme()` live instead of depending on a
push notification. **Confirmed safe to delete, not merely assumed.**

---

## 4. Disposition of the confinement fix (July 21/22, and tonight's `get_current_theme()` redefinition)

**Coexists, does not need adjustment, and this redesign supersedes only the READ half of tonight's
most recent commit — not the July 21/22 fix at all.**

- **July 21/22 confinement fix** (discarding hover-flagged `_pending_fade_call` stashes at the three
  drain sites): untouched. That fix protects `_schedule_deferred_restyle`/`theme_applied` from ever
  being reached by an abandoned hover-flagged stash — a write-side concern about which panels get
  restyled from a REPLAYED call, nothing to do with what a READER is told. This redesign does not
  change `_on_theme_changed`, `_pending_fade_call`, or any of the three drain sites.
- **Tonight's `get_current_theme()` redefinition** (`_resolve_theme(self.get_active_theme())`):
  **directly superseded** — this design replaces what `get_active_theme()` itself does internally
  (from reading two stored fields to computing live), while keeping `get_current_theme()`'s own
  one-line delegation exactly as committed. No second change needed to `get_current_theme()`
  itself; only `get_active_theme()`'s body changes.
- **The two same-day reactive corrections** (`clear_stale_hover_state`'s ramp-repaint and
  main-window-repaint additions): **deleted along with the method itself** — see §3. There is
  nothing left for them to correct.

---

## 5. All confirmed runtime call sites — 9, not 7 (2 more found by this design's own re-audit)

The original tonight's audit found 7. Re-grepping `get_current_theme()`/`get_active_theme()` for
this design surfaced **two more real, runtime call sites** — flagged explicitly rather than
silently folded in, per the task's own standing rule that an un-observed leak is still a leak:

| # | Site | Confirmed in original audit? | Behavior under `get_displayed_theme()` |
|---|---|---|---|
| 1 | `library.py:482` `_resolve_theme_colors` | Yes | Correct, no call-site change — same `.get(...)`-style access on the resolved dict from `get_current_theme()`. |
| 2 | `library.py:1261` `_on_view_mode_changed` (via `_resolve_theme_colors`) | Yes | Same as #1. |
| 3 | `library.py:1556` `_refresh_search_match_state` | Yes | Correct, no change. |
| 4 | `transport_bar_blur.py:575` frost wash | Yes | Correct, no change. |
| 5 | `sleep_timer.py:188` ramp colors | Yes | Correct, no change. |
| 6 | `speed_controls.py:271` ramp colors | Yes | Correct, no change. |
| 7 | `app.py:875` `_reload_excluded_books` | Yes | Correct, no change. |
| 8 | **`app.py:2630` `_on_speed_right_clicked` shimmer** | Yes (listed in task) | Correct, no change. |
| 9 | **`app.py:221` `restyle_for_backdrop_change`** (`tm.apply_panel_alpha_pass(tm.get_active_theme())`) | **No — newly found** | Calls `get_active_theme()` directly (not `get_current_theme()`). Under the redesign this returns the live-computed answer instead of the stored field — correct, no call-site change needed; this was already routed through the "sanctioned" accessor, just never audited as a distinct site before. |
| 10 | **`app.py:1509` `_set_bg_suppressed`** (`self.theme_manager.get_active_theme()`) | **No — newly found, and this is the ORIGINAL bypass the July 20 audit was built to close** | Fires on every book-load/empty-state transition. Correct under the redesign with no call-site change. **CORRECTED (2026-08-04, Pryme) — see the note directly below the table: this site is NOT reachable mid-hover, contrary to what this row originally claimed.** |

**Every site: correct with zero call-site changes**, because both public accessor names and their
return-type contracts are preserved exactly. The two newly-found sites (#9, #10) do not represent a
gap in this design — they were already calling the "sanctioned" `get_active_theme()`, which becomes
correct automatically once its internals change. They are surfaced here because failing to name them
would repeat tonight's exact mistake (auditing to a fixed list instead of re-grepping fresh).

**CORRECTION (2026-08-04):** the original row #10 above, and §6 step 3's inclusion of "a book-load
while hovering" as one of four scenarios to live-verify, were both WRONG — Pryme corrected this
directly. `_set_bg_suppressed` is called only from `library_controller.py`'s `apply_library_state`
(three call sites, all inside it — confirmed by grep, no other caller anywhere in the codebase), and
`apply_library_state` only runs as part of the Library-selection/empty-state flow, which only
executes while the Library panel is open. `PanelManager.is_overlay_open_or_committed()` (the
standing one-overlay-at-a-time gate documented in CLAUDE.md) means Library and Settings/Themes can
never be open simultaneously — a book can only be loaded from Library, and a hover-preview can only
happen while Settings/Themes is open. These two states are mutually exclusive by construction, so
"book-load while hovering" was never a real, reachable scenario — not rare, not edge-case, actually
IMPOSSIBLE given this app's panel-exclusivity architecture. This was an error in the original
design-doc audit (asserted as fact without checking the gate that rules it out), not a nuance or a
timing detail. §6 step 3's scenario list is corrected accordingly — see the note there.

---

## 6. Migration sequencing

**Recommendation: build `get_displayed_theme()` alongside the existing fields first, verify
agreement, THEN redirect the two public accessors, THEN delete the two dead mechanisms — never a
single big-bang pass.** Given tonight's own track record on this exact code (two same-day reactive
corrections, each one verified only after being caught live rather than in advance), a staged rollout
with an explicit agreement-check step is the only sequencing that fits the evidence of what actually
goes wrong here.

1. **Add `get_displayed_theme()` as a new, additional method** — do not yet change
   `get_active_theme()`/`get_current_theme()`. At this point it exists but nothing calls it.
2. **Add a temporary, log-only agreement check** inside `get_active_theme()` (its EXISTING body,
   unchanged): compute `get_displayed_theme()`'s answer too, and log a warning if the two disagree,
   without changing which one is actually returned. This is the same "verify before trusting"
   discipline this project's CLAUDE.md already mandates elsewhere (e.g. the `SWATCH-LEAVE-SUSPECT`
   probe) — it turns "does the new logic actually agree with the old one in real, live use" from an
   assumption into a measured fact, across real usage sessions, before anything depends on it.
3. **Live-verify the agreement check across real sessions** — specifically targeting: a genuine
   hover with the cursor resting still, a hover interrupted mid-fade, and the `[SWATCH-LEAVE-SUSPECT]`
   scenario. **CORRECTED (2026-08-04, Pryme):** the fourth scenario originally listed here —
   "a book-load while hovering (site #10 above, the highest-value target)" — is not a real scenario.
   `_set_bg_suppressed` (site #10) only runs from the Library-selection/empty-state flow, which can
   only execute while the Library panel is open; `is_overlay_open_or_committed()`'s one-overlay-at-
   a-time gate means Settings/Themes (required for any hover) can never be open at the same time.
   Book-load-while-hovering is structurally impossible in this app, not merely untested — drop it
   from the verification checklist entirely rather than treating a zero-hit search for it as
   evidence of anything. Zero disagreements over a real session, across the three scenarios that ARE
   real, is the bar — matching this project's own standing rule that a single clean pass is evidence,
   not proof, so this step should span more than one sitting if anything looks borderline.
4. **Only after step 3 shows sustained agreement**, redirect `get_active_theme()`'s body to return
   `get_displayed_theme()`'s answer directly (remove the log-only shadow check), and confirm
   `get_current_theme()`'s existing one-line delegation still needs no change.
5. **Delete `clear_stale_hover_state()` and its two call sites** (`PanelManager._on_settings_hidden`)
   — safe once step 4 has landed and been observed for a period, since nothing can be "stuck" anymore
   for it to correct.
6. **Delete `check_cursor_on_settle()` and its wiring** (`_on_settings_slide_finished`) — confirmed
   safe already (§3: `ThemeItem` has native `:hover` QSS styling independent of the `hovered` signal,
   checked directly against `themes.py`, not left open). Sequenced after step 5 anyway, matching this
   design's general bias toward observing each change independently rather than bundling deletions.
7. **`_is_hover_active`/`_active_display_theme_internal`/`_check_swatch_still_hovered` are never
   touched** at any step — they remain exactly as they are today, serving only the fade pipeline's
   internal dedup and trigger-correction needs.

This sequencing means the risky part (does the live-computed answer actually match reality in every
case tonight's bugs exposed) is verified BEFORE anything is deleted or redirected, and the two
deletions happen last and independently of each other — so a problem discovered at step 6 does not
require unwinding step 5, and vice versa.

---

## 7. Step-3 live-verification finding: Esc-dismiss-while-hovering disagrees, and does so for a real, non-incidental reason

Found live (2026-08-04), first real `[SHADOW-CHECK]` disagreement since the instrumentation shipped:

```
old_path='Rebma' new_path='Not the Only Fruit' _is_hover_active=False
_active_display_theme_internal='Rebma' _current_theme_name='Rebma'
_cover_theme_active=False settings_panel.isVisible()=True tabs.currentIndex()=0
```

Repro: Settings open, Themes tab active, cursor resting on the "Not the Only Fruit" swatch (a
genuine live hover, not a click), then press **Esc**. No wrong behavior was visible in the app —
expected, since nothing reads `get_displayed_theme()` yet; this is exactly what the shadow check
exists to surface before it could matter.

**Root cause, confirmed by reading `PanelManager._close_settings_flow` (`panels.py:1399-1421`), not
assumed:** Esc routes to `_close_settings_flow`, which calls
`self.main_window.theme_manager._on_theme_unhovered()` and `.snap_theme_forward()`
**synchronously, at the very top of the method** — before `settings_panel_animation.start()` is
even reached, several lines later, and long before the animation's `finished` signal fires
`_on_settings_hidden`. So there is a real, non-zero window — from the Esc keypress until the slide-
out animation actually completes — where:

- The OLD path (`_is_hover_active`/`_active_display_theme_internal`) has already committed to "hover
  is over, reverted to the real active theme" — correct and intentional; this is the snapback the
  confinement fix depends on.
- `get_displayed_theme()` still sees `settings_panel.isVisible() == True`, `tabs.currentIndex() == 0`,
  and the cursor still geometrically resting on the same swatch (nothing moved it) — so it still,
  correctly by ITS OWN logic, reports "currently hovering this swatch."

**This is not a bug in either path individually — it is two different questions ("has the fade
pipeline reverted yet" vs. "is the cursor geometrically on a swatch right now, with the panel still
visible") that are both being answered honestly, at a moment where their answers have genuinely
diverged.** Neither number is wrong; they disagree because the close flow reverts application state
strictly before the widgets it's closing report themselves as gone.

**Why this matters for step 4, and must not be patched now:** if `get_active_theme()` were
redirected to return `get_displayed_theme()`'s answer as-is (step 4), this exact sequence — Esc
while genuinely hovering — would make any caller reading the active theme during that window
briefly see the ABANDONED hover theme instead of the reverted one, until `settings_panel.isVisible()`
actually flips to `False`. That is a real, user-visible regression risk specific to the Esc/dismiss
path, not a flaw in the geometry-check design itself. Fixing it would mean either (a) having
`get_displayed_theme()` also consult something that reflects "is a close/dismiss already committed,"
which reintroduces a form of stored transitional state this design set out to eliminate, or (b)
having the close flow hide/mark the panel not-a-hover-target synchronously, before or alongside the
snapback call, so `get_displayed_theme()`'s geometry check stops seeing a live target in the same
tick. Both are step-4-or-later design decisions, not something to patch reactively inside the
still-shadow-only step 2 instrumentation — consistent with the task's scope boundary (fade/animation
triggering logic is out of scope for this design) and this project's standing discipline against
patching around an undiagnosed mechanism instead of naming it precisely.

**Disposition:** logged here as the first confirmed real disagreement case, for step 3's live-
verification record and for whoever authors step 4 to resolve explicitly (most likely candidate:
have `_close_settings_flow` snapshot/clear the panel's hover-eligibility before or atomically with
calling `_on_theme_unhovered()`, so both paths agree at the same instant) rather than silently. Not
yet fixed; not yet blocking anything, since step 2's shadow check is observer-only by construction.

### 7b. Second occurrence, different trigger — INITIAL CAUSAL CLAIM BELOW WAS WRONG, corrected after reading actual log timestamps

Found later the same day, no Esc/dismiss involved: select a theme (right-click, `_on_theme_
right_clicked` — `_current_theme_name` set to "The Color Purple"), then sweep the cursor across
several different swatches ("Blood Meridian", then "Dorian Grey"). Log (file timestamps, not just
the terminal mirror — this distinction is what corrected the analysis below):

```
01:10:44,287  new_path='Blood Meridian'  _is_hover_active=False
01:10:44,455  new_path='Blood Meridian'  _is_hover_active=False
01:10:44,461  new_path='Blood Meridian'  _is_hover_active=False
01:10:46,834  new_path='Dorian Grey'     _is_hover_active=False
01:10:47,004  new_path='Dorian Grey'     _is_hover_active=False
01:10:47,011  new_path='Dorian Grey'     _is_hover_active=False
```

**My first pass (below the strikethrough-in-spirit paragraph) claimed this was the same ordering
race as §7 — `_on_theme_unhovered()`'s revert outrunning the cursor's actual departure from the
swatch. That claim was retracted after actually reading the timestamps rather than just the
theme-name pattern.** ~~"same root cause as §7, reached by a different trigger... the geometry
check can still find the cursor resolving to a ThemeItem for one or more calls immediately after
the revert, until the cursor has moved far enough."~~ That explanation requires the disagreement
window to be short (one Qt event-loop tick, milliseconds) — it does not fit a window spanning
**174ms** for one swatch and **177ms** for the next, nor three repeated identical disagreements
each separated by tens to hundreds of ms while the cursor was (per the "swept several swatches"
description) still moving, not resting.

**Corrected explanation, checked against `_HOVER_DEBOUNCE_MS = 80` (theme_manager.py:108):**
`_on_theme_hovered` — the entry point real `ThemeItem.enterEvent`s call — does not set
`_is_hover_active` itself; it only restarts an 80ms debounce timer, and only the debounce's
eventual firing (`_fire_pending_hover` → `_on_theme_changed(..., hover=True)` → `_mark_theme_
applied`) sets `_is_hover_active = True`. During a sweep across several swatches, each new
`enterEvent` RESTARTS that same timer — so if the cursor keeps moving (or pauses on each swatch for
less than 80ms), `_is_hover_active` can legitimately stay `False` for the entire sweep, because
nothing ever "settles" long enough to commit. `get_displayed_theme()` has no debounce at all — it
answers "what is under the cursor at this exact instant," which during a sweep is a **different
question** than "what has the debounced fade pipeline decided to commit to," not a delayed version
of the same answer.

**This is not the §7 race (state-revert-vs-cursor-position ordering) — it is the debounce itself
producing a real, expected divergence between an instantaneous read and a coalesced one.** This
matters for step 4 in a different way than §7 does: it is not a bug to fix by re-ordering two
events, it is a property of what `get_displayed_theme()` fundamentally IS — un-debounced — versus
what `_is_hover_active` fundamentally is — the debounced fade pipeline's own commit flag. Redirecting
`get_active_theme()` to `get_displayed_theme()` as-is (step 4) would make any external reader see the
swatch currently under the cursor **immediately**, without waiting for the 80ms settle the fade
pipeline currently uses to avoid restyling on every swatch a sweep passes over. Whether that is
desirable (arguably it's a more honest "what's shown" answer, since the swatch's own `:hover` QSS is
also instantaneous with no debounce) or needs its own settling behavior at the READ layer is a
step-4 design decision, not something this shadow-check step should resolve. Flagged, not fixed —
same discipline as §7, but a genuinely different mechanism, and worth keeping distinct rather than
folding into "the same bug" the way my first pass wrongly did.

### 7c. Third occurrence, plain resting hover — NOT a defect, this is the intended, steady-state disagreement, distinct from §7 and §7b

Found later the same day, no right-click/Esc/gutter involved — hovering a single swatch, nothing
else happening. Log:

```
old_path='Pink Institute' new_path='Cerulean Sea'    _is_hover_active=False _active_display_theme_internal='Pink Institute'
old_path='Pink Institute' new_path='Melnibonéan'     _is_hover_active=True  _active_display_theme_internal='Melnibonéan'
old_path='Pink Institute' new_path='Melnibonéan'     _is_hover_active=True  _active_display_theme_internal='Melnibonéan'
old_path='Pink Institute' new_path='Melnibonéan'     _is_hover_active=True  _active_display_theme_internal='Melnibonéan'
```

The first line is another instance of §7b's pattern (`_is_hover_active=False` mid-sweep/pre-settle
— not re-analyzed again here). The remaining three are a **different, and entirely expected,**
disagreement: `_is_hover_active=True`, `_active_display_theme_internal='Melnibonéan'` — the debounce
HAS settled, hover bookkeeping is fully committed, nothing is mid-transition. `get_active_theme()`'s
own code, unchanged since 2026-07-20, is:

```python
if self._is_hover_active:
    if self._cover_theme_active and self._cover_theme is not None:
        _old_result = self._cover_theme
    else:
        _old_result = self._current_theme_name   # <-- deliberately NOT the hover theme
```

`get_active_theme()` was built specifically to **hide** the hovered theme from every external caller
while a hover is live — that is the entire "hover-safe" contract this method has had since the
2026-07-20 audit (§ Context, `review/Review_260720_theme_reach.md`): a caller reading the active
theme mid-hover was never supposed to see the preview, only the real committed theme. So
`old_path='Pink Institute'` here is not the old path malfunctioning — it is doing precisely its
documented job. `get_displayed_theme()` reporting `'Melnibonéan'` is also not wrong — it is
answering the deliberately different question this whole redesign exists to ask: not "what is safe
to tell external code," but "what is actually being shown right now."

**This is the plain, steady-state case — the ordinary experience of hovering a swatch with nothing
else going on — and it is SUPPOSED to disagree, every single time, for as long as
`get_active_theme()` keeps its current hover-concealment behavior.** It is categorically different
from §7 (a genuine ordering race during panel dismiss) and §7b (a genuine debounce-vs-instantaneous
mismatch during a sweep): neither of those is "intended" — both are edge cases worth resolving.
This one is not an edge case and is not a bug: it is the two methods doing exactly what each was
built to do, and disagreeing on their very definitions of "what to report during a hover." Step 4 is
not about reconciling this disagreement — it is about **deciding to stop concealing the hover
entirely**, which was always the explicit intent of this redesign (§ Context: "there is no hover to
report — full stop" only describes the *absence* case; when a hover genuinely IS live, the whole
point is that `get_displayed_theme()` reports it truthfully, where `get_active_theme()` today does
not). Every one of the 9 call sites (§5) was already audited under the 2026-07-20/08-03 confinement
work to confirm they are safe to show the hovered theme while it's live — that was the substance of
the "hover-safe" fixes earlier tonight. So this disagreement is not a risk step 4 introduces; it is
the exact intended effect step 4 is FOR. Recording it here only so it is not mistaken for a fourth
open defect alongside §7/§7b — it isn't one.

### 7d. Fourth occurrence, hover + right-click together — same mechanism as §7b, triggered by selection instead of a plain sweep

Found later the same day: hovering and right-clicking (selecting) several swatches in sequence.
Log, with real file timestamps checked (not assumed from the pattern, per the §7b correction
lesson):

```
02:02:41,166  new_path='Cerulean Sea'  _is_hover_active=False   (+201ms span, 3 lines)
02:02:55,611  new_path='Winterfell'    _is_hover_active=False   (+196ms span, 3 lines)
02:02:57,405  new_path='Shai-Hulud'    _is_hover_active=False   (+192ms span, 3 lines)
```

Every line: `_is_hover_active=False` and `_active_display_theme_internal == _current_theme_name`
(both equal the just-selected theme) — the same signature as §7b, not §7c: the debounce has not
yet committed a hover, so the OLD path is reporting "nothing previewed yet, still on the selected
theme" while `get_displayed_theme()` correctly reports whatever swatch is live under the cursor.

**Same underlying mechanism as §7b (the 80ms debounce not yet settled), with one addition worth
naming precisely rather than left unexplained:** `_on_theme_right_clicked` (theme_manager.py:2187)
explicitly stops the hover debounce timer and clears `_pending_hover_theme` on every right-click —
deliberate, so a stale queued preview from before the click can't land afterward and fight the
freshly-selected theme (see its own comment, "cancel it so a stale delayed preview can't land after
this commit"). So each of these windows starts from a clean stop, not a mid-flight timer: click →
timer cleared → `_apply_stylesheets`-driven restyle runs synchronously for the selection itself →
only once that returns does Qt deliver the next swatch's `enterEvent`, which restarts the debounce
fresh → ~80ms later it settles. The measured windows here (~192-201ms) are longer than §7b's
(46-242ms, same ballpark but this consistently sits at the high end) — consistent with the
selection's own restyle work adding real, non-debounce delay before the debounce timer even gets to
start, on top of its own 80ms. Not independently re-measured to confirm the split between
restyle-time and debounce-time; flagged as the same class of finding as §7b (an un-debounced read
vs. a debounced commit, legitimately differing while the newer hover hasn't settled) rather than a
new mechanism, and belongs on the same step-4 list as §7b rather than as a fifth distinct case.

### 7e. Fifth occurrence, clicking Exclusive cover-art mode — a genuinely NEW mechanism: `get_active_theme()`'s non-hover branch never consults `_cover_theme_active` at all, and the disagreement here lands mid-drain of a stashed fade call

Found later the same day, clicking the Exclusive cover-art-mode button. Log (three lines, ~400ms
span, confirmed via full surrounding context this time — not inferred from the pattern alone):

```
old_path='Elphaba' new_path={...cover-derived dict...} _is_hover_active=False
_active_display_theme_internal='Elphaba' _current_theme_name='Elphaba' _cover_theme_active=True
```

**Root cause, confirmed directly from the surrounding log context (not guessed):** the line
immediately preceding the first disagreement is:

```
[FADE-FINISHED-TRACE] _on_fade_finished ENTRY
  _pending_fade_call=({cover_dict}, False, 750, False, True, True)
  _active_display_theme_internal='Elphaba' _is_hover_active=False
```

`set_cover_art_mode("exclusive")` (theme_manager.py:2592) had already run and set
`self._cover_theme_active = True` synchronously — but the actual `_on_theme_changed(self.
_cover_theme, ...)` call that would apply the cover dict and, critically, call `_mark_theme_applied`
(the SOLE writer of `_active_display_theme_internal`) got STASHED behind an in-flight fade rather
than applied immediately (the `_pending_fade_call` mechanism from the July 21/22 confinement fix,
§4). So for the entire window between the click and `_on_fade_finished`'s drain actually running
`_apply_stylesheets`/`_mark_theme_applied`, the app is in a real, legitimate transitional state:
`_cover_theme_active=True` (set eagerly) but `_active_display_theme_internal` still holds the
PRE-cover value, because nothing has painted the cover dict yet.

**This is not the §7/§7b/§7d timing-window pattern — it is a genuinely different, and more
fundamental, gap: `get_active_theme()`'s non-hover branch has never consulted `_cover_theme_active`
at all.** Re-reading its exact code:

```python
if self._is_hover_active:
    if self._cover_theme_active and self._cover_theme is not None:
        _old_result = self._cover_theme          # cover IS checked here
    else:
        _old_result = self._current_theme_name
else:
    _old_result = self._active_display_theme_internal or self._current_theme_name
    # ^ no _cover_theme_active check anywhere in this branch, by design or oversight
```

The cover-theme check only exists in the `_is_hover_active` branch. The non-hover branch — the one
taken essentially all the time — trusts `_active_display_theme_internal` unconditionally, on the
assumption that `_mark_theme_applied` always keeps it in sync with reality. That assumption is
false for exactly as long as a cover-theme apply sits in `_pending_fade_call`'s queue: `_cover_theme_
active` flips synchronously at the click, `_active_display_theme_internal` only flips once the
stash drains. `get_displayed_theme()` has no such gap — its final fallback checks `_cover_theme_
active`/`_cover_theme` directly and unconditionally, so it correctly reports the cover dict the
instant the click sets `_cover_theme_active = True`, regardless of whether the paint itself has
happened yet.

**Disposition:** this is a real, pre-existing gap in `get_active_theme()`'s OLD logic, exposed by
the shadow check rather than introduced by it — `get_active_theme()` has, since 2026-07-20, been
capable of returning a stale non-cover theme name for the whole span of any stashed cover-theme
apply, to every one of its 9 external callers, whenever a fade happens to be in flight at the moment
Exclusive/with_pool is toggled. This is arguably worse than §7/§7b/§7d (which are brief, sub-300ms
windows) because a fade in flight can itself take up to 750ms (`_THEME_SWITCH_FADE_MS`), and the gap
lasts exactly as long as the stash sits queued. Not fixed here — flagged for step 4, and it changes
step 4's shape slightly: `get_displayed_theme()` is not just a replacement for the two hover fields,
it is also, incidentally, already MORE CORRECT than `get_active_theme()` on the cover-theme axis
independent of hover, which step 4's author should note explicitly rather than treat this class of
disagreement as symmetric with §7/§7b/§7d.

### 7f. Pryme's own observation, not a shadow-check log line: the ALREADY-TRACKED `TODO.md` 2026-08-02 book-switch flow/nudge-animation stutter (cover-theme on) has gone from rare to almost every switch tonight — NOT resolved, recorded as open

Pryme reported (2026-08-04): with cover-theme-based theming on, a theme-change apply landing
mid-flow-animation or mid-nudge-animation during a book switch is a known, previously-rare issue —
**this is the same bug as the existing `TODO.md` 2026-08-02 entry, "Theme-apply
ordering/deferral for book-switch flow stutter (cover-theme on)"** (confirmed the same item after
initially, wrongly, treating it as a separate new observation — corrected in this same exchange).
What is new tonight is not the bug itself but its FREQUENCY: it has been happening on almost every
book switch during this session's testing, where it was rare before.

**Checked, not assumed:** `git diff 95eae22 HEAD -- theme_manager.py` (95eae22 = last commit before
tonight's redesign work) shows every non-additive line this session touched is scoped to either the
`get_current_theme()`/`get_active_theme()` READ path (redefinition + shadow-check, §7e's subject)
or the two `clear_stale_hover_state()` repaint corrections (which fire only from `PanelManager.
_on_settings_hidden`, i.e. only when Settings is being closed). Nothing this session touches
`apply_cover_theme`, `_apply_pending_cover_theme`, `load_book`, `_on_theme_changed`'s fade/stash
scheduling, or any flow/nudge-animation code. So there is no mechanism in tonight's diff by which
these changes could shift WHEN a cover-theme apply lands relative to a flow/nudge animation during a
plain book switch.

**What I have NOT ruled out, and want named rather than silently assumed away:** tonight's testing
pattern itself may differ from Pryme's usual usage in a way that's a real (if incidental) variable —
most of tonight's book-switch testing happened with Settings open (hovering/right-clicking swatches
to provoke shadow-check disagreements), and per CLAUDE.md's own documented finding
("Hover-preview theme application must never reach `_schedule_deferred_restyle`..."), restyle cost
is PANEL-OPEN-STATE dependent, not cadence dependent — a theme apply while Settings/the Themes tab
is open measures ~590-620ms live vs. ~430-440ms with no panel open. If Settings being open during a
book switch makes a stashed/mid-flight collision more likely (untested, not confirmed), then what
changed tonight could be the TESTING PATTERN (many Settings-open book switches in a short span)
rather than anything in the code. This is a real, checkable hypothesis — not a deflection — but it
is unverified; I have not confirmed whether Pryme's book switches tonight coincided with Settings
being open versus closed at each stutter.

**Disposition: recorded as an open observation, explicitly NOT investigated or fixed this session**
per Pryme's own framing ("nothing to fix in this session"). If revisited, the first check should be
whether the increased frequency correlates with Settings-panel-open state during the switch, before
assuming any causal link to this session's read-path changes — which the diff itself does not
support.

---

## 8. Coexistence with the future book-switch flow-stutter sequencing fix (`TODO.md` 2026-08-02)

Pryme flagged (2026-08-04) that this design must be able to coexist with a LATER, separate,
deliberately-deferred fix for the flow-stutter item in §7f — one that reorders WHEN
`_apply_stylesheets`'s "immediate tier" vs. "deferred tier" run relative to the book-switch flow
animation (see the TODO entry's own "Immediate tier"/"Deferred tier" split). Pryme named this
sequencing work as delicate, previously having caused book-progress resets, and wants confirmation
that this hover-state redesign will not add a second axis of risk to that already-risky future work.

**Checked directly, not assumed: `get_displayed_theme()` and the shadow-check are pure readers with
no dependency on WHEN anything paints.** They call `.isVisible()`/`.currentIndex()`/
`mapFromGlobal`/`rect().contains()`/`childAt()`, and read `_current_theme_name`/`_cover_theme_active`/
`_cover_theme` — never `_apply_stylesheets`, `_mark_theme_applied`, `_pending_fade_call`,
`theme_applied.emit`, `_refresh_panel_visuals`, or `update_theme_list_visuals` (the exact set of
calls the flow-stutter TODO item's "immediate tier"/"deferred tier"/TAIL split is about — confirmed
by reading `_on_theme_changed`'s post-apply block, theme_manager.py:960-968, where all of them fire
together right after `_mark_theme_applied`). A future change to WHEN that tier split happens changes
nothing this design reads, and nothing this design does can influence when that tier split fires.
This holds regardless of which sequencing option (a) or (b) in the TODO entry is eventually chosen.

**The one real dependency, and it argues for doing step 4 BEFORE attempting the sequencing fix, not
after or in parallel:** §7e already found that `get_active_theme()`'s OLD path is wrong for the
entire span a cover-theme apply sits queued in `_pending_fade_call` — a real, pre-existing gap. The
proposed sequencing fix's whole design is to defer MORE work (settings/speed/sleep/stats/book_detail
panels, the TAIL) until after the flow animation completes — which, by construction, LENGTHENS the
exact window §7e describes, not shortens it. Two consequences worth being explicit about:

- If step 4 (redirecting `get_active_theme()` to `get_displayed_theme()`) lands BEFORE the
  sequencing fix is attempted, this entire disagreement class disappears — `get_displayed_theme()`
  never had the lag, so a longer deferral window under the new sequencing has no correctness
  consequence for theme reads, only the timing consequence the sequencing fix is explicitly trying
  to manage.
- If the sequencing fix is attempted FIRST, while `get_active_theme()` still has the §7e gap, the
  window where callers can read a stale (non-cover) theme name gets systematically longer as a
  direct, foreseeable side effect of that fix's own design — a second, avoidable variable inside an
  already-delicate change. This is worth naming to whoever attempts the sequencing fix, so a
  correctness regression discovered there isn't mistakenly attributed to the sequencing logic itself
  when it is actually this pre-existing, independent read-path gap.

**On the progress-reset risk specifically:** confirmed by direct reading that no method in this
design (`get_displayed_theme()`, the `get_active_theme()` shadow-check, the counter/stdout
additions) reads or writes `_logical_pos`, `_seek_target`, `time_pos`, or any book-switch/seek state
— this design's entire surface is theme/panel/cursor state, a different subsystem from the
seek-tracking one CLAUDE.md's own standing rules document as fragile. This is a claim about THIS
design's isolation from that risk, not a guarantee about the future sequencing fix itself, which
remains a separate, harder problem in its own right and should be scoped, instrumented, and verified
against VT/Undo on its own terms when it is eventually attempted — same standing discipline this
project already applies to that class of change.

**Disposition:** no conflict found; one dependency identified (favoring step 4 before the sequencing
fix, not the reverse); progress-reset risk is specific to the sequencing fix's own subsystem and not
introduced by anything in this design. Not asking to proceed to step 4 — recording this analysis so
it's available whenever the sequencing fix is actually scheduled.

---

## 9. Resting-hover probe results — confirms existing findings, surfaces nothing new (2026-08-04)

`_resting_hover_probe_timer` (added to close the gap noted after §7: none of the 9 real callers
poll, so a quiet resting hover produced zero `get_active_theme()` calls and thus no opportunity for
the shadow check to fire) ran continuously for ~4.5 minutes of real, varied usage (02:57-03:01),
producing 259 `[SHADOW-CHECK]` lines (2 periodic summaries — first appearance of these all
session, confirming total calls finally crossed 200/400 — plus 257 disagreement lines).

Full breakdown, decomposed the same way as every earlier finding (by `_is_hover_active`/
`_cover_theme_active`, cross-checked against `old_path`/`new_path` shape):

| Category | Count | Disposition |
|---|---|---|
| §7c (hover-concealment, `_is_hover_active=True`) | 251 | Not a defect — the resting-hover probe, by design, samples the SETTLED-hover window every 700ms, so it disproportionately catches this already-understood, expected divergence. Includes a previously-unseen but mechanically identical sub-case: `_is_hover_active=True` AND `_cover_theme_active=True` together (53 of the 251) — a cover theme active as the pre-hover baseline while a swatch is hovered on top of it. Confirmed by reading actual log content: `old_path` is the cover dict (correct per the OLD path's own `_is_hover_active` branch, which checks `_cover_theme_active` there), `new_path` is the hovered swatch name (correct per `get_displayed_theme()`). Same §7c mechanism, not a new one. |
| §7b/§7d (debounce not yet settled) | 2 | Rare in this batch specifically because the probe's 700ms cadence sits well outside the 80-150ms debounce/sweep window these are about — consistent with, not contradicting, the earlier finding. |
| §7e (cover-theme stash-lag gap) | 4 | Same real, pre-existing gap as the original Exclusive-click occurrence — `_is_hover_active=False`, `_cover_theme_active=True`, `_active_display_theme_internal` still a plain string (not yet updated by the queued `_mark_theme_applied` call). Three of the four are consecutive probe ticks (~185ms apart) catching the same brief drain window mid-flight, not three independent bugs. Adds confirming evidence to §7e; does not change its disposition. |
| Summary lines | 2 | The periodic call/disagreement-count logs themselves, not disagreements. |

251 + 2 + 4 + 2 = 259 — every line accounted for by an already-traced mechanism; nothing
unexplained, nothing new.

**Why the raw "50-58% disagreement rate" (100/200, then 232/400 cumulative) is not alarming despite
sounding like one:** the overwhelming majority (251/257, ~98%) is §7c — the deliberate, by-design
divergence this whole redesign exists to eliminate at step 4 (stop concealing a live hover from
external readers). A high count here is actually a sign the probe is working as intended: it can
only produce a §7c line when a hover has genuinely settled and stayed resting, which is exactly the
scenario §6 step 3 needed covered and nothing else in the app was generating calls during. The
disagreement rate is not a defect-density metric for this instrumentation — most of what it's
counting is intended-and-known divergence, not bugs.

**Net result of adding the probe:** it closed the one real testing gap identified (resting hover was
previously un-exercised, not merely un-disagreeing), and confirms via several fresh minutes of
volume that §7/§7b/§7c/§7d/§7e remain the complete, exhaustive list of disagreement mechanisms
found this session — no sixth mechanism turned up despite significantly more call volume than any
prior single window. `_resting_hover_probe_timer` and `_poll_theme_for_resting_hover_check` remain
temporary scaffolding, per their own docstrings, to be deleted once the live-verification period
ends.

---

## 10. `SWATCH-LEAVE-SUSPECT` could not be deliberately reproduced — checked why, not just reported as absent

Pryme spent several minutes (after ~03:13) deliberately trying to trigger `[SWATCH-LEAVE-SUSPECT]`
by slowly edging the cursor out toward the panel gutter — the technique suggested as most likely to
land inside the blur-grab's hidden window, based on the 12 historical firings' cursor positions all
clustering near the panel edge. Zero firings resulted (confirmed: `grep -c "SWATCH-LEAVE-SUSPECT"`
unchanged at 12, all from before 02:21, none since).

**I initially misdiagnosed why, and want the correction on record rather than just the final
answer.** My first hypothesis was that the hide/show mechanism this probe depends on
(`_on_themes_tab_left`'s `not visible` branch, requiring `swatch_box`/the panel to have been made
invisible by the blur grab at the moment of the leave) might have been removed or reworked since the
probe was written (2026-07-21/22), based on `transport_bar_blur.py`'s current logging showing a
`refresh_dirty`/`_grab_and_blur` rect-based path with no obvious `.hide()`/`.show()` in the lines I
first read. **This was wrong, and I retract it**: reading further in the same method
(`transport_bar_blur.py:941-942`) shows an explicit, still-current comment — "the panel must be
hidden for the grab too, same as the overlay already is" — confirming the hide/show cycle this
whole mechanism depends on is still real and still runs on every grab tick.

**SECOND CORRECTION, from Pryme directly (2026-08-04): the "faster cadence = shorter window = harder
to land in" reasoning above was also wrong, and conflates two different quantities.** Pryme's
objection, checked and confirmed correct: the number that matters for "does a crossing land inside a
hidden window" is HOW LONG each individual hide/show cycle keeps the widget invisible, not how often
cycles start. I substituted tick FREQUENCY for hidden-window DURATION without checking the duration
number at all.

**Checked directly this time.** `transport_bar_blur.py`'s own `_grab_and_blur` comment (the
INPUT-LEAK FIX, 2026-08-01) states the hidden duration explicitly: **"~48ms, ~5x/sec while a panel is
open"** — a ~48ms hidden window, at a ~200ms cadence, as a STEADY-STATE baseline. That baseline
does not match the bursty ~15-20ms-apart timestamps pulled from the log, because — checked
further, and this is the actual resolution — `refresh_dirty` is NOT a fixed-interval poll at any
rate. `_schedule_refresh` (`transport_bar_blur.py:611`) arms a coalescing `QTimer.singleShot(0, ...)`
only in response to a REAL Qt Paint event on a tracked widget; the "~5×/sec while a book plays"
figure describes what falls out of that mechanism during quiet playback (the transport bar's own
periodic repaint), not a configured rate. There is no single "refresh rate" knob to lower, because
there is no polling loop — the bursty 15-20ms-apart samples in tonight's log were captured DURING
active hover/theme interaction, where many distinct real Paint events (each hover repaint, each
swatch highlight change) each independently triggered one coalesced grab in quick succession. That
is a materially different, and more debatable, situation than "an unnecessary fast timer": it is
"how many distinct dirty events does active UI interaction generate, and does each really need its
own fresh grab-and-blur" — which is Pryme's original point, correctly re-stated, not addressed by
anything in my first-pass explanation above.

**Disposition, corrected:** whether the per-crossing odds of landing inside a hidden window are
better or worse during active interaction (bursty, many short grabs) versus quiet playback (steady
~48ms/~200ms baseline) is NOT established by anything checked so far — my "harder to land in during
a slow edge-out" conclusion above does not survive this correction and should not be relied on. What
IS established: the hide/show mechanism is real and current (confirmed, see above), the ~48ms figure
is a steady-state baseline from the code's own comments and not necessarily representative of the
burstier rate active interaction produces, and Pryme's standing point — that grabbing this often
during active interaction is not obviously required by anything the blurred rects themselves need —
is a genuine, previously-raised, still-unresolved question about `transport_bar_blur.py`'s dirty-
tracking granularity, separate from and not resolved by this hover-state redesign. Recording it here
as a real open item Pryme has flagged more than once, not settling it — it is outside this design's
scope (which is the `get_active_theme()`/`get_displayed_theme()` read path, not the blur overlay's
refresh cadence) and belongs with whoever next touches `transport_bar_blur.py`'s dirty-tracking
mechanism, with a note that the coalescing/event-driven shape is intentional (per its own comments)
but the volume of distinct dirty events it coalesces during active interaction has not been measured
or challenged before now.

---

## 11. Step 4 shipped — a real, unstaged occurrence of the original bug confirms the fix live

**Step 4 landed 2026-08-04**: `get_active_theme()`'s body now returns `self.get_displayed_theme()`
directly (the shadow-check, stdout mirror, module-level counters, and the temporary
`_resting_hover_probe_timer`/`_poll_theme_for_resting_hover_check` scaffolding were all removed in
the same change — see the commit for the full diff). `get_current_theme()` needed no change; its
one-line `_resolve_theme(self.get_active_theme())` delegation automatically inherits the new
behavior. `check_cursor_on_settle`, `clear_stale_hover_state`, `_is_hover_active`,
`_active_display_theme_internal`, and `_check_swatch_still_hovered` were NOT touched, per the
design's own sequencing (deletions of the first two, and any future change to the fade-pipeline
internals, remain separate, later steps).

**Live verification found a real, spontaneous occurrence of the exact bug class this redesign
targets** — not staged, not requested, caught during ordinary post-deploy use. Pryme reported seeing
"Sunspear" in the main window while "Eyes of Ibad" was the real active theme, reverting later.
Checked against the log (`04:24:22-04:24:31`, confirmed to be running the NEW code — the app instance
that logged it started at `04:12:30`, before the episode, and the next restart was at `04:25:39`,
after): `_active_display_theme_internal` genuinely stuck at `'Sunspear'` for ~9 seconds (a real
instance of the pre-existing hover/leave-misclassification bug this whole design exists to fix) while
`_current_theme_name` stayed correctly `'Eyes of Ibad'` throughout — traced to `[SWATCH-BACKSTOP-
FIRED]` catching a leave the jitter guard missed and correcting it via `_on_theme_unhovered()`, the
existing, untouched backstop mechanism working exactly as designed.

**Confirmed by direct code reading**: `get_displayed_theme()`'s geometry branch requires `settings_
panel.isVisible()`, `tabs.currentIndex()==0`, AND `swatch_box.isVisible()` all true before it ever
checks cursor position (theme_manager.py, the `if` guard at the top of the method). Cross-checked
against the log's `[SWATCH-BACKSTOP-COST]` lines for this exact window: `swatch_box.isVisible()` was
`False` for the earlier ticks (guard fails immediately, falls through to `_current_theme_name`) and
`True` with `outside=True` (cursor off the box) for the later ticks (geometry check runs, finds no
`ThemeItem` under the cursor, falls through to the same `_current_theme_name` return) — so
`get_displayed_theme()`/`get_active_theme()` would have returned `'Eyes of Ibad'` to any external
caller at every point across the entire episode, never `'Sunspear'`, despite the internal bookkeeping
being stuck the whole time.

**Confirmed live by Pryme (not inferred): the main window's actual painted colors corrected sooner
than the full ~9-second bookkeeping-stuck window** — consistent with the visible correction tracking
the backstop's `_on_theme_unhovered()` call (which drives the real repaint) rather than tracking
`_active_display_theme_internal`'s eventual settle a few seconds later. The bookkeeping lag was real
but had neither a visible consequence (paint corrected earlier, via the pre-existing backstop) nor a
read-path consequence (confirmed above) — it is exactly the class of "stale internal state that no
longer matters because nothing outside the fade pipeline reads it" this redesign was built to
produce.

**Disposition: strong, real-world confirmation of item 5 in the step-4 verification checklist** — an
unstaged, naturally-occurring instance of the original bug class, with the read side (this design's
actual scope) confirmed clean by code tracing and the paint side (pre-existing, untouched machinery)
confirmed by Pryme's direct observation to have corrected well before the bookkeeping did. Suite:
442/442, matching baseline, both before and after the step-4 diff.
