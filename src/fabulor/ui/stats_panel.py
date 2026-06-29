# THEME_ANIM_TODO: ElidedLabel, SessionListWidget, BookDayRow, 
# FinishedBookThumb, FinishedScrollRow, StatsPanel
import math
import os
import random
import re
from datetime import date
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QLabel,
    QGridLayout, QSpinBox, QScrollArea, QPushButton, QApplication
)
from PySide6.QtCore import (
    Qt, QRect, QRectF, Signal, QSize, QPoint, QPointF, QEvent, QThreadPool, QTimer, Property,
    QPropertyAnimation, QEasingCurve,
)
from PySide6.QtGui import QPainter, QColor, QFont, QPixmap, QImage, QIcon, QEnterEvent, QPen, QPainterPath
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


# BookDayRow's intrinsic height: 48px cover + 2px top/bottom margin (layout.setContentsMargins(4, 2, 21, 2))
_STATS_ROW_HEIGHT = 52

# BookDayRow's title/author labels previously had only an elision CAP (max_px), not a fixed
# width -- so short text produced a narrower label, shrinking the row's total width below the
# viewport, while long text (elided right up to the cap) produced a wider label. Either way the
# row's total intrinsic width varied per row, and since the row widget isn't clipped to the
# viewport, the right-aligned clock_lbl/prog_lbl visibly shifted left/right between rows/refreshes
# even with no scrollbar-visibility change. Fixed by giving title_lbl/author_lbl a hard
# setFixedWidth equal to the elision budget, computed to exactly fill the row layout's
# fixed-width budget: margins(4+4) + cover(48) + spacing(6) + content_block, where
# content_block = title_lbl + spacing(6) + clock_lbl(50) == author_lbl + spacing(6) + prog_lbl(98).
# The row's right margin was previously 21px (a leftover gutter reservation for a
# conditionally-shown scrollbar); now that the scrollbar gutter lives in the QScrollArea itself
# (always-on, see _fixup_scroll_policy), the row's own right margin only needs to match the left.
_STATS_TITLE_WIDTH = 134
_STATS_AUTHOR_WIDTH = 86


def _fixup_scroll_policy(scroll):
    """Keep the vertical scrollbar's gutter reserved at a constant width at all
    times (policy stays ScrollBarAlwaysOn -- set once at construction, never
    toggled) so viewport width -- and therefore every row's right-aligned content
    -- never shifts between refreshes, regardless of row count or scrollbar
    visibility. Only the handle's visibility/usability changes: hidden via QSS
    (object property) when content doesn't overflow the viewport by a full row,
    so the dead-but-visible scrollbar from a few px of rounding overflow never
    renders, without changing layout width."""
    content = scroll.widget()
    if content is None:
        return
    overflow = content.sizeHint().height() - scroll.viewport().height()
    bar = scroll.verticalScrollBar()
    needs_bar = overflow >= _STATS_ROW_HEIGHT
    if bar.property("inert") == (not needs_bar):
        return
    bar.setProperty("inert", not needs_bar)
    bar.setEnabled(needs_bar)
    bar.style().unpolish(bar)
    bar.style().polish(bar)


class BookDayRow(QWidget):
    clicked = Signal(dict)

    def __init__(self, row_data: dict, assets_dir: str, index: int = 0, placeholder_color: str = "#888888", parent=None):
        super().__init__(parent)
        self._row_data = row_data
        self.setObjectName("stats_book_day_row_alt" if index % 2 else "stats_book_day_row")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # A book is archived if its path is missing (location removed), explicitly
        # excluded, or confirmed missing from disk (is_missing — see db.py's
        # set_book_missing/mark_books_missing)
        self._is_archived = (row_data.get("book_path") is None or
                            row_data.get("is_deleted", 0) or
                            row_data.get("is_excluded", 0) or
                            row_data.get("is_missing", 0))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
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
        title_lbl = ElidedLabel(row_data.get("book_title", "Unknown"), max_px=_STATS_TITLE_WIDTH)
        title_lbl.setFixedWidth(_STATS_TITLE_WIDTH)
        # Finished-title coloring is independent of archived state — only the
        # cover thumbnail dims for is_archived (via _dim_effect above), not
        # the title text. Was previously an if/elif that let _is_archived
        # silently override is_finished, but stats_book_title_deleted has no
        # QSS rule at all, so an archived+finished book's title rendered
        # identically to a never-finished book's — losing the finished cue.
        if is_finished:
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
        author_lbl = ElidedLabel(row_data.get("book_author", ""), max_px=_STATS_AUTHOR_WIDTH)
        author_lbl.setFixedWidth(_STATS_AUTHOR_WIDTH)
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
                            row_data.get("is_missing", 0) or
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
    ARROW_W = 11  # width of each edge-scroll arrow sliver

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

        # Gradient fade instead of a flat rgba box — a hard-edged black
        # rectangle reads as a jagged silhouette against light thumbnails
        # (dark covers just happen to blend with it by coincidence). Each
        # side fades from opaque at the OUTER screen edge (x1/y1 = 0 for
        # left, x2/y2 = 1 for right) toward fully transparent at the inner
        # edge nearest the thumbnail content, so there's no hard boundary
        # anywhere — just a soft vignette the arrow glyph sits on top of.
        self._hovered = False
        self._overlay_rgb = (0, 0, 0)        # set_arrow_colors() overrides per theme
        self._overlay_text_rgb = (255, 255, 255)

        self._left_arrow = QPushButton("◀", self)
        self._left_arrow.setFixedSize(self.ARROW_W, 51)
        self._left_arrow.setCursor(Qt.CursorShape.PointingHandCursor)
        self._left_arrow.clicked.connect(lambda: self._scroll_by(-51))
        self._left_arrow.hide()

        self._right_arrow = QPushButton("▶", self)
        self._right_arrow.setFixedSize(self.ARROW_W, 51)
        self._right_arrow.setCursor(Qt.CursorShape.PointingHandCursor)
        self._right_arrow.clicked.connect(lambda: self._scroll_by(51))
        self._right_arrow.hide()

        self._apply_arrow_styles()

        bar = self._scroll.horizontalScrollBar()
        bar.valueChanged.connect(self._update_arrows)
        bar.rangeChanged.connect(self._update_arrows)

        self._current_sig = []

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._scroll.setGeometry(0, 0, self.width(), self.height())
        self._left_arrow.move(0, 0)
        self._right_arrow.move(self.width() - self.ARROW_W, 0)

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

    def set_arrow_colors(self, overlay_rgb: tuple[int, int, int], text_rgb: tuple[int, int, int]):
        """Theme-driven overlay color for the scroll-edge arrows — a fixed
        black gradient looks like a dark smudge against a light theme
        background (bg_main/bg_deep), so StatsPanel.on_theme_changed derives
        a light-vs-dark overlay from theme luminance and pushes it here.
        Per-cover contrast (some individual covers are light even in a dark
        theme, or vice versa) is deliberately NOT handled — that would mean
        recoloring per-thumbnail, which reads as the overlay "shape-shifting"
        thumbnail to thumbnail; theme-level contrast is the agreed trade-off."""
        self._overlay_rgb = overlay_rgb
        self._overlay_text_rgb = text_rgb
        self._apply_arrow_styles()

    def _apply_arrow_styles(self):
        # Flat, fully-opaque solid-color sliver — no gradient, no
        # border-radius, no border. The gradient/derived-luminance approach
        # was tried and dropped (live testing across themes: black, white,
        # and darkened-bg_main overlays all either looked smudgy, too
        # harsh, or too thin to read clearly). The sliver is only ever
        # shown while the row itself is hovered (_hovered gate in
        # enterEvent/_update_arrows), so its background is fully opaque at
        # rest — :hover on the BUTTON itself only brightens the arrow
        # glyph's text color, it does not change the background further.
        r, g, b = self._overlay_rgb
        tr, tg, tb = self._overlay_text_rgb
        text_base_a, text_hover_a = 140, 200

        common = (
            f"background: rgba({r},{g},{b},255);"
            f"color: rgba({tr},{tg},{tb},{text_base_a});"
            "font-size: 7px; border: none; border-radius: 0px; padding: 0px; margin: 0px;"
        )
        hover_common = f"color: rgba({tr},{tg},{tb},{text_hover_a});"

        self._left_arrow.setStyleSheet(
            f"QPushButton {{ {common} }}"
            f"QPushButton:hover {{ {hover_common} }}"
        )
        self._right_arrow.setStyleSheet(
            f"QPushButton {{ {common} }}"
            f"QPushButton:hover {{ {hover_common} }}"
        )

    def set_items(self, rows: list[dict], click_callback, placeholder_color: str = "#888888"):
        # Order-sensitive signature: book_id alone misses changes that don't
        # alter membership but do alter what's rendered (re-finish reordering,
        # cover swaps, resurrection/exclusion flipping is_deleted, is_excluded,
        # or is_missing — three independent soft-delete-ish flags, see
        # CLAUDE.md). Comparing the full tuple per row keeps the no-rebuild
        # fast path for the common truly-unchanged case while still catching
        # everything that matters — avoids the rebuild-driven cover
        # flash/stutter risk on panel open.
        incoming_sig = [
            (r.get("book_id"), r.get("event_time"),
             r.get("active_cover_path") or r.get("cover_path"),
             r.get("is_deleted"), r.get("is_excluded"), r.get("is_missing"))
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


# --- Grid transition style (A/B toggle, gutters unaffected) ---
# "wave" : original behaviour — diagonal Mexico-wave alpha stagger (per-cell
#          delay = horizontal lead + vertical zigzag), pure alpha fade.
# "rows" : curtain sweep — one row revealed/concealed at a time, straight
#          top->bottom on reveal, bottom->top on conceal (mirrors the gutter
#          cascade direction). No diagonal/zigzag component. Deliberately
#          underwhelming — kept as the "worst case" baseline option.
# "pop"  : same diagonal wave timing as "wave", but cells also scale up from
#          a center-anchored inset rect as they reveal (and shrink back on
#          conceal) instead of only fading alpha. Current default.
# Other candidates tried and rejected: "ripple" (radial from center — left
# the panel empty too long), "cols"/"cols_zig" (symmetric column curtain,
# with/without zigzag — too slow, and speeding up felt off). Wave's longer
# diagonal path is what makes it read as intricate; nothing else tried matched it.
GRID_TRANSITION_STYLE = "pop"


def _grid_cell_anim(progress: float, row: int, col: int, n_rows: int, n_cols: int,
                     style: str = GRID_TRANSITION_STYLE) -> tuple[float, float]:
    """Returns (alpha_frac, scale_frac) for a cell at (row, col), both in 0..1,
    given the current global reveal/conceal progress (0..1) and grid extents.
    alpha_frac drives fillRect alpha; scale_frac (1.0 unless the style scales)
    drives an inset shrink so the cell pops in/out instead of just fading."""
    row_div = max(1, n_rows - 1)
    col_div = max(1, n_cols - 1)

    if style == "rows":
        # Straight row-at-a-time sweep — no column component at all.
        delay = (row / row_div) * 0.85
        alpha = max(0.0, min(1.0, (progress - delay) * 15))
        return alpha, 1.0

    # "wave" and "pop" share the existing diagonal-zigzag timing.
    h_delay = (col / col_div) * 0.25
    eff_row = row if col % 2 == 0 else (n_rows - 1 - row)
    v_delay = (eff_row / row_div) * 0.65
    delay = h_delay + v_delay
    alpha = max(0.0, min(1.0, (progress - delay) * 15))

    if style == "pop":
        return alpha, alpha
    return alpha, 1.0


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
            # The rect's y-axis maps to widget -x (leftward) after rotation, so shifting
            # it by -4 here moves the rendered label 4px left in widget space, off the
            # next cell column, without touching cx (cell anchor) or the hour labels.
            painter.drawText(
                QRect(2, -self.CELL - 4, self.DATE_LABEL_H, self.CELL * 2),
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

            for hour in range(24):
                y = self.DATE_LABEL_H + hour * (self.CELL + self.GAP)

                anim_alpha, anim_scale = _grid_cell_anim(
                    self._reveal_progress, hour, col_i, 24, self.N_DAYS)

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
                if anim_scale >= 1.0:
                    painter.fillRect(x, y, self.CELL, self.CELL, color)
                elif anim_scale > 0.0:
                    inset = (self.CELL * (1.0 - anim_scale)) / 2.0
                    painter.fillRect(QRectF(x + inset, y + inset,
                                             self.CELL - 2 * inset, self.CELL - 2 * inset), color)

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
        self._streak_count: int = 0            # displayed count
        self._last_animated_streak: int | None = None  # value shown as of the last animate_streak_count()
        # Leg-2 grid tie-in: while a pause-then-tick is in flight, the newest
        # _pending_reveal_days day-cells (day_index 0..N-1) render as plain
        # "not yet listened" regardless of self._cache, until _revealed_days
        # catches up — driven in lockstep with the counter by the same timer
        # (see _run_streak_leg2). 0 pending = paint everything from _cache as
        # normal (the default, at-rest state).
        self._pending_reveal_days: int = 0
        self._revealed_days: int = 0

        self._reveal_anim = QPropertyAnimation(self, b"reveal_progress")
        self._reveal_anim.setDuration(1000)
        self._reveal_anim.setEasingCurve(QEasingCurve.Type.Linear)

        self._label_anim = QPropertyAnimation(self, b"label_progress")
        self._label_anim.setEasingCurve(QEasingCurve.Type.Linear)

        # Streak count-up: up to two legs, run sequentially. Leg 1: 0 ->
        # previously-shown value, always linear/even-paced, no slowdown (an
        # eased curve like OutCubic reads as an unwanted pause even when
        # nothing actually changed). Leg 2 (only when the streak increased):
        # previous -> current, short and snappy after an explicit pause —
        # reads as a distinct "tick over" rather than a continuation of leg 1.
        # Leg 2 is a discrete one-step-per-day timer (not a continuous tween)
        # so the number and the grid's per-cell reveal stay in lockstep; total
        # duration scales sub-linearly with day count (see _run_streak_leg2).
        self._STREAK_LEG1_MS = 800
        self._STREAK_PAUSE_MS = 550
        self._STREAK_LEG2_BASE_MS = 250
        self._STREAK_LEG2_SCALE_MS = 300
        self._STREAK_LEG2_CAP_MS = 1200
        self._STREAK_LEG2_SPEEDUP_AFTER_DAYS = 3   # 1-3 days keep the original pace
        self._STREAK_LEG2_SPEEDUP_FACTOR = 0.25     # time past the boundary runs at 25% (75% faster)
        self._streak_count_anim = QPropertyAnimation(self, b"streak_count")
        self._streak_count_anim.setEasingCurve(QEasingCurve.Type.Linear)
        self._streak_leg1_slot = None
        self._streak_leg2_timer: QTimer | None = None
        self._streak_leg2_step_timer: QTimer | None = None

        self._update_size()

    def get_streak_count(self) -> int:
        return self._streak_count

    def set_streak_count(self, v: int):
        self._streak_count = v
        self.update()

    streak_count = Property(int, get_streak_count, set_streak_count)

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
        animate_reveal(), animate_labels_in(), or animate_streak_count() —
        the caller owns all transition timing (mirrors the heatmap path), so
        a plain panel slide-reopen (refresh_current_tab -> _refresh_time ->
        set_data, no animate_* calls) shows everything statically at rest,
        exactly like the grid cells and labels already do."""
        self._cache = dict(cache)
        self._streak = dict(streak_info)
        self._finished = set(finished_dates)
        self._today = today
        self._longest_dates = self._compute_longest_run(self._cache)
        if self._streak_count_anim.state() != QPropertyAnimation.State.Running:
            # Keep showing whatever was last animated to until a caller
            # explicitly asks for a new count-up (see animate_streak_count).
            self._streak_count = self._displayed_streak_target()
        self.update()

    def _displayed_streak_target(self) -> int:
        return int(self._streak.get('current', 0))

    def _disconnect_streak_leg1_slot(self):
        prev = self._streak_leg1_slot
        if prev is not None:
            try:
                self._streak_count_anim.finished.disconnect(prev)
            except (RuntimeError, TypeError):
                pass
            self._streak_leg1_slot = None

    def animate_streak_count(self, previous: int | None = None):
        """Count up to the current streak, in up to two legs:
        Leg 1 (always): 0 -> previous, linear, constant speed, no slowdown.
        Leg 2 (only if the streak increased since last shown): a short pause,
        then a quick snappy tick from previous -> current.
        If the streak hasn't changed since the last call, leg 1 alone runs
        0 -> current (skips leg 2 — there's nothing to tick over to).

        previous: the streak value as of the last time this animation
        actually ran. Defaults to self._last_animated_streak (this-session
        memory only); callers that need it to survive an app restart — i.e.
        StatsPanel, via config.get_last_shown_streak()/set_last_shown_streak()
        — must pass it explicitly. Without a persisted previous value, the
        very first animate_streak_count() call of a new session would always
        treat current as "unchanged" and skip the pause-then-tick leg even
        when the streak genuinely grew since the last time it was shown.

        Callers: _on_tab_changed (tab click) and the view-switch seam — never
        the bare set_data/refresh_current_tab path, so a panel slide-reopen
        never animates."""
        current = self._displayed_streak_target()
        if previous is None:
            previous = self._last_animated_streak
        if previous is None:
            previous = current   # first-ever reveal: no prior value to distinguish from

        self._streak_count_anim.stop()
        self._disconnect_streak_leg1_slot()
        if self._streak_leg2_timer is not None:
            self._streak_leg2_timer.stop()
            self._streak_leg2_timer = None
        if self._streak_leg2_step_timer is not None:
            self._streak_leg2_step_timer.stop()
            self._streak_leg2_step_timer = None

        grew = current > previous
        leg1_target = previous if grew else current
        self._streak_count_anim.setDuration(self._STREAK_LEG1_MS)
        self._streak_count_anim.setStartValue(0)
        self._streak_count_anim.setEndValue(leg1_target)

        # Grid tie-in: set BEFORE leg 1 starts (not at leg-2 start), so the
        # newest cells stay dimmed for the full duration of the count-up to
        # the OLD value and the pause — only popping in once leg 2 actually
        # ticks. Only the "full" path (this method) touches the grid;
        # catch_up_streak_count deliberately never does (slide-reopen must
        # never animate the grid).
        self._pending_reveal_days = (current - previous) if grew else 0
        self._revealed_days = 0
        self.update()

        if grew:
            def _on_leg1_finished():
                self._disconnect_streak_leg1_slot()
                timer = QTimer(self)
                timer.setSingleShot(True)
                timer.timeout.connect(lambda: self._run_streak_leg2(previous, current))
                timer.start(self._STREAK_PAUSE_MS)
                self._streak_leg2_timer = timer
            self._streak_leg1_slot = _on_leg1_finished
            self._streak_count_anim.finished.connect(_on_leg1_finished)

        self._last_animated_streak = current
        self._streak_count_anim.start()

    def catch_up_streak_count(self, previous: int | None):
        """Panel slide-reopen catch-up: the panel was already open on the
        Timeline tab in a prior session/switch (so QTabWidget.currentChanged
        never fires — _on_tab_changed is the only place that normally calls
        animate_streak_count, and the slide-reopen path deliberately never
        triggers grid/label animation). If the persisted previous value
        differs from the freshly-loaded current, that increment would
        otherwise go uncalled-out: set_data already snapped the display
        straight to current with no comparison. This shows previous
        immediately (no count-up, no grid touch), then after the same pause
        used elsewhere, ticks up to current with the leg-2 snap. A no-op
        (straight snap to current) if previous is None/unchanged/decreased —
        there's nothing to tick over to."""
        current = self._displayed_streak_target()
        self._streak_count_anim.stop()
        self._disconnect_streak_leg1_slot()
        if self._streak_leg2_timer is not None:
            self._streak_leg2_timer.stop()
            self._streak_leg2_timer = None
        if self._streak_leg2_step_timer is not None:
            self._streak_leg2_step_timer.stop()
            self._streak_leg2_step_timer = None
        # Never touch the grid on this path — slide-reopen must never animate
        # grid cells, only the catch-up tick (see _run_streak_leg2's
        # pending_days=0 short-circuit).
        self._pending_reveal_days = 0
        self._revealed_days = 0

        self._last_animated_streak = current
        if previous is None or current <= previous:
            self.set_streak_count(current)
            return

        self.set_streak_count(previous)
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self._run_streak_leg2(previous, current))
        timer.start(self._STREAK_PAUSE_MS)
        self._streak_leg2_timer = timer

    def _run_streak_leg2(self, previous: int, current: int):
        """Steps the counter (and, if _pending_reveal_days > 0, one grid cell
        per step) from previous to current, one integer at a time. Total
        duration scales sub-linearly with the day count so a 1-day catch-up
        still feels like the old snappy tick (1 day == LEG2_BASE_MS exactly):
        raw = LEG2_BASE_MS + (sqrt(days) - 1) * LEG2_SCALE_MS, capped at
        LEG2_CAP_MS. Days 1-LEG2_SPEEDUP_AFTER_DAYS keep that pace unmodified;
        beyond that the time PAST the boundary is compressed by
        LEG2_SPEEDUP_FACTOR (continuous at the boundary, not a jump), so a
        large gap (e.g. weeks away) doesn't take proportionally forever and
        reads ~20% snappier than the raw curve. A discrete step timer (not
        a continuous QPropertyAnimation) is used specifically so the displayed
        number and the revealed grid cell change in the exact same frame —
        two independently-timed animations could drift a tick apart."""
        self._streak_leg2_timer = None
        days = current - previous
        if days <= 0:
            self.set_streak_count(current)
            return

        def _raw_total(d):
            return self._STREAK_LEG2_BASE_MS + (d ** 0.5 - 1) * self._STREAK_LEG2_SCALE_MS
        raw = _raw_total(days)
        if days > self._STREAK_LEG2_SPEEDUP_AFTER_DAYS:
            # Days 1-3 keep the original pace; anything beyond is compressed
            # ~20% (applied only to the time PAST the day-3 mark, so the
            # curve stays continuous at the boundary instead of jumping).
            anchor = _raw_total(self._STREAK_LEG2_SPEEDUP_AFTER_DAYS)
            raw = anchor + (raw - anchor) * self._STREAK_LEG2_SPEEDUP_FACTOR
        total_ms = min(self._STREAK_LEG2_CAP_MS, raw)
        step_ms = max(1, int(total_ms / days))

        def _step():
            new_count = self._streak_count + 1
            self.set_streak_count(new_count)
            if self._pending_reveal_days > 0:
                self._revealed_days = min(self._pending_reveal_days, self._revealed_days + 1)
                self.update()
            if new_count >= current:
                self._streak_leg2_step_timer.stop()

        timer = QTimer(self)
        timer.timeout.connect(_step)
        self._streak_leg2_step_timer = timer
        timer.start(step_ms)

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

        from PySide6.QtGui import QFontMetrics

        # --- top band: fire icon + current-streak number, centered ---
        # Displayed value is the animated count (0 -> current), not the raw
        # streak value directly — see _animate_streak_count / set_streak_count.
        today_iso = self._today.isoformat()
        active = self._cache.get(today_iso, 0) == 1     # listened today => streak active
        info_color = QColor(self._accent)                # accent when active; dimmed when not
        if not active:
            info_color.setAlpha(90)
        info_font = QFont()
        info_font.setPointSize(13)
        info_font.setBold(True)
        num_str = str(self._streak_count)
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
            # Each label owns the band down to the next label's row (3 cells,
            # or 2 for the last band) — not just its own 14px cell. The band
            # has far more vertical room than a single cell, so anchor the
            # text to the band's top (with a small margin) instead of
            # vertically centering it in 14px, which clipped tall glyphs
            # (e.g. "g" descender in "Aug") against the cell boundary.
            next_r = drawn[rank + 1] if rank + 1 < len(drawn) else N_ROWS
            band_h = (next_r - r) * self.CELL + (next_r - r - 1) * self.GAP
            rect = QRect(0, y - 1, self.GUTTER_W - 3, band_h - 2)
            cascade_pos = rank if sweep_in else (m - 1 - rank)
            local = self._label_local(cascade_pos, m)
            if local <= 0.0:
                continue
            painter.save()
            label_color = QColor(self._label_color)
            label_color.setAlpha(round(255 * local))
            painter.setPen(label_color)
            painter.drawText(rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop, label)
            painter.restore()

        # --- cells ---
        for r in range(N_ROWS):
            for c in range(N_COLS):
                day_index = r * N_COLS + c       # 0 = today (top-left)
                cell_date = self._today - timedelta(days=day_index)
                iso = cell_date.isoformat()

                x = self.GUTTER_W + c * (self.CELL + self.GAP)
                y = self.TOP_PAD + r * (self.CELL + self.GAP)

                anim_alpha, anim_scale = _grid_cell_anim(
                    self._reveal_progress, r, c, N_ROWS, N_COLS)

                # Leg-2 tie-in: a not-yet-revealed newest cell paints as plain
                # "not listened" regardless of the real cache/longest-run/
                # finished data, until _revealed_days catches up to it.
                still_pending = day_index < (self._pending_reveal_days - self._revealed_days)
                listened = (not still_pending) and self._cache.get(iso, 0) == 1
                is_longest = (not still_pending) and iso in self._longest_dates
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
                if anim_scale >= 1.0:
                    painter.fillRect(x, y, self.CELL, self.CELL, color)
                elif anim_scale > 0.0:
                    inset = (self.CELL * (1.0 - anim_scale)) / 2.0
                    painter.fillRect(QRectF(x + inset, y + inset,
                                             self.CELL - 2 * inset, self.CELL - 2 * inset), color)

                # Border/dot only once the cell has fully popped to size — avoids
                # a full-size border floating over a still-shrunk "pop" fill.
                if is_longest and anim_alpha > 0 and anim_scale >= 0.999:
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

                if (not still_pending) and iso in self._finished and anim_alpha > 0 and anim_scale >= 0.999:
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
    fires at the start of the retreat.

    A decorative TASSEL (cord + bound head + fanned fringe) hangs from the top
    of the tab, threaded through it like a real bookmark ribbon, and drapes
    down into the visible band below the tab bar. The cord swings (idle micro-
    sway + a decaying kick on activation). The whole tassel reads as part of
    the bookmark, not a separate pendulum.

    Click model: a single fixed hit-region (_hit_region) — the tab rect plus a
    tight box around the resting tassel — is the SOLE source of truth for BOTH
    the click test (mousePressEvent) AND the hand cursor (mouseMoveEvent). The
    cursor only shows the hand where a click actually works; there is no dead
    space that lies about being clickable. The region is fixed at the rest
    position (sway is small enough to stay within its slack), so it doesn't
    move under the cursor."""

    # --- tab geometry (unchanged: the tab is still 20x56, peeks 7px, slides
    # the same distance — REST_Y/EXT_Y derive from TASSEL_H and must NOT change) ---
    TASSEL_W = 20
    TASSEL_H = 55
    REST_Y = -(TASSEL_H - 7)    # only ~7px peeks below the tab bar
    EXT_Y = 4
    HOLD_MS = 1200
    SLIDE_MS = 200

    # --- tassel geometry (cord + head + fringe), widget-local coords ---
    SWAY_PAD = 21        # extra width to the RIGHT for the tassel + swing (left edge unchanged)
    CORD_W = 3           # cord stroke width

    # Bead count/radius are rolled once per launch (same "gacha" pattern as
    # the fringe variation caps below): 65% of the time the baseline 6 beads
    # @ 1.6px, the rest split across slightly-more/slightly-smaller options.
    # More beads pairs with a smaller radius so the cord's total beaded
    # texture stays visually consistent across rolls.
    _BEAD_OPTIONS = ((6, 1.6), (7, 1.5), (8, 1.4))
    _BEAD_OPTION_WEIGHTS = (0.65, 0.20, 0.15)
    _HOLE_R = 2.6        # punch-hole radius where the cord threads through the tab
    # Anchor: top-centre of the tab, as if the cord threads through a hole there.
    _ANCHOR_X = TASSEL_W // 2
    _ANCHOR_Y = 4
    # The tassel hangs down-and-right so its body lands in the visible band
    # below the tab bar (the tab itself is mostly tucked at rest). Head sits
    # only slightly right of the anchor (shorter, more vertical cord) rather
    # than far off the tab's right edge.
    _HEAD_X = TASSEL_W - 2    # head sits just past the tab's right edge
    _HEAD_Y = 30              # widget-y of the head top; shorter cord drop
    _HEAD_W = 9               # bound head (wrapped knot) width
    _HEAD_H = 7               # bound head height
    _FRINGE_LEN = 22          # length of the hanging threads
    _FRINGE_SPREAD = 6        # how far the skirt fans out at the bottom (half-width)
    _FRINGE_COUNT = 17        # number of thread lines

    # Individual-thread variation (length + color), so the fringe reads as
    # separate fibers rather than a flat, uniform skirt. Only a minority of
    # threads get treatment — applying it to all of them would just look like
    # a shorter/differently-colored skirt, not "a few threads stand out."
    # Picked once per app launch (random.Random() with no fixed seed, in
    # __init__) and never re-rolled afterwards — varying ACROSS launches adds
    # welcome variety without the per-paint/per-tab-visit flicker that would
    # read as a bug rather than a feature.
    #
    # As of 2026-06-20 the per-thread CAPS themselves are also rolled once per
    # launch ("gacha" roll — see _roll_fringe_caps), skewed toward sane values
    # via random.triangular(low, high, mode) with a rare chance of a much
    # louder result. _FRINGE_LEN_VARY_PX stays a fixed constant (tested: more
    # than ~2px reads as "worn down" rather than "fibrous," no benefit to
    # randomizing it). The values below are the tested sane baseline / mode
    # anchors that _roll_fringe_caps's triangular distributions are built
    # around — they are no longer used directly at runtime.
    _FRINGE_VARY_FRACTION = 0.45   # ~45% of threads get length/color treatment
    _FRINGE_LEN_VARY_PX = 2        # max shortening for a varied thread (px) — fixed, not rolled
    _FRINGE_HUE_VARY = 30          # max hue shift, degrees, for a varied thread
    _FRINGE_LIGHT_VARY = 50        # max value(brightness) shift for a varied thread

    # tassel_head's accent-derived fallback (used only when a theme doesn't
    # set its own tassel_head) gets a much narrower, flat (non-gacha) jitter —
    # "mostly a darker version of accent, sometimes a slightly different hue,"
    # deliberately NOT tied to the fringe's louder per-launch roll.
    _HEAD_VALUE_SCALE_RANGE = (0.35, 0.55)   # accent value (brightness) multiplier
    _HEAD_HUE_VARY = 15                      # max hue jitter, degrees

    # Per-thread fringe animation, restricted to the OUTERMOST threads on
    # each side of the skirt (NOT a random sample across all _FRINGE_COUNT —
    # a random sample reads as the whole skirt subtly shifting together,
    # since "random" thread indices are scattered evenly across the fan and
    # visually blend back into the shared sway; only the threads at the true
    # left/right edges are spatially isolated enough to read as individuals
    # "doing their own thing"). Settled on "phase_lag": reuses the existing
    # shared sway formula, just evaluated at an offset phase per animated
    # thread — cheap (no new state beyond a phase offset per thread, no new
    # trig beyond what _current_sway already does). An "independent" mode
    # (own decoupled oscillator per thread) was A/B tested and dropped — see
    # NOTES.md. The lag applies ONLY to the kick (activation swing), never to
    # idle sway — see _fringe_thread_sway's docstring: lagging idle sway
    # produced a color-blend shimmer between neighboring differently-hued
    # threads (confirmed by live A/B testing 2026-06-20), because idle sway
    # is slow/small enough that the lag reads as a separate competing motion;
    # the kick is fast/large enough that the same lag reads as personality
    # instead.
    _FRINGE_ANIM_EDGE_N = 5            # outermost N threads on EACH side get a phase-lagged KICK
    _FRINGE_ANIM_PHASE_LAG = 1.8       # rad, per-thread stagger (was 0.6 — too subtle to read)

    # --- sway physics constants ---
    _TICK_MS = 33                 # ~30fps, mastches CoverCarousel._TICK_MS
    _DT = _TICK_MS / 1000.0       # tick duration in seconds
    IDLE_AMP = 1.0               # px, barely-noticeable perpetual sway
    IDLE_STEP = 0.03              # _idle_phase increment/tick (~3.5s per full cycle)
    KICK_AMP = 6.0                # px, activation swing amplitude
    KICK_DECAY = 2.2              # exp decay rate (per second)
    KICK_FREQ = 16.0              # rad/s swing frequency (~3 visible cycles before settling)
    _KICK_CLEAR_PX = 0.3          # clear the kick once its ENVELOPE falls below this

    clicked = Signal()

    # Explicit two-tier hue roll (replaces a single wide triangular distribution
    # — measured: triangular(30, 130, 45) has a much longer right tail than left
    # (85deg of span above the mode vs. 15deg below), so the realized rolls
    # skewed loud overall despite 45 being the single most likely value;
    # 100-roll sample came back median 64.5 / mean 67.2, nowhere near "mostly
    # sane." A flat low-probability gate into its own separate range is the
    # explicit, easy-to-reason-about fix: roll the gate first, THEN roll
    # within whichever tier it lands in.
    _HUE_WILD_CHANCE = 0.04        # chance of landing in the wild tier at all
    _HUE_WILD_RANGE = (90, 130)    # wild tier: flat (no skew needed, it's rare already)

    @staticmethod
    def _roll_fringe_caps(rng: random.Random) -> tuple[int, int, float]:
        """Rolls this launch's fringe-variation CAPS (the gacha stage) before
        rolling individual threads against them. hue_vary: 96% of the time a
        sane triangular(30, 70, 45) roll; 4% of the time a flat roll in the
        separate _HUE_WILD_RANGE (90-130) — an explicit two-tier gate rather
        than one continuous distribution, so the wild tier's rarity doesn't
        get diluted by tail mass (see the class comment above). light_vary
        stays a single triangular(30, 50, 45) — that one already behaved.
        _FRINGE_VARY_FRACTION's ceiling derives from where hue_vary landed in
        its OWN tier's range (sane tier maps to [0.45, 0.70]; wild tier maps
        to [0.70, 0.90]), and the actual fraction is triangular-sampled below
        that ceiling, skewed low. Returns (hue_vary, light_vary, vary_fraction)."""
        light_vary = round(rng.triangular(30, 50, 45))
        if rng.random() < TasselOverlay._HUE_WILD_CHANCE:
            wild_low, wild_high = TasselOverlay._HUE_WILD_RANGE
            hue_vary = round(rng.uniform(wild_low, wild_high))
            hue_frac = (hue_vary - wild_low) / (wild_high - wild_low)
            fraction_ceiling = 0.70 + hue_frac * (0.90 - 0.70)
        else:
            hue_vary = round(rng.triangular(30, 70, 45))
            hue_frac = (hue_vary - 30) / (70 - 30)
            fraction_ceiling = 0.45 + hue_frac * (0.70 - 0.45)
        vary_fraction = rng.triangular(0.45, fraction_ceiling, 0.45)
        return hue_vary, light_vary, vary_fraction

    @staticmethod
    def derive_head_fallback(accent: QColor, value_scale: float, hue_delta: int) -> QColor:
        """tassel_head's fallback when a theme doesn't set its own: mostly a
        darker version of accent (value_scale, ~0.35-0.55x), with a small,
        flat (non-gacha) hue jitter — deliberately separate from the fringe's
        louder per-launch roll. Pure function so StatsPanel can roll
        value_scale/hue_delta once per launch independent of TasselOverlay's
        own lifecycle (on_theme_changed may run before self._tassel exists)."""
        h, s, v, a = accent.getHsv()
        new_h = (h + hue_delta) % 360 if h >= 0 else h   # h == -1 for achromatic accent
        new_v = max(0, min(255, round(v * value_scale)))
        return QColor.fromHsv(new_h, s, new_v, a)

    def __init__(self, parent=None):
        super().__init__(parent)
        # Widget is wider (right) and taller (down) than the tab so the tassel
        # has room. Left edge stays at x=0 so the caller's .move(2, REST_Y) and
        # the TASSEL_W/TASSEL_H-derived REST_Y/EXT_Y are intact.
        total_w = self.TASSEL_W + self.SWAY_PAD
        tassel_bottom = self._HEAD_Y + self._HEAD_H + self._FRINGE_LEN + 4
        total_h = max(self.TASSEL_H, tassel_bottom)
        self.setFixedSize(total_w, total_h)
        self._bg = QColor("#9B59B6")
        self._cord_color = QColor("#000000")
        self._head_color = QColor("#000000")
        self._fringe_color = QColor("#000000")
        self._show_tassel = True   # cord/head/fringe decoration only — the tab is ALWAYS shown/clickable
        self._icon: QPixmap | None = None
        self.setMouseTracking(True)   # so mouseMoveEvent fires for the cursor logic
        self._slide = QPropertyAnimation(self, b"pos")
        self._slide.setDuration(self.SLIDE_MS)
        self._slide.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._on_switch = None
        self._on_retreated_cb = None
        self._busy = False
        self._slide_slot = None

        # Per-thread fringe variation, picked once for this app launch (not
        # re-rolled per tab visit or per paint — see the constants above).
        # _fringe_variation[i] = (len_delta_px, hue_delta_deg, value_delta) or
        # None for an untouched thread (the majority).
        rng = random.Random()
        self._bead_count, self._bead_r = rng.choices(
            self._BEAD_OPTIONS, weights=self._BEAD_OPTION_WEIGHTS, k=1)[0]
        hue_vary, light_vary, vary_fraction = self._roll_fringe_caps(rng)
        self._fringe_variation: list[tuple[float, int, int] | None] = []
        for _ in range(self._FRINGE_COUNT):
            if rng.random() < vary_fraction:
                self._fringe_variation.append((
                    rng.uniform(0, self._FRINGE_LEN_VARY_PX),
                    rng.randint(-hue_vary, hue_vary),
                    rng.randint(-light_vary, light_vary),
                ))
            else:
                self._fringe_variation.append(None)

        # Phase-lagged fringe animation: the outermost _FRINGE_ANIM_EDGE_N
        # threads on EACH side of the skirt (indices 0..N-1 and
        # (count-N)..count-1 — see the class comment above for why edges, not
        # a random sample). Picked once per launch, same as the variation
        # roll above — not tied to it (an edge thread can also independently
        # roll length/color variation, or not).
        n = self._FRINGE_COUNT
        edge_n = min(self._FRINGE_ANIM_EDGE_N, n // 2 if n > 1 else 0)
        anim_indices = list(range(edge_n)) + list(range(n - edge_n, n))
        self._fringe_anim_phase_lag: dict[int, float] = {
            i: rng.uniform(-self._FRINGE_ANIM_PHASE_LAG, self._FRINGE_ANIM_PHASE_LAG)
            for i in anim_indices
        }

        # Sway state — idle (perpetual) and kick (transient, decaying) are kept
        # separate and summed only at paint, so the idle sway runs uninterrupted
        # while a kick decays on top of it.
        self._idle_phase = 0.0
        self._kick_t = 0.0
        self._kick_active = False
        self._sway_timer = QTimer(self)   # parented so Qt cleans it up
        self._sway_timer.setInterval(self._TICK_MS)
        self._sway_timer.timeout.connect(self._on_sway_tick)

    @property
    def _tab_rect(self) -> QRect:
        """The tab's sub-rect within the (larger) widget — the source of truth
        for the tab fill in paintEvent."""
        return QRect(0, 0, self.TASSEL_W, self.TASSEL_H)

    @property
    def _tassel_rect(self) -> QRect:
        """Tight box bounding the resting tassel body (head + fringe), with a
        little slack for sway. Kept separate from the tab so the empty top-
        right corner (right of the tab, above the tassel) is NOT clickable."""
        slack = int(self.KICK_AMP) + 2
        left = self._HEAD_X - slack
        right = self._HEAD_X + self._HEAD_W + self._FRINGE_SPREAD + slack
        top = self._HEAD_Y - 2
        bottom = self._HEAD_Y + self._HEAD_H + self._FRINGE_LEN + 2
        return QRect(left, top, right - left, bottom - top)

    def _in_hit_region(self, pt: QPoint) -> bool:
        """Clickable + hand-cursor test: inside the tab OR inside the tassel
        body — but NOT the empty corners between them. The SOLE source of truth
        for both mousePressEvent and the cursor in mouseMoveEvent, so the hand
        cursor never lies about where a click works. Fixed at the rest position
        (sway slack absorbs the small movement), so it doesn't track under the
        pointer. When the tassel decoration is hidden (set_show_tassel(False)),
        only the tab counts — there's nothing drawn at _tassel_rect to click."""
        if self._tab_rect.contains(pt):
            return True
        return self._show_tassel and self._tassel_rect.contains(pt)

    def set_show_tassel(self, show: bool):
        """Toggles the decorative cord/head/fringe only. The bookmark tab
        itself (the view-switch nav control) is never affected — it's the
        sole hit-target this widget exists for; the tassel is decoration on
        top of it."""
        if show == self._show_tassel:
            return
        self._show_tassel = show
        if not show:
            self._sway_timer.stop()
            self._kick_active = False
            self._kick_t = 0.0
        elif self.isVisible():
            self._sway_timer.start()
        self.update()

    def _disconnect_slide(self):
        if self._slide_slot is not None:
            try:
                self._slide.finished.disconnect(self._slide_slot)
            except (RuntimeError, TypeError):
                pass
            self._slide_slot = None

    def set_colors(self, body: QColor):
        self._bg = QColor(body)
        self.update()

    def set_tassel_colors(self, cord: QColor, head: QColor, fringe: QColor):
        self._cord_color = QColor(cord)
        self._head_color = QColor(head)
        self._fringe_color = QColor(fringe)
        self.update()

    def set_icon(self, pm: QPixmap):
        self._icon = pm
        self.update()

    # --- sway driver ---
    def _on_sway_tick(self):
        # Safety net: stop repainting if we're not actually visible, even if a
        # hideEvent was never delivered (tab-stack propagation is not assumed).
        if not self.isVisible():
            return
        self._idle_phase += self.IDLE_STEP
        if self._idle_phase > 2 * math.pi:
            self._idle_phase -= 2 * math.pi
        if self._kick_active:
            self._kick_t += self._DT
            # Clear on the ENVELOPE (not the composited value, which zero-crosses
            # every half-cycle and would clear at the first crossing).
            envelope = self.KICK_AMP * math.exp(-self.KICK_DECAY * self._kick_t)
            if envelope < self._KICK_CLEAR_PX:
                self._kick_active = False
                self._kick_t = 0.0
        self.update()

    def _kick(self):
        """Fresh swing impulse. A reset mid-decay snaps to full amplitude (a new
        impulse, not added-to-velocity) — intended for MVP, not a bug."""
        self._kick_t = 0.0
        self._kick_active = True
        if not self._sway_timer.isActive() and self.isVisible():
            self._sway_timer.start()

    def _current_sway(self) -> float:
        sway = self.IDLE_AMP * math.sin(self._idle_phase)
        if self._kick_active:
            sway += (self.KICK_AMP * math.exp(-self.KICK_DECAY * self._kick_t)
                     * math.sin(self.KICK_FREQ * self._kick_t))
        return sway

    def _fringe_thread_sway(self, i: int, base_sway: float) -> float:
        """Per-thread sway for fringe thread index i. Threads NOT selected for
        animation (the majority) just return base_sway unchanged — same
        motion as the head/cord, no extra cost. The outermost edge threads
        (see _fringe_anim_phase_lag, picked once at launch) only get the lag
        applied to the KICK term, never the idle term — confirmed by live
        testing (2026-06-20) that lagging idle sway specifically is what
        produces a color-blend shimmer between neighboring differently-hued
        threads: idle sway is slow/small enough that the lag between
        neighbors reads as a separate competing motion, whereas the kick is
        fast/large enough that the same lag doesn't. So idle stays perfectly
        uniform across all threads (no shimmer source at rest); only an
        active kick gets the per-thread phase offset, where it reads as
        individual threads catching the swing differently rather than as a
        shimmer."""
        if self._kick_active:
            lag = self._fringe_anim_phase_lag.get(i)
            if lag is not None:
                return (self.IDLE_AMP * math.sin(self._idle_phase)
                        + self.KICK_AMP * math.exp(-self.KICK_DECAY * self._kick_t)
                        * math.sin(self.KICK_FREQ * self._kick_t + lag))
        return base_sway

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # --- tab (unchanged appearance; drawn in _tab_rect, the shared region) ---
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._bg)
        painter.drawRoundedRect(self._tab_rect.adjusted(0, 0, -1, -1), 5, 5)
        if self._icon is not None:
            # Icon sits in the lower portion of the TAB that's revealed when extended.
            iw = self._icon.width()
            ih = self._icon.height()
            ix = (self.TASSEL_W - iw) // 2
            iy = self.TASSEL_H - ih - 7
            painter.drawPixmap(ix, iy, self._icon)

        # --- tassel: cord -> bound head -> fanned fringe (swings with sway) ---
        # Purely decorative — gated on _show_tassel ("Show tassel" in the
        # Stats ⚙ tab). The tab drawn above is NEVER gated: it's the sole
        # click target this widget exists for and must always render/work.
        if not self._show_tassel:
            painter.end()
            return
        sway = self._current_sway()
        # The head is where the cord ends and the fringe begins; sway displaces
        # it (and the fringe below it) sideways, the anchor stays put.
        head_cx = self._HEAD_X + self._HEAD_W / 2 + sway
        head_top = self._HEAD_Y
        head_bottom = self._HEAD_Y + self._HEAD_H

        # Punch hole: where the cord threads through the tab, drawn at the
        # fixed anchor point (it never sways — only the cord/head/fringe
        # below it do). A small dark hollow ring, painted over the tab fill
        # but under the cord, so the cord reads as passing through it rather
        # than just starting at an arbitrary point in space.
        hole_r = self._HOLE_R
        hole_center = QPointF(self._ANCHOR_X, self._ANCHOR_Y)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._bg.darker(160))
        painter.drawEllipse(hole_center, hole_r, hole_r)
        painter.setBrush(self._bg.darker(220))
        painter.drawEllipse(hole_center, hole_r * 0.55, hole_r * 0.55)

        # Cord: a real loop (like a ribbon threaded through the bookmark hole
        # and tied at the top) — not just a bow. The path swings OUT past the
        # head's x-position and slightly UP first, then hooks back down INTO
        # the head from nearly straight above, so the cord arrives vertical
        # rather than diagonal. c1 pushes the curve outward/upward from the
        # anchor (the widest point of the loop). c2 sits directly above
        # head_top_pt (same x — not off to the side) so the curve's tangent at
        # the endpoint points straight down into the head.
        anchor = QPointF(self._ANCHOR_X, self._ANCHOR_Y)
        head_top_pt = QPointF(head_cx, head_top)
        loop_out = self.SWAY_PAD - 6   # how far the loop swings out past the head
        c1 = QPointF(self._ANCHOR_X + loop_out + sway * 0.6,
                     self._ANCHOR_Y - 2)
        c2 = QPointF(head_cx,
                     head_top - self._HEAD_H * 0.8)
        cord = QPainterPath(anchor)
        cord.cubicTo(c1, c2, head_top_pt)
        pen = QPen(self._cord_color, max(1.0, self.CORD_W - 1.5))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(cord)

        # Beads: small filled dots strung along the cord at even path-length
        # intervals, giving it a braided/knotted texture instead of reading as
        # a single smooth plastic strand. A subtle highlight dot (lighter, half
        # the radius, offset up-left) on each bead sells it as a rounded bead
        # rather than a flat circle.
        painter.setPen(Qt.PenStyle.NoPen)
        bead_h, bead_s, bead_v, bead_a = self._cord_color.getHsv()
        bead_highlight = QColor.fromHsv(bead_h, max(0, bead_s - 60), min(255, bead_v + 70), bead_a)
        for i in range(1, self._bead_count + 1):
            t = i / (self._bead_count + 1)
            pt = cord.pointAtPercent(t)
            painter.setBrush(self._cord_color)
            painter.drawEllipse(pt, self._bead_r, self._bead_r)
            painter.setBrush(bead_highlight)
            painter.drawEllipse(
                QPointF(pt.x() - self._bead_r * 0.35, pt.y() - self._bead_r * 0.35),
                self._bead_r * 0.4, self._bead_r * 0.4,
            )

        # Bound head: a small rounded knot (the wrapped binding of the tassel).
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._head_color)
        head_rect = QRectF(head_cx - self._HEAD_W / 2, head_top,
                           self._HEAD_W, self._HEAD_H)
        painter.drawRoundedRect(head_rect, 2.5, 2.5)

        # Fringe: a fan of fine threads hanging from the head, widening into a
        # skirt at the bottom. The sway tilts the whole fan. A minority of
        # threads (see _fringe_variation, picked once at launch) are slightly
        # shorter and/or hue/brightness-shifted, so the skirt reads as
        # individual fibers rather than one flat-colored shape.
        fringe_pen = QPen(self._fringe_color, 1)
        fringe_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        n = self._FRINGE_COUNT
        base_h, base_s, base_v, base_a = self._fringe_color.getHsv()
        for i in range(n):
            frac = (i / (n - 1)) - 0.5 if n > 1 else 0.0   # -0.5..0.5
            variation = self._fringe_variation[i] if i < len(self._fringe_variation) else None
            length = self._FRINGE_LEN
            if variation is not None:
                len_delta, hue_delta, value_delta = variation
                length -= len_delta
                fringe_pen.setColor(QColor.fromHsv(
                    (base_h + hue_delta) % 360,
                    base_s,
                    max(0, min(255, base_v + value_delta)),
                    base_a,
                ))
            else:
                fringe_pen.setColor(self._fringe_color)
            painter.setPen(fringe_pen)
            top = QPointF(head_cx + frac * (self._HEAD_W - 2), head_bottom)
            # Threads splay outward and the whole skirt leans with the sway.
            # A few edge threads (see _fringe_thread_sway) catch the KICK
            # swing slightly differently — idle sway stays perfectly uniform
            # (see that method's docstring for why).
            thread_sway = self._fringe_thread_sway(i, sway)
            bottom = QPointF(head_cx + frac * 2 * self._FRINGE_SPREAD + thread_sway * 0.5,
                             head_bottom + length)
            painter.drawLine(top, bottom)

        painter.end()

    def showEvent(self, event):
        super().showEvent(event)
        if self._show_tassel and not self._sway_timer.isActive():
            self._sway_timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._sway_timer.stop()
        self._kick_active = False
        self._kick_t = 0.0

    def mousePressEvent(self, event):
        # The bookmark tab AND the tassel body are clickable; the empty corners
        # between/around them are not. Same source of truth the cursor uses, so
        # the hand never lies about where a click works.
        if self._in_hit_region(event.position().toPoint()):
            self.clicked.emit()
        else:
            event.ignore()

    def mouseMoveEvent(self, event):
        # Hand cursor ONLY where a click actually does something; default arrow
        # elsewhere on the widget (so no dead space shows a misleading hand).
        if self._in_hit_region(event.position().toPoint()):
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.unsetCursor()

    def leaveEvent(self, event):
        self.unsetCursor()

    @property
    def is_busy(self) -> bool:
        """True from the moment a play() cycle starts until the bookmark is
        fully retreated at rest. Callers that trigger a parallel transition
        alongside the bookmark animation (see StatsPanel._on_tassel_clicked)
        must check this BEFORE doing anything — play() itself already no-ops
        on repeat clicks, but a caller that unconditionally kicks off its own
        side effect regardless of play()'s return would still re-trigger that
        side effect on every click, even though the bookmark visually ignored
        it. Multiple overlapping StatsPanel transitions racing over the same
        grid visibility/state is what produced the indefinite hang."""
        return self._busy

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
        self._kick()   # swing impulse on slide-down (orthogonal to _busy/callbacks)

    def _on_extended(self):
        self._disconnect_slide()
        QTimer.singleShot(self.HOLD_MS, self._retreat)

    def _retreat(self):
        # Fire the switch as the tassel starts tucking in, so the panel is
        # already changing while the tassel retreats.
        self._kick()   # swing impulse on retreat (orthogonal to _busy/callbacks)
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
        self._tassel_body_color = QColor("#9B59B6")
        self._tassel_icon_color = QColor("#000000")
        self._tassel_cord_color = QColor("#000000")
        self._tassel_head_color = QColor("#000000")
        self._tassel_fringe_color = QColor("#000000")
        # tassel_head's accent-derived fallback jitter, rolled once per app
        # launch (only used when a theme doesn't set its own tassel_head —
        # see TasselOverlay.derive_head_fallback). Rolled here, not in
        # TasselOverlay, because on_theme_changed can run before self._tassel
        # exists.
        head_rng = random.Random()
        self._head_value_scale = head_rng.uniform(*TasselOverlay._HEAD_VALUE_SCALE_RANGE)
        self._head_hue_delta = head_rng.randint(
            -TasselOverlay._HEAD_HUE_VARY, TasselOverlay._HEAD_HUE_VARY)
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
        # bookmark_body/bookmark_icon are independently overridable; their
        # fallbacks reproduce the original derivations exactly.
        accent_light = theme.get("accent_light", "#9B59B6")
        bookmark_body_fallback = QColor.fromHsv(
            self._accent_color.hue(), int(self._accent_color.saturation() * 0.35),
            self._accent_color.value(), self._accent_color.alpha())
        self._tassel_body_color = QColor(theme.get("bookmark_body", bookmark_body_fallback))
        self._tassel_icon_color = QColor(theme.get("bookmark_icon", theme.get("accent_dark", theme.get("bg_main", "#000000"))))
        # tassel_fringe falls back to accent_light; cord/head fall back to
        # tassel_fringe (so setting only tassel_fringe recolors the whole tassel).
        fringe_color = QColor(theme.get("tassel_fringe", accent_light))
        self._tassel_cord_color = QColor(theme.get("tassel_cord", fringe_color))
        head_fallback = TasselOverlay.derive_head_fallback(
            self._accent_color, self._head_value_scale, self._head_hue_delta)
        self._tassel_head_color = QColor(theme.get("tassel_head", head_fallback))
        self._tassel_fringe_color = fringe_color
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
            self._tassel.set_colors(self._tassel_body_color)
            self._tassel.set_tassel_colors(
                self._tassel_cord_color, self._tassel_head_color, self._tassel_fringe_color)
            self._update_tassel_icon()
        if hasattr(self, 'tabs') and hasattr(self, '_settings_svg_path'):
            self.tabs.setTabIcon(5, self._make_settings_icon(theme))
        # Re-render placeholder pixmaps on all existing rows so the color
        # updates immediately without requiring a full tab rebuild.
        if not hasattr(self, '_finished_scroll_row'):
            return
        color = self._placeholder_color
        # Scroll-edge arrow overlay: accent_dark, per the user's explicit
        # choice — tried deriving from bg_main luminance (and before that, a
        # flat black/white pick by background lightness) but both were
        # rejected live across themes (too smudgy, too harsh, or unrelated
        # to the panel's own palette). accent_dark is a real theme color,
        # not a derived guess, and is generally dark enough for white text.
        accent_dark_color = QColor(theme.get("accent_dark", theme.get("accent", "#1a1a1a")))
        arrow_overlay_rgb = (accent_dark_color.red(), accent_dark_color.green(), accent_dark_color.blue())
        arrow_text_rgb = (255, 255, 255)
        for attr in ('_finished_scroll_row', '_day_finished_scroll',
                     '_week_finished_scroll', '_month_finished_scroll'):
            scroll_row = getattr(self, attr, None)
            if scroll_row is not None:
                scroll_row.set_arrow_colors(arrow_overlay_rgb, arrow_text_rgb)
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

        tassel_header = QLabel("Show tassel")
        tassel_header.setObjectName("settings_header")
        layout.addWidget(tassel_header)

        tassel_row = QHBoxLayout()
        self._show_tassel_buttons = {}
        for state in ["On", "Off"]:
            btn = QPushButton(state)
            btn.setObjectName("pattern_button")
            btn.clicked.connect(lambda _, s=state: self._set_show_tassel(s == "On"))
            tassel_row.addWidget(btn)
            self._show_tassel_buttons[state] = btn
        tassel_row.addStretch()
        layout.addLayout(tassel_row)
        self._update_show_tassel_buttons()

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

    def _set_show_tassel(self, enabled: bool):
        self.config.set_show_tassel(enabled)
        self._update_show_tassel_buttons()
        if hasattr(self, '_tassel'):
            self._tassel.set_show_tassel(enabled)

    def _update_show_tassel_buttons(self):
        enabled = self.config.get_show_tassel()
        for state, btn in self._show_tassel_buttons.items():
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
        self._tassel.set_colors(self._tassel_body_color)
        self._tassel.set_tassel_colors(
            self._tassel_cord_color, self._tassel_head_color, self._tassel_fringe_color)
        self._tassel.move(2, TasselOverlay.REST_Y)
        self._update_tassel_icon()
        self._tassel.clicked.connect(self._on_tassel_clicked)
        self._tassel.raise_()
        self._tassel.set_show_tassel(self.config.get_show_tassel())
        return widget

    def _update_tassel_icon(self):
        # Showing streak -> clock icon (click goes to heatmap);
        # showing heatmap -> calendar icon (click goes to streak).
        name = "clock.svg" if self._show_streak_grid else "fire.svg"
        self._tassel.set_icon(load_currentcolor_icon(name, self._tassel_icon_color.name(), 14))

    def _on_tassel_clicked(self):
        # Ignore repeat clicks until the bookmark is fully back at rest —
        # without this, _switch_timeline_view() fired on every click regardless
        # of whether the bookmark animation itself was busy (play() no-ops on
        # repeat but this caller didn't check), so rapid clicking queued up
        # multiple overlapping conceal/reveal cycles racing over the same grid
        # visibility state and could hang the view indefinitely.
        if self._tassel.is_busy:
            return
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
            self._refresh_time(streak_mode="full")   # populates the incoming grid
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
        # Always-on policy reserves a constant-width gutter regardless of row
        # count -- see _fixup_scroll_policy, which only toggles the handle's
        # visibility/usability, never the policy, so viewport width (and every
        # row's right-aligned content) never shifts between refreshes.
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self._day_scroll = scroll

        self._day_rows_widget = QWidget()
        self._day_rows_layout = QVBoxLayout(self._day_rows_widget)
        self._day_rows_layout.setContentsMargins(0, 2, 0, 0)
        self._day_rows_layout.setSpacing(0)
        self._day_rows_layout.addStretch()

        scroll.setWidget(self._day_rows_widget)

        def _day_rows_wheel(e):
            bar = scroll.verticalScrollBar()
            notches = -1 if e.angleDelta().y() > 0 else 1
            target = bar.value() + notches * _STATS_ROW_HEIGHT
            snapped = round(target / _STATS_ROW_HEIGHT) * _STATS_ROW_HEIGHT
            max_aligned = (bar.maximum() // _STATS_ROW_HEIGHT) * _STATS_ROW_HEIGHT
            bar.setValue(max(bar.minimum(), min(max_aligned, snapped)))
            e.accept()
        scroll.wheelEvent = _day_rows_wheel

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
        QTimer.singleShot(0, lambda: _fixup_scroll_policy(self._day_scroll))

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
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self._week_scroll = scroll

        self._week_rows_widget = QWidget()
        self._week_rows_layout = QVBoxLayout(self._week_rows_widget)
        self._week_rows_layout.setContentsMargins(0, 2, 0, 0)
        self._week_rows_layout.setSpacing(0)
        self._week_rows_layout.addStretch()

        scroll.setWidget(self._week_rows_widget)

        def _week_rows_wheel(e):
            bar = scroll.verticalScrollBar()
            notches = -1 if e.angleDelta().y() > 0 else 1
            target = bar.value() + notches * _STATS_ROW_HEIGHT
            snapped = round(target / _STATS_ROW_HEIGHT) * _STATS_ROW_HEIGHT
            max_aligned = (bar.maximum() // _STATS_ROW_HEIGHT) * _STATS_ROW_HEIGHT
            bar.setValue(max(bar.minimum(), min(max_aligned, snapped)))
            e.accept()
        scroll.wheelEvent = _week_rows_wheel

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
        QTimer.singleShot(0, lambda: _fixup_scroll_policy(self._week_scroll))

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
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self._month_scroll = scroll

        self._month_rows_widget = QWidget()
        self._month_rows_layout = QVBoxLayout(self._month_rows_widget)
        self._month_rows_layout.setContentsMargins(0, 2, 0, 0)
        self._month_rows_layout.setSpacing(0)
        self._month_rows_layout.addStretch()

        scroll.setWidget(self._month_rows_widget)

        def _month_rows_wheel(e):
            bar = scroll.verticalScrollBar()
            notches = -1 if e.angleDelta().y() > 0 else 1
            target = bar.value() + notches * _STATS_ROW_HEIGHT
            snapped = round(target / _STATS_ROW_HEIGHT) * _STATS_ROW_HEIGHT
            max_aligned = (bar.maximum() // _STATS_ROW_HEIGHT) * _STATS_ROW_HEIGHT
            bar.setValue(max(bar.minimum(), min(max_aligned, snapped)))
            e.accept()
        scroll.wheelEvent = _month_rows_wheel

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
        QTimer.singleShot(0, lambda: _fixup_scroll_policy(self._month_scroll))

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
            QTimer.singleShot(0, lambda: self._refresh_time(streak_mode="full"))
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

    def _refresh_time(self, streak_mode: str = "none"):
        """streak_mode:
        "full"     - the grid cells/labels are also animating (tab click,
                     view-switch seam). Full 0->previous->[pause]->current
                     count-up.
        "catch_up" - plain panel slide-reopen, Timeline already the active
                     tab (so _on_tab_changed never fires this session). Grid
                     cells/labels stay static per the no-animate-on-reopen
                     rule, but the streak number alone still needs to call
                     out an increment that happened while the panel was
                     closed: snaps to previous, pauses, ticks to current.
        "none"     - plain panel slide-reopen onto a tab other than Timeline,
                     or any other refresh with no streak transition to show.
                     set_data() snaps the number straight to current."""
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
            if streak_mode in ("full", "catch_up"):
                # Persisted across app restarts — see Config.get/set_last_shown_streak.
                # Written immediately after the call: both animate_streak_count() and
                # catch_up_streak_count() read it synchronously before any animation
                # actually plays, so persisting now (not after the animation finishes)
                # correctly marks "shown" for next time regardless of session length.
                prev_shown = self.config.get_last_shown_streak()
                if streak_mode == "full":
                    self._streak_grid.animate_streak_count(previous=prev_shown)
                else:
                    self._streak_grid.catch_up_streak_count(prev_shown)
                self.config.set_last_shown_streak(int(streak.get('current', 0)))
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
            # Panel slide-reopen with Timeline already active: currentChanged
            # never fires (the tab index didn't change), so this is the only
            # refresh — grid cells/labels stay static (no animate_reveal /
            # animate_labels_in call here), but the streak number still needs
            # to call out any increment that happened while the panel was
            # closed. See _refresh_time's streak_mode docstring.
            self._refresh_time(streak_mode="catch_up")

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