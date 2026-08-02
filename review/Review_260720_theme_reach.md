# Theme-Reach Audit — theme-bleed / heartbeat bugs
**Branch:** `blur-composited-overlay`  **Date:** 2026-07-20  **Scope:** read-only investigation, no fixes proposed.

This audit inventories every path by which stylesheet/style state can reach `content_container` or
`main_window` (or their descendants), checks each against CLAUDE.md's invariant #4
(`_apply_stylesheets` is the sole dispatcher — no direct `setStyleSheet()` bypass), and traces whether
preview/hover theme state (`_active_display_theme` while `_is_hover_active` is or recently was `True`)
can reach those two widgets by any path, however indirect.

**Widget ownership, confirmed by direct construction-site reading (not assumed):** `MainWindow` is a
plain `QWidget` (`app.py:304`, `class MainWindow(QWidget)`). `content_container` is constructed as
`QWidget()` then added to `main_window`'s `root_layout` (`app.py:600-604`) — a direct child.
`sidebar` (`main_window_builders.py:500`, `QWidget(mw)`), `settings_panel` (`main_window_builders.py:622`,
`QWidget(mw)`), `speed_panel`/`sleep_panel` (`app.py:584,651`, constructed with `self` as parent),
`library_panel`/`stats_panel`/`book_detail_panel` (`main_window_builders.py:560,569,590`, all
`parent=mw`), and `title_bar` are all direct children of `main_window`. `ThemeItem` buttons
(`title_bar.py:58`) live inside `settings_panel`'s subtree (the Themes tab). Ownership tree is
unambiguous — ThemeItem's ancestor chain reaches `main_window` through `settings_panel`.

---

## 1. Full call-site inventory for theme application

### `setStyleSheet()` call sites on `content_container` / `main_window` / their descendants

| # | File:Function | Target | Trigger |
|---|---|---|---|
| 1 | `ui/theme_manager.py:914` `_apply_stylesheets` | `mw` (main_window) | Every theme apply (rotation, click, hover preview, cover-theme, startup) |
| 2 | `ui/theme_manager.py:917` `_apply_stylesheets` | `mw.title_bar` | Same as #1 |
| 3 | `ui/theme_manager.py:921` `_apply_stylesheets` | `mw.content_container` | Same as #1 (uses `get_player_stylesheet(theme_name, suppress_bg_image=mw._bg_suppressed)`) |
| 4 | `ui/theme_manager.py:941` `_apply_stylesheets` | `mw.sidebar` | Same as #1 |
| 5 | `ui/theme_manager.py:998` `_apply_stylesheets` | `mw.settings_panel`, `mw.speed_panel`, `mw.sleep_panel` (loop) | Same as #1; wrapped in the `_spurious_enter_guard_until` try/finally (heartbeat mitigation #1) |
| 6 | `ui/theme_manager.py:1051` `_apply_stylesheets_deferred` | `mw.library_panel` | Deferred (non-hover only) invisible-surface batch |
| 7 | `ui/theme_manager.py:1058` `_apply_stylesheets_deferred` | `mw.stats_panel`, `mw.book_detail_panel` (loop) | Same as #6 |
| 8 | **`app.py:1282` `_set_bg_suppressed`** | `mw.content_container` (i.e. `self.content_container`, called as an instance method of `MainWindow`) | Called via `AppInterface.set_bg_suppressed` → `library_controller.py` at book-load/empty-state transitions (`apply_library_state`), independent of any theme-change call |

Other `setStyleSheet()` sites found repo-wide are on widgets that are NOT descendants of
`content_container`/`main_window` in a theme-relevant sense, or are cosmetic/local (tag dots, popups,
context menus, search-field error highlighting, history-row backgrounds, etc.) inside
`tag_manager.py`, `sleep_timer.py`, `speed_controls.py`, `book_detail_panel.py`, `excluded_books.py`,
`library.py`, `stats_panel.py`, `cover_panel.py`, `text_context_menu.py`, `main_window_builders.py`. All
of these are one-off inline stylesheets for a specific small widget (buttons/dots/labels), not the
base/theme QSS for `main_window`/`content_container`, and none of them read `_active_display_theme` or
`_is_hover_active`. They are out of scope for the bleed/heartbeat mechanism and not enumerated further.

### `setProperty()` / `style().polish()`/`.unpolish()` on QSS-selector-driving properties

All found instances (theme-pool buttons `theme_widgets`, interval buttons, cover-pool button,
settings toggle buttons in `app.py`/`settings_controller.py`'s sync helpers, audio/speed/sleep panel
buttons, stats-panel progress bar, tag-manager color dots, cover-panel fit buttons) target **leaf
buttons/widgets inside already-styled panels** (`settings_panel`, `speed_panel`, `sleep_panel`,
`stats_panel`, `cover_panel`) — they mutate `selected`/`active_display`/`inert`/`kbdSelected`/`fitKey`
dynamic properties consumed by that panel's own QSS `[property="..."]` selectors, not
`content_container`/`main_window` directly. None of them bypass the theme system in the sense of
painting a *different theme's* colors onto `main_window`/`content_container` — they re-polish the
CURRENT theme's per-button selected/active state. `book_detail_panel.py:46` and `controls.py:356`
`setPalette()` calls are on local widgets, not `main_window`/`content_container`. No `QPalette` call
touches `main_window`.

**Relevant to the heartbeat bug specifically:** `theme_manager.py:1220,1221` (`update_interval_visuals`),
`1282,1283` (`update_theme_list_visuals`), `1354,1355` (`update_cover_art_mode_visuals`), `1383,1384`
(`_update_cover_pool_btn`) all call `.style().unpolish()/.polish()` on `ThemeItem`/interval/cover-pool
buttons living inside `settings_panel`. NOTES.md records that `update_theme_list_visuals()`'s
unpolish/polish calls were investigated and **disproven** as the heartbeat's cause (live trace showed
`repolished 0/58 buttons` while the spurious `enterEvent` still fired) — kept here for completeness of
the inventory, not as a live suspect.

---

## 2. Invariant #4 — dispatcher-bypass check

CLAUDE.md invariant: *never call `main_window.setStyleSheet()` globally — each component owns its own
stylesheet, dispatched through `_apply_stylesheets`.*

| Call site | Routes through `_apply_stylesheets`? |
|---|---|
| #1-5 (theme_manager.py, `_apply_stylesheets` itself) | **YES** — this IS the dispatcher body. |
| #6-7 (theme_manager.py, `_apply_stylesheets_deferred`) | **YES** — called exclusively from `apply_full_pass`/`_flush_deferred_restyle_now`, both of which are only reached via `_on_theme_changed`'s call graph, which is the dispatcher's own caller chain. |
| **#8 `app.py:1282` `_set_bg_suppressed` → `mw.content_container.setStyleSheet(...)`** | **NO — CONFIRMED BYPASS.** |

### Flagged bypass: `MainWindow._set_bg_suppressed` (`app.py:1258-1293`)

This method calls `self.content_container.setStyleSheet(get_player_stylesheet(theme_name,
suppress_bg_image=suppressed))` **directly**, entirely outside `_apply_stylesheets`/`ThemeManager`.
It is invoked via `AppInterface.set_bg_suppressed()` (`app.py:104`) from `library_controller.py`
(`apply_library_state`, lines 204/230/238) on book-load, empty-library-state entry/exit, and no-book
transitions — a call graph that is **independent of any `ThemeManager` state machine gating**
(no `_fade_in_flight`/`_any_animating`/hover check of any kind).

Critically, it derives `theme_name` from ThemeManager's live state:
```python
theme_name = (getattr(self.theme_manager, '_active_display_theme', None)
              or self.theme_manager._current_theme_name)
```
`_active_display_theme` is set to the hover-preview theme name whenever a hover preview is in flight
(`_on_theme_changed`, `theme_manager.py:510`, before the hover-vs-non-hover distinction is
otherwise gated) — see finding #2 below for why this specific bypass is the most plausible reachability
path found in this audit. The docstring's own reasoning (avoiding a "flash to the non-cover theme")
shows this was a deliberate design choice, not an oversight, but it was made without considering
`_is_hover_active`.

This bypass writes `content_container`'s stylesheet using whatever theme name `_active_display_theme`
currently holds — hover or not — and this call can land while `_is_hover_active` is `True` (see §4).
**This is the single clearest, most direct candidate root cause found for the theme-bleed bug and is
flagged prominently as requested.**

No other bypass of invariant #4 was found among the `main_window`/`content_container`-touching call
sites inventoried in §1.

---

## 3. State variable read/write inventory (whole-repo grep, not just theme_manager.py)

All three variables are defined and mutated **exclusively within `ui/theme_manager.py`**. The only
cross-file **read** is `_active_display_theme` from `app.py`.

### `_pending_fade_call`
| File:Function | R/W | Condition |
|---|---|---|
| `theme_manager.py:133` `__init__` | W (init `None`) | Construction |
| `theme_manager.py:224-227` `_on_fade_finished` | R+W (consume) | Resumes a stashed call once the fade animation's `finished` signal fires |
| `theme_manager.py:507` `_on_theme_changed` (`elif _fade_running:`) | W (stash) | A new theme-change call arrives while `_fade_in_flight` is `True` |
| `theme_manager.py:794` `complete_main_fade` (log only) | R | Diagnostic `[BLEED-TRACE]` logging, no logic effect |
| `theme_manager.py:860-862` `complete_main_fade` | R+W (consume) | Panel-open path: if a call was stashed when `.stop()` orphaned it (no `finished` emission), hand off via a full `_on_theme_changed(*pending)` re-call instead of the stale fallback reapply |

No occurrences outside `theme_manager.py`.

### `_active_display_theme`
| File:Function | R/W | Condition |
|---|---|---|
| `theme_manager.py:119` `__init__` | W (init to `_current_theme_name`) | Construction |
| `theme_manager.py:178` `get_current_theme` | R | Any caller resolving "what theme is currently shown" (used by `chapter_list_widget.update_theme`, hover buttons, etc.) |
| `theme_manager.py:247` `snap_theme_forward` | R (passed to `_apply_stylesheets`) | Instantly finishing an in-flight fade from the Settings-panel side |
| `theme_manager.py:249` `snap_theme_forward` | R (passed to `_refresh_panel_visuals`) | Same |
| `theme_manager.py:449-455` `_on_theme_changed` | R (no-op guard) | Compared against the incoming `theme_name`+`hover` to short-circuit redundant calls |
| `theme_manager.py:510` `_on_theme_changed` | **W** | Set to `theme_name` unconditionally as soon as the no-op guard and the two animation-in-flight guards (`_any_animating`, `_fade_running`) are cleared — **this write happens for hover calls too** (`hover=True` is a normal argument here), so this variable holds the hover-preview theme name for the duration of the preview. |
| `theme_manager.py:795,869,879` `complete_main_fade` (log only) | R | `[BLEED-TRACE]` diagnostic logging |
| `theme_manager.py:882` `complete_main_fade` (fallback branch) | R (passed to `_apply_stylesheets`) | Only reached if `_pending_fade_call` is `None` at panel-open time — re-polishes sliders using whatever theme is currently "active" |
| **`app.py:1280` `_set_bg_suppressed`** | **R (cross-file)** | Reads directly, with `or self.theme_manager._current_theme_name` fallback only if falsy — **does not check `_is_hover_active` at all**. See §2 bypass finding. |

No writes outside `theme_manager.py`. The one cross-file read (`app.py:1280`) is the load-bearing
link in the reachability trace below.

### `_is_hover_active`
| File:Function | R/W | Condition |
|---|---|---|
| `theme_manager.py:88` `__init__` | W (init `False`) | Construction |
| `theme_manager.py:247` `snap_theme_forward` | R (passed to `_apply_stylesheets`) | Same call as `_active_display_theme` read above |
| `theme_manager.py:450` `_on_theme_changed` | R (no-op guard) | Compared against incoming `hover` |
| `theme_manager.py:458` `_on_theme_changed` | **W** | Set to `hover` unconditionally, *before* the animation-in-flight guards are checked — so this is set to `True` even on a call that will end up stashed in `_pending_fade_call` and not actually applied yet. |
| `theme_manager.py:797,870,880` `complete_main_fade` (log only) | R | `[BLEED-TRACE]` diagnostic logging |
| `theme_manager.py:882` `complete_main_fade` (fallback branch) | R (passed to `_apply_stylesheets`) | Same fallback as above |

No occurrences outside `theme_manager.py` — **`_set_bg_suppressed` (`app.py`) never reads
`_is_hover_active`**, which is the specific gap that makes its `_active_display_theme` read unsafe.

---

## 4. Preview-to-active reachability

### Path A — `_set_bg_suppressed` reading a live hover-preview theme name (HIGH confidence, real bypass, not yet confirmed as THE live bug but structurally sound)

1. User hovers a theme swatch in the Themes tab. `_on_theme_hovered` → (after debounce) `_fire_pending_hover`
   → `_on_theme_changed(theme_name, hover=True)`.
2. `_on_theme_changed` sets `self._is_hover_active = True` (line 458) and, once past the
   `_any_animating`/`_fade_running` guards, `self._active_display_theme = theme_name` (line 510) —
   this is the *hovered* theme name, now live in `_active_display_theme` for as long as the hover
   preview is showing (which can be several seconds if the user holds the hover).
3. **Concurrently**, anything that drives `library_controller.apply_library_state` (a book finishing
   load, a scan completing, folders being added/removed, an "excluded" toggle causing the current book
   to disappear from the visible book, etc.) calls `self.ui.set_bg_suppressed(True/False)` — this path
   has **no coupling whatsoever** to `ThemeManager`'s fade/hover state machine; it can fire at any
   moment, including while a hover preview is actively displayed.
4. `_set_bg_suppressed` (`app.py:1258`) reads `theme_manager._active_display_theme` — at this moment,
   the *hovered* theme name — and calls `self.content_container.setStyleSheet(get_player_stylesheet(
   theme_name, suppress_bg_image=suppressed))` directly, bypassing `_apply_stylesheets` entirely.
5. Result: `content_container`'s stylesheet is now painted with the hover-preview theme's colors, via a
   code path that has no knowledge of hover state and will not be corrected by
   `_on_theme_unhovered`'s subsequent restyle unless that restyle happens to touch
   `content_container` too — which it does (via `_apply_stylesheets`), but only on `_on_theme_unhovered`
   firing (cursor actually leaving the themes tab). If `_set_bg_suppressed` fires again with hover still
   active, or if the timing interleaves such that this call is the LAST write to
   `content_container.setStyleSheet()` before the user leaves the Themes tab under some race, stale
   hover coloring can persist visibly on `content_container` (and by extension appear "bled into the
   main window," since `content_container` is the visible player surface).

This path requires no involvement of `complete_main_fade`, `_pending_fade_call`, or blur code at all —
it is a **structurally independent, second bypass mechanism** from the one already investigated
(`complete_main_fade`'s stale-fallback-reapply theory, NOTES.md lines 280-367). It may explain why
disabling blur does not eliminate the bleed in all cases (NOTES.md explicitly flags this as an
unexplained gap in the `complete_main_fade` theory) — nothing in this path touches
`transport_bar_blur.py` either, so if this is (part of) the real mechanism, "disabling blur eliminates
the bug" would still need a separate explanation (not resolved by this audit; flagged as an open
question, not a contradiction of this finding).

**Confidence: MEDIUM-HIGH that this is A real, exploitable path (the code, read literally, has no
guard preventing it); confidence LOW-MEDIUM that it is THE (or the only) live root cause — not verified
against a live reproduction in this read-only audit.**

### Path B — `complete_main_fade`'s stale-fallback re-apply (documented in NOTES.md, partially mitigated, unverified)

Already documented in detail in `NOTES.md` (lines 280-367) and partially addressed by an uncommitted
code change (the `_pending_fade_call` hand-off branch, `theme_manager.py:860-873`). Re-confirmed by
this audit's reading of the current code: the fallback branch (`theme_manager.py:882`) still reapplies
`self._active_display_theme`/`self._is_hover_active` directly via `_apply_stylesheets` whenever
`_pending_fade_call` is `None` at panel-open time — if `_active_display_theme` is still holding a
hover-preview theme name at that instant (e.g. hover was active, no second call got stashed, but the
hover hadn't been un-set by `_on_theme_unhovered` yet — possible if a panel is opened by some path other
than leaving the Themes tab, e.g. a keyboard shortcut opening Library while hovering), this reapplies
the hover theme onto the **fast synchronous path**, which includes `mw`/`content_container` (call sites
#1 and #3 in §1). NOTES.md explicitly states this fix is **NOT verified** under blur-on soak testing.
**Confidence: MEDIUM (per NOTES.md's own uncertainty) — plausible, previously partially addressed,
verification status unchanged by this audit.**

### Path C — hover write happens before the animating-guards short-circuit (LOW confidence, narrow window)

`_is_hover_active` is written (line 458) *before* the `_any_animating`/`_fade_running` guards are
evaluated, but `_active_display_theme` is written (line 510) *after* those guards clear. This creates a
narrow window where `_is_hover_active == True` but `_active_display_theme` still holds the *previous*
(possibly non-hover) theme name — i.e., the two variables can be transiently inconsistent with each
other. This does not, by itself, let hover *color* reach `main_window`/`content_container` (since
`_apply_stylesheets` hasn't run yet for the hover call), but it does mean any external reader (like
`_set_bg_suppressed`, Path A) that samples `_is_hover_active` and `_active_display_theme` at different
times (it doesn't — it only reads `_active_display_theme`) or that relies on the two being consistent
could be misled. Recorded for completeness; **no confirmed exploitable path found this session beyond
what Path A already covers** (Path A doesn't need `_is_hover_active` consistency at all — it never
reads that variable). **Confidence: LOW / theoretical only.**

### Path D — `_grab_and_blur` compositing a hover-tinted `main_window` frame into the blur overlay (MEDIUM confidence, blur-specific, explains "only reproduces with blur on")

`TransportBarBlurOverlay._grab_and_blur()` (`transport_bar_blur.py:529`) calls
`self.main_window.grab(padded_rect)` — a synchronous rasterization of `main_window`'s **current live
composited appearance**, including `content_container` and everything under it, at the exact instant
the grab runs. This is triggered by `refresh_dirty()` on any real `QEvent.Paint` from one of the 12
tracked transport-bar widgets, with **no check anywhere in this call chain against
`theme_manager._is_hover_active`**. If a hover-preview restyle (`_apply_stylesheets(hover=True)`,
call sites #1/#3/#4/#5 in §1) has just painted `main_window`/`content_container` with the hovered
theme's colors, and a tracked widget happens to repaint (e.g. the marquee-scrolling label, a slider
animation tick) while that hover coloring is still live on screen, `_grab_and_blur` will capture and
bake that hover-tinted frame into the blur overlay's pixmap — which then persists, composited behind
whatever panel is open, until the next dirty-rect refresh happens to land after the hover reverts.
This would visibly read exactly as "hovered theme bled into the live main window," specifically **while
blur is on** (grab only happens as part of the blur overlay's refresh cycle) — which is consistent with
NOTES.md's confirmed observation that both reported bugs only reproduce with blur enabled, and which
neither Path A nor Path B (§4 above) explains on their own. This is a genuinely distinct mechanism from
Path A/B: it does not require any bypass of invariant #4 — `_apply_stylesheets` painted the hover color
correctly and as designed; the bug (if this is it) is that the blur overlay's grab is not
hover-state-aware and can commit a transient/preview frame to a longer-lived pixmap.
**Confidence: MEDIUM — mechanism is structurally sound and specifically explains the blur-only
reproduction gap NOTES.md flags as unexplained by Path B; not verified live in this read-only audit.**

### Paths checked and CONFIRMED safe (documented so what's already safe is recorded too)

- **`_apply_stylesheets_deferred` (library/stats/book_detail panels) cannot show hover color:** it is
  only ever called from `apply_full_pass`/`_flush_deferred_restyle_now`, both reached only through
  `_on_theme_changed`'s `if not hover:` branch (`theme_manager.py:606-607`, `apply_full_pass`'s own
  `if not hover:` gate at line 434). Hover calls never reach this code. Confirmed safe.
- **`theme_applied` signal (`stats_panel`/`tags_panel`/`book_detail_panel.on_theme_changed`) cannot
  carry hover state:** it is only emitted from `apply_full_pass` (line 439, inside the `if not hover:`
  block) and `_flush_deferred_restyle_now` (line 1151, only reached from the non-hover deferred-restyle
  path). Never emitted during a hover preview. Confirmed safe.
- **`sync_all_settings_visuals`/`update_*_visuals` helpers (`app.py`, `settings_controller.py`) cannot
  leak theme *color* to `content_container`/`main_window`:** every occurrence found only calls
  `setProperty`/`style().polish()/.unpolish()` on leaf buttons inside already-themed panels — none of
  them call `setStyleSheet()` on `content_container`/`main_window` or read `_active_display_theme`/
  `_is_hover_active`. Confirmed safe (though `update_theme_list_visuals` was independently investigated
  and disproven as the heartbeat's cause per NOTES.md, not because it's implicated in the bleed).
- **`_pending_fade_call`/`_active_display_theme`/`_is_hover_active` have no writers outside
  `theme_manager.py`:** confirmed by whole-repo grep (§3) — the only external touch-point anywhere in
  the codebase is the single cross-file read at `app.py:1280` (Path A). No other file reads or writes
  any of the three.
- **Cosmetic `setStyleSheet()` calls in `tag_manager.py`, `book_detail_panel.py`,
  `excluded_books.py`, `library.py`, `stats_panel.py`, `cover_panel.py`, `sleep_timer.py`,
  `speed_controls.py`, `text_context_menu.py`:** none of these read `_active_display_theme`/
  `_is_hover_active`, and none target `content_container`/`main_window` directly (only their own
  local widget/subwidget). Confirmed out of scope for both bugs.

---

## Summary of most important findings

1. **Invariant #4 bypass, confirmed:** `MainWindow._set_bg_suppressed` (`app.py:1258-1293`) calls
   `self.content_container.setStyleSheet(...)` directly, entirely outside `_apply_stylesheets`, and
   derives the theme name from `theme_manager._active_display_theme` with **no check of
   `_is_hover_active`**. This is invoked from `library_controller.apply_library_state` on book-load/
   empty-state transitions, on a call graph with zero coupling to ThemeManager's animation/hover state
   machine — it can fire at any moment, including mid-hover-preview.
2. **`_grab_and_blur` (`transport_bar_blur.py:529`) is similarly hover-unaware:** it grabs
   `main_window`'s live composited frame (including `content_container`) on any tracked-widget repaint,
   with no gate on `_is_hover_active`, and bakes whatever is on screen at that instant into the
   longer-lived blur-overlay pixmap. This is a plausible explanation for why both bugs are reported as
   blur-only.
3. The previously-documented `complete_main_fade` stale-reapply mechanism (NOTES.md) remains a
   plausible, partially-mitigated, still-unverified contributor.

Both new paths (A and D) are independent of the already-known/partially-fixed `complete_main_fade`
mechanism and of each other — any structural containment fix should account for all three.
