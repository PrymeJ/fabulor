# TODO Archive

Closed, fixed, verified, and superseded entries moved out of [TODO.md](TODO.md) to keep the active
list scannable. Kept, not deleted, per the project's normal practice of not throwing away detail
that isn't fully duplicated in NOTES.md/SESSION.md/a commit message. Order is the same relative
order these entries had in TODO.md before the split (2026-07-30).

- **[2026-09-15, scope corrected 2026-09-17, design settled + IMPLEMENTED 2026-09-19] Book Detail
  panel's Tags tab tag chip grid gained full keyboard navigation.** Design was walked through
  directly by Pryme and confirmed via AskUserQuestion, then implemented the same day against it:
  Down enters the chip grid at the first chip; Left/Right wrap reading-order across rows (past a
  row's last chip, Right continues onto the next row's first — same convention
  `_handle_themes_swatch_arrows` established for the Themes swatch grid); Up/Down move
  column-aware to the row above/below, clamped to a shorter row's own length, derived from real
  `FlowLayout` geometry (`_tag_chip_rows()`, groups by `chip.y()`); the tag-add text field stays
  explicitly OUT of arrow reach at every boundary (Tab only); Right/Down off the LAST chip reaches
  "Tag management" (Up/Left returns) — the one boundary that continues past the grid rather than
  wrapping within it; Del removes the selected chip's tag via the exact same `_on_remove_tag` the
  mouse's × button calls; Space/Enter filters via the exact same `tag_filter_requested` signal and
  inert-tag exclusion (`_tag_chip_is_clickable`) a mouse click uses; digits 1-5 jump straight to
  the Nth chip. A "G opens Tags panel" shortcut was considered and explicitly dropped per Pryme's
  own call. New `_TagChip` class (replacing a bare `QWidget()` chip construction) holds a
  `keyboard_selected` property; "Tag management" is tracked via a plain flag
  (`_tag_manager_kbd_selected`), NOT real Qt focus — granting it real focus would have silently
  stopped `BookDetailPanel.keyPressEvent` from ever firing again (this class doesn't use Qt's
  native per-widget focus/Tab order at all), a real mechanism problem caught before it shipped.
  Neither the chip grid nor "Tag management" can use the traveling marker (neither ever holds
  real Qt focus, so the marker — which only traces real focus — has nothing to trace under either
  keyboard-nav style) — found live immediately after first shipping ("neither fill nor marker
  works"), fixed with a dedicated `QWidget#tag_chip[keyboard_selected="true"]` QSS fill, the same
  structural answer the Themes swatch grid already has for the identical gap. New
  `tests/test_book_detail_tag_chips_keys.py` (22 tests) exercises the real navigation logic
  against genuine multi-row `FlowLayout` geometry — a first draft's zero-size test chips silently
  made every "multi-row" test meaningless (FlowLayout placed everything on one row regardless of
  container width) until caught by directly inspecting chip geometry rather than trusting the
  tests passing. The panel's tab bar itself was intentionally left OUT of scope (not wired into
  the shared `_kbdnav_active_panel_key` mechanism) — see TODO.md's own still-open entry for that
  narrower, unrelated gap. Commit `1a268a7`.

- **[2026-09-18, FIXED same day] REGRESSION: cover-art-theme hover previewed spuriously with no
  mouse hover at all — same-day regression of the hover-from-Off fix (`5f0c45c`).** Root cause:
  `_on_cover_pool_btn_hovered` applied its preview SYNCHRONOUSLY, with no debounce, unlike every
  theme swatch (which queues through `_hover_debounce_timer`, 150ms, via `_on_theme_hovered`/
  `_fire_pending_hover`). Harmless while this method only had a no-op branch for "no cover theme to
  preview," but became a real bug the moment the Off-mode preview branch gave it something to
  actually apply on every hover — a brief, unintended pass-over now committed the preview instantly.
  Pryme's own diagnosis pinned it precisely: "When I pass over the theme swatch quickly, they don't
  trigger as they have a guard for, I think, 80ms. But the cover art theme doesn't have it." Fixed
  by routing `_on_cover_pool_btn_hovered` through the exact same `_pending_hover_theme`/
  `_hover_debounce_timer` queue the swatches use — `_on_theme_changed` and `_fire_pending_hover`'s
  trailing keyboard-hover reassert already accept either a theme name or a dict, so this was a
  drop-in fix, not a new mechanism. Live-confirmed by Pryme. Commit `5757f4e`.

- **[2026-08-03, FIXED 2026-09-18] `af command error` on Audio-tab mono/swap/balance — root cause
  was mpv's native `pan` filter shadowing ffmpeg's filter of the same name.** Mono, Channel swap,
  and L/R balance all threw `('Error running mpv command', -12, (...))` (`mpv.ErrorCode.COMMAND`)
  and produced no audible effect whatsoever — confirmed live against a real `ao='pulse'` mpv
  instance (a `/dev/zero`/`ao='null'` isolated repro attempt masked the bug entirely and returned
  success, which is why it wasn't caught by any earlier isolated test). Root cause: mpv ships its
  own NATIVE `pan` filter (legacy MPlayer libaf, different coefficient syntax) alongside libavfilter's
  `pan` of the identical name — `Player.apply_audio_processing`'s unqualified `pan=...` string with
  ffmpeg-style `c0=.../c1=...` options resolved to mpv's native filter and was rejected outright.
  Fixed by wrapping every `pan=...` filter string as `lavfi=[pan=...]`, which routes explicitly
  through libavfilter. `equalizer=...` (used by voice_boost, and later the new EQ bands below) was
  never affected — no name collision for that filter. Commit `97b5b38`.

- **[2026-09-17, FIXED 2026-09-18] "A working parametric EQ in the Audio tab" — shipped as a 5-band
  fixed-frequency EQ, explicitly NOT fully parametric, per Pryme's own confirmed choice.** Replaced
  "Speech compression (Normalization)" to reclaim panel space. 5 bands (100/300/1000/3000/8000 Hz —
  rumble, warmth, presence, sibilance, air) tuned for narration rather than music, ±6dB at 0.1dB
  resolution. Reused the already-working `equalizer=f=...:width_type=o:width=2:g=...` syntax
  voice_boost relies on; a band within 0.01 of 0.0dB is omitted from the filter chain entirely.
  `Config.get_norm_enabled`/`set_norm_enabled` deliberately left in place, unused (cheap, preserves
  a clean re-add path, avoids an orphaned QSettings value with no getter). Layout iterated across
  three live-feedback rounds (packed narrow sliders → rejected; one full-width slider per row with
  balance moved below → close but one header silently wrapped to two lines; final shape confirmed
  correct). New `tests/test_audio_processing.py`, 10 tests. Commits `119a2e6`, `1cc3ba9`.

  **A pre-existing, silent tab-to-tab spacing drift was found and fixed in the same pass, unrelated
  to the EQ itself.** `#settings_header`'s un-pinned height varied 1-2px per label purely from
  font-metric descenders, independent of available space or group count — proven, not assumed, via
  a live empirical test (temporarily padding the spacious Controls tab with 5 dummy groups to see if
  it also drifted once it had as many groups as the tighter-looking Look tab; it did, ruling out
  space-driven compression as the mechanism). Fixed via `min-height`/`max-height: 18px` on the
  Settings panel's own `#settings_header` QSS rule. A second, independent outlier (the Themes tab's
  Off/With pool/Exclusive row having its own explicit `setSpacing(4)`/zero-margin override, the only
  button row across all Settings tabs with one) was found and fixed the same pass. Commit `b4f1325`.

- **[2026-09-17, FIXED 2026-09-18] Settings' Off/On toggle button order was inconsistent across the
  panel — audited every pair, fixed the two real default mismatches, left the rest as-is.** Full
  inventory (17 toggles/ramp rows across Audio, Appearance, Library, Controls, Sprint, Sleep, Stats'
  ⚙, and Playback) found two genuine families rather than one inconsistent mess: literal Off/On
  toggles split roughly 50/50 between Off-left and On-left with no rule, while every named-option
  pair (Stereo/Mono, Embedded/.cue, By name/By index, Traveling/Fill, Auto-play/Jump only) already
  puts its default on the left with zero exceptions.

  Pryme's own review of the inventory: most of the "inconsistency" is acceptable as two distinct,
  internally-consistent conventions (Off-left toggles that also happen to match "default on the
  left," e.g. Compression/Voice boost/Cover-art-based theme/Backward seek compensation) — not a bug.
  Theme hover fade starts Off but Off isn't its default; explicitly left as-is, not made default.
  Three items were real and fixed:
  1. **Chapter notches** — labels were `["On","Off"]` but the actual default was `False`/Off, so
     the highlighted default sat on the right while every other On-left toggle has its default on
     the left. Fixed by flipping the config default to `True` (`config.py`,
     `get_chapter_notches_enabled`).
  2. **Persist search filter** — button order changed from `["Off","On"]` to `["On","Off"]`
     (`main_window_builders.py`), and the master toggle's config default flipped `False`→`True`
     (`config.py`, `get_persist_filter_enabled`). The Tag/Text/Year sub-filters already defaulted
     to selected individually, so the net effect is On by default with all three sub-filters
     selected, as asked — the pre-existing self-correcting guard (master forced back Off if none of
     the three sub-flags are set) stays intact and is now simply never triggered by the defaults.
  3. **Stats ⚙ Default timeline view** — the only toggle on the whole panel where the left slot
     ("Streak") was the NON-default option (`"heatmap"` was the real default). Fixed by flipping
     the config default to `"streak"` (`config.py`, `get_default_timeline_view`).

  A fourth, unrelated live ask surfaced during the same investigation: the "Day starts at" spinbox
  displayed a bare `0`–`23` instead of an hour ("0:00"–"23:00"). Fixed via `textFromValue`/
  `valueFromText` overrides on `_ThemedSpinBox` (display-only — the stored/emitted value stays a
  plain int, config/signal wiring untouched) — confirmed live. A follow-up ask (remove the
  full-text-selection flash on arrow-click/keyboard-focus) was fixed via `stepBy`/`focusInEvent`
  overrides calling `lineEdit().deselect()` — `QAbstractSpinBox.stepBy` selects the full text
  AFTER updating the value, so a naive `valueChanged`-connected deselect gets clobbered; the fix
  had to run after `super().stepBy()` instead. A further ask (remove the read-only field's blinking
  text caret) was attempted twice and reverted both times: `setReadOnly(True)` also silently blocks
  the up/down arrow buttons (confirmed via a real dispatched-click test, not assumed — Qt's
  `ReadOnly` flag is documented as guarding only the `QLineEdit`'s own typed-input path, but that
  documentation understated its actual scope); a second attempt swallowing the line edit's
  `QEvent.Type.Timer` events (theorized as the blink-driving timer) preserved arrow functionality
  but was confirmed live NOT to stop the blink — the assumption about which timer drives the caret
  was wrong. No further attempt made; Pryme's call to leave the caret as-is (Qt exposes no public
  caret-color API separate from `QPalette::Text`, which the visible digits also use, and no
  `setCursorBlink`/`setCursorVisible` method in this Qt build — genuinely no safe lever available).

  Also this session: Playback defaults changed — speed increment (step) `0.1`→`0.05`, skip duration
  `10s`→`5s` (both `config.py`; both values were already present as existing UI button options in
  `speed_controls.py`, `[0.05, 0.1, 0.25, 0.5]` and `[5, 10, 15, 30]` respectively, so no UI code
  change was needed beyond the config default).

  A second, duplicate TODO.md entry ("Chapter label scroll has a 2px gap on the left before
  scrolling starts") was also removed in this pass — confirmed to be the same ScrollingLabel
  first-glyph-clipping bug the entry itself flagged as a likely duplicate, already closed as
  accepted debt earlier the same session (see NOTES.md, 2026-09-18 — not TODO_ARCHIVE, since that
  bug was never fixed, only investigated and abandoned).

- **[2026-08-08, CLOSED as won't-fix 2026-09-18] Stats archived-book cover dimming — turned out to
  be a grayscale treatment, not an opacity tuning problem, and the underlying code this item
  described no longer exists anyway.** The original entry cited `StatsRowDelegate.paint()`'s
  `painter.setOpacity(0.4)` as too faint against `BookDayRow`'s dimming, plus a suspected GC bug in
  `BookDayRow._dim_effect()`'s bare `QGraphicsOpacityEffect`. Both `BookDayRow` and that opacity
  mechanism were fully removed by the 2026-08-05/09 Stats lazy-delegate migration (see CLAUDE.md's
  Stats Panel section) — current code (`to_grayscale()`/`_cover_pixmap`/`_grayscale_cache` in
  `stats_panel.py`) desaturates archived covers to grayscale, not opacity, so the entry was stale
  before it was even reachable.

  Live-tested 2026-09-18 with real screenshots across four Day-view months: Pryme could reliably
  spot the grayscale treatment on covers with real color, but confirmed two genuinely
  indistinguishable false leads along the way — a small corner "icon" on a couple of covers
  (Solaris, Blood of Amber, The Tunnel) turned out to just be those covers' own naturally
  monochrome artwork, not an archive marker. The actual, load-bearing finding: **a cover that is
  already near-monochrome by design (Death and the Dervish, Auto-da-Fé) renders visually identical
  archived vs. not** — grayscale has nothing left to change on an already-grayscale image. Pryme
  confirmed this is a genuine dead end, not a tuning problem: adjusting opacity instead would look
  bad on covers generally, and a badge overlay was explicitly rejected. Closed as an accepted
  limitation — no fix exists that doesn't trade one problem for a worse one.

- **[2026-09-17, FIXED 2026-09-18, live-confirmed by Pryme] Book Detail's Tags-tab tag-add field —
  five distinct completer bugs, all filed as one detail-free placeholder ("priority but not yet
  reproduced") and all fully diagnosed and fixed in one session once Pryme actually walked through
  the reproduction.** Real screenshots and precise step-by-step reports this time, not a vague
  symptom — see the git log for the exact wording of each.

  1. **Query capped at 10 results regardless of how many tags actually matched a prefix**
     (`db.py`'s `get_tag_suggestions`, `LIMIT 10`). A broad shared-namespace prefix like `"ai:"`
     silently hid every match past the first 10 alphabetically. Raised to `LIMIT 50` — the app's
     own global unique-tag cap (`add_book_tag` enforces it), so every match is now always
     returned regardless of prefix breadth. Zero-risk, one-line fix.
  2. **Typing a more specific prefix right after a broader one could show zero matches for a
     genuinely valid tag** (e.g. "ai:" → "ai: s" briefly showed nothing, even though "ai: scott
     brick" matches). Root cause: Qt's own `QLineEdit`/`QCompleter` wiring re-filters the popup
     IMMEDIATELY on every keystroke against whatever the model currently holds — before this
     app's 200ms debounced DB re-query has a chance to fetch the correct, fresh result set for
     the new prefix. Fixed by calling `self._tag_completer.complete()` explicitly after each
     debounced model update, forcing Qt to re-run completion against the NEW model rather than
     leaving the popup showing a stale filter pass.
  3. **The dropdown wouldn't grow back to fit more results after narrowing then widening the
     search** (backspacing showed a scrollbar instead of a taller popup). Same root cause and
     same fix as #2 — `QCompleter` does not automatically recompute popup geometry when its
     model's row count changes while already visible; the explicit `complete()` call above forces
     that recomputation too.
  4. **Tab while typing wiped the text but left what looked like a stuck cursor, and typing again
     was broken or limited to one character.** Confirmed directly via an isolated Qt test
     (`QLineEdit`+`QCompleter`, not assumed): `clearFocus()` does NOT close an already-open
     `QCompleter` popup — it stays visible, orphaned, floating over the now-cleared/defocused
     field. The "stuck cursor" was this leftover popup, not the `QLineEdit`'s own caret. Fixed
     by calling `self._tag_completer.popup().hide()` explicitly in `_clear_tag_input()`
     (`book_detail_panel.py`), the shared "leave the field" action Tab-away and Escape both use.
  5. **Down/Up arrow navigation through the suggestion popup "quickly selects one as if I
     clicked/pressed Enter on it."** The trickiest of the five — two investigation rounds:
     - **First theory (independently correct, but NOT the actual cause — confirmed by live
       retest making no difference):** `_ensure_panel_owns_focus()` (runs on every keypress) uses
       `isAncestorOf` to detect focus drifting outside the panel — a `QCompleter` popup is a
       genuine top-level `Qt.WindowType.Popup` window, never a widget-tree descendant, so it
       reads as "outside" exactly like any other popup (same shape as this panel's/Tag Manager's
       own documented `safe`-allowlist gotcha, see CLAUDE.md's "Keyboard focus ownership"
       consequence 5). Added a `QApplication.activePopupWidget()` guard, mirroring the existing
       `activeModalWidget()` guard for the file-dialog case. Kept in the final code as
       independently correct, but its docstring now explicitly says it did NOT fix this bug,
       since Pryme confirmed live (tested with the backdrop set to Transparent to rule out blur
       too) that it made no difference.
     - **Real cause, found via temporary `[TAGCOMPLETE-TRACE]` log instrumentation rather than a
       third guess** (per CLAUDE.md's "never substitute a plausible explanation for a checked
       one" rule) — confirmed first that NO `activated` signal or `_on_add_tag` call EVER fired
       on an arrow press (ruling out literal accidental selection), then caught the actual
       mechanism directly in the log: a Down press was followed ~193ms later by
       `_do_tag_suggestions firing... text='ai [listened]' suggestions=1`. Arrow-key navigation
       through a `QCompleter` popup writes the highlighted row's full text into the line edit as
       an inline preview — standard, documented Qt behavior — and `_on_tag_input_changed` had no
       way to tell that apart from genuine typing, so it restarted the 200ms debounce timer for
       the preview text too. 200ms later, `_do_tag_suggestions` re-queried the DB using the FULL
       PREVIEWED TAG STRING as the search prefix, which of course matched only that one tag,
       collapsed the suggestion list to 1 result, and reshaped the popup — visually reading as
       "the arrow key just picked something," even though nothing was ever actually selected or
       added. Fixed by connecting `QCompleter.highlighted` (fires exactly when the inline preview
       is written, before the resulting `textChanged`) to set a one-shot flag
       (`_tag_input_change_from_completer`) that `_on_tag_input_changed` checks and consumes,
       skipping the debounce restart for that one call only — a genuine keystroke immediately
       after still restarts it normally.

  All five fixes committed together with the diagnostic trace stripped back out once the real
  cause was confirmed (`3794231` for #1/#2/#3, `5de212c` for #4/#5, `e2014cf` for the one test
  fixture update carried along with #4). Full pytest suite green throughout; `pyflakes` clean.
  **Live-confirmed fixed by Pryme** for all five, in two rounds — #1-#3 confirmed together, #4
  confirmed separately, then #5 needed the deeper trace-based investigation above before it
  actually resolved.

- **[2026-06-27, re-verified 2026-09-17, FIXED 2026-09-18] Pyflakes: unused imports across 15
  files, plus the `BookDetailPanel` undefined-name reference in `ui/panels.py`.** Pryme's own
  framing going in: "not urgent, and something technically totally for you, not requiring me" —
  low-risk, deletion-only cleanup, done in one pass rather than left open indefinitely.

  Removed ~30 dead imports total (confirmed via `python -m pyflakes src/fabulor/` plus a `grep` of
  each name across its own file before deleting, to rule out a string-quoted type annotation or
  other non-obvious use pyflakes wouldn't see): `app.py` (`QModelIndex`, `QRegularExpression`,
  `QIntValidator`, `QRegularExpressionValidator`, `THEMES`, `ThemeComboBox`, `CoverLoaderWorker`,
  `LibraryPanel`, `StatsPanel`, `BookDetailPanel`, `TagManagerWidget`, `BOOK_QUOTES`),
  `library/scanner.py` (`Qt`), `flow_layout.py` (see below), `carousel.py` (`Qt`),
  `cover_panel.py` (`os`, `QSizePolicy`, `QBrush`, `save_cover_image`, a dead local
  `import tempfile, shutil`), `text_context_menu.py` (`QEvent`), `title_bar.py` (`QPixmap`),
  `book_detail_panel.py` (a dead local `QColor` import), `speed_controls.py` (`THEMES`),
  `theme_manager.py` (`QPushButton`, `QWidget`), `tag_manager.py` (`QImage`), `stats_panel.py`
  (`QEnterEvent`), `library.py` (`QWidget`, `QLabel`, `QGridLayout`, `QProgressBar`, `QDateTime`,
  `QCoreApplication`), `panels.py` (`QLabel`, `QPushButton`, `QVBoxLayout`, `QLineEdit`), and
  `models/book.py` (`field`, `asdict`).

  **The `BookDetailPanel` reference was real, not a lint-only nuisance** — `panels.py`'s
  `self.book_detail_panel: "BookDetailPanel | None" = None` had NO backing import anywhere in the
  file, string-quoted so it never raised at runtime, but genuinely unresolvable by any static
  tooling. Fixed with a `TYPE_CHECKING`-guarded import (`if TYPE_CHECKING: from .book_detail_panel
  import BookDetailPanel`) — confirmed no circular-import risk first (`book_detail_panel.py` does
  not import `panels.py` or anything that does).

  **A second, structurally identical latent bug was found and fixed in the same pass, NOT in the
  original TODO entry's list** — `flow_layout.py`'s `horizontalSpacing()`/`verticalSpacing()`
  referenced a bare `QStyle` name that was only ever imported LOCALLY inside a different method
  (`_smart_spacing`), so those two methods would raise `NameError` if Qt's layout engine ever
  called them directly rather than routing through `_smart_spacing` first — genuinely undefined,
  not just an unused-import false alarm. Moved the `QStyle` import to module level.

  Every touched module import-checked directly (`import fabulor.<module>` for all 15) in addition
  to `pytest tests/ -q` (green) and `py_compile` — Pryme's own live check was "the app is loading
  correctly with no errors in the terminal," which this matches. Commit `e2df6ac`.

- **[2026-09-09, FIXED earlier — 2026-09-06 and 2026-09-10 — closed 2026-09-18, live-confirmed by
  Pryme] Two keyboard-nav consistency gaps that were already fixed before this entry was even
  filed, and just never got moved out of TODO.md.** Both items were logged 2026-09-09 as "not yet
  investigated," but reading the actual code this session found each one had a fix already
  committed with its own detailed root-cause comment still sitting in place — the TODO entry had
  simply gone stale rather than being closed at the time.

  **Settings' Themes-tab interval options had no Tab-focus indicator** ("Tab in Settings doesn't
  underline the interval options. Enter selects them, but they are never indicated"). Fixed
  `3015945`, 2026-09-06 — three days BEFORE this TODO entry was filed. `themes.py`'s
  `QWidget#settings_panel[kbdnav="true"] QLabel#theme_interval_label:focus { border-bottom: ... }`
  rule is the real fix; its own comment already documents that `text-decoration: underline` was
  tried first and confirmed inert on `QLabel` via direct offscreen pixel comparison, with
  `border-bottom` used instead as the actual working substitute. Live-confirmed by Pryme this
  session with a screenshot showing "5" underlined while tabbed to.
  **Speed panel's Tab order skipped Default Speed until after Smart Rewind.** Fixed `e3e8145`,
  2026-09-10 — one day after this entry was filed, evidently without the entry being closed at the
  time. Root cause, per that commit's own comment in `panels.py`'s `panel_tab_widgets`: Speed's
  Default Speed row is deleted and rebuilt on every panel open (`_rebuild_def_speed_row`, called
  from `_start_speed_entry`), so its buttons become the NEWEST entries in Qt's internal
  child-object list — `findChildren` order reflects recreation order, not layout order, the
  moment anything in the panel gets rebuilt after construction. Arrow-key navigation was already
  immune (`flat_panel_rows` reads the real `QVBoxLayout`/`QHBoxLayout`/`QGridLayout` structure via
  `itemAt`, not `findChildren`) — Tab was the only consumer still using the fragile walk. Fixed by
  making `panel_tab_widgets` delegate to `flat_panel_rows` for Speed/Sleep/Sprint instead of its
  own `findChildren`-based walk.

  Both closed on Pryme's own confirmation this session ("Both fixed") rather than fresh
  diagnosis — the investigative work here was locating the pre-existing fixes and their commits,
  not producing new ones.

- **[2026-09-08, FIXED 2026-09-18, not yet live-verified by Pryme] Library keyboard nav didn't
  yield to mouse hover during pagination, and its 1-per-row keyboard-selection tint used its own
  separate color instead of matching mouse hover.** Reported as the Library-specific instance of
  the 2026-09-15 hover-pickup/most-recent-input-wins pass, which had deliberately NOT extended to
  Library: "Library doesn't get it correctly either. Pagination makes it jump to the mouse."
  Pryme's own framing of the underlying principle, worth keeping on record: "Make the keys pickup
  from where the mouse is, and make the keys win unless the mouse hovered over something else.
  This principle should be observed throughout the app with a holistic approach."

  Precise symptom, from Pryme directly: "if the mouse is hovering and stationary over any row
  that is not the first or the last row, that row is visited after pressing up or down keys
  depending on the direction. The same for PgUp and PgDn. Mouse already on the last row, going
  down is smooth and straightforward. Some other row, it jumps there, making you have to press
  PgDn twice." Root cause: `LibraryPanel._on_view_entered` (Qt's `entered` signal) treated every
  call as genuine mouse intent and unconditionally reassigned `currentIndex()` — but `entered`
  also re-fires when `scrollTo()` moves content underneath a PHYSICALLY STATIONARY cursor, which
  is exactly what every keyboard page/line move does (`_flash_keyboard_selection`/
  `_flash_keyboard_selection_list`'s own `scrollTo(index)` call). A keyboard PageDown would move
  `currentIndex` correctly via Qt's native handler, then immediately have it silently overwritten
  by a synthetic `entered` call resolving to whatever row the mouse geometrically ended up over
  after the scroll — explaining both "jumps to a mid-list row" and "press PgDn twice" (the first
  press's real effect was immediately clobbered).

  Fixed by porting `StatsRowListView`'s already-proven jitter-tolerant poll mechanism
  (`stats_panel.py`, itself built for this exact bug shape) to `LibraryPanel`, in shape rather
  than reinvented: `_enter_kbdnav_hover_mode()` (called once, from `_on_keyboard_nav_moved` — the
  single choke point every keyboard-driven `currentIndex` change already routes through) arms an
  anchor at the cursor's current position and silences `_on_view_entered` entirely; a repeating
  60ms poll (`_on_kbdnav_hover_poll`) is the ONLY path that can hand hover back to the mouse, and
  only once the cursor has moved past a 3px jitter tolerance AND rests over a real, different row.
  Confirmed the ordering is safe: native `QListView.keyPressEvent` (which does NOT itself scroll,
  since `setAutoScroll(False)` is set) runs before the poll is armed, but the actual `scrollTo()`
  call — the thing that can trigger a spurious `entered` — happens inside
  `_flash_keyboard_selection[_list]`, called from `_on_keyboard_nav_moved` AFTER the poll is
  already armed. This also resolves a second symptom filed nearby in TODO.md ("`Alt+Enter` opens
  the book under the mouse rather than the keyboard-selected one" and "PageUp/PageDown produce two
  highlights") — both were the same root cause (`currentIndex` being silently stolen by a stray
  `entered` call), not separate bugs.

  **Second, smaller fix bundled into the same investigation, confirmed by Pryme directly**: of the
  five view modes, only 1-per-row still had its own separate keyboard-selection tint
  (`library_item_keyboard_color`/`_alpha`, default `accent`/0.25) — List already reuses the
  mouse's own hover-fade mechanism, and 2-per-row/3-per-row/Square dropped their own tint back in
  2026-07-09 in favor of reusing the same duration/progress overlay mouse hover already shows
  ("2, 3 and 4 modes don't actually have similar highlights. They activate the overlay, which
  works as the focus indicator" — Pryme's own confirmation this session). 1-per-row's
  `_kbd_base_color` now derives from `library_item_hover_color`/`_alpha` (the SAME style/alpha
  mouse hover uses) instead of the separate keyboard keys, which no theme dict ever actually set —
  they were pure dead fallback-to-`accent` the whole time. The two dead keys were removed from
  `themes.py`'s doc block; no theme dict entries existed to remove.

  Both fixes committed together (`9058136`). Full pytest suite green. **Not yet live-verified by
  Pryme** — both are exactly the class of change (visual color, and a live mouse/keyboard
  interaction bug) that needs eyes on the real running app, not just tests, per CLAUDE.md's own
  rule on visual/interaction matters.

- **[2026-08-09, FIXED 2026-09-18, live-confirmed by Pryme] Stats Day/Week/Month row title elision
  truncated well before the row's real right edge, even when nothing else on that line needed the
  space.** Confirmed visually by Pryme comparing Week and Month side by side: "Blood of Amber: The
  Chronicl..." (Week) vs. "...Chronicle..." (Month), "David Foster Wall...". Not a migration
  regression — `_STATS_TITLE_WIDTH`/`_STATS_AUTHOR_WIDTH` (fixed pixel budgets, `stats_panel.py`)
  predate the Day/Week delegate migration; it only became visible from direct side-by-side
  comparison once multiple tabs were showing the same books.

  The TODO entry originally called for porting Library's full invasive elision (title/author share
  space dynamically, with a further hover-expand interaction). Asked Pryme directly whether he
  wanted that full mechanism or a simpler fix scoped to just the truncation complaint — he chose
  the simpler option: no hover-invade added to Stats rows, just let title/author use real free
  space instead of a fixed cap.

  **First attempt was a live-confirmed no-op — root cause was mis-scoped.** `title_w`/`author_w`
  were widened from `min(_STATS_TITLE_WIDTH/_STATS_AUTHOR_WIDTH, ...)` to
  `min(content_w - trailing_budget, max(_STATS_TITLE_WIDTH/_STATS_AUTHOR_WIDTH, real_text_width))`
  — the fixed constants became a floor instead of a ceiling. Pryme reported no visible change.
  Root cause: `trailing_budget` was still the fixed `CLOCK_W`(50px)/`PROG_W`(98px) constants, and in
  a real row (measured 186px `content_w`) `content_w - SPACING - CLOCK_W` (130px) was already *below*
  the old fixed title cap (134px) — so `min(title_max, ...)` was clamped down by `title_max` before
  the new floor logic ever had anything to expand. The actual waste was never the title's own cap;
  it was `CLOCK_W`/`PROG_W` reserving their full fixed budget regardless of how much space the real
  clock/prog text ("14m" vs. the 50px budget sized for "23h 59m") actually needed.

  **Real fix**: `clock_w`/`prog_w` are now `min(CLOCK_W/PROG_W, max(floor, real_text_width + 2))` —
  sized to the row's ACTUAL clock/prog text, floored (`_STATS_CLOCK_MIN_WIDTH=30`,
  `_STATS_PROG_MIN_WIDTH=40`) so a short/empty string can't collapse the column to near-zero and
  crowd the title against the row edge — and `title_max`/`author_max` are computed from these real
  (not fixed) trailing widths. Confirmed safe against the original 2026-08-09 anti-jitter rationale
  for the fixed constants: `clock_rect`/`prog_rect` are always anchored so their RIGHT edge sits at
  `content_x + content_w` regardless of `clock_w`/`prog_w` (right-aligned text within a
  variable-width, fixed-right rect), so the numeric columns' visible right edge never shifts row to
  row — only the title/author's own elision boundary varies, which is the intended effect. Also
  removed a duplicate `clock_seconds`/`prog_text` computation that existed twice in the original
  code (once for layout, once for painting) by computing each once and reusing it.
  `QFontMetrics` added to the module's top-level Qt import.

  Full pytest suite green, no regressions. **Live-confirmed by Pryme** after the second fix.

- **[2026-09-17, FIXED 2026-09-18] Sleep timer's end-of-chapter mode never faded out — timed
  mode's fade ratio is a function of wall-clock time remaining; end-of-chapter mode had no
  equivalent at all, snapping straight from full volume to pause the instant it fired.**
  Design worked through with Pryme before writing any code, specifically around the friction he
  raised directly: what happens if the user seeks within the anchor chapter WHILE a fade is
  already showing (e.g. skips from 5 minutes left to 1 minute left) — the naive answer ("nothing,
  the fade just wasn't tracking position at all") was the actual bug.

  **Design, three decisions made explicitly before implementing:**
  1. The fade ratio recomputes fresh every 200ms tick from live `player_pos` vs. the anchor
     chapter's own end — mirrors timed mode's `remaining / effective_fade` exactly, just measured
     in playback position instead of wall-clock seconds. This makes both seek directions correct
     by construction: a forward seek within the chapter (Pryme's exact scenario) makes the very
     next tick more faded; Pryme confirmed a backward seek should let the volume recover too,
     rather than being a one-way ratchet once dipping starts.
  2. Pryme's own follow-up question surfaced a second real gap: what if the chapter is shorter
     than the configured fade duration, or end-of-chapter is armed with very little of the
     chapter left? Timed mode already has an answer for the equivalent case —
     `effective_fade = min(_current_sleep_fade, _total_timer_duration)`, capping the fade window
     at the timer's own total length so an over-long fade setting can't produce a below-zero or
     instant-near-silent start. End-of-chapter mode needed the same cap, but there's no fixed
     "total duration" — added `_sleep_eoc_distance_at_arm` (`anchor_end - player_pos` at the
     moment Sleep is armed), the direct positional mirror of `_total_timer_duration`.
  3. Whether a backward seek PAST the original arm point should reopen a wider fade window (a
     fresh, larger cap) or leave the original cap frozen — decided to freeze it for the whole arm
     cycle, exactly matching how `_total_timer_duration` itself is set once at arm time and never
     recomputed for timed mode either. One consistent rule between the two modes.

  **Implementation** (`sleep_timer.py`): `_sleep_eoc_distance_at_arm` set in
  `_do_arm_sleep_timer`'s `end_of_chapter` branch (reusing `update_timer_state`'s own
  `anchor_end` derivation — next chapter's start, or total duration if the anchor is the last
  chapter), cleared in `disable_sleep_timer` alongside `_sleep_eoc_anchor`. `update_timer_state`'s
  EOC branch gained an `else` off the existing `reached_end` check, computing
  `remaining = anchor_end - player_pos` and `effective_fade = min(_current_sleep_fade,
  _sleep_eoc_distance_at_arm)` then `set_fade_ratio(remaining / effective_fade)` when within the
  window — same shape as timed mode's fade block, deliberately not a shared helper (the two
  differ in what "remaining" and the cap actually are, and the existing code doesn't share one
  between them either).

  New regression test (`tests/test_sleep_eoc_fade.py`, 5 tests, no Qt/mpv — binds the real
  unbound `update_timer_state`/`_do_arm_sleep_timer`/`disable_sleep_timer` methods to a
  lightweight fake, the same pattern `test_book_detail_panel_keys.py` uses for widgets too
  expensive to construct for real in a unit test) pins all three decisions: forward-seek fades
  further, backward-seek recovers, the arm-time cap holds even against a backward seek past the
  arm point. Full suite green (`pytest tests/`, no regressions). Not yet live-verified by Pryme —
  next real sleep-timer session should confirm the fade sounds right, not just that the math
  checks out.

- **[2026-09-08, FIXED 2026-09-17, live-confirmed by Pryme] Library scan focus strand —
  root-caused and fixed; the ORIGINAL
  THEORY WAS WRONG.** Originally reported as "Rescan clicked, Esc closes Settings while the scan
  is still running, then Space/arrow keys are no-ops," with a working theory that
  `_set_scan_buttons_enabled(False)` moving focus to a sibling scan button was the culprit — that
  theory was investigated, found not to reproduce synthetically, and a diagnostic
  (`[FOCUS-STRAND-TRACE]`) was left in `app.py`'s `_focus_allows_global_shortcuts()`, gated on "no
  panel open AND focus still panel-local," to catch the next live occurrence.

  **Pryme reproduced it live on 2026-09-17 and the trace DID fire** — but pointed at something
  completely different: the stranded focus owner was `fabulor.ui.tag_manager._TagBookGrid`, a
  Tags-panel widget, not a scan button. Tracing the log showed Tags had been closed **31 minutes
  earlier**; the strand had been sitting invisible the whole time, and the scan/Settings-close
  sequence in the original report was just the first moment `_focus_allows_global_shortcuts()`
  happened to run its check while no panel was open — a trigger for the *diagnostic*, not the
  *bug*.

  **A second, more careful repro then broke the original diagnostic entirely**: Pryme reproduced
  the same dead-keys symptom again, but this time `[FOCUS-STRAND-TRACE]` never fired at all.
  Targeted instrumentation added to `tag_manager.py` (`showEvent`/`hideEvent`/`_open_tag`/
  `_show_list`/`eventFilter`, all temporary, all removed once root-caused) caught the real
  mechanism directly: `TagManagerWidget.refresh_books()` (called unconditionally by
  `_on_scan_finished` → `app.refresh_tag_manager()` on every completed scan, among several other
  call sites) called `self._open_tag(self._current_tag)` whenever `_current_tag` was set — with
  **no check that the panel was actually visible**. `_current_tag` is deliberately never cleared
  on close (a reopen should land back on the same tag), so ANY scan finishing after a Tags visit,
  no matter how much earlier, re-triggered `_open_tag()` — which calls
  `QApplication.instance().installEventFilter(self)` and `_book_grid.setFocus(...)` as real side
  effects, reinstalling the app-wide filter and re-focusing `_TagBookGrid` even though the panel
  was genuinely closed (`self.isVisible()=False`, confirmed directly in the trace,
  `[TAG-FILTER-TRACE] _open_tag: installEventFilter self.isVisible()=False panel_visible=False`,
  fired 267ms after `_on_scan_finished`). From that point, `TagManagerWidget`'s own
  `QApplication`-wide event filter — which Qt runs BEFORE `MainWindow`'s own filter, since it was
  installed more recently — silently swallowed every arrow key app-wide before
  `MainWindow.keyPressEvent` (and therefore `_focus_allows_global_shortcuts`) ever saw them. This
  is exactly why the second repro produced dead keys with zero `[FOCUS-STRAND-TRACE]` hits: the
  original diagnostic could only ever catch cases where the key reached `MainWindow` at all, and
  this mechanism guarantees it never does.

  **Both of Pryme's repro observations are fully explained by this mechanism**: "didn't work with
  a fresh start without visiting Tags" — `_current_tag` is never set, so `refresh_books()` is a
  no-op; "the second scan after visiting Tags made it stranded" — any scan after a Tags visit
  retriggers it, reliably.

  **Fix** (`tag_manager.py`, `refresh_books()`): gated the `_open_tag()` call on `self.isVisible()`
  in addition to `self._current_tag` being set — `if self._current_tag and self.isVisible():`.
  `refresh_books()`'s only job is keeping an already-displayed tag's book grid current after a
  scan; there is nothing to refresh, and no side effects to trigger, when the panel isn't on
  screen. All temporary `[TAG-FILTER-TRACE]` instrumentation removed once the mechanism was
  confirmed. `pytest tests/ -k tag` green (29 tests, no new test added for this specific gap — the
  bug requires a real scan-finished signal + prior tag visit + panel-closed state to reproduce,
  which the existing test doubles don't model; worth a dedicated regression test in a future
  session if this area is touched again). **Live-confirmed fixed by Pryme** — retested the exact
  repro (visit a tag, close Tags, run a scan) and keys stayed responsive.

  **The original `[FOCUS-STRAND-TRACE]` diagnostic is left in place, not removed** — it's a
  general-purpose "no panel open, something still holds focus" catch-all that could still be
  useful for a genuinely different future occurrence, and it did correctly catch and disprove the
  original theory even though it wasn't (and structurally couldn't have been) the tool that found
  this actual bug.

- **[2026-09-17] CLOSED: Library 2-per-row grid doesn't fully fill available whitespace.** Confirmed
  fixed by Pryme directly — the layout looks right now. No commit is cited here because the entry
  was caught stale during a routine check of the HTML triage view rather than traced to a specific
  fix; if the exact commit that resolved it is ever needed, `git log -- src/fabulor/ui/library.py`
  around the 2-per-row cell-sizing constants is the place to look.

- **[2026-09-17] CLOSED: sidebar mouse-wheel conflict over the cover art area — turned out to be a
  documentation/framing mistake, not a code bug needing further work.** Pryme originally logged:
  "when the sidebar is open, mouse wheel over art area both closes it and hits the volume... behavior
  to be decided," with a stated lean toward "closing the sidebar if it is over the art area, then
  manipulating the volume as usual with the next flick." Investigation found `visual_area`'s wheel
  branch (`app.py:4031`) was the one wheel-active zone missing the `panel_manager.dismiss_sidebar()`
  call the other two (`speed_button`, `chapter_progress_slider`) already had before their own action,
  same event — added it to match, **same-flick** (dismiss then nudge volume, no `return` in between,
  identical to those two zones' existing pattern). The fix was scoped and confirmed with Pryme via
  AskUserQuestion at build time as "same-flick, matching the pattern" — but the TODO.md entry
  recording it was written sloppily, restating the ORIGINAL "close now, volume on the next flick"
  lean as if that were what got built, when only the same-flick version was ever implemented.
  Pryme tested live post-fix (confirmed fresh app launch, not a stale process) and reported "same
  behavior as before" — correctly, since `_nudge_volume` always ran regardless of sidebar state both
  before and after this change; only the (functionally invisible in this exact repro)
  `dismiss_sidebar()` call was new. On reflection, asked directly, Pryme said he has no strong
  preference between "close-then-volume-on-next-flick" and "close-and-volume-same-flick" — the
  same-flick behavior as built is fine. Closed on "acceptable as built and live-tested," not on
  "matches the original ask," since the original ask was itself mis-scoped in the entry's own first
  draft. Lesson for next time: when an entry's own text later gets contradicted by a live report,
  re-derive what was ACTUALLY built and ACTUALLY confirmed with the user at build time, rather than
  trusting the entry's own retrospective summary of itself.

- **[2026-09-16] CLOSED (corrects the original 2026-07-15 entry's scope): Undo doesn't return to
  the true origin after a rapid spree of small seeks.** The 2026-07-15 entry narrowed this live to
  "Next/Prev specifically — every other undo/restore path correctly returns to the true origin" and
  left the root cause undiagnosed. That narrowing turned out to be an artifact of which repro had
  been tried, not the actual scope: the real root cause, found 2026-09-16, was general to EVERY
  seek-driven call site that gated its own call to `save_seek_position` on that single seek's own
  displacement exceeding a threshold (`60 * speed`) — `handle_next`/`handle_prev`, chapter-list
  click, slider release/right-click, and chapter-slider release all shared the identical shape.
  Next/Prev was simply the easiest to trigger (small chapter-to-chapter jumps make the "spree of
  small seeks that individually never qualify" case common), not a special case. Root cause: a
  caller-side gate that skips calling `save_seek_position` entirely when a single seek doesn't
  qualify also skips capturing the coalescing anchor for that seek — so whichever LATER seek in the
  same spree happens to individually qualify captures ITS OWN start position as the anchor, a
  mid-spree position rather than where the spree began. Fixed by moving the distance decision INTO
  `save_seek_position` itself: the anchor is now captured unconditionally on every call within a
  live coalescing spree, and only the "show the overlay" decision is gated on CUMULATIVE distance
  from that anchor. Two related follow-up bugs found and fixed the same session: the long-skip
  buttons and `|<`-to-restart showed Undo for seeks that didn't actually move (near-EOF silent
  refusal, or a trivial move already at the start) — fixed by reading `time_pos` back after
  `seek_async` rather than trusting the pre-computed target; and the chapter-slider wheel scrub (and
  later, on request, regular skip taps/holds too) showed Undo on every single tick regardless of
  size — given the same standard distance gate, so a spree of small ticks now correctly earns Undo
  only once cumulative distance crosses 60s. Full detail: CLAUDE.md's "Undo must anchor to a seek
  spree's start" rule and its two follow-up rules; `tests/test_undo_position.py`. Commits `3fe85a0`,
  `693274f`, `651c557`, `1a6e633`, `df1923e`. Live-verified by Pryme across all four input
  modalities (Next/Prev, long-skip/restart, wheel scrub, regular skip taps/holds).

- **[2026-09-17] CLOSED by Pryme's own report (a month of real use, zero recurrence): the
  punch-through-FLASH collision.** The spurious-`enterEvent` heartbeat's two triggers were fixed
  2026-07-21 (`1a00abd`) and verified live at the time. The underlying punch-through-FLASH itself —
  a real, event-driven `main_window.grab()` landing right after a restyle against Qt's
  post-restyle repaint/repolish backlog, measured live with outliers up to 357ms — stayed open
  through several rounds because it was "never fixed, only reduced in frequency and de-amplified,"
  and the decisive restyle-and-grab-coinciding capture this item always called for was never
  actually run (a 2026-07-27 13s idle capture was explicitly noted as inconclusive — too short,
  too idle to have a real chance of catching it). Closed 2026-09-17 on Pryme's direct report: "Never
  seen once since the blur branch was done with. More than a month." The transport-bar blur overlay
  went through a substantial rework across 2026-08-01 through 2026-08-18 (park/unpark, manual
  hover-paint into the frost — see the "CLOSED: transport-bar frost hover/pressed/tooltip saga"
  entry below) that concluded around 2026-08-18; git history confirms no further changes to
  `transport_bar_blur.py` until 2026-09-08 (an unrelated focus fix), consistent with "the blur
  branch was done with" over a month before this closure. This is sustained real-use observation,
  not a targeted capture — the open question this entry always carried (whether a recurring flash
  would be the live main window or the overlay's grabbed pixmap) was never answered and would need
  re-investigating from scratch if this ever resurfaces.

- **[2026-09-17] CLOSED by Pryme's own soak testing: theme-bleed, both halves.** Two entries
  (2026-07-21) each said "verified fixed with blur ON, not yet soak-tested" and were held open
  pending a longer soak: (1) hovering a swatch to preview then closing the panel, repeatedly,
  bleeding the preview color into the whole live main window instead of reverting — fixed
  2026-07-20 via two independent causes closed the same day (state-read bypass in
  `_set_bg_suppressed`, hover-unaware blur grab in `refresh_dirty`; NOTES.md "Theme-bleed Pass 1 +
  Pass 2"); (2) the `complete_main_fade()` fix for the same underlying symptom, verified separately
  since the bug's own reproduction was inconsistent (sometimes immediate, sometimes ~5 minutes).
  Pryme confirmed 2026-09-17: "Theme bleed is closed. I have been soaking it for weeks." Both
  closed on that basis. Explicitly distinct from, and does NOT close, the punch-through-FLASH
  collision (`main_window.grab()` landing right after a restyle against Qt's repaint/repolish
  backlog) — that item is separate, was never fixed (only reduced in frequency), and stays open in
  TODO.md under "Right-click / theme-restyle performance." Also does not resolve the untriaged
  "general responsiveness reported slow after this fix landed" follow-up, kept open separately.

- **[2026-09-17] CLOSED: "Cover art based theme" right-click doesn't activate from Off mode when no
  cover theme has been built yet.** Reported by Pryme directly, correcting a wrong "already
  shipped" claim from the same day's staleness audit (see the correction note above). Root cause:
  `apply_cover_theme` (`theme_manager.py`) bare-returns via `clear_cover_theme()` whenever mode is
  Off, without ever building `theme_dict`/setting `self._cover_theme` — so for a book that's been
  Off the whole session, `self._cover_theme` stays `None`. `_on_cover_pool_btn_right_clicked`'s
  `if not self._cover_theme: return` guard then made right-click silently do nothing in exactly
  that state, even though left-click (`_on_cover_pool_btn_clicked` → `set_cover_art_mode`) already
  builds the theme on-demand via `apply_cover_theme(pixmap, user_initiated=True)` when switching
  Off → With pool. Pryme's own framing of the fix: "it is not clear if the user wants to set With
  pool or Exclusive [when right-clicking from Off]... We can make the right click on cover art
  theme label select the With pool option if Off is selected." Fixed by having
  `_on_cover_pool_btn_right_clicked` call `set_cover_art_mode("with_pool")` when `_cover_theme` is
  None and mode is Off, before its existing activation logic — reuses the same on-demand build path
  left-click already uses rather than duplicating it. `pytest tests/ -k "theme or cover"` green
  (no dedicated test existed for this handler; none added, per no test infra covering it was found
  to extend). Live UI verification not yet done by Pryme.

- **[2026-07-21, FIXED 2026-09-18, live-confirmed by Pryme] "Cover art based theme" hover doesn't
  preview from Off mode — the hover half of the sibling right-click fix directly above.**
  `_on_cover_pool_btn_hovered` (`theme_manager.py`) early-returned whenever `self._cover_theme` was
  `None` — which is unconditionally true in Off mode: `clear_cover_theme()` nulls it on every path
  that switches to Off (`_on_cover_pool_btn_clicked`, `set_cover_art_mode`, and
  `apply_cover_theme`'s own `mode == "off"` branch), so hovering the "Cover art based theme" entry
  while Off was selected was always a silent no-op, with no exception. (Live investigation initially
  chased a false lead: Pryme first reported hover working after "With pool → Off" but not after
  "Exclusive → Off" — a real, reproducible-sounding asymmetry that contradicted the code, which has
  no such branch. Added `[COVERHOVER-TRACE]` instrumentation to settle it with evidence rather than
  re-theorize from the source per usual practice; before the trace was even needed, Pryme retested
  more carefully and retracted the claim himself — "It is not previewed when going back to Off. I
  think I confused it with a similar looking theme." The code was right the whole time.)

  Design decision (Pryme, 2026-09-18), settling the open question the original entry deliberately
  left unresolved: hover-from-Off should preview transiently, like every other theme swatch's
  hover, and must NOT commit the mode the way a left/right-click on the same button does. Fixed by
  building a theme dict from the current cover pixmap on demand, purely for the preview call
  (`_on_theme_changed(theme_dict, save=False, fade_ms=fade, hover=True)`) — `self._cover_theme`,
  `self._cover_theme_active`, and the stored config mode are never touched by this path, so the
  existing unhover snapback (`_on_theme_unhovered`) needed no changes: it already reads those same
  two fields and correctly falls through to reverting to `self._current_theme_name` when both are
  unset, exactly the same as leaving any other unselected swatch's hover. Trace instrumentation
  fully removed once the real cause was confirmed live. `pytest tests/ -q` green, pyflakes clean.
  Commit `5f0c45c`.

- **[2026-09-17] CLOSED: two "FIXED" bullets sitting under "Settings keyboard-focus regressions
  found while testing Tags," same class of gap as the entry below (a done-status note left in the
  open-work file).** Both were flagged `— FIXED` in their own text and had nothing outstanding:
  (1) **Excluded Books focus strand.** Un-excluding the LAST remaining book drops
  `ExcludedBooksPopup.book_count` to 0, and `reposition()` hides the popup entirely in that case —
  if the popup itself held real Qt focus, `hide()` stranded it with nothing to reclaim it,
  permanently blocking global shortcuts until a mouse click reset focus elsewhere. Fixed in
  `_on_excluded_book_restored` (app.py) by redirecting to the same target
  `_on_excluded_books_exit_upward` already uses on a normal Up-out-of-the-popup exit. (2)
  **Speed/Sleep/Sprint "ramp-up" buttons' highlight not clearing.** Each panel's per-instance ramp
  stylesheet (`_apply_preset_ramp_colors`) had a bare, unscoped `QPushButton:focus` rule for the
  keyboard-cursor highlight; these buttons keep real Qt focus even after the traveling marker
  itself stops being drawn, so the bare `:focus` rule kept matching and the highlight stayed lit
  indefinitely. Fixed by scoping the rule to `[kbdnav="true"]` in all three panels. The heading
  itself stays open in TODO.md — its middle bullet (the Library-scan focus strand) is a genuine,
  still-unreproduced live bug — only these two flanking done-status bullets are archived here.

- **[2026-09-17] CLOSED: "Book Detail panel blur timing" heading — a fourth instance of the same
  gap, caught during a follow-up triage pass rather than by a fresh audit.** Its sole entry
  described the park/unpark fix (`fix/book-detail-blur-park`, merged) addressing both original
  2026-08-01 entries plus the same-day stale-parked-frame follow-up (`a9dfb06`), with nothing left
  outstanding — the entry's own last sentence already pointed at TODO_ARCHIVE.md for the closure
  record, which is what tipped this off as the same "done-status note sitting in the open-work
  file" shape as the three above. Closed outright; the closure records it already pointed at
  (`a9dfb06`, and the "[2026-08-14] Book Detail panel blur timing" original entries) remain
  elsewhere in this file.

- **[2026-09-17] CLOSED: "Keyboard navigation — remaining surfaces" status note — a pure done-status
  entry that was never actually open work, missed by the same-day staleness audit's own edit.** The
  2026-09-17 audit corrected this entry's stale "not merged" branch reference (`c2023e1` merged
  `feature/traveling-focus-marker` on 2026-09-10) but left the whole heading sitting in TODO.md — an
  "open work" file — describing something with nothing left outstanding: "The whole Settings panel
  ... plus Speed, Sleep, and Sprint are all arrow-navigable ... `disable_sleep_btn`'s and
  `disable_sprint_btn`'s missing-hover gaps ... were both closed this pass ... no longer an open
  item." Pryme caught it directly: "From this wording, I can't see anything outstanding. What am I
  missing?" — correctly, nothing. This is the same class of gap the audit was supposed to be
  hunting for (an entry whose own text says "done" left un-archived), and the audit fixed the
  factual claim inside the entry without asking whether the entry belonged in TODO.md at all.
  Closed outright; the underlying facts (arrow-nav shipped 2026-09-07, hover-gap fixes bundled into
  that pass) are already documented in CLAUDE.md's "What's Built" section, so nothing is lost by
  removing this pointer.

- **[2026-09-17] CLOSED, staleness-audit batch: eleven TODO.md entries found already fixed/shipped
  by later commits, never moved out.** Found via a full audit of TODO.md against git history and
  CLAUDE.md's changelog (2026-09-17). Grouped here as one batch since each was independently
  confirmed against a specific commit or current source, not against each other:

  1. **Diacritic-insensitive library search** [2026-09-08] — fully implemented by `612a946` ("feat:
     add diacritic-aware search and sort to the library", 2026-09-10): `_diacritic_aware_find`/
     `_diacritic_char_matches` in `ui/library.py`, wired into `_apply_filter_and_sort`. The branch
     this entry said to wait for (`feature/traveling-focus-marker`) merged the same day.
  2. **`feature/traveling-focus-marker` "not merged" references** (three places in TODO.md) —
     merged via `c2023e1` on 2026-09-10 (`git log main..feature/traveling-focus-marker` is empty).
     Further keyboard-nav work shipped directly on `main` afterward (`513631e`, 2026-09-15).
  3. **"Traveling focus marker must be keyboard-only, not mouse-activated"** [2026-07-10] —
     implemented; `app.py`'s `_set_keyboard_nav_active`/`_update_focus_marker` has the full
     `TabFocusReason`/`MouseFocusReason` modality-ownership design, matching CLAUDE.md's
     2026-09-03/04 changelog entry.
  4. **"Keyboard-selection focus indicator is nearly invisible"** [2026-07-09] — solved by the
     now-shipped traveling-focus-marker feature (`ui/focus_marker.py`, wired app-wide).
  5. **"Stats Day/Week/Month sub-nav and Tags panel keyboard nav — deferred, larger scope"**
     [2026-07-12] — Tags panel nav shipped (`_handle_tag_list_keys`/`_handle_thumb_grid_keys` in
     `tag_manager.py`, 2026-09-13/15 per CLAUDE.md); Stats' own "⚙" tab got `_handle_stats_arrows`
     (2026-09-08). Narrower residual (Day/Week/Month `‹`/`›` prev/next buttons specifically) kept
     open in TODO.md under "Panel focus / keyboard navigation," reworded to reflect only that gap.
  6. **History tab `_history_scroll` row-height viewport quantization** [2026-07-11] — fixed by
     `b20a1ff` ("fix: eliminate History tab row clipping and keyboard-nav scroll drift",
     2026-08-12) via `layout.addSpacing(3)` making the viewport an exact multiple of the row
     height (`book_detail_panel.py`) — shipped without the tags-gutter-work dependency the entry
     said blocked it.
  7. **Book Detail blur "stale parked frame while parked and book excluded/cover changed"**
     [2026-08-14] — fixed same day by `a9dfb06` ("fix: invalidate a parked frame when content
     changes beneath it"), implementing the `_parked_frame_invalid` flag the entry proposed almost
     verbatim; confirmed present in `transport_bar_blur.py`.
  8. **Book Detail blur "opening slide drops blurred window too early"** [2026-08-01] — fixed by
     the park/unpark mechanism; `park_for_panel`'s own docstring in `transport_bar_blur.py`
     explicitly states it fixes "a visible crisp frame on both the open and the close."
  9. **Book Detail blur "closing reveal-scanner is intermittent"** [2026-08-01] — the
     reveal-scanner mechanism no longer exists in source at all (superseded outright by park/
     unpark, which the "Book Detail panel blur timing" section of TODO.md already noted does not
     use it).
  10. **Three-state panel background "clicking an option has perceptible lag, not yet
      investigated"** [2026-07-28] — investigated and partially fixed by `149c647` ("perf: scope
      the backdrop-mode restyle to the surfaces that read the panel alpha", 2026-08-02, days after
      the entry was written): cut from ~1040ms to ~555ms by scoping the restyle instead of running
      a full pass. A further ~140ms residual (skip-hidden-panels) was deliberately not bundled;
      kept open in TODO.md's Pending section, reworded to describe only that residual. The entry's
      own open question about `blur_enabled` migration is also resolved — `config.py` confirms
      full migration to the three-state `panel_backdrop` key, with the old boolean kept only as a
      one-time backward-compatibility read.
  11. **Volume/muted-icon "don't accept wheel-scroll while visible" and "clicking the muted icon
      should restore volume"** [2026-06-23, both] — both fully implemented in `app.py`:
      `wheelEvent` explicitly handles `volume_slider.underMouse()`/`muted_icon_label.underMouse()`
      (with an inline comment referencing this exact TODO closure), and `_restore_from_mute()`
      implements the "value before manipulation started" capture design (`_pre_mute_volume`),
      wired to `_toggle_mute` (the `m` key), `_on_muted_icon_clicked` (click), and wheel-scroll-up.
      The third sibling entry, "Slider→muted-icon transition is abrupt," is NOT closed by this —
      `_show_volume_overlay` still jumps directly with no transition — and stays open in TODO.md.

  **Correction, retracted the same day it was written:** item 4 of this batch (originally covering
  the "cover art based theme" hover/right-click entry) claimed the right-click-from-Off half was
  "already implemented" via `_on_cover_pool_btn_right_clicked`. That was wrong — Pryme corrected it
  directly: "Not fully implemented. Left click selects the cover art theme, right click doesn't set
  it." Re-reading the handler confirmed Pryme's report, not the original claim: with mode Off,
  `apply_cover_theme` bare-returns via `clear_cover_theme()` and never builds `self._cover_theme`
  for that book, so `_on_cover_pool_btn_right_clicked`'s `if not self._cover_theme: return` guard
  made right-click a no-op from Off whenever no cover theme had been built yet — exactly the
  reported symptom, not a false report. See the separate 2026-09-17 entry below for the actual fix
  applied in response. The lesson: a function existing and being reachable is not the same as it
  producing the claimed behavior in the state the report describes — this should have been
  verified against the specific Off-mode-with-no-prior-cover-theme case, not just confirmed to
  exist.

  Also reworded in place (not archived, since the underlying work is still partially open):
  the "Stats refactor... depth reduction" restyle-perf entry (a same-day-but-later investigation,
  `review/Investigation_260802_restyle_cost_depth_and_narrowing.md`, found depth flat over 2
  months — the depth-reduction framing needs re-verifying against current widget-tree depth,
  possibly already covered by the Stats delegate migration); and the History-tab delete-animation
  "blocked on the above" framing (its blocker, item 6 above, shipped — the animation itself was
  never re-tuned, so it's unblocked-but-not-resumed, not stale in substance).

- **[2026-09-10] CLOSED: Settings/Stats "⚙" tab Right-arrow inconsistency at a row's last
  button.** Reported live 2026-09-09 as "Right arrow is mostly no-op, from Look and Controls it
  goes to the tab" and initially scoped as needing a live `QApplication.focusWidget()` trace to
  diagnose why Qt's native sibling-focus-chain stepping resolved differently per tab. Root cause
  turned out not to need that trace at all, once reframed as a design question rather than a
  diagnosis: `_handle_settings_arrows`/`_handle_stats_arrows` never had a DELIBERATE Right/Left
  model at a row's edge — both deferred to Qt's own native chain (construction order, not the
  visual row model), which is exactly the mechanism `_handle_flat_panel_arrows`'s own comment
  already named as "never actually safe, just lucky" after it caused a REAL escape-to-an-
  unrelated-row bug on Speed/Sleep/Sprint (fixed 2026-09-07). Both methods now use the same
  full reading-order wrap Speed/Sleep/Sprint already had: Right past a row's last item continues
  to the next row's first item, past the LAST row's last item wraps to the tab bar; Left mirrors
  this backward; Down at the last row now wraps to the tab bar (was a swallow); Up from the tab
  bar now lands on the last row (only Down-from-tab-bar existed before). No native-chain
  dependency remains in either method. `7fdd882`.

- **[2026-09-10] INVESTIGATED, NOT RESOLVED: Sleep/Sprint Disable-Cancel button blinks
  highlight→dark→highlight before disappearing.** Root cause fully traced (a live paint-event
  logger, not guesswork): Qt's own `QAbstractButton::mouseReleaseEvent` repaints the button back
  to enabled/hover-visible as part of its internal `isDown()` transition, and only AFTER that
  repaint does it emit `clicked()` — so nothing reachable from the `clicked` slot can suppress it.
  Three fix attempts, each tried live and each failed for a distinct, verified reason: disabling
  on press (kills `clicked()` outright, button gets stuck), disabling in the `clicked` slot or
  fading the hide (too late to help, and the fade version introduced a real focus-jump
  regression), and an opaque click-through scrim overlay (visually worked, but gets permanently
  stuck if the mouse is pressed then dragged off the button before release — a real, natively-
  supported gesture the design never accounted for). Full trace-by-trace writeup, including the
  exact timestamps and synthetic-test evidence for each failure: NOTES.md, 2026-09-10. Left as a
  known, low-priority cosmetic issue — both `sprint_panel.py` and `sleep_timer.py` are back to
  their pre-investigation committed state, no code changes kept.

- **[2026-09-10] CLOSED: Book-detail keyboard shortcut (Alt+Enter/Shift+Enter) consistency across
  panels.** Originally opened 2026-09-08 with two explicit follow-ups after Tags' thumbnail grid
  gained both modifiers as synonyms: (1) give Library's own keyboard nav a matching Shift+Enter
  (it only accepted Alt+Enter); (2) give Speed/Sleep/Sprint's Shift-modifier "other click"
  convention a matching Alt+Enter (it only accepted Shift). Both were deferred to the next session
  pending a decision on whether Alt even made sense outside Tags/Library, discussed and settled:
  Alt+Enter is a real external convention ("get info about the selected thing," e.g. Windows
  Explorer/classic media players' Properties binding) that already matches what Library/Tags use
  it for; Shift+Enter has no comparable external convention, but since it already shipped on
  Speed/Sleep/Sprint and costs nothing to also honor elsewhere, both modifiers are now accepted
  as full synonyms everywhere either existed alone — Library's `_list_key` (`ui/library.py`) and
  `_handle_flat_panel_arrows`/`_handle_panel_grid_arrows` (`app.py`) each OR both modifier checks
  together now, matching Tags' `_handle_thumb_grid_keys` shape exactly.

- **[2026-09-09] CLOSED: confirmation-dialog Escape behavior is inconsistent app-wide.** Originally
  scoped as "not yet started, no sites enumerated" — a full audit (background research agent) found
  nine armed-confirmation sites total: Book Detail's four (remove/exclude book, mark
  finished/unfinished, delete all listening history, per-row delete-session), Tag Manager's
  delete-a-tag, Stats' reset-all-stats, Sprint's reset-all-sprint-data plus a generic
  conflict-confirm overlay, Sleep's own conflict-confirm overlay. Six already handled Escape
  correctly; three did not (Stats' reset, both panels' conflict-confirm overlay) — fixed by moving
  Sprint's/Sleep's Escape handling from a silently-unreachable `keyPressEvent` override into a
  proper `showEvent`-installed `eventFilter` (matching Stats' own already-correct pattern; neither
  panel's widget ever holds real Qt focus, so `keyPressEvent` on the panel itself was dead code).
  The scope then grew past the original ask, per follow-on live requests in the same session: Delete
  now arms three of these confirmations from anywhere on the relevant surface (Stats' reset, Sprint's
  reset, Book Detail's "Delete listening history"); and the whole set was generalized to "any key
  other than Space/Enter dismisses the confirmation and swallows that press," closing a further Tab-
  specific gap that recurred at three Book Detail confirmations (Tab is dispatched inside
  `BookDetailPanel.eventFilter`, which runs before `keyPressEvent`, so a swallow check placed there
  could never see it) and, independently, at Tags' delete-tag confirm (Tab checked ahead of its own
  swallow block). A related, pre-existing subtle bug (`_history_selected_index` could silently point
  at a `'confirming'`-state row without its visual updating) was traced afterward and found already
  closed as a side effect of the swallow-and-dismiss fix — no separate patch needed. Full narrative:
  SESSION.md, 2026-09-09 Session 1. Live-check list: TESTING.md's "Confirmation-dialog keyboard
  consistency" section. Commits `dd3b0e6`, `fc29062`, `9eeddbc`, `ca9036f`, `cab02e4`.

- **[2026-09-08] CLOSED, verified fixed: fill-highlight marker style's selected+focused+hovered
  pattern_button case.** Flagged as unchecked in the same session the `kbdnav_style` fix landed —
  a theme swatch (`#pattern_button[selected="true"]`, ID + attribute selector, higher specificity
  than a bare `:focus`/`:focus:hover`) that is simultaneously the active selection AND keyboard-
  focused AND mouse-hovered was suspected of the same specificity problem plain hover had before
  that fix. Confirmed live-checked (Pryme, next session) and already covered: the `kbdnav_style`
  fix's `[selected="true"]:hover` variant of the `:focus:hover` pairing handles this case too — no
  further work needed.

- **[2026-07-29] CLOSED, not a Fabulor bug: sidebar/theme-swatch right-click dispatch loss.** See
  NOTES.md ("CLOSED, cause is outside Fabulor: right-click loss reproduces on the bare X11 desktop
  with no app involved") for the full account. Right-click misses were independently confirmed to
  reproduce across several unrelated apps (Vivaldi, qBittorrent, VS Code, Calibre) and, decisively,
  on the **bare X11 desktop with no application in the loop at all**. That rules out anything in
  Fabulor's own code as the cause. The `investigate/rclick-contextmenu` branch (the
  `customContextMenuRequested` delivery-mechanism experiment) was discarded — `main` never had it,
  so nothing needed reverting on `main`. The branch itself is kept, not deleted, with the experiment
  and all diagnostic probes (`[EARLIEST]`/`[WCLICK]`/`[RCLICK]`/`[LCLICK]`/`[GUARD-CHAIN]`/
  `[CONTEXTMENU-ARM/RECEIVED/TIMEOUT]`/`[STALL-PROBE]`/`[SETSTYLE-PROBE]`) committed on it as a WIP
  commit, in case any of it is useful again later. Nothing pending on Fabulor's side unless it
  resurfaces with clear evidence it's Fabulor-specific (reproduces in the app but demonstrably not
  on the bare desktop under otherwise-identical conditions).

  **Folded in below: an earlier, narrower write-up of this same symptom** (originally logged
  2026-07-28 as still-OPEN, before the bare-desktop evidence above explained it) — kept for its
  specific diagnostic detail (the contradiction between a logged success and a blank screen, the
  four mechanisms it disproved), now understood to be the same OS/compositor-level issue, not a
  separate open question.

  > *[2026-07-28] Sidebar right-click sometimes does nothing, and the log says it worked.*
  > Right-click the main window with no panel open (the only way to open the sidebar). Nothing
  > appears; the next click opens it. Sometimes takes three.
  > **The contradiction to solve** (captured 21:49:24 with `[SIDEBAR-VIS]`): the click the app logged
  > as a full success — `[RCLICK]` -> toggle `False -> True` -> widget settled at `pos=(0,56)
  > size=(70,200) visible=True hidden=False parent_visible=True` — showed nothing on screen, while
  > the NEXT click logged nothing at all and visibly opened it. **The user's unanswered objection:**
  > if the app thought the sidebar was open after the first click, the second should have logged a
  > CLOSE. It opened instead.
  > **Four mechanisms disproven** (detail in NOTES.md, "OPEN: sidebar right-click sometimes does
  > nothing"): `sidebar.width()==0`, `_on_sidebar_hidden`, `resize_panels`, and widget
  > geometry/visibility at settle — the failing open is byte-identical to a working one on every
  > readable property. Plus the six eliminated earlier in the day for the broader right-click
  > question.
  > **Next measurement, not yet taken:** whether a Paint event is delivered to the sidebar across the
  > slide in the failing case. Everything readable is correct, which points at compositing rather than
  > state — the class this codebase already documents as invisible to offscreen inspection.
  > Probes in the tree: `[RCLICK]`, `[RCLICK-BRANCH]`, `[SIDEBAR-VIS]`.


- **[2026-07-28] CLOSED (live-verified): "my right-clicks are missing" — they were applying one
  step behind** (`4700b31`). Not lost presses: every click reached Qt, the widget and the handler.
  Each applied the PREVIOUS click's theme, because hovering a swatch starts a 375ms preview fade and
  the click ~400ms later stashed behind it — near-universal, since hover-then-click is how the grid
  is used. Fixed by letting a deliberate selection interrupt an in-flight fade (the half explicitly
  left alone when hovers got the same treatment that morning). Verified over a four-minute run: 104
  selections, 104 applied immediately, zero stashed. A DEBUG regression detector remains at that
  site — `grep 'OUTCOME' fabulor.log | grep 'applied=False'` should stay empty for right-clicks.
  Six candidate causes were eliminated en route (hardware, input stack, blur, hit-testing, restyle
  load, animation) — kept in NOTES.md so they are not re-derived.
  **Two adjacent threads also closed (2026-07-28, same session):** (a) the morning's theme-swatch
  log-vs-eyes disagreement (log said 89/90 clicks applied distinct themes while half appeared to do
  nothing) — no longer reproducible after this fix, which is consistent with it having been the same
  one-step-behind bug seen before it was understood; (b) the single 1046ms sidebar drop the 300ms
  slide window did not explain — 30 further app starts with right-clicks, with and without cover-based
  themes, produced no missed sidebar toggles at all. Both put to bed unless they recur; the DEBUG
  regression detector above is how (a) would be spotted again.

- **[2026-07-20] CLOSED (fixed 2026-07-27, live-verified 2026-08-05):
  `refresh_dirty`'s cooldown/hover gates don't re-arm a declined tick.** Both declining gates
  (hover-active, post-restyle cooldown) returned without scheduling any retry, on the documented
  reasoning that "the next real paint picks it up" — the dirty union is deliberately not consumed, so
  a later paint would find it.
  **Why that reasoning did not hold** (static trace, `theme_manager.py`): the hover gate's own
  docstring argued hover-end self-corrects because `_on_theme_unhovered`'s snapback restyle repaints
  the tracked widgets. But the snapback is `_on_theme_changed(..., hover=False)`, and that method's
  no-op guard (`_active_display_theme_internal == theme_name and _is_hover_active == hover`) returns
  early **without calling `_apply_stylesheets`** whenever the requested pair is already the applied
  one — exactly the state after a hover preview was DECLINED here instead of painted: the live theme
  never moved, `_mark_theme_applied` was never reached for the hovered theme, so the snapback is a
  genuine duplicate → guard fires → no restyle → no Paint event → the stranded union is never
  retried. Overlay would hold stale content indefinitely while the app kept running.
  **Fix (`ac87e0a`, 2026-07-27):** `_rearm_after_decline()` / `_fire_rearm()`
  (`transport_bar_blur.py`) — a delayed (`_DECLINE_REARM_MS = 450`, sized above
  `_POST_RESTYLE_COOLDOWN_S` so one retry normally clears the cooldown outright rather than
  spinning) coalescing retry, armed by both declining gates only. Deliberately on its own
  `_rearm_pending` flag, not routed through `_schedule_refresh` — that is the tracker's real-paint
  entry point, and a declined tick must not masquerade as observed paint. A no-dirty tick is not a
  decline and does not re-arm. Cleared in `hide_for_panel`. Pinned by
  `tests/test_blur_decline_rearm.py` (7 tests) — but at the time of that commit, only static-traced
  and unit-pinned, explicitly **not** live-verified (the commit message says so directly): per this
  area's standing rule, offscreen harnesses cannot see compositing defects here, so the actual
  stale-overlay symptom needed a live confirmation the unit tests alone could not provide.
  **Live-verified 2026-08-05** (`tools/blur_rearm_live_probe.py`, a real non-offscreen `MainWindow`
  driven by a script, kept in `tools/` as a diagnostic): opened Settings, hovered a theme different
  from the committed one, then un-hovered back to the already-committed theme — the exact
  no-op-snapback stranding path this fix targets. This organically produced **38 consecutive
  declined ticks** (25 via the hover gate, then 13 via the cooldown gate once the snapback's own
  restyle triggered it) — real repaint pressure from the hover itself, well beyond anything the
  script explicitly drove. The coalesced re-arm retry kept firing through all 38 declines and landed
  a successful `COMPOSITED` refresh once both gates cleared. The overlay never froze. This closes the
  entry as fixed AND live-confirmed, not merely unit-pinned — the gap the original fix left open.
  **Also closes** the related "[2026-07-20] blur overlay's refresh timer permanently stops firing"
  entry below it in the old TODO.md, whose UPDATE 2026-07-27 (b) had already traced this exact
  mechanism as the likely cause without ever reproducing the original screenshot; this live
  reproduction is the confirmation that update was waiting on.
  **Distinct from a SIBLING no-op-guard failure mode** found and fixed separately on 2026-08-03
  (`review/Report_260803_snapback_stuck_theme_fix.md`, `has_settled_waiter`): that fix covers the
  no-op guard firing wrongly when a theme call is deferred via
  `PanelManager.call_when_panels_settled` (the panel-open/blur-animation window) — a different
  trigger of the same underlying guard weakness (`_active_display_theme_internal` trusted as ground
  truth when it shouldn't be), not the `refresh_dirty` gate-decline path this entry covers. The two
  fixes are independent; neither resolves the other's case.

- **[2026-08-05] Transport-bar blur grab volume/cost re-confirmed against July's numbers, no
  regression found.** Investigated in response to a report that the blur "fires too much." Grab
  scope (`self.main_window.grab(padded_rect)`, never a full-window grab) confirmed unchanged from
  July — no drift, unlike the unrelated `mw.grab()` full-window capture found the same night in the
  theme-fade overlay (a different mechanism entirely; see NOTES.md 2026-08-05). Refresh cadence
  confirmed still fully event-driven (`_REFRESH_INTERVAL_MS` no longer exists as a live constant,
  only in a historical comment). Measured over a real ~12-minute session with 32 panel-opens: 590
  total grabs, mean 14.15ms, median 14.95ms, p90 18.77ms, max 72.46ms (first call in process,
  matching this project's documented first-call-elevated pattern) — in line with July's per-call
  cost figures, no evidence of a runaway loop or increased firing rate. The "fires too much"
  complaint is not explained by grab volume or per-call cost; if it recurs, look elsewhere (possibly
  the same general-responsiveness thread flagged in the still-open theme-bleed entry in TODO.md).

- **[2026-07-28] CLOSED (live-verified): sidebar right-clicks discarded mid-slide** (`f0dbc99`,
  `911b4c5`). The re-entrancy guard silently dropped 5 of 25 clicks (20%) arriving inside the 300ms
  slide. The first fix — queueing the toggle — was worse: each replay started a new slide that
  caught the next click, producing eight consecutive toggles at 306-322ms with the sidebar running
  one step behind. Root error was queueing a RELATIVE operation; now defers the desired FINAL state,
  so repeated clicks overwrite and an even number cancels out. Live-confirmed responsive.

- **[2026-07-28 Session 2] CLOSED (live-verified): first theme hover after opening Settings was dead
  ~2s.** Two parts. (1) `8c348b0` — the guard deferred via a flat 700ms retry against a 1500ms
  blur-in, guaranteeing two retry rounds plus up to 700ms of overshoot; replaced with
  `PanelManager.call_when_panels_settled` (~16ms resume) for the animating case only, `_panel_open`
  keeps the timer since it ends on a user action. Deliberately a predicate re-check, NOT a
  `finished` subscription — `stop()` emits no `finished` and `blur_animation.stop()` runs on every
  panel open, so a signal-based resume would be silently dropped (the failure already diagnosed 3x
  against `_fade_anim`). Also fixes the 2026-07-22 starvation: the new arm never restarts a running
  timer, and hover can no longer reach the old one. (2) `434763f` — the remaining ~1.1s was the blur
  itself, so the blur-in is now 400ms when Settings opens onto the Themes tab. Measured: 0ms dead
  window for a hover 400ms+ after open, 366ms worst case, and NO stall (worst frame gap ~17ms,
  identical to baseline). Both live-confirmed; the shorter blur-in does not read as abrupt.
  Full analysis and the disproven alternatives: NOTES.md, 2026-07-28.

- **[2026-07-28 Session 1] CLOSED (live-verified): theme hover previews swallowed, three bugs across six
  commits (`ac87e0a`, `57a7dd0`, `197e112`, `554476b`, `9b8d9df`, `70159d6`, `6eb07ca`).**
  (1) A hover arriving during a **snapback fade** was stashed then discarded — no preview ever
  appeared and nothing retried it. The predicate is now simply `bool(hover)`: a genuine hover
  interrupts ANY in-flight fade, including a genuine selection's settle-fade (that protection had no
  requirement behind it and swallowed previews for 750ms after every click). (2) **`048ae3a`
  reverted** — it keyed on `_is_hover_active`, which means "the last APPLIED theme was a preview",
  not "a hover is live now", so it ate legitimate snapbacks after a real mouse-out. The 775ms
  flash-then-revert it targeted is structural (`_fade_anim.stop()` emits no `finished`) and is now
  handled by clearing the stash at the interrupt site. (3) The **swatch-leave check** ended up back
  where it started: `isVisible()` is the discriminator. Two cursor-delta replacements were tried and
  both shipped regressions (~70 spurious snapbacks; then the 80ms debounce killed ~15x/sec while
  moving). Full analysis: NOTES.md and SESSION.md, 2026-07-28.
  **How to verify live** (the unit suite covers decision logic only; Qt paint/timing is not
  testable here): use the Themes tab normally with a book playing — the blur grab only fires during
  playback, which is what creates the synthetic leaves. Sweep across swatches, sit still on one,
  leave to the dismiss sliver, come back. Then with the app closed (logs rotate at 2MB under DEBUG):
  `grep -c "SWATCH-LEAVE-SUSPECT" ~/.local/state/fabulor/log/fabulor.log` — **must be 0**. That probe
  fires only when a leave is suppressed while hidden AND the cursor is outside `swatch_box`, i.e. a
  real exit that was eaten — the one observation that falsifies the premise. If non-zero, bring the
  lines back rather than patching around them; they carry the cursor position and widget rect.
  **[Superseded 2026-08-05 — do not act on the "must be 0" step above.** The premise was falsified
  live on 2026-08-03; `17d46e2` made the probe detect-and-correct, so a non-zero count is expected
  and handled. See `review/Design_260805_swatch_leave_suspect_correction.md`. Left as the archived
  record.**]**
  Also worth watching: previews appearing reliably while the cursor is in motion (regression 2's
  symptom), and after clicking a theme (the selection-fade case).

- **[2026-07-27] SUPERSEDED by the entry above — the fix described here was reverted 2026-07-28
  (`197e112`); see NOTES.md for why the discriminator was wrong: a theme preview
  self-cancelled ~775ms after appearing, with the mouse sitting still.** Repro: hover outside the
  swatch area, come back onto a swatch, hold still — the preview flashes correctly, then reverts to
  the active theme with no user action. Confirmed PRE-EXISTING (reproduced with the same day's
  declined-tick re-arm fix stashed), so unrelated to that work despite surfacing alongside it.
  **Mechanism** (read from a live DEBUG capture, not theorised — three prior hypotheses all missed
  it): leaving stashes a snapback into `_pending_fade_call` whenever a fade is in flight; re-entering
  and settling applies a genuine preview; `_on_fade_finished` then drains the stash unconditionally
  and replays the obsolete snapback on top, cancelling the live preview. The drain had a discard for
  the OPPOSITE case (`pending[3]` — the 2026-07-21 hover-confinement rule) but no symmetric check
  for a snapback superseded by a live hover; its own trace line was already printing
  `_is_hover_active=True` at that moment, unused. **Fix:** mirror-image discard gated on
  `_is_hover_active and _pending_hover_theme is None` (both halves load-bearing — see NOTES.md).
  Scoped to `_on_fade_finished` ONLY; the other two drain sites are panel-dismiss paths where a
  superseding live hover isn't a real state. `tests/test_superseded_snapback.py` (7 tests).
  **Still to do:** confirm live that the flash-then-revert is gone — it's a visual behaviour and the
  unit tests only pin the drain decision.

- **[2026-07-27] CLOSED (measured, not pursued): blur-grab residual cost.** Re-measured after that
  day's blur fixes and found to be a much smaller problem than first recorded. Kept as a record so
  the analysis is not re-derived; see the reopening bar below before acting on any recurrence.

  **The original characterisation was WRONG in two specific ways** (recorded so they are not
  repeated): (1) "the 50ms `_GRAB_FEEDBACK_SUPPRESS_S` never catches a 64ms loop" — it catches
  **94%** (2655 suppressed vs 157 passed); (2) "all 13 tracked widgets repaint in a synchronized
  self-inflicted burst" — that burst is **gone** once `_compute_bounding_rect` skips hidden widgets.

  **Post-fix measurement** (Settings open, book playing, ~13s idle): 120 grabs/13s (was ~32/s),
  median gap 61ms, **zero full-rect grabs**, cost ≈**3.6% of the main thread** (mean 3.86ms).
  Remaining paint sources are dominated by `chapter_selector` (84) and `play_pause_btn` (36) — a
  scrolling marquee and a playing-state icon, i.e. **genuine content change, not loop-driven**.

  **The 19.11ms outlier was characterised and found to have no condition attached.** Ruled out, each
  by measurement: not the widget or region (its rect `(68,417,164,24)` was the SMALLEST and most
  common, grabbed 83 times at ~2.7ms); not size (area correlates sanely — 7k px→1.64ms,
  51k px→5.80ms, neither near 15ms); not the documented restyle-backlog collision (no
  `_apply_stylesheets` anywhere near it); not a self-inflicted cascade (the preceding paints were
  all correctly SUPPRESSED). Breakdown was `grab_ms=15.28` / blur 3.78 / crop 0.05 — i.e. **`QWidget.grab()`
  itself**, not the blur. Distribution is otherwise tight: p50 3.48ms, p95 6.26ms, p99 8.00ms, and
  **1 of 120** samples above 10ms. Conclusion: environmental tail latency on a synchronous render
  (backing-store realloc / compositor / scheduler preemption), with nothing to fix.

  **REOPENING BAR — deliberately a condition, not a recurrence count.** A single further outlier is
  NOT grounds to reopen; the whole point of this entry is that isolated spikes were already observed
  and explained. Reopen only if a capture shows the spike **correlating with something specific** —
  i.e. one of: (a) it repeatedly lands on a particular widget or rect rather than being spread across
  whichever grab happens to be running; (b) it reproducibly follows a particular app state or action
  (theme change, tab switch, book load, scan, panel transition); (c) it clusters in time rather than
  appearing as isolated samples; or (d) the frequency itself shifts materially — several per
  thousand rather than ~1 in 120. Absent one of those, a recurrence is the same environmental tail
  already documented here. **A user-visible intermittent stutter is independently sufficient** to
  reopen regardless of the above, since that is a symptom rather than a statistic — but capture a
  longer window (minutes, not 13s) before concluding, as one 13s sample can establish "no visible
  condition" but cannot characterise a tail.

  **Still genuinely open and unresolved:** whether the panel `hide()` is strictly necessary for the
  grab. Removing the grab would remove its tail latency too, so this remains the one structural
  improvement available. A prior attempt to avoid it (grab `content_container` + `bg_main` fill) was
  reverted 2026-07-19 because it broke theme hover-preview/snapback for reasons **never diagnosed** —
  confront that first; do not simply re-attempt it. Full detail in NOTES.md (2026-07-27).


- **[2026-07-28] CLOSED: Sleep/Speed preset buttons were translucent, showing the cover art
  through them** (`fa6d301`). Both panels built the ramp as an alpha ramp (75..255) on the accent,
  emitted as `rgba()`; at alpha 75 the first button is ~29% opaque and composited against whatever
  sat behind the translucent panel. Replaced with `preset_ramp_rgb` (`themes.py`) — the same
  progression blended in colour space from `bg_main` toward `accent`, emitted opaque. The old
  75..255 span is reproduced as mix ratios so the look is preserved. Scope note (also in NOTES.md):
  the other `setAlpha` sites are QPainter-drawn against a known surface and are NOT the same bug —
  do not sweep them. `tests/test_preset_ramp.py` (8 tests).

- **[VERIFIED, 2026-07-18] Rapid-switch progress-integrity check against tonight's final
  startup-sequencing state — PASSED, no data-integrity issue found.** Ran the Bug-1/Bug-2-era
  repro (rapid switching between Colorless Tsukuru Tazaki and Sometimes a Great Notion, 00:44-00:46)
  against the committed state (`cd5ec5b` + `0990e00`). Log-confirmed across many rapid switches:
  `_restore_position`'s `book_data.progress` always matched the correct prior value for each book
  (Tazaki → `23307.624886`, Sometimes a Great Notion → `56004.037344...`) on every switch, no
  near-zero transient, no dropped restore. Progress integrity holds.

- **[FIXED, committed `1025b0a`, 2026-07-18] "Theme-ROTATION landing mid-flow-animation" —
  CORRECTED: not a rotation-timer bug at all, it was `clear_cover_theme()`'s revert-to-pool-theme
  path (no cover on the switched-to book) with no stand-down, plus a real second bug it exposed.**
  Originally logged as "theme rotation," but the user later corrected the framing: "Against the
  Day" had no cover art, so the theme change was `clear_cover_theme()` reverting to the pool theme,
  not the independent rotation timer. Two bugs, both fixed, see NOTES.md's 2026-07-18 entry for the
  full trace: (1) `_show_no_cover_state` had no stand-down at all, unlike the has-cover path's
  existing `is_any_panel_visible()` defer — fixed via a new `_PENDING_CLEAR_COVER_THEME` sentinel;
  (2) that fix exposed `_run_deferred_restyle` never checking `_fade_in_flight`, only the flow
  animation, so the fade the reverted-theme starts could still get its flush landed mid-fade if a
  fast-loading (no-cover) book's own flow animation finished first — fixed by adding the
  `_fade_in_flight` guard condition and wiring `_on_fade_finished` to re-trigger the check. Live-
  verified: cover→placeholder switch, cover-art-based theme ON, fade now completes smoothly.

- **[VERIFIED, 2026-07-18] 4-condition × 10-sample worst_gap matrix (VT/ON, VT/OFF, M4B/ON,
  M4B/OFF) re-run against the fully-fixed final state (all five bugs committed) — PASSED, all
  four conditions clean.** 10 samples/condition judged sufficient rather than the original 30 —
  the earlier 30-sample runs were specifically needed to detect an intermittent timing race (scan
  duration vs. animation duration); with that race now removed at the source (no scan on normal
  launch), a smaller sample is enough to confirm the healthy baseline holds, not to hunt for a
  rare collision. Results: VT/OFF 51.8ms/34.2ms median (max 70.1/50.5), VT/ON 50.3ms/33.1ms median
  (max 60.8/47.0), M4B/OFF 41.0ms/25.2ms median (max 61.2/44.4), M4B/ON 32.3ms/17.1ms median (max
  48.8/40.2) — all four in the same healthy ~30-70ms range, cover-ON and cover-OFF statistically
  indistinguishable in both formats, no trace of the original 400-570ms stutter. Corroborated by
  the user's own incidental testing while chasing the other fixes this session: no progress lost,
  flow smooth throughout. This closes out the last open verification item from tonight's work.


- **[FIXED, committed `5cfe3a3`, 2026-07-17] Bare-Qt-chrome-at-startup bug — CORRECTED root cause
  (not "book has a cover + mode Off" as first diagnosed; see NOTES.md correction entry at the
  top).** Real cause: `_setup_ui` applied only the visible-surface pass at startup
  (`_apply_stylesheets` alone), never the deferred invisible-surface pass. Any later startup call
  into `_on_theme_changed` with the same theme name (always true for `clear_cover_theme()`, hit by
  BOTH the no-cover case and the cover-mode-Off case — cover presence is irrelevant) hit the
  same-name no-op guard and never reached the deferred pass, leaving
  library/settings/speed/sleep/stats/book_detail panels unstyled for the session. Fixed via a
  shared `apply_full_pass()` helper, called once at startup. Live-verified (log evidence in
  `review/Snapshot_260717_theming_state.md`): panels show correctly styled on first open after a cold
  launch with cover-theme Off. A SECOND, unrelated regression was found and fixed in the same
  commit — theme hover preview no longer reaching settings/speed/sleep panels (introduced by the
  same night's earlier deferred-restyle narrowing, which had moved that styling into a
  not-hover-gated method alongside panels that were ALREADY correctly hover-gated before the
  narrowing). Also live-verified via real hover events in the log.
  Every cover-OFF trace/number from tonight's Regime A benchmarking (both the original 8-batch
  pass and the corrected V2 re-run) is still VOID and must not be cited going forward — those runs
  predate this fix. Re-running is a separate decision, not automatic.


- **[FIXED, committed `cd5ec5b`, 2026-07-18] Post-library-scan cover-refresh
  (`library_controller.py:161`) racing the book-load flow animation — SUPERSEDES this entry's own
  "not yet confirmed why" open question.** The mechanism traced here (every book-load calling
  `apply_cover_theme` twice — once at startup, again from the post-scan cover-refresh whenever a
  background scan finishes — with the second call's synchronous `_apply_stylesheets` freezing the
  flow animation if the scan happened to finish mid-animation) was correct. The actual fix was
  upstream of this call site entirely: `handle_background_tasks` was starting a library scan on
  EVERY app launch, unconditionally, contradicting CLAUDE.md's own documented contract — gating
  `scanner.start()` behind the same `manual/force_refresh/has_indexed_books` predicate that already
  gated its status message means a normal launch no longer scans at all, so the second
  `apply_cover_theme` call this entry describes never fires in that case. This also answers the
  entry's own deferred question ("why does the second call still hit the no-`_fade_anim` branch") —
  it doesn't anymore, because there's no second call to begin with on a normal launch. Manual/forced
  scans (Rescan, add/remove folder) still trigger the post-scan refresh exactly as before — that
  path was never the bug. See NOTES.md's 2026-07-17/18 entry for the full trace and the empty-
  library-panel regression this fix's first (incomplete) attempt caused and then also fixed in the
  same commit. Confirmed NOT a VT-specific bug either, exactly as this entry's own "likely NOT
  actually a VT bug" note predicted — final 10-sample benchmark (2026-07-18) shows VT and M4B
  behaving identically post-fix.


- **[CLOSED, 2026-07-18, by explicit user decision] Flow-animation/theme-apply narrowing work —
  umbrella issue from 2026-07-16/17, now closed.** Original closure bar was ALL FOUR criteria
  simultaneously: (1) app launch smooth cover ON/OFF × VT/non-VT, (2) book-switch smooth same
  matrix, (3) no progress loss under rapid switching, (4) library panel doesn't stutter on open.
  Status at closure: (1)/(2) — confirmed via the final 10-sample worst_gap benchmark (2026-07-18,
  see entry above), all four conditions in the healthy 30-70ms range. (3) — confirmed via the
  rapid-switch progress-integrity re-check (2026-07-18, see entry above), no data loss across many
  switches. (4) — library-panel-open stutter remains **not separately re-verified this session**;
  it was INCONCLUSIVE at the time this umbrella was written and was not the direct target of any
  of tonight's five fixes (though `cd5ec5b`'s startup-population fix does address a RELATED
  first-open symptom — the empty-panel flash — which is a different bug from the stutter this
  criterion originally meant). Explicitly asked and closed rather than left open on a technicality:
  the user has not observed this stutter during tonight's extensive testing and elected to close
  this umbrella now, on the basis that if it resurfaces it will be noticeable and can be
  investigated fresh at that point — not on the basis that (4) was formally re-verified. If it
  resurfaces, treat as a new investigation; the INCONCLUSIVE trail (cache-miss hypothesis that
  failed correlation testing twice) in NOTES.md's 2026-07-16/17 entry is background, not a
  confirmed dead end to avoid re-checking.


- **[FIXED, committed `cd5ec5b`, 2026-07-18] Cover-theme `_apply_stylesheets` freezing the
  app-start flow animation (Regime B) — same root mechanism as the post-library-scan cover-refresh
  entry above, fixed by the same commit.** This 2026-07-14 measurement (400-600ms worst frame gap,
  up to 791ms, cover-theme-ON cold launches) predates the later, more precise trace that identified
  the actual second-call trigger (the unconditional launch scan). Gating `scanner.start()` behind
  the manual/force/no-indexed-books predicate removes the second `apply_cover_theme` call on a
  normal launch entirely, which is what this entry's "cold launch, no panel animating to trigger
  the existing guard" gap was really describing — there's no longer a second call for that guard to
  need to catch. Final 10-sample benchmark (2026-07-18) confirms cold-launch worst_gap now sits in
  the healthy 30-70ms range across VT/M4B × cover ON/OFF, down from the 400-791ms measured here.
  Superseded, not folded into any future async-`_apply_stylesheets` redesign — the root cause here
  turned out to be a scan-trigger bug, not something requiring the deferred/async stylesheet
  architecture change this entry originally pointed toward.

- **[2026-07-28, CLOSED (live-verified 2026-07-30): `a4f4e71` (mid-close panel no longer dispatched
  to on right-click).** Narrowed from an earlier three-commit bundle logged the same night as
  UNVERIFIED — `3132be7` (three-state panel background) and `f3221f6` were resolved separately (see
  TODO.md's three-state panel background entry and its own closed record above); `a41698c`'s
  remaining performance issue is covered by the app-wide restyle perf-pass item in TODO.md. This was
  the one commit left genuinely unconfirmed. Fix: a panel stays `isVisible()` for its entire ~300ms
  close-slide, and `handle_drag_area_right_click` used to derive "which panel is open" from a
  duplicated `isVisible()` ladder — so a right-click arriving mid-close was routed into that panel's
  own close flow, which early-returns while its animation runs, silently swallowing the click
  instead of falling through to the sidebar toggle. Same shape as the sidebar drop fixed earlier the
  same day, present in four more places (`_close_speed_flow`/`_close_sleep_flow`/
  `_close_stats_flow`/`_close_tags_flow`). Fixed at the dispatcher: `active_full_panel()` now
  excludes a panel via `_is_closing(key)` (checks whether the panel's close *animation* is actually
  running, not just `isVisible()`), so a mid-close panel no longer reads as "the open panel."
  Verified live: right-clicking during a panel's close-slide now correctly falls through to the
  sidebar toggle.

- **[2026-06-25, CLOSED (live-verified 2026-07-30): shimmer plays on speed right-click even when
  speed is already default.** `_on_speed_right_clicked` always played the "just set" shimmer sweep,
  even when the right-clicked speed already equalled the stored default — a silent no-op that looked
  identical to a dropped click. Fixed by comparing `current` speed against
  `config.get_default_speed()` *before* calling `set_default_speed`, and playing the shimmer in
  reverse (top-right to bottom-left, via a new `ShimmerButton.play_shimmer(reverse=...)` parameter)
  when nothing actually changed — distinct, confirmable feedback instead of silence. A repeat
  right-click while the reverse sweep is still running is now a no-op rather than restarting it; the
  forward ("just set") direction keeps its original restart-on-click behavior since it signals a real
  change every time. Live-verified working as intended.

- **[2026-06-25, CLOSED (live-verified 2026-07-30): tag action button's check→delete revert timer
  can fire mid-edit.** After a tag rename, an unguarded `QTimer.singleShot(2000, ...)` reverted the
  action button's visual state; starting a new edit within that 2s window left the stale timer
  running, and when it fired it silently flipped the button back to delete-mode regardless of the
  in-progress "save" state. Fixed by capturing the timer (`self._rename_revert_timer`) and having
  `_on_tag_name_changed` — which fires on every keystroke — stop and clear it before deciding the
  button's mode. Live-verified: starting a new edit within the 2s window no longer gets silently
  reverted out from under it.

- **[2026-06-25, DECIDED AGAINST, not implemented (2026-07-30): Cover Panel has no duplicate-cover
  detection.** Attempted, not shipped. Two detection mechanisms were tried and both failed for the
  same underlying reason: JPEG re-encoding is lossy, so comparing a freshly-picked image (whether by
  raw file bytes, by re-encoded JPEG bytes, or by decoded pixel data) against an already-stored cover
  (itself a previous re-encode) essentially never matches, even for the literal same source file —
  confirmed directly: `QImage.save(..., "JPEG")` does not reproduce identical bytes across separate
  encode calls, and a decode → save → reload → decode round trip does not reproduce identical pixels
  either, at the same resolution, from the same source. A reliable fix needs to compare against
  something that predates the lossy re-encode — e.g. a hash of the original picked file's raw bytes,
  stored in a new `book_covers` column — which is a real schema change for a papercut-level feature
  (wasting one of 4 cover slots on a re-added duplicate is the user's own choice to make, not
  something worth enforcing). Decided not worth pursuing further at this cost/value ratio. If
  revisited, do not re-attempt byte- or pixel-comparison against the stored JPEG — start from the
  schema-change approach or drop it again.

- **[2026-08-07] FIXED and live-verified (2026-08-08): Smart Rewind re-fired on every Play press
  after the first, until the next real pause.** `toggle_play_pause` (app.py) called
  `apply_smart_rewind(self._last_pause_timestamp, ...)` on every unpause, but `_last_pause_timestamp`
  was only ever written at pause (app.py, the `else` branch) and at app init — never reset after a
  rewind actually applied. Diagnosed from log traces alone (`seek_async`/`_on_time_pos_change`/
  persistence) since neither `toggle_play_pause` nor `apply_smart_rewind` had any logging: paused
  ~15min, then 5 Play presses ~1-2s apart produced 5 separate `seek_async` backward seeks (~23-24s
  each = `rewind_sec × speed`), all with `paused=True`, because `away_duration` kept recomputing from
  the same stale timestamp. **Fix**: `Player.apply_smart_rewind` (player.py:1317) now returns `True`
  when it issues a seek and `False` on every early-exit (no instance/timestamp, `wait_min`/
  `rewind_sec` ≤ 0, or away-duration under threshold) — its only call site. `toggle_play_pause`
  (app.py:3137) captures that return and sets `self._last_pause_timestamp = None` only when a rewind
  actually fired, placed after the seek is issued and before `self.player.pause = False`.
  `_last_pause_timestamp` still has exactly one set-site (the pause branch) plus this one new
  `None`-reset site. Full test suite green; live-verified — did not get stuck on repeat Play presses.

- **[2026-08-08] FIXED and live-verified (2026-08-09): Stats Day-tab row hover-highlight flicker,
  specific to blur being enabled.** Root cause: `TransportBarBlurOverlay._grab_and_blur` hides then
  shows the active panel ~5x/sec while blur is enabled and any panel is open (`transport_bar_blur.py`).
  Hiding `StatsRowListView` correctly delivers a real `leaveEvent` (Qt recomputes what's under the
  cursor), clearing the hover fill via the existing `leaveEvent` handler — but re-showing only fires
  `showEvent`/`enterEvent`, never Qt's `entered` signal, since `entered` only fires on an actual
  mouse-move over a new index, not a visibility change alone. With a stationary cursor this read as
  "the highlight vanishes and never comes back until the mouse moves"; with a slowly-moving cursor,
  each ~200ms hide/show cycle raced the movement and produced a visible flicker. Confirmed live via
  temporary `HOVER-TRACE` instrumentation (added and stripped in the same pass): a genuine
  `leaveEvent(hovered_row_was=0)` fired at the hide, followed by `showEvent`/`enterEvent` with no
  `_on_entered` in between. **Fix** (`f2c88ae`): `StatsRowListView.showEvent` re-derives the correct
  hovered row from the CURRENT cursor position via `indexAt()` — the same query a real mouse-move
  would trigger — instead of waiting for `entered` to eventually fire. Live-verified by Pryme for
  both Day and Week (`a103619` extended the same `StatsRowListView` class to Week with zero
  Week-specific change needed, since the fix lives on the shared class).

- **[2026-08-11] FIXED and live-verified (2026-08-12): Chapter title flicker on Prev/Next/chapter-list
  seeks (VT/CUE, non-VT walk).** Fixed in `787bfaa` — see NOTES.md's 2026-08-11 entry, "Resolution
  (2026-08-12)", for the fix shape and live-verification detail (149 settle events, ~50 genuine
  artifact firings, zero chapter regressions, zero false suppressions on legitimate backward seeks
  including Prev across a file boundary). Original investigation, preserved below:

  [2026-08-11] **Reproduced, root-caused, NOT fixed — investigation only, see NOTES.md for full
  write-up + log excerpt.** Every chapter-boundary seek settles correctly, but the very next raw
  `time_pos` sample from mpv reads BACKWARD (into the previous chapter) before resuming forward.
  `_on_time_pos_change`'s non-VT chapter walk (`player.py:317-330`) reads mpv's raw `value`, not the
  settled `_logical_pos`, so the stale sample resolves to the previous chapter for one tick and the
  chapter-list/label flicker back-then-forward. Confirmed via DEBUG-level log trace (excerpt in
  NOTES.md), reproduced on real Prev/Next/chapter-list-click seeks across two VT books.
  **Confirmed present on `main`, unrelated to the sleep-fix/listening-sprint branches** — `git diff
  main -- src/fabulor/player.py` shows zero difference in the affected code.
  **This is a known bug, already fixed once and reverted**: `b6a4023` ("fix: drop mpv's stale
  backward time_pos sample after a seek (chapter-UI bounce/stick)", 2026-06-15) describes this exact
  mechanism almost verbatim and fixed it via a global-position backward-jump reject
  (`_last_global_pos` + `_STALE_BACKWARD_TOLERANCE=0.3`, comparing in global/VT-aware space); reverted
  minutes later by `4ae0783` with no rationale recorded in the revert itself — CLAUDE.md's "VT+Undo
  is the known-fragile zone" section says it broke VT backward-seek, the play/pause icon, and
  chapter[1]→[0] click, with no mechanism-level cause ever diagnosed for any of the three. Neither
  the constant nor the reject-branch exist in the codebase today (confirmed via grep).
  **Open question, unresolved:** the user reported this persisting across a book switch AND a prior
  app restart, but a LATER restart (immediately after this investigation, no code changes) made it
  stop reproducing. Neither "pure mpv timing artifact" nor "stuck app-level flag" cleanly explains
  both observations — re-establish reproducibility before assuming it's gone or attempting a fix.
  **Do not attempt a fix without live-verifying VT backward-seek, the play/pause icon, and
  chapter[1]→[0] click specifically** — those are the three symptoms `b6a4023` is recorded as having
  broken, and no mechanism-level cause was ever found for any of them; a fix that doesn't specifically
  re-check those three risks reintroducing the same regression blind. Standing CLAUDE.md rule
  applies: a clean instrumentation run is not sufficient evidence of safety in this zone — `b6a4023`
  itself had one (32/32 clean) and still broke three other things live.

  This entry's mechanism is closely related to, but not necessarily identical with, two still-open
  TODO.md entries: "Chapter list highlight fluctuates and scrolls to bottom on click" (2026-07-21,
  likely closed by the same fix per the investigation, but explicitly not closed pending
  re-verification) and "Investigate intermittent chapter-number flicker on backward seek to
  boundary" (2026-07-22, working theory is settle undershoot rather than a stale post-settle sample
  — possibly a distinct bug). Both remain in TODO.md; do not assume either is closed by this entry.

- **CLOSED 2026-08-18: transport-bar frost hover/pressed/tooltip saga — original bug statement
  through the render()/children-hide/manual-paint sub-thread and final fix.** Moved as two blocks,
  in order — this one is the originating entry (2026-08-01, measured 2026-08-14: hover
  hit-or-miss + next-chapter tooltip stuck, the shared `_grab_and_blur` hide/show mechanism), the
  next is the 4th–6th direction attempts through the final fix. All three issues (hover flicker,
  chapter_preview_label tooltip, pressed state) are now fixed; see NOTES.md/SESSION.md 2026-08-18
  for the closing summary.
- [2026-08-01, MEASURED 2026-08-14] Transport buttons paint hovered/pressed under an open panel —
  4th instance of the grab's hide/show cycle; synthetic-Enter path measured, but it does NOT explain
  the cursor-far-from-buttons case (NOTES.md). **Affects EVERY panel** (Settings/Sleep/Speed/Stats),
  not Book Detail — its frost is a separate surface that does not use the shared overlay at all.
  Symptom per Pryme: hover is *"a hit and miss, sometimes it highlights and sometimes not"*, and the
  next-chapter tooltip *"stays stuck"*. It runs the whole time a panel is **open**, not only while
  it is opening (the 2026-08-01 framing understated this).
  **2026-08-14 measurement (NOTES.md, top entry):** 225 grabs / 21.1s sustained; of 702 accepted
  paints, **0 land inside the 50ms `_grab_suppress_until` guard and 565 land in the 50-70ms band** —
  the loop clears the guard by 8-15ms every single cycle, always in the same direction. The
  intermittency is a race against that ~60ms flicker, NOT stale state; a fix premised on staleness
  will miss. Probes are permanent and env-gated: `FABULOR_GRAB_TRACE=1`.
  Two directions, neither started: widen `_GRAB_FEEDBACK_SUPPRESS_S` (cheap, symptom-level, and the
  2026-07-27 objection to it stands — though it was written without knowing the margin is this
  thin), or suppress by STATE across the hide/show rather than by a clock deadline (immune to
  round-trip drift, more invasive).
  **2026-08-14, third direction TRIED and REVERTED 2026-08-15:** `_grab_and_blur` was changed to
  grab `content_container` (with `bg_main` composited underneath) instead of `main_window`, removing
  the panel hide/show entirely on the theory that removing the hide/show cycle removes this whole
  entry's mechanism. **It did not fix the symptom.** Pryme confirmed live: highlight was "more
  responsive than before but still not acceptable... stays stale," and the next-button tooltip
  stopped appearing under an open panel AT ALL (not merely stuck — absent). The change was also
  reverted for an unrelated, more urgent reason: `content_container.grab()` returns Qt's default
  palette color (32,35,38), fully opaque, at every pixel it doesn't paint itself (the transport
  controls' inter-row layout gaps), which produced a visible rectangular darkening artifact — see
  the NOTES.md entry "Grab-source switch shipped, restored the frost it broke, then falsified the
  working theory behind per-source rate limits" (2026-08-15) for the full investigation, including
  two failed compositing fixes that could never have worked (same-color-over-itself is a no-op, and
  the opaque grab overwrites any fill painted underneath it regardless of color). Reverted back to
  `main_window` + panel-hide 2026-08-15 (`_grab_and_blur`/`_grab_and_blur_for_frost` also collapsed
  back into one function, `panel` now an explicit parameter). **This entry's underlying bug — hover
  hit-or-miss, tooltip stuck/absent — is CONFIRMED STILL OPEN as of 2026-08-15**, unchanged by any
  of this. Neither direction below was ever tried; both are still live options.

- [2026-08-16] **A FOURTH direction TRIED and REVERTED: `QWidget.render(sourceRegion=...)` in place
  of the per-tick `grab()`+hide/show, keeping `grab()`+hide/show only for `show_for_panel`'s one-time
  panel-open pass.** Premise confirmed real by direct measurement before implementation: render()
  delivers zero synthetic Enter/Leave, and — the load-bearing result — `QApplication.widgetAt()`
  does NOT flip during a render() call the way it demonstrably does across a real `hide()`/`show()`
  (reproduced directly in a scratch harness). This is not a dead premise; the mechanism genuinely
  addresses the hover/tooltip bug's documented root cause. Two real regressions were found and fixed
  in sequence during implementation (a flat `bg_main` hole-fill visible at low, normal
  `panel_opacity_hover`; then a compounding-blur feedback loop from sourcing the fix's replacement
  fill off the live, continuously-updated overlay pixmap instead of a write-once snapshot) — full
  mechanism, root-cause evidence, and the fix for each in NOTES.md ("render() investigated..." entry,
  2026-08-16) and `review/INDEX.md`'s row for `Design_260816_render_hole_fill_feedback_loop.md` (the
  file itself was deleted 2026-08-16 Session 2 once the render() direction was settled dead — see
  below — its content is preserved in that INDEX row). A THIRD issue then
  surfaced under live tab-switching ("wrong state flashes... jumps from one stale image to another")
  that was NOT root-caused — two candidate theories (a timing gap, `show_for_panel` re-firing) were
  checked directly against the log and both ruled out; the likelier remaining direction (the live
  overlay's own accumulated dirty-crop compositing being internally inconsistent, exposed differently
  by whatever a tab switch happens to repaint) was never checked. Pryme's call: "I reverted the
  render() approach. Introduces more issues than it solves." `transport_bar_blur.py` is back to the
  exact previously-committed state (`4c4937f`/`5247177`) — confirmed via grep that zero trace of
  `_render_and_blur`/`_panel_open_snapshot`/the four `[RENDER-*]` probes remains in the file. Nothing
  from this attempt was committed. **This entry's underlying bug — hover hit-or-miss, tooltip
  stuck/absent — remains open, unchanged.** If render() is ever re-attempted: the hole-fill MUST be
  write-once-per-panel-open and read-only (never re-derived from `self._overlay.pixmap()`'s own
  ongoing output, at any remove) — that requirement is now established by two independent live
  failures, not a guess — and the tab-switch inconsistency needs to be root-caused BEFORE
  re-attempting a fill fix, not treated as adjacent to it; it may share a cause with the feedback loop
  or may be the live overlay's own patchwork compositing, unconfirmed either way. Also unchecked: does
  the same tab-switch symptom reproduce on `main` (pre-render(), `_grab_and_blur`-only) — would
  distinguish "render() caused this" from "render() merely exposed a pre-existing issue in
  `refresh_dirty`'s incremental compositing."

- [2026-08-16, Session 2, TRIED and REVERTED — a FIFTH direction, DEAD, not a tunable regression]
  **Hide only the panel's CHILDREN (`panel.findChildren(QWidget)`), leave the panel itself visible,
  instead of hiding the panel.** Premise confirmed real by direct measurement before implementation:
  `QApplication.widgetAt()` stays resolved to the panel (no flip) when only children are hidden, a real
  `grab()` came back correctly panel-colored (not a hole) where children were hidden, and an exhaustive
  `hideEvent` audit across all six panels found no hard-stop-triggering side effect (one real timer-stop,
  `TasselOverlay`, already proven self-healing under a MORE aggressive version of the same mechanism
  today). Implemented, syntax-verified, reviewed. **Shipped a severe, structurally different regression
  from every prior attempt**, Pryme's report verbatim: *"Psychedelic. Everything is everywhere on top of
  everything, they are jumping up and down, the copy paste menu slides down the screen and takes focus
  from my browser."* Screenshots showed every panel tab (Settings, Sprint, Stats) rendering with heavily
  overlapping/ghosted/duplicated content; a popup escaped the application window entirely and stole OS
  focus. **Not diagnosed to a specific widget class before revert** — the working hypothesis, unconfirmed,
  is that `findChildren(QWidget)` recurses into structural widgets (`QStackedWidget` pages, `QTabWidget`
  internals, `QMenu`/popup widgets — which are top-level windows in Qt even when logically nested, scroll
  viewports) that the hideEvent audit never checked for, because that audit's question was "does hiding
  this have a BEHAVIORAL side effect," never "is hiding this AT ALL, independent of any hideEvent
  override, safe for Qt's own layout/stacking/window machinery." Reverted by Pryme himself
  (`transport_bar_blur.py` confirmed back to zero diff against `HEAD`). Assessed directly, when asked
  "is this dead": **yes, not salvageable without treating it as a new, large piece of work** — a real fix
  would mean hand-curating, per panel, which children are safe leaf-content to hide vs. structural and
  must never be touched, as ongoing maintenance for every current and future widget any panel gains, not
  a one-time correction. Combined with the same-day render() dead end (entry above), TWO independent
  hide/show-avoidance strategies have now failed for two different structural reasons in one day.
  **One thread raised and deliberately left unchased this session**: `chapter_preview_label` — the real
  widget behind what this whole investigation has been calling "the tooltip" (see NOTES.md, the button
  hover/tooltip QSS investigation) — is confirmed NOT present in `TransportBarBlurOverlay._widgets`/
  `_all_tracked_widgets()` at all. The dirty tracker has zero visibility into its fade in/out, independent
  of whichever grab mechanism sits underneath. Not yet traced through to what this implies for whether
  the frost shows the label correctly TODAY, under the current (reverted-to) `_grab_and_blur`-only code.
  **Whoever picks this up next should resolve that tracking question first** — it may reframe the whole
  problem, since a fix to the grab mechanism cannot help a widget the dirty tracker never sees change in
  the first place. **This entry's underlying bug — hover hit-or-miss, tooltip/preview stuck/absent —
  remains open, unchanged by any of this.**

- [2026-08-16, Session 3] **A SIXTH direction, still viable and still committed as WIP (`30a19e3`) —
  manual paint: intercept real Enter/Leave on the 6 transport buttons and paint hover state directly
  into the overlay pixmap instead of grabbing it.** Unlike the four/five directions above, this one
  is NOT dead — the core mechanism (verified: correct Enter→paint/Leave→restore mapping, correct
  6-button set, `_button_overlay_rect`'s straddling-button clip for next_button/speed_button) remains
  committed and untouched. Three specific bugs were diagnosed this session, one fix attempt caused a
  real regression (reverted), and a second fix's re-test surfaced a third, worse, unexplained symptom
  that ended the session before a fourth patch was attempted. Full trace: NOTES.md, "manual-paint hover
  mechanism" entry, 2026-08-16 Session 3.
  - **Issue 1 — RESOLVED to root cause, Session 4 (2026-08-16), CONFIRMED PRE-EXISTING, not caused
    by this WIP.** Originally reported as "wrong color during theme hover-preview," suspected to be
    `_paint_button_hover` calling the wrong theme getter — disproven by reading `theme_manager.py`
    (`get_current_theme()` is documented and confirmed hover-inclusive). Correctly reframed from
    Pryme's screenshots: the FROST'S OWN GRABBED-RECT BACKGROUND doesn't update to a hovered theme's
    style during a live swatch preview at all, and streaks in on commit rather than landing atomically.
    **Root cause found**: `refresh_dirty`'s existing `_is_hover_active` gate (added 2026-07-20 to
    prevent a previewed theme's colors baking into the frost) suppresses EVERY grab for the entire
    duration of any hover-preview, with a second `_POST_RESTYLE_COOLDOWN_S` gate extending the freeze
    briefly after unhover — only then does one atomic catch-up grab land. Confirmed live via
    `[TIMER-TRACE]`'s existing `reason=hover_active_gate`/`reason=cooldown_gate` lines: 64+ consecutive
    declines during one real hover, one `COMPOSITED` after. **This is deliberate, pre-existing design,
    NOT something the manual-paint work introduced** — confirmed three ways: (1) an isolation flag
    (`FABULOR_SKIP_HOVER_FILTER=1`, temporary) proved `_HoverPaintFilter`'s mere presence makes no
    difference — same gate/catch-up shape with the filter installed or not; (2) a `git worktree` checkout
    of `4c4937f` (the commit immediately before this WIP — zero button-paint code exists there) reran
    the identical live test and got the identical `hover_active_gate` → `cooldown_gate` → one
    `COMPOSITED` shape. This settled a live disagreement between two Claude sessions (one argued
    pre-existing, one — this WIP's own working assumption — argued newly introduced) with direct
    evidence rather than continued argument. Full trace: NOTES.md, Session 4. **A real fix needs
    either allowing some grab during a hover-preview without re-introducing the 2026-07-20 color-bleed
    bug the gate exists to prevent, or a different mechanism entirely for keeping the frost visually
    coherent during a live preview** — not attempted, investigation only.
  - **Issue 2 (diagnosed, Fix A caused a regression, Fix B's status unconfirmed):** dirty-tracker
    grabs — both a hovered button's own repaint AND unrelated full-region ticks that happen to cover
    a button's rect — can overwrite crisp manual paint with a blurred grab result, confirmed via three
    new instrumentation blocks (`[HOVER-PAINT]`/`[HOVER-RESTORE]`/`[DIRTY-GRAB]`, gated behind
    `FABULOR_GRAB_TRACE=1` — NOT present in the reverted code, would need re-adding if revisited). Fix
    A (exclude buttons from the dirty tracker) shipped a real, live-confirmed regression: manual paint
    never handles `:pressed` (a real, separate QSS state from `:hover`), and the dirty tracker was the
    ONLY mechanism ever capturing it — excluding buttons broke pressed-state feedback in the frost
    entirely ("depressed style... not caught at all or fast... feels like the pre-fix state"). Fix A
    was reverted; Fix B (track hovered buttons, re-apply paint after any composite whose dirty region
    overlaps one) was re-tested alongside Issue 3's fix, but the re-test surfaced Issue 1's screenshot
    (see below) before Fix B could be confirmed clean on its own — **status unconfirmed, not proven
    working or broken**. If revisited: `:pressed` needs its OWN handling (a real gap, not covered by
    any current design) before buttons can safely be excluded from the tracker again — Press/Release
    interception and a `_paint_button_pressed` method were discussed as an option but never built.
  - **Issue 3 (implemented, status unconfirmed for the same reason as Fix B):** `_panel_open_snapshot`
    stale after a theme change while a panel is open — clean, scoped fix identified and implemented
    (a missing line in `force_refresh_now()` mirroring `show_for_panel`'s own snapshot capture, plus
    connecting the already-existing `theme_manager.theme_applied` signal — confirmed `Signal(dict)`,
    fires only on genuine commits — to a new guarded `_on_theme_applied` slot). Implementation itself
    was not the problem; it was re-tested alongside Fix B and neither was isolated from the other
    before the session stopped.
  - **The stopping point**: after reverting Fix A, a re-test screenshot (Waknuk theme, cover-art-pool
    hover-preview active) showed the frost's lower two-thirds as a solid bright orange-to-red gradient
    with button glyphs barely visible through it — not a wrong theme color, not the earlier
    sequenced-paint streaking, not matching any hypothesis tested this session. Pryme's own read:
    this looks like uninitialized/garbage pixel data. **Not diagnosed** — the session stopped here
    rather than propose a fourth patch, on the reasoning that three unresolved/uncertain things were
    now simultaneously true (Issue 1 still completely open, Fix B/Issue 3 never isolated from each
    other or re-verified clean, and now a new, worse, unrecognized failure) and continuing to patch
    forward without understanding the current state was not the responsible move.
  - **Outcome**: `transport_bar_blur.py` reverted to `30a19e3` (the manual-paint WIP commit) — all of
    this session's Issue 2/3 code is gone; the underlying manual-paint mechanism from the WIP commit is
    untouched. **Per Pryme's explicit instruction, take these one at a time next session, starting with
    the reframed Issue 1** (frost grabbed-rect content, not button hover color) — not the original,
    now-disproven "wrong theme getter" framing.
  - **Issue 1 — FIXED (2026-08-16, Session 5, `5d7d7e6`), scoped to the Themes tab only.** Reasoned
    through live with Pryme rather than re-derived: park/unpark (the mechanism used for Book Detail
    parking a panel's frost) does NOT apply here, because Book Detail's underlay is fully occluded
    (nothing changes, safe to freeze) while Settings/Themes's underlay is genuinely live (ticking time
    labels, the progressing chapter slider, and during a hover, the theme colors themselves) — parking
    would freeze a visibly moving scene, which is worse than the original staleness, not a fix for it.
    The shipped fix is narrower than either "make the frost track the preview live" (would mean
    reopening `hover_active_gate`) or "freeze a good-enough frame" (still wrong for a live underlay):
    **suppress the frost entirely while the Themes tab is active**, since `transport_bar_blur`
    (the strip) and `visual_area_blur` (the cover art) are already two independent calls at every
    panel-open site — skipping one while keeping the other required no changes to either blur
    mechanism itself. Wired via `PanelManager._sync_transport_bar_blur_for_settings_tab()`
    (`panels.py`), called from three sites: `QTabWidget.currentChanged` (real tab switches),
    `_start_settings_entry`'s slide-finished handler (panel OPEN — needed separately because
    reopening Settings already on Themes fires no `currentChanged`), and `apply_blur_live` (the live
    Settings > Blur toggle). Live-confirmed working by Pryme, including the reopen-on-Themes and
    toggle-while-on-Themes edge cases. **Does not touch `hover_active_gate`,
    `_POST_RESTYLE_COOLDOWN_S`, park/unpark, or the theme-preview/commit lifecycle at all** — the
    parts of this file with the worst regression track record are untouched by this fix.
  - **Three issues remain open, restated in Pryme's own framing (2026-08-16, Session 5) — all live in
    the separate manual-paint mechanism (`_HoverPaintFilter`/`_paint_button_hover`/
    `_restore_button_from_snapshot`), untouched by the Issue 1 fix above:**
    1. **Hover state inconsistent** — "sometimes blurred, sometimes crisp." Matches this entry's
       original Issue 2 (dirty-tracker grabs racing/overwriting manual paint) — Fix A regressed
       `:pressed` and was reverted; Fix B was never isolated/re-verified clean.
    2. **Tooltip not shown under an open panel.** Matches the `chapter_preview_label` tracking gap
       flagged in Session 2 above (not present in `_all_tracked_widgets()` at all) — still unresolved
       and still the recommended starting point per that entry's own note.
    3. **Pressed state not properly showing.** The confirmed Fix-A regression: manual paint has no
       `:pressed` handling at all; the dirty tracker was the only mechanism ever capturing it, and
       excluding buttons from that tracker (Fix A) broke it. A real fix needs its own
       `_paint_button_pressed` + Press/Release interception, not yet designed.
    Take one at a time, per Pryme's standing instruction — start wherever seems most tractable next
    session; no priority order given among the three.
  - **Issue 1 (hover flicker) and Issue 3 (pressed state) — both worked on Session 6 (2026-08-17),
    both landed real fixes for sub-problems but Issue 3's core mechanism was found fundamentally
    broken and is UNCOMMITTED, left as a starting point for next session.**
    - **Hover flicker (Issue 1) — FIXED, not yet committed.** Root cause: `refresh_dirty`'s per-tick
      composite (an unrelated dirty widget, or the hovered button's own QSS repaint) was overwriting
      crisp manual hover paint with a blurred grab result. Fixed by tracking which buttons are
      currently hovered (`_hovered_buttons`, populated/discarded in `_HoverPaintFilter.eventFilter`'s
      Enter/Leave branches) and re-applying `_paint_button_hover` in `refresh_dirty` for any hovered
      button whose overlay rect intersects the just-composited region. Live-confirmed working.
    - **Content redraw for `next_button`/`speed_button` — FIXED, not yet committed.** The manual fill
      is an opaque `accent_light`/`accent_dark` rect with nothing drawn on top, which hid the button's
      real content (the `▶` chapter-skip glyph, the speed value) entirely — noticeably wrong per
      Pryme, since the real QSS hover keeps content visible over its fill. Scoped to `next_button`/
      `speed_button` only — the two buttons that straddle the panel's right edge into the live
      sliver (per `_button_overlay_rect`'s own comment), so they're the only two whose manual fill is
      ever actually visible. `next_button` draws a Unicode `▶` glyph (not the SVG icon — simpler, and
      this is an approximation on a manual fill, not the real icon); `speed_button` draws its numeric
      value with the trailing "x" dropped (`button.text().rstrip('xX')`). Both blurred at a separate,
      smaller radius (`_CONTENT_BLUR_RADIUS`, tuned live to 6.0) than the background grab, and
      right-aligned within the clipped overlay rect (`target.moveRight(rect.right())`) rather than
      centered — centering left the glyph/text reading as left-aligned within the visible frosted
      strip, confirmed live. `next_button`'s glyph additionally needed a -1px vertical nudge
      (`y_offset`, tuned live) against the font metrics' own centering; `speed_button`'s digits needed
      none.
    - **Pressed state (`:pressed`, `accent_dark`) — FIXED in shape, but the underlying signal it
      depends on was found UNRELIABLE. Root problem NOT solved; a concrete next direction was agreed
      but not implemented.** Full mechanism: `_HoverPaintFilter` gained `MouseButtonPress`/
      `MouseButtonRelease` branches (`_set_pressed(obj, True/False)` — a single mutation point for
      `_pressed_buttons` that also paints/restores and arms/disarms a poll timer), mirroring
      Enter/Leave's shape. `_paint_button_hover`/`_paint_button_pressed` were unified into a shared
      `_paint_button_fill(button, theme_key)` so the accent_dark pressed fill gets the same
      content-redraw treatment as hover. `refresh_dirty`'s re-apply loop was extended to also
      re-apply pressed paint (pressed wins over hover for a button that's in both sets, matching real
      QSS specificity — a pressed button is always also "hovered" since Enter fires before Press).
      **This much works and was live-confirmed for a simple press/release.**
      The harder problem — Qt does not fire Enter/Leave during an active mouse grab (a QPushButton
      grabs the mouse for the duration of a press), so a drag-off/drag-back-in while held only
      generates `MouseMove` — went through three failed iterations before the session ended:
      1. **React to `MouseMove`, reading `isDown()` on each one.** Correct in principle (`isDown()`
         flips exactly in sync with Qt's own rect hit-test, confirmed by direct probe both
         directions) but Qt's actual `MouseMove` delivery during a SLOW drag can gap by 1.5+ seconds
         with zero events (confirmed live via a `[PRESS-BORDER-TRACE]` probe — a real slow-drag repro
         showed a 1.6s gap while the cursor was leaving a pressed button's rect), so this visibly
         lagged the real widget — Pryme's report: "hit or miss... left side catches up" only once the
         cursor moved far enough to generate another event.
      2. **Replace MouseMove-reactive with a 50ms polling timer reading `isDown()` directly**
         (`_pressed_poll_timer`/`_pressed_poll_tick`), independent of event delivery entirely. This
         regressed WORSE per Pryme's live report ("much worse... left side not changing at all")
         before being understood: `isDown()` itself is not perfectly reliable as a live-polled
         signal. Confirmed via a `[POLL-TICK-TRACE]` probe: a single poll tick read `isDown()==False`
         504ms into an otherwise-continuous, cursor-never-moved 4.7s hold — the false reading landed
         22-30ms after a `[GRAB-ENTRY]` for that same button's rect, strongly correlating the glitch
         with `_grab_and_blur`'s panel hide/show cycle (the SAME underlying hazard as the documented
         tassel hand-cursor flicker — hiding/showing a widget mid-interaction perturbs Qt's live
         pointer/press-tracking state — just corrupting `isDown()` instead of the resolved cursor
         shape). One false reading discarded the button from `_pressed_buttons` and stopped the poll
         timer, stranding the frost on the hover fill for the rest of the hold with nothing left
         polling to correct it.
      3. **Add a wall-clock release debounce** (`_pressed_false_since`, `_RELEASE_DEBOUNCE_S = 0.15`
         — require `isDown()==False` to persist 150ms before treating it as a real release, chosen as
         wall-clock rather than a tick count because grabs fire every ~5-15ms, frequently enough that
         a fixed N-tick debounce could still get unlucky within a multi-second hold). **This did NOT
         fix it** — re-tested live and found the false reading is not always a transient blip: in a
         fresh 5-second-hold repro, `isDown()` read `False` starting ~720ms in and STAYED `False`
         continuously for the rest of the hold (not a blip — a sustained wrong value for the
         remainder of the interaction). A debounce of any duration cannot distinguish a sustained
         wrong reading from a genuine release, since from the poller's perspective they're identical.
      **Session ended here — Pryme's explicit call: don't touch the grab cycle to fix this (out of
      scope), and the poller/debounce direction is dead as a sole signal.** Agreed next direction,
      NOT implemented: **poll `QCursor.pos()` against the button's rect instead of trusting
      `isDown()`** — a geometric containment check doesn't depend on Qt's internal press-state
      bookkeeping at all, so it should be immune to whatever the grab hide/show is perturbing.
      Pryme's own framing for the state machine this needs: *"Hover > Mouse pressed (painting
      pressed already here) > Outside the button coords, paint regular. Back inside button coords,
      paint pressed. Simple hover with no mouse, highlight."* This is the explicit session-opener for
      next time.
      **Diagnostic tooling left in place, all gated behind `FABULOR_GRAB_TRACE=1` (inert by
      default), useful for the next attempt:** `[ALL-EVENTS-TRACE]` (unconditional, every event type
      reaching `_HoverPaintFilter`, including `spontaneous()` — the tool that finally confirmed real
      Press/Release delivery once the earlier "Press never fires" scare turned out to be a
      timestamp-reporting mismatch, not a real bug); `[POLL-TICK-TRACE]`; `[SET-PRESSED-TRACE]`;
      `[PAINT-FILL-TRACE]`/`[PAINT-RESTORE-TRACE]` (log the computed rect and whether it came back
      empty — ruled out an empty-rect theory directly). A temporary live clock was also added to
      `title_bar.py` (`_debug_clock_timer`, `HH:MM:SS.mmm`, 50ms update) for correlating
      screen-recorded frames/screenshots against log timestamps — extracting video frames with
      `ffmpeg` and reading the burned-in clock proved far more reliable than manually timed
      screenshots for this class of investigation.
      **Nothing from this session's pressed-state work is committed.** `transport_bar_blur.py` and
      `title_bar.py` both carry a large uncommitted diff — the hover-flicker fix and the
      next/speed content-redraw are working and could be committed separately if picked apart from
      the pressed-state code, but were left together, uncommitted, since the session ended
      mid-investigation. Full trace: NOTES.md, 2026-08-17 Session 6.

  - **ALL THREE ISSUES NOW RESOLVED, 2026-08-18 (Session 1).** Full mechanism/trace: NOTES.md,
    2026-08-18 entry.
    1. **Hover flicker** — already fixed Session 6, committed `7cc8ab6`.
    2. **Tooltip not shown under an open panel** — this was always `chapter_preview_label`, the
       widget the Session 2/5 entries above flagged as missing from `_all_tracked_widgets()`
       entirely. Added to tracking; a new `_paint_preview_label` redraws its real box+text (QSS
       background/border/font, not a manual fill like the buttons) clipped to the panel-covered
       portion. Two real bugs found along the way (fade-together opacity; a stale-panel-open-snapshot
       lingering-border bug, only partially fixed — see the still-open TODO entry below) and one
       real perf bug (see #3). Committed `596e07a` (wip) then `0d39b38` (fix).
    3. **Pressed state** — root cause was NOT the signal (`isDown()` vs. `QCursor.pos()`) and NOT a
       timing lag. The poll iterated `_pressed_buttons` directly, the SAME set `_set_pressed(False)`
       removes a button from on exit — a one-way door: once a button exited during a held press, the
       poll loop could never see it again for the rest of that hold, so re-entry was silently never
       detected. ("Signal swapped to `QCursor.pos()` per the plan above, tested — 'Didn't work. No
       difference,' because the swap could never have fixed this bug.") Fixed by splitting session
       tracking (`_mouse_down_buttons`, opened/closed only by real Press/Release) from paint-state
       tracking (`_pressed_buttons`, freely toggled by the poll in either direction) — the poll now
       iterates the session set, which it never mutates, so re-entry is caught on every tick. The
       release debounce (`_RELEASE_DEBOUNCE_S`) was then shrunk, then removed entirely — the
       geometric signal has no equivalent of `isDown()`'s "brief false positive" hazard, so nothing
       needed debouncing once the one-way door was fixed. Committed `632fccf` then `33a531a`.

    **New still-open item from this session's work**, added to the top of this file's dated list:
    the chapter-preview-label frost redraw has a confirmed-live, deprioritized cosmetic residual — a
    faint border can linger after the preview fully fades, in some cases even after the fresh-grab
    fix (`0d39b38`). Pryme confirmed it does not cause any further update/hitching cost and is not
    visible under a real (non-transparent) panel background — explicitly deprioritized as "not that
    important... a harmless artifact," not reverted or further chased this session.


- [2026-08-15] **Per-source rate limits did NOT fix the rectangular artifact, the stale button
  highlight, or the missing tooltip — Pryme confirmed live, and had predicted this before testing.**
  Checkpoint C (grab frequency/breakdown by category) passed fully: marquee throttled to ~120-184ms
  gaps while scrolling and zero grabs when the title fits (`timer_active=False`, stop-when-fits
  confirmed working); time/slider categories produced zero grabs while paused in every window
  checked. Checkpoint D (live visual) is where it failed — three results, read together:
  - **Rectangular artifact: still present, unchanged.** Pryme's own words: *"has nothing to do with
    the frequency of the grabs."* This retracts the working theory this whole rate-limiting pass was
    built on (a live patch refreshing too often against a frozen backdrop) — reducing refresh
    frequency does not touch it, which means the mechanism is a compositing/coverage defect (wrong
    content, wrong position, or a region not redrawn as part of a coherent whole), not a rate
    problem. Do not re-attempt a frequency-based fix for this artifact without new evidence pointing
    at frequency specifically.
  - **Button highlight: more responsive than before (the immediate category's 0.0s window is doing
    something) but still "not acceptable," "stays stale."** The word "stale" here is the same word
    that describes the artifact's frozen backdrop — plausibly the same underlying cause surfacing as
    two symptoms, not two separate bugs. Not confirmed, just noted as the likelier reading before
    anyone spends time on it as if it were independent.
  - **Next-button tooltip: does not appear AT ALL under an open panel** — not delayed, not
    flickering, absent. This is new information this pass surfaced, not previously isolated. A
    tooltip is a separate top-level window Qt manages outside the widget tree the blur overlay
    composites, so this is unlikely to share a mechanism with the grab/composite pipeline at all —
    worth investigating as its own question (something intercepting the hover before Qt schedules
    the tooltip, or a z-order/focus interaction with the overlay) rather than folding into the
    artifact investigation.
  - **Marquee scroll through frost: "acceptable."** The one thing this pass targeted (unconditional
    high-frequency repaints from a widget with no state change) was the right diagnosis for the
    marquee specifically — confirms rate-limiting was correctly scoped there, and wrong for the
    button/tooltip/artifact cluster.
  Per this pass's own scope limit ("if still present, log to TODO.md, do not fix here"), no further
  fix attempted in this session. The per-source rate limiting code itself stays (Checkpoint C's
  results are real and the marquee behavior is confirmed correct) — it just isn't the fix for the
  artifact/highlight/tooltip cluster, which needs a different investigation.

  **RESOLVED 2026-08-15 (artifact only) — root cause found, unrelated to rate limiting.** A pixel
  probe on the live grab confirmed `content_container.grab()` (the transport path's grab source at
  the time) returns fully opaque, wrongly-colored pixels wherever `content_container` doesn't paint
  its own content — Qt's default palette color, not transparent. That made every compositing fix
  attempted (a flat `bg_main` fill, then a two-pass `bg_main`+wash fill) provably unreachable: an
  opaque `drawPixmap` on top overwrites any fill painted underneath it regardless of color. Fixed by
  reverting the grab source to `main_window` (which is fully, correctly painted) — see the "Blur grab
  hide/show side effects" entry above. Confirmed gone by Pryme on the theme that showed it. The
  **highlight-stale and tooltip-absent halves are NOT resolved** — both persist unchanged with the
  grab source reverted (Pryme: "tooltip and hover broken just like before"), confirming they were
  never caused by the grab-source/rate-limiting work at all. Both remain open; see the "Blur grab
  hide/show side effects" entry above for their status.

- **[2026-09-13] CLOSED: Tags panel: Tab was a no-op on the tag list.** The low-priority item from
  2026-09-09 ("Could be added, but not a big deal") was implemented: Tab moves the keyboard cursor
  down one row (same as Down), Shift+Tab (delivered by Qt as `Key_Backtab`) moves it up one row —
  nothing fancier, no new destination, since Tab has no "next stop" to cycle to in this view. The
  fix needed a second, non-obvious piece: `_tag_scroll`'s own per-widget `eventFilter` (the thing
  that makes Up/Down work) can never see Tab/Backtab at all — Qt resolves those two keys as
  focus-chain navigation inside `QWidget::event()` itself, before a filter installed on a single
  widget ever gets the KeyPress; only an application-level filter runs early enough. Fixed by also
  installing `TagManagerWidget`'s existing app-wide filter while the list view is visible (not just
  while the tag-detail sub-panel is open, as before), with a new branch scoped to exactly those two
  keys so every other list-view key still goes through the unaffected, unchanged
  `_tag_scroll`-scoped path. `3e21fc7`.

- **[2026-09-15] CLOSED: Hover-pickup keyboard navigation for Settings/Speed/Sleep/Sprint/Stats,
  plus the tab-bar mouse/keyboard mutual-exclusion gap it was folded into.** Two previously-paused
  TODO items closed together in one session, since the second (tab-bar reclaim) turned out to need
  the same anchor-discipline lesson the first one's two earlier failed attempts had already learned
  the hard way. Both directions (keys picking up from a stationary mouse; mouse reclaiming from a
  stale keyboard highlight) now ship for Settings' arrow-nav tabs, Speed, Sleep, Sprint, and Stats
  (including its own tab bar and "⚙" tab), plus Tags' thumbnail grid gained the mouse-reclaim half
  for the first time (it never had any reconciliation at all before this).

  **Root cause of both prior anchor-refresh failures (attempts 1/2 above), finally confirmed
  live:** pickup cannot share `_kbdnav_cursor_anchor` with `_set_keyboard_nav_active` at all, in
  either direction (write OR read-only). `_set_keyboard_nav_active(True)` fires on EVERY qualifying
  keypress, not just the first — it only skips the anchor WRITE once already active, but still runs
  unconditionally before any arrow-handler method. On the very first arrow press after a panel
  opens, that call IS the `False`→`True` transition, so it stamps `_kbdnav_cursor_anchor` to the
  mouse's CURRENT position one line before pickup logic ever runs — silently erasing the "did the
  mouse move before this press" signal pickup needs, on exactly the press that needed it most. A
  fresh `_claim_panel_focus` anchor stamp (this session's first attempt at reviving the paused item)
  was stranded the same way. Fixed by splitting off a wholly separate `_pickup_cursor_anchor`
  (app.py) that `_set_keyboard_nav_active` never touches — written only by `_claim_panel_focus` (the
  panel-open baseline) and by `_pickup_hover_target` itself after a successful pickup (so the next
  check is "moved since the last pickup," not "moved since panel open" forever). Confirmed working
  live by Pryme after this specific fix, distinguishing it from the earlier, still-broken attempt
  that read the shared anchor: "Settings, Sprint, Sleep, Speed options buttons finally pick up from
  the mouse highlight."

  **Tab-bar mouse-reclaim (the folded-in second item) — the 2026-09-10 "no mechanism confirmed"
  stuck-hover bug finally explained.** `QTabBar`'s native `:hover` is driven by real Qt
  `HoverEnter/HoverMove/HoverLeave` events (`WA_Hover`, on by default) — while the mouse rests
  somewhere else during keyboard suppression, no such event is ever delivered for the bar, so Qt's
  internal `State_MouseOver` goes stale and does not self-correct, even on later GENUINE mouse
  movement (confirmed directly: leaving and re-entering the bar does not fix it; only a click does).
  Confirmed live via a synthetic `QMouseEvent(MouseMove)` dispatch that this is NOT fixable by
  faking mouse movement — only a real `QHoverEvent` moves the internal state. Fix:
  `MainWindow._resync_tab_bar_hover` dispatches one corrective `QHoverEvent(HoverMove)` at the
  cursor's real position, from the exact call site `_set_keyboard_nav_active` already had for
  repolishing the bar, the instant keyboard mode releases (`active=False`) — pure native-`:hover`
  repaint, no custom paintEvent, so styling stays pixel-identical to native everywhere else in the
  app (a hand-painted `KbdnavHoverTabBar` overlay was tried first this session and correctly
  rejected live as visually inconsistent and fragile across desktop styles — reverted entirely, not
  shipped).

  This fix is *also* what makes the two originally-reverted suppression QSS rules
  (`[kbdnav="true"][kbdnav_style="traveling"/"kbdnav_tab_focused"] QTabBar::tab:hover:!selected`,
  themes.py) finally safe to port to `get_stats_stylesheet` — they were reverted in 2026-09-10
  specifically because native hover never recovered once suppressed, which is precisely the bug
  `_resync_tab_bar_hover` now fixes. Ported both. Without them, a keyboard-ONLY tab-bar session
  (arrow keys only, mouse never moving at all) left a stale native `:hover` visible on whichever tab
  the mouse had hovered before keyboard nav began — for the ENTIRE session, since the reclaim poll
  only ever reacts to mouse MOVEMENT and never fires at all in this case. Live-reported and
  precisely distinguished from the reclaim-poll mechanism (which traced as byte-identical between
  Settings and Stats via a temporary `[KBDNAV-TRACE]` logger, later removed): "Overall tab is
  selected, Month is hovered. I press right arrow, navigate the tabs, traveling marker is shown, the
  Month tab still has the mouse hover highlight... That's the inconsistency between two panels." Two
  more real, independent gaps found and fixed in the same pass: `_cursor_over_navigable_control`
  never recognized Stats' own tab bar OR its "⚙" tab's button rows as navigable controls at all (it
  only checked `flat_panel_rows`, which knows nothing about Stats), so the modality flag could never
  clear there by any path regardless of the QSS/hover-event fixes above.

  **Tags' thumbnail grid — new `GridHoverTracker` (hover_tracker.py), a 2-D sibling to the existing
  `ScrollHoverTracker`** (row-band hit-testing doesn't fit a multi-column grid; `childAt()` does,
  since each thumbnail is a real child widget, unlike a `QTabBar::tab` sub-control). Explicit design
  call: NO mouse-hover visual on thumbnails at all — the tracker feeds keyboard pickup silently,
  only the keyboard's own ring (`set_keyboard_focused`) ever paints. Found and fixed a real ordering
  bug in `_TagBookGrid.set_kbdnav_pos`: applying the keyboard visual BEFORE suspending the mouse
  tracker meant that seeding the keyboard cursor from a hovered thumbnail (the pickup case) had the
  tracker's own suspend-triggered clear immediately undo the visual just shown — first arrow press
  after a hover read as a no-op, second press (a real position change) was the first one that
  visibly worked. Fixed by reordering: suspend first, apply the visual last.

  **Tags list Enter/Space on a hovered-but-not-selected row** — extended to fall back to
  `ScrollHoverTracker.hovered_row` when no keyboard cursor is active, matching how Library's mouse
  hover already IS its real `currentIndex()` so Enter naturally acts on it there with no separate
  mechanism needed. Deliberately scoped to the tag LIST only, NOT the thumbnail grid below it — the
  grid's Enter/Space removes a book from the tag with no undo, and CLAUDE.md documents a real
  2026-09-13 incident (a phantom Qt key-redelivery silently removing a book) that is specifically
  why that grid requires a genuine keyboard press first, never a bare hover; extending hover-acts-
  as-select there was explicitly deferred, not decided against.

  Full session narrative (three rounds of live reports, each traced to a distinct, confirmed root
  cause rather than patched blind) in SESSION.md, 2026-09-15. `513631e`.

  **Not closed by this pass, deliberately left open:** Library's own instance of "keys don't pick up
  from mouse hover, pagination jumps to the mouse" (2026-09-08 Session 4, still below in the open
  TODO list) — named at the time as the natural next target for this same principle, but out of
  scope for this session; Book Detail's tab bar was also never wired into this keyboard-modality
  system at all (confirmed directly this session — `_kbdnav_active_panel_key` only recognizes
  settings/speed/sleep/sprint/stats), a pre-existing gap rather than a regression, explicitly
  deferred to a future session per Pryme's own call ("Fix Stats first, Book Detail later").
