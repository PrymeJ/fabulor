"""Order-independent VT restore-on-load rendezvous (see NOTES.md 2026-07-16, "Book progress
silently resetting to ~0 on rapid book-switch", Bug 2).

Root cause: `_on_file_loaded`'s VT branch only issues the restore-seek if
`_vt_restore_pending` is already set at the moment it runs. Under main-thread contention,
`_on_file_loaded` (mpv's own file-loaded event) can fire BEFORE `_restore_position` (queued off
`book_ready`/`_on_file_ready`, and can itself be delayed a further 50ms by the
library-still-animating deferred-restore path) has called `defer_vt_restore`. When that
happens the VT branch found `None`, concluded "nothing to consume," and never issued the
seek — `is_seeking` was never set `True`, so nothing downstream (including
`_on_vt_file_switched`'s `_seek_target is None` clear-gate) could tell a restore was still
owed, and `_sync_persistence` went on to persist the near-zero, file-0-start position over the
real saved one.

Fix: `Player._vt_file_loaded_awaiting_restore` is an explicit rendezvous flag, symmetric
between the two write sites, so neither has to assume which one runs first:

- `_on_file_loaded`'s VT branch: if `_vt_restore_pending` is already set, consume it (issue the
  seek) as before. If not, set `_vt_file_loaded_awaiting_restore = True` instead of concluding
  there's nothing to do.
- `defer_vt_restore`: if `_vt_file_loaded_awaiting_restore` is already `True` (the file-loaded
  branch above already ran and found nothing), issue the seek directly. Otherwise, stash
  `_vt_restore_pending` as before, for `_on_file_loaded`'s branch to consume when it runs.

These tests exercise both arrival orders directly against `Player`, following the
`_vt_player`/`_FakeMpv` pattern in `test_vt_seek.py`.
"""
import tempfile
import types

from fabulor.player import Player

# A real, persistent temp file — seek_async's VT same-file branch pre-checks os.path.exists
# (2026-07-14 missing-file fix), so the restore target's file must exist on disk.
_TEMP_MP3 = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
_TEMP_MP3.write(b"\x00" * 1024)
_TEMP_MP3.close()


class _FakeMpv:
    """Minimal mpv stand-in: records command_async, exposes a settable `path`/`pause`."""
    def __init__(self, path=""):
        self.path = path
        self.pause = False
        self.commands = []

    def command_async(self, *args):
        self.commands.append(args)


def _vt_player():
    p = Player(db=None, config=None)
    p._virtual_timeline = TIMELINE
    p._chapter_list = [{"time": e["cumulative_start"]} for e in TIMELINE]
    p._current_vt_index = 0
    p.instance = _FakeMpv(path=_TEMP_MP3.name)
    return p


# Single-file timeline is enough here — both scenarios restore within file 0 (the realistic
# "book_ready fires before instance.play() for VT books" case per the book_ready invariant in
# CLAUDE.md); cross-file restore targets aren't part of this specific race.
TIMELINE = [
    {"file_path": _TEMP_MP3.name, "cumulative_start": 0.0, "duration": 47200.0},
]

RESTORE_TARGET = 15184.71637  # a real value captured from the live Colorless Tsukuru repro


def test_file_loaded_first_then_defer_marks_and_then_restores():
    """Order A: _on_file_loaded's VT branch runs first (mpv loaded file 0) and finds no
    restore pending yet. It must mark _vt_file_loaded_awaiting_restore rather than silently
    concluding there's nothing to do. When defer_vt_restore arrives afterward, it must see
    the flag and issue the seek directly instead of stashing for a consumer that already ran."""
    p = _vt_player()

    # _on_file_loaded's VT branch runs with no _pending_local_pos (first-file load, not a
    # cross-file follow-up) and no _vt_restore_pending set yet.
    p._on_file_loaded(event=types.SimpleNamespace())

    assert p._vt_file_loaded_awaiting_restore is True
    assert p._vt_restore_pending is None
    assert p._is_seeking is False  # no seek issued yet — restore hasn't arrived
    assert p.instance.commands == []

    # defer_vt_restore arrives late.
    p.defer_vt_restore(RESTORE_TARGET)

    assert p._vt_file_loaded_awaiting_restore is False  # consumed
    assert p._vt_restore_pending is None
    assert p._is_seeking is True
    assert p._seek_target == RESTORE_TARGET
    assert p.instance.commands == [('seek', RESTORE_TARGET, 'absolute+exact')]


def test_defer_first_then_file_loaded_consumes_as_before():
    """Order B (today's assumed/normal order): defer_vt_restore arrives first and stashes
    _vt_restore_pending, since _on_file_loaded hasn't run yet (_vt_file_loaded_awaiting_restore
    is still False). When _on_file_loaded's VT branch runs, it must consume the stash and
    issue the seek exactly as it always has — unchanged behavior for this ordering."""
    p = _vt_player()

    p.defer_vt_restore(RESTORE_TARGET)

    assert p._vt_restore_pending == RESTORE_TARGET
    assert p._vt_file_loaded_awaiting_restore is False
    assert p._is_seeking is False  # stash-only; no seek issued yet
    assert p.instance.commands == []

    p._on_file_loaded(event=types.SimpleNamespace())

    assert p._vt_restore_pending is None  # consumed
    assert p._vt_file_loaded_awaiting_restore is False
    assert p._is_seeking is True
    assert p._seek_target == RESTORE_TARGET
    assert p.instance.commands == [('seek', RESTORE_TARGET, 'absolute+exact')]


def test_neither_flag_left_stuck_after_either_ordering():
    """Regression guard: whichever order ran, both rendezvous fields must end up back at
    their neutral/consumed state — a stuck True/non-None would either fire a stray seek on
    a LATER, unrelated file-load, or silently swallow a future restore."""
    p_a = _vt_player()
    p_a._on_file_loaded(event=types.SimpleNamespace())
    p_a.defer_vt_restore(RESTORE_TARGET)
    assert p_a._vt_file_loaded_awaiting_restore is False
    assert p_a._vt_restore_pending is None

    p_b = _vt_player()
    p_b.defer_vt_restore(RESTORE_TARGET)
    p_b._on_file_loaded(event=types.SimpleNamespace())
    assert p_b._vt_file_loaded_awaiting_restore is False
    assert p_b._vt_restore_pending is None


def test_load_book_resets_awaiting_restore_flag():
    """load_book's reset block must clear _vt_file_loaded_awaiting_restore, same as it
    already clears _vt_restore_pending — otherwise a stale True from an abandoned book-load
    could (in principle) leak into the next book's rendezvous. See NOTES.md for why this is
    traced-safe today (defer_vt_restore has exactly one call site, always downstream of a
    fresh load_book for the CURRENTLY loading book) — this test pins the reset itself."""
    p = Player(db=None, config=None)
    p._virtual_timeline = TIMELINE  # pretend a previous VT book was mid-restore-rendezvous
    p._vt_file_loaded_awaiting_restore = True

    p.load_book("/some/other/book/path")

    assert p._vt_file_loaded_awaiting_restore is False
    assert p._vt_restore_pending is None
