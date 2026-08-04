"""ThemeManager.call_when_theme_settled — event-driven-in-effect, predicate-driven-in-
mechanism resume for the corrected snapback-timing spec (pure, headless).

See review/Design_260804_snapback_timing.md. Mirrors PanelManager.call_when_panels_settled
exactly (tests/test_panel_settle_resume.py, Group A) — same reasoning applies identically:
QPropertyAnimation.stop() does not emit `finished` (verified empirically, 2026-07-28), and a
snapback's own fade gets stopped whenever a NEWER call interrupts it (see
test_hover_interrupts_snapback.py) — a signal-based resume would be silently dropped exactly
when a fast dismiss-during-hover-out sequence needs it most. These tests pin the decision
logic only: whether the callback fires immediately or is queued, and the queue's lifecycle.
Qt paint/compositing is not covered here — see the corrected-timing task's own live-
verification items.
"""
import pytest

from fabulor.ui.theme_manager import ThemeManager


class _FakeTimer:
    def __init__(self):
        self.starts = 0

    def start(self):
        self.starts += 1


def _make_tm(fading):
    """ThemeManager with only call_when_theme_settled's collaborators. `fading` is a
    mutable single-item list so a test can flip it between ticks."""
    tm = ThemeManager.__new__(ThemeManager)
    tm._fade_in_flight = fading[0]
    tm._theme_settled_watch_timer = _FakeTimer()
    tm._theme_settled_watch_armed = False
    tm._theme_settled_waiters = []
    # Keep `fading` and tm._fade_in_flight in sync via a tiny property shim, mirroring
    # test_panel_settle_resume.py's _any_panel_animating lambda-over-mutable-list trick.
    tm.__dict__["_fading_ref"] = fading
    return tm


def _set_fade_in_flight(tm, value):
    tm._fade_in_flight = value
    tm._fading_ref[0] = value


def test_fires_synchronously_when_nothing_fading():
    tm = _make_tm([False])
    ran = []
    tm.call_when_theme_settled(lambda: ran.append(1))
    assert ran == [1]
    assert tm._theme_settled_watch_timer.starts == 0


def test_defers_and_arms_when_fading():
    tm = _make_tm([True])
    ran = []
    tm.call_when_theme_settled(lambda: ran.append(1))
    assert ran == []
    assert tm._theme_settled_watch_timer.starts == 1
    assert len(tm._theme_settled_waiters) == 1


def test_second_waiter_does_not_restart_the_timer():
    # Same absolute-deadline property as PanelManager's settle watch (2026-07-22
    # starvation fix) — armed exactly once no matter how many waiters queue.
    tm = _make_tm([True])
    for _ in range(5):
        tm.call_when_theme_settled(lambda: None)
    assert tm._theme_settled_watch_timer.starts == 1
    assert len(tm._theme_settled_waiters) == 5


def test_tick_rearms_while_still_fading():
    tm = _make_tm([True])
    ran = []
    tm.call_when_theme_settled(lambda: ran.append(1))
    tm._on_theme_settled_watch_tick()
    assert ran == []
    assert tm._theme_settled_watch_timer.starts == 2  # initial arm + re-arm
    assert len(tm._theme_settled_waiters) == 1


def test_tick_drains_once_settled():
    tm = _make_tm([True])
    ran = []
    tm.call_when_theme_settled(lambda: ran.append(1))
    _set_fade_in_flight(tm, False)
    tm._on_theme_settled_watch_tick()
    assert ran == [1]
    assert tm._theme_settled_waiters == []


def test_multiple_waiters_all_drain_in_order():
    tm = _make_tm([True])
    ran = []
    tm.call_when_theme_settled(lambda: ran.append("a"))
    tm.call_when_theme_settled(lambda: ran.append("b"))
    _set_fade_in_flight(tm, False)
    tm._on_theme_settled_watch_tick()
    assert ran == ["a", "b"]
