import os
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTabWidget,
    QPushButton, QScrollArea, QProgressBar, QGridLayout
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap

from .stats_panel import BarChartWidget


class BookDetailPanel(QWidget):
    close_requested = Signal()

    def __init__(self, db, config, parent=None):
        super().__init__(parent)
        self.db = db
        self.config = config
        self._book_path: str | None = None
        self._book_data: dict = {}
        self.setObjectName("book_detail_panel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._assets_dir = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "assets")
        )
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        title_bar = QWidget()
        title_bar.setObjectName("book_detail_title_bar")
        title_bar_layout = QHBoxLayout(title_bar)
        title_bar_layout.setContentsMargins(8, 6, 8, 6)

        back_btn = QPushButton("‹ Back")
        back_btn.setObjectName("stats_nav_btn")
        back_btn.clicked.connect(self.close_requested.emit)
        title_bar_layout.addWidget(back_btn)
        title_bar_layout.addStretch()

        layout.addWidget(title_bar)

        header = QWidget()
        header.setObjectName("book_detail_header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 10, 10, 10)
        header_layout.setSpacing(12)

        self._cover_label = QLabel()
        self._cover_label.setFixedSize(72, 72)
        self._cover_label.setScaledContents(False)
        header_layout.addWidget(self._cover_label)

        meta_block = QVBoxLayout()
        meta_block.setSpacing(2)

        self._title_label = QLabel()
        self._title_label.setObjectName("book_detail_title")
        self._title_label.setWordWrap(True)

        self._author_label = QLabel()
        self._author_label.setObjectName("book_detail_author")

        self._narrator_label = QLabel()
        self._narrator_label.setObjectName("book_detail_narrator")

        self._year_label = QLabel()
        self._year_label.setObjectName("book_detail_year")

        meta_block.addWidget(self._title_label)
        meta_block.addWidget(self._author_label)
        meta_block.addWidget(self._narrator_label)
        meta_block.addWidget(self._year_label)
        meta_block.addStretch()

        header_layout.addLayout(meta_block, stretch=1)
        layout.addWidget(header)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("stats_tabs")
        self.tabs.addTab(self._build_stats_tab(), "Stats")
        self.tabs.addTab(self._build_metadata_tab(), "Metadata")
        layout.addWidget(self.tabs, stretch=1)

    def _build_stats_tab(self) -> QWidget:
        widget = QWidget()
        outer = QVBoxLayout(widget)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)

        self._furthest_label = QLabel("Furthest position")
        self._furthest_label.setObjectName("stats_key_label")
        outer.addWidget(self._furthest_label)

        self._furthest_bar = QProgressBar()
        self._furthest_bar.setObjectName("stats_progress_bar")
        self._furthest_bar.setRange(0, 100)
        self._furthest_bar.setValue(0)
        self._furthest_bar.setFixedHeight(6)
        self._furthest_bar.setTextVisible(False)
        outer.addWidget(self._furthest_bar)

        self._furthest_pct_label = QLabel("")
        self._furthest_pct_label.setObjectName("stats_value_label")
        outer.addWidget(self._furthest_pct_label)

        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(6)

        stat_rows = [
            ("Total listened", "—"),
            ("Sessions",       "—"),
            ("Started",        "—"),
            ("Finished",       "—"),
        ]

        self._stat_labels = []
        for i, (key, default) in enumerate(stat_rows):
            k = QLabel(key)
            k.setObjectName("stats_key_label")
            v = QLabel(default)
            v.setObjectName("stats_value_label")
            grid.addWidget(k, i, 0, Qt.AlignmentFlag.AlignLeft)
            grid.addWidget(v, i, 1, Qt.AlignmentFlag.AlignLeft)
            self._stat_labels.append(v)

        outer.addWidget(grid_widget)

        chart_header = QLabel("Listening history")
        chart_header.setObjectName("stats_key_label")
        outer.addWidget(chart_header)

        self._book_chart = BarChartWidget()
        outer.addWidget(self._book_chart)

        outer.addStretch()
        return widget

    def _build_metadata_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)
        placeholder = QLabel("Metadata editing coming soon")
        placeholder.setObjectName("stats_placeholder_label")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(placeholder)
        layout.addStretch()
        return widget

    def load_book(self, book_data: dict, tab: str = 'stats'):
        self._book_path = book_data.get('path') or book_data.get('book_path')
        self._book_data = book_data

        pixmap = QPixmap()
        cover_path = book_data.get('cover_path')
        if cover_path and os.path.exists(cover_path):
            pixmap.load(cover_path)
        if pixmap.isNull():
            pixmap.load(os.path.join(self._assets_dir, "fabulor.ico"))
        if not pixmap.isNull():
            side = min(pixmap.width(), pixmap.height())
            x = (pixmap.width() - side) // 2
            y = (pixmap.height() - side) // 2
            cropped = pixmap.copy(x, y, side, side).scaled(
                72, 72,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self._cover_label.setPixmap(cropped)

        self._title_label.setText(book_data.get('title') or book_data.get('book_title', ''))
        self._author_label.setText(book_data.get('author') or book_data.get('book_author', ''))

        narrator = book_data.get('narrator', '')
        self._narrator_label.setText(narrator if narrator else '')
        self._narrator_label.setVisible(bool(narrator))

        year = book_data.get('year')
        self._year_label.setText(str(year) if year else '')
        self._year_label.setVisible(bool(year))

        for i in range(self.tabs.count()):
            if self.tabs.tabText(i).lower() == tab.lower():
                self.tabs.setCurrentIndex(i)
                break

        self._refresh_stats()

    def _refresh_stats(self):
        if not self._book_path:
            return
        day_start = self.config.get_day_start_hour()
        stats = self.db.get_book_stats(self._book_path, day_start)
        duration = self._book_data.get('duration')

        furthest = stats['furthest_position']
        if duration and duration > 0:
            pct = min(100, int((furthest / duration) * 100))
            self._furthest_bar.setValue(pct)
            remaining = max(0, duration - furthest)
            self._furthest_pct_label.setText(
                f"{pct}%  —  {self._fmt(remaining)} remaining"
            )
        else:
            self._furthest_bar.setValue(0)
            self._furthest_pct_label.setText("—")

        self._stat_labels[0].setText(self._fmt(stats['total_seconds']))
        self._stat_labels[1].setText(str(stats['session_count']))

        if stats['first_session']:
            d = datetime.fromisoformat(stats['first_session'])
            self._stat_labels[2].setText(f"{d.strftime('%b')} {d.day}, {d.year}")
        else:
            self._stat_labels[2].setText("—")

        if stats['finished_count'] == 0:
            self._stat_labels[3].setText("—")
        elif stats['finished_count'] == 1:
            d = datetime.fromisoformat(stats['last_finished'])
            self._stat_labels[3].setText(f"{d.strftime('%b')} {d.day}, {d.year}")
        else:
            d = datetime.fromisoformat(stats['last_finished'])
            self._stat_labels[3].setText(
                f"{stats['finished_count']}× — last {d.strftime('%b')} {d.day}, {d.year}"
            )

        self._book_chart.set_data(stats['per_day'])

    def on_theme_changed(self, theme: dict):
        from PySide6.QtGui import QColor
        color = QColor(theme.get('accent', '#9B59B6'))
        self._book_chart.set_accent_color(color)

    @staticmethod
    def _fmt(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        if h > 0:
            return f"{h}h {m}m"
        return f"{m}m"
