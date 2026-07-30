"""Shared `QLineEdit` subclass fixing word-selection loss after a double-click.

**The bug.** On this app's target desktop (KDE Plasma / Wayland), a `mouseMoveEvent` with
**zero displacement** can arrive a few tens of milliseconds after a double-click, while the
button is still down. `QLineEdit` treats any move in that window as the start of a drag-select:
it discards the word selection and re-anchors the cursor to the press position — mid-word. The
user sees a double-clicked word highlight, then silently hold only a prefix of itself.

Measured live, 2026-07-30, with no mouse movement in either case:

    DOUBLECLICK   sel='Shards'   cursor=6   click_x=21
    DRAG-CHANGED  sel='Sha'      cursor=3   x=21      <- same x, 40ms later
    DOUBLECLICK   sel='Clayton'  cursor=7   click_x=112
    DRAG-CHANGED  sel='Cl'       cursor=2   x=112     <- same x

The downstream damage is worse than the highlight: a following Ctrl+X or Cut acts on the
truncated selection, so cutting a double-clicked "Andrew" yields "And" and leaves "rew Kishino"
in the field. That is data loss in a metadata editor, not a cosmetic glitch.

**The same defect on a single click.** A stray move between press and release makes Qt
drag-select from the press point to the release point, so a click meant to place the caret
silently highlights a run of text instead. Measured live: a click on the `i` of "A Tale of Two
Cities" selected "A Tale of Two C", and a click in a narrator field produced

    DRAG-CHANGED  sel='Zara Ra'  cursor=7  x=42  was=''      <- no prior selection, no double-click

`was=''` and the absence of any `DOUBLECLICK` line identify it as a press-drag, and the selection
runs from the field's left edge to the click point — a shape a double-click cannot produce.

**The fix.** While a mouse button is down, ignore moves that have not travelled
`QApplication.startDragDistance()` (10px here). Past that distance the guard stands down and Qt
takes over, so a genuine drag-select still works from the first real movement — verified live,
where deliberate drags moved 10-25px immediately and selected correctly.

The anchor is set by both `mousePressEvent` and `mouseDoubleClickEvent` and cleared on release,
so it covers both entry points: a click places the caret, a double-click keeps its word, and only
deliberate movement selects.

**Use this instead of a bare `QLineEdit` for any new text input.** The defect is in Qt's own
handling and applies to every field in the app, not to one panel — it was first reported in Book
Detail's metadata fields and then independently in the Tags panel.
"""

from PySide6.QtCore import QElapsedTimer
from PySide6.QtWidgets import QLineEdit, QApplication

# A drag must be sustained, not instantaneous. Spurious movement arrives as a single event a few
# tens of ms after the press (measured: ~40ms after a double-click), so anything inside this
# window is treated as noise no matter how far it claims to have travelled — the distance check
# alone cannot catch a stray move that jumps well past the 10px threshold in one event, which is
# what left an occasional one-character selection after the first fix. A deliberate press-drag
# takes far longer than this to begin, so the window costs real drags nothing.
_DRAG_DWELL_MS = 120


class DragSafeLineEdit(QLineEdit):
    """QLineEdit that keeps a double-clicked word selected when a stationary move follows."""

    def __init__(self, parent=None):
        super().__init__(parent)
        # x where the current button-press began (plain press OR double-click). Held only
        # while the button is down. None means "not guarding" — either no button is down, or
        # the pointer has already travelled far enough to be a real drag.
        self._press_anchor_x = None
        # Time since that press, for the dwell check below.
        self._press_timer = QElapsedTimer()

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        self._press_anchor_x = event.position().toPoint().x()
        self._press_timer.start()

    def mouseDoubleClickEvent(self, event):
        super().mouseDoubleClickEvent(event)
        self._press_anchor_x = event.position().toPoint().x()
        self._press_timer.start()

    def mouseMoveEvent(self, event):
        anchor = self._press_anchor_x
        if anchor is not None:
            far_enough = (abs(event.position().toPoint().x() - anchor)
                          >= QApplication.startDragDistance())
            held_long_enough = self._press_timer.elapsed() >= _DRAG_DWELL_MS
            if not (far_enough and held_long_enough):
                # Not yet a real drag — either it hasn't travelled far enough, or it moved too
                # soon after the press to be intentional. Consume it so QLineEdit never starts
                # a drag-select.
                #
                # After a DOUBLE-click this preserves the word selection, which Qt would
                # otherwise discard, re-anchoring the caret mid-word ('Shards' -> 'Sha').
                #
                # After a SINGLE click it stops a click from silently becoming a selection:
                # a stray move between press and release made Qt select from the press point
                # to the release point, so clicking into a field mid-word could highlight
                # everything before the caret ('A Tale of Two C' from a click on the 'i').
                # A click should place the caret; only a deliberate drag should select.
                event.accept()
                return
            # Far enough AND sustained: a real drag. Stand down for the rest of this press.
            self._press_anchor_x = None
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._press_anchor_x = None
        super().mouseReleaseEvent(event)
