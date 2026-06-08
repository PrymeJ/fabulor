## Session Summary — 2026-06-08 Session 2

**Branch:** `main` (direct commits)

**Scope:** Fix the EOF finish-revert flow (the auto-dismiss/no-op revert bug
left over from Session 1's banner work), shape its dismissal/feedback
behavior per user spec, then chase a scanner regression ("re-add a removed
location and books stay missing") to its root cause and fix the stats-panel
staleness it exposed along the way.

### What was built

**EOF revert bug — root cause and fix (`bea0b3a`)**
Investigated why the "Marked as finished" banner auto-dismissed after ~10s
and why clicking Revert appeared to do nothing (book stayed finished, banner
"just refreshed"). Two independent bugs at the EOF write site
(`app.py` EOF block, ~line 1345):
- `auto_hide=True, auto_hide_ms=10000` made the banner disappear on its own —
  wrong for a banner carrying action buttons that must persist until the user
  acts.
- `_on_revert_finish` reset `_eof_event_written = False` while the player was
  *still sitting at EOF* (`is_eof` stays `True` until a new file loads). On
  the very next UI tick the EOF block saw the guard cleared and re-fired:
  wrote a fresh `finished` event, re-set `_eof_book_id`, and re-displayed the
  banner+buttons — net effect "revert does nothing, banner just refreshes."
  Removed that reset; the latch now only re-arms in `_on_file_ready` when a
  genuinely new file loads (its correct, pre-existing reset point).
Also removed the `Key_R` debug shortcut (`# TODO: remove before release —
debug shortcut to simulate EOF finished banner`) — its original form
(`write_book_event(self._current_book.id, 'finished')`, swapping `id` into
the `book_path` slot with no `book_id` kwarg) had been writing malformed
`book_events` rows (`book_path='12263'`, `book_id=NULL`) during testing.
Found and deleted ~250 such rows directly from `library.db` (verified zero
remain). The corrected EOF call site (passes `.path`/`book_id=` correctly)
was unaffected.

**Shaping revert/dismiss behavior (`a54e008`)**
Per spec: after reverting, show "Finished status reverted" (no icon — hide
both buttons first) for 5s via the existing `auto_hide`/`status_hide_timer`
machinery, instead of silently vanishing. Added a shared
`_dismiss_eof_prompt()` — hides the prompt without touching the DB, book
stays finished — and wired it into every action that should silently retire
a pending prompt rather than offer a revert: seeking/rewinding away from EOF
(detected at the `is_eof` → playback transition in `_update_ui_sync`'s
`else` branch), clicking Restart, starting the sleep timer, and switching
books (`_on_book_selected_from_library`). The pre-existing scan-start clobber
in `_update_status_banner_ui` (`show_cancel=True` hides the eof controls and
clears `_eof_book_id`) was left as-is — same contract, now commented to make
clear it's intentional rather than incidental — since the banner state there
is already mid-rewrite for the scan message.

**Scanner regression: re-added locations stayed empty (`fea932e`)**
User reported removing then re-adding a scan location left its books "missing"
in the library/stats, requiring a manual force rescan to bring them back —
"adding folders should take effect immediately, just like removing them."
Traced to the documented `known_paths` skip behavior (CLAUDE.md, 2026-06-06
note): `remove_scan_location` soft-deletes (`is_deleted=1`), but a routine
scan sees the path in the unfenced `known_paths` and skips re-processing it
regardless of the flag — only a force rescan calls `upsert_books_batch` and
resets it. `add_scan_location` had no resurrection counterpart. Added
`db.restore_books_under_path(path)` — un-soft-deletes (`is_deleted=0`) books
under `path`, gated on `is_excluded=0` so user-trashed books still require a
manual force rescan (mirrors `remove_scan_location`'s soft-delete query,
inverted) — called from `_on_scan_now_clicked` right after
`add_scan_location`. New CLAUDE.md note documents this as a deliberately
narrower, separate code path from the scanner/`upsert_books_batch`
resurrection.

**Stats/tags panels not reflecting resurrection — two layers**
First layer: `restore_books_under_path` is a synchronous DB write, but the
only existing refresh trigger was `_on_scan_finished` (fires on the scanner's
`finished` signal) — not guaranteed to follow promptly (e.g. a scan already
running means `handle_background_tasks` won't start a new one). Added
explicit `refresh_stats()`/`refresh_tag_manager()` calls right after the
resurrection, mirroring the calls already in `_on_scan_finished`.

Second layer — user reported Stats → Overall's "Recently finished" carousel
stayed stale even across close/reopen, while Day/Week/Month's identical
carousels refreshed fine. Root cause: `FinishedScrollRow.set_items` (shared
by all four) skipped its rebuild whenever the **set of `book_id`s** matched
the previous render — a guard added in an earlier session specifically to
avoid spurious rebuilds from `_invalidate_period_cache()` reordering query
results with no real change. Overall's top-20 membership rarely changes
day-to-day, so the guard kept blocking rebuilds even when order/covers/
`is_deleted` changed; Day/Week/Month's churnier period-scoped lists changed
membership often enough to mask the same bug. Considered unconditionally
rebuilding (simplest, guaranteed-fresh) but rejected it per user concern:
~20 `FinishedBookThumb` widgets rebuilding during the panel-open slide
animation risks exactly the stutter/cover-flash class of bug that
`_add_row_safely`/`refresh_cover`/`on_cover_changed` were built to avoid
elsewhere in this panel. Replaced the set-of-ids guard with an
order-sensitive signature — `(book_id, event_time, active_cover_path or
cover_path, is_deleted)` per row — that deliberately re-introduces order
sensitivity (reordering IS meaningful now: re-finishing reorders the list)
while still skipping the rebuild in the true no-change case. NOTES.md's
existing entry on this widget updated to record both the original rationale
and why it had to be superseded.

### Commits
- `bea0b3a` fix: stop EOF revert from re-arming the finished-event guard
- `a54e008` feat: shape EOF revert-prompt dismissal and post-revert feedback
- `fea932e` fix: resurrect soft-deleted books on location re-add and refresh stats/tags

---

## Session Summary — 2026-06-08 Session 1

**Branch:** `main` (direct commits)

**Scope:** Add a "finish-book" status banner revert/dismiss action; isolate and
fix a tooltip/cursor flicker bug on the new banner buttons; add a "finished"
status icon to the Book Detail Panel sourced from the existing stats query;
wire live-refresh hooks so stats/finished-status/library updates appear in
real time when the relevant panels are already open.

### What was built

**Revert action for the finish-book status banner**
New `db.unfinish_book(book_id)` deletes the most recent `finished` event for a
book. `_on_revert_finish` calls it, resets `_eof_event_written`/`_eof_book_id`,
hides the banner, and refreshes `stats_panel`/`library_panel`. Initially wired
through a generic `status_action_btn` (text-based "Revert" button reused from
the scan-cancel banner), then replaced with two dedicated, purpose-built
buttons — `eof_revert_btn` (icon-only, `revert.svg`) and `eof_close_btn`
("✕", dismiss-only, via new `_dismiss_eof_banner`) — once it became clear the
generic button's styling and layout couldn't serve both the scan-cancel and
finish-revert use cases cleanly. `_eof_book_id: int | None` tracks which book
the pending revert/dismiss applies to; cleared on `load_book` and whenever a
scan starts (`_update_status_banner_ui` now hides both eof buttons and resets
`_eof_book_id` when `show_cancel=True` — a finish banner must not survive a
scan taking over the same banner widget).

**Status banner styling/layout pass**
Banner height raised 30→36px (then `setFixedHeight` 40→36 at the widget level
for consistency), background changed from `transparent`/`setAutoFillBackground`
to a real `WA_StyledBackground` + QSS `background: {bg_status_banner|bg_deep|
bg_main}` (new optional theme key `bg_status_banner`, documented in the theme
key reference at the top of `themes.py`), label font bumped to 15px, and the
`raise_()` call simplified by dropping a stale `_fade_overlay` visibility check
that no longer reflected how the overlay and banner interact.

**Tooltip/cursor flicker — root-caused to `HoverButton`**
`eof_revert_btn` initially used `HoverButton` (for a hover icon-color swap,
`accent` → `accent_light`) plus `setToolTip` and `setCursor`. This combination
produced a visible enter/leave cycle: the tooltip popup overlapped the small
24×24 button, stealing hover, which re-triggered enter/leave on the button,
which re-showed the tooltip — a feedback loop that also made the cursor
flicker between arrow and pointing-hand. Eliminated through systematic
elimination (disabling the icon swap entirely had no effect, ruling out
`setIcon`; A/B testing against `cancel_scan_btn` and `eof_close_btn` — both
stable despite having `setCursor`/`setToolTip` — isolated the cause to
`HoverButton`'s `enterEvent`/`leaveEvent` overrides and signal emission
specifically). Fix: switched to plain `QPushButton` + `installEventFilter(self)`
catching native `QEvent.Enter`/`QEvent.Leave` in the global `eventFilter` to
drive the icon swap directly — stable.

After several precise pixel-offset attempts at custom tooltip positioning
(a `_show_clamped_tooltip` helper anchored to cursor position, adjusted
6px → 8px → 14px gaps per user feedback), the user concluded the tooltips
were unnecessary — both buttons are visually self-explanatory — and asked to
drop them entirely rather than keep chasing placement. Fully removed:
`setToolTip` calls on both buttons, `_show_clamped_tooltip` method, the
`QEvent.ToolTip` branch in `eventFilter`, and the now-unused `QToolTip` import.
Verified via grep returning zero matches across all four symbols.

**QSS specificity and dead-code cleanup**
Confirmed and cleaned up two leftover issues from the styling pass: a dead
duplicate `#eof_revert_btn`/`:hover` block in `get_player_stylesheet`
(unreachable — that stylesheet targets `content_container`, a sibling of
`status_banner`, not an ancestor — same class of cascade trap as the
documented `bg_image`/`visual_area` rule in CLAUDE.md), and a blanket
`QPushButton { background: transparent; border: none; padding: 0px; }` rule
that had been added to the `mw`-scoped stylesheet and was silently flattening
`cancel_scan_btn`'s border-radius (it matched every `QPushButton` in scope,
including buttons with their own radius rules). Both removed; the final
`#eof_revert_btn`/`#eof_close_btn` rules are qualified with the `status_banner`
ancestor (`QWidget#status_banner QPushButton#eof_revert_btn`) to win cascade
specificity without a blanket rule.

**SVG icon loading consolidation**
Per a separate plan-mode assessment, deleted the duplicate `_load_svg_icon` in
`book_detail_panel.py` (and its `functools.lru_cache` import) and migrated its
8 call sites to the existing `load_themed_icon` in `icon_utils.py` — the two
were near-identical copy-paste functions. `ui_helpers._load_svg_icon` was
deliberately left untouched: it returns `QIcon` (not `QPixmap`), supports
dynamic sizing, and has richer CSS-form regex recoloring that `restart.svg`
specifically depends on to render in the correct theme color — consolidating
it in would have broken that icon's rendering.

**Finished status icon in Book Detail Panel**
Added `self._finished_label` (16×16 `QLabel`, `check.svg` via
`load_themed_icon` at `accent` color, size 16, opacity 0.7 — matching the
existing trash/lock/save icon convention) positioned in `right_col` directly
below `_meta_action_btn`, aligned with the narrator row. Sourced from
`stats['finished_count'] > 0` — the exact same value already computed for the
Stats tab's "Finished" row — achieving a single source of truth with zero
additional DB queries. `_update_finished_icon(finished: bool)` owns visibility
and pixmap; wired into `_refresh_stats()` and `on_theme_changed`.

Layout fix: the icon initially slid up into the lock/save button's space when
that button was hidden (its layout slot collapsed). Fixed by adding
`setRetainSizeWhenHidden(True)` to `_meta_action_btn`'s `QSizePolicy` so it
always reserves its 24×24 footprint in `right_col`, pinning the finished icon
beneath it regardless of the action button's visibility.

**Live-refresh wiring for stats/finished-status/library**
Previously, finishing a book or closing a session while the Book Detail Panel,
Stats Panel, or Library Panel (Finished view) was open did not update those
views — only a close-and-reopen refreshed them. Added `isVisible()`-gated
refresh calls (matching the existing pattern in `stats_panel`):
`_on_session_written` now also calls `book_detail_panel._refresh_stats()` when
visible; the EOF "marked as finished" handler now also calls
`library_panel.refresh()` and `book_detail_panel._refresh_stats()` when those
panels are visible. Confirmed final behavior matches the user's spec exactly:
when in the main window, Library/Stats/Book-Detail show the update on next
visit (no refresh cost paid while not visible); when already viewing one of
those panels, the update appears live.

### Files touched
- `app.py` — `_update_status_banner_ui`, `_on_revert_finish`, `_dismiss_eof_banner`,
  `_eof_book_id`, eventFilter (icon hover swap via `QEvent.Enter`/`Leave`,
  tooltip interception added then fully removed), `_reload_button_icons`,
  `_on_session_written`, EOF "marked as finished" handler, debug shortcut `R`
- `db.py` — `unfinish_book`
- `themes.py` — `bg_status_banner` theme key, `#eof_revert_btn`/`#eof_close_btn`
  QSS (scoped to `status_banner` ancestor), removed dead duplicate block and
  blanket `QPushButton` rule
- `ui/main_window_builders.py` — `build_status_banner` (eof button construction,
  sizes, cursors, removed tooltips and `HoverButton`)
- `ui/book_detail_panel.py` — `_finished_label`, `_update_finished_icon`,
  `_refresh_stats`/`on_theme_changed` wiring, `_load_svg_icon` → `load_themed_icon`
  migration
- `assets/icons/revert.svg` — new icon

---

## Session Summary — 2026-06-07 Session 1

**Branch:** `main` (direct commits)

**Scope:** Eliminate book-switch animation race conditions; fix chapter label
staleness; replace chapter list widget-per-row with delegate; timer suspension
during animation window.

### What was fixed

**ui_timer suspension during book-load animation window**
`_on_file_ready` now stops `ui_timer` at the top of the method (covers both
startup and library-load paths). `_resume_ui_timer()` restarts it and is
connected to `progress_slider._flow_anim.finished` for the animate path;
called explicitly on all non-animate exits (setValue, no-duration, error).
Eliminates the one-tick race where the timer wrote `setValue` before
`_flow_anim.state()` transitioned to `Running`.

**Chapter label and hints staleness on book switch**
`_on_file_loaded_populate_chapters` now calls
`_update_chapter_label_from_index(curr_chap_idx)` at the end, gated on
`not self.player.is_seeking`. When seeking, `chapter_changed` handles the
label post-settle; when not seeking (position 0, VT), this is the only write
opportunity. Also hoisted `curr_chap_idx` out of the inner block so it is
in scope at the call site.

**Chapter list delegate refactor (`chapter_list.py`)**
Replaced `QWidget`/`QHBoxLayout`/`QLabel` per-row construction with
`ChapterItemDelegate(QStyledItemDelegate)`. `populate()` now creates only
`QListWidgetItem` + 3 `setData()` calls per chapter — no widget lifecycle,
no `setItemWidget()`. Paint fires only for visible rows. `update_theme()`
passthrough added to `ChapterList`; wired in `theme_manager.py` alongside
the library delegate update. `ROLE_CHAP_INDEX`, `ROLE_CHAP_TITLE`,
`ROLE_CHAP_DURATION` replace anonymous `Qt.UserRole` offsets.

### What was attempted and reverted

**Seek-settle deferral for VT file-boundary seeks (`player.py`)**
Attempted to defer `file_switched` emission until after `_pending_local_pos`
seek settled in `_on_time_pos_change`. Introduced undo regression (VT slider
stuck after undo). Reverted cleanly.

**Populate deferral to after `_flow_anim.finished`**
Added `chaps_flow_deferred` flag to defer `_on_file_loaded_populate_chapters`
until after the flow animation. Fixed the bottleneck but caused chapter and
progress sliders to flow sequentially rather than simultaneously — visual
regression. Reverted.

### Known remaining issues

**Startup animation stutter (all book types, VT worst)**
On startup, the event loop is under pressure from background work (stats
cache, cover cache, library population) when `book_ready` fires. The flow
animation competes for main-thread time, producing a visible stutter around
the 15-25% mark. Library loads are smooth because the event loop is idle.
Three options documented for future revisit:
1. Skip animation on startup (detect via `_switch.phase == IDLE`), go
   straight to `setValue`. Low risk, inconsistent UX.
2. Defer/cheapen background work — lazy load stats/cover cache, move work
   off main thread. Correct long-term fix, large scope.
3. Delay animation — fragile, hardware-dependent. Rejected.

**Intermittent chapter[0] flash on M4B startup (very rare)**
Pre-existing. Not addressed this session.

### Files touched
- `app.py` — `_on_file_ready` (timer stop), `_resume_ui_timer` (new method),
  `__init__` (`_flow_anim.finished` connection), `_on_file_loaded_populate_chapters`
  (chapter label write)
- `ui/chapter_list.py` — delegate refactor
- `ui/theme_manager.py` — `update_theme` call for chapter list

---

## Session Summary — 2026-06-06 Session 2

**Branch:** `refactor/extract-mainwindow-builders` → merged to `main`

**Scope:** Attempted structural fix for book-switch animation race conditions;
reverted after cascading regressions; merged stable branch to main.

### What was attempted (and reverted)

**Seek-settle deferral (`wip: converge slider animations at seek_settled signal`)**
Goal was to eliminate three races: flow animation stutter, intermittent chapter[0]
flash, and notch double-animation. Approach deferred `animate_to` to a new
`_on_seek_settled()` convergence point triggered by a `seek_settled` signal from
`player.py` and a direct inline call from the no-progress `_restore_position` path.

Reverted after producing: slider/fill desync, broken undo, notch reanimation on
every scrub, VT slider corruption, and chapterless book snaps. Root cause was
accumulated sequencing complexity — each fix introduced new race surfaces faster
than old ones were closed.

### What was merged to main

Branch merged as-is at pre-wip state. Remaining known issues carried forward:

- Flow animation stutter on book switch (rare) — 200ms timer has a one-tick race
  with `animate_to`; structural fix is to suspend timer during load window and
  resume on `_flow_anim.finished`. Documented in NOTES.md.
- Intermittent chapter[0] flash on M4B startup (very rare)

### Key learning

The `_on_seek_settled` consolidation was correct in intent but wrong in execution.
The 200ms timer is the silent antagonist — it fires regardless of load state and
requires guards that have a one-tick gap. The proper fix is structural: suspend
`ui_timer` during the book-load window (from book selection until
`_flow_anim.finished`), not flag-based guarding. Deferred to a focused session.

### Files touched
- `app.py` — wip changes reverted; net change from session: none beyond branch baseline
- `player.py` — `seek_settled` signal added and removed; net: none
- `book_switch.py` — unchanged from branch; still in main as part of
  BookSwitchState refactor

---

## Session Summary — 2026-06-06 Session 1

**Branch:** `refactor/extract-mainwindow-builders` (NOT merged to main)

**Scope:** Book-switch animation polish; chapter label flash; stale slider after book removal; scanner resurrecting excluded/deleted books.

### What was fixed

**Progress slider flows from 0 on startup** — `_on_file_ready` was skipping the animation entirely when `SM.take_progress_target()` returned `None` (no switch in progress). Now defaults `pre = 0`, so startup, EOF-restart, and post-removal loads all animate from 0. EOF-restart is safe: `new_progress == 0` → `new_val == 0` → `pre == new_val` → `setValue(0)`, no animation. DB duration fallback (`book_data.duration`) added alongside `player.duration` to cover the cold-start duration race without affecting the `_chaps_dur_retried` retry path.

**Chapter slider flows from 0 on startup and chapterless→chaptered** — same `pre_chap = 0` default applied to `_on_file_loaded_populate_chapters`. Chapterless→chaptered now animates correctly; `begin()` passes `None` for chapterless outgoing books (no meaningful capture), which the default converts to 0.

**Chapter label flash to index 0 on deferred populate** — `_update_chapter_label_from_index` now has a second gate: `self._switch.flow_pending_chapter`. In the deferred path the seek settles before the 50ms drain fires, leaving `_is_seeking` already False when `populate()` emits `currentRowChanged(0)`. The `flow_pending_chapter` gate is True throughout the `try` block (consumed only after it), blocking the spurious index-0 write.

**Stale progress slider value after book removal** — `_on_book_removed` was not zeroing `_value` before clearing `_suppress_fill`. When the next book loaded, the first paint showed the old book's final position. Fixed: stop `_flow_anim`, set `_value = 0`, reset chapter slider and chapter UI state before `_load_cover_art("")`.

**Scanner resurrecting excluded/deleted books** — `known_paths` was built from `get_all_books()` (fenced by `is_excluded=0 AND is_deleted=0`). Excluded/deleted books were absent, treated as new by the scanner, and upserted — resetting both flags to 0 on every scan. Fix: new `get_all_book_paths()` method (unfenced `SELECT path FROM books`) used in scanner instead. Side effect: folder removal + re-add no longer auto-resurrects `is_deleted` books via a non-force scan. Manual Rescan still works. Silent resurrection was the worse behavior.

### Non-obvious decisions

See NOTES.md entries dated 2026-06-06 for full reasoning on: startup `pre=0` safety, `flow_pending_chapter` gate rationale, `_set_bg_suppressed` direct color assignment vs `_set_chapter_ui_active`, removal of preemptive `_set_chapter_ui_active(False)`, and scanner `known_paths` unfencing.

### Files touched
- `app.py` — `_on_file_ready` (pre=0 default, DB duration fallback), `_on_file_loaded_populate_chapters` (pre_chap=0 default), `_update_chapter_label_from_index` (flow_pending_chapter gate), `_on_book_removed` (slider zero before _load_cover_art).
- `db.py` — `get_all_book_paths()` (new unfenced method).
- `library/scanner.py` — use `get_all_book_paths()` for known_paths.

---

## Session Summary — 2026-06-05 Session 4

**Branch:** `refactor/extract-mainwindow-builders` (NOT merged to main)

**Scope:** Book-switch transition visual fixes — chapterless background flash, chaptered→chaptered chapter slider flow, progress slider 0% regression.

### What was fixed

**Chapterless→chapterless background flash** — `_set_bg_suppressed` calls `content_container.setStyleSheet(...)`, which triggers Qt to call `polish()` on all child widgets. `polish()` re-reads the QSS and restores the chapter slider's `bg_color`/`fill_color` from the stylesheet, overriding the transparent values set by the earlier `_set_chapter_ui_active(False)`. Fix: lightweight re-assert directly after `setStyleSheet` in `_set_bg_suppressed`, guarded by `not _chapter_ui_active`:

```python
if not getattr(self, '_chapter_ui_active', True) and hasattr(self, 'chapter_progress_slider'):
    s = self.chapter_progress_slider
    s.bg_color = QColor("transparent")
    s.fill_color = QColor("transparent")
    s.update()
```

This is intentionally NOT a call to `_set_chapter_ui_active()` — that carries side effects (animation stops, cursor, label stylesheet) that are wrong at this call site.

**Chaptered→chaptered chapter slider flow** — the unconditional preemptive `_set_chapter_ui_active(False)` in `_on_book_selected_from_library` was hiding the chapter slider before load regardless of whether the outgoing book had chapters. For chaptered→chaptered, this killed the flow animation: the slider would clear, blink, then animate from the old position instead of holding it visibly and flowing cleanly to the new one. Removing the unconditional call restores the correct behavior. The `_set_bg_suppressed` guard handles chapterless books; chaptered books stay visible and flow.

**`_switch.begin()` pre_chap=None for chapterless outgoing books** — capturing the slider value when `_chapter_ui_active` is False armed `flow_pending_chapter` unnecessarily. Now `None` is passed, keeping `flow_pending_chapter` False and `_sync_chapter_ui` ungated throughout.

**Progress slider 0% flash gone** — the 200ms timer no longer writes 0 during the pre-ready window. Occasional jump on progress slider remains — pre-existing race, not zeroing.

### Invariants established

`_set_bg_suppressed` must re-assert transparency after `setStyleSheet`. Qt's repolish overwrites custom color properties on child widgets. The lightweight re-assert is load-bearing — remove it and the chapterless flash returns.

### Remaining known issues

- Progress slider occasional jump — intermittent race, pre-existing.
- Chapterless↔chaptered transitions are abrupt (slider appears/disappears without animation) — cosmetic, deferred.
- DB-first progress value causes drift visible in short chapters (≤15s) — deferred.

---

## Session Summary — 2026-06-05 Session 3

**Branch:** `refactor/extract-mainwindow-builders` (NOT merged to main)

**Scope:** Consolidate the scattered book-switch transition guards into a single state machine. No behavior change — every guard site is a 1:1 predicate rename with identical timing.

### What was built

**`book_switch.py` + `BookSwitchState`** — a single authority for the book-switch lifecycle. Previously, six concurrent concerns (`book_ready` emission, library slide-out animation, mpv position-restore seek, cover load, 200ms UI timer, cover-art theme fade) were coordinated by ad-hoc flags read directly off `MainWindow`. The Session 2 regression list above is the symptom: each fix added another scattered guard. `BookSwitchState` now owns the six **switch-specific** flags behind an explicit `SwitchPhase` (`IDLE`/`LOADING`/`RESTORING`). Instantiated once as `self._switch` in `MainWindow.__init__`.

Flags absorbed (old `MainWindow` attr → SM): `_mpv_ready` → `in_deadzone` (inverted); `_pre_switch_slider_value` → `flow_pending_progress` + `take_progress_target()`; `_pre_switch_chap_slider_value` → `flow_pending_chapter` + `take_chapter_target()`; `_chaps_dur_retried`, `_file_ready_deferred`, `_chaps_deferred` → same-named SM members.

**Transitions:** `begin(pre_slider, pre_chap)` (IDLE→LOADING) in `_on_book_selected_from_library`; `library_revealed()` (LOADING→RESTORING) in `panels._on_library_hidden`; the two `take_*_target()` consumers drain captures back to IDLE.

### Non-obvious decisions

**Phase is *derived*, not stored.** `phase` is computed from `in_deadzone` + the two pre-value sub-flags, so there is no fragile terminal "switch done" transition: it returns to `IDLE` automatically once the deadzone ends and both `book_ready` handlers consume their captures. The post-consume animation/seek-settle window is carried by the retained orthogonal guards — exactly as before.

**Scope boundary: switch-specific flags only.** The SM does NOT absorb the *orthogonal* guards — `player._is_seeking`/`_seek_target`, the slider-drag flags, `_flow_anim` running state, `mp3_seek_reload_pending`. Those fire for non-switch reasons (chapter nav, manual seeks, theme color animations, MP3 stop-and-load) and are the documented fixes for the Session 2 bugs. Absorbing them would extend the blast radius into chapter navigation and manual seeking. The SM *composes* with them: e.g. `_sync_progress_sliders` still reads `not is_seeking and not slider_animating and not self._switch.flow_pending_progress`.

**`_mpv_ready` writes outside the selection path were deleted, not rerouted.** Init (`__init__`), startup-restore, and EOF-restart never call `begin()`, so phase is `IDLE` and `in_deadzone` is already `False` there — the old `_mpv_ready = True` writes were no-ops. Only the selection-path write became `begin()`.

**The ghost fix is orthogonal and untouched.** The chapter-slider ghost (theme-fade overlay punch-through exposing a moving `animate_to()` fill) is fixed by the double-chain `when_animations_done` wait in `_apply_pending_cover_theme`, not by any of the six flags. The SM left it alone, so consolidation neither fixes nor breaks it.

### Known limitation (pre-existing, not addressed)

**Rapid-switch has no stale-book guard.** `_on_file_ready` operates entirely through `self.current_file` (set synchronously by `begin()`); there is no switch-generation token dropping a `book_ready` queued for an earlier selection. `take_progress_target()` is the identical read-and-null as the old code — same exposure, no better, no worse. The SM is the natural home for a future fix (a `generation` counter bumped in `begin()` and checked by each handler), but that is a behavior change and was deliberately left out of this consolidation.

### Files touched
- `book_switch.py` (new) — `BookSwitchState`, `SwitchPhase`.
- `app.py` — instantiate `self._switch`; delete the six attrs + three non-selection `_mpv_ready` writes; rewrite `_on_book_selected_from_library`, `_on_file_ready`, `_on_file_loaded_populate_chapters`, `_drain_deferred_file_ready`, and the guard sites in `_update_ui_sync`/`_sync_progress_sliders`/`_sync_chapter_ui`/`_sync_persistence`.
- `ui/panels.py` — `_on_library_hidden` uses `library_revealed()` + SM deferred flags.
- `player.py` — **not** touched (seek lifecycle out of scope).

---

## Session Summary — 2026-06-05 Session 2

**Branch:** `refactor/extract-mainwindow-builders` (NOT merged to main)

**Scope:** MainWindow builder extraction refactor; post-refactor regression fixes for book-switch animation pipeline (progress slider, chapter slider, chapter label, cover theme, chapter slider background).

### What was built

**Refactor: `ui/main_window_builders.py` + `ui/ui_helpers.py`** — extracted all 19 `_build_*` methods from `MainWindow` into free functions. Each takes `mw` and assigns widgets directly onto it; `_setup_ui` calls them in identical order. `COVER_AREA_HEIGHT`, `_load_svg_icon` moved to `ui_helpers.py` to avoid circular imports. `app.py` dropped ~1100 lines (3071 → ~1970). Batch A: player-view builders. Batch B: panel builders. Batch C: settings builders (intra-module calls become plain function calls, not `mw.`). All tests confirmed working before this session's regressions surfaced.

### Post-refactor regressions fixed (all on the branch)

**Progress slider 0% flash (root cause, `player.py`)** — `_on_time_pos_change` cleared `_is_seeking` on the first `time_pos=0` from the new file (the `_seek_target is None` branch). `_sync_progress_sliders` guards on `not is_seeking`, so the guard was instantly dropped, allowing the 200ms timer to write 0 to the slider before `_on_file_ready` ran. Fix: `_is_seeking` only clears when `_seek_target is not None AND abs(global - target) < 1.0`. `load_book` now resets `_seek_target = None` alongside `_cached_time_pos`/`_cached_duration`. `_restore_position` explicitly clears `is_seeking=False` for the no-progress case. See CLAUDE.md "DO NOT restore the `_seek_target is None` branch" rule.

**Progress slider: dur=None race (`_on_file_ready`)** — when `_cached_duration` hasn't arrived yet, `not dur` was animating to 0 as a fallback. Fixed to set `new_val = None` and skip animation when dur unavailable (after DB fallback `book_data.duration` also fails). `new_progress == 0` is now a separate branch that always animates to 0 correctly.

**Progress slider snap (DB duration fallback)** — `_on_file_ready` now falls back to `book_data.duration` (DB-stored) when `_cached_duration` is None. Lets animation run with an approximate target rather than skipping and snapping.

**Chapter label/slider not appearing: `_chaps_dur_retried` retry** — `_on_file_loaded_populate_chapters` was calling `_set_chapter_ui_active(False)` when `dur=None`, making the chapter label transparent for the entire session. Fixed: if `dur=None`, schedule one 150ms retry (`_chaps_dur_retried` flag, reset in `_on_book_selected_from_library`) instead of deactivating. Retry proceeds normally when duration arrives.

**Chapter label oscillation / VU-meter during seeks** — `_update_chapter_label_from_index` now gates on `is_seeking`. Intermediate `time_pos` events as mpv scans toward the seek target crossed chapter boundaries, firing `chapter_changed` on each, producing visible label oscillation on backward seeks. Gate suppresses all updates during seeking; the final `time_pos` event that settles the seek fires one clean update. Side effect: CUE-mode optimistic emit from `seek_async` is also suppressed, but the settle-time `time_pos` still updates within ~100ms.

**Chapter label stuck on wrong book after seek** — the `is_seeking` gate blocks label updates but `_on_time_pos_change` still updates `_last_nonvt_chapter` during intermediate events. When the seek settled at the same chapter as the last tracked one, `curr == _last_nonvt_chapter` → no `chapter_changed` emit → label never updated. Fixed in `player.py`: reset `_last_nonvt_chapter = -1` and `_last_vt_chapter = -1` when `_is_seeking` clears, guaranteeing one final emit.

**Chapter slider timer jitter after seek** — after the seek completed, the 200ms timer wrote intermediate positions to the chapter slider. Added `is_seeking` guard to `_sync_chapter_ui` (now mirrors `_sync_progress_sliders`). Timer self-corrects within one 200ms tick after seek settles.

**Chapter slider background flash (no-chapter books)** — the slider background area briefly appeared during book switches. Root cause: `_on_book_selected_from_library → apply_current_state → _set_bg_suppressed` repolished the chapter slider's `bg_color` back to a theme color before `_on_file_loaded_populate_chapters` called `_set_chapter_ui_active(False)`. Fixed: preemptive `_set_chapter_ui_active(False)` in `_on_book_selected_from_library` at selection time. Slider stays transparent throughout; `_on_file_loaded_populate_chapters` calls `_set_chapter_ui_active(True)` only when chapters are confirmed.

**Chapter slider bg flash from running color animations** — if a theme fade started while the book had chapters, `QPropertyAnimation` instances on `bg_color`/`fill_color` targeted non-transparent colors. When switching to a no-chapter book, `_set_chapter_ui_active(False)` set `bg_color = transparent`, but the running animation immediately overrode it on the next frame. Fixed: `_set_chapter_ui_active(False)` now stops any in-flight `_slider_anims` for the chapter slider before setting transparent.

**Cover art theme flash to pool theme** — `_set_bg_suppressed` was regenerating the `content_container` stylesheet using `_current_theme_name` (the named pool theme) instead of `_active_display_theme` (which holds the cover art dict when a cover theme is active). `apply_library_state` calls `_set_bg_suppressed(False)` on every book switch, causing a brief flash to the pool theme between every cover-art-theme transition. Fixed: `_set_bg_suppressed` now uses `_active_display_theme or _current_theme_name`.

### Reverted / known remaining issues

**Chapter slider value animation reverted** — the original `_on_file_loaded_populate_chapters` code used `animate_to(new_chap_val, old_value=pre_chap)` for a "flow" animation on the chapter slider during book switches. This was NOT introduced this session (it was pre-existing). However testing confirmed it causes ghosting: the theme overlay punch-through exposes the chapter slider widget, and the moving slider value creates a visible ghost against the static overlay screenshot. Reverted to `setValue(new_chap_val)`. The authoritative position computation (chapter list walk against saved progress) was retained; only the animation call was removed. The `_pre_switch_chap_slider_value` flag and its `_sync_chapter_ui` guard were removed with it.

**Progress slider still occasionally snaps** — the `dur=None` path where neither `_cached_duration` nor `book_data.duration` is available. Rare but not eliminated. The DB fallback covers most cases.

### What to watch for if reverting the refactor

If the branch is reverted to the pre-refactor state on `main`, the following fixes should be cherry-picked or manually applied (they are independent of the extraction):
1. `player.py` `_on_time_pos_change` — `_seek_target is None` branch fix
2. `player.py` `_last_nonvt_chapter`/`_last_vt_chapter` reset on seek clear
3. `app.py` `_on_file_ready` — `dur=None` skip instead of animate-to-0
4. `app.py` `_on_file_loaded_populate_chapters` — `_chaps_dur_retried` retry, preemptive `_set_chapter_ui_active(False)`, authoritative `new_chap_val` computation, and removal of `animate_to`
5. `app.py` `_update_chapter_label_from_index` — `is_seeking` gate
6. `app.py` `_sync_chapter_ui` — `is_seeking` guard
7. `app.py` `_set_chapter_ui_active(False)` — stop running color animations
8. `app.py` `_set_bg_suppressed` — use `_active_display_theme` not `_current_theme_name`
9. `app.py` preemptive `_set_chapter_ui_active(False)` in `_on_book_selected_from_library`

---

## Session Summary — 2026-06-05 Session 1

**Scope:** Library sort view — Progress and Finished sort keys, dynamic sort combo, sort direction defaults, null-last sorting.

### What was built

**"Progress" and "Finished" sort keys** — two new conditional sort options added to the library panel sort combo. "Progress" appears only when at least one visible book has `progress > 1.0`; "Finished" appears only when at least one visible book has a `finished` event in `book_events`. Checked via `db.has_books_with_progress()` and `db.has_finished_books()` on each `refresh()`. `db.get_finished_book_data()` returns `{book_id: datetime}` of the most recent finished event per book, stored as `BookModel._finished_dates`.

**Dynamic sort combo** (`_rebuild_sort_combo`) — replaces the static 6-item population in `_setup_ui`. On first call reads sort key and direction from config (via `_sort_initialized` flag); subsequent calls preserve current state. When a conditional key is removed (e.g. last progress book deleted), falls back to Title and applies Title's default direction, saving both to config.

**Sort direction defaults** (`_SORT_DIRECTION_DEFAULTS`) — class-level dict mapping each key to its default ascending bool. `_on_sort_changed` applies the default for the new key and saves key+direction to config immediately. `_toggle_sort_direction` saves only the direction. Config always holds exactly what's shown.

**Null-last sorting** — `effective_val(b)` replaces the old `_is_missing` predicate and the `None`-fallback inside `sort_key`. Returns the actual sortable value or `None` for: computed fields (`finished` → checks `_finished_dates`, not `Book`), progress/last_played below threshold, `None` DB values, and empty/whitespace strings. `have/missing` split is now universal across all sort fields — books with no value for the active field always appear at the end regardless of direction.

**`history_deleted` wired to library refresh** — `BookDetailPanel.history_deleted` now also connects to `LibraryPanel.refresh` so the Finished key disappears immediately when a user deletes all history for the last finished book.

### Non-obvious decisions

- `"finished"` is a computed sort key, not a DB column. `start_idle_preload` and any other path passing sort keys to `get_all_books` falls back to `"title"` when the key is not in `db._ALLOWED_SORT_COLUMNS`.
- `books.finished_at` exists on the schema but is never written — `_finished_dates` from `book_events` is the sole source of truth for Finished sort/filter. `finished_at` is inert.
- `effective_val` must handle `"finished"` via `_finished_dates.get(b.id)` — `getattr(b, "finished", None)` silently returns `None` for every book (field doesn't exist on `Book`), which would dump the entire Finished view into `missing`.
- Sort direction and sort key are always saved to config together as a pair in `_on_sort_changed`. Saving only the key (as in a previous iteration) caused wrong direction on next startup if the key's default differed from the saved direction.

---

## Session Summary — 2026-06-04 Session 3

**Scope:** Period navigation UX improvements in stats_panel.py — right-click jump-to-boundary on nav buttons, mouse wheel navigation on period headers, and a user-configurable scroll acceleration setting.

### What was built

**Right-click on ‹ / › nav buttons** — jumps to the oldest or newest available period without stepping through intermediate entries. Six methods added (`_day/week/month_oldest/newest`); `mousePressEvent` overridden on all six buttons via lambda assignment (same pattern as the existing reset-confirm handler). Right-click `‹` → oldest (highest index), right-click `›` → newest (index 0).

**Mouse wheel on period header** — `wheelEvent` installed on the header widget (`QWidget` containing the arrows and date label) for each of the three period tabs. Scoped to the header only; does not capture wheel events from the book-row grid, carousel, or tab widget. Wheel-up moves toward the most recent period, wheel-down moves toward the oldest.

**Day-tab scroll acceleration** — step size derived from total number of available day periods at wheel time: 1/2/3/4/7 (thresholds: 50/100/200/300). Week and Month always step 1. The step table is read lazily from `_active_days` at event time, so no extra DB query is needed.

**"Period scroll acceleration" toggle in Stats ⚙ tab** — On/Off `pattern_button` row under the "Day starts at" spinner. Uses `config.get/set_stats_accel_scroll()` (default On, stored as `"true"`/`"false"` string in QSettings). When Off, step is always 1 regardless of period count. Button selected state uses the standard `setProperty("selected", ...)`/`unpolish`/`polish` pattern.

### Non-obvious decisions

- `wheelEvent` is installed on the `header` local variable directly (same closure-assignment pattern as the button `mousePressEvent` overrides already in the file). No subclass or event filter needed.
- The acceleration guard sits inside `_day_wheel` only — Week/Month closures are unaffected and remain unconditionally step-1, so the setting has no code path to toggle there.
- `_active_days/weeks/months` are accessed via `getattr(..., None) or []` inside the wheel closures — safe at install time when the lists don't exist yet.

---

## Session Summary — 2026-06-04 Session 2

**Scope:** Fix cover flicker and widget stacking in the stats panel's finished-books carousel (`FinishedScrollRow` / `FinishedBookThumb` in `stats_panel.py`).

### What was built

**Root-cause investigation** — traced three separate bugs through `_cover_cache`, `CoverLoaderWorker`, the idle preloader, and the `set_items` call chain:

1. **`FinishedBookThumb._on_cover_loaded` discarded worker result** — cover was applied locally but never written to `_cover_cache`, so every carousel rebuild for excluded/deleted books (preloader skips them) or custom-cover books (before preloader reached them) was a cold-cache miss. Fix: write `_cover_cache[self._book_id] = pixmap` before `_apply_cover`, storing `self._book_id` in `__init__`.

2. **`_current_ids` guard was order-sensitive** — `set_items` compared `incoming_ids == self._current_ids` as list equality. `_on_tab_changed` calls `_invalidate_period_cache()` before each refresh, causing the DB to re-run `get_finished_in_period` which could return the same books in a different order — bypassing the guard and triggering a full rebuild. Fix: changed to `set(incoming_ids) == set(self._current_ids)`.

3. **`setWidgetResizable(True)` prevented horizontal scrolling** — forces the container to fill viewport width, compressing fixed-size thumbs instead of overflowing. Fix: set `setMinimumWidth(n × 47 + (n−1) × 4)` on the container after population, allowing the layout to overflow correctly while keeping `setWidgetResizable(True)` for correct height.

`setParent(None)` replaced `deleteLater()` in the clear loop for synchronous widget removal.

### Non-obvious decisions

- First-visit cold-cache flash (books not yet in cache on first stats-panel open) is accepted — inherent to the lazy-load architecture. The fix eliminates all *subsequent* flickers, which was the real UX problem.
- `_current_ids` stores a list (insertion order preserved for future use) but comparison is set-based — only the comparison operator changed, not the storage type.
- `setWidgetResizable(False)` was tried and caused all thumbs to disappear (container collapsed to zero height). Reverted immediately; `setMinimumWidth` was the correct solution.

---

## Session Summary — 2026-06-04 Session 1

**Scope:** Reorganise and normalise `themes.py` theme dicts — key renames, canonical ordering, formatting, alphabetical sort.

### What was built

**Key renames** (updated in `themes.py`, `cover_theme.py`, `library.py`, `book_detail_panel.py`):
- `bg_library` → `library_bg`
- `progress_text` → `slider_progress`
- `expand_button` → `dropdown_expand`
- `curr_chap_highlight` → `dropdown_curr_chap`
- `panel_theme_names_dimmed` → `settings_theme_names_dimmed`

**Canonical key order** established and applied to all 58 themes:
1. Core backgrounds (`bg_deep`, `bg_main`, `bg_sidebar`, `bg_dropdown`, `bg_image`, `panel_opacity_hover`, `undo_hover`)
2. Core text & accent (`text`, `text_on_light_bg`, `accent`, `accent_light`, `accent_dark`)
3. Player buttons (`button_text`, `button_play`, `button_skip`, `button_chapter`, `slider_progress`)
4. Player sliders (overall, chapter, vol + `notch_color`, `notch_opacity`)
5. Chapter dropdown (`dropdown_curr_chap`, `dropdown_text`, `dropdown_time_text`, `dropdown_expand`)
6. Sidebar (`sidebar_text`, `sidebar_text_hover`, `sidebar_opacity`)
7. Library display (`library_bg` through `search_error_text`)
8. Settings panel (`settings_tab_hover_*`, `settings_theme_names_dimmed`)
9. Tags (`tag_list_text`, `tag_list_text_hover`)
10. Misc UI (`cover_preview_bg`, placeholder covers, carousel)
11. Gradients (all `gradient_*` keys last)

**Formatting normalised** across all themes: uniform `"key":` column width (32 chars), single space before value, all hex codes uppercased, floats consistently formatted.

**Theme dict alphabetically sorted** A–Z (accent-insensitive, so Melnibonéan sorts with M).

**Docstring updated** with new key names and corrected fallback references (`bg_library` → `library_bg` in three entries).

### Non-obvious decisions
- `panel_opacity_hover` and `undo_hover` placed in Group 1 (backgrounds/transparency) rather than their previous scattered positions — both are window-level transparency/interaction values, not component-specific.
- `search_error_text` moved into the Library group (Group 7) — it exclusively styles the library search field error state.
- The `bg_library` Qt property name on `BookDelegate` in `library.py` (lines 1005–1007) was intentionally left unchanged — it is a Python `@Property` identifier, not a theme dict key.

---

## Session Summary — 2026-06-03 Session 4

**Scope:** Strip theme `bg_image` in the no-book and empty-library states — `app.py`, `themes.py`, `library_controller.py`, `theme_manager.py`.

### What was built

Themes with a `bg_image` (Overlook, Winterfell, Pyke, etc.) painted their image over the prompts, carousel, and quote in the no-book and empty-library states. The image is now suppressed in exactly those two states and restored whenever a book is loaded.

- **`get_player_stylesheet(theme_name, suppress_bg_image=False)`** (`themes.py`): when `True`, the `bg_image` is omitted from the `#visual_area` rule entirely.
- **`MainWindow._set_bg_suppressed(suppressed)`** (`app.py`): single authority. Sets `self._bg_suppressed`, calls `setAutoFillBackground(not suppressed)`, and re-applies `content_container`'s stylesheet via `get_player_stylesheet(theme, suppress_bg_image=suppressed)`. Exposed on `UIInterface` as `set_bg_suppressed`.
- **`apply_library_state`** (`library_controller.py`): drives it — `set_bg_suppressed(True)` in the empty branch and the no-book branch (before `show_carousel()`), `set_bg_suppressed(False)` in the has_book branch.
- **`ThemeManager._apply_stylesheets`** reads `getattr(mw, '_bg_suppressed', False)` so a theme change while in a suppressed state does not re-introduce the image.
- `_show_carousel` / `_hide_carousel` no longer touch `carouselActive` or `autoFillBackground` — suppression is fully owned by the state machine. The `carouselActive` QSS rule and property are gone.

### Non-obvious decisions

1. **The image cannot be cancelled by overriding the child widget.** Qt's QSS cascade treats `background-image: none` as "unspecified", so an ancestor rule's `url()` wins on the child per-property even when the child sets `none`. Verified with a red-background diagnostic: the child stylesheet applied (area went red) but the image layered on top of the red. The only reliable kill is to never emit the image — hence the `suppress_bg_image` flag at generation time. Two earlier attempts (renaming the `carouselActive` property; a child instance stylesheet with `background-image: none`) both produced no visible change. Full tried/failed writeup in NOTES.md.
2. **The `QGraphicsBlurEffect` on `visual_area` was a red herring** — suspected of caching a source pixmap, but `blurRadius` is 0 except during panel transitions and the red diagnostic proved repaints propagate normally.
3. **Per-state stripping over hiding image-themes from the pool.** Suppressing the themes themselves would have left a visible gap in the Settings theme pool. Stripping the image per-state keeps every theme selectable.
4. **`setAutoFillBackground(False)` is load-bearing, not cosmetic.** `CoverCarousel` is parented to `content_container` and stacked under `visual_area`. Without `autoFillBackground=False`, `visual_area` paints its own background over the carousel stripe even when the QSS image is suppressed — the stripe is occluded regardless. `False` makes `visual_area` transparent so the stripe shows through. This is why `setAutoFillBackground` lives in `_set_bg_suppressed` rather than in the carousel methods where it originally was: suppression and transparency must always be set together. Separating them would leave a state where the image is gone but the stripe is still hidden.

### Known cosmetic note

In the empty state the stripped background plus the window gradient can read slightly dark behind the quote panel. Accepted as good enough — far better than the overlapping image.

---

## Session Summary — 2026-06-03 Session 3

**Scope:** Carousel slide-in animation; transport button alignment regression fix — `app.py`, `carousel.py`.

### What was built

**Carousel slide-in animation (`app.py`):**

`_show_carousel` now positions the `CoverCarousel` off-screen to the right at `x = CAROUSEL_STRIPE_W` and slides it to `x = 0` over 220ms with an `OutCubic` ease via `QPropertyAnimation` on `b"pos"`. Covers reveal only after 325ms (`_REVEAL_FIRST_DELAY_MS`) so they always appear on the settled stripe, never mid-slide. `_carousel_slide_anim` is stored on `MainWindow` (initialised to `None` in `__init__`) and stopped/cleared in `_hide_carousel` before the widget is torn down.

**Transport button alignment fix (`app.py`):**

The transport button row had regressed since commit `4b55058` (which wrapped the buttons' `QHBoxLayout` in a named `QWidget`). The wrapper widget was shrinking to fit its children (240px) instead of filling the 280px content area, and inter-button spacing had been implicitly zeroed. Fixed by: `setSpacing(10)` on the inner layout (240px buttons + 4 × 10px gaps = 280px, exactly filling the content area) and `setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)` on the wrapper. Also corrected `carousel_holder.setFixedWidth` to use `CAROUSEL_STRIPE_W` (300) instead of the now-stale hardcoded 280.

### Non-obvious decisions

1. **`setSpacing(10)` chosen to fill exactly 280px**: 5 buttons × fixed widths (46+46+56+46+46 = 240px) + 4 gaps × 10px = 280px = content area width (300px window − 10px left margin − 10px right margin). This aligns Prev with `current_time_label`'s left edge and Next with `total_time_label`'s right edge. Any other spacing value leaves a visible offset.

2. **Root cause of the regression**: wrapping a `QHBoxLayout` in a `QWidget` (for naming/visibility) removes style-derived layout defaults — the widget shrinks to content and spacing is no longer guaranteed. Always call `setSpacing(N)` explicitly and set `Expanding` size policy on any named wrapper widget. Documented in CLAUDE.md, GEMINI.md, and NOTES.md.

---

## Session Summary — 2026-06-03 Session 2

**Scope:** Carousel stripe geometry and theming — `app.py`, `carousel.py`, `themes.py`.

### What was built

The cover carousel stripe is now full-width (300px, bleeding to both window edges) with themed fill and 1px border lines at top and bottom.

**Geometry (carousel.py + app.py):**

`CoverCarousel` is now parented to `content_container`, not `visual_area` or `carousel_holder`. Geometry: `setGeometry(0, y, CAROUSEL_STRIPE_W, carousel_h)` where `y = carousel_holder.mapTo(content_container, QPoint(0, 0)).y()`. `stackUnder(self.visual_area)` keeps covers behind the label and button. The previous approach (parented to `visual_area`, offset `x=-10`) did not reach both edges cleanly.

The `visual_area` QSS background (including `bg_image` rules) must be suppressed for the duration of the carousel or it paints over the stripe center. Fixed via a dynamic property: `visual_area.setProperty("carouselActive", True)` + `unpolish/polish`. A corresponding QSS rule in `get_player_stylesheet` (`QWidget#visual_area[carouselActive="true"]`) forces both `background-color: transparent` and `background-image: none`. `setAutoFillBackground(False/True)` is toggled alongside it. Both are restored in `_hide_carousel`.

**Theming (carousel.py + app.py + themes.py):**

Two new theme keys documented in the `themes.py` docstring under `NO-BOOK CAROUSEL`:
- `carousel_bg` → fill color (`_stripe_color`). Fallback: `bg_main` (not `bg_deep` — every theme has `bg_main`; `bg_deep` is unreliable).
- `carousel_stripe` → 1px border line color (`_line_color`). Fallback: auto-derived from `carousel_bg` via lightness shift.

`_auto_stripe_line_color(hex)` in `carousel.py`: shifts HSL lightness by `_LINE_LIGHTNESS_SHIFT` (0.35) — up for dark fills, down for light fills.

`CoverCarousel.__init__` accepts `line_color: str | None`. `_line_color_explicit` is set at construction and never changed — it controls whether `__init__`'s explicit color is used or auto-derive runs. `set_stripe_color(color, line_color=None)` always recomputes `_line_color` (either from the passed value or auto-derived) — the `_line_color_explicit` flag is not consulted here. This is intentional: if `set_stripe_color` also checked `_line_color_explicit`, a theme with an explicit `carousel_stripe` at construction would never be able to switch to a different explicit value when the theme changes. Each call to `set_stripe_color` is self-contained.

**Key constants added to `carousel.py`:**
- `_LINE_LIGHTNESS_SHIFT = 0.35`
- `_STRIPE_LINE_PX = 1`

**Slide-in animation (`app.py`):**

Added in the closing commit of this session (`0973194`, later amended). `_show_carousel` positions the carousel at `x = CAROUSEL_STRIPE_W` (off-screen right) and slides it to `x = 0` over 220ms. `_carousel_slide_anim` stored on `MainWindow`; stopped in `_hide_carousel`. (Full notes moved to Session 3 where it was formally documented.)

### What was debugged mid-session

The initial implementation used `carousel_stripe` as both the fill key and the line-color key — they were the same variable. `carousel_bg` was wired in the docstring but not in the code, so it had no effect. Swapping the wiring (two call sites in `app.py`) fixed the key semantics. The `_line_color_explicit` flag initially also bled into `set_stripe_color`, causing themes to steal each other's line colors on theme rotation — removed from that method.

# Session Summary — 2026-06-03 Session 1 — SVG cover placeholder, stylesheet parse fix, chapter slider flash guard

## What changed

### `app.py` — SVG logo placeholder for no-cover state (commits `b5815a2`, `707e91b`)

`_show_cover_placeholder()` added to `MainWindow`. Intercepts both no-cover exits in `_load_cover_art` (the `else` branch — no cover in DB, and the null-pixmap fallback after load attempt). Recolors `fabulor.svg` via four regex passes (attribute and CSS property forms, `(?!none)` guarded) to the `placeholder_cover` theme color, renders into a `COVER_AREA_HEIGHT * 0.65` square pixmap, and sets it on `cover_art_label`.

- `_showing_placeholder: bool` flag added in `__init__`, cleared at top of `_apply_main_cover`, checked in `_reload_button_icons` to re-render on theme change.
- The early `not file_path` return (no-book state) is untouched — `cover_art_label` stays hidden there.
- `_ASSETS_DIR` module-level constant added alongside `_ICONS_DIR`.

### `icon_utils.py` — consolidated placeholder renderer (commit `f48c0bd`)

`render_logo_placeholder(color, size) -> QPixmap` — canonical single implementation, replaces the duplicate that was in `tag_manager.py`. `render_logo_placeholder_bordered(color, icon_size, canvas_w, canvas_h, offset_y=0) -> QPixmap` added for thumbnail contexts: renders logo centered on a fixed canvas with a 2px border in the same color. `offset_y` allows per-site vertical nudge (used by `FinishedBookThumb` to align with real covers).

### `stats_panel.py` + `tag_manager.py` — themed placeholder in thumbnails (commits `707e91b`, `09bc9bb`)

`BookDayRow`, `FinishedBookThumb`, and `_TagBookThumb` all replaced `fabulor.ico` fallback with `render_logo_placeholder_bordered`. `StatsPanel.on_theme_changed` now resolves the theme via `_resolve_theme()` before reading colors (raw dict from `get_current_theme()` lacks merged keys). `TagManagerWidget.on_theme_changed` made robust to both string and dict input. `FinishedBookThumb.cover_label` gained `setAlignment(Qt.AlignCenter)` (was missing, causing top-left offset for smaller placeholder).

### `book_detail_panel.py` — placeholder in header cover (commits `499b7d3`, `09bc9bb`)

Both `.ico` fallbacks in `load_book` and `_refresh_header_cover` replaced with `render_logo_placeholder_bordered`. Canvas is 80×120 (portrait), icon rendered at 80px and centered. Border drawn on the full canvas.

### `themes.py` — placeholder theme keys + `currentColor` fix (commits `707e91b`, `f48c0bd`, `b32b9b0`)

Three new keys documented in docstring: `placeholder_cover`, `placeholder_stats`, `placeholder_tags` with fallback chains. `currentColor` (unsupported CSS3 keyword) removed from `QPushButton#book_detail_close_btn` border — was causing "Could not parse stylesheet" Qt warnings on every child widget receiving the stats stylesheet. Replaced with `border: none`.

### `theme_manager.py` — chapter slider flash guard (commit `b32b9b0`)

`_do_fade_with_slider_animation` now skips `chapter_progress_slider` when `mw._chapter_ui_active` is `False`. The overlay punch-through re-exposes the slider during the window between `_apply_stylesheets` (repolish overwrites transparent colors) and `_set_chapter_ui_active` reapplication, causing a full-opacity flash.

### `library_controller.py` — status banner scan guard (commit `82e12b7`)

Status banner no longer clears while a scan is running. Previously the completion handler could dismiss the banner before the scan-in-progress state was fully reflected.

### `app.py` + `scanner.py` + `library_controller.py` — multi-select folder removal, targeted rescan (commit `7efb644`)

Folder removal UI gained multi-select. Rescan targets only the re-added or modified locations rather than the full library.

### `assets/fabulor.svg` — viewport adjustment (commit `222dc9c`)

SVG viewport and path data updated for better centering of the logo artwork within the 250×250 viewBox.

---

## Non-obvious decisions

1. **`_resolve_theme` in `on_theme_changed`**: `get_current_theme()` returns a raw unresolved dict — it does not merge against the base theme. Any `on_theme_changed` handler that reads merged keys (like `library_narrator`) must call `_resolve_theme()` itself. `_resolve_theme` is idempotent on already-resolved dicts.

2. **`render_logo_placeholder_bordered` canvas vs icon size**: the border is drawn on the full canvas (`canvas_w × canvas_h`), not on the icon. The icon is rendered at `icon_size` and centered. This means the visual margin between icon and border is the SVG's own internal padding plus `(canvas - icon) / 2`.

3. **`offset_y` on `FinishedBookThumb`**: real covers use `KeepAspectRatioByExpanding` + crop and land at y=0 naturally. The placeholder's centered position was 1px higher than real covers in the `FinishedScrollRow` context. `offset_y=1` corrects this without touching the other sites.

4. **`currentColor` in QSS**: Qt QSS does not support the CSS3 `currentColor` keyword. It silently fails to parse the entire stylesheet block and logs "Could not parse stylesheet" on every widget that inherits it. The warning appeared on QPushButton, BookDetailPanel, CoverPanel, MainWindow, QListView — all children of panels styled with the stats stylesheet.

---

# Session Summary — 2026-06-02 Session 2 — State machine fixes, scan-active disabling, no-audiobooks state

## What changed

### `library_controller.py` + `app.py` — `apply_library_state` defensive guard (commit `645f460`)

The empty branch now opens with `self.ui.set_visible(False)` before any other call. This overrides the `set_visible(state["has_book"])` that ran at the top of `apply_library_state` — a defensive guard ensuring player chrome never coexists with the empty state even if `has_book` is still `True` at the moment the branch fires (e.g. book not yet unloaded).

### `library_controller.py` — `_on_remove_folder_clicked`: `no_folders_left` check (commit `645f460`)

Book unloading on folder removal previously only fired when `current_file.startswith(path_p)` — i.e. the active book was inside the removed folder. This missed the case where all folders are removed: the active book is now unreachable regardless of which folder it was in, but the path check still fails if it was in a different folder already removed in a prior step. Added:

```python
no_folders_left = len(self.db.get_scan_locations()) == 0
if current_file and (current_file.startswith(path_p) or no_folders_left):
    self.app.on_book_removed()
```

Unload fires before `_check_library_status` / `apply_current_state` so state is computed with `has_book=False`.

### `app.py` — `_on_book_removed` calls `apply_current_state()` (commit `645f460`)

Added `self.library_controller.apply_current_state()` at the end of `_on_book_removed`. Fixes the book-detail **trash button** path (`_on_book_detail_removed` → `_on_book_removed`) which previously left stale player chrome visible — it refreshed library/tags/stats panels but never re-ran the chrome gate. The folder-removal path was already gated via `_check_library_status`; the extra call there is redundant-but-harmless.

### `app.py` + `library_controller.py` + `ui/panels.py` — Scan-active button disabling (commit `645f460`)

Add/Remove/Rescan buttons in the Library panel are now non-interactive during an active scan. Visible but `setEnabled(False)`.

- `_set_scan_buttons_enabled(enabled)` helper on `MainWindow` controls `add_folder_btn`, `remove_folder_btn`, `refresh_library_btn`.
- `UIInterface.set_scan_buttons_enabled(v)` passthrough added.
- Disabled in `handle_background_tasks` immediately before `scanner.start()`.
- Re-enabled in `_on_scan_finished` and `_on_cancel_scan_clicked` (cancel path re-enables immediately; `_on_scan_finished` fires when the worker thread exits, so both cover the lifecycle).
- `_start_library_entry` in `panels.py` syncs button state on panel open via `scanner.is_running()` — if a scan is already running when the Library panel slides in, the buttons open already disabled.

### `library_controller.py` + `db.py` + `app.py` — No-audiobooks state + Library button visibility (commit `42e5f7d`)

**Problem:** A library path configured but containing zero legitimate audiobooks (text files, wrong directory, unmounted drive) fell into the no-book state — showing the carousel and "Go to Library" even though the Library panel has nothing to show. Root cause: `compute_library_state` used `get_book_count()` which counts all DB rows including `is_deleted=1` and `is_excluded=1` books, so soft-deleted books from a prior scan kept `has_indexed_books=True` even after all real books were removed.

**Fix — `db.py`:** New `get_visible_book_count()` queries `WHERE is_deleted = 0 AND is_excluded = 0`. `compute_library_state` now uses this.

**Fix — `apply_library_state`:** Expanded the empty-like condition to `mode == "empty" or not has_indexed_books` (the `or` clause is currently redundant since `compute_library_state` already collapses no-books into `mode="empty"`, but kept as a future guard). Within the branch, prompt text is discriminated by `has_locations`:
- `has_locations=False` → `"No library folders."`
- `has_locations=True` → `"No audiobooks in the folders added."`

`UIInterface.set_prompt_text(text)` passthrough added.

**Fix — Library button visibility:** `library_trigger_btn` and `library_separator` (10px `QWidget` spacer immediately below it in `sidebar_layout`) are toggled together via `UIInterface.set_library_btn_visible(v)`. Hidden in the empty-like branch, visible in the else branch. The `addSpacing(10)` that previously separated the Library button from the rest of the sidebar was converted to a named `QWidget` (`self.library_separator`) so it can be toggled.

**Fix — `_rotate_quote`:** Removed the `if not self.db.get_scan_locations()` guard that was suppressing quotes when library folders exist. `_rotate_quote` is only ever called from the empty-like branch, so the guard was redundant for the no-paths case and actively wrong for the no-audiobooks case (where `has_locations=True`). Quotes now rotate in both sub-cases.

---

# Session Summary — 2026-06-02 Session 1 — Empty/no-book state UX + cover carousel

## What changed

### `app.py` — Empty and no-book state UI gates (commit `4b55058` + follow-ups)

**Problem:** Transport controls, progress fill, Sleep/Playback sidebar buttons, and volume wheel were all active/visible with no book loaded, offering inert affordances.

**Changes:**
- `_set_interface_visible(visible)` extended: hides `transport_controls` (QWidget container wrapping the playback button row), suppresses the progress slider fill via `ClickSlider._suppress_fill = not visible` + `setEnabled(visible)`, hides `sleep_trigger_btn` and `speed_trigger_btn`. All are restored when a book loads.
- `wheelEvent` `visual_area` branch now guards `if not self.current_file: return` (previously used `is None`, which never fires since `current_file` initialises to `""`, not `None`).
- `scan_info_label` ("Loading all your books…") removed entirely — widget, layout entry, and all references.
- `KEY_Q` in `keyPressEvent`: rotates the quote when `not self.current_file and self.quote_section.isVisible()`. Testing aid only — `# TODO: remove before release`.

### `app.py` + `themes.py` — Status banner fixes (commits `05b112e`, `b743c96`)

- Removed `border-right: 1px solid {accent}` from `#status_banner` QSS — was painting a 1px accent-colored vertical sliver on the right edge of the banner.
- `#status_banner QPushButton` rule added: transparent background, theme text color, accent hover state. Previously unstyled (OS default appearance).
- `#status_banner` background changed from `rgba(bg_main, panel_opacity_hover)` to `transparent` — makes the banner area track the main window's background through theme transitions instead of snapping independently.
- `_update_status_banner_ui` `raise_()` calls guarded: the banner is not raised while `_fade_overlay` is visible. Root cause of the snap: scan progress updates were firing `status_banner.raise_()` repeatedly, lifting the banner above the fade overlay mid-fade and exposing the newly-applied QSS colors before the fade completed.

### `app.py` + `library_controller.py` — Empty-state layout (commits `4b55058`, `6829dbe`, `c0e3fed`)

**Empty-state layout redesign** — three vertical sections in `visual_layout`:

1. **Scan section** (`self.scan_section`, stretch=1): `QWidget` container with `addSpacing(50)` before the prompt label and `addSpacing(80)` between label and button. Label lands ~50px from section top; button ~150px. `addStretch()` at the bottom. No `setAlignment` — spacers handle positioning.
2. **Quote section** (`self.quote_section`, `setFixedHeight(240)`): `quote_label` inside with `Qt.AlignBottom | Qt.AlignHCenter` — quotes stay bottom-anchored within the fixed box and expand upward as they rotate.
3. Status banner is a floating `QWidget(self)` overlay, not a layout item.

`_update_idle_prompts_ui(visible)` now toggles `scan_section.setVisible(visible)` (previously toggled the three widgets individually). `_update_quote_ui` now toggles `quote_section.show/hide` rather than `quote_label` directly.

**Stale banner clear:** Empty branch of `apply_library_state` now calls `update_status("", show_banner=False, show_cancel=False)` instead of `update_status(None, show_banner=True, show_cancel=None)` — previously left a stale "Library updated: N books." visible after all folders were removed.

**Debug buttons removed** (commit `29a99d6`): `next_quote_btn` and `temp_settings_btn` removed from `_build_status_banner`, layout, and signal connections. `KEY_Q` is the replacement testing shortcut for quote rotation.

**Label style parity** (commit `29a99d6`): "No book selected." and "No library folders." both use `font-weight: bold; font-size: 16px;`. The style is applied in `_update_metadata_ui` (used by the controller path) and directly in `_load_cover_art` (the no-file path).

### `app.py` + `db.py` + `ui/carousel.py` — Ambient cover carousel (commit `4a73f44`)

New ambient cover carousel for the no-book state. **Issues are pending from visual inspection — commit is tagged `wip`.**

**`ui/carousel.py` — `CoverCarousel(QWidget)`:**
- Fixed 280×150px, no mouse interaction.
- Covers bottom-aligned within the 150px container, scroll left at `scroll_speed` px/s (default 15, was initially 30).
- 33ms QTimer (`~30 fps`), sub-pixel `_offset` accumulation, seamless loop reset when `_offset >= _strip_w`.
- Static mode (≤ 3 covers): no timer, covers centered horizontally. Threshold is count-based (`n <= 3`) — the width formula (`3 * 96 = 288 > 280`) doesn't fit in the viewport, so centering is the right call.
- `stop()` method stops the timer safely; no-op in static mode (timer is `None`).

**`db.py` — `get_all_cover_paths()`:**
Returns `cover_path` for all `is_deleted=0 AND is_excluded=0` books with a non-null, non-empty `cover_path`. Uses `books.cover_path` (scanner thumbnails) — active covers from `book_covers` are not consulted.

**`app.py` — `_build_carousel_covers()`, `_show_carousel()`, `_hide_carousel()`:**
- Shuffles all cover paths, caps at 100, Pillow header-only reads classify by aspect ratio (portrait ≥ 1.4 : landscape/square). Portrait pool preferred (≥ 8 portraits → 140px height); square fallback (≥ 4 squares → 92px); hybrid fallback (≥ 4 portraits → 140px). Fewer than 4 → no carousel.
- Covers scaled-and-cropped to exactly (92, cover_h) via `KeepAspectRatioByExpanding` + `copy()` center crop.
- `_show_carousel()`: calls `_hide_carousel()` first (safe teardown of prior instance), builds `CoverCarousel`, wraps it in a `_carousel_container` with `addSpacing(30)` above and below, inserts at index 0 of `visual_layout`.
- `_hide_carousel()`: stops timer, removes container from layout, `deleteLater()`.
- `UIInterface.show_carousel()` / `hide_carousel()` delegate to the above.

**`library_controller.py` — wiring:**
- `apply_library_state` no-book branch (else, not has_book) → `show_carousel()` after metadata update.
- `apply_library_state` player branch (has_book) and empty branch → `hide_carousel()`.
- Carousel reshuffles on each no-book entry.

**Layout approach: FALLBACK.** `metadata_label` is shared with the player state (used for "Author - Title" when no cover exists at lines ~2338, ~2367). Carousel is inserted as an independent `visual_layout` item at index 0, not grouped with the label.

---

# Session Summary — 2026-06-01 Session 3 — App icon update (commit `64768d2`)

Single `chore` commit. No logic changes.

---

# Session Summary — 2026-06-01 Session 2 — Sticky chapter hints + chapter snap-back fix

## What changed

### `app.py` + `config.py` + `settings_controller.py` — Chapter hints Sticky/Transient/Off mode (commit `6023a08`)

**Previous state:** Chapter hint labels (showing the prev/next chapter title on button hover) had a binary On/Off toggle. On click, `_clear_preview()` was always called unconditionally in `handle_prev`/`handle_next`.

**Change:** Expanded to three modes persisted via `config.get_chapter_hints_mode()` / `config.set_chapter_hints_mode()` (QSettings key `chapter_hints_mode`, default `"Sticky"`). Old key `chapter_hints_enabled` is superseded.

- **Sticky** — preview label persists after a nav button click for as long as the mouse stays on the button. `_update_chapter_label_from_index` refreshes the preview text (to the new prev/next title) after every `chapter_changed` signal when a nav button is `underMouse()`.
- **Transient** — `_clear_preview()` is called on click, fading the label out immediately (previous behavior).
- **Off** — preview never shown; `_clear_preview()` called on mode switch.

`hints_mode_changed` signal type changed from `Signal(bool)` to `Signal(str)`. `set_hints_selection` in `VisualsInterface` updated to match the three-button layout (`["Sticky", "Transient", "Off"]`). `settings_controller._update_hints_mode` and `_update_hints_visuals` updated to pass/read the string mode.

Also fixed: `_on_prev_hover` / `_on_next_hover` changed guard from `get_chapter_hints_enabled()` to `get_chapter_hints_mode() != "Off"`.

---

### `player.py` — `_on_chapter_change` fully suppressed; `_on_time_pos_change` drives chapter tracking universally

**Root cause diagnosed:** `_on_time_pos_change` and `_on_chapter_change` were both emitting `chapter_changed` for embedded M4B books. The `_is_seeking` guard on `_on_chapter_change` was structurally insufficient: `_on_time_pos_change` clears `_is_seeking` when the position settles within 1.0s of `_seek_target`. By the time mpv fires the chapter property observer (`_on_chapter_change`), `_is_seeking` is already `False` — the guard cannot filter the stale mpv native chapter value.

**Symptom:** Clicking Prev or Next while paused caused the chapter label to flash the correct chapter briefly then snap back to the previous one. When playing, continuous `time_pos` events re-emitted the correct chapter within milliseconds and masked the snap-back. When paused, mpv fires no further events after settling, so the stale `_on_chapter_change` value was permanent.

**Fix:** `_on_chapter_change` now contains only `return`. `_on_time_pos_change` handles all three book types:
- **VT** (`_virtual_timeline is not None and _chapter_list`): walks `_chapter_list` against global position, emits via `_last_vt_chapter`.
- **CUE** (`_chapter_list is not None, _virtual_timeline is None`): `self.chapter_list` returns `_chapter_list`; same walk path.
- **Embedded M4B** (`_chapter_list is None, _virtual_timeline is None`): `self.chapter_list` returns `self.instance.chapter_list` (live from mpv); walks it, emits via `_last_nonvt_chapter`.

Also fixed: VT `next_chapter()` was missing `_CHAPTER_BOUNDARY_EPSILON` on the seek target (non-VT branch already had it). Added epsilon to match.

Also removed: stale `print()` debug statement in VT `next_chapter()`.

---

## Invariant added

**DO NOT restore any emit in `_on_chapter_change`.** It is fully suppressed. `_on_time_pos_change` is the sole driver of `chapter_changed` for all book types. The `_is_seeking` guard that previously lived on `_on_chapter_change` was structurally broken — `_on_time_pos_change` always clears `_is_seeking` first.

---

## Commits

- `6023a08` — feat: implement sticky chapter preview label on navigation when hovered
- `0e0196b` — feat: add quotes
- `fc85c5f` — fix: suppress async mpv chapter snap-back on navigation

---

# Session Summary — 2026-06-01 Session 1 — Cover area height fix + library state refactor

## What changed

### `app.py` — Pin cover art label to fixed height (`COVER_AREA_HEIGHT`)

**Problem:** `cover_art_label` had an Expanding vertical size policy and no maximum height. With `visual_area` added to `content_layout` with stretch factor 1, the label claimed all remaining vertical space. `_update_cover_art_scaling()` read `cover_art_label.height()` to scale the pixmap — which returned the layout-allocated height, not a stable design value. Two bugs:

1. Unusual-aspect-ratio covers (tall or landscape) caused the label to report an inflated height, producing an oversized pixmap; in the fixed-size window the transport controls below got squeezed out of view.
2. After returning from the empty/no-library state, the deferred `_update_cover_art_scaling` fired before the layout had settled, reading a stale height and reproducing the broken layout. Only a restart restored correct layout.

**Fix:**
- Added module-level constant `COVER_AREA_HEIGHT = 280` (calibrated empirically from the fixed-size window budget: 564px − title bar 32 − progress slider 24 = 508 content height; minus margins, spacing, and six fixed-height rows below `visual_area` = 290 theoretical, tuned to 280).
- `_build_cover_art`: added `setFixedHeight(COVER_AREA_HEIGHT)`, changed alignment from `AlignBottom | AlignHCenter` to `AlignCenter` so letterboxed covers center vertically in the fixed box.
- `_update_cover_art_scaling`: changed `target_h` from `self.cover_art_label.height()` to `COVER_AREA_HEIGHT`. `target_w` still reads `.width()`; the fit/stretch/crop/top scaling logic is untouched.

**Invariant added to CLAUDE.md:** Do not revert `target_h` to reading the live allocated height. The constant decouples scaling from transient layout state.

---

### `app.py` + `library_controller.py` — Restore player chrome after empty → load book path

**Problem:** `apply_library_state()` is the sole gate for player chrome visibility — it calls `set_visible(state["has_book"])` and manages `go_to_library_btn`. In the empty → add folder → scan → pick book path:

1. Empty state: `apply_library_state(mode="empty", has_book=False)` → chrome hidden.
2. Scan finishes: `apply_library_state(mode="ready", has_book=False)` → `go_to_library_btn.show()` fires. This state is sticky.
3. User picks a book: `_on_book_selected_from_library` sets `current_file`, calls `_load_cover_art` and `player.load_book` — but never re-runs the chrome gate. `_on_file_ready` doesn't either.

Result: cover loaded correctly (from the height fix), but chrome stayed hidden and `go_to_library_btn` remained visible until app restart.

**Fix (initial):** Added `apply_library_state(compute_library_state())` inline in the deferred `singleShot(0)` lambda in `_on_book_selected_from_library`, after `_load_cover_art` and `player.load_book`. (`_check_library_status()` was not used because it calls `handle_background_tasks`, which would fire a scan on every book pick.)

**Refactor:** Extracted the compute-and-apply pair into `apply_current_state()` on `LibraryController`, and rewrote `_check_library_status` to delegate to it:

```python
def apply_current_state(self):
    state = self.compute_library_state()
    self.apply_library_state(state)
    return state  # returned so _check_library_status can feed handle_background_tasks without recomputing

def _check_library_status(self, manual=False, force_refresh=False):
    state = self.apply_current_state()
    self.handle_background_tasks(state, manual, force_refresh)
```

The book-selection path now calls `self.library_controller.apply_current_state()` — one clean call, no inline replication. The compute+apply pairing lives in exactly one place.

**Caller audit:** Three remaining `_check_library_status` call sites all legitimately want a scan trigger or fire during an active scan where the trigger is a no-op. No callers need migration. `_on_scan_finished` does not call `_check_library_status` at all.

**Invariant added to CLAUDE.md:** Never replicate `apply_library_state(compute_library_state())` at a call site — route through `apply_current_state()`.

---

## Commits

- `12047a2` — wip: stabilize cover art height to prevent layout shifts
- `3899b8f` — wip: reveal player chrome when switching books in library
- `e12ce5b` — refactor: extract apply_current_state() from _check_library_status + fix cover area height
- (docs commit — CLAUDE.md, NOTES.md, SESSION.md)

---

# Session Summary — 2026-05-31 Session 3 — Tag refresh fix + theme rotation tuning

## What changed

### `app.py` — Refresh library and tags panel on book tag changes

**Problem:** Removing a tag from a book in `BookDetailPanel` did not update the library panel's `#tag` filter view or the Tags panel's current tag book list until the panels were re-opened.

**Root cause:** `book_detail_panel.tags_changed` connected directly to `stats_panel._on_tag_changed`, which refreshes the tag manager list view and rebuilds chips — but never touched the library panel or the `TagManagerWidget`'s current tag book list.

**Fix:** Replaced the direct connection with `_on_book_tags_changed`:
- Calls `stats_panel._on_tag_changed()` (existing behaviour)
- Calls `library_panel.refresh()` when the current search starts with `#` — re-applies the filter against the updated DB, dropping the now-untagged book from the results
- Calls `tags_panel.refresh_books()` — re-opens the current tag's book list in place (not `refresh()`, which would reset to the tag list view)

### `theme_manager.py` — Reduce weight exponent from 1.5 to 1.0

Simulated 10,000 rotations across 57 themes at three exponents. See NOTES.md for full table.

The original exponent of 1.5 produced a 3.4× min/max ratio (Hear Me Roar at 0.9%, Pyke at 3.0%). Dropping to 1.0 brings the ratio to 2.2× (Hear Me Roar at 1.2%, Pyke at 2.5%) while preserving perceptual ordering. Outlier themes reach parity without the weight curve inverting rankings the way 0.5 does.

---

# Session Summary — 2026-05-31 Session 2 — Sleep timer session integration + stats rounding

## What changed

### `app.py` + `sleep_timer.py` — Session recorder wired to sleep timer and chapter list

**Problems:**
1. Starting playback by selecting a sleep timer preset did not open a session.
2. When the sleep timer fired and paused playback, the session stayed open indefinitely — `session_recorder.pause()` was never called, so the 3-minute close timer never started.
3. Right-clicking a chapter in the chapter list forced play but did not open or resume a session.

**Root cause for (1):** `_on_sleep_timer_started` checked `not self.player.pause` before deciding whether to open a session. `player.pause` is a cached property updated asynchronously by mpv's observer callback — it still returned `True` at the point the signal fired synchronously, even though `set_sleep_timer` had already set `instance.pause = False`. The fix: drop the pause check entirely; since `set_sleep_timer` unconditionally unpauses before emitting `timer_started`, `current_file` is the only guard needed.

**Fix for (2):** Added `timer_expired = Signal()` to `SleepTimerPanel`. Emitted at each of the three natural-expiry points in `update_timer_state` (timed countdown, end-of-chapter, end-of-book) — but not from `disable_sleep_timer()`, so user-cancellation does not trigger it. Connected to `_on_sleep_timer_expired` in `app.py`, which mirrors the regular pause-button path: saves timestamp, saves progress, updates library playing state, calls `session_recorder.pause()`.

**Fix for (3):** `_on_chapter_list_selected` now calls `session_recorder.open()` or `resume()` when `force_play=True`.

### `sleep_timer.py` — Fire condition uses raw float, not floored int

`update_timer_state` computed `remaining_seconds = max(0, int(self._sleep_timer_end_time - current_time))` and fired when `remaining_seconds <= 0`. The `int()` floor meant the timer fired up to ~1 second early — a 2-minute preset would record ~119s instead of 120s, showing as "1m" in stats. Fixed by splitting: `remaining_raw` for the fire condition (`remaining_raw <= 0`), `int(remaining_raw)` for the display countdown.

### `stats_panel.py` — `_format_duration` rounds instead of floors

`_format_duration` used `int(seconds // 60)` for the minutes component (floor), while the Timeline heatmap used `round(seconds / 60)`. This caused consistent off-by-one disagreement for any session ending in 30–59 seconds past a minute boundary (e.g. 1:45 → "1m" in Day/Week/Month, "2m" in Timeline). Changed to `round((seconds % 3600) / 60)` with a carry guard for the `m == 60` edge case (e.g. 3599s → "1h 0m" not "1h 60m").

---

# Session Summary — 2026-05-31 Session 1 — Weighted theme rotation + recent exclusion window

## What changed

### `theme_manager.py` — Perceptual-distance weighted theme selection

**Problem:** Uniform random selection from the rotation pool could pick perceptually similar themes back-to-back, and could immediately re-select the theme that just played.

**Fix:** `_do_rotate` now uses `random.choices` with inverse-distance weights rather than `random.choice`.

**`_theme_distance(name_a, name_b)`** — module-level function. Computes perceptual distance (0.0–1.0) between two themes using four components of their `bg_main` and `accent` colors: bg hue delta (45%), bg lightness delta (25%), bg saturation delta (15%), accent hue delta (15%). `colorsys` is stdlib; imported inside the function. `THEMES` is already at module scope.

**Selection pipeline in `_do_rotate` (5 steps):**

1. **Recent exclusion** — the last `min(pool // 4, 8)` named themes (from `self._recent_themes`) are removed from the candidate set. Pool size is measured before any exclusion.
2. **Relax recent exclusion** — if removal would drop the candidate count below `_MIN_POOL = 4`, oldest-first re-admission from `_recent_themes` until the count recovers. Prevents stalling when the pool is small.
3. **Distance exclusion** — themes with distance > `_EXCLUSION_THRESHOLD = 0.5` from the current theme are filtered out, but only when the post-recent pool exceeds `_MIN_POOL`. If filtering would drop below `_MIN_POOL`, the filter is skipped.
4. **Inverse-distance weights** — each candidate is weighted `1 / (distance ** 1.5 + ε)`. Closer themes are more likely; the power curve sharpens the preference without fully excluding near neighbors.
5. **Cover-theme slot** — when `None` (cover art theme) is in the pool, it receives the median weight of the named candidates, keeping it always eligible but not preferentially selected.

**Recent history — `self._recent_themes`** — `deque(maxlen=10)` initialized in `__init__` after `_current_theme_name` is set. Appended after every rotation (named picks only, not cover). Manual right-click activation (`_on_theme_right_clicked`) also appends, so manual jumps participate in the exclusion window.

### `app.py` / `theme_manager.py` — Rotation key debounce (2s cooldown)

The `T` key shortcut for manual theme rotation now enforces a 2-second cooldown timer to prevent rapid repeated fires from saturating the rotation history with a single spammed theme.

---

# Session Summary — 2026-05-30 Session 2 — Slider color animation during theme fade

## What changed

### `theme_manager.py` — Two-state fade handling; slider color animation

**Problem:** `ClickSlider` widgets (the progress bar and chapter slider) repaint immediately when QSS applies during a theme change. This caused a ghost: the fade overlay showed old slider colors dissolving over sliders already displaying new colors.

**Fix:** `_on_theme_changed` now branches at the `fade_ms > 0` block:

- **Themes tab visible** (`themes_tab_active`): full overlay grab including sliders, no color animation — original behavior, unchanged. The user is deliberately previewing themes, nothing is moving.
- **All other fades** (auto-rotation, cover-art theme): delegates to `_do_fade_with_slider_animation`.

`_do_fade_with_slider_animation`: reads each slider's start colors (`bg_color`, `fill_color`, `notch_color`) before the grab, punches their rects out of the overlay mask (sliders paint their full rect so no background is exposed), starts the overlay fade, applies the new stylesheet, then on the next event loop tick reads the end colors (set by qproperty repolish), resets sliders to start, and animates them old→new via `QPropertyAnimation` over `fade_ms - 16ms`. `QEasingCurve.OutCubic`.

`_get_slider_anims(slider)`: lazily creates and caches three `QPropertyAnimation` instances per slider (keyed by `id(slider)`), parented to `ThemeManager`.

`abort_theme_fade` and `snap_theme_forward` both stop running slider animations; snap also drives each to its end value so the final theme color lands immediately.

`QColor`, `QEasingCurve`, `Property` added to imports.

### `app.py` — Temporary `t` shortcut for testing theme rotation

`keyPressEvent` now fires `_rotate_theme` after a 5-second delay when `T` is pressed. Exists to avoid waiting the full rotation interval during development; remove when no longer needed.

---

## Theme fade label ghosting — approaches tried and rejected

The session continued with attempts to extend the same treatment to the five time/chapter labels (`current_time_label`, `total_time_label`, `chap_elapsed_label`, `chap_duration_label`, `current_chapter_label`). All failed. The root cause was the same for every approach: **the overlay cross-fades by opacity-blending two full renders; any region treated differently from the rest of the window becomes a visible rectangle or flash**.

Sliders work because they are opaque and paint their full rect — the punch-hole exposes the slider itself, not the window background. Labels are transparent — any hole exposes the freshly-themed window background, which differs from the surrounding (still-fading) overlay.

### Failed approaches (in order)

1. **Mask punch-out for labels (no animation)** — labels have transparent backgrounds; the holes exposed the new theme bg instantly while the overlay around them still showed the old bg. Visible rectangle flash.

2. **Mirror QLabel on top of overlay** — a new QLabel was placed above the overlay at each label's geometry, copying text/font/alignment and animating color. Two problems: (a) the mirror renders on top of the real label = text doubles and looks bold, (b) `ScrollingLabel` scroll position is not tracked so the chapter label mirror was misaligned.

3. **Paint-over screenshot** — filled each label's rect in the overlay pixmap with the background color sampled just above it (row spacing), removing stale text from the overlay. The fill color was the OLD bg; by the time the overlay faded, the live label beneath had the NEW bg = a rectangle blink as the old-bg patch dissolved over the new-bg label.

4. **Deferred background repaint** — called `_apply_stylesheets(..., defer_base=True)` to hold the main-window background at the old color during the fade, so punch-holes would expose a matching bg. Side effect: every other component that depends on the base stylesheet (title bar, content_container) also got its bg deferred. Result: two different themes simultaneously; the background snapped at the end of the fade.

5. **Two-speed fade (fast overlay for label band)** — a second overlay covered the label band only, fading at 150ms while the main overlay faded at 750ms. The band reached the new theme ~600ms before its surroundings, making it visibly brighter for that window. Visible rectangle.

6. **Per-widget mini-overlays** — each label and slider got its own QLabel overlay showing a screenshot slice, fading in sync with the main overlay. Too many independent opacities; the whole player area animated as disconnected rectangles.

### Resolution: freeze-text

After the six failed overlay/rendering approaches, the fix came from attacking the ghost at its source rather than the overlay.

**`FreezableLabel(QLabel)`** added to `controls.py`. Exposes `freeze()`/`unfreeze()`; `setText` is a no-op while frozen. `ScrollingLabel` now inherits `FreezableLabel`. The four time labels in `app.py` were changed from `QLabel` to `FreezableLabel` at construction.

**`ThemeManager._do_fade_with_slider_animation`** freezes all five labels before `mw.grab()` (so the screenshot text and live label are identical at grab time), then unfreezes in `_on_fade_finished`/`abort_theme_fade`/`snap_theme_forward`. The chapter label is force-refreshed on unfreeze using the `chapter_list` + `time_pos` epsilon walk (same invariant as all other chapter display code) — so a chapter change during the freeze doesn't leave it stuck.

**Why it works:** the ghost only occurs when the live label's value changes under the frozen overlay. With text pinned, the overlay and the live label are always identical — nothing can diverge.

**Tradeoffs accepted:**
- Time labels pause for the 750ms fade duration. On normal playback this is a sub-second freeze. Worth it vs. the ghost on every seek-during-fade.
- The chapter label scrolls, pauses, then resumes — scroll position resets. Negligible.
- If a chapter changes during a fade the chapter label shows the old name for up to 750ms, then force-refreshes. Rare and brief.

**Why 750ms freeze feels more frozen than the discarded 1250ms+color-animation approach:** the color animation provided motion that masked the text freeze. Without it the labels are completely static, which the eye reads more clearly as "stuck" even though the actual duration is shorter. Accepted — the freeze is brief and the alternative is a ghost on every theme change.

---

# Session Summary — 2026-05-30 Session 1 — Font, inline confirmations, session crash recovery, position tracking fix

## What changed

### `main.py` — Open Sans Condensed set as app font

`OpenSans-CondensedRegular.ttf` added to `src/fabulor/assets/fonts/`. Loaded at startup via `QFontDatabase.addApplicationFont`. The TTF registers two family names; the condensed family is selected explicitly by name (`"Open Sans Condensed"`). Size fixed at 11pt to match the system default that all existing QSS pixel sizes were calibrated against — the font's own default is 12pt, which made everything 1pt larger.

### `themes.py` — No font-size changes needed

All affected widgets (chapter time labels, playback buttons, sleep grid buttons, library Add/Remove/Rescan, tag management button, delete/reset stat buttons) had no explicit `font-size` in their QSS and were inheriting the app font. The 11pt fix in `main.py` resolved all of them without touching stylesheets.

### `book_detail_panel.py`, `stats_panel.py` — System dialogs replaced with inline confirmations

Two `QMessageBox.question` dialogs replaced with the same click-to-confirm pattern already used by the trash button:

- **History tab → "Delete listening history"**: first click shows a `_delete_history_confirm_label` above the button (`book_detail_confirm_remove` style, `setFixedHeight(28)`); clicking the label confirms; auto-dismisses after 7 seconds. State tracked by `_delete_history_cancel_timer`.
- **Options tab → "Reset all stats"**: same pattern with `_reset_confirm_label` and `_reset_cancel_timer`. Button and confirm label pushed to the bottom of the tab via `addStretch()` before them, so the layout doesn't shift on show/hide.

### `session_recorder.py` — Crash recovery via checkpoint file

`SessionRecorder` now writes a JSON checkpoint every 30 seconds while a session is active, and recovers it on startup if the previous session ended uncleanly (crash, force-kill).

**Checkpoint location:** `<db_dir>/session_checkpoint.json`

**Write:** `_write_checkpoint` snapshots current session state (book, positions, accumulated listened seconds including the in-progress segment) without modifying live state. All I/O is `try/except OSError`. Fired by `_checkpoint_timer` (30s interval), started in `open()`, stopped in `close()`.

**Recovery:** `_recover_checkpoint` runs once in `__init__`. If the file exists and `listened_seconds >= 60`, it writes a session record to the DB on a daemon thread (same shape as `close()`'s `_write()`). The checkpoint is always deleted after recovery whether it succeeds or fails (`missing_ok=True`). If `listened_seconds < 60`, the file is discarded without writing.

**Clean close:** the checkpoint is deleted inside `_write()` after `session_written.emit()`, so only crashed/killed sessions leave a recoverable file behind.

`segment_start` is written as null when paused — the in-progress segment since the last checkpoint is considered lost on recovery (conservative, avoids complexity).

### `session_recorder.py` — `position_end` bug fixes

Two related fixes:

1. **`close()`**: `pos_end` now uses `max(live_pos, self._session_furthest_position or pos_start or 0.0, pos_start or 0.0)` so `position_end` is never less than `furthest_position` when mpv returns 0.0 at shutdown.
2. **`_recover_checkpoint()`**: `position_end` now uses `furthest if furthest is not None else position_start` instead of `position_start` unconditionally.

### `session_recorder.py` — `_session_furthest_position` never advanced (root cause + fix)

**Symptom:** Sessions closed with `position_start == position_end == 0.0` regardless of actual playback. Listened time accumulated correctly (wall-clock based); position tracking did not.

**Root cause:** `open()` performed incomplete initialization. It reset session position and listened-time state but left `_post_seek_pending_position` and `_seek_credit_timer` dangling from prior activity. The second condition in `update_furthest_position` checks `_post_seek_pending_position is None`; if a forward-seek's 15-second credit window was still live when `open()` ran (no intervening `close()` to clear it), every 200ms tick was short-circuited and `_session_furthest_position` never advanced past its open-time value (0.0 for a fresh book).

**Fix:** `open()` now resets seek-credit state explicitly, mirroring what `close()` already does:

```python
self._post_seek_pending_position = None
self._seek_credit_timer.stop()
```

Confirmed via isolation test: `SessionRecorder` exercised directly (no GUI), with a forward seek leaving pending non-None, then `open()` called without `close()` — before fix, furthest stuck; after fix, furthest advances correctly. Normal playback, backward seeks, and the legitimate forward-seek credit window all verified intact.

---

# Session Summary — 2026-05-29 Session 4 — Undo animation refactor + long skip / wheel undo

## What changed

### `app.py` — undo animation machinery replaced with single persistent slot

The previous implementation connected and disconnected `undo_anim.finished` to different slots at runtime (`_on_undo_slide_in_done` for slide-in, `undo_overlay.hide` for slide-out), tracked by two boolean flags (`_undo_slide_in_connected`, `_undo_slide_out_connected`). A missed disconnect or wrong flag state could leave a dangling or duplicate connection.

**Fix:** `undo_anim.finished` is now connected exactly once in `__init__` to a single dispatcher `_on_undo_anim_finished`. Direction is tracked by a single `_undo_sliding_in: bool | None` flag (None = not animating, True = sliding in, False = sliding out).

```python
def _on_undo_anim_finished(self):
    """Single dispatcher for undo_anim.finished. Replaces manual connect/disconnect."""
    if self._undo_sliding_in is True:
        self._undo_sliding_in = None
        self._on_undo_slide_in_done()
    elif self._undo_sliding_in is False:
        self._undo_sliding_in = None
        self.undo_overlay.hide()
```

`_trigger_undo` and `_hide_undo_banner` now set `_undo_sliding_in` before `undo_anim.start()` instead of connecting/disconnecting. Both call `undo_anim.stop()` followed by `_undo_sliding_in = None` before reconfiguring the animation — the stop fires `finished` with `_undo_sliding_in = None`, which the dispatcher ignores.

`_on_undo_slide_in_done` is unchanged in body — still starts the hide timer. It is now called by the dispatcher rather than being connected directly to the signal.

The two old boolean flags (`_undo_slide_in_connected`, `_undo_slide_out_connected`) are gone. Zero references remain.

### `app.py` — undo point added to long skip and chapter wheel scroll

Undo was previously triggered only on slider/right-click seeks and chapter nav. Three new call sites:

- **`handle_rewind(long_skip=True)`** — `_trigger_undo(old_pos)` after `seek_async`, inside the `if long_skip:` branch
- **`handle_forward(long_skip=True)`** — same; the pre-existing `print()` debug line was already absent
- **`wheelEvent` chapter progress slider branch** — `_trigger_undo(current_pos)` before `seek_async` (consistent with prev/next ordering)

Short skips (regular << and >> button taps) do not set an undo point — the distance is too small to warrant one.

## What was not changed

- `_on_undo_slide_in_done` body is unchanged
- No other methods modified
- `undo_anim.finished` has exactly one connection in the file

---

# Session Summary — 2026-05-29 Session 3 — App audit pass and SessionRecorder extraction

## Overview

Six audit passes applied to `app.py` as branch `refactor/app-audit`, plus a `SessionRecorder` extraction on `refactor/session-recorder` merged back in. Five commits total. No behavior changes — all fixes are correctness, architecture cleanup, and invariant enforcement.

## Pass 1 — Invariant violations, None guards, dead imports (commit c7cc829)

**Invariant #1 violation fixed** — `_sync_playback_state` was reading `self.player.chapter or 0` to seed the chapter label on first display. `self.player.chapter` is mpv's async property and is wrong for the same reasons documented in the critical rules. Replaced with the standard epsilon walk: find last `chapter_list` entry where `time <= pos + _CHAPTER_BOUNDARY_EPSILON`.

**EOF refresh_overall loop fixed** — `self.stats_panel.refresh_overall()` was unconditionally outside the `if not self._eof_event_written` block, firing every 200ms at EOF. Moved inside the guard — now fires exactly once per EOF event (commit c0dda9f removed the `#Temporary` comment on this block, making the behavior permanent).

**None guards added:**
- `_on_slider_released`: `old_pos = self.player.time_pos or 0.0` — `time_pos` can be `None` before mpv delivers position; `abs(None - new_pos)` would raise `TypeError`
- `_on_chap_slider_released`: same
- `_on_slider_right_clicked`: added `if self.player.mp3_seek_reload_pending: return` after the duration guard — prevents a right-click chapter snap from launching a seek into a live reload

**Initialization fixes:**
- `_mpv_ready`, `_pre_switch_slider_value`, `_pre_switch_chap_slider_value` all initialized unconditionally in `__init__`. Previously only set on specific code paths — methods reading them before first book load would raise `AttributeError`.
- `session_written.connect` moved from `_build_book_detail_panel` (runs once at UI build, too late if signal fires before detail panel is built) to the player signal block in `__init__`.

**Dead inner imports removed:**
- `import re` inside `_classify_filter` — `re` imported at module level (line 5)
- `from PySide6.QtCore import Qt` inside `_update_chapter_label_clickability` — `Qt` imported at module level
- `from PySide6.QtGui import QPainter` inside `_update_cover_art_scaling` — `QPainter` imported at module level

## Pass 2 — EOF #Temporary cleanup (commit c0dda9f)

Removed `#Temporary` markers from the EOF event block in `_update_ui_sync`. The `_eof_event_written` flag and `write_book_event` call are not temporary — they are the production EOF recording path. The markers were misleading; removing them signals the code is settled.

## Pass 3 — _classify_filter and save_search_filter moved to LibraryPanel (commit 1048256)

Both methods belong with the widget that owns the search field (`LibraryPanel`), not with `MainWindow`. `save_search_filter` is now public (no leading underscore) because it is called from `MainWindow.closeEvent`. `closeEvent` now calls `self.library_panel.save_search_filter()`. No behavior change.

`_classify_filter` carries a local `import re` in `library.py` per the task spec — `re` is not imported at module level in that file.

## Pass 4 — SessionRecorder extraction (commit 705261f)

All session state and persistence logic extracted from `MainWindow` into `SessionRecorder(QObject)` in a new file `session_recorder.py`.

**What moved:**
- `_session_start`, `_session_segment_start`, `_session_listened_seconds`, `_session_position_start`, `_session_furthest_position`, `_post_seek_pending_position`
- `_session_pause_timer` (3-min timeout → `close()`)
- `_post_seek_credit_timer` (15-sec seek credit)
- `_open_session`, `_resume_session`, `_pause_session`, `_close_session`, `_on_seek_credit_earned`
- `session_written = Signal()` class-level declaration

**What stayed on MainWindow:**
- `_current_book` — read by numerous UI methods; recorder receives it via `get_book_fn=lambda: self._current_book`
- All call sites updated to use `self.session_recorder.open/resume/pause/close()`

**New methods on SessionRecorder:**
- `update_furthest_position(pos)` — called from the 200ms UI timer loop, replaces the inline 5-line block that was in `_update_ui_sync`
- `notify_seek(new_pos)` — called from `_on_slider_released` and `_on_chap_slider_released`, replaces the duplicated 7-line seek-credit blocks in both
- `is_active` property — used at play sites to distinguish `open()` vs `resume()`

**Imports removed from app.py:** `threading`, `datetime` (now owned by `session_recorder.py`)

**Signal ownership transfer:** `session_written` emits from `SessionRecorder._write()` background thread. `MainWindow.__init__` connects via `self.session_recorder.session_written.connect(self._on_session_written)`.

## Pass 5 — set_started_at / get_book_started_at migration to book_id (commit d6888be)

Both DB methods now accept `book_id: int` instead of `book_path: str`. SQL uses `WHERE id = ?` instead of `WHERE path = ?`. The only call site is `session_recorder.py`'s `_write()` inner function, which now passes `book.id`. No dual-write needed — these methods do not write `book_path` to any column, so the migration policy (retain deprecated columns until drop pass) does not apply.

## What was tested

- Session record path: played a book past 60s, closed app → session visible in stats
- Session discard path: played < 60s, closed app → no session written, no crash
- Chapter label on "Select Chapter" state: resolved correctly without using `player.chapter`
- EOF handling: `refresh_overall()` fires once, not every 200ms

## What remains deferred

- `write_session` / `write_book_event` deprecated `book_path` columns: not yet dropped. Pending full column-drop migration pass.
- `book_files` table: still on `book_path` FK. Migrate when VT is next touched.
- VT file switch session recording: `session_recorder.close/open` wiring does not account for mid-book VT file transitions. Deferred until session recording is next touched.
- PanelManager patched post-construction (construction-order smell)
- `_update_pattern_visuals` duplication between `app.py` and `settings_controller.py`
- Temp debug buttons (`next_quote_btn`, `temp_settings_btn`) — intentionally kept for main player layout work

---

# Session Summary — 2026-05-29 Session 2 — Near-EOF seek hang, stats inflation fix

## What changed

### `player.py` — near-EOF seek guard in `seek_async`

mpv hangs silently when seeked to a position within ~2 seconds of a file's end. Two guards added:

**VT same-file branch** — after the stop-and-load block and before `command_async`:
```python
if target_file['duration'] - local_pos < 2.0:
    return  # too close to file end — let natural EOF handle it
```

**Non-VT branch** — before the stop-and-load check:
```python
dur = self._cached_duration
if dur and dur - pos < 2.0:
    return  # too close to EOF — let natural EOF handle it
```

Both guards are pure early-returns with no state mutation. mpv's natural EOF path (`_on_pause_test` near-EOF detection → `_advance_or_finish`) handles the terminal seconds correctly. The guard exists only in `seek_async` — it applies to all seek sources (skip buttons, mouse wheel, progress slider) on both VT and non-VT books.

Note: the stop-and-load condition for VT same-file already had `local_pos < target_file['duration'] - 5.0`, so stop-and-load was already protected. The new guard protects the `command_async` fallthrough path that stop-and-load bypasses.

### `db.py` — stats inflation fix in `get_daily_book_breakdown` and `get_books_listened_in_period`

`LEFT JOIN book_events be ON ls.book_id = be.book_id AND be.event_type = 'finished'` was producing a cartesian product between sessions and finished events before `GROUP BY`. If a book had N finished events, every session row was duplicated N times, inflating `SUM(listened_seconds)` by a factor of N.

Fixed by replacing the JOIN + aggregate column with a correlated scalar subquery:
```sql
(SELECT MAX(CASE WHEN be.event_type = 'finished' THEN 1 ELSE 0 END)
 FROM book_events be WHERE be.book_id = b.id) as is_finished
```
The `LEFT JOIN book_events be ON ...` line is removed entirely from both methods. The scalar subquery is safe even when `b.id` is NULL (orphaned sessions) — it returns NULL, which the callers already handle.

## Approaches tried and abandoned

### Attempt 1 — eager EOF via `_book_duration` guard at top of VT branch
Added guard before `_resolve_vt_index`:
```python
if pos >= (self._book_duration or 0) - 1.0:
    self._eof = True
    self.instance.pause = True
    self._cached_time_pos = self._book_duration - self._file_offset
    return
```
Problem: too aggressive. Any skip that lands in the last second of the book (which is valid mid-book territory for most files) would set EOF and freeze playback. Also set `_cached_time_pos` to a global position, which violates the rule that `_cached_time_pos` must hold local position for VT books.

### Attempt 2 — clamp to `duration - 0.5` and let mpv hit EOF
```python
if local_pos >= target_file['duration']:
    self.instance.command_async('seek', target_file['duration'] - 0.5, 'absolute+exact')
    return
```
Problem: still sends a seek into the danger zone. The hang happens below 2s from end, not just past end.

### Attempt 3 — last-file check with explicit EOF set + file switch for middle files
```python
if local_pos >= target_file['duration']:
    if target_idx == len(self._virtual_timeline) - 1:
        self._eof = True
        self.instance.pause = True
        return
    else:
        # manual VT file switch
```
Problem: this was reverted by the user — the correct fix is the 2s buffer, not manual EOF or file switching in the seek path.

### Attempt 4 — `_cached_duration` guard with state mutation in else branch
```python
dur = self._cached_duration
if dur and pos >= dur - 1.0:
    self._eof = True
    self.instance.pause = True
    self._cached_time_pos = dur
    return
```
Also reverted — setting `_eof`/`pause`/`_cached_time_pos` is the wrong pattern here; a pure early-return is sufficient and avoids side-effects.

## Key invariants preserved

- No state mutation on early return in either guard — `_eof`, `instance.pause`, `_cached_time_pos` are untouched.
- VT file-switch branch (`target_idx != self._current_vt_index`) is not affected by either guard.
- M4B/CUE books hit the non-VT guard; VT books hit the same-file guard. Coverage is complete for all seek paths.
- stop-and-load already had a `duration - 5.0` buffer; the new guard applies only to the `command_async` fallthrough.

---

# Session Summary — 2026-05-29 Session 1 — VT stop-and-load, reload guards, chapter UI persistence

## What changed

### `player.py` — VT stop-and-load seek (same-file MP3 within virtual timeline)

Extended `_mp3_stop_and_load` and `seek_async` to handle large MP3 files inside a virtual timeline book. The existing single-file stop-and-load path was VT-unaware; VT books skipped it entirely.

**New constant:**
```python
_VT_MP3_SIZE_THRESHOLD: int = 40 * 1024 * 1024  # 40 MB
```
Files below this use normal `command_async` even if the seek distance exceeds `_MP3_SEEK_THRESHOLD`.

**`_mp3_stop_and_load` generalized:**
```python
def _mp3_stop_and_load(self, target_pos: float, file_path: str | None = None, local_pos: float | None = None)
```
- `file_path`: VT file path, or `None` → falls back to `self._play_target` (single-file case)
- `local_pos`: within-file seek target, or `None` → uses `target_pos` (single-file case)
- `_cached_time_pos` is set to `local_pos if local_pos is not None else target_pos` — critical: for VT calls, must hold the **local** position so `time_pos` getter (`_file_offset + _cached_time_pos`) returns the correct global value without double-counting the offset.

**`seek_async` VT same-file branch — new stop-and-load gate:**
```python
if (target_file['file_path'].lower().endswith('.mp3')
        and abs(local_pos - ((self._cached_time_pos or 0.0) - self._file_offset)) > _MP3_SEEK_THRESHOLD
        and os.path.getsize(target_file['file_path']) > _VT_MP3_SIZE_THRESHOLD
        and 2.0 < local_pos < target_file['duration'] - 5.0
        and not self._mp3_seek_reload_pending):
    self._mp3_stop_and_load(pos, file_path=target_file['file_path'], local_pos=local_pos)
    return
```
Buffer rationale:
- `2.0 <` at start: prevents `start=T` with very small T from causing unexpected mpv behaviour.
- `< duration - 5.0` at end: prevents landing close enough to EOF that mpv immediately triggers VT file transition before state settles. Seeks in the 5s tail fall through to `command_async`.

**Bounds check before `command_async`:**
```python
if local_pos >= target_file['duration']:
    return  # past end — no state mutation, let natural EOF handle it
```
Added between stop-and-load block and `command_async` call.

**State mutation moved after bounds check:** The three state assignments (`_eof = False`, `is_seeking = True`, `_seek_target = pos`) were at the top of the VT branch before the same-file/different-file split. Moved inside each branch so no state is mutated on an early return.

**Public property added alongside `mp3_seek_visual_lock`:**
```python
@property
def mp3_seek_reload_pending(self) -> bool:
    return self._mp3_seek_reload_pending
```

### `player.py` — `_cached_time_pos` / `time_pos` offset bug — RESOLVED

**Root cause:** `_mp3_stop_and_load` was setting `self._cached_time_pos = target_pos` where `target_pos` is the global book position. The `time_pos` getter for VT books returns `self._file_offset + self._cached_time_pos`. So during the reload window, `time_pos` returned `_file_offset + global_pos` — inflated by exactly `_file_offset`.

**Fix:** `self._cached_time_pos = local_pos if local_pos is not None else target_pos`. For VT calls `local_pos` is the within-file offset; the getter then correctly returns `_file_offset + local_pos = global_pos`. For single-file calls `local_pos is None` and `target_pos == local_pos` anyway — no change in behaviour.

**Downstream consequence that was seen:** `handle_forward` and `handle_rewind` read `self.player.time_pos` to compute `new_pos`. During the reload window they were reading the inflated value and passing it to `seek_async`, which produced a second seek to a wrong position (sometimes near the beginning due to bounds clamping).

### `app.py` — `handle_forward` / `handle_rewind` reload guard and None check

Both methods now gate on `not self.player.mp3_seek_reload_pending` and guard against `old_pos is None`:
```python
def handle_rewind(self, long_skip=False):
    self.panel_manager.hide_all_panels()
    if self.player and not self.player.mp3_seek_reload_pending:
        old_pos = self.player.time_pos
        if old_pos is None:
            return
        ...

def handle_forward(self, long_skip=False):
    self.panel_manager.hide_all_panels()
    if self.player and not self.player.eof_reached and not self.player.mp3_seek_reload_pending:
        old_pos = self.player.time_pos
        if old_pos is None:
            return
        ...
```
`time_pos` can return `None` during the reload window even after the offset bug is fixed (mpv observer fires before the property is populated). `None + skip` = `0 + skip`, seeking to near the start of the book. The `None` guard prevents this independently of the reload pending flag.

### `player.py` — concurrent reload guard

Both `_mp3_stop_and_load` call sites in `seek_async` (VT same-file and non-VT) gained `and not self._mp3_seek_reload_pending` in their conditions. If a reload is already in flight, a second trigger is silently dropped. Without this guard, stacked `loadfile` calls cause the second `_on_file_loaded` to go through the normal post-load path (not the early-return), emitting `book_ready` and triggering position restore from DB.

### `app.py` + `ui/theme_manager.py` — `_set_chapter_ui_active` persistence across theme changes

**Problem:** Theme application calls `setStyleSheet` on `content_container`, which repolishes all child widgets. This undoes the cursor and stylesheet overrides that `_set_chapter_ui_active(False)` applied to chapter labels — after a theme change, the chapter UI appeared interactive again even for books without chapters.

**Fix:**
1. `_chapter_ui_active: bool = True` added to `app.py` `__init__`.
2. `_set_chapter_ui_active` sets `self._chapter_ui_active = active` at its top.
3. `_apply_stylesheets` in `theme_manager.py` calls `mw._set_chapter_ui_active(mw._chapter_ui_active)` at the end, after all `setStyleSheet` calls.

The flag tracks the logical state independently of widget appearance, so any stylesheet repolish is immediately corrected.

## What was investigated but not changed

- `progress_slider.valueChanged` / `sliderMoved`: neither is connected to a seek in app.py. The only seek path from the progress slider is `sliderReleased` → `seek_async`. Confirmed no `time_pos =` synchronous writes on the slider path.
- `_on_file_loaded` registration: registered exactly once, on `'file-loaded'` only (`event_callback('file-loaded')(self._on_file_loaded)` at line 107). Not registered on `end-file` or any other event. Double-fire would require mpv itself firing the event twice for one `loadfile` — possible with `keep_open='always'`, but not observed.

## Key invariants preserved

- `_on_file_loaded` early-return on `_mp3_seek_reload_pending` still fires before any VT file-switch logic. The `_is_vt_file_switch`, `_current_vt_index`, and `_file_offset` fields are never touched by stop-and-load — those are for real file transitions only.
- `book_ready` is never emitted during a stop-and-load reload on any path (VT or non-VT).
- VT file switches (different-file branch of `seek_async`) are completely unaffected.
- M4B and CUE books never reach stop-and-load intercept (not `.mp3`).

---

# Session Summary — 2026-05-28 Session 3 — EOF nav guards, chapterless book UI

## What changed

### `player.py` — `next_chapter` EOF and last-chapter guards

`next_chapter` now returns early in two cases:
1. `if self._eof: return` at the top — prevents any navigation after EOF is reached.
2. Last-chapter boundary check after the chapter walk — if `curr_chap >= len(chap_list) - 1` (non-VT) or `curr_chap >= len(self._chapter_list) - 1` (VT), return without seeking.

The old `else: seek to _book_duration` fallback path is gone from both branches. VT EOF is now reached naturally when the last file finishes playing. The non-VT path was seeking past the end of the last chapter, which caused state corruption on rapid >| clicks.

### `player.py` — `seek_within_chapter` EOF guard removed

An `if self._eof: return` guard was added to `seek_within_chapter` and then removed in the same session. The guard was wrong: mouse wheel on the chapter slider already cleared EOF correctly (via `seek_async` which clears `_eof` internally), and click/drag must behave identically. The guard belongs on directional advances (`next_chapter`, `handle_forward`) not positional seeks. `seek_within_chapter` is a positional seek — it should always proceed.

### `app.py` — `handle_forward` EOF guard

`handle_forward` (>> button) now checks `not self.player.eof_reached` before doing anything. Prevents >> from firing at EOF where Restart is showing.

### `app.py` — `_set_chapter_ui_active` — ghost chapter UI for books without chapters

New method `_set_chapter_ui_active(active: bool)`. When `active=False` (no chapter list):
- `chapter_progress_slider`: `bg_color` and `fill_color` set to transparent directly via property setters (calls `update()` automatically). `WA_TransparentForMouseEvents = True` kills all interaction.
- Chapter labels (`current_chapter_label`, `chap_elapsed_label`, `chap_duration_label`): `color: transparent` via instance stylesheet.
- `current_chapter_label` and `chap_duration_label` cursors set to `ArrowCursor`.
- `_chapter_label_clickable = False` set directly — bypasses `_update_chapter_label_clickability`.
- `_prev_chap_title` and `_next_chap_title` cleared, `_clear_preview()` called to dismiss any lingering hint.

When `active=True` (chapters present):
- Slider colors restored via `unpolish/polish` so the theme QSS re-drives them.
- `WA_TransparentForMouseEvents = False`, `PointingHandCursor` restored on slider and `chap_duration_label`.
- Label stylesheets cleared (theme QSS resumes).
- `_update_chapter_label_clickability()` called to restore correct cursor and clickable state.

Layout is never affected — no `setVisible` calls. All widgets stay in place.

`chap_duration_label.setCursor(Qt.PointingHandCursor)` removed from `_build_secondary_controls` — `_set_chapter_ui_active` owns that state exclusively.

Called from `_on_file_loaded_populate_chapters` in both branches.

---

# Session Summary — 2026-05-28 Session 2 — Stop-and-load seek for single VBR MP3 files

## What changed

### `player.py` — stop-and-load seek path

Seeking in VBR MP3 files with `absolute+exact` forces mpv to scan forward through the bitstream to locate the target frame. For long seeks this causes perceptible lag (1–30s depending on file size). The fix: for single `.mp3` files, seeks beyond a distance threshold reload the file with mpv's `start=` option rather than seeking within the open stream. mpv's Xing/TOC header provides an approximate byte offset for fast positioning.

**New constant** (after `_CHAPTER_BOUNDARY_EPSILON`):
```python
_MP3_SEEK_THRESHOLD: float = 60.0  # long seeks on single VBR MP3 use stop-and-load
```

**New state in `__init__`:**
- `_play_target: str | None` — resolved file path stored from `_on_playlist_resolved`
- `_mp3_seek_reload_pending: bool` — guards `_on_file_loaded` early-return
- `_mp3_seek_target: float` — stored target (unused after refactor but kept for symmetry)
- `_mp3_seek_was_playing: bool` — pre-seek pause state for restore
- `_mp3_seek_visual_lock: bool` — suppresses play/pause button icon updates during reload

All five reset in `load_book` alongside existing VT state resets. `_play_target` and `_mp3_seek_reload_pending`/`_mp3_seek_visual_lock` are the only ones read at runtime.

**`_on_playlist_resolved`:** `self._play_target = play_target` added as first line so all subsequent seek calls have the resolved path available.

**New method `_mp3_stop_and_load(target_pos)`:**
Sets `_mp3_seek_reload_pending`, stores `_mp3_seek_was_playing`, sets `_is_seeking` and `_seek_target`, updates `_cached_time_pos` for immediate UI consistency, sets `_mp3_seek_visual_lock = True`, pauses mpv, then issues:
```python
self.instance.command('loadfile', self._play_target, 'replace', '0', f'start={target_pos}')
```
The synchronous `command()` (not `command_async`) is intentional — the call returns as soon as mpv queues the load, before the file actually loads. Pause-before-load prevents brief wrong-position playback during the reload window.

**`_on_file_loaded` early-return block** (at top, before all existing logic):
```python
if self._mp3_seek_reload_pending:
    self._mp3_seek_reload_pending = False
    self._is_seeking = False
    self._seek_target = None
    self.instance.pause = not self._mp3_seek_was_playing
    self._mp3_seek_visual_lock = False
    return
```
The `return` is load-bearing — without it, `_on_file_loaded` would proceed to `book_ready` emission, triggering `_on_file_ready` in app.py which re-restores position from DB.

**`seek_async` intercept (non-VT `else` branch):**
```python
if (self._play_target is not None
        and self._play_target.lower().endswith('.mp3')
        and abs(pos - (self._cached_time_pos or 0.0)) > _MP3_SEEK_THRESHOLD):
    self._mp3_stop_and_load(pos)
    return
```
Added before the existing `command_async` call. Short seeks fall through. VT books never reach this branch (they're handled in the `if self._virtual_timeline is not None:` block above).

**Public property:**
```python
@property
def mp3_seek_visual_lock(self) -> bool:
    return self._mp3_seek_visual_lock
```

### `app.py` — play/pause button visual lock

`_set_play_icon` gains an early-return guard:
```python
if self.player.mp3_seek_visual_lock:
    return
```
`_set_play_icon` is the single funnel for all play/pause button icon updates. Guarding it here suppresses flicker from every call site (timer loop, `_sync_ui_render`, EOF path) during the reload window. The actual pause state and all other logic are unaffected — only the icon update is skipped.

### `player.py` — `apply_smart_rewind` unified to `seek_async`

Previously: VT path used `seek_async(new_pos)`; non-VT path used `self.time_pos = new_pos` (sync seek). This inconsistency meant smart rewind on non-VT books blocked the Qt main thread and bypassed the `_is_seeking` guard. Fixed: both paths now use `seek_async(new_pos)`. The `self.is_seeking = True` line after was also removed — `seek_async` sets `_is_seeking` internally.

## Key invariants

- `book_ready` is never emitted during a reload seek — the `_mp3_seek_reload_pending` guard returns before the existing book_ready emit.
- VT books: `_mp3_stop_and_load` is only reachable from the non-VT `else` branch. VT seeks are unaffected.
- M4B and CUE books: not `.mp3`, intercept not entered.
- Smart rewind: fires normally after reload resume — `instance.pause = False` in `_on_file_loaded` unpauses mpv, which triggers the normal resume path.
- `is_seeking` property: both `self.is_seeking = True` (property setter) and `self._is_seeking = True` (direct) are equivalent. The property has no side effects beyond the attribute assignment.

---

# Session Summary — 2026-05-28 Session 1 - book_id FK migration — listening_sessions, book_events, book_tags

## What changed

Migrated three tables from `book_path TEXT` join key to `book_id INTEGER REFERENCES books(id)`. `book_files` excluded (deferred to VT work). `book_path` columns retained as deprecated (not dropped, not written, not queried).

### Schema (`db.py` — `_create_tables`)

Three `PRAGMA table_info` + `ALTER TABLE … ADD COLUMN book_id INTEGER REFERENCES books(id)` blocks added after the existing `books` column migration guards. Each is followed immediately by a correlated `UPDATE` backfill (`SET book_id = (SELECT id FROM books WHERE books.path = <table>.book_path)`) and a new index (`idx_sessions_book_id`, `idx_book_events_book_id`, `idx_book_tags_book_id`). `book_tags` UNIQUE constraint (`UNIQUE(book_path, tag)`) left untouched — SQLite ALTER TABLE cannot modify constraints; requires a full table rebuild which is deferred to the `book_path` column drop pass.

### Write methods (`db.py`)

`write_session`, `write_book_event`, `add_book_tag` each gained a `book_id: int | None = None` parameter. `book_id` added to the INSERT column list. `book_path` writes retained so deprecated columns stay populated.

### Read/query methods (`db.py`)

All `LEFT JOIN books b ON ls.book_path = b.path` → `ON ls.book_id = b.id`. All `WHERE book_path = ?` → `WHERE book_id = ?`. `GROUP BY ls.book_path` → `GROUP BY ls.book_id` in `get_daily_book_breakdown` and `get_books_listened_in_period`. Correlated subqueries in both updated to match. `get_listening_time_per_period` now groups by `book_id` — orphaned NULL rows collapse (documented in NOTES.md). `COALESCE(b.title, ls.book_title, ls.book_path)` fallback chains preserved in all SELECT lists for orphaned rows. Method signatures updated: `get_book_stats`, `get_book_sessions`, `delete_book_stats`, `get_book_tags`, `remove_book_tag`, `get_tag_suggestions` all accept `book_id: int`; `add_book_tag` accepts `book_id: int, book_path: str`.

### Call sites

- `app.py` `_close_session`: `write_session(book_id=book.id, book_path=book.path, ...)` and `write_book_event(..., book_id=book.id)`.
- `book_detail_panel.py`: all tag/stats/session calls use `self._book_data['id']`. `_book_data` always has `'id'` — populated from the caller dict or from the `db.get_book()` fallback in `load_book`.
- `tag_manager.py` `_on_book_removed`: uses `self.db.get_book(path)` to retrieve `book_id`. Initial implementation used `next()` against `self._book_grid._books` — incorrect because `_TagBookGrid._on_remove` filters `_books` before calling `parent_remove`, so the lookup always returned `None`. DB call sidesteps ordering entirely.

### Bugs fixed alongside

**Tag remove count/delete not updating:** `_on_book_removed` was returning early (book_id None) on every call due to the `_books` ordering issue above. After the DB-call fix, remove, count update, and tag auto-delete all work correctly.

**Day tab stale after panel reopen:** `_open_stats_flow` called `refresh_overall()` only. If the user was already on the Day tab, `_on_tab_changed` never fired and `_cached_active_days` (populated from the previous open) was reused indefinitely. Fixed by: (1) `panels.py` — `refresh_overall()` → `refresh_current_tab()` on panel open; (2) `stats_panel.py` — `_on_tab_changed` now calls `_invalidate_period_cache()` first so every tab switch fetches fresh active-period data.


# Session Summary — 2026-05-27 Session 1 — Persist search filter, smart rewind sub-button visibility, field max lengths

## What changed

### `config.py` — four new persist-filter keys

`get/set_persist_filter_enabled` (default `False`), `get/set_persist_filter_tag` (default `True`), `get/set_persist_filter_text` (default `True`), `get/set_persist_filter_year` (default `True`). `get_smart_rewind_duration` default and guard unchanged (0 is correct for a fresh install where smart rewind has never been enabled).

### `app.py` — Persist search filter UI (Library tab)

New "Persist search filter" section at the bottom of `_build_library_tab`. Layout mirrors Smart Rewind: header label, then one `QHBoxLayout` with `[Off] [On]` left + stretch + `[Tag] [Text] [Year]` right. Sub-buttons created with `setVisible` matching config state at build time. All-three-off correction in `_sync_persist_filter_on_open()` (called from `panels.py` on every settings panel open) forces master Off if enabled but all sub-keys are False — sub-button visibility updated there too. `_on_persist_filter_master`: shows/hides sub-buttons, resets all three sub-keys to True if all were False before enabling. `_on_persist_filter_sub`: toggles one sub-key, no visibility change (sub-buttons stay visible until next panel open). `_update_persist_filter_visuals`: syncs `selected` property on master and sub buttons only — no `setVisible` call here. `_save_search_filter` (called from `closeEvent`) and `_classify_filter` (static) handle save side. Restore handled in `LibraryPanel.__init__` (see below).

### `ui/library.py` — search filter restore at construction time

`search_field.setMaxLength(26)` added immediately after construction. Persist-filter restore added right after the field is fully wired: reads `config.settings.value("persisted_filter")` directly and sets text with signals blocked, matching how sort key and view mode are restored in the same `__init__` block.

### `ui/speed_controls.py` — smart rewind duration button visibility

Duration buttons (`10`, `20`, `30`) created with `setVisible` matching `get_smart_rewind_wait() > 0` at build time. `_update_smart_rewind_mode` calls `setVisible(val > 0)` on all duration buttons immediately. `sync_smart_rewind_visuals()` public method added for panel-open sync (called from `panels.py`). `_validate_smart_rewind_settings` invalidation block removed — duration always has a saved value once smart rewind has ever been used, so the invalid state it guarded against cannot occur in normal use.

### `ui/panels.py` — sync hooks on settings and speed panel open

`_start_settings_entry` calls `main_window._sync_persist_filter_on_open()` before show. `_start_speed_entry` calls `speed_panel.sync_smart_rewind_visuals()` before show.

### `ui/theme_manager.py` — RuntimeWarning fix

`_panel_guard_timer.timeout.disconnect()` catch widened from `TypeError` to `(TypeError, RuntimeError)` — PySide6 raises `RuntimeError` (not `TypeError`) when disconnecting a signal with no connected slots.

### `ui/book_detail_panel.py` — field max lengths

`setMaxLength(300)` added inside `make_field()`, applying to all four metadata fields (title, author, narrator, year). Year's 4-digit validator is unaffected.

---

# Session Summary — 2026-05-26 Session 2 — Custom context menus on text input fields

## What changed

### `ui/text_context_menu.py` — new file

New `ContextIconMenu(QWidget)` — a frameless floating popup with four icon buttons (Cut, Copy, Paste, Delete). One shared instance per parent panel, reused across all fields via `show_for(target, global_pos)`. Dismisses on action (Popup window type handles focus-loss dismissal automatically).

Button state is evaluated at show time: Cut/Delete require selection + not read-only; Copy requires selection only; Paste requires clipboard text + not read-only. If no buttons would be active the menu is suppressed entirely.

Icons use `load_themed_icon` with `Normal` and `Disabled` pixmap modes on a single `QIcon` — disabled state renders at 0.3 opacity. Qt switches automatically; no QSS opacity hack needed.

Position logic: `QApplication.activeWindow()` provides the real top-level window (not the menu itself — see NOTES). Menu starts at cursor, nudges inward only when it would bleed past the window content area.

Themed via `apply_theme(dict)`: `accent` for icon color, `bg_main` for background, `accent` as rgba with 0.80 opacity for border.

### `book_detail_panel.py` — context menu wired to 5 fields

- `_title_label`, `_author_label`, `_narrator_label`, `_year_label` (`_ElidingLineEdit`): `CustomContextMenu` set inside `make_field()`, signals connected in a loop after all four are assigned.
- `_tag_input`: `CustomContextMenu` + signal at creation site.
- `_ctx_menu = ContextIconMenu(self)` created in `__init__` after `_build_ui()`.
- `on_theme_changed` forwards theme dict to `_ctx_menu.apply_theme(theme)`.
- IBeam cursor regression fixed: `_enter_edit_mode` and `_exit_edit_mode` both call `field.setCursor(IBeamCursor)` after each `setReadOnly` toggle — Qt resets the cursor silently on read-only change.

### `tag_manager.py` — context menu wired to `_tag_name_edit`

- `CustomContextMenu` policy set at creation; signal connected after `_ctx_menu` is assigned in `__init__`.
- `on_theme_changed` refactored to call `_resolve_theme` once and share the result with both `_update_tag_icons` and `_ctx_menu.apply_theme`.

### `library.py` — `search_field` right-click clears field

`CustomContextMenu` + `customContextMenuRequested` → `search_field.clear()`. No `ContextIconMenu` involved.

### `sleep_timer.py` — `custom_sleep_input` right-click clears field

Same pattern as `search_field`.

### `stats_panel.py` — `day_start_spin` suppressed

`NoContextMenu` on the `QSpinBox` in the Options tab.

---

# Session Summary — 2026-05-26 — Tag panel interaction polish and book detail ↔ tag manager wiring

## What changed

### `tag_manager.py` — spacing fix

`panel_layout` switched from uniform `setSpacing(6)` to `setSpacing(0)` with explicit `addSpacing` calls between items. Breakdown: 6px after back button, 2px after name row, 4px after reserved row. Eliminates the visual excess above the picker/confirmation row that came from the uniform gap.

### `tag_manager.py` — always enter via list view

`refresh()` now unconditionally resets to list view (`_current_tag = None`, hides `_panel_widget`, shows `_list_widget`) before rebuilding the tag list. Previously `refresh()` re-entered the tag panel via `_open_tag(_current_tag)` when a tag was open — on re-open after navigation away, the full book grid (potentially 100+ thumbnails) would reload without the user requesting it. The `_open_tag` call from `refresh()` has been removed entirely.

`refresh_books()` (used for in-session updates when the user is actively on a tag panel) is unchanged.

### `tag_manager.py` — picker dismiss fixes

- Clicking the color dot while editing a tag name now reverts the name and clears focus before opening the picker (`_toggle_color_picker` calls `_revert_tag_name()` + `clearFocus()`).
- `_panel_widget.mousePressEvent` extended: clicks on empty panel area now also dismiss the picker (previously only dismissed delete confirmation). The check is: confirming → cancel confirm; picker open → `_show_reserved("none")`; else no-op.
- `_show_reserved` locks/unlocks the book grid for the picker state (locked while picker is open, unlocked when dismissed), consistent with confirm-delete locking.

### `tag_manager.py` — trash cursor during delete confirmation

`_on_delete_tag` now sets `self._action_btn.setCursor(Qt.CursorShape.ArrowCursor)` alongside the icon dim. Previously the button showed a pointing hand on hover even during confirmation. `_cancel_delete_confirm` restores the cursor via `_set_action_mode("delete")`.

### `tag_manager.py` — Escape key on name field

App-level event filter now intercepts `KeyPress` with `Key_Escape` when `obj is self._tag_name_edit`. Calls `_revert_tag_name()` + `clearFocus()`. Same dismiss behavior as click-outside.

### `book_detail_panel.py` — Escape key on inline edit fields

Event filter (app-level, installed on `BookDetailPanel`) now intercepts `KeyPress` with `Key_Escape` when `self._editing` is True. Calls `_exit_edit_mode(save=False)`. Consistent with click-outside revert.

### `library.py`, `sleep_timer.py` — Escape on input fields

Both the library search field and the sleep timer custom input now clear their content and defocus on Escape via `keyPressEvent` overrides. This sets up a future "Escape dismisses panel when no field is focused" pattern without ambiguity.

### `tag_manager.py` — right-click on book thumbnail opens Book Detail Panel

`_TagBookThumb.mousePressEvent` now handles `RightButton`: emits `detail_requested` signal (new) instead of `remove_requested`. The signal bubbles: `_TagBookThumb.detail_requested` → `_TagBookGrid.parent_detail` (stub, overridden by `TagManagerWidget`) → `TagManagerWidget.detail_requested` (new `Signal(str)` on the widget). Wired in `app.py` to `panel_manager.open_book_detail({"path": path}, tab="stats", context='tags')`.

Behavior on right-click: Book Detail Panel slides in from the right over the tag panel. Close button on detail panel returns to tag panel (tag panel remains visible). Clicking the toolbar (title bar) dismisses both.

### `book_detail_panel.py` — "Tag management" button on Tags tab

New `QPushButton#tag_manager_nav_btn` ("Tag management") added to the bottom of the Tags tab. Visible only when `context != 'tags'` (i.e., opened from library or stats). Hidden when already opened from the tag panel (redundant navigation). Emits `open_tag_manager_requested` signal (new on `BookDetailPanel`). Wired in `app.py` to `_on_open_tag_manager_from_detail`, which calls `hide_all_panels()` then opens the tag panel after a 320ms delay (covers the longest close animation). Styled via `get_stats_stylesheet` (same function as `BookDetailPanel`).

### `themes.py` — `tag_manager_nav_btn` rule

Added to `get_stats_stylesheet`: transparent background, text color, `accent_dark` border, 4px padding, bold. Hover: accent fill. Pressed: accent_dark fill.

---

# Session Summary — 2026-05-25 Session 2 — Tag manager and book detail panel UX polish

## What changed

### `tag_manager.py` — inline rename UX fixes

Three bugs fixed in the tag name field:

- **Dirty state not recalculated after save.** After a successful rename, `_tag_name_original` was never updated to the new name. Re-editing back to the pre-save value incorrectly showed no dirty state. Fixed: `_on_rename` now sets `self._tag_name_original = new_name` on success.

- **No revert on click-outside.** The name field had no dismiss handler. Fixed: app-level `eventFilter` installed via `QApplication.instance().installEventFilter(self)` on `_open_tag`, removed on `_show_list` and `hideEvent`. Any click outside `_tag_name_edit` and `_action_btn` calls `_revert_tag_name()`, which restores text and resets mode to `"delete"`.

- **"Renamed" / "Name already in use" status label removed.** The `_rename_status` label and its layout slot were deleted. Success is indicated by the checkmark icon alone. Duplicate-name failure sets the action button to `"save_error"` mode, rendering the save icon in `#E05050` — stays red until the user types, which `_on_tag_name_changed` clears by resetting to `"save"` mode. No timer involved.

### `tag_manager.py` — action button mode state machine

`_set_action_mode` is the single owner of button enabled state, cursor, and icon. Key states:

- `"delete"` — trash icon, accent/0.70, pointing hand cursor, enabled
- `"save"` — save icon, accent/0.70, pointing hand cursor, enabled
- `"save_error"` — save icon, `#E05050`/0.90, arrow cursor, enabled (so Qt does not grey it)
- `"check"` — check icon, accent/1.0, arrow cursor, enabled (notification only — click is a no-op)

Hover handling via `installEventFilter(self)` on `_action_btn`. `_on_action_btn_hover` brightens trash to `#cc3333`/1.0 and save to accent/1.0 on enter; restores on leave. Guard: no-op when `_confirming_delete` is True.

### `tag_manager.py` — delete confirmation interaction guards

When confirmation is visible:
- `_detail_dot` cursor → arrow, `mousePressEvent` → `_cancel_delete_confirm`
- `_tag_name_edit` → `setReadOnly(True)`, cursor → arrow, `mousePressEvent` → `_cancel_delete_confirm`
- `_book_grid` thumbs → arrow cursor via `set_locked`
- Trash icon → accent/0.35 (drawn directly, no `setEnabled`)

All restored in `_cancel_delete_confirm`, which ends with `_set_action_mode("delete")` to prevent a red-on-restore flash from stale hover state.

### `tag_manager.py` — icon rendering fix

`_load_icon` now matches `book_detail_panel._load_svg_icon`: injects `<style>path { fill: color; }</style>` for SVGs with no explicit `fill`/`stroke` attributes (e.g. save.svg from Font Awesome). Previously rendered black regardless of theme color.

### `book_detail_panel.py` — delete confirmation parity with tag manager

- `_on_remove_clicked` now draws the trash icon at accent/0.35 and sets arrow cursor — no `setEnabled(False)`, so no Qt greying.
- Adds a 7-second `QTimer` (`_remove_cancel_timer`) that auto-dismisses confirmation, matching tag manager behavior.
- `_cancel_remove` restores hand cursor, stops/clears the timer, and calls `_update_remove_btn_icon()` to reset the icon.
- `eventFilter` hover guard: `_update_remove_btn_icon` hover calls skipped when `_confirming_remove` is True.

### Cursor assignments

| Widget | Normal | Confirming |
|---|---|---|
| Tag action button (trash/save) | Pointing hand | Arrow (save_error/check modes) |
| Tag detail dot | Pointing hand | Arrow |
| Tag name field | IBeam | Arrow |
| Book grid thumbs | Pointing hand | Arrow |
| Book detail trash | Pointing hand | Arrow |
| Book detail meta action btn | Pointing hand | — |
| Book detail inline edit fields | IBeam | — |

---

# Session Summary — 2026-05-25 Session 1 — Tag panel reserved row refactor and interaction guards

## What changed

### `tag_manager.py` — reserved row (`QStackedLayout`) replacing loose show/hide siblings

The `_color_picker_row` and `_confirm_delete_label` were previously independent widgets in `panel_layout`, shown and hidden via `.show()`/`.hide()`. Replaced with a single `_reserved_row` (`QWidget`, `setFixedHeight(32)`) containing a `QStackedLayout` with three pages: `_reserved_empty` (default), `_color_picker_row`, `_confirm_delete_label`. A new `_show_reserved(mode)` method switches pages by name (`"picker"`, `"confirm"`, `"none"`).

This eliminates layout shift — `panel_layout` always sees one fixed-height widget regardless of which page is active.

### Delete confirm state — lock, timer, dismiss

`_on_delete_tag` now:
- Shows `"confirm"` page via `_show_reserved`
- Locks the book grid (`_book_grid.set_locked(True)`) to prevent accidental book removal during confirm
- Disables `_action_btn`
- Starts a 7-second `QTimer` stored as `self._cancel_timer` (up from 3s)

`_cancel_delete_confirm` is now unconditional (no `if self._confirming_delete` guard) and handles all cleanup: resets flag, re-enables button, calls `_show_reserved("none")`, calls `set_locked(False)`, stops and clears timer. `_on_confirm_delete` calls `_cancel_delete_confirm()` first to ensure consistent cleanup before the delete.

### `_TagBookGrid` lock mechanism

Added `self._locked: bool = False` and `set_locked(locked: bool)`. When locked, `_on_remove` skips the thumb removal and grid rebuild, calling only `parent_remove` — which routes to `_on_grid_remove`, which detects `_confirming_delete` and cancels confirm instead of deleting the book.

### `_on_grid_remove` — picker dismissal on book remove

When picker is open and a book is removed (grid not locked), `_on_grid_remove` now calls `_show_reserved("none")` before `_on_book_removed`. Previously the picker would remain visible after a book removal.

### Panel-level click-to-dismiss

`_panel_widget.mousePressEvent` set to cancel delete confirm if confirming. Gives the user a large target to dismiss without needing to navigate to a specific widget.

### `_set_tag_color` — no full refresh

`_set_tag_color` no longer calls `refresh()`. Instead it calls `_update_list_dot(tag, color_key)` (new method) and `tag_changed.emit()`. `_update_list_dot` walks `_tag_list_layout`, matches the row by `tag_list_name` label text, and patches the dot's objectName and stylesheet in-place. `refresh()` was rebuilding the entire tag list and reloading covers on every color pick — unnecessary.

### Color picker dot size

Picker dots use `font-size: 18px` via inline `setStyleSheet`. The `setFixedSize(20, 20)` hit area is unchanged. No other dots in the file were modified.

---

# Session Summary — 2026-05-24 Standalone — Tag panel header redesign and styling polish

## What changed

### Tag panel header restructure (`tag_manager.py`)

The tag detail panel header was redesigned from a single `top_row` into two separate rows:

- `_back_btn` (`‹`) sits on its own row above the name area, added directly to `panel_layout`.
- `name_row` (`QHBoxLayout`) holds `_detail_dot` + `_tag_name_edit` + `_save_btn` + `_trash_btn`.
- `_save_btn` is hidden by default and appears only when the tag name field text diverges from `_tag_name_original`. `_on_tag_name_changed` drives show/hide. Clicking it or pressing Return calls `_on_rename`.
- `_trash_btn` triggers a two-step delete: first press shows `_confirm_delete_label` (a `_ClickableLabel` with a `clicked` signal) and starts a 3-second timeout; clicking the label fires `_on_confirm_delete` which does the actual delete. `_cancel_delete_confirm` hides the label on timeout.
- `_tag_name_edit` objectName changed from `metadata_field` to `tag_name_field` to avoid inheriting unrelated QSS from other panels.
- `MAX_TAG_LENGTH` constant centralised at module level (was duplicated).

### Icon rendering (`tag_manager.py`)

- Removed dependency on `icon_utils.py`. Inline `_load_icon(name, color, size, opacity)` renders SVG icons via `QSvgRenderer` directly in `tag_manager.py` — four lines, no shared module needed.
- `_update_tag_icons()` tints save and trash icons from `self._current_theme["accent"]` on every `on_theme_changed` call.
- Trash icon render/display size bumped from 18 to 21.

### `_ClickableLabel` helper

Added `_ClickableLabel(QLabel)` before `TAG_COLORS` — emits `clicked` signal on left mouse press. Used for the confirm-delete affordance; available for future reuse within the file.

### Dot objectName consistency

Colored tag dots were receiving an inline `setStyleSheet(f"color: {hex}")` but no objectName, so the `padding-top` QSS rule on `tag_dot_neutral` didn't apply to them. Fixed by assigning `tag_dot_colored` / `tag_dot_colored_inline` objectNames alongside the inline color at all three sites: `_build_tag_row`, the color picker loop, and `_update_detail_dot`. Picker-row and detail dots use `_inline` variants (16×20 fixed size) while list-row dots use the base names (14×20).

### `get_tags_stylesheet` additions and fixes (`themes.py`)

- Added `QLineEdit#tag_name_field` rule (replaces the now-removed `QLineEdit#metadata_field` duplicate that was never used in the tag panel after the header redesign).
- Added `QPushButton#tag_icon_btn` rule: transparent background, accent color, no border, no padding.
- Added `QLabel#tag_confirm_delete` rule: accent border, panel background, accent_light text.
- Added `QLabel#tag_dot_colored` rule carrying `padding-top: 0px` to match `tag_dot_neutral`.
- Added `QLabel#tag_list_name:hover` rule.
- Added `QLabel#book_count_label` rule: 14px bold, accent color.
- Added explicit `QWidget#tag_manager_list`, `QWidget#tag_manager_panel`, `QWidget#tag_list_container` transparent background rules (previously only `QScrollArea` was covered).
- Switched `QWidget#tag_list_row` hover/non-hover split: non-hover uses `bg_deep` at 0.6, hover uses `accent_dark` at 0.6.
- `QScrollBar:vertical` background changed from `bg_deep` to `transparent`.
- Tag list row height 36→31, left margin 8→4, spacing 2→1, dot size 16×16→14×20.
- `book_count_label` text no longer includes the tag name after rename or book removal (redundant beside the editable field).

### Theme changes

- `expand_button` theme key added — controls chapter list expand/collapse button color independently from `accent`. Documented in the theme key reference block. `get_base_stylesheet` reads `t.get('expand_button', t['accent'])`.
- **The Overlook**: full library overlay color suite added (`bg_library`, `library_*` keys), `expand_button` set to `#210606`, `button_text` added, `text` brightened to `#ffb692`, Alzabo `panel_opacity_hover` 1.00→0.88.
- **Pink Institute**: library hover alpha, title/author/elapsed/total/percentage/input colors adjusted; `button_text` darkened; `dropdown_text` / `dropdown_time_text` updated.
- **Annihilation**: hover alpha 0.4→0.18, title/author/elapsed/total/percentage/input/dropdown colors adjusted, `curr_chap_highlight` shifted, `button_text` darkened.
- **Rose Code**: `panel_theme_names_dimmed` brightened.
- Tag color `amber` renamed to `lemon` with hex `#DEE84A` (was `#E8A84A`).

### Non-obvious decisions

1. **`_save_btn` hidden via `hide()` not QSS**: The save button's visibility is managed in Python (`show()`/`hide()`), not via a QSS rule. This avoids the `hasattr` guard complexity and keeps the logic local to `_on_tag_name_changed` and `_open_tag`.

2. **`_confirm_delete_label` is a separate widget, not `_rename_status`**: An earlier approach re-used `_rename_status` text for the confirmation prompt and tested the flag on second trash press. The new approach gives the confirmation its own visible, clickable widget so the action is spatially distinct from status text.

3. **`tag_dot_neutral_inline` vs `tag_dot_neutral`**: The detail dot and picker dots need a different fixed size (16×20) than list row dots (14×20). Separate objectNames let QSS target each group independently without fighting the fixed-size constraint set in Python.

---

# Session Summary — 2026-05-23 Standalone — Tags panel wiring and styling

## What changed

`TagManagerWidget` (previously embedded inside `StatsPanel`'s options tab) is now a first-class sliding panel, wired the same way as `StatsPanel`, `SleepTimerPanel`, etc.:

- `_build_tags_panel()` in `MainWindow` constructs it, connects `theme_applied`, hides it.
- `PanelManager` holds `tags_panel` / `tags_panel_animation` and owns `_open_tags_flow` / `_start_tags_entry` / `_close_tags_flow` / `_on_tags_hidden`.
- TAGS sidebar button added after STATS.
- `tag_changed` signal connected to `stats_panel._on_tag_changed` so book detail panel chips stay in sync.
- `get_tags_stylesheet()` added to `themes.py` — dedicated stylesheet, does not reuse `get_stats_stylesheet`.

### Non-obvious decisions

1. **`WA_StyledBackground` on root only**: `TagManagerWidget` sets `setAttribute(Qt.WA_StyledBackground, True)` on itself. Child containers (`_list_widget`, `_panel_widget`) must NOT set it — if they do, Qt paints their background independently (solid grey) and overwrites the parent's semi-transparent fill. Only the root needs it.

2. **No broad `QWidget { background: transparent }` rule**: Adding this to the stylesheet kills the root's `rgba(bg_main, panel_opacity_hover)` fill, making the panel invisible. Named selectors only (`QWidget#tag_manager_list`, `QScrollArea`).

3. **`_container` in `_TagBookGrid` needs explicit `setStyleSheet("background: transparent")`**: It's a plain `QWidget` inside a `QScrollArea`. Without the inline rule it paints the system palette's window color (grey) regardless of QSS scope.

4. **`settings_header` rule must be duplicated in `get_tags_stylesheet`**: The tags panel has its own stylesheet scope. Rules from `get_settings_stylesheet` or `get_stats_stylesheet` don't bleed in. Any object name styled there must be re-declared.

---

# Session Summary — 2026-05-22 (Session 3) — Tag filter + tag color feature

## What was built

### Tag chip filter (library context)

The header tag display (the `● tag` chips shown under the year in the book detail panel header, not the Tags tab chips) was converted to be clickable when the panel was opened from the library. Clicking a tag dismisses the panel, sets the library search field to `#tag`, and opens the library filtered to that tag.

#### Implementation path and failures (tag chip click)

**Attempt 1 — `mousePressEvent` on `lbl` (QLabel inside chip QWidget)**
Patched `lbl.mousePressEvent` directly. Didn't fire — the parent `chip` QWidget consumed the event before it reached the child label. QLabel is not the top-level hit surface inside a chip.

**Attempt 2 — `mousePressEvent` on `chip` (the QWidget)**
Moved the patch to `chip.mousePressEvent`. The Tags tab chips worked, but the header row uses `_rebuild_tag_display`, not `_rebuild_tag_chips`. Wrong target.

**Attempt 3 — FlowLayout of individual QLabels for header display**
Replaced the single `_tag_display_label` QLabel with a `FlowLayout` container of per-tag labels. Broke layout: tags lost centering, single tag went left, spacing was off. Reverted.

**Attempt 4 — coordinate hit-testing on the single centered QLabel**
Restored the single QLabel, monkey-patched `mousePressEvent` to map click X to a tag via `QFontMetrics.horizontalAdvance`. Wrong for word-wrapped, centered text — `horizontalAdvance` on the full string does not model Qt's actual line layout, so clicks were off by large amounts.

**Final solution — `QLabel.linkActivated`**
Set `setTextFormat(RichText)` and rendered each tag as `<a href="{tag}">...</a>` with inline color. Qt's own rich text engine does the hit-testing and fires `linkActivated(tag)` correctly. Connected `linkActivated` to `tag_filter_requested` signal. `setContextMenuPolicy(NoContextMenu)` added to suppress the "Copy link location" right-click menu that appears on rich text links.

#### Color restoration
Switching to RichText broke the QSS `color:` inheritance — Qt's HTML renderer does not resolve QSS color on the parent label. Fixed by injecting `accent_light` from `self._theme` directly into the `style="color:..."` attributes at render time. Two separate variables `dot_color` and `text_color` (both `accent_light` for now) serve as the per-tag dot color fallback when no color is set.

`_rebuild_tag_display` is called from `on_theme_changed` so live theme switches re-render correctly. Both library and stats contexts use RichText; links are only present in library context.

#### Context threading
`BookDetailPanel.load_book` gained a `context: str = ''` parameter. `self._context` is set as the first line. `PanelManager.open_book_detail` gained the same kwarg and passes it through — it is the sole funnel into `load_book`. The library call site (`_on_library_detail_requested`) passes `context='library'`; the stats call site (`stats_panel.py`) passes nothing (defaults to `''`). Tags tab chips (`_rebuild_tag_chips`) follow the same `self._context == 'library'` guard on their `chip.mousePressEvent`.

**Rule added to GEMINI.md:** `open_book_detail` takes a `context` kwarg; it must be passed correctly at each call site.

#### Signal and slot
- `tag_filter_requested = Signal(str)` on `BookDetailPanel`
- `_on_tag_filter_requested(tag)` in `app.py`: calls `_close_book_detail_flow()`, then `_open_library_flow()`, then `set_search(f"#{tag}")` — order matters (see tag filter state below)

#### Tag filter state management (library.py, panels.py, app.py)
After a tag chip click the library opens pre-filtered to `#tag`. The filter clears automatically on next manual open:

- `LibraryPanel._tag_filter_active: bool` flag
- `set_search(text)` sets the flag after `setText`
- `clear_tag_filter_if_active()` clears the search field and resets the flag if set
- `focusInEvent` on `search_field` monkey-patched to call `clear_tag_filter_if_active` on focus — clicking into the search box while a tag filter is active clears it and lets the user type
- `_open_library_flow` in `panels.py` calls `clear_tag_filter_if_active` first. Initially this fired before `set_search`, erasing what was just set. Fixed by reordering `_on_tag_filter_requested`: `_open_library_flow` runs before `set_search`, so the clear is a no-op (flag not yet set) and `set_search` runs after with flag clean

### `_id_for_path` on BookModel (library.py)

`set_playing_path` was resolving `book_id` via `path_to_index` (walks `_filtered`) then calling `.data(ROLE_BOOK)` — a roundabout path through a `QModelIndex` just to extract an ID. Replaced with `_id_for_path` which walks `_books` (the full unfiltered list) and returns `Optional[int]`. More direct and correct: a playing book may be filtered out of `_filtered` while still needing its ID tracked.

### Library cursor regression fix (library.py)

The `PointingHandCursor` on the time label in library rows was shown for all books regardless of whether they had progress. The cursor was set whenever the mouse was within `_time_label_rect`, which is a geometry-only method with no data access. Fixed by checking `has_progress` at the event filter call site before setting the cursor.

### Library time label hit rect (library.py)

`_time_label_rect` for grid/square modes used `hit_w = 66` (hardcoded pixels). This was too wide for the smaller fonts used in 2-per-row, 3-per-row, and Square modes, extending the hit zone over the elapsed time label. Fixed by building a `QFontMetrics` from the correct pixel size for the current mode (from `FONT_SIZES`) and measuring the worst-case string (`-00h 00m`). The 1-per-row mode retains its hardcoded geometry. `QFontMetrics` added to the `PySide6.QtGui` import.

### Tag color feature

#### DB layer (db.py)
- `tags` table added: `name TEXT PRIMARY KEY, color TEXT DEFAULT NULL`
- Migration on startup: `INSERT OR IGNORE INTO tags (name) SELECT DISTINCT tag FROM book_tags` — populates from existing tags, idempotent
- Migration also truncates both `book_tags.tag` and `tags.name` to 20 chars (down from 25)
- `add_book_tag` now inserts `INSERT OR IGNORE INTO tags (name) VALUES (?)` after the `book_tags` insert — ensures every new tag is registered at write time, not just at migration
- `get_all_tags()` updated: `LEFT JOIN tags t ON bt.tag = t.name`, returns `color` in each row dict
- `get_tag_color(tag) -> str | None` added
- `set_tag_color(tag, color_key | None)` added — upserts into `tags`

#### Palette (tag_manager.py)
`TAG_COLORS` dict at module level with 9 named color keys (`coral`, `peach`, `amber`, `lime`, `mint`, `sky`, `lavender`, `rose`, `white`). Neutral (no color key set) resolves to theme `accent_light` at render time.

#### Tag list rows (tag_manager.py)
`_make_tag_row` replaced with `_build_tag_row(tag_data: dict) -> QWidget`:
- Fixed height 36px
- Layout: colored dot (`●`) + tag name (stretch) + count badge
- Dot: `setStyleSheet(f"color: {color_hex}")` when color set; `objectName("tag_dot_neutral")` otherwise
- Count badge: `objectName("tag_count_badge")`, `setMinimumWidth(24)`

#### Tag detail panel (tag_manager.py)
- `_detail_dot` added to top_row (between back button and name edit): 20×20, clicking opens inline color picker
- `_color_picker_row`: hidden by default, contains neutral dot + one dot per `TAG_COLORS` entry; clicking any sets that color and hides the row
- `_toggle_color_picker()`, `_set_tag_color(color_key)`, `_update_detail_dot(color_key)` added
- `_open_tag()` now calls `get_tag_color(tag)` and `_update_detail_dot()` immediately after setting `_current_tag`

#### Book detail panel (book_detail_panel.py)
- `TAG_COLORS` imported from `tag_manager`
- `_rebuild_tag_chips()`: `tag_colors = {t: db.get_tag_color(t) for t in tags}` built once; each chip gets a colored dot (`objectName("tag_chip_dot")`) before the label
- `_rebuild_tag_display()`: same `tag_colors` dict built; dot color in both library and non-library branches resolves as `TAG_COLORS.get(tag_colors.get(t)) or dot_color` — per-tag color when set, theme accent fallback
- `setMaxLength` 25 → 20 on tag input field

#### Pending
- QSS for new object names (`tag_list_row`, `tag_list_name`, `tag_count_badge`, `tag_dot_neutral`, `tag_chip_dot`) not yet written

---

# Session Summary — 2026-05-22 (Session 2) — Weekly audit

## Findings

- **`terminate()` regression fixed**: `wait_for_shutdown()` was missing, restored. Confirmed as a python-mpv API method, not a custom implementation. The four-step sequence (store ref, clear `self.instance`, `terminate()`, `wait_for_shutdown()`) must be treated as atomic — no git trace of when it was dropped.
- **Upsert parity**: `upsert_book` and `upsert_books_batch` are in sync. All `CASE WHEN X_locked` guards present in both.
- **Signal connections**: No stale connections found. All invariants holding.
- **No regressions** in deferred areas (VT, CUE, chapter nav, cover loading).
- **`refresh_books()`**: Has three callers — not dead code.
- **`path_to_index()`**: Confirmed in `library.py` (`LibraryPanel`, line ~856), not `book_model.py`.
- **Sleep + session recording**: Sleep feature also prevents session recording during the sleep window (same deferred bucket as VT session gaps). Both deferred until single large MP3 handling is resolved.

---

# Session Summary — 2026-05-22 (Session 1)

## What was built: Tag manager thumbnail grid resize and remove stability

### Changes

- **`_TagBookThumb`**: 80×80 → 48×48. Both `setFixedSize` calls (widget and `_cover` label) updated. Scaling changed from `KeepAspectRatio` to crop-to-square (`KeepAspectRatioByExpanding` + `.copy()`) in both pixmap paths: placeholder load and `_apply_cover`.
- **`_TagBookGrid`**: `_cols` 3 → 5. Height clamp (`setMinimumHeight`/`setMaximumHeight`) removed from both `_rebuild` and `_on_remove` — scroll area handles height automatically via `setWidgetResizable(True)`. `setVerticalScrollBarPolicy(ScrollBarAlwaysOff)` added — vertical scrollbar was appearing and stealing ~10px viewport width, clipping the 5th column. `setColumnStretch(_cols, 1)` added for left-alignment. Stretch row added at end of `_rebuild` and `_on_remove` via `setRowStretch(rowCount(), 1)`.
- **`_on_remove`**: Simplified — the hide/show reflow loop replaced with a single `self._rebuild()` call. Safe because `_cover_cache` is a shared reference with the library panel; cache hits are synchronous and inline, so no cover flicker on rebuild.
- **`stats_panel.py` line 1206**: Right margin 10 → 0 in `_build_options_tab` layout. The 10px right margin was clipping the 5th grid column by consuming width before it reached `_TagBookGrid`. Left margin 10 → 6 separately to match the 6px from tag list row content padding.
- **`TagManagerWidget.refresh()`**: Re-calls `_open_tag(self._current_tag)` after rebuilding the tag list, if a tag was selected. Fixes the case where tagging a book from `BookDetailPanel` (which triggers `refresh()` via `tags_changed` → `_on_tag_changed`) left the open tag panel showing stale book count and grid.

---

# Session Summary — 2026-05-21

## What was built: SVG playback control icons with per-theme color baking

### Overview

All five playback buttons (prev, rewind, play/pause/restart, forward, next) replaced text labels with SVG icons. Icons are colored at load time by substituting fill/stroke values in the SVG source — PySide6 does not honor `currentColor` in SVGs rendered via `QSvgRenderer`, so there is no runtime CSS hook; color must be baked into the pixmap.

### `_load_svg_icon(name, color="white")` (app.py)

- Reads SVG as text, applies four regex substitutions before rendering:
  - `fill="..."` attribute (XML) — skips `fill="none"`
  - `stroke="..."` attribute (XML) — skips `stroke="none"`
  - `fill:...` inside `style="..."` (Inkscape inline CSS) — skips `fill:none`
  - `stroke:...` inside `style="..."` (Inkscape inline CSS) — skips `stroke:none`
- The `style=` passes were added specifically for `restart.svg`, which Inkscape exported with `style="fill:#030303;stroke:#000000"` on the `<path>` element. The attribute-level regexes never touched it, leaving it black regardless of theme.
- Renders via `QSvgRenderer` into a `QPixmap` sized to `renderer.defaultSize()` — preserves SVG's native aspect ratio so `setIconSize` scaling is correct.
- Falls back to `QIcon()` (null) on any exception; call sites check `isNull()` and fall back to text.

### `QSS color: does not work for icons`

The first attempt added per-button `#play_pause_btn { color: ... }` rules to `get_player_stylesheet()`. This is wrong for two independent reasons:
1. Qt's `color:` CSS property does not colorize `QIcon` pixmaps — it only affects text rendering. Icon pixels are painted as-is from the stored pixmap.
2. Even if `color:` worked, the SVGs had hardcoded `fill="white"` (or `fill:#030303` for restart), so the SVG source itself would still render the wrong color regardless of any stylesheet rule.

### Theme key fallback chain (themes.py)

- `button_play` → color for play/pause/restart button. Falls back: `button_text` → `text_on_light_bg` → `text`.
- `button_skip` → color for rewind/forward. Falls back to `button_play`.
- `button_chapter` → color for prev/next chapter. Falls back to `button_play`.
- Resolved in `_reload_button_icons()`, not in `get_player_stylesheet()` — the QSS variables were removed after it became clear they were inert.

### `_reload_button_icons(theme_name)` (app.py)

- Called from `ThemeManager._apply_stylesheets()` on every theme change, and explicitly after button construction at init time.
- Rebuilds `_icon_play`, `_icon_pause`, `_icon_restart`, `_icon_rewind` dict, `_icon_forward` dict with the resolved theme colors.
- Guarded with `if not hasattr(self, 'play_pause_button'): return` — `_apply_stylesheets` is called early in `__init__` before the controls are built.
- **Init ordering trap:** `_apply_stylesheets` at line ~520 fires before the playback buttons are created at line ~660. Initial icon load must therefore happen explicitly via `_reload_button_icons(theme_name)` immediately after button construction — not from `_apply_stylesheets`. The guard makes the early call a no-op.

### Skip icon switching (app.py, speed_controls.py)

- `_icon_rewind` / `_icon_forward` are dicts keyed by seconds: `{5: QIcon, 10: QIcon, 30: QIcon}`. 15s falls back to the 10s icon via `.get(skip, self._icon_rewind[10])`.
- `_update_skip_icons()` reads `config.get_skip_duration()` and sets the correct icon on both buttons.
- `SpeedControlsPanel.skip_duration_changed = Signal(int)` added; emitted from `_update_skip_mode`. Connected in `app.py` to `lambda _: self._update_skip_icons()`.

### Button sizes

| Button | `setFixedSize` | `setIconSize` |
|---|---|---|
| prev / next | 46×33 | 32×22 |
| rewind / forward | 46×33 | 28×17 |
| play/pause/restart | 56×33 | 52×33 |

### Null fallback text

If `QIcon.isNull()` (file missing or load error):

| Button | Fallback text |
|---|---|
| play | "Play" |
| pause | "Pause" |
| restart | "Restart" |
| rewind | "<<" |
| forward | ">>" |
| prev | "\|<" |
| next | ">\|" |

`_set_play_icon()` always calls `setText("")` when setting a valid icon, so stale text never persists after icons load successfully.

---

# Session Summary — 2026-05-20 (Session 2)

## What was built: Archived book UI, narrator/year library sync, year validator, tag manager refresh wiring

### Narrator and year not syncing to library view (library.py, book_detail_panel.py)

- `metadata_saved` signal was `Signal(int, str, str)` — only carried `book_id`, `title`, `author`. Narrator and year were saved to DB but never pushed to the in-memory `Book` objects in `BookModel`.
- Signal widened to `Signal(int, str, str, str, object)` — now emits `(book_id, title, author, narrator, year_int)`.
- `BookModel.update_book_metadata` extended to accept and set `narrator` and `year` on the matched book object.
- `_on_book_metadata_saved` in `app.py` updated to match new signature.
- `year_int` computation hoisted before the DB call to avoid duplication between `_book_data.update` and the emit.

### Year field input validation (book_detail_panel.py)

- `QRegularExpressionValidator(QRegularExpression(r'^-?\d*$'))` attached to `_year_label` at construction — blocks all non-digit, non-minus input at the keystroke level.
- Scanner's `_parse_year` already sanitizes at the read path (4-digit range check) — no change needed there.

### `get_book_dict` (db.py)

- New method `get_book_dict(book_path)` — `SELECT * FROM books WHERE path = ?`, returns `dict(row)` or `None`. Raw row including `is_deleted` and `is_excluded`, no `Book` dataclass mapping.
- Needed because `get_book()` returns a `Book` object and `Book` does not carry `is_deleted`/`is_excluded`.

### `is_deleted` and `is_excluded` added to stats queries (db.py)

- `get_daily_book_breakdown`, `get_books_listened_in_period`, `get_finished_in_period`, `get_recently_finished`, and `get_books_by_tag` all extended to return `b.is_deleted, b.is_excluded` in their SELECT.

### Archived book UI in BookDetailPanel (book_detail_panel.py)

- `_is_archived` detection replaced: was `self.db.is_book_excluded(path)` (excluded-only). Now uses `get_book_dict` — true if row is missing (`is_deleted` via location removal), or either flag is set.
- `_is_archived` block moved to execute before the cover pixmap block in `load_book()` — ordering bug: original had it after, causing stale non-grayscale cover on first open.
- `_apply_cover(pixmap)` added — single method for cover scaling/display. Calls `to_grayscale(pixmap)` when `_is_archived`. Replaces duplicated inline scaling in both `load_book` and `_refresh_header_cover`.
- `to_grayscale` imported from `cover_loader.py`.
- `_remove_btn` hidden for all archived states (previously hidden only for `is_excluded`; now also hidden for `is_deleted`).

### Archived book UI in stats widgets (stats_panel.py, tag_manager.py)

- `BookDayRow`, `FinishedBookThumb`, `_TagBookThumb` all unified to use `to_grayscale()` from `cover_loader.py` — removed inline `convertToFormat(Format_Grayscale8)` which drops alpha.
- `_is_archived` computed from `is_deleted`, `is_excluded`, and `book_path is None` in all three widgets.
- `BookDayRow._deleted` field replaced by `_is_archived`.

### Tag manager refresh wiring (tag_manager.py, app.py, library_controller.py)

- `TagManagerWidget.refresh_books()` added — calls `_open_tag(self._current_tag)` if a tag is currently shown, re-fetching books from DB.
- `AppInterface.refresh_tag_manager()` and `AppInterface.refresh_stats()` added — thin proxies to `stats_panel._tag_manager.refresh_books()` and `stats_panel.refresh_current_tab()` respectively. Required because `self.app` in `library_controller.py` is `AppInterface`, not the main app object.
- `_on_book_detail_removed` in `app.py` now calls `refresh_books()` and `refresh_current_tab()` after library refresh — stats tab data and tag grid update immediately on book removal.
- `_on_scan_finished` in `library_controller.py` now calls `refresh_tag_manager()` and `refresh_stats()` after panel refresh — path removal updates propagate to tag manager.
- `_on_active_cover_changed` in `app.py` now calls `stats_panel._tag_manager.refresh_books()` at the end — cover change in detail panel reflects in tag manager immediately.

### Deferred to Session 7

- **Deleted-book Stats UI** — visual differentiation (monochrome cover, read-only metadata, hidden Cover+Tags tabs) remains incomplete in BookDetailPanel for the full deleted-book case.
- **`to_grayscale` alpha channel** — `Format_Grayscale8` drops alpha; transparent placeholder pixels become black. Fix: composite onto themed background before converting. Defer until app icon is finalized.
- **Main player layout broken states** — no book loaded, no library folders.
- **Rescan selected path only** — partial scan overhaul deferred.

---

# Session Summary — 2026-05-20

## What was built: Library view duration regression fix, hand cursor on duration toggles, stats panel cover fix, auto-select first cover for no-cover books

### Library view duration regression fix (library.py)

- `_resolve_playback` in `BookDelegate` was applying per-book speed to `dur_disp` regardless of whether the book had progress.
- Fix: when `has_progress` is `False`, speed is forced to `1.0` and `dur_disp` equals `dur`. Books with no progress always show total duration at 1x; per-book speed has no effect on the displayed duration.
- **Invariant:** speed is only applied when `has_progress` is `True` — do not remove this gate.

### Hand cursor on duration toggles (app.py, library.py)

- **Main player:** `setCursor(Qt.PointingHandCursor)` added to `self.total_time_label` and `self.chap_duration_label` during construction in `_build_secondary_controls` in `app.py`.
- **Library view:** `eventFilter` on `self._list_view.viewport()` extended in `LibraryPanel` to handle `MouseMove` — calls `delegate._time_label_rect(option, index)` and sets `PointingHandCursor` when mouse is within that rect, `ArrowCursor` otherwise. Leave event resets to `ArrowCursor`.

### Stats panel cover fix (stats_panel.py, book_detail_panel.py, tag_manager.py, app.py)

- **Root cause:** `BookDayRow`, `FinishedBookThumb`, and `_TagBookThumb` were constructing `CoverLoaderWorker` with `book.cover_path` from the `books` table (scanner thumbnail) instead of the user-selected active cover from `book_covers`.
- **Fix:** `StatsPanel._inject_active_covers()` added — walks a list of row dicts, calls `db.get_active_cover_path(book_path)` per row, injects result as `"active_cover_path"` key. Called before constructing `BookDayRow`/`FinishedBookThumb` in all four tab refresh methods (Overall, Day, Week, Month).
- `TagManagerWidget._inject_active_covers()` added — same pattern, keyed on `path` instead of `book_path`. Called in `_open_tag` before passing books to `_book_grid.set_books()`.
- `BookDayRow` and `FinishedBookThumb` now read `active_cover_path` from `row_data` and pass it as override to `CoverLoaderWorker`. Fallback to scanner `cover_path` if `active_cover_path` is absent.
- `_TagBookThumb` updated identically — reads `active_cover_path`, passes to `CoverLoaderWorker`.
- `refresh_cover()` added to `BookDayRow` and `FinishedBookThumb` — invalidates `_cover_cache` entry, re-triggers worker with `active_cover_path=cover_path`. When `cover_path` is empty (last cover removed), immediately restores placeholder icon without spawning a worker.
- `FinishedBookThumb.__init__` now stores `self._assets_dir` (was missing; required by `refresh_cover`).
- `active_cover_changed` signal on `BookDetailPanel` changed from `Signal(str)` to `Signal(str, str)` — now emits `(book_path, cover_path)`. Intermediate slot `_on_cover_panel_changed` added to bridge `CoverPanel.active_cover_changed` (single-arg) and re-emit with `self._book_path`.
- `_on_active_cover_changed` in `app.py` updated to match new `(book_path, cover_path)` signature — no longer reads `book_detail_panel._book_path` from outside.
- `StatsPanel.on_cover_changed(book_path, cover_path)` added — walks only the visible tab's rows via `_iter_day_rows` and `_iter_finished_thumbs`, calls `refresh_cover` on matching widgets only. No tab rebuild.

### Auto-select first cover for no-cover books (cover_panel.py)

- When a cover is added and `_covers` was empty before the add (i.e. the book had absolutely no covers — no embedded, no user), the new cover is automatically set as active, shown in the preview, and `active_cover_changed` is emitted.
- Condition: `had_no_covers = len(self._covers) == 0` captured before the append. Books with an embedded locked cover always have at least one entry in `_covers` at load time and are never affected.
- "Rinse and repeat" behavior: if all user covers are deleted (returning to zero), the next add triggers auto-select again.
- Subsequent covers added to a book that already has one are not auto-selected.

### Deferred to Session 7

- **Deleted-book Stats UI** — stats panel shows sessions and history for excluded/deleted books. No visual differentiation, duration label not clickable. Cover monochrome, metadata read-only, Cover+Tags tabs hidden.
- **Main player layout broken states** — no book loaded, no library folders.
- **Rescan selected path only** — partial scan overhaul deferred.

---

# Session Summary — 2026-05-19

## What was built: Metadata lock feature, duration label cursor fix, path_to_index bug fix

### Schema and DB (db.py)

- Added four columns to `books` table via ad-hoc migration: `title_locked`, `author_locked`, `narrator_locked`, `year_locked` (all `INTEGER NOT NULL DEFAULT 0`).
- Migration pattern: `if "col_name" not in col_names: ALTER TABLE` — checks for duplicates before adding.
- New methods: `set_metadata_locks(path, **locks)` (saves lock dict), `get_metadata_locks(path)` (returns lock dict).
- Both `upsert_book` and `upsert_books_batch` updated with `CASE WHEN books.X_locked = 1 THEN excluded.X ELSE updated.X END` guards for all four fields. Narrator and year preserve existing `COALESCE(NULLIF(...), ...)` guards inside the ELSE branch.
- Upsert ON CONFLICT block resets all four locks to 0 on rescan (alongside `is_deleted` and `is_excluded` reset) — rescanning a book with user edits will overwrite if locks aren't set.
- **Invariant:** upsert_book and upsert_books_batch must stay in sync. Any schema or logic change in one must be applied to the other.

### Metadata lock UI (book_detail_panel.py, themes.py)

- Replaced `self._save_label` with unified `self._meta_action_btn` — single `QToolButton` (24×24, objectName `metadata_action_btn`), positioned in `right_col` below close button.
- `_MetaActionState` enum (HIDDEN, DIRTY, LOCKED, UNLOCKED) drives all button appearance and behavior:
  - HIDDEN: button invisible, no icon
  - DIRTY: save icon at 0.6 opacity; click → `_on_inline_save()`
  - LOCKED: lock icon at 0.6 opacity; click → clear all locks, emit UNLOCKED state
  - UNLOCKED: lock-open icon at 0.6 opacity; auto-transitions to HIDDEN after 2.5s via `QTimer.singleShot(2500)`
- Hover effect: all non-HIDDEN states show icon at full 1.0 opacity on Enter, revert to 0.6 on Leave (via eventFilter).
- Lock state determined per-field on save in `_commit_inline_save()` — if field text changed, set lock to True. On unlock, clear all four at once.
- `_is_archived` guard: if `is_book_excluded()`, always force state to HIDDEN regardless of lock state.
- Pre-edit state saved in `_enter_edit_mode()`, restored on dismiss via `_exit_edit_mode(save=False)` — clicking outside reverts button to pre-edit state.
- Icons: `lock.svg` and `lock-open.svg` (developmentseed/collecticons), `save.svg` (Font Awesome) in `assets/icons/`.

### SVG icon rendering (_load_svg_icon in book_detail_panel.py)

- Module-level helper cached via `@functools.lru_cache(maxsize=32)` with cache key `(svg_path, color, size, opacity)`.
- Replaces both `stroke="#000000"` and `fill="#000000"` with provided color for compatibility with both stroke-based (e.g. trash icon) and fill-based (e.g. lock icon) SVGs.
- For SVGs with neither explicit stroke nor fill (e.g. Font Awesome), injects a CSS `<style>path { fill: {color}; }</style>` rule — but only if the SVG has no stroke replacements (to avoid interfering with stroke-only icons).
- Opacity parameter applied via `painter.setOpacity()` before rendering.

### Duration label cursor fix (_update_duration_label, _toggle_duration in book_detail_panel.py)

- Both methods now use `config.get_book_speed(self._book_path)` with fallback to `config.get_default_speed()`.
- Speed comparison uses tolerance `abs(speed - 1.0) < 1e-9` to handle floating-point rounding errors (e.g. 1.0000000000000053).
- Cursor and toggle disabled (arrow cursor, no-op on click) when speed is effectively 1x.
- Prevents misleading UI when default speed (2.0x) is applied but not yet saved to config.

### BookModel.path_to_index bug fix (library.py)

- `BookModel.path_to_index()` now walks `self._books` instead of `self._filtered`.
- Previous behavior: filtered-out books returned `None`, leaving `_playing_id` unset, causing incorrect pruning in `set_books()`.
- New behavior: correct row index returned regardless of filter state, so `set_playing_path()` correctly sets `_playing_id`.

### Deferred to Session 6

- **Deleted-book Stats UI** — stats panel shows sessions and history for excluded/deleted books. No visual differentiation, duration label not clickable. Cover monochrome, metadata read-only, Cover+Tags tabs hidden.
- **Main player layout broken states** — no book loaded, no library folders.
- **Rescan selected path only** — partial scan overhaul deferred.

---

# Session Summary — 2026-05-18

## What was built: Book removal (is_excluded), trash button, inline confirmation UI

### Schema and DB (db.py)

- Added `is_excluded INTEGER NOT NULL DEFAULT 0` to the `books` CREATE TABLE statement.
- Migration added alongside the existing `is_deleted` migration — same PRAGMA pattern, safe for existing DBs.
- `get_all_books` WHERE clause updated to `is_deleted = 0 AND is_excluded = 0`.
- Both `upsert_book` and `upsert_books_batch` ON CONFLICT blocks now reset `is_excluded = 0` alongside `is_deleted = 0` — re-scanning a removed book resurfaces it automatically.
- New methods: `set_book_excluded(path, excluded)` and `is_book_excluded(path)`.
- `is_excluded` is additive and independent from `is_deleted`. Stats queries intentionally left unchanged — history and progress are preserved on exclusion.

**Key invariant:** The scanner passes `None` for `progress`, not `0.0`. The `COALESCE(NULLIF(excluded.progress, 0.0), books.progress)` in both upserts is a safety net, not a contract. Passing `0.0` from the scanner would overwrite saved progress — this was an existing rule, reconfirmed this session.

### Trash button (book_detail_panel.py, themes.py)

- `QToolButton` (`remove_book_btn`, 24×24, transparent background) added to `right_col` in `BookDetailPanel._build_ui` — bottom-right of the header, mirroring the close button at top-right.
- SVG icon loaded via `_load_svg_icon()` module-level helper: reads `assets/icons/trash.svg`, replaces `stroke="#000000"` with the desired color, renders via `QSvgRenderer` into a `QPixmap`. Supports an `opacity` float parameter (used for the idle state at 60%).
- Idle color: `accent` at 60% opacity via `painter.setOpacity(0.60)`. Hover: solid `#cc3333`. Enter/Leave handled in the existing `eventFilter` — `obj is self._remove_btn` branch returns `False` (does not consume events).
- `book_removed = Signal()` added to `BookDetailPanel`.
- `_remove_btn` hidden (`setVisible(False)`) when `is_book_excluded()` is True at `load_book` time — prevents showing the button for a book already excluded (e.g. opened from stats history).

### Inline confirmation (book_detail_panel.py, themes.py)

Replaced the system `QMessageBox` with an inline `_ClickableLabel`:

- `_confirm_remove_label = _ClickableLabel("Click to remove from library")`, object name `book_detail_confirm_remove`, right-aligned, hidden by default.
- Positioned in `dur_save_row` to the right of the stretch, between `_save_label` and the trash button column.
- `_on_remove_clicked`: if not already confirming, sets `_confirming_remove = True`, hides `_duration_label`, shows `_confirm_remove_label`.
- `_on_confirm_remove`: calls `db.set_book_excluded`, then `_cancel_remove()`, then emits `book_removed`.
- `_cancel_remove`: restores `_duration_label`, hides `_confirm_remove_label`, resets flag.
- Click-outside dismissal: `eventFilter` MouseButtonPress branch checks `_confirming_remove` — if the click lands outside `(_confirm_remove_label, _remove_btn)`, calls `_cancel_remove()`. Returns `False` so clicks are not swallowed.
- `_cancel_remove()` also called from `_on_close_clicked` and `hideEvent` so the confirmation never persists across panel close or hide.
- QSS for `QLabel#book_detail_confirm_remove` added to `get_stats_stylesheet()` in `themes.py`: `font-size: 14px`, `color: accent`, `border: 2px solid accent`, `background: rgba(bg_main, panel_opacity_hover)`, `padding: 0px 4px`. No inline `setStyleSheet` on the widget.

### Signal wiring (app.py)

- `book_removed` connected to `_on_book_detail_removed` in `_build_book_detail_panel`.
- `_on_book_detail_removed`: reads `book_detail_panel._book_path`, closes the panel via `panel_manager._close_book_detail_flow()`, refreshes the library via `library_panel.refresh(force=True)`, and conditionally calls `_on_book_removed()` if the removed book was the currently playing one.
- `_on_book_removed` itself is unchanged.

### Deferred this session

- **Metadata lock feature** — designed: new `is_metadata_locked` column, lock icon in book detail header, `upsert_book` CASE logic to skip title/author/narrator/year update when locked. Schema and upsert SQL drafted. Deferred — not started in code.
- **Rescan selected path only** — requested, deferred to partial scan overhaul. Current scanner always does a full location scan.
- **Deleted-book Stats UI** — stats panel shows sessions and history for excluded/deleted books (via listening_sessions join). No visual differentiation currently. Duration label not clickable for books no longer in the library. Carry to next session.

### Still open

- `path_to_index()` in `ui/library.py` walks `self._filtered`, not `self._books` — books filtered out of the view return `None`, leaving `_playing_id` unset. Documented in CLAUDE.md under "FIX NEEDED". Not touched this session.
- Main player layout broken states — not touched this session.

---

# Session Summary — 2026-05-17

## Features / fixes shipped

### Soft-delete for books (`is_deleted`)

Books are no longer hard-deleted when a scan location is removed. `remove_scan_location` now does `UPDATE books SET is_deleted = 1 WHERE path LIKE ?` instead of `DELETE`. All rows, progress, covers, `book_files`, and session history survive. Re-adding the location resurrects the book instantly via the upsert `ON CONFLICT DO UPDATE SET is_deleted = 0` clause.

`get_all_books` filters with `WHERE is_deleted = 0` — the library view sees only live books. Stats queries are not filtered (they are keyed by `book_path`/`book_title`, not joined to books).

**Files:** `db.py` — schema, migration, `remove_scan_location`, `upsert_book`, `upsert_books_batch`, `get_all_books`

### Progress preservation on re-add / rescan

Two compounding bugs caused progress to show as zero after a book was re-added:

1. **Hard deletes destroyed the DB row.** Config held the last position as a fallback, but it only synced back to DB after a manual book load via `_restore_position`. Fixed by the soft-delete above.

2. **Scanner sends `0.0`, not `NULL`, for progress.** The existing `COALESCE(excluded.progress, books.progress)` treated `0.0` as a real value and overwrote saved progress. Fixed by wrapping with `NULLIF`: `COALESCE(NULLIF(excluded.progress, 0.0), books.progress)`.

**Residual:** Any book whose row was created during a hard-delete cycle (before this commit) will still require one manual load to sync config→DB via `_restore_position`. New cycles are clean.

**Files:** `db.py` — `upsert_book`, `upsert_books_batch`

### Post-scan library refresh without scroll reset

`LibraryPanel.refresh()` now syncs the model's filter/sort state directly from UI widgets (`_filter_text`, `_sort_field`, `_sort_direction`) before calling `set_books()`, replacing the old `_apply_current_sort_filter()` call which triggered a second `beginResetModel`. Gemini also added `BookModel.set_books()` pruning of `_live_pos`/`_live_dur` to retain only the playing book's entry across refreshes, and `update_playing_progress` now maintains `_playing_id` on the model so `set_books` can prune correctly without a window traversal.

**Files:** `ui/library.py` — `LibraryPanel.refresh`, `BookModel.set_books`, `BookModel.update_playing_progress`, `BookModel.__init__`, `LibraryPanel.set_playing_path`

### `_held_play` AttributeError fix

`Player._held_play` was assigned inside `load_book()` (not in `__init__`), so `ungate_play()` raised `AttributeError` if called before any book had been loaded — e.g., on app start when the library panel is hidden. Fixed by moving initialization to `__init__` alongside the other VT state attributes. The redundant assignment in `load_book()` was removed.

**Files:** `player.py` — `__init__`, `load_book`

## Known debt added this session

- `path_to_index()` in `BookModel` walks `self._filtered`, not `self._books`. If a book is currently filtered out of the view when playback starts, `_playing_id` will be set to `None` and `_live_pos`/`_live_dur` pruning at next `set_books` will discard live progress data for it. Not yet fixed — needs `_books` walk, not `_filtered`.


# Session Summary — 2026-05-16 (session 3)

## Chapter navigation drift, CUE file support, teardown crash

### Chapter boundary drift — root cause

All chapter navigation bugs shared the same root cause: mpv seeks with a bias toward not missing a frame, undershooting chapter boundaries by ~23ms. The chapter property observer is async and unreliable at boundaries, especially while paused. The epsilon system (`_CHAPTER_BOUNDARY_EPSILON = 0.35`) compensates for this throughout the codebase — in chapter walks, restore, and all boundary seeks. Moving the epsilon to write time was considered but rejected: testing showed the saved position itself can already be inside the wrong chapter's territory in mpv's representation, so the epsilon must live at read/seek time.

### next_chapter non-VT used `self.chapter = N`

Native mpv chapter assignment, same drift issue. Replaced with `chapter_list` walk + `seek_async(target + _CHAPTER_BOUNDARY_EPSILON)` mirroring VT branch. Missing `return target` statements in both branches also caused Undo after Next to silently fail — fixed.

### previous_chapter non-VT "go to previous" case used `self.chapter = N-1`

Same fix. The "restart current chapter" case already used `seek_async` correctly.

### Chapter label not updating after seek while paused

mpv fires the `time-pos` observer once after a seek while paused, then goes silent. The single callback is unreliable — can fire at an intermediate position before the seek fully lands. Three observer-based approaches failed. Fix: `seek_async` non-VT now immediately sets `_cached_time_pos = pos` and emits `chapter_changed` with the derived chapter index synchronously. `_on_time_pos_change` also has a non-VT walk block (`_last_nonvt_chapter`) for natural playback transitions, mirroring VT.

### `_on_chapter_change` racing with `seek_async` emit

mpv's native chapter observer was firing with stale index after seek, overwriting the correct chapter. Added `_is_seeking` guard and `_chapter_list is not None` guard (cue mode) to `_on_chapter_change`.

### "Opening Credits" flash on app start

mpv's `chapter=0` observer callback fired before `_on_file_ready` could call `seek_async`. Fixed by setting `_is_seeking = True` in `load_book` at file load time.

### Player.terminate() teardown crash

libmpv's internal threads (`avformat_close_input`) were still running while Qt destroyed objects. Crash was masked by a `print()` in `_on_end_file` keeping the thread alive. Fix: store instance reference, clear `self.instance`, call `terminate()` then `wait_for_shutdown()`. Discovered via git bisect after removing debug prints.

### CUE file support added

Single-file M4B/M4A only. VT books excluded — cue alignment with individual MP3 files is too fragile. Global setting in Library tab: "Embedded" (default) | ".cue". Stored in config via `chapter_list_source`. New `chapter_source TEXT DEFAULT 'embedded'` column on books table.

Detection in `_resolve_playlist` worker thread: one cue file → use it; multiple → match stem against folder name pattern `Artist - Title`; no match → fallback. `_parse_cue` validates: FILE stem matches audio file (handles UTF-8 BOM via `utf-8-sig`), first timestamp is `0.0`, timestamps strictly increasing, all timestamps within file duration (from DB, skipped if unavailable). Fewer than 2 tracks → reject. `_chapter_list` populated from cue; `_virtual_timeline` stays `None`.

When cue active, `_on_chapter_change` suppressed (`_chapter_list is not None` guard). Chapter list clicks use `seek_async(target + epsilon)` instead of `self.player.chapter = idx`. `seek_within_chapter` non-VT uses position-based walk instead of `self.chapter`.

Silent fallback on invalid cue — no banner. mpv embedded chapters used without notification.

**Files:** `player.py` — `_resolve_playlist`, `_select_cue_file`, `_parse_cue`, `_get_chapter_source_setting`, `seek_within_chapter`; `ui/chapter_list.py` — `_activate_item`; `db.py` — books table schema; `config.py` — `get/set_chapter_list_source`; `app.py` — `_build_library_tab`, `VisualsInterface`, `MainWindow` signal; `settings_controller.py` — `_update_chapter_list_source`

---


# Session Summary — 2026-05-16 (session 2)

## Chapter navigation boundary drift — root cause and fixes

All chapter navigation bugs shared the same root cause: mpv's seek precision and chapter property observer are unreliable at chapter boundaries. mpv is a video player — it biases toward not missing a frame, so seeks can undershoot by ~23ms. At chapter boundaries this lands in the wrong chapter. The chapter property observer is async and can fire with stale or intermediate values, especially while paused.

### Fixes applied

**next_chapter / previous_chapter non-VT:** Were using `self.chapter = N` (native mpv property assignment). Replaced with `seek_async(target + _CHAPTER_BOUNDARY_EPSILON)` mirroring the VT branch. `_CHAPTER_BOUNDARY_EPSILON = 0.35` is the tolerance needed to clear mpv's float drift window — it appears in the chapter walk, restore, and all chapter seeks for this reason.

**_restore_position non-VT:** Was using raw saved position. Changed to `seek_async(progress + _CHAPTER_BOUNDARY_EPSILON)`. Trade-off: restores 0.35s later than saved. Accepted — imperceptible in practice, confirmed by testing.

**seek_async non-VT:** Now immediately sets `_cached_time_pos = pos` and emits `chapter_changed` with the derived chapter index. Necessary because mpv fires the time-pos observer only once after a seek while paused, and that single callback is unreliable — it can fire at an intermediate position and go silent before the seek fully lands.

**_on_time_pos_change non-VT branch:** Now walks `chapter_list` and emits `chapter_changed` when the chapter index changes, mirroring the VT path. Tracks last emitted index via `_last_nonvt_chapter`. Handles natural chapter transitions during playback correctly.

**_on_chapter_change guard:** Now returns early if `_is_seeking` is True. Without this, mpv's native observer races with the `seek_async` emit and overwrites the correct chapter with a stale value.

**_is_seeking set at file load time:** Now set to True in `load_book`, suppressing spurious chapter observer callbacks during initial load before `_restore_position` runs. Previously caused an "Opening Credits" flash because mpv's chapter=0 callback fired before `_on_file_ready` could call `seek_async`.

**Player.terminate():** Now stores the instance reference, clears `self.instance` first, then calls `terminate()` followed by `wait_for_shutdown()`. Prevents a teardown race where libmpv's internal threads (`avformat_close_input`) were still running while Qt was destroying objects. The crash was masked for an unknown period by a `print()` in `_on_end_file` keeping the thread alive long enough for cleanup to complete.

### Known remaining issues

- **Undo after Next:** Undo button does not show. Undo after Prev causes chapter slider drift when restoring to chapter start. Root cause is same boundary drift — undo target is at a chapter boundary and restore lands in the wrong chapter. Deferred.
- **Chapter slider drift on Prev:** Intermittently shows slider at far right after navigation. Not reliably reproducible. Suspected same boundary/race cause. Monitor.
- **apply_smart_rewind and Undo restore:** Still use `time_pos =` assignment in some paths — not yet audited for boundary drift. Needs testing near chapter starts.

**Files:** `player.py` — `next_chapter`, `previous_chapter`, `seek_async`, `_on_time_pos_change`, `_on_chapter_change`, `load_book`, `terminate`


# Session Summary — 2026-05-16 (session 1)

## M4B chapter navigation bug fixes

### Bug: Prev while paused jumps to N-1 instead of restarting N — RESOLVED

**Root cause (two parts):**

1. `previous_chapter()` non-VT identified the current chapter via `self.chapter or 0` (mpv's async property), which can be stale when paused. Fixed by replacing with a walk of `chapter_list` against `time_pos + 0.35`, matching the VT and display paths.

2. The "restart current chapter" case used `self.time_pos = chap_start` (default seek mode). Default seek undershoots by one AAC frame (~23ms). When paused, playback never advances past the boundary — mpv correctly keeps reporting N-1. When playing, the undershoot was masked because forward playback crossed the boundary in the same timer tick. Fixed: `seek_async(chap_start + 0.35)` — uses `absolute+exact` AND the +0.35 epsilon clears the ~0.25s float drift in M4B chapter metadata.

**Files:** `player.py` — `previous_chapter()`

---

### Bug: Chapter slider shows stale fill after Prev/Next — RESOLVED

**Root cause:** Time labels in `_sync_chapter_ui` update without an `is_seeking` guard; slider `setValue` was gated on `not is_seeking`. For `self.chapter = N` seeks (chapter nav), `_seek_target` is never set, so `_is_seeking` clears on the first `_on_time_pos_change` callback — before the seek completes. Race: the 200ms timer fires, the label shows "00:00" (correct), but the slider retains the stale near-full value from the previous chapter. Attempting `setValue(0)` in `handle_prev`/`handle_next` made it worse — it was overwritten once the race resolved.

**Fix:** Removed `setValue(0)` from `handle_prev`/`handle_next`. Removed `not self.player.is_seeking` from the chapter slider's `setValue` condition in `_sync_chapter_ui`. The `chap_animating` guard (the architecturally protected one) is unchanged. The chapter slider now updates every 200ms unconditionally and self-corrects within one tick of the seek completing.

**Files:** `app.py` — `handle_prev`, `handle_next`, `_sync_chapter_ui`

---

### Bug: Book load shows end of N-1 instead of start of N — RESOLVED

**Root cause:** `_restore_position` for non-VT used `self.player.time_pos = book_data.progress` (default seek mode). When saved position was at chapter N's start, the one-frame undershoot (~23ms for AAC at 44.1kHz) landed before the chapter boundary. mpv correctly reported N-1 for that sub-boundary position.

**Three chapter-signal approaches failed — do not retry:**

- **Timer correction in `_sync_chapter_ui`:** Tracked `_last_chapter_display_idx` and compared on each tick. Failed because `_update_chapter_label_from_index` (the signal path) was not updating the index, so the correction never fired. Adding tracking there caused a visible N-1→N flash on every book load.

- **Walk-based signal in `_on_time_pos_change` for non-VT:** mpv emits intermediate `time_pos` values during seeks. The walk fired on these, emitting wrong chapter indices. Caused N+2 flashes on Next, "end of N-1" on load, and a stuck chapter slider. Regression cascade.

- **Walk in `_on_chapter_change` with direct `instance.time_pos` read:** Could not reliably get the post-seek position before the chapter callback fired. Still showed N-1 on load.

All three tried to correct the label after the seek landed wrong. The correct fix is at the seek itself.

**Fix:** `_restore_position` non-VT now uses `seek_async(book_data.progress + 0.35)`. Restores 0.35s past the saved position — accepted trade-off, consistent with what `previous_chapter` does for the same reason.

**Rule established:** `chapter_changed` signal for non-VT must remain on `_on_chapter_change` (mpv's async chapter property). VT uses `_on_time_pos_change` because VT chapter times are exact DB values; non-VT chapter times have ~0.25s float drift. The `_on_time_pos_change` path cannot distinguish intermediate seek values from settled ones and must not be used for non-VT chapter signalling.

**Files:** `app.py` — `_restore_position`

---


# Session Summary — 2026-05-15 (session 2)

## What was done: Four targeted bug fixes in player.py — no features, no behavior changes for non-VT books

---

## Bug 1: Signal accumulation in `load_book`

### Root cause
`load_book` called `self._playlist_resolved.connect(self._on_playlist_resolved)` on every invocation. `_on_playlist_resolved` disconnects itself when it fires, but if `load_book` was called twice before the worker thread emitted the signal, two connections accumulated. The handler then ran twice on the next emit — the second run saw stale `_held_play` / `_virtual_timeline` state from the new book, not the old one.

### Symptom
Rapid book switches (particularly VT → any) could reset the newly selected book's progress slider to 0%, because the double handler invocation triggered position restore twice.

### Fix
Added disconnect-before-connect guard in `load_book` immediately before the `connect` call:
```python
try:
    self._playlist_resolved.disconnect(self._on_playlist_resolved)
except RuntimeError:
    pass
self._playlist_resolved.connect(self._on_playlist_resolved)
```
`_on_playlist_resolved`'s self-disconnect is kept as a secondary safety net.

---

## Bug 2: `_is_seeking` never clears after a cross-file VT seek

### Root cause
`seek_async` stores the seek target in `_seek_target` as a **global VT position**. `_on_time_pos_change` clears `_is_seeking` when `abs(value - self._seek_target) < 1.0`. But `value` in that callback is mpv's raw **local file position** — for any VT file after the first, the local position and global target are numerically incomparable. The condition was never satisfied, so `_is_seeking` stayed `True` indefinitely, causing the progress slider to stop updating until some other event cleared the flag.

### Fix
In `_on_time_pos_change`, convert `value` to a global position before comparing:
```python
global_value = value + (self._file_offset or 0)
if self._seek_target is None or abs(global_value - self._seek_target) < 1.0:
    self._is_seeking = False
    self._seek_target = None
```
For non-VT books `_file_offset` is always `0.0` — behavior unchanged.

---

## Bug 3: `_on_chapter_change` emitting spurious local indices during VT playback

### Root cause
mpv's `chapter` property observer fires `_on_chapter_change` unconditionally. During VT playback mpv only knows about the current single file — its chapter index resets to 0 on every file switch. Any listener on `chapter_changed` received both the correct global VT index (emitted by `_on_time_pos_change`) and the wrong local mpv index (emitted by `_on_chapter_change`). This caused chapter label flicker and incorrect chapter highlighting.

### Fix
Gate the emit in `_on_chapter_change` — return early for VT books:
```python
def _on_chapter_change(self, name, value):
    if value is not None:
        if self._virtual_timeline is not None:
            return
        self.chapter_changed.emit(int(value))
```
`_on_time_pos_change` remains the sole source of `chapter_changed` during VT playback.

---

## Bug 4: `apply_smart_rewind` using `time_pos` setter directly on VT books

### Root cause
`apply_smart_rewind` computed a rewind position from `self.time_pos` (the global VT position) and wrote it via `self.time_pos = new_pos`. The `time_pos` setter writes directly to `self.instance.time_pos` — mpv's local file position. On a VT book this is a type error: writing a global position as a local position seeks within the current file only, ignoring file boundaries.

### Fix
Extract the computed position to `new_pos` and route through `seek_async` for VT books:
```python
new_pos = max(start_limit, (self.time_pos or 0) - rewind_amt)
if self._virtual_timeline is not None:
    self.seek_async(new_pos)
else:
    self.time_pos = new_pos
```

---

---

## Bug 5: `update_timer_state` crashes if `self.player` is `None`

### Root cause
`update_timer_state` called `self.player.set_fade_ratio(1.0)` unconditionally as its second statement, with no guard on `self.player`. Called every 200ms, this would raise `AttributeError` if `player` were `None`.

### Fix
Added `if not self.player: return` as the very first statement in `update_timer_state`.

---

## Bug 6: `end_of_chapter` mode used `self.player.chapter` (async mpv property)

### Root cause
The `end_of_chapter` branch in `update_timer_state` derived the current chapter via `self.player.chapter`. For non-VT books this falls through to mpv's async `instance.chapter` property, which can be ahead of or behind `time_pos` after any seek — violating the critical architecture rule.

### Fix
Replaced the `self.player.chapter` read with a position-based walk of `chapter_list`, matching the pattern used in `_sync_chapter_ui`:
```python
chaps = self.player.chapter_list or []
curr_chap = 0
for i, ch in enumerate(chaps):
    if ch.get('time', 0) <= player_pos + 0.35:
        curr_chap = i
```
The 0.35s tolerance matches the architecture rule.

---

## Bug 7: `end_of_chapter` and `end_of_book` modes compared against `player_dur` without a `None`/`0` guard

### Root cause
Both branches used `player_pos >= player_dur - 0.5` with no guard on `player_dur`. If `player_dur` was `None`, this raised `TypeError`. If it was `0` (no file loaded), the condition evaluated to `player_pos >= -0.5`, which is always true at position 0.0 — triggering an immediate end-of-book pause on book load.

### Fix
Added `if not player_dur: return` in both branches before any arithmetic on `player_dur`.

---

## Bug 8: Speed setter did not update `_cached_speed`

### Root cause
`player.speed` setter wrote to `self.instance.speed` but not to `self._cached_speed`. The getter returns `_cached_speed`, which is only updated via the mpv observer callback. Between the write and the next callback, `self.player.speed` returned the old value. Rapid scroll wheel events both read the stale cached speed and applied the same delta twice instead of stacking.

### Fix
Added `self._cached_speed = value` immediately after `self.instance.speed = value` inside the setter guard.

---

## Bug 9: `TitleBar.mousePressEvent` called `windowHandle().startSystemMove()` without a `None` guard

### Root cause
`QWidget.windowHandle()` returns `None` if the native window hasn't been created yet. Calling `.startSystemMove()` on `None` raises `AttributeError`. Only `win.panel_manager` was guarded, not the window handle.

### Fix
Stored the result of `windowHandle()` before use and guarded the call:
```python
handle = win.windowHandle()
if handle:
    handle.startSystemMove()
```

---

## Files changed this session

| File | Changes |
|---|---|
| `src/fabulor/player.py` | Disconnect-before-connect in `load_book`; global-position seek settler in `_on_time_pos_change`; VT early-return in `_on_chapter_change`; `seek_async` routing in `apply_smart_rewind`; speed setter now updates `_cached_speed` immediately |
| `src/fabulor/ui/sleep_timer.py` | `update_timer_state`: `self.player` None guard; position-based chapter walk replacing `self.player.chapter`; `player_dur` None/0 guard in both `end_of_chapter` and `end_of_book` branches |
| `src/fabulor/ui/title_bar.py` | `mousePressEvent`: `windowHandle()` None guard before `startSystemMove()` |

---


# Session Summary — 2026-05-15 (session 3)

## What was done: Targeted bug fixes across five files — no features

Nine bugs fixed across five files. All player.py fixes are non-VT-transparent (non-VT paths unchanged). No behavior regressions on M4B or single-file books.

---

## player.py — 4 bugs

### Bug 1: Signal accumulation in `load_book`
`load_book` connected `_on_playlist_resolved` on every call. If called twice before the worker emitted, two handlers accumulated and ran on the next emit — double position restore, progress slider reset to 0% on the new book. Fixed with disconnect-before-connect guard (try/except RuntimeError).

### Bug 2: `_is_seeking` stuck after cross-file VT seek
`seek_async` stored seek target as a global VT position; `_on_time_pos_change` compared it against mpv's local file position. Numerically incomparable for any file after the first — `_is_seeking` never cleared, progress slider stopped updating. Fixed by converting `value` to global position (`value + self._file_offset`) before the comparison.

### Bug 3: Spurious local chapter indices during VT playback
mpv's chapter observer fired `_on_chapter_change` unconditionally, emitting mpv's local per-file chapter index (resets to 0 on every file switch) alongside the correct global VT index emitted by `_on_time_pos_change`. Caused chapter label flicker and incorrect highlighting. Fixed by returning early in `_on_chapter_change` when `_virtual_timeline is not None`.

### Bug 4: `apply_smart_rewind` ignoring VT file boundaries
`apply_smart_rewind` wrote rewind position via `self.time_pos = new_pos` (mpv local setter) even on VT books, where the position was derived from the global VT coordinate. Ignored file boundaries, only sought within the current file. Fixed by routing through `seek_async(new_pos)` when `_virtual_timeline is not None`.

---

## library_controller.py — 1 bug

### Scanner not stopped before folder removal
`_on_remove_folder_clicked` called `db.remove_scan_location` while a scan could still be writing books from that folder. Scanner finished against the now-deleted location; results persisted in DB. Fixed by adding `self.scanner.stop()` as the first line of the method, before any DB call.

---

## book_detail_panel.py — 2 fixes

### Event filter active app-wide for entire session
`QApplication.instance().installEventFilter(self)` was called once in `__init__` and never removed. The filter intercepted every app-wide mouse event even while the panel was hidden. `_is_editing` is always False when hidden, so the filter body was a no-op — but the interception happened on every click. Fixed with `showEvent`/`hideEvent` pair: install on show, remove on hide. `super()` calls preserved in both.

### Edit state not reset on panel close
If the panel was closed while `_editing` was True (via a path that bypassed click-outside detection), the edit state persisted until the next `load_book`. Unsaved edits were silently discarded without explicitly exiting. Fixed by adding `if self._editing: _exit_edit_mode(save=False)` in `hideEvent`, between `removeEventFilter` and `super().hideEvent`.

---

## theme_manager.py — 2 fixes

### Panel animation guard accumulating deferred theme changes
`_on_theme_changed` used `QTimer.singleShot` when a panel was animating. Multiple theme changes during an animation accumulated separate deferred calls that fired in a burst. Replaced with a stored `_panel_guard_timer` (single-shot, interval `_PANEL_ANIM_GUARD_MS`): each new deferred call stops, disconnects, reconnects, and restarts the timer — only the last one fires.

### `abort_theme_fade` not resetting overlay opacity
After stopping the fade animation and hiding the overlay, `_fade_effect` opacity was left at whatever value the animation had reached when stopped. Any code path that inspected opacity before the next fade started saw a stale non-zero value. Fixed by adding `self._fade_effect.setOpacity(0.0)` after `hide()`. Order: `stop()` → `hide()` → `setOpacity(0.0)`.

---

## panels.py — 2 fixes

### Book detail panel wrong y position in `resize_panels`
`resize_panels` used `sidebar_y = 56` for the book detail panel, but the authoritative position in `_start_book_detail_entry` and `_close_book_detail_flow` is `32` (title bar height only — the panel covers the progress bar). On window resize while the panel was open, it jumped 24px. Fixed by using `32` directly in the book detail panel block; all other panels retain `sidebar_y = 56`.

### `Optional` not imported (pre-existing, fixed incidentally)
`Optional` used in type annotations but not imported. Fixed with the appropriate import addition.

---

## Known issue caught incidentally: Timeline tab title not updated after metadata edit

Editing a book title via the Book Detail Panel inline editor is reflected everywhere except the Stats → Timeline tab. `stats_panel.refresh_all()` is called after `metadata_saved`, which refreshes Day/Week/Month/Finished tabs, but the Timeline tab appears to have its own data path that does not re-fetch book titles. Root cause not yet isolated. To be investigated in a future session.

---

## Files changed this session (part 1)

| File | Changes |
|---|---|
| `src/fabulor/player.py` | Disconnect-before-connect in `load_book`; global-position seek settler in `_on_time_pos_change`; VT early-return in `_on_chapter_change`; `seek_async` routing in `apply_smart_rewind` |
| `src/fabulor/library_controller.py` | `scanner.stop()` as first line of `_on_remove_folder_clicked` |
| `src/fabulor/ui/book_detail_panel.py` | `showEvent`/`hideEvent` pair for event filter lifecycle; `_exit_edit_mode(save=False)` guard in `hideEvent` |
| `src/fabulor/ui/theme_manager.py` | `_panel_guard_timer` stored timer replacing `QTimer.singleShot`; `_fade_effect.setOpacity(0.0)` in `abort_theme_fade` |
| `src/fabulor/ui/panels.py` | `Optional` import added; book detail panel y position corrected to `32` in `resize_panels` |

---

## controls.py — 3 fixes

### `when_animations_done` double registration
Each call connected a new closure to `_flow_anim.finished` or `_reveal_anim.finished` without checking for an existing pending registration. If called twice while an animation was running, two closures accumulated and `callback()` fired twice. Fixed by adding `_when_done_pending` flag: `when_animations_done` returns early if already pending; the flag is cleared in `_after_reveal` before `callback()` and in the immediate-call path before `callback()`. `_after_flow` re-enters `when_animations_done` which re-sets the flag before connecting `_after_reveal` — correct because the two-phase (flow then reveal) sequence needs the flag live across both phases.

### `_reveal_anim` not stopped when markers are cleared
`set_markers([])` returned early without stopping `_reveal_anim`. An in-flight reveal animation continued running against a now-empty marker list, firing `finished` when it completed and leaving a stale animation live. Fixed by adding `self._reveal_anim.stop()` in the `if not ratios:` branch, before `self.update()`.

### `ScrollingLabel` timer not stopped on hide
The scroll timer ran indefinitely regardless of widget visibility. When the label was hidden the timer continued firing `_update_scroll` and calling `update()` unnecessarily. Fixed with `hideEvent`/`showEvent` pair: `hideEvent` stops the timer before `super()`; `showEvent` calls `_update_scrolling_state()` after `super()` to restart only if the text still needs scrolling.

---

## cover_panel.py — 2 fixes

### `upsert_cover` return value unguarded
`_on_add_cover` used the return value of `upsert_cover` as `cover_id` in the new cover dict and as the `_thumbnails` key without any None/falsy check. If the DB call failed silently and returned None, `_thumbnails[None]` was inserted and all subsequent cover lookups by id would break. Fixed by adding `if not cover_id: self._show_error(...); return` immediately after the `upsert_cover` call, before `cover_id` is used anywhere.

### Fit mode buttons visible with no cover selected
The four fit mode buttons were always visible, including when `_selected is None` (book with no covers, or all covers deleted). Clicking them was a silent no-op but misleadingly appeared actionable. Fixed by adding `_set_fit_buttons_visible(visible: bool)` helper; buttons start hidden in `_build_ui`; `_select_cover` shows them; the three paths that set `_selected = None` (`load_book` else branch, `_on_thumb_delete` no-covers path, `_on_thumb_delete` non-active deletion with no active fallback) hide them.

---

## chapter_list.py — 3 fixes

### Digit buffer not cleared on book switch
`_digit_buffer` was only cleared in `_commit_digit_jump` and on Escape/C. No clear on `populate` (called on every book switch). If the user typed a digit for book A, switched to book B within 800ms, and the timer fired, `_commit_digit_jump` ran against book B's chapter list with book A's digit string. Fixed by adding `self._digit_buffer = ""` and `self._digit_timer.stop()` as the first two statements in `populate`, before the `try` block.

### Digit keypresses not consumed
The `elif Qt.Key.Key_0 <= key <= Qt.Key.Key_9:` branch in `keyPressEvent` handled digit keys but never called `event.accept()`. The event propagated to the parent widget. Fixed by adding `event.accept()` as the last line of that branch.

### `ValueError` not caught in `_commit_digit_jump`
The `by_index` path called `int(typed)` which raises `ValueError` on non-numeric input. The except clause caught only `ShutdownError`, `AttributeError`, `SystemError` — `ValueError` propagated uncaught. Fixed by adding `ValueError` to the except tuple in `_commit_digit_jump`.

---

## Files changed this session (part 2)

| File | Changes |
|---|---|
| `src/fabulor/ui/controls.py` | `_when_done_pending` flag in `__init__`; `when_animations_done` guard + flag lifecycle; `_reveal_anim.stop()` in `set_markers` empty path; `ScrollingLabel.hideEvent`/`showEvent` |
| `src/fabulor/ui/cover_panel.py` | `upsert_cover` return value guard in `_on_add_cover`; `_set_fit_buttons_visible` helper; buttons start hidden; shown in `_select_cover`, hidden in three `_selected = None` paths |
| `src/fabulor/ui/chapter_list.py` | `_digit_buffer`/`_digit_timer` reset at top of `populate`; `event.accept()` in digit branch; `ValueError` added to `_commit_digit_jump` except tuple |

---


# Session Summary — 2026-05-15 (session 1)

## What was done

Three back-to-back mechanical refactors of `app.py`, each plan-first, verify-then-implement. No behavior changes. Goal was reducing `app.py` cognitive load and breaking implicit coupling between `MainWindow` and a few internal collaborators.

### Refactor 1 — Extract SettingsController interface classes to module level

The five interface classes that bridge `SettingsController` to `MainWindow` (`VisualsInterface`, `PanelInterface`, `UICallbackInterface`, `LibraryInterface`, `PlayerInterface`) were defined inline inside `MainWindow.__init__` and instantiated immediately. The `VisualsInterface` case was the worst: it was a no-arg class whose 11 methods delegated to 11 closure functions in the surrounding `__init__` scope, capturing `self` implicitly.

Moved all five to module level, between `BrowserInterface` and `class MainWindow`. The 11 closures and the wrapper delegations disappeared — `VisualsInterface` now takes `main` as a constructor argument and references `self._main.<widget>` directly. The other four interfaces moved unchanged.

Sonnet's plan had one real bug Claude Code caught: in `set_hover_fade_selection` and `set_digit_mode_selection`, the rewrite used `m = self._main` while the original used `m` as the loop variable — would have shadowed silently. Plan was corrected to use `md` as the loop var before implementation.

Net: ~150 lines removed from `__init__`. No external callers of the closures (verified via grep across `app.py` and `settings_controller.py`).

### Refactor 2 — Encapsulate `_cover_cache` access behind `LibraryPanel` methods

`app.py` was reaching into `library.py`'s module-level `_cover_cache` dict in two places via inline `from .ui.library import _cover_cache` imports — once to evict an entry when a book's active cover changed, once to read a cached pixmap in the legacy cover-load path. This coupled `MainWindow` to `_cover_cache`'s key type (`book.id`) and storage format.

Added two methods to `LibraryPanel`: `evict_cover(book_id)` and `get_cached_cover(book_id)`. Both call sites in `app.py` now go through the panel. Zero `_cover_cache` references remain in `app.py`.

Sonnet's plan had a second real bug Claude Code caught: in `_on_active_cover_changed`, the rewrite claimed `book` was "already fetched two lines earlier" and proposed `self.library_panel.evict_cover(book.id) if book else None` after removing the `book = self.db.get_book(book_path)` line. But `book` was only defined on the line being removed — the replacement would have raised `NameError`, surfacing only when a user changed the active cover of the currently-playing book (not basic testing). Plan was corrected to keep the `book = ...` line and use a proper `if book:` block.

The `_cover_cache` dict itself stays as a module-level singleton in `library.py` — its current internal users (`BookModel`, preloader, `_on_cover_loaded`) are unchanged. The encapsulation is at the `app.py` ↔ `library.py` boundary only.

### Refactor 3 — Extract settings tab builders from `_build_settings_panel`

`_build_settings_panel` was a 345-line monolith building all five tabs (Themes, Look, Library, Audio, Controls) inline. Extracted each tab into a dedicated `_build_*_tab` method. `_build_settings_panel` is now a 21-line orchestrator.

Pure mechanical extraction. Every `self.*` attribute assignment preserved (a local-variable rebinding would have silently broken `VisualsInterface`'s `hasattr` lookups). The trailing artifacts the plan flagged were preserved verbatim:
- Three `theme_manager.update_*` calls remain after `addTab` inside `_build_themes_tab`.
- `# Visual initialization moved to after SettingsController binding` comment kept at end of `_build_appearance_tab`.
- `self._update_pattern_visuals()` moved into `_build_library_tab` immediately after `addTab` (matches previous order).
- `# Library controller connections are consolidated in __init__` doc comment kept in `_build_library_tab` (button signal connections still happen in `__init__` after `LibraryController` is constructed).
- The `# TAB 4: SHORTCUTS` comment with the tab label `"Controls"` — both kept (deliberate inconsistency from previous renames; out of scope to change).

## What changed in the codebase

| File | Change |
|---|---|
| `src/fabulor/app.py` | Five interface classes hoisted to module level. `VisualsInterface` now takes `main` constructor arg. Two inline `_cover_cache` imports removed; call sites use `library_panel.evict_cover` / `library_panel.get_cached_cover`. `_build_settings_panel` split into orchestrator + five `_build_*_tab` methods. |
| `src/fabulor/ui/library.py` | Added `LibraryPanel.evict_cover(book_id)` and `LibraryPanel.get_cached_cover(book_id)` after `hideEvent`, before `BookModel`. `_cover_cache` itself unchanged. |

## Working method observations

All three refactors followed the same loop: Sonnet drafts the plan, Claude Code reads the actual code first and reports back, user gates the implementation. Two of three plans contained real bugs that this verification caught before any code was written:

- Refactor 1: `m`/`md` loop variable shadowing.
- Refactor 2: `book` referenced after the line defining it was deleted, would have NameError'd only in a narrow runtime path.

Both were the kind of bug that mechanical "search and replace from the plan" implementation would have shipped. Worth keeping the "verify against actual code before implementing" step explicit going forward — line numbers in plans drift, scope claims ("already fetched two lines earlier") need spot-checking, and shadowing is invisible without seeing the original variable names side by side.

## Files changed this session

| File | Changes |
|---|---|
| `src/fabulor/app.py` | Module-level interface classes (5); `_build_settings_panel` orchestrator + 5 tab builders; `_cover_cache` access routed through `library_panel` |
| `src/fabulor/ui/library.py` | `LibraryPanel.evict_cover` and `LibraryPanel.get_cached_cover` |

---


# Session Summary — 2026-05-14 (session 2) / 2026-05-15

## What was built: Multi-file MP3 virtual timeline (stage 3 — rounds 1–3, with fixes)

---

## Problem

Multi-file MP3 audiobook folders (many .mp3 files per folder) could not be seeked, navigated by chapter, or advanced naturally without freezing the Qt main thread or losing playback position. The existing code treated each folder as either a single-file play or a concat:// stream. Stage 3 added a Python-side virtual timeline so Fabulor can seek globally across all files in a folder, maintain persistent progress, and display chapter navigation consistent with M4B books.

---

## Stage 3 — Round 1 and Round 2 (reverted)

Two earlier attempts at stage 3 were made and reverted before this session.

**Round 1** used a concat:// stream approach. mpv concatenated all MP3 files in a playlist and treated the result as a single stream. Reverted: mpv blocked the Qt main thread on backward seeks across file boundaries (same root cause as single-file MP3 seeking — bitstream scan), and seek precision near boundaries was unreliable.

**Round 2** is not explicitly documented but involved a partial virtual timeline without the book_ready/file_switched signal separation. It broke due to a feedback loop: `_on_file_ready` was connected to file_loaded, so it ran on every file load during natural advancement — triggering position restore, which triggered a file switch, which triggered file_loaded again, causing quadruple-advance cycles on every EOF.

---

## Stage 3 — Round 3: What was built

### Architecture overview

The virtual timeline is a Python-side list of `{file_path, cumulative_start, duration}` entries built from the `book_files` DB table (pre-scanned by the scanner). mpv plays one file at a time. The player translates global seeks into (file_index, local_offset) pairs and issues `instance.play(file_path)` + `_pending_local_pos` for cross-file seeks.

### Signal separation — the key non-obvious decision

The feedback loop from prior rounds was broken by splitting one signal into two:

- `book_ready` — fires **once per book**, before any file is loaded (VT books: from `ungate_play` / `_on_playlist_resolved`; non-VT books: from `_on_file_loaded`). Connected to `_on_file_ready` (position restore, UI init).
- `file_switched` — fires **per VT file load**, from `_on_file_loaded` when `_virtual_timeline is not None`. Connected only to `_on_vt_file_switched` (lightweight: just clears `is_seeking`).

`_on_file_ready` is no longer connected to `file_loaded` at all. This eliminates the feedback loop entirely.

**Why book_ready fires from different places for VT vs non-VT:** For VT books, we need to emit book_ready before any file loads (so position restore uses the global VT position). For non-VT books (M4B), we need to emit book_ready after the file is loaded (so `self.player.duration` is valid when `_on_file_ready` reads it for the slider animation).

### DB fast path — `book_files` table

`_resolve_playlist` checks the `book_files` table (populated by the scanner via `upsert_book_files`). If rows exist, it reads `{file_path, sort_order, duration_ms, cumulative_start_ms}` directly — no mutagen re-scan at play time. The virtual timeline is built from these rows and stored in `_virtual_timeline`. Chapter list is derived from the filenames (`{title: af.stem, time: cumulative_start_seconds}`). Returns only the first file path for the initial `instance.play()`.

### Async file switching

Cross-file seeks call `instance.play(target_file)` and store `_pending_local_pos` (the local offset within that file). When `file-loaded` fires for the new file, `_on_file_loaded` checks `_is_vt_file_switch`, seeks to `_pending_local_pos` via `command_async`, and clears the flag.

`_is_vt_file_switch = True` gates `_on_pause_test` — transient mpv pause events during file loading are silently dropped, preventing the pause handler from firing `_advance_or_finish` again mid-switch.

### Natural EOF advancement

`_on_pause_test` detects EOF (position within 1.5s of duration while paused). For VT books, `_advance_or_finish` increments `_current_vt_index`, updates `_file_offset`, sets `_is_vt_file_switch = True`, and calls `instance.play(next_file)`. After `instance.play()`, checks `if self.instance.pause: self.instance.pause = False` — mpv inherits the paused state from `keep_open='always'` and the previous file's EOF state, so this unpause is required.

**Why `keep_open='always'` produces RESTARTED (reason_int=2) not EOF (reason_int=0):** With `keep_open='always'`, mpv never closes the stream on EOF — it restarts. The end-file event always fires with reason RESTARTED. The `_on_end_file` reason_int=0 (true EOF) branch is unreachable dead code in this configuration. EOF detection is handled exclusively by `_on_pause_test` near-EOF position check.

---

## Bugs found and fixed during session

### Quadruple-advance at natural EOF
Four rapid `end-file / file_ready` cycles occurred on every natural file advance. `_advance_or_finish` called `instance.play(next_file)`, which briefly set mpv's pause state to True during file load. `_on_pause_test` fired for each transient pause and called `_advance_or_finish` again before the first one completed. Fixed by: `_is_vt_file_switch` flag gates `_on_pause_test` — if set, return immediately.

### Natural advance started paused
After `instance.play(next_file)`, the new file started in paused state. mpv inherits pause from `keep_open='always'` and prior EOF. Fixed by: explicit `if self.instance.pause: self.instance.pause = False` in `_advance_or_finish` after `instance.play()`.

### M4B contamination from VT books
Switching from a VT book to an M4B: the VT book's `_cached_time_pos` (a local file offset) persisted into the M4B load window. `_sync_persistence` saved this stale position against the M4B path before the M4B file was loaded. Fixed by two changes:
1. `load_book` reset block clears `_cached_time_pos = None` and `_cached_duration = None`.
2. `_sync_persistence` gated on `getattr(self, '_mpv_ready', True)` — no saves while the library panel is animating and mpv hasn't started.

### Chapter slider sent to 0.8% (only worked for file 0)
`seek_within_chapter` was using mpv's `self.chapter` property to find the current chapter (local per-file index). For VT books, this is always the chapter within the current file, not the global chapter. Fixed by: VT branch in `seek_within_chapter` walks `_chapter_list` by global `time_pos` to find current chapter, derives chapter start/end from the global list, then calls `seek_async` with the computed global position.

### Skip buttons non-functional after cross-file seek
`handle_rewind` and `handle_forward` used `self.player.time_pos = new_pos` (synchronous setter). For VT books, setting `time_pos` writes to mpv's current file only — it doesn't trigger a file switch. Fixed by: changed to `self.player.seek_async(new_pos)`, which routes through the VT file-switch logic.

### Chapter list highlighted wrong row (and dead on VT books)
`ChapterList._activate_item` called `self.player.chapter = idx` — mpv's local chapter setter. For VT books this is per-file chapter index, not the global index. Fixed by: VT branch reads `chapters[idx].get('time')` and calls `seek_async(target_time)`.

`Player.chapter` getter returned `self.instance.chapter` (mpv local). For VT books fixed to walk `_chapter_list` by global `time_pos` and return the matching global index.

`chapter_changed` signal was only emitted by mpv's chapter observer (local per-file changes). VT books only had one chapter per file, so the label never updated. Fixed by: `_on_time_pos_change` now computes the global VT chapter index on every position update, compares to `_last_vt_chapter`, and emits `chapter_changed` when it changes. `_last_vt_chapter = -1` resets in `load_book`.

### Progress slider wrong fill on VT → M4B switch
Progress slider showed ~66% fill for an M4B book that was at 0% progress. `_on_file_ready` read `self.progress_slider.value()` to compute `new_val` for the switch animation. During the switch window, the slider still held the VT book's stale value (~666/1000). `_update_ui_sync` had gated its `setValue` call on `not slider_animating and not self.player.is_seeking`, so the slider wasn't updated yet when `_on_file_ready` ran. Fixed by: compute `new_val = int((new_progress / dur) * 1000)` from the authoritative DB progress and player duration, not from the stale slider widget value.

---

## Non-obvious decisions

- `book_ready` fires from two different places (VT: before load, non-VT: after load) — this asymmetry is intentional. VT needs the signal before any file is loaded so the initial position restore sets `_pending_local_pos` on the right file. Non-VT needs it after load so `self.player.duration` is valid when the slider animation reads it.
- `_last_vt_chapter = -1` (not 0) on reset ensures the first time_pos tick always emits `chapter_changed`, so the label is set correctly even when the book starts at chapter 0.
- The `_pre_switch_slider_value` animation reads `self.progress_slider.value()` under the assumption the slider has been updated. This assumption is wrong during a book switch because the slider update in `_update_ui_sync` is gated. Any future "animate from old to new position" logic must read from the data source (progress / duration), never from the widget's current value.
- `keep_open='always'` makes end-file reason_int=0 unreachable — the RESTARTED event fires instead. Any new EOF-detection logic must go into `_on_pause_test`, not `_on_end_file`.

---

## Files changed this session

| File | Changes |
|---|---|
| `src/fabulor/db.py` | `book_files` table, `upsert_book_files`, `get_book_files` |
| `src/fabulor/library/scanner.py` | Populates `book_files` on multi-file scan; `cumulative_start_ms` per file |
| `src/fabulor/player.py` | `_virtual_timeline`, `_file_offset`, `_book_duration`, `_chapter_list`, `_current_vt_index`, `_pending_local_pos`, `_is_vt_file_switch`, `_last_vt_chapter` fields; `_resolve_playlist` DB fast path; `book_ready` / `file_switched` signals; `_on_file_loaded` VT branching; `_advance_or_finish` VT advancement + unpause; `_on_pause_test` gated by `_is_vt_file_switch`; `seek_async` VT file-switch routing; `seek_within_chapter` VT branch; `previous_chapter` / `next_chapter` VT branches; `chapter` getter VT branch (walks `_chapter_list`); `_on_time_pos_change` VT chapter watcher + `chapter_changed` emit; `load_book` reset clears all VT fields + `_cached_time_pos` + `_cached_duration` |
| `src/fabulor/app.py` | `db` constructed before `player`; `book_ready` → `_on_file_ready` + `_on_file_loaded_populate_chapters`; `file_switched` → `_on_vt_file_switched`; `_restore_position` uses `seek_async` for VT; `handle_prev` / `handle_next` use `seek_async`; `handle_rewind` / `handle_forward` use `seek_async`; `_sync_persistence` gated on `_mpv_ready`; `_on_file_ready` slider animation reads from `new_progress / duration` not stale slider value |
| `src/fabulor/ui/chapter_list.py` | `_activate_item` VT branch uses `seek_async(target_time)` instead of `self.player.chapter = idx` |

# Session Summary — 2026-05-14 (session 1)

## What was built: Async MP3 seek — eliminate Qt main thread block on backward seeks

---

## Problem

Seeking backwards in MP3 files (both single files and `concat://` multi-file streams) blocked the Qt main thread for 10–30 seconds. mpv scans backwards through MP3 bitstreams to find frame boundaries rather than using arithmetic seeking. python-mpv's property setter (`self.instance.time_pos = value`) is a synchronous blocking call — it holds the GIL on the calling thread until libmpv acknowledges the seek. Since all seeks were called from slider release handlers on the Qt main thread, the entire event loop froze for the duration of the scan.

---

## Root cause analysis

The full seek path was traced from slider release to mpv:

1. `ClickSlider.mouseReleaseEvent` → emits `sliderReleased` (Qt main thread)
2. `_on_slider_released` reads `time_pos`, `duration`, `speed` (blocking property reads), then writes `self.player.time_pos = new_pos` (blocking write)
3. `Player.time_pos` setter: `self.instance.time_pos = value` — python-mpv blocks until libmpv acks

`_on_chap_slider_released` had a second block: it read `self.player.time_pos` back immediately after the seek write (to check undo threshold), blocking again until mpv's position settled.

Pre-seek reads (`time_pos`, `duration`, `speed`) also cross the IPC boundary but are fast (~1ms) when mpv isn't mid-seek. They were cached anyway (see property caching below). The write was the primary cause.

---

## Fix 1 — `seek_async` (player.py)

Added `Player.seek_async(pos)` which uses `command_async('seek', pos, 'absolute+exact')` — dispatches the seek to libmpv's command queue and returns immediately. `absolute+exact` forces hr-seeking regardless of the `hr-seek` option, matching the precision of the old `time_pos =` writes. `_eof = False` and `is_seeking = True` are set inline; `_seek_target = pos` is stored for the settler check.

`seek_within_chapter` updated to call `seek_async` and return `new_pos` (the computed seek target) so callers don't need to read `time_pos` back after the seek. `undo_seek` updated to call `seek_async`.

`_on_slider_released`, `_on_slider_right_clicked` updated to call `seek_async`. `_on_chap_slider_released` rewritten to use the returned `new_pos` from `seek_within_chapter` — eliminating all post-seek `time_pos` reads.

`apply_smart_rewind`, skip buttons (`handle_rewind`, `handle_forward`), chapter nav (`handle_prev`, `handle_next`), and the book-load position restore remain on the sync `time_pos =` path — not slider-driven, not the problem path.

---

## Fix 2 — Property caching via `observe_property` (player.py)

All four frequently-read mpv properties are now cached via observers and served from Python-side fields:

| Property | Cache field | Observer |
|---|---|---|
| `time-pos` | `_cached_time_pos` | `_on_time_pos_change` |
| `duration` | `_cached_duration` | `_on_duration_change` |
| `pause` | `_cached_pause` | `_on_pause_test` (extended) |
| `speed` | `_cached_speed` | `_on_speed_change` |

Getters now return cached values. Setters still write to `self.instance` — mpv fires the observer which updates the cache. No round-trip on reads.

---

## Fix 3 — `is_seeking` lifecycle moved to observer (player.py)

Previously `is_seeking` was cleared by the 200ms polling loop in `_update_ui_sync` and `get_stable_position` — before mpv had delivered the new position. This caused the progress sliders to animate back and forth during slow seeks (VU meter effect).

`_on_time_pos_change` now clears `_is_seeking` (and `_seek_target`) when the observed position is within 1.0s of the seek target. This fires only once mpv has actually moved to the new position — the observer is the only correct place for this.

`_is_seeking = False` removed from the playing branch of `get_stable_position` and the playing branch of `_update_ui_sync`. The paused-branch clear in `get_stable_position` and `_update_ui_sync` is retained — it handles the deadzone case where mpv settles while paused.

Both slider `setValue` calls in `_sync_progress_sliders` and `_sync_chapter_ui` are gated with `not self.player.is_seeking` so the timer can't fight the seek while it's in flight.

---

## Diagnostic instrumentation (added then removed this session)

Temporary `print` calls were added to `_on_time_pos_change` (`SEEK SETTLED`) and `_sync_progress_sliders` (`SLIDER SET` / `SLIDER GATED`) to confirm gate behaviour. Removed before commit.

---

## Files changed this session

| File | Changes |
|---|---|
| `src/fabulor/player.py` | `seek_async`; `_seek_target` field; `seek_within_chapter` returns `new_pos`; `undo_seek` uses `seek_async`; property caching for `time_pos`, `duration`, `pause`, `speed`; `_on_time_pos_change` clears `is_seeking` on settle; `_is_seeking = False` removed from `get_stable_position` playing branch |
| `src/fabulor/app.py` | `_on_slider_released`, `_on_slider_right_clicked` use `seek_async`; `_on_chap_slider_released` uses returned `new_pos`; `is_seeking = False` removed from `_update_ui_sync` playing branch; `is_seeking` gates confirmed on both slider `setValue` calls |

---


# Session Summary — 2026-05-13

## What was built: Multi-file book support, smooth panel close, progress accuracy, theme fix

---

## Feature 1: Multi-file book support (player.py)

Books stored as folders of multiple audio files (MP3, M4A, FLAC) now play as a single continuous stream. Previously they silently failed with mpv reporting `no audio or video data played`.

### How it works

`_resolve_playlist(path)` scans direct children for audio files, sorts alphabetically, and returns either the single file path or a `concat://file1|file2|...` URI. For multi-file books it also builds an ffmetadata chapter file:

```
;FFMETADATA1
[CHAPTER]
TIMEBASE=1/1000
START=0
END=187000
title=Chapter 01
...
```

Each chapter boundary is a cumulative millisecond timestamp derived from `mutagen.File(f).info.length`. Written to a `NamedTemporaryFile(delete=False)`. `instance.chapters_file` is set to this path **before** `instance.play()` — mpv reads it at load time, order is critical.

### Diagnosis

Added `event_callback('end-file')` observer. The event is an `MpvEventEndFile` object — data lives in `.d` dict, not as top-level attributes. `getattr(event, 'reason', ...)` always returns the default. Must use `event.d.get('reason')` or `isinstance(event, dict)` branch. Values are bytes (`b'stop'`), must decode. `'redirect'` added to exclusion set — mpv fires this for internal playlist advances.

---

## Feature 2: Async playlist resolution (player.py)

`_resolve_playlist` calls `mutagen.File()` for every file in the folder. For a 260-file book this blocked the main thread, stuttering any concurrent animation.

### How it works — gate/ungate pattern

`load_book` spawns a `QRunnable` worker on `QThreadPool.globalInstance()`. The worker emits `_playlist_resolved(play_target, chapters_file)` when done. `_on_playlist_resolved` checks `_play_gated`:

- If `True` (gate still up): stores result in `_held_play`, prints "held — waiting for ungate"
- If `False` (gate already lifted): calls `instance.play()` immediately

`ungate_play()` sets `_play_gated = False`. If `_held_play` is populated, drains it and plays. If not (worker still running), the flag ensures `_on_playlist_resolved` will play on arrival.

This handles the race without polling: whichever finishes last — the animation or the worker — triggers `instance.play()`.

**Non-library paths** (startup, EOF restart) call `_mpv_ready = True` then `ungate_play()` immediately after `load_book`. No animation to wait for, gate lifts instantly.

---

## Feature 3: Panel close stutter fix (app.py, player.py, panels.py)

### Root cause (non-obvious)

The stutter was **not** a main-thread block. Every Python step in the book-switch sequence was under 2ms. The cause was mpv's PulseAudio negotiation on background threads creating OS scheduler priority inversions that delayed Qt's `QAnimationTimer` wake-ups.

**Diagnostic signal:** back-button close (identical slide animation, no mpv work) was always smooth. Book-selection close always stuttered. The only difference was `instance.play()` being called concurrently.

### The complete book-switch sequence (what finally worked)

**`_on_book_selected_from_library`:**
1. Save progress, clear UI state, reset `_paused_time = None`, set `_mpv_ready = False`
2. Capture `_pre_switch_slider_value` and `_pre_switch_chap_slider_value` for flow animation
3. `panel_manager.hide_all_panels()` — animation starts, `_is_animating = True`
4. `QTimer.singleShot(0, lambda: ...)` — defers DB writes, library model updates, `_load_cover_art`, and `player.load_book` to next event loop cycle. Animation gets its first frame uncontested.

**Background worker:** resolves playlist, emits signal, result held in `_held_play`.

**`_on_library_hidden` (fires after 300ms):**
1. `_is_animating = False`, panel hidden
2. `mw._mpv_ready = True`
3. `player.ungate_play()` — `instance.play()` fires here, after animation is complete
4. If `_file_ready_deferred` or `_chaps_deferred`: `QTimer.singleShot(50, _drain_deferred_file_ready)`
5. Else: `_apply_pending_cover_theme()`

**`_mpv_ready` guard in deadzone:** `_update_ui_sync` deadzone checks `getattr(self, '_mpv_ready', True)` before accepting any `mpv_pos`. While `False`, all positions from the old (still-playing) file are silently ignored. `_paused_time` stays `None`. Without this, the 200ms timer accepted the previous book's position during the 300ms animation window and wrote it to the slider — producing random progress display on book load.

**`_mpv_ready` defaults to `True`** via `getattr` so that startup, seek, and normal playback are completely unaffected by this guard.

### Why _on_file_ready deferral is kept

Even though `instance.play()` now fires after the animation, on fast SSDs `file_loaded` can still arrive before `_on_library_hidden` if the worker finished early. The `_is_animating` check in `_on_file_ready` and `_on_file_loaded_populate_chapters` catches this and defers via flags. The 50ms `singleShot` delay before draining avoids a last-frame compositor hitch.

---

## Feature 4: Progress slider flow animation restored (app.py)

The flow animation (`animate_to`) broke because of interference from the new async sequence. The fix was to restore the original working logic exactly:

- `_update_ui_sync()` runs unconditionally in `_on_file_ready` (not guarded by `is_seeking`)
- After it runs, `progress_slider.value()` holds the correct position (or 0 for new books)
- `animate_to(new_val, old_value=pre)` fires immediately, before the next timer tick can fight it
- Chapter slider animation fires from `_on_file_loaded_populate_chapters` — chapter data must exist for the target to be valid

The many intermediate approaches (deferred animation from deadzone, `_fire_deferred_slider_animation`, `_seek_target` guard) were all removed. The original SESSION 2026-05-01 logic was correct; the new async timing made it work again once `_mpv_ready` prevented the stale-position problem.

---

## Bug fix: Theme fade overlay ghost (theme_manager.py)

Cover-art theme transitions (`isinstance(theme_name, dict)`) now subtract `progress_slider`, `chapter_progress_slider`, and `progress_percentage_label` from the `_fade_overlay` mask. These custom-painted widgets update immediately; without exclusion the old screenshot morphed over their correct values visually.

`QRegion` import moved outside the `if pm.is_any_panel_visible()` branch — it was previously only imported in that branch, causing `UnboundLocalError` when no panel was visible.

Cover theme application deferred to `_apply_pending_cover_theme()`, called after both deferred callbacks drain. `when_animations_done` on `progress_slider` ensures theme fires after notch reveal animation completes.

---

## Files changed this session

| File | Changes |
|---|---|
| `src/fabulor/player.py` | `_resolve_playlist` worker thread; `_playlist_resolved` signal; `_on_playlist_resolved`; `ungate_play()`; `_play_gated`/`_held_play` flags; `end-file` observer; `'redirect'` exclusion |
| `src/fabulor/app.py` | Book-switch sequence reordered; `_mpv_ready` guard in deadzone; deferred drain pattern; `_file_ready_deferred`/`_chaps_deferred` flags; `_drain_deferred_file_ready`; `_apply_pending_cover_theme`; flow animation restored to original logic |
| `src/fabulor/ui/panels.py` | `_on_library_hidden` sets `_mpv_ready`, calls `ungate_play()`, drains deferred callbacks; removed `_pending_cover_pixmap` drain (moved to app.py) |
| `src/fabulor/ui/theme_manager.py` | `QRegion` import hoisted; slider/percentage exclusion mask for cover-art transitions |
| `NOTES.md` | Panel close stutter fully documented; library close stutter marked resolved |

---


# Session Summary — 2026-05-12

## What was done: Cover persistence fixes, preloader correction, window size lock

---

## Window size locked to 300×564 (separate chat window)

Two changes made outside this session, documented here for the record:

- `app.py:379` — replaced `setMinimumWidth(300)` + `resize(300, 450)` with `setFixedSize(300, 564)`. Locks the window to a single fixed size regardless of content state.
- `app.py:538` — changed `setMinimumSize(280, 280)` to `setMinimumSize(0, 0)` on `cover_art_label`. The old 280×280 minimum was forcing the window to expand beyond 450px when a cover loaded — removing it allows the cover label to fill whatever space the fixed window provides without fighting the layout.

The window is now always 300×564. Cover display scales to fit that space via `_update_cover_art_scaling`. No collapse risk in practice: `cover_art_label` has `Expanding × Expanding` size policy and `visual_area` claims the space with stretch factor 1.

---

## Active cover not persisting after app restart

### Symptom
User selects a custom cover via the Cover tab. It displays correctly in the main window. After restarting the app, the original scanner cover appears instead.

### Root cause
`_load_cover_art` correctly calls `get_active_cover` and retrieves `active_path` (the user-selected cover). But it then fell through to the cache/`extract_cover` path, which loaded the scanner thumbnail from `_cover_cache` (populated by the library preloader using `book.cover_path`) and displayed that instead.

### Fix
When `active_path` is set from `book_covers`, load from it directly via `QPixmap(active_path)` and call `_apply_main_cover` — no cache check, no `extract_cover`. Cache is bypassed because it may hold a stale scanner thumbnail. Falls through to the legacy path only if `active_path` file is missing on disk.

---

## Library thumbnail showing original cover after active cover change

### Symptom
After selecting a custom cover, the library panel thumbnail for that book still showed the scanner cover. Inconsistent — sometimes correct, sometimes stale.

### Root cause
The preloader (`_preload_covers` in library.py) created `CoverLoaderWorker(book)` without `active_cover_path`. It always loaded `book.cover_path` (scanner thumbnail), writing it to `_cover_cache`. `_load_visible_covers` then skipped books already in cache, so the stale entry was never replaced.

### Fix
Preloader now calls `get_active_cover_path(book.path)` before constructing the worker, matching what `_trigger_cover_load` already did. Pre-migration books (no `book_covers` entry) get `None` and fall back to `book.cover_path` as before. The asymmetry between the two code paths was a bug, not intentional — the NOTES entry describing it as intentional has been updated.

---

## Player cover reverting after library reload (AttributeError also fixed)

### Symptom
After removing and re-adding a scan library location, the currently playing book displayed the original cover instead of the user-selected one. Also triggered `AttributeError: 'AppInterface' object has no attribute 'load_cover_art'`.

### Fix
1. Added `load_cover_art` method to `AppInterface` (was only on `PlayerInterface` used by `SettingsController`).
2. `library_controller._on_scan_finished` now calls `self.app.load_cover_art(current_file)` after `refresh_panel` — refreshes the player cover from the latest DB state after every scan completion, ensuring the active `book_covers` entry is used.

---

## Files changed this session

| File | Changes |
|---|---|
| `src/fabulor/app.py` | `_load_cover_art` loads from `active_path` directly when set, bypassing cache; `setFixedSize(300, 564)`; `cover_art_label.setMinimumSize(0, 0)`; `load_cover_art` added to `AppInterface` |
| `src/fabulor/ui/library.py` | Preloader now passes `active_cover_path` to `CoverLoaderWorker`, matching `_trigger_cover_load` |
| `src/fabulor/library_controller.py` | `_on_scan_finished` calls `load_cover_art(current_file)` after scan; `load_cover_art` on `AppInterface` |
| `NOTES.md` | Pre-migration preloader bypass entry updated (was bug, not intentional) |

---


# Session Summary — 2026-05-11

## What was done: Cover panel polish, bug fixes, and no-cover book handling

Continued from prior session where cover management was implemented. This session was focused entirely on visual polish, edge case fixes, and one non-obvious root-cause bug.

---

## Cover panel visual fixes

### Thumbnail overlay height
Reduced `_OVERLAY_HEIGHT` from 24 to 17px. One constant change, all geometry derived from it.

### + button layout
Extensive iteration. Final architecture: `_left_col` is a QWidget with explicit `setFixedHeight` computed as `n × 72 + max(n-1, 0) × 6`. The `+` button lives in `left_wrapper` (not `_thumb_layout`) with `setSpacing(6)` matching the inter-thumb gap. This guarantees the button always sits exactly one gap below the last thumb regardless of count. `_update_left_col_height()` is called after every thumb change (rebuild, add, delete).

### + button appearance
`setFixedSize(_THUMB_SIZE, _THUMB_SIZE)` — square. `border-radius: 0px`, `background-color: #2A2A2A` matching the thumbnail slot fallback color.

### Slot cap fix
Changed `user_count < 3` to `len(self._covers) < 4` throughout — books without a locked cover now correctly allow 4 user slots. Slot index range changed from `range(1, 4)` to `range(1, 5)`.

### Overlay suppression
Two rules: (1) hide overlay when the locked cover is the only cover (`_update_overlay_enabled`); (2) suppress in `paintEvent` when `_is_locked and _is_active` — both × and ✓ are absent in that state, nothing to click.

### Thumbnail image bleed
Fixed `paintEvent` to clip the image draw to `rect().adjusted(1,1,-1,-1)`, then draw the 2px accent border on top. Image no longer bleeds into the border zone.

### Active outline reliability
Switched `set_active()` from `update()` (deferred) to `repaint()` (immediate). Removed `border` lines from `QFrame#CoverThumbnail` QSS to eliminate style engine conflict with `paintEvent`-drawn border.

### Preview area
Fixed size `205 × 270`. Right column layout: preview → `addSpacing(8)` → fit buttons (fixed height 34px) → `addStretch()`. Stretch absorbs remaining vertical space below buttons; buttons are always 8px below the preview. `root.addStretch()` added after right column so it doesn't expand horizontally with panel width.

### Top/Crop preview rendering
Both modes now render into a `w × w` square centered in the `w × h` preview canvas with letterbox bars, matching the player's square cover art area.

### Preview background
Default `transparent` (inherits panel background). Themes can set `cover_preview_bg` key to override. `_preview_bg` colour used when filling the canvas in fit/top modes.

### Fit mode button alignment
`btn.setFixedHeight(34)` on each fit button. `266 preview + 6 spacing + 34 buttons = 306px = 4 × 72 + 3 × 6` (bottom of 4th thumb slot).

### ✓ button updates preview
`_on_thumb_set_active` now calls `_select_cover(active)` after `_update_active_outlines()`, so the preview area refreshes to show the newly active cover.

### Fit mode propagates to main window
`_on_fit_mode_clicked` emits `active_cover_changed` when the selected cover is also the active cover. `app._on_active_cover_changed` reads `fit_mode` from DB and stores it in `self._cover_fit_mode`. `_update_cover_art_scaling` branches on `_cover_fit_mode` (fit / stretch / crop / top). `_load_cover_art` also reads fit mode on book load.

### Header cover (book detail panel)
`_refresh_header_cover` added — updates the 80×120 cover in the BookDetailPanel header when active cover or fit mode changes. Connected as a second slot on `_cover_panel.active_cover_changed`.

### Header thumbnail width locked
`_cover_label.setFixedWidth(80)` with `setMaximumHeight(120)`. Width no longer varies with cover aspect ratio, preventing text drift in the meta block.

---

## Tag strip — reserved height
`_tag_display_label` changed to `setFixedHeight(38)` and always visible (text set to `""` when no tags, never hidden). Keeps the tab bar and cover panel at a consistent Y position regardless of tag count. Looks slightly odd when empty but acceptable — will improve once panel background is made opaque.

---

## No-cover book: author/title fallback bug

### Symptom
Books with no cover (no `book_covers` entry, empty `book.cover_path`) showed a blank main window instead of "author - title". The fallback only appeared after the user manually added a cover, set it active, then deleted it.

### Root cause
Two independent issues:
1. `_load_cover_art` correctly reached the "author - title" branch for truly no-cover books. But `library_controller.apply_library_state` ([library_controller.py:126](src/fabulor/library_controller.py#L126)) called `update_metadata(None, show_metadata=False)` immediately after, hiding `metadata_label` unconditionally whenever `has_book=True`.
2. The "load, select, delete" workaround worked because `_on_active_cover_changed` evicted the cache before calling `_load_cover_art`, which then correctly reached the "author - title" branch without interference.

### Fix
Removed `show_metadata=False` from `library_controller.py:126`. `_load_cover_art` is now the sole controller of `metadata_label` visibility when a book is playing. Added an early-return in `_load_cover_art`: if both `get_active_cover` and `book.cover_path` are empty, show "author - title" immediately without touching the cache or calling `extract_cover`.

### Critical — do not revert
The `show_metadata=False` must not be restored to `library_controller.apply_library_state` when `has_book=True`. That line was silently overriding cover display logic on every book switch.

---

## Files changed this session

| File | Changes |
|---|---|
| `src/fabulor/ui/cover_panel.py` | Thumbnail overlay height; + button layout, size, colour; slot cap and index range; overlay suppression (two rules); image bleed clip; active outline reliability; preview fixed size; Top/Crop square rendering; preview background; fit button height; ✓ updates preview; fit mode emits signal; `_update_left_col_height` helper |
| `src/fabulor/ui/book_detail_panel.py` | `_tag_display_label` always visible with fixed height 38; `_refresh_header_cover` method; `_cover_label.setFixedWidth(80)`; active cover changes update header |
| `src/fabulor/app.py` | `_update_cover_art_scaling` branches on `_cover_fit_mode` (fit/stretch/crop/top); `_load_cover_art` reads fit mode and short-circuits for no-cover books; `_on_active_cover_changed` evicts cache and reads fit mode; `_on_active_cover_changed` handles empty `file_path` (all covers deleted) |
| `src/fabulor/library_controller.py` | Removed `show_metadata=False` from `apply_library_state` when `has_book=True` |
| `src/fabulor/themes.py` | `get_cover_panel_stylesheet`: border removed from `CoverThumbnail` QSS; `cover_preview_bg` default changed to `transparent`; `FitModeButton` padding `4px 8px 6px 8px`; `CoverAddButton` radius 0, background `#2A2A2A` |
| `NOTES.md` | `library_controller` metadata_label ownership; pre-migration preloader bypass; cover panel layout decisions |

---


# Session Summary — 2026-05-10 (session 2)

## What was done: Theme transition refinement — Themes tab, user_initiated propagation, regression fixes

---

## Bug: Playback/Sleep panel grids not updating on theme change

### Symptom
Speed and Sleep panel grids showed stale colors after a theme change until the panels were reopened.

### Root cause
The rename of `_update_speed_grid_styling` → `_refresh_panel_visuals` (prior session) was applied to the early-startup path in `_on_theme_changed` but not to the main fade path (line 248). The `hasattr` guard silently swallowed the miss.

### Fix
Updated the main path to call `_refresh_panel_visuals`. One line.

---

## Themes tab — per-element animation ruled out

### Audit findings
All color in the Settings panel Themes tab and tab bar is driven by QSS. Widget inventory:

- `QTabBar::tab` — `bg_deep` (normal), `accent` (selected), `settings_tabbar_hover_*` (hover), `accent_dark` (pane border). No `@Property`.
- `ThemeItem(QPushButton)` — `panel_theme_names_dimmed` (default text), `accent` (selected text + hover bg tint), `accent_light` (hover text). State encoded via `[selected]` and `[active_display]` dynamic Qt properties + unpolish/polish.
- Cover-mode / interval `QLabel` buttons — same two-state QSS pattern via `[selected]`.
- `QLabel#settings_header` — `accent_light` text.
- `QLabel#theme_hint` — `accent` text.
- `QPushButton#theme_add_all/remove_all/change_now` — `text`, `accent_dark`, `accent`, `button_text`.
- `QPushButton#pattern_button` — `panel_theme_names_dimmed`, `accent`, `accent_light`, `accent_dark`, `button_text`; three dynamic property states.

### Why per-element animation is not viable here

1. **Dynamic property state machine**: `ThemeItem` has three visual states (dimmed / selected / active_display). Transitions between them are not always A→B — any of the six pairwise combinations can occur. Each requires resolving the correct source and target color at flip time from the current theme dict.

2. **`QTabBar` is not customizable without subclassing**: It renders through `QStyle` internally. Animating tab colors requires overriding `paintTab`, storing per-tab `QColor` properties, and handling selected/hover/normal states manually — a substantial Qt internals job.

3. **N simultaneous instances**: Interval labels and ThemeItem buttons all flip state at once. Each instance would need its own `QPropertyAnimation`, started synchronously, with correct per-instance before/after colors.

4. **QSS `background: transparent` + `palette()` interaction**: Tested with `ThemedButton(HoverButton)` canary — setting `QPalette.Button` has no effect when QSS is active on the widget. `background: transparent` in QSS lets the window background show through instead of the palette color. The only working path is a `paintEvent` override that fills a rounded rect explicitly, then `super().paintEvent()` for text. This works but requires hardcoding the border-radius value to match QSS, and hover/pressed states lose their background change entirely (QSS `:hover` background rules don't fire when `background: transparent` is set).

### Decision
Themes tab remains QSS-driven. The overlay snap-on-open + `user_initiated` flag combination is the pragmatic solution. All other tabs are already tamed.

---

## Themes tab — overlay snap refinements

### Problem 1: Automatic theme change while Themes tab is active dissolves it
Previous fix (`user_initiated=False` + `settings_panel.isVisible()`) was too broad — it snapped even when the user was on a different tab where the overlay would be harmless.

### Fix
Narrowed the snap condition to check `tabs.currentIndex() == 0` (Themes tab) AND `settings_panel.isVisible()`. Other tabs now get the overlay normally.

### Problem 2: Off → With pool / Exclusive had no animation; reverse direction did
`apply_cover_theme` always passed `user_initiated=False`. When clicking a mode button with no cached cover theme, `set_cover_art_mode` called `apply_cover_theme(pixmap)` → snap. The reverse path (clicking Off when cover active) called `clear_cover_theme` → `_on_theme_changed(..., user_initiated=True)` → animated.

### Fix
Added `user_initiated=False` default parameter to `apply_cover_theme`. `set_cover_art_mode` passes `user_initiated=True`. Automatic call in `_on_library_hidden` keeps the default `False`.

### Problem 3: Change Now button snapped instead of animating
`change_now_btn` was directly connected to `_do_rotate`, which always passed `user_initiated=False` to `_on_theme_changed`. Timer-driven rotation and user click shared the same call.

### Fix
Added `user_initiated=False` default parameter to `_do_rotate`. Button connected via lambda passing `user_initiated=True`. Timer path unchanged.

### Problem 4: Dismissing settings panel while overlay was running dissolved the panel
`_close_settings_flow` called `_on_theme_unhovered()` (snapback for hover previews) but did not abort an in-progress non-hover fade overlay, which continued dissolving the sliding panel.

### Fix
Added `snap_theme_forward()` call immediately after `_on_theme_unhovered()` in `_close_settings_flow`. Runs before the slide-out animation starts, so the panel slides away against the settled theme.

### Attempted: delayed snap on dismiss (rejected)
Tried `snap_theme_forward(delay_ms=250)` to let the overlay partially play before snapping. Result: overlay text ghosted on screen even at 50ms delay — the overlay pixmap content was visible as a frozen artifact during the slide. Reverted. Instant snap is the only viable option.

---

## Non-obvious decisions

1. **`tabs.currentIndex() == 0` not widget identity**: The Themes tab check uses index rather than a stored widget reference to avoid holding a reference to an internal tab widget that could go stale. Index 0 is stable — tab order is fixed at build time.

2. **`user_initiated` default is `False` on `apply_cover_theme` and `_do_rotate`**: All automatic callers (book load, rotation timer, `_fire_pending_rotation`) pass no argument and get the safe default. Only explicit user-action callers pass `True`. This is fail-safe — a missed caller produces a snap, not an unwanted animation over open UI.

3. **`snap_theme_forward` checks overlay visibility, not animation state**: The animation may have already finished (opacity reached 0) while the overlay is still technically visible waiting for `_on_fade_finished`. The check `_fade_overlay.isVisible()` catches this tail case; checking only `Running` state would miss it.

---

## Files changed this session

| File | Changes |
|---|---|
| `src/fabulor/ui/theme_manager.py` | Themes-tab-active snap condition narrowed to `tabs.currentIndex() == 0`; `user_initiated` param on `apply_cover_theme` and `_do_rotate`; `_refresh_panel_visuals` regression fix in main fade path |
| `src/fabulor/ui/panels.py` | `snap_theme_forward()` added to `_close_settings_flow` alongside `_on_theme_unhovered()` |
| `src/fabulor/app.py` | `change_now_btn` connected via lambda with `user_initiated=True`; `set_cover_art_mode` passes `user_initiated=True` to `apply_cover_theme` |
| `NOTES.md` | Themes tab per-element animation complexity documented |

---


# Session Summary — 2026-05-10

## What was done: Theme fade animation — overlay approach audit and partial fix. No features.

## Problem investigated
Full-window overlay fade caused panel chrome, library rows, and cover art to morph or dissolve visibly during theme transitions when panels were open. Three distinct failure cases identified:
1. Hover preview in settings panel with panel closing mid-fade — overlay dissolves the sliding panel
2. Cover theme firing while a panel is open — overlay freezes a pixmap over actively changing UI, causing ghosts and dissolution
3. Deferred retry of automatic theme change dropping `user_initiated` flag back to `True`

## Approaches tried and rejected
- **Stylesheet interpolation** (`QVariantAnimation` driving `_apply_stylesheets` per frame) — unacceptable performance, discarded immediately
- **Full per-element Q_PROPERTY animation** — only viable long-term path but requires converting all QSS-driven widgets away from QSS for color; deferred
- **QPalette-based animation** — incompatible with 30-key semantic theme dicts across 50 themes; ruled out
- **Overlay masking (all panels)** — same user-facing result as instant snap for panels; no benefit over snap-forward

## What was implemented
- **Partial masking:** overlay masks out all visible panels except `settings_panel`, so theme previews in settings animate correctly via overlay while other panels are excluded
- **`user_initiated` flag on `_on_theme_changed`:** distinguishes automatic theme changes (cover theme, rotation timer) from user-driven ones (hover, right-click). When `user_initiated=False` and settings panel is visible, overlay is skipped and stylesheet is applied instantly
- **Deferred retry lambda bug fixed:** `_PANEL_ANIM_GUARD_MS` retry lambda was dropping `user_initiated` back to `True`; fixed by capturing it in the lambda closure
- **`snap_theme_forward()` added to `ThemeManager`:** stops fade animation and applies final theme immediately; called from `_open_settings_flow`

## Widget instrumentation (preparatory work for future per-element animation)
`@Property(QColor)` definitions added to all custom-painted widgets. No animation wiring yet — dead code for now, ready for future use:
- `ClickSlider` — already had `bg_color`, `fill_color`, `notch_color`, `notch_opacity`
- `ScrollingLabel` — `text_color`
- `BarChartWidget` — `accent_color`
- `_RangeBar` — `accent_color`, `bg_color`
- `HourlyHeatmap` — `accent_color`, `label_color`
- `BookDelegate` — 15 color properties matching all private paint attributes
- `_ElidingLineEdit` — `text_color`

## Files changed this session

| File | Changes |
|---|---|
| `src/fabulor/ui/theme_manager.py` | `user_initiated` param on `_on_theme_changed`; deferred retry lambda fix; `snap_theme_forward()` extended to abort on overlay visible (not just animation running); `user_initiated=False` on `apply_cover_theme` and both `_do_rotate` calls; overlay masking for non-settings panels |
| `src/fabulor/ui/panels.py` | `_open_settings_flow` calls `snap_theme_forward()` instead of `_abort_theme_fade()` |
| `src/fabulor/ui/controls.py` | `text_color` `@Property(QColor)` on `ScrollingLabel`; `THEME_ANIM_TODO` comment |
| `src/fabulor/ui/stats_panel.py` | `accent_color`/`bg_color` `@Property(QColor)` on `_RangeBar`; `accent_color`/`label_color` on `HourlyHeatmap`; `THEME_ANIM_TODO` comment |
| `src/fabulor/ui/library.py` | 15 `@Property(QColor)` properties on `BookDelegate`; `THEME_ANIM_TODO` comment |
| `src/fabulor/ui/book_detail_panel.py` | `text_color` `@Property(QColor)` on `_ElidingLineEdit`; `Property` added to imports; `QPixmap` removed from imports; `THEME_ANIM_TODO` comment |
| `src/fabulor/ui/chapter_list.py` | `THEME_ANIM_TODO` comment |
| `src/fabulor/app.py` | `THEME_ANIM_TODO` comment listing uninstrumented widgets |
| `NOTES.md` | "Theme Transition — Long-term Plan" section added: current state, why QPalette won't work, per-element Q_PROPERTY path, full list of widgets still needing instrumentation |

---


# Session Summary — 2026-05-09 (session 2)

## What was done: Resource leak audit + signal/slot lifecycle hardening + config correctness + theme fixes. No features.

---

## Resource leaks fixed

### `app.py` — `closeEvent`
- `_undo_timer.stop()` added after `quote_timer.stop()` — was not stopped on shutdown, could fire against widgets being destroyed.
- `_preload_restart_timer.stop()` added (guarded by `hasattr`) — parentless timer created lazily in `eventFilter`; could fire into a destroyed `library_panel` within the 5s window after close.

### `library.py` — `BookDelegate`
- `_pulse_timer`, `_scroll_timer`, `_hover_fade_timer` changed from `QTimer()` to `QTimer(self)` — parentless timers are not stopped when the delegate is destroyed.

### `library.py` — `_preload_tick`
- Preload `CoverLoaderWorker` workers now added to `_active_workers` with the same `finished`-discard pattern as the on-demand path. Previously untracked — no way to know if workers were still running when the panel closed.

---

## Signal/slot duplicate connection fixes

### `panels.py` — five `_open_*_flow` methods
All five (`_open_library_flow`, `_open_settings_flow`, `_open_speed_flow`, `_open_stats_flow`, `_open_sleep_flow`) accumulated a permanent extra `sidebar_animation.finished` → `_on_sidebar_closed_for_panel` connection each time they were called while the sidebar was expanded. Added disconnect-before-connect pattern (matching the existing `_on_sidebar_closed_for_panel` self-disconnect) to all five.

---

## Edge case hardening (`app.py`)

- **`toggle_play_pause` Restart branch** — `os.path.exists` check added before the DB writes and `load_book` call. Previously, a deleted file caused progress to be zeroed with no recovery path.
- **`_update_ui_sync` EOF duration DB read** — guarded by `_eof_dur_fetched` flag (initialized in `__init__`, reset in `_on_book_selected_from_library`). Was calling `db.get_book()` on every 200ms timer tick when EOF was reached with no duration; now fires once per book load.
- **`_on_book_removed`** — `self._current_book = None` and `self._close_session()` added before `player.terminate()`. Previously, `_current_book` was left pointing at the removed book and any open session was silently dropped without being written.

---

## Config correctness (`config.py`)

- **`get_day_start_hour`** — bare `int()` replaced with `self._safe_int("day_start_hour", 0)`. `int()` on a list (which `QSettings` can return on certain Linux Qt backends) raises `TypeError`. 13 call sites in `stats_panel.py` and `book_detail_panel.py` would have crashed the stats panel on first paint.

---

## Threading — `CoverLoaderWorker.player_instance` removed

`player_instance` parameter removed from `CoverLoaderWorker.__init__` — it was stored but never read in `run()`. Holding a live `Player` reference in the thread pool was unnecessary. All six call sites updated: two in `library.py` (pass removed), two in `stats_panel.py` (`None` argument removed), one in `tag_manager.py` (`None` argument removed).

---

## Theme fixes (`themes.py`)

- **`panel_theme_names_dimmed` — 8-character hex values** in `"Oranges Are Not the Only Fruit"` (`#8CF1F8FF`) and `"Red Rising"` (`#FFFFFFFF`) stripped to 6-character (`#8CF1F8`, `#FFFFFF`). Qt's QSS parser rejects 8-digit hex, silently dropping the color rule.
- **`panel_theme_names_dimmed` — missing from 5 themes** — added to `"Emiko"` (`#1AA652`), `"Melnibonéan"` (`#6F868A`), `"Slow Regard"` (`#B87E3A`), `"The Color Purple"` (`#6B2FAD`, lighter than `accent_dark` for legibility on near-black), `"Tigana"` (`#8A8268`). All derived from each theme's `accent_dark`; The Color Purple uses a midpoint value because `#5A189A` is near-invisible on `#1A002E`.

---

## Debounce — tag suggestion DB queries (`book_detail_panel.py`)

`_on_tag_input_changed` previously called `db.get_tag_suggestions()` on every keystroke synchronously. Added `_tag_suggest_timer` (200ms, single-shot, parented) in `__init__`. `_on_tag_input_changed` now only restarts the timer; `_do_tag_suggestions` (new method) performs the DB query when the timer fires.

---

## Deferred to NOTES.md

- `_is_running` unsynchronized flag in `ScannerWorker` — technically a data race, benign under CPython GIL. Fix requires `threading.Event`. Address in scanner refactor.
- `library_panel_animation.finished` duplicate connection risk in `_start_library_entry` / `_close_library_flow` — low-frequency race, most paths guarded. Address when panel animation code is next touched.
- Book switch state split on DB failure in `_on_book_selected_from_library` — requires transaction wrapper or rollback mechanism. Not a common failure mode.
- Sleep timer state not persisted across restarts — `get_sleep_duration` / `get_sleep_mode` written but never read on startup. Product decision deferred.

---

## Files changed this session

| File | Changes |
|---|---|
| `src/fabulor/app.py` | `_undo_timer.stop()` and `_preload_restart_timer.stop()` in `closeEvent`; `_eof_dur_fetched` flag added; `toggle_play_pause` existence check; `_on_book_removed` clears `_current_book` and calls `_close_session` |
| `src/fabulor/ui/panels.py` | Disconnect-before-connect on `sidebar_animation.finished` in all five `_open_*_flow` methods |
| `src/fabulor/ui/library.py` | `_pulse_timer`, `_scroll_timer`, `_hover_fade_timer` parented to `self`; preload workers tracked in `_active_workers` |
| `src/fabulor/ui/cover_loader.py` | `player_instance` parameter removed |
| `src/fabulor/ui/stats_panel.py` | `None` argument removed from two `CoverLoaderWorker` calls |
| `src/fabulor/ui/tag_manager.py` | `None` argument removed from `CoverLoaderWorker` call |
| `src/fabulor/ui/book_detail_panel.py` | `_tag_suggest_timer` debounce added; `_do_tag_suggestions` method added |
| `src/fabulor/config.py` | `get_day_start_hour` uses `_safe_int` |
| `src/fabulor/themes.py` | 8-char hex values fixed in two themes; `panel_theme_names_dimmed` added to five themes |
| `NOTES.md` | Scanner `_is_running` race; panel animation duplicate connection risk; book switch DB state split; sleep timer persistence gap |

---


# Session Summary — 2026-05-09 (session 3)

## What was done: path→ID migration for _cover_cache, BookModel, and signal chain — architectural debt paid

---

## Migration scope

`_cover_cache` and all BookModel internal dicts (`_covers`, `_hovered_path`, `_show_remaining`, `_live_pos`, `_live_dur`) were keyed by `book.path` (str). All are now keyed by `book.id` (int). The `CoverLoaderSignals.cover_loaded` signal changed from `Signal(str, QImage)` to `Signal(int, QImage)`.

---

## Files changed

### `cover_loader.py`
- `cover_loaded = Signal(str, QImage)` → `Signal(int, QImage)`
- `run()`: `book_path = self.book_data.path` → `book_id = self.book_data.id`; emits `book_id`

### `library.py` — `_cover_cache`
- Comment updated: `{path: QPixmap}` → `{book_id (int): QPixmap}`

### `library.py` — `BookModel.data()`
- `ROLE_COVER`: `self._covers.get(path)` → `self._covers.get(book.id)`
- `ROLE_HOVERED`: `self._hovered_path == path` → `== book.id`
- `ROLE_SHOW_REM`: `self._show_remaining.get(path, True)` → `get(book.id, True)`
- `ROLE_LIVE_POS`: `self._live_pos.get(path, ...)` → `get(book.id, ...)`
- `ROLE_LIVE_DUR`: `self._live_dur.get(path, ...)` → `get(book.id, ...)`
- Unused `path = book.path` assignment removed

### `library.py` — `BookModel` mutators
- `_trigger_cover_load`: `worker._book_path = book.path` → `worker._book_id = book.id`
- `_on_cover_loaded(path, image)` → `(book_id, image)`; cache write and `notify_cover_cached` use `book_id`
- `_on_preload_cover_loaded(path, image)` → same rename
- `_load_visible_covers`: `in_flight` set uses `_book_id`; cache hit check uses `book.id`; in-flight check uses `book.id`
- `start_idle_preload`: preload queue filtered by `b.id not in _cover_cache`
- `_preload_tick`: cache hit check and `worker._book_id` use `book.id`
- `update_playing_progress(path, ...)` → `(book_id, ...)`; dict writes and emit use `book_id`
- `toggle_show_remaining(path)` → `(book_id)`; dict write and emit use `book_id`
- `set_hovered(path)` → `(book_id)`; `previous is not None` guard (correct for int); emits use `_emit_for_id`
- `update_book_metadata(path, ...)` → `(book_id, ...)`; lookup by `book.id`; emits `_emit_for_id`
- `update_cover(path, ...)` → `(book_id, ...)`; `_covers[book_id]`; emits `_emit_for_id`
- `notify_cover_cached(path)` → `(book_id: int)`; calls `_emit_for_id`
- `_emit_for_path` deleted (zero callers remaining)
- `_emit_for_id(book_id: int)` added alongside where `_emit_for_path` was

### `library.py` — `LibraryPanel`
- `update_current_book_progress`: `path` lookup removed; uses `book = getattr(self.window(), '_current_book', None)` and `book.id`
- `_on_view_entered`: `set_hovered(self._hovered_book_path)` → `set_hovered(book.id if book else None)`
- `editorEvent`: `toggle_show_remaining(book.path)` → `toggle_show_remaining(book.id)`

### `book_detail_panel.py`
- `metadata_saved = Signal(str, str, str)` → `Signal(int, str, str)`
- `load_book` dict: `'id': full.id` added
- `_commit_inline_save`: emits `self._book_data.get('id')` instead of `self._book_path`

### `app.py`
- `_on_book_metadata_saved(path, title, author)` → `(book_id, title, author)`; passes `book_id` to `update_book_metadata`
- `_load_cover_art`: `_cover_cache.get(file_path)` → `_cover_cache.get(book.id) if book else None` (uses already-fetched `book` from line above)

### `stats_panel.py` — `BookDayRow` and `FinishedBookThumb`
- `_FT`/`_BD` anonymous objects gain `'id': row_data.get('book_id')`
- Cache hit check: `book_path in _cover_cache` → `_cover_cache.get(book_id)`; lookup uses `book_id`
- `_on_cover_loaded(path, image)` → `(book_id, image)` on both widgets

### `tag_manager.py` — `_TagBookThumb`
- `_TT` anonymous object gains `'id': book.get('book_id')`
- Cache hit and lookup use `book_id`
- `_on_cover_loaded(path, image)` → `(book_id, image)`

---

## Non-obvious decisions

1. **`data()` read side migrated alongside write side**: the internal dicts (`_show_remaining`, `_live_pos`, `_live_dur`, `_hovered_path`) are read in `data()` by key. Changing the mutators without updating `data()` would have been a silent no-op bug — all lookups would miss, returning defaults on every call.

2. **`set_hovered` guard changed from `if previous:` to `if previous is not None:`**: the old guard treated `0` (a valid int id) as falsy. `is not None` is the correct guard for an int that can legitimately be 0.

3. **`_emit_for_path` deleted, not kept as dead code**: zero callers confirmed before deletion. `update_book_metadata` and `update_cover` were the last two, both migrated in the same session.

4. **stats_panel and tag_manager constraints lifted**: the anonymous `_BD`/`_FT`/`_TT` objects and `_on_cover_loaded` handlers in those files had to be updated — there is no way to change the signal to `Signal(int, QImage)` without updating all receivers. The previously noted NOTES.md debt about fragile anonymous constructors is now paid.

5. **app.py `_load_cover_art` uses already-fetched `book`**: `db.get_book(file_path)` is already called at the top of `_load_cover_art`. The cache lookup was changed to `_cover_cache.get(book.id) if book else None` with no additional DB call.

---


# Session Summary — 2026-05-09 (session 4)

## What was done: Debt payoff — scanner thread safety, method rename, cover signal fix

---

## Scanner — `threading.Event` replacing unsynchronized `_is_running` flag

`ScannerWorker._is_running` was a plain `bool` written from the main thread and read from the worker thread with no synchronization primitive. Replaced with `threading.Event`:

- `__init__`: `self._is_running = True` → `self._running = threading.Event(); self._running.set()`
- `stop()`: `self._is_running = False` → `self._running.clear()`
- All three read sites: `if not self._is_running` → `if not self._running.is_set()`

`import threading` added at top of `scanner.py`. `LibraryScanner` untouched. NOTES.md debt entry removed.

---

## `_update_speed_grid_styling` → `_refresh_panel_visuals` rename

Method was misnamed — it orchestrates all panel visual updates on theme change, not just speed grid styling. Renamed at all 4 call sites across 2 files:

- `settings_controller.py:24` — `main._update_speed_grid_styling = ...` → `main._refresh_panel_visuals = ...`
- `theme_manager.py:216–217` — `hasattr` check and call updated (two occurrences, both replaced)

NOTES.md debt entry removed.

---

## `panels.py` — `_on_sidebar_closed_for_panel` signal connection guard

All five `_open_*_flow` methods (`_open_library_flow`, `_open_settings_flow`, `_open_speed_flow`, `_open_stats_flow`, `_open_sleep_flow`) were accumulating a permanent extra `sidebar_animation.finished → _on_sidebar_closed_for_panel` connection on each call while the sidebar was expanded. Added `_sidebar_panel_signal_connected` bool flag in `__init__`; each flow method only connects when the flag is False and sets it True; `_on_sidebar_closed_for_panel` disconnects and clears the flag on fire. Eliminates the duplicate-connection pattern and removes the RuntimeWarning on disconnect.

---

## Files changed this session

| File | Changes |
|---|---|
| `src/fabulor/library/scanner.py` | `_is_running` → `threading.Event`; `import threading` added |
| `src/fabulor/settings_controller.py` | `_update_speed_grid_styling` → `_refresh_panel_visuals` |
| `src/fabulor/ui/theme_manager.py` | `_update_speed_grid_styling` → `_refresh_panel_visuals` (2 sites) |
| `src/fabulor/ui/panels.py` | `_sidebar_panel_signal_connected` flag; disconnect-before-connect replaced with guard pattern |
| `NOTES.md` | Scanner race entry removed; rename entry removed |

---


# Session Summary — 2026-05-09 (session 5)

## What was done: Stats panel first-visit flash fixed + DPR thumbnail fix reverted

---

## Stats panel — first-visit garbled flash on Day/Week/Month tabs — FIXED

### Root cause
Each tab's `BookDayRow` widgets are constructed and inserted into the layout on first visit. Qt defers full widget realization (stylesheet propagation, font metrics, layout geometry) until the first paint. The first visible frame fired before realization was complete, producing a garbled render. Second visit was clean because the widget tree had already been realized.

### Fix
`_add_row_safely(layout, widget)` helper added to `StatsPanel`. Sets `widget.setVisible(False)` before `insertWidget`, then `setVisible(True)` immediately after. This forces Qt to fully realize the widget before it is ever painted. Applied in all three refresh methods wrapped in `setUpdatesEnabled(False/True)` with `layout.invalidate()` and `widget.updateGeometry()` after the loop.

### What was tried and failed (10+ approaches over multiple sessions)
Full history preserved in NOTES.md. Short list: DPR fix, fixed height, stretch→AlignTop, setUpdatesEnabled alone, pre-populating tabs before show(), ElidedLabel showEvent, disabling elision, ensurePolished, QTimer nudge + processEvents. None resolved it. The working fix was discovered by the user testing while a revert was being applied.

---

## Files changed this session

| File | Changes |
|---|---|
| `src/fabulor/ui/stats_panel.py` | `_add_row_safely()` helper added; all three refresh methods use it wrapped in `setUpdatesEnabled` + `invalidate` + `updateGeometry`; `QApplication` import added then removed (failed attempt cleanup) |
| `NOTES.md` | First-visit flash documented as RESOLVED; full failure history preserved |

---


# Session Summary — 2026-05-09

## What was done: Scanner hardening, DB batch write, stats panel cache

---

## Scanner — single-pass `iterdir()` + `PermissionError` guard

`_extract_metadata` previously called `book_dir.iterdir()` twice — once for cover images, once for audio files. Replaced with a single `all_files` list at the top:

```python
try:
    all_files = [f for f in book_dir.iterdir() if f.is_file()]
except PermissionError:
    return None
```

Both loops now iterate `all_files`. The `is_file()` filter moves to the single collection point — the cover loop no longer needs it inline. Returns `None` on `PermissionError`; `run_scan` skips `None` results.

---

## Scanner — cancellation check inside per-file loop

`_is_running` was checked between books but not between files within a book. Added `if not self._is_running: break` at the top of the `for idx, af in enumerate(audio_files)` loop. A cancel now exits mid-book on the next file boundary rather than waiting for all files to be processed.

---

## Scanner + DB — batch upsert with single commit

Previously `run_scan` called `db.upsert_book(metadata)` per book — one connection open/commit/close per book. Replaced with a `pending` list that accumulates metadata dicts, flushed via `db.upsert_books_batch(pending)` in two places: on cancellation (`_is_running` goes False mid-loop) and at normal loop end. No extracted metadata is lost regardless of how the scan ends.

`upsert_books_batch(book_data_list)` added to `LibraryDB` — same SQL query and param-cleaning logic as `upsert_book`, using `conn.executemany()` inside a single `_get_conn()` context. One commit for the entire scan.

---

## Stats panel — period cache + Timeline deferral

### Period cache

`get_active_periods()` was called on every tab switch and nav button press — three separate DB reads (day/week/month) even when switching back to a tab viewed moments ago. Added `_cached_active_days/weeks/months` (initialized to `None` in `__init__`). Each `_refresh_daily/weekly/monthly` only queries the DB when its cache is `None`. `_invalidate_period_cache()` clears all three; called at the top of `refresh_all()` and `refresh_current_tab()`. Nav button handlers are untouched — they reuse the cached list naturally.

### Timeline tab deferral

`_refresh_time()` (heatmap DB query) was called synchronously on tab switch before the tab widget had finished rendering. Changed to `QTimer.singleShot(0, self._refresh_time)` so it fires after the event loop tick. `animate_reveal()` remains immediate — it starts the animation regardless of whether data has arrived yet.

`QTimer` added to `stats_panel.py` imports.

---

## Library — blank covers on sort/direction change

`_on_sort_changed` and `_toggle_sort_direction` called `sort_books()` but never triggered the preloader for the newly visible items. Added `QTimer.singleShot(0, self._load_visible_covers)` after each — same fix already present on the search path.

---

## Files changed this session

| File | Changes |
|---|---|
| `src/fabulor/library/scanner.py` | Single-pass `iterdir()`; `PermissionError` guard returning `None`; cancellation check inside audio file loop; `pending` batch list replacing per-book `upsert_book` calls |
| `src/fabulor/db.py` | `upsert_books_batch()` added |
| `src/fabulor/ui/stats_panel.py` | `_cached_active_*` vars in `__init__`; cache check in `_refresh_daily/weekly/monthly`; `_invalidate_period_cache()` added; `refresh_all`/`refresh_current_tab` invalidate on entry; Timeline tab deferred via `singleShot`; `QTimer` imported |
| `src/fabulor/ui/library.py` | `singleShot(0, _load_visible_covers)` after sort in `_on_sort_changed` and `_toggle_sort_direction` |

---


# Session Summary — 2026-05-08

## What was done: Book switch sequence — cover loading, position restore, theme change timing

---

## Cover loading on book switch — async path

`_start_cover_load_async(path)` added to `app.py`. On book switch, checks `_cover_cache` for a hit first. On cache hit, calls `_apply_main_cover(pixmap)` immediately. On miss, dispatches a `CoverLoaderWorker` with a one-shot `QueuedConnection` to `_on_main_cover_loaded`. Falls back to `_load_cover_art(path)` (synchronous mutagen path) when no `cover_path` is recorded.

`_apply_main_cover(pixmap)` extracted from `_load_cover_art` — shared by the sync and async paths. Handles the `_pending_cover_pixmap` deferral logic.

`_on_book_selected_from_library` now calls `_start_cover_load_async(path)` instead of `_load_cover_art(path)`.

### Known issue — cover cache miss path still hits mutagen

The async path only avoids mutagen when `cover_path` is in `_cover_cache`. On a cache miss with a valid `cover_path`, a `CoverLoaderWorker` is dispatched. But when `cover_path` is None (book was added without a cached path), `_load_cover_art` is called as fallback, which still calls `player.extract_cover()` → mutagen. The cache is not populated for the main page independently of the library panel having previously loaded it. This remains unresolved.

---

## Position restore — moved to load time

Position computation moved out of `_restore_position` into `_on_book_selected_from_library`, before `player.load_book()`:

```python
config_pos = self.config.get_last_position(path)
if config_pos > 0:
    self.db.update_progress(path, config_pos)
book_data_pre = self.db.get_book(path)
start_pos = book_data_pre.progress if book_data_pre else 0
self.player.load_book(path, start=start_pos)
```

### Attempt: loadfile `start=` option

`load_book` was extended with `start: float = 0`. When `start > 0`, used `instance.loadfile(path, start=str(int(start)))` instead of `instance.play(path)`. python-mpv's `loadfile` accepts `**options` encoded as `key=value` and passed to mpv's loadfile command.

**Result: did not work.** mpv reported `time_pos=0.0` in `_on_file_ready` regardless of the `start=` value and format tried (`str(int(start))`, `f"+{int(start)}"`). The `loadfile` options string is supported by mpv but the specific python-mpv version in use either doesn't pass it through or the file type ignores it. The approach was abandoned.

**Reverted** `load_book` back to always using `instance.play(path)`, removed `start` parameter.

### Working solution: deferred `time_pos` assignment

Position is computed in `_on_book_selected_from_library` and committed to the DB before `load_book`. `_restore_position` (called from `_on_file_ready`) re-reads from DB after the config sync, then:

```python
self.player.is_seeking = True        # immediate — blocks slider animation from snapping to 0
QTimer.singleShot(50, lambda: self._do_seek(progress))
```

`_do_seek` was later simplified to a direct `time_pos` assignment after testing confirmed `time_pos` assignment works reliably once `_on_file_ready` has fired (duration is available, mpv is ready). `is_seeking = True` is set immediately; `time_pos` assigned in the same call. The 50ms timer and `_do_seek` were removed.

### `_restore_position` current state

- Volume restore deferred via `QTimer.singleShot(0, ...)` to avoid blocking the file-ready path
- `config_pos` sync + DB re-read for accurate progress after sync
- `is_seeking = True` set before `time_pos` assignment
- Speed restore and audio tab sync remain synchronous

---

## Theme change timing — wait for slider animations

### Problem

`apply_cover_theme` was called inside `_on_library_hidden` (fires when the 300ms library slide-out finishes). The slider flow animation runs 200–600ms. The reveal (notch fade-in) runs 300–1200ms after flow finishes. Theme change landing during flow caused an abrupt color change that paused the animation mid-flight.

### Attempts

**Fixed 350ms timer**: moved `apply_cover_theme` call 350ms after `_on_library_hidden`. Cleared the flow animation but the chapter notches changed color abruptly when they appeared.

**Include sliders in fade**: removed `progress_slider` and `chapter_progress_slider` from `_apply_fade_mask` exclusions. Sliders do not crossfade smoothly — the stylesheet update pauses the animation. Reverted.

**Removed all mask exclusions** (`_apply_fade_mask` now calls `clearMask()`): since the theme change is deferred until after all animations, no exclusions needed. The percentage label no longer needs to be punched out.

### Working solution: `when_animations_done` on the slider

`when_animations_done(callback)` added to `ClickSlider` (controls.py). Checks `_flow_anim` first — if running, connects a one-shot to its `finished` which recursively calls `when_animations_done` after flow. Then checks `_reveal_anim` — if running, connects a one-shot to fire the callback after reveal. If neither is running, calls immediately.

`_on_library_hidden` uses this:
```python
slider.when_animations_done(lambda: mw.theme_manager.apply_cover_theme(pixmap))
```

Theme change now fires only after both flow and notch reveal are complete. No timers.

### `_apply_fade_mask` removed

Method and all mask logic removed entirely. `_on_theme_changed` now calls `self._fade_overlay.clearMask()` unconditionally. `QRegion` and `QPoint` imports removed from `theme_manager.py`.

---

## Theme fade snap-forward on panel open

### Problem

Theme fade animation runs 750ms. If the user opens any panel during that window, the stale screenshot overlay (showing the old theme) slides in with the panel, ghosts over the content, and fades out mid-browse.

### Fix

`abort_theme_fade()` added to `ThemeManager`: stops `_fade_anim` if running and hides the overlay immediately. The new stylesheet is already applied underneath — stopping the overlay reveals it instantly (snap forward, not back).

`_abort_theme_fade()` helper added to `PanelManager`, calls `theme_manager.abort_theme_fade()`. Called at the top of every panel open entry point: `_open_library_flow`, `_open_settings_flow`, `_open_speed_flow`, `_open_stats_flow`, `_open_sleep_flow`, `open_book_detail`.

---

## Random theme rotation — panel-aware deferral + timer reset

### Panel-aware deferral

`_rotate_theme` now checks `is_any_panel_visible()` before rotating. If a panel is open, sets `_pending_rotation = True` and returns. `_notify_panel_closed()` added to `PanelManager` — called at the end of every `_on_*_hidden` handler. If no panels remain visible, calls `theme_manager._fire_pending_rotation()`, which fires `_rotate_theme` via a 3000ms `QTimer.singleShot`. The 3s delay avoids a theme change landing immediately after panel close (book load, slider animation, etc. may still be settling).

Manual "Change now" button connected to `_do_rotate` instead of `_rotate_theme` — bypasses the panel-visible guard so it always works while settings are open.

### Timer reset on manual change

`_restart_rotation_timer()` added: restarts the rotation timer from the current interval. Called after every manual theme activation (`_on_theme_right_clicked`) and after every successful rotation (`_do_rotate`). Prevents the timer firing 10 seconds after a manual change.

### `get_current_theme` dict key fix

`get_current_theme()` was passing `_active_display_theme` directly to `THEMES.get()`. When the cover theme (a dict) is being previewed via hover, `_active_display_theme` is set to the dict, causing `TypeError: unhashable type: 'dict'`. Fixed: check `isinstance(active, dict)` and resolve via `_resolve_theme()` in that branch.

---

## Cover cache hit in `_load_cover_art`

`_apply_main_cover(pixmap)` extracted from `_load_cover_art` — handles show/hide, scaling, and `_pending_cover_pixmap` deferral logic. Shared by cache-hit and mutagen paths.

`_load_cover_art` now checks `_cover_cache.get(file_path)` before calling `player.extract_cover()`. Cache is keyed by audiobook path (same key `CoverLoaderWorker` emits). On hit: calls `_apply_main_cover` and returns immediately — no mutagen. On miss: falls through to `player.extract_cover()` as before. Import kept scoped inside the method to avoid circular import risk.

Cache is only populated when the library panel has loaded that book's cover in the current session. Cold start confirmed: `keys=0`, always a miss on first book load if library was never opened. On warm session (library opened at least once), subsequent book switches hit the cache and skip mutagen entirely.

---

## Panel close delay on book switch

`panel_manager.hide_all_panels()` fires immediately on book select, `player.load_book()` called directly after on the same thread. mpv initialization competes with the slide-out compositor on slower loads. Moving `load_book` after animation finish requires deferring all book-switch logic. Accepted as-is.

---

## Sidebar close — pending rotation not firing

`_notify_panel_closed` was never called when the sidebar closed by plain toggle (no panel opening). `_on_sidebar_closed_for_panel` disconnects itself immediately and only fires when a panel needs to open after collapse. A plain close had no completion handler.

Fix: permanent `sidebar_animation.finished` connection to `_on_sidebar_hidden` added in `__init__`. `_on_sidebar_hidden` calls `_notify_panel_closed` only when `sidebar_expanded` is False (closing direction). Coexists safely with `_on_sidebar_closed_for_panel` — both can be connected simultaneously.

`Qt.UniqueConnection` removed from `_toggle_sidebar` (was broken — only works with QObject member function pointers, not Python callables; was accumulating duplicate connections silently). `Qt` and `QEasingCurve` removed from panels.py imports as now unused.

---

## `cover_loader.py` — `os.path.exists` guard

`CoverLoaderWorker.run()` now checks `os.path.exists(cover_source_path)` before calling `QImage.load()`. Guards against stale paths (deleted file, moved library). Null image emitted on miss — `_on_cover_loaded` discards it as before. `import os` already present.

---

## Library blank covers on sort change

`_on_sort_changed` and `_toggle_sort_direction` were missing `QTimer.singleShot(0, self._load_visible_covers)` after `sort_books()`. Sort changed the visible item set but the preloader was never triggered for the new range. Same fix as the existing search path (line 475).

---

## Files changed this session

| File | Changes |
|---|---|
| `src/fabulor/app.py` | `_apply_main_cover` added; `_load_cover_art` uses `_cover_cache` hit check; position computation before `load_book`; `_restore_position` simplified; `is_seeking` set immediately |
| `src/fabulor/ui/library.py` | `QTimer.singleShot(0, self._load_visible_covers)` after sort in `_on_sort_changed` and `_toggle_sort_direction` |
| `src/fabulor/player.py` | `load_book` `start` param added and removed (loadfile failed); `seekable` property added |
| `src/fabulor/ui/controls.py` | `when_animations_done(callback)` added to `ClickSlider` |
| `src/fabulor/ui/panels.py` | `_on_library_hidden` uses `when_animations_done`; `_notify_panel_closed` on all hidden handlers; `_abort_theme_fade` on all open flows; `_on_sidebar_hidden` permanent connection; `Qt`/`QEasingCurve` imports removed |
| `src/fabulor/ui/theme_manager.py` | `_apply_fade_mask` removed; `abort_theme_fade()` added; `_pending_rotation` + `_fire_pending_rotation` + `_restart_rotation_timer` + `_do_rotate` added; `get_current_theme` dict key fix |
| `src/fabulor/ui/cover_loader.py` | `os.path.exists` guard added |

---


# Session Summary — 2026-05-07 (session 2)

## What was done: Cover loader thread-safety fix — QPixmap→QImage in worker

---

## Problem

`CoverLoaderWorker.run()` was constructing and loading a `QPixmap` on a threadpool worker thread. `QPixmap` requires the main (GUI) thread — constructing it off-thread is undefined behavior in Qt and triggers `QPainter` failures at paint time.

---

## Fix

### cover_loader.py
- `QPixmap` import removed; `QImage` added
- `CoverLoaderSignals.cover_loaded` signal changed from `Signal(str, QPixmap)` to `Signal(str, QImage)`
- `run()` now constructs and loads a `QImage` (safe on any thread), emits it

### library.py
- `QImage` added to QtGui imports
- `_on_cover_loaded(path, image)` — renamed parameter, added `QPixmap.fromImage(image)` conversion as first step before existing DPR / cache / notify logic
- `_on_preload_cover_loaded(path, image)` — same pattern (this handler also receives the same signal via the same worker)

### stats_panel.py
- `CoverLoaderWorker`, `_cover_cache` (from `.library`), `QThreadPool`, `QImage` added to imports
- `BookDayRow.__init__`: cover loading replaced with placeholder-first async pattern — load `fabulor.ico` immediately, check `_cover_cache` for a hit, else dispatch worker
- `BookDayRow._on_cover_loaded` / `_apply_cover` added — grayscale conversion for deleted books preserved
- `FinishedBookThumb.__init__`: same pattern
- `FinishedBookThumb._on_cover_loaded` / `_apply_cover` added — crop-to-square logic preserved from original

### tag_manager.py
- `CoverLoaderWorker`, `_cover_cache`, `QThreadPool`, `QImage` added to imports
- `_TagBookThumb.__init__`: cover loading replaced with placeholder-first async pattern
- `_TagBookThumb._on_cover_loaded` / `_apply_cover` added

---

## Shared cache

All three stats/tag widgets import `_cover_cache` directly from `.library` — the same module-level dict the library preloader and main cover loader write to. No second cache created.

---

## Known debt logged

`CoverLoaderWorker` is constructed with an anonymous type object in three places (`stats_panel.py` × 2, `tag_manager.py` × 1) because it was designed for a `Book` dataclass + player instance. This is noted in NOTES.md. Resolution deferred to the path→ID migration.

---

## Files changed this session

| File | Changes |
|---|---|
| `src/fabulor/ui/cover_loader.py` | `QPixmap`→`QImage` in signal and `run()`; `QPixmap` import removed |
| `src/fabulor/ui/library.py` | `QImage` import added; both cover-loaded handlers convert `QImage`→`QPixmap` on main thread |
| `src/fabulor/ui/stats_panel.py` | `BookDayRow` and `FinishedBookThumb` deferred, cache-aware cover loading |
| `src/fabulor/ui/tag_manager.py` | `_TagBookThumb` deferred, cache-aware cover loading |

---


# Session Summary — 2026-05-07

## What was done: Tag UX polish — chips, add field, tag manager row styling, completer popup theming

---

## Tag chip styling (book detail Tags tab)

### New theme rules in `get_stats_stylesheet()`

- `QWidget#tag_chip` — pill shape: `background rgba(accent, 0.12)`, `border rgba(accent, 0.40)`, `border-radius: 12px`. Requires `chip.setAttribute(Qt.WA_StyledBackground, True)` — without it QWidget does not paint background or border regardless of QSS rules.
- `QWidget#tag_chip QLabel#tag_chip_label` — `accent_light`, 14px, `background: transparent; border: none` to prevent inheritance bleed from parent chip border.
- `QWidget#tag_chip QPushButton#tag_chip_remove_btn` — borderless ×, `accent_light` at 60% opacity, goes full `text` color on hover.
- `QPushButton#stats_nav_btn` base + `:hover` — the ‹ back button in the tag panel previously only had a `:disabled` rule; no base style caused it to render as a raw system button.
- `QWidget#tag_manager_row QLabel#tag_chip_label` — tag name in list rows gets full-brightness `text` at 13px to visually separate it from the dimmed count label (`stats_key_label`) beside it.

### `WA_StyledBackground` on tag manager rows

`_make_tag_row` in `tag_manager.py` needed `row.setAttribute(Qt.WA_StyledBackground, True)` for the hover background to paint. Without it the `:hover` rule is parsed but ignored.

### Add field and + button

The tag input and add button previously shared `metadata_field` and `book_detail_close_btn` object names — they had no independent styles. Renamed to `tag_add_field` and `tag_add_btn` and given dedicated rules:

- `tag_add_field`: `bg_dropdown` at 60% opacity, `accent_dark` border sharpening to `accent` on `:focus`, 13px.
- `tag_add_btn`: solid `accent` background, 18px bold `+`, proper hover/pressed states.

### Add field hidden at 5 tags

The input row is wrapped in `self._tag_input_widget` (a `QWidget`, not a bare layout) so `setVisible(len(tags) < 5)` hides it when the per-book limit is reached. Previously it was a bare `QHBoxLayout` which cannot be hidden.

### FlowLayout `heightForWidth`

`hasHeightForWidth` was returning `False`; the outer `QVBoxLayout` could not know how tall the chip container needed to be. Implemented `heightForWidth(width)` calling `_do_layout(QRect(0,0,width,0), test_only=True)`, which returns the exact pixel height for any given container width. Removed all manual `setMinimumHeight` estimates from `_rebuild_tag_chips` — the layout drives height automatically. This fixed the add field drifting down with each chip added (the old worst-case height estimate reserved too much space).

### FlowLayout default margins

`FlowLayout` inherits Qt's default widget layout margins (11px on all sides) unless explicitly zeroed. The chip container's left edge was visually 11px further right than the stats grid in the same tab. Fix: `self._tag_chip_layout.setContentsMargins(0, 0, 0, 0)` after construction.

### Tags tab padding alignment

All three tabs (Stats, History, Tags) now use identical `setContentsMargins(10, 10, 10, 10)` and `setSpacing(8)`. Tags tab previously had `setSpacing(10)` — 2px difference is immediately visible when switching between adjacent tabs that share bar/percentage rows in their first content row.

### `● tag` display — multi-word tags

`_rebuild_tag_display` already used NBSP (`\xa0`) between bullet and tag name to prevent line-breaking. Multi-word tags (e.g. "space opera") could still break between their words. Fix: `t.replace(' ', '\xa0')` inside the f-string so all internal spaces in a tag become NBSP. The separator between distinct tags remains en-space (valid break point) so tags can wrap between them, never within them.

### "Recent history" label spacing

`QLabel#stats_history_header` `margin-top` raised from `0px` to `5px` to push the "Recent history" heading down and eliminate clipping of the descender on "Remaining" immediately above it.

---

## Completer popup theming

The `QCompleter` popup is a top-level `QAbstractItemView` widget — it does not inherit the panel's stylesheet (set on `book_detail_panel`) or the main window's base stylesheet. It must be styled directly via `completer.popup().setStyleSheet(...)`.

### Implementation

`_style_completer_popup()` method on `BookDetailPanel`. Reads `bg_dropdown`, `text`, `accent`, `accent_dark` from `self._theme` and applies a stylesheet directly to `self._tag_completer.popup()`. Called from `on_theme_changed` and from `_on_tag_input_changed` (each time suggestions are populated).

### Why not at build time

`completer.popup()` returns `None` until the user first types — Qt creates the popup widget lazily. `_style_completer_popup()` has an early-return guard for `popup is None`. The first call where the popup actually exists (first keystroke that produces suggestions) applies the style. Subsequent theme changes re-apply it because the popup persists after first creation.

### Completer popup reappearing after selection

Selecting from the popup called `_on_tag_completer_activated → _on_add_tag`, which cleared the input. `textChanged` fired during `clear()`, calling `_on_tag_input_changed`, which repopulated the model, causing the popup to reappear. Fix: `self._tag_completer_model.setStringList([])` before `self._tag_input.clear()` in `_on_add_tag` — model is empty before the clear, so the popup has nothing to show when `textChanged` fires.

---

## Files changed this session

| File | Changes |
|---|---|
| `src/fabulor/themes.py` | `tag_chip`, `tag_chip_label`, `tag_chip_remove_btn`, `tag_add_field`, `tag_add_btn`, `stats_nav_btn` base+hover rules added; `tag_manager_row` label color; chip `border-radius` 10→12px; chip label font 12→14px; `stats_history_header` `margin-top` 0→5px |
| `src/fabulor/ui/book_detail_panel.py` | `WA_StyledBackground` on chips; chip padding `(10,5,7,5)`, × btn 16→18px; FlowLayout spacing 8/8; FlowLayout `setContentsMargins(0,0,0,0)`; `_tag_input_widget` wrapper for hide/show; Tags tab spacing 10→8; `_style_completer_popup`; `_tag_completer` stored as instance var; completer model cleared before input clear; `t.replace(' ', '\xa0')` in tag display |
| `src/fabulor/ui/tag_manager.py` | `WA_StyledBackground` on tag list rows |
| `src/fabulor/ui/flow_layout.py` | `hasHeightForWidth` returns `True`; `heightForWidth` implemented |

---


# Session Summary — 2026-05-06 (session 5)

## What was done: Tag manager, library search extensions, book detail tag display

---

## Tag manager (Stats ⚙ tab)

New `TagManagerWidget` in `src/fabulor/ui/tag_manager.py`. Two-state widget inside the ⚙ tab:

**Tag list state**: scrollable list of all unique tags, each row showing tag name + book count. Click a row to open its panel.

**Tag panel state**: back button (‹), inline rename field (Enter to save), Delete tag button, book count label, scrollable 3-column thumbnail grid of associated books. Clicking a thumbnail removes that book from the tag immediately and reflows the grid. When the last book is removed, the tag is deleted and the view returns to the list automatically.

### DB methods added

- `get_all_tags()` — all unique tags with count, alphabetical
- `get_books_by_tag(tag)` — books with path, title, author, cover_path
- `rename_tag(old, new)` — updates all books; returns False if new name already exists
- `delete_tag(tag)` — removes from all books
- `get_unique_tag_count()` — for enforcing global limit
- Global 50-tag limit enforced in `add_book_tag()` — only applies when adding a genuinely new tag, not when tagging a second book with an existing tag

### Sync wiring

`BookDetailPanel.tags_changed` signal added, emitted on add and remove. Connected in `app.py` to `stats_panel._on_tag_changed`, which refreshes the tag manager list and book detail chips in both directions. Tag manager refreshes on ⚙ tab open via `_on_tab_changed`.

### Non-obvious decisions

1. **`filter_empty` vs `_filter_no_match`**: the fallback-to-all-books behavior and the red indicator contradict each other if you use `len(self._filtered) == 0`. Solution: track `_filter_no_match` separately in `_apply_filter_and_sort` before the fallback is applied, then expose it as `filter_empty` after `endResetModel()`.

2. **`_is_incomplete_year_filter`**: prevents red background while the user is mid-typing a year filter. Rules: single `<`/`>` with any number of digits = incomplete. Two different operators with second number under 4 digits = incomplete. Same operator twice (`>2020>`) = never incomplete, goes red immediately. Impossible range (`<2000>2010`) = 4 digits on both sides = complete + invalid = red.

3. **`\xa0` between bullet and tag, ` ` between tags**: `setWordWrap(True)` on a QLabel breaks at any space. Non-breaking space (`\xa0`) glues `●` to the tag name. En-space (` `) between tags gives Qt a valid break point between them only. This prevents `●` appearing alone at end of line.

4. **Tag max length 25 chars**: started at 30, tried 20, settled on 25. DB migration truncates existing longer tags on startup. UI enforces via `setMaxLength(25)`.

5. **No tag display in library rows**: considered but rejected. Rows are already dense; no space without layout compromises. Tag search (`#tag`) provides the discovery mechanism instead.

---

## Library search extensions

Search now supports:
- `#tag` — prefix match across all tags (e.g. `#gr` finds `grimdark`, `gripping`)
- `>NNNN` — books with year ≥ N
- `<NNNN` — books with year ≤ N
- `>NNNN<NNNN` or `<NNNN>NNNN` — year range, inclusive both ends
- Plain text — title/author/narrator; year only if exactly 4 digits (avoids `19` matching all 1900s books)
- No match → show all books + dark red background on search field (`rgba(120,0,0,0.6)`)
- Clearing or fixing the search clears the background
- Reopening the library panel clears a no-match search field automatically
- `<` and `>` prefixed searches never go red (incomplete by definition until digits follow)
- `Hear Me Roar` and `Red Rising` themes override error text to `#cc0000` (their normal text is already pinkish, `#ffaaaa` would be invisible)
- `BookModel` now takes `db` parameter for tag lookup

---

## Book detail — tag display row

Read-only centered tag row between header and tabs. Single `QLabel` with `setWordWrap(True)` and `AlignCenter`. Hidden when book has no tags.

Format: `● tag1  ● tag2  ● tag3` — bullets and tags joined with en-spaces as break points, non-breaking space between bullet and tag name.

Style: `tag_display_chip` — 11px, `accent_light` color, no border, 2px vertical padding.

### Things tried and rejected

- **FlowLayout with stretch centering**: FlowLayout left-aligns; wrapping inner widget width fights the outer stretch. Abandoned for single QLabel.
- **Individual chip QLabels in HBoxLayout**: only showed one chip (layout didn't know to wrap).
- **Border/box chip style**: looked cluttered; dot-separated plain text is cleaner.
- **`· tag · tag`** interpunct separator: bullet before each tag (`● tag`) reads better and keeps the dot with its tag on wrap.

---

## Files changed this session

| File | Changes |
|---|---|
| `src/fabulor/ui/tag_manager.py` | New file — `TagManagerWidget`, `_TagBookThumb`, `_TagBookGrid` |
| `src/fabulor/db.py` | `get_all_tags`, `get_books_by_tag`, `rename_tag`, `delete_tag`, `get_unique_tag_count`; global 50-tag limit in `add_book_tag`; 25-char migration on startup |
| `src/fabulor/ui/book_detail_panel.py` | `tags_changed` signal; tag display row (`_tag_display_label`); `_rebuild_tag_display`; max tag length 25; header bottom margin 4px |
| `src/fabulor/ui/stats_panel.py` | Tag manager wired into ⚙ tab; `_on_tag_changed` refreshes both directions; refresh on tab open |
| `src/fabulor/ui/library.py` | `BookModel` takes `db`; `_parse_year_range`; `_is_incomplete_year_filter`; full search grammar; `filter_empty` / `_filter_no_match`; red background on no-match; clear on reopen |
| `src/fabulor/app.py` | `book_detail_panel.tags_changed` connected to `stats_panel._on_tag_changed` |
| `src/fabulor/themes.py` | `tag_display_chip` style; `tag_manager_row` hover style; `QSpinBox` height reduced |

---


# Session Summary — 2026-05-06 (session 4)

## What was done: Book detail History tab, session row layout tuning, field elision, library polish

---

## New: History tab in Book Detail Panel

Added a third tab "History" between Stats and Tags. Contains its own `SessionListWidget` (`_history_session_list`) populated with the same session data as the one in the Stats tab. Both lists receive the same `set_data()` and `set_colors()` calls in `_refresh_stats()` and `_apply_bar_colors()`.

The "Listening history" header in the Stats tab renamed to "Recent history".

---

## Session row layout tuning (`SessionListWidget._make_row`)

Goal: bar should be wide with roughly equal space on both sides of it.

- Timestamp label: `110 → 92px`, double space + ` – ` → single space + `–` (no spaces around dash)
- Delta label (`+%`): `42 → 36px`
- Pct label: `36 → 32px`
- Row spacing: `8 → 4px`
- Added `hbox.addSpacing(6)` between delta label and bar to balance left/right margins around the bar

Month format was already `%b` (3 letters), confirmed no change needed.

---

## Book detail header — read-only field elision (`_ElidingLineEdit`)

Fields (title, author, narrator, year) are `QLineEdit` widgets. In read-only mode Qt scrolls to show the end of long text, clipping the left side. Goal: show from the left, elide on the right.

### What was tried and failed

1. **`_ElidingLineEdit` with `PE_PanelLineEdit` draw** — elided correctly but shifted 2-3px right on entering edit mode. Root cause: `PE_PanelLineEdit` draws a border/padding in read-only that differs from the stylesheet-applied state in edit mode.
2. **`super().paintEvent()` then overdraw text** — double-vision ghost: Qt drew the scrolled text, overdraw painted elided text on top.
3. **`super().paintEvent()` + `fillRect(palette().base())`** — fields have `background: transparent` in stylesheet; `palette().base()` painted a solid color rectangle over them.
4. **`super().setText(elided)` → `super().paintEvent()` → `super().setText(full)`** — no text appeared at all; `setText` triggers signals and layout recalculations that interfere with paint.
5. **`self.rect().adjusted(2, 0, -2, 0)`** — correct geometry, no shift on edit. But `contentsMargins()` + `textMargins()` approach used `SE_LineEditContents` which returned a different inset than what Qt uses internally.

### Working solution

Skip `PE_PanelLineEdit` entirely. Draw only the text using `self.rect().adjusted(3, 0, -2, 0)` — the 3px left margin matches Qt's hardcoded internal text offset. `setCursorPosition(0)` called in `_enter_edit_mode` and `_sync_header_from_fields` keeps fields anchored left in both states, eliminating the scroll-to-end artifact. Result: no ghost, correct elision, no shift on edit.

### Non-obvious facts

- Qt's internal horizontal text margin for `QLineEdit` is 3px (not 2, not from `textMargins()`). Empirically determined by pixel-comparing read-only and edit mode screenshots in Gimp — one arrow-key nudge = 1px difference.
- `setCursorPosition(0)` must be called both when loading a book and when exiting edit mode (`_sync_header_from_fields`) — not only in `_enter_edit_mode` — otherwise the first display of a long title still shows from the right.
- Duration label left margin bumped `2 → 3px` to align with the elided fields after the 3px offset was established.

---

## Library — cover display: stretch-to-fill for near-identical ratios

Added a third branch in `_draw_cover()` before the existing crop-to-fill (8% tolerance):

- `ratio_diff < 0.02`: stretch to fill exactly via `painter.drawPixmap(rect, cover, cover.rect())` — no crop, no letterbox, distortion sub-pixel at cell sizes.
- `ratio_diff < 0.08`: crop to fill (existing behavior).
- `≥ 0.08`: letterbox (existing behavior).

Covers measured to verify thresholds:
- Sorrow of War (224×344 = 0.6512): 0.88% from 2-per-row cell → stretch
- The Good Soldier (222×344 = 0.6453): 1.78% from cell → stretch
- Annihilation (226×328 = 0.6890): 4.87% from cell → still crops (white border eaten, acceptable)

### Non-obvious decision

Annihilation's white border is cropped because 4.87% stretch would be noticeable on its bold typography. The crop is imperceptible to users not specifically looking for it. Decision: leave it.

---

## Library — search thumbnail loading fix

`_on_search_changed` called `filter_books()` which triggered `beginResetModel()`/`endResetModel()`, but never called `_load_visible_covers()` afterwards. Covers for newly-visible books after a search were only loaded on next scroll, not immediately. Fix: added `QTimer.singleShot(0, self._load_visible_covers)` after `filter_books()`.

---

## Stats panel settings tab — "Day starts at" label style + spinner size

- Label given `objectName("settings_header")` to match other settings section headers (bold, 14px, `accent_light`).
- Spinner `setFixedWidth(56)` to keep it compact.
- `QSpinBox` stylesheet: `padding: 1px 2px; max-height: 22px` to reduce height.

---

## Planned but not started: Tag manager in Stats settings tab

Design agreed:
- Tag list: chips with book count. No per-chip buttons in the list.
- Click a chip → panel replaces tag list in the same area (fixed top anchor). Tag name editable inline at top, delete button for the whole tag.
- Scrollable thumbnail grid of associated books. Click thumbnail → removes tag from that book immediately, thumbnail disappears, column reflows vertically.
- Day-starts-at spinner and Reset button stay anchored at the bottom, always visible.
- Tag limit: 50 unique tags enforced at add time.
- DB methods needed: `get_all_tags()`, `get_books_by_tag()`, `rename_tag()`, `delete_tag()`.

---

## Files changed this session

| File | Changes |
|---|---|
| `src/fabulor/ui/book_detail_panel.py` | History tab added; `_ElidingLineEdit` with 3px left margin; `setCursorPosition(0)` in `_sync_header_from_fields`; duration label margin `2→3px`; "Recent history" rename |
| `src/fabulor/ui/stats_panel.py` | `_make_row` layout tuned (widths, spacing, 6px gap before bar); settings tab label styled + spinner fixed width |
| `src/fabulor/themes.py` | `QSpinBox` max-height and padding reduced |
| `src/fabulor/ui/library.py` | `_draw_cover` stretch-to-fill branch at 2% threshold; `_load_visible_covers` after search filter |

---


# Session Summary — 2026-05-06 (session 3)

## What was done: Book Detail Panel redesign + stats panel label styles

---

## Stats panel — period label styling

`QLabel#stats_day_label` added to `get_stats_stylesheet()`: 16px, `accent` color. Sits above `stats_day_total` (bold, 15px, `accent_light`) to create a clear date/total hierarchy within each tab.

`QLabel#stats_session_label` added: 13px, `accent_light` — used in `SessionListWidget` rows, 1px larger than the general `stats_key_label` (12px).

---

## Book Detail Panel — full redesign

### Stats tab restructure

- **Furthest position row**: label + custom `_RangeBar` (stretches) + percentage label, all on one line in a `QGridLayout` row. Bar uses `curr_chap_highlight` fill / `library_slider_bg` background from the active theme. Colors applied on load and on theme change via `_apply_bar_colors()`.
- **Remaining**: own grid row below furthest position. Speed-aware: shows `"Xh Ym at 2x"` when speed ≠ 1.0.
- **Last session**: new grid row after Sessions. Shows date, time (24h), and duration of most recent session.
- **Listening history header**: `QLabel#stats_history_header` — bold, 15px, `accent_light`, matching settings headers.
- **Listening history**: `BarChartWidget` replaced with `SessionListWidget` — a `QScrollArea` (no scrollbar) containing per-session rows. Each row: timestamp + end time (`May 6  03:08 – 03:21`), stretching `_RangeBar` showing position slice, percentage at right. All on one line.
- **`_RangeBar`**: custom `QWidget` painting a flat filled rectangle. `update_range()` and `set_colors()` for live updates. 1px semi-transparent accent outline.
- **Delete listening history**: moved from Stats tab to Tags tab bottom.

### New DB method

`db.get_book_sessions(book_path)` — returns individual sessions newest-first with `session_start`, `listened_seconds`, `position_start`, `position_end`.

### DB performance additions

- **WAL mode**: `PRAGMA journal_mode=WAL` set on every connection. Allows simultaneous reads and writes, improving UI responsiveness during background scans.
- **Composite index**: `idx_sessions_path_start ON listening_sessions (book_path, session_start)` — speeds up per-book session history lookups which sort by `session_start DESC`.

### Header — duration label

`_ClickableLabel` added after year. Shows wall-clock duration by default (`18h 30m`). If book speed ≠ 1.0x, clicking toggles to speed-adjusted (`9h 15m at 2x`) and back. Resets to wall-clock on each `load_book`. Hidden when no duration data.

Implemented as a proper `_ClickableLabel` subclass (Signal + `mousePressEvent` override) — assigning to `mousePressEvent` on a `QLabel` instance is silently ignored by Qt's C++ event dispatch.

### Header — inline metadata editing

Fields (title, author, narrator, year) are always-present `QLineEdit` widgets styled to look like labels: `background: transparent; border: 1px solid transparent; padding: 0px; margin: 0px`. `setFrame(False)` removes Qt's internal frame padding. `setReadOnly(True)` at rest.

Click any field → `_enter_edit_mode()`: all four go `setReadOnly(False)`, narrator and year become visible (were hidden if empty), `_check_dirty()` connected to `textChanged`.

`_check_dirty()`: compares current text against `_orig_*` values captured on entry. Save label appears only when something actually differs; disappears if you type back to match.

Save label (`_ClickableLabel`, `accent` color, right-aligned) sits on the same row as the duration label (HBoxLayout: duration left, stretch, Save right).

Exiting edit mode (click outside / Enter / tab change / close):
- **Revert**: `setReadOnly(True)`, restore text from `_book_data`, hide narrator/year if empty, hide Save.
- **Save**: commit to DB, emit `metadata_saved`, show "Saved" for 1 second then hide.

App-level event filter (`QApplication.instance().installEventFilter(self)`) catches all mouse presses. If editing and click is outside the four fields + Save label + close button (checked via `QRect(mapToGlobal(topLeft), mapToGlobal(bottomRight)).contains(gpos)`), exits edit mode.

`book_detail_panel` added to the guard list in `app.py`'s `mousePressEvent` — it was missing, causing any click in the rightmost area (where `hide_all_panels` wasn't suppressed) to close the panel.

Narrator and year use `QSizePolicy.setRetainSizeWhenHidden(True)` — hiding them never shifts duration or anything below.

### Tags tab

Metadata grid, save button, and `_on_save_metadata` removed entirely. Tab now contains only tag chips, add field, and delete history button. Tab renamed from "Metadata" to "Tags".

---

## Non-obvious decisions

1. **`_ClickableLabel` subclass required**: Qt's C++ event dispatch ignores Python assignments to `instance.mousePressEvent`. A proper subclass with `mousePressEvent` override and a `Signal()` is the only reliable way.

2. **`QLineEdit` always in layout, never swapped**: earlier attempts used `QStackedWidget` (page 0 = label, page 1 = edit) and floating overlaid edits with `setGeometry`. Both caused layout jumps. The working solution mirrors the Tags tab's existing `QLineEdit` fields: always in layout, styled transparent at rest, `setReadOnly` toggled.

3. **App-level event filter, not panel-level**: `installEventFilter(self)` on the panel only catches events for the panel object itself, not child widgets. `QApplication.instance().installEventFilter(self)` catches all mouse presses app-wide, enabling reliable click-outside detection.

4. **`setRetainSizeWhenHidden(True)` on narrator/year**: prevents layout shift when fields are hidden. Must get/modify/set the `QSizePolicy` object — `sizePolicy().setRetainSizeWhenHidden(True)` alone is a no-op because `sizePolicy()` returns a copy.

5. **`book_detail_panel` missing from `mousePressEvent` guard**: the main window's `mousePressEvent` checked 5 panels and called `_hide_popups()` for any click outside them. Book detail panel was not in the list, so any click in an uncovered area closed it. One-line fix in `app.py`.

---

## Files changed this session

| File | Changes |
|---|---|
| `src/fabulor/db.py` | Added `get_book_sessions()`; WAL mode enabled; composite index on `listening_sessions (book_path, session_start)` |
| `src/fabulor/ui/book_detail_panel.py` | Full stats tab restructure; `SessionListWidget` replaces `BarChartWidget`; duration label; inline metadata editing; Tags tab cleanup; app-level event filter; `_RangeBar` colors from theme |
| `src/fabulor/ui/stats_panel.py` | Added `SessionListWidget`, `_RangeBar`; `stats_session_label` object name on session rows |
| `src/fabulor/themes.py` | `stats_day_label`, `stats_day_total`, `stats_history_header`, `stats_session_label` styles; `QLineEdit#book_detail_*` transparent-label style; `book_detail_save_label` style |
| `src/fabulor/app.py` | `book_detail_panel` added to `mousePressEvent` guard list |




# Session Summary — 2026-05-06 (session 2)

## What was done: Theme hover preview snapback fix

---

## Bug: snapback not triggering when leaving the theme pool

### Symptom
After the introduction of `pool_container` (commit `b23d3ef`) and the bin-sorting layout changes, hovering a theme button previewed the theme correctly, but moving the mouse to the tab bar, the sliver on the right, or the cover-art section above the pool did not snap back to the current theme.

### Root cause — wrong boundary widget
The `leaveEvent` was attached only to `themes_tab` (the full tab content widget). With the old layout, theme buttons were direct children of `themes_layout` so any exit from the pool area also exited `themes_tab`, triggering the leaveEvent. After `pool_container` was introduced as an intermediate widget, the meaningful boundary for "left the pool area" became `pool_container`, not `themes_tab`. The `themes_tab.leaveEvent` was still reachable in theory (sliver, tab bar) but was not reliably firing in practice.

### Fix
Added `pool_container.leaveEvent = lambda _: self.theme_manager._on_theme_unhovered()` immediately before `themes_layout.addWidget(pool_container)` in `_build_settings_panel()`. The original `themes_tab.leaveEvent` is kept as a belt-and-suspenders fallback. The guard in `_on_theme_changed` (checks `_active_display_theme` and `_is_hover_active`) prevents any double-apply if both fire.

---

## Bug: snapback always animated at 750ms, ignoring "Off" setting

### Symptom
Even with hover animation set to "Off" in Settings, the snapback faded over 750ms instead of being instant.

### Root cause
`_on_theme_changed` had an unconditional override:
```python
if not hover:
    fade_ms = _THEME_SWITCH_FADE_MS  # always 750, ignores passed value
```
This ran for ALL non-hover calls — both actual theme changes and the snapback — overwriting whatever `fade_ms` was passed in. The caller's explicit value was silently discarded.

### Fix
Changed the logic so the `_THEME_SWITCH_FADE_MS` default only applies when `fade_ms` was not explicitly provided:
```python
if fade_ms is None:
    fade_ms = _THEME_SWITCH_FADE_MS if not hover else self.config.get_theme_fade_duration()
```
`_on_theme_unhovered` now explicitly passes `fade_ms=_SNAPBACK_FADE_MS` (200ms), which is respected.

---

## New constant: `_SNAPBACK_FADE_MS`

Added alongside the two existing timing constants at the top of `theme_manager.py`:

```python
_THEME_SWITCH_FADE_MS = 750       # fade duration for non-hover theme switches
_SNAPBACK_FADE_MS     = 200       # fade duration when reverting a hover preview
_PANEL_ANIM_GUARD_MS  = 700       # delay before retrying a theme change mid-panel-animation
```

The top of `theme_manager.py` is the canonical location for all theme timing constants.

---

## Files changed this session

| File | Changes |
|---|---|
| `src/fabulor/app.py` | Added `pool_container.leaveEvent` for snapback boundary |
| `src/fabulor/ui/theme_manager.py` | Added `_SNAPBACK_FADE_MS = 200`; fixed `fade_ms` override logic; `_on_theme_unhovered` passes `fade_ms=_SNAPBACK_FADE_MS` |

---


# Session Summary — 2026-05-06

## What was done: Stats panel UI polish

---

## Stats panel tab bar — settings icon

The sixth tab in the stats tab bar (Options/Prefs) went through many iterations. Final working state:

- Tab text is `"⚙"` (U+2699, text variant — not `"⚙️"` emoji variant which forces color rendering and ignores CSS)
- The `⚙` character has taller font metrics than alphanumeric text, inflating the tab bar height by ~5px
- Fix: `padding-top: -2px; padding-bottom: 0px` on `QTabWidget#stats_tabs QTabBar::tab:last` counteracts the character's extra ascent without affecting other tabs or the tab bar height

```css
QTabWidget#stats_tabs QTabBar::tab:last {
    padding-top: -2px;
    padding-bottom: 0px;
}
```

### Things that did not work
- `max-height` on `QTabBar::tab` — Qt ignores it for tabs
- `QTabBar` subclass overriding `tabSizeHint` to return `height×height` — correct sizing but caused black line above tabs and icon left-alignment with no CSS fix available
- `⚙️` emoji variant — ignores CSS color, renders with intrinsic color
- `setCornerWidget` — created ugly external button outside tab flow
- `setExpanding(False)` / `setExpanding(True)` — did not resolve overflow
- Custom `paintEvent` with `QStylePainter` + separate `QPainter` — double-rendering artifacts
- Various `QTabBar::tab:last` padding overrides — either caused overflow/arrows or conflicted with subclass sizing

### Non-obvious facts
- `⚙` vs `⚙️`: same codebase point U+2699 but the variation selector U+FE0F forces emoji rendering. Without it, the character respects CSS `color` but has different font metrics than Latin text.
- The stats panel layout had `setContentsMargins(5, 5, 5, 5)`, giving the tab widget only 260px in a 270px panel. This caused overflow with 6 tabs. Changed to `setContentsMargins(0, 5, 0, 5)` so the tab widget fills the full panel width.
- Tab bar overflow (arrows appearing) was triggered by 6 tabs × `margin-left: 2px` = 12px + tab content widths exceeding the available width.

---

## Stats panel — Reset all stats button style

`QPushButton#stats_reset_btn` now matches the Library panel's Add/Remove/Rescan button style: transparent background, accent-colored border, accent fill on hover, accent-dark on press. Added to `get_stats_stylesheet()` in `themes.py`.

---

## Files changed this session

| File | Changes |
|---|---|
| `src/fabulor/themes.py` | `stats_reset_btn` style added; `QTabWidget#stats_tabs QTabBar::tab:last` padding fix for `⚙` height; settings panel tab padding restored to original asymmetric values |
| `src/fabulor/ui/stats_panel.py` | Layout margins changed to `0, 5, 0, 5`; options tab label changed to `"⚙"` |

---


# Session Summary — 2026-05-02

## What was done: Full codebase audit + targeted hardening (no features)

Four audit passes (dead code, error handling, thread safety, DB consistency, memory/resource leaks) followed by targeted fixes for every critical and high-priority finding.

---

## Fixes applied

### Schema / DB crashes (would break fresh installs)
- **`book_events` table missing from `_create_tables()`** — table was queried in 6+ places but never created. Added with `id`, `book_path`, `event_type`, `event_time` columns and two indexes.
- **`book_duration` column missing from `listening_sessions`** — `write_session()` and two stats queries referenced it. Added to `CREATE TABLE`.
- **`finished_at` column missing from `books`** — `reset_stats()` and `delete_book_stats()` both referenced it. Added to `CREATE TABLE` alongside `started_at`. The existing `ALTER TABLE started_at` migration guard still handles pre-existing databases; it hits `OperationalError` (column now exists) and silently passes as before.
- Deleted `/home/pryme/.local/share/fabulor/library.db` so it is recreated with the correct schema on next launch.

### Thread safety
- **`player.chapter_changed` and `player.file_loaded` signal connections** — mpv property-observer callbacks run on mpv's internal C thread, not the Qt main thread. `AutoConnection` does not queue to the main thread from a non-Qt thread. Added `Qt.ConnectionType.QueuedConnection` to all three `self.player.*signal*.connect()` calls in `app.py`.
- **`CoverLoaderWorker` signal connections** — `QThreadPool` workers run off the main thread. Added `Qt.ConnectionType.QueuedConnection` to all three `worker.signals.*.connect()` calls in `library.py` (`cover_loaded` × 2, `finished` × 1).
- **`QPropertyAnimation.Running` → `QAbstractAnimation.State.Running`** — the shorthand was unrecognised by PySide6 type stubs. Replaced all 14 occurrences in `panels.py`; added `QAbstractAnimation` to the import.

### Error handling
- **Bare `except:` in `scanner.py`** — two bare-except clauses (metadata extraction, thumbnail caching) swallowed `KeyboardInterrupt` and `SystemExit`. Changed to `except Exception:`.
- **Bare `except:` on signal disconnects in `panels.py`** — seven bare-except clauses on `.finished.disconnect()` calls. Changed to `except RuntimeError:` (the specific exception Qt raises when disconnecting a signal that was never connected). Expanded all five single-line `except RuntimeError: pass` forms to two-line style to clear linter warnings.
- **`mutagen.File()` returning `None` in `player.py`** — added explicit `if audio is None: return pixmap` guard immediately after the call. Return type matches the function's other early-return paths.
- **UI/DB divergence in `book_detail_panel.py`** — `_book_data` was updated in-memory unconditionally after `db.update_book_metadata()` regardless of success. Changed `update_book_metadata()` to return `bool` (`True` on success, `False` on exception). Wrapped the in-memory update in `if self.db.update_book_metadata(...):`.
- **Daemon thread session write in `app.py`** — `_write()` closure ran `write_session()` and `set_started_at()` with no error handling. Wrapped entire body in `try/except Exception: pass` so DB failures don't crash the daemon thread.

### Dead code / unused imports
- Removed `QSizePolicy` from `flow_layout.py` import.
- Removed `QApplication`, `QGuiApplication`, `Config`, `THEMES`, `ThemeComboBox` from `panels.py` imports (5 unused names). Also removed the stale comments justifying them.
- Removed `import math` and `import random` from `app.py`.
- Removed all commented-out debug instrumentation from `settings_controller.py`: 6 `#print(...)` calls, 6 `#self._debug_settings_state()` calls, and the fully-commented `_debug_settings_state` method stub.

### Memory / resource leaks
- **`_reveal_timer` accumulating connections** — every call to `_reveal_list_rows()` in `panels.py` created a new `QTimer` and added a `timeout` connection without clearing the previous one. Added a stop-and-disconnect guard before reassigning the timer.
- **`ui_timer` and `quote_timer` not stopped in `closeEvent`** — both timers could fire during Qt teardown. Added `self.ui_timer.stop()` and `self.quote_timer.stop()` at the top of `closeEvent` in `app.py`.
- **`_active_workers` not cleared in `cancel_preload()`** — added `self._active_workers.clear()` to `cancel_preload()` in `library.py`. In-flight workers still complete; their `finished` lambda calls `discard()` on an entry no longer in the set, which is a no-op.

---

## What was audited but not changed

- **`_cover_cache` unbounded pixmap cache** — flagged (no eviction policy, grows with library size). Not fixed this session; requires an LRU implementation decision.
- **`_preload_timer` not stopped in `hideEvent`** — flagged. Not fixed; low priority.
- **`add_book_tag()` TOCTOU** — count-check and insert not in a single transaction. Flagged. Not fixed; race is theoretical given single-user local app.
- **`_close_session` daemon thread session loss on fast exit** — inherent to the threading model. Flagged, error handling added, but the fundamental race (daemon thread killed before write completes) is not resolved without a different architecture.
- **`update_book_metadata()` and `remove_book_tag()` writes outside transactions** — flagged. Not fixed this session.

---

## Files changed this session

| File | Changes |
|---|---|
| `src/fabulor/db.py` | Added `book_events` table; added `book_duration` to `listening_sessions`; added `finished_at` and `started_at` to `books` CREATE TABLE; `update_book_metadata()` now returns `bool` |
| `src/fabulor/app.py` | `QueuedConnection` on player signals; `ui_timer.stop()` / `quote_timer.stop()` in `closeEvent`; `_write()` wrapped in try/except; removed `import math` / `import random` |
| `src/fabulor/player.py` | `None` guard after `mutagen.File()` |
| `src/fabulor/ui/panels.py` | `except RuntimeError:` on all signal disconnects; `QAbstractAnimation.State.Running` throughout; `_reveal_timer` stop/disconnect guard; removed unused imports |
| `src/fabulor/ui/library.py` | `QueuedConnection` on CoverLoaderWorker signals; `_active_workers.clear()` in `cancel_preload()` |
| `src/fabulor/ui/book_detail_panel.py` | In-memory update guarded by DB write result |
| `src/fabulor/ui/flow_layout.py` | Removed unused `QSizePolicy` import |
| `src/fabulor/settings_controller.py` | Removed all commented debug instrumentation |

---


# Session Summary — 2026-05-01

## What was built: Progress bar flow animation + theme fade exclusions + chapter UI sync fix

---

## Feature 1: Flow animation on book switch

When a new book is loaded, the overall progress slider and chapter progress slider animate from the previous book's position to the new one. Speed is proportional to distance (200ms minimum, 600ms for a full-range jump, InOutCubic easing).

### Implementation

- `ClickSlider` gained an `animatedValue` Qt `Property(int)` (getter/setter wrapping `setValue`) so `QPropertyAnimation` can drive it.
- `animate_to(target, old_value=None)` on `ClickSlider`: lazily creates the animation, computes duration from distance, stops any in-flight animation before starting.
- In `_on_book_selected_from_library`: captures both slider values into `_pre_switch_slider_value` and `_pre_switch_chap_slider_value` before the switch.
- In `_on_file_ready`: after `_update_ui_sync()` snaps sliders to the new book's position, fires `animate_to(new_val, old_value=pre)` for both sliders.
- `_sync_progress_sliders` and `_sync_chapter_ui` skip their `setValue` calls while the respective animation is running (checked via `QPropertyAnimation.State.Running`), preventing the 200ms UI timer from fighting the animation.

### Zero-progress edge case

When the new book has no saved progress, `_update_ui_sync` may return early (no valid mpv position yet), leaving sliders stale. Fix: check `book_data.progress` in `_on_file_ready`. If zero, snap both sliders to 0. If non-zero, animate. If `pre == new_val`, snap (no pointless animation). All four combinations (0→0, 0→progress, progress→0, progress→progress) handled.

---

## Feature 2: Theme fade overlay exclusions

The cover-art theme fade uses a pixmap overlay fading from opaque (old screenshot) to transparent (new theme). During this crossfade, progress sliders were visually morphing between values.

### Implementation

- `_apply_fade_mask()` on `ThemeManager`: builds a `QRegion` from the full window rect, subtracts excluded widget rects (mapped via `w.mapTo(mw, QPoint(0, 0))`), applies as mask to the overlay.
- Only called for cover-art theme transitions (`isinstance(theme_name, dict) and not hover`). All other fades call `clearMask()` for a full-window crossfade.
- Excluded: `progress_slider`, `progress_percentage_label`, `chapter_progress_slider`. These snap immediately — safe because they're custom-painted and always show the correct value.

### What was tried and rejected

- Excluding time labels, chapter label, speed button: punching holes exposes new theme colors in those areas while the rest of the window shows the old screenshot — visible hodgepodge. Only custom-painted widgets can be safely excluded.
- Separating speed button text from its background color: not feasible. The overlay is a flat pixmap; there's no way to punch a hole transparent to color but opaque to text.

---

## Bug fix: Chapter UI sync when paused (pre-existing bug)

### Symptoms

- Rewinding within chapter 1 while paused left the chapter slider stuck at the old position.
- Pressing prev/next while paused took the chapter slider to the wrong position (end of chapter rather than beginning).
- Both issues only appeared when paused, not during playback.

### Root causes

1. `_update_ui_sync` returned early when `mpv_pos is None` (transient during seek while paused), so `_sync_chapter_ui` never ran and the slider stayed stale.
2. `_sync_chapter_ui` used `self.player.chapter` (mpv's live property) for chapter boundary lookup. mpv updates `chapter` asynchronously — it can be ahead of `time_pos`, causing the UI to show the wrong chapter.
3. For chapter navigation (prev/next), mpv updates `chapter` instantly but `time_pos` lags. `_paused_time` holds the old position, so the pos-derived chapter lookup found the wrong chapter.

### Fix

**1.** In `_update_ui_sync`: when `mpv_pos is None` but paused with `_paused_time` cached, fall through using the cached position. Don't overwrite `_paused_time` with `0.0` when `mpv_pos is None` mid-seek — hold it until mpv settles.

**2.** In `_sync_chapter_ui`: always derive chapter from `pos` by walking the chapter list, using `chap.get('time', 0) <= pos + 0.5`. The 0.5s tolerance is necessary — mpv's chapter boundary floats consistently land ~0.25s short of their nominal values.

**3.** In `handle_prev`/`handle_next`: compute the target chapter's start time before the async mpv call (mirroring the logic in `Player.previous_chapter()`/`next_chapter()`), and set `_paused_time` to it immediately. This ensures the pos-derived lookup finds the correct chapter on the very next timer tick.

### The whack-a-mole sequence (things tried and failed)

1. Always derive from pos → prev/next broke: `_paused_time` still held old position when the lookup ran.
2. Use `is_seeking` flag to switch between pos-derived and `mpv_chapter` → chapter 1 broke again: `is_seeking` clears on the tick mpv settles, at which point `mpv_chapter` is already ahead of `time_pos`.
3. Pre-set `_paused_time` to chapter start in handle_prev/next, then always derive from pos → worked without playing; after playing, the timer overwrote `_paused_time` with the live mpv position before the lookup ran.
4. 0.01s epsilon on boundary comparison → not enough; shortfall is ~0.25s.
5. **Final**: 0.5s epsilon + pre-set `_paused_time` in handle_prev/next → all cases pass.

---

## Non-obvious decisions

1. **0.5s epsilon**: Chapter boundary times from mpv are fractional and consistently ~0.25s short. 0.5s is the minimum safe value. It only affects display lookup, never seek targets. Closest real-world chapter boundaries observed: 2s apart.

2. **Derive chapter from pos everywhere, never from `self.player.chapter`**: Using the mpv property anywhere reintroduces the async lag problem. Display is driven by `pos` (`_paused_time` when paused), so chapter derivation must match.

3. **Pre-compute target chapter start before the mpv seek call**: `previous_chapter()`/`next_chapter()` write to mpv asynchronously. Reading `self.player.chapter` after them returns the old value. Target must be computed using the same conditional logic as the Player methods, before the call.

4. **Flow animation suppresses the UI timer's setValue**: Without this, the 200ms timer fights the animation frame-by-frame, causing jitter on the slider.

---


# Session Summary — 2026-05-13

## What was built: Multi-file book support + panel close stutter fix + progress accuracy

---

## Feature 1: Multi-file book support (player.py)

Books stored as folders with multiple audio files (MP3, M4A, FLAC) now play as a single continuous stream. Previously only single-file M4Bs worked; multi-file folders silently failed with `no audio or video data played`.

### Implementation

- `_resolve_playlist(path)` scans direct children for audio files (no recursion), sorts alphabetically, and returns either the single file path or a `concat://file1|file2|...` URI.
- For multi-file books, builds an ffmetadata chapter file (`;FFMETADATA1` format, `TIMEBASE=1/1000`, cumulative millisecond timestamps) using mutagen durations. Written to a `NamedTemporaryFile` with `delete=False` — cleanup is deferred.
- `instance.chapters_file` is set before `instance.play()` — order is critical; mpv reads the chapters file at load time.
- Empty folder falls through to `instance.play(path)` as graceful degradation.

### Diagnosis path
- `end-file` observer added to catch silent load failures. The event dict is an `MpvEventEndFile` object — data is in `.d`, not top-level attributes. `getattr(event, 'reason', ...)` returns the default; must use `event.d.get('reason', ...)` or `isinstance(event, dict)` check.
- `b'stop'` / `b'error'` are bytes, not strings — must decode before comparing.
- `'redirect'` added to exclusion set alongside `'eof'` and `'stop'` — mpv fires this for internal playlist transitions.

---

## Feature 2: Async playlist resolution (player.py)

`_resolve_playlist` runs mutagen on every file in the folder synchronously. For 260-file books this blocked the main thread long enough to visibly stutter any concurrent animation.

### Implementation

- `load_book` spawns a `QRunnable` worker via `QThreadPool.globalInstance()`. Worker runs `_resolve_playlist` on a background thread, emits `_playlist_resolved` signal (str, str) when done.
- `_play_gated = True` flag set at `load_book` time. `_on_playlist_resolved` checks this flag: if still gated, stores result in `_held_play`; if gate already lifted, plays immediately.
- `ungate_play()` sets `_play_gated = False`. If `_held_play` is already populated, plays immediately. If not (resolve still running), the flag ensures `_on_playlist_resolved` will play when it arrives.
- This two-path design handles the race between the animation finishing and the worker finishing — whichever comes second triggers play.

---

## Feature 3: Panel close stutter fix — gate/ungate + _mpv_ready

The library panel close slide stuttered whenever a book was selected. Back-button close (no mpv work) was always smooth. This was the diagnostic signal.

### Root cause

mpv's audio pipeline initialisation (PulseAudio negotiation) happens on background threads when `instance.play()` is called. This causes brief OS scheduler priority inversions that delay Qt's animation timer wake-ups — not a Python main-thread block. Timing every Python step showed nothing over 2ms, yet the animation still stuttered.

### The fix — complete book-switch sequence

**`_on_book_selected_from_library` now:**
1. Saves progress, clears UI state, resets `_paused_time = None`, sets `_mpv_ready = False`
2. Captures pre-switch slider values for flow animation
3. Calls `hide_all_panels()` — animation starts immediately
4. Defers all remaining work via `QTimer.singleShot(0, lambda: ...)`: DB writes, library panel state updates, cover load, `load_book`

**`load_book` (async):** Kicks off worker thread for `_resolve_playlist`. Stores result in `_held_play`, waits for ungate.

**`_on_library_hidden` (after 300ms animation):**
1. Sets `_mpv_ready = True`
2. Calls `player.ungate_play()` — only now does `instance.play()` fire
3. Drains `_file_ready_deferred` and `_chaps_deferred` via `singleShot(50)` if `file_loaded` already fired
4. Applies pending cover theme via `_apply_pending_cover_theme()`

**`_mpv_ready` guard in deadzone:** `_update_ui_sync` ignores all `mpv_pos` values while `_mpv_ready = False`. This prevents the 200ms timer from accepting the previous book's stale position during the animation window — which was causing random progress display.

### Unobvious decisions

- **`_mpv_ready` defaults to `True`** (via `getattr(self, '_mpv_ready', True)`) — ensures all non-library-switch paths (startup, seek, normal playback) are unaffected.
- **Startup and EOF-restart** call `self._mpv_ready = True` then `player.ungate_play()` directly — there is no animation to wait for.
- **`_on_file_ready` deferral** checks `library_panel._is_animating`. Since `ungate_play()` fires from `_on_library_hidden` after `_is_animating = False`, `file_loaded` almost always arrives after the animation — but the check is kept as a safety net for fast SSDs.
- **50ms delay in drain** (`singleShot(50, _drain_deferred_file_ready)`) avoids last-frame compositor hitch. Do not remove.
- **Flow animation** fires from `_on_file_ready` using `pre_switch` values captured before book switch. Chapter slider animation fires from `_on_file_loaded_populate_chapters` — chapter data must exist for the target value to be meaningful.

### What was tried and failed

- `singleShot(0)` for `load_book` only — animation got one frame then stalled; `instance.play()` still fired too early.
- `is_seeking` guard on `_sync_progress_sliders` — broke flow animation (seeking clears before correct value lands).
- `_seek_target` proximity check — caused 228% progress when book had no saved position.
- Skipping `_update_ui_sync` when `is_seeking` — slider was 0 when `animate_to` fired.
- Deferred slider animation from deadzone `is_seeking→False` transition — fired on wrong tick.
- All Python-side timing instrumentation showed nothing blocking. The stutter was OS-level.

---

## Bug fix: Theme fade overlay ghost on cover-art transitions (theme_manager.py)

The `_fade_overlay` pixmap was covering the progress sliders and percentage label during cover-art theme transitions, causing them to visually morph between values.

### Fix
`_apply_fade_mask()` re-implemented: for `isinstance(theme_name, dict)` transitions, builds a `QRegion` from the full window rect and subtracts `progress_slider`, `chapter_progress_slider`, and `progress_percentage_label` rects (mapped to window coordinates). Applied after the panel mask. `QRegion` import moved out of the inner `if` branch to avoid `UnboundLocalError` when no panel is visible.

### Theme fires after notches
Cover theme application deferred to `_apply_pending_cover_theme()`, called from `_drain_deferred_file_ready` after both `_on_file_ready` and `_on_file_loaded_populate_chapters` complete. `when_animations_done` on `progress_slider` ensures theme fires after notch reveal animation.

---


# Session Summary — 2026-04-30

## What was built: Chapter List overlay, complete rewrite and extension

### Architecture change
The chapter list was previously a `Qt.Popup` top-level window (floating outside the app). It is now a **child widget** (`Qt.Widget`) of `MainWindow`, parented directly to it. This means it can never escape the window boundary, moves with the window, and does not appear on screen coordinates. All positioning uses window-local coordinates via `mapTo()`.

### Files changed
- `src/fabulor/ui/chapter_list.py` — full rewrite
- `src/fabulor/ui/controls.py` — `HoverButton` gained `rightClicked` signal
- `src/fabulor/ui/panels.py` — `hide_all_panels` and `handle_drag_area_right_click` updated to call `fade_out()` instead of `hide()`
- `src/fabulor/app.py` — chapter list wiring, event filter, new handlers, Controls tab, signals
- `src/fabulor/settings_controller.py` — two new settings wired
- `src/fabulor/config.py` — two new config keys
- `src/fabulor/themes.py` — `chapter_expand_btn` style added to `get_base_stylesheet()`

---

## ChapterList widget — key implementation details

### Positioning (`show_above`)
- `setFixedWidth(window.width())` — matches window width exactly
- Show at opacity 0, measure `h_overhead = height() - viewport().height()` (border + internal padding, varies by platform/stylesheet), then `setFixedHeight(visible_rows * ROW_HEIGHT + h_overhead)`
- Positioned via `anchor_widget.mapTo(window, ...)` — pure local coords, no `mapToGlobal`
- Bottom edge fixed at the chapter label row; grows upward on expand

### Height/scroll stability
- `setUniformItemSizes(True)` + explicit `item.setSizeHint(QSize(w, ROW_HEIGHT))` — prevents Qt lazy size recalculation
- `setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)` — no scrollbar
- `scroll_to_active` uses `verticalScrollBar().setValue(top_row * ROW_HEIGHT)` — exact pixel, no `scrollToItem` snapping
- `_TOP_MARGIN = 66` — list never grows above y=66 (below title bar + progress bar)

### Fade animation
- `QGraphicsOpacityEffect` on the list itself; `QPropertyAnimation` on opacity
- Fade in: 600ms, fade out: 600ms
- Expand button (`_expand_btn`) is a **sibling widget** (child of `MainWindow`, not of the list) to avoid being clipped by the opacity effect. Its own `QGraphicsOpacityEffect` is driven by `self._anim.valueChanged` — same easing, frame-perfect sync.
- `_hide_connected` bool tracks whether `_on_fade_out_finished` is connected to `finished` signal — avoids PySide6 RuntimeWarning on disconnect

### Click behavior
- Left click → seek, respect pause state
- Right click → seek + `player.pause = False` (force play)
- Both emit `chapter_selected(title, old_pos, force_play)` signal
- `chapter_changed(title)` also emitted for label update

### Keyboard (only when chapter list has focus)
- Up/Down → `super().keyPressEvent` (default QListWidget selection movement)
- Left/Right → expand/collapse toggle (only when `_can_expand`)
- Enter/Return → seek, respect pause state
- Space → seek + force play
- Escape or `c` → dismiss
- Digits → digit jump with 800ms debounce timer

### Digit jump
- Accumulates digits in `_digit_buffer`, restarts 800ms timer on each keypress
- On commit: branches on `config.get_chapter_digit_mode()`
  - `"by_name"`: regex `(?<!\d)N(?!\d)` word-boundary search in chapter titles
  - `"by_index"`: 1-based position in chapter list
- If `config.get_chapter_digit_autoplay()` is True: calls `_activate_item(item, force_play=True)` immediately
- If False: just scrolls to and selects the row (user presses Enter/Space to commit)

### Expand button
- Only shown when `count() > VISIBLE_ROWS`
- Sibling widget, moved to `(window.width() - EXPAND_BTN_W, list.y() - EXPAND_BTN_H)` on every `_apply_height` call
- Clicking it calls `_toggle_expand()` then `QTimer.singleShot(0, self.setFocus)` to return focus to list
- State (▲/▼, `_expanded`) reset in `_on_fade_out_finished` — after fade completes, not on dismiss initiation

### Focus
- `show_above` calls `QTimer.singleShot(0, self.setFocus)` — deferred so Qt finishes show event before focus transfer
- Same pattern in `_toggle_expand` after button click steals focus

### Undo integration
- `chapter_selected` signal connected to `_on_chapter_list_selected(title, old_pos, force_play)` in `app.py`
- Undo triggered if `abs(new_pos - old_pos) > 60 * speed`

### Event filter (app.py)
- On `MouseButtonPress` outside the list: calls `fade_out()`, returns `True` (swallow)
- Exception: if click is on `_expand_btn.geometry()`, do nothing (let button handle it)
- This prevents cover art click from also playing/pausing when dismissing the list

---

## New: Prev button right-click → seek to 00:00:00
- `HoverButton` gained `rightClicked = Signal()` and `mousePressEvent` override
- `prev_button.rightClicked` connected to `_on_prev_right_click`
- Handler: `player.time_pos = 0`, `player.is_seeking = True`, `_trigger_undo(old_pos)` unconditionally

---

## New: Controls tab in Settings panel
Previously a placeholder. Now contains:

**Chapter number keys row** (left group + right group, stretch between):
- Left: "By name" / "By index" — maps to `config.chapter_digit_mode`
- Right: "Auto-play" / "Jump only" — maps to `config.chapter_digit_autoplay`

Signals: `chapter_digit_mode_changed(str)`, `chapter_digit_autoplay_changed(bool)` on `MainWindow`
Wired through `SettingsController._update_chapter_digit_mode` / `_update_chapter_digit_autoplay`
Visual sync via `set_digit_mode_selection` / `set_digit_autoplay_selection` in `VisualsInterface`
Both included in `sync_all_settings_visuals()`

Config defaults: `chapter_digit_mode = "by_name"`, `chapter_digit_autoplay = True`

---

## Non-obvious decisions made this session

1. **Child widget not popup**: `Qt.Popup` widgets live in screen coordinates and escape the window when dragged to a screen edge. Child widget stays inside always.

2. **h_overhead measured after show**: `frameWidth()` is unreliable — it doesn't capture stylesheet-applied borders. The real overhead is `height() - viewport().height()` measured after the widget is shown (at opacity 0).

3. **Expand button as sibling**: `QGraphicsOpacityEffect` clips child rendering to the widget bounding rect. A button at negative y (above the list) is invisible. Solution: make it a sibling child of `MainWindow` so it's in the same coordinate space but outside the opacity effect's clip region.

4. **Scroll via setValue not scrollToItem**: `scrollToItem(PositionAtTop)` causes 1-2px nudge at scroll boundaries because it uses Qt's snapping logic. `verticalScrollBar().setValue(row * ROW_HEIGHT)` is exact.

5. **Focus via singleShot(0)**: Direct `setFocus()` call after `show()` loses to the button click's focus grab. Deferring via `QTimer.singleShot(0, self.setFocus)` lets Qt finish processing the event before the focus transfer.

6. **_hide_connected flag**: PySide6 emits `RuntimeWarning` (not raises `RuntimeError`) when `disconnect()` is called on a signal with no connections. Track connection state manually to avoid this.

---

## Cover art based theme — settings UI overhaul (2026-04-30, session 2)

### What changed

The Themes tab in Settings was restructured. Interval selection converted from buttons to clickable `QLabel` widgets. Cover art theme controls redesigned from scratch.

### Cover art mode selector
Off / With pool / Exclusive labels, left-to-right. The entire pool block (theme grid + bulk buttons + interval row) is wrapped in `pool_container` (`QWidget`) on `theme_manager` and hidden when Exclusive is selected.

### Cover art based theme entry in pool
`ThemeItem("Cover art based theme")` is the first row of the pool, always present (never hidden or shifted). Behavior mirrors any other pool entry:

- **Off**: dimmed, not bold. Left-click → set With pool. Right-click → activate + set With pool (requires cover).
- **With pool**: bold. Left-click → set Off, deactivate if active. Right-click → activate cover theme.
- **active_display** (underline): shown when cover theme is currently displayed. Cleared when a pool theme is right-clicked.
- **Disabled**: when in With pool mode and no cover is loaded.

### Theme switching fixes
- Switching to Exclusive with no cached cover theme now rebuilds from `current_cover_pixmap`.
- Switching to Off always reverts to pool theme regardless of `_cover_theme_active` state.
- `_on_theme_right_clicked` clears `_cover_theme_active` so underline moves correctly to the clicked theme.
- `clear_cover_theme` no longer has early-return guard — always nulls `_cover_theme` and updates pool btn.

### Change now includes cover in With pool
`_rotate_theme` appends `None` as a candidate when mode is `with_pool` and `_cover_theme` exists. Tracks whether cover was the current display to avoid immediate re-selection.

### Non-obvious decisions
1. **Cover entry always in place**: hiding/showing causes row shift and animation jank. State communicated through bold/dim/underline/disabled only.
2. **selected = mode is with_pool**: being in the pool IS the mode setting. Toggle is symmetric: off↔with_pool.
3. **Exclusive hides pool_container**: cover entry disappears in Exclusive — correct, the mode selector communicates state.
4. **panel_opacity_hover**: was `1.00` (fully opaque panels) in cover_theme. Changed to `0.92` to match other themes.



