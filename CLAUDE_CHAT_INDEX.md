# Fabulor — Project Chat Index

Reverse-chronological index of architecture/design chat windows (newest → oldest).  
VS Code / Claude Code implementation windows are not included.  
Use this file to locate which window discussed a given topic before pulling it up for context.

---

## 31. `fabulor: | Stats panel carousel placeholder flashing bug` — Jun 4 2026
**URL:** https://claude.ai/chat/2303cfb1-3f7d-44ff-8c74-85fde0d763b1

- Finished-books carousel: placeholder flash on tab switch for specific books
- Root cause: `FinishedBookThumb._on_cover_loaded` not writing to `_cover_cache[book_id]` — result consumed locally and discarded
- Fix: cache write in `_on_cover_loaded`; `self._book_id` stored in `__init__`
- `FinishedScrollRow.set_items`: `_current_ids` guard (set equality) skips rebuild when IDs unchanged
- `setParent(None)` replaces `deleteLater()` for synchronous widget removal
- `setMinimumWidth` computed after population (`n × 47 + (n−1) × 4`)
- First-visit cold-cache flash (startup, preloader not yet reached) accepted
- Mouse wheel navigation on the date header row (the ‹/› + date label widget) in Day, Week, and Month tabs
- Right-click on ‹/› nav buttons jumps to oldest/newest period
- "Period scroll acceleration" toggle in Stats ⚙ tab; step table for Day tab (1/2/3/4/7)

---

## 30. `fabulor: | Carousel stripe full-width bleed issue` — Jun 4 2026
**URL:** https://claude.ai/chat/899b605a-fcfa-4562-bd8c-2ab040afaadd

- Carousel stripe: 300px full-width solid-colour background in no-book state
- Attempt 1: `AlignHCenter` inside 280px `carousel_holder` — constrained to 280px, no bleed
- Attempt 2: `setGeometry(-10, y, 300, h)` parented to `visual_area` — failed (mode not confirmed)
- Diagnostic prints to check: parent, geometry, `WA_ClipChildren`, `autoFillBackground`
- Fallback: parent to `content_container` instead of `visual_area`
- Session ended before carousel resolved; finished book handling deferred to new window

---

## 29. `fabulor: || state machine, empty states, carousel, path list, scanner UX` — Jun 3 2026
**URL:** https://claude.ai/chat/f6c5920a-e572-4fa2-a571-a0e25009de55

- Cover art exceeding bounds: `COVER_AREA_HEIGHT=280` constant; `setFixedHeight(280)` + `AlignCenter` on `cover_art_label`; `_update_cover_art_scaling` uses constant as `target_h` (invariant — never revert to label height)
- Chrome restore failure after empty→add library→load book path: `apply_current_state()` added in deferred `singleShot(0)` in `_on_book_selected_from_library`
- `apply_current_state()` extracted as public method on `LibraryController` — compute + apply without scan side effects
- `_check_library_status` delegates to `apply_current_state()` then feeds returned state to `handle_background_tasks`
- 10px calibration error: `COVER_AREA_HEIGHT=290` → 280 (self-diagnosed)
- Chapter list opens toward cover art area — would overlap if cover enlarged (deferred resize)
- Next task: empty-state UX pass (no-library and no-book-selected views)

---

## 28. `fabulor: || MP3 seek - multiple files` — Jun 1 2026
**URL:** https://claude.ai/chat/bea0b470-409c-4ba2-a650-3c2f790e6d68

- `command_async` replaces sync `time_pos` writes for slider-driven seeks
- All hot mpv properties (`time_pos`, `duration`, `pause`, `speed`) moved to observer-cached values
- `is_seeking` clearance moved to `time_pos` observer (clears only when mpv settles)
- Virtual timeline (VT) architecture for multi-file MP3 folders
- `book_files` DB table: per-file duration and cumulative offset
- Player loads one file at a time (not `concat://`); `seek_async` resolves global pos to `(file, local_offset)`
- Signal separation: `book_ready` (once per book, from `ungate_play`/`_on_playlist_resolved`) vs `file_switched` (per VT load, lightweight handler only) vs `file_loaded` (unused in app.py)
- `book_ready` fires before `instance.play()` for VT books — breaks infinite load feedback loop
- Natural file advancement via `_advance_or_finish` from `_on_pause_test`, gated by `_is_vt_file_switch`
- `keep_open='always'`: `end-file` reason 0 never fires; VT uses position-based advancement
- VT-aware chapter navigation: `previous_chapter`, `next_chapter`, `seek_within_chapter` walk `_chapter_list` by global `time_pos`
- `_last_vt_chapter` drives `chapter_changed` emission by detecting transitions in `_on_time_pos_change`
- `_cached_time_pos` / `_cached_duration` cleared in `load_book` reset block
- `handle_forward`/`handle_rewind` use `seek_async`; guard: `reload_pending AND old_pos is None`
- EOF crash fix: 2s buffer before file end in all `seek_async` paths
- Deferred: single large MP3 seek (planned "Optimize" action); intermittent M4B chapter-stuck-after-VT-session (instrumented); sessions not recorded on VT file switches

---

## 27. `fabulor: ||| Weekly audit 05.29, app.py audit, SessionRecorder, theme fade ghost fix, label freeze, sleep in sessions, weighted rotation` — May 31 2026
**URL:** https://claude.ai/chat/6517044d-d2b4-463b-a304-5e3cd6d01fc5

- Six-pass audit of `app.py`
- Dead inner imports removed (Pass 1)
- Uninitialized state variables fixed (Pass 2)
- `_classify_filter` and `save_search_filter` moved to `LibraryPanel` (Pass 3)
- `SessionRecorder` extracted to `session_recorder.py` owning all session lifecycle state, timers, signals, 30s JSON checkpoint (Pass 3)
- Invariant #1 violation fixed: `self.player.chapter` direct read replaced with epsilon walk (Pass 4)
- `time_pos` None guards, `reload_pending` guards, `refresh_overall()` every 200ms at EOF fixed (Pass 4)
- `set_started_at`/`get_book_started_at` migrated from `book_path` to `book_id` (Pass 5)
- Undo animation connect/disconnect replaced with `_on_undo_anim_finished` dispatcher (Pass 6)
- `SessionRecorder.open()` bug: `_post_seek_pending_position` + seek credit timer dangling → `0.0→0.0` records
- Undo points extended to long skip buttons and mouse wheel chapter seek
- Session integration: sleep timer start/expiry, chapter list right-click force-play
- Sleep timer: raw float comparison (was firing ~1s early)
- `_format_duration`: floor → round with carry guard for 60-minute edge case
- Tag refresh: `_on_book_tags_changed` routes to `tags_panel.refresh_books()` (not `refresh()`)
- Theme fade ghost fix: `_do_fade_with_slider_animation` for non-settings fades; `QPropertyAnimation` on `bg_color`/`fill_color`/`notch_color`; label text frozen during fade
- Weighted perceptual theme rotation: bg hue 45%, bg lightness 25%, bg sat 15%, accent hue 15%; inverse-distance weighting exponent 1.0; exclusion threshold 0.5 when pool >4; recent window `min(pool//4, 8)`
- T-key theme shortcut: fires immediately, 2s cooldown, one pending max

---

## 26. `fabulor: ||| Text right click context menu, mouse pointer states, library search persistence, smart rewind UI improved, stop-and-load and visual lock introduced, DB migration, stats inflation, MP3 EOF crash fixed` — May 29 2026
**URL:** https://claude.ai/chat/e342f88f-a075-4daa-960b-63d28fbf4e55

- Theme preview sidebar bleed: stylesheet dropping off theme pool widget mid-preview (not masking issue)
- Scoped stylesheet excluding theme pool during panel animation → cold-cache miss pattern
- P2-C + P6-A + 320ms timer: identified as fragility cluster, documented in NOTES.md, deferred
- Undo animation: `_on_undo_anim_finished` single persistent slot with `_undo_sliding_in: bool | None` direction flag, replacing connect/disconnect machinery

---

## 25. `fabulor: ||| Weekly codebase audit 05.22, tags` — May 26 2026
**URL:** https://claude.ai/chat/6ca3801f-78b7-4e1d-99b3-ef00f7de8738

- `Player.terminate()` regression: `wait_for_shutdown()` silently dropped — fixed immediately (crash risk in `avformat_close_input`)
- `path_to_index()` location corrected (in `library.py`); `_id_for_path()` added to `BookModel` for ID lookup from `_books`
- Tag color feature: `tags` table with `color TEXT DEFAULT NULL`; `TAG_COLORS` palette (9 named colors)
- `icon_utils.py` created as shared SVG loading utility
- Tag chip character limit: 25 → 20
- `TagManagerWidget` promoted to standalone sidebar panel (`TAGS` entry)
- Tag list rows: colored dot + truncated name + count badge (number only)
- Individual tag panel: back button own row; dot/name/action-button second row
- `QStackedLayout` reserved row (32px) for color picker / delete confirmation / empty — no layout shift
- Action button cycles: trash → save (dirty) → check (post-save 1.5s)
- Delete confirmation: `_ClickableLabel`, 7s timer, grid lock, cancel-on-outside-click
- `_update_list_dot()` for targeted list row update without full grid rebuild
- `check.svg` created with `stroke="#000000"` polyline convention
- Right-click on tag thumbnails → book detail panel; nav button in book detail's Tags tab → tag manager
- 320ms `QTimer.singleShot` after `hide_all_panels` documented as debt

---

## 24. `fabulor: | Archived book detail panel read-only mode` — May 22 2026
**URL:** https://claude.ai/chat/cbfc4039-6616-4d87-8ea4-6def92ba143a

- Archived books: metadata/cover/tag editing kept; grayscale cover only visual signal; trash button hidden
- `_is_archived` flag must be set BEFORE the cover block that reads it in `load_book()` (ordering bug fixed)
- Tag manager refresh chain: trash button, scan completion, active cover change — all three wired
- `refresh_tag_manager()` and `refresh_stats()` wrappers added to `AppInterface`
- `Format_Grayscale8` drops alpha → placeholder logo renders with black background (deferred, TODO added)
- `get_book_dict()` added to `db.py` returning raw dict from `SELECT *` (Book object lacks `is_deleted`/`is_excluded`)
- Folder watching deferred; `watchdog` library confirmed as correct choice
- Mark-finished design: write to `book_events`, reset progress, hide from Progress view, near trash button, non-reversible
- SVG transport icon work identified as separate chat topic; opener prompt drafted

---

## 23. `fabulor: | SVG transport control icons for audiobook player` — May 21 2026
**URL:** https://claude.ai/chat/0e3dadbb-9864-47af-b6d4-29d2b4d89c8d

- Three-tier button color theme key system: `button_play`, `button_skip`, `button_chapter` → fallback to `button_text`
- Button sizes: play/pause/restart=56×33px, others=46×33px; icon display sizes specified
- Skip icon variants: 1/2/3 chevrons for 5s / 10s+15s / 30s; `_update_skip_icons()` on init and settings change
- PySide6 SVG renderer does NOT honour `currentColor` — `_load_svg_icon()` must target inline `style=` CSS (Inkscape export style), not just XML `fill=`
- Restart icon: arc geometry failed; external SVG adopted, viewBox manipulation used for sizing
- `icon_utils.py` created as shared SVG icon loading utility

---

## 22. `fabulor: | metadata lock, Stats covers, duration fix` — May 20 2026
**URL:** https://claude.ai/chat/b7c17ffa-5c9c-4981-adcf-c3c45034e30a

- Metadata lock: 4 bool lock columns in `books`; `CASE WHEN books.X_locked` in both `upsert_book` and `upsert_books_batch` (invariant: both must stay in sync)
- `_meta_action_btn` driven by `_MetaActionState` enum: HIDDEN, DIRTY, LOCKED, UNLOCKED
- `active_cover_changed` changed to `Signal(str, str)` emitting `(book_path, cover_path)`
- `_load_svg_icon` cached via `lru_cache(maxsize=32)`
- Duration label cursor fix: `abs(speed - 1.0) < 1e-9` tolerance; `config.get_book_speed()` with fallback
- `path_to_index()` bug fix: walk `self._books` not `self._filtered`
- Library view duration regression fixed in `_resolve_playback`: speed/`dur_disp` adjustments gated on `has_progress=True`
- Hand cursor on main player duration labels + `eventFilter` on library viewport
- Stats panel cover loading: `_inject_active_covers()` fetches `db.get_active_cover_path()` before widget construction
- `refresh_cover()` methods added to `BookDayRow` and `FinishedBookThumb`

---

## 21. `fabulor: || Library progress display after rescanning, delete book` — May 18 2026
**URL:** https://claude.ai/chat/de596e26-de6f-4082-a1e2-f965c639d17c

- Books not showing progress after rescan: two compounding causes — hard deletes destroying rows + scanner sending `0.0` for progress
- Soft-delete: `is_deleted` + `is_excluded` columns; `get_all_books` filters both
- Upsert fixed with `NULLIF` to treat `0.0` as NULL
- Stale `_live_pos`/`_live_dur` cache pruned in `BookModel.set_books()`
- `BookModel._playing_id` tracking to avoid window traversal; redundant double DB fetch removed
- `path_to_index()` walks `self._filtered` not `self._books` — identified (deferred)
- "Remove from library" trash button in book detail panel
- Inline confirmation UI via `theme.py` QSS (`book_detail_confirm_remove`)
- `book_removed` signal wired: close panel, refresh library, unload player if active book removed
- Metadata lock designed (4 `_locked` bool columns, `CASE WHEN` upsert) — deferred
- Folder watching (`watchdog`): identified as right long-term fix, deferred

---

## 20. `fabulor: || chapter drift fixed, cue implemented` — May 17 2026
**URL:** https://claude.ai/chat/ff302263-ba45-4775-9ecf-846d01e0886c

- Root cause: mpv "don't miss a frame" bias undershoots chapter boundaries ~23ms; chapter property observer unreliable at boundaries while paused
- `_CHAPTER_BOUNDARY_EPSILON = 0.35` established as authoritative tolerance across codebase
- Epsilon applied at seek/read time, not write time (invariant)
- Fixes to: `next_chapter`, `previous_chapter`, `seek_async`, `_restore_position`, `_on_time_pos_change`, `_on_chapter_change`, `_update_chapter_label_from_index`
- Teardown crash: libmpv threads outliving Qt cleanup — store ref → clear → `terminate()` → `wait_for_shutdown()`
- CUE file support: single-file M4B/M4A only, validation (FILE stem, first timestamp zero, monotonic, duration bounds), UTF-8 BOM via `utf-8-sig`, global setting in Library tab
- Deferred: undo-after-Prev chapter slider drift; `apply_smart_rewind` and Undo restore paths not audited for boundary drift

---

## 19. `fabulor: || Weekly codebase audit 05.16` — May 16 2026
**URL:** https://claude.ai/chat/6561c4b5-91fe-4000-a6f3-48dda0cc5000

- `CLAUDE.md` Critical Architecture Rules section added
- Five interface classes extracted from `MainWindow.__init__` (147 lines removed)
- `_cover_cache` access encapsulated behind `LibraryPanel.evict_cover` / `get_cached_cover`
- `_build_settings_panel` split into five tab builder methods
- 11-file code review: `app.py`, `library.py`, `db.py`, `player.py`, `library_controller.py`, `book_detail_panel.py`, `theme_manager.py`, `panels.py`, `controls.py`, `cover_panel.py`, `chapter_list.py`
- Pass 6 (API consistency) and Pass 8 (config key audit) completed
- Real bugs found: m/md variable shadowing in VisualsInterface; NameError in `_on_active_cover_changed`
- Deferred: M4B chapter label drift, chapter slider not resetting after Prev/Next, progress slider race on book switch, Timeline tab not updating after metadata edits, CoverThumbnail signal naming

---

## 18. `fabulor: | MP3 seek - blocking behavior` — May 15 2026
**URL:** https://claude.ai/chat/4853eef8-431d-478e-900a-f07e89e56380

- Memory/docs update from SESSION.md, NOTES.md, GEMINI.md
- Playback failures with "wild" audio files: root cause — `load_book()` always passed folder path to `mpv.play()`
- `end-file` observer + `load_failed` signal for silent failure detection
- `_resolve_playlist()`: folder → single file or `concat://` with synthetic ffmetadata chapters
- `instance.chapters_file` must always be assigned unconditionally (stale chapter bleed fix)
- `_on_load_failed` calling `hide_all_panels()` aggressively — regression fixed
- Panel stutter traced to PulseAudio negotiation → gate/ungate pattern + `_mpv_ready` deadzone flag
- MP3 backward seek lag (10-30s, blocking Qt main thread) — diagnosed, not yet solved
- All mpv option approaches tested and failed; MKA remux instant but 23s build time
- Next step: trace full seek path from `ClickSlider` release to `time_pos` set

---

## 17. `fabulor: Distributing a desktop app across platforms` — May 9 2026
**URL:** https://claude.ai/chat/d45c49fc-1ad2-4c5f-acb4-87801e5a9388

- Linux: PyPI, Flatpak/Flathub, AppImage, AUR
- Windows: PyInstaller/Nuitka standalone, GitHub Releases, signed installer, Winget manifest
- Discoverability: GitHub README + demo assets, r/audiobooks, r/linux, r/selfhosted, HN Show HN, MobileRead
- Longer-term: AlternativeTo, Product Hunt, landing page
- Sequencing: GitHub → PyPI → Flathub → Reddit/HN → Windows lags Linux

---

## 16. `fabulor: | Library panel animation stutter during book load` — May 9 2026
**URL:** https://claude.ai/chat/7a9d784a-8160-4592-8edd-0fe6cf38626b

- `_pending_panel_hide` flag: defers `hide_all_panels()` until `_on_file_ready` completes
- `_open_session` calling `_get_current_position()` (libmpv C call) blocked during load — 25-35ms
- Fix: `_close_session` moved to `_on_book_selected_from_library`; `_open_session` removed from `_on_file_ready`
- `restore_position` variance (1ms–92ms) from mpv seek I/O — outside Python's control
- Defer `load_book()` until after panel animation `finished` signal — attempted and reverted (progress-reset race)
- `_file_ready_deferred` flag approach: tested and reverted (broke progress restoration)
- Alternative audio backends evaluated; mpv confirmed as correct choice
- Seek verification threshold: 30s as intent signal

---

## 15. `fabulor: | Weekly codebase audit passes 05.02` — May 9 2026
**URL:** https://claude.ai/chat/f3c421d5-d825-47af-8b58-7f044e88c952

- Pass 7: unguarded mpv property accesses — `_update_ui_sync`, chapter list methods
- Pass 7B: TOCTOU races on user-interaction property writes; `is_initialized` wrapper added to `Player`
- Pass 9: Wayland/platform assumptions — `self.y()`-after-`move()` pattern fixed in `chapter_list.py` and `app.py` undo overlay animation
- Passes 8 and 6 deferred

---

## 14. `fabulor: || library panel model/view migration` — May 9 2026
**URL:** https://claude.ai/chat/3d65d983-e352-4612-ae9e-2d24a76aa86f

- Migration from virtual widget pool to `QAbstractListModel` + `QStyledItemDelegate` + `QListView`
- All 5 view modes delegate-painted including List mode
- Covers load on-demand via viewport-aware binary search on `visualRect`
- Idle preloader: batches of 3, 50ms intervals, starts 4s after launch, pauses on interaction
- `_cover_cache` singleton shared by reference with `BookModel._covers`
- `FONT_SIZES` and `ITEM_DIMENSIONS` dicts as single source of truth
- `_apply_view_mode()` as the only method to set `viewMode` and `gridSize`
- `_close_session()` 25-30ms block fix: DB write moved to daemon thread
- `end-file`/`load_failed` signal added for silent failure detection
- `_resolve_playlist()`: folders → single file or `concat://` URI with synthetic ffmetadata chapters
- All mpv and cover loader signal connections use `Qt.ConnectionType.QueuedConnection`
- Five-pass audit findings and fixes documented in summary

---

## 13. `fabulor: | theme fade animation granularity` — May 10 2026
**URL:** https://claude.ai/chat/ebc36108-594a-409a-b457-1114ed8f1418

- Full-window overlay fade causes panel chrome/covers to dissolve during theme changes
- Stylesheet interpolation: tried and rejected (performance)
- Overlay masking: same user-facing result as snap; artifact risk
- Full per-element `@Property(QColor)` animation: investigated exhaustively; `ClickSlider` already done; `BookDelegate` 15 properties; QSS dynamic-property system incompatible with conversion
- QPalette-based animation: ruled out (50-theme system, 30 semantic keys)
- **Resolution:** `user_initiated` bool param to `_on_theme_changed`; when `False` and settings panel visible → skip overlay, apply instantly
- Lambda bug: `_PANEL_ANIM_GUARD_MS` retry dropped `user_initiated` back to `True`
- `snap_theme_forward()` added to `ThemeManager`, called from `_open_settings_flow`
- Full per-element animation documented in `NOTES.md` as deferred long-term solution
- 1500ms preview duration found as source of apparent sluggishness (not a regression)

---

## 12. `fabulor: | book cover management interface design` — May 12 2026
**URL:** https://claude.ai/chat/e11ec5e7-e062-4859-9a81-6116c60aefed

- Cover management: up to 4 covers per book (1 locked scanner original + 3 user-added)
- Fit modes: Fit, Stretch, Crop, Top (tile mode added then removed)
- Thumbnails left column, larger preview right; single bottom overlay with × / ✓
- 5MB import cap; PNG-to-JPEG conversion on import
- `book_covers` as single source of truth; `get_active_cover_path()` in `db.py`
- Scanner upserts locked slot-0 row into `book_covers`
- `books.cover_path` marked deprecated (not dropped yet)
- New files: `cover_manager.py`, `cover_panel.py`
- `active_cover_changed` signal wiring in `app.py`
- `LibraryPanel.refresh_book_cover()` evicts cache by `book.id`, triggers async reload
- `SmoothTransformation` scaling once at load time in `CoverThumbnail._load_pixmap`
- Fit mode changes emit `active_cover_changed` when selected cover is active

---

## 11. `fabulor: | book details, stats, metadata` — Apr 27 2026
**URL:** https://claude.ai/chat/9c0ba03b-67d2-4dd4-9c60-a747bdc38de3

- Close button: circular ✕ (28×28, border-radius 14px), top-right in header
- `update_book_metadata()`, `get_book_tags()`, `add_book_tag()`, `remove_book_tag()`, `get_tag_suggestions()` DB methods
- `book_tags` table: `(book_path, tag)` UNIQUE, 5-tag limit, 30-char max
- Tag suggestions: excludes tags already on current book, sources from all others
- Freeform chips with library-wide autocomplete (no presets)
- `FlowLayout` extracted to `ui/flow_layout.py`
- `_get_conn` missing `conn.commit()` bug fixed
- `load_book` reading stale `book_data` before enrichment — fixed with `'duration' not in book_data` guard
- Year stored as INTEGER; `int(year)` guard with `isdigit()` check
- Stats tab cover loading sluggishness deferred (sync `pixmap.load()` in `BookDayRow.__init__`)

---

## 10. `fabulor: || stats, session recording design, metadata` — Apr 29 2026
**URL:** https://claude.ai/chat/50ac77b3-30b2-444c-b8e2-022e0a68a09d

- `listening_sessions` and `book_events` DB schema finalised
- Git incident resolved: stash pop merge conflicts across 5 files
- `_eof` not resetting in `load_book()` → Restart stuck bug fix
- `_restore_position` reading stale DB progress after restart → unwanted smart rewind fix
- Full session recording: `_open_session`, `_close_session`, `_on_seek_credit_earned`, 15s seek credit timer
- Stats query layer: 5 DB methods using Julian day math, configurable day-start hour offset
- `StatsPanel` extracted to `ui/stats_panel.py`, wired into `PanelManager`
- `BarChartWidget`, `BookDayRow`, `FinishedBookThumb` widgets built
- `BookDetailPanel` in `ui/book_detail_panel.py` with Stats and Metadata tabs
- `ThemeManager` converted to `QObject` to emit `theme_applied` signal
- Assets organised under `src/fabulor/assets/` with `get_asset_path()`

---

## 9. `fabulor: Performance and refactoring analysis` — Apr 24 2026
**URL:** https://claude.ai/chat/88768f6a-0bcb-4ba8-b6e2-f401bccfa64c

- Haiku code review filtered: DB indexes, SQL injection fix in `get_all_books`, path concat fix
- `setUpdatesEnabled` wrapping for mode switches
- `_get_or_create_label` helper with guarded `installEventFilter`
- Five typed interface classes replacing `SimpleNamespace`
- Signal/slot replacing dynamic method binding in `settings_controller.py`
- `Book` dataclass rolled out to all call sites (6 passes needed)
- Diff-based library refresh (added/removed/changed sets)
- Chapter hints moved from `_update_ui_sync` hot path to `file_loaded` callback
- Stats panel schema: `listening_sessions`, `book_events`, `finished_at` on `books`
- Right-click context menu on BookItem — designed, deferred to after model/view rewrite

---

## 8. `fabulor: library view mode performance, diary` — Apr 24 2026
**URL:** https://claude.ai/chat/3ff7fbee-f286-43e2-800f-6e87d1838aaf

- DB fetch ~0.01s; widget construction 3-5s across 316 BookItems — root cause confirmed
- Virtual scrolling with ~15-20 recycled BookItem pool — implemented by Gemini in one pass
- Thumbnail sharpness: 2× size, `SmoothTransformation`, `setDevicePixelRatio(dpr)`
- Smart aspect-ratio scaling: crop when ratios within 8%, letterbox otherwise
- Square art view mode with center-crop
- Year sorting: first 4-digit regex, prefer `originaldate`, store as nullable int, nulls last
- Recent (Last Played) filters to played books only
- `DEVLOG.md` suggestion for future projects

---

## 7. `fabulor: || Progress bar width not updating, library performance` — Apr 23 2026
**URL:** https://claude.ai/chat/c2c66108-3e68-4457-b465-e1d61c3eda75

- Progress bar background color not rendering in grid view modes
- QSS scoped stylesheet conflicts; theme color resolution always reading first theme
- `LibraryPanel.update_progress_bar_theme()` wiring
- 6946-widget tree causing 1.5s `setStyleSheet` cost
- Stylesheet refactored into per-component functions
- Virtual scrolling pool of 30 reusable `BookItem` widgets introduced
- `_apply_stylesheets` applies per-component rather than on main window

---

## 6. `Book display layout and performance optimization` — Apr 21 2026
**URL:** https://claude.ai/chat/8356e030-f832-4c01-9ed7-116a33fedd2f

- Hover overlay system for 2-per-row and 3-per-row library grid
- Gradient overlay covering bottom 20-30% of cover
- No-progress state: total duration left-aligned only
- With-progress state: elapsed left / remaining right, progress bar + percentage
- Minus sign on remaining time
- Hit-test bug: `mapToGlobal` failure causing click-through to library dismiss
- Two-overlay rendering bug from child widgets inheriting gradient stylesheet

---

## 5. `fabulor: refactoring MainWindow` — Apr 17 2026
**URL:** https://claude.ai/chat/58c54083-ef9a-4a52-8f1a-365ad6554eba

- Rejected CoPilot's 8-9 file extraction plan as over-fragmented
- `LibraryController` extraction with `AppInterface` / `BrowserInterface`
- `SettingsController` extraction with `settings_ui` interface wrapper
- `_update_ui_sync` decomposed into 5 private helpers in-place
- `SimpleNamespace` vs typed interface classes — debt acknowledged
- Git workflow: local vs remote branch deletion

---

## 4. `fabulor: Statistics pages` — Apr 19 2026
**URL:** https://claude.ai/chat/13047ca4-402f-45d7-8f8b-435052a9ec65

- "Furthest position reached" model for progress tracking
- Seeking forward doesn't count as progress without listening through it (deferred from v1)
- "Longest listening stretch" as a lightweight stat
- Manual "mark as finished" — no automatic completion detection
- Stats bifurcated: those needing finished flag vs pure playback time
- Tapping a bar on general stats → navigates to per-book page filtered by date
- Tabs and pagination needed given small page/font constraints

---

## 3. `fabulor: | Speed panel/themes/audio` — Apr 20 2026
**URL:** https://claude.ai/chat/2c99bc0e-03c6-474e-b133-56b2061b66d8

- Theme hover preview performance: 80ms debounce, reusable overlay/animation objects, scoped stylesheet, `_stylesheet_cache`
- `_is_hover_active` flag to unblock confirmed activations after hovering same theme
- `_any_panel_animating()` guard to defer theme changes during slide animations
- Bin-packed theme grid layout, bold-metric fixed widths
- `ThemeManager.get_packed_themes()` lazy caching
- Audio processing via mpv: `af` string assignment, PipeWire remixing blocks balance/pan filters
- Voice boost EQ via lavfi `equalizer` — confirmed working
- Chapter list scrollbar initial styling fix
- `NOTES.md` / `ARCHITECTURE.md` introduced for tracking debt

---

## 2. `fabulor: || questions` — Apr 20 2026
**URL:** https://claude.ai/chat/63459d38-2012-42dc-98dd-0fecfd33e1de

- High-level status review: themes, panels, scanner, library view modes, smart rewind, undo seek
- app.py grew to 2267 lines — component refactoring plan introduced
- SQLite via platformdirs for cross-platform storage
- Two-layer progress persistence (config = live, DB = lazy sync)
- `setObjectName` as QSS selectors for library theming
- BookItem dimensions from panel width at render time
- `entr` for auto-restart during dev
- Audiobook UX principles documented (no persistent chapter list, portrait grid, fixed window, mini-player)

---

## 1. `fabulor: bugs` — Apr 14 2026
**URL:** https://claude.ai/chat/2952dc64-5aa6-4649-b174-04466e05dde0

- Library sort: `_sort_items_in_place()`, type-aware keys, None-to-bottom tuple trick
- EOF/restart 30-hour saga: `keep_open='always'` fix, `_eof` flag, Layer 2 position-based EOF fallback
- `eof_reached` property bug (was reading mpv attribute, not `self._eof`)
- `config.get_last_position()` None guard
- Chapter `IndexError` in `_on_item_clicked`
- Undo button animation disconnect warnings — `_undo_slide_in_connected` flags
- DB upsert bug: missing `progress` binding

---

*Index updated Jun 4 2026. Newest entry at top.*
