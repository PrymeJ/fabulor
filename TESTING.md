## Playback

- [x] Play/pause toggles correctly
- [x] Rwd/fwd works
- [x] Prev/next works
- [x] Beginning of the file logic correct
- [x] EOF restarts on next play
- [x] Speed button left click opens menu
- [x] Previous chapter grace period
- [x] End of the file Play button turns into Restart
- [x] End of the file logic correct
- [x] Speed button left click opens menu
- [x] Speed-adjusted time calculations (Elapsed/Total change with speed)
- [x] Speed button right click increases speed || hold right click ?
- [x] Speed button shift+right click descreases speed
- [x] Mouse wheel scroll over speed button adjusts speed
- [x] Smart Rewind: Selection persists, respects chapter boundaries, and triggers on resume 
     (if away_duration >= (wait_min * 60) in player.py to test)

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
- [x] Volume slider functional
- [x] Volume slider draggable

## UI

- [x] Window draggable
- [x] Current chapter corresponds to progress bar position
- [x] Book time: Elapsed (Fixed width, left)
- [x] Book time: Total/Remaining toggle (Fixed width, right, persists)
- [x] Chapter time: Elapsed (Fixed width, left)
- [x] Chapter time: Total/Remaining toggle (Fixed width, right, synced with book toggle)
- [x] Chapter name opens drop-up
- [x] Chapter names in drop-up responsive
- [x] Chapter names in drop-up geometry || newlines after the last chapter, width, test slide up
- [x] Right click on chapter names toggles remaining/total time || not implemented
- [x] Toolbar buttons displayed and responsive
- [x] Art displayed when present
- [x] Size locked

## Sidebar

- [x] Slides on right click on cover art field
- [x] Opacity on on hover
- [x] Clicking on it dismisses || tbd
- [x] Hides on menu open
- [x] Hides on Speed button click || too fast?
- [x] All clicks on buttons dismisses and performs
- [x] Settings clickable
- [x] Playback clickable
- [x] Clicking on chapter name dismisses

## Settings panel || scrollbar issues, remove vertical line and darken, font size +1

- [x] Speed button switcheroo when settings on
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
- [] Hover overlay appears/disappears correctly in grid modes (2/3/Square)
- [] List mode hover-expand works for title and author independently
- [x] List mode trailing hover fade toggleable in Settings (Slow/Normal/Fast/Off, default Slow)
- [x] Hovered row stays lit while pointer is stationary; fades out only on leave

### Theme
- [x] Theme switch updates all delegate colors immediately
- [] Library stylesheet applies to toolbar inputs and background
- [] All five modes respect theme colors

### Performance regression checks
- [x] Library open #1: <100ms
- [x] Library open #2 (covers cached): <50ms
- [x] Mode switch: <30ms
- [] Library dismiss: <5ms

### Legacy checks (pre-rewrite)
- [] Books do not flicker when shuffled (Grid re-insertion logic)
- [x] Persistent thumbnails (Metadata updates don't wipe loaded images)
- [x] Back button dismisses

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
