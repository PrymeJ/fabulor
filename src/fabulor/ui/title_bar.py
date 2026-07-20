import logging
import time

from PySide6.QtWidgets import QWidget, QLabel, QPushButton, QHBoxLayout
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap, QCursor

logger = logging.getLogger(__name__)


class TitleBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(32)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 4, 0)
        layout.setSpacing(0)

        self.title_label = QLabel("Fabulor")
        layout.addWidget(self.title_label)
        layout.addStretch()

        for symbol, slot in [("─", self._minimize), ("✕", self._close)]:
            btn = QPushButton(symbol)
            btn.setFixedSize(32, 32)
            # Keep the chrome buttons out of the keyboard focus chain entirely — Tab must
            # never be able to land on (and thus trigger) minimize or close, in any context.
            # This is the unconditional floor under the app-wide Tab policy.
            btn.setFocusPolicy(Qt.NoFocus)
            btn.clicked.connect(slot)
            layout.addWidget(btn)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            win = self.window()
            if win.panel_manager:
                win.panel_manager.hide_all_panels()
            handle = win.windowHandle()
            if handle:
                handle.startSystemMove()

    def _minimize(self): self.window().showMinimized()
    def _close(self): self.window().close()


class RightClickButton(QPushButton):
    rightClicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.rightClicked.emit()
            event.accept()
        else:
            super().mousePressEvent(event)


class ThemeItem(RightClickButton):
    hovered = Signal(str)

    def __init__(self, name, parent=None):
        super().__init__(name, parent)
        self.theme_name = name
        self.setObjectName("theme_item")
        self.setMouseTracking(True)
        self.setFlat(True)
        self._last_leave_pos = None

    def enterEvent(self, event):
        # SPURIOUS-ENTEREVENT GUARD (2026-07-20 — the "heartbeat" bug; full
        # mechanism in NOTES.md / theme_manager.py's _apply_stylesheets, the
        # settings_panel.setStyleSheet() try/finally block). Confirmed live:
        # ThemeManager._apply_stylesheets's settings_panel.setStyleSheet() call
        # forces Qt to re-run its style/geometry cascade through the whole
        # settings_panel subtree, which re-evaluates hit-testing for whatever's
        # under the cursor and can fire a fully realistic-looking
        # leaveEvent+enterEvent pair on a widget the cursor never actually
        # left — confirmed indistinguishable from a genuine quick
        # leave-and-return by event shape alone (both fire, same widget, same
        # cursor position), so leave-presence is NOT used as the signal here.
        #
        # Two-signal check instead: main_window's
        # _spurious_enter_guard_until (a perf_counter() deadline set by
        # _apply_stylesheets, cleared via try/finally so it can never get stuck
        # True and permanently swallow real hovers) tells us whether we're
        # inside the narrow (~50ms, measured ~8-15ms real) window where the
        # cascade can produce this artifact at all. Within that window, we
        # additionally require the cursor's CURRENT position to exactly match
        # the position OUR OWN leaveEvent reported moments ago — a genuine
        # same-widget re-hover that happens to land in this window by
        # coincidence would still show the cursor having moved away and back
        # (a different position, or no matching prior leave recorded at all),
        # so it is not swallowed. Only an enter at the SAME position as the
        # immediately-preceding leave, inside the guard window, is treated as
        # synthetic and dropped.
        window = self.window()
        guard_until = getattr(window, '_spurious_enter_guard_until', 0.0)
        now = time.perf_counter()
        pos = QCursor.pos()
        in_window = now < guard_until
        pos_matches = self._last_leave_pos == (pos.x(), pos.y())
        if in_window and pos_matches:
            logger.warning(
                f"[ENTEREVENT-TRACE] t={now:.6f} ThemeItem.enterEvent SUPPRESSED (synthetic) "
                f"theme_name={self.theme_name!r} pos=({pos.x()}, {pos.y()}) "
                f"guard_until={guard_until:.6f} last_leave_pos={self._last_leave_pos!r}"
            )
            return  # synthetic — drop without emitting hovered or calling super()
        logger.warning(
            f"[ENTEREVENT-TRACE] t={now:.6f} ThemeItem.enterEvent PASSED "
            f"theme_name={self.theme_name!r} pos=({pos.x()}, {pos.y()}) "
            f"in_window={in_window} pos_matches={pos_matches} guard_until={guard_until:.6f} "
            f"last_leave_pos={self._last_leave_pos!r}"
        )
        self.hovered.emit(self.theme_name)
        super().enterEvent(event)

    def leaveEvent(self, event):
        pos = QCursor.pos()
        self._last_leave_pos = (pos.x(), pos.y())
        logger.warning(
            f"[ENTEREVENT-TRACE] t={time.perf_counter():.6f} ThemeItem.leaveEvent "
            f"theme_name={self.theme_name!r} pos=({pos.x()}, {pos.y()})"
        )
        super().leaveEvent(event)