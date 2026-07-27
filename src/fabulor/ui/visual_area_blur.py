"""Clipped backdrop blur for `visual_area` (cover art / theme bg_image / quotes).

THE BUG THIS FIXES: `visual_area` is one widget holding three things the user
sees as separate surfaces — the cover art (`cover_art_label`, a child), the theme
background (`bg_image`, painted by the `#visual_area` QSS rule on the widget
itself), and the quotes screen (`quote_section`, a child). A plain
QGraphicsBlurEffect attached to it blurs the WHOLE widget, including the ~30px
sliver to the right of an open panel that the panel does not actually cover and
which the user can plainly see. That sliver must stay sharp.

WHY A PAINT-TIME MASK AND NOT A GRAB-BASED OVERLAY (load-bearing — do not
"simplify" this into an overlay):

    An earlier attempt (2026-07-27, reverted) added a cached-pixmap QLabel
    parented to `content_container` and raised it above everything. That is the
    same stacking context the CoverCarousel lives in (it is parented to
    content_container and deliberately `stackUnder(visual_area)`, at full window
    width). The raised sibling clipped the "Go to Library" button, made geometry
    jump on every blur toggle, and left a frozen non-scrolling strip over the
    live carousel — a static cached frame cannot sit over moving content. Those
    are structural z-order consequences and remain true today. Do not
    re-introduce that approach.

    A QGraphicsEffect subclass introduces NO new stacked sibling and re-renders
    on every paint, so neither failure mode applies. Verified by pixel probe
    before implementing: draw() is invoked per paint and tracks moving content
    (no frozen frame); the clip is a real hard boundary (the sliver keeps pure
    source pixels, zero blurred bleed); and there is no edge-alpha seam at the
    boundary, so none of the 4x-radius padding the grab path needs is required
    here.

COST NOTE: this keeps (adapts) the existing blur_effect rather than retiring it,
so blur re-runs on every paint of visual_area. That is cheap on THIS surface
specifically — unlike the transport bar (continuous 200ms ui_timer / marquee /
slider repaints, which is why the grab-based mechanism exists there), visual_area
has no intrinsic motion, and a carousel scroll tick calls update() on the
CAROUSEL widget, not on its sibling visual_area, so the ~30fps scroll does not
drive this effect.
"""
import logging

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QGraphicsBlurEffect

logger = logging.getLogger(__name__)


class ClippedBlurEffect(QGraphicsBlurEffect):
    """A QGraphicsBlurEffect that blurs ONLY inside `clip_rect`, drawing the rest
    of the source unblurred.

    `clip_rect` is in the effect's SOURCE (widget-local) coordinate space — i.e.
    visual_area-local, not content_container-local and not main-window-local. The
    caller owns the conversion; see PanelManager._apply_visual_area_clip.

    A null/empty clip means "blur nothing" — the source is drawn through
    untouched. That is the correct state when blur is disabled or no panel is
    open, and it makes the effect safe to leave permanently attached.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._clip: QRect = QRect()

    def set_clip_rect(self, rect: QRect | None):
        new = QRect(rect) if rect is not None else QRect()
        if new == self._clip:
            return
        self._clip = new
        self.update()

    def clip_rect(self) -> QRect:
        return QRect(self._clip)

    def draw(self, painter):
        # Null/empty clip: nothing is meant to be blurred. Draw the source
        # straight through — cheaper than blurring and discarding, and this is
        # the resting state whenever no panel is open.
        if self._clip.isNull() or self._clip.isEmpty():
            self.drawSource(painter)
            return

        source_rect = self.sourceBoundingRect().toRect()

        # ONE blurred render, composited ONCE — see the "double-render" note
        # below for why this must not go back to a two-pass draw.
        #
        # Render the blur into an offscreen pixmap first, then blit only the
        # clipped part of it. super().draw(painter) renders the WHOLE source
        # blurred and would rely on the painter's clip to mask it; but
        # QGraphicsBlurEffect pads and offsets its own output, so its render can
        # bleed past the clip boundary and land on top of the sharp drawSource
        # pass underneath — the same pixels rendered twice, compositing to a
        # visibly brighter, "thicker" image.
        #
        # DOUBLE-RENDER BUG (found live 2026-07-27): the original implementation
        # here drew the source twice — drawSource() for the region outside the
        # clip, then super().draw() for the region inside it. That produced a
        # sustained bright/thick "two images superimposed" state during the
        # blur-in animation. Proven to be the blur render itself, not a one-frame
        # artifact, by stretching the blur-in to 8s: the thickened state then
        # persisted for ~2s, scaling with the animation rather than staying a
        # blip. NOTE: this was NOT reproducible offscreen — plain-vs-clipped
        # comparisons across radii 0..10, including a transparent-child-over-
        # themed-background model of visual_area, came back byte-identical every
        # time. Live observation is the only thing that sees it; do not "verify"
        # a change here with an offscreen harness alone.
        blurred = QPixmap(source_rect.size())
        blurred.fill(Qt.transparent)
        p = QPainter(blurred)
        p.translate(-source_rect.topLeft())
        super().draw(p)
        p.end()

        # Sharp source everywhere, then the blurred copy over just the clip.
        # Each output pixel is written by exactly one of these two blits — the
        # clip is applied to the ALREADY-rendered blur, so nothing can bleed.
        self.drawSource(painter)
        painter.save()
        painter.setClipRect(self._clip)
        painter.drawPixmap(source_rect.topLeft(), blurred)
        painter.restore()
