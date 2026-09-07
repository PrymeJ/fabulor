"""Animated keyboard-highlight fade for the Speed/Sleep/Sprint preset ramp buttons.

The ramp buttons (Speed's speed grid, Sleep's/Sprint's duration-preset grids) are
plain QPushButtons styled via per-instance setStyleSheet (see each panel's
_apply_preset_ramp_colors) for their base/hover/pressed/keyboard-focus colors.
Animating that highlight in sync with TravelingFocusMarker's own fade (see
focus_marker.py's _FADE_MS) by juggling setStyleSheet strings on every animation
tick would mean reconstructing the WHOLE per-button stylesheet (hover, pressed,
the mouse-hover-suppression rules) each frame, and risks the fade visibly
fighting a real hover/press during the animation.

A sibling overlay widget avoids the stylesheet-juggling problem, but the first
version of this (2026-09-08) got the STACKING wrong: it raised the overlay ABOVE
the button, so at full opacity it painted over the button's own text — reported
live as "it fades away the text too... a dark rectangle." The overlay must sit
BEHIND the button, and the button's own background must go transparent for the
fade's duration, so the sequence each frame is: overlay's fading color paints
first (the new background), then the button's own native paint runs on top and
draws ONLY its text (no fill of its own to hide the overlay) — the button's
`color`/font stays exactly as normal throughout, only its background is
temporarily sourced from the overlay instead of its own QSS `background-color`.
"""
from PySide6.QtCore import Qt, QVariantAnimation, QEasingCurve
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

# Matches focus_marker.py's own _FADE_MS exactly, by explicit live design call
# (2026-09-08): the ramp button's highlight should visually finish fading at the
# same moment the marker itself finishes fading, not before or after.
_FADE_MS = 750


class _RampHighlightOverlay(QWidget):
    """Sibling overlay painting a solid, alpha-fading rect BEHIND one ramp
    button — see this module's docstring for the stacking order and why it
    matters."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._color = QColor("#ffffff")
        self.hide()

    def set_color(self, color: QColor) -> None:
        self._color = color
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), self._color)
        painter.end()


class RampHighlightFade:
    """One instance per panel (Speed/Sleep/Sprint), tracking at most one in-flight
    fade at a time — a button losing keyboard focus before its own fade finishes
    is the normal case (arrow to the next button), not an edge case, so `begin`
    always cancels whatever fade was already showing."""

    def __init__(self):
        self._overlay: _RampHighlightOverlay | None = None
        self._anim: QVariantAnimation | None = None
        self._btn: QWidget | None = None
        self._btn_normal_stylesheet: str = ""

    def begin(self, btn: QWidget, hover_color: QColor) -> None:
        """(Re)start a fade-out on `btn`, from `hover_color` at full opacity down
        to fully transparent, over _FADE_MS. A previous fade on a DIFFERENT
        button (if any) is cancelled and fully restored first."""
        self.cancel()
        # The button's own background must go transparent for the fade's
        # duration — otherwise its normal QSS background-color paints ON TOP
        # of the overlay every frame (buttons paint after their siblings once
        # the overlay is lowered) and the fade is invisible. `background:
        # transparent` overrides the QPushButton rule's background-color
        # without touching color/border/font, and Qt's cascade lets a later
        # declaration win within the same selector — appending it after the
        # button's existing stylesheet is enough, no need to parse/rebuild it.
        self._btn_normal_stylesheet = btn.styleSheet()
        btn.setStyleSheet(
            self._btn_normal_stylesheet + " QPushButton { background: transparent; }"
        )
        overlay = _RampHighlightOverlay(btn.parentWidget())
        overlay.setGeometry(btn.geometry())
        overlay.set_color(hover_color)
        overlay.show()
        overlay.lower()  # BEHIND the button, not above it — see module docstring
        anim = QVariantAnimation()
        anim.setDuration(_FADE_MS)
        anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        anim.setStartValue(255)
        anim.setEndValue(0)

        def _on_tick(alpha):
            c = QColor(hover_color)
            c.setAlpha(alpha)
            overlay.set_color(c)

        anim.valueChanged.connect(_on_tick)
        anim.finished.connect(self._on_finished)
        anim.start()
        self._overlay = overlay
        self._anim = anim
        self._btn = btn

    def _on_finished(self) -> None:
        # The fade completed on its own (never interrupted by cancel()) —
        # restore the button's real stylesheet and drop the overlay.
        self._restore_and_clear()

    def cancel(self) -> None:
        """Stop any in-flight fade, restore the button's real stylesheet
        (undoing begin()'s `background: transparent` override), and remove
        the overlay — all immediately. MUST restore the stylesheet itself:
        _apply_preset_ramp_colors (the only thing that would otherwise
        reassert it) runs on theme/selection changes, NOT on every focus
        move, so a caller of cancel() (a fresh arrow-press/Tab landing on a
        DIFFERENT button, or _enter_patrol's unconditional call on every
        resume) cannot be assumed to trigger a reassert on its own — an
        earlier version of this method assumed exactly that and left the
        button's background permanently transparent after any interrupted
        fade."""
        self._restore_and_clear()

    def _restore_and_clear(self) -> None:
        if self._anim is not None:
            self._anim.stop()
            self._anim = None
        if self._btn is not None:
            self._btn.setStyleSheet(self._btn_normal_stylesheet)
            self._btn = None
        if self._overlay is not None:
            self._overlay.deleteLater()
            self._overlay = None
