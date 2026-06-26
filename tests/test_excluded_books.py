"""DB contract for user-excluded books surviving a force rescan.

As of 2026-06-27 the upserts no longer reset is_excluded=0 — a force rescan
(upsert_books_batch / upsert_book) must KEEP an existing is_excluded=1, so the
Excluded Books section in the Library settings tab is the deliberate restore
path (db.set_book_excluded(path, False)), not an accidental side effect of a
rescan. is_deleted is still reset to 0 on upsert (location-readd resurrection is
unchanged). Both upsert variants must stay in lockstep (CLAUDE.md rule).
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
