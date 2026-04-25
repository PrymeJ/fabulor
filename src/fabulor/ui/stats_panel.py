import os
from datetime import date
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QLabel,
    QGridLayout, QSpinBox, QScrollArea, QPushButton
)
from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QPainter, QColor, QFont, QPixmap, QImage


class BarChartWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._data = []  # list of {'date': str, 'seconds': float}
        self._accent_color = QColor("#9B59B6")
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

            color = QColor(accent)
            if i == max_idx and day['seconds'] > 0:
                color = color.lighter(130)
            painter.fillRect(x, bar_y, bar_w, bar_h, color)

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

    @staticmethod
    def _format_seconds(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        if h > 0:
            return f"{h}h {m}m"
        return f"{m}m"


def _dim_effect():
    from PySide6.QtWidgets import QGraphicsOpacityEffect
    effect = QGraphicsOpacityEffect()
    effect.setOpacity(0.4)
    return effect


class BookDayRow(QWidget):
    def __init__(self, row_data: dict, assets_dir: str, parent=None):
        super().__init__(parent)
        self.setObjectName("stats_book_day_row")
        deleted = row_data.get("book_path") is None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(8)

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

        # Text block — title, author, progress bar
        text_block = QVBoxLayout()
        text_block.setSpacing(2)

        is_finished = bool(row_data.get("is_finished", 0))

        title_lbl = QLabel(row_data.get("book_title", "Unknown"))
        if deleted:
            title_lbl.setObjectName("stats_book_title_deleted")
        elif is_finished:
            title_lbl.setObjectName("stats_book_title_finished")
        else:
            title_lbl.setObjectName("stats_book_title")
        title_lbl.setFixedWidth(105)
        f_title = title_lbl.font()
        f_title.setPointSize(f_title.pointSize() - 2)
        title_lbl.setFont(f_title)
        title_lbl.setWordWrap(False)

        author_lbl = QLabel(row_data.get("book_author", ""))
        author_lbl.setObjectName("stats_book_author")
        author_lbl.setFixedWidth(90)
        f_author = author_lbl.font()
        f_author.setPointSize(f_author.pointSize() - 2)
        author_lbl.setFont(f_author)

        text_block.addWidget(title_lbl)
        text_block.addWidget(author_lbl)

        layout.addLayout(text_block, stretch=1)

        # Right side — stats (matching rows of the text block)
        time_block = QVBoxLayout()
        time_block.setSpacing(2)
        time_block.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        clock_seconds = row_data.get("clock_seconds") or 0.0
        clock_lbl = QLabel(StatsPanel._format_duration(clock_seconds))
        clock_lbl.setObjectName("stats_time_label")
        clock_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        f_clock = clock_lbl.font()
        f_clock.setPointSize(f_clock.pointSize() - 2)
        clock_lbl.setFont(f_clock)
        time_block.addWidget(clock_lbl)

        book_seconds = row_data.get("book_seconds_advanced") or 0.0
        duration = row_data.get("book_duration")
        furthest = row_data.get("furthest_position") or 0.0

        book_row2 = QHBoxLayout()
        book_row2.setSpacing(4)
        book_row2.setContentsMargins(0, 0, 0, 0)

        book_lbl = QLabel(StatsPanel._format_duration(book_seconds))
        book_lbl.setObjectName("stats_book_time_label")
        book_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        f_book = book_lbl.font()
        f_book.setPointSize(f_book.pointSize() - 2)
        book_lbl.setFont(f_book)
        book_row2.addWidget(book_lbl)

        if duration and duration > 0:
            pct = min(100, int((furthest / duration) * 100))
            sep_lbl = QLabel("·")
            sep_lbl.setObjectName("stats_book_time_label")
            f_sep = sep_lbl.font()
            f_sep.setPointSize(f_sep.pointSize() - 2)
            sep_lbl.setFont(f_sep)
            book_row2.addWidget(sep_lbl)

            pct_lbl = QLabel(f"{pct}%")
            pct_lbl.setObjectName("stats_book_time_label")
            pct_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
            f_pct = pct_lbl.font()
            f_pct.setPointSize(f_pct.pointSize() - 2)
            pct_lbl.setFont(f_pct)
            book_row2.addWidget(pct_lbl)

        time_block.addLayout(book_row2)

        layout.addLayout(time_block)


class FinishedBookThumb(QWidget):
    def __init__(self, row_data: dict, assets_dir: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        cover_label = QLabel()
        cover_label.setFixedSize(48, 48)
        cover_label.setScaledContents(True)
        cover_path = row_data.get("cover_path")
        pixmap = QPixmap()
        if cover_path and os.path.exists(cover_path):
            pixmap.load(cover_path)
        if pixmap.isNull():
            icon_path = os.path.join(assets_dir, "fabulor.ico")
            pixmap.load(icon_path)
        cover_label.setPixmap(pixmap)

        title_lbl = QLabel(row_data.get("book_title", "Unknown"))
        title_lbl.setObjectName("stats_finished_thumb_title")
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        title_lbl.setWordWrap(True)
        title_lbl.setFixedWidth(56)
        font = title_lbl.font()
        font.setPointSize(font.pointSize() - 2)
        title_lbl.setFont(font)

        layout.addWidget(cover_label, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(title_lbl)


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
        outer.setContentsMargins(10, 10, 10, 10)

        grid_container = QWidget()
        grid = QGridLayout(grid_container)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)

        rows = [
            ("Listening time", "—"),
            ("Books started",  "—"),
            ("Sessions",       "—"),
            ("Most listened",  "—"),
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

        self._bar_chart = BarChartWidget()

        outer.addWidget(self._bar_chart)
        outer.addSpacing(16)
        outer.addWidget(grid_container, 0, Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch()
        return widget

    def on_theme_changed(self, theme: dict):
        self._accent_color = QColor(theme.get("accent", "#9B59B6"))
        if hasattr(self, '_bar_chart'):
            self._bar_chart.set_accent_color(self._accent_color)

    def refresh_overall(self):
        day_start = self.config.get_day_start_hour()
        stats = self.db.get_overall_stats(day_start)
        self._overall_value_labels[0].setText(self._format_duration(stats['total_seconds']))
        self._overall_value_labels[1].setText(str(stats['books_started']))
        self._overall_value_labels[2].setText(str(stats['total_sessions']))
        if stats['most_listened_title']:
            duration = self._format_duration(stats['most_listened_seconds'])
            self._overall_value_labels[3].setText(f"{stats['most_listened_title']}  ({duration})")
        else:
            self._overall_value_labels[3].setText("—")
        days = self.db.get_last_n_days(7, day_start)
        self._bar_chart.set_data(days)

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
        layout.addStretch()
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

        # Total time for the day
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
        self._day_rows_layout.setContentsMargins(4, 4, 4, 4)
        self._day_rows_layout.setSpacing(4)
        self._day_rows_layout.addStretch()

        scroll.setWidget(self._day_rows_widget)
        outer.addWidget(scroll, stretch=1)

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
        if not self._active_days:
            self._day_label.setText("No activity yet")
            self._day_total_label.setText("")
            self._day_prev_btn.setEnabled(False)
            self._day_next_btn.setEnabled(False)
            return

        self._current_day_index = min(self._current_day_index, len(self._active_days) - 1)
        date_str = self._active_days[self._current_day_index]

        # Format date label
        d = date.fromisoformat(date_str)
        self._day_label.setText(f"{d.strftime('%A, %B')} {d.day}")

        # Navigation button state
        self._day_prev_btn.setEnabled(self._current_day_index < len(self._active_days) - 1)
        self._day_next_btn.setEnabled(self._current_day_index > 0)
    
        # Fetch and display rows
        rows = self.db.get_daily_book_breakdown(date_str, self.config.get_day_start_hour())

        # Clear existing rows (keep the stretch at the end)
        while self._day_rows_layout.count() > 1:
            item = self._day_rows_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        total_seconds = 0.0
        rows = [r for r in rows if (r.get("clock_seconds") or 0.0) >= 60]
        for row in rows:
            total_seconds += row.get("clock_seconds") or 0.0
            book_row = BookDayRow(row, self._assets_dir)
            self._day_rows_layout.insertWidget(self._day_rows_layout.count() - 1, book_row)

        self._day_total_label.setText(self._format_duration(total_seconds))

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
        self._week_rows_layout.setContentsMargins(4, 4, 4, 4)
        self._week_rows_layout.setSpacing(4)
        self._week_rows_layout.addStretch()

        scroll.setWidget(self._week_rows_widget)
        outer.addWidget(scroll, stretch=1)

        self._week_finished_section = QWidget()
        self._week_finished_section.setObjectName("stats_finished_section")
        finished_outer = QVBoxLayout(self._week_finished_section)
        finished_outer.setContentsMargins(4, 4, 4, 4)
        finished_outer.setSpacing(4)

        finished_header = QLabel("Finished this week")
        finished_header.setObjectName("stats_section_header")
        finished_outer.addWidget(finished_header)

        self._week_finished_row = QHBoxLayout()
        self._week_finished_row.setSpacing(8)
        self._week_finished_row.setAlignment(Qt.AlignmentFlag.AlignLeft)
        finished_outer.addLayout(self._week_finished_row)

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

        while self._week_rows_layout.count() > 1:
            item = self._week_rows_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        total_seconds = 0.0
        for row in rows:
            total_seconds += row.get("clock_seconds") or 0.0
            book_row = BookDayRow(row, self._assets_dir)
            self._week_rows_layout.insertWidget(self._week_rows_layout.count() - 1, book_row)

        self._week_total_label.setText(self._format_duration(total_seconds))

        finished = self.db.get_finished_in_period('week', week_str, day_start)

        while self._week_finished_row.count() > 0:
            item = self._week_finished_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if finished:
            for f in finished:
                thumb = FinishedBookThumb(f, self._assets_dir)
                self._week_finished_row.addWidget(thumb)
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
        self._month_rows_layout.setContentsMargins(4, 4, 4, 4)
        self._month_rows_layout.setSpacing(4)
        self._month_rows_layout.addStretch()

        scroll.setWidget(self._month_rows_widget)
        outer.addWidget(scroll, stretch=1)

        self._month_finished_section = QWidget()
        self._month_finished_section.setObjectName("stats_finished_section")
        finished_outer = QVBoxLayout(self._month_finished_section)
        finished_outer.setContentsMargins(4, 4, 4, 4)
        finished_outer.setSpacing(4)

        finished_header = QLabel("Finished this month")
        finished_header.setObjectName("stats_section_header")
        finished_outer.addWidget(finished_header)

        self._month_finished_row = QHBoxLayout()
        self._month_finished_row.setSpacing(8)
        self._month_finished_row.setAlignment(Qt.AlignmentFlag.AlignLeft)
        finished_outer.addLayout(self._month_finished_row)

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

        while self._month_rows_layout.count() > 1:
            item = self._month_rows_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        total_seconds = 0.0
        for row in rows:
            total_seconds += row.get("clock_seconds") or 0.0
            book_row = BookDayRow(row, self._assets_dir)
            self._month_rows_layout.insertWidget(self._month_rows_layout.count() - 1, book_row)

        self._month_total_label.setText(self._format_duration(total_seconds))

        finished = self.db.get_finished_in_period('month', month_str, day_start)

        while self._month_finished_row.count() > 0:
            item = self._month_finished_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if finished:
            for f in finished:
                thumb = FinishedBookThumb(f, self._assets_dir)
                self._month_finished_row.addWidget(thumb)
            self._month_finished_section.show()
        else:
            self._month_finished_section.hide()

    def _on_tab_changed(self, index: int):
        if self.tabs.tabText(index) == "Overall":
            self.refresh_overall()
        elif self.tabs.tabText(index) == "Daily":
            self._refresh_daily()
        elif self.tabs.tabText(index) == "Weekly":
            self._refresh_weekly()
        elif self.tabs.tabText(index) == "Monthly":
            self._refresh_monthly()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("stats_tabs")

        self.tabs.addTab(self._build_overall_tab(), "Overall")
        self.tabs.addTab(self._build_daily_tab(), "Daily")
        self.tabs.addTab(self._build_weekly_tab(), "Weekly")
        self.tabs.addTab(self._build_monthly_tab(), "Monthly")

        self.tabs.addTab(self._build_options_tab(), "Options")

        self.tabs.currentChanged.connect(self._on_tab_changed)

        layout.addWidget(self.tabs)
        self.refresh_overall()
