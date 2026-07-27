"""Declined-tick re-arming in the transport-bar blur overlay (pure, headless).

`refresh_dirty()` has two DECLINING gates — hover-active and post-restyle
cooldown — that turn a tick away WITHOUT consuming the accumulated dirty union,
on the reasoning that "the next real paint picks it up". These tests pin the
re-arm that makes that reasoning safe.

Why the re-arm is needed (the stranding path, 2026-07-27): the hover gate's
own argument for self-correction is that hover-end runs a snapback restyle which
repaints the tracked widgets. But the snapback is
`_on_theme_changed(..., hover=False)`, and that method's no-op guard returns
early — without calling `_apply_stylesheets` — whenever the requested
(theme_name, hover) pair is already the applied one. That is precisely the case
after a hover preview was DECLINED here rather than painted: the live theme never
moved, so the snapback is a genuine duplicate, the guard fires, no restyle runs,
and no Paint event is emitted. With no further paint, the stranded dirty union is
never retried and the overlay holds stale content indefinitely.

These tests drive the gate/re-arm decision directly. The Qt compositing itself is
live-only (see TESTING.md's "Panel blur" section) — offscreen harnesses have
already been shown unable to see defects in this area.
"""
import pytest

from fabulor.ui.transport_bar_blur import (
    TransportBarBlurOverlay,
    _DECLINE_REARM_MS,
    _POST_RESTYLE_COOLDOWN_S,
)


class _FakeTracker:
    """Stands in for _DirtyRectTracker: records whether the union was consumed."""

    def __init__(self):
        self.consumed = False

    def take_dirty_union(self):
        self.consumed = True
        return None


class _FakeThemeManager:
    def __init__(self, hover_active=False, last_restyle=None):
        self._is_hover_active = hover_active
        self._last_apply_stylesheets_at = last_restyle


class _FakeMainWindow:
    def __init__(self, theme_manager):
        self.theme_manager = theme_manager


def _make_overlay(hover_active=False, last_restyle=None):
    """Build an overlay with the gate-relevant state only, bypassing __init__
    (which builds real QWidgets). These tests exercise refresh_dirty's decision
    logic, which touches none of that."""
    overlay = object.__new__(TransportBarBlurOverlay)
    overlay.main_window = _FakeMainWindow(_FakeThemeManager(hover_active, last_restyle))
    overlay._active = True
    overlay._active_panel = None
    overlay._tracker = _FakeTracker()
    overlay._refresh_pending = False
    overlay._rearm_pending = False
    overlay._rearm_calls = 0
    # Capture the re-arm instead of arming a real QTimer (no QApplication here).
    overlay._rearm_after_decline = lambda: setattr(
        overlay, "_rearm_calls", overlay._rearm_calls + 1
    )
    return overlay


def test_hover_gate_declines_and_rearms():
    # The stranding case: hover preview active, so the tick is declined. Without
    # a re-arm this union waits on a paint that the snapback's no-op guard may
    # never produce.
    overlay = _make_overlay(hover_active=True)
    overlay.refresh_dirty()
    assert overlay._rearm_calls == 1
    # Declining must NOT consume the union — the retry needs it still there.
    assert overlay._tracker.consumed is False


def test_cooldown_gate_declines_and_rearms():
    import time

    # A restyle just landed: the tick defers rather than colliding with Qt's
    # repaint/repolish backlog (the punch-through-flash collision).
    overlay = _make_overlay(last_restyle=time.perf_counter())
    overlay.refresh_dirty()
    assert overlay._rearm_calls == 1
    assert overlay._tracker.consumed is False


def test_expired_cooldown_does_not_decline():
    import time

    # Past the cooldown window: the gate must let the tick through, reaching
    # take_dirty_union() rather than re-arming.
    overlay = _make_overlay(
        last_restyle=time.perf_counter() - (_POST_RESTYLE_COOLDOWN_S * 2)
    )
    overlay.refresh_dirty()
    assert overlay._rearm_calls == 0
    assert overlay._tracker.consumed is True


def test_no_dirty_does_not_rearm():
    # A clean tick that simply found nothing dirty is NOT a decline — re-arming
    # it would spin a retry loop forever with no content change to chase.
    overlay = _make_overlay()
    overlay.refresh_dirty()
    assert overlay._rearm_calls == 0
    assert overlay._tracker.consumed is True


def test_inactive_overlay_does_not_rearm():
    # Panel closed mid-flight: no retry should be armed against a torn-down
    # overlay.
    overlay = _make_overlay(hover_active=True)
    overlay._active = False
    overlay.refresh_dirty()
    assert overlay._rearm_calls == 0


def test_rearm_coalesces():
    # Real _rearm_after_decline (not the capture): repeated declines while one
    # retry is already pending must arm exactly one timer, not pile up.
    overlay = _make_overlay(hover_active=True)
    del overlay._rearm_after_decline  # fall back to the real bound method

    armed = []
    import fabulor.ui.transport_bar_blur as mod

    class _FakeTimer:
        @staticmethod
        def singleShot(ms, fn):
            armed.append((ms, fn))

    original = mod.QTimer
    mod.QTimer = _FakeTimer
    try:
        overlay.refresh_dirty()
        overlay.refresh_dirty()
        overlay.refresh_dirty()
    finally:
        mod.QTimer = original

    assert len(armed) == 1
    assert armed[0][0] == _DECLINE_REARM_MS


def test_rearm_delay_clears_the_cooldown_window():
    # The retry must be sized above the cooldown it's most often waiting out,
    # or a single retry just re-declines.
    assert _DECLINE_REARM_MS / 1000.0 > _POST_RESTYLE_COOLDOWN_S
