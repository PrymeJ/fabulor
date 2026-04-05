from PySide6.QtWidgets import QListWidget, QListWidgetItem, QWidget, QHBoxLayout, QLabel
from PySide6.QtCore import Qt, Signal

class ChapterList(QListWidget):
    """Widget to display and navigate audiobook chapters."""
    chapter_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.player = None
        self.itemClicked.connect(self._on_item_clicked)

    def set_player(self, player):
        """Link the player instance to this widget."""
        self.player = player

    def populate(self, total_duration=0):
        """Fetch chapters from the player and update the UI."""
        if not self.player:
            return
        self.clear()
        chapters = self.player.chapter_list or []
        for i, chap in enumerate(chapters):
            title = chap.get('title') or f"Chapter {i+1}"
            start = chap.get('time', 0)
            # Get duration by checking the start of the next chapter or the total book duration
            end = chapters[i+1].get('time', total_duration) if i+1 < len(chapters) else total_duration
            duration_str = self._format_seconds(end - start)

            item = QListWidgetItem(self)
            item.setData(Qt.UserRole, i)
            
            # Create a widget for the list item to allow right-aligned duration
            widget = QWidget()
            layout = QHBoxLayout(widget)
            layout.setContentsMargins(5, 2, 5, 2)
            
            name_label = QLabel(title)
            time_label = QLabel(duration_str)
            time_label.setStyleSheet("color: gray;") # subtle color for the duration
            
            layout.addWidget(name_label)
            layout.addStretch()
            layout.addWidget(time_label)
            
            item.setSizeHint(widget.sizeHint())
            self.addItem(item)
            self.setItemWidget(item, widget)

        # Update the UI with the current chapter name if available
        if chapters:
            initial_title = chapters[0].get('title') or "Chapter 1"
            self.chapter_changed.emit(initial_title)

    def _format_seconds(self, seconds):
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        return f"{h:02}:{m:02}:{s:02}"

    def _on_item_clicked(self, item):
        """Seek to the selected chapter."""
        if self.player:
            idx = item.data(Qt.UserRole)
            self.player.chapter = idx
            # Find the title from the custom widget labels
            widget = self.itemWidget(item)
            if widget:
                title = widget.findChild(QLabel).text()
                self.chapter_changed.emit(title)