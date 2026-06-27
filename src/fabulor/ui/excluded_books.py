"""Excluded Books popup for the Library settings tab.

Lists books the user has trashed (is_excluded=1, is_deleted=0) and lets them be
restored. A toggle line ("N books excluded ▼") in the Library tab opens
ExcludedBooksPopup — a real popup parented directly to MainWindow, not a
widget living inside the settings tab's QVBoxLayout. This mirrors
ChapterList (chapter_list.py) deliberately: that overlay/expand-inline
approach was tried first and hit an unfixable rendering wall inside the
settings panel's fixed-height tab layout (confirmed independently twice).
Parenting to MainWindow and positioning/sizing it directly (setGeometry,
show(), raise_()) sidesteps the whole class of QVBoxLayout/QScrollArea
interaction that caused that — same as ChapterList already does for chapter
navigation.

Difference from ChapterList: this expands DOWNWARD from its anchor (the
toggle line sits mid-panel, not pinned near the bottom of a fixed area like
the chapter label), and there is no second-level "expand further" tier —
ChapterList's _can_expand/_expand_btn two-stage reveal doesn't apply here.

The per-row restore affordance copies _HistoryRow's hover-reveal slide
animation exactly (same _ANIM_MS / OutCubic-in / InOutQuad-out, same
off-screen-right child overlay), substituting eye.svg for the X icon.
Restore is immediate and silent — no confirm panel.
"""
from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve, QRect, QSize, QTimer
from PySide6.QtGui import QIcon, QFontMetrics
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QToolButton, QListWidget, QListWidgetItem,
    QGraphicsOpacityEffect,
)

from .icon_utils import load_currentcolor_icon
from ..themes import _hex_to_rgb


class _ExcludedRow(QWidget):
    """One excluded book on a single compact line: title (primary) and author
    (secondary, dimmed) on the left, a hover-reveal eye button on the right
    that restores the book immediately on click.

    Hover-reveal mechanics are a direct copy of _HistoryRow (book_detail_panel):
    an absolutely-positioned child overlay parked off-screen right, slid in/out
    by animating its geometry over _ANIM_MS."""

    restore_requested = Signal(str)  # emits book path

    _EYE_W   = 26    # width of the revealed eye overlay (compact)
    _ANIM_MS = 250
    ROW_H    = 24    # matches ChapterList.ROW_HEIGHT for visual consistency

    def __init__(self, path: str, title: str, author: str, index: int, parent=None):
        super().__init__(parent)
        self._path = path
        self._row_index = index
        self._state = 'idle'   # idle | hover
        self._anim: QPropertyAnimation | None = None
        self._eye_color = '#cccccc'
        self._title = (title or "Unknown title").strip()
        self._author = (author or "").strip()

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("excluded_row")
        self.setFixedHeight(self.ROW_H)

        hbox = QHBoxLayout(self)
        # Left margin reserves room for the eye overlay (see below) so text
        # never overlaps it or reflows when it slides in on hover — mirrors
        # the old right-margin reservation, just on the other edge now.
        hbox.setContentsMargins(self._EYE_W, 1, 10, 0)
        hbox.setSpacing(6)

        self._title_lbl = QLabel(self._title)
        self._title_lbl.setObjectName("excluded_row_title")
        self._title_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._author_lbl = QLabel(self._author)
        self._author_lbl.setObjectName("excluded_row_author")
        # Both vertically centered in the row — without this the author
        # label (smaller font, 11px vs the title's 12px) sat visibly higher
        # than the title since QLabel top-aligns by default and the two
        # fonts have different ascent/line-height.
        self._author_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        hbox.addWidget(self._title_lbl)
        hbox.addWidget(self._author_lbl, stretch=1)

        # ── eye overlay (child, absolutely positioned off-screen LEFT) ──
        # Left, not right: the popup's QListWidget owns a vertical scrollbar
        # at the row's right edge, so a right-side reveal (the _HistoryRow
        # pattern this was originally copied from) would contest that same
        # strip. Left is clear of the scrollbar and still reads naturally as
        # "reveal an action for this row" on hover.
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

        self._overlay.setGeometry(-self._EYE_W, 0, self._EYE_W, self.ROW_H)

        self.setMouseTracking(True)

    def set_colors(self, theme: dict | None):
        if not theme:
            return
        # Popup surface (chapter_dropdown-style: bg_deep + accent border) owns
        # the background; rows themselves stay transparent — same reasoning
        # as inline rows elsewhere in the app that sit on a themed surface
        # rather than carrying their own per-row card fill.
        title_color = theme.get('dropdown_text', theme.get('text', '#ffffff'))
        # Author rendered as the same hue at reduced opacity (not a different
        # color) — slightly darker than the title to create visual separation
        # without a separator glyph, while staying theme-agnostic.
        author_rgba = f"rgba({_hex_to_rgb(title_color)}, 0.65)"
        self.setStyleSheet(
            "QWidget#excluded_row { background-color: transparent; }"
            f"QLabel#excluded_row_title {{ color: {title_color}; font-size: 12px; }}"
            f"QLabel#excluded_row_author {{ color: {author_rgba}; font-size: 11px; }}"
        )
        self._overlay.setStyleSheet("QWidget#excluded_row_overlay { background-color: transparent; }")
        self._eye_btn.setStyleSheet("QToolButton { background: transparent; border: none; }")
        eye_color = theme.get('accent_light', '#cccccc')
        if eye_color != self._eye_color:
            self._eye_color = eye_color
            self._set_eye_icon(eye_color)
        self._apply_elide()

    def _set_eye_icon(self, color: str):
        icon_size = self.ROW_H - 8
        pixmap = load_currentcolor_icon("eye.svg", color, icon_size)
        self._eye_btn.setIcon(QIcon(pixmap))
        self._eye_btn.setIconSize(QSize(icon_size, icon_size))

    def _apply_elide(self):
        # The eye-width reservation now lives in hbox's left content margin
        # (see __init__), so this only needs the layout's own margins + the
        # inter-label spacing — not a separate _EYE_W subtraction on top.
        avail = self.width() - self._EYE_W - 10 - 6   # L margin (= eye width) + R margin + gap
        if avail <= 0:
            return
        fm = QFontMetrics(self._title_lbl.font())
        title_w = fm.horizontalAdvance(self._title)
        if title_w > avail:
            self._title_lbl.setText(fm.elidedText(self._title, Qt.TextElideMode.ElideRight, avail))
            self._author_lbl.setText("")
            return
        self._title_lbl.setText(self._title)
        author_avail = avail - title_w
        self._author_lbl.setText(
            fm.elidedText(self._author, Qt.TextElideMode.ElideRight, author_avail)
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._state == 'idle':
            self._overlay.move(-self._EYE_W, 0)
        elif self._state == 'hover':
            self._overlay.setGeometry(0, 0, self._EYE_W, self.ROW_H)
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
        """Animate overlay width by sliding its right edge; left edge stays
        pinned at the row's left (mirror of _HistoryRow._slide_overlay, which
        anchors to the row's right edge instead — see the left-vs-right note
        in __init__ for why this one is flipped)."""
        if self._anim and self._anim.state() == QPropertyAnimation.State.Running:
            self._anim.stop()
        start_geom = self._overlay.geometry()
        end_geom = QRect(0, 0, target_w, self.ROW_H) if target_w > 0 else QRect(-self._EYE_W, 0, self._EYE_W, self.ROW_H)
        sliding_in = target_w > 0
        self._anim = QPropertyAnimation(self._overlay, b"geometry", self)
        self._anim.setDuration(self._ANIM_MS)
        self._anim.setEasingCurve(
            QEasingCurve.Type.OutCubic if sliding_in else QEasingCurve.Type.InOutQuad
        )
        self._anim.setStartValue(start_geom)
        self._anim.setEndValue(end_geom)
        self._anim.start()


class ExcludedBooksPopup(QListWidget):
    """Popup list of excluded books, parented directly to MainWindow — same
    architecture as ChapterList (see module docstring for why). Opens via
    show_below(anchor_widget, window), closes via fade_out()."""

    restore_requested = Signal(str)  # emits book path; owner performs the DB write + refresh

    POPUP_W = 237      # narrower than the full window — matches the settings
                       # panel's own content width, not the whole 300px app
    POPUP_X = 17       # offset from the settings panel's left edge
    MAX_LIST_H = 75    # capped total popup height; scrolls beyond this
    FADE_IN_MS = 300
    FADE_OUT_MS = 250
    _BOTTOM_MARGIN = 20  # clearance kept below the popup, since it opens
                         # DOWNWARD (unlike ChapterList's _TOP_MARGIN, which
                         # reserves space above an UPWARD-opening list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Widget)
        self.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setObjectName("excluded_popup")
        self.setUniformItemSizes(True)
        self.hide()

        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity)

        self._anim = QPropertyAnimation(self._opacity, b"opacity")
        self._anim.setEasingCurve(QEasingCurve.InOutQuad)
        self._hide_connected = False

        self._theme: dict | None = None
        self._rows: dict[str, _ExcludedRow] = {}  # path -> row widget

    def set_theme(self, theme: dict):
        self._theme = theme
        bg_deep = theme.get('bg_deep', '#1a1a1a')
        accent = theme.get('accent', '#888888')
        # Scrollbar styling copied from chapter_dropdown's (ChapterList) QSS —
        # same popover surface pattern, same slim themed handle instead of
        # the default unthemed OS scrollbar.
        # Without an explicit ::item:selected rule, Qt falls back to a
        # system/default highlight color instead of a themed one — the same
        # rule chapter_dropdown defines, reusing the same dropdown_curr_chap
        # key for consistency between the two popover surfaces.
        sel_bg = theme.get('dropdown_curr_chap', accent)
        sel_text = theme.get('text', '#ffffff')
        self.setStyleSheet(
            f"QListWidget#excluded_popup {{ background-color: {bg_deep}; "
            f"border: 1px solid {accent}; outline: none; }}"
            f"QListWidget#excluded_popup::item:selected {{ "
            f"background-color: {sel_bg}; color: {sel_text}; }}"
            f"QListWidget#excluded_popup QScrollBar:vertical {{ width: 8px; "
            f"background: {bg_deep}; border: none; margin: 0px; }}"
            f"QListWidget#excluded_popup QScrollBar::handle:vertical {{ "
            f"background: {accent}; min-height: 20px; border-radius: 4px; }}"
            f"QListWidget#excluded_popup QScrollBar::add-line:vertical, "
            f"QListWidget#excluded_popup QScrollBar::sub-line:vertical {{ height: 0px; }}"
            f"QListWidget#excluded_popup QScrollBar::add-page:vertical, "
            f"QListWidget#excluded_popup QScrollBar::sub-page:vertical {{ background: none; }}"
        )
        for row in self._rows.values():
            row.set_colors(theme)

    def reload(self, books: list[tuple]):
        """Rebuild from a list of (path, title, author)."""
        self.clear()
        self._rows = {}
        for i, (path, title, author) in enumerate(books):
            self._add_row(path, title, author, i)

    def _add_row(self, path, title, author, index):
        row = _ExcludedRow(path, title, author, index)
        row.set_colors(self._theme)
        row.restore_requested.connect(self._on_row_restore)
        item = QListWidgetItem()
        item.setSizeHint(QSize(self.POPUP_W, _ExcludedRow.ROW_H))
        item.setData(Qt.UserRole, path)
        self.addItem(item)
        self.setItemWidget(item, row)
        self._rows[path] = row

    def _on_row_restore(self, path: str):
        # Fire the DB write/refresh immediately; animate the row out visually,
        # then remove it from the list once the collapse finishes.
        self.restore_requested.emit(path)
        row = self._rows.pop(path, None)
        if row is None:
            return

        def _remove():
            for i in range(self.count()):
                item = self.item(i)
                if item.data(Qt.UserRole) == path:
                    self.takeItem(i)
                    break
            if self.count() == 0:
                self.fade_out()

        anim = QPropertyAnimation(row, b"maximumHeight", row)
        anim.setDuration(_ExcludedRow._ANIM_MS)
        anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        anim.setStartValue(_ExcludedRow.ROW_H)
        anim.setEndValue(0)
        anim.finished.connect(_remove)
        anim.start()
        row._out_anim = anim  # keep ref

    def show_below(self, anchor_widget, window):
        """Position the popup inside the parent window, just below anchor_widget.
        Mirror of ChapterList.show_above — same fade-in mechanics, opposite
        anchor direction (downward, since this toggle sits mid-panel rather
        than pinned near the bottom of a fixed area)."""
        self.setFixedWidth(self.POPUP_W)

        self._opacity.setOpacity(0.0)
        self.show()

        anchor_local = anchor_widget.mapTo(window, anchor_widget.rect().bottomLeft())
        anchor_bottom_y = anchor_local.y()
        h_overhead = self.frameWidth() * 2
        available_px = min(self.MAX_LIST_H, window.height() - anchor_bottom_y - self._BOTTOM_MARGIN)
        rows = max(1, min(self.count(), (available_px - h_overhead) // _ExcludedRow.ROW_H))
        self.setFixedHeight(rows * _ExcludedRow.ROW_H + h_overhead)
        self.move(self.POPUP_X, anchor_bottom_y)
        self.raise_()
        QTimer.singleShot(0, self.setFocus)

        self._anim.stop()
        self._anim.setDuration(self.FADE_IN_MS)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(0.97)
        self._disconnect_hide()
        self._anim.start()

    def fade_out(self):
        self._anim.stop()
        self._anim.setDuration(self.FADE_OUT_MS)
        self._anim.setStartValue(self._opacity.opacity())
        self._anim.setEndValue(0.0)
        self._disconnect_hide()
        self._anim.finished.connect(self._on_fade_out_finished)
        self._hide_connected = True
        self._anim.start()

    def dismiss_immediately(self):
        """Hide with no fade at all. Used when the popup's anchor is about to
        move out from under it (the settings panel sliding closed, or a click
        outside it while the panel itself is closing) — a fade can't keep up
        with that motion and would visibly lag/detach from the toggle line it
        was anchored to. fade_out() is for a deliberate, standalone close
        (clicking the toggle again) where the panel itself isn't moving."""
        self._anim.stop()
        self._disconnect_hide()
        self.hide()

    def _on_fade_out_finished(self):
        self.hide()

    def _disconnect_hide(self):
        if self._hide_connected:
            self._anim.finished.disconnect(self._on_fade_out_finished)
            self._hide_connected = False


class ExcludedBooksSection(QWidget):
    """Toggle line ("N books excluded ▼") for the Library settings tab.
    Invisible (zero height, hidden) when no books are excluded. Clicking it
    opens/closes an ExcludedBooksPopup parented to MainWindow (set via
    set_popup_anchor) rather than expanding anything inline — see module
    docstring for why."""

    toggle_requested = Signal()  # owner opens/closes the popup, anchored to this widget

    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme: dict | None = None
        self._count = 0
        self._expanded = False

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._header = QLabel("Excluded books")
        self._header.setObjectName("settings_header")
        outer.addWidget(self._header)
        outer.addStretch()

        # Pure state indicator — visible only while the popup is open, shows
        # "▲" only (there's nothing to show when hidden, so no "▼" state is
        # ever needed). NOT a click target: no cursor, no mousePressEvent.
        # Mirrors ChapterList's _expand_btn in spirit (visible only when
        # relevant) but unlike it, has no click handler of its own at all —
        # the "N books excluded" label below is the only way to toggle the
        # popup. Do not add one "for consistency"; that would create a second
        # way to open/close the popup that doesn't match the design.
        self._arrow = QLabel("")
        self._arrow.setObjectName("excluded_toggle_arrow")
        self._arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._arrow.setContentsMargins(0, 7, 0, 0)
        # Same fixed-height pin as the count label below, same reasoning:
        # don't let this widget's own sizeHint (which can fluctuate with its
        # text content) influence the row's height.
        self._arrow.setFixedHeight(self._header.sizeHint().height())
        self._arrow.setVisible(False)
        outer.addWidget(self._arrow)
        outer.addStretch()

        self._toggle = QLabel("")
        self._toggle.setObjectName("excluded_toggle")
        self._toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle.mousePressEvent = self._on_toggle_clicked
        self._toggle.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        # Nudged down 5px — the header has its own `margin-top: 10px` (QSS
        # settings_header rule) baked into its sizeHint, so simply centering
        # the toggle within that same box reads visibly too high relative to
        # the header's actual (lower, margin-shifted) glyph position.
        self._toggle.setContentsMargins(0, 7, 0, 0)
        # Fixed height pinned to the header's own sizeHint — see the
        # commit history for why: rich text with an inline
        # <span style="font-size:..."> can report a different sizeHint()
        # between "▼" and "▲" content even at the same nominal size, and
        # since this label shares a row with the header, that fluctuation
        # used to ripple into the header row's height.
        self._toggle.setFixedHeight(self._header.sizeHint().height())
        outer.addWidget(self._toggle)

    def set_theme(self, theme: dict):
        self._theme = theme
        self._apply_toggle_text()

    def set_count(self, count: int):
        """Called by the owner after the popup's reload() — drives visibility
        and the toggle label. count == 0 hides this widget entirely (zero
        space allocated), matching the original "invisible when empty" rule."""
        self._count = count
        self.setVisible(count > 0)
        self._apply_toggle_text()

    def set_expanded(self, expanded: bool):
        """Called by the owner once the popup has actually opened/closed, so
        the arrow reflects real popup state rather than assuming the toggle
        click always succeeds."""
        self._expanded = expanded
        self._arrow.setVisible(expanded)
        self._apply_toggle_text()

    def _on_toggle_clicked(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self.toggle_requested.emit()

    def _apply_toggle_text(self):
        plural = "book" if self._count == 1 else "books"
        color = (self._theme or {}).get('text', '#ffffff')
        self._toggle.setText(
            f'<span style="color:{color}; font-size:13px;">{self._count} {plural} excluded</span>'
        )
        if self._expanded:
            self._arrow.setText(f'<span style="color:{color}; font-size:13px;">▲</span>')
