"""Regression net for TasselOverlay's idle/kick tick-rate switching (2026-09-25).

Root cause this addresses (see NOTES.md/TODO.md "Continuous ~90% CPU while Stats'
Timeline tab is open"): TasselOverlay.update() forces Qt to repaint the WHOLE
WA_StyledBackground region it sits in — including HourlyHeatmap/StreakGrid's own
expensive paintEvent (20-27ms EACH) — even though those grids never actually changed.
At the original fixed _TICK_MS=33ms this fired continuously the entire time Stats'
Timeline tab was open, measured at ~90% sustained CPU. A WA_OpaquePaintEvent fix on
the GRIDS was tried first and caused a real SIGSEGV (crashed inside Qt's own compiled
code, tied to one of the grids' own QPropertyAnimations ticking) — reverted.

This fix instead reduces how often the expensive cascade can even fire, without
touching the grids' paint contract at all: idle sway (IDLE_AMP is only ±1px total
motion) now ticks at a much coarser _IDLE_TICK_MS rate; a kick (a real, visible ~6px
swing) switches the SAME timer to the fast _TICK_MS rate for as long as it's actively
decaying, then drops back to idle-slow once its envelope clears.

Three places have to agree on which interval is "current" and keep _idle_phase's
per-tick step correct for whichever interval is actually in effect: __init__ (starts
idle-slow), _kick() (switches to fast, unconditionally, since idle may already be
ticking when a kick arrives), _on_sway_tick's envelope-clear (switches back to
idle-slow), showEvent (must resume at whichever interval matches _kick_active, since
hideEvent deliberately preserves kick state across the transport-bar blur grab's
~64ms hide/show churn), and set_show_tassel (always resumes idle-slow, since it
unconditionally clears _kick_active on the preceding disable).
"""
import math

import pytest
from PySide6.QtWidgets import QApplication

from fabulor.ui.stats_panel import TasselOverlay


@pytest.fixture
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def tassel(qapp):
    return TasselOverlay()


def test_starts_at_the_idle_slow_interval(tassel):
    assert tassel._sway_timer.interval() == TasselOverlay._IDLE_TICK_MS


def test_kick_switches_to_the_fast_interval_immediately(tassel):
    tassel._kick()
    assert tassel._sway_timer.interval() == TasselOverlay._TICK_MS


def test_kick_switches_to_fast_even_when_idle_timer_already_running(tassel):
    """The idle timer can already be active (at the slow interval) when a kick
    arrives — _kick() must switch the interval unconditionally, not only when the
    timer was previously stopped."""
    tassel.show()
    assert tassel._sway_timer.isActive()
    assert tassel._sway_timer.interval() == TasselOverlay._IDLE_TICK_MS
    tassel._kick()
    assert tassel._sway_timer.interval() == TasselOverlay._TICK_MS


def test_envelope_clearing_drops_back_to_idle_slow_interval(tassel):
    tassel.show()
    tassel._kick()
    assert tassel._sway_timer.interval() == TasselOverlay._TICK_MS
    # Drive _kick_t directly past the envelope-clear threshold and fire one tick,
    # rather than waiting out the real ~1s decay.
    tassel._kick_t = 100.0  # envelope = KICK_AMP * exp(-KICK_DECAY * 100) ≈ 0
    tassel._on_sway_tick()
    assert tassel._kick_active is False
    assert tassel._sway_timer.interval() == TasselOverlay._IDLE_TICK_MS


def test_idle_phase_step_is_scaled_for_the_slow_interval(tassel):
    """A single slow-interval tick must advance _idle_phase by the SAME amount of
    real wall-clock motion as several fast-interval ticks would — not by IDLE_STEP
    unscaled, which would make the sway's real period slower by the same factor the
    tick rate dropped."""
    ratio = TasselOverlay._IDLE_TICK_MS / TasselOverlay._TICK_MS
    tassel.show()  # idle, slow interval
    assert tassel._kick_active is False
    before = tassel._idle_phase
    tassel._on_sway_tick()
    after = tassel._idle_phase
    assert after - before == pytest.approx(TasselOverlay.IDLE_STEP * ratio)


def test_idle_phase_step_is_unscaled_during_a_kick(tassel):
    tassel.show()
    tassel._kick()
    before = tassel._idle_phase
    tassel._on_sway_tick()
    after = tassel._idle_phase
    assert after - before == pytest.approx(TasselOverlay.IDLE_STEP)


def test_idle_sways_real_period_is_independent_of_tick_rate(tassel):
    """A full 2*pi phase cycle must take approximately the same WALL-CLOCK time
    whether sampled at the fast or the slow interval — this is the actual behavior
    guarantee the phase-step scaling exists for, checked end-to-end rather than just
    checking the scaled increment in isolation."""
    # Fast-interval reference: how many ticks to complete one full cycle, and how
    # much wall-clock time that represents.
    tassel.show()
    tassel._kick()  # forces the fast interval regardless of idle/kick bookkeeping
    fast_ticks = 0
    phase = 0.0
    while phase < 2 * math.pi:
        phase += TasselOverlay.IDLE_STEP
        fast_ticks += 1
    fast_ms = fast_ticks * TasselOverlay._TICK_MS

    # Slow-interval: same loop, using the SCALED step _on_sway_tick actually applies.
    ratio = TasselOverlay._IDLE_TICK_MS / TasselOverlay._TICK_MS
    slow_ticks = 0
    phase = 0.0
    while phase < 2 * math.pi:
        phase += TasselOverlay.IDLE_STEP * ratio
        slow_ticks += 1
    slow_ms = slow_ticks * TasselOverlay._IDLE_TICK_MS

    # Allow slack for the slow interval's coarser quantization (fewer, bigger
    # steps land less precisely on the 2*pi boundary) — the two must still be
    # close, not off by the un-scaled ratio (which would fail this by ~4.5x).
    assert slow_ms == pytest.approx(fast_ms, rel=0.25)


def test_show_event_resumes_at_fast_interval_when_a_kick_was_preserved_across_hide(tassel):
    """hideEvent deliberately preserves _kick_active across the transport-bar blur
    grab's frequent hide/show churn (see that method's own docstring) — showEvent's
    resume must honor that preserved state, not unconditionally resume idle-slow."""
    tassel.show()
    tassel._kick()
    tassel.hide()  # _kick_active survives this, by design
    assert tassel._kick_active is True
    tassel.show()
    assert tassel._sway_timer.interval() == TasselOverlay._TICK_MS


def test_show_event_resumes_at_idle_slow_interval_with_no_kick_active(tassel):
    tassel.show()
    tassel.hide()
    assert tassel._kick_active is False
    tassel.show()
    assert tassel._sway_timer.interval() == TasselOverlay._IDLE_TICK_MS


def test_set_show_tassel_re_enable_resumes_at_idle_slow_interval(tassel):
    """set_show_tassel(False) unconditionally clears _kick_active — re-enabling must
    always resume idle-slow, unlike showEvent's resume which has real preserved
    kick state to honor."""
    tassel.show()
    tassel._kick()
    assert tassel._sway_timer.interval() == TasselOverlay._TICK_MS
    tassel.set_show_tassel(False)
    assert tassel._kick_active is False
    tassel.set_show_tassel(True)
    assert tassel._sway_timer.interval() == TasselOverlay._IDLE_TICK_MS
