from PySide6.QtWidgets import QListWidget, QListWidgetItem, QWidget, QHBoxLayout, QLabel
from PySide6.QtCore import Qt, Signal, QSize

ROW_HEIGHT = 24
VISIBLE_ROWS = 5
TIME_LABEL_WIDTH = 58
H_MARGIN = 10  # left + right padding total inside items


class ChapterList(QListWidget):
    """Overlay list for chapter navigation, rendered as a child of the main window."""
    chapter_changed = Signal(str)
    chapter_selected = Signal(str, float)  # (title, old_pos)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.player = None
        # Child widget, not a popup — stays inside the parent window always
        self.setWindowFlags(Qt.Widget)
        self.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setObjectName("chapter_dropdown")
        self.setUniformItemSizes(True)
        self.hide()
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
        w = self.width()
        name_width = w - TIME_LABEL_WIDTH - H_MARGIN

        for i, chap in enumerate(chapters):
            title = chap.get('title') or f"Chapter {i+1}"
            start = chap.get('time', 0)
            end = chapters[i+1].get('time', total_duration) if i + 1 < len(chapters) else total_duration
            duration_str = self._format_seconds((end - start) / effective_speed)

            item = QListWidgetItem(self)
            item.setData(Qt.UserRole, i)
            item.setSizeHint(QSize(w, ROW_HEIGHT))

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

    def show_above(self, anchor_widget, window):
        """Position the list inside the parent window, just above anchor_widget."""
        self.setFixedWidth(window.width())

        # Measure real height overhead (borders + any internal padding) after sizing
        self.show()
        h_overhead = self.height() - self.viewport().height()
        self.hide()

        corrected_height = self._visible_rows * ROW_HEIGHT + h_overhead
        self.setFixedHeight(corrected_height)

        # All coordinates are in window-local space — no mapToGlobal needed
        anchor_local_y = anchor_widget.mapTo(window, anchor_widget.rect().topLeft()).y()
        self.move(0, anchor_local_y - corrected_height)
        self.raise_()
        self.show()
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
        old_pos = self.player.time_pos or 0.0
        self.player.chapter = idx
        self.hide()
        actual_title = chapters[idx].get('title') or f"Chapter {idx+1}"
        self.chapter_changed.emit(actual_title)
        self.chapter_selected.emit(actual_title, old_pos)
