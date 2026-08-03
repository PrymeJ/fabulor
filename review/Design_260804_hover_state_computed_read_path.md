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
| 10 | **`app.py:1509` `_set_bg_suppressed`** (`self.theme_manager.get_active_theme()`) | **No — newly found, and this is the ORIGINAL bypass the July 20 audit was built to close** | Fires on every book-load/empty-state transition — genuinely reachable mid-hover, exactly the scenario `get_active_theme()` was created to protect. Correct under the redesign with no call-site change; notably, this is the single most important site to re-verify live, since it is the historically-confirmed highest-value target for this whole class of bug. |

**Every site: correct with zero call-site changes**, because both public accessor names and their
return-type contracts are preserved exactly. The two newly-found sites (#9, #10) do not represent a
gap in this design — they were already calling the "sanctioned" `get_active_theme()`, which becomes
correct automatically once its internals change. They are surfaced here because failing to name them
would repeat tonight's exact mistake (auditing to a fixed list instead of re-grepping fresh).

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
   hover with the cursor resting still, a hover interrupted mid-fade, the `[SWATCH-LEAVE-SUSPECT]`
   scenario already caught once tonight (leave-while-hidden misclassification), and at least one
   book-load while hovering (site #10 above, the highest-value target). Zero disagreements over a
   real session is the bar — matching this project's own standing rule that a single clean pass is
   evidence, not proof, so this step should span more than one sitting if anything looks borderline.
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
