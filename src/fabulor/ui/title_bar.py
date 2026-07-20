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

    def enterEvent(self, event):
        # INVESTIGATION LOGGING (2026-07-20 — tracing the spurious repeated
        # enterEvent-on-stationary-cursor bug). Logs the global cursor position
        # at every enterEvent so a real reproduction can rule out (or confirm)
        # actual OS-level cursor jitter as the cause, independent of any other
        # theory. Read-only, no behavior change.
        pos = QCursor.pos()
        logger.warning(
            f"[ENTEREVENT-TRACE] t={time.perf_counter():.6f} ThemeItem.enterEvent "
            f"theme_name={self.theme_name!r} global_cursor_pos=({pos.x()}, {pos.y()})"
        )
        self.hovered.emit(self.theme_name)
        super().enterEvent(event)