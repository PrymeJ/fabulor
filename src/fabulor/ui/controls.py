from PySide6.QtWidgets import QWidget, QLabel, QPushButton
from PySide6.QtCore import Qt, Signal, Property, QTimer, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QColor, QPainter

class ClickSlider(QWidget):
    valueChanged = Signal(int)
    sliderPressed = Signal()
    sliderReleased = Signal()
    rightClicked = Signal(float)

    def __init__(self, orientation=Qt.Horizontal, parent=None):
        super().__init__(parent)
        self._value = 0
        self._minimum = 0
        self._maximum = 1000
        self._dragging = False
        self.center_mark = False
        self._markers = []
        self.snap_to_center = False
        # Default colors (will be overridden by QSS)
        self._bg_color = QColor("#4B0082")
        self._fill_color = QColor("#C8A2C8")
        self._notch_color = QColor("#FFFFFF")
        self._notch_opacity = 100

        # Reveal animation state
        self._revealed_count = 0.0
        self._reveal_from_left = True
        self._reveal_anim = QPropertyAnimation(self, b"revealedCount")
        self._reveal_anim.setEasingCurve(QEasingCurve.Type.Linear)

    @Property(QColor)
    def bg_color(self): return self._bg_color
    @bg_color.setter
    def bg_color(self, color): self._bg_color = color; self.update()

    @Property(QColor)
    def fill_color(self): return self._fill_color
    @fill_color.setter
    def fill_color(self, color): self._fill_color = color; self.update()

    @Property(QColor)
    def notch_color(self): return self._notch_color
    @notch_color.setter
    def notch_color(self, color): self._notch_color = color; self.update()

    @Property(int)
    def notch_opacity(self): return self._notch_opacity
    @notch_opacity.setter
    def notch_opacity(self, val): self._notch_opacity = val; self.update()

    @Property(float)
    def revealedCount(self):
        return self._revealed_count

    @revealedCount.setter
    def revealedCount(self, v):
        self._revealed_count = float(v)
        self.update()

    def minimum(self): return self._minimum
    def maximum(self): return self._maximum

    def setRange(self, min_, max_):
        self._minimum = min_
        self._maximum = max_

    def value(self): return self._value

    def set_markers(self, ratios):
        if not ratios:
            self._markers = []
            self._revealed_count = 0.0
            self.update()
            return

        self._markers = ratios
        
        # If the flow animation is currently running, hide notches and wait.
        # Otherwise, reveal them immediately.
        is_animating = (hasattr(self, '_flow_anim') and 
                       self._flow_anim.state() == QPropertyAnimation.State.Running)
        
        if is_animating:
            self._revealed_count = 0.0
        else:
            self._start_reveal()

    def _start_reveal(self):
        num_notches = max(0, len(self._markers) - 2)
        if num_notches == 0:
            self._revealed_count = 0.0
            self.update()
            return

        self._reveal_anim.stop()
        self._reveal_anim.setStartValue(0.0)
        self._reveal_anim.setEndValue(float(num_notches))
        
        # 40ms per notch provides a smooth, visible fade-in sequence
        dur = max(300, min(1200, num_notches * 40))
        self._reveal_anim.setDuration(dur)
        self._reveal_anim.start()

    def setValue(self, val):
        val = max(self._minimum, min(self._maximum, val))
        if val != self._value:
            self._value = val
            self.valueChanged.emit(val)
            self.update()

    # --- animated value property for QPropertyAnimation ---
    def _get_animated_value(self):
        return self._value

    def _set_animated_value(self, val):
        self.setValue(val)

    animatedValue = Property(int, _get_animated_value, _set_animated_value)

    def animate_to(self, target, old_value=None):
        """Animate the slider from old_value (or current) to target.

        Duration scales with distance so large jumps feel fast and small ones feel slow.
        Range: 200ms (tiny move) to 600ms (full-range jump).
        """
        if not hasattr(self, '_flow_anim'):
            self._flow_anim = QPropertyAnimation(self, b"animatedValue")
            self._flow_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)

        start = old_value if old_value is not None else self._value
        span = self._maximum - self._minimum
        distance = abs(target - start) / max(1, span)
        duration = int(200 + distance * 400)

        # Direction detection: If target is smaller than start, flow is Left.
        # Request says: Flow Left -> Appear from Left. Flow Right -> Appear from Right.
        self._reveal_from_left = (target < start)

        if self._flow_anim.state() == QPropertyAnimation.State.Running:
            self._flow_anim.stop()

        self._value = start
        self._flow_anim.setStartValue(start)
        self._flow_anim.setEndValue(target)
        self._flow_anim.setDuration(duration)
        self._flow_anim.finished.connect(self._start_reveal, Qt.UniqueConnection)
        self._flow_anim.start()

    def _val_from_x(self, x):
        if self.snap_to_center:
            mid_x = self.width() / 2
            # Snap if within 5 pixels of the physical center
            if abs(x - mid_x) < 5:
                return (self._minimum + self._maximum) // 2
                
        return self._minimum + int((self._maximum - self._minimum) * x / self.width())

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self.sliderPressed.emit()
            self.setValue(self._val_from_x(event.position().x()))
        elif event.button() == Qt.RightButton:
            click_ratio = event.position().x() / max(1, self.width())
            # Always seek. Snap to closest marker if available, otherwise use click position.
            if self._markers:
                target_ratio = min(self._markers, key=lambda x: abs(x - click_ratio))
            else:
                target_ratio = click_ratio
            self.rightClicked.emit(target_ratio)

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

        if self.center_mark:
            # Draw a subtle notch in the dead center
            p.setPen(QColor(255, 255, 255, 60))
            mid = self.width() // 2
            p.drawLine(mid, 0, mid, self.height())

        if self._markers and len(self._markers) > 2:
            mid_y = self.height() // 2
            # Draw subtle markers for internal chapter boundaries
            # Skip first (0) and last (len-1) as requested
            m_len = len(self._markers)
            for i, ratio in enumerate(self._markers):
                if i == 0 or i == m_len - 1:
                    continue
                
                # Determine the reveal sequence order based on flow direction
                if self._reveal_from_left:
                    order = i
                else:
                    order = m_len - 1 - i

                # Calculate individual notch opacity based on reveal progress
                # If revealedCount is 1.5, notch #1 is full, notch #2 is at 50% opacity.
                opacity_ratio = max(0.0, min(1.0, self._revealed_count - (order - 1)))
                if opacity_ratio <= 0:
                    continue

                x = int(ratio * self.width())
                c = QColor(self._notch_color)
                c.setAlpha(int(self._notch_opacity * opacity_ratio))
                p.setPen(c)
                if i % 2 == 1:
                    p.drawLine(x, mid_y, x, self.height()) # Center to Bottom
                else:
                    p.drawLine(x, mid_y, x, 0)             # Center to Top
        p.end()

class ScrollingLabel(QLabel):
    """A label that scrolls its text horizontally if it's too long to fit."""
    clicked = Signal()

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._scroll_pos = 0
        self._scroll_mode = "Slow"
        self._direction = -1  # -1 for left, 1 for right
        self._pause_ticks = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_scroll)
        self._timer.setInterval(120)
        self.setCursor(Qt.PointingHandCursor)
        self.setWordWrap(False)

    def set_scroll_mode(self, mode):
        self._scroll_mode = mode
        intervals = {"Slow": 120, "Normal": 60}
        if mode in intervals:
            self._timer.setInterval(intervals[mode])
        self._update_scrolling_state()
        self.update()

    def setText(self, text):
        super().setText(text)
        self._update_scrolling_state()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_scrolling_state()

    def _update_scrolling_state(self):
        if self._scroll_mode == "Off":
            self._timer.stop()
            self._scroll_pos = 0
            self.update()
            return

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
        p = QPainter(self)
        text = self.text()
        metrics = self.fontMetrics()
        text_width = metrics.horizontalAdvance(text)
        y = (self.height() + metrics.ascent() - metrics.descent()) // 2
        
        if self._timer.isActive():
            p.drawText(self._scroll_pos, y, text)
        else:
            # Center the text within the available width
            if self._scroll_mode == "Off":
                # Draw elided text when scrolling is disabled
                elided = metrics.elidedText(text, Qt.ElideRight, self.width())
                elided_width = metrics.horizontalAdvance(elided)
                x = max(0, (self.width() - elided_width) // 2)
                p.drawText(x, y, elided)
            else:
                x = max(0, (self.width() - text_width) // 2)
                p.drawText(x, y, text)
        p.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()

class HoverButton(QPushButton):
    """A button that emits signals on mouse enter/leave for hover effects."""
    hovered = Signal()
    unhovered = Signal()
    rightClicked = Signal()

    def enterEvent(self, event):
        self.hovered.emit()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.unhovered.emit()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.rightClicked.emit()
        else:
            super().mousePressEvent(event)