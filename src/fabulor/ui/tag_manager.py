import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QLineEdit, QGridLayout, QSizePolicy, QStackedLayout
)
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, Signal, QTimer, QThreadPool, QSize, QByteArray, QEvent
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
    if '<style' not in svg and 'stroke=' not in svg:
        svg = svg.replace('<svg', f'<svg><style>path {{ fill: {color}; }}</style>', 1)
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
            w = self.parent()
            while w and not isinstance(w, _TagBookGrid):
                w = w.parent()
            if isinstance(w, _TagBookGrid) and w._locked:
                w.parent_remove(self._path)
                return
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
        self._locked: bool = False
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


    def set_locked(self, locked: bool):
        self._locked = locked
        cursor = Qt.CursorShape.ArrowCursor if locked else Qt.CursorShape.PointingHandCursor
        for thumb in self._thumbs.values():
            thumb.setCursor(cursor)

    def _on_remove(self, path: str):
        if self._locked:
            self.parent_remove(path)
            return
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
        self._editing: bool = False
        self._cancel_timer: QTimer | None = None
        self._current_theme: dict = {}
        self._action_btn_mode: str = "delete"
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
        self._tag_list_container.setSizePolicy(
            QSizePolicy.Policy.Preferred, 
            QSizePolicy.Policy.Maximum
        )
        list_layout.addWidget(self._tag_scroll)
        self._stack_layout.addWidget(self._list_widget)

        # ── Tag panel view ───────────────────────────────────────────────
        self._panel_widget = QWidget()
        self._panel_widget.mousePressEvent = lambda e: self._on_panel_bg_click()
        self._panel_widget.setObjectName("tag_manager_panel")
        self._panel_widget.hide()
        panel_layout = QVBoxLayout(self._panel_widget)
        panel_layout.setContentsMargins(10, 10, 10, 0)
        panel_layout.setSpacing(0)

        self._back_btn = QPushButton("‹")
        self._back_btn.setObjectName("stats_nav_btn")
        self._back_btn.setFixedSize(24, 25)
        self._back_btn.clicked.connect(self._show_list)
        panel_layout.addWidget(self._back_btn)
        panel_layout.addSpacing(6)

        name_row = QHBoxLayout()
        name_row.setSpacing(0)

        self._detail_dot = QLabel("●")
        self._detail_dot.setFixedSize(14, 14)
        self._detail_dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._detail_dot.setObjectName("tag_dot_neutral")
        self._detail_dot.setCursor(Qt.CursorShape.PointingHandCursor)
        self._detail_dot.mousePressEvent = lambda e: self._toggle_color_picker()
        name_row.setContentsMargins(4, 0, 0, 0)
        name_row.addWidget(self._detail_dot)

        self._tag_name_edit = QLineEdit()
        self._tag_name_edit.setObjectName("tag_name_field")
        self._tag_name_edit.setMaxLength(MAX_TAG_LENGTH)
        self._tag_name_edit.returnPressed.connect(self._on_rename)
        self._tag_name_edit.textChanged.connect(self._on_tag_name_changed)
        self._tag_name_edit.mousePressEvent = lambda e: (
            self._show_reserved("none") if self._reserved_layout.currentWidget() is self._color_picker_row else None,
            QLineEdit.mousePressEvent(self._tag_name_edit, e)
        )[-1]
        self._tag_name_edit.installEventFilter(self)
        name_row.addWidget(self._tag_name_edit, stretch=1)

        self._action_btn = QPushButton()
        self._action_btn.setObjectName("tag_icon_btn")
        self._action_btn.setFixedSize(28, 28)
        self._action_btn.setFlat(True)
        self._action_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._action_btn.clicked.connect(self._on_action_btn_clicked)
        self._action_btn.installEventFilter(self)
        name_row.addWidget(self._action_btn)

        panel_layout.addLayout(name_row)
        panel_layout.addSpacing(0)

        self._reserved_row = QWidget()
        self._reserved_row.setFixedHeight(21)
        reserved_layout = QStackedLayout(self._reserved_row)
        reserved_layout.setContentsMargins(0, 0, 0, 0)
        reserved_layout.setStackingMode(QStackedLayout.StackingMode.StackOne)

        self._color_picker_row = QWidget()
        picker_layout = QHBoxLayout(self._color_picker_row)
        picker_layout.setContentsMargins(2, 0, 10, 0)
        picker_layout.setSpacing(9)
        neutral_dot = QLabel("●")
        neutral_dot.setFixedSize(20, 20)
        neutral_dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        neutral_dot.setObjectName("tag_dot_neutral")
        neutral_dot.setStyleSheet("font-size: 27px;")
        neutral_dot.setCursor(Qt.CursorShape.PointingHandCursor)
        neutral_dot.mousePressEvent = lambda e: self._set_tag_color(None)
        picker_layout.addWidget(neutral_dot)
        for color_key, color_hex in TAG_COLORS.items():
            dot = QLabel("●")
            dot.setFixedSize(20, 20)
            dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            dot.setStyleSheet(f"font-size: 27px; color: {color_hex};")
            dot.setCursor(Qt.CursorShape.PointingHandCursor)
            dot.mousePressEvent = lambda e, k=color_key: self._set_tag_color(k)
            picker_layout.addWidget(dot)
        picker_layout.addStretch()

        self._confirm_delete_label = _ClickableLabel("Click to delete the tag")
        self._confirm_delete_label.setObjectName("tag_confirm_delete")
        self._confirm_delete_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._confirm_delete_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._confirm_delete_label.clicked.connect(self._on_confirm_delete)

        self._reserved_empty = QWidget()

        reserved_layout.addWidget(self._reserved_empty)
        reserved_layout.addWidget(self._color_picker_row)
        reserved_layout.addWidget(self._confirm_delete_label)
        reserved_layout.setCurrentWidget(self._reserved_empty)

        self._reserved_layout = reserved_layout
        panel_layout.addWidget(self._reserved_row)
        panel_layout.addSpacing(4)

        self._book_count_label = QLabel("")
        self._book_count_label.setObjectName("book_count_label")
        panel_layout.addWidget(self._book_count_label)
        panel_layout.addSpacing(6)

        self._book_grid = _TagBookGrid(self._assets_dir)
        self._book_grid.parent_remove = self._on_grid_remove
        panel_layout.addWidget(self._book_grid)

        self._stack_layout.addWidget(self._panel_widget)

    def hideEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        super().hideEvent(event)

    def refresh_books(self) -> None:
        if self._current_tag:
            self._open_tag(self._current_tag)

    def refresh(self):
        """Reload tag list from DB. Always lands on the list view."""
        self._current_tag = None
        self._panel_widget.hide()
        self._list_widget.show()

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

    def _build_tag_row(self, tag_data: dict) -> QWidget:
        row = QWidget()
        row.setObjectName("tag_list_row")
        row.setAttribute(Qt.WA_StyledBackground, True)
        row.setCursor(Qt.CursorShape.PointingHandCursor)
        row.setFixedHeight(31)

        layout = QHBoxLayout(row)
        layout.setContentsMargins(4, 0, 8, 0)
        layout.setSpacing(1)

        dot = QLabel("●")
        dot.setFixedSize(14, 20)
        dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        color_key = tag_data.get('color')
        color_hex = TAG_COLORS.get(color_key) if color_key else None
        if color_hex:
            dot.setObjectName("tag_dot_colored")
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

    def _show_reserved(self, mode: str):
        if mode == "picker":
            self._reserved_layout.setCurrentWidget(self._color_picker_row)
            if not self._confirming_delete and not self._editing:
                self._book_grid.set_locked(True)
        elif mode == "confirm":
            self._reserved_layout.setCurrentWidget(self._confirm_delete_label)
        else:
            self._reserved_layout.setCurrentWidget(self._reserved_empty)
            if not self._confirming_delete and not self._editing:
                self._book_grid.set_locked(False)

    def _toggle_color_picker(self):
        if self._confirming_delete:
            return
        current = self._reserved_layout.currentWidget()
        if current is self._color_picker_row:
            self._show_reserved("none")
        else:
            self._revert_tag_name()
            self._tag_name_edit.clearFocus()
            self._show_reserved("picker")

    def _set_tag_color(self, color_key: str | None):
        if not self._current_tag:
            return
        self.db.set_tag_color(self._current_tag, color_key)
        self._show_reserved("none")
        self._update_detail_dot(color_key)
        self._update_list_dot(self._current_tag, color_key)
        self.tag_changed.emit()

    def _update_list_dot(self, tag: str, color_key: str | None):
        color_hex = TAG_COLORS.get(color_key) if color_key else None
        for i in range(self._tag_list_layout.count() - 1):
            item = self._tag_list_layout.itemAt(i)
            if item and item.widget():
                row = item.widget()
                dot = row.findChild(QLabel, "tag_dot_neutral") or row.findChild(QLabel, "tag_dot_colored")
                name_lbl = row.findChild(QLabel, "tag_list_name")
                if name_lbl and name_lbl.text() == tag and dot:
                    if color_hex:
                        dot.setObjectName("tag_dot_colored")
                        dot.setStyleSheet(f"color: {color_hex};")
                    else:
                        dot.setObjectName("tag_dot_neutral")
                        dot.setStyleSheet("")
                    dot.style().unpolish(dot)
                    dot.style().polish(dot)
                    break

    def _update_detail_dot(self, color_key: str | None):
        color_hex = TAG_COLORS.get(color_key) if color_key else None
        if color_hex:
            self._detail_dot.setObjectName("tag_dot_colored")
            self._detail_dot.setStyleSheet(f"color: {color_hex};")
        else:
            self._detail_dot.setStyleSheet("")
            self._detail_dot.setObjectName("tag_dot_neutral")
        self._detail_dot.style().unpolish(self._detail_dot)
        self._detail_dot.style().polish(self._detail_dot)

    def _open_tag(self, tag: str):
        self._current_tag = tag
        self._tag_name_original = tag
        self._confirming_delete = False
        self._show_reserved("none")
        if hasattr(self, '_action_btn'):
            self._action_btn.setEnabled(True)
            self._set_action_mode("delete")
        if hasattr(self, '_cancel_timer') and self._cancel_timer:
            self._cancel_timer.stop()
            self._cancel_timer = None
        self._tag_name_edit.setText(tag)
        color_key = self.db.get_tag_color(tag)
        self._update_detail_dot(color_key)

        books = self._inject_active_covers(self.db.get_books_by_tag(tag))
        self._book_count_label.setText(
            f"{len(books)} book{'s' if len(books) != 1 else ''}"
        )
        self._book_grid.set_books(books)

        self._list_widget.hide()
        self._panel_widget.show()
        QApplication.instance().installEventFilter(self)

    def _show_list(self):
        QApplication.instance().removeEventFilter(self)
        self._panel_widget.hide()
        self._list_widget.show()
        self._current_tag = None
        self.refresh()

    def _on_action_btn_hover(self, hover: bool):
        if self._confirming_delete or self._action_btn_mode not in ("delete", "save"):
            return
        color = self._current_theme.get("accent", "#888888")
        if self._action_btn_mode == "delete":
            icon_color = "#cc3333" if hover else color
            px = _load_icon("trash.svg", icon_color, 21, 1.0 if hover else 0.70)
            self._action_btn.setIcon(QIcon(px))
            self._action_btn.setIconSize(QSize(21, 21))
        elif self._action_btn_mode == "save":
            px = _load_icon("save.svg", color, 16, 1.0 if hover else 0.7)
            self._action_btn.setIcon(QIcon(px))
            self._action_btn.setIconSize(QSize(16, 16))

    def eventFilter(self, obj, event):
        if obj is self._action_btn:
            if event.type() == QEvent.Type.Enter:
                self._on_action_btn_hover(True)
            elif event.type() == QEvent.Type.Leave:
                self._on_action_btn_hover(False)
            return False

        if obj is self._tag_name_edit:
            if event.type() == QEvent.Type.FocusIn:
                self._editing = True
                self._book_grid.set_locked(True)
            elif event.type() == QEvent.Type.FocusOut:
                self._editing = False
                if not self._confirming_delete:
                    self._book_grid.set_locked(False)
            return False

        if event.type() == QEvent.Type.MouseButtonPress:
            from PySide6.QtCore import QRect
            gpos = event.globalPosition().toPoint()

            def hits(w):
                return w.isVisible() and QRect(
                    w.mapToGlobal(w.rect().topLeft()),
                    w.mapToGlobal(w.rect().bottomRight())
                ).contains(gpos)

            safe = (self._tag_name_edit, self._action_btn)
            if not any(hits(w) for w in safe):
                self._revert_tag_name()
        return super().eventFilter(obj, event)

    def _revert_tag_name(self):
        if self._tag_name_edit.text().strip() != self._tag_name_original:
            self._tag_name_edit.setText(self._tag_name_original)
            self._set_action_mode("delete")

    def _dismiss_edit(self):
        self._revert_tag_name()
        self._tag_name_edit.clearFocus()

    def _on_panel_bg_click(self):
        if self._confirming_delete:
            self._cancel_delete_confirm()
        elif self._reserved_layout.currentWidget() is self._color_picker_row:
            self._show_reserved("none")
        elif self._editing:
            self._dismiss_edit()

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
            self._tag_name_original = new_name
            books = self.db.get_books_by_tag(new_name)
            self._book_count_label.setText(
                f"{len(books)} book{'s' if len(books) != 1 else ''}"
            )
            self._set_action_mode("check")
            self.tag_changed.emit()
            QTimer.singleShot(2000, lambda: self._set_action_mode("delete"))
        else:
            self._set_action_mode("save_error")

    def _on_tag_name_changed(self, text: str):
        if text.strip() != self._tag_name_original:
            self._set_action_mode("save")
        else:
            self._set_action_mode("delete")

    def _on_action_btn_clicked(self):
        if self._action_btn_mode == "delete":
            self._on_delete_tag()
        elif self._action_btn_mode in ("save", "save_error"):
            self._on_rename()

    def _set_action_mode(self, mode: str):
        self._action_btn_mode = mode
        color = self._current_theme.get("accent", "#888888")
        self._action_btn.setEnabled(mode in ("delete", "save", "save_error", "check"))
        self._action_btn.setCursor(
            Qt.CursorShape.ArrowCursor if mode in ("save_error", "check")
            else Qt.CursorShape.PointingHandCursor
        )
        if mode == "delete":
            px = _load_icon("trash.svg", color, 21, 0.70)
            self._action_btn.setIcon(QIcon(px))
            self._action_btn.setIconSize(QSize(21, 21))
        elif mode == "save":
            px = _load_icon("save.svg", color, 16, 0.7)
            self._action_btn.setIcon(QIcon(px))
            self._action_btn.setIconSize(QSize(16, 16))
        elif mode == "save_error":
            px = _load_icon("save.svg", "#E05050", 16, 0.9)
            self._action_btn.setIcon(QIcon(px))
            self._action_btn.setIconSize(QSize(16, 16))
        elif mode == "check":
            px = _load_icon("check.svg", color, 16, 1.0)
            self._action_btn.setIcon(QIcon(px))
            self._action_btn.setIconSize(QSize(16, 16))

    def _update_tag_icons(self):
        self._set_action_mode(self._action_btn_mode)

    def _on_delete_tag(self):
        if not self._current_tag:
            return
        if self._confirming_delete:
            return
        self._show_reserved("confirm")
        self._book_grid.set_locked(True)
        self._confirming_delete = True
        color = self._current_theme.get("accent", "#888888")
        px = _load_icon("trash.svg", color, 21, 0.35)
        self._action_btn.setIcon(QIcon(px))
        self._action_btn.setCursor(Qt.CursorShape.ArrowCursor)
        self._detail_dot.setCursor(Qt.CursorShape.ArrowCursor)
        self._detail_dot.mousePressEvent = lambda e: self._cancel_delete_confirm()
        self._tag_name_edit.setReadOnly(True)
        self._tag_name_edit.setCursor(Qt.CursorShape.ArrowCursor)
        self._tag_name_edit.mousePressEvent = lambda e: self._cancel_delete_confirm()
        if hasattr(self, '_cancel_timer') and self._cancel_timer:
            self._cancel_timer.stop()
        self._cancel_timer = QTimer()
        self._cancel_timer.setSingleShot(True)
        self._cancel_timer.timeout.connect(self._cancel_delete_confirm)
        self._cancel_timer.start(7000)

    def _on_confirm_delete(self):
        if not self._confirming_delete:
            return
        self._cancel_delete_confirm()
        self.db.delete_tag(self._current_tag)
        self.tag_changed.emit()
        self._show_list()

    def _cancel_delete_confirm(self):
        self._confirming_delete = False
        self._show_reserved("none")
        self._book_grid.set_locked(False)
        self._detail_dot.setCursor(Qt.CursorShape.PointingHandCursor)
        self._detail_dot.mousePressEvent = lambda e: self._toggle_color_picker()
        self._tag_name_edit.setReadOnly(False)
        self._tag_name_edit.setCursor(Qt.CursorShape.IBeamCursor)
        self._tag_name_edit.mousePressEvent = lambda e: (
            self._show_reserved("none") if self._reserved_layout.currentWidget() is self._color_picker_row else None,
            QLineEdit.mousePressEvent(self._tag_name_edit, e)
        )[-1]
        if hasattr(self, '_cancel_timer') and self._cancel_timer:
            self._cancel_timer.stop()
            self._cancel_timer = None
        self._set_action_mode("delete")

    def on_theme_changed(self, theme_name: str) -> None:
        from ..themes import get_tags_stylesheet
        self._current_theme_name = theme_name
        self.setStyleSheet(get_tags_stylesheet(theme_name))
        if hasattr(self, '_action_btn'):
            from ..themes import _resolve_theme
            self._current_theme = _resolve_theme(theme_name)
            self._update_tag_icons()

    def _on_grid_remove(self, path: str):
        if self._confirming_delete:
            self._cancel_delete_confirm()
            return
        if self._editing:
            self._dismiss_edit()
            return
        current = self._reserved_layout.currentWidget()
        if current is self._color_picker_row:
            self._show_reserved("none")
            return
        self._on_book_removed(path)

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
                f"{len(remaining)} book{'s' if len(remaining) != 1 else ''}"
            )
            self.tag_changed.emit()
