# TODO

Deferred work — short, dated, status-tracked entries. Not for root-cause writeups (those go in
NOTES.md) or session logs (SESSION.md). When an entry is started, move it under "In Progress" with
the date; when done, delete it (the commit/SESSION.md entry is the permanent record).

## Pending

- **[2026-07-14] VT progress restore silently resets on book-switch (not cold app-launch) — root
  cause confirmed, NOT fixed.** Distinct from anything shipped tonight (`faeaa83`/`685e433` were
  verified via 200 cold-launch cycles only; book-switch was never tested until now). Root cause:
  `_restore_position` (sets `_vt_restore_pending`) runs from a `Qt.QueuedConnection` slot on the Qt
  main thread; `_on_file_loaded` (consumes it) fires on mpv's own independent event thread. Nothing
  guarantees the former runs before the latter — it does at cold launch (nothing else competes for
  the Qt event loop) but not on book-switch, where a slow synchronous operation on the Qt thread can
  let `_on_file_loaded` win the race, find nothing pending, and never re-check. Confirmed live
  trigger: cover-art-driven theme application (~325-400ms synchronous `_apply_stylesheets` pass) —
  every failing switch coincided with it, every clean switch (plain theme, no cover-art extraction)
  succeeded. **This is the THIRD independent instance of synchronous main-thread theme
  application/extraction cost causing a real bug** (first: 2026-07-04 hover-preview fade-timing bug;
  second: tonight's own measurement of the same cost outside the Themes tab entirely; third: this
  bug, the first of the three to corrupt actual state rather than just visual timing). **Suggested
  direction, not designed:** the durable fix likely belongs at the theme-application layer (make
  `_apply_stylesheets`/cover-art extraction async, or defer it away from book-switch's event
  sequencing) rather than a fourth patch onto `_vt_restore_pending`/`_on_file_loaded` — the deferred-
  restore mechanism itself is sound and isn't this bug's actual fault. Full mechanism, the two
  contrasting live log traces, and the async-theme-application direction are in NOTES.md, "VT
  progress restore silently resets on BOOK-SWITCH..." (2026-07-14). **Diagnostic instrumentation
  (`[BOOKSWITCH-TRACE]` debug logging across `player.py`/`app.py`/`ui/panels.py`) was deliberately
  left in place, uncommitted-but-present, for whoever picks this up** — use it to confirm a fix
  actually closes the race rather than trusting a few clean manual tries, same discipline as every
  other fix tonight.

- **[2026-07-13] First-app-launch-only VT flow-animation stutter on load.** User-reported,
  independent of the VT-restore-on-load / general `file_switched`-race investigation that surfaced
  it. Confirmed present on `main` (pre-existing, not introduced by that session's fixes — the user
  checked `main` directly). Traced (code-reading only, NOT a forced live A/B against the actual
  stutter's timing) to the progress slider's own `QPropertyAnimation` glide — a self-contained
  animation that doesn't read from or write to the deferred-restore seek or `_on_file_loaded`, so
  the trace found no interaction mechanism with that session's fixes. That is "the trace found
  nothing," not "a live-forced test showed nothing" — full caveat and the specific
  `_on_time_pos_change` VT-chapter-walk timing-shift contract to check first are in NOTES.md
  ("`_on_file_loaded`'s general... race" entry, the "Also checked... first-app-launch-only VT
  flow-animation stutter" paragraph). **Before considering this fixed, re-run
  `tools/fs_race_harness.py`, `tools/vt_restore_race_harness.py`, and the VT+Undo checklist, since
  any timing change near app-start VT loading risks interacting with the `_vt_restore_pending`/
  `file_switched`-guard fixes shipped this session** — so a future same-day fix attempt inherits
  that verification bar automatically instead of being evaluated as a standalone animation bug.

- **[2026-07-14] VT missing-file handling — consolidated design (supersedes three earlier,
  narrower entries from the same night: the cross-file chapter-cycling bug, the
  discovery-timing/banner-permanence gaps, and the original "richer design deferred" sketch — all
  folded into one plan since they turned out to be facets of the same design, not separate
  problems).** Current shipped behavior (same-file missing-file case only): unload + `is_missing`,
  reusing the existing M4B runtime path. Below is the actual intended design, decided in
  conversation but NOT implemented — needs its own session, deliberately kept off this branch to
  avoid sidetracking from the drift-adjacent fixes it exists for.

  **1. Load-time check (closes the M4B/VT discovery-timing asymmetry — mostly decided, one open
  question).** M4B is a single file: if it's missing, the book can't even load, so the failure is
  exposed immediately and unconditionally. VT is a folder of files: today, the book loads fine
  even if a file is already gone, because nothing checks at load time — a missing file is only
  discovered *reactively*, contingent on some later action (Play, Next, a seek/skip) happening to
  target it. This means a VT book can sit in the library for an arbitrary stretch — across
  sessions, across restarts — reporting as a normal, fully playable book while a file is silently
  gone. Decided direction: at load time, compare the file count the book was built/scanned with
  (`book_files` row count in the DB) against the count of matching audio files actually present in
  the folder (not a full per-file `os.path.exists` sweep — a single directory listing/glob + count
  comparison, cheap regardless of file count, unlike hundreds of individual stat calls). **Open
  question, not yet resolved:** is a listdir+count comparison actually fast enough to add zero
  perceptible load-time latency, including on slow/network-mounted storage or very large VT books?
  Needs to be measured against a real large book (Zhivago, 260 files, is the natural test case)
  before trusting it — this is the one piece of the design that's still genuinely open; everything
  else below is decided pending implementation.

  **2. Post-load discovery (file goes missing after the book already loaded/played once) — the
  bug this actually started from.** `seek_async`'s cross-file `else` branch (`player.py`
  ~820-833, `self.instance.play(target_file['file_path'])`) has no existence check and commits
  `_current_vt_index`/`_file_offset` to the target BEFORE confirming it loaded. When the file is
  missing, mpv's ERROR end-file fires, and `_on_end_file`'s ERROR-path reset (already shipped)
  clears seek state but never touches `_current_vt_index`/`_file_offset` — leaving them pointing
  at a file that was never actually loaded. Live-reproduced result: banner shows mpv's own generic
  error text (not "File missing."); Play does nothing; Next/Prev cycle a fixed subset of the
  book's chapters forever, permanently unable to reach the missing file or anything past it; no
  freeze, no crash. Full mechanism, traced step-by-step, in NOTES.md "VT cross-file missing-file
  jump corrupts `_current_vt_index`/`_file_offset` — DIAGNOSED, NOT FIXED" (2026-07-14) — that
  writeup also settles that no rollback/snapshot mechanism is needed: a pre-check
  (`os.path.exists`, same shape as the already-shipped same-file fix) before committing any state
  resolves the "file doesn't exist" case cleanly, since nothing is ever committed to roll back. A
  file that exists but is corrupt/unreadable (passes `os.path.exists`, still fails at
  `instance.play()`) is the one remaining case needing `_on_end_file`'s ERROR path to recognize a
  VT cross-file jump was in flight and route it into the same handling as (3) below, rather than
  leaving `_current_vt_index`/`_file_offset` stranded. Loose thread, not yet reconciled: a second,
  earlier live test (moved a different file, skipped over it, played the first file successfully,
  then some later navigation triggered an unload the user couldn't precisely reconstruct) is very
  likely this exact bug — but was never deliberately re-reproduced against this now-understood
  mechanism, so treat it as likely-explained, not confirmed, until someone runs that exact sequence
  again on purpose.

  **3. What happens on discovery — decided, and deliberately the SMALL version of this design.**
  Explicitly rejected: blocking playback/UI until the user chooses an action. That was floated and
  immediately ruled out — it would mean disabling the overall progress slider, the chapter slider,
  every transport button, and the chapter list, which is a large, risky surface for what looks
  like a small edge case, and isn't worth the blast radius. **Decided instead: unload the book
  immediately** (reusing the exact same `_mark_book_missing` → `_on_book_removed` path already
  shipped tonight — nothing new needed here), **and show a sticky banner with two actions: Dismiss
  (= exclude — closing the banner without choosing Rescan is equivalent to accepting the
  exclusion) and Rescan.** Banner must not auto-hide, needs a real close button, and — restart
  behavior carried over from the earlier draft of this entry — should never reappear at app start
  just because the book is already excluded; the book should simply already be excluded (via the
  self-healing `is_missing` flag) and the app comes up in its normal state, silently. **Rescan
  means: re-scan just that book's folder** (not a full naming-pattern-style rebuild, not
  timeline-renumbering) — missing files stay missing, but the rest of the book plays normally
  around the gap; this reuses the scanner's existing per-folder rescan machinery rather than
  building something new. **Cover-art flash concern, already raised and already answered:** the
  user doesn't want the excluded/reloaded book's cover art visibly popping in the main UI while
  this resolves — same reasoning as why the existing library-panel slide already hides book-switch
  transitions from view. The intended fix (matching an existing app pattern, not a new one) is to
  route the Rescan-and-reload through the library panel slide, the same way a normal book switch
  already avoids showing intermediate cover-art states in the open.

  **Net effect of this design vs. today's shipped behavior:** (1) closes the "sits broken
  indefinitely" discovery gap for the common case (missing before the book is ever loaded); (2)
  fixes the specific cycling/stuck-book corruption for the case a file goes missing after load;
  (3) gives the user a real choice (exclude vs. rescan-and-keep-playing-around-the-gap) instead of
  today's unconditional silent exclusion, without taking on the blocked-UI design that was
  considered and rejected as disproportionate risk for the size of the problem.

- **[2026-07-13] Chapter-elapsed label reads ~1s short for up to `_CHAPTER_WALK_TOLERANCE` after
  crossing a chapter boundary (chapter-relative display only; absolute position is exact).**
  Surfaced (NOT caused) by the `_logical_pos` seek-drift fix — with absolute position now exact,
  this pre-existing chapter-display artifact became cleanly visible instead of being drowned in the
  old compounding drift (per the user: "it was worse before, drifting all around, impossible to
  tell them apart"). Mechanism: `_sync_chapter_ui` (`app.py`, ~line 1987) resolves the current
  chapter with the tolerance-padded walk `chap.time <= pos + _CHAPTER_WALK_TOLERANCE` (0.5s), then
  computes `c_elapsed = max(0, pos - chap_start)`. When a skip/seek lands within ~0.5s BEFORE a
  boundary, the walk already resolves to the NEXT chapter (tolerance), so `c_elapsed` clamps toward
  0 while the true position is still just short of the boundary — a chapter-relative offset up to
  ~1s (the chapter-remaining label uses `end - pos` with no tolerance, so the two can disagree at
  the seam). **Confirmed observationally NOT the drift bug:** absolute total-elapsed / total-
  remaining / chapter-remaining all read reliably ("10s is 10s, 30s is 30s"); the step size is
  steady (5s skips land 5s apart), it only shifts ~1s at a boundary crossing and stays consistent
  within the new chapter. Also: this touches `_CHAPTER_WALK_TOLERANCE` and the chapter-walk block,
  both of which the drift-fix plan explicitly did NOT touch (heavily-scarred epsilon zone). **Its
  own investigate-first cycle** — the tolerance exists to stop paused Next/Prev sticking (see the
  constant's own comment in `player.py`), so narrowing/removing it for the display walk risks
  reintroducing that; a display-only fix (e.g. resolve the chapter-elapsed label's chapter without
  the tolerance, or clamp `c_elapsed` differently at the seam) is the likely direction but needs
  its own repro + verification against the stuck-Next/Prev symptom. Not blocking the drift fix.

- **[2026-07-12] Chapter-slider load-time retrace: the flow-animation target and the actual
  restore seek disagree by `_CHAPTER_BOUNDARY_EPSILON` (0.35s).** Found while investigating the
  compounding seek-drift bug (branch `fix/seek-drift-logical-position`, not yet merged) — this
  started as a hypothesis (originally called "Finding 5" on that branch) that the retrace was the
  same `_logical_pos`-fixable raw-`time_pos` residual as the drift bug, but that hypothesis was
  **disproven by live log data, not assumption**: every captured book-load restore-seek settles
  with zero residual (`_is_embedded_m4b` isn't set yet when `_restore_position`'s seek runs, so the
  paused-undershoot compensation never applies to it — separate quirk, not this bug). The REAL
  cause, traced after that disproof: `_on_file_loaded_populate_chapters` (`app.py:1574`,
  `_on_file_loaded_populate_chapters`) computes the CHAPTER SLIDER's flow-animation target with
  `_CHAPTER_BOUNDARY_EPSILON` (+0.35s) baked in unconditionally for every non-VT book
  (`seek_offset = 0.0 if VT else _CHAPTER_BOUNDARY_EPSILON`), while `_restore_position`'s actual
  seek (`app.py:1665`, `seek_async(book_data.progress)`) deliberately omits any offset — per its
  own comment, restore is not chapter navigation and has no boundary to clear. **The bug is that
  these two independently-computed values disagree, not that either is individually wrong for its
  own purpose** — the animation target assumes a chapter-navigation-style landing offset that the
  real seek was never going to produce. On a short chapter (5-25s, confirmed live) the mismatch is
  a large, highly visible fraction of the slider's width: the slider animates to
  `progress + 0.35`, then visibly retraces back to the true `progress` once the 200ms timer starts
  reading the real (unoffset) position. **This is a separate, third bug from the compounding-drift
  fix on that branch and is NOT fixed by `_logical_pos`** — neither of the two mismatched values
  reads `player.time_pos`, so nothing about the drift-fix branch's `time_pos`-getter change touches
  this at all. If revisited: `_on_file_loaded_populate_chapters` should not apply
  `_CHAPTER_BOUNDARY_EPSILON` when computing the load/restore animation target, mirroring
  `_restore_position`'s own no-epsilon reasoning. Full trace (Finding 5, corrected, and Finding 5b)
  in `SEEK_DRIFT_MEASUREMENTS.md` on the `fix/seek-drift-logical-position` branch — branch-local,
  re-derive from `app.py:1574` vs `app.py:1665` if that branch is ever discarded before merge.

- **[2026-07-12] `_PAUSED_SEEK_UNDERSHOOT_COMP` (0.37s) is applied unconditionally to every paused
  embedded-M4B seek, not gated on chapter-boundary proximity. Still UNFIXED — a fix attempt was
  made and reverted 2026-07-14; read that writeup FIRST, it is not this entry's original framing.**
  Found while investigating the compounding seek-drift bug (branch `fix/seek-drift-logical-position`,
  not yet merged). The constant's ORIGINAL purpose (CLAUDE.md, Session 3, 2026-06-13) was
  chapter-boundary landing precision — Prev/Next skipping a chapter's first word, or paused
  Prev/Next re-resolving the chapter just left. But the actual gate in `seek_async`
  (`if self._is_embedded_m4b and self._cached_pause:`) checks only file format and pause state — no
  boundary-proximity check at all. It fires on every paused seek, including genuinely mid-chapter
  ones (`seek_within_chapter` via a chapter-slider click, `_restore_position` on book-load) that
  have nothing to do with chapter navigation. Real but NOT compounding/urgent — a single bounded
  per-seek error, not a progressive drift.

  **2026-07-14 attempt — implemented, unit-tested, found structurally wrong, fully reverted (no
  code merged to `main`).** A "gate on whether the compensated command crosses a `_chapter_list`
  boundary" design was built, then failed its own test for ordinary chapter navigation, then was
  traced to a category error, not a tuning problem: the gate checked whether the artificially
  inflated mpv COMMAND crosses a boundary, when the whole point of the compensation is that the
  command and mpv's real landing are different numbers by design (the command is inflated
  specifically because mpv undershoots it back down). A bare position number can't recover whether
  a given seek's crossing was INTENDED (chapter nav, labeled skips — every "must land exactly"
  caller) or accidental (only freeform slider drag/click has no stated numeric contract, and is
  the one "approximate is acceptable" case) — that information exists at the call site and is
  discarded before it reaches `seek_async` today. **Full mechanism, the two-category model, and the
  corrected direction for a next attempt (destination seeks should pass an explicit intent signal
  to `seek_async`, not have it inferred from arithmetic) are written up in NOTES.md,
  "`_PAUSED_SEEK_UNDERSHOOT_COMP` boundary-crossing gate — IMPLEMENTED, TESTED, FOUND STRUCTURALLY
  WRONG, REVERTED" (2026-07-14) — read that before attempting this again; do not restart from this
  entry's original 07-12 framing or from the abandoned plan file
  (`.claude/plans/come-to-think-of-silly-sun.md`, which reflects the now-known-wrong design and is
  NOT a blueprint).** Also separately confirmed and worth carrying forward: the visual "sliver,
  retraces" drift on short chapters is a DISPLAY/ANIMATION-timing problem distinct from landing
  precision — even a perfect seek-precision fix would not by itself resolve it. `seek_async` remains
  exactly the heavily-scarred, repeatedly-reverted function the "Seek/position tracking — VT+Undo
  is the known-fragile zone" CLAUDE.md rule is about; any future attempt needs its own
  investigate-then-plan cycle, live-verified against the exact stuck-Next/Prev bug this constant
  was built to fix, same as before.

- **[2026-07-12] DEFERRED (not planned for the current shipping push): Stats Day/Week/Month
  sub-navigation and Tags panel keyboard nav.** Explicitly scoped OUT while implementing Book
  Detail's Left/Right tab-switching + per-tab actions (History row nav, Cover thumbnail nav) the
  same session — those turned out to be low-risk once designed, because they fit within a panel
  that's ALREADY the sole real-Qt-focus owner (`PanelManager._claim_panel_focus`), so a new
  `keyPressEvent` override on the panel itself was enough (same shape as `ChapterList`/
  `StatsPanel`'s existing Left/Right). Stats sub-nav and Tags panel nav are a materially
  different, LARGER scope: they'd require inventing a "focus-zone" model — a way to enter/exit
  sub-navigation inside an already-focused panel (e.g. "arrow into the Day/Week/Month `‹`/`›`
  controls" as a distinct mode from whatever else that panel's keys might mean), plus a new
  visual focus indicator for controls that have never needed one (Stats' `‹`/`›` nav buttons have
  no existing hover-equivalent to reuse the way History-row keyboard-selection reused mouse
  hover, or Cover-tab nav reused the existing preview pane). Every binding shipped in this and the
  prior two sessions fit the simpler "add shortcuts to an already-focused panel" shape; these two
  don't. Sleep/Playback/Settings are considered adequately served by their existing
  `panel_tab_widgets` Tab-cycling and are NOT being extended further either (no focus-zone gap
  there — Tab-cycle already reaches every control).
- **[2026-07-11] FIX (blocked on upcoming tags-gutter layout work): History tab's `_history_scroll`
  has no row-height viewport quantization, unlike every other scrollable list in the app.**
  `book_detail_panel.py`'s `_history_scroll` (`QScrollArea`) is added via `outer.addWidget(...,
  stretch=1)` — its viewport height is whatever's left over in the fixed-size Book Detail Panel,
  with no relationship to `_HistoryRow.ROW_H` (27px). `ChapterList`, `ExcludedBooksPopup`, and
  `library.py`'s grid views all quantize their visible area to an exact multiple of their row
  height so scrolling always lands on a clean row boundary; History tab never got this treatment,
  and live testing with a long injected session list showed rows appearing to "shift" on scroll as
  a result. A first attempt (fixed `_HISTORY_VISIBLE_ROWS` constant, `ChapterList`-style
  `showEvent`/`_h_overhead` measurement) was tried and reverted live — didn't work, and pushed the
  "Delete listening history" button out of its clamped bottom position. Not diagnosed further.
  Explicitly deferred: the user has separate, upcoming layout work adding a tags gutter above the
  History tab, which will itself change this tab's available vertical space — re-tuning viewport
  quantization now would likely need redoing once that lands. Do this AFTER the tags-gutter work.
  See NOTES.md "History tab delete-session animation" for the full writeup, including the reverted
  attempt's exact shape (don't repeat it blind).
- **[2026-07-11] TUNE (blocked on the above): History tab delete-session collapse animation still
  "pauses near the end," per the user — bearable, not fixed.** Two other bugs in the same code path
  were fixed this session (collapse stall from a `minimumHeight` floor, `813f7d9`; post-delete
  color-flash from an unnecessary full row rebuild, `86b6cc9`), but a residual smoothness issue
  remains even for a plain 2-row single delete (rules out an overlapping-animations theory — this is
  per-frame cost during a single 150ms animation). Per the user, don't resume tuning this until the
  viewport-quantization item above is settled — no point polishing an animation inside a viewport
  that doesn't have stable row boundaries yet.
- **[2026-07-10] DESIGN + IMPLEMENT: traveling focus marker must be keyboard-only — mouse must not
  activate it, and mouse should hide an already-active marker.** Lives on the not-yet-merged
  `feature/traveling-focus-marker` branch (see that branch's SESSION.md entry, "Traveling-border-
  marker focus indicator"), not on `main` yet. Currently (`ui/focus_marker.py`/
  `app.py._update_focus_marker`) the marker shows for whatever widget `QApplication.focusWidget()`
  reports, via the app-wide `FocusIn`/`FocusOut` filter — this doesn't distinguish a Tab-driven
  focus change from a mouse click landing focus on a button, so a mouse click currently activates
  the marker too. Explicitly deferred: do not implement until the marker is settled and rolled out
  app-wide (today it's Settings' Look tab only). Full spec not yet decided — open questions to
  resolve before implementing: does "mouse activity" mean any mouse movement, or only a
  click/press; should moving the mouse over the currently-focused (marker-lit) widget without
  clicking hide it; does a keyboard action after a mouse click re-arm it immediately (consistent
  with how the existing four-phase lifecycle already resumes-on-Tab from any phase) or does it
  need its own re-arm condition. Whatever the answer, reuse `FocusReason`
  (`Qt.FocusReason.TabFocusReason` vs `Qt.FocusReason.MouseFocusReason`, already available on the
  `QFocusEvent` the app-wide filter receives) rather than inventing a separate mouse-tracking
  mechanism — `_update_focus_marker` doesn't currently branch on it, so this is a targeted
  narrowing of that existing check, not a rebuild.
- **[2026-07-10] DECIDE: PageUp/PageDown jump distance in the library list.** `52b7abb` fixed
  PageUp/PageDown/Home/End so the viewport actually follows the selection (they were never
  broken navigation-wise, just invisible — `setAutoScroll(False)` ate the native scroll-follow).
  Left as Qt's native page-jump distance, unexamined. Native Qt typically pages by roughly one
  viewport's worth of rows, which may or may not be the right feel per view mode (five very
  different row heights: List's ~28px rows vs. Square's ~95px cells vs. 1-per-row's ~159px).
  Decide whether to override the jump distance (and if so, to what — e.g. a fixed row count, or
  something tied to `ITEM_DIMENSIONS`/`cols` like the existing wheel-scroll fix's
  `rows_per_screen * cell_h` computation) or leave native behavior alone. Not yet tested live
  across all five modes to see whether native feels right or wrong anywhere.
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
