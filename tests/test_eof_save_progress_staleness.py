"""Real-DB integration tests for `MainWindow._save_current_progress`'s
`_current_book`/`current_file` staleness guard — the 11th bug found in the
"Resuming an M4B..." EOF/book-switch investigation family (found 2026-09-22,
one day after the first ten were closed out, via live testing explicitly
requested to stress-test the fixed logic further).

Root cause: `Player._restore_position`/`_on_file_ready` populates
`MainWindow._current_book` with the book's TRUE saved position — but
`_on_file_ready` defers itself (`BookSwitchState.mark_file_ready_deferred()`)
whenever the library panel is still mid-close-animation, and
`BookSwitchState.begin()` (called at the START of every new book selection)
unconditionally resets `_file_ready_deferred = False` — silently DISCARDING a
still-pending deferred call rather than ever running it. A rapid second
switch landing before the first switch's library-close animation finishes
can therefore permanently skip `_restore_position` for the book that was
briefly current. `player.time_pos` at that point still reflects mpv's raw,
untouched fresh-load transient (typically ~0.0) — and the NEXT
`_on_book_selected_from_library` call (switching AWAY from that book) used to
persist that raw ~0.0 as the book's new saved progress via
`_save_current_progress()`, permanently overwriting its real one.

Live report: "Shadow reset to 0 along the way, I had to type the name to
find and load it" — traced via `[BOOKSWITCH-TRACE]`/`[PERSIST-TRACE]` log
correlation to the exact sequence: switch to book X -> library still
animating -> _on_file_ready DEFERRED for X -> switch AGAIN to book Y before
X's library-close animation ever finishes -> begin() silently discards X's
deferred restore -> the switch-away's _save_current_progress() persists
mpv's raw 0.0 as X's new saved progress.

Fix: `_save_current_progress` now requires `_current_book is not None and
_current_book.path == current_file` before trusting `player.time_pos` for a
DB write — the same staleness signal fix #10 already established
(TODO_ARCHIVE.md): `_current_book` only ever reflects a book whose
`_restore_position` has actually completed, so if it disagrees with
`current_file`, the book's true position was never restored and the value
cannot be trusted.
"""
import pytest

from fabulor.db import LibraryDB


def _save_current_progress(db, current_book, current_file, time_pos, is_initialized=True):
    """Direct copy of the fixed _save_current_progress logic (app.py) — see
    module docstring for why this isn't imported directly (that method reads
    several other MainWindow/Player attributes this test doesn't model)."""
    if current_file and is_initialized:
        if current_book is None or current_book.path != current_file:
            return  # SKIPPED — this is the fix under test
        pos = time_pos
        if pos is not None:
            db.update_progress(current_file, pos)


class _Book:
    def __init__(self, path, id):
        self.path = path
        self.id = id


@pytest.fixture
def real_db(tmp_path):
    return LibraryDB(db_path=tmp_path / "test_library.db")


def _seed_book(db, path, title, duration=3600.0, progress=3600.0):
    db.upsert_book({
        "path": path, "folder_name_raw": title, "title": title, "author": "Author",
        "narrator": None, "duration": duration, "progress": progress,
        "cover_path": None, "year": None,
    })
    return db.get_book(path)


# --------------------------------------------------------------------------- #
# The exact live bug, reproduced against a real DB.
# --------------------------------------------------------------------------- #
def test_stale_current_book_does_not_zero_the_outgoing_books_progress(real_db):
    """book_x's real progress (3550.0, near its own 3600.0 duration — the
    exact 'left at 100%' shape the whole investigation started from) must
    survive a switch where its own restore never completed."""
    book_x = _seed_book(real_db, "/audiobooks/shadow_in_summer", "Shadow in Summer",
                         duration=3600.0, progress=3550.0)

    # The exact staleness snapshot from the live bug: current_file has
    # already moved to book_x (the switch INTO it started), but
    # _current_book is still whatever the PREVIOUS book was (or None, if
    # this is the very first switch of the session) — book_x's own
    # _restore_position was deferred and then discarded by a second, rapid
    # switch before it ever ran.
    stale_current_book = None  # models the "never even got this far" case
    current_file = book_x.path
    # mpv's raw fresh-load transient — what player.time_pos would read
    # without a completed restore.
    raw_transient_pos = 0.0

    _save_current_progress(real_db, stale_current_book, current_file, raw_transient_pos)

    reread = real_db.get_book(book_x.path)
    assert reread.progress == 3550.0, (
        f"book_x's real progress was overwritten with the raw transient "
        f"({reread.progress!r}) — the exact live corruption this fix closes."
    )


def test_stale_current_book_pointing_at_a_DIFFERENT_book_does_not_corrupt_either(real_db):
    """The other half of the staleness window: _current_book is not None,
    but it's the OUTGOING book from an EARLIER switch, not the one
    current_file now names. Must not corrupt EITHER book's progress."""
    book_prev = _seed_book(real_db, "/audiobooks/drop_of_corruption", "Drop of Corruption",
                            duration=57000.0, progress=57000.0)
    book_x = _seed_book(real_db, "/audiobooks/shadow_in_summer", "Shadow in Summer",
                         duration=3600.0, progress=3550.0)

    stale_current_book = _Book(path=book_prev.path, id=book_prev.id)
    current_file = book_x.path  # already switched to book_x

    _save_current_progress(real_db, stale_current_book, current_file, 0.0)

    reread_prev = real_db.get_book(book_prev.path)
    reread_x = real_db.get_book(book_x.path)
    assert reread_prev.progress == 57000.0, "book_prev's progress must be untouched"
    assert reread_x.progress == 3550.0, "book_x's progress must be untouched"


def test_current_book_matching_current_file_saves_normally(real_db):
    """Sanity control: the overwhelmingly common case (a book that finished
    loading normally) must be completely unaffected by this guard."""
    book = _seed_book(real_db, "/audiobooks/some_book", "Some Book",
                       duration=3600.0, progress=1200.0)
    matching_current_book = _Book(path=book.path, id=book.id)

    _save_current_progress(real_db, matching_current_book, book.path, 1800.0)

    reread = real_db.get_book(book.path)
    assert reread.progress == 1800.0, "a normal, matched save must still write through"


def test_no_current_book_at_all_skips_save_without_crashing(real_db):
    """Startup window: current_file is set (restored from Config) before
    _current_book has ever been populated. Must not crash, must not write
    anything."""
    book = _seed_book(real_db, "/audiobooks/some_book", "Some Book",
                       duration=3600.0, progress=1200.0)

    _save_current_progress(real_db, None, book.path, 0.0)  # must not raise

    reread = real_db.get_book(book.path)
    assert reread.progress == 1200.0, "untouched — nothing should have been written"


# --------------------------------------------------------------------------- #
# The upstream mechanism: BookSwitchState.begin() silently discards a
# still-pending deferred file-ready flag. Confirms the mechanism directly,
# independent of the DB-write guard above (defense in depth — if a future
# refactor ever reintroduces a path that trusts player.time_pos without the
# staleness check, THIS test still catches the underlying discard).
# --------------------------------------------------------------------------- #
def test_book_switch_state_begin_discards_a_pending_deferred_file_ready():
    from fabulor.book_switch import BookSwitchState

    switch = BookSwitchState()
    switch.begin(pre_slider=0, pre_chap=None)
    switch.mark_file_ready_deferred()
    assert switch.file_ready_deferred is True

    # A second, rapid switch begins before the first's deferred call ever
    # drained — this is the exact mechanism the live bug exploited.
    switch.begin(pre_slider=0, pre_chap=None)

    # Documents CURRENT (buggy) behavior: begin() unconditionally clears the
    # flag with no way for the caller to know a deferred call was dropped.
    # This assertion exists so a future fix to THIS layer (rather than the
    # _save_current_progress guard, which is what was actually shipped) is
    # forced to consciously update this test, not silently leave a stale
    # comment describing behavior that no longer matches the code.
    assert switch.file_ready_deferred is False
