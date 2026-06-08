import os
from PySide6.QtCore import QObject, Signal, QRunnable, Slot
from PySide6.QtGui import QImage, QPixmap, QPainter

class CoverLoaderSignals(QObject):
    cover_loaded = Signal(int, QImage) # Emits book_id, image
    finished = Signal()

def to_grayscale(pixmap: QPixmap) -> QPixmap:
    """Utility to convert a QPixmap to grayscale, preserving the alpha channel.

    Format_Grayscale8 discards alpha — transparent edge pixels get composited
    against black, producing a black fringe on anything with transparency (e.g.
    SVG placeholders with antialiased borders). Instead: get luminance via
    Grayscale8, then re-apply the original alpha channel from the ARGB32 source
    using a QPainter with CompositionMode_DestinationIn."""
    if pixmap.isNull():
        return pixmap
    source = pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    grey = source.convertToFormat(QImage.Format.Format_Grayscale8) \
                 .convertToFormat(QImage.Format.Format_ARGB32)
    # Re-apply the original alpha: paint the alpha mask from source onto grey
    # using DestinationIn, which multiplies destination alpha by source alpha.
    painter = QPainter(grey)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    painter.drawImage(0, 0, source)
    painter.end()
    return QPixmap.fromImage(grey)

class CoverLoaderWorker(QRunnable):
    """Worker to load covers using QThreadPool to avoid thread exhaustion."""
    def __init__(self, book_data, active_cover_path=None, parent=None):
        super().__init__()
        self.signals = CoverLoaderSignals()
        # Proxy the signals for easier access
        self.cover_loaded = self.signals.cover_loaded
        self.finished = self.signals.finished

        self.book_data = book_data
        self._active_cover_path = active_cover_path

    @Slot()
    def run(self):
        book_id = self.book_data.id
        cover_source_path = (
            self._active_cover_path
            if self._active_cover_path is not None
            else self.book_data.cover_path
        )

        image = QImage()
        if cover_source_path and os.path.exists(cover_source_path):
            image.load(cover_source_path)

        self.cover_loaded.emit(book_id, image)
        self.finished.emit()