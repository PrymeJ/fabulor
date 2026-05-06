import os
import re
from datetime import date
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QLabel,
    QGridLayout, QSpinBox, QScrollArea, QPushButton
)
from PySide6.QtCore import Qt, QRect, Signal, QSize, QPoint, QEvent
from PySide6.QtGui import QPainter, QColor, QFont, QPixmap, QImage, QIcon, QEnterEvent
from PySide6.QtWidgets import QAbstractScrollArea


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

        if max_seconds > 0:
            max_bar_x = bar_gap + max_idx * (bar_w + bar_gap)
            max_label = self._format_seconds(max_seconds)
            painter.setPen(self.palette().text().color())
            font = QFont()
            font.setPointSize(7)
            painter.setFont(font)
            painter.drawText(QRect(max_bar_x - 20, 0, bar_w + 40, y_label_h),
                             Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                             max_label)

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
        m = int((seconds % 3600) // 60)
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
        hbox.setSpacing(8)

        try:
            from datetime import timedelta
            dt_start = datetime.fromisoformat(s['session_start'])
            secs = s.get('listened_seconds') or 0.0
            dt_end = dt_start + timedelta(seconds=secs)
            ts_text = (
                f"{dt_start.strftime('%b')} {dt_start.day}"
                f"  {dt_start.strftime('%H:%M')} – {dt_end.strftime('%H:%M')}"
            )
        except Exception:
            ts_text = s.get('session_start', '—')
            secs = 0.0

        ts_label = QLabel(ts_text)
        ts_label.setObjectName("stats_session_label")
        ts_label.setFixedWidth(110)
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
        delta_label.setFixedWidth(42)
        delta_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        hbox.addWidget(delta_label)

        bar = _RangeBar(pos_start, pos_end, duration, self._accent, self._bg)
        bar.setFixedHeight(6)
        hbox.addWidget(bar, stretch=1)

        pct_label.setObjectName("stats_value_label")
        pct_label.setFixedWidth(36)
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
            x1 = int((self._start / self._duration) * w)
            x2 = int((self._end / self._duration) * w)
            x2 = min(x2, w)
            painter.fillRect(x1, 0, x2 - x1, h, self._accent)

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

    def __init__(self, row_data: dict, assets_dir: str, index: int = 0, parent=None):
        super().__init__(parent)
        self._row_data = row_data
        self.setObjectName("stats_book_day_row_alt" if index % 2 else "stats_book_day_row")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        deleted = row_data.get("book_path") is None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 21, 2)
        layout.setSpacing(6)

        # Cover thumbnail 48x48
        cover_label = QLabel()
        cover_label.setFixedSize(48, 48)
        cover_label.setAlignment(Qt.AlignCenter)
        cover_path = row_data.get("cover_path")
        pixmap = QPixmap()
        if cover_path and os.path.exists(cover_path):
            pixmap.load(cover_path)
        if pixmap.isNull():
            icon_path = os.path.join(assets_dir, "fabulor.ico")
            pixmap.load(icon_path)

        if not pixmap.isNull():
            if deleted:
                # Convert to grayscale
                image = pixmap.toImage()
                gray = image.convertToFormat(QImage.Format.Format_Grayscale8)
                pixmap = QPixmap.fromImage(gray)

            # Scale with KeepAspectRatioByExpanding to fill the 48x48 square
            scaled = pixmap.scaled(
                48, 48,
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation
            )
            cover_label.setPixmap(scaled)

        if deleted:
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
        if deleted:
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

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._row_data)


class FinishedBookThumb(QWidget):
    clicked = Signal(dict)
    def __init__(self, row_data: dict, assets_dir: str, parent=None):
        super().__init__(parent)
        self._row_data = row_data
        self.setFixedSize(47, 47)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        cover_label = QLabel()
        cover_label.setFixedSize(47, 47)
        cover_label.setScaledContents(False)
        cover_path = row_data.get("cover_path")
        pixmap = QPixmap()
        if cover_path and os.path.exists(cover_path):
            pixmap.load(cover_path)
        if pixmap.isNull():
            icon_path = os.path.join(assets_dir, "fabulor.ico")
            pixmap.load(icon_path)

        if not pixmap.isNull():
            # Crop to center square
            side = min(pixmap.width(), pixmap.height())
            x = (pixmap.width() - side) // 2
            y = (pixmap.height() - side) // 2
            cropped = pixmap.copy(x, y, side, side)
            scaled = cropped.scaled(47, 47, Qt.AspectRatioMode.IgnoreAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation)
            cover_label.setPixmap(scaled)

        layout.addWidget(cover_label)

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

    def set_items(self, rows: list[dict], click_callback):
        while self._layout.count() > 0:
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for row in rows:
            thumb = FinishedBookThumb(row, self._assets_dir)
            thumb.clicked.connect(click_callback)
            self._layout.addWidget(thumb)
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

        from PySide6.QtCore import QPropertyAnimation, QEasingCurve
        # Animation for footer label
        self._fade_anim = QPropertyAnimation(self, b"footer_alpha")
        self._fade_anim.setDuration(180)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)

        # Animation for grid reveal wave
        self._reveal_anim = QPropertyAnimation(self, b"reveal_progress")
        self._reveal_anim.setDuration(1000)
        self._reveal_anim.setEasingCurve(QEasingCurve.Type.Linear)

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

    from PySide6.QtCore import Property as _Property
    footer_alpha = _Property(float, get_footer_alpha, set_footer_alpha)
    reveal_progress = _Property(float, get_reveal_progress, set_reveal_progress)

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
        for col_i, date_str in enumerate(self._dates):
            cx = self.HOUR_LABEL_W + col_i * (self.CELL + self.GAP) + self.CELL // 2
            try:
                d = date.fromisoformat(date_str)
                label = d.strftime('%b %d')
            except ValueError:
                label = date_str
            has_data = self._col_totals.get(date_str, 0) > 0
            label_pen = QColor(self._label_color)
            if not has_data:
                label_pen.setAlpha(60)
            painter.save()
            painter.setPen(label_pen)
            painter.translate(cx + 2, self.DATE_LABEL_H - 1)
            painter.rotate(-90)
            painter.drawText(
                QRect(0, -self.CELL // 2, self.DATE_LABEL_H - 2, self.CELL),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                label
            )
            painter.restore()

        # Hour labels on the left — every 3 hours as "00:00"
        for hour in range(0, 24, 3):
            y = self.DATE_LABEL_H + hour * (self.CELL + self.GAP) + 1
            painter.setPen(self._label_color)
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


class StatsPanel(QWidget):
    def __init__(self, db, config, parent=None):
        super().__init__(parent)
        self.db = db
        self.config = config
        self.setObjectName("stats_panel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._accent_color = QColor("#9B59B6")
        self._active_days: list[str] = []
        self._current_day_index: int = 0
        self._active_weeks: list[str] = []
        self._current_week_index: int = 0
        self._active_months: list[str] = []
        self._current_month_index: int = 0
        self._assets_dir: str = os.path.join(os.path.dirname(__file__), "..", "assets")
        self._assets_dir = os.path.normpath(self._assets_dir)
        self._build_ui()

    @staticmethod
    def _format_duration(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
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
        self._accent_color = QColor(theme.get("accent", "#9B59B6"))
        if hasattr(self, '_bar_chart'):
            self._bar_chart.set_accent_color(self._accent_color)
        if hasattr(self, '_heatmap'):
            self._heatmap.set_accent_color(self._accent_color)
        if hasattr(self, 'tabs') and hasattr(self, '_settings_svg_path'):
            self.tabs.setTabIcon(5, self._make_settings_icon(theme))

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
        finished = self.db.get_recently_finished(limit=20)
        self._finished_scroll_row.set_items(finished, self._on_book_row_clicked)
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
        layout.setContentsMargins(10, 10, 10, 10)

        pref_row = QHBoxLayout()
        pref_row.addWidget(QLabel("Day starts at"))
        self.day_start_spin = QSpinBox()
        self.day_start_spin.setRange(0, 23)
        self.day_start_spin.setValue(self.config.get_day_start_hour())
        self.day_start_spin.valueChanged.connect(self.config.set_day_start_hour)
        pref_row.addWidget(self.day_start_spin)
        pref_row.addStretch()
        layout.addLayout(pref_row)

        reset_btn = QPushButton("Reset all stats")
        reset_btn.setObjectName("stats_reset_btn")
        reset_btn.clicked.connect(self._on_reset_stats)
        layout.addWidget(reset_btn)

        layout.addStretch()
        return widget

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
        outer.addStretch()
        return widget

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

        self._day_label = QLabel("—")
        self._day_label.setObjectName("stats_day_label")
        self._day_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._day_next_btn = QPushButton("›")
        self._day_next_btn.setObjectName("stats_nav_btn")
        self._day_next_btn.setFixedWidth(28)
        self._day_next_btn.clicked.connect(self._day_next)

        header_layout.addWidget(self._day_prev_btn)
        header_layout.addWidget(self._day_label, stretch=1)
        header_layout.addWidget(self._day_next_btn)
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

    def _refresh_daily(self):
        self._active_days = self.db.get_active_periods(
            'day', self.config.get_day_start_hour()
        )
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
        rows = [r for r in rows if (r.get("clock_seconds") or 0.0) >= 60]
        for i, row in enumerate(rows):
            total_seconds += row.get("clock_seconds") or 0.0
            book_row = BookDayRow(row, self._assets_dir, index=i)
            book_row.clicked.connect(self._on_book_row_clicked)
            self._day_rows_layout.insertWidget(self._day_rows_layout.count() - 1, book_row)

        self._day_total_label.setText(self._format_duration(total_seconds))

        day_start = self.config.get_day_start_hour()
        finished = self.db.get_finished_in_period('day', date_str, day_start)
        self._day_finished_scroll.set_items(finished, self._on_book_row_clicked)
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

        self._week_label = QLabel("—")
        self._week_label.setObjectName("stats_day_label")
        self._week_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._week_next_btn = QPushButton("›")
        self._week_next_btn.setObjectName("stats_nav_btn")
        self._week_next_btn.setFixedWidth(28)
        self._week_next_btn.clicked.connect(self._week_next)

        header_layout.addWidget(self._week_prev_btn)
        header_layout.addWidget(self._week_label, stretch=1)
        header_layout.addWidget(self._week_next_btn)
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

    def _refresh_weekly(self):
        from datetime import datetime, timedelta
        self._active_weeks = self.db.get_active_periods('week', self.config.get_day_start_hour())
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
        rows = self.db.get_books_listened_in_period('week', week_str, day_start)
        rows = [r for r in rows if (r.get("clock_seconds") or 0.0) >= 60]
        total_seconds = 0.0
        for i, row in enumerate(rows):
            total_seconds += row.get("clock_seconds") or 0.0
            book_row = BookDayRow(row, self._assets_dir, index=i)
            book_row.clicked.connect(self._on_book_row_clicked)
            self._week_rows_layout.insertWidget(self._week_rows_layout.count() - 1, book_row)

        self._week_total_label.setText(self._format_duration(total_seconds))

        finished = self.db.get_finished_in_period('week', week_str, day_start)
        self._week_finished_scroll.set_items(finished, self._on_book_row_clicked)
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

        self._month_label = QLabel("—")
        self._month_label.setObjectName("stats_day_label")
        self._month_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._month_next_btn = QPushButton("›")
        self._month_next_btn.setObjectName("stats_nav_btn")
        self._month_next_btn.setFixedWidth(28)
        self._month_next_btn.clicked.connect(self._month_next)

        header_layout.addWidget(self._month_prev_btn)
        header_layout.addWidget(self._month_label, stretch=1)
        header_layout.addWidget(self._month_next_btn)
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

    def _refresh_monthly(self):
        from datetime import datetime
        self._active_months = self.db.get_active_periods('month', self.config.get_day_start_hour())
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
        rows = self.db.get_books_listened_in_period('month', month_str, day_start)
        rows = [r for r in rows if (r.get("clock_seconds") or 0.0) >= 60]
        total_seconds = 0.0
        for i, row in enumerate(rows):
            total_seconds += row.get("clock_seconds") or 0.0
            book_row = BookDayRow(row, self._assets_dir, index=i)
            book_row.clicked.connect(self._on_book_row_clicked)
            self._month_rows_layout.insertWidget(self._month_rows_layout.count() - 1, book_row)

        self._month_total_label.setText(self._format_duration(total_seconds))

        finished = self.db.get_finished_in_period('month', month_str, day_start)
        self._month_finished_scroll.set_items(finished, self._on_book_row_clicked)
        if finished:
            self._month_finished_section.show()
        else:
            self._month_finished_section.hide()

    def _on_tab_changed(self, index: int):
        if self.tabs.tabText(index) == "Overall":
            self.refresh_overall()
        elif self.tabs.tabText(index) == "Day":
            self._refresh_daily()
        elif self.tabs.tabText(index) == "Week":
            self._refresh_weekly()
        elif self.tabs.tabText(index) == "Month":
            self._refresh_monthly()
        elif self.tabs.tabText(index) == "Timeline":
            self._refresh_time()
            self._heatmap.animate_reveal()

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
        self._active_days = self.db.get_active_periods('day', self.config.get_day_start_hour())
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

    def _on_reset_stats(self):
        from PySide6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self, "Reset stats",
            "Delete all listening history? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.db.reset_stats()
            self.refresh_all()
            bdp = getattr(getattr(self, '_panel_manager', None), 'book_detail_panel', None)
            if bdp and bdp.isVisible():
                bdp._refresh_stats()

    def _refresh_time(self):
        rows = self.db.get_hourly_heatmap(n_days=14)
        self._heatmap.set_data(rows, datetime.now().date())

    def refresh_all(self):
        self.refresh_overall()
        self._refresh_daily()
        self._refresh_weekly()
        self._refresh_monthly()
        self._refresh_time()

    def refresh_current_tab(self):
        name = self.tabs.tabText(self.tabs.currentIndex())
        if name == "Overall":
            self.refresh_overall()
        elif name == "Day":
            self._refresh_daily()
        elif name == "Week":
            self._refresh_weekly()
        elif name == "Month":
            self._refresh_monthly()
        elif name == "Hour":
            self._refresh_time()

    def set_panel_manager(self, panel_manager):
        self._panel_manager = panel_manager

    def _on_book_row_clicked(self, row_data: dict):
        if hasattr(self, '_panel_manager'):
            self._panel_manager.open_book_detail(row_data, tab='stats')