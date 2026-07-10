# TODO

Deferred work — short, dated, status-tracked entries. Not for root-cause writeups (those go in
NOTES.md) or session logs (SESSION.md). When an entry is started, move it under "In Progress" with
the date; when done, delete it (the commit/SESSION.md entry is the permanent record).

## Pending

- **[2026-07-09] FIX: Library Tab toggle isn't actually clamping — falls through to Qt's default
  focus chain.** The app-wide Tab/Escape policy (`624fc22`) was supposed to leave Library's
  existing list↔search Tab toggle as the ONLY thing Tab reaches while Library is open (the
  `MainWindow._handle_tab_escape` branch returns `False` for `panel == "library"` specifically to
  defer to that toggle). Live-tested by Pryme: it does not clamp. From the book list, Tab takes
  ~7 presses to reach the first combo box (sort/filter dropdown) — walking through it, the
  asc/desc arrow button, the second (view-mode) combo, the search field, and the back button
  before finally reaching the books again. Pryme doesn't want Tab to reach the combos/back button
  at all, but says the bigger problem is not knowing where focus currently is at any point — "I
  have no idea where it is until going there." Two live theories, unconfirmed:
  (1) nothing calls `_list_view.setFocus()` when Library first opens, so the very first Tab press
  starts from whatever widget had focus before Library opened — never from the list at all; (2)
  the list's own Tab-catching keyPressEvent patch may not actually be consuming plain `Key_Tab`
  the way it consumes arrows, letting it fall through to Qt's native chain. **Do not guess-fix
  either theory** — Pryme's own instinct (endorsed) is to instrument first: log the actual focused
  widget on every Tab press, per view mode (the different view modes reportedly take different
  press-counts to cycle back around, which is itself a clue). Get a verified per-press focus trace
  before touching code.
- **[2026-07-09] FIX: keyboard-selection focus indicator is nearly invisible.** Across the Tab/
  Escape live-testing, Pryme reported it's "almost impossible to see where the focus is" for
  keyboard-focused controls in general (not just the Library keyboard-selection highlight from the
  earlier session — this is about standard widget focus, e.g. in Settings/Speed/Sleep panels via
  the new Tab cycling). Floated a glow-style indicator as one option, undecided. Explicitly
  deferred to a future session ("we'll try and decide tomorrow") — do not implement a specific
  fix without discussing the visual approach first.
- **[2026-07-09] Parked, to pick up next session:** three items named by Pryme at session end, not
  yet scoped or investigated:
  - A "hodge-podge" bug from a screenshot Pryme has: pressing `T` (rotate theme) and a panel-open
    shortcut (`L`/`G`/`P`/`A`/`S`/`Z`) in quick succession produces some kind of visible glitch.
    Screenshot exists on Pryme's end; not yet shared/described in enough detail to reproduce or
    diagnose — ask for the screenshot/repro steps at the start of next session.

- **[2026-07-06] FIX (batched with the mpv-playback pass): books opened-without-playing save a
  spurious non-zero position → spurious library progress.** A book opened and closed without
  genuine playback persists a small non-zero position instead of 0: `_save_current_progress`
  (`app.py:1294`) saves mpv's actual reported `time_pos`, and the paused-embedded restore path adds
  a `_PAUSED_SEEK_UNDERSHOOT_COMP` (0.37, `player.py:670-671`) residual scaled by the per-book
  speed, landing a few tenths past 0. `MIN_PROGRESS = 1.0` (`library.py:54`) is the only thing
  hiding this; any book whose crept value clears 1.0 (observed: 2666 = 1.3588) draws a progress
  bar/% in the library while showing `0:00:00`. Library-wide-latent — DB `progress` is written from
  config only when a book is actually opened (`_restore_position`, `app.py:1601-1613`), so each
  book surfaces the bug the first time it's re-opened after creeping. **Do NOT fix by bumping
  `MIN_PROGRESS`** (hides the symptom) **and do NOT fix in isolation by persisting the logical
  `_seek_target`** — that path is entangled with the guarded MPV-seek / `_seek_target` invariants
  (CLAUDE.md) and other open mpv-playback issues; user's explicit call is to handle all the mpv
  problems together, not one-by-one, or it opens a can of worms. Blocked on: that batched
  mpv-playback pass being scheduled. When the source fix lands, also write a one-time cleanup that
  zeroes existing sub-threshold `pos_` (config) and `books.progress` (DB) values — they won't
  self-heal. Full writeup + the two mid-investigation misreads (speed-coefficient values, stale
  duplicate `[pos_]` config section) in NOTES.md "Near-zero saved positions show spurious library
  progress". See also DEBT_INVENTORY.md (Stats / library UI).

- **[2026-07-03] DECIDE: excluding the currently-playing book behaves differently for M4B vs VT.**
  Not a bug to fix — a design decision to make later. When the loaded/playing book is excluded
  (user-trash) or flagged missing while playing, single-file **M4B** books keep playing (only the
  library row disappears); **VT** (multi-file MP3) books drop to the no-book-loaded screen. Both
  are "correct" in isolation — the divergence is the open question. Observed while verifying the
  `is_missing OR is_excluded` teardown fix (`a48dc3d`, 2026-07-03); the fix itself is format-
  agnostic (it just decides *whether* teardown fires), so this divergence lives downstream in how
  playback survives an excluded/missing book, not in `_on_scan_finished`. Known and deliberately
  tolerated: an M4B continuing to play a since-removed book hurts nothing and only holds memory
  already loaded, so it's been left as-is. Decide later whether to (a) make both formats keep
  playing, (b) make both drop to no-book, or (c) formally document the split as intended. No action
  until then; captured so it isn't rediscovered as a "bug" and reflexively "fixed."

- **[2026-07-01] Book Detail panel slide-in feels less smooth from Library than from Stats.**
  User observation, unconfirmed and not yet investigated: right-clicking a book row in the Library
  panel to open Book Detail feels janky compared to clicking a book row in the Stats panel to open
  the same panel — same target panel (`open_book_detail` → `_start_book_detail_entry`,
  `panels.py:578`), so if real, the difference is in what's already on-screen underneath, not the
  panel itself. One structural note found while checking: `_start_book_detail_entry` does NOT touch
  `blur_animation` at all (every other `_start_*_entry` — library/settings/speed/stats/sleep/tags —
  starts/stops it), so whatever blur state the currently-open panel left in place just carries over
  unchanged; unclear if that's relevant. User also flagged this may just be "noticing now because
  I'm paying attention" rather than a real regression — needs a clean side-by-side comparison
  before concluding anything. Do not conflate with the sidebar-bleed-through investigation
  (NOTES.md, same date) — confirmed structurally unrelated: Book Detail never routes through
  `_on_sidebar_closed_for_panel` (no sidebar trigger button opens it; it's reached only from
  library rows, stats rows, and tag chips), so that fix does not touch this path at all.

- **[2026-07-01] Theme hover-preview performance pass needed — regressed from a prior fix.**
  User reports theme pool hover-preview (Settings → Themes tab, hovering a theme button to preview
  it) has been sluggish for a while and was previously fixed (\"more than a month ago\") via
  dedicated stylesheets, but has since degraded again for an unknown reason. Could not locate the
  original fix in NOTES.md/SESSION.md by searching for hover-preview performance, dedicated
  stylesheets, or QSS-caching terms — either it predates the retained history or was described
  differently there; **ask the user for the specifics/date before assuming anything about what the
  original fix actually changed.** Needs a full profiling/performance pass on the hover path
  (`_on_theme_hovered` → `_on_theme_changed`, `theme_manager.py`), not a guess-and-patch — likely
  candidates worth checking first: whether per-hover work that should be cached/precomputed is being
  redone on every hover tick, and whether anything added since the original fix (e.g. the
  `tags_panel` mask-exclusion addition, `65b5688`, or other `_apply_stylesheets` dispatch growth) is
  back on the hot path.

- **[2026-07-01] ScrollingLabel first-glyph clipping.** When a chapter name is long enough to scroll,
  the first character ('c', 't', etc.) clips against the widget's left edge at the start position
  (`_scroll_pos = 0`). Qt renders glyphs at x=0 with no left margin and the widget boundary shears
  them. Attempted fixes: `+2` draw offset (fixes left, clips right or leaves a gap), `setClipRect`
  (gaps and clips simultaneously), `leftBearing` compensation (bearing reports 0 for these glyphs so
  no help), `eraseRect`/`fillRect` background clear (causes ghost-text overlap on chapter switch),
  `update()` after `_timer.start()` (same ghost problem). All attempts introduced worse regressions.
  The committed state (`72d80df`) has a visible 2px gap at the start position as the least-bad
  tradeoff. Needs a fresh look — possibly `QTextLayout` instead of raw `drawText`, or a containing
  widget with `setContentsMargins` rather than painting directly.

- **[2026-06-27] Unused imports / dead names flagged by pyflakes in `app.py` and `ui/panels.py`.**
  Pre-existing, not introduced this session (confirmed via `git log -p`), surfaced while checking a
  warning on an unrelated edit. `app.py`: `QModelIndex`, `QRegularExpression` (QtCore),
  `QIntValidator`, `QRegularExpressionValidator` (QtGui), `THEMES` (themes), `ThemeComboBox`
  (theme_manager), `CoverLoaderWorker` (cover_loader), `LibraryPanel` (ui.library), `StatsPanel`
  (stats_panel), `BookDetailPanel` (book_detail_panel), `TagManagerWidget` (tag_manager),
  `BOOK_QUOTES` (book_quotes); also a `QPropertyAnimation` import shadowed by a loop variable at
  app.py:1212. `ui/panels.py`: `QWidget`, `QLabel`, `QPushButton`, `QHBoxLayout`, `QVBoxLayout`,
  `QGridLayout`, `QLineEdit` unused, plus an undefined-name `BookDetailPanel` reference at line 34
  (likely meant to be removed or imported — needs investigation, not just an unused-import deletion).
  Run `python -m pyflakes src/fabulor/app.py src/fabulor/ui/panels.py` to reproduce. Low priority,
  cosmetic/lint-only except the undefined-name one, which should be checked for being a latent bug
  rather than assumed harmless.
- **[2026-06-27] Excluded Books popup (`ui/excluded_books.py`) theming gaps — four issues, found via
  live screenshot comparison on a flamboyant/cyberpunk-style theme:**
  - On at least one such theme, row text and the eye icon are barely visible against the popup's
    `bg_deep` background — needs a per-theme override (or a contrast-aware fallback) for this
    specific theme, not just the popup's general color keys.
  - The popup's `::item:selected` highlight (`dropdown_curr_chap`) and `settings_folder_list`'s own
    selection highlight read as visually inconsistent side-by-side in the same screenshot — different
    colors entirely (not just hue, looks like two different theme keys or fallback paths winning).
  - Corner radius mismatch: the popup's selection highlight is flat/square; `settings_folder_list`'s
    is rounded. Should match (one or the other) since they're both "selected row in a themed list"
    in the same panel.
  - Background color mismatch between the two same-panel list surfaces (popup vs. folder list) —
    they don't read as part of the same design system in a single screenshot even though each looks
    fine in isolation.
  Not urgent — deferred by explicit instruction ("not going to deal with these now"). Revisit
  together as one pass over `excluded_books.py`'s `set_theme` + `themes.py`'s `dropdown_curr_chap`/
  `bg_deep` keys, probably alongside the cyberpunk-style theme(s) that surfaced it.

- **[2026-06-25] Shimmer plays on speed right-click even when speed is already default.**
  `_on_speed_right_clicked` always plays the shimmer animation; it should skip it when current speed
  already equals the default speed, since there's nothing to reset. See NOTES.md "TODO (before
  release): suppress shimmer when speed is already the default" (~line 1006).
- **[2026-06-25] Tag action button's check→delete revert timer can fire mid-edit.** After a tag
  rename, an unguarded `QTimer.singleShot(2000, ...)` reverts the action button's visual state; if
  the user starts a new edit within that 2s window, the revert can fire mid-edit and silently undo
  the in-progress state. Low-priority UX papercut, not a correctness bug. Fix: capture/cancel the
  timer when a new edit starts. See NOTES.md "tag action button check → delete 2s timer" (~line
  1568).
- **[2026-06-25] Cover Panel: no duplicate-cover detection.** Adding the same cover image twice (via
  `_on_add_cover`, cover_panel.py:497) creates redundant files and DB rows with no content-hash or
  size/dimension check. Implement before the 4-slot cap becomes a felt constraint — a duplicate
  wastes a slot. See NOTES.md "Duplicate cover detection not implemented" (~line 2097).
- **[2026-06-25] Pre-release cleanup pass (bundle into one commit, not piecemeal):**
  - Remove the `Q`-key quote-rotation shortcut (`app.py`, testing-only — already flagged inline as
    `# TODO: remove before release — testing only` at app.py:1947).
  - Remove debug `print()`/timing instrumentation left over from VT debugging in `_close_session`,
    `_on_file_ready`, `_on_book_selected_from_library`.
  - Switch the VT playlist-resolution temp files (`ffmetadata`/`concat` in `_resolve_playlist`) from
    `delete=False` to `delete=True` (or add explicit cleanup) once VT is considered stable — they
    currently accumulate in `/tmp` across sessions.
  See NOTES.md "Cleanup Deferrals — Pre-existing, Deliberate" (~line 2108) for all three.
- **[2026-06-25] Re-verify: chapter nav undo/restore near boundaries.** A 2026-05-16 NOTES.md entry
  ("Deferred — chapter nav undo/restore near boundaries", ~line 2087) lists three bugs: Undo doesn't
  appear after Next, Undo after Prev drifts the chapter slider to the far right, and
  `apply_smart_rewind`/Undo restore used raw `time_pos =` assignment in some paths. This predates the
  Session 3 (2026-06-13) chapter-seek precision rework, which unified chapter nav (including
  embedded-M4B clicks) onto `seek_async` with calibrated offsets — these bugs may already be fixed as
  a side effect. Confirm whether they still reproduce before doing any work; if fixed, delete this
  entry instead of carrying it forward.

- **[2026-06-23] Volume slider/muted icon don't accept wheel-scroll while visible.** Only
  `visual_area` (the cover art) currently handles volume wheel events (`wheelEvent` in `app.py`).
  Scrolling directly over the volume slider or the muted icon while either is visible/showing is a
  no-op, which is surprising — muscle memory expects scrolling over a volume control to adjust it,
  especially right after it's been shown. Needs care: if the empty space *around* where the slider
  appears (within `vol_stack`'s 104×24 box) also accepts scroll, that could itself feel inconsistent
  once the box is empty/hidden again. Decide the exact hit-region before implementing.
- **[2026-06-23] Slider→muted-icon transition is abrupt.** When volume hits 0% with no sleep timer
  active, `_show_volume_overlay` jumps straight to the muted icon with no transition (see
  `ed563a4`/`81734d3` — this was a deliberate choice to skip the slider preview, not an oversight).
  Visually it reads as a hard cut. Idea floated: a quick two-sided mask/wipe that conceals the
  volume bar first, then reveals the muted icon, rather than an instant swap. Needs a concrete
  animation design before implementing — not just "add a fade."
- **[2026-06-23] Clicking the muted icon (and a future `M` key) should restore volume — to what
  value?** Naive "restore to 100%" is probably wrong. Likely wants the same kind of "value before
  manipulation started" capture that `Player.save_seek_position`/`undo_seek` already use for
  seeking (one-level undo, captured at the start of a manipulation). Needs its own capture point
  for volume — probably at the first wheel/drag/key event of a manipulation "session," not on every
  change. Design this alongside the `M` key shortcut, not before — see git history around
  `ed563a4` for the muted-icon work this builds on.
- **[2026-06-23] Arrow-key volume control (if/when added) must integrate with the auto-hide timer
  the same way wheel/click/drag do.** Whatever wires up arrow keys for volume needs to call through
  the same path as `_on_volume_changed`/`_show_volume_overlay` (see `64e75cc`), not a separate one —
  otherwise the overlay could disappear mid-keypress the same way dragging used to before that fix.

- **[2026-06-19] Remove theme inheritance from "The Color Purple."** Every theme currently resolves
  via `_resolve_theme()` as `THEMES["The Color Purple"].copy()` overlaid with the requested theme's
  own dict — any key a theme doesn't define falls back to Purple's literal value, not to that
  theme's own derived fallback (e.g. an accent-derived color). `_NO_BASE_INHERIT_KEYS` in
  `themes.py` is a manually-maintained escape hatch for keys where this is wrong, and it's easy to
  forget to update when adding a new optional key (see CLAUDE.md rule on `_NO_BASE_INHERIT_KEYS`,
  added 2026-06-19). Made sense early when Purple was a stable default; doesn't anymore — Purple
  probably won't even ship as the default theme. Target design: no theme inherits literal values
  from another theme; every key is either required (defined in all themes) or has a documented
  code-level fallback chain, never "whatever the base template happened to set."
  **Blocked on:** user's planned full pass over every theme (adding keys where current fallbacks
  don't look right) — doing the inheritance refactor before that pass would only have a partial
  picture of which keys actually need it. Revisit once that pass is done.

## In Progress

(none)
