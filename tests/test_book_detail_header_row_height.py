"""Regression test: the header row's height must not depend on whether _duration_label happens
to be visible.

Root-caused live 2026-09-26 (Pryme): a book with a genuinely missing duration (an excluded/
deleted book with no `duration` in its DB row) hides _duration_label via _update_duration_label.
Without a retain-size-when-hidden policy, dur_save_row (a QHBoxLayout with no visible children in
that case — _confirm_remove_label is also normally hidden) collapsed to zero height, shrinking
meta_block's total height and pulling every row below the header (the tab bar) up with it — Pryme
reported the tab row sitting 12px higher for such a book than for every other book. Confirmed by
temporarily writing a non-zero duration into that book's DB row (reverted after) and observing the
tabs snap back to their correct position, isolating the cause to this one label's hidden-vs-shown
height. Fixed by giving _duration_label the same setRetainSizeWhenHidden(True) policy
_narrator_label/_year_label already use for the identical reason (see that code's own comment).

Constructs a real BookDetailPanel widget tree (QWidget.__init__ bypass + a direct _build_ui()
call, same escape hatch test_book_detail_panel_keys.py's _FocusSpyBookDetailPanel/
_FakeBookDetailPanel use) rather than a light fake — this bug is a genuine QLayout geometry
question (does a QHBoxLayout with a hidden retain-size-policy child report a real height?), which
only a real, laid-out Qt widget tree can actually answer. _build_ui() itself never touches
self.db/self.config (only later methods like load_book do), so no db/config fake is needed at
all for this test."""
import pytest
from PySide6.QtWidgets import QApplication

from fabulor.ui.book_detail_panel import BookDetailPanel


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _BareBookDetailPanel(BookDetailPanel):
    """Builds the real widget tree without needing db/config — see this file's own docstring."""

    def __init__(self):
        from PySide6.QtWidgets import QWidget
        QWidget.__init__(self)
        # _build_ui constructs a CoverPanel(db=self.db, ...) but never calls anything on it
        # (that only happens via CoverPanel.load_book, which this test never calls) — a bare
        # placeholder is sufficient.
        self.db = object()
        self._theme = {}
        self._is_archived = False
        self._is_excluded = False
        self._is_missing = False
        self._confirming_remove = False
        self._is_finished = False
        self._confirming_finished = False
        self._meta_state = None
        self._book_data = {}
        self._tag_display_tags = []
        import os
        self._assets_dir = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "src", "fabulor", "assets")
        )
        self.setObjectName("book_detail_panel")
        self._build_ui()
        self._ctx_menu = None


def _header_widget(panel):
    """The header QWidget _build_ui constructs and names "book_detail_header" — found by
    objectName rather than index, so this test doesn't depend on _build_ui's internal ordering
    beyond that name staying attached to the header."""
    from PySide6.QtWidgets import QWidget
    header = panel.findChild(QWidget, "book_detail_header")
    assert header is not None, "book_detail_header widget not found — _build_ui's structure changed"
    return header


def test_header_height_unchanged_by_duration_label_visibility(qapp):
    panel = _BareBookDetailPanel()
    panel.resize(300, 600)
    header = _header_widget(panel)
    header.layout().activate()
    panel.layout().activate()

    panel._duration_label.setVisible(True)
    panel._duration_label.setText("1h 0m")
    header.layout().activate()
    panel.layout().activate()
    height_with_duration = header.sizeHint().height()

    panel._duration_label.setVisible(False)
    header.layout().activate()
    panel.layout().activate()
    height_without_duration = header.sizeHint().height()

    assert height_without_duration == height_with_duration, (
        "hiding _duration_label changed the header row's height — the tab bar (and every other "
        "row below the header) would shift position depending on whether the current book has "
        "a duration, which is the exact bug this test guards against"
    )


def test_duration_label_retains_size_when_hidden(qapp):
    """Direct pin of the actual fix (the size policy), independent of the layout-height
    assertion above — if this policy is ever reverted, this fails immediately and points at the
    right line, rather than only failing the less specific height comparison above."""
    panel = _BareBookDetailPanel()
    assert panel._duration_label.sizePolicy().retainSizeWhenHidden() is True
