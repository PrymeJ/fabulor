from PySide6.QtWidgets import QSlider
from PySide6.QtCore import Qt

class ClickSlider(QSlider):
    """A slider that jumps to the position where it is clicked."""
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            # Calculate position based on the click
            val = self.minimum() + ((self.maximum() - self.minimum()) * event.position().x()) / self.width()
            self.setValue(int(val))
            self.sliderReleased.emit() 
        super().mousePressEvent(event)