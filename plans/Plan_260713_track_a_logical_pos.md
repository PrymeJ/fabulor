# Fix compounding seek drift: track a logical position separate from mpv's raw report

## Context

Alternating forward/backward seeks (chapter-slider wheel scroll, or plain skip-button presses)
do not cancel out — position creeps forward every full cycle, enough to reach the end of the book
by scrolling/skipping back and forth. Root cause, confirmed by reading the code directly:
`Player.time_pos` (`player.py`) returns `self._cached_time_pos`, which `_on_time_pos_change`
unconditionally overwrites with mpv's **raw** reported position on every `time-pos` event —
including right after a seek settles, when mpv's real landing differs from the app's own nominal
`_seek_target` by a small residual (the reason `_PAUSED_SEEK_UNDERSHOOT_COMP = 0.37` exists at
all). Every subsequent seek computes its new target from this raw, imprecision-laden `time_pos`
rather than from the correct nominal position the app already tracks in `_seek_target` — so
per-seek residuals compound instead of cancelling. 18 call sites across `app.py`,
`ui/chapter_list.py`, `ui/theme_manager.py`, `ui/library.py` read `player.time_pos`.

This is the same root cause already caught and **deliberately deferred** in NOTES.md ("Near-zero
saved positions show spurious library progress," 2026-07-06) and TODO.md
(`[2026-07-06] FIX (batched with the mpv-playback pass)`), for a different symptom (a book opened
and closed without playback saves a creeped non-zero position instead of exactly 0). This plan is
that batched pass.

## Prior-history findings — READ BEFORE WRITING ANY CODE

A dedicated history audit (git log, NOTES.md, SESSION.md, TODO.md, DEBT_INVENTORY.md) found this
is NOT a first attempt at this problem class. Full detail now lives in CLAUDE.md's "Seek/position
tracking — VT+Undo is the known-fragile zone" rule (added as a direct result of this audit — read
it in the live file before starting, it is the authoritative summary). Restated here for the
implementation session:

**Three independent prior incidents, all in this exact area, all broke VT and/or Undo:**

- **2026-06-06, `seek_settled` signal attempt (`12dcf32` → reverted `a506de9`).** Introduced a new
  settle-convergence point for slider animations. Reverted after producing slider/fill desync,
  broken undo, notch reanimation on every scrub, VT slider corruption, chapterless-book snaps.
  Documented root cause: *"the 200ms timer is the silent antagonist — it fires regardless of load
  state and requires guards that have a one-tick gap."*
- **2026-06-06, `file_switched`-deferral attempt.** Deferred `file_switched` emission until after
  a VT seek settled. Reverted — broke undo (VT slider stuck after undo).
- **2026-06-15, `b6a4023` (reverted `4ae0783`/`92902cd`) — the structurally closest precedent.**
  Added `_last_global_pos` and rejected backward `time_pos` jumps in `_on_time_pos_change` via a
  `_STALE_BACKWARD_TOLERANCE = 0.3` heuristic. **Verified clean by instrumentation — 32/32 known
  artifacts correctly classified, zero false positives during forward playback or VT switches —
  shipped, and still broke VT backward-seek, the play/pause icon, and chapter[1]→[0] click.** No
  mechanism-level cause for any of the three was ever diagnosed; the record stops at "regressed
  X/Y/Z."

**What this means for this plan, stated plainly:** clean instrumentation data is necessary but has
already been proven **not sufficient** evidence of safety on this exact bug class. This plan's
delta-accumulation approach is a different mechanism from `b6a4023` (accumulate deltas + resync
fallback, vs. `b6a4023`'s outright sample rejection) but shares the identical risk shape: a
heuristic distinguishing "genuine motion" from "artifact motion" using only the previous sample as
context. It has no positive precedent (nothing this specific has been tried and kept) but is not a
documented repeat of a known-bad shape either — it is genuinely unproven territory, sitting
directly adjacent to a heuristic that looked correct and wasn't. **Do not treat a clean
instrumentation run as sufficient to proceed to live verification with reduced scrutiny — it
wasn't sufficient last time.**

One prior lesson this plan is already consistent with: the 2026-05-16 epsilon-origin note rejected
correcting position at a later write/save point in favor of correcting at the point of use (seek
time). This plan's design (correction at `seek_async`'s write sites) follows that lesson rather
than repeating the rejected alternative.

## Why VT+Undo verify FIRST, before the drift symptom itself

Not procedural — evidentiary. The presenting symptom (drift) has never been what actually broke
when this subsystem was touched before; VT and/or Undo broke, every single time, three times
independently. `b6a4023` is the sharpest evidence: verified correct against real captured data and
still broke three things with no diagnosed connection to the fix itself. A clean drift-cycle test
at the end would prove almost nothing about whether this implementation is safe — it's exactly the
kind of green result that gave false confidence last time. VT+Undo is the demonstrated fault line:
if this design silently breaks something the way its predecessors did, this is where it would show
up first. Checking it first means finding out in minutes whether the pattern is repeating, instead
of after a full verification pass that would otherwise feel like "done."

## Proposed approach

*(Design finalized 2026-07-12 against the full live-instrumentation dataset — 593 settles / 5879
samples across paused/playing, 1x–3x, VT and non-VT, rapid/interrupted/boundary/near-EOF seeks.
`SEEK_DRIFT_MEASUREMENTS.md` (branch-local, 8 findings) is the evidence record. Two constants and
one mechanism below were MEASURED, not guessed; one subtle sequencing trap was found and closed —
see "The settle/first-post-settle mechanism" and "Residual risks".)*

### Data model — two new fields + one constant on `Player`, no new class/file

```python
self._logical_pos: float | None = None     # GLOBAL space (matches _seek_target's convention)
self._last_raw_global: float | None = None # previous raw GLOBAL sample, for delta accumulation
self._just_settled: bool = False           # skip-one flag: the first post-settle sample is skipped
```

```python
# Sample-to-sample GLOBAL-position delta above which a raw sample is a discontinuity
# (VT file-switch / rapid-seek jump landing outside is_seeking) rather than continuous
# playback -> resync _logical_pos to raw. Measured 2026-07-12: normal deltas ~0.043s (1x)
# to ~0.13-0.26s (3x); largest genuine non-seek motion 0.556s (VT file-advance, 3x);
# smallest genuine seek jump ~9.4s. 2.5 sits in that clean gap.
_LOGICAL_POS_RESYNC_THRESHOLD = 2.5
```

`_logical_pos` represents "the position the app currently believes it is at." Lifecycle:
- **Set to the nominal target at every seek write site**, next to each existing `self._seek_target
  = <value>` (see the write-site map below) — the same value, always GLOBAL.
- **Adopted exactly at settle** — in `_on_time_pos_change`'s existing settle branch (`abs(global -
  _seek_target) < 1.0`), set `_logical_pos = self._seek_target` (nominal, discards the landing
  residual), and set `_just_settled = True`.
- **First post-settle sample is SKIPPED** (the load-bearing correction — see next section). When
  `_just_settled` is True, that one sample does NOT accumulate: `_logical_pos` holds the adopted
  target, `_last_raw_global` re-baselines to that sample's own raw global, `_just_settled` clears.
- **Advanced by delta during normal playback** (not seeking, not just-settled) — `_logical_pos +=
  (global - _last_raw_global)` per sample. A delta whose magnitude exceeds
  `_LOGICAL_POS_RESYNC_THRESHOLD` resyncs `_logical_pos = global` instead (VT file-switch, rapid
  seek outside `is_seeking` — Finding 4 confirmed this must NOT gate on `is_seeking`).
- **Resync on first-ever / post-reset** — if `_logical_pos is None` or `_last_raw_global is None`,
  set `_logical_pos = global`.

### The settle / first-post-settle mechanism (the one subtle trap, found and closed)

A "reprime the delta baseline at settle" idea (from an earlier design pass) was traced against real
numbers and found to be **case-incompatible**: same-file-paused and VT-cross-file settles want
*opposite* baselines, because mpv behaves differently after each — after a same-file paused settle
the next raw sample stays at mpv's *actual* landing (residual-laden), while after a VT cross-file
settle the next raw sample *catches up to the target*. No single reprime value works for both. The
correct, case-agnostic mechanism is **"skip exactly the first post-settle sample's accumulation"**:
it refuses to reconcile the deliberately-created raw/logical divergence via a delta at all, waits
one tick for mpv's stream to stabilize, then resumes lockstep accumulation from wherever mpv
actually is. Verified by hand-trace against both cases' real numbers (paused 8.56/8.19; VT
694.51/694.86) — both land correct. This supersedes the "no-op by construction" framing from
Finding 8, which was TRUE but INCOMPLETE (it held for same-file, was never validated against VT
cross-file, which is exactly where the naive version breaks). The "skip exactly one" count is
itself MEASURED (see Residual risks): across 482 post-settle sequences the second sample was always
clean normal playback — never two consecutive ragged samples.

### Ordering inside `_on_time_pos_change` (load-bearing)

`_cached_time_pos = value` stays exactly where it is (raw, unconditional). The new logical-position
maintenance block goes AFTER the existing settle branch (so `_just_settled`/`_logical_pos` are set
first) and BEFORE the chapter-walk blocks (which stay byte-for-byte unchanged, still reading raw
`value`/`global_pos`). The `_last_raw_global` re-baseline happens INSIDE the maintenance block
(skip-branch and accumulate/resync branches all set it to the current sample's raw global), so
there is no separate trailing unconditional update to sequence against the settle — this avoids the
clobber trap the earlier "reprime + trailing update" formulation created. All new logic guards on
`value is not None`, matching every existing raw read.

### Write-site map (exact, grep-verified line numbers, current `player.py`)

Each `self._seek_target = <x>` gets a `_logical_pos` companion:
- **`_logical_pos = <same value>`** (adopt the intended target): `seek_async` non-VT (~719), VT
  same-file (~662), VT cross-file (~680); `_mp3_stop_and_load` (~628); `_on_file_loaded` VT
  cross-file follow-up (~536, `pending + target_offset`, GLOBAL); `_on_file_loaded` mp3-reload
  settle (~496, adopt BEFORE the `_seek_target = None` clear — this path `return`s early and never
  hits the `_on_time_pos_change` settle, so it must adopt here or `_logical_pos` stays stale).
- **`_logical_pos = None`** (genuine reset — getter falls back to raw path): `load_book` reset
  (~437, plus `_last_raw_global = None`); `_on_file_loaded` VT EOF-guard skip (~514, seek abandoned
  — see the one-tick note in Residual risks).
- The settle clear (~182) is handled by the adopt-then-`_just_settled` logic above, not a bare
  companion.

**Hard constraint from prior history (2026-05-29 NOTES.md entry):** `_cached_time_pos` holds
FILE-LOCAL position for VT books — never global. `_logical_pos` must not repeat this mistake in
reverse: it is always GLOBAL, matching `_seek_target`'s existing convention, and must never be
conflated with `_cached_time_pos`'s local-space semantics. A prior real bug (VT stop-and-load "0%
reset") came from exactly this kind of local/global mixing. Do NOT couple the `_logical_pos` write
to any `_cached_time_pos` write — they are independent (`_cached_time_pos` is local-for-VT).

### Remove the temporary instrumentation as part of this change

The `[SEEK-DRIFT-MEASURE]` block in `_on_time_pos_change` (~lines 145-176), the `_dbg_last_raw_global`
field in `__init__` (~98), and its reset in `load_book` (~438) were the measurement scaffold — all
three are removed when the real `_logical_pos` logic lands. Grep-verify no `_dbg_last_raw_global` /
`SEEK-DRIFT-MEASURE` references remain.

### `Player.time_pos` getter — the entire blast-radius-limiting move

```python
@property
def time_pos(self):
    if self._logical_pos is not None:
        return self._logical_pos
    if self._cached_time_pos is None:
        return None
    if self._virtual_timeline is not None:
        return self._file_offset + self._cached_time_pos
    return self._cached_time_pos
```

Every existing call site (18 found across `app.py`, `ui/chapter_list.py`, `ui/theme_manager.py`,
`ui/library.py`) keeps calling `player.time_pos` exactly as today. **No call-site changes required
anywhere outside `player.py`.**

### What must keep reading RAW mpv data (unchanged) — protects the epsilons

- **The chapter-walk-and-emit block inside `_on_time_pos_change`** (VT and non-VT branches) —
  keeps reading `value`/`global_pos` (raw). Drives `chapter_changed`, calibrated against mpv's
  *actual* landing; must never consume already-corrected data.
- **`_cached_time_pos` itself** — stays raw, unconditionally updated on every sample, never frozen.
  Independently pinned by `tests/test_seek_state.py::test_cached_time_pos_tracks_every_sample`
  (guards against `b6a4023`'s shape of regression). `_logical_pos` is additive, not a replacement.
- **`seek_async`'s paused-undershoot compensation** — keeps sending the compensated value to the
  mpv command only; `_seek_target`/`_logical_pos` keep the uncompensated nominal value.
- **`_on_pause_test`** — reads `self.instance.time_pos` directly, bypasses the property already;
  untouched.
- **MPV-init block** (`_ensure_mpv`, `load_book`'s MPV constructor args, `locale.setlocale`) — out
  of scope, standing CLAUDE.md rule, no exceptions.

### Call-site inventory (18, categorized — for reference, no changes needed at any of them)

- **Seek-origin math (the drift-causing sites, fixed automatically by the getter change):**
  `app.py` — `handle_rewind`, `handle_forward`, `wheelEvent`'s chapter-notch branch.
- **Undo-threshold comparisons** (`abs(new_pos - old_pos) > 60 * speed`, precision-insensitive):
  `_on_slider_released`, `_on_slider_right_clicked`, `_on_chap_slider_released`,
  `_on_prev_right_click`, `handle_prev`, `handle_next`, `_on_chapter_list_selected`,
  `ui/chapter_list.py`'s `_activate_item`.
- **Continuous display/persistence (real behavior change, believed positive):** `_update_ui_sync`
  (drives `session_recorder.update_furthest_position`), `_show_chapter_dropdown`,
  `_save_current_progress` (the exact site the deferred 2026-07-06 TODO.md item is about — this
  fix resolves it as a side effect), `ui/library.py`'s `update_current_book_progress`,
  `ui/theme_manager.py`'s `_unfreeze_fade_labels`.

**Confirmed (2026-07-12 trace, no code changes made): `_restore_position`'s `seek_async` call
(`app.py:1665`) IS write site #4 (one of the four `seek_async` sites already listed above) — book
load/resume-on-load does NOT take a separate position-setting path.** Traced directly: `_on_file_ready`
(`app.py:1434`) → `_restore_position` (`app.py:1651`) → `self.player.seek_async(book_data.progress)`
(`app.py:1665`), which assigns `_seek_target` and settles through `_on_time_pos_change`'s normal
settle check exactly like any other seek. Verified there is exactly one `seek_async(...progress...)`
call site in the codebase (grepped), and exactly one `book_ready` connection wiring `_on_file_ready`
(`app.py:389`, `QueuedConnection`, wired once at startup) plus one direct re-invocation
(`_drain_deferred_file_ready`, `app.py:1590-1592`, the documented library-panel-animation deferral
drain — same function, delayed call, not a second implementation). So both cold-launch and
switching-books-from-the-library route through the identical path. No new write site needed. This
closes what was previously an open question (raised while investigating a related, previously-
unexplained symptom — see the new verification item below) — do not re-investigate this later
thinking it's still open.

## Pre-fix data collection — DONE (2026-07-12)

The instrumentation step is COMPLETE. Temp `[SEEK-DRIFT-MEASURE]` logging was added to
`_on_time_pos_change` (behavior-neutral, 174 tests still green), run live across the full scenario
set (alternating wheel-scroll paused+playing, skip buttons, VT cross-file, rapid/interrupted
seeks, chapter-boundary crossings, near-EOF, 1x–3x), yielding 5879 samples / 593 settles. All
constants and the skip-one mechanism above are derived from that data, not guessed. Full record:
`SEEK_DRIFT_MEASUREMENTS.md` (branch-local). The instrumentation is REMOVED as part of landing the
real fix (see "Remove the temporary instrumentation" above). **Lesson carried forward regardless:
clean data was necessary but not sufficient (`b6a4023`); live VT+Undo verification still runs
FIRST — see below.**

## Implementation and verification order (this order is load-bearing, do not reorder)

1. Add the constant `_LOGICAL_POS_RESYNC_THRESHOLD = 2.5`, the `_logical_pos` / `_last_raw_global` /
   `_just_settled` fields (`__init__`), and the `_on_time_pos_change` maintenance block
   (settle-adoption + `_just_settled` skip-one + delta-accumulation + resync fallback), in the
   ordering specified above. Remove the temp instrumentation in the same change.
2. Add the `_logical_pos` companions at every `_seek_target` write site per the write-site map
   (adopt-value at the six seek/reload sites, `None` at the two reset/abandon sites).
3. Add `load_book`'s reset additions (`_logical_pos = None`, `_last_raw_global = None`); change the
   `time_pos` getter to short-circuit on `_logical_pos`.
4. Write and pass new `tests/test_seek_state.py` cases (settle-adopts-target-exactly, skip-one,
   alternating-cycle regression, delta-accumulation, resync-guard, None-sample survival) BEFORE any
   live testing.
5. **Live-verify chapter landing and VT+Undo FIRST, together, before anything else:**
   - Next/Prev in both paused and playing states — correct chapter, start of chapter, first word
     intact.
   - Undo immediately after a seek, in both VT and non-VT books.
   - VT backward-seek specifically, the play/pause icon state right after a seek settles, and a
     chapter[1]→[0] click — named individually because `b6a4023` broke exactly these three, for
     reasons never diagnosed. A clean pass here is the closest available evidence this plan's
     different mechanism doesn't share `b6a4023`'s undiagnosed failure cause — not proof, but the
     specific regression surface to point verification at.
   **If any of the above regresses: STOP and escalate (see below). Do not proceed to drift
   verification with a known regression in this set.**
6. Only after step 5 is confirmed clean: live-verify the two drift repros (wheel-scroll
   alternating cycles, plain skip-button cycles), paused and playing, embedded M4B.
7. **Live-verify the load-time "sliver"/retrace on a short chapter (~25s or less), mid-chapter
   saved position (e.g. 7s in) — expected outcome, not yet confirmed.** Traced 2026-07-12: the
   flow animation lands the slider exactly on the nominal DB-stored position; separately, once
   that animation finishes, the 200ms `ui_timer` resumes and `_update_ui_sync` (`app.py:1746`)
   starts reading `player.time_pos` live — today raw, carrying whatever landing residual
   `_restore_position`'s `seek_async` settled with (the same 0.09–0.37s residual class this whole
   fix targets), visible as a retrace on a short-enough chapter that the residual is a noticeable
   fraction of the visible range. This is a DIFFERENT, already-fixed bug from the existing
   `_sliver_clamp` (`app.py:2017`, paused-only, chapter-slider-only, NOTES.md 2026-06-15) — do not
   conflate them or "fix" this by extending that clamp. Once `_logical_pos` lands, this path should
   resolve as a side effect with no new write site needed (`_restore_position`'s `seek_async` call
   is confirmed write site #4, see above) — **but this is a prediction from the trace, not yet a
   confirmed live result, and per this whole session's throughline (clean instrumentation/reasoning
   has not been sufficient on its own for this codebase before), it must not be marked resolved
   until an actual repro shows the retrace gone.** Also note explicitly: unlike the chapter slider,
   the main progress slider has NO defensive clamp of any kind today — after this fix, correctness
   on this path comes entirely from `_logical_pos` reading true, with zero fallback protection if
   the settle-adoption or repriming logic has a bug. This is exactly why it needs a real live check
   here, not just "should be fine given the trace" — and exactly why a clamp should NOT be added as
   a hedge (a clamp would just be another hack papering over the same root cause this plan exists
   to eliminate).

   **Third confirmed instance, same check:** manual chapter-slider click on a short chapter
   (`_on_chap_slider_released` → `seek_within_chapter` → `seek_async`) shows the identical
   `_PAUSED_SEEK_UNDERSHOOT_COMP` residual (confirmed live, 0.37s landing residual on a 5s chapter
   — reads as "moves to click point, then jumps forward," not a progressive drift). Same write
   site, already covered, no plan change needed beyond checking it in this same step: short
   chapter, manual click at various points, in addition to the book-load case above.
8. Extend and pass `tests/test_vt_seek.py` for the VT cross-file settle case.
9. Spot-check `session_recorder` furthest-position tracking on a real session.
10. Re-run `tests/test_seek_state.py`'s existing tests UNMODIFIED — must stay green with zero
    changes to their assertions (they assert `_cached_time_pos` directly).

## DO NOT

- Do NOT change `_cached_time_pos`'s update logic. Stays raw, unconditional, every sample. If you
  think you need to touch it, stop and escalate.
- Do NOT change what the chapter-walk-and-emit block in `_on_time_pos_change` reads — raw
  `value`/`global_pos`, never `_logical_pos`. This is what keeps the epsilons calibrated against
  real mpv behavior.
- Do NOT touch `_CHAPTER_WALK_TOLERANCE`, `_EMBEDDED_CHAPTER_SEEK_OFFSET`,
  `_PAUSED_SEEK_UNDERSHOOT_COMP`, or `_CHAPTER_BOUNDARY_EPSILON` values. If live verification
  suggests one needs adjustment, stop and escalate — do not tune them as part of this fix.
- Do NOT change any of the 18 call sites outside `player.py`. The getter is the seam. If a call
  site seems to need special handling, stop and escalate rather than special-casing it.
- Do NOT touch `_on_pause_test` — unrelated, already bypasses the property.
- Do NOT touch the MPV-init block, `_ensure_mpv`, `load_book`'s MPV constructor args, or
  `locale.setlocale`. Out of scope per standing CLAUDE.md rule.
- Do NOT re-guess the resync threshold — it is `_LOGICAL_POS_RESYNC_THRESHOLD = 2.5`, measured
  (Findings 1/8). If live behavior suggests it's wrong, stop and escalate rather than tuning it
  blind.
- Do NOT replace the `_just_settled` skip-one with a "reprime the baseline at settle" formulation —
  that was traced and found case-incompatible (same-file-paused and VT-cross-file want opposite
  baselines; see "The settle / first-post-settle mechanism"). Skip-one is the only case-agnostic
  fix.
- Do NOT skip straight to drift verification before chapter-landing/VT+Undo verification passes.
- Do NOT perform the one-time DB/QSettings migration (zeroing poisoned sub-threshold
  `pos_`/`books.progress` values) as part of this session. Log it as a follow-up in TODO.md — it
  depends on this fix already being landed and verified.

## Escalation conditions — stop and report, do not improvise

- Chapter Next/Prev landing regresses in any state (paused or playing).
- VT backward-seek, the play/pause icon after a seek settles, or a chapter[1]→[0] click misbehaves
  in any way — the exact three things `b6a4023` broke; treat any anomaly here as high-signal even
  if it seems minor or unrelated to position tracking.
- Undo after a seek regresses in either VT or non-VT books.
- The first-post-settle sample cannot be reliably distinguished from a genuine implausible jump
  without a threshold that also misclassifies normal high-speed playback deltas. Any sign of the
  "fires regardless of load state, one-tick guard gap" shape from the 2026-06-06 `seek_settled`
  revert → stop immediately rather than patching the gap.
- VT cross-file delta continuity does not match this plan's assumption (the sample immediately
  after a file-load doesn't cleanly fall into "settle" or "implausible jump").
- Any existing test in `test_seek_state.py`, `test_vt_seek.py`, or `test_session_recorder.py`
  fails and the failure is not obviously explained by the intended logical-vs-raw behavior change.
- Anything else structurally resembling `b6a4023` (looks correct under instrumentation, breaks
  something unrelated-looking in live use) — do not patch around it inline. That shape has already
  consumed one full implementation-and-revert cycle without a diagnosed cause; assume it will
  again if rushed.

**What "stop and report" means procedurally, so it isn't just a phrase:** on any escalation
condition, stop making further changes in this area entirely — do not attempt a fix, do not
proceed to the next step in the implementation/verification order above, and do not move on to a
different, unrelated task in the same session as if nothing happened. Report what regressed, what
was observed, and what had already been changed at that point, directly in conversation, then wait
for input before doing anything else. Do not revert, commit, or otherwise resolve the state
unilaterally, and do not end the session — leave the working tree exactly as it was at the moment
of escalation so the state is fully visible, and let the user decide whether to revert, investigate
further, or redirect.

## Verification plan (detail)

New `tests/test_seek_state.py` cases (drive `_on_time_pos_change` directly with synthetic samples,
no mpv / no QApplication — existing file style):
- **settle-adopts-target-exactly**: `_is_seeking=True`, `_seek_target=150.0`; feed a settle sample
  OFF-target (`150.37`, the residual). Assert `_logical_pos == 150.0` (exact, not `150.37`),
  `time_pos == 150.0`, `_is_seeking is False`, `_just_settled is True`.
- **skip-one-then-clean**: after the settle above, feed the first post-settle sample; assert
  `_logical_pos` UNCHANGED (still `150.0`) and `_just_settled` cleared; then a second normal sample
  accumulates from there. This pins the skip-one mechanism.
- **alternating-cycle-returns-to-origin**: N alternating forward/back seeks each followed by an
  off-target settle sample; assert `time_pos` returns to the exact origin (`< 1e-9`) — the direct
  drift regression.
- **delta-accumulation-tracks-playback**: no seek, seeded `_logical_pos`; feed a monotone
  small-delta sequence; assert `_logical_pos` advances by the summed deltas; assert
  `_cached_time_pos == last_sample` (co-invariant unchanged).
- **resync-on-implausible-delta**: seed `_logical_pos=100.0`, `_last_raw_global=90.0`; feed
  `500.0` (delta 410 ≫ 2.5); assert `_logical_pos == 500.0` (resync, NOT `100+410=510`). Sub-case:
  `is_seeking=False`, `seek_target=None`, a `raw=0.0`-style large NEGATIVE jump (Finding 4) →
  assert resync, confirming the fallback is NOT gated on `is_seeking`.
- **logical-pos-survives-None-sample**: seed `_logical_pos=200.0`, feed a `None` sample; assert
  `_logical_pos == 200.0` (unchanged, the deliberate asymmetry vs `_cached_time_pos` which goes
  `None`).

`tests/test_vt_seek.py` — **VT cross-file settle + first-post-settle-skip** (the highest-risk case,
pins the trap that was found): simulate the cross-file seek, assert `_logical_pos` == GLOBAL
`_seek_target`; feed the off-target settle (`cum+0.30`) then the Finding-2 next-tick sample whose
global is `cum+0.35` (mpv catching up); assert `_logical_pos` stays at the ADOPTED target and does
NOT become `target + 0.35` (i.e. the skip-one prevented the residual re-add). Mirror the file's
existing `_simulate_cross_file_seek` GLOBAL-vs-LOCAL harness.

`tests/test_session_recorder.py` — re-run, confirms the furthest-position semantic shift doesn't
break anything pinned.

All EXISTING `test_seek_state.py` tests must pass UNMODIFIED (they assert `_cached_time_pos` /
`chapter_changed` / `_is_seeking` / `_seek_target`, none of which this change alters).

- Live verification per the ordered list above (chapter landing + VT/Undo first, then drift).
- Follow-up (not this session): one-time migration zeroing already-poisoned sub-threshold `pos_`
  (QSettings) / `books.progress` (DB) values — log as a new TODO.md entry.

## Residual risks carried into implementation (do not silently consider resolved without a check)

1. VT file-switch delta continuity — still the least-verified part in LIVE terms; the mechanism is
   now traced and unit-testable (see the VT cross-file settle test), but needs live VT-book
   verification, not just embedded-M4B testing. (No longer "unknown" — the settle-adoption +
   skip-one design is hand-traced correct against the real 694.51/694.86 numbers; this risk is now
   "verify the trace holds live," not "design unresolved.")
2. **RESOLVED by measurement + trace — first-post-settle handling.** Was "investigation-shaped."
   Now: the "skip exactly the first post-settle sample" mechanism is designed, hand-traced against
   both same-file-paused and VT-cross-file real numbers (both correct), and the "exactly one ragged
   sample" assumption is MEASURED across 482 post-settle sequences (second sample always clean
   normal playback, max |delta| 0.128s, zero two-ragged cases). See the sub-resync gap below for
   the one precisely-bounded residual.
3. **RESOLVED by measurement — implausible-delta threshold** is `_LOGICAL_POS_RESYNC_THRESHOLD =
   2.5`, chosen from the measured clean gap (largest genuine non-seek motion 0.556s, smallest
   genuine seek jump ~9.4s). No longer a guess.
4. Chapter-current-index resolution (`activate_chapter_index`, `previous_chapter`, `next_chapter`,
   `seek_within_chapter`) now reads logical instead of raw — believed safe, not a provable no-op,
   primary focus of step 5 live verification.
5. `session_recorder.update_furthest_position` now receives logical positions — believed
   benign-to-positive, spot-check live, not exhaustively checked against the full state machine.
6. **Sub-resync second-ragged post-settle sample — bounded theoretical gap, NOT observed.** The
   "skip exactly one" rule skips the first post-settle sample; the resync guard (≥2.5s) catches a
   *large* second ragged sample cleanly (hand-traced, no order-dependent skip/resync interaction —
   the skip flag is already cleared by the time a second sample is evaluated). The one uncovered
   case: a SECOND consecutive post-settle sample whose |delta| is above the normal-playback floor
   but BELOW 2.5s would leak into `_logical_pos`. **This never occurred across the entire
   stress-test session (482 sequences, second sample always normal playback).** The leak, if it
   ever occurred, is **capped below 2.5s by construction** — it can be at most just under the
   resync threshold, on a single sample, and cannot compound (the third sample resumes clean
   lockstep) — so it can never be worse than the resync guard's own ceiling. **Falsification
   signal (name it so it's not re-diagnosed from scratch):** if live verification or future
   debugging ever shows TWO CONSECUTIVE post-settle samples both above the normal-playback floor,
   this documented-risk has become real and this section is where to start, not a new mystery. A
   `skip-until-clean` generalization (skip while |delta| > per-speed floor) was considered and
   deliberately NOT taken — it adds another measured constant and complexity to the hottest code
   path to guard a case the data says doesn't happen.

## After landing — required report contents

- Instrumentation numbers actually used for the implausible-delta threshold, and why.
- Explicit confirmation the verification order above was followed (chapter landing + VT/Undo
  before drift), not just that all checks eventually passed.
- Any residual concern not resolved by testing — do not silently mark this fully closed if any of
  the five residual risks weren't concretely addressed by a test or a live check.
- **Explicit statement, one way or the other: did this implementation show any sign of the
  `b6a4023` pattern (clean under instrumentation, something breaks live anyway)?** If yes, stop
  and report rather than patching — that pattern has no diagnosed fix on record; guessing at one
  now risks the same undiagnosed-revert outcome. If no, say so plainly so NOTES.md can record a
  real resolution rather than an assumed one.

## Critical files

- `src/fabulor/player.py` — all logic changes: `_on_time_pos_change`, `time_pos` getter,
  `seek_async` (four `_seek_target` write sites), `_mp3_stop_and_load`, `_on_file_loaded`'s VT
  cross-file follow-up, `load_book`'s reset block, `__init__`'s new fields.
- `tests/test_seek_state.py` — primary regression suite; add new logical-position tests.
- `tests/test_vt_seek.py` — extend for VT cross-file (highest-risk area).
- `CLAUDE.md` — the VT+Undo fragile-zone rule already exists (added from this history audit); add
  one new rule documenting `_logical_pos`'s own invariants once implemented, parallel to the
  existing `_seek_target`/`is_seeking` rules.
- `NOTES.md` — update the 2026-07-06 entry (mark resolved, link commit); add a short note
  explicitly comparing this fix's outcome to `b6a4023` (same risk shape, different mechanism) —
  whether it held up live or not, for future-history-audit discoverability.
- `TODO.md` — mark the batched item done; add the DB/QSettings migration as a new, separate
  follow-up entry.
- `src/fabulor/app.py` — no code changes required; `_save_current_progress`, `wheelEvent`,
  `handle_rewind`/`handle_forward` are the call sites whose *behavior* changes and are the focus
  of live verification.
