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
from .icon_utils import render_logo_placeholder_bordered as _render_svg_placeholder_bordered
from .text_context_menu import ContextIconMenu
from .line_edit_dragfix import DragSafeLineEdit
from .hover_tracker import ScrollHoverTracker

MAX_TAG_LENGTH = 20

# Tag list row geometry. The viewport has to hold a whole number of rows or the
# list drifts on scroll and shows partial rows at its edges — measured live at
# 450px viewport against a 35px pitch, a 30px remainder
# (tools/tags_geometry_probe.py).
#
# N rows have N-1 gaps between them, NOT N: the last row has no trailing gap.
# So the height is (N * row) + ((N - 1) * spacing), not N * pitch. Getting this
# wrong is what cut the top and bottom rows on the first attempt — 12 * 37 = 444
# counts a 12th gap that does not exist, 5px too tall.
#
# 12 * 32 + 11 * 5 = 439, leaving 11px of the 450px viewport. The row grew by
# 1px rather than shrinking to fit 13 rows because 450 / 13 is not an integer,
# and the nearest exact divisors would need a visibly tighter row. The +1 also
# fixes badge centring: a 20px badge in a 31px row leaves an odd 11px to split,
# in a 32px row an even 12px.
_TAG_ROW_HEIGHT = 32
_TAG_ROW_SPACING = 5
_TAG_ROWS_VISIBLE = 12
# Distance from one row's top to the next's — the correct unit for a SCROLL
# STEP (every row after the first sits one pitch further down). Deliberately
# not used for the viewport's total height, which needs one fewer gap; see
# _tag_list_height.
_TAG_ROW_PITCH = _TAG_ROW_HEIGHT + _TAG_ROW_SPACING  # 37

# Two independent horizontal gaps around the scrollbar. They are NOT
# interchangeable — each moves a different edge:
#
#   [ row ]<-- ROW_SCROLLBAR_GAP -->|bar|<-- SCROLLBAR_EDGE_GAP -->| panel edge
#
# ROW_SCROLLBAR_GAP is the container's right margin: it shrinks the ROW and
# leaves the bar where it is. SCROLLBAR_EDGE_GAP is the list layout's right
# margin: it is the space right OF the bar, and it is what actually moves the
# bar horizontally. Widening the first to push the bar right does not work; that
# was tried.
#
# Without ROW_SCROLLBAR_GAP the row background runs flush into the bar (measured:
# row right edge 252, scrollbar x 252).
_TAG_ROW_SCROLLBAR_GAP = 4
_TAG_SCROLLBAR_EDGE_GAP = 5

# Rows travelled per wheel notch. Half a viewport, deliberately — NOT matched to
# Stats (1 row) or the Library (a full page), because each suits how its list is
# actually read:
#
#   Stats  — dense rows you READ (cover, title, author, percentages, duration).
#            One row per notch keeps the row under your eye while the next
#            arrives; a jump would cost you your place.
#   Tags   — a name, a dot, a count. You SCAN these looking for one, and
#            scanning rewards large jumps.
#   Library— a grid of covers recognised by shape and colour, and it can hold
#            thousands of books, so a page per flick is the only way to traverse.
#
# 12 (a full page) was considered and rejected: it leaves zero overlap, so every
# row is new after a flick and there is no anchor to re-orient against. 6 keeps
# half the list on screen. With tags capped at 50 globally (db.add_book_tag)
# that is ~8 flicks end to end.
_TAG_SCROLL_ROWS = 6


def _tag_list_height(rows: int) -> int:
    """Exact pixel height of `rows` tag rows — N rows, N-1 gaps."""
    if rows <= 0:
        return 0
    return rows * _TAG_ROW_HEIGHT + (rows - 1) * _TAG_ROW_SPACING


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
    remove_requested = Signal(str)   # book_path
    detail_requested = Signal(str)   # book_path

    def __init__(self, book: dict, assets_dir: str, placeholder_color: str = "#888888", parent=None):
        super().__init__(parent)
        self._path = book['path']
        self._is_archived = (book.get('is_deleted', 0) or book.get('is_excluded', 0) or book.get('is_missing', 0))
        self.setFixedSize(47, 47)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(book.get('title', ''))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._cover = QLabel()
        self._cover.setFixedSize(47, 47)
        self._cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cover.setScaledContents(False)

        pm = _render_svg_placeholder_bordered(placeholder_color, 35, 47, 47, offset_y=1)
        self._cover.setPixmap(pm)

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
        scaled = pixmap.scaled(47, 47, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
        x = (scaled.width() - 47) // 2
        y = (scaled.height() - 47) // 2
        self._cover.setPixmap(scaled.copy(x, y, 47, 47))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.detail_requested.emit(self._path)
            return
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

    def __init__(self, assets_dir: str, placeholder_color: str = "#888888", parent=None):
        super().__init__(parent)
        self._assets_dir = assets_dir
        self._placeholder_color = placeholder_color
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QScrollArea.Shape.NoFrame)

        self._container = QWidget()
        self._container.setStyleSheet("background: transparent;")
        self._grid = QGridLayout(self._container)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(3)
        self.setWidget(self._container)

        self._books: list[dict] = []
        self._thumbs: dict[str, _TagBookThumb] = {}
        self._cols = 5
        self._locked: bool = False
        self._grid.setColumnStretch(self._cols, 1)

    def set_placeholder_color(self, color: str):
        if self._placeholder_color != color:
            self._placeholder_color = color
            if self._books:
                self._rebuild()

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
            thumb = _TagBookThumb(book, self._assets_dir, self._placeholder_color)
            thumb.remove_requested.connect(self._on_remove)
            thumb.detail_requested.connect(self.parent_detail)
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
        pass

    def parent_detail(self, path: str):
        pass


class TagManagerWidget(QWidget):
    """
    Two-state widget:
      - Tag list: scrollable chips with book count
      - Tag panel: book grid for a selected tag, with inline rename and delete
    """
    tag_changed = Signal()       # emitted when tags are modified (rename, delete, book removed)
    detail_requested = Signal(str)  # book_path — right-click on thumbnail

    def __init__(self, db, assets_dir: str, parent=None):
        super().__init__(parent)
        self.db = db
        self._assets_dir = assets_dir
        self.setObjectName("tags_panel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._current_tag: str | None = None
        self._tag_name_original: str = ""
        self._confirming_delete: bool = False
        self._cancel_timer: QTimer | None = None
        self._rename_revert_timer: QTimer | None = None
        self._current_theme: dict = {}
        self._action_btn_mode: str = "delete"
        self._placeholder_color_tags: str = "#888888"
        self._build_ui()
        self._ctx_menu = ContextIconMenu(self)
        self._tag_name_edit.customContextMenuRequested.connect(
            lambda pos: self._ctx_menu.show_for(self._tag_name_edit, self._tag_name_edit.mapToGlobal(pos))
        )

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
        # Right margin 4, not 10: this is the space to the RIGHT of the
        # scrollbar (between it and the panel edge), and it is what positions the
        # scrollbar horizontally. Narrowing the row via the container's own right
        # margin does NOT move the bar — it only shrinks the row and leaves the
        # bar where it was. Left stays 10; the asymmetry is deliberate.
        list_layout.setContentsMargins(10, 0, _TAG_SCROLLBAR_EDGE_GAP, 10)
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
        # Right margin only: the rows are as wide as the viewport, so without it
        # a row's background runs flush into the scrollbar. Stats gets the same
        # separation from its row's own right margin; here the rows fill the
        # container, so it belongs on the container. 4px to match Stats.
        self._tag_list_layout.setContentsMargins(0, 0, _TAG_ROW_SCROLLBAR_GAP, 0)
        # 5, not 4 — with the 32px row this gives a 37px pitch, and 12 rows then
        # occupy exactly the viewport (see _tag_list_height).
        self._tag_list_layout.setSpacing(_TAG_ROW_SPACING)
        self._tag_list_layout.addStretch()
        self._tag_scroll.setWidget(self._tag_list_container)
        # Re-resolve the hovered row when the list scrolls under a still cursor —
        # QSS :hover alone goes stale there. See ui/hover_tracker.py.
        self._row_hover = ScrollHoverTracker(
            self._tag_scroll,
            lambda: [self._tag_list_layout.itemAt(i).widget()
                     for i in range(self._tag_list_layout.count())
                     if self._tag_list_layout.itemAt(i).widget() is not None],
            self)
        # Horizontal Ignored, not Preferred: with Preferred the container claims
        # its own sizeHint and came out 245px wide inside a 242px viewport
        # (measured), overhanging by 3px — so a right margin measured from the
        # container's edge landed 3px further right than intended and the rows
        # still nearly touched the scrollbar. Ignored holds it to the viewport
        # width, which is what widgetResizable(True) is for.
        #
        # Vertical stays Maximum — that is what lets the container size to its
        # content height so the scroll range is right.
        self._tag_list_container.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Maximum
        )
        # Exactly 12 rows of content, so the viewport is a whole number of rows
        # and the list cannot come to rest mid-row. Without it the viewport is
        # the full 450px leftover — 12 rows plus a 30px sliver of a 13th, which
        # is what made the rows appear to drift when scrolled.
        self._tag_scroll.setMaximumHeight(_tag_list_height(_TAG_ROWS_VISIBLE))
        # Sizing the viewport to whole rows is only half of it: without a
        # row-sized scroll step the list still comes to rest mid-row, which is
        # the drift symptom itself. Qt's default singleStep has no relationship
        # to the pitch. Snap every wheel notch to a multiple of it and clamp to
        # the last aligned position, mirroring the Stats rows wheelEvent.
        bar = self._tag_scroll.verticalScrollBar()
        bar.setSingleStep(_TAG_ROW_PITCH)

        def _tag_rows_wheel(e):
            notches = -1 if e.angleDelta().y() > 0 else 1
            target = bar.value() + notches * _TAG_ROW_PITCH * _TAG_SCROLL_ROWS
            snapped = round(target / _TAG_ROW_PITCH) * _TAG_ROW_PITCH
            max_aligned = (bar.maximum() // _TAG_ROW_PITCH) * _TAG_ROW_PITCH
            bar.setValue(max(bar.minimum(), min(max_aligned, snapped)))
            e.accept()

        self._tag_scroll.wheelEvent = _tag_rows_wheel
        # stretch=1 so the scroll area claims surplus height BEFORE the trailing
        # stretch does. A bare addStretch() carries a stretch factor of 1 too, so
        # without this the two split the surplus and the viewport settled at
        # 225px — half of what the cap allows (measured, tools/tags_geometry_probe.py).
        list_layout.addWidget(self._tag_scroll, stretch=1)
        # Required PARTNER to the cap above, not decoration. The scroll area was
        # this column's only expanding member, so capping it alone leaves the
        # freed pixels with nowhere to go and QVBoxLayout redistributes them
        # around the block — which would push the header and the first row down
        # and break the dot alignment between this view and the tag panel. The
        # stretch gives that remainder an explicit home at the BOTTOM, keeping
        # the list's top edge exactly where it is today. Same trap, same fix, as
        # the Stats rows viewport (see stats_panel._cap_rows_viewport).
        list_layout.addStretch()
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

        self._tag_name_edit = DragSafeLineEdit()
        self._tag_name_edit.setObjectName("tag_name_field")
        self._tag_name_edit.setMaxLength(MAX_TAG_LENGTH)
        self._tag_name_edit.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tag_name_edit.returnPressed.connect(self._on_rename)
        self._tag_name_edit.textChanged.connect(self._on_tag_name_changed)
        self._tag_name_edit.mousePressEvent = lambda e: (
            self._show_reserved("none") if self._reserved_layout.currentWidget() is self._color_picker_row else None,
            QLineEdit.mousePressEvent(self._tag_name_edit, e)
        )[-1]
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

        self._book_grid = _TagBookGrid(self._assets_dir, self._placeholder_color_tags)
        self._book_grid.parent_remove = self._on_grid_remove
        self._book_grid.parent_detail = lambda path: self.detail_requested.emit(path)
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
        # Puts the row into Qt's hover tracking (underMouse/style machinery) —
        # same reasoning as BookDayRow in stats_panel.py; see the note there,
        # including why this is correctness rather than the arrow-cursor fix.
        row.setAttribute(Qt.WA_Hover, True)
        row.setCursor(Qt.CursorShape.PointingHandCursor)
        # 32, not 31, for two reasons that happen to want the same pixel.
        #
        # Centring: the badge and dot are both 20px tall in a row with zero
        # top/bottom margins. At 31 the leftover is 11px — odd, so it cannot
        # split evenly and the badge sits a pixel off centre. At 32 it is 12,
        # which splits 6/6 exactly.
        #
        # Quantization: 32 + 5px spacing gives a 37px pitch, and 37 * 12 = 444
        # against the 450px viewport — a 6px remainder instead of 35's 30px.
        # See _quantize_tag_viewport.
        row.setFixedHeight(_TAG_ROW_HEIGHT)

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
            if not self._confirming_delete:
                self._book_grid.set_locked(True)
        elif mode == "confirm":
            self._reserved_layout.setCurrentWidget(self._confirm_delete_label)
        else:
            self._reserved_layout.setCurrentWidget(self._reserved_empty)
            if not self._confirming_delete:
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
            px = _load_icon("trash.svg", icon_color, 16, 1.0 if hover else 0.70)
            self._action_btn.setIcon(QIcon(px))
            self._action_btn.setIconSize(QSize(16, 16))
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

        if obj is self._tag_name_edit and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self._revert_tag_name()
                self._tag_name_edit.clearFocus()
                return True

        if event.type() == QEvent.Type.MouseButtonPress:
            from PySide6.QtCore import QRect
            gpos = event.globalPosition().toPoint()

            def hits(w):
                return w.isVisible() and QRect(
                    w.mapToGlobal(w.rect().topLeft()),
                    w.mapToGlobal(w.rect().bottomRight())
                ).contains(gpos)

            # _ctx_menu belongs here: it is the Cut/Copy/Paste menu for _tag_name_edit itself,
            # so clicking it is not "clicking outside the edit". Without it, pressing Cut ran
            # _revert_tag_name() first — which setText()s the field back to the original name
            # and clears the selection — so the button's handler then cut nothing, and the
            # in-progress rename was silently discarded. Same defect and same fix as
            # BookDetailPanel.eventFilter's safe tuple (2026-07-30).
            safe = (self._tag_name_edit, self._action_btn, self._ctx_menu)
            if not any(hits(w) for w in safe):
                self._revert_tag_name()
        return super().eventFilter(obj, event)

    def _revert_tag_name(self):
        if self._tag_name_edit.text().strip() != self._tag_name_original:
            self._tag_name_edit.setText(self._tag_name_original)
            self._set_action_mode("delete")

    def _on_panel_bg_click(self):
        if self._confirming_delete:
            self._cancel_delete_confirm()
        elif self._reserved_layout.currentWidget() is self._color_picker_row:
            self._show_reserved("none")

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
            if self._rename_revert_timer:
                self._rename_revert_timer.stop()
            self._rename_revert_timer = QTimer(self)
            self._rename_revert_timer.setSingleShot(True)
            self._rename_revert_timer.timeout.connect(lambda: self._set_action_mode("delete"))
            self._rename_revert_timer.start(2000)
        else:
            self._set_action_mode("save_error")

    def _on_tag_name_changed(self, text: str):
        # A new edit starting must cancel any pending revert-to-"delete" from a
        # previous rename's 2s "check" confirmation — otherwise that stale timer
        # fires mid-edit and silently flips the button back to "delete" regardless
        # of the in-progress "save" state (see TODO.md's tag-manager entry).
        if self._rename_revert_timer:
            self._rename_revert_timer.stop()
            self._rename_revert_timer = None
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
            px = _load_icon("trash.svg", color, 16, 0.70)
            self._action_btn.setIcon(QIcon(px))
            self._action_btn.setIconSize(QSize(16, 16))
        elif mode == "save":
            px = _load_icon("save.svg", color, 16, 0.7)
            self._action_btn.setIcon(QIcon(px))
            self._action_btn.setIconSize(QSize(16, 16))
        elif mode == "save_error":
            px = _load_icon("save.svg", "#E05050", 16, 0.9)
            self._action_btn.setIcon(QIcon(px))
            self._action_btn.setIconSize(QSize(16, 16))
        elif mode == "check":
            px = _load_icon("check.svg", color, 16, 0.7)
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
        px = _load_icon("trash.svg", color, 16, 0.35)
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

    def on_theme_changed(self, theme_name) -> None:
        from ..themes import get_tags_stylesheet, _resolve_theme
        resolved = _resolve_theme(theme_name)
        # get_tags_stylesheet expects a name string; derive one for the stylesheet
        # but use the resolved dict for all color lookups below.
        self._current_theme_name = theme_name if isinstance(theme_name, str) else resolved
        self.setStyleSheet(get_tags_stylesheet(theme_name))
        if hasattr(self, '_action_btn'):
            self._current_theme = resolved
            self._update_tag_icons()
        self._ctx_menu.apply_theme(resolved)
        self._placeholder_color_tags = resolved.get(
            'placeholder_tags',
            resolved.get('placeholder_stats',
                resolved.get('placeholder_cover',
                    resolved.get('library_narrator',
                        resolved.get('text', '#888888'))))
        )
        if hasattr(self, '_book_grid'):
            self._book_grid.set_placeholder_color(self._placeholder_color_tags)

    def _on_grid_remove(self, path: str):
        if self._confirming_delete:
            self._cancel_delete_confirm()
            return
        current = self._reserved_layout.currentWidget()
        if current is self._color_picker_row:
            self._show_reserved("none")
            return
        self._on_book_removed(path)

    def _on_book_removed(self, path: str):
        if self._current_tag:
            book = self.db.get_book(path)
            if book is None:
                return
            self.db.remove_book_tag(book.id, self._current_tag)
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
