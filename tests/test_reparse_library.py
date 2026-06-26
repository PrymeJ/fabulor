"""Characterization test for db.reparse_library — does the (now UI-less) naming
pattern re-parse actually work, and does it respect lock flags?

This pins the ACTUAL behavior of reparse_library against a throwaway DB so we can
decide definitively whether the removed Naming Pattern UI was driving something
correct, partial, or broken. Findings (asserted below):

  * "Author - Title" splits raw "X - Y" as author=X, title=Y. Works.
  * "Title - Author" splits raw "X - Y" as title=X, author=Y. Works.
  * A folder name with no " - " separator sets title=raw, author="". Works.
  * It RESPECTS the *_locked flags (fixed 2026-06-27): a locked title/author
    survives a re-parse, matching upsert_book/upsert_books_batch's CASE WHEN
    guards. Mixed locks update only the unlocked field. (Before the fix it
    overwrote locked rows unconditionally — a latent data-loss bug.)
"""
from fabulor.db import LibraryDB


def _seed(db, path, folder_name_raw, title, author):
    db.upsert_book({
        "path": path, "folder_name_raw": folder_name_raw,
        "title": title, "author": author,
        "narrator": "", "duration": 1.0, "cover_path": "", "year": None,
    })


def test_reparse_author_title_pattern(tmp_path):
    db = LibraryDB(tmp_path / "library.db")
    p = "/books/Stephen King - The Shining"
    _seed(db, p, "Stephen King - The Shining", title="placeholder", author="placeholder")

    db.reparse_library("Author - Title")

    book = db.get_book(p)
    assert book.author == "Stephen King"
    assert book.title == "The Shining"


def test_reparse_title_author_pattern(tmp_path):
    db = LibraryDB(tmp_path / "library.db")
    p = "/books/The Shining - Stephen King"
    _seed(db, p, "The Shining - Stephen King", title="placeholder", author="placeholder")

    db.reparse_library("Title - Author")

    book = db.get_book(p)
    assert book.title == "The Shining"
    assert book.author == "Stephen King"


def test_reparse_no_separator(tmp_path):
    db = LibraryDB(tmp_path / "library.db")
    p = "/books/JustATitle"
    _seed(db, p, "JustATitle", title="placeholder", author="placeholder")

    db.reparse_library("Author - Title")

    book = db.get_book(p)
    assert book.title == "JustATitle"
    assert book.author == ""


def test_reparse_roundtrip_both_patterns(tmp_path):
    """Same folder name, re-parsed under each pattern, yields swapped fields."""
    db = LibraryDB(tmp_path / "library.db")
    p = "/books/A - B"
    _seed(db, p, "A - B", title="x", author="y")

    db.reparse_library("Author - Title")
    b1 = db.get_book(p)
    assert (b1.author, b1.title) == ("A", "B")

    db.reparse_library("Title - Author")
    b2 = db.get_book(p)
    assert (b2.title, b2.author) == ("A", "B")


def test_reparse_respects_both_locks(tmp_path):
    """A fully-locked row (title + author) survives a re-parse untouched."""
    db = LibraryDB(tmp_path / "library.db")
    p = "/books/Real Author - Real Title"
    _seed(db, p, "Real Author - Real Title", title="My Edited Title", author="My Edited Author")
    with db._get_conn() as conn:
        conn.execute(
            "UPDATE books SET title_locked = 1, author_locked = 1 WHERE path = ?", (p,)
        )

    db.reparse_library("Author - Title")

    book = db.get_book(p)
    # Both locked — user's edits preserved.
    assert book.title == "My Edited Title"
    assert book.author == "My Edited Author"


def test_reparse_respects_title_lock_only(tmp_path):
    """Only title locked: title preserved, author re-parsed from the folder name."""
    db = LibraryDB(tmp_path / "library.db")
    p = "/books/Folder Author - Folder Title"
    _seed(db, p, "Folder Author - Folder Title", title="My Edited Title", author="old author")
    with db._get_conn() as conn:
        conn.execute("UPDATE books SET title_locked = 1 WHERE path = ?", (p,))

    db.reparse_library("Author - Title")

    book = db.get_book(p)
    assert book.title == "My Edited Title"      # locked → kept
    assert book.author == "Folder Author"       # unlocked → re-parsed


def test_reparse_respects_author_lock_only(tmp_path):
    """Only author locked: author preserved, title re-parsed (the vice-versa case)."""
    db = LibraryDB(tmp_path / "library.db")
    p = "/books/Folder Author - Folder Title"
    _seed(db, p, "Folder Author - Folder Title", title="old title", author="My Edited Author")
    with db._get_conn() as conn:
        conn.execute("UPDATE books SET author_locked = 1 WHERE path = ?", (p,))

    db.reparse_library("Author - Title")

    book = db.get_book(p)
    assert book.author == "My Edited Author"    # locked → kept
    assert book.title == "Folder Title"         # unlocked → re-parsed
