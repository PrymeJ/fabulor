import logging
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
from . import scrollbar_jump

logger = logging.getLogger(__name__)

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

# Thumbnail row pitch for _TagBookGrid (the tag-detail panel's book grid) —
# _TagBookThumb is a fixed 47x47 (see its setFixedSize call) and the grid's
# own QGridLayout uses a uniform 3px spacing (self._grid.setSpacing(3)), so
# every row after the first sits exactly 50px further down. Used by
# _TagBookGrid.wheelEvent to correct scroll drift — see that method.
_TAG_GRID_ROW_PITCH = 50


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


class _ThumbFocusRing(QWidget):
    """A border overlay marking the keyboard-selected thumbnail — see
    _TagBookThumb.set_keyboard_focused for why this is a separate sibling widget
    rather than a paintEvent override on the thumbnail itself. Overlaps the SAME
    rect the no-cover placeholder's own border occupies
    (render_logo_placeholder_bordered's `pm.rect().adjusted(0, 0, -1, -1)`, 47×47
    here), by explicit design: a real cover has no border of its own to clash
    with, and a placeholder's border is simply covered/replaced by this one when
    both are showing, rather than the two competing visually. Pen width 2 (was
    1) — a 1px border was reported live as "barely visible and clashes with
    the placeholder [border]"; 2px reads as a clearly distinct focus indicator
    rather than looking like the placeholder's own outline."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._color = QColor("#ffffff")

    def set_color(self, color_hex: str) -> None:
        self._color = QColor(color_hex)
        self.update()

    def paintEvent(self, event):
        # Filled-frame technique (outer rect minus inner rect, via fillRect)
        # rather than a stroked drawRect — a stroked rect was reported live
        # as missing its top-left and bottom-left corner pixels (the
        # thumbnail showing through). A non-antialiased QPainter stroke on a
        # closed rect draws its four edges as separate segments and can drop
        # a corner pixel where two perpendicular 2px-wide segments should
        # overlap; filling four solid border bands has no such seam — each
        # band is a plain opaque rect, and the four together always cover
        # every corner completely regardless of pen/join-style quirks.
        painter = QPainter(self)
        thickness = 2
        r = self.rect()
        painter.fillRect(r.x(), r.y(), r.width(), thickness, self._color)  # top
        painter.fillRect(r.x(), r.bottom() - thickness + 1, r.width(), thickness, self._color)  # bottom
        painter.fillRect(r.x(), r.y(), thickness, r.height(), self._color)  # left
        painter.fillRect(r.right() - thickness + 1, r.y(), thickness, r.height(), self._color)  # right
        painter.end()


class _DotFocusRing(QWidget):
    """Same idea as _ThumbFocusRing, but a ring (not a square) for the color-
    picker dots — sized/positioned as a sibling overlay over each QLabel "●"
    glyph, same reason (Qt paints a parent before its children, so a ring drawn
    on the QLabel itself would sit BEHIND the glyph text)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._color = QColor("#ffffff")

    def set_color(self, color_hex: str) -> None:
        self._color = QColor(color_hex)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = painter.pen()
        pen.setColor(self._color)
        pen.setWidth(2)
        painter.setPen(pen)
        # Same symmetric-inset fix as _ThumbFocusRing above, for the same
        # reason: adjusted(1,1,-2,-2) insets the bottom/right 1px more than
        # the top/left for a 2px pen, which reads as the ring sitting
        # slightly toward the top-left of where it should be centered —
        # reported live as "not sharp enough, and it is in the wrong place."
        painter.drawEllipse(self.rect().adjusted(1, 1, -1, -1))
        painter.end()


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

        # Keyboard-cursor indicator (2026-09-08) — a SIBLING overlay, not a paintEvent
        # override on this widget or on _cover: Qt paints a parent's own paintEvent
        # BEFORE its children, never after, so a border drawn in _TagBookThumb's own
        # paintEvent would be painted first and then covered by _cover's pixmap —
        # invisible regardless of z-order calls. A separate, raised, mouse-transparent
        # widget sized to match is the only way to guarantee the border paints on TOP
        # of the cover/placeholder, real or not — same rect the placeholder's own
        # border already occupies (_render_svg_placeholder_bordered's
        # pm.rect().adjusted(0,0,-1,-1)), by design: "a hollow square with 1px border
        # ... to exactly overlap and cover the placeholder's outline."
        self._focus_ring = _ThumbFocusRing(self)
        self._focus_ring.setGeometry(0, 0, 47, 47)
        self._focus_ring.hide()

    def set_keyboard_focused(self, focused: bool, color: str | None = None) -> None:
        """Show/hide the keyboard-cursor border overlay. `color` is only read when
        `focused` is True (typically the panel's live theme accent)."""
        if color is not None:
            self._focus_ring.set_color(color)
        self._focus_ring.setVisible(focused)
        if focused:
            self._focus_ring.raise_()

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
        # Real Qt focus (2026-09-08, keyboard nav) — entry point for the whole
        # tag-detail sub-panel; TagManagerWidget._claim_panel_focus-equivalent
        # targets this widget directly, same reasoning as _tag_scroll for the
        # list view (KeyPress events need to land HERE for eventFilter to see
        # them). QScrollArea's own default is already StrongFocus, but set
        # explicitly rather than relied on, matching the Speed/Sleep/Sprint
        # grids' own convention of never assuming a Qt default silently holds.
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

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
        # Keyboard cursor — (row, col) into the REAL thumbnail grid, i.e.
        # `self._cols` columns, never grid.columnCount() (which is _cols + 1,
        # counting the trailing stretch column above — a real gotcha here that
        # doesn't apply to Speed/Sleep/Sprint's grids, which have no such
        # column). None means no keyboard cursor active, matching the
        # "no memory across a rebuild/exit" convention every other kbdnav
        # region on this branch already follows.
        self._kbdnav_pos: tuple[int, int] | None = None
        self._kbdnav_color = "#ffffff"

        # Right-click-to-jump (ui/scrollbar_jump.py) lands on a pixel-exact
        # position by default — would clip a thumbnail row here, same reason
        # this was needed for Library/Stats and the tag LIST view before
        # their own row-snap fixes (see _TAG_ROW_PITCH's own registration,
        # above). _TAG_GRID_ROW_PITCH is a fixed, uniform stride (every
        # thumbnail is 47x47 with 3px grid spacing), so the snap is a plain
        # floor-to-multiple.
        scrollbar_jump.register_snap(
            self.verticalScrollBar(),
            lambda v: (v // _TAG_GRID_ROW_PITCH) * _TAG_GRID_ROW_PITCH
        )

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

        # Every thumbnail was just deleted and recreated — a keyboard cursor from
        # before this rebuild points at a widget that no longer exists. Re-derive
        # (clamped to the new, possibly-shorter book count) and reapply the visual
        # to the corresponding NEW widget at the same (row, col), rather than
        # dropping the cursor outright — a book removal via Enter/Space should
        # leave the cursor sensibly positioned for the next removal, not force a
        # fresh Down/Up before the grid is navigable again.
        if self._kbdnav_pos is not None:
            row, col = self._kbdnav_pos
            n = len(self._books)
            if n == 0:
                self._kbdnav_pos = None
            else:
                last_row = (n - 1) // self._cols
                row = min(row, last_row)
                cols_in_row = min(self._cols, n - row * self._cols)
                col = min(col, cols_in_row - 1)
                self._kbdnav_pos = (row, col)
                self._apply_kbdnav_visual()

    def _apply_kbdnav_visual(self) -> None:
        """Show the focus ring on exactly the thumbnail at self._kbdnav_pos (or
        none showing if that's None) — the single place that touches
        set_keyboard_focused, so cursor state and visual state can never drift
        apart across a rebuild/move."""
        for r in range(self._grid.rowCount()):
            for c in range(self._cols):
                item = self._grid.itemAtPosition(r, c)
                w = item.widget() if item is not None else None
                if isinstance(w, _TagBookThumb):
                    w.set_keyboard_focused((r, c) == self._kbdnav_pos, self._kbdnav_color)

    def set_kbdnav_color(self, color_hex: str) -> None:
        self._kbdnav_color = color_hex
        if self._kbdnav_pos is not None:
            self._apply_kbdnav_visual()

    def kbdnav_pos(self):
        return self._kbdnav_pos

    def set_kbdnav_pos(self, pos: tuple[int, int] | None) -> None:
        self._kbdnav_pos = pos
        self._apply_kbdnav_visual()
        if pos is not None:
            item = self._grid.itemAtPosition(*pos)
            w = item.widget() if item is not None else None
            if w is not None:
                self.ensureWidgetVisible(w, 0, 0)

    def kbdnav_grid_shape(self) -> tuple[int, int]:
        """(row_count, cols) for the REAL thumbnail grid — cols is always
        self._cols, never self._grid.columnCount() (see __init__'s comment on
        the trailing stretch column). The last row may be short."""
        n = len(self._books)
        if n == 0:
            return (0, self._cols)
        return ((n - 1) // self._cols + 1, self._cols)

    def kbdnav_row_length(self, row: int) -> int:
        n = len(self._books)
        return max(0, min(self._cols, n - row * self._cols))

    def kbdnav_current_path(self) -> str | None:
        if self._kbdnav_pos is None:
            return None
        item = self._grid.itemAtPosition(*self._kbdnav_pos)
        w = item.widget() if item is not None else None
        return w._path if isinstance(w, _TagBookThumb) else None

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

    def wheelEvent(self, event):
        # Every thumbnail row sits on a fixed, uniform _TAG_GRID_ROW_PITCH
        # stride, so the scrollbar should always rest on a multiple of it —
        # but Qt's native wheel handling (this method does NOT override the
        # per-notch amount/direction — super() runs it unchanged) only ever
        # applies a relative delta with no knowledge of that pitch, so
        # repeated scrolling drifts a row's cut line further off the pitch
        # over time. Live-reported as "the mouse step was tuned to scroll
        # without causing drifts, but they drift" once the grid held enough
        # thumbnails (100+) to actually scroll multiple pages — this grid
        # never had the fix its sibling lists already got (Library/Stats
        # 2026-08-12, the tag LIST view earlier this same 2026-09-08 branch).
        # Same idiom as StatsRowListView.wheelEvent (stats_panel.py): let
        # native scroll apply its unchanged delta first, then round the
        # RESULT to the nearest row boundary on the next event-loop tick
        # (the corrected value isn't available yet inside this call, since
        # eventFilter/override callbacks run BEFORE QAbstractItemView/
        # QScrollArea applies its own scroll).
        super().wheelEvent(event)
        bar = self.verticalScrollBar()

        def _snap_after_native_scroll():
            v = bar.value()
            snapped = round(v / _TAG_GRID_ROW_PITCH) * _TAG_GRID_ROW_PITCH
            snapped = max(bar.minimum(), min(bar.maximum(), snapped))
            if snapped != v:
                bar.setValue(snapped)

        QTimer.singleShot(0, _snap_after_native_scroll)

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
        # Keyboard cursor for the tag LIST (added 2026-09-08) — an index into
        # _tag_list_rows(), independent of ScrollHoverTracker's mouse-driven
        # _hovered (that tracker's own suspend() is the coexistence hook, see
        # hover_tracker.py's docstring: "designed for keyboard selection to
        # land on top"). None means no keyboard cursor is currently active —
        # distinct from 0, a real cursor at the first row.
        self._kbdnav_row_index: int | None = None
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
        # QSS :hover alone goes stale there. See ui/hover_tracker.py. Shares
        # _tag_list_rows() with the keyboard cursor below (added 2026-09-08) so
        # the two can never disagree about what a "row" is.
        self._row_hover = ScrollHoverTracker(
            self._tag_scroll, self._tag_list_rows, self,
            on_mouse_reclaim=self._on_mouse_reclaimed_tag_list,
        )
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
        # Right-click-to-jump (ui/scrollbar_jump.py) lands on a pixel-exact position by
        # default, same as it did for Library/Stats before their row-snap fix — would clip
        # a row here too. _TAG_ROW_PITCH is a fixed, uniform stride (every row is the same
        # 32px height + 5px spacing, unlike Library's per-view-mode heights), so the snap is
        # a plain floor-to-multiple, no per-row walk needed.
        scrollbar_jump.register_snap(
            bar, lambda v: (v // _TAG_ROW_PITCH) * _TAG_ROW_PITCH
        )

        def _tag_rows_wheel(e):
            notches = -1 if e.angleDelta().y() > 0 else 1
            target = bar.value() + notches * _TAG_ROW_PITCH * _TAG_SCROLL_ROWS
            snapped = round(target / _TAG_ROW_PITCH) * _TAG_ROW_PITCH
            max_aligned = (bar.maximum() // _TAG_ROW_PITCH) * _TAG_ROW_PITCH
            bar.setValue(max(bar.minimum(), min(max_aligned, snapped)))
            e.accept()

        self._tag_scroll.wheelEvent = _tag_rows_wheel
        # Arrow-key handling for the tag LIST is real keyboard-nav as of 2026-09-08 —
        # see _handle_tag_list_keys/_set_kbdnav_row, wired in eventFilter's KeyPress
        # branch. `_tag_scroll` needs real focus (StrongFocus, Qt's default for
        # QAbstractScrollArea, unclaimed here — unlike Book Detail's History tab,
        # where the same default was a bug to fix, see book_detail_panel.py's
        # `_history_scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)`) so KeyPress events
        # actually land on it for the filter to see. `bar.setSingleStep(_TAG_ROW_PITCH)`
        # above still matters for the WHEEL/scrollbar-drag path, which never goes
        # through the keyboard cursor at all. Installed on _tag_scroll itself, not its
        # viewport() — arrow-key KeyPress events target whatever widget holds focus, which is
        # the scroll area itself under Qt's default StrongFocus. The installEventFilter() call
        # itself is deferred to the END of _build_ui (not here) — eventFilter's very first
        # branch reads self._action_btn, which does not exist yet at this point in
        # construction; installing here crashed immediately with AttributeError the first
        # time this was tried (confirmed via a live probe traceback, 2026-08-13).
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
        # 24, not 21 (live design follow-up, 2026-09-08) — grew to match the
        # color-picker dots' own 24x24 box (see _add_picker_dot's comment):
        # the keyboard-cursor ring needed room the old 20px dot/21px row
        # could not give it without being clipped. Pushes the book-count
        # label and thumbnail grid down by 3px — explicitly OK'd live.
        self._reserved_row.setFixedHeight(24)
        reserved_layout = QStackedLayout(self._reserved_row)
        reserved_layout.setContentsMargins(0, 0, 0, 0)
        reserved_layout.setStackingMode(QStackedLayout.StackingMode.StackOne)

        self._color_picker_row = QWidget()
        picker_layout = QHBoxLayout(self._color_picker_row)
        picker_layout.setContentsMargins(2, 0, 10, 0)
        picker_layout.setSpacing(9)
        # Ordered list of (dot widget, color_key, focus ring) — the color ROW's
        # keyboard-nav cursor is an index into this, built in the SAME
        # left-to-right order the widgets are actually added, so Left/Right
        # visually match cursor movement.
        self._color_picker_dots: list[tuple[QLabel, str | None, "_DotFocusRing"]] = []

        def _add_picker_dot(color_key, color_hex):
            dot = QLabel("●")
            # 24x24, not 20x20 (live design follow-up, 2026-09-08) — the ring
            # is a CHILD of this label (Qt clips a child to its parent's own
            # rect), so no ring geometry could ever avoid being clipped while
            # the label itself stayed 20x20: an 18x18 ring centered on the
            # glyph's true painted center (measured below) needs vertical
            # room from y=5 to y=23, which a 20px-tall parent cannot give it
            # regardless of the ring's own size/position. Reported live as
            # "more space at the top than bottom, and its bottom gets
            # clipped." 24x24 gives the needed room; _reserved_row/
            # _color_picker_row grew to match (see their own construction,
            # above) — explicitly OK'd live: "we can safely push the N books
            # label and the thumbnails here if the ring needs those 2 or 3px."
            dot.setFixedSize(24, 24)
            dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            dot.setStyleSheet("font-size: 27px;" if color_hex is None
                               else f"font-size: 27px; color: {color_hex};")
            if color_hex is None:
                dot.setObjectName("tag_dot_neutral")
            dot.setCursor(Qt.CursorShape.PointingHandCursor)
            dot.mousePressEvent = lambda e, k=color_key: self._set_tag_color(k)
            picker_layout.addWidget(dot)
            ring = _DotFocusRing(dot)
            # The "●" glyph's visual center does NOT match this label's
            # geometric center — confirmed live across two rounds (first
            # "clipped at the bottom", then, after enlarging the box and
            # recentring from an offscreen pixel measurement, "still not
            # centered, more space at the top"). The offscreen measurement
            # method itself is not trustworthy here — see CLAUDE.md's "DO NOT
            # verify a settings-panel/tab visual layout bug with headless
            # test scripts alone" — so ring.setGeometry below is now a bare,
            # directly-tunable number rather than derived from a recomputed
            # offscreen bounding box; nudge it directly against what's
            # visible live rather than re-measuring. A ring sized tight to
            # the glyph (first attempt: 12x12) was reported live as
            # "impossible to see, clashes with the placeholder" — a ring
            # HUGGING the dot reads as part of the dot rather than as a
            # indicator. y=4 (x still 3) is a live-nudged value, not derived
            # from any measurement — see the note above on why the
            # offscreen-measured offset is not being trusted anymore. Tuned
            # live across three rounds: y=5 read as "more space at top",
            # y=3 read as "wrong direction" (too much space at bottom); y=4
            # split the difference.
            ring.setGeometry(3, 4, 18, 18)
            ring.hide()
            self._color_picker_dots.append((dot, color_key, ring))

        _add_picker_dot(None, None)
        for color_key, color_hex in TAG_COLORS.items():
            _add_picker_dot(color_key, color_hex)
        picker_layout.addStretch()
        # Keyboard cursor into _color_picker_dots — None means no cursor active.
        # Reset to None every time the picker opens/closes (_show_reserved), same
        # "no memory across exit" convention as the tag list and thumbnail grid.
        self._color_kbdnav_index: int | None = None

        self._confirm_delete_label = _ClickableLabel("Confirm to delete the tag")
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

        # Deferred to the end of _build_ui — see the comment near _tag_scroll's other
        # setup above for why (eventFilter's self._action_btn access needs it to exist first).
        self._tag_scroll.installEventFilter(self)

    def showEvent(self, event):
        # Mirrors hideEvent below — required because TransportBarBlurOverlay
        # hides and re-shows the active panel ~5-15x/sec while a book plays
        # (see transport_bar_blur.py's own docstring), and each of those
        # synthetic hides fires hideEvent same as a real close. Without this
        # counterpart, the FIRST blur-grab cycle after _open_tag() strips the
        # QApplication-wide filter for good (removeEventFilter with no
        # matching reinstall) — confirmed live 2026-09-07: every detail-panel
        # key (Backspace/Delete/arrows) went dead within ~200ms of opening a
        # tag, every time, because hideEvent's remove had already fired
        # several times over by the time a key was pressed. BookDetailPanel
        # already gets this for free (it pairs showEvent/hideEvent on itself,
        # so its own filter self-heals every grab tick) — TagManagerWidget
        # never had the showEvent half. Reinstall is scoped to the detail
        # sub-panel actually being the visible one, since the filter must NOT
        # be active while the tag LIST view is showing (that view's own
        # eventFilter gate is `obj is self._tag_scroll`, unaffected by this).
        super().showEvent(event)
        if self._panel_widget.isVisible():
            QApplication.instance().installEventFilter(self)

    def hideEvent(self, event):
        # See showEvent above for why this alone is insufficient against the
        # blur grab. Removing here is still correct and necessary for the
        # REAL close case: _close_tags_flow hides the whole TagManagerWidget
        # without ever calling _show_list() first when a tag detail happens
        # to be open, so this is what stops the filter from leaking past a
        # genuine panel close.
        QApplication.instance().removeEventFilter(self)
        super().hideEvent(event)

    def refresh_books(self) -> None:
        if self._current_tag:
            self._open_tag(self._current_tag)

    def tag_scroll_widget(self):
        """The tag list's QScrollArea — the widget PanelManager._start_tags_entry gives
        real Qt focus to, so the list's own arrow-key handling (eventFilter, gated on
        `obj is self._tag_scroll`) actually receives KeyPress events. Exposed as a
        method rather than reaching into the private `_tag_scroll` attribute directly
        from panels.py."""
        return self._tag_scroll

    def refresh(self):
        """Reload tag list from DB. Always lands on the list view."""
        self._current_tag = None
        self._panel_widget.hide()
        self._list_widget.show()
        # Any keyboard cursor belongs to the OLD rows, about to be deleted —
        # clearing here (not re-deriving after rebuild) matches every other
        # region's "no memory across a rebuild/exit" convention this branch
        # established (see ThemeManager._kbdnav_swatch_pos's docstring); the
        # panel's own claim-focus path re-establishes row 0 on next entry.
        self._kbdnav_row_index = None

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

    def _tag_list_rows(self) -> list:
        """Tag-list row widgets in visual order, live off the layout — shared by
        ScrollHoverTracker (mouse) and the keyboard cursor below, so the two
        mechanisms can never disagree about what a "row" is. Rows are looked up
        fresh each call (never cached) since refresh() rebuilds them wholesale."""
        return [w for i in range(self._tag_list_layout.count())
                if (w := self._tag_list_layout.itemAt(i).widget()) is not None]

    def _on_mouse_reclaimed_tag_list(self) -> None:
        """Called by ScrollHoverTracker the instant it detects the REAL mouse has
        genuinely moved while the keyboard cursor was active (most-recent-input-
        wins — see ScrollHoverTracker._maybe_reclaim_from_mouse). Clears the
        keyboard cursor's own highlight WITHOUT touching the tracker's suspended
        state itself — the tracker has already un-suspended and is about to
        resync to the real cursor position in the same call, so calling back
        into _set_kbdnav_row(None) here (which would re-invoke suspend(False) a
        second time) is unnecessary and would just repeat work the tracker is
        already mid-way through doing."""
        rows = self._tag_list_rows()
        idx = self._kbdnav_row_index
        if idx is not None and 0 <= idx < len(rows):
            rows[idx].setProperty("hovered", "false")
            rows[idx].style().unpolish(rows[idx])
            rows[idx].style().polish(rows[idx])
        self._kbdnav_row_index = None

    def _set_kbdnav_row(self, index: int | None) -> None:
        """Move the tag-list keyboard cursor to `index` (or clear it with None),
        updating the visual highlight and suspending/resuming mouse hover to
        match — the same coexistence contract hover_tracker.py's docstring
        describes ("designed for keyboard selection to land on top";
        ScrollHoverTracker.suspend is the hook). Reuses the exact same
        `hovered` property + unpolish/polish primitive ScrollHoverTracker
        itself uses (_set_hovered), rather than a second visual mechanism, so
        a keyboard-selected row and a mouse-hovered row are pixel-identical —
        explicit design call: "Mouse hover highlight style to be used to
        indicate the active row." Scrolls the new row into view."""
        rows = self._tag_list_rows()
        prev_index = self._kbdnav_row_index
        if prev_index is not None and 0 <= prev_index < len(rows):
            rows[prev_index].setProperty("hovered", "false")
            rows[prev_index].style().unpolish(rows[prev_index])
            rows[prev_index].style().polish(rows[prev_index])
        self._kbdnav_row_index = index
        if index is None:
            self._row_hover.suspend(False)
            return
        self._row_hover.suspend(True)
        if 0 <= index < len(rows):
            row = rows[index]
            row.setProperty("hovered", "true")
            row.style().unpolish(row)
            row.style().polish(row)
            self._tag_scroll.ensureWidgetVisible(row, 0, 0)

    def _handle_tag_list_keys(self, event) -> bool:
        """Up/Down/PgUp/PgDown/Home/End move the keyboard cursor; Enter/Space
        open the tag under it (the same action a left-click on the row
        performs) — live design call, 2026-09-08: list-view nav ships before
        the tag-detail sub-panel's own, larger set of interactions. Returns
        True iff the key was consumed."""
        key = event.key()
        rows = self._tag_list_rows()
        if not rows:
            return False
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            if self._kbdnav_row_index is not None and 0 <= self._kbdnav_row_index < len(rows):
                tag = rows[self._kbdnav_row_index].property("tag_name")
                if tag:
                    self._open_tag(tag)
            return True
        # Pick up from wherever the MOUSE is currently hovering, when no keyboard
        # cursor is active yet — live design call, 2026-09-08: "can down arrow be
        # made to go to the next tag after grimdark [the currently mouse-hovered
        # row], while still taking away the mouse highlight? This way it would be
        # made like just one marker." ScrollHoverTracker.hovered_row is exactly
        # the hook its own docstring names for this ("so a future keyboard cursor
        # can coordinate with it rather than guess") — read ONLY when there is no
        # existing keyboard cursor (self._kbdnav_row_index is None), so an
        # in-progress keyboard session never gets silently reset to wherever the
        # mouse happens to be resting from an earlier, unrelated hover.
        if self._kbdnav_row_index is None:
            hovered = self._row_hover.hovered_row
            current = rows.index(hovered) if hovered in rows else -1
        else:
            current = self._kbdnav_row_index
        if key == Qt.Key.Key_Down:
            self._set_kbdnav_row(min(current + 1, len(rows) - 1) if current >= 0 else 0)
        elif key == Qt.Key.Key_Up:
            self._set_kbdnav_row(max(current - 1, 0) if current >= 0 else len(rows) - 1)
        elif key == Qt.Key.Key_PageDown:
            self._set_kbdnav_row(min(current + _TAG_SCROLL_ROWS, len(rows) - 1) if current >= 0 else 0)
        elif key == Qt.Key.Key_PageUp:
            self._set_kbdnav_row(max(current - _TAG_SCROLL_ROWS, 0) if current >= 0 else len(rows) - 1)
        elif key == Qt.Key.Key_Home:
            self._set_kbdnav_row(0)
        elif key == Qt.Key.Key_End:
            self._set_kbdnav_row(len(rows) - 1)
        else:
            return False
        return True

    def _handle_tag_detail_keys(self, event) -> bool:
        """Keyboard nav for the tag-DETAIL sub-panel — live design 2026-09-08.
        Dispatch order matters: panel-wide keys first (they must win regardless
        of where the keyboard cursor currently is), then whichever REGION
        (thumbnail grid / color row) is currently reachable. Returns True iff
        the key was consumed.

        Panel-wide, work from anywhere EXCEPT while _tag_name_edit has real
        focus (checked FIRST, below, before any of these) — Tab/Shift+Tab is
        the one key that still applies while editing, since it's the way OUT
        of edit mode; every other key while editing belongs to the QLineEdit
        itself. (Correction, 2026-09-08: an earlier version of this docstring
        claimed "native editing keys never reach here since QLineEdit
        consumes them before this app-wide filter runs" — that was simply
        wrong. A QApplication-wide event filter runs BEFORE the target
        widget's own event delivery, not after, so with the old dispatch
        order — hasFocus() checked LAST — Backspace/Delete were stolen from
        the field entirely: Backspace closed the whole panel instead of
        deleting a character, Delete armed the tag-delete confirmation
        instead of deleting a character. Confirmed live.)
          Backspace — same action as clicking the '<' back button
          Escape    — cancel an ARMED delete confirmation only; otherwise NOT
                      consumed here, so it falls through to MainWindow's own
                      panel-close handling (same class of "let the more
                      specific case intercept, defer otherwise" as
                      BookDetailPanel's own Escape handling elsewhere in this
                      app)
          Delete    — arm the delete confirmation (mirrors Space/Enter's role
                      as "activate" elsewhere: global within the panel,
                      explicit design call — "Delete button will not have
                      focus")
          Tab / Shift+Tab — jump into (or out of) the name field's edit mode;
                      identical behavior for both, since there's no "next
                      stop" to cycle to the way Tab normally cycles a row of
                      controls (explicit design call)
        """
        key = event.key()

        if key == Qt.Key.Key_Tab or (key == Qt.Key.Key_Backtab):
            if self._tag_name_edit.hasFocus():
                self._tag_name_edit.clearFocus()
                self._book_grid.setFocus(Qt.FocusReason.TabFocusReason)
            else:
                if self._reserved_layout.currentWidget() is self._color_picker_row:
                    self._show_reserved("none")
                self._clear_color_kbdnav()
                self._tag_name_edit.setFocus(Qt.FocusReason.TabFocusReason)
                self._tag_name_edit.selectAll()
            return True

        if self._tag_name_edit.hasFocus():
            # Editing — every other key belongs to the QLineEdit itself
            # (returnPressed/textChanged are already wired via signals;
            # Escape is claimed by the dedicated obj-is-_tag_name_edit branch
            # in eventFilter, which runs before this method is ever reached;
            # arrows/Backspace/Delete move/edit the text cursor natively).
            # Nothing below applies while editing.
            return False

        if key == Qt.Key.Key_Backspace:
            self._show_list()
            return True

        if key == Qt.Key.Key_Escape:
            if self._confirming_delete:
                self._cancel_delete_confirm()
                return True
            return False  # not armed — defer to the panel's own close handling

        if key == Qt.Key.Key_Delete:
            if not self._confirming_delete:
                self._on_delete_tag()
            return True

        if self._confirming_delete:
            # A dedicated branch, ahead of the color-row/thumbnail-grid
            # dispatch below — live design call, 2026-09-08, fixing a real
            # bug: with no branch here, Enter/Space fell through to whichever
            # region's own handler (color row or thumbnail grid) and did
            # THAT region's normal thing instead of confirming — reported
            # live as "Enter doesn't confirm, Space just dismisses" (Space
            # was actually triggering the thumbnail grid's own remove action,
            # which itself checks _confirming_delete and cancels — a
            # dismiss, not a confirm, and only by accident of that check
            # existing elsewhere). Enter/Space now confirm; any arrow key
            # dismisses (cancels) the confirmation rather than moving a
            # cursor that, while armed, isn't meant to be visibly navigable
            # anyway (the grid is locked — see _book_grid.set_locked).
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
                self._on_confirm_delete()
                return True
            if key in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
                self._cancel_delete_confirm()
                return True
            return True  # swallow everything else too — nothing should reach the locked grid/colors

        if self._color_kbdnav_index is not None:
            return self._handle_color_row_keys(event)
        return self._handle_thumb_grid_keys(event)

    def _clear_color_kbdnav(self) -> None:
        if self._color_kbdnav_index is not None:
            _, _, ring = self._color_picker_dots[self._color_kbdnav_index]
            ring.hide()
        self._color_kbdnav_index = None

    def _set_color_kbdnav(self, index: int) -> None:
        if self._color_kbdnav_index is not None:
            _, _, prev_ring = self._color_picker_dots[self._color_kbdnav_index]
            prev_ring.hide()
        self._color_kbdnav_index = index
        _, _, ring = self._color_picker_dots[index]
        color = self._current_theme.get("tags_kbdnav_ring", self._current_theme.get("accent_light", "#ffffff"))
        ring.set_color(color)
        ring.show()
        ring.raise_()

    def _handle_color_row_keys(self, event) -> bool:
        """Left/Right cycle the picker dots with CONTINUOUS wrap (Right past the
        last dot goes to the first, Left before the first goes to the last —
        live design call, 2026-09-08 follow-up: differs from the thumbnail
        grid's reading-order wrap since this is a flat row, not a 2-D grid);
        Down leaves to the thumbnail grid, Up leaves to the name field's edit
        mode (explicit design call: "name is reachable from the colored dots.
        You just press Up."); Enter/Space picks the focused color, same action
        as clicking it."""
        key = event.key()
        n = len(self._color_picker_dots)
        idx = self._color_kbdnav_index
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            _, color_key, _ = self._color_picker_dots[idx]
            self._set_tag_color(color_key)
            return True
        if key == Qt.Key.Key_Right:
            self._set_color_kbdnav((idx + 1) % n)
            return True
        if key == Qt.Key.Key_Left:
            self._set_color_kbdnav((idx - 1) % n)
            return True
        if key == Qt.Key.Key_Down:
            self._clear_color_kbdnav()
            self._show_reserved("none")  # leaving without picking a color closes the picker
            pos = self._book_grid.kbdnav_pos()
            if pos is None:
                rows_count, _ = self._book_grid.kbdnav_grid_shape()
                if rows_count > 0:
                    self._book_grid.set_kbdnav_pos((0, 0))
            self._book_grid.setFocus(Qt.FocusReason.OtherFocusReason)
            return True
        if key == Qt.Key.Key_Up:
            self._clear_color_kbdnav()
            self._show_reserved("none")  # leaving without picking a color closes the picker
            self._tag_name_edit.setFocus(Qt.FocusReason.OtherFocusReason)
            self._tag_name_edit.selectAll()
            return True
        return False

    def _handle_thumb_grid_keys(self, event) -> bool:
        """Left/Right/Up/Down move the thumbnail cursor with READING-ORDER wrap
        (same model as Themes' swatch grid and the Speed/Sleep/Sprint preset
        grids' 2026-09-07 fix): past a row's last thumbnail, Right continues
        onto the next row's first; past a row's first, Left continues onto the
        previous row's last. Right at the very LAST thumbnail overall wraps
        around to the very first (live design follow-up, 2026-09-08). Left at
        the grid's OWN first thumbnail (row 0, col 0) instead exits UP to the
        color row rather than wrapping — explicit live design call, confirmed
        again on the same follow-up: "wrapping it up to go to the last item...
        it can be argued that it makes going back up harder to find," so Left
        stays a second, more-discoverable way out at that one position, while
        Right still gets the full wrap. Up at row 0 (any column) also exits to
        the color row. Enter/Space = left-click (remove from tag);
        Shift+Enter/Shift+Space OR Alt+Enter/Alt+Space = right-click (open
        book detail) — Shift mirrors the Speed/Sleep/Sprint Shift-modifier
        convention for "the other click" established earlier this branch;
        Alt is ADDITIONALLY supported because Library already uses Alt+Enter
        for its own "open detail" action (live design call, 2026-09-08 —
        Library gaining a matching Shift+Enter, and Speed/Sleep/Sprint
        possibly gaining Alt+Enter, are both deferred to TODO.md)."""
        key = event.key()
        modifiers = event.modifiers()
        other_click = bool(
            modifiers & Qt.KeyboardModifier.ShiftModifier
            or modifiers & Qt.KeyboardModifier.AltModifier
        )
        rows_count, cols = self._book_grid.kbdnav_grid_shape()
        if rows_count == 0:
            return False
        pos = self._book_grid.kbdnav_pos()
        if pos is None:
            self._book_grid.set_kbdnav_pos((0, 0))
            return True
        row, col = pos

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            path = self._book_grid.kbdnav_current_path()
            if path:
                if other_click:
                    self.detail_requested.emit(path)  # right-click equivalent
                else:
                    # left-click equivalent — routed through _TagBookGrid's own
                    # _on_remove (NOT _on_grid_remove directly), same path a real
                    # mouse click takes via _TagBookThumb.mousePressEvent's
                    # remove_requested signal. _on_remove is what keeps the
                    # grid's own self._books/_rebuild() in sync with the removal
                    # — calling _on_grid_remove (parent_remove) alone, as an
                    # earlier version of this did, updated the DB and the book-
                    # count label but left the grid showing the stale (pre-
                    # removal) thumbnails until the next full _open_tag. Found
                    # live 2026-09-08 from a screenshot: label said "2 books",
                    # grid still showed 3 thumbnails.
                    self._book_grid._on_remove(path)
            return True

        def _row_len(r: int) -> int:
            return self._book_grid.kbdnav_row_length(r)

        if key == Qt.Key.Key_Right:
            if col + 1 < _row_len(row):
                self._book_grid.set_kbdnav_pos((row, col + 1))
            elif row + 1 < rows_count:
                self._book_grid.set_kbdnav_pos((row + 1, 0))
            else:
                self._book_grid.set_kbdnav_pos((0, 0))  # last overall -> wrap to first
            return True
        if key == Qt.Key.Key_Left:
            if col > 0:
                self._book_grid.set_kbdnav_pos((row, col - 1))
            elif row > 0:
                self._book_grid.set_kbdnav_pos((row - 1, _row_len(row - 1) - 1))
            else:
                self._enter_color_row_from_thumbnails()
            return True
        if key == Qt.Key.Key_Down:
            # Wraps to row 0 at the last row (live design follow-up,
            # 2026-09-08) — mirrors Right-wraps-to-the-first-thumbnail rather
            # than exiting the grid, since Down/Up already have their own
            # dedicated exit (row 0's Up) distinct from this axis.
            next_row = row + 1 if row + 1 < rows_count else 0
            target_col = min(col, _row_len(next_row) - 1)
            self._book_grid.set_kbdnav_pos((next_row, target_col))
            return True
        if key == Qt.Key.Key_Up:
            if row > 0:
                target_col = min(col, _row_len(row - 1) - 1)
                self._book_grid.set_kbdnav_pos((row - 1, target_col))
            else:
                self._enter_color_row_from_thumbnails()
            return True
        return False

    def _enter_color_row_from_thumbnails(self) -> None:
        """Leaves the thumbnail grid upward into the color row — opening the
        picker first if it wasn't already showing (Left/Up from the grid are
        the KEYBOARD's own way of reaching the colors, distinct from the
        mouse's click-the-dot toggle, so they must make the row visible
        themselves rather than requiring it to already be open)."""
        self._book_grid.set_kbdnav_pos(None)
        self._book_grid.clearFocus()
        if self._reserved_layout.currentWidget() is not self._color_picker_row:
            if not self._confirming_delete:
                self._show_reserved("picker")
        self._set_color_kbdnav(0)

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
        row.setProperty("tag_name", tag)  # read back by _handle_tag_list_keys' Enter/Space
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
        # Keyboard-nav entry point (2026-09-08): the thumbnail grid, not the top
        # row — explicit live design call ("I am considering that we start with
        # the thumbnails... more practical", since thumbnails receive the most
        # interaction and a top-row-first entry would cost 2-3 presses to reach
        # them every time). No stale cursor survives a re-open of a (possibly
        # different) tag.
        self._book_grid.set_kbdnav_pos(None)
        # _clear_color_kbdnav(), not a bare `= None` — the bare form (this
        # line's own shape until 2026-09-08) left whatever _DotFocusRing was
        # showing from a PRIOR session still visible, since only
        # _clear_color_kbdnav actually calls ring.hide() on it. The dot ring
        # widgets are built once in _build_ui and never recreated (unlike the
        # thumbnail grid's rings, which are fresh every _rebuild()), so a ring
        # left shown here survives indefinitely — reported live as "closed the
        # panel, changed the theme, came back and the ring from earlier is
        # still lingering... did it again, a third one appeared" (each
        # reopen's ring was a real widget, correctly positioned, just never
        # told to hide).
        self._clear_color_kbdnav()
        self._book_grid.setFocus(Qt.FocusReason.OtherFocusReason)

    def _show_list(self):
        QApplication.instance().removeEventFilter(self)
        self._panel_widget.hide()
        self._list_widget.show()
        self._current_tag = None
        self.refresh()
        # Without this, real Qt focus stays wherever it last was in the detail
        # panel (e.g. _book_grid) — invisible since that widget is now hidden,
        # but it means _tag_scroll never gets a KeyPress, so arrows silently do
        # nothing until the user backs all the way out and the panel is
        # reopened (whatever re-claims focus at that point). Backspace from the
        # detail panel must leave the list exactly as ready for arrow nav as
        # a fresh panel-open does.
        self._tag_scroll.setFocus(Qt.FocusReason.OtherFocusReason)

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
            if event.key() == Qt.Key.Key_Down and self._panel_widget.isVisible():
                # Down from the name field cancels any unsaved edit and returns
                # to the color row — explicit live design call, 2026-09-08:
                # "Down arrow from the name should cancel it and go back to
                # colors" — "the user haven't hit Enter to save them, so going
                # out means discard is the intention." Same discard as Escape
                # (_revert_tag_name), but landing in the color row rather than
                # the thumbnail grid, mirroring how Up from the color row is
                # what reaches the name field in the first place. Reuses
                # _enter_color_row_from_thumbnails (its name is a slight
                # misnomer now — it's really "enter the color row from
                # wherever", already correctly guarded against
                # _confirming_delete) rather than duplicating the same
                # picker-opening logic a second time.
                self._revert_tag_name()
                self._tag_name_edit.clearFocus()
                self._enter_color_row_from_thumbnails()
                return True

        # Tag-LIST keyboard cursor (added 2026-09-08) — replaces the old scroll-only
        # stub that used to live here (native singleStep scrolling with no real
        # selection). Scoped to the list view being visible: the tag-detail
        # sub-panel's own, separate set of interactions (back/edit/delete/color
        # picker/thumbnails) is a SEPARATE handler, below.
        if (obj is self._tag_scroll and event.type() == QEvent.Type.KeyPress
                and self._list_widget.isVisible()):
            if self._handle_tag_list_keys(event):
                return True

        # Tag-DETAIL keyboard nav (added 2026-09-08). Scoped to the detail
        # sub-panel being visible, checked on every KeyPress in the panel
        # regardless of `obj` — Backspace/Esc/Delete/Tab are meant to work from
        # ANYWHERE in the panel (explicit design call: "Delete... Global. Delete
        # button will not have focus."), not just from one specific focused
        # widget, so this can't be gated the same way the list's own handler is.
        if event.type() == QEvent.Type.KeyPress and self._panel_widget.isVisible():
            if self._handle_tag_detail_keys(event):
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
            # Enter with nothing actually changed — live design call, 2026-09-08:
            # this used to be a silent no-op (Enter appeared to do nothing at
            # all), which read as broken. Since there's nothing to save, Enter
            # here means the same thing leaving the field any other way means:
            # exit edit mode, same as Escape (_revert_tag_name is a no-op too
            # in this exact case, since the text already matches the original).
            self._tag_name_edit.clearFocus()
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
        # Keyboard-cursor focus ring color (2026-09-08 follow-up) — was
        # hardcoded white, which reads poorly against light-background themes
        # (live report); briefly fell back to accent, then switched to
        # accent_light after a live "not sharp/needs to be lighter" report —
        # matches focus_folder_list_dot's own convention for a similarly
        # thin/small focus affordance.
        kbdnav_ring_color = resolved.get('tags_kbdnav_ring', resolved.get('accent_light', '#ffffff'))
        if hasattr(self, '_book_grid'):
            self._book_grid.set_kbdnav_color(kbdnav_ring_color)
        if hasattr(self, '_color_kbdnav_index') and self._color_kbdnav_index is not None:
            _, _, ring = self._color_picker_dots[self._color_kbdnav_index]
            ring.set_color(kbdnav_ring_color)

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
