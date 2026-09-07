"""Traveling-border-marker keyboard-focus indicator.

A marker travels continuously along the *border* of whichever control currently holds keyboard
focus. One mechanism, one overlay, works for any widget with a traceable perimeter — a segmented
`pattern_button`, a tab header, and (in future) a slider.

Three interchangeable paint styles share the same phase/motion machinery below (see
`_MARKER_STYLE`): "dot" draws a single filled circle at the current position; "gradient" draws a
short trailing stretch of the border behind it, fading toward the tail (a "comet"); "rotate"
(default) outlines the WHOLE border at all times with a color sweep continuously traveling around
it — no moving position or trail, every point on the perimeter is lit at once and only the COLOR
travels ("a 1px border with rotating hues"). The sweep walks `focus_marker_palette` (a theme-driven
list of 2+ colors, see themes.py GROUP 10), not an HSV hue rotation — hue rotation on this app's
near-white/pale theme text colors is close to a visual no-op (near-zero saturation), so the marker
blends between real, separately-saturated palette colors instead. Switching styles only changes
`paintEvent` / `_marker_color` — the perimeter, phases, and timers (self._t as a moving position
for "dot"/"gradient", or as a sweep phase offset for "rotate") are identical either way.

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
import math
from enum import Enum, auto

from PySide6.QtWidgets import QWidget, QTabBar, QListWidget
from PySide6.QtCore import (Qt, QRect, QPoint, QPointF, QTimer, QVariantAnimation, QElapsedTimer,
                             Property)
from PySide6.QtGui import QPainter, QColor, QPen


# ── Tunable defaults (adjust live; mirror the shipped-default convention) ─────────────────────

# Patrol speed. Fixed pixels-per-second so a small widget's border laps quickly and a wide one
# takes proportionally longer — NOT a fixed lap time. Per direct guidance this should read as
# calm/idle, not urgent: "slow enough not to be annoying." Best-guess default, flagged for live
# tuning.
_PATROL_SPEED_PX_PER_SEC = 5.0

# The dot itself.
_DOT_RADIUS = 3.0        # px

# Corner rounding, so the traced perimeter follows the widget's ACTUAL rendered shape (its QSS
# border-radius) instead of a sharp-cornered box. Values match themes.py's QPushButton
# border-radius (4px, inherited by #pattern_button) and QTabBar::tab's border-top-*-radius (2px,
# top corners only — the bottom corners are square, matching _tab_perimeter's untraced bottom
# edge). If either QSS radius ever changes, update the matching constant here too.
_BUTTON_CORNER_RADIUS = 4.0   # px — QPushButton (and #pattern_button, which doesn't override it)
_TAB_CORNER_RADIUS = 2.0      # px — QTabBar::tab's top-left/top-right radius
_LIST_ITEM_CORNER_RADIUS = 0.0
                              # px — a selected list row paints a plain rectangular block
                              # (QListWidget#settings_folder_list::item:selected sets only a
                              # background-color, no border-radius), so the marker is square
                              # around it. Named rather than a literal 0 so the reason is
                              # recorded and it tracks the QSS if that ever gains a radius.
_CORNER_ARC_SEGMENTS = 6      # polyline segments per rounded corner; higher = smoother arc

# Keyboard-navigable controls that paint SQUARE corners, so the marker must not round them (see
# _corner_radius_for). ClickSlider draws a plain filled rect — no drawRoundedRect, and no
# border-radius in its QSS — so tracing it at the button radius visibly clipped its corners.
_SQUARE_CORNER_OBJECT_NAMES = frozenset(("balance_slider",))

# Qt's painting convention puts pixel CENTRES at half-integer coordinates, so a 1px stroke drawn
# on an integer straddles two rows at half intensity each rather than filling one (measured
# 2026-09-05: #7f7f7f/#808080 across two rows at integer y, one crisp #ffffff row at y+0.5).
# Applied to every perimeter the marker traces — the tab's top edge, and all four edges of a
# widget rect, where it additionally pulls the right/bottom strokes back inside the widget
# (left()+width() is one PAST the last painted pixel).
_HALF_PIXEL = 0.5

# Controls that show keyboard focus as a FILL SHIFT in QSS instead of a traveling border, and so
# must NOT get a marker at all — showing both would double up the affordance this whole mechanism
# exists to keep singular.
#
# The traveling marker is a thin-border affordance. It reads well crawling a small
# #pattern_button or a tab, where the border IS the visual edge of the control; on a large filled
# button the border is not what the eye tracks, so a dot circling it reads as noise rather than
# as "you are here" (live judgement 2026-09-04, after the marker was tried on Audio's Reset
# button and on Library's list boxes).
#
# Their focus appearance lives entirely in themes.py (search the object name) or, for
# excluded_popup, in its own per-row hover-reveal eye animation (ui/excluded_books.py,
# _ExcludedRow.set_hovered) — this module's only job is to stay out of the way.
#
# theme_interval_label (2026-09-06) is not a "fill" like the others — it uses a plain
# `:focus { text-decoration: underline }` QSS rule instead (themes.py). Same reasoning as
# reset_audio_btn's own comment there: the border marker read as noise on this widget, this
# time confirmed live rather than by shared design judgement — the marker was visually
# broken on it (too small/low-contrast to read clearly against a bare QLabel), and the
# underline was chosen as a working replacement, not a stylistic preference. The variable
# name stays as-is (every excluded widget shares "skip the traveling marker" even though
# what replaces it differs per widget) rather than renaming it for one new case.
#
# disable_sleep_btn (2026-09-07) reported live the same way reset_audio_btn originally was:
# the marker's geometry read wrong on a large filled button, and the explicit preference was
# for keyboard focus to look exactly like mouse hover instead — already true in themes.py's
# #disable_sleep_btn:focus rule (same focus_sleep_disable_btn fallback both states read), so
# excluding it here is what lets that existing fill show cleanly with no marker drawn over it.
#
# disable_sprint_btn (2026-09-07, same session) — explicitly requested to mirror
# disable_sleep_btn exactly ("Cancel the sprint should have used the hover styling instead of
# the traveling marker, mimicking the Disable sleep timer button"). Note stats_reset_btn
# (Sprint's "Reset all sprint data") is deliberately NOT in this set — explicit instruction the
# same session that it should KEEP the traveling marker, since it has no solid background for
# the marker to compete with visually.
_FILL_FOCUS_OBJECT_NAMES = frozenset((
    "reset_audio_btn", "settings_folder_list", "excluded_popup", "theme_interval_label",
    "disable_sleep_btn", "disable_sprint_btn",
))

# Live-observed 1px horizontal misalignment specific to the QTabBar path — confirmed live
# 2026-08-19 to affect ONLY the tab bar, not #pattern_button rectangles (which render correctly at
# x=rect.left() with no offset), so this is scoped to the tab-bar rect only, not a general fix.
# Root cause not isolated (every synthetic reproduction attempt rendered pixel-correct against a
# reference line; the discrepancy only shows on the real live widget), but the fix itself is
# simple and was specified directly rather than guessed further: shift the traced rect 1px right.
_TAB_RECT_X_NUDGE = 1

# Which paint style to use. "dot": a single filled circle (original). "gradient": a trailing
# stretch of the border behind the current position, fading out toward the tail (a "comet").
# "rotate": the ENTIRE border is always outlined; a color sweep travels continuously around it —
# no moving position, no trail, the whole perimeter is lit at once and only the COLOR travels. All
# three share the exact same phase/motion machinery below; only paintEvent's rendering differs.
# Adjust-live, same convention as the other tunables here.
_MARKER_STYLE = "rotate"   # "dot" | "gradient" | "rotate"

# Fallback rotation palette for the "gradient"/"rotate" shimmer (see _marker_color/
# TravelingFocusMarker.focus_marker_palette), used only until the first QSS qproperty- write
# arrives (or if a theme's focus_marker_palette string is empty/unparseable). The real,
# theme-aware default lives in themes.py's get_base_stylesheet: [accent_light, accent_dark] —
# deliberately NOT accent itself, since #pattern_button[selected="true"]'s background IS accent,
# and a marker that also rotates through accent would nearly vanish against a selected button at
# that point in its cycle. This module-level constant is a generic (non-theme) placeholder purely
# so the widget has something valid to paint with before any stylesheet has been applied.
_DEFAULT_ROTATE_PALETTE = (QColor(196, 206, 214), QColor(110, 120, 130))   # cool steel silver pair

# Gradient-segment tunables (only used when _MARKER_STYLE == "gradient").
_TRAIL_LENGTH_PX = 34.0      # arc-length of the trailing segment, in px along the perimeter
_TRAIL_SAMPLES = 18          # points sampled along the trail; higher = smoother curve/fade
_TRAIL_WIDTH = 1.0           # stroke width, px

# Rotating-border tunables (only used when _MARKER_STYLE == "rotate"). Live-confirmed visible and
# tuned against a real running app (2026-08-19) after an earlier silver-only version read as
# "static" — turned out to be a genuinely working mechanism paired with too-subtle a color choice,
# confirmed by temporarily swapping in a full rainbow. Adjust-live like the rest of this file.
_ROTATE_WIDTH = 1.0          # stroke width, px — "a 1px border"
_ROTATE_SAMPLES = 64         # segments the full perimeter is split into for the palette sweep;
                              # higher = smoother gradient, more drawLine calls per paint
_ROTATE_WAVE_PX = 80.0       # px of border per full palette cycle — fixed in px (not normalized
                              # to perimeter length) so the sweep's visual density looks the same
                              # on a small button and a wide tab header
_ROTATE_SPEED_PX_PER_SEC = 45.0
                              # Own speed for the palette sweep's phase — deliberately NOT tied to
                              # _PATROL_SPEED_PX_PER_SEC. self._t's usual meaning is "fraction of
                              # perimeter traveled," so phase_px = self._t * perimeter_length
                              # advances at exactly _PATROL_SPEED_PX_PER_SEC regardless of the
                              # widget's actual size (the two `* length` / `/ length` cancel) — at
                              # the original 5 px/sec and a 40px wavelength that's one full cycle
                              # every 8 real seconds, which reads as static at a glance. This is a
                              # visual sweep rate, not a physical position, so it gets its own much
                              # faster constant instead.

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
        # Whether this is a real closed loop (last point == first) vs. an open path whose t-wrap
        # is a bookkeeping convenience, not a real segment. `_paint_rotating_border` (the only
        # style that draws every sample connected to its neighbor, INCLUDING the wraparound pair)
        # must know this: drawing a line from point_at(1.0) [== point_at(0.0) after wrap] back to
        # the start is correct for a closed loop (it just re-traces the already-real closing
        # segment) but WRONG for an open path — it fabricates a diagonal line straight across the
        # untraced gap (found live 2026-08-19: this drew a visible slanted line across the tab's
        # bottom and a stray mark outside its left edge, on QTabBar's open top+sides-only path).
        self.closed = len(points) >= 2 and _dist(points[0], points[-1]) < 0.01
        self._seg_len: list[float] = []
        total = 0.0
        for i in range(len(points) - 1):
            d = _dist(points[i], points[i + 1])
            self._seg_len.append(d)
            total += d
        self.length = max(total, 1.0)  # guard div-by-zero for a degenerate 0-size rect

    def vertex_ts(self) -> list:
        """The t-position of every VERTEX on this path, in [0, 1].

        Painting samples the path at evenly-spaced t and joins consecutive samples with straight
        lines. Nothing about even spacing makes a sample land on a corner, so a segment that
        happens to straddle one draws a diagonal SHORTCUT across it and the corner reads as
        clipped. On a 140x12 slider two of the four corners fell 1.625px from the nearest sample
        while the other two landed exactly — which is precisely how it presented live
        (2026-09-05: "always the top right and bottom left").

        Callers merge these into their sample list so every corner is a real sample and no
        segment ever spans one. Cheap: a handful of cumulative sums, recomputed per paint only
        because the perimeter itself is rebuilt on target change, not per frame."""
        ts = [0.0]
        acc = 0.0
        for seg in self._seg_len:
            acc += seg
            ts.append(acc / self.length)
        return ts

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


def _parse_palette(value: str) -> list:
    """Parse a comma-joined hex string into QColors — the form a palette arrives in from QSS,
    since Qt properties cannot carry a Python list. Falls back to _DEFAULT_ROTATE_PALETTE if
    fewer than 2 valid colors survive (empty string before the first stylesheet application, or
    a malformed theme value); the sweep needs at least two to blend between."""
    colors = [QColor(part.strip()) for part in value.split(",") if part.strip()]
    colors = [c for c in colors if c.isValid()]
    return colors if len(colors) >= 2 else list(_DEFAULT_ROTATE_PALETTE)


def _blend_color(a: QColor, b: QColor, frac: float) -> QColor:
    """Plain per-channel RGB lerp from `a` (frac=0) to `b` (frac=1). Deliberately NOT an HSV blend
    — see _marker_color's docstring for why an HSV hue rotation is a visual no-op on the
    near-desaturated colors this app's themes actually use for text/focus_marker."""
    frac = max(0.0, min(1.0, frac))
    return QColor(
        int(a.red()   + (b.red()   - a.red())   * frac),
        int(a.green() + (b.green() - a.green()) * frac),
        int(a.blue()  + (b.blue()  - a.blue())  * frac),
    )


def _corner_arc(center: QPointF, radius: float, start_deg: float, end_deg: float,
                 segments: int = _CORNER_ARC_SEGMENTS) -> list[QPointF]:
    """Points along a circular arc from start_deg to end_deg (Qt-style: 0deg = 3 o'clock, degrees
    increase counter-clockwise), INCLUSIVE of both endpoints. Used to trace a widget's actual
    rounded-rect corners (matching its QSS border-radius) instead of a sharp 90deg corner — a
    straight-line rect perimeter reads as visibly wrong overlaid on a rounded button/tab, since the
    marker is meant to sit ON the real border, not outside or squared off from it."""
    if radius <= 0:
        return [center]
    pts = []
    for i in range(segments + 1):
        deg = start_deg + (end_deg - start_deg) * (i / segments)
        rad = math.radians(deg)
        pts.append(QPointF(center.x() + radius * math.cos(rad),
                            center.y() - radius * math.sin(rad)))
    return pts


def _corner_radius_for(widget) -> float:
    """The corner radius the marker should trace for `widget` — it must match what that widget
    actually PAINTS, or the marker cuts corners the widget doesn't have (or squares off ones it
    does). Confirmed live 2026-09-04 on the Audio tab's balance slider: traced at the button
    radius, its corners were visibly clipped against a square bar.

    Keyed on objectName rather than on class, deliberately: the radius is a QSS fact (themes.py
    styles these by object name), so reading the same key keeps the two in step, and it avoids
    importing widget classes into this module just to isinstance-check them.

    `_SQUARE_CORNER_OBJECT_NAMES` is the exception list because square is the exception — every
    button in these panels is rounded. Add to it when a new square-painted control becomes a
    keyboard stop."""
    return 0.0 if widget.objectName() in _SQUARE_CORNER_OBJECT_NAMES else _BUTTON_CORNER_RADIUS


def _rect_perimeter(rect: QRect, inset: float = 0.0, radius: float = 0.0) -> _Perimeter:
    """Closed loop around all four edges of `rect`, starting at the top-left and going clockwise.
    `inset` (default 0) offsets the path inward from the raw edge; at 0 the marker rides centered ON
    the border line, straddling it. A positive inset would tuck the path fully inside the border.
    `radius` (default 0, sharp corners) rounds all four corners to match the widget's own QSS
    border-radius — the corner is traced as a real arc (see _corner_arc), not cut straight across,
    so the marker follows the button's actual rendered shape.

    Uses `left() + width()` / `top() + height()` for the far edges, NOT `rect.right()` /
    `rect.bottom()` — Qt's QRect.right()/.bottom() are the last INCLUSIVE pixel
    (`left() + width() - 1`), not the true edge coordinate, a documented trap in this codebase
    (see CLAUDE.md's Qt QRect rule). Using them here left the perimeter's right/bottom edges 1px
    short of the widget's actual rendered border (found live 2026-08-19, forcing the marker color
    to solid white to make the 1px gap unambiguous against the real tab border)."""
    l = rect.left() + inset
    t = rect.top() + inset
    r = rect.left() + rect.width() - inset
    b = rect.top() + rect.height() - inset
    rad = max(0.0, min(radius, (r - l) / 2.0, (b - t) / 2.0))
    if rad <= 0:
        tl, tr = QPointF(l, t), QPointF(r, t)
        br, bl = QPointF(r, b), QPointF(l, b)
        return _Perimeter([tl, tr, br, bl, tl])
    pts = []
    # Clockwise from just right of top-left corner: top edge, top-right arc, right edge,
    # bottom-right arc, bottom edge, bottom-left arc, left edge, top-left arc (closes the loop).
    pts += [QPointF(l + rad, t), QPointF(r - rad, t)]
    pts += _corner_arc(QPointF(r - rad, t + rad), rad, 90, 0)
    pts += [QPointF(r, b - rad)]
    pts += _corner_arc(QPointF(r - rad, b - rad), rad, 0, -90)
    pts += [QPointF(l + rad, b)]
    pts += _corner_arc(QPointF(l + rad, b - rad), rad, -90, -180)
    pts += [QPointF(l, t + rad)]
    pts += _corner_arc(QPointF(l + rad, t + rad), rad, 180, 90)
    return _Perimeter(pts)


def _tab_top_edge_perimeter(rect: QRect, inset: float = 0.0) -> _Perimeter:
    """Open path along ONLY the top edge of `rect`, left to right — the marker style tabs
    actually use (2026-09-04).

    Replaces the top+sides path (_tab_perimeter, kept below for reference) because the sides read
    as noise: a tab is a small target, and three edges meant the dot spent most of its lap moving
    vertically through the two short sides, drawing attention to the tab's outline rather than to
    the tab. On some themes the side strokes also sat awkwardly against the neighbouring tab's
    edge. One horizontal sweep across the top is calmer and unambiguous.

    A straight line, but INSET at each end by the tab's own corner radius, so it spans only the
    flat part of the top edge. Running the full width put the ends out where QTabBar::tab's
    border-top-*-radius has already curved the border away, which visually squared off the
    rounded corners — the marker read as a hard bar capping a soft shape (reported live
    2026-09-05). Stopping at the tangent points leaves the corners visibly round.

    Offset by _HALF_PIXEL so the 1px stroke lands ON one pixel row instead of straddling two.
    Measured 2026-09-05: a 1px antialiased line at an INTEGER y renders as two rows at ~50%
    each (#7f7f7f / #808080), while the same line at y+0.5 renders as one crisp full-intensity
    row (#ffffff). The smeared version blends with the tab's own border underneath, which read
    live as the sweep slanting upward at both ends. This matters here and not for the button
    perimeters because those are dominated by their corner arcs and vertical runs; a long
    perfectly-horizontal line is the case where the smear is unmissable."""
    l = rect.left() + inset + _TAB_CORNER_RADIUS
    t = rect.top() + inset + _HALF_PIXEL
    r = rect.left() + rect.width() - inset - _TAB_CORNER_RADIUS
    return _Perimeter([QPointF(l, t), QPointF(r, t)])


def _tab_perimeter(rect: QRect, inset: float = 0.0, radius: float = 0.0) -> _Perimeter:
    """Open path over ONLY the top and two side edges of `rect` — the bottom edge (shared with the
    tab's content panel below) is deliberately not patrolled. Path: bottom-left up
    the left side, across the top, down the right side to bottom-right. t wraps from bottom-right
    back to bottom-left (jumping the un-traced bottom). `radius` rounds only the top-left/top-right
    corners (matching QSS's border-top-*-radius on QTabBar::tab — the bottom corners are square,
    same as the tab widget itself).

    SUPERSEDED 2026-09-04 by _tab_top_edge_perimeter (see its docstring for why) and no longer
    called. Kept because it is the only worked example of an open path with rounded corners, and
    because the geometry bugs it exercised — the phantom wraparound segment and the endpoint
    sampling short of the true end — are easy to reintroduce; both fixes live in
    _paint_rotating_border and _paint_gradient_trail, keyed on _Perimeter.closed.

    Uses `left() + width()` / `top() + height()` for the far edges, NOT `rect.right()` /
    `rect.bottom()` — see _rect_perimeter's docstring for why (the Qt QRect inclusive-edge trap,
    CLAUDE.md)."""
    l = rect.left() + inset
    t = rect.top() + inset
    r = rect.left() + rect.width() - inset
    b = rect.top() + rect.height() - inset
    rad = max(0.0, min(radius, (r - l) / 2.0, (b - t) / 2.0))
    if rad <= 0:
        bl, tl = QPointF(l, b), QPointF(l, t)
        tr, br = QPointF(r, t), QPointF(r, b)
        return _Perimeter([bl, tl, tr, br])
    pts = [QPointF(l, b), QPointF(l, t + rad)]
    pts += _corner_arc(QPointF(l + rad, t + rad), rad, 180, 90)
    pts += [QPointF(r - rad, t)]
    pts += _corner_arc(QPointF(r - rad, t + rad), rad, 90, 0)
    pts += [QPointF(r, b)]
    return _Perimeter(pts)


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
        # Theme-driven rotation palette for the "gradient"/"rotate" styles (see _marker_color).
        # Set via qproperty-focus_marker_palette, a comma-joined hex string (Qt properties can't
        # carry a Python list directly) — parsed once here into real QColors on every write.
        # Falls back to _DEFAULT_ROTATE_PALETTE if the string is empty/unparseable (e.g. before
        # the first stylesheet application).
        self._focus_marker_palette: list[QColor] = list(_DEFAULT_ROTATE_PALETTE)
        # Separate palette used only while the target is a settings TAB — see _active_palette.
        # themes.py defaults it to focus_marker_palette, so the two are identical unless a theme
        # deliberately overrides the tab one.
        self._focus_marker_tab_palette: list[QColor] = list(_DEFAULT_ROTATE_PALETTE)
        # Separate palette used only while the target is a SELECTED button (any #pattern_button-
        # shaped control with the "selected" dynamic property true — see _active_palette). A
        # selected button fills with `accent`, and the default palette's accent_light/accent_dark
        # pairing can read as barely perceptible against that fill on themes where those colors
        # sit close to accent itself (reported live 2026-09-05, screenshots: marker plainly
        # visible on an unselected "Transparent" button, nearly invisible on the selected "Frosty
        # glass" button, same theme, same marker). themes.py defaults it to focus_marker_palette,
        # so this is a no-op split unless a theme actually overrides it — same shape as
        # focus_marker_tab_palette above.
        self._focus_marker_selected_palette: list[QColor] = list(_DEFAULT_ROTATE_PALETTE)

    @Property(QColor)
    def focus_marker_color(self): return self._focus_marker_color
    @focus_marker_color.setter
    def focus_marker_color(self, color): self._focus_marker_color = color; self.update()

    @Property(float)
    def focus_marker_alpha(self): return self._focus_marker_alpha
    @focus_marker_alpha.setter
    def focus_marker_alpha(self, value): self._focus_marker_alpha = value; self.update()

    @Property(str)
    def focus_marker_palette(self): return ",".join(c.name() for c in self._focus_marker_palette)
    @focus_marker_palette.setter
    def focus_marker_palette(self, value: str):
        self._focus_marker_palette = _parse_palette(value)
        self.update()

    @Property(str)
    def focus_marker_tab_palette(self):
        return ",".join(c.name() for c in self._focus_marker_tab_palette)
    @focus_marker_tab_palette.setter
    def focus_marker_tab_palette(self, value: str):
        self._focus_marker_tab_palette = _parse_palette(value)
        self.update()

    @Property(str)
    def focus_marker_selected_palette(self):
        return ",".join(c.name() for c in self._focus_marker_selected_palette)
    @focus_marker_selected_palette.setter
    def focus_marker_selected_palette(self, value: str):
        self._focus_marker_selected_palette = _parse_palette(value)
        self.update()

    def _active_palette(self) -> list:
        """Which palette the current target should be drawn with. A settings TAB sits on the tab
        bar — and, when selected, on its own accent fill — which is a different backdrop from the
        panel behind the buttons, so a palette that reads well on a button can blend into
        invisibility on a tab (reported live 2026-09-05). Themes that need it set
        focus_marker_tab_palette; themes.py defaults that key to focus_marker_palette, so this is
        a no-op split unless a theme actually overrides it.

        A SELECTED button (any #pattern_button-shaped toggle across Look/Controls/Audio — the
        "selected" dynamic property is true) has the same problem for the same reason: it fills
        with `accent`, a different backdrop from an unselected button's transparent background,
        so a palette tuned for the latter can vanish against the former (reported live
        2026-09-05, screenshots: same marker, plainly visible on unselected "Transparent",
        barely visible on selected "Frosty glass"). Checked via `property("selected")` rather
        than a QSS/style query — call sites across the codebase set it as either the string
        "true" or a raw bool, so this compares against both forms rather than assuming one."""
        if isinstance(self._target, QTabBar):
            return self._focus_marker_tab_palette
        try:
            is_selected = self._target is not None and self._target.property("selected") in ("true", True)
        except RuntimeError:
            # Target's C++ object was deleted between the last successful _rebuild_perimeter and
            # this paint (e.g. a panel rebuild) — same stale-widget window _rebuild_perimeter
            # already guards against. Fall back to the plain palette; the next paintEvent will see
            # _perimeter is None (set by _rebuild_perimeter's own matching guard) and skip drawing
            # entirely, so this value is never actually used for long.
            is_selected = False
        if is_selected:
            return self._focus_marker_selected_palette
        return self._focus_marker_palette

    # ── public API (called from app.py's focus wiring) ───────────────────────────────

    def show_for(self, widget: QWidget) -> None:
        """(Re)start patrol on `widget`. Carries the current relative position (self._t) over to
        the new widget's border rather than resetting to a fixed start-point. Interrupts any
        slowing/waiting/fading in progress and resumes full-speed patrol immediately.

        Declines widgets that show focus as a QSS fill shift instead (see
        _FILL_FOCUS_OBJECT_NAMES) — clearing rather than tracing them, so the two affordances
        never appear at once."""
        if widget is None or widget.objectName() in _FILL_FOCUS_OBJECT_NAMES:
            self.clear()
            return
        self._target = widget
        self._rebuild_perimeter()      # keeps self._t (relative-position carryover)
        self._enter_patrol()

    def keep_awake(self) -> None:
        """Restart the idle dwell on the CURRENT target, as if the user had just arrived on it —
        without rebuilding the perimeter or moving the marker.

        For controls where a keypress acts on the control itself rather than moving to another
        one, so the normal "no input for a while, therefore slow to a stop and fade" reading is
        wrong: the user is demonstrably still there. Audio's L/R balance slider is the case that
        prompted this — Left/Right adjust its value instead of changing focus, so without this
        the marker would settle and fade while the user was actively dragging the value.

        Deliberately reuses _enter_patrol wholesale rather than poking the idle timer directly:
        it is the same path a fresh Tab-arrival takes, so it also interrupts an in-flight
        slow/wait/fade and restores full alpha and speed — exactly what "the user is still here"
        should mean, and already well exercised. A no-op when nothing is being shown."""
        if self._target is None or self._perimeter is None:
            return
        # Re-map first: for a list box the traced rect is the SELECTED ROW, not the widget, so
        # the thing being kept awake may also have moved (arrowing between paths). Rebuilding is
        # cheap and a no-op for targets whose geometry did not change.
        self._rebuild_perimeter()
        if self._perimeter is None:
            self.clear()
            return
        self._enter_patrol()

    def clear(self) -> None:
        """Focus left the scope (or the panel closed). Stop everything, hide."""
        was_dormant = self._phase == _Phase.IDLE
        self._target = None
        self._perimeter = None
        self._phase = _Phase.IDLE
        self._stop_all_timers()
        self.hide()
        # Covers the one path where a ramp button's [kbdnav]-gated highlight
        # could otherwise outlive the marker: _update_focus_marker's
        # "focus moved out of scope but keyboard mode is STILL active" branch
        # calls clear() without [kbdnav] itself flipping false (that only
        # happens via _set_keyboard_nav_active, a separate call). The
        # _on_fade_finished notification covers the idle-fade case; this
        # covers every other way the marker can go from showing to hidden.
        if not was_dormant:
            self.main_window._on_focus_marker_dormant_changed(True)

    def reposition(self) -> None:
        """Re-map the target's rect after a layout shift (e.g. a tab switch that moved things).
        No-op if not currently shown. Preserves self._t."""
        if self._target is None or not self.isVisible():
            return
        self._rebuild_perimeter()
        self.update()

    # ── phase transitions ────────────────────────────────────────────────────────────

    def _enter_patrol(self) -> None:
        was_dormant = self._phase == _Phase.IDLE
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
        # Tell MainWindow the marker is visibly active again — see
        # _on_fade_finished's own notification for why this exists (a QSS
        # highlight riding on [kbdnav="true"] alone has no way to know the
        # marker has gone dormant vs. is genuinely showing).
        if was_dormant:
            self.main_window._on_focus_marker_dormant_changed(False)

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
        # A ramp button's own keyboard-highlight QSS rule (Speed/Sleep/Sprint's
        # _apply_preset_ramp_colors) is gated on the panel's [kbdnav="true"]
        # property alone, which stays true for the whole time keyboard mode
        # is logically active — including while the marker itself has
        # idle-faded to nothing. Without this notification the highlight had
        # no way to know the marker had gone dormant and stayed lit
        # indefinitely after the fade finished, reported live 2026-09-08:
        # "the marker disappears after inactivity, but the highlight lingers
        # until I hover with mouse somewhere or press arrows or Tab."
        self.main_window._on_focus_marker_dormant_changed(True)

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
        else traces its full rect, rounded to match whatever corner radius that widget actually
        paints (see _corner_radius_for). Guards a destroyed C++ widget (stale Python ref after a
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
                rect.translate(_TAB_RECT_X_NUDGE, 0)  # see _TAB_RECT_X_NUDGE's own comment
                # inset=0: the path follows the raw border line so the marker sits centered ON it
                # (straddling it half-in/half-out), not tucked inside the perimeter.
                self._perimeter = _tab_top_edge_perimeter(rect)
            elif isinstance(w, QListWidget) and w.currentRow() >= 0:
                # Trace the SELECTED ITEM, not the box. The keyboard's unit of selection inside a
                # list is the row, so a marker around the whole box says nothing about which path
                # is actually selected — and read as "the box is selected, not the item"
                # (reported live 2026-09-05).
                item = w.item(w.currentRow())
                vr = w.visualItemRect(item)
                if not vr.isValid() or vr.isEmpty():
                    self._perimeter = None
                    return
                # visualItemRect is in VIEWPORT coordinates, so map from the viewport — mapping
                # from the list widget itself would be off by the frame and any scroll offset.
                top_left = w.viewport().mapTo(self.main_window, vr.topLeft())
                rect = QRect(top_left, vr.size())
                self._perimeter = _rect_perimeter(
                    rect, inset=_HALF_PIXEL, radius=_LIST_ITEM_CORNER_RADIUS)
            else:
                top_left = w.mapTo(self.main_window, QPoint(0, 0))
                rect = QRect(top_left, w.size())
                # inset=_HALF_PIXEL for the same reason the tab's top edge is offset (see
                # _tab_top_edge_perimeter): a 1px stroke on an integer coordinate straddles two
                # pixel lines at half intensity instead of filling one. It matters on all four
                # edges here, and it also pulls the right/bottom strokes back onto the widget —
                # rect.left()+width() is one PAST the last painted pixel, so at inset 0 those
                # two edges drew just outside the control. Both were visible on the Audio tab's
                # balance slider, whose long flat runs and hard edges leave nowhere to hide
                # (reported live 2026-09-05).
                self._perimeter = _rect_perimeter(
                    rect, inset=_HALF_PIXEL, radius=_corner_radius_for(w))
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

    def _marker_color(self, palette_frac: float | None = None) -> QColor:
        """Marker color at the current fade strength. `focus_marker_color`/`focus_marker_alpha`
        (Qt Properties, set via QSS qproperty- in get_base_stylesheet — see __init__) are the
        theme-driven ceiling color/opacity for the "dot" style; theme.py's own fallback for
        focus_marker derives from `text` (contrasts against that theme's backgrounds by
        construction, unlike accent, which can vanish into a segmented button's selected-state
        fill). self._alpha (0-255, driven only during FADING) scales the ceiling down as the fade
        runs — same ceiling-times-dynamic shape as library.py's _kbd_fill_color()/_kbd_alpha.

        `palette_frac` (0..1, or None — the default, meaning "don't use the palette," used only by
        the "gradient"/"rotate" per-sample shimmer, never by "dot") walks the palette
        `_active_palette()` selects — a real, theme-driven list of 2+ colors (see the
        focus_marker_palette / focus_marker_tab_palette Qt Properties, set via QSS qproperty-
        from get_base_stylesheet) — wrapping smoothly from the
        last color back to the first so a continuous sweep has no seam. None is a deliberate
        sentinel, NOT 0.0 — 0.0 is a legitimate, meaningful sweep position (the very start of the
        palette, i.e. pure palette[0]) and using falsiness to mean "no palette" silently mapped
        every frac==0.0 call to the plain base color instead of palette[0], a real bug caught only
        by testing the boundary value numerically, not by reading the code. This is a plain RGB
        _blend_color between adjacent palette entries, NOT an HSV hue rotation of
        focus_marker_color: most themes' `text` colors are near-white/pale pastels (low saturation
        by design, for legibility against a dark background), and rotating hue on a
        near-zero-saturation color is a visual no-op — hue barely matters once saturation is ~0,
        which is exactly why an earlier version of this looked static/colorless (confirmed live:
        base was pure white, S=0, hue rotation produced the identical color at every angle
        regardless of the shift). Blending between real, separately-saturated theme colors is
        visible regardless of how desaturated any single one of them is."""
        pal = self._active_palette()
        if palette_frac is not None and len(pal) >= 2:
            pos = max(0.0, min(1.0, palette_frac)) * len(pal)
            i = int(pos) % len(pal)
            frac = pos - int(pos)
            c = _blend_color(pal[i], pal[(i + 1) % len(pal)], frac)
        else:
            c = QColor(self._focus_marker_color)
        c.setAlpha(int(self._focus_marker_alpha * 255) * self._alpha // 255)
        return c

    def paintEvent(self, event):
        if self._perimeter is None or self._phase == _Phase.IDLE:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        try:
            if _MARKER_STYLE == "rotate":
                self._paint_rotating_border(p)
            elif _MARKER_STYLE == "gradient":
                self._paint_gradient_trail(p)
            else:
                self._paint_dot(p)
        finally:
            p.end()

    def _paint_dot(self, p: QPainter) -> None:
        pos = self._perimeter.point_at(self._t)
        p.setPen(Qt.NoPen)
        p.setBrush(self._marker_color())
        p.drawEllipse(pos, _DOT_RADIUS, _DOT_RADIUS)

    def _paint_gradient_trail(self, p: QPainter) -> None:
        """Short trailing stretch of the perimeter behind the current position (self._t), fading
        toward the tail with a slow hue drift — drawn as _TRAIL_SAMPLES short connected segments
        (each its own color/alpha) rather than one stroke, since QPen/QLinearGradient can't express
        a fade *along* an arbitrary curved path. The leading sample (closest to self._t) is the
        brightest/most opaque; the tail sample is dimmest, mirroring the "comet" look a plain dot
        doesn't have.

        `self._t - i * step_t` going negative is CLAMPED to 0.0 on an open perimeter, not wrapped.
        `point_at` wraps any t into [0,1) unconditionally — correct for a closed loop (continuing
        backward past the start just continues around the loop, which is real geometry there), but
        on an open path (the tab's top+sides-only path) a negative t wraps to NEAR 1.0, i.e. the
        FAR end of the path, not a smooth continuation off the near end. Near self._t≈0 (i.e. near
        the tab's bottom-left start), this drew a stray line jumping most of the way across to the
        other side — the same class of bug as _paint_rotating_border's phantom wraparound segment,
        just triggered by a different sampling shape (backward-from-head vs. full-perimeter)."""
        step_t = (_TRAIL_LENGTH_PX / _TRAIL_SAMPLES) / self._perimeter.length
        if self._perimeter.closed:
            pts = [self._perimeter.point_at(self._t - i * step_t) for i in range(_TRAIL_SAMPLES + 1)]
        else:
            pts = [self._perimeter.point_at(max(0.0, self._t - i * step_t))
                   for i in range(_TRAIL_SAMPLES + 1)]
        pen = QPen()
        pen.setWidthF(_TRAIL_WIDTH)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        for i in range(_TRAIL_SAMPLES):
            frac = i / _TRAIL_SAMPLES              # 0 at the head, ~1 at the tail
            fade = 1.0 - frac                       # opacity ceiling for this segment; also the
                                                      # palette blend strength — pure palette[0] at
                                                      # the head, fading to the plain base color at
                                                      # the tail
            color = self._marker_color(palette_frac=fade)
            color.setAlpha(int(color.alpha() * fade))
            pen.setColor(color)
            p.setPen(pen)
            p.drawLine(pts[i], pts[i + 1])

    def _paint_rotating_border(self, p: QPainter) -> None:
        """The ENTIRE perimeter outlined at once — no moving position, no trail. Split into
        _ROTATE_SAMPLES short connected segments, each colored by a palette-sweep position that is
        a function of arc-length position ALONG the border (fixed cycle length in px, so the sweep
        looks the same density on any widget size) plus a continuously advancing phase offset —
        this is what makes the sweep visibly travel around the loop rather than sit static. The
        phase is derived from self._t (self._t * length advances at exactly
        _PATROL_SPEED_PX_PER_SEC, independent of `length` — the two `* length` / `/ length`
        cancel), rescaled by _ROTATE_SPEED_PX_PER_SEC / _PATROL_SPEED_PX_PER_SEC so the sweep gets
        its OWN visual speed rather than inheriting the (much slower, tuned for "calm dot") patrol
        speed — at patrol speed an 80px cycle took many real seconds per lap, which read as static
        at a glance (confirmed live by temporarily swapping in a full rainbow, which made the same
        underlying motion obviously visible — the mechanism was always working, the plain
        two-color-silver default was just too subtle a color choice to register at this speed).
        self._t is still driven by exactly the same PATROL/SLOWING/WAITING motion machinery as the
        other two styles (see _on_motion_tick): full speed while patrolling, easing to a stop for
        SLOWING/WAITING — the rescale preserves that easing, so the sweep itself slows and holds
        too, rather than the whole border just cutting off mid-sweep."""
        length = self._perimeter.length
        phase_px = self._t * length * (_ROTATE_SPEED_PX_PER_SEC / _PATROL_SPEED_PX_PER_SEC)
        # `point_at` wraps t into [0,1), so t=1.0 silently aliases to t=0.0 (the start) — fine for
        # a closed loop (that IS the true endpoint) but wrong for an open path, where the true
        # endpoint only exists at t=1.0 exactly and is otherwise unreachable by index sampling.
        # Evenly spacing _ROTATE_SAMPLES+1 index-based samples across [0,1) — the old code —
        # therefore left the open path's last real sample short of the true end (found live
        # 2026-08-19: the tab's right side visibly stopped ~1.4px above its true bottom-right
        # corner while the left side correctly reached its bottom-left corner via index 0, making
        # the two sides look uneven/"slanted" even after the separate phantom-wraparound-segment
        # bug, below, was fixed). Building the sample list explicitly per case fixes both: closed
        # loops keep sampling [0,1) (t=1.0 would just re-visit the start redundantly); open paths
        # sample all _ROTATE_SAMPLES+1 points evenly across the CLOSED interval [0,1] instead, so
        # the final sample is the true endpoint, not an aliased wraparound.
        if self._perimeter.closed:
            ts = [i / _ROTATE_SAMPLES for i in range(_ROTATE_SAMPLES + 1)]
        else:
            ts = [i / _ROTATE_SAMPLES for i in range(_ROTATE_SAMPLES)]
            ts.append(0.999999999)  # true endpoint, avoids t==1.0's wrap
        # Merge in the path's own vertices so no segment straddles a corner and cuts it off as a
        # diagonal — see _Perimeter.vertex_ts. Built against a FIXED snapshot of the even samples
        # (`lo`/`hi` and the dedup both read `ts` as it was, not as it is being appended to): an
        # earlier attempt tested against the list while mutating it, so a vertex could be
        # measured against a moving bound and silently dropped — which left the bottom-left
        # corner still cut. Re-sorted afterwards so the walk stays monotonic, which arc_px below
        # depends on.
        lo, hi = ts[0], ts[-1]
        merged = sorted(ts + [vt for vt in self._perimeter.vertex_ts() if lo < vt < hi])
        # Deduplicate AFTER sorting, against the previous kept value — so vertices are checked
        # against each other, not only against the even samples. A rounded rect contributes ~30
        # arc vertices, many closer together than _EPS, and an earlier version that compared
        # each vertex only to the even samples let those through: the list came back
        # non-monotonic, which silently corrupts arc_px below (it assumes strictly increasing t).
        _EPS = 1e-9
        ts = [merged[0]]
        for t in merged[1:]:
            if t - ts[-1] > _EPS:
                ts.append(t)
        pts = [self._perimeter.point_at(t) for t in ts]
        pen = QPen()
        pen.setWidthF(_ROTATE_WIDTH)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)  # RoundCap bulges at the joints between these many
                                                   # short adjoining segments, reading thicker than
                                                   # the actual _ROTATE_WIDTH.
        for i in range(len(pts) - 1):
            # From the sample's own t, NOT from its index — the corner merge above makes the
            # spacing uneven, so an index-derived position would stretch and compress the colour
            # sweep around every corner.
            arc_px = ts[i] * length
            # Continuous sweep position through the palette, in [0, 1), wrapping — NOT a
            # symmetric -1..1 wave. A sine wave would bounce back and forth between only two
            # points in the palette (its min/max) rather than genuinely cycling through every
            # color in a 3+ color palette in order.
            pos = ((arc_px + phase_px) / _ROTATE_WAVE_PX) % 1.0
            color = self._marker_color(palette_frac=pos)
            pen.setColor(color)
            p.setPen(pen)
            p.drawLine(pts[i], pts[i + 1])
