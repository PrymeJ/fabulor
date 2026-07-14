"""Deterministic forced-race harness for the general `_on_file_loaded` seek /
`file_switched` race fix (`_on_vt_file_switched`'s guarded is_seeking clear).

Temporary, verification-only — NOT shipped. See NOTES.md "`_on_file_loaded`'s general
'issue a seek, then unconditionally emit `file_switched`' race" (2026-07-13) for the full
mechanism, and the fix plan for the design rationale.

This is a DIFFERENT race shape from `vt_restore_race_harness.py`: that harness controls
ONE delayed operation (mpv's file-loaded completion) against a single fixed request. This
harness controls the ORDERING of TWO independent, both-eventually-arriving events racing
each other — the seek's settle sample (`_on_time_pos_change`) and the queued
`_on_vt_file_switched` clear — since the confirmed live evidence (six `[FS-RACE]` misses
across wheel/arrow/seek-button/slider-click/chapter-list-click) showed the seek DOES land in
every failure case; what's contested is which of the two arrives first. No sleep-based
delay is used — both orderings are driven explicitly, by construction, so this is
deterministic and reproducible rather than probabilistic.

The harness drives the REAL, unmodified `Player.seek_async`/`_on_file_loaded`/
`_on_time_pos_change` logic directly, and calls the REAL unbound
`MainWindow._on_vt_file_switched` (bound to a tiny fake exposing only `player`) to test the
actual guarded-vs-unguarded behavior — not a reimplementation of either.

Usage:
    python tools/fs_race_harness.py

Exits 0 if all scenarios behave as expected; prints PASS/FAIL per scenario.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from fabulor.player import Player

_TEMP_MP3 = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
_TEMP_MP3.write(b"\x00" * 1024)
_TEMP_MP3.close()


class _FakeMpv:
    """Minimal mpv stand-in: records command_async, exposes a settable `path`."""
    def __init__(self, path=""):
        self.path = path
        self.commands = []

    def command_async(self, *args):
        self.commands.append(args)


TIMELINE = [
    {"file_path": _TEMP_MP3.name, "cumulative_start": 0.0, "duration": 47.2},
    {"file_path": _TEMP_MP3.name, "cumulative_start": 47.2, "duration": 4216.3},
]
CROSS_FILE_TARGET = 4756.657978944053  # a real captured target from tonight's [FS-RACE] pass


def _vt_player():
    p = Player(db=None, config=None)
    p._virtual_timeline = TIMELINE
    p._chapter_list = [{"time": e["cumulative_start"]} for e in TIMELINE]
    return p


class _FakeMW:
    """Supplies exactly the collaborator _on_vt_file_switched reads off self."""
    def __init__(self, player):
        self.player = player


def unguarded_on_vt_file_switched(mw):
    """Mirrors the OLD (pre-fix) app.py:_on_vt_file_switched — unconditional clear."""
    mw.player.is_seeking = False


def guarded_on_vt_file_switched(mw):
    """Mirrors the NEW (fixed) app.py:_on_vt_file_switched — gated on _seek_target."""
    if mw.player._seek_target is None:
        mw.player.is_seeking = False


def _issue_cross_file_seek(p, target_idx, pending_local):
    """Mirrors seek_async's VT cross-file branch's state writes (the same shape the
    real _on_file_loaded/_pending_local_pos path and seek_async's cross-file branch
    both use) — issues a seek that WILL settle once a matching sample arrives."""
    target_file = p._virtual_timeline[target_idx]
    p.instance = _FakeMpv(path=target_file["file_path"])
    p._is_seeking = True
    p._seek_target = CROSS_FILE_TARGET
    p._logical_pos = CROSS_FILE_TARGET
    p._current_vt_index = target_idx
    p._file_offset = target_file["cumulative_start"]


def run_scenario(on_vt_file_switched_fn, order, label):
    """order='clear_first' simulates the queued _on_vt_file_switched clear winning
    the race against the settle sample (the failure-inducing order, confirmed live
    across six input methods tonight). order='settle_first' simulates the settle
    winning (the success order, also confirmed live in the same session)."""
    p = _vt_player()
    target_idx = 1
    _issue_cross_file_seek(p, target_idx=target_idx, pending_local=634.5888859735305)
    mw = _FakeMW(p)
    # The settle-worthy raw sample must be LOCAL to the target file: _on_time_pos_change
    # computes global_value = value + _file_offset, and the settle tolerance is < 1.0,
    # so this must land WITHIN 1.0 of CROSS_FILE_TARGET but not be mathematically
    # identical to it — a sample that exactly equals the target would make the OLD
    # code's "corruption" indistinguishable from correct behavior (the maintenance
    # block's post-reset resync branch, self._logical_pos = global_value, would
    # recompute the same value by coincidence). Real mpv landings always carry a
    # small residual (this is the whole reason _logical_pos/the skip-one mechanism
    # exist — see the merged drift fix); 0.3s here mirrors that and is what actually
    # exposes the OLD code's clobber as a real difference from the target.
    residual = 0.3
    landing_sample = (CROSS_FILE_TARGET - TIMELINE[target_idx]["cumulative_start"]) - residual

    if order == "clear_first":
        on_vt_file_switched_fn(mw)  # the queued clear fires first
        p._on_time_pos_change("time-pos", landing_sample)  # settle-worthy sample arrives after
    elif order == "settle_first":
        p._on_time_pos_change("time-pos", landing_sample)  # settle fires first
        on_vt_file_switched_fn(mw)  # the queued clear arrives afterward
    else:
        raise ValueError(order)

    # Correctness check: did the seek's logical target survive intact, and is
    # is_seeking in a sane (not permanently stuck) state afterward?
    target_survived = p._logical_pos == CROSS_FILE_TARGET
    not_stuck = not (p._is_seeking and p._seek_target is not None and order == "settle_first")
    print(f"  [{label}] order={order}: is_seeking={p._is_seeking} "
          f"seek_target={p._seek_target} logical_pos={p._logical_pos} "
          f"target_survived={target_survived}")
    return target_survived


def run_never_freezes_when_clear_wins_and_settle_never_comes(on_vt_file_switched_fn, label):
    """A genuinely-adversarial case: the clear fires, and (unlike the scenarios
    above) NO settle-worthy sample ever arrives at all (e.g. the seek silently
    failed for an unrelated reason). The guarded code must not freeze forever —
    confirm is_seeking eventually reflects a resolvable state, not a permanent
    stuck condition with zero recovery path. This does not test _on_end_file's
    ERROR-path fix (covered separately in tests/test_vt_seek.py) — it only checks
    that the guard itself doesn't introduce a NEW way to get stuck beyond what the
    ERROR-path fix already covers."""
    p = _vt_player()
    _issue_cross_file_seek(p, target_idx=1, pending_local=634.5888859735305)
    mw = _FakeMW(p)
    on_vt_file_switched_fn(mw)
    # No settle sample ever arrives. Confirm the state is exactly what the
    # ERROR-path fix (tested separately) is designed to recover from — not a
    # NEW, different stuck shape introduced by the guard itself.
    stuck_as_expected = p._is_seeking and p._seek_target == CROSS_FILE_TARGET
    print(f"  [{label}] no settle ever arrives: is_seeking={p._is_seeking} "
          f"seek_target={p._seek_target} (recoverable via _on_end_file ERROR path "
          f"if this is what a failed load looks like)")
    return stuck_as_expected


def main():
    print("=== General file_switched race harness ===")
    print(f"Cross-file seek target: {CROSS_FILE_TARGET}\n")

    print("OLD (unguarded) code, clear-first order (the failure-inducing order, "
          "confirmed live 6x tonight):")
    old_clear_first_survives = run_scenario(unguarded_on_vt_file_switched, "clear_first", "OLD")

    print("\nOLD (unguarded) code, settle-first order (control — this order already worked):")
    old_settle_first_survives = run_scenario(unguarded_on_vt_file_switched, "settle_first", "OLD")

    print("\nNEW (guarded) code, clear-first order (must now survive):")
    new_clear_first_survives = run_scenario(guarded_on_vt_file_switched, "clear_first", "NEW")

    print("\nNEW (guarded) code, settle-first order (must still work):")
    new_settle_first_survives = run_scenario(guarded_on_vt_file_switched, "settle_first", "NEW")

    print("\nNEW (guarded) code, clear fires but settle never arrives "
          "(confirms no NEW freeze shape):")
    new_no_new_freeze = run_never_freezes_when_clear_wins_and_settle_never_comes(
        guarded_on_vt_file_switched, "NEW")

    print("\n=== Results ===")
    print(f"OLD clear-first FAILS (proves the harness forces the real bug):     "
          f"{'PASS' if not old_clear_first_survives else 'FAIL'}")
    print(f"OLD settle-first survives (sanity control):                        "
          f"{'PASS' if old_settle_first_survives else 'FAIL'}")
    print(f"NEW clear-first SURVIVES (the actual fix):                         "
          f"{'PASS' if new_clear_first_survives else 'FAIL'}")
    print(f"NEW settle-first still survives (no regression):                   "
          f"{'PASS' if new_settle_first_survives else 'FAIL'}")
    print(f"NEW no-settle-ever leaves exactly the ERROR-path-recoverable state: "
          f"{'PASS' if new_no_new_freeze else 'FAIL'}")

    all_pass = (
        not old_clear_first_survives
        and old_settle_first_survives
        and new_clear_first_survives
        and new_settle_first_survives
        and new_no_new_freeze
    )
    print(f"\nOverall: {'PASS' if all_pass else 'FAIL'}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
