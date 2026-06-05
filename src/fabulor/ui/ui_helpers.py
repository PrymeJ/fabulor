"""Shared low-level UI helpers used by both app.py (MainWindow) and the
extracted main_window_builders module.

These were originally module-level in app.py. They were moved here so that
main_window_builders.py can use them without importing app.py (which would
create a circular import: app.py imports the builders module). This module
depends only on Qt + stdlib, so it can never participate in a cycle.
"""
import os
import re

from PySide6.QtCore import Qt, QByteArray
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


def _load_svg_icon(name, color="white"):
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
        size = renderer.defaultSize()
        pixmap = QPixmap(size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        return QIcon(pixmap)
    except Exception as e:
        print(f"Warning: could not load icon {name}: {e}")
        return QIcon()
