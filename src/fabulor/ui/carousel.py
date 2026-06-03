"""Ambient auto-scrolling cover art carousel for the no-book state.

Purely decorative: no mouse interaction, no cursor, no key handling. Covers
scroll left at a slow continuous pace, or sit static and centered when there
are too few to fill the strip.
"""
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QTimer, QElapsedTimer
from PySide6.QtGui import QPainter, QColor

def _auto_stripe_line_color(hex_color: str) -> str:
    """Derive a 2px line color from the stripe fill by shifting HSL lightness."""
    c = QColor(hex_color)
    lum = c.lightnessF()
    lum = min(1.0, lum + _LINE_LIGHTNESS_SHIFT) if lum < 0.5 else max(0.0, lum - _LINE_LIGHTNESS_SHIFT)
    result = QColor.fromHslF(c.hslHueF(), c.hslSaturationF(), lum, c.alphaF())
    return result.name()


CAROUSEL_STRIPE_W   = 300   # full window width; bleeds to both edges
CAROUSEL_STRIPE_PAD = 13    # px above and below covers inside the stripe
CAROUSEL_COVER_W    = 96    # slightly wider than old 92 to fill 300px
_TICK_MS = 33                      # ~30 fps
_REVEAL_INTERVAL_MS = 75           # ms between each cover appearing
_REVEAL_FIRST_DELAY_MS = 325       # ms before the first cover appears
_REVEAL_INITIAL_OPACITY = 0.2      # starting opacity for the first-cover fade-in
_REVEAL_FADE_MS = 180              # duration of the first-cover fade from _REVEAL_INITIAL_OPACITY to 1.0
_LINE_LIGHTNESS_SHIFT = 0.35       # HSL lightness delta for auto-derived stripe line color
_STRIPE_LINE_PX = 1                # height of the top/bottom border lines on the stripe


class CoverCarousel(QWidget):
    def __init__(self, pixmaps, cover_h, stripe_color="#2a2a2a",
                 gap=4, scroll_speed=15, line_color: str | None = None, parent=None):
        """pixmaps: list of QPixmap each already scaled/cropped to (CAROUSEL_COVER_W, cover_h)."""
        super().__init__(parent)
        self._cover_w = CAROUSEL_COVER_W
        self._cover_h = cover_h
        self._gap = gap
        self._scroll_speed = scroll_speed
        self._stripe_color = QColor(stripe_color)
        self._line_color_explicit = line_color is not None
        self._line_color = line_color if line_color is not None else _auto_stripe_line_color(stripe_color)
        self._unit = self._cover_w + gap
        self._offset = 0.0                        # float for sub-pixel accumulation
        self.setFixedWidth(CAROUSEL_STRIPE_W)
        self.setFixedHeight(cover_h + 2 * CAROUSEL_STRIPE_PAD)

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

        # Reveal phase: covers appear one by one before scrolling begins.
        self._revealing = True
        self._reveal_count = 0   # incremented to 1 on first tick (after first-delay)
        self._first_cover_opacity = _REVEAL_INITIAL_OPACITY
        self._fade_timer = None
        self._reveal_target = (
            min(4, len(self._pixmaps))            # static: all covers (already ≤ 3)
            if self._static
            else min(4, len(pixmaps))             # scroll: original (un-duplicated) count
        )
        self._reveal_timer = QTimer(self)
        self._reveal_timer.setSingleShot(True)
        self._reveal_timer.setInterval(_REVEAL_FIRST_DELAY_MS)
        self._reveal_timer.timeout.connect(self._reveal_first)
        self._reveal_timer.start()

    def _reveal_first(self):
        self._reveal_count = 1
        self._first_cover_opacity = _REVEAL_INITIAL_OPACITY
        step = (1.0 - _REVEAL_INITIAL_OPACITY) / max(1, _REVEAL_FADE_MS / _TICK_MS)
        self._fade_step = step
        self._fade_timer = QTimer(self)
        self._fade_timer.setInterval(_TICK_MS)
        self._fade_timer.timeout.connect(self._fade_tick)
        self._fade_timer.start()
        self.update()
        if self._reveal_count < self._reveal_target:
            self._reveal_timer = QTimer(self)
            self._reveal_timer.setInterval(_REVEAL_INTERVAL_MS)
            self._reveal_timer.timeout.connect(self._reveal_tick)
            self._reveal_timer.start()
        else:
            self._reveal_timer = None
            self._revealing = False
            if self._timer is not None:
                self._elapsed.restart()
                self._last_ms = 0
                self._timer.start()

    def _fade_tick(self):
        self._first_cover_opacity = min(1.0, self._first_cover_opacity + self._fade_step)
        self.update()
        if self._first_cover_opacity >= 1.0:
            t = self._fade_timer
            self._fade_timer = None
            if t is not None:
                t.stop()

    def _reveal_tick(self):
        self._reveal_count += 1
        self.update()
        if self._reveal_count >= self._reveal_target:
            t = self._reveal_timer
            self._reveal_timer = None
            self._revealing = False
            if t is not None:
                t.stop()
            if not self._static and self._timer is not None:
                self._elapsed.restart()
                self._last_ms = 0
                self._timer.start()

    def _tick(self):
        now_ms = self._elapsed.elapsed()
        dt = (now_ms - self._last_ms) / 1000.0
        self._last_ms = now_ms
        self._offset = (self._offset + self._scroll_speed * dt) % self._strip_w
        self.update()

    def stop(self):
        """Stop scroll and reveal timers. Safe to call at any phase."""
        rt = self._reveal_timer
        if rt is not None and rt.isActive():
            rt.stop()
        ft = self._fade_timer
        if ft is not None and ft.isActive():
            ft.stop()
        if self._timer is not None:
            self._timer.stop()

    def start(self):
        """Resume the scroll timer after a stop(). Safe to call when in static mode."""
        if self._revealing:
            return   # reveal not finished — scroll starts automatically when done
        if self._timer is not None and not self._timer.isActive():
            # Reset elapsed so dt doesn't spike from accumulated idle time.
            self._elapsed.restart()
            self._last_ms = 0
            self._timer.start()

    def set_stripe_color(self, color: str, line_color: str | None = None):
        self._stripe_color = QColor(color)
        if line_color is not None:
            self._line_color = line_color
        else:
            self._line_color = _auto_stripe_line_color(color)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(self.rect(), self._stripe_color)
        lc = QColor(self._line_color)
        p.fillRect(0, 0, self.width(), _STRIPE_LINE_PX, lc)
        p.fillRect(0, self.height() - _STRIPE_LINE_PX, self.width(), _STRIPE_LINE_PX, lc)
        bottom_y = self.height() - CAROUSEL_STRIPE_PAD

        if self._revealing:
            y = bottom_y - self._cover_h
            for i in range(min(self._reveal_count, len(self._pixmaps))):
                if i == 0 and self._first_cover_opacity < 1.0:
                    p.setOpacity(self._first_cover_opacity)
                    p.drawPixmap(i * self._unit, y, self._pixmaps[i])
                    p.setOpacity(1.0)
                else:
                    p.drawPixmap(i * self._unit, y, self._pixmaps[i])
            return

        y = bottom_y - self._cover_h             # bottom-aligned, padded from stripe edge

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
