import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QLineEdit, QGridLayout, QSizePolicy
)
from PySide6.QtCore import Qt, Signal, QTimer, QThreadPool
from PySide6.QtGui import QPixmap, QImage, QColor
from .cover_loader import CoverLoaderWorker
from .library import _cover_cache


class _TagBookThumb(QWidget):
    remove_requested = Signal(str)  # book_path

    def __init__(self, book: dict, assets_dir: str, parent=None):
        super().__init__(parent)
        self._path = book['path']
        self._removed = False
        self.setFixedSize(80, 80)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(book.get('title', ''))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._cover = QLabel()
        self._cover.setFixedSize(80, 80)
        self._cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cover.setScaledContents(False)

        placeholder = QPixmap()
        placeholder.load(os.path.join(assets_dir, 'fabulor.ico'))
        if not placeholder.isNull():
            self._cover.setPixmap(placeholder.scaled(
                80, 80, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            ))

        self._assets_dir = assets_dir
        cover_path = book.get('cover_path')
        if cover_path and os.path.exists(cover_path):
            if cover_path in _cover_cache:
                self._apply_cover(_cover_cache[cover_path])
            else:
                worker = CoverLoaderWorker(
                    type('_TT', (), {'path': cover_path, 'cover_path': cover_path})(),
                    None,
                )
                worker.signals.cover_loaded.connect(
                    self._on_cover_loaded, Qt.ConnectionType.QueuedConnection
                )
                QThreadPool.globalInstance().start(worker)

        layout.addWidget(self._cover)

    def _on_cover_loaded(self, path, image):
        if image.isNull():
            return
        self._apply_cover(QPixmap.fromImage(image))

    def _apply_cover(self, pixmap):
        scaled = pixmap.scaled(
            80, 80,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._cover.setPixmap(scaled)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.remove_requested.emit(self._path)


class _TagBookGrid(QScrollArea):
    """Scrollable grid of book thumbnails for a tag."""

    def __init__(self, assets_dir: str, parent=None):
        super().__init__(parent)
        self._assets_dir = assets_dir
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QScrollArea.Shape.NoFrame)

        self._container = QWidget()
        self._grid = QGridLayout(self._container)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(4)
        self.setWidget(self._container)

        self._books: list[dict] = []
        self._thumbs: dict[str, _TagBookThumb] = {}
        self._cols = 3

    def set_books(self, books: list[dict]):
        self._books = list(books)
        self._rebuild()

    def _rebuild(self):
        # Clear existing
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._thumbs.clear()

        for i, book in enumerate(self._books):
            thumb = _TagBookThumb(book, self._assets_dir)
            thumb.remove_requested.connect(self._on_remove)
            self._grid.addWidget(thumb, i // self._cols, i % self._cols)
            self._thumbs[book['path']] = thumb

        # Update height based on rows
        rows = max(1, (len(self._books) + self._cols - 1) // self._cols)
        cell = 80 + 4
        self.setMinimumHeight(min(rows * cell, 4 * cell))
        self.setMaximumHeight(min(rows * cell, 4 * cell))

    def _on_remove(self, path: str):
        if path in self._thumbs:
            thumb = self._thumbs.pop(path)
            thumb.deleteLater()
            self._books = [b for b in self._books if b['path'] != path]
            # Reflow remaining thumbs
            while self._grid.count():
                item = self._grid.takeAt(0)
                if item.widget():
                    item.widget().hide()
            for i, book in enumerate(self._books):
                if book['path'] in self._thumbs:
                    t = self._thumbs[book['path']]
                    t.show()
                    self._grid.addWidget(t, i // self._cols, i % self._cols)
            rows = max(1, (len(self._books) + self._cols - 1) // self._cols)
            cell = 80 + 4
            h = min(rows * cell, 4 * cell)
            self.setMinimumHeight(h)
            self.setMaximumHeight(h)

        # Signal upward — parent will handle DB removal
        self.parent_remove(path)

    def parent_remove(self, path: str):
        # Overridden by TagManagerWidget
        pass


class TagManagerWidget(QWidget):
    """
    Two-state widget:
      - Tag list: scrollable chips with book count
      - Tag panel: book grid for a selected tag, with inline rename and delete
    """
    tag_changed = Signal()  # emitted when tags are modified (rename, delete, book removed)

    def __init__(self, db, assets_dir: str, parent=None):
        super().__init__(parent)
        self.db = db
        self._assets_dir = assets_dir
        self._current_tag: str | None = None
        self._build_ui()

    def _build_ui(self):
        self._stack_layout = QVBoxLayout(self)
        self._stack_layout.setContentsMargins(0, 0, 0, 0)
        self._stack_layout.setSpacing(0)

        # ── Tag list view ────────────────────────────────────────────────
        self._list_widget = QWidget()
        list_layout = QVBoxLayout(self._list_widget)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(0)

        self._tag_scroll = QScrollArea()
        self._tag_scroll.setWidgetResizable(True)
        self._tag_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._tag_scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        self._tag_list_container = QWidget()
        self._tag_list_layout = QVBoxLayout(self._tag_list_container)
        self._tag_list_layout.setContentsMargins(0, 0, 0, 0)
        self._tag_list_layout.setSpacing(4)
        self._tag_list_layout.addStretch()
        self._tag_scroll.setWidget(self._tag_list_container)
        list_layout.addWidget(self._tag_scroll)
        self._stack_layout.addWidget(self._list_widget)

        # ── Tag panel view ───────────────────────────────────────────────
        self._panel_widget = QWidget()
        self._panel_widget.hide()
        panel_layout = QVBoxLayout(self._panel_widget)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(6)

        # Back + tag name (editable) + delete button
        top_row = QHBoxLayout()
        top_row.setSpacing(6)

        self._back_btn = QPushButton("‹")
        self._back_btn.setObjectName("stats_nav_btn")
        self._back_btn.setFixedWidth(28)
        self._back_btn.clicked.connect(self._show_list)
        top_row.addWidget(self._back_btn)

        self._tag_name_edit = QLineEdit()
        self._tag_name_edit.setObjectName("metadata_field")
        self._tag_name_edit.returnPressed.connect(self._on_rename)
        top_row.addWidget(self._tag_name_edit, stretch=1)

        self._delete_btn = QPushButton("Delete tag")
        self._delete_btn.setObjectName("stats_reset_btn")
        self._delete_btn.clicked.connect(self._on_delete_tag)
        top_row.addWidget(self._delete_btn)

        panel_layout.addLayout(top_row)

        self._rename_status = QLabel("")
        self._rename_status.setObjectName("stats_value_label")
        self._rename_status.setAlignment(Qt.AlignmentFlag.AlignLeft)
        panel_layout.addWidget(self._rename_status)

        self._book_count_label = QLabel("")
        self._book_count_label.setObjectName("stats_key_label")
        panel_layout.addWidget(self._book_count_label)

        self._book_grid = _TagBookGrid(self._assets_dir)
        self._book_grid.parent_remove = self._on_book_removed
        panel_layout.addWidget(self._book_grid)

        self._stack_layout.addWidget(self._panel_widget)

    def refresh(self):
        """Reload tag list from DB."""
        while self._tag_list_layout.count() > 1:
            item = self._tag_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        tags = self.db.get_all_tags()
        for tag_data in tags:
            row = self._make_tag_row(tag_data)
            self._tag_list_layout.insertWidget(self._tag_list_layout.count() - 1, row)

    def _make_tag_row(self, tag_data: dict) -> QWidget:
        row = QWidget()
        row.setObjectName("tag_manager_row")
        row.setAttribute(Qt.WA_StyledBackground, True)
        row.setCursor(Qt.CursorShape.PointingHandCursor)
        hbox = QHBoxLayout(row)
        hbox.setContentsMargins(4, 3, 4, 3)
        hbox.setSpacing(6)

        chip = QLabel(tag_data['tag'])
        chip.setObjectName("tag_chip_label")
        hbox.addWidget(chip)

        count = QLabel(f"{tag_data['count']} book{'s' if tag_data['count'] != 1 else ''}")
        count.setObjectName("stats_key_label")
        hbox.addWidget(count)
        hbox.addStretch()

        row.mousePressEvent = lambda e, t=tag_data['tag']: self._open_tag(t)
        return row

    def _open_tag(self, tag: str):
        self._current_tag = tag
        self._tag_name_edit.setText(tag)
        self._rename_status.setText("")

        books = self.db.get_books_by_tag(tag)
        self._book_count_label.setText(
            f"{len(books)} book{'s' if len(books) != 1 else ''} tagged \"{tag}\""
        )
        self._book_grid.set_books(books)

        self._list_widget.hide()
        self._panel_widget.show()

    def _show_list(self):
        self._panel_widget.hide()
        self._list_widget.show()
        self._current_tag = None
        self.refresh()

    def _on_rename(self):
        if not self._current_tag:
            return
        new_name = self._tag_name_edit.text().strip().lower()
        if new_name == self._current_tag:
            return
        if not new_name:
            return
        success = self.db.rename_tag(self._current_tag, new_name)
        if success:
            self._current_tag = new_name
            books = self.db.get_books_by_tag(new_name)
            self._book_count_label.setText(
                f"{len(books)} book{'s' if len(books) != 1 else ''} tagged \"{new_name}\""
            )
            self._rename_status.setText("Renamed")
            self.tag_changed.emit()
            QTimer.singleShot(1500, lambda: self._rename_status.setText(""))
        else:
            self._rename_status.setText("Name already in use")
            QTimer.singleShot(1500, lambda: self._rename_status.setText(""))

    def _on_delete_tag(self):
        if not self._current_tag:
            return
        from PySide6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self, "Delete tag",
            f"Remove tag \"{self._current_tag}\" from all books? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.db.delete_tag(self._current_tag)
            self.tag_changed.emit()
            self._show_list()

    def _on_book_removed(self, path: str):
        if self._current_tag:
            self.db.remove_book_tag(path, self._current_tag)
            remaining = self.db.get_books_by_tag(self._current_tag)
            if not remaining:
                self.db.delete_tag(self._current_tag)
                self.tag_changed.emit()
                self._show_list()
                return
            tag = self._current_tag
            self._book_count_label.setText(
                f"{len(remaining)} book{'s' if len(remaining) != 1 else ''} tagged \"{tag}\""
            )
            self.tag_changed.emit()
