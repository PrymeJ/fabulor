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


def test_cross_file_settle_adopts_logical_and_skip_one_prevents_residual_readd():
    """The Finding-2 trap (drift fix): a VT cross-file settle adopts the GLOBAL target
    into _logical_pos; the FIRST post-settle sample (mpv catching up to the target) must
    NOT re-add the landing residual via delta accumulation. Pins that the skip-one
    mechanism is what prevents 694.86 + 0.35 -> 695.21 (the compounding re-add)."""
    p = _vt_player(TIMELINE_HI)
    idx = 27
    cum = TIMELINE_HI[idx]["cumulative_start"]           # 108000.0
    _simulate_cross_file_seek(p, target_idx=idx, pending_local=0.35)
    target = 0.35 + cum
    assert p._seek_target == target
    assert p._logical_pos == target                       # adopted at the write site, GLOBAL
    # settle sample lands OFF target by a residual (global 0.30 short — mpv landed short):
    p._on_time_pos_change("time-pos", 0.05)               # global = 0.05 + foff(cum) = cum + 0.05
    assert p._is_seeking is False
    assert p._logical_pos == target                       # adopted exact target, discarded residual
    assert p._just_settled is True
    # first post-settle sample: mpv catches UP to the true target (global == target) — MUST be
    # skipped, else delta (target - settle_raw = 0.30) re-adds and logical -> target + 0.30.
    p._on_time_pos_change("time-pos", 0.35)               # global = cum + 0.35 = target
    assert p._logical_pos == target                       # NOT target + 0.30 — skip-one held
    assert p._just_settled is False
    assert p.time_pos == target


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
# Nav must never strand is_seeking (the soak-found freeze): is_seeking=True is only
# ever paired with a non-None _seek_target (seek_async sets both together, ONLY when it
# actually seeks). A genuine no-op (next_chapter past the last chapter) must seek nothing
# and set neither.
# --------------------------------------------------------------------------- #
def _chaptered_player(chapter_times):
    """Non-VT chaptered player (embedded-M4B-like): _chapter_list set, no VT."""
    p = Player(db=None, config=None)
    p._virtual_timeline = None
    p._chapter_list = [{"time": t} for t in chapter_times]
    p.instance = _FakeMpv()
    p._cached_duration = chapter_times[-1] + 100.0  # past the last chapter, for EOF guard
    return p


def test_previous_chapter_in_first_chapter_rewinds_to_start_without_stranding():
    """In the FIRST chapter, Prev rewinds to the book start (0:00) — the 2s
    restart-vs-previous threshold does not apply (no previous chapter to step to). It
    DOES seek, so is_seeking is set, but WITH a matching _seek_target (not stranded)."""
    p = _chaptered_player([0.0, 100.0, 200.0])
    p._cached_time_pos = 0.5   # within the old 2s dead zone
    p._cached_speed = 1.0
    assert p._is_seeking is False
    ret = p.previous_chapter()
    assert ret == 0.0                       # rewinds to book start
    assert p.instance.commands != []        # a seek WAS issued (no longer a no-op)
    # freeze invariant: is_seeking set ⟹ _seek_target set (settle can clear them together)
    assert p._is_seeking is True
    assert p._seek_target is not None


def test_previous_chapter_first_chapter_past_threshold_also_rewinds_to_start():
    """Even past 2s into the first chapter, Prev goes to 0:00 (restart current = start)."""
    p = _chaptered_player([0.0, 100.0, 200.0])
    p._cached_time_pos = 50.0
    p._cached_speed = 1.0
    ret = p.previous_chapter()
    assert ret == 0.0
    assert p._is_seeking is True
    assert p._seek_target is not None


def test_next_chapter_past_last_does_not_strand_is_seeking():
    p = _chaptered_player([0.0, 100.0, 200.0])
    # In the last chapter → next_chapter() is a genuine no-op; must not set is_seeking.
    p._cached_time_pos = 250.0
    p._cached_speed = 1.0
    assert p._is_seeking is False
    p.next_chapter()
    assert p._is_seeking is False
    assert p._seek_target is None
    assert p.instance.commands == []
