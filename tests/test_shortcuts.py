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


def _press(dispatcher, key, autorepeat=False,
           modifiers=Qt.KeyboardModifier.NoModifier):
    """Deliver a synthetic key press to the dispatcher; return whether it was consumed.
    Pass autorepeat=True to simulate a held-key repeat tick (QKeyEvent's autorep flag),
    and modifiers=... to test modified combos (Shift/Ctrl/Alt+key)."""
    ev = QKeyEvent(QEvent.Type.KeyPress, key, modifiers, "", autorepeat)
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


# ── Autorepeat (per-binding) ─────────────────────────────────────────────────────

def test_autorepeat_suppressed_by_default(qapp):
    # A held-key repeat tick on a default (allow_autorepeat=False) binding does NOT
    # fire and returns False (falls through like an unbound key), while a genuine
    # non-autorepeat press of the same key still fires normally.
    disp, counts = _make({Action.OPEN_CHAPTER_LIST: Binding(Qt.Key.Key_C)})
    assert _press(disp, Qt.Key.Key_C, autorepeat=True) is False
    assert counts[Action.OPEN_CHAPTER_LIST] == 0
    assert _press(disp, Qt.Key.Key_C) is True
    assert counts[Action.OPEN_CHAPTER_LIST] == 1


def test_autorepeat_allowed_when_binding_opts_in(qapp):
    # The mechanism the future skip/volume/chapter-skip bindings will need: a binding
    # built with allow_autorepeat=True fires on a repeat tick. Uses a real action slot
    # with an arbitrary key — the point is the flag, not which action it maps to.
    disp, counts = _make({
        Action.SHOW_LIBRARY: Binding(Qt.Key.Key_L, allow_autorepeat=True)
    })
    assert _press(disp, Qt.Key.Key_L, autorepeat=True) is True
    assert counts[Action.SHOW_LIBRARY] == 1


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
    # The panel-open family (G/P/A/S/Z) mirrors L: same key mapping, same DROP guard.
    for action, key in (
        (Action.SHOW_TAGS, Qt.Key.Key_G),
        (Action.SHOW_PLAYBACK, Qt.Key.Key_P),
        (Action.SHOW_STATS, Qt.Key.Key_A),
        (Action.SHOW_SETTINGS, Qt.Key.Key_S),
        (Action.SHOW_SLEEP, Qt.Key.Key_Z),
    ):
        assert DEFAULT_BINDINGS[action].key == key
        assert DEFAULT_BINDINGS[action].guard is GuardKind.COOLDOWN_DROP
    # Volume/speed/seek/chapter-nav/long-skip repeat on hold; panel-open/theme/etc. don't.
    autorepeating = {a for a, b in DEFAULT_BINDINGS.items() if b.allow_autorepeat}
    assert autorepeating == {
        Action.VOLUME_UP, Action.VOLUME_DOWN, Action.SPEED_UP, Action.SPEED_DOWN,
        Action.SEEK_BACK, Action.SEEK_FORWARD,
        Action.LONG_SKIP_BACK, Action.LONG_SKIP_FORWARD,
        Action.CHAPTER_PREV, Action.CHAPTER_NEXT,
    }
    # No two actions share a (key, modifiers) pair — the uniqueness that keeps bare Up
    # (volume) distinct from Alt+Up (speed) and Shift/Ctrl+Left distinct from each other.
    pairs = [(b.key, b.modifiers) for b in DEFAULT_BINDINGS.values()]
    assert len(pairs) == len(set(pairs))


def test_unregistered_action_is_a_silent_noop(qapp):
    # A bound action with no registered handler consumes the key but fires nothing
    # (the state where L's binding exists before its handler is wired).
    disp = ShortcutDispatcher(bindings={Action.SHOW_LIBRARY: Binding(Qt.Key.Key_L)})
    assert _press(disp, Qt.Key.Key_L) is True   # bound -> consumed, no handler -> no crash


# ── Transport keys + modifier matching ───────────────────────────────────────────

def test_transport_bindings_fire_their_actions(qapp):
    # Each transport binding, delivered with its exact key+modifiers, fires exactly its
    # own action against the SHIPPED default table.
    disp, counts = _make(DEFAULT_BINDINGS)
    cases = [
        (Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier,      Action.PLAY_PAUSE),
        (Qt.Key.Key_Up,    Qt.KeyboardModifier.NoModifier,      Action.VOLUME_UP),
        (Qt.Key.Key_Down,  Qt.KeyboardModifier.NoModifier,      Action.VOLUME_DOWN),
        (Qt.Key.Key_Left,  Qt.KeyboardModifier.NoModifier,      Action.SEEK_BACK),
        (Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier,      Action.SEEK_FORWARD),
        (Qt.Key.Key_Left,  Qt.KeyboardModifier.ShiftModifier,   Action.LONG_SKIP_BACK),
        (Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier,   Action.LONG_SKIP_FORWARD),
        (Qt.Key.Key_Left,  Qt.KeyboardModifier.ControlModifier, Action.CHAPTER_PREV),
        (Qt.Key.Key_Right, Qt.KeyboardModifier.ControlModifier, Action.CHAPTER_NEXT),
        (Qt.Key.Key_Up,    Qt.KeyboardModifier.AltModifier,     Action.SPEED_UP),
        (Qt.Key.Key_Down,  Qt.KeyboardModifier.AltModifier,     Action.SPEED_DOWN),
        (Qt.Key.Key_M,     Qt.KeyboardModifier.NoModifier,      Action.MUTE),
        (Qt.Key.Key_U,     Qt.KeyboardModifier.NoModifier,      Action.UNDO),
    ]
    for key, mods, action in cases:
        assert _press(disp, key, modifiers=mods) is True
        assert counts[action] == 1, f"{action} should have fired once for {key}/{mods}"


def test_modifier_disambiguates_same_key(qapp):
    # The whole point of adding modifier support: bare Up != Alt+Up, and bare Left,
    # Shift+Left, and Ctrl+Left are three different actions on the same physical key.
    disp, counts = _make(DEFAULT_BINDINGS)

    assert _press(disp, Qt.Key.Key_Up) is True              # bare -> volume, not speed
    assert counts[Action.VOLUME_UP] == 1
    assert counts[Action.SPEED_UP] == 0

    assert _press(disp, Qt.Key.Key_Up,
                  modifiers=Qt.KeyboardModifier.AltModifier) is True  # Alt -> speed
    assert counts[Action.SPEED_UP] == 1
    assert counts[Action.VOLUME_UP] == 1                    # unchanged

    assert _press(disp, Qt.Key.Key_Left,
                  modifiers=Qt.KeyboardModifier.ShiftModifier) is True
    assert counts[Action.LONG_SKIP_BACK] == 1
    assert counts[Action.CHAPTER_PREV] == 0

    assert _press(disp, Qt.Key.Key_Left,
                  modifiers=Qt.KeyboardModifier.ControlModifier) is True
    assert counts[Action.CHAPTER_PREV] == 1
    assert counts[Action.LONG_SKIP_BACK] == 1               # unchanged

    # Bare Left -> seek, not long-skip or chapter-nav.
    assert _press(disp, Qt.Key.Key_Left) is True
    assert counts[Action.SEEK_BACK] == 1
    assert counts[Action.LONG_SKIP_BACK] == 1                # unchanged
    assert counts[Action.CHAPTER_PREV] == 1                  # unchanged


def test_keypad_modifier_does_not_defeat_bare_binding(qapp):
    # Qt sets KeypadModifier on some arrow-key presses; the mask strips it so bare Up
    # (VOLUME_UP) still matches even when the event carries KeypadModifier.
    disp, counts = _make(DEFAULT_BINDINGS)
    assert _press(disp, Qt.Key.Key_Up,
                  modifiers=Qt.KeyboardModifier.KeypadModifier) is True
    assert counts[Action.VOLUME_UP] == 1
    assert counts[Action.SPEED_UP] == 0


def test_ctrl_t_no_longer_matches_bare_theme_binding(qapp):
    # Adding real modifier support means a bare-key binding matches only NoModifier now —
    # Ctrl+T no longer rotates the theme (documented behavior change), bare T still does.
    disp, counts = _make(DEFAULT_BINDINGS)
    assert _press(disp, Qt.Key.Key_T,
                  modifiers=Qt.KeyboardModifier.ControlModifier) is False
    assert counts[Action.TOGGLE_THEME] == 0
    assert _press(disp, Qt.Key.Key_T) is True
    assert counts[Action.TOGGLE_THEME] == 1


def test_is_autorepeat_reflects_current_dispatch(qapp):
    # The flag the speed-nudge handler reads to self-throttle held-key repeats: True only
    # while a repeat-sourced handler runs, False for a tap, False again after dispatch.
    seen = []
    disp = ShortcutDispatcher(bindings={
        Action.VOLUME_UP: Binding(Qt.Key.Key_Up, allow_autorepeat=True)
    })
    disp.register(Action.VOLUME_UP, lambda: seen.append(disp.is_autorepeat))

    _press(disp, Qt.Key.Key_Up, autorepeat=False)
    _press(disp, Qt.Key.Key_Up, autorepeat=True)
    assert seen == [False, True]
    assert disp.is_autorepeat is False   # reset after each dispatch
