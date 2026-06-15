"""Sanity checks: a Player can be constructed and driven with NO mpv, NO event loop.

If these fail, the rest of the seek-state suite can't run — they prove the harness's
core assumption (Player is a pure-ish state machine off the mpv instance).
"""
from fabulor.player import Player


def test_player_constructs_without_mpv():
    p = Player(db=None, config=None)
    assert p.instance is None  # mpv is deferred; never created in tests
    assert p._cached_time_pos is None
    assert p._is_seeking is False


def test_on_time_pos_change_updates_cache_without_mpv():
    p = Player(db=None, config=None)
    p._on_time_pos_change("time-pos", 12.5)
    assert p._cached_time_pos == 12.5


def test_chapter_changed_signal_fires_without_event_loop():
    p = Player(db=None, config=None)
    # Non-VT chapter list set directly (shadows the instance-reading property).
    p._chapter_list = None  # ensure property path is what we exercise below
    p._virtual_timeline = None
    received = []
    p.chapter_changed.connect(received.append)
    # With a populated _chapter_list the walk runs and emits synchronously.
    p._chapter_list = [{"time": 0.0}, {"time": 100.0}]
    p._virtual_timeline = None  # CUE-like: chapter_list set, no VT
    p._last_nonvt_chapter = -1
    p._on_time_pos_change("time-pos", 150.0)
    assert received == [1]  # synchronous emit, no QApplication needed
