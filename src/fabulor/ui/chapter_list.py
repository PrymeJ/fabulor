from PySide6.QtWidgets import QListWidget, QListWidgetItem, QWidget, QHBoxLayout, QLabel, QGraphicsOpacityEffect, QPushButton
from PySide6.QtCore import Qt, Signal, QSize, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QMouseEvent

ROW_HEIGHT = 24
VISIBLE_ROWS = 5
TIME_LABEL_WIDTH = 58
H_MARGIN = 10

FADE_IN_MS = 600
FADE_OUT_MS = 600

EXPAND_BTN_W = 26
EXPAND_BTN_H = 11


class ChapterList(QListWidget):
    """Overlay list for chapter navigation, rendered as a child of the main window."""
    chapter_changed = Signal(str)
    chapter_selected = Signal(str, float, bool)  # (title, old_pos, force_play)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.player = None
        self.setWindowFlags(Qt.Widget)
        self.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setObjectName("chapter_dropdown")
        self.setUniformItemSizes(True)
        self.hide()

        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity)

        self._anim = QPropertyAnimation(self._opacity, b"opacity")
        self._anim.setEasingCurve(QEasingCurve.InOutQuad)
        self._hide_connected = False

        self._expanded = False
        self._anchor_bottom = 0
        self._h_overhead = 0
        self._TOP_MARGIN = 66
        self._can_expand = False

        # Detached button — sibling widget in the parent window, not inside the list.
        # Its opacity effect is driven by the same animation via valueChanged so they
        # fade in perfect sync.
        self._btn_opacity = QGraphicsOpacityEffect(parent)
        self._btn_opacity.setOpacity(0.0)

        self._expand_btn = QPushButton("▲", parent)
        self._expand_btn.setObjectName("chapter_expand_btn")
        self._expand_btn.setFixedSize(EXPAND_BTN_W, EXPAND_BTN_H)
        self._expand_btn.setGraphicsEffect(self._btn_opacity)
        self._expand_btn.clicked.connect(self._toggle_expand)
        self._expand_btn.hide()

        # Drive the button's opacity from the same animation — no separate timer
        self._anim.valueChanged.connect(self._sync_btn_opacity)

    def _sync_btn_opacity(self, value):
        self._btn_opacity.setOpacity(value)

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
        self._can_expand = self.count() > VISIBLE_ROWS
        self._expanded = False
        self._expand_btn.setText("▲")

    def show_above(self, anchor_widget, window):
        """Position the list inside the parent window, just above anchor_widget."""
        self.setFixedWidth(window.width())

        self._opacity.setOpacity(0.0)
        self.show()
        self._h_overhead = self.height() - self.viewport().height()

        anchor_local_y = anchor_widget.mapTo(window, anchor_widget.rect().topLeft()).y()
        self._anchor_bottom = anchor_local_y
        available_px = anchor_local_y - self._TOP_MARGIN
        self._max_rows_available = max(VISIBLE_ROWS, available_px // ROW_HEIGHT)

        self._apply_height(self._visible_rows)
        self.raise_()
        self.setFocus()

        self._anim.stop()
        self._anim.setDuration(FADE_IN_MS)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(0.94)
        self._disconnect_hide()
        self._anim.start()

    def _apply_height(self, rows):
        """Resize and reposition keeping the bottom edge fixed at _anchor_bottom."""
        h = rows * ROW_HEIGHT + self._h_overhead
        self.setFixedHeight(h)
        self.move(0, self._anchor_bottom - h)
        self._reposition_btn()

    def _reposition_btn(self):
        """Place the button just above the list's top-right corner."""
        if not self._can_expand:
            self._expand_btn.hide()
            return
        self._expand_btn.move(self.width() - EXPAND_BTN_W, self.y() - EXPAND_BTN_H)
        self._expand_btn.raise_()
        self._expand_btn.show()

    def _toggle_expand(self):
        self._expanded = not self._expanded
        self._expand_btn.setText("▼" if self._expanded else "▲")
        rows = min(self.count(), self._max_rows_available) if self._expanded else self._visible_rows
        self._apply_height(rows)

    def fade_out(self):
        self._anim.stop()
        self._anim.setDuration(FADE_OUT_MS)
        self._anim.setStartValue(self._opacity.opacity())
        self._anim.setEndValue(0.0)
        self._disconnect_hide()
        self._anim.finished.connect(self._on_fade_out_finished)
        self._hide_connected = True
        self._anim.start()

    def _on_fade_out_finished(self):
        self._expanded = False
        self._expand_btn.setText("▲")
        self._expand_btn.hide()
        self.hide()

    def _disconnect_hide(self):
        if self._hide_connected:
            self._anim.finished.disconnect(self._on_fade_out_finished)
            self._hide_connected = False

    def scroll_to_active(self, index):
        count = self.count()
        if count == 0:
            return
        top_row = max(0, min(index - 2, count - VISIBLE_ROWS))
        self.verticalScrollBar().setValue(top_row * ROW_HEIGHT)

    def mousePressEvent(self, event: QMouseEvent):
        item = self.itemAt(event.pos())
        if item is None:
            super().mousePressEvent(event)
            return

        if not self.player:
            return

        idx = item.data(Qt.UserRole)
        chapters = self.player.chapter_list or []
        if not (0 <= idx < len(chapters)):
            return

        old_pos = self.player.time_pos or 0.0
        self.player.chapter = idx
        actual_title = chapters[idx].get('title') or f"Chapter {idx+1}"

        if event.button() == Qt.LeftButton:
            self.fade_out()
            self.chapter_changed.emit(actual_title)
            self.chapter_selected.emit(actual_title, old_pos, False)
        elif event.button() == Qt.RightButton:
            self.fade_out()
            self.chapter_changed.emit(actual_title)
            self.chapter_selected.emit(actual_title, old_pos, True)

    def _elide_text(self, text, width):
        return self.fontMetrics().elidedText(text, Qt.ElideRight, max(width, 40))

    def _format_seconds(self, seconds):
        seconds = max(0, seconds)
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        return f"{h:02}:{m:02}:{s:02}"
