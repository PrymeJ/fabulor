"""Regression net for the List-mode slide-paint-suppression fix (see
plans/library-list-slide-paint-suppression.md for the full design, measurement, and
review trail).

Measured baseline (2026-09-25, _wire_paint_probe): QListView's own paint cost during a
Library open slide was 149-187ms of a ~300ms nominal slide in List mode — by far the
worst of any view mode. Root cause is the same class of problem CLAUDE.md already
documents for Book Detail: a widget that moves gets repainted in full by Qt on every
position tick, and List mode's per-row delegate painting is the single most expensive
thing in the panel.

Fix: grab library_panel's list viewport ONCE at open-start (content is already current
at that point — nothing is stored across a close, so there is no staleness window to
guard), with hover suppressed for that one grab so a held hover or an in-flight fade
trail can never freeze into the static proxy. A QLabel proxy shows that pixmap and
moves for free as a child of library_panel while the real viewport's repainting is
suppressed for the duration of the slide; the proxy is torn down once the panel has
settled and a live repaint has been requested.

Two design revisions preceded this, both caught by independent review before any code
was written — not rediscovered live:
  1. A first draft grabbed at CLOSE and cached the pixmap for reuse at the next open.
     Rejected: Off hover-fade mode has no timer/flag to detect a held hover; a
     fingerprint meant to catch staleness missed real cases (metadata edits, exclusion,
     theme changes, all reachable via Book Detail while Library is closed); the
     deferred-grab lifecycle had an unguarded reopen-during-pending-grab race.
  2. The open-start grab itself went through two further corrections: the hover-suppress
     flag must live on the DELEGATE INSTANCE (library_panel._delegate), never on the
     BookDelegate CLASS (an instance attribute of the same name silently shadows a class
     attribute — setting the class attribute would do nothing and the bug would be very
     easy to miss); and setUpdatesEnabled(False) must target the VIEWPORT specifically,
     not the QListView itself (which would also freeze the frame border and scrollbar,
     neither of which the proxy covers).

This file tests the mechanism in isolation — the delegate's hover-suppression paint
logic directly, and PanelManager's proxy lifecycle via a minimal fake MainWindow (the
same pattern tests/test_pending_panel_sheet_consumed_once.py already uses for
ThemeManager) — not a full live app. Live checks (hover correctness, the proxy-to-live
handoff, start latency, rapid open/close, theme/metadata changes while closed) are
listed in the design plan and are not repeated here; per this project's own documented
lesson, live-perceived smoothness and visual handoff correctness are not things an
automated test can establish on their own.
"""
import pytest
from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QListView, QVBoxLayout, QWidget

from fabulor.models.book import Book
from fabulor.ui.library import BookDelegate
from fabulor.ui.panels import PanelManager


@pytest.fixture
def qapp():
    return QApplication.instance() or QApplication([])


class _FakeIndex:
    """Only .row() is read by _paint_list_row (for alternating-row color)."""
    def __init__(self, row):
        self._row = row

    def row(self):
        return self._row


def _painted_rect_color(delegate, book, hovered, suppress, hover_fade_mode="Off",
                         hover_fade_alpha=None, kbd_hover_path=None):
    """Paints one list row into a small offscreen pixmap and returns the color at its
    TOP-LEFT corner — real QPainter output, not a mocked call, so this catches an
    actual visual regression rather than just "was fillRect called with these args".
    Sampled at the corner (not the center) deliberately: the row is wide enough that
    title/author text or cover art can land under a center sample, but the hover fill
    (like the alternating row background under it) always covers the FULL row rect,
    so a corner pixel reliably reflects only the background/hover layer regardless of
    what text happens to be drawn on top elsewhere in the row."""
    delegate._hover_fade_mode = hover_fade_mode
    delegate._suppress_hover_for_grab = suppress
    delegate._kbd_hover_path = kbd_hover_path
    if hover_fade_alpha is not None:
        delegate._hover_fade = {book.path: hover_fade_alpha}
    else:
        delegate._hover_fade = {}

    pixmap = QPixmap(200, 24)
    pixmap.fill(QColor(0, 0, 0, 0))
    from PySide6.QtGui import QPainter
    from PySide6.QtWidgets import QStyleOptionViewItem
    painter = QPainter(pixmap)
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 200, 24)
    index = _FakeIndex(0)
    try:
        delegate._paint_list_row(painter, option, index, book, hovered,
                                  show_rem=False, live_pos=0.0, live_dur=0.0)
    finally:
        painter.end()
    image = pixmap.toImage()
    return image.pixelColor(2, 2)


@pytest.fixture
def delegate(qapp):
    d = BookDelegate(theme={})
    return d


@pytest.fixture
def book():
    return Book(path="/library/some_book", title="Some Book")


# ---------------------------------------------------------------------------
# Delegate-level: hover suppression must zero the WHOLE fade state, not just
# the hovered row.
# ---------------------------------------------------------------------------

def test_suppressed_grab_hides_a_held_hover_in_active_fade_mode(delegate, book):
    normal = _painted_rect_color(delegate, book, hovered=True, suppress=False,
                                  hover_fade_mode="Normal", hover_fade_alpha=255)
    suppressed = _painted_rect_color(delegate, book, hovered=True, suppress=True,
                                      hover_fade_mode="Normal", hover_fade_alpha=255)
    assert normal != suppressed
    row_bg = _painted_rect_color(delegate, book, hovered=False, suppress=True,
                                  hover_fade_mode="Normal", hover_fade_alpha=0)
    assert suppressed == row_bg


def test_suppressed_grab_hides_a_held_hover_in_off_fade_mode(delegate, book):
    normal = _painted_rect_color(delegate, book, hovered=True, suppress=False,
                                  hover_fade_mode="Off")
    suppressed = _painted_rect_color(delegate, book, hovered=True, suppress=True,
                                      hover_fade_mode="Off")
    assert normal != suppressed
    row_bg = _painted_rect_color(delegate, book, hovered=False, suppress=True,
                                  hover_fade_mode="Off")
    assert suppressed == row_bg


def test_suppressed_grab_hides_a_mid_fade_out_trail_on_a_non_hovered_row(delegate, book):
    """A row that isn't the hovered one but still has a live, decaying alpha entry in
    _hover_fade (the mouse left it recently) must ALSO be suppressed — this is the
    direct regression test for the "whole fade state, not just the hovered row" fix.
    Confirms the flag doesn't just special-case _list_hovered_path/the hovered param."""
    with_trail = _painted_rect_color(delegate, book, hovered=False, suppress=False,
                                      hover_fade_mode="Normal", hover_fade_alpha=180)
    suppressed = _painted_rect_color(delegate, book, hovered=False, suppress=True,
                                      hover_fade_mode="Normal", hover_fade_alpha=180)
    assert with_trail != suppressed
    row_bg = _painted_rect_color(delegate, book, hovered=False, suppress=True,
                                  hover_fade_mode="Normal", hover_fade_alpha=0)
    assert suppressed == row_bg


def test_suppressed_grab_hides_keyboard_hover_in_off_mode(delegate, book):
    """Off mode's hover branch also checks book.path == self._kbd_hover_path — must be
    suppressed too, not just the mouse-hover 'hovered' parameter."""
    normal = _painted_rect_color(delegate, book, hovered=False, suppress=False,
                                  hover_fade_mode="Off", kbd_hover_path=book.path)
    suppressed = _painted_rect_color(delegate, book, hovered=False, suppress=True,
                                      hover_fade_mode="Off", kbd_hover_path=book.path)
    assert normal != suppressed


# ---------------------------------------------------------------------------
# PanelManager-level: the proxy lifecycle, via a minimal fake MainWindow (same
# shape as tests/test_pending_panel_sheet_consumed_once.py's ThemeManager fixture).
# ---------------------------------------------------------------------------

class _FakeScanner:
    def is_running(self):
        return False


class _FakeAnimation:
    """Stands in for library_panel_animation — records calls, never actually ticks.
    finished is a tiny pub-sub so tests can drive _on_library_shown/_on_library_hidden
    directly without a real event loop."""
    class _Signal:
        def __init__(self):
            self._slots = []

        def connect(self, slot):
            self._slots.append(slot)

        def disconnect(self, slot=None):
            if slot is None:
                if not self._slots:
                    raise RuntimeError("no connections")
                self._slots.clear()
            else:
                self._slots.remove(slot)

        def emit(self):
            for slot in list(self._slots):
                slot()

    class _State:
        Stopped = 0
        Running = 1

    def __init__(self):
        self.finished = self._Signal()
        self._state = self._State.Stopped
        self.start_calls = 0
        self._start_value = None
        self._end_value = None

    def state(self):
        return self._state

    def setStartValue(self, v):
        self._start_value = v

    def setEndValue(self, v):
        self._end_value = v

    def duration(self):
        return 300

    def start(self):
        self.start_calls += 1
        self._state = self._State.Running


def _build_fake_main_window(qapp, tmp_path, view_mode="List"):
    """A minimal MainWindow stand-in carrying only what _start_library_entry,
    _on_library_shown, _close_library_flow, and _teardown_library_list_proxy actually
    read off it — NOT a full app shell. Standing up a real PanelManager via its own
    __init__ would require constructing the whole app's chrome (TransportBarBlurOverlay
    alone reaches into a dozen unrelated MainWindow widgets), which is out of scope for
    testing this proxy mechanism and would make these tests fragile against any future,
    unrelated __init__ change. See _build_panel_manager below for how PanelManager
    itself is constructed without running its __init__."""
    from PySide6.QtCore import QSettings
    from fabulor.config import Config

    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))

    mw = QWidget()
    mw.resize(300, 564)
    mw.show()
    mw.config = Config()
    mw.config.set_library_view_mode(view_mode)
    # get_blur_enabled()'s default was confirmed live to read True (panel_backdrop
    # defaults to "frosty") even against a fresh, isolated QSettings store — pin it
    # explicitly rather than rely on that default, since _close_library_flow's blur
    # branch needs a REAL blur_effect (self.blur_effect.blurRadius()) this fixture's
    # fake MainWindow deliberately doesn't provide (nothing under test here exercises
    # blur behavior).
    mw.config.set_blur_enabled(False)
    mw.scanner = _FakeScanner()
    mw._set_scan_buttons_enabled = lambda *a, **k: None

    library_panel = QWidget(mw)
    library_panel.setObjectName("library_panel")
    # A real layout, not a bare QWidget with none — _start_library_entry calls
    # library_panel.layout().activate() to force the viewport's geometry to settle
    # before the grab (see that call site's own comment: on a process's first-ever
    # show, Qt has not yet synchronously propagated setFixedWidth/setFixedHeight down
    # into the QAbstractScrollArea's internal viewport geometry, confirmed live
    # 2026-09-25). A None layout would make that call raise, which the surrounding
    # try/except would silently swallow — masking whether activate() is actually
    # being exercised rather than genuinely testing it.
    layout = QVBoxLayout(library_panel)
    layout.setContentsMargins(0, 0, 0, 0)
    library_panel._list_view = QListView(library_panel)
    layout.addWidget(library_panel._list_view)
    library_panel._list_view.resize(280, 400)
    library_panel._list_view.show()
    library_panel._delegate = BookDelegate(theme={})
    library_panel._is_animating = False
    # True by default here — these tests exercise the synchronous fast path (every
    # open after a process's first) unless a test explicitly sets this False to
    # exercise the first-open deferral instead. See _start_library_entry's own
    # comment for why this flag exists and what it gates.
    library_panel._first_show_geometry_settled = True

    def _refresh(*a, **k):
        pass
    library_panel.refresh = _refresh

    mw.library_panel = library_panel
    mw.library_panel_animation = _FakeAnimation()
    mw.blur_effect = None
    mw.blur_animation = _FakeAnimation()

    return mw


def _build_panel_manager(mw):
    """Constructs a PanelManager WITHOUT running its real __init__ (which builds the
    whole app's panel/animation/button wiring — see _build_fake_main_window's
    docstring). Sets only the attributes _start_library_entry/_on_library_shown/
    _close_library_flow/_teardown_library_list_proxy actually read, confirmed by
    reading each method directly rather than guessed."""
    pm = PanelManager.__new__(PanelManager)
    pm.main_window = mw
    pm.config = mw.config
    pm.library_panel = mw.library_panel
    pm.library_panel_animation = mw.library_panel_animation
    pm.blur_effect = mw.blur_effect
    pm.blur_animation = mw.blur_animation
    pm._library_list_proxy = None
    pm._library_entry_animation_pending = False
    pm._flush_pending_restyle = lambda: None
    return pm


@pytest.fixture
def pm(qapp, tmp_path):
    mw = _build_fake_main_window(qapp, tmp_path, view_mode="List")
    return _build_panel_manager(mw)


def test_opening_in_list_mode_creates_a_proxy_with_updates_disabled_on_the_viewport(pm):
    pm._start_library_entry()
    assert pm._library_list_proxy is not None
    assert isinstance(pm._library_list_proxy, QLabel)
    assert pm._library_list_proxy.isVisible()
    assert not pm.library_panel._list_view.viewport().updatesEnabled()
    # QListView itself must NOT be the disabled target (see "Disable on the viewport,
    # not the view" in the design plan) — only its viewport.
    assert pm.library_panel._list_view.updatesEnabled()


def test_opening_in_a_grid_mode_never_creates_a_proxy(qapp, tmp_path):
    mw = _build_fake_main_window(qapp, tmp_path, view_mode="3 per row")
    pm = _build_panel_manager(mw)

    pm._start_library_entry()
    assert pm._library_list_proxy is None
    assert pm.library_panel._list_view.viewport().updatesEnabled()


# ---------------------------------------------------------------------------
# First-open geometry-settle deferral. LibraryPanel.showEvent defers a geometry-
# correcting re-run of _apply_view_mode by one event-loop tick on a process's
# first-ever show (a pre-existing fix, unrelated to this feature, for List/Square
# mode's top-margin remainder math). Grabbing the viewport before that correction
# lands captures it 1px short — confirmed live, 2026-09-25: reproduced only on a
# process's first Library open, as a visible ~1-2px vertical pop at handoff.
# _library_panel._first_show_geometry_settled is False only until that correction
# has run once; _start_library_entry must defer its own grab by the same one tick
# in that case, and stay synchronous (today's fast path) every other time.
# ---------------------------------------------------------------------------

def test_first_open_defers_the_grab_until_the_geometry_settle_completes(qapp, tmp_path):
    mw = _build_fake_main_window(qapp, tmp_path, view_mode="List")
    mw.library_panel._first_show_geometry_settled = False
    pm = _build_panel_manager(mw)

    import fabulor.ui.panels as panels_mod
    captured = []
    original_qtimer = panels_mod.QTimer
    patched = type("PatchedQTimer", (), {
        "singleShot": staticmethod(lambda ms, cb: captured.append(cb))
    })
    panels_mod.QTimer = patched
    try:
        pm._start_library_entry()
    finally:
        panels_mod.QTimer = original_qtimer

    # Nothing has happened synchronously yet — the grab, the proxy, and the
    # animation start are all deferred behind the pending flag.
    assert pm._library_list_proxy is None
    assert pm._library_entry_animation_pending is True
    assert pm.library_panel_animation.start_calls == 0
    assert len(captured) == 1

    # Simulate the geometry settling (what LibraryPanel.showEvent's own deferred
    # callback does), THEN let the deferred call captured above actually run.
    mw.library_panel._first_show_geometry_settled = True
    captured[0]()

    assert pm._library_list_proxy is not None
    assert pm._library_entry_animation_pending is False
    assert pm.library_panel_animation.start_calls == 1


def test_subsequent_opens_stay_on_the_synchronous_fast_path(pm):
    """pm's fixture already has _first_show_geometry_settled=True (every open after
    a process's first) — the grab and animation start must happen synchronously,
    inline, with no deferral at all."""
    pm._start_library_entry()
    assert pm._library_list_proxy is not None
    assert pm._library_entry_animation_pending is False
    assert pm.library_panel_animation.start_calls == 1


def test_close_during_the_first_open_deferral_gap_is_correctly_dropped(qapp, tmp_path):
    """A close issued in the narrow window between _start_library_entry scheduling
    the deferred grab and that deferred call actually running must be dropped, same
    as a close issued while the animation is genuinely Running — otherwise
    _close_library_flow would start a close-slide from the WRONG assumed start
    position (library_panel is still off-screen; the animation hasn't started)."""
    mw = _build_fake_main_window(qapp, tmp_path, view_mode="List")
    mw.library_panel._first_show_geometry_settled = False
    pm = _build_panel_manager(mw)

    pm._start_library_entry()
    assert pm._library_entry_animation_pending is True

    pm._close_library_flow()
    # Dropped — no close-slide was started (the fake animation's own start_calls
    # counter would have incremented if _close_library_flow had proceeded).
    assert pm.library_panel_animation.start_calls == 0


def test_proxy_placement_uses_mapTo_not_raw_viewport_geometry(pm):
    # Give the layout a nonzero top margin so _list_view sits at a nonzero offset
    # within library_panel — mapTo-derived placement and the viewport's own raw
    # (locally-scoped) .geometry() must then genuinely diverge. Without an offset the
    # two can coincide by chance (e.g. a 1px frame landing at the same (1,1) either
    # way), which would let a wrong mapping pass this test undetected. This is the
    # direct regression test for the coordinate-space bug the design review caught.
    # (A layout-managed widget ignores a manual .move() — the layout would just
    # reposition it back on the next activate() — so the offset has to come from the
    # layout's own margins instead.)
    pm.library_panel.layout().setContentsMargins(0, 37, 0, 0)

    pm._start_library_entry()
    viewport = pm.library_panel._list_view.viewport()
    expected_top_left = viewport.mapTo(pm.library_panel, QPoint(0, 0))
    expected_size = viewport.size()
    proxy_geom = pm._library_list_proxy.geometry()

    assert proxy_geom.topLeft() == expected_top_left
    assert proxy_geom.size() == expected_size
    # The raw, locally-scoped viewport().geometry() is NOT what the proxy should be
    # placed at — confirms the fix actually uses mapTo rather than the wrong value.
    assert proxy_geom.topLeft() != viewport.geometry().topLeft()


def test_suppress_hover_flag_is_false_again_immediately_after_the_grab(pm):
    pm._start_library_entry()
    assert pm.library_panel._delegate._suppress_hover_for_grab is False


def test_grab_failure_falls_back_to_a_normal_live_slide(pm, monkeypatch):
    """viewport().grab() raising must not prevent the animation from starting — the
    inner try/finally clears the flag, the outer except falls through to a live slide."""
    def _raise(*a, **k):
        raise RuntimeError("simulated grab failure")

    monkeypatch.setattr(pm.library_panel._list_view.viewport(), "grab", _raise)
    pm._start_library_entry()

    assert pm.library_panel._delegate._suppress_hover_for_grab is False
    assert pm._library_list_proxy is None
    assert pm.library_panel._list_view.viewport().updatesEnabled()
    assert pm.library_panel_animation.start_calls == 1


def test_failure_after_proxy_creation_falls_back_and_tears_down_cleanly(pm, monkeypatch):
    """A failure AFTER the proxy has been created and stored (not inside grab() itself)
    must still be caught by the outer except and cleaned up via
    _teardown_library_list_proxy — this is the case a try/finally around grab() alone
    would NOT catch. The monkeypatch must only throw on setUpdatesEnabled(False) — a
    blanket throw would also break the teardown's own restore-to-True call inside the
    except handler, failing this test for a reason unrelated to the code under test."""
    viewport = pm.library_panel._list_view.viewport()
    original = viewport.setUpdatesEnabled

    def _throw_only_on_false(enabled):
        if enabled is False:
            raise RuntimeError("simulated failure after proxy creation")
        original(enabled)

    monkeypatch.setattr(viewport, "setUpdatesEnabled", _throw_only_on_false)
    pm._start_library_entry()

    assert pm._library_list_proxy is None
    assert viewport.updatesEnabled()
    assert pm.library_panel_animation.start_calls == 1


def test_on_library_shown_tears_down_proxy_from_within_the_settle_singleshot(pm):
    """The proxy must be torn down from inside the singleShot(16, ...) settle callback,
    not synchronously inside _on_library_shown itself — verified via call order."""
    pm._start_library_entry()
    assert pm._library_list_proxy is not None

    calls = []
    orig_single_shot = None
    from PySide6.QtCore import QTimer as _QTimer
    orig_single_shot = _QTimer.singleShot

    def _capture_single_shot(ms, callback):
        calls.append(callback)

    import fabulor.ui.panels as panels_mod
    original_qtimer = panels_mod.QTimer
    patched = type("PatchedQTimer", (), {"singleShot": staticmethod(_capture_single_shot)})
    panels_mod.QTimer = patched
    try:
        pm._on_library_shown()
    finally:
        panels_mod.QTimer = original_qtimer

    # The proxy must still exist immediately after _on_library_shown returns — teardown
    # is deferred to the captured settle callback, not run synchronously.
    assert pm._library_list_proxy is not None
    assert len(calls) == 1

    calls[0]()
    assert pm._library_list_proxy is None


def test_teardown_is_idempotent_when_no_proxy_exists(pm):
    assert pm._library_list_proxy is None
    pm._teardown_library_list_proxy()  # must not raise
    assert pm._library_list_proxy is None


def test_close_landing_after_open_finished_but_before_settle_singleshot_tears_down_immediately(pm):
    """Drive the open animation to 'finished' (proxy exists, _on_library_shown has run,
    but its singleShot settle callback has not fired yet), then close — confirm
    _close_library_flow's own teardown call removes the proxy immediately, and the
    later-firing settle callback's own teardown call is a safe no-op against it."""
    pm._start_library_entry()
    assert pm._library_list_proxy is not None

    import fabulor.ui.panels as panels_mod
    captured = []
    original_qtimer = panels_mod.QTimer
    patched = type("PatchedQTimer", (), {
        "singleShot": staticmethod(lambda ms, cb: captured.append(cb))
    })
    panels_mod.QTimer = patched
    try:
        pm.library_panel_animation.finished.emit()  # -> _on_library_shown
    finally:
        panels_mod.QTimer = original_qtimer

    assert pm._library_list_proxy is not None  # settle callback hasn't fired yet
    assert len(captured) == 1

    # Reset the fake animation to Stopped so _close_library_flow's own guard doesn't
    # early-return (it only no-ops while genuinely Running).
    pm.library_panel_animation._state = pm.library_panel_animation._State.Stopped
    pm._close_library_flow()

    assert pm._library_list_proxy is None
    assert pm.library_panel._list_view.viewport().updatesEnabled()

    # The settle callback captured above fires later (mirroring the real 16ms delay) —
    # confirm it no-ops harmlessly against the already-torn-down proxy.
    captured[0]()
    assert pm._library_list_proxy is None


def test_close_after_a_stuck_finished_connection_still_tears_down_the_proxy(pm):
    """Simulates _on_library_shown never running at all (the finished signal never
    delivers) — the direct regression test for the race the design review's point 1
    raised: an orphaned proxy from an earlier open must not survive into the next one."""
    pm._start_library_entry()
    assert pm._library_list_proxy is not None

    # Do NOT fire `finished` — _on_library_shown never runs, mirroring a stuck
    # connection. Reset state so _close_library_flow's own running-guard doesn't
    # early-return (the guard would otherwise make this test pass for the wrong
    # reason — see the design plan's correction of the original close-during-open
    # framing).
    pm.library_panel_animation._state = pm.library_panel_animation._State.Stopped
    pm._close_library_flow()

    assert pm._library_list_proxy is None
    assert pm.library_panel._list_view.viewport().updatesEnabled()

    # A subsequent open must not stack a second proxy on top of an orphaned first one.
    pm._start_library_entry()
    assert pm._library_list_proxy is not None
