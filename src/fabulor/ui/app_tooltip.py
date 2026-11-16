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
`context` property selects per-panel spacing (`tags` for the Tags panel's
book-title tooltips), derived from the source widget's ancestors in
`_CONTEXT_BY_ANCESTOR`.

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

# objectName of an ancestor -> value of the tooltip's `context` property.
_CONTEXT_BY_ANCESTOR = {
    "tags_panel": "tags",
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
        self._hide_timer.timeout.connect(self.hide_tip)
        self._grab_hidden = False

    # -- public -----------------------------------------------------------

    def show_tip(self, text: str, source: QWidget, global_pos: QPoint, index=None):
        if not text:
            self.hide_tip()
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

    def hide_tip(self):
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
            context = _CONTEXT_BY_ANCESTOR.get(w.objectName())
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

    def __init__(self, tip: AppTooltip, window: QWidget):
        super().__init__(tip)
        self._tip = tip
        self._window = window

    def eventFilter(self, obj, event):
        if self._tip is None:
            return False
        t = event.type()
        if t == QEvent.Type.ToolTip:
            return self._on_tooltip_event(obj, event)
        tip = self._tip
        if not tip.isVisible():
            return False
        if t in (QEvent.Type.MouseButtonPress, QEvent.Type.Wheel,
                 QEvent.Type.KeyPress):
            tip.hide_tip()
        elif (obj is tip.source and t in (QEvent.Type.Leave, QEvent.Type.Hide)
              and _grab_depth == 0):
            # During a blur grab the panel is hidden and re-shown, which sends
            # Hide and Leave to every widget in it; those are not the user.
            tip.hide_tip()
        elif (obj is tip.source and tip.source_index is not None
              and t in (QEvent.Type.MouseMove, QEvent.Type.HoverMove)):
            view = obj.parentWidget()
            if isinstance(view, QAbstractItemView):
                if view.indexAt(event.position().toPoint()) != tip.source_index:
                    tip.hide_tip()
        return False

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
                self._tip.hide_tip()
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
    _instance.hide_tip()


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
