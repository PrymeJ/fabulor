# THEME_ANIM_TODO: LibraryPanel, BookDelegate
import random
from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QGridLayout, QFrame, QPushButton, QHBoxLayout, QComboBox, QLineEdit, QProgressBar, QStyledItemDelegate, QListView, QStyleOptionViewItem,
)
from PySide6.QtCore import QThreadPool, QEvent, QAbstractListModel, QModelIndex, QSize, QTimer, QDateTime, Property, QPropertyAnimation
from PySide6.QtCore import Qt, Signal, QCoreApplication, QRect, QPoint
from typing import Optional
from ..models.book import Book
from .icon_utils import render_logo_placeholder, render_logo_placeholder_bordered
from PySide6.QtGui import QPixmap, QImage, QColor, QFont, QFontMetrics
from PIL import Image, ImageFilter

# View mode: (internal_key, [display_name_options])
ONE_PER_ROW_MODE   = ("1 per row", ["1 Flew Over", "1 Tree", "Ready Player 1", "1, None", "Power of 1", "1st Circle", "1st Law"])
TWO_PER_ROW_MODE   = ("2 per row", ["2 Cities", "2 Towers", "Swim-2-Birds", "2nd Sex", "2nd Sons"])
THREE_PER_ROW_MODE = ("3 per row", ["3 Body", "3 Stigmata", "3 Kingdoms", "Drawing of the 3", "3 Lives", "The 3rd Man", "3rd Policeman", "3 Guineas", "3 Comrades"])
SQUARE_MODE        = ("Square",    ["Washington Sq."])
LIST_MODE          = ("List",      ["Cannery Row", "Tamarisk Row"])
VIEW_MODES = [ONE_PER_ROW_MODE, TWO_PER_ROW_MODE, THREE_PER_ROW_MODE, SQUARE_MODE, LIST_MODE]

# Constants for Virtual Scrolling
ITEM_DIMENSIONS = {
    "3 per row": {"w": 96,  "h": 146, "cols": 3},
    "Square":    {"w": 96,  "h": 96,  "cols": 3},
    "2 per row": {"w": 140, "h": 226, "cols": 2},
    "1 per row": {"w": 292, "h": 159, "cols": 1},
    "List":      {"w": 290, "h": 28,  "cols": 1}
}

SORT_KEY_MAP = {
    "Title":       "title",
    "Author":      "author",
    "Last Played": "last_played",
    "Progress":    "progress",
    "Duration":    "duration",
    "Year":        "year",
    "Finished":    "finished",
}

MIN_PROGRESS = 1.0  # seconds — anything under 1 second is treated as zero

PRELOAD_INTERVAL_MS = 50   # ms between preload timer ticks
PRELOAD_BATCH_SIZE  = 4    # covers dispatched per tick (~80/s). Chosen by measuring the real
                           # warm path's MAIN-thread jank (heartbeat, warming in isolation after
                           # startup settle) at 50ms interval: batch 3 = 5 blocks>18ms / 25ms max,
                           # batch 4 = 6 blocks / 28ms max (indistinguishable from 3), batch 5 = 13
                           # blocks / 47ms max (clearly worse). So 4 buys ~33% faster warming for
                           # no meaningful extra jank; 5 is the wall. The cost is on the MAIN thread,
                           # NOT the off-thread LANCZOS: each worker fires TWO QueuedConnection
                           # completion slots (cover_loaded + sized_cover_loaded, each doing
                           # QImage->QPixmap + a dict write) and _preload_tick also does a synchronous
                           # get_active_cover_path DB read per book. Do NOT remove batching (dumping
                           # all workers at once froze the main thread ~766ms) and do NOT raise past 4
                           # without re-measuring the real two-slot path (an isolated one-slot sweep
                           # under-measures it and will mislead you toward a higher number).

_cover_cache: dict = {}  # module-level singleton {book_id (int): QPixmap}, shared by BookModel and idle preloader

def _parse_year_range(text: str):
    """Parse '>NNNN<NNNN' or '<NNNN>NNNN' into (min, max). Returns None if not a range."""
    import re
    m = re.fullmatch(r'>(\d+)<(\d+)|<(\d+)>(\d+)', text)
    if not m:
        return None
    if m.group(1):
        lo, hi = int(m.group(1)), int(m.group(2))
    else:
        lo, hi = int(m.group(4)), int(m.group(3))
    return (lo, hi) if lo <= hi else None  # invalidate impossible ranges

def _is_incomplete_year_filter(text: str) -> bool:
    """True while the user is still typing a year filter — no red yet."""
    import re
    # Single operator alone or with digits: <, >, <2010, >2010
    if re.fullmatch(r'[<>]\d*', text):
        return True
    # Range in progress: operator+digits+DIFFERENT operator+incomplete digits
    # >2010< or >2010<20 — but NOT >2010> (same operator = never valid)
    m = re.fullmatch(r'([<>])(\d+)([<>])(\d*)', text)
    if m and m.group(1) != m.group(3):
        # Only incomplete if the range isn't yet parseable as complete+invalid
        # i.e. second number has fewer than 4 digits (still being typed)
        return len(m.group(4)) < 4
    return False

FONT_SIZES = {
    "1 per row": {
        "title":      (14, True),   # (px, bold)
        "author":     (14, False),
        "narrator":   (13, False),
        "year":       (14, False),
        "elapsed":    (14, False),
        "total":      (14, False),
        "percentage": (14, False),
    },
    "2 per row": {
        "title":      (13, True),
        "author":     (12, False),
        "elapsed":    (14, False),
        "total":      (14, False),
        "percentage": (14, False),
    },
    "3 per row": {
        "title":      (12, True),   # no-cover placeholder text band
        "author":     (12, False),
        "elapsed":    (12, False),
        "total":      (12, False),
        "percentage": (12, False),
    },
    "Square": {
        "title":      (12, True),   # no-cover placeholder text band
        "author":     (12, False),
        "elapsed":    (12, False),
        "total":      (12, False),
        "percentage": (12, False),
    },
    "List": {
        "title":      (14, True),
        "author":     (13, False),
        "total":      (13, False),
        "elapsed":    (13, False),
    },
}

ACTIVE_BOOK_STRIPE_WIDTH = 4 # for the List view

class LibraryPanel(QFrame):
    book_selected    = Signal(str)
    back_requested   = Signal()
    detail_requested = Signal(str)

    _open_count = 0

    _SORT_DIRECTION_DEFAULTS = {
    "Title":       True,   # ascending, A→Z
    "Author":      True,   # ascending, A→Z
    "Year":        False,  # descending, newest→oldest
    "Duration":    False,  # descending, longest→shortest
    "Last Played": False,  # descending, most recent first
    "Progress":    False,  # descending, highest first
    "Finished":    False,  # descending, most recently finished first
    }

    def __init__(self, db, config, player_instance=None, parent=None):
        super().__init__(parent)
        self.db              = db
        self.config          = config
        self.player_instance = player_instance

        self._active_workers = set()
        self._current_theme  = {}
        self._show_start     = None
        self._tag_filter_active: bool = False
        self._sort_initialized = False

        self._setup_ui()
        self._resolve_theme_colors()
        self._setup_model_view()

        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(1000)
        self._progress_timer.timeout.connect(self.update_current_book_progress)

    # ── Theme ────────────────────────────────────────────────────────────────

    def _resolve_theme_colors(self):
        main_win = self.parent() if hasattr(self.parent(), 'theme_manager') else self.window()
        if main_win and hasattr(main_win, 'theme_manager'):
            self._current_theme = main_win.theme_manager.get_current_theme()

    def update_progress_bar_theme(self) -> None:
        self._resolve_theme_colors()
        self._delegate.update_theme(self._current_theme)
        self._apply_view_mode(self._delegate._view_mode)
        self._list_view.viewport().update()

    # ── Sort combo ───────────────────────────────────────────────────────────

    def _init_sort_combo(self, saved_sort: str) -> None:
        """Populate sort_combo with the base options, restoring saved_sort."""
        self.sort_combo.blockSignals(True)
        self.sort_combo.clear()
        for display, key in [
            ("Title",    "Title"),
            ("Author",   "Author"),
            ("Recent",   "Last Played"),
            ("Duration", "Duration"),
            ("Year",     "Year"),
        ]:
            self.sort_combo.addItem(display, key)
        idx = self.sort_combo.findData(saved_sort)
        self.sort_combo.setCurrentIndex(idx if idx != -1 else self.sort_combo.findData("Title"))
        self.sort_combo.blockSignals(False)

    def _rebuild_sort_combo(self) -> None:
        """Rebuild sort_combo dynamically, adding Progress/Finished only when data exists."""
        first_call = not self._sort_initialized
        if first_call:
            current_key = self.config.get_library_sort_key()
            self._sort_initialized = True
        else:
            current_key = self.sort_combo.currentData()

        self.sort_combo.blockSignals(True)
        self.sort_combo.clear()

        has_prog     = self.db.has_books_with_progress()
        has_finished = self.db.has_finished_books()

        options = [
            ("Title",    "Title"),
            ("Author",   "Author"),
            ("Recent",   "Last Played"),
            ("Duration", "Duration"),
            ("Year",     "Year"),
        ]
        if has_prog:
            options.insert(0, ("Progress", "Progress"))
        if has_finished:
            options.append(("Finished", "Finished"))

        for display, key in options:
            self.sort_combo.addItem(display, key)

        idx = self.sort_combo.findData(current_key)
        if idx == -1:
            idx = self.sort_combo.findData("Title")
            self.sort_combo.setCurrentIndex(idx)
            fallback_key = self.sort_combo.currentData()
            self._sort_ascending = self.__class__._SORT_DIRECTION_DEFAULTS.get(fallback_key, True)
            self.sort_dir_btn.setText("↑" if self._sort_ascending else "↓")
            self.config.set_library_sort_key(fallback_key)
            self.config.set_library_sort_ascending(self._sort_ascending)
        else:
            self.sort_combo.setCurrentIndex(idx)
            if first_call:
                self._sort_ascending = self.config.get_library_sort_ascending()
                self.sort_dir_btn.setText("↑" if self._sort_ascending else "↓")

        self.sort_combo.blockSignals(False)

    # ── Model / view setup ───────────────────────────────────────────────────

    def _setup_model_view(self):
        self._book_model = BookModel(db=self.db, parent=self)
        self._delegate   = BookDelegate(
            theme=self._current_theme,
            parent=self,
        )

        self._list_view = QListView(self)
        self._list_view.setModel(self._book_model)
        self._list_view.setItemDelegate(self._delegate)
        self._list_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list_view.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self._list_view.setResizeMode(QListView.ResizeMode.Adjust)
        self._list_view.setViewMode(QListView.ViewMode.ListMode)
        self._list_view.setUniformItemSizes(True)
        self._list_view.setMouseTracking(True)
        self._list_view.setContextMenuPolicy(Qt.CustomContextMenu)

        self._list_view.clicked.connect(self._on_item_clicked)
        self._list_view.customContextMenuRequested.connect(self._on_context_menu)
        self._list_view.entered.connect(self._on_view_entered)
        self._list_view.viewport().installEventFilter(self)
        self._list_view.verticalScrollBar().valueChanged.connect(self._load_visible_covers)
        self._list_view.viewport().setMouseTracking(True)
        self.main_layout.addWidget(self._list_view)
        self._delegate.set_viewport(self._list_view.viewport())

        saved_mode = self.style_combo.currentData()
        self._apply_view_mode(saved_mode)

    # ── Toolbar ──────────────────────────────────────────────────────────────

    def _setup_ui(self):
        self.setObjectName("library_panel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        self.top_bar_widget = QFrame()
        self.top_bar_widget.setObjectName("library_top_bar")
        self.top_bar_layout = QHBoxLayout(self.top_bar_widget)
        self.top_bar_layout.setContentsMargins(3, 13, 3, 6)
        self.top_bar_layout.setSpacing(3)

        self.sort_combo = QComboBox()
        self.sort_combo.setFixedWidth(65)
        self.sort_combo.setFixedHeight(30)
        self._init_sort_combo(self.config.get_library_sort_key())
        self._sort_ascending   = self.config.get_library_sort_ascending()
        self._last_filter_mode = self.sort_combo.currentData()
        self.sort_combo.currentTextChanged.connect(self._on_sort_changed)

        self.sort_dir_btn = QPushButton("↑" if self._sort_ascending else "↓")
        self.sort_dir_btn.setFixedWidth(16)
        self.sort_dir_btn.setFixedHeight(26)
        self.sort_dir_btn.clicked.connect(self._toggle_sort_direction)

        self.style_combo = QComboBox()
        for key, options in VIEW_MODES:
            self.style_combo.addItem(random.choice(options), key)
        self.style_combo.setFixedWidth(94)
        saved_mode = self.config.get_library_view_mode()
        for i in range(self.style_combo.count()):
            if self.style_combo.itemData(i) == saved_mode:
                self.style_combo.setCurrentIndex(i)
                break
        self.style_combo.currentTextChanged.connect(self._on_view_mode_changed)

        self.search_field = QLineEdit()
        self.search_field.setMaxLength(26)
        self.search_field.setPlaceholderText("search #tag")
        self.search_field.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.search_field.customContextMenuRequested.connect(lambda _: self.search_field.clear())
        self.search_field.setFixedWidth(63)
        self.search_field.setFixedHeight(30)
        self.search_field.textChanged.connect(self._on_search_changed)
        _original_focus = self.search_field.focusInEvent
        def _on_search_focus(event):
            if self._tag_filter_active:
                self.search_field.setText("")
                self._tag_filter_active = False
            _original_focus(event)
        self.search_field.focusInEvent = _on_search_focus
        def _search_key(e):
            if e.key() == Qt.Key.Key_Escape:
                self.search_field.clear()
                self.search_field.clearFocus()
            else:
                QLineEdit.keyPressEvent(self.search_field, e)
        self.search_field.keyPressEvent = _search_key

        if self.config.get_persist_filter_enabled():
            _saved = self.config.settings.value("persisted_filter", "")
            if _saved:
                self.search_field.blockSignals(True)
                self.search_field.setText(_saved)
                self.search_field.blockSignals(False)

        self.back_button = QPushButton("Back")
        self.back_button.setFixedHeight(28)
        self.back_button.clicked.connect(self.back_requested.emit)

        self.top_bar_layout.addWidget(self.sort_combo)
        self.top_bar_layout.addWidget(self.sort_dir_btn)
        self.top_bar_layout.addWidget(self.style_combo)
        self.top_bar_layout.addWidget(self.search_field)
        self.top_bar_layout.addWidget(self.back_button)
        self.main_layout.addWidget(self.top_bar_widget)

    # ── QListView slots ──────────────────────────────────────────────────────

    def _on_item_clicked(self, index):
        book = index.data(ROLE_BOOK)
        if not book:
            return
        if self._delegate.pending_field_filter:
            field, value = self._delegate.pending_field_filter
            self._delegate.pending_field_filter = None
            target = f"<{value}>{value}" if field == "year" else value
            if self.search_field.text() == target:
                self.set_search("")
            else:
                self.set_search(target)
            return
        live_pos = index.data(ROLE_LIVE_POS) or 0.0
        live_dur = index.data(ROLE_LIVE_DUR) or 0.0
        if live_pos > 0 and live_dur > 0:
            # Check if click was on time rect via delegate
            if self._delegate.last_event_was_toggle:
                self._delegate.last_event_was_toggle = False
                return
        self.book_selected.emit(book.path)

    def _on_context_menu(self, pos):
        index = self._list_view.indexAt(pos)
        if not index.isValid():
            return
        book = index.data(ROLE_BOOK)
        if book:
            self.detail_requested.emit(book.path)

    def _on_view_entered(self, index):
        book = index.data(ROLE_BOOK)
        prev_path = getattr(self, '_hovered_book_path', None)
        self._hovered_book_path = book.path if book else None
        self._book_model.set_hovered(book.id if book else None)
        if book:
            self._delegate.on_hover_enter(book.path)
            self._delegate.on_list_hover_enter(book.path)
        if prev_path and prev_path != self._hovered_book_path:
            self._delegate.on_list_hover_leave(prev_path)

    def _on_view_left(self):
        prev_path = getattr(self, '_hovered_book_path', None)
        self._hovered_book_path = None
        self._book_model.set_hovered(None)
        self._delegate.on_hover_leave()
        if prev_path:
            self._delegate.on_list_hover_leave(prev_path)

    def eventFilter(self, obj, event):
        if obj is self._list_view.viewport():
            if event.type() == QEvent.Type.MouseMove:
                pos = event.position().toPoint()
                self._delegate._hover_pos = pos
                idx = self._list_view.indexAt(pos)
                if idx.isValid():
                    book = idx.data(ROLE_BOOK)
                    # Cache the hovered book so the scroll-tick cursor refresh (_advance_scroll)
                    # can re-test the target under a stationary pointer as the marquee moves.
                    self._delegate._hover_book = book
                    if book:
                        self._delegate.on_hover_move(book.path, pos)
                    self._list_view.update(idx)
                    opt = QStyleOptionViewItem()
                    self._delegate.initStyleOption(opt, idx)
                    opt.rect = self._list_view.visualRect(idx)
                    hit = self._delegate._time_label_rect(opt, idx)
                    has_progress = book and (book.progress or 0.0) > MIN_PROGRESS
                    # Hand only over a real filter target — for a multi-value author/narrator
                    # that means over a name, NOT over the separator gap between names (a dead
                    # zone that clicks through to normal selection).
                    field_target = book and self._delegate._field_filter_target_at(book, pos)
                    if (hit and hit.contains(pos) and has_progress) or field_target:
                        self._list_view.viewport().setCursor(Qt.PointingHandCursor)
                    else:
                        self._list_view.viewport().setCursor(Qt.ArrowCursor)
                else:
                    self._list_view.viewport().setCursor(Qt.ArrowCursor)
                    self._delegate._hover_book = None
            elif event.type() == QEvent.Type.Leave:
                self._list_view.viewport().setCursor(Qt.ArrowCursor)
                self._delegate._hover_book = None
                self._on_view_left()
        return super().eventFilter(obj, event)



    # ── View mode ────────────────────────────────────────────────────────────

    def _apply_view_mode(self, mode: str) -> None:
        self._delegate.set_view_mode(mode)
        dim = ITEM_DIMENSIONS.get(mode, ITEM_DIMENSIONS["3 per row"])
        if mode in ("3 per row", "2 per row", "Square"):
            self._list_view.setViewMode(QListView.ViewMode.IconMode)
            self._list_view.setGridSize(QSize(dim["w"], dim["h"]))
            self._list_view.setSpacing(0)
            c = self._delegate._grid_bg
            self._list_view.viewport().setStyleSheet(
                f"background-color: rgb({c.red()},{c.green()},{c.blue()});"
            )
        else:
            self._list_view.setViewMode(QListView.ViewMode.ListMode)
            self._list_view.setGridSize(QSize())
            self._list_view.viewport().setStyleSheet("")

    def _on_view_mode_changed(self, _):
        mode = self.style_combo.currentData()
        self.config.set_library_view_mode(mode)
        self._resolve_theme_colors()

        # Capture the topmost visible book BEFORE the layout changes, as a plain index into
        # the filtered list. Content-anchored, NOT geometry-anchored: carrying the scrollbar's
        # raw pixel value() across the switch (Qt's default) lands it on a different book per
        # mode because each mode's total scroll range differs — the same pixel offset is a
        # different fraction of a different range (top/0 is the only range-independent value,
        # which is why it was the one case that "just worked"). A list index is stable across
        # the switch by construction: a mode change never reorders or refilters _filtered.
        top_row = self._first_visible_row()

        self._apply_view_mode(mode)
        self._book_model.set_hovered(None)

        self._list_view.reset()

        def _after_reset(_attempt=0):
            first_idx = self._book_model.index(0, 0)
            if first_idx.isValid() and self._list_view.visualRect(first_idx).isEmpty() and _attempt < 5:
                QTimer.singleShot(50, lambda: _after_reset(_attempt + 1))
                return
            # Restore the same book to the top now that the new mode's layout exists. scrollTo
            # clamps a too-large index gracefully (e.g. a near-bottom grid row that has no
            # equivalent in a shorter-range mode). top_row is None only if the layout wasn't
            # ready at capture time; index 0 / None both effectively leave the view at the top,
            # matching today's behavior for the scroll-to-top case (no regression there).
            if top_row is not None and 0 <= top_row < self._book_model.rowCount():
                idx = self._book_model.index(top_row, 0)
                if idx.isValid():
                    self._list_view.scrollTo(idx, QListView.ScrollHint.PositionAtTop)
            self._load_visible_covers()

        QTimer.singleShot(0, _after_reset)

    # ── Data / refresh ───────────────────────────────────────────────────────

    def refresh(self, force=False):
        self._resolve_theme_colors()
        self._rebuild_sort_combo()
        # Sync model's filter/sort state from UI without triggering a reset, then
        # reload books with a layoutChanged so the view keeps its scroll position.
        sort_key  = self.sort_combo.currentData()
        ascending = getattr(self, '_sort_ascending', True)
        self._book_model._filter_text   = self.search_field.text().lower().strip()
        self._book_model._sort_field    = SORT_KEY_MAP.get(sort_key, "title")
        self._book_model._sort_direction = "ascending" if ascending else "descending"
        self.config.set_library_sort_key(sort_key)
        self.config.set_library_sort_ascending(ascending)

        # Fetch books once and pass them to the model
        books = self.db.get_all_books()
        for book in books:
            book.speed = self.config.get_book_speed(book.path) or 1.0

        self._book_model.set_finished_dates(self.db.get_finished_book_data())
        self._book_model.set_books(books)

        def _after_covers(_attempt=0):
            first_idx = self._book_model.index(0, 0)
            if first_idx.isValid() and self._list_view.visualRect(first_idx).isEmpty() and _attempt < 5:
                QTimer.singleShot(50, lambda: _after_covers(_attempt + 1))
                return
            self._load_visible_covers()

        QTimer.singleShot(0, _after_covers)


    def _apply_current_sort_filter(self):
        text = self.search_field.text().lower().strip()
        self._book_model.filter_books(text)

        sort_key  = self.sort_combo.currentData()
        ascending = getattr(self, '_sort_ascending', True)
        direction = "ascending" if ascending else "descending"
        self._book_model.sort_books(SORT_KEY_MAP.get(sort_key, "title"), direction)
        self.config.set_library_sort_key(sort_key)
        self.config.set_library_sort_ascending(ascending)

    # ── Cover loading ────────────────────────────────────────────────────────

    def _first_visible_row(self) -> Optional[int]:
        """Row index of the topmost visible book via a visualRect binary search — the true
        first-visible row (indexAt(topLeft) is unreliable in IconMode because it can land in
        an inter-cell gutter). Returns None if the layout isn't ready (item 0 has no rect) or
        there are no rows. Single source of "what's on top" — used by both _load_visible_covers
        and the view-mode-switch position capture, which must agree."""
        row_count = self._book_model.rowCount()
        if row_count == 0:
            return None
        first_idx = self._book_model.index(0, 0)
        if not first_idx.isValid() or self._list_view.visualRect(first_idx).isEmpty():
            return None
        viewport_rect = self._list_view.viewport().rect()
        def _vr(row): return self._list_view.visualRect(self._book_model.index(row, 0))
        lo, hi = 0, row_count - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if _vr(mid).bottom() < viewport_rect.top():
                lo = mid + 1
            else:
                hi = mid
        return lo

    def _load_visible_covers(self):
        if not self.isVisible():
            return
        first_row = self._first_visible_row()
        if first_row is None:  # layout not ready
            return
        # Use visualRect to find the true visible row range — indexAt(bottomRight)
        # is unreliable in IconMode (grid) because it lands in inter-cell gutters.
        viewport_rect = self._list_view.viewport().rect()
        row_count = self._book_model.rowCount()
        def _vr(row): return self._list_view.visualRect(self._book_model.index(row, 0))
        lo, hi = first_row, row_count - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if _vr(mid).top() > viewport_rect.bottom():
                hi = mid - 1
            else:
                lo = mid
        last_row = lo
        first_row = max(0, first_row - 5)
        last_row  = min(row_count - 1, last_row + 5)
        in_flight = {getattr(w, '_book_id', None) for w in self._active_workers}
        dispatched = 0
        skipped_cached = 0
        skipped_flight = 0
        for row in range(first_row, last_row + 1):
            index = self._book_model.index(row, 0)
            book  = index.data(ROLE_BOOK)
            if not book:
                continue
            if _cover_cache.get(book.id):
                skipped_cached += 1
                continue
            if book.id in in_flight:
                skipped_flight += 1
                continue
            self._trigger_cover_load(book)
            dispatched += 1

    def _trigger_cover_load(self, book):
        from .cover_loader import CoverLoaderWorker
        active_path = self.db.get_active_cover_path(book.path) if self.db else None
        worker = CoverLoaderWorker(book, active_cover_path=active_path)
        worker._book_id = book.id
        self._active_workers.add(worker)
        worker.signals.cover_loaded.connect(self._on_cover_loaded, Qt.ConnectionType.QueuedConnection)
        worker.signals.finished.connect(lambda w=worker: self._active_workers.discard(w), Qt.ConnectionType.QueuedConnection)
        QThreadPool.globalInstance().start(worker)

    def _on_cover_loaded(self, book_id, image):
        if image.isNull():
            return
        if image.width() > 320 or image.height() > 480:
            image = image.scaled(
                320, 480,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        pixmap = QPixmap.fromImage(image)
        dpr = self.screen().devicePixelRatio() if self.screen() else 1.0
        pixmap.setDevicePixelRatio(dpr)
        _cover_cache[book_id] = pixmap  # write to cache directly
        if not getattr(self, '_is_animating', False):
            self._book_model.notify_cover_cached(book_id)  # emit dataChanged only if not sliding

    def refresh_book_cover(self, book_path: str) -> None:
        """Evict stale cache entry and reload cover for a single book by path."""
        book = self.db.get_book(book_path)
        if book is None:
            return
        _cover_cache.pop(book.id, None)
        self._delegate.evict_sized_cover(book.id)
        self._trigger_cover_load(book)

    # ── Sort / filter ────────────────────────────────────────────────────────

    def _toggle_sort_direction(self):
        self._sort_ascending = not getattr(self, '_sort_ascending', True)
        self.sort_dir_btn.setText("↑" if self._sort_ascending else "↓")
        sort_key  = self.sort_combo.currentData()
        direction = "ascending" if self._sort_ascending else "descending"
        self._book_model.sort_books(SORT_KEY_MAP.get(sort_key, "title"), direction)
        self.config.set_library_sort_ascending(self._sort_ascending)
        QTimer.singleShot(0, self._load_visible_covers)

    def _on_sort_changed(self):
        sort_key = self.sort_combo.currentData()
        self._sort_ascending = self.__class__._SORT_DIRECTION_DEFAULTS.get(sort_key, True)
        self.sort_dir_btn.setText("↑" if self._sort_ascending else "↓")
        direction = "ascending" if self._sort_ascending else "descending"
        self._book_model.sort_books(SORT_KEY_MAP.get(sort_key, "title"), direction)
        self.config.set_library_sort_key(sort_key)
        self.config.set_library_sort_ascending(self._sort_ascending)
        self._last_filter_mode = sort_key
        QTimer.singleShot(0, self._load_visible_covers)

    def _on_search_changed(self, text):
        self._book_model.filter_books(text.lower().strip())
        no_match = self._book_model.filter_empty
        incomplete = _is_incomplete_year_filter(text.lower().strip())
        if no_match and not incomplete:
            main_win = self.parent()
            tm = getattr(main_win, 'theme_manager', None)
            theme = tm.get_current_theme() if tm else {}
            text_color = theme.get('search_error_text', '#ffaaaa')
            self.search_field.setStyleSheet(
                f"background-color: rgba(120, 0, 0, 0.6); color: {text_color};"
            )
        else:
            self.search_field.setStyleSheet("")
        QTimer.singleShot(0, self._load_visible_covers)

    @staticmethod
    def _classify_filter(text: str):
        """Returns 'tag', 'year', or 'text' for a non-empty search string."""
        import re
        if text.startswith('#'):
            return 'tag'
        if (text.startswith('>') and text[1:].isdigit()) or \
           (text.startswith('<') and text[1:].isdigit()) or \
           re.fullmatch(r'[<>]\d+[<>]\d+', text):
            return 'year'
        return 'text'

    def save_search_filter(self):
        """Persist the current search field text to config on app close."""
        if not self.config.get_persist_filter_enabled():
            return
        text = self.search_field.text()
        if not text:
            self.config.settings.setValue("persisted_filter", "")
            return
        kind = self._classify_filter(text)
        allowed = (
            (kind == 'tag' and self.config.get_persist_filter_tag()) or
            (kind == 'year' and self.config.get_persist_filter_year()) or
            (kind == 'text' and self.config.get_persist_filter_text())
        )
        self.config.settings.setValue("persisted_filter", text if allowed else "")

    # ── Live progress ────────────────────────────────────────────────────────

    def update_current_book_progress(self):
        if getattr(self, '_is_animating', False):
            return
        if not self.player_instance:
            return

        pos = self.player_instance.time_pos or 0.0
        dur = self.player_instance.duration  or 0.0

        book = getattr(self.window(), '_current_book', None)
        if not book or dur <= 0:
            return

        self._book_model.update_playing_progress(book.id, pos, dur)

    def set_playing_path(self, path: str) -> None:
        self._delegate.set_playing_path(path)
        # Sync playing ID to the model to avoid window traversals
        self._book_model._playing_id = self._book_model._id_for_path(path)
        self._list_view.viewport().update()

    def set_is_playing(self, playing: bool) -> None:
        self._delegate.set_is_playing(playing)
        self._list_view.viewport().update()

    def set_hover_fade_enabled(self, mode: str) -> None:
        self._delegate.set_hover_fade_enabled(mode)

    def set_search(self, text: str) -> None:
        self.search_field.setText(text)
        self._tag_filter_active = True

    def clear_tag_filter_if_active(self) -> None:
        if self._tag_filter_active:
            self.search_field.setText("")
            self._tag_filter_active = False

    # ── Hide ─────────────────────────────────────────────────────────────────

    def _rotate_view_mode_labels(self):
        self.style_combo.blockSignals(True)
        for i, (_, options) in enumerate(VIEW_MODES):
            self.style_combo.setItemText(i, random.choice(options))
        self.style_combo.blockSignals(False)

    # ── Idle preload ─────────────────────────────────────────────────────────

    def _current_sized_key_dims(self) -> Optional[tuple]:
        """Device-pixel (dev_w, dev_h) the preloader should warm _sized_cover_cache to for
        the CURRENT view mode — the exact key _get_sized_cover computes at paint time
        (round(target * dpr)). Returns None when the mode draws no scaled cover (List), or
        when the panel has no screen yet. DPR is read here, on the MAIN thread, and passed
        by value into the worker — the worker must never read screen()/DPR itself."""
        cell = self._delegate.cover_cell_size()
        if cell is None:
            return None
        screen = self.screen()
        dpr = screen.devicePixelRatio() if screen else 1.0
        dev_w = max(1, round(cell[0] * dpr))
        dev_h = max(1, round(cell[1] * dpr))
        return (dev_w, dev_h)

    def _preload_paused(self) -> bool:
        """Per-batch gate: True while it is unsafe to run background preload work.
        Pauses ONLY during active animations + scan/theme-flow (the confirmed-to-interfere
        states); NOT gated on a static open panel, the Stats Month tab, playback, or seeking
        (all tested safe). Playback/seeking are deliberately allowed."""
        mw = self.window()
        # Scan in progress
        scanner = getattr(mw, 'scanner', None)
        if scanner is not None and scanner.is_running():
            return True
        tm = getattr(mw, 'theme_manager', None)
        if tm is not None:
            # Theme fade in flight
            if getattr(tm, '_fade_in_flight', False):
                return True
            fade_anim = getattr(tm, '_fade_anim', None)
            if fade_anim is not None and fade_anim.state() == QPropertyAnimation.State.Running:
                return True
        # Cover-art / book-switch flow animation (either slider)
        for slider_attr in ('progress_slider', 'chapter_progress_slider'):
            slider = getattr(mw, slider_attr, None)
            flow = getattr(slider, '_flow_anim', None) if slider is not None else None
            if flow is not None and flow.state() == QPropertyAnimation.State.Running:
                return True
        # Any panel slide animation running
        pm = getattr(mw, 'panel_manager', None)
        if pm is not None and pm.is_any_panel_animating():
            return True
        return False

    def start_idle_preload(self):
        if getattr(self, '_preload_timer', None) and self._preload_timer.isActive():
            return  # already running

        # Resume interrupted queue, or build a fresh one. A book stays queued if it needs
        # EITHER its raw cover (_cover_cache) OR its current-view-mode sized entry
        # (_sized_cover_cache) — the whole point of this pass is that a raw-warm-but-
        # sized-cold book (viewed once, or warmed by an earlier raw-only preload) still
        # needs sized warming. The per-tick skip re-checks this, so an already-fully-warm
        # book is dropped cheaply.
        if not getattr(self, '_preload_queue', None):
            sort_key  = SORT_KEY_MAP.get(self.config.get_library_sort_key(), "title")
            if sort_key not in self.db._ALLOWED_SORT_COLUMNS:
                sort_key = "title"
            ascending = self.config.get_library_sort_ascending()
            books = self.db.get_all_books(sort_by=sort_key, order="ASC" if ascending else "DESC")
            self._preload_queue = [b for b in books if self._needs_preload(b.id)]

        if not self._preload_queue:
            return

        if not getattr(self, '_preload_timer', None):
            self._preload_timer = QTimer(self)
            self._preload_timer.setSingleShot(False)
            self._preload_timer.timeout.connect(self._preload_tick)
        self._preload_timer.setInterval(PRELOAD_INTERVAL_MS)
        self._preload_timer.start()

    def _needs_preload(self, book_id: int) -> bool:
        """A book needs a preload pass if its raw cover is not cached, OR (for the current
        view mode) its sized entry is not cached. Sized target None (e.g. List mode) means
        only the raw cover matters."""
        if book_id not in _cover_cache:
            return True
        target = self._current_sized_key_dims()
        if target is None:
            return False
        return (book_id, target[0], target[1]) not in self._delegate._sized_cover_cache

    def _preload_tick(self):
        if not getattr(self, '_preload_queue', None):
            self._preload_timer.stop()
            return
        # Per-batch gate: pause (leave the queue intact) during interfering states. The
        # 5s idle-restart machinery in MainWindow.eventFilter resumes us after inactivity;
        # here we simply skip this tick and try again on the next one.
        if self._preload_paused():
            return
        from .cover_loader import CoverLoaderWorker
        sized_target = self._current_sized_key_dims()
        for _ in range(PRELOAD_BATCH_SIZE):
            if not self._preload_queue:
                break
            book = self._preload_queue.pop(0)
            raw_needed = book.id not in _cover_cache
            sized_needed = (
                sized_target is not None
                and (book.id, sized_target[0], sized_target[1]) not in self._delegate._sized_cover_cache
            )
            if not raw_needed and not sized_needed:
                continue
            active_path = self.db.get_active_cover_path(book.path) if self.db else None
            worker = CoverLoaderWorker(
                book,
                active_cover_path=active_path,
                sized_target=sized_target if sized_needed else None,
            )
            worker._book_id = book.id
            # cover_loaded warms _cover_cache; sized_cover_loaded warms _sized_cover_cache.
            # Both are QueuedConnection so the QImage->QPixmap conversion + dict write run on
            # the main thread (never write either cache from the worker).
            worker.signals.cover_loaded.connect(self._on_preload_cover_loaded, Qt.ConnectionType.QueuedConnection)
            worker.signals.sized_cover_loaded.connect(self._on_preload_sized_cover_loaded, Qt.ConnectionType.QueuedConnection)
            QThreadPool.globalInstance().start(worker)
            self._active_workers.add(worker)
            worker.signals.finished.connect(
                lambda w=worker: self._active_workers.discard(w),
                Qt.ConnectionType.QueuedConnection
            )

    def _on_preload_cover_loaded(self, book_id, image):
        if image.isNull():
            return
        pixmap = QPixmap.fromImage(image)
        dpr = self.screen().devicePixelRatio() if self.screen() else 1.0
        pixmap.setDevicePixelRatio(dpr)
        _cover_cache[book_id] = pixmap
        # If the model is showing this book, notify it
        if not getattr(self, '_is_animating', False):
            self._book_model.notify_cover_cached(book_id)

    def _on_preload_sized_cover_loaded(self, book_id, dev_w, dev_h, image):
        """Main-thread tail of the sized-warming path: convert the off-thread-scaled QImage
        to a QPixmap and store it under the exact key _get_sized_cover uses at paint time.
        Keying MUST match _get_sized_cover: (book_id, dev_w, dev_h) with dev_* already
        computed as round(target * dpr) on the main thread at enqueue time, and DPR set on
        the pixmap so its own devicePixelRatio matches what the paint path expects."""
        if image.isNull():
            return
        pixmap = QPixmap.fromImage(image)
        dpr = self.screen().devicePixelRatio() if self.screen() else 1.0
        pixmap.setDevicePixelRatio(dpr)
        self._delegate._sized_cover_cache[(book_id, dev_w, dev_h)] = pixmap
        if not getattr(self, '_is_animating', False):
            self._book_model.notify_cover_cached(book_id)

    def cancel_preload(self):
        if getattr(self, '_preload_timer', None) and self._preload_timer.isActive():
            self._preload_timer.stop()
            # leave _preload_queue intact so start_idle_preload can resume
        self._active_workers.clear()

    def preload_complete(self) -> bool:
        return not getattr(self, '_preload_queue', None)

    def showEvent(self, event):
        super().showEvent(event)
        if self._book_model.filter_empty:
            self.search_field.blockSignals(True)
            self.search_field.clear()
            self.search_field.setStyleSheet("")
            self.search_field.blockSignals(False)
            self._book_model.filter_books("")
        QTimer.singleShot(0, self._load_visible_covers)
        self._progress_timer.start()

    def hideEvent(self, event):
        self._progress_timer.stop()
        super().hideEvent(event)
        self._book_model.set_hovered(None)
        self._rotate_view_mode_labels()

    def evict_cover(self, book_id: int) -> None:
        _cover_cache.pop(book_id, None)
        self._delegate.evict_sized_cover(book_id)

    def get_cached_cover(self, book_id: int):
        return _cover_cache.get(book_id)


ROLE_BOOK     = Qt.UserRole + 0
ROLE_COVER    = Qt.UserRole + 1
ROLE_HOVERED  = Qt.UserRole + 2
ROLE_SHOW_REM = Qt.UserRole + 3
ROLE_LIVE_POS = Qt.UserRole + 4
ROLE_LIVE_DUR = Qt.UserRole + 5


class BookModel(QAbstractListModel):

    def __init__(self, db=None, parent=None):
        super().__init__(parent)
        self._db = db
        self._books: list[Book] = []
        self._filtered: list[Book] = []
        self._covers = _cover_cache  # shared singleton — preloader writes here before model exists
        self._show_remaining: dict[str, bool] = {}
        self._live_pos: dict[str, float] = {}
        self._live_dur: dict[str, float] = {}
        self._playing_id: Optional[int] = None
        self._hovered_path: Optional[str] = None
        self._filter_text: str = ""
        self._sort_field: str = "title"
        self._sort_direction: str = "ascending"
        self.filter_empty: bool = False
        self._filter_no_match: bool = False
        self._finished_dates: dict[int, object] = {}

    # ── QAbstractListModel interface ────────────────────────────────────────

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._filtered)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._filtered)):
            return None
        book = self._filtered[index.row()]

        if role == ROLE_BOOK:
            return book
        if role == ROLE_COVER:
            return self._covers.get(book.id)
        if role == ROLE_HOVERED:
            return self._hovered_path == book.id
        if role == ROLE_SHOW_REM:
            return self._show_remaining.get(book.id, True)
        if role == ROLE_LIVE_POS:
            return self._live_pos.get(book.id, book.progress or 0.0)
        if role == ROLE_LIVE_DUR:
            return self._live_dur.get(book.id, book.duration or 0.0)
        if role == Qt.DisplayRole:
            return book.title
        return None

    # ── Data mutation ───────────────────────────────────────────────────────

    def set_books(self, books: list[Book]) -> None:
        self.beginResetModel()
        self._books = list(books)

        # Retain live position only for the currently playing book
        self._live_pos = {k: v for k, v in self._live_pos.items() if k == self._playing_id}
        self._live_dur = {k: v for k, v in self._live_dur.items() if k == self._playing_id}

        self._apply_filter_and_sort()
        self.endResetModel()

    def set_finished_dates(self, dates: dict) -> None:
        self._finished_dates = dates

    def update_book_metadata(self, book_id: int, title: str, author: str, narrator: str = "", year: object = None) -> None:
        for book in self._books:
            if book.id == book_id:
                book.title = title
                book.author = author
                book.narrator = narrator or None
                book.year = year
                break
        self._apply_filter_and_sort()
        self._emit_for_id(book_id)

    def update_cover(self, book_id: int, pixmap: QPixmap) -> None:
        self._covers[book_id] = pixmap
        self._emit_for_id(book_id)

    def notify_cover_cached(self, book_id: int) -> None:
        self._emit_for_id(book_id)

    def update_playing_progress(self, book_id: int, position: float, duration: float) -> None:
        self._playing_id = book_id
        self._live_pos[book_id] = position if position > MIN_PROGRESS else 0.0
        self._live_dur[book_id] = duration
        self._emit_for_id(book_id)

    def toggle_show_remaining(self, book_id: int) -> None:
        self._show_remaining[book_id] = not self._show_remaining.get(book_id, True)
        self._emit_for_id(book_id)

    def set_hovered(self, book_id: Optional[int]) -> None:
        previous = self._hovered_path
        self._hovered_path = book_id
        if previous is not None:
            self._emit_for_id(previous)
        if book_id is not None:
            self._emit_for_id(book_id)

    # ── Sort / filter ───────────────────────────────────────────────────────

    def sort_books(self, field: str, direction: str) -> None:
        self._sort_field = field
        self._sort_direction = direction
        self.beginResetModel()
        self._apply_filter_and_sort()
        self.endResetModel()

    def filter_books(self, text: str) -> None:
        self._filter_text = text.lower()
        self.beginResetModel()
        self._apply_filter_and_sort()
        self.endResetModel()
        # True if filter is active and produced no results (# alone is not a real filter)
        self.filter_empty = self._filter_no_match

    # ── Internal ────────────────────────────────────────────────────────────

    def _apply_filter_and_sort(self) -> None:
        # Narrow to the relevant subset for the current sort key first,
        # then apply text/tag/year filtering on that subset.
        from datetime import datetime as dt

        if self._sort_field == "last_played":
            source = [b for b in self._books if (b.progress or 0.0) > MIN_PROGRESS]
        elif self._sort_field == "finished":
            source = [b for b in self._books if b.id in self._finished_dates]
        else:
            source = self._books

        text = self._filter_text
        if text:
            if text == '#':
                books = list(source)
                self._filter_no_match = False
            elif text.startswith('#'):
                tag = text[1:]
                if self._db:
                    tagged = self._db.get_paths_for_tag_prefix(tag)
                else:
                    tagged = set()
                matched = [b for b in source if b.path in tagged]
                self._filter_no_match = not matched
                books = matched if matched else list(source)
            elif _parse_year_range(text) is not None:
                year_min, year_max = _parse_year_range(text)
                matched = [b for b in source
                           if b.year is not None and year_min <= b.year <= year_max]
                self._filter_no_match = False
                books = matched if matched else list(source)
            elif text.startswith('>') and text[1:].isdigit():
                year_min = int(text[1:])
                matched = [b for b in source if b.year is not None and b.year >= year_min]
                self._filter_no_match = False
                books = matched if matched else list(source)
            elif text.startswith('<') and text[1:].isdigit():
                year_max = int(text[1:])
                matched = [b for b in source if b.year is not None and b.year <= year_max]
                self._filter_no_match = False
                books = matched if matched else list(source)
            else:
                matched = [
                    b for b in source
                    if text in b.title.lower()
                    or text in (b.author or "").lower()
                    or text in (b.narrator or "").lower()
                    or (b.year is not None and len(text) == 4 and text.isdigit() and text == str(b.year))
                ]
                self._filter_no_match = not matched
                books = matched if matched else list(source)
        else:
            self._filter_no_match = False
            books = list(source)

        reverse = self._sort_direction == "descending"
        field = self._sort_field

        def effective_val(b):
            if field == "finished":
                return self._finished_dates.get(b.id)
            if field == "progress":
                v = b.progress or 0.0
                return v if v > MIN_PROGRESS else None
            if field == "last_played":
                return None if (b.progress or 0.0) <= MIN_PROGRESS else getattr(b, field, None)
            val = getattr(b, field, None)
            if val is None:
                return None
            if isinstance(val, str) and not val.strip():
                return None
            return val

        def sort_key(b):
            if field == "progress":
                pos = b.progress or 0.0
                dur = b.duration or 0.0
                return pos / dur if dur > 0 else 0.0
            if field == "finished":
                return self._finished_dates.get(b.id, dt.min)
            val = getattr(b, field, None)
            if isinstance(val, str):
                return val.lower()
            return val

        have    = [b for b in books if effective_val(b) is not None]
        missing = [b for b in books if effective_val(b) is None]
        have.sort(key=sort_key, reverse=reverse)
        missing.sort(key=lambda b: (b.title or "").lower())
        books = have + missing
        self._filtered = books

    def _emit_for_id(self, book_id: int) -> None:
        for row, book in enumerate(self._filtered):
            if book.id == book_id:
                idx = self.index(row)
                self.dataChanged.emit(idx, idx, [Qt.DisplayRole])
                return

    def path_to_index(self, path: str) -> Optional[QModelIndex]:
        for row, book in enumerate(self._filtered):
            if book.path == path:
                return self.index(row)
        return None

    def _id_for_path(self, path: str) -> Optional[int]:
        for book in self._books:
            if book.path == path:
                return book.id
        return None


class BookDelegate(QStyledItemDelegate):
    """
    QStyledItemDelegate for the model/view library rewrite.
    Accepts theme colors as constructor arguments; never resolves them itself.
    """

    def __init__(self, theme: dict, parent=None):
        super().__init__(parent)
        self._apply_theme(theme)
        self.last_event_was_toggle = False
        self.pending_field_filter = None  # (field, value) or None
        self._hover_book = None  # book under cursor, for scroll-tick cursor refresh
        self._view_mode = "3 per row"
        self._alt_row_color = QColor(255, 255, 255, 10)  # overridden by _apply_theme
        self._hover_pos = QPoint()
        self._playing_path = ""
        self._is_playing = False
        self._pulse_phase = 0.0
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(40)
        self._pulse_timer.timeout.connect(self._advance_pulse)
        # Scroll state for 1-per-row and 2-per-row
        # (path, field) → [offset, direction, pause_ticks]  direction: -1=left, 1=right
        self._scroll_state: dict    = {}
        self._scroll_hovered_path   = ""
        self._scroll_field_rects: dict = {}  # path → {field: (x, y, w, h, full_text_w)}
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setInterval(40)
        self._scroll_timer.timeout.connect(self._advance_scroll)
        # Hover fade state — List mode only, user-toggleable
        self._hover_fade_mode = "Off"   # "Slow", "Normal", "Fast", "Off"
        self._list_hovered_path = ""
        self._hover_fade: dict = {}     # path → current alpha (0–255)
        self._hover_fade_timer = QTimer(self)
        self._hover_fade_timer.setInterval(16)  # ~60fps
        self._hover_fade_timer.timeout.connect(self._advance_hover_fade)
        

    def _apply_theme(self, theme: dict) -> None:
        def qc(hex_str, alpha=255):
            h = hex_str.lstrip('#')
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            return QColor(r, g, b, alpha)

        self._pg_bg          = theme.get('library_slider_bg',   theme.get('slider_overall_bg',   '#333333'))
        self._pg_fill        = theme.get('library_slider_fill', theme.get('slider_overall_fill', '#aaaaaa'))
        hc = theme.get('library_item_hover_color', theme.get('accent', '#ffffff'))
        ha = theme.get('library_item_hover_alpha', 0.50)
        self._hover_bg_color = qc(hc, int(ha * 255))

        self._bg_library     = qc(theme.get('library_bg',          '#1e1e1e'))
        self._grid_bg        = qc(theme.get('library_grid_bg',    theme.get('library_bg', '#1a1a1a')))
        self._row_one        = qc(theme.get('library_row_one',    '#242424'))
        self._row_two        = qc(theme.get('library_row_two',    '#2a2a2a'))
        self._color_title    = qc(theme.get('library_title',      '#ffffff'))
        self._color_author   = qc(theme.get('library_author',     '#aaaaaa'))
        self._color_narrator = qc(theme.get('library_narrator',   '#888888'))
        self._color_year     = qc(theme.get('library_year', theme.get('library_narrator', '#888888')))
        # Placeholder logo color (hex string — render_logo_placeholder_bordered takes a str).
        # placeholder_library is library-grid-tier (optional); falls back through the player tier.
        self._placeholder_color = theme.get('placeholder_library',
            theme.get('placeholder_cover',
                theme.get('library_narrator', theme.get('text', '#888888'))))
        # Reset the rendered-placeholder cache so stale-color pixmaps don't survive a theme switch.
        # Assigned (not .clear()'d) so the first call from __init__ works before the attr exists.
        self._placeholder_cache: dict = {}  # (color, w, h) → QPixmap
        self._sized_cover_cache: dict = {}  # (book_id, w, h) → QPixmap, pre-scaled to one cell size
        self._color_elapsed  = qc(theme.get('library_elapsed',    '#cccccc'))
        self._color_total    = qc(theme.get('library_total',      '#cccccc'))
        self._color_pct      = qc(theme.get('library_percentage', '#aaaaaa'))
        self._alt_row_color  = self._row_two
        self._color_accent   = qc(theme.get('accent', '#ffffff'))

    @Property(QColor)
    def pg_bg(self): return QColor(self._pg_bg)
    @pg_bg.setter
    def pg_bg(self, color): self._pg_bg = color; self.parent().update()

    @Property(QColor)
    def pg_fill(self): return QColor(self._pg_fill)
    @pg_fill.setter
    def pg_fill(self, color): self._pg_fill = color; self.parent().update()

    @Property(QColor)
    def hover_bg_color(self): return self._hover_bg_color
    @hover_bg_color.setter
    def hover_bg_color(self, color): self._hover_bg_color = color; self.parent().update()

    @Property(QColor)
    def bg_library(self): return self._bg_library
    @bg_library.setter
    def bg_library(self, color): self._bg_library = color; self.parent().update()

    @Property(QColor)
    def grid_bg(self): return self._grid_bg
    @grid_bg.setter
    def grid_bg(self, color): self._grid_bg = color; self.parent().update()

    @Property(QColor)
    def row_one(self): return self._row_one
    @row_one.setter
    def row_one(self, color): self._row_one = color; self.parent().update()

    @Property(QColor)
    def row_two(self): return self._row_two
    @row_two.setter
    def row_two(self, color): self._row_two = color; self.parent().update()

    @Property(QColor)
    def color_title(self): return self._color_title
    @color_title.setter
    def color_title(self, color): self._color_title = color; self.parent().update()

    @Property(QColor)
    def color_author(self): return self._color_author
    @color_author.setter
    def color_author(self, color): self._color_author = color; self.parent().update()

    @Property(QColor)
    def color_narrator(self): return self._color_narrator
    @color_narrator.setter
    def color_narrator(self, color): self._color_narrator = color; self.parent().update()

    @Property(QColor)
    def color_elapsed(self): return self._color_elapsed
    @color_elapsed.setter
    def color_elapsed(self, color): self._color_elapsed = color; self.parent().update()

    @Property(QColor)
    def color_total(self): return self._color_total
    @color_total.setter
    def color_total(self, color): self._color_total = color; self.parent().update()

    @Property(QColor)
    def color_pct(self): return self._color_pct
    @color_pct.setter
    def color_pct(self, color): self._color_pct = color; self.parent().update()

    @Property(QColor)
    def alt_row_color(self): return self._alt_row_color
    @alt_row_color.setter
    def alt_row_color(self, color): self._alt_row_color = color; self.parent().update()

    @Property(QColor)
    def color_accent(self): return self._color_accent
    @color_accent.setter
    def color_accent(self, color): self._color_accent = color; self.parent().update()

    def update_theme(self, theme: dict) -> None:
        self._apply_theme(theme)

    # ── Public API ──────────────────────────────────────────────────────────

    def set_view_mode(self, mode: str) -> None:
        self._view_mode = mode
        self._update_pulse_timer()

    def set_playing_path(self, path: str) -> None:
        self._playing_path = path or ""
        self._update_pulse_timer()

    def _update_pulse_timer(self) -> None:
        should_run = self._view_mode == "List" and bool(self._playing_path) and self._is_playing
        if should_run and not self._pulse_timer.isActive():
            self._pulse_timer.start()
        elif not should_run and self._pulse_timer.isActive():
            self._pulse_timer.stop()
            self._pulse_phase = 0.0

    def set_is_playing(self, playing: bool) -> None:
        self._is_playing = playing
        self._update_pulse_timer()

    def _advance_pulse(self) -> None:
        self._pulse_phase = (self._pulse_phase + 0.01) % 1.0
        vp = getattr(self, '_viewport', None)
        if vp:
            vp.update()

    def set_viewport(self, vp) -> None:
        self._viewport = vp

    # ── Hover fade (List mode) ───────────────────────────────────────────────

    def set_hover_fade_enabled(self, mode: str) -> None:
        self._hover_fade_mode = mode
        if mode == "Off":
            self._list_hovered_path = ""
            self._hover_fade.clear()
            self._hover_fade_timer.stop()

    def on_list_hover_enter(self, path: str) -> None:
        if self._hover_fade_mode == "Off":
            return
        self._list_hovered_path = path
        self._hover_fade[path] = self._hover_fade.get(path, 0)
        if not self._hover_fade_timer.isActive():
            self._hover_fade_timer.start()

    def on_list_hover_leave(self, path: str) -> None:
        if self._hover_fade_mode == "Off":
            return
        if self._list_hovered_path == path:
            self._list_hovered_path = ""
        if path not in self._hover_fade:
            self._hover_fade[path] = self._hover_bg_color.alpha()
        if not self._hover_fade_timer.isActive():
            self._hover_fade_timer.start()

    _HOVER_FADE_STEP_OUT = {"Slow": 3, "Normal": 5, "Fast": 7}

    def _advance_hover_fade(self) -> None:
        target_alpha = self._hover_bg_color.alpha()
        step_in  = 25
        step_out = self._HOVER_FADE_STEP_OUT.get(self._hover_fade_mode, 10)
        changed = False
        hovered_path = self._list_hovered_path
        for path in list(self._hover_fade):
            current = self._hover_fade[path]
            if path == hovered_path:
                new = min(target_alpha, current + step_in)
            else:
                new = max(0, current - step_out)
            if new != current:
                self._hover_fade[path] = new
                changed = True
            if new == 0 and path != hovered_path:
                del self._hover_fade[path]
        if not self._hover_fade:
            self._hover_fade_timer.stop()
        if changed:
            vp = getattr(self, '_viewport', None)
            if vp:
                vp.update()

    # ── Hover-scroll ────────────────────────────────────────────────────────

    _SCROLL_PX       = 0.8   # pixels per tick
    _SCROLL_PAUSE    = 50    # ticks to pause at each end (~1.2s at 40ms)
    _SCROLL_PAUSE_START = 10 # longer initial pause before first scroll

    def on_hover_enter(self, path: str) -> None:
        if self._view_mode not in ("1 per row", "2 per row", "3 per row", "Square"):
            return
        self._scroll_hovered_path = path
        # Clear state for any other path
        self._scroll_state = {k: v for k, v in self._scroll_state.items() if k[0] == path}
        self._start_scroll_for_path(path)

    def on_hover_leave(self) -> None:
        if not self._scroll_hovered_path:
            return
        keys = [k for k in self._scroll_state if k[0] == self._scroll_hovered_path]
        for k in keys:
            del self._scroll_state[k]
        self._scroll_hovered_path = ""
        if not self._scroll_state:
            self._scroll_timer.stop()
        vp = getattr(self, '_viewport', None)
        if vp:
            vp.update()

    def on_hover_move(self, path: str, viewport_pos) -> None:
        if self._view_mode not in ("1 per row", "2 per row", "3 per row", "Square"):
            return
        rects = self._scroll_field_rects.get(path, {})
        field_under = None
        for field, (fx, fy, fw, fh, _) in rects.items():
            if fx <= viewport_pos.x() < fx + fw and fy <= viewport_pos.y() < fy + fh:
                field_under = field
                break
        self._start_scroll_for_path(path, field_override=field_under)

    def _start_scroll_for_path(self, path: str, field_override: str = None) -> None:
        rects = self._scroll_field_rects.get(path, {})
        if not rects:
            return
        elided = {f for f, (_, _, fw, _, ftw) in rects.items() if ftw > fw}
        if not elided:
            return
        if field_override and field_override in elided:
            target = field_override
        else:
            for candidate in ("title", "author", "narrator"):
                if candidate in elided:
                    target = candidate
                    break
            else:
                return
        # Switch target: remove other fields for this path, keep existing state for target
        to_remove = [k for k in self._scroll_state if k[0] == path and k[1] != target]
        for k in to_remove:
            del self._scroll_state[k]
        if (path, target) not in self._scroll_state:
            # [offset, direction, pause_ticks]
            self._scroll_state[(path, target)] = [0.0, -1, self._SCROLL_PAUSE_START]
        if not self._scroll_timer.isActive():
            self._scroll_timer.start()

    def _advance_scroll(self) -> None:
        if not self._scroll_state:
            self._scroll_timer.stop()
            return
        changed = False
        for key, state in list(self._scroll_state.items()):
            path, field = key
            rects = self._scroll_field_rects.get(path, {})
            if field not in rects:
                del self._scroll_state[key]
                continue
            _, _, fw, _, ftw = rects[field]
            max_scroll = ftw - fw
            if max_scroll <= 0:
                del self._scroll_state[key]
                continue
            offset, direction, pause = state
            if pause > 0:
                state[2] -= 1
                continue
            offset += direction * self._SCROLL_PX
            if offset <= -max_scroll:
                offset = -max_scroll
                state[1] = 1
                state[2] = self._SCROLL_PAUSE
            elif offset >= 0:
                offset = 0.0
                state[1] = -1
                state[2] = self._SCROLL_PAUSE
            state[0] = offset
            changed = True
        if changed:
            # Text moved under a possibly-stationary cursor — refresh the hand/arrow cursor at
            # the last known pointer position so it tracks what's actually under the mouse now
            # (a name → hand, the gap between names → arrow), not what was there at the last
            # mouse-move. The grab itself is always correct at click time; this keeps the
            # affordance honest while the marquee scrolls.
            self._refresh_hover_cursor()
            vp = getattr(self, '_viewport', None)
            if vp:
                vp.update()

    def _refresh_hover_cursor(self) -> None:
        """Re-decide the viewport cursor for the currently-hovered book at the last known
        pointer pos. Driven by _advance_scroll so a stationary cursor over a scrolling
        multi-value field flips hand↔arrow as names/gaps pass under it. Mirrors the
        mouse-move cursor logic in LibraryPanel.eventFilter, routed through the same
        _field_filter_target_at so the two never diverge.

        Scoped to only touch the cursor while the pointer is over one of this book's
        author/narrator/year field rects — so it never clobbers the cursor the mouse-move
        handler set elsewhere (e.g. over the time label, or a different row)."""
        vp = getattr(self, '_viewport', None)
        book = getattr(self, '_hover_book', None)
        if vp is None or book is None:
            return
        if self._view_mode not in ("1 per row", "2 per row"):
            return
        if self._filterable_field_at(book.path, self._hover_pos) is None:
            return  # pointer not over any field of this book — leave the cursor as-is
        if self._field_filter_target_at(book, self._hover_pos):
            vp.setCursor(Qt.PointingHandCursor)
        else:
            vp.setCursor(Qt.ArrowCursor)

    def sizeHint(self, option, index):
        dim = ITEM_DIMENSIONS.get(self._view_mode, ITEM_DIMENSIONS["3 per row"])
        return QSize(dim["w"], dim["h"])

    # ── Paint dispatch ──────────────────────────────────────────────────────

    def paint(self, painter, option, index):
        book     = index.data(ROLE_BOOK)
        cover    = index.data(ROLE_COVER)
        hovered  = index.data(ROLE_HOVERED) or False
        show_rem = index.data(ROLE_SHOW_REM)
        if show_rem is None:
            show_rem = True
        live_pos = index.data(ROLE_LIVE_POS) or 0.0
        live_dur = index.data(ROLE_LIVE_DUR) or 0.0

        if book is None:
            return

        painter.save()
        painter.setClipRect(option.rect)

        if self._view_mode == "1 per row":
            self._paint_one_per_row(painter, option, index, book, cover, hovered, show_rem, live_pos, live_dur)
        elif self._view_mode == "2 per row":
            self._paint_two_per_row(painter, option, index, book, cover, hovered, show_rem, live_pos, live_dur)
        elif self._view_mode in ("3 per row", "Square"):
            self._paint_grid_cell(painter, option, index, book, cover, hovered, show_rem, live_pos, live_dur)
        elif self._view_mode == "List":
            self._paint_list_row(painter, option, index, book, hovered, show_rem, live_pos, live_dur)

        painter.restore()

    # ── editorEvent — toggle remaining/total on time label click ────────────

    def editorEvent(self, event, model, option, index):
        from PySide6.QtCore import QEvent as _QEvent
        if event.type() not in (_QEvent.Type.MouseButtonPress, _QEvent.Type.MouseButtonRelease):
            return False

        book = index.data(ROLE_BOOK)
        if not book:
            return False

        if self._view_mode in ("1 per row", "2 per row"):
            target = self._field_filter_target_at(book, event.pos())
            if target:
                if event.type() == _QEvent.Type.MouseButtonRelease:
                    self.pending_field_filter = target
                return True

        live_pos = index.data(ROLE_LIVE_POS) or 0.0
        live_dur = index.data(ROLE_LIVE_DUR) or 0.0
        if live_pos <= 0 or live_dur <= 0:
            return False

        hit = self._time_label_rect(option, index)
        if hit and hit.contains(event.pos()):
            if event.type() == _QEvent.Type.MouseButtonRelease:
                model.toggle_show_remaining(book.id)
                self.last_event_was_toggle = True
            return True
        return False

    # ── Playback resolution ──────────────────────────────────────────────────

    def _resolve_playback(self, book, live_pos: float, live_dur: float) -> tuple:
        """Returns (pos, dur, dur_disp, pct, has_progress, speed)"""
        has_progress = (book.progress or 0.0) > MIN_PROGRESS
        pos = live_pos if live_pos > 0 else (book.progress or 0.0)
        dur = live_dur if live_dur > 0 else (book.duration or 0.0)
        speed = (book.speed or 1.0) if has_progress else 1.0
        dur_disp = dur / speed if has_progress else dur
        pct = min(1.0, pos / dur) if has_progress and dur > 0 else 0.0
        return pos, dur, dur_disp, pct, has_progress, speed

    # ── Mode painters ───────────────────────────────────────────────────────

    def _paint_one_per_row(self, painter, option, index, book, cover, hovered, show_rem, live_pos, live_dur):
        r = option.rect

        painter.fillRect(r, self._row_one if index.row() % 2 == 0 else self._row_two)
        if hovered:
            painter.fillRect(r, self._hover_bg_color)

        # Cover (100×151, margins 4,4)
        cover_w, cover_h = 100, 151
        cover_rect = QRect(r.x() + 4, r.y() + 4, cover_w, cover_h)
        row_bg = self._row_one if index.row() % 2 == 0 else self._row_two
        if hovered:
            ha = self._hover_bg_color.alphaF()
            def _blend(base, over, a):
                return int(base * (1 - a) + over * a)
            cover_bg = QColor(
                _blend(row_bg.red(),   self._hover_bg_color.red(),   ha),
                _blend(row_bg.green(), self._hover_bg_color.green(), ha),
                _blend(row_bg.blue(),  self._hover_bg_color.blue(),  ha),
            )
        else:
            cover_bg = row_bg
        self._draw_cover(painter, cover_rect, cover, book, square=False, bg=cover_bg)

        pos, dur, dur_disp, pct, has_progress, speed = self._resolve_playback(book, live_pos, live_dur)

        text_x = r.x() + 4 + cover_w + 8
        text_w = r.right() - text_x - 4

        # Bottom block uses these; fm_time is read again below for the time row. (The bottom
        # block is bottom-anchored to r.bottom() and recomputes its own bar_y/time_y — the
        # text zone no longer needs to derive a text_bottom, since fields now pack from the
        # top by fixed heights rather than filling the space down to the bottom block.)
        BAR_H  = 6
        PAD    = 4
        self._set_font(painter, mode=self._view_mode, field="elapsed")
        fm_time = painter.fontMetrics()

        # Zone 2 — text block, packed downward from the top
        text_y = r.y() + PAD

        # Fixed, RESERVED slots per field TYPE. Each of the four metadata rows always owns the
        # same vertical position whether or not the others are present — a missing field leaves
        # its slot empty rather than letting later fields slide up. So a book with no narrator
        # renders title / author / <gap> / year, with year still in its own row. The slot y is
        # the cumulative sum of every PRECEDING slot's height + gap, computed unconditionally
        # from each field type's own font (not from which fields happen to exist). FIELD_GAP=8
        # reproduces the previous full-metadata spacing (title@4, author@31, narrator@58,
        # year@84) so a fully-populated book doesn't shift.
        FIELD_GAP = 8
        SLOT_ORDER = ("title", "author", "narrator", "year")
        values = {
            "title":    book.title or "",
            "author":   book.author or "",
            "narrator": book.narrator or "",
            "year":     str(book.year) if book.year else "",
        }
        color_map = {
            "title":    self._color_title,
            "author":   self._color_author,
            "narrator": self._color_narrator,
            "year":     self._color_year,
        }

        # Reserve each slot's y up front, walking ALL types regardless of population.
        slot_y = {}
        row_text_y = text_y
        for slot in SLOT_ORDER:
            self._set_font(painter, mode=self._view_mode, field=slot)
            slot_y[slot] = row_text_y
            row_text_y += painter.fontMetrics().height() + FIELD_GAP

        field_rects = {}
        for field in SLOT_ORDER:
            value = values[field]
            if not value:
                continue  # slot stays empty and reserved; later fields keep their own y
            self._set_font(painter, mode=self._view_mode, field=field)
            fm = painter.fontMetrics()
            full_w = fm.horizontalAdvance(value)
            line_h = fm.height()
            row_text_y = slot_y[field]
            field_rects[field] = (text_x, row_text_y, text_w, line_h, full_w)
            painter.setPen(color_map[field])
            offset = self._scroll_state.get((book.path, field), [None])[0] if (book.path, field) in self._scroll_state else None
            clip_rect = QRect(text_x, row_text_y, text_w, line_h)
            if offset is not None and full_w > text_w:
                painter.save()
                painter.setClipRect(clip_rect)
                painter.drawText(text_x + int(offset), row_text_y + fm.ascent(), value)
                painter.restore()
            else:
                painter.drawText(text_x, row_text_y + fm.ascent(), fm.elidedText(value, Qt.ElideRight, text_w))
        self._scroll_field_rects[book.path] = field_rects

        # Bottom block
        HPAD = 4
        VPAD = 8
        bar_y  = r.bottom() - VPAD - BAR_H
        time_y = max(r.y() + PAD, bar_y - VPAD - fm_time.height())
        baseline     = time_y + fm_time.ascent() # vertical center against bar

        if has_progress:
            elapsed_str = self._fmt(pos / speed)
            right_str   = f"-{self._fmt((dur - pos) / speed)}" if show_rem else self._fmt(dur_disp)

            # Time row
            painter.setPen(self._color_elapsed)
            painter.drawText(text_x, baseline, elapsed_str)

            self._set_font(painter, mode=self._view_mode, field="total")
            fm_total = painter.fontMetrics()
            right_w  = fm_total.horizontalAdvance(right_str)
            painter.setPen(self._color_total)
            painter.drawText(r.right() - HPAD - right_w, baseline, right_str)

            # Bar row
            bar_rect = QRect(text_x, bar_y, 147, BAR_H)
            self._draw_progress_bar(painter, bar_rect, pct)

            # Percentage — same row as bar, right of bar
            pct_str = f"{int(pct * 100)}%"
            self._set_font(painter, mode=self._view_mode, field="percentage")
            fm_pct  = painter.fontMetrics()
            pct_y   = bar_y + (BAR_H - fm_pct.height()) // 2 + fm_pct.ascent()
            painter.setPen(self._color_pct)
            pct_w = fm_pct.horizontalAdvance(pct_str)
            painter.drawText(r.right() - HPAD - pct_w, pct_y, pct_str)
        else:
            # No progress — total time at bar row, right-aligned
            dur_str  = self._fmt(dur_disp)
            self._set_font(painter, mode=self._view_mode, field="total")
            fm_total = painter.fontMetrics()
            dur_w    = fm_total.horizontalAdvance(dur_str)
            no_prog_y = bar_y + (BAR_H - fm_total.height()) // 2 + fm_total.ascent()
            painter.setPen(self._color_total)
            painter.drawText(r.right() - HPAD - dur_w, no_prog_y, dur_str)

    def _paint_two_per_row(self, painter, option, index, book, cover, hovered, show_rem, live_pos, live_dur):
        r = option.rect
        painter.fillRect(r, self._grid_bg)

        # Cover (113×172, left margin 13, top 8)
        cover_x = r.x() + 13
        cover_y = r.y() + 8
        cover_w, cover_h = 113, 172
        cover_rect = QRect(cover_x, cover_y, cover_w, cover_h)
        self._draw_cover(painter, cover_rect, cover, book, square=False, bg=self._grid_bg)

        # Title and author below cover
        text_x = cover_x
        text_w = cover_w - 14
        text_y = cover_y + cover_h + 2

        field_rects = {}
        title_h = self._draw_scrollable_field(
            painter, path=book.path, field="title", value=book.title or "",
            x=text_x, y=text_y, w=text_w, color=self._color_title, field_rects=field_rects)
        text_y += title_h + 2
        self._draw_scrollable_field(
            painter, path=book.path, field="author", value=book.author or "",
            x=text_x, y=text_y, w=text_w, color=self._color_author, field_rects=field_rects)
        self._scroll_field_rects[book.path] = field_rects

        # Hover overlay over cover rect
        if hovered:
            self._draw_hover_overlay(painter, cover_rect, book, show_rem, live_pos, live_dur, large=True)

    def _draw_scrollable_field(self, painter, *, path, field, value, x, y, w, color, field_rects, center=False) -> int:
        """Draw one text field: elide at rest, scroll the active hovered field if it overflows.
        Records field_rects[field] = (x, y, w, line_h, full_w) (caller owns the final
        self._scroll_field_rects[path] = field_rects assignment). Returns the line height.
        When center=True and the text fits (no scroll), it is horizontally centered in w.
        Modeled on the original 1-/2-per-row per-field draw."""
        self._set_font(painter, mode=self._view_mode, field=field)
        fm = painter.fontMetrics()
        line_h = fm.height()
        full_w = fm.horizontalAdvance(value)
        field_rects[field] = (x, y, w, line_h, full_w)
        painter.setPen(color)
        offset = self._scroll_state.get((path, field), [None])[0] if (path, field) in self._scroll_state else None
        if offset is not None and full_w > w:
            painter.save()
            painter.setClipRect(QRect(x, y, w, line_h))
            painter.drawText(x + int(offset), y + fm.ascent(), value)
            painter.restore()
        elif center and full_w <= w:
            painter.drawText(QRect(x, y, w, line_h), Qt.AlignHCenter | Qt.AlignVCenter, value)
        else:
            painter.drawText(x, y + fm.ascent(), fm.elidedText(value, Qt.ElideRight, w))
        return line_h

    def _paint_grid_cell(self, painter, option, index, book, cover, hovered, show_rem, live_pos, live_dur):
        r = option.rect
        painter.fillRect(r, self._grid_bg)
        square = (self._view_mode == "Square")
        has_cover = cover is not None and not cover.isNull()

        if has_cover:
            # Real cover: fills cell with 2px margin, no text (unchanged behavior).
            cover_rect = QRect(r.x() + 3, r.y() + 2, r.width() - 4, r.height() - 4)
            self._draw_cover(painter, cover_rect, cover, book, square=square, bg=self._grid_bg)
            # Drop any stale field-rect entry (e.g. book gained a cover after a no-cover paint),
            # else phantom scroll zones would linger on this real-cover cell until restart.
            self._scroll_field_rects.pop(book.path, None)
            if hovered:
                self._draw_hover_overlay(painter, cover_rect, book, show_rem, live_pos, live_dur, large=False)
            return

        # No cover: title + author at the top, logo centered below them. The 1px border frames
        # the WHOLE cell area (a square in Square mode), not just the logo. Cell size unchanged.
        cell_rect = QRect(r.x() + 3, r.y() + 2, r.width() - 4, r.height() - 4)
        painter.fillRect(cell_rect, self._grid_bg)

        field_rects = {}
        text_x = cell_rect.x() + 2
        text_w = cell_rect.width() - 4
        text_y = cell_rect.y() + 3
        title_h = self._draw_scrollable_field(
            painter, path=book.path, field="title", value=book.title or "",
            x=text_x, y=text_y, w=text_w, color=self._color_title, field_rects=field_rects, center=True)
        text_y += title_h + 1
        author_h = self._draw_scrollable_field(
            painter, path=book.path, field="author", value=book.author or "",
            x=text_x, y=text_y, w=text_w, color=self._color_author, field_rects=field_rects, center=True)
        self._scroll_field_rects[book.path] = field_rects

        # Logo centered in the area below the text rows.
        logo_top = text_y + author_h + 2
        logo_rect = QRect(cell_rect.x(), logo_top, cell_rect.width(), cell_rect.bottom() - logo_top + 1)
        self._draw_placeholder_logo(painter, logo_rect)

        # 1px border around the whole cell.
        painter.setPen(QColor(self._placeholder_color))
        painter.drawRect(cell_rect.adjusted(0, 0, -1, -1))

        if hovered:
            self._draw_hover_overlay(painter, cell_rect, book, show_rem, live_pos, live_dur, large=False)

    def _paint_list_row(self, painter, option, index, book, hovered, show_rem, live_pos, live_dur):
        r   = option.rect
        fm  = option.fontMetrics

        # Alternating row background, then hover on top
        painter.fillRect(r, self._row_one if index.row() % 2 == 0 else self._row_two)
        if self._hover_fade_mode != "Off":
            fade_alpha = self._hover_fade.get(book.path, 0)
            if fade_alpha > 0:
                fade_color = QColor(self._hover_bg_color)
                fade_color.setAlpha(fade_alpha)
                painter.fillRect(r, fade_color)
        elif hovered:
            painter.fillRect(r, self._hover_bg_color)

        if book.path == self._playing_path:
            import math
            if self._is_playing:
                alpha = int(120 + 135 * (0.5 + 0.5 * math.sin(self._pulse_phase * 2 * math.pi)))
            else:
                alpha = 255
            stripe_color = QColor(self._color_accent)
            stripe_color.setAlpha(alpha)
            painter.fillRect(QRect(r.x(), r.y(), ACTIVE_BOOK_STRIPE_WIDTH, r.height()), stripe_color)

        pos, dur, dur_disp, pct, has_progress, speed = self._resolve_playback(book, live_pos, live_dur)

        # Time column width
        TIME_W    = fm.horizontalAdvance("-00:00:00") + 2
        LEFT_PAD  = 4
        RIGHT_PAD = 4
        AVAILABLE = option.rect.width() - LEFT_PAD - RIGHT_PAD - TIME_W

        AUTHOR_BASE = 100
        TITLE_CM    = 4
        BUFFER      = 4

        title  = book.title  or ""
        author = book.author or ""

        title_text_w  = fm.horizontalAdvance(title)
        author_text_w = fm.horizontalAdvance(author)

        author_w     = min(author_text_w + BUFFER, AUTHOR_BASE)
        title_max_lw = AVAILABLE - author_w

        if author_text_w + BUFFER > AUTHOR_BASE:
            spare        = max(0, title_max_lw - (title_text_w + TITLE_CM))
            author_w     = min(author_text_w + BUFFER, AUTHOR_BASE + spare)
            title_max_lw = AVAILABLE - author_w

        title_avail = title_max_lw - TITLE_CM

        ew = fm.horizontalAdvance("…")
        title_elided  = title_text_w  - title_avail >= ew
        author_elided = author_text_w - author_w    >= ew

        disp_title  = fm.elidedText(title,  Qt.ElideRight, title_avail) if title_elided  else title
        disp_author = fm.elidedText(author, Qt.ElideRight, author_w)    if author_elided else author

        # Layout geometry derived from option.rect
        left       = r.x() + LEFT_PAD + TITLE_CM
        mid        = left + title_avail
        right      = r.x() + LEFT_PAD + AVAILABLE
        title_rect = QRect(left, r.y(), title_max_lw +8, r.height()) # +8 prevents clipping with still some separation
        author_rect = QRect(mid, r.y(), author_w, r.height())
        time_rect  = QRect(right, r.y(), TIME_W, r.height())

        local_x       = self._hover_pos.x() - r.x()
        expand_title  = hovered and (left - r.x() <= local_x < mid - r.x()) and title_elided
        expand_author = hovered and (mid - r.x() <= local_x < right - r.x()) and author_elided
        full_rect     = QRect(left, r.y(), AVAILABLE - TITLE_CM, r.height())

        if expand_title:
            self._set_font(painter, mode=self._view_mode, field="title")
            painter.setPen(self._color_title)
            painter.drawText(full_rect, Qt.AlignLeft | Qt.AlignVCenter, title)
        elif expand_author:
            self._set_font(painter, mode=self._view_mode, field="author")
            painter.setPen(self._color_author)
            painter.drawText(full_rect, Qt.AlignRight | Qt.AlignVCenter, author)
        else:
            self._set_font(painter, mode=self._view_mode, field="title")
            painter.setPen(self._color_title)
            painter.drawText(title_rect, Qt.AlignLeft | Qt.AlignVCenter, disp_title)
            self._set_font(painter, mode=self._view_mode, field="author")
            painter.setPen(self._color_author)
            painter.drawText(author_rect, Qt.AlignRight | Qt.AlignVCenter, disp_author)

        # Time column — single value, right-aligned; toggle switches elapsed/remaining
        self._set_font(painter, mode=self._view_mode, field="total")
        painter.setPen(self._color_total)
        if has_progress:
            time_str = f"-{self._fmt((dur - pos) / speed)}" if show_rem else self._fmt(dur_disp)
        else:
            time_str = self._fmt(dur_disp)
        painter.drawText(time_rect, Qt.AlignRight | Qt.AlignVCenter, time_str)

    # ── Drawing helpers ─────────────────────────────────────────────────────

    def _get_sized_cover(self, book, cover: QPixmap, target_w: int, target_h: int) -> QPixmap:
        """Returns `cover` pre-scaled close to target_w×target_h (device pixels), aspect
        preserved (NOT expanded/cropped — _draw_cover's square/crop/letterbox branches all
        derive their own crop/inset math from the source's actual proportions, so this must
        stay a plain bounded fit, same as KeepAspectRatio). Cached per (book_id, target size).
        Only shrinks — never upscales a smaller source, which would soften it further."""
        dpr = cover.devicePixelRatio() or 1.0
        dev_w = max(1, round(target_w * dpr))
        dev_h = max(1, round(target_h * dpr))
        key = (book.id, dev_w, dev_h)
        sized = self._sized_cover_cache.get(key)
        if sized is not None:
            return sized
        if cover.width() <= dev_w and cover.height() <= dev_h:
            sized = cover
        else:
            # Expand slightly past the bound (scaled to the larger of the two ratios) so the
            # later crop/letterbox math in _draw_cover still has enough pixels on both axes —
            # a plain bounded KeepAspectRatio fit can leave one axis short of target.
            scale = max(dev_w / cover.width(), dev_h / cover.height())
            new_w = max(1, round(cover.width() * scale))
            new_h = max(1, round(cover.height() * scale))
            sized = self._lanczos_scale(cover, new_w, new_h)
            sized.setDevicePixelRatio(dpr)
        self._sized_cover_cache[key] = sized
        return sized

    @staticmethod
    def _lanczos_qimage(src: QImage, w: int, h: int) -> QImage:
        """The actual PIL LANCZOS+UnsharpMask scale, QImage -> QImage. THREAD-SAFE:
        touches only QImage (a pure raster container, safe off the GUI thread) and PIL
        — deliberately NO QPixmap, so this can run on a CoverLoaderWorker thread to warm
        _sized_cover_cache without blocking the main thread (see the idle-preloader
        sized-warming path). The QImage -> QPixmap conversion is a separate main-thread
        step (see _lanczos_scale, which is the thin main-thread tail around this).

        Format_RGBA8888 before constBits() is mandatory (tightly-packed, no row padding)
        and must not be reordered — see scanner.py's identical conversion.

        LANCZOS is mathematically more correct than bilinear but, unlike Qt's
        SmoothTransformation (bilinear), doesn't ring/overshoot at edges — on flat-color
        graphic covers that overshoot is exactly what reads as "punchy" contrast, so a
        straight LANCZOS swap measurably improves text legibility while looking *less*
        crisp on high-contrast art (confirmed by user A/B at real cell size). A mild
        UnsharpMask after the resize restores some of that edge punch without giving up
        LANCZOS's cleaner text rendering — applied on the RGB channels only, alpha passed
        through untouched so cover edges/transparency aren't affected. Strength is
        deliberately conservative (percent=25): an earlier percent=60 pass was confirmed by
        the user to look "cartoonish"/HDR-filtered — visible haloing on photographic
        gradients (skies, faces) where LANCZOS leaves no real edge for the mask to find, so
        it amplifies noise instead. Do not raise percent without re-checking against
        photographic covers, not just flat-color graphic ones — the latter tolerates much
        more sharpening before artifacts become visible."""
        qimg = src.convertToFormat(QImage.Format.Format_RGBA8888)
        pil_img = Image.frombuffer(
            "RGBA", (qimg.width(), qimg.height()),
            bytes(qimg.constBits()), "raw", "RGBA", 0, 1,
        )
        pil_img = pil_img.resize((max(1, w), max(1, h)), Image.Resampling.LANCZOS)
        r, g, b, a = pil_img.split()
        sharpened = Image.merge("RGB", (r, g, b)).filter(
            ImageFilter.UnsharpMask(radius=0.8, percent=25, threshold=2)
        )
        pil_img = Image.merge("RGBA", (*sharpened.split(), a))
        return QImage(
            pil_img.tobytes(), pil_img.width, pil_img.height, QImage.Format.Format_RGBA8888
        ).copy()

    @staticmethod
    def _lanczos_scale(cover: QPixmap, w: int, h: int) -> QPixmap:
        """Main-thread tail: QPixmap -> QPixmap around the thread-safe _lanczos_qimage.
        Used by _get_sized_cover on the paint path. The single implementation of the scale
        logic lives in _lanczos_qimage — this only bridges QPixmap<->QImage (a GUI-thread
        operation). Do NOT call this off-thread; call _lanczos_qimage there instead."""
        return QPixmap.fromImage(BookDelegate._lanczos_qimage(cover.toImage(), w, h))

    def evict_sized_cover(self, book_id: int) -> None:
        """Drop all cached pre-scaled pixmaps for a book — call whenever its source
        cover in _cover_cache is replaced or evicted, else stale sizes linger."""
        stale = [k for k in self._sized_cover_cache if k[0] == book_id]
        for k in stale:
            del self._sized_cover_cache[k]

    def _draw_cover(self, painter, rect: QRect, cover, book, *, square: bool, bg: QColor = None):
        painter.fillRect(rect, bg if bg is not None else QColor(13, 0, 26))

        if cover and not cover.isNull():
            cover = self._get_sized_cover(book, cover, rect.width(), rect.height())
            if square:
                # Center-crop to fill rect
                src_w, src_h = cover.width(), cover.height()
                side = min(src_w, src_h)
                src_rect = QRect(
                    (src_w - side) // 2,
                    (src_h - side) // 2,
                    side, side
                )
                painter.drawPixmap(rect, cover, src_rect)
            else:
                pw, ph = cover.width(), cover.height()
                if pw > 0 and ph > 0:
                    cell_ratio  = rect.width()  / rect.height()  if rect.height()  > 0 else 1.0
                    cover_ratio = pw / ph
                    ratio_diff = abs(cover_ratio - cell_ratio) / cell_ratio if cell_ratio > 0 else 1.0
                    if ratio_diff < 0.02:
                        # Near-identical ratio — stretch to fill exactly, distortion imperceptible
                        painter.drawPixmap(rect, cover, cover.rect())
                    elif ratio_diff < 0.08:
                        # Close enough — crop to fill (KeepAspectRatioByExpanding)
                        scale = max(rect.width() / pw, rect.height() / ph)
                        sw = int(pw * scale)
                        sh = int(ph * scale)
                        sx = (sw - rect.width())  // 2
                        sy = (sh - rect.height()) // 2
                        src_rect = QRect(
                            int(sx / scale), int(sy / scale),
                            int(rect.width()  / scale), int(rect.height() / scale)
                        )
                        painter.drawPixmap(rect, cover, src_rect)
                    else:
                        # Letterbox — KeepAspectRatio, centred
                        scale = min(rect.width() / pw, rect.height() / ph)
                        dw = int(pw * scale)
                        dh = int(ph * scale)
                        dx = rect.x() + (rect.width()  - dw) // 2
                        dy = rect.y() + (rect.height() - dh) // 2
                        painter.drawPixmap(QRect(dx, dy, dw, dh), cover, cover.rect())
        else:
            # Placeholder: themed Fabulor logo with a 1px border, centered on the received rect.
            # The border is drawn inside the canvas (adjusted(0,0,-1,-1)), so it does not grow rect.
            pm = self._placeholder_pixmap(rect.width(), rect.height())
            if not pm.isNull():
                painter.drawPixmap(rect.x(), rect.y(), pm)

    def _placeholder_pixmap(self, w: int, h: int) -> QPixmap:
        """Cached bordered-logo placeholder sized to w×h. Cache cleared on theme change.
        Used by 1-/2-per-row where the logo fills the whole cover rect with its own border."""
        if w <= 0 or h <= 0:
            return QPixmap()
        key = ("bordered", self._placeholder_color, w, h)
        pm = self._placeholder_cache.get(key)
        if pm is None:
            icon_size = int(min(w, h) * 0.88)
            pm = render_logo_placeholder_bordered(self._placeholder_color, icon_size, w, h)
            self._placeholder_cache[key] = pm
        return pm

    def _draw_placeholder_logo(self, painter, rect: QRect) -> None:
        """Draw the themed logo (no border) centered within rect. Used by the 3-per-row/Square
        no-cover layout, where the border frames the whole cell separately."""
        if rect.width() <= 0 or rect.height() <= 0:
            return
        icon_size = max(1, int(min(rect.width(), rect.height()) * 0.88))
        key = ("logo", self._placeholder_color, icon_size)
        pm = self._placeholder_cache.get(key)
        if pm is None:
            pm = render_logo_placeholder(self._placeholder_color, icon_size)
            self._placeholder_cache[key] = pm
        if pm.isNull():
            return
        dx = rect.x() + (rect.width() - pm.width()) // 2
        dy = rect.y() + (rect.height() - pm.height()) // 2
        painter.drawPixmap(dx, dy, pm)

    def _draw_hover_overlay(self, painter, cover_rect: QRect, book, show_rem, live_pos, live_dur, *, large: bool):
        from PySide6.QtGui import QLinearGradient, QBrush

        pos, dur, dur_disp, pct, has_progress, speed = self._resolve_playback(book, live_pos, live_dur)

        overlay_mode = "2 per row" if large else "3 per row"

        # Measure content height to size overlay precisely
        BAR_H = 6
        HPAD  = 3
        VPAD  = 6

        self._set_font(painter, mode=overlay_mode, field="elapsed")
        fm_time = painter.fontMetrics()

        if has_progress:
            # time row + 2px gap + bar row, plus VPAD top and bottom
            oh_full = VPAD + fm_time.height() + 8 + BAR_H + VPAD
        else:
            # just bar-row height centred on total text, plus VPAD top and bottom
            self._set_font(painter, mode=overlay_mode, field="total")
            fm_total = painter.fontMetrics()
            oh_full = VPAD + max(BAR_H, fm_total.height()) + VPAD

        oh_full = max(oh_full, int(cover_rect.height() * 0.18))  # never shrink below ~18%

        # full_rect is sized/positioned exactly as before this fix — it is the coordinate
        # space all content (text baselines, bar rect) is computed against below, so no
        # drawn element moves from where it used to render. Only the box we actually paint
        # (overlay_rect) is cropped shorter at the top, removing the unused leading space
        # that font line-height reserves above the real glyph ink — the bottom margin was
        # already correct (geometric, not font-based) on both branches and is untouched.
        full_rect = QRect(cover_rect.x(), cover_rect.bottom() - oh_full + 1, cover_rect.width(), oh_full)
        inner = full_rect.adjusted(HPAD, VPAD, -HPAD, -VPAD)

        if has_progress:
            # Topmost content is the time row's baseline (computed the same way the paint
            # code below computes it) — find its ink-top directly rather than estimating
            # leading from font metrics, so the crop is exact regardless of font/string.
            bar_y_probe  = inner.bottom() - BAR_H
            time_y_probe = max(inner.y(), bar_y_probe - 4 - fm_time.height())
            ink_top = time_y_probe + fm_time.ascent() + fm_time.tightBoundingRect("0").top()
        else:
            # Must mirror the bottom-anchored formula used in the actual draw below exactly,
            # or the crop and the real content position disagree.
            ink_bottom_probe = fm_total.tightBoundingRect("0").bottom()
            no_prog_y_probe = inner.bottom() - ink_bottom_probe
            ink_top = no_prog_y_probe + fm_total.tightBoundingRect("0").top()

        desired_overlay_top = ink_top - VPAD
        oh = max(cover_rect.bottom() - desired_overlay_top + 1, BAR_H + 2 * VPAD)
        oh = min(oh, oh_full)
        overlay_rect = QRect(cover_rect.x(), cover_rect.bottom() - oh + 1, cover_rect.width(), oh)

        # Semi-transparent gradient background
        grad = QLinearGradient(overlay_rect.topLeft(), overlay_rect.bottomLeft())
        grad.setColorAt(0.0, QColor(0, 0, 0, 180))
        grad.setColorAt(1.0, QColor(0, 0, 0, 240))
        painter.fillRect(overlay_rect, QBrush(grad))

        if has_progress:
            # Rows bottom-up: bar at inner.bottom(), time row above it
            bar_y  = inner.bottom() - BAR_H
            time_y = bar_y - 4 - fm_time.height()
            time_y = max(inner.y(), time_y)

            # Time row
            elapsed_str = self._fmt(pos / speed)
            right_str   = f"-{self._fmt((dur - pos) / speed)}" if show_rem else self._fmt(dur_disp)

            self._set_font(painter, mode=overlay_mode, field="elapsed")
            fm_time = painter.fontMetrics()
            painter.setPen(self._color_elapsed)
            painter.drawText(inner.x(), time_y + fm_time.ascent(), elapsed_str)

            self._set_font(painter, mode=overlay_mode, field="total")
            fm_total = painter.fontMetrics()
            right_w  = fm_total.horizontalAdvance(right_str)
            painter.setPen(self._color_total)
            painter.drawText(inner.right() - right_w, time_y + fm_total.ascent(), right_str)

            # Bar + percentage on same row, percentage right-aligned
            pct_str = f"{int(pct * 100)}%"
            self._set_font(painter, mode=overlay_mode, field="percentage")
            fm_pct = painter.fontMetrics()
            pct_w  = fm_pct.horizontalAdvance(pct_str)
            bar_w  = max(10, inner.width() - pct_w - 4)
            bar_rect = QRect(inner.x(), bar_y, bar_w, BAR_H)
            self._draw_progress_bar(painter, bar_rect, pct)

            pct_y = bar_y + (BAR_H - fm_pct.height()) // 2 + fm_pct.ascent()
            painter.setPen(self._color_pct)
            painter.drawText(inner.right() - pct_w, pct_y, pct_str)

        else:
            # No progress — total duration bottom-anchored on tight ink bounds so its visual
            # bottom margin matches the has_progress bar's flush VPAD margin (both 6px), rather
            # than landing ~2px short from vertical centring.
            self._set_font(painter, mode=overlay_mode, field="total")
            fm_total = painter.fontMetrics()
            dur_str   = self._fmt(dur_disp)
            dur_w     = fm_total.horizontalAdvance(dur_str)
            ink_bottom = fm_total.tightBoundingRect(dur_str).bottom()
            no_prog_y = inner.bottom() - ink_bottom
            painter.setPen(self._color_total)
            painter.drawText(inner.right() - dur_w, no_prog_y, dur_str)

    def _draw_progress_bar(self, painter, rect: QRect, pct: float):
        # Background track
        painter.fillRect(rect, QColor(self._pg_bg))
        # Fill
        fill_w = int(rect.width() * pct)
        if fill_w > 0:
            fill_rect = QRect(rect.x(), rect.y(), fill_w, rect.height())
            painter.fillRect(fill_rect, QColor(self._pg_fill))

    # ── Utilities ───────────────────────────────────────────────────────────

    def _time_label_rect(self, option, index) -> "QRect | None":
        """Returns the hit-testable rect for the time/remaining label."""
        if self._view_mode == "1 per row":
            r = option.rect
            # Right side of the time row, matching _paint_one_per_row layout
            fm_h = 20  # approximate
            y = r.bottom() - 4 - 6 - 4 - fm_h
            return QRect(r.right() - 70, r.y() + y - r.y(), 66, fm_h)
        elif self._view_mode in ("2 per row", "3 per row", "Square"):
            # Approximate overlay height: VPAD(6) + time_row(~16) + 8 + bar(6) + VPAD(6) = ~42px
            r = option.rect
            cover_rect = self._cover_rect(r)
            oh = 42
            overlay_rect = QRect(cover_rect.x(), cover_rect.bottom() - oh + 1, cover_rect.width(), oh)
            # Hit zone: right portion of the time row only (total/remaining label), HPAD=3 inset
            HPAD = 3
            VPAD = 6
            BAR_H = 6
            time_h = 16
            bar_y  = overlay_rect.y() + oh - VPAD - BAR_H
            time_y = bar_y - 4 - time_h
            px, bold = FONT_SIZES.get(self._view_mode, {}).get("total", (12, False))
            f = QFont(option.font)
            f.setPixelSize(px)
            f.setBold(bold)
            hit_w = QFontMetrics(f).horizontalAdvance("-00h 00m") + 2
            return QRect(overlay_rect.right() - HPAD - hit_w, time_y, hit_w, time_h)
        elif self._view_mode == "List":
            r      = option.rect
            fm     = option.fontMetrics
            time_w = fm.horizontalAdvance("-00:00:00") + 2
            return QRect(r.right() - 4 - time_w, r.y(), time_w, r.height())
        return None

    def _filterable_field_at(self, path: str, pos: "QPoint") -> Optional[str]:
        """Returns 'author'/'narrator'/'year' if pos hits that field's actual rendered text
        (not its full layout slot) for the given book path in 1-/2-per-row mode, else None.
        This is the field-level hit-test; _field_filter_target_at layers segment resolution
        on top for multi-value author/narrator."""
        rects = self._scroll_field_rects.get(path, {})
        for field in ("author", "narrator", "year"):
            if field not in rects:
                continue
            fx, fy, fw, fh, full_w = rects[field]
            hit_w = min(full_w, fw)
            if fx <= pos.x() < fx + hit_w and fy <= pos.y() < fy + fh:
                return field
        return None

    def _field_filter_target_at(self, book, pos: "QPoint"):
        """Resolve a viewport position to the (field, value) a click would filter on, or None
        if pos is not a click target. Single source of truth for BOTH the click grab
        (editorEvent) and the hand-cursor decision (LibraryPanel.eventFilter / scroll-tick
        refresh) so they can never diverge. For multi-value author/narrator, value is the
        single name under the cursor; a position in the separator gap between names owns no
        segment and returns None (dead zone → default cursor, click falls through to normal
        card selection). year and single-value fields return the whole value."""
        field = self._filterable_field_at(book.path, pos)
        if not field:
            return None
        value = getattr(book, field, None)
        if not value:
            return None
        value = str(value)
        if field in ("author", "narrator"):
            # Multi-value: require the point to land on an actual name, not the gap between.
            # (_segment_bounds is empty for single-value, so this only gates multi-value.)
            if self._segment_bounds(value, field):
                seg = self._segment_under_point(book.path, field, value, pos)
                if not seg:
                    return None  # over a separator gap — not a target
                value = seg[0]
        return (field, value)

    # ── Segment-aware hit-testing for multi-value author/narrator click-to-filter ──
    # Clicking one name in "Feist, Wurts" grabs just that name. The separators (', ' etc.)
    # are dead zones: a click there resolves to no segment, so it is NOT a filter target and
    # falls through to normal card selection (same as clicking blank card space). There is no
    # hover affordance beyond the cursor shape — no underline, no color swap.

    @staticmethod
    def _split_field_value(value: str) -> list:
        """Approximate split of a multi-value author/narrator string into segments.
        Splits on ',', ';', ' and ', ' & ' (word variants case-insensitive), trims each,
        drops empties. No word-boundary precision for names that contain 'and' as a substring
        of a word — accepted approximation."""
        import re
        if not value:
            return []
        parts = re.split(r'\s*,\s*|\s*;\s*|\s+and\s+|\s+&\s+', value, flags=re.IGNORECASE)
        return [p.strip() for p in parts if p.strip()]

    def _field_font_metrics(self, field: str) -> "QFontMetrics":
        """QFontMetrics for a field in the current view mode, matching _set_font's sizing.
        Built without a painter so the hit-test can measure text off the paint cycle."""
        size, bold = FONT_SIZES.get(self._view_mode, {}).get(field, (13, False))
        f = QFont()
        f.setPixelSize(size)
        f.setBold(bold)
        return QFontMetrics(f)

    def _segment_bounds(self, value: str, field: str) -> list:
        """List of (segment_text, start_px, width_px) measured against the ORIGINAL string
        so separator widths are exact — start_px is fm.horizontalAdvance(value[:idx]) at each
        segment's real index in value, not a reconstructed ', '-joined position. Empty list
        if fewer than 2 segments."""
        segs = self._split_field_value(value)
        if len(segs) < 2:
            return []
        fm = self._field_font_metrics(field)
        out = []
        search_from = 0
        for seg in segs:
            idx = value.find(seg, search_from)
            if idx < 0:
                continue
            start_px = fm.horizontalAdvance(value[:idx])
            width_px = fm.horizontalAdvance(seg)
            out.append((seg, start_px, width_px))
            search_from = idx + len(seg)
        return out

    def _segment_under_point(self, book_path: str, field: str, value: str, viewport_pos):
        """Which segment of a multi-value field is under viewport_pos right now, accounting
        for the live scroll offset (0 when at rest / not scrolling) and clipping to the field's
        on-screen slot. Returns (seg_text, seg_start_px_in_value, seg_width_px) or None if the
        field isn't multi-segment or the point misses every visible segment — INCLUDING a point
        in the separator gap between two names, which owns no segment and is therefore a dead
        zone (no filter, cursor stays default). Works whether the marquee is moving or still."""
        rects = self._scroll_field_rects.get(book_path, {})
        if field not in rects:
            return None
        fx, fy, fw, fh, _ = rects[field]
        # Offset 0 when the field isn't currently scrolling (drawn at its natural x).
        state = self._scroll_state.get((book_path, field))
        offset = int(state[0]) if state is not None else 0
        # Vertical gate: same slot y-band the whole field uses.
        if not (fy <= viewport_pos.y() < fy + fh):
            return None
        px = viewport_pos.x()
        for seg, start_px, width_px in self._segment_bounds(value, field):
            # On-screen span, in viewport coords: field left + scroll offset + segment start.
            screen_x = fx + offset + start_px
            # Clip to the field slot — a segment scrolled past either edge isn't hittable.
            lo = max(screen_x, fx)
            hi = min(screen_x + width_px, fx + fw)
            if lo < hi and lo <= px < hi:
                return (seg, start_px, width_px)
        return None

    def _cover_rect(self, r: QRect) -> QRect:
        if self._view_mode == "1 per row":
            return QRect(r.x() + 4, r.y() + 4, 100, 151)
        elif self._view_mode == "2 per row":
            return QRect(r.x() + 13, r.y() + 8, 113, 172)
        else:
            return QRect(r.x() + 2, r.y() + 2, r.width() - 4, r.height() - 4)

    def cover_cell_size(self) -> Optional[tuple]:
        """Logical (w, h) of the cover RECT drawn for the current view mode — the exact
        target_w/target_h that _draw_cover passes to _get_sized_cover — so the idle
        preloader can pre-scale to the same key. Returns None for modes that draw no cover
        via _get_sized_cover (List).

        Deterministic because the grid view is fixed-width (300px window) with
        setGridSize == sizeHint == ITEM_DIMENSIONS[mode], so option.rect at paint time is
        exactly the mode's cell size — no view stretching. The fixed-size modes (1/2 per
        row) use constant cover rects independent of the cell. Keep this in lockstep with
        _paint_grid_cell (r.width()-4, r.height()-4), _paint_one_per_row (100×151), and
        _paint_two_per_row (113×172): if any of those cover-rect formulas change, this must
        change with it, or preloaded sized entries will key on a stale size and silently
        never be hit at paint time."""
        mode = self._view_mode
        if mode == "1 per row":
            return (100, 151)
        if mode == "2 per row":
            return (113, 172)
        if mode in ("3 per row", "Square"):
            dim = ITEM_DIMENSIONS[mode]
            # _paint_grid_cell: cover_rect = (r.x()+3, r.y()+2, r.width()-4, r.height()-4)
            return (dim["w"] - 4, dim["h"] - 4)
        return None  # List draws no cover via _get_sized_cover

    @staticmethod
    def _fmt(seconds: float) -> str:
        s = int(seconds or 0)
        return f"{s // 3600}:{(s % 3600) // 60:02}:{s % 60:02}"

    @staticmethod
    def _set_font(painter, *, mode: str, field: str):
        size, bold = FONT_SIZES.get(mode, {}).get(field, (13, False))
        f = QFont(painter.font())
        f.setPixelSize(size)
        f.setBold(bold)
        painter.setFont(f)
