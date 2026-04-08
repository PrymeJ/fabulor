from PySide6.QtCore import QObject, Signal, QRunnable, Slot
from PySide6.QtGui import QPixmap

class CoverLoaderSignals(QObject):
    cover_loaded = Signal(str, QPixmap) # Emits book_path, pixmap
    finished = Signal()

class CoverLoaderWorker(QRunnable):
    """Worker to load covers using QThreadPool to avoid thread exhaustion."""
    def __init__(self, book_data, player_instance, parent=None):
        super().__init__()
        self.signals = CoverLoaderSignals()
        # Proxy the signals for easier access
        self.cover_loaded = self.signals.cover_loaded
        self.finished = self.signals.finished
        
        self.book_data = book_data
        self.player_instance = player_instance

    @Slot()
    def run(self):
        book_path = self.book_data["path"]
        cover_source_path = self.book_data.get("cover_path")

        pixmap = QPixmap()
        if cover_source_path:
            pixmap.load(cover_source_path)
        
        self.cover_loaded.emit(book_path, pixmap)
        self.finished.emit()