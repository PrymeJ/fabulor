"""Flush-on-close contract for ``SessionRecorder.close()``.

Pins the invariant violated by the ``_on_book_removed`` ordering bug (app.py):
a session with ``listened >= 60`` and a VALID book MUST be flushed to the DB when
``close()`` is called. The bug nulled ``_current_book`` BEFORE calling ``close()``,
so its ``get_book_fn`` lambda returned ``None`` and the ``book is not None`` guard
silently discarded every active session on book/path removal — data loss for long
sessions. close() reads the book through get_book_fn at call time, so the caller
must keep the book valid until after close() returns.

Also pins ``_recover_checkpoint``'s ``session_end`` contract: a stranded checkpoint
(app crashed/killed before ``close()`` cleared it) must recover using the
checkpoint file's own mtime as ``session_end``, never ``datetime.now()`` at
recovery time — see CLAUDE.md / NOTES.md 2026-08-22 for the corruption this
caused (a session that actually stopped near midnight was recovered on a later
relaunch and stamped with that relaunch's wall-clock time as session_end,
wrongly attributing the day to the streak grid and smearing listened_seconds
across every clock-hour in between in the hourly heatmap).

These tests need a QApplication because SessionRecorder builds QTimers.
"""
import json
import os
from datetime import datetime, timedelta

import pytest
from PySide6.QtWidgets import QApplication

from fabulor.session_recorder import SessionRecorder


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeBook:
    id = 1
    path = "/books/long-one"
    title = "Long One"
    author = "Author"
    duration = 36000.0


class _FakeDB:
    """Captures write_session calls; db_path.parent is a tmp dir for the checkpoint."""
    def __init__(self, tmp_path):
        self.db_path = tmp_path / "library.db"
        self.sessions = []

    def write_session(self, **kwargs):
        self.sessions.append(kwargs)

    def get_book_started_at(self, book_id):
        return None

    def set_started_at(self, book_id, when):
        pass


def _make_recorder(tmp_path, book):
    db = _FakeDB(tmp_path)
    rec = SessionRecorder(
        db=db,
        get_position_fn=lambda: 1000.0,
        get_book_fn=lambda: book,
    )
    return rec, db


def test_close_flushes_session_with_valid_book_and_60s(qapp, tmp_path):
    """>= 60s listened + valid book → exactly one session is written."""
    book = _FakeBook()
    rec, db = _make_recorder(tmp_path, book)
    rec.open()
    # Force a clearly-over-threshold listened total without real wall-clock waiting:
    # backdate the segment start so close()'s accumulate adds > 60s.
    rec._session_segment_start = datetime.now() - timedelta(seconds=120)

    t = rec.close()
    if t is not None:
        t.join(timeout=2.0)

    assert len(db.sessions) == 1, "valid book + >=60s must flush exactly one session"
    assert db.sessions[0]["book_id"] == book.id
    assert db.sessions[0]["listened_seconds"] >= 60
    assert not rec.is_active


def test_close_discards_when_book_is_none(qapp, tmp_path):
    """The ordering bug, frozen: book None at close() time → discarded even at >=60s.

    This is the exact failure the app.py reorder prevents. It is NOT a desired
    behavior to rely on — it documents WHY close() must be called before the book
    is nulled. Defect B (sub-60s discard) is intentional and unrelated.
    """
    rec, db = _make_recorder(tmp_path, None)
    rec.open()
    rec._session_segment_start = datetime.now() - timedelta(seconds=120)

    t = rec.close()
    if t is not None:
        t.join(timeout=2.0)

    assert db.sessions == [], "book None at close() time must discard (ordering-bug shape)"


def test_recover_checkpoint_uses_file_mtime_not_now(qapp, tmp_path):
    """A stranded checkpoint must recover with session_end derived from the
    checkpoint file's mtime (last real write, ~30s cadence while the session
    was open), not datetime.now() at recovery time — which could be hours or
    days later and would corrupt the streak grid / hourly heatmap."""
    db_path = tmp_path / "library.db"
    checkpoint_path = tmp_path / "session_checkpoint.json"

    session_start = datetime(2026, 8, 21, 22, 59, 52, 213310)
    stale_mtime = datetime(2026, 8, 21, 23, 6, 30)  # ~last real checkpoint write
    data = {
        "book_id": 1,
        "book_path": "/books/long-one",
        "book_title": "Long One",
        "book_author": "Author",
        "book_duration": 36000.0,
        "session_start": session_start.isoformat(),
        "position_start": 100.0,
        "furthest_position": 200.0,
        "listened_seconds": 132.29,
    }
    checkpoint_path.write_text(json.dumps(data), encoding="utf-8")
    stale_ts = stale_mtime.timestamp()
    os.utime(checkpoint_path, (stale_ts, stale_ts))

    db = _FakeDB(tmp_path)
    rec = SessionRecorder(
        db=db,
        get_position_fn=lambda: 1000.0,
        get_book_fn=lambda: _FakeBook(),
    )
    # _recover_checkpoint's write happens on a daemon thread; give it a moment.
    import time
    for _ in range(50):
        if db.sessions:
            break
        time.sleep(0.05)

    assert len(db.sessions) == 1
    recovered_end = db.sessions[0]["session_end"]
    assert recovered_end == stale_mtime, (
        f"session_end must equal the checkpoint file's mtime ({stale_mtime}), "
        f"not recovery-time now() — got {recovered_end}"
    )
    # session_end must never precede session_start even under clock skew.
    assert recovered_end >= db.sessions[0]["session_start"]


def test_recover_checkpoint_unlinks_synchronously_before_write_completes(qapp, tmp_path):
    """The checkpoint file must be gone the instant _recover_checkpoint's
    synchronous portion returns, NOT only after the daemon write thread's
    finally block runs. Otherwise a second process launched in quick
    succession (e.g. an entr-style kill/relaunch dev loop, which never runs
    closeEvent/clear_checkpoint) can see the same still-present checkpoint
    and recover it AGAIN as a duplicate session before the first recovery's
    write thread has had a chance to unlink it. Found live 2026-08-22/23:
    dozens of duplicate listening_sessions rows from exactly this race —
    see NOTES.md. This test does NOT wait for the write thread at all —
    the file must already be gone by the time __init__ returns."""
    db_path = tmp_path / "library.db"
    checkpoint_path = tmp_path / "session_checkpoint.json"

    data = {
        "book_id": 1,
        "book_path": "/books/long-one",
        "book_title": "Long One",
        "book_author": "Author",
        "book_duration": 36000.0,
        "session_start": datetime(2026, 8, 22, 19, 0, 0).isoformat(),
        "position_start": 100.0,
        "furthest_position": 200.0,
        "listened_seconds": 200.0,
    }
    checkpoint_path.write_text(json.dumps(data), encoding="utf-8")

    db = _FakeDB(tmp_path)
    SessionRecorder(
        db=db,
        get_position_fn=lambda: 1000.0,
        get_book_fn=lambda: _FakeBook(),
    )

    assert not checkpoint_path.exists(), (
        "checkpoint must be unlinked synchronously during __init__, before "
        "the write thread's DB call — a second immediate relaunch must never "
        "be able to see (and re-recover) this same checkpoint file"
    )
