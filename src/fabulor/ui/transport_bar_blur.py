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
  3. On panel-open, the overlay fades in (opacity 0->1) once it's shown, so
     the transport bar doesn't blur-in instantly. On panel-close: torn down
     immediately at the START of the close animation (not the end) so the
     transport bar returns to live view right away instead of staying blurred
     through the whole slide-out. No live-tracking during either transition
     (deferred per the plan).

vol_stack (sleep_timer_label / volume_slider / muted_icon_label) is a
QStackedWidget where only one page is ever actually shown — an inactive page
reports bogus geometry (Qt's default-widget size sentinel, since it's never
been laid out while hidden), so only vol_stack.currentWidget() is tracked,
resolved fresh via _vol_stack_active_widget() on every bounding-rect
computation and every show_for_panel() call (never cached), since the active
page can change while a panel stays open.
"""
import logging
import os
import time

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPoint, QPropertyAnimation, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QFontMetrics, QPainter, QPixmap
from PySide6.QtWidgets import (
    QGraphicsBlurEffect, QGraphicsOpacityEffect, QGraphicsScene, QLabel,
    QPushButton, QWidget,
)

logger = logging.getLogger(__name__)

# GRAB-LOOP PROBE (2026-08-14). Instruments the self-sustaining hide/show
# feedback loop documented in NOTES.md ("Bug 2", 2026-07-27, still open) and
# re-measured 2026-08-14: [DIRTY-TRACE] logs every Paint the tracker actually
# accepts (i.e. what SURVIVES _grab_suppress_until), [GRAB-ENTRY] logs each
# grab's entry time so entry-to-entry gaps can be derived without folding in
# the grab's own cost.
#
# Env-gated rather than deleted: this is the verification instrument for any
# future fix to that loop, and the 2026-07-27 session's version was thrown away
# and had to be rewritten from scratch tonight. Off by default, so it costs one
# module-level bool comparison per paint when disabled. Same shape as
# panels.py's FABULOR_STUTTER_PROFILE.
#
#     FABULOR_GRAB_TRACE=1 python main.py
#
# Analysis: read gaps CHRONOLOGICALLY, never sorted — the loop shows up as a
# run of ~60-64ms gaps, and a median hides it completely (CLAUDE.md).
_GRAB_TRACE_ENABLED = os.environ.get("FABULOR_GRAB_TRACE") == "1"

# [OVERLAY-DUMP] probe (2026-08-15, compositing-coherence investigation) — a
# one-shot dump of the overlay's live pixmap plus a fresh full-region grab of
# the same area at the same instant, saved as PNGs, so the two can be diffed
# by eye/pixel to answer "is the frozen surrounding region stale content, or
# correct content at wrong geometry". Fires on the NEXT refresh_dirty COMPOSITE
# after the env var is set (a real dirty tick already has both the current
# overlay pixmap and the machinery to grab a fresh one in scope — no separate
# grab/composite path needed, so this cannot touch grab or compositing logic).
# Read once at import; toggling the env var after launch has no effect,
# matching FABULOR_GRAB_TRACE's own contract.
_DUMP_OVERLAY_ENABLED = os.environ.get("FABULOR_DUMP_OVERLAY") == "1"

_BLUR_RADIUS = 5.0
# Manual-paint content redraw (2026-08-17): next_button's icon and
# speed_button's text are the only two pieces of button CONTENT the frost
# needs to redraw on top of the manual hover/pressed fill — they're the two
# buttons that straddle the panel edge into the live sliver (see
# _button_overlay_rect's own comment), the other four sit fully under an
# opaque panel and are never redrawn. _BLUR_RADIUS (5.0) is tuned for the
# whole grabbed BACKGROUND region with a large padding margin
# (_grab_and_blur's pad = radius*4); applied directly to a small icon/text
# pixmap with no comparable padding it would smear past legibility. This is
# a separate, smaller radius for icon/text-scale content — tuned live
# against how the rest of the frost actually looks (1.5 read too crisp
# against the surrounding blur, 2026-08-17).
_CONTENT_BLUR_RADIUS = 6.0
# Pressed-state poll (2026-08-17) — see _pressed_poll_tick's docstring. Qt's
# MouseMove delivery during a mouse grab (an active button press) can gap by
# 1.5s+ during a slow drag (measured live via [PRESS-BORDER-TRACE] — a real
# repro showed zero MouseMove events for 1.6s while the cursor was slowly
# leaving a pressed button's rect), so a MouseMove-reactive sync visibly
# lagged the real widget. 50ms keeps the lag imperceptible for a press/
# release without meaningfully adding to refresh_dirty's own per-tick cost —
# this only reads QCursor.pos() + a rect containment test, no grab/blur/
# composite work. (Originally read isDown() instead — see _pressed_poll_tick's
# docstring for why that signal was replaced the same day.)
_PRESSED_POLL_MS = 50
# Release debounce (2026-08-17) — kept when the poll's signal was changed from
# isDown() to cursor-vs-rect containment (see _pressed_poll_tick's docstring).
# Originally sized against a confirmed isDown() defect: QPushButton.isDown()
# could read a single transient False mid-hold, correlated with
# _grab_and_blur's panel hide/show cycle (a [GRAB-ENTRY] landed 22-30ms before
# a spurious isDown() False on speed_btn during an otherwise-continuous 4.7s
# hold, cursor never moved) — the same underlying hide/show-perturbs-Qt's-
# live-pointer-state hazard as the tassel hand-cursor flicker (_grab_and_blur's
# own CURSOR-FLICKER-FIX comments). That specific hazard does not apply to a
# geometric containment check (it depends only on the button's own geometry
# and the live cursor position, neither of which the grab cycle perturbs), but
# the debounce is retained regardless — it also absorbs an ordinary one-tick
# boundary flicker right at the rect edge, which is a real (if much smaller)
# source of noise for any poll-based containment test. A tick-count debounce
# was considered and rejected: grabs fire every ~5-15ms (the documented
# grab-feedback-loop cadence elsewhere in this file), frequently enough that a
# fixed N-tick debounce could still get unlucky within a multi-second hold. A
# WALL-CLOCK duration is more robust than a tick count because it doesn't
# assume ticks land evenly spaced.
_RELEASE_DEBOUNCE_S = 0.15
# Fade-IN only, on appear — dismiss stays instant (see hide_for_panel) so the
# transport bar snaps back to live view the moment the panel starts closing.
_FADE_IN_MS = 1500

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
#
# THIS GUARD IS UNCHANGED BY THE PER-SOURCE RATE LIMITS BELOW (2026-08-15) —
# it stays read in _grab_and_blur (via self._grab_suppress_until) for its
# original purpose, self-inflicted repaint suppression after a grab. The
# per-category windows are a SEPARATE, independent gate checked earlier, in
# _DirtyRectTracker.eventFilter — a dirty event must pass BOTH to schedule a
# grab. Confirmed live (2026-08-14/15, [PLAYBTN-PAINT] investigation) that
# this guard does NOT catch play_pause_button's grab-driven feedback loop
# (42% of its repaints arrive just after the 50ms window expires, in the
# 50-70ms band) — the per-category windows do not fix that either; they
# only reduce how often small per-widget grabs are scheduled in the first
# place. Different mechanism, different fix, not attempted in this pass.
_GRAB_FEEDBACK_SUPPRESS_S = 0.05

# Per-source rate limits (2026-08-15) — gate whether a dirty event from a
# given widget CATEGORY schedules a grab at all, independent of
# _GRAB_FEEDBACK_SUPPRESS_S above (which gates whether a scheduled grab
# actually executes). See _DirtyRectTracker.eventFilter for where both are
# checked, and TransportBarBlurOverlay.__init__ for the category map.
#
# _SUPPRESS_MARQUEE_S is a TEST VALUE, not calibrated — see TODO.md.
# _SUPPRESS_SLIDER_S is a FLOOR, fixed for this pass — proportional scaling
# by chapter duration is deferred (needs a chapter-duration injection point
# from app.py; PanelManager has no chapter-change signal today — see
# TODO.md and _DirtyRectTracker.set_chapter_duration).
_SUPPRESS_IMMEDIATE_S = 0.0
_SUPPRESS_MARQUEE_S = 0.100
_SUPPRESS_TIME_S = 0.500
_SUPPRESS_SLIDER_S = 0.200

# Retry delay for a tick turned away by one of refresh_dirty()'s two DECLINING
# gates (hover-active, post-restyle cooldown) — see _rearm_after_decline() for
# why a declined tick cannot rely on "the next real paint picks it up". Sized
# above _POST_RESTYLE_COOLDOWN_S (0.4s) so one retry normally clears the
# cooldown window outright instead of re-declining repeatedly; the hover gate
# clears on its own timescale (cursor movement) and simply retries until then.
_DECLINE_REARM_MS = 450

# SLIDER-DRAG GATE (2026-07-31). CURRENT AGAIN as of 2026-08-15 — briefly
# HISTORICAL between 2026-08-14 and 2026-08-15 while the grab source was
# content_container (see below), but that source was reverted and the panel
# hide this gate defends against is back in _grab_and_blur.
#
# As written: _grab_and_blur() hides the active panel for the duration of its
# grab, and hiding a widget mid-drag destroys QAbstractSlider's in-progress drag
# state — the slider keeps receiving MouseMove events but its value stays pinned
# at the press-time value, so the handle doesn't move at all. Confirmed live on
# the Stats Day/Week/Month scrollbars (every failing drag showed a dense
# MouseMove stream interleaved with Hide/Show pairs timestamp-matched to
# _grab_and_blur, value never advancing; working drags contained no Hide/Show at
# all) and reproduced in isolation (an identical synthetic drag yields 324 with
# no hide/show, 0 when the panel is hidden on even every third move).
#
# THE FAILED ATTEMPT, preserved verbatim — a DIFFERENT change from the one that
# superseded it, and would still fail if repeated: skipping only the panel-hide
# *while still grabbing main_window* was tried first and REVERTED the same day
# (2026-07-31/2026-07-19 era) — the grab then photographs the panel itself, so
# the overlay composites panel-over-panel and the transport region reads as
# transparent. Against a main_window grab the hide is not incidental, it IS the
# grab.
#
# HISTORY, for anyone reading this gate's git blame: 2026-08-14 changed the
# grab source to content_container instead (the panel is not inside it, so
# there was nothing to hide, and this gate's own root cause was gone for that
# one day). That change was reverted 2026-08-15 — content_container.grab()
# returns opaque, wrongly-colored pixels for anything it doesn't paint itself,
# which produced a different, real visual defect (see _grab_and_blur's
# docstring). main_window + panel-hide is the grab source again, so this gate
# is defending a live hazard, not a historical one — do not remove it or treat
# it as dead code again without re-confirming the grab source first.
#
# _DRAG_WATCH_MS polls for the drag ending (a slider emits no signal this class
# observes, and the grab that would otherwise notice is the thing suspended).
_DRAG_WATCH_MS = 100


def panel_rect_in_common_space(panel, common_ancestor) -> QRect:
    """`panel`'s TARGET (settled, post-slide-in) geometry, mapped into
    `common_ancestor`'s coordinate space — NOT its live/current position.

    SHARED (2026-07-27): extracted from TransportBarBlurOverlay so the
    visual_area clipped-blur derives its clip boundary from the SAME panel rect
    by the same rules — one clip mechanism, not two that can drift apart. Both
    callers use this; do not re-derive panel geometry anywhere else.

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

    `panel` is a raw child of main_window while `common_ancestor`
    (content_container) is a SIBLING of panel, not an ancestor of it — Qt's
    widget.mapTo(target, ...) only works when `target` is in `widget`'s
    parent hierarchy (an ancestor); called on siblings it emits
    "QWidget::mapTo(): parent must be in parent hierarchy" and silently
    returns an UNTRANSLATED point (confirmed live via a direct test), so
    the main_window-local rect below is round-tripped through
    panel.parentWidget() (== main_window) instead."""
    settled_rect_in_main_window = QRect(QPoint(0, panel.y()), panel.size())
    global_top_left = panel.parentWidget().mapToGlobal(settled_rect_in_main_window.topLeft())
    top_left = common_ancestor.mapFromGlobal(global_top_left)
    return QRect(top_left, panel.size())


def _dragging_slider(panel):
    """The QAbstractSlider inside `panel` that is currently mid-drag, or None.

    Checks QAbstractSlider rather than QScrollBar because the defect this gates
    against belongs to the base class's drag handling, so it applies equally to
    a panel's ClickSliders. isVisible() is required: a slider on a hidden tab can
    retain a stale sliderDown from its own interrupted drag, and without this
    check that stale flag would suppress grabs for the rest of the session."""
    from PySide6.QtWidgets import QAbstractSlider
    for slider in panel.findChildren(QAbstractSlider):
        if slider.isSliderDown() and slider.isVisible():
            return slider
    return None


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
    # DPR must be carried across explicitly: QPixmap(size) always comes back at
    # 1.0 regardless of the source (measured 2026-08-14), so without this the
    # blur silently strips DPR off the frame mid-pipeline. Stamped BEFORE
    # painting, so the render target rect below is interpreted in logical
    # coordinates — matching QGraphicsScene.render()'s own expectations.
    out.setDevicePixelRatio(pixmap.devicePixelRatio())
    out.fill(Qt.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.Antialiasing)
    scene.render(
        painter,
        QRect(QPoint(0, 0), pixmap.deviceIndependentSize().toSize()),  # LOGICAL
        scene.itemsBoundingRect(),
    )
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

    def __init__(self, common_ancestor, on_dirty=None, is_suppressed=None,
                 category_of=None, suppress_window_for=None):
        super().__init__()
        self._common_ancestor = common_ancestor
        self._dirty_union: QRect | None = None
        self._on_dirty = on_dirty
        # is_suppressed: optional zero-arg callable returning True while paint
        # events should be dropped entirely (not accumulated, not triggering
        # on_dirty) — see TransportBarBlurOverlay._grab_suppress_until, the
        # feedback-loop guard added 2026-07-20. Independent of the per-category
        # gate below — both must pass for a dirty event to schedule a grab.
        self._is_suppressed = is_suppressed
        # category_of(obj) -> category string; suppress_window_for(category) ->
        # seconds. Both optional callables (not a dict) so the OVERLAY owns the
        # widget-identity map — see its __init__ — and this tracker stays free
        # of any main_window/widget-list coupling, matching its existing shape.
        self._category_of = category_of
        self._suppress_window_for = suppress_window_for
        self._last_grab_by_category: dict[str, float] = {}
        # Reserved for the proportional slider rate (deferred — see TODO.md).
        # Not read anywhere yet: the slider category currently always uses the
        # fixed _SUPPRESS_SLIDER_S floor via suppress_window_for("slider").
        self._chapter_duration_s: float = 0.0

    def set_chapter_duration(self, seconds: float) -> None:
        """Stub for the proportional slider rate — not implemented this pass.
        No caller exists yet: PanelManager has no chapter-change signal to
        wire it from (confirmed at Checkpoint A), and app.py is out of scope
        for this pass. Safe to leave unwired; the slider stays at its fixed
        floor until this is connected."""
        self._chapter_duration_s = seconds

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Paint:
            if self._is_suppressed is not None and self._is_suppressed():
                return False
            # Placed AFTER the _is_suppressed() early-return on purpose: the
            # question this probe answers is what SURVIVES the 50ms guard, which
            # is exactly what it fails to catch against the loop's ~64ms
            # round-trip. Measured 2026-08-14: 565 of 702 accepted paints landed
            # in the 50-70ms band, none inside the guard.
            if _GRAB_TRACE_ENABLED:
                logger.warning(
                    f"[DIRTY-TRACE] w={obj.objectName() or type(obj).__name__} "
                    f"ev_rect={event.rect()} size={obj.size()} t={time.perf_counter():.6f}"
                )
            # PER-SOURCE RATE LIMIT (2026-08-15) — a second, independent gate
            # from _is_suppressed above. That guard is global (one deadline for
            # every source); this one is per-CATEGORY, so a fast-repainting
            # marquee can't starve a slow-repainting time label of its own
            # budget, or vice versa. A category with no window configured
            # (category_of/suppress_window_for absent, or an unmapped obj)
            # falls through unsuppressed — never silently defaulted to a
            # window that wasn't explicitly chosen for it.
            if self._category_of is not None and self._suppress_window_for is not None:
                category = self._category_of(obj)
                if category is not None:
                    window = self._suppress_window_for(category)
                    now = time.perf_counter()
                    last = self._last_grab_by_category.get(category, 0.0)
                    if now - last < window:
                        return False
                    self._last_grab_by_category[category] = now
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


class _HoverPaintFilter(QObject):
    """QEvent.Enter/Leave filter for manual button-hover painting (2026-08-16).
    Same shape as _DirtyRectTracker above — a small dedicated QObject, not the
    owning TransportBarBlurOverlay itself, which is a plain class and cannot
    be installEventFilter's target directly. Intercepts ONLY Enter/Leave on
    the widgets it's installed on; every other event passes through
    unconsumed, same contract as _DirtyRectTracker's own eventFilter."""

    def __init__(self, overlay):
        super().__init__()
        self._overlay = overlay

    def eventFilter(self, obj, event):
        # TEMP TRACE (2026-08-17, missing-Press investigation) — unconditional,
        # every event type, no branching. Remove once the cause is found.
        if _GRAB_TRACE_ENABLED:
            logger.warning(
                f"[ALL-EVENTS-TRACE] obj={obj.objectName()!r} "
                f"type={event.type()!r} spontaneous={event.spontaneous()}"
            )
        if event.type() == QEvent.Type.Enter:
            self._overlay._paint_button_hover(obj)
            self._overlay._hovered_buttons.add(obj)
        elif event.type() == QEvent.Type.Leave:
            self._overlay._restore_button_from_snapshot(obj)
            self._overlay._hovered_buttons.discard(obj)
            self._overlay._set_pressed(obj, False)
        elif event.type() == QEvent.Type.MouseButtonPress:
            # Pressed SESSION (2026-08-17, revised same day — see
            # _mouse_down_buttons' own comment). A press always arrives with
            # the cursor already inside (Qt only delivers MouseButtonPress to
            # the widget under the cursor), so _hovered_buttons already has
            # obj — no separate add needed there. This opens the session; the
            # poll paints/repaints within it based on live cursor geometry.
            self._overlay._mouse_down_buttons.add(obj)
            self._overlay._set_pressed(obj, True)
            self._overlay._arm_pressed_poll()
        elif event.type() == QEvent.Type.MouseButtonRelease:
            # Unconditional session close — the ONE authoritative signal that
            # ends a pressed session, regardless of what the poll's geometric
            # check currently believes (drag-off-then-release, drag-back-in-
            # then-release, release exactly at the boundary — all the same
            # instruction: stop tracking this button now).
            self._overlay._mouse_down_buttons.discard(obj)
            self._overlay._set_pressed(obj, False)
            self._overlay._disarm_pressed_poll_if_idle()
            # Release-while-still-over reverts to :hover, not the unhovered
            # base state — matches real QSS button behavior, and obj is still
            # in _hovered_buttons (no Leave fired) so this is just repainting
            # what should already be showing. A release after the cursor left
            # the button (drag-off-then-release) is already handled: Leave
            # already ran _restore_button_from_snapshot and discarded obj from
            # _hovered_buttons, so repainting hover here would be wrong for
            # that case — guard on membership.
            if obj in self._overlay._hovered_buttons:
                self._overlay._paint_button_hover(obj)
        # NOTE: no MouseMove branch. An earlier version tried tracking
        # press/leave/re-entry during a grab off MouseMove + isDown() — see
        # _pressed_poll_tick's own docstring for why that was replaced with a
        # poll instead of extended further.
        return False  # never consume — must not affect real hover/click delivery


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

        # Per-source rate-limit category map (2026-08-15) — keyed by OBJECT
        # IDENTITY, never by objectName()/string, per the accepted plan. Built
        # here (not in _DirtyRectTracker) so the tracker never needs a
        # main_window/widget-list reference — matching its existing shape,
        # which takes only common_ancestor + callables. Passed to the tracker
        # as two lookup callables (_category_of/_suppress_window_for) at both
        # construction sites below.
        #
        # Exhaustive: every widget _all_tracked_widgets() can ever return is
        # listed once, including all three possible vol_stack pages (only one
        # is live at a time, resolved dynamically by _vol_stack_active_widget,
        # but the map itself is static and covers all three so a mute/sleep/
        # volume-interaction transition never lands on an unmapped widget).
        self._category_by_widget: dict[int, str] = {
            id(w): "immediate" for w in (
                main_window.prev_button,
                main_window.rewind_button,
                main_window.forward_button,
                main_window.next_button,
                main_window.speed_button,
                main_window.sleep_timer_label,   # vol_stack page 0
                main_window.volume_slider,       # vol_stack page 1's real content
                main_window.muted_icon_label,    # vol_stack page 2
            )
        }
        self._category_by_widget[id(main_window.play_pause_button)] = "play"
        self._category_by_widget[id(main_window.current_chapter_label)] = "marquee"
        for w in (main_window.chap_elapsed_label, main_window.chap_duration_label,
                  main_window.current_time_label, main_window.total_time_label):
            self._category_by_widget[id(w)] = "time"
        self._category_by_widget[id(main_window.chapter_progress_slider)] = "slider"

        self._suppress_window_by_category = {
            "immediate": _SUPPRESS_IMMEDIATE_S,
            "play": _SUPPRESS_IMMEDIATE_S,
            "marquee": _SUPPRESS_MARQUEE_S,
            "time": _SUPPRESS_TIME_S,
            "slider": _SUPPRESS_SLIDER_S,
        }

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

        # Fade-in only (see _FADE_IN_MS). Dismiss (hide_for_panel) sets the
        # opacity effect's own opacity back to 1.0 and tears it down instantly
        # — no animation on the way out.
        self._opacity_effect = QGraphicsOpacityEffect(self._overlay)
        self._opacity_effect.setOpacity(1.0)
        self._overlay.setGraphicsEffect(self._opacity_effect)
        self._fade_in_anim = QPropertyAnimation(self._opacity_effect, b"opacity")
        self._fade_in_anim.setDuration(_FADE_IN_MS)
        self._fade_in_anim.setStartValue(0.0)
        self._fade_in_anim.setEndValue(1.0)
        self._fade_in_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._tracker: _DirtyRectTracker | None = None
        self._tracker_widgets: list = []  # widgets the tracker's filter is actually
                                           # installed on — NOT recomputed via
                                           # _all_tracked_widgets() at removal time,
                                           # since the vol_stack active page can
                                           # change mid-open (see hide_for_panel).
        self._bounding_rect: QRect | None = None
        self._active = False
        self._active_panel = None  # set in show_for_panel, cleared in hide_for_panel.
                                    # Default `panel` for _grab_and_blur's hide/show
                                    # (main_window grab source, restored 2026-08-15 —
                                    # see that function's docstring). Also read by
                                    # _panel_hides_everything, the drag gate and
                                    # frost_panel_backdrop (which passes its own
                                    # `panel` explicitly instead of this default).
        self._panel_open_snapshot: QPixmap | None = None  # set once per
            # panel-open in show_for_panel (a copy of the same clean grab
            # self._overlay is shown with), read-only thereafter, cleared in
            # hide_for_panel. Display/identity state, same category as
            # _bounding_rect/_active_panel above — deliberately NOT cleared in
            # _disarm_grabbing, so a parked frame (park_for_panel) keeps its
            # snapshot intact exactly like it keeps everything else in this
            # group intact; see park_for_panel's own docstring. Manual-paint
            # hover fix (2026-08-16): the restore source for
            # _restore_button_from_snapshot when a button's hover ends —
            # painting the button's real appearance back rather than a flat
            # placeholder, since it's a real clean grab, not a synthetic fill.
        self._hover_buttons: list = []  # the QPushButton-family tracked
            # widgets with self._hover_filter installed for manual hover
            # painting. Populated in show_for_panel/unpark_for_panel, cleared
            # in _disarm_grabbing (the "stop producing new frames" half, NOT
            # hide_for_panel's display/identity half — mirrors _tracker/
            # _tracker_widgets' own lifecycle exactly, not _bounding_rect's).
        self._hovered_buttons: set = set()  # WHICH of _hover_buttons currently
            # has manual hover paint showing right now (2026-08-17, dirty-composite
            # overwrite fix) — distinct from _hover_buttons itself, which is the
            # fixed list of buttons the filter is installed ON, not which of them
            # are hovered at this instant. Populated in _HoverPaintFilter.eventFilter
            # on Enter, discarded on Leave. Same "active-state, not display/identity"
            # category as _hover_buttons — cleared in _disarm_grabbing, not
            # hide_for_panel: while parked, nothing should be re-painting hover
            # state into a pixmap park_for_panel needs to stay static.
        self._pressed_buttons: set = set()  # WHICH of _hover_buttons currently
            # has manual PRESSED paint showing (2026-08-17). Same shape/lifecycle
            # as _hovered_buttons — see that attribute's own comment; the two are
            # deliberately separate sets (a button is exactly one of unhovered/
            # hovered/pressed at a time, never both hovered- and pressed-painted
            # simultaneously — MouseButtonRelease repaints hover, not both).
            # PAINT STATE ONLY — see _mouse_down_buttons below for the session
            # boundary. Do NOT use membership here to decide whether the real
            # mouse button is still down; a button can be down (a live
            # session) while NOT in this set (cursor currently outside the
            # rect, painted as hover/idle instead).
        self._mouse_down_buttons: set = set()  # WHICH buttons have a real,
            # currently-open MouseButtonPress/Release session (2026-08-17,
            # multi-crossing fix). This is the SOLE authority for "is the
            # mouse physically down on this button right now" — opened only by
            # a real MouseButtonPress, closed only by a real
            # MouseButtonRelease, NEVER by the poll. _pressed_buttons above is
            # a separate, PAINT-state set the poll toggles freely in both
            # directions while a button is in this set.
            #
            # Root cause this fixes (found live, 2026-08-17): the poll used to
            # iterate _pressed_buttons directly and only ever discover exits
            # (inside->outside), calling _set_pressed(False) — which both
            # repaints AND removes the button from _pressed_buttons. Once
            # removed, the SAME poll loop (`for button in
            # self._pressed_buttons`) can never see that button again, so a
            # later re-entry (outside->inside) during the SAME held press was
            # silently never detected — confirmed live: "right side clears,
            # then left side catches up... I continue to press and cross the
            # button multiple times... left side never changes" after the
            # first exit. Iterating this SEPARATE, session-scoped set instead
            # (which the poll never mutates) lets the poll freely call
            # _set_pressed(True) on re-entry and _set_pressed(False) on exit,
            # any number of times, for as long as the real session stays open.
        self._pressed_false_since: dict = {}  # button -> perf_counter() of the
            # FIRST poll tick that read the cursor as OUTSIDE the button's rect
            # since the last inside read (2026-08-17, release debounce — see
            # _RELEASE_DEBOUNCE_S; originally keyed off isDown()==False, revised
            # same day to cursor-vs-rect containment, see _pressed_poll_tick's
            # docstring). A button is only actually released by the poll once
            # "outside" has persisted for that long; entry is removed the
            # instant the cursor reads inside again. Keyed only by buttons
            # currently being polled — _set_pressed(True) via a fresh Press
            # always starts a button with no entry here. A real
            # MouseButtonRelease bypasses this entirely (see _set_pressed) —
            # this dict only debounces the POLL's own decision.
        self._pressed_poll_timer = QTimer(main_window)  # polls cursor-vs-rect
            # containment (originally isDown(), revised 2026-08-17 same day —
            # see _pressed_poll_tick's own docstring) while any button is
            # pressed. Armed/disarmed only by _set_pressed, on _pressed_buttons'
            # empty<->non-empty transitions — mirrors _sidebar_idle_poll_timer's
            # convention (panels.py): a repeating QTimer started/stopped only on
            # one condition's transition edges, never scattered start/stop calls.
        self._pressed_poll_timer.setInterval(_PRESSED_POLL_MS)
        self._pressed_poll_timer.timeout.connect(self._pressed_poll_tick)
        self._hover_filter = _HoverPaintFilter(self)  # constructed once,
            # reused across every panel-open — it holds no per-open state of
            # its own (unlike _tracker, which IS rebuilt fresh each open,
            # since it accumulates a dirty union that must reset).

        # CACHED-FRAME REWORK (2026-07-20): no fixed-interval polling timer
        # anymore — see _DirtyRectTracker's class docstring for why. A real
        # Paint event on a tracked widget calls _schedule_refresh(), which arms
        # a coalescing QTimer.singleShot(0, ...) if one isn't already pending.
        # _refresh_pending is the coalescing flag; nothing here fires unless a
        # real repaint happened first.
        self._refresh_pending = False

        # PARKED state (2026-08-14): the overlay is showing a FROZEN pixmap and
        # is not live-grabbing. Set while Book Detail covers the underlying
        # panel — see park_for_panel. Deliberately a SEPARATE flag rather than a
        # third value of _active: four existing guards read `if not self._active`
        # (refresh_dirty, _fire_rearm, _check_drag_ended, force_refresh_now), and
        # each must keep answering "no, I am not live-grabbing" while parked, so
        # nothing can re-grab over the frozen frame.
        self._parked: bool = False
        self._parked_panel: object = None  # QWidget ref or None
        # Set when a content change lands while parked that the frozen frame
        # cannot reflect (see force_refresh_now). unpark_for_panel discards
        # rather than reuses such a frame.
        self._parked_frame_invalid: bool = False

        # Retry flag for _rearm_after_decline() — kept separate from
        # _refresh_pending so a declined tick's retry never reads as observed
        # paint activity (see that method's docstring).
        self._rearm_pending = False

        # SLIDER-DRAG STATE (2026-07-31) — see the drag gate in refresh_dirty()
        # for the root cause. _drag_watch_timer polls for the drag ending,
        # because a slider emits no signal this class is wired to observe and
        # the grab that would otherwise notice is exactly what's suspended.
        self._drag_suspended = False
        self._drag_watch_timer = QTimer(self.main_window)
        self._drag_watch_timer.setInterval(_DRAG_WATCH_MS)
        self._drag_watch_timer.timeout.connect(self._check_drag_ended)

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
        # STATUS 2026-08-15: this guard is defending its ORIGINAL, full hazard
        # again. Between 2026-08-14 and 2026-08-15 the grab source was
        # content_container (the panel is not inside it, so the panel hide/show
        # cycle this guard was sized against did not exist for that one day —
        # a prior version of this comment said so). That source was reverted
        # 2026-08-15 (content_container.grab() is opaque everywhere, which
        # produced a real, different visual defect — see _grab_and_blur's
        # docstring), so main_window + panel-hide is back, and with it the
        # exact repaint cycle this guard exists for. Do not treat this as a
        # narrow case again without re-confirming the grab source first.
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

    def _category_of(self, widget) -> str | None:
        """obj-identity lookup into self._category_by_widget. Returns None for
        anything not in the map — the tracker treats that as unsuppressed
        (see _DirtyRectTracker.eventFilter), never a silent default category."""
        return self._category_by_widget.get(id(widget))

    def _suppress_window_for(self, category: str) -> float:
        return self._suppress_window_by_category[category]

    # -- lifecycle ----------------------------------------------------------

    def _panel_hides_everything(self, panel) -> bool:
        """True when `panel` paints opaquely over the whole region we'd blur, so
        the grab's result cannot be seen by anyone.

        Currently only the Stats panel's Timeline tab qualifies (its heatmap
        needs an opaque backdrop — see StatsPanel.covers_opaquely). Grabbing
        under it is pure cost: measured 2026-07-27, ~15 grabs/sec at ~4.4ms of
        synchronous grab+blur on the main thread, producing an image nothing
        renders, while delaying the tassel's 33ms sway timer to an effective
        22.8fps (a visibly slow swing).

        Deliberately asks the PANEL whether it is opaque rather than testing tab
        indices or object names here — a new opaque surface only has to grow its
        own covers_opaquely() to be honoured, and tab reordering can't break it.
        """
        checker = getattr(panel, 'covers_opaquely', None)
        return bool(callable(checker) and checker())

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
        # A new panel claiming the overlay always beats an old parked frame.
        # Must run BEFORE every other branch here, including the
        # _panel_hides_everything early-return below and the _active guard:
        # _on_tag_filter_requested (app.py) calls _close_book_detail_flow() then
        # _open_library_flow() synchronously, before _on_book_detail_hidden
        # fires, so Library reaches this method while a frame is still parked.
        # _active is False while parked, so without this the parked pixmap and
        # geometry would be silently overwritten without ever going through
        # unpark_for_panel — and the later _on_book_detail_hidden would then
        # tear down Library's brand-new live overlay.
        if self._parked:
            self.hide_for_panel()
        if self._panel_hides_everything(panel):
            # Nothing behind this panel is visible — skip the grab entirely
            # rather than blurring an image nobody can see.
            return
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
        # Manual-paint hover fix (2026-08-16): a copy of this same clean grab,
        # kept as the restore source for _restore_button_from_snapshot. Must
        # be a copy (QPixmap(blurred), not the same object) — self._overlay's
        # own pixmap is mutated in place by _paint_button_hover/
        # _restore_button_from_snapshot below, and a shared reference would
        # let those mutations corrupt the "clean" restore source too.
        self._panel_open_snapshot = QPixmap(blurred)
        self._overlay.setGeometry(self._bounding_rect)
        self._opacity_effect.setOpacity(0.0)
        self._overlay.show()
        self._overlay.raise_()
        if self._fade_in_anim.state() == QPropertyAnimation.State.Running:
            self._fade_in_anim.stop()
        self._fade_in_anim.start()
        t_blit_done = time.perf_counter()

        self._tracker = _DirtyRectTracker(
            self._common_ancestor,
            on_dirty=self._schedule_refresh,
            is_suppressed=lambda: time.perf_counter() < self._grab_suppress_until,
            category_of=self._category_of,
            suppress_window_for=self._suppress_window_for,
        )
        self._tracker_widgets = self._all_tracked_widgets()
        for widget in self._tracker_widgets:
            widget.installEventFilter(self._tracker)
        self._tracker.take_dirty_union()  # reset: the first pass already covers everything

        # Manual-paint hover fix (2026-08-16): a SEPARATE filter (self, not
        # self._tracker) on just the 6 QPushButton-family tracked widgets,
        # intercepting only Enter/Leave — see _HoverPaintFilter.eventFilter.
        # Kept as its own list (not derived from _tracker_widgets at use
        # time) for the same reason _tracker_widgets itself is snapshotted
        # rather than recomputed: removeEventFilter must target exactly what
        # installEventFilter was called on.
        self._hover_buttons = [
            w for w in self._tracker_widgets if isinstance(w, QPushButton)
        ]
        for widget in self._hover_buttons:
            widget.installEventFilter(self._hover_filter)

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

    def frost_panel_backdrop(self, panel, rect_in_main_window: QRect):
        """Frost the backdrop of a panel that covers the whole content area, by
        giving THAT PANEL its own blurred-pixmap child. For Book Detail.

        WHY NOT show_for_panel / self._overlay (found live 2026-08-01, with a
        pixmap dump + a Z-order probe, after a first attempt shipped invisible):
        self._overlay is parented to content_container, while Book Detail is a
        child of main_window raised above it. raise_() only reorders a widget
        among ITS OWN SIBLINGS, so the shared overlay can climb to the top of
        content_container's 13 children and still sit UNDER Book Detail — the
        probe logged `same_parent=False`, and the grabbed pixmap was verifiably
        correct while nothing appeared on screen. The only part of it the user
        could see was the strip lying outside the panel's own opaque paint.
        The other five panels are 90% width, so their uncovered remainder hides
        this; a full-width panel exposes it completely.

        The fix is structural, not a raise_() ordering tweak: the frost is a
        child of the panel itself, stacked below the panel's content with
        lower(), so nothing can occlude it and no Z-order reasoning is needed.
        Deliberately NOT solved by reparenting self._overlay to main_window —
        that is the documented "pink-wash" trap (see __init__'s parenting note,
        2026-07-19), and it would perturb the five panels that work today.

        `rect_in_main_window` is the region to frost, in MAIN_WINDOW coordinates
        — the caller owns it, because the answer differs per source panel (see
        PanelManager._book_detail_frost_rect).

        Uses the shared _grab_and_blur(rect, panel) — both paths grab
        main_window with an explicit panel to hide, collapsed back into one
        function 2026-08-15 after a brief content_container/main_window split
        (2026-08-14–15) proved unnecessary: that split existed only to spare
        the transport path its panel-hide, and the split itself introduced a
        worse defect (content_container.grab() is opaque everywhere, so no
        compositing fix underneath it can ever show through — see
        _grab_and_blur's docstring). With both paths back on main_window, they
        differ only in WHICH panel gets hidden, which is exactly what the
        `panel` parameter is for.

        THIS call passes Book Detail explicitly (not the default
        self._active_panel) — a self-exclusion, not a hide-everything, so the
        panel BEHIND Book Detail (Stats/Library) stays visible in the grab and
        is what shows through the frost. The hide is cheap here because this
        runs once per open, not on every dirty tick like the transport path.

        No _DirtyRectTracker: a panel covering the content area occludes all 12
        tracked widgets, so any refresh they could drive is invisible, while
        the grab's own hide/show re-exposes them and re-arms the next grab —
        the ~64ms self-sustaining loop measured at ~15 grabs/sec (NOTES.md,
        2026-07-27). The frost is therefore STATIC while the panel is open, an
        accepted tradeoff (a playing book's remaining-time text can tick
        underneath and the frost will not follow it).
        """
        if rect_in_main_window.isEmpty():
            logger.warning("[TIMER-TRACE] frost_panel_backdrop SKIP reason=empty_rect")
            return

        t_entry = time.perf_counter()
        # _grab_and_blur takes a rect in _common_ancestor (content_container)
        # space and maps it back to main_window internally. Convert once here
        # so the caller can think purely in main_window coordinates.
        top_left_common = self._common_ancestor.mapFromGlobal(
            self.main_window.mapToGlobal(rect_in_main_window.topLeft()))
        rect_common = QRect(top_left_common, rect_in_main_window.size())

        # `panel` (Book Detail) is hidden for the grab so its own translucent
        # wash is not captured and then double-applied by the wash composite
        # below. Passed explicitly (not the default self._active_panel) — the
        # panel THIS call must hide is not the panel driving the transport-bar
        # overlay.
        blurred = self._grab_and_blur(rect_common, panel)

        # Paint the panel's OWN translucent wash on top of the blurred snapshot,
        # into the pixmap itself.
        #
        # WHY (found live 2026-08-01, second failed attempt): the panel sets
        # WA_StyledBackground, so its `rgba(bg_main, panel_opacity_hover)` wash is
        # painted by the PANEL, in its own paint pass, BEFORE any child. A child
        # can therefore never sit beneath it — frost.lower() only reaches the
        # bottom of the CHILD stack, which is still above the wash. The result was
        # an opaque sharp snapshot covering the wash entirely, which read as "the
        # panel background was removed" and made the foreground HARDER to read
        # rather than softer — the exact opposite of what a frost is for.
        #
        # Compositing the wash into the pixmap makes the frost the finished
        # backdrop (blurred content + tint), so it is correct wherever it sits in
        # the child stack.
        theme = self.main_window.theme_manager.get_current_theme()
        wash = QColor(theme['bg_main'])
        wash.setAlphaF(float(theme['panel_opacity_hover']))
        painter = QPainter(blurred)
        painter.fillRect(blurred.rect(), wash)
        painter.end()

        frost = getattr(panel, '_backdrop_frost', None)
        if frost is None:
            frost = QLabel(panel)
            frost.setObjectName("panel_backdrop_frost")
            frost.setAttribute(Qt.WA_TransparentForMouseEvents)
            panel._backdrop_frost = frost
        frost.setPixmap(blurred)
        # Panel-LOCAL geometry: the frost is a child of the panel, so it is
        # positioned relative to the panel's own top-left, not the window's.
        panel_top_left = panel.mapFrom(self.main_window, rect_in_main_window.topLeft())
        frost.setGeometry(QRect(panel_top_left, rect_in_main_window.size()))
        # Bottom of the child stack: under all real content, over the (now
        # redundant, still-painted) wash it already includes.
        frost.lower()
        frost.show()

        logger.warning(
            f"[PERF] frost_panel_backdrop DONE panel={panel.objectName()!r} "
            f"rect_mw={rect_in_main_window} frost_geom={frost.geometry()} "
            f"no_tracker=True total_ms={(time.perf_counter() - t_entry) * 1000:.2f}"
        )

    def clear_panel_backdrop_frost(self, panel):
        """Drop the frost child installed by frost_panel_backdrop, if any."""
        frost = getattr(panel, '_backdrop_frost', None)
        if frost is not None:
            frost.hide()
            frost.setPixmap(QPixmap())

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

    def _rearm_after_decline(self):
        """Re-arm a refresh that one of refresh_dirty()'s two DECLINING gates
        (hover-active, post-restyle cooldown) turned away, so the accumulated
        dirty union is retried instead of waiting for a future paint that may
        never come.

        Why this is needed (2026-07-27): both gates deliberately decline WITHOUT
        consuming take_dirty_union(), on the reasoning that "the next real paint
        picks it up". That reasoning holds only while more paints are guaranteed
        to arrive. The hover gate's own docstring argues hover-end self-corrects
        because the snapback restyle repaints the tracked widgets — but the
        snapback is `_on_theme_changed(..., hover=False)`, which hits that
        method's no-op guard and returns WITHOUT calling _apply_stylesheets
        whenever the snapback target theme is already the applied
        (theme_name, hover) pair. That is exactly the case when a hover preview
        was declined here rather than painted: the live theme never moved, so the
        snapback is a genuine duplicate, the guard fires, no restyle runs, no
        Paint event is emitted, and the last-declined dirty union is stranded on a
        cache nothing will refresh. The overlay then holds stale content
        indefinitely while the app keeps running — the shape reported in the
        frozen-overlay bug (TODO.md, 2026-07-20).

        Deliberately a delayed retry, not a singleShot(0): both gates are
        time-based, so an immediate turn would just re-decline in a tight loop
        until the window expires. The interval is sized above
        _POST_RESTYLE_COOLDOWN_S so a single retry normally clears the cooldown
        gate outright rather than spinning through several declines.

        Not routed through _schedule_refresh(): that is the tracker's real-paint
        entry point and its coalescing flag is meant to answer "did something
        genuinely repaint". Keeping the retry on its own flag preserves that
        meaning and keeps a declined tick from masquerading as observed paint.
        """
        if self._rearm_pending:
            return
        self._rearm_pending = True
        QTimer.singleShot(_DECLINE_REARM_MS, self._fire_rearm)

    def _fire_rearm(self):
        self._rearm_pending = False
        if not self._active:
            return
        self._schedule_refresh()

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

        if self._active_panel is not None and self._panel_hides_everything(self._active_panel):
            # Opaque surface moved over us (e.g. a tab switch to Timeline) —
            # stop re-grabbing until something visible is behind the panel again.
            return
        if not self._active or self._tracker is None:
            logger.warning(
                f"[TIMER-TRACE] refresh_dirty tick={_tick} EARLY-RETURN "
                f"reason=inactive_or_no_tracker active={self._active} "
                f"tracker_is_none={self._tracker is None}"
            )
            return

        # HOVER GATE (2026-07-20 — theme-bleed Mechanism B / audit Path D,
        # review/Review_260720_theme_reach.md): a hover-preview restyle rewrites
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
            self._rearm_after_decline()
            return

        # See _POST_RESTYLE_COOLDOWN_S's declaration above for the root cause
        # and measured numbers this gates against. Checked BEFORE
        # take_dirty_union() so a skipped tick leaves the accumulated dirty
        # union untouched in the tracker for the next tick to pick up — nothing
        # is consumed or dropped, this tick just declines to act on it yet.
        last_restyle = getattr(theme_manager, '_last_apply_stylesheets_at', None)
        if last_restyle is not None and (time.perf_counter() - last_restyle) < _POST_RESTYLE_COOLDOWN_S:
            logger.warning(f"[TIMER-TRACE] refresh_dirty tick={_tick} EARLY-RETURN reason=cooldown_gate")
            self._rearm_after_decline()
            return

        # SLIDER-DRAG GATE — see _DRAG_WATCH_MS's declaration for the root cause
        # and for why skipping only the panel-hide was tried and reverted.
        # Checked BEFORE take_dirty_union() so everything dirtied during the drag
        # accumulates untouched and lands in one composite when the drag ends.
        # The cost is a blur that goes stale for the length of the drag; the
        # visible elements that keep moving on their own (the chapter slider on a
        # short chapter, a scrolling title) drift out of sync with the live
        # widget underneath until then. That is deliberate: the alternative is
        # a scrollbar that cannot be dragged at all.
        if self._active_panel is not None and _dragging_slider(self._active_panel) is not None:
            if not self._drag_suspended:
                self._drag_suspended = True
                self._drag_watch_timer.start()
                logger.warning(
                    f"[TIMER-TRACE] refresh_dirty tick={_tick} EARLY-RETURN "
                    f"reason=slider_drag_gate (suspending grabs until drag ends)")
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

        # Re-apply manual hover/pressed paint for any currently-hovered/
        # pressed button whose overlay rect intersects the just-composited
        # region — the composite above may have overwritten the crisp manual
        # paint with a blurred grab result (2026-08-17). Pressed wins over
        # hover for a button that is both (Enter always fires before Press,
        # so a pressed button is in both sets) — matches real QSS specificity
        # (:pressed overrides :hover) and avoids painting hover then
        # immediately overpainting it with pressed for the same button.
        for btn in self._hovered_buttons:
            if btn in self._pressed_buttons:
                continue
            btn_rect = self._button_overlay_rect(btn)
            if btn_rect.intersects(local):
                self._paint_button_hover(btn)
        for btn in self._pressed_buttons:
            btn_rect = self._button_overlay_rect(btn)
            if btn_rect.intersects(local):
                self._paint_button_pressed(btn)

        logger.warning(f"[TIMER-TRACE] refresh_dirty tick={_tick} COMPOSITED dirty={dirty}")

        # [OVERLAY-DUMP] one-shot (2026-08-15) — fires on the first real
        # composite after FABULOR_DUMP_OVERLAY=1 is set, right after the line
        # above so `combined` IS the pixmap the user is looking at right now.
        # Saves it alongside a fresh full-region grab of the same
        # _bounding_rect taken at this same instant, for a direct diff.
        # Read-only: does not touch grab/composite logic, does not run unless
        # explicitly armed, and never fires more than once per arm.
        if _DUMP_OVERLAY_ENABLED and not getattr(self, '_overlay_dump_done', False):
            self._overlay_dump_done = True
            t_dump = time.perf_counter()
            combined.save("/tmp/fabulor_overlay_dump.png", "PNG")
            fresh = self._grab_and_blur(self._bounding_rect)
            fresh.save("/tmp/fabulor_fullgrab_dump.png", "PNG")
            overlay_topleft_common = self._overlay.geometry().topLeft()
            logger.warning(
                f"[OVERLAY-DUMP] t={t_dump:.6f} "
                f"overlay_geometry={self._overlay.geometry()} "
                f"overlay_topleft_common={overlay_topleft_common} "
                f"bounding_rect={self._bounding_rect} "
                f"last_dirty={dirty} last_dirty_local={local} "
                f"overlay_pixmap_size={combined.size()} "
                f"fullgrab_size={fresh.size()} "
                f"saved overlay -> /tmp/fabulor_overlay_dump.png "
                f"saved fullgrab -> /tmp/fabulor_fullgrab_dump.png"
            )

    def _check_drag_ended(self):
        """Poll while grabs are suspended for a slider drag; resume on release.

        Resumes with a FULL-rect re-grab rather than replaying the accumulated
        dirty union. During the suspension the tracker saw no Paint events from
        the grab's own hide/show cycle, so its union reflects only what the app
        repainted on its own — it is not a reliable record of everything that
        changed on screen while the blur was frozen. A full pass is the only
        thing that guarantees no stale region survives, which is the constraint
        that rules out simply letting the dirty union drain here."""
        if not self._active or self._active_panel is None:
            self._drag_watch_timer.stop()
            self._drag_suspended = False
            return
        if _dragging_slider(self._active_panel) is not None:
            return  # still dragging
        self._drag_watch_timer.stop()
        self._drag_suspended = False
        logger.warning("[TIMER-TRACE] slider drag ended — full-rect refresh, grabs resumed")
        self.force_refresh_now()

    def force_refresh_now(self):
        """ONE-TIME forced full-rect re-grab, for known content-change events
        that don't necessarily produce a Paint event on any of the 12 tracked
        widgets (a settings-tab switch changes what's visible/selected in the
        settings_panel itself, not in the transport bar's own widgets, so
        _DirtyRectTracker would never see it). Not a hot loop, not called on
        hover — wired only to QTabWidget.currentChanged (panels.py) and
        show_for_panel's own existing mandatory first pass. No-op if the overlay
        isn't currently active, same as every other entry point here.

        PARKED case (2026-08-14): a parked frame cannot be refreshed in place —
        re-grabbing would restart the ~15 grabs/sec refresh cycle that
        park_for_panel exists to stop while Book Detail is open, AND (grab
        source is main_window again as of 2026-08-15 — see _grab_and_blur's
        docstring) would photograph Book Detail into the cache, via the panel
        hide _grab_and_blur performs. (A comment here briefly said that second
        hazard was gone, 2026-08-14–15, while the grab source was
        content_container. It is back.) The parking invariant is unchanged
        either way — the point is not to be grabbing at all here.
        So the frame is marked invalid instead, and unpark_for_panel discards it
        rather than reusing it. Handling this HERE rather than at each call site
        means every present and future caller of force_refresh_now gets parked
        invalidation for free — including _on_book_removed (app.py), which is
        what surfaced this: excluding the playing book hides the transport
        chrome, and the frozen frame then sat over the region the ambient
        CoverCarousel had just been given, showing a stale blurred band across
        it (reported live 2026-08-14). That is the same seam the isVisible()
        filter in _compute_bounding_rect was added to prevent on 2026-07-27 —
        that guard covers a rect being COMPUTED wrong, this covers a correct
        rect going STALE."""
        if self._parked:
            self._parked_frame_invalid = True
            # Drop it NOW rather than only flagging it for unpark to discard at
            # close. The frame depicts chrome that has ALREADY gone — measured
            # 2026-08-14: the parked rect is QRect(10, 300, 260, 198), the full
            # transport bar, while a genuine post-removal grab is
            # QRect(98, 474, 104, 24), because _set_interface_visible(False)
            # hid almost all of it. Leaving it up until close meant the stale
            # image stayed composited over the region the ambient carousel had
            # just been given, and even after unpark discarded it there was a
            # one-frame flash of it before the fallback grab landed (reported
            # live). Hiding it here means the region simply shows live content
            # from this moment on; _parked_frame_invalid still tells unpark to
            # take the fresh-grab path rather than trying to reuse anything.
            self._overlay.hide()
            return
        if not self._active or self._bounding_rect is None:
            return
        if self._active_panel is not None and self._panel_hides_everything(self._active_panel):
            return
        logger.warning("[TIMER-TRACE] force_refresh_now: tab-switch triggered full-rect refresh")
        blurred = self._grab_and_blur(self._bounding_rect)
        self._overlay.setPixmap(blurred)
        if self._tracker is not None:
            self._tracker.take_dirty_union()  # this pass already covers everything just grabbed

    def _disarm_grabbing(self):
        """Stop live grabbing, WITHOUT touching the displayed image or identity.

        The "stop grabbing" half of hide_for_panel, extracted so park_for_panel
        can reuse it (see the park/unpark section below). Everything here is
        about not producing new frames; nothing here changes what is currently
        on screen.

        Deliberately does NOT touch _overlay, _opacity_effect, _fade_in_anim,
        _bounding_rect or _active_panel — those are the display/identity half
        and stay in hide_for_panel. That split is the whole point: parking needs
        this half alone.
        """
        self._refresh_tick_count = 0
        # The drag watcher must not outlive the overlay it was polling for —
        # otherwise it keeps ticking against a panel that is no longer active.
        self._drag_watch_timer.stop()
        self._drag_suspended = False
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
        # Manual-paint hover fix (2026-08-16): same "stop producing new
        # frames" category as the tracker above, not the display/identity
        # half — while parked (Book Detail over this panel), manual hover
        # painting would mutate a pixmap park_for_panel is relying on staying
        # static, and the buttons aren't even the visually relevant surface
        # anymore (Book Detail occludes them). Removed from exactly
        # self._hover_buttons for the same stale-filter reason as above.
        for widget in self._hover_buttons:
            widget.removeEventFilter(self._hover_filter)
        self._hover_buttons = []
        self._hovered_buttons = set()
        self._pressed_buttons = set()
        self._mouse_down_buttons = set()
        self._pressed_false_since = {}
        self._pressed_poll_timer.stop()
        self._active = False
        # Any in-flight decline-retry is left to fire once and no-op on its own
        # `if not self._active` guard (same safety property the coalescing
        # singleShot already relies on); clearing the flag here just lets the
        # next panel-open arm a fresh one instead of inheriting a stale True.
        self._rearm_pending = False

    def hide_for_panel(self):
        """Tear down unconditionally, instantly — no fade on the way out. Called
        from the panel's *_close_flow (at the START of the close animation, not
        after it finishes), so the transport bar returns to live view right away
        instead of staying blurred through the whole slide-out — see the accepted
        plan's §6 for why live-dissolve-during-slide is deferred, not implemented
        here. Any in-flight fade-IN (see show_for_panel) is stopped and opacity
        reset to 1.0 so the next show_for_panel starts from a clean state."""
        logger.warning(
            f"[TIMER-TRACE] hide_for_panel ENTRY active={self._active} "
            f"active_panel={self._active_panel.objectName() if self._active_panel else None!r} "
            f"refresh_pending={self._refresh_pending} "
            f"tick_count_this_session={getattr(self, '_refresh_tick_count', 0)}"
        )
        self._disarm_grabbing()
        if self._fade_in_anim.state() == QPropertyAnimation.State.Running:
            self._fade_in_anim.stop()
        self._opacity_effect.setOpacity(1.0)
        self._overlay.hide()
        self._overlay.setPixmap(QPixmap())
        self._bounding_rect = None
        self._active_panel = None
        self._panel_open_snapshot = None
        self._parked = False
        self._parked_panel = None
        self._parked_frame_invalid = False

    # --- park / unpark -------------------------------------------------------

    def park_for_panel(self):
        """Freeze the live overlay into a static backdrop and stop grabbing.

        Used when Book Detail opens over an underlying panel. The underlay's
        blurred transport bar stays on screen as a frozen image instead of being
        discarded and re-grabbed at close — which is what produced a visible
        crisp frame on both the open and the close (reported live 2026-08-14).

        The parked frame needs no masking or reveal logic: _overlay is a child
        of content_container, while Book Detail is a child of main_window raised
        above it, so Book Detail occludes the parked frame by construction,
        everywhere it covers it, on every frame. (Same Z-order fact that made an
        early Book Detail frost attempt ship invisible — see CLAUDE.md, "A blur
        overlay can only cover what shares its parent".)

        HARD INVARIANT: never grab while parked. Re-grabbing restarts the
        feedback loop _park_blur_for_book_detail exists to prevent (measured
        self-sustaining at ~64ms / ~15 grabs per second, NOTES.md 2026-07-27)
        AND (grab source is main_window again as of 2026-08-15) would hide
        _active_panel while Book Detail is on top, photographing Book Detail
        into the cache. (This second hazard was briefly absent 2026-08-14–15,
        while the grab source was content_container. It is back — see
        _grab_and_blur's docstring for why that source was reverted.)
        Every guard that keeps this true reads `if not self._active`, which
        _disarm_grabbing sets False — hence _parked being a separate flag.
        """
        if not self._active or self._bounding_rect is None:
            # Nothing live to park: blur off, or the underlay is opaque and
            # show_for_panel already early-returned (_panel_hides_everything).
            self._parked = False
            return
        # Freeze any in-flight fade at full opacity BEFORE disarming — a frame
        # caught mid-fade and frozen at 0.4 would be a visible half-blur.
        if self._fade_in_anim.state() == QPropertyAnimation.State.Running:
            self._fade_in_anim.stop()
        self._opacity_effect.setOpacity(1.0)
        self._disarm_grabbing()
        self._parked = True
        self._parked_panel = self._active_panel
        # Fresh park, fresh frame — never inherit a previous session's verdict.
        self._parked_frame_invalid = False
        # _overlay (shown), its pixmap, _bounding_rect and _active_panel are all
        # deliberately left intact — that is what "parked" means.
        logger.warning(
            f"[TIMER-TRACE] park_for_panel: froze overlay for "
            f"{self._parked_panel.objectName() if self._parked_panel else None!r} "
            f"rect={self._bounding_rect}"
        )

    def unpark_for_panel(self, panel) -> bool:
        """Re-arm live grabbing under an already-parked frame.

        Returns True if the parked frame was reused, False if the caller must
        fall back to show_for_panel (today's path).

        STEP ORDERING IS LOAD-BEARING: `_active = True` must precede clearing
        _parked/_parked_panel, which must precede force_refresh_now(), because
        force_refresh_now guards on `not self._active` — and a future
        `if self._parked:` branch in that method (the deferred stale-frame
        invalidation pass) would short-circuit the refresh if _parked were still
        set. Reordering these silently turns the refresh into a no-op.

        The refresh at the end is NOT optional. show_for_panel grabs FIRST
        (:463) and arms the tracker afterwards (:475-483); that tracker block
        contains no grab and no force_refresh_now — its take_dirty_union() is a
        reset, not a trigger. The parked path deliberately skips that initial
        grab because the image is already on screen, so this is the one grab
        that reconciles whatever changed while parked.
        """
        if not self._parked:
            return False
        if (panel is not self._parked_panel or not panel.isVisible()
                or self._parked_frame_invalid):
            # A different panel, the underlay went away while Book Detail was
            # open (hide_all_panels paths), or a content change landed that the
            # frozen frame cannot reflect (force_refresh_now while parked) —
            # the frame is not reusable. Falling back to show_for_panel gives
            # today's behaviour: a correct, freshly grabbed blur.
            self.hide_for_panel()
            return False
        # Re-arm the tracker exactly as show_for_panel does at :475-483.
        # Do NOT add a _grab_and_blur call here: the image is already on screen.
        self._tracker = _DirtyRectTracker(
            self._common_ancestor,
            on_dirty=self._schedule_refresh,
            is_suppressed=lambda: time.perf_counter() < self._grab_suppress_until,
            category_of=self._category_of,
            suppress_window_for=self._suppress_window_for,
        )
        self._tracker_widgets = self._all_tracked_widgets()
        for widget in self._tracker_widgets:
            widget.installEventFilter(self._tracker)
        self._tracker.take_dirty_union()  # discard pre-arm dirt; triggers nothing
        # Manual-paint hover fix (2026-08-16): re-install exactly like
        # show_for_panel does — park_for_panel's own _disarm_grabbing call
        # removed this filter, so it needs re-arming here too.
        # _panel_open_snapshot itself needs no action: _disarm_grabbing never
        # touches it, so the one from before the park is still valid.
        self._hover_buttons = [
            w for w in self._tracker_widgets if isinstance(w, QPushButton)
        ]
        for widget in self._hover_buttons:
            widget.installEventFilter(self._hover_filter)
        self._active = True
        self._parked = False
        self._parked_panel = None
        self._parked_frame_invalid = False
        logger.warning(
            f"[TIMER-TRACE] unpark_for_panel: reused parked frame for "
            f"{panel.objectName()!r}, re-armed and refreshing"
        )
        self.force_refresh_now()
        return True

    def discard_parked_frame(self):
        """Drop a parked frame, if there is one. No-op otherwise.

        Safe to call on any path: if the overlay has since been claimed by
        another panel (show_for_panel drops a stale park at its entry), _parked
        is already False and nothing happens. Called from
        _resume_blur_after_book_detail's early-return branch, where the underlay
        is gone — without it, the hide_all_panels paths
        (_on_open_tag_manager_from_detail, _on_tag_filter_requested) would
        strand a frozen blurred band over the transport bar.
        """
        if self._parked:
            self.hide_for_panel()

    # -- geometry -------------------------------------------------------------

    def _panel_rect_in_common_space(self, panel) -> QRect:
        """Thin wrapper over the module-level panel_rect_in_common_space() — see
        that function for the full rationale. Kept as a method so existing call
        sites read unchanged."""
        return panel_rect_in_common_space(panel, self._common_ancestor)

    def _compute_bounding_rect(self) -> QRect | None:
        """Union of the tracked widgets that are ACTUALLY VISIBLE.

        The isVisible() filter is load-bearing, not a micro-optimization (found
        live 2026-07-27). In the no-book state `_set_interface_visible(False)`
        hides almost all of the transport chrome — measured: only
        progress_slider remains visible, the other five sampled widgets are
        hidden — but this used to union every tracked widget unconditionally,
        including hidden ones whose geometry the layout still reports. That
        produced a full-height rect (measured `QRect(10, 300, 260, 198)`,
        spanning y=300..497) covering a region where nothing was actually
        drawn.

        In the no-book state the ambient CoverCarousel occupies y=227..392, so
        that phantom rect overlapped it from y=300 down. The overlay's CACHED
        pixmap then sat frozen over the lower two-thirds of the scrolling
        carousel: sharp above y=300, blurred and stuck below it — a visible
        horizontal seam straight across the cover thumbnails. Restricting the
        union to visible widgets keeps the rect on chrome that is genuinely
        on screen.

        Returns None when nothing tracked is visible, which callers already
        treat as "no blur" via their empty/None rect guards.
        """
        rect: QRect | None = None
        for widget in self._all_tracked_widgets():
            if not widget.isVisible():
                continue
            top_left = widget.mapTo(self._common_ancestor, QPoint(0, 0))
            widget_rect = QRect(top_left, widget.size())
            rect = widget_rect if rect is None else rect.united(widget_rect)
        return rect

    def _button_overlay_rect(self, button: QWidget) -> QRect:
        """`button`'s rect in overlay-local coordinates, clipped to the
        overlay pixmap's own bounds.

        The clip is load-bearing, not defensive polish: next_button and
        speed_button straddle the panel's right edge (confirmed live,
        2026-08-16 — 20 of their ~46-60px width sits in the live, unblurred
        sliver past the panel, only the remainder is inside the frosted
        _bounding_rect at all). An unclipped rect would ask _paint_button_hover
        /_restore_button_from_snapshot to draw or copy pixels that don't exist
        in the overlay pixmap. Qt would silently truncate the draw either way,
        but computing the intersection explicitly here — once, in the one
        place both callers share — is what makes that truncation something
        both callers can reason about (an empty rect after clipping means
        "nothing to paint," checked by both callers) rather than relying on
        an implicit clip neither of them asked for. The live, unblurred
        sliver these two buttons partly sit in is not touched by either
        helper — it is already rendering its own correct, native :hover QSS,
        since it was never part of the grab in the first place."""
        top_left = button.mapTo(self._common_ancestor, QPoint(0, 0))
        overlay_rect = QRect(top_left - self._bounding_rect.topLeft(), button.size())
        overlay_bounds = QRect(QPoint(0, 0), self._bounding_rect.size())
        return overlay_rect.intersected(overlay_bounds)

    def _paint_button_content(self, painter: QPainter, button: QWidget, rect: QRect) -> None:
        """Redraw `button`'s real CONTENT (icon or text) on top of a manual
        fill already painted into `rect`, blurred at _CONTENT_BLUR_RADIUS to
        stay visually consistent with the rest of the (blurred) frost.

        Scoped to next_button and speed_button ONLY (2026-08-17) — the two
        buttons that straddle the panel edge into the live sliver (see
        _button_overlay_rect's own comment) and are therefore the only two
        whose manual fill is ever actually seen. The other four sit fully
        under an opaque panel and are never redrawn — a flat fill with no
        content is invisible there, so there is nothing to fix.

        Reads the button's CURRENT displayed content live (icon()/text())
        rather than re-deriving which icon/value should be showing — that
        selection logic already lives elsewhere (_set_play_icon,
        _update_skip_icons, the speed-change handler) and duplicating it here
        would be a second, driftable copy of the same decision."""
        mw = self.main_window
        # Per-button vertical trim against the font metrics' own centering —
        # the ▶ glyph reads visually low relative to its font-metrics bounding
        # box (confirmed live, 2026-08-17); speed_button's plain digits/period
        # need no correction.
        y_offset = 0
        if button is getattr(mw, 'next_button', None):
            # Unicode glyph, not the SVG icon pixmap — simpler, and this is
            # an approximation drawn on a manual fill, not the real icon.
            text = "▶"  # ▶
            font = button.font()
            y_offset = -1  # tuned live, 2026-08-17
        elif button is getattr(mw, 'speed_button', None):
            # Numeric value only — button.text() is "1.90x"; drop the "x".
            text = button.text().rstrip('xX')
            if not text:
                return
            font = button.font()
        else:
            return
        metrics = QFontMetrics(font)
        text_size = metrics.size(Qt.TextFlag.TextSingleLine, text)
        content = QPixmap(text_size)
        content.fill(Qt.GlobalColor.transparent)
        text_painter = QPainter(content)
        text_painter.setFont(font)
        text_painter.setPen(button.palette().buttonText().color())
        text_painter.drawText(content.rect(), Qt.AlignmentFlag.AlignCenter, text)
        text_painter.end()
        blurred_content = _blur_pixmap(content, _CONTENT_BLUR_RADIUS)
        # Hug the RIGHT edge of `rect`, not centered — `rect` is clipped to
        # the frosted region only (the button's left portion sits under the
        # panel, per _button_overlay_rect's own comment), so the visible
        # frosted sliver is left of the panel's edge and the content must
        # anchor toward that edge, matching where the real button's content
        # actually sits (confirmed live, 2026-08-17 — centering left the
        # glyph/text looking left-aligned within the visible strip).
        target = QRect(0, 0, blurred_content.width(), blurred_content.height())
        target.moveRight(rect.right())
        target.moveTop(rect.center().y() - target.height() // 2 + y_offset)
        painter.drawPixmap(target.topLeft(), blurred_content)

    def _paint_button_fill(self, button: QWidget, theme_key: str) -> None:
        """Shared implementation for _paint_button_hover/_paint_button_pressed
        — paint `button`'s state fill (flat color, border-radius 4px — the
        ONLY thing that changes per the QSS investigation) directly into
        self._overlay's pixmap, in place of a grab. next_button/speed_button
        additionally get their real content (icon/text) redrawn on top — see
        _paint_button_content — since an opaque fill alone hides it entirely
        and its absence is noticeable.

        This is the manual-paint replacement for the grab-based approaches
        that failed structurally (see NOTES.md, 2026-08-16 sessions): no
        panel hide, no children hide, no hit-test disturbance — this method
        never touches panel or button visibility at all, it only mutates the
        already-shown overlay pixmap directly, driven by a real Enter/Press
        event (see _HoverPaintFilter.eventFilter, near _DirtyRectTracker
        above)."""
        theme = self.main_window.theme_manager.get_current_theme()
        color = QColor(theme[theme_key])
        rect = self._button_overlay_rect(button)
        if _GRAB_TRACE_ENABLED:
            logger.warning(
                f"[PAINT-FILL-TRACE] button={button.objectName()!r} "
                f"theme_key={theme_key!r} rect={rect} empty={rect.isEmpty()} "
                f"bounding_rect={self._bounding_rect}"
            )
        if rect.isEmpty():
            return
        pixmap = QPixmap(self._overlay.pixmap())
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(rect, 4, 4)
        self._paint_button_content(painter, button, rect)
        painter.end()
        self._overlay.setPixmap(pixmap)

    def _paint_button_hover(self, button: QWidget) -> None:
        """Hover fill — see _paint_button_fill. QSS: accent_light."""
        self._paint_button_fill(button, 'accent_light')

    def _paint_button_pressed(self, button: QWidget) -> None:
        """Pressed fill (2026-08-17) — see _paint_button_fill. QSS:
        accent_dark. Matters more than hover in practice, per Pryme: a longer
        press makes the opaque-fill-hides-content discrepancy visible for
        longer than a quick hover would."""
        self._paint_button_fill(button, 'accent_dark')

    def _set_pressed(self, button: QWidget, pressed: bool) -> None:
        """Single mutation point for _pressed_buttons — the PAINT-state set
        only. Paints/restores the manual fill on a real transition; does NOT
        touch the poll timer or _mouse_down_buttons (the SESSION set) — see
        _arm_pressed_poll/_disarm_pressed_poll_if_idle for that, called
        separately by Press/Release. This split (2026-08-17, multi-crossing
        fix) is what lets the poll call this repeatedly, in both directions,
        for as long as a session stays open — see _mouse_down_buttons' own
        comment for the bug this replaced."""
        was_in_set = button in self._pressed_buttons
        if _GRAB_TRACE_ENABLED:
            logger.warning(
                f"[SET-PRESSED-TRACE] button={button.objectName()!r} "
                f"pressed={pressed} currently_in_set={was_in_set} "
                f"timer_active={self._pressed_poll_timer.isActive()}"
            )
        if pressed:
            if not was_in_set:
                self._paint_button_pressed(button)
                self._pressed_buttons.add(button)
        else:
            if was_in_set:
                self._pressed_buttons.discard(button)
                self._restore_button_from_snapshot(button)
            self._pressed_false_since.pop(button, None)

    def _arm_pressed_poll(self) -> None:
        """Start the poll timer if it isn't already running — called once per
        button on MouseButtonPress (session open), never by the poll itself.
        Idempotent: safe to call while other buttons already have the timer
        running (a second button pressed while the first is still held)."""
        if not self._pressed_poll_timer.isActive():
            self._pressed_poll_timer.start()

    def _disarm_pressed_poll_if_idle(self) -> None:
        """Stop the poll timer once no button has an open session — called on
        MouseButtonRelease (session close), never by the poll itself. Keyed
        off _mouse_down_buttons (the session set), NOT _pressed_buttons (the
        paint-state set) — a button can be mid-session with no paint showing
        (cursor currently outside the rect) and the poll must keep running
        for it regardless."""
        if not self._mouse_down_buttons and self._pressed_poll_timer.isActive():
            self._pressed_poll_timer.stop()

    def _pressed_poll_tick(self) -> None:
        """Poll cursor-vs-rect containment for every button with an open
        press SESSION (_mouse_down_buttons), independent of MouseMove event
        delivery (2026-08-17, revised twice same day).

        Qt does not fire Enter/Leave to a widget during an active mouse grab
        (a QPushButton grabs the mouse for the duration of a press) — a
        drag-off/drag-back-in only generates MouseMove, and Qt's actual
        MouseMove delivery during a SLOW drag can gap by 1.5+ seconds with no
        events at all (confirmed live via [PRESS-BORDER-TRACE]: a real
        slow-drag repro showed a 1.6s gap with zero MouseMove events while the
        cursor was leaving a pressed button's rect). Polling removes the
        dependency on event delivery entirely — the frost updates within one
        poll interval of the real state regardless of how sparse mouse events
        are.

        SIGNAL: originally polled QPushButton.isDown() directly. isDown() was
        found NOT reliable as a live signal — confirmed via
        [POLL-TICK-TRACE]: a single tick read isDown()==False 504ms into an
        otherwise-continuous 4.7s hold (cursor never moved, real release only
        ~4.2s later), correlated with _grab_and_blur's panel hide/show cycle
        landing 22-30ms earlier for that same button's rect (same underlying
        hazard as the tassel hand-cursor flicker — hide/show perturbs
        Qt-internal pointer/press state). Replaced with a direct geometric
        check instead — button.rect().contains(button.mapFromGlobal(
        QCursor.pos())) — which does not depend on any Qt-internal
        press-tracking state the grab cycle can perturb, only on the button's
        own (always-correct) geometry and the live global cursor position.

        ITERATION TARGET (2026-08-17, second revision, the multi-crossing
        fix): this originally iterated self._pressed_buttons directly and
        only ever discovered EXITS (inside->outside), via _set_pressed(False)
        — which both repaints AND removes the button from _pressed_buttons.
        Once removed, the same `for button in self._pressed_buttons` loop
        could never see that button again, so a later re-entry
        (outside->inside) during the SAME held press was silently never
        detected. Confirmed live (Pryme, 2026-08-17): "right side clears,
        then left side catches up... I continue to press and cross the
        button multiple times... left side never changes" after the first
        exit — a one-way door, not a timing lag. Fixed by iterating
        self._mouse_down_buttons instead — a SEPARATE set this method never
        mutates (only Press/Release do, via _arm_pressed_poll/
        _disarm_pressed_poll_if_idle) — so a button that exits and later
        re-enters during the same session is checked, and re-checked, on
        every single tick for as long as the session stays open, in either
        direction, any number of times.

        _RELEASE_DEBOUNCE_S / _pressed_false_since tracking is retained: a
        genuine micro-jitter at the exact rect boundary could still flip the
        containment test for a single poll tick, and the debounce absorbs
        that the same way it absorbed isDown()'s noise, just against a signal
        that is not independently known to go wrong for multi-second
        stretches. It debounces only the OUTSIDE direction (matching its
        original design) — a re-entry (outside->inside) is applied
        immediately, no debounce, since there is no equivalent "brief false
        positive" hazard on that side to guard against.

        Iterates a snapshot (list(...)) since a future _set_pressed caller
        could in principle mutate _pressed_buttons mid-iteration; this method
        no longer mutates _mouse_down_buttons itself, so no iteration hazard
        exists there, but the snapshot pattern is kept for consistency."""
        cursor_pos = QCursor.pos()
        if _GRAB_TRACE_ENABLED:
            logger.warning(
                f"[POLL-TICK-TRACE] mouse_down_buttons="
                f"{[b.objectName() for b in self._mouse_down_buttons]} "
                f"cursor_pos=({cursor_pos.x()}, {cursor_pos.y()})"
            )
        now = time.perf_counter()
        for button in list(self._mouse_down_buttons):
            inside = button.rect().contains(button.mapFromGlobal(cursor_pos))
            if inside:
                self._pressed_false_since.pop(button, None)
                self._set_pressed(button, True)
                continue
            since = self._pressed_false_since.get(button)
            if since is None:
                self._pressed_false_since[button] = now
            elif now - since >= _RELEASE_DEBOUNCE_S:
                self._pressed_false_since.pop(button, None)
                self._set_pressed(button, False)

    def _restore_button_from_snapshot(self, button: QWidget) -> None:
        """Restore `button`'s overlay-local rect from self._panel_open_snapshot
        — the clean, unhovered frame captured once in show_for_panel — in
        place of a grab, on hover leave.

        Real content, not a flat placeholder: this is the same clean grab
        self._overlay was originally shown with, so the restored region shows
        whatever was actually there (the button's real unhovered QSS state,
        its icon, anything else in that rect) rather than a guessed fill."""
        if self._panel_open_snapshot is None:
            logger.warning(
                "[HOVER-RESTORE] _panel_open_snapshot is None — skipping "
                "restore. Should be unreachable while a panel is open; see "
                "show_for_panel/hide_for_panel for where it is set/cleared."
            )
            return
        rect = self._button_overlay_rect(button)
        if _GRAB_TRACE_ENABLED:
            logger.warning(
                f"[PAINT-RESTORE-TRACE] button={button.objectName()!r} "
                f"rect={rect} empty={rect.isEmpty()} "
                f"bounding_rect={self._bounding_rect}"
            )
        if rect.isEmpty():
            return
        pixmap = QPixmap(self._overlay.pixmap())
        painter = QPainter(pixmap)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.drawPixmap(rect.topLeft(), self._panel_open_snapshot, rect)
        painter.end()
        self._overlay.setPixmap(pixmap)

    def _grab_and_blur(self, rect: QRect, panel=None) -> QPixmap:
        """Grabs main_window with `panel` hidden. `panel` defaults to
        self._active_panel (the transport-bar path's every call site); the
        frost path (frost_panel_backdrop) passes Book Detail explicitly, since
        the panel it must hide is not the one driving this overlay.

        COLLAPSED BACK 2026-08-15 from a content_container/main_window split
        that lived here 2026-08-14–15. That split's premise — grab
        content_container so the panel (a sibling, not a descendant) is never
        in the grab and never needs hiding — traded the hover-flicker bug
        below for a WORSE one: content_container.grab() returns Qt's default
        QPalette color (32,35,38), fully OPAQUE, at every pixel it doesn't
        paint itself (the QVBoxLayout inter-row gaps in the transport
        controls). Confirmed live via a pixel probe: because that grab is
        opaque everywhere, ANY compositing fill painted underneath it — flat
        bg_main, or a two-pass bg_main+panel-wash — is completely overwritten
        by the final drawPixmap and never reaches the output; the artifact
        Pryme reported (a visible rectangular darkening, ~4-7% below bg_main,
        consistent across two themes) survived both fix attempts because
        neither could possibly have changed the composited pixel. The defect
        is the grab source itself having no transparency for a fill to show
        through — not a wrong fill color. See NOTES.md for the full trail.

        ROOT CAUSE main_window as the source solves (found live, 2026-07-19,
        Pryme directly identified the background color itself as wrong — not a
        coordinate or blur bug): content_container (_common_ancestor) has NO
        styled background of its own. main_window's real stylesheet paints
        bg_main (the theme's actual background color) and it shows through
        underneath content_container in normal on-screen compositing — but
        grab() only rasterizes a widget's OWN paint, never an ancestor's
        background showing through it.

        Grabbing main_window means the panel (raised above content_container,
        a child of main_window) IS in the grab unless hidden — its own
        translucent wash would double-apply on top of the real content. Hence
        the hide/show below.

        THE HOVER-FLICKER BUG this hide causes, and why it is accepted:
        hiding `panel` for the grab un-covers whatever transport widget sits
        underneath, so Qt re-hit-tests and re-resolves the cursor — a parked
        cursor keeps receiving real Enter/Leave events with no mouse movement,
        confirmed live at ~10.6 grabs/sec, none caught by the 50ms suppress
        guard (NOTES.md, 2026-08-14). Content_container's exclusion of the
        panel by construction was the fix attempt for exactly this — reverted
        2026-08-15 because it broke compositing correctness while, per
        Pryme's live testing, not even fixing the flicker it was built for
        ("more responsive... but still stale"). The flicker itself remains
        open; see TODO.md.

        The cursor-pin and mouse-transparency compensation below are NOT the
        flicker fix — they are two independently-shipped, still-necessary
        fixes for two OTHER bugs the hide creates (cursor flicker, 2026-07-21;
        real clicks landing on invisibly-uncovered widgets, 2026-08-01). Both
        are restored verbatim from main, unchanged by this collapse.
        """
        if panel is None:
            panel = self._active_panel

        # main_window-local coordinates, via the same mapToGlobal/mapFromGlobal
        # round-trip _panel_rect_in_common_space uses. `rect` arrives in
        # _common_ancestor (content_container) space from every caller.
        main_window_rect = QRect(
            self.main_window.mapFromGlobal(self._common_ancestor.mapToGlobal(rect.topLeft())),
            rect.size(),
        )
        pad = int(_BLUR_RADIUS * 4)
        padded_rect = main_window_rect.adjusted(-pad, -pad, pad, pad)

        t0 = time.perf_counter()
        if _GRAB_TRACE_ENABLED:
            logger.warning(f"[GRAB-ENTRY] t={t0:.6f} rect={rect}")

        # FEEDBACK-LOOP GUARD (2026-07-20) — see the declaration comment on
        # self._grab_suppress_until in __init__ for why this is a wall-clock
        # deadline, not a boolean cleared when this call returns (that was tried
        # and confirmed live NOT to work — Qt delivers some self-inflicted
        # repaints on later event-loop turns). try/finally guarantees the
        # deadline is set even if the grab raises.
        # CURSOR-FLICKER FIX (2026-07-21): hiding `panel` for the grab exposes
        # whatever transport-bar widget is behind it at the cursor position —
        # an arrow-cursor QLabel/QWidget — so Qt re-resolves the LIVE cursor to
        # arrow on hide() and back to the panel widget's cursor on show().
        # Because this grab runs on every dirty-refresh tick (~5-15x/sec while
        # a panel is open), a widget the pointer is resting on with a
        # PointingHand cursor (Stats book rows, cover-pool swatches) flickers
        # hand<->arrow continuously with no mouse movement. Confirmed live via
        # a [CURSOR-TRACE] probe (2026-07-21): BEFORE-HIDE=13(hand) ->
        # AFTER-HIDE=0(arrow) -> AFTER-SHOW=13(hand), every tick. Fix: pin the
        # visible cursor across the hide->grab->show window with an
        # application override set to the shape actually under the pointer
        # right now, then remove it after show(). The whole cycle is
        # synchronous (~2-15ms, no event-loop turn), so the override brackets
        # it cleanly and is gone before any real user input is processed. Only
        # pushed when a panel is actually being hidden and a widget is under
        # the cursor; always popped in the finally, so it can never strand a
        # stuck override.
        from PySide6.QtWidgets import QApplication

        _cursor_override_pushed = False
        # Initialized OUTSIDE the try: the finally below always iterates it, and
        # it is only populated on the panel-visible branch — leaving it unbound
        # would raise NameError out of the finally on every panel-less grab.
        _mouse_blocked = []
        try:
            self._grab_suppress_until = time.perf_counter() + _GRAB_FEEDBACK_SUPPRESS_S
            overlay_was_visible = self._overlay.isVisible()
            if overlay_was_visible:
                self._overlay.hide()
            panel_was_visible = panel is not None and panel.isVisible()
            if panel_was_visible:
                w_under = QApplication.widgetAt(QCursor.pos())
                if w_under is not None:
                    QApplication.setOverrideCursor(w_under.cursor())
                    _cursor_override_pushed = True
                # INPUT-LEAK FIX (2026-08-01). Hiding the panel un-covers the
                # transport widgets for the duration of the grab, and Qt
                # hit-tests against what is actually visible — so a cursor
                # resting over Play/Prev/Next gets a REAL Enter and the button
                # paints itself hovered, and a click lands on a widget the user
                # cannot see. Made mouse-TRANSPARENT rather than hidden: the
                # whole point of the grab is to photograph these widgets, so
                # hiding them would empty the very region being blurred.
                # WA_TransparentForMouseEvents leaves rendering untouched and
                # only stops them being hit-test targets while the panel that
                # should be covering them is temporarily away.
                _mouse_blocked = []
                for _w in self._all_tracked_widgets():
                    if not _w.testAttribute(Qt.WA_TransparentForMouseEvents):
                        _w.setAttribute(Qt.WA_TransparentForMouseEvents, True)
                        _mouse_blocked.append(_w)
                panel.hide()
            src = self.main_window.grab(padded_rect)
            if panel_was_visible:
                panel.show()
            if overlay_was_visible:
                self._overlay.show()
        finally:
            # Restore before the cursor override is popped, and unconditionally
            # — leaving a transport button permanently mouse-transparent would
            # make it unclickable for the rest of the session.
            for _w in _mouse_blocked:
                _w.setAttribute(Qt.WA_TransparentForMouseEvents, False)
            if _cursor_override_pushed:
                QApplication.restoreOverrideCursor()
            self._grab_suppress_until = time.perf_counter() + _GRAB_FEEDBACK_SUPPRESS_S
        t1 = time.perf_counter()

        return self._blur_pad_crop(src, rect, pad, t0=t0, t1=t1,
                                   padded_rect=padded_rect, tag="transport")

    def _blur_pad_crop(self, src: QPixmap, rect: QRect, pad: int, *,
                       t0: float, t1: float, padded_rect: QRect,
                       tag: str) -> QPixmap:
        """Shared tail of both grab paths: blur, crop. Both callers now grab
        main_window (see _grab_and_blur's 2026-08-15 collapse), which is
        already fully painted — no compositing fill is needed here. This
        function previously also built a bg_main/panel_wash canvas underneath
        the grab, for the brief period the transport path grabbed
        content_container instead (2026-08-14–15); that whole path was
        removed with the collapse, not merely disabled, because it never
        worked in the first place: content_container.grab() is opaque
        everywhere, so a fill painted underneath it was provably unreachable
        by the final drawPixmap — see _grab_and_blur's docstring.

        The padding margin exists because QGraphicsBlurEffect treats "outside
        the source pixmap" as transparent and blends that transparency into the
        blurred result near every edge — confirmed live (2026-07-19, the
        color-shift/hard-edge-tint bug): even a fully opaque solid-color source
        came back with alpha as low as 194/255 near its edges after blurring,
        which then visibly tinted whatever was composited underneath. Since
        every dirty sub-rect has edges, blurring it directly always hits this on
        all four sides. Padding pushes the artifact into a margin cropped away
        before the result is composited, so only genuinely blurred, full-alpha
        pixels survive. 4x radius: measured 2026-07-19 (see TODO.md 2026-08-14 —
        the "converges to 255" figure is actually 253, pre-existing).
        """
        blurred_padded = _blur_pixmap(src)
        t2 = time.perf_counter()

        # Crop the padding back off — the margin's edge-transparency artifact
        # never reaches the caller.
        #
        # DEVICE px, not logical: QPixmap.copy() operates on device pixels
        # (measured 2026-08-14), so every term is scaled by dpr. At DPR=1 this
        # is identical to the old `QRect(pad, pad, rect.width(),
        # rect.height())`, which is why that line survived — it was only ever
        # correct on a DPR=1 display. The result keeps `dpr` (copy propagates
        # it), so the returned pixmap is the same logical size as `rect` and
        # the caller's contract is unchanged.
        #
        # (The previous comment here claimed grab() clamps at the widget's real
        # edges and that this is what keeps the crop in range. It does not
        # clamp at all — an out-of-bounds rect returns the full requested size
        # with the outside area simply unpainted, measured 2026-08-14. The crop
        # is in range because the grab is always exactly padded_rect-sized,
        # which is true for any grab source.)
        dpr = src.devicePixelRatio()
        idpr = int(round(dpr))
        crop = QRect(pad * idpr, pad * idpr, rect.width() * idpr, rect.height() * idpr)
        result = blurred_padded.copy(crop)
        t3 = time.perf_counter()

        # Permanent, env-gated DPR verification (2026-08-14). The dev display is
        # DPR=1.0, so a regression in the ledger above is invisible to the eye
        # here — this line is the instrument that catches it, on this machine or
        # a HiDPI one. Enable with FABULOR_GRAB_TRACE=1. Do not delete: it is
        # the standing check for the exact bug that reverted the 2026-07-19
        # attempt.
        if _GRAB_TRACE_ENABLED:
            logger.warning(
                f"[GRAB-DPR] tag={tag} dpr={dpr} src={src.size()} "
                f"blurred={blurred_padded.size()} crop={crop} "
                f"result={result.size()} result_dpr={result.devicePixelRatio()} "
                f"want_logical={rect.size()} "
                f"ok={result.deviceIndependentSize().toSize() == rect.size()}"
            )

        logger.warning(
            f"[PERF] _grab_and_blur tag={tag} rect={rect} padded_rect={padded_rect} "
            f"grab_ms={(t1 - t0) * 1000:.2f} blur_ms={(t2 - t1) * 1000:.2f} "
            f"crop_ms={(t3 - t2) * 1000:.2f} total_ms={(t3 - t0) * 1000:.2f}"
        )
        return result
