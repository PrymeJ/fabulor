"""App-wide "right-click the gutter to jump there" for every `QScrollBar`.

**The default behaviour, and why it's replaced.** Right-clicking a scrollbar's
gutter opens the native style's context menu — "Scroll here / Top / Bottom /
Page up / Page down / Scroll up / Scroll down". That menu is a system-styled
popup: it ignores the app's theme entirely, and every one of its entries except
"Scroll here" is already reachable another way (wheel, gutter left-click,
keyboard). This filter performs "Scroll here" directly on right-press and
suppresses the menu.

**Two events, not one.** The menu is not raised by the mouse press.
`QScrollBar`'s `contextMenuPolicy` is `DefaultContextMenu`, so Qt delivers a
separate `QEvent.ContextMenu` and `QScrollBar.contextMenuEvent()` builds the
menu from that. Consuming only the press produces exactly the half-fixed state
this was first shipped in: the handle jumps correctly *and* the menu still
appears. Both event types have to be swallowed.

`QEvent.ContextMenu` is how every Qt platform plugin routes a native context
menu, so this is not specific to the KDE/openSUSE desktop where it was reported
— the suppression holds on other distros, and on Windows/macOS.

**Installed once, on QApplication**, rather than per-widget. Scrollbars in this
app come from `QScrollArea`, `QListWidget`, `QListView` and `QComboBox` popup
views, several of which Qt creates internally — there is no single construction
site to patch, and a per-widget approach would silently miss any scroll area
added later. An application-level filter sees every `QScrollBar` regardless of
who created it or when.

**Positioning matches Qt's own "Scroll here".** The value is derived with
`QStyle.sliderValueFromPosition` against the real groove rect, with the handle's
length subtracted from the span and half of it from the click position, so the
handle centres on the cursor rather than starting there. Deriving the ratio from
the widget's full height instead would drift by up to half a handle — most
visibly at the extremes, where a click near the bottom could not reach maximum.
The groove and handle rects come from `QStyle.subControlRect`, so a themed
scrollbar (this app's are 8px wide via QSS, not the platform default) measures
correctly; hardcoding either dimension would break the mapping under any theme
that changes it.

Horizontal scrollbars are handled with the same logic on the x axis. The app has
none today, but the filter is orientation-agnostic rather than silently wrong if
one is ever added.

**Opt-in row-boundary snapping** (`register_snap`, 2026-08-12). The pixel-exact
jump above can land mid-row, clipping the topmost visible row. A scrollbar can
register a `fn(raw_value: int) -> int` that rounds the computed value down to a
row boundary before `setValue` — see `library.py`'s `_list_view` and
`stats_panel.py`'s three `StatsRowListView`s for the two registered snap shapes.
Unregistered scrollbars (QComboBox popups, the chapter list, `SessionListWidget`,
the Recently-finished carousels) are unaffected — `_snap_fns.get(obj)` is `None`
for them and the jump behaves exactly as before.
"""
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QScrollBar, QStyle, QStyleOptionSlider


class ScrollBarJumpFilter(QObject):
    """Right-press on a scrollbar jumps the handle to the cursor.

    Install once on the QApplication instance; see `install()` below."""

    def eventFilter(self, obj, event):
        if not isinstance(obj, QScrollBar):
            return False

        # The native menu is NOT driven by the mouse press — QScrollBar's
        # contextMenuPolicy is DefaultContextMenu, so Qt delivers a separate
        # QEvent.ContextMenu and QScrollBar.contextMenuEvent() builds the menu
        # from it. Consuming only the press leaves the menu fully intact
        # (confirmed live: the handle jumped correctly and the menu still
        # appeared). Both events must be swallowed.
        #
        # Filtering the event rather than setting Qt.NoContextMenu on each bar
        # keeps this application-wide: the policy approach would need every
        # scrollbar caught at creation, including the ones Qt makes internally
        # for QComboBox popups and item views.
        #
        # ContextMenu is platform-agnostic — X11/Wayland/Windows/macOS all route
        # the native menu through it — so this suppression is not specific to
        # the KDE/openSUSE desktop where it was reported.
        if event.type() == QEvent.Type.ContextMenu:
            return True

        if (
            event.type() != QEvent.Type.MouseButtonPress
            or event.button() != Qt.MouseButton.RightButton
        ):
            return False

        # A scrollbar with no range has nothing to jump to (the handle fills the
        # groove). Returning True still suppresses the native menu, which is what
        # we want — the menu's other entries would all be no-ops here anyway.
        if obj.minimum() >= obj.maximum():
            return True

        opt = QStyleOptionSlider()
        opt.initFrom(obj)
        opt.orientation = obj.orientation()
        opt.minimum = obj.minimum()
        opt.maximum = obj.maximum()
        opt.pageStep = obj.pageStep()
        opt.sliderPosition = obj.sliderPosition()
        opt.sliderValue = obj.value()
        # Qt draws a horizontal scrollbar by rotating the vertical layout, so
        # State_Horizontal must be set for subControlRect to report the right
        # sub-rects. It is absent by default (initFrom only copies widget state).
        if obj.orientation() == Qt.Orientation.Horizontal:
            opt.state |= QStyle.StateFlag.State_Horizontal

        style = obj.style()
        groove = style.subControlRect(
            QStyle.ComplexControl.CC_ScrollBar, opt,
            QStyle.SubControl.SC_ScrollBarGroove, obj)
        handle = style.subControlRect(
            QStyle.ComplexControl.CC_ScrollBar, opt,
            QStyle.SubControl.SC_ScrollBarSlider, obj)

        pos = event.position().toPoint()
        if obj.orientation() == Qt.Orientation.Vertical:
            click = pos.y() - groove.y() - handle.height() // 2
            span = groove.height() - handle.height()
        else:
            click = pos.x() - groove.x() - handle.width() // 2
            span = groove.width() - handle.width()

        if span <= 0:
            return True  # handle fills the groove; nothing to jump to

        value = QStyle.sliderValueFromPosition(
            obj.minimum(), obj.maximum(), click, span,
            opt.upsideDown if obj.orientation() == Qt.Orientation.Vertical else False)
        snap = _snap_fns.get(obj)
        if snap is not None:
            value = snap(value)
        obj.setValue(value)
        return True  # consume, so the native context menu never opens


_filter = None
_snap_fns: dict = {}


def register_snap(scrollbar, fn):
    """Register a row-snap function for one scrollbar.

    fn(raw_value: int) -> int — receives the would-be setValue argument
    and returns the snapped value. Evaluated at right-click time, not at
    registration time, so closures that re-read live state are correct.

    No deregister API is provided. In this app no registered view is
    ever destroyed mid-session, so the dict does not leak. If a future
    view teardown/rebuild were added, a matching deregister call would
    be needed.
    """
    _snap_fns[scrollbar] = fn


def install(app):
    """Install the jump filter on `app`, once. Idempotent.

    Called from MainWindow's construction. The filter is kept alive by this
    module-level reference — an application-wide event filter whose only
    reference is a local goes out of scope and stops working silently."""
    global _filter
    if _filter is None:
        _filter = ScrollBarJumpFilter()
        app.installEventFilter(_filter)
    return _filter
