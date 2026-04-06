from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, Signal, Property
from PySide6.QtGui import QColor, QPainter

class ClickSlider(QWidget):
    valueChanged = Signal(int)
    sliderPressed = Signal()
    sliderReleased = Signal()

    def __init__(self, orientation=Qt.Horizontal, parent=None):
        super().__init__(parent)
        self._value = 0
        self._minimum = 0
        self._maximum = 1000
        self._dragging = False
        # Default colors (will be overridden by QSS)
        self._bg_color = QColor("#4B0082")
        self._fill_color = QColor("#C8A2C8")

    @Property(QColor)
    def bg_color(self): return self._bg_color
    @bg_color.setter
    def bg_color(self, color): self._bg_color = color; self.update()

    @Property(QColor)
    def fill_color(self): return self._fill_color
    @fill_color.setter
    def fill_color(self, color): self._fill_color = color; self.update()

    def minimum(self): return self._minimum
    def maximum(self): return self._maximum

    def setRange(self, min_, max_):
        self._minimum = min_
        self._maximum = max_

    def value(self): return self._value

    def setValue(self, val):
        val = max(self._minimum, min(self._maximum, val))
        if val != self._value:
            self._value = val
            self.valueChanged.emit(val)
            self.update()

    def _val_from_x(self, x):
        return self._minimum + int((self._maximum - self._minimum) * x / self.width())

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self.sliderPressed.emit()
            self.setValue(self._val_from_x(event.position().x()))

    def mouseMoveEvent(self, event):
        if self._dragging:
            self.setValue(self._val_from_x(event.position().x()))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = False
            self.setValue(self._val_from_x(event.position().x()))
            self.sliderReleased.emit()

    def paintEvent(self, event):
        p = QPainter(self)
        ratio = (self._value - self._minimum) / max(1, self._maximum - self._minimum)
        filled = int(ratio * self.width())
        p.fillRect(0, 0, self.width(), self.height(), self._bg_color)
        p.fillRect(0, 0, filled, self.height(), self._fill_color)