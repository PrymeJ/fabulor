"""Regression net for ``Player.apply_smart_rewind``.

Two bugs fixed together (see CLAUDE.md's smart-rewind section):

1. Smart rewind must be confined to the chapter playback was paused in — it must
   never rewind past that chapter's start, landing in the previous chapter. The
   original code derived "current chapter" via ``self.chapter`` (mpv's native
   property for non-VT, or a tolerance-less walk for VT) instead of the app's
   established ``chapter_list`` + ``_CHAPTER_WALK_TOLERANCE`` walk pattern (see
   CLAUDE.md's "DO NOT use self.player.chapter" rule) — these tests drive
   ``apply_smart_rewind`` directly (no mpv, no QApplication) with a fake
   ``instance`` and assert the clamp lands exactly on the chapter's own start.
2. The pending-pause timestamp (``MainWindow._last_pause_timestamp``) must be
   cleared on every book load/removal, so a rewind armed on one book can never
   fire against whatever book is loaded next — covered separately, at the
   app.py call sites, not here (this file only covers the Player-side clamp).
"""
import time

from fabulor.player import Player, _CHAPTER_WALK_TOLERANCE


class _FakeMpvInstance:
    """Minimal stand-in for python-mpv's Handle — only what seek_async touches
    on the non-VT path (no VT/cross-file play() needed for these tests)."""
    def __init__(self):
        self.seek_calls = []

    def command_async(self, *args):
        self.seek_calls.append(args)


def make_player():
    p = Player(db=None, config=None)
    p.instance = _FakeMpvInstance()
    p._play_target = "book.m4b"  # non-mp3, so seek_async's stop-and-load branch is skipped
    return p


def setup_non_vt(player, chapter_times, cached_duration=100000.0):
    player._virtual_timeline = None
    player._chapter_list = [{"time": t} for t in chapter_times]
    player._file_offset = 0.0
    player._cached_duration = cached_duration
    player._last_nonvt_chapter = -1


def setup_vt(player, file_durations, current_index, cached_time_pos):
    timeline = []
    chapters = []
    cum = 0.0
    for dur in file_durations:
        # seek_async's VT same-file branch checks os.path.exists() on the target
        # file before issuing the seek — use this test file's own real path so
        # that check passes (see _abandon_seek_missing_file).
        timeline.append({"file_path": __file__,
                         "cumulative_start": cum, "duration": dur})
        chapters.append({"time": cum})
        cum += dur
    player._virtual_timeline = timeline
    player._chapter_list = chapters
    player._file_offset = timeline[current_index]["cumulative_start"]
    player._current_vt_index = current_index
    player._cached_time_pos = cached_time_pos
    player._cached_duration = sum(file_durations)


# --------------------------------------------------------------------------- #
# confinement to the paused chapter
# --------------------------------------------------------------------------- #
def test_rewind_clamps_to_current_chapter_start_non_vt():
    p = make_player()
    # Chapters at 0, 100, 200. Paused 6s into chapter[1] (time=106).
    setup_non_vt(p, [0.0, 100.0, 200.0])
    p._cached_time_pos = 106.0
    p._logical_pos = 106.0

    # A rewind big enough to cross the chapter[1] boundary (106 - 60 = 46, well
    # before chapter[1]'s start at 100) must clamp to 100.0, not slide into
    # chapter[0].
    rewound = p.apply_smart_rewind(last_pause_ts=time.time() - 999, wait_min=1, rewind_sec=60)
    assert rewound is True
    assert p._seek_target == 100.0


def test_rewind_within_chapter_does_not_clamp():
    p = make_player()
    setup_non_vt(p, [0.0, 100.0, 200.0])
    p._cached_time_pos = 106.0
    p._logical_pos = 106.0

    # A small rewind that stays inside chapter[1] should land exactly on the
    # unclamped target.
    rewound = p.apply_smart_rewind(last_pause_ts=time.time() - 999, wait_min=1, rewind_sec=5)
    assert rewound is True
    assert p._seek_target == 101.0


def test_rewind_exactly_at_chapter_start_goes_to_zero_of_chapter():
    p = make_player()
    setup_non_vt(p, [0.0, 100.0, 200.0])
    # Paused right at the chapter boundary itself.
    p._cached_time_pos = 100.0
    p._logical_pos = 100.0

    rewound = p.apply_smart_rewind(last_pause_ts=time.time() - 999, wait_min=1, rewind_sec=30)
    assert rewound is True
    assert p._seek_target == 100.0


def test_rewind_uses_walk_tolerance_not_native_chapter_property():
    """A position a hair past a boundary (inside _CHAPTER_WALK_TOLERANCE) must
    still resolve to the chapter it nominally belongs to, matching every other
    chapter-position walk in the app (previous_chapter/next_chapter/_sync_chapter_ui)."""
    p = make_player()
    setup_non_vt(p, [0.0, 100.0, 200.0])
    boundary_fuzz = _CHAPTER_WALK_TOLERANCE / 2
    p._cached_time_pos = 100.0 - boundary_fuzz
    p._logical_pos = 100.0 - boundary_fuzz

    rewound = p.apply_smart_rewind(last_pause_ts=time.time() - 999, wait_min=1, rewind_sec=30)
    assert rewound is True
    # Resolves as chapter[1] (walk tolerance), so the clamp floor is 100.0 even
    # though raw position (99.75) is technically still in chapter[0].
    assert p._seek_target == 100.0


def test_rewind_clamps_to_current_chapter_start_vt():
    p = make_player()
    # Three VT files (chapters) of 100s/100s/100s. Currently in file/chapter 1,
    # at global position 106 (6s into that chapter).
    setup_vt(p, [100.0, 100.0, 100.0], current_index=1, cached_time_pos=6.0)
    p._logical_pos = 106.0

    rewound = p.apply_smart_rewind(last_pause_ts=time.time() - 999, wait_min=1, rewind_sec=60)
    assert rewound is True
    assert p._seek_target == 100.0


# --------------------------------------------------------------------------- #
# not-yet-due / disabled cases stay no-ops (pre-existing behavior, still correct)
# --------------------------------------------------------------------------- #
def test_no_rewind_when_wait_not_elapsed():
    p = make_player()
    setup_non_vt(p, [0.0, 100.0, 200.0])
    p._cached_time_pos = 106.0
    p._logical_pos = 106.0

    rewound = p.apply_smart_rewind(last_pause_ts=time.time(), wait_min=5, rewind_sec=30)
    assert rewound is False
    assert p._seek_target is None


def test_no_rewind_when_disabled():
    p = make_player()
    setup_non_vt(p, [0.0, 100.0, 200.0])
    p._cached_time_pos = 106.0
    p._logical_pos = 106.0

    rewound = p.apply_smart_rewind(last_pause_ts=time.time() - 999, wait_min=0, rewind_sec=30)
    assert rewound is False
    rewound = p.apply_smart_rewind(last_pause_ts=None, wait_min=5, rewind_sec=30)
    assert rewound is False
