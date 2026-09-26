"""Regression test for ScannerWorker._extract_metadata silently losing duration on a real,
valid, untagged MP3.

Root-caused live 2026-09-26 (Pryme): a single-file MP3 book showed duration=0.0 in the DB with no
narrator/year either. `_extract_metadata`'s per-file loop used `if m and m.info:` to decide
whether mutagen successfully parsed a file — but `mutagen.FileType` (what `mutagen.File()`
returns) subclasses `dict` (it IS the file's tag mapping), so a real, fully-parsed, PERFECTLY
VALID file with ZERO ID3/tag data evaluates as an empty dict, and `bool(m)` is False even though
`m.info` (a genuine, non-null MPEGInfo with a real `.length`) is available. The guard silently
discarded the file's real duration whenever it simply had no tags — confirmed directly against
the real file once it was restored to disk:

    >>> m = mutagen.File(real_path)
    >>> bool(m and m.info)   # OLD condition
    False
    >>> bool(m is not None and m.info)   # NEW condition
    True
    >>> m.info.length
    14030.210612244899

The SAME failure hit four more files (Shadow Country's MP3 parts) in one rescan the very first
time scanner.py's own new [SCAN-DURATION] logging ran — this was silently losing duration data
more broadly than the one book that happened to surface it, not a one-off.

Reproduces the bug condition with a real, mutagen-parseable MP3 built from raw MPEG frame bytes
(no ffmpeg dependency, no checked-in binary fixture) — `mutagen.mp3.MPEGInfo` needs at least a
few consecutive synced frames to compute a real duration; a single correct 128kbps/44100Hz/
stereo frame header repeated is sufficient and has genuinely zero tag data (mutagen.File()
returns tags=None for it), matching the real book's file exactly (also tags=None on direct
inspection)."""
import os
from pathlib import Path

import pytest
import mutagen

from fabulor.library.scanner import ScannerWorker


def _write_untagged_mp3(path: Path) -> None:
    """A real, valid, mutagen-parseable, genuinely TAG-FREE MP3 — see this file's own docstring
    for why this exact construction reproduces the bug (not just "any MP3 without tags" — it
    must be enough consecutive valid frames for MPEGInfo to sync and compute a real duration,
    or mutagen.File() returns an object with m.info is None instead, which is a DIFFERENT,
    already-correctly-handled case)."""
    # A single valid MPEG-1 Layer III frame header: sync (11 bits) + MPEG1 + Layer3 + no-CRC,
    # 128kbps, 44100Hz, no padding, stereo.
    header = bytes([0xFF, 0xFB, 0x90, 0x00])
    frame_size = 417  # 144 * bitrate / samplerate = 144 * 128000 / 44100 ≈ 417.96 -> 417
    frame = header + bytes(frame_size - len(header))
    path.write_bytes(frame * 40)


@pytest.fixture
def untagged_mp3_book(tmp_path):
    """A book folder containing exactly one real, untagged, mutagen-parseable MP3 — the same
    shape as the real book that surfaced this bug (single MP3 file, no ID3 tags at all)."""
    book_dir = tmp_path / "Some Author - Some Untagged Book"
    book_dir.mkdir()
    mp3_path = book_dir / "Some Untagged Book.mp3"
    _write_untagged_mp3(mp3_path)
    return book_dir, mp3_path


def test_reproduces_the_bug_condition_directly(untagged_mp3_book):
    """Sanity check on the fixture itself, independent of ScannerWorker: confirms the generated
    file actually reproduces mutagen's dict-truthiness quirk this bug depended on, before trusting
    any assertion made through the scanner about it."""
    _, mp3_path = untagged_mp3_book
    m = mutagen.File(mp3_path)
    assert m is not None
    assert bool(m) is False, "fixture must reproduce mutagen's falsy-but-valid FileType object"
    assert m.info is not None
    assert m.info.length > 0


class _FakeDB:
    """Supplies exactly what _extract_metadata calls on `db` for a single-file, no-cover book —
    upsert_book_files (multi-file only, never reached here) and the cover-upsert pair (never
    reached either, since this fixture has no cover file)."""

    def upsert_book_files(self, *a, **kw):
        raise AssertionError("upsert_book_files should not be called for a single-file book")

    def get_covers_for_book(self, *a, **kw):
        raise AssertionError("get_covers_for_book should not be called with no cover file")

    def upsert_cover(self, *a, **kw):
        raise AssertionError("upsert_cover should not be called with no cover file")


def test_extract_metadata_captures_duration_from_an_untagged_mp3(untagged_mp3_book):
    book_dir, mp3_path = untagged_mp3_book
    worker = ScannerWorker(db_path=":memory:")
    result = worker._extract_metadata(book_dir, extensions={".mp3"}, db=_FakeDB())

    assert result is not None
    assert result["duration"] > 0, (
        "an untagged-but-perfectly-valid MP3's real duration must not be silently dropped — "
        "this is the exact live bug: duration stayed 0.0 for a book with no ID3 tags at all"
    )
    # Cross-check against mutagen's own reported length directly, not just "some positive number"
    m = mutagen.File(mp3_path)
    assert result["duration"] == pytest.approx(m.info.length)


def test_extract_metadata_falls_back_to_folder_name_when_tags_are_absent(untagged_mp3_book):
    """The untagged case also has no title/author tags — confirms the folder-name fallback still
    runs correctly alongside the duration fix, since both are read from the same `m`/`m.tags`."""
    book_dir, _ = untagged_mp3_book
    worker = ScannerWorker(db_path=":memory:")
    result = worker._extract_metadata(book_dir, extensions={".mp3"}, db=_FakeDB())

    assert result["author"] == "Some Author"
    assert result["title"] == "Some Untagged Book"
    assert result["narrator"] == ""


class _RecordingDB:
    """Same as _FakeDB but records upsert_book_files calls instead of asserting they never
    happen — used by the multi-file VT test below, where upsert_book_files SHOULD fire."""

    def __init__(self):
        self.upsert_book_files_calls = []

    def upsert_book_files(self, book_path, book_files):
        self.upsert_book_files_calls.append((book_path, book_files))

    def get_covers_for_book(self, *a, **kw):
        return []

    def upsert_cover(self, *a, **kw):
        pass


def test_multi_file_vt_book_keeps_every_untagged_part_in_book_files(tmp_path):
    """The real-world bug this fix closed, exactly as reported live 2026-09-26 (Pryme): a 5-part
    MP3 audiobook (Shadow Country) where only Part 1 happened to carry ID3 tags — Parts 2-5, all
    genuinely valid and playable, were silently excluded from `book_files` by the `if m` }
    truthiness bug leaving `book_files` with only 1 of 5 rows. Per CLAUDE.md's own documented VT
    logic, a `book_files` result this sparse means `Player` never builds a real virtual timeline
    for the book at all — Player.duration/chapter navigation only ever sees Part 1's ~8h18m
    instead of the full ~40h+ across all 5 parts, and the app never "stitches" the parts into one
    continuous playback the way a proper VT book does. This test pins the FIX at the exact layer
    it lives in (_extract_metadata's book_files list, which upsert_book_files receives) — it does
    not exercise Player/VT-building itself, which is a separate, already-covered layer (see
    tests/test_seek_state.py and the VT-specific tests) that only ever sees what this method
    hands it."""
    book_dir = tmp_path / "Some Author - Multi-Part Book"
    book_dir.mkdir()

    # Part 1 carries a tag (mirrors the real book: only the first file had ID3 data) — added via
    # mutagen after writing the raw frames, so this file's `bool(m)` is True and it was NEVER
    # affected by the bug; it's included here so this test's own book has the same shape as the
    # real one, not because it's the thing under test.
    part1 = book_dir / "Part1.mp3"
    _write_untagged_mp3(part1)
    tagged = mutagen.File(part1, easy=True)
    tagged["title"] = "Part 1"
    tagged.save()

    # Parts 2-5: genuinely untagged, the exact shape that silently dropped out of book_files
    # before this fix.
    other_parts = []
    for n in range(2, 6):
        p = book_dir / f"Part{n}.mp3"
        _write_untagged_mp3(p)
        other_parts.append(p)

    worker = ScannerWorker(db_path=":memory:")
    db = _RecordingDB()
    result = worker._extract_metadata(book_dir, extensions={".mp3"}, db=db)

    assert len(db.upsert_book_files_calls) == 1
    _, book_files = db.upsert_book_files_calls[0]
    assert len(book_files) == 5, (
        "all 5 parts must land in book_files, not just the one part that happened to carry a "
        "tag — a sparse book_files here is exactly what breaks VT stitching for the whole book"
    )
    # Total duration must sum ALL 5 parts, not just Part 1's.
    single_part_duration = mutagen.File(part1).info.length
    assert result["duration"] == pytest.approx(single_part_duration * 5, rel=0.01)
