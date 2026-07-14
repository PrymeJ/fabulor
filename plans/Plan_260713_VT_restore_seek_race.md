# Fix design: VT restore-seek race (seek issued before mpv loads the file)

## Context

The investigation completed this session (instrumented, timestamped, live-reproduced 3 times — 2
failures, 1 success, same book/position/code path) confirmed the mechanism: for VT (multi-file)
books, `Player.book_ready.emit()` fires from `_on_playlist_resolved`/`ungate_play` **before**
`self.instance.play(play_target)` is called. The queued `_on_file_ready` → `_restore_position` →
`seek_async` chain this triggers can reach mpv (`command_async('seek', ...)`) before mpv has
actually loaded the target file. mpv silently accepts and drops the command — no error, nothing to
catch. Confirmed VT-specific: non-VT's `book_ready` fires from *inside* `_on_file_loaded`, i.e.
only after mpv's load already completed, so no such window exists there. Confirmed
non-deterministic: identical book/position/code path produced one clean success and two clean
failures across three real launches, depending on the real wall-clock race between mpv's internal
file-open and the ~1-30ms Qt-queued-slot delay.

This plan designs the fix. **Nothing in this plan has been implemented — planning only**, per
explicit instruction.

## What's confirmed, and why it rules out some fix shapes

- **No error/exception path exists to catch.** `command_async('seek', ...)` returns normally
  whether or not mpv had a file loaded. Any fix relying on catching a seek failure is a non-starter
  — there is nothing to catch.
- **The race is genuinely nondeterministic**, not "usually fine." A single clean live test after a
  fix proves very little — this needs either a way to force the race window wide open for testing,
  or many repeated real launches, before it can be trusted. (Same lesson as `b6a4023`'s reverted
  heuristic: clean instrumentation/a clean pass is not sufficient evidence on this bug class.)
- **`book_ready`'s pre-`play()` emission for VT is NOT hard-required by anything downstream**,
  confirmed by git-history + NOTES.md + CLAUDE.md research this session:
  - The single commit that introduced this (`1c8d1b6`, 2026-05-15, the original VT implementation)
    and NOTES.md's own writeup of it ("Multi-file MP3 virtual timeline — RESOLVED") give one
    stated rationale: avoiding the "Round 2" quadruple-advance feedback loop, where an earlier,
    abandoned implementation connected `_on_file_ready` directly to `file_loaded`/every VT file
    switch, so restoring position on every switch triggered another switch. That bug is what
    CLAUDE.md's "must never converge" language is actually protecting against — **not** a
    requirement that `book_ready` precede `instance.play()` specifically.
  - `book_ready`'s two consumers (`_on_file_ready`, `_on_file_loaded_populate_chapters`, both
    `app.py:389-390`, both `QueuedConnection`) and `file_switched`'s one consumer
    (`_on_vt_file_switched`, `app.py:391`, `QueuedConnection`) are **completely disjoint** — no
    slot listens to both signals, so there's no cross-talk to preserve beyond the "fires once per
    book, not per file switch" invariant itself.
  - **The actual invariant worth preserving is narrower than "before `play()`":** `book_ready` must
    fire exactly once per VT book, at first-file selection — not on every VT file switch (that's
    what caused Round 2). Whether it fires a few milliseconds before or after `instance.play()` is
    incidental, not load-bearing, as long as the once-per-book property holds.
- **TODO.md's own 2026-07-13 entry (written during the drift-fix branch, before this investigation)
  already converged on the same direction independently**: "Likely fix directions for Layer 1:
  re-issue the restore-seek AFTER the file is confirmed loaded, or serialize the restore against
  the first `file_switched`, rather than issuing it while the file is still loading... Once Layer 1
  is fixed (seek actually reaches target and settles), the clobber and freeze both disappear on
  their own and no `_on_vt_file_switched` / maintenance-block guard is needed."
- **`_on_time_pos_change`'s maintenance block (`player.py:190-209`) already has an explicit,
  commented "known out-of-scope gap"** acknowledging exactly this: it does NOT guard against
  `_on_vt_file_switched` clobbering `_logical_pos` during a still-pending restore, specifically
  because fixing that at the consumer side only trades a silent clobber for a UI freeze — the seek
  never settles either way while it's dropped. **This confirms the correct fix point is the seek
  itself never landing, not the consumer that reacts to `is_seeking`/`_seek_target`.** Once the
  seek actually settles, this block's existing `not self._is_seeking` gate and the settle branch
  (`player.py:166-189`) work exactly as designed — no change needed there.

## Root cause, restated precisely

`_restore_position` (`app.py:1658-1679`, confirmed current) calls `self.player.seek_async(book_data.progress)`
(`app.py:1672`) in response to `book_ready`, which for VT books fires before `instance.play()` has
even been issued, let alone completed. `seek_async`'s VT same-file branch (`player.py:718-738`,
confirmed current — `target_idx == self._current_vt_index`, true for a restore into the book's
first file) issues `self.instance.command_async('seek', local_pos, 'absolute+exact')` directly
(`player.py:738`) with no check that mpv has an active/matching file loaded. When this races ahead
of mpv's actual load completion (confirmed instrumented: `mpv_raw_time_pos=None` and
`mpv_raw_duration=None` at the moment the command is sent, in both captured failures), mpv silently
drops the seek. Nothing re-issues it. The book then plays from ~0 while the UI (driven by
`_logical_pos`, correctly holding the restore target since the merged drift fix) shows the correct
saved position — a real display/audio desync, not a display bug.

## Proposed approach

**Defer only the mpv seek command, not `book_ready`'s emission or any of its consumers.** Add a
small, new, explicitly-named piece of state that holds a pending VT restore target across the gap
between "restore was requested" and "mpv confirms the first file is actually loaded," then issue
the seek from the point that's already confirmed (by this investigation's own instrumentation) to
run after mpv's load completes: `_on_file_loaded`'s VT branch.

1. **New field**: `Player._vt_restore_pending: float | None`, alongside the other VT state fields
   in `__init__` (`player.py`, near `_pending_local_pos` at line 124) and reset in `load_book`'s
   VT-state-reset block (`player.py`, near line 461, alongside `_pending_local_pos = None`) —
   `None` means no restore is pending. This is a **new, separate field** from `_pending_local_pos`
   (which already has an established, different meaning: the local offset for an in-flight
   cross-file seek from `seek_async`, consumed at `player.py:545-547`). Do not repurpose
   `_pending_local_pos` for this — it would conflate two distinct lifecycles (an already-in-flight
   cross-file seek vs. a not-yet-issued initial restore) in the exact fragile zone CLAUDE.md warns
   about keeping decoupled.

2. **`seek_async`'s VT same-file branch does not change its normal behavior.** The fix is scoped to
   `_restore_position`'s call path only — mid-book same-file seeks (e.g. chapter nav within the
   current file, undo, wheel-scroll) are NOT part of this race (they target a file mpv already has
   loaded and playing) and must keep using the existing direct `command_async` path unchanged. The
   new deferred path applies ONLY to the very first restore-seek issued for a freshly-selected VT
   book, distinguished by: `_restore_position` is being called for the first time since `load_book`
   reset VT state, i.e. before the first `_on_file_loaded` for this book has run.

   Concretely: `_restore_position` (`app.py:1658`), when it detects a VT book (`self.player._virtual_timeline is not None`)
   AND this is the pre-first-load window, stores the target via a new small `Player` method (e.g.
   `defer_vt_restore(pos: float)`) instead of calling `seek_async` immediately. `_on_file_loaded`'s
   VT branch (`player.py:592-594`, where `file_switched.emit()` already fires — confirmed by this
   session's instrumentation to run only after mpv's own file-loaded event, i.e. after
   `mpv_raw_time_pos`/`mpv_raw_duration` are populated) checks for a pending deferred restore and,
   if present, calls `seek_async(pending_target)` at that point instead — then clears the pending
   field. This reuses the EXACT point in the code that this investigation proved runs after mpv's
   load actually completes, with zero new signal wiring and zero change to `book_ready`,
   `file_switched`, or any of their three consumers.

   **How this avoids Round 2's convergence bug**: `_on_file_loaded`'s VT branch runs on every VT
   file switch, not just the first — so the deferred-restore check must only find a pending value
   the first time (natural, since it's cleared immediately after use, and `load_book` never sets it
   again until the next book selection). No new "is this the first file" guard is needed beyond
   the field's own None-ness — this is simpler than threading a new "first load" flag through
   `_on_file_loaded`, and it cannot mis-fire on a later natural file-advance because the field will
   already be `None` by then.

3. **`_restore_position` still needs to do everything else it currently does for a VT book
   immediately** (volume restore, DB progress read/update, speed restore) — only the actual
   `seek_async` call is deferred. Re-check `_restore_position`'s full body (`app.py:1658-1679`)
   during implementation to confirm exactly which lines move and which stay, since some of this
   (e.g. `self.player.is_seeking = True`, set immediately at `app.py:1665`-equivalent before the
   deferred call) may still need to be set immediately so the UI's existing `is_seeking`-gated
   deadzone behavior (slider freeze during the wait) continues to work correctly while the seek is
   pending — this is a real design detail to resolve carefully during implementation, not glossed
   over: setting `is_seeking = True` immediately (before the file is even loaded) with no
   `_seek_target` yet set is a new state combination that doesn't exist today and must be checked
   against every place that reads `is_seeking`/`_seek_target` together (the settle branch at
   `player.py:166`, the maintenance block gate at `player.py:210`, `_on_vt_file_switched` at
   `app.py:1432`).

## What must NOT change

- **The non-VT restore path** — already correct (confirmed: `book_ready` fires after
  `_on_file_loaded` completes for non-VT, no race window exists). Zero changes to the non-VT branch
  of `seek_async`, `_on_file_loaded`'s non-VT branch, or `_restore_position`'s non-VT behavior.
- **`book_ready`'s emission sites and timing** — `_on_playlist_resolved`/`ungate_play` keep emitting
  it exactly where and when they do today, for both VT and non-VT. Do not reorder these emit calls
  relative to `instance.play()`. Do not touch `_on_file_ready` or `_on_file_loaded_populate_chapters`
  beyond what's strictly necessary for point 3 above (and that should be minimal-to-none — they
  already tolerate `player.duration`/position being not-yet-final via their own retry logic).
- **`file_switched` and `_on_vt_file_switched`** — completely untouched, including the
  unconditional `is_seeking = False` clear. Per CLAUDE.md's explicit prior findings (this exact
  clear was tried as a guard-narrowing target twice and reverted twice), and per this plan's own
  finding that once the seek actually settles, no guard is needed here at all — this handler stays
  exactly as it is.
- **`_logical_pos`/`_seek_target`/the settle mechanism/the skip-one logic** — all merged,
  live-verified, out of scope. If the deferred-restore design turns out to need `_logical_pos` to
  be set at a different moment than today (e.g. at the deferral point rather than at the eventual
  `seek_async` call), that is a new, small, explicitly-called-out addition to propose and review —
  not a reason to touch the existing settle/skip-one internals themselves.
- **`_pending_local_pos`** — existing meaning and lifecycle (cross-file seek in flight) stays
  exactly as-is; the new field must be separate, not layered onto this one.
- **Mid-book same-file VT seeks** (chapter nav, undo, wheel-scroll within the current file) — must
  keep using the existing immediate `command_async` path. Only the very first restore-on-load seek
  is deferred.

## How this will be verified (the nondeterminism problem)

A single clean live test after the fix proves very little, since the bug itself is timing-dependent
and was seen to succeed "by luck" even before any fix (the 16:59:05 capture). Verification needs to
force the race window open, not just re-run and hope:

1. **Forced-delay test harness (temporary, testing-only, removed before shipping):** add a
   controllable artificial delay between `instance.play(play_target)` being issued and mpv's file-
   load actually being processed — the goal is to make the OLD, unfixed code path fail on every
   single run (proving the harness genuinely forces the race), then confirm the NEW, fixed code
   path succeeds on every single run under the same forced delay (proving the race window is
   actually closed, not just narrowed). Candidate mechanism: a temporary env-var-gated
   `time.sleep()` inserted right before `_restore_position`'s call site processes (or inside a test
   double for `instance.play`), OR — preferably, since this needs to exercise the real mpv IPC
   timing — a temporary instrumented delay inside `seek_async`'s entry (only when a debug flag is
   set) that holds the deferred-seek dispatch back by an artificial N ms, to confirm the mechanism
   is correct even if the real window is normally only a few ms.
2. **Repeated real launches (no artificial delay), same book/position used in this investigation**
   (Colorless Tsukuru Tazaki, and re-derive a fresh saved-position repro for a second VT book) — at
   least 10-15 consecutive close/relaunch cycles, checking the log (or, since instrumentation will
   be removed, a temporary re-add of the same `[VT-RESTORE-RACE]`-style tags scoped to just this
   verification pass) for 100% success, not "looked fine a few times."
3. **The full VT+Undo standing-rule checklist, per CLAUDE.md, BEFORE checking the presenting
   symptom**: VT normal playback (multi-file, mid-book, natural file-advance across a boundary), VT
   cross-file seeking (skip/chapter-nav across a file boundary), and Undo — all verified live, not
   assumed safe because the restore-specific fix is scoped narrowly. This is non-negotiable per the
   standing rule; a scoped fix can still regress an adjacent path in this zone (three of the four
   prior incidents did).
4. Confirm `pytest tests/ -q` stays green, and add new unit tests for the new
   `_vt_restore_pending` field's lifecycle (set in `load_book`'s reset, set by the new deferral
   path, consumed exactly once by `_on_file_loaded`'s VT branch, never leaks a stale value into a
   later book) in the existing pure-state-machine style (`tests/test_seek_state.py` /
   `tests/test_vt_seek.py`) — no mpv/QApplication required, matching how the rest of this state is
   already tested.

## Residual risks (stated plainly)

- **This is now explicitly the fifth documented incident risk in the VT+Undo fragile zone**
  (CLAUDE.md's standing rule currently lists three prior regressions plus this session's confirmed
  bug as a fourth "known-fragile" entry; a fix attempt here is the fifth touch on this zone). Three
  of the four prior attempts in this zone were reverted after passing their own verification.
- **The `is_seeking`/`_seek_target` state-combination question in step 3 above is not fully solved
  by this plan** — it's flagged as a real design detail requiring careful implementation-time
  checking against every existing reader of those two fields, not asserted safe in advance.
- **A forced-delay test harness is itself new, temporary code in a fragile zone** — it must be
  written carefully enough to prove what it claims (that it reliably reproduces the OLD failure
  100% of the time) before it can be trusted to validate the NEW fix; if the harness itself doesn't
  reliably force the old bug, a "100% pass under the harness" result for the fix is meaningless.
- **Deferring the seek changes exactly when `is_seeking` becomes true relative to when
  `_seek_target` becomes non-None**, for the specific case of a VT book's initial restore. This is
  a genuinely new state-timing combination in code that has broken three times before under far
  smaller changes. It needs to be treated with the same weight as those incidents, not as a "small,
  obviously safe" tweak.

## Escalation conditions — stop and report, do not push through

- If implementation reveals that `is_seeking`/`_seek_target` need to be set at the deferral point
  (before the file loads) in a way that conflicts with how the settle branch, the maintenance
  block, or `_on_vt_file_switched` currently read them — stop and report the conflict rather than
  adding a new guard to reconcile it inline. (Per CLAUDE.md's standing rule: "if something
  regresses, stop and report rather than patching inline — patching around an undiagnosed
  regression in this zone has not worked before.")
- If the forced-delay verification harness cannot be made to reliably reproduce the OLD bug 100% of
  the time (i.e. the race is more sensitive to real OS/mpv-internal timing than a simple injected
  delay can simulate) — stop and report, since that means confidence in the fix cannot be
  established the way this plan intends, and a different verification strategy needs to be
  designed before implementation is considered done.
- If VT+Undo live verification (step 3) turns up ANY regression, however small or seemingly
  unrelated (per the standing rule: "a heuristic... can score perfectly against captured samples
  and still break something live, for reasons that may never be diagnosed") — stop and report
  immediately rather than attempting an inline patch.
- If the investigation into `book_ready`'s ordering (done this session) turns out to have missed
  something once implementation starts — e.g. a consumer or timing assumption not surfaced by this
  session's research — stop and report rather than silently working around it.

## Current state of investigation instrumentation

The `[VT-RESTORE-RACE]` temporary DEBUG logging added during the investigation phase has been
**fully removed** — confirmed via `git status`/`git diff` showing `player.py`/`app.py` clean
against `HEAD`, and `grep -rn "VT-RESTORE-RACE" src/fabulor/` returning no matches. `pytest tests/
-q` passes (185 tests). Any new instrumentation needed for this fix's own verification (per the
"How this will be verified" section above) should be added fresh, scoped to this fix's review
cycle, and removed again before this branch ships — same discipline as the investigation phase.

## Critical files

- `src/fabulor/player.py` — `__init__` (near line 124, new field), `load_book`'s VT-state reset
  (near line 461), `_on_playlist_resolved` (479-504), `ungate_play` (506-519, both untouched in
  their `book_ready`/`play()` ordering), `_on_file_loaded` (529-596, VT branch dispatch at
  592-594 — the new deferred-seek consumption point), `seek_async` (697-796, VT same-file branch
  714-738 — unchanged for mid-book seeks, reused by the deferred path for the restore case),
  `_on_time_pos_change` (162-259, settle branch 166-189 and maintenance-block gate 190-225 — must
  NOT change, only re-verified against the new timing).
- `src/fabulor/app.py` — `_on_vt_file_switched` (1430-1432, untouched), `_on_file_ready`
  (1434-1480), `_restore_position` (1658-1679, the call site that changes for VT books),
  `_on_file_loaded_populate_chapters` (1515+, re-check but expected untouched).
- `CLAUDE.md` — "book_ready invariant" (~line 98) and "Seek/position tracking — VT+Undo is the
  known-fragile zone" (~line 138) — both re-read in full this session; any fix implementation must
  re-read them again immediately before writing code, and update the VT+Undo rule with this as a
  new (hopefully successful, unlike three of the four priors) entry once verified.
- `TODO.md` — the existing "VT restore-on-load is broken" entry (2026-07-13) is the item this fix
  resolves; delete it once shipped and verified (per the project's TODO.md convention).
- `tests/test_seek_state.py`, `tests/test_vt_seek.py` — where new unit tests for the deferred-
  restore field's lifecycle belong, alongside the existing merged drift-fix tests.

## Verification checklist before considering this fix done

1. Forced-delay harness proves the OLD code fails 100% of the time under a widened race window.
2. Same harness proves the NEW code succeeds 100% of the time under the same widened window.
3. 10-15 real consecutive close/relaunch cycles on 2 different VT books with saved positions, no
   artificial delay, 100% success.
4. VT normal playback, VT cross-file seeking, and Undo all separately live-verified with no
   regression, BEFORE declaring the presenting symptom fixed (per the standing rule's required
   order).
5. `pytest tests/ -q` green, including new tests for `_vt_restore_pending`'s lifecycle.
6. Any temporary verification-only instrumentation removed again before merge.
7. CLAUDE.md's VT+Undo fragile-zone rule updated with this as a new entry (success or, if
   reverted, failure — matching how the three prior attempts are documented either way).
