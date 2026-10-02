"""Regression test: a mouse click on a row's eye button must not scroll the Excluded Books
popup back to row 0.

Root-caused live 2026-10-02 (Pryme): clicking the eye button on any row (its own
setFocusPolicy is NoFocus — see _ExcludedRow.__init__'s own comment) still delivers a mouse
press to the QListWidget viewport underneath, and QListWidget's StrongFocus default turns that
into a genuine focusInEvent for the whole popup, with reason MouseFocusReason. ExcludedBooksPopup
.focusInEvent unconditionally forced currentRow() to 0 on every entry — correct for a KEYBOARD
entry (Tab from "Persist search filter"), but for a mouse click it visibly scrolled the list to
the top and revealed row 0's eye instead of the row actually clicked, even though the clicked
button's own `clicked` signal (closed over the correct path) still restored the right book —
reported as "click the bottom row's eye, list jumps to the top; click the SAME book again (now
that focus is already held) and it works."

Builds a real ExcludedBooksPopup (no db/app wiring needed — reload() only touches its own rows)
and drives real QFocusEvents with each reason, since this is a genuine Qt focus-handling
question that only a live QFocusEvent can answer."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFocusEvent
from PySide6.QtWidgets import QApplication

from fabulor.ui.excluded_books import ExcludedBooksPopup


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_popup(qapp, rows=5):
    popup = ExcludedBooksPopup()
    books = [(f"/book/{i}", f"Title {i}", f"Author {i}") for i in range(rows)]
    popup.reload(books)
    return popup


def test_mouse_focus_in_does_not_reset_current_row(qapp):
    popup = _make_popup(qapp)
    popup.setCurrentRow(3)
    assert popup.currentRow() == 3

    popup.focusInEvent(QFocusEvent(QFocusEvent.Type.FocusIn, Qt.FocusReason.MouseFocusReason))

    assert popup.currentRow() == 3, (
        "a mouse-driven focus-in (e.g. clicking a row's eye button) must leave the current row "
        "alone — forcing it back to row 0 is what caused the list to visibly scroll to the top "
        "instead of acting on the clicked row"
    )


def test_tab_focus_in_still_lands_on_row_zero(qapp):
    """The fix must not break the original keyboard-entry behavior this method exists for."""
    popup = _make_popup(qapp)
    popup.setCurrentRow(3)

    popup.focusInEvent(QFocusEvent(QFocusEvent.Type.FocusIn, Qt.FocusReason.TabFocusReason))

    assert popup.currentRow() == 0, (
        "keyboard (Tab) entry must still always land on row 0 — only mouse-driven focus-in "
        "should skip the reset"
    )
