## Playback

- [x] Play/pause toggles correctly
- [x] Rwd/fwd works
- [x] Prev/next works
- [x] Previos chapter grace period
- [x] Prev/next works
- [x] Beginning of the file logic correct
- [x] End of the file Play button turns into Restart
- [x] End of the file logic correct
- [x] Restart restarts directly
- [x] EOF restarts on next play
- [x] Speed button left click opens menu || wheel control, hold left click ?
- [x] Speed-adjusted time calculations (Elapsed/Total change with speed)
- [x] Speed button right click increases speed || hold right click ?
- [x] Speed button shift+right click descreases speed

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
- [x] Volume slider functional || wheel control
- [x] Volume slider draggable
- [x] Volume slider draggable

## UI

- [x] Window draggable
- [x] Current chapter corresponds to progress bar position
- [x] Book time: Elapsed (Fixed width, left)
- [x] Book time: Total/Remaining toggle (Fixed width, right, persists)
- [x] Chapter time: Elapsed (Fixed width, left)
- [x] Chapter time: Total/Remaining toggle (Fixed width, right, synced with book toggle)
- [x] Chapter name opens drop-up
- [x] Chapter names in drop-up responsive || scrollbar check when library is implemented
- [x] Chapter names in drop-up geometry || newlines after the last chapter, width, test slide up
- [x] Right click on chapter names selects them || for what reason? questionable behavior
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
- [x] Clicking on chapter name does not dismiss

## Settings panel || scrollbar issues, remove vertical line and darken, font size +1

- [x] Speed button switcheroo when settings on
- [x] All clicks on buttons dismisses and performs
- [x] Clicking on chapter name does not dismiss
- [x] Blur works || either needs improvement or removal
- [x] Library add works
- [x] Remove selected works
- [x] Rescan library works

## Speed panel || Playback or Speed?, remove vertical line and darken

- [x] Choosing speed dismisses panel
- [x] Choosing default speed does not dismiss panel
- [x] Choosing step does not dismiss panel
- [x] Left clicking on the panel does not dismiss the panel
- [x] Clicking on chapter name does not dismiss

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

## Library loading

- [x] "No library" message displayed (quotes rotation active)
- [x] Idle quotes (Random selection, justification, font scaling)
- [x] "Scan now" button triggers native folder dialog
- [x] Folder redundancy check (Parent vs Subfolder logic)
- [x] "No book selected" message displayed when indexed but idle
- [x] "Go to Library" button visibility states
- [x] Scan status banner (Progress percentage, cancel functionality)

## Library panel

- [x] Books do not flicker when shuffled (Grid re-insertion logic)
- [x] Grid/List views work correctly
- [x] Naming Pattern re-parsing (Author-Title / Title-Author live swap)
- [ ] Search filter logic
- [x] Sorting: Title, Author, Last Played, Progress, Duration
- [x] Ascending/Descending toggle works for all keys
- [x] Async cover loading (Placeholders active until loaded)
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
- [x] Theme rotation: Timer based on interval settings

## Theme engine || reorder

- [x] Theme changes apply immediately
- [x] Hover works || needs improvement
- [x] Hover preview reverts on dismiss
- [x] All clicks on buttons dismisses and performs
- [x] Clicking on chapter name does not dismiss

## Each theme here || name default needs fix, feat random

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
