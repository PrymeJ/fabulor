"""App-wide suppression of Qt/Fusion's native keyboard-focus rectangle (PE_FrameFocusRect).

QSS `outline: none` does NOT suppress this on Fusion (this app's active style on its target
desktop, confirmed via `QApplication.style().objectName() == "fusion"`) — Fusion paints the dotted
focus rect as its own primitive in `drawPrimitive`, independent of the widget's QSS box model, and
setting `outline: none` on `#pattern_button` / `QTabBar::tab` was confirmed live to have zero
effect. `NoFocusRectStyle` is a `QProxyStyle` that no-ops `PE_FrameFocusRect` at the `drawPrimitive`
level instead — the standard, reliable way to suppress it regardless of style/desktop.

Applied app-wide, not scoped to the widgets `ui/focus_marker.py`'s traveling marker currently
tracks: this app's entire UI is custom-painted (frameless window, custom title bar, themed
everything), so there is no widget anywhere that relies on the native rectangle today, and scoping
this per-widget would mean re-adding it every time the traveling marker is extended to a new
widget class.
"""
from PySide6.QtWidgets import QProxyStyle, QStyle


class NoFocusRectStyle(QProxyStyle):
    def drawPrimitive(self, element, option, painter, widget=None):
        if element == QStyle.PrimitiveElement.PE_FrameFocusRect:
            return
        super().drawPrimitive(element, option, painter, widget)
