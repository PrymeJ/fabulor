"""Regression net: Book Detail's backdrop grab must not tear down what the user is doing in it.

Live-reported 2026-10-20 (Pryme), Frosty and Opaque only: typing in a Book Detail metadata field
lost focus and reverted after a few seconds; the tag field's suggestion popup closed by itself;
the exclusion confirmation sometimes dismissed itself. Cause: PanelManager's 10s frost refresh
calls frost_panel_backdrop -> TransportBarBlurOverlay._grab_and_blur, which HID Book Detail to
photograph the backdrop behind it. That hide fires the panel's real hideEvent (Book Detail's
exits edit mode with save=False, cancels armed confirms), moves Qt focus off the panel, and
closes the completer popup.

Fix: `exclude_by_move=True` (frost_panel_backdrop always passes it) parks the panel past the
grabbed rect instead of hiding it. These tests drive the REAL _grab_and_blur (unbound, on a light
fake `self` — standing up a full TransportBarBlurOverlay needs MainWindow) against real widgets.

The hide-path test is the control: it must reproduce the bug, which proves the same assertions
in the move-path test are capable of failing (a test that cannot fail proves nothing)."""
import pytest
from PySide6.QtCore import QRect, QStringListModel
from PySide6.QtWidgets import QApplication, QCompleter, QLabel, QLineEdit, QWidget

from fabulor.ui.transport_bar_blur import TransportBarBlurOverlay


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _Panel(QWidget):
    """Counts hide/show events — Book Detail's teardown lives in its hideEvent."""
    def __init__(self, parent):
        self.hide_events = 0
        self.show_events = 0
        super().__init__(parent)

    def hideEvent(self, event):
        # getattr: Qt can deliver a hide during interpreter teardown, after attrs are gone.
        self.hide_events = getattr(self, "hide_events", 0) + 1
        super().hideEvent(event)

    def showEvent(self, event):
        self.show_events = getattr(self, "show_events", 0) + 1
        super().showEvent(event)


class _FakeOverlayHost:
    """Exactly what _grab_and_blur reads off self on the blur=False path."""
    def __init__(self, main_window, panel):
        self.main_window = main_window
        self._common_ancestor = main_window  # identity mapping: rects are main_window space
        self._active_panel = panel
        self._overlay = QLabel(main_window)
        self._overlay.hide()
        self._grab_suppress_until = 0.0

    def _all_tracked_widgets(self):
        return []


def _build(qapp):
    mw = QWidget()
    mw.setFixedSize(300, 564)
    mw.setStyleSheet("background: rgb(0, 0, 255);")
    panel = _Panel(mw)
    panel.setGeometry(0, 32, 300, 532)
    panel.setAutoFillBackground(True)
    panel.setStyleSheet("background: rgb(255, 0, 0);")
    edit = QLineEdit(panel)
    edit.setGeometry(10, 10, 200, 24)
    completer = QCompleter(QStringListModel(["fantasy", "fiction", "favourite"]), edit)
    edit.setCompleter(completer)
    mw.show()
    mw.activateWindow()
    qapp.processEvents()
    edit.setFocus()
    qapp.processEvents()
    edit.setText("f")
    if not edit.hasFocus():
        pytest.skip("platform could not give the line edit real focus")
    panel.hide_events = 0
    panel.show_events = 0
    return mw, panel, edit, completer


def _grab(mw, panel, exclude_by_move):
    host = _FakeOverlayHost(mw, panel)
    return TransportBarBlurOverlay._grab_and_blur(
        host, QRect(0, 32, 300, 532), panel, blur=False, exclude_by_move=exclude_by_move)


def test_hide_path_reproduces_the_teardown(qapp):
    """Control: the old hide-based grab DOES fire hideEvent — the mechanism behind the bug."""
    mw, panel, edit, completer = _build(qapp)
    _grab(mw, panel, exclude_by_move=False)
    qapp.processEvents()
    assert panel.hide_events == 1, "control failed: hide path no longer fires hideEvent"
    mw.close()


def test_move_path_leaves_the_panel_untouched(qapp):
    mw, panel, edit, completer = _build(qapp)
    pos_before = panel.pos()

    _grab(mw, panel, exclude_by_move=True)
    qapp.processEvents()

    assert panel.hide_events == 0 and panel.show_events == 0, (
        "Book Detail's hideEvent exits edit mode with save=False and cancels armed confirms — "
        "the backdrop grab must never fire it")
    assert panel.isVisible()
    assert panel.pos() == pos_before, "panel must be restored to exactly where it was"
    assert edit.hasFocus(), "the field being edited must keep real Qt focus"
    assert edit.text() == "f"
    mw.close()


def test_move_path_keeps_completer_popup_open(qapp):
    """The tag field's suggestion popup must survive a grab. Popups can't be shown under the
    offscreen platform (nor focused windows under Wayland/Xwayland on the dev desktop), so this
    skips there — it runs on any platform that can show one. Live check: TESTING.md."""
    mw, panel, edit, completer = _build(qapp)
    completer.setCompletionPrefix("f")
    completer.complete()
    qapp.processEvents()
    if not completer.popup().isVisible():
        mw.close()
        pytest.skip("platform could not show the completer popup")
    _grab(mw, panel, exclude_by_move=True)
    qapp.processEvents()
    assert completer.popup().isVisible(), "the tag suggestion popup must stay open"
    mw.close()


def test_move_path_still_excludes_the_panel_from_the_grab(qapp):
    """The whole point of the grab is to photograph what's BEHIND the panel. Every pixel of
    the result must be the main window's blue, none of the panel's red."""
    mw, panel, edit, completer = _build(qapp)
    src = _grab(mw, panel, exclude_by_move=True)
    img = src.toImage()
    assert not img.isNull()
    for x in range(0, img.width(), 7):
        for y in range(0, img.height(), 7):
            c = img.pixelColor(x, y)
            assert not (c.red() > 200 and c.blue() < 50), (
                f"panel paint leaked into the grab at ({x},{y}): {c.name()}")
    mw.close()


def test_move_path_restores_position_even_if_grab_raises(qapp, monkeypatch):
    """A raising grab must never strand Book Detail parked off-screen."""
    mw, panel, edit, completer = _build(qapp)
    pos_before = panel.pos()

    def _boom(*a, **k):
        raise RuntimeError("grab failed")
    monkeypatch.setattr(mw, "grab", _boom)
    with pytest.raises(RuntimeError):
        _grab(mw, panel, exclude_by_move=True)
    assert panel.pos() == pos_before
    mw.close()


# --- The REAL BookDetailPanel -------------------------------------------------------------
# The tests above prove no hideEvent fires on a stand-in panel. These drive the actual panel,
# so a future change to BookDetailPanel's own hideEvent teardown, or to how the grab excludes
# it, is caught against the real symptoms Pryme reported (edit reverted + focus lost; armed
# exclusion confirm dismissed). Temp DB + MagicMock config: nothing touches real settings.

_BOOK = {'id': 1, 'path': '/x/book', 'title': 'Orig Title', 'author': 'A', 'narrator': 'N',
         'year': 2000, 'duration': 3600.0, 'progress': 0.0}


def _real_panel(qapp, tmp_path):
    from unittest.mock import MagicMock
    from fabulor.db import LibraryDB
    from fabulor.ui.book_detail_panel import BookDetailPanel
    cfg = MagicMock()
    cfg.get_book_speed.return_value = None
    cfg.get_default_speed.return_value = 1.0
    cfg.get_book_eq_mode.return_value = "global"
    mw = QWidget()
    mw.setFixedSize(300, 564)
    bdp = BookDetailPanel(LibraryDB(str(tmp_path / "t.db")), cfg, parent=mw)
    bdp.setGeometry(0, 32, 300, 532)
    mw.show()
    mw.activateWindow()
    qapp.processEvents()
    bdp.load_book(dict(_BOOK))
    qapp.processEvents()
    return mw, bdp


def _start_editing(qapp, bdp):
    bdp._enter_edit_mode(bdp._title_label)
    qapp.processEvents()
    bdp._title_label.setText("Typed New")
    if not bdp._title_label.hasFocus():
        pytest.skip("platform could not give the title field real focus")


@pytest.mark.parametrize("exclude_by_move, survives", [(False, False), (True, True)])
def test_real_panel_edit_survives_grab(qapp, tmp_path, exclude_by_move, survives):
    """(False, False) is the control: the hide path must reproduce the reported revert."""
    mw, bdp = _real_panel(qapp, tmp_path)
    _start_editing(qapp, bdp)
    _grab(mw, bdp, exclude_by_move=exclude_by_move)
    qapp.processEvents()
    state = (bdp._editing, bdp._title_label.hasFocus(), bdp._title_label.text())
    if survives:
        assert state == (True, True, "Typed New"), f"edit torn down by the grab: {state}"
    else:
        assert state == (False, False, "Orig Title"), f"control no longer reproduces: {state}"
    mw.close()


@pytest.mark.parametrize("exclude_by_move, survives", [(False, False), (True, True)])
def test_real_panel_remove_confirm_survives_grab(qapp, tmp_path, exclude_by_move, survives):
    mw, bdp = _real_panel(qapp, tmp_path)
    bdp._on_remove_clicked()
    qapp.processEvents()
    assert bdp._confirming_remove
    _grab(mw, bdp, exclude_by_move=exclude_by_move)
    qapp.processEvents()
    assert bdp._confirming_remove is survives
    mw.close()
