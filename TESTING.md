## EQ/balance gradient fills, Audio tab reorder, EQ keyboard/wheel nav — 2026-09-19

Background: after the 5-band EQ shipped (below), live feedback across multiple themes and
screenshots found the sliders' flat fill hard to read, the tab order awkward for keyboard nav,
and — while digging into keyboard behavior — two real functional gaps: the 5 EQ rows were
completely invisible to arrow-key navigation (a layout-nesting bug, not a design choice), and
mouse wheel did nothing on any of the 6 sliders. A third gap, focusing a slider under the "fill
highlight" keyboard-nav style, was found and fixed in the same pass. Commit `9ce9e83`.

### Audio tab order and slider sizing
- [ ] Settings → Audio tab order, top to bottom: Voice boost / Stereo-Mono / Channel swap /
  Equalizer / L/R balance (EQ moved above balance, off the very top of the tab)
- [ ] Each EQ slider spans (close to) the tab's full width, with its freq label immediately to
  its right — no longer a short slider with the label floating near mid-screen
- [ ] L/R balance stays a shorter, fixed-width slider (not full-width like EQ) — check it does
  not visually blend into the cover art shown behind the Audio tab

### Gradient fills
- [ ] L/R balance: dragging away from center shows a gradient, brighter toward whichever edge
  you're approaching, darker toward center — the brightness at a given screen position stays
  fixed as you drag; only how much of the ramp is revealed changes (a small deflection shows a
  dim sliver near center, not an instant bright flash at its own short fill edge)
- [ ] Equalizer: dragging a band to the RIGHT (boost) brightens toward the right edge; dragging
  LEFT (cut) darkens toward the left edge — the two directions are NOT mirror images of each
  other (right brightens, left darkens — confirm both read distinctly, and that the far-left/most
  cut position is still visibly distinguishable from the panel background, not crushed to black)
- [ ] Balance and EQ read as visually distinct gradient styles from each other, not identical

### EQ keyboard navigation (regression fix)
- [ ] From Channel swap's row, pressing Down steps into the FIRST EQ slider row (100Hz) — not
  straight through to L/R balance
- [ ] Up/Down steps through all 5 EQ slider rows individually, then into L/R balance
- [ ] Left/Right on a focused EQ slider adjusts ITS OWN value (same as balance already did) —
  confirm this still works now that the rows are reachable at all
- [ ] Traveling marker still traces each EQ slider correctly (this worked before; confirms the
  layout flattening didn't disturb it)

### Mouse wheel on Audio sliders (new)
- [ ] Scrolling the mouse wheel over L/R balance changes its value
- [ ] Scrolling the mouse wheel over each of the 5 EQ sliders changes that slider's value
- [ ] Scrolling the wheel over the transport progress/chapter/volume sliders elsewhere in the
  app still does exactly what it always did (chapter nav / chapter scrub / volume) — confirms
  the new per-slider wheel support didn't leak into or override the existing transport behavior

### Fill-highlight keyboard-nav style + sliders (new)
- [ ] In Settings → Look, switch the keyboard-nav marker style to "Fill highlight"
- [ ] Tab/arrow focus onto L/R balance or any EQ slider in the Audio tab — the traveling border
  marker still shows on the slider (square corners), NOT a flat fill and NOT nothing
- [ ] Move focus off the slider onto a button (e.g. Voice boost) — that button now shows the
  flat fill-highlight style, not the traveling marker (confirms sliders are a deliberate,
  narrow exception, not a break in fill_highlight generally)
- [ ] Switch back to "Traveling marker" style — sliders behave exactly as before

## 5-band EQ + Settings tab spacing/row fixes — 2026-09-18 Session 3

Background: added a 5-band EQ to Settings → Audio (replacing Normalization), then fixed a
tab-to-tab header-pitch drift and a stray row-spacing override discovered along the way while
checking the new EQ's layout. Commits `119a2e6`, `1cc3ba9`, `b4f1325`.

**Update, 2026-09-19:** the Up/Down and Left/Right item below was checked at the time but the
EQ rows were in fact NOT reachable by arrow-key Up/Down at all — a layout-nesting bug (the 5 EQ
rows sat inside a QVBoxLayout wrapper invisible to panels.settings_tab_button_rows()'s
single-level walk) let Left/Right-on-a-focused-slider work correctly wherever focus DID land,
which is what made this read as passing. Fixed in the 2026-09-19 section above — re-verify there,
not here.

### Equalizer
- [x] Settings → Audio shows an "Equalizer" section with 5 sliders (100, 300, 1K, 3K, 8K), each
  with center-snap/center-mark like balance (now ABOVE L/R balance — see 2026-09-19 reorder)
- [ ] Dragging/arrow-keying each EQ slider produces an audible tonal change while a book plays,
  with **no console error** (this is exactly the failure mode mono/swap/balance had — must not
  reintroduce it)
- [ ] Reset to defaults restores all 5 EQ sliders to center (flat) and hides itself again once
  every Audio control (voice boost, mono, swap, balance, all 5 EQ bands) is back to default
- [x] ~~Keyboard Up/Down moves focus between the 5 EQ slider rows~~ — see the 2026-09-19 update
  note above; superseded by the "EQ keyboard navigation" checklist in the section above
- [ ] Traveling marker traces each EQ slider's square corners correctly (not rounded)
- [ ] "Speech compression (Normalization)" no longer appears anywhere in the Audio tab

### Settings tab header/row spacing consistency (`b4f1325`)
- [x] Switching between Themes/Look/Library/Audio/Controls, every tab's header-to-header spacing
  looks identical — no tab reads as "tighter" or "more cramped" than another
- [x] Themes tab: the Off / With pool / Exclusive button row's spacing now matches every other
  button row in Settings (was visibly tighter before the fix)

## Settings Off/On toggle defaults + day-starts-at spinbox — 2026-09-18 Session 2

Background: TODO_ARCHIVE.md's 2026-09-18 closure entry has the full audit (`a41b407`).

### Toggle default flips (config-only changes — first app launch on a fresh profile, or after
clearing the relevant QSettings key, is what actually exercises the new default)
- [ ] Chapter notches: on a fresh profile, Settings → Look should show Chapter notches defaulting
  to On (was Off) — and notches should actually be visible on the progress slider by default
- [ ] Persist search filter: on a fresh profile, Settings → Library should show the master toggle
  defaulting to On (button order also flipped to On/Off, left to right) with Tag, Text, and Year
  all individually shown as selected
- [ ] Stats ⚙ → Default timeline view: on a fresh profile, should default to Streak (was Heatmap) —
  opening the Stats panel's Timeline tab for the first time should show the streak grid, not the
  heatmap
- [ ] Playback panel: Step should default to 0.05 (was 0.1); Skip should default to 5s (was 10s) —
  confirm both are highlighted correctly on a fresh profile

### Day-starts-at spinbox (`2:00` format, confirmed live by Pryme via screenshot)
- [x] Spinbox displays "H:00" (e.g. "2:00") instead of a bare hour number
- [ ] Click the up/down arrow buttons — value should still change correctly and the displayed text
  should update to match (e.g. 2:00 → 3:00)
- [ ] Click the up/down arrows repeatedly, or Tab into the field via keyboard — the field's text
  should NOT show a full-text selection highlight flash on either interaction
- [ ] The blinking text-edit caret is still present when the field has focus — this was
  investigated and explicitly left unfixed (no safe Qt lever found after two reverted attempts);
  not a regression if still visible

## Cover-art-theme hover previews from Off mode — 2026-09-18 Session 2/3

Regression found and fixed same-day (Session 3, `5757f4e`): the preview applied synchronously with
no debounce, so a brief pass-over (no lingering) fired it instantly — fixed by routing through the
same 150ms `_hover_debounce_timer` queue every theme swatch already uses. Live-confirmed by Pryme.

- [x] Quickly passing the cursor over the "Cover art based theme" entry (no lingering) does NOT
  trigger a preview — matches every theme swatch's own quick-pass-over behavior
- [x] With cover-art-theme mode set to Off and a book with a cover loaded, hovering (lingering on)
  the "Cover art based theme" entry in Settings → Look previews the cover-derived theme, then
  reverts cleanly when the mouse leaves
- [ ] After that hover-and-leave, confirm the mode is STILL Off and the stored theme was NOT
  changed — hovering must only preview, never commit (unlike left/right-click on the same button)
- [ ] Repeat with mode set to With pool, then to Exclusive — hover-preview-from-Off is the only new
  behavior; confirm the other two modes' existing hover/click behavior is unchanged
- [ ] Confirm a book with NO cover art still no-ops correctly on hover (no crash, no stale preview)

## Library keyboard-selection highlight unification + pagination hover-jump fix — 2026-09-18 Session 1

Two changes shipped together (`9058136`). **Both confirmed live by Pryme.** Background: CLAUDE.md's
"Keyboard-selection visual, per view mode" note and the `StatsRowListView` hover-poll mechanism
this was ported from.

### Keyboard highlight color (1-per-row only)
- [x] 1-per-row view mode: arrow-navigate to a book with the mouse elsewhere — the keyboard
  highlight should now look like a mouse-hover highlight (same color/opacity as hovering that row
  with the mouse), not the old separate, more subtle tint
- [ ] Confirm List, 2-per-row, 3-per-row, and Square modes look UNCHANGED — this fix only touches
  1-per-row's own tint

### Pagination no longer jumps to a stationary mouse's row
- [x] Rest the mouse over some row in the middle of the list (not the first or last visible row),
  then press Down or Up repeatedly with the mouse NOT moving — the keyboard selection should
  advance one row at a time from wherever it already was, never snapping to the row under the
  mouse
- [x] Same check with PageDown/PageUp — this was the original reported symptom ("making you have
  to press PgDn twice") — a single PageDown should move a full page, not appear to consume one
  press just resolving the mouse's row first
- [ ] Same check with Home/End
- [ ] With the mouse already resting on the LAST visible row, press Down — should still feel
  smooth (this case was already reported working correctly before the fix; confirm it's still
  fine, not regressed)
- [ ] After a keyboard move, physically move the mouse onto a genuinely different row — the
  keyboard highlight should yield to mouse hover normally, same as before this fix (mouse
  reclaim itself must still work, only the false-positive "mouse never moved" case was broken)

## Book Detail Tags tab — tag-add field completer, five bugs fixed — 2026-09-18 Session 1

All five **live-confirmed fixed by Pryme** (`3794231`, `5de212c`). Background: TODO_ARCHIVE.md's
2026-09-18 closure entry has the full per-bug root-cause writeup.

- [x] Type a broad shared-prefix (e.g. `ai:`) with 10+ matching tags — the full list should show,
  not just the first 10
- [x] Type a prefix, then immediately type a more specific continuation (e.g. `ai:` then a space
  then a letter) — matches should show without a spurious empty flash
- [x] Narrow the search down, then backspace to widen it again — the dropdown should grow back to
  fit more results instead of staying capped at a scrollbar
- [x] Start typing a tag, press Tab mid-typing — the field should clear with no leftover dropdown
  and no stuck-looking cursor; typing a fresh tag afterward should work normally
- [x] Type a prefix, press Down/Up repeatedly through the suggestions — the list should stay
  stable as you arrow through it, never collapsing to a single result or looking like something
  got auto-selected (no tag should actually be added without pressing Enter/Tab-selecting/clicking)

## Sleep timer end-of-chapter mode fade-out — 2026-09-18 Session 1

Not yet live-verified by Pryme. Background: TODO_ARCHIVE.md's 2026-09-18 closure entry;
`tests/test_sleep_eoc_fade.py` pins the math in isolation.

- [ ] Arm sleep timer in end-of-chapter mode with a fade duration configured, let it play down
  toward the chapter's end — volume should audibly fade out approaching the boundary, not snap
  straight from full to paused
- [ ] While the fade is audibly running, seek FORWARD within the same chapter (e.g. skip ahead) —
  the fade should become MORE pronounced on the next tick, not stay at the pre-seek ratio
- [ ] While faded, seek BACKWARD within the same chapter (e.g. undo or skip back) — volume should
  audibly recover, not stay faded or snap back to full instantly
- [ ] Arm end-of-chapter mode very close to a chapter's own end (or on a chapter shorter than the
  configured fade duration) — the fade should still sound graceful over whatever time is actually
  left, not jump straight to near-silent

## Smart rewind: per-book scoping and chapter confinement — 2026-09-16 Session 1

Two bugs, both live-verified this session. Background/full mechanism: CLAUDE.md's "Smart rewind
must be reset per book" and "DO NOT use `self.player.chapter`" rules; `tests/test_smart_rewind.py`
covers the chapter-clamp logic in isolation (no mpv/QApplication).

### Per-book scoping (no cross-book leak)
- [x] Enable smart rewind (Speed panel), pause a book long enough to arm the wait threshold, then
  switch to a DIFFERENT book before resuming — the new book's first resume must NOT rewind at all
- [ ] Same check via the EOF-restart path: arm smart rewind, let a book reach EOF, press
  Play/Restart — the restart-from-0 must not itself trigger a stale rewind
- [ ] Same check via book removal: arm smart rewind on a book, remove it from the library (trash
  button or scan-location removal) before resuming, then select and play a different book — no
  stale rewind should fire

### Chapter confinement (clamps to the paused chapter's own start)
- [x] Pause a few seconds into a chapter, wait past the smart-rewind threshold, resume — rewind
  lands at 0:00 of THAT chapter, never crosses into the previous chapter
- [ ] Same check on a VT (multi-file MP3) book — chapter boundaries are file boundaries there;
  confirm the clamp still respects the file/chapter start correctly
- [ ] Same check paused exactly AT (or within a second of) a chapter's own start — should stay put
  at that chapter's 0:00, not drift backward into the previous chapter

### Known, separate, NOT fixed — do not mistake this for a smart-rewind regression
- [ ] Landing exactly at a chapter start (via smart rewind's clamp, `|<`/Prev, or ordinary chapter
  nav) can clip the first fraction of a second of narration (e.g. "apter two" instead of "Chapter
  two"). This is the pre-existing mpv seek-landing-precision issue tracked in TODO.md's
  "Seek-landing precision at chapter boundaries" group — reproduces identically via plain Prev with
  smart rewind never involved. Confirm it's still present (expected) rather than treating it as a
  new bug introduced by this session's fixes.

## Undo: spree anchoring, boundary no-ops, and coverage across all seek inputs — 2026-09-16 Session 1

Four fixes, all live-verified this session, all sharing one mechanism: `Player.save_seek_position`
now captures the undo anchor unconditionally within a coalescing spree (rapid calls inside
`undo_duration`, default 3s) and gates only whether the overlay SHOWS on cumulative distance from
that anchor (`60s * speed` for most call sites). Background: CLAUDE.md's "Undo must anchor to a
seek spree's start" rule and its two follow-up rules; `tests/test_undo_position.py` covers the
anchor/threshold logic in isolation (no mpv/QApplication).

### Spree anchoring (Next/Prev, chapter-list click, slider release, chapter-slider release)
- [x] Sit in a short chapter (well under a minute), press Next through it into a longer chapter
  (repeat a couple more times if needed), then click Undo — lands back at the position BEFORE the
  first Next, not at the start of the first long chapter
- [ ] Same check via rapid chapter-list clicks (click chapter 3, then chapter 4, then chapter 5 in
  quick succession) — Undo returns to the position before the first click, not chapter 4's start
- [ ] Same check via rapid progress-slider drags/releases in quick succession — Undo returns to the
  position before the FIRST release in the spree
- [ ] A single Next/Prev press on its own, far enough to individually exceed the 60s threshold
  (e.g. a very long chapter) — Undo still shows immediately and correctly, single-press behavior
  unaffected by the spree-anchoring change

### Long-skip / restart boundary no-ops (must NOT show Undo for a seek that didn't move)
- [x] Right-click `>` (long skip forward) when the remaining time is less than the configured
  long-skip duration (target would land within ~2s of EOF) — no Undo shown, since `seek_async`
  silently refuses to seek that close to EOF
- [x] Right-click `<` (long skip backward) or right-click `|<` (restart to 0:00) while already
  sitting at/near 0:00 — no Undo shown (the move is real but trivially small)
- [ ] A genuine long skip mid-book (well clear of both EOF and the start) — Undo still shows
  correctly, only the boundary cases are suppressed

### Chapter-slider wheel scrub (no Undo for a single small tick)
- [x] Scroll the chapter progress slider once on a short chapter (under a minute, or e.g. a 4m04s
  chapter whose 10%-of-length step is ~24s) — no Undo shown for that single tick
- [ ] Scroll the chapter progress slider repeatedly/rapidly until cumulative distance exceeds 60s
  — Undo now shows, anchored to the position before the FIRST tick in the scroll spree
- [ ] Scroll near the chapter's own end/start boundary (clamped step) — no Undo for a step that
  lands exactly on the boundary with negligible net movement

### Regular skip taps/holds (`</>` buttons and Left/Right keys) — extended to the same gate
- [x] Hold the `>` or `<` button (auto-repeats every ~150ms) past ~60s of cumulative skip in one
  direction — Undo now shows, anchored to the position before the hold began
- [ ] Same check holding Left or Right arrow keys instead of the buttons
- [ ] A single tap of `>`/`<`, or a single Left/Right press, at the default skip duration (10s) —
  no Undo shown (stays silent, matching the original single-tap design intent)
- [ ] Rapid repeated taps (not a held key) past 60s cumulative — Undo shows, same as a held key
- [ ] Shift+Left / Shift+Right (keyboard long-skip) near EOF/start — same boundary no-op check as
  the long-skip buttons above, since both route through the same `handle_rewind`/`handle_forward`

## Hover-pickup keyboard navigation + tab-bar mouse-reclaim — 2026-09-15 Session 1

Two directions on each surface: keys picking up from wherever the mouse is hovering (no keyboard
cursor active yet), and mouse hover reclaiming a stale keyboard highlight once it's genuinely the
most-recent input. All confirmed live in this session except where noted.

### Keys pick up from mouse hover (Settings, Speed, Sleep, Sprint, Stats)
- [x] Settings, any arrow-nav tab (Look/Controls/Audio/Library/Themes): rest the mouse over a
  button, press an arrow with NO prior keyboard nav this session — the keyboard cursor should
  seed from that button, not the tab's first row
- [x] Settings tab bar: hover a different tab than the currently selected one, press an arrow —
  picks up from the hovered tab
- [x] Speed / Sleep / Sprint panels: same check, hover a preset button then press an arrow
- [ ] Stats "⚙" tab: hover a button (day-start-hour spinbox, reset button), press an arrow —
  picks up from hover (added same session as the fix above; confirm separately from the four
  panels already verified)
- [ ] On a FRESH panel open, with the mouse resting somewhere but never having moved since open:
  arrows should start from the DEFAULT (first row), not pick up from the resting mouse — pickup
  requires genuine movement, not just presence
- [ ] Hold an arrow key with the mouse completely stationary: pickup should not re-trigger on
  every repeat, keyboard nav should continue normally from wherever it already is

### Mouse hover reclaims from keyboard (Settings and Stats tab bars)
- [ ] Settings tab bar: arrow-navigate between tabs (marker visible on one), then move the mouse
  to hover a DIFFERENT tab — the marker/keyboard highlight should disappear and native hover
  should show on the tab the mouse is over
- [ ] Stats tab bar: same check — arrow through Overall/Timeline/Day/Week/Month/⚙, then hover a
  different tab with the mouse; this was the ORIGINAL reported bug (two earlier attempts failed,
  see NOTES.md 2026-09-10/2026-09-15) — verify carefully across a few repetitions
- [ ] Stats tab bar, KEYBOARD-ONLY session: hover a tab with the mouse, then switch tabs using
  ONLY arrow keys (mouse never moves again) — the originally-hovered tab must NOT stay visibly
  highlighted through the whole sequence (this was the specific reproduction that found the real
  bug — a stationary mouse never triggers the reclaim poll at all, so this exercises the QSS
  suppression rules, not the poll)
- [ ] Compare Settings vs. Stats side by side doing the identical sequence — should look and
  behave identically in both directions

### Tags — thumbnail grid mouse/keyboard pickup, and list Enter-on-hover
- [ ] Tags → open a tag's detail view → hover a thumbnail with the mouse (confirm NO visual
  highlight appears from hover alone — this is intentional, only the keyboard ring should ever
  show) → press an arrow key → the keyboard ring should appear on the PREVIOUSLY HOVERED
  thumbnail on the FIRST press, not require a second press
- [ ] Tags list (not the thumbnail grid) → hover a tag row with the mouse, no keyboard cursor
  active → press Enter or Alt+Enter directly — should open that tag's detail view immediately,
  matching Library's own hover+Enter behavior
- [ ] Tags thumbnail grid → hover a thumbnail, press Enter/Space with NO prior arrow press —
  should still be a no-op (deliberately NOT extended to hover — destructive, no-undo action, see
  CLAUDE.md's 2026-09-13 incident)

### Explicitly NOT in scope for this session — confirm these still show their PRE-EXISTING behavior, unchanged
- [ ] Book Detail's own tab bar: no keyboard arrow-nav, no mouse-reclaim styling change (never
  wired into this system at all — confirm nothing broke, not that it now works)

(Library's own keyboard/mouse hover coexistence shipped 2026-09-18 — see that entry below; it is
no longer an open gap as of this session.)

## Confirmation-dialog keyboard consistency — Escape/Delete/swallow-and-dismiss — 2026-09-09 Session 1

Nine sites total. All nine share the same two rules now: Escape (and every other non-Space/
Enter key) cancels JUST the confirmation, panel/tab stays open; Delete arms a confirmation
where one was added this session (Stats/Sprint reset, Book Detail's history-delete).

### Escape cancels the confirmation, not the whole panel
- [ ] Stats ⚙ tab → "Reset all listening stats" → arm it → Escape: confirmation reverts, Stats panel stays open
- [ ] Sprint panel → "Reset all sprint data" (only reachable when no sprint is active) → arm it → Escape: reverts, panel stays open
- [ ] Sprint panel → trigger the conflict-confirm overlay (e.g. try to start a sprint while Sleep is active) → Escape: reverts, panel stays open
- [ ] Sleep panel → trigger its own conflict-confirm overlay (e.g. try to start Sleep while a sprint is active) → Escape: reverts, panel stays open

### Delete arms a confirmation, from anywhere on the relevant surface (not just when focus is on the button)
- [ ] Book Detail → History tab, arrow down to select a row, then Up at row 0: row deselects (does not just stay put)
- [ ] Book Detail → History tab, with NO row selected → Delete: arms "Delete listening history"
- [ ] Book Detail → History tab, with a row selected → Delete: arms THAT row's own "Delete this session?" (unchanged, still works)
- [ ] Stats ⚙ tab → Delete, with focus anywhere on that tab (the day-start-hour spinbox, a toggle button, the tab bar itself) — not just the reset button: arms "Reset all listening stats"
- [ ] Stats → a DIFFERENT tab (Overall/Day/Week/Month/Timeline) → Delete: does nothing (the button isn't there)
- [ ] Sprint panel → Delete, with focus anywhere on the panel (not just the reset button), while the button is genuinely visible (no sprint active): arms "Reset all sprint data"
- [ ] Sprint panel → while a sprint IS active (reset button hidden) → Delete: does nothing
- [ ] Sprint panel → focus the custom sprint-duration or grace-duration text field → Delete: deletes a character forward, does NOT arm the reset confirmation
- [ ] Only Delete works for these — X does nothing (dropped as a synonym; confirm it's genuinely inert, not just untested)

### Any key other than Space/Enter dismisses an armed confirmation and does nothing else (swallow, not also navigate)
Test with Up/Down/Left/Right and at least one letter key at each site — the confirmation should
revert and the key's normal action (row move, tab switch, etc.) should NOT also happen on that
same press. A second press of the same key, now that nothing is armed, should behave normally.
- [ ] Stats "Reset all stats" armed → Up/Down/Left/Right/a letter: reverts, no side navigation
- [ ] Sprint "Reset all sprint data" armed → same
- [ ] Sprint's conflict-confirm overlay armed → same
- [ ] Sleep's conflict-confirm overlay armed → same
- [ ] Book Detail "Remove/exclude book" armed → Left/Right does NOT also cycle to a different tab
- [ ] Book Detail "Mark finished/unfinished" armed → same
- [ ] Book Detail "Delete listening history" armed → Up/Down does NOT also move the row-selection cursor
- [ ] Book Detail per-row "Delete this session?" armed on one row → Up/Down does NOT move the keyboard-hover cursor among the OTHER rows either — the whole row list should be inert until the confirm is dismissed
- [ ] Tags panel, delete-a-tag confirm armed → Up/Down/Left/Right: reverts (this one already worked before this session — regression-check only)

### Tab specifically (the gap that recurred three times in one pass)
Tab in Book Detail is dispatched in `eventFilter`, separately from every other key — verify it
independently, not just as "one of the arrow keys" above.
- [ ] Book Detail → arm "Remove/exclude book" (from ANY tab, since the confirm is header-level, not tab-local) → Tab: dismisses, does NOT enter metadata edit mode
- [ ] Book Detail → arm "Mark finished/unfinished" → Tab: dismisses, same check
- [ ] Book Detail → History tab → arm "Delete listening history" → Tab: dismisses, does NOT enter metadata edit mode
- [ ] Book Detail → History tab → arm a per-row "Delete this session?" → Tab: dismisses, same check
- [ ] Tags panel → arm delete-a-tag → Tab: dismisses, does NOT move focus into the (read-only-while-confirming) tag-name field

## Stats Day/Week/Month row-list keyboard nav — hover/cursor fixes, blur interaction — 2026-09-08 Session 4

**LIVE-ONLY, blur specifically.** The two central bugs here (mouse/keyboard hover fight, marker
bleeding onto Book Detail) only reproduce with the transport-bar blur setting ON — it drives the
5-15x/sec hide/show grab cycle both bugs trace back to. All 507 automated tests passed throughout
every attempt in this area, including the two that later failed live — do not treat a green test
run as coverage for anything in this section.

### Row-list cursor shape
- [ ] Day/Week/Month, a period with few sessions (Finished-books carousel hidden): hover down past
      the last real row into the empty space below it — cursor is a plain arrow, not a pointing hand
- [ ] Move back up onto a real row: cursor returns to the pointing hand
- [ ] Click in the empty space below the last row: no-op, no crash
- [ ] Mouse leaves the row list entirely (off the bottom, into the tab bar area): cursor is the
      arrow, not stuck as a hand

### Mouse/keyboard hover fight (blur ON)
- [ ] Arrow down into a Day/Week/Month tab's row list, rest the mouse on a DIFFERENT row than the
      keyboard cursor, keep pressing Up/Down repeatedly: the keyboard's highlight stays on the
      keyboard's own row — it does not snap to wherever the mouse is resting, on any single press
- [ ] Same test with PgUp/PgDn/Home/End instead of Up/Down
- [ ] After a burst of keyboard presses, physically move the mouse onto a different real row: the
      highlight now correctly follows the mouse (reclaim still works — this isn't testing that
      mouse control is broken, only that it doesn't fire from a stationary cursor)
- [ ] Repeat the whole check with the transport-bar blur setting OFF: same correct behavior (this
      was already working before blur was in the mix — confirms the fix didn't regress the no-blur
      case while fixing the blur case)
- [ ] Repeat with blur ON while a book is actively playing (the grab cycle only runs then) vs.
      paused/no book (grab cycle idle) — the fight should be gone in both, but the playing case is
      the one that actually exercises the fix

### Marker bleeding onto Book Detail (blur ON, traveling marker style)
- [ ] Settings > Controls > Keyboard marker style = "Traveling marker". Open Stats, arrow into a
      tab (e.g. Day), press Enter/Space on a row to open Book Detail: the marker does NOT appear
      anywhere on Book Detail, during or after its slide-in animation
- [ ] Same check with the marker genuinely mid-patrol (still actively animating, not yet dormant)
      the instant Enter is pressed — the in-flight animation must not continue rendering onto Book
      Detail once it's open
- [ ] Close Book Detail back to Stats: keyboard focus lands somewhere sane (the tab bar or the row
      that was open), not stranded — arrow keys work immediately, no extra Tab/click needed
- [ ] Repeat with blur OFF: same correct behavior (this bug was blur-specific; confirms no
      regression to the already-correct no-blur case)
- [ ] Repeat opening Book Detail from Library (not Stats) with blur ON and the marker mid-patrol on
      some other keyboard-navigable panel state, if reachable — the underlying fix
      (`_grab_and_blur`'s focus save/restore) is general, not Stats-specific, so this should also
      be clean

## Traveling focus marker — keyboard/mouse modality, Look-tab arrows — 2026-09-04

**LIVE-ONLY.** Every bug in this section was invisible to scripted checks: three separate offscreen
harnesses rendered the marker's geometry pixel-correct against a reference line while the live app
showed a 1px offset, and the modality bugs were all found by tracing the running app, never by
reading the code. Two of them were *introduced* by a fix that reasoned correctly from a passing
test. Do not treat green tests or a clean render as coverage here.

### Marker appearance (Settings > Look)
- [ ] Tab into the Look tab's buttons: the marker traces the button's **rounded** corners, following the real border — not a sharp-cornered box, and not offset outside it
- [ ] Marker on a settings TAB: top and both sides are traced, the bottom edge is deliberately not — and there is **no diagonal line** cutting across the untraced bottom, and no stray mark past the left or right edge
- [ ] Both vertical sides reach the same depth (an uneven/"slanted" bottom means the endpoint sampling regressed)
- [ ] The color visibly travels around the border. If it looks static, check the theme's `focus_marker_palette`: an HSV hue rotation on a near-white color is a visual no-op — this must be an RGB blend between genuinely different colors
- [ ] No native dotted focus rectangle anywhere (suppressed app-wide by `NoFocusRectStyle`; QSS `outline: none` does NOT work on Fusion)

### Modality — most recent input wins
- [ ] Click a button with the mouse: marker does **not** appear
- [ ] Click a **tab** with the mouse: marker does not appear (Qt reports this as `TabFocusReason`, hence `_MOUSE_PRESS_FOCUS_WINDOW_S` — a regression here shows the marker on mouse clicks)
- [ ] Tab/arrow to navigate: marker appears, and any mouse `:hover` highlight **clears** — on both tabs and buttons
- [ ] Hover a tab, then arrow through the tabs: the hovered tab's highlight goes away and stays away (no blink-then-return)
- [ ] Hover a button, then arrow between buttons: same
- [ ] Move the mouse onto a tab or button while the marker is showing: hover takes over, marker disappears
- [ ] Move the mouse over **dead space** (a header, empty area): marker stays — only a real control hands control back
- [ ] Keyboard-navigate, go to another settings tab and back: mouse hover still works **without** needing a click first (this specific strand needed the setter and the hand-back check to span the same controls)
- [ ] Arrow around the **Themes** tab, return to Look: hover still works on both tabs and buttons
- [ ] Type an arrow key inside a text field (Library search, sleep custom minutes): modality unaffected, no marker

### Arrow navigation — all button-row tabs (Look, Controls, Audio, Library, Themes)
Run these on **each** participating tab; the handler is generic, so a break on one is likely a break on all.
Themes has its own additional row shape and internal swatch-grid navigation — see its own
section below for that part specifically.
- [ ] From the tab bar, **Down** enters the controls at the first row's first control
- [ ] **Down**/**Up** move between rows, always landing on the row's **first** control
- [ ] **Up** from the first row returns to the tab bar
- [ ] **Left** at the first row's first control returns to the tab bar
- [ ] **Left**/**Right** otherwise step within the row (native behaviour, unchanged)
- [ ] **Down** on the last row does nothing (swallowed — it must not fall out of the grid)
- [ ] Tab/Shift+Tab still cycle through every control exactly as before
- [ ] **Space** and **Return/Enter** both activate the focused control (Qt gives Space for free; Enter is ours)

### Settings → Themes tab (added 2026-09-06 Session 2)
Row-to-row nav is the generic mechanism above (mode row, swatch grid as one stop, bulk row,
interval row); this section covers the swatch grid's own internal navigation and the tab's
shortcuts, which are Themes-specific.

**Swatch grid entry/exit**
- [ ] **Down** from the mode row lands on the swatch grid's first item (Cover art based theme),
  and previews it automatically (no extra keypress) — same debounced preview a mouse hover uses
- [ ] **Up** from the grid's first row leaves to the mode row above; the swatch's preview reverts
  to the committed theme the instant you leave (no lag, no stuck highlight)
- [ ] **Down** off the grid's last row leaves to Add all/Remove all/Change now; preview reverts
- [ ] **Left** off the grid's first column (row 0 only) leaves to the tab bar; preview reverts
- [ ] **Tab** away from the grid (forward or Shift+Tab backward) also reverts the preview — this
  was a real bug (2026-09-06): both Tab and every arrow exit initially failed to revert whenever
  the real mouse cursor happened to be resting near wherever it last hovered a swatch, because
  the exit path was reusing the MOUSE leaveEvent's jitter-detection heuristic on a keyboard
  action that has nothing to do with where the mouse physically is
- [ ] Leave the grid, then re-enter with Down/Up: lands back at row 0/last row (no memory of the
  previous position — same as folder_list_widget's own exit-and-reenter behaviour)

**Inside the grid**
- [ ] **Right** from a row's last swatch continues onto the NEXT row's first swatch (reading-order
  wrap, not a clamp) — confirmed on a genuinely bin-packed row boundary, not just a short row
- [ ] **Left** from a row's first swatch continues onto the PREVIOUS row's last swatch
- [ ] **Right** off the grid's very last swatch exits downward (same as Down there)
- [ ] **Up**/**Down** move to the same column index on the row above/below, clamped to that row's
  own length if it's shorter — this is a DIFFERENT movement than Left/Right's wrap
- [ ] Arrival at any swatch shows a visible hover-look highlight (a real QSS property,
  `kbdnav_hover` — NOT `Qt.WA_UnderMouse`, which was tried first and confirmed live not to
  actually repaint `:hover` at all) — moving to a new swatch must not leave two swatches
  highlighted, or none
- [ ] **Space** toggles the focused swatch's pool membership only (mirrors a LEFT click) —
  it must NOT also switch the active theme
- [ ] **Enter/Return** selects the focused swatch AND switches to it immediately (mirrors a
  RIGHT click) — it must NOT just toggle pool membership
- [ ] No traveling marker ever appears inside the grid — the hover-look property above is the
  only "where am I" affordance
- [ ] Resting the real mouse somewhere outside the grid while navigating with arrows: the preview
  must hold (this was the periodic-backstop bug, fixed earlier this session — the 500ms
  swatch-leave-still-hovered check was treating "mouse physically outside the box" as a leave
  signal even though the keyboard, not the mouse, was driving)

**Interval row**
- [ ] **Left/Right** move between the interval values (2/5/10/20/30/60/120/Off) — plain `QLabel`s
  have NO native arrow-key focus chaining (confirmed live and synthetically; unlike QPushButton,
  which gets this from Qt's own style), so this needs its own explicit handling — a regression
  here would show Right/Left doing nothing
- [ ] The focused interval value shows an underline via a bottom border — NOT
  `text-decoration: underline`, which was tried first and confirmed live not to render on
  `QLabel` at all (identical output with/without the rule)
- [ ] **Enter/Space** on the focused interval value sets the rotation interval

**Tab-scoped shortcuts** (work no matter which control on the tab has focus)
- [ ] `A` and `Ctrl+A` both trigger Add all
- [ ] `R` triggers Remove all; `Ctrl+D` also triggers Remove all
- [ ] `T` and `C` both trigger Change now
- [ ] Typing "20", "30", "60", "120" (as separate keystrokes, quickly) sets that rotation interval
  after a short pause (buffered, not one-key-per-value — typing "2" then "0" quickly must set
  20, not land on 2 then separately on 0)
- [ ] Typing an interval that doesn't exist (e.g. `9`, `121`) does nothing after the pause
- [ ] None of these letters/digits do anything on any OTHER settings tab, or leak to the global
  shortcuts (e.g. `T` must not rotate the main-window theme while Settings has focus)

### Live row membership (controls that appear and disappear)
- [ ] Look: set **Chapter notches** Off — the Animation pair disappears and stops being a stop; On again and it returns
- [ ] Audio: with every audio setting at default, **Reset to defaults** is hidden and is not a stop; change any setting and it becomes reachable
- [ ] Library with **no folders**: the folder box is skipped entirely (Down from the tab lands on **Add**), and Remove/Rescan are dimmed, unhoverable, unclickable and skipped by both Tab and arrows
- [ ] Library after adding a folder: the box becomes a stop and Remove/Rescan come back

### Audio — slider and Reset button
- [ ] **Left/Right** on the focused balance slider change its value instead of moving focus
- [ ] Holding Left/Right keeps the marker awake indefinitely — it must not fade mid-adjustment
- [ ] The marker stops and fades normally a couple of seconds after you stop pressing
- [ ] **Enter** on the slider does nothing (no crash — it has no click())
- [ ] **Reset to defaults** shows a FILL SHIFT when focused, not a traveling marker
- [ ] Its mouse hover works (this was broken pre-existing) and matches the keyboard focus colour
- [ ] Both follow `focus_audio_tab_reset` if a theme overrides it

### Library — Manage folders list (cursor and selection are independent facts)
No traveling marker here — the current row is shown as a small dot at the row's right edge
(`_FolderListItemDelegate`), separate from the accent fill a selected row gets. Arrow keys never
change selection, on entry, mid-list, or exit; Space/Enter is the only thing that does.
- [ ] **Down** from the tab bar enters the box **on the first path**, with **nothing selected** —
  the dot shows on row 0, no accent fill anywhere
- [ ] **Up** from the Add row enters the box **on the last path**, same: dot only, nothing selected
- [ ] Arrow through several rows with nothing selected: only the dot moves, no row ever gets an
  accent fill from arrowing alone
- [ ] **Space** (or **Enter**) toggles the current row's selection on; press it again on the same
  row and it toggles back off — both keys must behave IDENTICALLY, never split add/remove
- [ ] Select two or three non-adjacent rows with Space, then arrow through the whole list: the
  dot moves freely and the selected rows' accent fill is undisturbed the entire time
- [ ] With exactly **ONE** path: Down enters it (must not bounce straight back out)
- [ ] Up on the first path / Down on the last leaves the box — **whatever is selected stays
  selected** (this used to clear on the way out; it must not anymore, since Remove needs to act on
  it after Tabbing away)
- [ ] Tab/Shift+Tab into the box also land on a path (dot on row 0/last, nothing selected), not the
  bare box
- [ ] **Del** removes the CURRENT-ROW path immediately, with no selection required first — works
  identically whether or not that row happens to also be selected, and never touches other selected
  rows
- [ ] **Remove** button is dimmed/unclickable whenever nothing is selected, and enables live the
  instant a row is Space-selected — including right after a scan finishes (it must not silently
  re-enable itself with no selection)
- [ ] A plain click on the sole selected path deselects it (toggle-off) instead of re-selecting the
  same path; Ctrl+click's own toggle behavior is unaffected
- [ ] **Left** anywhere inside the box goes to the tab bar; **Right** anywhere inside the box is a
  no-op (neither has a native meaning for a folder-path row)
- [ ] The folder list's own scrollbar has **square** corners, matching its border-radius override
  (a themed scrollbar rule elsewhere in Settings sets 4px and can silently win if this one's value
  is ever merely omitted rather than set to 0px)

### Excluded Books popup (Settings → Library, below Persist search filter)
Self-managed overlay with its own `keyPressEvent` — mirrors `ChapterList`'s conventions rather than
`_handle_settings_arrows`'s button-row model. No separate marker/fill/dot: the row's own hover-
reveal eye slide IS the "you are here" indicator, driven by keyboard exactly like a real mouse hover
would.
- [ ] **Down** from any Persist search filter button enters the box on row 0, eye revealed
- [ ] **Right** from Persist search filter's rightmost button also enters the box on row 0
- [ ] With 0 excluded books, the box is invisible and never becomes a keyboard stop at all
- [ ] Up/Down move the eye one row at a time; scrolling happens automatically once past the visible
  window, including past the 7-row expanded cap if there are more than 7 excluded books
- [ ] **Left/Right** (either key) toggle expand/collapse, same as `ChapterList`'s own convention —
  not tied to scroll position, a deliberate action only
- [ ] **Space/Enter** on the current row restores it — same effect as clicking its eye
- [ ] **Up** at row 0 always exits to Persist search filter's row, collapsing the box first if it
  was expanded (never a no-op, regardless of expand state)
- [ ] Collapsing while the eye is on a row beyond the default 3 (only reachable while expanded)
  scrolls that row back into view rather than resetting the cursor to row 0
- [ ] Shift+Tab away from the box, or a mouse click landing on any other Settings control, also
  collapses an expanded box — not just the Up-at-row-0 path
- [ ] **Mouse and keyboard, "most recent move wins":** rest the mouse on one row while arrowing the
  keyboard to a different row — only ONE eye is ever open at a time, and it always follows whichever
  input moved most recently
- [ ] With the transport-bar blur enabled and the panel open, rest the mouse motionless on a row and
  press an arrow key repeatedly: the keyboard's eye must stay put on the new row, not flash and
  immediately revert to the mouse's row (this was a real, confirmed bug — the blur's hide/show grab
  cycle delivers a real, matched leave+enter pair to a perfectly stationary mouse roughly every
  200ms)
- [ ] Expand the box with the MOUSE while a Persist search filter button holds keyboard focus: focus
  moves into the box (row 0) rather than staying stranded under the now-covered button
- [ ] Arrow (Left/Right) across Persist search filter's own buttons while the box is ALREADY
  expanded: same redirect, focus moves into the box instead of landing on a covered PSF button
- [ ] The scrollbar handle is a distinct, darker shade from `ExcludedBooksSection`'s expand arrow
  directly above it (both used to be plain `accent` and visually merged at their shared edge), and
  has square corners like the folder list's

### Marker shape (per control type)
- [ ] Small buttons: rounded corners traced, all four corners intact — no corner cut off as a diagonal
- [ ] Balance slider: a crisp **square** rectangle sitting on the bar, not rounded and not spilling past its right/bottom edge
- [ ] Settings tabs: one flat sweep along the top edge only, stopping short of the rounded corners, not slanting at the ends
- [ ] Selected folder path: square outline around the **row**
- [ ] If a theme's tab marker blends into the tab bar, `focus_marker_tab_palette` overrides it for tabs alone

### Theme preview revert on tab switch
- [ ] Hover a theme swatch to preview, then switch tabs **with the mouse**: the preview reverts fully, *then* the tab switches — the snapback must not play over the newly-arrived tab
- [ ] Same with **arrow keys** on the tab bar (this path used to revert after the switch)
- [ ] Switching tabs with no preview showing: no added delay, behaves exactly as before

### Speed / Sleep / Sprint panels — keyboard navigation (added 2026-09-07 Session 1)
These three panels have no tabs — one flat row-of-rows per panel (`PanelManager.
flat_panel_rows`), with each panel's own preset grid a single stop that owns its own internal
navigation (`MainWindow._handle_panel_grid_arrows`). Run the row-to-row checks on **all three**
panels; the mechanism is shared.

**Row-to-row**
- [ ] Down/Up move between rows (the preset grid, custom-duration row, and whatever else the
  panel has), landing on the row's first control
- [ ] **Right/Left at a row's last/first item continue into the NEXT/PREVIOUS row** rather than
  stopping or jumping to an unrelated row — this was a real, repeatedly-reported bug (Qt's
  native inter-button arrow stepping is NOT scoped to the visual row, it follows construction
  order) fixed by handling Left/Right fully explicitly; re-check every row boundary in each
  panel, not just one, since the bug's exact landing spot depended on construction order
- [ ] Space and Enter BOTH activate a plain click (a real inversion bug had Space doing nothing)
- [ ] Shift+Space and Shift+Enter both trigger a `rightClicked` action where one exists (Sleep's
  Fade-out row: left-click applies now, Shift-click sets as default) — a no-op, not a plain
  click, on any control with no `rightClicked` signal

**Preset grid (Speed's 12 speed buttons; Sleep's 14 duration + End of chapter; Sprint's 10
duration + End of chapter)**
- [ ] Right/Left wrap in reading order across grid rows — rightmost cell continues onto the
  NEXT row's first cell, leftmost continues onto the PREVIOUS row's last; off the grid
  entirely in either direction, exits to the row above/below the grid in the panel
- [ ] Up/Down move by column, clamped to a shorter row's own length where relevant
- [ ] The spanning "End of chapter" cell (Sleep/Sprint) is ONE stop reachable from either
  column it occupies, not two, and Left/Right/Up/Down around it behave like any other cell
- [ ] The keyboard-focused grid button shows the SAME hover-style highlight a mouse hover
  would (a real `:focus` QSS rule reproduced in each grid's own per-instance ramp
  stylesheet) — moving to a new cell must show exactly one highlighted button, never zero,
  never two
- [ ] **This highlight must NOT appear on any other button in the panel** — Default speed,
  Percentage/Fixed/Custom/None, Off/On, or (critically) Reset all sprint data. A real bug
  briefly leaked it onto all of these via an unscoped `QPushButton:focus` rule; confirm via
  screenshot comparison across a full navigation pass, not just a glance
- [ ] Resting the real mouse on a DIFFERENT grid button than the keyboard-focused one:
  exactly one of the two shows a highlight at a time, never both (kbdnav hover-suppression)

**Text fields (Sleep's custom-duration input; Sprint's custom-duration and custom-grace-period
inputs)**
- [ ] Left/Right on a focused text field do NOT move the text cursor and do NOT dead-end —
  they act like Down/Up respectively (there's no horizontal sibling to distinguish the two)
- [ ] Up/Down on a focused text field move rows normally, untouched by the above
- [ ] Typing a digit while focus is ANYWHERE ELSE on Sleep or Sprint redirects into that
  panel's DURATION field (not the grace field) and starts typing fresh, replacing any stale
  text — never fires while already inside that field
- [ ] On Sprint specifically, with Grace mode = Custom (so `custom_grace_input` is visible):
  typing a bare digit still goes to the DURATION field, never the grace field

**Panel-specific**
- [ ] Sprint's grace-period submenu (Percentage/Fixed/Custom sub-rows) is fully reachable by
  arrow navigation in EVERY grace mode that shows it — this was completely unreachable before
  a real fix (a bare-`QWidget`-wrapper case `flat_panel_rows` didn't handle at all)
- [ ] Sprint responds to Tab and Shift+Tab at all (a pre-existing, unrelated gap — the panel
  was simply missing from the Tab-cycling dispatch list)
- [ ] `disable_sleep_btn`/`disable_sprint_btn` show ONLY a hover-style fill for both mouse and
  keyboard focus — no traveling marker ever appears on them
- [ ] `stats_reset_btn` ("Reset all sprint data") shows ONLY the traveling marker — no fill of
  any kind, confirming it was NOT swept up by the grid's keyboard-focus rule
- [ ] Closing any of the three panels (Escape, gutter click, or its own action) never shows the
  marker visibly sliding off-panel with the close animation

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

## Panel blur — clip, timing, carousel, opaque-tab skip — 2026-07-27

**All of these are LIVE-ONLY checks.** Every bug in this section was invisible to offscreen
harnesses — the double-render came back byte-identical in every scripted comparison and was only
ever visible in the running app. Do not treat a passing script as coverage here.

### Sliver clip (cover art / theme bg_image / quotes — all one `visual_area` widget)
- [ ] Open Settings over a book with cover art: the ~20px sliver to the RIGHT of the panel stays sharp; the area behind the panel blurs
- [ ] Same with a theme that has a `bg_image` ("The Overlook" plus one other) — sliver sharp, occluded part blurred
- [ ] Quote screen (no library folders configured): same split, no hard-edged artifacts during the slide
- [ ] Library panel: no blur artifacts and NO sharp strip — it is full-width and opaque, so it is skipped entirely (null clip), not given a full-rect clip
- [ ] "No book selected" label blurs (subtly — it is bold text; verify it is not sharp rather than expecting an obvious effect)

### Blur-in timing and the double-render regression
- [ ] Panel open: blur starts only AFTER the panel has settled, not during the slide — it must not run ahead of the panel and expose a clip edge over uncovered content
- [ ] Blur builds smoothly (1500ms InOutQuad) with **no bright/"thick" flash** at any point — a momentary double-image means the two-pass `draw()` has regressed
- [ ] Settings > Blur ON toggle: same, no flash (this path has no panel slide, so it isolates the render from the timing)
- [ ] Settings > Blur OFF: clears promptly (500ms), live view returns as the panel slides away
- [ ] **Diagnostic if a flash ever reappears:** temporarily raise `_BLUR_IN_MS` (panels.py) to ~8000. A one-frame artifact stays a blip; a render bug stretches with the animation. This is what identified the original double-render.

### Carousel (no-book state)
- [ ] Fresh launch with no book loaded: the carousel appears **at startup**, without needing to load and unload a book first
- [ ] Panel open over the carousel: thumbnails blur along with the stripe and "Go to Library" button — no sharp thumbnails against a blurred stripe
- [ ] Carousel keeps scrolling smoothly while blurred — no frozen strip, no ghosting, no horizontal seam across the thumbnails
- [ ] Panel close: carousel un-blurs cleanly, no blurred band left behind
- [ ] Blur toggle on/off with a panel open over the carousel: no geometry jump, no clipped "Go to Library" button

### Opaque Timeline tab (grab skip)
- [ ] Stats → Timeline with blur on: no blur is applied behind the panel (correct — the tab is deliberately opaque so the heatmap's alpha-encoded minutes stay readable)
- [ ] Stats → Overall / Day / Week / Month: blur DOES apply normally on those tabs
- [ ] Switch Timeline → another tab → back: no stale blurred band left behind the opaque tab in either direction

### Tassel (bookmark) with blur ON
- [ ] Resting state: gentle idle sway continues normally
- [ ] Click the bookmark: it swings visibly — not stiff/motionless (regression check for `hideEvent` resetting the kick)
- [ ] The swing runs at normal speed, not slow motion (it should settle in ~1.4s; noticeably slower means the sway timer is being starved again)

### Slider drags while a panel is blurred — 2026-07-31

The grab hides the active panel, and hiding a widget mid-drag destroys `QAbstractSlider`'s drag
state. Grabs are now suspended for the length of any slider drag. **All live-only** — the offscreen
harness could reproduce the value-pinning but said nothing about what the screen looked like, which
is exactly how the first attempted fix shipped a worse bug.

- [ ] Stats → Week or Month (pick a period with enough rows to overflow), drag the scrollbar handle: it tracks the mouse for the full length of the drag
- [ ] **Switch tabs, then drag again** — this is the repro that made the original bug appear tab-dependent; it must work on every tab, every time, with no close/reopen needed
- [ ] Drag with a book **playing** (the grab only ticks when something repaints) — still tracks
- [ ] All three Panel background modes (Transparent / Frosty glass / Opaque): drag works in each
- [ ] **Panel must never blank during a drag** — regression check for the reverted first fix, where the grab photographed the panel itself and the rows visibly disappeared and restored one by one
- [ ] Wheel-scroll and gutter-click still work (one-shot interactions, unaffected by the gate — they kept working even when the drag was broken, which is what made the bug look scrollbar-specific)
- [ ] On release, the blurred transport strip refreshes to current content — no stale band left behind
- [ ] **Accepted, not a bug:** during a long drag the blur freezes, so a scrolling title / a chapter slider on a short chapter drift out of sync with the live widget until release. Verify it *resolves on release*; the drift itself is expected (see DEBT_INVENTORY.md)
- [ ] Transport progress slider (a `ClickSlider` in the main window, not a panel): still drags normally — the gate keys off `QAbstractSlider`, so confirm it didn't catch anything it shouldn't
- [ ] Start a drag, then close the panel mid-drag: no stuck state, no leftover polling (the drag watcher must not outlive the overlay)

### Declined-tick re-arm (hover / hover-out / gutter click / tab click after hovering / Change now) — 2026-08-05

`refresh_dirty`'s hover-active and post-restyle-cooldown gates decline a tick without consuming its
dirty union, on the assumption a later real paint will pick it up — which fails specifically when
the eventual snapback is a genuine no-op (the hovered theme never diverged from what's already
applied) and produces no Paint event of its own. `_rearm_after_decline`/`_fire_rearm` retry a
declined tick on a delay instead of waiting on a paint that may never come. Fixed 2026-07-27
(`ac87e0a`), live-verified 2026-08-05 (`tools/blur_rearm_live_probe.py` — see NOTES.md). **All
live-only**, same as the rest of this section.

- [ ] Open Settings with a panel blurred, hover a theme swatch different from the committed one, hold the hover a few seconds: the blurred transport bar keeps refreshing (no visible freeze on an old frame)
- [ ] Un-hover (move off the swatch) back to the committed theme without ever selecting anything: the blurred transport bar is NOT left showing stale colors — it should match the live (committed) theme within about half a second
- [ ] Hover a swatch, then click the right-hand gutter to dismiss the panel while still hovering: no stale blurred frame left over on the way out, and the transport bar looks correct once the panel is gone
- [ ] Hover a swatch, then click a DIFFERENT Settings tab (not Themes) while the hover is still active: the blurred transport bar does not freeze on the hovered theme's colors — it settles to whatever theme is actually committed
- [ ] Hover a swatch, then click "Change now": the blurred transport bar updates to the newly-committed theme, not stuck on the pre-click hover preview
- [ ] Repeat the hover/un-hover cycle several times in a row (rapid re-hover before the previous one settles): no permanently frozen blur at the end of the sequence
- [ ] **Diagnostic if a stale/frozen blurred frame ever reappears:** grep the log for `refresh_dirty tick=` lines — a long run of `EARLY-RETURN reason=hover_active_gate` or `reason=cooldown_gate` with no eventual `COMPOSITED` afterward means the re-arm regressed; it should always eventually land a `COMPOSITED` once the hover ends and the cooldown clears.

### Stale-cache regressions (state is correct; only the cached pixmap goes stale)
- [ ] Remove the last scan location while a panel is open with an active book: no ghost transport buttons left over the quote screen
- [ ] General tell for this bug class: if closing and reopening the panel fixes the visual, it is a missed repaint, not wrong state — look for a content change that produced no Paint event on a tracked widget

### Book Detail panel backdrop — 2026-08-01

Book Detail is the only panel that opens ON TOP of another one, and the only one that owns its frost
as its own child (the shared overlay is a child of `content_container` and can never rise above a
panel parented to `main_window` — that attempt shipped completely invisible). **Live-only**: the
first failed attempt logged a correct rect, a non-null pixmap and a completed grab while showing
nothing on screen, so a green log proves the grab ran, never that anything is visible.

Do all of these with **Panel background = Frosty glass**.

- [ ] Stats → click a book row → Book Detail: the backdrop is visibly **frosted**, not sharp. Compare against Transparent mode — if the two look the same, the fix has regressed to the original bug
- [ ] The frost makes the panel's own text **easier** to read, not harder. A sharp, high-contrast image showing through (especially one that looks like the panel's background was removed) means the wash is no longer composited into the frost pixmap
- [ ] Over Stats: the frosted region starts under the **progress bar** and stops ~10px off the bottom — the progress bar itself stays live and unfrosted
- [ ] Library → right-click a book → Book Detail: frosted from under the **title bar** to the bottom (the library is opaque and full-width, so there is more to cover than in the Stats case)
- [ ] No visible offset: the frost must not sit shifted against what is behind it. Check at a hard edge — the Stats panel's right border is the easiest tell
- [ ] Open Book Detail over Stats' **Timeline** tab (the one opaque tab): the frost shows the blurred heatmap, not a blank or skipped grab
- [ ] Close Book Detail: Stats returns sharp and correctly re-blurred behind, with no Book Detail ghost baked into the transport-bar blur
- [ ] Book Detail → tag chip → Tag Manager, and → tag filter → Library: neither leaves a frozen blurred band over the transport bar (these paths close two panels at once)
- [ ] Transparent and Opaque modes: no frost appears at all in either
- [ ] Static-frost check (accepted behaviour, not a bug): open Book Detail over Library while a book is playing — the remaining-time text underneath does not update through the frost. It should read as deliberate, not broken

**Perf tell.** While Book Detail is open there should be exactly ONE `_grab_and_blur` and ZERO
`refresh_dirty` composites (it installs no dirty tracker). Count in the log — the window is between
`frost_panel_backdrop DONE` and the next `hide_for_panel ENTRY`:
```
grep -c "_grab_and_blur" ~/.local/state/fabulor/log/fabulor.log
grep -c "DIRTY-TRACE"    ~/.local/state/fabulor/log/fabulor.log
```
A non-zero DIRTY-TRACE count in that window means the tracker is back and the ~64ms grab loop is
running again — **the absence of visible stutter does not rule this out**, a ~3ms grab is entirely
capable of running invisibly.

### Book Detail blur — park/unpark (2026-08-14)

Opening Book Detail used to tear the underlay's blur down entirely and rebuild it at close; that
produced a crisp main window at open-start and again at close-start, the second followed by a 1500ms
fade. The blur is now **parked** — grabbing stops, the last frame stays on screen — so Book Detail's
own geometry occludes and uncovers it with no rebuild. **Live-only**: an offscreen harness returned
byte-identical output for a plainly-visible compositing bug on this exact code (2026-07-27).

All with **Panel background = Frosty glass** and **a book playing** (the grab loop must be genuinely
active before the open, or there is nothing to park).

The two target transitions — watch the transition, not the endpoints:

- [ ] Stats open, main window blurred → click a book row: the main window **never goes crisp** at
      any point while Book Detail slides in. Watch the region right of the panel's left edge
- [ ] Close Book Detail: the main window **never goes crisp**, and there is **no ~1.5s softening**
      afterwards — the blur is simply already there as the panel uncovers it
- [ ] Repeat both 5+ times at varying speeds, including a fast open-close-open. The earlier
      reveal-scanner attempt was *intermittent*, so one clean run proves nothing. Watch specifically
      for transport buttons arriving sharp or late at the panel's trailing edge
- [ ] Stats behind Book Detail going crisp then blurred (the pre-existing minor seam) is unchanged —
      confirm it did not get worse

Paths where a stranded parked frame would show up:

- [ ] Book Detail over Stats → tag chip → Tag Manager: no frozen blurred band over the transport
      bar; Tags gets its own correct blur (`hide_all_panels` closes both, Tags opens 320ms later)
- [ ] Book Detail over Stats → tag filter → Library: no leftover band; Library is opaque and
      full-width so it correctly takes no blur
- [ ] Book Detail opened from **Library** context (right-click a book), then closed: `'library'` is
      absent from the resume map, so this takes the early-return branch — the one that must call
      `discard_parked_frame()`. A band left here means that call was dropped
- [ ] Book Detail over Stats' **Timeline** tab (opaque, `covers_opaquely()`): nothing was parked;
      expect exactly today's behaviour

Regression checks on the five panels that must be untouched by the `_disarm_grabbing` extraction:

- [ ] Settings / Speed / Sleep / Sprint / Stats / Tags: open and close each — blur appears at
      slide-finish, clears at close-start, as before
- [ ] Settings > Blur toggle ON then OFF with a panel open (`apply_blur_live` → `hide_for_panel`)
- [ ] Stats → Week/Month → drag the scrollbar (the drag-watcher lives in the extracted half)

Deferred item — **record what you see, do not fix**:

- [ ] Open Book Detail over Stats for the **currently playing** book, exclude it via the trash
      button (Book Detail stays open in the Stats context), then close. Note whether the stale
      parked frame is visible or stays hidden behind the closing panel. This observation is what
      decides whether the stale-frame invalidation pass is needed — see TODO.md

**Perf tell — not optional.** Between `park_for_panel` and `unpark_for_panel` there must be **zero**
`_grab_and_blur` lines and **zero** `refresh_dirty ... COMPOSITED` lines. A non-zero count means the
~15 grabs/sec feedback loop is back and the design's premise is broken.
```
grep -n "park_for_panel\|unpark_for_panel\|_grab_and_blur\|DIRTY-TRACE" \
     ~/.local/state/fabulor/log/fabulor.log | less
```
Log path is `~/.local/state/fabulor/log/fabulor.log` — **not** `/tmp/fabulor_run.log`. As above, the
absence of visible stutter does not rule this out.

**Cost, stated honestly:** grabs per open/close cycle stay at **2** (Book Detail's own frost, plus
one at unpark). This does not reduce the count — it moves one grab *off* the visible transition.
Read ~10 consecutive cycles **chronologically, unsorted**, before aggregating: the first cycle in a
process differs in kind (cold pixmap) and sorting would hide exactly that.

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

## Muted-volume icon + sleep timer interaction (rewritten 2026-08-10 — mute now takes priority by default)

Mute wins over the sleep label by default; the one exception is a freshly-(re)armed sleep timer
while muted, which shows a transient confirmation for ~2s before reverting to the mute icon.

- [ ] Mute first (volume to 0%, no timer), then start a sleep timer — countdown/confirmation text
      shows immediately (jumps straight to it, no empty-slider preview first — see the
      `_show_volume_overlay` fix below), then reverts to the muted icon after ~2s
- [ ] Start a sleep timer first (not muted), then mute — muted icon appears immediately, no empty
      slider preview, no lingering countdown text
- [ ] While muted with an active sleep timer (past the initial 2s confirmation), the indicator shows
      the muted icon, NOT the countdown — mute wins for the remainder of the timer
- [ ] Unmute while a sleep timer is active — countdown label reappears immediately
- [ ] Let an active sleep timer expire/get cancelled while muted — indicator stays on the muted icon
      throughout (no flash of empty countdown text)
- [ ] Toggling mute on/off repeatedly while a sleep timer counts down — no stuck/blank indicator state
- [ ] Hitting 0% via M key, mouse wheel, or Down arrow (not just slider drag) while a sleep timer is
      armed jumps straight to mute icon (or the transient confirmation, if just armed) — no empty
      slider preview for the full 2s dismiss window (regression check for the fix that closed this
      exact gap)

## End-of-chapter sleep mode (added 2026-08-10)

Test against both an embedded-M4B/CUE book AND a multi-file (VT) book — see NOTES.md 2026-08-10 for
the mechanism (anchor chapter, `user_seek_pending`/`sleep_fired` flags) and why VT specifically.

### Natural arrival (no interaction after arming)
- [ ] Arm end-of-chapter sleep, take no action, let it reach the anchor chapter's own end — playback
      pauses, indicator shows nothing extra (no "Sleep cancelled" text)
- [ ] Repeat on a VT (multi-file) book where the anchor chapter's end happens to coincide with a VT
      file boundary — playback still pauses and STAYS paused (regression check for the
      `_advance_or_finish` unpause race: VT's own near-EOF auto-advance must not silently un-pause
      the sleep-triggered pause within the following ~100ms)
- [ ] Repeat with the anchor as the LAST chapter in the book (fires against `player_dur`, not the
      next chapter's start time)

### Manual cancel
- [ ] Arm end-of-chapter sleep, click the sleep countdown label to disarm — indicator clears
      immediately, no "Sleep cancelled" text at any point
- [ ] Arm end-of-chapter sleep, click the sidebar cancel (X) button to disarm — same, no message

### Seek-driven cancellation
- [ ] Arm end-of-chapter sleep, seek forward past the anchor WHILE PLAYING via each of: Next button,
      chapter-list click, main slider drag, wheel/skip — each shows "Sleep cancelled" for the full
      `_dismiss_ms` window, then clears; playback does NOT pause
- [ ] Same, but landing on the immediately-next chapter specifically (not several chapters ahead) —
      must still show the message (this was the exact case an earlier distance-based heuristic got
      wrong — see NOTES.md 2026-08-10)
- [ ] Arm end-of-chapter sleep, seek forward past the anchor WHILE PAUSED — "Sleep cancelled" shows
      for the full window; playback stays paused (it was already paused, sleep didn't cause it)
- [ ] Arm end-of-chapter sleep, scrub/seek within the SAME (anchor) chapter — sleep stays armed, no
      message, and a later natural arrival still fires correctly (regression check for the
      same-chapter-seek stale-flag bug: such a seek never fires `chapter_changed`, so the flag needs
      the settle-based clear in `update_timer_state`, not just `_on_chapter_changed`)
- [ ] Arm end-of-chapter sleep, scrub within the anchor chapter, THEN seek forward past the anchor —
      "Sleep cancelled" still shows (confirms the flag gets correctly re-set by the second seek, not
      left stuck from the first)
- [ ] Navigate BACKWARD past the anchor — sleep stays armed, no message
- [ ] "Sleep cancelled" text is visible even while muted (confirms it reuses the sleep-just-armed
      transient display mechanism correctly, not swallowed by the mute icon)

### Book switch
- [ ] Arm either sleep mode (timed or end-of-chapter), switch to a different book from the library —
      sleep silently disarms (no "Sleep cancelled" message, no confirmation banner) — a sleep timer
      is scoped to the book it was armed on
- [ ] Restarting the SAME finished book (EOF → Restart) does NOT disarm an active sleep timer — only
      an actual switch to a different book does

## Listening Sprint (added 2026-08-10/11, extended 2026-08-11 and 2026-08-12)

Sprint (sidebar, `R` key) is a structural sibling of the sleep timer — same 200ms-polled indicator
zone, same shared `sleep_timer_label`. See NOTES.md 2026-08-10/11 for the original mechanism (grace
pool, `time.time()`-based clock, shared-label interference bug), NOTES.md 2026-08-11 for the
backward-seek unit-mismatch bug, book-switch cancellation, and end-of-chapter mode, and NOTES.md
2026-08-12 for stats tracking, grace-warning pulsation, and the Reset all sprint data button's
three-round layout/styling fix trail.

### Basic run
- [x] Set a short sprint (e.g. 5 min) — indicator shows `-MM:SS | TT:TT`, remaining ticking down,
      total staying fixed
- [x] Sprint indicator text updates every ~200ms while playing, does NOT freeze or go blank at any
      point during a normal run (regression check for the shared-label interference bug — sleep's
      own per-tick emit must not blank sprint's text)
- [x] Panel background is fully opaque/themed, same as Sleep's panel — NOT transparent or missing
      (regression check for the literal-selector background bug)
- [x] Let a sprint complete naturally — "Sprint completed" shows for the full dismiss window (~2s,
      matching Sleep's own message timing), then clears; playback CONTINUES uninterrupted (sprint
      completion never pauses, unlike sleep)
- [x] Cancel via the sidebar × or the panel's own cancel button — sprint disarms immediately, no
      message shown (matches Sleep's manual-cancel behavior — only pool-exhaustion ("Sprint failed"),
      book switch ("Sprint cancelled"), and a seek-driven EOC crossing ("Sprint cancelled") show one)

### Grace mode selector (redesigned 2026-08-11 — was a flat None/3s/5s/15s/30s row)
- [ ] Open the panel — Percentage mode selected by default (new-install default), 2% submenu row
      visible and flush with the duration grid's right edge, correct preset highlighted
- [ ] Switch None → Percentage or Fixed — submenu appears immediately at the correct position, no
      flicker/flash of the wrong position first (regression check for the container-shown-before-
      child-row-visible ordering bug)
- [ ] Switch to Custom — input field visible, no Set button (removed 2026-08-12 in favor of live
      validation), text centered
- [ ] Switch to None — submenu container hides entirely, no empty gap left behind
- [ ] Each preset row (Percentage: 2/5/10/15/20/25%, Fixed: 5/10/15/30/45/60s) — 6 buttons, flush
      with the duration grid above, no visible gap on the right edge
- [ ] Custom grace input: type a value — saves immediately on every keystroke, no Set click needed;
      caps at 3 digits (999s max); clear the field — in-memory grace becomes 0 for the current
      session WITHOUT overwriting the last saved config value (relaunch restores the last valid
      value, even if the field was left empty); Escape and right-click both clear the field
- [ ] Close and relaunch the app — grace mode AND the selected value within that mode both persist,
      AND the mode button shows as visibly selected immediately on panel open (not just after
      clicking something — regression check for the missing startup `update_panel_styling()` call)

### Grace pool
- [ ] Pause mid-sprint — indicator switches from the running countdown to a "Grace MM:SS" countdown
- [ ] Unpause before grace exhausts — sprint countdown resumes correctly, consumed grace time is
      deducted from future grace windows (repeated brief pauses shouldn't refill the pool)
- [ ] Let grace exhaust while paused — "Sprint failed" shows for the full dismiss window (~2s,
      not the near-instant dismissal this session found and fixed — see NOTES.md), then clears
- [ ] Set grace to "None" — pausing at all cancels the sprint immediately (no grace window)
- [ ] Forward seeking mid-sprint does NOT consume grace or pause the sprint (seeks are free)

### Grace-exhaustion warning pulsation (added 2026-08-12)
- [ ] 6s grace pool, pause — no pulsation for the first 1s, starts at 5s remaining
- [ ] 30s grace pool, pause — pulsation starts at 10s remaining (20s into the pause), not before
- [ ] 120s+ grace pool, pause — pulsation starts at 15s remaining (105s into the pause)
- [ ] Unpause mid-pulsation, before grace exhausted — pulsation stops immediately, indicator label
      returns to full opacity (not left mid-fade)
- [ ] Pause until grace exhausts — pulsation stops exactly as "Sprint failed" appears (not still
      pulsating behind the message)
- [ ] EOC sprint — same pulsation behavior as duration mode (grace pool applies identically)

### Books / Sprints stats (Overall tab, added 2026-08-12)
- [ ] Overall tab shows exactly 10 rows, NO vertical scrollbar — even with mouse wheel scrolled over
      the tab (regression check: `ScrollBarAlwaysOff` alone does not stop wheel-scroll, the scroll
      area's wheelEvent must also be no-op'd)
- [ ] "Books" row shows "N started · M finished" — M counts DISTINCT books ever finished (an
      unfinish-then-refinish of the same book must not double-count)
- [ ] Arm and cancel a sprint (any method) — "Sprints" row's started count increments; finished
      count does NOT
- [ ] Arm and let a sprint complete naturally (duration or EOC mode) — finished count increments,
      "Average successful sprint" updates, WHILE Stats stays open on the Overall tab (no tab switch
      or panel reopen needed — regression check for the missing live-refresh-while-visible bug)
- [ ] Relaunch — Sprints/Books counts persist correctly

### Reset all sprint data (added 2026-08-12)
- [ ] Button sits pinned to the bottom of the Sprint panel, same margin from the panel edge as
      Stats' "Reset all listening stats" — NOT floating with empty space below it (regression check
      for the addStretch-placement bug: the stretch must come BEFORE the reset button/confirm block,
      not after, or the button floats wherever the content above happens to end)
- [ ] Visual style (solid-fill on hover, outline at rest) matches Stats' "Reset all listening stats"
      and Book Detail's "Delete listening history" exactly — NOT a plain outline with no hover fill
      (regression check: `get_sprint_stylesheet` must define its own `#stats_reset_btn` rule; the
      object name being shared with those two panels does NOT mean the styling is automatically
      shared — each stylesheet function is independently scoped)
- [ ] Click the button — confirmation label appears directly ABOVE the button (the button itself
      stays visible and unchanged the whole time — it is never hidden or disabled during confirm),
      no layout shift anywhere else in the panel
- [ ] Click anywhere else in the app while confirming — dismisses the confirmation (matches Stats'
      own click-outside-dismisses behavior)
- [ ] Escape while confirming — same as click-outside, dismisses immediately
- [ ] 7 seconds pass with no interaction — confirmation dismisses on its own
- [ ] Confirm (click the label) — `sprint_attempts`/`sprint_sessions` both emptied; Overall tab's
      Sprints row resets to "0 started · 0 finished", Average successful sprint resets to "—"
- [ ] Start a sprint while the Sprint panel is open (or leave it open, then arm from elsewhere) —
      the reset button is NOT visible while a sprint is active; when the sprint ends (any way —
      cancel, fail, or complete) WHILE THE PANEL STAYS OPEN, the reset button reappears immediately
      without needing to close and reopen the panel (regression check: `disable_sprint()` must show
      the button synchronously — the panel-open-only sync path alone is not enough, since it never
      re-runs on a disarm that happens while the panel is already open)

### Backward-seek compensation (added 2026-08-11, config-gated, default Off)
- [ ] Toggle Off (default) — seeking backward during an active sprint does NOT change the displayed
      remaining time at all
- [ ] Toggle On — seeking backward visibly extends the remaining time by the rewound distance,
      converted to WALL-CLOCK seconds (at e.g. 2x speed, a 5-second backward seek should add ~5
      seconds to the timer, NOT 10 — regression check for the speed/wall-clock unit-mismatch bug;
      test explicitly at a non-1x speed, the bug was invisible at 1x)
- [ ] Toggle On, seek forward then seek back to the same spot — KNOWN GAP, not fixed: this currently
      still inflates the sprint duration by the full backward distance with no credit for the earlier
      free forward seek (a 10-min sprint, +20min forward, -20min back, becomes a ~30-min sprint).
      This is why the setting defaults Off — do not treat this as a regression, it's the documented
      reason the toggle exists. See NOTES.md 2026-08-11 and TODO.md.
- [ ] Setting persists after relaunch

### Book switch cancels an active sprint (added 2026-08-11)
- [ ] Start a sprint, switch to a different book via the library — sprint disarms, "Sprint cancelled"
      shows for the dismiss window, then clears; the new book does NOT inherit the sprint
- [ ] Confirm this is DISTINCT from manual cancel: sidebar ×, panel cancel button, and both
      sleep/sprint conflict-gate confirms must all still disarm SILENTLY, no message

### End-of-chapter mode (added 2026-08-11)
- [ ] Click "End of chapter" in the duration grid — sprint arms, indicator shows `00:00 | chapter`
      and ticks UP (elapsed, not counting down like duration mode)
- [ ] Let playback reach the anchor chapter's end naturally (no seeking) — "Sprint completed" shows,
      playback continues uninterrupted (matches duration mode's own non-pausing completion)
- [ ] Arm, then seek forward past the anchor chapter (chapter-list click, Next button, or slider) —
      "Sprint cancelled" shows (NOT "Sprint failed" — this is a seek-driven interruption, not a grace
      failure)
- [ ] Arm, then seek backward — sprint stays armed, elapsed continues ticking from where it was (no
      cancellation for backward navigation)
- [ ] Arm, then pause until the grace pool exhausts — "Sprint failed" shows (grace still applies in
      EOC mode)
- [ ] Arm, navigate backward to an earlier chapter, then play forward through to the ORIGINAL anchor
      chapter's end — sprint completes normally (the anchor is fixed at arm time; backward navigation
      alone never cancels, only a seek that lands PAST the anchor does)
- [ ] With backward-seek compensation toggled On, seek backward during an EOC sprint — the elapsed
      display does NOT change from the compensation (EOC mode is exempt — it has no duration budget
      to extend)
- [ ] Arm an EOC sprint while the sleep timer is active — the sleep/sprint conflict confirm still
      appears correctly
- [ ] "End of chapter" button visually matches Sleep's own "End of chapter" button — same color/style
      as the numbered presets (NOT the grace-mode-selector button style), flush with the duration
      grid's right edge, no 1px gap

### Mute interaction (mirrors Sleep's own mute-priority section above)
- [ ] Arm a sprint while muted — sprint text shows briefly (~2s) as confirmation, then reverts to
      the mute icon
- [ ] While muted with an active sprint (past the initial confirmation), the indicator shows the
      mute icon, NOT the countdown
- [ ] Pause mid-sprint while muted — entering the grace countdown ALSO gets its own brief transient
      reveal before reverting to the mute icon (this is sprint-specific — the grace-entry transition
      needed its own detection separate from the arm-time one; see NOTES.md)
- [ ] Unmute while a sprint or its grace countdown is active — the relevant text reappears
      immediately

### Mutual exclusion with Sleep
- [ ] Arm a sprint, then try to arm the sleep timer — a confirm overlay appears IN THE SLEEP PANEL;
      confirming cancels the sprint and arms sleep; letting it time out (7s) or not confirming
      leaves both states unchanged
- [ ] Arm the sleep timer, then try to arm a sprint — same, confirm overlay appears IN THE SPRINT
      PANEL this time; confirming cancels sleep and arms the sprint

### Panel-open button flash
- [x] Arm a sprint (or sleep timer) from its own panel — the panel closes on arm; the "Cancel the
      sprint"/"Disable the sleep timer" button does NOT visibly flash on screen for a frame before
      the panel slides away (confirmed live 2026-08-11, across multiple rounds of this session's
      testing — previously flagged as not yet re-verified)
- [x] Reopen the panel after arming — the Cancel/Disable button IS correctly visible now (confirms
      the deferred-to-panel-open sync)

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

## App-wide Tab / Escape key policy (added 2026-07-09)

Global behavior installed in MainWindow's app-wide event filter. Library's own Tab/Escape
handling (search field, list) is a separate, more specific mechanism — see the Library panel
"Keyboard navigation" section above; it composes with this policy rather than being replaced by it.

- [ ] In EVERY context (no panel open; Library; Settings; Speed; Sleep; Tags; Book Detail open) — repeatedly pressing Tab NEVER moves focus to the window's minimize or close button
- [ ] With no panel open: Tab does nothing
- [ ] Settings panel open: Tab cycles through the ACTIVE tab's controls in a sensible order, wrapping at the end back to the first; Shift+Tab (Backtab) cycles backward; never lands on minimize/close
- [ ] Settings → Themes tab specifically: Tab cycles the mode row, the swatch grid (as ONE stop), the bulk row, and the interval row — see the dedicated Themes tab section below for what Tab does entering/leaving the swatch grid specifically
- [ ] Speed panel open: Tab cycles that panel's controls with wrap, same as Settings
- [ ] Sleep panel open: Tab cycles that panel's controls with wrap, same as Settings
- [ ] Tags panel open: Tab does nothing (no controls wired for cycling yet)
- [ ] Book Detail panel open (not editing a field): Tab does nothing
- [ ] Book Detail panel open, editing a metadata field, press Escape: edit cancels, panel stays open (unaffected by this feature — BookDetailPanel's own separate filter still owns this)
- [ ] Book Detail panel open, NOT editing, press Escape: panel closes
- [ ] Library open, search field focused, type something, press Escape: field clears and loses focus; Library panel itself stays open (does NOT also close)
- [ ] Library open, list focused (not search field), press Escape: Library panel closes
- [ ] Settings / Speed / Sleep / Tags panel open, press Escape (not inside a text field): panel closes
- [ ] Sleep panel's custom-minutes text field focused, press Escape: field's own existing Escape behavior runs (clears/defocuses), does not also close the Sleep panel
- [ ] Tag manager's tag-name edit field focused, press Escape: field's own existing Escape behavior runs, does not also close the Tags panel
- [ ] `pytest tests/ -q` stays green (no seek/session paths touched by this feature)

## Main-window transport keyboard shortcuts (added 2026-07-11)

Each key below calls the exact same method the corresponding on-screen button/wheel already
uses — see KEYBINDINGS.md's "Transport / player keys" table for the reuse mapping. Test with a
book loaded unless noted.

- [ ] `Space`: toggles play/pause, at startup and mid-playback — does NOT open the speed menu
- [ ] `Up` / `Down`: volume ±5, same visual overlay as the wheel; holding the key repeats
- [ ] `Alt+Up` / `Alt+Down`: speed ± the configured increment, clamped 0.25×–8.0×; holding the key
      repeats but is throttled (not a raw per-tick jump — feel should be a controlled ramp, not an
      instant jump to the ceiling/floor); a single tap always applies exactly one step
- [ ] `Shift+Left` / `Shift+Right`: long skip back/forward (`long_skip_duration`), same as the
      rewind/forward button's right-click, including the undo-overlay capture
- [ ] `Ctrl+Left` / `Ctrl+Right`: previous/next chapter, same as the chapter nav buttons and the
      progress-slider wheel
- [ ] `m`: mutes (drops to 0); pressing again restores the prior volume; manually dragging the
      slider back up while "muted" and then pressing `m` again stores a FRESH value (does not
      restore the old pre-mute value)
- [ ] `u`: undoes the last seek ONLY while the undo affordance is visibly showing; no-op (and no
      crash) when it isn't
- [ ] Bare `Left`/`Right` (no modifier) do nothing — this is intentional, not a bug (only the
      Shift/Ctrl variants are bound)
- [ ] `Ctrl+T` no longer rotates the theme (bare `T` still does) — a deliberate side effect of
      adding real modifier support to the dispatcher
- [ ] No book loaded: `Space`/`Up`/`Down`/`Alt+Up`/`Alt+Down`/`m` are inert (no crash, no
      change) — the transport is hidden/disabled in this state anyway, but confirm no stray
      exception if a key is fired in a race with book unload

## Keyboard focus ownership (added 2026-07-11)

The invariant: exactly one widget owns real keyboard focus at a time, and global shortcuts only
fire when that owner is MainWindow itself or nothing panel-local — never while a panel/overlay is
open and one of its own widgets holds focus. See CLAUDE.md's "Keyboard focus ownership" rule and
NOTES.md's "Keyboard focus ownership" writeup for the full mechanism and the two dead ends found
while fixing it (do not re-attempt clearing focus BEFORE `hide()` — confirmed live to be silently
undone by `hide()` itself).

- [ ] **Startup, nothing clicked:** `Space` toggles play/pause immediately (not the speed menu);
      no widget shows a focus highlight
- [ ] **Arrow-key spam at idle, nothing clicked:** never opens a sidebar panel, never surfaces the
      volume control's focus ring, never cycles through hidden controls
- [ ] **Library open → close → any shortcut:** every global shortcut (`a`/`s`/`t`/`Space`/etc.,
      not just arrows) fires normally immediately after Library closes
- [ ] **Chapter list open (`C`) → close via a SECOND `C` press → any shortcut:** fires normally
      afterward; the list is not still capturing arrows/Space while visually closed
- [ ] **Chapter list open → close via `Escape`:** same check — shortcuts work immediately after
- [ ] **Book Detail opened from Library (right-click or Alt+Enter a book):**
  - [ ] Library's arrow-key navigation and Space-to-play do NOT fire while Book Detail is the
        visible panel — pressing arrows/Space repeatedly must not silently move the library
        selection or load a book underneath
  - [ ] Book Detail's own Tab-cycle / click-to-edit still works normally
  - [ ] Closing Book Detail returns to Library in its prior state (selection unchanged)
- [ ] **Book Detail: focus a metadata field (click to edit) or the tag-add field, then press
      `Up`/`Down`/`m`/`u`:** the field keeps editing focus, nothing happens to volume/speed/mute/
      undo, and the panel does NOT close
- [ ] **Same check inside Library's search field and any Settings text input:** `Up`/`Down`/`m`/`u`
      typed/pressed there do not leak out to global shortcuts (should type or no-op locally, per
      that field's own behavior — never dismiss the panel or change volume)
- [ ] **Settings / Speed / Sleep / Stats / Tags, opened via the sidebar (the normal path):** each
      panel's own Tab-cycle and mouse interaction work exactly as before this fix; global shortcuts
      (arrows, Space, letters) do nothing while the panel is open, and resume normally after close
- [ ] `pytest tests/ -q` stays green

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

### Corner-hotspot trigger (2026-08-09, `ui/sidebar_hotspot.py`)
- [x] Hovering the 15×15 zone (top-left of the cover art, just under the progress bar) for ~200ms opens the sidebar
- [x] A quick mouse pass-through the zone (shorter than the hover-intent delay) does NOT open it
- [x] The hotspot is invisible — no indicator, no marker, by design (an earlier flat-alpha square indicator was tried and removed; see SESSION.md 2026-08-09)
- [x] While the sidebar is open (either open method), hovering the zone does nothing
- [x] Right-click-opened sidebar does NOT close when the cursor leaves the sidebar's own area — only idle timeout or an explicit dismiss (click-away, nav-item click) closes it
- [x] Hotspot-opened sidebar DOES close as soon as the cursor leaves the sidebar's own area
- [x] With no mouse movement anywhere in the window, an open sidebar (either method) auto-dismisses after ~10s
- [x] Re-arm requires exit + re-entry: after any auto/explicit dismiss with the cursor still resting in the 15×15 zone, hovering does NOT immediately reopen it — moving the cursor out and back in does
- [x] Settings > Controls tab: "Sidebar hotspot" On/Off toggle disables/enables hover-open; right-click-to-open still works regardless of this setting

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

## Transport bar blur (composited overlay, blur enabled in Settings — 2026-07-21)

Applies to every panel that blurs the mini transport bar: Settings, Speed, Sleep, Stats, Tags.
(Library and Book Detail never apply transport-bar blur — not in scope here.)

### Appear timing + fade-in
- [ ] Opening any of the five panels: the transport bar stays LIVE (unblurred) while the panel is still sliding in — no blur visible until the slide-in animation has fully finished
- [ ] Once the panel finishes sliding in, the blur fades in smoothly (not an instant snap) over the panel's mini transport bar
- [ ] The fade-in plays every time a panel opens, not just the first time this session
- [ ] Rapidly reopening a panel (close, then immediately reopen) doesn't leave the blur stuck at partial opacity or double-fade

### Dismiss timing (no lingering blur)
- [ ] Closing any of the five panels: the transport bar snaps back to LIVE view immediately when the close/slide-out animation STARTS — it does not stay blurred for the whole slide-out duration
- [ ] No fade-out animation on dismiss (this is intentional — dismiss is instant, only appear fades)
- [ ] Switching directly between two of the five panels (e.g. Settings → Stats via sidebar) doesn't leave a stale blurred frame visible during the transition

### Cross-panel non-regression
- [ ] Blur still clips to each panel's own width (e.g. Settings' narrower panel doesn't blur the total_time_label sliver past its right edge)
- [ ] Toggling "Blur" off in Settings still fully disables both the appear-fade and the composited overlay (no blur, no fade, transport bar always live)
- [ ] Blur/fade behavior unaffected by which panel triggered it — spot-check at least two of the five (e.g. Speed and Tags) live, not just Settings

### Cursor stability while blur is on (fixed 2026-07-21)
- [x] Resting the mouse motionless over a Stats book row (hand-cursor widget) with blur ON: cursor stays a steady hand, no hand↔arrow flicker
- [x] Resting the mouse motionless over a cover-pool swatch (Settings → Themes tab) with blur ON: steady cursor, no flicker (note: this swatch has no hand cursor set at all — expected arrow, not a regression)
- [x] Resting the mouse over "Change now" with blur ON: steady arrow (it has no hand cursor property — this is correct, not a bug)
- [ ] Real mouse movement between widgets/panels still updates the cursor correctly with blur ON (the override-cursor fix must not stick a stale shape past genuine movement)
- [ ] Same checks with blur OFF: no flicker (this code path doesn't run without blur, so should be unaffected either way)
- [x] Timeline tassel's hover cursor is steady (not shaky) with blur ON (fixed 2026-07-21 — synthetic hide-driven leaveEvent no longer clears the dynamic hand cursor; `leaveEvent` guarded on `isVisible()`)
- [ ] Moving the cursor genuinely OFF the tassel (blur ON) still reverts it to arrow correctly (the real-mouse-out path still works)

### Live blur toggle (Settings > Blur On/Off, applies immediately — 2026-07-21)
- [ ] With the Settings panel open and Blur OFF: clicking Blur **On** immediately blurs the transport bar (bottom part) — no close/reopen needed
- [ ] Same click also re-blurs the cover image immediately (the previously-broken Off→On direction)
- [ ] With Blur ON: clicking **Off** immediately clears both the transport-bar overlay and the cover-image blur
- [ ] Several On/Off cycles: no stuck overlay, no double-apply artifacts, blur matches a fresh open-with-blur-On
- [ ] Close and reopen Settings after toggling: the normal open/close blur flow is unaffected (live-apply didn't corrupt the overlay's active state)

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
- [ ] Mouse wheel over the carousel (added 2026-08-12, `4848eaf`): each wheel notch moves exactly
      one thumbnail — repeated scrolling never leaves a thumbnail partially clipped at either edge
- [ ] Wheel-scroll and arrow-button clicks land on the same positions — scrolling by wheel to a
      given thumb and by arrow clicks to the same thumb produce identical scroll offsets
- [ ] Wheel-scroll at either end of the carousel: no wrap, no crash, display unchanged

### Scroll-arrow overlay (15px sliver, accent_dark / stats_carousel_stripe)
- [ ] Arrow sliver is a flat, fully-opaque solid color — no gradient, no rounded corners, no border
- [ ] Sliver color matches the current theme's `accent_dark` (or `stats_carousel_stripe` if a theme sets it) — not a fixed black/white regardless of theme
- [ ] Switch themes while the stats panel is open (live, not just on next launch): sliver color updates immediately to the new theme's color
- [ ] Hovering the row (not the sliver itself): sliver background is visible but at reduced opacity vs. hovering the sliver directly
- [ ] Hovering the sliver itself: background goes fully opaque, arrow glyph brightens
- [ ] Sliver renders cleanly against both light and dark book covers — no jagged/hard-edged silhouette effect from the old flat-black overlay

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

## Scrollbar right-click jump / row-snap (`ui/scrollbar_jump.py`)

App-wide: right-clicking any scrollbar's gutter jumps the handle to the cursor instead of opening
the native "Scroll here / Top / Bottom / ..." context menu (`1ac70b2`, 2026-07-31). As of
2026-08-12 (`a343b6c`) and 2026-08-13 (`0cbddbd`), five of those scrollbars additionally snap the
jump to a row boundary instead of a pixel-exact position.

### Right-click jump (all scrollbars, base behaviour)
- [ ] Right-click a scrollbar gutter (not the handle) at various points: handle jumps to that
      point, centered under the cursor
- [ ] No native context menu ("Scroll here / Top / Bottom / Page up / ...") appears
- [ ] Right-click directly on the handle itself: no crash, behaves sanely (jumps or no-ops)
- [ ] Left-click on the gutter (native page-step behaviour) is unaffected
- [ ] A scrollbar whose handle fills the entire groove (nothing to scroll): right-click is a no-op,
      still suppresses the native menu, no crash
- [ ] `QComboBox` popup scrollbars, the chapter-list overlay, and `SessionListWidget` are
      unaffected by any of the row-snap changes below (never registered)

### Row-snap — Library panel
- [ ] 3-per-row mode: right-click the scrollbar at several gutter positions — the topmost visible
      row of covers is always fully shown, never clipped mid-row
- [ ] 2-per-row mode: same check
- [ ] Square mode: same check
- [ ] List mode: same check
- [ ] 1-per-row mode (if present in the view-mode rotation): same check
- [ ] Switch view mode (1/2/3/4/5 or the dropdown) then immediately right-click the scrollbar: snap
      uses the NEW mode's row height, not a stale one from before the switch
- [ ] Right-click near the very top and very bottom of the scrollbar range: snap still lands on a
      clean row boundary at both extremes, no off-by-one

### Row-snap — Stats Day / Week / Month tabs
- [ ] Day tab: right-click the scrollbar at several positions — topmost row is always fully shown,
      never clipped
- [ ] Week tab: same check
- [ ] Month tab: same check
- [ ] A period with few enough rows that the scrollbar has little/no range: right-click is a
      harmless no-op, no crash

### Row-snap — Tags panel (added 2026-08-13)
- [ ] Right-click the tag-list scrollbar at several gutter positions — topmost row is always fully
      shown, never clipped
- [ ] Existing wheel-scroll and viewport-cap behavior unaffected (unchanged by this fix)

### Self-correction from a dragged scrollbar — Library / Stats / Tags (added 2026-08-13)
- [ ] Library: drag the scrollbar handle to a position that leaves a row half-visible, then wheel-
      scroll once — the half-visible row snaps to fully visible on that same flick
- [ ] After the correction, further wheel flicks scroll by the same amount as before (unchanged
      per-notch behavior)
- [ ] Repeat in each view mode (1-per-row, 2-per-row, 3-per-row, Square, List)
- [ ] Stats Day/Week/Month: same drag-then-wheel check, same result
- [ ] Tags panel: drag the scrollbar to a half-visible row, then press Up or Down (arrow-key nav,
      not real keyboard row-navigation yet) — same on-the-spot correction, same result
- [ ] The four carousels (Recently-finished, cover carousel, etc.) are unaffected — no partial-row
      state to correct

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

#### Square mode geometry (2026-07-09)
- [ ] Uniform 4px gap between covers in both directions (horizontal and vertical), not visually uneven
- [ ] Covers render as true squares — no visible clipping or stretch on any cover
- [ ] Scrolling (wheel or keyboard) never autoscrolls just from hovering near the top/bottom edge without clicking
- [ ] Wheel scroll moves by one full screen of rows (not a fixed 3-row jump that feels arbitrary relative to how many rows are visible)
- [ ] Scrolling to the very bottom of the list reaches the TRUE last row (not stuck a partial row short)
- [ ] Scrolling to the very top reaches the true first row, with the same 4px gap above it as between any two rows (no oversized top gutter)
- [ ] First-ever Library open of a session in Square mode shows correct spacing immediately — does not show an oversized gap that only "settles" after switching modes once

#### 2-per-row mode geometry (2026-07-10)
- [ ] Cover is visibly larger than before (118×180) and the grid shows exactly 2 columns (not 1)
- [ ] Middle gap between the two columns is visibly TIGHTER than the outer left/right margins
- [ ] No sliver of a partial third row visible at the bottom of the viewport
- [ ] Keyboard Up/Down scrolling in this mode reaches the true top and bottom of the list, same as Square
- [ ] Known remaining cosmetic debt (not yet fixed, do not report as new): grid still doesn't fully use all available vertical whitespace — cell size/gaps may look slightly tighter than ideal; this is tracked, not expected to be perfect yet

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
- [ ] Clicking into the search field while a tag filter is active reverts to the last explicitly-typed/searched text (not empty) and allows normal typing from there
- [ ] Opening library manually (sidebar button) while a tag filter is active reverts the field to the last explicit text (not empty)
- [ ] Opening library via tag chip a second time replaces the previous tag filter
- [ ] Tag filter does not persist across app restarts
- [ ] A tag chip whose tag is already the active library filter (library context only) shows a regular cursor and does nothing on click — inert, not a re-set, not a toggle
- [ ] Reopening a book's detail panel after typing `#sometag` manually: the matching chip (if the book has that tag) is inert; other tags on that book remain clickable
- [ ] Click a tag chip to filter, then open a DIFFERENT book's detail panel that also has that tag: that chip is inert there too (live check against current search text, not tied to which specific chip instance was clicked)
- [ ] Click a tag chip to filter, then open a book with a different tag: that different tag's chip remains clickable
- [ ] Tag chip inert/clickable state is unaffected by (and does not affect) the Stats panel or Tags panel entry points to the detail panel — chips there are never clickable regardless of active filter, unchanged

### Search match-state styling (red/no-match vs. normal) stays in sync with book-set changes
- [ ] Search `#sometag` matching exactly one book (field shows normal styling) → remove that tag from the book (Book Detail Panel) → field turns red (fixed 2026-07-18 — see NOTES.md)
- [ ] Re-add the same tag to the same book → field returns to normal styling automatically, without retyping anything
- [ ] With a no-match search active (field red) → exclude a book that would now be excluded from a currently-matching set, or restore/un-exclude a book that now matches → field restyles correctly (normal↔red) without retyping
- [ ] With a no-match search active → mark a book missing (or a missing book's file reappears via rescan) so match state flips → field restyles correctly
- [ ] Leave the search field empty → trigger a library refresh (tag change, scan, exclude/restore) → field stays neutral (no false red)
- [ ] Edit a book's title/author via Book Detail Panel while a related no-match search is active in the library behind it → field restyles correctly (normal↔red) once the edit is saved
- [ ] Sort-only actions (toggle ascending/descending, change sort field) with a no-match search active → field's red/normal state is unchanged by sorting alone
- [ ] Live-typing red/normal toggle (type a no-match search, edit it to match, edit back) still works exactly as before — regression check, unaffected by the above

### Click-to-filter (author/narrator/year, library grid — 1-per-row/2-per-row only)
- [ ] Left-clicking author text sets the search field to the author's name and filters the library
- [ ] Left-clicking narrator text (1-per-row only) sets the search field and filters
- [ ] Left-clicking year text sets the search field to `<YYYY>YYYY` and filters to that exact year
- [ ] Left-clicking title text does nothing special (normal select/play) — title is never a filter target
- [ ] Clicking anywhere else on the card (cover, blank space) still selects/plays the book as before
- [ ] Right-click still opens the Book Detail Panel, unaffected by any of the above
- [ ] 3-per-row, Square, and List modes show no behavior change at all (feature is scoped out of them)
- [ ] Missing narrator/year (1-per-row): that row is blank, not filled by an adjacent field shifting up
- [ ] Hand cursor appears only directly over a field's rendered text, not below/around it in the reserved row slot
- [ ] Hand cursor does not bleed between adjacent field rows (author/narrator/year) when moving the pointer vertically between them

#### Multi-value author/narrator (e.g. "Feist, Wurts")
- [ ] Clicking one name filters to just that name, not the full joined string
- [ ] Hand cursor appears over each name individually
- [ ] Hovering/clicking the separator (`, ` / `; ` / ` and ` / ` & `) shows the default cursor and falls through to normal card selection — not a filter, not the full string
- [ ] While the field is actively scrolling (marquee), holding the cursor still: cursor flips hand→arrow as a separator passes under it, and back to hand as the next name arrives
- [ ] Segment click resolves correctly whether the field is mid-scroll or at rest (short multi-value string that never overflows)
- [ ] No underline, color change, or other visual decoration appears on hover, on any field, scrolling or static

#### Toggle-off / revert reverts to last explicit text (not empty) — applies uniformly to tag AND field clicks
- [ ] Type a search manually, click an author/narrator/year value, click the same value again: field reverts to the manually-typed text, not ""
- [ ] Type a search, click field A, click field B, click a year, click the same year again: field reverts to the originally-typed text (not field A or B — only one explicit value is ever remembered)
- [ ] Type a search, click a tag chip, click a second tag chip: field shows the second tag's filter (not the first, not blank) — clicking a second click-filter must not silently lose the typed text
- [ ] Type a search, click a tag chip, close and reopen the library (sidebar button): field reverts to the typed text, not empty
- [ ] Type a search, click an author, click a tag, click a different author, click that author again: field reverts to the originally-typed text
- [ ] Right-click to clear the field, then click a field value or tag, then click it again (or reopen the library): field reverts to empty (the right-click-clear is itself now the "explicit" value) — right-click behavior itself is completely unchanged
- [ ] With no typed text this session (fresh open, no persisted filter): click a field value, click it again — field reverts to whatever the session's initial value was
- [ ] Left-clicking into the search field while ANY click-filter (tag or field) is showing reverts to the last explicit text and places the cursor there for editing — it does NOT clear to empty
- [ ] Left-clicking into the search field when it already shows the real explicit text (no click-filter active) does nothing special — normal cursor/focus, no revert, no clear
- [ ] "Persist search filter" restart behavior (see that section below) is completely unaffected by any of the above

### Keyboard navigation (added 2026-07-09)
- [ ] Opening the library and pressing Up/Down immediately navigates the list — no click or Tab needed first
- [ ] Up/Down move selection in all five view modes
- [ ] Up/Down scroll the viewport to follow the selection once it moves off-screen, in ALL five view modes including List (2026-07-10 fix: List mode's keyboard nav previously moved the selection but never scrolled the viewport — `setAutoScroll(False)`, set elsewhere to kill unwanted hover-driven autoscroll, also silently disabled Qt's native keyboard-nav autoscroll)
- [ ] Left/Right move selection by one column in 2-per-row, 3-per-row, and Square
- [ ] Left/Right are a no-op in 1-per-row (no adjacent column)
- [ ] Left/Right in List mode do NOT move the row selection — see the dedicated "List mode title/author keyboard expand" section below
- [ ] Enter or Space on the selected row plays that book (same as left-click)
- [ ] Alt+Enter on the selected row opens Book Detail on the Stats tab (same as right-click)
- [ ] On open (or after any panel/dialog interaction that drops focus), NEITHER the search field NOR the list has focus — pressing Tab moves to the search field; pressing any arrow key moves focus to the list AND performs that arrow's action in one press (2026-07-09 Tab-cycle redesign: no longer list↔search toggle)
- [ ] Tab from the search field moves focus to "nothing focused" (not directly to the list) — the search field loses focus but the list does NOT gain it
- [ ] From "nothing focused," pressing Tab moves focus to the search field
- [ ] From "nothing focused," pressing an arrow key moves focus to the list AND performs the arrow's action (no wasted keypress)
- [ ] Tab never moves focus to the sort combo, view-mode combo, sort-direction button, or Back button
- [ ] Tabbing away from the list drops the keyboard-selection highlight instantly (no fade-out wait) in every mode EXCEPT List, where it is unaffected (List's highlight is the mouse-hover-fade mechanism, not the generic highlight)
- [ ] Typing `_the` in search matches only titles STARTING WITH "the" (e.g. not "In the Woods")
- [ ] Existing `#tag` / `>NNNN` / `<NNNN` / year-range search syntaxes still work after the `_prefix` addition
- [ ] Mouse hover sets the real selection too — hovering book B then pressing Enter/Alt+Enter acts on B, not a stale keyboard-selected book
- [ ] Moving the mouse onto a keyboard-selected row clears the keyboard highlight instantly (no stacked highlight)
- [ ] Moving the mouse onto a DIFFERENT book than the keyboard-selected one fades the keyboard highlight out quickly, not after its full ~2.5s timer
- [ ] Keyboard-selection highlight (1-per-row) is a themed tint; grid modes (2/3-per-row, Square) show the same duration/progress overlay mouse hover shows, with no separate tint underneath it
- [ ] List mode's keyboard highlight follows the Hover-fade setting (Fast/Normal/Slow) — fades in per that speed
- [ ] List mode's keyboard highlight with Hover-fade set to Off shows an instant fill (not silently invisible)
- [ ] Clicking the sort dropdown or view-mode dropdown to make a selection returns keyboard focus to the list afterward — arrows immediately drive the list again, not the dropdown
- [ ] Same check after clicking a dropdown open and dismissing it WITHOUT choosing a value (click away)
- [ ] Sort/view-mode dropdown popups show a proper themed hover highlight on the item under the cursor (no thin dark lines / missing highlight)
- [ ] Sort/view-mode dropdown closed-state arrow renders as a themed triangle, not a plain light square
- [ ] Sort/view-mode dropdown corners (all four) stay fully rounded — no square/flat corner near the arrow
- [ ] Alt+Enter on the already-open book does NOT re-trigger the slide-in animation on repeat presses
- [ ] With Book Detail Panel already open (any entry point), arrow-navigating to a different book in the library list and pressing Alt+Enter does NOT retarget or re-slide the open panel — it stays exactly as-is
- [ ] Book Detail Panel must be closed (its own close button, or the existing close flow) before a different book's detail can be opened

### Sort-field and view-mode keyboard shortcuts (added 2026-07-10, list-focus-scoped only)
- [ ] With the search field focused (not the list), typing `t`, `a`, `r`, `d`, `y`, `p`, `f`, or any digit 1–5 types normally into the field — no sort/view change
- [ ] With the list focused: `t` / `a` / `r` / `d` / `y` sort by Title / Author / Recent / Duration / Year respectively, matching the dropdown's own field selection
- [ ] Pressing the letter of a sort field that is NOT currently active switches to it at that field's correct default direction (Title/Author → ascending ↑; Recent/Duration/Year → descending ↓)
- [ ] Pressing the letter of the CURRENTLY active sort field toggles direction (↑↔↓), identical to clicking the ↑/↓ button — repeat presses keep toggling indefinitely, never sticks or skips
- [ ] Holding a sort letter down does NOT rapid-fire the toggle (autorepeat suppressed)
- [ ] `p` (Progress): with at least one book that has progress, switches to Progress sort; with NO books having progress (so "Progress" isn't in the dropdown), `p` is a silent no-op — no field change, no direction change
- [ ] `f` (Finished): same as above, gated on at least one finished book existing
- [ ] Digits `1`–`5` switch view mode to 1-per-row / 2-per-row / 3-per-row / Square / List respectively, matching the view-mode dropdown
- [ ] Pressing the digit for the CURRENTLY active view mode is a no-op — no flicker, no re-layout, no re-triggered slide/reveal animation
- [ ] Holding a view-mode digit down does NOT repeatedly re-trigger the switch
- [ ] After any of the above, arrow-key row navigation, Enter/Space/Alt+Enter, and the Tab focus-cycle all continue to work unchanged

### List mode title/author keyboard expand (added 2026-07-10, List mode only)
- [ ] A row where BOTH title and author already fit their slots without eliding: Left and Right do nothing at all — no expand, no elide change, in any state
- [ ] A row with a LONG title and a SHORT author: the row shows title EXPANDED (invading the author's slot) the moment it becomes the keyboard selection — this is the starting state, not something you have to press Left for
- [ ] From that title-expanded starting state, Right moves the title back to its normal place (both fields shown elided/fit as normal)
- [ ] From that normal/collapsed state, Right again is a no-op (author is too short to ever expand)
- [ ] From that normal/collapsed state, Left re-expands the title
- [ ] A row with a SHORT title and a LONG author: shows in the normal/collapsed state (nothing pre-expanded) the moment it becomes the keyboard selection
- [ ] From that normal state, Right expands the author (invading the title's slot)
- [ ] From author-expanded, Right again is a no-op (already there)
- [ ] From author-expanded, Left shrinks the author back to the normal/collapsed state
- [ ] A row with BOTH title and author long: shows title EXPANDED the moment it becomes the keyboard selection (same starting state as the long-title/short-author case)
- [ ] From title-expanded, Right goes DIRECTLY to author-expanded — it does NOT pass through/land on the normal collapsed state
- [ ] From author-expanded, Left goes DIRECTLY back to title-expanded — same non-collapsing toggle, in both directions
- [ ] For a both-long row, repeatedly alternating Left/Right toggles cleanly between title-expanded and author-expanded indefinitely — never lands on the collapsed state, never gets stuck
- [ ] Navigating away from an expanded row (Up/Down to a different row) and back: the row is reset to its OWN starting state (title-expanded if its title is long, collapsed otherwise) — nothing is remembered from the previous visit
- [ ] Mouse hover on any row (including one with keyboard-forced expand state) still works exactly as before — hovering title/author zones expands them independently of whatever the keyboard last set, unaffected
- [ ] After using keyboard Left/Right to expand a row, moving the mouse over a DIFFERENT row's title/author and back does not leave any stale keyboard-forced expand visible on the original row
- [ ] This entire feature has zero effect on any other view mode (1-per-row, 2-per-row, 3-per-row, Square) — their Left/Right column-move behavior is unchanged

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
- [ ] "Reset all listening stats" (renamed from "Reset all stats" 2026-08-12, moved 3px down) prompts
      confirmation, clears all data, refreshes all tabs

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
- [ ] A book that is BOTH finished AND archived (excluded/deleted/missing): title still shows in finished color, not the plain/unfinished color — only the cover thumbnail dims for archived state
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
- [ ] "Reset all listening stats" button shows inline confirmation label above the button on first click
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
- [ ] Opens from Library via Alt+Enter on the keyboard-selected book (see Library panel > Keyboard navigation)
- [ ] Close button slides panel out and returns to previous view
- [ ] Panel is full window width, fully covers other panels (no bleed-through)
- [ ] Clicking anywhere outside the panel does not close it (guard in mousePressEvent)
- [ ] Theme applied correctly on first open (no system color fallback)
- [ ] Bar colors update on theme change (curr_chap_highlight / library_slider_bg)
- [ ] Requesting detail again while already open (any entry point, same or different book) is a no-op — no re-slide, no retargeting; panel must be closed first (added 2026-07-09)

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
- [ ] **The caret lands in the field that was clicked**, not in Title (fixed 2026-07-30 — clicking Narrator used to select the narrator text and then move the caret to Title)
- [ ] Narrator and year fields appear with placeholders even when previously hidden
- [ ] Year field rejects non-digit characters; minus sign allowed as first character only
- [ ] Year field accepts at most 4 digits — typing or **pasting** `14451` cannot produce a 5-digit year (fixed 2026-07-30; the paste path bypassed the old validator and reached the DB)
- [ ] A negative year (e.g. `-500`) saves and survives a restart

#### Empty fields (added 2026-07-30)
- [ ] Clearing a field's text and saving leaves a dimmed placeholder ("Title" / "Author" / "Narrator" / "Year") in read-only mode — the field is still visible and still clickable back into edit mode
- [ ] All four fields can be emptied at once and the panel remains fully navigable (click and Tab both still enter edit mode)
- [ ] **Library regression:** with a book whose title is empty, open the library and type in the search field — no crash, and the panel keeps working for the rest of the session (fixed 2026-07-30; the crash used to strand the model mid-reset, breaking every subsequent filter and sort until restart)
- [ ] Same check for an empty author
- [ ] Sorting by Title and by Author with an empty-titled/empty-authored book present does not crash

#### Text selection with the mouse (added 2026-07-30 — Qt drag-select workaround)
Applies to **every** text input in the app: Book Detail metadata fields, library search, tag name (Tags panel), tag input (Book Detail), and the sleep-timer custom duration.
- [ ] Double-clicking a word selects the **whole** word and it stays selected — no silent shrink to a prefix a moment later
- [ ] Cut/Ctrl+X immediately after a double-click removes the entire word, not a prefix of it (this was real data loss: cutting "Andrew" left "rew Kishino")
- [ ] A single click places the caret and selects **nothing** — it does not highlight a run of text from the field's left edge to the click point
- [ ] A deliberate click-and-drag still selects normally, from the first real movement
- [ ] A deliberate *fast* drag still registers (the 120ms `_DRAG_DWELL_MS` in `ui/line_edit_dragfix.py` is the knob if this starts failing)
- [ ] Triple-click / select-all and keyboard selection (Shift+arrows, Ctrl+A) are unaffected
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
- [ ] **The edit is not reverted by opening the menu** — select text, right-click, click Cut: the text is actually cut (fixed 2026-07-30; the menu is a `Qt.Popup`, so it read as "focus left the field" and the click-outside handler reverted the edit first, leaving the selection visibly highlighted but the field restored)
- [ ] Same check after having typed a change: select part of an edited-but-unsaved field, right-click, Cut — the edit is preserved and the cut applies to it
- [ ] Escape and click-elsewhere still revert the edit as before (the fix must not have disabled click-outside revert generally)

### Tag name field context menu (Tag manager)
- [ ] Right-clicking tag name field shows context menu with correct enabled state
- [ ] All four actions work correctly
- [ ] Menu dismisses on action and on click-outside
- [ ] Cut via the icon actually cuts here too — same `Qt.Popup` revert bug, fixed in this panel as well (2026-07-30)
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

#### Row-boundary alignment (viewport / wheel / keyboard-nav — added 2026-08-12)
- [ ] With enough sessions to overflow: scroll to the very bottom (any method) — the last row is
      fully visible, never clipped/partial
- [ ] Mouse wheel over the row list: each notch moves by exactly one row height — never leaves a
      row partially visible at either edge, in either scroll direction
- [ ] Arrow-key navigation (see Keyboard navigation below) through the full list, both directions:
      no row is ever partially clipped at the top or bottom edge while navigating
- [ ] With the tab bar (Stats/History/Tags/Cover) visible: switch to Stats, Tags, and Cover tabs —
      their content still looks correctly positioned (the 3px push affects all four tabs' content
      start position equally, not just History)

#### Keyboard navigation (added 2026-08-12)
- [ ] With History tab focused/open: Down arrow selects the first row (shows its hover-X);
      repeated Down moves selection one row at a time, no wrap past the last row
- [ ] Up arrow moves selection back up one row at a time, no wrap past the first row
- [ ] Keyboard-selecting a row scrolls it fully into view if it was partially/fully off-screen
- [ ] Delete/X key with a row keyboard-selected: arms that row's delete confirmation, same as
      clicking its X
- [ ] Space/Enter with a confirmation armed (via keyboard or mouse): confirms the delete
- [ ] Left/Right arrow still cycles Stats → History → Tags → Cover (wrapping both ways) while the
      History tab is active

#### Mouse + keyboard interaction (added 2026-08-12)
- [ ] Keyboard-select a row (Down arrow), then move the mouse onto a DIFFERENT row: the
      keyboard-selected row's X disappears, only the mouse-hovered row shows an X — never both
      at once
- [ ] Hover a row with the mouse and hold it there (don't move), then press Down/Up arrow: the
      mouse-hovered row's X disappears once keyboard selection moves to a different row, even
      though the cursor never physically left it — never two X's showing simultaneously
- [ ] Arm a delete confirmation via mouse click (the X icon), THEN press Up/Down: selection moves
      correctly with the usual hover-X on the new row (not the armed row's own confirming state,
      which is untouched) — do NOT see the list scroll natively with no X and no row-boundary
      alignment (this was a focus-strand regression — see below)
- [ ] Arm a delete confirmation via mouse click, THEN press Left/Right: tabs still switch
      correctly (Stats/History/Tags/Cover) — do NOT see Left/Right stop responding
- [ ] After the above: close and reopen Book Detail (or switch tabs and back) — keyboard
      navigation and tab-cycling both still work normally, confirming no lingering focus loss

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
- [ ] With master On (any sub-toggle): type a real search, click a tag/author/narrator/year filter (field now shows the clicked value), quit the app WITHOUT closing the library panel first, relaunch: field shows the ORIGINAL TYPED text on restart, not the clicked filter's value (fixed 2026-07-18 — see NOTES.md)
- [ ] Same as above but with nothing typed first (only a click-filter applied before exit-with-panel-open): field is empty on restart, not the clicked filter's value

## Excluded Books (Settings → Library)

- [ ] Section invisible (zero space) when no books are excluded
- [ ] Trash a book (book detail panel): list appears under "Excluded books" on next Settings open, count shows "1 book excluded" (singular)
- [ ] Trash a second book: count shows "2 books excluded" (plural)
- [ ] List sits flush BELOW the "Excluded books" row, as the topmost element — does not float above it or leave a gap
- [ ] Very first Settings → Library open in a fresh app session: list is visible immediately (not just on a second open)
- [ ] Switching to another settings tab (e.g. Themes) and back to Library: list still renders in the right place, not at a stale/garbage position
- [ ] 1–3 excluded books: collapsed box is always exactly 3 rows tall (empty space below the list for 1 or 2 books — box does NOT shrink to fit)
- [ ] 4+ excluded books: arrow appears, live/clickable styling (not dimmed)
- [ ] 1–3 excluded books: arrow appears dimmed and inert — clicking it does nothing (no expand, no glyph change)
- [ ] Click the arrow with 4+ books: list expands to exactly 7 rows (not fewer, even if there are only 4–6 excluded books — empty space below the last row is fine)
- [ ] Arrow glyph is ▲ when collapsed, ▼ when expanded (matches ChapterList's direction-of-next-click convention)
- [ ] Arrow visually moves UP with the box when expanded (sits flush on the list's current top edge, collapsed or expanded) — does not get left behind at the collapsed position
- [ ] Expanding covers whatever settings rows are above it (Chapter source, Naming pattern, etc.) rather than pushing them or leaving a gap — same as ChapterList overlaying content below it
- [ ] Click outside the list while expanded: collapses back to 3 rows (does not hide the list entirely)
- [ ] Switch tabs while expanded: list becomes hidden/clipped immediately (no fade, no flash on the new tab)
- [ ] Restore a book via its row's hover-reveal eye icon: row slides out, book reappears in the library/grid
- [ ] Restore the 4th-from-last book (count goes 4→3): list immediately collapses to 3 rows and the arrow drops to dimmed/inert — does not stay stuck expanded at 7 rows
- [ ] Restore books down to exactly 1 left (e.g. 2→1): box stays at the fixed 3-row collapsed height — does not shrink to 1 row
- [ ] Restore the last remaining excluded book (1→0): list and the "Excluded books" header/count line both disappear immediately — no leftover empty box or stale count text
- [ ] "N books excluded" count is correct immediately after each restore — no off-by-one (this was a real bug: the count used to read 1 too high right after clicking the eye, since the restored row isn't actually removed from the list widget until its slide-out animation finishes a moment later)
- [ ] Restore a book that is also flagged `is_missing` (folder deleted from disk): does NOT appear in this list at all, with no eye icon, regardless of `is_excluded` state
- [ ] Arrow sits flush against the row's RIGHT edge; "N books excluded" label is to its left with a small gap (not overlapping)
- [ ] With Settings → Library ALREADY open: exclude a book via the detail panel's trash button, then navigate back to Settings → Library — the list appears immediately (not just the count text), no close/reopen of the settings panel needed
- [ ] With Settings → Library ALREADY open and 4+ books just excluded that way: arrow appears in its correct (live) state, list is visible at the correct collapsed size — not invisible with a "stuck" clickable arrow
- [ ] Same scenario, click the arrow: list expands UPWARD (not downward, not off-screen), arrow moves UP with it (not down) — this was a real regression where both directions inverted when the list was first shown via a same-tab refresh rather than a fresh panel open
- [ ] Exclude a book whose file is still present, then move/delete its folder, then force-rescan: the book is flagged `is_missing` and disappears from this list (does not stay stuck showing `is_excluded=1` forever with a live, misleading eye icon)
- [ ] Exclude a book whose file is still present, move/delete its folder, then try to PLAY the now-missing book (instead of rescanning): same result — the popup updates and the book disappears from the list without needing a manual refresh
- [ ] A book that is ONLY `is_missing` (not excluded, not location-deleted): book detail panel shows ONLY the gravestone icon, NOT the ghost icon too
- [ ] A book that is ONLY `is_excluded` (file still present): book detail panel shows ONLY the ghost icon, NOT the gravestone icon
- [ ] A book that is BOTH `is_excluded` AND `is_missing`/`is_deleted`: book detail panel shows BOTH icons together (this is correct, not a bug)

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