# Critical Architecture Rules

## DO NOT modify, refactor, or touch any code related to MPV initialization under any circumstances. This includes the _ensure_mpv() method, the load_book() method's MPV init block, the locale.setlocale(locale.LC_NUMERIC, "C") call, and all MPV constructor arguments (vo, ao, vid, ytdl, keep_open). This code resolves a hard-won, non-obvious bug involving libcaca, libtinfo, and Qt's locale reset on Wayland/openSUSE. Any "improvement," "cleanup," or "fix" to this block will break the app. If you think something in this block needs changing, say so explicitly and wait for confirmation before touching it.

## DO NOT use self.player.chapter to derive which chapter the UI should display. It looks like the obvious choice but it is wrong — mpv updates the chapter property asynchronously and it will be ahead of or behind time_pos after any seek. Always derive the current chapter by walking self.player.chapter_list and finding the last entry whose time <= pos + 0.35. The 0.35s tolerance is intentional: mpv's chapter boundary floats consistently land ~0.25s short of their nominal values. This rule applies everywhere in _sync_chapter_ui and any future method that maps a playback position to a chapter index.

## DO NOT connect _on_file_ready to the file_loaded signal. It must only connect to book_ready. book_ready fires once per book (before any file for VT books; after file-loaded for non-VT). file_loaded fires on every mpv file-loaded event including VT file switches mid-book. If _on_file_ready runs on every file switch, it triggers position restore, which triggers another file switch, causing a quadruple-advance feedback loop. This was the root cause of two reverted stage 3 implementations.

## DO NOT read self.progress_slider.value() (or any slider's .value()) in _on_file_ready to compute the "new position" for a switch animation. The slider value is stale at that point — _update_ui_sync's setValue call is gated on not slider_animating and not is_seeking and may not have run yet. Always compute the target slider value from the authoritative data: int((new_progress / self.player.duration) * 1000).

## DO NOT remove the animation-state guard in _sync_progress_sliders or _sync_chapter_ui. Both methods check whether the flow animation is running before calling setValue. If that check is removed, the 200ms UI timer will fight the animation frame-by-frame, causing visible jitter. The guard must survive any refactor of those methods.

## DO NOT restore the show_metadata=False argument to the apply_library_state call in
library_controller.py. It was removed on 2026-05-11 because it was silently overriding
cover display on every book switch. _load_cover_art owns metadata_label visibility. If
you believe this needs to change, say so explicitly and wait for confirmation.

# Fabulor — Project State

## Goal

A cross-platform desktop audiobook player for Linux (primary) and Windows (later port).
Fills a genuine gap: existing Linux players (Cozy and similar) treat audiobooks like music
files, have slow library loading, poor metadata support, and desktop-centric UIs that assume
the user is watching the screen. This app assumes the opposite.

The visual and interaction reference is **Listen** (Android). The design language is
mobile-inspired — clean, dark, cover-art-driven — but the interaction model is desktop:
keyboard shortcuts, window management, information density where it matters.

---

## Core Design Principle

**Audiobooks are not music. The screen is not the primary interface.**

The user is doing something else while listening. They glance at the player occasionally.
They need controls that work without focus. Every UI decision flows from this principle.

Consequences:
- Chapter list is not permanently visible. It is not a sidebar.
- The default view is vertical and minimal.
- Global hotkeys matter more than on-screen buttons.
- Progress through the book is the primary information, not the chapter list.
- A collapsed mini-player mode exists for users who want the controls without the UI.

---

## Tech Stack

| Layer | Choice | Rationale |
|---|---|---|
| UI framework | PySide6 (Qt) | Native performance, proper desktop behaviors, high ceiling, cross-platform |
| Audio engine | mpv via python-mpv | Stable, supports every format, high-quality time-stretching at 4x+ |
| Time-stretching | rubberband (primary) | Better audio quality at high speeds vs scaletempo |
| Metadata | Mutagen | Standard, handles M4B/MP3/FLAC, read and write |
| Database | SQLite via sqlite3 | Local library cache, instant subsequent loads |
| Color extraction | colorthief + Pillow (later) | Dynamic background from cover art, v1 uses flat color |
| Path handling | pathlib.Path everywhere | No hardcoded separators, portable to Windows |

**Not used:** Flet (convenience ceiling too low for a serious desktop app)

### Color roadmap
- v1: flat user-defined background color
- Later: colorthief extracts dominant color from cover art
- Later: Pillow normalizes it (darken, check contrast against white text)
- Later: optionally materialyoucolor for full Material You dynamic theming

---

## Library Model

**Folder = Book.** One folder per book. The folder name is parsed for metadata.
The database stores overrides and cache. Source files are never mutated unless the
user explicitly triggers a metadata edit.

### Folder name parsing
Two patterns, selectable in Settings (applied globally):
- `Author - Title` (default)
- `Title - Author`

If a folder matches neither pattern, the full folder name is used as the title with
no author parsed. This is the user's problem, not the app's.

### Bracket content in folder names
Bracket suffixes such as `Author - Title [Simon Vance]` or `Author - Title [64kbps]`
are treated as part of the title string. No stripping, no grouping, no special handling.
Two folders with the same Author - Title but different bracket content are two distinct
books. The app is not a database; it does not group by anything.

### Scanning behavior
- First run: full scan, all metadata written to SQLite. May take tens of seconds
  for large libraries (300+ folders). This is expected and communicated to the user.
- Subsequent runs: instant. Database is read, not the disk.
- Incremental updates: only folders added/removed/modified since last scan are
  re-processed.
- Background scanning: UI remains responsive during scan via worker thread.

### Metadata fields stored per book
- Title, Author (parsed from folder or overridden)
- Narrator (read from file tags if present; displayed in 1 per row library view)
- Cover art (embedded or overridden)
- Total duration
- Last playback position
- Playback speed (per-book override; falls back to global default if not set)
- Chapter list (if available)
- Year (if available)
- User overrides flag (title, cover changed manually)

---

## Chapter Handling

Priority order:

1. **M4B with embedded chapter markers** → use them directly (Mutagen reads them)
2. **MP3 folder (multi-file)** → each file becomes one chapter. Title = `Path(file).stem`. Start time = cumulative offset from all preceding files. Chapter list stored in `_chapter_list` on Player; displayed identically to M4B chapters. Navigation uses `seek_async` with global time, not mpv's chapter property.
3. **M4B with no chapter markers** → treated as one track, no chapter list shown
4. Everything else → edge case, deferred

**MP3 numbering:** natural sort (2 before 10 before 19) is the target behavior but
is out of scope for v1. Deferred.

**Silence detection for chapter generation: explicitly out of scope.** Unreliable
across encodings, narrators, and music intros. Not implemented.

---

## Playback

- Engine: mpv
- Time-stretching filter: rubberband (primary), scaletempo (fallback/option)
- Speed range: up to at least 4x with pitch correction maintained
- Per-book speed memory: the app remembers the last speed used for each book
- Global default speed: set in Settings; used when no per-book override exists
- In-app volume: independent of system volume (useful for normalizing loud/quiet narrators)

---

## UI Structure

### Main view (default)
Vertical layout. Narrow window suitable for parking in a corner.

**Layout TBD after UI experimentation.** The following is a working outline,
not a locked specification. Elements and their order may shift once the interface
is interactive.

Candidate elements from top to bottom:
- Cover art (square, dominant element)
  - Possible interaction: tap/click anywhere on cover = play/pause toggle (undecided)
  - Possible interaction: click left area = rewind, right area = forward (undecided)
  - Note: placing cover art flush at the top edge may look poor — padding or
    a menu bar above it may be needed
- Title and Author
  - Hidden when cover art is present (redundant information)
  - Displayed in collapsed/mini-player state where cover art is absent
- Narrator
  - Not shown in main window under any circumstance
- Chapter dropdown (see below)
- Book progress bar (full book, continuous)
  - Chapter markers as notches if chapter data exists
  - Displays: time elapsed · time remaining (toggle on click)
  - Optional toggle (v2 candidate): time at current speed vs time at 1x speed
- Chapter progress bar
  - Separate from book progress bar
  - Displays time elapsed and remaining within the current chapter
- Playback speed control
  - Slides in the speed panel with playback options
  - Clicking opens a control menu
- Transport controls
  - Previous chapter · Rewind X seconds · Play/Pause · Forward X seconds · Next chapter
  - Play/Pause button may be removed if cover art tap gesture is adopted (undecided)
  - Skip interval (X seconds) is user-configurable in Settings
- Right click on the cover art area (A specific button may be added later)
  - Triggers a sliding panel: Settings, Stats, etc.
- Library button
  - Triggers a full-screen slide-in library view

### Chapter dropdown
- Collapsed state: displays current chapter name as a clickable label; also toggled by pressing `c`
- Label is non-clickable when no chapters exist or only 1 chapter
- Expanded state: overlay list rendered as a child widget of the main window (not a popup — stays within the window boundary always)
  - 5 rows visible by default; expand button (▲/▼) appears top-right when chapter count > 5
  - Expanded height capped so the list never exceeds the available space above the chapter label (respects top margin below the progress bar)
  - Each row: chapter name (left-aligned, elided) · duration at current playback speed (right-aligned)
  - Fade in (600ms) / fade out (600ms) animation; expand button opacity synced to the same animation
  - Active chapter centered in the 5-row window on open
- Click behavior:
  - Left click: seek to chapter, respect current play/pause state
  - Right click: seek to chapter + force play
  - Clicking outside the list (or pressing `c`, `Escape`): dismisses without seeking
  - Clicking cover art while list is open: dismisses only, does not play/pause
- Keyboard navigation while list is open:
  - Up/Down: move selection
  - Left/Right: expand/collapse (when > 5 chapters)
  - Enter/Return: seek (respects pause state)
  - Space: seek + force play
  - Escape or `c`: dismiss
  - Digit keys: jump to chapter by typed number — mode configurable in Settings (Controls tab)
    - By name: word-boundary search in chapter titles ("6" matches "Chapter 6", not "Chapter 16")
    - By index: 1-based position in the chapter list
    - 800ms debounce allows multi-digit entry (e.g. "3" then "2" → "32")
    - Auto-play or Jump-only: configurable in Settings (Controls tab)
- Undo triggered on chapter jump when distance > 60s × current speed
- Jump memory: position at the moment of jump is stored (one level deep)
  - Re-selecting the chapter jumped *from* returns playback to the exact pre-jump position (deferred)
  - No dedicated back button — the undo overlay is the undo mechanism

### Mini-player mode
- Toggled by a button in the main view
- No cover art
- Minimal controls only: play/pause, rewind, forward, progress indicator
- Title and Author displayed (since cover art is absent)
- Button to restore full view

### Library view
- Full-screen, slides in
- Sort functionality by title, author, recent, progress, duration, year with asc/desc toggle
- Five different view modes (1, 2, 3 books per row, square, and list with no covers)
- Triggered by dedicated library button in main view

### Background color
- v1: with a themes selected from a pool with random theme change option 
- Later: extracted from cover art, darkened for contrast, white text always readable

---

## Keyboard and Global Hotkeys

### Global (work regardless of focused window)
- Play/pause → via MPRIS2 on Linux (media key, works with earbud single tap)
- Forward X seconds → configurable global hotkey
- Rewind X seconds → configurable global hotkey

**Wayland note:** pynput does not work for global hotkeys under Wayland.
Global shortcuts on KDE/Wayland use D-Bus registration via KDE Global Shortcuts.
MPRIS2 handles media keys natively and is the primary mechanism.

### In-app (require window focus)
- Space → play/pause
- Left/Right arrow → rewind/forward
- Comma/Period → speed down/up
- `c` → open/close chapter list (when chapters exist)
- Digit keys → chapter jump (when chapter list is open; behavior configurable in Settings)
- Prev button right-click → seek to 00:00:00 with undo

All shortcuts user-rebindable in Settings (Controls tab partially implemented).

### Earbud tap gestures
- Single tap play/pause → works via MPRIS2, essentially free
- Double/triple tap → hardware and OS dependent, outside app control
- Documented in README as hardware-dependent, not promised as a feature

---

## File Responsibilities

fabulor/
├── main.py                          # Entry point
├── test_db.py                       # Database tests
├── pyproject.toml
├── requirements.txt
├── TESTING.md
├── README.md
├── LICENSE
│
└── src/fabulor/
    ├── __init__.py
    ├── app.py                       # MainWindow wiring only. No feature logic.
    ├── player.py                    # MPV player wrapper, audio processing
    ├── db.py                        # SQLite database layer
    ├── config.py                    # QSettings wrapper, user preferences, config persistence 
    ├── themes.py                    # Theme definitions; per-component QSS functions (get_base_stylesheet, get_title_bar_stylesheet, get_player_stylesheet, get_library_stylesheet, get_settings_stylesheet, get_sidebar_stylesheet, set_stats_stylesheet)
    ├── book_quotes.py               # Quote data
    ├── settings.py                  # (Tiny, 402 bytes)
    ├── library_controller.py         # Library logic
    ├── settings_controller.py        # Settings logic (with dynamic binding)
    │
    ├── library/
    │   ├── __init__.py
    │   └── scanner.py               # Async file scanning worker, background threads
    │
    └── ui/
        ├── __init__.py
        ├── audio_controls.py        # Audio settings tab
        ├── title_bar.py             # Window title bar
        ├── controls.py              # Playback controls (sliders, buttons)
        ├── chapter_list.py          # Chapter dropdown and chapter list logic
        ├── library.py               # Library grid, BookModel, BookDelegate
        ├── cover_loader.py          # Async cover loader using QThreadPool; emits Signal(int, QImage) (book_id, image) — callers convert to QPixmap on the main thread
        ├── cover_theme.py           # Extracts dominant color from cover art to derive a theme dict
        ├── speed_controls.py        # Playback speed panel
        ├── sleep_timer.py           # SleepTimer UI and logic
        ├── stats_panel.py           # Stats panel content and options
        ├── audio_controls.py        # Audio settings tab
        ├── theme_manager.py         # ThemeManager, ThemeComboBox; _apply_stylesheets() dispatches per-component setStyleSheet calls; timing constants (_THEME_SWITCH_FADE_MS, _SNAPBACK_FADE_MS, _PANEL_ANIM_GUARD_MS) defined at top of file
        ├── panels.py                # Panel manager (library, settings panels)
        │
        ├── models/
        ├── __init__.py
        └── book.py                  # Book dataclass
  └── assets/                        # Project assets
        ├── fabulor.ico              # Project icon
  │     ├── img                      # Theme backgrounds
        ├── overlook.png             # Background for The Overlook
    
## Stylesheet architecture (COMPLETED)

Each major UI component owns its own stylesheet. `ThemeManager._apply_stylesheets(theme_name, hover=False)` dispatches `setStyleSheet()` to individual components — never to `main_window` as a whole.

**Components and their functions:**
- `main_window` ← `get_base_stylesheet()` — QWidget#mainwindow bg, QToolTip, status_banner, overall/scan progress bars, chapter_dropdown, undo overlay
- `title_bar` ← `get_title_bar_stylesheet()` — TitleBar bg and buttons
- `content_container` ← `get_player_stylesheet()` — cover area, playback buttons, sliders, metadata labels
- `library_panel` ← `get_library_stylesheet()` — BookItems, grid, search bar, scrollbars (skipped during hover — library is always hidden during settings interaction)
- `settings_panel`, `speed_panel`, `sleep_panel` ← `get_settings_stylesheet()` — all settings controls, theme buttons, audio tab, scrollbars
- `sidebar` ← `get_sidebar_stylesheet()` — sidebar bg and buttons
- `stats_panel` ← `get_stats_stylesheet()` — stats panel with its tabs and buttons

**Key rules:**
- `_apply_stylesheets()` is the only entry point for theme application. Never call `main_window.setStyleSheet()` directly with a full-app stylesheet.
- All 6 functions use `_resolve_theme(theme_name)` to merge the base theme with any custom overrides before building rules.
- Initial application happens at the end of `_setup_ui()`, after all widgets are constructed — not during widget creation.
- `chapter_list_widget` is a direct child of `main_window` (not inside `content_container`), so its rules live in `get_base_stylesheet()`.
- During `hover=True`, `library_panel` is not restyled. All other components are.

---

## Player state (player.py)

_eof: bool — reset to False in load_book() before instance.play() fires
_paused_time: float | None — drift tracking for paused position; lives on Player, not app
_is_seeking: bool — exposed via is_seeking property/setter on Player
_seek_target: float | None — stores the target pos passed to seek_async; cleared by _on_time_pos_change when position settles within 1.0s
_base_volume, _fade_ratio, _undo_pos, _last_undo_click_time — also on Player

Property caching (added 2026-05-14)
time_pos, duration, pause, speed are all cached via observe_property callbacks and served from _cached_time_pos, _cached_duration, _cached_pause, _cached_speed. Reads never cross the IPC boundary. Setters still write to self.instance — the observer fires and updates the cache automatically.

Seeking — async path (added 2026-05-14)
Player.seek_async(pos) uses command_async('seek', pos, 'absolute+exact') — non-blocking, returns immediately. This is the correct method for all UI-driven seeks (slider, chapter slider, right-click snap, undo, and all VT cross-file seeks). apply_smart_rewind and book-load position restore remain on the sync time_pos = path.
seek_within_chapter returns the computed new_pos (float) on success, None on early exit. Callers use this value directly — never read time_pos back after a seek.
is_seeking is cleared in _on_time_pos_change when the observed position arrives within 1.0s of _seek_target. It is NOT cleared in the 200ms polling loop.

Virtual timeline — multi-file MP3 books (added 2026-05-15)
_virtual_timeline: list | None — [{file_path, cumulative_start, duration}] entries built from book_files DB table. None for all non-VT books.
_file_offset: float — cumulative start of the currently playing file in seconds. Added to mpv's local time_pos to get global position.
_book_duration: float | None — total duration of the book across all files.
_chapter_list: list | None — [{title, time}] where time is global seconds. For VT books, derived from filenames. For M4B, from embedded markers.
_current_vt_index: int — index into _virtual_timeline for the currently playing file.
_pending_local_pos: float | None — local seek target for the next file-loaded event (set by seek_async for cross-file seeks).
_is_vt_file_switch: bool — True while a VT file switch is in progress. Gates _on_pause_test to prevent transient pauses during file load from triggering _advance_or_finish.
_last_vt_chapter: int — last emitted global chapter index. -1 on reset so the first position tick always emits chapter_changed.

Signals:
book_ready — fires once per book. VT: from ungate_play/_on_playlist_resolved (before any file loads). Non-VT: from _on_file_loaded (after mpv loads the file).
file_switched — fires per VT file load from _on_file_loaded when _virtual_timeline is not None. Connected only to _on_vt_file_switched (clears is_seeking).
file_loaded — kept but not connected to _on_file_ready. Do not reconnect.

EOF detection with keep_open='always':
mpv never fires end-file with reason EOF (reason_int=0) when keep_open='always' is set — it always fires RESTARTED (reason_int=2). All EOF detection must go through _on_pause_test near-EOF position check (pos >= dur - 1.5 while paused). The _on_end_file reason_int=0 branch is unreachable dead code.

Restart from EOF (app.py toggle_play_pause)

Clears both config and DB progress to 0 before load_book
load_book resets _eof = False immediately — before mpv starts loading
_restore_position sees 0 in both stores, skips seek entirely
Smart rewind does not fire on restart because no resume-from-pause path is taken

Seeking state pattern

All seeking state goes through self.player.is_seeking, not self._is_seeking on app
_update_ui_sync reads self.player.is_seeking for drift guard
Both _sync_progress_sliders and _sync_chapter_ui gate setValue with not self.player.is_seeking

EOF UI path

_update_ui_sync: when is_eof, synthesizes pos = dur, updates sliders and labels, returns early
DB duration fallback: if dur is None at EOF, fetches from db.get_book() via book.duration (attribute, not dict key)

---

## Library Architecture 

The library panel has been fully migrated from a virtual widget pool to Qt's model/view architecture. Key points for any model working on this codebase:
BookModel(QAbstractListModel) owns all data — books, sort, filter, cover pixmaps, hover state, toggle state, and live playback position/duration. It lives in library.py. The model's _covers dict is the same object as the module-level _cover_cache singleton — covers loaded by the idle preloader are immediately visible to the model without any copy or transfer step.
BookDelegate(QStyledItemDelegate) paints all five view modes. List mode is fully delegate-painted — there are no setIndexWidget calls in the current codebase. The delegate accepts all theme colors as constructor arguments via a theme dict passed at construction and on theme change. It never resolves colors itself.
Cover loading is viewport-aware and on-demand. _load_visible_covers uses binary search on visualRect to find the true visible row range — do not use indexAt(bottomRight) in IconMode, it returns invalid in inter-cell gutters. An idle preloader (start_idle_preload) dispatches workers in batches of 3 at 50ms intervals starting 4 seconds after app launch, pausing on user interaction and resuming after 5 seconds of inactivity.
ITEM_DIMENSIONS and FONT_SIZES are the single source of truth for cell geometry and font sizing across all modes. SORT_KEY_MAP maps combobox display keys to Book dataclass field names. MIN_PROGRESS = 1.0 — anything under one second is treated as no progress.
A dedicated 1-second `_progress_timer` drives dynamic updates via update_current_book_progress → BookModel.update_playing_progress → dataChanged → delegate repaint for the playing book's cell only. This is separate from the 200ms main UI sync timer.
_apply_view_mode(mode) is the single method that switches QListView between IconMode (grid) and ListMode — always call this, never set viewMode or gridSize directly.     

---
## Session Recording with DB integration

- _close_session() then _current_book = db.get_book() then _open_session() — order is critical. Close before updating _current_book or the wrong book gets credited.
- _session_position_start set after _restore_position() via config.get_last_position() — not from mpv directly, which is async and returns 0 at that point.
- PRAGMA foreign_keys = ON added to db.py connection setup.
started_at added to books table — set on first session write if not already set.
- Threshold: 60 seconds wall-clock. Pause timeout: 3 minutes. Seek credit: 15 seconds continuous play.
- Ctrl+C / entr -r kills bypass closeEvent — sessions interrupted this way are lost. Expected, not a bug.

## Cross-Platform Notes

Linux is the primary target. Windows is a later port, not a parallel build.

Design-for-portability rules (applied from day one):
- `pathlib.Path` everywhere, no string path concatenation
- No Linux-only libraries in core logic
- Media integration abstracted: MPRIS2 on Linux, SMTC on Windows (later)
- Global hotkeys abstracted: platform implementation swappable

Packaging is a separate problem solved per platform when needed:
- Linux: Flatpak (later)
- Windows: PyInstaller or Nuitka (later)

---

## Handling the Books Removed from the Library

**Implemented 2026-05-18 — approach differs from the original design below.**

The `books` table now has two independent soft-delete flags:
- `is_deleted INTEGER NOT NULL DEFAULT 0` — set by `remove_scan_location` when a monitored folder is removed.
- `is_excluded INTEGER NOT NULL DEFAULT 0` — set by `set_book_excluded` when the user manually removes a book via the trash button in BookDetailPanel.

Both are filtered by `get_all_books`. Stats queries intentionally see all rows regardless of either flag — history and progress are preserved permanently. Both flags reset to 0 on the next rescan (`upsert_book` ON CONFLICT block resets `is_deleted=0, is_excluded=0`), which resurfaces the book.

The `deleted_books` table approach described below was designed before implementation and is now superseded. Do not implement it.

~~When "Remove from Library" gets implemented alongside the library rewrite, deleted_books gets created at the same time, not retrofitted after. A deleted_books table will be populated on removal, storing path, title, author, cover_data (cover as BLOB, not path — paths become invalid). Cover data kept for N days or permanently, user preference. When a book is removed from library, a row goes in before the DELETE. Then get_finished_in_period, get_daily_book_breakdown, and all breakdown queries check deleted_books as a second LEFT JOIN fallback when books returns NULL.~~

## Known Edge Case

- Screen drag 4K→1080p: Virtual scroll rebind will call set_cover again, which fetches DPR from self.screen(), so it would
re-scale correctly if something triggers a rebind. But if the user drags without scrolling, no rebind fires, and the pixmap
stays at 2× DPR on a 1× screen. The fix is connecting to QWindow.screenChanged signal.

---

## Explicit Out of Scope for v1

- Windows port
- Dynamic color extraction from cover art (flat color only)
- Silence-based chapter generation
- MP3 natural sort (2 before 10 before 19)
- Metadata editor (title/cover editing within app)
- Global hotkey configuration UI (defaults only in v1)
- Double/triple tap earbud gesture support
- Bookmarks beyond last-position memory

---

## Open Questions

- **UI layout:** Final element order and interactions (cover art tap gestures, play/pause
  button presence) to be decided after hands-on experimentation with the interface.
  Not a blocker for starting development.

---

## Agent Context

This project uses multiple AI agents with divided responsibilities:

- **Claude** (this project): architecture, decisions, code review, documentation
- **Gemini**: M4B pipeline scripts, folder naming conventions, chapter naming convention
- **Windsurf / Copilot / other**: code generation and implementation
- **GPT**: critique and synthesis

When bringing code or decisions from other agents into this project, paste a brief
summary of what was built and any decisions made. Claude does not need the full code
to give architectural guidance — module summaries and decision logs are sufficient.

---

## Commit Convention

- Start repo on day one, before any working code
- Commit on every meaningful unit of progress
- Message format: short, specific, imperative
  - ✅ `Add SQLite scanner with incremental update logic`
  - ✅ `Wire chapter dropdown to mpv seek`
  - ❌ `update` / `fix stuff` / `changes`

---

---

## Settings — Controls Tab

The Controls tab (previously a placeholder) now contains:

- **Chapter number keys — By name / By index**: determines how digit key presses map to chapters when the chapter list is open. "By name" does a word-boundary search in chapter titles (e.g. "6" finds "Chapter 6" but not "Chapter 16"). "By index" uses 1-based position in the list.
- **Auto-play / Jump only**: when a digit jump resolves, "Auto-play" seeks and starts playing; "Jump only" seeks but respects the current pause state.

Both settings persist via QSettings (`chapter_digit_mode`, `chapter_digit_autoplay`). Visual state synced through `SettingsController.sync_all_settings_visuals()`.

---

## DO NOT use `self.player.chapter = idx` for chapter navigation anywhere. Always use `seek_async(target + _CHAPTER_BOUNDARY_EPSILON)` with a position-based chapter walk. Native mpv chapter assignment undershoots boundaries and causes drift — this was the root cause of multiple navigation bugs.

## DO NOT read `self.chapter` (mpv's native property) to determine the current chapter index in any navigation or display path. Always walk `chapter_list` against `time_pos + _CHAPTER_BOUNDARY_EPSILON`.

## DO NOT emit `chapter_changed` from `_on_chapter_change` when `_is_seeking` is `True` or when `_chapter_list` is not `None` (cue mode). The `_is_seeking` guard prevents the native mpv observer from racing with `seek_async`'s immediate emit and overwriting the correct chapter index with a stale value — this caused visible label errors on every chapter seek. The `_chapter_list` guard prevents cue-mode corruption — mpv's native chapter index has no relationship to cue chapter index. Both conditions are checked together; removing either breaks chapter navigation.

## DO NOT set `_virtual_timeline` for CUE books. CUE mode is indicated solely by `_chapter_list` being non-`None` with `_virtual_timeline` remaining `None`. Setting `_virtual_timeline` would activate VT file-switching machinery on a single-file book.

## DO NOT simplify `Player.terminate()` — it must call `wait_for_shutdown()` after `terminate()` to prevent a libmpv teardown crash in `avformat_close_input`. The crash was masked for an unknown period by a debug print and is easy to reintroduce.

## DO NOT pass `0.0` as the `progress` value to `upsert_book` or `upsert_books_batch`. Use `None` if progress is unknown. The scanner does not know a book's saved playback position — it must omit progress entirely (leave it as `None`) so the `COALESCE(NULLIF(..., 0.0), books.progress)` upsert logic can preserve whatever the user left off at. Passing `0.0` is treated as "no progress supplied" by the NULLIF safety net, but that is a net, not a contract — callers must use `None`.

## DO NOT modify `upsert_book` without applying the identical change to `upsert_books_batch`. Both methods must share identical SQL logic — they differ only in execute vs executemany. The `CASE WHEN books.X_locked = 1` guards for title, author, narrator, year are load-bearing: they prevent rescans from overwriting user-edited metadata. Out-of-sync upserts cause silent data loss.

## DO NOT remove the `CASE WHEN books.X_locked = 1` guards from the upsert ON CONFLICT block. These guards protect user-edited metadata from being overwritten by rescans. The pattern `CASE WHEN books.title_locked = 1 THEN excluded.title ELSE updated.title END` must be applied to all four metadata fields (title, author, narrator, year) in both upsert methods.

## DO NOT add columns to the migration block without checking for duplicates. The pattern is `if "col_name" not in col_names: ALTER TABLE`. Duplicate ALTER TABLE statements crash the migration. Check before adding.

---

*Last updated: 2026-05-19 — Metadata lock feature, upsert guards for locked fields, migration pattern.*
