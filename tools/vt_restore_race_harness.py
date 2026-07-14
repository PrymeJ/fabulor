"""Deterministic forced-race harness for the VT restore-on-load seek fix.

Temporary, verification-only — NOT shipped. See the fix plan (referenced from
TODO.md/CLAUDE.md's VT+Undo fragile-zone rule) for the full design rationale.

This does NOT use time.sleep() or any env-var-gated delay in application code. The
real race is between two independent asynchronous events (mpv's file-loaded
completion vs. Qt's queued book_ready-consumer dispatch) that Python cannot directly
observe or control the real timing of. A sleep-based delay would only approximate
that race probabilistically — insufficient for proving the OLD code fails on EVERY
run (sub-step 1b) rather than most runs. Instead, this harness uses a fully mocked
mpv instance (`_ControllableMpv`) that reports "not yet loaded" (time_pos/duration
both None, mirroring the real captured failure signature) until explicitly told to
finish loading via `finish_load()` — making the two orderings ("seek issued before
load finishes" vs "seek issued after load finishes") fully deterministic and
reproducible by construction, not by chance.

The harness drives the REAL, unmodified `Player`/`_restore_position`-shaped logic —
it does not reimplement any of the fix's logic. `_restore_position`'s VT branch is
mirrored here (calling into `player.seek_async`/`player.defer_vt_restore` exactly as
`app.py` does) because the real `_restore_position` lives on `MainWindow`, which pulls
in the full Qt app; replicating just its VT branch against a raw `Player` instance
keeps this a pure logic test with no PySide6/QApplication dependency, matching how
`tests/test_vt_seek.py`/`tests/test_seek_state.py` already test `Player` directly.

Usage:
    python tools/vt_restore_race_harness.py

Exits 0 if all sub-steps behave as expected for whichever code is currently checked
out; prints a clear PASS/FAIL per scenario. Run once against the pre-fix commit
(via a separate git worktree) and once against the fix, per the plan's sub-steps
1a/1b/1c.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from fabulor.player import Player

# A real (tiny) file is needed: seek_async's VT same-file branch calls
# os.path.getsize() on the target file's path as part of its MP3-stop-and-load size
# check. Well under _VT_MP3_SIZE_THRESHOLD (40MB) so that branch never triggers.
_TEMP_MP3 = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
_TEMP_MP3.write(b"\x00" * 1024)
_TEMP_MP3.close()


class _ControllableMpv:
    """Mock mpv instance whose 'file loaded' state is set explicitly, not by timing.

    Before finish_load() is called: time_pos and duration are None, path is set (mpv
    has accepted the file) but nothing else is ready — mirrors the exact instrumented
    failure signature captured live (mpv_raw_time_pos=None mpv_raw_duration=None) at
    the moment the old code's premature seek command was sent.
    """

    def __init__(self):
        self.path = None
        self.time_pos = None
        self.duration = None
        self.core_idle = True
        self.pause = False
        self.commands = []
        self._loaded = False

    def play(self, path):
        # Mirrors real mpv: accepting a play() call does NOT mean the file is
        # loaded yet — path is set, but time_pos/duration stay None until
        # finish_load() is called (the equivalent of mpv's own file-loaded event).
        self.path = path
        self._loaded = False
        self.time_pos = None
        self.duration = None

    def command_async(self, *args):
        # Faithful to real mpv: a seek command issued before the file is loaded is
        # silently accepted (no exception) but has no effect — recorded here so the
        # harness can distinguish "issued while not loaded" (dropped) from "issued
        # while loaded" (takes effect).
        self.commands.append((args, self._loaded))
        if self._loaded and args[0] == 'seek':
            self.time_pos = args[1]

    def finish_load(self, duration):
        """The equivalent of mpv's real file-loaded event actually completing."""
        self._loaded = True
        self.time_pos = 0.0
        self.duration = duration


TIMELINE = [
    {"file_path": _TEMP_MP3.name, "cumulative_start": 0.0, "duration": 2759.03},
]
RESTORE_TARGET = 656.648


def _vt_player_for_restore():
    p = Player(db=None, config=None)
    p._virtual_timeline = TIMELINE
    p._chapter_list = [{"time": e["cumulative_start"]} for e in TIMELINE]
    p._current_vt_index = 0
    p.instance = _ControllableMpv()
    return p


def old_code_restore_position_vt_branch(p, target_pos):
    """Mirrors the OLD (pre-fix) app.py:_restore_position VT behavior: calls
    seek_async directly and immediately, exactly as the code did before this fix."""
    p.is_seeking = True
    p.seek_async(target_pos)


def new_code_restore_position_vt_branch(p, target_pos):
    """Mirrors the NEW (fixed) app.py:_restore_position VT behavior: defers via
    defer_vt_restore instead of seeking immediately."""
    p.is_seeking = False
    p.defer_vt_restore(target_pos)


def run_seek_first(restore_fn, label):
    """Simulates the queued book_ready consumer's restore call running BEFORE mpv's
    file-loaded event completes — the failure-inducing order, confirmed live in the
    17:02:27/17:05:53 captures. This is the ONLY order that occurs in the real app for
    a VT book's initial restore (book_ready always fires before instance.play() for
    VT books — see CLAUDE.md's book_ready invariant — so the restore is always
    requested chronologically before mpv's file-loaded event, whether or not it wins
    the race in real wall-clock terms). There is no real "restore requested after
    file-loaded" scenario to test as a control for the OLD code either, for the same
    reason — both code paths are always exercised in this same order; what differs is
    what each one DOES with that order, which is exactly what this harness checks.
    """
    p = _vt_player_for_restore()
    restore_fn(p, RESTORE_TARGET)          # restore requested (queued book_ready consumer)
    p.instance.finish_load(TIMELINE[0]["duration"])
    p._on_file_loaded(event=None)          # mpv's file-loaded event now arrives
    landed = p.instance.time_pos == RESTORE_TARGET
    print(f"  [{label}] instance.time_pos={p.instance.time_pos} landed_on_target={landed}")
    return landed


def run_natural_advance_is_noop():
    """Control for the NEW code only: a SECOND, natural VT file-advance (no restore
    pending — already consumed by the first _on_file_loaded call) must not re-seek.
    This is the real analog of "does the fix avoid Round 2's quadruple-advance
    feedback loop" — mirrors tests/test_vt_seek.py's
    test_on_file_loaded_is_a_noop_for_natural_file_advance_with_nothing_pending,
    reproduced here so the harness's own PASS/FAIL output is self-contained."""
    p = _vt_player_for_restore()
    new_code_restore_position_vt_branch(p, RESTORE_TARGET)
    p.instance.finish_load(TIMELINE[0]["duration"])
    p._on_file_loaded(event=None)  # first load: consumes the deferred restore
    commands_after_first_load = len(p.instance.commands)
    p._on_file_loaded(event=None)  # natural second file-advance: nothing pending
    no_reseek = len(p.instance.commands) == commands_after_first_load
    print(f"  [NEW natural-advance control] re-seeked_on_second_load={not no_reseek}")
    return no_reseek


def main():
    print("=== VT restore-on-load race harness ===")
    print(f"Restore target: {RESTORE_TARGET}\n")

    print("OLD (direct seek_async) code — the only order that occurs in the real app:")
    old_fails = not run_seek_first(old_code_restore_position_vt_branch, "OLD")

    print("\nNEW (deferred) code — the same real-app order:")
    new_ok = run_seek_first(new_code_restore_position_vt_branch, "NEW")

    print("\nNEW code — natural second file-advance must not re-seek (Round 2 check):")
    new_no_reconverge = run_natural_advance_is_noop()

    print("\n=== Results ===")
    print(f"1b (OLD code fails under the real book_ready-before-play() order): "
          f"{'PASS' if old_fails else 'FAIL'}")
    print(f"1c (NEW code succeeds under the same real order):                  "
          f"{'PASS' if new_ok else 'FAIL'}")
    print(f"    (NEW code: natural file-advance does not re-seek):             "
          f"{'PASS' if new_no_reconverge else 'FAIL'}")

    all_pass = old_fails and new_ok and new_no_reconverge
    print(f"\nOverall: {'PASS' if all_pass else 'FAIL'}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
