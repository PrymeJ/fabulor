
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

## Sleep Timer

### State not persisted across restarts
`config.get_sleep_duration()` and `config.get_sleep_mode()` exist and are written by `SleepTimerPanel.set_sleep_timer()` ([sleep_timer.py:130–137](src/fabulor/ui/sleep_timer.py#L130-L137)), but nothing reads them on startup. `SleepTimerPanel.__init__` always starts with `_sleep_timer_end_time = None` and `_sleep_mode = None`. Whether to restore sleep timer state across restarts is a product decision. Address when sleep timer feature is next touched.

---

## Panel Animation — Deferred Fixes

### `library_panel_animation.finished` duplicate connection risk — `_start_library_entry` and `_close_library_flow`
`_start_library_entry` ([panels.py:86](src/fabulor/ui/panels.py#L86)) connects `finished` → `_on_library_shown` with no guard against the animation already running. `_close_library_flow` ([panels.py:223](src/fabulor/ui/panels.py#L223)) does the same for `_on_library_hidden`. If either is called twice before the animation completes, a second connection accumulates; the self-disconnect in `_on_library_shown`/`_on_library_hidden` only clears one copy per firing. Most paths are guarded (`_close_library_flow` checks `Running` at line 212; the sidebar path serialises through `_on_sidebar_closed_for_panel`), so the race is low frequency but real. Fix when panel animation code is next touched: add the disconnect-before-connect pattern matching the other animation handlers.

---

## Known Architectural Debt

### _cover_cache has no eviction — unbounded growth
`_cover_cache` ([library.py:43](src/fabulor/ui/library.py#L43)) is a module-level `dict` keyed by `book_id (int) → QPixmap`. It grows for the lifetime of the session and is never pruned. At ~226×344px JPEG-decoded to RGBA in memory, each entry is roughly 300 KB. 500 user-added covers (125+ books × 4 slots, all loaded in one session) would consume ~150 MB. Not a realistic v1 scenario given the 4-per-book cap. Revisit if the cap is raised or if memory pressure is reported. Fix when ready: LRU eviction keyed on last-visible timestamp, sized to ~200 entries.

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

## Library Panel — Open/Close Performance (CLOSE STUTTER RESOLVED 2026-05-13 — open performance still has open items)

Current state: close slide on book selection is smooth. Open performance is unchanged.

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