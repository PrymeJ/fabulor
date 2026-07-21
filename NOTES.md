## Blur toggle now applies live to the open Settings panel; the Off→On cover-image asymmetry explained (2026-07-21)

The Settings > Blur On/Off toggle only wrote config (`_update_blur_mode` → `config.set_blur_enabled`
+ visual refresh), so it took effect only on the next panel close/reopen. Fixed by adding
`PanelManager.apply_blur_live(enabled)`, called from `_update_blur_mode` after the config write. It
acts on the already-open Settings panel (the only panel the toggle is reachable from) for both blur
mechanisms: the transport-bar composited overlay (`_apply`/`_clear_transport_bar_blur`, already
live-callable — `show_for_panel` early-returns if `self._active`, `hide_for_panel` tears down
unconditionally, and `show_for_panel` recomputes the bounding rect from the panel's current settled
geometry) and the cover-image `blur_effect`.

**The user-observed Off→On-doesn't-but-On→Off-does asymmetry (cover image), root cause:**
`MainWindow.set_blur_selection(enabled)` (`app.py`) — called by the toggle's visual refresh — had
`if not enabled: m.blur_effect.setBlurRadius(0)` but NO `enabled=True` counterpart. So turning blur
Off live-zeroed the cover-image blur, while turning it On did nothing to the image. `apply_blur_live`
adds the missing On direction (animate `blur_effect` 0→10), making the toggle symmetric. (This
cover-image path is expected to be replaced by the transport-bar grab code later — see the TODO
about giving the cover-art area the same treatment — so it's deliberately minimal.)

Routing note: `SettingsController` reaches panels through the `PanelInterface` facade, which is
constructed (`app.py` `_setup_ui`) BEFORE `panel_manager` exists, so `PanelInterface` holds a `main`
reference and reads `main.panel_manager` lazily at call time rather than capturing the not-yet-created
object. Guards on the method: `settings_panel.isVisible()` and — required per plan-review, not
optional — `is_any_panel_animating()`, so the toggle can never apply/clear blur mid-slide (the "this
state is unreachable so no guard needed" assumption is precisely what caused this session's
`_do_rotate`/"Change now" regression). `2dd1445`.

---

## Timeline tassel cursor went shaky under blur — synthetic leaveEvent from the blur grab's panel hide, cleared its dynamic hand cursor 5×/sec (2026-07-21)

**Symptom:** the Timeline tassel's hand cursor was steady with blur OFF but "shaky" with blur ON —
flipping hand↔arrow while the pointer rested motionless on it. This was the deferred follow-up from
Session 6's general cursor-fluctuation fix (`906fa4a`), which did NOT resolve the tassel because the
tassel is architecturally different from the Stats book rows that fix addressed.

**Why the general fix didn't cover it:** `BookDayRow` etc. use a STATIC `setCursor(PointingHandCursor)`
(a persistent widget property), so pinning an override cursor across `_grab_and_blur`'s hide/show was
enough. `TasselOverlay` uses a DYNAMIC cursor — `setCursor(hand)` in `mouseMoveEvent` while inside
`_in_hit_region`, `unsetCursor()` in `leaveEvent` — re-asserted only on mouse movement. So the
override-pin preserved whatever shape was resolved at grab time, but couldn't fix a cursor the
tassel's own logic had already cleared.

**Investigation (live-first, temporary `[TASSEL-CURSOR]` log probe on `mouseMoveEvent`/`leaveEvent`/
`enterEvent`):** the smoking gun was the leave-event counts across one hover — **85 `leaveEvent
vis=False` vs. exactly 1 `leaveEvent vis=True`**. The `vis=False` is decisive: those leaves fire
while the tassel is mid-hide, i.e. they're SYNTHETIC, delivered by Qt as a side effect of the panel
being hidden — not real mouse-outs. Full mechanism: `transport_bar_blur._grab_and_blur` hides then
re-shows the whole Stats panel ~5×/sec (to grab the transport bar behind it); the tassel is a
descendant of that panel, so each hide delivers it a synthetic `leaveEvent` (`isVisible()` False) →
`unsetCursor()` clears the hand → the re-show fires a synthetic `enterEvent` but NOT a
`mouseMoveEvent` (the mouse didn't move), so nothing restores the hand. Net: the hand cursor is
cleared and only briefly recovered, 5×/sec — the shakiness.

**The clean discriminator:** a GENUINE mouse-leave fires while the widget is still visible
(`isVisible()` True — the single `vis=True` leave in the trace, when the pointer actually left the
tassel); the blur-induced synthetic leave fires mid-hide (`isVisible()` False). So `self.isVisible()`
in `leaveEvent` cleanly tells the two apart.

**Fix:** guard `TasselOverlay.leaveEvent`'s `unsetCursor()` on `self.isVisible()` — only clear the
hand on a real mouse-out; ignore the synthetic hide-driven leaves so the cursor survives the
hide/show churn. Tassel-local, doesn't touch the blur code, composes with Session 6's override-cursor
fix. Verified live: steady hand on the tassel under blur, correct arrow on a genuine mouse-out, click
and extended-tassel hover still correct (`537f018`). General lesson worth remembering: a widget with a
DYNAMIC (mouseMove-driven) cursor is vulnerable to any code elsewhere that hides/shows an ancestor,
because the resulting synthetic leave clears the cursor with no movement to restore it — guarding the
`leaveEvent` on `isVisible()` is the fix pattern.

Separately, same session: the tassel's clickable/hand hit zone was too wide to the right — ~8px of
sway slack (`int(KICK_AMP)+2`) extended past the visible fringe edge. Decoupled the right-side slack
from the shared sway slack (`right_slack`, tuned live to `-1`, i.e. 1px inside the visible fringe);
left edge, `_tab_rect`, and vertical sway tolerance unchanged (`8955a2d`).

---

## Sleep/Speed preset buttons had no hover/pressed feedback — pre-existing, not a regression (2026-07-21)

**Symptom:** user reported the Sleep panel's time-preset buttons (2 min, 5 min, ... 90 min) and the
Speed panel's speed-preset buttons lost hover styling "after last night's changes to button types,"
while "End of chapter" and "Set" (in the same Sleep panel) still showed hover/pressed color clearly.

**Investigation, in order:** (1) checked commit history on this branch for the last 24h touching
`sleep_timer.py`, `speed_controls.py`, `themes.py`, `title_bar.py`, `main_window_builders.py` —
nothing. (2) Per explicit instruction, checked out `main` read-only and compared: both files'
button-construction code and `get_settings_stylesheet`'s QSS (the generic `QPushButton {}` /
`QPushButton:hover {}` / `QPushButton:pressed {}` rules) are byte-for-byte identical to this branch,
same line numbers. (3) User confirmed via screenshot that `main` shows the exact same "no style"
behavior. This ruled out a recent regression entirely — whatever "last night's changes to button
types" referred to, it isn't what caused this; the gap has always existed, just unnoticed until now.

**Root cause, found by diffing what's different between the working buttons ("End of chapter",
"Set") and the broken preset grids:** `SleepTimerPanel.update_panel_styling`
(`sleep_timer.py`) and `SpeedControlsPanel.update_visuals` (`speed_controls.py`) each give every
preset button its own **per-instance** `btn.setStyleSheet(f"background-color: rgba(...); color:
...; border: none;")` call, to create a deliberate visual alpha ramp across the row (later
presets more opaque than earlier ones — `alpha = int(75 + (180 * (i / (n - 1))))`). In Qt, a
widget-level stylesheet set via `setStyleSheet()` on the widget itself takes precedence over the
panel's own cascading QSS for that widget — and this inline stylesheet only ever specified a flat
`background-color`, never `:hover` or `:pressed`. So every preset button in both panels has had
**zero** hover/press visual feedback since this ramp effect was first written — a plain omission in
the original inline-stylesheet string, not a recent break. "End of chapter"/`set_custom_btn` are
never included in the loop that calls `setStyleSheet()` this way, so they simply keep inheriting the
panel-level `QPushButton:hover`/`:pressed` rules normally — which is exactly why they alone showed
the expected hover color and looked like the "correct" reference point.

Same-shape confirmation: the app's OTHER preset-style button groups in `speed_controls.py` (step,
undo, skip, long-skip, smart-wait/dur — all via `setObjectName("pattern_button")` + a
property-driven QSS rule, never a per-instance `setStyleSheet()`) all hover correctly, matching the
theory precisely — it's specifically the alpha-ramp buttons' per-instance stylesheet that's missing
the states, not something about fixed-size buttons or `QGridLayout` in general (both of those were
considered and ruled out: the main transport buttons are also `setFixedSize` and hover fine).

**Fix:** extended the inline stylesheet string in both methods to include `QPushButton:hover`/
`QPushButton:pressed` rules, computed from each button's own already-ramped color via
`QColor.lighter(130)` (hover) and `.darker(130)` (pressed) — so the per-button alpha ramp is
preserved exactly as designed, while every preset button now visibly responds to hover/press like
every other button in these panels. Identical fix, same shape, applied to both
`SleepTimerPanel.update_panel_styling` and `SpeedControlsPanel.update_visuals`. Verified live.
Committed `8f2d15e`.

---

## Cursor fluctuating hand↔arrow over panel widgets when blur is on — root-caused and fixed via live [CURSOR-TRACE] instrumentation (2026-07-21)

**Symptom:** with blur ON, resting the mouse motionless over an interactive panel widget with a
PointingHand cursor (Stats book rows, cover-pool swatches — anywhere with `setCursor(PointingHandCursor)`)
made the cursor flicker between hand and arrow with no mouse movement at all. Reported alongside the
Timeline tassel and the "Change now" button, but those two turned out to be different cases (see
below) — the general fluctuation is what got fixed here.

**Investigation approach (per explicit instruction):** live-instrument first, confirm the mechanism,
THEN fix — not guess-and-check. A temporary `[CURSOR-TRACE]` probe was added to
`TransportBarBlurOverlay._grab_and_blur` (`transport_bar_blur.py`), logging the widget under the
global cursor position and its resolved `cursor().shape()` at three points: before the panel is
hidden, immediately after hiding it, and immediately after showing it again. First probe attempt
raised `TypeError` (`int(CursorShape)` doesn't work on this PySide6 version — fixed to `.shape().value`).

**Root cause, confirmed with 100% reproducibility across every tick:** `_grab_and_blur` hides the
entire active panel (`self._active_panel.hide()`) so its pixels don't appear in
`main_window.grab(padded_rect)` (needed because the panel is a sibling child of `main_window`,
raised above `content_container`, and `main_window.grab()` rasterizes everything visible — see the
`content_container` background-color note in the same file for why grabbing `main_window` instead of
`content_container` is required and non-negotiable). This grab runs on every dirty-refresh tick —
~5×/sec while a book plays, since the mini transport bar's time/chapter labels repaint continuously.
Live trace, Stats book row, every single tick identical:
```
BEFORE-HIDE  widget_under_cursor='stats_book_day_row' cursor_shape=13 (hand)
AFTER-HIDE   widget_under_cursor='QLabel'             cursor_shape=0  (arrow)
AFTER-SHOW   widget_under_cursor='stats_book_day_row' cursor_shape=13 (hand)
```
Hiding the panel exposes whatever transport-bar widget is positionally behind it at the cursor
location (an arrow-cursor `QLabel`) — Qt re-runs hit-testing and resolves the live cursor to that
widget's arrow. Showing the panel again resolves it back to hand. No `QApplication.overrideCursor()`
was ever involved (checked and logged `None` throughout) — this is pure widget-under-cursor
hit-testing following visibility, not an override fighting anything.

**Two related-but-different findings from the same trace, NOT fixed here:**
- **"Change now" button** (`theme_change_now`) reported `cursor_shape=0` (arrow) even at BEFORE-HIDE
  — it has no `PointingHandCursor` set on it as a widget property at all. Whatever the user
  originally saw "turning into a hand" over that button was very likely the same hit-test churn
  momentarily resolving to a *different*, nearby hand-cursor widget, not the button itself gaining a
  hand cursor. Confirmed live post-fix: the button now stays a steady arrow, which is correct.
- **Timeline tassel** reported `cursor_shape=0` (arrow) even at BEFORE-HIDE, resting motionless
  directly on it — because `TasselOverlay` sets its cursor dynamically inside `mouseMoveEvent` via
  `_in_hit_region()` (not a static `setCursor()` on the whole widget), so it only reads as hand while
  the mouse is actively moving within the hit region. This is a structurally different mechanism from
  the fix below and was confirmed, post-fix, to still be "shaky" specifically when blur is on (steady
  with blur off) — logged as a separate TODO item, not resolved by this fix. The override-cursor pin
  below preserves whatever shape was ALREADY resolved at grab time; it can't retroactively make the
  tassel's own hit-test logic decide "hand" if it hadn't already.

**Fix:** bracket the synchronous `hide() → main_window.grab() → show()` sequence in `_grab_and_blur`
with an application override cursor. Right before hiding the panel, read the widget currently under
the global cursor (`QApplication.widgetAt(QCursor.pos())`) and push its resolved cursor as an
override (`QApplication.setOverrideCursor(w_under.cursor())`); pop it in the `finally` immediately
after the panel is shown again. Since the whole hide→grab→show cycle is synchronous with no
intervening event-loop turn (confirmed by the trace itself — all three probes land within the same
few milliseconds), the override cleanly brackets exactly the churn window and is gone before any
real user input could observe it. Guarded so it's only pushed when a panel is actually being hidden
AND a widget is under the cursor, and always popped in `finally` regardless of how the block exits —
cannot strand a stuck override.

**Verified live, all cases:** Stats book row now shows a steady hand cursor (no flicker); "Change
now" shows a steady arrow (correct, matches its actual cursor property); real mouse movement between
widgets still updates the cursor normally (the override doesn't fight genuine cursor changes, since
it's popped before the next tick and any real movement happens between ticks); blur-off path
untouched (this whole mechanism only runs when blur is on). Committed `906fa4a`.

---

## Panel-open theme guard: the `bypass_panel_open_guard` mechanism, its forward audit, and the stranded-`_fade_in_flight` "T does nothing" bug it exposed (2026-07-21)

**The guard.** To stop themes visibly changing while the user has an unrelated panel open (reported
live: the automatic rotation timer's deferred replay landing on an open Sleep panel), `_on_theme_changed`
gained a `_panel_open` guard: a call defers (via the existing `_panel_guard_timer` retry) when a full
panel is visible — UNLESS the call is a hover preview OR carries `bypass_panel_open_guard=True`. The
guard reuses `PanelManager.is_any_full_panel_visible()` (excludes the bare sidebar) and the existing
retry mechanism; the new trigger condition is `if _any_animating or _panel_open:`.

**Why `hover` alone was not the right discriminator (regressed 3×).** The naïve first cut gated on
`not hover`. That broke the Settings panel itself, because MANY non-hover theme changes are
themselves *Themes-tab-local actions* that must apply live while that panel is open: the
close-snap-back (`_on_theme_unhovered`), right-click-select, left-click-toggle-active, the
cover-art-mode buttons, the cover-pool button, AND — the third regression — the "Change now" button
(`_do_rotate(user_initiated=True)`). The real distinction is **general trigger** (rotation timer,
deferred replay, book-load cover-theme change — no relationship to any open panel) vs.
**Themes-tab-local action/settle-step** (only exists because that panel is open). Only general
triggers may be blocked.

**The exhaustive FORWARD audit (canonical — do not re-derive backward).** After three regressions
from tracing backward from `_on_theme_changed`'s callers, the correct audit traces FORWARD from
every interactive widget built in `build_themes_tab` (`main_window_builders.py:645-774`):

| Widget (construction line) | Signal → handler | Reaches `_on_theme_changed`? | Bypass |
|---|---|---|---|
| Cover-mode buttons `:662` | `clicked` → `set_cover_art_mode` | Yes (via its own calls + `clear_cover_theme`/`apply_cover_theme`) | ✅ `=True` |
| Cover-pool item `:685` | `clicked` → `_on_cover_pool_btn_clicked` | Via `set_cover_art_mode` + `clear_cover_theme(=True)` | ✅ |
| Cover-pool item `:686` | `rightClicked` → `_on_cover_pool_btn_right_clicked` | Yes | ✅ `=True` |
| Cover-pool item `:687` | `hovered` → `_on_cover_pool_btn_hovered` | Yes (`hover=True`) | ✅ via `hover` |
| Swatch `:703` | `clicked` → `toggle_theme_selection` | Only when removing the active theme | ✅ `=True` |
| Swatch `:704` | `rightClicked` → `_on_theme_right_clicked` | Yes | ✅ `=True` |
| Swatch `:705` | `hovered` → `_on_theme_hovered` → `_fire_pending_hover` | Yes (`hover=True`) | ✅ via `hover` |
| tab/pool `leaveEvent` `:714`/`:768` | → `_on_theme_unhovered` | Yes | ✅ `=True` |
| Add all `:728` | `clicked` → `select_all_themes` | **No** (pool + visuals only) | N/A |
| Remove all `:729` | `clicked` → `deselect_all_themes` | **No** | N/A |
| Change now `:730` | `clicked` → `_do_rotate(user_initiated=True)` | Yes | ✅ `=user_initiated` |
| Interval labels `:762` | `mousePressEvent` → `set_rotation_interval` | **No** (timer + visuals only) | N/A |

`_do_rotate` and `apply_cover_theme` both already had a `user_initiated` parameter that exactly
distinguishes the general-trigger caller (automatic rotation timer / book-load, `False`) from the
Themes-tab caller (Change now / cover-mode button, `True`) — so both forward `bypass_panel_open_guard=
user_initiated` rather than needing a separate flag. General triggers that must stay blocked and do
NOT bypass: `_do_rotate()` from the rotation timer, `_on_fade_finished`'s drain, `complete_main_fade`'s
drain, `apply_cover_theme`/`clear_cover_theme` from book-load. The retry lambda forwards
`bypass_panel_open_guard` so a deferred bypass call keeps its exemption on retry.

**The "Change now" regression, precisely (why the forward audit was necessary).** "Change now" calls
`_do_rotate(user_initiated=True)` DIRECTLY, skipping `_rotate_theme`'s entry-time visibility check.
Before the fix, `_do_rotate` set `self._current_theme_name` synchronously then called
`_on_theme_changed(..., bypass=False)`, which deferred (panel open). An unrelated side effect — the
cursor leaving whatever swatch it happened to be over as the click landed — fired `_on_theme_unhovered`,
which read the already-mutated `_current_theme_name` and applied IT with its own (correct) bypass.
Net effect: haphazard "sometimes works, underline doesn't move, panel flickers" — two competing
calls for the same theme racing. Fixed by `_do_rotate` forwarding `bypass_panel_open_guard=user_initiated`.

**The stranded-`_fade_in_flight` bug this exposed — "T does nothing" (confirmed live 19:33 → fixed,
verified 19:56).** A *pre-existing latent* bug that the snap-back changes made reproducible.
`snap_theme_forward` (called by `_close_settings_flow`) stops any running `_fade_anim`
(`QPropertyAnimation.stop()` — which does NOT emit `finished`, so `_on_fade_finished`, the only other
clearer, never runs) but cleared `_fade_in_flight` ONLY inside its `if self._pending_fade_call is not
None:` drain branch. The close-snap-back now genuinely starts a real 750ms fade via the
themes-tab-visible path (panel still visible during close → `_fade_in_flight=True`), which
`snap_theme_forward` immediately stops — and with nothing stashed, the in-branch-only clear was
skipped, leaving `_fade_in_flight` **stranded True with no live fade**. The next non-bypass
`_on_theme_changed` (a `T`-key rotation) then hit the `_fade_running` guard, stashed itself into
`_pending_fade_call`, and orphaned there forever (no fade to drain it) — so `T` silently did nothing.
**Fix:** clear `self._fade_in_flight = False` UNCONDITIONALLY right after the `_fade_anim.stop()` in
`snap_theme_forward`, not only in the drain branch. Cross-checked the other two fade-resolution paths:
`_on_fade_finished` clears unconditionally first thing; `complete_main_fade` clears before its own
stop — neither has the gap, so the fix is `snap_theme_forward`-only. Verified live: after a
settings-close snap-back, `T` now logs `fade_in_flight=False` → applies (`_apply_stylesheets` runs),
not `-> stashing`.

**Known deferred (see TODO.md):** cursor fluctuates hand↔arrow over panel widgets when blur is on —
`_grab_and_blur` hides/shows the whole active panel each tick, re-triggering Qt cursor/hit-test
resolution. Root-caused, not fixed this pass (its own live investigation, kept separate so a
fluctuation symptom can't be confused with a leftover T-shortcut symptom).

---

## Chapter-dropdown colors lagged one theme change behind — root cause and fix; second confirmed `_active_display_theme_internal` timing trap (2026-07-21)

**Symptom:** after any theme change, the chapter dropdown's current-chapter highlight
(`dropdown_curr_chap`) showed the *previous* theme's color, every time, deterministically.
User later confirmed `dropdown_time_text` lags identically. Requested: investigate read-only first
(plan mode), audit for any other lagging consumer, plan a fix — no code changes until the plan was
reviewed and approved.

**Mechanism, confirmed by reading code, not live tracing (the bug was deterministic, so static
analysis was sufficient):** `ThemeManager._apply_stylesheets(self, theme_name, hover=False)`
(`theme_manager.py:1109`) is the single method that paints a new theme onto every widget. Every
line in it styles directly from the `theme_name` parameter it was called with —
`get_base_stylesheet(theme_name)`, `get_title_bar_stylesheet(theme_name)`,
`get_player_stylesheet(theme_name, ...)`, `get_sidebar_stylesheet(theme_name)`,
`get_settings_stylesheet(theme_name)`, and the excluded-books section/popup via
`_resolve_theme(theme_name)` directly — except one: the chapter-list block
(`theme_manager.py:1169-1172`, before this fix):

```python
if hasattr(mw, 'chapter_list_widget'):
    theme_dict = self.get_current_theme() or {}
    mw.chapter_list_widget.update_theme(theme_dict)
```

`get_current_theme()` (`theme_manager.py:176-179`) resolves `self._active_display_theme_internal`
(falling back to `_current_theme_name`) — NOT the `theme_name` argument this call actually received.
`_active_display_theme_internal` is written exclusively by `_mark_theme_applied(theme_name, hover)`
(`theme_manager.py:541`, added in Session 1 tonight to fix the guard-masking bug), and every real
call site invokes it strictly *after* `_apply_stylesheets` has already returned (`theme_manager.py`
lines 603-604, 794-795, 806-807, 947-948). So at the exact moment the chapter-list block runs
*inside* `_apply_stylesheets`, `_active_display_theme_internal` still holds the *previous* apply's
theme name — this call's own `_mark_theme_applied` hasn't fired yet. Every theme change therefore
painted the dropdown with the theme from one apply ago, unconditionally.

`ChapterItemDelegate.update_theme` (`chapter_list.py:34-40`) reads three keys off that one stale
`theme_dict` — `dropdown_text`, `dropdown_time_text`, `dropdown_curr_chap` — so all three lag from
the identical single cause, not three independent bugs. The user visually confirmed lag on two of
the three; `dropdown_text` almost certainly lags too but is less visually obvious (ordinary row
text vs. a highlight/duration accent).

**Audit confirming scope (nothing else affected):** `grep -n "get_current_theme()"
theme_manager.py` returns exactly one call site — the one fixed here. Every other line in both
`_apply_stylesheets` and `_apply_stylesheets_deferred` (the library/stats/book_detail
invisible-surface batch) threads `theme_name` through directly with no stale-state reads.

**Fix:** replaced the stale read with the same `_resolve_theme(theme_name)` pattern the
excluded-books block already uses a few lines further down in the same method:

```python
from ..themes import _resolve_theme
theme_dict = _resolve_theme(theme_name)
mw.chapter_list_widget.update_theme(theme_dict)
```

Fixes all three colors in one change, since they share the one `theme_dict`. Committed `6617cd1`.

**Standing caution — this is the SECOND confirmed instance of the same class of bug.** Session 1
tonight's `_mark_theme_applied` fix correctly delayed `_active_display_theme_internal`'s write to
fire only after a confirmed apply (closing the guard-masking bug), but that timing shift has now
twice exposed a hidden downstream dependency nobody knew existed until the write moved: first
`snap_theme_forward`'s precondition on `_fade_in_flight` (Session 1/2), now this chapter-dropdown
block. **Any code that reads theme state via `get_current_theme()`/`_active_display_theme_internal`
must tolerate "last confirmed apply," not "most recent request."** Recorded here so a third
instance, if one surfaces, can be recognized immediately rather than re-diagnosed from scratch —
check this pattern first if a similar "one behind" or "reads a theme value that hasn't updated yet"
symptom shows up anywhere else touching theme state.

---

## Transport-bar blur timing: dismiss no longer lingers through the slide-out; appear now waits for the panel to finish opening and fades in (2026-07-21)

**Unrelated subsystem to the theme-hover entries below** — this is `ui/transport_bar_blur.py` /
`ui/panels.py`'s composited transport-bar blur overlay (used by Settings/Speed/Sleep/Stats/Tags),
not `theme_manager.py`. Found and fixed via ordinary use across two separate live-requested changes
in the same session, not an investigation-first pass — both were simple, mechanically obvious once
the call sites were read.

**Dismiss lingered too long.** `TransportBarBlurOverlay.hide_for_panel()` itself was always
instant/unconditional — the lingering wasn't inside that method. It was in WHEN it got called:
`_clear_transport_bar_blur()` was wired to each panel's `_on_*_hidden` handler
(`_on_speed_hidden`, `_on_sleep_hidden`, `_on_stats_hidden`, `_on_tags_hidden`,
`_on_settings_hidden`), which Qt only fires once the panel's `QPropertyAnimation` slide-out
`finished` signal lands — i.e. after the full close animation plays out. So the blurred transport
bar sat there, visibly blurred, for the entire dismiss animation, then snapped to live only at the
very end. Fix: moved `_clear_transport_bar_blur()` out of all five `_on_*_hidden` handlers and into
their corresponding `_close_*_flow` methods, called immediately after each slide-out animation's
`.start()` — i.e. at the moment the user actually asked to close, not the moment the animation
finishes playing. `hide_for_panel()` itself needed no changes; only its call-site timing did.
Committed `82d2c6f`.

**Appear should wait for the panel to finish opening, and fade in.** Symmetric follow-up. Before this
fix, `_apply_transport_bar_blur(panel)` was called synchronously right after
`panel_animation.start()` in each `_start_*_entry`/`_open_*_flow` — i.e. blur appeared concurrently
with the panel still sliding into position, not once it had arrived. Fixed by moving each call into
a `finished` callback on the panel's own OPEN animation instead of its close animation (a different
signal than the dismiss fix above touches): `_start_settings_entry` already had a local
`_on_settings_slide_finished` closure to hook into; `_start_speed_entry`, `_start_stats_entry`,
`_start_sleep_entry`, and `_start_tags_entry` each needed a small local `_on_*_slide_finished`
closure added (self-disconnecting, matching the existing pattern). This isn't just smoother — it's
more correct: `_apply_transport_bar_blur` clips its grab to `panel`'s own geometry via
`_panel_rect_in_common_space`, and that geometry isn't at its final resting value until the slide-in
animation actually completes; grabbing mid-slide (the old behavior) was technically racing the
panel's own position.

On top of the retimed appear, a fade-in was added so the blur doesn't snap on instantly even once
correctly timed. `TransportBarBlurOverlay.__init__` now builds a `QGraphicsOpacityEffect` on the
overlay `QLabel` and a `QPropertyAnimation` on its `opacity` property (`OutCubic`, duration
`_FADE_IN_MS`). `show_for_panel` sets opacity to 0.0 immediately before `_overlay.show()`, then
starts the fade (stopping any still-running previous fade first, same `if state == Running: stop()`
pattern used everywhere else in this codebase). This is deliberately appear-ONLY: `hide_for_panel`
stops any in-flight fade-in and resets opacity to 1.0 synchronously, with no fade-out animation of
its own — dismiss stays exactly as instant as the fix above made it; the opacity reset just ensures
the NEXT `show_for_panel` starts from a clean, fully-opaque baseline rather than wherever the
previous fade happened to leave off. `_FADE_IN_MS` was initially set to 180 and then live-tuned by
the user directly in the file to 1500 mid-session — kept as their live-tested value, not reverted or
second-guessed. Two now-stale docstrings (the module's own mechanism-overview comment, and
`hide_for_panel`'s docstring — both still described the pre-fix "torn down after slide-out
finishes" timing) were corrected in the same pass to describe both the new open-side fade-in and the
already-fixed close-side instant teardown. Committed `10b9650`.

Both changes verified live by the user before commit, per the standing practice this session of not
committing until the actual running app confirms the change (not just re-reading the diff). No new
CLAUDE.md rule — neither change resolves a hard-won bug from before; they're live-tuned UX timing
adjustments to a subsystem whose mechanism was already fully documented in
`transport_bar_blur.py`'s own module docstring.

---

## Hover-on-hover now interrupts the in-flight preview instead of being stashed and discarded — a direct side effect of the confinement fix just above, found via normal use and fixed same night (2026-07-21)

**Context:** direct follow-on to the guard-masking/hover-confinement entry immediately below. That
fix was correct for the bug it targeted (a transient cursor pass-over getting drained and applied
through the full path on panel dismiss) but had a real side effect the user found through ordinary
theme browsing, not edge-case testing: hovering theme A starts a preview fade; genuinely resting on
theme B (a real, 80ms-debounce-cleared hover, not a fast pass-over) while A's fade is still running
got B's call stashed by the existing `_fade_running` branch — and, per the confinement fix, silently
discarded at drain time because it's hover-flagged. Nothing replaced it with a fresh preview
attempt, so the user was left looking at A's stale colors while deliberately hovering B, sometimes
for the whole 80-90ms+ debounce window and beyond, with no preview appearing until some unrelated
event happened to drain the stash. Described directly as "annoying, confusing."

**Investigation, before any fix (`Investigation_HoverInterruptsHover_260721.md`):** confirmed the
80ms debounce (`_HOVER_DEBOUNCE_MS`, exactly 80, not 90) is a single global timer, fully upstream of
`_on_theme_changed`, with zero further role once a hover call exists — untouched by this fix. Found
TWO real entry points that produce a genuine `hover=True` call: the debounced swatch-sweep path
(`_fire_pending_hover`) and the cover-pool button's own hover (`_on_cover_pool_btn_hovered`,
undebounced by design — a single fixed target, no sweep to coalesce). Both reach the identical stash
branch. Confirmed, by tracing rather than assuming, that hover-interrupts-hover and
hover-interrupts-genuine-selection are THE SAME CODE PATH today — `_fade_in_flight` is a plain
boolean with no memory of what started it; the only way to distinguish the two cases is
`self._is_hover_active` (correctly maintained by the earlier `_mark_theme_applied` fix to reflect
whatever was last genuinely applied — i.e. what started the currently-running fade). Confirmed the
fade-stop mechanism needed for an interrupt already exists (`theme_manager.py`, the
`if self._fade_anim.state() == Running: stop()` pattern used at four other sites) and is currently
simply unreachable for any stashed call, since the stash branch returns before execution gets there.

**Fix:** one condition added to the existing `elif _fade_running:` branch — if the incoming call is
a hover AND the in-flight fade is itself a hover, skip the stash and fall through to the
stop-and-apply flow that already exists a few lines down. No new stop mechanism, no new apply
mechanism, no new state. Every other combination is explicitly unchanged: a hover arriving during a
GENUINE SELECTION's settle-fade still stashes-then-discards exactly as before (a preview must never
interrupt a real selection); a genuine selection arriving during any fade still stashes-then-replays
via the existing drain sites, untouched.

**Live verification, both go/no-go items the user required before considering this done — mechanism
confirmed, not just symptom absence:**
1. Hover-interrupts-hover via the swatch sweep: 67 clean interrupt events across a live session,
   each showing `[hover debounce] firing preview for '<name>' ...ms after last enterEvent` →
   `hover_interrupts_hover=True -> interrupting in-flight hover fade` → the new theme's mask-build
   starting immediately, no stash, no discard.
2. Hover-interrupts-hover via the cover-pool button (the "Cover art based theme" entry, a `ThemeItem`
   like every swatch but wired to the book's cover-derived colors) — a second, real, undebounced
   entry point into the identical branch, confirmed live to trigger the same
   `hover_interrupts_hover=True` interrupt correctly.
3. Genuine-selection-fade-interrupted-by-hover confirmed UNCHANGED via a full traced sequence: a
   real click's settle-fade (`fade_ms=750`) in flight, a hover arriving mid-fade correctly took
   `hover_interrupts_hover=False -> stashing for fade completion` (not the new interrupt path), the
   genuine selection's fade completed undisturbed, and the stale hover stash was correctly
   discarded at drain time by the earlier confinement fix — exactly the pre-existing, working
   behavior, unaffected by this change.

All diagnostic logging (`[BLEED-TRACE]`'s new `hover_interrupts_hover` field, the GUARD debug line's
updated branch-decision text) is left in place, matching this session's standing practice.

---

## Guard-masking bug (theme stuck unapplied for 75+ seconds) and hover-preview confinement — both root-caused, fixed, and live-verified together over a real 15-minute session (2026-07-21)

**Context:** continuation of the same night's theme-bleed work (see the entry below). After the
Pass 1/Pass 2 fixes there, the user kept finding theme-state bugs that didn't fit either mechanism
— panels showing a theme that was never actually selected, sometimes for a full minute or more,
and separately a panel briefly showing colors from a theme the cursor had only grazed in passing.
Both were root-caused via direct live log tracing (not guessed at) across several rounds of
screen-recorded repro, and both are now fixed and confirmed via a real 15-minute mixed-use test
session (03:00–03:15), not just isolated single-shot repros.

### Bug 1 — the no-op guard could mask a theme that was requested but never painted

`ThemeManager._on_theme_changed`'s no-op guard compares the incoming `(theme_name, hover)` against
`_active_display_theme_internal`/`_is_hover_active` and skips the whole apply if they already
match — a legitimate optimization (this app was measurably slow re-applying themes on every hover
tick before this guard existed). The bug: both fields were written **unconditionally**, the moment
`_on_theme_changed` decided *what* was being requested, before it decided whether to actually apply
that request or stash it for later (the `_any_animating`/`_fade_running` branches, used when a fade
is already in flight). A call that got stashed still left the fields claiming the requested
theme/hover was already live. When that stash was later drained and replayed with the identical
`(theme_name, hover)` pair, the guard saw "already matches" and silently no-op'd — `_apply_stylesheets`
never ran, and the theme stayed stuck at whatever was last *genuinely* applied.

Confirmed live via a full origin-to-symptom trace (session restarted 00:45:16): `'Pyke'` applied
successfully at `00:46:16,670`; a click to `'Shade of the Evening'` at `00:46:19,867` landed while
a hover-preview fade was still finishing, got stashed; every subsequent attempt to apply it hit the
no-op guard from `00:46:20,271` through `00:47:35,799` — over 75 seconds, verified via a temporary
`_theme_ever_applied` marker (set only inside `_apply_stylesheets`) that stayed pinned at `'Pyke'`
the entire window. A user screenshot taken inside that window showed exactly the split this predicts:
Library/Stats/Tags/Sleep's per-button colors still on `'Pyke'`, main window/Speed/Sleep's own panel
chrome already on `'Shade of the Evening'` (the fast pass and deferred pass diverged, both stuck on
whatever they'd each last genuinely painted).

Two wrong hypotheses were formed and retracted live before landing on this: (1) "chrome has an
independent trigger, buttons don't" — traced and found false, `sleep_panel.setStyleSheet()` (chrome)
is gated by the exact same guard as everything else; (2) "the deferred-restyle batch's last-write-wins
coalescing raced the fast pass" — retracted immediately on checking the rotated log file, which showed
the deferred pass *did* genuinely complete for the stuck theme minutes earlier; the actual defect was
purely the guard-masking mechanism above, confirmed by a third trace showing `_on_fade_finished`
draining a stash whose fields had already been "poisoned" by an earlier hover call to the same theme
name.

**Fix:** consolidated both writes into one method, `_mark_theme_applied(theme_name, hover)`, called
only immediately after `_apply_stylesheets` has genuinely run — at all four real-apply call sites
(`_on_theme_changed`'s three branches: themes-tab overlay fade, slider-animated fade, instant/no-fade;
plus `apply_full_pass`, a separate startup-only path with its own direct `_apply_stylesheets` call,
reached both from `_on_theme_changed`'s early branch and directly from `app.py`). The two old
unconditional write sites (`_is_hover_active = hover` before the stash-decision branches;
`_active_display_theme_internal = theme_name` right after them, still before the real apply) were
deleted, not left as fallbacks. The guard's own comparison logic was deliberately left untouched —
an explicit design check confirmed the fix needed to be entirely about *when* the fields are
written, not *how* they're compared; if the guard itself had needed changing too, that would have
meant the write-timing fix wasn't sufficient on its own. A full read-site audit (every consumer of
either field in `theme_manager.py`) found no code path anywhere that depends on the old pre-apply
timing, so no second/staging field was needed.

### Bug 2 — hover previews could be replayed through the same path as a genuine selection

Separate, unrelated mechanism, found while live-testing Bug 1's fix. `get_base_stylesheet`'s narrow
scope (main window, `QToolTip`, `status_banner`, the overall progress slider, chapter dropdown,
`undo_overlay`) exists specifically so a hover preview never has to walk the full panel tree — the
same cost `_schedule_deferred_restyle`'s deferred-batch split exists to avoid for genuine changes.
This confinement was never actually enforced at the one place it needed to be: none of the three
`_pending_fade_call` drain sites (`_on_fade_finished`, `snap_theme_forward`, `complete_main_fade`)
checked whether the stashed call was a hover preview before replaying it. A transient cursor
pass-over a swatch (not a deliberate hover-select, just transit on the way to dismissing a panel)
fires a real `hover=True` call; if that call got stashed (a previous selection's fade still
settling) and was later drained on panel-dismiss, it got applied through the FULL path — reaching
`_schedule_deferred_restyle` and every panel-level stylesheet, exactly like a real click would.

Confirmed via a screen-recorded live repro (`02:06:46`–`02:07:11`): user selected `Melnibonéan`
(genuine), then moved the cursor toward the dismiss direction, transiting over `Urras` for a
fraction of a second; `Urras`'s hover call got stashed (the previous fade was still finishing);
`snap_theme_forward`'s drain (fixed under Bug 1 to correctly reach the deferred pass) applied it
with `hover=True` at `02:06:48,161` — confirmed via `[SNAP-DRAIN-TRACE] ... theme_name='Urras'
hover=True`. Sleep/Stats panels visibly showed `Urras`-derived colors afterward, despite `Urras`
never being a genuine selection.

**Fix:** at all three drain sites, check the stashed call's `hover` flag before replaying it. If
`True`, discard — clear `_pending_fade_call`, do not call `_on_theme_changed` at all. There is no
correct later moment to apply an abandoned preview; by the time any of these drains run, the user
has moved on (cursor elsewhere, or the panel that was showing the preview has already closed).
Recorded as a permanent architectural rule in CLAUDE.md: *"Hover-preview theme application must
never reach `_schedule_deferred_restyle` or any panel-level stylesheet... a preview must never be
replayed through the same apply path as a genuine selection."* One adjacent check done before
implementing: `user_initiated=False` (automatic rotation, automatic cover-theme changes) is a
real, separate flag from `hover` and was confirmed to never conflict with it — every automatic-change
call site always passes `hover=False`, so the hover-only discard check can't accidentally swallow
a legitimate automatic theme change.

### Live verification — both fixes together, not just reasoned to compose

Per explicit instruction, the two fixes were verified running together over a real 15-minute mixed
interaction session (03:00–03:15), not just argued to be compatible. Log analysis: 55 hover-flagged
stashes correctly discarded across all three drain sites (54 via `_on_fade_finished`, 1 via
`snap_theme_forward`) with zero reaching the apply path; zero occurrences of the actual Bug 1
signature (`hover=False` + the diagnostic `SUSPECT_MASKED_STASH=True` marker). 15 occurrences of
`SUSPECT_MASKED_STASH=True` did appear, but all 15 were `hover=True` — traced and found to be a
false-positive gap in the diagnostic marker itself (it doesn't distinguish "guard blocked a real
pending apply" from "guard correctly no-op'd a redundant hover re-entry," and only non-hover
applies ever update the `_theme_ever_applied` comparison value, so any hover no-op will always look
like a mismatch even when it's completely benign). This is a diagnostic-precision gap only — it
does not affect app behavior — logged as a follow-up in TODO.md, not fixed this session.

**Diagnostic logging from this investigation (`[GUARD-MASK-TRACE]`, `[FADE-FINISHED-TRACE]`,
`[SNAP-DRAIN-TRACE]`, `_theme_ever_applied`) is deliberately left in place**, per explicit
instruction — useful for confirming the fix holds under future real usage, and for diagnosing the
`SUSPECT_MASKED_STASH` false-positive follow-up.

---

## Theme-bleed: two independent causes found and closed via a read-only audit + two fix passes; hover-pulsate confirmed gone live, one of at least three causes still open, and a new responsiveness regression is unexplained (2026-07-20)

**Context:** theme-bleed (hover-preview colors leaking into `content_container`/`main_window`) had
been investigated across multiple sessions via direct trigger-hunting (see the `complete_main_fade`
entries elsewhere in this file) with partial, unverified fixes. Rather than continue hunting
triggers one at a time, a read-only audit (`Agent` tool, `Explore` subagent) was run first to map
every code path by which preview/hover theme state could reach those two widgets, before any fix
was attempted — full detail in `Audit_ThemeReach_260720.md` (not reproduced here; this entry covers
what was actually implemented from it).

**Audit findings (summary):** the audit inventoried every `setStyleSheet()` call site on
`content_container`/`main_window` and their descendants, checked each against CLAUDE.md's
invariant #4 (`_apply_stylesheets` is the sole dispatcher), and traced whether hover state could
reach those two widgets. It found one confirmed invariant-#4 bypass and one separate,
structurally-independent pixel-capture mechanism — see the two fix passes below, each named after
the audit's own path label.

### Pass 1 — state-read bypass (audit "Path A"), landed but confirmed insufficient alone

`MainWindow._set_bg_suppressed` (`app.py`) read `theme_manager._active_display_theme` directly and
called `content_container.setStyleSheet(...)` outside `_apply_stylesheets` entirely — a real
bypass of invariant #4. It derived the theme name from `_active_display_theme` with **no check of
`_is_hover_active`**, and is invoked from `library_controller.apply_library_state` on book-load and
empty-state transitions — a call graph with zero coupling to `ThemeManager`'s fade/hover state
machine, so it can fire at any moment, including mid-hover-preview. The audit confirmed via a
whole-repo grep that `_active_display_theme` had no writes outside `theme_manager.py` and exactly
one cross-file read (this one) — so this was a clean field-privatization, not a flat replacement
needing to accommodate some other legitimate external consumer.

**Fix:** renamed the field to `_active_display_theme_internal` (20 occurrences within
`theme_manager.py`, pure rename, no behavior change) and added
`ThemeManager.get_active_theme()` — a resolving accessor that returns the actual active theme
(the live cover theme dict if one is active, else `_current_theme_name`) while a hover preview is
live, and the raw internal value otherwise. Return type matches the field's own type (`str` or a
cover-theme `dict`) since `_set_bg_suppressed`'s existing cover-theme-flash-avoidance logic depends
on that. `_set_bg_suppressed` now calls the accessor instead of reading the field. Verified via a
repo-wide grep after the rename that nothing else referenced the old bare name in code (two
comment-only hits: the accessor's own historical docstring, and an unrelated English-language
comment in `library.py` that happens to contain the string). 212/216 tests passed (4 pre-existing,
confirmed-unrelated failures in `test_cover_theme_pending.py`, verified via `git stash` comparison
against the unmodified branch tip).

**Live test result (same day): insufficient alone.** The user tested with blur ON immediately after
this fix landed and reported the hover-pulsate bleed was still visibly present (screenshot: the
blurred transport-bar area still showing the hovered theme's colors). This was the first hard
evidence that the live bug was actually Mechanism B (below), not this bypass — Pass 1 was a real,
necessary fix (closes a genuine invariant-#4 violation) but was not the live cause of what the user
was actually seeing.

### Pass 2 — hover-unaware blur grab (audit "Path D" / "Mechanism B"), landed same day, fixed the visible symptom

Traced directly from the user's screenshot rather than re-guessing. Mechanism, confirmed by reading
the code (not assumed): a hover-preview restyle calls `_apply_stylesheets(hover=True)`, which
rewrites `content_container`'s stylesheet (`theme_manager.py` call site). Rewriting a parent's
stylesheet forces Qt to repolish/repaint every styled descendant — including all 12 widgets
`TransportBarBlurOverlay` tracks (`transport_bar_blur.py`: chapter labels, sliders, buttons, speed
button). Confirmed these widgets have no stylesheet of their own (grepped `theme_manager.py` for
direct `setStyleSheet`/`update()`/`polish()` calls on any of them — none found), so their repaint is
a deterministic consequence of the `content_container` restyle, not incidental timing overlap with
something else (e.g. the marquee label or a slider animation).

`_DirtyRectTracker.eventFilter` (`transport_bar_blur.py`) sees these repaints as real `QEvent.Paint`
events — correctly, by its own design, since it has no way to distinguish "restyled because of a
genuine theme change" from "restyled because of a hover preview" — and calls
`TransportBarBlurOverlay._schedule_refresh()`, which arms a coalescing `QTimer.singleShot(0, ...)`.
`refresh_dirty()` then calls `_grab_and_blur()`, which grabs `main_window`'s **live composited
frame at that exact instant** — showing the hovered theme's colors — and bakes it into the overlay
pixmap. Confirmed via grep: `transport_bar_blur.py` had **zero** references to `_is_hover_active`
anywhere before this fix — no part of the blur pipeline had any hover awareness at all. This also
explained a second symptom the user reported independently ("panels are slow... the grab has very
high frequency"): every hover tick that restyles `content_container` fires a repaint on all 12
tracked widgets, which is 12 potential dirty-triggering paints per hover step, not one.

**Fix:** added a gate in `refresh_dirty()` (`transport_bar_blur.py`), placed immediately before the
existing `_POST_RESTYLE_COOLDOWN_S` cooldown gate: early-return while
`theme_manager._is_hover_active` is `True`, without calling `take_dirty_union()` — so the
accumulated dirty rect is not consumed or lost, just left for a later real paint to pick up (same
non-destructive-decline pattern the pre-existing cooldown gate already uses, per its own comment).

**Hover-end safety, traced explicitly before shipping (not assumed by analogy):** the risk with a
"skip while hovering" gate is that if nothing ever re-triggers a refresh after hover ends, the
overlay could go stale indefinitely — a real concern given the separate, still-open frozen-overlay
bug (below). Traced the actual resume path: `_on_theme_unhovered()` (`theme_manager.py`) calls
`_on_theme_changed(..., hover=False, fade_ms=_SNAPBACK_FADE_MS)` — a normal restyle. Critically,
`_on_theme_changed` sets `self._is_hover_active = hover` **unconditionally, before** any of its
animation/panel guards run (line ~458, ahead of the fade/panel-animation branches) — so by the time
this snapback restyle actually repaints `content_container` and its descendants, `_is_hover_active`
is already `False`. That repaint fires a fresh, real `QEvent.Paint` on the tracked widgets, which
re-arms `_schedule_refresh()` and lands in `refresh_dirty()` with the new gate now clear — hover-end
self-corrects through the ordinary event-driven path. No separate `force_refresh_now`-style forced
call was needed or added.

**Known gap found in the same code path, deliberately NOT fixed this session — logged here in full
so a future session doesn't have to re-derive it:** `refresh_dirty()`'s early-return gates (both the
new hover gate and the pre-existing `_POST_RESTYLE_COOLDOWN_S` gate) do not re-arm themselves.
`_schedule_refresh()`'s `QTimer.singleShot(0, self.refresh_dirty)` fires exactly once per arm; if
`refresh_dirty()` declines via either gate, `_refresh_pending` was already reset to `False` at the
top of the method (before either gate is checked), and nothing schedules another attempt. A
declined tick is retried **only if some later real `QEvent.Paint` fires on a tracked widget** — the
hover case verified above is safe specifically because hover-end reliably produces exactly such a
paint, but this is a property of what triggered the decline, not a general guarantee the gate
mechanism provides. If a tick is ever declined for a reason that is NOT followed by any further
repaint, the accumulated dirty union sits in the tracker uncomposited indefinitely, with no error
and no future retry — visually indistinguishable from the separately-tracked, still-unexplained
frozen-overlay bug (see the "blur overlay's refresh timer stops firing permanently" entry
elsewhere in this file / TODO.md). Not investigated further, not touched, per explicit scope
instruction to stay narrowly on the hover gate this session.

**Live test result:** user confirmed the hover-pulsate bleed is visually gone. **Also reported: general
UI responsiveness is now slow.** Not yet triaged — candidate causes not yet checked: whether the new
gate's decline path (or the resulting change in when/how often grabs actually happen) is adding
overhead somewhere, or whether this is unrelated to today's changes entirely. Needs live
profiling before attributing a cause; not assumed to be the hover gate just because of proximity in
time.

**Verification status, stated plainly:** the specific symptom the user reported (hover-pulsate into
the blurred area) is confirmed gone live. This is NOT the same as "theme-bleed is fixed" — the
audit identified at least three independent causes, and `complete_main_fade()`'s stale-fallback-
reapply path (a separate, already-partially-mitigated, still-unverified mechanism from an earlier
session — see that entry elsewhere in this file) was neither touched nor re-verified this session.
No soak test (blur on, repeated hover+panel-open cycles, multi-minute stretches) has been run
against either of today's two fixes. Test suite: 212/216 passed both times today (4 pre-existing,
confirmed-unrelated failures, unchanged by either fix).

---

## FIXED and live-verified with raw before/after tick data: transport-bar blur reworked from a 1200ms polling timer to event-driven refresh; the rework itself introduced a feedback loop, closed with a measured wall-clock suppression window (2026-07-20)

**Motivation:** the punch-through-flash investigation (see the entry below) found the polling timer's
`refresh_dirty()` was the mechanism colliding with Qt's post-restyle repaint backlog, but only some of
those collisions were on ticks with real dirty content — many were the timer firing on schedule and
finding nothing to do, an unnecessary cost layered on top of the real one. Direction: replace the poll
with event-driven refresh — `_DirtyRectTracker`'s existing `QEvent.Paint` observation (already
correctly wired, just previously only used to accumulate state a poll would later consume) now calls
`TransportBarBlurOverlay._schedule_refresh()` directly on every real paint, which arms a coalescing
`QTimer.singleShot(0, ...)` — never a fixed interval, never fires unless something genuinely repainted
first. `_REFRESH_INTERVAL_MS`/`_refresh_timer` removed entirely. A one-time forced refresh was added on
settings-tab switch (`QTabWidget.currentChanged`, wired in `panels.py`) since a tab switch changes
`settings_panel`'s own visible content without generating a `Paint` event on any of the transport bar's
own tracked widgets.

**Bug introduced by the rework, found live during its own testing, fixed same session:**
`_grab_and_blur()`'s existing `hide()`→`main_window.grab()`→`show()` cycle on the currently-open panel
(done to keep the panel's own translucent wash out of the captured pixels — unchanged, pre-existing
behavior) forces Qt to repaint the tracked transport-bar widgets underneath the panel, since they're
momentarily exposed/re-occluded. Under the OLD polling design this was invisible — the timer didn't
care what caused dirtiness. Under the NEW event-driven design, the tracker saw these self-inflicted
repaints as real content changes and called `_schedule_refresh()` again, which called
`_grab_and_blur()` again, which hid/showed the panel again, causing another self-inflicted repaint —
an unbounded feedback loop. Confirmed live: continuous `COMPOSITED` ticks firing far faster than any
real content could plausibly be changing, described directly by the user as visible stutter and "no
hover" (the overlay was refreshing so fast the constant grab activity itself froze normal interaction).

**First fix attempt, tried and confirmed insufficient:** a plain boolean (`_grab_in_progress`) set
`True` at the start of the hide→grab→show sequence and cleared in a `finally` block the instant the
sequence's Python call returned. Did NOT stop the loop — confirmed live it kept ticking. Root cause of
that failure, found via a direct isolated PySide6 measurement (not assumed): Qt does not deliver every
repaint this sequence triggers synchronously. One paint lands inline (~1ms), but 1-2 more land on
LATER event-loop turns. A follow-up measurement using wall-clock timestamps (not turn counts) found
every deferred paint arrives within **~20ms** of the sequence, consistently, across a 200ms observation
window — turn-counting was rejected as a sizing method because a separate measurement showed the paint
count still climbing across multiple `singleShot(0)` turns (1→2→2→3), not settling after exactly one.

**Fix that worked:** `_grab_suppress_until`, a `perf_counter()` deadline (not a boolean, not a turn
count) — set to `now + 50ms` at the START of the hide→grab→show sequence and re-extended to
`now + 50ms` again in the `finally` block after it completes. `_DirtyRectTracker` drops any paint event
observed while `time.perf_counter() < _grab_suppress_until` — not queued, simply dropped, accepted
tradeoff being at most one hover-step of staleness in the cached blur (never the live, unblurred UI),
self-correcting on the next real paint or forced refresh. 50ms was chosen with real margin over the
measured ~20ms deferred-paint window.

**Verification — raw tick-interval data, before and after, on direct request (not narrative
description):**

BEFORE (pre-fix, `03:21:04`, 20 consecutive `COMPOSITED` ticks), intervals in ms:
```
33.0, 17.0, 19.0, 14.0, 20.0, 15.0, 15.0, 17.0, 27.0, 17.0, 27.0, 16.0, 21.0, 15.0, 17.0, 12.0, 17.0, 9.0, 16.0
```
avg 18.1ms, min 9.0ms, max 33.0ms — the tight machine-gunning loop.

AFTER (post-fix, `04:18:03` onward, 17 consecutive `COMPOSITED` ticks), intervals in ms:
```
61.0, 127.0, 1554.0, 64.0, 63.0, 69.0, 65.0, 65.0, 75.0, 1222.0, 1393.0, 1457.0, 2035.0, 1390.0, 2081.0, 1391.0
```
avg 819.5ms, min 61.0ms, max 2081.0ms. Not uniform — two clusters: a short run of ~60-130ms intervals
(the settings-panel slide-in animation's own frame cadence, several real repaints in quick succession)
followed by long ~1.2-2.1 SECOND gaps (steady state, driven by the separate spurious-`enterEvent` bug's
own ~1.3-1.4s cycle — see that entry below). Minimum post-fix interval (61ms) is more than 3x the
pre-fix AVERAGE (18ms); the tight repeating sub-40ms pattern is gone entirely. Confirmed live by the
user as no longer producing stutter/frozen-hover.

**What this does NOT fix, stated plainly:** the residual punch-through-flash collision (a real,
event-driven grab landing right after a real restyle) is unchanged — this rework only removed the
*unnecessary* polling-driven grab volume, never claimed to eliminate the collision itself. See the
entry below for that bug's continued-open status, now confirmed to be getting hit far more often than
normal usage would produce because of the separate spurious-`enterEvent` bug (see further below).

---

## STILL OPEN, NOT FIXED: the "heartbeat" (`ThemeItem.enterEvent` firing repeatedly on a stationary cursor) has TWO independent spurious triggers — a guard against one is in place, the bug still reproduces because the second trigger is unidentified (2026-07-20)

**Do not describe this as fixed, partially or otherwise. The reported symptom is unchanged: the cursor
still triggers repeated spurious hover cycles while stationary.** A guard was added against one of the
two confirmed triggers, and that guard measurably works for the case it targets (verified via log:
alternating cycles show it correctly suppressing the trigger it covers) — but the bug as experienced is
not resolved, because a second, independent trigger produces the same symptom on the cycles the guard
doesn't cover. "One of two causes addressed" is not the same as "fixed" when the second cause alone is
sufficient to keep reproducing the bug in full.

**This entry replaces two earlier, sequentially disproven theories in this same investigation — both
retracted here explicitly, not silently superseded, per the session's own standard:**

1. **First theory (disproven):** `update_theme_list_visuals()`'s `btn.style().unpolish()`/`.polish()`
   calls were the cause. A fix was implemented (only repolish a button whose `selected`/`active_display`
   state actually changed) and tested live: the fix's own instrumentation showed **`repolished 0/58
   buttons`** on every single cycle — zero repolish calls happening at all — while the spurious
   `enterEvent` kept firing on the identical schedule. **This conclusively disproves the theory**, not
   merely fails to confirm it. The guard itself was kept (it's a harmless, legitimate minor
   optimization independent of this bug), but the comment attributing it to fixing the heartbeat was
   corrected.
2. **Second theory (real, but only half the picture):** checkpoint-level tracing across every
   `_apply_stylesheets` call in the log, with zero exceptions across the sample, showed the spurious
   `enterEvent` landing 8-15ms after `settings_panel.setStyleSheet(ss_panels)` completes (specifically
   — NOT `mw.setStyleSheet(base)`, which was checked and ruled out: its completion-to-enterEvent gap was
   86-98ms, ~6-10x longer and inconsistent with being the direct trigger). `settings_panel` is the real,
   direct Qt ancestor of every `ThemeItem` — its `setStyleSheet()` call forces a style/geometry cascade
   through that whole subtree, re-evaluating hit-testing for whatever the cursor rests on.

**A guard was implemented against trigger #2 and is live-verified to suppress that specific trigger when
it fires:** a two-signal guard in `ThemeItem.enterEvent` (`title_bar.py`) —
`main_window._spurious_enter_guard_until` (a `perf_counter()` deadline set/cleared via `try/finally`
around `settings_panel.setStyleSheet()` in `_apply_stylesheets`, `theme_manager.py`) combined with a
cursor-position match against the position `ThemeItem`'s own `leaveEvent` reported moments earlier.
**Before implementing, the investigation explicitly checked (per direct instruction) whether "no
preceding leaveEvent" alone would have been a safe discriminator — it would NOT have been:** live
logging showed the spurious cascade ALSO fires a fully realistic-looking `leaveEvent` immediately before
every spurious `enterEvent`, at the identical cursor position, indistinguishable by event shape alone
from a genuine quick leave-and-return. This is why the time-window signal (derived from code under our
control) is the load-bearing one, with cursor-position as a secondary check — not the other way around.
Both signals combined were required.

**The reported bug is NOT fixed. Reproducing the stationary-hover scenario after this change shows the
heartbeat still happening, unchanged from the user's perspective — the cursor still triggers repeated
spurious hover cycles while stationary.** What the log shows is that the guard correctly suppresses one
of the two triggers, alternating with a second, unguarded trigger passing through:
```
leaveEvent  pos=(60, 208)
enterEvent  SUPPRESSED (synthetic)  in_window=True   pos_matches=True   <- one trigger, suppressed
...
leaveEvent  pos=(60, 208)
enterEvent  PASSED       (real)     in_window=False  pos_matches=True   <- second, unguarded trigger
```
The `PASSED` case is a **second, distinct spurious leave/enter pair** — confirmed NOT caused by either
`_apply_stylesheets` call (`hover=False` snapback or `hover=True` preview): it fires ~500ms after the
guarded `hover=False` restyle completes, and — critically — **before** the next `hover=True` restyle
even begins (confirmed via timestamp ordering, not assumed). It correlates with two back-to-back
`_on_theme_changed: EARLY-RETURN no-op guard` lines for the already-active theme, appearing immediately
before the spurious leave/enter pair each time — but what triggers THOSE calls (candidates not yet
checked: the 700ms `_panel_guard_timer` retry mechanism, or something else entirely) was not identified
before the session ended. **Since either trigger alone reproduces the full user-visible symptom, this
change does not resolve the bug — it only demonstrates that one of its (at least two) causes is now
correctly handled.**

**Representative log excerpt, the WORKING half of the fix** (timestamps abbreviated to HH:MM:SS,mmm):
```
40,274  leaveEvent  pos=(60, 208)
40,517  enterEvent SUPPRESSED (synthetic)  guard_until=40280.523397  last_leave_pos=(60, 208)
```

**Representative log excerpt, the UNFIXED second trigger:**
```
41,038  leaveEvent  pos=(60, 208)
41,038  [_on_theme_changed EARLY-RETURN no-op guard] theme_name='Urras' (x2, back to back)
41,047  enterEvent PASSED (real)  in_window=False  guard_until=40280.523397 (long expired)
41,128  [hover debounce] firing preview for 'Sitting in the Wing Chair' 80.8ms after last enterEvent
```

**Flagged as a possible wider pattern, per the escalation instructions — NOT investigated:** any other
call site in the codebase that calls `style().unpolish()`/`.polish()`, or any other full-subtree
`setStyleSheet()` call, on a widget the cursor could plausibly be resting over could have a similar
latent issue. Not searched for beyond the two call sites checked here (`update_theme_list_visuals`,
`_apply_stylesheets`'s `settings_panel`/`mw` calls). See `DEBT_INVENTORY.md`.

**Diagnostic logging status:** `ThemeItem.enterEvent`/`leaveEvent` (`title_bar.py`) log
`[ENTEREVENT-TRACE]` on every firing, including whether the guard suppressed or passed the event and
why (`in_window`, `pos_matches`, `guard_until`, `last_leave_pos`) — **left in place deliberately**, not
temporary, since the bug is only partially fixed and this logging is what a future session will need
to find the second trigger. Do not remove until the second trigger is found and fixed.

**Process note, for the record:** this investigation went through three sequential theories before
landing on a real (if partial) fix — each one tested live and either disproven outright (theory 1) or
found to explain only part of the symptom (theory 2/the shipped fix). The session was explicit at each
step about which claims were confirmed by log evidence versus still theoretical, and retracted the
first theory outright rather than quietly moving past it. The user's own insistence on checking the
leaveEvent-reliability assumption BEFORE implementing (rather than after) caught a real gap in the
originally-proposed single-signal design before it shipped.

---

## NEW BUG, confirmed real via one accidental live occurrence, ROOT CAUSE NOT CONFIRMED — "the timer stopped" was this investigation's own first guess and static analysis found a gap in that claim, not evidence for it: the blur overlay froze on stale content while the app kept running, cause unknown (2026-07-20)

**Confirmed via direct log+screenshot correlation:** at `02:00:29,040`, `show_for_panel ENTRY
panel='stats_panel' self._active=False` → mandatory first-pass grab succeeds → `show_for_panel DONE
panel='stats_panel'`. Normal, successful open, no error logged. After that `DONE` line, zero further
`transport_bar_blur` log activity of any kind appears for over a minute, while the app kept running and
the theme kept changing live via `T` rotation — confirmed by a screenshot taken at ~`02:02:xx` showing
the overlay's grabbed transport-bar buttons in a blue theme while the surrounding, unblurred chrome had
moved on to pink/magenta.

**Correction, made during this same investigation's static analysis pass — read before trusting
anything above about "the timer stopped":** the title/framing above ("refresh timer stops firing
permanently") was this investigation's initial hypothesis, stated too confidently before the code was
actually read. `refresh_dirty()` (the timer's connected slot), as it existed at the time of the
occurrence, had **multiple silent early-return paths and zero log statements anywhere in the method** —
meaning a healthy timer firing exactly on schedule every 1200ms, hitting an early return every single
tick (e.g. because nothing dirtied the tracked widgets), would ALSO produce exactly zero log output.
**"No log lines after `show_for_panel DONE`" was never actually evidence the timer died** — it is
equally consistent with the timer running perfectly and correctly finding nothing to do. This
correction is being stated explicitly and separately, not folded silently into a revised theory,
because presenting an unconfirmed claim as confirmed is exactly the failure this session already had
to walk back once tonight on a different bug (see the theme-bleed entry below) — the same standard
applies here.

**What IS still a real, open question, now correctly scoped:** whether the overlay's pixmap content
was frozen (confirmed, via the screenshot's two-tone mismatch) because (a) the timer genuinely stopped
firing, (b) the timer kept firing but `_tracker`'s dirty-union stayed empty every tick because the
tracked widgets' `QEvent.Paint` events never fired during this particular T-rotation-while-Stats-open
sequence, or (c) something else. Static analysis (below) ranks these candidates but does NOT resolve
between (a) and (b) — that requires the newly-added permanent logging (see the entry below) to catch
the next real occurrence.

This is a third, distinct bug from both the punch-through flash and the theme-bleed-into-main-window
issue documented elsewhere in this file — found by accident while trying to reproduce the theme-bleed
bug, not something being deliberately investigated. **Not reliably reproducible on demand** — caught
once, by the user happening to screenshot it.

---

## Static analysis + permanent logging for the frozen-overlay bug above — ranked candidates, no confirmed root cause (2026-07-20)

**Method note, per explicit instruction:** this investigation deliberately did NOT prioritize live
reproduction (the bug isn't reliably reproducible on demand) — static code reading plus permanent
logging for the next accidental occurrence, per the user's explicit direction.

**Ruled out by direct code reading:**
- **`_refresh_timer.start()` never being called** — ruled out for the one occurrence caught: `.start()`
  (`transport_bar_blur.py`, `show_for_panel`) is the line immediately before the `show_for_panel DONE`
  log line, which DID appear in the log. Since `DONE` logged, `.start()` already ran.
- **An unhandled exception in the `refresh_dirty` slot silently stopping the `QTimer`** — tested
  directly in an isolated PySide6 harness (a `QTimer` connected to a slot that raises on its 2nd tick):
  the exception's traceback prints to stderr but the **timer keeps firing on every subsequent tick
  regardless** (confirmed: 10 ticks observed over a 500ms window despite the slot raising on tick 2,
  `timer.isActive()` still `True` at the end). PySide6/Qt does not stop or disconnect a timer because
  its connected slot raised. This rules out the specific "exception kills the timer" mechanism named in
  the investigation prompt.
- **The timer object being garbage-collected or reparented** — `self._refresh_timer = QTimer(main_window)`
  is parented to `main_window`, which lives for the app's full lifetime; no reparenting exists anywhere
  in the file.
- **A second/overlapping `show_for_panel` call silently stopping-without-restarting the timer** — ruled
  out for this mechanism specifically: `show_for_panel` early-returns immediately if `self._active` is
  already `True` (now logged — see below), a pure no-op that never touches the timer. The only place
  `.stop()` is called at all is `hide_for_panel()`, which is a full, symmetric teardown (also hides the
  overlay and clears `_active`) — inconsistent with the screenshot showing a visibly *shown*, frozen
  overlay rather than a missing one, so this path doesn't fit the observed symptom.

**NOT ruled out, ranked by plausibility given the actual code:**
1. **(Most plausible) The tracked widgets simply never repainted during this specific sequence, so
   `_tracker`'s dirty-union legitimately stayed empty every tick — no bug, working as designed, just an
   unexpected input.** `_DirtyRectTracker.eventFilter` only marks a rect dirty on a real `QEvent.Paint`
   for one of the 12 tracked widgets; a `T`-rotation theme change does not directly force those specific
   widgets to repaint, and per every restyle-timing finding elsewhere in this file tonight, Qt's repaint
   scheduling for a stylesheet change is deferred/batched and not guaranteed to hit any specific widget
   promptly. If the tracked widgets' pixels didn't visually need to change (or their repaint kept
   getting deferred past the timer's 1200ms tick), the tracker would never report anything dirty, and
   `refresh_dirty()` would correctly and silently no-op forever — which matches the total-silence
   symptom without requiring the timer to have failed at all. Complicating this ranking: the SAME log
   window shows multiple successful `_grab_and_blur`/dirty-composite cycles in the ~40 seconds
   immediately BEFORE the freeze (`01:59:48` through `02:00:29`), meaning dirty events clearly were
   flowing correctly moments earlier in the same session — so if this is the explanation, something
   about the specific `show_for_panel` at `02:00:29` (a fresh Stats-panel open, resetting the tracker)
   would need to have left the newly re-armed tracker unable to see further paints, which is not fully
   explained by "restyle repaint scheduling is generally deferred" alone.
2. **A genuine timer death after some N ticks, mechanism unidentified.** Not ruled out by the exception
   test above (that test only covers ONE specific mechanism); Qt's `QTimer` can stop for other reasons
   this investigation didn't have code-level evidence to check (e.g. event-loop starvation from
   elsewhere in the app, though nothing in this codebase's own code should cause that for a plain
   interval timer). Ranked below (1) only because (1) is directly supported by a real, cited code gap
   (`_DirtyRectTracker`'s paint-event dependency), while this candidate has no specific supporting code
   citation — it's the residual "something else" category.

**Permanent logging added (required deliverable, done regardless of the above ranking):**
`transport_bar_blur.py` now logs, at all times (not a temporary debug flag): every `_refresh_timer
.start()` call with `isActive()`/`interval()` confirmation; every `refresh_dirty()` tick with a running
counter and, for every early-return path, which specific reason it took (`inactive_or_no_tracker`,
`cooldown_gate`, `no_dirty`, `dirty_empty_after_intersect`, `overlay_pixmap_null`), or `COMPOSITED` with
the dirty rect on a real update; every `hide_for_panel()` entry with the timer's `isActive()` state and
total tick count for that session; every `show_for_panel` early-return reason
(`already_active`/`empty_bounding_rect`/`empty_intersection_with_panel`). The next occurrence of this
bug will show either (a) `refresh_dirty` ticks stopping entirely (supports timer death) or (b)
`refresh_dirty` ticks continuing indefinitely with `reason=no_dirty` (supports candidate 1 above,
tracker never seeing paints) — this distinction was previously invisible and is now directly
diagnosable from existing logs without a deliberate live repro.

---

## UNTESTED code change, NOT VERIFIED, NOT COMMITTED: a theory-driven fix for "hovered theme bleeds into the whole live main window" exists in `theme_manager.py`, but has never been tested under the one condition where either bug reproduces (2026-07-19/20)

**Status, stated plainly because an earlier version of this entry claimed the opposite: this fix has
NOT been verified. Do not trust the "FIXED"/"live-tested"/"verified" language that was previously
here — it was wrong, and the assistant said so directly only after being corrected by the user three
times in a row.**

**What actually happened, precisely:** both bugs (the punch-through flash AND the theme-bleed) only
reproduce with blur ON. The assistant wrote a code change in `complete_main_fade()` (below) intended
to fix the theme-bleed bug, then tested it — but every test that reported "no issues" was run with
**blur OFF**. Blur-off was already independently established, HOURS before this fix was written, as a
condition that eliminates both bugs regardless of any other code change — the user demonstrated this
directly earlier the same session, before touching `complete_main_fade()` at all. Testing the fix with
blur off therefore reproduces a result that was already known and has nothing to do with whether the
fix does anything: it is a control condition, not a test of the change. The assistant repeatedly
described this blur-off "no issues" result as evidence the fix worked — first as "live-tested across
several variations," then, after pushback, as merely lacking one confirmed exercise of the new code
path, and only on a fourth correction did it identify the actual error: there is no test of this fix,
under blur-on, at all. **The user was direct about the pattern this fits: over the course of about a
week, error after error came from confidently asserting things were fixed, correct, or verified
without ground the assertion actually supported — this entry is a fresh, dated instance of exactly
that failure mode, not a one-off.**

**Additionally, per the user (this is why "no reproduction across many tests" was never going to be
meaningful evidence even under the right condition): the theme-bleed bug does not reproduce
reliably or on a fixed timescale.** Sometimes it appears almost immediately; sometimes it has taken
around five minutes of use to surface. A short test session — even run under the correct condition —
finding no recurrence would not be strong evidence of a fix; the absence could just as easily mean the
session wasn't long enough or lucky enough to hit the window. Any future verification attempt needs
to account for this explicitly (e.g. a long-duration soak test with blur on, not a handful of
deliberate hover-then-open attempts) rather than trusting a short session's silence.

**The mechanism this code change targets (recorded as a hypothesis with supporting trace evidence,
NOT as a confirmed fix) — still worth keeping, since the reasoning may well be correct even though the
fix is unverified:**

1. Rapid theme interaction (hovering several swatches in quick succession, or otherwise triggering
   more than one `_on_theme_changed` call before the first one's fade animation finishes) can leave a
   second call stashed in `self._pending_fade_call` (`theme_manager.py`, the `elif _fade_running:`
   branch of `_on_theme_changed`) — by design, meant to be resumed by `_on_fade_finished` once the
   in-flight fade completes naturally.
2. `complete_main_fade()` (`theme_manager.py:765-800`) is called at the top of **every** panel-open
   flow (`_open_stats_flow`, `_open_tags_flow`, `_open_library_flow`, etc., via `panels.py`'s
   `_complete_main_fade()`). Its whole purpose is to instantly finish an in-flight fade before the
   opening panel paints — waiting for the fade's normal ~200-750ms duration is not acceptable there,
   so it force-stops the animation with `.stop()`.
3. `QPropertyAnimation.stop()` does **not** emit Qt's `finished` signal. `_on_fade_finished` is the
   only code that resumes `_pending_fade_call` — so if a panel opened while a fade was in flight AND
   a second theme call was stashed, that stashed call was silently orphaned. It never ran, for that
   hover/theme cycle.
4. `complete_main_fade()` then reapplied the theme itself, using `self._active_display_theme` /
   `self._is_hover_active` (the old line 800) — but both were **stale** at that point, still holding
   whatever theme name and hover state the *orphaned* call would have corrected them to (the write to
   `_active_display_theme` only happens after the `_fade_running` guard the stashed call got caught
   by — see `_on_theme_changed`, line ~498). So the stale reapplication would put the **wrong theme**
   back onto the fast synchronous path (`main_window`/`content_container`/title bar/sidebar/settings/
   speed/sleep) — which would explain "the hovered theme bleeding into the live main window," not a
   captured-frame staleness issue.
5. This would also explain a real, independently-noticed detail: Speed/Sleep panels never looked
   wrong while Stats/Tags/Library did. The fast synchronous path (the one this theory says is
   corrupted) covers Speed/Sleep directly, so they'd always match whatever (possibly wrong) theme the
   fast path had — internally consistent, never visibly mismatched. Stats/Tags/Library are restyled
   via a *separate*, deferred path (`_apply_stylesheets_deferred`) this theory says the bug never
   touches — so they'd keep showing the correct theme, and the mismatch would only be visible as a
   contrast between the two.

**Why disabling blur eliminates both bugs is NOT explained by this theory, and was never chased.**
The mechanism above has no dependency on blur code at all — nothing in `transport_bar_blur.py` is
referenced anywhere in steps 1-5. If this theory is complete, the bug should reproduce with blur off
too, just as reliably (accounting for the 5-minute-worst-case timing above). That was never actually
tested for long enough to mean anything. This is a real, acknowledged gap in the theory, not a minor
footnote — it means the theory itself may be incomplete or wrong, not just unverified in its details.

**The code change (uncommitted, in `theme_manager.py`, `complete_main_fade()`):** checks
`self._pending_fade_call` immediately after clearing `_fade_in_flight` and stopping the animation. If
a call is pending, it consumes it and re-invokes `_on_theme_changed(*pending)` — mirroring
`_on_fade_finished`'s own resume pattern — instead of falling through to the old
`self._apply_stylesheets(self._active_display_theme, hover=self._is_hover_active)` reapplication. The
guard-condition safety argument for why the resumed call can't loop or re-stash (checked against
`_on_theme_changed`'s actual conditions, not by analogy) still holds as a piece of static reasoning —
but static reasoning about safety is not the same as verification that the change fixes the reported
bug, and should not be presented as if it were.

**What an actual verification would require, not yet done:** a soak test — blur ON, repeated hover
and panel-open cycles, run long enough (at least several 5+ minute stretches, given the reported
worst-case reproduction time) to give a real absence-of-recurrence result some weight. Nothing run
tonight meets that bar.

---

## OPEN, root cause partially understood but not fixed: a collision between the blur overlay's grab and Qt's post-theme-restyle repaint backlog causes an intermittent flash during theme hover — three fix attempts tried, all failed or reverted (2026-07-19)

**Symptom, corrected (an earlier draft of this entry described it wrong — see below):** the flash
does NOT require rapid hovering. A single hover-and-hold over one theme swatch in Settings → Themes
is enough to trigger it intermittently, in exactly the region the blur overlay covers (the transport
bar behind the settings panel). What's actually seen is the display flashing **between themes** — it
reads as the main window itself peeking through, not simply "wrong/unthemed color." **It is not
confirmed whether this is the live main window becoming visible for a frame, or the blur overlay's
grabbed/blurred pixmap showing stale-theme content** — the user flagged this ambiguity directly and
it was not resolved before the session ended. Reproducible on a fresh restart, not a one-off. The
user was explicit up front that the overlay/masking machinery added earlier this same session (see
the entry below) must not be assumed unrelated without checking.

**Earlier, inaccurate description (corrected above, kept here so the correction is traceable):**
this entry originally said the bug required "rapidly hovering theme swatches" and described the
symptom as the blur overlay showing "unthemed/wrong-colored content." Both are wrong — hold, not
rapid, triggers it, and the visual is themes flashing against each other / the main window peeking
through, not a flat wrong color. The investigation and fix attempts below were conducted under the
"grab collides with restyle backlog" framing, which may still be a correct mechanism for whatever IS
happening, but the exact visual being explained was mischaracterized while that work was done —
this should be re-verified against the corrected symptom description before trusting any
conclusion below as fully explaining what the user is actually seeing.

**Root cause, confirmed via direct sub-call timing (not guessed):** `TransportBarBlurOverlay
.refresh_dirty()` (`ui/transport_bar_blur.py`) periodically calls `_grab_and_blur()`, which calls
`main_window.grab(padded_rect)`. That `grab()` call is a **synchronous** Qt operation — it forces
any pending/queued repaint or QSS repolish work to resolve immediately, rather than waiting for
Qt's normal event-loop-driven paint cycle. `ThemeManager._apply_stylesheets()` (the method that
runs on every hover-preview tick) leaves exactly this kind of backlog behind it, measured directly
via `[_apply_stylesheets]` debug timing already in the codebase: `total=230-320ms`, dominated by
`mw.setStyleSheet(base)=155-180ms` — which cascades a QSS repolish to every descendant of
`main_window`, not just the top-level rule's own selector. A `grab()` landing inside or shortly
after that backlog window measured **250-350ms**, vs. a normal **5-10ms** grab landing clear of it.
During rapid hover (theme restyles firing roughly every 1.2-1.5s via the hover-debounce timer), a
`grab()` colliding with this window is common, not rare.

**Attempt 1 — `_fade_in_flight` guard (failed, reverted):** gated the grab on `theme_manager
._fade_in_flight` being `False`. Live-tested by the user: "Bug is there." The flag can read `False`
even while the actual repaint backlog is still settling — it tracks the fade-overlay animation's
own state, not Qt's repaint queue, so the two are not reliably correlated. Reverted.

**Attempt 2 — `QTimer.singleShot(0, ...)` deferral (failed, reverted):** deferred the grab call by
one event-loop turn, on the theory that yielding once would let Qt drain the queued repaint work
first. First live test showed improvement (1 spike vs. 4-10 before); a second test showed spikes
got WORSE (9 outliers). Root cause of the failure: the backlog is not queued Qt *event-loop* work
that a `singleShot(0)` turn lets drain — it is **lazy** repaint/repolish state that Qt computes
on-demand, synchronously, the moment something (any `grab()` call, from any caller, at any point)
forces it to resolve. Deferring by one turn does not change whether that forcing still happens; it
can even land the deferred call at a *worse* moment relative to a still-in-flight restyle. Confirmed
via log evidence: a grab firing just 9ms after `_apply_stylesheets`'s own logged completion still
cost 280ms — the "wait a turn" strategy has no mechanism to actually avoid this. Reverted cleanly
(removed the `_composite_dirty()` split method that had been introduced to support the defer).

**Attempt 3 — post-restyle cooldown gate (failed on a real gap, reverted):** added
`ThemeManager._last_apply_stylesheets_at` (a `perf_counter()` timestamp) and a
`_POST_RESTYLE_COOLDOWN_S = 0.4` check in `refresh_dirty()`: skip the tick if less than 400ms has
passed since the last completed restyle, re-checking on the *next* tick without losing the
accumulated dirty union. First version stamped the timestamp only at `_apply_stylesheets`'s *exit*.
Traced live: a `refresh_dirty()` tick could fire and pass the gate (correctly seeing a stale,
>400ms-old timestamp from the *previous* restyle) and then have `_grab_and_blur()` collide with a
**new** restyle that started — and hadn't yet stamped its own timestamp — while the grab was still
running. Fixed by additionally stamping at *entry* (so "a restyle is in flight" becomes visible to
the gate immediately, not only after it finishes) — this half of the fix is real and still in the
code (`theme_manager.py`, both the `__init__` declaration comment and the entry+exit stamp sites).
**But live-retesting after that fix showed the flash still occurring on nearly every restyle**,
traced to a *different*, more fundamental gap the entry-stamp fix cannot close: the gate only
evaluates conditions at the instant `refresh_dirty()` is *called*. `_grab_and_blur()`'s `grab()`
call itself was, at that point in the investigation, believed to take the full 250-350ms — meaning
a restyle could start and complete *while a grab that had already passed the gate was still
running*. No pre-call gate can see a future event. This is why the interval-based mitigation (below)
empirically worked where the gate did not: at `_REFRESH_INTERVAL_MS >= 1200`, a tick rarely lands
close enough to the ~1.2-1.5s hover-restyle cadence to still have a grab exposed when the next
restyle fires — pure timing-alignment luck, not a structural fix.

**The user's own empirical interval sweep — collected independently, without being asked to
interpret it, and initially dismissed by the assistant before being shown to matter:** the user
manually tested `_REFRESH_INTERVAL_MS` values from 50ms to 9000ms and reported raw pass/fail without
theorizing: 50/100ms → flashes; 200ms through 1100ms → flashes; **1200ms → no flashes**; 2000/4000/
9000ms → no flashes. The assistant's first reaction was to assert this timer "is NOT" the blur
code's own refresh timer — wrong, and corrected directly by the user, who had to point out the
assistant's own recent edit to that exact constant before the connection was acknowledged. This
sweep is what ultimately reframed the investigation away from "make the gate smarter" and toward
"find out what's actually inside the ~250-350ms cost" (see below).

**The real bottleneck, found via sub-call profiling — NOT `grab()` itself:** `_grab_and_blur()` was
instrumented with fine-grained timing splitting `overlay.hide()` / `panel.hide()` / the raw
`main_window.grab()` call / `panel.show()` / `overlay.show()` into separate brackets. Result,
confirmed across many live samples: **the raw `grab()` call itself is consistently ~2-3ms** — cheap,
exactly as a small (~300×238px) region should be. The entire 220-270ms cost is inside
**`self._active_panel.hide()`** — hiding the currently-open settings panel before the grab (done so
the grab doesn't capture the panel's own translucent wash baked into the pixels — see the
`main_window`-grab-source fix in the entry below). **This overturns the original diagnosis.** The
"grab() forces the repaint backlog to resolve" theory was wrong in its specific attribution: `grab()`
was never the expensive call. `hide()` on the panel's subtree is. The mechanism for *why* `hide()`
specifically costs 220-270ms (whether it's the same repolish-backlog phenomenon, attributed to the
wrong call, or something else entirely — e.g. `_release_panel_focus`'s focus-transfer work, or a
`hideEvent` side effect) was **not** further diagnosed before the next attempt (below) was tried and
had to be reverted for an unrelated, more serious reason.

**Attempt 4 — grab `content_container` directly instead of `main_window`, avoiding the panel
hide()/show() entirely (tried and REVERTED — broke theme hover-preview/snapback):** since
`content_container` (unlike `main_window`) does not contain the panel in its subtree at all, grabbing
it directly removes the need to hide the panel before every grab. This reintroduces the *original*
bug this session's first entry (below) already fixed — `content_container` has no styled background
of its own, so a bare grab would again return Qt's default palette grey instead of the theme's real
color — so the fix additionally read `theme_manager.get_current_theme()['bg_main']` and painted it
as an explicit solid-fill base layer under the grabbed content before blurring, rather than relying
on any ancestor's painted background. Implementation composited the (possibly `grab()`-clamped, since
`content_container` is smaller than `main_window` and the padded rect can extend past its own
bounds) grabbed pixmap onto a `bg_main`-filled canvas at the correct offset, then blurred.

Two live-confirmed problems, in order found:

1. **Geometry/DPI bug (partially fixed before problem 2 was found):** the first version came back
   visibly larger and shifted right compared to the real transport bar underneath. Root cause:
   `QPixmap.size()` returns **device**-pixel dimensions; a plain `QPixmap(padded_rect.size())`
   defaults to `devicePixelRatio()==1.0`, so drawing a DPR>1 `grab()` result onto it (or building a
   same-shaped output pixmap in `_blur_pixmap`) reads as too-large/shifted to every downstream
   consumer. Fixed by explicitly stamping `setDevicePixelRatio()` on both the compositing canvas (in
   `_grab_and_blur`) and the blur output pixmap (in `_blur_pixmap`) to match the source grab's DPR,
   and computing `QGraphicsScene.render()`'s target rect in logical (DPR-divided) coordinates. This
   half of the fix was verified correct in isolation (geometry matched) before problem 2 below was
   found.

2. **Theme hover-preview/snapback broke — far more serious, root cause NOT diagnosed:** after the
   DPI fix, live-testing showed the settings panel's theme hover preview no longer correctly
   reverted on unhover. The user's exact description: hovering a swatch changed the app's actual
   colors to the hovered theme while the settings panel's own selection state stayed on the
   *previously active* theme (not the hovered one); un-hovering did **not** revert the colors back;
   *reopening* the settings panel afterward is what finally snapped the colors back to the true
   active theme. Described by the user as "horrible regression." Neither change made in this attempt
   should, on its face, touch hover/snapback state: `theme_manager.get_current_theme()` is
   documented and confirmed (via `grep` across the whole `theme_manager.py`) to be read-only (calls
   `_resolve_theme(active)`, no mutation); removing `panel.hide()`/`panel.show()` calls should if
   anything reduce side effects, not introduce new ones. **The actual mechanism was never found** —
   this was surfaced live, immediately assessed as too severe and too poorly understood to keep
   iterating on, and the whole attempt was reverted back to the known-good `main_window`-grab +
   panel-hide/show version (flash present, but geometry and snapback both correct) rather than risk
   compounding an unverified fix on top of a confirmed-broken one. **Anyone re-attempting the
   `content_container`-direct-grab approach must diagnose this coupling first** — it is real,
   reproducible, and currently unexplained, not a cosmetic side issue.

**Current state, end of session:** reverted cleanly to the `main_window`-grab + panel-hide/show
version (the state documented in the entry below, plus the harmless, still-in-place
`_last_apply_stylesheets_at` entry+exit stamping and the `refresh_dirty()` cooldown gate — both
inert now that the gate's premise was found insufficient, but neither wrong nor actively harmful to
leave in place). The punch-through flash is **still present and unfixed**. `_REFRESH_INTERVAL_MS` is
at `1200` (empirically flash-free per the user's sweep, not a real fix). TEMP PERF instrumentation
(`[PERF]` `logger.warning` calls in `show_for_panel`/`_grab_and_blur`, plus the gate-check
diagnostic added and left in `refresh_dirty()`) is still in the file — not yet removed, since the
bug isn't resolved. See TODO.md for the deferred next steps.

**Separately, confirmed real and pre-existing, explicitly out of scope for this investigation per
the user's own instruction:** `ThemeItem.enterEvent` (`title_bar.py`) fires repeatedly (~1.4-1.6s
apart) for a **stationary** cursor resting on a theme swatch — confirmed via log evidence showing
`[hover debounce] firing preview...` lines recurring on that cadence with no mouse movement in
between. This has apparently always silently re-triggered real restyles on a timer-like cadence even
at rest; it only became visible/consequential tonight because `grab()`/`hide()` now has something
expensive to collide with on each of those spurious re-fires. The user was explicit: stay scoped to
the blur collision only, do not fix the spurious `enterEvent` itself in this pass — noted here and in
TODO.md as a separate, deferred, pre-existing finding.

---

## FIXED and live-verified: composited-overlay transport-bar blur grabbed the wrong background entirely — `content_container.grab()` returned Qt's default palette grey, not the theme's real color, because `content_container` has no styled background of its own (2026-07-19)

**Feature context:** `blur-composited-overlay` branch, `ui/transport_bar_blur.py`
(`TransportBarBlurOverlay`) — a single rasterized grab of the mini transport bar's union bounding
rect, blurred as one image and composited into an overlay under whichever panel (settings/speed/
sleep/stats/tags) is currently open, per the accepted plan
(`~/.claude/plans/good-catch-claude-twinkly-kay.md`).

**Symptom, as the user actually reported it, several times, in these words:** "the background
color is wrong" / "background in the grab is corrupted" / a directly-quoted theme hex value
(`"bg_main": "#1A002E"`) pasted from an IDE selection to make the claim unambiguous. Visually: the
blurred region's background read as a flat near-black/grey rather than the active theme's real
background color (a distinct purple for "Chatsubo," for example) — not merely "blurred," a
genuinely different color.

**Root cause:** `content_container` (the widget `_grab_and_blur` called `.grab()` on, aliased as
`_common_ancestor` throughout `transport_bar_blur.py`) has **no `background-color` rule of its
own**. The theme's `bg_main` color is painted by `get_base_stylesheet()` onto `QWidget#mainwindow`
(`themes.py`, `_get_gradient_style(t, "bg", t['bg_main'])` → `QWidget#mainwindow { background: ...
}`) — `main_window` itself, not `content_container`. In normal on-screen Qt compositing,
`content_container` is transparent-by-default and `main_window`'s background paints through
underneath it, so the app looks correct to the eye. But `QWidget.grab()` only rasterizes a widget's
**own** paint buffer plus its children's — it does not include whatever ancestor background is
merely showing through it in the final composited frame. So `content_container.grab(rect)` was
always returning Qt's plain default `QPalette` window color, confirmed by direct measurement to be
exactly `#202326` on the dev machine, completely independent of which theme was active — this is
why the corruption's exact shade appeared to shift when the user tested different themes (each
theme's real color differs, but the WRONG color returned by `grab()` never changed, since it was
never reading the theme at all).

**Fix (`b2e0eb0`):** `_grab_and_blur` now grabs from `main_window` instead of `content_container`.
Since `main_window` genuinely paints `bg_main` on itself, its `.grab()` correctly returns the real
themed background. The rect passed to `.grab()` is translated from `content_container`-local space
into `main_window`-local space via `main_window.mapFromGlobal(content_container.mapToGlobal(rect.topLeft()))`
(a `mapToGlobal`/`mapFromGlobal` round-trip, not `mapTo()` — see the mapTo-between-siblings note
below, which is a distinct but related finding from earlier in the same investigation). Because
`main_window`'s widget subtree also contains the currently-open panel (raised above
`content_container`), grabbing `main_window` while the panel is visible would additionally capture
the panel's own translucent `rgba(bg_main, panel_opacity_hover)` wash on top of the real content —
double-applying the panel's own tint before blur even ran. Fixed by hiding `self._active_panel`
(a new field, set in `show_for_panel`, cleared in `hide_for_panel`) for the duration of each grab,
mirroring the pre-existing overlay-hide pattern from an earlier fix in the same file (see below).

**Five other real bugs found and fixed in the same investigation, before this one, roughly in
discovery order** (all in `transport_bar_blur.py`, all confirmed live, not just reasoned about):

1. **Overlay positioned in the wrong region entirely ("pink wash").** The `QLabel` overlay was
   constructed as `QLabel(main_window)` but positioned using `content_container`-relative
   coordinates (`self._overlay.setGeometry(self._bounding_rect)`, where `_bounding_rect` is
   computed in `content_container` space). `content_container` sits below the title bar + progress
   bar in `main_window`'s `root_layout` (`app.py:596-604`) — it is NOT at `(0,0)` within
   `main_window`. Fixed by reparenting the overlay to `content_container` (`QLabel(self._common_ancestor)`)
   so its positioning coordinate space actually matches where it's being told to go.

2. **Self-referential grab ("burn effect," compounding black corruption).** Once fix #1 landed, the
   overlay became a sibling widget *inside* `content_container`'s own subtree — meaning
   `content_container.grab()` (as it was at the time) rasterized the overlay's own prior blurred
   output along with the real content. Every `refresh_dirty()` call (every ~50ms while a panel is
   open) would grab-and-reblur its own previous result, compounding progressively toward solid
   black over a handful of cycles. Fixed by hiding the overlay (`self._overlay.hide()`) for the
   duration of every grab call and restoring its prior visibility state afterward — this pattern is
   what the panel-hiding fix for the `content_container`→`main_window` change (above) directly
   mirrors.

3. **`QStackedWidget` inactive-page geometry is bogus.** `vol_stack` (`sleep_timer_label` /
   `vol_container`[`volume_slider`] / `muted_icon_label`) only ever shows one page at a time.
   Confirmed via direct test: a hidden `QStackedWidget` page's `.size()` returns Qt's
   uninitialized-widget default sentinel (`640×480`), not its real small size, because it's never
   actually been laid out while hidden. Including all three pages unconditionally in the
   bounding-rect union blew the rect out to cover unrelated areas of the window (this is what
   produced the "cover art peeking through, blurred" artifact the user flagged from an early raw
   grab). Fixed by resolving only `vol_stack.currentWidget()` — via a new
   `_vol_stack_active_widget()` helper, called fresh on every bounding-rect computation and every
   `show_for_panel()` call, never cached, since the active page can change while a panel stays open
   (mute toggled, sleep timer started/stopped mid-session).

4. **"No blur at all" — a live/mid-animation position read.** `show_for_panel(panel)` is called
   synchronously immediately after the panel's slide-in `QPropertyAnimation.start()` (every
   `_start_*_entry` in `panels.py`). At that exact moment the panel is typically still off-screen or
   barely moved — reading its position via `panel.mapToGlobal(QPoint(0,0))` at that instant produced
   a `panel_rect` that never overlapped the transport-bar union, so `raw_rect.intersected(panel_rect)`
   came back empty and `show_for_panel` silently no-op'd on every single call. Confirmed via the
   user's own debug-log request: `_panel_rect_in_common_space` logged the exact rects at the moment
   of the bug, immediately showing the intersection was empty. Fixed by computing the panel's
   **settled** (post-slide-in target) rect directly: `QRect(QPoint(0, panel.y()), panel.size())` in
   `main_window`-local space — every panel-open `QPropertyAnimation` in this codebase animates ONLY
   `x`, always ending at `x=0`, with `y`/width/height already final at call time (confirmed via
   `grep` across every `_*_animation.setEndValue(QPoint(0, ...))` call site in `panels.py`).

5. **`mapTo()` between sibling widgets silently returns the wrong point.** Computing a panel's rect
   in `content_container`'s coordinate space requires translating between two widgets that are
   BOTH children of `main_window` but neither is an ancestor of the other. `QWidget.mapTo(target,
   point)` is only valid when `target` is in `widget`'s parent hierarchy (an ancestor) — called on
   true siblings, Qt emits `QWidget::mapTo(): parent must be in parent hierarchy` and silently
   returns the point **untranslated** (confirmed via a direct isolated test: a widget at
   main-window-local `(20,100)` mapped via `mapTo()` into a sibling's space returned `(20,100)`
   unchanged, not the correct `(20,50)`). Fixed by using `mapToGlobal()`/`mapFromGlobal()` instead,
   which is valid for any two widgets regardless of hierarchy — confirmed correct via the same
   isolated-test methodology, and reused for the `content_container`→`main_window` grab-source fix
   at the top of this note.

**A padding/alpha fix that was real but insufficient, kept anyway:** `QGraphicsBlurEffect` treats
"outside the source pixmap" as transparent and blends that transparency into the blurred result
near every edge — confirmed via direct measurement that a fully opaque solid-color test pixmap came
back with corner alpha as low as 194/255 after blurring, converging to 255 only around 4x the blur
radius of padding. Since every dirty sub-rect (and the bounding rect itself) has edges, this hit on
every single grab. Fixed by grabbing with a padding margin (`4 * _BLUR_RADIUS`), blurring the
padded pixmap, then cropping the artifact-carrying margin away before compositing. This fix is
real, independently verified, and stayed in the shipped code — but it did **not** resolve the color
corruption the user was reporting, because the corruption's actual cause (the wrong grab source,
above) was upstream of anything the padding fix could touch. Recorded here specifically as a
caution against declaring a bug fixed because *a* real bug was found and fixed in the vicinity — the
user's reported symptom must stop reproducing, not merely improve or partially explain.

**The investigation failure that delayed finding the real root cause — recorded because the user
was explicit that this needs to be on the record, not softened:** every isolated test built to
reproduce the corruption (a raw grab saved to disk from a synthetic widget and inspected, that grab
run through the blur function standalone, the blurred/cropped result inspected) came back visually
clean — because every synthetic test widget was built with an explicit `background-color` style
rule on the exact widget being grabbed, which the *real* `content_container` never has. This
difference between the test setup and production reality was never checked; instead, each clean
isolated-test result was treated as evidence the grab/blur/crop pipeline was correct, and the
investigation moved on to test other hypotheses (a bounding-rect-too-small "coverage gap" theory,
tested by widening the rect to the panel's full size — ruled out live, the corrupted area got
*bigger*, not smaller or gone; a `refresh_dirty()`/repeated-compositing theory, tested by disabling
dirty-tracking entirely and leaving only the single mandatory first-pass grab — corruption was
still present identically). The user directly and repeatedly told the assistant the background
color itself was the wrong thing (not buttons, not coordinates, not layout), first in general terms
and then by pasting the theme's literal `bg_main` hex value from an IDE selection when the
assistant kept re-examining the wrong part of a screenshot. The assistant said "you're right"
multiple times across this exchange without the retraction actually taking hold — the "the grab is
clean" premise survived, unstated but unchanged, into three further rounds of diagnostic work. This
produced a new standing CLAUDE.md rule (added the same session, committed separately): when the
user says a specific claim is wrong, the required response is to restate the corrected belief,
name what it replaces, and check every downstream step that depended on it — not just say "you're
right" and continue reasoning from the same premise. Full rule text in CLAUDE.md, directly below
"The user sees the rendered pixels..." (the closest existing rule in spirit, now generalized beyond
visual/pixel claims specifically).

**Sibling comparison branch:** `blur-direct-widget` (applies `QGraphicsBlurEffect` per-widget
instead of compositing one grabbed region) was built in the same session as a cheap-fallback
comparison. Its own real bug (a `deleteLater()` double-delete crash on panel-close) and its known,
accepted limitation (icon buttons blur into jagged/washed edges under this approach, confirmed
worse — not better — at a higher blur radius) are recorded in SESSION.md, 2026-07-19 Session 1,
not repeated here since neither touches this branch's code.

**Verification:** fix confirmed correct live by the user immediately after the `main_window`-grab
fix landed, across the exact theme ("Chatsubo") that had been used to demonstrate the bug. Temporary
debug instrumentation (`_debug_log`/`_debug_save` in `transport_bar_blur.py`, writing per-grab PNGs
and exact rect/geometry data to `/tmp/tbb_debug` — added at the user's explicit request specifically
to inspect the real production call site rather than trust another synthetic test) was removed from
the file once the fix was confirmed; the debug output files were also deleted from `/tmp`.

---

## FIXED and live-verified: search-field match-state (red/no-match) styling went stale after any book-set mutation — tag add/remove, exclude/restore, missing-detection, scan-add, metadata edit — because only `filter_books()` (the `textChanged` path) ever resynced `filter_empty` or re-applied the stylesheet (2026-07-18)

**Bug (second, unrelated report the same session as the persistence fix below):** the search
field's red/no-match vs. normal styling didn't update when the set of visible books changed while
the search text stayed the same. Two directions reported: (1) a search matching one book, then
that book gets removed/excluded/marked-missing/un-tagged — zero matches now, field should turn
red but doesn't; (2) a no-match search, then a book is added/restored/re-tagged so it would now
match — field should clear but doesn't.

**Root cause, traced via a find-and-report-only investigation first:** `BookModel.filter_empty` —
the flag `LibraryPanel._on_search_changed` read to decide the field's stylesheet — was only ever
resynced from the internal `_filter_no_match` inside `filter_books()` (`library.py:1872`, at the
time of investigation). Every book-set-mutating path funnels through `LibraryPanel.refresh()`
(`library.py:1187-1232`) → `BookModel.set_books()` (`library.py:1807-1816`), which calls
`_apply_filter_and_sort()` **directly** — this recomputed `_filter_no_match` correctly but never
resynced `filter_empty`, and `search_field.setStyleSheet(...)` was applied **only** inline inside
`_on_search_changed` — no other code path in the entire codebase ever touched it. Same gap in
`update_book_metadata()` (`library.py:1821-1830`, called from a title/author/narrator/year edit
via `BookDetailPanel`), which also calls `_apply_filter_and_sort()` directly.

**A live-debug detour that produced a process-management lesson, not a code lesson:** the first
attempt to live-verify the reported tag-add/remove repro used temporary `print()` instrumentation
in `db.add_book_tag`/`db.remove_book_tag`/`app.py`'s `_on_book_tags_changed`/the tag branch of
`_apply_filter_and_sort`. The first live run showed **zero hits on any instrumented line** —
looking like the tag-mutation UI wasn't reaching the DB layer at all, a much more serious bug than
reported. Investigating that dead-end surfaced the real explanation: a stray
`entr -r python main.py` dev-loop process, left running from an earlier session
(`fabulorentr`'s pattern), was silently serving a separate, unpatched app instance — the user's
repro clicks were landing on that window, not the freshly-launched instrumented one. `ps aux`
confirmed two independent Fabulor processes running simultaneously. Killing the stray instance and
retesting against a single known instance immediately produced the expected, much narrower
result: both tag-add and tag-remove correctly reapply the filter (the visible book list is correct
in both directions — confirmed live), and only the styling is stale, exactly matching the original
diagnosis. **This produced a new standing process-management rule, added to CLAUDE.md's "Running
the app" section:** before trusting any live repro, run `ps aux | grep -E 'entr|main.py'` and kill
any stray instance first — a leftover dev-loop instance can silently serve stale code and produce
misleading "the fix didn't work"/"nothing happened" symptoms indistinguishable from a real code
defect.

**Verified consequence (traced directly, not assumed):** `_on_book_tags_changed`
(`app.py:1400-1405`) reads:
```python
def _on_book_tags_changed(self) -> None:
    self.stats_panel._on_tag_changed()
    search = self.library_panel.search_field.text().strip()
    if search.startswith("#"):
        self.library_panel.refresh()
    self.tags_panel.refresh_books()
```
`self.library_panel.refresh()` is the *only* call in this method touching `library_panel` at all.
This confirms that adding the restyle step to the tail of `refresh()` automatically fixes the tag
add/remove styling bug too (for the already-existing `search.startswith("#")` condition this
method already gates on), with zero additional wiring needed at the tag-mutation call sites
themselves.

**Fix (`ebf9e36`):**
1. `BookModel._apply_filter_and_sort()` (`library.py`, previously ending at line 1976) gained one
   new last line: `self.filter_empty = self._filter_no_match`. Every caller of this method —
   `set_books()`, `update_book_metadata()`, `sort_books()`, and `filter_books()` itself — now
   unconditionally keeps `filter_empty` in sync. `filter_books()`'s own pre-existing explicit
   resync became redundant but harmless; left in place rather than removed for no benefit.
2. Extracted the styling block previously inline in `_on_search_changed` (lines 1444-1455 at the
   time) into a new standalone `LibraryPanel._refresh_search_match_state()`, changed to read
   `self.search_field.text()` itself instead of taking `text` as a signal-argument parameter — so
   it's callable from non-signal contexts. Deliberately does not touch
   `_explicit_filter_text`/`_programmatic_search_update` (user-edit-only bookkeeping, stays in
   `_on_search_changed`), does not call `filter_books()` (callers are responsible for having
   already updated filter state via `_apply_filter_and_sort()`), and does not call
   `_load_visible_covers` (each existing call site already handles that independently — no new
   shared post-mutation hook was invented, matching the codebase's existing precedent for that
   concern).
3. Wired the new method into three places: `_on_search_changed` (replacing the inline block),
   the tail of `refresh()` (immediately after `set_books()`, before the deferred cover-loading
   block — this single call site is what fixes every `refresh()`-routed mutation type at once),
   and `_on_book_metadata_saved` (`app.py`, after `update_book_metadata(...)`, since that path
   doesn't go through `refresh()`).

**Deliberately excluded, with reasoning:**
- `_toggle_sort_direction` and the dead-code `_apply_current_sort_filter` (zero callers anywhere,
  confirmed via grep) — `_toggle_sort_direction` never assigns `self._sort_field` (only
  `self._sort_ascending`; the only two assignment sites are `refresh()`'s `_filter_text`-sync line
  and inside `sort_books()` itself), and `_apply_filter_and_sort`'s `source` narrowing
  (`library.py:1888-1893`) keys purely on `self._sort_field` — direction/reverse only affects final
  ordering *after* filtering (`library.py:1944-1946`). Reordering an unchanged field cannot change
  match count. This exclusion holds.
- **CORRECTION (2026-07-18, later the same session): `_on_sort_changed` was *incorrectly* included
  in this exclusion in the original version of this entry — it needed the call and was missing it.**
  The original reasoning ("sorting changes ordering only... match count cannot change from sorting
  alone") is true of reordering, but `_on_sort_changed` doesn't just reorder — it's the single
  handler for the sort-mode DROPDOWN (`sort_combo.currentTextChanged`, `library.py:823`), and
  selecting a new mode changes `self._sort_field` via `sort_books()` (`library.py:1369`), which DOES
  change the narrowed `source` subset before filtering ever runs (`library.py:1888-1893`: "Recent"
  narrows to progress-only books, "Finished" to finished-dates only, "Progress"/others use the full
  list). Found live via screenshots (both "stuck-green" and "stuck-red": switching modes left the
  search field's color frozen at whatever it was before the switch, even though the match state had
  genuinely changed). Fixed (`4af50ca`) by adding one `self._refresh_search_match_state()` call at
  the end of `_on_sort_changed`, after `self._last_filter_mode = sort_key`. Confirmed unnecessary to
  special-case "Progress" mode — it uses the `else` branch (full book list), so it structurally
  cannot cause a false color on its own, matching the design intent. Live-verified by the user
  against both stuck-green and stuck-red repros, plus a regression check that `_toggle_sort_direction`
  alone still causes no color change.
- `showEvent`'s existing separate stale-filter-on-reopen handling (clears the field entirely if
  `filter_empty` is stale-`True` at panel reopen) — a different scenario (stale filter surviving a
  hide/show cycle) from this fix (stale styling while the panel stays open across a mutation); not
  touched or duplicated.
- The Tag Manager (`⚙`, `TagManagerWidget`)'s own `tag_changed` signal — confirmed via
  `main_window_builders.py:606` to connect **only** to `stats_panel._on_tag_changed`, never
  reaching `library_panel` at all. Initially logged as a real gap and a TODO.md follow-up, larger
  in kind than the styling bug fixed here (the book list itself would never update, not just
  styling) — but **closed same-session as closed-not-open, not deferred, once its actual
  reachability was checked.** `_open_tags_flow` (`panels.py:620-628`) gates on
  `PanelManager.is_overlay_open_or_committed()` — the exact same one-overlay-at-a-time check that
  blocks the Tag Manager from opening while the library panel is already visible (confirmed by
  reading the gate's definition, `panels.py:890-904`: "the single gate for 'ignore a second
  overlay-open request'"). Since the Tag Manager and an open library panel can never be visible
  at the same time, and `showEvent`'s existing stale-filter-on-reopen handling (see the exclusion
  immediately above) already re-validates `filter_empty` on every library reopen — including a
  reopen right after a Tag Manager session — there is no code path where a user could ever
  actually observe the stale `#tag` search this gap would otherwise produce. Removed from
  TODO.md's "Pending" list (which is for work still needing to happen); logged here instead so a
  future investigation doesn't rediscover the same non-propagation wiring, treat it as live, and
  burn another cycle re-deriving this same reachability conclusion.

**Tests:** `tests/test_library_shortcuts.py` gained two model-layer cases constructing a bare
`BookModel` and calling `set_books()` alone (never `filter_books()`), asserting `filter_empty`
tracks the match state correctly — pinning the `_apply_filter_and_sort()` resync independent of
any UI/signal path. `pytest tests/ -q`: same 4 pre-existing `test_cover_theme_pending.py` failures
as the established baseline (unrelated); everything else, including both new tests, passes.

**Live-verified** by the user against all 7 scenarios in the approved plan: tag-remove reddens the
field, tag-re-add clears it; exclude/restore/missing-detection restyle correctly; an empty search
field stays neutral across a refresh; live-typing red/neutral toggling is unchanged; a metadata
edit while a related no-match search is active restyles correctly; sort-only actions leave styling
untouched.

---

## FIXED and live-verified: `save_search_filter()` persisted the live widget text instead of `_explicit_filter_text` — a clicked tag/author/narrator/year filter survived an app restart as if it were typed search text, but only when the library panel was left open across the restart (2026-07-18)

**Supersedes a stale claim in `SESSION.md`'s `d8f193d` entry** (2026-07-05, the toggle-off-reverts
commit): that entry states *"`save_search_filter()` ... reads `search_field.text()` directly and
never references `_explicit_filter_text`, so that setting's behavior is unaffected."* That was true
in the narrow sense that `d8f193d`'s own change didn't alter `save_search_filter`'s behavior — but
it was also the exact latent bug this entry fixes, just not recognized as one at the time. See this
entry instead of treating that line as still-accurate; SESSION.md itself has been annotated to point
here.

**The bug:** `LibraryPanel` correctly maintains two separate pieces of state — `search_field.text()`
(the live widget, which legitimately shows a clicked filter's string while it's active, by design,
so the filter actually applies) and `self._explicit_filter_text` (the user's last genuinely typed
value, insulated from click-originated writes via the `_programmatic_search_update` guard set in
`set_search()`). `save_search_filter()` (`library.py`, was line 1474) read `self.search_field.text()`
— the wrong one — when persisting to `QSettings["persisted_filter"]`.

This didn't surface on an ordinary close-library → reopen-library cycle within the same running
session: `_close_library_flow()` (`panels.py`) never calls `save_search_filter()` at all (no
persistence happens on a plain panel close), and reopening runs `clear_tag_filter_if_active()`
first, which reverts the widget's displayed text back to `_explicit_filter_text` before anything
could be saved. It surfaced specifically when the whole app was closed (`MainWindow.closeEvent`)
*while the library panel was still open* — `closeEvent` calls `save_search_filter()` directly,
bypassing `_close_library_flow`/`clear_tag_filter_if_active` entirely, so it read whatever a
clicked filter had left sitting in the widget and persisted that as if it were real typed text. On
the next launch, the restore path (`library.py:913-924`) has no separate marker to tell "this was
typed" from "this was clicked" apart — only the final string ever gets persisted — so the clicked
filter was promoted straight into the new session's `_explicit_filter_text` baseline,
indistinguishable from a genuine typed search from then on.

**Fix:** one line — `save_search_filter()` now reads `self._explicit_filter_text` instead of
`self.search_field.text()`. Everything else in the method (`_classify_filter`'s shape-based
tag/year/text classification, the per-kind `persist_filter_tag/year/text` gating, the final
`setValue`) is unchanged; it just now operates on the correct source string. Confirmed before
changing it that `text` had no other use in the 15-line function body (no logging, no UI feedback
side effect) that switching the source could break.

Both writers of `_explicit_filter_text` (`_on_search_changed`'s guarded branch, `set_search`'s
guard) are synchronous, same-thread, in-order attribute assignments with no deferral — confirmed
during investigation that there's no timing window where `_explicit_filter_text` could be stale
relative to arbitrary `closeEvent` timing.

**Tests:** four new cases added to `tests/test_library_shortcuts.py` (the existing home for
`LibraryPanel` logic tests), following that file's established pattern of binding the real unbound
method to a lightweight fake host rather than instantiating a full `LibraryPanel`/`QApplication` —
`save_search_filter` needs no widget, only `self.config` and `self._explicit_filter_text`. Covers:
clicked-filter-showing-with-typed-explicit-text persists the explicit text (the reported case),
empty explicit text persists empty, a disallowed kind persists empty, an allowed year-kind filter
persists correctly. `pytest tests/ -q`: same pre-existing 4 `test_cover_theme_pending.py` failures
as documented in the entry above this one (confirmed via `git stash` to fail identically on `main`
without this change); everything else, including all new tests, passes.

**Live-verified, update:** the app-restart repro (click a filter, exit with panel open, relaunch,
confirm the typed text — not the clicked filter — is restored) was confirmed working by the user
later the same session, alongside the live verification of the match-state styling fix above. Both
fixes from this 2026-07-18 session are now fully closed out.

---

## FIXED: cover-pool "remove from pool" click left `ThemeManager._cover_theme` stale instead of nulling it — latent, not currently reachable as a visible bug, fixed on contract grounds (2026-07-18)

Found while investigating an unrelated, already-resolved question (whether `clear_cover_theme()`'s
long-removed no-op guard was worth reinstating — conclusion: no, see NOTES.md history/commit log for
that; it was not itself a bug). Tracing `clear_cover_theme()`'s call sites surfaced a real defect in
a neighboring method.

**The bug:** `_on_cover_pool_btn_clicked`'s "remove from pool" branch manually inlined a subset of
`clear_cover_theme()`'s effects (`_cover_theme_active = False` + a direct `_on_theme_changed` call)
instead of calling `clear_cover_theme()` itself. `clear_cover_theme()`'s own docstring states its
whole contract: "`_cover_theme` stays None so `cover_pool_btn` greys out." The manual inline never
touched `self._cover_theme`, so it stayed non-`None` — stale but, at that instant, still matching the
current book's cover. The follow-on `set_cover_art_mode("off")` call couldn't fix this either: by the
time it ran, `_cover_theme_active` was already `False` (set two lines earlier), so its own
conditional `if self._cover_theme_active: self.clear_cover_theme()` took the `else` branch instead.

**Consequence, traced but confirmed NOT currently reachable:** `set_cover_art_mode`'s non-off branch
decides whether to rebuild the theme from the live cover pixmap or reuse the cached dict, keyed on
`self._cover_theme is None`. With the stale non-`None` dict, a later "add to pool" click always
reactivates the cached dict rather than rebuilding — which would show the wrong colors if the cached
dict no longer matched the current book/cover. Verified by tracing every write site of both
`current_cover_pixmap` and `_cover_theme`: every real invalidation path (`_apply_main_cover` on book
switch, `_show_no_cover_state` for a no-cover book, `_on_active_cover_changed` when the user picks a
different cover for the same book via the Cover Panel) independently routes through
`apply_cover_theme`/`clear_cover_theme` and correctly rebuilds or nulls `_cover_theme` before the
stale value could ever be read back mismatched. So there was no live, user-reproducible "wrong
colors" repro today — the bug was real but latent, relying entirely on every *other* code path
happening to clean up after it. Fixed anyway, on contract-violation grounds: the next new mutation
path, or any reordering of these checks, could reintroduce a real wrong-colors bug without touching
this method at all.

**Fix:** replaced the manual inline with a direct call to `clear_cover_theme()`, which is a strict
superset of what the inline did (also nulls `_cover_theme`, also calls `_update_cover_pool_btn()`).
The historical reason for the manual inline — avoiding a double-apply when `set_cover_art_mode("off")`
runs right after — no longer applies, since `_on_theme_changed`'s existing same-theme-name no-op
guard (added this session) already absorbs the redundant second call for free. Scope: one method,
`theme_manager.py`'s `_on_cover_pool_btn_clicked`, `else` branch. `pytest tests/ -q` unchanged (206
passed, the same pre-existing 4 `test_cover_theme_pending.py` failures as before this change, confirmed
via `git stash` earlier this session to fail identically on `main` too). Live-verified by the user.

---

## FIXED and live-verified: excluding a book while a panel was open snapped the theme instead of deferring it; exposed a second, more fundamental _on_theme_changed re-entrancy gap (2026-07-18)

Repro: open Book Detail for the currently-playing book (from Library or Stats), cover-art-based
theme mode ON, exclude it. The cover disappears, so the theme must revert to the pool theme — but
that revert fired immediately, unconditionally, while the panel was still visibly open (or, for the
library context, still mid-slide-closing — see below), producing a visible snap instead of the
normal fade. Commit `c281ee3`.

**Root cause:** `_on_book_detail_removed` → (currently-playing book) → `_on_book_removed` →
`_load_cover_art("")`. The empty-`file_path` teardown branch of `_load_cover_art` called
`self.theme_manager.clear_cover_theme()` directly and unconditionally — no panel-visibility check
at all. This is the same method whose book-SWITCH call site (`_show_no_cover_state`) already got a
stand-down in the previous fix (`1025b0a`) — but this teardown call site was deliberately left
untouched at the time, since it's not a book-switch (no flow animation to protect against). It
needed its own guard for a different reason entirely: a panel can still be open when a book is
excluded.

**Confirmed via direct code read, not assumed from the description:** `_close_book_detail_flow`
(`panels.py`) is NOT synchronous — it starts an animated slide-out and only calls
`book_detail_panel.hide()` later, inside the animation's `finished` callback. So even for the
library context, where `_on_book_detail_removed` calls `_close_book_detail_flow()` before
`_load_cover_art("")` runs, the panel was still `isVisible() == True` (still mid-slide) at the
moment `clear_cover_theme()` fired. Both the library-context and stats-context repros are real —
confirmed by reading the code, not by testing only one and assuming the other behaved the same.

**Fix, mirroring an existing pattern exactly (per direct instruction — do not invent new deferral
logic):** `_rotate_theme` already defers when a panel is open (`_pending_rotation = True`, resumed
by `PanelManager._notify_panel_closed()` → `_fire_pending_rotation()` → a 3s-after-close
`QTimer.singleShot`). Added `ThemeManager.request_clear_cover_theme()` with the identical
panel-visibility check and a parallel `_pending_clear_cover_theme` flag; extended
`_fire_pending_rotation` with a second, independent check (not `elif` — a rotation and a pending
clear can legitimately both be armed at once, e.g. a rotation was already queued when the book got
excluded too). `app.py`'s `_load_cover_art` empty-path branch now calls
`request_clear_cover_theme()` instead of `clear_cover_theme()` directly. The book-switch call site
(`_show_no_cover_state`) is untouched — different mechanism, already correct.

**Second, more fundamental gap, found by directly checking rather than assuming — asked explicitly:
"does `_do_rotate`/`_on_theme_changed` already respect `_fade_in_flight`?"** Checked: **no.**
`_on_theme_changed` only guards against panel SLIDE animations (`_any_panel_animating()`); it
unconditionally stops and restarts `_fade_anim` regardless of whether one is already running
(`if self._fade_anim.state() == QPropertyAnimation.Running: self._fade_anim.stop()`). This is a
real, pre-existing gap, not introduced by this fix — but this fix is the first thing to reliably
queue two independently-scheduled theme-apply actions (a pending rotation and a pending
cover-theme clear, both released from the same panel-close event) capable of landing within 750ms
of each other on purpose. Without addressing it, "fire the clear, then fire the rotation" would
produce exactly the visible interruption this whole fix exists to prevent — between two of the
app's own deferred actions this time, instead of between a theme call and a flow animation.

**Fix for the re-entrancy gap:** gave `_on_theme_changed` a second, independent guard branch for
`_fade_in_flight`, structured as `if _any_animating: ... elif _fade_in_flight: ...` — `elif`, not
two independent `if`s, so a single call is claimed by exactly one defer-and-resume mechanism, never
both (which could otherwise fire it twice). **Retry-cadence check, raised directly before
implementing:** `_PANEL_ANIM_GUARD_MS` (700ms, the existing flat retry interval) is SHORTER than
`_THEME_SWITCH_FADE_MS` (750ms) — reusing it verbatim for the fade case would almost always retry
~50ms too early, forcing a second full 700ms wait (up to ~1400ms total instead of landing right at
750ms). So the fade branch does NOT reuse `_panel_guard_timer` — it stashes the call
(`_pending_fade_call`) and resumes via `_fade_anim`'s own `finished` signal
(`_on_fade_finished`, already touched by the previous fix's `_run_deferred_restyle` re-trigger),
zero-delay and event-driven instead of polled.

**Race safety between the two mechanisms, designed for explicitly (raised directly: "make sure the
stash-and-resume logic and the flat-retry logic can't both claim ownership of the same pending
call, or fire it twice"):** both resume paths re-enter through a FULL re-call to
`_on_theme_changed` — never a direct apply. This is the load-bearing property: it already held for
the pre-existing panel-animation retry (`_panel_guard_timer.timeout.connect(lambda:
self._on_theme_changed(theme_name, save, fade_ms, hover, user_initiated))`), and the new fade-branch
resume follows the identical shape. Consequence: if a panel animation starts while a call is
stashed waiting on the fade, `_on_fade_finished`'s resume re-enters `_on_theme_changed`, which
re-checks `_any_animating` fresh and correctly falls into the panel-retry branch instead — neither
mechanism needs to know about the other, because the re-check at resume time determines ownership
fresh each time, not whichever branch originally deferred the call.

Live-verified: excluding the playing book from Book Detail (both library and stats contexts),
cover-theme ON, no longer snaps — theme now fades smoothly after the panel closes. `pytest tests/
-q` (excluding the already-known-stale `test_cover_theme_pending.py`): 208 pass.

---

## FIXED and live-verified: the no-cover book-switch path had no stand-down at all, and the theme fade it starts could race the next book's own flow animation (2026-07-18)

Found via a directional live repro during the rapid-switch verification pass: switching from a
covered book to a placeholder (no-cover) book, cover-art-based theme mode ON, made the theme fade
visibly "jump" partway through instead of completing smoothly — described by the user as feeling
like the earlier "Regime B" shape (a synchronous cost landing inside an in-flight animation).
Switching the other direction (placeholder → covered) never showed this. Two coupled bugs, both
fixed, commit `1025b0a`.

**First correction made mid-investigation, worth recording because it was a real dead end, not
just a footnote:** the first hypothesis was "the clear_cover_theme deferral waits for the sliders
before firing, and apply_cover_theme's path doesn't" — directly challenged by the user ("why does
placeholder→cover not wait, if both paths use the same `when_animations_done` chain?"), and that
challenge was correct. Checked via log timestamps: in every captured instance of BOTH directions,
`_apply_pending_cover_theme`'s `ENTRY` → `progress_slider settled` → `_apply() firing` all land at
the identical microsecond — the deferral resolves instantly every time because the sliders are
already idle by the time it runs. Neither path was ever actually waiting. That framing was wrong
and had to be abandoned before the real mechanism (below) was found.

**Bug A — `_show_no_cover_state` (app.py) had no stand-down at all.** `_apply_main_cover` (the
has-cover path, reached when switching TO a covered book) already had a real deferral: `if
self.panel_manager and self.panel_manager.is_any_panel_visible(): self._pending_cover_pixmap =
pixmap` — stash instead of applying immediately. `_show_no_cover_state` (reached when switching TO
a placeholder book) called `self.theme_manager.clear_cover_theme()` directly and unconditionally,
every time, with no equivalent check. Both paths reach the identical `_on_theme_changed` body and
defeat its same-theme-name no-op guard equally (a cover-derived `theme_dict` is jittered per call
so it's never `==` the previous one; a differently-named pool theme is trivially not equal either)
— so that guard was never the differentiator either. The gap was purely upstream: only the
has-cover path had ever been given a stand-down mechanism to enter in the first place. Fixed by
giving `_show_no_cover_state` the identical `is_any_panel_visible()` stand-down, via a new
`_PENDING_CLEAR_COVER_THEME` sentinel (a plain `object()`, distinct from `None`/a real `QPixmap`)
so `_apply_pending_cover_theme`'s existing `when_animations_done` drain can tell "revert to pool
theme is pending" apart from "apply this cover's theme is pending" and call the right one
(`clear_cover_theme()` vs `apply_cover_theme(pixmap)`).

**Bug B — exposed by Bug A's fix, not caused by it: `_run_deferred_restyle` only guarded against
the book-load flow animation, never against the theme FADE it itself starts.** Once Bug A gave the
no-cover path a real stand-down, `clear_cover_theme()` started running through the same
`_do_fade_with_slider_animation` fade path the has-cover case already used — a real 750ms fade.
Traced precisely via two live captures (one clean, one showing the jump), comparing exact
timestamps:
- **Placeholder→cover (clean):** `_flush_deferred_restyle_now: EXIT` completes at `t≈75034.253`;
  the newly-selected book's own flow animation doesn't start until `t≈75034.45` — ~200ms LATER, no
  overlap. A covered M4B's load involves more upstream work (playlist resolution, cover lookup)
  that pushes its flow animation's start out far enough to clear the flush entirely.
- **Cover→placeholder (jump):** the newly-selected book's flow animation starts almost immediately
  — `_on_file_ready` fires only ~26ms after `clear_cover_theme()` — because a plain MP3 with no
  cover reaches it far faster. Still running when `_run_deferred_restyle` checks, so it correctly
  defers (`DEFERRED (flow_anim still Running)`) — but once that ~300ms flow animation ends, the
  flush proceeds with **zero check for whether the fade (750ms, started well before the flow
  animation even began) is still running.** It usually still has hundreds of ms left. The flush's
  own ~150-220ms cost then lands inside it — the visible jump.
- This is the same book-load-speed-determines-collision-timing shape as the scan-on-launch bug
  fixed earlier the same night, recurring here with cover-extraction cost as the variable instead
  of scan duration — not a difference between the two theme-call code paths themselves.

Fixed by adding a second guard condition to `_run_deferred_restyle`: defer if EITHER the flow
animation OR `self._fade_in_flight` (the fade's own in-progress flag, set in
`_do_fade_with_slider_animation`) is true. Also wired `_on_fade_finished` to re-invoke
`_run_deferred_restyle` when the fade ends — mirroring the flow animation's existing
`finished`-signal wiring in `app.py` — required for correctness beyond just this repro: without it,
a restyle held back ONLY by the fade (no flow animation involved at all, e.g. a plain theme
rotation from an idle screen) would never get re-checked and could stay pending indefinitely.

Both changes are purely additive — no existing guard, scheduling, or coalescing logic was removed
or weakened; `flush_deferred_restyle`'s deliberate bypass-both-waits behavior for the panel-open
compensation case is untouched (that path's whole point is guaranteeing no panel ever opens onto
stale colors, correctness intentionally prioritized over the rare mid-animation freeze there).

Live-verified: cover→placeholder switch, cover-art-based theme ON, fade now completes smoothly, no
jump. `pytest tests/ -q`: 208 pass; `tests/test_cover_theme_pending.py`'s 4 failures are confirmed
pre-existing (identical failures with this fix reverted via `git stash`) — that file pins a
since-removed `_cover_theme_apply_pending`/`_resolve_cover_source`/`source_key` design that no
longer matches the real `_apply_pending_cover_theme` shape; not a regression from this change, and
not a green invariant to rely on until someone rewrites it against current code.

---

## FIXED and live-verified: unconditional scan-on-launch was the real root cause of the flow-animation stutter; fixing it naively caused a second real bug (empty library panel on first open); both fixed (2026-07-17/18)

**This entry supersedes the VT/cover-ON second-`apply_cover_theme`-call root-cause writeup further
below as the actual FIX for that mechanism — the mechanism trace further down (post-scan cover
refresh, `_apply_stylesheets`'s unguarded `mw.setStyleSheet(base)`) was correct and led directly
here; this entry is where it was closed.**

**Bug 1 — mechanism, precisely.** `handle_background_tasks` (`library_controller.py:240-263`, pre-fix)
called `self.scanner.start(...)` **unconditionally** whenever `state["mode"] != "scanning" and
state["has_locations"]` — the `if manual or force_refresh or not state["has_indexed_books"]:` check
right next to it only gated the status-banner message, never the scan itself. This has been the
code's actual behavior since at least 2026-04-16 (`9ce9ef7`, the commit that extracted
`handle_background_tasks` — confirmed via `git show`, the unconditional `scanner.start()` call
predates that refactor too, so it was never a regression introduced by any single commit, just a
long-standing bug against the code's own documented contract at CLAUDE.md:759 ("starts a scan when
manual, force, or no indexed books, and not already scanning")). So every app launch with any scan
location configured ran a full library scan, regardless of library state.

That launch scan finishing fires `_on_scan_finished` (`library_controller.py`), whose last act (for
a book that's still valid) is `self.app.load_cover_art(current)` — a SECOND cover-load for the book
already loaded at startup. This chains into `_apply_main_cover` → `theme_manager.apply_cover_theme`
→ `_on_theme_changed` → `_apply_stylesheets`, whose `mw.setStyleSheet(base)` costs ~200-300ms
synchronously on the main thread (measured, both cover-ON and cover-OFF conditions, this session).
When this second call's timing happened to land inside the ~450ms book-load flow animation window,
it froze the animation — `worst_gap` observed 400-570ms on both sliders in repeated live captures.

**Why this looked book/format/cover-mode dependent and wasn't, corrected from earlier in this same
investigation:** whether the stutter appeared was governed entirely by whether the (variable-
duration) scan finished before or during the (fixed ~450-500ms) flow animation — nothing about VT
vs M4B, or cover-theme mode, changes this mechanism. At small-to-medium library sizes a non-force
scan (mostly skipping already-known books, see the "what a non-force scan writes" note below) often
finishes in well under a second, landing inside the animation window unpredictably run to run — this
is why 30-sample A/B benchmarks earlier this session sometimes showed VT/cover-ON as severely
stuttering and other times as clean: pure scan-duration variance, confirmed live via direct log
correlation (`STARTING SCAN` → `_on_scan_finished` timestamps vs. `animate_to START`/`END`
timestamps), not a re-run artifact or a flaky benchmark.

**Fix:** moved `self.ui.set_scan_buttons_enabled(False)` and
`self.scanner.start(force_refresh=force_refresh, locations=locations)` INSIDE the
`manual or force_refresh or not state["has_indexed_books"]` predicate. A normal launch
(`manual=False, force_refresh=False`, the only affected caller — `app.py:481`) no longer scans at
all. Every manual/forced caller (`_on_removed`, `_on_scan_now_clicked`, `_on_rescan_clicked`) is
unaffected — live-verified via the Rescan button, which still starts a real scan and completes
normally (`STARTING SCAN manual=True force_refresh=True` → `_on_scan_finished total=379`, ~39s for
the full library at the time).

**Accepted trade, stated explicitly to the user before implementing:** a book folder added to an
existing scan location from OUTSIDE the app (between sessions) now surfaces only on the next manual
Rescan, not automatically on the following launch. This matches CLAUDE.md's documented contract and
was a deliberate choice, not an oversight.

**Un-exclude/restore confirmed independent of this change, live-traced not inferred:**
`_on_excluded_book_restored` (`app.py:805-829`) does the DB flip (`set_book_excluded(path, False)`)
then directly refreshes every view itself (library/detail/stats/tags) — its own docstring says it
refreshes "the same way a rescan completion would." `set_book_excluded` (`db.py:1596`) is a plain
`UPDATE` on an existing soft-deleted row. Neither depends on a scan running.

**What a non-force scan actually writes to the DB for already-known, unchanged books, traced in a
follow-up investigation before finalizing the "no automatic re-scan" trade above: NOTHING.**
`ScannerWorker.run_scan`'s Phase 1 (discovery) is pure filesystem reads, zero `db.*` calls. Phase 2's
`if not self.force_refresh and book_path in known_paths: continue` skips `_extract_metadata`
entirely for an already-known book — no `upsert_book_files`, no `upsert_cover`, no inclusion in the
batched `upsert_books_batch`. The force-only missing-book-detection write (`mark_books_missing`) is
gated behind `if self.force_refresh:` and does not run at all on a non-force scan. So a routine
background scan after the animation (a design not taken, but considered) would have bought nothing
beyond new-folder detection — confirming the accepted trade above didn't quietly give up any
DB-freshness behavior for already-known books; there was none to give up.

**On scan-on-launch's likely original intent, for anyone revisiting this later:** scan-on-launch's
likely original purpose was a cheap non-force "soft scan" to auto-discover new folders without a
full rescan cost — this worked at the scan level but never fully connected to auto-refreshing the
visible library, and was removed 2026-07-17/18 as part of the animation-stutter fix. If
auto-discovery of new folders is wanted later, revisit as a deliberate feature (cheap scan +
population trigger, both working), not by reverting today's fix.

**Bug 2 — the naive Bug-1 fix's own regression: library panel opened EMPTY on the very first open
after a fresh launch, filling in ~1-2s later. Live-observed by the user, not caught by any test or
narrow check this session ran.** Traced precisely: `LibraryPanel.refresh()` (the only method that
does `self.db.get_all_books()` → `self._book_model.set_books(...)`) had exactly TWO triggers in the
entire codebase — `panels.py:_on_library_shown` (fires only when the user opens the panel) and
`library_controller.py:_on_scan_finished` (fires only when a scan completes). Grep-confirmed: no
other call site exists, and nothing in `app.py`'s `__init__`/startup sequence ever populated the
model. With Bug 1's fix removing the scan trigger on a normal launch, trigger (b) vanished and
trigger (a) doesn't fire until the panel is actually opened — so the panel's own open/slide-in
animation had to do the first-ever population live, in front of the user. The scan was never
*supposed* to be what populates the library on screen; it had been doing that as an accidental,
undocumented side effect the whole time, and removing it correctly exposed a real, pre-existing gap
that had simply never been observable before (because the scan always ran first and masked it).

The user explicitly named the constraint set that shaped the fix, having already independently
tried and rejected the two obvious-looking alternatives: (1) refresh-on-panel-open synchronously —
tried, live-confirmed to stutter the panel's own slide-in animation, rejected; (2) revert Bug 1
(scan on every launch again) — rejected, since that's the exact regression Bug 1 fixed. The fix
had to populate from the DB, early, asynchronously, decoupled from both.

**Fix:** added `QTimer.singleShot(0, self.library_panel.refresh)` immediately after
`self.library_controller._check_library_status()` in `app.py`'s `__init__` (~line 481). This queues
the EXISTING `refresh()` method — no new query logic — to run on the next Qt event-loop turn after
startup, fully decoupled from the scan and from panel-open. Live-verified via trace: `LibraryPanel.
refresh: ENTRY` now fires ~1.3s after `Fabulor started`, populating in ~10ms; the flow animation's
`animate_to START` lands ~65ms after that populate call finishes, not overlapping — `worst_gap`
stayed in the healthy 35-120ms range on the same launch, confirming this fix doesn't reintroduce
Bug 1. `_load_visible_covers()` (called at the end of `refresh()`) no-ops while the panel is hidden
(its own `isVisible()` guard), so no cover I/O is wasted at startup — covers dispatch for real on
the panel's actual first open, same cost as before.

**Known, accepted limitation, user-confirmed live:** opening the library extremely early — before
the idle cover-cache warmup has had time to run — can still show a brief first-visit cover-load
hitch. This is a pre-existing, much smaller, separate cost (cover dispatch/paint jank, not
population/empty-panel) and was explicitly not treated as a new bug.

Both fixes: commit `cd5ec5b`.

---

## FIXED and live-verified: `_sized_cover_cache` was wiped on every theme apply — cover-theme-mode book switches stuttered the library panel's first open, even after a long wait (2026-07-18)

Found via a follow-up user report immediately after the two fixes above shipped: with cover-art-
based theme mode ON, the FIRST library-panel open after a book switch stuttered — reproducible even
after waiting 15+ seconds (ruling out a simple timing race), smooth on the second open in the same
session, and did NOT reproduce with fixed/pool themes unless the theme itself was actually changed.
User's own hypothesis, stated up front and confirmed exactly correct: theme apply was invalidating
or bypassing the cover-size cache for the switched book.

**Mechanism, traced precisely, live-confirmed:** `BookDelegate._apply_theme` (`library.py:2053`)
unconditionally reassigned `self._sized_cover_cache: dict = {}` on every call — not a `.clear()`,
a full reassignment, wiping every book's warmed sized-cover cache, not just the switched book's.
`_apply_theme` is called from `update_theme()`, whose only caller is
`LibraryPanel.update_progress_bar_theme()`, called from `theme_manager.py`'s
`_apply_stylesheets_deferred` alongside `library_panel.setStyleSheet(...)` — confirmed the
`setStyleSheet` call itself never touches either cover cache; `update_progress_bar_theme()` is what
does, via `_apply_theme`'s reassignment. This deferred batch flushes synchronously right before
every panel open (`flush_deferred_restyle()`, called from `complete_main_fade()` and
`PanelManager._flush_pending_restyle()`, both at the top of every panel-open flow before `show()`)
— so the wipe lands immediately before the exact paint that opens the library panel, forcing every
visible cell into `_get_sized_cover`'s cache-miss branch, which runs a synchronous main-thread
LANCZOS scale during that paint.

**Why cover-theme-specific, and why waiting didn't help — the piece that made this reproducible and
distinguishable from a timing race:** `_on_theme_changed` has a no-op guard that short-circuits when
the incoming `theme_name` already equals `_active_display_theme`. For fixed/pool themes, `theme_name`
is a stable string — switching to a book whose theme happens to already be active hits the guard,
`_apply_stylesheets_deferred` never runs, cache survives. For cover-derived themes,
`apply_cover_theme` builds a theme dict via `build_cover_theme`, which **deliberately jitters every
color by a small amount per call** ("Small per-call jitter ensures the same cover produces slightly
varied palettes" — `cover_theme.py`) — so the dict is essentially never `==` the previous one, the
no-op guard never fires for a cover-theme switch, and the wipe runs on EVERY such switch,
unconditionally. Waiting doesn't help because the wipe already happened at flush-time, well before
any subsequent wait — nothing re-warms the cache until a real repaint (the first open itself)
happens. Second open is smooth because no new cover-theme apply occurs (same book still loaded), so
the no-op guard fires and the wipe never re-runs; the cache — warmed by the first open's own
synchronous fills — survives.

**Why the wipe was unnecessary in the first place, per direct question before proposing the fix:**
`_apply_theme`'s `_sized_cover_cache` reset sat directly beneath `_placeholder_cache`'s reset, whose
comment correctly explains ITS OWN necessity ("stale-color pixmaps don't survive a theme switch") —
`_placeholder_cache` genuinely caches theme-COLORED renders keyed by `(color, w, h)`, so a real
theme color change needs fresh entries (or at minimum, a stale color simply isn't looked up again
under the new key — but the wholesale reset there is at minimum harmless and arguably intentional
given the small cache size). `_sized_cover_cache` caches real cover ART pre-scaled to a cell size —
nothing about a theme (colors, fonts, etc.) has any bearing on how a cover image should be scaled,
and the cache's own lookup key (`(book_id, dev_w, dev_h)`) already re-derives `dev_w`/`dev_h` from
the live device pixel ratio at lookup time, so even a screen/DPR change can't return a stale entry
through this key. The wipe was a defensive copy-paste from the adjacent, legitimate reset, never
actually checked against whether the same reasoning applied — it didn't.

**Fix:** removed the reassignment; `_sized_cover_cache` is now only initialized once (guarded by
`hasattr`, so `BookDelegate.__init__`'s first call still creates it before any lookup) and never
reset on subsequent theme applies. Live-verified: cover-theme ON, book switch, 15+ second wait,
first library-panel open now smooth.

Commit `0990e00`.

---

## CORRECTION (2026-07-17, later same night): the diagnosis below is WRONG about WHICH condition triggers the bug — kept for the record, do not act on the "book HAS a cover" framing

The entry immediately below diagnoses the bare-Qt-chrome bug as gated on "book HAS a cover, AND
cover-theme mode is Off." That framing is incorrect and was directly corrected live: **whether the
loaded book has cover art is irrelevant.** The real defect, found by adding a live trace directly on
`_on_theme_changed`'s same-theme-name no-op guard (not by further code reading), is that
`_setup_ui`'s startup call applied only the visible-surface pass and never the deferred
invisible-surface pass — so ANY later startup call into `_on_theme_changed` with the SAME theme
name (which `clear_cover_theme()` always uses, reached both by the no-cover case AND the
cover-mode-Off case) hits the no-op guard and never reaches the deferred pass. Cover presence
doesn't change this at all. Fixed via a shared `apply_full_pass()` helper called from `_setup_ui`.
Full corrected picture, live-verified: `NOTES_THEMING_CURRENT_STATE.md`. A second, unrelated
regression (hover preview no longer reaching settings/speed/sleep panels, introduced by the SAME
night's earlier deferred-restyle narrowing, not by this fix) was also found and fixed — also
documented there.

---

## REAL CORRECTNESS BUG, independent of Regime A/B: `apply_cover_theme()` silently skips ALL theming when cover-theme mode is "Off" and the book has a cover — app renders as unstyled bare Qt chrome, not the plain pool theme (2026-07-17)

**This is a standalone regression, not a benchmark artifact, not related to tonight's Regime A/B
investigation except that it silently invalidated a chunk of that investigation's data.** Found
live, by direct visual report (a screenshot of the Speed panel showing completely unstyled default
Qt widgets — no colors, no fonts, no theming of any kind), then confirmed by direct code reading
after the log trail turned out to be a dead end (the log had rotated past the process's own
startup, so log-only investigation could not settle this — this needed a live visual check, per
this project's standing "the user's eyes are ground truth" rule, and got one).

**Root cause, precisely:** `ThemeManager.apply_cover_theme()` (`theme_manager.py:991-1003`) is the
ONLY code path that applies any real theme (via `_on_theme_changed` → `_apply_stylesheets`) for a
book that has cover art. Neither `ThemeManager.__init__` nor anything in `app.py`'s startup
sequence calls `_on_theme_changed`/`_apply_stylesheets` directly — startup theming for a book with
a cover flows exclusively through this one function. Its early-return guard:
```python
mode = self.config.get_cover_art_theme_mode()
if mode == "off":
    return
```
exits immediately with NO fallback call to apply the plain pool theme. Compare against the
`_load_cover_art` (`app.py`) no-cover case, which handles this correctly: when a book has no cover
at all, `_show_no_cover_state`/`clear_cover_theme` runs, and `clear_cover_theme()`
(`theme_manager.py:1016-1021`) DOES call `_on_theme_changed(self._current_theme_name, save=False)`
— a real theme apply. **The gap is specifically: book HAS a cover, AND cover-theme mode is "Off."**
That combination is the one state with no path to ever calling `_on_theme_changed` at app startup.
The base chrome (`mw.setStyleSheet`, panel stylesheets, everything) simply never gets painted —
the app runs the entire session in bare, default Qt widget styling until something UNRELATED
happens to trigger a theme change for the first time (manually rotating the theme with `T`,
confirmed live to immediately "fix" the appearance — proving the theme pipeline itself works fine
once actually invoked; the bug is purely that nothing ever invokes it in this specific state).

**This does not match the design intent of the "Off" cover-theme mode.** The settings panel offers
Off/With-pool/Exclusive as cover-theme DISPLAY modes — the clear implication (and the correct
behavior for the no-cover case, which already works) is that "Off" means "use the plain
theme-pool colors, no cover-derived tinting," not "apply no theme at all, ever." The current
behavior for a book with a cover is the latter, silently, with no error, no log warning, nothing —
which is why it went unnoticed through this entire session's testing.

**Every "cover-theme OFF" trace and benchmark number gathered earlier tonight is VOID and must not
be cited as evidence of anything going forward** — the original 8-batch Regime A benchmark's OFF
conditions (M4B/OFF, VT/OFF, both the first pass and the corrected V2 re-run) were unknowingly run
against a completely unstyled, unthemed app for every book that had cover art, not against "a
themed app with cover-tinting turned off" as the test design intended. This is NOT a case of
"the numbers still mean something, just under different conditions than we thought" — an unstyled
app has different widget paint costs, different stylesheet-application costs (none, since none
ran), and does not represent any real user-facing configuration this bug fix should be validated
against. Do not attempt to salvage or reinterpret those OFF-condition numbers.

**What this does NOT invalidate:** the VT/cover-ON root-cause trace immediately above (the
post-scan cover-refresh race, `_apply_stylesheets`'s unguarded `mw.setStyleSheet(base)` call inside
`_on_theme_changed`'s `not hasattr(self, '_fade_anim')` branch) is unaffected — that investigation
was entirely on cover-theme-ON conditions, where `apply_cover_theme` does NOT hit this early
return and theme application proceeds normally (confirmed: those traces show real
`_apply_stylesheets`/`apply_cover_theme` activity throughout, this bug was never in play there).
That mechanism and its findings stand.

**Not yet fixed as of this write-up — fix is the very next step, then a live visual re-confirmation
(not just a log check that `_on_theme_changed` fired) before any benchmark re-run is planned.**

---

## FIXED (2026-07-17/18) — see the "unconditional scan-on-launch" entry near the top of this file for the actual fix

The mechanism traced below (post-scan cover-refresh racing the flow animation) was correct and is
exactly what got fixed — see the entry titled "FIXED and live-verified: unconditional
scan-on-launch was the real root cause..." near the top of this file for the fix itself
(`cd5ec5b`) and its live verification. The "post-scan cover-refresh" this entry describes IS
`_on_scan_finished`'s second `load_cover_art` call; "an unrelated post-scan cover-refresh" in this
entry's own title turned out to be the whole story, not just a contributing factor — the scan
itself was running on every launch unconditionally, which this entry did not yet know at the time
it was written. Kept below for the trace detail (still accurate), superseded only on "not fixed
yet" / "fix not proposed yet."

---

## Regime A fix — REAL, harmless, but small; the actual VT/cover-ON stutter is a DIFFERENT, pre-existing bug: an unrelated post-scan cover-refresh landing inside the flow animation (2026-07-17)

**Status: mechanism now FULLY understood via direct trace (caller identified, not guessed). This
is not "VT is fragile" — it's a specific, findable race between two unrelated subsystems. Not
fixed yet; fix not proposed yet (this entry is trace + root cause only, per standing discipline).**

**The `setCurrentRow` visibility gate (this session's actual Regime A fix) works exactly as
designed and is safe to keep, but it was never responsible for the severe VT/cover-ON stutter the
user kept correctly flagging as unresolved.** Full before/after data (8 conditions × both sliders,
n=30 matched pre/post): M4B is flat on both sliders/cover-states (no real effect, the fix's target
mechanism barely matters there). VT/cover-OFF improved modestly on both sliders (~90→76ms,
~84→75ms median) — a real, minor win, though never independently confirmed by a live perception
check the way VT/cover-ON was (do not over-claim this one either). None of this explains
VT/cover-ON's severe stutter, which the user described directly as "flow, pause, flow or flow,
pause, jump, pause, flow" and confirmed felt just as bad after the fix as before, DESPITE
`overall_progress`'s summary metric showing a shift (369→329ms) — a shift later correctly
identified by the user as still deep in dangerous territory, using a blood-pressure analogy (180/120
→ 175/118 is not a result, if the patient is still at serious risk of a heart attack). That
correction was right and is preserved as the standing benchmark for this whole investigation: a
shrinking number is not evidence of a resolved user-visible problem.

**Root cause of VT/cover-ON's stutter, confirmed via a direct per-frame trace with caller
identification (`traceback.extract_stack()` added temporarily to `apply_cover_theme`,
`theme_manager.py`) — NOT the mechanism previously guessed:**

Every book-load — VT or M4B, no exception — calls `theme_manager.apply_cover_theme()` from
`_apply_main_cover` (`app.py:2581`) **twice**, not once:
1. **First call**: from `_load_cover_art` (`app.py:475`), during app `__init__`, immediately on
   startup, BEFORE the flow animation starts.
2. **Second call**: from the SAME `_apply_main_cover` call site, triggered by
   `LibraryController`'s post-library-scan cover-refresh (`library_controller.py:161`) —
   `self.app.load_cover_art(current)`, whose own comment states its purpose plainly: "Refresh
   player cover after scan — ensures the active book_covers entry is used, not a stale cache entry
   from before the scan." This fires whenever the background library scan (started from
   `_check_library_status()` at app startup) finishes, which is a genuinely independent,
   variable-duration background-thread event — NOT gated on, or aware of, the flow animation's
   state at all.

**`_run_deferred_restyle` (`theme_manager.py`) already has a guard for exactly this shape of
collision** ("if flow_anim still Running, defer") — but it's a race, not a guarantee. In every M4B
capture, the scan finished and this second call completed BEFORE `animate_to START`, so the guard
never even needed to engage — clean by luck of timing, not by design correctness. In every VT
capture (3/3, tight clustering, not noise: worst_gap 350.3/350.2/328.9ms on `overall_progress`,
586.0/582.6/563.6ms on `chapter_progress`), the scan finished ~416ms into the animation — late
enough that the second `apply_cover_theme` call lands mid-flight and freezes both sliders, which
then snap to their end value in one frame the instant the block clears. This is the exact "flow,
pause, jump" shape the user described, confirmed frame-by-frame, not inferred.

**CORRECTION — the actual blocking call is `_apply_stylesheets`'s synchronous
`mw.setStyleSheet(base)`, NOT `_flush_deferred_restyle_now` as first attributed.** Precise
timing check: `_apply_stylesheets`'s own summary line (`[_apply_stylesheets hover=False]
total=209.8ms mw.setStyleSheet(base)=192.8ms ...`) lands at `14:25:15,076`, squarely inside the
second `apply_cover_theme`'s own ENTRY (`14:25:14,820`) → EXIT (`14:25:15,076`) window — meaning
this ~193ms cost happens INSIDE `apply_cover_theme` → `_on_theme_changed`, before
`_flush_deferred_restyle_now` is even scheduled. `_run_deferred_restyle`'s existing
flow-anim-Running guard is real and does correctly defer the LATER, separate
`_flush_deferred_restyle_now` call (confirmed: its own `[STUTTER-TRACE] proceeding via NATURAL
path` log line appears AFTER the freeze, once the animation has already snapped to its end value
— the guard is doing its job on the thing it guards, it just isn't the thing causing this freeze).
**The real gap is in `_on_theme_changed` itself (`theme_manager.py:339-392`): its `if not
hasattr(self, '_fade_anim')` branch — reached whenever this is the very first theme application
before the fade-overlay machinery exists — calls `self._apply_stylesheets(theme_name,
hover=hover)` synchronously and UNCONDITIONALLY, with NO flow-animation guard of any kind.** The
docstring comment justifying this ("Called before initialize_fade_overlay ... at startup nothing
is animating or interactive, so there is no stutter to avoid") is TRUE for the first
`apply_cover_theme` call (genuine app startup, correct) but FALSE for the second call (post-scan
refresh, which can fire well after the flow animation has already started) — the code has no way
to distinguish these two cases and applies the "nothing is animating" assumption to both.

**Why `chapter_progress` looks worse than `overall_progress` in this specific condition: a
duration-ratio artifact, not a second bug.** The same absolute ~586ms stall (from `overall_progress`'s
own last-frame timestamp to `chapter_progress`'s) eats a much larger fraction of `chapter_progress`'s
shorter nominal duration (374ms vs `overall_progress`'s 452ms), so its catch-up frame has to cover
more ground in the same blocked window. Both sliders are victims of the identical single stall;
there are not two separate mechanisms to explain.

**Why this reads as "VT is fragile" when it is not, mechanistically, about VT at all:** nothing
in VT's own seek/settle machinery (`seek_async`, cross-file branch, settle-eval — all confirmed
fast and clean in the same trace, ~10ms total, zero contribution to the stall) is implicated. The
correlation with VT specifically is very likely incidental — whatever makes the background scan
take longer in these captures (larger/slower-to-verify folder structure for a multi-file VT
audiobook, plausible but not directly measured) is a property of THIS PARTICULAR BOOK's scan cost,
not of VT-format playback. A different VT book with a fast-scanning folder might show the same
clean timing M4B showed here; a different M4B book in a slow-scanning location might show the same
freeze VT showed here. This needs to be kept in mind before generalizing "VT" as the causal
category in any future write-up of this bug.

**Confirmed via `caller=` trace line that the `setCurrentRow` gate is completely uninvolved in this
specific stutter:** zero `[_update_chapter_label_from_index]` log lines appear in any of the three
traced VT/cover-ON runs — the chapter list stays hidden throughout, so the gate this session shipped
correctly suppresses that call every time, and there was never anything for it to fix here. Do not
conflate "the Regime A fix didn't help VT/cover-ON" with "the Regime A fix is broken" — they're
unrelated facts about two different mechanisms sharing the same symptom surface (a stutter during
the same flow animation).

**NOT FIXED. Explicitly stopped at trace + root cause — do not move to implementation yet, per
direct instruction.** The precise gap is now identified: `_on_theme_changed`'s `not hasattr(self,
'_fade_anim')` branch (`theme_manager.py:377-392`) calls `self._apply_stylesheets(...)`
synchronously with NO flow-animation guard, on the documented assumption that this branch only
ever runs once, at genuine app startup, before anything can be animating. That assumption is false
for the SECOND `apply_cover_theme` call (post-scan refresh), which reaches this same branch
because `_active_display_theme`/`hasattr(self, '_fade_anim')` state doesn't change between the two
calls in a way that would route the second one differently — this needs independent confirmation
(has `_fade_anim` genuinely still not been set by the second call, or is something else routing it
into this branch a second time?) before any fix is designed, not assumed from this trace alone.
Two DISTINCT, unrelated stutter mechanisms are now understood to land in the same book-load
flow-animation window: (1) the previously-documented Regime B theme-apply hazard (already known,
out of scope for tonight's original Regime A work) and (2) THIS newly-found post-scan
cover-refresh race, which shares Regime B's general shape (a synchronous theme-restyle pass
landing mid-animation) but is a DIFFERENT code path (`_apply_stylesheets` inside the
no-`_fade_anim` branch, not `_flush_deferred_restyle_now`, which — confirmed — correctly deferred
in every captured run and is not at fault here). Do not conflate the two paths in any future fix;
they are protected by different guards (or, in path (2)'s case, no guard at all).

**Files touched (temporary tracing only, not a fix):** `theme_manager.py` —
`apply_cover_theme` gained a `traceback.extract_stack()`-based caller-identification log line
(`caller=file:line in function`), which is what actually found `library_controller.py:161` as the
second call's source — this should stay in place until the bug above is fixed and verified, per
standing instrumentation-retention policy for this investigation.

---



## Book progress silently resetting to ~0 on rapid book-switch (FIXED, live-verified — two bugs), plus a library-panel stutter (INCONCLUSIVE, not root-caused) — UMBRELLA ISSUE STAYS OPEN (2026-07-16/17)

**Status, stated plainly and not to be softened in a future pass: this is NOT closed.** Two
specific write-path bugs (below, "Bug 1" and "Bug 2") each have a live-verified fix — meaning a
fix was implemented, a live trace was pulled afterward, and the trace showed the fix's own
mechanism actually engaging correctly against the real trigger, repeatedly, not just "tests pass."
That is a real result and is recorded as such. But the standing bar for calling ANY of this
"fixed" — set explicitly, not a default — is:

1. App launch is smooth (flow animation, no stutter) with cover-based theme ON and OFF, for both
   VT and non-VT books.
2. Book-switch is smooth (flow animation, no stutter) with cover-based theme ON and OFF, for both
   VT and non-VT books.
3. No book loses saved progress, under rapid repeated switching, for either book type.
4. The library panel does not stutter on open.

**None of these four are true simultaneously right now.** A live-testing session the same night
Bug 1 and Bug 2 were fixed also surfaced (4): the library panel stutters on open. This was
investigated at length (see "Library-panel stutter" below) across three rounds — one theme-apply
hypothesis disproven by trace, one cache-miss hypothesis that looked confirmed on a single paired
comparison but failed a direct correlation test twice, including against a reconstructed
pre-narrowing baseline. **Net result: INCONCLUSIVE, not root-caused.** The user reproduced the
stutter directly twice, but a later identical repro produced none — it is real and intermittent,
not yet tied to any specific mechanism the investigation tested. Read the full entry below before
resuming this — it corrects an earlier over-confident claim within the same investigation, not
just a stale one.

**Why this matters beyond "there's one more thing to fix":** the whole reason this session's chain
started (drift/epsilon → decided to fix flow animation first → that surfaced the progress-reset
bugs → fixing the progress-reset bugs' investigation coincided with the library stutter
reappearing) is that touching the flow-animation/theme-apply timing has now TWICE produced a new,
previously-absent failure mode elsewhere (the progress-reset bugs' contention window widening, and
now this stutter). There is no standing reason yet to believe the NEXT fix in this area won't do
the same. Do not mark Bug 1/Bug 2/the stutter as independently "done" in a way that lets a future
session (or a future summary) treat the overall issue as closed — it closes only when all four
criteria above hold at once, verified live, in the same session that made the last change.

**Trigger:** repeatedly switching away from and back to a book in rapid succession (no playback,
no manual seeking required) can reset its saved `progress` to a near-zero value. First caught by
the user mid-session on `Infinite Jest` (M4B/CUE); the investigation initially treated this as a
narrow M4B correctness regression surfaced by the unrelated `_apply_stylesheets` narrowing work in
progress this session (see the RANK-1/RANK-2 entry above) — that framing was too narrow. Confirmed
live tonight to also strike VT (multi-file) books, via a different write path than initially
assumed, and confirmed to be pre-existing (a DB sweep found 20 books already sitting at
near-zero-progress fingerprint values, `0.05` or `~1e-8`, from before tonight's fix work began —
see below).

**Bug 1 (FIXED, live-verified): `_sync_persistence`'s 200ms-tick write had no seek-state guard at
all.** `_sync_persistence` (`app.py`) writes `self.config.set_last_position(current_file, pos)`
every 0.1% of duration change, gated only on `is_slider_dragging`/`_switch.in_deadzone` — nothing
about whether a restore-seek was still in flight. On a book-switch, `_restore_position` issues a
seek to the saved position, but mpv reports a transient near-zero `time_pos` for several 200ms
ticks before that seek settles (`0.0`, then a residual like `1.03e-08`). `_sync_persistence` was
writing that transient straight to config — and `_restore_position` (`app.py`) copies
`config.get_last_position` into the DB on every load (`if config_pos > 0: db.update_progress(...)`),
so a bad transient written once gets laundered into permanent DB state on the very next load. Fix:
a monotonic guard, `if self.player.is_seeking and pos < self._last_saved_pos: return`, mirroring
`SessionRecorder.update_furthest_position`'s existing "only advances" pattern. Deliberately NOT a
plain `is_seeking` guard (rejected up front, before any fix attempt) — if `is_seeking` ever strands
`True` (a documented failure mode elsewhere in this codebase), a plain guard would stop saving
entirely; the monotonic form only skips writes that would regress, so it can never fully strand.

**First implementation of the guard had a baseline bug, caught only by insisting on a live re-test
after the guard already "looked done."** `_last_saved_pos` was reset to `0.0` on every book-switch
(`_on_book_selected_from_library`), same as the pre-existing `_last_saved_pct = -1` reset it sits
next to. That seemed like the obvious mirror of the existing pattern — it was wrong. Since `0.0` is
never less than `0.0`, the guard's own precondition (`pos < _last_saved_pos`) could never be True
during the exact window right after a switch — the window the guard exists to protect. Confirmed
live: the guard fired zero times across an entire test session using this reset, and the very next
manual test reproduced the reset again, with trace logging showing `WRITE ... pos=1.03e-08
last_saved_pos(prev)=0.0`. Fix: seed `_last_saved_pos` from the INCOMING book's own DB-stored
progress at switch time (`db.get_book(path).progress`) instead of `0.0` — the real floor
`_restore_position` is about to seek to. Re-tested live afterward; trace showed the guard correctly
firing (`SKIP (monotonic guard) ... pos=0.0 last_saved_pos=92679.23`) on the next attempted
transient write for the same book. **This is the reason the fix was not reported as done after the
first implementation + passing unit tests** — the unit tests exercised the guard's logic in
isolation and could not have caught a wrong real-world seed value; only a live trace could, and did.

**A related, unguarded write path was found but is NOT (yet) implicated.**
`_save_current_progress` (`app.py`) does a synchronous, completely unguarded
`db.update_progress(current_file, player.time_pos)` at the top of every book-switch handler, before
`current_file` is reassigned to the new book. Every live trace across both test sessions showed
this path reading healthy, correct values on every call (it runs before the new book's `load_book`
touches any player state, so there's no transient window at this call site under the switch pattern
tested). Left as-is — no fix without evidence it's needed; flagging so a future investigator doesn't
assume this path is safe by design rather than "safe in every case observed so far."

**Bug 2 (root cause pinned via targeted live trace; fix implemented and LIVE-VERIFIED against its
specific trigger, repeatedly — but see the top-of-entry status note: this does not make the
umbrella issue "fixed").** VT cross-file restore hit `_sync_persistence` with `is_seeking=False`
and a near-zero transient `pos`, so Bug 1's guard never engaged. Confirmed via two independent live
reproductions, both VT (multi-file) books, both with the identical signature:
```
_sync_persistence: WRITE current_file='...Colorless Tsukuru...' pos=0.0102... is_seeking=False last_saved_pos(prev)=13830.898284
_sync_persistence: WRITE current_file='...Sometimes a Great Notion...' pos=7.28e-07 is_seeking=False last_saved_pos(prev)=42884.981352
```
**Root cause, pinned via targeted `[VT-SEEK-TRACE]` instrumentation (added specifically for this,
covering every write to `is_seeking`/`_seek_target`/`_vt_restore_pending` in the VT restore path,
with `time.perf_counter()` ordering):** `_on_file_loaded`'s VT branch (`player.py`) only issues the
restore-seek if `_vt_restore_pending` is already set at the moment it runs. Under main-thread
contention, `_on_file_loaded` (driven by mpv's own event) can fire BEFORE `_restore_position`
(queued off `book_ready`/`_on_file_ready`) has called `defer_vt_restore` — the branch found `None`,
logged "nothing to consume," and never issued the seek. Because no seek was issued, `is_seeking`
was never set `True`, so nothing downstream (including `_on_vt_file_switched`'s
`_seek_target is None` clear-gate) could tell a restore was still owed, and `_sync_persistence`
went on to persist the near-zero file-0-start position over the real saved one.

**A first fix attempt was rejected during design review, before implementation, for assuming an
ordering that wasn't structural** (see the design-review exchange for the full reasoning — kept
here only as the standing lesson): it made `_on_vt_file_switched` consume a late-arriving
`_vt_restore_pending` as a fallback, which only worked because in the one trace captured,
`_restore_position` happened to run before that handler's `QueuedConnection` slot fired. That's an
emergent timing fact, not a guarantee — the same shape of assumption (which of two things runs
first) that caused the bug in the first place, one level down. Traced further (per explicit demand
before accepting the design) and found the ordering claim WAS in fact false under a real,
independently-confirmed scenario (the library-still-animating deferred-restore path, which can
delay `_restore_position` by 50ms past that handler's queued delivery) — the design was corrected,
not silently patched over; see the corrected reasoning preserved in
`plans/b-and-it-s-not-glittery-mccarthy.md` if the mechanism ever needs re-deriving.

**Actual fix shipped: an order-independent rendezvous flag,
`Player._vt_file_loaded_awaiting_restore`**, symmetric between the two write sites so neither has
to assume which runs first:
- `_on_file_loaded`'s VT branch: if `_vt_restore_pending` is set, consume it (unchanged). If not,
  set `_vt_file_loaded_awaiting_restore = True` instead of concluding there's nothing to do.
- `defer_vt_restore`: if `_vt_file_loaded_awaiting_restore` is already `True`, issue the seek
  directly (the consumer already ran and won't run again this file-load). Otherwise, stash
  `_vt_restore_pending` as before.
`_on_vt_file_switched` was reverted to its original, pre-session form — it is now, and was always
meant to be, fully orthogonal to this rendezvous state (it only ever touches
`is_seeking`/`_seek_target`, which the two sites above set correctly regardless of firing order).

**Live-verified, not just unit-tested:** after implementation, a live rapid-switching session on
Colorless Tsukuru / Sometimes a Great Notion hit the exact "file-loaded-first" failure-mode
ordering **dozens of times**, naturally, via `[VT-SEEK-TRACE]`. Every single occurrence showed the
new mechanism engaging correctly — `_on_file_loaded_VT_MARKED_awaiting_restore` followed by
`defer_vt_restore_LATE_issuing_seek` with the correct target, the cross-file seek settling exactly
(`distance=0.0`), and the persisted value matching the restored position
(`_sync_persistence: WRITE ... pos=15294.485404 last_saved_pos(prev)=15294.485404` — no near-zero
transient). Zero resets across the whole session. The library-still-animating DEFERRED path also
fired 3 times during the same session and was clean in every case (though those specific instances
were M4B books protected by Bug 1's guard, not VT books hitting this specific rendezvous — the
rendezvous fix itself was exercised via the non-deferred file-loaded-first path extensively, which
is the same underlying race). Full trace-by-trace evidence is in the session transcript; not
reproduced here in full, but the mechanism and one complete verified cycle are recorded above.

**A pre-existing, separately-caused instance of the same symptom was found and cleaned up — not a
new bug, don't re-investigate it.** A DB sweep (read-only, before any fix landed) found 20 books
already sitting at near-zero-progress fingerprint values (`0.05`, the `seek_async` target floor, or
raw values like `1.9e-8`/`2.0e-8`) predating tonight's session — i.e. this exact class of bug had
already struck for an unknown period before tonight. These were reset to `0.0` (the schema's actual
default — an earlier attempt to reset them to `NULL` as an "unset" sentinel was wrong and caused two
live crashes, since several read sites assume `progress` is always a number; corrected immediately).
No recovery of the real prior positions is possible — the data is gone, not miscategorized.

**Reusable standing fact, worth its own note beyond this specific bug:** `_restore_position`'s
`if config_pos > 0: db.update_progress(...)` pattern — reading a QSettings-backed config value and
copying it into the DB on next load — means config here behaves as a write-once-per-load cache that
LAUNDERS whatever was last written into it, good or bad, into permanent state. Any future code
touching this pattern (or writing a similar "cache written by an unrelated tick, later trusted as
ground truth by a different subsystem" shape) should treat a transiently-wrong write as capable of
becoming permanent, not self-correcting. This is a general hazard class, not specific to this bug —
worth remembering if a similar shape bites something else later.

**Library-panel stutter — INCONCLUSIVE. NOT root-caused, despite an earlier pass in this same
session wrongly declaring it "ROOT CAUSE FOUND." That claim is retracted below — read this
correction, not the confident version, if this section is ever skimmed.**

The investigation went through three rounds, each disproving the previous one's confidence rather
than confirming it:

1. **Round 1 (theme-apply timing):** initial user isolation (cover-theme ON, first open after
   book-load) suggested `_flush_pending_restyle`/`_flush_deferred_restyle_now` forcing synchronous
   theme-restyle work during the library's open animation. Targeted `[STUTTER-TRACE]` logging
   disproved this directly — `_flush_pending_restyle` was ALWAYS a no-op (`was_pending=False`) and
   the animation window was a clean ~300ms in every captured case, no overlap with restyle work at
   all.
2. **Round 2 (cache-miss theory, WRONGLY treated as confirmed):** a live `cProfile` capture
   bracketing `_start_library_entry`→`_on_library_shown` (gated behind `FABULOR_STUTTER_PROFILE=1`,
   `panels.py`) caught one stutter instance dominated by cold `BookDelegate._get_sized_cover`
   (`library.py`) cache misses falling through to synchronous PIL LANCZOS resize/convert/
   unsharp-mask — 0.164s total window, 0.118s (72%) in that path across 13 misses, versus a clean
   0.057s/zero-LANCZOS capture moments earlier. This was written up as root cause. **That was
   premature** — it was one paired comparison, not a controlled repro, and calling it "found"
   before testing the actual correlation was the mistake.
3. **Round 3 (the actual correlation test, which falsified round 2 as stated):** re-ran the same
   profiler against a scripted repro (progress-bearing rows → no-progress rows → back to
   progress-bearing rows) **twice**, including once against a reconstructed pre-narrowing baseline
   (clean `HEAD`, commit `41da27a`, with only the profiler bracket added — no Bug 1/Bug 2, no
   RANK-1 narrowing at all, to rule out this being caused by any of tonight's work). **Neither run's
   raw numbers correlated with progress/no-progress rows the way the user's live perception did.**
   First run: pre-narrowing "progress" window ranged 0.090–0.154s, "no-progress" window ranged
   0.076–0.195s — no-progress was not cleaner, in fact its ceiling was higher. Second run: the
   "progress" window (0.094–0.144s) was actually the *tightest* range of the three windows tested,
   contradicting "top cleaner, bottom stuttery" outright. Call counts fluctuated 31k–85k with no
   clean pattern either.

**User's own final assessment, which stands as the honest summary:** the stutter is real —
observed directly, twice — but **not reliably reproducible**, and a later attempt at the identical
repro produced no stutter at all. This is NOT the same as "fixed" or "root-caused." It may be
intermittent for reasons the profiling approach used so far can't isolate (frame-delivery/
compositor-level jank rather than raw Python CPU time in the profiled bracket is one live
possibility, not yet investigated), or it may correlate with something neither round's hypothesis
tested. **Do not resume this investigation by re-asserting the LANCZOS cache-miss theory as
established** — it produced one suggestive data point, then failed a direct correlation test
twice. Treat it as one ruled-out-as-sufficient explanation, not a disproven-entirely one, and start
any future pass from the fact that the user's live perception and the profiler's raw wall-clock
numbers have not yet been shown to agree.

**Confirmed NOT caused by tonight's Bug 1/Bug 2 fixes**, independent of the above — neither fix
touches `library.py`, `_sized_cover_cache`, `_get_sized_cover`, or the idle preloader, and the
stutter (whatever its real cause) was reproduced against the pre-narrowing baseline too, before
either fix existed.

**Not fixed. No code changed for this issue beyond the temporary `FABULOR_STUTTER_PROFILE`-gated
profiler in `panels.py`** (`_start_library_entry`/`_on_library_shown`/`_stop_stutter_profile`) —
kept in place, disabled by default, for whenever this is picked up again. Do not propose a fix
direction until the actual correlate is found — profiling wall-clock CPU time in this bracket has
not, so far, been shown to track what the user is seeing.

**Reusable lesson, worth remembering independent of this specific stutter:** a `cProfile` bracket
measuring wall-clock Python time can come back completely clean while the compositor still visibly
drops frames — GC pauses, animation-driver/event-loop contention, or paint scheduling that happens
outside the profiled bracket (or outside Python entirely, e.g. inside Qt's own C++ paint/composite
path) are invisible to it. A clean `cProfile` capture is evidence the Python code in that bracket
wasn't the cost; it is NOT evidence nothing was slow. If a visual stutter/jank symptom doesn't
correlate with a `cProfile` capture's numbers (as happened here, twice), that is itself informative
— it points toward frame-timing/compositor-level causes, not "the profiler must be wrong" or "it
must be gone now." The next tool to reach for in that situation is Qt's own frame-timing or
paint-event instrumentation (e.g. hooking `paintEvent`/`QPropertyAnimation` frame delivery directly,
or an external compositor-level frame timer), not another `cProfile` pass with a different bracket —
that would just repeat the same blind spot. This is a general profiling-methodology fact, not
specific to the library panel; keep it in mind for any future UI-smoothness investigation in this
codebase.

**Files touched:** `app.py` — `_sync_persistence` (monotonic guard + trace logging),
`_on_book_selected_from_library` (`_last_saved_pos` seeding fix, incoming-book DB-progress seed),
`_save_current_progress` (trace logging only, no behavior change), `_on_vt_file_switched` (reverted
to original form after the rejected fallback design). `player.py` — `_on_file_loaded`'s VT branch,
`defer_vt_restore`, `load_book`'s reset block (all three: new `_vt_file_loaded_awaiting_restore`
rendezvous flag), plus `_seek_state_trace` and its call sites throughout the VT restore path.
Tests: `tests/test_vt_file_switched_guard.py` (reverted to its original 3-test form),
`tests/test_vt_restore_race.py` (new — both rendezvous arrival orders + the `load_book` reset).
Design record: `plans/b-and-it-s-not-glittery-mccarthy.md` (the rejected-then-corrected
`_on_vt_file_switched` design, kept for the reasoning trail).

**All `[VT-SEEK-TRACE]`/`[PERSIST-TRACE]` instrumentation deliberately left in place** — per this
investigation's standing instruction, do not strip it until ALL FOUR criteria in the top-of-entry
status note hold simultaneously, live-verified, not just Bug 1/Bug 2's own triggers.

---

## Making theme-apply safe to run without starving anything — feasibility findings, RANK-1/RANK-2 split into two separate fixes (2026-07-14)

**Status: INVESTIGATION + design-feasibility ONLY — no code changed, tree clean (`git diff` empty).
No fix plan yet (that's the next, separate step).** Follow-up to the two reports directly below
(the synchronous-main-thread timing map and the flow-animation-stutter split), answering: can the
~400ms synchronous `_apply_stylesheets`/theme-apply cost be made safe, and can the underlying
P1↔P2 race pattern be closed at the source? **Full report:
`review/Report_260714_theme_apply_safety_feasibility.md`.** Temporary DEBUG probes used
(`[APPLY-ORIGIN]` stack-origin logging on `apply_cover_theme`, plus the earlier reverted
`[STUTTER-PROBE]`) and fully removed.

**Phase 0 — `_any_panel_animating` is DELIBERATE and panel-scoped, NOT the thing protecting the
flow animation.** Origin commit `a5cf753` (2026-04-18, "guard against theme changes during panel
animation to prevent hitches") built it to protect a moving PANEL SLIDE from theme-apply. The
deeper history the user recalled is real: the theme transition is a heavyweight full-window overlay
fade, and a moving slider fill under that overlay *ghosts* (NOTES 2026-06-05) — a real visual
artifact, not just jank; the lightweight per-element `@Property` alternative was started and
abandoned as ~40–80h (NOTES 2026-06-19), and the "snap chrome instantly" middle path was explicitly
user-rejected as jarring. So the guard is deliberate-for-reason-X, panel-scoped; its Regime-B
protection on book-switch is a same-KIND effect reached incidentally, and cold-launch was never in
its scope.

**Correction to the parent report, with a more surgical root cause for cold-launch Regime B.**
Book-switch's Regime-B immunity is NOT primarily `_any_panel_animating` — it's a separate,
also-deliberate mechanism: `_apply_pending_cover_theme` waits for BOTH sliders'
`when_animations_done()` before applying. Cold launch takes a DIFFERENT branch of `_apply_main_cover`
(no panel visible → apply immediately, no slider wait), and the actual trigger is a redundant
post-scan cover reload (`_on_scan_finished` → `load_cover_art`, `library_controller.py:158-161`)
firing a full `_apply_stylesheets` during the flow animation (traced via `[APPLY-ORIGIN]`: two cover
applies per cold launch, the second ~2.4s in when the startup scan finishes). So cold-launch
Regime B is a *missing `when_animations_done()` chain + a redundant re-apply*, closeable narrowly
without touching the theme-apply cost or any race machinery.

**RANK-1 (the ~400ms cost) — key feasibility facts:** (1) Caller audit: almost every trigger
genuinely needs the full restyle (a theme/cover change re-colors the whole QSS-driven tree); only
hover-preview already runs reduced. This is NOT "narrow ops routed through an expensive path." (2)
Qt architecture: `setStyleSheet` is GUI-thread-only — **"async" cannot mean threaded**; the
achievable shapes are DEFERRAL (don't run it in the racing window — mirrors the existing
`when_animations_done()` pattern, lowest risk) or CHUNKING (split ~8 sub-applies across ticks —
partial, since the base `setStyleSheet` is one indivisible ~180ms call). (3) `theme_applied.emit`'s
DirectConnection fan-out is never awaited and only restyles hidden panels — separately deferrable.

**RANK-2 (the structural race) — feasibility is thread-dependent and asymmetric:** non-VT
`book_ready` is emitted from the mpv thread, so its QueuedConnection is MANDATORY and the
precondition cannot be removed at all. VT `book_ready` is emitted on the Qt thread, so a Direct
connection COULD run restore synchronously before the theme apply and remove the precondition — but
it's a single shared connection, the emit is deliberately before `instance.play()`, and it alters
the timing the shipped VT fixes were verified against (touches the VT-fragile blast radius even
without editing those functions). **Deferred, dated, and tracked in TODO.md** ("RANK-2, 2026-07-14")
so it doesn't become the exact undocumented structural risk this investigation exists to prevent.

**Recommendation: RANK-1 and RANK-2 are TWO separate fixes, not one** — different blast radius
(RANK-1 confined to `theme_manager.py` + two cover-apply call sites, mirroring a proven pattern;
RANK-2 re-architects a connection in the VT-fragile zone); RANK-1 alone closes all three
currently-observed victims (Race 3, Regime B, Themes-tab fade) while RANK-2 is insurance against a
hypothetical future sync op; RANK-1 has a cheap low-risk shape (the missing slider-wait) and RANK-2
doesn't. **Do NOT generalize `_any_panel_animating` to cold-launch** — Phase 0 showed that's the
wrong lever; the real cold-launch mechanism is the missing `when_animations_done()` on a different
code path. This is ready for the actual RANK-1 fix plan as its own next step.

---

## App-start flow-animation stutter is TWO mechanisms, not one — and it corrects the parent report's "isolated glitch" answer (2026-07-14)

**Status: INVESTIGATION ONLY — no code changed, working tree clean (`git diff` empty). No fixes.**
Live-verified follow-up to the parent report (`review/Report_260714_synchronous_main_thread_work.md`,
entry directly below), closing the gap it explicitly left open: it declined to treat the 2026-07-13
"first-app-launch-only VT flow-animation stutter" TODO item as settled, because that item's
"isolated, unrelated animation glitch" conclusion was trace-only against since-changed code, and
because new information from the user — the stutter occurs on **all book types**, not just VT (M4B
rarely/subtly, MP3 frequently/visibly) — structurally could not be P1/P2/P3 (all three are VT-only
by construction). This investigation reproduced it live and measured it. **Full raw numbers,
per-config tables, and the traced smoking-gun launches: `review/Data_260714_flow_animation_stutter.md`.**

**Method (measured, not traced):** temporary DEBUG-gated `[STUTTER-PROBE]` per-frame gap
instrumentation (since reverted, tree clean) on `ClickSlider.animate_to`/`_set_animated_value`
(the flow-anim glide) and on `library_panel_animation` (the slide). 60 cold launches (10 × 3 book
types × 2 cover modes) via a cold-relaunch harness, plus 12 deliberate live book-switches the user
drove manually — the user's visual observations were recorded alongside and **agreed with the
instrumentation at every point**. A smooth `QPropertyAnimation` ticks ~16ms; a large inter-frame
gap = the main thread was blocked between frames.

**The answer, corrected: the stutter is TWO distinct mechanisms wearing one name — confirmed by
magnitude, trigger, and visual character all differing, not assumed to be one bug.**

- **Regime A — baseline animation roughness (~70ms worst gap). Independent of P1/P2/P3 AND of theme
  apply.** Present on EVERY cold launch of EVERY book type, cover on or off, with zero
  `_apply_stylesheets` anywhere near the window (worst_gap median 70–76ms, never observed >108.7ms;
  0/10 apply-in-window on all OFF configs and both MP3 configs). Lands at animation start,
  coinciding with synchronous chapter-list `populate` + repeated
  `_update_chapter_label_from_index setCurrentRow` calls + the first mpv `time_pos` samples. This
  IS the "isolated glitch" the original trace found — real, book-type-agnostic, unrelated to any
  race pair. It's what the user sees on MP3 (10/10) and M4B-OFF (~half): a rough *start*, not a
  freeze. **This is a genuinely new, separate low-rank finding, not part of the theme hazard.**
- **Regime B — severe mid-animation freeze (~400–600ms). This IS the parent report's RANK-1
  theme-apply hazard, a THIRD victim of it.** Only on cover-theme-ON configs where a full
  `_apply_stylesheets` pass lands INSIDE the flow-animation window (M4B POOL 10/10, VT POOL 8/9;
  worst_gap median 566–595ms, max 791ms; overrun +287…+531ms). Traced smoking gun (M4B POOL): the
  ~400ms `_apply_stylesheets` begins ~200ms into the animation, blocks the main thread for its full
  duration, and the next flow-anim frame arrives 599.5ms later having snapped straight to the end —
  a freeze-then-snap, exactly the user's "mid pause, then flows." Same operation that starves the
  P1↔P2 restore consumer in the parent report; here it starves the `QPropertyAnimation` frame
  driver instead.

**"Why is MP3 different" — answered, and it's a timing offset, not a work difference.** The
cover-theme apply fires at different delays relative to the animation per book type: M4B-POOL median
188ms after animate-start (mid-anim → freeze), VT-POOL median 368ms (late but still catches it),
**MP3-POOL fires the apply entirely AFTER the animation ends** (0/10 in-window). So MP3 shows only
Regime A, which is why the user saw MP3 stutter identically cover-on and cover-off. The offset is set
by when the post-file-ready cover-theme re-apply fires; MP3's lands past the window. (Loose thread,
non-load-bearing: a POOL cold launch fires `_apply_stylesheets` three times and the exact trigger of
the third/post-file-ready one wasn't chased down — Regime B is proven regardless of which re-apply
fires it. Noted in the data file.)

**Book-switch is different from cold-launch, and it agrees with the user's eyes: all 12 deliberate
switches were CLEAN (Regime A only, worst_gap 18–64ms), both cover modes. Panel slides: 54 slides,
worst frame gap 17–19ms, ZERO freezes** — the user's "no panel slowness" confirmed exactly. Why
book-switch and slides mostly escape Regime B: the **`_any_panel_animating` guard in
`_on_theme_changed` defers the theme apply until the library slide finishes** (captured live:
`any_panel_animating=True -> queuing deferred retry`), which structurally prevents the ~400ms apply
from running *during* a slide and usually pushes it past the flow animation too. But it CAN still
rarely catch the flow anim: one incidental switch (not among the 12) hit a 356ms flow-anim freeze
when file-ready landed just after the panel guard cleared — same Regime B mechanism, far rarer on
book-switch because the guard deflects it. The cover-on VT progress resets the user saw on
book-switch are the separate, known Race 3, NOT an animation stutter.

**Corrected answer to the parent report's "is the flow-animation-stutter TODO independent of
P1/P2/P3":**
- **Independent of P1/P2/P3: YES, now confirmed by measurement** (not trace) — none of the three
  race pairs are involved in either regime on any book type; the cross-book-type occurrence alone
  rules them out (they're VT-only).
- **But "isolated, unrelated animation glitch" was INCOMPLETE** — that describes only Regime A. The
  parent report missed Regime B: the RANK-1 theme-apply hazard is ALSO a flow-animation stutter
  cause. The TODO item is really two bugs.

**RANK impact on the parent report:**
- **RANK-1 (theme apply) gains a third confirmed victim.** Parent report had it starving (a) the
  Themes-tab fade and (b) the P1↔P2 restore consumer. Now add (c) the flow-animation frame driver
  on cold launch (M4B-cover 10/10). Same ~400ms operation, same fix target (`setStyleSheet`/
  `_apply_stylesheets`) — this strengthens the case that the durable fix belongs at the
  theme-application layer.
- **The `_any_panel_animating` guard is a partial, accidental mitigation** — it's why book-switch
  and panel slides mostly escape Regime B, and why COLD LAUNCH (no panel animating to trigger the
  guard) is exactly the gap it doesn't cover. Any fix that makes theme-apply async should preserve
  or generalize that deflection.
- **New separate LOW-rank item: Regime A** — a ~70ms synchronous chapter-populate/label-update
  burst at animation start, book-type-agnostic, independent of everything else, never >108ms. Real
  but sub-perceptible-to-mild; should be its own rank, not folded into the theme hazard.

---

## Synchronous main-thread work during app start / book load / theme change / panel slide — full inventory + cross-thread pair map (2026-07-14)

**Status: INVESTIGATION ONLY — no code changed, working tree was clean throughout (`git diff` empty). No fixes proposed.** This exists because three separate races have now been found in this territory (the two 2026-07-13 VT fixes, and today's theme/VT-restore-starvation finding directly below this entry), each discovered by accident and root-caused only after the fact. This entry is the shared map every one of those fixes was designed *without*: what can compete for the Qt main thread during these four moments, so the next fix here (Rank 1/Rank 2 below will directly inform it) is designed against the full picture instead of discovering the next collision by surprise. **Full report with all measured distributions, the per-sub-step `_apply_stylesheets` breakdown, and the complete inventory tables: `review/Report_260714_synchronous_main_thread_work.md`.**

**Evidence basis — measured, not guessed:** all timings came from the pre-existing `[BOOKSWITCH-TRACE]`/`[_on_theme_changed]`/`[_apply_stylesheets]` DEBUG instrumentation already captured in today's `fabulor.log` (a large real sample: **70 `_apply_stylesheets` runs, 33 full-pipeline runs, 6 fully-traced book-switches**), plus one isolated read-only `build_cover_theme` measurement run in a throwaway subprocess. **Deliberately keeping the `[BOOKSWITCH-TRACE]` instrumentation in place** — it's what made this investigation possible from a log alone, and per the discipline the entry below already calls for, it should stay until Race 3 (the theme/VT-restore starvation) is actually fixed and the fix verified against it.

**The dominant cost, with a correction to the working model.** `_apply_stylesheets` (full, `hover=False`) runs **synchronously on the Qt main thread, median 318ms, p90 463ms, max 639ms** (n=70). Its single largest sub-step is `mw.setStyleSheet(base)` — the global base stylesheet that repolishes the entire widget tree — at **median ~180ms, max 355ms** on its own. The full `_on_theme_changed` pipeline (which wraps `_apply_stylesheets` + `grab()` + mask-build + the `theme_applied.emit` fan-out + `_refresh_panel_visuals`) runs **median 442ms, max 759ms** (n=33). **The correction: the "cover-art-based theme" cost is NOT the dominant-color pixel extraction — `build_cover_theme` measured ~4–5ms (it downsamples to 64×64 first, so source cover size is irrelevant). The cost is that a cover-art book-switch UNCONDITIONALLY forces a full `_apply_stylesheets` pass, whereas a plain non-cover book-switch fires none at all.** Any future "make cover-theme async" work must target `setStyleSheet`/`_apply_stylesheets`, NOT `cover_theme.py` — the color scan is a red herring its name invites.

**The one hazardous cross-thread pattern (call it P1↔P2).** Two threads matter: the **Qt main thread** (all UI, `_apply_stylesheets`, `_restore_position`, every queued/`singleShot` slot) and mpv's single **`MPVEventHandlerThread`** (all `event_callback` + `observe_property` handlers — confirmed by reading python-mpv's installed source, see the entry below). QThreadPool workers (`_resolve_playlist`, `CoverLoaderWorker`) always marshal back via queued signals and are not directly hazardous. The hazard: **a Qt-QUEUED writer racing an mpv-thread READER that is immune to Qt being blocked.**
- **P1:** `ungate_play` emits `book_ready` (main thread) → `_on_file_ready` → `_restore_position` → `defer_vt_restore` sets `_vt_restore_pending`. This consumer is on a **`Qt.QueuedConnection`** (`app.py:389`), so it runs only when the Qt loop is free — i.e. *behind* whatever runs synchronously next on the main thread.
- **P2:** mpv's `file-loaded` fires `_on_file_loaded` on the **mpv thread**, which READS `_vt_restore_pending` with no lock. The mpv thread runs immediately, unaffected by Qt being blocked — so if P1's writer hasn't run yet, P2 reads `None`.
- The injection point is `_on_library_hidden` (`panels.py`): it calls `ungate_play()` (queuing P1's consumer) and then, **in the same synchronous call stack**, `_apply_pending_cover_theme()` → the ~400ms theme apply. That ~400ms is exactly the window in which P2 reads `None`.

**The race read straight off captured timestamps — bimodal, no reconstruction needed.** Measured gap from `book_ready` emit → `_on_file_ready` entry, per switch: **420ms, 444ms, 419ms | 2ms, 0ms, 1ms.** When a theme apply lands in the window: ~420–444ms (restore starved, `_on_file_loaded` already read `None` and did nothing). When none competes: ~0–2ms (restore wins). Nothing in between — the signature of a single ~400ms synchronous blocker, exactly one starving operation.

**All three known races map onto this cleanly — two structural pairs, nothing forced:**
- **Race 1 (VT restore-on-load, fixed via `_vt_restore_pending`/`defer_vt_restore`)** IS pair P1↔P2. At cold start nothing competes for the Qt loop, so P1's writer always wins — which is precisely why 200 automated cold restarts passed. The deferred-restore mechanism is the fix for the *pair*; it just assumed P1 always wins.
- **Race 2 (general `_on_file_loaded` "seek then unconditionally emit `file_switched`", fixed via the gated `_on_vt_file_switched` clear + `_on_end_file` ERROR reset)** is a *third* pair, P3: the mpv-thread `file_switched.emit()` racing the queued main-thread `is_seeking` clear. Independent of theme timing.
- **Race 3 (theme apply starving `_restore_position` on book-switch — the entry directly below, NOT fixed)** is P1↔P2 AGAIN, reached via book-switch's own theme apply instead of cold-start timing. **It is not a fourth pattern** — same structural pair as Race 1, different trigger delaying the same queued consumer.

**Ranked risk (judgment, the input to a future fix cycle — not itself a plan):**
1. **CRITICAL — `_apply_stylesheets`/`_on_theme_changed` (median 442ms, max 759ms, sync).** The ONLY operation long enough to lose a queued consumer a race, and it already has — corrupting STATE (silent progress reset), not just visuals. Worst-possible position: injected synchronously into `_on_library_hidden` right after the `book_ready` emit whose consumer it then starves. This single operation's duration + position is what makes the whole territory fragile. Correct target for the eventual fix (NOTES.md's own "async/deferred theme application" direction points here — again, target `setStyleSheet`, not extraction).
2. **MODERATE — the P1↔P2 pattern itself, independent of theme.** Even with theme apply made async tomorrow, the structural hazard (Qt-queued writer vs. unsynchronized mpv-thread reader) remains: ANY future sync op ≥ ~100ms landing in that window reopens it. Deferred-restore papers over the common case; it does not remove the pattern. Ranked above the cosmetic items because it's the *reusable* failure shape.
3. **LOW — `_ensure_mpv` (cold-start MPV init, sync, one-time).** Heavy but runs once, before steady-state, guarded by `instance is None` (the instance persists across switches — NOT a per-switch cost), with no consumer racing it. Safe as-is.
4. **LOW — `build_streak_grid_cache` (startup, sync DB).** Bounded 364-row window, one-time, pre-UI, nothing races it. Recorded for completeness per "don't assume safe," not because it shows risk.
- **Negligible:** flow animation, panel slides, cover scaling, `_resolve_playlist`, idle preload (all async `QPropertyAnimation`/QThreadPool), and `build_cover_theme` (~4ms) — explicitly cleared of the suspicion its name invites.

**The two TODO.md flow-animation-stutter entries — one is this pattern, one isn't:**
- **"VT progress restore silently resets on book-switch" (2026-07-14)** is NOT independent — it IS Race 3 (P1↔P2 starved by the Rank-1 theme apply), already correctly self-identified in that entry as "the third instance of synchronous main-thread theme cost."
- **"First-app-launch-only VT flow-animation stutter" (2026-07-13)** appears INDEPENDENT of the starvation pattern — traced (code-trace only, per its own caveat) to the progress slider's own async `QPropertyAnimation` glide, which neither reads nor writes the deferred-restore seek or `_on_file_loaded` state. It sits in the negligible async-animation bucket. **Caveat preserved:** that separability was never live-forced against the actual stutter, and the VT chapter-walk now emits `chapter_changed` at a shifted time — re-verify live before treating it as closed. Not re-verified here (out of scope: investigation only).

**One related-in-kind item outside the four named moments:** `theme_applied.emit`'s fan-out is a **DirectConnection** (sync inline) — the stats/tags/book_detail `on_theme_changed` restyle runs inline on every theme apply, a meaningful slice of the ~124ms pipeline−`_apply_stylesheets` delta. Not a race, but the same shape (synchronous main-thread work chained onto a signal), and it means any "how expensive is a theme change" accounting that stops at `_apply_stylesheets` undercounts. For whoever sizes the Rank-1 fix: making `_apply_stylesheets` async does NOT automatically make this fan-out async — it's a separate synchronous chain off the same emit.

---

## VT progress restore silently resets on BOOK-SWITCH (not cold app-launch) — DIAGNOSED, root cause is theme application starving the Qt-side restore consumer, NOT the deferred-restore mechanism itself (2026-07-14)

**Status: root cause fully traced and confirmed via targeted live instrumentation
(`[BOOKSWITCH-TRACE]` debug logging, added this session and DELIBERATELY LEFT IN PLACE — not
reverted, since the mechanism below is still only understood, not yet fixed). NOT FIXED.** Found
live after the day's earlier VT restore-on-load fix (`faeaa83`/`685e433`, verified via 200
cold-app-launch cycles) — the user reported that restore worked in all 200 of those cold-launch
cycles but had never once been tested on a **book-switch** (selecting a different book from the
library panel while the app is already running), and that book-switch to a VT book reliably resets
progress to 0 instead of restoring it.

**This is category (c) from the three explanations considered up front (a genuinely separate
pre-existing bug / a real interaction with tonight's guard changes / something in between sharing
machinery but reached via a different trigger) — confirmed precisely, not just "closest fit."**
Tonight's `_vt_restore_pending`/`defer_vt_restore` mechanism is not wrong and is not the bug; it
correctly handles the case it was designed for. What's missing is a guarantee that mechanism relies
on implicitly: that `_restore_position` (which sets `_vt_restore_pending`) always runs, on the Qt
main thread, before `_on_file_loaded` (which consumes it, firing on mpv's own independent event
thread) checks it for the newly-loading file. That guarantee holds at cold app start, where nothing
else is competing for the Qt event loop. It does NOT hold on book-switch, where a slow synchronous
operation on the Qt thread can starve `_restore_position` long enough for `_on_file_loaded` to run
first, on mpv's separate thread, completely unaffected by whatever is blocking Qt.

**The exact mechanism, confirmed by live log trace, not inferred:**

Failing case (`_on_file_loaded` wins the race):
```
15:41:21,965  ungate_play: emitting book_ready (held-play branch)
15:41:21,984  _on_file_loaded: VT branch, _vt_restore_pending is None — NOTHING TO CONSUME
15:41:21,984  [_on_theme_changed GUARD] any_panel_animating=False        <- theme change starts HERE
  ... 325-400ms of synchronous _apply_stylesheets work on the Qt main thread ...
15:41:22,384  [_on_theme_changed hover=False] pipeline=399.3ms
15:41:22,385  _on_file_ready: entry                                       <- book_ready's QUEUED slot,
15:41:22,387  _restore_position: entry                                       stuck behind the theme work
15:41:22,388  defer_vt_restore: setting _vt_restore_pending=28109.6       <- set ~400ms too late; nothing
                                                                              will ever re-check it
```
Succeeding case (`_restore_position` wins the race, same code, no theme change in the window):
```
15:42:15,694  ungate_play: emitting book_ready (held-play branch)
15:42:15,696  _on_file_ready: entry                                      <- runs almost immediately
15:42:15,697  _restore_position: entry
15:42:15,700  defer_vt_restore: setting _vt_restore_pending=13538.18
15:42:15,706  [VT-RESTORE-CONSUME] consuming deferred restore target=13538.18   <- consumed within ~6ms
15:42:15,706  seek_async: CLOBBERING pending restore target=... (last-write-wins, expected/harmless)
15:42:15,741  _on_file_loaded (2nd time, for the cross-file seek's target file): nothing pending — correct, already consumed
```

The user's own live report named the trigger exactly: both failures coincided with **"Cover art
based theme"** switching a book whose new cover drives a fresh dominant-color extraction + theme
application; both successes were plain, non-cover-driven theme switches with no such synchronous
cost in the window. `book_ready` is a `Qt.ConnectionType.QueuedConnection` (`app.py:389`) — its
consumer (`_on_file_ready` → `_restore_position` → `defer_vt_restore`) cannot run until the Qt event
loop is free, and a ~325-400ms synchronous `_apply_stylesheets` pass (title bar, library panel,
settings/speed/sleep panels, stats/book-detail panels, sidebar, all regenerated and reapplied on the
same call) is easily enough to lose that race against `_on_file_loaded`, which runs on mpv's own
event thread and is not blocked by anything happening on Qt's.

**Why this is NOT the deferred-restore mechanism's bug to fix, and should very likely NOT be
"fixed" with another patch to `_vt_restore_pending`/`_on_file_loaded`:** the mechanism does exactly
what it was built to do — hold the restore target until the file is confirmed loaded — but it was
built assuming a single-producer-single-consumer ordering (`_restore_position` sets, `_on_file_loaded`
reads, in that order) that is only true when nothing else is competing for the Qt main thread at that
moment. **This is the third independent data point that synchronous, main-thread theme
application/extraction work in this codebase is expensive enough to cause real, user-visible
problems reaching well beyond the Themes tab it was written for:**
1. **2026-07-04** ("Theme-name hover preview," NOTES.md above) — a ~450-580ms synchronous
   `_apply_stylesheets` pass during Themes-tab hover preview caused fade-animation timing bugs
   (the animation's clock started before the restyle finished, degrading into a late snap).
2. **Tonight, independently, via this exact instrumentation** — a 325-400ms synchronous
   `_apply_stylesheets` pass measured directly (`[_on_theme_changed hover=False] pipeline=399.3ms`),
   this time triggered by cover-art-driven theme application on a plain book-switch, nowhere near
   the Themes tab.
3. **Tonight's actual bug** — the same class of synchronous cost, this time large enough and
   timed unluckily enough to make a Qt `QueuedConnection` consumer lose a race against an
   independent mpv-thread event, corrupting application STATE (a silent progress reset), not just a
   visual animation glitch. This is a step up in severity from the previous two instances, which
   were both purely cosmetic/timing bugs — this one loses the user's actual saved position.

**Suggested direction for whoever picks this up — not decided, not designed, explicitly deferred:**
given this is the third occurrence of the same underlying cost causing a real problem in a third
different subsystem, the more durable fix likely belongs at the **theme-application layer** — making
`_apply_stylesheets`/cover-art theme extraction asynchronous, or at minimum deferring it away from
moments where something else (like a book-switch's own event sequencing) is racing against the Qt
main thread — rather than adding a fourth patch on top of `_vt_restore_pending`/`_on_file_loaded` to
paper over one more way a slow main-thread operation can starve it. A patch narrowly targeting VT
restore (e.g., some kind of retry/re-check after the fact) would treat the symptom in one call site
while leaving the actual cost free to cause a similarly-shaped problem somewhere else next time
something else happens to race against a slow theme apply. That said, this needs its own
investigate-then-plan cycle (what would "async theme apply" actually require — thread-safety of
`_apply_stylesheets`'s Qt widget mutations is a real constraint, not a given) — not designed further
here.

**Live instrumentation added and deliberately left in place** (not reverted — this is diagnostic,
not a fix, and the mechanism is still only understood, not yet resolved): `[BOOKSWITCH-TRACE]` debug
logging across `Player.load_book`/`_on_playlist_resolved`/`ungate_play`/`defer_vt_restore`/
`_on_file_loaded`'s VT branch/`seek_async`'s `_vt_restore_pending` clobber (`player.py`), and
`MainWindow._on_book_selected_from_library`/`_on_file_ready`/`_restore_position`
(`app.py`), and `PanelManager._close_library_flow`/`_on_library_hidden` (`ui/panels.py`). All
`logger.debug`, silent below `FABULOR_LOG_LEVEL=DEBUG`, zero behavior change (195 tests unaffected).
Whoever picks this up next should use this instrumentation to confirm a fix actually closes the
race, not just that it happens to work on a few manual tries — the same discipline this whole
session has held to elsewhere.

---

## `_PAUSED_SEEK_UNDERSHOOT_COMP` boundary-crossing gate — IMPLEMENTED, TESTED, FOUND STRUCTURALLY WRONG, REVERTED (2026-07-14)

**Status: attempted and abandoned this session, on branch `fix/vt-restore-and-chapter-epsilons`
(never merged to `main` — the gate code, and the tests written for it, were reverted out of the
working tree before anything else on that branch was committed). Logged in full, not glossed over,
so a future session starts from the corrected understanding below rather than either re-deriving
tonight's dead end or finding an approved-looking plan sitting around and trusting it.** This is
the first of three drift-adjacent items deferred from the `_logical_pos` fix (TODO.md, 2026-07-12),
picked specifically to go first because it sits upstream of the other two (see that TODO.md entry).

**What was measured, and stands as real, correct findings independent of the failed fix:** live
instrumentation (`[UNDERSHOOT-MEASURE]` debug logging, temporary, since removed) plus a real user
test session against an embedded M4B with 4s/11s/17s chapters established, by direct trace, three
things that remain true and useful for whoever picks this up next:
1. A user-reported "smoking gun" — a paused chapter-slider click near a chapter end where the
   main-window chapter label showed the NEXT chapter's name while the chapter-list dropdown and
   the 200ms `_sync_chapter_ui` timer both kept showing the CURRENT chapter, for 20+ seconds, until
   real playback resumed and caught up — is real and reproducible, and its proximate mechanism is
   fully traced: the compensated mpv command can numerically fall on the far side of a chapter
   boundary in `_chapter_list`, and the raw sample mpv reports back immediately after the seek
   command (before settle) can therefore resolve to a different chapter than the LOGICAL
   (uncompensated) target does — `_update_chapter_label_from_index` reacts to that raw resolution
   within ~10ms, while `_sync_chapter_ui`/the chapter-list dropdown read the logical position and
   disagree with it for as long as the discrepancy persists.
2. Restore-on-load (`_restore_position`) never reaches this compensation at all, in any case,
   structurally — `book_ready` is connected to `_on_file_ready` (calls `_restore_position`) BEFORE
   `_on_file_loaded_populate_chapters` (the only place `_is_embedded_m4b` is ever set `True`), both
   `QueuedConnection`, so the gate's own flag is always still `False` when the restore seek runs.
   Confirmed empirically across 12+ captured restore-on-load seeks, zero exceptions. The user's
   separately-reported restore-on-load retrace is real but is a DIFFERENT bug — the already-tracked
   "Chapter-slider load-time retrace" TODO.md item — not this constant.
3. Very short chapters (~4s) show a distinct, separate "VU-meter" jitter on repeated paused slider
   clicks with ZERO chapter-boundary crossing involved — root cause confirmed as simply "0.37s is
   ~9% of a 4s chapter's total width," no residual-accumulation-across-clicks mechanism (that
   theory was checked and found wrong). Logged as its own TODO.md entry, explicitly out of scope
   for this constant's fix.

**What was designed, implemented, and then found to be built on a wrong premise — the actual
failure, stated plainly, not softened:** the fix attempt added a check to `seek_async`'s paused
embedded-M4B branch: walk `_chapter_list` (unpadded, deliberately not `_CHAPTER_WALK_TOLERANCE`) to
see whether `pos` and `pos + _PAUSED_SEEK_UNDERSHOOT_COMP` (the compensated mpv command) resolve to
different chapter indices; if so, suppress the compensation. This was implemented, unit-tested
against every real non-VT caller of `seek_async` that relies on the compensation while paused
(`activate_chapter_index`, `previous_chapter`, `next_chapter`, `apply_smart_rewind`, `undo_seek`,
`seek_within_chapter`), and one of those tests immediately failed in a way that exposed the real
problem: `activate_chapter_index`'s own paused target (`nominal + _EMBEDDED_CHAPTER_SEEK_OFFSET` =
`nominal - 0.09`) sits, by construction, on the near side of the very boundary it's trying to
reach — the `+0.37` compensation is not incidental to that seek, it is THE mechanism that is
supposed to carry the seek across the boundary it's deliberately targeting. The gate, applied
uniformly, would have suppressed compensation for ordinary chapter nav — breaking exactly the case
this constant exists to serve.

**The deeper error, once traced past that first failing test — not a tuning problem, a category
error:** the gate's premise was "does the compensated *command* numerically cross a `_chapter_list`
boundary." That's the wrong quantity. The compensation exists because mpv, while paused,
*undershoots* whatever position it's given by ~0.37s — the inflated command carries `pos + 0.37`
specifically so that mpv's own shortfall lands the REAL playback position back down near `pos`.
Checking whether the artificially-inflated command crosses a boundary says nothing reliable about
where mpv is actually going to land — the whole design of this constant is that the command and the
landing are different numbers by construction, and a walk against the command value was never
going to correctly predict real playback behavior. This explains both directions of the gate's
failure, not just the chapter-nav one: it also explains why the two 11s-chapter cases (a click the
user confirmed correctly crossed into the next chapter) and the one 17s-chapter case (a click the
user confirmed incorrectly crossed) could not be told apart by the gate's own arithmetic — both
"crossed" the inflated command's numeric boundary in the same mechanical sense, but whether real
playback should land before or after that boundary is a question of INTENT (what the caller was
trying to do), not of where a derived number happens to fall.

**Why intent can't be recovered from a bare position number after the fact, and what direction that
implies instead:** every seek method in this codebase falls into one of two categories, and the
category is knowable at the CALL SITE but not from `pos` alone once it reaches `seek_async`:
- **"Must land exactly"** — Next/Prev, chapter-list click, wheel-driven chapter-crossing,
  right-click-to-chapter-start, every labeled skip amount (5/10/15/30s, 1/2/5min). These callers
  know, unambiguously, that they are aiming at a specific boundary or a specific stated distance —
  the intent is explicit in the calling code, it is simply not passed down to `seek_async` today.
- **"Approximate is acceptable"** — freeform chapter-slider drag/click is the ONLY member of this
  category, because it is the only seek with no stated numeric contract; wherever it lands is
  "correct" by definition, so a compensation nudging it by 0.37s is never fixing an error, only
  potentially introducing a visible one.
  A downstream implication of this, not yet investigated: undo_seek reseeks to whatever position
  save_seek_position captured, which itself could have come from either category depending on what
  produced the original seek — undo's own category membership may need to be inherited from its
  source seek rather than treated as always-approximate or always-exact; NOT resolved here, flagged
  for whoever designs the next attempt.
  A gate that infers which category a seek belongs to from `pos` and `_chapter_list` alone is
  trying to reconstruct information that was thrown away before it ever reached `seek_async` — this
  is exactly why the 11s/17s cases were indistinguishable and why chapter nav produced a false
  positive. **The fix direction that follows: a destination-seek should carry an explicit signal
  from its caller stating which category it belongs to, not have its nature guessed downstream from
  arithmetic on a bare float.** This was not designed further tonight — it's the corrected premise
  for the next attempt, not a plan.

**What remains unsolved, explicitly, so it isn't conflated with what was attempted tonight:**
- The actual landing-precision problem `_PAUSED_SEEK_UNDERSHOOT_COMP` exists to solve is untouched
  — still applied unconditionally, exactly as before this session (the revert restored `player.py`
  to its pre-attempt state, byte for byte).
- **The visual drift on short chapters is a SEPARATE problem from landing precision, even in the
  best case.** Even a perfect fix to where mpv actually lands does not by itself address the
  "shows a sliver, retraces" ANIMATION/DISPLAY behavior on short chapters — that's a rendering/UI-
  timing question (how the slider animates and re-renders against a changing position), not a
  question of where the seek itself lands. The two are related (a landing-precision fix would
  likely reduce how OFTEN the display artifact is visible) but are not the same fix, and solving one
  does not by construction solve the other.
- The two originally-deferred display bugs — "Chapter-slider load-time retrace" (07-12) and
  "Chapter-elapsed ~1s boundary offset" (07-13) — are still sitting downstream of whatever this
  constant's eventual fix becomes, entirely unresolved, exactly as before tonight's attempt.

**Nothing from this attempt was merged.** `player.py` and `tests/test_seek_state.py` were reverted
to their pre-attempt committed state (`git checkout --`) before this branch's other work (the VT
missing-file fixes) was fast-forwarded to `main`. The investigation plan file used for this attempt
(`.claude/plans/come-to-think-of-silly-sun.md`) reflects the now-known-wrong gate design and should
NOT be treated as a starting point for the next attempt — it documents a dead end, not a blueprint.
This NOTES.md entry, not that plan file, is the correct starting point next time.

---

## VT cross-file missing-file jump corrupts `_current_vt_index`/`_file_offset` — DIAGNOSED, NOT FIXED (2026-07-14)

**Status: root cause traced and confirmed via live repro; fix deliberately deferred as part of the
consolidated design in TODO.md, "VT missing-file handling — consolidated design" (this bug is its
section 2, "Post-load discovery"). Not implemented tonight — logged here in full so the mechanism
doesn't need to be re-derived when picked up.** Found immediately after the same-file missing-file
fix (previous entry, above) shipped — the same-file fix (`seek_async`'s
`if target_idx == self._current_vt_index:` branch) does not cover the sibling `else` branch (the
cross-file jump, `self.instance.play(target_file['file_path'])`), which has no existence check at
all.

**Live repro (user-reported, reproduced exactly as described):** VT book, file 5 moved out from
under it. Click chapter 5 in the chapter list (a cross-file jump, since the book was on an earlier
file) → banner "Failed to load: loading failed." (mpv's own generic error string, not "File
missing." — confirms this hits `_on_end_file`'s ERROR path with mpv's own `file_error`, not the
same-file fix's `_abandon_seek_missing_file` path at all). Click Play → nothing happens. Click Next
→ plays file 2. Click Next from file 4 → doesn't play, banner again. Click Prev → goes to file 1,
plays. Click Next repeatedly → cycles 2, 3, 4, 2, 3, 4, 2, 3, 4... forever. No freeze, no crash, no
terminal error. The book is permanently stuck cycling a subset of its own chapters and can no
longer reach file 5 or anything past it — and, per the user, this state was reachable ("I was able
to get it unloaded before") under a similar-but-not-identical earlier sequence they couldn't fully
pin down: a *different* file moved, skipped over (banner shown as expected), then the first file
played successfully, then — at some later point the user couldn't precisely reconstruct — further
navigation triggered the unload. That ambiguity is very likely *this* bug, or a close sibling of
it, now that the mechanism below is understood — but it was never re-reproduced deliberately, so
treat it as likely-explained, not confirmed-explained, until someone deliberately re-runs that
exact sequence against this writeup's mechanism.

**Root cause, traced by reading the exact code path, not assumed:**

1. `seek_async`'s cross-file `else` branch (`player.py`, currently ~820-833) commits
   `_current_vt_index = target_idx` and `_file_offset = target_file['cumulative_start']`
   **optimistically — before `self.instance.play(target_file['file_path'])` is called, and with no
   existence check at all** (unlike the same-file branch, which now checks `os.path.exists` first).
   `is_seeking`/`_seek_target`/`_logical_pos` are set the same way, but those three are true "seek in
   flight" state; `_current_vt_index`/`_file_offset` are "which file are we logically on" state — a
   different kind of fact, committed at the same optimistic moment but not cleaned up by the same
   mechanism.
2. `instance.play()` fails silently (file doesn't exist) → mpv fires `end-file` with `reason=ERROR`.
3. `_on_end_file`'s ERROR path (Part 2, already shipped — see the entry below) resets
   `is_seeking`/`_seek_target`/`_logical_pos`/`_last_raw_global`/`_just_settled`. **It does NOT touch
   `_current_vt_index`, `_file_offset`, `_is_vt_file_switch`, or `_pending_local_pos`** — those were
   never in scope for Part 2, which was written for the seek-state strand, not the file-index
   commit. So after the reset, `_current_vt_index`/`_file_offset` are left pointing at file 5 (the
   file that never actually loaded), while `self.instance`'s real loaded file is whatever it fell
   back to (observed: still file 4, or possibly nothing meaningfully loaded — not independently
   confirmed which).
4. `_cached_time_pos` (mpv's raw, unconditional-every-sample property — see the `_logical_pos`
   entry below for why it's never touched by any reset) still holds file 4's last raw position,
   since mpv never produced a sample for file 5.
5. `time_pos`'s getter (`player.py:693-704`): with `_logical_pos` back to `None` (reset by step 3),
   it falls through to the raw path — for VT, `self._file_offset + self._cached_time_pos`. This is
   now `file 5's cumulative_start + file 4's raw local position` — a value that was never a real
   playback position, but happens to numerically resolve back into the middle of the timeline
   (explaining why it doesn't resolve to file 5 itself, or crash, or go out of bounds).
6. `next_chapter`/`previous_chapter` (`player.py:1114+`) resolve the current chapter by walking
   `_chapter_list` against `self.time_pos` — this corrupted value — every single time they're
   called. The walk deterministically lands in whatever range the corrupted arithmetic resolves to,
   which is why Next cycles a fixed subset of chapters (2, 3, 4, 2, 3, 4...) instead of either
   reaching file 5 or erroring: nothing ever re-derives `_current_vt_index`/`_file_offset` from
   where mpv is actually and genuinely positioned, so the corruption is permanent and self-
   reinforcing rather than self-correcting on the next `_on_time_pos_change` sample (contrast with
   the same-file fix and Parts 1+2, where a genuine mpv sample is always able to correct the state —
   here there's no genuine sample to correct it with, because mpv's real position was never file 5's
   in the first place).

**Why "Play does nothing" specifically:** `_current_vt_index`/`_file_offset` claim file 5, but
`self.instance` was never actually holding file 5 — whatever play/pause toggling does, it's acting
on a player whose real loaded-file state doesn't match what the app believes, so the visible
behavior is inert.

**This is structurally the same bug CLASS Parts 1+2 fixed (optimistic state committed before
confirmation, with nothing to correct it on failure) — applied to two different fields
(`_current_vt_index`/`_file_offset`) that were out of scope for that fix.** It is not covered by
tonight's same-file missing-file fix (previous entry) and is NOT the same code path.

**No rollback is actually needed for the missing-file case — checked, not assumed.** An earlier
draft of this writeup framed the fix as needing to decide what `_current_vt_index`/`_file_offset`
should roll back TO on failure, treating "the player should end up in some valid, resumable state"
as a requirement. It isn't: tonight's decided product behavior for the same-file missing-file case
is unconditional unload + exclude the whole book — there is no "resume playback from wherever it
was" requirement anywhere in that design. A rollback only makes sense if the goal is recovering to
a playable state; the actual goal is reaching the same unload-and-exclude outcome without
corrupting state on the way there. If the cross-file branch pre-checks `os.path.exists` BEFORE
committing `_current_vt_index`/`_file_offset`/`is_seeking`/`_seek_target`/`_logical_pos`/
`_is_vt_file_switch`/`_pending_local_pos` (same shape as the same-file fix) and routes straight to
the same `_abandon_seek_missing_file`-style handling on failure, none of those fields are ever
written to the bad target in the first place — there is nothing to roll back, because nothing was
ever committed. This fully resolves the "file doesn't exist" case with the same simple pre-check
shape the same-file fix already uses; no snapshot/rollback mechanism needs to be built for it.

**Where a rollback-shaped concern DOES remain — a separate, narrower case:** a file that *exists*
on disk but is corrupt or otherwise unreadable would pass `os.path.exists` and still fail at
`instance.play()`, hitting this same corruption via a different trigger (mpv's ERROR event instead
of a pre-check). That case still needs to reach the same unload-and-exclude outcome — via
`_on_end_file`'s ERROR path recognizing a VT cross-file jump was in flight and routing it to
`_mark_book_missing` (mirroring how the same-file fix routes through `load_failed`), not by trying
to recover playback or by rolling `_current_vt_index`/`_file_offset` back to "the file we were
already on." Whether this narrower case is worth handling in the same pass, or is rare enough to
defer further, is part of what the TODO.md entry's "needs a proper design" is pointing at — but the
design question is now just "how does the corrupt-but-present case reach unload-and-exclude,"
not "what do we roll back to."

**Explicitly not done tonight:** no code changed for this.

---

## VT missing-file exception strands seek state — FIXED and live-verified (2026-07-14)

**Status: FIXED.** Found live immediately after the general `file_switched` race fix (Parts 1+2,
below) landed — a pre-existing bug whose consequences the guard fix changed (see "Why this wasn't
caught before," below). Fixed via a pre-check, unit-tested against the real, actually-missing file
on disk, and live-confirmed by the user against the exact reported repro (deleted VT file,
Doctor Zhivago).

**The bug:** `seek_async`'s VT same-file branch (`player.py`, `os.path.getsize` call, formerly
line 788) calls `os.path.getsize(target_file['file_path'])` unconditionally as part of the
MP3-stop-and-load size-threshold test — with no existence check. If that VT file is missing from
disk (deleted/moved/renamed), this raises `FileNotFoundError` — **after** `is_seeking`/
`_seek_target`/`_logical_pos` are already set (a few lines earlier in the same branch) but
**before** any seek command is ever issued. Reported live: user deleted `002 - Doctor Zhivago
(Unabridged).mp3` from a VT book folder already playing chapter 002, then pressed Next
(`handle_next` → `Player.next_chapter` → `seek_async`), producing the traceback via a real
screenshot. Observed symptom, exactly as reported and exactly consistent with stranded seek
state: app doesn't crash; a banner briefly shows prior UI text; skipping to a different, existing
file plays fine; but progress/chapter display becomes erratic afterward (stale chapter label vs.
actual playback); switching to a different book and back restores correctly to the last-played
file (the book-switch path re-derives state fresh, masking the strand rather than fixing it).

**Why this wasn't caught before, and why the general-race fix (Parts 1+2, below) changed its
consequences without causing it:** before Part 1's guard, the next VT `file_switched` event would
unconditionally clear `is_seeking` — accidentally self-healing this exact stranded state, for the
wrong reason (an accident of the very bug Part 1 fixed). After the guard (clears only when
`_seek_target is None`), that accidental recovery path is gone, and nothing else clears it. The
missing existence check itself predates all of this session's other work — confirmed via git
blame-equivalent reasoning (the `os.path.getsize` call and its surrounding MP3-threshold logic
were untouched by either the VT-restore-on-load fix or Parts 1+2).

**Where the exception was actually being caught:** confirmed via investigation, not assumed — no
try/except exists anywhere in the call chain (`handle_next` → `Player.next_chapter` →
`seek_async`, or the equivalent chapter-list/other-seek entry points) in Fabulor's own source.
`main.py` installs no `sys.excepthook`, no `qInstallMessageHandler`. Since `handle_next` is
invoked via a Qt signal-slot connection, the exception was being caught by PySide6/Qt's own
default behavior for uncaught exceptions raised inside a Python slot (log/print the traceback,
keep running) — a Qt runtime characteristic, not application-level error handling. The "Failed to
load: loading failed." banner text visible in the user's screenshot was unrelated leftover UI
state, not this bug's actual error surface (confirmed: `_on_load_failed` fires from a different
signal entirely, mpv's own `end-file` ERROR event or the "no audio files in folder" case).

**Correction made during planning, before implementation:** the original instruction said "matching
M4B behavior... `is_excluded=1`." This is not what the actual runtime M4B missing-file path does —
confirmed via direct investigation. The real runtime handler, `_mark_book_missing` (`app.py`),
uses `db.set_book_missing(path, True)` — the **`is_missing`** flag, not `is_excluded`. Using
`is_excluded` here would have reintroduced the exact "ping-pong bug" documented in CLAUDE.md's
soft-delete-flags section (2026-06-27): `is_excluded` is sticky and reserved for user-trash
actions; a book auto-flagged via `is_excluded` shows up in the Excluded Books popup's restore
list, gets "restored" with no file behind it, and gets re-flagged on the next load attempt,
forever. `is_missing` is the dedicated, self-healing flag built specifically to prevent this. The
fix reuses the existing `_mark_book_missing` helper as-is — "matching M4B behavior" is satisfied
more precisely by reusing the exact mechanism than by the letter of the original instruction.

**The fix, decided as a pre-check (not a try/except) — the two are not equivalent:** a try/except
around `os.path.getsize` would still let `FileNotFoundError` actually get raised and unwind (just
caught one frame closer, instead of relying on Qt to catch it further up) — strictly weaker than
preventing the exception from ever occurring. `seek_async`'s VT same-file branch now checks
`os.path.exists(target_file['file_path'])` immediately after `is_seeking`/`_seek_target`/
`_logical_pos` are set, before `os.path.getsize` is ever reached. On a missing file:
`Player._abandon_seek_missing_file()` resets `_is_seeking`/`_seek_target`/`_logical_pos`/
`_last_raw_global`/`_just_settled` — the exact same field set `_on_end_file`'s ERROR-path reset
uses (Part 2, below), mirrored rather than reinvented, since this is the third place in as many
days resetting this exact shape for the same underlying reason (a seek that will never settle) —
then emits `self.load_failed.emit("File missing.")` and `seek_async` returns early (no seek
command issued). `_on_load_failed` (`app.py`) already shows its own unconditional banner
(`f"Failed to load: {reason}."`) before branching on `reason`; its branch now also matches
`"File missing."` (alongside the existing `"no audio files in folder"`) and calls
`self._mark_book_missing(self.current_file)` — the book's folder path, not the individual missing
VT file's path, since `set_book_missing` matches against `books.path` (the folder-level row) and
the product decision is to mark/unload the whole book. `_mark_book_missing` → `_on_book_removed`
was reused entirely as-is (both are CLAUDE.md-protected / already correct); nothing in that chain
was touched.

**`_vt_restore_pending` needed no attention — confirmed, not assumed.** `seek_async`'s very first
statement (after the `if not self.instance: return` guard) is the unconditional
`self._vt_restore_pending = None` clear. `os.path.exists`/`os.path.getsize` are reached well after
that clear, inside the VT branch — execution always passes through the clear first regardless of
what happens afterward.

**Verification:**
- New unit tests in `tests/test_vt_seek.py`
  (`test_seek_async_missing_vt_file_does_not_raise_and_clears_seek_state`,
  `test_seek_async_existing_vt_file_unaffected_by_missing_file_guard`) — the missing-file test
  uses a real `tmp_path` file that is never created (genuinely absent on disk, not a mocked
  `os.path.exists`), confirming `seek_async` doesn't raise, resets all five fields, emits
  `load_failed("File missing.")` exactly once, and issues no seek command. The sanity-control test
  confirms a present file's seek is completely unaffected by the new check. Both required a fixture
  fix: `TIMELINE[0]` (the shared module-level fixture used by several pre-existing tests) used a
  synthetic non-existent path (`"f00.mp3"`) — harmless before this fix since nothing checked
  existence, but two pre-existing tests (`test_on_file_loaded_consumes_pending_restore_via_real_seek`,
  `test_manual_seek_during_deferral_clears_pending_restore_last_write_wins`) legitimately drive
  `seek_async`'s same-file branch against it and started failing once the real guard was added.
  Fixed by pointing `TIMELINE[0]` at a real, persistent `tempfile.NamedTemporaryFile` (same pattern
  `tools/fs_race_harness.py` already used) rather than touching the many unrelated tests that only
  need `TIMELINE[0]`'s path as an opaque string. `pytest tests/ -q` — 195 tests, all green.
- Direct live-object smoke test (not the GUI, but the real unmodified `Player` class) driven
  against the actual on-disk missing file (`002 - Doctor Zhivago (Unabridged).mp3`, confirmed
  absent from the real folder) — `seek_async` raised no exception, all five fields reset,
  `load_failed` emitted `["File missing."]`, zero commands issued to the fake mpv instance.
- Re-ran both existing forced-condition harnesses to confirm no regression, since this fix touches
  the same function (`seek_async`) and field set as Parts 1+2: `tools/fs_race_harness.py` — all 5
  scenarios PASS (unchanged from before this fix); `tools/vt_restore_race_harness.py` — all 3
  checks PASS (unchanged).
- **User live-tested the exact reported scenario directly** (their own dev `entr` session, which
  auto-reloaded with the fix applied) and confirmed: banner shows on hitting the missing file;
  pressing Play afterward is a no-op (expected — `_on_book_removed` already tore down
  `current_file`/the player by that point); pressing Next after the banner removes/unloads the
  book; a manual rescan correctly revives the book with the still-missing files excluded. The user
  also tested a second missing-file scenario (moved a different file, skipped over it, banner
  shown, played the first file successfully, then some further navigation eventually triggered the
  unload) but was not fully certain of the exact sequence and asked not to change behavior yet,
  wanting to test and report more precisely first — **this is open, not a confirmed bug**; no
  further changes have been made pending clearer reproduction from the user.

**What was deliberately NOT built:** a richer design (sticky banner offering "remove from library"
vs. "rebuild/resync the virtual timeline around the gap and keep playing") was explicitly scoped
out as a genuinely larger feature — logged in TODO.md instead of attempted here. Current behavior
is unconditional unload + mark-missing the whole book on any single missing VT file, matching
M4B's existing behavior exactly.

---

## `_on_file_loaded`'s general "issue a seek, then unconditionally emit `file_switched`" race — FIXED and live-verified (2026-07-13)

**Status: FIXED.** Root cause confirmed via live instrumented timing (see below), fix designed and
implemented as two required parts, both verified under forced/adversarial conditions AND via
extensive real live testing (45 real cross-file crossings across all 6 input methods + Undo, 0
real misses). This was a standalone finding, independent of (but discovered by) the VT
restore-on-load fix (`_vt_restore_pending`/`defer_vt_restore`, same session) — both now ship
together, per the dependency decision made when this was still open (see the fix plan, still
retained at `.claude/plans/come-to-think-of-silly-sun.md` at commit time, for the full design
rationale, the "what solved means" contract, and the full verification bar).

**The fix, two required parts:**
1. **`_on_vt_file_switched`** (`app.py:1430-1442`) now gates its `is_seeking` clear on
   `self.player._seek_target is None`, instead of clearing unconditionally. Data-model finding
   that justified this (not just "try the guard again"): every reader of `is_seeking` in the
   codebase needs "has the seek settled" semantics, which `_on_time_pos_change`'s settle branch
   already owns correctly — `_on_vt_file_switched`'s unconditional clear was a second, competing
   writer, git-confirmed (`1c8d1b6`, 2026-05-15) to have been added on top of an already-working
   settle mechanism (`7f891f1`, the prior commit). Its only genuinely necessary case is when no
   seek was issued at all (`_seek_target` already `None`) — exactly what the guard preserves.
2. **`_on_end_file`'s ERROR branch** (`player.py:620-645`) now also resets
   `is_seeking`/`_seek_target`/`_logical_pos`/`_last_raw_global`/`_just_settled` when a seek was
   genuinely pending (`if self._is_seeking:`) — required as a companion fix, not optional: without
   it, a VT cross-file seek whose target file fails to load (missing/corrupt/permission error)
   would strand `is_seeking=True` forever with Part 1's guard now declining to ever clear it (no
   settle will ever arrive for a load that failed). This was a real, confirmed, pre-existing gap on
   `main`, unrelated to either bug fixed this session — found by explicitly enumerating every way a
   VT seek could still genuinely never settle before trusting the Part 1 guard as safe.

**Why the guard (Part 1) is legitimately different this time, not a third blind repeat of a closed
idea — checked with real evidence, not assumed:** both prior attempts at exactly this guard (one
undocumented/untracked from 2026-06-15 per CLAUDE.md's summary, one from this session's own
drift-fix branch) were tested EXCLUSIVELY against seeks that were structurally incapable of ever
landing at all (the VT-restore-on-load `book_ready`-before-`play()` bug, Layer 1, separately fixed
this session). Against a seek that can never land, any guard that keeps `is_seeking=True` alive
produces a permanent freeze — that is not evidence against the guard's own logic, it's the
inevitable consequence of testing it against an unrelated, unfixed bug. Confirmed via git history
(no commit ever added/reverted this exact guard — the 2026-06-15 attempt was never committed) and
this session's own TODO.md entry, which states directly: "the seek never settles to clear it, since
mpv is at 0." Neither historical freeze constitutes evidence against the guard when applied to a
seek proven capable of settling — which is exactly the general race's actual failure shape
(confirmed via live `[FS-RACE]` instrumentation: the seek DOES land in every captured miss, it's a
timing loss against the clear, not a structural non-landing).

**Verification — forced-condition harnesses (both required, both pass 100%):**
- `tools/vt_restore_race_harness.py` (existing, from the VT-restore-on-load fix work) re-run with
  Parts 1+2 applied — still 100% pass (sub-steps 1a/1b/1c all PASS).
- `tools/fs_race_harness.py` (new, built for this fix specifically) — a deterministic,
  non-sleep-based mock that controls the ORDERING of two independent events (the seek's settle
  sample vs. `_on_vt_file_switched`'s clear) rather than one delayed operation, since the general
  race's actual shape is two-events-racing, not one-thing-arriving-late. All 5 scenarios PASS: OLD
  code fails under clear-first ordering (proves the harness genuinely forces the bug — and this
  harness caught its own fixture bug during construction: an initial landing-sample value
  coincidentally equaled the target exactly, which masked the real corruption by making the
  post-reset resync branch recompute the same value by coincidence; fixed by using a sample with a
  deliberate 0.3s residual, matching how real mpv landings actually carry a small residual — this
  is exactly why the fix's own residual-discarding mechanism, `_logical_pos` adopting `_seek_target`
  exactly at settle, exists in the first place); OLD code survives settle-first (sanity control);
  NEW code survives BOTH orderings; NEW code leaves exactly the `_on_end_file`-ERROR-recoverable
  state (not a new freeze shape) when the settle never arrives at all.
- New unit tests: `tests/test_vt_file_switched_guard.py` (3 tests, pure state-machine style, binds
  the real unbound `MainWindow._on_vt_file_switched` to a tiny fake) and three new tests in
  `tests/test_vt_seek.py` for the `_on_end_file` ERROR-path reset (including a guard-vs-no-guard
  distinction check: the original abandon-reset pattern this mirrors has no explicit `is_seeking`
  guard because it's nested inside a caller condition that already guarantees a seek is pending;
  `_on_end_file` has no equivalent guarantee, since it's reachable from ANY load failure including
  a natural-advance play() failing with nothing pending — confirmed by re-reading the mirrored
  pattern's actual call site, not assumed). `pytest tests/ -q` — 193 passed.

**Verification — real live testing (not a substitute for the above, the confirmation on top of
it):** ~45 real VT cross-file crossings captured across one live session, deliberately covering
every one of the six input methods the original investigation found misses on (wheel-scroll,
arrow-key, seek/skip-button, progress-slider click, chapter-list click) plus natural EOF-advance,
in both paused and playing states, plus three explicit Undo tests (slider-seek+undo, wheel+undo
twice, chapter-list+undo) — satisfying CLAUDE.md's VT+Undo standing-rule checklist. Result, via a
fully automated sweep of the session's `fabulor.log` (not manual sampling): **0 real misses**. One
false-positive flagged by an early version of the sweep script turned out to be a rapid,
correctly-superseded seek (a fast wheel-tick issuing a newer target before the prior one could
settle — confirmed via the `seek_async: entry` line showing a third, different target firing
before the flagged crossing's settle window closed) — not a bug, and the sweep script was corrected
to account for legitimate supersession before being trusted. This live result is the confirmation
layer on top of the two forced-condition harnesses, not a replacement for them — a clean live pass
alone was proven insufficient evidence multiple times earlier this same session.

**Verification — 200-cycle automated OS-level restart stress test (added after the fix was
believed complete, to reconcile a real methodology gap):** the user separately ran ~50 manual
app relaunches pre-fix while trying to reproduce the deferred-restore bug and got 50/50 clean
restores — apparently contradicting the earlier-confirmed real failures. Reconciled, not
dismissed: manual clicking can't reliably force the deferred-restore race's actual window (the gap
between `book_ready` firing and mpv's own `file-loaded` event arriving, which is mostly determined
by mpv init/disk-cache timing, not human click cadence) — the same reasoning already applied to why
manual testing alone was insufficient for the general race earlier in this session. To get a real,
high-volume, machine-paced repro independent of human timing: 200 automated restarts were run by
touching an unrelated, unmodified file (`book_quotes.py`) every 3 seconds to trigger the user's own
`entr -r python main.py` dev-loop, which kills the running instance with a bare `SIGTERM` (confirmed
earlier this session: this does NOT run `closeEvent`, so this is a genuine hard-kill-and-reload
cycle, not a graceful close/reopen — arguably a MORE adversarial test than a clean close, since nothing
about the restart is app-controlled) and restarts against the same fixed saved position (progress
was not touched during the run, so all 200 cycles targeted the identical saved position). Result,
via the same automated `fabulor.log` sweep methodology: **200/200, zero real misses.** One
false-positive was caught and corrected during analysis — an early sweep incorrectly concatenated
the four rotated log files out of chronological order (`.log.1/.2/.3` do not rotate in the naive
numeric order; verified via each file's actual first/last timestamps), which briefly appeared to
show a "miss" that was really the scan window running into an unrelated, chronologically-earlier
log chunk. Corrected by checking real timestamps before trusting file order, then re-run clean.
This 200-cycle result is now the strongest single piece of evidence for the VT-restore-on-load
fix specifically (as opposed to the general race, which the ~45-crossing manual test and the
`fs_race_harness.py` forced-condition harness already covered) — it directly answers "why did 50
manual launches not reproduce a confirmed-real bug" (wrong instrument for the job, not evidence the
bug wasn't real) without needing to just trust that answer.

**Documentation cleanup done as part of landing this fix:** the `[VT-RESTORE-RACE]` DEBUG tag
(`player.py`, inside `_on_file_loaded`'s deferred-restore consumption) was kept as a permanent,
low-noise diagnostic breadcrumb (not investigation scaffolding — it fires rarely, only when a
deferred restore is actually consumed) but renamed to `[VT-RESTORE-CONSUME]`, since its old name
tied it to a specific investigation rather than describing what it reports — the same accuracy
standard applied to the stale `_on_time_pos_change` comment earlier this session. All `[FS-RACE]`
temporary instrumentation from the investigation phase was fully removed (confirmed via grep)
before this fix was designed.

---

### Original investigation record (preserved below, now historical — the mechanism it describes is fixed)

**Status at time of writing: confirmed mechanism, live-reproduced, NOT FIXED.** This was a
standalone finding, independent of (but discovered by, and at the time blocking) the VT
restore-on-load fix (`_vt_restore_pending`/`defer_vt_restore`, same session, see below).

**The mechanism, confirmed via live testing + code trace (not inferred).** `Player._on_file_loaded` (`player.py`, VT branch ~592-618) has this shape, for BOTH of the two cases that can issue a seek within it:

1. The `_pending_local_pos` branch (~555-601) — used by `seek_async`'s VT cross-file branch (user-initiated seek across a file boundary) — sets `_seek_target`/`_logical_pos` directly, issues `instance.command_async('seek', pending, 'absolute+exact')` (~601), and falls through.
2. The deferred-restore branch (added this session, ~612-615) — consumes `_vt_restore_pending` and calls `seek_async(pending_target)`, which sets `is_seeking=True`/`_seek_target=pending_target` together.

**Both cases fall through to the same line**, unconditionally: `self.file_switched.emit()` (~616). `file_switched` connects to `_on_vt_file_switched` (`app.py:1430-1432`) via `Qt.ConnectionType.QueuedConnection`; that handler unconditionally does `self.player.is_seeking = False`. Because it's queued, it runs on the next Qt event-loop iteration — almost immediately, and with no guarantee the just-issued seek has settled (settling requires an actual mpv `time-pos` sample landing within 1.0 of target, in `_on_time_pos_change`'s settle branch, `player.py` ~166-198). If the clear lands first: `_seek_target` is orphaned (the settle branch requires `is_seeking=True` to ever fire, so it can never re-adopt the target), and the `_logical_pos` maintenance block's gate (`not self._is_seeking`, ~199-234) opens prematurely, resyncing/accumulating `_logical_pos` from raw, mid-flight mpv samples — corrupting a seek that may have already landed correctly a moment earlier. This is what produces the reported symptom precisely: **the UI restores to the correct position, holds briefly, then resets** — not "never restores," which is the tell that distinguishes this from a simpler "seek never issued" bug.

**Why this wasn't caught by the existing, older cross-file-seek path (case 1 above), even though it has the identical hazard shape:** traced and confirmed (2026-07-13 investigation) — `_advance_or_finish` (the natural VT EOF-advance path, the overwhelmingly common case during normal listening) explicitly sets `_pending_local_pos = None` before advancing, so on that path `_on_file_loaded`'s seek block is skipped entirely (no seek issued, nothing to race). Only an explicit **user cross-file seek** (skip/chapter-nav across a file boundary) populates `_pending_local_pos` and actually exercises the race — a much rarer trigger than "every VT book's every launch," which is why it hadn't surfaced before. **This is not a new bug introduced by the VT-restore-on-load fix — it's a pre-existing, latent race that fix made far more frequently visible** (by adding a second, very-common-case caller — every VT restore-on-load — into the same hazardous shape). Verified: no re-arm of `is_seeking=True` happens between `file_switched.emit()` and `_on_vt_file_switched`'s clear for either case (grepped every `is_seeking = True` site in both files) — the two cases are mechanically identical, differing only in how often they execute the seek-then-emit sequence.

**Two prior approaches are CLOSED — already tried and reverted, do not re-propose either as "the fix":**
1. **Defer `file_switched`'s emission** (until after the seek settles, or until it's otherwise safe) — tried 2026-06-06, reverted. Broke Undo (VT slider stuck after undo). See CLAUDE.md's "Seek/position tracking — VT+Undo is the known-fragile zone" rule, which records this exact prior attempt.
2. **Narrow `_on_vt_file_switched`'s clear** (e.g. gate it on `_seek_target is None`, or otherwise make it conditional) — tried twice this session's drift-fix branch (`fix/seek-drift-logical-position`) and reverted both times. Trades the clobber for a UI freeze instead (labels/slider stuck on the previous book, because the seek genuinely never settles once `is_seeking` gets stuck `True` with no path to clear it). See CLAUDE.md's VT+Undo rule and TODO.md history for the same finding.

Any future fix attempt needs to find a THIRD approach that isn't a variant of either of these — e.g., something that changes when/whether a seek is issued relative to `file_switched`'s emission without touching the emission's timing itself or the consumer's clear logic. Not designed here; this entry documents the confirmed mechanism only, per explicit instruction to stop before designing a fix.

**Live reproduction evidence (VT restore-on-load, deferred-restore case):** user-reported and log-confirmed on real app launches with a VT book with a genuine saved position — approximately 4 failures out of ~50-90 real launches in one test session, all matching the "restores correctly, then resets, no error" shape. Confirmed via `fabulor.log` DEBUG capture (temporary `[VT-RESTORE-RACE]` tag, since removed) showing the deferred seek landing correctly, followed shortly by a queued `_on_vt_file_switched` clear, followed by `_logical_pos` reverting to a stale near-zero value.

**Live reproduction evidence (general race, manual cross-file seeks — this is the part that was explicitly re-verified against real instrumented timing rather than left as "theoretically exposed"):** a second, dedicated instrumentation pass (temporary `[FS-RACE]` DEBUG tags at `file_switched.emit()`, `_on_vt_file_switched`'s clear, the settle branch, and the `_pending_local_pos` cross-file `command_async` call — all since removed) was run against a real VT book, one input method at a time, explicitly to confirm or refute whether the *manual* cross-file-seek path (as opposed to the deferred-restore path) is really exposed to this race in practice, not just structurally in the code. Result: **confirmed exposed, across every manual input method tested that crosses a VT file boundary.** Six clean, unambiguous misses were captured (no `[FS-RACE] settle:` line ever appeared for the seek's target before a later action's seek overwrote `_seek_target`), spanning four distinct input types in one session:
- **Wheel-scroll crossing a boundary** (~21:05:59): target `2483.1234`s (`target_idx=0`) — `_on_vt_file_switched`'s clear landed ~2ms before the settle-worthy raw sample arrived; miss confirmed.
- **Arrow-key nav crossing a boundary** (~21:07:18): target `10731.566013481253`s (`target_idx=5`) — clear fired, no settle line ever appeared for this target.
- **Seek/skip-button crossing a boundary** (~21:08:32): target `10727.773719472038`s (`target_idx=5`) — same shape, confirmed miss.
- **Progress-slider left-click** (~21:09:42): target `26015.261058`s (`target_idx=14`) — confirmed miss.
- **Chapter-list left-click** (~21:11:02): target `14590.668627574567`s (`target_idx=9`) — confirmed miss, with an additional nested-load wrinkle: `_on_file_loaded` fired a SECOND time in the same sequence (a second `file_switched.emit()` at an already-`is_seeking=False` state), consistent with the deferred/cross-file target resolving into a file that itself triggers a further load event. Worth deeper investigation if this exact path is targeted by a future fix.

Several **clean settles were also captured in the same session**, on the SAME input methods (seek-button in the opposite direction, progress-slider right-click, chapter-list right-click) — confirming the race is genuinely intermittent/timing-dependent, not deterministic per input method: whether a given manual cross-file seek wins or loses the race depends on real scheduling, not on which button/control triggered it. **Natural EOF-advance during regular playback crossing a file boundary was confirmed as a non-issue**, exactly as the static trace predicted: at that moment `is_seeking`/`_seek_target` are already `False`/`None` (no seek was ever issued for a natural advance — `_advance_or_finish` sets `_pending_local_pos = None`), so `_on_vt_file_switched`'s clear is observed firing as a genuine no-op.

**Conclusion of this second instrumentation pass: the manual cross-file-seek path is not "theoretically" exposed — it reproducibly misses its settle in real usage, across every tested input method, at a rate consistent with genuine timing-sensitivity (not every attempt misses, but enough do, on ordinary interaction, to be a real user-facing bug independent of the VT-restore-on-load fix).** This raises the practical severity of this finding beyond "a fix I'm about to ship might depend on it" — it means VT cross-file navigation itself (skip, chapter click, slider click, wheel, arrows) can already intermittently corrupt `_logical_pos`/orphan `_seek_target` on `main`, independent of any code from this session. This should be weighed accordingly when this finding is next picked up for a fix design.

**Investigated, and NOT independently live-verified — a cross-thread race on `_vt_restore_pending` itself. Treat as "not fully ruled out," not "confirmed separate," per the same discipline this session already learned once tonight (the `is_seeking` reprime trap: a mechanism that explains every observed case is not automatically the only mechanism).** `_on_file_loaded` (and every other mpv event/property callback) runs on mpv's own internal `MPVEventHandlerThread` (confirmed via python-mpv's actual installed source, `fabulorenv/lib/python3.13/site-packages/mpv.py` — both `event_callback` and `observe_property` handlers are dispatched from the same `_loop` method on that one background thread), NOT the Qt main thread — **this part IS solid, confirmed by reading the actual installed library source, not inferred.** `_vt_restore_pending` is written from the Qt main thread (`defer_vt_restore`, called from `_restore_position`) and read/cleared inside `_on_file_loaded` on that separate thread, with no lock or Qt-signal marshaling between them — also confirmed by direct code reading. **What is NOT independently live-verified: the claim that this race cannot produce the "restores then resets" symptom.** That conclusion rests entirely on static reasoning (traced: `_vt_restore_pending` is read once, then cleared unconditionally as `seek_async`'s first action, before `is_seeking`/`_seek_target` are ever touched — so the two mechanisms are sequential stages in the same call, not concurrent) — it was never forced with an instrumented, timestamped reproduction the way the FS-RACE finding above was. The reasoning is sound and CPython's GIL genuinely does make a torn/corrupted read of a plain `float | None` impossible (only ordering/visibility is at stake, and a lost-write read would simply see `None` and skip the seek — a different, more plausible symptom: "VT book silently fails to restore at all, no `[VT-RESTORE-RACE]`-style log line despite genuine saved progress > 0"). But "the reasoning is sound" is not the same standard this session otherwise held itself to for every other claim tonight. **Action for a future session: if either the reproduced "restores then resets" symptom persists after the FS-RACE mechanism is fixed, or a NEW "silently never restores, no log line" symptom is ever seen, revisit this specific mechanism with real cross-thread timing instrumentation before assuming either possibility is closed.**

**Also checked, and likewise NOT independently live-verified against the actual visual stutter — ruled separable by code trace only: a first-app-launch-only VT flow-animation stutter**, independently reported by the user during this investigation. Confirmed present on `main` (pre-existing, not introduced by anything this session) — that part is solid (the user checked `main` directly). Confirmed via code trace only (not a forced live A/B against the actual stutter's timing) to occur in the progress-slider's own `QPropertyAnimation` glide (a self-contained animation, unread by/unwritten-to by the deferred seek or `_on_file_loaded`), not in the restore/settling window this fix's mechanism touches. Same caveat as above applies: this is "the trace found no interaction mechanism," not "a live-forced test showed no interaction." One caveat carried forward as an explicit contract for any future stutter investigation regardless: the VT chapter-walk in `_on_time_pos_change` is unguarded by `is_seeking` (unlike the non-VT branch) and now emits `chapter_changed` at a shifted, later time than before this session's fix (since the seek it's walking toward now fires later, from inside `_on_file_loaded`, rather than immediately from `_restore_position`) — this affects the chapter title/list label only, not the progress slider, but any future change to VT chapter-walk gating should be checked against this shifted timing, and any future stutter investigation should re-verify the separability claim live before relying on it.

---

## Compounding seek drift fixed via `_logical_pos` — measure-first, VT-first, and the same-shape-as-`b6a4023` risk that did NOT recur (2026-07-13)

**Branch:** `fix/seek-drift-logical-position` (`9521ee4` fix + follow-up docs). Core claim
**live-verified**, not merely designed/unit-tested — see the verification section below.

**The bug.** `Player.time_pos` returned `_cached_time_pos`, which `_on_time_pos_change` overwrites
with mpv's RAW reported position on every sample — including right after a seek settles, when
mpv's real landing differs from the nominal `_seek_target` by a small residual (the ~0.09s playing
overshoot / ~0.37s paused undershoot `_PAUSED_SEEK_UNDERSHOOT_COMP` was built to compensate). Every
subsequent seek computed its target from that raw, imprecision-laden `time_pos` rather than the
logical target the app already tracked in `_seek_target`, so residuals compounded — alternating
forward/back wheel-scroll or skip-button cycles crept forward every round, enough to reach EOF by
scrolling back and forth. Same root cause already caught and deferred 2026-07-06 (the entry below,
"Near-zero saved positions…").

**The fix.** A new `_logical_pos` field (always GLOBAL, like `_seek_target`), returned by the
`time_pos` getter when set. Adopted EXACTLY from `_seek_target` at settle (discarding the residual);
the first post-settle sample is SKIPPED so the discarded residual is not re-added; advanced by
raw-sample delta during normal playback; resynced to raw on a delta above
`_LOGICAL_POS_RESYNC_THRESHOLD` (2.5s). The getter is the single seam — all 18 `player.time_pos`
call sites are unchanged. `_cached_time_pos` and the chapter-walk stay raw and untouched (so the
epsilons stay calibrated against mpv's actual landing).

**Two design traps found and closed — both by re-deriving from real numbers, not trusting a
plausible label:**
1. *The reprime trap.* An early "reprime the delta baseline at settle" idea was traced against real
   data and found CASE-INCOMPATIBLE: same-file-paused and VT-cross-file settles want OPPOSITE
   baselines (paused → the next raw sample stays at mpv's actual landing; VT cross-file → the next
   raw sample catches UP to the target), so no single reprime value works for both. "Skip exactly
   the first post-settle sample" is the only case-agnostic fix — it refuses to reconcile the
   deliberately-created raw/logical divergence via a delta at all, waits one tick for mpv's stream
   to stabilize, then resumes lockstep. This superseded an earlier "no-op by construction" framing
   (which was TRUE for same-file but never validated against VT cross-file — exactly where it
   breaks).
2. *The `settled_this_call` ordering.* First implementation consumed the `_just_settled` skip on
   the settle sample itself instead of the next one; caught by hand-tracing the VT numbers
   (694.51/694.86) BEFORE testing. Fixed with a `settled_this_call` local so the skip lands on the
   first post-settle sample.

**Measured, not guessed.** `_LOGICAL_POS_RESYNC_THRESHOLD = 2.5` and the "exactly one ragged
post-settle sample" assumption both came from live instrumentation (5879 samples / 593 settles;
482 post-settle sequences, second sample always clean, max |delta| 0.128s, zero two-ragged cases).
One precisely-bounded residual risk carried forward: a sub-2.5s SECOND consecutive ragged
post-settle sample would leak, but it never occurred in the data, is capped below the resync
threshold by construction, and cannot compound — falsification signal is "two consecutive
post-settle samples both above the normal-playback floor."

**The `b6a4023`-shape risk that did NOT recur — the whole point of the VT-first discipline.** This
was the standing worry (CLAUDE.md "VT+Undo is the known-fragile zone"): `b6a4023` was a
structurally similar heuristic (new tracking field + per-sample decision) that scored 32/32 clean
under instrumentation, shipped, and still broke VT backward-seek / play-pause-icon / chapter[1]→[0]
click for reasons never diagnosed. Per the plan, VT+Undo + those three exact surfaces were
verified FIRST, before the drift symptom. They came back **clean** — so this fix, though the same
SHAPE as `b6a4023`, did not share its undiagnosed failure. That is the direct payoff of not
trusting the clean instrumentation run and front-loading the historically-fragile checks.

**Live verification (the core claim, confirmed — not assumed):**
- Chapter Next/Prev (paused + playing), Undo after a seek (VT and non-VT), VT backward-seek, the
  play/pause icon after a settle, chapter[1]→[0] click — all clean (the `b6a4023` regression
  surface).
- The drift symptom itself: alternating wheel-scroll and skip-button cycles, paused and playing,
  embedded M4B — position returns to origin instead of creeping; absolute total-elapsed/remaining
  read exactly ("10s is 10s"); steps are steady, not compounding. Was chaotic before ("drifting
  all around, impossible to tell boundaries apart"), now steady.

**Three things this fix SURFACED but deliberately did NOT fix (each its own deferred TODO,
2026-07-13, on `main`):**
1. *VT restore-on-load* — the restore seek never actually executes in mpv (races the file load),
   so VT books resume near 0. Pre-existing (silent before, because raw `time_pos` just showed 0);
   the fix made it a visible desync. Two guards were tried and REVERTED — they only trade the
   data-loss clobber for a UI freeze, because the seek never settles regardless; the real fix is to
   make the seek execute. VT restore-on-load behaves exactly as on `main` — neither improved nor
   worsened. (Entangled clobber + seek-execution item in TODO.md.)
2. *Chapter-elapsed ~1s boundary offset* — a pre-existing `_CHAPTER_WALK_TOLERANCE` (0.5s)
   chapter-DISPLAY artifact (absolute position stays exact), now visible because absolute got
   exact. Untouched (epsilon zone the plan avoided).
3. *`_PAUSED_SEEK_UNDERSHOOT_COMP` over-application* and the *chapter-slider load-time retrace*
   (both found earlier this arc, already logged).

**Discipline that paid off, recorded for the next attempt in this zone:** measure before picking
constants; VT+Undo FIRST; re-derive from real numbers rather than defending a plausible label
(the reprime trap and the `settled_this_call` ordering were both caught this way); and when the
fix surfaces a deeper pre-existing bug, scope it OUT and defer it as its own item rather than
letting the branch grow a fourth tail (VT restore-on-load).

## Cover-pool right-click silent no-op (2026-07-12)

Found while investigating a user report that right-clicks aren't always registered — especially
on the cover-pool theme button (Settings → Themes → "Cover art based theme"). This is a
distinct, minor issue from the main fade-overlay investigation (see the theme-fade-overlay entry
below for the primary finding); noted here for completeness, not currently prioritized for a fix.

`ThemeManager._on_cover_pool_btn_right_clicked` (`theme_manager.py:948-959`) starts with:

```python
if not self._cover_theme:
    return
```

`self._cover_theme` is only populated once cover-art theme extraction has run for the current
book's cover (`apply_cover_theme`) — so a right-click on the pool button before that (no book
loaded, or extraction still pending right after a book switch) is a complete, silent no-op: no
visual change, no log, no signal. This will read identically to "my right-click didn't
register," but it's a deliberate state gate, not an event-handling bug — the button's associated
feature genuinely doesn't apply yet.

Same shape as the main-window drag-area's `db.get_book_count() > 0` gate
(`app.py:_on_drag_area_pressed`) — both silently swallow a right-click when the feature they'd
activate has no valid target yet. The drag-area case is a one-time "any books indexed at all"
check, so it's rarely hit after first launch; the pool-button case is easier to hit repeatedly
since cover-theme availability is per-book and can be momentarily unset right after switching
books.

Not fixed — deferred, see DEBT_INVENTORY.md "Theme system". If revisited, the straightforward
fix is a brief visual nudge (e.g. a quick shake/flash) when the right-click is a no-op for this
reason, so it reads as "not available yet" rather than "nothing happened."

## Book Detail Panel keyboard shortcuts: four more focus/dispatch bugs, two of them generalizing the Session 3 invariant (2026-07-12)

Extending the keyboard focus-ownership invariant (see the entry below this one) from the
main-window transport keys into `BookDetailPanel` — a panel with far more clickable, later-
hideable widgets than any panel exercised so far — surfaced four more bugs, each traced live
before any fix. Two were new instances of the exact class Session 3 already understood; two
were genuinely new failure modes the invariant hadn't covered. All four are fixed; this note is
the trace record, including one case where the user's live report directly overrode an
incorrect first assessment.

### Bug 1 — three more widget-deletion-strands-focus sites (tag chip, History row, bulk-delete button)

**Symptom (live report):** deleting a tag chip closed the whole Book Detail panel; arrow keys
also started changing volume afterward.

**Trace:** `_rebuild_tag_chips()` (`book_detail_panel.py`) deletes every tag chip's `x`
(remove) `QPushButton` — including the one the user just clicked, which held real Qt focus at
that exact moment — via `deleteLater()`, with no reclaim. Confirmed the SAME shape already
found and fixed for Library/ChapterList/Settings-etc. in Session 3, just at a site inside a
panel's own internal rebuild rather than at panel open/close. Two more sites with the identical
shape turned up on inspection, all fixed the same session, before shipping:
- `_on_history_delete_confirmed`'s `_finish()` callback deletes a `_HistoryRow`, whose
  `_trash_btn` (`QToolButton`) could hold real focus if the user mouse-clicked it before
  keyboard-confirming the delete.
- `_on_delete_book_stats` (bulk "Delete listening history") calls
  `self._delete_history_btn.setEnabled(False)` on the very button that was just clicked to
  reach this method — `setEnabled(False)` drops Qt focus exactly like `hide()`/`deleteLater()`
  do, immediately and synchronously.

**Why "arrow keys manipulate volume" is the SAME bug, not a second one:** once focus drops to
`None`, `MainWindow._focus_allows_global_shortcuts()` reads "nothing panel-local has focus" and
the GLOBAL dispatcher takes over for EVERY subsequent key, not just the one that happened to
close the panel — `Up`/`Down` firing `VOLUME_UP`/`VOLUME_DOWN` and arrow-driven panel-close are
two visible symptoms of one root state (focus at `None`), confirmed by tracing that both stop
reproducing together once focus is correctly reclaimed.

**Fix, two layers (per explicit instruction not to keep patching individual sites reactively
after the third one turned up):**
1. Individual reclaim at each known site (`_rebuild_tag_chips`, the History per-row delete
   callback, `_on_delete_book_stats`) — immediate, doesn't wait for the next keypress.
2. A general safety net, `BookDetailPanel._ensure_panel_owns_focus()`, called at the top of
   `eventFilter` on every `KeyPress`: if `QApplication.focusWidget()` is `None` or not a
   descendant of the panel (`isAncestorOf`), reclaim focus for the panel before the key is
   processed. Cheap (`setFocus()` on an already-focused widget is a no-op) and makes any FUTURE
   site with this same shape self-heal on the very next keypress instead of silently
   reintroducing the bug — this is the piece that generalizes beyond Session 3, which fixed
   each known site individually with no equivalent net.

Verified live, 3/3 deterministic runs: tab-cycling, F/Del/K, and History/Cover nav all survive
a full pass of tag-deletion → History-row-delete → bulk-delete-arm in sequence.

### Bug 2 — Up/Down while editing metadata fired History row-selection instead of cycling fields

**Symptom (live report):** in the History tab, `Tab` into metadata edit mode, then `Up`/`Down`
moved the History row selection (and its hover-reveal visual) instead of moving between the
title/author/narrator/year fields.

**Trace:** `BookDetailPanel.keyPressEvent`'s own docstring had claimed (written earlier the
same session, before this bug was found) that editing fully shields the method from ever being
reached — reasoning that `_enter_edit_mode` grants a `QLineEdit` real focus, so that field
should own every key. **Disproven by direct instrumented trace**, same mechanism already
documented in the Session 3 note below for the main-window case: a single-line `QLineEdit` has
NO native handling for `Up`/`Down` (unlike `Left`/`Right`/`Del`/letters, which it genuinely
consumes for cursor movement/delete/typing) — Qt delivered `Up`/`Down` to the focused
`QLineEdit` first, it left them unaccepted, and they propagated to `BookDetailPanel
.keyPressEvent`, which — with no `_editing` check — dispatched them as whatever tab-local
binding was active underneath the edit (History's own `Up`/`Down` row-selection, since the
user was on the History tab). This is the SAME class of bug as Session 3's main-window
Up/Down-in-a-field case, just manifesting inside one panel's own local dispatch instead of the
global one — confirming the underlying Qt behavior (a widget can legitimately own SOME keys
and not others, and the ones it doesn't own still propagate) is general, not scoped to
`MainWindow`'s dispatcher specifically.

**Fix:** `keyPressEvent` now checks `self._editing` FIRST. If editing: `Up`/`Down` route to
`_cycle_metadata_field(backward=...)` — the exact method `Tab`/`Shift+Tab` already use, so
there's one field-cycling implementation, not two; every other key falls through to
`super().keyPressEvent(event)` untouched, since `QLineEdit` already correctly owns and consumes
`Left`/`Right`/`Del`/letters/`Enter` (`Enter` specifically triggers the field's native
`returnPressed` → `_on_inline_save`, confirmed already working correctly — no fix needed there,
that part of the original report described existing correct behavior, not a bug). If not
editing: dispatch proceeds exactly as before (tab-local bindings, then top-level).

Verified live: `Down`/`Down`/`Up` while editing correctly moved title→author→narrator→author
with zero History-selection-index change; `Left`/`Right`/`Del` while editing confirmed to NOT
fire tab-cycling or remove-confirm (fall through to native `QLineEdit` behavior as intended).

### Bug 3 — modal file-picker's Escape order was backwards (initial assessment was WRONG, corrected by user pushback)

**Symptom (live report):** Cover tab, keyboard-select the `+` slot, press `Enter` → opens the
native file picker. Press `Escape` once → Book Detail closes (picker stays open). Press
`Escape` again → NOW the picker closes.

**First response — WRONG, corrected before any code changed:** initially characterized this as
"expected modal-dialog behavior" (a genuinely modal dialog should own `Escape` while it's on
top, so needing an extra `Escape` to fully back out seemed like an inherent, low-priority cost
of using a modal file picker at all). **The user directly pushed back**: "the order is opposite
of expected" — first `Escape` should cancel the topmost thing (the picker), not the panel
underneath it. This is exactly the kind of correction this project's collaboration model is
built to catch (flag → the user corrects the framing → re-investigate), and re-tracing
immediately found the real, fixable bug the first assessment had talked past.

**Re-trace, this time live with a real `QFileDialog`:** `BookDetailPanel.eventFilter` is
installed on `QApplication.instance()` in `showEvent`/removed in `hideEvent` — meaning it
intercepts EVERY `KeyPress` event app-wide for as long as Book Detail is open, INCLUDING ones
destined for a modal dialog it opened but doesn't own the input routing for. Confirmed by
direct trace (a real, shown `QFileDialog(modal=True)`, `QApplication.activeModalWidget()`
correctly returning the dialog): sending `Escape` to the dialog's own focused child
(`fileNameEdit`) still reached `BookDetailPanel.eventFilter` first — event filters installed
on `QApplication` run ahead of ANY target widget's own handling, dialog or not — and the
filter's own Escape-priority chain (tag-clear → edit-cancel → panel-close) ran and closed the
panel before the dialog's native Escape-to-cancel ever got a turn. `_ensure_panel_owns_focus()`
(Bug 1's fix) had the identical shape of bug layered on top, confirmed by the same trace: it
would have fought to steal focus back to the panel from the dialog's own internal widgets on
EVERY keystroke while the dialog was up, since those widgets belong to a separate top-level
window and are not descendants of `BookDetailPanel` (`isAncestorOf` correctly returns `False`
for them) — so the safety net's own logic ("focus isn't a descendant, reclaim it") was, in this
one case, actively wrong instead of protective.

**Fix:** a single guard at the very top of `eventFilter` — `if event.type() ==
QEvent.Type.KeyPress and QApplication.activeModalWidget() is not None: return False` — declines
to handle the event at all whenever ANY modal dialog anywhere in the app is active, not scoped
to dialogs this panel itself opened (so it also protects against any future modal a later
feature adds). This single check covers both the Escape-interception bug and the focus-reclaim
overreach, since both were downstream of the same missing "am I allowed to act right now"
question.

Verified live, 3/3 deterministic runs with a real (non-blocking `.open()`, since
`getOpenFileName()`'s blocking call can't be exercised from the same test script)
`QFileDialog`: first `Escape` now correctly cancels ONLY the dialog; Book Detail is fully
unaffected (`isVisible()` stays `True` throughout). Confirmed the fix does not change normal
(no-dialog) `Tab`/`Escape`/tab-cycling behavior — the guard is scoped strictly to "a modal is
active," not a blanket change (separate control-case test, both live and in
`tests/test_book_detail_panel_keys.py`).

### Bug 4 (design question, not a bug) — should Cover's tab-local key overrides be "made consistent" by removing top-level actions from History/Tags?

Raised, not a defect: since Cover tab's own `Up`/`Down`/`Space`/`Enter`/`Del`/`F`/`T`/`S`/`C`
take priority over the top-level `F`(finished-toggle)/`Del`(remove)/`k`(lock) bindings while
that tab is active, top-level actions are effectively unreachable from Cover — raising the
question of whether to remove them from History/Tags too, for symmetry. **Kept as-is, no code
change:** the asymmetry is the exact same "more specific tab-local binding wins" pattern
History's own `Up`/`Down`/`Del`/`Space`/`Enter` already apply over the SAME top-level bindings,
uncontroversially — Cover is simply the tab with the most local meaning today, not a special
case needing correction. Removing top-level reach from History/Tags would trade away real
functionality (keyboard mark-finished/remove/lock from most tabs) to fix a labeling
inconsistency, not a functional one.

---

## Keyboard focus ownership: three related bugs surfaced by adding transport shortcuts (2026-07-11)

Adding main-window transport shortcuts (Space/volume/speed/skip/chapter/mute/undo,
`shortcuts.py`/`app.py`) surfaced three keyboard-focus bugs in sequence, each traced live before
any fix — per the project's rule that live Qt behavior is ground truth, not a script's assertion.
All three share one underlying gap and were ultimately fixed as a single enforced invariant (see
the CLAUDE.md "Keyboard focus ownership" rule). This note is the trace-by-trace record, including
two dead ends worth knowing about if this class of bug resurfaces.

### Background: how a key reaches (or doesn't reach) the dispatcher

`MainWindow.keyPressEvent` delegates to `ShortcutDispatcher.handle_key_event`
(`shortcuts.py`). Two independent facts about Qt matter here, both confirmed by direct
instrumented trace (not assumed from documentation):

1. A key event is delivered to the **focused widget first**. If that widget's `keyPressEvent`
   leaves it unaccepted (e.g. a plain `QLineEdit` doesn't handle `Up`/`Down` in a single-line
   field), Qt propagates the SAME event up the parent chain, and `MainWindow.keyPressEvent`
   still runs — it is NOT skipped just because a child widget saw the key first.
2. `raise_()`/`.show()` change paint/Z-order stacking only. They have **zero effect on Qt
   keyboard focus**. A widget "underneath" a freshly-raised panel can still hold real focus and
   keep consuming every key exactly as if the panel on top of it didn't exist.

### Round 1 — always-on chrome widgets stole keyboard focus at startup and via Tab/arrow nav

**Symptom (live report):** `Space` at startup opened the speed menu instead of toggling
play/pause. Arrow keys moved a focus highlight through hidden controls (the volume slider) and
then began opening sidebar panels one by one.

**Trace:** `speed_button` (`ShimmerButton`, a `QPushButton` subclass) was the first
`Qt.StrongFocus`-default widget constructed in `MainWindow._setup_ui`, so Qt auto-focused it at
startup with no explicit `setFocus()` call needed — Qt does this automatically for the first
eligible widget in tab order when nothing else claims focus. `Space` then fired the focused
button's own `clicked`. The sidebar (`build_sidebar`) is `move(-50, 56)` then `show()`n — visible
to Qt (in the focus/tab chain) despite being off-screen; nothing ever `hide()`s it, only moves it.
Its six trigger buttons + `sleep_cancel_btn` carried Qt's default `StrongFocus`, so arrow/Tab
navigation could land on them and `Space` would fire whichever was focused.

**Fix:** `setFocusPolicy(Qt.NoFocus)` on every always-on chrome widget outside a panel: the five
transport buttons (already done in an earlier pass this session), the two title-bar buttons
(already done), `speed_button`, `sleep_timer_label`, the six sidebar triggers +
`sleep_cancel_btn`, `undo_overlay`, `eof_revert_btn`/`eof_close_btn`/`cancel_scan_btn`,
`scan_now_btn`, `go_to_library_btn`. `ClickSlider` (progress/chapter/volume sliders) needed no
change — it's a `QWidget` subclass, `NoFocus` by default, with no `keyPressEvent` override, so it
was never a candidate.

**Verification:** instrumented headless trace confirmed `QApplication.focusWidget()` is `None` at
startup and stays `None` through the transport view with nothing clicked, and a synthetic `Space`
press is consumed by the dispatcher (fires `PLAY_PAUSE`).

### Round 2 — stuck focus after Library / ChapterList / BookDetail close

**Symptom (live report):** After closing Library, every shortcut — not just modified ones —
stopped firing. After opening the chapter list once and closing it once, focus stayed stuck on it:
arrows navigated chapters, `Space` activated the highlighted one, even though it was visually
closed.

**Trace, first attempt (WRONG, corrected via re-trace, not assumption):** `LibraryPanel.showEvent`
calls `self._list_view.setFocus()` unconditionally on open; nothing in `_on_library_hidden`
(`panels.py`) ever called `clearFocus()`. First fix: add `clearFocus()` targeting the actual
focused descendant, placed BEFORE `self.library_panel.hide()`. This looked correct by inspection
and matched the obvious "undo what open did" shape — but a live re-test after applying it showed
the bug **still reproduced**. Fine-grained tracing (print statements at every line of
`_on_library_hidden`, run 3× for determinism) showed exactly why:
```
[traced] before clear, focused=QListView isAncestorOf: True
[traced] called clearFocus() on QListView
[traced] immediately after clearFocus(), focusWidget = None      # <- worked!
[traced] immediately after hide(), focusWidget = QListView       # <- undone by hide()!
```
`hide()` on a widget that had JUST been cleared of focus **silently re-grants it focus** if
nothing else in the window is a viable focus candidate — confirmed reproducibly across 3 runs,
not a one-off. This is a real Qt behavior (widget hide/show focus reassignment falls back to the
"best" remaining candidate), and in a codebase where chrome is NoFocus-swept, the widget being
hidden can BE that fallback candidate, defeating a clear that ran moments earlier.

**Fix (verified, 5/5 deterministic re-runs):** move `clearFocus()` to run AFTER `hide()`, not
before — ordering is load-bearing. Applied to `_on_library_hidden` (`panels.py`),
`ChapterList._on_fade_out_finished` (`chapter_list.py` — this single completion handler is
reached from BOTH of the chapter list's close paths: `MainWindow._show_chapter_dropdown`'s
external toggle branch, and the widget's OWN `keyPressEvent` handling `Escape`/`C` directly — the
second path matters because when the list holds real focus, a user's second `C` press is
delivered by Qt straight to the list's own handler, never reaching `MainWindow` at all, so a fix
only in the external toggle path would have missed the common case), and defensively to
`_on_book_detail_hidden` (Book Detail didn't grab focus on open yet at this point in the session,
so this was a no-op then — it became load-bearing once Round 3's fix added the claim).

**Also confirmed via `git log -p --follow`:** neither `_on_library_hidden` nor the chapter list's
close paths ever had a focus-restore step in their history. This predates the transport-shortcuts
work; it was invisible before because nothing important lived in `MainWindow.keyPressEvent` for
the transport controls until this session made Space/arrows/etc. load-bearing global shortcuts.

### Round 3 — arrow-in-field dismissed edits, Book Detail bled through to Library underneath

**Symptom (live report, two distinct repros in one message):** (a) Focus a Book Detail
inline/tag edit field, press `Up`/`Down` — the whole panel dismisses. (b) Open Book Detail from
Library, press arrow keys a few times, then `Space` — the Library underneath visibly navigates and
a book loads, even though Book Detail is the only thing visible.

Per explicit user direction, this round was investigated fully (both mechanisms traced to their
actual root cause) BEFORE any fix was written, to avoid a third round of reactive whack-a-mole.

**Trace (a):** `QLineEdit.keyPressEvent` for `Up` correctly receives the key first (confirmed via
a direct instrumented `sendEvent`), but a plain single-line `QLineEdit` has no special handling
for `Up`/`Down`, so it calls the base `QWidget.keyPressEvent`, which leaves the event
**unaccepted**. Qt's propagation then delivers the SAME event to `MainWindow.keyPressEvent` next
— confirmed by trace (`accepted_before=True` going in per-handler, `accepted=False` coming out of
the QLineEdit call). `MainWindow.keyPressEvent` had ZERO focus-awareness — it unconditionally
handed every key to the dispatcher regardless of what was focused. `VOLUME_UP`/`VOLUME_DOWN`'s
handler chain ends in `_on_volume_changed`, which unconditionally calls
`self.panel_manager.hide_all_panels()` — that's what dismissed the panel. Confirmed this is
GENERAL, not Up/Down-specific: ordinary letters typed into the same field never leaked, because
`QLineEdit` DOES accept/consume plain character keys itself (never reaches step 2 of
propagation) — the bug is confined to whichever specific keys a given focused widget happens not
to care about, which today is Up/Down/m/u for a `QLineEdit`, but would be different keys for a
different widget type.

**Trace (b):** `PanelManager.open_book_detail` → `load_book` → `_start_book_detail_entry`
(`panels.py`) read in full — none of the three ever call `.setFocus()` on anything; they only
`.show()`/`.raise_()`. Confirmed live: immediately after Book Detail opens, `QApplication
.focusWidget()` is STILL `Library._list_view`, and `_list_view.hasFocus()` is `True`. Sending
three real `Down` presses (to whatever currently has real focus, exactly as the OS would) never
reached `MainWindow.keyPressEvent` even once — they went straight to `_list_view`'s own key
handling, and `currentRow` advanced 1→2→3 exactly. A subsequent `Space` activated the current item
directly, and `MainWindow.current_file` was observed to actually change. This is Book Detail's
open path never claiming focus, combined with Library's `_list_view` still legitimately holding
it from before Book Detail opened over it.

**Why these are two different mechanisms sharing one gap, not one bug:** (a) the CORRECT widget
has focus and gets first refusal, but silently declines a key it doesn't want, and nothing stops
the leftover from reaching global scope. (b) the WRONG widget (belonging to a different, now-
obscured panel) has focus and fully consumes the key itself — it never reaches global scope at
all. Opposite failure directions. But both stem from the same absence: nothing in the codebase
ever established "the currently active panel owns keyboard focus" as an enforced invariant —
panels either grab focus ad hoc on their own open (Library, ChapterList) or never grab it at all
(the other six), and nothing arbitrates when panels open over each other.

**Fix, both halves together (per explicit user direction — fixing only one leaves the other's
failure mode open):**
- **Ownership** — `PanelManager._claim_panel_focus(panel_widget, panel_key=None)`, called from
  every one of the six `_start_*_entry` methods (Settings/Speed/Sleep/Stats/Tags/BookDetail —
  audited via a full read of every panel's open path in `panels.py`, confirmed NONE of the six
  grabbed focus before this fix, not just Book Detail) right after `.raise_()`. Settings/Speed/
  Sleep reuse `panel_tab_widgets(panel_key)` — the SAME "first focusable widget" list Tab-cycling
  already treats as canonical — as the claim target, so opening a panel and immediately pressing
  Tab continues into its second control, matching the existing Tab-cycle's own notion of order.
  Stats/Tags/BookDetail (not in that list) claim the panel root itself, granting it
  `Qt.StrongFocus` if it doesn't already have a Tab-accepting policy. Library/ChapterList's
  existing self-managed grabs were left untouched (working, no reason to route them through a
  second mechanism).
- **Dispatch** — `MainWindow._focus_allows_global_shortcuts()`: `keyPressEvent` only calls
  `handle_key_event` when `QApplication.focusWidget()` is `None` or `MainWindow` itself. This
  form (rather than enumerating every panel and checking `isAncestorOf`) is deliberately simple:
  because Round 1's NoFocus sweep already guarantees no chrome widget outside a panel can hold
  focus, and Round 3's ownership fix guarantees every open panel's widget genuinely does, "focus
  is not None and not MainWindow" is EQUIVALENT to "focus is panel-local" by construction — no
  panel list to keep in sync, and it can't silently drift if a panel is added later (though a new
  panel/overlay still MUST call the claim/release helpers itself, or it becomes invisible to this
  equivalence in a different way — see the CLAUDE.md rule).
- Also released the five newly-focus-claiming panels' close handlers symmetrically
  (`_on_settings_hidden`/`_on_speed_hidden`/`_on_sleep_hidden`/`_on_stats_hidden`/
  `_on_tags_hidden`), same `_release_panel_focus` helper, same after-`hide()` ordering from
  Round 2's lesson. Book Detail's pre-existing inline clearFocus was consolidated into the same
  shared helper rather than left as duplicated logic.

**Verification — two false signals caught by re-tracing, both test-harness bugs, not code bugs:**
1. First test run reported Symptom A "still failing" (`MainWindow.keyPressEvent ran (SHOULD BE
   False)?: True` for every key). Re-traced with fine-grained logging and confirmed the fix DOES
   work — `_focus_allows_global_shortcuts()` correctly returned `False`, and the dispatcher never
   fired. The test's assertion was checking the wrong thing: `keyPressEvent` is SUPPOSED to run
   every time (it's where the new guard lives) — the test needed to check whether the dispatcher's
   HANDLER executed (panel closed? volume changed?), not whether the outer method was invoked.
2. First test run reported Symptom B "still failing" for all five non-Book-Detail panels (focus
   stayed on Library's `_list_view` after "opening" Settings/Speed/etc.). Traced: the test called
   the GATED `_open_settings_flow()` while Library was already open — and `is_overlay_open_or_
   committed()` (a pre-existing, correct, unrelated policy) silently dropped the open request, so
   `settings_panel.isVisible()` was `False` the whole time; there was nothing to test. Re-ran
   calling `_start_settings_entry()` directly (bypassing the gate, isolating the focus-claim
   mechanic from the separate one-overlay-at-a-time policy) and confirmed the claim mechanic works
   correctly for all five panels, 3/3 deterministic runs. Also separately confirmed, in a
   REALISTIC single-panel-open scenario (matching how these five are actually reached in the real
   app — from the sidebar, never over Library, since the gate prevents that combination), that
   `_release_panel_focus` correctly returns focus to `None` on close, 3/3 runs.

Both false signals were caught by re-tracing with more targeted instrumentation rather than either
trusting the first red result or trusting the fix's own reasoning — same discipline as Round 2's
correction. General lesson for this class of bug: a headless Qt focus trace is trustworthy ground
truth here (unlike the settings-panel-layout class of bug documented elsewhere in this file, where
headless scripts repeatedly lied) — but the TEST's assertions and the TEST's scenario setup are
just as capable of being wrong as the code, and both need to be independently sanity-checked
against what the code is actually doing before accepting a red (or a green) result at face value.

---

## History tab delete-session animation: stall, above-row-shift, and color-flash — three distinct bugs in one code path (2026-07-11)

Bug report: confirming "Delete this session?" in the Book Detail Panel's History tab animated a
partial slide that visibly stalled partway, leaving the last remaining row's content sitting at a
vertical offset. Three screenshots showed the stall clearly. This turned out to be three separate,
independently-diagnosed bugs layered in the same ~30-line method
(`BookDetailPanel._on_history_delete_confirmed`), each requiring its own fix — worth recording all
three, including the two dead ends, since the failure modes are non-obvious and easy to reintroduce.

### Bug 1: the collapse stalls partway (FIXED, `813f7d9`)

`_HistoryRow.__init__` (book_detail_panel.py) calls `self.setFixedHeight(self.ROW_H)` — `ROW_H = 27`.
`QWidget.setFixedHeight()` sets BOTH `minimumHeight` and `maximumHeight` to that value; this is easy
to forget since the method name only mentions "fixed," not that it clamps both bounds. The delete
handler then runs:

```python
anim = QPropertyAnimation(row, b"maximumHeight", self)
anim.setStartValue(row.height())
anim.setEndValue(0)
```

Since `minimumHeight` is still pinned at 27, the layout can never actually shrink the row below that
floor no matter what `maximumHeight` animates to — Qt resolves effective widget height from both
constraints. The animation itself runs with no error; the visual collapse just stalls the instant it
hits the row's own minimum. Fix: `row.setMinimumHeight(0)` before constructing the animation. One
line, no other changes needed for this bug alone.

**Excluded Books has the identical latent bug, but it's invisible in practice.** `_ExcludedRow`
(`ui/excluded_books.py`) also does `setFixedHeight(self.ROW_H)`, and its restore-row removal
(`ExcludedBooksPopup._on_row_restore`) runs the same shape of `maximumHeight` animation before
`takeItem()`. It never visibly stalls because the row lives inside a `QListWidget` via a
`QListWidgetItem` whose `setSizeHint()` was fixed once at creation and never updated to track the
animating property — the list viewport simply doesn't reflow live during the animation at all; the
row just sits at its fixed item size until `takeItem()` pops it out instantly. This matches what the
user independently observed testing it side-by-side ("it doesn't animate like History... not saying
this as necessarily a bug, it looks alright as it is"). **CLAUDE.md's prior claim that Excluded Books
"intentionally copies this same slide pattern" from History is stale/inaccurate** — it copies the
hover-reveal eye-icon slide mechanics, not a working removal-collapse animation. Left unfixed
(user explicitly said not to touch it, since the current frozen/instant look reads fine as-is) — but
worth knowing the shape of the bug is duplicated there if it's ever touched.

### Bug 2: rows ABOVE the deleted one visibly shift (FIXED via AlignTop; a first attempted fix was reverted for making the animation worse)

After fixing the stall, live testing surfaced a new symptom: not just rows below the deleted row
sliding up (expected), but rows ABOVE it visibly shifting down and back — including, in one test, the
topmost row in a long list when deleting near the bottom. This shouldn't be possible in a normal
top-to-bottom `QVBoxLayout` reflow from a single shrinking child.

Root cause: `_history_container`'s fixed height (set by `_resize_history_container`,
`n * ROW_H`) was only updated ONCE, inside the animation's `finished` callback — for the entire
150ms collapse, the container stayed at its OLD (larger, for the old row count) fixed height while
the row inside it was shrinking toward 0. `_history_layout` (`QVBoxLayout`, spacing 0) had no
`setAlignment` set, so with the container's fixed height now exceeding the sum of its children's
actual heights, Qt's default behavior distributed that slack across ALL rows in the layout rather
than leaving it as unused space below the last row — hence unrelated rows shifting.

**First fix attempt (worked for this bug, made overall smoothness worse — reverted):** added a
`valueChanged` handler on the SAME animation that called
`self._history_container.setFixedHeight(base_container_h + value)` every tick, keeping the
container's height in lockstep with the row's shrinking `maximumHeight`. This did fix the
above-rows-shifting symptom. But it introduced a new, separate jaggedness: each animation tick now
forced TWO independent layout passes instead of one — one from the row's own `maximumHeight` change,
one from the container's `setFixedHeight` call triggered by the Python slot — and the user reported
this as visible stutter even with as few as 2 total rows (ruling out an overlapping-animations
theory; this was a single delete, single animation, still jagged).

**What actually shipped:** reverted the lockstep `valueChanged` hack entirely. Added
`_history_layout.setAlignment(Qt.AlignmentFlag.AlignTop)` instead — this alone stops the slack
redistribution (any leftover space between the container's stale fixed height and its rows' actual
summed height collects at the bottom, unused, rather than being distributed across rows), with zero
added per-frame cost. Confirmed sufficient on its own; the container still only gets resized once, in
`_finish()`, same as before Bug 2 was ever found.

### Bug 3: post-delete "color-correction flash" (FIXED, `86b6cc9`) — user's fix was more precise than the first attempt

Separately from the animation's smoothness, the user noticed a distinct rough moment right after the
collapse finished: the alternating row-stripe colors visibly "correct" themselves. Root cause:
`_finish()` called `self._refresh_stats()`, which unconditionally called
`self._populate_history(sessions, duration)` — a full teardown (`deleteLater()` on every remaining
row) and rebuild (fresh `_HistoryRow` + `set_colors`, 5 `setStyleSheet` calls each) of every
surviving row, even though only one row was ever removed.

**First fix attempt (wrong, per the user's own correction):** added a `rebuild_history: bool` flag to
`_refresh_stats` and had the delete path skip the history rebuild entirely, reasoning "only one row
gets popped, only the last row loses its color pairing." This is wrong for a scrollable,
multi-page list: a row above the deleted one, anywhere in a long scrolled list (not just the visible
bottom), shifts into an index it didn't have before, flipping its intended stripe parity — skipping
recolor entirely produces back-to-back same-color rows wherever a delete happens away from the very
end of the full list. The user caught this immediately after testing with 30+ injected sessions and
scrolling to various positions before deleting.

**What actually shipped:** kept the `rebuild_history` flag (skips the wasteful full
`_populate_history`/`_apply_bar_colors` rebuild), but added a targeted, cheap fix instead of "skip
entirely": a new `_HistoryRow.restripe(index, theme)` method that re-applies ONLY the 3 index-
dependent background stylesheets (the row itself, its hover overlay, its confirm panel) — skipping
the theme-only trash-icon-reload check and confirm-label restyle that `set_colors` also does but
which never depend on row index. `_on_history_delete_confirmed` captures the deleted row's index
before removing it from `self._history_rows`, then walks every surviving row from that index onward
(NOT just the last row) and calls `restripe` with its new position. This is correct regardless of
scroll position or where in the list the delete happens, and touches only the rows that actually
need it.

### Still open: no viewport row-quantization on the History tab's QScrollArea (deferred, see TODO.md)

While testing Bug 2/3 with a long (30+ row) injected-session list, the user identified a fourth,
more fundamental issue, independent of the animation entirely: `_history_scroll`
(`QScrollArea`, `book_detail_panel.py`) is added via `outer.addWidget(self._history_scroll,
stretch=1)` — its viewport height is whatever space is left over in the fixed-size Book Detail
Panel, with NO relationship to `_HistoryRow.ROW_H`. Every other scrollable list/grid in this app —
`ChapterList` (`ROW_HEIGHT`/`VISIBLE_ROWS`, `_h_overhead` measured live after `show()`, `setFixedHeight`
quantized to whole rows), `ExcludedBooksPopup` (same pattern, `frameWidth()*2` overhead), and
`library.py`'s grid views (remainder-into-top-margin variant, since its `QListView` viewport is
layout-driven by an actually-resizable window) — deliberately quantizes its visible area to an exact
multiple of its row height, specifically so scrolling always lands on a clean row boundary rather
than cutting a row at an arbitrary sub-row pixel offset. History tab never got this treatment, and
the user's live testing showed exactly the symptom you'd expect from its absence: scrolling made rows
appear to "shift" rather than landing cleanly.

An attempt to fix this the same session (mirroring `ChapterList`'s exact idiom — a
`_HISTORY_VISIBLE_ROWS` constant, one-time `overhead = scroll.height() - scroll.viewport().height()`
measured via `showEvent` + `QTimer.singleShot(0, ...)`, then `scroll.setFixedHeight(rows * ROW_H +
overhead)`) was tried and **reverted live without being diagnosed** — per the user, "this didn't work
at all," and it additionally pushed the "Delete listening history" button (which must stay clamped
to the bottom of the tab) out of its correct position. Not investigated further before reverting,
since the user separately noted upcoming, unrelated work on a tags gutter above the History tab will
itself change this tab's available vertical space — re-tuning a fixed row count now would likely need
redoing once that lands. Deferred; see TODO.md. **Do not re-attempt the animation-smoothness tuning
(Bug 2's remaining "pauses near the end" report, still present but "bearable") until the viewport
quantization is settled** — per the user, it doesn't make sense to keep polishing an animation
running inside a viewport that itself doesn't have stable row boundaries yet.

A throwaway script (`/tmp/.../scratchpad/inject_fake_sessions.py`, not part of the repo) was used to
inject 30 synthetic `listening_sessions` rows for "The Tunnel" directly into the live `library.db`
via `LibraryDB.write_session(...)`, to get a real long/scrollable list for testing without needing 30
real listening sessions. These rows are still in the live DB as of this writing.

---

## Grid-mode geometry, final pass: 3-per-row alignment, and the 2-per-row whole-system solve (2026-07-10, later sessions)

Closes out the multi-session grid-view-mode geometry work (Square, List, 3-per-row, 2-per-row all
now have clean scroll boundaries with no drift and no stray gaps). This entry covers the two
hardest remaining modes, both of which took several real wrong turns before landing — recorded in
full because the wrong turns are exactly the trap a future pass would fall into again.

### 3-per-row: aligning to Square, and why the "obvious" full-symmetry fix made it WORSE

Goal: 3-per-row and Square are horizontally identical (3 columns, same left/right margin shape) —
they only ever needed to differ in row height. But 3-per-row's cell was still `96×146` with
margins `(4, 2, 0, 2)` while Square had already been fixed to `95×95` / `(4, 0, 0, 4)` in an
earlier session — so covers/gaps visibly shifted 1px right when toggling `3`↔`4`.

**Width fix (clean, no drama):** `w: 96→95`, matching Square exactly. Confirmed live: toggling
`3`/`4` now aligns pixel-for-pixel.

**Margin fix: tried the "obviously correct" symmetric copy TWICE, reverted both times.** The
naive move — copy Square's `(4, 0, 0, 4)` margin shape onto 3-per-row too, since it's the "more
correct" boundary-margin shape (same reasoning that fixed Square's own first/last-row asymmetry)
— was tried as (a) a plain remainder-into-top-margin push (mirroring Square's own
`_apply_view_mode` fix verbatim) and (b) a top/bottom SPLIT of the remainder. **Both reverted
live**, both times producing the same ~50px gap under the toolbar. Root cause: Square's fix works
because its `viewport_h % cell_h` remainder is tiny (2-3px, invisible as a margin). 3-per-row's
`cell_h=146` only fits 3 rows with a MUCH larger remainder (~40-57px depending on the exact
number) — pushing that entire remainder into a margin (or splitting it) is glaringly visible as
"one big empty gap," not "boundary correctness." **Lesson: the Square-mode remainder-margin
pattern is only invisible-safe when the remainder is small relative to cell_h — do not
mechanically reapply it to a mode with a much taller row without checking the actual remainder
size first.**

**What actually shipped:** `_GRID_MARGINS["3 per row"] = (4, 0, 0, 4)` (the symmetric shape DOES
stay — this part was right) — but the vertical START position is corrected with a flat,
eyeballed `setViewportMargins(0, 2, 0, 0)` in `_apply_view_mode` (2px, not a computed remainder),
matching the exact "flat push, not math" idiom 2-per-row's original 9px fix already established.
Cell height (`146`) was deliberately left un-clipped — 3-per-row keeps its partial 4th row
visible (the same "3 rows fully visible, 4th partially cut" look it always had); the user
explicitly chose this over letting the grid try to fit tighter, since a taller-row mode can never
fit a clean 2-row-style whole-number-of-rows anyway.

### 2-per-row: the second growth attempt collided a title into the next cover, then a from-scratch whole-system solve fixed it

Follow-on to the 2026-07-10 Session 1 cover enlargement below (118×180, first pass). The user
tried to push further — widen the cover more to fill remaining whitespace — with a **live,
uncommitted experiment that grew the cover to 130×198 without touching cell_h**. This is the key
mistake this whole saga hinges on: **the cover-rect code in `_paint_two_per_row` is completely
independent of `cell_h`** — it draws at a fixed size from `cover_y = r.y()` regardless of how
tall the cell is. So growing the cover this way didn't grow the row — it just ate into whatever
trailing space existed below the author line. Confirmed live via screenshot: the "P" in a book's
title started visibly overlapping/penetrating the NEXT row's cover. Separately, in the same
experimental state, the top viewport push (still the old flat 9px) made the covers start ~7px
lower than the scrollbar track's own top — a real, separate misalignment bug, visible once you
line up two screenshots.

**Multiple false starts trying to fix this incrementally, before stepping back:**
1. Tried shrinking `cell_h` by 5px in isolation ("get rid of the space under the author") without
   touching the cover — this DID reclaim trailing space correctly (confirmed: user could see the
   author line moving relative to the next cover), but doing single-variable nudges one at a time
   against a codebase where 5 separate locations (`ITEM_DIMENSIONS`, `_TWO_PER_ROW_LEFT_MARGIN`,
   the hardcoded literals in `_paint_two_per_row`, `_cover_rect`, `cover_cell_size`) all have to
   move together kept producing results that didn't converge on what the user actually wanted.
2. A `text_w = cover_w - 14` line was misread by the user as controlling vertical spacing ("the
   14px from the top") — it doesn't; it only bounds where the marquee-scroll text elides, with no
   effect on layout position. Wasted a round confirming "changing it does nothing" before the
   actual misunderstanding (w, not h) was caught.
3. The assistant made an explicit process error mid-session: told the user "these changes are
   made over the current version" (agreeing to build ON TOP of the 130×198 experiment), the user
   said "alright, stash [it]" (meaning: preserve this as a checkpoint, still building on it after),
   and the assistant then asked whether to POP the stash it had just been told to keep — a direct
   contradiction caught immediately by the user. **Lesson: when a user stashes something as a
   checkpoint mid-task, that is not the same as abandoning it — don't ask to reverse a stash you
   were never asked to create as a rollback point.**

**What broke the loop: solving the FULL system at once instead of one variable at a time.** Given
real, live-measured numbers this time (not guessed font metrics) — `title_h + author_h ≈ 34px`
measured from an actual live trailing-gap observation (13px trailing gap at a known `cell_h`),
cover aspect ratio `118/180 ≈ 0.6556` — the assistant solved simultaneously for: (a) cover as
large as possible on the same AR, (b) a real (not zero, not 13px) trailing gap after the author
line, (c) a near-flush top gutter matching Square's own ~2-3px (not the old 9px), (d) an EXACT
2-row fit with zero leftover for a 3rd-row sliver. The equation `2×cell_h + top_push = 477`
(window height minus chrome) combined with the trailing-gap target converged on: cover
`128×195`, `cell_h=237`, top push `3px` (down from 9px), margins `_TWO_PER_ROW_LEFT_MARGIN =
(9, 8)` (absorbing the cover's width growth into the outer margins while keeping the proven 16px
middle gap unchanged). `2×237+3 = 477` exactly — no sliver, and Square-like flush top gap, in one
consistent change instead of another round of guess-and-check.

**Final hand-tuning, done live by the user directly (not further iterated blind):** `text_w`
(`cover_w - 14` → `cover_w - 2`), `text_y`'s two gap offsets (`+2`/`+2` → final `+1`/`+0`, plus a
further live author-line nudge), all confirmed against both the running app and a Photopea
mockup. The resulting trailing-gap-after-author value is intentionally NOT restated as an exact
px figure in code comments, since it was hand-tuned past the point the arithmetic model tracks —
comments instead say "confirmed live, do not recompute against fresh arithmetic."

**Deliberately NOT pursued:** the user confirmed in Photopea that 2-per-row's top edge sits 1px
lower than Square's, and explicitly declined to chase it — "that would break the viewport." This
is accepted, permanent, cosmetic-only debt, not a bug to revisit.

**Final follow-up (same day):** `_TWO_PER_ROW_LEFT_MARGIN` was `(9, 8)` (16px middle gap) after
the whole-system solve above — confirmed live as reading "too tight in the middle relative to
the outer edges." One more nudge, shifting 2px from middle to outer: `(11, 6)` — outer=11px each,
middle=12px, close to visually even. Total per-column slack (`outer + middle_half = 17`, fixed by
`cover_w=128`/`cell_w=145`) is unchanged; only how it's split moved. Declared done — "Thing of
beauty" — after this change. If revisiting 2-per-row's margins in the future, `(11, 6)` is the
final value, not `(9, 8)`.

**Commits:** `ef4b826` (3-per-row width-only alignment), `352b72f` (3-per-row margins + 2px
push), `f0c0f62` (2-per-row whole-system solve), `3e929b4` (2-per-row margin final nudge).

---

## 2-per-row cover enlargement: column-aware margins, a frameWidth collapse, and an eyeballed viewport push (2026-07-10 Session 1)

Follow-on to the Square-mode geometry saga (below), applied to 2-per-row: grow the cover to use
more of the available vertical space, then redistribute the freed horizontal space so the outer
margins are wider than the gap between the two columns. Commit `d74ebee`.

### Why a uniform per-cell margin couldn't work here

For any two adjacent cells with the same left/right margin `L`/`R` (as every other grid mode in
this codebase uses), the visual gap between them is `right_of_left_cell + left_of_right_cell =
R + L`. If margins are symmetric (`L == R`, the normal case), the middle gap is always `2L` —
exactly double the outer margin, structurally, for any `L`. The user wanted a middle gap (16px)
*smaller* than the outer margins, which a symmetric uniform margin can never produce. Fix:
`BookDelegate._TWO_PER_ROW_LEFT_MARGIN = (19, 8)` — column 0 gets left=19/right=8, column 1 gets
left=8/right=19 (both sum to cell_w=145; the shared middle gap is `8+8=16`, the two outer edges
are each `19`). `index.row() % 2` derives the visual column from the flat `BookModel` list index
(IconMode wraps a `QAbstractListModel` visually — same reasoning already used for keyboard-nav
column math elsewhere in `library.py`). `_cover_rect()` and `cover_cell_size()` were updated to
accept/use the column too, so every cover-rect consumer (`_time_label_rect`, the overlay hit-test,
the idle preloader's sized-cache key) stays in lockstep — same discipline as `_GRID_MARGINS`.

### The exact-fit trap: `cell_w=146` collapsed the grid to 1 column

First attempt sized the cell so `2 * cell_w` landed EXACTLY on the nominal 292px viewport width
(146×2=292, zero slack). Confirmed live: this collapsed IconMode to a single column instead of
two. Cause: `QListView`'s default `frameWidth()` is 1px, taken off both sides of the viewport
(2px total), so the real usable width is 290, not 292 — a cell size with zero slack against the
wrong (nominal, not frame-adjusted) width leaves Qt no room and it silently drops a column. Fixed
by using `cell_w=145` (2×145=290, the frame-adjusted width) and absorbing the 1px difference into
the outer margins (20→19 each) rather than the middle gap, which stays exactly 16px as planned.
**Lesson for any future fixed-width IconMode sizing in this app: budget against
`viewport().width()` at runtime, or at minimum subtract `2 * view.frameWidth()` from the nominal
window width before dividing into columns — don't assume the full nominal width is usable.**

### Vertical sliver + the eyeballed 9px push

Same symptom Square mode hit originally: a sliver of a third row visible at the bottom, caused by
an asymmetric cell margin (top=8, bottom=0) leaving the true last row's bottom margin at 0 instead
of a real gap. Fixed with the same "boundary-margin swap" pattern as Square (top=0, bottom=8) —
the mid-list row-to-row gap is unaffected (`bottom + top` is 8 either way), only the unpaired
first/last row's margin changes.

After that, the user asked to shrink the viewport a further 9px so the menu-to-grid gap grows to
match — **explicitly not as a precision request**. This session's own precise `cell_h` math (based
on a live-measured "469px available" figure) had already been superseded once the margins changed,
and the user's exact words were that "your precise calculations are wrong too anyway" and that
they were eyeballing it. Implemented as a flat, undecorated `setViewportMargins(0, 9, 0, 0)` for
`"2 per row"` in `_apply_view_mode`, with a code comment explicitly noting it is NOT derived from
`cell_h`/viewport arithmetic. Confirmed live to fix clean scroll-boundary snapping (mirrors why
Square mode's `remainder`-based margin exists — a viewport height that isn't a multiple of
`cell_h` makes `QScrollBar.maximum()` land off a row boundary — but here the fix is a flat eyeballed
constant rather than a computed remainder, because the user explicitly asked for a nudge, not a
recalculation).

**Deferred by the user ("Later"):** even after all of the above, 2-per-row still doesn't fully use
the available whitespace — cell size can likely grow further and the gaps can tighten more. No
new target number was given. Do NOT reuse this session's 469px vertical-space figure as a baseline
for that follow-up — it was measured before the 9px viewport push existed and is now stale; ask
for a fresh live measurement first.

---

## Library Tab-clamp root cause, and the Square-mode scroll/geometry saga (2026-07-09 Session 3)

Two unrelated pieces of work, documented together because they landed in the same session.

### 1. Library Tab toggle wasn't actually clamping — QListView eats Tab before keyPressEvent

**Symptom (carried over from Session 2):** pressing Tab from the book list took 7+ presses to
reach the sort combo, walking through the transport bar, sidebar buttons, and both toolbar combos
before finally reaching `search_field`.

**Investigation:** added temporary `logging.DEBUG`-level focus-trace instrumentation (removed once
resolved) at three points: `LibraryPanel.showEvent` right after `_list_view.setFocus()` (plus a
`QTimer.singleShot(0, ...)` echo, to catch anything stealing focus back post-event-loop), both Tab
branches (`_list_key`, `_search_key`), and `MainWindow._handle_tab_escape`'s entry point. Had the
user reproduce the bug live with `FABULOR_LOG_LEVEL=DEBUG python main.py` and pulled the real log.

**What the trace showed:** focus WAS genuinely on `QListView` on the very first Tab press (ruling
out "nothing focuses the list on open" — `showEvent`'s `setFocus()` call was working correctly).
But there was not a single `[_list_key Tab]` log line anywhere in the trace — only
`_handle_tab_escape` ever saw the Tab keypresses, correctly deferred (`panel == "library" → return
False`), and then Qt's native focus-chain walk took over (confirmed by the sequence of focused
widgets in the trace: `QListView → ShimmerButton(speed_btn) → HoverButton(prev_btn) →
RightClickButton(rewind_btn) → ...` — the entire main-window transport bar and sidebar, in
creation order).

**Root cause:** `QAbstractItemView` (`QListView`'s base class) overrides `event()` and intercepts
`QEvent.KeyPress` for `Key_Tab`/`Key_Backtab` specifically, routing them directly into
`focusNextPrevChild()` — Qt's native chain-walk — *before* dispatch ever reaches `keyPressEvent()`.
This is genuinely different from every other key this app's `_list_key` handles (Up/Down/Enter/
Space/Left/Right): none of those are special-cased by Qt at the `event()` level, so they all reach
`keyPressEvent` normally. The existing `_list_key` Tab branch was silently dead code the whole
time — not from a logic bug, but because the key never arrived there at all.

**Fix (`2fa5a98`):** moved the Tab/Backtab interception from the `_list_view.keyPressEvent`
monkeypatch to a NEW `_list_view.event` monkeypatch (same instance-monkeypatch idiom already used
elsewhere in this file), filtered strictly to `e.type() == QEvent.Type.KeyPress and e.key() in
(Qt.Key.Key_Tab, Qt.Key.Key_Backtab)` — every other event, including every other key, is passed
through to the original `event()` unchanged, so nothing else's behavior could regress.

**Verification:** a second focus-trace, post-fix, showed clean `QListView ↔ QLineEdit`
alternation on every Tab press, zero stray widgets in between, across both view modes tested live.

---

### 2. Square mode: autoscroll, wheel-scroll, and true-square-cover — three real fixes and one
### reverted regression, with a lot of wrong turns along the way worth recording precisely

User reported, testing Square mode specifically: hovering near the top/bottom edge auto-scrolled
without any click; keyboard nav visibly "auto-corrected" after landing on a partial row (jarring);
and separately, a hard constraint that vertical and horizontal inter-cover gaps must be equal
("a true + between every pair of adjacent covers"), that the top toolbar's position can't move,
and that cell size/margins otherwise have some flexibility.

#### 2a. The measured baseline (do not re-derive from scratch — these are live-measured, confirmed
multiple times across the session)

- Window: fixed `300×564` (title bar 32px → `LibraryPanel` height 532px).
- `top_bar_widget`: 49px tall (`13px` top margin + `30px` tallest child + `6px` bottom margin,
  `QHBoxLayout` contentsMargins `(3, 13, 3, 6)`).
- `main_layout` spacing (top bar → list): 6px (Qt default, no explicit override).
- **`_list_view` viewport: 292×477px** — this is the real, live-measured available grid area
  (300px window − 8px scrollbar gutter wide, 564 − 32 title bar − 49 top bar − 6 spacing tall).
  Confirmed via a real `_open_library_flow()` + `switch_to_square()` probe reading actual
  `viewport().size()`, not calculated from constants — and re-confirmed live by the user's own
  screenshots throughout the session.

#### 2b. Row-fit (cell height) — the one piece of geometry that was right the first time and never
reverted

At the original `96×96` cell, `477 / 96 = 4.97` → 4 full rows (384px) + a 5th cut at 93/96px
(3px short of a clean 5th row). At `96×95`: `5 × 95 = 475px`, fitting in 477px with 2px to spare.
This part of the fix landed before this session (documented already) and was never touched again.

#### 2c. Horizontal margin — one wrong formula caught before shipping, one correct formula found

**WRONG (caught, never shipped as final):** `cover_rect = QRect(r.x()+4, r.y()+2, r.width()-7,
r.height()-4)` — intended `left=4, right=3`. The bug: `gap_between_adjacent_covers = right_of_
cell_N + left_of_cell_N+1 = 3 + 4 = 7`, not 4. This came from conflating "how much total leftover
width exists across the whole row" (7px, at cell_w=96 vs. a since-reverted cell_w=95 idea) with
"what the actual gap between two tiled cells is" — those are different quantities and must be
modeled cell-by-cell (each cell's own left+right margin, tiled edge-to-edge), not as one shared
pool split however seems reasonable.

**CORRECT (shipped, held for the rest of the session):** `left=4, right=0`, cell_w unchanged at
96. `3 × 96 = 288` of the 292px viewport leaves exactly 4px of leftover, which with `right=0`
lands as: gap between cells = `0 + 4 = 4` (matches), AND the outer-right edge (viewport edge minus
the last cell's right-margin-adjusted edge) independently comes out to 4px too — no fractional
splitting, nothing left unaccounted for, verified by explicit sum: `4 + 288 + 0 = 292`.

#### 2d. The 94×94 (and 96×94) true-square-cell attempts — arithmetic passed, live check failed,
reverted — the key "don't trust arithmetic alone" lesson of the session

Given the constraints (5 rows, 4px gaps, some flexibility in top margin), several budgets were
solved on paper:
- `94×94` cell, gap=4: `5×94=470` tiled, `477-470=7` leftover, `bottom=4` (matches gap) leaves
  `top=3`. Horizontally: `3×94=282`, `292-282=10` leftover, `left=4` leaves `right=6`. Every
  number summed exactly to the viewport dimensions (`3+470+4=477`, `4+282+6=292`).
- This was implemented (`ITEM_DIMENSIONS["Square"] = {"w": 94, "h": 94}`, `_GRID_MARGINS["Square"]
  = (4, 3, 6, 4)`) and reported by the user as **visually wrong**: 10px gaps instead of 4, a 7px
  sliver at the bottom. The exact mechanism was never fully pinned down before it was reverted —
  the priority was restoring a known-good state over continuing to debug blind. Reverted to the
  `96×95`/`(4,2,0,2)` values from 2c/2b.
- **This is the moment worth remembering:** the arithmetic was internally consistent and summed
  correctly, and was STILL wrong once rendered. Whatever assumption fed the model (likely: an
  incorrect belief about how `_GRID_MARGINS`' four values compose with `ITEM_DIMENSIONS`' cell
  size across a full tiled row, or a stale cache/paint path not accounted for) was never isolated.
  Any future change to `ITEM_DIMENSIONS["Square"]` or `_GRID_MARGINS["Square"]` MUST be verified
  against the real running app before being treated as done — this is now written directly into
  both the `ITEM_DIMENSIONS` and `_GRID_MARGINS` code comments as a standing warning.

#### 2e. Autoscroll-on-hover — root-caused correctly, fixed, confirmed (`b4dd1f5`)

`QAbstractItemView.hasAutoScroll` defaults to `True` (16px `autoScrollMargin`), and — confirmed
live — fires from pure mouse hover position near the top/bottom viewport edge, no button held.
Nothing in this app's code called `startAutoScroll`/`doAutoScroll` explicitly; this is Qt's own
native drag-autoscroll machinery, apparently reachable from hover alone given `setMouseTracking
(True)` is already on for this list (needed for the existing hover-highlight/overlay features).
Fixed with a single `self._list_view.setAutoScroll(False)` call at construction. Confirmed live
by the user before being trusted as fixed.

#### 2f. Wheel scroll: fixed 3-row jump regardless of viewport row count — user found this
directly, not the model

The user directly observed (unprompted) that every wheel flick scrolled exactly 3 rows,
regardless of view mode: correct-*looking* for 1-per-row (which happens to show 3 rows on screen)
purely by coincidence, wrong for Square (5 rows visible) and List (~17 rows visible — the user
also confirmed List was affected, just less obviously so with small 28px rows). Root cause:
`QApplication.wheelScrollLines()` — a GLOBAL Qt setting, confirmed `=3` on this system — multiplied
by `QScrollBar.singleStep()` (which was already correctly `=cell_h` per row height). `3 × 95 =
285px` per flick, a fixed jump with no relationship to how many rows actually fit the viewport.

**Fix (`b4dd1f5`):** intercepted `_list_view.wheelEvent` (instance monkeypatch), computing
`rows_per_screen = viewport_h // cell_h` fresh per event (reads `ITEM_DIMENSIONS[view_mode]`, so
it's correct per-mode automatically) and scrolling the vertical scrollbar by exactly
`rows_per_screen * cell_h` per flick — a fresh, fully-new screen of rows every scroll, always
landing on a row boundary during normal (non-boundary) scrolling. Confirmed live and never
reverted — this is the one part of the "nudge" complex that survived the whole session intact.

#### 2g. `pageStep`: a fully wrong theory, built twice, zero live effect both times — a real
methodology lesson about headless verification

Before wheelScrollLines (2f) was found, the model theorized the "3-row jump" was really a
`pageStep`-alignment problem (`pageStep` auto-set by Qt to the raw viewport height, 477, not a
multiple of `cell_h`). Two implementation attempts, both dead ends:

- **First attempt:** hooked `verticalScrollBar().rangeChanged` to re-snap `pageStep` to a clean
  multiple of `cell_h`. Verified via an offscreen probe that this correctly changed `pageStep` to
  475 in isolation — but had **zero effect in the real running app** (user tested, unchanged). Root
  cause of the non-effect: `QAbstractItemView.updateGeometries()` calls
  `verticalScrollBar().setPageStep(...)` **directly**, not via `setRange()` — confirmed by testing
  that `QScrollBar.setPageStep()` alone does NOT emit `rangeChanged` (`sb.setRange(0,1000)` then
  `sb.setPageStep(50)` — zero `rangeChanged` emissions). The hook was listening for a signal Qt
  never fires for this code path.
- **Second attempt:** switched to overriding `updateGeometries()` itself (instance monkeypatch),
  confirmed via trace that it DID intercept Qt's internal calls and DID successfully change
  `pageStep` (475, held through a 1.5s settle window in an offscreen probe) — and STILL had zero
  observable effect when the user tested the real app.
- **The theory itself was never right.** `pageStep` only governs PageUp/PageDown and clicking in
  the scrollbar's track — not wheel scroll (`wheelScrollLines × singleStep`, see 2f) and not
  `QAbstractItemView`'s native autoscroll (`hasAutoScroll`/`autoScrollMargin`, see 2e). All
  `pageStep`-related code (`_fix_page_step`, the `updateGeometries` override, the `rangeChanged`
  connection) was fully removed once the real mechanisms were found — none of it does anything in
  the shipped code.
- **This is the SECOND time this session** (after 2d) that an offscreen/headless check reported
  success while the live app disagreed. Per the existing CLAUDE.md rule about headless
  verification for settings-panel visual bugs, this session extends that lesson to scroll/focus
  mechanics generally: an offscreen probe reading back a Qt property's value is not proof the
  property is actually driving the behavior in question in the real, live, running app.

#### 2h. Boundary drift ("2px nudge") — a real bug, a fix that worked for one input path, a worse
regression discovered, and a full revert — currently OPEN

**Confirmed real** via user-provided red-line screenshot overlays: two states (library just-opened
vs. scrolled by one row via arrow keys) superimposed at 50% opacity, with a red reference line
drawn at a fixed position. Same-state overlay (control) showed crisp, single-pixel gutter lines;
cross-state overlay showed visibly muddy/doubled lines — a genuine ~2px misalignment, not
perception. Further screenshots (scrollbar-at-top vs. scrollbar-at-bottom, same red line) showed
the drift symmetrically at both the top and bottom boundaries, same content, same ~2px magnitude.

**Root cause:** `QScrollBar.setValue()` silently clamps any out-of-range value to
`[minimum, maximum]`. `maximum()` (`= content_height − viewport_height`) has no reason to be a
multiple of `cell_h` — confirmed: `11493 % 95 = 93`. So scrolling (or `scrollTo()`-based keyboard
nav) past either end lands the scrollbar on this arbitrary, non-row-aligned boundary value instead
of a clean row-aligned position.

**Fix attempt (reverted, see below):** added `_snap_scroll_to_row(target, cell_h)`, called from
both the wheel handler (before `setValue`, where the overshoot is directly known) and from
`_flash_keyboard_selection` (after `scrollTo()`, where the overshoot information is already gone
— Qt clamps before returning). The keyboard-nav call site initially had a real logic bug: it
checked `sb.value() > sb.maximum()`, which can **never** be true post-`scrollTo()` (Qt already
clamped), so the snap silently never fired for keyboard nav even though the helper itself was
correct — fixed to check `sb.value() == sb.maximum()` instead (checking for "landed exactly on
the boundary", not "overshot past it", since the overshoot itself isn't observable after the fact).
Wheel-scroll boundary drift confirmed fixed by the user at this point.

**The regression, found by the user, called "more important" than the original drift:** snapping
an overshoot to the nearest row-aligned value **below** `maximum()` means the scrollbar can no
longer reach the TRUE bottom of the list at all — the last row (or several rows, depending on the
remainder size) became permanently unreachable via wheel scroll or arrow-key nav, needing a manual
scrollbar drag to see. Confirmed affecting all four grid/list modes except 1-per-row (which
happens not to trigger the boundary case as visibly). This is a straightforwardly worse bug than a
2px cosmetic nudge — content becoming unreachable is a real functional break.

**Reverted in full (`ca5b9d6`):** `_snap_scroll_to_row` deleted; the wheel handler now just calls
`sb.setValue(target)` directly, letting Qt's own native `[minimum, maximum]` clamp apply — the
exact same behavior `scrollTo()` already had unassisted. Reachability confirmed restored.

**Current state: the 2px boundary drift is back, unfixed, on both wheel and keyboard-nav paths.**
Affects Square, 3-per-row, and List; explicitly expected by the user to also affect 2-per-row once
that mode is worked on, since the underlying Qt scroll mechanics are shared across all grid/list
modes. **Any future fix attempt must not reintroduce a short-of-maximum() clamp** — reaching the
genuine top/bottom of the list always has to take priority over eliminating the cosmetic drift.
Next agreed step: instrument (not guess), verify every claim against the real running app, not an
offscreen probe (see 2d and 2g for why that specific shortcut has already failed twice this
session).

#### 2i. True-square cover (kept, `3275c24`) — the framing confusion that blocked progress longer
than the arithmetic did

Separately from the row-fit work (2b–2d): even after the `96×95` cell fix, the cover itself
rendered `92×91` — visibly not square, since `top=2/bottom=2` (on a 95-tall cell) gives `91` but
`left=4/right=0` (on a 96-wide cell) gives `92`.

The path to the eventual fix took several wrong framings, each corrected by the user directly
rather than found independently:
1. First attempt: bumped `right` 0→1 on the EXISTING 96-wide cell to shrink the cover to 91×91.
   This is internally correct for the cover's own squareness, but — not initially connected by the
   model — it also changes the inter-cover GAP (`right(1) + left(4) = 5`, not 4), because `right`
   is shared by every cell uniformly. The user caught the resulting 5px vertical gap live.
2. Model then incorrectly assumed the fix required making `left`/`right` different per COLUMN
   (first vs. last column), since a single shared margin can't square the cover without also
   changing the gap. The user repeatedly corrected this — the columns are NOT what needed to
   change; something else entirely.
3. The actual ask (confirmed only after several rounds of the user drawing red arrows on a
   screenshot pointing at the empty strip between the last column and the scrollbar, and then a
   short direct Q&A — "what is that space", "what's the total width of the container", "what's
   the blocker") was: shrink the CELL itself (not just the cover-within-an-unchanged-cell) by the
   same 1px, so the gap math (2c) is completely untouched, and the 3 freed pixels (1px × 3
   columns) fall out automatically into the window's own trailing gutter past the last column —
   no per-cell or per-column margin change needed at all.

**Final fix:** `ITEM_DIMENSIONS["Square"]["w"]`: 96→95 (matching the already-95 height — a true
95×95 CELL, not just a square cover carved from an unchanged cell). `_GRID_MARGINS["Square"]`
LEFT COMPLETELY UNCHANGED at `(4, 2, 0, 2)`. With `left=4, right=0` on a 95-wide cell:
`cover_w = 95 − 4 − 0 = 91`, matching `cover_h = 95 − 2 − 2 = 91` — square, confirmed live. Gap
between cells: `right(0) + left(4) = 4`, untouched. Trailing gutter: `3 × (96−95) = 3px` freed,
landing automatically past the last column since nothing else in the tiling changed — verified by
the user's own arithmetic (`4+91+4+91+4+91=285` of the `300px` window, `300−285=15px` gutter,
matching the live screenshot) after the model had been modeling the wrong container width (`292`,
the scrollbar-excluded viewport) instead of the full `300px` window the user was actually
measuring the gutter against.

**Process lesson for 2i specifically:** when a verbal geometry description isn't landing after
multiple attempts, a short, literal, concrete question ("what is X", "what's the blocker") unblocks
faster than proposing another guessed reformulation of the same wrong model. The user's own
direct-question approach here is what actually broke the loop, not further calculation from the
model's side.

---

## Library keyboard navigation: the focus-trap bug and what it revealed about `QComboBox` on this desktop (2026-07-09)

Three follow-up bugs surfaced by live-testing the new Library keyboard-nav feature
(`fe4f0f9`), each traced and fixed the same session. Recorded together since the second one
is the meatier root-cause writeup and the other two are quick context.

### 1. Sort/view-mode dropdown silently stranded keyboard focus

**Symptom:** clicking either toolbar dropdown (sort key, view mode) to make a selection left it
holding keyboard focus. Since arrows only drive book-list nav while `_list_view` has focus,
touching either dropdown once silently broke keyboard navigation with no recovery except
clicking the list again.

**Investigation (per the user's instruction to find the actual mechanism, not guess-and-patch):**
diffed the whole keyboard-nav commit against its parent. It only ever *added* focus machinery
(`_list_view.setFocusPolicy(Qt.StrongFocus)`, three `setFocus()` calls) — nothing touches
`sort_combo`/`style_combo`, and neither ever had an explicit focus policy before. This is **not
a regression** in the sense of something being removed: a plain `QComboBox` has always kept
keyboard focus on itself after its popup closes (any means — value picked, click-away, Escape),
which was harmless before arrow keys drove anything in Library. The keyboard-nav work made
`_list_view`'s focus state load-bearing for the first time; nothing was ever added to reclaim it.

Also checked (and ruled out) whether the user's *separately* reported "arrows don't cycle the
open popup's own options" was a real second bug: no event filter anywhere in the codebase
touches either combo box or its popup, and `MainWindow`'s one app-wide `eventFilter` only
observes `KeyPress` to reset an idle-preload timer — never consumes it, never inspects the key.
A native combo popup is a self-contained Qt popup with its own internal event loop; nothing in
this app could plausibly interfere with it. Read this as a likely misdiagnosis of bug #1's
symptom (testing arrows after the popup had already closed) rather than a real second bug — no
fix attempted for it, and the user's live testing after fix #1 landed didn't surface it again.

**Fix (`f6388d2`):** `hidePopup()` is Qt's own hook for "the popup just closed, regardless of
how." Overridden via the same instance-monkeypatch idiom the file already uses for
`search_field.keyPressEvent` — call the original, then `self._list_view.setFocus()`. Applied to
both `sort_combo` and `style_combo`.

### 2. `QComboBox` popup hover/selection and the down-arrow are both silently broken by QSS, on this desktop

The user then reported the ACTUAL visual bug being chased the whole time: the popup's hover
highlight was invisible — thin dark lines appeared above/below the hovered row instead of a
themed background fill — and a light square/rectangle sat where the dropdown arrow should be.
The user noted this specific area (Library dropdown popup styling) had already been attempted
and abandoned roughly 3 months earlier, undocumented at the time (possibly Gemini, possibly an
earlier Claude Code session) — confirmed nothing about it exists anywhere in CLAUDE.md,
NOTES.md, SESSION.md, TODO.md, or auto-memory before this session.

**First attempt (wrong assumption, corrected same session):** `themes.py`'s
`get_library_stylesheet` had `QComboBox QAbstractItemView` styled (background/border — visibly
working, matches the theme) but **no `::item:hover`/`::item:selected` rule at all**, and no
scoped scrollbar rule for the popup's internal viewport. Added both, plus `outline: none` on
`::item` (Fusion's per-item focus rectangle survives regardless of background color unless the
item itself, not just the view, suppresses it) — live-tested: **zero visible difference**, not
even a partial change.

**Diagnosis, done properly instead of guessing again:** since "zero difference" rules out a
subtlety/color problem, swapped the hover/selected rule to a glaring, impossible-to-miss `red`
and asked the user to check live. Still no red — conclusively proving the QSS rule was not
reaching the popup's paint AT ALL on this system, not a matter of picking a better color.

Cross-checked the mechanism in isolation (outside the running app, a bare `QComboBox` built
fresh in a throwaway script) to rule out anything app-specific (timing, another stylesheet,
an event filter):
- `combo.view()` IS reachable in the ancestor widget's object tree (`findChildren` finds it) —
  so this isn't a total cascade failure; base-level properties (background, border) genuinely
  do inherit, matching what was visibly working.
- `view().hasMouseTracking()` was `True` — ruled out the mouse-tracking-disabled theory.
- Sent a synthetic `QMouseEvent(MouseMove)` directly to the popup viewport, and separately
  called `view().setCurrentIndex(...)` (Qt's own native "current item" state, a much stronger
  and more deterministic signal than hover) — grabbed screenshots of the live popup in both
  cases. **Neither showed any highlight at all**, confirming the failure is unconditional, not
  hover-specific.
- Environment: `QApplication.style().objectName() == "fusion"`, `platformName() == "wayland"`,
  `QT_QPA_PLATFORMTHEME` unset, `XDG_CURRENT_DESKTOP=KDE`. So this is Qt's OWN Fusion style, not
  a KDE/Plasma platform-theme plugin overriding things — yet the pseudo-state paint still doesn't
  apply. Root mechanism not fully pinned beyond "confirmed real and unconditional on this
  desktop" — not worth chasing further given a working alternative existed.

**Fix (`3e8c241`):** stopped relying on native pseudo-state painting for popup items entirely.
Added `_ComboItemDelegate(QStyledItemDelegate)`, installed via
`combo.view().setItemDelegate(...)`, that paints the row background for
`State_MouseOver`/`State_Selected` directly. Reads `LibraryPanel._current_theme` live at paint
time (same theme dict `BookDelegate` uses), so no separate theme-change plumbing was needed —
`update_progress_bar_theme` already keeps it fresh. Confirmed to have no measurable performance
cost: it only runs while that specific popup is open (a small, separate `QListView` from the
book grid), never touches `LibraryPanel`'s slide animation or `BookDelegate`'s own paint path.

**The down-arrow turned out to be the same root cause.** `QComboBox::down-arrow`'s `image: none`
+ border-triangle QSS trick was ALSO being ignored — the native style painted its own arrow
glyph regardless, rendering as a plain light square (reproduced in the same kind of isolated
screenshot test). Fix (`8515605`): `_ThemedComboBox(QComboBox)` overrides `paintEvent` — calls
`super().paintEvent()` first (background/border/text still paint correctly via the style; only
the item-popup and arrow pseudo-states are broken), then paints a themed triangle over just the
arrow's `subControlRect(SC_ComboBoxArrow)`.

**Regression caught and fixed in the same pass:** the first arrow-fix draft filled the ENTIRE
arrow rect edge-to-edge before drawing the triangle. `subControlRect(SC_ComboBoxArrow)` spans
the full control height, including the curved pixels of the top-right/bottom-right rounded
corners — a flat fill there squares them off. Live screenshot from the user caught this
immediately ("top right and bottom right radius of the box seem broken"). Fixed by insetting the
fill vertically (`corner_clearance = 6`) so it only covers the flat middle section, never
touching the border-radius curve. Re-verified via an isolated 4×-scaled screenshot before asking
the user to re-check live.

Both `sort_combo` and `style_combo` are now constructed as `_ThemedComboBox(self)` instead of
plain `QComboBox()`; `_ComboItemDelegate` is installed on each one's `view()` right after
construction, alongside the `hidePopup()` focus-release override from bug #1.

### 3. `open_book_detail` re-triggered its slide-in animation on every repeat request, and could be hijacked onto a different book

**Symptom (reported after 1 & 2 were fixed):** Alt+Enter on the currently-open book re-slid the
Book Detail Panel every time it was pressed, even though it was already open.

**Root cause:** `open_book_detail` (`panels.py`) called `_start_book_detail_entry()`
unconditionally — that method always moves the panel off-screen right, THEN slides it back to
`x=0`, with no check for "is it already there." Every Alt+Enter (or any other call to
`open_book_detail`) yanked it out and back in.

**A narrower first fix was rejected as insufficient by the user, correctly.** The first attempt
only skipped the re-slide when the SAME book path was already showing — but the user pointed
out a real hack this still allowed: right-click a book to open its detail panel, then (while it's
open) arrow-navigate to a DIFFERENT book in the still-visible list behind it, then press
Alt+Enter. Since the path comparison would see a different `requested_path`, it would have let
`load_book` swap the panel onto the new book's data while already open — the panel never
stacks (still only ever one at a time), but a currently-open detail panel silently retargeting
itself to a different book was exactly the class of bug being fixed, just from a different
angle.

**Actual fix (`c521c39`):** `open_book_detail` now drops the ENTIRE request — no `load_book`
call, no animation — whenever `book_detail_panel.isVisible()` is already `True`, regardless of
which book. The user must close the panel via an existing close path first. Checked all three
callers (`app.py`'s library right-click/Alt+Enter path, `stats_panel.py`'s row click,
`tag_manager`'s book click via `main_window_builders.py`) — none of them legitimately need to
retarget an already-open panel; each is "open detail for a book I clicked from wherever I'm
browsing," not a same-panel tab-switch flow. Confirmed this doesn't conflict with the documented
`open_book_detail` UNGATED note in CLAUDE.md — that note is about the *cross-panel*
(`is_overlay_open_or_committed`) exclusion gate, an orthogonal concern; this new guard is
book-detail-vs-book-detail only.

---

## Near-zero saved positions show spurious library progress: config↔DB drift + open-without-play position creep (2026-07-06)

**Symptom:** "2666 (Unabridged)" showed a progress bar / percentage in the library despite reading
`0:00:00` and `0.0%` in both the player and the library card. The user expected books effectively
at the start not to count as "in progress."

**Immediate cause — `MIN_PROGRESS` is too coarse.** The library gate is `MIN_PROGRESS = 1.0`
(seconds, `library.py:54`). `books.progress` for 2666 was `1.3588` — over 1.0, so
`_resolve_playback` set `has_progress = True` (draws bar/%/elapsed, `library.py:1676`) and the
"Last Played" sort subset included it (`library.py:1135`). But `pos/dur = 1.3588/141340 ≈ 0.00001`
→ renders `0.0%` / `0:00:00`. So classification and display contradict each other. Bumping
`MIN_PROGRESS` (e.g. to 5s) hides the symptom but is NOT the fix — it just moves the threshold a
book's crept value has to clear.

**Why only 2666 showed it, when the config had many books at ~1.75–2.0.** Two independent position
stores, and they drift:
- **`books.progress` (DB)** — what the library grid reads.
- **`pos_{path}` (QSettings/config)** — what `_restore_position` reads to seek on load
  (`app.py:1601`).
The DB `progress` is only written from config **when that specific book is actually opened**
(`_restore_position`: `config_pos → db.update_progress → seek_async`, `app.py:1601-1613`). 2666 is
the user's `last_book`, restored every launch, so its crept config value reached the DB. The other
books had crept `pos_` values but hadn't been re-opened, so their DB `progress` stayed `0.0` and
they correctly showed no progress. **The bug is library-wide-latent:** each book surfaces spurious
progress the first time it's re-opened after creeping.

**Two misreads corrected mid-investigation, recorded so they aren't repeated:**
1. The cluster of config values `1.75 / 1.80 / 1.90 / 2.0 / 2.1` looked like a fixed +0.05/cycle
   climb toward EOF. It is NOT — those digits are the per-book **speed coefficients** interacting
   with the seek landing (user's correction), and that whole block of values lived under a **stale
   duplicate `[pos_]`-shaped section below `[speed_]`** in the config, not the live `[pos_]` group
   at line 56. The live values are smaller (0.04–0.42 range) and get **overwritten fresh** each
   open→close, not monotonically climbed. Confirmed by re-opening The Fawn/Kundera/Austerlitz/Soviet
   Milk: DB went to 0.4199 / 0.0407 / 0.0 / 0.0 and live config to 0.4199 / 0.0499 / 0 / 0 — below
   1.0, so they now correctly read 00:00:00 with no bar.
2. The real defect underneath: **a book opened and closed without genuine playback saves a small
   non-zero position instead of preserving 0.** `_save_current_progress` (`app.py:1294`) persists
   mpv's actual reported `time_pos`, and on the paused-embedded restore path a
   `_PAUSED_SEEK_UNDERSHOOT_COMP` (0.37, `player.py:670-671`) residual — scaled by speed — lands a
   few tenths of a second past 0 rather than exactly at the saved position. That residual is what
   gets saved. Same class as the already-fixed VT `+0.35` creep (see `_restore_position` comment
   `app.py:1607-1612`); it survived on the paused-embedded compensation path.

**Why this is deferred, not fixed now (user's call):** persisting the *logical* position
(`_seek_target`) instead of mpv's reported `time_pos` would fix the creep but is entangled with
other open mpv-playback issues (see the heavily-guarded MPV-seek / `_seek_target` invariants in
CLAUDE.md). Fixing it in isolation risks a can of worms. To be tackled together with the other mpv
problems as a set, not one-by-one. Already-poisoned config/DB values won't self-heal — a one-time
cleanup zeroing sub-threshold `pos_`/`progress` entries is a candidate when the source fix lands.

**RESOLVED 2026-07-13 (`9521ee4`, branch `fix/seek-drift-logical-position`) — the "source fix" this
entry anticipated.** The root cause named here (persisting/reading mpv's raw `time_pos` instead of
the logical position) is exactly what `_logical_pos` fixes — the getter now returns the logical
position, so `_save_current_progress` persists it, and the open-without-play creep no longer
accumulates. See the top-of-NOTES entry "Compounding seek drift fixed via `_logical_pos`".

**Cleanup done 2026-07-13** (same day, once the fix was merged and soak-tested) —
`tools/cleanup_poisoned_progress.py` (dry-run by default, `--apply` to write): zeroed 223 poisoned
`books.progress` DB rows and 224 poisoned `pos_{path}` QSettings keys (values in `(0, MIN_PROGRESS]`
— matches `ui/library.py`'s own gate exactly). DB backed up to
`library.db.pre-cleanup-<timestamp>.bak` before applying; re-ran the dry-run after to confirm 0
remaining in both stores. This closes the entry fully — no more outstanding follow-up.

---

## List-mode title/author spacing: one fix that stuck, three that were reverted, and why (2026-07-06)

`BookDelegate._paint_list_row` draws, per row, `[title (left-aligned)] … [author (right-aligned)] [time]`.
Two defects were chased across four rounds. Only the first was kept (`d37507c`); the rest were
reverted. This writeup exists so the next attempt does not re-walk the same three dead ends.

### The one fix that stuck (`d37507c`) — wrong measurement font

Every width in `_paint_list_row` was measured with `fm = option.fontMetrics` (the generic 11pt app
font), but title *draws* at 14px **bold** and author at 13px regular (`FONT_SIZES["List"]`, applied
via `_set_font` at draw time). The 11pt measurement under-reported title width by ~5-7px, so a
near-miss title was judged to fit, drawn un-elided, and overflowed into author's space — while a
title that overflowed by a *lot* elided correctly (the "near-miss fails, far-miss elides" signature,
confirmed by lengthening a failing title until it elided). Fixed by measuring each field with a
`QFontMetrics` built from `option.font` + that field's real `(size, bold)`. This is correct and
kept. It also removed a `>= ellipsis-width` tolerance band (which only existed to forgive the
wrong-font error) in favour of a strict `>` fit test, and shrank the `title_rect` clip margin +8 → +2.

### The core insight (the reason the next three attempts all failed)

**Rect-boundary padding cannot produce a constant glyph-to-glyph gap when one field is left-aligned
and the other is right-aligned within its own rect.** The visible gap between title's last glyph and
author's first glyph is:

```
gap = reserve + title_slack + author_rect_slack
```

- `reserve` — whatever fixed separation you build into the geometry (e.g. `TITLE_CM`).
- `title_slack` — title is **left-aligned**, so if the title text is shorter than its budget, the
  unused budget becomes empty space on its *right*. Content-dependent (varies per title).
- `author_rect_slack` — author is **right-aligned** flush to its rect's right edge, so if the author
  text is narrower than its rect, empty space opens on its *left*. Content-dependent (varies per
  author).

Both slack terms are per-book. So no amount of rect-edge tuning yields a constant *glyph* gap.
Measured for "The Riddle-Master of Hed" / "Patricia A. McKillip" (`option.rect.width()=300`):
title ends at x=144, author text starts at x=158 → **14px gap** = 6 (title slack) + 4 (reserve) +
4 (author rect slack), not the 4px the "structural" attempt assumed. **Any real fix must measure
actual drawn glyph extents and position relative to those, not relative to rect edges** — e.g.
anchor author's *left* edge (left-align it, or place its text start at a fixed offset past the
title's measured glyph end), rather than right-aligning it into a rect whose left edge is all the
geometry controls.

### The three reverted shapes, briefly

1. **Pad-only** (rejected before landing) — add a fixed `TITLE_SEP` pad to compensate the overflow.
   Rejected because it papers over the wrong-font root cause with a magic number calibrated to
   today's exact font/sizes; superseded by the measurement fix above.
2. **Symmetric `TITLE_CM` reserve at author→time** (`author_draw_w = author_w - TITLE_CM` at point of
   use) — gave author→time a real 4px gap, but the borrow branch's own `spare = max(0, title_max_lw
   - (title_text_w + TITLE_CM))` **double-counted** `TITLE_CM` against `title_avail = title_max_lw -
   TITLE_CM`, cancelling the title→author gap to ~0 for borrow/elided rows while leaving short rows
   fine → row-dependent collisions (9 of 18 `#elide` test rows). Reverted.
3. **Structural `mid` placement** (`author_left = title_right + TITLE_CM`, borrow spare no longer adds
   `TITLE_CM`) — fixed the double-count and made all 18 test rows show a clean ≥4px author→time gap in
   the *arithmetic*. But live it exposed the opposite-alignment slack problem above (the "structural"
   gap rendered as 7-14px, not 4, and varied per row), AND left the hover-invade path misaligned:
   `full_rect` (invade draw) still used `AVAILABLE - TITLE_CM` → right edge at the time column, 4px
   right of resting author's `author_right` → author visibly jumped 4px on hover. Reverted.

### Orthogonal instability found during the round-3 post-mortem (NOT caused by any of these rounds)

`_paint_list_row` reads `option.rect.width()` live, and the list view is configured
`setResizeMode(ResizeMode.Adjust)` + `ListMode` (`library.py` ~258-259), so a row's width tracks the
live **viewport** width rather than a fixed constant (`sizeHint` returns 290, viewport is ~300; Qt
stretches). If a paint occurs while the library panel is mid-slide-in or before the viewport settles,
`option.rect.width()` differs → `AVAILABLE` differs → `title_avail` differs → **the same title can
elide in one paint and not another**. This matched the reported "three near-identical resting-state
screenshots of the same row show different author x-positions / different title elision." The resting
geometry is otherwise a **pure function** of `(book, option.rect, option.font)` — it reads no
`_hover_pos`, no scroll/timer/leftover state — so `option.rect.width()` is the *only* non-constant
input. This affects **any** List-mode geometry that reads `option.rect.width()`, not just this
feature. Logged in DEBT_INVENTORY.md ("Stats / library UI"). A real spacing fix should either not
depend on live width, or the width must be made stable first.

## Library click-to-filter: three bugs worth remembering the shape of (2026-07-05)

Full feature narrative is in SESSION.md (2026-07-05, commits `5f637dc`..`a7271a5`). Three bugs from
that work are worth a standalone note because the *shape* of each is likely to recur elsewhere,
not just the specific line that was wrong.

**1. Partial removal of prototype code left dangling references that only failed at runtime.**
The segment-hit-test spike (`53fb087`) was built with three helper methods
(`_spike_update_hover_segment`, `_spike_recompute_hover_segment`, `_spike_draw_segment_highlight`)
whose only job was driving a throwaway underline. When removing them, the *definitions* were
deleted correctly, but two of their *call sites* — inside `_paint_one_per_row`'s and
`_draw_scrollable_field`'s scroll-drawing branches — were missed in that same pass, plus a third
call site in `_advance_scroll`. Because Python doesn't check attribute/method existence until the
line actually executes, this didn't surface as an import error or a crash on startup — it surfaced
as "the marquee scroll animation looks broken," reported by the user, because every scroll-tick
paint of a scrolling field was raising `AttributeError` and presumably being swallowed or degrading
silently somewhere in the paint/timer path. The fix was a `grep` sweep for the deleted names across
the whole file, not a re-read of "the block I edited." **Lesson: when deleting a method, grep the
method name file-wide before considering the removal done — a call site outside the section you
were looking at will not announce itself as a syntax error, and may not announce itself as an error
at all if the failure mode is a caught/logged exception in a hot path like paint() or a timer tick.**

**2. A UI-visible string comparison silently diverged from what a length-limited widget actually
stores.** The toggle-off feature (`7ba2753`) compares a click's target string against
`search_field.text()` to decide whether to clear or overwrite. `search_field` has
`setMaxLength(26)` (set once at construction, for display-width reasons unrelated to this
feature). A grabbed author credit longer than 26 chars (`"Edith Grossman - translator"`, 27 chars)
gets silently truncated by Qt when written via `setText`/`set_search` — but the code computing the
comparison target had no reason to know that, since `target` is built from the raw click value, not
read back from the widget. First click: sets fine (nobody compares yet). Second click on the same
segment: `target` (27 chars) != `search_field.text()` (26 chars, truncated) → treated as a
different value → re-sets instead of clearing. The bug was invisible in code review because both
sides of the `==` look reasonable in isolation; it only manifests with a real string that happens
to cross the 26-char boundary, which is why it wasn't caught until a real book's metadata hit it.
Fixed (`8d4e935`) by comparing against `target[:search_field.maxLength()]` — i.e., reading the
constraint from the widget itself rather than assuming the value passed to `set_search` is what
ends up stored. **Lesson: any code that compares an external string against "what a widget
currently holds" must derive the comparison value through the same transformation the widget
applies (length limits, input masks, case-folding validators, etc.), not just diff the two raw
strings — the widget's stored value and the value you handed it are not guaranteed to be equal.**

**3. A guard added at one write-path was silently absent from a second, older write-path to the
same widget.** `d8f193d` introduced `self._programmatic_search_update`, set around `set_search`'s
`search_field.setText(...)` call, so `_on_search_changed` could tell a click-originated change
apart from a genuine user edit and only update `self._explicit_filter_text` on the latter. This
correctly protected every *new* call added for the click-to-filter feature — but `search_field`
already had an older, pre-existing direct-`setText` call site, `clear_tag_filter_if_active()`
(added long before this feature, originally just `setText("")` unconditionally), that nobody
thought to route through the new guard because it wasn't being *changed* by this feature, only
*read past* by it. The result: typing `"Feist"`, clicking a tag, then clicking a second tag,
silently lost `"Feist"` — the second click's `_open_library_flow()` → `clear_tag_filter_if_active()`
ran before that click's own `set_search`, saw `_tag_filter_active` was `True` from the first click,
and called the old unguarded `setText("")`, which `_on_search_changed` read as real typing and
overwrote `_explicit_filter_text` with `""`. A near-identical second instance of the exact same
oversight was found the same day in `focusInEvent`'s handler (`a7271a5`) — also a pre-existing
direct `setText("")` call, also never routed through the guard. Both fixed by having those call
sites reuse `clear_tag_filter_if_active()` (itself now guarded) rather than calling `setText`
directly. **Lesson: when adding a guard/flag to make one code path distinguishable from "real user
input," grep for every OTHER call site that writes the same property the same way — a guard is only
as good as its coverage, and old call sites that predate the guard are exactly the ones easiest to
forget because they don't show up in a diff of the feature that introduced the guard.**

## Theme-name hover preview: skip hidden-panel restyle, start the fade AFTER the restyle, debounce the pipeline (2026-07-04)

Hovering a theme name in Settings ▸ Themes ran a ~450–580ms synchronous main-thread
restyle, and the fade animation's clock was started *before* that block — so at the
default fade duration the animation could fully elapse under the restyle and degrade
into a late snap. Sweeping the cursor across several names queued one full restyle per
name crossed, which is why the lateness was intermittent. Three fixes landed
(`826fb8f`); items 4–6 from the same investigation were deferred pending visual
inspection (item 4, the `_load_svg_pixmap` LRU, landed separately — see below).

1. **Skip hidden-panel work when `hover=True`.** `_apply_stylesheets` already skipped
   the library panel + chapter list on hover; extended to the always-hidden
   `stats_panel`/`book_detail_panel` QSS + `stats_panel.on_theme_changed`, and to the
   trailing `_refresh_panel_visuals` / `theme_applied.emit()` / theme-list dimming in
   `_on_theme_changed`.

   **Why this is safe (the load-bearing invariant, not obvious):** a hover preview can
   never leave a panel showing stale colors, because *every* hover exit already runs a
   full `hover=False` restyle — unhover snapback, click-to-activate, and tab-leave all
   do. And a panel can only be opened via the sidebar, which requires *leaving the
   Themes tab first* (`leaveEvent` → unhover → full restyle). So there is no reachable
   sequence where a panel becomes visible after a hover-only restyle without a full
   restyle in between. If a future change ever makes a config panel openable *without*
   leaving the Themes tab, this skip becomes unsafe and must be revisited.

2. **Start `_fade_anim` AFTER `_apply_stylesheets`** in the themes-tab hover branch. The
   overlay is shown/raised *before* the restyle (so the restyle happens invisibly
   beneath it); starting the fade afterward gives it its full configured duration
   instead of burning the clock inside the restyle.

3. **Debounce `_on_theme_hovered` (60ms single-shot).** A cursor sweep across N names
   now fires the pipeline once, for the name it settles on. Unhover and cover-pool
   hover both cancel a pending debounced hover so a stale preview can't fire after the
   cursor has moved on.

Measured (offscreen, timing only): `_apply_stylesheets` hover cost 451ms → 316ms (30%
faster on the skip alone). The residual ~316ms is dominated by `mw.setStyleSheet(base)`
(~185–270ms), a top-level-widget style invalidation flagged as a separate, out-of-scope
refactor — do not conflate it with this hover work. Instrumentation is DEBUG-level (per
the `FABULOR_LOG_LEVEL` convention): per-step wall-clock in `_apply_stylesheets`
(skipped steps log SKIP) + a fade-start-timing line in `_on_theme_changed`.

## `_load_svg_pixmap` LRU cache: returned pixmaps are shared read-only across callers (2026-07-04)

`_load_svg_pixmap` (`ui_helpers.py`) was given an `lru_cache(maxsize=64)` core
(`_load_svg_pixmap_cached`), matching the caching pattern `icon_utils.py`'s
`load_themed_icon`/`load_currentcolor_icon` already used, keyed on
`(name, color, size_wh)` — the `QSize` arg is normalized to a hashable `(w, h)`
tuple since `QSize` itself isn't hashable.

**Load-bearing assumption, not just an implementation detail:** every call site
now gets back the *same* `QPixmap` object on a cache hit, not a fresh copy. All
current callers use it read-only (`setPixmap`, wrapping in `QIcon(...)`,
`drawPixmap`), which is safe. But a future caller that tried to paint into a
returned pixmap in place (e.g. `QPainter(pixmap)` to draw an overlay directly
onto it, rather than onto a fresh copy) would silently corrupt every other icon
currently sharing that `(name, color, size)` cache entry — anywhere else in the
app using that same icon at that same color/size would show the mutated result,
with no error or warning. This is the same sharing contract `icon_utils`'s
existing cached loaders already carry; `_load_svg_pixmap` just newly joins it.
If in-place mutation is ever needed, the caller must `QPixmap(cached).copy()`
(or equivalent) first — never paint directly onto the object the cache returned.

## Removed a redundant direct `stats_panel.on_theme_changed` call — signal path was already the owner (2026-07-04)

`ThemeManager._apply_stylesheets` had a direct `stats_panel.on_theme_changed(...)`
call inside its `if not hover:` block (added 2026-06-29, `b17de6f`, alongside the
Recently-Finished scroll-arrow color fix). Its commit message justified it by
claiming `on_theme_changed` "was previously only ever called once, at startup" —
which was **factually wrong**. The `theme_applied` signal → `on_theme_changed`
connection (`build_stats_panel` in `main_window_builders.py`) has driven it on
every live theme change since the ThemeManager-as-QObject introduction
(2026-04-25, `e337eba`), and still does. `tags_panel` and `book_detail_panel` use
the same signal wiring and have no direct call.

**Confirmed a true duplicate, not dual-trigger coverage:** both live-update sites
are gated by the *same* `if not hover:` condition (one in `_apply_stylesheets`,
one guarding the `theme_applied.emit()` in `_on_theme_changed`), so they always
fire together and never independently. Measured: a real theme change fired
`on_theme_changed` **2×**, a hover preview fired it **0×**. `on_theme_changed` is
fully idempotent — deterministic attribute writes + `.update()` repaint requests +
pixmap re-renders (through the LRU-cached icon loaders), no `.emit()`, no timers,
no DB queries, no accumulating state — so the double-call was pure waste, not a
correctness bug.

**The important verification (the original bug did NOT depend on the direct
call):** before removing, isolated the signal path by neutralizing only the direct
call and confirming the Recently-Finished arrow overlay color
(`FinishedScrollRow._overlay_rgb`, the exact observable `b17de6f` was fixing) still
updated to the new theme's `stats_carousel_stripe`/`accent_dark` on a real theme
change — it did, via the signal path alone, firing `on_theme_changed` exactly 1×.
So the direct call was not masking any signal-path gap (ordering, timing, or a
hover-state edge in the connection); the April signal wiring genuinely already
covered the live-update the arrow fix needed. Removed the direct call; the signal
connection is now the single owner. Do NOT re-add a direct call here.

## FUTURE IDEA (not decided, not implemented): preload the first-page cover set of EVERY view mode (2026-07-03)

**Status: future design idea only. Not decided, not planned, not implemented in this pass.** This
is captured so it isn't lost, not as a committed direction. It came out of the idle-preloader
sized-cache-warming work (see "Idle preloader warms `_sized_cover_cache`" below) and is a distinct,
smaller-scoped opportunity from what that pass implemented.

**The observation (confirmed):** each view mode deterministically shows the *same books* at
scroll-position-zero, regardless of how many times the user has switched modes or which mode is
currently active. "What books are visible on the first open of view mode X" is knowable in advance
— it's a pure function of the current sort order and X's page size — *without the user ever having
navigated to X*. (The grid is fixed-width at 300px, so page size per mode is a constant: roughly
20–30 books.)

**Why it's interesting:** the sized-cache warming that WAS implemented this pass warms only the
**currently active** view mode's cell size, because warming *all* modes' *entire reachable book
sets* would scale memory as (modes × whole library) — explicitly ruled out as not scaling for large
libraries. But warming just the **first-page set** of every mode is bounded by *page size per mode*
(~20–30 books × 5 modes ≈ a small constant), NOT by total library size — so it does NOT reintroduce
the "don't scale per-mode warming by library size" concern. It would make the *first* open of a
mode the user has never visited this session already-warm, killing the first-paint LANCZOS stall for
mode switches too (which the current pass explicitly left as an accepted first-paint cost — see that
pass's point 5).

**Why it's separate and deferred:** it needs its own design pass — computing each mode's first-page
book set from the current sort without instantiating the mode, choosing when to warm the non-active
modes (they'd want an even lower priority than the active mode's full reachable set), and deciding
how a sort-order change invalidates the precomputed first-page sets. Different enough in scope from
"warm the active mode's whole reachable set" that folding it in would have muddied the current pass.
Revisit as a dedicated follow-up if mode-switch first-paint stall becomes a felt problem.

---

## `_sized_cover_cache` memory + warming-time cost (all view modes vs. active-only) (2026-07-04)

Reference numbers behind the "active view mode only" scoping decision for the idle-preloader
sized-cache warming (see "Idle preloader warms `_sized_cover_cache`" and the FUTURE IDEA entry
above). Kept here so the tradeoff doesn't have to be re-derived.

**Memory model.** A sized pixmap costs `stored_w × stored_h × 4 bytes` (RGBA8888), and — this is
the key point — that is **independent of the source cover's file size or resolution**: it's the
scaled-down raster, not the original. `stored_w/h` is the source scaled to *cover* the cell (max
of the two axis ratios; `_get_sized_cover`'s expand-then-crop), so slightly larger than the cell
on one axis. Per-mode cover-rect sizes come from `BookDelegate.cover_cell_size()`:
Square 92×92, 3-per-row 92×142, 2-per-row 113×172, 1-per-row 100×151 (List has no cover). Costs
scale with **DPR²** (a HiDPI/Retina 2× display quadruples every number — 2× per axis), so any
"cache more" decision must be reasoned at DPR 2, not DPR 1.

Per-book, summing the 4 cover-bearing modes: **~237 KB at DPR 1, ~950 KB at DPR 2.**

| Library size | All 4 modes @DPR1 | All 4 modes @DPR2 | Active-mode-only @DPR2 (what ships) |
|---|---|---|---|
| 383 (current lib) | 89 MB | 355 MB | 114 MB |
| 1,000 | 232 MB | 928 MB | 297 MB |
| 4,000 | 927 MB | **3.7 GB** | 1.2 GB |
| 10,000 | 2.3 GB | **9.3 GB** | 3.0 GB |

The intercept is tolerable; the **slope** is the problem — cost is `books × modes × dpr²` and
`_sized_cover_cache` has **no eviction** (grows for the session; see DEBT_INVENTORY.md). "All modes"
just multiplies the already-unbounded active-mode figure by 4 for **no additional stall benefit**
over "active mode" + the bounded first-page-per-mode idea combined. Hence: do NOT warm all modes.
If mode-switch stall becomes a felt problem, do the **first-page-per-mode** approach from the FUTURE
IDEA entry instead — ~20–30 books × 5 modes ≈ **~5 MB flat at DPR 2, independent of library size**.

**Warming time (measured, this machine, 383-book lib, "3 per row").** With the shipped config
(`PRELOAD_BATCH_SIZE=3` / `PRELOAD_INTERVAL_MS=50` ⇒ 60 books/s theoretical) and the real gate in
place, the whole library warmed (both `_cover_cache` and `_sized_cover_cache`) in **~6 s of
preloading**, after the initial 5 s idle wait — steady **~58–61 books/s**, i.e. it hits the dispatch
ceiling. Warming is **dispatch-bound, not scale-bound**: the off-thread LANCZOS keeps up with the
50 ms tick, so time scales linearly and predictably as **≈ books ÷ 60 seconds** (≈ 17 s for 1,000
books, ≈ 67 s for 4,000). This is wall-clock while idle and untouched; any interaction resets the
5 s idle timer and pauses in-flight work, so real-world completion is longer if the app is actively
used.

---

## No-cover-source handling consolidated into `_show_no_cover_state` (2026-07-03)

Step 1.5 of the placeholder rework: de-duplicated the two identical no-cover branches in
`_load_cover_art` (app.py) ahead of the title/author layout redesign, so that redesign lands in
one place instead of two. **No behavioral change.**

**Helper shape** — took all five statements (the earlier extraction diff's sketch had omitted the
`_pending_cover_pixmap = None` and `theme_manager.clear_cover_theme()` calls, but both branches did
them, so they belong inside):
```python
def _show_no_cover_state(self, book) -> None:
    self.current_cover_pixmap = QPixmap()
    self._pending_cover_pixmap = None
    self.theme_manager.clear_cover_theme()
    self._show_cover_placeholder()
    self.metadata_label.show()
    self.metadata_label.setText(
        f"{book.author} - {book.title}" if book else "Unknown book"
    )
```

**Call sites (2, both now one-liners):** the `not active_path and not fallback_path` branch, and the
final `else` after `player.extract_cover(file_path)` returns a null pixmap. Both call
`self._show_no_cover_state(book)` then behave as before (the first `return`s; the second is the end
of the method).

**Were the two branches identical?** Yes — **byte-for-byte identical**, all five statements in the
same order. No per-call-site difference, so nothing had to stay outside the helper and no parameter
was needed for a divergence.

**One thing worth flagging: there is a THIRD no-cover branch that is deliberately NOT part of this
helper** — the `if not file_path:` early return at the top of `_load_cover_art`. It is the "no book
loaded at all" path and does the *opposite* of the two consolidated branches: it **hides** the cover
label AND **hides** `metadata_label` (and calls `_cover_placeholder.clear()`, not
`_show_cover_placeholder()`). It only shares the `current_cover_pixmap = QPixmap()` +
`clear_cover_theme()` lines superficially; its intent (show nothing) is distinct from "show the
placeholder + metadata". Left untouched — folding it in would have changed behavior.

**No third duplicate of the sequence elsewhere:** grep for the dash-joined
`"{book.author} - {book.title}"` / `"Unknown book"` format across `src/fabulor/` returns exactly one
hit — inside the new helper. Nothing else in the codebase reproduced it.

**Tests:** full suite green (48 passed). Pure de-duplication, no test changes.

## Cover placeholder extracted to its own module (2026-07-03)

Step 1 of a two-step change: pulled the no-cover Fabulor-logo placeholder rendering out of
`MainWindow` (app.py) into `ui/cover_placeholder.py` (`CoverPlaceholder`) with **no behavioral
change**. This is the groundwork for a follow-up that redesigns the placeholder's text layout
(author/title on separate lines, title wrap, logo position shifting with one- vs two-line title) —
that layout logic is explicitly NOT in this change.

**Public interface** (drifted slightly from the original prompt sketch — the color is resolved by
the caller, not the module):
- `CoverPlaceholder()` — no args; owns the `_showing` bool.
- `show(cover_art_label, color: str)` — renders `fabulor.svg` recolored to `color` at
  `COVER_AREA_HEIGHT * 0.65`, sets it on the label, `show()`s, sets `_showing=True`; on any
  exception hides the label and sets `_showing=False` (identical to the old inline behavior).
- `clear()` — sets `_showing=False` (a real cover loaded).
- `refresh(cover_art_label, color: str)` — re-renders only if `_showing` (theme-change path).
- `is_showing` property.

**Why `color` is a parameter, not resolved inside the module:** the old `_show_cover_placeholder`
resolved the placeholder color from the live theme (`_resolve_theme(...)` +
`placeholder_cover`→`library_narrator`→`text`→`#888888` chain). Keeping that resolution in the
module would have coupled it to `ThemeManager`/`themes.py`. Instead app.py keeps a tiny
`_placeholder_color()` helper that does the resolution and passes the string in. Both call sites
(`_show_cover_placeholder`, and the theme-change `refresh` in `_reload_button_icons`) go through it,
so the fallback chain still lives in exactly one place.

**app.py call-site mapping** (was → now):
- `self._showing_placeholder = False` (init) → `self._cover_placeholder = CoverPlaceholder()`.
- `_apply_main_cover`: `self._showing_placeholder = False` → `self._cover_placeholder.clear()`.
- `_load_cover_art` `not file_path` branch: same flag-clear → `.clear()`.
- `_reload_button_icons`: `if self._showing_placeholder: self._show_cover_placeholder()` →
  `self._cover_placeholder.refresh(self.cover_art_label, self._placeholder_color())`.
- `_show_cover_placeholder` (still exists, now a 1-liner delegating to `.show(...)`) — kept so its
  two call sites in `_load_cover_art` are untouched.

**Dead imports removed from app.py** (only ever used by the moved SVG-building code): `re`,
`QByteArray`, `QSvgRenderer`, and `_ASSETS_DIR` (from `ui_helpers`). Verified each had exactly one
remaining occurrence (its import line) before removing. `COVER_AREA_HEIGHT` stays imported in app.py
(still used by `_update_cover_art_scaling`); it is *also* imported by the new module from
`ui_helpers` (the single source of truth), not duplicated.

**Awkwardness worth flagging before the layout follow-up:** the "no cover source" handling is
duplicated across TWO branches of `_load_cover_art` — the early `not active_path and not
fallback_path` branch (~line 2224) and the final `else` when `extract_cover` returns null (~line
2255). Both do the same four things: clear pixmap, clear pending cover, `clear_cover_theme()`,
`_show_cover_placeholder()`, then `metadata_label.show()` + set the `"{author} - {title}"` text.
The layout redesign will touch that metadata text, so whoever picks up step 2 should consider
folding those two branches into one helper first — otherwise the new two-line author/title layout
has to be written twice. Left as-is here to keep this diff a pure move.

**Tests:** no test referenced `_showing_placeholder`, so none needed updating. Full suite green
(48 passed).

## Sidebar visible through settings panel on open — ROOT CAUSE CONFIRMED, not yet fixed (2026-07-01)

**Do not file this under "Spurious sidebar expand during theme hover" (below in this file, originally
2026-05-26).** They read as the same bug ("sidebar bleeds through / is visible when it shouldn't be")
but source tracing this session showed they are not — see that entry's own correction for why its
original race theory is dead. This is a separate bug, now root-caused, with a fix not yet written.

**Symptom:** the sidebar is visible through the Settings panel specifically at the moment the panel
first appears — never once it's already open and stable. Settings' background is intentionally
semi-transparent (`panel_opacity_hover` in `themes.py`, ~0.88–0.95 depending on theme), so *some*
see-through is by design; the bug is that the sidebar is fully expanded (`x=0`, not mid-collapse)
underneath, because it never actually started closing.

**Root cause, confirmed via live `perf_counter()` trace (`panels.py` instrumentation, commit
`ed1c7b2`):** `_toggle_sidebar()`'s re-entrancy guard —
```python
if self.sidebar_animation.state() == QAbstractAnimation.State.Running:
    return
```
— returns *before* doing anything, including before logging, if a sidebar animation is already in
flight. All six `_open_*_flow` methods (`_open_library_flow`, `_open_settings_flow`,
`_open_speed_flow`, `_open_sleep_flow`, `_open_stats_flow`, `_open_tags_flow`; `_pending_panel_open`
assignments at `panels.py:95,184,267,386,418,496`) share one queued-open pattern that assumes every
`_toggle_sidebar()` call it makes *starts a new animation* it can wait on via
`sidebar_animation.finished.connect(_on_sidebar_closed_for_panel)`. It doesn't check the guard itself
and has no way to know when its call was silently dropped.

**The confirmed failure sequence (2026-07-01 20:42:59, user's own words: "I managed to sneak in a
right click between clicking the Settings entry and panel actually sliding"):**
1. User rapid-toggles the sidebar (closed→open→closed→**open**, the last one still `Running`).
2. User clicks Settings while that 4th (opening) animation is still in flight:
   `_open_settings_flow` sees `sidebar_expanded=True` (already flipped synchronously at the 4th
   toggle's click time, per the earlier-confirmed synchronous-write behavior) and `sidebar_animation.
   state()=Running`. It queues `_pending_panel_open="settings"`, connects
   `_on_sidebar_closed_for_panel` to `finished`, and calls `_toggle_sidebar()` — a 5th call.
3. That 5th call hits the guard above and returns immediately, doing nothing — no new animation, no
   flag flip, silently dropped. `_open_settings_flow` has no idea.
4. The 4th animation (the one already running — an **opening** slide) finishes on its own, landing
   the sidebar at `(0, 56)`, fully expanded.
5. Its `finished` signal fires `_on_sidebar_closed_for_panel`, which has no way to tell this
   `finished` came from an opening animation rather than a closing one it caused — it just dispatches
   `_start_settings_entry()` immediately. Confirmed in the log:
   `_on_sidebar_closed_for_panel ENTRY sidebar_expanded=True` →
   `_start_settings_entry ENTRY sidebar_expanded=True sidebar.pos()=(0, 56)`.
6. Settings slides in over a fully-expanded, fully-visible sidebar. Its ~90%-opaque background makes
   the sidebar visible underneath for the whole open (not just a transient frame) — matching the
   user's report that it's visible from the moment the panel first appears.

**Ruled out en route to this (kept for context, not because the theories were viable — they were
useful negative evidence that narrowed the search):** an over-broad first catch turned out to be
correct state, not a bug (sidebar toggled open independently of any panel-open flow, hovering
happened afterward with both simultaneously and validly open); repeated rapid right-clicks *while
Settings was already open* correctly triggered `_close_settings_flow` every time and never reproduced
it; two clean single-click Settings opens traced frame-by-frame showed no overlap window at all. All
three were genuinely clean runs — the bug only appears when the *extra* click lands during the brief
window while a sidebar animation from a **preceding, separate** toggle is still in flight, which none
of those three scenarios happened to hit.

**Fix approach (not yet implemented — deliberately deferred to a separate session):** the queued-open
pattern needs to detect a dropped `_toggle_sidebar()` call and either retry it once the in-flight
animation actually finishes, or (simpler) have the six `_open_*_flow` methods check
`sidebar_animation.state() == Running` themselves before deciding whether to queue at all, and/or have
`_on_sidebar_closed_for_panel` re-check `sidebar_expanded` when it fires and bail out (re-queue) rather
than blindly dispatching if the sidebar turns out to still be expanded. Whichever approach, it must be
applied consistently across all six `_open_*_flow` methods, not just `_open_settings_flow` — they share
the identical pattern and are equally exposed.

**Instrumentation that caught this (commit `ed1c7b2`, `panels.py`), all DEBUG-level / silent by
default and left in place — still useful for confirming the fix once written:**
`handle_drag_area_right_click` (which panel-visible flags it sees, which branch it takes);
`_open_settings_flow` entry state; `_on_sidebar_closed_for_panel` entry/exit; `_on_sidebar_hidden`
entry; frame-by-frame `settings_panel_animation` tracing. Known gap: `_toggle_sidebar`'s early-return
guard returns before its own log line, so a dropped call is currently invisible directly — its
presence has to be inferred from the surrounding `_on_sidebar_hidden`/`_open_settings_flow`/
`_on_sidebar_closed_for_panel` timestamps, as done above. A future instrumentation pass could log the
guard's early return explicitly if this needs re-diagnosing.

---

## Logging infrastructure added — `user_log_dir("fabulor")` uses the one-arg platformdirs form; revisit for the Windows port (2026-07-01)

Added `src/fabulor/logger_setup.py` (`setup_logging()`, called first thing in `main.py`'s
`__main__` block): a rotating file handler (2 MB × 3) on the `fabulor` root logger, level from
`FABULOR_LOG_LEVEL` (default WARNING), file sink only. Module-level `logger` instances are
declared in `player.py`, `app.py`, `ui/theme_manager.py` but have **no call sites yet** — those
land incrementally in later sessions.

**Windows-port gotcha — the two `platformdirs` call forms differ, and it matters on Windows:**

- The **log sink** uses the **one-arg** form: `platformdirs.user_log_dir("fabulor")` — appname
  only, **no appauthor**. On Linux this resolves to `~/.local/state/fabulor/log`.
- **Every other user-dir call** in the codebase uses the **two-arg** form
  `platformdirs.user_data_dir("fabulor", "fabulor")` / `user_cache_dir("fabulor", "fabulor")`
  (appname **and** appauthor) — see `db.py`, `library/cover_manager.py`, `library/scanner.py`.

On Linux the `appauthor` argument is ignored, so the two forms differ only cosmetically and
everything lands under `~/.local/{state,share,cache}/fabulor/`. **On Windows** `platformdirs`
inserts `appauthor` as an actual path segment (`…\fabulor\fabulor\…`), so the one-arg log dir and
the two-arg data/cache dirs would land under **different** parent folders. When porting, decide
whether to unify on the two-arg form (recommended, for one consistent per-app tree). This was
left as-is deliberately this session to keep the logging change additive-only.

## A delegated `setFixedSize(other_widget.size())` call was the real cause of the icon-position bug — found AFTER a full revert (2026-06-28 → 2026-06-29)

**Symptom:** adding a gravestone icon (`_missing_label`) next to the existing ghost icon
(`_ghost_label`) in `BookDetailPanel`'s header pushed the ghost icon down whenever both were
visible, and pushed the whole panel's tab row (Stats/History/Tags) down with it. A full session
(2026-06-28 Session 2, several hours) tried to fix this via `QSizePolicy.RetainSizeWhenHidden`,
unifying the two widgets into a single `QToolButton` with a `QStackedLayout`, and a real (but
unrelated) `_cover_label` fixed-height fix — none of it found the actual bug, and the whole
structural detour was reverted back to the prior commit.

**Root cause, found by the user independently after the revert:**
`self._missing_label.setFixedSize(self._finished_label.size())` — the gravestone label's size was
*delegated* to another widget's `.size()` at construction time, not a literal number. This is the
reason a "grep for suspicious magic numbers" pass across the broken layout never found it during
the original multi-hour investigation: there was no number to grep for at the call site. The actual
fixed size baked in at construction time differed from what was visually expected, and because nothing
else in the surrounding code uses delegated sizing this way, there was no comparison point to notice
it against.

**The fix, three lines, no structural change at all:**
```python
self._missing_label.setFixedSize(16, 18)              # literal, not delegated
self._missing_label.setContentsMargins(0, 0, 0, -1)
self._ghost_label.setContentsMargins(8, -2, 0, 0)
```
The entire `RetainSizeWhenHidden`/`QStackedLayout` unification from the reverted session was
unnecessary — the original two-separate-widgets structure was fine; only the size value was wrong.

**General lesson:** `widget.setFixedSize(other_widget.size())` (or any size/geometry call that reads
from a SECOND widget's current state rather than a literal) is exactly as much a "magic number" as a
hardcoded literal — it's just one level of indirection deeper, and won't show up in a search for
literal numbers. When debugging an unexplained size/position discrepancy, explicitly check every
`setFixedSize`/`setGeometry`/`resize` call for a delegated argument, not just literal-looking ones.

## `is_missing` silently dropped from five stats/tag SELECT queries (2026-06-28)

**Symptom:** two specific books (The Carpet Makers, The Lotus Shoes), both flagged `is_missing=1`
via the scanner's force-rescan detector, showed in FULL COLOR in the Overall/Day/Week/Month stats
tabs instead of monochrome with the ghost icon — while other books flagged via the older
`is_deleted`/`is_excluded` mechanisms displayed correctly archived. The user noticed the pattern
("what's common... is that they are both books I finished and removed") and asked for a DB check
rather than accepting a UI-only diagnosis.

**Root cause:** `stats_panel.py`'s `BookDayRow`/`FinishedBookThumb` archived check
(`row_data.get("is_missing", 0)`) was already correct — it had been updated for `is_missing` in an
earlier session. The bug was one layer down: `get_daily_book_breakdown`, `get_books_listened_in_period`,
`get_finished_in_period`, `get_recently_finished`, and `get_books_by_tag` (`db.py`) all `SELECT`ed
`b.is_deleted` and `b.is_excluded` explicitly, but never `b.is_missing` — so the row dict handed to
the widget simply didn't have that key, and `.get("is_missing", 0)` defaulted to 0 regardless of the
column's true value in the database. A correct `WHERE`-clause fence (the kind of gap the
`is_missing` rollout session swept for and fixed in seven other queries) does NOT catch this: these
five queries don't fence on `is_missing` in their `WHERE` at all (they intentionally show
archived/missing books, just dimmed) — the gap was purely in the `SELECT` column list.

**Verification approach:** queried `library.db` directly via `sqlite3` for the two affected books'
raw flag values, confirming `is_missing=1, is_excluded=0, is_deleted=0` — i.e. genuinely archived,
genuinely not displaying as such. Then grepped `db.py` for every `b.is_excluded` `SELECT` site and
added `b.is_missing` immediately after each one as a single `replace_all` edit, rather than fixing
one query and assuming the others were fine — this exact "fix one, the others were the same shape"
pattern was the lesson from the original `is_missing` rollout's `WHERE`-fence sweep, reapplied here
to `SELECT` lists instead.

**Lesson:** `WHERE`-clause fencing and `SELECT`-column completeness are two independent things that
both need a full sweep whenever a new soft-delete-ish flag is added — fixing one does not imply the
other is fixed, and a query that's correctly UNfenced (because it deliberately wants to show
archived rows) can still silently omit the column that tells the caller WHY a row is archived.

## A second, independent path into the `is_missing` ping-pong: excluding BEFORE the file goes missing (2026-06-28)

**Symptom, user's exact repro:** exclude a book (file still on disk at the time) → move its folder
out of any scanned location → force rescan. Expected (per the original `is_missing` fix): the book
gets `is_missing=1` and disappears from the Excluded Books popup, since `get_excluded_books()`
already fences `is_missing=0`. Actual: it stayed `is_excluded=1, is_missing=0` indefinitely, full
rescans included — the book never got the `is_missing` flag despite its folder genuinely being gone.
It stayed visible in the popup with a live eye icon; clicking it just un-excluded a book with no file
behind it, reproducing the EXACT symptom the original `is_missing` fix existed to eliminate.

**Root cause:** the scanner's force-rescan missing-detector diffs `db.get_visible_book_paths_under(loc)`
against what Phase 1 actually found on disk, flagging anything missing from that diff via
`mark_books_missing`. `get_visible_book_paths_under`'s query fences `is_deleted = 0 AND is_excluded
= 0 AND is_missing = 0` — by design, for OTHER call sites that need "visible in the library right
now." But for THIS call site, that same fence means an already-excluded book is invisible to the
diff entirely: the scanner never even considers whether its folder still exists, because the query
filtered it out before the comparison ever happens. The original `is_missing` fix (see the entry
below this one) only covers a book that goes missing BEFORE the user excludes it — once excluded,
file-existence checking for that book silently stops forever. Two independent orderings of the same
two events (exclude, then lose the file vs. lose the file, then the scanner catches it) take two
different code paths, and only one of them was fixed.

**The fix:** added `get_non_deleted_book_paths_under` — identical shape to
`get_visible_book_paths_under` but fencing ONLY `is_deleted = 0`, deliberately NOT `is_excluded`/
`is_missing` — and switched the scanner's missing-detector to use it instead. This does not
resurrect anything into view: `get_excluded_books()` (which drives the popup) still independently
fences `is_missing = 0`, so the moment this new, wider check sets `is_missing=1` on an excluded
book, it disappears from the popup on the very next reload — closing the loop the original fix was
supposed to close. Verified directly against the live DB (not just by reading the code): toggled
`is_excluded` on a real row and confirmed `get_visible_book_paths_under` excluded it from its result
while `get_non_deleted_book_paths_under` included it, before trusting the fix and asking the user to
re-test live.

**Why this wasn't caught by the original `is_missing` session's testing:** that session's repro
order was always "file goes missing → scanner flags it → (optionally) user later interacts with the
now-missing-flagged row." It never tested "user excludes a book that's still present, THEN its file
disappears" — a different chronological ordering of the same two facts, which happens to route
through a completely different DB query with its own independent fence. Any future flag-interaction
bug in this area should be checked against BOTH orderings of "user does X" / "file does Y", not just
the one that was originally reported.

## Ghost icon and the new missing/gravestone icon doubled up for the same is_missing reason (2026-06-28)

**Symptom:** after wiring up a new dedicated `missing.svg` (gravestone) icon for `is_missing` books
in `BookDetailPanel`, ANY book flagged `is_missing=1` showed BOTH the new gravestone icon AND the
pre-existing ghost icon — even when `is_excluded` and `is_deleted` were both 0.

**Root cause:** the first implementation pass set the new icon's visibility from `_is_missing`
(correct) but left the ghost icon's visibility driven by the existing `_is_archived` boolean, which
is `is_deleted OR is_excluded OR is_missing` — i.e. `is_missing` was already one of `_is_archived`'s
three inputs by design (from the original `is_missing` rollout, which intentionally folded it into
the existing archived/dimmed treatment with NO new icon, since no gravestone asset existed yet).
Adding a second, MORE SPECIFIC icon on top of that broad boolean, without narrowing what the ORIGINAL
icon responds to, inevitably double-fires both for the overlapping case.

**The fix, per the user's explicit rule** ("is_missing=1 OR is_deleted=1, gravestone. is_excluded=1,
ghost. Separate things."): split into two independent booleans. `_is_excluded` (new) drives the
ghost icon — `is_excluded` ONLY, nothing else. `_is_missing` (redefined) drives the gravestone icon
— `is_missing OR is_deleted` (both "gone from disk" reasons share the one icon; "user explicitly
trashed it" gets the other). `_is_archived` itself is UNCHANGED and still drives the unrelated
grayscale-cover and remove-button-visibility logic, which legitimately wants "archived for ANY
reason" — only the two ICONS needed to stop sharing one trigger condition. A book can still show
BOTH icons together when it's independently true for both reasons (e.g. excluded AND later found
missing) — that's correct, not a regression of this fix.

## Excluded Books popup: two more bugs only reproducible via a same-tab refresh (2026-06-28)

**Symptom 1:** start the app, exclude a book via the detail panel's trash button WHILE Settings →
Library is already open, then navigate back to Settings → Library. The toggle line correctly reads
"1 book excluded" but the list itself is invisible. Closing and reopening the settings panel fixes
it.

**Root cause 1:** `_on_book_detail_removed` (the trash-button signal handler in `app.py`) simply
never called `_reload_excluded_books()` at all — every other refresh it does (library panel, tags,
stats) was present; this one call was missing. The count line showing correctly was misleading: it
implied SOME refresh path ran, but it was actually the LATER close/reopen of the settings panel
(which does call `_reload_excluded_books()` normally) that the user performed as part of their own
repro investigation, not anything triggered by the exclude action itself.

**Symptom 2 (worse, same underlying class):** with 6 books excluded via the same trash-while-open
flow, the count line again showed correctly, but the arrow was clickable, and clicking it grew the
list DOWNWARD instead of upward, with the arrow moving UP instead of down to track it — both
directions visibly inverted from the correct, already-tested-in-Session-1 behavior.

**Root cause 2 (found after fixing root cause 1 — this symptom persisted even with the
`_reload_excluded_books()` call added):** `_reload_excluded_books()` calls
`excluded_books_section.set_count(len(books))` immediately before
`excluded_books_popup.reposition(excluded_books_section, library_tab)`. `set_count()` can flip
`excluded_books_section` from hidden to visible (`setVisible(count > 0)`) if the count was 0 before
this call (i.e., the section had no reason to be shown). Qt does NOT guarantee that a widget's
`height()` reflects its final, laid-out size the instant `setVisible(True)` returns — the actual
layout pass can land on a later tick of the event loop. `reposition()` reads
`anchor_widget.height()` synchronously, a few lines later in the SAME call stack, with no
opportunity for that layout pass to run in between — so it can compute `_anchor_bottom` from a
stale or zero height. Garbage height feeds directly into both the list's vertical position
(explaining the invisible-but-correctly-counted box) and, since the SAME `_anchor_bottom` anchors
the arrow's lift calculation in `_reposition_arrow`, into the arrow's position too — explaining why
the direction itself looked inverted: the underlying expand-upward/lift-the-arrow-up logic (fixed
and tested in Session 1) was never wrong; it was being fed a corrupted starting point.

**The fix:** `self.library_tab.layout().activate()` immediately before the `reposition()` call,
forcing the pending layout pass to resolve synchronously so `anchor_widget.height()` is guaranteed
current by the time it's read. This is narrower than `QApplication.processEvents()` (which would
also process unrelated pending events/repaints/signals) — `layout().activate()` only forces this one
layout's geometry to recompute.

**Why this didn't surface in Session 1's testing:** every Session 1 repro opened the settings panel
fresh each time (close fully, then reopen) — `_library_tab_shown_once` was already `True` by the
relevant point, and `excluded_books_section` was already visible and already correctly laid out from
a PRIOR open, so `set_count()` never actually flipped visibility from hidden to shown in the middle
of a `reposition()` call. The bug only exists in the narrower window where a refresh happens WHILE
the tab is already the current, visible page AND the section's visibility is changing as part of
that same refresh — a path Session 1 never exercised because its repros always closed the panel
between state changes.

## Excluded Books list: re-parented to library_tab, position/expand bugs fixed (2026-06-28)

**Context:** following the 2026-06-27 popup rebuild (entry below) and the always-visible/arrow-split
redesign, this session was almost entirely live back-and-forth with the user fixing four distinct
bugs in the new list. Recorded in full because several of the fixes are genuinely unobvious and at
least two of my own diagnostic approaches were actively wrong before landing on the real cause —
worth keeping the wrong turns visible, not just the final fix.

### Bug 1 — list rendered ~100px too high, overlapping other settings rows

**Symptom, as the user reported it (verbatim, paraphrased across several messages):** the list
appeared well above the "Excluded books" row, overlapping "Naming pattern"/"Chapter source" text.
Screenshots were given multiple times; my own geometry-measurement diagnostics ("anchor_top=350,
height=74, target_y=276... math is internally consistent") kept reporting the position as correct,
directly contradicting the user's repeated visual reports. **This contradiction was real and was
not resolved by re-measuring harder** — the actual bug was in the surrounding architecture, not the
arithmetic.

**What it actually was:** the list's `_reposition_vertically()` computed `target_y = anchor_top -
self.height()` — i.e., it anchored to the row's TOP edge and grew upward from there, immediately.
That arithmetic was internally self-consistent (hence my diagnostics kept passing), but it placed
the box in the wrong general area: anchoring to the row's top edge and subtracting height puts the
box's bottom edge AT the row's top edge, i.e. flush-above-and-touching, not where it's supposed to
sit when collapsed. The correct model (confirmed explicitly by the user, see "Bugs 2-3" below) is:
the box at its DEFAULT (collapsed, 3-row) size sits flush BELOW the "Excluded books" row, and ONLY
when expanded does it grow upward from there, covering whatever's above. The original code skipped
the "sits below by default" step entirely and went straight to "anchored above, grown upward by its
current height" — which for a 7-row expanded box reaches much further up than the 3-row collapsed
case ever should.

**Why my own diagnostics didn't catch it:** I was verifying that `move()` placed the widget where the
code told it to, which it always did — the bug was in deciding WHERE that should be, not in the
move() call itself. A script confirming "the code does what the code says" cannot catch "the code
says the wrong thing." This is the same class of failure flagged in the existing CLAUDE.md rule "DO
NOT verify a settings-panel/tab visual layout bug with headless test scripts alone" — added for a
different bug, same underlying lesson, reconfirmed here.

**The fix, in two corrected passes (I got the SECOND attempt wrong too — see Bug pass 2):**
1st pass: anchored flush below the row, grew DOWNWARD when expanded. User caught this immediately:
growing downward runs the box off the bottom of the tab/window — there's no room below "Excluded
books," same as there's no room above it for the original upward-without-an-anchor-step bug. 2nd
pass (correct, confirmed): the box's BOTTOM edge is computed ONCE, fixed at `anchor_bottom =
anchor_top + anchor_height + DEFAULT_ROW_COUNT_HEIGHT` (always using the 3-row height for this
calculation, regardless of current expand state) — that bottom edge never moves again. Expanding to
7 rows only moves the TOP edge upward from that fixed bottom, covering whatever's above (Naming
pattern/Chapter source) as the topmost element — exactly mirroring how `ChapterList` anchors its
bottom and grows up. `_reposition_vertically()` is now just `self.move(POPUP_X, anchor_bottom -
self.height())` — trivial once the anchor concept was right.

### Bug 2 — arrow didn't visually move when the list expanded

**Symptom:** code clearly called `move()` on the arrow with a new, higher y-coordinate when
expanding, confirmed via direct inspection — but the arrow never visibly moved.

**Root cause:** the arrow `QLabel` was a CHILD of `ExcludedBooksSection` (the toggle-line row
widget), which itself has no fixed height — it's a normal `QVBoxLayout` member sized to its natural
content. Qt clips child widgets to their parent's bounding rect; moving a child to a y-coordinate
above its parent's own (0,0) origin (which is exactly what "lift the arrow up to track the
expanding box" requires) makes it paint over nothing — silently invisible, no warning, no error.
This is the same fundamental class of bug as `ChapterList`'s historical "DO NOT try to expand a
widget's height inside the Library settings tab's QVBoxLayout" trap (see CLAUDE.md), just
manifesting as silent clipping instead of stolen layout space.

**The fix:** re-parented the arrow `QLabel` to `library_tab` directly (the SAME parent the popup
itself uses), via a new `ExcludedBooksSection.set_arrow_parent(library_tab)` called once from
`app.py` right after both objects exist. Positioning is now computed via `self.mapTo(library_tab,
...)` to translate the section's own row position into `library_tab`'s coordinate space, so the
arrow can be centered on the row horizontally while moving freely in the vertical axis without any
parent-bounds clipping.

### Bug 3 — collapsed/expanded sizing shrank to fit instead of staying fixed

**Symptom:** with 4 excluded books, expanding showed 4 rows, not 7; going from 2 books down to 1
shrank the collapsed box to 1 row instead of staying at 3.

**Root cause:** `_resize_to_row_count()` used `min(self.count(), MAX_EXPANDED_ROWS or
DEFAULT_VISIBLE_ROWS)` — capping the shown row count at however many books actually existed. The
correct, explicitly confirmed behavior: collapsed is ALWAYS exactly 3 rows (with empty space below
the list if there are 1-2 books) and expanded is ALWAYS exactly 7 rows (with empty space if there
are 4-6) — two fixed sizes, never a shrink-to-fit. Removed the `min()` entirely from both the resize
logic and the arrow's lift-distance calculation (which has to use the same fixed delta, or the arrow
and the box would disagree on how far "expanded" actually moves).

### Bug 4 — book count off-by-one and stuck-expanded state, both from the same stale read

**Symptom, in order discovered:** (a) restoring a book down to exactly 3 left a stale "4 books
excluded" label for a moment / arrow stayed lifted at the expanded position; (b) the count label was
consistently one too high immediately after clicking an eye icon.

**Root cause (one cause, two symptoms):** `ExcludedBooksPopup` used `self.count()` — the live
`QListWidget` item count — as the source of truth for both the displayed count AND the
`is_expandable` decision. But the restore flow (`_on_row_restore`) fires the `restore_requested`
signal (which `app.py` uses to update the DB and refresh the count label) BEFORE removing the row
from the widget — the actual `takeItem()` call only happens after a ~250ms slide-out animation
finishes. So `self.count()` is stale-by-one for the entire duration of that animation, and anything
that reads it synchronously right after a restore (which `app.py`'s handler does, immediately) sees
the old, pre-restore count.

**The fix:** added an explicit `_book_count` integer on the popup, decremented immediately in
`_on_row_restore` (in lockstep with the `restore_requested` emit, not waited on the animation), and
rewired `is_expandable`, `reposition()`'s show/hide check, and `_resize_to_row_count()` to read it
instead of `self.count()`. Exposed via a public `book_count` property so `app.py` doesn't need to
duplicate the DB query it was previously using as an awkward workaround for the same staleness.
`app.py`'s restore handler also now explicitly forces `popup.set_expanded(False)` when the fresh
count drops to/below the default — without that, the popup's internal `_expanded` flag had no other
trigger to clear it when the count crossed the threshold from the OUTSIDE (i.e. via restore, as
opposed to the user clicking the arrow), leaving it stuck sized at 7 rows even after the section's
arrow had already visually flipped to its dimmed/collapsed style.

**General lesson, stated plainly since it cost real back-and-forth:** `QListWidget.count()` (or any
live widget-state read) is not a safe stand-in for "the true current count of the underlying data"
the moment there's an animation or any other delay between a user action and the widget actually
reflecting it. Track the real count as an explicit variable updated at the moment of the actual data
change, not derived from incidentally-correct-most-of-the-time widget introspection.

## Excluded-books "Schrödinger's audiobook": restoring a missing book put it right back in Excluded Books (2026-06-27)

**Symptom:** a book that was both physically deleted from disk AND flagged in the Excluded Books
popup would ping-pong forever. Click the eye to restore → the book reappears in the library (with
no file behind it) → user tries to play it → it lands right back in Excluded Books → repeat.

**Root cause:** `is_excluded` was overloaded to mean two different things. (1) The user deliberately
trashed a book via the detail-panel trash button (`set_book_excluded`, book still physically
present at the time). (2) The force-rescan missing-detector (`mark_books_missing`, added the
previous session — see the popup-architecture entry below) flagged a book whose folder is gone,
using the SAME flag. The popup's eye-click restore (`_on_excluded_book_restored` → 
`set_book_excluded(path, False)`) treated every row identically — for a case-(2) row, the file
genuinely isn't there, so unconditionally un-excluding it just put a file-less row back in the
visible library. The user (or `_on_book_selected_from_library`/playback) would try to load it,
`_mark_book_missing` would fire again (`os.path.exists(path)` still False), calling
`set_book_excluded(path, True)` again — landing it right back in Excluded Books.

This was unreachable before the previous session's missing-detection feature shipped: `is_excluded`
only ever got set by a deliberate user action on a book that was, by definition, still present when
they clicked trash. The bug only existed in the *combination* of two correct-on-their-own features.

**The fix:** a new, independent `is_missing` column (`db.py` migration, same pattern as the existing
`is_excluded`/`*_locked` columns). `mark_books_missing`/`_mark_book_missing` now write `is_missing`,
never `is_excluded`. `get_excluded_books()` filters `is_missing=1` rows out of the popup entirely —
there is no restore action that makes sense for a book that isn't there, so it simply isn't shown.

The two flags have **deliberately opposite** reset behavior, which is itself worth flagging for
future readers: `is_excluded` is sticky (the upserts' `CASE WHEN books.is_excluded THEN 1 ELSE 0
END` — a force rescan must never silently un-exclude a deliberate user-trash). `is_missing` is the
opposite — both upserts reset it to a **plain, unconditional 0**, no CASE WHEN at all — because an
upsert only ever runs for a path the scanner just rediscovered on disk; rediscovery is unambiguous
proof the file is back, so there's nothing to guard against. Do not "fix" `is_missing` to also use a
CASE WHEN guard "for consistency" with `is_excluded` — that would make a returned file's row stay
hidden forever, which is the opposite of correct.

**A visibility-fence gap this surfaced, caught by a failing test rather than by review:** the first
implementation pass only added the `is_missing=0` filter to `get_excluded_books()`. Running the test
suite immediately afterward failed on `get_visible_book_count()` — it still counted a missing book
as visible, because `is_deleted=0 AND is_excluded=0` is a pattern repeated across SEVEN separate
queries in `db.py` (`get_all_books`, `get_visible_book_paths_under`, `get_visible_book_count`,
`has_books_with_progress`, `has_finished_books`, `get_finished_book_data`, `get_all_cover_paths`)
plus an eighth, identically-shaped check in `ui/tag_manager.py`'s `_is_archived` (found by grep, not
by the test — a different quote style than the others, so a naive grep for the exact `is_deleted = 0
AND is_excluded = 0` string missed it on the first pass too). **Lesson: when adding a new flag that
needs to participate in an existing "is this visible" contract, grep for every occurrence of the
existing fence pattern across the WHOLE codebase, not just the one query you're directly touching —
and confirm the count with a test, not by inspection, since this exact gap survived one round of
manual review and was only caught by `assert db.get_visible_book_count() == 1` failing with `2`.**

**Accepted edge case, not fixed:** a book can be both `is_excluded=1` AND `is_missing=1` (the user
trashed a book that was already missing, or trashed it before it was ever discovered missing). While
missing, it's correctly hidden from the popup. When the file returns and a force rescan runs,
`is_missing` self-heals (clears) but `is_excluded` stays sticky — so the book reappears in the
*popup* (now visible again since `is_missing=0`) but not the library, with no proactive notification
that this happened. The user could plausibly forget the book existed and wonder where a "newly
returned" file went. Explicitly accepted as out of scope — no notification mechanism was built.

---

## Excluded Books list wouldn't expand inside the settings panel — five inline approaches failed before a MainWindow-level popup (ChapterList's architecture) fixed it (2026-06-27)

**Symptom:** a toggle line ("N books excluded ▼") in the Library settings tab was meant to expand
an inline list of restorable books below it. Across five distinct implementation attempts, the
list either silently failed to grow past ~0px, caused the entire Library tab to visibly drift
(other widgets resizing to compensate), flickered, or rendered nothing at all despite every
programmatic check — geometry, `isVisible()`, stylesheet, row content — reporting correct.

**Root cause:** `settings_panel` (`main_window_builders.py` `build_settings_panel`) is a **fixed
500px height** widget, and the Library tab page has **no `QScrollArea` of its own** (unlike
`StatsPanel._build_overall_tab`, which wraps its content in one as a safety net — not adoptable
here per explicit product decision that no panel should have a scrollbar). Any widget inside that
tab trying to grow taller than the tab's already-fully-claimed vertical budget has nowhere to put
the extra height — Qt either refuses to allocate it (if the growing widget's effective size
policy/sizeHint doesn't force it) or steals it from a sibling with a flexible size (causing visible
drift elsewhere in the tab).

**What was tried and reverted, in order** (full detail with code patterns in SESSION.md
2026-06-27 Session 2 — kept brief here):

1. `QScrollArea.maximumHeight` animated alone, default `Expanding` policy → did nothing
   (`QScrollArea.sizeHint()` is ~`(0, 4)` regardless of content; with no sibling stretch to absorb
   slack, the layout granted it ~0px rather than growing it).
2. `minimumHeight` driven in lockstep with `maximumHeight` (via a custom `Property`) → genuinely
   grew the list, but the tab had no spare budget, so it stole space from the folder-list box and
   visibly drifted the whole tab every animation frame.
3. Header+toggle merged onto one row + `QSizePolicy.Fixed` on the scroll area → drift became a
   flicker (`Fixed` sizes from `sizeHint()` clamped to min/max, not `maximumHeight` alone, so it
   fought itself without `minimumHeight` also driven — and adding that back changed nothing
   further, by this point with no further user-visible effect).
4. Absolute-overlay positioning (`setGeometry`/`show()`/`raise_()`, no layout at all) **as a child
   of the section widget itself** → every programmatic check passed; nothing rendered live, in
   either this session's testing or an independent attempt by a different model (Gemini) given the
   same approach to fix.

**The actual fix:** stop trying to grow anything *inside* the Library tab's layout at all. Rebuilt
as `ExcludedBooksPopup` (`ui/excluded_books.py`), parented directly to `MainWindow` — copying
`ChapterList`'s (`ui/chapter_list.py`) already-proven architecture exactly: `QGraphicsOpacityEffect`
fade only (no size/height `QPropertyAnimation` at all), `show()`/`raise_()`/`setGeometry()` called
synchronously from the click handler, `QTimer.singleShot(0, ...)` for focus. Because the popup is
never a descendant of the tab's `QVBoxLayout`, nothing in that layout is ever asked to renegotiate
space for it — it floats above everything, the same way `ChapterList` floats above the player
chrome. `ExcludedBooksSection` (the toggle line) stayed inside the tab; only the *list itself*
needed to leave.

One concrete bug inside the fix worth flagging for future similar work: the first popup version
used a `_TOP_MARGIN` constant copy-pasted from `ChapterList`, which opens *upward* and reserves
clearance above itself. This popup opens *downward*, so that same constant — subtracted from the
available-height calculation — was reserving clearance in the wrong direction and silently
starving the list down to fitting only 1 row. Renamed to `_BOTTOM_MARGIN` and applied on the
correct side once that direction mismatch was caught via live user testing.

**Process lesson — do not skip:** every one of attempts 1–4 was "verified" via headless Python
scripts (`processEvents()` loops, manual `QPropertyAnimation.setCurrentTime()`, synthetic
`QMouseEvent` delivery, even a same-process `MainWindow()` instantiation with the settings panel
never actually opened through its real animated entry path). Every single one of those scripts
reported success or at least "looks plausible" at some point in this arc, including for the fully
broken attempt 4. None of that matched what the user actually saw. For settings-panel/tab-layout
visual bugs specifically: do not trust headless geometry/visibility assertions as a substitute for
having the user check the live, actually-opened panel — the gap between "this script says it's
fine" and "the real app does this" was the single biggest time cost in this session.

---

## `_on_book_removed` nulled `_current_book` before calling `session_recorder.close()`, silently discarding every active session on book/path removal regardless of duration (2026-06-25)

**Symptom path:** any removal of the currently-playing book — scan-location removal
(`library_controller.py` `_on_remove_locations_clicked` → `app.on_book_removed`), the book-detail
trash button (`_on_book_detail_removed`), or a confirmed-missing file (`_mark_book_missing`) — all
funnel into `app.py`'s `_on_book_removed`. The original ordering was:

```python
self.current_file = ""
self._current_book = None
self.session_recorder.close()
```

**Root cause:** `SessionRecorder` is constructed with `get_book_fn=lambda: self._current_book`
(`app.py`, `SessionRecorder(...)` call site). `close()` reads the book through that lambda via
`book = self._get_book()` and gates the entire flush on `listened >= 60 and book is not None`. By
the time `close()` ran, `_current_book` had already been set to `None` two lines above — so `book`
was always `None` and the `else` (discard) branch fired unconditionally, independent of how long
the session had been open. This was *not* the documented 60s-threshold behavior (sub-60s sessions
intentionally discard on every close path, voluntary or not — that part is correct and untouched);
this was the book-validity half of the same `and` guard failing every single time, silently
dropping sessions of any length, including multi-hour ones.

**Why it went unnoticed:** the discard path only prints to stdout
(`"[close_session] discarded — listened={listened:.0f}s < 60s threshold"`), and that log line is
misleading in this exact failure mode — `listened` was correctly accumulated and often well over
60s; the message just doesn't distinguish "discarded because too short" from "discarded because no
book," since the `book is not None` half of the guard isn't mentioned in the print at all.

**Why the checkpoint didn't backstop it:** the 30s `session_checkpoint.json` exists for crash
recovery, but `_on_book_removed` returns normally (no crash) and a subsequent graceful app exit
calls `clear_checkpoint()` synchronously in `closeEvent`, deleting it before the next startup could
ever recover it. The checkpoint only helps when the process dies before a clean `close()`/
`clear_checkpoint()` pair runs — it was never going to catch this.

**Fix:** reorder so `close()` is called while both `_current_book` and `current_file` are still
valid, and the player is still live (`terminate()` runs later in the same method, unchanged):

```python
self.session_recorder.close()
self.current_file = ""
self._current_book = None
```

`close()`'s own internal `_get_position()` read also depends on the player still being attached —
this ordering fixes both the book-validity guard and keeps the position read correct, in one move.

**Test added:** `tests/test_session_recorder.py` — constructs a real `SessionRecorder` (needs a
`QApplication` for its `QTimer`s) against a fake DB, and pins two cases: a valid book + ≥60s
listened flushes exactly one `write_session` call; a `None` book at close time discards even at
≥60s (freezing the bug's exact shape, not endorsing it — it documents why the call must happen
before the book is nulled, not that `None`-book discard is itself desirable behavior).

**Scope explicitly not changed:** the 60s threshold itself, `close()`'s signature, every other
`session_recorder.close()`/`.pause()` call site. This was purely an ordering bug in one method.

---

## Library cover thumbnails looked "pretty much the same" after a discovery + resampling fix — the real bottleneck was the paint-time downscale, not the source (2026-06-24)

**Starting complaint:** small grid thumbnails (3-per-row/Square, ~88-96px cells) had crumbling
cover text. User compared against The StoryGraph at a similar thumbnail size and confirmed the
size itself wasn't unusual — this was a resampling-quality question, not a "we're doing the size
wrong" one.

**Two real, independent bugs found and fixed first, both in `scanner.py`'s `_extract_metadata`:**

1. **Cover discovery only matched exact filenames** `cover`/`folder`/`front`/`art` (case-insensitive
   stem). 98% of the library was silently falling back to tiny embedded MP3/M4B tag art instead of
   available high-res external cover images. Fixed with a fallback: if no name match and the folder
   has exactly one image file, use it (almost certainly the cover, just unconventionally named); if
   multiple unmatched images exist, leave unset and fall through to the embedded-tag path rather than
   guess. Verified via a live survey of the real 380-book library DB: match rate rose from 8/380 (2%)
   to 354/380 (93%).
2. **Thumbnail resampling was `Qt.SmoothTransformation` (bilinear) into a no-quality-argument JPEG
   (~75 default) capped at 226×344** — both lossy and, on HiDPI, already short of the largest grid
   cell's real pixel needs. Replaced with a PIL pipeline: `QImage.convertToFormat(Format_RGBA8888)`
   → `Image.frombuffer` → `Image.Resampling.LANCZOS` to a 320×480 cap → `.convert("RGB")` →
   `.save(..., "JPEG", quality=88, optimize=True)`. New cache dir `thumbnails_v2` (old `thumbnails/`
   left orphaned on disk, never deleted — mixed-library safety).

**Both fixes landed, force rescan run — user reported "Made no difference."** This was not a
re-test-it-and-see situation: the user had old thumbnails saved locally and did an actual
before/after comparison, twice, and was right both times. The first time I'd claimed success off
metadata alone (resolution, filename match) without doing a real pixel comparison — wrong. The
second time I mischaracterized an aside the user made about Dolphin-file-manager-vs-app rendering
softness as if it were in-app evidence of a regression — the user had explicitly said Dolphin
doesn't matter, and called this out sharply. Both of those are logged in case the pattern repeats:
**when the user says "no difference," verify pixel-for-pixel at the real render size before
re-asserting anything — don't lean on file size/resolution proxies, and don't reframe an aside as
evidence for a claim the user didn't make.**

**Actual root cause:** the discovery + resampling fixes only improve the *source* thumbnail
(226×344 → 320×480, bilinear → LANCZOS). They never touch the *paint-time* step —
`BookDelegate._draw_cover`'s `painter.drawPixmap(rect, cover, src_rect)` — which still does one
more Qt bilinear downscale from the cached thumbnail down to the actual grid cell size (as small as
~88×88 up to ~292×159 depending on view mode). Feeding that final bilinear step a sharper, larger
source doesn't survive the step itself. Confirmed by simulating both old and new cached thumbnails
downscaled to real cell sizes with PIL `BILINEAR` (matching Qt's behavior) and visually comparing —
they were, as the user said, pretty much the same.

**Fix: pre-render per-cell-size pixmaps so paint time becomes a near-1:1 blit.** Added to
`BookDelegate` in `library.py`:
- `_sized_cover_cache: dict` (instance state, not the module-level `_cover_cache`) keyed by
  `(book_id, device_w, device_h)`.
- `_get_sized_cover(book, cover, target_w, target_h)` — lazily builds and caches a pre-scaled
  pixmap bounded to the target size (device-pixel-ratio aware), called from `_draw_cover` before
  its existing square/crop/letterbox branching. Deliberately a plain aspect-preserving bounded fit
  (NOT `KeepAspectRatioByExpanding` to the cell) — those branches derive their own crop/inset math
  from the source pixmap's real proportions, so over-cropping here breaks letterbox specifically.
  Only shrinks; never upscales a smaller source.
- `_lanczos_scale(cover, w, h)` — the actual resize, via the same PIL round-trip as the scanner fix
  (`Format_RGBA8888` before `constBits()`, same packing requirement and corruption risk if reordered).
- `evict_sized_cover(book_id)` wired into `LibraryPanel.evict_cover` and `refresh_book_cover` so a
  replaced/refreshed source cover doesn't leave stale pre-scaled entries behind. View-mode switches
  don't need eviction — the cache key already includes target size, so old-size entries just become
  unused, same low-volume staleness as the existing `_placeholder_cache`.

**Verified properly this time** — not metadata, actual pixel comparison at real cell size (96×146,
the 3-per-row dimension), both via a synthetic text image and a real cached cover ("Under Heaven").
Old bilinear-paint-time path vs. new pre-scaled-LANCZOS path: text was visibly, measurably sharper
in the new path on both. Then confirmed against the live app by the user directly.

**Second-round finding: plain LANCZOS swap measurably improved text but lost contrast/"punch" on
flat-color graphic covers** (SF Masterworks-style art was the clearest case — user's own framing:
"the same trade-off as the Dolphin vs app test — you lose crispness if it becomes more legible").
Real effect, not a regression in the new code: bilinear's edge ringing/overshoot was incidentally
reading as punchy contrast; LANCZOS is more correct and doesn't do that. Added a PIL `UnsharpMask`
pass after the LANCZOS resize in `_lanczos_scale`, RGB channels only (alpha untouched, so transparent
cover edges aren't affected). First attempt at `radius=1.0, percent=60` overshot — user's words:
"out of focus, then we slapped an HDR filter on it to salvage it," with visible haloing on
photographic gradients (skies, faces) where LANCZOS leaves no real edge for the mask to find, so it
amplifies noise instead. Settled on `radius=0.8, percent=25` — confirmed by the user to keep the
text legibility gain without the cartoonish/HDR look. **Any future change to this sharpen strength
must be re-checked against a photographic cover, not just a flat-color graphic one — the latter
tolerates much more sharpening before artifacts become visible**, which is exactly how the first,
too-strong value got picked without anyone noticing on the graphic-art test case alone.

**Scope note:** this only touches the library grid/list thumbnails (`BookDelegate` in `library.py`).
The main player view's cover (`cover_art_label`, `_update_cover_art_scaling` in `app.py`) is a
separate code path and was not part of this change.

## `book_info_layout` 2px centering drift: missing `setSpacing(0)`, not an icon/font/style issue (2026-06-23)

**Symptom:** the volume slider, sleep-timer countdown label, and new muted-volume icon — all three
pages of the `vol_stack` `QStackedWidget` — read as shifted right relative to the play button and
the chapter name label above them. Visually subtle (a few px) but real, confirmed by the user with
two identical squares drawn in an image editor and placed against each widget's own left/right
margins.

**Wrong diagnoses tried first, in order, each disproven before moving to the next:**
1. The muted icon's SVG had an asymmetric `viewBox` (`viewBox="-3.5 0 24 24"`) — measuring the
   rendered glyph's bounding box at high resolution showed it was in fact centered within ~1%, so
   this wasn't the cause. A "nudge the icon a few px left" workaround was applied anyway (tuned by
   eye to 6px, since the *layout* bug was still present and uncorrected at that point) and later
   fully reverted once the real fix landed — see below.
2. "Optical centering" (the icon's solid speaker body reads as visually heavier than its thinner
   left side, even with a centered bounding box) — plausible-sounding, and the rendered icon really
   does look asymmetric at small sizes, but this was the wrong explanation: it doesn't explain why
   the volume *slider* and the sleep *label* — both completely different render paths with no
   shape-weight component — showed the exact same rightward drift.
3. `QPushButton` (the sleep-timer label) text-centering quirks under Fusion style, stylesheet
   specificity, `SE_PushButtonContents` content-rect margins — multiple isolated PySide6 scripts
   were built to test `QStyleOptionButton`/`subElementRect`/raw pixel renders of the button alone,
   and every one of them came back correctly centered. This was real evidence, but it was evidence
   about a synthetic reconstruction, not the actual running app — the gap between the two turned out
   to be the actual bug.

**Root cause:** `book_info_layout` (`main_window_builders.py`, the row containing
`current_time_label | vol_stack | total_time_label`) never called `setSpacing(0)`, so Qt's default
inter-item spacing (Fusion style default, several px) was inserted at every gap between consecutive
layout items — including the two `addStretch(1)` spacer items flanking `vol_stack`. Spacer items and
real widgets don't necessarily get identical treatment from the default spacing in every Qt layout
configuration, and the net effect measured here was a 4px asymmetry: `vol_stack`'s left margin from
the window edge measured 100px, its right margin measured 96px (confirmed via real `QWidget.geometry()`
and `mapTo()` dumps from a temporary debug keypress handler in `app.py`, not from any isolated
synthetic script). The sibling `chapter_info_layout` row (which centers "Chapter 1" correctly, and
was the reference the user kept comparing against) has only 3 items with the centered widget itself
stretching — no `addStretch()` spacer items at all — so it never hit this asymmetry.

**Fix:** `book_info_layout.setSpacing(0)`, plus adding a matching `addStretch(1)` before
`current_time_label`'s sibling `vol_stack` (previously there was a stretch only *after* `vol_stack`,
left-packing the row instead of centering it) — see
[main_window_builders.py:401-407](src/fabulor/ui/main_window_builders.py#L401-L407). Confirmed fixed
via the same debug-geometry dump: `vol_stack` now sits at x=98 with a symmetric 98px margin on both
sides of a 300px window. The muted-icon nudge workaround from diagnosis #1 was removed entirely once
this landed — the icon needed zero compensation once the real layout bug was fixed.

**Lesson for future layout-centering bugs:** when a `QHBoxLayout` mixes `addStretch()` spacers with
real widgets and a row reads as off-center by a small, consistent amount, check `setSpacing()` on
that specific layout before suspecting the painted content (icons, fonts, button styles) — and when
synthetic reconstructions keep disagreeing with a user's direct visual report, get real
`geometry()`/`mapTo()` numbers from the running app rather than continuing to refine the
reconstruction. A temporary keypress-triggered debug dump (this session used `G`, removed after the
fix) is fast to wire up and far more conclusive than re-deriving Qt's layout math by hand.

---

## StreakGrid gutter labels: both descender clipping ("Aug") AND left-edge first-letter clipping ("Jan"/most months) fixed by the same band-height change (2026-06-22)

**Symptom:** Two distinct-looking clips on the `StreakGrid` left-gutter row labels turned out to
share one fix. (1) Descenders clipped vertically — e.g. "Aug 28" cut off at the bottom of the "g".
(2) The left-edge first-letter clip — e.g. "Jan 01" → "an 01" — an offscreen sweep across all 12
months suggested this affects most months, not just "J" ones (Sep, Aug, May, Apr, Nov, Oct appeared
to lose their first letter the same way; "Jul" looked like the one exception in that sweep).

**Root cause:** the label rect (`QRect(0, y, GUTTER_W-3, CELL)`, `Qt.AlignVCenter`) only spanned a
single 14px cell row, but labels are drawn only every 3rd row (`drawn = range(0, N_ROWS, 3)`) — each
visible label visually "owns" the unlabeled rows below it too, down to the next label (3 cells, or 2
for the last band, since `N_ROWS=26` isn't a multiple of 3). Squeezing the label into one 14px row
left it cramped on both axes — vertically against descenders, and apparently tight enough that
`Qt.AlignRight`'s left-side overflow also reached the widget edge more readily than once the rect
had more room.

**Fix:** compute each label's owned band height from its row to the next label's row
(`band_h = (next_r - r) * CELL + (next_r - r - 1) * GAP`), anchor with `Qt.AlignTop` instead of
`Qt.AlignVCenter`, with a small calibrated vertical offset (`y - 1`, tuned against two rounds of
live visual feedback: first `+2` margin from band top, then `-2`, settled at `-1` net from the
original `y`). See [stats_panel.py:1757-1771](src/fabulor/ui/stats_panel.py#L1757-L1771). Confirmed
fixed live, on the real running app, for both the descender clip and the left-edge first-letter
clip across multiple months — no further gutter-label work outstanding.

Caveat for future offscreen verification of this widget: an offscreen render taken after this fix
still showed the left-edge clip in a quick scripted check, but it did not reproduce on the real
app — same divergence already seen earlier this session with the sidebar margin fix (offscreen
render and the live app disagreed there too). The offscreen month-sweep script is still useful as a
coarse regression check (loop `date(2026, month, day)` across all 12 months, call
`StreakGrid.set_data({}, {...}, set(), d)`, render to `QPixmap`, crop to the gutter region) for
catching gross regressions like wrong band assignment or rect math, but its pixel-level clipping
verdict should not be trusted over a live visual check on real fonts/DPI/rendering stack.

---

## HourlyHeatmap top date labels: "J" clipped — fixed; several intermediate approaches tried and reverted (2026-06-21)

**Symptom:** In the Stats panel's Timeline tab, both views had a "J" clipping bug. `HourlyHeatmap`'s
rotated top date labels showed "un 19" / "un 20" / "un 21" instead of "Jun 19" / "Jun 20" / "Jun 21"
— originally on the rightmost (most recent) column only; `StreakGrid`'s left-gutter row labels
showed "un 21" / "ul 20" instead of "Jun 21" / "Jul 20". This is a continuation of the unresolved
2026-06-10 NOTES.md entry "Timeline header date labels — 'J' glyph clipped at top edge", whose
fix (`QRect(2, -CELL, DATE_LABEL_H, CELL*2)`, doubling the rotated rect's height) turned out to
only fix the *non-rightmost* columns — the rightmost column has a second, independent clip source
that the 2026-06-10 fix didn't touch.

**Root cause (heatmap, rightmost column only):** the doubled rect height (`CELL*2=28`, centered at
`y=-CELL`) needed by the 2026-06-10 fix made the rotated rect's far edge extend past the widget's
own right boundary for the last column only — `wx_max = (HOUR_LABEL_W + col*(CELL+GAP) + CELL//2 +
2) + CELL`, which for `col=N_DAYS-1` exceeds the fixed widget width by ~8px. Qt clips painting at
the widget boundary regardless of the QRect passed to `drawText` (the QRect only controls
alignment/wrapping, not a hard clip region) — so the "J" of the rightmost label(s) is cut by the
widget edge, not by the rect. Every other column has a following cell's width to absorb that same
~8px overhang, so only the last column showed it.

**Root cause (StreakGrid gutter labels, "Jun 21" / "Jul 20"):** unrelated mechanism, same visual
symptom. The row-date rect is `QRect(0, y, GUTTER_W-3, CELL)` with `Qt.AlignRight` — Qt anchors the
text's **right** edge to the rect's right edge; the "Mon DD" string (e.g. "Jun 21", advance ~35px at
9pt) is wider than the 29px rect, so the string's left side already extends past `x=0` for every
label in the 14-day cycle (confirmed via `QFontMetrics.boundingRect` on all 9 labels — all had
negative left bounds). For most letters that overflow is invisible: `boundingRect.x()` being
negative is normal side-bearing whitespace with no dark pixels there. "J" is the exception — its
descender hook is real ink sitting in exactly that overflow band, so it alone gets clipped at the
widget's left edge (`x=0`) while "May 10", "Mar 29", etc. render fully despite the same or larger
nominal overflow.

**Approaches tried and reverted for the StreakGrid gutter (all confirmed bad, in order):**
1. **Widen the rect's right edge** (`GUTTER_W+3` instead of `GUTTER_W-3`) to shift the whole
   AlignRight-anchored string rightward, off the left boundary. Fixed "Jun 21"/"Jul 20" in isolated
   testing, but in the real app — where active/listened cells render at high opacity — the shifted
   text's *right* edge now reached into the first grid cell column (`x=32`) and got visibly
   overpainted by the opaque cell fill ("Jun 2" with the "1" eaten). Moving the anchor only relocates
   which end of the string clips; the string is wider than the available 0–32px slot at 9pt
   regardless of where it's positioned.
2. **Shrink font to 8pt (rect unmoved).** Verified-by-math first (wrongly) as sufiscient; in an actual
   render it still clipped "Jun 21" → "un 21" — the earlier ink-bound calculation for 8pt had been
   conflated with a combined "8pt + shift" case, not 8pt alone. 8pt alone was not enough margin.
3. **Shrink font to 7pt (rect unmoved).** This one *did* render every label fully with no clipping
   and no cell overlap (verified via `tightBoundingRect`/`boundingRect` math and an offscreen
   render) — but the user rejected it on sight as illegibly small, with too much resulting dead
   whitespace in the gutter. **Deferred** — needs a different approach (e.g., a shorter date format
   at a readable size, or restructuring the gutter) the next time this is picked up. Do NOT default
   back to shrinking this font as "the fix" without re-confirming legibility first.
4. **User then fully reverted the gutter changes.** StreakGrid's "Jun 21"/"Jul 20" clipping is
   UNFIXED and deferred — see TODO.md.

**Approaches tried and reverted for the HourlyHeatmap rightmost column (in order):**
1. **Widen the whole widget by `+CELL`** (`_update_size`: `w = HOUR_LABEL_W + N_DAYS*(CELL+GAP) +
   CELL`). Fixed the rightmost-column overflow in isolation, but violates the hard constraint that
   `HourlyHeatmap` and `StreakGrid` must stay pixel-identical in size (242×448) for the
   heatmap↔streak `TasselOverlay` transition to align cell-for-cell — reverted.
2. **Shrink the rotated rect's height from `CELL*2` down to a tightly-measured ~16px** (instead of
   widening the widget) — this approach did NOT regress to the pre-2026-06-10 bug as long as the
   measured worst-case ink height (~15px across all "Mon DD" labels at 11pt, via
   `QFontMetrics.tightBoundingRect`) still fits with margin. Combined with also changing the
   rotation anchor from `cx+2` to `cx`, this brought the rightmost column's overflow to exactly 0 in
   calculation — **the user then independently reverted this entire session's changes before this
   approach was committed**, so it is NOT the shipped fix; recorded here only so it isn't
   re-investigated as if it were untried.

**Shipped fix (heatmap only):** kept the original `CELL*2`-tall rect and the original widget size
(both untouched), and instead shifted only the rect's `y`-offset in the rotated coordinate frame
from `-CELL` to `-CELL-4` (`QRect(2, -self.CELL - 4, self.DATE_LABEL_H, self.CELL * 2)` at
[stats_panel.py:1052-1057](src/fabulor/ui/stats_panel.py#L1052-L1057)). After `rotate(-90)`, the
rect's local +y axis maps to widget **-x** (leftward); increasing the magnitude of the negative `y`
offset by 4 shifts every rendered label 4px left in widget space, off the widget's right edge for
the last column, without touching `cx` (the cell-anchor x, shared with cell positions), the hour
labels, or the widget's overall size. (An initial pass shifted by `-5`; the user visually confirmed
that overshot by 1px and asked for `-4`.) Verified via offscreen render: no clipping on any column
including the rightmost, and the labels no longer encroach on the cell grid. The `StreakGrid` gutter
clip is a **separate, still-open bug** — see TODO.md — do not assume this fix also covers it; the
two labels live in different widgets with different alignment/rotation mechanics.

---

## Session recorded twice on graceful app close (2026-06-21)

**Symptom (user-reported):** closing the app while a listening session is active records that
session **twice** in `listening_sessions`. It records correctly (once) when force-killing the
process, when the 3-minute pause timeout fires, or when loading another book mid-session.

**Root cause — a daemon-thread-vs-checkpoint race.** `SessionRecorder` writes a crash-recovery
checkpoint (`session_checkpoint.json`) every 30s while a session is live; on startup,
`_recover_checkpoint()` re-writes any checkpoint with `listened >= 60`. In the original
`close()`, the DB write **and** the checkpoint `unlink` both happened inside the `_write` closure
running on a **daemon** thread. `closeEvent` called `close()` then immediately `event.accept()`,
and the process tore down. Daemon threads are killed on process exit — so the in-flight `_write`
typically *completed its DB write* (the row landed: copy #1) but never reached the `unlink`. The
checkpoint survived on disk, and the **next startup's `_recover_checkpoint()` re-wrote the same
session** (copy #2, with a fresh `session_end`).

Why only the graceful-close path:
- **Load another book / 3-min timeout** — `close()` runs but the app keeps running, so the daemon
  thread completes the `unlink` before any restart; checkpoint gone, no duplicate.
- **Force-kill** — no `closeEvent`, so `close()` never runs; the session is written only once, by
  recovery on the next startup.

Only graceful close left *both* a landed DB write *and* a surviving checkpoint.

**Fix — two independent guards, because the duplicate and a potential lost-write are different
failure modes:**
1. The checkpoint `unlink` was removed from the `_write` daemon closure entirely and moved into a
   new synchronous `SessionRecorder.clear_checkpoint()`.
2. `close()` now builds the flush thread into a **local** (not `self._flush_thread` — avoids
   unnecessary shared state) and returns it (`None` on the sub-60s/no-book discard branch).
   `closeEvent` does: `t = close(); if t: t.join(timeout=0.5); clear_checkpoint(); event.accept()`.

The join gives the DB write a bounded chance to land; the **unconditional** synchronous
`clear_checkpoint()` makes the duplicate impossible regardless of how the join resolved. Critically,
the clear must *not* live inside `_write` after the DB write (its original spot) — if it did, a
join *timeout* could leave the thread killed after the write committed but before the unlink,
resurrecting the exact bug. Ordering is load-bearing: `join → clear_checkpoint → event.accept()`,
all before `accept()` (the point of no return).

**Branch table (every case pinned):**

| Join outcome | Write landed? | Result |
|---|---|---|
| Completes (normal) | yes | checkpoint cleared → exactly one row |
| Times out (DB stalled) | yes | checkpoint cleared anyway → one row, no duplicate |
| Times out (DB stalled) | no | checkpoint cleared, no row → session lost |

The third row is the only loss case and is reachable only if a **single-row** WAL insert exceeds
500ms — i.e. the DB is locked/broken, where losing one session row is the least of the problem. The
DB uses `journal_mode=WAL` with `synchronous` at its WAL default `FULL` (fsync per commit), which
is routinely sub-millisecond for one row; 500ms absorbs an occasional fsync spike under disk
pressure with comfortable margin. (Orthogonal lever if it ever proves marginal:
`PRAGMA synchronous=NORMAL`, safe under WAL — not done.) `losing-at-worst` beats `duplicating`; the
prior behavior was a *guaranteed* duplicate.

The recovery path's own `unlink` (`finally` in `_recover_checkpoint`) is unchanged — it runs at
startup while the app stays alive, so its daemon thread completes normally.

**Files:** `session_recorder.py` (`close()` returns the thread, no inline unlink; new
`clear_checkpoint()`), `app.py` (`closeEvent`).

---

## Streak count / grid cell mismatch (2026-06-19 Session 4)

**Symptom (user-reported):** while testing different `day_start_hour` settings, the streak grid's
lit-cell count and the displayed streak number disagreed. Concretely: a session running
04:53→06:02 on 2026-06-10, `day_start_hour` 5 or 6. The session's adjusted start-date is 06-09
(04:53 falls before the 5am/6am boundary) and its adjusted end-date is 06-10 (06:02 falls after
it) — so the session was genuinely listened to across parts of *both* adjusted-days.

**First diagnosis (wrong, reverted):** assumed the streak grid was the bug, on the theory that the
Day tab and `get_active_periods` are start-date only, so the grid (which lights a cell on EITHER a
session's start OR end adjusted-date) should be made start-only too, "to match." This was
implemented, then the user caught the actual intent before it landed: **the grid was correct.** A
session spanning the day_start_hour boundary really was listened to on both of those adjusted-days
— lighting both cells reflects reality, the same way a session spanning real midnight should light
both calendar days. The Day tab intentionally shows it as one entry on its start-date only (see
"Day/Week/Month session-splitting, scoped out" below) — that's a deliberate, different design
choice for that view, not a bug to be reconciled by changing the grid. The grid-only-start-date
change was fully reverted (`build_streak_grid_cache`, `_update_streak_grid_cache_for_date` both
restored to their original start∪end behavior).

**Actual root cause:** `get_streaks` (which computes the streak NUMBER/label, not the grid cells)
builds its day-set from `get_active_periods('day', ...)` — start-date only, by design, since
`get_active_periods` also drives the Day/Week/Month period navigator and must stay start-only
there — plus a separate finished-event query. It never unioned session **end**-dates. So for a
session spanning the boundary, the grid correctly lit two cells, but `get_streaks`'s day-set (and
therefore the streak count) only ever credited the start-date — undercounting relative to what the
grid visibly showed. This is exactly the cross-check invariant already documented in CLAUDE.md
("`StreakGrid` cross-checking its longest run against `get_streaks()['longest']`") — the two paths
had drifted because an end-date source was present in one (the grid) and absent in the other
(`get_streaks`).

**Fix:** added a session_end-date query directly inside `get_streaks` (NOT inside
`get_active_periods` — that function's start-only contract is load-bearing for Day/Week/Month nav
and must not change) and unioned its results into `active_set`, alongside the existing
session-start set (from `get_active_periods`) and the finished-event set. `get_streaks`'s day-set is
now built from the same three sources as `build_streak_grid_cache` (start, end, finished) — start
and end via separate queries since `get_active_periods` can't be reused for the end-date half
without breaking its start-only contract elsewhere.

**Verification:** scripted repro — write one session 04:53→06:02, rebuild the grid and call
`get_streaks` at `day_start_hour` 4/5/6. At 5 and 6 (where the session spans the boundary), both
the grid's lit-cell count and `get_streaks()['longest']` now read 2; at 4 (where the whole session
falls after the boundary, no spanning) both read 1. Matched exactly at all three offsets after the
fix; before the fix `get_streaks()['longest']` read 1 at all three offsets regardless of how many
cells were actually lit.

**Day/Week/Month session-splitting — considered, scoped out:** the same boundary-spanning session
also raises the question of whether the Day tab should show it on both adjusted-days too (split
proportionally, the way the Hourly Heatmap already splits sessions across clock-hour cells). This
was deliberately NOT done: it would require splitting `listened_seconds`, `position_start`/
`position_end`, `furthest_position`, and the per-book `is_finished` flag proportionally across two
rows, touching `get_daily_book_breakdown`'s aggregate `SUM`/`MAX` columns, the Book Detail Panel's
per-book stats grid, and the delete-session/delete-book-stats cascade (deleting one half of a split
session would need to correctly re-derive both affected days). Large blast radius for a genuinely
rare case (only sessions that straddle the configured `day_start_hour`, not all spanning sessions).
The Day tab stays start-date-only by design; a spanning session shows as one entry, attributed to
its start day, with its full (unsplit) duration and position range — same as before this session's
fixes, unchanged.

**Lesson:** before "fixing" a discrepancy between two views that are SUPPOSED to represent different
granularities of the same data (a coarse "did I listen at all that day" grid vs. a precise per-book
Day-tab listing), confirm which one is actually wrong by reasoning about what real listening
behavior should produce — not by assuming the two should always show identical numbers. The
correct fix here was almost the opposite of the first instinct: bring the under-counting path
(`get_streaks`) up to match the correct one (the grid), not bring the grid down to match the
under-counting Day tab.

## TasselOverlay: dangling tassel design iteration (2026-06-19 Session 3)

**Goal:** make the Timeline bookmark tab feel like a real bookmark by adding a decorative
dangling tassel — cord + bound head + fringe — that sways. New animation category for this
codebase (no prior rotation/curve-based or perpetual-idle animation existed anywhere; everything
else is position/opacity/color `QPropertyAnimation` or state-gated repeating `QTimer`s).

**Round 1 (built under a full plan-mode design — see the now-resolved plan file): "pendulum with
a circle," not a tassel.** The first implementation drew a single straight cord ending in a plain
filled circle, floating to the *side* of the tab like a clock pendulum. Two real problems, both
caught immediately on the first screenshot: (1) a tassel has three visually distinct parts — cord,
a bound "head" knot, and a fanned fringe of threads — not a dot; reference photos make this
unambiguous. (2) `setCursor(PointingHandCursor)` was applied to the WHOLE widget in `__init__`, so
the hand cursor appeared over dead/empty space (the swing area) where clicking did nothing — a
real UX bug, not a cosmetic one. **Lesson:** "this beats physics" / "circle ≠ tassel" feedback
meant the shape itself was wrong at a structural level, not just under-detailed — redrawing more
detail onto a circle would not have fixed it; the anatomy needed rebuilding from reference images.

**Fix for round 1's issues — `_in_hit_region()`.** A single property is now the SOLE source of
truth for both `mousePressEvent` (click) and a new `mouseMoveEvent` (cursor): `tab_rect.contains(pt)
or tassel_rect.contains(pt)`. `mouseMoveEvent` calls `setCursor`/`unsetCursor` based on the same
test, so the hand cursor can never show over a region where clicking is a no-op. `tassel_rect` is a
*tight* box around the resting tassel body (head + fringe + sway slack) — NOT the full widget
bounding box — so the empty corners between the tab and the tassel (and above/right of the tassel)
correctly do NOT show a hand or accept clicks. Fixed at the rest position (not tracking the live
sway) so the clickable region doesn't move under the pointer.

**Round 2: cord geometry, two sub-rounds.** A tassel's cord isn't taut — it drapes/loops (visible
in every reference photo: the cord visibly loops through the bookmark hole before reaching the
knot). (2a) First attempt used a quadratic Bezier with the control point only modestly offset —
read as "goes straight" / "pretty much the same thing" even after changing to a cubic, because both
cubic control points were placed *below* the anchor with only a small horizontal offset: the curve
never swung out far enough past the head's x-position to read as a loop rather than a slightly-bent
line. (2b) Second attempt fixed the bulge (control point pushed above-and-right of the anchor, the
loop's widest point) but then the curve arrived at the head *diagonally from the right*, because the
second control point was placed to the side of the head rather than above it — "bulge doesn't
align." **Fix:** the curve's approach angle at an endpoint is set by the control point immediately
before it, independent of the rest of the path — placing `c2` directly above `head_top_pt` (same x)
makes the tangent at the endpoint point straight down, so the cord visibly drops into the head
vertically regardless of how the loop bulges earlier in the path. Also shortened the drop
(`_HEAD_Y` 50→34) and pulled the head closer to the tab (`_HEAD_X`, `SWAY_PAD` reduced) per
feedback that the original proportions were too long/far. **Lesson:** when a Bezier "doesn't look
right," diagnose bulge (shape, mid-path control points) and approach angle (endpoint, the control
point closest to that endpoint) as separate, independently-tunable concerns — fixing one doesn't
fix the other, and conflating them wastes iteration rounds.

**What's preserved/unchanged throughout all rounds:** the tab's own `_tab_rect`, its 7px rest-peek,
`REST_Y`/`EXT_Y` (still derived from the original `TASSEL_H=56`), and the caller's
`.move(2, REST_Y)` in `_build_time_tab` — verified numerically at every round via a headless
offscreen-Qt script (`QT_QPA_PLATFORM=offscreen`) computing widget size, hit-region containment,
and control-point bounds before ever launching the real app. The `showEvent`/`hideEvent` timer
lifecycle was also verified empirically (not assumed) with a probe subclass mounted in a real
`QTabWidget`, confirming both `hideEvent` firing AND `isVisible()` flipping `False` on tab-switch-
away and panel-close, and both recovering on return.

## Main-window theme fade interrupt (sidebar mid-fade) FIXED; full color-animation rework DEFERRED (2026-06-19 Session 2)

**Symptom:** press `T` (theme rotate), then right-click the drag area to open the sidebar while the
fade is still running → a slider (progress and/or chapter) stays painted in the OLD theme's color
while everything else is already the NEW theme. Hard to hit deliberately, and self-corrects on the
next theme change, but real.

**Root cause (two parts, from instrumented logs).** The non-Themes-tab fade
(`_do_fade_with_slider_animation`) excludes the sliders from the overlay snapshot and instead
animates their `bg_color`/`fill_color`/`notch_color` `@Property` values from old→new. Those animations
are kicked off from a deferred `QTimer.singleShot(0, _start_color_anims)` (deferred so the new QSS has
polished first). (1) If a panel/sidebar opens in the window between the fade starting and that
deferred callback firing, the callback still runs and *re-resets* the sliders to the OLD start colors
before animating — and if the fade is then torn down, they're stranded there. (2) There was no
main-window-appropriate way to *complete* an in-flight fade on interrupt — `snap_theme_forward` exists
but is Settings-panel-oriented (it re-applies stylesheets in a way tuned for the Themes-tab preview)
and was never intended for the main window; calling it there (an earlier attempted fix) did not
resolve the stranding.

**Why the sliders specifically (not the rest of the UI).** `ClickSlider.paintEvent` paints directly
from its `@Property` colors (`self._bg_color` etc.), NOT from QSS at paint time. The new-theme colors
reach those properties only via `_apply_stylesheets` → Qt `polish()` reading the
`qproperty-bg_color`/etc. declarations in `get_player_stylesheet`. So once the fade's color animation
has overridden the `@Property` and is then stopped mid-flight, the slider keeps the stranded value
until something re-polishes it. The rest of the UI (buttons, panels, labels) reads its colors from QSS
at paint time, so it was already correct the instant `_apply_stylesheets` ran.

**Fix:** `ThemeManager.complete_main_fade()` — stops the main `_fade_anim` and any running slider color
animations, hides the overlay, unfreezes the fade labels, then re-applies the stylesheet for
`_active_display_theme`, which re-polishes the slider `@Property` colors to the correct new-theme
values (overriding whatever the stopped animation left). A new `_fade_in_flight` flag (set when a
fade starts, cleared in `_on_fade_finished` and `complete_main_fade`) ALSO guards the deferred
`_start_color_anims` so it returns early once the fade is completed/interrupted — closing the
re-strand window in cause (1). `_toggle_sidebar` (the sidebar is the gateway to every panel, and the
target of the drag-area right-click) calls `complete_main_fade()` before sliding; it's a no-op if no
fade is running. Future panel hotkeys (`l`/`s`/etc., planned) would hit the identical race and should
make the same call.

**DEFERRED — the deeper friction (full per-element color-animation rework).** The real reason theme
changes are restricted to "main window only, no panel open" is that the main-window theme transition
is a heavyweight FULL-WINDOW animated fade: an overlay snapshot of the whole window + frozen time/
chapter labels (text pinned so it can't change under the overlay and ghost) + the slider color
tweens. That heaviness is what risks morph/ghost artifacts if anything is moving (a panel sliding)
during the fade. If theme changes were *only* cheap per-element `@Property` color animations (nothing
positional, no overlay, no frozen labels), they could run freely even with a panel open — the
original desired behavior. That rework was started in a prior session and abandoned as enormous:
every QSS-styled widget (buttons and their hover/pressed/disabled states, panel chrome, the Themes-tab
pool items with their regular/underline/bold variants, gradients, cover-art-derived colors) would
need converting from QSS-driven coloring to custom-paint `@Property` coloring, because QSS pseudo-
states (`:hover`/`:pressed`/`:disabled`) have no equivalent in custom-paint land and would each be
reimplemented by hand. Rough estimate 40–80h+ with high regression risk against a system that works.
The cheaper middle path (snap panel chrome instantly while keeping slider tweens, dropping the overlay
for the panel-open case) was floated and **rejected by the user**: instant theme snaps look jarring/
violent — the overlay fade exists precisely to avoid that, and snapping would be a worse experience,
not a better one. So: the overlay fade stays; `complete_main_fade` is the pragmatic interrupt fix.

## Percentage label tween oscillation FIXED; tassel click hang FIXED; streak grid catch-up reveal added (2026-06-19)

**Percentage label oscillation — truncate-vs-round mismatch, not a timing race.** The progress
percentage label's book-load count-up animation (added 2026-06-18) animated toward
`new_val / 10`, where `new_val = int((new_progress/dur)*1000)` — `int()` truncates toward zero, so
a true value like 739.97 becomes 739, displaying "73.9%". The live 200ms tick that resumes right
after the flow instead computes `percent = (pos/dur)*100` and formats it with `f"{percent:.1f}%"`,
which *rounds* — for the same ~739.97-ish true percentage, that's "74.0%". Every book whose saved
progress's true percentage rounds up in its last digit reproduced this, consistently, every time —
not intermittently, which in hindsight should have been the tell that it wasn't a race. First
attempt was a settle-delay guard (`_pct_label_settling`, cleared 250ms after the tween finished) on
the theory that the live tick was racing the tween's completion. Confirmed wrong by testing it: the
jump was bit-for-bit identical with the delay in place. Real fix: compute the tween's end value
directly as `round((new_progress/dur)*100, 1)` in `_animate_percentage_label`, matching the live
tracker's own rounding exactly, instead of re-deriving a coarser value from the slider's truncated
`new_val`. The settle-delay plumbing was removed entirely once the root-cause fix made it
unnecessary — it's a math/formatting consistency issue, not a timing one, so no delay of any length
would have fixed it.

**Tassel click hang — caller didn't check the busy guard it relied on.** Rapid-clicking the
Timeline tassel while a heatmap↔streak transition was already running could hang the view
indefinitely (reported via screenshot: bookmark visible but frozen, both grids blank, no further
clicks doing anything). `TasselOverlay.play()` already had a `_busy` flag that correctly no-oped on
repeat clicks for the bookmark slide animation itself (added in an earlier session). But
`StatsPanel._on_tassel_clicked` called `self._switch_timeline_view()` unconditionally on every
click, regardless of whether `play()` had actually done anything that time — so every extra click
during the busy window independently kicked off another full `_switch_timeline_view()` cycle: a new
`animate_conceal()`/`animate_labels_out()` pair racing against the one(s) already in flight, another
`_show_streak_grid` flip, multiple `_seam()` closures fighting over the same grid's
`setVisible`/`set_label_progress` calls. Enough overlapping cycles left both grids hidden with no
surviving callback able to flip either back to visible — the hang. Fix: added a public
`TasselOverlay.is_busy` property (`return self._busy`) and `_on_tassel_clicked` returns immediately
if it's `True`, before touching either the bookmark or the grid transition. General lesson for this
codebase: a guard living inside one method (`play()`'s `_busy` check) does not protect a caller that
also independently triggers side effects alongside that method — the caller needs to check the same
guard itself if it wants the same protection.

**Streak grid catch-up reveal.** The newest `current - previous` day-cells (`day_index` 0 through
`N-1`, where `day_index=0` is today) now render as plain "not listened" — regardless of what's
actually in `_cache`/`_longest_dates`/`_finished` — for the full duration of the counter's leg 1
count-up to the old value and the pause that follows, via two new `StreakGrid` fields
(`_pending_reveal_days`, `_revealed_days`) checked in `paintEvent` as a `still_pending` gate. Once
leg 2 starts, cells pop in one at a time in the exact same frame as each integer increment of the
counter — both are driven by one discrete `QTimer` (`_run_streak_leg2`), not two independently-timed
animations, specifically so they can't drift a tick apart from each other. This required replacing
leg 2's previous continuous `QPropertyAnimation` tween with a stepped timer entirely. Total leg-2
duration: `raw = LEG2_BASE_MS + (sqrt(days) - 1) * LEG2_SCALE_MS`, capped at `LEG2_CAP_MS` (1200ms);
1 day lands exactly on `LEG2_BASE_MS` (250ms, matching the original single-tick feel). Per user
feedback, anything beyond `LEG2_SPEEDUP_AFTER_DAYS` (3) is further compressed: the time *past* the
3-day mark runs at `LEG2_SPEEDUP_FACTOR` (0.25, i.e. 75% faster than the raw curve for that portion
— tuned down from an initial 0.8/~20%-faster after visual testing showed it wasn't enough), so the
curve stays continuous at the boundary instead of jumping. Net effect: 9 days ≈ 565ms (was 850ms
pre-tune), 25 days ≈ 715ms, 100 days ≈ 1090ms (still under the 1200ms cap). `catch_up_streak_count`
(the panel-slide-reopen path) explicitly zeroes
`_pending_reveal_days`/`_revealed_days` before calling into the same leg-2 timer, so the grid itself
is never touched there — the established "never animate the grid on a slide-reopen" rule still
holds; only the counter shows the catch-up tick in that case.

**Deferred (minor): background-refresh race with an in-flight catch-up reveal.** If
`StatsPanel.refresh_all()` (a background data refresh, e.g. from the session-write live-refresh
path) runs while `StreakGrid`'s leg-2 reveal is mid-flight, `set_data()` refreshes
`_cache`/`_longest_dates`/`_finished` from the database but does not touch
`_pending_reveal_days`/`_revealed_days` at all (by design — those fields are owned exclusively by
`animate_streak_count`/`catch_up_streak_count`/`_run_streak_leg2`). Confirmed by the user to behave
exactly as predicted: a narrow timing collision, cosmetic only (the dimmed cells can briefly look
stale relative to the freshly-loaded cache until the reveal timer finishes or the next refresh
corrects it). Accepted as-is for now — not worth the added state-reconciliation complexity for how
rarely the two events overlap. Candidate fix if it's ever worth doing: on detecting an interrupting
`set_data()` call while `_pending_reveal_days > self._revealed_days`, reveal all remaining pending
cells at once (snap `_revealed_days = _pending_reveal_days`) before applying the new data, rather
than trying to keep the staged per-day reveal in sync with a cache that just changed under it.

## Timeline tab visual rework: grid pop transition, label cascades, streak counter (2026-06-18)

**Grid transition style.** Replaced the cell reveal/conceal alpha-only fade with a "pop": cells
also scale up from a center-anchored inset as they reveal (and shrink back on conceal), using the
same diagonal Mexico-wave timing as before. Implemented as a shared `_grid_cell_anim(progress, row,
col, n_rows, n_cols, style)` helper in `stats_panel.py` so `HourlyHeatmap` and `StreakGrid` can't
drift apart. A `GRID_TRANSITION_STYLE` module constant selects the style; `"pop"` is the shipped
default, `"rows"` (a deliberately underwhelming row-curtain sweep) is kept in code as an internal
comparison baseline only — never exposed as a user-facing option. Tried and rejected: `"ripple"`
(radial wave from center — left the panel empty too long before anything appeared) and `"cols"`/
`"cols_zig"` (symmetric column curtain converging on center, with/without a wave-style zigzag — too
slow, and speeding it up felt off). None matched the original wave's diagonal path for visual
interest; the wave's longer travel distance is what makes it read as intricate. The longest-run
border and finished-day dot are gated on `anim_scale >= 0.999` so they never float over a still-
shrunk "pop" cell.

**Label cascades (top dates, left-gutter dates/hours) — mirrored, not reversed.** Each label now
fades in/out in place (opacity ramp) instead of the old internal clip-rect wipe, with an even
per-label stagger (`_LABEL_STAGGER_FRACTION` split across columns/rows) replacing the old lead-
fraction/sharp formula. The critical fix: enter and exit must be TRUE MIRRORS of each other, not the
same sweep played in reverse. The first implementation reused one opacity-ramp formula for both
directions and relied on clamping to mask the asymmetry — this silently made the "leading" label
hold at full opacity until late in the exit animation instead of fading first, which read as wrong
direction even though the cascade-rank assignment was correct. Fix: the exit formula anchors each
label's fade window from the END of the timeline (`end - span` to `end`) instead of reusing the
enter formula's start-anchored window. Verified by hand-computing local opacity at several progress
values for both cascade ranks before trusting it visually (see git history for the throwaway
verification script). Top labels: enter sweeps left-to-right (col 0/newest leads), exit sweeps
right-to-left (oldest leads). Left-gutter labels (Heatmap hours, Streak dates): enter top-to-bottom,
exit bottom-to-top. A second real bug surfaced after the math fix: `_label_sweep_in` was only ever
set inside `animate_labels_in`/`animate_labels_out`, never initialized in `__init__`, so the very
first paint before either had run raised `AttributeError` — fixed by initializing it `False` in both
`HourlyHeatmap.__init__` and `StreakGrid.__init__`.

**Streak counter animation — two legs, persisted across restarts.** The streak number now counts
up instead of appearing statically. Leg 1: linear (NOT eased — `OutCubic` was tried first and its
natural deceleration near the end was indistinguishable from a deliberate "pause before the last
tick," which is misleading when the streak hasn't actually changed) 0 → previously-shown value, 800ms
(`_STREAK_LEG1_MS`). Leg 2 (only if the streak grew since it was last shown): a 550ms pause
(`_STREAK_PAUSE_MS`, raised from an initial 400ms — 1-day deltas at 400ms were not perceptible) then
a snappy 250ms (`_STREAK_LEG2_MS`) linear tick from previous → current. If the streak is unchanged
(or decreased) since last shown, leg 2 is skipped entirely — single count straight to current, no
pause. The "previous" value MUST be persisted (`Config.get_last_shown_streak()` /
`set_last_shown_streak()`, QSettings-backed) rather than kept only in an in-memory
`StreakGrid._last_animated_streak` — an in-memory-only value resets to `None` on every app launch,
so the very first reveal of a new session always fell into the "no prior value, skip the pause"
branch even when the streak had genuinely grown since the app was last closed. Returns `None` (not
`0`) when never set, so a fresh install or pre-feature upgrade with a real non-zero streak doesn't
misread "never tracked" as "previous was 0" and spuriously animate a 0→N count with a pause that
implies growth from nothing.

**Panel-reopen catch-up gap (the trickiest part).** `QTabWidget.currentChanged` only fires when the
active tab index actually changes. If the Stats panel slides open with Timeline already the
remembered active tab (normal case: panel was last closed on Timeline/Streak), `_on_tab_changed`
never runs this session — the only code path that executes is the plain `refresh_current_tab() ->
_refresh_time() -> StreakGrid.set_data()` slide-reopen flow, which (correctly, by design) never
triggers `animate_reveal()`/`animate_labels_in()` on the grid. Before this fix, that same flow also
silently swallowed the streak count-up: `set_data()` just snapped the displayed number straight to
the new value with no comparison against the persisted previous value at all, so a streak that grew
while the app/panel was closed showed the new number immediately with no visual call-out — and the
user only ever saw the pause-then-tick by accident, on the next *manual* tab switch (which doesn't
re-derive "previous" correctly either, since at that point the display already shows the new value).
Fix: `_refresh_time()` takes a `streak_mode` parameter (`"full"` | `"catch_up"` | `"none"`) instead
of a single animate-or-not boolean. `"catch_up"` is wired only from `refresh_current_tab`'s Timeline
branch (the slide-reopen path) and calls `StreakGrid.catch_up_streak_count(previous)`: snaps the
display straight to the persisted previous value (no count-up, no grid touch at all — the hard "no
animation on slide-reopen" rule still applies to the grid), then after the same pause used
elsewhere, ticks up to current via the existing leg-2 logic. `"full"` (tab click, view-switch seam)
runs the normal two-leg `animate_streak_count()`. `"none"` (background refreshes like `refresh_all`)
leaves `set_data()`'s plain snap untouched, no persistence write. This is the only place where the
streak number's animation rule deliberately diverges from the grid's: the grid stays fully static on
every slide-reopen, the number gets one exception so a real change is never silently swallowed.

**Deferred:** matching the pause-then-tick effect inside the grid itself — dimming the
`current - previous` newest day-cells and revealing them one at a time, in lockstep with the
counter's leg 2 tick, while still drawing the longest-run border and finished-dot correctly on
already-revealed cells. Estimated moderate-to-high complexity (new per-cell "pending reveal" state,
likely replacing leg 2's continuous tween with a discrete step timer, careful interaction with the
existing `is_longest`/`_finished`/pop-scale logic) — explicitly scoped as a separate future pass, not
attempted here.

## VU-meter oscillation on embedded M4B FIXED (2026-06-16)

**Symptom:** clicking Next/Prev or a chapter-list item **while playing** caused the chapter slider
to spike full-right (~100%), chapter labels to show "00:00:00 / -00:00:00", and the chapter name to
flash the wrong chapter — all for one 200ms tick before self-correcting. Only while playing; never
while paused.

**Root cause:** `player.chapter_list` (property) fell back to `self.instance.chapter_list` for
embedded M4B — a live read from the mpv C layer on every call. During/after a seek, mpv's C thread
updates chapter boundary data asynchronously; one tick where `_sync_chapter_ui` reads a transient
state produces either near-zero `chap_dur` (labels write "00:00:00"; slider `setValue` is already
guarded by `chap_dur > 0` at line 1678 so it skips) or `c_elapsed ≈ chap_dur` with stale boundary
(slider full-right). While paused, mpv's C thread is quiescent after settle — no race.

**Hypothesis confirmed:** the `[CHAP-UI]` Step-0 instrument ran during a multi-hour soak with no
spike tick ever appearing, which means the cache eliminated the race entirely before it could be
observed. The specific hypothesis (A: near-zero chap_dur / B: stale boundary) was never confirmed
from a log line — the fix held for all soaked seeks. The `setValue` guard at line 1678 is an
independent safety net that remains.

**Fix:** `cache_chapter_list()` in `player.py` snapshots `instance.chapter_list` into `_chapter_list`
once at file-loaded time (called from `_on_file_loaded_populate_chapters` after `dur` is confirmed).
The `chapter_list` property already prefers `_chapter_list` when non-None → all reads during playback
hit the stable Python list, never the live C layer.

**Sentinel swap:** two code sites previously used `_chapter_list is None` as a proxy for "this is
embedded M4B" — `seek_async` (paused undershoot comp) and `_chapter_seek_offset()` (−0.09 offset).
After the cache, `_chapter_list` is non-None for embedded M4B too, so both were switched to a
dedicated `_is_embedded_m4b` flag set by `cache_chapter_list()`. The `chapter_list` property's own
early-return (`if self._chapter_list is not None`) is unchanged and correct.

## Chapter-slider paused "sliver" FIXED; load-time transient sliver DEFERRED (2026-06-15)

**Fixed (paused sliver):** at a freshly-landed chapter start, the chapter slider showed a thin fill
("sliver") while paused — the VT/CUE nav target is `nominal + _CHAPTER_BOUNDARY_EPSILON` (0.35), so
`c_elapsed = pos − chap_start ≈ 0.35`, rendered as a few-percent fill on a short chapter. Visible ONLY
while paused (live playback advances `pos` and swallows it within a frame). Fix is display-only:
`_sliver_clamp(pause, c_elapsed)` in `app.py` reads the slider value as 0 when paused AND
`c_elapsed < _CHAPTER_SLIVER_EPS` (= `_CHAPTER_BOUNDARY_EPSILON + 0.25` = 0.60, tied to the constant so
it tracks any retune). Applied at both the 200ms `_sync_chapter_ui` setValue and the flow-anim
`new_chap_val`. Released instantly on play (gate opens, `pos` already moving → no jump, no animation).
Labels untouched (already floor to 00:00). Measured paused settle jitter ~0.0004s, so 0.25 headroom is
~600× the real landing error (soak logs `/tmp/fabulor_{run,vtfix,vtboth}.log`). Headless tests:
`tests/test_sliver_clamp.py`.

**Deferred (load-time transient sliver):** on book load at a chapter start, the slider can show a brief
sliver then self-correct on the next tick. This is the one-frame flow-path residual (pause/value settle
ordering at load), NOT the paused artifact above — it's transient, cosmetic, self-healing, and tied to
the delicate `load_book` cache-reset / flow-animation ordering we deliberately don't want to disturb.
Deferred. If chased later: the `_sliver_clamp` at the flow-anim site depends on `load_book`'s
`_cached_pause = True` reset running first — do not reorder the computation above that reset.

## First-chapter Prev rewinds to 0:00 (drop the 2s threshold in chapter 0) (2026-06-15)

In the FIRST chapter there is no previous chapter, so `previous_chapter`'s `2.0 × speed`s
restart-vs-previous threshold doesn't apply. Previously, sitting in the first 2s of chapter 0 made Prev
a no-op (the `curr_chap > 0` branch dead-ended), leaving e.g. 0:01 awkward to clear to 0:00 without the
right-click progress-reset (which casual users won't know). Now `curr_chap == 0` always
`seek_async(0.0)` → rewinds to book start (both VT and non-VT branches). The `seek_async` 0.05 floor
still applies (true-0/negative absolute seek can land mpv at EOF — see the floor rule), so it lands at
0.05s ≈ 00:00 (and the sliver clamp reads it as 0). Freeze invariant preserved: `seek_async` sets
`is_seeking` WITH a matching `_seek_target`, so no stranding. Tests updated in `tests/test_vt_seek.py`
(the old "chapter-0 Prev is a no-op" contract was intentionally replaced).

## VT loads are STRICTLY SERIALIZED — no overlapping-seek clobber (2026-06-15)

Proven by a both-edges capture (`[PLAY-ISSUE]` at each `play()`, `[FILE-LOADED]` at `_on_file_loaded`):
every `play()` produces its matching `file-loaded` ~12–18ms later, IN issue order, before the next
`play()` is issued. So the rapid-backward-seek "overlapping cross-file seeks clobber `_file_offset`/
`_seek_target`" theory does NOT occur in practice. This retired a large amount of explored machinery
(a single seek-state object, PendingLoad records keyed by index, generation counters, FIFO-vs-path
disambiguation) — all of it solving a clobber that can't happen while loads are serial. If a future
mpv version or refactor ever makes loads async/batched, the committed `[VT-DESYNC]` tripwire in
`_on_file_loaded` will fire (loaded path != `_virtual_timeline[_current_vt_index]` path), and the
shelved design in `experiments/seek_state_desync/` becomes relevant. Until then: `_current_vt_index`
and `_file_offset` set speculatively in `seek_async` before `play()` ARE correct at `_on_file_loaded`
time, because nothing overlapped to change them.

## VT cross-file seek froze because `_seek_target` was stored LOCAL, settle compares GLOBAL (2026-06-15, FIXED `29b266c`)

Permanent chapter-UI freeze on VT books after a cross-file seek (e.g. rapid backward seek). Root
cause: `_on_file_loaded`'s cross-file follow-up set `self._seek_target = pending` where `pending` is a
LOCAL offset into the new file, but the settle in `_on_time_pos_change` is
`abs((value + _file_offset) − _seek_target) < 1.0` — i.e. it expects `_seek_target` in GLOBAL space.
So `abs(global − local) ≈ the file's cumulative_start` (e.g. 110107), never `< 1.0`, `is_seeking`
stuck True forever, chapter slider + remaining-time frozen. Signature in the log: `seek=True tgt=0.35`
while `gpos` is in the thousands. Fix: `self._seek_target = pending + target_file['cumulative_start']`
(GLOBAL); the mpv `command_async('seek', pending, ...)` stays LOCAL. Uses the timeline entry
(self-consistent with the index that drives the seek) not the bare `_file_offset` field. Validated:
`tests/test_vt_seek.py` is RED with the old LOCAL line and GREEN after, against the real captured
`vtidx=0` (target 0.35) and `vtidx=27` (target 0.35+108000) cases. The same coordinate-space bug was
identifiable in the very first agent trace weeks ago; it got buried under an offset-clobber theory and
re-surfaced only when the real both-edges capture was read.

## Boundary nav stranded `is_seeking` → freeze; the unconditional app-level set was the bug (2026-06-15, FIXED `29b266c`)

Separate permanent freeze (reproduces on M4B AND VT). `handle_prev`/`handle_next`/`_on_prev_right_click`
in app.py set `self.player.is_seeking = True` UNCONDITIONALLY after calling the player nav method. At
the **chapter[0] Prev boundary** (within ~first 2s, where the "go to previous chapter" branch runs but
there is no previous chapter) and the **last-chapter Next** boundary, `previous_chapter()`/
`next_chapter()` no-op WITHOUT calling `seek_async`, so `_seek_target` is never set. The unconditional
`is_seeking = True` then strands the flag: `is_seeking=True, _seek_target=None` → the settle
(`...and self._seek_target is not None`) can never run → permanent freeze. Log signature: `seek=True
tgt=None` while `value` climbs freely. Fix: REMOVE the redundant app-level `is_seeking = True`; the
nav methods set `is_seeking` via `seek_async` ONLY when they actually seek. This is the SAME class as
the chapter-list-click freeze fixed earlier (`_on_chapter_list_selected` already carries the warning
comment). User-confirmed by soak (markers: "chapter[0] within first second, left-click Prev → freeze;
wait 2s → correct; right-click Prev always works"). Harness adds contract guards that the nav methods
at a boundary leave `is_seeking` False.

## Playing-seek chapter-UI oscillation — RESOLVED by M4B cache fix (2026-06-16)

Isolated while verifying the position-creep fix (2026-06-13). Clicking Next/Prev or a chapter-list
entry **while playing** made the chapter slider jump to the chapter's END and bounce between chapters
before settling; the chapter label flickered identically.

**Resolution (2026-06-16):** no bounce/stick observed during multi-hour soak after the embedded M4B
`cache_chapter_list()` fix landed. The two symptoms (VU-meter spike full-right and bounce/stick) were
the same bug: `player.chapter_list` for embedded M4B was a live C-layer read on every call; during a
playing seek mpv's C thread updated boundary data mid-read, producing transient `chap_dur ≈ 0` or
wrong `c_elapsed`. The cache eliminated the race entirely. The stale-backward-sample hypothesis below
was the best theory at the time but the cache fix made it moot.

**History (kept for reference):** the earlier "settle clears too early" hypothesis was disproven by
instrumentation (`dist=0.0` clean settles). The updated hypothesis was a stale BACKWARD `time_pos`
sample mpv emits after a clean settle (~0.56–0.87s back). A fix (`b6a4023`, drop backward global
jumps while not seeking) was reverted (`4ae0783`) because it regressed VT backward-seek + play/pause
icon + chapter[1]→[0] click. That revert is still in the tree and correct — do not re-apply it.

## Position creep on restart was an epsilon on the restore seek (2026-06-13, FIXED `3bb14cf`)

`_restore_position` added `+_CHAPTER_BOUNDARY_EPSILON` (0.35) to the non-VT restore seek. Restore is
NOT chapter navigation — no boundary to clear — so this was wrong. The save path
(`_save_current_progress` / `_sync_persistence`) saves the true `time_pos`; on restart the seek landed
at `progress + 0.35`, the 200ms sync saved that inflated landing, and it became the next restore's
input → ~0.35s forward every restart until EOF. The VT branch (`seek_async(progress)`, no epsilon)
never crept — direct proof non-VT needed none. Fix: collapse both branches to a single
`seek_async(book_data.progress)`. The `_CHAPTER_BOUNDARY_EPSILON` import stays — still used by the
VT-gated flow-animation display offset at app.py:1250 (unrelated). This fixed ONLY the creep; the
load-time sliver/clip are the separate pre-existing oscillation family above.

## Chapter-seek precision: mpv overshoots ~0.09s playing, undershoots ~0.37s paused (2026-06-13)

The single biggest non-obvious finding of the Session 3+4 chapter-seek work. **mpv's exact seek
(`command_async('seek', pos, 'absolute+exact')`) does NOT land on `pos`.** Measured across 5
embedded M4Bs / 67 chapter seeks (temporary `[CHAP-MEASURE]` instrumentation, since removed):

- **Playing:** lands ~**+0.09s** PAST the target (1–2 AAC frames of overshoot). Consistent across
  files; the spread is frame-quantization (~0.046s steps at 1024/22050Hz), not per-file variance.
- **Paused:** lands ~**−0.37s** SHORT of the target, and the `time-pos` observer reports unstable
  intermediate values while paused (e.g. `settled=28101` for a `nominal=1289` seek — do not trust a
  single post-seek `time_pos` sample while paused).

This overturns the old documented rationale ("mpv chapter floats land ~0.25s short of nominal").
Switching to `exact`/`hr-seek` is a **no-op** — the code already uses `absolute+exact`; the residual
is decoder/frame landing, not keyframe snapping. Do not re-propose it.

**Why the old single `_CHAPTER_BOUNDARY_EPSILON = 0.35` "worked" and what it cost:** it was doing
two jobs at once — a read-side position→chapter-index walk tolerance AND a seek-target epsilon.
As a walk tolerance, 0.35 *barely* covered the ~0.37 paused undershoot (which is why paused Next/Prev
got stuck "occasionally" — the undershoot sometimes exceeded 0.35). As a seek epsilon, +0.35 on top
of mpv's own +0.09 overshoot skipped ~0.44s of every chapter's opening audio ("Part 3"→"3",
"Nineteen"→"teen"). The user's prior manual sweep finding "0.35 is the only reliable value" was the
walk-tolerance constraint, not an audio sweet spot.

**The three-constant split (player.py):**
- `_CHAPTER_WALK_TOLERANCE = 0.5` — ALL position→index walks (`time <= pos + X`) in player.py and
  app.py. Must exceed the ~0.37 paused undershoot; 0.5 is still far below the ~2s minimum real
  chapter spacing, so it can't misattribute to an adjacent chapter.
- `_EMBEDDED_CHAPTER_SEEK_OFFSET = -0.09` — embedded-M4B chapter-nav seek targets (via
  `_chapter_seek_offset()`). Cancels mpv's playing-overshoot.
- `_PAUSED_SEEK_UNDERSHOOT_COMP = 0.37` — forward correction added to the mpv seek **command only**
  when paused + embedded, inside `seek_async`. `_seek_target`/`_cached_time_pos` keep the logical
  (uncompensated) position so the walk/UI stay correct. Guarded so it doesn't push into the near-EOF
  deadzone.
- `_CHAPTER_BOUNDARY_EPSILON = 0.35` — now ONLY the VT/CUE seek-target epsilon. Do NOT reuse for
  walks or embedded seeks.

**`seek_async` target floor (`if pos < 0.05: pos = 0.05`):** the negative embedded offset turns a
Prev/Next that resolves to chapter 0 (nominal ≈ 0) into a NEGATIVE absolute seek. mpv treats a
negative/zero absolute seek as undefined and **lands at EOF** — observed as "previous chapter near
book start jumps to 100% and marks the book finished." The floor prevents this and also self-heals
the secondary "next is stuck" symptom (a bad seek had set `_eof`, after which `next_chapter`'s
`if self._eof: return` did nothing).

VT first-word clipping (multi-file) is the same *class* of issue but a different *cause* (VT chapter
boundaries are file starts from summed mutagen durations vs mpv's decoded sample count) and is
**deferred** — VT clicks/nav still use `+0.35`.

## Chapter-list click freeze was a stuck `is_seeking` flag, not a seek problem (2026-06-13)

Embedded-M4B chapter-list clicks froze the chapter slider + chapter time labels (audio and the
overall slider were fine) until a manual slider click revived them. Root cause: the embedded click
navigated via native `self.player.chapter = idx`, whose setter sets `instance.chapter` and
`_eof = False` but NOT `_seek_target`. `_on_chapter_list_selected` set `is_seeking = True`
unconditionally; `_sync_chapter_ui` and `_update_chapter_label_from_index` early-return while
`is_seeking` is True; and `is_seeking` is cleared ONLY by `_on_time_pos_change` when
`_seek_target is not None` (`_on_chapter_change` is fully suppressed). Native chapter assignment never
set `_seek_target`, so the clear condition could never fire → permanent freeze. A manual slider drag
calls `seek_async` (which sets `_seek_target`), which is why it "revived" the UI.

**Fix:** new public `Player.activate_chapter_index(idx)` seeks to
`chapter_list[idx]['time'] + self._chapter_seek_offset()` via `seek_async` (mode-aware offset). All
book types now route chapter-list clicks through it; the embedded native-nav branch is gone, as is
`ChapterList`'s reach into `_virtual_timeline`/`_chapter_list` (the coupling violation previously
flagged in NOTES is now RESOLVED — `_activate_item` calls one public method, no private-attr access).
Removed the redundant `is_seeking = True` from `_on_chapter_list_selected` (`seek_async` sets it
synchronously, before the slot fires, with `_seek_target` set). This crossed the former CLAUDE.md
"embedded clicks must use `self.chapter = idx`" rule — that exception (git `e243193`, 2026-05-17)
existed only because the *then-current* `seek_async + 0.35` drifted, which the −0.09 model fixed.
The native `chapter` **getter** is still read by `apply_smart_rewind` (clamp to chapter start) and
remains valid: mpv updates its native chapter from playback position regardless of how the seek was
issued. CLAUDE.md (all references) revised in the same commit.

## `refresh_current_tab()` dispatch must use the live tab name, not the old one (2026-06-13)

`refresh_current_tab()` dispatches by `tabs.tabText(currentIndex())`. When a tab is renamed, every dispatch branch in every dispatch function must be updated in the same commit — there is no compile-time check. The Timeline tab was renamed from `"Hour"` to `"Timeline"` in `addTab` and `_on_tab_changed` but the `refresh_current_tab()` branch was missed, silently skipping `_refresh_time()` on every panel-open and session-write while that tab was active. If a tab name changes in the future, grep for the old string across the whole file before committing.

## Per-session delete must emit `history_deleted` to refresh the stats StreakGrid (2026-06-12)

The "delete all history for this book" button (`_on_delete_book_stats_confirmed`) emits
`BookDetailPanel.history_deleted`, which is wired to `stats_panel.refresh_all` **and**
`library_panel.refresh` (`main_window_builders.py:556-557`). The **per-session** delete
(`_on_history_delete_confirmed`, the 2026-06-10 `_HistoryRow` flow) originally did NOT emit it — it
only called `_refresh_stats()` (the book-detail panel's own widgets). `db.delete_session` correctly
invalidates the streak-grid cache cell in-transaction, but the stats panel's `StreakGrid` (mounted
underneath the book-detail overlay when opened from a stats row) never re-queried, so a deleted day
could keep showing as listened until a tab change. Fix: emit `self.history_deleted.emit()` in the
per-session delete's `_finish` callback too — reuses the existing fan-out, no new signal. The emit
fires from a `QPropertyAnimation.finished` callback (UI thread), so the existing direct connection is
correct. The recorder is NOT involved in deletes (`db.delete_session` is called straight from the
panel) — do not route deletion notifications through `SessionRecorder`. Was REVIEW_PASS7 finding #9.

## StreakGrid invariant: a 'finished' day is ALWAYS a listened day (2026-06-12)

**Bug fixed:** the grid could show a finished dot on an UN-filled cell — a book taken to
finished on a day with no session ≥ 60s lit the dot (`book_events`) but not the fill
(`streak_grid_cache`, which is session-only). Worse, even after filling the cell, the day didn't
count toward the streak number (`get_streaks` reads sessions only).

**Rule now enforced everywhere:** `finished ⟹ listened`. A 'finished' `book_event` marks its day
as listened in the cache, counts toward `get_streaks()` current/longest, counts in
`StreakGrid._compute_longest_run`, AND the dot shares the filled cell. All using the **same
day_start_hour adjustment as sessions** — finished dates used to be raw calendar dates (different
cell for a non-midnight day-start); they are now adjusted dates so dot and fill always coincide.

**The six touch-points (keep them consistent — this is the new sync invariant):**
1. `build_streak_grid_cache` — the `listened=1` UNION includes finished adjusted-dates.
2. `_update_streak_grid_cache_for_date` — if no session backs the day, falls through to a finished-event check before darkening (so deleting the last session on a finished day keeps it lit).
3. `write_book_event(event_type='finished', day_start_hour=…)` — marks the cell at finish time (immediate, no rebuild needed).
4. `unfinish_book(book_id, day_start_hour=…)` — re-evaluates the day; darkens if nothing else backs it.
5. `delete_book_stats` — gathers finished-event days (not just session days) into its recompute set.
6. `get_streaks` — unions finished adjusted-dates into its day set; `get_streak_grid_finished_dates(day_start_hour)` uses the adjusted date for the dot.

**Date-space:** ONE space now — day_start_hour-adjusted — across sessions, finished events, cache,
streaks, and dot. Do NOT reintroduce a raw-calendar finished date; it desyncs dot from fill.
**Existing data self-heals:** `build_streak_grid_cache` runs on every app startup (`app.py:319`),
so finished-but-dark days from before this fix light up on next launch — no migration.
Cross-check still holds: `len(StreakGrid._longest_dates) == get_streaks()['longest']` (both now
include finished days; if they diverge, an attribution change hit some sites but not all six above).

## StreakGrid — four facts that will confuse whoever touches it next (2026-06-11)

The streak-grid panel (`StreakGrid` + `TasselOverlay` in `stats_panel.py`) has four non-obvious points.
Full narrative is in SESSION.md (2026-06-11 Session 3); this is the quick "why is it like this" reference.

1. **`load_themed_icon` tints `currentColor` SVGs anyway — but use `load_currentcolor_icon` regardless.**
   clock.svg / calendar.svg use `fill="currentColor"`, not `fill="#000000"`. We expected the existing
   `load_themed_icon` (which only swaps `#000000`) to render them untinted — it doesn't, because its
   `<style>`-injection fallback (`if '<style' not in svg_data and 'stroke=' not in svg_data`) lands a
   `path { fill: color }` rule that Qt applies over `currentColor`. So both loaders produce a tinted icon.
   The new `load_currentcolor_icon` recolors `currentColor` **explicitly via regex** and is the preferred
   path for these icons — the `load_themed_icon` success is incidental to that fallback firing, not a
   contract. Don't revert clock/calendar to `load_themed_icon` "because it works the same."

2. **`books.finished_at` is dead — query `book_events` (`event_type='finished'`) for finished state.**
   `books.finished_at` is in the schema but never written (only reset to NULL). Every finished-book query
   uses `book_events`; `get_streak_grid_finished_dates()` does too. Querying `books.finished_at` returns
   silently empty.

3. **Longest-streak DATES are computed in the widget; `get_streaks()` returns only COUNTS.**
   `get_streaks(day_start_hour)` → `{'current','longest'}` ints, not which days. `StreakGrid` derives the
   date set itself (`_compute_longest_run` over the cache; ISO sort + consecutive-run scan; most-recent
   wins on a tie via `>=`). **Cross-check invariant:** `len(self._longest_dates) == streak_info['longest']`
   — two independent paths over the same `listening_sessions` data (SQL count vs. Python run scan over the
   cache). They were equal (16==16) against the real DB. A divergence means the cache and `get_streaks`
   have drifted (an attribution change applied to one site but not the four cache sites — see the
   Session-1 "change all four" note). That mismatch is the diagnostic; do not clamp one to the other.

4. **`animate_conceal()` is additive-only; keep it separate from `animate_reveal()`.**
   `HourlyHeatmap.animate_reveal` and `paintEvent` are byte-for-byte unchanged. `animate_conceal` is a NEW
   method on both grids that reuses `reveal_progress` in reverse (1.0→0.0, 600ms) and **restores 1000ms in
   its `finished` callback** so the following construct wave runs full-length. Do NOT fold a
   `setDuration(600)` into `animate_reveal` to share code — the asymmetric restore is the whole point.
   It tracks its pending slot in `self._conceal_slot` and disconnects only when present (no
   `Failed to disconnect (None)` warning). Relatedly, `StreakGrid.set_data` does NOT self-reveal — the
   caller fires exactly one `animate_reveal()`, else the tab-change reveal double-fires and hitches.

## Timeline header date labels — "J" glyph clipped at top edge (2026-06-10, unresolved)

**Goal:** The rotated date labels at the top of `HourlyHeatmap` show months starting with "J" (Jan, Jun, Jul) as "un", "ul" — the top of the "J" glyph is cut off. May, Sep, Oct etc. render fine.

**Setup:** Labels are drawn rotated -90° via `painter.save() / translate / rotate(-90) / drawText / restore`. The translate anchor is at `(cx+2, DATE_LABEL_H - 3)`. After rotation, `AlignLeft` means text grows in the +x direction of the rotated frame, which maps to the -y direction (upward) in widget space. So the *start* of the string (the "J") is nearest the widget's top edge (y=0).

**What the red background diagnostic showed:** The `QRect` passed to `drawText` is fully inside the widget — there is plenty of space above the rect. The "J" is not being clipped by the widget boundary or the rect boundary in any obvious geometric sense. Despite `setClipping(False)` on the painter, the glyph is still truncated.

**Approaches tried and why they all failed:**

1. **Increase top container margin** (`outer.setContentsMargins(8, 12→30, 8, 8)`) — moves the widget down so its y=0 is further from the screen edge. With 30px margin the "J" rendered. But this adds ugly whitespace and doesn't fix the root cause; it just hides it.

2. **Increase `DATE_LABEL_H`** (44→48→50→52→58) — grows the widget header zone and pushes the grid down. Tried in combination with adjusting the translate offset to keep labels visually in place. Never fixed the clipping regardless of value.

3. **Adjust translate y** (`DATE_LABEL_H - 1`, `-3`, `-17`) — shifts the anchor point. Moving it down (larger subtract) pushes text further from the grid. Moving it up (smaller subtract) pushes text closer to y=0 and makes it worse. None fixed "J".

4. **Offset the text rect x** (`QRect(4, ...)`, `QRect(6, ...)`) — in rotated space, positive x maps to downward in widget space, so this pushes the text start away from y=0. Visually this just clipped May and other months too — the rect was now too short for the full text.

5. **Negative x on the text rect** (`QRect(-6, ...)`) — intended to let the "J" glyph bleed past x=0 in rotated space (= above y=0 in widget space). Made no visible difference.

6. **`painter.setClipping(False)`** before the label loop — no effect. Qt clips painter output at the widget boundary regardless of this flag when painting inside a `paintEvent`.

7. **`AlignRight`** — anchors the text end (the day number) near the grid, so "J" starts further from y=0. User confirmed this was already tried independently and still showed "un" not "Jun".

8. **Per-label `j_offset`** — tried shifting J-month labels by 4px via `DATE_LABEL_H - 3 + j_offset` in the translate. No effect.

9. **Font metrics `descent_extra`** — tried computing `fm.descent() - fm.leading()` and using it as either a translate offset or a rect x offset. Didn't fix it; the x/y confusion in rotated space made results unpredictable.

**What is actually happening (hypothesis):** Qt's `drawText` clips the rendered glyph to the bounding rect even when the glyph's ink extends outside it (e.g. a "J" whose hook descends below the baseline, which in rotated-90° space maps to above the rect's left edge). `setClipping(False)` on the painter does not disable this per-glyph clipping — that is internal to Qt's text renderer. The fix likely requires either: (a) painting the text at a position where the glyph's natural ink extent stays inside the rect (i.e. add padding at the rect's start equal to the font's descent), or (b) using a `QPainterPath` to stroke the text outline instead of `drawText`, which respects `setClipping(False)`. Option (a) is the sane path but requires knowing the exact descent in rotated coordinates.

**Resolution:** The clipping was the rect *height* being too tight, not the widget boundary or the rect's x origin. After rotate(-90), the rect's height maps to horizontal ink space in widget coordinates. `CELL=14` is too narrow for glyphs whose ink extends outside the em square (e.g. "J"'s hook). Fix: `QRect(2, -self.CELL, self.DATE_LABEL_H, self.CELL * 2)` — doubling the height and centering it with `y=-CELL` gives all glyphs enough room. The `x=2` is the 2px margin from the grid edge.

---

## Semi-transparent session history rows — investigation dead end (2026-06-10)

**Goal:** Make `_HistoryRow` widgets in the Book Detail Panel History tab render semi-transparently like the tag rows in the Tags panel, so the panel background (and cover art behind it) bleeds through.

**Why it looks like it should work:** The panel background is `rgba(bg_main, panel_opacity_hover)` set via QSS. The Tags panel rows use `rgba(bg_deep, 0.6)` in `get_tags_stylesheet` via a class-level `QWidget#tag_list_row` rule — no instance `setStyleSheet` — and they visually appear semi-transparent.

**Approaches tried and why they failed:**

1. **`rgba()` in instance `setStyleSheet` on the row** — an instance stylesheet has higher specificity than a parent/class rule in Qt's QSS cascade. The row's own `setStyleSheet` set a fully opaque background that won every time. Removing the instance stylesheet was necessary but not sufficient.

2. **`rgba()` in `get_stats_stylesheet` as a class rule (`QWidget#history_row_odd` / `even`)** — the stylesheet was generated correctly (verified via unit test: `rgba(19,8,72, 224)`). The row widget resolved the correct semi-transparent color in `palette()`. But visually the rows were still fully opaque. The scroll area viewport was painting an opaque fill on top.

3. **Making the scroll area transparent** — tried `QScrollArea#history_scroll QWidget#qt_scrollarea_viewport { background: transparent }`, `viewport().setAutoFillBackground(False)`, and `viewport().setAttribute(WA_NoSystemBackground, True)`. Palette tests confirmed `autoFill=False` on the viewport, but visual result unchanged. The `WA_StyledBackground` + `WA_NoSystemBackground` combo also didn't help.

4. **Making the container transparent** — added `WA_StyledBackground` to `_history_container` and named it `"history_container"` with a `background: transparent` rule. Container correctly resolved to alpha=0 in tests. Still no visual change on rows, and the changes broke slider fill/bg colors in the stats panel (unintended stylesheet interaction via the shared `get_stats_stylesheet`).

**Root cause hypothesis:** The `QScrollArea` internal viewport widget has special paint handling that isn't fully controlled by QSS or the `WA_*` attributes. The Tags panel works because its scroll area is inside `TagManagerWidget` which has its own stylesheet (`get_tags_stylesheet`) applied directly to it — not shared with other panels. The history scroll area shares `get_stats_stylesheet` with `stats_panel`, making scoped rules fragile.

**Current state:** Solid alternating row colors (`session_history_row_one` / `two` per theme, fallback `library_row_one` / `two`). Alzabo has explicit values. This is the working baseline.

**Possible future path:** Give `BookDetailPanel` its own dedicated stylesheet function instead of sharing `get_stats_stylesheet`. That would allow unscoped `QScrollArea { background: transparent }` rules without risking stats panel regressions. Not pursued — the effort/risk ratio is poor for a cosmetic change.

---

## TODO (before release): suppress shimmer when speed is already the default (2026-06-10)

`_on_speed_right_clicked` unconditionally plays the shimmer sweep on every right-click. Before release, add a guard: if `round(current, 9) == round(config.get_default_speed(), 9)` (same float-drift tolerance as `sync_btn`), skip both `set_default_speed` and `play_shimmer` — the speed is already the default, so there is nothing to confirm. Or allow one play but not repeated triggering on the same value. Decision deferred.

---

## "Delete listening history" button has manually managed cursor states — skip in bulk cursor pass (2026-06-10)

The button in the History tab has two explicit cursor states set in code:
- `PointingHandCursor` when idle (clickable)
- `ArrowCursor` while the "Click to delete all history for this book" confirm label is visible (not clickable)

Any bulk pass that sets `PointingHandCursor` globally (via QSS or a sweep of all interactive widgets) must **exclude this button**. Overriding it would break the disabled-state cursor and remove the visual signal that the button is temporarily inert.

Managed in `_on_delete_book_stats` (sets `ArrowCursor`, disables button) and `_cancel_delete_history` (restores `PointingHandCursor`, re-enables button).

---

## eventFilter safe-zone pattern for floating confirm labels (2026-06-10)

When a confirm label is floated absolutely above a button (not in the layout), the eventFilter's click-outside dismissal must include **both** the confirm label **and the button underneath** in the safe zone. Without the button in the safe zone, clicking the button while confirm is visible triggers this sequence:

1. `MouseButtonPress` fires eventFilter → confirm not hit → `_cancel_delete_history()` → confirm hidden, button re-enabled
2. Click propagates to now-enabled button → `_on_delete_book_stats()` → confirm shown again

The fix: `if not hits(confirm_label) and not hits(button): _cancel_delete_history()`. The button being disabled doesn't help here because the eventFilter fires before Qt's normal event routing.

---

## `_eof_event_written` resets only in `_on_file_ready` — never in `_on_revert_finish` (2026-06-08)

`_eof_event_written` guards the EOF block (app.py:1361-1363) from writing a
duplicate `finished` `book_event` on every 200ms UI tick while the player
sits at EOF — it's set `True` the first time the event is written, and the
*only* place it is reset to `False` is `_on_file_ready` (app.py:1092, on
the next book load).

An earlier version of `_on_revert_finish` also reset it to `False`, on the
theory that reverting "undoes" the finish and should let it re-fire later.
This was wrong and caused a re-arm bug: the player is *still sitting at
EOF* when revert is clicked (nothing seeks away), so the very next 200ms
tick saw `_eof_event_written == False` again, re-wrote the `finished`
event, and silently undid the revert the user just performed.

**Do not add that reset back to `_on_revert_finish`.** The flag's job is
"have we written a finished-event for *this* EOF arrival" — revert changes
the DB's finished status, not whether this EOF arrival already wrote its
event. `_on_file_ready` remains the sole legitimate reset point, because a
new `book_ready` means a genuinely new EOF can occur later.

---

## Known gaps — missing-file edge cases not yet exercised (2026-06-08)

While hardening the missing-folder/ghost-playback bug (guard in
`_on_book_selected_from_library` + try/except in `player.py`'s
`_ResolveWorker.run`), two related scenarios were identified but not
verified — both would need a populated multi-file (VT) book or real
removable media to test meaningfully, so they're logged rather than
speculatively patched:

- **Partial VT folder removal**: `_resolve_playlist` builds the virtual
  timeline straight from `db.get_book_files(path)` with no per-file
  existence check. If some (not all) files in a multi-file book are
  deleted externally, behavior is unverified — it may rely on the
  existing `end-file`/`ERROR` → `load_failed` → `_on_load_failed` banner
  path firing per missing file during VT advancement, or it may stall
  mid-book when `_advance_or_finish` tries to play a vanished path.
- **Removable/network drive unmount mid-buffer**: path exists at
  selection time, then the drive unmounts while mpv is buffering. Almost
  certainly funnels through the same `end-file`/`ERROR` →
  `load_failed` mechanism that already handles in-flight I/O errors
  (case "file disappears mid-playback", confirmed working), but the
  timing/UX — does the banner appear promptly, or does mpv hang during
  the buffer stall before the error event fires — is unverified without
  real removable media.

Two adjacent scenarios were checked and confirmed already handled:
file-vanishes-mid-playback fires mpv's `end-file` event with
`reason == ERROR (4)`, which `_on_end_file` turns into `load_failed` →
`_on_load_failed`'s "Failed to load: {reason}" banner (player.py:426-433,
app.py:1220-1222); and startup restore of a missing last-played book is
guarded by `os.path.exists(last_book)` at app.py:390, falling through
cleanly to the empty-library state with no stale UI.

---

## HoverButton + setToolTip on small buttons causes an enter/leave feedback loop (2026-06-08)

`eof_revert_btn` (24×24, in the status banner) was built as a `HoverButton`
with `setToolTip` and `setCursor(Qt.PointingHandCursor)`, intended to swap its
icon color (`accent` → `accent_light`) on hover. In practice the tooltip
popup overlapped the small button, stealing the hover — which fired
`leaveEvent`/`enterEvent` on the button again, re-showing the tooltip, in a
loop. Symptoms: the tooltip flickered in and out, and the cursor cycled
between arrow and pointing-hand.

Systematic elimination ruled out the obvious suspects: disabling the icon
swap entirely (`setIcon` calls) had no effect, and `cancel_scan_btn` /
`eof_close_btn` — both plain `QPushButton`s with `setCursor` + `setToolTip` —
were completely stable. The cause was specifically `HoverButton`'s
`enterEvent`/`leaveEvent` overrides and `hovered`/`unhovered` signal emission
interacting badly with native Qt tooltip tracking on a small widget.

**Fix:** use plain `QPushButton` + `installEventFilter(self)`, handling
`QEvent.Enter`/`QEvent.Leave` directly in the global `eventFilter` to drive
hover-based icon swaps. Avoid `HoverButton` for small (<~30px) widgets that
also need a tooltip — or skip the tooltip (the eventual choice here: both
banner buttons are visually self-explanatory, so tooltips were dropped
entirely rather than chasing precise `QToolTip.showText` placement, which has
no window-bounds awareness and is fragile on small widgets near window edges).

---

## Startup animation stutter (2026-06-07)
On app startup, `book_ready` fires while the event loop is under pressure
from background work (stats panel cache, cover cache, library population).
The flow animation competes for main-thread time, producing a stutter around
the 15-25% mark. Library loads are smooth because the app is idle at that
point.

This is not a race condition — it is event-loop contention during a
legitimately busy startup window. It cannot be fixed at the animation layer.

Three options for future revisit:
1. **Skip animation on startup** — detect `_switch.phase == IDLE` (startup
   never calls `begin()`, so phase stays IDLE), go straight to `setValue`.
   Low risk, zero complexity, inconsistent with library-load behavior.
2. **Defer/cheapen background work** — lazy-load stats/cover cache, move
   population off the main thread. Correct long-term fix, large scope.
3. **Delay animation** — fragile, hardware-dependent. Rejected.

**Intermittent chapter[0] flash on **
Pre-existing. Probably only occurs on app start, not on library book loads. Not
addressed this session.

---

## Startup flow animation: pre defaults to 0, not None — 2026-06-06

`_on_file_ready` and `_on_file_loaded_populate_chapters` both do `pre = SM.take_*_target(); pre = pre if pre is not None else 0`. The `None` case covers startup, EOF-restart, and post-removal loads (no `begin()` was called).

Defaulting to 0 is safe for all three:
- **Startup / post-removal with progress:** animates from 0 to the saved position — correct, there is no meaningful "old" slider position.
- **EOF-restart:** `new_progress == 0` so `new_val == 0`, `pre == new_val`, falls into `setValue(0)` — no animation, no visible change.
- **DB duration fallback (`book_data.duration`):** used as fallback when `player.duration` is not yet cached. Sufficient to compute `new_val`; the 200ms timer corrects with the live mpv value once available. Does not affect the `_chaps_dur_retried` retry path, which guards against `player.duration` being `None` independently.

---

## flow_pending_chapter gate in _update_chapter_label_from_index — 2026-06-06

`_update_chapter_label_from_index` has two gates: `player.is_seeking` and `self._switch.flow_pending_chapter`. The second gate was added because `is_seeking` alone is insufficient in the deferred populate path.

When `_on_file_loaded_populate_chapters` is deferred (library still animating) and the seek settles before the 50ms drain fires, `_is_seeking` is already False by the time `populate()` is called. `populate()` sets row 0, emitting `currentRowChanged(0)`, which fires `chapter_changed(0)` and writes chapter 0's name to the label before `_sync_chapter_ui` can correct it.

`flow_pending_chapter` is True throughout `_on_file_loaded_populate_chapters` — `take_chapter_target()` is called after the `try` block, after `populate()`. So the gate blocks the spurious index-0 update and lifts only after the chapter animation target is established.

---

## _set_bg_suppressed re-assert uses direct color assignment, not _set_chapter_ui_active — 2026-06-06

After `content_container.setStyleSheet(...)`, Qt calls `polish()` on all child widgets, which re-reads QSS and overwrites `bg_color`/`fill_color` back to theme colors on the chapter slider. The re-assert in `_set_bg_suppressed` uses direct property assignment (`s.bg_color = QColor("transparent")`), NOT `_set_chapter_ui_active(False)`.

Calling `_set_chapter_ui_active(False)` here would: stop in-flight `bg_color`/`fill_color` QPropertyAnimations (breaking theme fades mid-transition), reset cursor and label stylesheets (side effects wrong at this site), and caused chaptered→chaptered regressions in testing. Direct color assignment is the minimal correct fix and avoids all of these.

---

## Removed preemptive _set_chapter_ui_active(False) from _on_book_selected_from_library — 2026-06-06

The unconditional `_set_chapter_ui_active(False)` before every book load hid the chapter slider regardless of whether the outgoing book had chapters. For chaptered→chaptered switches this destroyed the flow animation: the slider cleared, triggered a hide/show cycle that disrupted `when_animations_done` timing, and caused the chapter ghost. The old position — which is the animation's start point — was gone before `animate_to` could use it.

Protection for chapterless books moved to `_set_bg_suppressed`, which is the correct architectural home: it fires exactly when the repolish that needs countering happens, and only when `_chapter_ui_active` is already False (so chaptered books are unaffected).

---

## Scanner known_paths must be unfenced — 2026-06-06

`scanner.py` uses `known_paths` to skip re-extracting metadata for books already in the DB. Previously built from `get_all_books()` which filters `is_excluded=0 AND is_deleted=0`. Excluded/deleted books were therefore absent from `known_paths`, treated as new by the scanner, and passed to `upsert_books_batch` — which resets `is_excluded=0` and `is_deleted=0`, resurrecting them on every scan.

Fix: `get_all_book_paths()` queries `SELECT path FROM books` with no filter. Excluded/deleted books are now recognised as known and skipped. Side effect: folder removal + re-add no longer auto-resurrects `is_deleted` books via a non-force scan. A manual Rescan (force_refresh=True) still works. Silent resurrection was worse than requiring an explicit rescan.

---

## Theme fade must not start while any slider value animation is running — 2026-06-05

`animate_to()` on a slider while a theme fade overlay punch-through is active causes ghosting. The overlay punches a hole for each included slider, exposing the live widget. If the slider's fill position is moving, the animated fill produces a visible ghost against the static overlay screenshot.

**What is safe for themes:** color animation only (`bg_color`/`fill_color`/`notch_color` via `QPropertyAnimation` in `theme_manager.py`). Colors change inside the widget without moving the fill, so no position-ghost is produced.

**What causes ghosting:** `animate_to()` (value/fill animation) overlapping with the fade overlay's active window.

**Progress slider:** safe because `_apply_pending_cover_theme` defers via `progress_slider.when_animations_done()`. The theme fade starts only after the progress animation completes.

**Chapter slider:** safe because `_apply_pending_cover_theme` chains a SECOND wait through `chapter_progress_slider.when_animations_done()` after the progress slider. Both must settle before `apply_cover_theme` fires.

**Invariant (enforced by `_apply_pending_cover_theme`):** cover art theme fade starts only after BOTH `progress_slider` AND `chapter_progress_slider` animations have finished. If any new slider gets `animate_to()` during book switches, add it to the chain.

---

## _set_bg_suppressed must use _active_display_theme, not _current_theme_name — 2026-06-05

`_set_bg_suppressed` regenerates `content_container`'s stylesheet by calling `get_player_stylesheet(theme_name, suppress_bg_image=...)`. Using `_current_theme_name` (the named pool theme) instead of `_active_display_theme` (which holds the cover dict when a cover theme is active) causes a one-frame flash to the pool theme on every book switch, because `apply_library_state` calls `_set_bg_suppressed(False)` on each switch.

Fix: `theme_name = getattr(tm, '_active_display_theme', None) or tm._current_theme_name`.

---

## Chapter slider background: preemptive _set_chapter_ui_active(False) at book switch — 2026-06-05

The chapter slider background becomes briefly visible during book switches. Root cause: `apply_current_state → apply_library_state → _set_bg_suppressed` repolishes child widgets (via `content_container.setStyleSheet`) resetting the chapter slider's `bg_color` from transparent back to the theme color, before `_on_file_loaded_populate_chapters` calls `_set_chapter_ui_active(False)`.

Fix: call `_set_chapter_ui_active(False)` preemptively in `_on_book_selected_from_library` at selection time. The slider stays transparent throughout the loading window. `_on_file_loaded_populate_chapters` restores it to active only when chapters are confirmed.

Also: `_set_chapter_ui_active(False)` must stop any running `bg_color`/`fill_color` QPropertyAnimations on the chapter slider before setting transparent. A theme fade that started while the book had chapters creates color animations targeting non-transparent values; they override the transparent assignment on the next animation frame.

---

## Library sort: computed keys must not be passed to get_all_books() — 2026-06-05

`"finished"` is computed in-memory by `BookModel` from `_finished_dates`; it is not a DB column and is not in `db._ALLOWED_SORT_COLUMNS`. Any code path that passes a `SORT_KEY_MAP` value to `get_all_books()` must guard against computed keys:

```python
if sort_key not in self.db._ALLOWED_SORT_COLUMNS:
    sort_key = "title"
```

Currently applies to `start_idle_preload`. Any future method with the same shape needs the same guard.

---

## _finished_dates is the source of truth for Finished sort/filter — 2026-06-05

`BookModel._finished_dates: dict[int, datetime]` is populated via `db.get_finished_book_data()` in `LibraryPanel.refresh()`. It is the sole authority for whether a book is "finished" and when it was last finished.

`books.finished_at` exists on the schema but is **never written** anywhere in the codebase. Do not read it for Finished-related logic. Either implement the write or drop the column in a future migration — currently harmless but confusing.

The `effective_val` / `have-missing` split in `_apply_filter_and_sort` handles `"finished"` via `self._finished_dates.get(b.id)` — **not** `getattr(b, "finished", None)`. The field does not exist on `Book`; `getattr` would return `None` for every book, silently dumping the entire Finished view into `missing`.

---

## Sort key and direction must be saved to config together — 2026-06-05

`_on_sort_changed` saves both `sort_key` and `sort_ascending` to config whenever the user switches sort keys. `_toggle_sort_direction` saves only the direction. This means config always reflects exactly what's shown.

Saving the key without the direction (or vice versa) produces wrong state on next startup: if the key's default direction differs from the last-saved direction, restoring only the key applies the default instead of the user's last state.

When `_rebuild_sort_combo` falls back to Title (because a conditional key like Progress/Finished is no longer valid), it applies Title's default direction and saves both key and direction to config immediately — not the removed key's direction.

---

## Finished-books carousel cover loading (stats_panel.py) — 2026-06-04

`FinishedBookThumb._on_cover_loaded` now writes to `_cover_cache[self._book_id]` before
calling `_apply_cover`, matching the library grid's pattern. Previously the worker result
was consumed locally and discarded, causing cold-cache misses on every carousel rebuild for
custom-cover books and excluded/deleted finished books (which the preloader skips entirely,
since `get_all_books` is fenced by `is_deleted = 0 AND is_excluded = 0`). Fix: cache write
in `_on_cover_loaded` + `self._book_id` stored in `__init__`.

`FinishedScrollRow.set_items`:
- **2026-06-08 revision:** the original `_current_ids` guard (set equality on `book_id`)
  caused the Overall tab's "recently finished" carousel to go stale — its top-20 membership
  rarely changes day-to-day, so the guard kept skipping rebuilds even when order, covers, or
  `is_deleted` (location-resurrection) changed. Day/Week/Month's churnier period-scoped lists
  masked the same bug because their membership changes often enough to pass the set check.
  Replaced with `_current_sig`: an order-sensitive list of
  `(book_id, event_time, active_cover_path/cover_path, is_deleted)` tuples. This deliberately
  re-introduces order-sensitivity — order changes ARE meaningful now (re-finishing reorders
  the list) — while still skipping the rebuild in the common truly-unchanged case, preserving
  the perf/flash guard the original code wanted (no widget churn during the panel-open slide).
- ~~`_current_ids` guard (set equality, not list equality)~~ — superseded above. The original
  concern (`_invalidate_period_cache()` re-running the query and changing row order with no
  real change) is still valid, but set-equality threw out too much signal; the richer
  signature distinguishes "real reorder" from "incidental reorder" via `event_time`.
- `setParent(None)` replaces `deleteLater()` for synchronous widget removal — `deleteLater`
  is deferred and left old widgets in the layout during rapid successive calls.
- `setMinimumWidth` computed after population (`n × 47 + (n−1) × 4`) so the container
  overflows correctly with `setWidgetResizable(True)`. Without this, `setWidgetResizable(True)`
  forces the container to viewport width, compressing fixed-size thumbs instead of scrolling.

First-visit cold-cache flash (startup, books not yet reached by preloader) is accepted
behaviour. All subsequent visits for the same book IDs are cache hits.

---

## Suppressing a theme `bg_image`: only regeneration works, not child override (2026-06-03)

The theme `bg_image` (Overlook hexagons, etc.) is painted by `content_container`'s
`QWidget#visual_area { background-image: url(...) }` rule (`get_player_stylesheet`). In
the no-book and empty-library states it overlapped the prompts / carousel / quote. Goal:
strip the image in those two states, keep it everywhere a book is loaded.

**What was tried and failed:**

1. **Rename `carouselActive` → `bgSuppressed` and set the property in the state machine.**
   No change. The original `carouselActive` mechanism never actually suppressed anything —
   the no-book state already showed the image with the carousel fully built (so the
   property *was* set). Renaming a non-working rule does nothing.
2. **Instance stylesheet on `visual_area` itself: `background-image: none`.** No change.
   A red-background diagnostic proved why: setting `QWidget#visual_area { background-image:
   none; background-color: red }` as the child's own stylesheet **did** turn the area red,
   but the image layered *on top of the red*. So the child stylesheet applies fine — but
   **Qt's QSS cascade treats `background-image: none` as "unspecified"**, so the ancestor
   rule's `url()` wins on the child per-property. `background-color` (a real value) overrode;
   `background-image: none` was silently dropped. No child override can kill an ancestor's
   background-image. (The `QGraphicsBlurEffect` on `visual_area`, suspected as a pixmap-cache
   culprit, was a red herring — `blurRadius` is 0 except during panel transitions, and the
   red proved repaints propagate fine.)

**What worked:** regenerate `content_container`'s stylesheet **without** the image.
`get_player_stylesheet(theme_name, suppress_bg_image=True)` omits the `bg_image` from the
`#visual_area` rule entirely — the only reliable kill, since the image is simply never
emitted. `MainWindow._set_bg_suppressed` is the single authority: it sets `_bg_suppressed`,
calls `setAutoFillBackground(False)` (so the transparent `visual_area` lets the carousel
stripe / themed window bg show through), and re-applies the regenerated stylesheet.
`apply_library_state` drives it (`True` for empty + no-book, `False` for has_book), and
`ThemeManager._apply_stylesheets` reads `_bg_suppressed` so a theme change in those states
doesn't re-introduce the image.

**Why this over hiding image-themes from the pool:** the alternative (suppressing the
themes themselves) would have meant a visible gap in the theme pool shown in Settings —
ugly and confusing. Stripping the image per-state keeps every theme selectable.

---

## Wrapping a `QHBoxLayout` in a `QWidget` loses inter-item spacing (2026-06-03)

When a `QHBoxLayout` is assigned directly to a parent `QVBoxLayout` (via `addLayout`), it fills the parent's full width and inherits style-derived spacing (~6px). When the same layout is instead assigned to a `QWidget` wrapper (for naming/visibility purposes) and that widget is added via `addWidget`, two things break: (1) the widget shrinks to wrap its children's fixed sizes instead of filling available width, and (2) `setContentsMargins(0,0,0,0)` on the inner layout does NOT reset spacing — but the previous lack of an explicit `setSpacing` relied on style defaults that may not apply in all states. Always call `setSpacing(N)` explicitly on any `QHBoxLayout` inside a `QWidget` wrapper so the spacing is not state-dependent. Also set `setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)` on the wrapper widget so it fills available width like a bare layout would.

Root cause of the transport button alignment regression introduced in the `4b55058` refactor.

---

## Carousel geometry (2026-06-03)

- `CoverCarousel` is parented to `content_container`, not `visual_area` or `carousel_holder`. `setGeometry(0, y, CAROUSEL_STRIPE_W, carousel_h)` where `y = carousel_holder.mapTo(content_container, QPoint(0, 0)).y()`. `stackUnder(self.visual_area)` keeps it behind the label and button.
- `visual_area`'s `bg_image` must be suppressed while the carousel shows, or a theme with a bg_image paints over the stripe center. This is now handled by the state machine, not the carousel: `apply_library_state`'s no-book branch calls `set_bg_suppressed(True)` before `show_carousel()`. Suppression works by regenerating `content_container`'s stylesheet without the image (`get_player_stylesheet(..., suppress_bg_image=True)`) — see the bg_image-suppression note above for why a child-widget override (the old `carouselActive` property) could not work. `_show_carousel`/`_hide_carousel` no longer touch `carouselActive` or `autoFillBackground`.
- `carousel_bg` → fill. `carousel_stripe` → 1px border lines. Both fall back to `bg_main` (not `bg_deep` — every theme has `bg_main`).
- `set_stripe_color` always recomputes line color; `_line_color_explicit` is `__init__`-only. If this flag ever bleeds into `set_stripe_color`, themes will steal each other's line colors on rotation.

---

## Cover placeholder (2026-06-03)

- `_show_cover_placeholder()` intercepts both no-cover exits in `_load_cover_art` — the `else` branch only. The early `not file_path` return (no-book state) is untouched; `cover_art_label` stays hidden there.
- `render_logo_placeholder(color, size)` lives in `icon_utils.py` — single implementation. Stats panel and tag manager both import it as `_render_svg_placeholder`. Don't reimplement it locally.
- `render_logo_placeholder_bordered(color, icon_size, canvas_w, canvas_h, offset_y=0)` also lives in `icon_utils.py` — renders the logo centered on a fixed canvas with a 2px border. Used by book detail panel, stats panel, and tag manager thumbnails.
- `_showing_placeholder` flag: set by `_show_cover_placeholder()`, cleared at the top of `_apply_main_cover`. Theme refresh: `_reload_button_icons` calls `_show_cover_placeholder()` again if flag is set.
- Placeholder border: shown in thumbnail contexts (book detail header, stats rows, tag thumbnails) only — not in the main cover area where the logo fills sufficient space.
- Theme keys: `placeholder_cover` (main player), `placeholder_stats`, `placeholder_tags` — documented in `themes.py` docstring with fallback chains.

---

## Theme rotation weight exponent — tuned to 1.0 (2026-05-31)

`_do_rotate` weights candidates as `1.0 / (distance ** exp + ε)`. The original exponent was 1.5. Simulated over 10,000 rotations with all 57 themes in the pool:

| Exponent | Min pick rate | Max pick rate | Ratio |
|---|---|---|---|
| 1.5 (original) | 0.9% | 3.0% | 3.4× |
| **1.0 (current)** | **1.1%** | **2.5%** | **2.2×** |
| 0.5 | 1.2% | 2.3% | 1.9× |

1.0 was chosen: flattens the distribution meaningfully without the ordering inversions that appear at 0.5 (e.g. Lilac Girls surges above themes that beat it at 1.5 for no perceptual reason). The "prefer visually different" ordering is preserved — just less aggressively amplified.

Do not lower the exponent further without re-running the sim. At 0.5 the weights are so flat that the distance exclusion filter (step 4) does most of the work alone, and the weight curve stops adding meaningful signal.

## Theme fade — slider color animation + label freeze (2026-05-30)

`ClickSlider` widgets repaint immediately on QSS repolish, producing a ghost during the overlay fade. Fixed in `theme_manager.py` by punching slider rects out of the overlay mask and animating `bg_color`/`fill_color`/`notch_color` via `QPropertyAnimation`. Works because sliders paint their full rect — the hole exposes the slider itself, not the window background.

**Labels** cannot use punch-holes (transparent background would expose the freshly-themed window bg = rectangle flash). Six overlay/rendering approaches failed (see SESSION.md 2026-05-30 Session 2). Fixed instead with `FreezableLabel` — text is pinned for the fade duration so the live label and overlay screenshot are always identical, making a ghost impossible.

**`FreezableLabel(QLabel)`** in `controls.py`: `setText` is a no-op while frozen. `ScrollingLabel` inherits it. The four time labels are `FreezableLabel` at construction; `ScrollingLabel` (chapter label) gains freeze for free. Chapter label is force-refreshed on unfreeze via `chapter_list` + `time_pos` epsilon walk so a chapter change during the freeze doesn't leave it stuck.

**Tradeoff:** Labels pause for 750ms on every theme change. The freeze feels more prominent than expected because there is no color motion to mask it — earlier experiments with color animation on frozen labels made the freeze less perceptible but introduced other artifacts. Accepted as the cleanest outcome.

---

## App audit pass — 2026-05-29 (refactor/app-audit)

Six audit passes applied as a single branch. All items below confirmed landed.

**Invariant violations fixed:**
- `self.player.chapter` direct read in `_sync_playback_state` replaced with epsilon walk (invariant #1 — async chapter property). Now walks `chapter_list` finding last entry `<= pos + _CHAPTER_BOUNDARY_EPSILON`.
- `refresh_overall()` inside EOF block was firing every 200ms at EOF — now inside the `if not self._eof_event_written` guard, fires exactly once per EOF event.
- `#Temporary` comments removed from EOF handling block — the behavior is permanent, not provisional.

**None guards added:**
- `_on_slider_released`: `old_pos = self.player.time_pos or 0.0`
- `_on_chap_slider_released`: same
- `_on_slider_right_clicked`: added `if self.player.mp3_seek_reload_pending: return` after the duration guard

**Initialization fixes:**
- `_mpv_ready`, `_pre_switch_slider_value`, `_pre_switch_chap_slider_value` now all initialized unconditionally in `__init__` (previously only set on some code paths, causing `AttributeError` if relevant methods ran before first book load)
- `session_written.connect` moved from `_build_book_detail_panel` to the player signal block in `__init__`

**Dead inner imports removed:**
- `import re` inside `_classify_filter`
- `from PySide6.QtCore import Qt` inside `_update_chapter_label_clickability`
- `from PySide6.QtGui import QPainter` inside `_update_cover_art_scaling`

**Method relocations:**
- `_classify_filter` and `save_search_filter` moved from `MainWindow` to `LibraryPanel` — they belong with the widget that owns the search field. `closeEvent` now calls `self.library_panel.save_search_filter()`.

**SessionRecorder extraction:**
- All session state and persistence moved to `SessionRecorder(QObject)` in `session_recorder.py`
- `MainWindow` retains `_current_book`; recorder reads it via lambda
- `session_written` signal ownership transferred to `SessionRecorder`; `MainWindow.session_written` removed
- `update_furthest_position()` replaces inline furthest-pos tracking in the 200ms UI loop
- `notify_seek()` replaces duplicated seek-credit logic in both slider released handlers
- `threading` and `datetime` imports removed from `app.py` (now owned by recorder)
- Session record and discard paths confirmed working manually

**DB migration:**
- `set_started_at` / `get_book_started_at` migrated to `book_id` parameter (no `book_path` lookup). Only call site is `session_recorder.py`.

---

## Deferred: drop deprecated `book_path` args from write_session / write_book_event (2026-05-29)

`write_session` and `write_book_event` still accept and write `book_path` alongside `book_id`. The `book_path` columns in `listening_sessions` and `book_events` are not queried but are retained for easy rollback. When ready: remove the `book_path` parameter from both method signatures, drop the column writes, then run the column-drop migration pass described in the existing "drop deprecated book_path columns" entry below.

## Deferred: book_files not yet migrated to book_id FK (2026-05-29)

`book_files` still uses `book_path TEXT` as its composite primary key `(book_path, file_path)`. Migrate when VT is next being actively worked on.

## Deferred: panel construction and animation sequencing debt — P2-C + P6-A + P6-D (2026-05-29)

Three fragilities with a shared root. Fix together in one deliberate structural pass — do not touch individually.

**P2-C — PanelManager patched post-construction (low):**
`PanelManager` is constructed before `_build_book_detail_panel` runs. `panel_manager.book_detail_panel` and `panel_manager.book_detail_panel_animation` are manually patched at lines ~1321–1322 after the fact. `PanelManager` does not own all its panels at construction time. Not broken, but fragile.

**P6-A — `book_ready` two-slot deferred mechanism (medium):**
`player.book_ready` connects to both `_on_file_ready` and `_on_file_loaded_populate_chapters`. Both check `library_panel._is_animating` and set their own deferred flags (`_file_ready_deferred`, `_chaps_deferred`). `_drain_deferred_file_ready` handles both. The two independent flags are functional but fragile — if one fires but the other fails to drain (e.g. due to a VT file-load ordering race), state is inconsistent.

**P6-D — `QTimer.singleShot(320ms)` in `_on_open_tag_manager_from_detail` (known debt):**
`app.py:1075` (was ~1713): `QTimer.singleShot(320, self.panel_manager._open_tags_flow)`. 320ms is a magic number covering the longest panel *position* close animation (300ms) + 20ms margin. The correct fix is an `all_panels_hidden` signal from `PanelManager`, emitted when the last running close animation completes. **Design must decide whether `blur_animation` (500ms) counts toward "hidden" — see the "hide_all_panels then open: timer vs signal" entry below for the full design and the blur caveat.** Single site, no duplication (confirmed REVIEW_PASS8 #6).

**Fix trigger:** When mini player mode is built, panel construction order will be rationalized anyway. Fix all three then.

## Deferred: `_update_pattern_visuals` duplication (2026-05-29)

`_update_pattern_visuals` in `app.py` and its equivalent in `settings_controller.py` share overlapping responsibility for updating the pattern button visual state. The duplication was noted but not resolved in the audit pass — fixing requires confirming which call sites use which path and whether either can be removed. Address in the next settings-panel pass.

## `KEY_Q` quote rotation shortcut — remove before release (2026-06-02)

`keyPressEvent` fires `library_controller._rotate_quote()` when `Key_Q` is pressed and `not self.current_file and self.quote_section.isVisible()`. Testing aid only. Remove before release. Marked `# TODO: remove before release — testing only` in `app.py`.

---

## mpv hangs silently on seeks within 2s of file end — buffer required on every seek path (2026-05-29)

Seeking mpv to a position within approximately 2 seconds of a file's `duration` causes it to hang silently — no error, no EOF event, no recovery. The buffer must be present in every seek path that calls `command_async` or `loadfile start=`.

Current guards in `seek_async` (player.py):
- **VT same-file branch**: `if target_file['duration'] - local_pos < 2.0: return` — placed after the stop-and-load block, before `command_async`.
- **Non-VT branch**: `if dur and dur - pos < 2.0: return` — placed before the stop-and-load check.
- **stop-and-load (VT)**: condition already includes `local_pos < target_file['duration'] - 5.0` — covered.
- **stop-and-load (non-VT)**: `_mp3_stop_and_load` uses `loadfile start=X`; the non-VT guard above fires first and prevents it from being called near EOF.

Do not remove these guards. Do not add a seek path to `command_async` or `loadfile` without including a 2s (minimum) buffer from the file's duration.

## Stats inflation: `LEFT JOIN book_events` before GROUP BY produces cartesian product (2026-05-29)

`get_daily_book_breakdown` and `get_books_listened_in_period` in `db.py` were joining `book_events` before the `GROUP BY`, producing one row per `(session, finished_event)` pair. If a book had N finished events, `SUM(listened_seconds)` was inflated by N. Fixed by replacing the join with a correlated scalar subquery:

```sql
(SELECT MAX(CASE WHEN be.event_type = 'finished' THEN 1 ELSE 0 END)
 FROM book_events be WHERE be.book_id = b.id) as is_finished
```

Rule: never join `book_events` directly into a query that also aggregates `listening_sessions`. Always use a scalar subquery for the `is_finished` flag.

## `_cached_time_pos` holds local position for VT books — never set it to global (2026-05-29)

`_cached_time_pos` is the raw value observed from mpv's `time-pos` property. For VT books mpv only knows about the current file, so `_cached_time_pos` is always file-local. The `time_pos` getter adds `_file_offset` to translate to global book position: `return self._file_offset + self._cached_time_pos`.

Consequence: **never assign a global position to `_cached_time_pos` in a VT context**. Doing so causes `time_pos` to return `_file_offset + global_pos`, inflated by exactly `_file_offset`. This was the root cause of the 0% reset bug in VT stop-and-load: `_mp3_stop_and_load` was setting `_cached_time_pos = target_pos` (global), inflating `time_pos` during the reload window, and `handle_forward`/`handle_rewind` were reading that inflated value and seeking to a wrong position.

Correct assignment: `_cached_time_pos = local_pos if local_pos is not None else target_pos`. For single-file calls `local_pos is None` and `target_pos == local_pos`, so no change in behaviour.

## `handle_forward` / `handle_rewind` — two independent guards required (2026-05-29)

Both methods must guard on `not self.player.mp3_seek_reload_pending` **and** check `if old_pos is None: return` after reading `time_pos`. These are separate failure modes:

1. `mp3_seek_reload_pending` guard: prevents entering the method at all while a reload is in flight, which avoids reading a potentially corrupt `time_pos`.
2. `old_pos is None` guard: `time_pos` can still return `None` during the reload window (mpv observer fires before the property is populated after `loadfile`). `None - skip` in Python raises `TypeError`; historically the code used `(old_pos or 0) - skip` which silently became `0 - skip` and sought to near the start of the book.

Both guards are required. Removing either reintroduces a distinct bug.

## Theme repolish overrides `_set_chapter_ui_active` state — always reapply after theme change (2026-05-29)

`_apply_stylesheets` calls `setStyleSheet` on `content_container`, which triggers a Qt repolish of all child widgets. This clears instance stylesheets and cursor overrides set by `_set_chapter_ui_active(False)` — after a theme change, the chapter UI appeared interactive again for books without chapters.

Fix: `_chapter_ui_active: bool` flag in `app.py` tracks the logical state. `_set_chapter_ui_active` sets the flag. `_apply_stylesheets` calls `mw._set_chapter_ui_active(mw._chapter_ui_active)` at its end to reapply. `_set_chapter_ui_active` is idempotent so repeated calls are safe.

## `_mp3_seek_reload_pending` concurrent reload guard (2026-05-29)

`_mp3_stop_and_load` must not be called while `_mp3_seek_reload_pending` is already `True`. Without this guard, stacked `loadfile` calls cause the second `_on_file_loaded` to go through the normal post-load path instead of the early-return block, emitting `book_ready` and triggering position restore from DB — resetting playback to the saved progress position.

Both call sites in `seek_async` (VT same-file branch and non-VT branch) include `and not self._mp3_seek_reload_pending` in their conditions. If a reload is already in flight the new seek request is silently dropped (normal `command_async` fallthrough still available for the non-VT path if the distance check also fails).

## `seek_within_chapter` has no EOF guard — intentional (2026-05-28)

`seek_within_chapter` does not guard on `self._eof`. An EOF guard was added and removed in the same session. The reason: `seek_async` clears `_eof` internally, so any positional seek correctly transitions out of EOF state. Mouse wheel on the chapter slider already worked at EOF for this reason. Click/drag on the chapter slider must behave the same way. The EOF guard belongs on directional advances (`next_chapter`, `handle_forward`) that should be inert once EOF is reached — not on positional seeks that the user explicitly initiates.

## `next_chapter` last-chapter boundary — no fallback to `_book_duration` (2026-05-28)

Both VT and non-VT branches of `next_chapter` now return early when `curr_chap >= len(chap_list) - 1`. The old `else: seek to _book_duration or duration` fallback is gone. For non-VT: seeking past the last chapter caused state corruption on rapid >| clicks. For VT: EOF is reached naturally when the last file finishes playing — forcing a seek to `_book_duration` was redundant and wrong. If `next_chapter` is ever touched again, do not restore the `_book_duration` fallback.

## `chap_duration_label` cursor owned by `_set_chapter_ui_active` (2026-05-28)

`chap_duration_label.setCursor(Qt.PointingHandCursor)` was set unconditionally in `_build_secondary_controls`. It was moved to `_set_chapter_ui_active` so the cursor state is managed alongside the chapter UI active/inactive toggle. Active: `PointingHandCursor`. Inactive (no chapters): `ArrowCursor`. If `_build_secondary_controls` is ever refactored, do not re-add the unconditional cursor set there.

## Deferred: drop deprecated `book_path` columns from session/event/tag tables (2026-05-28)

`listening_sessions`, `book_events`, and `book_tags` retain `book_path TEXT` columns that are no longer written or queried — kept for now to allow easy rollback. When ready to drop: a single migration pass in `_create_tables` using `PRAGMA table_info` + `CREATE TABLE … AS SELECT` (SQLite doesn't support `DROP COLUMN` below 3.35; check version or use the full table-rebuild pattern). No logic changes required — all query paths already use `book_id`.

## Deferred: migrate `book_files` to `book_id` FK (2026-05-28)

`book_files` still uses `book_path TEXT` as its composite primary key `(book_path, file_path)`. Migrate this when VT (virtual timeline) is next being actively worked on — the table is internal to the VT/scanner path and the change is isolated there.

## `get_listening_time_per_period` — orphaned sessions collapse under NULL book_id (2026-05-27)

`get_listening_time_per_period` groups by `period, book_id` and selects `book_path` alongside it. For rows where `book_id IS NULL` (sessions whose book path had no match in `books` during the migration backfill, or sessions written before the migration), SQLite treats all NULLs as equal in GROUP BY, so multiple orphaned books collapse into a single row. The `book_path` column in that row will be whichever path SQLite happens to pick from the group — not reliable.

This was already a degenerate case: before the migration, `book_path` was the key and orphaned sessions were at least grouped correctly per path. After migration, correctness depends on the backfill having matched all paths. In practice, all in-library sessions (including for `is_deleted=1` books) are backfilled correctly because `books.id` still exists. Only sessions for paths that were hard-deleted from the `books` table (which the app never does) would have `book_id = NULL`.

**Consequence:** `get_listening_time_per_period` results are only consumed by the stats heatmap (`get_hourly_heatmap` is separate). Low impact. No fix planned; document for awareness.

## `ContextIconMenu` — `self.window()` returns the menu itself under Popup window type (2026-05-27)

`ContextIconMenu` uses `Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint`. Under this window type, `self.window()` returns the widget itself — not the top-level application window — because Popup creates a new top-level window in Qt's hierarchy. Using `self.window().width()` / `.height()` for position clamping therefore clamps against the menu's own 126×36px bounds, not the app window. Fix: use `QApplication.activeWindow()` instead. Guard against `None` (returns `None` when the app is not focused or during shutdown).

## `ContextIconMenu` — `WA_TranslucentBackground` wipes the background despite `WA_StyledBackground` (2026-05-27)

Setting `WA_TranslucentBackground` on a `QWidget` subclass that also uses `WA_StyledBackground` causes the QSS `background:` rule to be ignored — the widget renders fully transparent even with a valid stylesheet. The two attributes conflict: `WA_TranslucentBackground` forces alpha compositing at the window level, which punches through the QSS paint. Remove `WA_TranslucentBackground` and rely solely on `WA_StyledBackground` + the QSS `background:` rule for solid background rendering.

## `hide_all_panels` then open: timer vs signal (2026-05-26)

`_on_open_tag_manager_from_detail` in `app.py` calls `panel_manager.hide_all_panels()` then uses `QTimer.singleShot(320, panel_manager._open_tags_flow)` to delay the open until all close animations have finished. 320ms is chosen to clear the longest panel close animation (300ms).

**Why this is debt:** The 320ms is a magic number. If any panel animation duration is changed, this delay silently breaks. The correct approach is a signal: `PanelManager` should emit an `all_panels_hidden` signal after the last running close animation completes. `hide_all_panels` would need to track which animations were started (count or set), and each `_on_*_hidden` callback would decrement the count and emit the signal when it hits zero. The caller would connect to `all_panels_hidden` with a one-shot connection.

**Why the timer was used:** `hide_all_panels` runs multiple close animations in parallel with no shared completion point. Adding the count-down mechanism was a larger change than warranted for a single use case. If a second "hide-all-then-open" flow is added anywhere, the signal approach becomes mandatory.

**⚠ Blur caveat — decide this when designing the signal (REVIEW_PASS8 #6):** the close flow runs TWO kinds of animation in parallel: the panel *position* slide (300ms; tags 200ms) AND `blur_animation` (**500ms**, `app.py:556`). The 320ms timer only clears the *position* slide — at T+320ms the blur fade is still running, and `_any_panel_animating()` (`panels.py:544`) counts blur, so "all panels hidden" is NOT literally true at 320ms. The reopen works anyway because it only needs the panel off-screen (position done at 300ms); blur is cosmetic and the reopen re-drives it. **So the `all_panels_hidden` signal must choose:** (a) fire when the last *position* animation completes (≈ current 320ms behavior, ignore blur) — simplest, preserves today's timing; or (b) wait for blur too (~500ms) — "truly idle" but ~180ms slower to reopen, a deliberate behavior change. Recommend (a): exclude `blur_animation` from the count, because the reopen contract is "panel off-screen," not "no pixels moving." Whichever is chosen, document it at the signal definition so the next person doesn't re-derive this.

**Where to fix:** `panels.py` — `hide_all_panels` and each `_on_*_hidden` method (track a started-count, decrement per `_on_*_hidden`, emit at zero; decide blur per the caveat above). `app.py` — replace `singleShot(320, ...)` with a one-shot `all_panels_hidden` connection.

## `QStackedLayout` for mutually exclusive UI slots (2026-05-25)

When multiple widgets need to occupy the same fixed space with only one visible at a time, `QStackedLayout` inside a fixed-height container is the correct pattern. `.show()`/`.hide()` on siblings in a regular layout shifts surrounding content as each sibling collapses; `QStackedLayout` holds the reserved space constant regardless of which page is current. Pattern: create a `QWidget` with `setFixedHeight(N)`, assign a `QStackedLayout` to it, add all candidate pages (including a blank `QWidget` as the "empty" page), default to `setCurrentWidget(empty_page)`, and switch via `setCurrentWidget`. Store the layout reference on `self` for access from other methods.

**Concrete value (tag manager):** the reserved row in `tag_manager.py` is `self._reserved_row`, a `QWidget` with **`setFixedHeight(21)`** (`tag_manager.py:336`) wrapping the `QStackedLayout` whose three pages are `_reserved_empty` / `_color_picker_row` / `_confirm_delete_label`. The height is **21px, not 32** — REVIEW_PASS8 #2 flagged a checklist that said 32px; that figure was never in any project doc, and the code has correctly been 21 all along. Recording the real value here so future audits reference 21 and don't re-flag a non-issue. No call site overrides it.

## `_set_tag_color` — must not call `refresh()` or `_open_tag()` (2026-05-25)

Tag color change requires exactly three operations: DB write (`db.set_tag_color`), detail dot update (`_update_detail_dot`), list row dot update (`_update_list_dot`). `refresh()` rebuilds the entire tag list widget tree and reloads all cover images — correct for tag renames and deletions, but grossly unnecessary for a color change where no count, name, or book membership changes. `_open_tag()` would re-query books and rebuild the book grid. Any future change to `_set_tag_color` must preserve this constraint: patch in-place, do not rebuild.

## Deferred (low/UX): tag action button `check → delete` 2s timer can silently revert a slow edit (2026-06-12)

After a successful rename, `_on_rename` sets the action button to `check` then arms an **unguarded** `QTimer.singleShot(2000, lambda: self._set_action_mode("delete"))` (`tag_manager.py:622`). If the user starts a *new* rename within those 2s, `_on_tag_name_changed` moves the button to `save`, but the still-pending singleShot fires at T+2s and forces it back to `delete` — **silently reverting the in-progress edit's button state**. Phrased precisely: a user who types a single character and then pauses (entirely plausible for short tag names) will see their input's save-affordance disappear before the next keystroke restores it. It is NOT a correctness bug — the edit field text is untouched and the next keystroke re-sets `save` — but it is a real UX papercut, not a benign "self-heal." Deferred as low-priority debt. Fix when touched: capture the timer (or a generation token) and cancel/invalidate it in `_on_tag_name_changed` when the state moves to `save`. Was REVIEW_PASS8 finding #1.

## `terminate()` regression pattern — four-step sequence is atomic (2026-05-22)

`Player.terminate()` lost `wait_for_shutdown()` with no git trace — it was either never committed without it or dropped silently during a refactor. The four-step sequence must be treated as atomic: store the instance reference, clear `self.instance`, call `terminate()`, then call `wait_for_shutdown()`. Without `wait_for_shutdown()`, libmpv's internal threads outlive Qt's cleanup and crash in `avformat_close_input`. `wait_for_shutdown()` is a python-mpv API method — no custom implementation needed or appropriate. Any "simplification" that removes or reorders these steps will reintroduce the crash, possibly masked again by debug output.

## `_cover_cache` shared reference — tag thumbnails use library cache (2026-05-22)

`tag_manager.py` imports `_cover_cache` directly from `library.py` (`from .library import _cover_cache`). It is the same dict object the library panel populates — not a copy. `_TagBookThumb.__init__` checks this cache synchronously: a hit calls `_apply_cover` inline with no worker and no queued signal, so the pixmap is set before the widget is shown. This is why `_rebuild()` is safe to call on remove without cover flicker. If the cache strategy ever changes in `library.py` (eviction policy, key type, etc.), tag thumbnails are directly affected.

## `color:` QSS does not colorize QIcon pixmaps (2026-05-21)

Qt's `color:` CSS property affects text rendering only. It has no effect on `QIcon` pixels — the pixmap is painted as stored. To tint an SVG icon to a theme color, the color must be substituted directly into the SVG source before rendering, not applied via stylesheet.

## PySide6 does not honor `currentColor` in SVGs (2026-05-21)

`QSvgRenderer` does not resolve the CSS `currentColor` keyword against the widget's palette. SVGs that use `currentColor` for fill/stroke will render black (or transparent). Color must be baked into the SVG bytes at load time. The fix: read SVG as text, regex-substitute all `fill="..."` / `stroke="..."` attributes and `fill:` / `stroke:` inline style properties (Inkscape exports the latter), then render to a `QPixmap` sized to `renderer.defaultSize()`.

The `style="..."` pass is not optional — Inkscape SVGs exported with "plain SVG" or without explicit attribute export use inline CSS on the `<path>` element and the attribute-level regex will miss them entirely.

## `to_grayscale` and alpha channel (2026-05-20)

`Format_Grayscale8` drops the alpha channel — transparent pixels become black. Affects the placeholder logo cover when displayed for archived books. Fix: composite onto the themed background color before converting. Revisit when the app icon is finalized/vectorized. Lives in `to_grayscale()` in `cover_loader.py`.

## `_is_archived` ordering in `load_book()` (2026-05-20)

`_is_archived` and any flag that gates visual state must be set before any method that reads it is called in `load_book()`. Easy to regress as `load_book` grows — the cover block must always come after the archived detection block. The original implementation had it backwards; that was caught and fixed in session 2 of 05.20.

## `deleteLater()` and layout repaint (2026-05-20)

`deleteLater()` defers widget destruction to the next event loop iteration. If a layout doesn't visually update after a grid rebuild, a `refresh_current_tab()` or equivalent repaint trigger is needed to force Qt to process the deferred deletions and re-render.

## `AppInterface` is not the main `App` object (2026-05-20)

Attributes on the main app (e.g. `stats_panel`) are not accessible via `self.app` in `library_controller.py` — `self.app` is `AppInterface`, a thin proxy. Add a wrapper method to `AppInterface` for any new cross-panel call from the controller. Do not access `self.app.<main_attr>` directly.

## Stats panel cover loading — `_inject_active_covers` performance note (2026-05-20)

`_inject_active_covers` does one `get_active_cover_path` DB query per book, synchronously on the main thread. Acceptable for current list sizes. If the Month view with many books becomes perceptible, batch into a single `WHERE path IN (...)` query and return a dict keyed by path.

## `_iter_day_rows` — unrendered tab safety (2026-05-20)

`_iter_day_rows` uses `getattr(self, '_week_rows_layout', None)` and `getattr(self, '_month_rows_layout', None)`. These attributes may not exist if those tabs have never been rendered (Qt defers tab content until first visit). The method returns silently on `None` — this is intentional. Do not change to a direct attribute access.

## `active_cover_changed` signal widening — call site contract (2026-05-20)

`BookDetailPanel.active_cover_changed` was widened from `Signal(str)` to `Signal(str, str)` — `(book_path, cover_path)`. `CoverPanel.active_cover_changed` remains `Signal(str)`. The intermediate slot `_on_cover_panel_changed` in `BookDetailPanel` bridges them. Any future slot connected to `BookDetailPanel.active_cover_changed` must accept both positional args.

## Metadata lock feature (2026-05-19)

Four independent lock columns on `books`: `title_locked`, `author_locked`, `narrator_locked`, `year_locked` (all `INTEGER NOT NULL DEFAULT 0`). Locks are set per-field on save (`_commit_inline_save`), cleared all-at-once on unlock. Persisted to DB via `set_metadata_locks()` and read via `get_metadata_locks()`.

**Upsert protection:** The ON CONFLICT block in both `upsert_book` and `upsert_books_batch` uses `CASE WHEN books.X_locked = 1 THEN excluded.X ELSE updated.X END` for all four fields. This prevents rescans from overwriting user edits. Narrator and year preserve their existing `COALESCE(NULLIF(...), ...)` guards inside the ELSE branch (respecting existing empty-field behavior).

**Rescan resurrection:** Locks reset to 0 in the ON CONFLICT block alongside `is_deleted` and `is_excluded` — rescanning brings back locked metadata unchanged, but allows overwrite on the next rescan if locks aren't re-set.

**UI state machine:** `_MetaActionState` enum (HIDDEN, DIRTY, LOCKED, UNLOCKED) drives the metadata action button exclusively. DIRTY = save icon on keystroke, LOCKED = lock icon after save, UNLOCKED = lock-open icon after unlock click, HIDDEN = no button. Pre-edit state saved in `_enter_edit_mode`, restored on click-outside dismiss. UNLOCKED auto-transitions to HIDDEN after 2.5s via `self._unlock_timer` (QTimer, cancelled at the top of every `_set_meta_state()` call).

## SVG icon rendering caching (2026-05-19)

`_load_svg_icon()` in book_detail_panel.py is cached via `@functools.lru_cache(maxsize=32)` with cache key `(svg_path, color, size, opacity)`. Replaces both `stroke="#000000"` and `fill="#000000"` attributes with the provided color for compatibility. For SVGs with neither attribute (Font Awesome), injects a CSS `<style>path { fill: {color}; }</style>` rule — but only if no stroke replacements happened (to avoid interfering with stroke-only icons like trash).

Theme changes that call `_set_meta_state()` will hit the cache for previously seen (path, color, size, opacity) tuples. This is intentional — icon rendering is deterministic.

## Duration label cursor and toggle (2026-05-19)

Speed comparison uses tolerance `abs(speed - 1.0) < 1e-9` to handle floating-point rounding errors (values like 1.0000000000000053 or 0.9999999999999991 stored in config). When speed is effectively 1x, cursor shows arrow (not hand) and toggle is disabled (no-op on click). Speed sourced from `config.get_book_speed(self._book_path)` with fallback to `config.get_default_speed()` — prevents misleading UI when default speed hasn't been saved yet.

## Book removal — is_excluded vs is_deleted (2026-05-18)

Two independent soft-delete flags on the `books` table:

- `is_deleted = 1` — set by `remove_scan_location` when a folder is removed from the scan list. Means "this folder is no longer being monitored." Resurrected automatically when the folder is re-added and rescanned (`upsert_book` resets it to 0 in the ON CONFLICT block).
- `is_excluded = 1` — set by `set_book_excluded` when the user explicitly removes a book from the library via the trash button in BookDetailPanel. Resurrected the same way — rescanning the location resets it to 0.

Both are filtered by `get_all_books` (`WHERE is_deleted = 0 AND is_excluded = 0`). Stats queries are intentionally left unfenced — history, progress, and session data survive removal and are visible in the stats panel.

The `upsert` resurrection behavior (rescan brings a book back) is a deliberate design choice, not an oversight. If permanent exclusion is needed in the future, the upsert blocks would need a conditional reset: `is_excluded = CASE WHEN excluded.something THEN 0 ELSE books.is_excluded END`.

> **SUPERSEDED 2026-06-27:** the "future" above arrived. `is_excluded` is now sticky through
> rescans (`is_excluded=CASE WHEN books.is_excluded THEN 1 ELSE 0 END` in both upserts) — a rescan no
> longer resurrects a trashed/missing book. The restore path is now the **Excluded Books** section in
> the Library settings tab (`ui/excluded_books.py` → `set_book_excluded(path, False)`). `is_deleted`
> still resets on upsert (location-readd resurrection unchanged). The lines above (1701, 1705)
> describe the pre-2026-06-27 behavior and are kept as the historical record. See CLAUDE.md "Sticky
> `is_excluded`".

## Scanner progress invariant — never pass 0.0 (2026-05-18)

`upsert_book` and `upsert_books_batch` use `COALESCE(NULLIF(excluded.progress, 0.0), books.progress)` to avoid overwriting saved playback positions on rescan. The scanner does not know the user's position — it must pass `None`, not `0.0`. The `NULLIF` is a safety net for accidental zeros, not a contract callers can rely on. If a future DB engine or sqlite version changes `NULLIF` semantics, `0.0` would overwrite progress silently.

## CUE file support — architectural notes (2026-05-16)

- `_chapter_list` being non-`None` is the flag for cue mode. No separate `_cue_mode` boolean needed — the `chapter_list` property already abstracts over VT/cue/native.
- `_on_chapter_change` is fully suppressed (always returns immediately as of 2026-06-01). It was previously guarded per-mode; now it does nothing. `_on_time_pos_change` drives all chapter tracking universally.
- All chapter navigation must use position-based walks against `_chapter_list` when populated — never `self.chapter` directly.
- `_virtual_timeline` stays `None` for cue books — do not set it, VT file-switching machinery must not activate.
- CUE files from Windows rippers (EAC, dBpoweramp) almost always have a UTF-8 BOM — read with `utf-8-sig`, not `utf-8`.

## Player.terminate() must call wait_for_shutdown() (2026-05-16)

Without it, libmpv's internal threads outlive Qt's cleanup, causing a crash in `avformat_close_input`. Was masked for an unknown period by a debug print keeping the thread alive. Easy to regress — do not simplify the teardown sequence.

## Chapter boundary epsilon — named constant (2026-05-16)

`_CHAPTER_BOUNDARY_EPSILON = 0.35` appears in chapter walk, restore, and all boundary seeks. It compensates for mpv's "don't miss a frame" bias (undershoots boundaries by ~23ms) and for float drift in mpv's internal chapter boundary representation. Moving it to write time at save was considered and rejected — the saved position itself can already be on the wrong side of mpv's boundary. The epsilon must live at seek time.

---

## Multi-file MP3 virtual timeline — RESOLVED (2026-05-15)

**Problem:** Multi-file MP3 folders (N .mp3 files per book) could not be seeked globally, navigated by chapter, or advanced naturally across files. Two earlier implementations were reverted — concat:// blocked on backward seeks; partial VT without signal separation caused quadruple-advance feedback loops.

**Architecture:**
- `book_files` DB table stores per-file `{file_path, sort_order, duration_ms, cumulative_start_ms}`, populated by the scanner. Player reads this at load time (no mutagen re-scan).
- `_virtual_timeline` list on Player holds `{file_path, cumulative_start, duration}` entries. Player translates global positions into (file_index, local_offset) and issues `instance.play(target_file)` + `_pending_local_pos` for cross-file seeks.
- `book_ready` signal fires once per book (before any file for VT; after file-loaded for non-VT). `file_switched` fires per VT file load. This separation eliminates the feedback loop: `_on_file_ready` is not connected to `file_loaded` at all.

**Why book_ready fires from two different places:** VT books need it before any file loads (so position restore sets `_pending_local_pos` on the right file). Non-VT books need it after file-loaded (so `self.player.duration` is valid when the slider animation reads it). This asymmetry is intentional.

**Natural EOF advancement:** `keep_open='always'` means mpv never fires end-file with reason_int=0 (EOF) — it always fires RESTARTED (reason_int=2). All EOF detection goes through `_on_pause_test` near-EOF position check. `_is_vt_file_switch` gates `_on_pause_test` during file-load transient pauses to prevent quadruple-advance.

**Chapter tracking for VT:** `Player.chapter` getter walks `_chapter_list` by global `time_pos`. `_on_time_pos_change` emits `chapter_changed` whenever the global chapter index changes (compared to `_last_vt_chapter`). `ChapterList._activate_item` calls `seek_async(target_time)` for VT books instead of `self.player.chapter = idx`.

**What not to do:**
- Do not connect `_on_file_ready` to `file_loaded` — this was the root cause of the feedback loop in Round 2.
- Do not use `self.player.chapter` (mpv local) for VT books anywhere — it reflects per-file chapter index, not global.
- Do not read `self.progress_slider.value()` in `_on_file_ready` for switch animation — the slider may not have been updated yet (gated on `not slider_animating and not is_seeking`). Always compute from `new_progress / self.player.duration`.
- `keep_open='always'` makes `_on_end_file` reason_int=0 unreachable — do not add EOF logic there.

---

## MP3 seek blocks Qt main thread — RESOLVED (2026-05-14)

**Root cause:** `self.instance.time_pos = value` in python-mpv is synchronous — holds the GIL on the calling thread until libmpv acks the seek. For MP3 streams, libmpv scans backwards through the bitstream to find frame boundaries before acking. Called from slider release handlers on the Qt main thread → 10–30s freeze.

**Fix:**
- `Player.seek_async(pos)` uses `command_async('seek', pos, 'absolute+exact')` — non-blocking, returns immediately. `absolute+exact` preserves hr-seek precision.
- `seek_within_chapter` returns the computed `new_pos` so callers never need to read `time_pos` back after a seek.
- All four hot-path properties (`time_pos`, `duration`, `pause`, `speed`) cached via `observe_property` — reads no longer cross the IPC boundary.
- `is_seeking` clearance moved into `_on_time_pos_change` observer (fires when mpv delivers the settled position) — removed from the 200ms polling loop where it fired prematurely.

**What is intentionally left on sync path:** Skip buttons, book-load position restore. Not slider-driven, not the problem path. `apply_smart_rewind` was also left on sync initially but was unified to `seek_async` on 2026-05-28.

**`_seek_target = None` edge case:** If `seek_async` is called and `_seek_target` is `None` when the observer fires, `is_seeking` still clears (the `_seek_target is None` branch). This is safe — it means no target was set, so any position qualifies as settled. The edge case that previously caused 228% progress was from an earlier implementation that used `_seek_target` in the flow-animation path; that code was removed.

---

## Single VBR MP3 seek lag — RESOLVED (2026-05-28)

**Root cause:** `absolute+exact` seeks in VBR MP3 files require mpv to scan forward through the compressed bitstream to locate the target frame. For large files or long seeks, this scan takes 1–30 seconds. This is a libmpv/VBR constraint — no seek flag avoids it for stream-based seeking.

**Fix:** `seek_async` intercepts seeks above `_MP3_SEEK_THRESHOLD` (60s) on single `.mp3` files (`_play_target.endswith('.mp3')` and `_virtual_timeline is None`) and calls `_mp3_stop_and_load(target_pos)` instead. This issues `loadfile … start={target_pos}` which positions via the Xing/TOC header (byte offset from TOC fraction) — approximate but fast.

**State machine:**
1. `_mp3_stop_and_load`: sets `_mp3_seek_reload_pending`, `_mp3_seek_visual_lock`, pauses mpv, issues `loadfile`.
2. `_on_file_loaded` early-return block: clears `_mp3_seek_reload_pending`, clears `_is_seeking`, restores pause state, clears `_mp3_seek_visual_lock`, returns without emitting `book_ready`.
3. `_set_play_icon` in app.py: returns early while `mp3_seek_visual_lock` is True — prevents play/pause icon flicker during the reload window.

**Why not `loadfile start=` for all seeks?** Short seeks on VBR MP3 are fast (mpv's seek is a forward scan from a nearby keyframe). The 60s threshold avoids unnecessary file reloads on short seeks where `absolute+exact` is fine. The threshold is a module constant (`_MP3_SEEK_THRESHOLD`) for easy tuning.

**Invariant:** `book_ready` is never re-emitted during a reload seek. The early-return in `_on_file_loaded` skips all existing post-load logic. VT, M4B, CUE books: not `.mp3` or `_virtual_timeline is not None` — intercept never reached.

**Previously attempted (rejected):** `loadfile start=` from `_restore_position` — mpv reported `time_pos=0.0` after `file-loaded` regardless. That was a position-restore context; here we issue `loadfile` with a live player instance that has already loaded the file, which behaves differently.

---

## Stats Panel — First-visit flash on Day/Week/Month tabs — RESOLVED

### Fix
`setVisible(False)` before `insertWidget`, then `setVisible(True)` immediately after, for each `BookDayRow` in all three refresh methods. Forces Qt to fully realize the widget before it is first painted. Applied to `_refresh_daily`, `_refresh_weekly`, `_refresh_monthly`.

### Symptom (was)
On first visit to each of Day, Week, Month tabs after app start, content flashed garbled for a split second then rendered correctly. Happened exactly once per tab per session — second visit was clean. Overall tab (no `BookDayRow` widgets) unaffected.

### What was tried and failed
- **DPR fix on thumbnails** — wrong diagnosis, covers are not the cause
- **`setFixedHeight` on `BookDayRow`** — wrong diagnosis
- **`addStretch()` → `setAlignment(AlignTop)`** — wrong diagnosis; also changed `insertWidget`/clear loop as collateral
- **`setUpdatesEnabled(False)` + `QTimer.singleShot(0)` re-enable** — wrong diagnosis
- **Pre-populating all tabs before `show()`** — wrong diagnosis
- **`ElidedLabel.showEvent` override** — no change
- **Disabling elision entirely** — no change; elision is not the cause
- **`ensurePolished()` on each row after insert** — no change
- **`QTimer.singleShot(0, window().update() + processEvents())`** — no change
- **`setVisible(False)` → insert → `setVisible(True)` on each row** — **THIS WORKED** (see fix above)

### What is known
- The flash is the entire row content (text + layout), not just thumbnails
- It is not a DPR, cover loading, layout stretch, or stylesheet timing issue (all ruled out)
- Root cause undiagnosed. Do not re-attempt the above.

---

## Panel Animation — Deferred Fixes

### `library_panel_animation.finished` duplicate connection risk — `_start_library_entry` and `_close_library_flow`
`_start_library_entry` ([panels.py:86](src/fabulor/ui/panels.py#L86)) connects `finished` → `_on_library_shown` with no guard against the animation already running. `_close_library_flow` ([panels.py:223](src/fabulor/ui/panels.py#L223)) does the same for `_on_library_hidden`. If either is called twice before the animation completes, a second connection accumulates; the self-disconnect in `_on_library_shown`/`_on_library_hidden` only clears one copy per firing. Most paths are guarded (`_close_library_flow` checks `Running` at line 212; the sidebar path serialises through `_on_sidebar_closed_for_panel`), so the race is low frequency but real. Fix when panel animation code is next touched: add the disconnect-before-connect pattern matching the other animation handlers.

---

## Known Architectural Debt

### _cover_cache has no eviction — unbounded growth
`_cover_cache` ([library.py:43](src/fabulor/ui/library.py#L43)) is a module-level `dict` keyed by `book_id (int) → QPixmap`. It grows for the lifetime of the session and is never pruned. At ~226×344px JPEG-decoded to RGBA in memory, each entry is roughly 300 KB. 500 user-added covers (125+ books × 4 slots, all loaded in one session) would consume ~150 MB. Not a realistic v1 scenario given the 4-per-book cap. Revisit if the cap is raised or if memory pressure is reported. Fix when ready: LRU eviction keyed on last-visible timestamp, sized to ~200 entries.

### _sized_cover_cache has no eviction either — compounds the _cover_cache debt above (2026-06-24)
`_sized_cover_cache` (`BookDelegate`, [library.py:1085](src/fabulor/ui/library.py#L1085), added alongside the LANCZOS cover-quality fix — see "Library cover thumbnails..." entry above) is per-delegate-instance, keyed by `(book_id, device_w, device_h)`, and never pruned — same shape of problem as `_cover_cache`, but multiplied: every distinct cell size a book has been rendered at (one per view mode × DPR combination actually visited) gets its own cached pixmap on top of the one already held in `_cover_cache`. View-mode switches don't evict old-size entries (deliberate — see the `_get_sized_cover` CLAUDE.md rule), so a session that visits all 5 view modes holds up to 5 extra pre-scaled copies per book it has viewed, in addition to the native-resolution source. Not fixed now — eviction policy here is the same open decision as `_cover_cache`'s, and the two should be solved together (likely the same LRU/cap mechanism, or one driving the other's eviction) rather than inventing a second, independent policy. Do not implement a bound for one without considering the other.

### `_lanczos_scale`'s `cover.toImage()` readback cost (2026-06-24)
`_lanczos_scale` (`BookDelegate`, [library.py:1775](src/fabulor/ui/library.py#L1775)) calls `cover.toImage()` on a `QPixmap` to get pixel data for the PIL round-trip. `QPixmap` is typically stored server-side/GPU-backed in Qt; `toImage()` can force a readback to CPU memory, which is comparatively expensive versus operating on a `QImage` throughout. This runs once per `(book_id, cell-size)` (cached after, not on every paint), and only on a cache miss, so it's not a per-frame cost — but it is a real conversion cost on every new book/view-mode/DPR combination encountered. Not measured or fixed; flagging in case cover-loading or scroll-stutter complaints come up later and this round-trip is a plausible contributor. Possible mitigation if it ever matters: keep the decoded `QImage` from the original load path (before it becomes a `QPixmap` for `_cover_cache`) and feed `_lanczos_scale` from that instead, avoiding the round-trip entirely — not attempted, would touch `_on_cover_loaded`'s cache-write contract.

---

### Book switch state split on DB failure — `_on_book_selected_from_library`
`_on_book_selected_from_library` ([app.py:1449–1458](src/fabulor/app.py#L1449-L1458)) sets `current_file = path`, then fires `db.update_last_played`, `config.set_last_book`, and `player.load_book` as four sequential side effects with no rollback. If `db.update_last_played` raises (disk full, locked DB), `current_file` already points at the new book but mpv is still playing the old one. Subsequent `_update_ui_sync` ticks write position data for the new path keyed against the old mpv session. Fix requires either: (a) a transaction wrapper that rolls back `current_file` and config on failure, or (b) delaying `current_file` assignment until after all DB writes succeed. Not a common failure mode — DB operations would need to be failing for this to trigger.

### Stats page sluggishness on Weekly and Monthly tabs
RESOLVED: BookDayRow and FinishedBookThumb now load covers asynchronously via CoverLoaderWorker, with placeholder fallback and _cover_cache hit check.

---

## Book Switch Sequence — Known Remaining Issues

### cover_path can be an audio file path in edge case
Scanner sets `cover_path = str(af)` (audio file) when no external image exists but the file has embedded art. It then immediately extracts and saves a `.jpg` thumbnail, replacing `cover_path` with the thumbnail path. So the DB normally always stores a `.jpg` path. Exception: if `img.save()` fails (disk full, permissions), the audio file path is stored instead. `CoverLoaderWorker` calls `QImage.load()` on it, which returns a null image. `_on_cover_loaded` discards null images silently — result is a missing cover, not a crash. No fix applied; failure mode is acceptable.

---

### Cover cache — cold start still hits mutagen
`_load_cover_art` checks `_cover_cache.get(file_path)` before calling mutagen. Cache is keyed by audiobook path and populated by the library panel's `CoverLoaderWorker`. On a warm session (library opened at least once), cache hits are instant. On cold start (library never opened this session), cache is empty and mutagen runs as before. Resolving cold-start requires either: (a) storing cover thumbnails on disk during scan, or (b) populating the cache independently on first book load.

### library_controller must not hide metadata_label when a book is loaded
`apply_library_state` ([library_controller.py:126](src/fabulor/library_controller.py#L126)) previously called `update_metadata(None, show_metadata=False)` unconditionally when `has_book=True`. This hid the "author - title" fallback set by `_load_cover_art` for no-cover books. Fixed by removing `show_metadata=False` from that call — `_load_cover_art` is now the sole owner of `metadata_label` visibility when a book is playing. Do not restore the `show_metadata=False` there.

### `book_covers` pre-migration books — fallback behavior
Both the preloader and `_trigger_cover_load` now call `get_active_cover_path(book.path)` before constructing `CoverLoaderWorker`. For books with no `book_covers` entry, `get_active_cover_path` returns `None` and the worker falls back to `book.cover_path` (scanner thumbnail) — same visual result as before, consistently applied. The previous asymmetry (preloader ignoring `book_covers`) was a bug, not intentional. No further action needed; when all books are rescanned the fallback path becomes a no-op.

### Panel close delay on book switch — RESOLVED (2026-05-13)
The stutter on book selection was caused by mpv's audio pipeline initialisation (PulseAudio negotiation on background threads) competing with the Qt animation timer at the OS scheduler level — not a main-thread block. Confirmed by timing: every Python step was under 2ms, but the animation still stuttered. Back-button close (no mpv work) was always smooth; this was the diagnostic signal.

**The fix — three-part sequence:**

1. **`_playlist_resolved` worker thread** (`player.py`): `_resolve_playlist` (mutagen reads) moved to `QThreadPool` worker. Result is held in `_held_play` rather than calling `instance.play()` immediately.

2. **Gate/ungate pattern** (`player.py`): `load_book` sets `_play_gated = True`. `_on_playlist_resolved` stores the resolved target in `_held_play` if still gated, or plays immediately if gate already lifted. `ungate_play()` either drains `_held_play` or sets `_play_gated = False` for future resolution. This means `instance.play()` — the call that kicks off PulseAudio init — never fires until after the animation completes.

3. **`_mpv_ready` flag** (`app.py`): `_on_book_selected_from_library` sets `_mpv_ready = False`. The deadzone in `_update_ui_sync` ignores all `mpv_pos` values while `_mpv_ready` is False. `_mpv_ready = True` is set in `_on_library_hidden` (library path) or directly before `ungate_play()` (startup/EOF-restart paths). This prevents the 200ms UI timer from accepting the previous book's stale position during the animation window and writing it to the slider.

**`ungate_play()` call sites:** `_on_library_hidden` (library flow), startup book restore, EOF restart. Any new `load_book` call that bypasses the library panel must also call `_mpv_ready = True` then `ungate_play()` immediately after.

**`_on_file_ready` / `_on_file_loaded_populate_chapters` deferral:** Both check `library_panel._is_animating` and set deferred flags if True. `_on_library_hidden` drains them via `QTimer.singleShot(50, _drain_deferred_file_ready)`. The 50ms is intentional — avoids last-frame compositor hitch.

**What was tried and failed:**
- Deferring only `_load_cover_art` and `load_book` via `singleShot(0)` — not enough; `instance.play()` still fired one event loop cycle into the animation.
- `is_seeking` guard on `_sync_progress_sliders` — broke flow animation because `is_seeking` clears before mpv delivers real position.
- `_seek_target` proximity check — caused 228% progress when `target=None` or book had no saved position.
- Skipping `_update_ui_sync` when `is_seeking=True` in `_on_file_ready` — broke flow animation because slider value was 0 when `animate_to` was called.
- Deferred slider animation from deadzone `is_seeking` transition — fired on wrong tick, reading wrong slider value.

**Unobvious:** The stutter root cause is OS scheduler, not Python. Python profiling and timing showed nothing. The diagnostic was: back button (identical slide, no mpv work) was always smooth.

### Position restore fragility
`_restore_position` re-reads from DB after `config_pos` sync. If `_current_book` (set at the top of `_on_file_ready`) was read before the sync, its `progress` value may be stale. The current workaround is a fresh `db.get_book()` call inside `_restore_position`. This is a second DB read on the file-ready path. Could be eliminated by moving the config sync earlier (before `db.get_book` in `_on_file_ready`), but requires care — `_current_book` is used by the slider animation logic immediately after.

### mpv `loadfile start=` option does not work
Tested with `instance.loadfile(path, start=str(int(seconds)))` and `f"+{int(seconds)}"`. mpv reports `time_pos=0.0` after `file-loaded` fires regardless. python-mpv's `loadfile` encodes options correctly (`key=value` string) but the seek either doesn't apply or is overridden. If this ever works in a future python-mpv/mpv version, `time_pos` assignment in `_restore_position` can be replaced entirely.

---

## Library Panel — Open/Close Performance (RESOLVED — close stutter 2026-05-13, open performance since fixed)

Current state: both close slide and open performance are smooth. The attempt log below is kept as
historical record of what was tried during the close-stutter session; the open-side work that
finally resolved it landed later. Do not re-investigate the reverted attempts below as if open.

### What was attempted this session and reverted

**Attempt 1 — refresh() after animation (old behavior, worked but caused blank flash)**
`_on_library_shown` called `refresh()` after slide-in. `refresh()` does full DB read + model reset + cover load. Caused visible blank flash before content appeared. This was the original code.

**Attempt 2 — on_open() replacing refresh() (BROKE EVERYTHING)**
Added `LibraryPanel.on_open()` which only called `update_current_book_progress()`. Replaced `refresh()` call in `_on_library_shown` with `on_open()`. This broke: progress not saved correctly, Recent/Progress sorts not updating, dynamic time updates broken. Root cause: `refresh()` does more than populate books — it also updates all books' speed-adjusted durations and re-applies sort/filter. `on_open()` didn't replicate this. REVERTED.

**Attempt 3 — mpv callback deferral (partially correct, needs retesting)**
`_on_file_ready` and `_on_file_loaded_populate_chapters` deferred via `library_panel_animation.finished` signal when animation was running. This eliminated the burst-retry timer loop. Deferred flags `_file_ready_deferred` and `_chaps_deferred` prevented double-connecting. 50ms singleShot after `finished` to avoid last-frame compositor hitch. This was CORRECT and did not break anything — it was rolled back only because it was bundled with the broken on_open() commit.

**Attempt 4 — preload callback guard (correct)**
`_on_preload_cover_loaded` now checks `_is_animating` before `notify_cover_cached`. This was correct and did not break anything — rolled back only because bundled.

**Attempt 5 — List mode text layout cache (correct)**
`_list_row_layout()` caches `fm.horizontalAdvance()` and `fm.elidedText()` results per `(book.path, available_width)`. Cleared on theme change, view mode change, refresh(). This was correct and did not break anything — rolled back only because bundled.

**Attempt 6 — row pixmap cache (broke List hover effects)**
Pre-rendering list rows to QPixmap. Broke trailing hover fade effect and elision-on-hover because those are per-frame dynamic. Reverted. The right approach: cache only the static layer (bg + text + progress), paint hover effects live on top. Not implemented correctly.

**Attempt 7 — setUpdatesEnabled(False) during slide-in/out (caused ghost)**
Suppressing repaints on _list_view during animation caused transparent panel ghost in List and 1-per-row modes — the panel appeared as a skeleton sliding over the content. Root cause: suppressing updates prevented Qt from clearing the panel's painted content as it moved. REVERTED.

**Attempt 8 — opacity animation instead of pos (not a fair test)**
Replaced QPropertyAnimation on pos with opacity. Other panels slide fine, so this wasn't comparable. Reverted.

### What the debug output showed
- `[FILE_READY] animating=True` and `[POPULATE_CHAPS] animating=True` — mpv fires file-loaded during the 300ms animation on fast SSDs. These callbacks hit the main thread and compete with the compositor.
- `[UI_SYNC] fired during animation` — 200ms timer fires 1-2 times during animation. Tests showed this is NOT the cause — it fires during smooth animations too.

---

## ChapterList — Deferred Fixes (2026-05-15)

### `fade_out` signal accumulation — DEFERRED

`fade_out` ([chapter_list.py:179](src/fabulor/ui/chapter_list.py#L179)) calls `_disconnect_hide` before connecting `_on_fade_out_finished`, and sets `_hide_connected = True`. If `fade_out` is called twice before the animation completes, the second call disconnects the first connection (via `_disconnect_hide`) and creates a new one. The first animation's `finished` fires with no handler; the second fires correctly. The `_anim.stop()` call resets animation state so the two calls don't compound. **Safe in practice.** The `_hide_connected` flag is semantically stale between `_on_fade_out_finished` returning and the next `_disconnect_hide` call, but this window is never observable — `_disconnect_hide` is only called from `fade_out` and `show_above`, both of which immediately follow with a fresh connect. Defer until chapter list animation is next refactored.

### `_activate_item` accesses `player._virtual_timeline` directly — DEFERRED

`_activate_item` ([chapter_list.py:283](src/fabulor/ui/chapter_list.py#L283)) reads `self.player._virtual_timeline` to decide whether to call `seek_async` or set `self.player.chapter`. This is a coupling violation — `ChapterList` depends on a private Player attribute. The correct fix is a public `Player.is_virtual_timeline` property (or routing all chapter activation through a single Player method that handles both cases internally). Defer until a Player public API review pass. Do not access `_virtual_timeline` from any other UI file in the meantime.
- Skipping `_update_ui_sync` entirely during animation caused transparent ghost panel. Not viable.
- `valueChanged` on QPropertyAnimation fires only twice (start/end positions), not per frame — measuring frame gaps via valueChanged is meaningless.

### Confirmed facts
- Other panels (settings, speed, sleep, stats) slide perfectly — library-specific problem.
- Empty library slides in/out smoothly — book content weight causes the stutter.
- Back button close (no book load): smooth.
- Book load close: stutters near end — mpv file-loaded fires during last frames.
- Grid modes: open smooth, close mostly smooth.
- List mode open: stutter proportional to book count (~17 visible rows of heavy paint).
- GTX 1060 won't help — Qt animation driver is CPU-bound, GPU only does final composite.

### What to do next (correct order)

1. **Re-apply mpv callback deferral** (Attempt 3) — tested, correct, no side effects. Apply to app.py only. Test: load books, verify progress saves, sorts work, dynamic updates work BEFORE looking at animation.

2. **Re-apply preload callback guard** (Attempt 4) — one line change, correct. Test same.

3. **Re-apply List mode text layout cache** (Attempt 5) — correct, no side effects. Test same.

4. **Fix library open flash WITHOUT breaking refresh()** — the correct approach: call `refresh()` BEFORE `show()` while panel is at `-panel_w` (off-screen). The panel is populated before the first visible frame. The `_after_covers` retry loop in `refresh()` will wait for `visualRect` to be non-empty, which happens naturally after the animation ends. Do NOT replace `refresh()` with a lightweight alternative — it does too much.

5. **Row pixmap cache for List mode** — cache static layer (bg, alternating color, stripe for non-playing rows, text, progress bar, time) keyed on `(book.path, row_width, row_height, row_parity, is_playing_paused, pct_bucket, show_rem)`. Paint hover effects live on top in all cases. Skip cache for the actively pulsing playing row. This eliminates the paint-heavy slide-in for List mode without suppressing updates.

### CRITICAL TESTING CHECKLIST before committing any library changes
- [ ] Open library → verify books shown correctly
- [ ] Select a book → verify progress saves after listening
- [ ] Reopen library → verify Recent sort shows updated book at top
- [ ] Verify Progress sort orders by percentage correctly
- [ ] Verify dynamic time updates tick every ~1 second while playing
- [ ] Close with Back button → smooth slide
- [ ] Close by selecting a book → check for ghost/stutter
- [ ] Open in List mode → check for ghost/skeleton
- [ ] Open in Grid modes → check content visible during slide

--- 

## Theme Transition — Long-term Plan

### Current state (as of 2026-05-10)
Overlay fade works correctly when no panels are open. When panels are open, automatic theme changes (cover theme, rotation) snap instantly. Settings panel hover preview animates correctly via overlay. The `user_initiated` flag distinguishes automatic from user-driven theme changes.

### Known remaining limitation
The overlay approach is fundamentally incompatible with any panel being open during a theme change — a frozen pixmap over an actively changing UI produces ghosts and dissolution artifacts. The current workaround (snap when panels are open) is acceptable for normal use.

### Long-term correct solution: per-element Q_PROPERTY color animation
Replace the overlay entirely with `QPropertyAnimation` on color properties of each widget. All custom-painted widgets are already instrumented (see session 2026-05-10). The remaining work is the QSS-driven majority:

**Why QPalette won't work:** Theme dicts have up to 30 semantic color keys across 50 themes. QPalette has a fixed role set that does not map onto this structure cleanly.

**What's required:** Convert QSS-driven widgets to use programmatic color assignment (via palette or stored attributes + custom painting) for color only, keeping QSS for structural styling (geometry, borders, fonts, hover/pressed states). Scope is wide — every button, label, background across all panels and tabs.

**When to do it:** After the UI is feature-complete and stable. This is a polish-pass architectural change. Do it as a dedicated session with no feature work mixed in.

**Widgets still needing instrumentation (THEME_ANIM_TODO):**
- `app.py`: `MainWindow`, `TitleBar`, `ChapterList`, `SpeedControlsPanel`, `AudioSettingsTab`, `SleepTimerPanel`, `StatsPanel`, `BookDetailPanel`, `status_banner`, `sidebar`, `vol_container`
- `chapter_list.py`: `ChapterList`
- `library.py`: `LibraryPanel`
- `stats_panel.py`: `ElidedLabel`, `SessionListWidget`, `BookDayRow`, `FinishedBookThumb`, `FinishedScrollRow`, `StatsPanel`
- `book_detail_panel.py`: `BookDetailPanel`, `_ClickableLabel`

---

## Themes Tab — Excluded from Per-Element Animation (2026-05-10)

The Settings panel Themes tab was audited and ruled out for per-element color animation. All other tabs are tamed (no custom-painted widgets, overlay runs over them cleanly). The Themes tab is the permanent exception.

### Widget inventory and color sources

| Widget | Theme keys | State mechanism |
|---|---|---|
| `QTabBar::tab` | `bg_deep`, `accent`, `settings_tab_hover_*`, `accent_dark`, `button_text` | QSS pseudo-classes |
| `ThemeItem(QPushButton)` | `panel_theme_names_dimmed`, `accent`, `accent_light` | `[selected]`, `[active_display]` dynamic properties + unpolish/polish |
| Cover-mode / interval `QLabel` | `panel_theme_names_dimmed`, `accent` | `[selected]` dynamic property |
| `QLabel#settings_header` | `accent_light` | QSS only |
| `QLabel#theme_hint` | `accent` | QSS only |
| `QPushButton#theme_add/remove/change_now` | `text`, `accent_dark`, `accent`, `button_text` | QSS only |
| `QPushButton#pattern_button` | `panel_theme_names_dimmed`, `accent`, `accent_light`, `accent_dark`, `button_text` | `[selected]`, `[is_default]` dynamic properties |

### Why per-element animation is not viable

**Dynamic property state machine on ThemeItem**: Three visual states (dimmed / selected / active_display), six possible pairwise transitions. Each requires resolving both the source and target color from the current theme dict at the moment of the flip, then starting a `QPropertyAnimation`. The unpolish/polish mechanism would have to be suppressed and replaced entirely.

**QTabBar is not instrumentation-friendly**: Renders through `QStyle` internally. Animating tab colors requires subclassing `QTabBar`, overriding `paintTab`, and managing per-tab color state manually. Not feasible without a dedicated rewrite of the tab bar.

**N simultaneous instances**: Interval labels and ThemeItem pool buttons all flip state at once. Each instance needs its own animation with correct per-instance before/after colors computed at flip time.

**QPalette does not work when QSS is active**: Confirmed via `ThemedButton` canary test. Setting `QPalette.Button` is silently ignored when any QSS `background` rule applies to the widget — QSS takes full precedence. `background: transparent` in QSS causes the window background to show through rather than the palette color. The only working background path is a `paintEvent` override painting a rounded rect explicitly, which requires hardcoding `border-radius` to match QSS and loses QSS `:hover`/`:pressed` background states entirely.

### What works instead
`user_initiated` flag on `_on_theme_changed` + Themes-tab-active check: automatic theme changes (cover art, rotation) snap instantly when Themes tab is open. User-driven changes (hover preview, right-click, Change Now, mode buttons) animate normally. `snap_theme_forward()` on settings panel close prevents overlay dissolution during slide-out.

---

## Theme System — Known Bugs (2026-05-26, corrected 2026-07-01)

### Spurious sidebar expand during theme hover — root cause still unknown; original theory disproven

**Symptom:** Occasionally during hover-preview over theme pool items, the sidebar briefly becomes
visible behind or alongside the settings panel. Visually this shows as sidebar button labels
(SETTINGS, STATS, etc.) bleeding through, giving a hodge-podge appearance.

**CORRECTION (2026-07-01):** The "Mitigation (2026-05-26)" paragraph that used to appear here
claimed the overlay mask was changed to unconditionally exclude the sidebar geometry. This was
checked against source: it is **factually wrong**. `git log -p -L` on both mask-exclusion sites
(`theme_manager.py`, then-lines ~392 and ~506) shows `if pm.sidebar_expanded: mask -=
QRegion(pm.sidebar.geometry())` has been **identical since its introduction on `99438c5`
(2026-05-10)**, through the cited 2026-05-26 date, through every commit since, unchanged in the
current source. The commit that date's docs entry pointed to (`65b5688`, 2026-05-26, "perf: add
tags_panel to fade overlay mask") only appends `'tags_panel'` to the panel-exclusion list — it
never touches the sidebar conditional. No commit anywhere in either file's history makes the
sidebar exclusion unconditional. Whether this mitigation was ever actually written and lost, or
the original doc entry was simply aspirational/incorrect when filed, is unknown — but the guard
itself was never touched, so nothing here needs fixing on that front. Do not cite "unconditional
sidebar mask exclusion" as existing mitigation again without re-checking the source.

**Root cause: still unknown. The original race theory is DISPROVEN, not just unconfirmed** — this
is a real result, not a shrug. The old theory: `_on_theme_right_clicked` → `_on_theme_changed` →
`_any_panel_animating()` guard fires while a sidebar animation is in progress → deferred retry
executes after the sidebar has already closed → `sidebar_expanded` left stale. Traced against
source (2026-07-01) and ruled out on two independent grounds:
1. `sidebar_expanded` is written **synchronously in `_toggle_sidebar`, before `sidebar_animation.start()`**
   (`panels.py`) — never from an animation-finished callback. It reflects the most recent click's
   intent the instant the click handler runs; there is no code path where an animation completes
   and the flag fails to already match it. It cannot go stale relative to a completed animation.
2. `sidebar_animation.setDuration(300)` (`main_window_builders.py`) vs. the guard's own
   `_PANEL_ANIM_GUARD_MS = 700` retry delay (`theme_manager.py`) — a single sidebar toggle is
   never still `Running` when a 700ms-later deferred retry fires. And the deferred retry fully
   re-runs `_any_panel_animating()` from scratch (no bypass on retry), so even a still-animating
   sidebar at that later moment would just re-defer, not fall through with stale state.

**Do not remove the `if pm.sidebar_expanded:` guard** — confirmed to be a single, correctly-behaving
flag (not two distinct checks under one name), referenced identically at both mask-exclusion sites
plus ~12 other read sites in `panels.py`. It is not the cause of the bug.

**Two untested candidate mechanisms (2026-07-01), neither requiring `sidebar_expanded` to be wrong:**
- **Repaint/QSS ordering gap:** the fade overlay's mask punches a hole at the sidebar's *current*
  geometry (correctly reflecting `sidebar_expanded`), but if `_apply_stylesheets`' sidebar
  `setStyleSheet(get_sidebar_stylesheet(...))` repolish/repaint lands after the overlay is shown
  rather than before, the hole could expose one or more frames of the sidebar still rendering
  old-theme (or unstyled) colors — reading as the reported "hodge-podge" bleed-through without any
  flag being incorrect.
- **z-order race between independent `.raise_()` calls:** `_toggle_sidebar` calls
  `self.sidebar.raise_()` on open; `_on_theme_changed`/`_do_fade_with_slider_animation` separately
  call `self._fade_overlay.raise_()` after building the mask. If both land close enough together,
  Qt's stacking order could resolve with the sidebar on top of the overlay regardless of what the
  mask says — orthogonal to the mask/QRegion mechanism entirely.

**Instrumentation added (2026-07-01, commits `3aeed97`, `90029f0`):** `logger.debug` calls with
inline `time.perf_counter()` timestamps (sub-millisecond resolution — the standard log timestamp's
millisecond granularity isn't fine enough to disambiguate closely-spaced events here) now bracket:
`_toggle_sidebar` entry + its `sidebar.raise_()` call (`panels.py`); the `_any_panel_animating()`
guard result, both mask-build blocks' `sidebar_expanded`/`sidebar.geometry()` reads, and both
`_fade_overlay.raise_()` call sites (`theme_manager.py`); and the sidebar `setStyleSheet()` call in
`_apply_stylesheets`. Silent below `FABULOR_LOG_LEVEL=DEBUG`; verified live (hover + independent
sidebar toggles) to produce a correctly-ordered, human-readable sequence — see SESSION.md 2026-07-01
for the verification log excerpt. No repro was forced or captured this session; the instrumentation
is in place for whenever the bug next surfaces during normal use with DEBUG enabled, which should
let it distinguish between the two candidates above (or surface a third mechanism neither covers).

---

## Player / VT — Deferred Bug Investigations (2026-05-16)

### Prev chapter while paused goes to N-1 instead of restarting N — RESOLVED (2026-05-16)

Two root causes:

1. `previous_chapter()` non-VT was reading `self.chapter or 0` (mpv's async property) to identify the current chapter. When paused this value can lag. Fixed: replace with a walk of `chapter_list` against `time_pos + 0.35`, same as VT and display paths.

2. The "restart current chapter" case used `self.time_pos = chap_start` (default seek). Default seek undershoots by one AAC frame (~23ms). When paused, playback never advances past the boundary to self-correct; mpv kept reporting N-1. When playing, forward playback masked the undershoot in one tick. Fixed: `seek_async(chap_start + 0.35)` — `absolute+exact` seek plus epsilon to clear the ~0.25s float drift window.

### Chapter slider position wrong after Prev/Next chapter — RESOLVED (2026-05-16)

Root cause: time labels in `_sync_chapter_ui` update without an `is_seeking` guard; slider `setValue` was gated on `not is_seeking`. For `self.chapter = N` seeks, `_seek_target` is never set, so `_is_seeking` clears on the first `_on_time_pos_change` callback. Race: timer fires with label showing correct "00:00" but slider retaining the stale near-full value from the previous chapter. A `setValue(0)` call in `handle_prev`/`handle_next` made it worse — it was overwritten before the seek settled.

Fixed: remove `setValue(0)` from both handlers; remove `not self.player.is_seeking` from the chapter slider's `setValue` condition in `_sync_chapter_ui`. Keep the `chap_animating` guard — that is the architecturally protected one. The slider now updates every 200ms unconditionally and self-corrects within one tick.

### M4B chapter label shows previous chapter on book load — RESOLVED (2026-05-16)

Root cause: `_restore_position` non-VT used `self.player.time_pos = book_data.progress` (default seek). One-frame undershoot (~23ms) lands before the chapter boundary when saved position is at chapter N's start. mpv correctly reports N-1 for that position.

Three signal-path approaches failed — **do not retry**:
- **Timer correction in `_sync_chapter_ui`**: `_update_chapter_label_from_index` (signal path) never updated the tracking index so the correction never fired. Adding tracking there caused N-1→N flash on every book load.
- **Walk in `_on_time_pos_change` for non-VT**: fires on every audio frame including intermediate seek values. Caused N+2 flashes on Next and a regression cascade (stuck slider, broken label on all seeks).
- **Walk in `_on_chapter_change` with direct `instance.time_pos` read**: could not reliably get the post-seek position before the chapter callback fired.

Fixed at the seek: `_restore_position` now uses `seek_async(book_data.progress + 0.35)`. Restores 0.35s past the saved position — accepted trade-off, consistent with what `previous_chapter` does for the same reason.

**Rule (superseded — see below):** Earlier rule said `chapter_changed` for non-VT must remain on `_on_chapter_change`. That rule is now wrong. See the 2026-06-01 session entry below.

### M4B chapter label drift after slider/right-click seek — RESOLVED (2026-05-16, session 2) — superseded by 2026-06-01

Root cause: mpv fires `time-pos` observer only once after a seek while paused. That single callback can arrive at an intermediate position and go silent before the seek fully lands — label stays wrong until the next natural `chapter_changed` emit.

Fix applied in 2026-05-16:
- `_on_time_pos_change` added non-VT branch walking `chapter_list` against `value + _CHAPTER_BOUNDARY_EPSILON`, emitting `chapter_changed` when index changes. Tracked via `_last_nonvt_chapter`.
- `seek_async` non-VT immediately set `_cached_time_pos = pos` and emitted `chapter_changed`.
- `_on_chapter_change` returned early if `_is_seeking` is True.

**This fix introduced a latent race** — see "Chapter snap-back on Prev/Next while paused" below.

### Chapter snap-back on Prev/Next while paused — RESOLVED (2026-06-01)

Root cause: `_on_time_pos_change` and `_on_chapter_change` were both emitting `chapter_changed` for embedded M4B books. The `_is_seeking` guard on `_on_chapter_change` was insufficient because `_on_time_pos_change` clears `_is_seeking` first (when the position settles within 1.0s of `_seek_target`). By the time `_on_chapter_change` fires, `_is_seeking` is already False — the guard cannot protect against the stale mpv native chapter value.

When **playing**, continuous `time_pos` events keep re-emitting the correct chapter within milliseconds, masking the snap-back. When **paused**, mpv fires no further events after settling — the stale `_on_chapter_change` value is the last word. Symptom: clicking Next while paused briefly shows the correct chapter title, then snaps back to the previous chapter. The actual seek did happen; only the label was wrong.

Fix: `_on_chapter_change` is now fully suppressed (immediate `return`). `_on_time_pos_change` handles chapter tracking universally for all three book types:
- **VT** (`_virtual_timeline is not None and _chapter_list`): walks `_chapter_list` against global position.
- **CUE** (`_chapter_list is not None, _virtual_timeline is None`): `self.chapter_list` returns `_chapter_list`, walks it.
- **Embedded M4B** (`_chapter_list is None, _virtual_timeline is None`): `self.chapter_list` returns `self.instance.chapter_list` (live from mpv), walks it.

All three paths track via `_last_nonvt_chapter` / `_last_vt_chapter` and emit only on change. No emission path remains in `_on_chapter_change`.

**Current rule:** `_on_chapter_change` is dead (always returns). Do not restore it. `_on_time_pos_change` is the sole driver of `chapter_changed` for all book types.

### M4B chapter stuck intermittently after a VT session — TRACED, not a Fabulor state-leak (2026-06-12, review/Review_260612_6.md #6)
Symptom (CLAUDE.md Known Debt): chapter display freezes at a chapter boundary in some embedded-M4B books, sometimes after a multi-file VT session.

**Trace conclusion (don't re-trace the reset path — it's clean):** The full VT-session-end → M4B-load → chapter-init path was walked. `load_book` (player.py ~343-360) **resets every relevant field synchronously before the async resolve worker is queued**: `_virtual_timeline=None`, `_chapter_list=None`, `_file_offset=0.0`, `_current_vt_index=0`, `_last_vt_chapter=-1`, `_last_nonvt_chapter=-1`, plus `_cached_time_pos/_cached_duration/_seek_target=None` and the `_mp3_seek_*` flags. **No VT/chapter-tracking state survives the VT→M4B transition.** `_last_nonvt_chapter=-1` forces the first `_on_time_pos_change` walk to emit. So the freeze is NOT a leaked `_virtual_timeline`/`_chapter_list`/`_last_nonvt_chapter`.

**Where the freeze actually originates (the real lead for next time):** the embedded-M4B branch of `_on_time_pos_change` walks `self.chapter_list`, which for M4B is `self.instance.chapter_list` (mpv-native). It is gated by `elif self.chapter_list and value is not None` — if mpv hasn't parsed the chapter table yet (or a particular M4B reports `time-pos` updates with a malformed/empty native chapter list), the branch is skipped and `_last_nonvt_chapter` never advances past its initial value → label sticks. Secondary contributor: the settle-reset (`_last_nonvt_chapter=-1`) only fires inside the seek-clear branch (`_seek_target is not None`), so on a normal play-through across a boundary the advance relies solely on `curr != _last_nonvt_chapter`; if two boundaries fall inside one `is_seeking`-gated window only the final chapter emits (coalescing, not a leak).

**Next investigation should instrument `self.instance.chapter_list` readiness at the first `_on_time_pos_change` for the affected M4Bs** — it is an mpv-data/timing property, not Fabulor reset-path state. Do not re-audit `load_book`'s reset block; it is comprehensive and correct.

### Progress slider race on book switch — TRACED, not a missing guard (2026-06-12, review/Review_260612_6.md #7)
Symptom: slider briefly shows 0% / wrong position before settling on book switch.

**Trace conclusion (don't re-derive):** The authoritative set in `_on_file_ready` — `animate_to(new_val, old_value=pre)` / `setValue(new_val)` at app.py ~1189/1192, where `new_val = int(new_progress/dur*1000)` and `pre = _switch.take_progress_target()` — is protected by **three composable guards** that hold through the switch window: `slider_animating` (flow `_flow_anim` Running), `player.is_seeking` (restore seek in flight), and `_switch.flow_pending_progress` (pre-switch capture not yet consumed). All three are checked together in `_sync_progress_sliders` (app.py ~1597) before the 200ms timer's `setValue`.

No second *unguarded synchronous* writer exists. The residual exposure is **purely a timing overlap**, not a missing guard: the resumed 200ms timer (`_resume_ui_timer` fires on `_flow_anim.finished`) can tick in the thin window where `slider_animating` has gone False (animation done) AND `is_seeking` has gone False (restore seek settled within 1.0s) but the live `pos` transiently differs from the animation's end value. It self-corrects on the very next tick (writes the now-converged live position). Matches the "intermittent, brief 0%/wrong-position" symptom.

The disconnect-before-connect fix in `load_book` addressed the *double-handler* variant (a real bug, fixed). This residual is the leftover guard-release-ordering overlap. **If determinism is ever wanted, the lever is ordering** — hold the timer resume until BOTH the flow animation finished AND the restore seek settled, rather than resuming on `_flow_anim.finished` alone. Not pursued; the self-correct makes it cosmetic and rare. Full writer list with file:line is in review/Review_260612_6.md §7.

### VT sessions not recorded correctly across file switches — believed FIXED (verify, 2026-06-25)
Original issue: `_close_session`/`_open_session` wiring did not account for mid-book VT file
transitions — when mpv emitted `file_switched`, the session layer treated it as a new play event
rather than continuation of the same book, breaking listening-time attribution across VT file
boundaries. Believed resolved as of 2026-06-25 (`file_switched` now threaded into the recorder), but
not independently re-confirmed here — left in NOTES as a root-cause record pending a verification
pass. If a VT book's listening time still fragments across its file boundaries, this is where to
start.

---

## Stats Panel — Timeline Tab Not Updated After Metadata Edit — RESOLVED (2026-05-16)

`get_hourly_heatmap` was reading `book_title` directly from `listening_sessions` (value snapshotted at recording time) instead of joining `books` to get the current title. Fixed: added `LEFT JOIN books b ON ls.book_path = b.path` and changed the select to `COALESCE(b.title, ls.book_title, ls.book_path)`, matching the pattern already used by all other stats queries in `db.py`. Updated title now appears in heatmap tooltips immediately after edit, with no restart needed.

### Deferred — chapter nav undo/restore near boundaries

- **Undo after Next:** Undo button does not appear. Root cause not yet isolated — may be `_undo_pos` not being set on the `seek_async` path.
- **Undo after Prev:** Undo fires but chapter slider drifts to far right. Undo target is at a chapter boundary; restore lands in wrong chapter for same boundary-drift reasons as the other nav bugs.
- **apply_smart_rewind and Undo restore:** Still use `time_pos =` assignment in some paths. Not yet audited for boundary drift. Needs testing near chapter starts.

---

## Cover Panel — Deferred Issues (2026-05-16)

### Duplicate cover detection not implemented
`_on_add_cover` ([cover_panel.py:497](src/fabulor/ui/cover_panel.py#L497)) copies the selected file into the book's cover directory without checking if an identical image already exists (by content hash or file size + dimensions). A user adding the same image twice creates redundant copies on disk and redundant DB rows. Implement before the cover panel slot limit (4) becomes a user-visible constraint — a duplicate wastes a slot.

### `upsert_cover` delete ordering — file before DB
On cover deletion, the current implementation deletes the file before the DB row. If the DB delete fails (locked, disk error), the file is gone but the DB still references it — the thumbnail shows a broken image on next open. The correct order is: delete DB row first, then delete file. If the file delete fails, the DB is clean and the orphaned file is harmless (not referenced). Address when cover panel is next touched.

### `_on_thumb_delete` does not check file delete return value
`_on_thumb_delete` ([cover_panel.py:444](src/fabulor/ui/cover_panel.py#L444)) calls the delete operation but does not inspect whether the file was successfully removed. A silent failure leaves an unreferenced file on disk. At minimum, log the failure. Address alongside the ordering fix above.

---

## Cleanup Deferrals — Pre-existing, Deliberate (2026-05-16)

These items exist in the codebase intentionally and should not be removed without a dedicated cleanup pass.

### Debug prints and timing instrumentation
`_close_session`, `_on_file_ready`, `_on_book_selected_from_library` contain `print()` calls and timing probes left from VT debugging. Remove in a dedicated cleanup commit — do not remove piecemeal during feature work.

### `KEY_Q` quote rotation shortcut — remove before release
`keyPressEvent` → `library_controller._rotate_quote()` when empty state active. Tagged `# TODO: remove before release` in `app.py`.

### Temp EOF flags
`_eof_event_written` and `_eof_dur_fetched` flags, and associated `#Temporary` comments, were added to guard double-write during EOF session close. Review whether they are still necessary after the session recording rewrite for VT. Do not remove blindly — check whether the guard condition is still reachable.

### Temp file accumulation for VT playlist resolution
`_resolve_playlist` writes `ffmetadata` and `concat` files with `delete=False` (or equivalent) for debugging. These accumulate in `/tmp` across sessions. Switch to `delete=True` or explicit cleanup in a `finally` block when VT is considered stable.

### Config — `balance` key has no bounds validation
`config.set_balance(value)` writes whatever it receives. The audio tab constrains input to `[-1.0, 1.0]` via the slider, but the config layer has no clamp. A manually edited or corrupted QSettings file can store an out-of-range value that passes silently to mpv's audio filter. Add `max(-1.0, min(1.0, value))` in `set_balance` when config is next touched.
---

## Library State Refactor + Cover Area Fix (2026-06-01)

### `apply_current_state()` vs `_check_library_status()` (LibraryController)

`apply_current_state()` computes library state, applies it to the UI, and returns the computed state object — no background-task or scan side effects. `_check_library_status()` delegates to `apply_current_state()` and feeds its returned state into `handle_background_tasks()`. All scan triggering lives in `_check_library_status` alone.

The book-selection path (`_on_book_selected_from_library`) calls `self.library_controller.apply_current_state()` inside its deferred `singleShot(0)` lambda, after `_load_cover_art` and `player.load_book`, so cover and chrome reveal in the same event-loop tick. `_check_library_status` is not used here because `handle_background_tasks` would fire a scan on every book pick.

`apply_library_state` is the sole chrome gate: it calls `set_visible(state["has_book"])` and manages `go_to_library_btn` visibility. Chrome only appears when this gate runs with `has_book=True`. The failure mode that prompted the refactor: in the empty → add folder → scan → pick book path, `current_file` was set but the gate never ran with `has_book=True`, so chrome stayed hidden until restart.

**Caller audit (2026-06-01):** Three `_check_library_status` call sites remain. All three legitimately want a scan trigger (`_on_remove_folder_clicked`, `_on_scan_now_clicked`) or fire during an active scan where `handle_background_tasks` guards on `mode != "scanning"` and is effectively a no-op (`_on_scan_progress` at `current == 1`). None need migration to `apply_current_state()` for correctness. `_on_scan_finished` does not call `_check_library_status` at all.

### `COVER_AREA_HEIGHT = 280` (`app.py` module constant)

Calibrated fixed height of the cover art box in pixels. `cover_art_label` is pinned with `setFixedHeight(COVER_AREA_HEIGHT)` and `setAlignment(Qt.AlignCenter)`. `_update_cover_art_scaling` uses this as `target_h`.

Value derived from the fixed-size window budget (564px total − title bar 32 − progress slider 24 = 508 content height; minus content margins 20, 5 spacing gaps 50, and six fixed-height rows below visual_area: speed 33, preview 21, controls 33, chapter_info 24, chapter_slider 13, book_info 24 = 148; 508 − 218 = 290 theoretical). Calibrated empirically to 280 after testing covers of various aspect ratios.

Do not derive `target_h` from `cover_art_label.height()` — that reflects transient layout allocation, which is wrong during any state transition. If the window layout ever changes, re-calibrate empirically.

---

## Empty-state and no-book-state layout — architecture notes (2026-06-02)

### `visual_layout` widget order and visibility contract

The `visual_layout` (inside `visual_area`) contains these widgets in order:

| Index | Widget | Empty state | No-book state | Player state |
|---|---|---|---|---|
| 0 | `cover_art_label` (fixed 280px) | hidden | hidden | shown |
| 1 | `scan_section` (stretch=1) | shown | hidden | hidden |
| 2 | `metadata_label` | hidden | shown ("No book selected.") | owner: `_load_cover_art` |
| 3 | `go_to_library_btn` | hidden | shown | hidden |
| 4 | `quote_section` (fixed 240px) | shown | hidden | hidden |

When the carousel is active, `_carousel_container` is inserted at index 0 (pushing everything else down by one). It is removed and `deleteLater()`'d on player-state and empty-state entry. The container wraps `CoverCarousel` with `addSpacing(30)` above and below.

### Status banner is a floating overlay, not a layout item

`status_banner` is a `QWidget(self)` child of `MainWindow`, positioned via `setGeometry(0, height-30, width, 30)` in `resizeEvent`. It is not in `visual_layout` or `content_layout`. Raising it above the fade overlay is suppressed while `_fade_overlay.isVisible()` — see session notes on the snap-back bug fix.

### `_suppress_fill` on `ClickSlider` — paint-only gate

`ClickSlider._suppress_fill = True` prevents the fill rect from being painted in `paintEvent` while still painting the background groove. The flag is toggled by `_set_interface_visible`. `setEnabled(False)` is also called alongside it to block mouse events; `ClickSlider.paintEvent` does not read `isEnabled()` so there is no visual side-effect from disabling.

### Cover carousel — sampling invariants

- Uses `books.cover_path` (scanner thumbnails), not user-selected active covers from `book_covers`. Intentional — fast, no joins, matches prompt scope.
- Pillow reads are header-only (`img.size` without `img.load()`) — reads only the image header, not the full pixel data.
- Static mode threshold is count-based (`n <= 3`), not width-based. Three covers at 96px/slot = 288px > 280px viewport, so they cannot scroll seamlessly (2x strip = 576px < threshold for gapless looping). Centered static layout is correct for 2–3 covers.
- `scroll_speed` default is 15 px/s (tuned from initial 30 — user preference).
- Carousel issues from visual inspection are pending resolution (commit tagged `wip`).

### Design decision — cancel scan keeps partial results

Cancelling a scan leaves already-scanned books in the library. This is intentional: for a large library mid-scan, removing the partial results would be destructive — the user would lose progress data and cover art for hundreds of books already processed. If a user adds the wrong folder, they remove it manually. Do not treat partial-scan residue as a bug.

### Intentional redundancy — `or not has_indexed_books` in `apply_library_state`

The condition `state["mode"] == "empty" or not state["has_indexed_books"]` contains a redundant clause. `compute_library_state` already sets `mode = "empty"` whenever `not has_indexed_books` (line: `if not has_locations or not has_indexed_books: mode = "empty"`), so the `or not has_indexed_books` branch can never be reached today. It is kept as a guard against future refactors that might introduce a state where `has_indexed_books=False` but `mode != "empty"` (e.g. a new `"no_books"` mode). Do not remove it for cleanup — the redundancy is load-bearing intent, not dead code.

### `_showing_placeholder` must be cleared on every path that hides the cover, not just the has-cover path

`_load_cover_art("")` hid `cover_art_label` but never reset `_showing_placeholder`, so a `_panel_guard_timer`-deferred `_reload_button_icons` (fired later, after a panel animation that was in flight at removal time finished) would see the stale `True` flag and unconditionally repaint the logo placeholder back onto the hidden label — the intermittent "logo cover survives location removal" bug. Verified via a forced race (toggle `panel_manager._any_panel_animating()` to `True` around `_on_book_removed()`, then flip it back and fire the single-shot guard timer once) rather than relying on wall-clock UI timing; see git log for the fix commit. Any boolean UI-state flag with more than one "clear" call site is a candidate for this same class of bug if one of those call sites is ever missed.
