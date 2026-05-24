import functools
from pathlib import Path
from PySide6.QtCore import Qt, QByteArray
from PySide6.QtGui import QPixmap, QPainter
from PySide6.QtSvg import QSvgRenderer

ICONS_DIR = Path(__file__).parent.parent / "assets" / "icons"

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