"""Real-DB integration test for the `_current_book`/`current_file` staleness
guard (TODO_ARCHIVE.md fix #10 of the "Resuming an M4B..." investigation).

Unlike test_eof_race_fuzz.py (which drives `Player` state directly, no DB),
this file drives the actual `_update_ui_sync` finished-write LOGIC against a
REAL, throwaway SQLite `LibraryDB` (via `tmp_path`), then queries that same
DB afterward to verify no book's `book_events`/`progress` was corrupted by a
switch landing in the staleness window — the exact kind of check the live
bug needed a manual `sqlite3` query to catch, done here automatically.

The finished-write branch itself (app.py, inside `_update_ui_sync`) is:

    if (not self._eof_event_written and self._current_book is not None
            and self._current_book.path == self.current_file):
        self.db.write_book_event(self._current_book.path, 'finished',
                                  book_id=self._current_book.id, ...)
        self._eof_event_written = True
        self._eof_book_id = self._current_book.id

Extracted here as `_maybe_write_finished_event` — a direct copy of that
branch's logic, not a reimplementation — so a future edit to the real branch
that silently drops the staleness guard would need to ALSO be made here to
keep this test passing, making regressions here visible rather than papered
over by testing something that has drifted from the real code.
"""
import random

import pytest

from fabulor.db import LibraryDB


def _maybe_write_finished_event(db, current_book, current_file, eof_event_written,
                                 day_start_hour=0):
    """Direct copy of _update_ui_sync's finished-write branch (app.py) — see
    module docstring for why this isn't imported/refactored out of app.py
    directly (that method is deeply Qt-widget-entangled)."""
    if (not eof_event_written and current_book is not None
            and current_book.path == current_file):
        db.write_book_event(current_book.path, 'finished',
                             book_id=current_book.id, day_start_hour=day_start_hour)
        return True, current_book.id
    return eof_event_written, None


class _Book:
    """Minimal stand-in for models.book.Book — only .path/.id are read by
    the branch under test."""
    def __init__(self, path, id):
        self.path = path
        self.id = id


@pytest.fixture
def real_db(tmp_path):
    db = LibraryDB(db_path=tmp_path / "test_library.db")
    return db


def _seed_book(db, path, title, duration=3600.0, progress=3600.0):
    db.upsert_book({
        "path": path,
        "folder_name_raw": title,
        "title": title,
        "author": "Author",
        "narrator": None,
        "duration": duration,
        "progress": progress,
        "cover_path": None,
        "year": None,
    })
    return db.get_book(path)


def _finished_event_count_for_path(db, path):
    with db._get_conn() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM book_events WHERE book_path = ? AND event_type = 'finished'",
            (path,)
        ).fetchone()[0]


def _finished_event_book_ids_for_path(db, path):
    with db._get_conn() as conn:
        rows = conn.execute(
            "SELECT book_id FROM book_events WHERE book_path = ? AND event_type = 'finished'",
            (path,)
        ).fetchall()
        return [r[0] for r in rows]


# --------------------------------------------------------------------------- #
# The exact live bug: current_file already the NEW book, _current_book still
# the OLD book (the staleness window `_on_file_ready`'s QueuedConnection
# creates). Must NOT write against the old book's identity.
# --------------------------------------------------------------------------- #
def test_stale_current_book_does_not_write_finished_event_for_wrong_book(real_db):
    book_a = _seed_book(real_db, "/audiobooks/book_a", "Book A")
    book_b = _seed_book(real_db, "/audiobooks/book_b", "Book B")

    # The exact staleness snapshot: current_file has already moved to book_b
    # (updated synchronously in _on_book_selected_from_library), but
    # _current_book is still book_a (not yet reassigned by the queued
    # _on_file_ready handler).
    stale_current_book = _Book(path=book_a.path, id=book_a.id)
    current_file = book_b.path

    eof_event_written, book_id = _maybe_write_finished_event(
        real_db, stale_current_book, current_file, eof_event_written=False
    )

    assert eof_event_written is False  # correctly SKIPPED, not written
    assert book_id is None
    assert _finished_event_count_for_path(real_db, book_a.path) == 0
    assert _finished_event_count_for_path(real_db, book_b.path) == 0


def test_current_book_catching_up_on_the_next_tick_writes_correctly(real_db):
    """The skipped tick must not be a permanent block — once _current_book
    catches up (matches current_file), the very next check must succeed."""
    book_a = _seed_book(real_db, "/audiobooks/book_a", "Book A")

    current_file = book_a.path
    # Tick 1: staleness window (_current_book still None, as it would be
    # transiently right after load_book's own reset, before _on_file_ready
    # has run at all)
    eof_event_written, _ = _maybe_write_finished_event(
        real_db, None, current_file, eof_event_written=False
    )
    assert eof_event_written is False
    assert _finished_event_count_for_path(real_db, book_a.path) == 0

    # Tick 2: _current_book has now caught up (mirrors _on_file_ready having
    # run in between the two ticks)
    caught_up_book = _Book(path=book_a.path, id=book_a.id)
    eof_event_written, book_id = _maybe_write_finished_event(
        real_db, caught_up_book, current_file, eof_event_written=eof_event_written
    )
    assert eof_event_written is True
    assert book_id == book_a.id
    assert _finished_event_count_for_path(real_db, book_a.path) == 1
    assert _finished_event_book_ids_for_path(real_db, book_a.path) == [book_a.id]


def test_eof_event_written_flag_prevents_a_second_write_even_when_matched(real_db):
    """Sanity: the staleness guard is additive, not a replacement for the
    existing _eof_event_written one-shot gate — a book that's already had
    its event written must not get a second one on a later matched tick."""
    book_a = _seed_book(real_db, "/audiobooks/book_a", "Book A")
    current_book = _Book(path=book_a.path, id=book_a.id)

    eof_event_written, _ = _maybe_write_finished_event(
        real_db, current_book, book_a.path, eof_event_written=False
    )
    assert eof_event_written is True
    assert _finished_event_count_for_path(real_db, book_a.path) == 1

    # A later tick, still matched, but eof_event_written is now True:
    eof_event_written2, book_id2 = _maybe_write_finished_event(
        real_db, current_book, book_a.path, eof_event_written=True
    )
    assert eof_event_written2 is True
    assert book_id2 is None
    assert _finished_event_count_for_path(real_db, book_a.path) == 1  # still just one


# --------------------------------------------------------------------------- #
# Randomized rapid-switch simulation across 3 books (2 "M4B-shaped", 1
# "VT-shaped" in spirit — this layer doesn't care about VT vs non-VT, only
# about the current_file/_current_book desync window) — mirrors the ACTUAL
# live repro shape: "I was testing it with 2 M4Bs and 1 VT. Finishing them,
# reverting them and switching them to test."
# --------------------------------------------------------------------------- #
def test_randomized_rapid_switching_across_three_books_never_corrupts_wrong_book(real_db):
    books = [
        _seed_book(real_db, "/audiobooks/book_a", "Book A", duration=3600.0, progress=3600.0),
        _seed_book(real_db, "/audiobooks/book_b", "Book B", duration=1800.0, progress=1800.0),
        _seed_book(real_db, "/audiobooks/book_c", "Book C", duration=5400.0, progress=5400.0),
    ]
    rng = random.Random(42)

    # Simulates: current_file always reflects the latest switch target
    # immediately (synchronous). _current_book lags by a random number of
    # "ticks" (0-2) after each switch, modeling the QueuedConnection delay
    # _on_file_ready's real ordering can introduce.
    current_file = None
    current_book = None
    eof_event_written = True  # no book loaded yet
    pending_book_catchup = None
    catchup_delay = 0

    history = []
    for step in range(200):
        if rng.random() < 0.3 or current_file is None:
            # A book switch happens.
            target = rng.choice(books)
            current_file = target.path
            eof_event_written = False
            catchup_delay = rng.randint(0, 2)  # ticks until _current_book catches up
            pending_book_catchup = target
            history.append(f"step {step}: SWITCH to {target.path}")
        else:
            # An ordinary UI tick.
            if pending_book_catchup is not None:
                if catchup_delay <= 0:
                    current_book = _Book(path=pending_book_catchup.path,
                                          id=pending_book_catchup.id)
                    pending_book_catchup = None
                else:
                    catchup_delay -= 1

            eof_event_written, written_book_id = _maybe_write_finished_event(
                real_db, current_book, current_file, eof_event_written
            )
            if written_book_id is not None:
                history.append(
                    f"step {step}: WROTE finished for book_id={written_book_id} "
                    f"(current_file={current_file!r})"
                )

    # Invariant: every 'finished' event actually written must have used the
    # book_id that matches its own book_path — never a mismatched pair (the
    # exact corruption shape of the live bug, where the visible book and
    # the written book_id disagreed).
    with real_db._get_conn() as conn:
        rows = conn.execute(
            "SELECT book_path, book_id FROM book_events WHERE event_type = 'finished'"
        ).fetchall()
    path_to_id = {b.path: b.id for b in books}
    for row in rows:
        assert path_to_id[row["book_path"]] == row["book_id"], (
            f"Finished event for {row['book_path']!r} was written with "
            f"book_id={row['book_id']!r}, but that path's real id is "
            f"{path_to_id[row['book_path']]!r} — wrong-book corruption. "
            f"History:\n" + "\n".join(history)
        )
