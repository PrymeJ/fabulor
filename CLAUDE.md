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

### DO NOT read self.progress_slider.value() (or any slider's .value()) in _on_file_ready to compute the "new position" for a switch animation. The slider value is stale at that point — _update_ui_sync's setValue call is gated on not slider_animating and not is_seeking and may not have run yet. Always compute the target slider value from the authoritative data: int((new_progress / self.player.duration) * 1000).

### DO NOT remove the animation-state guard in _sync_progress_sliders or _sync_chapter_ui. Both methods check whether the flow animation is running before calling setValue. If that check is removed, the 200ms UI timer will fight the animation frame-by-frame, causing visible jitter. The guard must survive any refactor of those methods.

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
- `_mpv_ready` deadzone flag — prevents stale position display during library panel slide-out
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
├── app.py                    # MainWindow wiring + module-level SettingsController interface classes (VisualsInterface, PanelInterface, UICallbackInterface, LibraryInterface, PlayerInterface, BrowserInterface) — ~2570 lines
├── player.py                 # MPV wrapper, VT, async seek, gate/ungate
├── db.py                     # SQLite layer
├── config.py                 # QSettings wrapper
├── themes.py                 # Theme dicts + per-component QSS functions
├── library_controller.py     # Library logic, scan wiring
├── settings_controller.py    # Settings logic (dynamic binding)
├── library/
│   └── scanner.py            # Async file scan (threading.Event for cancel)
└── ui/
    ├── controls.py           # ClickSlider (animatedValue, when_animations_done), HoverButton
    ├── chapter_list.py       # Chapter list overlay (child widget, not popup)
    ├── library.py            # BookModel, BookDelegate, LibraryPanel (owns evict_cover/get_cached_cover — app.py must not access _cover_cache directly), _cover_cache
    ├── cover_loader.py       # CoverLoaderWorker: Signal(int, QImage)
    ├── cover_panel.py        # Cover management panel
    ├── cover_theme.py        # Dominant color extraction
    ├── theme_manager.py      # ThemeManager — overlay, snapback, rotation
    ├── panels.py             # PanelManager — all panel open/close flows
    ├── book_detail_panel.py  # Book detail (stats, history, tags, cover header, inline edit)
    ├── stats_panel.py        # Stats panel, TagManagerWidget, SessionListWidget, _RangeBar
    ├── tag_manager.py        # TagManagerWidget internals
    ├── title_bar.py          # Custom title bar
    ├── speed_controls.py     # Speed panel
    ├── sleep_timer.py        # Sleep timer panel
    ├── flow_layout.py        # FlowLayout (heightForWidth implemented)
    └── models/
        └── book.py           # Book dataclass
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

### `WA_StyledBackground` required for QSS on plain `QWidget` containers

Any `QWidget` subclass (not `QFrame`, not `QLabel`) that owns a background-color QSS rule **must** call `setAttribute(Qt.WA_StyledBackground, True)`. Without it Qt silently ignores the background rule — the widget appears either fully transparent or painted by the system palette. This applies to every panel root widget and any intermediate container that needs its own background. Child containers that should be transparent must NOT set `WA_StyledBackground` — set it only on the root. Verified on `TagManagerWidget` (2026-05-24).

---

*Last updated: 2026-05-24 — library_year theme key added (1-per-row year field color, falls back to library_narrator); library overlay (2/3-per-row, Square) switched from hardcoded white to library_elapsed/library_total/library_percentage theme colors; cover_theme.py updated with brighter text/text_dim/text_dimmer values, chap_fill_lighter and slider_bg_lighter variants for improved overlay legibility.*
