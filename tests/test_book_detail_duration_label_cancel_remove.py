"""Regression test for _cancel_remove re-showing a stale duration.

Root-caused live 2026-09-26 (Pryme): a book with a genuinely missing duration (an excluded/
deleted book with no `duration` in its DB row) correctly shows a BLANK duration label on open
(_update_duration_label hides it when duration is falsy) — but the label's TEXT was never
cleared, only its visibility toggled. _on_close_clicked unconditionally calls _cancel_remove
on every close (not just when a remove-confirm was actually armed), and _cancel_remove used to
unconditionally do `self._duration_label.setVisible(True)` regardless of whether the CURRENT
book has a duration — so the PREVIOUS book's stale duration text reappeared, visible during the
close slide, then correctly hid again on the next open of the same (durationless) book.

Uses the same unbound-method-on-a-light-fake pattern as test_book_detail_frost_gate.py:
standing up a real BookDetailPanel needs the whole widget tree/db/config; _cancel_remove and
_update_duration_label only ever read/write a small, enumerable set of attributes off self, all
supplied here."""
import pytest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from fabulor.ui.book_detail_panel import BookDetailPanel


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeConfig:
    def __init__(self, speed=None, default_speed=1.0):
        self._speed = speed
        self._default_speed = default_speed

    def get_book_speed(self, path):
        return self._speed

    def get_default_speed(self):
        return self._default_speed


class _FakeTimer:
    def stop(self):
        pass


class _FakeStack:
    """Stands in for the real QStackedLayout _cancel_remove/_on_remove_clicked switch between
    _duration_label and _confirm_remove_label — only records the last widget made current."""

    def __init__(self):
        self.current = None

    def setCurrentWidget(self, widget):
        self.current = widget


class _FakeHost:
    """Supplies exactly what _cancel_remove / _update_duration_label read or write on self."""

    def __init__(self, duration, qapp):
        self.config = _FakeConfig()
        self._book_path = "/some/book"
        self._book_data = {"duration": duration}
        self._duration_show_adjusted = False
        self._confirming_remove = True
        self._confirm_remove_label = QLabel()
        self._confirm_remove_label.setVisible(True)
        self._duration_label = QLabel()
        # Simulate the STALE state: text left over from a PREVIOUSLY open book, hidden because
        # the current book's own duration is falsy — exactly what load_book -> _update_duration_
        # label produces for a durationless book.
        self._duration_label.setText("14h 27m")
        self._duration_label.setVisible(duration not in (None, 0, 0.0))
        self._remove_btn = QPushButton()
        self._remove_cancel_timer = _FakeTimer()
        self._theme = {}
        self.update_remove_btn_icon_calls = 0
        self._dur_save_stack = _FakeStack()

    def _update_remove_btn_icon(self, hover: bool = False):
        # _cancel_remove's icon reset — unrelated to the duration-label bug this file pins,
        # stubbed rather than exercised for real (it only touches self._remove_btn's icon via
        # load_themed_icon, real theming machinery this test doesn't need).
        self.update_remove_btn_icon_calls += 1

    _fmt = staticmethod(BookDetailPanel._fmt)
    _update_duration_label = BookDetailPanel._update_duration_label


def _cancel_remove(host):
    BookDetailPanel._cancel_remove(host)


def _update_duration_label(host):
    BookDetailPanel._update_duration_label(host)


def test_cancel_remove_keeps_duration_label_hidden_for_a_durationless_book(qapp):
    """The bug: duration=0/None (a book whose DB row genuinely has no duration) must stay
    hidden through _cancel_remove, not get force-shown with the previous book's stale text."""
    host = _FakeHost(duration=0.0, qapp=qapp)
    assert host._duration_label.isVisible() is False
    assert host._duration_label.text() == "14h 27m"  # stale, pre-fix state

    _cancel_remove(host)

    assert host._duration_label.isVisible() is False, (
        "a durationless book's label must stay hidden after _cancel_remove — "
        "re-showing it exposes the PREVIOUS book's stale text"
    )


def test_cancel_remove_shows_the_current_books_own_duration_when_it_has_one(qapp):
    """The fix must not just always hide it either — a book that DOES have a duration should
    still correctly show (and it should show ITS OWN duration/text, not whatever was stale)."""
    host = _FakeHost(duration=3600.0, qapp=qapp)
    host._duration_label.setVisible(False)  # as if hidden by some earlier state
    host._duration_label.setText("STALE OTHER BOOK TEXT")

    _cancel_remove(host)

    assert host._duration_label.isVisible() is True
    assert host._duration_label.text() == "1h 0m"  # this book's OWN duration, freshly formatted


def test_cancel_remove_always_clears_the_confirm_state(qapp):
    """_cancel_remove's other responsibilities (unrelated to the bug) must survive the fix
    unchanged: confirming_remove flag cleared, confirm label hidden, cursor reset."""
    host = _FakeHost(duration=0.0, qapp=qapp)
    assert host._confirming_remove is True

    _cancel_remove(host)

    assert host._confirming_remove is False
    assert host._confirm_remove_label.isVisible() is False


def test_update_duration_label_alone_hides_for_falsy_duration(qapp):
    """Direct pin of _update_duration_label's own contract, independent of _cancel_remove —
    the method _cancel_remove now delegates to."""
    host = _FakeHost(duration=None, qapp=qapp)
    host._duration_label.setVisible(True)
    host._duration_label.setText("STALE")

    _update_duration_label(host)

    assert host._duration_label.isVisible() is False
