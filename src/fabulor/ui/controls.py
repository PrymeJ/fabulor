from PySide6.QtWidgets import QWidget, QLabel
from PySide6.QtCore import Qt, Signal, Property, QTimer
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
        p.end()

class ScrollingLabel(QLabel):
    """A label that scrolls its text horizontally if it's too long to fit."""
    clicked = Signal()

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._scroll_pos = 0
        self._direction = -1  # -1 for left, 1 for right
        self._pause_ticks = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_scroll)
        self._timer.setInterval(50)  # Slower interval for a smoother, less "tiring" feel
        self.setCursor(Qt.PointingHandCursor)
        self.setWordWrap(False)

    def setText(self, text):
        super().setText(text)
        self._update_scrolling_state()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_scrolling_state()

    def _update_scrolling_state(self):
        text_width = self.fontMetrics().horizontalAdvance(self.text())
        if text_width > self.width() and self.width() > 0:
            if not self._timer.isActive():
                self._scroll_pos = 0
                self._direction = -1
                self._pause_ticks = 40  # Initial pause at the start
                self._timer.start()
        else:
            self._timer.stop()
            self._scroll_pos = 0
            self.update()

    def _update_scroll(self):
        if self._pause_ticks > 0:
            self._pause_ticks -= 1
            return

        text_width = self.fontMetrics().horizontalAdvance(self.text())
        max_scroll = text_width - self.width()

        if self._direction == -1:  # Scrolling towards the end
            self._scroll_pos -= 1
            if abs(self._scroll_pos) >= max_scroll:
                self._direction = 1
                self._pause_ticks = 40  # Pause at the end
        else:  # Scrolling back to the beginning
            self._scroll_pos += 1
            if self._scroll_pos >= 0:
                self._scroll_pos = 0
                self._direction = -1
                self._pause_ticks = 40  # Pause at the beginning

        self.update()

    def paintEvent(self, event):
        if not self._timer.isActive():
            super().paintEvent(event)
            return

        p = QPainter(self)
        text = self.text()
        metrics = self.fontMetrics()
        y = (self.height() + metrics.ascent() - metrics.descent()) // 2
        
        p.drawText(self._scroll_pos, y, text)
        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()