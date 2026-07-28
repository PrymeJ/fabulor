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
