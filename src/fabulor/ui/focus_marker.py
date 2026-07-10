"""Traveling-border-marker keyboard-focus indicator.

A single small dot travels continuously along the *border* of whichever control currently holds
keyboard focus. One mechanism, one overlay, works for any widget with a traceable perimeter — a
segmented `pattern_button`, a tab header, and (in future) a slider.

Why an overlay (not a QSS `[focused]` rule or per-widget paintEvent): the dot must be drawn ON the
control's border and reach even inline-styled buttons whose own stylesheet would override a panel
QSS rule. A single mouse-transparent overlay child of MainWindow, mapping the focused widget's rect
into its own coordinates, sidesteps all of that — the same approach the earlier (now discarded)
ring/caret/pulse comparison build used, kept only at that structural level.

Scope for this pass (deliberately narrow): wired for the Settings panel's **Look tab only** — its
`pattern_button` groups plus the Settings tab bar header. See app.py's `_update_focus_marker`.

Lifecycle — a four-phase state machine, NOT Library's hold-then-fade or the tassel's sway/kick:

    PATROL   dot moves along the border at a FIXED speed (px/sec, size-independent), indefinitely,
             as long as focus stays put and no further Tab/Backtab arrives.
    SLOWING  after `_IDLE_BEFORE_SLOWDOWN_MS` of no keyboard input, the dot decelerates smoothly to
             a stop (it must NOT fade while still moving).
    WAITING  once stopped, it sits fully visible and stationary for `_WAIT_MS`.
    FADING   only then does it fade out over `_FADE_MS`.

Any Tab/Backtab (or fresh focus arrival) during SLOWING/WAITING/FADING resumes PATROL immediately
on the newly-focused widget, at the *carried-over relative position* (same % of perimeter traveled)
— a fade in progress never blocks the next move.

Tunables are the module-level `_*` constants below; all are flagged as adjust-live defaults, the
same convention as Library's keyboard-selection highlight alpha (`library_item_keyboard_alpha`).
"""
from enum import Enum, auto

from PySide6.QtWidgets import QWidget, QTabBar
from PySide6.QtCore import (Qt, QRect, QPoint, QPointF, QTimer, QVariantAnimation, QElapsedTimer,
                             Property)
from PySide6.QtGui import QPainter, QColor


# ── Tunable defaults (adjust live; mirror the shipped-default convention) ─────────────────────

# Patrol speed. Fixed pixels-per-second so a small widget's border laps quickly and a wide one
# takes proportionally longer — NOT a fixed lap time. Per direct guidance this should read as
# calm/idle, not urgent: "slow enough not to be annoying." Best-guess default, flagged for live
# tuning.
_PATROL_SPEED_PX_PER_SEC = 11.0

# The dot itself.
_DOT_RADIUS = 3.0        # px

# Phase timings.
_IDLE_BEFORE_SLOWDOWN_MS = 2600   # PATROL -> SLOWING: quiet time before the dot starts decelerating
_SLOWDOWN_MS = 1200                # SLOWING duration: smooth decel to a full stop
_WAIT_MS = 750                    # WAITING duration: stopped, fully visible, before the fade begins
_FADE_MS = 750                    # FADING duration: alpha -> 0

# Motion driver tick. ~60fps; distance-based so the visual speed is tick-rate-independent.
_TICK_MS = 16


class _Phase(Enum):
    IDLE = auto()      # nothing focused / hidden
    PATROL = auto()    # moving at fixed speed, indefinitely
    SLOWING = auto()   # decelerating to a stop
    WAITING = auto()   # stopped, full alpha, holding
    FADING = auto()    # stopped, alpha fading to 0


class _Perimeter:
    """An ordered, closed-or-open polyline around (part of) a widget's border, with arc-length
    lookup. Built once per focus target from a rect. `point_at(t)` maps t in [0,1) to a QPointF
    along the path; `length` is the total px traveled for one full lap (used for fixed-speed t
    advancement)."""

    def __init__(self, points: list[QPointF]):
        # `points` are the polyline vertices IN ORDER. For a closed loop (buttons) the last vertex
        # equals the first so the final segment closes it; for an open path (tab header top+sides)
        # it simply ends at the last vertex and t wraps back to the start (a visible jump across
        # the un-traced bottom edge — acceptable, and cheaper than easing it).
        self._pts = points
        self._seg_len: list[float] = []
        total = 0.0
        for i in range(len(points) - 1):
            d = _dist(points[i], points[i + 1])
            self._seg_len.append(d)
            total += d
        self.length = max(total, 1.0)  # guard div-by-zero for a degenerate 0-size rect

    def point_at(self, t: float) -> QPointF:
        t -= int(t)  # wrap into [0,1)
        if t < 0:
            t += 1.0
        target = t * self.length
        acc = 0.0
        for i, seg in enumerate(self._seg_len):
            if acc + seg >= target or i == len(self._seg_len) - 1:
                frac = 0.0 if seg <= 0 else (target - acc) / seg
                a, b = self._pts[i], self._pts[i + 1]
                return QPointF(a.x() + (b.x() - a.x()) * frac,
                               a.y() + (b.y() - a.y()) * frac)
            acc += seg
        return self._pts[0]


def _dist(a: QPointF, b: QPointF) -> float:
    dx, dy = b.x() - a.x(), b.y() - a.y()
    return (dx * dx + dy * dy) ** 0.5


def _rect_perimeter(rect: QRect, inset: float = 0.0) -> _Perimeter:
    """Closed loop around all four edges of `rect`, starting at the top-left and going clockwise.
    `inset` (default 0) offsets the path inward from the raw edge; at 0 the dot rides centered ON
    the border line, straddling it. A positive inset would tuck the path fully inside the border."""
    l = rect.left() + inset
    t = rect.top() + inset
    r = rect.right() - inset
    b = rect.bottom() - inset
    tl, tr = QPointF(l, t), QPointF(r, t)
    br, bl = QPointF(r, b), QPointF(l, b)
    return _Perimeter([tl, tr, br, bl, tl])


def _tab_perimeter(rect: QRect, inset: float = 0.0) -> _Perimeter:
    """Open path over ONLY the top and two side edges of `rect` — the bottom edge (shared with the
    tab's content panel below) is deliberately not patrolled, per the design. Path: bottom-left up
    the left side, across the top, down the right side to bottom-right. t wraps from bottom-right
    back to bottom-left (jumping the un-traced bottom)."""
    l = rect.left() + inset
    t = rect.top() + inset
    r = rect.right() - inset
    b = rect.bottom() - inset
    bl, tl = QPointF(l, b), QPointF(l, t)
    tr, br = QPointF(r, t), QPointF(r, b)
    return _Perimeter([bl, tl, tr, br])


class TravelingFocusMarker(QWidget):
    """Mouse-transparent overlay child of MainWindow that draws the traveling focus dot around the
    currently-focused control. Owns one motion QTimer and one fade QVariantAnimation, both idle
    unless a target is being shown."""

    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.setObjectName("traveling_focus_marker")
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.hide()

        self._target: QWidget | None = None
        self._perimeter: _Perimeter | None = None
        self._t = 0.0                 # normalized position along the perimeter, in [0,1)
        self._phase = _Phase.IDLE
        self._alpha = 255             # 0–255, driven only during FADING
        self._slow_factor = 1.0       # 0..1 speed multiplier, driven only during SLOWING

        # Fixed-speed motion driver. Distance-based advance (px/sec), so t moves at a rate
        # inversely proportional to the perimeter length — same visual speed on any widget size.
        self._motion_timer = QTimer(self)
        self._motion_timer.setInterval(_TICK_MS)
        self._motion_timer.timeout.connect(self._on_motion_tick)
        self._clock = QElapsedTimer()  # measures real dt between ticks

        # Phase timers.
        self._idle_timer = QTimer(self)   # PATROL dwell -> triggers SLOWING
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(self._begin_slowing)

        self._wait_timer = QTimer(self)   # WAITING dwell -> triggers FADING
        self._wait_timer.setSingleShot(True)
        self._wait_timer.timeout.connect(self._begin_fading)

        # SLOWING decel ramp (drives _slow_factor 1 -> 0 with an ease-out so it eases to a stop).
        self._slow_anim = QVariantAnimation(self)
        self._slow_anim.setDuration(_SLOWDOWN_MS)
        self._slow_anim.setStartValue(1.0)
        self._slow_anim.setEndValue(0.0)
        self._slow_anim.valueChanged.connect(self._on_slow_tick)
        self._slow_anim.finished.connect(self._on_slow_finished)

        # FADING alpha ramp.
        self._fade_anim = QVariantAnimation(self)
        self._fade_anim.setDuration(_FADE_MS)
        self._fade_anim.setStartValue(255)
        self._fade_anim.setEndValue(0)
        self._fade_anim.valueChanged.connect(self._on_fade_tick)
        self._fade_anim.finished.connect(self._on_fade_finished)

        # Theme-driven dot color/ceiling-alpha, set via QSS qproperty- in get_base_stylesheet
        # (mirrors ClickSlider's bg_color/fill_color) so a theme change — including a live hover
        # preview, which calls mw.setStyleSheet(get_base_stylesheet(...)) on every tick — repaints
        # the marker automatically, the same way #overall_progress's fill_color does. Defaults
        # here are the theme dict's own fallbacks (theme.get('focus_marker', 'text'-derived) /
        # theme.get('focus_marker_alpha', 1.0)) so an unstyled widget still looks right.
        self._focus_marker_color = QColor("#ffffff")
        self._focus_marker_alpha = 1.0

    @Property(QColor)
    def focus_marker_color(self): return self._focus_marker_color
    @focus_marker_color.setter
    def focus_marker_color(self, color): self._focus_marker_color = color; self.update()

    @Property(float)
    def focus_marker_alpha(self): return self._focus_marker_alpha
    @focus_marker_alpha.setter
    def focus_marker_alpha(self, value): self._focus_marker_alpha = value; self.update()

    # ── public API (called from app.py's focus wiring) ───────────────────────────────

    def show_for(self, widget: QWidget) -> None:
        """(Re)start patrol on `widget`. Carries the current relative position (self._t) over to
        the new widget's border rather than resetting to a fixed start-point. Interrupts any
        slowing/waiting/fading in progress and resumes full-speed patrol immediately."""
        if widget is None:
            self.clear()
            return
        self._target = widget
        self._rebuild_perimeter()      # keeps self._t (relative-position carryover)
        self._enter_patrol()

    def clear(self) -> None:
        """Focus left the scope (or the panel closed). Stop everything, hide."""
        self._target = None
        self._perimeter = None
        self._phase = _Phase.IDLE
        self._stop_all_timers()
        self.hide()

    def reposition(self) -> None:
        """Re-map the target's rect after a layout shift (e.g. a tab switch that moved things).
        No-op if not currently shown. Preserves self._t."""
        if self._target is None or not self.isVisible():
            return
        self._rebuild_perimeter()
        self.update()

    # ── phase transitions ────────────────────────────────────────────────────────────

    def _enter_patrol(self) -> None:
        self._phase = _Phase.PATROL
        self._alpha = 255
        self._slow_factor = 1.0
        self._slow_anim.stop()
        self._fade_anim.stop()
        self._wait_timer.stop()
        # Restart the "quiet time before slowdown" dwell.
        self._idle_timer.start(_IDLE_BEFORE_SLOWDOWN_MS)
        # Ensure the overlay is up and the motion driver running.
        self.setGeometry(self.main_window.rect())
        self.raise_()
        self.show()
        if not self._motion_timer.isActive():
            self._clock.restart()
            self._motion_timer.start()
        self.update()

    def _begin_slowing(self) -> None:
        if self._target is None or self._phase != _Phase.PATROL:
            return
        self._phase = _Phase.SLOWING
        self._slow_anim.stop()
        self._slow_anim.start()   # eases _slow_factor 1 -> 0; motion timer keeps ticking

    def _on_slow_finished(self) -> None:
        # Reached a full stop. Motion timer no longer needs to advance t; hold, then fade.
        if self._phase != _Phase.SLOWING:
            return
        self._slow_factor = 0.0
        self._phase = _Phase.WAITING
        self._motion_timer.stop()
        self._wait_timer.start(_WAIT_MS)
        self.update()

    def _begin_fading(self) -> None:
        if self._phase != _Phase.WAITING:
            return
        self._phase = _Phase.FADING
        self._fade_anim.stop()
        self._fade_anim.start()

    def _on_fade_finished(self) -> None:
        if self._phase != _Phase.FADING:
            return
        # Fully faded and still focused: go dormant but keep the target so a later Tab can carry
        # its relative position over. Hide the overlay (nothing to draw at alpha 0).
        self._phase = _Phase.IDLE
        self._alpha = 0
        self.hide()

    # ── driven ticks ─────────────────────────────────────────────────────────────────

    def _on_motion_tick(self) -> None:
        if self._perimeter is None or self._target is None:
            return
        dt = self._clock.restart() / 1000.0  # seconds since last tick
        # Distance-based, size-independent speed. _slow_factor is 1.0 during PATROL and ramps to 0
        # during SLOWING (WAITING/FADING don't tick — the motion timer is stopped by then).
        speed = _PATROL_SPEED_PX_PER_SEC * self._slow_factor
        self._t += (speed * dt) / self._perimeter.length
        self._t -= int(self._t)
        self.update()

    def _on_slow_tick(self, value) -> None:
        self._slow_factor = float(value)

    def _on_fade_tick(self, value) -> None:
        self._alpha = int(value)
        self.update()

    # ── geometry ──────────────────────────────────────────────────────────────────────

    def _rebuild_perimeter(self) -> None:
        """Map the target's border into overlay coordinates and build its perimeter. A QTabBar
        traces only the active tab's top+side edges (bottom shared with the panel); everything
        else traces its full rounded rect. Guards a destroyed C++ widget (stale Python ref after a
        panel rebuild) as 'no target'."""
        w = self._target
        if w is None:
            self._perimeter = None
            return
        try:
            if not w.isVisible():
                self._perimeter = None
                return
            if isinstance(w, QTabBar):
                idx = w.currentIndex()
                tr = w.tabRect(idx)
                if not tr.isValid():
                    self._perimeter = None
                    return
                top_left = w.mapTo(self.main_window, tr.topLeft())
                rect = QRect(top_left, tr.size())
                # inset=0: the path follows the raw border line so the dot sits centered ON it
                # (straddling it half-in/half-out), not tucked inside the perimeter.
                self._perimeter = _tab_perimeter(rect)
            else:
                top_left = w.mapTo(self.main_window, QPoint(0, 0))
                rect = QRect(top_left, w.size())
                self._perimeter = _rect_perimeter(rect)
        except RuntimeError:
            self._target = None
            self._perimeter = None

    def _stop_all_timers(self) -> None:
        self._motion_timer.stop()
        self._idle_timer.stop()
        self._wait_timer.stop()
        self._slow_anim.stop()
        self._fade_anim.stop()

    # ── paint ────────────────────────────────────────────────────────────────────────

    def _marker_color(self) -> QColor:
        """Dot color at the current fade strength. `focus_marker_color`/`focus_marker_alpha` (Qt
        Properties, set via QSS qproperty- in get_base_stylesheet — see __init__) are the
        theme-driven ceiling color/opacity; theme.py's own fallback for focus_marker derives from
        `text` (contrasts against that theme's backgrounds by construction, unlike accent, which
        can vanish into a segmented button's selected-state fill). self._alpha (0-255, driven only
        during FADING) scales the ceiling down as the fade runs — same ceiling-times-dynamic shape
        as library.py's _kbd_fill_color()/_kbd_alpha."""
        c = QColor(self._focus_marker_color)
        c.setAlpha(int(self._focus_marker_alpha * 255) * self._alpha // 255)
        return c

    def paintEvent(self, event):
        if self._perimeter is None or self._phase == _Phase.IDLE:
            return
        pos = self._perimeter.point_at(self._t)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        try:
            p.setPen(Qt.NoPen)
            p.setBrush(self._marker_color())
            p.drawEllipse(pos, _DOT_RADIUS, _DOT_RADIUS)
        finally:
            p.end()
