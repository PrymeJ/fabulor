"""_close_settings_flow blocks on the hover-out snapback settling (pure, headless).

See review/Design_260805_snapback_timing_v2.md. Pins the decision logic only — which branch
runs, and the re-entrancy guard's lifecycle — not Qt's real QTimer.singleShot/animation
painting, which needs live verification (see the corrected-timing task's own items).

CRITICAL, v2's correction over the reverted 2026-08-04 attempt: `_close_settings_flow` must
NOT call `snap_theme_forward()` directly. That call force-stops and instantly re-applies
whatever fade `_on_theme_unhovered()` just started, so the wait this method sets up via
`call_when_theme_settled` was structurally never entered — `_fade_in_flight` was already
False by the time it was checked. The visible result was `_apply_stylesheets`'s own
~700-810ms synchronous cost running with no animation on screen (a freeze), then the correct
colors appearing instantly once it finished (a jump) — not, as first suspected, an
event-loop-blocking wait mechanism. `snap_theme_forward()` is still reachable, but only as
`call_when_theme_settled`'s own internal termination-guarantee fallback for a fade that
genuinely never settles — never called unconditionally from this method.
"""
import pytest

from fabulor.ui.panels import PanelManager


class _FakeThemeManager:
    def __init__(self, fade_in_flight_after_unhover):
        self.unhovered_calls = 0
        self.snap_forward_calls = 0
        self.settled_callbacks = []
        self._fade_in_flight_after_unhover = fade_in_flight_after_unhover
        self._fade_in_flight = False

    def _on_theme_unhovered(self):
        self.unhovered_calls += 1
        self._fade_in_flight = self._fade_in_flight_after_unhover

    def snap_theme_forward(self):
        self.snap_forward_calls += 1

    def call_when_theme_settled(self, callback):
        self.settled_callbacks.append(callback)


class _FakePanel:
    def isVisible(self):
        return True


def _make_pm(theme_manager):
    pm = PanelManager.__new__(PanelManager)
    pm.main_window = type("MW", (), {
        "theme_manager": theme_manager,
        "tabs": type("Tabs", (), {"currentIndex": lambda self: 0})(),
    })()
    pm.settings_panel = _FakePanel()
    pm._finish_close_settings_flow_with_gap_calls = 0
    pm._after_settle_gap_calls = 0
    pm._finish_close_settings_flow_with_gap = lambda: setattr(
        pm, "_finish_close_settings_flow_with_gap_calls",
        pm._finish_close_settings_flow_with_gap_calls + 1,
    )
    pm._close_settings_flow_after_settle_gap = lambda: setattr(
        pm, "_after_settle_gap_calls", pm._after_settle_gap_calls + 1,
    )
    return pm


def test_ordinary_dismiss_with_no_hover_proceeds_immediately():
    # The overwhelming majority case: nothing was hovered, the snapback's own
    # no-op guard means _fade_in_flight never gets set. Zero added delay —
    # _close_settings_flow_after_settle_gap runs directly, no settle-gap timer,
    # and snap_theme_forward is NEVER called from this path (v2 correction).
    tm = _FakeThemeManager(fade_in_flight_after_unhover=False)
    pm = _make_pm(tm)
    PanelManager._close_settings_flow(pm)
    assert tm.unhovered_calls == 1
    assert tm.snap_forward_calls == 0
    assert pm._after_settle_gap_calls == 1
    assert pm._finish_close_settings_flow_with_gap_calls == 0
    assert tm.settled_callbacks == []


def test_dismiss_during_a_genuine_hover_waits_for_the_snapback():
    # A real hover-out: _on_theme_unhovered's snapback genuinely started a fade
    # (_fade_in_flight True after the call). The close must NOT proceed directly
    # — it must register with call_when_theme_settled instead, and must NOT call
    # snap_theme_forward() itself (that would force-stop the very fade being
    # waited on/watched — the exact bug this v2 fix corrects).
    tm = _FakeThemeManager(fade_in_flight_after_unhover=True)
    pm = _make_pm(tm)
    PanelManager._close_settings_flow(pm)
    assert tm.unhovered_calls == 1
    assert tm.snap_forward_calls == 0
    assert pm._after_settle_gap_calls == 0
    assert pm._finish_close_settings_flow_with_gap_calls == 0
    assert len(tm.settled_callbacks) == 1

    # Simulate the snapback settling: call_when_theme_settled's callback fires.
    tm.settled_callbacks[0]()
    assert pm._finish_close_settings_flow_with_gap_calls == 1
    assert pm._after_settle_gap_calls == 0  # still waiting on the settle-gap timer


def test_second_dismiss_while_first_is_pending_is_a_no_op():
    # VERIFICATION ITEM 11: spamming Esc/gutter while a snapback is already
    # resolving must not re-issue _on_theme_unhovered() a second time — the
    # re-entrancy guard (_settings_close_pending) must catch it.
    tm = _FakeThemeManager(fade_in_flight_after_unhover=True)
    pm = _make_pm(tm)
    PanelManager._close_settings_flow(pm)
    assert tm.unhovered_calls == 1

    # Second dismiss arrives before the first has settled.
    PanelManager._close_settings_flow(pm)
    assert tm.unhovered_calls == 1  # UNCHANGED — no second call
    assert tm.snap_forward_calls == 0
    assert len(tm.settled_callbacks) == 1  # no second registration either


def test_guard_clears_after_settling_so_a_later_dismiss_works_normally():
    # The guard must not strand True forever — a dismiss AFTER the panel has
    # actually finished closing must work normally (e.g. the panel was reopened
    # and is being dismissed again).
    tm = _FakeThemeManager(fade_in_flight_after_unhover=True)
    pm = _make_pm(tm)
    PanelManager._close_settings_flow(pm)
    tm.settled_callbacks[0]()  # settle fires -> _finish_close_settings_flow_with_gap

    # _finish_close_settings_flow_with_gap is stubbed in this harness (it would
    # normally call _close_settings_flow_after_settle_gap via a real QTimer,
    # which is what actually clears the guard) — clear it here to simulate that
    # real method having run, then confirm a fresh dismiss is unblocked.
    pm._settings_close_pending = False
    tm2_unhovered_before = tm.unhovered_calls
    PanelManager._close_settings_flow(pm)
    assert tm.unhovered_calls == tm2_unhovered_before + 1
