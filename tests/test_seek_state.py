"""Seek-state regression net for ``Player._on_time_pos_change``.

These tests drive the seek-settle state machine and the chapter-resolution walk
DIRECTLY — no mpv, no audio, no QApplication. They encode the invariants that the
reverted ``b6a4023`` fix violated (it early-returned and starved the settle/cache),
so this suite is provably able to catch that whole class of regression.

The invariants under test:
  * the seek settle clears ``is_seeking``/``_seek_target`` once the position lands —
    INCLUDING backward seeks (target lower than current), which is what broke;
  * ``_cached_time_pos`` tracks every sample and never freezes (the "stale slider /
    -00:00 remaining" symptom);
  * the chapter walk resolves and emits the right index (VT global-space and non-VT
    tolerance-space), without re-emitting an unchanged chapter.
"""
import pytest

from fabulor.player import Player, _CHAPTER_WALK_TOLERANCE


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def make_player():
    """A Player with no mpv instance, ready to receive _on_time_pos_change calls."""
    return Player(db=None, config=None)


def capture_chapters(player):
    """Connect a list-collector to chapter_changed; returns the list."""
    received = []
    player.chapter_changed.connect(received.append)
    return received


def setup_non_vt(player, chapter_times):
    """CUE-like / chaptered single file: _chapter_list set, no virtual timeline.

    (Embedded M4B reads chapters off the mpv instance; here we set _chapter_list so
    the walk has data without an mpv. The walk arithmetic is identical.)
    """
    player._virtual_timeline = None
    player._chapter_list = [{"time": t} for t in chapter_times]
    player._file_offset = 0.0
    player._last_nonvt_chapter = -1
    player._last_vt_chapter = -1


def setup_vt(player, file_durations, current_index):
    """Multi-file VT book. Builds _virtual_timeline + _chapter_list (one chapter per
    file at its cumulative start), and sets _file_offset for the current file."""
    timeline = []
    chapters = []
    cum = 0.0
    for dur in file_durations:
        timeline.append({"file_path": f"f{len(timeline)}.mp3",
                         "cumulative_start": cum, "duration": dur})
        chapters.append({"time": cum})
        cum += dur
    player._virtual_timeline = timeline
    player._chapter_list = chapters
    player._file_offset = timeline[current_index]["cumulative_start"]
    player._current_vt_index = current_index
    player._last_nonvt_chapter = -1
    player._last_vt_chapter = -1


# --------------------------------------------------------------------------- #
# invariant 1 — seek settle clears the flag, INCLUDING backward seeks
# --------------------------------------------------------------------------- #
def test_settle_clears_is_seeking_forward_non_vt():
    p = make_player()
    setup_non_vt(p, [0.0, 100.0, 200.0])
    got = capture_chapters(p)
    p._is_seeking = True
    p._seek_target = 150.0
    # far from target — still seeking, and the seek does not clear yet
    p._on_time_pos_change("time-pos", 120.0)
    assert p._is_seeking is True
    assert p._seek_target == 150.0
    # within 1.0 of target — settles, then the SAME call re-walks and emits the
    # landed chapter (ch1). The -1 reset's purpose is exactly to force that fresh
    # emit on settle, so post-call _last_nonvt_chapter is the landed index, not -1.
    p._on_time_pos_change("time-pos", 150.2)
    assert p._is_seeking is False
    assert p._seek_target is None
    assert p._last_nonvt_chapter == 1     # landed chapter emitted after the reset
    assert got[-1] == 1                    # the clean settle emit fired


def test_settle_clears_on_BACKWARD_seek_non_vt():
    """The regression case: user dragged backward, target < current position.
    b6a4023's early-return starved this — the settle never fired, slider froze."""
    p = make_player()
    setup_non_vt(p, [0.0, 100.0, 200.0])
    p._cached_time_pos = 180.0       # currently near end of ch1
    p._is_seeking = True
    p._seek_target = 40.0            # sought backward into ch0
    # descending samples toward the backward target
    p._on_time_pos_change("time-pos", 120.0)
    assert p._is_seeking is True     # not yet landed
    p._on_time_pos_change("time-pos", 40.3)
    assert p._is_seeking is False    # MUST settle on the backward landing
    assert p._seek_target is None


def test_settle_clears_on_BACKWARD_seek_vt():
    """Same backward-seek settle, in a VT book and global coordinate space."""
    p = make_player()
    setup_vt(p, [1000.0, 1000.0, 1000.0], current_index=1)  # _file_offset = 1000
    p._cached_time_pos = 800.0       # local 800 → global 1800
    p._is_seeking = True
    p._seek_target = 1200.0          # global target in file 1 (local 200)
    p._on_time_pos_change("time-pos", 500.0)   # global 1500, far
    assert p._is_seeking is True
    p._on_time_pos_change("time-pos", 200.2)   # global 1200.2, lands
    assert p._is_seeking is False
    assert p._seek_target is None


# --------------------------------------------------------------------------- #
# invariant 2 — the pipeline is never starved (cache tracks every sample)
# --------------------------------------------------------------------------- #
def test_cached_time_pos_tracks_every_sample():
    p = make_player()
    setup_non_vt(p, [0.0, 100.0])
    for v in (10.0, 10.1, 10.2, 9.9, 10.3):  # includes a tiny backward blip
        p._on_time_pos_change("time-pos", v)
        assert p._cached_time_pos == v   # never freezes, every sample


def test_cached_time_pos_updates_on_backward_seek_landing():
    """The exact freeze symptom: after a backward seek lands, the cache must hold the
    NEW (lower) position, not the stale high one."""
    p = make_player()
    setup_vt(p, [1000.0, 1000.0], current_index=1)
    p._cached_time_pos = 800.0
    p._is_seeking = True
    p._seek_target = 1100.0
    p._on_time_pos_change("time-pos", 100.5)   # global 1100.5, lands
    assert p._cached_time_pos == 100.5         # cache followed the landing
    assert p._is_seeking is False


def test_post_backward_seek_samples_not_starved_non_vt():
    """THE regression catcher. b6a4023 early-returned when (not is_seeking and
    _seek_target is None) on a backward GLOBAL jump — which is precisely the state of
    the samples that arrive AFTER a backward seek settles. Those samples sit at the
    new (lower) position while the last-accepted-high value lingers, so the buggy
    guard dropped them ALL → cache froze, chapter went stale, -00:00 remaining.

    Here: settle a backward seek, then feed continued playback samples at the new low
    position and assert the cache keeps tracking and the chapter keeps resolving."""
    p = make_player()
    setup_non_vt(p, [0.0, 100.0, 200.0])
    got = capture_chapters(p)
    p._cached_time_pos = 180.0            # was near end of ch1
    p._is_seeking = True
    p._seek_target = 40.0                 # sought back into ch0
    p._on_time_pos_change("time-pos", 40.2)    # lands → settles, is_seeking False
    assert p._is_seeking is False
    # post-settle playback samples at the NEW low position (this is where b6a4023 bit)
    p._on_time_pos_change("time-pos", 40.4)
    p._on_time_pos_change("time-pos", 40.6)
    assert p._cached_time_pos == 40.6    # NOT frozen at 180 or 40.2
    assert got[-1] == 0                  # resolved to ch0 (not stuck on ch1)


def test_post_backward_seek_samples_not_starved_vt():
    """Same regression, VT/global space — the case that broke VT in the field."""
    p = make_player()
    setup_vt(p, [1000.0, 1000.0], current_index=1)   # offset 1000
    got = capture_chapters(p)
    p._cached_time_pos = 800.0           # local 800 → global 1800 (ch1)
    p._is_seeking = True
    p._seek_target = 1100.0              # global, local 100 (still ch1, lower)
    p._on_time_pos_change("time-pos", 100.2)   # lands, settles
    assert p._is_seeking is False
    p._on_time_pos_change("time-pos", 100.4)
    p._on_time_pos_change("time-pos", 100.6)
    assert p._cached_time_pos == 100.6   # cache tracking, not frozen at 800
    assert got[-1] == 1                  # chapter resolves, not stale


# --------------------------------------------------------------------------- #
# invariant 3 — chapter walk resolves + emits correctly, no spurious re-emit
# --------------------------------------------------------------------------- #
def test_non_vt_chapter_walk_and_emit():
    p = make_player()
    setup_non_vt(p, [0.0, 100.0, 200.0])
    got = capture_chapters(p)
    p._on_time_pos_change("time-pos", 50.0)    # ch0
    p._on_time_pos_change("time-pos", 150.0)   # ch1
    p._on_time_pos_change("time-pos", 160.0)   # still ch1 — no re-emit
    p._on_time_pos_change("time-pos", 205.0)   # ch2
    assert got == [0, 1, 2]


def test_non_vt_walk_uses_tolerance():
    """A position just shy of a boundary (within _CHAPTER_WALK_TOLERANCE) resolves to
    the upcoming chapter — the documented tolerance behavior."""
    p = make_player()
    setup_non_vt(p, [0.0, 100.0])
    got = capture_chapters(p)
    # 99.7 is < 100 but within 0.5 tolerance → resolves to ch1
    p._on_time_pos_change("time-pos", 100.0 - (_CHAPTER_WALK_TOLERANCE / 2))
    assert got == [1]


def test_vt_chapter_walk_global_space():
    p = make_player()
    setup_vt(p, [1000.0, 1000.0, 1000.0], current_index=1)  # offset 1000
    got = capture_chapters(p)
    # local 500 → global 1500 → file/chapter index 1
    p._on_time_pos_change("time-pos", 500.0)
    assert got == [1]


def test_vt_file_switch_resolves_new_chapter_no_freeze():
    """Simulate a VT file advance: _file_offset jumps to the next file, value resets
    to ~0. The chapter must resolve to the new file and the cache must track it —
    this is the cross-file case the (reverted) global-space fix had to protect."""
    p = make_player()
    setup_vt(p, [1000.0, 1000.0], current_index=0)   # in file 0, offset 0
    got = capture_chapters(p)
    p._on_time_pos_change("time-pos", 990.0)         # global 990, ch0
    assert got == [0]
    # advance to file 1: offset jumps, local value resets near 0
    p._file_offset = 1000.0
    p._current_vt_index = 1
    p._on_time_pos_change("time-pos", 0.5)           # global 1000.5, ch1
    assert got == [0, 1]
    assert p._cached_time_pos == 0.5                 # cache tracked the reset, no freeze


# --------------------------------------------------------------------------- #
# invariant 4 — _logical_pos: the drift fix. time_pos returns the app's BELIEVED
# position (adopted from _seek_target at settle, delta-accumulated during playback,
# resynced on discontinuity), decoupled from mpv's raw per-seek landing residual.
# See SEEK_DRIFT_MEASUREMENTS.md and the plan for the mechanism these pin.
# --------------------------------------------------------------------------- #
def test_settle_adopts_seek_target_exactly_not_raw_landing():
    """The core discard-residual invariant: on settle, _logical_pos becomes the exact
    nominal _seek_target, NOT the raw sample that triggered the settle (which lands off
    by mpv's ~0.09/0.37s residual). time_pos then returns the exact target."""
    p = make_player()
    setup_non_vt(p, [0.0, 100.0, 200.0])
    p._is_seeking = True
    p._seek_target = 150.0
    p._logical_pos = 150.0            # written at the seek site
    p._on_time_pos_change("time-pos", 120.0)      # far — still seeking
    assert p._is_seeking is True
    # settle sample OFF target by the paused-undershoot residual (0.37)
    p._on_time_pos_change("time-pos", 150.37)
    assert p._is_seeking is False
    assert p._logical_pos == 150.0                # exact target, NOT 150.37
    assert p.time_pos == 150.0                    # getter returns logical
    assert p._just_settled is True                # skip-one armed for the next sample


def test_skip_one_then_clean_accumulation():
    """The first post-settle sample is SKIPPED (does not accumulate), so the residual
    it still carries is not re-added; the second sample resumes clean lockstep."""
    p = make_player()
    setup_non_vt(p, [0.0, 100.0, 200.0])
    p._is_seeking = True
    p._seek_target = 150.0
    p._logical_pos = 150.0
    p._on_time_pos_change("time-pos", 150.37)     # settle -> logical=150.0, just_settled=True
    assert p._just_settled is True
    # first post-settle sample: raw 150.37 again (mpv sitting at its landing) -> SKIPPED
    p._on_time_pos_change("time-pos", 150.37)
    assert p._logical_pos == 150.0                # unchanged — residual not re-added
    assert p._just_settled is False               # skip consumed
    # second sample: genuine playback advance of ~0.043s from the (now-clean) baseline
    p._on_time_pos_change("time-pos", 150.413)
    assert abs(p._logical_pos - (150.0 + 0.043)) < 1e-9   # accumulated the real motion


def test_alternating_cycle_returns_to_origin():
    """The direct drift regression: N alternating forward/back seeks, each landing off
    target by the residual, must cancel — time_pos returns to the exact origin, not
    creep. (Pre-fix this compounded ~0.37s per settle toward EOF.)"""
    p = make_player()
    setup_non_vt(p, [0.0, 100000.0])          # single huge chapter, no boundary interplay
    origin = 500.0
    p._logical_pos = origin
    p._last_raw_global = origin
    p._just_settled = False
    RESIDUAL = 0.37
    for _ in range(6):
        for target in (origin + 250.0, origin):     # forward then back to origin
            p._is_seeking = True
            p._seek_target = target
            p._logical_pos = target                  # seek-site write
            # settle sample lands off by the residual (paused-style undershoot)
            p._on_time_pos_change("time-pos", target + RESIDUAL)
            # first post-settle sample (mpv still at its landing) — skipped
            p._on_time_pos_change("time-pos", target + RESIDUAL)
    assert abs(p.time_pos - origin) < 1e-9           # exact, no compounding


def test_delta_accumulation_tracks_playback():
    """Between seeks, _logical_pos advances by the summed raw deltas (not by adopting
    each raw value), and _cached_time_pos independently mirrors the raw sample."""
    p = make_player()
    setup_non_vt(p, [0.0, 100000.0])
    p._logical_pos = 10.0
    p._last_raw_global = 10.0
    p._just_settled = False
    p._is_seeking = False
    seq = [10.043, 10.086, 10.213, 10.299]
    for v in seq:
        p._on_time_pos_change("time-pos", v)
    assert abs(p._logical_pos - seq[-1]) < 1e-9      # tracked continuous playback
    assert p._cached_time_pos == seq[-1]             # co-invariant: raw mirror unchanged


def test_resync_on_implausible_delta():
    """A delta above _LOGICAL_POS_RESYNC_THRESHOLD (VT file-switch / rapid seek landing
    outside is_seeking) resyncs _logical_pos to the raw global, rather than accumulating
    a spurious jump. Fallback is NOT gated on is_seeking."""
    from fabulor.player import _LOGICAL_POS_RESYNC_THRESHOLD
    p = make_player()
    setup_non_vt(p, [0.0, 100000.0])
    p._logical_pos = 100.0
    p._last_raw_global = 90.0            # note: != _logical_pos, so accumulate would give 510
    p._just_settled = False
    p._is_seeking = False
    big = 90.0 + _LOGICAL_POS_RESYNC_THRESHOLD + 400.0   # far above threshold
    p._on_time_pos_change("time-pos", big)
    assert p._logical_pos == big         # resynced to raw, NOT 100 + (big-90)
    # negative discontinuity (rapid backward VT-style jump) while not seeking — also resyncs
    p._logical_pos = 1000.0
    p._last_raw_global = 1000.0
    p._on_time_pos_change("time-pos", 640.0)   # delta -360, not seeking, seek_target None
    assert p._logical_pos == 640.0


def test_logical_pos_survives_none_sample():
    """A transient raw time-pos of None (file boundary / pre-first-frame) must NOT
    collapse _logical_pos to None — the getter's belief persists across it (deliberate
    asymmetry vs _cached_time_pos, which DOES mirror the None)."""
    p = make_player()
    setup_non_vt(p, [0.0, 100000.0])
    p._logical_pos = 200.0
    p._last_raw_global = 200.0
    p._just_settled = False
    p._is_seeking = False
    p._on_time_pos_change("time-pos", None)
    assert p._logical_pos == 200.0       # unchanged
    assert p.time_pos == 200.0
    assert p._cached_time_pos is None    # raw mirror DID take the None
