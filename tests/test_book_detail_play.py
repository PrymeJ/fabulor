"""Book Detail's play button (Stats/Tags context) loads a book without the Library.

A Library click ends the switch deadzone and ungates playback from
PanelManager._on_library_hidden. A load from Book Detail has no Library slide, so
BookSwitchState.waits_for_panels holds file-ready/chapters back and
MainWindow._on_panels_cleared_for_switch does that work once every panel settles."""
import pytest
from PySide6.QtCore import QPointF, Qt, QEvent
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QWidget

import fabulor.app as app_mod
from fabulor.app import MainWindow
from fabulor.book_switch import BookSwitchState
from fabulor.ui.book_detail_panel import BookDetailPanel, _CoverPlayOverlay


@pytest.fixture(autouse=True)
def qapp():
    yield QApplication.instance() or QApplication([])


# ── BookSwitchState ─────────────────────────────────────────────────────────────

def test_wait_for_panels_lifecycle():
    sw = BookSwitchState()
    sw.begin(100, None)
    assert sw.waits_for_panels is False
    sw.wait_for_panels()
    assert sw.waits_for_panels and sw.in_deadzone
    sw.library_revealed()
    assert not sw.waits_for_panels and not sw.in_deadzone


def test_begin_resets_a_stale_wait():
    sw = BookSwitchState()
    sw.begin(100, None)
    sw.wait_for_panels()
    sw.begin(200, None)
    assert sw.waits_for_panels is False


# ── MainWindow switch plumbing ──────────────────────────────────────────────────

class _Player:
    def __init__(self):
        self.ungated = 0

    def ungate_play(self):
        self.ungated += 1


def _mw():
    mw = MainWindow.__new__(MainWindow)
    mw._switch = BookSwitchState()
    mw.library_panel = type("LP", (), {"_is_animating": False})()
    mw.player = _Player()
    mw.current_file = "/b.m4b"
    mw.cover_theme_applied = 0
    mw._apply_pending_cover_theme = lambda: setattr(
        mw, "cover_theme_applied", mw.cover_theme_applied + 1)
    return mw


def test_file_ready_and_chapters_defer_while_waiting_for_panels():
    mw = _mw()
    mw._switch.begin(100, None)
    mw._switch.wait_for_panels()
    MainWindow._on_file_ready(mw)
    MainWindow._on_file_loaded_populate_chapters(mw)
    assert mw._switch.file_ready_deferred and mw._switch.chaps_deferred


def test_panels_cleared_ends_deadzone_ungates_and_drains(monkeypatch):
    scheduled = []
    monkeypatch.setattr(app_mod.QTimer, "singleShot", lambda ms, fn: scheduled.append(fn))
    mw = _mw()
    mw._switch.begin(100, None)
    mw._switch.wait_for_panels()
    mw._switch.mark_file_ready_deferred()
    MainWindow._on_panels_cleared_for_switch(mw)
    assert not mw._switch.in_deadzone and not mw._switch.waits_for_panels
    assert mw.player.ungated == 1
    assert scheduled == [mw._drain_deferred_file_ready]
    assert mw.cover_theme_applied == 0      # the drain applies it


def test_panels_cleared_with_nothing_deferred_applies_cover_theme(monkeypatch):
    scheduled = []
    monkeypatch.setattr(app_mod.QTimer, "singleShot", lambda ms, fn: scheduled.append(fn))
    mw = _mw()
    mw._switch.begin(100, None)
    mw._switch.wait_for_panels()
    MainWindow._on_panels_cleared_for_switch(mw)
    assert scheduled == [] and mw.cover_theme_applied == 1 and mw.player.ungated == 1


def _requesting_mw(monkeypatch, current_file):
    queued = []
    monkeypatch.setattr(app_mod.QTimer, "singleShot", lambda ms, fn: queued.append(fn))
    mw = _mw()
    mw.current_file = current_file
    mw.selected = []

    def select(path):
        mw.selected.append(path)
        if path != mw.current_file:
            mw._switch.begin(100, None)
            mw.current_file = path
    mw._on_book_selected_from_library = select
    settled = []
    mw.panel_manager = type("PM", (), {
        "call_when_panels_settled": lambda self, cb: settled.append(cb)})()
    return mw, queued, settled


def test_play_request_switches_and_waits_for_panels(monkeypatch, tmp_path):
    book = tmp_path / "book.m4b"
    book.write_bytes(b"")
    mw, queued, settled = _requesting_mw(monkeypatch, "/other.m4b")
    MainWindow._on_book_play_requested(mw, str(book))
    assert mw.selected == [str(book)] and mw._switch.waits_for_panels
    assert settled == []                    # queued behind load_book's singleShot(0)
    queued.pop()()
    assert settled == [mw._on_panels_cleared_for_switch]


@pytest.mark.parametrize("case", ["already_loaded", "missing_file"])
def test_play_request_that_does_not_switch_does_not_wait(monkeypatch, tmp_path, case):
    book = tmp_path / "book.m4b"
    if case == "already_loaded":
        book.write_bytes(b"")
    current = str(book) if case == "already_loaded" else "/other.m4b"
    mw, queued, settled = _requesting_mw(monkeypatch, current)
    if case == "missing_file":
        mw._on_book_selected_from_library = lambda p: mw.selected.append(p)
    MainWindow._on_book_play_requested(mw, str(book))
    assert mw.selected == [str(book)]       # the existing early returns still run
    assert not mw._switch.waits_for_panels and queued == []


# ── The overlay ─────────────────────────────────────────────────────────────────

def _press(x, y):
    return QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(x, y), QPointF(x, y),
                       Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)


def _overlay():
    host = QWidget()
    o = _CoverPlayOverlay(host)
    o.setGeometry(0, 0, 80, 120)
    clicks = []
    o.clicked.connect(lambda: clicks.append(1))
    return host, o, clicks


def test_overlay_clicks_only_inside_the_disc_when_offered():
    host, o, clicks = _overlay()
    o.set_offered(True)
    assert not o.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    o.mousePressEvent(_press(40, 60))       # centre
    o.mousePressEvent(_press(5, 5))         # corner, outside the disc
    assert clicks == [1]


def test_overlay_not_offered_is_transparent_to_the_mouse():
    host, o, clicks = _overlay()
    o.set_offered(False)
    assert o.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


@pytest.mark.parametrize("offered, archived, expected", [
    (True, False, True),
    (True, True, False),
    (False, False, False),
], ids=["offered", "archived", "not_offered"])
def test_panel_withholds_play_from_archived_books(offered, archived, expected):
    panel = BookDetailPanel.__new__(BookDetailPanel)
    calls = []
    panel._play_overlay = type("O", (), {"set_offered": lambda self, v: calls.append(v)})()
    panel._is_archived = archived
    panel._book_path = "/b.m4b"
    emitted = []
    panel.play_requested = type("S", (), {"emit": lambda self, p: emitted.append(p)})()
    BookDetailPanel.set_play_offered(panel, offered)
    assert calls == [expected]
    BookDetailPanel._on_play_clicked(panel)
    assert emitted == (["/b.m4b"] if expected else [])
