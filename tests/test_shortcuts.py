"""Guard-behavior contract for the global-key ShortcutDispatcher (shortcuts.py).

Pins the three spam-guard semantics that used to live as ad-hoc timer bookkeeping in
MainWindow (the theme-key cooldown) plus the new drop guard for the library key:

- NONE:              fire on every press.
- COOLDOWN_COALESCE: leading fire; in-window presses coalesce to exactly ONE trailing
                     fire when the window elapses; that trailing fire restarts the window.
                     (T's historical behavior — the last press always lands.)
- COOLDOWN_DROP:     leading fire; in-window presses are dropped with NO trailing fire.
                     (L — a repeat while the panel opens is meaningless, not merely late.)

Needs a QApplication because the guards use QTimer. Cooldowns are set to a few ms and the
event loop is pumped with a bounded spin so the trailing fires can land without wall-clock
sleeps in the assertions themselves.
"""
import time

import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QKeyEvent

from fabulor.shortcuts import (
    Action, GuardKind, Binding, DEFAULT_BINDINGS, ShortcutDispatcher,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


COOLDOWN_MS = 30


def _press(dispatcher, key):
    """Deliver a synthetic key press to the dispatcher; return whether it was consumed."""
    ev = QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
    return dispatcher.handle_key_event(ev)


def _pump(app, ms):
    """Spin the event loop for at least `ms` so pending single-shot timers fire."""
    deadline = time.monotonic() + ms / 1000.0
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.001)
    app.processEvents()


def _make(bindings):
    """A dispatcher + a per-action fire counter recorded via registered handlers."""
    disp = ShortcutDispatcher(bindings=bindings)
    counts = {}
    for action in bindings:
        counts[action] = 0
        def handler(a=action):
            counts[a] += 1
        disp.register(action, handler)
    return disp, counts


# ── NONE guard ────────────────────────────────────────────────────────────────

def test_none_guard_fires_every_press(qapp):
    disp, counts = _make({Action.ROTATE_QUOTE: Binding(Qt.Key.Key_Q)})
    for _ in range(5):
        assert _press(disp, Qt.Key.Key_Q) is True
    assert counts[Action.ROTATE_QUOTE] == 5


# ── COALESCE guard ──────────────────────────────────────────────────────────────

def test_coalesce_leading_fire_then_one_trailing(qapp):
    disp, counts = _make({
        Action.TOGGLE_THEME: Binding(Qt.Key.Key_T, GuardKind.COOLDOWN_COALESCE, COOLDOWN_MS)
    })
    # First press fires immediately (leading edge).
    assert _press(disp, Qt.Key.Key_T) is True
    assert counts[Action.TOGGLE_THEME] == 1
    # A burst during the window is coalesced — none fire now.
    for _ in range(4):
        assert _press(disp, Qt.Key.Key_T) is True   # still 'ours', just throttled
    assert counts[Action.TOGGLE_THEME] == 1
    # After the window elapses, exactly ONE trailing fire lands.
    _pump(qapp, COOLDOWN_MS * 3)
    assert counts[Action.TOGGLE_THEME] == 2


def test_coalesce_burst_then_settle_yields_exactly_one_trailing(qapp):
    # A burst of N in-window presses collapses to exactly ONE trailing fire, no matter
    # how many were pressed — the defining "coalesce" property (last press lands, the
    # rest are absorbed). Two independent burst+settle cycles each add exactly one fire.
    disp, counts = _make({
        Action.TOGGLE_THEME: Binding(Qt.Key.Key_T, GuardKind.COOLDOWN_COALESCE, COOLDOWN_MS)
    })
    # Cycle 1: leading fire + a burst -> one trailing fire.
    _press(disp, Qt.Key.Key_T)                 # leading fire (count 1)
    for _ in range(6):
        _press(disp, Qt.Key.Key_T)             # all coalesced
    _pump(qapp, COOLDOWN_MS * 4)               # one trailing fire (count 2), window closes
    assert counts[Action.TOGGLE_THEME] == 2

    # Cycle 2 (window fully closed): a fresh leading fire + burst -> one more trailing.
    _press(disp, Qt.Key.Key_T)                 # fresh leading fire (count 3)
    for _ in range(6):
        _press(disp, Qt.Key.Key_T)             # coalesced
    _pump(qapp, COOLDOWN_MS * 4)               # one trailing fire (count 4)
    assert counts[Action.TOGGLE_THEME] == 4


def test_coalesce_press_after_idle_window_is_a_fresh_leading_fire(qapp):
    disp, counts = _make({
        Action.TOGGLE_THEME: Binding(Qt.Key.Key_T, GuardKind.COOLDOWN_COALESCE, COOLDOWN_MS)
    })
    _press(disp, Qt.Key.Key_T)          # leading fire (count 1)
    _pump(qapp, COOLDOWN_MS * 3)        # nothing pending -> no trailing fire, window closes
    assert counts[Action.TOGGLE_THEME] == 1
    _press(disp, Qt.Key.Key_T)          # window closed -> fresh leading fire
    assert counts[Action.TOGGLE_THEME] == 2


# ── DROP guard ──────────────────────────────────────────────────────────────────

def test_drop_leading_fire_then_no_trailing(qapp):
    disp, counts = _make({
        Action.SHOW_LIBRARY: Binding(Qt.Key.Key_L, GuardKind.COOLDOWN_DROP, COOLDOWN_MS)
    })
    assert _press(disp, Qt.Key.Key_L) is True
    assert counts[Action.SHOW_LIBRARY] == 1
    # Presses during the window are dropped outright.
    for _ in range(4):
        assert _press(disp, Qt.Key.Key_L) is True
    assert counts[Action.SHOW_LIBRARY] == 1
    # Critically: NO trailing fire after the window elapses.
    _pump(qapp, COOLDOWN_MS * 3)
    assert counts[Action.SHOW_LIBRARY] == 1
    # Once the window has fully lapsed, the next press is a fresh leading fire.
    assert _press(disp, Qt.Key.Key_L) is True
    assert counts[Action.SHOW_LIBRARY] == 2


# ── Dispatch bookkeeping ─────────────────────────────────────────────────────────

def test_unbound_key_returns_false_and_does_not_fire(qapp):
    disp, counts = _make({Action.ROTATE_QUOTE: Binding(Qt.Key.Key_Q)})
    assert _press(disp, Qt.Key.Key_X) is False
    assert counts[Action.ROTATE_QUOTE] == 0


def test_bound_key_returns_true_even_when_guard_suppresses(qapp):
    disp, counts = _make({
        Action.TOGGLE_THEME: Binding(Qt.Key.Key_T, GuardKind.COOLDOWN_COALESCE, COOLDOWN_MS)
    })
    _press(disp, Qt.Key.Key_T)                        # leading fire opens the window
    assert _press(disp, Qt.Key.Key_T) is True         # suppressed by guard, still consumed


def test_default_table_shape(qapp):
    # The shipped table maps the documented keys to the documented guards.
    assert DEFAULT_BINDINGS[Action.OPEN_CHAPTER_LIST].key == Qt.Key.Key_C
    assert DEFAULT_BINDINGS[Action.OPEN_CHAPTER_LIST].guard is GuardKind.NONE
    assert DEFAULT_BINDINGS[Action.TOGGLE_THEME].key == Qt.Key.Key_T
    assert DEFAULT_BINDINGS[Action.TOGGLE_THEME].guard is GuardKind.COOLDOWN_COALESCE
    assert DEFAULT_BINDINGS[Action.ROTATE_QUOTE].key == Qt.Key.Key_Q
    assert DEFAULT_BINDINGS[Action.ROTATE_QUOTE].guard is GuardKind.NONE
    assert DEFAULT_BINDINGS[Action.SHOW_LIBRARY].key == Qt.Key.Key_L
    assert DEFAULT_BINDINGS[Action.SHOW_LIBRARY].guard is GuardKind.COOLDOWN_DROP


def test_unregistered_action_is_a_silent_noop(qapp):
    # A bound action with no registered handler consumes the key but fires nothing
    # (the state where L's binding exists before its handler is wired).
    disp = ShortcutDispatcher(bindings={Action.SHOW_LIBRARY: Binding(Qt.Key.Key_L)})
    assert _press(disp, Qt.Key.Key_L) is True   # bound -> consumed, no handler -> no crash
