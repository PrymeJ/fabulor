"""SidebarHotspot — a small, always invisible, always-on-cover-art hover zone that opens
the sidebar as a second method alongside the existing right-click trigger. Purely a
hit-test/hover widget — no paintEvent, no visual indicator (a "Square" indicator style
was tried and removed; see git history / SESSION.md 2026-08-09 for why). See
review/Plan_260809_corner_hotspot_sidebar_trigger.md for the full investigation/design.

Two independent pieces of state live on this widget:
  _armed         — whether a hover-intent CAN start a new open. Cleared whenever the
                   sidebar transitions to open while the cursor is resting inside this
                   widget's rect (regardless of which method opened it), restored only
                   by a genuine leaveEvent. This is what stops the loop where the idle
                   timer closes the sidebar while the cursor never moved, the still-
                   resting cursor reads as a fresh hover-enter, and the sidebar reopens
                   indefinitely — see the plan's section 4 for the full trace. It is
                   deliberately geometric (exit-then-reentry), never a time-based
                   cooldown.
  _hover_timer   — the hover-intent debounce. Started on enterEvent (only if armed and
                   the hotspot setting is on), stopped on leaveEvent. Firing calls
                   on_fire(), which is the actual sidebar-open trigger.
"""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QWidget

HOTSPOT_SIZE = 15
_HOTSPOT_HOVER_INTENT_MS = 200


class SidebarHotspot(QWidget):
    def __init__(self, config, on_fire, parent=None):
        super().__init__(parent)
        self._config = config
        self._on_fire = on_fire
        self._armed = True
        self.setFixedSize(HOTSPOT_SIZE, HOTSPOT_SIZE)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(_HOTSPOT_HOVER_INTENT_MS)
        self._hover_timer.timeout.connect(self._fire)

    def disarm_if_cursor_inside(self):
        """Called whenever the sidebar transitions to open, regardless of which method
        opened it. If the cursor happens to be resting inside this widget's rect at that
        moment, disarm — the only way back to armed is a genuine leaveEvent. This is what
        makes the re-arm rule independent of opened_via; see the module docstring."""
        if self.rect().contains(self.mapFromGlobal(self.cursor().pos())):
            self._armed = False

    def enterEvent(self, event):
        super().enterEvent(event)
        if not self._config.get_sidebar_hotspot_enabled():
            return
        if not self._armed:
            return
        self._hover_timer.start()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self._hover_timer.stop()
        self._armed = True

    def _fire(self):
        if not self._config.get_sidebar_hotspot_enabled():
            return
        self._on_fire()
