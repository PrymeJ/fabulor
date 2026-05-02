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
- [x] Chapter time: Elapsed (Fixed width, left)
- [x] Chapter time: Total/Remaining toggle (Fixed width, right, synced with book toggle)
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
- [x] Hover overlay appears/disappears correctly in grid modes (2/3/Square)
- [x] Elision on hover works correctly on 1 per view and 2 per view modes
- [x] List mode hover-expand works for title and author independently
- [x] List mode trailing hover fade toggleable in Settings (Slow/Normal/Fast/Off, default Slow)
- [x] Hovered row stays lit while pointer is stationary; fades out only on leave

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

## Book Detail Panel

### Navigation
- [ ] Opens from Daily/Weekly/Monthly row click with slide-in from right
- [ ] Opens from Overall finished thumbnail click
- [ ] Back button slides panel out to the right and returns to stats
- [ ] Panel is full window width, fully covers stats panel (no bleed-through)
- [ ] Theme applied correctly on first open (no system color fallback)
- [ ] Accent color updates on theme change

### Header
- [ ] Cover displays at correct aspect ratio, max 120×120
- [ ] App icon placeholder shown when no cover available
- [ ] Title, author shown always
- [ ] Narrator and year shown only when present, hidden when absent
- [ ] Deleted book (book_path NULL) handled gracefully

### Stats tab
- [ ] Furthest position progress bar shows correct percentage and remaining time
- [ ] Furthest position fetches duration from DB when not in book_data
- [ ] Total listened, sessions, started date display correctly
- [ ] Finished shows "—" when never finished
- [ ] Finished shows date when finished once
- [ ] Finished shows "Nx — last [date]" when finished more than once
- [ ] Day-by-day bar chart renders with correct data and accent color
- [ ] Delete listening history prompts confirmation, clears data, refreshes panel

### Metadata tab
- [ ] Placeholder shown (implementation pending)

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
