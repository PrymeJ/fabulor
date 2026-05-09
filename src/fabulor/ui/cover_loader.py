import os
from PySide6.QtCore import QObject, Signal, QRunnable, Slot
from PySide6.QtGui import QImage

class CoverLoaderSignals(QObject):
    cover_loaded = Signal(int, QImage) # Emits book_id, image
    finished = Signal()

class CoverLoaderWorker(QRunnable):
    """Worker to load covers using QThreadPool to avoid thread exhaustion."""
    def __init__(self, book_data, parent=None):
        super().__init__()
        self.signals = CoverLoaderSignals()
        # Proxy the signals for easier access
        self.cover_loaded = self.signals.cover_loaded
        self.finished = self.signals.finished

        self.book_data = book_data

    @Slot()
    def run(self):
        book_id = self.book_data.id
        cover_source_path = self.book_data.cover_path

        image = QImage()
        if cover_source_path and os.path.exists(cover_source_path):
            image.load(cover_source_path)

        self.cover_loaded.emit(book_id, image)
        self.finished.emit()