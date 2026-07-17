"""Lifecycle contract for the deferred invisible-surface restyle batch
(ThemeManager._schedule_deferred_restyle / _run_deferred_restyle /
flush_deferred_restyle / _flush_deferred_restyle_now).

Design + rationale: plans/going-forward-on-this-twinkly-corbato.md. The theme apply is
split into a synchronous visible fast path (~280ms) and a deferred batch (~355ms of
invisible-surface work) that runs ONCE, off the animation path — after the flow
animation on book-load, or on the next event-loop turn for rotation/T.

These pin the batch's own lifecycle, independent of the ~355ms of real styling:
- coalescing (multiple triggers → one batch, last-write-wins theme),
- runs exactly once (no double-apply, no leak across triggers),
- the animation guard (does NOT run while a flow animation is Running — that's the
  whole point; the _flow_anim.finished connection re-fires it after),
- the forced flush (panel-open compensation) bypasses the animation guard.

We bind the REAL unbound ThemeManager methods to a tiny fake supplying exactly the
collaborators they touch (following tests/test_vt_file_switched_guard.py), so no
QApplication / real widget tree is needed — the batch body is stubbed out via
_flush_deferred_restyle_now being observable through _apply_stylesheets_deferred +
the TAIL spies.
"""
import pytest

from fabulor.ui.theme_manager import ThemeManager


class _FakeFlowAnim:
    """Stand-in for progress_slider._flow_anim exposing just .state()."""
    # QPropertyAnimation.State.Running is compared by identity in _run_deferred_restyle
    # via `== QPropertyAnimation.Running`; we import the real enum so the comparison is real.
    def __init__(self, running=False):
        from PySide6.QtCore import QAbstractAnimation
        self._running = running
        self._Running = QAbstractAnimation.State.Running
        self._Stopped = QAbstractAnimation.State.Stopped

    def state(self):
        return self._Running if self._running else self._Stopped


class _FakeSlider:
    def __init__(self, running=False):
        self._flow_anim = _FakeFlowAnim(running)


class _FakeMW:
    def __init__(self, anim_running=False):
        self.progress_slider = _FakeSlider(anim_running)
        self._refresh_calls = []

    def _refresh_panel_visuals(self, theme_name):
        self._refresh_calls.append(theme_name)


class _FakeTM:
    """Binds the real ThemeManager deferred-batch methods to a minimal object.

    _schedule_deferred_restyle calls QTimer.singleShot — to keep these tests
    QApplication-free and deterministic, we override it with a spy that records the
    request instead of arming a real timer, then drive _run_deferred_restyle manually
    (mimicking the timer firing / the _flow_anim.finished connection firing). This
    isolates the coalescing + guard + once-only logic from Qt's event loop.
    """
    # real methods under test
    _run_deferred_restyle = ThemeManager._run_deferred_restyle
    flush_deferred_restyle = ThemeManager.flush_deferred_restyle
    _flush_deferred_restyle_now = ThemeManager._flush_deferred_restyle_now

    def __init__(self, anim_running=False):
        self.main_window = _FakeMW(anim_running)
        self._deferred_restyle_pending = False
        self._deferred_restyle_theme = None
        # spies for the batch body
        self.deferred_applied = []       # theme_names passed to _apply_stylesheets_deferred
        self.emit_calls = []             # theme dicts emitted
        self.list_visuals_calls = 0

    # ---- schedule: spy version (no real QTimer) mirroring the real coalescing ----
    def _schedule_deferred_restyle(self, theme_name):
        self._deferred_restyle_theme = theme_name
        if self._deferred_restyle_pending:
            return
        self._deferred_restyle_pending = True
        # real code would QTimer.singleShot(0, self._run_deferred_restyle); tests fire manually

    # ---- batch body spies (replace the real ~355ms styling) ----
    def _apply_stylesheets_deferred(self, theme_name):
        self.deferred_applied.append(theme_name)

    def update_theme_list_visuals(self):
        self.list_visuals_calls += 1

    # theme_applied.emit(...) — the real one is a Qt signal; spy it
    class _Emitter:
        def __init__(self, outer):
            self._outer = outer
        def emit(self, theme_dict):
            self._outer.emit_calls.append(theme_dict)

    @property
    def theme_applied(self):
        return _FakeTM._Emitter(self)


def _set_anim_running(tm, running):
    tm.main_window.progress_slider._flow_anim._running = running


def test_coalesce_two_triggers_one_batch_last_wins():
    tm = _FakeTM(anim_running=False)
    tm._schedule_deferred_restyle("themeA")
    tm._schedule_deferred_restyle("themeB")   # before the (manual) run — coalesce
    assert tm._deferred_restyle_pending is True
    assert tm._deferred_restyle_theme == "themeB"   # last-write-wins
    tm._run_deferred_restyle()                # timer fires
    assert tm.deferred_applied == ["themeB"]  # applied once, latest theme
    assert tm.list_visuals_calls == 1
    assert tm._deferred_restyle_pending is False
    assert tm._deferred_restyle_theme is None


def test_runs_exactly_once_second_run_is_noop():
    tm = _FakeTM(anim_running=False)
    tm._schedule_deferred_restyle("t")
    tm._run_deferred_restyle()
    tm._run_deferred_restyle()                # e.g. _flow_anim.finished also firing
    assert tm.deferred_applied == ["t"]       # exactly once
    assert tm.list_visuals_calls == 1


def test_tail_runs_with_the_batch():
    tm = _FakeTM(anim_running=False)
    tm._schedule_deferred_restyle("t")
    tm._run_deferred_restyle()
    # TAIL: _refresh_panel_visuals + theme_applied.emit + update_theme_list_visuals
    assert tm.main_window._refresh_calls == ["t"]
    assert len(tm.emit_calls) == 1
    assert tm.list_visuals_calls == 1


def test_animation_running_defers_batch_then_runs_when_finished():
    """The core anti-freeze guard: while a flow animation is Running, _run_deferred_restyle
    must NOT run the batch (it would freeze the animation). It stays armed; the later
    _flow_anim.finished-triggered call runs it."""
    tm = _FakeTM(anim_running=True)
    tm._schedule_deferred_restyle("t")
    tm._run_deferred_restyle()                # singleShot(0) fires DURING animation
    assert tm.deferred_applied == []          # did NOT run — animation still going
    assert tm._deferred_restyle_pending is True   # stays armed
    # animation finishes → the _flow_anim.finished connection calls _run_deferred_restyle again
    _set_anim_running(tm, False)
    tm._run_deferred_restyle()
    assert tm.deferred_applied == ["t"]        # now it runs, after the animation
    assert tm._deferred_restyle_pending is False


def test_flush_forces_batch_even_during_animation():
    """The panel-open compensation: flush_deferred_restyle bypasses the animation guard
    and runs synchronously NOW (correctness before a panel paints beats the rare freeze)."""
    tm = _FakeTM(anim_running=True)
    tm._schedule_deferred_restyle("t")
    tm.flush_deferred_restyle()               # panel opening — force it now
    assert tm.deferred_applied == ["t"]        # ran despite animation Running
    assert tm._deferred_restyle_pending is False
    # a subsequent _run_deferred_restyle (timer/anim-finished) is a no-op
    tm._run_deferred_restyle()
    assert tm.deferred_applied == ["t"]        # still once


def test_flush_noop_when_nothing_pending():
    tm = _FakeTM(anim_running=False)
    tm.flush_deferred_restyle()               # nothing armed
    assert tm.deferred_applied == []
    assert tm._deferred_restyle_pending is False


def test_no_leak_across_triggers():
    """Two separate trigger→run cycles (e.g. two book switches) each apply their own
    theme once; no state bleeds from the first into the second."""
    tm = _FakeTM(anim_running=False)
    tm._schedule_deferred_restyle("A")
    tm._run_deferred_restyle()
    tm._schedule_deferred_restyle("B")
    tm._run_deferred_restyle()
    assert tm.deferred_applied == ["A", "B"]
    assert tm._deferred_restyle_pending is False
    assert tm._deferred_restyle_theme is None
