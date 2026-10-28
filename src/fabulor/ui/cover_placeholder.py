"""Cover-art placeholder logo rendering.

When a book has no cover art, the Fabulor logo SVG is shown in the cover
label instead of a real cover, with the book's title (1-2 lines) and author
(1 line, upper-cased) painted beneath it. This module owns that rendering and
the "currently showing the placeholder" state that MainWindow used to track
via a bare ``_showing_placeholder`` bool.

What text goes where is decided by ``cover_placeholder_layout`` (pure logic);
this module supplies the real font measurement and paints the result into
the label's pixmap. Text is painted rather than set on QLabels so the width
that was measured is exactly the width that is drawn — no QLabel word-wrap
or elision can re-flow the pre-elided strings. The theme-color resolution
stays in themes.placeholder_colors; this module just takes the resolved
(logo, title, author) colors.
"""
import os
import re

from PySide6.QtCore import Qt, QByteArray, QRectF
from PySide6.QtGui import QPixmap, QPainter, QFont, QFontMetricsF, QRawFont, QColor
from PySide6.QtSvg import QSvgRenderer

from .ui_helpers import _ASSETS_DIR, COVER_AREA_HEIGHT
from . import cover_placeholder_layout as L


def make_font(family: str, role: str, spacing: float = 0.0) -> QFont:
    """The exact QFont used both to measure and to paint ``role`` text.
    Letter-spacing (author only, chosen per name by the layout) is applied
    here (not via QSS) so measurement and painting agree."""
    f = QFont(family)
    weight = L.ROLE_WEIGHTS.get((family, role), L.FAMILY_WEIGHTS.get(family))
    if weight:
        f.setWeight(QFont.Weight(weight))
    if role == L.ROLE_AUTHOR:
        f.setPixelSize(L.ROLE_PX_SIZES.get((family, role), L.AUTHOR_PX_SIZE))
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    else:
        f.setPixelSize(L.ROLE_PX_SIZES.get((family, role), L.TITLE_PX_SIZE))
    return f


class QtFontMeasurer:
    """Real ``text_width``/``supports_char`` for the layout module. Needs a
    QGuiApplication and the bundled fonts registered."""

    def __init__(self):
        self._metrics = {}
        self._raw = {}

    def metrics(self, family: str, role: str, spacing: float = 0.0) -> QFontMetricsF:
        key = (family, role, spacing)
        fm = self._metrics.get(key)
        if fm is None:
            fm = self._metrics[key] = QFontMetricsF(make_font(family, role, spacing))
        return fm

    def text_width(self, text: str, family: str, role: str, spacing: float = 0.0) -> float:
        # Qt's advance includes letter-spacing after the LAST glyph too, which
        # is never drawn; drop it so fitting and centering match the ink.
        adv = self.metrics(family, role, spacing).horizontalAdvance(text)
        return adv - spacing if text else 0.0

    def supports_char(self, family: str, ch: str) -> bool:
        raw = self._raw.get(family)
        if raw is None:
            raw = self._raw[family] = QRawFont.fromFont(make_font(family, L.ROLE_TITLE))
        # ord(): PySide6's str overload of supportsCharacter returns False for
        # every non-ASCII character (checked 2026-10-27: 'Ă' False, ord('Ă') True).
        return raw.isValid() and raw.familyName() == family and raw.supportsCharacter(ord(ch))


class CoverPlaceholder:
    """Renders the Fabulor logo placeholder (plus title/author) into a cover
    label and tracks whether it is currently the thing being shown."""

    def __init__(self):
        self._showing = False
        self._title = ""
        self._author = ""
        self._measurer = None          # built lazily: needs a running QGuiApplication
        self._layouts = L.PlaceholderLayoutCache()

    def show(self, cover_art_label, colors, title: str, author: str) -> None:
        """Render and display the placeholder in ``cover_art_label``.
        ``colors`` is (logo, title, author)."""
        self._title = title or ""
        self._author = author or ""
        try:
            if self._measurer is None:
                self._measurer = QtFontMeasurer()
            layout = self._layouts.get(self._title, self._author, L.TEXT_MAX_WIDTH_PX,
                                       self._measurer.text_width,
                                       self._measurer.supports_char)
            cover_art_label.setPixmap(self._render(cover_art_label, colors, layout))
            cover_art_label.show()
            self._showing = True
        except Exception:
            cover_art_label.hide()
            self._showing = False

    def _render(self, cover_art_label, colors, layout) -> QPixmap:
        logo_color, title_color, author_color = colors
        w = cover_art_label.width() or 280
        h = COVER_AREA_HEIGHT
        dpr = cover_art_label.devicePixelRatioF()
        pm = QPixmap(int(w * dpr), int(h * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)

        # Logo
        logo_size = L.LOGO_SIZE_PX[layout.state]
        logo_top = L.LOGO_TOP_PX[layout.state]
        _logo_renderer(logo_color).render(
            painter, QRectF((w - logo_size) / 2, logo_top, logo_size, logo_size))

        # Title lines, then author, each horizontally centered.
        painter.setPen(QColor(title_color))
        fm = self._measurer.metrics(layout.title_family, L.ROLE_TITLE)
        painter.setFont(make_font(layout.title_family, L.ROLE_TITLE))
        baseline = logo_top + logo_size + L.LOGO_TITLE_GAP_PX + round(fm.capHeight())
        for i, line in enumerate(layout.title_lines):
            if i:
                baseline += L.TITLE_LINE_PITCH_PX
            painter.drawText(int(round((w - fm.horizontalAdvance(line)) / 2)), baseline, line)
        if layout.author_text:
            painter.setPen(QColor(author_color))
            sp = layout.author_letter_spacing
            afm = self._measurer.metrics(layout.author_family, L.ROLE_AUTHOR, sp)
            painter.setFont(make_font(layout.author_family, L.ROLE_AUTHOR, sp))
            baseline += L.TITLE_AUTHOR_GAP_PX + round(afm.capHeight())
            text_w = self._measurer.text_width(layout.author_text, layout.author_family,
                                               L.ROLE_AUTHOR, sp)
            x = int(round((w - text_w) / 2))
            painter.drawText(x, baseline, layout.author_text)
        painter.end()
        return pm

    def clear(self) -> None:
        """Mark the placeholder as no longer showing (a real cover loaded)."""
        self._showing = False

    def refresh(self, cover_art_label, colors) -> None:
        """Re-render with ``colors`` (logo, title, author) only if the
        placeholder is currently showing (used on theme change). Same
        title/author, so the layout is a cache hit."""
        if self._showing:
            self.show(cover_art_label, colors, self._title, self._author)

    @property
    def is_showing(self) -> bool:
        return self._showing


def _logo_renderer(color: str) -> QSvgRenderer:
    logo_path = os.path.join(_ASSETS_DIR, "fabulor.svg")
    with open(logo_path) as f:
        data = f.read()
    data = re.sub(r'fill="(?!none)[^"]*"',     f'fill="{color}"',   data)
    data = re.sub(r'stroke="(?!none)[^"]*"',   f'stroke="{color}"', data)
    data = re.sub(r'(fill:)(?!none)[^;}"]*',   rf'\g<1>{color}',     data)
    data = re.sub(r'(stroke:)(?!none)[^;}"]*', rf'\g<1>{color}',     data)
    return QSvgRenderer(QByteArray(data.encode()))
