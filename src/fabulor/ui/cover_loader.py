import os
from PySide6.QtCore import QObject, Signal, QRunnable, Slot
from PySide6.QtGui import QImage, QPixmap, QPainter

class CoverLoaderSignals(QObject):
    cover_loaded = Signal(int, QImage) # Emits book_id, image
    # Emits book_id, dev_w, dev_h, scaled QImage — the idle preloader's sized-warming
    # path (loads + LANCZOS-scales a cover off-thread; main-thread slot converts to
    # QPixmap and writes _sized_cover_cache). QImage only: no QPixmap crosses threads.
    sized_cover_loaded = Signal(int, int, int, QImage)
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
    """Worker to load covers using QThreadPool to avoid thread exhaustion.

    Two modes:
      - default: load the raw cover QImage from disk, emit `cover_loaded(book_id, image)`.
        Main thread converts to QPixmap and writes _cover_cache.
      - sized (when `sized_target` is given): additionally LANCZOS-scale the loaded image
        to the given device-pixel size OFF-THREAD (QImage only) and emit
        `sized_cover_loaded(book_id, dev_w, dev_h, scaled)`. Main thread converts to QPixmap
        and writes _sized_cover_cache. `sized_target` must be a pre-computed (dev_w, dev_h)
        tuple — DPR is read on the MAIN thread at enqueue time and passed in; the worker
        must never read screen()/DPR itself.
    """
    def __init__(self, book_data, active_cover_path=None, parent=None, sized_target=None):
        super().__init__()
        self.signals = CoverLoaderSignals()
        # Proxy the signals for easier access
        self.cover_loaded = self.signals.cover_loaded
        self.sized_cover_loaded = self.signals.sized_cover_loaded
        self.finished = self.signals.finished

        self.book_data = book_data
        self._active_cover_path = active_cover_path
        self._sized_target = sized_target  # (dev_w, dev_h) or None

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

        if self._sized_target is not None and not image.isNull():
            dev_w, dev_h = self._sized_target
            # Mirror _get_sized_cover's "only shrink" rule: if the source already fits the
            # target box, no scale is needed — the raw pixmap will be used directly at paint
            # time, so don't warm a sized entry (matches _get_sized_cover's `sized = cover`
            # branch, which caches the raw cover under the key; here we simply skip and let
            # the paint-path store it, keeping the worker's job to the expensive case only).
            if image.width() > dev_w or image.height() > dev_h:
                # LANCZOS import is deferred to avoid a circular import at module load
                # (library.py imports this module). Off-thread-safe: QImage + PIL only.
                from .library import BookDelegate
                scale = max(dev_w / image.width(), dev_h / image.height())
                new_w = max(1, round(image.width() * scale))
                new_h = max(1, round(image.height() * scale))
                scaled = BookDelegate._lanczos_qimage(image, new_w, new_h)
                self.sized_cover_loaded.emit(book_id, dev_w, dev_h, scaled)

        self.finished.emit()
