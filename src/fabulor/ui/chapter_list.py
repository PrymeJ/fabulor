from PySide6.QtWidgets import QListWidget, QListWidgetItem, QWidget, QHBoxLayout, QLabel
from PySide6.QtCore import Qt, Signal

class ChapterList(QListWidget):
    """Widget to display and navigate audiobook chapters."""
    chapter_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.player = None
        # Make it a floating popup
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFixedWidth(280)
        self.setObjectName("chapter_dropdown")
        
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
            
            name_label = QLabel(self._elide_text(title, 180))
            time_label = QLabel(duration_str)
            time_label.setObjectName("chapter_time")
            
            layout.addWidget(name_label)
            layout.addStretch()
            layout.addWidget(time_label)
            
            item.setSizeHint(widget.sizeHint())
            self.addItem(item)
            self.setItemWidget(item, widget)
            
        # Cap height based on content
        list_height = min(400, self.count() * 30 + 10)
        self.setFixedHeight(list_height)

    def _elide_text(self, text, width):
        """Helper to elide text for the list items."""
        metrics = self.fontMetrics()
        return metrics.elidedText(text, Qt.ElideRight, width)

    def _format_seconds(self, seconds):
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        return f"{h:02}:{m:02}:{s:02}"

    def _on_item_clicked(self, item):
        if self.player:
            idx = item.data(Qt.UserRole)
            chapters = self.player.chapter_list or []
            if idx >= len(chapters):
                return  # Player state is stale, ignore click
            self.player.chapter = idx
            self.hide()
            actual_title = chapters[idx].get('title') or f"Chapter {idx+1}"
            self.chapter_changed.emit(actual_title)