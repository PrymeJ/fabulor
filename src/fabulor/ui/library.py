import os
from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QGridLayout, QScrollArea, QFrame, QSizePolicy, QApplication
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

class LibraryPanel(QWidget):
    book_selected = Signal(str)

    def __init__(self, db, player_instance=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.player_instance = player_instance
        self._grid_items = {}
        self._active_workers = set()
        self._initialized = False
        self.setObjectName("library_panel")
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 10, 0, 0)

        header = QLabel("Your Library")
        header.setObjectName("settings_header")
        header.setContentsMargins(15, 0, 0, 5)
        self.main_layout.addWidget(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        self.container = QWidget()
        self.grid = QGridLayout(self.container)
        self.grid.setSpacing(5)
        self.grid.setContentsMargins(10, 10, 10, 10)
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        
        self.scroll.setWidget(self.container)
        self.main_layout.addWidget(self.scroll)

    def refresh(self, force=False):
        if self._initialized and not force:
            return
    
        books = self.db.get_all_books()
        existing_paths = {self._grid_items[p].book_data["path"] 
                         for p in self._grid_items}
        new_paths = {b["path"] for b in books}
        
        # Remove stale
        for path in existing_paths - new_paths:
            self._grid_items[path].deleteLater()
            del self._grid_items[path]
    
        cols = 2 if self.width() < 240 else 3
        pool = QThreadPool.globalInstance()
        
        # Add new only and update layout
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
            
            # Always add/re-add to the grid to maintain correct sorting and layout
            self.grid.addWidget(self._grid_items[path], i // cols, i % cols)

            # Process events every few items to keep the UI responsive and allow the 'X' button to work
            if i % 5 == 0:
                QCoreApplication.processEvents()

        self._initialized = True

    def _on_cover_loaded(self, book_path, pixmap, book_item):
        if not pixmap.isNull():
            book_item.cover_label.setPixmap(pixmap.scaled(
                book_item.cover_label.size(), 
                Qt.KeepAspectRatioByExpanding, 
                Qt.SmoothTransformation
            ))
        else:
            # If still no pixmap, ensure placeholder is visible
            display_title = book_item.book_data.get("title") or "Unknown"
            book_item.cover_label.setText(display_title[:1])
            book_item.cover_label.setProperty("placeholder", True)