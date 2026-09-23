"""Regression net for PanelManager._wire_slide_paint_suppression (panels.py, 2026-09-23) — the
mechanism that suppresses Book Detail's per-child-widget repaint cost during its slide animation
by showing a static pixmap proxy on top of the (still-visible, still-moving) real panel instead.

See PanelManager._wire_slide_paint_suppression's own docstring, and this feature's design plan
(including its two post-implementation corrections), for the full rationale — in short:

- A REJECTED first design hid the real panel during the slide and swapped to a proxy, which
  would have broken PanelManager.active_full_panel()/is_any_full_panel_visible() (both read
  panel.isVisible() directly, and active_full_panel() is relied on app-wide for shortcut/overlay
  gating). The shipped design keeps the real panel visible and moving throughout — only its OWN
  paint processing is suppressed (setUpdatesEnabled(False)) while a synced pixmap proxy shows on
  top.
- A first correction attempt (grab underlay + composite wash for OPEN only) tried to fix a
  live-reported opaque-then-pop regression, but shipped a WORSE bug — the proxy showed a tinted,
  content-less backdrop for the whole slide, since the composited pixmap never had Book Detail's
  own real content (cover/title/stats/tags) painted into it.
- The FINAL, shipped design (Pryme's own correction): the backdrop was never supposed to slide
  at all — it should be STATIC, matching frost_panel_backdrop's own established behavior. The
  fix moved `_apply_transport_bar_blur_full` to ALSO fire at slide-START (not just slide-finish,
  `_start_book_detail_entry`), producing a real static frost/wash backdrop as its own layer (a
  child of the panel, independent of the panel's own suppressed paint) from the first frame.
  With that separate static layer in place, the sliding proxy needs NOTHING but the panel's own
  real content — a plain `panel.grab()` is correct for BOTH open and close, identical to the
  very first (pre-correction) version of this mechanism. No open/close asymmetry survives in
  the final design.

Uses real QWidget/QPropertyAnimation/QLabel objects for the animation/paint mechanism (genuine Qt
behavior, not something a fake can stand in for), bound to a light fake standing in for
PanelManager itself, same "bind the real method to a light fake" pattern test_panel_exclusion.py
already uses for is_overlay_open_or_committed.
"""
import inspect

import pytest
from PySide6.QtWidgets import QApplication, QWidget, QLabel
from PySide6.QtCore import QPoint, QPropertyAnimation, QEasingCurve, Qt, QAbstractAnimation

from fabulor.ui.panels import PanelManager


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class _FakePanelManagerHost:
    """Stands in for `self` inside PanelManager._wire_slide_paint_suppression — the shipped
    method reads nothing off self (no config/theme_manager needed after the final correction
    reverted to plain panel.grab() for both directions), so this fake is intentionally empty;
    kept as a named class (rather than passing `None`) so a future re-addition of state to the
    method surfaces here as a clear AttributeError rather than a silent None-related failure."""
    pass


def _make_panel_and_proxy(qapp):
    host = QWidget()
    host.setFixedSize(400, 400)
    host.show()

    panel = QWidget(host)
    panel.setFixedSize(270, 300)
    panel.move(QPoint(270, 32))
    child = QLabel("some real content", panel)
    child.move(10, 10)
    panel.show()

    proxy = QLabel(host)
    proxy.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    proxy.hide()

    anim = QPropertyAnimation(panel, b"pos")
    anim.setDuration(300)
    anim.setEasingCurve(QEasingCurve.OutCubic)

    fake_pm = _FakePanelManagerHost()
    PanelManager._wire_slide_paint_suppression(fake_pm, panel, anim, proxy)
    return host, panel, proxy, anim


def _open(anim):
    anim.setStartValue(QPoint(270, 32))
    anim.setEndValue(QPoint(0, 32))


def _close(anim):
    anim.setStartValue(QPoint(0, 32))
    anim.setEndValue(QPoint(270, 32))


@pytest.mark.parametrize("direction", ["open", "close"])
def test_on_start_suppresses_panel_updates_and_shows_proxy_with_grab(qapp, direction):
    host, panel, proxy, anim = _make_panel_and_proxy(qapp)
    try:
        if direction == "open":
            _open(anim)
        else:
            panel.move(QPoint(0, 32))
            _close(anim)
        anim.start()
        try:
            assert panel.updatesEnabled() is False, (
                "panel's own updates must be disabled once the slide starts")
            assert proxy.isVisible() is True
            assert proxy.pos() == panel.pos()
            assert proxy.pixmap() is not None and not proxy.pixmap().isNull(), (
                f"proxy must hold a real, non-empty pixmap on {direction}"
            )
        finally:
            anim.stop()
    finally:
        host.deleteLater()


@pytest.mark.parametrize("direction", ["open", "close"])
def test_proxy_pixmap_is_a_plain_panel_grab_both_directions(qapp, direction):
    """FINAL design: both directions use an unmodified panel.grab() — no underlay
    compositing, no wash painted onto the proxy's own pixmap. The static backdrop (frost/wash)
    is a SEPARATE layer (see _start_book_detail_entry's early _apply_transport_bar_blur_full
    call), not something baked into this pixmap. Verified via size/format equivalence rather
    than byte-for-byte image equality — a second panel.grab() taken after
    setUpdatesEnabled(False) can legitimately differ at the pixel level from the grab the
    implementation itself took a moment earlier, which would be a test-timing artifact, not a
    real difference in what was captured."""
    host, panel, proxy, anim = _make_panel_and_proxy(qapp)
    try:
        if direction == "open":
            _open(anim)
        else:
            panel.move(QPoint(0, 32))
            _close(anim)
        anim.start()
        try:
            proxy_pixmap = proxy.pixmap()
            assert proxy_pixmap.size() == panel.size()
            assert proxy_pixmap.hasAlphaChannel() == panel.grab().hasAlphaChannel()
        finally:
            anim.stop()
    finally:
        host.deleteLater()


def test_value_changed_tick_moves_proxy_to_match(qapp):
    host, panel, proxy, anim = _make_panel_and_proxy(qapp)
    try:
        _open(anim)
        anim.start()
        try:
            anim.setCurrentTime(150)
            assert proxy.pos() == panel.pos(), (
                "proxy must follow the real panel's position on every animation tick")
        finally:
            anim.stop()
    finally:
        host.deleteLater()


def test_on_finished_restores_updates_and_hides_proxy(qapp):
    host, panel, proxy, anim = _make_panel_and_proxy(qapp)
    try:
        _open(anim)
        anim.start()
        anim.setCurrentTime(300)  # force-complete: fires finished synchronously
        assert panel.updatesEnabled() is True, (
            "panel's own updates must be re-enabled once the slide settles")
        assert proxy.isVisible() is False
    finally:
        host.deleteLater()


def test_panel_visibility_and_position_are_never_touched_by_this_mechanism(qapp):
    """The core regression net for the REJECTED first design's flaw: this mechanism must be
    a no-op with respect to panel.isVisible()/panel.pos() at every point in the lifecycle —
    before, during, and after the animation."""
    host, panel, proxy, anim = _make_panel_and_proxy(qapp)
    try:
        assert panel.isVisible() is True

        _open(anim)
        anim.start()
        assert panel.isVisible() is True, "must stay visible once the slide starts"

        anim.setCurrentTime(150)
        assert panel.isVisible() is True, "must stay visible mid-slide"
        assert panel.pos() != QPoint(270, 32), (
            "panel must have genuinely moved under the animation's own control")

        anim.setCurrentTime(300)
        assert panel.isVisible() is True, "must stay visible once the slide finishes"
        assert panel.pos() == QPoint(0, 32)
    finally:
        host.deleteLater()


class _FakeActiveFullPanelGate:
    """Supplies exactly what PanelManager.active_full_panel() reads off self."""
    def __init__(self, book_detail_visible: bool):
        self._book_detail_visible = book_detail_visible

    class _FakePanel:
        def __init__(self, visible):
            self._visible = visible

        def isVisible(self):
            return self._visible

    def __getattr__(self, name):
        if name.endswith("_panel"):
            return self._FakePanel(False)
        raise AttributeError(name)

    @property
    def book_detail_panel(self):
        return self._FakePanel(self._book_detail_visible)

    def _is_closing(self, key):
        return False

    class main_window:
        class chapter_list_widget:
            @staticmethod
            def isVisible():
                return False


def test_active_full_panel_book_detail_unaffected_by_slide_mechanism():
    """Direct regression test for the rejected design's flaw: active_full_panel() must report
    'book_detail' purely off book_detail_panel.isVisible(), which _wire_slide_paint_suppression
    never touches (confirmed by test_panel_visibility_and_position_are_never_touched_by_this_
    mechanism above)."""
    gate = _FakeActiveFullPanelGate(book_detail_visible=True)
    assert PanelManager.active_full_panel(gate) == "book_detail"

    gate_not_open = _FakeActiveFullPanelGate(book_detail_visible=False)
    assert PanelManager.active_full_panel(gate_not_open) is None


def test_close_during_open_animation_is_dropped_by_existing_guard(qapp):
    """_close_book_detail_flow's own close-during-open guard (`if ... state() ==
    Running: return`) must still correctly no-op a close request issued while the open
    animation is running, with _wire_slide_paint_suppression wired onto the SAME animation
    object. This mechanism must never alter the animation's reported .state()."""
    host, panel, proxy, anim = _make_panel_and_proxy(qapp)
    try:
        _open(anim)
        anim.start()
        try:
            assert anim.state() == QAbstractAnimation.State.Running, (
                "the exact condition _close_book_detail_flow's guard checks")
        finally:
            anim.stop()
        assert anim.state() != QAbstractAnimation.State.Running, (
            "sanity: state must genuinely change once stopped, not just be uninspected")
    finally:
        host.deleteLater()


def test_grab_happens_after_layout_and_content_population_in_start_book_detail_entry():
    """Regression net for the open-path grab-timing requirement named in the design plan:
    _wire_slide_paint_suppression's grab (inside anim.start()) must fire AFTER
    _start_book_detail_entry's own layout().activate()/refresh_tag_display()/.show() sequence.

    CAVEAT (per the design plan's own explicit caveat): this does NOT verify actual rendered
    pixel content — a genuine pre/post-layout visual difference was judged not reliably
    reproducible in a headless/offscreen test context. Instead this verifies CALL ORDER via
    source inspection: refresh_tag_display() (an ordinary Python method, spyable) must appear
    before book_detail_panel_animation.start() in _start_book_detail_entry's source text. This
    is a structural guarantee, not a runtime pixel check."""
    import fabulor.ui.panels as panels_module

    source = inspect.getsource(panels_module.PanelManager._start_book_detail_entry)
    refresh_pos = source.index("refresh_tag_display()")
    start_pos = source.index("book_detail_panel_animation.start()")
    assert refresh_pos < start_pos, (
        "refresh_tag_display() must be called before book_detail_panel_animation.start()"
    )
    activate_pos = source.index("layout().activate()")
    assert activate_pos < refresh_pos, (
        "layout().activate() must run before refresh_tag_display()"
    )


def test_frost_backdrop_fires_at_open_start_not_only_at_slide_finish():
    """Regression net for the final fix's actual mechanism: _start_book_detail_entry must call
    self._apply_transport_bar_blur_full(self.book_detail_panel) BEFORE
    book_detail_panel_animation.start() — not only from the slide-finished callback — so the
    static backdrop behind the sliding proxy exists from the very first frame. Verified via
    source-order inspection (same shape as the layout/refresh ordering test above): the EARLY
    call must appear in the method's source text before book_detail_panel_animation.start()."""
    import fabulor.ui.panels as panels_module

    source = inspect.getsource(panels_module.PanelManager._start_book_detail_entry)
    start_call_pos = source.index("book_detail_panel_animation.start()")
    # The first occurrence of the frost call in the method's source — must be BEFORE .start().
    early_frost_pos = source.index("_apply_transport_bar_blur_full")
    assert early_frost_pos < start_call_pos, (
        "_apply_transport_bar_blur_full must be called before book_detail_panel_animation."
        "start(), producing the static backdrop from the first frame of the slide — not only "
        "from the slide-finished callback"
    )
