from pathlib import Path
from PySide6.QtWidgets import QWidget, QHBoxLayout, QToolButton, QApplication
from PySide6.QtCore import Qt, QEvent, QPoint, QSize
from PySide6.QtGui import QIcon

from .icon_utils import load_themed_icon

_ICONS_DIR = Path(__file__).parent.parent / "assets" / "icons"
_BTN_SIZE = 20
_ICON_SIZE = 14


class ContextIconMenu(QWidget):
    """Floating horizontal icon menu for QLineEdit context actions.

    One shared instance. Call show_for(target, global_pos) to display it.
    Dismisses on action or focus loss.
    """

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._target = None
        self._color = "#ffffff"
        self._build_ui()

    def _build_ui(self):
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 4, 4, 4)
        row.setSpacing(2)

        self._cut_btn   = self._make_btn("cut.svg",    self._do_cut)
        self._copy_btn  = self._make_btn("copy.svg",   self._do_copy)
        self._paste_btn = self._make_btn("paste.svg",  self._do_paste)
        self._del_btn   = self._make_btn("delete.svg", self._do_delete)

        for btn in (self._cut_btn, self._copy_btn, self._paste_btn, self._del_btn):
            row.addWidget(btn)

    def _make_btn(self, icon_name: str, slot) -> QToolButton:
        btn = QToolButton(self)
        btn.setFixedSize(_BTN_SIZE, _BTN_SIZE)
        btn.setIconSize(QSize(_ICON_SIZE, _ICON_SIZE))
        btn.setAutoRaise(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(slot)
        btn.setProperty("_icon_name", icon_name)
        return btn

    def _refresh_icons(self):
        for btn in (self._cut_btn, self._copy_btn, self._paste_btn, self._del_btn):
            name = btn.property("_icon_name")
            icon = QIcon()
            icon.addPixmap(load_themed_icon(name, self._color, _ICON_SIZE, 0.9), QIcon.Mode.Normal)
            icon.addPixmap(load_themed_icon(name, self._color, _ICON_SIZE, 0.3), QIcon.Mode.Disabled)
            btn.setIcon(icon)

    def apply_theme(self, theme: dict):
        _BDR_OPACITY = 0.80
        self._color = theme.get("accent", "#ffffff")
        bg   = theme.get("bg_main", "#1e1e1e")
        _bdr_hex = theme.get("accent", "#555555").lstrip("#")
        r, g, b = int(_bdr_hex[0:2], 16), int(_bdr_hex[2:4], 16), int(_bdr_hex[4:6], 16)
        bdr  = f"rgba({r},{g},{b},{_BDR_OPACITY})"
        hvr  = theme.get("accent_dark", "#555555")
        self.setStyleSheet(
            f"ContextIconMenu {{ background: {bg}; border: 1px solid {bdr}; border-radius: 4px; }}"
            f"QToolButton {{ background: transparent; border: none; }}"
            f"QToolButton:hover {{ background: {hvr}; border-radius: 3px; }}"
        )
        self._refresh_icons()

    def show_for(self, target, global_pos: QPoint):
        self._target = target
        has_sel     = target.hasSelectedText()
        read_only   = target.isReadOnly()
        has_clip    = bool(QApplication.clipboard().text())

        cut_ok    = has_sel and not read_only
        copy_ok   = has_sel
        paste_ok  = has_clip and not read_only
        delete_ok = has_sel and not read_only

        if not any((cut_ok, copy_ok, paste_ok, delete_ok)):
            return

        self._cut_btn.setEnabled(cut_ok)
        self._copy_btn.setEnabled(copy_ok)
        self._paste_btn.setEnabled(paste_ok)
        self._del_btn.setEnabled(delete_ok)

        self.adjustSize()
        w = self.width()
        h = self.height()

        win = QApplication.activeWindow()
        if win is None:
            self.move(global_pos)
            self.show()
            return

        win_global = win.mapToGlobal(QPoint(0, 0))
        content_top = win_global.y()
        content_left = win_global.x()
        content_right = content_left + win.width()
        content_bottom = content_top + win.height()

        x = max(content_left, min(global_pos.x(), content_right - w))
        y = max(content_top, min(global_pos.y(), content_bottom - h))
        self.move(x, y)
        self.show()

    # --- actions ---

    def _dismiss(self):
        self.hide()
        self._target = None

    def _do_cut(self):
        if self._target:
            self._target.cut()
        self._dismiss()

    def _do_copy(self):
        if self._target:
            self._target.copy()
        self._dismiss()

    def _do_paste(self):
        if self._target:
            self._target.paste()
        self._dismiss()

    def _do_delete(self):
        if self._target:
            self._target.del_()
        self._dismiss()
