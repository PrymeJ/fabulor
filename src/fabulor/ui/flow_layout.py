from PySide6.QtWidgets import QLayout
from PySide6.QtCore import Qt, QRect, QSize, QPoint


class FlowLayout(QLayout):
    def __init__(self, parent=None, h_spacing=-1, v_spacing=-1):
        super().__init__(parent)
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self._items = []

    def addItem(self, item):
        self._items.append(item)

    def horizontalSpacing(self):
        if self._h_spacing >= 0:
            return self._h_spacing
        return self._smart_spacing(QStyle.PixelMetric.PM_LayoutHorizontalSpacing)

    def verticalSpacing(self):
        if self._v_spacing >= 0:
            return self._v_spacing
        return self._smart_spacing(QStyle.PixelMetric.PM_LayoutVerticalSpacing)

    def count(self):
        return len(self._items)

    def itemAt(self, index):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return False

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect, test_only):
        margins = self.contentsMargins()
        effective = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x = effective.x()
        y = effective.y()
        line_height = 0
        h_space = self._h_spacing if self._h_spacing >= 0 else 6
        v_space = self._v_spacing if self._v_spacing >= 0 else 6

        for item in self._items:
            item_size = item.sizeHint()
            next_x = x + item_size.width()
            if next_x > effective.right() and line_height > 0:
                x = effective.x()
                y = y + line_height + v_space
                next_x = x + item_size.width()
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item_size))
            x = next_x + h_space
            line_height = max(line_height, item_size.height())

        return y + line_height - rect.y() + margins.bottom()

    def _smart_spacing(self, pm):
        parent = self.parent()
        if parent is None:
            return -1
        from PySide6.QtWidgets import QWidget, QStyle
        if isinstance(parent, QWidget):
            return parent.style().pixelMetric(pm, None, parent)
        return self.spacing()
