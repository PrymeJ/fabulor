import os
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTabWidget,
    QPushButton, QScrollArea, QProgressBar, QGridLayout,
    QLineEdit, QCompleter
)
from PySide6.QtCore import Qt, Signal, QStringListModel
from PySide6.QtGui import QPixmap

from .stats_panel import BarChartWidget
from .flow_layout import FlowLayout


class BookDetailPanel(QWidget):
    close_requested = Signal()
    history_deleted = Signal()
    metadata_saved = Signal(str, str, str)  # path, title, author

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

        header = QWidget()
        header.setObjectName("book_detail_header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 10, 10, 10)
        header_layout.setSpacing(12)

        self._cover_label = QLabel()
        self._cover_label.setMaximumSize(120, 120)
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

        self._close_btn = QPushButton("✕")
        self._close_btn.setObjectName("book_detail_close_btn")
        self._close_btn.setFixedSize(15, 15)
        self._close_btn.clicked.connect(self.close_requested.emit)
        header_layout.addWidget(self._close_btn, alignment=Qt.AlignmentFlag.AlignTop)

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

        delete_btn = QPushButton("Delete listening history")
        delete_btn.setObjectName("stats_reset_btn")
        delete_btn.clicked.connect(self._on_delete_book_stats)
        outer.addWidget(delete_btn)

        return widget

    def _build_metadata_tab(self) -> QWidget:
        widget = QWidget()
        outer = QVBoxLayout(widget)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(10)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)

        def make_field(label_text):
            lbl = QLabel(label_text)
            lbl.setObjectName("stats_key_label")
            field = QLineEdit()
            field.setObjectName("metadata_field")
            return lbl, field

        title_lbl, self._meta_title = make_field("Title")
        author_lbl, self._meta_author = make_field("Author")
        narrator_lbl, self._meta_narrator = make_field("Narrator")
        year_lbl, self._meta_year = make_field("Year")

        grid.addWidget(title_lbl,           0, 0)
        grid.addWidget(self._meta_title,    1, 0)
        grid.addWidget(author_lbl,          0, 1)
        grid.addWidget(self._meta_author,   1, 1)
        grid.addWidget(narrator_lbl,        2, 0)
        grid.addWidget(self._meta_narrator, 3, 0)
        grid.addWidget(year_lbl,            2, 1)
        grid.addWidget(self._meta_year,     3, 1)

        outer.addLayout(grid)

        save_btn = QPushButton("Save")
        save_btn.setObjectName("stats_nav_btn")
        save_btn.clicked.connect(self._on_save_metadata)
        outer.addWidget(save_btn)

        tag_header = QLabel("Tags")
        tag_header.setObjectName("stats_key_label")
        outer.addWidget(tag_header)

        self._tag_chip_container = QWidget()
        self._tag_chip_layout = FlowLayout(self._tag_chip_container)
        outer.addWidget(self._tag_chip_container)

        tag_input_row = QHBoxLayout()
        self._tag_input = QLineEdit()
        self._tag_input.setObjectName("metadata_field")
        self._tag_input.setPlaceholderText("Add tag…")
        self._tag_input.setMaxLength(30)
        self._tag_input.returnPressed.connect(self._on_add_tag)

        self._tag_completer_model = QStringListModel()
        completer = QCompleter(self._tag_completer_model, self._tag_input)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        completer.activated.connect(self._on_tag_completer_activated)
        self._tag_input.setCompleter(completer)
        self._tag_input.textChanged.connect(self._on_tag_input_changed)

        add_tag_btn = QPushButton("+")
        add_tag_btn.setObjectName("book_detail_close_btn")
        add_tag_btn.setFixedSize(28, 28)
        add_tag_btn.clicked.connect(self._on_add_tag)

        tag_input_row.addWidget(self._tag_input)
        tag_input_row.addWidget(add_tag_btn)
        outer.addLayout(tag_input_row)

        outer.addStretch()
        return widget

    def _rebuild_tag_chips(self):
        while self._tag_chip_layout.count():
            item = self._tag_chip_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        tags = self.db.get_book_tags(self._book_path)
        for tag in tags:
            chip = QWidget()
            chip.setObjectName("tag_chip")
            row = QHBoxLayout(chip)
            row.setContentsMargins(6, 2, 4, 2)
            row.setSpacing(4)
            lbl = QLabel(tag)
            lbl.setObjectName("tag_chip_label")
            x_btn = QPushButton("✕")
            x_btn.setObjectName("tag_chip_remove_btn")
            x_btn.setFixedSize(16, 16)
            x_btn.clicked.connect(lambda checked, t=tag: self._on_remove_tag(t))
            row.addWidget(lbl)
            row.addWidget(x_btn)
            self._tag_chip_layout.addWidget(chip)

        # Update container height so the outer VBoxLayout knows how much space to allocate.
        row_h = 28
        v_gap = 6
        n = len(tags)
        rows = max(1, n)  # at least one row height so the area is visible
        self._tag_chip_container.setMinimumHeight(rows * row_h + (rows - 1) * v_gap if n else row_h)

    def _on_tag_input_changed(self, text: str):
        text = text.strip()
        if text and self._book_path:
            suggestions = self.db.get_tag_suggestions(text, self._book_path)
            self._tag_completer_model.setStringList(suggestions)
        else:
            self._tag_completer_model.setStringList([])

    def _on_tag_completer_activated(self, text: str):
        self._tag_input.setText(text)
        self._on_add_tag()

    def _on_add_tag(self):
        tag = self._tag_input.text().strip().lower()
        if not tag or not self._book_path:
            return
        added = self.db.add_book_tag(self._book_path, tag)
        if added:
            self._tag_input.clear()
            self._rebuild_tag_chips()
        else:
            self._tag_input.setStyleSheet("border: 1px solid red;")
            from PySide6.QtCore import QTimer
            QTimer.singleShot(800, lambda: self._tag_input.setStyleSheet(""))

    def _on_remove_tag(self, tag: str):
        if self._book_path:
            self.db.remove_book_tag(self._book_path, tag)
            self._rebuild_tag_chips()

    def _on_save_metadata(self):
        if not self._book_path:
            return
        title = self._meta_title.text().strip()
        author = self._meta_author.text().strip()
        narrator = self._meta_narrator.text().strip()
        year = self._meta_year.text().strip()
        if self.db.update_book_metadata(self._book_path, title, author, narrator, year):
            self._book_data.update({
                'title': title, 'author': author,
                'narrator': narrator, 'year': year
            })
            self._sync_header_from_fields()
            self.metadata_saved.emit(self._book_path, title, author)

    def _sync_header_from_fields(self):
        self._title_label.setText(self._book_data.get('title') or self._book_data.get('book_title', ''))
        self._author_label.setText(self._book_data.get('author') or self._book_data.get('book_author', ''))
        narrator = self._book_data.get('narrator', '')
        self._narrator_label.setText(narrator)
        self._narrator_label.setVisible(bool(narrator))
        year = self._book_data.get('year')
        self._year_label.setText(str(year) if year else '')
        self._year_label.setVisible(bool(year))

    def load_book(self, book_data: dict, tab: str = 'stats'):
        self._book_path = book_data.get('path') or book_data.get('book_path')
        self._book_data = book_data
        if 'duration' not in book_data:
            full = self.db.get_book(self._book_path)
            if full:
                self._book_data = {
                    'path': full.path,
                    'title': full.title,
                    'author': full.author,
                    'narrator': full.narrator or '',
                    'year': full.year,
                    'cover_path': full.cover_path,
                    'duration': full.duration,
                }

        pixmap = QPixmap()
        cover_path = self._book_data.get('cover_path')
        if cover_path and os.path.exists(cover_path):
            pixmap.load(cover_path)
        if pixmap.isNull():
            pixmap.load(os.path.join(self._assets_dir, "fabulor.ico"))
        if not pixmap.isNull():
            scaled = pixmap.scaled(
                120, 120,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self._cover_label.setPixmap(scaled)
            self._cover_label.setFixedSize(scaled.width(), scaled.height())

        self._title_label.setText(self._book_data.get('title') or self._book_data.get('book_title', ''))
        self._author_label.setText(self._book_data.get('author') or self._book_data.get('book_author', ''))

        narrator = self._book_data.get('narrator', '')
        self._narrator_label.setText(narrator if narrator else '')
        self._narrator_label.setVisible(bool(narrator))

        year = self._book_data.get('year')
        self._year_label.setText(str(year) if year else '')
        self._year_label.setVisible(bool(year))

        self._meta_title.setText(self._book_data.get('title') or self._book_data.get('book_title', ''))
        self._meta_author.setText(self._book_data.get('author') or self._book_data.get('book_author', ''))
        self._meta_narrator.setText(self._book_data.get('narrator', '') or '')
        self._meta_year.setText(str(self._book_data.get('year')) if self._book_data.get('year') else '')
        self._rebuild_tag_chips()

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
        if not duration:
            book = self.db.get_book(self._book_path)
            if book:
                duration = book.duration

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

    def _on_delete_book_stats(self):
        from PySide6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self, "Delete history",
            f"Delete all listening history for this book? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            if self._book_path:
                self.db.delete_book_stats(self._book_path)
                self._refresh_stats()
                self.history_deleted.emit()

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
