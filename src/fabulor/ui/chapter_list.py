# THEME_ANIM_TODO: ChapterList
import logging
import time
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QStyledItemDelegate, QStyle, QGraphicsOpacityEffect, QPushButton
from PySide6.QtCore import Qt, Signal, QSize, QPropertyAnimation, QEasingCurve, QTimer
from PySide6.QtGui import QMouseEvent, QKeyEvent, QColor
from mpv import ShutdownError

logger = logging.getLogger(__name__)

ROW_HEIGHT = 24
VISIBLE_ROWS = 5
TIME_LABEL_WIDTH = 58
H_MARGIN = 10

FADE_IN_MS = 450
FADE_OUT_MS = 300

EXPAND_BTN_W = 26
EXPAND_BTN_H = 11

ROLE_CHAP_INDEX = Qt.UserRole
ROLE_CHAP_TITLE = Qt.UserRole + 1
ROLE_CHAP_DURATION = Qt.UserRole + 2


class ChapterItemDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._color_text = QColor("#ffffff")
        self._color_time = QColor("#aaaaaa")
        self._color_highlight = QColor("#ffffff")

    def update_theme(self, theme_dict):
        def c(key, fallback):
            val = theme_dict.get(key) or fallback
            return QColor(val) if isinstance(val, str) else val
        self._color_text = c('dropdown_text', theme_dict.get('text', '#ffffff'))
        self._color_time = c('dropdown_time_text', theme_dict.get('text', '#aaaaaa'))
        self._color_highlight = c('dropdown_curr_chap', '#ffffff')

    def paint(self, painter, option, index):
        painter.save()
        painter.setClipRect(option.rect)

        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, self._color_highlight)

        r = option.rect
        title = index.data(ROLE_CHAP_TITLE) or ""
        title_rect = r.adjusted(H_MARGIN, 0, -(TIME_LABEL_WIDTH + H_MARGIN), 0)
        painter.setPen(self._color_text)
        painter.drawText(title_rect, Qt.AlignLeft | Qt.AlignVCenter, title)

        duration = index.data(ROLE_CHAP_DURATION) or ""
        time_rect = r.adjusted(r.width() - TIME_LABEL_WIDTH - H_MARGIN, 0, -H_MARGIN, 0)
        painter.setPen(self._color_time)
        painter.drawText(time_rect, Qt.AlignRight | Qt.AlignVCenter, duration)

        painter.restore()

    def sizeHint(self, option, index):
        return QSize(option.rect.width() if option.rect.isValid() else 0, ROW_HEIGHT)


class ChapterList(QListWidget):
    """Overlay list for chapter navigation, rendered as a child of the main window."""
    chapter_changed = Signal(str)
    chapter_selected = Signal(str, float, bool)  # (title, old_pos, force_play)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.player = None
        self.config = None
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

        self._delegate = ChapterItemDelegate(self)
        self.setItemDelegate(self._delegate)

        self._digit_buffer = ""
        self._digit_timer = QTimer(self)
        self._digit_timer.setSingleShot(True)
        self._digit_timer.setInterval(800)
        self._digit_timer.timeout.connect(self._commit_digit_jump)

    def _sync_btn_opacity(self, value):
        self._btn_opacity.setOpacity(value)

    def set_player(self, player):
        self.player = player

    def set_config(self, config):
        self.config = config

    def update_theme(self, theme_dict):
        self._delegate.update_theme(theme_dict)
        self.update()

    def populate(self, total_duration=0, speed=1.0, list_width=0):
        logger.debug(
            f"t={time.perf_counter():.6f} [populate ENTRY] "
            f"count_before={self.count()} scroll_before={self.verticalScrollBar().value()}"
        )
        self._digit_buffer = ""
        self._digit_timer.stop()
        try:
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

                item = QListWidgetItem()
                item.setData(ROLE_CHAP_INDEX, i)
                item.setData(ROLE_CHAP_TITLE, self._elide_text(title, name_width))
                item.setData(ROLE_CHAP_DURATION, duration_str)
                item.setSizeHint(QSize(w, ROW_HEIGHT))
                self.addItem(item)

            self._visible_rows = min(VISIBLE_ROWS, self.count())
            self._can_expand = self.count() > VISIBLE_ROWS
            self._expanded = False
            self._expand_btn.setText("▲")
            logger.debug(
                f"t={time.perf_counter():.6f} [populate EXIT] "
                f"count_after={self.count()} scroll_after={self.verticalScrollBar().value()}"
            )
        except (ShutdownError, AttributeError, SystemError):
            return

    def show_above(self, anchor_widget, window):
        """Position the list inside the parent window, just above anchor_widget."""
        logger.debug(
            f"t={time.perf_counter():.6f} [show_above ENTRY] "
            f"count={self.count()} scroll_before={self.verticalScrollBar().value()} "
            f"isVisible={self.isVisible()}"
        )
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
        QTimer.singleShot(0, self.setFocus)

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
        self._expand_btn.move(self.width() - EXPAND_BTN_W, self._anchor_bottom - self.height() - EXPAND_BTN_H)
        self._expand_btn.raise_()
        self._expand_btn.show()

    def _toggle_expand(self):
        self._expanded = not self._expanded
        self._expand_btn.setText("▼" if self._expanded else "▲")
        rows = min(self.count(), self._max_rows_available) if self._expanded else self._visible_rows
        self._apply_height(rows)
        QTimer.singleShot(0, self.setFocus)

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
        logger.debug(
            f"t={time.perf_counter():.6f} [scroll_to_active ENTRY] "
            f"index={index} count={count} isVisible={self.isVisible()} "
            f"scroll_before={self.verticalScrollBar().value()}"
        )
        if count == 0:
            return
        top_row = max(0, min(index - 2, count - VISIBLE_ROWS))
        self.verticalScrollBar().setValue(top_row * ROW_HEIGHT)
        logger.debug(
            f"t={time.perf_counter():.6f} [scroll_to_active EXIT] "
            f"top_row={top_row} scroll_after={self.verticalScrollBar().value()}"
        )

    def mousePressEvent(self, event: QMouseEvent):
        item = self.itemAt(event.pos())
        if item is None:
            super().mousePressEvent(event)
            return

        if event.button() == Qt.LeftButton:
            self._activate_item(item, force_play=False)
        elif event.button() == Qt.RightButton:
            self._activate_item(item, force_play=True)

    def keyPressEvent(self, event: QKeyEvent):
        key = event.key()
        if key in (Qt.Key_Up, Qt.Key_Down):
            super().keyPressEvent(event)
        elif key in (Qt.Key_Left, Qt.Key_Right) and self._can_expand:
            self._toggle_expand()
        elif key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            item = self.currentItem()
            if item:
                self._activate_item(item, force_play=(key == Qt.Key_Space))
        elif key in (Qt.Key.Key_Escape, Qt.Key.Key_C):
            self._digit_timer.stop()
            self._digit_buffer = ""
            self.fade_out()
        elif Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
            self._digit_buffer += event.text()
            self._digit_timer.start()  # restart — fires 800ms after last digit
            event.accept()

    def _commit_digit_jump(self):
        try:
            typed = self._digit_buffer
            self._digit_buffer = ""
            if not self.player:
                return
            chapters = self.player.chapter_list or []
            mode = self.config.get_chapter_digit_mode() if self.config else "by_name"

            if mode == "by_index":
                target = int(typed) - 1
                if not (0 <= target < len(chapters)):
                    return
            else:
                # Search chapter titles for a word-boundary match of the typed number.
                # "6" matches "Chapter 6" but not "Chapter 16" or "Chapter 60".
                import re
                pattern = re.compile(r'(?<!\d)' + re.escape(typed) + r'(?!\d)')
                target = next(
                    (i for i, c in enumerate(chapters)
                     if pattern.search(c.get('title', ''))),
                    None
                )
                if target is None:
                    return

            self.setCurrentRow(target)
            self.scroll_to_active(target)

            if self.config and self.config.get_chapter_digit_autoplay():
                item = self.item(target)
                if item:
                    self._activate_item(item, force_play=True)
        except (ShutdownError, AttributeError, SystemError, ValueError):
            return

    def _activate_item(self, item, force_play=False):
        logger.debug(
            f"t={time.perf_counter():.6f} [_activate_item ENTRY] "
            f"requested_idx={item.data(ROLE_CHAP_INDEX)} force_play={force_play}"
        )
        try:
            if not self.player:
                return
            idx = item.data(ROLE_CHAP_INDEX)
            chapters = self.player.chapter_list or []
            if not (0 <= idx < len(chapters)):
                return
            old_pos = self.player.time_pos or 0.0
            # All book types (embedded M4B, CUE, VT) navigate by seeking to the chapter
            # boundary via Player.activate_chapter_index, which applies the mode-aware
            # seek offset internally. This routes through seek_async (sets _seek_target)
            # so the chapter slider/labels' is_seeking guard clears on settle — embedded
            # M4B previously used native `self.chapter = idx`, which never set
            # _seek_target and left the chapter UI frozen until a manual slider click.
            self.player.activate_chapter_index(idx)
            actual_title = chapters[idx].get('title') or f"Chapter {idx+1}"
            self.fade_out()
            self.chapter_changed.emit(actual_title)
            self.chapter_selected.emit(actual_title, old_pos, force_play)
        except (ShutdownError, AttributeError, SystemError):
            return

    def _elide_text(self, text, width):
        return self.fontMetrics().elidedText(text, Qt.ElideRight, max(width, 40))

    def _format_seconds(self, seconds):
        seconds = max(0, seconds)
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        return f"{h:02}:{m:02}:{s:02}"
