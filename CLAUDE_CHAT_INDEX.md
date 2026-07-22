# Fabulor — Project Chat Index

Chronological index of architecture/design chat windows (oldest → newest).  
VS Code / Claude Code implementation windows are not included.  
Use this file to locate which window discussed a given topic before pulling it up for context.

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

## 5. `fabulor: refactoring MainWindow` — Apr 17 2026
**URL:** https://claude.ai/chat/58c54083-ef9a-4a52-8f1a-365ad6554eba

- Rejected CoPilot's 8-9 file extraction plan as over-fragmented
- `LibraryController` extraction with `AppInterface` / `BrowserInterface`
- `SettingsController` extraction with `settings_ui` interface wrapper
- `_update_ui_sync` decomposed into 5 private helpers in-place
- `SimpleNamespace` vs typed interface classes — debt acknowledged
- Git workflow: local vs remote branch deletion

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

## 13. `fabulor: | theme fade animation granularity` — May 10 2026
**URL:** https://claude.ai/chat/ebc36108-594a-409a-b457-1114ed8f1418

- Full-window overlay fade causes panel chrome/covers to dissolve during theme changes
- Stylesheet interpolation: tried and rejected (performance)
- Overlay masking: same user-facing result as snap; artifact risk
- Full per-element `@Property(QColor)` animation: investigated exhaustively; QSS dynamic-property system incompatible with conversion
- QPalette-based animation: ruled out (50-theme system, 30 semantic keys)
- **Resolution:** `user_initiated` bool param to `_on_theme_changed`; when `False` and settings panel visible → skip overlay, apply instantly
- Lambda bug: `_PANEL_ANIM_GUARD_MS` retry dropped `user_initiated` back to `True`
- `snap_theme_forward()` added to `ThemeManager`, called from `_open_settings_flow`
- Full per-element animation documented in `NOTES.md` as deferred long-term solution

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
- All mpv and cover loader signal connections use `Qt.ConnectionType.QueuedConnection`
- Five-pass audit findings and fixes

---

## 15. `fabulor: | Weekly codebase audit passes 05.02` — May 9 2026
**URL:** https://claude.ai/chat/f3c421d5-d825-47af-8b58-7f044e88c952

- Pass 7: unguarded mpv property accesses — `_update_ui_sync`, chapter list methods
- Pass 7B: TOCTOU races on user-interaction property writes; `is_initialized` wrapper added to `Player`
- Pass 9: Wayland/platform assumptions — `self.y()`-after-`move()` pattern fixed
- Passes 8 and 6 deferred

---

## 16. `fabulor: | Library panel animation stutter during book load` — May 9 2026
**URL:** https://claude.ai/chat/7a9d784a-8160-4592-8edd-0fe6cf38626b

- `_pending_panel_hide` flag: defers `hide_all_panels()` until `_on_file_ready` completes
- `_open_session` calling `_get_current_position()` blocked mid-load — 25-35ms
- Fix: `_close_session` moved to `_on_book_selected_from_library`; `_open_session` removed from `_on_file_ready`
- Defer `load_book()` until after panel animation `finished` — attempted and reverted (progress-reset race)
- Alternative audio backends evaluated; mpv confirmed as correct choice
- Seek verification threshold: 30s as intent signal

---

## 17. `fabulor: Distributing a desktop app across platforms` — May 9 2026
**URL:** https://claude.ai/chat/d45c49fc-1ad2-4c5f-acb4-87801e5a9388

- Linux: PyPI, Flatpak/Flathub, AppImage, AUR
- Windows: PyInstaller/Nuitka standalone, GitHub Releases, signed installer, Winget manifest
- Discoverability: GitHub README + demo assets, r/audiobooks, r/linux, r/selfhosted, HN Show HN, MobileRead
- Sequencing: GitHub → PyPI → Flathub → Reddit/HN → Windows lags Linux

---

## 18. `fabulor: | MP3 seek - blocking behavior` — May 15 2026
**URL:** https://claude.ai/chat/4853eef8-431d-478e-900a-f07e89e56380

- Playback failures with "wild" audio files: root cause — `load_book()` always passed folder path to `mpv.play()`
- `end-file` observer + `load_failed` signal for silent failure detection
- `_resolve_playlist()`: folder → single file or `concat://` with synthetic ffmetadata chapters
- `instance.chapters_file` must always be assigned unconditionally (stale chapter bleed fix)
- Panel stutter traced to PulseAudio negotiation → gate/ungate pattern + `_mpv_ready` deadzone flag
- MP3 backward seek lag (10-30s, blocking Qt main thread) — diagnosed, not yet solved
- All mpv option approaches tested and failed; MKA remux instant but 23s build time

---

## 19. `fabulor: || Weekly codebase audit 05.16` — May 16 2026
**URL:** https://claude.ai/chat/6561c4b5-91fe-4000-a6f3-48dda0cc5000

- `CLAUDE.md` Critical Architecture Rules section added; "constraints are load-bearing until proven otherwise" principle
- Five interface classes extracted from `MainWindow.__init__` (147 lines removed)
- `_cover_cache` access encapsulated behind `LibraryPanel.evict_cover` / `get_cached_cover`
- `_build_settings_panel` split into five tab builder methods
- 11-file code review across core modules
- Real bugs found: m/md variable shadowing in VisualsInterface; NameError in `_on_active_cover_changed`
- Deferred: M4B chapter label drift, chapter slider not resetting after Prev/Next, progress slider race, Timeline tab not updating after metadata edits

---

## 20. `fabulor: || chapter drift fixed, cue implemented` — May 17 2026
**URL:** https://claude.ai/chat/ff302263-ba45-4775-9ecf-846d01e0886c

- Root cause: mpv undershoots chapter boundaries ~23ms; chapter property observer unreliable at boundaries while paused
- `_CHAPTER_BOUNDARY_EPSILON = 0.35` established as authoritative tolerance across codebase
- Teardown crash: `terminate()` → `wait_for_shutdown()` fix; store ref → clear → terminate
- CUE file support: single-file M4B/M4A only, validation, UTF-8 BOM via `utf-8-sig`, global Library tab setting
- Fixes to: `next_chapter`, `previous_chapter`, `seek_async`, `_restore_position`, `_on_time_pos_change`, `_on_chapter_change`, `_update_chapter_label_from_index`

---

## 21. `fabulor: || Library progress display after rescanning, delete book` — May 18 2026
**URL:** https://claude.ai/chat/de596e26-de6f-4082-a1e2-f965c639d17c

- Books not showing progress after rescan: hard deletes destroying rows + scanner sending `0.0`
- Soft-delete: `is_deleted` + `is_excluded` columns; upsert fixed with `NULLIF`
- Stale `_live_pos`/`_live_dur` cache pruned in `BookModel.set_books()`
- `path_to_index()` walks `self._filtered` not `self._books` — identified (deferred)
- "Remove from library" trash button with inline confirmation UI
- `book_removed` signal wired: close panel, refresh library, unload player if active book removed
- Metadata lock designed (4 `_locked` bool columns) — deferred

---

## 22. `fabulor: | metadata lock, Stats covers, duration fix` — May 20 2026
**URL:** https://claude.ai/chat/b7c17ffa-5c9c-4981-adcf-c3c45034e30a

- Metadata lock: 4 bool lock columns; `CASE WHEN books.X_locked` in both upserts (invariant: must stay in sync)
- `_meta_action_btn` driven by `_MetaActionState` enum: HIDDEN, DIRTY, LOCKED, UNLOCKED
- `active_cover_changed` changed to `Signal(str, str)` emitting `(book_path, cover_path)`
- Duration label cursor fix: `abs(speed - 1.0) < 1e-9` tolerance
- `path_to_index()` bug fixed: walk `self._books` not `self._filtered`
- Library view duration regression fixed: speed/`dur_disp` gated on `has_progress=True`
- Stats panel cover loading: `_inject_active_covers()` fetches `db.get_active_cover_path()` before widget construction

---

## 23. `fabulor: | SVG transport control icons for audiobook player` — May 21 2026
**URL:** https://claude.ai/chat/0e3dadbb-9864-47af-b6d4-29d2b4d89c8d

- Three-tier button color theme keys: `button_play`, `button_skip`, `button_chapter` → fallback `button_text`
- Skip icon variants: 1/2/3 chevrons for 5s / 10s+15s / 30s; `_update_skip_icons()` on init and settings change
- PySide6 SVG renderer does NOT honour `currentColor` — `_load_svg_icon()` must target inline `style=` CSS
- Restart icon: arc geometry failed; external SVG adopted, viewBox manipulation for sizing
- `icon_utils.py` created as shared SVG icon loading utility

---

## 24. `fabulor: | Archived book detail panel read-only mode` — May 22 2026
**URL:** https://claude.ai/chat/cbfc4039-6616-4d87-8ea4-6def92ba143a

- Archived books: metadata/cover/tag editing kept; grayscale cover only visual signal; trash button hidden
- `_is_archived` flag must be set BEFORE the cover block that reads it in `load_book()` (ordering bug fixed)
- Tag manager refresh chain wired across three triggers: trash, scan completion, active cover change
- `refresh_tag_manager()` and `refresh_stats()` wrappers added to `AppInterface`
- `get_book_dict()` added to `db.py` returning raw dict from `SELECT *`
- Mark-finished: write to `book_events`, reset progress, near trash button, non-reversible

---

## 25. `fabulor: ||| Weekly codebase audit 05.22, tags` — May 26 2026
**URL:** https://claude.ai/chat/6ca3801f-78b7-4e1d-99b3-ef00f7de8738

- `Player.terminate()` regression: `wait_for_shutdown()` silently dropped — fixed immediately
- `TagManagerWidget` promoted to standalone sidebar panel (`TAGS` entry)
- Tag color feature: `tags` table, `TAG_COLORS` palette (9 colors), colored dots in list/detail
- `QStackedLayout` reserved row (32px) for color picker / delete confirmation / empty — no layout shift
- Action button cycles: trash → save (dirty) → check (post-save 1.5s)
- Delete confirmation: 7s timer, grid lock, cancel-on-outside-click
- `_update_list_dot()` for targeted list row update without full grid rebuild
- `_set_tag_color` must never call `refresh()` (invariant established)
- 320ms `QTimer.singleShot` after `hide_all_panels` documented as debt

---

## 26. `fabulor: ||| Text right click context menu, mouse pointer states, library search persistence, smart rewind UI, DB migration, stats inflation, MP3 EOF crash fixed` — May 29 2026
**URL:** https://claude.ai/chat/e342f88f-a075-4daa-960b-63d28fbf4e55

- Custom `ContextIconMenu` widget replacing system context menus
- Library search filter persistence: master On/Off toggle + per-type sub-toggles (Tags/Text/Year)
- Right-click-to-clear on library search field
- Chapter wheel seek changed from fixed skip to 5% of chapter duration (min 10s)
- MP3 backward seek: `_mp3_stop_and_load` via stop-and-reopen with `start=T` (distance >60s threshold)
- `_cached_time_pos` must be LOCAL position in VT (not global — critical bug fix)
- EOF crash: 2s buffer before file end in all `seek_async` paths
- DB migration: `listening_sessions`, `book_events`, `book_tags` from `book_path` FK to `book_id` FK
- Stats inflation bug: `LEFT JOIN book_events` against `listening_sessions` creates cartesian product — fixed with scalar subquery for `is_finished`
- `SessionRecorder` extraction designed (Option Y: behavior-exposing methods)
- P2-C, P6-A, P6-D, P6-E documented as deferred debt

---

## 27. `fabulor: ||| Weekly audit 05.29, app.py audit, SessionRecorder, theme fade ghost fix, label freeze, sleep in sessions, weighted rotation` — May 31 2026
**URL:** https://claude.ai/chat/6517044d-d2b4-463b-a304-5e3cd6d01fc5

- Six-pass audit of `app.py`; dead imports removed, uninitialized state fixed
- `SessionRecorder` extracted to `session_recorder.py` with 30s JSON checkpoint
- Invariant #1 violation fixed: `self.player.chapter` direct read → epsilon walk
- `SessionRecorder.open()` bug: dangling `_post_seek_pending_position` → `0.0→0.0` records
- Theme fade ghost fix: `_do_fade_with_slider_animation`; `QPropertyAnimation` on slider color properties; labels frozen during fade
- Weighted perceptual theme rotation: distance metric, inverse-distance weighting exponent 1.0
- T-key theme shortcut: fires immediately, 2s cooldown, one pending max
- Sleep timer: raw float comparison fix (was firing ~1s early)
- `_format_duration`: floor → round with carry guard

---

## 28. `fabulor: || MP3 seek - multiple files` — Jun 1 2026
**URL:** https://claude.ai/chat/bea0b470-409c-4ba2-a650-3c2f790e6d68

- Virtual timeline (VT) architecture for multi-file MP3 folders; `book_files` DB table
- Signal separation: `book_ready` (once per book) vs `file_switched` (per VT load) — breaks infinite load loop
- `keep_open='always'`: natural file advancement via `_advance_or_finish` from `_on_pause_test`, gated by `_is_vt_file_switch`
- VT-aware chapter navigation walks `_chapter_list` by global `time_pos`
- `_cached_time_pos` / `_cached_duration` cleared in `load_book` reset block
- VT cross-file seek: `_seek_target` stored in GLOBAL coords; mpv command stays LOCAL (coordinate-space freeze fix)
- `handle_forward`/`handle_rewind`: `reload_pending AND old_pos is None` guard
- EOF crash: 2s buffer before file end in all `seek_async` paths

---

## 29. `fabulor: || state machine, empty states, carousel, path list, scanner UX` — Jun 3 2026
**URL:** https://claude.ai/chat/f6c5920a-e572-4fa2-a571-a0e25009de55

- `COVER_AREA_HEIGHT=280` constant; `setFixedHeight(280)` + `AlignCenter` on `cover_art_label` (invariant — never revert to label height)
- Chrome restore failure after empty→add library→load book: `apply_current_state()` added in deferred `singleShot(0)`
- `apply_current_state()` extracted as public method on `LibraryController` — sole compute+apply entry (invariant)
- `_check_library_status` delegates to `apply_current_state()` then feeds state to `handle_background_tasks`

---

## 30. `fabulor: | Carousel stripe full-width bleed issue` — Jun 4 2026
**URL:** https://claude.ai/chat/899b605a-fcfa-4562-bd8c-2ab040afaadd

- Full-width carousel stripe: parented to `content_container`, `carousel_holder.mapTo(content_container)` for y, `stackUnder(visual_area)`
- `visual_area` background suppressed via `get_player_stylesheet(suppress_bg_image=True)` — `setAutoFillBackground(False)` alone insufficient for QSS `background-image`
- `_set_bg_suppressed` as single authority coupling `setAutoFillBackground` and stylesheet regeneration
- Carousel color keys fixed: `carousel_stripe` → fill, `carousel_bg` → fallback `bg_main`
- `set_stripe_color` always recomputes line color from current fill; `_LINE_LIGHTNESS_SHIFT` constant
- `bg_image` themes (Overlook, Winterfell, Pyke etc.) no longer paint over prompts/carousel/quotes
- Sidebar phantom right-click after folder dialog dismissed: `QElapsedTimer` 500ms guard

---

## 31. `fabulor: | Stats panel carousel placeholder flashing bug, DayWeekMonth navigation` — Jun 4–5 2026
**URL:** https://claude.ai/chat/2303cfb1-3f7d-44ff-8c74-85fde0d763b1

- Placeholder flash root causes: placeholder-first construction before cache check; `_on_cover_loaded` not writing to `_cover_cache`; `os.path.exists` gating causing custom covers to always miss
- `setParent(None)` replaces `deleteLater()` for synchronous widget removal
- `setMinimumWidth(n*47 + (n-1)*4)` computed after population (layout bug fix)
- `_current_ids` guard (set equality) skips rebuild when period book IDs unchanged
- Mouse wheel navigation on date header row (Day/Week/Month tabs)
- Step acceleration for Day tab: 1/2/3/4/7 steps at ≤50/100/200/300/300+ periods
- Fixed step 1 for Week/Month tabs
- Options toggle controls acceleration only (not wheel nav itself); toggle is a button not a checkbox

---

## 32. `fabulor: ||| Code refactoring safety assessment` — Jun 6–7 2026
**URL:** https://claude.ai/chat/9489ea60-ee07-4e81-8c1e-5133068f689b

- 19 `_build_*` methods extracted from `app.py` into `ui/main_window_builders.py` (~946 lines removed)
- `BookSwitchState` state machine designed (IDLE/LOADING/RESTORING phases, consume-once `take_progress_target()`/`take_chapter_target()`)
- Chapterless-to-chapterless background flash: `polish()` during `setStyleSheet` overrides color properties; fix: lightweight re-assert in `_set_bg_suppressed`
- Chapter slider ghost during theme fades: unconditional `_set_chapter_ui_active(False)` before book load removed
- Short chapter position drift: `_CHAPTER_BOUNDARY_EPSILON` applied to `c_elapsed` too (not just seek target)
- Chapter label flashing to index 0: `flow_pending_chapter` as second gate in `_update_chapter_label_from_index`
- Stale time labels on book removal: cleared in `_on_book_removed()`
- Invariant: never call `_set_chapter_ui_active(False)` unconditionally before a book load

---

## 33. `fabulor: ||| Flow animation stuttering and race condition solutions` — Jun 7 2026
**URL:** https://claude.ai/chat/f8ed5cf8-945a-49ed-a8c1-145842676016

- Seek-settle deferral system (`BookSwitchState`, `_on_seek_settled()`, `seek_settled` signal) — attempted and reverted (slider desync, broken undo, notch reanimation)
- Three fixes that landed: (1) suspend `ui_timer` during animation window, resume via `_flow_anim.finished`; (2) `_update_chapter_label_from_index()` at end of `_on_file_loaded_populate_chapters()`; (3) `ChapterItemDelegate` replacing `QWidget`-per-row to eliminate `populate()` bottleneck
- Startup animation stutter: event-loop contention during busy startup — accepted limitation, not a fixable race
- `refactor/extract-mainwindow-builders` branch merged to main

---

## 34. `fabulor: || Code audit results assessment 06.12` — Jun 12–13 2026
**URL:** https://claude.ai/chat/fe849741-e0f3-4074-8f18-eb02af773204

- Audit Passes 5-8 completed; `DEBT_INVENTORY.md` created
- Un-archive color restoration fixed in `book_detail_panel.py`
- `finished ⟹ listened` made true across all surfaces (day-start-hour adjustment)
- Streak-grid refresh bug root cause: `"Hour"` vs `"Timeline"` string literal mismatch in `refresh_current_tab()` dispatch table
- Stats panel lazy-refresh design confirmed: Timeline uses dirty-flag/cache (364-day query); Day/Week/Month/Overall re-query intentionally
- Standing principle: "guard is probably correct — find the narrower fix before considering guard removal"
- Agents removing guards they don't understand flagged as recurring risk
- `/review/Review_YYMMDD_N.md` audit convention established, committed to git with commit hash in header
- `apply_current_state()` confirmed as sole compute+apply entry (invariant re-verified)

---

## 35. `fabulor: | Red team review: short-chapter "sliver"` — Jun 16 2026
**URL:** https://claude.ai/chat/a414f999-ce8e-4fbb-928f-a68be7cc7745

- Paused-state slider clamp: `_CHAPTER_SLIVER_EPS` constant; pause-gate race confirmed structurally impossible on that code path
- Transient UI spike on embedded M4B chapter navigation: `_chapter_list is None` used as implicit sentinel → inconsistent state during mpv async settle
- `_is_embedded_m4b` flag introduced to replace sentinel pattern; grep audit mandatory before implementation
- `_set_chapter_ui_active(bool)` must reapply after every theme change (repolish overrides stylesheet)
- Division-by-zero in production `setValue` call if cache fix regresses — flagged

---

## 36. `fabulor: | Chapter seek epsilon timing issue` — Jun 16 2026
**URL:** https://claude.ai/chat/637eac7b-32cd-4742-a3b7-f39a7c54d730

- Chapter UI bounce: single non-physical backward `time_pos` sample (0.56–0.87s stale jump) after clean settle
- Fix: six-line guard in `time_pos` callback rejecting backward samples beyond 0.3s threshold
- Guard uses global-space comparison (not local) to avoid cascade-freeze on VT file boundaries
- `is_seeking` stuck flag and position drift/creep from save/restore feedback loop also addressed
- Elaborate multi-mandate fixes (agreement gates, QTimer fallbacks, monotonicity) rendered unnecessary by instrumentation — measure first principle reinforced

---

## 37. `fabulor: | Red-team review of widget layout plan` — Jun 20 2026
**URL:** https://claude.ai/chat/c2cb9a1c-0ab9-4d1f-be9e-8861228a15e3

- TasselOverlay: decorative animated tassel on Stats Timeline tab (cord, bulb, physics, fringe gacha)
- Seven pre-implementation failure points identified: geometry offset, occlusion/click-stealing, `hideEvent` propagation, kick-clear gating, mid-decay kick resets, repaint over grid transitions, bezier behavior at peak
- Implementation prompt: geometry, data model, timer logic, paint, lifecycle, activation kicks, theme color integration
- Click pass-through downgraded from required to optional; hit-rect must derive from same constants as `_bg` rect in `paintEvent`
- Tassel rides with tab during slide animation — no counter-animation

---

## 38. `Game tracking apps and websites` (Fabulor mini-player discussion) — Jun 22 2026
**URL:** https://claude.ai/chat/f7adb638-f018-4297-94b1-79d2627f964e

- Folder watch and rating system: both ditched
- Mini-player: Claude Code friction audit revealed chapter progress routes through most tripwire-dense subsystem; decision deferred, leaning cut
- VT progress under 50% not persisting and resetting to 0% — new bug identified
- In-game photography platform idea evaluated and parked (2-3 year net-negative bet)
- `audio_client_name='fabulor'` in MPV constructor: makes PipeWire/PulseAudio stream-restore key stable; do not remove (invariant added later)

---

## 39. `OpenSUSE app audio volume resets automatically` — Jun 25 2026
**URL:** https://claude.ai/chat/895b130a-cb84-40dd-a89b-a1b6697449bc

- Volume reset to 5% on book load: WirePlumber `module-stream-restore` saving poisoned low-volume entry
- Fix: reset stream-restore DB + WirePlumber rule in `~/.config/wireplumber/wireplumber.conf.d/`
- `audio_client_name='fabulor'` in mpv init makes stream-restore key stable (do not remove)
- QtWidgets vs QML discussion: QML underrepresented in agent training data — reliable factor in choosing QtWidgets

---

## 40. `fabulor: | Building a configurable keyboard shortcut system` — Jul 2026
**URL:** https://claude.ai/chat/974090d3-1403-49b6-b3e1-e67ccc5bbb8e

- `shortcuts.py`: `Action` enum, `DEFAULT_BINDINGS` table, declarative `GuardKind` (NONE / COOLDOWN_COALESCE / COOLDOWN_DROP), `ShortcutDispatcher`
- `MainWindow.keyPressEvent` reduced to one-line delegate
- `L` key: no-op if library or any full panel already open, or empty-library state
- `PanelManager.is_any_full_panel_visible()` extracted as single source of truth for panel list
- Panel-overlap mutual exclusion: `is_overlay_open_or_committed()` gate on every overlay-open path
- `PanelManager.dismiss_sidebar()` added (single-purpose caller)
- Autorepeat filtering is per-binding; ChapterList `keyPressEvent` intentionally left outside the system
- `KEYBINDINGS.md` created with full binding inventory + planned/tentative keys section
- No `QShortcut`/`QAction` anywhere — all hand-rolled (confirmed)
- Branch `feat/shortcuts-module`, 60/60 tests passing

---

## 41. `fabulor: || Implementing clickable filters for library metadata` — Jul 2026
**URL:** https://claude.ai/chat/d0d073ec-2c33-447a-9b12-7b85a43e2956

- Click-to-filter for author/narrator/year in library grid (1-per-row, 2-per-row)
- `_explicit_filter_text` tracks last user-set value; click-originated filters are transient overrides
- Toggle-off: clicking active filter reverts to `_explicit_filter_text` (not `""`)
- Multi-value segmentation: delimiter splitting on `,` `;` `" and "` `" & "`; delimiters are dead zones
- Segment hit-testing tracks live scroll offsets in marquee animation
- No hover decoration beyond cursor shape (underline built to prove hit-test, then removed)
- Right-click-to-clear on search field: established gesture, must not be shadowed
- List-mode click-to-filter scoped as follow-on; `_list_author_segment_at` path isolated
- List-mode title measurement bug: was using `option.fontMetrics` (11pt generic) vs actual draw fonts (14px bold / 13px regular); fixed with per-field `QFontMetrics`
- Author→time spacing: three approaches failed; root cause — rect-boundary padding cannot produce constant glyph-to-glyph gap under opposite-alignment fields; deferred

---

## 42. `fabulor: | Improving book cover text layout` — Jul 2026
**URL:** https://claude.ai/chat/b3d461a1-a1d8-4aa0-a2bf-700f6fbb1cd9

- `cover_placeholder.py` extracted: `CoverPlaceholder` in `ui/cover_placeholder.py`; pure refactor, no behavioral changes
- Two duplicate "no cover art" branches collapsed into `_show_no_cover_state()` helper
- Placeholder logo debt noted: also appears in tags/stats/library panels — follow-up to extract shared `logo_icon.py` primitive, NOT merge into `cover_placeholder.py`
- Layout decisions: author on one line (truncate); title on 1-2 lines (two discrete fixed states)
- Font sizes: discrete steps, not continuous shrink-to-fit
- Layout results cached per book keyed by version stamp, computed lazily on first show
- Versa font (full-uppercase) preferred over Fjalla One; Python-side `.upper()` before measurement
- Injectable `QFontMetrics` for font-swapping dev testing; `FABULOR_LOG_LEVEL`-style env var toggle

---

## 43. `fabulor: || Implementing a logging system` — Jul 2026
**URL:** https://claude.ai/chat/36ee4c68-05de-4b8b-9dc3-4c2f5f4d88e3

- `logger_setup.py`: `RotatingFileHandler` (2MB, 3 backups) to `platformdirs.user_log_dir("fabulor")/fabulor.log`
- Silent at WARNING by default; verbose at `FABULOR_LOG_LEVEL=DEBUG`
- `fabulorentr` shell function: sets DEBUG + `entr` file-watching
- Instrumentation for chapter oscillation: `_on_time_pos_change`, `seek_async`, chapter navigation methods, `_sync_chapter_ui`
- Instrumentation for sidebar bleed-through: `_toggle_sidebar`, mask-build blocks, `raise_()` sites, `_apply_stylesheets` sidebar branch; `time.perf_counter()` for microsecond resolution
- Sidebar bleed-through root cause caught live: `_on_sidebar_closed_for_panel` dispatched panel-open while `sidebar_expanded` still True — re-arm guard added
- `FABULOR_LOG_LEVEL=DEBUG` to remain active until chapter oscillation and sidebar bugs fully resolved

---

## 44. `fabulor: || Library path rescanning and removed books behavior` — Jul 2026
**URL:** https://claude.ai/chat/d442bd00-1572-4ae9-a24a-88de938b0150

- `_on_scan_finished` now checks if currently-loaded book was flagged missing and calls `on_book_removed()` (drops to no-book state)
- `is_missing` and `is_excluded` flag split: `is_missing` self-heals on upsert (scanner-detected), `is_excluded` sticky (user-initiated)
- Excluded Books popup: inline collapsible section at bottom of Library settings tab; invisible at count 0; hover-reveal eye icon restores on click
- Naming Pattern setting in Library tab identified as dead code — to be removed
- Library tab item spacing inconsistent with Look/Audio tabs by ~10px — to be normalised
- `get_non_deleted_book_paths_under` (fences `is_deleted=0` only, not `is_excluded`/`is_missing`) covers "exclude first, then file disappears" path

---

## 45. `fabulor: || Weekly code review plan for Claude Code - Jul 3` — Jul 2026
**URL:** https://claude.ai/chat/e8abbace-6111-46d4-aa02-5e55be69fa74

- Scan teardown predicate bug: `_on_scan_finished` checked `is_book_excluded` instead of `is_book_missing` after flag split — fixed to check both (`is_missing OR is_excluded`)
- M4B continues playing on exclusion (intentional); VT stops (intentional — streaming broken files would crash)
- Invariant sweep: 17/17 PASS; two `setStyleSheet` calls outside `_apply_stylesheets` confirmed as fan-outs, not competing entries
- Library slide-in jank root cause: `_get_sized_cover`/`_lanczos_scale` running synchronously in `paint()` on main thread during slide-settle window
- `_sized_cover_cache` is load-bearing (invariant): removing it silently regresses to bilinear; scanner-side fix alone produces zero visible improvement
- Idle preloader resurrected: `CoverLoaderWorker` sized-mode variant; `panel_manager.is_any_panel_animating()` gate; armed after `_finish_startup` with 5s idle; batch size 4
- Scroll-position preservation on view-mode switch: `_first_visible_row()` + `scrollTo(index, PositionAtTop)` inside `_after_reset` deferral
- Theme hover perf: skip hidden-panel restyle when `hover=True`; `_load_svg_pixmap` LRU cache; 60ms debounce

---

## 46. `fabulor: || Pre-implementation plan critique` — Jul 2026
**URL:** https://claude.ai/chat/9f2b6261-95a2-47bb-8940-01f96cd411da

- Cover quality improvement post-mortem: 320×480 LANCZOS JPEG thumbnails; `_sized_cover_cache`/`_get_sized_cover` pipeline confirmed load-bearing
- `DEBT_INVENTORY.md` created with three entries: unbounded `_sized_cover_cache` growth, `toImage()` GPU→CPU readback on cache miss, local PIL import
- Session-open-on-book-removal bug: `_on_book_removed` cleared `_current_book` before `session_recorder.close()` → close saw null state → session discarded; fix: `close()` first, then null state
- 60-second session discard threshold unchanged for all close paths including involuntary
- Implementation prompt drafted with pinning test to prevent future regression

---

## 47. `fabulor: || Memory update history` — Jul 7 2026
**URL:** https://claude.ai/chat/e29fd33e-fae5-4573-a159-17a0bff09b14

- Memory consolidation session: 1914-line session log fed into memory system
- TasselOverlay confirmed implemented: procedural dangling tassel on Stats Timeline tab, physics, fringe gacha variation, theme keys
- Playing-seek oscillation considered fixed after extended soak
- `_showing_placeholder` race fixed: empty-path branch now clears `_showing_placeholder=False` before `clear_cover_theme()`
- Session-duplicate-on-graceful-close fixed: `close()` returns flush thread; `closeEvent` joins 0.5s + unconditional `clear_checkpoint()`
- Shortcuts system, click-to-filter, idle preloader fix, Excluded Books popup, cover thumbnail quality, logging — all confirmed in memory
- Achievements feature idea: discussed, decided against, filed to `TODO.md`
- Memory tool patterns documented: removal order is load-bearing; `replace` doesn't free a slot; `remove` then `add` for consolidation

---

## 48. `fabulor: | Keyboard shortcuts without keyboard navigation` — Jul 10 2026
**URL:** https://claude.ai/chat/0dbe49ae-4a29-4ea7-a4c4-b2638404e1f3

- Library full keyboard nav: arrow keys, Enter/Space to play, Alt+Enter for book detail, Tab toggles list/search, underscore-prefix search syntax, sort-field letter keys, view-mode digit keys 1–5
- QComboBox focus trap: hidePopup() override returns focus to list view
- QComboBox popup paint: silently ignored on this desktop — custom _ComboItemDelegate + _ThemedComboBox with own arrow (DO-NOT rule in CLAUDE.md)
- Tab clamp bug: QAbstractItemView.event() intercepts Tab before keyPressEvent — fix moved to event() level
- setAutoScroll(False) kills Qt native scroll-to-follow-selection — requires scrollTo() in affected handlers
- Escape: uniformly closes open panel; search field clear-and-defocus takes precedence when focused
- Tab must never reach window chrome (minimize/close) anywhere — hard constraint
- List-mode Left/Right: expand title/author text beyond truncation, evaluated fresh on landing, never sticky
- Traveling border-marker focus indicator: dot patrols widget border, carries relative perimeter position across Tab, four-phase lifecycle (patrol → decelerate → wait → fade); scoped to Settings Look tab for validation
- Theme fade mid-transition + panel-open shortcut: wired snap-forward mechanism into keyboard-shortcut panel-open paths

---

## 49. `fabulor: ||| Epsilon drift bug investigation and seek precision issues` — Jul 2026
**URL:** https://claude.ai/chat/c82ad6ff-5e4c-4e6c-bdf6-5b7f0825c120

- _logical_pos field on Player: decouples app's believed position from mpv's raw per-seek landing residual; time_pos getter is the sole seam (all 18 call sites unchanged)
- _apply_stylesheets narrowing: ~55% avoidable work (invisible-surface panels restyled unconditionally); fast-path/deferred-batch split with when_animations_done() for book-load and singleShot(0) for rotation/T
- M4B progress-reset regression: unguarded _sync_persistence write laundered near-zero transient time_pos into DB; fixed with monotonic guard seeded from DB progress
- VT cross-file restore race: _vt_file_loaded_awaiting_restore flag makes handoff order-independent (whichever of _on_file_loaded / restore stash runs first sets it, second consumes it)
- _apply_stylesheets visible-surface pass at __init__ line 682 was poisoning no-op guard — startup theming bug discovered during benchmarking
- Restyle-on-panel-open rejected as compensating mechanism (library panel stutter history)
- Regime A flow-animation hitching (~70–117ms at animation start) open at session end
- NOTES.md / SESSION.md confirmed as ground truth over TODO.md

---

## 50. `fabulor: ||| Flow animation and progress reset bug investigation handoff` — Jul 2026
**URL:** https://claude.ai/chat/8db18b08-697d-4e5b-a47d-1abe08db290a

- _sync_persistence monotonic guard: seeded from DB progress, prevents near-zero transient overwrite
- VT cross-file restore race: _vt_file_loaded_awaiting_restore flag (order-independent rendezvous)
- Library population regression after scan-on-launch removal: population now wired via QTimer.singleShot(0, self.library_panel.refresh) directly from DB
- _sized_cover_cache defensive wipe bug: unconditional assignment replaced with hasattr init-only guard
- _show_no_cover_state → request_clear_cover_theme() with is_any_panel_visible() deferral (was calling clear_cover_theme() unconditionally)
- Fade re-entrancy: _on_theme_changed guard extended to check _fade_in_flight; fade finished signal used for resume (flat 700ms poll was shorter than fade, causing early retry)
- _on_cover_pool_btn_clicked remove branch routed through canonical clear_cover_theme() (was inlining a subset)
- Claude Code "it's late, stop here" suggestions flagged as persistent violation — explicit CLAUDE.md rule confirmed

---

## 51. `fabulor: || Player keyboard shortcuts design` — Jul 2026
**URL:** https://claude.ai/chat/101c2cf5-57a2-4e1d-b936-dd257975c34f

- Player shortcuts: Space=play/pause, Up/Down=volume, Shift+Left/Right=long skip, Ctrl+Left/Right=chapter, Alt+Up/Down=speed, m=mute, u=undo
- Bracket keys and punctuation rejected: not stable across non-US keyboard layouts
- Configurable keybindings deferred: real cost (settings UI, conflict detection, persistence, test surface) not worth it for ~10 users
- _nudge_volume / _nudge_speed extracted so keyboard and mouse wheel share one implementation
- Speed autofire throttle: SPEED_NUDGE_THROTTLE_S; chapter/long-skip use separately named constants (CHAPTER_NUDGE_THROTTLE_S, LONG_SKIP_THROTTLE_S) — higher consequence per step
- Destructive-action-with-confirmation: Del/F/x arm visual confirmation state; Space/Enter confirms; single taps never skip confirmation
- Focus invariant established and made load-bearing: exactly one widget owns focus; global dispatcher only acts when focusWidget() is None or MainWindow
- All six panel open paths call PanelManager._claim_panel_focus; all close paths call _release_panel_focus
- clearFocus() must run after hide() — hide() on still-focused widget silently re-grants focus if last StrongFocus candidate in tab order (CLAUDE.md invariant)
- Any new always-on chrome widget must be Qt.NoFocus or focus-ownership breaks
- _ensure_panel_owns_focus() self-healing safety net on BookDetailPanel
- Book detail panel-local shortcuts: Left/Right cycles tabs, F/Del-x/K arm finished-toggle/remove/lock

---

## 52. `fabulor: | Deletion animation positioning issue` — Jul 2026
**URL:** https://claude.ai/chat/c139c005-47dc-46fb-b508-facb72f8db41

- History session row deletion animation: row content slid partway then paused in mid-transition
- Root cause: setFixedHeight() pinning minimumHeight while only maximumHeight was being animated — Qt constraint conflict
- Fix: row.setMinimumHeight(0) before constructing the animation
- Edge-case flagged: deleting last row + setFixedHeight(max(h, 1)) guard in _history_container may leave 1px dead zone
- Settings "Excluded Books" restore animation shares same pattern but intentionally left alone

---

## 53. `fabulor: | Library search filter persistence bug on app restart` — Jul 2026
**URL:** https://claude.ai/chat/1b27227d-8223-49ec-889a-72c420e9aed7

- Search persistence bug: clicked filters promoted to permanent typed filters on restart — save_search_filter() was reading search_field.text() instead of _explicit_filter_text; one-line fix
- Search field match-state styling not updating when book set changes under active search: _refresh_search_match_state() extracted, wired into refresh() and _on_search_changed
- Sort/filter mode switch (Recent, Finished, etc.) not resetting match-state styling: one line added to _on_sort_changed
- Tag Manager / Library mutual-exclusion: stale styling non-issue in practice; LibraryPanel.showEvent() re-validates before user can see it — documented in DEBT_INVENTORY.md as investigated-and-closed
- Stray entr -r python main.py dev-loop process can silently serve stale code — ps aux | grep -E 'entr|main.py' check added to CLAUDE.md
- Decision against creating UI panel-exclusivity reference doc: exceptions (Book Details over Library/Stats) make it a maintenance liability

---

## 54. `fabulor: ||| blur 1` — Jul 2026
**URL:** https://claude.ai/chat/aaf8ad7e-24a0-466d-bcbb-882d831b5919

- Architecture choice: blur-composited-overlay branch (grab pixmap, blur, composite) over blur-direct-widget (QGraphicsBlurEffect directly on widgets)
- Perf spike: UNIFIED_DIRTY_RECT confirmed best performer; QGraphicsBlurEffect slightly better visually; both within budget
- Mandatory full-rect blur pass on panel-open; dirty-sub-rect tracking via QEvent.Paint filter
- content_container.grab() confirmed broken: only rasterizes widget's own paint, not ancestor background — returns Qt default grey, not theme bg_main; fix: main_window.grab()
- main_window.grab() occasionally costs 290ms: Qt defers repaint/repolish work after setStyleSheet(); grab() forces synchronous resolution — whichever call is first pays the cost
- Pre-existing enterEvent quirk: fires at ~1.2–1.6s intervals for stationary cursor on theme swatches; cooldown gate insufficient (grab runs 290ms; new restyle can start mid-grab)
- CLAUDE.md entry added: Claude Code repeatedly called raw grab "clean" without verifying the specified test — social "you're right" without retracting the invalidated conclusion

---

## 55. `fabulor: ||| blur 2` — Jul 2026
**URL:** https://claude.ai/chat/5ed756db-a1ac-4881-af8d-4d278a677bff

- Punch-through flash: collision cost confirmed — setStyleSheet() defers work; first call to force synchronous resolution pays full accumulated cost
- content_container.grab() ruled out (never forces resolution — permanently stale)
- complete_main_fade() orphans _pending_fade_call: .stop() doesn't emit finished, so _pending_fade_call is never drained
- Spurious ThemeItem.enterEvent heartbeat: two-signal guard suppressed ~half the cycles (~1.4s→2.8s); second undiagnosed trigger path fires ~500ms after guarded restyle — halving frequency has no practical effect (consequence is binary); assessed as likely unfixable via this approach
- Feedback loop: _grab_and_blur() hide/show cycle generated paint events that dirty tracker interpreted as real content changes → machine-gun re-triggering at ~18ms; fixed with reentrancy guard + ~50ms window
- Direction B accepted: cached-frame blur with opportunistic refresh; forced refresh only on tab-switch/panel-open
- Decision to pursue structural fix: hover-preview state must be incapable of reaching content_container/main_window regardless of trigger source

---

## 56. `fabulor: ||| blur 3` — Jul 2026
**URL:** https://claude.ai/chat/4bae2606-b8fb-4527-b4ed-e166899a0095

- Nine bugs found, root-caused, and fixed in one session:
- _active_display_theme/_is_hover_active state written at call-decision time, not after apply completes — _mark_theme_applied() consolidation point introduced
- _grab_and_blur() grabbing while hover-active — _is_hover_active gate in refresh_dirty()
- complete_main_fade() orphaning _pending_fade_call via .stop() not emitting finished
- No-op guard poisoned by pre-apply state writes
- Hover-preview confinement violation: hover-flagged stashes replayed through full apply path reaching panels — hover stashes now discarded (not deferred) at all three drain sites (_on_fade_finished, snap_theme_forward, complete_main_fade)
- Hover-interrupts-hover: stop-and-apply (not stash) when incoming hover interrupts running hover fade
- Chapter-dropdown colors lagging one theme behind
- Non-hover theme changes applying while panels open: required forward-audit (enumerate Themes-tab widgets from construction, trace signals forward) after backward-audit failed three times
- T-shortcut rotation silently dead after Settings panel close: _fade_in_flight stranded True — unconditional clear after stop
- Three open threads at session end: heartbeat second trigger (root-caused, plan written, not implemented); blur-toggle-not-applying-live (planned, not implemented); cursor fluctuation under blur (root-caused, deferred)

---

## 57. `fabulor: | blur 4` — Jul 2026
**URL:** https://claude.ai/chat/5aaecfe1-ce7b-44c0-8b27-d14d029fcee8

- _pending_fade_call widened from 5-tuple to 6-tuple including bypass_panel_open_guard — snapback was silently dropping this flag, landing in panel-open guard and getting clobbered by ongoing hover activity
- Confirmed empirically: bypass_panel_open_guard=True never co-occurs with hover=True across 65 log entries (required before widening, to avoid reopening theme-bleed regression)
- apply_cover_theme/clear_cover_theme calls from app.py legitimately reach _on_theme_changed with hover=False, bypass_panel_open_guard=False — snap_theme_forward behavior change is real but correct
- Synthetic-leave suppression: spurious unhover events during window blur/focus grabs guarded (modeled on existing ThemeItem-level mechanism)
- Hover-active region narrowed from themes_tab to pool_container specifically — prompt drafted for next pass
- main_window_builders.py confirmed as pure wiring file; behavior belongs in theme_manager.py
- 4 pre-existing test_cover_theme_pending.py failures established as baseline for all pytest runs

---

Index last updated Jul 22 2026. To update: open a new entry at the bottom following the same format.
