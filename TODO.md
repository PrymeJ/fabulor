# TODO

Deferred work — short, dated, status-tracked entries. Not for root-cause writeups (those go in
NOTES.md) or session logs (SESSION.md). When an entry is started, move it under "In Progress" with
the date; when done, delete it (the commit/SESSION.md entry is the permanent record).

## Pending

- **[2026-07-21] Chapter list: clicking a chapter sometimes makes the current-chapter highlight
  fluctuate between chapter rows and scrolls the list to the bottom — visual bug, not yet
  investigated.** User-reported, intermittent ("sometimes"), not yet reproduced under
  instrumentation. Not root-caused — no hypothesis yet on mechanism (candidate areas to check when
  picked up: `chapter_list.py`'s selection/scroll handling on click, and whether this interacts
  with `_on_time_pos_change`'s chapter-walk-driven `chapter_changed` emits racing the click's own
  selection, given how many other chapter-UI bugs in this codebase have come from exactly that kind
  of race — see the CLAUDE.md chapter-navigation rules — but this is a guess, not confirmed).
  Needs live instrumentation added first to catch an occurrence with real state, before any fix is
  attempted — do not fix blind. Not started.
- **[2026-07-21] "Cover art based theme" should trigger a live PREVIEW on hover even when its mode
  is Off.** Right now `_on_cover_pool_btn_hovered` (`theme_manager.py`) early-returns if
  `self._cover_theme` is None, and with cover-art mode Off there's effectively no preview — hovering
  the "Cover art based theme" entry does nothing. Desired: hovering it should preview the cover-
  derived theme regardless of the Off/With pool/Exclusive selection, so the user can see what it
  would look like before committing. Not started — needs to confirm a cover theme is buildable for
  the current book (there may be no cover / no `_cover_theme` computed while mode is Off) before it
  can preview anything.
- **[2026-07-21] Transport-bar blur scope: cover art area needs the same clip/blur treatment as the
  bottom (transport) part — deferred, blocked on the placeholder-text rehaul.** Currently
  `TransportBarBlurOverlay` only tracks the mini transport bar (chapter label, chapter progress,
  time labels, transport buttons, speed button, vol_stack) — the cover art area is out of scope
  entirely. Per the user, the cover art region should eventually get the same bounding-rect/clip
  treatment `_apply_transport_bar_blur` already gives the bottom part, but this is intentionally
  pending until the cover-art placeholder text is reworked first (no-cover-book state) — doing the
  blur scoping before that rehaul would mean redoing the bounding-rect/geometry work once the
  placeholder layout changes underneath it. Not started.
- **[2026-07-21] `SUSPECT_MASKED_STASH` diagnostic marker has a false-positive gap — deal with
  later, not a functional bug.** Confirmed via a real 15-minute live session (03:00–03:15) after
  the guard-masking + hover-confinement fixes landed: the marker fired `True` 15 times, but every
  one was `hover=True` (an ordinary, correct hover no-op, not the actual bug — which is `hover=False`
  + the marker). The marker doesn't distinguish "guard blocked a real pending apply" from "guard
  correctly no-op'd a redundant hover re-entry," because only non-hover applies update the
  `_theme_ever_applied` comparison value it checks against. Diagnostic-precision issue only — does
  not affect app behavior, both real fixes are confirmed working via the same session's log. Full
  detail: NOTES.md, "Guard-masking bug ... and hover-preview confinement" entry, 2026-07-21.
- **[2026-07-21] Theme-bleed: VERIFIED FIXED with blur ON, not yet soak-tested.** Two of (at
  least) three independent causes were closed 2026-07-20 (state-read bypass in
  `_set_bg_suppressed`, hover-unaware blur grab in `refresh_dirty`). User has now explicitly tested
  and confirmed this live with blur ON (not the earlier blur-OFF-only tests that couldn't have
  caught it) — no bleed observed. Not a soak test yet (short/targeted session, not sustained
  multi-minute+ repeated cycling), so keep as pending rather than closed until a longer soak
  confirms it holds. Full root-cause detail, the audit trail, and the fix mechanism for both
  passes: NOTES.md, "Theme-bleed Pass 1 + Pass 2" entry, 2026-07-20. Session narrative: SESSION.md,
  Session 3, 2026-07-20. Separately, still open: general responsiveness was reported slow after
  this fix landed — not soak-related, not yet triaged. Candidate follow-up (not started): the new
  responsiveness complaint may be the hover gate's decline path adding overhead elsewhere, or may
  be unrelated — needs live profiling, not assumed.
- **[2026-07-20] `refresh_dirty`'s cooldown/hover gates don't re-arm a declined tick — candidate
  mechanism for the still-open frozen-overlay bug below, NOT investigated or touched this
  session.** Found while implementing the hover gate above. Detail: NOTES.md, same entry as above.
- **[2026-07-20] NEW: blur overlay's refresh timer stops firing permanently after a normal
  `show_for_panel` call — confirmed via one accidental occurrence, root cause not yet found.**
  Overlay freezes on stale content indefinitely (confirmed via screenshot: grabbed transport-bar
  buttons showing an old theme's blue while the live, unblurred chrome around them had moved on to
  pink/magenta) while the app keeps running and the real theme keeps changing. Log shows
  `show_for_panel DONE` succeeding normally, then zero `transport_bar_blur` log lines of any kind for
  over a minute. Distinct third bug from the punch-through flash and the theme-bleed item below — found
  by accident, not reliably reproducible. See NOTES.md for full detail; investigation in progress
  (static analysis + permanent timer-lifecycle logging, per the user's explicit direction not to rely
  on live repro as the primary method).
- **[2026-07-21] "Hovered theme bleeds into the whole live main window" — VERIFIED FIXED with blur
  ON, not yet soak-tested.** The `theme_manager.py`, `complete_main_fade()` fix (previously
  uncommitted/unverified — every earlier "no issues" report had been run with blur OFF, which was
  already independently known to mask this bug regardless of the fix) has now been explicitly
  tested and confirmed live by the user WITH blur ON. Since the bug's own reproduction was
  inconsistent (sometimes immediate, sometimes ~5 minutes), a single positive session is real
  evidence but not conclusive — an actual soak test (blur on, repeated hover+panel-open cycles,
  several 5+ minute stretches) is still the bar for calling this fully closed. Keep as pending until
  that soak test happens. This was a real, separate bug from the punch-through-flash item below —
  the two got conflated in earlier drafts of this TODO/NOTES.
- **[2026-07-21] Spurious-`enterEvent` heartbeat — BOTH triggers now identified and fixed; the
  underlying punch-through-FLASH collision is a separate, still-open item (below).** The heartbeat
  (spurious repeated enter/leave on a stationary cursor over a `ThemeItem`, each spurious enter
  emitting `hovered()` → unwanted preview) had two triggers: (1) the `setStyleSheet`-cascade in
  `_apply_stylesheets` (guarded by `_spurious_enter_guard_until` since 2026-07-20, kept); (2) the
  transport-bar blur grab (`_grab_and_blur`) hiding/re-showing the settings panel every tick —
  identified 2026-07-21 via `[ENTEREVENT-TRACE]` log forensics and fixed (`1a00abd`, see NOTES.md +
  SESSION.md Session 8). The fix records `_last_leave_was_synthetic = not isVisible()` in
  `ThemeItem.leaveEvent` and drops the enter when that flag + `pos_matches` hold. Verified live: 10
  synthetic suppressed, 0 surviving heartbeat, 33 genuine hovers unaffected. `[ENTEREVENT-TRACE]`/
  `vis=` logging left in for soak-verification (remove after a clean soak). **What remains OPEN,
  separately:** the punch-through-FLASH itself — the underlying collision of a real, event-driven
  `main_window.grab()` landing right after a restyle against Qt's post-restyle repaint/repolish
  backlog (measured live, outliers up to 357ms). That was never fixed, only reduced in frequency
  (event-driven rework) and de-amplified (the heartbeat that used to drive extra spurious restyles
  is now cut). **Whether the visible flash is the live main window or the overlay's grabbed pixmap
  was never confirmed** — resume there if it resurfaces: (1) confirm what's flashing (live vs.
  grabbed pixmap); (2) the heartbeat is no longer a contributing amplifier, so any remaining flash
  is the raw grab-vs-restyle timing collision alone.
- **[2026-07-18] `closeEvent` can save a near-zero progress if SIGTERM/close lands between
  `load_book` and the VT restore-seek landing — found via a 400-cycle cold-launch stress test,
  narrow and not confirmed to matter in real usage.** Test: 5 VT + 5 M4B books, 40 cold launches
  each (`entr -r` restart via touching `book_quotes.py`, ~2s between touches), cover-theme ON,
  checking DB `progress` for corruption after every launch. Result: 398/400 clean; 2 anomalies, both
  isolated single-event drops that then held perfectly stable for the rest of that book's 40-launch
  batch (no repeating/systematic corruption). One (Colorless Tsukuru Tazaki, launch 24) was traced
  to a burst of `seek_async` calls ~10.75s apart milliseconds apart — stray wheel-scroll input
  landing on the progress slider during this interactive session, not an app bug. The other
  (Austerlitz, launch 2) is real: the first Austerlitz launch's `load_book` fired but
  `_restore_position` had not yet run when `entr` sent SIGTERM (~1.4s later) for the next cycle;
  `closeEvent` (`app.py:3370`) unconditionally calls `_save_current_progress()` whenever
  `current_file` is set, with no check for whether the VT restore-seek actually landed, so it saved
  the just-loaded (~0) position over the real 10420.78s. **Caveat from the user, load-bearing:**
  this test's rapid restart cadence doesn't reproduce the original bug's shape — the original issue
  was progress restoring correctly in the GUI and then *later* dropping to zero, not a load
  interrupted before restore ever ran. Real usage doesn't SIGTERM the app mid-book-load, so it's
  unclear this narrow race is worth pursuing on its own. Not triaged as a priority; revisit only if
  a similar shape shows up from real usage, not from stress-test cadence alone.
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
  `NOTES_THEMING_CURRENT_STATE.md`): panels show correctly styled on first open after a cold
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

- **[FUTURE REDESIGN, 2026-07-14] Incremental/`@Property` color animation instead of whole-theme
  stylesheet swap + overlay punch-through — explicitly SEPARATE from Findings 1/2/3 and from the
  RANK-1 fix; not investigated, not designed, out of scope for now.** Raised by Pryme while the
  cold-launch theme work was in flight. The reasoning worth preserving: the current architecture can
  only change colors by regenerating and re-applying whole stylesheets — a full-widget-tree
  `_apply_stylesheets` pass — which is precisely the ~400ms synchronous main-thread cost that is the
  measured root of Race 3, Regime B, and RANK-1 in the first place (median 318ms, pipeline median
  442ms, max 759ms; `mw.setStyleSheet(base)` alone is ~180ms because Qt re-polishes every
  descendant — see `review/Report_260714_synchronous_main_thread_work.md`). An incremental approach
  — animating individual colors via `@Property` on the widgets that need them, rather than swapping
  the whole stylesheet and masking the transition with a full-window overlay — might not need that
  pass at all, which would dissolve the cost rather than sequence around it.
  **Known prior art / why this is big, not a quick win:** NOTES.md 2026-06-19 ("Main-window theme
  fade interrupt ... full color-animation rework DEFERRED") records that this exact rework was
  **started in a prior session and abandoned as ~40–80h with high regression risk** — every
  QSS-styled widget (buttons + their `:hover`/`:pressed`/`:disabled` states, panel chrome, Themes-tab
  pool items, gradients, cover-derived colors) would need converting from QSS-driven coloring to
  custom-paint `@Property` coloring, because QSS pseudo-states have no custom-paint equivalent and
  would each be reimplemented by hand. The cheaper middle path (snap panel chrome instantly, keep
  slider tweens) was **explicitly rejected by Pryme** — instant theme snaps read as jarring/violent,
  which is the whole reason the overlay fade exists. Also relevant: `ClickSlider` ALREADY paints from
  `@Property` colors rather than QSS at paint time — it is the one widget class where this model is
  already proven in-tree (and, not coincidentally, the one whose colors can get stranded — see the
  2026-06-19 entry).
  **Status:** a real, recorded idea with a real prior estimate against it. Do NOT fold into
  Findings 1/2/3 or the RANK-1 fix — if it is ever picked up it needs its own investigate-then-plan
  cycle sized against that 40–80h prior estimate, not a mid-fix scope expansion.

- **[RANK-2, 2026-07-14] Close the P1↔P2 race precondition structurally (insurance, not a live-bug
  fix) — deferred, deliberately separate from the RANK-1 theme-apply fix.** The structural hazard:
  a Qt-queued writer (`_vt_restore_pending`, written via the `book_ready`→`_on_file_ready`
  QueuedConnection at `app.py:389`) racing an mpv-thread reader (`_on_file_loaded`'s read of it),
  exposed whenever ANY ~100ms+ synchronous main-thread op starves the Qt queue in that window. Today
  the only such op is theme-apply (fixed narrowly by RANK-1), but the pattern re-opens for the next
  heavy sync op anyone adds later (a heavier chapter populate, a sync DB migration, etc.). Feasibility
  already investigated (see `review/Report_260714_theme_apply_safety_feasibility.md`, RANK-2 section):
  - **VT path:** both `book_ready` emit sites (`ungate_play`, `_on_playlist_resolved`) run on the Qt
    main thread, so a Direct (non-queued) connection COULD run `_restore_position`/`defer_vt_restore`
    synchronously before the subsequent `_apply_pending_cover_theme`, removing the race precondition
    entirely for VT. **But** `book_ready`/`_on_file_ready` is a single shared connection (can't be
    Direct-for-VT / Queued-for-non-VT without a second signal or per-emit juggling), the VT emit is
    deliberately placed BEFORE `instance.play()` (CLAUDE.md book_ready invariant), and making restore
    synchronous there changes the timing the shipped VT fixes (`_on_vt_file_switched` gated clear,
    `_on_end_file` ERROR reset, `_logical_pos`) were verified against — so it TOUCHES the blast radius
    of the VT-fragile zone even without editing those functions.
  - **Non-VT path:** `book_ready` is emitted from the mpv thread, so the QueuedConnection is
    MANDATORY thread-marshaling — the precondition cannot be removed at all; non-VT's only protection
    is "don't run a long sync op in the window" (i.e. the RANK-1 fix).
  - **Why deferred, not done now:** it's insurance against a hypothetical future sync op, not a live
    bug (RANK-1 closes all three currently-observed victims); its cheapest shape still re-architects a
    connection in the highest-risk zone in the codebase. If ever attempted, it needs its own
    investigate-then-plan cycle and the full VT+Undo verification bar (`tools/fs_race_harness.py`,
    `tools/vt_restore_race_harness.py`, live checklist) re-run — NOT bundled with RANK-1. Captured
    here so this structural risk is dated and tracked, not left buried in a review report.

- **[2026-07-14, STILL OPEN — trigger condition likely narrowed by tonight's work, NOT re-verified,
  do not assume fixed] VT progress restore silently resets on book-switch (not cold app-launch) —
  root cause confirmed, NOT fixed.** Root cause: `_restore_position` (sets `_vt_restore_pending`)
  runs from a `Qt.QueuedConnection` slot on the Qt main thread; `_on_file_loaded` (consumes it)
  fires on mpv's own independent event thread. Nothing guarantees the former runs before the
  latter — it does at cold launch (nothing else competes for the Qt event loop) but not on
  book-switch, where a slow synchronous operation on the Qt thread can let `_on_file_loaded` win
  the race, find nothing pending, and never re-check. Confirmed live trigger at the time: cover-
  art-driven theme application (~325-400ms synchronous `_apply_stylesheets` pass) — every failing
  switch coincided with it.
  **2026-07-18 update, not a fix:** tonight's `_apply_pending_cover_theme` deferral work
  (`1025b0a`/`c281ee3`) means the expensive `apply_cover_theme`/`clear_cover_theme` synchronous
  work this bug's trigger depends on now runs LATER on a book-switch than it used to — deferred
  until both sliders finish `when_animations_done`, rather than immediately. This may narrow or
  close the window this race needs, but that is a hypothesis, not a verified fix — the rapid-switch
  progress-integrity re-check run tonight (see entry above) exercised book-switch repeatedly with
  cover-theme ON and found no data loss, which is circumstantial support but was not designed as a
  targeted re-test of THIS specific race (it didn't specifically try to catch `_on_file_loaded`
  winning against a still-pending `_restore_position`). Root cause (the QueuedConnection vs.
  mpv-thread race itself) is UNCHANGED and UNFIXED — do not close this entry on the strength of
  tonight's incidental testing. If revisited: re-run the original repro from NOTES.md's 2026-07-14
  entry specifically, with the `[BOOKSWITCH-TRACE]` instrumentation (still in place), before
  concluding either way.

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

- **[RANK-LOW, MEASURED 2026-07-14] App-start flow-animation baseline roughness (Regime A) — a
  standalone ~70ms hitch at animation start, independent of everything else.** Present on EVERY cold
  launch of EVERY book type, cover on or off, with no theme apply anywhere near the window (worst
  frame gap ~70–76ms median, never observed >108ms). A synchronous burst at animation start:
  chapter-list `populate` + repeated `_update_chapter_label_from_index setCurrentRow` calls + the
  first mpv `time_pos` samples, all landing in the animation's first ~50–90ms. Real but
  sub-perceptible-to-mild — a rough *start*, not a freeze. **Independent of P1/P2/P3 (confirmed by
  measurement — occurs on M4B and MP3, which have no `_vt_restore_pending`/`file_switched` at all)
  and independent of the RANK-1 theme-apply hazard.** This is the ONLY part of the old combined
  "flow-animation stutter" item that is a genuine standalone animation-timing bug — it is what the
  original 2026-07-13 trace-only investigation correctly found (it was right about this, blind to
  Regime B). **Verification bar for any fix touching this or near-app-start VT load timing:** re-run
  `tools/fs_race_harness.py`, `tools/vt_restore_race_harness.py`, and the VT+Undo checklist, since
  any timing change near app-start VT loading risks interacting with the `_vt_restore_pending`/
  `file_switched`-guard fixes. Full detail in NOTES.md (2026-07-14) and
  `review/Data_260714_flow_animation_stutter.md`.

  *Historical note: these two entries replace a single 2026-07-13 "first-app-launch-only VT
  flow-animation stutter" item that was traced (code-reading only) to the progress slider's own
  `QPropertyAnimation` glide and believed to be one isolated bug. The 2026-07-14 live measurement
  found it was two genuinely different bugs with different ranks — keeping them as one entry would
  recreate the "one bug wearing two names" confusion the investigation resolved. The original trace
  was right about Regime A and blind to Regime B; its "the trace found nothing, not a live-forced
  test showed nothing" caveat is what prompted the measurement that split them.*

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
- **[2026-07-09] FIX: keyboard-selection focus indicator is nearly invisible.** Across the Tab/
  Escape live-testing, Pryme reported it's "almost impossible to see where the focus is" for
  keyboard-focused controls in general (not just the Library keyboard-selection highlight from the
  earlier session — this is about standard widget focus, e.g. in Settings/Speed/Sleep panels via
  the new Tab cycling). Floated a glow-style indicator as one option, undecided. Explicitly
  deferred to a future session ("we'll try and decide tomorrow") — do not implement a specific
  fix without discussing the visual approach first.
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
- **[2026-06-27] Excluded Books popup (`ui/excluded_books.py`) corner-radius mismatch.**
  The popup's selection highlight is flat/square; `settings_folder_list`'s is rounded (`4px`).
  Should match (one or the other) since they're both "selected row in a themed list" in the same
  panel. Narrowed 2026-07-15 from a four-issue entry after audit: the `::item:selected` color
  inconsistency is moot (the popup now disables selection entirely — `NoSelection`, see
  `excluded_books.py`'s `set_theme` comment); the bg_deep/bg_dropdown background mismatch was
  closed as not worth chasing.
  **Reminder for the eventual full per-theme color pass** (see the "Remove theme inheritance from
  The Color Purple" entry below, and SESSION.md's alphabetical library-color pass): re-check the
  Excluded Books popup generally as part of that pass — both this corner-radius mismatch and
  general contrast/legibility across themes — since the popup is hidden whenever no book is
  excluded and is easy to forget about otherwise. Not theme-specific; no single theme needs
  singling out.

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
- **[2026-06-25] Pre-release cleanup pass (bundle into one commit, not piecemeal).** Narrowed
  2026-07-15 after audit — the third original sub-item (switch VT playlist-resolution temp files
  from `delete=False` to `delete=True`) is stale: that `ffmetadata`/`concat` tempfile mechanism in
  `_resolve_playlist` no longer exists, removed in `95ab53e` before this entry was even written.
  Remaining:
  - Remove the `Q`-key quote-rotation shortcut (`app.py`, testing-only — already flagged inline as
    `# TODO: remove before release — testing only`).
  - Remove stray debug `print()`/timing instrumentation left in `player.py` (`[load_book]`,
    `[VT-DESYNC]`, metadata-extraction-error, af-command-error) — the original sub-item named
    `_close_session`/`_on_file_ready`/`_on_book_selected_from_library` specifically, but session-close
    logic has since moved into `SessionRecorder.close()`, so those exact function names are gone;
    the underlying ask (strip leftover debug prints before release) still applies to what's there now.
  See NOTES.md "Cleanup Deferrals — Pre-existing, Deliberate" (~line 2108) for original context.
- **[2026-07-15] Undo doesn't return to the true origin after rapid repeat Next/Prev within
  `undo_duration` — narrowed live to Next/Prev specifically, not general undo/restore.**
  `save_seek_position(old_pos, duration_limit)` (`player.py`) only writes `_undo_pos` when it's
  unset or when more than `duration_limit`s (default 3s, `config.get_undo_duration()`) have passed
  since the last capture — a rapid second capture within that window is skipped, which by reading
  the code should leave `_undo_pos` pointing at the FIRST departure point (chapter 3), not the most
  recent one (chapter 4). Concrete repro, live-tested by the user: in chapter 3 with ~30s left,
  click Next twice in quick succession (chapter 3 → 4 → 5), then click Undo — **actually lands at
  the chapter 3/4 boundary ("beginning of chapter 4"), not back in chapter 3.** Further live
  testing (2026-07-15) narrowed this to Next/Prev specifically — every other undo/restore path
  (seeking, smart-rewind, chapter-slider clicks) correctly returns to the true origin position;
  only rapid repeated Next/Prev clicks fail to chain back past the most recent hop. Root cause NOT
  yet diagnosed — the shared `_last_undo_click_time`/skip logic described above doesn't obviously
  explain why Next/Prev's call path would behave differently from every other `save_seek_position`
  caller; needs live tracing of `_undo_pos` across both Next calls (not just code reading) and a
  diff against how the other, correctly-behaving call sites invoke `save_seek_position`, before
  attempting a fix.

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
