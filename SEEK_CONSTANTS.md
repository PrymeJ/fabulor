# Seek constants — interaction map

mpv's seek behavior is not precise. The constants at the top of `src/fabulor/player.py`
are empirically measured compensations for specific, characterized mpv artifacts — overshoot,
undershoot, stale post-settle samples, sample-to-sample discontinuities. They are not design
choices and should not be adjusted without re-running the relevant measurement.

This document complements the inline comments in `player.py` — it does not duplicate them.
The comments remain authoritative for each constant's value and immediate rationale. This
document adds what comments cannot: the cross-constant interaction map, measurement provenance
in one place, and navigation guidance for anyone considering a change.

## Constants table

| Name | Value | Phenomenon it compensates | Book types affected | Measurement date | Source |
|---|---|---|---|---|---|
| `_CHAPTER_WALK_TOLERANCE` | 0.5s | mpv's paused-seek undershoot (~0.37s) misattributing a position→chapter-index walk to the chapter just left | All (VT, CUE, embedded M4B) — every position→index walk in `player.py`/`app.py` | 2026-06-13 | Inline comment, `player.py` |
| `_CHAPTER_BOUNDARY_EPSILON` | 0.35s | Legacy seek-target epsilon for boundary landing | VT and CUE only (embedded M4B uses `_EMBEDDED_CHAPTER_SEEK_OFFSET` instead) | Pre-2026-06-13 (superseded rationale corrected 2026-06-13) | Inline comment, `player.py` |
| `_EMBEDDED_CHAPTER_SEEK_OFFSET` | −0.09s | mpv's natural chapter-seek overshoot (~0.09s, 1–2 AAC frames) while playing | Embedded M4B only | 2026-06-13 (5 M4Bs, 67 chapter seeks) | Inline comment, `player.py` |
| `_PAUSED_SEEK_UNDERSHOOT_COMP` | 0.37s | mpv's paused-seek undershoot — while paused, an exact seek lands ~0.37s short of target | Embedded M4B only; VT/CUE paused-seek behavior was not characterized | 2026-06-13 | Inline comment, `player.py` |
| `_LOGICAL_POS_RESYNC_THRESHOLD` | 2.5s | Distinguishes a genuine discontinuity (VT file-switch, rapid-seek jump landing outside the `is_seeking` window) from normal playback delta, for `_logical_pos` accumulation | All (operates in global position space) | 2026-07-12 (5879 samples / 593 settles) | Inline comment cites `SEEK_DRIFT_MEASUREMENTS.md` — **this file does not exist in the repo (confirmed via `git log --all`). Dead reference; documentation debt.** The underlying measurement is not lost — see NOTES.md, "Compounding seek drift fixed via `_logical_pos`" (2026-07-13), which restates the same figures (5879 samples / 593 settles, 482 post-settle sequences, max \|delta\| 0.128s) inline. Treat NOTES.md as the working source of record until/unless `SEEK_DRIFT_MEASUREMENTS.md` is recreated. |
| `_POST_SETTLE_BACKWARD_TOLERANCE` | 0.05s | mpv's stale post-settle backward `time_pos` sample (~50–900ms after settle, into the previous chapter) reaching the chapter walk | All (VT, CUE, embedded M4B) — any seek that settles | 2026-08-12 | Inline comment, `player.py`; live-verified in NOTES.md, 2026-08-11 entry's "Resolution (2026-08-12)" |

## Interaction map

This is the section that doesn't exist anywhere else today — the relationships between these
constants that matter for correctness, and what breaks if a change violates one.

### `_PAUSED_SEEK_UNDERSHOOT_COMP` (0.37) vs `_CHAPTER_WALK_TOLERANCE` (0.5)

The walk tolerance must exceed the undershoot comp, or the chapter walk misattributes after a
paused seek. **Direction of failure:** if `_CHAPTER_WALK_TOLERANCE` is lowered to ≤ 0.37, a
paused seek to a chapter boundary lands short of it by ~0.37s, and the position→index walk
(`time <= pos + tolerance`) resolves to the chapter just left instead of the target — paused
Next/Prev gets stuck re-targeting the same chapter and the chapter slider/label freeze. The
current 0.13s gap (0.5 − 0.37) is the safety margin. This is documented as the single narrowest
margin in this set — see "Before you change anything" below.

### `_POST_SETTLE_BACKWARD_TOLERANCE` (0.05) vs minimum real chapter spacing (~2s)

The tolerance must stay far below minimum chapter spacing, or the post-settle guard could
suppress a genuine position rather than only the stale artifact. **Direction of failure:** if
`_POST_SETTLE_BACKWARD_TOLERANCE` were widened toward ~2s, a legitimate short backward seek that
lands close to — but genuinely short of — the settle target (e.g. a real chapter-to-chapter
seek whose net displacement is small) could be misclassified as the stale artifact and have its
chapter walk suppressed. The current gap (0.05s vs. ~2s minimum spacing) is roughly 40x, wide by
design — see the `_on_time_pos_change` settle-site comment for why the reference is the *exact*
settle position rather than a magnitude estimate, which is what allows the tolerance to stay this
tight in the first place.

### `_CHAPTER_BOUNDARY_EPSILON` vs `_EMBEDDED_CHAPTER_SEEK_OFFSET`

Mutually exclusive by book type — `_CHAPTER_BOUNDARY_EPSILON` applies to VT/CUE seek targets,
`_EMBEDDED_CHAPTER_SEEK_OFFSET` applies to embedded M4B chapter-nav targets only. They must
never both apply to the same seek. **Direction of failure:** if a future code path applied both
to the same target (e.g. an embedded M4B seek that also added the VT/CUE epsilon), the combined
offset (+0.35 and −0.09 partially cancel, but not to a value anyone has measured or intended)
would land nowhere near either constant's calibrated target — reproducing exactly the "first
word of the chapter skipped" bug `_EMBEDDED_CHAPTER_SEEK_OFFSET` was introduced to fix (see its
inline comment: the old unified `_CHAPTER_BOUNDARY_EPSILON` skipped ~0.44s of every embedded
chapter's opening before the split).

### `_PAUSED_SEEK_UNDERSHOOT_COMP` vs `_POST_SETTLE_BACKWARD_TOLERANCE`

The undershoot comp shifts where a paused seek actually lands — that already-compensated landing
position is what becomes `_post_settle_target` when the seek settles. `_POST_SETTLE_BACKWARD_TOLERANCE`
(0.05) only needs to cover float noise around that landing, not the raw ~0.37s undershoot
magnitude, because the compensation has already been applied to the mpv seek command by the time
settle fires. **Direction of failure:** if a future change made `_post_settle_target` capture the
*uncompensated* nominal target instead of the actual settled `value`, the post-settle tolerance
would need to be widened toward the undershoot magnitude to avoid false suppression on every
paused embedded-M4B seek — which would then reopen the `_POST_SETTLE_BACKWARD_TOLERANCE` vs.
minimum-chapter-spacing risk above. The two constants stay decoupled only because
`_post_settle_target` is assigned from the settle call's actual raw `value`, not a nominal or
pre-compensation figure — see the settle-site assignment in `_on_time_pos_change`.

### `_LOGICAL_POS_RESYNC_THRESHOLD` (2.5) — independent of the others

Operates in global space on delta magnitude, not on chapter boundaries or seek targets. The
measured gap between the largest normal-playback delta (0.556s, a VT natural file-advance at 3x
speed) and the smallest genuine seek jump (~9.4s) is wide — 2.5 sits cleanly in that gap. No
current interaction with the chapter-walk constants (`_CHAPTER_WALK_TOLERANCE`,
`_CHAPTER_BOUNDARY_EPSILON`, `_EMBEDDED_CHAPTER_SEEK_OFFSET`) or with
`_POST_SETTLE_BACKWARD_TOLERANCE` — it governs `_logical_pos` accumulation/resync, which the
chapter walk deliberately does not read (the walk reads raw `value`, per the invariant in
CLAUDE.md's `Player.time_pos` section). If a future change ever made the chapter walk read
`_logical_pos` instead of raw `value`, this independence would end and the interaction would need
re-deriving from scratch — do not assume it stays independent under such a change.

## Before you change anything

- **Re-read the interaction map first.** Changing one constant can push another outside its safe
  range — the pairs above are not independent by accident, and some of the margins are narrow.
- **Re-characterize the relevant mpv behavior before adjusting a value.** These were measured, not
  estimated. A plausible-sounding new value is not a substitute for a new measurement.
- **`_CHAPTER_WALK_TOLERANCE` and `_PAUSED_SEEK_UNDERSHOOT_COMP` are the highest-risk pair** — the
  0.13s gap between them is the smallest safety margin in this set.
- **The `SEEK_DRIFT_MEASUREMENTS.md` reference in `_LOGICAL_POS_RESYNC_THRESHOLD`'s inline comment
  is a dead link.** If you need to re-characterize that constant, re-run log instrumentation from
  scratch (see `logger_setup.py` and `FABULOR_LOG_LEVEL`) rather than looking for the file — it
  does not exist in this repo, confirmed via `git log --all -- SEEK_DRIFT_MEASUREMENTS.md`.
- **VT+Undo is the known-fragile zone.** Any change touching seek behavior must be live-verified
  against VT (multi-file) books and Undo before being considered done — see CLAUDE.md's
  "Seek/position tracking — VT+Undo is the known-fragile zone" section for the four-times-broken
  history behind this rule.

## Measurement methodology

All constants were characterized via DEBUG-level log instrumentation
(`FABULOR_LOG_LEVEL=DEBUG`, `fabulorenv` activated, app run under `entr` for rapid restart
during iteration). The general approach: instrument `_on_time_pos_change` to emit raw sample
values at the relevant event (post-seek, post-settle, file-boundary), capture a representative
session log, measure the artifact magnitude distribution, set the constant with margin. Sample
counts where known are in the inline comments (e.g. 67 chapter seeks across 5 M4Bs for the
overshoot/undershoot figures; 5879 samples / 593 settles for the resync threshold; 149 settle
events / ~50 artifact firings for the post-settle guard's live verification). No external
measurement tooling — log files and manual analysis only.
