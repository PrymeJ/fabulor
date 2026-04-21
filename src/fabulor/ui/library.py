import os
from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QGridLayout, QScrollArea, QFrame, QSizePolicy, QApplication, QPushButton, QHBoxLayout, QComboBox, QLineEdit, QProgressBar
)
from PySide6.QtCore import QThread, QThreadPool # Added QThreadPool
from PySide6.QtCore import Qt, Signal, QCoreApplication
from PySide6.QtGui import QPixmap

class BookItem(QFrame):
    clicked = Signal(str) # Emits the file path

    def __init__(self, book_data, view_mode="3 per row", player_instance=None, parent=None):
        super().__init__(parent)
        self.book_data = book_data
        self.view_mode = view_mode
        self.setObjectName("book_item")
        self._is_toggling = False
        self._show_remaining = True
        self.setCursor(Qt.PointingHandCursor)
        
        self._build_ui()
        self.update_data(book_data)

    # ---------------- UI BUILD ----------------
    def _clear_layout(self):
        if self.layout():
            while self.layout().count():
                item = self.layout().takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            self.layout().deleteLater()

    def _make_cover(self, w, h):
        label = QLabel()
        label.setFixedSize(w, h)
        label.setStyleSheet("background:#0D001A;")
        label.setAlignment(Qt.AlignCenter)
        label.setContentsMargins(0,0,0,0)
        return label

    def _make_time_row(self):
        row = QHBoxLayout()
        row.setContentsMargins(0,0,0,0)
        row.setSpacing(0)

        self.elapsed_label = QLabel()
        self.elapsed_label.setObjectName("book_item_elapsed")
        self.elapsed_label.setContentsMargins(0,0,0,0)
        self.total_label = QLabel()
        self.total_label.setObjectName("book_item_total")
        self.total_label.setContentsMargins(0,0,0,0)

        # Hardcoded sizes
        if self.view_mode == "1 per row":
            size = 14
        elif self.view_mode == "2 per row":
            size = 13
        else: # 3 per row
            size = 12
        self.elapsed_label.setStyleSheet(f"font-size: {size}px;")
        self.total_label.setStyleSheet(f"font-size: {size}px;")

        row.addWidget(self.elapsed_label)
        row.addStretch()
        row.addWidget(self.total_label)
        return row

    def _make_progress_row(self):
        self.progress_container = QWidget()
        self.progress_container.setFixedHeight(16)
        row = QHBoxLayout(self.progress_container)
        row.setContentsMargins(0,0,0,0)
        row.setSpacing(8)

        if self.view_mode == "1 per row":
            row.addStretch()

        self.progress_outer = QFrame()
        self.progress_outer.setObjectName("book_progress_outer")
        self.progress_inner = QFrame(self.progress_outer)
        self.progress_inner.setObjectName("book_progress_inner")
        self.progress_inner.setFixedHeight(6)

        self.pct_label = QLabel()
        self.pct_label.setObjectName("book_item_percentage")
        self.pct_label.setContentsMargins(0,0,0,0)

        # Hardcoded size
        if self.view_mode == "1 per row":
            size = 14
        elif self.view_mode == "2 per row":
            size = 13
        else: # 3 per row
            size = 12
        self.pct_label.setStyleSheet(f"font-size: {size}px;")

        # Styling and Constraints
        self.progress_outer.setFixedHeight(6)
        if self.view_mode == "3 per row":
            self.progress_outer.setFixedWidth(65)
        elif self.view_mode == "2 per row":
            self.progress_outer.setFixedWidth(84)
        elif self.view_mode == "1 per row":
            self.progress_outer.setFixedWidth(132)
        
        self.pct_label.setFixedWidth(35)
        self.pct_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        row.addWidget(self.progress_outer)
        row.addWidget(self.pct_label)
        return self.progress_container

    def _build_ui(self):
        self._clear_layout()

        mode = self.view_mode

        # -------- 3 PER ROW --------
        if mode == "3 per row":
            self.setFixedSize(96,186)
            layout = QVBoxLayout(self)
            layout.setContentsMargins(3,2,0,0)
            layout.setSpacing(2)

            self.cover_label = self._make_cover(90,140)
            layout.addWidget(self.cover_label)

            self.time_row = self._make_time_row()
            layout.addLayout(self.time_row)

            self.progress_row = self._make_progress_row()
            layout.addWidget(self.progress_row)

        # -------- 2 PER ROW --------
        elif mode == "2 per row":
            self.setFixedSize(140,274)
            layout = QVBoxLayout(self)
            layout.setContentsMargins(13,8,0,0)
            layout.setSpacing(0)

            self.cover_label = self._make_cover(113,172)
            layout.addWidget(self.cover_label, alignment=Qt.AlignLeft)

            self.title_label = QLabel()
            self.title_label.setObjectName("book_item_title")
            self.title_label.setStyleSheet("font-size: 14px;")
            self.author_label = QLabel()
            self.author_label.setObjectName("book_item_author")
            self.author_label.setStyleSheet("font-size: 13px;")

            for lbl in (self.title_label, self.author_label):
                lbl.setContentsMargins(0,0,14,0)

            layout.addWidget(self.title_label)
            layout.addWidget(self.author_label)

            self.time_row = self._make_time_row()
            self.time_row.setContentsMargins(0,0,14,0)
            layout.addLayout(self.time_row)

            self.progress_row = self._make_progress_row()
            self.progress_row.setContentsMargins(0,0,14,0)
            layout.addWidget(self.progress_row)

        # -------- 1 PER ROW --------
        elif mode == "1 per row":
            self.setFixedSize(292,161)
            layout = QHBoxLayout(self)
            layout.setContentsMargins(4,4,4,4)
            layout.setSpacing(8)

            self.cover_label = self._make_cover(100,151)
            layout.addWidget(self.cover_label)

            text_layout = QVBoxLayout()
            text_layout.setSpacing(2)

            self.title_label = QLabel()
            self.title_label.setObjectName("book_item_title")
            self.title_label.setStyleSheet("font-size: 14px;")
            self.author_label = QLabel()
            self.author_label.setObjectName("book_item_author")
            self.author_label.setStyleSheet("font-size: 14px;")
            self.narrator_label = QLabel()
            self.narrator_label.setObjectName("book_item_narrator")
            self.narrator_label.setStyleSheet("font-size: 14px;")
            self.year_label = QLabel()
            self.year_label.setStyleSheet("font-size: 12px;")

            for lbl in (self.title_label, self.author_label, self.narrator_label, self.year_label):
                lbl.setContentsMargins(0,0,0,0)

            text_layout.addWidget(self.title_label)
            text_layout.addWidget(self.author_label)
            text_layout.addWidget(self.narrator_label)
            text_layout.addWidget(self.year_label)

            self.time_row = self._make_time_row()
            text_layout.addLayout(self.time_row)

            self.progress_row = self._make_progress_row()
            text_layout.addWidget(self.progress_row)

            layout.addLayout(text_layout)

        # -------- LIST --------
        else:  # list
            self.setFixedSize(290,28)
            layout = QHBoxLayout(self)
            layout.setContentsMargins(4,4,4,4)
            layout.setSpacing(6)

            self.title_label = QLabel()
            self.title_label.setObjectName("book_item_title")
            self.title_label.setStyleSheet("font-size: 14px;")
            self.title_label.setContentsMargins(4,0,0,0)

            self.author_label = QLabel()
            self.author_label.setObjectName("book_item_author")
            self.author_label.setStyleSheet("font-size: 14px;")
            self.author_label.setFixedWidth(100)
            self.author_label.setAlignment(Qt.AlignRight)
            self.author_label.setContentsMargins(0,0,0,0)

            self.total_label = QLabel()
            self.total_label.setObjectName("book_item_total")
            self.total_label.setStyleSheet("font-size: 14px;")
            self.total_label.setFixedWidth(46)
            self.total_label.setAlignment(Qt.AlignRight)
            self.total_label.setContentsMargins(0,0,0,0)

            layout.addWidget(self.title_label)
            layout.addStretch()
            layout.addWidget(self.author_label)
            layout.addWidget(self.total_label)

        if mode in ("2 per row", "3 per row"):
            self._overlay_has_progress = False
            self.overlay_widget = QWidget(self)
            ovl_layout = QVBoxLayout(self.overlay_widget)
            ovl_layout.setContentsMargins(4, 4, 4, 4)
            ovl_layout.setSpacing(2)
            ovl_layout.addStretch()

            # Top row: elapsed (left) · remaining/total (right). Hidden when no progress.
            self.overlay_time_row = QWidget()
            self.overlay_time_row.setAttribute(Qt.WA_TransparentForMouseEvents)
            time_row_layout = QHBoxLayout(self.overlay_time_row)
            time_row_layout.setContentsMargins(0, 0, 0, 0)
            time_row_layout.setSpacing(0)
            self.overlay_elapsed_label = QLabel()
            self.overlay_remaining_label = QLabel()
            time_row_layout.addWidget(self.overlay_elapsed_label)
            time_row_layout.addStretch()
            time_row_layout.addWidget(self.overlay_remaining_label)
            ovl_layout.addWidget(self.overlay_time_row)

            # Bottom row: progress bar + pct% if progress; total duration centered if no progress.
            # We use a container for progress elements and a separate label for total duration (no progress)
            # and manage their visibility.
            bottom_row = QWidget()
            bottom_row.setAttribute(Qt.WA_TransparentForMouseEvents)
            bottom_layout = QHBoxLayout(bottom_row)
            bottom_layout.setContentsMargins(0, 0, 0, 0)
            bottom_layout.setSpacing(4)
            self.overlay_progress_bar = QProgressBar()
            self.overlay_progress_bar.setObjectName("overlay_progress_bar")
            self.overlay_progress_bar.setFixedHeight(6)
            self.overlay_progress_bar.setTextVisible(False)
            self.overlay_progress_bar.setRange(0, 1000)
            self.overlay_progress_bar.setValue(0)
            self.overlay_pct_label = QLabel()
            self.overlay_pct_label.setStyleSheet("color: white; font-size: 14px; background: transparent;")
            self.overlay_pct_label.setFixedWidth(30)
            self.overlay_pct_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

            # Container for progress bar and percentage
            self.overlay_progress_container = QWidget()
            progress_container_layout = QHBoxLayout(self.overlay_progress_container)
            progress_container_layout.setContentsMargins(0,0,0,0)
            progress_container_layout.setSpacing(4)
            progress_container_layout.addWidget(self.overlay_progress_bar, 1)
            progress_container_layout.addWidget(self.overlay_pct_label)

            # Label for total duration when no progress
            self.overlay_total_duration_label = QLabel()
            self.overlay_total_duration_label.setStyleSheet("color: white; font-size: 14px; background: transparent;")
            self.overlay_total_duration_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

            bottom_layout.addWidget(self.overlay_progress_container)
            bottom_layout.addWidget(self.overlay_total_duration_label)
            ovl_layout.addWidget(bottom_row)
            self.overlay_widget.setStyleSheet(
                "background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 rgba(0,0,0,100), stop:1 rgba(0,0,0,230));"
            )
            self.overlay_time_row.setStyleSheet("background: transparent;")
            bottom_row.setStyleSheet("background: transparent;")
            for lbl in (self.overlay_elapsed_label, self.overlay_remaining_label, self.overlay_pct_label):
                lbl.setStyleSheet("color: white; font-size: 12px; background: transparent;")
            self.overlay_elapsed_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self.overlay_remaining_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

            self.overlay_widget.setAttribute(Qt.WA_TransparentForMouseEvents)
            self.overlay_widget.hide()
            self._reposition_overlay()

    def _reposition_overlay(self):
        if not hasattr(self, 'overlay_widget'):
            return
        cx = self.cover_label.x()
        cy = self.cover_label.y()
        cw = self.cover_label.width()
        ch = self.cover_label.height()
        pct = 0.30 if self._overlay_has_progress else 0.20
        oh = int(ch * pct)
        self.overlay_widget.move(cx, cy + ch - oh)
        self.overlay_widget.resize(cw, oh)

    def _update_progress_bar(self):
        if not hasattr(self, 'overlay_progress_bar'):
            return
        prog = float(self.book_data.get("progress") or 0)
        dur = float(self.book_data.get("duration") or 0)
        pct = (prog / dur) if dur > 0 else 0
        self.overlay_progress_bar.setValue(int(pct * 1000))

    def enterEvent(self, event):
        if hasattr(self, 'overlay_widget'):
            self.overlay_widget.show()
            self.overlay_widget.raise_()
            self._update_progress_bar()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if hasattr(self, 'overlay_widget'):
            self.overlay_widget.hide()
        super().leaveEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self._reposition_overlay()

    def mousePressEvent(self, event):
        self._is_toggling = False
        if event.button() == Qt.LeftButton:
            prog = float(self.book_data.get("progress") or 0)
            dur = float(self.book_data.get("duration") or 0)
            
            if prog > 0 and dur > 0:
                target = None
                # If overlay is visible, it takes precedence for the hit test
                if hasattr(self, 'overlay_widget') and self.overlay_widget.isVisible():
                    target = self.overlay_remaining_label
                elif hasattr(self, 'total_label'):
                    target = self.total_label

                if target:
                    from PySide6.QtCore import QRect
                    hit_rect = QRect(target.mapToGlobal(target.rect().topLeft()), target.size())
                    if hit_rect.contains(event.globalPosition().toPoint()):
                        self._is_toggling = True
                        self._show_remaining = not self._show_remaining
                        self.update_data(self.book_data)
                        event.accept()
                        return
        super().mousePressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Ensure progress inner width is updated when the layout resizes the parent
        if hasattr(self, "progress_inner") and hasattr(self, "progress_outer"):
            prog = float(self.book_data.get("progress") or 0)
            dur = float(self.book_data.get("duration") or 0)
            pct = (prog / dur) if dur > 0 else 0
            w = int(self.progress_outer.width() * pct)
            self.progress_inner.setFixedWidth(w)        
        self._reposition_overlay()

    def update_data(self, book_data):
        """Updates the item's metadata and UI labels."""
        self.book_data = book_data

        title = book_data.get("title") or ""
        author = book_data.get("author") or ""
        narrator = book_data.get("narrator")
        year = book_data.get("year")

        prog = float(book_data.get("progress") or 0)
        dur = float(book_data.get("duration") or 0)
        pct = (prog / dur) if dur > 0 else 0
        speed = float(self.book_data.get("speed") or 1.0)
        has_progress = prog > 0 and dur > 0

        def fmt_time(s):
            s = int(s or 0)
            return f"{s//3600}:{(s%3600)//60:02}:{s%60:02}"

        # title/author
        if hasattr(self, "title_label"):
            self.title_label.setText(title)
        if hasattr(self, "author_label"):
            self.author_label.setText(author)

        # narrator/year visibility
        if hasattr(self, "narrator_label"):
            self.narrator_label.setText(narrator or "")
            self.narrator_label.setVisible(bool(narrator))

        if hasattr(self, "year_label"):
            self.year_label.setText(str(year) if year else "")
            self.year_label.setVisible(bool(year))

        # time row
        if hasattr(self, "elapsed_label"):
            self.elapsed_label.setText(fmt_time(prog))
            self.elapsed_label.setVisible(prog > 0)

        if hasattr(self, "total_label"):
            if has_progress and self._show_remaining:
                self.total_label.setText(f"-{fmt_time((dur - prog) / speed)}")
            else:
                self.total_label.setText(fmt_time(dur / speed))

        # progress
        show_progress = prog > 0
        if hasattr(self, "progress_outer") and hasattr(self, "pct_label"):
            self.progress_outer.setVisible(show_progress)
            self.pct_label.setVisible(show_progress)
            self.pct_label.setText(f"{int(pct*100)}%")

        if hasattr(self, "progress_inner"):
            w = int(self.progress_outer.width() * pct)
            self.progress_inner.setFixedWidth(w)

        if hasattr(self, 'overlay_widget'):

            if has_progress != self._overlay_has_progress:
                self._overlay_has_progress = has_progress
                self._reposition_overlay()

            if has_progress:
                # Show elapsed and remaining/total in the top row
                self.overlay_time_row.setVisible(True)
                if self.view_mode == "2 per row":
                    style = "color: white; font-size: 14px; background: transparent;"
                    self.overlay_elapsed_label.setStyleSheet(style)
                    self.overlay_remaining_label.setStyleSheet(style)
                    self.overlay_pct_label.setStyleSheet(style)

                self.overlay_elapsed_label.setVisible(True)
                self.overlay_remaining_label.setVisible(True)
                remaining_s = (dur - prog) / speed
                total_s = dur / speed
                self.overlay_elapsed_label.setText(fmt_time(prog))
                if self._show_remaining:
                    self.overlay_remaining_label.setText(f"-{fmt_time(remaining_s)}")
                else:
                    self.overlay_remaining_label.setText(fmt_time(total_s))
                self.overlay_remaining_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

                # Show progress bar elements in the bottom row
                self.overlay_progress_container.setVisible(True)
                self.overlay_total_duration_label.setVisible(False) # Hide total duration label
                self.overlay_pct_label.setText(f"{int(pct * 100)}%")
                self._update_progress_bar()
            else:
                self.overlay_time_row.setVisible(False)
                self.overlay_progress_container.setVisible(False) # Hide progress bar elements
                self.overlay_total_duration_label.setVisible(True) # Show total duration label
                if self.view_mode == "2 per row":
                    self.overlay_total_duration_label.setStyleSheet("color: white; font-size: 15px; background: transparent;")

                self.overlay_total_duration_label.setText(fmt_time(dur / speed))
                self.overlay_total_duration_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def set_cover(self, pixmap):
        if not pixmap or pixmap.isNull():
            return
        scaled = pixmap.scaled(
            self.cover_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        self.cover_label.setPixmap(scaled)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self._is_toggling:
                self._is_toggling = False
                return
            self.clicked.emit(self.book_data["path"])
        super().mouseReleaseEvent(event)


class LibraryPanel(QFrame):
    book_selected = Signal(str)
    back_requested = Signal() # Signal to request closing the panel

    def __init__(self, db, config, player_instance=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.config = config
        self.player_instance = player_instance
        self._grid_items = {}
        self._active_workers = set() # Keep track of active cover loader workers
        self._initialized = False
        self.setObjectName("library_panel")
        
        self.main_layout = QVBoxLayout(self) # Main layout for the panel
        self.main_layout.setContentsMargins(0, 0, 0, 0) # Remove top margin to cover the progress bar

        # Top bar for controls (Back button, Sort, Styles, Search)
        self.top_bar_widget = QFrame()
        self.top_bar_widget.setObjectName("library_top_bar") # For specific styling if needed
        self.top_bar_layout = QHBoxLayout(self.top_bar_widget)
        self.top_bar_layout.setContentsMargins(3, 6, 3, 6)
        self.top_bar_layout.setSpacing(0)

        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["Title", "Author", "Last Played", "Progress", "Duration"]) 
        self.sort_combo.setFixedWidth(73) # Increased to prevent clipping
        self.sort_combo.setCurrentText(self.config.get_library_sort_key())
        self._sort_ascending = self.config.get_library_sort_ascending()
        self._last_filter_mode = self.sort_combo.currentText()

        self.top_bar_layout.setSpacing(3)
        self.sort_combo.currentTextChanged.connect(self._on_sort_changed)
        self.top_bar_layout.addWidget(self.sort_combo)

        self.sort_dir_btn = QPushButton("↑")
        self.sort_dir_btn.setFixedWidth(16)
        self.sort_dir_btn.setFixedHeight(26)
        self.sort_dir_btn.setCheckable(True)
        self.sort_dir_btn.setChecked(not self._sort_ascending)
        self.sort_dir_btn.setText("↑" if self._sort_ascending else "↓")
        self.sort_dir_btn.clicked.connect(self._toggle_sort_direction)
        self.top_bar_layout.insertWidget(1, self.sort_dir_btn)

        self.style_combo = QComboBox()
        self.style_combo.addItems(["1 per row", "2 per row", "3 per row", "List"])
        self.style_combo.setFixedWidth(86) 
        self.style_combo.setCurrentText(self.config.get_library_view_mode())
        self.top_bar_layout.setSpacing(3)
        self.style_combo.currentTextChanged.connect(self._on_view_mode_changed)
        self.top_bar_layout.addWidget(self.style_combo)

        #self.top_bar_layout.addStretch() # Pushes subsequent widgets to the right

        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("search #tag")
        self.search_field.setAlignment(Qt.AlignCenter) 
        self.search_field.setFixedWidth(63)
        self.search_field.setFixedHeight(30)
        self.top_bar_layout.setSpacing(3)
        self.top_bar_layout.addWidget(self.search_field)

        self.back_button = QPushButton("Back")
        self.back_button.setFixedHeight(28)
        self.top_bar_layout.setSpacing(3)
        self.back_button.clicked.connect(self.back_requested.emit)
        self.top_bar_layout.addWidget(self.back_button)

        self.main_layout.addWidget(self.top_bar_widget) # Add the top bar to the main layout

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        self.container = QWidget()
        self.container.setObjectName("library_scroll_contents")
        self.grid = QGridLayout(self.container)
        self.grid.setSpacing(0)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        
        self.scroll.setWidget(self.container)
        self.main_layout.addWidget(self.scroll)

        # Prevent grid expansion by fixing column stretches and adding a spacer column
        for col in range(3):
            self.grid.setColumnStretch(col, 0)
        self.grid.setColumnStretch(3, 1) # Absorbs extra horizontal space

    def refresh(self, force=False):
        if force:
            # Clear all existing items to force rebuild with the new view_mode
            for item in self._grid_items.values():
                item.deleteLater()
            self._grid_items.clear()
        
        if self._initialized and not force:
            # Even if we don't do a full DB refresh, we MUST sync the 
            # live progress of the current book before returning.
            self.update_current_book_progress()
            return

        sort_text = self.sort_combo.currentText()
        # Robustly get the currently playing file from the main window
        main_win = self.parent() if hasattr(self.parent(), 'current_file') else self.window()
        current_file = getattr(main_win, 'current_file', "")

        # Always fetch from DB with a simple title sort; display sorting is handled in-memory
        books = self.db.get_all_books(sort_by="title COLLATE NOCASE ASC")

        # For last played, it will show only books with non-null last_played
        if sort_text == "Last Played":
            books = [b for b in books if b.get("last_played") is not None]

        existing_paths = {self._grid_items[p].book_data["path"] 
                         for p in self._grid_items}
        new_paths = {b["path"] for b in books}
        
        # Remove stale
        for path in list(self._grid_items.keys()):
            if path not in new_paths:
                self._grid_items[path].deleteLater()
                del self._grid_items[path]
        pool = QThreadPool.globalInstance()
        
        # Update existing items or create new ones
        for i, book in enumerate(books):
            path = book["path"]

            # Inject live progress from Config for the active book to ensure 
            # accuracy even if DB sync is still pending.
            if path == current_file:
                book["progress"] = self.config.get_last_position(path)

            if path not in existing_paths:
                item = BookItem(book, view_mode=self.style_combo.currentText(), player_instance=self.player_instance)
                from .cover_loader import CoverLoaderWorker # Import here to avoid circular dependency
                
                worker = CoverLoaderWorker(book, self.player_instance)
                # Keep a reference to prevent garbage collection of the signals object
                self._active_workers.add(worker)
                worker.signals.cover_loaded.connect(lambda bp, pm, book_item=item: self._on_cover_loaded(bp, pm, book_item))
                worker.signals.finished.connect(lambda w=worker: self._active_workers.discard(w))

                item.clicked.connect(self.book_selected.emit)
                self._grid_items[path] = item
                pool.start(worker)
            else:
                self._grid_items[path].update_data(book)
            
        self._initialized = True
        self._sort_items_in_place()
    
    def _on_view_mode_changed(self, mode):
        self.config.set_library_view_mode(mode)
        self.refresh(force=True)

    def _toggle_sort_direction(self):
        self._sort_ascending = not getattr(self, '_sort_ascending', True)
        self.sort_dir_btn.setText("↑" if self._sort_ascending else "↓")
        self._sort_items_in_place(ascending=self._sort_ascending)

    def _on_sort_changed(self):
        sort_text = self.sort_combo.currentText()
        if sort_text == "Last Played" or self._last_filter_mode == "Last Played":
            self.refresh(force=True)
        else:
            self._sort_items_in_place()
        self._last_filter_mode = sort_text

    def _sort_items_in_place(self, ascending=None):
        # Toggle direction if called from button, otherwise keep current
        if ascending is None:
            ascending = getattr(self, '_sort_ascending', True)
        else:
            self._sort_ascending = ascending

        sort_text = self.sort_combo.currentText()
        self.config.set_library_sort_key(sort_text)
        self.config.set_library_sort_ascending(ascending)

        sort_key = sort_text.lower().replace(" ", "_")
        view_mode = self.style_combo.currentText()
        if view_mode == "3 per row":
            cols = 3
        elif view_mode == "2 per row":
            cols = 2
        else:
            cols = 1

        # Numeric fields sort as float, datetime as string (ISO format sorts correctly), text as lower
        numeric_keys = {"progress", "duration"}
        datetime_keys = {"last_played", "date_added"}

        def sort_value(item):
            val = item.book_data.get(sort_key)
            if val is None:
                return (1, 0 if sort_key in numeric_keys else "")
            if sort_key == "progress":
                duration = item.book_data.get("duration") or 1
                return (0, float(val) / float(duration))
            if sort_key in numeric_keys:
                return (0, float(val))
            if sort_key in datetime_keys:
                return (0, str(val))
            return (0, str(val).lower())

        # Split into items with values and items with None to ensure nulls always go last
        items = sorted(
            [i for i in self._grid_items.values() if i.book_data.get(sort_key) is not None],
            key=sort_value,
            reverse=not ascending
        ) + sorted(
            [i for i in self._grid_items.values() if i.book_data.get(sort_key) is None],
            key=sort_value
        )

        self.container.setUpdatesEnabled(False)
        while self.grid.count():
            self.grid.takeAt(self.grid.count() - 1)
            
        is_alternating = view_mode in ["1 per row", "List"]
        
        for i, item in enumerate(items):
            # Apply alternating row property for QSS targeting
            item.setProperty("alt_row", str(i % 2) if is_alternating else "none")
            item.style().unpolish(item)
            item.style().polish(item)
            self.grid.addWidget(item, i // cols, i % cols)
        self.container.setUpdatesEnabled(True)

    def update_current_book_progress(self):
        """Live update for the currently playing book's progress and sorting."""
        if getattr(self, '_is_animating', False):
            return
            
        main_win = self.parent() if hasattr(self.parent(), 'current_file') else self.window()
        current_file = getattr(main_win, 'current_file', "")
        if current_file and current_file in self._grid_items:
            # Sync the in-memory data from the config cache
            live_pos = self.config.get_last_position(current_file)
            item = self._grid_items[current_file]
            item.book_data["progress"] = live_pos
            item.update_data(item.book_data)
            # Only re-sort if currently sorting by progress
            if self.sort_combo.currentText() == "Progress":
                self._sort_items_in_place()

    def _on_cover_loaded(self, book_path, pixmap, book_item):
        # Only attempt to set cover if the BookItem actually has a cover_label (i.e., not in List view)
        if hasattr(book_item, 'cover_label'):
            if not pixmap.isNull():
                book_item.cover_label.setPixmap(pixmap.scaled(
                    book_item.cover_label.size(), 
                    Qt.KeepAspectRatioByExpanding, 
                    Qt.SmoothTransformation
                ))
                book_item.cover_label.setProperty("placeholder", False)
                book_item.cover_label.setText("") 
                book_item.cover_label.style().unpolish(book_item.cover_label)
                book_item.cover_label.style().polish(book_item.cover_label)
            else:
                # If still no pixmap, ensure placeholder is visible
                display_title = book_item.book_data.get("title") or "Unknown"
                book_item.cover_label.setText(display_title[:1])
                book_item.cover_label.setProperty("placeholder", True)