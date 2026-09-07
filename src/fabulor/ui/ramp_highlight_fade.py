"""Animated keyboard-highlight fade for the Speed/Sleep/Sprint preset ramp buttons.

The ramp buttons (Speed's speed grid, Sleep's/Sprint's duration-preset grids) are
plain QPushButtons styled via per-instance setStyleSheet (see each panel's
_apply_preset_ramp_colors) for their base/hover/pressed/keyboard-focus colors.
Animating that highlight in sync with TravelingFocusMarker's own fade (see
focus_marker.py's _FADE_MS) by juggling setStyleSheet strings on every animation
tick would mean reconstructing the WHOLE per-button stylesheet (hover, pressed,
the mouse-hover-suppression rules) each frame, and risks the fade visibly
fighting a real hover/press during the animation.

A sibling overlay widget avoids all of that — same technique tag_manager.py's
_ThumbFocusRing/_DotFocusRing already use for the same underlying reason (Qt
paints a parent before its children, so an overlay is the only way to guarantee
something paints on TOP regardless of the button's own content). The overlay is
a solid rect in the button's OWN hover color, alpha-animated 255->0 over the
marker's own _FADE_MS — the button's real QSS keeps painting underneath
unchanged, so hover/press still work normally through the fade, and cancelling
the fade (a fresh arrow-press, or this button regaining focus) is just hiding
the overlay, no stylesheet reconstruction needed either way.
"""
from PySide6.QtCore import Qt, QVariantAnimation, QEasingCurve
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

# Matches focus_marker.py's own _FADE_MS exactly, by explicit live design call
# (2026-09-08): the ramp button's highlight should visually finish fading at the
# same moment the marker itself finishes fading, not before or after.
_FADE_MS = 750


class _RampHighlightOverlay(QWidget):
    """Sibling overlay painting a solid, alpha-fading rect over one ramp button —
    see this module's docstring for why an overlay rather than a stylesheet
    animation."""

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

    def begin(self, btn: QWidget, hover_color: QColor) -> None:
        """(Re)start a fade-out on `btn`, from `hover_color` at full opacity down
        to fully transparent, over _FADE_MS. A previous fade on a DIFFERENT
        button (if any) is cancelled and its overlay hidden first."""
        self.cancel()
        overlay = _RampHighlightOverlay(btn)
        overlay.setGeometry(btn.rect())
        overlay.set_color(hover_color)
        overlay.show()
        overlay.raise_()
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
        anim.finished.connect(overlay.deleteLater)
        anim.start()
        self._overlay = overlay
        self._anim = anim

    def cancel(self) -> None:
        """Stop any in-flight fade and remove its overlay immediately — the
        caller is about to reassert (or has already reasserted) the button's
        own normal highlighted style itself, so there's nothing left for the
        overlay to sit on top of."""
        if self._anim is not None:
            self._anim.stop()
            self._anim = None
        if self._overlay is not None:
            self._overlay.deleteLater()
            self._overlay = None
