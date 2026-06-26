"""Excluded Books section for the Library settings tab.

Lists books the user has trashed (is_excluded=1, is_deleted=0) and lets them be
restored. The section is entirely invisible (no header, no space allocated) when
the excluded count is zero — the owner calls reload() on each settings-panel open
to recheck the count.

The per-row restore affordance copies _HistoryRow's hover-reveal slide animation
exactly (same _ANIM_MS / OutCubic-in / InOutQuad-out, same off-screen-right child
overlay), substituting eye.svg for the X icon. Restore is immediate and silent —
no confirm panel.
"""
from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve, QRect, QSize
from PySide6.QtGui import QIcon, QFontMetrics
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea, QToolButton,
)

from .icon_utils import load_currentcolor_icon


class _ExcludedRow(QWidget):
    """One excluded book on a single compact line: "Title — Author" (elided
    right) on the left, a hover-reveal eye button on the right that restores
    the book immediately on click.

    Hover-reveal mechanics are a direct copy of _HistoryRow (book_detail_panel):
    an absolutely-positioned child overlay parked off-screen right, slid in/out
    by animating its geometry over _ANIM_MS."""

    restore_requested = Signal(str)  # emits book path

    _EYE_W   = 26    # width of the revealed eye overlay (compact)
    _ANIM_MS = 250
    ROW_H    = 21    # compact single-line row

    def __init__(self, path: str, title: str, author: str, index: int, parent=None):
        super().__init__(parent)
        self._path = path
        self._row_index = index
        self._state = 'idle'   # idle | hover
        self._anim: QPropertyAnimation | None = None
        self._eye_color = '#cccccc'
        title = (title or "Unknown title").strip()
        author = (author or "").strip()
        self._full_text = f"{title} — {author}" if author else title

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("excluded_row")
        self.setFixedHeight(self.ROW_H)

        hbox = QHBoxLayout(self)
        hbox.setContentsMargins(10, 0, 10, 0)
        hbox.setSpacing(0)

        # Single elided line. Eliding is done manually in _apply_elide against
        # the available width so the eye overlay always has reserved room
        # (text never reflows when the eye slides in).
        self._text_lbl = QLabel(self._full_text)
        self._text_lbl.setObjectName("excluded_row_text")
        hbox.addWidget(self._text_lbl, stretch=1)

        # ── eye overlay (child, absolutely positioned off-screen right) ──
        self._overlay = QWidget(self)
        self._overlay.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._overlay.setObjectName("excluded_row_overlay")
        self._overlay.setFixedHeight(self.ROW_H)

        ov_layout = QHBoxLayout(self._overlay)
        ov_layout.setContentsMargins(2, 0, 2, 0)
        ov_layout.setSpacing(0)

        self._eye_btn = QToolButton(self._overlay)
        self._eye_btn.setObjectName("excluded_row_eye_btn")
        self._eye_btn.setFixedSize(self._EYE_W - 4, self.ROW_H - 4)
        self._eye_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._eye_btn.setToolTip("Restore this book to the library")
        self._eye_btn.clicked.connect(lambda: self.restore_requested.emit(self._path))
        self._set_eye_icon(self._eye_color)
        ov_layout.addWidget(self._eye_btn)

        self._overlay.setGeometry(self.width(), 0, self._EYE_W, self.ROW_H)

        self.setMouseTracking(True)

    def set_colors(self, theme: dict | None):
        if not theme:
            return
        key = 'session_history_row_one' if self._row_index % 2 == 0 else 'session_history_row_two'
        fallback_key = 'library_row_one' if self._row_index % 2 == 0 else 'library_row_two'
        row_bg = theme.get(key) or theme.get(fallback_key) or theme.get('bg_main', 'transparent')
        text_color = theme.get('text', '#ffffff')
        self.setStyleSheet(
            f"QWidget#excluded_row {{ background-color: {row_bg}; }}"
            f"QLabel#excluded_row_text {{ color: {text_color}; font-size: 11px; }}"
        )
        self._overlay.setStyleSheet(f"QWidget#excluded_row_overlay {{ background-color: {row_bg}; }}")
        self._eye_btn.setStyleSheet("QToolButton { background: transparent; border: none; }")
        eye_color = theme.get('accent_light', '#cccccc')
        if eye_color != self._eye_color:
            self._eye_color = eye_color
            self._set_eye_icon(eye_color)
        self._apply_elide()

    def _set_eye_icon(self, color: str):
        icon_size = self.ROW_H - 5   # ~16px in a 21px row
        pixmap = load_currentcolor_icon("eye.svg", color, icon_size)
        self._eye_btn.setIcon(QIcon(pixmap))
        self._eye_btn.setIconSize(QSize(icon_size, icon_size))

    def _apply_elide(self):
        # Reserve the eye width + the layout margins so text never overlaps the
        # eye or reflows when it slides in.
        avail = self.width() - 20 - self._EYE_W   # 10px L + 10px R margins
        if avail <= 0:
            return
        fm = QFontMetrics(self._text_lbl.font())
        self._text_lbl.setText(
            fm.elidedText(self._full_text, Qt.TextElideMode.ElideRight, avail)
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        row_w = self.width()
        if self._state == 'idle':
            self._overlay.move(row_w, 0)
        elif self._state == 'hover':
            self._overlay.setGeometry(row_w - self._EYE_W, 0, self._EYE_W, self.ROW_H)
        self._apply_elide()

    def enterEvent(self, event):
        super().enterEvent(event)
        if self._state == 'idle':
            self._state = 'hover'
            self._slide_overlay(self._EYE_W)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        if self._state == 'hover':
            self._state = 'idle'
            self._slide_overlay(0)

    def _slide_overlay(self, target_w: int):
        """Animate overlay width by sliding its left edge; right edge stays at row right.
        Identical pattern to _HistoryRow._slide_overlay."""
        if self._anim and self._anim.state() == QPropertyAnimation.State.Running:
            self._anim.stop()
        start_geom = self._overlay.geometry()
        row_w = self.width()
        end_geom = QRect(row_w - target_w, 0, target_w, self.ROW_H)
        sliding_in = target_w > start_geom.width()
        self._anim = QPropertyAnimation(self._overlay, b"geometry", self)
        self._anim.setDuration(self._ANIM_MS)
        self._anim.setEasingCurve(
            QEasingCurve.Type.OutCubic if sliding_in else QEasingCurve.Type.InOutQuad
        )
        self._anim.setStartValue(start_geom)
        self._anim.setEndValue(end_geom)
        self._anim.start()

    def animate_out(self, on_done):
        """Collapse the row's height to 0 then call on_done (used after restore)."""
        anim = QPropertyAnimation(self, b"maximumHeight", self)
        anim.setDuration(self._ANIM_MS)
        anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        anim.setStartValue(self.ROW_H)
        anim.setEndValue(0)
        anim.finished.connect(on_done)
        anim.start()
        self._out_anim = anim  # keep ref


class ExcludedBooksSection(QWidget):
    """Collapsible "Excluded Books" section. Invisible (zero height, hidden) when
    no books are excluded. Owner wires `restore` to db.set_book_excluded(path,
    False) + the standard refresh sequence."""

    restore_requested = Signal(str)  # emits book path; owner performs the DB write + refresh

    # Show exactly 3 compact rows; scroll beyond that. 3 × ROW_H(21) + the
    # list container's 4px top margin.
    _LIST_H  = 3 * _ExcludedRow.ROW_H + 4
    _ANIM_MS = 250

    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme: dict | None = None
        self._expanded = False
        self._rows: list[_ExcludedRow] = []
        self._height_anim: QPropertyAnimation | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._header = QLabel("Excluded Books")
        self._header.setObjectName("settings_header")
        outer.addWidget(self._header)

        self._toggle = QLabel("")
        self._toggle.setObjectName("excluded_toggle")
        self._toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle.mousePressEvent = self._on_toggle_clicked
        outer.addWidget(self._toggle)

        # Scrollable list, height-animated open/closed.
        self._scroll = QScrollArea()
        self._scroll.setObjectName("excluded_scroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setMaximumHeight(0)

        self._list_container = QWidget()
        self._list_container.setObjectName("excluded_list_container")
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(0, 4, 0, 0)
        self._list_layout.setSpacing(0)
        self._list_layout.addStretch()
        self._scroll.setWidget(self._list_container)
        outer.addWidget(self._scroll)

    def set_theme(self, theme: dict):
        self._theme = theme
        for row in self._rows:
            row.set_colors(theme)
        self._apply_toggle_text()

    def reload(self, books: list[tuple]):
        """Rebuild from a list of (path, title, author). Hide the whole section
        (zero space) when empty. Called on each settings-panel open."""
        # collapse and clear
        self._expanded = False
        self._scroll.setMaximumHeight(0)
        for row in self._rows:
            row.setParent(None)
            row.deleteLater()
        self._rows = []

        if not books:
            self.setVisible(False)
            return

        self.setVisible(True)
        for i, (path, title, author) in enumerate(books):
            row = self._add_row(path, title, author, i)
            self._rows.append(row)
        self._apply_toggle_text()

    def _add_row(self, path, title, author, index) -> _ExcludedRow:
        row = _ExcludedRow(path, title, author, index, self._list_container)
        row.set_colors(self._theme)
        row.restore_requested.connect(self._on_row_restore)
        # insert before the trailing stretch
        self._list_layout.insertWidget(self._list_layout.count() - 1, row)
        return row

    def _on_row_restore(self, path: str):
        target = next((r for r in self._rows if r._path == path), None)
        if target is None:
            return
        # Fire the DB write/refresh immediately; animate the row out visually.
        self.restore_requested.emit(path)

        def _remove():
            if target in self._rows:
                self._rows.remove(target)
            target.setParent(None)
            target.deleteLater()
            self._apply_toggle_text()
            # When the last row is restored, the list stays visible for the rest
            # of this settings session (it disappears on the next reload()).

        target.animate_out(_remove)

    def _on_toggle_clicked(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._expanded = not self._expanded
        self._animate_height(self._LIST_H if self._expanded else 0)
        self._apply_toggle_text()

    def _animate_height(self, target: int):
        if self._height_anim and self._height_anim.state() == QPropertyAnimation.State.Running:
            self._height_anim.stop()
        self._height_anim = QPropertyAnimation(self._scroll, b"maximumHeight", self)
        self._height_anim.setDuration(self._ANIM_MS)
        self._height_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._height_anim.setStartValue(self._scroll.maximumHeight())
        self._height_anim.setEndValue(target)
        self._height_anim.start()

    def _apply_toggle_text(self):
        n = len(self._rows)
        arrow = "▲" if self._expanded else "▼"
        plural = "book" if n == 1 else "books"
        color = (self._theme or {}).get('text', '#ffffff')
        # font-size 11px = 1px smaller than the settings-panel default (12px).
        self._toggle.setText(
            f'<span style="color:{color}; font-size:11px;">{n} {plural} excluded {arrow}</span>'
        )
