# Fabulor — Claude Context

## What this file is for

This is a reference document for Claude and Claude Code. It records **what has been built**, key
architectural decisions, and current state. GEMINI.md is the canonical design spec — read it for
the full project description and Gemini-specific constraints. This file answers "where are we now?"

---

## Critical Architecture Rules

These rules exist because violating them caused real bugs. The reasoning is documented in
SESSION.md. They are not arbitrary constraints — they are load-bearing until proven otherwise
in a specific context.

If you believe the cleanest solution requires crossing one of them, stop and explain why before
proceeding. Don't route around them silently. The bar for crossing one is: you've identified a
specific reason the rule doesn't apply in this case, not just that it would be simpler to ignore it.

---

### DO NOT modify, refactor, or touch any code related to MPV initialization under any circumstances. This includes the _ensure_mpv() method, the load_book() method's MPV init block, the locale.setlocale(locale.LC_NUMERIC, "C") call, and all MPV constructor arguments (vo, ao, vid, ytdl, keep_open). This code resolves a hard-won, non-obvious bug involving libcaca, libtinfo, and Qt's locale reset on Wayland/openSUSE. Any "improvement," "cleanup," or "fix" to this block will break the app. If you think something in this block needs changing, say so explicitly and wait for confirmation before touching it.

### DO NOT use self.player.chapter to derive which chapter the UI should display. It looks like the obvious choice but it is wrong — mpv updates the chapter property asynchronously and it will be ahead of or behind time_pos after any seek. Always derive the current chapter by walking self.player.chapter_list and finding the last entry whose time <= pos + 0.35. The 0.35s tolerance is intentional: mpv's chapter boundary floats consistently land ~0.25s short of their nominal values. This rule applies everywhere in _sync_chapter_ui and any future method that maps a playback position to a chapter index.

### DO NOT connect _on_file_ready to the file_loaded signal. It must only connect to book_ready. book_ready fires once per book (before any file for VT books; after file-loaded for non-VT). file_loaded fires on every mpv file-loaded event including VT file switches mid-book. If _on_file_ready runs on every file switch, it triggers position restore, which triggers another file switch, causing a quadruple-advance feedback loop. This was the root cause of two reverted stage 3 implementations.

**book_ready invariant:** For VT books, `book_ready` is emitted from `ungate_play` or `_on_playlist_resolved` (before any file loads, while VT state is ready). `_on_file_loaded` never emits `book_ready` for VT books — it emits `file_switched` instead. For non-VT books (M4B, single-file), `_on_file_loaded` is the only emitter of `book_ready`. These two paths are mutually exclusive and must never converge.

**Book-switch state machine (`book_switch.py`, `self._switch: BookSwitchState`):** The switch-specific transition flags live on one object, not as loose `MainWindow` attributes. `phase` (`IDLE`/`LOADING`/`RESTORING`) is *derived* from the sub-flags, so there is no fragile terminal transition. Flag mapping (old attr → SM): `_mpv_ready` → `in_deadzone` (inverted; set by `begin()` at selection, cleared by `library_revealed()` in `panels._on_library_hidden`); `_pre_switch_slider_value` → `flow_pending_progress` + `take_progress_target()`; `_pre_switch_chap_slider_value` → `flow_pending_chapter` + `take_chapter_target()`; `_chaps_dur_retried`/`_file_ready_deferred`/`_chaps_deferred` → same-named SM members. The SM owns ONLY switch-specific state. The **orthogonal** guards — `player._is_seeking`/`_seek_target`, the slider-drag flags, `_flow_anim` running state, `mp3_seek_reload_pending` — stay separate and the SM composes with them (e.g. `_sync_progress_sliders` reads `not is_seeking and not slider_animating and not self._switch.flow_pending_progress`). Do NOT fold those into the SM: they fire for chapter nav / manual seeks / theme color animations and are the fixes for the rules below. Known gap: no stale-book guard on rapid switching (the SM is the natural home for a future `generation` counter, deliberately not added). **Consume-once constraint:** `take_progress_target()`/`take_chapter_target()` are consuming reads — each captured value can be read exactly once, which is what flips `flow_pending_*` to False and tears the switch down. A future fix that needs to *inspect* a pre-value without consuming it must add a non-consuming peek property; do NOT read-then-restore via `take()`, and do NOT make a guard depend on `take()`'s side effect.

### DO NOT read self.progress_slider.value() (or any slider's .value()) in _on_file_ready to compute the "new position" for a switch animation. The slider value is stale at that point — _update_ui_sync's setValue call is gated on not slider_animating, not is_seeking, and not self._switch.flow_pending_progress, and may not have run yet. The legitimate pre-switch capture happens earlier, in self._switch.begin(...) at selection time; _on_file_ready consumes it via self._switch.take_progress_target(). Always compute the target slider value from the authoritative data: int((new_progress / self.player.duration) * 1000).

**Duration race corollary (also _on_file_ready and _on_file_loaded_populate_chapters):** For non-VT books, `player.duration` (`_cached_duration`) is populated by an mpv property observer on the mpv thread. In rare timing conditions it may be None when the queued `book_ready` signal is processed on the Qt main thread. Two rules apply: (1) in `_on_file_ready`, if `not dur`, set `new_val = None` and skip the animation entirely — never animate to 0 as a fallback, because `not dur` and `new_progress == 0` are different cases; (2) in `_on_file_loaded_populate_chapters`, if `not dur`, schedule a 150ms retry via the `self._switch.chaps_dur_retried` flag (reset on each book selection by `self._switch.begin(...)` in `_on_book_selected_from_library`) rather than calling `_set_chapter_ui_active(False)` prematurely — that makes the chapter label text transparent for the entire session.

**Chapter flow animation target:** `_on_file_loaded_populate_chapters` must compute `new_chap_val` from a chapter-list walk against `new_progress` (same algorithm as `_sync_chapter_ui`), NOT from `self.chapter_progress_slider.value()`. At the time this handler runs, the 200ms timer has not ticked; the slider still holds the previous book's chapter position, which equals `pre_chap`, making `pre_chap != new_chap_val` always False and degrading `animate_to` to `setValue`.

### DO NOT remove the animation-state guard in _sync_progress_sliders or _sync_chapter_ui. Both methods check whether the flow animation is running before calling setValue. If that check is removed, the 200ms UI timer will fight the animation frame-by-frame, causing visible jitter. The guard must survive any refactor of those methods.

### DO NOT remove the `self._switch.flow_pending_chapter` guard from `_sync_chapter_ui`
(Formerly `_pre_switch_chap_slider_value is not None` — same predicate, now read off the switch state machine.) Without this guard the 200ms timer can fire between the pre-switch capture in `self._switch.begin(...)` (`_on_book_selected_from_library`) and the `animate_to()` call in `_on_file_loaded_populate_chapters`, writing `setValue(chapter_at_pos_0)` to the slider. `animate_to()` then resets `_value = start` (= pre_chap) before animating, so the user sees: pre_chap → 0 (timer) → pre_chap (animate_to reset) → flow. This is the "blinks first, jumps, then flows" artifact. Mirrors the `flow_pending_progress` guard in `_sync_progress_sliders`. The capture is consumed once via `self._switch.take_chapter_target()`.

### DO NOT remove the `is_seeking` gate from `_update_chapter_label_from_index`
Without this gate, every intermediate `time_pos` event during a seek fires `chapter_changed`, causing the chapter name label to oscillate through all chapter boundaries crossed in the seek direction (VU-meter effect, worst on long backward seeks). The final `time_pos` that settles the seek clears `_is_seeking` and fires one clean `chapter_changed` with the correct index. The CUE-mode optimistic emit from `seek_async` is also suppressed by this gate — it is intentional; the settle-time `time_pos` provides the update with at most ~100ms latency on local files.

### DO NOT restore the `_seek_target is None` branch in `_on_time_pos_change`
The original `if self._seek_target is None or abs(...) < 1.0` condition caused a race: `load_book` sets `_is_seeking=True` with `_seek_target=None`; the first `time_pos=0` from the new file cleared `_is_seeking=False` immediately; `_sync_progress_sliders` (which guards on `not is_seeking`) was then unblocked before `_on_file_ready` ran, and the 200ms timer wrote 0 to the slider. The fix: only clear `_is_seeking` when `_seek_target is not None` AND position is within 1.0s. `load_book` also now resets `_seek_target = None` (alongside `_cached_time_pos` and `_cached_duration`) to clear any stale target from an interrupted seek on the previous book. `_restore_position` explicitly clears `is_seeking=False` for the no-progress case (where no `seek_async` is called and `_seek_target` stays None), so the slider can update during normal playback. Do NOT add the asymmetric-clear back — it was the root cause of the "0% flash before the flow animation" bug.

### DO NOT let `_do_fade_with_slider_animation` iterate `chapter_progress_slider` when `_chapter_ui_active` is False
The slider loop in `_do_fade_with_slider_animation` must skip `chapter_progress_slider` when `mw._chapter_ui_active` is `False`. The theme overlay punch-through re-exposes the slider during the window between `_apply_stylesheets` (which repolishes child widgets and overwrites transparent colors with theme colors) and the `_set_chapter_ui_active` reapplication at the end of `_apply_stylesheets`. Without the guard the slider briefly renders at full opacity, causing a visible flash. Guard: `if attr == 'chapter_progress_slider' and not mw._chapter_ui_active: continue`.

### DO NOT restore `show_metadata=False` to `library_controller.apply_library_state`
The `show_metadata=False` argument was removed from the `apply_library_state` call in
`library_controller.py` on 2026-05-11. Do not restore it. It was silently overriding cover
display on every book switch — `_load_cover_art` owns `metadata_label` visibility and the
call was fighting it. If you think metadata visibility needs to be controlled at the
`apply_library_state` call site, stop and explain why before touching it.

### DO NOT use `self.chapter = idx` for chapter navigation anywhere
Always use `seek_async(target_time + _CHAPTER_BOUNDARY_EPSILON)` with a position-based walk of `chapter_list`. Native mpv chapter assignment undershoots boundaries and causes drift. This applies in `chapter_list.py`, `player.py`, and anywhere else chapter navigation is triggered. The only exception is embedded M4B chapter list clicks where `_chapter_list is None` and `_virtual_timeline is None` — that path still uses `self.chapter = idx` because mpv owns the chapter boundaries natively.

### DO NOT restore any emit in `_on_chapter_change` — it is fully suppressed as of 2026-06-01
`_on_chapter_change` now contains only `return`. `_on_time_pos_change` drives `chapter_changed` universally for all book types (VT, CUE, embedded M4B) via position walk. The old `_is_seeking` guard on `_on_chapter_change` was insufficient: `_on_time_pos_change` clears `_is_seeking` first, so by the time `_on_chapter_change` fires the guard is already False — it emitted stale mpv native chapter values, causing snap-back on Prev/Next while paused. Do not add back any emit here.

### DO NOT set `_virtual_timeline` for CUE books
CUE mode is indicated solely by `_chapter_list` being non-`None` with `_virtual_timeline` remaining `None`. Setting `_virtual_timeline` would activate VT file-switching machinery on a single-file book.

### DO NOT simplify `Player.terminate()`
It must store the instance reference, clear `self.instance`, call `terminate()`, then `wait_for_shutdown()`. Without `wait_for_shutdown()`, libmpv's internal threads outlive Qt's cleanup and crash in `avformat_close_input`. This was masked for an unknown period by a debug print. The sequence is intentional — do not reorder or remove steps.

### DO NOT hard-delete from the `books` table
`remove_scan_location` soft-deletes via `UPDATE books SET is_deleted = 1` — never `DELETE FROM books`. All rows, progress, covers, `book_files`, and session history must survive a location removal so they can be resurrected when the location is re-added. Any query that drives the library view must include `WHERE is_deleted = 0 AND is_excluded = 0`. Stats queries must not — they key off `book_path`/`book_title` in the sessions tables directly and must see all historical rows.

### DO NOT conflate `is_deleted` and `is_excluded`
They are two independent soft-delete flags on `books`. `is_deleted = 1` is set by `remove_scan_location` (location removed from scan list). `is_excluded = 1` is set by `set_book_excluded` (user explicitly removed a book via the trash button). Both reset to `0` in the `upsert_book`/`upsert_books_batch` ON CONFLICT blocks, so rescanning resurfaces either kind of removed book. Stats queries are intentionally unfenced by both flags — listening history and progress survive removal permanently.

### DO NOT swap `get_book_count()` and `get_visible_book_count()` — they serve different purposes
`get_book_count()` queries `SELECT COUNT(*) FROM books` — all rows, including `is_deleted=1` and `is_excluded=1`. Correct for stats (which must see all historical rows). `get_visible_book_count()` queries with `WHERE is_deleted = 0 AND is_excluded = 0` — only rows visible in the library. `compute_library_state` uses `get_visible_book_count()` for `has_indexed_books`; never change it to `get_book_count()`. Using the unfenced count would make `has_indexed_books=True` even when the library panel shows 0 books (soft-deleted rows from a prior scan remain in the DB), routing the empty state into the no-book carousel instead of the scan/quote prompt.

### DO NOT pass `0.0` as `progress` to `upsert_book` or `upsert_books_batch`
The scanner does not know a book's saved playback position. Pass `None` if progress is unknown. The `COALESCE(NULLIF(excluded.progress, 0.0), books.progress)` in both upserts is a safety net against accidental `0.0` — it is not a contract that callers can rely on. Passing `0.0` would overwrite saved progress on any future DB engine that handles `NULLIF` differently.

### DO NOT keep upsert_book and upsert_books_batch out of sync
Both methods share identical SQL logic — any schema or ON CONFLICT guard change in one MUST be applied to the other. They differ only in execute vs executemany. The `CASE WHEN books.X_locked = 1` guards for title, author, narrator, year are load-bearing: they prevent rescans from overwriting user-edited metadata. Skipping this sync causes silent data loss on rescans.

### DO NOT remove the CASE WHEN books.X_locked guards from upsert ON CONFLICT
The guards `CASE WHEN books.title_locked = 1 THEN excluded.title ELSE updated.title END` (and narrator/author/year equivalents) protect user-edited metadata from being overwritten by rescans. They must survive any future refactor.

### DO NOT add separate save/lock widgets to BookDetailPanel
The metadata action button state is driven exclusively by `_MetaActionState` enum. Do not add `_save_label` or `_lock_btn` widgets — use `_set_meta_state()` to manage appearance.

### DO NOT set cursor or stylesheet on chapter widgets outside `_set_chapter_ui_active`
`_set_chapter_ui_active(active: bool)` is the sole owner of chapter slider cursor, chapter label stylesheets, and `WA_TransparentForMouseEvents` state. Do not set these directly in `_build_secondary_controls`, theme application, or any other call site. Theme changes repolish child widgets and clear instance stylesheets — `_apply_stylesheets` reapplies the correct state by calling `mw._set_chapter_ui_active(mw._chapter_ui_active)` at its end. The `_chapter_ui_active` flag tracks the logical state and must stay in sync: always route through `_set_chapter_ui_active`, never set flag or widget state separately.

---

## Tech Stack

PySide6 (Qt) + mpv via python-mpv. Python. SQLite. Mutagen for metadata. See GEMINI.md for full
stack details.

---

## Collaboration Model

- **Claude**: architecture, decisions, code review, documentation, root-cause investigation
- **Gemini**: pipeline scripts, folder naming conventions — kept in lane by GEMINI.md guardrails
- **Windsurf / Copilot**: code generation
- **GPT**: critique

Claude does not need hard constraint rules like GEMINI.md — the working model is "flag, confirm, then act."

## Conventions

- **SESSION.md entries are always prepended** (newest at the top), not appended.
- **All git commit messages must start with a verb** (e.g. `feat:`, `fix:`, `docs:`, `refactor:`).
- **After completing a task, flag if SESSION.md, NOTES.md, CLAUDE.md, or TESTING.md would benefit from an update** — but only when there is something specific and non-obvious worth recording, not as a reflexive offer after every change.

---

## Window

Fixed size: 300×564px (`setFixedSize(300, 564)` in app.py:379). Cover label has no minimum size
so it fills the fixed window. Do not fight this with per-widget minimum sizes.

---

## Implemented Features (complete)

### Player
- Single-file M4B playback with embedded chapter markers
- CUE file chapter support for single-file M4B/M4A books
  - Global setting in Settings → Library: "Embedded" (default) | ".cue"
  - `_resolve_playlist()` detects `.cue` in folder, calls `_parse_cue()` on worker thread
  - `_parse_cue()` validates: FILE stem match, first timestamp = 0.0, strictly increasing, all within file duration (from DB). Reads with `utf-8-sig` to handle Windows ripper BOM.
  - On success: `_chapter_list` populated, `_virtual_timeline` stays `None`. On failure: silent fallback to embedded.
  - `_chapter_list` being non-`None` is the cue-mode flag — no separate boolean needed.
- Multi-file MP3/M4A/FLAC book support via Virtual Timeline (VT)
  - `_resolve_playlist()` in player.py, run on a QThreadPool worker (async)
  - Reads `book_files` DB table (populated at scan time) to build `_virtual_timeline`, plays the first file directly. If `book_files` is empty (no audio files found), falls back to playing the folder path as-is.
  - Gate/ungate pattern: `_play_gated` / `_held_play` / `ungate_play()` in player.py
  - `instance.play()` fires only from `_on_library_hidden` after slide animation completes
- Virtual timeline (VT): `_virtual_timeline`, `_file_offset`, `_chapter_list`, `_current_vt_index`, `_pending_local_pos`, `_is_vt_file_switch`, `_last_vt_chapter`
  - Signals: `book_ready`, `file_switched` (do not reconnect `file_loaded` to `_on_file_ready`)
- Property caching: `time_pos`, `duration`, `pause`, `speed` cached via observe_property
- Async seeking: `Player.seek_async(pos)` uses `command_async('seek', pos, 'absolute+exact')`
  - All UI-driven seeks (slider, chapter, right-click, undo, VT cross-file, chapter nav) use `seek_async`
  - Smart rewind also uses `seek_async` (unified 2026-05-28 — was `time_pos =` on non-VT, now consistent)
  - Skip buttons, position restore remain on sync `time_pos =` path
  - Chapter navigation always uses position-based walk + `seek_async(target + _CHAPTER_BOUNDARY_EPSILON)` — never `self.chapter = idx`
- Stop-and-load seek for single VBR MP3 files: `seek_async` intercepts seeks > `_MP3_SEEK_THRESHOLD` (60s) on single `.mp3` files and calls `_mp3_stop_and_load()` instead of `command_async`. Uses `loadfile start=X` which positions via the Xing/TOC header rather than stream scanning. Playback state restored in `_on_file_loaded` early-return block. `book_ready` is NOT re-emitted during reload. `_mp3_seek_visual_lock` suppresses play/pause icon flicker during the reload window. VT, M4B, and CUE paths are unaffected.
  - MP3 seek state variables: `_play_target` (resolved file path for current book), `_mp3_seek_reload_pending` (guards `_on_file_loaded` early-return and prevents concurrent reloads), `_mp3_seek_was_playing` (pre-reload pause state for restore), `_mp3_seek_visual_lock` (suppresses icon updates during reload window). All reset in `load_book`.
  - VT same-file stop-and-load: `_mp3_stop_and_load` takes optional `file_path` and `local_pos`. `_cached_time_pos` must be set to `local_pos` (not global `target_pos`) so the `time_pos` getter (`_file_offset + _cached_time_pos`) returns the correct global value. Setting it to global `target_pos` double-counts `_file_offset`.
  - Concurrent reload guard: both call sites in `seek_async` include `and not self._mp3_seek_reload_pending`. Stacked `loadfile` calls cause the second `_on_file_loaded` to bypass the early-return and emit `book_ready`, triggering DB position restore.
- `_CHAPTER_BOUNDARY_EPSILON = 0.35` — compensates for mpv's ~23ms undershoot at chapter boundaries and float drift in mpv's internal boundary representation. Lives at seek time, not save time.
- Chapter changed signal path: `_on_time_pos_change` drives `chapter_changed` universally for all book types via position walk — VT (walks `_chapter_list` against global pos), CUE (walks `_chapter_list`), embedded M4B (walks `self.instance.chapter_list`). `_on_chapter_change` is fully suppressed (always returns). `seek_async` also emits `chapter_changed` immediately for CUE mode (where `_chapter_list` is set) as an optimistic paused-case update.
- Per-book speed memory, global speed default, volume control
- Smart rewind on resume
- Undo (one level, position-at-jump stored, triggered if distance > 60s × speed)
- `keep_open='always'` — EOF detection via `_on_pause_test` near-EOF position check, not `end-file`

### UI — Player view
- Cover art display with four fit modes (fit/stretch/crop/top), driven by `_cover_fit_mode`
- Chapter list overlay (child widget of MainWindow, not popup)
  - Fade in/out (600ms), expand/collapse, keyboard nav, digit jump with 800ms debounce
  - Digit modes: by_name (word-boundary regex) / by_index (1-based), auto-play/jump-only configurable
- Progress slider with chapter notch markers and notch reveal animation
- Chapter progress slider
- Flow animation on book switch (progress and chapter sliders animate between positions)
- Theme-aware UI timer guards: `_sync_progress_sliders` and `_sync_chapter_ui` skip setValue during animation
- `self._switch.in_deadzone` flag (`book_switch.py`) — prevents stale position display during library panel slide-out (was `_mpv_ready`)
- Scrolling labels for title/author (ScrollingLabel)
- Speed controls panel
- Sleep timer panel
- Sidebar with stats, settings, cover, book detail access

### Book Detail Panel (implemented — web Claude sometimes thinks it's not)
- Header: inline editable title, author, narrator, year fields (QLineEdit styled as labels)
  - `_ElidingLineEdit` with 3px left margin, `setCursorPosition(0)` in read-only mode
  - App-level event filter for click-outside detection
  - Metadata lock feature: four independent locks (title_locked, author_locked, narrator_locked, year_locked) persist changes across rescans
  - Unified metadata action button (`_meta_action_btn`, 24×24 QToolButton in right column below close button)
    - DIRTY state: save icon, click to save changes and set locks
    - LOCKED state: lock icon, click to unlock all four fields
    - UNLOCKED state: lock-open icon, auto-hides after 2.5s
    - HIDDEN state: button invisible when no locks and not editing
  - Click-outside dismissal: reverts to pre-edit state (LOCKED if locked before, HIDDEN if not)
- Stats tab: furthest position `_RangeBar`, remaining time (speed-aware), last session row, recent history `SessionListWidget`
- History tab: full `SessionListWidget` (same data, separate widget)
- Tags tab: FlowLayout chip display, add field with QCompleter, remove buttons
  - Per-book limit: 5 tags. Global limit: 50 unique tags.
  - `_tag_display_label` always visible with `setFixedHeight(38)` — tag row always reserves height
  - Completer popup styled directly via `_style_completer_popup()` (lazy init, styled on first keystroke)
- Header cover: 80×120 fixed-width, updated on active cover or fit mode change
- Duration label: wall-clock by default, toggles to speed-adjusted on click
  - Cursor disabled (arrow) and toggle disabled when speed is 1.0x (uses tolerance `abs(speed - 1.0) < 1e-9`)
  - Sourced from `config.get_book_speed()` with fallback to `config.get_default_speed()`

### Cover Panel (implemented)
- Up to 4 user cover slots (sort_order 1–4) + 1 locked scanner cover (sort_order=0)
- `_left_col` fixed height: `n × 72 + max(n-1, 0) × 6`, updated via `_update_left_col_height()`
- Preview: 205×270 fixed. Top/Crop rendered as w×w square centered in w×h canvas (letterbox bars)
- Overlay suppressed when sole cover is locked
- Fit mode propagates to main window on active cover change
- `_load_cover_art` has early-return for no-cover books → shows "author - title"
  - `library_controller.apply_library_state` does NOT pass `show_metadata=False` when `has_book=True` — do not restore this, it was a bug

### Library Panel
- Qt model/view: `BookModel(QAbstractListModel)` + `BookDelegate(QStyledItemDelegate)`
- Five view modes: 1/2/3-per-row grid, square, list (no list-mode `setIndexWidget`)
- `_cover_cache` keyed by `book.id` (int), not `book.path`
- `CoverLoaderSignals.cover_loaded` signal: `Signal(int, QImage)` — int is book_id, QImage converted to QPixmap on main thread
- Viewport-aware cover loading (`_load_visible_covers` uses binary search on visualRect)
- Idle preloader: batches of 3, 50ms intervals, starts 4s after launch, pauses on interaction
- Search: plain text, `#tag` prefix, `>NNNN`/`<NNNN` year filters, range combos
  - No-match: red background on search field, fallback to all books
  - Incomplete year filter (`<` or `>` with partial digits) never shows red
- Sort by title/author/recent/progress/duration/year with asc/desc toggle
- `_on_sort_changed` and `_toggle_sort_direction` fire `singleShot(0, _load_visible_covers)` after sort

### Stats Panel
- Day/Week/Month tabs with `BookDayRow` and `SessionListWidget`
- Timeline tab (heatmap, deferred via `singleShot(0, _refresh_time)`)
- Finished books tab
- Tag manager (⚙ tab): `TagManagerWidget` — list view and tag panel view
  - DB methods: `get_all_tags`, `get_books_by_tag`, `rename_tag`, `delete_tag`, `get_unique_tag_count`
- Period cache: `_cached_active_days/weeks/months`, invalidated in `refresh_all`/`refresh_current_tab`
- `_add_row_safely` helper: hide-before-insert, show-after, wrapped in `setUpdatesEnabled(False/True)` — fixes first-visit flash
- `_inject_active_covers(rows)` — enriches row dicts with `"active_cover_path"` from `book_covers` before widget construction. Must be called at every `BookDayRow`/`FinishedBookThumb` construction site.
- `on_cover_changed(book_path, cover_path)` — targeted refresh: walks visible tab's rows via `_iter_day_rows`/`_iter_finished_thumbs`, calls `refresh_cover` on matching widgets only. No tab rebuild.
- `BookDayRow.refresh_cover` and `FinishedBookThumb.refresh_cover` — evict cache entry, re-trigger worker. On empty `cover_path` (last cover removed), restore placeholder immediately without spawning a worker.

### Theme System
- 50+ named themes in themes.py. Per-component stylesheets (never `main_window.setStyleSheet()` globally)
- `ThemeManager._apply_stylesheets(theme_name, hover=False)` dispatches to 7 components
- Cover-art based dynamic theme via colorthief (with pool / exclusive modes)
- Theme hover preview with 200ms snapback
- Theme rotation (manual, timed, panel-aware deferral via `_pending_rotation`)
- Overlay fade (750ms) — `snap_theme_forward()` on panel open; `abort_theme_fade()` on panel close
  - `user_initiated` flag: automatic changes snap when Themes tab (index 0) is active
  - Themes tab remains QSS-driven (per-element animation ruled out — see SESSION.md 2026-05-10)
  - `_SNAPBACK_FADE_MS = 200`, `_THEME_SWITCH_FADE_MS = 750`, `_PANEL_ANIM_GUARD_MS = 700` at top of theme_manager.py

### Settings Panel
- Themes tab, Controls tab, Audio tab (WAL + other DB settings), Library tab
- Controls tab: chapter digit mode (by_name/by_index), auto-play/jump-only toggle
- Library tab: naming pattern, folder management, chapter source (Embedded / .cue)

### Session Recording
- DB: `listening_sessions`, `book_events` tables. WAL mode. Index on `book_id`.
- `listening_sessions`, `book_events`, and `book_tags` use `book_id INTEGER REFERENCES books(id)` as their book FK. `book_path` columns are retained but deprecated — not written or queried, not dropped. Orphaned rows (path no longer in `books`) keep `book_id = NULL` and still surface in stats via LEFT JOIN.
- 60s wall-clock threshold, 3min pause timeout, 15s seek credit
- `started_at`, `finished_at` on books table

#### SessionRecorder (`session_recorder.py`)
All session state and persistence logic lives in `SessionRecorder(QObject)`, not `MainWindow`. `MainWindow` holds `self.session_recorder` and delegates all lifecycle calls to it. `_current_book` stays on `MainWindow` — the recorder receives it via `get_book_fn=lambda: self._current_book`.

**Public API:**
- `open()` — start a new session (first play after no active session)
- `resume()` — resume after a short pause (< 3 min window)
- `pause()` — accumulate segment time, start 3-min timeout
- `close()` — flush to DB if ≥ 60s listened, reset all state
- `update_furthest_position(pos)` — called from the 200ms UI loop; replaces inline furthest-pos tracking that was in `_update_ui_sync`
- `notify_seek(new_pos)` — called from slider released handlers; replaces duplicated seek-credit logic
- `is_active` — property, True when session is open

**Signal:** `session_written` lives on `SessionRecorder`, not `MainWindow`. Connect via `self.session_recorder.session_written.connect(...)`.

**DB migration status:**
- `set_started_at` / `get_book_started_at` — fully migrated to `book_id` (no `book_path` lookup). No other call sites outside `session_recorder.py`.
- `write_session` / `write_book_event` — still dual-write `book_path` + `book_id`. `book_path` columns not yet dropped — pending final column drop pass.

---

## Critical Architecture Rules

### DO NOT use `self.player.chapter` for chapter display
Always derive chapter by walking `self.player.chapter_list`, finding last entry where `time <= pos + 0.35`. mpv updates chapter property asynchronously.

### DO NOT use `self.chapter = idx` for chapter navigation
Always use `seek_async(target_time + _CHAPTER_BOUNDARY_EPSILON)` with a position-based walk. Exception: embedded M4B chapter list clicks where `_chapter_list is None` and `_virtual_timeline is None`.

### DO NOT restore any emit in `_on_chapter_change` — it is fully suppressed
`_on_chapter_change` always returns immediately. `_on_time_pos_change` is the sole driver of `chapter_changed` for all book types. The old `_is_seeking` guard was insufficient — it cleared before `_on_chapter_change` fired, causing paused-state snap-back.

### DO NOT set `_virtual_timeline` for CUE books
CUE mode = `_chapter_list is not None` and `_virtual_timeline is None`. Setting `_virtual_timeline` activates VT file-switching on a single-file book.

### DO NOT simplify `Player.terminate()`
Must store instance, clear `self.instance`, call `terminate()`, then `wait_for_shutdown()`. Without `wait_for_shutdown()`, libmpv threads crash in `avformat_close_input`.

### DO NOT connect `_on_file_ready` to `file_loaded`
Must only connect to `book_ready`. `file_loaded` fires on every mpv file load including VT mid-book switches; causes quadruple-advance feedback loop.

### DO NOT read `progress_slider.value()` in `_on_file_ready` for animation
Slider value is stale. Always compute from `int((new_progress / self.player.duration) * 1000)`.

### DO NOT seek to a position within 2 seconds of a file's duration
mpv hangs silently when seeked within ~2s of EOF — no error, no event, no recovery. Every `command_async('seek', ...)` or `loadfile start=X` call must be preceded by a guard that returns early if `duration - pos < 2.0`. Guards currently live in `seek_async` (player.py): VT same-file branch checks `target_file['duration'] - local_pos < 2.0`; non-VT branch checks `self._cached_duration - pos < 2.0`. The stop-and-load path has its own 5s buffer. If any new seek path is added, the buffer must be present.

### DO NOT join `book_events` directly into a query that aggregates `listening_sessions`
The join produces a cartesian product (sessions × finished events per book) before GROUP BY, inflating `SUM(listened_seconds)` by the finished event count. Always use a correlated scalar subquery: `(SELECT MAX(CASE WHEN be.event_type = 'finished' THEN 1 ELSE 0 END) FROM book_events be WHERE be.book_id = b.id) as is_finished`. Applies to `get_daily_book_breakdown`, `get_books_listened_in_period`, and any future query with the same shape.

### DO NOT remove animation-state guards in `_sync_progress_sliders` / `_sync_chapter_ui`
Both check whether animation is running before setValue. Removing causes jitter from 200ms timer fighting animation.

### DO NOT touch MPV init block
`_ensure_mpv()`, `load_book()` MPV block, `locale.setlocale(LC_NUMERIC, "C")`, all MPV constructor args. Hard-won Wayland/libcaca/libtinfo/Qt locale bug fix. Changing anything breaks the app.

### DO NOT restore `show_metadata=False` to `library_controller.apply_library_state`
Removed in 2026-05-11 — it was silently overriding cover display on every book switch. `_load_cover_art` owns `metadata_label` visibility.

### DO NOT use `active_cover_changed` on `BookDetailPanel` as a single-arg signal
It emits `(book_path, cover_path)` — both args required at all call sites. `CoverPanel.active_cover_changed` remains `Signal(str)`; the intermediate slot `_on_cover_panel_changed` in `BookDetailPanel` injects `self._book_path` and re-emits. Do not connect `CoverPanel.active_cover_changed` directly to `BookDetailPanel.active_cover_changed`.

### DO NOT pass raw DB rows directly to `BookDayRow` or `FinishedBookThumb`
Always call `StatsPanel._inject_active_covers()` on the row list first. Raw rows carry only `cover_path` (scanner thumbnail); `_inject_active_covers` adds `active_cover_path` from `book_covers`. Skipping it causes stats panel thumbnails to show scanner art instead of the user-selected cover.

### DO NOT remove the `has_progress` gate on speed application in `BookDelegate._resolve_playback`
Speed is only applied to `dur_disp` when `has_progress` is `True`. Books with no progress always show total duration at 1x regardless of per-book speed. Removing this gate causes incorrect duration display in the library view.

### DO NOT replicate `apply_library_state(compute_library_state())` at a call site
`apply_current_state()` on `LibraryController` is the sole entry point for reconciling library UI state without scan side effects. Any call site that needs compute-and-apply (but not a scan trigger) must call `self.library_controller.apply_current_state()` — never inline the two-liner. Inlining the compute+apply pair creates sync-drift risk identical to the `upsert_book` / `upsert_books_batch` invariant: the pairing can drift independently from `apply_current_state`'s implementation. `_check_library_status` delegates to `apply_current_state` internally and additionally calls `handle_background_tasks`; use it only when a scan trigger is appropriate.

### DO NOT suppress the theme `bg_image` by overriding `visual_area` — regenerate the stylesheet without it
The theme `bg_image` is painted by `content_container`'s `QWidget#visual_area { background-image: url(...) }` rule in `get_player_stylesheet`. It is stripped in the no-book and empty-library states (where it overlapped the prompts/carousel/quote). The ONLY working suppression is `get_player_stylesheet(theme_name, suppress_bg_image=True)`, which omits the image at generation time. Do NOT attempt to cancel it with a child override (`visual_area` instance stylesheet, a `background-image: none` rule, or a dynamic property like the removed `carouselActive`): Qt's QSS cascade treats `background-image: none` as "unspecified", so the ancestor `url()` wins on the child per-property and the image survives (verified — a child `background-color` override applied while the image layered on top). `MainWindow._set_bg_suppressed(suppressed)` is the sole authority: it sets `_bg_suppressed`, sets `setAutoFillBackground(not suppressed)`, and re-applies the regenerated stylesheet. `apply_library_state` drives it (`True` for empty + no-book, `False` for has_book) and `ThemeManager._apply_stylesheets` reads `_bg_suppressed` so a theme change in those states keeps the image stripped. `_show_carousel`/`_hide_carousel` must NOT touch background or `autoFillBackground` — suppression is owned by the state machine, not the carousel.

### DO NOT revert `_update_cover_art_scaling` to reading `cover_art_label.height()` for `target_h`
`_update_cover_art_scaling` uses `COVER_AREA_HEIGHT` (a module-level constant in `app.py`) as `target_h`, not `self.cover_art_label.height()`. The live allocated height is transient and state-dependent — it reflects whatever the layout engine allocated at the moment of the call, which can be wrong during any state transition (empty→book, no-cover→cover, panel open/close). The constant decouples scaling from layout state and prevents any cover aspect ratio or state transition from breaking the layout. `cover_art_label` is also pinned with `setFixedHeight(COVER_AREA_HEIGHT)` in `_build_cover_art`. If the window layout ever changes, re-calibrate `COVER_AREA_HEIGHT` empirically by testing covers of various aspect ratios and confirming no bottom clipping in fit mode.

---

## Pending / Known Debt

- `_cover_cache` has no eviction policy (unbounded LRU). Deferred.
- Theme transitions — long-term path is per-element `@Property(QColor)` animation, but Themes tab QSS complexity makes it non-trivial. `THEME_ANIM_TODO` comments mark instrumented widgets.
- `CoverLoaderWorker` anonymous type objects in stats_panel/tag_manager (path→ID migration context). Deferred to next cover refactor.
- Sleep timer state not persisted across restarts (`get_sleep_duration`/`get_sleep_mode` never read on startup). Product decision deferred.
- Screen drag 4K→1080p: cover scaling doesn't update without scroll (needs `QWindow.screenChanged`).
- MP3 natural sort (2 before 10) — out of scope for v1.
- Book detail panel background opacity — user wants it opaque eventually. Not in current scope.
- **Deleted/excluded book UI in stats panel** — stats panel shows sessions and history for excluded books (via `listening_sessions` join, which is unfenced by `is_excluded`). No visual differentiation currently. Duration label not clickable for books no longer in the library. Cover monochrome, metadata read-only, Cover+Tags tabs hidden — deferred to Session 7.
- **Session recording gaps (fully deferred):**
  - VT file switches — `session_recorder.close/open` wiring doesn't account for mid-book VT file transitions. `file_switched` is not threaded into the session recorder.
  - Sleep timer — sleep feature prevents session recording during the sleep window. Deferred.
- **`path_to_index()`** is in `library.py` (`LibraryPanel`, not `BookModel`).
- **VT open issues (multi-file MP3) — fully deferred:**
  - Progress slider race on book switch with VT books — timing between `_on_playlist_resolved`, `ungate_play`, and slider animation needs verification.
  - M4B chapter stuck intermittently — chapter display freezes at a chapter boundary in some M4B books; root cause not yet isolated.
  - Rapid book switch (VT → any) regression: test that the newly selected book's progress slider shows the correct position and not 0%. Symptom of a double-handler invocation resetting progress; fixed via disconnect-before-connect in `load_book`, but should be part of regression runs.

---

## Files and Responsibilities

```
src/fabulor/
├── app.py                    # MainWindow wiring + module-level interface classes (VisualsInterface, PanelInterface, UICallbackInterface, LibraryInterface, PlayerInterface, BrowserInterface, UIInterface, AppInterface)
├── player.py                 # MPV wrapper, VT, async seek, gate/ungate
├── db.py                     # SQLite layer
├── config.py                 # QSettings wrapper
├── themes.py                 # Theme dicts + per-component QSS functions (get_player_stylesheet accepts suppress_bg_image)
├── library_controller.py     # Library logic, scan wiring, apply_library_state, _set_bg_suppressed
├── settings_controller.py    # Settings logic (dynamic binding)
├── session_recorder.py       # SessionRecorder — session open/pause/resume/close, checkpoint, furthest-pos tracking
├── book_switch.py            # BookSwitchState — single authority for the book-switch transition lifecycle (phase, deadzone, pre-switch captures, deferred flags)
├── book_quotes.py            # Quote pool for the empty/no-book state rotation
├── assets.py                 # get_asset_path helper (resolves paths into the assets/ bundle)
├── library/
│   ├── scanner.py            # Async file scan (threading.Event for cancel)
│   └── cover_manager.py      # Cover extraction and DB persistence helpers
├── models/
│   └── book.py               # Book dataclass
└── ui/
    ├── controls.py           # ClickSlider (animatedValue, when_animations_done), HoverButton, FreezableLabel
    ├── chapter_list.py       # Chapter list overlay (child widget, not popup)
    ├── library.py            # BookModel, BookDelegate, LibraryPanel (owns evict_cover/get_cached_cover — app.py must not access _cover_cache directly), _cover_cache
    ├── cover_loader.py       # CoverLoaderWorker: Signal(int, QImage)
    ├── cover_panel.py        # Cover management panel
    ├── cover_theme.py        # Dominant color extraction
    ├── theme_manager.py      # ThemeManager — overlay, snapback, rotation; reads _bg_suppressed on theme change
    ├── panels.py             # PanelManager — all panel open/close flows
    ├── book_detail_panel.py  # Book detail (stats, history, tags, cover header, inline edit)
    ├── stats_panel.py        # Stats panel, SessionListWidget, _RangeBar
    ├── tag_manager.py        # TagManagerWidget — tag list, tag panel, book grid, color picker
    ├── title_bar.py          # Custom title bar
    ├── speed_controls.py     # Speed panel
    ├── sleep_timer.py        # Sleep timer panel
    ├── audio_controls.py     # Audio settings panel (normalisation, voice boost, balance, stereo/mono)
    ├── carousel.py           # CoverCarousel — ambient scrolling strip in no-book state
    ├── flow_layout.py        # FlowLayout (heightForWidth implemented)
    ├── icon_utils.py         # render_logo_placeholder, render_logo_placeholder_bordered — SVG logo placeholder renderers
    └── text_context_menu.py  # Right-click Cut/Copy/Paste/Delete context menu for metadata and tag fields
```

---

## Stylesheet Architecture

Each major component owns its stylesheet. Never call `main_window.setStyleSheet()` with a full-app stylesheet.

| Widget | Function |
|---|---|
| `main_window` | `get_base_stylesheet()` — bg, tooltips, chapter_dropdown, undo overlay |
| `title_bar` | `get_title_bar_stylesheet()` |
| `content_container` | `get_player_stylesheet()` — cover, sliders, playback buttons, metadata labels |
| `library_panel` | `get_library_stylesheet()` — skipped during hover |
| `settings_panel`, `speed_panel`, `sleep_panel` | `get_settings_stylesheet()` |
| `sidebar` | `get_sidebar_stylesheet()` |
| `stats_panel` | `get_stats_stylesheet()` |
| `tags_panel` (`TagManagerWidget`) | `get_tags_stylesheet()` |

### Wrapping a layout in a `QWidget` for naming purposes requires explicit `setSpacing`

When a `QHBoxLayout` is added directly to a parent layout via `addLayout`, it fills the full available width and inherits style-derived spacing. When the same layout is wrapped in a `QWidget` (for `setObjectName`, `setVisible`, etc.) and added via `addWidget`, two things change: (1) the widget shrinks to its children's fixed sizes unless given `setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)`, and (2) spacing is no longer guaranteed by style inheritance. Always call `setSpacing(N)` explicitly on any layout inside a named `QWidget` wrapper.

### `WA_StyledBackground` required for QSS on plain `QWidget` containers

Any `QWidget` subclass (not `QFrame`, not `QLabel`) that owns a background-color QSS rule **must** call `setAttribute(Qt.WA_StyledBackground, True)`. Without it Qt silently ignores the background rule — the widget appears either fully transparent or painted by the system palette. This applies to every panel root widget and any intermediate container that needs its own background. Child containers that should be transparent must NOT set `WA_StyledBackground` — set it only on the root. Verified on `TagManagerWidget` (2026-05-24).

---

*Last updated: 2026-06-03 — file tree synced with tracked sources (added session_recorder.py, book_quotes.py, assets.py, library/cover_manager.py, models/, ui/audio_controls.py, ui/carousel.py, ui/icon_utils.py, ui/text_context_menu.py; corrected models/book.py path; updated descriptions for themes.py suppress_bg_image, theme_manager.py _bg_suppressed, tag_manager.py, stats_panel.py, controls.py FreezableLabel); bg-image suppression invariant added to Critical Architecture Rules.*
