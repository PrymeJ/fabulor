"""Force-rescan missing-book detection contract for ``ScannerWorker.run_scan``.

Pins the behavior added 2026-06-26, revised 2026-06-27: a book whose folder is
physically deleted from disk must be flagged ``is_missing=1`` (NOT ``is_excluded``,
NOT hard-deleted, NOT ``is_deleted``) on a FORCE rescan — same dedicated-flag
semantics as ``app.py``'s ``_mark_book_missing`` — so it leaves the visible library
but survives in Stats and self-heals (is_missing clears automatically) the next
time a scan rediscovers the folder. Originally this used ``is_excluded`` (the same
flag the user-trash flow uses); that caused a ping-pong bug — un-excluding a missing
book via the Excluded Books popup put a file-less row back in the library, which
got re-flagged the next time the user tried to load it. ``is_missing`` is a separate
flag specifically to avoid that — see CLAUDE.md and NOTES.md, 2026-06-27.

Load-bearing guards these tests pin:
  * runs ONLY on ``force_refresh=True`` (a non-force scan must never flag anything);
  * scoped to walked (reachable) locations only — an offline/unmounted location
    (its root does not ``exists()``) must NOT have its books flagged missing;
  * a transient per-folder ``OSError`` during discovery must not read as "gone".

The scanner emits Qt signals (``progress``/``finished``); ``run_scan`` itself can be
called directly on the worker without a running event loop — the signal emits are
no-ops without connected slots, which is fine here.
"""
import os
from pathlib import Path

import pytest

from fabulor.db import LibraryDB
from fabulor.library.scanner import ScannerWorker


def _make_book_folder(parent: Path, name: str) -> Path:
    d = parent / name
    d.mkdir(parents=True)
    # One real audio file so Phase 1 discovers it as a book folder.
    (d / "track.mp3").write_bytes(b"\x00")
    return d


@pytest.fixture
def env(tmp_path):
    """A DB + one scan location holding two indexed, visible books on disk."""
    db = LibraryDB(tmp_path / "library.db")
    loc = tmp_path / "audiobooks"
    loc.mkdir()
    db.add_scan_location(str(loc))

    keep = _make_book_folder(loc, "Author - Keep Me")
    gone = _make_book_folder(loc, "Author - Delete Me")
    for d in (keep, gone):
        db.upsert_book({
            "path": str(d), "folder_name_raw": d.name,
            "title": d.name, "author": "Author",
            "narrator": "", "duration": 100.0, "cover_path": "", "year": None,
        })
    assert db.get_visible_book_count() == 2
    return db, str(loc), str(keep), str(gone)


def test_force_rescan_flags_deleted_folder(env, tmp_path):
    db, loc, keep, gone = env
    # Physically remove one book's folder.
    os.remove(Path(gone) / "track.mp3")
    Path(gone).rmdir()

    worker = ScannerWorker(str(db.db_path), force_refresh=True, locations=[loc])
    worker.run_scan()

    assert db.is_book_missing(gone), "deleted folder must be flagged is_missing"
    assert not db.is_book_missing(keep), "present folder must stay visible"
    assert db.get_visible_book_count() == 1
    # Soft-delete only: the row (and its stats lineage) survives, NOT hard-deleted.
    assert db.get_book(gone) is not None


def test_non_force_scan_does_not_flag_deleted_folder(env, tmp_path):
    db, loc, keep, gone = env
    os.remove(Path(gone) / "track.mp3")
    Path(gone).rmdir()

    worker = ScannerWorker(str(db.db_path), force_refresh=False, locations=[loc])
    worker.run_scan()

    # A routine (non-force) scan must never flag a missing book — only the
    # explicit Rescan button (force) is allowed to mutate flags.
    assert not db.is_book_missing(gone)
    assert db.get_visible_book_count() == 2


def test_offline_location_does_not_flag_its_books(env, tmp_path):
    db, loc, keep, gone = env
    # Simulate the whole location going offline: its root no longer exists, but
    # its books are still indexed and visible in the DB. A force rescan that
    # can't reach the root must NOT flag every book under it as missing.
    import shutil
    shutil.rmtree(loc)
    assert not Path(loc).exists()

    worker = ScannerWorker(str(db.db_path), force_refresh=True, locations=[loc])
    worker.run_scan()

    assert not db.is_book_missing(keep)
    assert not db.is_book_missing(gone)
    assert db.get_visible_book_count() == 2


def test_transient_iterdir_error_is_not_treated_as_missing(env, tmp_path, monkeypatch):
    db, loc, keep, gone = env
    # Make the audio-presence check raise for the "gone" folder only — simulating
    # a flaky mount / permission hiccup, NOT a deleted folder. It must be recorded
    # in skipped_dirs and excluded from the missing diff, so it stays visible.
    real_iterdir = Path.iterdir

    def flaky_iterdir(self):
        if str(self) == gone:
            raise OSError("simulated transient I/O error")
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", flaky_iterdir)

    worker = ScannerWorker(str(db.db_path), force_refresh=True, locations=[loc])
    worker.run_scan()

    assert not db.is_book_missing(gone), \
        "a transient per-folder I/O error must not flag the book missing"
    assert db.get_visible_book_count() == 2


# --- _on_scan_finished teardown predicate (library_controller.py) ------------
#
# The scan-finished handler tears down the currently-loaded book when it is no
# longer in the library. Both flags are independent, legitimate reasons:
#   - is_missing=1  : force rescan found the folder gone from disk (this file's
#                     scanner tests above prove that flag gets written);
#   - is_excluded=1 : user trashed the book, possibly while it was playing.
# The teardown check is `is_book_missing(current) or is_book_excluded(current)`.
# Before the 2026-06-27 flag split, missing-detection wrote is_excluded, so the
# old `is_book_excluded`-only check happened to cover both; it no longer does.
# These pin the predicate directly (no Qt / controller wiring needed) so the two
# trigger flags can't silently drift apart again.

def _teardown_triggered(db, path) -> bool:
    """Mirror of the boolean evaluated at library_controller.py:_on_scan_finished."""
    return db.is_book_missing(path) or db.is_book_excluded(path)


def test_teardown_predicate_true_for_missing_book(env):
    db, loc, keep, gone = env
    db.mark_books_missing([gone])
    assert _teardown_triggered(db, gone), \
        "a book flagged is_missing must trigger the scan-finished teardown"
    assert not _teardown_triggered(db, keep)


def test_teardown_predicate_true_for_excluded_book(env):
    # Regression guard for the manually-tested path that must NOT break: excluding
    # the currently-loaded book still triggers teardown.
    db, loc, keep, gone = env
    db.set_book_excluded(gone, True)
    assert _teardown_triggered(db, gone), \
        "an excluded book must still trigger the scan-finished teardown"
    assert not _teardown_triggered(db, keep)


def test_teardown_predicate_false_for_visible_book(env):
    db, loc, keep, gone = env
    assert not _teardown_triggered(db, keep)
    assert not _teardown_triggered(db, gone)
