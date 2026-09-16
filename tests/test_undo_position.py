"""Regression net for ``Player.save_seek_position`` / ``undo_seek``.

Live bug (2026-09-16): sitting in a short (e.g. 40s) chapter and hitting Next
repeatedly through several chapters, then Undo, landed on the first LONG
chapter's start rather than the position before the short chapter was left.

Root cause: every seek-driven call site (handle_next/handle_prev, chapter-list
click, slider release, etc.) gated its OWN call to save_seek_position on
whether THAT SINGLE seek's displacement exceeded a threshold (60s at 1x
speed). A spree of small seeks — e.g. Next through a 40s chapter, whose own
displacement never crosses 60s — could clear the threshold in aggregate
while no single press ever qualified individually. Because the gate lived at
the CALLER and skipped calling save_seek_position entirely when it failed,
the anchor was never captured on the first (non-qualifying) press; whichever
later press finally cleared 60s captured ITS OWN old_pos as the anchor — a
mid-spree position, not the position before the spree began.

Fixed by moving the distance decision into save_seek_position itself: the
anchor (_undo_pos) is now captured unconditionally on every call within a
coalescing spree (duration_limit window), and only the "should the overlay
show" decision is gated on distance — using CUMULATIVE distance from the
live anchor, not the single call's own displacement. These tests drive
save_seek_position/undo_seek directly — no mpv, no QApplication.
"""
from fabulor.player import Player


class _FakeInstance:
    def command_async(self, *a):
        pass


def make_player():
    return Player(db=None, config=None)


# --------------------------------------------------------------------------- #
# the exact reported bug: a spree of small seeks must anchor to the SPREE's
# start, not to whichever press happened to individually qualify
# --------------------------------------------------------------------------- #
def test_spree_of_small_seeks_anchors_to_spree_start():
    p = make_player()
    duration_limit = 3  # default undo_duration
    threshold = 60.0    # 60s at 1x speed, the standard gate

    # Start: sitting at 0:00 in a 40s chapter. Next -> chapter end (~40s in).
    # This single seek's displacement (40s) does NOT clear the 60s threshold.
    shown = p.save_seek_position(old_pos=0.0, new_pos=40.0,
                                  duration_limit=duration_limit, threshold=threshold)
    assert shown is False
    # But the anchor must already be captured at the spree's true start (0.0),
    # quietly, so a later qualifying press resolves back to it.
    assert p._undo_pos == 0.0

    # Next again: now in a long chapter, seeks to e.g. 300s. This SINGLE
    # press's displacement (40 -> 300 = 260s) clears the threshold on its own
    # too, but the anchor must still be the ORIGINAL 0.0, not 40.0.
    shown = p.save_seek_position(old_pos=40.0, new_pos=300.0,
                                  duration_limit=duration_limit, threshold=threshold)
    assert shown is True
    assert p._undo_pos == 0.0

    # Undo now returns to the true spree start, not the first long chapter.
    # (seek_async floors any target below 0.05 to 0.05 — pre-existing,
    # unrelated EOF-safety behavior, not part of this fix.)
    p.instance = _FakeInstance()
    p.undo_seek()
    assert p._seek_target == 0.05


def test_spree_of_many_small_seeks_all_individually_below_threshold():
    """Several short chapters in a row, none individually crossing 60s, whose
    CUMULATIVE distance from the spree start eventually does."""
    p = make_player()
    duration_limit = 3
    threshold = 60.0

    positions = [0.0, 20.0, 35.0, 55.0, 70.0]  # each step < 60s from the previous
    shown_flags = []
    for old, new in zip(positions, positions[1:]):
        shown_flags.append(
            p.save_seek_position(old, new, duration_limit, threshold=threshold)
        )

    # 0 -> 20 -> 35 -> 55: none of these individual steps exceed 60s, AND none
    # of them are more than 60s from the true anchor (0.0) either — so no
    # overlay yet, but the anchor must still be exactly 0.0.
    # 55 -> 70: cumulative distance from anchor (0.0 -> 70.0 = 70s) clears the
    # threshold, so this one shows.
    assert shown_flags == [False, False, False, True]
    assert p._undo_pos == 0.0


# --------------------------------------------------------------------------- #
# coalescing window still works as before for calls that DO individually
# qualify (regression coverage for the pre-existing behavior)
# --------------------------------------------------------------------------- #
def test_repeated_qualifying_seeks_keep_first_anchor_within_window():
    p = make_player()
    duration_limit = 3
    threshold = 60.0

    assert p.save_seek_position(0.0, 100.0, duration_limit, threshold=threshold) is True
    assert p._undo_pos == 0.0
    # A second big seek shortly after should NOT move the anchor.
    assert p.save_seek_position(100.0, 250.0, duration_limit, threshold=threshold) is True
    assert p._undo_pos == 0.0


def test_anchor_resets_once_coalescing_window_expires():
    p = make_player()
    duration_limit = 3
    threshold = 60.0

    assert p.save_seek_position(0.0, 100.0, duration_limit, threshold=threshold) is True
    assert p._undo_pos == 0.0

    # Simulate the window having expired.
    p._last_undo_click_time -= (duration_limit + 1)

    assert p.save_seek_position(500.0, 600.0, duration_limit, threshold=threshold) is True
    assert p._undo_pos == 500.0


def test_zero_threshold_always_shows():
    """threshold=0.0 (long-skip / restart-to-0 / chapter-slider-wheel call sites)
    must show on every qualifying call regardless of distance, same as before
    this fix — these call sites never had a distance gate."""
    p = make_player()
    duration_limit = 3

    assert p.save_seek_position(10.0, 10.5, duration_limit, threshold=0.0) is True


def test_duration_limit_zero_disables_undo_entirely():
    p = make_player()
    assert p.save_seek_position(0.0, 1000.0, duration_limit=0, threshold=0.0) is False
    assert p._undo_pos is None
