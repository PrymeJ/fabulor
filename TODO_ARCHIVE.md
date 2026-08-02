# TODO Archive

Closed, fixed, verified, and superseded entries moved out of [TODO.md](TODO.md) to keep the active
list scannable. Kept, not deleted, per the project's normal practice of not throwing away detail
that isn't fully duplicated in NOTES.md/SESSION.md/a commit message. Order is the same relative
order these entries had in TODO.md before the split (2026-07-30).

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
