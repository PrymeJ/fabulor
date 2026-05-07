import os
from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTabWidget,
    QPushButton, QScrollArea, QGridLayout, QLineEdit, QCompleter
)
from PySide6.QtCore import Qt, Signal, QStringListModel, QTimer, QEvent
from PySide6.QtGui import QPixmap, QPainter, QFontMetrics
from PySide6.QtWidgets import QApplication

from .stats_panel import SessionListWidget, _RangeBar
from .flow_layout import FlowLayout


class _ElidingLineEdit(QLineEdit):
    """QLineEdit that elides text on the right when read-only."""

    def paintEvent(self, event):
        if not self.isReadOnly():
            super().paintEvent(event)
            return

        painter = QPainter(self)
        # 2 is Qt's hardcoded internal horizontal text margin for QLineEdit.
        rect = self.rect().adjusted(3, 0, -2, 0)
        fm = QFontMetrics(self.font())
        elided = fm.elidedText(self.text(), Qt.TextElideMode.ElideRight, rect.width())
        painter.setFont(self.font())
        painter.setPen(self.palette().text().color())
        painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided)
        painter.end()


class _ClickableLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class BookDetailPanel(QWidget):
    close_requested = Signal()
    history_deleted = Signal()
    metadata_saved = Signal(str, str, str)  # path, title, author
    tags_changed = Signal()

    def __init__(self, db, config, parent=None):
        super().__init__(parent)
        self.db = db
        self.config = config
        self._book_path: str | None = None
        self._book_data: dict = {}
        self._theme: dict = {}
        self._duration_show_adjusted: bool = False
        self._editing: bool = False
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
        header_layout.setContentsMargins(10, 10, 10, 4)
        header_layout.setSpacing(12)

        self._cover_label = QLabel()
        self._cover_label.setMaximumSize(120, 120)
        self._cover_label.setScaledContents(False)
        header_layout.addWidget(self._cover_label)

        meta_block = QVBoxLayout()
        meta_block.setSpacing(2)

        def make_field(obj_name, placeholder=''):
            edit = _ElidingLineEdit()
            edit.setObjectName(obj_name)
            edit.setPlaceholderText(placeholder)
            edit.setFrame(False)
            edit.setReadOnly(True)
            edit.textChanged.connect(self._check_dirty)
            edit.returnPressed.connect(self._on_inline_save)
            return edit

        self._title_label    = make_field("book_detail_title")
        self._author_label   = make_field("book_detail_author")
        self._narrator_label = make_field("book_detail_narrator", placeholder="Narrator")
        self._year_label     = make_field("book_detail_year",     placeholder="Year")
        for _f in (self._narrator_label, self._year_label):
            _sp = _f.sizePolicy()
            _sp.setRetainSizeWhenHidden(True)
            _f.setSizePolicy(_sp)

        self._duration_label = _ClickableLabel()
        self._duration_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._duration_label.clicked.connect(self._toggle_duration)
        self._duration_label.setContentsMargins(3, 0, 0, 0)

        self._save_label = _ClickableLabel("Save")
        self._save_label.setObjectName("book_detail_save_label")
        self._save_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._save_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._save_label.clicked.connect(self._on_inline_save)
        self._save_label.setVisible(False)

        dur_save_row = QHBoxLayout()
        dur_save_row.setContentsMargins(0, 0, 0, 0)
        dur_save_row.setSpacing(0)
        dur_save_row.addWidget(self._duration_label)
        dur_save_row.addStretch()
        dur_save_row.addWidget(self._save_label)

        meta_block.addWidget(self._title_label)
        meta_block.addWidget(self._author_label)
        meta_block.addWidget(self._narrator_label)
        meta_block.addWidget(self._year_label)
        meta_block.addLayout(dur_save_row)
        meta_block.addStretch()

        # Make fields clickable to enter edit mode
        for field in (self._title_label, self._author_label,
                      self._narrator_label, self._year_label):
            field.mousePressEvent = lambda e, f=field: self._on_field_click(e, f)

        header_layout.addLayout(meta_block, stretch=1)

        # Right column: close button + save label below it
        right_col = QVBoxLayout()
        right_col.setSpacing(4)
        right_col.setContentsMargins(0, 0, 0, 0)

        self._close_btn = QPushButton("✕")
        self._close_btn.setObjectName("book_detail_close_btn")
        self._close_btn.setFixedSize(15, 15)
        self._close_btn.clicked.connect(self._on_close_clicked)
        right_col.addWidget(self._close_btn, alignment=Qt.AlignmentFlag.AlignRight)

        right_col.addStretch()
        header_layout.addLayout(right_col)

        layout.addWidget(header)

        self._tag_display_label = QLabel()
        self._tag_display_label.setObjectName("tag_display_chip")
        self._tag_display_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._tag_display_label.setWordWrap(True)
        self._tag_display_label.setContentsMargins(8, 2, 8, 2)
        self._tag_display_label.hide()
        layout.addWidget(self._tag_display_label)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("stats_tabs")
        self.tabs.addTab(self._build_stats_tab(), "Stats")
        self.tabs.addTab(self._build_history_tab(), "History")
        self.tabs.addTab(self._build_metadata_tab(), "Tags")
        self.tabs.addTab(QWidget(), "Cover")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tabs, stretch=1)

        QApplication.instance().installEventFilter(self)

    def _build_stats_tab(self) -> QWidget:
        widget = QWidget()
        outer = QVBoxLayout(widget)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)

        from PySide6.QtGui import QColor
        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(6)

        # Row 0: Furthest position | [bar stretches col 1] | pct
        fp_key = QLabel("Furthest position")
        fp_key.setObjectName("stats_key_label")
        self._furthest_pct_label = QLabel("")
        self._furthest_pct_label.setObjectName("stats_value_label")

        fp_bar_row = QHBoxLayout()
        fp_bar_row.setContentsMargins(0, 0, 0, 0)
        fp_bar_row.setSpacing(0)
        self._furthest_bar = _RangeBar(0, 0, 1, QColor("#888"), QColor("#333"))
        self._furthest_bar.setFixedHeight(6)
        fp_bar_row.addWidget(self._furthest_bar)
        fp_bar_container = QWidget()
        fp_bar_container.setLayout(fp_bar_row)

        grid.addWidget(fp_key,               0, 0, Qt.AlignmentFlag.AlignLeft)
        grid.addWidget(fp_bar_container,     0, 1)
        grid.addWidget(self._furthest_pct_label, 0, 2, Qt.AlignmentFlag.AlignLeft)

        stat_rows = [
            ("Remaining",      "—"),
            ("Total listened", "—"),
            ("Sessions",       "—"),
            ("Last session",   "—"),
            ("Started",        "—"),
            ("Finished",       "—"),
        ]

        self._stat_labels = []
        for i, (key, default) in enumerate(stat_rows):
            k = QLabel(key)
            k.setObjectName("stats_key_label")
            v = QLabel(default)
            v.setObjectName("stats_value_label")
            grid.addWidget(k, i + 1, 0, Qt.AlignmentFlag.AlignLeft)
            grid.addWidget(v, i + 1, 1, 1, 2, Qt.AlignmentFlag.AlignLeft)
            self._stat_labels.append(v)

        grid.setColumnStretch(1, 1)
        outer.addWidget(grid_widget)

        self._history_header = QLabel("Recent history")
        self._history_header.setObjectName("stats_history_header")
        outer.addWidget(self._history_header)

        self._session_list = SessionListWidget()
        outer.addWidget(self._session_list)

        outer.addStretch()
        return widget

    def _build_history_tab(self) -> QWidget:
        widget = QWidget()
        outer = QVBoxLayout(widget)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)

        self._history_session_list = SessionListWidget()
        outer.addWidget(self._history_session_list)

        outer.addStretch()

        self._delete_history_btn = QPushButton("Delete listening history")
        self._delete_history_btn.setObjectName("stats_reset_btn")
        self._delete_history_btn.clicked.connect(self._on_delete_book_stats)
        outer.addWidget(self._delete_history_btn)

        return widget

    def _build_metadata_tab(self) -> QWidget:
        widget = QWidget()
        outer = QVBoxLayout(widget)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)


        self._tag_chip_container = QWidget()
        self._tag_chip_layout = FlowLayout(self._tag_chip_container, h_spacing=8, v_spacing=8)
        self._tag_chip_layout.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._tag_chip_container)

        self._tag_input_widget = QWidget()
        tag_input_row = QHBoxLayout(self._tag_input_widget)
        tag_input_row.setContentsMargins(0, 0, 0, 0)
        tag_input_row.setSpacing(6)
        self._tag_input = QLineEdit()
        self._tag_input.setObjectName("tag_add_field")
        self._tag_input.setPlaceholderText("Add tag…")
        self._tag_input.setMaxLength(25)
        self._tag_input.returnPressed.connect(self._on_add_tag)

        self._tag_completer_model = QStringListModel()
        completer = QCompleter(self._tag_completer_model, self._tag_input)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        completer.activated.connect(self._on_tag_completer_activated)
        self._tag_input.setCompleter(completer)
        self._tag_input.textChanged.connect(self._on_tag_input_changed)

        add_tag_btn = QPushButton("+")
        add_tag_btn.setObjectName("tag_add_btn")
        add_tag_btn.setFixedSize(32, 32)
        add_tag_btn.clicked.connect(self._on_add_tag)

        tag_input_row.addWidget(self._tag_input)
        tag_input_row.addWidget(add_tag_btn)
        outer.addWidget(self._tag_input_widget)

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
            chip.setAttribute(Qt.WA_StyledBackground, True)
            row = QHBoxLayout(chip)
            row.setContentsMargins(10, 5, 7, 5)
            row.setSpacing(6)
            lbl = QLabel(tag)
            lbl.setObjectName("tag_chip_label")
            x_btn = QPushButton("✕")
            x_btn.setObjectName("tag_chip_remove_btn")
            x_btn.setFixedSize(18, 18)
            x_btn.clicked.connect(lambda checked, t=tag: self._on_remove_tag(t))
            row.addWidget(lbl)
            row.addWidget(x_btn)
            self._tag_chip_layout.addWidget(chip)

        self._tag_input_widget.setVisible(len(tags) < 5)

        # Worst-case height: every chip on its own row (long tags).
        # FlowLayout will use less space if chips fit side by side.
        row_h = 36
        v_gap = 8
        n = len(tags)
        self._tag_chip_container.setMinimumHeight(
            n * row_h + max(0, n - 1) * v_gap if n else 0
        )

        self._rebuild_tag_display(tags)

    def _rebuild_tag_display(self, tags: list[str]):
        if not tags:
            self._tag_display_label.hide()
            return
        self._tag_display_label.setText("  ".join(f"● {t}" for t in tags))
        self._tag_display_label.show()

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
            self.tags_changed.emit()
        else:
            self._tag_input.setStyleSheet("border: 1px solid red;")
            from PySide6.QtCore import QTimer
            QTimer.singleShot(800, lambda: self._tag_input.setStyleSheet(""))

    def _on_remove_tag(self, tag: str):
        if self._book_path:
            self.db.remove_book_tag(self._book_path, tag)
            self._rebuild_tag_chips()
            self.tags_changed.emit()

    def _sync_header_from_fields(self):
        self._title_label.setText(self._book_data.get('title') or self._book_data.get('book_title', ''))
        self._author_label.setText(self._book_data.get('author') or self._book_data.get('book_author', ''))
        narrator = self._book_data.get('narrator', '')
        self._narrator_label.setText(narrator)
        year = self._book_data.get('year')
        self._year_label.setText(str(year) if year else '')
        if not self._editing:
            self._narrator_label.setVisible(bool(narrator))
            self._year_label.setVisible(bool(year))
            for field in (self._title_label, self._author_label,
                          self._narrator_label, self._year_label):
                field.setCursorPosition(0)

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

        self._editing = False
        self._exit_edit_mode(save=False)
        self._sync_header_from_fields()

        self._duration_show_adjusted = False
        self._update_duration_label()

        self._rebuild_tag_chips()

        for i in range(self.tabs.count()):
            if self.tabs.tabText(i).lower() == tab.lower():
                self.tabs.setCurrentIndex(i)
                break

        self._refresh_stats()

    def _update_duration_label(self):
        duration = self._book_data.get('duration') or 0.0
        if not duration:
            self._duration_label.setVisible(False)
            return
        speed = self.config.get_book_speed(self._book_path) or 1.0
        if self._duration_show_adjusted and speed != 1.0:
            text = f"{self._fmt(duration / speed)} at {speed:g}x"
        else:
            text = self._fmt(duration)
        self._duration_label.setText(text)
        self._duration_label.setVisible(True)

    def _toggle_duration(self):
        duration = self._book_data.get('duration') or 0.0
        speed = self.config.get_book_speed(self._book_path) or 1.0
        if not duration or speed == 1.0:
            return
        self._duration_show_adjusted = not self._duration_show_adjusted
        self._update_duration_label()

    def eventFilter(self, obj, event):
        if self._editing and event.type() == QEvent.Type.MouseButtonPress:
            from PySide6.QtCore import QRect
            gpos = event.globalPosition().toPoint()

            def hits(w):
                return w.isVisible() and QRect(
                    w.mapToGlobal(w.rect().topLeft()),
                    w.mapToGlobal(w.rect().bottomRight())
                ).contains(gpos)

            safe = (self._title_label, self._author_label,
                    self._narrator_label, self._year_label, self._save_label,
                    self._close_btn)
            if not any(hits(w) for w in safe):
                self._exit_edit_mode(save=False)
        return super().eventFilter(obj, event)

    def _on_tab_changed(self):
        if self._editing:
            self._exit_edit_mode(save=False)

    def _on_field_click(self, event, field):
        QLineEdit.mousePressEvent(field, event)
        self._enter_edit_mode()

    def _enter_edit_mode(self):
        if self._editing:
            return
        self._editing = True
        self._orig_title    = self._title_label.text()
        self._orig_author   = self._author_label.text()
        self._orig_narrator = self._narrator_label.text()
        self._orig_year     = self._year_label.text()
        self._narrator_label.setVisible(True)
        self._year_label.setVisible(True)
        for field in (self._title_label, self._author_label,
                      self._narrator_label, self._year_label):
            field.setReadOnly(False)
            field.setCursorPosition(0)
        self._save_label.setVisible(False)
        self._title_label.setFocus()

    def _check_dirty(self):
        if not self._editing:
            return
        dirty = (
            self._title_label.text()    != self._orig_title    or
            self._author_label.text()   != self._orig_author   or
            self._narrator_label.text() != self._orig_narrator or
            self._year_label.text()     != self._orig_year
        )
        if dirty:
            self._save_label.setText("Save")
            self._save_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._save_label.setVisible(dirty)

    def _exit_edit_mode(self, save: bool):
        if not self._editing:
            return
        self._editing = False
        for field in (self._title_label, self._author_label,
                      self._narrator_label, self._year_label):
            field.setReadOnly(True)
        if save:
            self._commit_inline_save()
        else:
            self._sync_header_from_fields()
            self._save_label.setVisible(False)
        narrator = self._book_data.get('narrator', '')
        year = self._book_data.get('year')
        self._narrator_label.setVisible(bool(narrator))
        self._year_label.setVisible(bool(year))

    def _on_inline_save(self):
        self._exit_edit_mode(save=True)

    def _commit_inline_save(self):
        title    = self._title_label.text().strip()
        author   = self._author_label.text().strip()
        narrator = self._narrator_label.text().strip()
        year     = self._year_label.text().strip()
        if self.db.update_book_metadata(self._book_path, title, author, narrator, year):
            self._book_data.update({
                'title': title, 'author': author,
                'narrator': narrator, 'year': year
            })
            self.metadata_saved.emit(self._book_path, title, author)
        self._sync_header_from_fields()
        self._save_label.setText("Saved")
        self._save_label.setCursor(Qt.CursorShape.ArrowCursor)
        self._save_label.setVisible(True)
        QTimer.singleShot(1000, lambda: self._save_label.setVisible(False))

    def _on_close_clicked(self):
        if self._editing:
            self._exit_edit_mode(save=False)
        self.close_requested.emit()

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

        speed = self.config.get_book_speed(self._book_path) or 1.0

        furthest = stats['furthest_position']
        if duration and duration > 0:
            pct = min(100, round((furthest / duration) * 100))
            self._furthest_bar.update_range(0, furthest, duration)
            self._furthest_pct_label.setText(f"{pct}%")
            remaining = max(0, duration - furthest)
            if speed != 1.0:
                self._stat_labels[0].setText(
                    f"{self._fmt(remaining / speed)} at {speed:g}x"
                )
            else:
                self._stat_labels[0].setText(self._fmt(remaining))
        else:
            self._furthest_bar.update_range(0, 0, 1)
            self._furthest_pct_label.setText("—")
            self._stat_labels[0].setText("—")

        self._stat_labels[1].setText(self._fmt(stats['total_seconds']))
        self._stat_labels[2].setText(str(stats['session_count']))

        sessions = self.db.get_book_sessions(self._book_path)

        has_history = bool(sessions)
        self._history_header.setVisible(has_history)
        self._session_list.setVisible(has_history)
        self._delete_history_btn.setVisible(has_history)

        if sessions:
            newest = sessions[0]
            try:
                ld = datetime.fromisoformat(newest['session_start'])
                secs = newest.get('listened_seconds') or 0.0
                self._stat_labels[3].setText(
                    f"{ld.strftime('%b')} {ld.day}  {ld.strftime('%H:%M')}  · {self._fmt(secs)}"
                )
            except Exception:
                self._stat_labels[3].setText("—")
        else:
            self._stat_labels[3].setText("—")

        if stats['first_session']:
            d = datetime.fromisoformat(stats['first_session'])
            self._stat_labels[4].setText(f"{d.strftime('%b')} {d.day}, {d.year}")
        else:
            self._stat_labels[4].setText("—")

        if stats['finished_count'] == 0:
            self._stat_labels[5].setText("—")
        elif stats['finished_count'] == 1:
            d = datetime.fromisoformat(stats['last_finished'])
            self._stat_labels[5].setText(f"{d.strftime('%b')} {d.day}, {d.year}")
        else:
            d = datetime.fromisoformat(stats['last_finished'])
            self._stat_labels[5].setText(
                f"{stats['finished_count']}× — last {d.strftime('%b')} {d.day}, {d.year}"
            )

        self._session_list.set_data(sessions, duration or 0.0)
        self._history_session_list.set_data(sessions, duration or 0.0)
        self._apply_bar_colors()

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

    def _apply_bar_colors(self):
        from PySide6.QtGui import QColor
        accent = QColor(self._theme.get('curr_chap_highlight', '#888888'))
        bg = QColor(self._theme.get('library_slider_bg', '#333333'))
        self._session_list.set_colors(accent, bg)
        self._history_session_list.set_colors(accent, bg)
        self._furthest_bar.set_colors(accent, bg)

    def on_theme_changed(self, theme: dict):
        from PySide6.QtGui import QColor
        self._theme = theme
        self._apply_bar_colors()

    @staticmethod
    def _fmt(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        if h > 0:
            return f"{h}h {m}m"
        return f"{m}m"
