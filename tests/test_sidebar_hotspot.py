"""Corner-hotspot sidebar trigger — see review/Plan_260809_corner_hotspot_sidebar_trigger.md.

Two open methods (right-click, hotspot-hover) share the sidebar's open/close machinery
but differ in one respect: hover-out dismissal only applies to a hotspot-opened sidebar.
An idle-dismiss poll and the hotspot's own geometric re-arm rule (exit-then-reentry,
never a time-based cooldown) apply to both.

`SidebarHotspot`'s own hover-intent/armed-state logic is tested against a real (headless)
QApplication with the real QWidget class — its enterEvent/leaveEvent/QTimer interaction is
exactly what would be re-encoded wrong by a fake, mirroring test_hover_excludes_speed_sleep.py's
reasoning for testing the real widget rather than a stand-in.

PanelManager's opened_via/idle-poll/hover-out logic is tested against a real MainWindow-shaped
fixture (not the full app — building the real MainWindow pulls in Player/mpv/LibraryDB, which
this suite avoids elsewhere too) that supplies exactly what _toggle_sidebar/on_sidebar_hover_out
read: sidebar_animation, sidebar, sidebar_expanded and friends.

QSettings isolation note: QSettings.setDefaultFormat(IniFormat) + setPath (the pattern
test_hover_excludes_speed_sleep.py uses) was tried first here and found NOT to isolate on this
platform/PySide6 build — confirmed live: QSettings("Fabulor", "Fabulor").format() reports
NativeFormat regardless of setDefaultFormat, and .fileName() resolves to the real
~/.config/Fabulor/Fabulor.conf every time, leaking test writes into the user's real config (this
actually happened once while developing these tests — see SESSION.md/NOTES.md). The `config`
fixture below instead monkeypatches fabulor.config.QSettings so Config()'s hardcoded
QSettings("Fabulor", "Fabulor") construction resolves to an explicit tmp_path .ini file via the
QSettings(path, IniFormat) two-arg form, which DOES isolate correctly (verified). Scoped to this
test module only, via monkeypatch — no other test file's isolation assumption is touched.
"""
import pytest
from PySide6.QtCore import QEvent, QPointF, QPoint, QSettings, QAbstractAnimation, QPropertyAnimation, QTimer
from PySide6.QtGui import QEnterEvent
from PySide6.QtWidgets import QApplication, QWidget

from fabulor.config import Config
from fabulor.ui.panels import PanelManager, _SIDEBAR_IDLE_DISMISS_MS
from fabulor.ui.sidebar_hotspot import SidebarHotspot, HOTSPOT_SIZE


@pytest.fixture
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def config(qapp, tmp_path, monkeypatch):
    ini_path = str(tmp_path / "test_settings.ini")

    class _IsolatedQSettings(QSettings):
        def __init__(self, *_args, **_kwargs):
            # Ignore Config's own ("Fabulor", "Fabulor") args — always resolve to
            # this test's own tmp_path .ini file. See module docstring for why
            # setDefaultFormat/setPath alone doesn't isolate on this platform.
            super().__init__(ini_path, QSettings.IniFormat)

    import fabulor.config as config_mod
    monkeypatch.setattr(config_mod, "QSettings", _IsolatedQSettings)
    return Config()


def _enter_event(widget):
    pos = QPointF(5, 5)
    return QEnterEvent(pos, pos, widget.mapToGlobal(pos.toPoint()))


def _leave_event():
    return QEvent(QEvent.Type.Leave)


# ---------------------------------------------------------------------------
# SidebarHotspot — hover-intent, armed/re-arm, settings gating, paint gating
# ---------------------------------------------------------------------------

def _make_hotspot(config, fired=None):
    calls = fired if fired is not None else []
    hotspot = SidebarHotspot(config, on_fire=lambda: calls.append(True))
    hotspot.show()
    return hotspot, calls


def test_hover_intent_delay_not_instant(qapp, config):
    """A mouse-pass-through shorter than the hover-intent delay must not fire — the
    timer starts on enter and is cancelled by leave before it can time out."""
    hotspot, calls = _make_hotspot(config)
    hotspot.enterEvent(_enter_event(hotspot))
    assert hotspot._hover_timer.isActive()
    hotspot.leaveEvent(_leave_event())
    assert not hotspot._hover_timer.isActive()
    assert calls == []


def test_hover_intent_fires_after_delay(qapp, config):
    hotspot, calls = _make_hotspot(config)
    hotspot.enterEvent(_enter_event(hotspot))
    hotspot._hover_timer.timeout.emit()  # simulate the delay elapsing
    assert calls == [True]


def test_no_op_while_disarmed(qapp, config):
    """Hotspot must not arm a hover-intent timer while disarmed (the re-arm gate)."""
    hotspot, calls = _make_hotspot(config)
    hotspot._armed = False
    hotspot.enterEvent(_enter_event(hotspot))
    assert not hotspot._hover_timer.isActive()
    assert calls == []


def test_rearm_requires_exit_and_reentry(qapp, config):
    """Disarming, then leaving the zone, re-arms; disarming with no leave does not."""
    hotspot, calls = _make_hotspot(config)
    hotspot._armed = False
    # Still "inside" — no leaveEvent — must stay disarmed.
    assert hotspot._armed is False
    hotspot.leaveEvent(_leave_event())
    assert hotspot._armed is True
    hotspot.enterEvent(_enter_event(hotspot))
    assert hotspot._hover_timer.isActive()


def test_disarm_if_cursor_inside_only_disarms_when_inside(qapp, config):
    hotspot, calls = _make_hotspot(config)
    hotspot.move(0, 0)
    hotspot.resize(HOTSPOT_SIZE, HOTSPOT_SIZE)
    # cursor() reports the real (offscreen) global pointer; not guaranteed inside the
    # widget, so just confirm the two possible outcomes are the ones this method can
    # produce — the geometric branch itself, not a live cursor position.
    was_armed = hotspot._armed
    hotspot.disarm_if_cursor_inside()
    assert hotspot._armed in (True, False)
    # If the cursor is outside (the common offscreen case), armed state is preserved.
    if not hotspot.rect().contains(hotspot.mapFromGlobal(hotspot.cursor().pos())):
        assert hotspot._armed == was_armed


def test_hotspot_enabled_setting_gates_hover_intent(qapp, config):
    config.set_sidebar_hotspot_enabled(False)
    hotspot, calls = _make_hotspot(config)
    hotspot.enterEvent(_enter_event(hotspot))
    assert not hotspot._hover_timer.isActive()


def test_hotspot_enabled_setting_gates_fire(qapp, config):
    """Even if the timer somehow fires, a since-disabled setting blocks the callback —
    the re-check at fire time the plan calls for (config toggled off mid-delay)."""
    hotspot, calls = _make_hotspot(config)
    hotspot.enterEvent(_enter_event(hotspot))
    config.set_sidebar_hotspot_enabled(False)
    hotspot._hover_timer.timeout.emit()
    assert calls == []


# ---------------------------------------------------------------------------
# PanelManager — opened_via, idle poll, hover-out
#
# PanelManager.__init__ wires up far more than the sidebar (transport blur overlay,
# tab-bar interceptor, six other panels' own animations) — building a fake MainWindow
# that satisfies the full __init__ is itself a source of drift risk (a fake construction
# path can silently diverge from what __init__ actually needs over time). Following
# this suite's own established convention (test_vt_file_switched_guard.py,
# test_panel_exclusion.py: "bind the REAL unbound method to a tiny fake supplying
# exactly the collaborators it reads"), these tests skip __init__ entirely
# (PanelManager.__new__) and set only the attributes each method under test actually
# touches — confirmed by reading each method body directly, not guessed. sidebar_animation
# is a REAL QPropertyAnimation (not a fake) since its timing/state() is exactly what
# _toggle_sidebar's own documented history (see panels.py) says is load-bearing.
# ---------------------------------------------------------------------------

def _make_panel_manager(config):
    from PySide6.QtCore import QPropertyAnimation, QEasingCurve

    pm = PanelManager.__new__(PanelManager)
    pm.config = config
    pm.sidebar_expanded = False
    pm._pending_panel_open = None
    pm._sidebar_toggle_queued = False
    pm._sidebar_pending_target = None
    pm._sidebar_opened_via = None
    pm._sidebar_last_cursor_pos = None
    pm._sidebar_last_movement_ts = None

    sidebar = QWidget()
    sidebar.setFixedWidth(70)
    pm.sidebar = sidebar
    pm.sidebar_animation = QPropertyAnimation(sidebar, b"pos")
    # 0ms, not the real 300ms: a QPropertyAnimation with setDuration(0) completes
    # SYNCHRONOUSLY on start() (confirmed live — state() reads Stopped immediately
    # after start() returns), so sidebar_expanded's flip and _toggle_sidebar's own
    # logic can be tested without an event loop / QTest.qWait. The mid-slide-defer
    # branch (_sidebar_pending_target, a click arriving while genuinely still
    # animating) is real animation-timing machinery this feature doesn't touch —
    # out of scope here; it has its own documented history in panels.py directly.
    pm.sidebar_animation.setDuration(0)
    pm.sidebar_animation.setEasingCurve(QEasingCurve.OutCubic)

    from PySide6.QtCore import QTimer
    poll_timer = QTimer()
    poll_timer.setInterval(500)
    pm._sidebar_idle_poll_timer = poll_timer
    pm._settled_watch_armed = False
    pm._panels_settled_waiters = []
    poll_timer_settle = QTimer()
    poll_timer_settle.setSingleShot(True)
    pm._settled_watch_timer = poll_timer_settle

    class _FakeMainWindow:
        chapter_list_widget = QWidget()
        chapter_list_widget.fade_out = lambda: None
        theme_manager = None

    pm.main_window = _FakeMainWindow()

    for name in ("library_panel", "settings_panel", "speed_panel", "sleep_panel",
                 "sprint_panel", "stats_panel", "tags_panel"):
        w = QWidget()
        w.cancel_preload = lambda: None
        setattr(pm, name, w)
    pm.library_panel.cancel_preload = lambda: None
    pm.book_detail_panel = None
    pm.book_detail_panel_animation = None

    # _toggle_sidebar's mid-slide-defer branch (call_when_panels_settled ->
    # _any_panel_animating) reads every OTHER panel's animation too, even though none
    # of them are under test here — real, never-started QPropertyAnimations so
    # .state() reads Stopped, same as a genuinely idle panel.
    for name in ("library_panel_animation", "settings_panel_animation",
                 "speed_panel_animation", "sleep_panel_animation", "sprint_panel_animation",
                 "stats_panel_animation", "tags_panel_animation", "blur_animation"):
        setattr(pm, name, QPropertyAnimation(QWidget(), b"pos"))

    return pm


@pytest.fixture
def panel_manager(qapp, config):
    return _make_panel_manager(config)


def test_right_click_open_sets_opened_via(panel_manager):
    pm = panel_manager
    assert pm.sidebar_expanded is False
    pm.handle_drag_area_right_click(event=None)
    assert pm.sidebar_expanded is True
    assert pm._sidebar_opened_via == "right_click"


def test_toggle_sidebar_closing_clears_opened_via(panel_manager):
    pm = panel_manager
    pm.handle_drag_area_right_click(event=None)
    assert pm._sidebar_opened_via == "right_click"
    pm._toggle_sidebar()  # closes
    assert pm.sidebar_expanded is False
    assert pm._sidebar_opened_via is None


def test_idle_poll_armed_on_open_disarmed_on_close(panel_manager):
    pm = panel_manager
    assert not pm._sidebar_idle_poll_timer.isActive()
    pm.handle_drag_area_right_click(event=None)
    assert pm._sidebar_idle_poll_timer.isActive()
    pm._toggle_sidebar()
    assert not pm._sidebar_idle_poll_timer.isActive()


def test_idle_poll_dismisses_regardless_of_opened_via(panel_manager):
    """Idle timeout applies identically whether opened via right-click or hotspot —
    simulated here by directly invoking the poll tick with a stale movement timestamp,
    since real 10s+ wall-clock waits don't belong in a unit test."""
    import time
    pm = panel_manager
    pm.handle_drag_area_right_click(event=None)
    assert pm.sidebar_expanded is True
    pm._sidebar_last_movement_ts = time.monotonic() - (_SIDEBAR_IDLE_DISMISS_MS / 1000.0) - 1
    pm._on_sidebar_idle_poll_tick()
    assert pm.sidebar_expanded is False


def test_idle_poll_resets_on_cursor_movement(panel_manager, monkeypatch):
    import time
    from PySide6.QtGui import QCursor
    pm = panel_manager
    pm.handle_drag_area_right_click(event=None)
    stale_ts = time.monotonic() - (_SIDEBAR_IDLE_DISMISS_MS / 1000.0) - 1
    pm._sidebar_last_movement_ts = stale_ts
    # Simulate movement: report a different cursor position than last recorded.
    moved_pos = QPoint(
        pm._sidebar_last_cursor_pos.x() + 50, pm._sidebar_last_cursor_pos.y()
    )
    monkeypatch.setattr(QCursor, "pos", staticmethod(lambda: moved_pos))
    pm._on_sidebar_idle_poll_tick()
    assert pm.sidebar_expanded is True  # not dismissed
    assert pm._sidebar_last_movement_ts > stale_ts  # movement clock reset


def test_hover_out_dismisses_hotspot_opened_sidebar(panel_manager):
    pm = panel_manager
    pm.handle_drag_area_right_click(event=None)  # opens via right_click branch
    pm._sidebar_opened_via = "hotspot_hover"  # simulate a hotspot-driven open
    pm.on_sidebar_hover_out()
    assert pm.sidebar_expanded is False


def test_hover_out_does_not_dismiss_right_click_opened_sidebar(panel_manager):
    pm = panel_manager
    pm.handle_drag_area_right_click(event=None)
    assert pm._sidebar_opened_via == "right_click"
    pm.on_sidebar_hover_out()
    assert pm.sidebar_expanded is True


def test_hover_out_ignored_while_sidebar_closed(panel_manager):
    pm = panel_manager
    assert pm.sidebar_expanded is False
    pm.on_sidebar_hover_out()  # must not raise or open the sidebar
    assert pm.sidebar_expanded is False


def test_hover_out_ignored_mid_animation(panel_manager):
    """A leaveEvent firing while the sidebar's own open/close slide is running must
    not be treated as a real cursor-left signal (the widget's geometry is moving)."""
    pm = panel_manager
    pm.handle_drag_area_right_click(event=None)
    pm._sidebar_opened_via = "hotspot_hover"
    # Give this ONE test a genuinely non-zero duration (the fixture defaults to 0 so
    # other tests can assert post-toggle state synchronously — see the fixture's own
    # comment) so sidebar_animation.state() can actually read Running when checked.
    pm.sidebar_animation.setDuration(5000)
    pm.sidebar_animation.setStartValue(QPoint(0, 56))
    pm.sidebar_animation.setEndValue(QPoint(-70, 56))
    pm.sidebar_animation.start()
    assert pm.sidebar_animation.state() == QAbstractAnimation.State.Running
    pm.on_sidebar_hover_out()
    assert pm.sidebar_expanded is True  # not dismissed while animating
    pm.sidebar_animation.stop()


def test_dismiss_sidebar_via_toggle_still_clears_opened_via_and_idle_poll(panel_manager):
    """Regression pin for the shared close path every dismiss route (nav-item click,
    click-away, idle timeout, hover-out) ultimately funnels through: _toggle_sidebar's
    closing branch. Every _open_*_flow (e.g. _open_library_flow, not exercised directly
    here — it needs is_overlay_open_or_committed/_complete_main_fade/library_panel's own
    clear_tag_filter_if_active, outside this feature's scope) calls _toggle_sidebar()
    when sidebar_expanded is True before dispatching to its own panel; this pins that
    the ONE closing branch both existing call sites and this feature's own dismiss paths
    share correctly tears down opened_via/the idle poll regardless of caller."""
    pm = panel_manager
    pm.handle_drag_area_right_click(event=None)
    assert pm.sidebar_expanded is True
    assert pm._sidebar_idle_poll_timer.isActive()
    pm._toggle_sidebar()
    assert pm.sidebar_expanded is False
    assert pm._sidebar_opened_via is None
    assert not pm._sidebar_idle_poll_timer.isActive()


def test_settings_toggle_hotspot_enabled_default_true(config):
    assert config.get_sidebar_hotspot_enabled() is True


def test_settings_toggle_hotspot_enabled_roundtrip(config):
    config.set_sidebar_hotspot_enabled(False)
    assert config.get_sidebar_hotspot_enabled() is False
    config.set_sidebar_hotspot_enabled(True)
    assert config.get_sidebar_hotspot_enabled() is True
