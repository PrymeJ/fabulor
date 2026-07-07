"""Data-driven dispatcher for MainWindow-level global key bindings.

Fabulor's global keys (``C`` open chapter list, ``T`` rotate theme, ``Q`` rotate
quote, ``L`` open library) were previously a hand-written if/elif chain in
``MainWindow.keyPressEvent``, with the theme key's spam-guard implemented as loose
``MainWindow`` timer attributes. This module replaces that with three pieces a future
Settings-configurable-bindings feature can extend without rework:

- an :class:`Action` enum of *semantic* actions (never key literals),
- a :data:`DEFAULT_BINDINGS` table (``Action`` -> :class:`Binding`) that a later
  Config-backed source can swap out wholesale — the dispatcher takes the table as a
  constructor argument, so persistence is a matter of building a different dict, not
  touching this file, and
- a per-binding *declarative* spam-guard (:class:`GuardKind`), so no action handler
  reimplements timer bookkeeping.

Scope boundary: this owns ONLY the "is this key bound + does its spam-guard allow it to
fire right now" decision. Action-*availability* gating that depends on app state (e.g.
"the chapter label is only clickable with 2+ chapters", "the quote only rotates in the
no-book state", "the library button is hidden in the empty state") stays inside each
action's registered handler — the dispatcher never inspects app state. This mirrors the
composition philosophy in ``book_switch.py``: one object owns one concern and composes
with the orthogonal guards rather than absorbing them.

Key-matching parity note: matching is on ``event.key()`` vs ``Qt.Key`` and deliberately
ignores modifiers, because that is exactly what the pre-migration code did (Ctrl+T
rotated the theme). Strict ``QKeySequence`` matching would *change* behavior, so
``Binding.key`` stays a bare ``Qt.Key`` until configurability lands and can widen it.

Autorepeat is a per-binding property (``Binding.allow_autorepeat``), NOT a global
dispatcher rule: all of today's bindings suppress held-key repeat (holding C otherwise
re-toggles the chapter dropdown every tick, holding T spams rotations), but a future
hold-to-repeat binding (skip/seek/volume — see KEYBINDINGS.md) can opt in. A
dispatcher-wide block would silently break those the moment they're added.
"""

from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable, Optional

from PySide6.QtCore import Qt, QObject, QTimer


class Action(Enum):
    """Semantic MainWindow-level actions. Not key literals — the key lives in the
    binding table so it can be rebound without touching handler wiring."""
    OPEN_CHAPTER_LIST = auto()
    TOGGLE_THEME = auto()
    ROTATE_QUOTE = auto()
    SHOW_LIBRARY = auto()


class GuardKind(Enum):
    """How rapid repeat presses of a binding are throttled."""
    NONE = auto()
    """Fire on every press. No timer."""

    COOLDOWN_COALESCE = auto()
    """Leading-edge fire, then a cooldown window. Presses during the window are
    coalesced into exactly ONE trailing fire when the window elapses, which restarts
    the window. Sustained spamming yields one fire per ``cooldown_ms``. This is the
    theme key's historical behavior — the last press always eventually lands."""

    COOLDOWN_DROP = auto()
    """Leading-edge fire, then a cooldown window. Presses during the window are
    dropped with NO trailing fire. For actions where a repeat is meaningless rather
    than merely throttled (you can't open an already-open panel), so a queued trailing
    fire would be wrong, not just redundant."""


@dataclass(frozen=True)
class Binding:
    """A key + its spam-guard. ``cooldown_ms`` is ignored when ``guard`` is NONE."""
    key: Qt.Key
    guard: GuardKind = GuardKind.NONE
    cooldown_ms: int = 0
    allow_autorepeat: bool = False
    """Whether a held-key autorepeat tick dispatches. Defaults False: none of today's
    bindings (C/T/Q/L) make sense held down — holding C otherwise re-toggles the chapter
    dropdown on every repeat, holding T would spam rotations, etc. Set True for a future
    binding that genuinely wants hold-to-repeat — e.g. the held Left/Right skip and
    Up/Down chapter-skip/volume keys sketched in KEYBINDINGS.md's planned-keys section,
    which will live in this same global dispatcher. Without this flag those would work on
    a single tap and silently NOT repeat on hold — an easy-to-miss regression."""


# Default table. A future Config-backed source builds an equivalent dict and passes it
# to ShortcutDispatcher(...) — nothing here needs to change for that.
DEFAULT_BINDINGS: dict[Action, Binding] = {
    Action.OPEN_CHAPTER_LIST: Binding(Qt.Key.Key_C),
    Action.TOGGLE_THEME:      Binding(Qt.Key.Key_T, GuardKind.COOLDOWN_COALESCE, 2000),
    # TODO: remove before release — testing only (Q rotates the no-book quote)
    Action.ROTATE_QUOTE:      Binding(Qt.Key.Key_Q),
    Action.SHOW_LIBRARY:      Binding(Qt.Key.Key_L, GuardKind.COOLDOWN_DROP, 500),
}


class _GuardState:
    """Per-binding runtime state for the cooldown guards. One instance per guarded
    action, held by the dispatcher. NONE-guarded actions get no _GuardState."""

    def __init__(self, dispatcher: "ShortcutDispatcher", action: Action, binding: Binding):
        self._dispatcher = dispatcher
        self._action = action
        self._binding = binding
        self._pending = False
        self._timer = QTimer(dispatcher)
        self._timer.setSingleShot(True)
        self._timer.setInterval(binding.cooldown_ms)
        self._timer.timeout.connect(self._on_timeout)

    def allow(self) -> bool:
        """Called on each press. Returns True if the handler should fire NOW.

        Encodes both cooldown guards: the leading-edge fire is identical for COALESCE
        and DROP; they differ only in whether an in-window press is remembered for a
        trailing fire."""
        if not self._timer.isActive():
            self._timer.start()
            return True
        if self._binding.guard is GuardKind.COOLDOWN_COALESCE:
            self._pending = True
        return False

    def _on_timeout(self):
        # Mirrors the old _on_theme_rotate_cooldown exactly: if a press was coalesced,
        # fire once now and restart the window. DROP never sets _pending, so it simply
        # lets the window lapse.
        if self._pending:
            self._pending = False
            self._dispatcher._fire(self._action)
            self._timer.start()


class ShortcutDispatcher(QObject):
    """Maps key events to registered action handlers, applying each binding's guard.

    ``MainWindow.keyPressEvent`` delegates to :meth:`handle_key_event`. Handlers are
    registered by the owner and invoked with no arguments (no action here needs the
    keystroke). The dispatcher does not gate on app state — that lives in the handlers."""

    def __init__(self, parent: Optional[QObject] = None,
                 bindings: Optional[dict[Action, Binding]] = None):
        super().__init__(parent)
        self._bindings = dict(bindings if bindings is not None else DEFAULT_BINDINGS)
        self._handlers: dict[Action, Callable[[], None]] = {}
        self._guards: dict[Action, _GuardState] = {
            action: _GuardState(self, action, binding)
            for action, binding in self._bindings.items()
            if binding.guard is not GuardKind.NONE
        }
        self._key_to_action: dict[int, Action] = {
            int(binding.key): action for action, binding in self._bindings.items()
        }

    def register(self, action: Action, handler: Callable[[], None]) -> None:
        """Bind a no-arg callable to an action. Overwrites any prior handler."""
        self._handlers[action] = handler

    def handle_key_event(self, event) -> bool:
        """Dispatch a QKeyEvent. Returns True iff the key is bound AND handled here (the
        caller should then NOT pass the event on). A bound key returns True even when its
        guard suppresses the fire — the key is still 'ours', it's just throttled. But a
        held-key autorepeat tick on a binding that disallows repeat returns False (same
        as an unbound key), so the caller's fallthrough to super() is consistent."""
        action = self._key_to_action.get(event.key())
        if action is None:
            return False
        binding = self._bindings[action]
        if event.isAutoRepeat() and not binding.allow_autorepeat:
            return False
        guard = self._guards.get(action)
        if guard is None or guard.allow():
            self._fire(action)
        return True

    def _fire(self, action: Action) -> None:
        handler = self._handlers.get(action)
        if handler is not None:
            handler()
