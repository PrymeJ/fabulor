from PySide6.QtWidgets import QListWidget, QListWidgetItem, QWidget, QHBoxLayout, QLabel
from PySide6.QtCore import Qt, Signal, QSize

ROW_HEIGHT = 24
VISIBLE_ROWS = 5
TIME_LABEL_WIDTH = 58
H_MARGIN = 10  # left + right margin total


class ChapterList(QListWidget):
    """Floating popup list for chapter navigation."""
    chapter_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.player = None
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setObjectName("chapter_dropdown")
        self.setUniformItemSizes(True)
        self.itemClicked.connect(self._on_item_clicked)

    def set_player(self, player):
        self.player = player

    def populate(self, total_duration=0, speed=1.0, list_width=0):
        if not self.player:
            return
        self.clear()
        if list_width > 0:
            self.setFixedWidth(list_width)
        chapters = self.player.chapter_list or []
        effective_speed = speed if speed and speed > 0 else 1.0
        list_width = self.width()
        name_width = list_width - TIME_LABEL_WIDTH - H_MARGIN

        for i, chap in enumerate(chapters):
            title = chap.get('title') or f"Chapter {i+1}"
            start = chap.get('time', 0)
            end = chapters[i+1].get('time', total_duration) if i + 1 < len(chapters) else total_duration
            duration_str = self._format_seconds((end - start) / effective_speed)

            item = QListWidgetItem(self)
            item.setData(Qt.UserRole, i)
            item.setSizeHint(QSize(list_width, ROW_HEIGHT))

            widget = QWidget()
            widget.setAttribute(Qt.WA_TranslucentBackground)
            layout = QHBoxLayout(widget)
            layout.setContentsMargins(5, 0, 5, 0)
            layout.setSpacing(4)

            name_label = QLabel(self._elide_text(title, name_width))
            name_label.setFixedHeight(ROW_HEIGHT)

            time_label = QLabel(duration_str)
            time_label.setObjectName("chapter_time")
            time_label.setFixedWidth(TIME_LABEL_WIDTH)
            time_label.setFixedHeight(ROW_HEIGHT)
            time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

            layout.addWidget(name_label, 1)
            layout.addWidget(time_label)
            widget.setFixedHeight(ROW_HEIGHT)

            self.addItem(item)
            self.setItemWidget(item, widget)

        self._visible_rows = min(VISIBLE_ROWS, self.count())
        # Set a provisional height; the real overhead (stylesheet borders + internal padding)
        # is only measurable after show(), so show_centered_on corrects it then.
        self.setFixedHeight(self._visible_rows * ROW_HEIGHT)

    def show_centered_on(self, anchor_widget, window):
        """Position and show the popup, flush with the window, just above anchor_widget."""
        win_pos = window.mapToGlobal(window.rect().topLeft())
        anchor_pos = anchor_widget.mapToGlobal(anchor_widget.rect().topLeft())
        x = win_pos.x()

        # Show offscreen first so Qt realises the widget and we can measure real overhead
        self.move(x, -9999)
        self.show()

        # Now measure actual overhead (stylesheet borders aren't reflected in frameWidth())
        overhead = self.height() - self.viewport().height()
        corrected_height = self._visible_rows * ROW_HEIGHT + overhead
        self.setFixedHeight(corrected_height)

        y = anchor_pos.y() - corrected_height
        self.move(x, y)
        self.setFocus()

    def scroll_to_active(self, index):
        """Scroll so the active row sits in the middle of the 5-row window."""
        count = self.count()
        if count == 0:
            return
        top_row = max(0, min(index - 2, count - VISIBLE_ROWS))
        self.verticalScrollBar().setValue(top_row * ROW_HEIGHT)

    def _elide_text(self, text, width):
        return self.fontMetrics().elidedText(text, Qt.ElideRight, max(width, 40))

    def _format_seconds(self, seconds):
        seconds = max(0, seconds)
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        return f"{h:02}:{m:02}:{s:02}"

    def _on_item_clicked(self, item):
        if not self.player:
            return
        idx = item.data(Qt.UserRole)
        chapters = self.player.chapter_list or []
        if not (0 <= idx < len(chapters)):
            return
        self.player.chapter = idx
        self.hide()
        actual_title = chapters[idx].get('title') or f"Chapter {idx+1}"
        self.chapter_changed.emit(actual_title)
