"""DB contract for user-excluded books surviving a force rescan, plus the
separate is_missing flag (added later the same day to fix a ping-pong bug).

As of 2026-06-27 the upserts no longer reset is_excluded=0 — a force rescan
(upsert_books_batch / upsert_book) must KEEP an existing is_excluded=1, so the
Excluded Books section in the Library settings tab is the deliberate restore
path (db.set_book_excluded(path, False)), not an accidental side effect of a
rescan. is_deleted is still reset to 0 on upsert (location-readd resurrection is
unchanged). Both upsert variants must stay in lockstep (CLAUDE.md rule).

Also as of 2026-06-27 (later same day): is_missing is a THIRD, independent
flag for "confirmed gone from disk", separate from is_excluded (user-trash).
The two used to be conflated — mark_books_missing/_mark_book_missing wrote
is_excluded=1 — which meant restoring a missing book via the popup's eye put
a file-less row back in the library that got re-flagged missing the next
time the user tried to load it (Schrödinger's audiobook). is_missing is the
opposite of is_excluded's stickiness: it self-heals (unconditional reset on
upsert) the moment the scanner rediscovers the folder, while is_excluded
stays sticky regardless. get_excluded_books() filters out is_missing rows
entirely — there's no restore action that makes sense for a missing book.
"""
from fabulor.db import LibraryDB


def _book(path, title="T", author="A"):
    return {
        "path": path, "folder_name_raw": title, "title": title, "author": author,
        "narrator": "", "duration": 100.0, "cover_path": "", "year": None,
    }


def test_upsert_book_keeps_is_excluded(tmp_path):
    db = LibraryDB(tmp_path / "library.db")
    p = "/books/Author - Excluded One"
    db.upsert_book(_book(p))
    db.set_book_excluded(p, True)
    assert db.is_book_excluded(p)

    # Simulate a force rescan re-extracting the same path.
    db.upsert_book(_book(p))
    assert db.is_book_excluded(p), "force rescan must not un-exclude a trashed book"


def test_upsert_batch_keeps_is_excluded(tmp_path):
    db = LibraryDB(tmp_path / "library.db")
    p = "/books/Author - Excluded Two"
    db.upsert_books_batch([_book(p)])
    db.set_book_excluded(p, True)
    assert db.is_book_excluded(p)

    db.upsert_books_batch([_book(p)])
    assert db.is_book_excluded(p), "batch force rescan must not un-exclude a trashed book"


def test_upsert_clears_is_deleted(tmp_path):
    # is_deleted (location removal) is still reset by upsert — only is_excluded is sticky.
    db = LibraryDB(tmp_path / "library.db")
    loc = "/books"
    p = "/books/Author - Removed Loc"
    db.add_scan_location(loc)
    db.upsert_book(_book(p))
    db.remove_scan_location(loc)  # sets is_deleted=1 for books under loc
    assert db.get_visible_book_count() == 0

    db.upsert_books_batch([_book(p)])  # rescan rediscovers it
    assert db.get_visible_book_count() == 1, "upsert must still clear is_deleted"


def test_get_excluded_books_shape_and_filter(tmp_path):
    db = LibraryDB(tmp_path / "library.db")
    visible = "/books/Author - Visible"
    excluded = "/books/Author - Excluded"
    deleted_excluded = "/books/Author - Both Flags"
    db.upsert_books_batch([
        _book(visible, "Visible", "AuthV"),
        _book(excluded, "Excluded", "AuthE"),
        _book(deleted_excluded, "Both", "AuthB"),
    ])
    db.set_book_excluded(excluded, True)
    db.set_book_excluded(deleted_excluded, True)
    # Mark the third also is_deleted=1 (location removed) — must NOT appear.
    db.add_scan_location("/books")
    db.remove_scan_location("/books")  # sets is_deleted=1 on all three

    # Re-upsert only the first two so they're is_deleted=0 again; third stays deleted.
    db.upsert_books_batch([_book(visible, "Visible", "AuthV"),
                           _book(excluded, "Excluded", "AuthE")])

    rows = db.get_excluded_books()
    # Only `excluded` qualifies: is_excluded=1 AND is_deleted=0.
    assert rows == [(excluded, "Excluded", "AuthE")]
    # Tuple shape: (path, title, author)
    assert len(rows[0]) == 3


def test_get_excluded_books_hides_missing_rows(tmp_path):
    """The ping-pong fix: a book flagged is_missing must NOT appear in the
    Excluded Books popup even if it's also is_excluded=1 — there is no
    sensible "restore" action for a book whose folder isn't there, and
    un-excluding it anyway used to put a file-less row back in the library
    that got re-flagged the moment the user tried to load it."""
    db = LibraryDB(tmp_path / "library.db")
    excluded_only = "/books/Author - Excluded Only"
    missing_only = "/books/Author - Missing Only"
    both = "/books/Author - Both"
    db.upsert_books_batch([
        _book(excluded_only, "Excluded Only", "A1"),
        _book(missing_only, "Missing Only", "A2"),
        _book(both, "Both", "A3"),
    ])
    db.set_book_excluded(excluded_only, True)
    db.set_book_excluded(both, True)
    db.mark_books_missing([missing_only, both])

    rows = db.get_excluded_books()
    assert rows == [(excluded_only, "Excluded Only", "A1")]


def test_is_missing_self_heals_on_upsert_but_is_excluded_stays_sticky(tmp_path):
    """is_missing is the OPPOSITE of is_excluded's stickiness: a rediscovered
    folder unconditionally clears is_missing (the upsert only ever runs for
    paths the scanner found on disk, so rediscovery is unambiguous proof the
    file is back) but must NOT touch a separately-set is_excluded."""
    db = LibraryDB(tmp_path / "library.db")
    p = "/books/Author - Comes Back"
    db.upsert_book(_book(p))
    db.mark_books_missing([p])
    assert db.is_book_missing(p)

    # Folder rediscovered — scanner re-upserts the same path.
    db.upsert_book(_book(p))
    assert not db.is_book_missing(p), "upsert must self-heal is_missing"
    assert not db.is_book_excluded(p)

    # Now repeat with is_excluded also set — confirm is_missing still clears
    # while is_excluded stays sticky (the "both flags" edge case).
    db.set_book_excluded(p, True)
    db.mark_books_missing([p])
    assert db.is_book_missing(p) and db.is_book_excluded(p)

    db.upsert_books_batch([_book(p)])
    assert not db.is_book_missing(p), "is_missing self-heals even with is_excluded also set"
    assert db.is_book_excluded(p), "is_excluded stays sticky regardless of is_missing"


def test_mark_book_missing_does_not_set_is_excluded(tmp_path):
    """mark_books_missing must write is_missing, never is_excluded — this is
    the actual root-cause fix for the ping-pong bug (previously this method
    wrote is_excluded=1, indistinguishable from a real user-trash action)."""
    db = LibraryDB(tmp_path / "library.db")
    p = "/books/Author - Gone"
    db.upsert_book(_book(p))
    db.mark_books_missing([p])
    assert db.is_book_missing(p)
    assert not db.is_book_excluded(p)


def test_visibility_queries_exclude_missing_books(tmp_path):
    """is_missing must be fenced everywhere is_deleted/is_excluded already
    are — get_visible_book_count, get_all_books, has_books_with_progress,
    has_finished_books, get_finished_book_data, get_all_cover_paths,
    get_visible_book_paths_under all use the same "is this book visible"
    contract; missing a fence anywhere reintroduces a missing book into the
    visible library count/grid even though it has no file behind it."""
    db = LibraryDB(tmp_path / "library.db")
    loc = "/books"
    visible = "/books/Author - Visible"
    missing = "/books/Author - Missing"
    db.add_scan_location(loc)
    db.upsert_books_batch([
        _book(visible, "Visible", "A1"),
        _book(missing, "Missing", "A2"),
    ])
    assert db.get_visible_book_count() == 2

    db.mark_books_missing([missing])
    assert db.get_visible_book_count() == 1
    assert [b.path for b in db.get_all_books()] == [visible]
    assert db.get_visible_book_paths_under(loc) == {visible}
