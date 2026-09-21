"""Regression net for `MainWindow._restore_position`'s near-EOF branch.

Live bug (2026-09-19, TODO.md's "Resuming an M4B after unfinishing it freezes the
app"): a book saved at/near its own duration (left at 100% via natural EOF, then
reselected in the library) froze the whole app on the next Play.

Root cause: `_restore_position` pre-set `self.player.is_seeking = True`
immediately before calling into `seek_async` (directly for non-VT, or via
`defer_vt_restore` -> `_on_file_loaded` -> `seek_async` once mpv confirms load,
for VT). `seek_async`'s own near-EOF guard ("too close to EOF — let natural EOF
handle it") silently no-ops in exactly this case — it returns before ever
reaching the `self.is_seeking = True` / `self._seek_target = pos` assignment it
normally makes together. The caller's pre-set is left stranded: `is_seeking`
stuck `True` with `_seek_target` permanently `None`, which
`_on_time_pos_change`'s settle branch can never clear (it requires
`_seek_target is not None`). Separately, a race between mpv's async `duration`
population and this call could let a genuine `command_async('seek', ...)` land
inside mpv's own documented ~2s EOF hang zone.

A FIRST fix attempt just skipped the seek call and left it at that — wrong,
found live: mpv loads every fresh file at position 0 regardless (or, for VT, at
the start of whichever file the saved position falls in), so skipping the seek
silently reset the visible position to 0%/chapter-start instead of leaving it at
its true saved 100%. The CORRECT fix synthesizes the same `_eof = True` state
`_advance_or_finish` sets on genuine natural completion — no mpv command of any
kind — which `_update_ui_sync`'s existing `is_eof` branch already renders
correctly every tick regardless of mpv's actual (irrelevant) position.

These tests drive `MainWindow._restore_position` directly against a fake `self`
carrying only the state that method reads — no QApplication, no real mpv, same
shape as test_book_detail_panel_keys.py's fake-panel pattern this session.
"""
import types

from fabulor.app import MainWindow
from fabulor.models.book import Book


class _FakePlayer:
    def __init__(self, virtual_timeline=None):
        self._virtual_timeline = virtual_timeline
        self._eof = False
        self._logical_pos = None
        self._cached_time_pos = None
        self.is_seeking = None
        self.seek_calls = []
        self.defer_vt_restore_calls = []

    @property
    def time_pos(self):
        # Mirrors Player.time_pos's real getter contract: _logical_pos wins when
        # set, falling back to raw _cached_time_pos otherwise. This is the exact
        # value _save_current_progress (app.py) reads and writes back to the DB
        # on the next switch-away — the real mechanism behind the "goes to 0%"
        # DB-corruption bug this fake exists to catch.
        return self._logical_pos if self._logical_pos is not None else self._cached_time_pos

    def seek_async(self, pos):
        # Mirrors seek_async's real contract for the cases these tests exercise:
        # only the near-EOF guard matters here, so this fake only models THAT
        # branch's actual behavior (an unconditional no-op return, is_seeking/
        # _seek_target/_logical_pos left untouched) rather than the full method.
        self.seek_calls.append(pos)
        self.is_seeking = True
        self._seek_target = pos
        self._logical_pos = pos  # matches the real seek_async's own assignment

    def defer_vt_restore(self, pos):
        self.defer_vt_restore_calls.append(pos)

    def set_volume_from_slider(self, v):
        pass


class _FakeConfig:
    def get_last_position(self, path):
        return 0.0  # no live Config cache to layer on top of the DB value

    def get_book_speed(self, path):
        return None

    def get_default_speed(self):
        return 1.0


class _FakeDB:
    def __init__(self, book):
        self._book = book
        self.update_progress_calls = []

    def get_book(self, path):
        return self._book

    def update_progress(self, path, pos):
        self.update_progress_calls.append((path, pos))


class _FakeVolumeSlider:
    def value(self):
        return 100


class _FakeMainWindow:
    def __init__(self, book, virtual_timeline=None):
        self.player = _FakePlayer(virtual_timeline)
        self.config = _FakeConfig()
        self.db = _FakeDB(book)
        self.current_file = book.path
        self.volume_slider = _FakeVolumeSlider()
        self.audio_tab = None
        self.set_speed_calls = []
        # Mirrors _on_file_ready's real reset ordering: _eof_event_written = False
        # runs immediately before _restore_position is called (app.py:2293/2296),
        # so these tests start from that same freshly-reset state.
        self._eof_event_written = False
        self._eof_book_id = None

    def _set_speed(self, value, save=True):
        self.set_speed_calls.append((value, save))


def _restore(mw):
    # Call the real, unbound MainWindow._restore_position against the fake —
    # no QApplication/QWidget construction needed, since the method only ever
    # touches attributes on self, none of which require a real Qt object.
    MainWindow._restore_position(mw)


# --------------------------------------------------------------------------- #
# the exact reported bug: a book saved at/near its own duration (non-VT)
# --------------------------------------------------------------------------- #
def test_book_saved_at_eof_does_not_call_seek_async():
    book = Book(path="book.m4b", duration=3600.0, progress=3600.0)
    mw = _FakeMainWindow(book)

    _restore(mw)

    assert mw.player.seek_calls == []


def test_book_saved_at_eof_leaves_is_seeking_false_not_stuck_true():
    book = Book(path="book.m4b", duration=3600.0, progress=3600.0)
    mw = _FakeMainWindow(book)

    _restore(mw)

    # The core regression: before the fix, is_seeking was pre-set True and then
    # never cleared (seek_async's near-EOF guard never ran to set _seek_target,
    # so the settle branch could never fire). After the fix, is_seeking must
    # never have been set True in the first place for this call.
    assert mw.player.is_seeking is False


def test_book_saved_at_eof_synthesizes_eof_flag_instead_of_resetting_to_zero():
    # The corrected fix, not just "no freeze": a first fix attempt merely
    # skipped the seek, which left mpv (and the UI) at its natural fresh-load
    # position of 0 instead of the book's true saved 100% — this is what must
    # NOT happen. _eof=True is what _update_ui_sync's existing branch already
    # renders correctly as "finished" every tick, with no mpv command involved.
    book = Book(path="book.m4b", duration=3600.0, progress=3600.0)
    mw = _FakeMainWindow(book)

    _restore(mw)

    assert mw.player._eof is True


def test_book_saved_within_two_seconds_of_duration_also_skips_seek():
    # Not exactly at duration — a book that finished with a fraction of a
    # second of silence/credits left, well inside the documented mpv EOF
    # hang zone. Same guard threshold seek_async's own near-EOF check uses.
    book = Book(path="book.m4b", duration=3600.0, progress=3599.2)
    mw = _FakeMainWindow(book)

    _restore(mw)

    assert mw.player.seek_calls == []
    assert mw.player.is_seeking is False
    assert mw.player._eof is True


# --------------------------------------------------------------------------- #
# reselecting an already-finished book must NOT re-trigger the "just now
# finished" side effect (duplicate DB event + revert-prompt banner) — live
# bug, 2026-09-21: "Revert the finished status, load another book, come
# back, it asks again whether to revert... it finishes it again just
# because it is going back to 100% although it wasn't even playing."
# --------------------------------------------------------------------------- #
def test_book_saved_at_eof_marks_the_finished_event_already_written():
    # _update_ui_sync's is_eof branch gates the "write a finished event, show
    # the revert-prompt banner" side effect on `not self._eof_event_written`.
    # That flag is reset to False on every book load (_on_file_ready, BEFORE
    # _restore_position runs) — without marking it True again here, a mere
    # reselect of an already-finished book reads as a brand new completion.
    book = Book(path="book.m4b", duration=3600.0, progress=3600.0)
    mw = _FakeMainWindow(book)
    assert mw._eof_event_written is False  # the pre-_restore_position reset

    _restore(mw)

    assert mw._eof_event_written is True


def test_book_saved_at_eof_leaves_eof_book_id_none():
    # _eof_book_id gates the revert button/banner machinery entirely
    # (_finish_revert returns immediately if it's None) — must stay None for
    # a synthetic restore-time EOF, so no revert prompt ever arms for it.
    book = Book(path="book.m4b", duration=3600.0, progress=3600.0)
    mw = _FakeMainWindow(book)

    _restore(mw)

    assert mw._eof_book_id is None


# --------------------------------------------------------------------------- #
# the DB-corruption bug: player.time_pos must correctly report the book's
# true (saved) position for a synthesized restore-time EOF, not fall through
# to raw _cached_time_pos (which mpv leaves near 0 on every fresh file load,
# regardless of the _eof flag). Live bug, 2026-09-21: "Library not showing
# 100% anymore, there are two sources of truth. Then it incorrectly catches
# up and goes to 0% on a click on the same book or another book." Root cause:
# the NEXT switch-away calls _save_current_progress (app.py), which reads
# player.time_pos and writes it straight to the DB's progress column —
# silently overwriting the book's correct saved duration with ~0 the moment
# _logical_pos wasn't also set alongside _eof.
# --------------------------------------------------------------------------- #
def test_book_saved_at_eof_sets_logical_pos_to_the_true_duration():
    book = Book(path="book.m4b", duration=3600.0, progress=3600.0)
    mw = _FakeMainWindow(book)

    _restore(mw)

    assert mw.player._logical_pos == 3600.0
    assert mw.player.time_pos == 3600.0  # what _save_current_progress would read


def test_book_saved_at_eof_does_not_touch_cached_time_pos():
    # CLAUDE.md: "Do NOT couple a _logical_pos write to any _cached_time_pos
    # write" and "_cached_time_pos... is FILE-LOCAL for VT" — this GLOBAL
    # duration value must never be written there, for either book type.
    book = Book(path="book.m4b", duration=3600.0, progress=3600.0)
    mw = _FakeMainWindow(book)

    _restore(mw)

    assert mw.player._cached_time_pos is None


# --------------------------------------------------------------------------- #
# ordinary resume (not near EOF) must be completely unaffected
# --------------------------------------------------------------------------- #
def test_ordinary_midbook_resume_still_seeks_normally():
    book = Book(path="book.m4b", duration=3600.0, progress=1200.0)
    mw = _FakeMainWindow(book)

    _restore(mw)

    assert mw.player.seek_calls == [1200.0]
    assert mw.player.is_seeking is True
    assert mw.player._eof is False
    # This branch never touches _eof_event_written — it stays at whatever
    # _on_file_ready's own pre-call reset left it (False), not force-marked.
    assert mw._eof_event_written is False
    # _logical_pos is set by seek_async itself here (its own normal contract),
    # not by _restore_position directly — same end result, different owner.
    assert mw.player.time_pos == 1200.0


def test_book_exactly_at_the_two_second_boundary_still_seeks():
    # duration - progress == 2.0 exactly is NOT "< 2.0" — must still seek,
    # matching seek_async's own guard's strict-less-than semantics.
    book = Book(path="book.m4b", duration=3600.0, progress=3598.0)
    mw = _FakeMainWindow(book)

    _restore(mw)

    assert mw.player.seek_calls == [3598.0]
    assert mw.player.is_seeking is True
    assert mw.player._eof is False


# --------------------------------------------------------------------------- #
# no progress at all: pre-existing branch, unaffected by this fix
# --------------------------------------------------------------------------- #
def test_zero_progress_clears_is_seeking_without_seeking():
    book = Book(path="book.m4b", duration=3600.0, progress=0.0)
    mw = _FakeMainWindow(book)

    _restore(mw)

    assert mw.player.seek_calls == []
    assert mw.player.is_seeking is False
    assert mw.player._eof is False


# --------------------------------------------------------------------------- #
# VT: the identical near-EOF gap, reached via defer_vt_restore instead of a
# direct seek_async call — must be caught the same way, before the VT/non-VT
# split, not just on the non-VT arm.
# --------------------------------------------------------------------------- #
def test_vt_book_saved_at_eof_does_not_defer_a_seek_either():
    book = Book(path="book_folder", duration=3600.0, progress=3600.0)
    mw = _FakeMainWindow(book, virtual_timeline=[{"file_path": "a.mp3"}])

    _restore(mw)

    assert mw.player.seek_calls == []
    assert mw.player.defer_vt_restore_calls == []
    assert mw.player.is_seeking is False
    assert mw.player._eof is True
    assert mw._eof_event_written is True
    assert mw._eof_book_id is None
    assert mw.player._logical_pos == 3600.0
    assert mw.player.time_pos == 3600.0
    assert mw.player._cached_time_pos is None  # never coupled, VT or not


def test_vt_book_ordinary_midbook_resume_still_defers_normally():
    book = Book(path="book_folder", duration=3600.0, progress=1200.0)
    mw = _FakeMainWindow(book, virtual_timeline=[{"file_path": "a.mp3"}])

    _restore(mw)

    assert mw.player.seek_calls == []
    assert mw.player.defer_vt_restore_calls == [1200.0]
    assert mw.player.is_seeking is False
    assert mw.player._eof is False


# --------------------------------------------------------------------------- #
# the SECOND, deeper "goes to 0%" recurrence (2026-09-21, live-confirmed after
# the _logical_pos fix above was already deployed and restarted): even with
# _logical_pos correctly set to the true duration by _restore_position,
# Player._on_time_pos_change's OWN "logical-position maintenance" block
# (player.py, runs on every raw mpv time_pos sample while not is_seeking)
# unconditionally resyncs _logical_pos to the raw sample whenever
# _last_raw_global is None — which is always true immediately after a fresh
# load, since _restore_position's synthesis never touches _last_raw_global.
# mpv itself always reports ~0 as its first sample of a freshly loaded file,
# regardless of any Fabulor-side flag — so within one real observer tick,
# _logical_pos was silently dragged back from `duration` to ~0, corrupting
# the DB the moment _save_current_progress next ran. These tests exercise
# the real Player._on_time_pos_change directly (not the _FakePlayer above,
# which doesn't implement this method) to pin the fix: while _eof is True,
# this block must leave _logical_pos untouched.
# --------------------------------------------------------------------------- #
from fabulor.player import Player  # noqa: E402 (grouped with this section, not file-top imports)


def _player_synthesized_at_eof(duration):
    """Mirror exactly what _restore_position now does for a book saved at EOF."""
    p = Player(db=None, config=None)
    p._eof = True
    p.is_seeking = False
    p._logical_pos = duration
    return p


def test_first_post_restore_raw_sample_does_not_drag_logical_pos_back_to_zero():
    p = _player_synthesized_at_eof(3600.0)

    # mpv's own first observer callback after a fresh load — always near 0,
    # regardless of any Fabulor-side state. Before the fix, this alone reset
    # _logical_pos to ~0.0 within a single tick.
    p._on_time_pos_change("time-pos", 0.0)

    assert p._logical_pos == 3600.0
    assert p.time_pos == 3600.0


def test_several_post_restore_samples_all_stay_frozen_while_eof():
    p = _player_synthesized_at_eof(3600.0)

    for raw in (0.0, 0.01, 0.03, 0.1):
        p._on_time_pos_change("time-pos", raw)

    assert p._logical_pos == 3600.0
    assert p.time_pos == 3600.0


def test_raw_cached_time_pos_still_updates_unconditionally_even_while_frozen():
    # _cached_time_pos is documented as "raw, unconditional, every sample" —
    # this guard must not touch that contract, only _logical_pos.
    p = _player_synthesized_at_eof(3600.0)

    p._on_time_pos_change("time-pos", 0.0)

    assert p._cached_time_pos == 0.0


def test_logical_pos_resumes_tracking_once_eof_clears_via_a_real_seek():
    # The guard must lift the instant a real seek begins (seek_async sets
    # self._eof = False as one of its first assignments on every branch that
    # issues a seek) — this is not a permanent freeze, only a while-at-EOF one.
    p = _player_synthesized_at_eof(3600.0)
    p._on_time_pos_change("time-pos", 0.0)  # still frozen at 3600.0
    assert p._logical_pos == 3600.0

    # Simulate a real seek_async call landing (e.g. the user pressed Prev):
    p._eof = False
    p._is_seeking = True
    p._seek_target = 100.0

    p._on_time_pos_change("time-pos", 100.0)  # settle sample

    assert p._is_seeking is False
    assert p._logical_pos == 100.0


def test_natural_eof_via_advance_or_finish_is_unaffected_non_vt():
    # The guard must not change behavior for the PRE-EXISTING natural-EOF
    # case: a book that plays all the way to its own end via real playback.
    # _logical_pos should already correctly track up to ~duration through
    # ordinary accumulation before _eof ever flips True (this test primes it
    # with a settle first, matching how a real session would arrive there),
    # and freezing it at that already-correct value is the desired behavior,
    # not a regression.
    p = Player(db=None, config=None)
    p.instance = types.SimpleNamespace(command_async=lambda *a: None, chapter_list=[])
    p._is_seeking = True
    p._seek_target = 3599.0
    p._on_time_pos_change("time-pos", 3599.0)  # settle near the end
    assert p._logical_pos == 3599.0

    p._advance_or_finish()  # natural EOF completion (non-VT branch)
    assert p._eof is True

    # A further raw sample or two right at the tail must not move it.
    p._on_time_pos_change("time-pos", 3599.5)

    assert p._logical_pos == 3599.0
