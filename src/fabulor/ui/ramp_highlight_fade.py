"""Animated keyboard-highlight fade for the Speed/Sleep/Sprint preset ramp buttons.

The ramp buttons (Speed's speed grid, Sleep's/Sprint's duration-preset grids) are
plain QPushButtons styled via per-instance setStyleSheet (see each panel's
_apply_preset_ramp_colors) for their base/hover/pressed/keyboard-focus colors.

Two earlier designs were tried and abandoned this same session (2026-09-08),
both confirmed wrong by live screenshots, not assumption:

1. A sibling overlay RAISED above the button — painted over the button's own
   text at full opacity ("it fades away the text too... a dark rectangle").
2. A sibling overlay LOWERED behind the button, with the button's background
   made transparent so the overlay would show through — the fade LOGIC was
   confirmed correct via live tracing (alpha genuinely ran 254->0 over the
   right ~750ms), but the color never visibly changed on screen until the
   very end (two screenshots at "marker stopped" and "marker almost done
   fading" showed the IDENTICAL highlight color, then it snapped) — a Qt
   repaint/compositing gap specific to a lowered sibling behind a
   transparent-background widget, not a logic bug.

This version interpolates the button's OWN `:focus` background-color directly,
via setStyleSheet, on every animation tick — no overlay widget at all. It is
the button's own native paint updating, which is guaranteed to actually
repaint (unlike a lowered sibling's compositing), at the cost of a
setStyleSheet call per frame instead of a cheap widget update(). The button's
full base stylesheet (hover/pressed/kbdnav rules) is preserved verbatim; only
one extra `:focus` rule is appended with the CURRENT interpolated color,
exploiting Qt's stylesheet cascade (a later declaration for the same selector
wins) rather than reconstructing the whole sheet.
"""
from PySide6.QtCore import QVariantAnimation, QEasingCurve
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget

# Matches focus_marker.py's own _FADE_MS exactly, by explicit live design call
# (2026-09-08): the ramp button's highlight should visually finish fading at the
# same moment the marker itself finishes fading, not before or after.
_FADE_MS = 750


class RampHighlightFade:
    """One instance per panel (Speed/Sleep/Sprint), tracking at most one in-flight
    fade at a time — a button losing keyboard focus before its own fade finishes
    is the normal case (arrow to the next button), not an edge case, so `begin`
    always cancels whatever fade was already showing."""

    def __init__(self):
        self._anim: QVariantAnimation | None = None
        self._btn: QWidget | None = None
        self._btn_normal_stylesheet: str = ""
        self._focus_selector: str = ""

    def begin(self, btn: QWidget, hover_color: QColor, base_color: QColor,
              focus_selector: str) -> None:
        """(Re)start a fade-out on `btn`'s :focus background, from `hover_color`
        down to `base_color` (its own normal, un-highlighted ramp color), over
        _FADE_MS. `focus_selector` is the exact QSS selector string that
        currently paints the highlight (e.g.
        'QWidget#speed_panel[kbdnav="true"][kbdnav_marker_active="true"] QPushButton:focus')
        — passed in rather than hardcoded here so this module stays panel-
        agnostic; each panel already builds this selector for its own base
        stylesheet and can hand over the same string. A previous fade on a
        DIFFERENT button (if any) is cancelled and fully restored first."""
        self.cancel()
        self._btn_normal_stylesheet = btn.styleSheet()
        self._focus_selector = focus_selector
        self._btn = btn
        anim = QVariantAnimation()
        anim.setDuration(_FADE_MS)
        # LINEAR, not InOutQuad — must match focus_marker.py's own _fade_anim,
        # which sets no easing curve at all (Qt's default is Linear). An
        # InOutQuad curve on an EARLIER overlay-based version of this fade
        # kept the color visually unchanged for the first ~40% of the
        # duration then dropped it fast at the end — live-traced and
        # confirmed as a curve mismatch, not a timing bug (both fades were
        # already starting/ending within ~25ms of each other).
        anim.setEasingCurve(QEasingCurve.Type.Linear)
        anim.setStartValue(hover_color)
        anim.setEndValue(base_color)

        def _on_tick(color):
            btn.setStyleSheet(
                self._btn_normal_stylesheet
                + f" {focus_selector} {{ background-color: {color.name()}; }}"
            )

        anim.valueChanged.connect(_on_tick)
        anim.finished.connect(self._on_finished)
        anim.start()
        self._anim = anim

    def _on_finished(self) -> None:
        # The fade completed on its own (never interrupted by cancel()) —
        # restore the button's real stylesheet (drops the appended override
        # rule, so the button's normal :focus rule — still fully lit, since
        # [kbdnav_marker_active] flips false separately via
        # MainWindow._on_focus_marker_dormant_changed — takes back over
        # rendering nothing, since kbdnav_marker_active is already false by
        # the time this fires).
        self._restore_and_clear()

    def cancel(self) -> None:
        """Stop any in-flight fade and restore the button's real stylesheet
        immediately — a fresh arrow-press/Tab (MainWindow._on_focus_marker_
        fade_cancel, called unconditionally on every marker resume) must snap
        the highlight back to full brightness instantly, not leave the
        override rule's last interpolated color in place."""
        self._restore_and_clear()

    def _restore_and_clear(self) -> None:
        if self._anim is not None:
            self._anim.stop()
            self._anim = None
        if self._btn is not None:
            self._btn.setStyleSheet(self._btn_normal_stylesheet)
            self._btn = None
