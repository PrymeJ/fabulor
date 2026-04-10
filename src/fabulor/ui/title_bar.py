from PySide6.QtWidgets import QWidget, QLabel, QPushButton, QHBoxLayout
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap


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
            btn.clicked.connect(slot)
            layout.addWidget(btn)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            win = self.window()
            if win.panel_manager:
                win.panel_manager.hide_all_panels()
            win.windowHandle().startSystemMove()

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
        self.hovered.emit(self.theme_name)
        super().enterEvent(event)