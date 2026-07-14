"""Behavior contract for `MainWindow._on_vt_file_switched`'s guarded is_seeking clear.

Root cause (see NOTES.md "`_on_file_loaded`'s general 'issue a seek, then unconditionally
emit `file_switched`' race", 2026-07-13): `_on_vt_file_switched` used to clear
`player.is_seeking` unconditionally on every VT file-switch, racing the seek-settle branch
in `_on_time_pos_change` whenever a fresh seek was issued in the same `_on_file_loaded` call
that emitted `file_switched`. Confirmed via live `[FS-RACE]` instrumentation across six
input methods (wheel, arrow, seek-button, slider-click, chapter-list-click — natural
EOF-advance as the control) that the clear can win the race and orphan `_seek_target`,
corrupting `_logical_pos` from stale mid-flight mpv samples.

Fix: only clear `is_seeking` when `player._seek_target is None` — i.e. only when nothing is
genuinely pending for the settle branch to ever resolve. This is verified SAFE against both
prior (reverted) attempts at this same guard, which were tested exclusively against seeks
that could structurally never land at all (a separate, since-fixed bug) — never against a
seek proven capable of settling, which is the actual shape of this bug.

MainWindow needs mpv + the DB + the full widget tree, so — following the pattern in
test_transport_shortcuts.py / test_panel_exclusion.py — these tests bind the REAL unbound
method to a tiny fake supplying exactly the collaborator (`player.is_seeking`/`_seek_target`)
it reads.
"""
from fabulor.app import MainWindow


class _FakePlayer:
    def __init__(self, is_seeking, seek_target):
        self.is_seeking = is_seeking
        self._seek_target = seek_target


class _FakeMW:
    def __init__(self, *, is_seeking, seek_target):
        self.player = _FakePlayer(is_seeking, seek_target)


def test_clears_is_seeking_when_no_seek_pending():
    """The genuinely-necessary case: natural EOF-advance / no seek in flight —
    _seek_target is already None, so clearing is_seeking is safe and correct."""
    mw = _FakeMW(is_seeking=True, seek_target=None)
    MainWindow._on_vt_file_switched(mw)
    assert mw.player.is_seeking is False


def test_does_not_clear_is_seeking_when_a_seek_is_pending():
    """The bug this guard fixes: a fresh seek was just issued (_seek_target set) in the
    same _on_file_loaded call that emitted file_switched. The unconditional clear used to
    orphan _seek_target here; the guard must leave both untouched, letting the settle
    branch in _on_time_pos_change be the sole owner of clearing is_seeking."""
    mw = _FakeMW(is_seeking=True, seek_target=4756.657978944053)
    MainWindow._on_vt_file_switched(mw)
    assert mw.player.is_seeking is True
    assert mw.player._seek_target == 4756.657978944053


def test_noop_when_already_settled():
    """If the settle branch already ran first (is_seeking already False, _seek_target
    already None), the guarded clear is a harmless no-op — same as before."""
    mw = _FakeMW(is_seeking=False, seek_target=None)
    MainWindow._on_vt_file_switched(mw)
    assert mw.player.is_seeking is False
