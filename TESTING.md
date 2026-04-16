## Playback

- [] Play/pause toggles correctly
- [] Rwd/fwd works
- [] Prev/next works
- [] Previos chapter grace period
- [] Prev/next works
- [] Beginning of the file logic correct
- [] End of the file Play button turns into Restart
- [] End of the file logic correct
- [] Restart restarts directly
- [] EOF restarts on next play
- [] Speed button left click opens menu || wheel control, hold left click ?
- [] Speed-adjusted time calculations (Elapsed/Total change with speed)
- [] Speed button right click increases speed || hold right click ?
- [] Speed button shift+right click descreases speed
- [] Mouse wheel scroll over speed button adjusts speed
- [] Smart Rewind: Selection persists, respects chapter boundaries, and triggers on resume 
     (if away_duration >= (wait_min * 60) in player.py to test)

## Sliders

- [] Book progress bar functional
- [] Book progress bar draggable
- [] Book progress bar updates the percentage
- [] Book progress bar updates the current chapter name
- [] Book progress bar updates the chapter progress bar
- [] Chapter progress bar functional
- [] Chapter progress bar draggable
- [] Chapter progress bar updates the percentage
- [] Chapter progress bar updates book progress bar
- [] Volume slider functional
- [] Volume slider draggable
- [] Volume slider draggable

## UI

- [] Window draggable
- [] Current chapter corresponds to progress bar position
- [] Book time: Elapsed (Fixed width, left)
- [] Book time: Total/Remaining toggle (Fixed width, right, persists)
- [] Chapter time: Elapsed (Fixed width, left)
- [] Chapter time: Total/Remaining toggle (Fixed width, right, synced with book toggle)
- [] Chapter name opens drop-up
- [] Chapter names in drop-up responsive || scrollbar check when library is implemented
- [] Chapter names in drop-up geometry || newlines after the last chapter, width, test slide up
- [] Right click on chapter names selects them || for what reason? questionable behavior
- [] Toolbar buttons displayed and responsive
- [] Art displayed when present
- [] Size locked

## Sidebar

- [] Slides on right click on cover art field
- [] Opacity on on hover
- [] Clicking on it dismisses || tbd
- [] Hides on menu open
- [] Hides on Speed button click || too fast?
- [] All clicks on buttons dismisses and performs
- [] Settings clickable
- [] Playback clickable
- [] Clicking on chapter name does not dismiss

## Settings panel || scrollbar issues, remove vertical line and darken, font size +1

- [] Speed button switcheroo when settings on
- [] All clicks on buttons dismisses and performs
- [] Clicking on chapter name does not dismiss
- [] Blur works || either needs improvement or removal
- [] Library add works
- [] Remove selected works
- [] Rescan library works

## Speed panel || Playback or Speed?, remove vertical line and darken

- [] Choosing speed dismisses panel
- [] Choosing default speed does not dismiss panel
- [] Choosing step does not dismiss panel
- [] Left clicking on the panel does not dismiss the panel
- [] Clicking on chapter name does not dismiss

## Sleep panel

- [] Sleep button in sidebar opens panel
- [] Time presets (2, 5, ..., 120 min) set timer correctly
- [] "End of Chapter" mode works
- [] "End of Book" mode works
- [] Custom time input works with positive integers (Regex validation)
- [] Custom time input rejects non-positive/invalid input
- [] "Disable Sleep Timer" button works
- [] Sidebar pulse animation triggers on active timer
- [] Volume fade-out logic (Scale ratio based on remaining seconds)

## Library loading

- [] "No library" message displayed (quotes rotation active)
- [] Idle quotes (Random selection, justification, font scaling)
- [] "Scan now" button triggers native folder dialog
- [] Folder redundancy check (Parent vs Subfolder logic)
- [] "No book selected" message displayed when indexed but idle
- [] "Go to Library" button visibility states
- [] Scan status banner (Progress percentage, cancel functionality)

## Library panel

- [] Books do not flicker when shuffled (Grid re-insertion logic)
- [] Grid/List views work correctly
- [] Naming Pattern re-parsing (Author-Title / Title-Author live swap)
- [ ] Search filter logic
- [] Sorting: Title, Author, Last Played, Progress, Duration
- [] Ascending/Descending toggle works for all keys
- [] Async cover loading (Placeholders active until loaded)
- [] Persistent thumbnails (Metadata updates don't wipe loaded images)
- [] Back button dismisses

## Saving states

- [] Book progress restored
- [] Chapter name restored
- [] Theme restored
- [] Speed setting restored
- [] Default speed setting 
- [] Step restored || name
- [] Sort by view restored
- [] Grid/list view restored
- [] Naming Pattern selection restored
- [] Show Remaining Time toggle restored
- [] Chapter Scroll mode restored
- [] Chapter Hints toggle restored

## Appearance & UX

- [] Chapter Scroll: Slow mode (80ms interval, ping-pong with pauses)
- [] Chapter Scroll: Normal mode (40ms interval)
- [] Chapter Scroll: Off mode (Centered elided text)
- [] Chapter Hints: Hover triggers fade-in/out
- [] Chapter Hints: Click on transport dismisses hint immediately
- [] Chapter Hints: Background scales to text width (Size Policy Maximum)
- [] Settings: Consistency in button groups (Blur, Fade, Hints, Scroll)
- [] Undo button: Sequence logic (anchors to first click during rapid seeking)
- [] Undo button: Threshold scales with playback speed (60s * speed)
- [] Theme rotation: Timer based on interval settings

## Audio Processing

- [ ] Normalization (Speech Compression) toggles correctly
- [ ] Voice Boost equalizer applies mid-range lift
- [ ] Stereo/Mono switch works
- [ ] Channel swap (L ↔ R) functions correctly
- [ ] L/R balance slider adjusts volume bias
- [ ] Balance slider snaps to center (0) when near notch
- [ ] Balance slider notch is visible at dead center
- [ ] "Reset to defaults" button hidden when settings are default
- [ ] "Reset to defaults" restores all audio settings and hides itself

## Theme engine

- [] Theme changes apply immediately
- [] Hover works
- [] Hover preview reverts on dismiss
- [] All clicks on buttons dismisses and performs
- [] Clicking on chapter name does not dismiss

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
