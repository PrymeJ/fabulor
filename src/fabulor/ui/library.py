import os
from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QGridLayout, QScrollArea, QFrame, QSizePolicy, QApplication, QPushButton, QHBoxLayout, QComboBox, QLineEdit
)
from PySide6.QtCore import QThread, QThreadPool # Added QThreadPool
from PySide6.QtCore import Qt, Signal, QCoreApplication
from PySide6.QtGui import QPixmap

class BookItem(QFrame):
    clicked = Signal(str) # Emits the file path

    def __init__(self, book_data, player_instance=None, parent=None):
        super().__init__(parent)
        self.book_data = book_data
        self.setObjectName("book_item")
        self.setCursor(Qt.PointingHandCursor)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(4)

        # Cover Area (Vertical Rectangle Aspect Ratio)
        self.cover_label = QLabel()
        self.cover_label.setObjectName("book_cover")
        # Approx 1:1.4 aspect ratio for 3-column layout
        self.cover_label.setFixedSize(80, 115) 
        self.cover_label.setAlignment(Qt.AlignCenter)
        
        # Initial placeholder
        display_title = book_data.get("title") or "Unknown"
        self.cover_label.setText(display_title[:1])
        self.cover_label.setProperty("placeholder", True)

        layout.addWidget(self.cover_label, 0, Qt.AlignCenter)

        # Labels
        self.title_label = QLabel(str(book_data.get("title") or "Unknown Title"))
        self.title_label.setObjectName("book_item_title")
        self.title_label.setWordWrap(True)
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setToolTip(self.title_label.text())
        layout.addWidget(self.title_label)

        self.author_label = QLabel(str(book_data.get("author") or "Unknown Author"))
        self.author_label.setObjectName("book_item_author")
        self.author_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.author_label)

        # Optional: Narrator could be added here based on settings
        
        self.setFixedHeight(180)
        self.setFixedWidth(90)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.book_data["path"])

    def update_data(self, book_data):
        """Updates the item's metadata and UI labels."""
        self.book_data = book_data
        title = str(book_data.get("title") or "Unknown Title")
        author = str(book_data.get("author") or "Unknown Author")
        
        self.title_label.setText(title)
        self.title_label.setToolTip(title)
        self.author_label.setText(author)
        
        # Update the placeholder letter if no cover is loaded
        if self.cover_label.property("placeholder"):
            self.cover_label.setText(title[:1])

class LibraryPanel(QFrame):
    book_selected = Signal(str)
    back_requested = Signal() # Signal to request closing the panel

    def __init__(self, db, player_instance=None, parent=None):
        super().__init__(parent)
        self.db = db
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
        self.top_bar_layout.setSpacing(5)

        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["Title", "Author", "Last Played", "Progress", "Duration"]) 
        self.sort_combo.setFixedWidth(80)
        self._sort_ascending = True
        self.top_bar_layout.setSpacing(3)
        self.sort_combo.currentIndexChanged.connect(lambda: self._sort_items_in_place(ascending=getattr(self, '_sort_ascending', True)))
        self.top_bar_layout.addWidget(self.sort_combo)

        self.sort_dir_btn = QPushButton("↑")
        self.sort_dir_btn.setFixedWidth(16)
        self.sort_dir_btn.setFixedHeight(26)
        self.sort_dir_btn.setCheckable(True)
        self.sort_dir_btn.clicked.connect(self._toggle_sort_direction)
        self.top_bar_layout.insertWidget(1, self.sort_dir_btn)

        self.style_combo = QComboBox()
        self.style_combo.addItems(["Grid", "List"])
        self.style_combo.setFixedWidth(80)
        self.top_bar_layout.setSpacing(3)
        self.style_combo.currentTextChanged.connect(lambda: self.refresh(force=True))
        self.top_bar_layout.addWidget(self.style_combo)

        #self.top_bar_layout.addStretch() # Pushes subsequent widgets to the right

        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("search")
        self.search_field.setAlignment(Qt.AlignCenter) 
        self.search_field.setFixedWidth(70)
        self.search_field.setFixedHeight(28)
        self.search_field.setStyleSheet("QLineEdit { font-size: 11px; }")
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
        self.grid = QGridLayout(self.container)
        self.grid.setSpacing(5)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        
        self.scroll.setWidget(self.container)
        self.main_layout.addWidget(self.scroll)

    def refresh(self, force=False):
        if self._initialized and not force:
            return
    
        # Always fetch from DB with a simple title sort; display sorting is handled in-memory
        books = self.db.get_all_books(sort_by="title COLLATE NOCASE ASC")
        existing_paths = {self._grid_items[p].book_data["path"] 
                         for p in self._grid_items}
        new_paths = {b["path"] for b in books}
        
        # Remove stale
        for path in list(self._grid_items.keys()):
            if path not in new_paths:
                self._grid_items[path].deleteLater()
                del self._grid_items[path]
    
        cols = 2 if self.width() < 240 else 3
        pool = QThreadPool.globalInstance()
        
        # Update existing items or create new ones
        for i, book in enumerate(books):
            path = book["path"]
            if path not in existing_paths:
                item = BookItem(book, player_instance=self.player_instance)
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
            
            # Always add/re-add to the grid to maintain correct sorting and layout
            self.grid.addWidget(self._grid_items[path], i // cols, i % cols)

        self._initialized = True

    def _toggle_sort_direction(self):
        self._sort_ascending = not getattr(self, '_sort_ascending', True)
        self.sort_dir_btn.setText("↑" if self._sort_ascending else "↓")
        self._sort_items_in_place(ascending=self._sort_ascending)

    def _sort_items_in_place(self, ascending=None):
        # Toggle direction if called from button, otherwise keep current
        if ascending is None:
            ascending = getattr(self, '_sort_ascending', True)
        else:
            self._sort_ascending = ascending

        sort_key = self.sort_combo.currentText().lower().replace(" ", "_")
        list_mode = self.style_combo.currentText() == "List"
        cols = 1 if list_mode else (3 if self.width() > 280 else 2)

        # Numeric fields sort as float, datetime as string (ISO format sorts correctly), text as lower
        numeric_keys = {"progress", "duration"}
        datetime_keys = {"last_played", "date_added"}

        def sort_value(item):
            val = item.book_data.get(sort_key)
            if val is None:
                return (1, 0 if sort_key in numeric_keys else "")
            if sort_key in numeric_keys:
                return (0, float(val))
            if sort_key in datetime_keys:
                return (0, str(val))
            return (0, str(val).lower())

        # Sort nulls always last by sorting ascending first, then reversing only non-null values
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
        for i, item in enumerate(items):
            self.grid.addWidget(item, i // cols, i % cols)
        self.container.setUpdatesEnabled(True)

    def _on_cover_loaded(self, book_path, pixmap, book_item):
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