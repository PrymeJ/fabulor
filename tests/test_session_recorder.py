"""Flush-on-close contract for ``SessionRecorder.close()``.

Pins the invariant violated by the ``_on_book_removed`` ordering bug (app.py):
a session with ``listened >= 60`` and a VALID book MUST be flushed to the DB when
``close()`` is called. The bug nulled ``_current_book`` BEFORE calling ``close()``,
so its ``get_book_fn`` lambda returned ``None`` and the ``book is not None`` guard
silently discarded every active session on book/path removal — data loss for long
sessions. close() reads the book through get_book_fn at call time, so the caller
must keep the book valid until after close() returns.

These tests need a QApplication because SessionRecorder builds QTimers.
"""
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
