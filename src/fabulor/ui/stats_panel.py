# THEME_ANIM_TODO: ElidedLabel, SessionListWidget, BookDayRow, 
# FinishedBookThumb, FinishedScrollRow, StatsPanel
import os
import re
from datetime import date
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QLabel,
    QGridLayout, QSpinBox, QScrollArea, QPushButton, QApplication
)
from PySide6.QtCore import (
    Qt, QRect, QRectF, Signal, QSize, QPoint, QEvent, QThreadPool, QTimer, Property,
    QPropertyAnimation, QEasingCurve,
)
from PySide6.QtGui import QPainter, QColor, QFont, QPixmap, QImage, QIcon, QEnterEvent, QPen
from PySide6.QtWidgets import QAbstractScrollArea
from .cover_loader import CoverLoaderWorker, to_grayscale
from .library import _cover_cache
from .icon_utils import render_logo_placeholder_bordered as _render_svg_placeholder_bordered
from .icon_utils import load_currentcolor_icon

# Fixed neutral grey used for SVG placeholders on archived (deleted/excluded) books.
# to_grayscale() on a raster cover looks right; applying it to a themed SVG placeholder
# does not — the SVG is already a flat icon and the grey wash just looks odd. Instead,
# render the placeholder in a fixed monochrome colour so it reads as intentionally greyed.
_ARCHIVED_PLACEHOLDER_COLOR = "#888888"


def _elide(text: str, font, max_px: int) -> str:
    from PySide6.QtGui import QFontMetrics
    return QFontMetrics(font).elidedText(text, Qt.TextElideMode.ElideRight, max_px)


class ElidedLabel(QLabel):
    """QLabel that elides text to a fixed pixel budget set at construction."""
    def __init__(self, text: str, max_px: int = 120, parent=None):
        super().__init__(parent)
        self._full_text = text
        self._max_px = max_px
        self.setWordWrap(False)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setMinimumWidth(0)
        super().setText(text)  # show full text until font is known; updateElision called after setFont

    def setFont(self, font):
        super().setFont(font)
        self._apply()

    def _apply(self):
        super().setText(_elide(self._full_text, self.font(), self._max_px))

    def setText(self, text: str):
        self._full_text = text
        self._apply()


class BarChartWidget(QWidget):
    
    date_clicked = Signal(str)
    def __init__(self, parent=None):
        super().__init__(parent)
        self._data = []  # list of {'date': str, 'seconds': float}
        self._accent_color = QColor("#9B59B6")
        self._bar_rects = []
        self._hovered_index: int = -1
        self.setMouseTracking(True)
        self.setFixedHeight(110)
        self.setMinimumWidth(200)
        

    def set_accent_color(self, color: QColor):
        self._accent_color = color
        self.update()

    def set_data(self, days: list[dict]):
        self._data = days
        self.update()

    def paintEvent(self, event):
        if not self._data:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._bar_rects: list[tuple[QRect, str]] = []  # (rect, date_str)

        w = self.width()
        h = self.height()
        label_h = 16
        y_label_h = 12
        chart_h = h - label_h - y_label_h
        n = len(self._data)
        bar_gap = 4
        bar_w = max(4, (w - bar_gap * (n + 1)) // n)
        max_seconds = max((d['seconds'] for d in self._data), default=1)
        if max_seconds == 0:
            max_seconds = 1

        accent = self._accent_color
        max_idx = max(range(n), key=lambda i: self._data[i]['seconds'])

        for i, day in enumerate(self._data):
            x = bar_gap + i * (bar_w + bar_gap)
            ratio = day['seconds'] / max_seconds
            bar_h = max(2, int(ratio * chart_h)) if day['seconds'] > 0 else 0
            bar_y = y_label_h + chart_h - bar_h

            color = QColor(self._accent_color)
            if i == max_idx and day['seconds'] > 0:
                color = color.lighter(130)
            if i == self._hovered_index:
                color = color.lighter(150)
            painter.fillRect(x, bar_y, bar_w, bar_h, color)
            self._bar_rects.append((QRect(x, bar_y, bar_w, bar_h), day['date']))

            day_date = date.fromisoformat(day['date'])
            label = day_date.strftime('%a')
            painter.setPen(self.palette().text().color())
            font = QFont()
            font.setPointSize(7)
            painter.setFont(font)
            painter.drawText(QRect(x, h - label_h, bar_w, label_h),
                             Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                             label)

        painter.setPen(self.palette().text().color())
        font = QFont()
        font.setPointSize(7)
        painter.setFont(font)
        if max_seconds > 0:
            max_bar_x = bar_gap + max_idx * (bar_w + bar_gap)
            painter.drawText(QRect(max_bar_x - 20, 0, bar_w + 40, y_label_h),
                             Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                             self._format_seconds(max_seconds))
        if self._hovered_index != -1 and self._hovered_index != max_idx:
            hov = self._data[self._hovered_index]
            if hov['seconds'] > 0:
                hov_x = bar_gap + self._hovered_index * (bar_w + bar_gap)
                ratio = hov['seconds'] / max_seconds
                hov_bar_h = max(2, int(ratio * chart_h))
                hov_bar_y = y_label_h + chart_h - hov_bar_h
                painter.drawText(QRect(hov_x - 20, hov_bar_y - y_label_h, bar_w + 40, y_label_h),
                                 Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                                 self._format_seconds(hov['seconds']))

        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            for rect, date_str in self._bar_rects:
                if rect.contains(event.pos()):
                    self.date_clicked.emit(date_str)
                    break
    def mouseMoveEvent(self, event):
        new_index = -1
        for i, (rect, _) in enumerate(self._bar_rects):
            if rect.contains(event.pos()):
                new_index = i
                break

        if new_index != self._hovered_index:
            self._hovered_index = new_index
            self.setCursor(Qt.PointingHandCursor if new_index != -1 else Qt.ArrowCursor)
            self.update()
    def leaveEvent(self, event):
        self._hovered_index = -1
        self.update()

    @staticmethod
    def _format_seconds(seconds: float) -> str:
        h = int(seconds // 3600)
        m = round((seconds % 3600) / 60)
        if m == 60:
            h += 1
            m = 0
        if h > 0:
            return f"{h}h {m}m"
        return f"{m}m"


class SessionListWidget(QScrollArea):
    """Scrollable list of individual listening sessions with a partial-range bar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QScrollArea.Shape.NoFrame)
        self._accent = QColor("#9B59B6")
        self._bg = QColor("#3A1A50")
        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        self._layout.addStretch()
        self.setWidget(self._container)
        self.setMinimumHeight(80)
        self.setMaximumHeight(240)

    def set_colors(self, accent: QColor, bg: QColor):
        self._accent = accent
        self._bg = bg
        for i in range(self._layout.count() - 1):
            item = self._layout.itemAt(i)
            if item and item.widget():
                bar = item.widget().findChild(_RangeBar)
                if bar:
                    bar.set_colors(accent, bg)

    def set_data(self, sessions: list[dict], duration: float):
        while self._layout.count() > 1:
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for s in sessions:
            row = self._make_row(s, duration)
            self._layout.insertWidget(self._layout.count() - 1, row)

    def _make_row(self, s: dict, duration: float) -> QWidget:
        row = QWidget()
        hbox = QHBoxLayout(row)
        hbox.setContentsMargins(0, 2, 0, 2)
        hbox.setSpacing(4)

        try:
            from datetime import timedelta
            dt_start = datetime.fromisoformat(s['session_start'])
            secs = s.get('listened_seconds') or 0.0
            dt_end = dt_start + timedelta(seconds=secs)
            ts_text = (
                f"{dt_start.strftime('%b')} {dt_start.day}"
                f" {dt_start.strftime('%H:%M')}–{dt_end.strftime('%H:%M')}"
            )
        except Exception:
            ts_text = s.get('session_start', '—')
            secs = 0.0

        ts_label = QLabel(ts_text)
        ts_label.setObjectName("stats_session_label")
        ts_label.setFixedWidth(92)
        hbox.addWidget(ts_label)

        pos_start = s.get('position_start') or 0.0
        pos_end = s.get('position_end') or 0.0

        if duration > 0:
            def fmt_pct(v):
                return f"{v:.0f}%" if round(v, 1) % 1 == 0 else f"{v:.1f}%"
            raw_delta = (pos_end - pos_start) / duration * 100
            delta = min(100.0, max(-100.0, raw_delta))
            delta_str = f"+{fmt_pct(delta)}" if delta >= 0 else fmt_pct(delta)
            delta_label = QLabel(delta_str)
            pct = min(100, round((pos_end / duration) * 100))
            pct_label = QLabel(f"{fmt_pct(pct)}")
        else:
            delta_label = QLabel("")
            pct_label = QLabel("")

        delta_label.setObjectName("stats_value_label")
        delta_label.setFixedWidth(36)
        delta_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        hbox.addWidget(delta_label)
        hbox.addSpacing(6)

        bar = _RangeBar(pos_start, pos_end, duration, self._accent, self._bg)
        bar.setFixedHeight(6)
        hbox.addWidget(bar, stretch=1)

        pct_label.setObjectName("stats_value_label")
        pct_label.setFixedWidth(32)
        pct_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        hbox.addWidget(pct_label)

        return row


class _RangeBar(QWidget):
    """Flat bar showing which portion of a book was covered in a session."""

    def __init__(self, pos_start: float, pos_end: float, duration: float,
                 accent: QColor, bg: QColor, parent=None):
        super().__init__(parent)
        self._start = pos_start
        self._end = pos_end
        self._duration = duration
        self._accent = accent
        self._bg = bg

    @Property(QColor)
    def accent_color(self):
        return self._accent_color

    @accent_color.setter
    def accent_color(self, color: QColor):
        self._accent_color = color
        self.update()

    @Property(QColor)
    def bg_color(self):
        return self._bg

    @bg_color.setter
    def bg_color(self, color: QColor):
        self._bg = color
        self.update()

    def update_range(self, pos_start: float, pos_end: float, duration: float):
        self._start = pos_start
        self._end = pos_end
        self._duration = duration
        self.update()

    def set_colors(self, accent: QColor, bg: QColor):
        self._accent = accent
        self._bg = bg
        self.update()

    def paintEvent(self, event):
        from PySide6.QtGui import QPen
        painter = QPainter(self)
        w, h = self.width(), self.height()

        painter.fillRect(0, 0, w, h, self._bg)

        if self._duration > 0:
            # Calculate pixel positions as floats first to maintain precision
            x1_float = (self._start / self._duration) * w
            x2_float = (self._end / self._duration) * w

            # Ensure x2_float doesn't exceed widget width
            x2_float = min(x2_float, float(w))

            # Calculate the width of the filled portion
            fill_width_float = x2_float - x1_float

            # Apply the 1px minimum width rule if there's any progress
            if fill_width_float > 0 and fill_width_float < 1:
                fill_width = 1
            else:
                fill_width = int(fill_width_float) # Convert to int for drawing
            painter.fillRect(int(x1_float), 0, fill_width, h, self._accent)

        outline = QColor(self._accent)
        outline.setAlpha(120)
        painter.setPen(QPen(outline, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(0, 0, w - 1, h - 1)

        painter.end()


def _dim_effect():
    from PySide6.QtWidgets import QGraphicsOpacityEffect
    effect = QGraphicsOpacityEffect()
    effect.setOpacity(0.4)
    return effect


class BookDayRow(QWidget):
    clicked = Signal(dict)

    def __init__(self, row_data: dict, assets_dir: str, index: int = 0, placeholder_color: str = "#888888", parent=None):
        super().__init__(parent)
        self._row_data = row_data
        self.setObjectName("stats_book_day_row_alt" if index % 2 else "stats_book_day_row")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # A book is archived if its path is missing (location removed) or if it's explicitly excluded
        self._is_archived = (row_data.get("book_path") is None or
                            row_data.get("is_deleted", 0) or
                            row_data.get("is_excluded", 0))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 21, 2)
        layout.setSpacing(6)

        # Cover thumbnail 48x48
        cover_label = QLabel()
        cover_label.setFixedSize(48, 48)
        cover_label.setAlignment(Qt.AlignCenter)
        book_path = row_data.get("book_path")
        cover_path = row_data.get("cover_path")

        pm = _render_svg_placeholder_bordered(_ARCHIVED_PLACEHOLDER_COLOR if self._is_archived else placeholder_color, 34, 48, 48, offset_y=1)  # BookDayRow init
        cover_label.setPixmap(pm)

        self._cover_label = cover_label
        self._assets_dir = assets_dir
        self._placeholder_color = placeholder_color
        self._has_real_cover = False

        active_cover_path = row_data.get("active_cover_path")
        load_path = active_cover_path or cover_path
        if book_path and load_path and os.path.exists(load_path):
            book_id = row_data.get("book_id")
            if _cover_cache.get(book_id):
                self._apply_cover(_cover_cache[book_id])
            else:
                worker = CoverLoaderWorker(
                    type('_BD', (), {'path': book_path, 'cover_path': cover_path, 'id': book_id})(),
                    active_cover_path=active_cover_path,
                )
                worker.signals.cover_loaded.connect(
                    self._on_cover_loaded, Qt.ConnectionType.QueuedConnection
                )
                QThreadPool.globalInstance().start(worker)

        if self._is_archived:
            cover_label.setGraphicsEffect(_dim_effect())
        layout.addWidget(cover_label)

        # Content block — Row-based layout to allow different widths for time and percentages
        content_block = QVBoxLayout()
        content_block.setSpacing(2)
        content_block.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        is_finished = bool(row_data.get("is_finished", 0))

        # Row 0: Title and Clock Time
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_lbl = ElidedLabel(row_data.get("book_title", "Unknown"), max_px=136)
        if self._is_archived:
            title_lbl.setObjectName("stats_book_title_deleted")
        elif is_finished:
            title_lbl.setObjectName("stats_book_title_finished")
        else:
            title_lbl.setObjectName("stats_book_title")
        f_title = title_lbl.font()
        f_title.setPointSize(f_title.pointSize() - 2)
        title_lbl.setFont(f_title)

        clock_seconds = row_data.get("clock_seconds") or 0.0
        clock_lbl = QLabel(StatsPanel._format_duration(clock_seconds))
        clock_lbl.setObjectName("stats_time_label")
        clock_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        clock_lbl.setFixedWidth(50)
        f_clock = clock_lbl.font()
        f_clock.setPointSize(f_clock.pointSize() - 2)
        clock_lbl.setFont(f_clock)

        title_row.addWidget(title_lbl, stretch=1)
        title_row.addWidget(clock_lbl)
        content_block.addLayout(title_row)

        # Row 1: Author and Percentages
        author_row = QHBoxLayout()
        author_row.setContentsMargins(0, 0, 0, 0)
        author_lbl = ElidedLabel(row_data.get("book_author", ""), max_px=88)
        author_lbl.setObjectName("stats_book_author")
        f_author = author_lbl.font()
        f_author.setPointSize(f_author.pointSize() - 2)
        author_lbl.setFont(f_author)

        duration = row_data.get("book_duration")
        pos_start = row_data.get("period_position_start")
        pos_end = row_data.get("period_position_end")

        prog_lbl = QLabel("")
        prog_lbl.setObjectName("stats_book_time_label")
        prog_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        prog_lbl.setFixedWidth(98)
        f_prog = prog_lbl.font()
        f_prog.setPointSize(f_prog.pointSize() - 2)
        prog_lbl.setFont(f_prog)

        if duration and duration > 0 and pos_start is not None and pos_end is not None:
            pct_start = min(100.0, pos_start / duration * 100)
            pct_end = min(100.0, pos_end / duration * 100)
            delta = pct_end - pct_start
            def fmt_pct(v):
                return f"{v:.0f}%" if round(v, 1) % 1 == 0 else f"{v:.1f}%"
            delta_str = f"+{fmt_pct(delta)}" if delta >= 0 else fmt_pct(delta)
            prog_lbl.setText(f"{fmt_pct(pct_start)} · {fmt_pct(pct_end)} | {delta_str}")
            if delta < 0:
                prog_lbl.setObjectName("stats_book_time_label_dim")

        author_row.addWidget(author_lbl, stretch=1)
        author_row.addWidget(prog_lbl)
        content_block.addLayout(author_row)

        layout.addLayout(content_block, stretch=1)

    def _on_cover_loaded(self, book_id, image):
        if image.isNull():
            return
        self._apply_cover(QPixmap.fromImage(image))

    def _apply_cover(self, pixmap):
        self._has_real_cover = True
        if self._is_archived:
            pixmap = to_grayscale(pixmap)
        scaled = pixmap.scaled(
            48, 48,
            Qt.KeepAspectRatioByExpanding,
            Qt.SmoothTransformation,
        )
        self._cover_label.setPixmap(scaled)

    def update_placeholder_color(self, color: str):
        if self._has_real_cover or self._is_archived:
            return
        self._placeholder_color = color
        pm = _render_svg_placeholder_bordered(color, 34, 48, 48, offset_y=1)
        self._cover_label.setPixmap(pm)

    def refresh_cover(self, cover_path: str):
        book_path = self._row_data.get("book_path")
        book_id = self._row_data.get("book_id")
        if not book_path or not book_id:
            return
        if book_id in _cover_cache:
            del _cover_cache[book_id]
        if cover_path and os.path.exists(cover_path):
            worker = CoverLoaderWorker(
                type('_BD', (), {'path': book_path, 'cover_path': cover_path, 'id': book_id})(),
                active_cover_path=cover_path,
            )
            worker.signals.cover_loaded.connect(
                self._on_cover_loaded, Qt.ConnectionType.QueuedConnection
            )
            QThreadPool.globalInstance().start(worker)
        else:
            pm = _render_svg_placeholder_bordered(_ARCHIVED_PLACEHOLDER_COLOR if self._is_archived else self._placeholder_color, 34, 48, 48, offset_y=1)  # BookDayRow refresh_cover
            self._cover_label.setPixmap(pm)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._row_data)


class FinishedBookThumb(QWidget):
    clicked = Signal(dict)
    def __init__(self, row_data: dict, assets_dir: str, placeholder_color: str = "#888888", parent=None):
        super().__init__(parent)
        self._row_data = row_data
        self._assets_dir = assets_dir
        self._placeholder_color = placeholder_color
        self._has_real_cover = False
        self.setFixedSize(47, 47)
        self._is_archived = (row_data.get("is_deleted", 0) or
                            row_data.get("is_excluded", 0) or
                            row_data.get("book_path") is None)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        cover_label = QLabel()
        cover_label.setFixedSize(47, 47)
        cover_label.setScaledContents(False)
        cover_label.setAlignment(Qt.AlignCenter)
        book_path = row_data.get("book_path")
        cover_path = row_data.get("cover_path")

        self._cover_label = cover_label

        active_cover_path = row_data.get("active_cover_path")
        load_path = active_cover_path or cover_path
        book_id = row_data.get("book_id")
        self._book_id = book_id
        cached = _cover_cache.get(book_id)
        if cached:
            self._apply_cover(cached)
        else:
            pm = _render_svg_placeholder_bordered(_ARCHIVED_PLACEHOLDER_COLOR if self._is_archived else placeholder_color, 34, 47, 47, offset_y=1)  # FinishedBookThumb init
            cover_label.setPixmap(pm)
            if book_path and load_path and os.path.exists(load_path):
                worker = CoverLoaderWorker(
                    type('_FT', (), {'path': book_path, 'cover_path': cover_path, 'id': book_id})(),
                    active_cover_path=active_cover_path,
                )
                worker.signals.cover_loaded.connect(
                    self._on_cover_loaded, Qt.ConnectionType.QueuedConnection
                )
                QThreadPool.globalInstance().start(worker)

        layout.addWidget(cover_label)

    def _on_cover_loaded(self, book_id, image):
        if image.isNull():
            return
        pixmap = QPixmap.fromImage(image)
        _cover_cache[self._book_id] = pixmap
        self._apply_cover(pixmap)

    def _apply_cover(self, pixmap):
        self._has_real_cover = True
        if self._is_archived:
            pixmap = to_grayscale(pixmap)
        side = min(pixmap.width(), pixmap.height())
        x = (pixmap.width() - side) // 2
        y = (pixmap.height() - side) // 2
        cropped = pixmap.copy(x, y, side, side)
        scaled = cropped.scaled(
            47, 47,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._cover_label.setPixmap(scaled)

    def update_placeholder_color(self, color: str):
        if self._has_real_cover or self._is_archived:
            return
        self._placeholder_color = color
        pm = _render_svg_placeholder_bordered(color, 34, 47, 47, offset_y=1)
        self._cover_label.setPixmap(pm)

    def refresh_cover(self, cover_path: str):
        book_path = self._row_data.get("book_path")
        book_id = self._row_data.get("book_id")
        if not book_path or not book_id:
            return
        if book_id in _cover_cache:
            del _cover_cache[book_id]
        if cover_path and os.path.exists(cover_path):
            worker = CoverLoaderWorker(
                type('_FT', (), {'path': book_path, 'cover_path': cover_path, 'id': book_id})(),
                active_cover_path=cover_path,
            )
            worker.signals.cover_loaded.connect(
                self._on_cover_loaded, Qt.ConnectionType.QueuedConnection
            )
            QThreadPool.globalInstance().start(worker)
        else:
            pm = _render_svg_placeholder_bordered(_ARCHIVED_PLACEHOLDER_COLOR if self._is_archived else self._placeholder_color, 34, 47, 47, offset_y=1)  # FinishedBookThumb refresh_cover
            self._cover_label.setPixmap(pm)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._row_data)


class FinishedScrollRow(QWidget):
    """Horizontally scrollable row of FinishedBookThumb widgets with edge scroll indicators."""
    def __init__(self, assets_dir: str, parent=None):
        super().__init__(parent)
        self._assets_dir = assets_dir
        self.setFixedHeight(51)

        self._scroll = QScrollArea(self)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setWidgetResizable(True)
        self._scroll.setSizeAdjustPolicy(QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        self._container = QWidget()
        self._layout = QHBoxLayout(self._container)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._scroll.setWidget(self._container)

        overlay_style = (
            "QPushButton {"
            "  background: rgba(0,0,0,170); color: rgba(255,255,255,140);"
            "  font-size: 7px; border: none; border-radius: 2px;"
            "  padding: 0px; margin: 0px;"
            "}"
            "QPushButton:hover { background: rgba(0,0,0,200); color: rgba(255,255,255,200); }"
        )

        self._hovered = False

        self._left_arrow = QPushButton("◀", self)
        self._left_arrow.setFixedSize(10, 51)
        self._left_arrow.setStyleSheet(overlay_style)
        self._left_arrow.setCursor(Qt.CursorShape.PointingHandCursor)
        self._left_arrow.clicked.connect(lambda: self._scroll_by(-51))
        self._left_arrow.hide()

        self._right_arrow = QPushButton("▶", self)
        self._right_arrow.setFixedSize(10, 51)
        self._right_arrow.setStyleSheet(overlay_style)
        self._right_arrow.setCursor(Qt.CursorShape.PointingHandCursor)
        self._right_arrow.clicked.connect(lambda: self._scroll_by(51))
        self._right_arrow.hide()

        bar = self._scroll.horizontalScrollBar()
        bar.valueChanged.connect(self._update_arrows)
        bar.rangeChanged.connect(self._update_arrows)

        self._current_sig = []

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._scroll.setGeometry(0, 0, self.width(), self.height())
        self._left_arrow.move(0, 0)
        self._right_arrow.move(self.width() - 10, 0)

    def enterEvent(self, event):
        self._hovered = True
        self._update_arrows()

    def leaveEvent(self, event):
        self._hovered = False
        self._left_arrow.hide()
        self._right_arrow.hide()

    def _update_arrows(self, *_):
        if not self._hovered:
            return
        bar = self._scroll.horizontalScrollBar()
        self._left_arrow.setVisible(bar.value() > bar.minimum())
        self._right_arrow.setVisible(bar.value() < bar.maximum())

    def set_items(self, rows: list[dict], click_callback, placeholder_color: str = "#888888"):
        # Order-sensitive signature: book_id alone misses changes that don't
        # alter membership but do alter what's rendered (re-finish reordering,
        # cover swaps, resurrection/exclusion flipping is_deleted or is_excluded —
        # the two independent soft-delete flags, see CLAUDE.md). Comparing the
        # full tuple per row keeps the no-rebuild fast path for the common
        # truly-unchanged case while still catching everything that matters —
        # avoids the rebuild-driven cover flash/stutter risk on panel open.
        incoming_sig = [
            (r.get("book_id"), r.get("event_time"),
             r.get("active_cover_path") or r.get("cover_path"),
             r.get("is_deleted"), r.get("is_excluded"))
            for r in rows
        ]
        if incoming_sig == self._current_sig:
            return
        self._current_sig = incoming_sig
        while self._layout.count() > 0:
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)
        for row in rows:
            thumb = FinishedBookThumb(row, self._assets_dir, placeholder_color)
            thumb.clicked.connect(click_callback)
            self._layout.addWidget(thumb)
        n = len(rows)
        min_w = n * 47 + max(n - 1, 0) * 4  # thumb width + spacing between thumbs
        self._container.setMinimumWidth(min_w)
        # Defer arrow update until layout has settled
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._update_arrows)

    def _scroll_by(self, delta: int):
        bar = self._scroll.horizontalScrollBar()
        bar.setValue(bar.value() + delta)

    def wheelEvent(self, event):
        bar = self._scroll.horizontalScrollBar()
        bar.setValue(bar.value() - event.angleDelta().y() // 2)


class HourlyHeatmap(QWidget):
    """Heatmap: columns = days (newest left), rows = hours 0–23 top to bottom.
    Always shows N_DAYS columns including empty days.
    Hour labels (00:00, 03:00 …) on the left; date labels rotated -90° along the top.
    """

    N_DAYS = 14
    GAP = 1
    CELL = 14
    HOUR_LABEL_W = 32   # wide enough for "00:00" at 11pt
    DATE_LABEL_H = 44   # tall enough for rotated "May 05" at 11pt
    TOTAL_LABEL_H = 44  # bottom gutter for rotated total-minutes label

    def __init__(self, parent=None):
        super().__init__(parent)
        self._accent = QColor("#9B59B6")
        self._label_color = QColor("#9B59B6")
        self._dates: list[str] = []
        self._cells: dict = {}        # (date, hour) -> {seconds, books}
        self.setMouseTracking(True)
        self._hovered: tuple | None = None
        self._footer_alpha: float = 0.0
        self._footer_date: str | None = None  # column the fade is tracking
        self._reveal_progress: float = 1.0     # 1.0 = fully shown (default)
        self._label_progress: float = 1.0      # 1.0 = labels fully shown (at rest)
        self._label_sweep_in: bool = False

        from PySide6.QtCore import QPropertyAnimation, QEasingCurve
        # Animation for footer label
        self._fade_anim = QPropertyAnimation(self, b"footer_alpha")
        self._fade_anim.setDuration(180)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)

        # Animation for grid reveal wave
        self._reveal_anim = QPropertyAnimation(self, b"reveal_progress")
        self._reveal_anim.setDuration(1000)
        self._reveal_anim.setEasingCurve(QEasingCurve.Type.Linear)

        # Animation for the column-label sweep (Phase B transition)
        self._label_anim = QPropertyAnimation(self, b"label_progress")
        self._label_anim.setEasingCurve(QEasingCurve.Type.Linear)

        self._update_size()

    def _update_size(self):
        w = self.HOUR_LABEL_W + self.N_DAYS * (self.CELL + self.GAP)
        h = self.DATE_LABEL_H + 24 * (self.CELL + self.GAP) + self.TOTAL_LABEL_H
        self.setFixedSize(w, h)

    def get_footer_alpha(self) -> float:
        return self._footer_alpha

    def set_footer_alpha(self, v: float):
        self._footer_alpha = v
        self.update()

    def get_reveal_progress(self) -> float:
        return self._reveal_progress

    def set_reveal_progress(self, v: float):
        self._reveal_progress = v
        self.update()

    def animate_reveal(self):
        """Triggers the staggered 'Mexico wave' color animation."""
        self._reveal_anim.stop()
        self._reveal_anim.setStartValue(0.0)
        self._reveal_anim.setEndValue(1.0)
        self._reveal_anim.start()

    def animate_conceal(self, on_done=None):
        """Reverse wave (reveal_progress -> 0) draining the grid. Additive — does
        not alter animate_reveal or paintEvent. Restores the 1000ms reveal
        duration in the finished callback so a normal conceal->reveal sequence
        runs the reveal at full length."""
        self._reveal_anim.stop()
        prev = getattr(self, '_conceal_slot', None)
        if prev is not None:
            self._reveal_anim.finished.disconnect(prev)
            self._conceal_slot = None
        self._reveal_anim.setDuration(600)
        self._reveal_anim.setStartValue(self._reveal_progress)
        self._reveal_anim.setEndValue(0.0)
        if on_done is not None:
            def _f():
                self._reveal_anim.finished.disconnect(_f)
                self._conceal_slot = None
                self._reveal_anim.setDuration(1000)
                on_done()
            self._conceal_slot = _f
            self._reveal_anim.finished.connect(_f)
        self._reveal_anim.start()

    # --- column-label cascade (Phase B; mirror of StreakGrid's row-label cascade) ---
    # Each label fades in/out in place (no internal wipe); only the per-column
    # start-time stagger is animated. Cascade direction mirrors between the two
    # transitions: appearing (labels_in) starts at col 0 (newest, e.g. Jun 18) and
    # sweeps rightward (toward older columns); disappearing (labels_out) starts at
    # the oldest column and sweeps leftward back toward col 0 — the true mirror of
    # the appear direction, not the same sweep played in reverse.
    _LABEL_STAGGER_FRACTION = 0.5   # fraction of total duration spent staggering starts

    def get_label_progress(self) -> float:
        return self._label_progress

    def set_label_progress(self, v: float):
        self._label_progress = v
        self.update()

    def _label_local(self, cascade_pos: int, m: int) -> float:
        """Opacity fraction (0..1) for a label at the given cascade rank, given
        the current global _label_progress. Each label ramps over its own slice
        of the timeline, staggered evenly by rank; _label_progress rises 0->1
        for an entrance and falls 1->0 for an exit, and the per-label ramp
        tracks it directly (no inversion needed — the leading label simply
        owns the slice nearest progress's start value in either direction)."""
        per_col = self._LABEL_STAGGER_FRACTION / max(1, m - 1)
        start = cascade_pos * per_col
        span = 1.0 - self._LABEL_STAGGER_FRACTION
        if span <= 0:
            return 1.0 if self._label_progress >= start else 0.0
        if self._label_sweep_in:
            return max(0.0, min(1.0, (self._label_progress - start) / span))
        # Exit: progress falls 1->0. The leading label (cascade_pos=0) must
        # reach 0 first, so its window is the *last* slice of the 1->0 sweep
        # (i.e. anchored from the top), while the trailing label holds at 1.0
        # the longest (anchored from the bottom).
        end = 1.0 - start
        return max(0.0, min(1.0, (self._label_progress - (end - span)) / span))

    def _disconnect_label_slot(self):
        prev = getattr(self, '_label_slot', None)
        if prev is not None:
            self._label_anim.finished.disconnect(prev)
            self._label_slot = None

    def animate_labels_out(self, on_done=None):
        """Cascade the column labels out (1 -> 0). Oldest column leads, sweeping
        leftward toward col 0 — mirrors animate_labels_in's direction."""
        self._label_anim.stop()
        self._disconnect_label_slot()
        self._label_sweep_in = False
        self._label_anim.setDuration(600)
        self._label_anim.setStartValue(self._label_progress)
        self._label_anim.setEndValue(0.0)
        if on_done is not None:
            def _f():
                self._label_anim.finished.disconnect(_f)
                self._label_slot = None
                on_done()
            self._label_slot = _f
            self._label_anim.finished.connect(_f)
        self._label_anim.start()

    def animate_labels_in(self):
        """Cascade the column labels in (0 -> 1), riding alongside the reveal
        wave. Col 0 (newest) leads, sweeping rightward."""
        self._label_anim.stop()
        self._disconnect_label_slot()
        self._label_sweep_in = True
        self._label_anim.setDuration(1000)
        self._label_anim.setStartValue(0.0)
        self._label_anim.setEndValue(1.0)
        self._label_anim.start()

    from PySide6.QtCore import Property as _Property
    footer_alpha = _Property(float, get_footer_alpha, set_footer_alpha)
    reveal_progress = _Property(float, get_reveal_progress, set_reveal_progress)
    label_progress = _Property(float, get_label_progress, set_label_progress)

    @Property(QColor)
    def accent_color(self):
        return self._accent

    @accent_color.setter
    def accent_color(self, color: QColor):
        self._accent = color
        self.update()

    @Property(QColor)
    def label_color(self):
        return self._label_color

    @label_color.setter
    def label_color(self, color: QColor):
        self._label_color = color
        self.update()

    def set_accent_color(self, color: QColor):
        self._accent = color
        self._label_color = color
        self.update()

    def set_data(self, rows: list[dict], today: date):
        from datetime import timedelta
        self._dates = [
            (today - timedelta(days=i)).isoformat()
            for i in range(self.N_DAYS)
        ]
        self._cells = {(r['date'], r['hour']): r for r in rows}
        
        # Precompute per-column totals for responsive hit-testing and fade logic
        self._col_totals = {}
        for date_str in self._dates:
            self._col_totals[date_str] = sum(
                self._cells[(date_str, h)]['seconds']
                for h in range(24) if (date_str, h) in self._cells
            )
            
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        faint = QColor(self._accent)
        faint.setAlpha(30)
        faint_dim = QColor(self._accent)
        faint_dim.setAlpha(12)  # empty-day cells are dimmer still

        font = QFont()
        font.setPointSize(11)
        painter.setFont(font)

        grid_bottom = self.DATE_LABEL_H + 24 * (self.CELL + self.GAP)

        # Date labels — rotated -90°, dimmed for empty days
        # Cascade order: IN (sweep-in True) -> col 0 (newest) leads, sweeping right;
        #                OUT (sweep-in False) -> oldest column leads, sweeping left
        #                back toward col 0 — the true mirror of the IN direction.
        n_cols = self.N_DAYS
        sweep_in = self._label_sweep_in
        for col_i, date_str in enumerate(self._dates):
            cx = self.HOUR_LABEL_W + col_i * (self.CELL + self.GAP) + self.CELL // 2
            try:
                d = date.fromisoformat(date_str)
                label = d.strftime('%b %d')
            except ValueError:
                label = date_str
            has_data = self._col_totals.get(date_str, 0) > 0
            cascade_pos = col_i if sweep_in else (n_cols - 1 - col_i)
            local = self._label_local(cascade_pos, n_cols)
            if local <= 0.0:
                continue
            label_pen = QColor(self._label_color)
            base_alpha = 60 if not has_data else 255
            label_pen.setAlpha(round(base_alpha * local))
            painter.save()
            painter.setPen(label_pen)
            painter.translate(cx + 2, self.DATE_LABEL_H - 3)
            painter.rotate(-90)
            # After rotate(-90), rect height maps to horizontal ink space in widget coords.
            # CELL alone is too tight for glyphs with ink outside the em square (e.g. "J").
            # CELL * 2 with y=-CELL centers the rect and gives enough room for all glyphs.
            painter.drawText(
                QRect(2, -self.CELL, self.DATE_LABEL_H, self.CELL * 2),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                label
            )
            painter.restore()

        # Hour labels on the left — every 3 hours as "00:00".
        # Cascade order mirrors StreakGrid's row-label cascade: IN -> top (00:00)
        # leads, cascading downward; OUT -> bottom leads, cascading upward.
        hours = list(range(0, 24, 3))
        n_hours = len(hours)
        for rank, hour in enumerate(hours):
            y = self.DATE_LABEL_H + hour * (self.CELL + self.GAP) + 1
            cascade_pos = rank if sweep_in else (n_hours - 1 - rank)
            local = self._label_local(cascade_pos, n_hours)
            if local <= 0.0:
                continue
            label_color = QColor(self._label_color)
            label_color.setAlpha(round(255 * local))
            painter.setPen(label_color)
            painter.drawText(
                QRect(0, y, self.HOUR_LABEL_W - 3, self.CELL),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"{hour:02d}:00"
            )

        # Cells
        for col_i, date_str in enumerate(self._dates):
            x = self.HOUR_LABEL_W + col_i * (self.CELL + self.GAP)
            has_data = self._col_totals.get(date_str, 0) > 0
            
            # Horizontal stagger: wave moves across columns (takes ~25% of animation)
            h_delay = (col_i / (self.N_DAYS - 1)) * 0.25

            for hour in range(24):
                y = self.DATE_LABEL_H + hour * (self.CELL + self.GAP)
                
                # Vertical stagger: flips direction every column (takes ~65% of animation)
                eff_row = hour if col_i % 2 == 0 else (23 - hour)
                v_delay = (eff_row / 23) * 0.65
                
                delay = h_delay + v_delay
                # Multiply by 15 to make the "reveal front" narrow and punchy
                anim_alpha = max(0.0, min(1.0, (self._reveal_progress - delay) * 15))

                c = self._cells.get((date_str, hour))
                if c:
                    intensity = min(1.0, c['seconds'] / 3600.0)
                    color = QColor(self._accent)
                    color.setAlpha(int((40 + intensity * 215) * anim_alpha))
                else:
                    color = QColor(faint if has_data else faint_dim)
                    base_a = 30 if has_data else 12
                    color.setAlpha(int(base_a * anim_alpha))

                if self._hovered == (date_str, hour) and c:
                    color = color.lighter(140)
                painter.fillRect(x, y, self.CELL, self.CELL, color)

        # Total-minutes footer — rotated -90°, below the grid, fades in/out on column hover
        if self._footer_date and self._footer_alpha > 0 and self._col_totals.get(self._footer_date, 0) > 0:
            col_i = self._dates.index(self._footer_date)
            total_min = int(self._col_totals[self._footer_date] / 60)
            label = f"{total_min}m"
            cx = self.HOUR_LABEL_W + col_i * (self.CELL + self.GAP) + self.CELL // 2
            footer_font = QFont()
            footer_font.setPointSize(13)
            painter.setFont(footer_font)
            pen_color = QColor(self._label_color)
            pen_color.setAlphaF(self._footer_alpha)
            painter.save()
            painter.setPen(pen_color)
            painter.translate(cx + 2, grid_bottom + self.TOTAL_LABEL_H)
            painter.rotate(-90)
            painter.drawText(
                QRect(0, -self.CELL // 2, self.TOTAL_LABEL_H - 2, self.CELL),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                label
            )
            painter.restore()

        painter.end()

    def _fade_to(self, target: float):
        self._fade_anim.stop()
        self._fade_anim.setStartValue(self._footer_alpha)
        self._fade_anim.setEndValue(target)
        self._fade_anim.start()

    def mouseMoveEvent(self, event):
        hit = self._hit_test(event.pos())
        if hit != self._hovered:
            self._hovered = hit
            self.update()
            new_date = hit[0] if hit else None
            # Only update the active footer date if the new target has listening data to show.
            # Otherwise, we just trigger a fade out of the current label.
            if new_date and self._col_totals.get(new_date, 0) > 0:
                if new_date != self._footer_date:
                    self._footer_date = new_date
                self._fade_to(1.0)
            else:
                self._fade_to(0.0)
        # Only show tooltip if hovering over a valid hour cell
        if hit and 0 <= hit[1] < 24 and hit in self._cells:
            c = self._cells[hit]
            try:
                d = date.fromisoformat(hit[0])
                friendly_date = f"{d.strftime('%b')} {d.day}"
            except ValueError:
                friendly_date = hit[0]
            total_min = round(c['seconds'] / 60)
            header = f"{friendly_date} {hit[1]:02d}:00 · {total_min} min"
            
            limit = 9
            sorted_books = sorted(c['books'], key=lambda x: -x['minutes'])
            display_books = sorted_books[:limit]
            truncated_count = len(sorted_books) - limit

            rows_html = "".join(
                f"<tr><td style='padding-right:15px'>{b['title']}</td>"
                f"<td align='right'>{b['minutes']}m</td></tr>"
                for b in display_books
            )
            more_color = f"rgba({self._label_color.red()}, {self._label_color.green()}, {self._label_color.blue()}, 0.5)"
            if truncated_count > 0:
                rows_html += f"<tr><td colspan='2' style='font-style: italic; color: {more_color}; padding-top: 2px;'>… and {truncated_count} more</td></tr>"

            html = (
                f"<html><body style='font-size:12px'>"
                f"<table border='0' cellspacing='0' cellpadding='0'>"
                f"<tr><td colspan='2' align='center'><b>{header}</b></td></tr>"
                f"<tr><td colspan='2'><hr style='margin:3px 0'/></td></tr>"
                f"{rows_html}</table>"
                f"</body></html>"
            )

            # Determine tooltip position
            global_pos = event.globalPosition().toPoint()
            win = self.window()
            # local_pos is relative to the main window (300px wide)
            local_pos = win.mapFromGlobal(global_pos)

            # Estimate dimensions to handle flipping logic
            # We use a 160px width budget to fit comfortably in the 300px window
            tt_w = 160
            tt_h = 40 + (len(display_books) * 18) + (18 if truncated_count > 0 else 0)
            
            # Horizontal flip: if on the right side, show to the left of the cursor
            if local_pos.x() > win.width() * 0.6:
                off_x = -(tt_w + 10)
            else:
                off_x = 15

            # Vertical flip: if in the bottom half (near the footer labels), show above
            if local_pos.y() > win.height() * 0.6:
                off_y = -(tt_h + 10)
            else:
                off_y = 15

            show_pos = global_pos + QPoint(off_x, off_y)

            from PySide6.QtWidgets import QToolTip
            QToolTip.showText(show_pos, html, self)
        else:
            from PySide6.QtWidgets import QToolTip
            QToolTip.hideText()

    def leaveEvent(self, event):
        self._hovered = None
        self._fade_to(0.0)
        self.update()

    def _hit_test(self, pos) -> tuple | None:
        x, y = pos.x(), pos.y()
        if x < self.HOUR_LABEL_W:
            return None
        col = (x - self.HOUR_LABEL_W) // (self.CELL + self.GAP)
        if 0 <= col < self.N_DAYS:
             row = (y - self.DATE_LABEL_H) // (self.CELL + self.GAP)
             return (self._dates[col], row)
        return None


class StreakGrid(QWidget):
    """364-day streak calendar. One cell per day: today is the top-left cell,
    days get older moving right then down (day_index = row*N_COLS + col).
    Listened days are filled with the accent color; the longest consecutive run
    gets a brighter inside border; days a book was finished show a centered dot.
    The left gutter holds the current-streak icon + number.

    Geometry mirrors HourlyHeatmap so the two can be swapped in place without
    reflowing the Timeline tab: same CELL, GAP, gutter width, and total 242x448.
    """

    N_ROWS = 26
    N_COLS = 14
    GAP = 1
    CELL = 14
    GUTTER_W = 32          # == HourlyHeatmap.HOUR_LABEL_W (cells start at same x)
    TOP_PAD = 44           # == HourlyHeatmap.DATE_LABEL_H (cells start at same y — grids align)
    BOTTOM_PAD = 14        # keep total 448: 44 + 26*(14+1) + 14 = 44 + 390 + 14 = 448

    def __init__(self, parent=None):
        super().__init__(parent)
        self._accent = QColor("#9B59B6")
        self._label_color = QColor("#9B59B6")
        self._longest_fill = self._derive_longest_fill(self._accent)
        self._finished_dot = self._derive_finished_dot(self._accent)
        self._cache: dict[str, int] = {}
        self._streak: dict = {}
        self._finished: set[str] = set()
        self._longest_dates: set[str] = set()
        self._today: date | None = None
        self._reveal_progress: float = 1.0     # 1.0 = fully shown (default)
        self._label_progress: float = 1.0      # 1.0 = labels fully shown (at rest)
        self._label_sweep_in: bool = False

        self._reveal_anim = QPropertyAnimation(self, b"reveal_progress")
        self._reveal_anim.setDuration(1000)
        self._reveal_anim.setEasingCurve(QEasingCurve.Type.Linear)

        self._label_anim = QPropertyAnimation(self, b"label_progress")
        self._label_anim.setEasingCurve(QEasingCurve.Type.Linear)

        self._update_size()

    def _update_size(self):
        w = self.GUTTER_W + self.N_COLS * (self.CELL + self.GAP)
        h = self.TOP_PAD + self.N_ROWS * (self.CELL + self.GAP) + self.BOTTOM_PAD
        self.setFixedSize(w, h)

    # --- reveal wave (same mechanism as HourlyHeatmap) ---
    def get_reveal_progress(self) -> float:
        return self._reveal_progress

    def set_reveal_progress(self, v: float):
        self._reveal_progress = v
        self.update()

    def animate_reveal(self):
        """Staggered construct wave — alternating columns, left-to-right."""
        self._reveal_anim.stop()
        self._reveal_anim.setDuration(1000)
        self._reveal_anim.setStartValue(0.0)
        self._reveal_anim.setEndValue(1.0)
        self._reveal_anim.start()

    def animate_conceal(self, on_done=None):
        """Reverse wave (reveal_progress -> 0) draining the grid. Restores the
        1000ms reveal duration before firing on_done so the next construct wave
        runs at full length."""
        self._reveal_anim.stop()
        prev = getattr(self, '_conceal_slot', None)
        if prev is not None:
            self._reveal_anim.finished.disconnect(prev)
            self._conceal_slot = None
        self._reveal_anim.setDuration(600)
        self._reveal_anim.setStartValue(self._reveal_progress)
        self._reveal_anim.setEndValue(0.0)
        if on_done is not None:
            def _f():
                self._reveal_anim.finished.disconnect(_f)
                self._conceal_slot = None
                self._reveal_anim.setDuration(1000)
                on_done()
            self._conceal_slot = _f
            self._reveal_anim.finished.connect(_f)
        self._reveal_anim.start()

    reveal_progress = Property(float, get_reveal_progress, set_reveal_progress)

    # --- label cascade (row date labels; mirror of HourlyHeatmap's column-label cascade) ---
    # Each label fades in/out in place (no internal wipe); only the per-row
    # start-time stagger is animated. Enter: top row leads, cascading downward.
    # Exit: bottom row leads, cascading upward (top row last) — the mirror image
    # of the enter direction, not the same sweep played in reverse.
    _LABEL_STAGGER_FRACTION = 0.5   # fraction of total duration spent staggering starts

    def get_label_progress(self) -> float:
        return self._label_progress

    def set_label_progress(self, v: float):
        self._label_progress = v
        self.update()

    label_progress = Property(float, get_label_progress, set_label_progress)

    def _label_local(self, cascade_pos: int, m: int) -> float:
        """Opacity fraction (0..1) for a label at the given cascade rank, given
        the current global _label_progress. Mirrors HourlyHeatmap._label_local —
        see its docstring for the enter/exit window placement rationale."""
        per_col = self._LABEL_STAGGER_FRACTION / max(1, m - 1)
        start = cascade_pos * per_col
        span = 1.0 - self._LABEL_STAGGER_FRACTION
        if span <= 0:
            return 1.0 if self._label_progress >= start else 0.0
        if self._label_sweep_in:
            return max(0.0, min(1.0, (self._label_progress - start) / span))
        end = 1.0 - start
        return max(0.0, min(1.0, (self._label_progress - (end - span)) / span))

    def _disconnect_label_slot(self):
        prev = getattr(self, '_label_slot', None)
        if prev is not None:
            self._label_anim.finished.disconnect(prev)
            self._label_slot = None

    def animate_labels_out(self, on_done=None):
        """Cascade the row labels out (1 -> 0). Bottom row leads, cascading upward."""
        self._label_anim.stop()
        self._disconnect_label_slot()
        self._label_sweep_in = False
        self._label_anim.setDuration(600)
        self._label_anim.setStartValue(self._label_progress)
        self._label_anim.setEndValue(0.0)
        if on_done is not None:
            def _f():
                self._label_anim.finished.disconnect(_f)
                self._label_slot = None
                on_done()
            self._label_slot = _f
            self._label_anim.finished.connect(_f)
        self._label_anim.start()

    def animate_labels_in(self):
        """Cascade the row labels in (0 -> 1), riding alongside the reveal wave.
        Top row leads, cascading downward."""
        self._label_anim.stop()
        self._disconnect_label_slot()
        self._label_sweep_in = True
        self._label_anim.setDuration(1000)
        self._label_anim.setStartValue(0.0)
        self._label_anim.setEndValue(1.0)
        self._label_anim.start()

    # --- color hooks (per-theme override pattern, mirrors HourlyHeatmap) ---
    @Property(QColor)
    def accent_color(self):
        return self._accent

    @accent_color.setter
    def accent_color(self, color: QColor):
        self._accent = color
        self.update()

    @Property(QColor)
    def label_color(self):
        return self._label_color

    @label_color.setter
    def label_color(self, color: QColor):
        self._label_color = color
        self.update()

    @Property(QColor)
    def longest_fill_color(self):
        return self._longest_fill

    @longest_fill_color.setter
    def longest_fill_color(self, color: QColor):
        self._longest_fill = color
        self.update()

    @Property(QColor)
    def finished_dot_color(self):
        return self._finished_dot

    @finished_dot_color.setter
    def finished_dot_color(self, color: QColor):
        self._finished_dot = color
        self.update()

    def set_accent_color(self, color: QColor):
        self._accent = color
        self._label_color = color
        self._longest_fill = self._derive_longest_fill(color)
        self._finished_dot = self._derive_finished_dot(color)
        self.update()

    @staticmethod
    def _derive_longest_fill(accent: QColor) -> QColor:
        # Now the CELL FILL for the longest run (accent is the border). A hue
        # rotation works for the 58 hand-picked named themes but cover-art
        # themes derive accent dynamically from artwork, so a fixed rotation
        # can land anywhere on the wheel. Instead stay on the same hue and
        # lighten/desaturate — a subdued tint of the accent itself — which
        # tracks the cover's palette reliably while still reading as a
        # distinct, lighter cell against the plain accent-filled ones.
        h, s, v, a = accent.getHsv()
        new_s = max(0, int(s * 0.55)) if s else 0
        new_v = min(255, v + 60) if v >= 0 else 200
        return QColor.fromHsv(h if h >= 0 else 0, new_s, new_v, a)

    @staticmethod
    def _derive_finished_dot(accent: QColor) -> QColor:
        # Dark punch-through: same hue, very low value — reads as a hole in a
        # filled cell rather than blending into the accent fill.
        h, s, v, a = accent.getHsv()
        return QColor.fromHsv(h if h >= 0 else 0, s, max(0, int(v * 0.25)), 255)

    # --- data ---
    def set_data(self, cache: dict, streak_info: dict,
                 finished_dates: set, today: date):
        """Store grid data and compute the longest run. Does NOT trigger
        animate_reveal() — the caller owns reveal timing (mirrors the heatmap
        path), so the Timeline-tab reveal isn't double-fired."""
        self._cache = dict(cache)
        self._streak = dict(streak_info)
        self._finished = set(finished_dates)
        self._today = today
        self._longest_dates = self._compute_longest_run(self._cache)
        self.update()

    @staticmethod
    def _compute_longest_run(cache: dict) -> set:
        """Longest run of consecutive listened days. On a tie, the most-recent
        run wins (>= keeps the later set). Returns a set of ISO date strings;
        matched against each cell's date in paintEvent, so orientation-independent."""
        listened = sorted(d for d, v in cache.items() if v)   # ISO sorts chronologically
        best: set = set()
        run: list = []
        prev: date | None = None
        for ds in listened:
            try:
                d = date.fromisoformat(ds)
            except ValueError:
                continue
            if prev is not None and (d - prev).days == 1:
                run.append(ds)
            else:
                run = [ds]
            if len(run) >= len(best):
                best = set(run)
            prev = d
        return best

    def paintEvent(self, event):
        from datetime import timedelta
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        if self._today is None:
            painter.end()
            return

        N_COLS, N_ROWS = self.N_COLS, self.N_ROWS
        col_div = max(1, N_COLS - 1)
        row_div = max(1, N_ROWS - 1)

        from PySide6.QtGui import QFontMetrics

        # --- top band: fire icon + current-streak number, centered ---
        current = int(self._streak.get('current', 0))
        today_iso = self._today.isoformat()
        active = self._cache.get(today_iso, 0) == 1     # listened today => streak active
        info_color = QColor(self._accent)                # accent when active; dimmed when not
        if not active:
            info_color.setAlpha(90)
        info_font = QFont()
        info_font.setPointSize(13)
        info_font.setBold(True)
        num_str = str(current)
        numw = QFontMetrics(info_font).horizontalAdvance(num_str)
        icon_sz = 16
        gap = 4
        total = icon_sz + gap + numw
        start_x = (self.width() - total) // 2
        band_mid = self.TOP_PAD // 2
        icon_pm = load_currentcolor_icon("fire.svg", info_color.name(), icon_sz)
        if not active:
            # name() drops alpha; re-apply dimming by painting at reduced opacity.
            painter.setOpacity(0.45)
        painter.drawPixmap(start_x, band_mid - icon_sz // 2, icon_pm)
        painter.setOpacity(1.0)
        painter.setFont(info_font)
        painter.setPen(info_color)
        painter.drawText(
            QRect(start_x + icon_sz + gap, 0, numw + 2, self.TOP_PAD),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            num_str
        )

        # --- left gutter: row date labels (every 3rd row) ---
        # TODO: hover to reveal the missing/skipped row dates (rows without a label).
        # Cascade order: IN (sweep-in True) -> top row leads, cascading downward;
        #                OUT (sweep-in False) -> bottom row leads, cascading upward
        #                (top row last) — the mirror of the IN direction.
        label_font = QFont()
        label_font.setPointSize(9)          # 9pt fits "Jun 10" in the 32px gutter
        painter.setFont(label_font)
        drawn = list(range(0, N_ROWS, 3))
        m = len(drawn)
        sweep_in = self._label_sweep_in
        for rank, r in enumerate(drawn):
            label_date = self._today - timedelta(days=r * N_COLS)   # leftmost (newest) cell of the row
            label = label_date.strftime('%b %d')
            y = self.TOP_PAD + r * (self.CELL + self.GAP)
            rect = QRect(0, y, self.GUTTER_W - 3, self.CELL)
            cascade_pos = rank if sweep_in else (m - 1 - rank)
            local = self._label_local(cascade_pos, m)
            if local <= 0.0:
                continue
            painter.save()
            label_color = QColor(self._label_color)
            label_color.setAlpha(round(255 * local))
            painter.setPen(label_color)
            painter.drawText(rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, label)
            painter.restore()

        # --- cells ---
        for r in range(N_ROWS):
            # Vertical stagger flips direction every column.
            for c in range(N_COLS):
                day_index = r * N_COLS + c       # 0 = today (top-left)
                cell_date = self._today - timedelta(days=day_index)
                iso = cell_date.isoformat()

                x = self.GUTTER_W + c * (self.CELL + self.GAP)
                y = self.TOP_PAD + r * (self.CELL + self.GAP)

                h_delay = (c / col_div) * 0.25
                eff_row = r if c % 2 == 0 else (N_ROWS - 1 - r)
                v_delay = (eff_row / row_div) * 0.65
                anim_alpha = max(0.0, min(1.0, (self._reveal_progress - (h_delay + v_delay)) * 15))

                listened = self._cache.get(iso, 0) == 1
                is_longest = iso in self._longest_dates
                if is_longest:
                    # Longest run swaps the fill/border roles: the distinct
                    # derived color fills the cell, accent becomes the border.
                    color = QColor(self._longest_fill)
                    color.setAlpha(int(255 * anim_alpha))
                elif listened:
                    color = QColor(self._accent)
                    color.setAlpha(int(255 * anim_alpha))
                else:
                    color = QColor(self._accent)
                    base_a = 30 if iso in self._cache else 12
                    color.setAlpha(int(base_a * anim_alpha))
                painter.fillRect(x, y, self.CELL, self.CELL, color)

                if is_longest and anim_alpha > 0:
                    border = QColor(self._accent)
                    border.setAlpha(int(255 * anim_alpha))
                    painter.save()
                    pen_w = 2
                    pen = QPen(border, pen_w)
                    pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
                    painter.setPen(pen)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    # Qt strokes QRect edges with a +1 bias on the right/bottom vs.
                    # top/left when unantialiased; using a QRectF inset by half the
                    # pen width on all sides keeps the stroke visually symmetric.
                    half = pen_w / 2
                    rectf = QRectF(x + half, y + half, self.CELL - pen_w, self.CELL - pen_w)
                    painter.drawRect(rectf)
                    painter.restore()

                if iso in self._finished and anim_alpha > 0:
                    # Contrasting dark punch-through so the dot reads on filled cells.
                    dot = QColor(self._finished_dot)
                    dot.setAlpha(int(255 * anim_alpha))
                    painter.save()
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(dot)
                    # Sharp centered square, matching the grid's unantialiased
                    # crisp-edge rendering.
                    dot_sz = 4
                    dx = x + (self.CELL - dot_sz) // 2
                    dy = y + (self.CELL - dot_sz) // 2
                    painter.drawRect(dx, dy, dot_sz, dot_sz)
                    painter.restore()

        painter.end()


class TasselOverlay(QWidget):
    """Narrow vertical strip pinned at the top-left of the Timeline tab, mostly
    tucked under the tab bar (only a ~7px sliver shows at rest). Click animates
    it down to reveal a centered icon, holds, then retreats — the view switch
    fires at the start of the retreat."""

    TASSEL_W = 20
    TASSEL_H = 56
    REST_Y = -(TASSEL_H - 7)    # only ~7px peeks below the tab bar
    EXT_Y = 4
    HOLD_MS = 1200
    SLIDE_MS = 200

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(self.TASSEL_W, self.TASSEL_H)
        self._bg = QColor("#9B59B6")
        self._icon: QPixmap | None = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._slide = QPropertyAnimation(self, b"pos")
        self._slide.setDuration(self.SLIDE_MS)
        self._slide.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._on_switch = None
        self._on_retreated_cb = None
        self._busy = False
        self._slide_slot = None

    def _disconnect_slide(self):
        if self._slide_slot is not None:
            try:
                self._slide.finished.disconnect(self._slide_slot)
            except (RuntimeError, TypeError):
                pass
            self._slide_slot = None

    def set_colors(self, accent: QColor):
        # Desaturated flat fill so the tassel reads as a tab, not a focal point.
        h, s, v, a = accent.getHsv()
        self._bg = QColor.fromHsv(h, int(s * 0.35), v, a)
        self.update()

    def set_icon(self, pm: QPixmap):
        self._icon = pm
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._bg)
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 5, 5)
        if self._icon is not None:
            # Icon sits in the lower portion that's revealed when extended.
            iw = self._icon.width()
            ih = self._icon.height()
            ix = (self.TASSEL_W - iw) // 2
            iy = self.TASSEL_H - ih - 6
            painter.drawPixmap(ix, iy, self._icon)
        painter.end()

    def mousePressEvent(self, event):
        self.clicked.emit()

    def play(self, on_switch, on_retreated=None):
        """Slide down (reveal) -> hold -> at retreat start call on_switch()
        if given -> slide back up -> at rest call on_retreated() if given.
        Ignores clicks while a cycle is in flight. Callers that need the
        switch to fire on click rather than at retreat can pass None for
        on_switch and invoke their callback separately."""
        if self._busy:
            return
        self._busy = True
        self._on_switch = on_switch
        self._on_retreated_cb = on_retreated
        self.raise_()
        x = self.x()
        self._slide.stop()
        self._slide.setStartValue(QPoint(x, self.REST_Y))
        self._slide.setEndValue(QPoint(x, self.EXT_Y))
        self._disconnect_slide()
        self._slide_slot = self._on_extended
        self._slide.finished.connect(self._on_extended)
        self._slide.start()

    def _on_extended(self):
        self._disconnect_slide()
        QTimer.singleShot(self.HOLD_MS, self._retreat)

    def _retreat(self):
        # Fire the switch as the tassel starts tucking in, so the panel is
        # already changing while the tassel retreats.
        if self._on_switch is not None:
            self._on_switch()
            self._on_switch = None
        x = self.x()
        self._slide.stop()
        self._slide.setStartValue(QPoint(x, self.EXT_Y))
        self._slide.setEndValue(QPoint(x, self.REST_Y))
        self._disconnect_slide()
        self._slide_slot = self._on_retreated
        self._slide.finished.connect(self._on_retreated)
        self._slide.start()

    def _on_retreated(self):
        self._disconnect_slide()
        self._busy = False
        if self._on_retreated_cb is not None:
            cb = self._on_retreated_cb
            self._on_retreated_cb = None
            cb()


class StatsPanel(QWidget):
    def __init__(self, db, config, parent=None):
        super().__init__(parent)
        self.db = db
        self.config = config
        self.setObjectName("stats_panel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._accent_color = QColor("#9B59B6")
        self._tassel_icon_color = QColor("#000000")
        self._placeholder_color = "#888888"
        self._active_days: list[str] = []
        self._current_day_index: int = 0
        self._active_weeks: list[str] = []
        self._current_week_index: int = 0
        self._active_months: list[str] = []
        self._current_month_index: int = 0
        self._cached_active_days = None
        self._cached_active_weeks = None
        self._cached_active_months = None
        self._assets_dir: str = os.path.join(os.path.dirname(__file__), "..", "assets")
        self._assets_dir = os.path.normpath(self._assets_dir)
        self._build_ui()

    @staticmethod
    def _format_duration(seconds: float) -> str:
        h = int(seconds // 3600)
        m = round((seconds % 3600) / 60)
        if m == 60:
            h += 1
            m = 0
        if h > 0:
            return f"{h}h {m}m"
        return f"{m}m"

    def _build_overall_tab(self) -> QWidget:
        widget = QWidget()
        outer = QVBoxLayout(widget)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Scrollable content area (bar chart + stats grid)
        scroll = QScrollArea()
        scroll.setObjectName("stats_scroll_area")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(10, 10, 10, 10)
        scroll_layout.setSpacing(8)

        self._bar_chart = BarChartWidget()
        self._bar_chart.date_clicked.connect(self._on_bar_date_clicked)
        scroll_layout.addWidget(self._bar_chart)

        grid_container = QWidget()
        grid = QGridLayout(grid_container)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)

        rows = [
            ("Listening time",  "—"),
            ("Books started",   "—"),
            ("Sessions",        "—"),
            ("Longest session", "—"),
            ("Last session",    "—"),
            ("Average session", "—"),
            ("Current streak",  "—"),
            ("Longest streak",  "—"),
        ]

        self._overall_value_labels = []
        for i, (key, default) in enumerate(rows):
            key_lbl = QLabel(key)
            key_lbl.setObjectName("stats_key_label")
            val_lbl = QLabel(default)
            val_lbl.setObjectName("stats_value_label")
            grid.addWidget(key_lbl, i, 0, Qt.AlignmentFlag.AlignLeft)
            grid.addWidget(val_lbl, i, 1, Qt.AlignmentFlag.AlignLeft)
            self._overall_value_labels.append(val_lbl)

        scroll_layout.addWidget(grid_container)
        scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        outer.addWidget(scroll, stretch=1)

        self._finished_section = QWidget()
        self._finished_section.setObjectName("stats_finished_section")
        finished_layout = QVBoxLayout(self._finished_section)
        finished_layout.setContentsMargins(4, 4, 4, 4)
        finished_layout.setSpacing(4)

        finished_header = QLabel("Recently finished")
        finished_header.setObjectName("settings_header")
        finished_layout.addWidget(finished_header)

        self._finished_scroll_row = FinishedScrollRow(self._assets_dir)
        finished_layout.addWidget(self._finished_scroll_row)

        outer.addWidget(self._finished_section)
        self._finished_section.hide()
        return widget

    def on_theme_changed(self, theme: dict):
        from ..themes import _resolve_theme
        theme = _resolve_theme(theme)
        self._accent_color = QColor(theme.get("accent", "#9B59B6"))
        self._tassel_icon_color = QColor(theme.get("accent_dark", theme.get("bg_main", "#000000")))
        self._placeholder_color = theme.get(
            'placeholder_stats',
            theme.get('placeholder_cover',
                theme.get('library_narrator', theme.get('text', '#888888')))
        )
        if hasattr(self, '_bar_chart'):
            self._bar_chart.set_accent_color(self._accent_color)
        if hasattr(self, '_heatmap'):
            self._heatmap.set_accent_color(self._accent_color)
        if hasattr(self, '_streak_grid'):
            self._streak_grid.set_accent_color(self._accent_color)
            outline = theme.get("streak_grid_outline")        # per-theme override hook
            if outline:
                self._streak_grid.longest_fill_color = QColor(outline)
            dot = theme.get("streak_grid_dot")                # per-theme override hook
            if dot:
                self._streak_grid.finished_dot_color = QColor(dot)
            self._streak_grid.update()
        if hasattr(self, '_tassel'):
            self._tassel.set_colors(self._accent_color)
            self._update_tassel_icon()
        if hasattr(self, 'tabs') and hasattr(self, '_settings_svg_path'):
            self.tabs.setTabIcon(5, self._make_settings_icon(theme))
        # Re-render placeholder pixmaps on all existing rows so the color
        # updates immediately without requiring a full tab rebuild.
        if not hasattr(self, '_finished_scroll_row'):
            return
        color = self._placeholder_color
        for attr in ('_finished_scroll_row', '_day_finished_scroll',
                     '_week_finished_scroll', '_month_finished_scroll'):
            scroll_row = getattr(self, attr, None)
            if scroll_row is not None:
                for widget in self._iter_finished_thumbs(scroll_row):
                    widget.update_placeholder_color(color)
        for tab_name in ("Day", "Week", "Month"):
            for widget in self._iter_day_rows(tab_name):
                widget.update_placeholder_color(color)

    def _make_settings_icon(self, theme: dict) -> QIcon:
        color = QColor(theme.get("text", "#ffffff"))
        with open(self._settings_svg_path, 'r') as f:
            svg_data = f.read()
        svg_data = re.sub(r'fill="[^"]*"', f'fill="{color.name()}"', svg_data)
        from PySide6.QtSvg import QSvgRenderer
        from PySide6.QtCore import QByteArray
        renderer = QSvgRenderer(QByteArray(svg_data.encode()))
        size = self.tabs.iconSize()
        pixmap = QPixmap(size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        return QIcon(pixmap)

    def _set_session_label(self, label, seconds, title, session_start_iso):
        if not title:
            label.setText("—")
            label.setToolTip("")
            return
        dur = self._format_duration(seconds)
        max_title_w = 18
        display_title = title if len(title) <= max_title_w else title[:max_title_w - 1] + "…"
        label.setText(f"{dur} · {display_title}")
        if session_start_iso:
            try:
                dt = datetime.fromisoformat(session_start_iso)
                label.setToolTip(dt.strftime("%b %d, %Y  %H:%M"))
            except ValueError:
                label.setToolTip("")
        else:
            label.setToolTip("")

    def refresh_overall(self):
        day_start = self.config.get_day_start_hour()
        stats = self.db.get_overall_stats(day_start)
        self._overall_value_labels[0].setText(self._format_duration(stats['total_seconds']))
        self._overall_value_labels[1].setText(str(stats['books_started']))
        self._overall_value_labels[2].setText(str(stats['total_sessions']))
        days = self.db.get_last_n_days(7, day_start)
        self._bar_chart.set_data(days)

        self._set_session_label(
            self._overall_value_labels[3],
            stats['longest_session_seconds'],
            stats['longest_session_title'],
            stats['longest_session_start'],
        )
        self._set_session_label(
            self._overall_value_labels[4],
            stats['last_session_seconds'],
            stats['last_session_title'],
            stats['last_session_start'],
        )

        # Avg session
        self._overall_value_labels[5].setText(
            self._format_duration(stats['avg_session_seconds'])
        )

        # Recently finished books
        finished = self._inject_active_covers(self.db.get_recently_finished(limit=20))
        self._finished_scroll_row.set_items(finished, self._on_book_row_clicked, self._placeholder_color)
        if finished:
            self._finished_section.show()
        else:
            self._finished_section.hide()

        # Streaks

        streaks = self.db.get_streaks(self.config.get_day_start_hour())
        self._overall_value_labels[6].setText(f"{streaks['current']} days")
        self._overall_value_labels[7].setText(f"{streaks['longest']} days")

    def _build_options_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 0, 10, 10)
        layout.setSpacing(6)

        pref_row = QHBoxLayout()
        day_label = QLabel("Day starts at")
        day_label.setObjectName("settings_header")
        pref_row.addWidget(day_label)
        self.day_start_spin = QSpinBox()
        self.day_start_spin.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.day_start_spin.setRange(0, 23)
        self.day_start_spin.setValue(self.config.get_day_start_hour())
        self.day_start_spin.valueChanged.connect(self.config.set_day_start_hour)
        self.day_start_spin.valueChanged.connect(self._on_day_start_hour_changed)
        self.day_start_spin.setFixedWidth(56)
        pref_row.addWidget(self.day_start_spin)
        pref_row.addStretch()
        layout.addLayout(pref_row)

        accel_header = QLabel("Period scroll acceleration")
        accel_header.setObjectName("settings_header")
        layout.addWidget(accel_header)

        accel_row = QHBoxLayout()
        self._accel_scroll_buttons = {}
        for state in ["On", "Off"]:
            btn = QPushButton(state)
            btn.setObjectName("pattern_button")
            btn.clicked.connect(lambda _, s=state: self._set_accel_scroll(s == "On"))
            accel_row.addWidget(btn)
            self._accel_scroll_buttons[state] = btn
        accel_row.addStretch()
        layout.addLayout(accel_row)
        self._update_accel_scroll_buttons()

        timeline_header = QLabel("Default timeline view")
        timeline_header.setObjectName("settings_header")
        layout.addWidget(timeline_header)

        timeline_row = QHBoxLayout()
        self._timeline_view_buttons = {}
        for state in ["Streak", "Heatmap"]:
            btn = QPushButton(state)
            btn.setObjectName("pattern_button")
            btn.clicked.connect(lambda _, s=state: self._set_default_timeline_view(s))
            timeline_row.addWidget(btn)
            self._timeline_view_buttons[state] = btn
        timeline_row.addStretch()
        layout.addLayout(timeline_row)
        self._update_timeline_view_buttons()

        layout.addStretch()

        self._reset_confirm_label = QLabel("DO YOU WANT TO DELETE ALL LISTENING HISTORY?")
        self._reset_confirm_label.setObjectName("book_detail_confirm_remove")
        self._reset_confirm_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._reset_confirm_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._reset_confirm_label.setFixedHeight(28)
        self._reset_confirm_label.mousePressEvent = lambda _: self._on_reset_stats_confirmed()
        self._reset_confirm_label.setVisible(False)
        layout.addWidget(self._reset_confirm_label)

        self._reset_stats_btn = QPushButton("Reset all stats")
        self._reset_stats_btn.setObjectName("stats_reset_btn")
        self._reset_stats_btn.clicked.connect(self._on_reset_stats)
        layout.addWidget(self._reset_stats_btn)

        self._reset_cancel_timer: QTimer | None = None

        return widget

    def _set_accel_scroll(self, enabled: bool):
        self.config.set_stats_accel_scroll(enabled)
        self._update_accel_scroll_buttons()

    def _update_accel_scroll_buttons(self):
        enabled = self.config.get_stats_accel_scroll()
        for state, btn in self._accel_scroll_buttons.items():
            btn.setProperty("selected", "true" if (state == "On") == enabled else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _set_default_timeline_view(self, state: str):
        # Persists the default only; does NOT switch the live view (takes effect
        # on the next Timeline tab open).
        self.config.set_default_timeline_view("streak" if state == "Streak" else "heatmap")
        self._update_timeline_view_buttons()

    def _update_timeline_view_buttons(self):
        cur = "Streak" if self.config.get_default_timeline_view() == "streak" else "Heatmap"
        for state, btn in self._timeline_view_buttons.items():
            btn.setProperty("selected", "true" if state == cur else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _on_tag_changed(self):
        if hasattr(self, '_tag_manager'):
            self._tag_manager.refresh()
        bdp = getattr(getattr(self, '_panel_manager', None), 'book_detail_panel', None)
        if bdp and bdp.isVisible():
            bdp._rebuild_tag_chips()

    def _build_time_tab(self) -> QWidget:
        widget = QWidget()
        widget.setObjectName("stats_time_tab")
        widget.setAttribute(Qt.WA_StyledBackground, True)
        outer = QVBoxLayout(widget)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(0)

        self._heatmap = HourlyHeatmap()
        self._heatmap.set_accent_color(self._accent_color)
        outer.addWidget(self._heatmap, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        self._streak_grid = StreakGrid()
        self._streak_grid.set_accent_color(self._accent_color)
        outer.addWidget(self._streak_grid, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        outer.addStretch()

        # Which view opens by default (persisted); the tassel toggles transiently.
        self._show_streak_grid = (self.config.get_default_timeline_view() == "streak")
        self._heatmap.setVisible(not self._show_streak_grid)
        self._streak_grid.setVisible(self._show_streak_grid)

        # Tassel overlay — absolutely positioned, mostly tucked under the tab bar.
        self._tassel = TasselOverlay(widget)
        self._tassel.set_colors(self._accent_color)
        self._tassel.move(2, TasselOverlay.REST_Y)
        self._update_tassel_icon()
        self._tassel.clicked.connect(self._on_tassel_clicked)
        self._tassel.raise_()
        return widget

    def _update_tassel_icon(self):
        # Showing streak -> clock icon (click goes to heatmap);
        # showing heatmap -> calendar icon (click goes to streak).
        name = "clock.svg" if self._show_streak_grid else "fire.svg"
        self._tassel.set_icon(load_currentcolor_icon(name, self._tassel_icon_color.name(), 14))

    def _on_tassel_clicked(self):
        # Bookmark animation only; transition fires immediately below. The icon
        # updates only once the bookmark is fully retreated (invisible at rest),
        # so it's always showing the *next* destination when next clicked.
        self._tassel.play(None, on_retreated=self._update_tassel_icon)
        self._switch_timeline_view()

    def _switch_timeline_view(self):
        # Phase 1: drain the current grid AND cascade its labels out, simultaneously.
        # The seam (visibility flip) fires only when BOTH complete (2-counter), so it's
        # correct regardless of which finishes first. Phase 2: reveal + labels-in on the
        # incoming grid. One visibility flip, continuous transition.
        going_to_streak = not self._show_streak_grid
        current = self._streak_grid if self._show_streak_grid else self._heatmap

        pending = {"n": 2}

        def _seam():
            pending["n"] -= 1
            if pending["n"] != 0:
                return
            current.setVisible(False)
            self._show_streak_grid = going_to_streak
            nxt = self._streak_grid if going_to_streak else self._heatmap
            nxt.set_label_progress(0.0)   # PRIME: incoming labels hidden so labels-in sweeps them on
            nxt.setVisible(True)
            # Tassel icon updates separately, once it's fully retreated (see
            # _on_tassel_clicked) — not here, to avoid an icon swap mid-animation.
            # Arm labels-in and reveal BEFORE _refresh_time(): set_data -> update() would
            # otherwise paint one frame at _label_progress=0.0 (hidden labels). Both arm
            # calls schedule an update; Qt coalesces them in the same event-loop turn.
            nxt.animate_labels_in()
            nxt.animate_reveal()          # explicit construct wave — set_data does NOT self-reveal
            self._refresh_time()          # populates the incoming grid
            self._tassel.raise_()

        current.animate_conceal(on_done=_seam)
        current.animate_labels_out(on_done=_seam)

    def _build_daily_tab(self) -> QWidget:
        widget = QWidget()
        outer = QVBoxLayout(widget)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Header
        header = QWidget()
        header.setObjectName("stats_daily_header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 6, 8, 6)

        self._day_prev_btn = QPushButton("‹")
        self._day_prev_btn.setObjectName("stats_nav_btn")
        self._day_prev_btn.setFixedWidth(28)
        self._day_prev_btn.clicked.connect(self._day_prev)
        self._day_prev_btn.mousePressEvent = lambda e: (
            self._day_oldest() if e.button() == Qt.MouseButton.RightButton
            else QPushButton.mousePressEvent(self._day_prev_btn, e)
        )

        self._day_label = QLabel("—")
        self._day_label.setObjectName("stats_day_label")
        self._day_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._day_next_btn = QPushButton("›")
        self._day_next_btn.setObjectName("stats_nav_btn")
        self._day_next_btn.setFixedWidth(28)
        self._day_next_btn.clicked.connect(self._day_next)
        self._day_next_btn.mousePressEvent = lambda e: (
            self._day_newest() if e.button() == Qt.MouseButton.RightButton
            else QPushButton.mousePressEvent(self._day_next_btn, e)
        )

        header_layout.addWidget(self._day_prev_btn)
        header_layout.addWidget(self._day_label, stretch=1)
        header_layout.addWidget(self._day_next_btn)

        def _day_wheel(e):
            days = getattr(self, '_active_days', None) or []
            n = len(days)
            if self.config.get_stats_accel_scroll():
                step = 1 if n <= 30 else 2 if n <= 100 else 3 if n <= 200 else 4 if n <= 300 else 7
            else:
                step = 1
            delta = -step if e.angleDelta().y() > 0 else step
            self._current_day_index = max(0, min(n - 1, self._current_day_index + delta))
            self._refresh_daily()
        header.wheelEvent = _day_wheel

        outer.addWidget(header)

        # Total time for the day (restored to top position)
        self._day_total_label = QLabel("")
        self._day_total_label.setObjectName("stats_day_total")
        self._day_total_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(self._day_total_label)

        # Scrollable book rows
        scroll = QScrollArea()
        scroll.setObjectName("stats_scroll_area")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._day_rows_widget = QWidget()
        self._day_rows_layout = QVBoxLayout(self._day_rows_widget)
        self._day_rows_layout.setContentsMargins(0, 2, 0, 0)
        self._day_rows_layout.setSpacing(2)
        self._day_rows_layout.addStretch()

        scroll.setWidget(self._day_rows_widget)
        outer.addWidget(scroll, stretch=1)

        self._day_finished_section = QWidget()
        self._day_finished_section.setObjectName("stats_finished_section")
        finished_outer = QVBoxLayout(self._day_finished_section)
        finished_outer.setContentsMargins(4, 4, 4, 4)
        finished_outer.setSpacing(4)

        finished_header = QLabel("Finished today")
        finished_header.setObjectName("settings_header")
        finished_outer.addWidget(finished_header)

        self._day_finished_scroll = FinishedScrollRow(self._assets_dir)
        finished_outer.addWidget(self._day_finished_scroll)

        outer.addWidget(self._day_finished_section)
        self._day_finished_section.hide()

        return widget

    def _day_prev(self):
        if self._current_day_index < len(self._active_days) - 1:
            self._current_day_index += 1
            self._refresh_daily()

    def _day_next(self):
        if self._current_day_index > 0:
            self._current_day_index -= 1
            self._refresh_daily()

    def _day_oldest(self):
        if self._active_days:
            self._current_day_index = len(self._active_days) - 1
            self._refresh_daily()

    def _day_newest(self):
        if self._active_days:
            self._current_day_index = 0
            self._refresh_daily()

    def _add_row_safely(self, layout, widget):
        widget.setVisible(False)
        layout.insertWidget(layout.count() - 1, widget)
        widget.setVisible(True)

    def _refresh_daily(self):
        if self._cached_active_days is None:
            self._cached_active_days = self.db.get_active_periods(
                'day', self.config.get_day_start_hour(), include_playback_finished=True)
        self._active_days = self._cached_active_days
        while self._day_rows_layout.count() > 1:
            item = self._day_rows_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not self._active_days:
            self._day_label.setText("No activity yet")
            self._day_total_label.setText("")
            self._day_prev_btn.setEnabled(False)
            self._day_next_btn.setEnabled(False)
            self._day_finished_section.hide()
            return

        self._current_day_index = min(self._current_day_index, len(self._active_days) - 1)
        date_str = self._active_days[self._current_day_index]

        # Format date label
        d = date.fromisoformat(date_str)
        self._day_label.setText(f"{d.strftime('%A, %B')} {d.day}")

        # Navigation button state
        self._day_prev_btn.setEnabled(self._current_day_index < len(self._active_days) - 1)
        self._day_next_btn.setEnabled(self._current_day_index > 0)
    
        rows = self.db.get_daily_book_breakdown(date_str, self.config.get_day_start_hour())
        total_seconds = 0.0
        rows = self._inject_active_covers([r for r in rows if (r.get("clock_seconds") or 0.0) >= 60])
        self._day_rows_widget.setUpdatesEnabled(False)
        for i, row in enumerate(rows):
            total_seconds += row.get("clock_seconds") or 0.0
            book_row = BookDayRow(row, self._assets_dir, index=i, placeholder_color=self._placeholder_color)
            book_row.clicked.connect(self._on_book_row_clicked)
            self._add_row_safely(self._day_rows_layout, book_row)
        self._day_rows_widget.setUpdatesEnabled(True)
        self._day_rows_layout.invalidate()
        self._day_rows_widget.updateGeometry()

        # Blank, not "0m", when the day exists only via a playback finish
        # (no qualifying session rows) — the book shows in the Finished strip.
        self._day_total_label.setText(self._format_duration(total_seconds) if rows else "")

        day_start = self.config.get_day_start_hour()
        finished = self._inject_active_covers(self.db.get_finished_in_period('day', date_str, day_start))
        self._day_finished_scroll.set_items(finished, self._on_book_row_clicked, self._placeholder_color)
        if finished:
            self._day_finished_section.show()
        else:
            self._day_finished_section.hide()

    def _build_weekly_tab(self) -> QWidget:
        widget = QWidget()
        outer = QVBoxLayout(widget)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget()
        header.setObjectName("stats_daily_header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 6, 8, 6)

        self._week_prev_btn = QPushButton("‹")
        self._week_prev_btn.setObjectName("stats_nav_btn")
        self._week_prev_btn.setFixedWidth(28)
        self._week_prev_btn.clicked.connect(self._week_prev)
        self._week_prev_btn.mousePressEvent = lambda e: (
            self._week_oldest() if e.button() == Qt.MouseButton.RightButton
            else QPushButton.mousePressEvent(self._week_prev_btn, e)
        )

        self._week_label = QLabel("—")
        self._week_label.setObjectName("stats_day_label")
        self._week_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._week_next_btn = QPushButton("›")
        self._week_next_btn.setObjectName("stats_nav_btn")
        self._week_next_btn.setFixedWidth(28)
        self._week_next_btn.clicked.connect(self._week_next)
        self._week_next_btn.mousePressEvent = lambda e: (
            self._week_newest() if e.button() == Qt.MouseButton.RightButton
            else QPushButton.mousePressEvent(self._week_next_btn, e)
        )

        header_layout.addWidget(self._week_prev_btn)
        header_layout.addWidget(self._week_label, stretch=1)
        header_layout.addWidget(self._week_next_btn)

        def _week_wheel(e):
            weeks = getattr(self, '_active_weeks', None) or []
            delta = -1 if e.angleDelta().y() > 0 else 1
            self._current_week_index = max(0, min(len(weeks) - 1, self._current_week_index + delta))
            self._refresh_weekly()
        header.wheelEvent = _week_wheel

        outer.addWidget(header)

        # Total time for the week
        self._week_total_label = QLabel("")
        self._week_total_label.setObjectName("stats_day_total")
        self._week_total_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(self._week_total_label)

        scroll = QScrollArea()
        scroll.setObjectName("stats_scroll_area")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._week_rows_widget = QWidget()
        self._week_rows_layout = QVBoxLayout(self._week_rows_widget)
        self._week_rows_layout.setContentsMargins(0, 2, 0, 0)
        self._week_rows_layout.setSpacing(2)
        self._week_rows_layout.addStretch()

        scroll.setWidget(self._week_rows_widget)
        outer.addWidget(scroll, stretch=1)

        self._week_finished_section = QWidget()
        self._week_finished_section.setObjectName("stats_finished_section")
        finished_outer = QVBoxLayout(self._week_finished_section)
        finished_outer.setContentsMargins(4, 4, 4, 4)
        finished_outer.setSpacing(4)

        finished_header = QLabel("Finished this week")
        finished_header.setObjectName("settings_header")
        finished_outer.addWidget(finished_header)

        self._week_finished_scroll = FinishedScrollRow(self._assets_dir)
        finished_outer.addWidget(self._week_finished_scroll)

        outer.addWidget(self._week_finished_section)
        self._week_finished_section.hide()

        return widget

    def _week_prev(self):
        if self._current_week_index < len(self._active_weeks) - 1:
            self._current_week_index += 1
            self._refresh_weekly()

    def _week_next(self):
        if self._current_week_index > 0:
            self._current_week_index -= 1
            self._refresh_weekly()

    def _week_oldest(self):
        if self._active_weeks:
            self._current_week_index = len(self._active_weeks) - 1
            self._refresh_weekly()

    def _week_newest(self):
        if self._active_weeks:
            self._current_week_index = 0
            self._refresh_weekly()

    def _refresh_weekly(self):
        from datetime import datetime, timedelta
        if self._cached_active_weeks is None:
            self._cached_active_weeks = self.db.get_active_periods(
                'week', self.config.get_day_start_hour(), include_playback_finished=True)
        self._active_weeks = self._cached_active_weeks
        while self._week_rows_layout.count() > 1:
            item = self._week_rows_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not self._active_weeks:
            self._week_label.setText("No activity yet")
            self._week_total_label.setText("")
            self._week_prev_btn.setEnabled(False)
            self._week_next_btn.setEnabled(False)
            self._week_finished_section.hide()
            return

        self._current_week_index = min(self._current_week_index, len(self._active_weeks) - 1)
        week_str = self._active_weeks[self._current_week_index]

        year, week = week_str.split("-W")
        monday = datetime.strptime(f"{year}-W{week}-1", "%Y-W%W-%w").date()
        sunday = monday + timedelta(days=6)
        self._week_label.setText(f"{monday.strftime('%b')} {monday.day} – {sunday.strftime('%b')} {sunday.day}")

        self._week_prev_btn.setEnabled(self._current_week_index < len(self._active_weeks) - 1)
        self._week_next_btn.setEnabled(self._current_week_index > 0)

        day_start = self.config.get_day_start_hour()
        rows = self._inject_active_covers(
            [r for r in self.db.get_books_listened_in_period('week', week_str, day_start)
             if (r.get("clock_seconds") or 0.0) >= 60]
        )
        total_seconds = 0.0
        self._week_rows_widget.setUpdatesEnabled(False)
        for i, row in enumerate(rows):
            total_seconds += row.get("clock_seconds") or 0.0
            book_row = BookDayRow(row, self._assets_dir, index=i, placeholder_color=self._placeholder_color)
            book_row.clicked.connect(self._on_book_row_clicked)
            self._add_row_safely(self._week_rows_layout, book_row)
        self._week_rows_widget.setUpdatesEnabled(True)
        self._week_rows_layout.invalidate()
        self._week_rows_widget.updateGeometry()

        self._week_total_label.setText(self._format_duration(total_seconds) if rows else "")

        finished = self._inject_active_covers(self.db.get_finished_in_period('week', week_str, day_start))
        self._week_finished_scroll.set_items(finished, self._on_book_row_clicked, self._placeholder_color)
        if finished:
            self._week_finished_section.show()
        else:
            self._week_finished_section.hide()

    def _build_monthly_tab(self) -> QWidget:
        widget = QWidget()
        outer = QVBoxLayout(widget)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget()
        header.setObjectName("stats_daily_header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 6, 8, 6)

        self._month_prev_btn = QPushButton("‹")
        self._month_prev_btn.setObjectName("stats_nav_btn")
        self._month_prev_btn.setFixedWidth(28)
        self._month_prev_btn.clicked.connect(self._month_prev)
        self._month_prev_btn.mousePressEvent = lambda e: (
            self._month_oldest() if e.button() == Qt.MouseButton.RightButton
            else QPushButton.mousePressEvent(self._month_prev_btn, e)
        )

        self._month_label = QLabel("—")
        self._month_label.setObjectName("stats_day_label")
        self._month_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._month_next_btn = QPushButton("›")
        self._month_next_btn.setObjectName("stats_nav_btn")
        self._month_next_btn.setFixedWidth(28)
        self._month_next_btn.clicked.connect(self._month_next)
        self._month_next_btn.mousePressEvent = lambda e: (
            self._month_newest() if e.button() == Qt.MouseButton.RightButton
            else QPushButton.mousePressEvent(self._month_next_btn, e)
        )

        header_layout.addWidget(self._month_prev_btn)
        header_layout.addWidget(self._month_label, stretch=1)
        header_layout.addWidget(self._month_next_btn)

        def _month_wheel(e):
            months = getattr(self, '_active_months', None) or []
            delta = -1 if e.angleDelta().y() > 0 else 1
            self._current_month_index = max(0, min(len(months) - 1, self._current_month_index + delta))
            self._refresh_monthly()
        header.wheelEvent = _month_wheel

        outer.addWidget(header)

        # Total time for the month
        self._month_total_label = QLabel("")
        self._month_total_label.setObjectName("stats_day_total")
        self._month_total_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(self._month_total_label)

        scroll = QScrollArea()
        scroll.setObjectName("stats_scroll_area")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._month_rows_widget = QWidget()
        self._month_rows_layout = QVBoxLayout(self._month_rows_widget)
        self._month_rows_layout.setContentsMargins(0, 2, 0, 0)
        self._month_rows_layout.setSpacing(2)
        self._month_rows_layout.addStretch()

        scroll.setWidget(self._month_rows_widget)
        outer.addWidget(scroll, stretch=1)

        self._month_finished_section = QWidget()
        self._month_finished_section.setObjectName("stats_finished_section")
        finished_outer = QVBoxLayout(self._month_finished_section)
        finished_outer.setContentsMargins(4, 4, 4, 4)
        finished_outer.setSpacing(4)

        finished_header = QLabel("Finished this month")
        finished_header.setObjectName("settings_header")
        finished_outer.addWidget(finished_header)

        self._month_finished_scroll = FinishedScrollRow(self._assets_dir)
        finished_outer.addWidget(self._month_finished_scroll)

        outer.addWidget(self._month_finished_section)
        self._month_finished_section.hide()

        return widget

    def _month_prev(self):
        if self._current_month_index < len(self._active_months) - 1:
            self._current_month_index += 1
            self._refresh_monthly()

    def _month_next(self):
        if self._current_month_index > 0:
            self._current_month_index -= 1
            self._refresh_monthly()

    def _month_oldest(self):
        if self._active_months:
            self._current_month_index = len(self._active_months) - 1
            self._refresh_monthly()

    def _month_newest(self):
        if self._active_months:
            self._current_month_index = 0
            self._refresh_monthly()

    def _refresh_monthly(self):
        from datetime import datetime
        if self._cached_active_months is None:
            self._cached_active_months = self.db.get_active_periods(
                'month', self.config.get_day_start_hour(), include_playback_finished=True)
        self._active_months = self._cached_active_months
        while self._month_rows_layout.count() > 1:
            item = self._month_rows_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not self._active_months:
            self._month_label.setText("No activity yet")
            self._month_total_label.setText("")
            self._month_prev_btn.setEnabled(False)
            self._month_next_btn.setEnabled(False)
            self._month_finished_section.hide()
            return

        self._current_month_index = min(self._current_month_index, len(self._active_months) - 1)
        month_str = self._active_months[self._current_month_index]

        d = datetime.strptime(month_str, "%Y-%m").date()
        self._month_label.setText(d.strftime("%B %Y"))

        self._month_prev_btn.setEnabled(self._current_month_index < len(self._active_months) - 1)
        self._month_next_btn.setEnabled(self._current_month_index > 0)

        day_start = self.config.get_day_start_hour()
        rows = self._inject_active_covers(
            [r for r in self.db.get_books_listened_in_period('month', month_str, day_start)
             if (r.get("clock_seconds") or 0.0) >= 60]
        )
        total_seconds = 0.0
        self._month_rows_widget.setUpdatesEnabled(False)
        for i, row in enumerate(rows):
            total_seconds += row.get("clock_seconds") or 0.0
            book_row = BookDayRow(row, self._assets_dir, index=i, placeholder_color=self._placeholder_color)
            book_row.clicked.connect(self._on_book_row_clicked)
            self._add_row_safely(self._month_rows_layout, book_row)
        self._month_rows_widget.setUpdatesEnabled(True)
        self._month_rows_layout.invalidate()
        self._month_rows_widget.updateGeometry()

        self._month_total_label.setText(self._format_duration(total_seconds) if rows else "")

        finished = self._inject_active_covers(self.db.get_finished_in_period('month', month_str, day_start))
        self._month_finished_scroll.set_items(finished, self._on_book_row_clicked, self._placeholder_color)
        if finished:
            self._month_finished_section.show()
        else:
            self._month_finished_section.hide()

    def _on_tab_changed(self, index: int):
        self._invalidate_period_cache()
        if self.tabs.tabText(index) == "Overall":
            self.refresh_overall()
        elif self.tabs.tabText(index) == "Day":
            self._refresh_daily()
        elif self.tabs.tabText(index) == "Week":
            self._refresh_weekly()
        elif self.tabs.tabText(index) == "Month":
            self._refresh_monthly()
        elif self.tabs.tabText(index) == "Timeline":
            QTimer.singleShot(0, self._refresh_time)
            grid = self._streak_grid if getattr(self, "_show_streak_grid", False) else self._heatmap
            grid.set_label_progress(1.0)   # labels shown statically on a plain tab open (no sweep)
            grid.animate_reveal()
            self._tassel.raise_()
        elif self.tabs.tabText(index) == "⚙":
            if hasattr(self, '_tag_manager'):
                self._tag_manager.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("stats_tabs")

        self.tabs.addTab(self._build_overall_tab(), "Overall")
        self.tabs.insertTab(1, self._build_time_tab(), "Timeline") # Insert Hour tab at index 1
        self.tabs.addTab(self._build_daily_tab(), "Day")
        self.tabs.addTab(self._build_weekly_tab(), "Week")
        self.tabs.addTab(self._build_monthly_tab(), "Month")
        #self.tabs.addTab(self._build_options_tab(), "⚙️")
        self.tabs.addTab(self._build_options_tab(), "⚙")

        self.tabs.currentChanged.connect(self._on_tab_changed)

        layout.addWidget(self.tabs)
        self.refresh_overall()

    def _on_bar_date_clicked(self, date_str: str):
    # Find the date in active_days and set index
        self._active_days = self.db.get_active_periods(
            'day', self.config.get_day_start_hour(), include_playback_finished=True)
        if date_str in self._active_days:
            self._current_day_index = self._active_days.index(date_str)
        else:
            self._current_day_index = 0
        # Switch to Daily tab
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == "Day":
                self.tabs.setCurrentIndex(i)
                break
    # _on_tab_changed fires automatically, which calls _refresh_daily

    def showEvent(self, event):
        super().showEvent(event)
        QApplication.instance().installEventFilter(self)

    def hideEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        self._cancel_reset_stats()
        super().hideEvent(event)

    def eventFilter(self, obj, event):
        if (
            event.type() == QEvent.Type.MouseButtonPress
            and self._reset_confirm_label.isVisible()
        ):
            gpos = event.globalPosition().toPoint()

            def hits(w):
                return w.isVisible() and QRect(
                    w.mapToGlobal(w.rect().topLeft()),
                    w.mapToGlobal(w.rect().bottomRight())
                ).contains(gpos)

            if not hits(self._reset_confirm_label) and not hits(self._reset_stats_btn):
                self._cancel_reset_stats()
        return super().eventFilter(obj, event)

    def _on_reset_stats(self):
        self._reset_confirm_label.setVisible(True)
        if self._reset_cancel_timer:
            self._reset_cancel_timer.stop()
        self._reset_cancel_timer = QTimer(self)
        self._reset_cancel_timer.setSingleShot(True)
        self._reset_cancel_timer.timeout.connect(self._cancel_reset_stats)
        self._reset_cancel_timer.start(7000)

    def _cancel_reset_stats(self):
        if self._reset_cancel_timer:
            self._reset_cancel_timer.stop()
        self._reset_confirm_label.setVisible(False)

    def _on_reset_stats_confirmed(self):
        self._cancel_reset_stats()
        self.db.reset_stats()
        self.refresh_all()
        bdp = getattr(getattr(self, '_panel_manager', None), 'book_detail_panel', None)
        if bdp and bdp.isVisible():
            bdp._refresh_stats()

    def _on_day_start_hour_changed(self, hour: int):
        """Day boundary changed — every day's attribution shifts, so fully
        rebuild the streak grid cache (clear then build) and re-stamp the cache
        date. Cheap (<=364 rows). hour comes from the signal, not config, so this
        is independent of slot connection order."""
        from datetime import timedelta
        self.db.reset_streak_grid_cache()
        self.db.build_streak_grid_cache(hour)
        today_adjusted = datetime.now() - timedelta(hours=hour)
        self.config.set_streak_grid_cache_date(today_adjusted.strftime('%Y-%m-%d'))

    def _refresh_time(self):
        if getattr(self, "_show_streak_grid", False):
            from datetime import timedelta
            day_start = self.config.get_day_start_hour()
            cache = self.db.get_streak_grid_cache()
            streak = self.db.get_streaks(day_start)
            finished = self.db.get_streak_grid_finished_dates(day_start)
            # Anchor the grid's "today" cell on the day_start_hour-adjusted date
            # (same shift as the cache rows and get_streaks), not the midnight
            # calendar date — else a post-midnight session lands one cell off.
            adjusted_today = (datetime.now() - timedelta(hours=day_start)).date()
            self._streak_grid.set_data(cache, streak, finished, adjusted_today)
        else:
            rows = self.db.get_hourly_heatmap(n_days=14)
            self._heatmap.set_data(rows, datetime.now().date())

    def _invalidate_period_cache(self):
        self._cached_active_days = None
        self._cached_active_weeks = None
        self._cached_active_months = None

    def refresh_all(self):
        self._invalidate_period_cache()
        self.refresh_overall()
        self._refresh_daily()
        self._refresh_weekly()
        self._refresh_monthly()
        self._refresh_time()

    def refresh_current_tab(self):
        self._invalidate_period_cache()
        name = self.tabs.tabText(self.tabs.currentIndex())
        if name == "Overall":
            self.refresh_overall()
        elif name == "Day":
            self._refresh_daily()
        elif name == "Week":
            self._refresh_weekly()
        elif name == "Month":
            self._refresh_monthly()
        elif name == "Timeline":
            self._refresh_time()

    def _inject_active_covers(self, rows: list[dict]) -> list[dict]:
        for row in rows:
            bp = row.get("book_path")
            if bp:
                row["active_cover_path"] = self.db.get_active_cover_path(bp)
        return rows

    def on_cover_changed(self, book_path: str, cover_path: str) -> None:
        current_tab = self.tabs.tabText(self.tabs.currentIndex())
        tab_finished = {
            "Overall": [self._finished_scroll_row],
            "Day": [self._day_finished_scroll],
            "Week": [self._week_finished_scroll],
            "Month": [self._month_finished_scroll],
        }
        for scroll_row in tab_finished.get(current_tab, []):
            for widget in self._iter_finished_thumbs(scroll_row):
                if widget._row_data.get("book_path") == book_path:
                    widget.refresh_cover(cover_path)
        for widget in self._iter_day_rows(current_tab):
            if widget._row_data.get("book_path") == book_path:
                widget.refresh_cover(cover_path)

    def _iter_day_rows(self, tab_name: str):
        layout_map = {
            "Day": self._day_rows_layout,
            "Week": getattr(self, '_week_rows_layout', None),
            "Month": getattr(self, '_month_rows_layout', None),
        }
        layout = layout_map.get(tab_name)
        if layout is None:
            return
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), BookDayRow):
                yield item.widget()

    def _iter_finished_thumbs(self, scroll_row):
        layout = scroll_row._layout
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), FinishedBookThumb):
                yield item.widget()

    def set_panel_manager(self, panel_manager):
        self._panel_manager = panel_manager

    def _on_book_row_clicked(self, row_data: dict):
        if hasattr(self, '_panel_manager'):
            self._panel_manager.open_book_detail(row_data, tab='stats')