"""Live backdrop blur for the mini transport bar behind an open panel.

Composited-overlay approach (per the accepted plan): a single semi-transparent
panel sits over the "mini transport bar" (chapter label, chapter elapsed/
duration labels, chapter progress slider, current/total time labels, transport
buttons, speed button, volume slider/mute icon, and the sleep timer label while
active). Rather than blurring each widget in place, this grabs a rasterized
snapshot of the WHOLE bounding region and blurs that snapshot as one image,
compositing it into an overlay drawn just under the panel — so gaps between
widgets and vol_stack's inactive pages blur too, unlike the direct-widget
blur-composited-overlay's sibling branch (blur-direct-widget).

Mechanism (see the accepted plan, /home/pryme/.claude/plans/good-catch-claude-
twinkly-kay.md, for the full design rationale):

  1. On panel-open: compute the bounding rect as the union of all in-scope
     widgets' geometry, mapped into content_container's coordinate space. Grab
     that rect, blur it (QGraphicsBlurEffect via a disposable proxy), blit it
     into an overlay QLabel positioned under the panel. This mandatory full-rect
     pass is unconditional and structurally guarantees no gap/seam, independent
     of the dirty-tracking below.
  2. While the panel stays open: a QEvent.Paint event filter installed on each
     in-scope widget observes real repaints WITHOUT touching the widgets' own
     timing/logic (ScrollingLabel's marquee timer, the 200ms ui_timer chain, or
     ClickSlider.animate_to) — it only reacts to the repaints those mechanisms
     already trigger. Dirty sub-rects accumulate into one QRect.united() union;
     only that union is re-grabbed, re-blurred, and patched into the overlay
     (not the whole bounding rect every time).
  3. On panel-close: the fallback behavior — the overlay stays static through
     the slide-out, then is torn down entirely once the close animation
     finishes. No live-tracking during the slide (deferred per the plan).

vol_stack (sleep_timer_label / volume_slider / muted_icon_label) is a
QStackedWidget where only one page is ever actually shown — an inactive page
reports bogus geometry (Qt's default-widget size sentinel, since it's never
been laid out while hidden), so only vol_stack.currentWidget() is tracked,
resolved fresh via _vol_stack_active_widget() on every bounding-rect
computation and every show_for_panel() call (never cached), since the active
page can change while a panel stays open.
"""
import logging

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QGraphicsBlurEffect, QGraphicsScene, QLabel

logger = logging.getLogger(__name__)

_BLUR_RADIUS = 5.0
# Drives refresh_dirty() while the overlay is active. Must be well under the
# marquee's fastest tick (60ms, "Normal" scroll speed) so scrolling still reads
# as smooth through the blur, and under the 200ms ui_timer's cadence too — see
# the accepted plan's worst-case-convergence section for why a single-union-
# rect composite stays cheap enough at this cadence.
_REFRESH_INTERVAL_MS = 50


def _blur_pixmap(pixmap: QPixmap, radius: float = _BLUR_RADIUS) -> QPixmap:
    """Blur pixmap via a disposable QGraphicsBlurEffect + offscreen QGraphicsScene.
    Never attaches the effect to a real widget — built and discarded per call."""
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


class _DirtyRectTracker(QObject):
    """QEvent.Paint filter: accumulates a union of dirty sub-rects, mapped into
    a common coordinate space, without consuming or altering the event."""

    def __init__(self, common_ancestor):
        super().__init__()
        self._common_ancestor = common_ancestor
        self._dirty_union: QRect | None = None

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Paint:
            top_left = obj.mapTo(self._common_ancestor, QPoint(0, 0))
            rect = QRect(top_left, obj.size())
            self._dirty_union = rect if self._dirty_union is None else self._dirty_union.united(rect)
        return False  # never consume — must not affect real painting

    def take_dirty_union(self) -> QRect | None:
        """Consuming read: returns the accumulated union and resets it to empty."""
        union = self._dirty_union
        self._dirty_union = None
        return union


class TransportBarBlurOverlay:
    """Owns the overlay widget, the bounding-rect computation, and the
    dirty-tracking lifecycle for one MainWindow's mini transport bar."""

    def __init__(self, main_window):
        self.main_window = main_window
        self._common_ancestor = main_window.content_container

        # Widgets in scope — see the accepted plan's Scope section. These are
        # always laid out and sized correctly, so their geometry/mapTo() is safe
        # to read unconditionally.
        self._widgets = [
            main_window.current_chapter_label,
            main_window.chap_elapsed_label,
            main_window.chap_duration_label,
            main_window.chapter_progress_slider,
            main_window.current_time_label,
            main_window.total_time_label,
            main_window.prev_button,
            main_window.rewind_button,
            main_window.play_pause_button,
            main_window.forward_button,
            main_window.next_button,
            main_window.speed_button,
        ]

        # vol_stack (sleep_timer_label / vol_container[volume_slider] /
        # muted_icon_label) is a QStackedWidget — only ONE page is ever actually
        # shown at a time, and a HIDDEN QStackedWidget page reports bogus
        # geometry: confirmed live (2026-07-19) that an inactive page's .size()
        # returns Qt's default-widget sentinel (640x480), not its real small
        # size, because it's never been laid out while hidden. Including all
        # three unconditionally blew the bounding-rect union out to cover
        # unrelated areas (the cover-art "burn" corruption bug). Only the vol_stack
        # page vol_stack.currentWidget() actually IS right now is geometry-safe —
        # resolved dynamically on every bounding-rect computation, never cached,
        # since the active page can change while a panel is open (mute toggled,
        # sleep timer started/stopped, volume-slider interaction).
        self._vol_stack = main_window.vol_stack

        # Parented to content_container (the SAME coordinate space _bounding_rect
        # and every widget.mapTo(...) call below is computed in) — NOT main_window.
        # content_container sits below the title bar + progress bar in main_window's
        # root_layout (app.py:596-604), so it is NOT at (0,0) within main_window;
        # parenting the overlay to main_window while positioning it with
        # content_container-relative coordinates smeared the overlay across the
        # wrong region entirely (found live, 2026-07-19 — the pink-wash bug).
        self._overlay = QLabel(self._common_ancestor)
        self._overlay.setObjectName("transport_bar_blur_overlay")
        self._overlay.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._overlay.hide()

        self._tracker: _DirtyRectTracker | None = None
        self._tracker_widgets: list = []  # widgets the tracker's filter is actually
                                           # installed on — NOT recomputed via
                                           # _all_tracked_widgets() at removal time,
                                           # since the vol_stack active page can
                                           # change mid-open (see hide_for_panel).
        self._bounding_rect: QRect | None = None
        self._active = False
        self._active_panel = None  # set in show_for_panel, cleared in hide_for_panel —
                                    # needed so _grab_and_blur can hide/restore the
                                    # currently-open panel around each grab from
                                    # main_window (see the "ROOT CAUSE" note there).

        # Drives refresh_dirty() while active — see _REFRESH_INTERVAL_MS. The
        # QEvent.Paint filter only accumulates dirty state; nothing else would
        # ever flush it into the overlay pixmap without this.
        self._refresh_timer = QTimer(main_window)
        self._refresh_timer.setInterval(_REFRESH_INTERVAL_MS)
        self._refresh_timer.timeout.connect(self.refresh_dirty)

    def _vol_stack_active_widget(self):
        current = self._vol_stack.currentWidget()
        # volume_slider lives INSIDE vol_container (the actual stack page) — when
        # vol_container is the active page, track volume_slider itself (the real
        # content), not the vol_container wrapper.
        if current is self.main_window.vol_container:
            return self.main_window.volume_slider
        return current

    def _all_tracked_widgets(self):
        return self._widgets + [self._vol_stack_active_widget()]

    # -- lifecycle ----------------------------------------------------------

    def show_for_panel(self, panel):
        """Mandatory full-rect first pass, called once on panel-open. Computes
        the bounding rect fresh (cheap — a handful of mapTo calls), clips it to
        `panel`'s own geometry (nothing ever renders blurred outside what the
        panel actually covers — e.g. total_time_label sits at the far right of
        the content area by layout design, past settings_panel's narrower
        90%-width edge; that sliver must stay crisp, not just "technically
        correct blur that peeks past the panel." Confirmed live, 2026-07-19),
        grabs+blurs the whole (clipped) region, shows the overlay, then arms
        dirty-tracking for subsequent updates while the panel stays open."""
        if self._active:
            return
        raw_rect = self._compute_bounding_rect()
        if raw_rect is None or raw_rect.isEmpty():
            return
        panel_rect = self._panel_rect_in_common_space(panel)
        self._bounding_rect = raw_rect.intersected(panel_rect)
        if self._bounding_rect.isEmpty():
            return

        self._active_panel = panel
        blurred = self._grab_and_blur(self._bounding_rect)
        self._overlay.setPixmap(blurred)
        self._overlay.setGeometry(self._bounding_rect)
        self._overlay.show()
        self._overlay.raise_()

        self._tracker = _DirtyRectTracker(self._common_ancestor)
        self._tracker_widgets = self._all_tracked_widgets()
        for widget in self._tracker_widgets:
            widget.installEventFilter(self._tracker)
        self._tracker.take_dirty_union()  # reset: the first pass already covers everything

        self._active = True
        self._refresh_timer.start()

    def refresh_dirty(self):
        """Re-grab+reblur only the union of sub-rects dirtied since the last
        composite (or since show_for_panel's reset), patch it into the overlay
        pixmap. No-op if nothing is dirty or the overlay isn't active. Call this
        periodically (or on a cheap trigger) while a blur-eligible panel is open."""
        if not self._active or self._tracker is None:
            return
        dirty = self._tracker.take_dirty_union()
        if dirty is None:
            return
        dirty = dirty.intersected(self._bounding_rect)
        if dirty.isEmpty():
            return

        blurred_slice = self._grab_and_blur(dirty)
        current = self._overlay.pixmap()
        if current is None or current.isNull():
            return
        combined = QPixmap(current)
        painter = QPainter(combined)
        local = dirty.translated(-self._bounding_rect.topLeft())
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.drawPixmap(local.topLeft(), blurred_slice)
        painter.end()
        self._overlay.setPixmap(combined)

    def hide_for_panel(self):
        """Fallback slide-out behavior: tear down unconditionally. Called from
        the panel's *_hidden handler (after the close animation finishes), not
        during the slide itself — see the accepted plan's §6 for why live-
        dissolve-during-slide is deferred, not implemented here."""
        self._refresh_timer.stop()
        if self._tracker is not None:
            # Remove from exactly what was installed on (self._tracker_widgets),
            # NOT a freshly recomputed _all_tracked_widgets() — the vol_stack
            # active page can change while the panel is open (mute toggled, sleep
            # timer started/stopped), so recomputing here could target a
            # DIFFERENT widget than the filter was actually installed on, leaking
            # a stale installEventFilter forever on the original one.
            for widget in self._tracker_widgets:
                widget.removeEventFilter(self._tracker)
            self._tracker = None
            self._tracker_widgets = []
        self._overlay.hide()
        self._overlay.setPixmap(QPixmap())
        self._bounding_rect = None
        self._active = False
        self._active_panel = None

    # -- geometry -------------------------------------------------------------

    def _panel_rect_in_common_space(self, panel) -> QRect:
        """`panel`'s TARGET (settled, post-slide-in) geometry, mapped into
        _common_ancestor's coordinate space — NOT its live/current position.

        show_for_panel() is called synchronously right after the panel's
        slide-in QPropertyAnimation.start() (panels.py, every _start_*_entry),
        so at the moment this runs the panel is typically still off-screen or
        mid-flight, not yet at its resting position — confirmed live
        (2026-07-19): reading panel.mapToGlobal() here produced an empty
        intersection with the transport-bar rect every time, silently
        no-opping show_for_panel entirely (the "no blur at all" regression).
        Every panel-open animation in panels.py animates ONLY x, always
        ending at x=0 with y fixed for the whole slide (confirmed: every
        `_*_animation.setEndValue(QPoint(0, ...))` call site) — so the
        settled rect is always (0, panel.y(), panel.width(), panel.height())
        in main_window-local coordinates; panel.y()/.size() are already
        final by the time this runs, only .x() is still animating.

        `panel` is a raw child of main_window while _common_ancestor
        (content_container) is a SIBLING of panel, not an ancestor of it — Qt's
        widget.mapTo(target, ...) only works when `target` is in `widget`'s
        parent hierarchy (an ancestor); called on siblings it emits
        "QWidget::mapTo(): parent must be in parent hierarchy" and silently
        returns an UNTRANSLATED point (confirmed live via a direct test), so
        the main_window-local rect below is round-tripped through
        panel.parentWidget() (== main_window) instead."""
        settled_rect_in_main_window = QRect(QPoint(0, panel.y()), panel.size())
        global_top_left = panel.parentWidget().mapToGlobal(settled_rect_in_main_window.topLeft())
        top_left = self._common_ancestor.mapFromGlobal(global_top_left)
        return QRect(top_left, panel.size())

    def _compute_bounding_rect(self) -> QRect | None:
        rect: QRect | None = None
        for widget in self._all_tracked_widgets():
            top_left = widget.mapTo(self._common_ancestor, QPoint(0, 0))
            widget_rect = QRect(top_left, widget.size())
            rect = widget_rect if rect is None else rect.united(widget_rect)
        return rect

    def _grab_and_blur(self, rect: QRect) -> QPixmap:
        # ROOT CAUSE (found live, 2026-07-19, after the user directly identified
        # the background color itself as wrong — not a coordinate or blur bug):
        # content_container (_common_ancestor) has NO styled background of its
        # own. main_window's real stylesheet paints bg_main (the theme's actual
        # background color, e.g. Chatsubo's #1A002E purple) and it shows through
        # underneath content_container in normal on-screen compositing — but
        # grab() only rasterizes a widget's OWN paint, never an ancestor's
        # background showing through it. So content_container.grab() was always
        # returning Qt's plain default QPalette window color (#202326 on this
        # system — confirmed to match exactly what every prior corrupted grab
        # showed), regardless of theme. This is why every isolated test using a
        # widget with an explicit background-color came back clean: the test
        # widget always had its OWN background set, unlike the real
        # content_container.
        #
        # Fix: grab from main_window instead (it has the real themed
        # background), translating `rect` (in _common_ancestor/content_container
        # space) into main_window-local coordinates via the same
        # mapToGlobal/mapFromGlobal round-trip already used in
        # _panel_rect_in_common_space (mapTo() is invalid between these two —
        # content_container is a CHILD of main_window here, so mapTo actually
        # would work, but the round-trip keeps the pattern consistent and
        # correct either way).
        #
        # Also: main_window's children include the panel itself, raised above
        # content_container — grabbing main_window while the panel is visible
        # would capture the panel's own translucent wash on top of the real
        # content, double-applying it before blur even runs. The panel must be
        # hidden for the grab too, same as the overlay already is.
        main_window_rect = QRect(
            self.main_window.mapFromGlobal(self._common_ancestor.mapToGlobal(rect.topLeft())),
            rect.size(),
        )

        # Grab with a padding margin, blur the padded pixmap, then crop back to
        # `rect`'s original size. QGraphicsBlurEffect treats "outside the source
        # pixmap" as transparent and blends that transparency into the blurred
        # result near every edge — confirmed live (2026-07-19, the color-shift/
        # hard-edge-tint bug): even a fully opaque solid-color source pixmap came
        # back with alpha as low as 194/255 near its edges after blurring, which
        # then visibly tinted whatever was composited underneath. Since every
        # dirty sub-rect has edges (it's a small region, not the whole window),
        # blurring it directly always hits this artifact on all four sides.
        # Padding pushes the artifact into a margin that gets cropped away before
        # the result is ever composited, so only genuinely blurred, full-alpha
        # pixels survive into the overlay.
        # 4x radius: measured (2026-07-19) to fully converge corner alpha to 255
        # for a solid-color test image — 2x still left visible residual alpha
        # loss (~251/255) at the crop boundary.
        pad = int(_BLUR_RADIUS * 4)
        padded_rect = main_window_rect.adjusted(-pad, -pad, pad, pad)

        overlay_was_visible = self._overlay.isVisible()
        if overlay_was_visible:
            self._overlay.hide()
        panel_was_visible = self._active_panel is not None and self._active_panel.isVisible()
        if panel_was_visible:
            self._active_panel.hide()
        grabbed = self.main_window.grab(padded_rect)
        if panel_was_visible:
            self._active_panel.show()
        if overlay_was_visible:
            self._overlay.show()

        blurred_padded = _blur_pixmap(grabbed)
        # Crop the padding back off — the margin's edge-transparency artifact
        # never reaches the caller. grab()'s automatic clamping at
        # _common_ancestor's real edges (e.g. window bounds) means the crop
        # rect always matches blurred_padded's actual size.
        crop = QRect(pad, pad, rect.width(), rect.height())
        return blurred_padded.copy(crop)
