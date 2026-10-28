"""Book Detail: an empty Narrator/Year is shown (blank) at rest, so clicking its row edits it.

They used to be hidden when empty. A hidden widget gets no clicks, so the only way in was to
click another field first. Layout must not change: the rows kept their space while hidden."""
import pytest
from unittest.mock import MagicMock
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QWidget


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def _panel(qapp, tmp_path, narrator, year):
    from fabulor.db import LibraryDB
    from fabulor.ui.book_detail_panel import BookDetailPanel
    cfg = MagicMock()
    cfg.get_book_speed.return_value = None
    cfg.get_default_speed.return_value = 1.0
    cfg.get_book_eq_mode.return_value = "global"
    tmp_path.mkdir(parents=True, exist_ok=True)
    mw = QWidget()
    mw.setFixedSize(300, 564)
    bdp = BookDetailPanel(LibraryDB(str(tmp_path / "t.db")), cfg, parent=mw)
    bdp.setGeometry(0, 32, 300, 532)
    mw.show()
    qapp.processEvents()
    bdp.load_book({'id': 1, 'path': '/x/book', 'title': 'T', 'author': 'A',
                   'narrator': narrator, 'year': year, 'duration': 3600.0, 'progress': 0.0})
    qapp.processEvents()
    return mw, bdp


def _click(qapp, widget):
    pos = QPointF(widget.width() / 2, widget.height() / 2)
    gpos = QPointF(widget.mapToGlobal(QPoint(int(pos.x()), int(pos.y()))))
    for typ in (QMouseEvent.Type.MouseButtonPress, QMouseEvent.Type.MouseButtonRelease):
        QApplication.sendEvent(widget, QMouseEvent(
            typ, pos, gpos, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier))
    qapp.processEvents()


def test_empty_fields_shown_at_rest_without_moving_the_layout(qapp, tmp_path):
    mw, full = _panel(qapp, tmp_path / "a", "N", 2000)
    rows_full = [w.geometry() for w in (full._narrator_label, full._year_label, full._duration_label)]
    mw.close()
    mw, bdp = _panel(qapp, tmp_path / "b", "", None)
    assert bdp._narrator_label.isVisible() and bdp._year_label.isVisible()
    assert not bdp._editing
    assert [w.geometry() for w in (bdp._narrator_label, bdp._year_label,
                                   bdp._duration_label)] == rows_full
    mw.close()


@pytest.mark.parametrize("field_name", ["_narrator_label", "_year_label"])
def test_clicking_an_empty_field_edits_it(qapp, tmp_path, field_name):
    mw, bdp = _panel(qapp, tmp_path, "", None)
    field = getattr(bdp, field_name)
    _click(qapp, field)
    assert bdp._editing
    assert not field.isReadOnly()
    if QApplication.focusWidget() is None:
        pytest.skip("platform gave no window focus")
    assert field.hasFocus()
    bdp._exit_edit_mode(save=False)
    qapp.processEvents()
    assert field.isVisible() and field.text() == ""
    mw.close()
