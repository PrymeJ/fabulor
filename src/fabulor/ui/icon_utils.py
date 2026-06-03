import functools
import re
from pathlib import Path
from PySide6.QtCore import Qt, QByteArray
from PySide6.QtGui import QPixmap, QPainter
from PySide6.QtSvg import QSvgRenderer

ICONS_DIR  = Path(__file__).parent.parent / "assets" / "icons"
_LOGO_PATH = Path(__file__).parent.parent / "assets" / "fabulor.svg"

@functools.lru_cache(maxsize=64)
def load_themed_icon(name: str, color: str, size: int, opacity: float = 1.0) -> QPixmap:
    svg_path = ICONS_DIR / name
    with open(svg_path, "r") as f:
        svg_data = f.read()
    svg_data = svg_data.replace('stroke="#000000"', f'stroke="{color}"')
    svg_data = svg_data.replace('fill="#000000"', f'fill="{color}"')
    if '<style' not in svg_data and 'stroke=' not in svg_data:
        svg_data = svg_data.replace('<svg', f'<svg><style>path {{ fill: {color}; }}</style>', 1)
    renderer = QSvgRenderer(QByteArray(svg_data.encode()))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    if opacity < 1.0:
        painter.setOpacity(opacity)
    renderer.render(painter)
    painter.end()
    return pixmap


def render_logo_placeholder(color: str, size: int) -> QPixmap:
    """Render fabulor.svg recolored to `color` into a `size`×`size` QPixmap."""
    try:
        data = _LOGO_PATH.read_text()
        data = re.sub(r'fill="(?!none)[^"]*"',     f'fill="{color}"',   data)
        data = re.sub(r'stroke="(?!none)[^"]*"',   f'stroke="{color}"', data)
        data = re.sub(r'(fill:)(?!none)[^;}"]*',   rf'\g<1>{color}',     data)
        data = re.sub(r'(stroke:)(?!none)[^;}"]*', rf'\g<1>{color}',     data)
        renderer = QSvgRenderer(QByteArray(data.encode()))
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        painter = QPainter(pm)
        renderer.render(painter)
        painter.end()
        return pm
    except Exception:
        return QPixmap()