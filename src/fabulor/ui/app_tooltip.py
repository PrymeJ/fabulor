"""Tooltips drawn inside the main window instead of as Qt popup windows.

**Why not Qt's tooltips.** Qt shows a tooltip as its own top-level window and
only keeps it on the SCREEN, so near the edge of this fixed 300x564 window it
spills out. Correcting its position after Qt creates it does not work on
native Wayland: the compositor keeps the position Qt first asked for
(measured 2026-11-16 with a probe — every corrective move was followed by a
Move event putting the tooltip back). A child widget of the main window
cannot be drawn outside it, so containment holds by construction.

**How it is wired.** One application-wide filter (see `install`) catches the
`QEvent.ToolTip` Qt sends to any widget in the main window, reads that
widget's tooltip text (or the hovered item's, for item views like the
Library folder list), shows it here, and consumes the event so Qt never
opens its own window. Widgets keep calling `setToolTip()` as before. Code
that showed tooltips by hand (`QToolTip.showText`, the Heatmap) calls
`show_text()`/`hide_text()` from this module instead.

**Placement.** Always vertically clear of the cursor, so it never covers the
pointer: below it if it fits, otherwise above. Horizontally it starts just
right of the cursor and slides left as far as needed to stay inside the
window, so it uses the full window width and stays on one line. Only text
wider than the whole window (minus a margin) wraps.

**Styling.** `QLabel#app_tooltip` in get_base_stylesheet (themes.py). A
`context` property selects per-source spacing (`heatmap` for the Heatmap's
multi-line HTML tooltip), derived from the source widget's class or an
ancestor's in `_CONTEXT_BY_CLASS`.

**The blur grab.** `transport_bar_blur` photographs the main window several
times a second; a visible tooltip would be baked into the frosted backdrop.
It calls `suppress_for_grab()` around its grab.
"""
from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QAbstractItemView, QLabel, QWidget

# Gap between the window border and the tooltip, in pixels.
_WINDOW_MARGIN = 4
# Below the cursor: clears the arrow pointer's hotspot-to-tip height.
_BELOW_CURSOR = 20
# Above the cursor: the hotspot is the arrow's tip, so less is needed.
_ABOVE_CURSOR = 6
# Horizontal start relative to the cursor, before sliding to fit.
_RIGHT_OF_CURSOR = 2
# Qt hides its own tooltips after 10s; match it.
_HIDE_AFTER_MS = 10_000
# Our own hover delay, matching Qt's (SH_ToolTip_WakeUpDelay 700ms). Shorter
# when a tooltip was just showing, like Qt's "fall asleep" window, so moving
# between tooltipped widgets doesn't wait the full delay each time.
_WAKE_DELAY_MS = 700
_WAKE_DELAY_AWAKE_MS = 100
_AWAKE_WINDOW_S = 2.0

# Class name of the source widget or an ancestor -> value of the tooltip's
# `context` property, which selects per-context spacing in themes.py.
_CONTEXT_BY_CLASS = {
    "HourlyHeatmap": "heatmap",
}

_instance = None  # the AppTooltip, set by install()
# >0 while transport_bar_blur's grab is hiding/showing panels; see
# suppress_for_grab.
_grab_depth = 0


class AppTooltip(QLabel):
    """The single in-window tooltip label. One instance, owned by MainWindow."""

    def __init__(self, window: QWidget):
        super().__init__(window)
        self._window = window
        self.setObjectName("app_tooltip")
        self.setTextFormat(Qt.TextFormat.AutoText)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        # Always-on chrome outside any panel must be NoFocus — see CLAUDE.md's
        # keyboard focus ownership rule (the NoFocus sweep).
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.hide()
        self._source = None
        self._source_index = None   # item-view tooltips: the hovered index
        self._text = None
        self._context = None
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(lambda: self.hide_tip("timeout"))
        self._grab_hidden = False

    # -- public -----------------------------------------------------------

    def show_tip(self, text: str, source: QWidget, global_pos: QPoint, index=None):
        if not text:
            self.hide_tip("empty text")
            return
        same = (self.isVisible() and source is self._source
                and text == self._text and index == self._source_index)
        self._hide_timer.start(_HIDE_AFTER_MS)
        if same:
            return  # like Qt: an unchanged tooltip stays where it is
        self._source = source
        self._source_index = index
        self._text = text
        self._apply_context(source)
        self.setText(text)
        self._fit_size()
        self.move(self._place(global_pos))
        self.show()
        self.raise_()

    def hide_tip(self, reason="unspecified"):
        if self.isVisible() and getattr(self, "_filter", None) is not None:
            self._filter.note_visible()
        self._hide_timer.stop()
        self._source = None
        self._source_index = None
        self._text = None
        self.hide()

    @property
    def source(self):
        return self._source

    @property
    def source_index(self):
        return self._source_index

    # -- layout -----------------------------------------------------------

    def _apply_context(self, source):
        context = None
        w = source
        while w is not None and w is not self._window:
            context = _CONTEXT_BY_CLASS.get(type(w).__name__)
            if context:
                break
            w = w.parentWidget()
        if context != self._context:
            self._context = context
            self.setProperty("context", context or "")
            self.style().unpolish(self)
            self.style().polish(self)

    def _fit_size(self):
        """One line at its natural width; wrap only past the window width."""
        avail = self._window.width() - 2 * _WINDOW_MARGIN
        self.setWordWrap(False)
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)
        hint = self.sizeHint()
        if hint.width() <= avail:
            self.resize(hint)
            return
        self.setWordWrap(True)
        self.resize(avail, self.heightForWidth(avail))

    def _place(self, global_pos: QPoint) -> QPoint:
        return place_tip(
            self._window.mapFromGlobal(global_pos),
            self.width(), self.height(),
            self._window.width(), self._window.height())


def place_tip(cursor: QPoint, w: int, h: int, win_w: int, win_h: int) -> QPoint:
    """Top-left for a w x h tooltip in a win_w x win_h window, cursor in
    window coordinates. Pure arithmetic, tested headless."""
    x = cursor.x() + _RIGHT_OF_CURSOR
    x = min(x, win_w - _WINDOW_MARGIN - w)
    x = max(x, _WINDOW_MARGIN)
    y = cursor.y() + _BELOW_CURSOR
    if y + h > win_h - _WINDOW_MARGIN:
        y = cursor.y() - _ABOVE_CURSOR - h
    y = max(y, _WINDOW_MARGIN)
    return QPoint(x, y)


class _TooltipFilter(QObject):
    """Application-wide: turns Qt's ToolTip events into AppTooltip shows and
    hides it on leave, click, wheel or key. Never consumes anything but the
    ToolTip event itself."""

    _tip = None  # class default: events can arrive before __init__ finishes

    _HOVER_EVENTS = (QEvent.Type.Enter, QEvent.Type.HoverEnter,
                     QEvent.Type.HoverMove, QEvent.Type.MouseMove)
    _INPUT_EVENTS = (QEvent.Type.MouseButtonPress, QEvent.Type.Wheel,
                     QEvent.Type.KeyPress)

    def __init__(self, tip: AppTooltip, window: QWidget):
        super().__init__(tip)
        self._tip = tip
        self._window = window
        # Our own hover delay. Qt's never completes while the blur grab runs:
        # its 700ms wait restarts on every panel hide/show (~64ms apart), so
        # Qt sent no ToolTip event at all with the blur on and a book playing
        # (measured 2026-11-16: zero ToolTip events across a 4s hover while
        # grabs logged every 64ms; events arrived only while grabs were idle).
        self._pending = None          # (source widget, item index or None)
        self._last_visible_at = 0.0   # time.monotonic() when a tip was last up
        self._wake = QTimer(self)
        self._wake.setSingleShot(True)
        self._wake.timeout.connect(self._on_wake)

    def eventFilter(self, obj, event):
        if self._tip is None:
            return False
        t = event.type()
        if t == QEvent.Type.ToolTip:
            return self._on_tooltip_event(obj, event)
        if _grab_depth == 0:
            if t in self._HOVER_EVENTS:
                self._on_hover(obj, event)
            elif t == QEvent.Type.Leave and self._pending and obj is self._pending[0]:
                self._cancel_pending()
            elif t in self._INPUT_EVENTS:
                self._cancel_pending()
        tip = self._tip
        if not tip.isVisible():
            return False
        if t in self._INPUT_EVENTS:
            tip.hide_tip(f"input {t.name}")
        elif (obj is tip.source and t in (QEvent.Type.Leave, QEvent.Type.Hide)
              and _grab_depth == 0):
            # During a blur grab the panel is hidden and re-shown, which sends
            # Hide and Leave to every widget in it; those are not the user.
            tip.hide_tip(f"source {t.name}")
        elif (obj is tip.source and tip.source_index is not None
              and t in (QEvent.Type.MouseMove, QEvent.Type.HoverMove)):
            view = obj.parentWidget()
            if isinstance(view, QAbstractItemView):
                if view.indexAt(event.position().toPoint()) != tip.source_index:
                    tip.hide_tip("item changed")
        return False

    # -- our own hover delay ---------------------------------------------

    def _candidate(self, obj, event):
        """(source, index, text) for what is under the cursor, or None.
        Mirrors _on_tooltip_event: an item view's viewport uses the hovered
        item's ToolTipRole; any other widget uses its own toolTip() or the
        nearest ancestor's (Qt propagates ToolTip events to parents)."""
        if not isinstance(obj, QWidget):
            return None
        try:
            if obj.window() is not self._window:
                return None
        except RuntimeError:
            return None
        view = obj.parentWidget()
        if isinstance(view, QAbstractItemView) and obj is view.viewport():
            pos_fn = getattr(event, "position", None)
            if pos_fn is None:
                return None
            index = view.indexAt(pos_fn().toPoint())
            text = index.data(Qt.ItemDataRole.ToolTipRole) if index.isValid() else None
            return (obj, index, str(text)) if text else None
        w = obj
        while w is not None and w is not self._window:
            if w is self._tip:
                return None
            text = w.toolTip()
            if text:
                return (w, None, text)
            w = w.parentWidget()
        return None

    def _on_hover(self, obj, event):
        cand = self._candidate(obj, event)
        if cand is None:
            # Only an event on the pending source itself (or inside it) can
            # mean the cursor left that source's tooltip area. Hover/Enter
            # events also reach QWindow objects, which are not QWidgets and
            # make isAncestorOf() raise (seen 2026-11-17), so skip them.
            if not isinstance(obj, QWidget):
                return
            if self._pending and (obj is self._pending[0]
                                  or self._pending[0].isAncestorOf(obj)):
                self._cancel_pending()
            return
        source, index, _text = cand
        key = (source, index)
        tip = self._tip
        if tip.isVisible() and tip.source is source and tip.source_index == index:
            return
        if self._pending == key:
            return
        self._pending = key
        import time
        awake = tip.isVisible() or (time.monotonic() - self._last_visible_at) < _AWAKE_WINDOW_S
        self._wake.start(_WAKE_DELAY_AWAKE_MS if awake else _WAKE_DELAY_MS)

    def _cancel_pending(self):
        self._pending = None
        self._wake.stop()

    def _on_wake(self):
        pending, self._pending = self._pending, None
        if pending is None:
            return
        source, index = pending
        try:
            if not source.isVisible():
                return
            local = source.mapFromGlobal(QCursor.pos())
        except RuntimeError:
            return
        if not source.rect().contains(local):
            return
        if index is not None:
            view = source.parentWidget()
            if view.indexAt(local) != index:
                return
            text = index.data(Qt.ItemDataRole.ToolTipRole)
        else:
            text = source.toolTip()
        if text:
            self._tip.show_tip(str(text), source, QCursor.pos(), index)

    def note_visible(self):
        import time
        self._last_visible_at = time.monotonic()

    def _on_tooltip_event(self, obj, event) -> bool:
        if not isinstance(obj, QWidget) or obj.window() is not self._window:
            return False  # another window (a dialog) keeps Qt's own tooltips
        # Item views: the event goes to the viewport, the text lives on the
        # hovered item (ToolTipRole), not on the widget.
        view = obj.parentWidget()
        if isinstance(view, QAbstractItemView) and obj is view.viewport():
            index = view.indexAt(event.pos())
            text = index.data(Qt.ItemDataRole.ToolTipRole) if index.isValid() else None
            if text:
                self._tip.show_tip(str(text), obj, event.globalPos(), index)
            else:
                self._tip.hide_tip("item has no tooltip")
            return True
        text = obj.toolTip()
        if not text:
            # No text of its own: let Qt propagate it to the parent, as it
            # would for a native tooltip.
            return False
        self._tip.show_tip(text, obj, event.globalPos())
        return True


def install(app, window: QWidget) -> AppTooltip:
    """Create the in-window tooltip and route the main window's tooltips to it."""
    global _instance
    tip = AppTooltip(window)
    tip._filter = _TooltipFilter(tip, window)
    app.installEventFilter(tip._filter)
    _instance = tip
    return tip


def show_text(text: str, source: QWidget, global_pos: QPoint | None = None):
    """For code that showed tooltips by hand. Falls back to Qt's QToolTip
    when not installed (tests, other windows)."""
    if global_pos is None:
        global_pos = QCursor.pos()
    if _instance is None or source.window() is not _instance._window:
        from PySide6.QtWidgets import QToolTip
        QToolTip.showText(global_pos, text, source)
        return
    _instance.show_tip(text, source, global_pos)


def hide_text():
    if _instance is None:
        from PySide6.QtWidgets import QToolTip
        QToolTip.hideText()
        return
    _instance.hide_tip("hide_text()")


class suppress_for_grab:
    """Context manager around transport_bar_blur's grab, which hides and
    re-shows the active panel ~5-15x/sec while a book plays.

    Two jobs: hide the tooltip so it is not photographed into the blurred
    backdrop, and make the filter ignore the Hide/Leave events the panel's
    hide/show sends to every widget inside it (all synchronous, so they land
    inside this block), which would otherwise close a tooltip shown from
    inside a panel within a fraction of a second."""

    def __enter__(self):
        global _grab_depth
        _grab_depth += 1
        self._was_visible = _instance is not None and _instance.isVisible()
        if self._was_visible:
            _instance.hide()
        return self

    def __exit__(self, *exc):
        global _grab_depth
        _grab_depth -= 1
        if self._was_visible and _instance is not None and _instance._text:
            _instance.show()
            _instance.raise_()
        return False
