"""Book Detail Stats tab: which rows show in each book state, and the "Added" date's UTC→local
conversion. Drives the real BookDetailPanel against a temp DB (same setup as
test_grab_exclude_by_move.py's _real_panel)."""
from datetime import datetime, timezone

import pytest
from PySide6.QtWidgets import QApplication, QWidget


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _panel(qapp, tmp_path, sessions=0, finishes=0):
    from unittest.mock import MagicMock
    from fabulor.db import LibraryDB
    from fabulor.ui.book_detail_panel import BookDetailPanel
    db = LibraryDB(str(tmp_path / "t.db"))
    db.upsert_book({'path': '/x/book', 'folder_name_raw': 'A - T', 'title': 'T', 'author': 'A',
                    'narrator': None, 'duration': 3600.0, 'progress': None,
                    'cover_path': None, 'year': None})
    book = db.get_book_dict('/x/book')
    for i in range(sessions):
        db.write_session('/x/book', 'T', 'A', 3600.0, datetime(2026, 10, i + 1, 10),
                         datetime(2026, 10, i + 1, 11), 0.0, 600.0, 600.0, 600.0,
                         book_id=book['id'])
    for _ in range(finishes):
        db.write_book_event('/x/book', 'finished', book_id=book['id'], source='manual')
    cfg = MagicMock()
    cfg.get_book_speed.return_value = None
    cfg.get_default_speed.return_value = 1.0
    cfg.get_book_eq_mode.return_value = "global"
    cfg.get_day_start_hour.return_value = 0
    mw = QWidget()
    mw.setFixedSize(300, 564)
    bdp = BookDetailPanel(db, cfg, parent=mw)
    bdp.setGeometry(0, 32, 300, 532)
    mw.show()
    qapp.processEvents()
    bdp.load_book(dict(book))
    qapp.processEvents()
    return mw, bdp


def _visible_keys(bdp):
    keys = bdp._stat_keys + [bdp._added_key, bdp._added_started_key]
    return [k.text() for k in sorted((k for k in keys if k.isVisibleTo(bdp)), key=lambda k: k.y())]


@pytest.mark.parametrize("sessions, finishes, expected", [
    (0, 0, ["Remaining", "Total listened", "Sessions", "Added"]),
    (2, 0, ["Remaining", "Total listened", "Sessions", "Last session", "Added", "Started"]),
    (2, 1, ["Remaining", "Total listened", "Sessions", "Last session", "Added · Started",
            "Finished"]),
    (2, 2, ["Remaining", "Total listened", "Sessions", "Last session", "Added · Started",
            "Finished"]),
    # Manual finish with no listening: no Started to merge with, so Added stays alone.
    (0, 1, ["Remaining", "Total listened", "Sessions", "Added", "Finished"]),
])
def test_visible_rows_per_state(qapp, tmp_path, sessions, finishes, expected):
    mw, bdp = _panel(qapp, tmp_path, sessions, finishes)
    assert _visible_keys(bdp) == expected
    mw.close()


def test_merged_row_joins_added_and_started(qapp, tmp_path):
    mw, bdp = _panel(qapp, tmp_path, sessions=1, finishes=1)
    assert bdp._added_started_label.text() == (
        f"{bdp._added_label.text()} · {bdp._stat_labels[4].text()}")
    assert bdp._stat_labels[4].text() == "Oct 1, 2026"
    mw.close()


def test_date_added_is_converted_from_utc_to_local():
    from fabulor.ui.book_detail_panel import BookDetailPanel
    raw = "2026-10-29 23:30:00"
    local = datetime(2026, 10, 29, 23, 30, tzinfo=timezone.utc).astimezone()
    assert BookDetailPanel._fmt_date_added(raw) == f"{local.strftime('%b')} {local.day}, {local.year}"
    assert BookDetailPanel._fmt_date_added(None) == "—"


@pytest.mark.parametrize("first, second", [((2, 0), (0, 0)), ((0, 0), (2, 0))],
                         ids=["more_rows_then_fewer", "fewer_rows_then_more"])
def test_rows_are_in_place_before_the_slide_in_grab(qapp, tmp_path, first, second):
    """The slide-in grabs the panel right after load_book, before the event loop runs any
    queued layout pass. Rows must already be where they settle, or the slide shows the
    previous book's row positions (spread out or overlapping)."""
    mw, bdp = _panel(qapp, tmp_path, *first)
    db = bdp.db
    db.upsert_book({'path': '/x/second', 'folder_name_raw': 'B - U', 'title': 'U', 'author': 'B',
                    'narrator': None, 'duration': 3600.0, 'progress': None,
                    'cover_path': None, 'year': None})
    book = db.get_book_dict('/x/second')
    for i in range(second[0]):
        db.write_session('/x/second', 'U', 'B', 3600.0, datetime(2026, 9, i + 1, 10),
                         datetime(2026, 9, i + 1, 11), 0.0, 600.0, 600.0, 600.0, book_id=book['id'])
    keys = lambda: bdp._stat_keys + [bdp._added_key, bdp._added_started_key]
    positions = lambda: [(k.text(), k.y()) for k in sorted(
        (k for k in keys() if k.isVisibleTo(bdp)), key=lambda k: k.y())]
    bdp.hide()
    bdp.load_book(dict(book))
    bdp.layout().activate()                       # what _start_book_detail_entry does
    at_grab = positions()
    bdp.show()
    qapp.processEvents()
    assert at_grab == positions()
    mw.close()
