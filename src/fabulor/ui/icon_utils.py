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


@functools.lru_cache(maxsize=64)
def load_currentcolor_icon(name: str, color: str, size: int) -> QPixmap:
    """Tint an SVG that uses fill="currentColor" (e.g. clock.svg, calendar.svg).
    load_themed_icon only swaps fill="#000000"; for currentColor icons its
    <style> fallback loses to the path's inline attribute, so they render
    untinted. This regex approach recolors any non-`none` fill/stroke while
    leaving `fill="none"` and `fill-opacity` rects transparent."""
    data = (ICONS_DIR / name).read_text()
    data = re.sub(r'fill="(?!none)[^"]*"',   f'fill="{color}"',   data)
    data = re.sub(r'stroke="(?!none)[^"]*"', f'stroke="{color}"', data)
    renderer = QSvgRenderer(QByteArray(data.encode()))
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    renderer.render(painter)
    painter.end()
    return pm


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


def render_logo_placeholder_bordered(color: str, icon_size: int, canvas_w: int, canvas_h: int, offset_y: int = 0) -> QPixmap:
    """Render fabulor.svg centered on a `canvas_w`×`canvas_h` canvas with a 2px border."""
    from PySide6.QtGui import QColor
    icon = render_logo_placeholder(color, icon_size)
    pm = QPixmap(canvas_w, canvas_h)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    if not icon.isNull():
        painter.drawPixmap((canvas_w - icon_size) // 2, (canvas_h - icon_size) // 2 + offset_y, icon)
    painter.setPen(QColor(color))
    painter.drawRect(pm.rect().adjusted(0, 0, -1, -1))
    painter.end()
    return pm