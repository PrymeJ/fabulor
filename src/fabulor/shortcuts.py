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

Key-matching note: matching is on ``(event.key(), modifiers)`` where ``modifiers`` is
``event.modifiers()`` masked to Shift/Ctrl/Alt (see ``_MODIFIER_MASK``). A binding's
``modifiers`` defaults to ``NoModifier``, so bare-key bindings (C/T/Q/L/...) match only an
unmodified press — this is a deliberate change from the original modifier-ignoring behavior
(where Ctrl+T also rotated the theme), made when the transport shortcuts added genuinely
modified combos (Shift/Ctrl/Alt+arrow) that must be told apart from their bare-key siblings
(e.g. bare ``Up`` = volume vs. ``Alt+Up`` = speed). The mask excludes ``KeypadModifier`` and
other stray bits so a numeric-keypad or platform-set flag on an arrow press can't defeat a
bare-key binding's match.

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


# Only these modifiers participate in key matching. event.modifiers() is masked to this
# before lookup, so KeypadModifier (which Qt sets on some arrow-key presses) and other
# stray bits can't stop a bare-key binding (NoModifier) from matching. See module docstring.
_MODIFIER_MASK = (
    Qt.KeyboardModifier.ShiftModifier
    | Qt.KeyboardModifier.ControlModifier
    | Qt.KeyboardModifier.AltModifier
)


class Action(Enum):
    """Semantic MainWindow-level actions. Not key literals — the key lives in the
    binding table so it can be rebound without touching handler wiring."""
    OPEN_CHAPTER_LIST = auto()
    TOGGLE_THEME = auto()
    ROTATE_QUOTE = auto()
    SHOW_LIBRARY = auto()
    SHOW_TAGS = auto()
    SHOW_PLAYBACK = auto()
    SHOW_STATS = auto()
    SHOW_SETTINGS = auto()
    SHOW_SLEEP = auto()
    # Transport / player actions (added alongside modifier support). Availability gating
    # (no book loaded, undo affordance not shown, etc.) lives in each MainWindow handler.
    PLAY_PAUSE = auto()
    VOLUME_UP = auto()
    VOLUME_DOWN = auto()
    LONG_SKIP_BACK = auto()
    LONG_SKIP_FORWARD = auto()
    CHAPTER_PREV = auto()
    CHAPTER_NEXT = auto()
    SPEED_UP = auto()
    SPEED_DOWN = auto()
    MUTE = auto()
    UNDO = auto()


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
    """A key (+ optional modifiers) + its spam-guard. ``cooldown_ms`` is ignored when
    ``guard`` is NONE."""
    key: Qt.Key
    guard: GuardKind = GuardKind.NONE
    cooldown_ms: int = 0
    allow_autorepeat: bool = False
    modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier
    """Modifiers that must be held for this binding to match, masked to Shift/Ctrl/Alt.
    Defaults to NoModifier (a bare-key binding — matches only an unmodified press). Set e.g.
    ``ShiftModifier`` so ``Shift+Left`` is told apart from bare ``Left`` and ``Ctrl+Left``,
    which now key on distinct ``(key, modifiers)`` pairs."""
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
    # G/P/A/S/Z mirror SHOW_LIBRARY exactly: open-only (never close their own panel),
    # COOLDOWN_DROP so a spammed key can't double-fire mid-slide. Each handler's
    # availability gate matches that panel's actual mouse-reachability (see app.py).
    Action.SHOW_TAGS:         Binding(Qt.Key.Key_G, GuardKind.COOLDOWN_DROP, 500),
    Action.SHOW_PLAYBACK:     Binding(Qt.Key.Key_P, GuardKind.COOLDOWN_DROP, 500),
    Action.SHOW_STATS:        Binding(Qt.Key.Key_A, GuardKind.COOLDOWN_DROP, 500),
    Action.SHOW_SETTINGS:     Binding(Qt.Key.Key_S, GuardKind.COOLDOWN_DROP, 500),
    Action.SHOW_SLEEP:        Binding(Qt.Key.Key_Z, GuardKind.COOLDOWN_DROP, 500),

    # Transport / player keys. All GuardKind.NONE (fire on every press — no leading/coalesce
    # semantics apply to a play/pause toggle or a per-step nudge). Volume/speed opt into
    # allow_autorepeat so holding the key repeats the step; speed additionally self-throttles
    # inside its handler (raw OS repeat rate is too fast at 0.05 increments).
    Action.PLAY_PAUSE:        Binding(Qt.Key.Key_Space),
    Action.VOLUME_UP:         Binding(Qt.Key.Key_Up,   allow_autorepeat=True),
    Action.VOLUME_DOWN:       Binding(Qt.Key.Key_Down, allow_autorepeat=True),
    Action.LONG_SKIP_BACK:    Binding(Qt.Key.Key_Left,  modifiers=Qt.KeyboardModifier.ShiftModifier),
    Action.LONG_SKIP_FORWARD: Binding(Qt.Key.Key_Right, modifiers=Qt.KeyboardModifier.ShiftModifier),
    Action.CHAPTER_PREV:      Binding(Qt.Key.Key_Left,  modifiers=Qt.KeyboardModifier.ControlModifier),
    Action.CHAPTER_NEXT:      Binding(Qt.Key.Key_Right, modifiers=Qt.KeyboardModifier.ControlModifier),
    Action.SPEED_UP:          Binding(Qt.Key.Key_Up,   allow_autorepeat=True, modifiers=Qt.KeyboardModifier.AltModifier),
    Action.SPEED_DOWN:        Binding(Qt.Key.Key_Down, allow_autorepeat=True, modifiers=Qt.KeyboardModifier.AltModifier),
    Action.MUTE:              Binding(Qt.Key.Key_M),
    Action.UNDO:              Binding(Qt.Key.Key_U),
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
        # Keyed by (Qt.Key int, masked-modifiers int) so e.g. Left / Shift+Left / Ctrl+Left
        # are three distinct bindings rather than colliding on the bare key. Note: Qt.Key is
        # int-backed (int() works), but Qt.KeyboardModifier is a Flag — use .value for it.
        self._key_to_action: dict[tuple[int, int], Action] = {
            (int(binding.key), (binding.modifiers & _MODIFIER_MASK).value): action
            for action, binding in self._bindings.items()
        }
        # True only while a handler triggered by an autorepeat tick is executing. Handlers
        # that self-throttle held-key repeat (e.g. speed nudge) read this via is_autorepeat.
        self._current_is_autorepeat = False

    @property
    def is_autorepeat(self) -> bool:
        """Whether the handler currently executing was fired by a held-key autorepeat tick.
        Valid only during a handler call; False otherwise. Lets a handler distinguish a
        single tap from a repeat without the dispatcher passing the event through."""
        return self._current_is_autorepeat

    def register(self, action: Action, handler: Callable[[], None]) -> None:
        """Bind a no-arg callable to an action. Overwrites any prior handler."""
        self._handlers[action] = handler

    def handle_key_event(self, event) -> bool:
        """Dispatch a QKeyEvent. Returns True iff the key is bound AND handled here (the
        caller should then NOT pass the event on). A bound key returns True even when its
        guard suppresses the fire — the key is still 'ours', it's just throttled. But a
        held-key autorepeat tick on a binding that disallows repeat returns False (same
        as an unbound key), so the caller's fallthrough to super() is consistent."""
        modifiers = (event.modifiers() & _MODIFIER_MASK).value
        action = self._key_to_action.get((event.key(), modifiers))
        if action is None:
            return False
        binding = self._bindings[action]
        if event.isAutoRepeat() and not binding.allow_autorepeat:
            return False
        guard = self._guards.get(action)
        if guard is None or guard.allow():
            self._current_is_autorepeat = event.isAutoRepeat()
            try:
                self._fire(action)
            finally:
                self._current_is_autorepeat = False
        return True

    def _fire(self, action: Action) -> None:
        handler = self._handlers.get(action)
        if handler is not None:
            handler()
