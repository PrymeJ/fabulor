"""Ambient auto-scrolling cover art carousel for the no-book state.

Purely decorative: no mouse interaction, no cursor, no key handling. Covers
scroll left at a slow continuous pace, or sit static and centered when there
are too few to fill the strip.
"""
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QTimer, QElapsedTimer
from PySide6.QtGui import QPainter

_COVER_W = 92
_WIDGET_W = 280
_WIDGET_H = 150
_TICK_MS = 33                      # ~30 fps


class CoverCarousel(QWidget):
    def __init__(self, pixmaps, cover_h, gap=4, scroll_speed=15, parent=None):
        """pixmaps: list of QPixmap each already scaled/cropped to (92, cover_h)."""
        super().__init__(parent)
        self._cover_w = _COVER_W
        self._cover_h = cover_h
        self._gap = gap
        self._scroll_speed = scroll_speed
        self._unit = self._cover_w + gap          # pixels per cover slot (= 96)
        self._offset = 0.0                        # float for sub-pixel accumulation
        self.setFixedWidth(_WIDGET_W)
        self.setFixedHeight(_WIDGET_H)

        # One set of covers spans this many pixels (one slot per cover incl. gap).
        n = len(pixmaps)
        self._strip_w = n * self._unit
        # Static mode for a small set that doesn't warrant a scroll (<= 3 covers).
        # A scrolling strip needs >= 2x the visible width to loop seamlessly, which
        # 3 covers (288px) can't sustain, so center them statically instead.
        self._static = n <= 3

        self._timer = None
        self._elapsed = QElapsedTimer()
        self._last_ms = 0

        if self._static:
            # No looping needed — draw the original list centered.
            self._pixmaps = list(pixmaps)
        else:
            # Duplicate so the strip is always >= 2x the visible width for gapless looping.
            self._pixmaps = list(pixmaps) + list(pixmaps)
            self._timer = QTimer(self)
            self._timer.setInterval(_TICK_MS)
            self._timer.timeout.connect(self._tick)
            self._elapsed.start()
            self._timer.start()

    def _tick(self):
        now_ms = self._elapsed.elapsed()
        dt = (now_ms - self._last_ms) / 1000.0
        self._last_ms = now_ms
        self._offset = (self._offset + self._scroll_speed * dt) % self._strip_w
        self.update()

    def stop(self):
        """Stop the scroll timer. Safe to call when in static mode."""
        if self._timer is not None:
            self._timer.stop()

    def start(self):
        """Resume the scroll timer after a stop(). Safe to call when in static mode."""
        if self._timer is not None and not self._timer.isActive():
            # Reset elapsed so dt doesn't spike from accumulated idle time.
            self._elapsed.restart()
            self._last_ms = 0
            self._timer.start()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        bottom_y = self.height()                 # covers sit on this baseline (150)
        y = bottom_y - self._cover_h             # bottom-aligned

        if self._static:
            # Centered static row, no scroll. _pixmaps is the un-duplicated list.
            total_w = len(self._pixmaps) * self._unit
            x_start = (self.width() - total_w) // 2
        else:
            x_start = -int(self._offset)

        for i, pm in enumerate(self._pixmaps):
            x = x_start + i * self._unit
            if x > self.width():
                break                            # past the right edge
            if x + self._cover_w < 0:
                continue                         # before the left edge — skip
            p.drawPixmap(x, y, pm)
