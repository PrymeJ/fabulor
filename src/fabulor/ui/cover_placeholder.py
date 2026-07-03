"""Cover-art placeholder logo rendering.

When a book has no cover art, the Fabulor logo SVG is shown in the cover
label instead of a real cover. This module owns that rendering and the
"currently showing the placeholder" state that MainWindow used to track via
a bare ``_showing_placeholder`` bool.

Extracted from ``app.py`` (MainWindow) with no behavioral change — same SVG,
same recolor regexes, same ``COVER_AREA_HEIGHT * 0.65`` sizing, same
show/hide-on-exception behavior. The theme-color resolution stays at the
call site in app.py; this module just takes the resolved color string.
"""
import os
import re

from PySide6.QtCore import Qt, QByteArray
from PySide6.QtGui import QPixmap, QPainter
from PySide6.QtSvg import QSvgRenderer

from .ui_helpers import _ASSETS_DIR, COVER_AREA_HEIGHT


class CoverPlaceholder:
    """Renders the Fabulor logo placeholder into a cover label and tracks
    whether it is currently the thing being shown."""

    def __init__(self):
        self._showing = False

    def show(self, cover_art_label, color: str) -> None:
        """Render and display the placeholder logo in ``cover_art_label``."""
        try:
            logo_path = os.path.join(_ASSETS_DIR, "fabulor.svg")
            with open(logo_path) as f:
                data = f.read()
            data = re.sub(r'fill="(?!none)[^"]*"',     f'fill="{color}"',   data)
            data = re.sub(r'stroke="(?!none)[^"]*"',   f'stroke="{color}"', data)
            data = re.sub(r'(fill:)(?!none)[^;}"]*',   rf'\g<1>{color}',     data)
            data = re.sub(r'(stroke:)(?!none)[^;}"]*', rf'\g<1>{color}',     data)
            ba = QByteArray(data.encode())
            renderer = QSvgRenderer(ba)
            placeholder_size = int(COVER_AREA_HEIGHT * 0.65)
            pm = QPixmap(placeholder_size, placeholder_size)
            pm.fill(Qt.transparent)
            painter = QPainter(pm)
            renderer.render(painter)
            painter.end()
            cover_art_label.setPixmap(pm)
            cover_art_label.show()
            self._showing = True
        except Exception:
            cover_art_label.hide()
            self._showing = False

    def clear(self) -> None:
        """Mark the placeholder as no longer showing (a real cover loaded)."""
        self._showing = False

    def refresh(self, cover_art_label, color: str) -> None:
        """Re-render at ``color`` only if the placeholder is currently showing
        (used on theme change)."""
        if self._showing:
            self.show(cover_art_label, color)

    @property
    def is_showing(self) -> bool:
        return self._showing
