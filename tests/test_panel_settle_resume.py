"""Event-driven resume for the panel-animation guard (pure, headless).

The bug (live-traced 2026-07-28, 03:34:44-47): the first theme hover after opening the
Settings panel took ~2.1s to preview. `_on_theme_changed`'s guard deferred via a flat
700ms retry (`_PANEL_ANIM_GUARD_MS`), but the blur-in runs 1500ms — and starts AFTER the
200-300ms slide, since `_start_visual_area_blur` is called from the slide-finished
callback. Two retry rounds are structurally guaranteed and up to 700ms is pure overshoot.

`PanelManager.call_when_panels_settled` replaces the poll for the ANIMATING case only.
It re-checks `_any_panel_animating()` on a 16ms tick rather than subscribing to
`finished`, because `QPropertyAnimation.stop()` does NOT emit `finished` (verified
empirically) and `blur_animation.stop()` runs unconditionally on every panel open — a
signal-based resume would be silently dropped, which is the exact failure already
diagnosed three times against `_fade_anim`.

The `_panel_open` case keeps the old timer: it ends on a USER ACTION (closing the panel),
not a clock, so there is no signal to subscribe to.

Qt paint/compositing is NOT covered here (see the plan's live-verification items). These
pin the decision logic: which mechanism claims a call, and the waiter queue's lifecycle.
"""
import pytest

from fabulor.ui.panels import PanelManager
from fabulor.ui.panels import _BLUR_IN_MS, _BLUR_IN_THEMES_TAB_MS
from fabulor.ui.theme_manager import ThemeManager


# --- Group C: Themes-tab blur-in shortening --------------------------------
#
# The guard fix above removed the POLLING overshoot but not the wait itself: a
# hover still cannot preview until the blur settles, so the first hover after
# opening Settings stayed dead for ~1.1s — reported as "would make the user
# wonder if it is broken".
#
# Shortening the blur-in on the Themes tab collapses that window (measured: 1091ms
# -> 0ms for a hover arriving 430ms after open; 366ms worst case at 50ms) and,
# unlike letting the hover interrupt the blur, introduces NO stall — worst frame
# gap stays ~17ms, identical to blur-alone baseline. It moves the settle point
# earlier rather than colliding a restyle with a running tween.

class _FakeTabs:
    def __init__(self, index):
        self._index = index

    def currentIndex(self):
        return self._index


def _make_blur_pm(tab_index, *, has_tabs=True):
    pm = PanelManager.__new__(PanelManager)
    pm.settings_panel = object()
    pm.main_window = type("MW", (), {})()
    if has_tabs:
        pm.main_window.tabs = _FakeTabs(tab_index)
    return pm


def test_themes_tab_gets_the_short_blur_in():
    pm = _make_blur_pm(0)
    assert pm._blur_in_duration_for(pm.settings_panel) == _BLUR_IN_THEMES_TAB_MS


@pytest.mark.parametrize("tab_index", [1, 2, 3, 4])
def test_other_settings_tabs_keep_the_full_blur_in(tab_index):
    # Look/Library/Audio/Controls: nobody is racing the blur there.
    pm = _make_blur_pm(tab_index)
    assert pm._blur_in_duration_for(pm.settings_panel) == _BLUR_IN_MS


def test_non_settings_panels_keep_the_full_blur_in():
    # Stats/Tags/Speed/Sleep share the same blur_animation singleton — their
    # panel-open feel must be untouched, even though Themes is the active tab.
    pm = _make_blur_pm(0)
    assert pm._blur_in_duration_for(object()) == _BLUR_IN_MS


def test_missing_tabs_falls_back_to_the_full_blur_in():
    # mw.tabs only exists inside settings_panel; never assume it is there.
    pm = _make_blur_pm(0, has_tabs=False)
    pm.main_window.tabs = None
    assert pm._blur_in_duration_for(pm.settings_panel) == _BLUR_IN_MS


def test_short_blur_in_is_actually_shorter():
    # Guards against someone "tidying" the two constants to the same value and
    # silently reinstating the dead first hover.
    assert _BLUR_IN_THEMES_TAB_MS < _BLUR_IN_MS


# --- Group A: call_when_panels_settled / _arm_settled_watch / tick ----------

class _FakeTimer:
    def __init__(self):
        self.starts = 0

    def start(self):
        self.starts += 1


def _make_pm(animating):
    """PanelManager with only the settle-watch collaborators. `animating` is a mutable
    single-item list so a test can flip it between ticks."""
    pm = PanelManager.__new__(PanelManager)
    pm._any_panel_animating = lambda: animating[0]
    pm._settled_watch_timer = _FakeTimer()
    pm._settled_watch_armed = False
    pm._panels_settled_waiters = []
    return pm


def test_fires_synchronously_when_nothing_animating():
    # Mirrors when_animations_done's else branch: nothing to wait for, run now.
    pm = _make_pm([False])
    ran = []
    pm.call_when_panels_settled(lambda: ran.append(1))
    assert ran == [1]
    assert pm._settled_watch_timer.starts == 0


def test_defers_and_arms_when_animating():
    pm = _make_pm([True])
    ran = []
    pm.call_when_panels_settled(lambda: ran.append(1))
    assert ran == []
    assert pm._settled_watch_timer.starts == 1
    assert len(pm._panels_settled_waiters) == 1


def test_second_waiter_does_not_restart_the_timer():
    # THE STARVATION PIN (2026-07-22). _panel_guard_timer did stop()+start() on every
    # re-arm, so its deadline was retriggerable — and because re-arming was driven by
    # mouse motion, a queued call could be starved indefinitely. Here the timer must be
    # armed exactly once no matter how many waiters queue, so the deadline is absolute.
    pm = _make_pm([True])
    for _ in range(5):
        pm.call_when_panels_settled(lambda: None)
    assert pm._settled_watch_timer.starts == 1
    assert len(pm._panels_settled_waiters) == 5


def test_tick_rearms_while_still_animating():
    pm = _make_pm([True])
    ran = []
    pm.call_when_panels_settled(lambda: ran.append(1))
    pm._on_settled_watch_tick()
    assert ran == []
    assert pm._settled_watch_timer.starts == 2   # initial arm + re-arm
    assert len(pm._panels_settled_waiters) == 1


def test_tick_drains_all_waiters_once_when_settled():
    animating = [True]
    pm = _make_pm(animating)
    ran = []
    for i in range(3):
        pm.call_when_panels_settled(lambda i=i: ran.append(i))
    animating[0] = False
    pm._on_settled_watch_tick()
    assert ran == [0, 1, 2]
    assert pm._panels_settled_waiters == []
    assert pm._settled_watch_armed is False


def test_stopped_animation_that_never_emitted_finished_still_resumes():
    # THE DESIGN'S WHOLE POINT. blur_animation.stop() emits no `finished`, and it runs on
    # every panel open (_start_visual_area_blur) and on blur-toggle-off. A signal-based
    # resume would be dropped here; a predicate re-check cannot be.
    animating = [True]
    pm = _make_pm(animating)
    ran = []
    pm.call_when_panels_settled(lambda: ran.append(1))
    animating[0] = False          # stop() — no `finished` signal anywhere
    pm._on_settled_watch_tick()
    assert ran == [1]


def test_stop_then_restart_in_one_block_is_never_observed():
    # panels.py's _start_visual_area_blur does stop() then start() with no event-loop
    # turn between, so the tick never sees the gap and the waiter stays pending.
    pm = _make_pm([True])
    ran = []
    pm.call_when_panels_settled(lambda: ran.append(1))
    pm._on_settled_watch_tick()   # predicate never went False
    assert ran == []
    assert len(pm._panels_settled_waiters) == 1


def test_callback_requeueing_during_drain_is_not_lost_or_double_run():
    # A callback may synchronously re-enter (the theme resume is a full re-call that can
    # re-defer). Pins the swap-before-invoke: the new waiter lands in a fresh list.
    animating = [False]
    pm = _make_pm(animating)
    calls = []

    def requeue():
        calls.append("first")
        animating[0] = True                       # something started again
        pm.call_when_panels_settled(lambda: calls.append("second"))

    pm._panels_settled_waiters = [requeue]
    pm._settled_watch_armed = True
    pm._on_settled_watch_tick()

    assert calls == ["first"]                     # second is queued, not run in this drain
    assert len(pm._panels_settled_waiters) == 1


# --- Group B: the _on_theme_changed branch split ---------------------------

class _RecordingPM:
    def __init__(self, animating, full_panel_visible):
        self._animating = animating
        self._full_panel_visible = full_panel_visible
        self.settled_callbacks = []

    def _any_panel_animating(self):
        return self._animating

    def is_any_full_panel_visible(self):
        return self._full_panel_visible

    def call_when_panels_settled(self, cb):
        self.settled_callbacks.append(cb)


class _RecordingGuardTimer:
    def __init__(self):
        self.starts = 0
        self.timeout = self

    def stop(self):
        pass

    def disconnect(self):
        pass

    def connect(self, fn):
        self._fn = fn

    def start(self):
        self.starts += 1


class _FakeConfig:
    def get_theme_fade_duration(self):
        return 750


class _FakeMW:
    def __init__(self, pm):
        self.panel_manager = pm


def _make_tm(animating=False, full_panel_visible=False):
    tm = ThemeManager.__new__(ThemeManager)
    pm = _RecordingPM(animating, full_panel_visible)
    tm.main_window = _FakeMW(pm)
    tm.config = _FakeConfig()
    tm._panel_guard_timer = _RecordingGuardTimer()
    tm._is_hover_active = False
    tm._fade_in_flight = False
    tm._pending_fade_call = None
    tm._active_display_theme_internal = "Active"
    tm._applied = []
    tm._apply_stylesheets = lambda n, hover=False: tm._applied.append((n, hover))
    return tm, pm


def _call(tm, theme="X", *, hover=False, bypass=False, user_initiated=True, fade_ms=750):
    try:
        ThemeManager._on_theme_changed(tm, theme, save=False, fade_ms=fade_ms, hover=hover,
                                       user_initiated=user_initiated,
                                       bypass_panel_open_guard=bypass)
    except Exception:
        pass  # past the branch decision lies real Qt painting


def test_animating_routes_to_settle_resume_not_the_timer():
    tm, pm = _make_tm(animating=True)
    _call(tm, hover=True)
    assert len(pm.settled_callbacks) == 1
    assert tm._panel_guard_timer.starts == 0


def test_panel_open_only_still_uses_the_guard_timer():
    # Not animation-driven — ends on a user action, so the poll stays.
    tm, pm = _make_tm(animating=False, full_panel_visible=True)
    _call(tm, hover=False, bypass=False)
    assert tm._panel_guard_timer.starts == 1
    assert pm.settled_callbacks == []


def test_both_true_animating_claims_the_call():
    # if/elif ordering: exactly one mechanism owns a call.
    tm, pm = _make_tm(animating=True, full_panel_visible=True)
    _call(tm, hover=False, bypass=False)
    assert len(pm.settled_callbacks) == 1
    assert tm._panel_guard_timer.starts == 0


def test_resume_is_a_full_recall_carrying_all_six_args():
    # Pins the 2026-07-22 lesson: dropping bypass_panel_open_guard on replay caused a
    # snapback to hang indefinitely. The resume must forward every argument.
    tm, pm = _make_tm(animating=True)
    seen = []
    tm._on_theme_changed = lambda *a: seen.append(a)
    ThemeManager._on_theme_changed(
        tm, "Waknuk", save=False, fade_ms=200, hover=False,
        user_initiated=True, bypass_panel_open_guard=True,
    )
    assert len(pm.settled_callbacks) == 1
    pm.settled_callbacks[0]()
    assert seen == [("Waknuk", False, 200, False, True, True)]


def test_resume_redefers_into_the_timer_if_the_panel_is_still_open():
    # Ownership transfer: animation settles, panel still open -> second pass lands in
    # the _panel_open branch rather than applying.
    tm, pm = _make_tm(animating=True, full_panel_visible=True)
    _call(tm, hover=False, bypass=False)
    cb = pm.settled_callbacks[0]
    pm._animating = False          # animation finished; panel still open
    try:
        cb()
    except Exception:
        pass
    assert tm._panel_guard_timer.starts == 1


# --- Group D: sidebar toggle defers to a TARGET STATE, not a queued toggle ---
#
# Two live-measured failures shaped this:
#   1. Original: the re-entrancy guard silently DISCARDED clicks arriving during the
#      300ms slide. 5 of 25 (20%) lost, four inside the slide window.
#   2. First fix (queue the toggle): each replay STARTED A NEW SLIDE that caught the
#      next click, which queued, which replayed... Eight consecutive toggles at
#      306-322ms, the sidebar running continuously one step behind the user, while the
#      log reported 26 clicks -> 26 toggles with "zero losses".
#
# Root error in (2): queueing a RELATIVE operation. The user is asking for the sidebar
# to END UP somewhere, so the deferred value is the desired FINAL state and repeated
# clicks overwrite it — an even number during one slide cancels out.

class _FakeSidebarAnim:
    def __init__(self, running):
        from PySide6.QtCore import QAbstractAnimation
        self._running = running
        self._R = QAbstractAnimation.State.Running
        self._S = QAbstractAnimation.State.Stopped

    def state(self):
        return self._R if self._running else self._S


def _make_sidebar_pm(anim_running, expanded=False):
    pm = PanelManager.__new__(PanelManager)
    pm.sidebar_animation = _FakeSidebarAnim(anim_running)
    pm.sidebar_expanded = expanded
    pm._sidebar_toggle_queued = False
    pm._sidebar_pending_target = None
    pm.settled_calls = []
    pm.call_when_panels_settled = lambda cb: pm.settled_calls.append(cb)
    return pm


def test_click_during_slide_defers_a_target_not_a_toggle():
    # Slide heading to expanded=True; one click during it means "no, I want False".
    pm = _make_sidebar_pm(anim_running=True, expanded=True)
    PanelManager._toggle_sidebar(pm)
    assert pm._sidebar_pending_target is False
    assert len(pm.settled_calls) == 1


def test_two_clicks_during_one_slide_cancel_out():
    # THE RUNAWAY PIN. Under the queued-toggle design these produced extra slides.
    # As a target, the second click restores the in-flight destination -> no-op.
    pm = _make_sidebar_pm(anim_running=True, expanded=True)
    PanelManager._toggle_sidebar(pm)
    PanelManager._toggle_sidebar(pm)
    assert pm._sidebar_pending_target is True      # back to where the slide is heading
    assert len(pm.settled_calls) == 1              # still only one replay scheduled


def test_satisfied_target_starts_no_new_slide():
    # The cycle's source: replaying when the target already matches state started a
    # fresh slide, which caught the next click.
    pm = _make_sidebar_pm(anim_running=True, expanded=True)
    PanelManager._toggle_sidebar(pm)
    PanelManager._toggle_sidebar(pm)               # cancels out -> target True
    replay = pm.settled_calls[0]
    pm.sidebar_animation._running = False
    calls = []
    pm._toggle_sidebar = lambda: calls.append(1)
    replay()
    assert calls == []                             # no slide started
    assert pm._sidebar_pending_target is None      # consumed


def test_unsatisfied_target_applies_once_settled():
    pm = _make_sidebar_pm(anim_running=True, expanded=True)
    PanelManager._toggle_sidebar(pm)               # target False, state True
    replay = pm.settled_calls[0]
    pm.sidebar_animation._running = False
    calls = []
    pm._toggle_sidebar = lambda: calls.append(1)
    replay()
    assert calls == [1]
    assert pm._sidebar_pending_target is None


def test_replay_stands_down_if_still_animating():
    # call_when_panels_settled waits on ALL animations, so the sidebar's own slide can
    # still be running when the settle arrives.
    pm = _make_sidebar_pm(anim_running=True, expanded=True)
    PanelManager._toggle_sidebar(pm)
    calls = []
    pm._toggle_sidebar = lambda: calls.append(1)
    pm.settled_calls[0]()
    assert calls == []
    assert pm._sidebar_toggle_queued is False      # a later click can defer again


def test_repeated_clicks_schedule_exactly_one_replay():
    pm = _make_sidebar_pm(anim_running=True, expanded=False)
    for _ in range(6):
        PanelManager._toggle_sidebar(pm)
    assert len(pm.settled_calls) == 1


# --- Group E: a CLOSING panel is not an open one --------------------------
#
# THE BUG (reported live 2026-07-28): "close the panel, right click gets
# swallowed." A panel stays isVisible() for its whole ~300ms close slide, so the
# right-click dispatcher still named it as the active panel and routed the click to
# that panel's close flow — which early-returns while its own animation runs. The
# click vanished instead of falling through to the sidebar toggle.
#
# Same shape as the sidebar drop fixed earlier the same day, in four more places.
# Fixed at the DISPATCHER, not in each close flow: those guards are correct
# (restarting a running slide would break it); the bug was treating a closing panel
# as an open one.

class _Anim:
    def __init__(self, running):
        from PySide6.QtCore import QAbstractAnimation
        self._running = running
        self._R = QAbstractAnimation.State.Running
        self._S = QAbstractAnimation.State.Stopped

    def state(self):
        return self._R if self._running else self._S


class _Panel:
    def __init__(self, visible):
        self._visible = visible

    def isVisible(self):
        return self._visible


def _make_dispatch_pm(*, visible, closing):
    pm = PanelManager.__new__(PanelManager)
    for key, attr in PanelManager._CLOSE_ANIMS:
        setattr(pm, f"{key}_panel" if key != "library" else "library_panel",
                _Panel(key == visible))
        setattr(pm, attr, _Anim(key == closing))
    pm.book_detail_panel = None
    pm.main_window = type("MW", (), {"chapter_list_widget": _Panel(False)})()
    return pm


def test_settled_open_panel_is_reported():
    pm = _make_dispatch_pm(visible="settings", closing=None)
    assert pm.active_full_panel() == "settings"


def test_closing_panel_is_not_reported_as_open():
    # THE PIN. Still isVisible(), but mid-slide — so the next right-click must fall
    # through to the sidebar rather than being eaten by the close flow.
    pm = _make_dispatch_pm(visible="settings", closing="settings")
    assert pm.active_full_panel() is None


@pytest.mark.parametrize("key", ["library", "settings", "speed", "sleep", "stats", "tags"])
def test_every_closing_panel_falls_through(key):
    # All six close flows have the identical early-return guard, so all six had the
    # bug — not just the settings panel the user happened to report it on.
    pm = _make_dispatch_pm(visible=key, closing=key)
    assert pm.active_full_panel() is None


def test_is_closing_is_false_for_an_unknown_key():
    pm = _make_dispatch_pm(visible=None, closing=None)
    assert pm._is_closing("nonexistent") is False
