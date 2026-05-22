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
- [ ] Chapter Navigation: Right-click on progress bar snaps to closest notch correctly
- [ ] Chapter Navigation: Digit key 'By name' jump respects word boundaries (e.g., "6" finds "Chapter 6" not "Chapter 16")
- [ ] Chapter Navigation: Digit key 'By index' jump uses 1-based indexing correctly
- [ ] Chapter Navigation: 800ms debounce allows for multi-digit entry (e.g., "1" then "2" for chapter 12)
- [ ] Chapter Navigation: Auto-play setting respected after digit jump
- [x] End of the file Play button turns into Restart
- [x] End of the file logic correct
- [x] Speed button left click opens menu
- [x] Speed-adjusted time calculations (Elapsed/Total change with speed)
- [x] Speed button right click increases speed || hold right click ?
- [x] Speed button shift+right click descreases speed
- [x] Mouse wheel scroll over speed button adjusts speed
- [x] Smart Rewind: Selection persists, respects chapter boundaries, and triggers on resume 
     (if away_duration >= (wait_min * 60) in player.py to test)

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

## UI

- [x] Window draggable
- [x] Current chapter corresponds to progress bar position
- [x] Book time: Elapsed (Fixed width, left)
- [x] Book time: Total/Remaining toggle (Fixed width, right, persists)
- [ ] Book time total/remaining label shows hand cursor on hover
- [x] Chapter time: Elapsed (Fixed width, left)
- [x] Chapter time: Total/Remaining toggle (Fixed width, right, synced with book toggle)
- [ ] Chapter time total/remaining label shows hand cursor on hover
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

## Settings panel

- [x] All clicks on buttons dismisses and performs
- [x] Blur works || either needs improvement or removal
- [x] Library add works
- [x] Remove selected works
- [x] Rescan library works

## Speed panel || Playback or Speed?, remove vertical line and darken

- [x] Choosing speed dismisses panel
- [x] Choosing default speed does not dismiss panel
- [x] Choosing step does not dismiss panel
- [x] Choosing Skip does not dismiss panel
- [x] Choosing Smart rewind does not dismiss panel
- [x] Left clicking on the panel does not dismiss the panel

## Sleep panel

- [x] Sleep button in sidebar opens panel
- [x] Time presets (2, 5, ..., 120 min) set timer correctly
- [x] "End of Chapter" mode works
- [x] "End of Book" mode works
- [x] Custom time input works with positive integers (Regex validation)
- [x] Custom time input rejects non-positive/invalid input
- [x] "Disable Sleep Timer" button works
- [x] Sidebar pulse animation triggers on active timer
- [x] Volume fade-out logic (Scale ratio based on remaining seconds)

## Library loading || size

- [x] "No library" message displayed (quotes rotation active)
- [x] Idle quotes (Random selection, justification, font scaling)
- [x] "Scan now" button triggers native folder dialog
- [] Folder redundancy check (Parent vs Subfolder logic)
- [x] "No book selected" message displayed when indexed but idle
- [x] "Go to Library" button visibility states
- [x] Scan status banner (Progress percentage, cancel functionality)

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
- [ ] Reset all stats prompts confirmation, clears all data, refreshes all tabs

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
- [ ] Reset all stats button prompts confirmation before executing

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
- [ ] Clicking outside the fields reverts all edits, hides Save
- [ ] Clicking another tab reverts all edits
- [ ] Closing the panel reverts all edits
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
- [ ] Metadata action button hidden for archived books (no lock/save icon)
- [ ] Stats panel: BookDayRow and FinishedBookThumb show grayscale cover for archived books
- [ ] Tag manager: _TagBookThumb shows grayscale cover for archived books

### Stats tab
- [ ] Furthest position: label + themed bar + percentage on one line, aligned with grid rows below
- [ ] Remaining: own row, speed-aware ("Xh Ym at 2x" when speed ≠ 1.0)
- [ ] Total listened, sessions, last session, started, finished display correctly
- [ ] Last session shows date, 24h time, and duration of most recent session
- [ ] Finished shows "—" / date / "Nx — last [date]" correctly
- [ ] Listening history header styled bold accent_light
- [ ] Listening history shows sessions newest-first
- [ ] Each session row: timestamp range (May 6  03:08 – 03:21) + bar + percentage
- [ ] Bar shows correct position slice within the book
- [ ] Bar and furthest position bar use theme colors (no system color fallback)
- [ ] No scrollbar visible on session list

### Tags tab
- [ ] Tag chips display all assigned tags
- [ ] Add tag field with autocomplete works; Enter and + button both add
- [ ] Remove (✕) button removes tag correctly
- [ ] Max 5 tags enforced (input flashes red on reject)
- [ ] Delete listening history button prompts confirmation, clears data, refreshes stats tab

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

## Each theme here

- [ ] Alzabo
- [ ] Anomander
- [ ] Blood Meridian
- [ ] Blue Moranth
- [ ] Brave New World
- [ ] Camorr
- [ ] Chatsubo
- [ ] Cibola Burn
- [ ] Dorian Grey
- [ ] Earthsea
- [ ] Emiko
- [ ] Eyes of Ibad
- [ ] Gormenghast
- [ ] Gravity's Rainbow
- [ ] Hear Me Roar
- [ ] Horrorshow
- [ ] Ithaca
- [ ] Jade City
- [ ] Manderley
- [ ] Melnibonéan
- [ ] Oranges Are Not the Only Fruit
- [ ] Razorgirl
- [ ] Rebma
- [ ] Red Rising
- [ ] Rivendell
- [ ] Shai-Hulud
- [ ] Shade of the Evening
- [ ] Shrike
- [ ] Sitting in the Wing Chair
- [ ] Slow Regard
- [ ] Symir
- [ ] The Bone Clocks
- [ ] The City of Stairs
- [ ] The Color Purple
- [ ] The Overlook
- [ ] The Waste Lands
- [ ] Tigana
- [ ] Tlön
- [ ] Unknown Kadath
- [ ] Urras
- [ ] Waknuk
- [ ] Winterfell