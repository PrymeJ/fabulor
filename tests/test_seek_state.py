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
