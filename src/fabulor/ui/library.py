import random
from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QGridLayout, QFrame, QPushButton, QHBoxLayout, QComboBox, QLineEdit, QProgressBar, QStyledItemDelegate, QListView,
)
from PySide6.QtCore import QThreadPool, QEvent, QAbstractListModel, QModelIndex, QSize, QTimer, QDateTime
from PySide6.QtCore import Qt, Signal, QCoreApplication, QRect, QPoint
from typing import Optional
from ..models.book import Book
from PySide6.QtGui import QPixmap, QColor, QFont

# View mode: (internal_key, [display_name_options])
ONE_PER_ROW_MODE   = ("1 per row", ["1 Flew Over", "1 Tree", "Ready Player 1", "1, None", "Power of 1", "1st Circle", "1st Law"])
TWO_PER_ROW_MODE   = ("2 per row", ["2 Cities", "2 Towers", "Swim-2-Birds", "2nd Sex", "2nd Sons"])
THREE_PER_ROW_MODE = ("3 per row", ["3 Body", "3 Stigmata", "3 Kingdoms", "Drawing of the 3", "3 Lives", "The 3rd Man", "3rd Policeman", "3 Guineas", "3 Comrades"])
SQUARE_MODE        = ("Square",    ["Washington Sq."])
LIST_MODE          = ("List",      ["Cannery Row"])
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
}

MIN_PROGRESS = 1.0  # seconds — anything under 1 second is treated as zero

PRELOAD_INTERVAL_MS = 50   # ms between preload timer ticks
PRELOAD_BATCH_SIZE  = 3    # covers dispatched per tick

_cover_cache: dict = {}  # module-level singleton {path: QPixmap}, shared by BookModel and idle preloader

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
        "elapsed":    (12, False),
        "total":      (12, False),
        "percentage": (12, False),
    },
    "Square": {
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

    def __init__(self, db, config, player_instance=None, parent=None):
        super().__init__(parent)
        self.db              = db
        self.config          = config
        self.player_instance = player_instance

        self._active_workers = set()
        self._current_theme  = {}
        self._show_start     = None

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

    # ── Model / view setup ───────────────────────────────────────────────────

    def _setup_model_view(self):
        self._book_model = BookModel(parent=self)
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
        self.top_bar_layout.setContentsMargins(3, 6, 3, 6)
        self.top_bar_layout.setSpacing(3)

        self.sort_combo = QComboBox()
        for display, key in [
            ("Title",    "Title"),
            ("Author",   "Author"),
            ("Recent",   "Last Played"),
            ("Progress", "Progress"),
            ("Duration", "Duration"),
            ("Year",     "Year"),
        ]:
            self.sort_combo.addItem(display, key)
        self.sort_combo.setFixedWidth(65)
        self.sort_combo.setFixedHeight(30)
        saved_sort = self.config.get_library_sort_key()
        for i in range(self.sort_combo.count()):
            if self.sort_combo.itemData(i) == saved_sort:
                self.sort_combo.setCurrentIndex(i)
                break
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
        self.search_field.setPlaceholderText("search #tag")
        self.search_field.setFixedWidth(63)
        self.search_field.setFixedHeight(30)
        self.search_field.textChanged.connect(self._on_search_changed)

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
        self._book_model.set_hovered(self._hovered_book_path)
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
                    if book:
                        self._delegate.on_hover_move(book.path, pos)
                    self._list_view.update(idx)
            elif event.type() == QEvent.Type.Leave:
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
        self._apply_view_mode(mode)
        self._book_model.set_hovered(None)

        self._list_view.reset()

        def _after_reset(_attempt=0):
            first_idx = self._book_model.index(0, 0)
            if first_idx.isValid() and self._list_view.visualRect(first_idx).isEmpty() and _attempt < 5:
                QTimer.singleShot(50, lambda: _after_reset(_attempt + 1))
                return
            self._load_visible_covers()

        QTimer.singleShot(0, _after_reset)

    # ── Data / refresh ───────────────────────────────────────────────────────

    def refresh(self, force=False):
        self._resolve_theme_colors()
        books = self.db.get_all_books(sort_by="title", order="ASC")

        for book in books:
            book.speed = self.config.get_book_speed(book.path) or 1.0

        self._book_model.set_books(books)
        self._apply_current_sort_filter()

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

    def _load_visible_covers(self):
        if not self.isVisible():
            return
        # Guard: layout not done yet if item 0 has no visual rect
        first_idx = self._book_model.index(0, 0)
        if not first_idx.isValid() or self._list_view.visualRect(first_idx).isEmpty():
            return
        # Use visualRect to find the true visible row range — indexAt(bottomRight)
        # is unreliable in IconMode (grid) because it lands in inter-cell gutters.
        viewport_rect = self._list_view.viewport().rect()
        row_count = self._book_model.rowCount()
        def _vr(row): return self._list_view.visualRect(self._book_model.index(row, 0))
        lo, hi = 0, row_count - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if _vr(mid).bottom() < viewport_rect.top():
                lo = mid + 1
            else:
                hi = mid
        first_row = lo
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
        in_flight = {getattr(w, '_book_path', None) for w in self._active_workers}
        dispatched = 0
        skipped_cached = 0
        skipped_flight = 0
        for row in range(first_row, last_row + 1):
            index = self._book_model.index(row, 0)
            book  = index.data(ROLE_BOOK)
            if not book:
                continue
            if self._book_model._covers.get(book.path):
                skipped_cached += 1
                continue
            if book.path in in_flight:
                skipped_flight += 1
                continue
            self._trigger_cover_load(book)
            dispatched += 1

    def _trigger_cover_load(self, book):
        from .cover_loader import CoverLoaderWorker
        worker = CoverLoaderWorker(book, self.player_instance)
        worker._book_path = book.path
        self._active_workers.add(worker)
        worker.signals.cover_loaded.connect(self._on_cover_loaded)
        worker.signals.finished.connect(lambda w=worker: self._active_workers.discard(w))
        QThreadPool.globalInstance().start(worker)

    def _on_cover_loaded(self, path, pixmap):
        if pixmap.isNull():
            return
        dpr = self.screen().devicePixelRatio() if self.screen() else 1.0
        pixmap.setDevicePixelRatio(dpr)
        _cover_cache[path] = pixmap  # write to cache directly
        if not getattr(self, '_is_animating', False):
            self._book_model.notify_cover_cached(path)  # emit dataChanged only if not sliding

    # ── Sort / filter ────────────────────────────────────────────────────────

    def _toggle_sort_direction(self):
        self._sort_ascending = not getattr(self, '_sort_ascending', True)
        self.sort_dir_btn.setText("↑" if self._sort_ascending else "↓")
        sort_key  = self.sort_combo.currentData()
        direction = "ascending" if self._sort_ascending else "descending"
        self._book_model.sort_books(SORT_KEY_MAP.get(sort_key, "title"), direction)
        self.config.set_library_sort_ascending(self._sort_ascending)

    def _on_sort_changed(self):
        sort_key  = self.sort_combo.currentData()
        ascending = getattr(self, '_sort_ascending', True)
        direction = "ascending" if ascending else "descending"
        self._book_model.sort_books(SORT_KEY_MAP.get(sort_key, "title"), direction)
        self.config.set_library_sort_key(sort_key)
        self._last_filter_mode = sort_key

    def _on_search_changed(self, text):
        self._book_model.filter_books(text.lower().strip())

    # ── Live progress ────────────────────────────────────────────────────────

    def update_current_book_progress(self):
        if getattr(self, '_is_animating', False):
            return
        if not self.player_instance:
            return

        path = getattr(self.window(), 'current_file', None)
        pos = self.player_instance.time_pos or 0.0
        dur = self.player_instance.duration  or 0.0

        if not path or dur <= 0:
            return

        self._book_model.update_playing_progress(path, pos, dur)

    def set_playing_path(self, path: str) -> None:
        self._delegate.set_playing_path(path)
        self._list_view.viewport().update()

    def set_is_playing(self, playing: bool) -> None:
        self._delegate.set_is_playing(playing)
        self._list_view.viewport().update()

    def set_hover_fade_enabled(self, mode: str) -> None:
        self._delegate.set_hover_fade_enabled(mode)

    # ── Hide ─────────────────────────────────────────────────────────────────

    def _rotate_view_mode_labels(self):
        self.style_combo.blockSignals(True)
        for i, (_, options) in enumerate(VIEW_MODES):
            self.style_combo.setItemText(i, random.choice(options))
        self.style_combo.blockSignals(False)

    # ── Idle preload ─────────────────────────────────────────────────────────

    def start_idle_preload(self):
        if getattr(self, '_preload_timer', None) and self._preload_timer.isActive():
            return  # already running

        # Resume interrupted queue, or build a fresh one
        if not getattr(self, '_preload_queue', None):
            sort_key  = SORT_KEY_MAP.get(self.config.get_library_sort_key(), "title")
            ascending = self.config.get_library_sort_ascending()
            books = self.db.get_all_books(sort_by=sort_key, order="ASC" if ascending else "DESC")
            self._preload_queue = [b for b in books if b.path not in _cover_cache]

        if not self._preload_queue:
            return

        if not getattr(self, '_preload_timer', None):
            self._preload_timer = QTimer(self)
            self._preload_timer.setSingleShot(False)
            self._preload_timer.timeout.connect(self._preload_tick)
        self._preload_timer.setInterval(PRELOAD_INTERVAL_MS)
        self._preload_timer.start()

    def _preload_tick(self):
        if not getattr(self, '_preload_queue', None):
            self._preload_timer.stop()
            return
        from .cover_loader import CoverLoaderWorker
        for _ in range(PRELOAD_BATCH_SIZE):
            if not self._preload_queue:
                break
            book = self._preload_queue.pop(0)
            if book.path in _cover_cache:
                continue
            worker = CoverLoaderWorker(book, self.player_instance)
            worker._book_path = book.path
            worker.signals.cover_loaded.connect(self._on_preload_cover_loaded)
            QThreadPool.globalInstance().start(worker)

    def _on_preload_cover_loaded(self, path, pixmap):
        if pixmap.isNull():
            return
        dpr = self.screen().devicePixelRatio() if self.screen() else 1.0
        pixmap.setDevicePixelRatio(dpr)
        _cover_cache[path] = pixmap
        # If the model is showing this book, notify it
        self._book_model.notify_cover_cached(path)

    def cancel_preload(self):
        if getattr(self, '_preload_timer', None) and self._preload_timer.isActive():
            self._preload_timer.stop()
            # leave _preload_queue intact so start_idle_preload can resume

    def preload_complete(self) -> bool:
        return not getattr(self, '_preload_queue', None)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._load_visible_covers)
        self._progress_timer.start()

    def hideEvent(self, event):
        self._progress_timer.stop()
        super().hideEvent(event)
        self._book_model.set_hovered(None)
        self._rotate_view_mode_labels()


ROLE_BOOK     = Qt.UserRole + 0
ROLE_COVER    = Qt.UserRole + 1
ROLE_HOVERED  = Qt.UserRole + 2
ROLE_SHOW_REM = Qt.UserRole + 3
ROLE_LIVE_POS = Qt.UserRole + 4
ROLE_LIVE_DUR = Qt.UserRole + 5


class BookModel(QAbstractListModel):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._books: list[Book] = []
        self._filtered: list[Book] = []
        self._covers = _cover_cache  # shared singleton — preloader writes here before model exists
        self._show_remaining: dict[str, bool] = {}
        self._live_pos: dict[str, float] = {}
        self._live_dur: dict[str, float] = {}
        self._hovered_path: Optional[str] = None
        self._filter_text: str = ""
        self._sort_field: str = "title"
        self._sort_direction: str = "ascending"

    # ── QAbstractListModel interface ────────────────────────────────────────

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._filtered)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._filtered)):
            return None
        book = self._filtered[index.row()]
        path = book.path

        if role == ROLE_BOOK:
            return book
        if role == ROLE_COVER:
            return self._covers.get(path)
        if role == ROLE_HOVERED:
            return self._hovered_path == path
        if role == ROLE_SHOW_REM:
            return self._show_remaining.get(path, True)
        if role == ROLE_LIVE_POS:
            return self._live_pos.get(path, book.progress or 0.0)
        if role == ROLE_LIVE_DUR:
            return self._live_dur.get(path, book.duration or 0.0)
        if role == Qt.DisplayRole:
            return book.title
        return None

    # ── Data mutation ───────────────────────────────────────────────────────

    def set_books(self, books: list[Book]) -> None:
        self.beginResetModel()
        self._books = list(books)
        self._apply_filter_and_sort()
        self.endResetModel()

    def update_cover(self, path: str, pixmap: QPixmap) -> None:
        self._covers[path] = pixmap
        self._emit_for_path(path)

    def notify_cover_cached(self, path: str) -> None:
        self._emit_for_path(path)

    def update_playing_progress(self, path: str, position: float, duration: float) -> None:
        self._live_pos[path] = position if position > MIN_PROGRESS else 0.0
        self._live_dur[path] = duration
        self._emit_for_path(path)

    def toggle_show_remaining(self, path: str) -> None:
        self._show_remaining[path] = not self._show_remaining.get(path, True)
        self._emit_for_path(path)

    def set_hovered(self, path: Optional[str]) -> None:
        previous = self._hovered_path
        self._hovered_path = path
        if previous:
            self._emit_for_path(previous)
        if path:
            self._emit_for_path(path)

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

    # ── Internal ────────────────────────────────────────────────────────────

    def _apply_filter_and_sort(self) -> None:
        text = self._filter_text
        if text:
            books = [
                b for b in self._books
                if text in b.title.lower()
                or text in (b.author or "").lower()
                or text in (b.narrator or "").lower()
            ]
        else:
            books = list(self._books)

        # Filter "Recent" to only show books that have progress
        if self._sort_field == "last_played":
            books = [b for b in books if (b.progress or 0.0) > MIN_PROGRESS]

        reverse = self._sort_direction == "descending"
        field = self._sort_field

        from datetime import datetime as dt
        def sort_key(b):
            if field == "progress":
                pos = b.progress or 0.0
                dur = b.duration or 0.0
                return pos / dur if dur > 0 else 0.0

            val = getattr(b, field, None)
            if val is None:
                if field == "last_played": return dt.min
                # Safeguard: check first book for type hint if available
                first_b = self._books[0] if self._books else None
                if first_b and isinstance(getattr(first_b, field, None), str):
                    return ""
                return 0
            if isinstance(val, str):
                return val.lower()
            return val

        if self._sort_field in ("last_played", "progress"):
            have    = [b for b in books if (b.progress or 0.0) > MIN_PROGRESS]
            missing = [b for b in books if (b.progress or 0.0) <= MIN_PROGRESS]
            have.sort(key=sort_key, reverse=reverse)
            missing.sort(key=lambda b: (b.title or "").lower())
            books = have + missing
        else:
            books.sort(key=sort_key, reverse=reverse)
        self._filtered = books

    def _emit_for_path(self, path: str) -> None:
        for row, book in enumerate(self._filtered):
            if book.path == path:
                idx = self.index(row)
                self.dataChanged.emit(idx, idx, [Qt.DisplayRole])
                return

    def path_to_index(self, path: str) -> Optional[QModelIndex]:
        for row, book in enumerate(self._filtered):
            if book.path == path:
                return self.index(row)
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
        self._view_mode = "3 per row"
        self._alt_row_color = QColor(255, 255, 255, 10)  # overridden by _apply_theme
        self._hover_pos = QPoint()
        self._playing_path = ""
        self._is_playing = False
        self._pulse_phase = 0.0
        self._pulse_timer = QTimer()
        self._pulse_timer.setInterval(40)
        self._pulse_timer.timeout.connect(self._advance_pulse)
        # Scroll state for 1-per-row and 2-per-row
        # (path, field) → [offset, direction, pause_ticks]  direction: -1=left, 1=right
        self._scroll_state: dict    = {}
        self._scroll_hovered_path   = ""
        self._scroll_field_rects: dict = {}  # path → {field: (x, y, w, h, full_text_w)}
        self._scroll_timer = QTimer()
        self._scroll_timer.setInterval(40)
        self._scroll_timer.timeout.connect(self._advance_scroll)
        # Hover fade state — List mode only, user-toggleable
        self._hover_fade_mode = "Off"   # "Slow", "Normal", "Fast", "Off"
        self._list_hovered_path = ""
        self._hover_fade: dict = {}     # path → current alpha (0–255)
        self._hover_fade_timer = QTimer()
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

        self._bg_library     = qc(theme.get('bg_library',         '#1e1e1e'))
        self._grid_bg        = qc(theme.get('library_grid_bg',    theme.get('bg_library', '#1a1a1a')))
        self._row_one        = qc(theme.get('library_row_one',    '#242424'))
        self._row_two        = qc(theme.get('library_row_two',    '#2a2a2a'))
        self._color_title    = qc(theme.get('library_title',      '#ffffff'))
        self._color_author   = qc(theme.get('library_author',     '#aaaaaa'))
        self._color_narrator = qc(theme.get('library_narrator',   '#888888'))
        self._color_elapsed  = qc(theme.get('library_elapsed',    '#aaaaaa'))
        self._color_total    = qc(theme.get('library_total',      '#aaaaaa'))
        self._color_pct      = qc(theme.get('library_percentage', '#888888'))
        self._alt_row_color  = self._row_two
        self._color_accent   = qc(theme.get('accent', '#ffffff'))

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
        if self._view_mode not in ("1 per row", "2 per row"):
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
        if self._view_mode not in ("1 per row", "2 per row"):
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
            vp = getattr(self, '_viewport', None)
            if vp:
                vp.update()

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

        live_pos = index.data(ROLE_LIVE_POS) or 0.0
        live_dur = index.data(ROLE_LIVE_DUR) or 0.0
        if live_pos <= 0 or live_dur <= 0:
            return False

        hit = self._time_label_rect(option, index)
        if hit and hit.contains(event.pos()):
            if event.type() == _QEvent.Type.MouseButtonRelease:
                model.toggle_show_remaining(book.path)
                self.last_event_was_toggle = True
            return True
        return False

    # ── Playback resolution ──────────────────────────────────────────────────

    def _resolve_playback(self, book, live_pos: float, live_dur: float) -> tuple:
        """Returns (pos, dur, dur_disp, pct, has_progress, speed)"""
        has_progress = (book.progress or 0.0) > MIN_PROGRESS
        pos = live_pos if live_pos > 0 else (book.progress or 0.0)
        dur = live_dur if live_dur > 0 else (book.duration or 0.0)
        speed = book.speed or 1.0
        dur_disp = dur / speed
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

        # Zone 1 — bottom block, anchored to r.bottom()
        BAR_H  = 6
        PAD    = 4
        self._set_font(painter, mode=self._view_mode, field="elapsed")
        fm_time = painter.fontMetrics()
        bar_y  = r.bottom() - PAD - BAR_H
        time_y = bar_y - PAD - fm_time.height()

        # Zone 2 — text block fills space above bottom block
        text_y      = r.y() + PAD
        text_bottom = time_y - PAD

        fields = [("title", book.title or "")]
        if book.author:
            fields.append(("author", book.author))
        if book.narrator:
            fields.append(("narrator", book.narrator))
        if book.year:
            fields.append(("year", str(book.year)))

        available_h = text_bottom - text_y
        line_h      = available_h // len(fields) if fields else available_h

        color_map = {
            "title":    self._color_title,
            "author":   self._color_author,
            "narrator": self._color_narrator,
            "year":     self._color_author,
        }
        field_rects = {}
        row_text_y = text_y
        for field, value in fields:
            self._set_font(painter, mode=self._view_mode, field=field)
            fm = painter.fontMetrics()
            full_w = fm.horizontalAdvance(value)
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
            row_text_y += line_h - 2
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
        self._set_font(painter, mode=self._view_mode, field="title")
        fm = painter.fontMetrics()
        title_val = book.title or ""
        title_full_w = fm.horizontalAdvance(title_val)
        field_rects["title"] = (text_x, text_y, text_w, fm.height(), title_full_w)
        painter.setPen(self._color_title)
        title_offset = self._scroll_state.get((book.path, "title"), [None])[0] if (book.path, "title") in self._scroll_state else None
        if title_offset is not None and title_full_w > text_w:
            painter.save()
            painter.setClipRect(QRect(text_x, text_y, text_w, fm.height()))
            painter.drawText(text_x + int(title_offset), text_y + fm.ascent(), title_val)
            painter.restore()
        else:
            painter.drawText(text_x, text_y + fm.ascent(), fm.elidedText(title_val, Qt.ElideRight, text_w))
        text_y += fm.height() + 2

        self._set_font(painter, mode=self._view_mode, field="author")
        fm = painter.fontMetrics()
        author_val = book.author or ""
        author_full_w = fm.horizontalAdvance(author_val)
        field_rects["author"] = (text_x, text_y, text_w, fm.height(), author_full_w)
        painter.setPen(self._color_author)
        author_offset = self._scroll_state.get((book.path, "author"), [None])[0] if (book.path, "author") in self._scroll_state else None
        if author_offset is not None and author_full_w > text_w:
            painter.save()
            painter.setClipRect(QRect(text_x, text_y, text_w, fm.height()))
            painter.drawText(text_x + int(author_offset), text_y + fm.ascent(), author_val)
            painter.restore()
        else:
            painter.drawText(text_x, text_y + fm.ascent(), fm.elidedText(author_val, Qt.ElideRight, text_w))
        self._scroll_field_rects[book.path] = field_rects

        # Hover overlay over cover rect
        if hovered:
            self._draw_hover_overlay(painter, cover_rect, book, show_rem, live_pos, live_dur, large=True)

    def _paint_grid_cell(self, painter, option, index, book, cover, hovered, show_rem, live_pos, live_dur):
        r = option.rect
        painter.fillRect(r, self._grid_bg)
        square = (self._view_mode == "Square")

        # Cover fills cell with 2px margin
        cover_rect = QRect(r.x() + 2, r.y() + 2, r.width() - 4, r.height() - 4)
        self._draw_cover(painter, cover_rect, cover, book, square=square, bg=self._grid_bg)

        if hovered:
            self._draw_hover_overlay(painter, cover_rect, book, show_rem, live_pos, live_dur, large=False)

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

    def _draw_cover(self, painter, rect: QRect, cover, book, *, square: bool, bg: QColor = None):
        painter.fillRect(rect, bg if bg is not None else QColor(13, 0, 26))

        if cover and not cover.isNull():
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
                    if cell_ratio > 0 and abs(cover_ratio - cell_ratio) / cell_ratio < 0.08:
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
            # Placeholder: first letter of title
            painter.setPen(QColor(180, 180, 180))
            f = QFont(painter.font())
            f.setPixelSize(painter.font().pixelSize() + 6 if painter.font().pixelSize() > 0
                           else painter.font().pointSize() + 6)
            f.setBold(True)
            painter.setFont(f)
            painter.drawText(rect, Qt.AlignCenter, (book.title or "?")[:1])

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
            oh = VPAD + fm_time.height() + 8 + BAR_H + VPAD
        else:
            # just bar-row height centred on total text, plus VPAD top and bottom
            self._set_font(painter, mode=overlay_mode, field="total")
            fm_total = painter.fontMetrics()
            oh = VPAD + max(BAR_H, fm_total.height()) + VPAD

        oh = max(oh, int(cover_rect.height() * 0.18))  # never shrink below ~18%
        overlay_rect = QRect(cover_rect.x(), cover_rect.bottom() - oh + 1, cover_rect.width(), oh)

        # Semi-transparent gradient background
        grad = QLinearGradient(overlay_rect.topLeft(), overlay_rect.bottomLeft())
        grad.setColorAt(0.0, QColor(0, 0, 0, 180))
        grad.setColorAt(1.0, QColor(0, 0, 0, 240))
        painter.fillRect(overlay_rect, QBrush(grad))

        inner = overlay_rect.adjusted(HPAD, VPAD, -HPAD, -VPAD)

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
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(inner.x(), time_y + fm_time.ascent(), elapsed_str)

            self._set_font(painter, mode=overlay_mode, field="total")
            fm_total = painter.fontMetrics()
            right_w  = fm_total.horizontalAdvance(right_str)
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
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(inner.right() - pct_w, pct_y, pct_str)

        else:
            # No progress — total duration vertically centred in inner, right-aligned
            self._set_font(painter, mode=overlay_mode, field="total")
            fm_total = painter.fontMetrics()
            dur_str   = self._fmt(dur_disp)
            dur_w     = fm_total.horizontalAdvance(dur_str)
            no_prog_y = inner.y() + (inner.height() - fm_total.height()) // 2 + fm_total.ascent() + 2
            painter.setPen(QColor(255, 255, 255))
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
            # Approximate overlay height: VPAD(5) + time_row(~16) + 2 + bar(6) + VPAD(5) = ~34px
            r = option.rect
            cover_rect = self._cover_rect(r)
            oh = 34
            overlay_rect = QRect(cover_rect.x(), cover_rect.bottom() - oh + 1, cover_rect.width(), oh)
            # Hit zone: the time row at the top of inner (VPAD=5 inset)
            return QRect(overlay_rect.x(), overlay_rect.y() + 5, overlay_rect.width(), 20)
        elif self._view_mode == "List":
            r      = option.rect
            fm     = option.fontMetrics
            time_w = fm.horizontalAdvance("-00:00:00") + 2
            return QRect(r.right() - 4 - time_w, r.y(), time_w, r.height())
        return None

    def _cover_rect(self, r: QRect) -> QRect:
        if self._view_mode == "1 per row":
            return QRect(r.x() + 4, r.y() + 4, 100, 151)
        elif self._view_mode == "2 per row":
            return QRect(r.x() + 13, r.y() + 8, 113, 172)
        else:
            return QRect(r.x() + 2, r.y() + 2, r.width() - 4, r.height() - 4)

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
