## Playback

- [x] Play/pause toggles correctly
- [x] Rwd/fwd works
- [x] Prev/next works
- [x] Beginning of the file logic correct
- [x] EOF restarts on next play
- [x] Speed button left click opens menu
- [x] Previous chapter grace period
- [ ] Rewind to beginning of chapter 1 while paused: chapter slider goes to 0, times show 00:00
- [ ] Prev/next while paused: chapter slider snaps to start of new chapter immediately
- [ ] Prev/next while playing: chapter slider snaps to start of new chapter immediately
- [ ] Prev/next pressed rapidly while playing: no stuck slider state
- [ ] **First chapter — Prev button:** anywhere in chapter 0 → rewinds to 0:00 (no grace period, no dead-end no-op)
- [ ] **First chapter — wheel scroll down on progress slider:** same as Prev — rewinds to 0:00
- [ ] **Last chapter — Next button:** no-op, no seek, no state corruption
- [ ] **Last chapter — wheel scroll up on progress slider:** no-op, no seek, no state corruption
- [ ] **Progress slider wheel scroll (chaptered book):** scroll up → next chapter; scroll down → previous chapter; chapter slider and labels update immediately
- [ ] **Progress slider wheel scroll (chapterless book):** no-op — no seek, no chapter jump, no error
- [ ] **Progress slider wheel scroll at EOF:** scroll up → no-op (already on last chapter or at EOF)
- [ ] Chapter Navigation: Right-click on progress bar snaps to closest notch correctly
- [ ] Chapter Navigation: Digit key 'By name' jump respects word boundaries (e.g., "6" finds "Chapter 6" not "Chapter 16")
- [ ] Chapter Navigation: Digit key 'By index' jump uses 1-based indexing correctly
- [ ] Chapter Navigation: 800ms debounce allows for multi-digit entry (e.g., "1" then "2" for chapter 12)
- [ ] Chapter Navigation: Auto-play setting respected after digit jump
- [x] End of the file Play button turns into Restart
- [x] End of the file logic correct
- [ ] EOF: >> (skip forward) button does nothing — no state change, no Play button appearing
- [ ] EOF: >| (next chapter) button does nothing — no state change, no Play button appearing
- [ ] EOF: chapter slider drag seeks within last chapter and turns Restart into Play
- [ ] EOF: chapter slider mouse wheel seeks within last chapter and turns Restart into Play (regression check — was already working)
- [ ] EOF: >| on last chapter of a multi-chapter book (not yet at EOF) — returns early, no seek, no corruption
- [ ] EOF: rapid >| clicks on last chapter — no freeze, no state corruption
- [x] Speed button left click opens menu
- [x] Speed-adjusted time calculations (Elapsed/Total change with speed)
- [x] Speed button right click sets current speed as global default
- [x] Speed button right click plays shimmer sweep (bottom-left → top-right glint)
- [ ] Shimmer: plays once and stops — does not loop or repeat on its own
- [ ] Shimmer: re-entrant right-clicks restart the sweep cleanly (no double-glint artefact)
- [ ] Shimmer opacity: `button_speed_shimmer` theme key overrides peak brightness (test with Alzabo theme which has an explicit value)
- [x] Mouse wheel scroll over speed button adjusts speed
- [ ] Default speed row: right-clicking at a non-preset speed (e.g. 2.35x via wheel) injects it in sorted position with 3.0x dropped
- [ ] Default speed row: injected custom button highlighted as selected
- [ ] Default speed row: closing and reopening the speed panel keeps the custom button (re-evaluated from config, not from prior UI state)
- [ ] Default speed row: clicking a different preset while custom is shown does not immediately drop the custom — only next panel open re-evaluates
- [ ] Default speed row: right-clicking at a canonical preset speed (e.g. 2.0x) shows the standard 7-button row with that preset highlighted, no custom injection
- [ ] Default speed row: whole-number speeds outside canonical list (4x, 5x, 6x, 7x, 8x) show as `N.0x` not `Nx`
- [x] Smart Rewind: Selection persists, respects chapter boundaries, and triggers on resume 
     (if away_duration >= (wait_min * 60) in player.py to test)

## Automated tests (pytest) — 2026-06-15

First automated tests exist. Run: `source fabulorenv/bin/activate && pytest tests/ -q` (pytest is
dev-only, in `requirements-dev.txt`). `tests/` drives `Player._on_time_pos_change`/seek-state directly
with NO mpv and NO QApplication (it's a near-pure state machine). Covers: seek-settle clears
is_seeking (forward + backward, VT + non-VT), cache never freezes, chapter walk/emit, VT file-switch,
the VT cross-file coordinate fix (RED→GREEN), and boundary-nav no-op contract guards. Keep these green
on any seek-path change — they catch the desync class that caused repeated regressions this session.

## VT / nav chapter-UI freezes — 2026-06-15 (both FIXED, soak-confirmed)

- [ ] **VT cross-file seek (rapid backward seek to start):** chapter slider + remaining-time keep
  tracking; NO permanent freeze. (Was: `_seek_target` stored LOCAL while settle expects GLOBAL →
  is_seeking stuck forever.)
- [ ] **Chapter[0] Prev, left-click within first ~2s:** no freeze (goes to/stays at chapter start);
  wait >2s then Prev → correctly goes to chapter beginning; right-click Prev → 00:00:00 always works.
- [ ] **Last chapter Next / Next-mash past the last chapter:** no-op cleanly, NO freeze.
- [ ] **Pause at last chapter → Next:** no-op, no freeze (clicking the slider was the old recovery).
- [ ] **M4B (not just VT):** the chapter[0]-Prev and last-chapter-Next boundary cases also must not
  freeze — the boundary fix is format-agnostic.
- [ ] Regression: normal forward VT advance, single cross-file seek, same-file seek — unaffected.
- [ ] `[VT-DESYNC]` never printed to stdout during normal use (it only fires if VT loads stop being
  serialized — a real desync, not expected).

## Chapter-seek precision & freeze (embedded M4B) — Session 3+4, 2026-06-13

Background: mpv's exact seek overshoots a chapter boundary by ~0.09s while **playing** and
undershoots by ~0.37s while **paused**. Three constants handle this (`player.py`):
`_EMBEDDED_CHAPTER_SEEK_OFFSET = -0.09` (embedded seek targets), `_PAUSED_SEEK_UNDERSHOOT_COMP = 0.37`
(forward correction on paused embedded seeks), `_CHAPTER_WALK_TOLERANCE = 0.5` (position→index walks).
VT/CUE keep `_CHAPTER_BOUNDARY_EPSILON = 0.35`.

### First-word audio fidelity (embedded M4B)
- [ ] Next chapter (playing) into a chapter that opens with a hard word/number ("Part 3", "Nineteen"): the **full first word** plays — not "3" / "teen" (no ~0.44s clip)
- [ ] Next chapter (paused) then play: first word still intact
- [ ] Prev chapter (playing & paused): lands at the chapter start, first word intact, no previous-chapter tail bleed
- [ ] Prev mid-chapter: goes to the **beginning of the current chapter** (not the previous chapter's end)

### Paused-navigation stuck-slider (the bug `_CHAPTER_WALK_TOLERANCE` fixes)
- [ ] Paused: press Next several times rapidly — chapter slider + both chapter time labels advance on **every** press (no sticking, no needing to click the slider to unstick)
- [ ] Paused: press Prev several times rapidly — advances every press
- [ ] Playing: Next/Prev never stick (regression — was already working)

### Negative-seek floor (chapter 0 / book start)
- [ ] Prev chapter at chapter 0/1 near book start: stays at/near 0%, does **NOT** jump to 100% / EOF / "finished" (the negative-absolute-seek-lands-at-EOF bug; `seek_async` floors targets at 0.05)
- [ ] After such a Prev, Next is **not** stuck (no stale `_eof` contamination)

### Undo / right-click notch (paused embedded)
- [ ] Pause at a chapter beginning → seek elsewhere → click Undo: returns to the saved position, **not** the end of the previous chapter (paused undershoot compensated)
- [ ] Right-click a chapter notch while paused: lands on the seeked position (note: starts playback; on books with audio at the very chapter start a small clip may remain — known minor, deferred)

### Chapter-list click — freeze fix (2026-06-13)
- [ ] Embedded M4B, **paused**: click various chapters in the chapter-list overlay — chapter slider + both chapter time labels update **immediately** (no freeze, no need to click the slider to revive). Audio lands on the chapter; first word plays
- [ ] Embedded M4B, **playing**: same, immediate update
- [ ] Rapid successive clicks (click chapter 3, then chapter 7 before the first settles): ends on **chapter 7**, slider not frozen, audio on 7
- [ ] Smart-rewind after a chapter-list click: clamps sanely to a chapter start (exercises the native `chapter` getter read, which is still valid post-seek)
- [ ] "Sliver" artifact gone — short chapters no longer leave a frozen sliver on the chapter slider after a click

### VT / CUE chapter-list click (must-not-break regression)
- [ ] VT (multi-file): chapter-list clicks across file boundaries load the correct chapter; slider/labels track — identical to before (uses unchanged `+0.35`). NOTE: VT first-word audio clip is a **known, separately-deferred** issue — do not expect this change to fix it
- [ ] CUE: chapter-list clicks unchanged

## Finish-book status banner (revert/dismiss)

- [ ] Reaching EOF shows "Marked as finished." banner with revert (↺) and close (✕) buttons
- [ ] Revert button click: plays a right-to-left wipe erasing the checkmark from the icon (≈550ms), pauses briefly, then the banner text swaps to "Finished status reverted."
- [ ] Revert button: icon and close (✕) button do not shift position when the text swaps between "Marked as finished." and "Finished status reverted." (status_label minimum-width fix)
- [ ] Revert button: during the wipe + pause, the icon is disabled (not clickable) but stays visible — no flicker or disappearance
- [ ] Revert button: after the text swap, the icon stays visible showing the arrow-only (no checkmark) icon, disabled — does not hide or vanish
- [ ] Revert button: db update (unfinish) only lands after the wipe + pause completes, not on the initial click
- [ ] Revert button: stats panel and library Finished view no longer show the book as finished (without needing to reopen)
- [ ] Close (✕) button while "Marked as finished." is showing: dismisses the banner and hides both eof buttons without reverting finished status
- [ ] Close (✕) button while "Finished status reverted." is showing (i.e. after a revert): dismisses the banner via a plain slide-out (no DB change — already reverted); button must NOT be missing/unresponsive at this point
- [ ] Banner auto-hides after 10s if neither button is pressed (pre-revert); finished status remains and eof buttons hide along with it
- [ ] Banner auto-hides after 5s once "Finished status reverted." is showing, if the close button isn't clicked first
- [ ] Banner does not visibly slide out and back in when the text swaps from "Marked as finished." to "Finished status reverted." (it should update in place, no dismiss-then-reappear)
- [ ] Re-finishing a previously-reverted book shows the banner again with the checkmark icon fully restored (reset_wipe) and re-marks it as finished
- [ ] Hover state: eof_revert_btn icon changes from accent to accent_light color; cursor is a pointing hand on both buttons
- [ ] No tooltip flicker or cursor flicker on either button (HoverButton/tooltip feedback-loop regression check)
- [ ] Starting a scan while the finish banner is shown: banner is taken over by scan progress, both eof buttons disappear (do not linger alongside the cancel button)
- [ ] Switching to a different book while the finish banner is visible: banner/eof buttons clear correctly, no stale `_eof_book_id` carries over to the new book
- [ ] Debug shortcut `R` simulates the EOF finished banner correctly (dev-only; confirm it doesn't ship enabled in release builds)

## Live-refresh on session write / book finish

- [ ] Finishing a book while Book Detail Panel is open: finished checkmark icon and stats tab update immediately, no need to close/reopen the panel
- [ ] Finishing a book while Library panel (Finished view) is open: book appears in the Finished view immediately
- [ ] Finishing a book while in the main window (no panels open): Library/Stats/Book-Detail show the update on next visit (lazy — no refresh cost paid while not visible)
- [ ] Closing a session without finishing the book while Book Detail Panel is open: stats (last session, history, totals) update immediately
- [ ] Reverting a finished status while Book Detail Panel is open for that book: finished checkmark disappears immediately
- [ ] Finished checkmark icon (Book Detail Panel, narrator row): shows only for books with `finished_count > 0`, sits at 0.7 opacity, aligned under the lock/save button regardless of that button's visibility (no overlap or position shift when it's hidden)
- [ ] Stats Timeline tab (streak grid or heatmap): completing a 60s+ session in the main window, then opening stats to Timeline — grid updates immediately without needing a tab round-trip
- [ ] Stats Timeline tab: completing a session while stats panel is open on Day tab — switching to Timeline shows fresh data (no manual refresh needed)
- [ ] Stats Timeline tab: completing a session while stats panel is open on Timeline tab — grid updates immediately (regression: was already working, must stay working)

## Flow animation (book switch)

- [ ] Switching from a book with progress to another with progress: both sliders animate smoothly
- [ ] Switching from progress → zero progress: both sliders animate down to 0
- [ ] Switching from zero progress → progress: both sliders animate up from 0
- [ ] Switching between two zero-progress books: both sliders snap to 0 (no animation)
- [ ] Animation speed feels proportional — large jump is fast, small jump is slow
- [ ] UI timer does not fight animation (no jitter during the move)
- [ ] Normal playback resumes correctly after animation completes
- [ ] Panel Interaction: Cover art theme update is deferred if a panel (Library/Settings) is open during book switch

## Multi-file MP3 books (virtual timeline)

### Basic playback
- [ ] Multi-file folder plays from the first file on first open
- [ ] Progress is saved and restored correctly across restarts (resumes at correct file + offset)
- [ ] Speed-adjusted time labels are correct (elapsed, remaining, chapter elapsed/remaining)
- [ ] EOF of last file shows Restart button and does not advance further

### Natural advancement
- [ ] Reaches end of file 1 → automatically advances to file 2 without pressing Play
- [ ] Advancement continues through all files to the end of the book
- [ ] Each file transition is seamless — no extra pause or Play-button-required step
- [ ] No double-advance or quadruple-advance (each file transition happens exactly once)

### Seeking
- [ ] Progress slider seek within current file works
- [ ] Progress slider seek backward into a previous file works (correct file loaded, correct offset)
- [ ] Progress slider seek forward into a next file works
- [ ] Chapter slider (within-chapter seek) works for all files, not just the first
- [ ] Rewind (skip button) crossing a file boundary works
- [ ] Forward (skip button) crossing a file boundary works
- [ ] Right-click on progress bar snaps to chapter notch correctly (any file)

### Chapter navigation
- [ ] Chapter list shows all files as chapters (filename as title, correct duration per file)
- [ ] Currently playing chapter is highlighted correctly in the chapter list when opened
- [ ] Chapter label at top shows the correct playing file name, updates on file advance
- [ ] Chapter label updates when skip buttons cross a file boundary
- [ ] Chapter label updates when slider seek crosses a file boundary
- [ ] Prev button: goes to start of current file if > grace period in, previous file otherwise
- [ ] Next button: advances to the next file
- [ ] Right-click on Prev: seeks to 00:00:00 of the entire book (file 0, offset 0)
- [ ] Chapter list left click: seeks to correct file + offset for any chapter
- [ ] Chapter list right click: seeks + forces play
- [ ] Digit key chapter jump routes correctly for VT books

### Cross-book contamination checks
- [ ] Switch from VT book mid-playback → M4B book: M4B progress slider shows correct position (not VT book's position)
- [ ] Switch from M4B book → VT book: VT book resumes at correct file + offset
- [ ] Switch VT → M4B → VT: all three states correct independently
- [ ] After switching books, previous book's chapter label does not bleed through
- [ ] Rapid book switch (VT → any): newly selected book's progress slider shows correct position, not 0% (regression: signal accumulation in load_book could cause handler to run twice, resetting progress)

## Books without chapters (chapterless)

- [ ] Chapter slider is invisible — no visual trace, layout unchanged (no pixel shift on surrounding elements)
- [ ] Chapter slider area does not show a hand cursor on hover
- [ ] Clicking where the chapter slider is has no effect
- [ ] Chapter label, elapsed and duration labels are invisible — no text visible, no cursor change on hover
- [ ] Chapter duration label shows no hand cursor (was unconditionally set in build; now ghosted)
- [ ] Prev/next chapter hover hints do not show a stale chapter name from the previously loaded book
- [ ] Switching from a chaptered book to a chapterless book: chapter UI ghosts, no layout shift
- [ ] Switching from a chapterless book back to a chaptered book: chapter UI restores fully, slider interactive, labels visible, hand cursors correct

## Single MP3 — stop-and-load seek (VBR fast positioning)

### Long seek (> 60s threshold — triggers reload)
- [ ] Seek forward > 60s on a large single MP3: lands near target position quickly (no stream-scan freeze)
- [ ] Seek backward > 60s: lands near target, no freeze
- [ ] Progress slider shows correct position after reload completes
- [ ] Chapter label correct after reload (no stale value from pre-seek position)
- [ ] Time labels (elapsed, remaining) correct after reload

### Playback state restore
- [ ] Seek > 60s while playing: playback resumes automatically after reload
- [ ] Seek > 60s while paused: stays paused after reload (play button shows ▶, not ⏸)
- [ ] Smart rewind fires correctly on resume after a reload seek (if configured)

### Short seek (< 60s threshold — normal seek_async path)
- [ ] Seek < 60s while playing: uses normal async seek, no file reload, no disruption
- [ ] Seek < 60s while paused: uses normal async seek, stays paused

### Play/pause button during rapid slider drags
- [ ] Rapid slider clicks (multiple long seeks in quick succession) while playing: button does not flicker between ▶ and ⏸
- [ ] Space bar press during or immediately after rapid slider clicks: button ends up in the correct final state
- [ ] Rapid slider clicks while paused: button consistently shows ▶ throughout, does not flash ⏸

### Non-regression (other formats must be unaffected)
- [ ] M4B seek (any distance): visual lock never activates, button behaves as before
- [ ] Multi-file MP3 folder (VT book, file < 40MB): VT seek path used, stop-and-load NOT triggered
- [ ] CUE book seek: normal path, no change
- [ ] FLAC book seek: normal path, no change

## VT stop-and-load seek (multi-file MP3, file > 40 MB)

### Same-file long seek (triggers reload)
- [ ] Seek backward > 60s within a large VT MP3 file: lands near target quickly, no stream-scan freeze
- [ ] Progress slider shows correct global position after reload (not inflated by file offset)
- [ ] Chapter label correct after reload
- [ ] Time labels correct after reload

### Playback state restore
- [ ] Seek > 60s within large VT file while playing: playback resumes after reload
- [ ] Seek > 60s within large VT file while paused: stays paused, play button shows ▶

### Short seek (< 60s — normal command_async path)
- [ ] Seek < 60s within large VT file: no reload, no disruption

### EOF and boundary protection
- [ ] Seek into final 5s of a VT file: uses normal command_async, not stop-and-load
- [ ] Seek into first 2s of a VT file (local_pos < 2.0): uses normal command_async, not stop-and-load
- [ ] Seek that crosses a VT file boundary: uses normal VT file-switch path, unaffected by stop-and-load

### Near-EOF seek guard (VT — within 2s of file end)
- [ ] Skip forward (>>) landing within 2s of current file end: returns early, no hang, no state change, natural EOF fires
- [ ] Next chapter (>|) targeting a position within 2s of file end: same early-return behaviour
- [ ] Mouse wheel over chapter slider landing within 2s of file end: same early-return behaviour
- [ ] Progress slider drag released within 2s of file end: same early-return behaviour
- [ ] Natural playback through final 2s: mpv hits EOF normally, VT advances to next file (guard only applies to seeks)

### Mouse wheel during reload
- [ ] Mouse wheel over chapter slider during a VT stop-and-load reload: does not trigger a second reload or seek to wrong position (handle_rewind/forward guard)
- [ ] Skip button press during reload: ignored (mp3_seek_reload_pending guard)

### Concurrent reload guard
- [ ] Rapid slider drags (multiple long seeks in quick succession) on large VT file: no stacked reloads, no book_ready re-emission, no DB position restore triggered mid-playback

### Non-regression
- [ ] Single-file MP3 stop-and-load: unaffected by VT changes, behaves as before
- [ ] VT file with file < 40 MB: no stop-and-load triggered regardless of seek distance
- [ ] VT file switch (seek crossing file boundary): _current_vt_index, _file_offset, _is_vt_file_switch unchanged by stop-and-load path

## Library sort views

### Sort combo population
- [ ] Fresh install (no config): combo shows Title only (no Progress or Finished), direction is ascending (↑)
- [ ] Library with progress books: Progress appears at top of combo
- [ ] Library with no progress books: Progress does not appear
- [ ] Library with finished books: Finished appears at bottom of combo
- [ ] Library with no finished books: Finished does not appear
- [ ] After deleting the last progress book's history: Progress disappears from combo on next refresh, combo falls back to Title with ascending direction
- [ ] After deleting the last finished book's history via book detail: Finished disappears immediately (history_deleted wires library refresh)

### Sort direction defaults and persistence
- [ ] Switch to each sort key in turn — verify default direction: Title ↑, Author ↑, Recent ↓, Duration ↓, Year ↓, Progress ↓, Finished ↓
- [ ] Toggle direction on Title (↑→↓), close app, reopen — Title sort opens with ↓
- [ ] Toggle direction on Progress (↓→↑), switch to Title (↓ default), switch back to Progress — Progress shows ↑ (persisted from toggle, not reset by the switch)
- [ ] Close app on Progress ↑, reopen — Progress ↑ restored
- [ ] Close app on Year ↓ (default), reopen — Year ↓ restored
- [ ] Close app on Year ↑ (toggled), reopen — Year ↑ restored

### Sort correctness
- [ ] Title ascending: A→Z, books with empty/unknown title appear at end
- [ ] Author ascending: A→Z, books with empty/unknown author appear at end
- [ ] Year descending: newest first, books with no year appear at end
- [ ] Year ascending: oldest first, books with no year appear at end
- [ ] Duration descending: longest first
- [ ] Recent: shows only books with progress, most recently played first
- [ ] Progress: shows only books with progress, highest percentage first; books with no progress do not appear
- [ ] Finished: shows only finished books, most recently finished first; unfinished books do not appear
- [ ] Null-last in all directions: books missing the active sort field always appear at the end regardless of ascending/descending

### Finished sort key
- [ ] Finishing a book (reaching EOF) causes it to appear under Finished sort on next library open/refresh
- [ ] Book finished multiple times: sort order reflects most recent finish date, not first
- [ ] Finished book deleted from history via book detail: disappears from Finished view immediately

### Search interaction with sort views
- [ ] Text search while on Progress sort: filters within in-progress books only (not all books)
- [ ] Text search while on Finished sort: filters within finished books only
- [ ] Text search while on Recent sort: filters within in-progress books only
- [ ] #tag search while on Finished sort: filters finished books by tag

## Near-EOF seek guard (non-VT: M4B, single MP3, CUE, FLAC)

- [ ] Skip forward (>>) landing within 2s of book end: returns early, no hang, mpv plays out naturally to EOF
- [ ] Next chapter (>|) on last chapter landing within 2s of end: returns early (last-chapter guard fires first, but EOF guard is backup)
- [ ] Mouse wheel over chapter slider landing within 2s of end: returns early, no hang
- [ ] Progress slider drag released within 2s of end: returns early, no hang
- [ ] Natural playback through final 2s: mpv hits EOF normally — guard only blocks seeks, not playback

## Chapter UI persistence across theme changes

- [ ] Load a book with no chapters: chapter slider transparent, labels transparent, no hand cursor
- [ ] Change theme (manual, rotation, hover): chapter UI remains ghost after theme change
- [ ] Load a chaptered book after a chapterless one: chapter UI fully restores (slider active, labels visible, hand cursor)
- [ ] Change theme while on a chaptered book: chapter UI remains fully interactive after theme change

## Cover art theme fade

- [ ] Switching book while cover art theme active: progress sliders snap instantly, no morph
- [ ] Theme hover previews: full-window crossfade, no holes or exposed areas
- [ ] Manual theme switch (right-click): full-window crossfade, no holes
- [ ] Theme rotation: full-window crossfade, no holes

## Sliders

- [x] Book progress bar functional
- [x] Book progress bar draggable
- [x] Book progress bar updates the percentage
- [x] Book progress bar updates the current chapter name
- [x] Book progress bar updates the chapter progress bar
- [x] Chapter progress bar functional
- [x] Chapter progress bar draggable
- [x] Chapter progress bar updates the percentage
- [x] Chapter progress bar updates book progress bar
- [x] Chapter notches functional along with their settings, only animate when a book is loaded
- [x] Volume slider functional
- [x] Volume slider draggable
- [ ] Volume overlay (slider) auto-hide timer resets on click, not just on wheel scroll
- [ ] Volume overlay (slider) auto-hide timer resets on drag, not just on wheel scroll
- [ ] Pressing the volume slider without moving it (press-and-hold) extends the auto-hide timer
- [ ] Volume slider, sleep-timer label, and muted icon are all pixel-aligned with the play button/chapter label center (no visible left/right drift — see NOTES.md margin bug if this regresses)

## Muted-volume icon (isolated, no sleep timer)

- [ ] Scrolling volume down to 0% (no sleep timer active) shows the muted icon immediately — no slider preview, no fade delay
- [ ] Scrolling volume up from 0% shows the normal slider overlay (2s visible + fade), not the icon
- [ ] Dragging the volume slider to exactly 0% (no sleep timer active) shows the muted icon immediately after release
- [ ] Muted icon is centered in its indicator slot (compare against the play button/chapter label — see Sliders section above)
- [ ] Muted icon recolors correctly on theme change (`slider_vol_fill` key; check a theme that overrides it and one that falls back to `text`)
- [ ] Muted icon disappears the instant volume is raised above 0%

## Muted-volume icon + sleep timer interaction

- [ ] Mute first (volume to 0%, no timer), then start a sleep timer — countdown label appears immediately, muted icon does NOT flash or linger
- [ ] Start a sleep timer first, then mute — slider overlay still previews normally (2s + fade) at 0%, then settles back to the countdown label, never to the muted icon
- [ ] While a sleep timer is active and volume is 0%, the indicator always shows the countdown, never the muted icon, for the entire duration of the timer
- [ ] Let an active sleep timer expire/get cancelled while volume is still at 0% — muted icon appears immediately once the countdown clears
- [ ] Unmuting while a sleep timer is active never reveals the muted icon at any point (no flash during the transition)
- [ ] Toggling mute on/off repeatedly while a sleep timer counts down — countdown text never gets stuck hidden behind the volume overlay or the muted icon

## UI

- [x] Window draggable
- [x] Current chapter corresponds to progress bar position
- [x] Book time: Elapsed (Fixed width, left)
- [x] Book time: Total/Remaining toggle (Fixed width, right, persists)
- [ ] Book time total/remaining label shows hand cursor on hover, only over the rendered text (not the empty reserved space to its left)
- [ ] Book time total/remaining label click only toggles when clicking the rendered text itself — clicking the empty space left of the text (within the fixed-width box) does nothing
- [x] Chapter time: Elapsed (Fixed width, left)
- [x] Chapter time: Total/Remaining toggle (Fixed width, right, synced with book toggle)
- [ ] Chapter time total/remaining label click only toggles when clicking the rendered text itself — clicking the empty space left of the text does nothing (no hand cursor on this one by design — never had one)
- [x] Chapter name opens drop-up (click or press c)
- [x] Chapter name click closes drop-up when open
- [x] Chapter names in drop-up responsive
- [x] Chapter names in drop-up geometry — 5 rows max, flush to window width, no overflow
- [x] Chapter list: left click seeks (respects pause state)
- [x] Chapter list: right click seeks + forces play
- [x] Chapter list: Enter/Return seeks (respects pause state)
- [x] Chapter list: Space seeks + forces play
- [x] Chapter list: Escape dismisses
- [x] Chapter list: Up/Down arrow moves selection
- [x] Chapter list: Left/Right arrow expands/collapses when > 5 chapters
- [x] Chapter list: expand arrow button visible only when > 5 chapters
- [x] Chapter list: expand arrow resets to collapsed state on close
- [x] Chapter list: digit keys jump to chapter (by name or by index, configurable)
- [x] Chapter list: fade in/out animation
- [x] Chapter list: chapter duration reflects current playback speed
- [x] Chapter list: clicking outside dismisses (cover art click does not also play/pause)
- [x] Chapter list: undo triggered on chapter jump > 60s * speed
- [x] Prev button right click seeks to 00:00:00 with undo
- [] Right click on chapter names toggles remaining/total time || not implemented
- [x] Toolbar buttons displayed and responsive
- [x] Art displayed when present
- [x] Size locked

## Sidebar

- [x] Slides on right click on cover art field
- [x] Opacity on on hover
- [x] Clicking on it dismisses || tbd
- [x] Hides on menu open
- [x] Hides on Speed button click
- [x] All clicks on buttons dismisses and performs
- [x] Settings clickable
- [x] Playback clickable
- [x] Stats clickable
- [x] Sleep clickable
- [x] Library clickable
- [x] Clicking on chapter name dismisses

### Soft-delete / path removal regression checks
- [ ] Removing a scan location marks books as is_deleted=1 (not hard-deleted)
- [ ] Removed books disappear from library view immediately
- [ ] Removed books' listening history and progress remain in stats panel
- [ ] Re-adding the same location resurfaces all books with progress intact
- [ ] Stats panel refreshes after path removal (rows update without manual tab switch)
- [ ] Tag manager book grid refreshes after path removal (removed-book thumbs update)

### Force-rescan missing-book detection (2026-06-26)
- [ ] Physically delete a book folder from disk, click Rescan (force) → book disappears from the library view
- [ ] Same: the deleted book is flagged is_excluded=1 (soft), NOT hard-deleted — its row, progress, and listening history still appear in the Stats panel (search by title)
- [ ] **Sticky exclusion (2026-06-27):** a deleted-then-missing-flagged book does NOT reappear on a later force rescan even if its folder is restored on disk — `is_excluded` is sticky through upserts now. The ONLY way back is the Excluded Books section (below). (Was previously: rescan cleared is_excluded — no longer true.)
- [ ] **Non-force scan does NOT remove a deleted folder's book** — re-adding a location (which triggers a non-force scan) leaves a physically-deleted book still visible (only the explicit Rescan button removes it)
- [ ] **Offline/unmounted location is safe:** with location A unmounted (root no longer exists) and location B present, clicking Rescan does NOT flag A's books missing — they stay visible (root.exists() guard via walked_locations)
- [ ] **Transient I/O hiccup is safe:** a book folder that momentarily errors on read (permission/flaky mount) during a force rescan is NOT flagged missing — it stays visible
- [ ] A force rescan with one book deleted and one present flags only the deleted one; the present book is untouched
- [ ] Excluded books (user-trashed via book detail trash button) are unaffected by the missing-detection pass — their is_excluded state is independent

### Excluded Books section — Library settings tab (2026-06-27)
- [ ] With zero excluded books, the section is entirely invisible (no header, no space) in the Library tab
- [ ] With ≥1 excluded book, "Excluded Books" header + "N books excluded ▼" line appears; cursor is a pointer hand over the line
- [ ] Count text is correct and singular/plural ("1 book" vs "2 books"); font is 1px smaller than other settings labels
- [ ] Clicking the line expands a scrollable list with a downward height animation; arrow flips to ▲; clicking again collapses, arrow back to ▼
- [ ] List shows exactly 3 rows at its fixed height; a 4th+ excluded book scrolls
- [ ] Each row is a single compact line (~21px): "Title — Author" elided right if too long; eye icon on the right
- [ ] Hovering a row slides the eye in from the right (same feel as the History tab trash reveal); hover away slides it back
- [ ] Clicking the eye restores the book immediately and silently (no confirm) — row animates out, count decrements, book reappears in the library grid
- [ ] Restore also refreshes stats panel, book detail panel, and tag manager (not just the library grid)
- [ ] Restoring the LAST row: list stays visible for the rest of this settings session; section disappears only on the NEXT settings-panel open (count rechecked)
- [ ] Section retints correctly on a theme change while the settings panel is open
- [ ] A book excluded, then restored via the eye, is NOT re-excluded by a subsequent force rescan (sticky flag was cleared by set_book_excluded(path, False))

### Naming pattern (restored 2026-06-27)
- [ ] Naming pattern section appears in the Library tab AFTER Manage folders (not before)
- [ ] "Author - Title" / "Title - Author" buttons show the selected-state highlight matching saved config
- [ ] Clicking a pattern re-splits all books' title/author from their folder names and refreshes the library grid + current book metadata
- [ ] **Lock guard:** a book whose title and/or author was edited and LOCKED (book detail panel) keeps its locked field(s) after a naming-pattern click; only unlocked fields re-parse
- [ ] Manage folders list box is shorter than before (~4 paths visible), with the naming pattern section below it

## Settings panel

- [x] All clicks on buttons dismisses and performs
- [x] Blur works || either needs improvement or removal
- [x] Library add works
- [x] Remove selected works
- [x] Rescan library works

### Library panel — multi-select folder removal and targeted rescan

- [ ] Ctrl+click / Shift+click selects multiple folders in the folder list
- [ ] "Remove selected" removes all selected folders in one operation
- [ ] Removing multiple folders updates library state correctly (books soft-deleted for all removed paths)
- [ ] "Rescan" with multiple folders selected rescans only the selected folders (targeted rescan)
- [ ] "Rescan" with no selection rescans all folders
- [ ] Right-clicking the folder list after closing a folder-picker dialog does NOT open a context menu (right-click suppressed on dialog-close)

## Speed panel || Playback or Speed?, remove vertical line and darken

- [x] Choosing speed dismisses panel
- [x] Choosing default speed does not dismiss panel
- [x] Choosing step does not dismiss panel
- [x] Choosing Skip does not dismiss panel
- [x] Choosing Smart rewind does not dismiss panel
- [x] Left clicking on the panel does not dismiss the panel

### Smart rewind sub-button visibility
- [ ] Panel opens with smart rewind Off: duration buttons (10, 20, 30) not visible
- [ ] Panel opens with smart rewind On: duration buttons visible with correct value selected
- [ ] Clicking Off: duration buttons hide immediately
- [ ] Clicking 5, 30, or 60: duration buttons appear with previously saved duration selected
- [ ] Close panel, reopen: visibility state matches current smart rewind wait setting

## Sleep panel

- [x] Sleep button in sidebar opens panel
- [x] Time presets (2, 5, ..., 120 min) set timer correctly
- [x] "End of Chapter" mode works
- [x] "End of Book" mode works
- [x] Custom time input works with positive integers (Regex validation)
- [x] Custom time input rejects non-positive/invalid input
- [ ] Right-clicking custom time input clears the field
- [ ] Pressing Escape while custom time input is focused clears the field and removes focus
- [x] "Disable Sleep Timer" button works
- [x] Sidebar pulse animation triggers on active timer
- [x] Volume fade-out logic (Scale ratio based on remaining seconds)

### Sleep timer — session integration
- [x] Selecting a sleep preset while paused: starts playback AND opens a session
- [x] Selecting a sleep preset while already playing: resumes session if active, opens new one if not
- [x] Selecting "End of Chapter" or "End of Book" while paused: starts playback AND opens a session
- [x] Sleep timer fires (timed): session is paused, 3-minute close timer starts, session is written after timeout
- [x] Sleep timer fires (end of chapter): same as above
- [x] Sleep timer fires (end of book): same as above
- [ ] Sleep timer fires then user resumes manually before 3 min: session resumes correctly, not doubled
- [ ] Sleep timer fires then 3 min elapses with no interaction: session is written with correct listened_seconds
- [x] User manually disables sleep timer while playing: session continues uninterrupted (not paused)
- [ ] `session_checkpoint.json` written within 30s of sleep-started session (crash safety)

## Library loading || size

- [x] "No library" message displayed (quotes rotation active)
- [x] Idle quotes (Random selection, justification, font scaling)
- [x] "Scan now" button triggers native folder dialog
- [] Folder redundancy check (Parent vs Subfolder logic)
- [x] "No book selected" message displayed when indexed but idle
- [x] "Go to Library" button visibility states
- [x] Scan status banner (Progress percentage, cancel functionality)

## Empty state (no library folders configured)

- [ ] "No library folders." label visible, bold 16px, ~50px from top of content area
- [ ] "Scan now" button visible, ~150px from top of content area
- [ ] Transport controls (play/pause, skip, chapter nav) hidden
- [ ] Progress slider fill hidden; groove (bg) still visible — no layout shift
- [ ] Progress slider non-interactive (click/drag does nothing, no Undo affordance)
- [ ] Sleep and Playback sidebar buttons hidden
- [ ] **Library sidebar button hidden** (nothing to browse); Settings, Stats, Tags visible at sidebar top
- [ ] **Library separator (10px gap below Library button) also hidden** — Settings button is flush to top
- [ ] Mouse wheel over cover area does nothing (no volume popup)
- [ ] Quote section (fixed 240px) visible and bottom-anchored — quotes sit at the bottom of their box
- [ ] Quotes rotate every 60 seconds automatically
- [ ] KEY_Q rotates to next quote immediately (testing shortcut)
- [ ] Status banner empty — no stale "Library updated: N books." after folders are removed
- [ ] "No book selected." and "Go to Library" NOT visible in empty state
- [ ] Cover carousel NOT visible in empty state

### Empty-state regression: add folder → load book

- [ ] Transport controls reappear on book load
- [ ] Progress slider fill reappears and tracks playback
- [ ] Sleep and Playback sidebar buttons reappear
- [ ] Library sidebar button reappears; separator restores
- [ ] Volume wheel works on cover area
- [ ] Cover art displays correctly at COVER_AREA_HEIGHT
- [ ] Quote section hidden; scan section hidden

## No-audiobooks state (library path configured, zero indexed audiobooks)

This state fires when `has_locations=True` but `get_visible_book_count()=0` (e.g. folder of text files, wrong directory, unmounted drive). Soft-deleted and excluded books do not count toward the visible book count.

- [ ] "No audiobooks in the folders added." label visible (not "No library folders.")
- [ ] "Scan now" button visible
- [ ] **Library sidebar button hidden** — same as empty state; nothing to browse
- [ ] Quote section visible with rotating quote (same as empty state)
- [ ] KEY_Q rotates quote
- [ ] "No book selected." and "Go to Library" NOT visible
- [ ] Carousel NOT visible
- [ ] Transport controls and player chrome hidden

### No-audiobooks transition tests

- [ ] Add a folder of text files → scan completes → no-audiobooks state shows correctly
- [ ] Rescan same folder → state unchanged (still no-audiobooks)
- [ ] Add a real audiobooks folder → scan completes → transitions to no-book state; Library button reappears; carousel shows
- [ ] Remove the text-files folder entirely → transitions to empty state; message changes to "No library folders."
- [ ] Soft-delete all books via trash button → state transitions to no-audiobooks (visible count = 0, excluded books don't count)

## No-book state (library indexed, no book selected)

- [ ] "No book selected." label visible, bold 16px, centered
- [ ] "Go to Library" button visible
- [ ] **Library sidebar button visible**
- [ ] Transport controls hidden
- [ ] Progress slider fill hidden; groove visible
- [ ] Progress slider non-interactive
- [ ] Sleep and Playback sidebar buttons hidden
- [ ] Mouse wheel over cover area does nothing
- [ ] Scan section NOT visible; quote section NOT visible
- [ ] Status banner shows scan progress if a background scan is running

### No-book-state cover carousel

- [ ] ≥ 12 portrait covers in library: carousel appears in carousel_holder, covers scroll left at slow continuous pace
- [ ] Portrait pool < 12, ≥ 4 square covers: carousel shows square thumbnails (92×92), scrolling
- [ ] 2–3 covers total: static centered row, no scroll, all covers visible
- [ ] 0–1 covers with art: no carousel — label and button only; carousel_holder reserves its 150px height — no layout shift
- [ ] All carousel covers are bottom-aligned within the 150px holder
- [ ] No cursor change, no hover effect, no click response on carousel
- [ ] Reshuffling: enter no-book state, load a book, remove the book → re-enter no-book state — cover order differs from previous visit
- [ ] Old carousel timer is not leaking: repeated no-book/player state cycling does not accumulate runaway timers
- [ ] Carousel appears after a scan completes (without app restart) — no carousel-pending cancellation issue

### Carousel slide-in and cover reveal animation

- [ ] On entering no-book state: carousel stripe slides in from the right over ~220ms (OutCubic ease), not a sudden appearance
- [ ] Covers do not appear during the slide — they start fading in 325ms after the stripe settles
- [ ] Covers fade in one by one with ~75ms stagger; no cover appears mid-slide
- [ ] On book load (carousel dismissed): stripe disappears without animation jitter
- [ ] Full-width stripe (300px, bleeds to both window edges) with themed fill and 1px border lines at top and bottom
- [ ] `carousel_bg` theme key controls stripe fill color; `carousel_stripe` controls border line color; both fall back correctly on themes that don't define them

### Theme bg_image suppression in no-book and empty states

- [ ] With an image-backed theme active (e.g. "The Overlook"): no-book state shows plain themed background — hexagon/carpet image is NOT visible behind "No book selected" label or carousel
- [ ] With an image-backed theme: empty state shows plain themed background — image NOT visible behind "No library folders." prompt or quote
- [ ] Load a book: bg_image reappears around the cover art (normal player look)
- [ ] Switch themes while in the no-book state: bg_image stays suppressed (no flash of the image on theme change)
- [ ] Switch themes while in the empty state: bg_image stays suppressed
- [ ] Switch themes while a book is loaded: bg_image of the new theme applies correctly

## Stats panel — finished-books carousel (FinishedBookThumb / FinishedScrollRow)

### Cache behaviour
- [ ] Open stats panel → Overall tab: recently-finished carousel populates; covers load (placeholder briefly visible on first visit if preloader hasn't reached book yet — accepted)
- [ ] Switch to Day/Week/Month tab with at least one finished book: carousel populates; covers load
- [ ] Switch away and back to same tab with same books: no rebuild, no placeholder flash — covers are cache hits, displayed immediately
- [ ] Period navigate (‹ / › arrows) to a different day/week/month and back: covers for previously-seen periods are cache hits on return, no flash

### Excluded / soft-deleted books
- [ ] Finish a book then exclude it (trash button): it still appears in the Finished carousel in stats
- [ ] Its cover loads correctly (no permanent placeholder) — preloader skips excluded books, but `_on_cover_loaded` writes to `_cover_cache` so subsequent visits are cache hits
- [ ] Cover renders in grayscale (archived book treatment)

### Redundant rebuild guard
- [ ] Rapidly switch Day → Week → Day: no duplicate thumbs, no stacking artifact
- [ ] Navigate period backward and forward to the same period: set_items called twice with same IDs — guard fires, no rebuild, thumbs unchanged
- [ ] Period query returning same books in different order: guard uses set equality, still fires — no spurious rebuild

### Horizontal scroll
- [ ] With 1 finished book: carousel shows the single thumb, no scroll arrows
- [ ] With enough finished books to overflow viewport width: right arrow (▶) appears on hover; scrolling moves thumbs; left arrow (◀) appears after scrolling; arrows hide on mouse-out
- [ ] Thumbs are not compressed — each is 47×47, not squashed to fit viewport
- [ ] With 15+ finished books: scroll to the end of the carousel — the last thumb is fully visible, not clipped at the right edge
- [ ] Placeholder and real-cover thumbs appear the same visual size (47×47) — no 1px size discrepancy between books with and without cover art

### Synchronous widget removal
- [ ] Navigate period rapidly (click ‹ several times quickly): no stacking — old thumbs removed before new ones inserted, no overlap

## Stats panel — period navigation (Day / Week / Month tabs)

### Right-click jump to boundary
- [ ] Right-click ‹ on Day tab: jumps directly to the oldest available day (no step-through)
- [ ] Right-click › on Day tab: jumps directly to the most recent day
- [ ] Right-click ‹ on Week tab: jumps to oldest week
- [ ] Right-click › on Week tab: jumps to most recent week
- [ ] Right-click ‹ on Month tab: jumps to oldest month
- [ ] Right-click › on Month tab: jumps to most recent month
- [ ] Right-click when already at the boundary: no crash, no index change, display unchanged
- [ ] Left-click still works normally after right-click handlers are installed

### Mouse wheel on period header
- [ ] Wheel up on Day header: moves to a more recent day (index decreases)
- [ ] Wheel down on Day header: moves to an older day (index increases)
- [ ] Wheel up on Week header: moves to the more recent week
- [ ] Wheel up on Month header: moves to the more recent month
- [ ] Wheel at the most-recent boundary: no wrap, no crash, display unchanged
- [ ] Wheel at the oldest boundary: no wrap, no crash, display unchanged
- [ ] Wheel on the book-row grid below the header: does NOT navigate periods (no capture outside header)
- [ ] Wheel on the finished-books carousel: does NOT navigate periods

### Scroll acceleration (Stats ⚙ tab toggle)
- [ ] "Period scroll acceleration" row visible in Stats ⚙ tab under "Day starts at"
- [ ] Default state is On on first launch (no prior preference saved)
- [ ] Preference survives app restart
- [ ] On: Day tab wheel step follows the table (≤50→1, ≤100→2, ≤200→3, ≤300→4, >300→7)
- [ ] Off: Day tab wheel always steps exactly 1 period per tick regardless of total count
- [ ] Week and Month wheel always step 1 regardless of the toggle state

### No-book-state regression: select book from library

- [ ] Carousel hides immediately on book load
- [ ] Cover art, transport controls, and full chrome restore correctly
- [ ] No carousel visible during or after book-load transition

## Scan-active button disabling

- [ ] Start a scan: Add, Remove, Rescan buttons in Library panel are visually disabled (greyed out) but still visible
- [ ] Scan completes: all three buttons re-enable
- [ ] Cancel scan: buttons re-enable immediately on cancel
- [ ] Open Library panel while a scan is already running: buttons open already disabled (not enabled-then-disabled flicker)
- [ ] Open Library panel when no scan is running: buttons open enabled

## Book removal / folder removal

- [ ] **Trash button (book detail panel):** removing the currently-playing book hides player chrome immediately; correct state shown (no-book or empty) without app restart
- [ ] **Folder removal (own folder):** removing the folder containing the active book unloads the book; player chrome disappears; correct state shown
- [ ] **Folder removal (last folder):** removing the last library folder while any book is loaded unloads the book regardless of path-match; empty state shown with Library button hidden
- [ ] **Folder removal (different folder):** removing a folder that does NOT contain the active book leaves the book loaded; only the folder list updates
- [ ] **Rescan flags loaded book missing:** with a book loaded and playing, delete its folder from disk, click Rescan → book unloads, player chrome disappears, drops to no-book-selected (or empty) state without app restart
- [ ] **Rescan flags loaded book missing — session preserved:** the unloaded book's in-progress session is flushed to Stats (not silently discarded) since on_book_removed closes the recorder before nulling the book
- [ ] **Rescan does NOT unload an unaffected loaded book:** a force rescan that flags a DIFFERENT book missing leaves the currently-loaded book playing untouched
- [ ] No stale time labels, chapter info, speed badge, or progress fill after book unload

## Library panel

### View modes
- [x] All five modes display correctly on first launch with saved mode restored
- [x] Switching between all modes is fast (target <100ms)
- [x] Grid modes (2/3/Square) use IconMode layout; List and 1-per-row use ListMode
- [x] Covers load for visible rows only on mode switch; preloaded covers appear instantly
- [x] Books times are show with speed taken into account

### Cover loading
- [x] First open: only visible rows dispatch workers
- [x] Scrolling loads covers for newly visible rows
- [x] Idle preloader starts 4 seconds after launch, pauses on interaction, resumes after 5 seconds
- [x] Covers persist across library open/close cycles (cached in _cover_cache)
- [] Missing covers show letterbox placeholder

### Sort and filter
- [x] Sorting: Title, Author, Last Played, Progress, Duration, Year
- [x] Ascending/Descending toggle works for all keys and persists across restarts
- [ ] Right-clicking search field clears the field
- [ ] Pressing Escape while search field is focused clears the field and removes focus
- [] Recent and Progress sort exclude books with progress < 1 second
- [] Progress sort orders by percentage not raw seconds
- [] Zero-progress books sort to bottom of Progress/Recent, alphabetically within that group
- [] Search filter works across title, author, narrator
- [] Naming Pattern re-parsing (Author-Title / Title-Author live swap)

### Dynamic updates (playing book)
- [x] Times update every ~1 second in all modes
- [x] Progress bar and percentage update every ~1 second
- [] Overlay in grid modes (2/3/Square) updates while visible
- [x] Accent stripe visible on playing book row in List mode

### Interaction
- [x] Left click opens book
- [x] Right click opens book details panel on stats tab
- [x] Time label click toggles remaining/total (requires progress > 1s)
- [x] Toggle does not dismiss panel or open book
- [x] Time label shows hand cursor on hover (only when book has progress > 1s)
- [ ] Time label shows arrow cursor on hover when book has no progress
- [ ] Books with no progress show total duration at 1x speed regardless of per-book speed setting
- [x] Hover overlay appears/disappears correctly in grid modes (2/3/Square)
- [x] Elision on hover works correctly on 1 per view and 2 per view modes
- [x] List mode hover-expand works for title and author independently
- [x] List mode trailing hover fade toggleable in Settings (Slow/Normal/Fast/Off, default Slow)
- [x] Hovered row stays lit while pointer is stationary; fades out only on leave

### Tag filter (from Book Detail Panel)
- [ ] Clicking a header tag chip (library context) dismisses detail panel and opens library filtered to #tag
- [ ] All view modes show the filtered result correctly (1/2/3-per-row, Square, List)
- [ ] Clicking into the search field while tag filter active clears it and allows normal typing
- [ ] Opening library manually (sidebar button) while tag filter is active clears the filter
- [ ] Opening library via tag chip a second time replaces the previous tag filter
- [ ] Tag filter does not persist across app restarts

### Theme
- [x] Theme switch updates all delegate colors immediately
- [] Library stylesheet applies to toolbar inputs and background
- [x] All five modes respect theme colors

### Performance regression checks
- [x] Library open #1: <100ms
- [x] Library open #2 (covers cached): <50ms
- [x] Mode switch: <30ms
- [] Library dismiss: <5ms

### Legacy checks (pre-rewrite)
- [] Books do not flicker when shuffled (Grid re-insertion logic)
- [x] Persistent thumbnails (Metadata updates don't wipe loaded images)
- [x] Back button dismisses

## Stats panel

### Overall tab
- [ ] Panel opens from sidebar with slide-in animation
- [ ] Listening time, books started, sessions, longest session, avg session, current streak, longest streak display correctly
- [ ] Most listened replaced with last session (book title + date)
- [ ] Current streak shows accent-colored dot when today is active
- [ ] Recently finished strip shows up to 5 thumbnails, hidden when empty
- [ ] Clicking a finished thumbnail opens Book Detail Panel on Stats tab
- [ ] Bar chart renders with correct accent color on first open (no system color fallback)
- [ ] Bar chart updates accent color on theme change
- [ ] Clicking a bar navigates to Daily tab and loads that date
- [ ] Day-start hour spinner persists across restarts
- [ ] Changing day-start hour reflects immediately on all tabs without restart
- [ ] Streak grid lit-cell count and the displayed streak number agree at every day-start-hour value — test with a session that straddles the configured day-start hour (e.g. a session from ~5 min before to ~1hr after the boundary): the grid should light BOTH adjusted-day cells (correct — the session was genuinely listened to on both), and the streak number/label must count both of those days too, not just the start day (regression: `get_streaks` used to only credit the session's start-date, undercounting relative to the grid — see NOTES.md "Streak count / grid cell mismatch"). The Day tab is expected to show the session as ONE entry on its start date only — that's by design, not a bug.
- [ ] Reset all stats prompts confirmation, clears all data, refreshes all tabs

### Timeline tab — grid transitions and label cascades

- [ ] Tassel click switches Heatmap ↔ Streak view; bookmark slides down, holds, retreats
- [ ] Tassel icon updates only once the bookmark is fully retreated (never mid-slide)
- [ ] Grid cells "pop" in/out (scale + alpha) during the reveal/conceal transition, not a plain fade
- [ ] Top date labels (Heatmap): entering sweeps left-to-right (Jun 18 first); exiting sweeps right-to-left (Jun 18 last) — true mirror, not the same sweep reversed
- [ ] Left-gutter labels (Heatmap hours, Streak dates): entering cascades top-to-bottom; exiting cascades bottom-to-top
- [ ] Opening the Stats panel with Timeline already the active tab shows the grid statically at rest — no cell/label animation plays (slide-reopen must never animate the grid)
- [ ] Switching tabs away from and back to Timeline (panel already open) re-plays the full reveal/cascade animation
- [ ] Rapid-clicking the tassel repeatedly while a heatmap↔streak transition is mid-flight: clicks are ignored (no-op) until the bookmark is fully retreated — view never hangs with both grids blank

### Timeline tab — dangling tassel decoration

- [ ] Cord renders as a draped LOOP (swings out then curves vertically down into the head), not a straight line or a diagonal bow
- [ ] Bound head + fanned fringe (multiple thread lines) are both visible — not a plain circle/dot
- [ ] At rest, the tassel sways very subtly and continuously (idle micro-sway) — barely noticeable, not distracting
- [ ] Clicking the tab: tassel swings more noticeably, decaying over ~2-3 cycles back to idle, on BOTH slide-down and retreat
- [ ] Hand cursor appears ONLY when hovering over the tab or the tassel body (head/fringe) — never over the empty space around/between them
- [ ] Clicking the tassel body (head or fringe, not just the thin tab) switches the Heatmap↔Streak view
- [ ] Clicking in the empty space around the tassel does nothing (no view switch, no hand cursor)
- [ ] Switching away from the Timeline tab and back, or closing/reopening the Stats panel: tassel sway stops while hidden (no background CPU use) and resumes cleanly on return
- [ ] Cycling themes (`T`): cord/head/fringe recolor via `accent_dark`/`bg_main` (or per-theme `tassel_cord`/`tassel_head`/`tassel_fringe` overrides if set), stay legible against varied backgrounds
- [ ] Tab itself is still unaffected: still peeks ~7px at rest, same slide distance/timing, same icon behavior as before this feature
- [ ] Setting only `tassel_fringe` in a theme recolors cord, head, AND fringe together (cord/head fall back to it); setting `tassel_cord`/`tassel_head` individually overrides only that one part
- [ ] Setting `bookmark_body` or `bookmark_icon` in a theme overrides the tab fill / icon color independently of the tassel parts

### Timeline tab — streak counter

- [ ] First-ever open of a session (real tab click, or view-switch to Streak): counts up 0 → current streak, linear pace, no slowdown
- [ ] Switching back to Streak again in the same session with no streak change: counts 0 → current again with no pause (since previous == current)
- [ ] Listen to extend the streak, then switch tabs away and back to Timeline (Streak view) in the same session: counts 0 → old value, brief pause, quick tick up to new value
- [ ] Close the app with Streak view showing a streak of N, listen to extend it, reopen the app, open Stats (lands back on Timeline/Streak since that was the last tab): number shows old value N briefly, pauses, ticks to N+1 — even though the grid cells/labels stay static (slide-reopen)
- [ ] Same scenario but landing on a non-Timeline tab on reopen: no streak animation anywhere until Timeline is actually opened
- [ ] Streak unchanged across an app restart: opening Timeline shows a plain 0 → N count, no pause
- [ ] Carry behavior (e.g. 9→10, 19→20, 29→30): counts as ordinary integers, no digit-by-digit artifacts
- [ ] Pause-then-tick only ever appears once per genuine streak change — repeated tab switches afterward show the new value with no further pause until the streak changes again
- [ ] Listen to add exactly 1 day to the streak: during leg 1 + pause, today's cell stays dimmed/not-listened-looking even though it's actually listened; once leg 2 ticks, today's cell pops in (with correct longest-run border / finished-dot if applicable) in the same instant the number increments
- [ ] Multi-day catch-up (e.g. after several days away, deltas via manual testing): each new day-cell pops in one at a time, oldest of the new days first, in lockstep with each counter increment — not all at once, not out of order
- [ ] Multi-day catch-up total duration feels proportionally quick (capped well under ~1.2s) even for double-digit day deltas — does not visibly drag

### Progress slider — percentage label count-up

- [ ] Switching books: percentage label counts up/down in lockstep with the progress slider's flow animation (same duration, finishes together)
- [ ] The label's final displayed value exactly matches what the live tracker shows on the very next 200ms tick — no visible jump/correction right as the animation ends (regression check for the truncate-vs-round bug)
- [ ] Test with a book whose saved progress's true percentage has a fractional part that would round up in the last digit (e.g. true ~73.97%) — label settles on the rounded value (74.0%), not the truncated one (73.9%)
- [ ] Cold app start (restoring last book): percentage label animates 0 → saved progress, same as a mid-session book switch

### Daily tab
- [ ] Most recent active day loads automatically on tab activation
- [ ] Left/right arrows page through active days only, disabled (dimmed) at boundaries
- [ ] Date header displays as "Friday, April 25"
- [ ] Per-book rows show cover (48×48 cropped), title, author, clock time, book time, percentage
- [ ] Rows with < 60s clock time are filtered out
- [ ] Rows sorted by clock time descending, book time as tiebreaker
- [ ] Deleted books show dimmed row with app icon placeholder
- [ ] Finished books show title in finished color
- [ ] Clicking a row opens Book Detail Panel on Stats tab
- [ ] Hand cursor on hover over rows

### Weekly tab
- [ ] Header displays as "Apr 21 – Apr 27"
- [ ] Navigation pages through active weeks only
- [ ] Per-book rows same as Daily (cover, times, percentage, finished color)
- [ ] "Finished this week" thumbnail strip appears only when books were finished that week
- [ ] Clicking a finished thumbnail opens Book Detail Panel
- [ ] Hand cursor on rows and finished thumbnails

### Monthly tab
- [ ] Header displays as "April 2026"
- [ ] Navigation pages through active months only
- [ ] Per-book rows same as Daily/Weekly
- [ ] "Finished this month" thumbnail strip appears only when applicable
- [ ] Hand cursor on rows and finished thumbnails

### Options tab
- [ ] Day-start hour spinner range 0–23, persists correctly
- [ ] Reset all stats button shows inline confirmation label above the button on first click
- [ ] Clicking the confirmation label executes the reset and refreshes all tabs
- [ ] Confirmation auto-dismisses after 7 seconds if not acted on
- [ ] Button and confirmation label are pinned to the bottom of the tab (not top)

### Stats accuracy and consistency

- [x] A 2-minute session shows "2m" in Day/Week/Month (not "1m" due to float truncation)
- [x] A session of Xm 30s–59s rounds up to X+1 in Day/Week/Month, matching Timeline
- [x] A session of Xm 0s–29s rounds down to X in Day/Week/Month, matching Timeline
- [ ] Day total and Timeline column total agree for each date (both sum raw seconds, then format)
- [ ] A session that spans midnight: Timeline splits it across two dates; Day/Week/Month assigns the whole session to the date of session_start
- [ ] Changing "Day starts at" to 6h: Day/Week/Month shift the cutoff; Timeline always cuts at 00:00

## Session crash recovery

### Checkpoint written during playback
- [ ] Play a book for 35+ seconds: `session_checkpoint.json` appears in the DB directory
- [ ] Checkpoint contains correct book_id, listened_seconds, furthest_position, session_start
- [ ] Pausing does not stop checkpoint writes (timer runs through pause)
- [ ] Stopping cleanly (pause + 3-min timeout, or book switch): checkpoint file is deleted

### Clean session close
- [ ] Play a book for 60+ seconds, then close the app normally: no checkpoint file left behind
- [ ] Play a book for < 60 seconds, then close normally: no checkpoint file (session discarded, no write)

### Crash recovery on next launch
- [ ] Simulate a crash: play 60+ seconds, kill the process (SIGKILL), relaunch — session appears in stats history
- [ ] Recovered session `listened_seconds` matches checkpoint value (not inflated by post-crash time)
- [ ] `position_end` equals `furthest_position` in recovered session (not stuck at `position_start`)
- [ ] Checkpoint file is deleted after recovery regardless of DB write success
- [ ] Simulate a crash after < 60 seconds: relaunch — no session written, checkpoint deleted
- [ ] Corrupt checkpoint file (invalid JSON): relaunch — app starts cleanly, checkpoint deleted, no crash

### Position tracking (furthest position)
- [ ] Play a book from the beginning for several minutes: `position_end` in the written session reflects actual progress, not 0.0
- [ ] Seek forward then continue playing: furthest position advances past the seek target after 15s credit window
- [ ] Seek backward: furthest position is not reduced
- [ ] Switch books (seek forward on book A, switch to book B, play): book B's furthest position advances from the start of that session (not blocked by book A's seek credit)

### Cover display in stats rows
- [ ] BookDayRow and FinishedBookThumb show the user-selected active cover (not scanner thumbnail)
- [ ] Cover updates immediately when active cover is changed in Cover Panel (no tab switch required)
- [ ] Removing the last cover from a book: placeholder icon shown immediately in stats rows
- [ ] Archived (excluded or location-deleted) books show grayscale cover in all stats rows

### Tag manager (⚙ tab)
- [ ] Tag list shows all tags with book counts
- [ ] Clicking a tag chip opens the tag panel with a book grid
- [ ] Book grid shows user-selected active cover (not scanner thumbnail)
- [ ] Archived books in the grid show grayscale cover
- [ ] Removing a book from a tag updates the grid and count immediately
- [ ] Renaming a tag updates the chip list and panel header
- [ ] Deleting a tag with confirmation removes it and returns to chip list
- [ ] After excluding a book: its thumbnail in the tag grid updates to grayscale without reopening the panel
- [ ] After a library path removal: tag manager grid refreshes to show updated state
- [ ] Closing and reopening the tag panel always lands on the tag list, not a previously viewed tag panel
- [ ] Opening panel with a tag that has 100+ books: no delay or freeze on open
- [ ] Tag panel grid with 5+ books: all 5 columns visible, rightmost column not clipped — 5×47 + 4×3 = 247px fits in the 250px content area
- [ ] Placeholder and real-cover thumbs in the tag grid appear the same visual size (47×47)

### Tag panel — inline name editing
- [ ] Editing tag name shows save icon (dirty state)
- [ ] Pressing Escape reverts edit and clears focus
- [ ] Clicking outside name field and save button reverts edit
- [ ] Saving and re-editing: dirty state correctly compares against saved name (not original)
- [ ] Duplicate name: save button turns red, clears on next keystroke
- [ ] Clicking the color dot while editing: name reverts, focus clears, picker opens

### Tag panel — color picker
- [ ] Clicking dot opens picker row
- [ ] Clicking dot again closes picker (toggle)
- [ ] Clicking empty panel area dismisses picker
- [ ] Clicking a book thumbnail while picker is open dismisses picker (no book removed)
- [ ] Book thumbnails show arrow cursor while picker is open
- [ ] After dismissing picker: book thumbnails restore hand cursor

### Tag panel — delete confirmation
- [ ] Trash button shows hand cursor in normal state
- [ ] Clicking trash shows confirmation, trash icon dims to 0.35 opacity, cursor becomes arrow
- [ ] Clicking anywhere on panel background dismisses confirmation
- [ ] Clicking a book thumbnail while confirming dismisses confirmation (no book removed)
- [ ] 7-second auto-dismiss fires if no action taken
- [ ] Confirming delete returns to tag list

### Tag panel — book thumbnail right-click
- [ ] Right-clicking a thumbnail opens Book Detail Panel (Stats tab) over the tag panel
- [ ] Tag panel remains visible behind Book Detail Panel
- [ ] Close button on Book Detail Panel returns to tag panel
- [ ] Clicking title bar dismisses both Book Detail Panel and tag panel

## Book Detail Panel

### Navigation
- [ ] Opens from library right-click with slide-in from right
- [ ] Opens from Stats panel row click
- [ ] Close button slides panel out and returns to previous view
- [ ] Panel is full window width, fully covers other panels (no bleed-through)
- [ ] Clicking anywhere outside the panel does not close it (guard in mousePressEvent)
- [ ] Theme applied correctly on first open (no system color fallback)
- [ ] Bar colors update on theme change (curr_chap_highlight / library_slider_bg)

### Header
- [ ] Cover displays at correct aspect ratio, max 120×120
- [ ] App icon placeholder shown when no cover available
- [ ] Title and author always shown
- [ ] Narrator and year shown only when present; hidden fields retain layout space (no shift)
- [ ] Duration label shown when duration available; hidden otherwise
- [ ] Duration toggles between wall-clock and speed-adjusted on click (only when speed ≠ 1.0)
- [ ] Duration resets to wall-clock when a new book is loaded

### Inline metadata editing
- [ ] Clicking any header field enters edit mode (all four fields become editable)
- [ ] Narrator and year fields appear with placeholders even when previously hidden
- [ ] Year field rejects non-digit characters; minus sign allowed as first character only
- [ ] Save label appears only when at least one field differs from original value
- [ ] Save label disappears if edits are reverted back to original values
- [ ] Enter in any field saves and shows "Saved" for 1 second
- [ ] Clicking Save saves and shows "Saved" for 1 second
- [ ] Pressing Escape reverts all edits and exits edit mode
- [ ] Clicking outside the fields reverts all edits, hides Save
- [ ] Clicking another tab reverts all edits
- [ ] Closing the panel reverts all edits
- [ ] IBeam cursor visible on all four metadata fields in both read-only and edit mode

### Metadata field context menu (Cut/Copy/Paste/Delete)
- [ ] Right-clicking a metadata field with selected text shows Cut/Copy/Delete enabled, Paste enabled if clipboard non-empty
- [ ] Right-clicking with no selection and clipboard empty: menu does not appear
- [ ] Right-clicking with no selection but clipboard has text: only Paste shows enabled (read-only field suppresses it)
- [ ] Cut removes selected text and copies to clipboard
- [ ] Copy copies selected text without removing it
- [ ] Paste inserts clipboard text at cursor
- [ ] Delete removes selected text without copying
- [ ] Menu dismisses after any action
- [ ] Menu dismisses when clicking outside it
- [ ] Menu stays within the application window bounds (does not bleed off-edge)
- [ ] Menu styled correctly with current theme (no system default appearance)
- [ ] Right-clicking the tag input field shows same menu with correct state

### Tag name field context menu (Tag manager)
- [ ] Right-clicking tag name field shows context menu with correct enabled state
- [ ] All four actions work correctly
- [ ] Menu dismisses on action and on click-outside
- [ ] Save updates title and author in library panel immediately (no panel close required)
- [ ] Save updates narrator and year in library panel immediately (no panel close required)
- [ ] Rescan after save: locked fields are not overwritten; unlocked fields update from metadata

### Metadata lock
- [ ] Saving a changed field sets a lock on that field (lock icon appears)
- [ ] Lock icon click unlocks all four fields (lock-open icon, auto-hides after 2.5s)
- [ ] Locked fields survive a library rescan unchanged
- [ ] Unlocked fields are overwritten by a rescan as normal
- [ ] Click-outside while editing reverts to pre-edit state (locked → lock icon, unlocked → hidden)
- [ ] Archived books: metadata action button is always hidden regardless of lock state

### Finished toggle (check icon, narrator row)
- [ ] Unfinished book: check icon slot is visible but empty at rest; hovering reveals a 30%-opacity dimmed check
- [ ] Finished book: check icon shows at 0.7 opacity at rest; hovering brightens to 0.9 opacity
- [ ] Clicking the check icon on an unfinished book shows "Click to mark this book finished" confirm over the narrator label
- [ ] Clicking the check icon on a finished book shows "Click to mark this book unfinished" confirm over the narrator label
- [ ] Clicking anywhere outside the confirm label and check icon dismisses without acting
- [ ] Confirm auto-dismisses after 7 seconds without acting
- [ ] Closing the panel while confirming dismisses without acting
- [ ] Confirming mark-finished: check icon fills in immediately; book appears in Finished tab/filter/stats immediately (history_deleted fan-out)
- [ ] Confirming mark-finished: streak grid is NOT lit for today — a manual finish is streak-neutral (source='manual', invisible to streak queries)
- [ ] Confirming mark-unfinished: check icon clears immediately; book removed from Finished tab/filter/stats immediately
- [ ] Confirming mark-unfinished: if the book was previously finished via EOF (source='playback'), that day's streak cell re-evaluates — may darken if no session backed it
- [ ] Mark-finished and mark-unfinished are mutually exclusive with the remove-from-library confirm (one dismisses the other)
- [ ] Finished toggle works for archived (excluded) books — no guard blocks it
- [ ] Finished toggle works for a book currently playing (no interference with session recording)

### Book removal (trash button)
- [ ] Trash button visible for normal (non-excluded) books
- [ ] Clicking trash shows inline "Click to remove from library" confirmation label
- [ ] Clicking the confirmation removes the book from the library view and closes the panel
- [ ] Clicking anywhere else (outside label and button) dismisses the confirmation without removing
- [ ] Closing the panel while confirming dismisses without removing
- [ ] After removal: book disappears from library panel immediately
- [ ] After removal: stats panel active tab refreshes (row counts update)
- [ ] After removal: tag manager book grid refreshes if the removed book was tagged
- [ ] Removed book's listening history and progress are preserved (visible in stats for that path)
- [ ] Re-scanning the removed book's folder resurfaces it in the library
- [ ] Trash button hidden when book is already excluded (opened from stats history)

### Archived book state (excluded or location-deleted)
- [ ] Opening an excluded book from stats history: cover shown in grayscale
- [ ] Opening a location-deleted book from stats history: cover shown in grayscale
- [ ] Trash button hidden for archived books
- [ ] Ghost icon appears in the trash button slot for archived books, same size, no cursor change, no tooltip
- [ ] Ghost icon color matches theme accent (updates on theme change)
- [ ] Metadata action button behaves normally for archived books (save/lock/hidden follows same logic as non-archived)
- [ ] Removing a book from the library via the trash button when opened from Library: panel closes
- [ ] Removing a book from the library via the trash button when opened from Stats or Tags: panel stays open, trash button replaced by ghost icon, cover goes grayscale, metadata action button hides
- [ ] Stats panel: BookDayRow and FinishedBookThumb show grayscale cover for archived books
- [ ] Tag manager: _TagBookThumb shows grayscale cover for archived books

### Stats tab
- [ ] Furthest position: label + themed bar + percentage on one line, aligned with grid rows below
- [ ] Remaining: own row, speed-aware ("Xh Ym at 2x" when speed ≠ 1.0)
- [ ] Total listened, sessions, last session, started, finished display correctly
- [ ] Last session shows date, 24h time, and duration of most recent session
- [ ] Finished shows "—" / date / "Nx — last [date]" correctly
- [ ] Listening history header ("Recent history") hidden when there are no sessions; visible otherwise
- [ ] Recent history shows max 4 sessions; last entry always anchored to same vertical position regardless of count (1–4 entries)
- [ ] Each session row: timestamp range + delta label (e.g. +98.6%) + bar + percentage
- [ ] Delta label does not clip at wide values (e.g. +98.6%)
- [ ] Bar and furthest position bar use theme colors (library_slider_fill / library_slider_bg)

### History tab
- [ ] All sessions shown newest-first, rows top-aligned with no extra spacing between them
- [ ] Rows span full tab width; date/delta on left and percentage on right retain 10px internal padding
- [ ] No scrollbar visible when few sessions; scrollbar appears (or area scrolls) when sessions overflow
- [ ] Hover a row → X icon slides in from right edge (45px, 150ms OutCubic)
- [ ] Mouse leaves row without clicking → X slides back out (150ms InOutQuad)
- [ ] Click X → "Delete this session?" slides in from left of X (X stays visible); 7s auto-dismiss timer starts
- [ ] While confirmation armed: hovering another row shows its X normally
- [ ] While confirmation armed: clicking another row's X dismisses previous confirmation AND its X, arms new row
- [ ] Confirmation auto-dismisses after 7 seconds; row returns to normal
- [ ] Click "Delete this session?" → row collapses (150ms height animation), rows shift up, container resizes
- [ ] After delete: Stats tab "Total listened", "Sessions", and recent history widget update correctly
- [ ] Click outside the confirming row (anywhere in panel) → confirmation AND X both dismiss
- [ ] Switch to another tab while confirmation armed → confirmation and X dismiss
- [ ] Close book detail panel while confirmation armed → confirmation and X dismiss, no stale timer
- [ ] Only one row can be in confirming state at a time
- [ ] "Delete listening history" button: shows hand cursor when idle; clicking shows confirm label above button, button switches to arrow cursor and stops accepting clicks
- [ ] "Delete listening history" confirm label: clicking it deletes all history, refreshes stats, auto-dismisses after 7s if not acted on
- [ ] "Delete listening history" button does not jump or shift position when confirm label appears or disappears
- [ ] Click outside "Delete listening history" confirm label (but not on button) → confirm dismissed, button re-enabled with hand cursor
- [ ] Click on button area while confirm label is visible → nothing happens (button stays disabled, confirm stays)

### Tags tab
- [ ] Tag chips display all assigned tags
- [ ] Add tag field with autocomplete works; Enter and + button both add
- [ ] Remove (✕) button removes tag correctly
- [ ] Max 5 tags enforced (input flashes red on reject)
- [ ] "Tag management" button visible when opened from library or stats
- [ ] "Tag management" button hidden when opened from tag panel (context='tags')
- [ ] Clicking "Tag management": all panels dismiss, then tag panel slides in

### Header tag chips (under year field)
- [ ] Tags shown in header row with correct accent color (● tag format)
- [ ] Opened from library: tag labels show hand cursor on hover
- [ ] Opened from library: clicking a tag dismisses panel, opens library filtered to #tag
- [ ] Opened from library: right-clicking a tag does nothing (no "Copy link location" menu)
- [ ] Opened from stats: tag labels show no cursor change, clicks do nothing
- [ ] Header tags re-render with correct colors on theme change while panel is open
- [ ] Adding or removing a tag on the Tags tab updates the header row immediately

## Cover Panel

### Opening and loading
- [ ] Cover panel opens from the Book Detail Panel (correct trigger)
- [ ] Panel loads thumbnails for the current book's covers from the DB
- [ ] Scanner-extracted cover (slot 0, locked) appears as the first thumbnail
- [ ] Active cover is shown with an accent outline
- [ ] Preview area shows the active cover rendered at correct aspect ratio
- [ ] Panel shows correct state for a book with no covers (empty thumbnails, blank preview)
- [ ] Theme colors apply correctly on open (no system color fallback)
- [ ] Theme change updates panel colors without reopening

### Thumbnail interaction
- [ ] Hovering a thumbnail shows a preview overlay (no commit yet)
- [ ] Left-clicking a thumbnail sets it as active and updates the main player cover
- [ ] Right-clicking (or delete) a non-locked thumbnail removes it
- [ ] Locked thumbnail (slot 0, scanner cover) cannot be deleted
- [ ] Active cover outline moves correctly when a new cover is activated
- [ ] Preview renders with correct fit mode (Fit / Fill / Stretch)

### Fit mode
- [ ] Fit button: cover letterboxed within preview area, no cropping
- [ ] Fill button: cover fills preview area, cropped to fit
- [ ] Stretch button: cover stretched to fill, aspect ratio ignored
- [ ] Fit mode selection persists per-cover across panel close/reopen
- [ ] Fit mode change takes effect immediately in preview

### Adding covers
- [ ] Add cover button opens file dialog (image formats only)
- [ ] Selected image is added as a new thumbnail and becomes active
- [ ] Adding a duplicate path does not create a second entry
- [ ] Error shown for unsupported file types or unreadable images
- [ ] New cover reflects in the main player cover immediately after add + activate
- [ ] First cover added to a no-cover book: automatically set as active, shown in preview immediately (no click required)
- [ ] Books with an embedded locked cover: adding a user cover does NOT auto-select it (normal behavior)
- [ ] After deleting all user covers from a previously no-cover book: next add auto-selects again
- [ ] Active cover change propagates immediately to: main player, library panel, book detail header, stats panel rows, tag manager book grid

### Persistence
- [ ] Active cover persists across app restarts (correct cover shown on next launch)
- [ ] Cover order (sort_order) is preserved across restarts
- [ ] Deleting a cover removes it from DB and thumbnail strip; active falls back to next available
- [ ] Switching to another book and back restores the correct cover state for each book

## Persist search filter (Settings → Library)

- [ ] Master Off by default on fresh install
- [ ] Clicking On: Tag, Text, Year sub-buttons appear, all selected
- [ ] Clicking On when all three sub-buttons were previously Off: sub-buttons reset to all On
- [ ] Clicking Off: sub-buttons hide immediately
- [ ] Close settings, reopen: sub-button visibility matches master state
- [ ] All three sub-buttons toggled Off, panel closed and reopened: master shows Off, sub-buttons hidden
- [ ] With master On and Tag enabled: tag filter (#tag) in search field persists across restart
- [ ] With master On and Text enabled: plain text filter persists across restart
- [ ] With master On and Year enabled: year filter (>NNNN) persists across restart
- [ ] With master On but Tag disabled: tag filter not restored on restart
- [ ] With master Off: search field always empty on launch regardless of previous filter

## Saving states

- [x] Book progress restored
- [x] Chapter name restored
- [x] Theme restored
- [x] Speed setting restored
- [x] Default speed setting 
- [x] Step restored || name
- [x] Sort by view restored
- [x] Grid/list view restored
- [x] Naming Pattern selection restored
- [x] Show Remaining Time toggle restored
- [x] Chapter Scroll mode restored
- [x] Chapter Hints toggle restored
- [x] Chapter digit jump mode restored (by name / by index)
- [x] Chapter digit autoplay setting restored (Auto-play / Jump only)

## Appearance & UX

- [x] Chapter Scroll: Slow mode (80ms interval, ping-pong with pauses)
- [x] Chapter Scroll: Normal mode (40ms interval)
- [x] Chapter Scroll: Off mode (Centered elided text)
- [x] Chapter Hints: Hover triggers fade-in/out
- [x] Chapter Hints: Click on transport dismisses hint immediately
- [x] Chapter Hints: Background scales to text width (Size Policy Maximum)
- [x] Settings: Consistency in button groups (Blur, Fade, Hints, Scroll)
- [x] Undo button: Sequence logic (anchors to first click during rapid seeking)
- [x] Undo button: Threshold scales with playback speed (60s * speed)
- [ ] Undo button: Long rewind (hold << or right-click <<) triggers undo point
- [ ] Undo button: Long forward (hold >> or right-click >>) triggers undo point
- [ ] Undo button: Mouse wheel over chapter slider triggers undo point
- [ ] Undo button: Short skip (<< / >> tap) does NOT trigger undo point
- [ ] Undo button: Animation — slide-in and slide-out both complete cleanly with no ghost or flicker
- [ ] Undo button: Triggering undo while already visible refreshes the hide timer (does not restart animation)
- [ ] Undo button: Triggering undo while slide-in is in progress is ignored (no duplicate animation)
- [ ] Undo button: Triggering undo while slide-out is in progress: slide-out interrupted, button slides back in
- [x] Theme rotation: Timer based on interval settings

## Audio Processing || no effect

- [] Normalization (Speech Compression) toggles correctly
- [x] Voice Boost equalizer applies mid-range lift
- [] Stereo/Mono switch works
- [] Channel swap (L ↔ R) functions correctly
- [] L/R balance slider adjusts volume bias
- [x] Balance slider snaps to center (0) when near notch
- [x] Balance slider notch is visible at dead center
- [x] "Reset to defaults" button hidden when settings are default
- [x] "Reset to defaults" restores all audio settings and hides itself

## Theme engine

- [x] Theme changes apply immediately
- [x] Hover works
- [x] Hover preview reverts on dismiss
- [x] All clicks on buttons dismisses and performs
- [ ] Press `T` to rotate theme, then immediately right-click the drag area to open the sidebar while the fade is still running: the new theme applies fully and cleanly — no slider left painted in the previous theme's color (regression check for the mid-fade interrupt strand)
- [ ] Same with rapid `T` spam followed by a well-timed right-click: no half-this-half-that "mulatto" theme that persists; any transient resolves on the next tick

## Cover art based theme

- [] Off mode: label dimmed, left-click → With pool, right-click → activate + With pool
- [] With pool: label bold, left-click → Off + deactivate if active, right-click → activate
- [] Active state: underline on Cover art based theme label when cover theme is displayed
- [] Underline moves to pool theme on right-click of any pool entry
- [] Disabled (greyed) when With pool selected but no cover loaded
- [] Switching to Exclusive hides pool block, keeps mode button selected
- [] Switching back from Exclusive restores pool block
- [] Change now button includes cover theme as a candidate in With pool mode
- [] panel_opacity_hover visible (not fully opaque) in panels when cover theme active
- [] No cover + Exclusive: silently uses pool, no mode revert

## CUE file support

- [ ] Set chapter source to ".cue" in Settings → Library
- [ ] Load an M4B with a valid cue file in the same folder
- [ ] Verify chapter list shows cue titles (including any extra entries like "Opening Credits", "PART I")
- [ ] Verify chapter label updates correctly on playback and seek
- [ ] Verify chapter list clicks navigate to correct position
- [ ] Verify Prev/Next navigate correctly using cue chapters
- [ ] Verify chapter slider stays within correct chapter boundaries
- [ ] Verify notches on progress slider correspond to cue chapters
- [ ] Set chapter source back to "Embedded" — verify embedded chapters restore correctly
- [ ] Test with cue file containing BOM (Windows ripper output)
- [ ] Test with cue file where FILE stem doesn't match audio file — verify silent fallback to embedded
- [ ] Test with cue file where first timestamp is not 0:00:00 — verify rejection and fallback
- [ ] Test with non-monotonic timestamps — verify rejection and fallback
- [ ] Test with timestamp beyond file duration — verify rejection and fallback
- [ ] Test with only one TRACK entry — verify rejection and fallback
- [ ] Test with multiple cue files in folder — verify correct file selected by stem match, fallback if no match
- [ ] Verify app start restores to correct chapter with cue active
- [ ] Verify Undo after Next shows correctly with cue active

## Each theme

- [ ] Alzabo
- [ ] Annihilation
- [ ] Anomander
- [ ] Blood Meridian
- [ ] Blue Moranth
- [ ] Brave New World
- [ ] Camorr
- [ ] Cerulean Sea
- [ ] Chatsubo
- [ ] Cibola Burn
- [ ] City of Stairs
- [ ] Crimson Guard
- [ ] Dorian Grey
- [ ] Driftmark
- [ ] Earthsea
- [ ] Emiko
- [ ] Eyes of Ibad
- [ ] Fifth Season
- [ ] Fire and Blood
- [ ] Galatea
- [ ] Goldfinch
- [ ] Gormenghast
- [ ] Gravity's Rainbow
- [ ] Hear Me Roar
- [ ] Highgarden
- [ ] Jade City
- [ ] Lilac Girls
- [ ] Manderley
- [ ] Melnibonéan
- [ ] Not the Only Fruit
- [ ] Pink Institute
- [ ] Piranesi
- [ ] Plum Island
- [ ] Pyke
- [ ] Razorgirl
- [ ] Rebma
- [ ] Red Rising
- [ ] Rivendell
- [ ] Rose Code
- [ ] Shai-Hulud
- [ ] Shade of the Evening
- [ ] Shrike
- [ ] Sitting in the Wing Chair
- [ ] Slow Regard
- [ ] Storm's End
- [ ] Sunspear
- [ ] The Color Purple
- [ ] The Eyrie
- [ ] The Overlook
- [ ] Tigana
- [ ] Turquoise Days
- [ ] Urras
- [ ] Violeta
- [ ] Waknuk
- [ ] Wasp Factory
- [ ] Waste Lands
- [ ] Winterfell
- [ ] Yellowface