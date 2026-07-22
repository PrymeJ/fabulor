"""
Standalone perf spike: real-time backdrop blur for a semi-transparent panel
sitting on top of the LIVE transport bar.

THROWAWAY MEASUREMENT CODE. Not wired into the app. Do not import from fabulor.

Real scenario being simulated: a panel (settings/library/stats/etc, ~90% width,
semi-transparent per the app's screenshot) slides in over the player view. The
transport bar underneath keeps updating while the panel is open: the chapter
title marquee keeps scrolling, the four time labels keep ticking, the chapter
slider keeps advancing (or bursts through a fast flow-animation during a
chapter transition). The panel's backdrop must show a BLURRED, illegible
version of all of that live motion, grabbed and re-blurred continuously, not
a static blur-once snapshot.

Mechanisms mirrored from the app's real code (controls.py / app.py /
main_window_builders.py), confirmed by direct source reading:

  - chapter/title ScrollingLabel: own QTimer, 60ms ("Normal") or 120ms ("Slow"),
    steps offset +/-1px/tick, 40-tick pause at each end, explicit self.update()
    every tick (controls.py ScrollingLabel._update_scroll).
  - four time labels (chap_elapsed 48x24, chap_duration 48x24, current_time 80x24,
    total_time 80x24): driven by the 200ms ui_timer steady-state cadence
    (app.py _update_ui_sync -> _sync_progress_sliders / _sync_chapter_ui).
  - chapter_progress_slider (13px tall, ~280px wide stand-in): steady-state
    setValue() on the same 200ms tick, OR (toggleable) a much faster ~16ms
    QPropertyAnimation "animate_to" burst mode simulating a chapter-transition
    flow animation (controls.py ClickSlider.animate_to / _flow_anim).

The panel itself is modeled as ONE semi-transparent region covering the whole
transport-bar area (matching the real "~90% width panel" shape) — NOT five
separate blurred widgets. What's compared across the three "compositing modes"
below is HOW that one panel decides what part of itself to re-render+reblur
on each frame, given that the content underneath is dirty in five independent
places at five independent cadences:

  1. SEPARATE       - panel still redraws as one surface, but only the sub-rect(s)
                       of ITSELF that sit above currently-dirty transport-bar
                       content are re-grabbed+reblurred each frame (finest-grained).
  2. UNIFIED_FULL    - any single dirty sub-widget underneath forces the ENTIRE
                       panel-covered region to be re-grabbed+reblurred (worst case,
                       simplest implementation).
  3. UNIFIED_DIRTY   - one panel surface, but only the UNION of dirty sub-rects
                       since the last composite is re-grabbed+reblurred, then
                       blitted into a persistent cached panel pixmap.

In all three modes the ENTIRE grabbed pixmap (label pixels, slider pixels, time
label pixels, and the sliver of raw backdrop between them) is blurred together
as one image — nothing stays crisp. That's the point: from the panel's side,
everything underneath is illegible motion.

Keybindings (runtime-switchable, no restart needed):
  1 / 2 / 3   -> compositing mode: separate dirty sub-rects / unified full-panel / unified dirty-union
  b           -> toggle blur backend: PIL Gaussian blur <-> QGraphicsBlurEffect
  s           -> toggle marquee speed: Normal(60ms) <-> Slow(120ms)
  a           -> toggle slider animate_to burst mode on/off
  q / Esc     -> quit

Instrumentation is written to spikes/blur_spike_log.txt (override with --log
PATH) AS WELL AS the terminal: running avg + worst-case render/blur/blit
timing every ~60 updates, plus a per-second total "blur-related main-thread
work" figure. This is a standalone script-local logger, not the app's
fabulor.log — this spike is throwaway and not wired into the app.
"""
import sys
import os
import time
import random
import argparse
import logging
from collections import deque
from enum import Enum

from PySide6.QtWidgets import (
    QApplication, QWidget, QGraphicsBlurEffect, QGraphicsScene,
)
from PySide6.QtCore import Qt, QTimer, QRect, QPoint, QSize
from PySide6.QtGui import QPainter, QColor, QPixmap, QImage, QFont, QPen, QLinearGradient

from PIL import Image, ImageFilter
from PIL.ImageQt import ImageQt


# ---------------------------------------------------------------------------
# Real geometry / cadence constants, as confirmed in the app's source.
# ---------------------------------------------------------------------------

CHAPTER_LABEL_SIZE = QSize(170, 24)       # layout-flexible in reality; 170 used as stand-in
CHAP_ELAPSED_SIZE = QSize(48, 24)
CHAP_DURATION_SIZE = QSize(48, 24)
CURRENT_TIME_SIZE = QSize(80, 24)
TOTAL_TIME_SIZE = QSize(80, 24)
SLIDER_SIZE = QSize(280, 13)              # 13px real height; 280 width stand-in

MARQUEE_INTERVAL_NORMAL_MS = 60
MARQUEE_INTERVAL_SLOW_MS = 120
MARQUEE_STEP_PX = 1
MARQUEE_PAUSE_TICKS = 40

UI_TIMER_MS = 200
ANIMATE_TO_BURST_MS = 16   # ~60fps QPropertyAnimation frame cadence

WINDOW_MARGIN = 20
REGION_GAP = 6

BLUR_RADIUS = 7.0
PANEL_TINT_ALPHA = 60      # the panel's own translucent color wash, drawn over the blur


class CompositeMode(Enum):
    SEPARATE = 1        # panel re-grabs/reblurs only the sub-rects above dirty content
    UNIFIED_FULL = 2     # any dirty sub-widget forces a full panel-region reblur
    UNIFIED_DIRTY_RECT = 3  # panel reblurs only the union of dirty sub-rects


class BlurBackend(Enum):
    PIL = "PIL Gaussian"
    QT_EFFECT = "QGraphicsBlurEffect"


# ---------------------------------------------------------------------------
# Timing instrumentation
# ---------------------------------------------------------------------------

def setup_logger(log_path: str) -> logging.Logger:
    logger = logging.getLogger("blur_spike")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fh = logging.FileHandler(log_path, mode="w")
    fh.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))
    logger.addHandler(fh)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(sh)

    return logger


class Stats:
    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.render_times = deque(maxlen=600)
        self.blur_times = deque(maxlen=600)
        self.blit_times = deque(maxlen=600)
        self.total_times = deque(maxlen=600)
        self.update_count = 0
        self._sec_start = time.perf_counter()
        self._sec_total_work = 0.0

    def record(self, render_s, blur_s, blit_s):
        total = render_s + blur_s + blit_s
        self.render_times.append(render_s)
        self.blur_times.append(blur_s)
        self.blit_times.append(blit_s)
        self.total_times.append(total)
        self._sec_total_work += total
        self.update_count += 1

        if self.update_count % 60 == 0:
            self._log_running()

        now = time.perf_counter()
        if now - self._sec_start >= 1.0:
            self.logger.info(
                f"  [1s window] total blur-related main-thread work: "
                f"{self._sec_total_work * 1000:.2f} ms / {now - self._sec_start:.3f} s "
                f"({100 * self._sec_total_work / (now - self._sec_start):.1f}% of a core)"
            )
            self._sec_start = now
            self._sec_total_work = 0.0

    def _log_running(self):
        def avg_worst(d):
            if not d:
                return 0.0, 0.0
            return (sum(d) / len(d)) * 1000, max(d) * 1000

        r_avg, r_worst = avg_worst(self.render_times)
        b_avg, b_worst = avg_worst(self.blur_times)
        bl_avg, bl_worst = avg_worst(self.blit_times)
        t_avg, t_worst = avg_worst(self.total_times)
        self.logger.info(
            f"[n={self.update_count:6d}] render avg/worst {r_avg:6.3f}/{r_worst:6.3f} ms | "
            f"blur avg/worst {b_avg:6.3f}/{b_worst:6.3f} ms | "
            f"blit avg/worst {bl_avg:6.3f}/{bl_worst:6.3f} ms | "
            f"TOTAL avg/worst {t_avg:6.3f}/{t_worst:6.3f} ms"
        )


# ---------------------------------------------------------------------------
# Marquee state, mirroring ScrollingLabel._update_scroll exactly
# ---------------------------------------------------------------------------

class MarqueeState:
    def __init__(self, text, widget_width, font):
        self.text = text
        self.widget_width = widget_width
        self.font = font
        self._scroll_pos = 0
        self._direction = 1
        self._pause_counter = 0
        self._text_width = self._measure(text)

    def _measure(self, text):
        from PySide6.QtGui import QFontMetrics
        return QFontMetrics(self.font).horizontalAdvance(text)

    def step(self):
        max_scroll = max(0, self._text_width - self.widget_width + 2)
        if max_scroll <= 0:
            return False
        if self._pause_counter > 0:
            self._pause_counter -= 1
            return False
        self._scroll_pos += self._direction * MARQUEE_STEP_PX
        if self._scroll_pos >= max_scroll:
            self._scroll_pos = max_scroll
            self._direction = -1
            self._pause_counter = MARQUEE_PAUSE_TICKS
        elif self._scroll_pos <= 0:
            self._scroll_pos = 0
            self._direction = 1
            self._pause_counter = MARQUEE_PAUSE_TICKS
        return True


class TransportRegion:
    """One independently-dirty sub-rect of the LIVE transport bar underneath the panel."""

    def __init__(self, name, rect: QRect, painter_fn):
        self.name = name
        self.rect = rect
        self.painter_fn = painter_fn
        self.dirty = True


# ---------------------------------------------------------------------------
# Blur backends — blur the WHOLE grabbed pixmap (content + backdrop together)
# ---------------------------------------------------------------------------

def pil_blur_pixmap(pixmap: QPixmap, radius: float = BLUR_RADIUS) -> QPixmap:
    if pixmap.width() == 0 or pixmap.height() == 0:
        return pixmap
    qimg = pixmap.toImage().convertToFormat(QImage.Format_RGBA8888)
    w, h = qimg.width(), qimg.height()
    buf = bytes(qimg.constBits())
    pil_img = Image.frombuffer("RGBA", (w, h), buf, "raw", "RGBA", 0, 1)
    blurred = pil_img.filter(ImageFilter.GaussianBlur(radius))
    result_qimg = ImageQt(blurred.convert("RGBA"))
    return QPixmap.fromImage(QImage(result_qimg))


def qt_effect_blur_pixmap(pixmap: QPixmap, radius: float = BLUR_RADIUS) -> QPixmap:
    if pixmap.width() == 0 or pixmap.height() == 0:
        return pixmap
    scene = QGraphicsScene()
    item = scene.addPixmap(pixmap)
    effect = QGraphicsBlurEffect()
    effect.setBlurRadius(radius)
    effect.setBlurHints(QGraphicsBlurEffect.QualityHint)
    item.setGraphicsEffect(effect)

    out = QPixmap(pixmap.size())
    out.fill(Qt.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.Antialiasing)
    scene.render(painter, QRect(QPoint(0, 0), pixmap.size()), scene.itemsBoundingRect())
    painter.end()
    return out


# ---------------------------------------------------------------------------
# Main spike widget
# ---------------------------------------------------------------------------

class BlurSpikeWidget(QWidget):
    def __init__(self, logger: logging.Logger):
        super().__init__()
        self.logger = logger
        self.setWindowTitle("Blur/Scroll Compositing Spike")
        self.setFixedSize(340, 220)

        self.mode = CompositeMode.SEPARATE
        self.blur_backend = BlurBackend.PIL
        self.marquee_slow = False
        self.burst_mode = False

        self.stats = Stats(logger)

        self.backdrop = self._make_backdrop(self.size())

        # --- Transport-bar sub-widget geometry, left-to-right ---
        x = WINDOW_MARGIN
        y0 = 40
        self.chapter_rect = QRect(x, y0, CHAPTER_LABEL_SIZE.width(), CHAPTER_LABEL_SIZE.height())
        x += CHAPTER_LABEL_SIZE.width() + REGION_GAP
        self.chap_elapsed_rect = QRect(x, y0, CHAP_ELAPSED_SIZE.width(), CHAP_ELAPSED_SIZE.height())
        x += CHAP_ELAPSED_SIZE.width() + REGION_GAP
        self.chap_duration_rect = QRect(x, y0, CHAP_DURATION_SIZE.width(), CHAP_DURATION_SIZE.height())

        x2 = WINDOW_MARGIN
        y1 = y0 + 30
        self.current_time_rect = QRect(x2, y1, CURRENT_TIME_SIZE.width(), CURRENT_TIME_SIZE.height())
        x2 += CURRENT_TIME_SIZE.width() + REGION_GAP
        self.total_time_rect = QRect(x2, y1, TOTAL_TIME_SIZE.width(), TOTAL_TIME_SIZE.height())

        y2 = y1 + 30
        self.slider_rect = QRect(WINDOW_MARGIN, y2, SLIDER_SIZE.width(), SLIDER_SIZE.height())

        # Panel region: the ~90%-width semi-transparent overlay sitting on top of
        # the whole transport bar (bounding box of all live sub-widgets, padded).
        self.panel_rect = self.chapter_rect.united(self.chap_elapsed_rect) \
            .united(self.chap_duration_rect).united(self.current_time_rect) \
            .united(self.total_time_rect).united(self.slider_rect)
        self.panel_rect.adjust(-10, -10, 10, 10)

        self.regions = {
            "chapter": TransportRegion("chapter", self.chapter_rect, self._paint_chapter_label),
            "chap_elapsed": TransportRegion("chap_elapsed", self.chap_elapsed_rect, self._paint_chap_elapsed),
            "chap_duration": TransportRegion("chap_duration", self.chap_duration_rect, self._paint_chap_duration),
            "current_time": TransportRegion("current_time", self.current_time_rect, self._paint_current_time),
            "total_time": TransportRegion("total_time", self.total_time_rect, self._paint_total_time),
            "slider": TransportRegion("slider", self.slider_rect, self._paint_slider),
        }

        # Persistent cache of the panel's blurred pixels (unified modes reuse/patch this).
        self.panel_cache = None  # QPixmap sized to panel_rect

        # --- Fake playback state ---
        self.font = QFont("Sans", 10)
        self.marquee = MarqueeState(
            "Chapter 7: The Long Road Home (a rather verbose chapter title)",
            CHAPTER_LABEL_SIZE.width(), self.font,
        )
        self.chap_elapsed_s = 0
        self.chap_duration_s = 754
        self.current_time_s = 0
        self.total_time_s = 9421
        self.slider_value = 0.0
        self.slider_target = 0.0
        self.slider_anim_start = 0.0
        self.slider_anim_start_time = 0.0
        self.slider_anim_duration = 0.0
        self.slider_animating = False

        # --- Timers mirroring the real mechanisms ---
        self.marquee_timer = QTimer(self)
        self.marquee_timer.timeout.connect(self._on_marquee_tick)
        self.marquee_timer.start(MARQUEE_INTERVAL_NORMAL_MS)

        self.ui_timer = QTimer(self)
        self.ui_timer.timeout.connect(self._on_ui_tick)
        self.ui_timer.start(UI_TIMER_MS)

        self.burst_timer = QTimer(self)
        self.burst_timer.timeout.connect(self._on_burst_tick)

        self.burst_trigger_timer = QTimer(self)
        self.burst_trigger_timer.timeout.connect(self._maybe_start_burst)
        self.burst_trigger_timer.start(4000)

        self.setFocusPolicy(Qt.StrongFocus)

        self.logger.info(
            f"panel_rect={self.panel_rect.width()}x{self.panel_rect.height()} "
            f"covering {len(self.regions)} live sub-widgets"
        )

    # -- backdrop (the raw player-view pixels the panel sits on top of) -------

    def _make_backdrop(self, size: QSize) -> QPixmap:
        pm = QPixmap(size)
        painter = QPainter(pm)
        grad = QLinearGradient(0, 0, size.width(), size.height())
        grad.setColorAt(0.0, QColor(30, 40, 70))
        grad.setColorAt(0.5, QColor(90, 30, 60))
        grad.setColorAt(1.0, QColor(20, 60, 50))
        painter.fillRect(pm.rect(), grad)
        rng = random.Random(42)
        for _ in range(40):
            r = rng.randint(4, 24)
            cx = rng.randint(0, size.width())
            cy = rng.randint(0, size.height())
            painter.setBrush(QColor(255, 255, 255, rng.randint(10, 40)))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QPoint(cx, cy), r, r)
        painter.end()
        return pm

    # -- fake playback tick sources (drive the LIVE content under the panel) --

    def _on_marquee_tick(self):
        if self.marquee.step():
            self.regions["chapter"].dirty = True
            self.update(self.panel_rect)

    def _on_ui_tick(self):
        self.chap_elapsed_s = (self.chap_elapsed_s + 1) % max(1, self.chap_duration_s)
        self.current_time_s = (self.current_time_s + 1) % max(1, self.total_time_s)
        self.regions["chap_elapsed"].dirty = True
        self.regions["chap_duration"].dirty = True
        self.regions["current_time"].dirty = True
        self.regions["total_time"].dirty = True

        if not self.slider_animating:
            self.slider_value = min(1000.0, self.slider_value + 1000.0 / max(1, self.chap_duration_s))
            self.regions["slider"].dirty = True

        self.update(self.panel_rect)

    def _maybe_start_burst(self):
        if not self.burst_mode or self.slider_animating:
            return
        self.slider_anim_start = self.slider_value
        self.slider_target = 0.0 if self.slider_value > 500 else 800.0
        self.slider_anim_start_time = time.perf_counter()
        distance = abs(self.slider_target - self.slider_anim_start) / 1000.0
        self.slider_anim_duration = 0.2 + distance * 0.4   # mirrors controls.py: 200 + distance*400 ms
        self.slider_animating = True
        self.burst_timer.start(ANIMATE_TO_BURST_MS)

    def _on_burst_tick(self):
        elapsed = time.perf_counter() - self.slider_anim_start_time
        t = min(1.0, elapsed / self.slider_anim_duration)
        eased = 1 - (1 - t) ** 3
        self.slider_value = self.slider_anim_start + (self.slider_target - self.slider_anim_start) * eased
        self.regions["slider"].dirty = True
        self.update(self.panel_rect)
        if t >= 1.0:
            self.slider_animating = False
            self.burst_timer.stop()

    # -- content painters for the live transport-bar widgets ------------------

    def _paint_chapter_label(self, painter: QPainter, rect: QRect):
        painter.setPen(QPen(QColor(255, 255, 255)))
        painter.setFont(self.font)
        painter.setClipRect(rect)
        painter.drawText(rect.x() - self.marquee._scroll_pos, rect.y(), 2000, rect.height(),
                          Qt.AlignVCenter | Qt.TextSingleLine, self.marquee.text)

    def _paint_chap_elapsed(self, painter: QPainter, rect: QRect):
        painter.setPen(QColor(230, 230, 230))
        painter.setFont(self.font)
        m, s = divmod(self.chap_elapsed_s, 60)
        painter.drawText(rect, Qt.AlignCenter, f"{m}:{s:02d}")

    def _paint_chap_duration(self, painter: QPainter, rect: QRect):
        painter.setPen(QColor(230, 230, 230))
        painter.setFont(self.font)
        m, s = divmod(self.chap_duration_s, 60)
        painter.drawText(rect, Qt.AlignCenter, f"-{m}:{s:02d}")

    def _paint_current_time(self, painter: QPainter, rect: QRect):
        painter.setPen(QColor(255, 255, 255))
        painter.setFont(self.font)
        h, rem = divmod(self.current_time_s, 3600)
        m, s = divmod(rem, 60)
        painter.drawText(rect, Qt.AlignCenter, f"{h}:{m:02d}:{s:02d}")

    def _paint_total_time(self, painter: QPainter, rect: QRect):
        painter.setPen(QColor(255, 255, 255))
        painter.setFont(self.font)
        h, rem = divmod(self.total_time_s, 3600)
        m, s = divmod(rem, 60)
        painter.drawText(rect, Qt.AlignCenter, f"{h}:{m:02d}:{s:02d}")

    def _paint_slider(self, painter: QPainter, rect: QRect):
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(80, 80, 90))
        painter.drawRoundedRect(rect, 3, 3)
        fill_w = int(rect.width() * (self.slider_value / 1000.0))
        painter.setBrush(QColor(120, 190, 255))
        painter.drawRoundedRect(QRect(rect.x(), rect.y(), fill_w, rect.height()), 3, 3)

    def _render_live_content(self, target: QPixmap, region_rect: QRect, offset: QPoint):
        """Paint the live transport-bar content for region_rect onto target at offset."""
        painter = QPainter(target)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.translate(offset)
        for region in self.regions.values():
            local = region.rect.translated(-region_rect.topLeft())
            painter.save()
            painter.translate(local.topLeft())
            region.painter_fn(painter, QRect(0, 0, region.rect.width(), region.rect.height()))
            painter.restore()
        painter.end()

    def _grab_and_blur(self, rect: QRect) -> QPixmap:
        """Grab backdrop + live sub-widget content under `rect`, blur the WHOLE thing."""
        grabbed = QPixmap(rect.size())
        grabbed.fill(Qt.transparent)
        p = QPainter(grabbed)
        p.drawPixmap(0, 0, self.backdrop.copy(rect))
        p.end()
        self._render_live_content(grabbed, rect, QPoint(0, 0))
        return self._blur(grabbed)

    def _blur(self, pm: QPixmap) -> QPixmap:
        if self.blur_backend == BlurBackend.PIL:
            return pil_blur_pixmap(pm)
        else:
            return qt_effect_blur_pixmap(pm)

    # -- paintEvent: draw raw backdrop first (as if panel not yet composited),
    #    then have the panel re-grab+reblur whatever's dirty underneath it -----

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self.backdrop)
        # draw the live (unblurred) transport bar once for reference, outside panel_rect area
        # (kept out of panel_rect so it never leaks into the blurred region visually)

        if self.mode == CompositeMode.SEPARATE:
            render_t, blur_t, blit_t = self._paint_separate(painter)
        elif self.mode == CompositeMode.UNIFIED_FULL:
            render_t, blur_t, blit_t = self._paint_unified_full(painter)
        else:
            render_t, blur_t, blit_t = self._paint_unified_dirty(painter)

        # panel's own translucent tint wash, over the blur, matching the app's semi-transparent panel look
        painter.fillRect(self.panel_rect, QColor(20, 30, 25, PANEL_TINT_ALPHA))
        painter.setPen(QColor(255, 255, 255, 90))
        painter.drawRect(self.panel_rect)

        # HUD
        painter.setPen(QColor(255, 255, 0))
        painter.setFont(QFont("Monospace", 8))
        hud = (f"mode={self.mode.name}  blur={self.blur_backend.value}  "
               f"marquee={'Slow(120ms)' if self.marquee_slow else 'Normal(60ms)'}  "
               f"burst={'ON' if self.burst_mode else 'off'}")
        painter.fillRect(0, 0, self.width(), 16, QColor(0, 0, 0, 160))
        painter.drawText(4, 12, hud)
        painter.setPen(QColor(200, 200, 200))
        painter.drawText(4, self.height() - 6,
                          "keys: 1/2/3 mode  b blur backend  s marquee speed  a burst  q quit")
        painter.end()

        self.stats.record(render_t, blur_t, blit_t)

    def _paint_separate(self, painter: QPainter):
        """Only re-grab+reblur the panel sub-rect above each currently-dirty widget,
        patched into a persistent cache — non-dirty sub-rects are NOT left showing
        raw backdrop, they replay their last blurred pixels from the cache."""
        if self.panel_cache is None:
            self.panel_cache = QPixmap(self.panel_rect.size())
            self.panel_cache.fill(Qt.transparent)
            # seed every region into the cache on first paint so nothing starts unblurred
            for region in self.regions.values():
                region.dirty = True

        render_total = blur_total = blit_total = 0.0
        for region in self.regions.values():
            if not region.dirty:
                continue
            # pad the grab rect slightly so the blur has neighboring pixels to work with
            grab_rect = region.rect.adjusted(-4, -4, 4, 4).intersected(self.panel_rect)
            t0 = time.perf_counter()
            blurred = self._grab_and_blur(grab_rect)
            t1 = time.perf_counter()

            cache_painter = QPainter(self.panel_cache)
            cache_painter.setCompositionMode(QPainter.CompositionMode_Source)
            cache_painter.drawPixmap(grab_rect.translated(-self.panel_rect.topLeft()).topLeft(), blurred)
            cache_painter.end()

            region.dirty = False
            blur_total += (t1 - t0)

        t2 = time.perf_counter()
        painter.drawPixmap(self.panel_rect.topLeft(), self.panel_cache)
        blit_total += (time.perf_counter() - t2)
        return render_total, blur_total, blit_total

    def _paint_unified_full(self, painter: QPainter):
        """Any single dirty sub-widget forces the WHOLE panel region to be reblurred."""
        any_dirty = any(r.dirty for r in self.regions.values())
        if not any_dirty and self.panel_cache is not None:
            painter.drawPixmap(self.panel_rect.topLeft(), self.panel_cache)
            return 0.0, 0.0, 0.0

        t0 = time.perf_counter()
        blurred = self._grab_and_blur(self.panel_rect)
        t1 = time.perf_counter()
        painter.drawPixmap(self.panel_rect.topLeft(), blurred)
        t2 = time.perf_counter()

        self.panel_cache = blurred
        for r in self.regions.values():
            r.dirty = False
        return 0.0, (t1 - t0), (t2 - t1)

    def _paint_unified_dirty(self, painter: QPainter):
        """One panel surface; only the union of dirty sub-rects is re-grabbed+reblurred
        and patched into a persistent cached panel pixmap."""
        dirty_regions = [r for r in self.regions.values() if r.dirty]
        if self.panel_cache is None:
            self.panel_cache = QPixmap(self.panel_rect.size())
            self.panel_cache.fill(Qt.transparent)

        if not dirty_regions:
            painter.drawPixmap(self.panel_rect.topLeft(), self.panel_cache)
            return 0.0, 0.0, 0.0

        union_rect = dirty_regions[0].rect
        for r in dirty_regions[1:]:
            union_rect = union_rect.united(r.rect)
        union_rect = union_rect.adjusted(-4, -4, 4, 4).intersected(self.panel_rect)

        t0 = time.perf_counter()
        blurred_slice = self._grab_and_blur(union_rect)
        t1 = time.perf_counter()

        cache_painter = QPainter(self.panel_cache)
        cache_painter.setCompositionMode(QPainter.CompositionMode_Source)
        cache_painter.drawPixmap(union_rect.translated(-self.panel_rect.topLeft()).topLeft(), blurred_slice)
        cache_painter.end()

        painter.drawPixmap(self.panel_rect.topLeft(), self.panel_cache)
        t2 = time.perf_counter()

        for r in dirty_regions:
            r.dirty = False
        return 0.0, (t1 - t0), (t2 - t1)

    # -- input ------------------------------------------------------------

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_1:
            self.mode = CompositeMode.SEPARATE
            self.logger.info(">> mode = SEPARATE (reblur only sub-rects above dirty content)")
        elif key == Qt.Key_2:
            self.mode = CompositeMode.UNIFIED_FULL
            self.logger.info(">> mode = UNIFIED_FULL (any dirty widget reblurs the whole panel)")
        elif key == Qt.Key_3:
            self.mode = CompositeMode.UNIFIED_DIRTY_RECT
            self.logger.info(">> mode = UNIFIED_DIRTY_RECT (reblur union of dirty sub-rects only)")
        elif key == Qt.Key_B:
            self.blur_backend = (BlurBackend.QT_EFFECT if self.blur_backend == BlurBackend.PIL
                                  else BlurBackend.PIL)
            self.logger.info(f">> blur backend = {self.blur_backend.value}")
        elif key == Qt.Key_S:
            self.marquee_slow = not self.marquee_slow
            self.marquee_timer.setInterval(
                MARQUEE_INTERVAL_SLOW_MS if self.marquee_slow else MARQUEE_INTERVAL_NORMAL_MS)
            self.logger.info(f">> marquee interval = {self.marquee_timer.interval()}ms")
        elif key == Qt.Key_A:
            self.burst_mode = not self.burst_mode
            self.logger.info(f">> animate_to burst mode = {'ON (fires every ~4s)' if self.burst_mode else 'off'}")
        elif key in (Qt.Key_Q, Qt.Key_Escape):
            QApplication.instance().quit()
        else:
            super().keyPressEvent(event)
        for r in self.regions.values():
            r.dirty = True
        self.panel_cache = None
        self.update()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", default=os.path.join(os.path.dirname(__file__), "blur_spike_log.txt"),
                         help="Path to write timing log (default: spikes/blur_spike_log.txt)")
    args = parser.parse_args()

    logger = setup_logger(args.log)
    logger.info(f"Blur/scroll compositing spike starting. Logging to {args.log}")
    logger.info("1=separate 2=unified-full 3=unified-dirty-rect  b=blur backend  s=marquee speed  a=burst  q=quit")

    app = QApplication(sys.argv)
    w = BlurSpikeWidget(logger)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
