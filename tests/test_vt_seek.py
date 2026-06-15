"""VT cross-file seek settle — regression for the permanent chapter-UI freeze.

Root cause (captured 2026-06-15, /tmp/fabulor_vtboth.log): `_on_file_loaded`'s
cross-file follow-up seek stored `_seek_target = pending` in LOCAL space, while the
settle in `_on_time_pos_change` compares GLOBAL `value + _file_offset`. So
`abs(global - local)` ≈ the file's cumulative_start — never < 1.0 — and `is_seeking`
stuck True forever → frozen chapter slider + remaining-time label.

Fix: store the GLOBAL target (`pending + cumulative_start`). These tests pin the
SYMPTOM: after the cross-file file-load runs, a time_pos sample AT the global target
must fire the settle and clear `is_seeking`. Both real captured cases are fixtures
(seek to file 0 / cumulative_start 0; seek to file 27 / cumulative_start 110107.1).
RED on the pre-fix LOCAL behaviour, GREEN after.
"""
import types

from fabulor.player import Player


class _FakeMpv:
    """Minimal mpv stand-in: records command_async, exposes a settable `path`."""
    def __init__(self, path=""):
        self.path = path
        self.commands = []

    def command_async(self, *args):
        self.commands.append(args)


def _vt_player(timeline):
    p = Player(db=None, config=None)
    p._virtual_timeline = timeline
    p._chapter_list = [{"time": e["cumulative_start"]} for e in timeline]
    return p


# Two files: file 0 @ cum 0 (dur 47.2), file 1 @ cum 47.2, ... file at index 2 @ cum 4263.5
TIMELINE = [
    {"file_path": "f00.mp3", "cumulative_start": 0.0, "duration": 47.2},
    {"file_path": "f01.mp3", "cumulative_start": 47.2, "duration": 4216.3},
    {"file_path": "f02.mp3", "cumulative_start": 4263.5, "duration": 4189.5},
]
# A high-offset case mirroring the captured vtidx=27 freeze.
TIMELINE_HI = [{"file_path": f"f{i:02d}.mp3",
                "cumulative_start": float(i) * 4000.0,
                "duration": 3999.0} for i in range(30)]


def _simulate_cross_file_seek(p, target_idx, pending_local):
    """Mirror seek_async's cross-file branch (state writes) + _on_file_loaded follow-up."""
    target_file = p._virtual_timeline[target_idx]
    p.instance = _FakeMpv(path=target_file["file_path"])
    # seek_async cross-file branch sets these BEFORE play():
    p._is_seeking = True
    p._seek_target = target_idx  # (value irrelevant; overwritten by _on_file_loaded)
    p._pending_local_pos = pending_local
    p._current_vt_index = target_idx
    p._file_offset = target_file["cumulative_start"]
    p._is_vt_file_switch = True
    # mpv loads the file → _on_file_loaded runs (the follow-up seek + _seek_target set):
    p._on_file_loaded(event=types.SimpleNamespace())


def test_cross_file_seek_target_is_global_file0():
    p = _vt_player(TIMELINE)
    _simulate_cross_file_seek(p, target_idx=0, pending_local=0.35)
    # GLOBAL target = pending + cumulative_start(0) = 0.35
    assert p._seek_target == 0.35
    assert p._is_seeking is True  # not yet settled
    # a time_pos sample AT the target fires the settle:
    p._on_time_pos_change("time-pos", 0.35)  # global = 0.35 + foff(0) = 0.35
    assert p._is_seeking is False
    assert p._seek_target is None


def test_cross_file_seek_target_is_global_high_offset():
    """The captured vtidx=27-style case: large cumulative_start. LOCAL target would
    leave abs(global - 0.35) ~= 110000 forever; GLOBAL target settles."""
    p = _vt_player(TIMELINE_HI)
    idx = 27
    cum = TIMELINE_HI[idx]["cumulative_start"]  # 108000.0
    _simulate_cross_file_seek(p, target_idx=idx, pending_local=0.35)
    assert p._seek_target == 0.35 + cum            # global, not local 0.35
    assert p._is_seeking is True
    # play lands at local 0.35 → global 108000.35 → within 1.0 of target → settles:
    p._on_time_pos_change("time-pos", 0.35)
    assert p._is_seeking is False
    assert p._seek_target is None


def test_local_target_would_NOT_settle_proving_the_bug():
    """Guard against regression: if _seek_target were LOCAL (the old bug), a global
    position far from it never settles. This encodes WHY the fix is needed."""
    p = _vt_player(TIMELINE_HI)
    idx = 27
    p._file_offset = TIMELINE_HI[idx]["cumulative_start"]
    p._current_vt_index = idx
    p._is_seeking = True
    p._seek_target = 0.35  # the OLD local value (simulating the bug directly)
    p._on_time_pos_change("time-pos", 0.35)  # global = 0.35 + 108000 = 108000.35
    # abs(108000.35 - 0.35) = 108000 >> 1.0 → never settles → the freeze
    assert p._is_seeking is True   # stuck — this is the bug the fix prevents


# --------------------------------------------------------------------------- #
# Boundary no-op nav must NOT strand is_seeking (the soak-found freeze).
# previous_chapter() at chapter 0 / next_chapter() past the last chapter must not
# leave is_seeking=True with _seek_target=None. The player nav methods set those via
# seek_async ONLY when they actually seek; nothing should set is_seeking on a no-op.
# --------------------------------------------------------------------------- #
def _chaptered_player(chapter_times):
    """Non-VT chaptered player (embedded-M4B-like): _chapter_list set, no VT, no mpv
    needed because the boundary path returns BEFORE any seek_async."""
    p = Player(db=None, config=None)
    p._virtual_timeline = None
    p._chapter_list = [{"time": t} for t in chapter_times]
    p.instance = _FakeMpv()
    return p


def test_previous_chapter_at_chapter0_does_not_strand_is_seeking():
    p = _chaptered_player([0.0, 100.0, 200.0])
    # Within ~first 2s of chapter 0 → "go to previous chapter" branch, but there is
    # no previous chapter → previous_chapter() must NOT seek and must NOT set is_seeking.
    p._cached_time_pos = 0.5
    p._cached_speed = 1.0
    assert p._is_seeking is False
    p.previous_chapter()
    assert p._is_seeking is False        # not stranded
    assert p._seek_target is None
    assert p.instance.commands == []     # no seek issued at the boundary


def test_next_chapter_past_last_does_not_strand_is_seeking():
    p = _chaptered_player([0.0, 100.0, 200.0])
    # In the last chapter → next_chapter() is a no-op; must not set is_seeking.
    p._cached_time_pos = 250.0
    p._cached_speed = 1.0
    assert p._is_seeking is False
    p.next_chapter()
    assert p._is_seeking is False
    assert p._seek_target is None
    assert p.instance.commands == []
