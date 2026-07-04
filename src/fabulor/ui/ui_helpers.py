"""Shared low-level UI helpers used by both app.py (MainWindow) and the
extracted main_window_builders module.

These were originally module-level in app.py. They were moved here so that
main_window_builders.py can use them without importing app.py (which would
create a circular import: app.py imports the builders module). This module
depends only on Qt + stdlib, so it can never participate in a cycle.
"""
import functools
import os
import re

from PySide6.QtCore import Qt, QByteArray, QSize
from PySide6.QtGui import QPixmap, QIcon, QPainter
from PySide6.QtSvg import QSvgRenderer

_ICONS_DIR  = os.path.join(os.path.dirname(__file__), "..", "assets", "icons")
_ASSETS_DIR = os.path.join(os.path.dirname(__file__), "..", "assets")

# Fixed height of the cover-art box. The window is fixed-size; this value is the
# height the cover area occupies in the correct ("proper") layout. The cover
# pixmap is scaled to fit inside (label width x this height) preserving aspect
# ratio, and centered. A fixed height guarantees the box can never resize and
# push the transport controls out of view.
COVER_AREA_HEIGHT = 280


@functools.lru_cache(maxsize=64)
def _load_svg_pixmap_cached(name, color, size_wh):
    """Cached core for _load_svg_pixmap. Keyed on (name, color, size_wh) — the
    three inputs that fully determine the output (SVG content on disk is static,
    so the same key always renders the same pixmap; a theme change simply passes
    a different `color` → different key). `size_wh` is a hashable (w, h) tuple or
    None (None → the SVG's own defaultSize). Follows icon_utils' lru_cache(64)
    pattern. Returned pixmaps are shared read-only across callers, same as
    icon_utils — callers must not mutate them in place."""
    try:
        path = os.path.join(_ICONS_DIR, name)
        with open(path) as f:
            data = f.read()
        data = re.sub(r'fill="(?!none)[^"]*"',         f'fill="{color}"',   data)
        data = re.sub(r'stroke="(?!none)[^"]*"',       f'stroke="{color}"', data)
        data = re.sub(r'(fill:)(?!none)[^;}"]*',       rf'\g<1>{color}',     data)
        data = re.sub(r'(stroke:)(?!none)[^;}"]*',     rf'\g<1>{color}',     data)
        ba = QByteArray(data.encode())
        renderer = QSvgRenderer(ba)
        target = QSize(*size_wh) if size_wh is not None else renderer.defaultSize()
        pixmap = QPixmap(target)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        return pixmap
    except Exception as e:
        print(f"Warning: could not load icon {name}: {e}")
        return QPixmap()


def _load_svg_pixmap(name, color="white", size=None):
    # Normalize the QSize arg to a hashable (w, h) tuple so it can key the
    # lru_cache (QSize itself is unhashable). None passes through unchanged.
    size_wh = (size.width(), size.height()) if size is not None else None
    return _load_svg_pixmap_cached(name, color, size_wh)


def _load_svg_icon(name, color="white"):
    return QIcon(_load_svg_pixmap(name, color))
