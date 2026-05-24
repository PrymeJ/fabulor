import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QLineEdit, QGridLayout, QSizePolicy
)
from PySide6.QtCore import Qt, Signal, QTimer, QThreadPool, QSize, QByteArray
from PySide6.QtGui import QPixmap, QImage, QColor, QIcon, QPainter
from PySide6.QtSvg import QSvgRenderer
from .cover_loader import CoverLoaderWorker, to_grayscale
from .library import _cover_cache

MAX_TAG_LENGTH = 20


class _ClickableLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


def _load_icon(name: str, color: str, size: int, opacity: float = 1.0) -> QPixmap:
    from pathlib import Path
    icons_dir = Path(__file__).parent.parent / "assets" / "icons"
    with open(icons_dir / name) as f:
        svg = f.read()
    svg = svg.replace('stroke="#000000"', f'stroke="{color}"')
    svg = svg.replace('fill="#000000"', f'fill="{color}"')
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    painter = QPainter(px)
    if opacity < 1.0:
        painter.setOpacity(opacity)
    renderer.render(painter)
    painter.end()
    return px

TAG_COLORS = {
    'coral':      '#E8735A',
    'peach':      '#F0956A',
    'lemon':      "#DEE84A",
    'lime':       '#8FC45A',
    'mint':       '#5AD4A0',
    'sky':        '#5AAEE8',
    'lavender':   '#8A78D8',
    'rose':       '#D865A0',
    'white':      '#F0F0F0',
}


class _TagBookThumb(QWidget):
    remove_requested = Signal(str)  # book_path

    def __init__(self, book: dict, assets_dir: str, parent=None):
        super().__init__(parent)
        self._path = book['path']
        self._is_archived = (book.get('is_deleted', 0) or book.get('is_excluded', 0))
        self.setFixedSize(48, 48)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(book.get('title', ''))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._cover = QLabel()
        self._cover.setFixedSize(48, 48)
        self._cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cover.setScaledContents(False)

        placeholder = QPixmap()
        placeholder.load(os.path.join(assets_dir, 'fabulor.ico'))
        if not placeholder.isNull():
            scaled = placeholder.scaled(48, 48, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            x = (scaled.width() - 48) // 2
            y = (scaled.height() - 48) // 2
            self._cover.setPixmap(scaled.copy(x, y, 48, 48))

        self._assets_dir = assets_dir
        cover_path = book.get('cover_path')
        active_cover_path = book.get('active_cover_path')
        load_path = active_cover_path or cover_path
        if load_path and os.path.exists(load_path):
            book_id = book.get('book_id')
            if _cover_cache.get(book_id):
                self._apply_cover(_cover_cache[book_id])
            else:
                worker = CoverLoaderWorker(
                    type('_TT', (), {'path': book['path'], 'cover_path': cover_path, 'id': book_id})(),
                    active_cover_path=active_cover_path,
                )
                worker.signals.cover_loaded.connect(
                    self._on_cover_loaded, Qt.ConnectionType.QueuedConnection
                )
                QThreadPool.globalInstance().start(worker)

        layout.addWidget(self._cover)

    def _on_cover_loaded(self, book_id, image):
        if image.isNull():
            return
        self._apply_cover(QPixmap.fromImage(image))

    def _apply_cover(self, pixmap):
        if self._is_archived:
            pixmap = to_grayscale(pixmap)
        scaled = pixmap.scaled(48, 48, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
        x = (scaled.width() - 48) // 2
        y = (scaled.height() - 48) // 2
        self._cover.setPixmap(scaled.copy(x, y, 48, 48))

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
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QScrollArea.Shape.NoFrame)

        self._container = QWidget()
        self._container.setStyleSheet("background: transparent;")
        self._grid = QGridLayout(self._container)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(4)
        self.setWidget(self._container)

        self._books: list[dict] = []
        self._thumbs: dict[str, _TagBookThumb] = {}
        self._cols = 5
        self._grid.setColumnStretch(self._cols, 1)

    def set_books(self, books: list[dict]):
        self._books = list(books)
        self._rebuild()

    def _rebuild(self):
        # Clear existing
        for r in range(self._grid.rowCount()):
            self._grid.setRowStretch(r, 0)

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

        # Push content to the top
        self._grid.setRowStretch(self._grid.rowCount(), 1)


    def _on_remove(self, path: str):
        if path in self._thumbs:
            thumb = self._thumbs.pop(path)
            thumb.deleteLater()
            self._books = [b for b in self._books if b['path'] != path]
            self._rebuild()

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
        self.setObjectName("tags_panel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._current_tag: str | None = None
        self._tag_name_original: str = ""
        self._confirming_delete: bool = False
        self._current_theme: dict = {}
        self._build_ui()

    def _inject_active_covers(self, books: list[dict]) -> list[dict]:
        for book in books:
            bp = book.get('path')
            if bp:
                book['active_cover_path'] = self.db.get_active_cover_path(bp)
        return books

    def _build_ui(self):
        self._stack_layout = QVBoxLayout(self)
        self._stack_layout.setContentsMargins(0, 0, 0, 0)
        self._stack_layout.setSpacing(0)

        # ── Tag list view ────────────────────────────────────────────────
        self._list_widget = QWidget()
        self._list_widget.setObjectName("tag_manager_list")
        list_layout = QVBoxLayout(self._list_widget)
        list_layout.setContentsMargins(10, 0, 10, 10)
        list_layout.setSpacing(10)

        header = QLabel("Tag management")
        header.setObjectName("settings_header")
        list_layout.addWidget(header)

        self._tag_scroll = QScrollArea()
        self._tag_scroll.setWidgetResizable(True)
        self._tag_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._tag_scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        self._tag_list_container = QWidget()
        self._tag_list_container.setObjectName("tag_list_container")
        self._tag_list_layout = QVBoxLayout(self._tag_list_container)
        self._tag_list_layout.setContentsMargins(0, 0, 0, 0)
        self._tag_list_layout.setSpacing(4)
        self._tag_list_layout.addStretch()
        self._tag_scroll.setWidget(self._tag_list_container)
        list_layout.addWidget(self._tag_scroll)
        self._stack_layout.addWidget(self._list_widget)

        # ── Tag panel view ───────────────────────────────────────────────
        self._panel_widget = QWidget()
        self._panel_widget.setObjectName("tag_manager_panel")
        self._panel_widget.hide()
        panel_layout = QVBoxLayout(self._panel_widget)
        panel_layout.setContentsMargins(10, 10, 10, 10)
        panel_layout.setSpacing(6)

        self._back_btn = QPushButton("‹")
        self._back_btn.setObjectName("stats_nav_btn")
        self._back_btn.setFixedSize(24, 28)
        self._back_btn.clicked.connect(self._show_list)
        panel_layout.addWidget(self._back_btn)

        name_row = QHBoxLayout()
        name_row.setSpacing(4)

        self._detail_dot = QLabel("●")
        self._detail_dot.setFixedSize(16, 28)
        self._detail_dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._detail_dot.setObjectName("tag_dot_neutral")
        self._detail_dot.setCursor(Qt.CursorShape.PointingHandCursor)
        self._detail_dot.mousePressEvent = lambda e: self._toggle_color_picker()
        name_row.addWidget(self._detail_dot)

        self._tag_name_edit = QLineEdit()
        self._tag_name_edit.setObjectName("tag_name_field")
        self._tag_name_edit.setMaxLength(MAX_TAG_LENGTH)
        self._tag_name_edit.returnPressed.connect(self._on_rename)
        self._tag_name_edit.textChanged.connect(self._on_tag_name_changed)
        name_row.addWidget(self._tag_name_edit, stretch=1)

        self._save_btn = QPushButton()
        self._save_btn.setObjectName("tag_icon_btn")
        self._save_btn.setFixedSize(28, 28)
        self._save_btn.setFlat(True)
        self._save_btn.hide()
        self._save_btn.clicked.connect(self._on_rename)
        name_row.addWidget(self._save_btn)

        self._trash_btn = QPushButton()
        self._trash_btn.setObjectName("tag_icon_btn")
        self._trash_btn.setFixedSize(28, 28)
        self._trash_btn.setFlat(True)
        self._trash_btn.clicked.connect(self._on_delete_tag)
        name_row.addWidget(self._trash_btn)

        panel_layout.addLayout(name_row)

        self._color_picker_row = QWidget()
        self._color_picker_row.hide()
        picker_layout = QHBoxLayout(self._color_picker_row)
        picker_layout.setContentsMargins(10, 4, 10, 4)
        picker_layout.setSpacing(8)

        neutral_dot = QLabel("●")
        neutral_dot.setFixedSize(20, 20)
        neutral_dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        neutral_dot.setObjectName("tag_dot_neutral")
        neutral_dot.setCursor(Qt.CursorShape.PointingHandCursor)
        neutral_dot.mousePressEvent = lambda e: self._set_tag_color(None)
        picker_layout.addWidget(neutral_dot)

        for color_key, color_hex in TAG_COLORS.items():
            dot = QLabel("●")
            dot.setFixedSize(20, 20)
            dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            dot.setStyleSheet(f"color: {color_hex};")
            dot.setCursor(Qt.CursorShape.PointingHandCursor)
            dot.mousePressEvent = lambda e, k=color_key: self._set_tag_color(k)
            picker_layout.addWidget(dot)

        picker_layout.addStretch()
        panel_layout.addWidget(self._color_picker_row)

        self._rename_status = QLabel("")
        self._rename_status.setObjectName("stats_value_label")
        self._rename_status.setAlignment(Qt.AlignmentFlag.AlignLeft)
        panel_layout.addWidget(self._rename_status)

        self._confirm_delete_label = _ClickableLabel("Click to confirm deletion")
        self._confirm_delete_label.setObjectName("tag_confirm_delete")
        self._confirm_delete_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._confirm_delete_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._confirm_delete_label.clicked.connect(self._on_confirm_delete)
        self._confirm_delete_label.setVisible(False)
        panel_layout.addWidget(self._confirm_delete_label)

        self._book_count_label = QLabel("")
        self._book_count_label.setObjectName("book_count_label")
        panel_layout.addWidget(self._book_count_label)

        self._book_grid = _TagBookGrid(self._assets_dir)
        self._book_grid.parent_remove = self._on_book_removed
        panel_layout.addWidget(self._book_grid)

        self._stack_layout.addWidget(self._panel_widget)

    def refresh_books(self) -> None:
        if self._current_tag:
            self._open_tag(self._current_tag)

    def refresh(self):
        """Reload tag list from DB."""
        while self._tag_list_layout.count() > 1:
            item = self._tag_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        tags = self.db.get_all_tags()
        for tag_data in tags:
            row = self._build_tag_row(tag_data)
            self._tag_list_layout.insertWidget(
                self._tag_list_layout.count() - 1, row
            )

        if self._current_tag:
            self._open_tag(self._current_tag)

    def _build_tag_row(self, tag_data: dict) -> QWidget:
        row = QWidget()
        row.setObjectName("tag_list_row")
        row.setAttribute(Qt.WA_StyledBackground, True)
        row.setCursor(Qt.CursorShape.PointingHandCursor)
        row.setFixedHeight(36)

        layout = QHBoxLayout(row)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(2)

        dot = QLabel("●")
        dot.setFixedSize(16, 16)
        dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        color_key = tag_data.get('color')
        color_hex = TAG_COLORS.get(color_key) if color_key else None
        if color_hex:
            dot.setStyleSheet(f"color: {color_hex};")
        else:
            dot.setObjectName("tag_dot_neutral")
        layout.addWidget(dot)

        name = QLabel(tag_data['tag'][:20])
        name.setObjectName("tag_list_name")
        layout.addWidget(name, stretch=1)

        badge = QLabel(str(tag_data['count']))
        badge.setObjectName("tag_count_badge")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedHeight(20)
        badge.setMinimumWidth(24)
        layout.addWidget(badge)

        tag = tag_data['tag']
        row.mousePressEvent = lambda e: self._open_tag(tag) if e.button() == Qt.MouseButton.LeftButton else None
        return row

    def _toggle_color_picker(self):
        visible = self._color_picker_row.isVisible()
        self._color_picker_row.setVisible(not visible)

    def _set_tag_color(self, color_key: str | None):
        if not self._current_tag:
            return
        self.db.set_tag_color(self._current_tag, color_key)
        self._color_picker_row.hide()
        self._update_detail_dot(color_key)
        self.refresh()

    def _update_detail_dot(self, color_key: str | None):
        color_hex = TAG_COLORS.get(color_key) if color_key else None
        if color_hex:
            self._detail_dot.setStyleSheet(f"color: {color_hex};")
            self._detail_dot.setObjectName("")
        else:
            self._detail_dot.setStyleSheet("")
            self._detail_dot.setObjectName("tag_dot_neutral")

    def _open_tag(self, tag: str):
        self._current_tag = tag
        self._tag_name_original = tag
        self._save_btn.hide()
        self._confirming_delete = False
        self._confirm_delete_label.setVisible(False)
        self._tag_name_edit.setText(tag)
        self._rename_status.setText("")
        color_key = self.db.get_tag_color(tag)
        self._update_detail_dot(color_key)

        books = self._inject_active_covers(self.db.get_books_by_tag(tag))
        self._book_count_label.setText(
            f"{len(books)} book{'s' if len(books) != 1 else ''}"
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

    def _on_tag_name_changed(self, text: str):
        if text.strip() != self._tag_name_original:
            self._save_btn.show()
        else:
            self._save_btn.hide()

    def _update_tag_icons(self):
        t_color = self._current_theme.get("accent", "#888888") if self._current_theme else "#888888"
        save_px = _load_icon("save.svg", t_color, 16, 0.7)
        self._save_btn.setIcon(QIcon(save_px))
        self._save_btn.setIconSize(QSize(16, 16))
        trash_px = _load_icon("trash.svg", t_color, 18, 0.7)
        self._trash_btn.setIcon(QIcon(trash_px))
        self._trash_btn.setIconSize(QSize(18, 18))

    def _on_delete_tag(self):
        if not self._current_tag:
            return
        self._confirming_delete = True
        self._confirm_delete_label.setVisible(True)
        QTimer.singleShot(3000, self._cancel_delete_confirm)

    def _on_confirm_delete(self):
        if not self._confirming_delete:
            return
        self._confirming_delete = False
        self._confirm_delete_label.setVisible(False)
        self.db.delete_tag(self._current_tag)
        self.tag_changed.emit()
        self._show_list()

    def _cancel_delete_confirm(self):
        if self._confirming_delete:
            self._confirming_delete = False
            self._confirm_delete_label.setVisible(False)

    def on_theme_changed(self, theme_name: str) -> None:
        from ..themes import get_tags_stylesheet
        self._current_theme_name = theme_name
        self.setStyleSheet(get_tags_stylesheet(theme_name))
        if hasattr(self, '_save_btn'):
            from ..themes import _resolve_theme
            self._current_theme = _resolve_theme(theme_name)
            self._update_tag_icons()

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
