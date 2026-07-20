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
import time

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QGraphicsBlurEffect, QGraphicsScene, QLabel

logger = logging.getLogger(__name__)

_BLUR_RADIUS = 5.0

# HISTORY: this used to be a fixed-interval QTimer poll (_REFRESH_INTERVAL_MS,
# last value 1200ms, previously tuned through a two-tier attempt that was tried
# and reverted 2026-07-19 — see NOTES.md for that reverted attempt's detail).
# REPLACED (2026-07-20) with an event-driven design: _DirtyRectTracker calls
# TransportBarBlurOverlay._schedule_refresh() directly on every real Paint event
# it observes, which arms a coalescing QTimer.singleShot(0, ...) — never a
# fixed-interval poll. See _schedule_refresh's and _DirtyRectTracker's
# docstrings for why this removes the punch-through-flash collision at its
# source rather than reducing its odds: main_window.grab() is now only ever
# reached in reaction to a widget that just genuinely repainted.

# Root cause (found live, 2026-07-19, the settings-panel "punch-through
# flash" during theme hover): QWidget.grab() renders synchronously and must
# resolve any pending/queued Qt repaint-repolish backlog left by a just-run
# _apply_stylesheets() call — Qt doesn't paint that inline, and grab() forces
# it to resolve synchronously if called too soon after. Measured live across
# many occurrences: normally 5-10ms, but 250-350ms when landing inside this
# backlog window. _COOLDOWN_MS is the skip window after
# ThemeManager._last_apply_stylesheets_at during which refresh_dirty() defers
# its tick rather than colliding with the backlog — 400ms gives margin above
# the measured 250-350ms range. This does NOT fix the underlying cost (a grab
# landing right at the boundary, or a genuinely slower restyle, can still
# collide) — it reduces how often refresh_dirty() specifically is the trigger.
# A skipped tick's dirty union is NOT cleared; the next tick (whenever the
# timer fires again) picks it up.
_POST_RESTYLE_COOLDOWN_S = 0.4

# Feedback-loop guard window (2026-07-20) — see self._grab_suppress_until's
# declaration in TransportBarBlurOverlay.__init__ for the full measurement and
# why this is a wall-clock deadline, not a boolean or a turn count. Measured
# live: every deferred paint _grab_and_blur()'s own hide->grab->show sequence
# triggers on the tracked widgets lands within ~20ms. 50ms gives real margin
# above that.
_GRAB_FEEDBACK_SUPPRESS_S = 0.05


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
    a common coordinate space, without consuming or altering the event.

    CACHED-FRAME REWORK (2026-07-20, replacing the 1200ms polling timer — see
    NOTES.md "punch-through flash" entries for the full collision root cause):
    on each real Paint event, in addition to accumulating the dirty union as
    before, this now calls `on_dirty` (TransportBarBlurOverlay._schedule_refresh)
    to arm a coalescing QTimer.singleShot(0, ...) — NOT a new forcing call, and
    NOT a fixed-interval poll. It only ever fires as a reaction to a real paint
    that already happened, at most once per event-loop turn, so a burst of
    paints (a ClickSlider.animate_to burst, a fast marquee tick) coalesces into
    ONE grab instead of one grab per repaint or one grab per fixed tick
    regardless of activity. This is what makes the refresh genuinely
    opportunistic: main_window.grab() is never called unless something the
    tracker actually observed repainting caused it, and the collision this was
    all about (grab() colliding with a still-settling setStyleSheet() backlog)
    can now only happen when a widget legitimately repainted at that moment —
    never as a side effect of a poll landing at an unlucky instant with nothing
    to actually refresh."""

    def __init__(self, common_ancestor, on_dirty=None, is_suppressed=None):
        super().__init__()
        self._common_ancestor = common_ancestor
        self._dirty_union: QRect | None = None
        self._on_dirty = on_dirty
        # is_suppressed: optional zero-arg callable returning True while paint
        # events should be dropped entirely (not accumulated, not triggering
        # on_dirty) — see TransportBarBlurOverlay._grab_suppress_until, the
        # feedback-loop guard added 2026-07-20.
        self._is_suppressed = is_suppressed

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Paint:
            if self._is_suppressed is not None and self._is_suppressed():
                return False
            top_left = obj.mapTo(self._common_ancestor, QPoint(0, 0))
            rect = QRect(top_left, obj.size())
            self._dirty_union = rect if self._dirty_union is None else self._dirty_union.united(rect)
            if self._on_dirty is not None:
                self._on_dirty()
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

        # CACHED-FRAME REWORK (2026-07-20): no fixed-interval polling timer
        # anymore — see _DirtyRectTracker's class docstring for why. A real
        # Paint event on a tracked widget calls _schedule_refresh(), which arms
        # a coalescing QTimer.singleShot(0, ...) if one isn't already pending.
        # _refresh_pending is the coalescing flag; nothing here fires unless a
        # real repaint happened first.
        self._refresh_pending = False

        # FEEDBACK-LOOP GUARD (2026-07-20, found live during this same rework's
        # own testing): _grab_and_blur()'s hide()->grab()->show() cycle on
        # self._active_panel forces Qt to repaint the tracked transport-bar
        # widgets underneath the panel (momentarily exposed/re-occluded), which
        # the event-driven tracker then saw as real content changes and
        # rescheduled ANOTHER refresh for — which called _grab_and_blur() again,
        # hid/showed the panel again, caused another self-inflicted paint, ad
        # infinitum. Confirmed live: continuous ~10-20ms COMPOSITED ticks that
        # never settled.
        #
        # FIRST ATTEMPT (reverted the same session): a plain try/finally boolean
        # set True for exactly the hide->grab->show call sequence's own duration,
        # cleared immediately after. Did NOT fix the loop — confirmed live it
        # kept ticking. Root cause of that failure, found via a direct isolated
        # PySide6 measurement (paint-event timestamps relative to the hide/show
        # call): Qt does NOT deliver every repaint this sequence triggers
        # synchronously. One paint lands inline (~1ms), but 1-2 MORE land on
        # later event-loop turns — measured consistently within ~20ms of the
        # sequence, never later, across a 200ms observation window with 20ms
        # sampling granularity. A guard that clears the instant the Python call
        # sequence returns closes before those deferred paints arrive, so they
        # slip through and re-trigger the loop exactly as observed live. A
        # single QTimer.singleShot(0, ...) turn-based extension was considered
        # and rejected without shipping it — the same measurement showed paint
        # COUNT still climbing across multiple singleShot(0) turns (1 -> 2 -> 2
        # -> 3), not settling after exactly one, so sizing the guard in "turns"
        # would have been guessing at a number rather than measuring one.
        #
        # FIX: a wall-clock cooldown, not a turn count or a bare boolean.
        # _grab_suppress_until (a perf_counter() deadline, not a boolean) is set
        # every time this window needs to extend — both at the START of the
        # hide->grab->show sequence AND, if the deadline hasn't yet passed,
        # extended forward from each subsequent measured deferred paint. Sized
        # to 50ms — comfortably above the ~20ms window every deferred paint was
        # measured to land within, with real margin. _schedule_refresh() drops
        # any paint event while time.perf_counter() < _grab_suppress_until — not
        # queued for later, simply ignored, per the accepted tradeoff that a
        # genuinely real paint landing in this narrow window may cost one
        # hover-step of staleness in the CACHED BLUR ONLY (the live, unblurred
        # UI is on a separate code path and is never affected), fully
        # self-correcting on the next real paint or forced refresh
        # (tab-switch/panel-open).
        self._grab_suppress_until = 0.0

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
        # TEMP PERF INSTRUMENTATION (2026-07-19, user-requested): measure the
        # mandatory full-rect pass's real cost on panel-open. Remove once the
        # bottleneck is identified and addressed.
        t_entry = time.perf_counter()
        logger.warning(
            f"[PERF] show_for_panel ENTRY panel={panel.objectName()!r} "
            f"t={t_entry:.6f} self._active={self._active}"
        )
        if self._active:
            logger.warning(
                f"[TIMER-TRACE] show_for_panel EARLY-RETURN reason=already_active "
                f"active_panel={self._active_panel.objectName() if self._active_panel else None!r} "
                f"requested_panel={panel.objectName()!r}"
            )
            return
        raw_rect = self._compute_bounding_rect()
        if raw_rect is None or raw_rect.isEmpty():
            logger.warning("[TIMER-TRACE] show_for_panel EARLY-RETURN reason=empty_bounding_rect")
            return
        panel_rect = self._panel_rect_in_common_space(panel)
        self._bounding_rect = raw_rect.intersected(panel_rect)
        if self._bounding_rect.isEmpty():
            logger.warning("[TIMER-TRACE] show_for_panel EARLY-RETURN reason=empty_intersection_with_panel")
            return
        t_rect_done = time.perf_counter()

        self._active_panel = panel
        blurred = self._grab_and_blur(self._bounding_rect)
        t_grab_blur_done = time.perf_counter()
        self._overlay.setPixmap(blurred)
        self._overlay.setGeometry(self._bounding_rect)
        self._overlay.show()
        self._overlay.raise_()
        t_blit_done = time.perf_counter()

        self._tracker = _DirtyRectTracker(
            self._common_ancestor,
            on_dirty=self._schedule_refresh,
            is_suppressed=lambda: time.perf_counter() < self._grab_suppress_until,
        )
        self._tracker_widgets = self._all_tracked_widgets()
        for widget in self._tracker_widgets:
            widget.installEventFilter(self._tracker)
        self._tracker.take_dirty_union()  # reset: the first pass already covers everything

        self._active = True
        logger.warning("[TIMER-TRACE] show_for_panel: event-driven refresh armed (no polling timer)")

        logger.warning(
            f"[PERF] show_for_panel DONE panel={panel.objectName()!r} "
            f"rect={self._bounding_rect} "
            f"rect_compute_ms={(t_rect_done - t_entry) * 1000:.2f} "
            f"grab_and_blur_ms={(t_grab_blur_done - t_rect_done) * 1000:.2f} "
            f"blit_ms={(t_blit_done - t_grab_blur_done) * 1000:.2f} "
            f"total_ms={(t_blit_done - t_entry) * 1000:.2f}"
        )

    def _schedule_refresh(self):
        """Called by _DirtyRectTracker on every real Paint event it observes on a
        tracked widget. Arms a coalescing QTimer.singleShot(0, ...) if one isn't
        already pending — NOT a new forcing call, and NOT a fixed-interval poll.
        A burst of paints (a slider animate_to burst, several fast marquee ticks)
        collapses into exactly one refresh_dirty() call on the next event-loop
        turn, not one per paint and not one per fixed tick regardless of
        activity. This is the actual mechanism that removes the punch-through-
        flash collision: main_window.grab() is now only ever reached as a
        reaction to something that genuinely just repainted, never as a side
        effect of a timer landing at an arbitrary moment with nothing dirty."""
        if self._refresh_pending:
            return
        self._refresh_pending = True
        QTimer.singleShot(0, self.refresh_dirty)

    def refresh_dirty(self):
        """Re-grab+reblur only the union of sub-rects dirtied since the last
        composite (or since show_for_panel's reset), patch it into the overlay
        pixmap. No-op if nothing is dirty or the overlay isn't active. Called via
        _schedule_refresh's coalescing singleShot(0), never on a fixed interval —
        see that method's docstring."""
        self._refresh_pending = False
        # PERMANENT logging (2026-07-20, added while investigating a "blur overlay
        # frozen indefinitely" bug — see NOTES.md/TODO.md). refresh_dirty() has
        # several silent early-return paths below and, before this line existed,
        # produced ZERO log output on a normal early-return tick — meaning "no log
        # lines after show_for_panel DONE" was NOT actually proof the timer had
        # stopped; it was equally consistent with the timer firing exactly on
        # schedule and finding nothing dirty every single tick. This tick counter
        # + early-return-reason log is what makes the NEXT occurrence of the
        # freeze diagnosable: if the timer is genuinely dead, this line stops
        # appearing entirely; if it's firing but always finding nothing dirty,
        # this line keeps appearing with reason='no_dirty' (or similar) forever.
        self._refresh_tick_count = getattr(self, '_refresh_tick_count', 0) + 1
        _tick = self._refresh_tick_count

        if not self._active or self._tracker is None:
            logger.warning(
                f"[TIMER-TRACE] refresh_dirty tick={_tick} EARLY-RETURN "
                f"reason=inactive_or_no_tracker active={self._active} "
                f"tracker_is_none={self._tracker is None}"
            )
            return

        # HOVER GATE (2026-07-20 — theme-bleed Mechanism B / audit Path D,
        # Audit_ThemeReach_260720.md): a hover-preview restyle rewrites
        # content_container's stylesheet, which forces Qt to repaint every
        # tracked transport-bar widget (they inherit content_container's QSS),
        # which fires a real Paint event, which this tracker correctly sees as
        # "something changed" and schedules a refresh for. Without this gate,
        # _grab_and_blur() below grabs main_window's LIVE composited frame at
        # that instant — which is showing the hovered theme's colors — and
        # bakes it into the overlay pixmap, confirmed live (screenshot,
        # 2026-07-20) as the visible "hover pulsates into the blurred area"
        # bug. Declining here (not consuming take_dirty_union()) is safe
        # specifically for the hover case: _on_theme_unhovered's own snapback
        # restyle (_apply_stylesheets(hover=False)) sets _is_hover_active=False
        # BEFORE it runs (see _on_theme_changed's write order) and itself
        # repaints the same tracked widgets, producing a fresh real Paint event
        # that re-arms _schedule_refresh and lands here with the gate now
        # clear — so hover-end self-corrects via the normal event-driven path,
        # no separate force_refresh_now-style call needed. This gate does NOT
        # cover the general "declined tick has no timer to retry itself"
        # gap — see NOTES.md/TODO.md, flagged as a candidate mechanism for the
        # still-open frozen-overlay bug, deliberately not touched here.
        theme_manager = getattr(self.main_window, 'theme_manager', None)
        if getattr(theme_manager, '_is_hover_active', False):
            logger.warning(f"[TIMER-TRACE] refresh_dirty tick={_tick} EARLY-RETURN reason=hover_active_gate")
            return

        # See _POST_RESTYLE_COOLDOWN_S's declaration above for the root cause
        # and measured numbers this gates against. Checked BEFORE
        # take_dirty_union() so a skipped tick leaves the accumulated dirty
        # union untouched in the tracker for the next tick to pick up — nothing
        # is consumed or dropped, this tick just declines to act on it yet.
        last_restyle = getattr(theme_manager, '_last_apply_stylesheets_at', None)
        if last_restyle is not None and (time.perf_counter() - last_restyle) < _POST_RESTYLE_COOLDOWN_S:
            logger.warning(f"[TIMER-TRACE] refresh_dirty tick={_tick} EARLY-RETURN reason=cooldown_gate")
            return

        dirty = self._tracker.take_dirty_union()
        if dirty is None:
            logger.warning(f"[TIMER-TRACE] refresh_dirty tick={_tick} EARLY-RETURN reason=no_dirty")
            return
        dirty = dirty.intersected(self._bounding_rect)
        if dirty.isEmpty():
            logger.warning(f"[TIMER-TRACE] refresh_dirty tick={_tick} EARLY-RETURN reason=dirty_empty_after_intersect")
            return

        blurred_slice = self._grab_and_blur(dirty)
        current = self._overlay.pixmap()
        if current is None or current.isNull():
            logger.warning(f"[TIMER-TRACE] refresh_dirty tick={_tick} EARLY-RETURN reason=overlay_pixmap_null")
            return
        combined = QPixmap(current)
        painter = QPainter(combined)
        local = dirty.translated(-self._bounding_rect.topLeft())
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        painter.drawPixmap(local.topLeft(), blurred_slice)
        painter.end()
        self._overlay.setPixmap(combined)
        logger.warning(f"[TIMER-TRACE] refresh_dirty tick={_tick} COMPOSITED dirty={dirty}")

    def force_refresh_now(self):
        """ONE-TIME forced full-rect re-grab, for known content-change events
        that don't necessarily produce a Paint event on any of the 12 tracked
        widgets (a settings-tab switch changes what's visible/selected in the
        settings_panel itself, not in the transport bar's own widgets, so
        _DirtyRectTracker would never see it). Not a hot loop, not called on
        hover — wired only to QTabWidget.currentChanged (panels.py) and
        show_for_panel's own existing mandatory first pass. No-op if the overlay
        isn't currently active, same as every other entry point here."""
        if not self._active or self._bounding_rect is None:
            return
        logger.warning("[TIMER-TRACE] force_refresh_now: tab-switch triggered full-rect refresh")
        blurred = self._grab_and_blur(self._bounding_rect)
        self._overlay.setPixmap(blurred)
        if self._tracker is not None:
            self._tracker.take_dirty_union()  # this pass already covers everything just grabbed

    def hide_for_panel(self):
        """Fallback slide-out behavior: tear down unconditionally. Called from
        the panel's *_hidden handler (after the close animation finishes), not
        during the slide itself — see the accepted plan's §6 for why live-
        dissolve-during-slide is deferred, not implemented here."""
        logger.warning(
            f"[TIMER-TRACE] hide_for_panel ENTRY active={self._active} "
            f"active_panel={self._active_panel.objectName() if self._active_panel else None!r} "
            f"refresh_pending={self._refresh_pending} "
            f"tick_count_this_session={getattr(self, '_refresh_tick_count', 0)}"
        )
        self._refresh_tick_count = 0
        # No timer to .stop() anymore (event-driven, not polled — see
        # _DirtyRectTracker's docstring). Any already-armed singleShot(0) from a
        # paint that happened right before close will still fire once, but
        # refresh_dirty()'s own `if not self._active` guard (unchanged) makes
        # that a harmless no-op — same safety property the old timer.stop() gave,
        # without needing an explicit cancel.
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
        #
        # ATTEMPTED FIX, REVERTED SAME DAY (2026-07-19): grabbing
        # content_container directly (no panel in its subtree, so no
        # hide()/show() needed) with a bg_main solid-fill composited underneath,
        # to avoid the hide()/show() cost measured below. This introduced TWO
        # new bugs, live-confirmed: (1) the blurred region came out visibly
        # larger and shifted right vs. the real transport bar underneath — a
        # devicePixelRatio handling gap in the new canvas-compositing code, only
        # partially fixed before the second bug below was found; (2) far more
        # seriously, theme hover-preview/snapback broke — hovering a swatch
        # started leaving the app's actual colors on the hovered theme instead
        # of the active one, and un-hovering no longer correctly reverted.
        # Mechanism for (2) was NOT diagnosed before reverting — the change
        # only added a read-only theme_manager.get_current_theme() call and
        # removed the panel hide()/show() pair, neither of which should
        # logically touch hover/snapback state, but the regression was
        # reproducible. Do not re-attempt the content_container approach
        # without first understanding why removing the hide()/show() pair (or
        # adding the get_current_theme() read) disturbs hover/snapback — this
        # is a real, serious, unexplained coupling, not a cosmetic issue.
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

        # TEMP PERF INSTRUMENTATION (2026-07-19, user-requested): break down
        # grab/blur/crop individually. Remove once the bottleneck is identified.
        t0 = time.perf_counter()

        # FEEDBACK-LOOP GUARD (2026-07-20) — see the declaration comment on
        # self._grab_suppress_until in __init__ for the full mechanism and why
        # this is a wall-clock deadline, not a boolean cleared the instant this
        # Python call sequence returns (that was tried first and confirmed live
        # NOT to work — Qt delivers some of this sequence's self-inflicted
        # repaints on later event-loop turns, after a bare try/finally boolean
        # had already cleared). try/finally still guarantees the deadline is set
        # (never left un-set) even if something in this block raises.
        try:
            self._grab_suppress_until = time.perf_counter() + _GRAB_FEEDBACK_SUPPRESS_S
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
        finally:
            self._grab_suppress_until = time.perf_counter() + _GRAB_FEEDBACK_SUPPRESS_S
        t1 = time.perf_counter()

        blurred_padded = _blur_pixmap(grabbed)
        t2 = time.perf_counter()

        # Crop the padding back off — the margin's edge-transparency artifact
        # never reaches the caller. grab()'s automatic clamping at
        # _common_ancestor's real edges (e.g. window bounds) means the crop
        # rect always matches blurred_padded's actual size.
        crop = QRect(pad, pad, rect.width(), rect.height())
        result = blurred_padded.copy(crop)
        t3 = time.perf_counter()

        logger.warning(
            f"[PERF] _grab_and_blur rect={rect} padded_rect={padded_rect} "
            f"grab_ms={(t1 - t0) * 1000:.2f} blur_ms={(t2 - t1) * 1000:.2f} "
            f"crop_ms={(t3 - t2) * 1000:.2f} total_ms={(t3 - t0) * 1000:.2f}"
        )
        return result
