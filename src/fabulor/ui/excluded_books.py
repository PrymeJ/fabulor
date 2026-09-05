"""Excluded Books list for the Library settings tab.

Lists books the user has trashed (is_excluded=1, is_deleted=0) and lets them be
restored. ExcludedBooksList is ALWAYS VISIBLE (not click-to-open) whenever
there's at least one excluded book — a permanent fixture under the "Excluded
books" header, not a popup. It's parented directly to library_tab (the
Library settings tab's own page widget, not MainWindow — see app.py) and
positioned/sized directly (move(), show(), raise_()), the same overlay
architecture as ChapterList (chapter_list.py): that's load-bearing, not
incidental — an earlier attempt to make this a normal widget living inside the
settings tab's QVBoxLayout, animated open/closed, hit an unfixable rendering
wall (confirmed independently twice; see NOTES.md 2026-06-27). Even though
this no longer animates open/closed, it stays a tab-level overlay rather than
a normal layout member for the same reason — a fixed-size jump between 3 and
6 rows still resizes the widget, and the proven-safe path is to keep doing
that outside the tab's layout rather than risk the same failure mode again.
It sits flush BELOW the "Excluded books" row as the topmost element, growing
downward and covering whatever else is there when expanded — same visual
relationship ChapterList has with content below it.

Default view shows up to DEFAULT_VISIBLE_ROWS (3); the arrow (on
ExcludedBooksSection, a separate widget — see its docstring) expands the
visible window up to MAX_EXPANDED_ROWS (6) when there are more books than the
default shows. The arrow is a real toggle now (click target moved off the
count label — see ExcludedBooksSection) and is dimmed/inert when there's
nothing to expand (count <= DEFAULT_VISIBLE_ROWS). Clicking outside the list
while expanded collapses it back to the default — it does NOT hide the list
entirely (there's no "closed" state anymore, only collapsed/expanded).

The per-row restore affordance copies _HistoryRow's hover-reveal slide
animation exactly (same _ANIM_MS / OutCubic-in / InOutQuad-out, same
off-screen-right child overlay), substituting eye.svg for the X icon.
Restore is immediate and silent — no confirm panel.
"""
from PySide6.QtCore import Qt, Signal, QPropertyAnimation, QEasingCurve, QRect, QSize
from PySide6.QtGui import QIcon, QFontMetrics
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QToolButton, QListWidget, QListWidgetItem,
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

    def __init__(self, path: str, title: str, author: str, index: int, parent=None,
                 owner: "ExcludedBooksPopup | None" = None):
        super().__init__(parent)
        self._path = path
        self._row_index = index
        self._owner = owner  # the ExcludedBooksPopup this row belongs to — used only to
            # coordinate mouse-vs-keyboard "last one wins" (see enterEvent/leaveEvent below).
            # NOT Qt parenting (this widget is parented into the list later via setItemWidget,
            # independent of this reference).
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
        # QToolButton defaults to TabFocus (a documented Qt gotcha — see CLAUDE.md's "Keyboard
        # focus ownership" consequence 2). Without this override, EVERY row's eye button — most
        # of them invisible off-screen at any given time, only revealed on hover — became its
        # own individual Tab stop (reported live 2026-09-05: "Tab goes to invisible eyes"), and
        # each one was also a fresh, unexcluded target for the traveling focus marker (it has no
        # entry in focus_marker.py's _FILL_FOCUS_OBJECT_NAMES, so it traced normally — this is
        # what the earlier "marker inside the popup" screenshot actually was, not a residual bug
        # in that fix). ExcludedBooksPopup itself is the sole intended Tab stop for this whole
        # list (see its own keyPressEvent for Space/Enter reaching the same restore action).
        self._eye_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
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
        # Mouse and keyboard drive the SAME reveal on potentially DIFFERENT rows independently
        # (the keyboard's own reveal lives in ExcludedBooksPopup._kbdnav_row_widget) — without
        # this notification, hovering row A with the mouse while the keyboard cursor sits on row
        # B left BOTH rows visibly revealed at once, since set_hovered's own idempotency guard
        # only protects a single row against itself, not two rows against each other (reported
        # live 2026-09-05: "the mouse/keyboard last to win logic is required here too as in
        # other places" — same shape as library.py's _on_view_entered yielding the keyboard
        # highlight to a real mouse hover). The mouse arriving always wins immediately.
        if self._owner is not None:
            self._owner.on_mouse_hover_row(self)
        self.set_hovered(True)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        if self._owner is not None:
            self._owner.on_mouse_leave_row(self)
        self.set_hovered(False)

    def set_hovered(self, hovered: bool) -> None:
        """Same reveal/retract the real mouse enterEvent/leaveEvent drive, callable directly —
        the keyboard-cursor path (ExcludedBooksPopup.keyPressEvent) has no real QEvent to send,
        since arrowing to a row never moves the actual cursor. The eye slide IS the keyboard
        cursor indicator here (no separate marker/fill/dot — a live design decision 2026-09-05:
        this list already has a per-row affordance that means exactly "you are here," so a
        second one would be redundant chrome)."""
        if hovered and self._state == 'idle':
            self._state = 'hover'
            self._slide_overlay(self._EYE_W)
        elif not hovered and self._state == 'hover':
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
    """Always-visible list of excluded books, parented directly to
    library_tab — same overlay architecture as ChapterList (see module
    docstring for why). Shown whenever there's at least one excluded book;
    sized to DEFAULT_VISIBLE_ROWS by default, expandable up to
    MAX_EXPANDED_ROWS via set_expanded(True). Sits flush below its anchor
    (the "Excluded books" row) and grows downward, covering whatever else
    is in the tab below it."""

    restore_requested = Signal(str)  # emits book path; owner performs the DB write + refresh
    expand_toggle_requested = Signal()  # keyboard Left/Right — owner mirrors
        # ExcludedBooksSection.toggle_requested's handler (app.py's
        # _on_excluded_toggle_clicked) exactly, since it also has to update the
        # OTHER widget (the arrow glyph on ExcludedBooksSection) that this class
        # has no reference to.
    exit_upward_requested = Signal()  # keyboard Up at row 0 — owner moves focus to whatever
        # sits above this box (Persist search filter's row). NOT implemented via
        # event.ignore()-then-bubble: this widget is several parents deep
        # (library_tab -> tabs -> settings_panel -> MainWindow) inside an
        # app-wide eventFilter-driven navigation scheme, and relying on Qt's
        # native unhandled-key propagation to reach the right ancestor is far
        # less certain than a direct signal to the one class (MainWindow) that
        # actually owns "what sits above this row" via settings_tab_button_rows().

    POPUP_W = 240      # narrower than the full window — matches the settings
                       # panel's own content width, not the whole 300px app
    POPUP_X = 10       # offset from the settings panel's left edge
    DEFAULT_VISIBLE_ROWS = 3  # default (collapsed) row count
    MAX_EXPANDED_ROWS = 7     # cap when expanded via the arrow
    ANCHOR_Y_NUDGE = 2  # shifts the list (and the arrow, in lockstep — see
                        # ExcludedBooksSection._reposition_arrow) 2px up from
                        # the literal flush-below-the-row position, by user
                        # visual preference (photo-edited mockup comparison)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Widget)
        self.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setObjectName("excluded_popup")
        self.setUniformItemSizes(True)
        # No row selection — clicking a row does nothing here (the eye button
        # is the only per-row action), so a persistent highlight just adds
        # visual noise with no purpose.
        self.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.hide()

        self._expanded = False
        self._theme: dict | None = None
        self._rows: dict[str, _ExcludedRow] = {}  # path -> row widget
        self._anchor_bottom: int | None = None  # fixed BOTTOM y of the list at
            # its DEFAULT (3-row) height, in window coords — this never moves;
            # expanding to 6 rows only moves the TOP edge upward, same as
            # ChapterList anchoring its bottom and growing up.
        # Tracked independently of self.count() (the live QListWidget item
        # count), which is stale-by-one immediately after a restore — the
        # restored row isn't actually removed from the widget until its
        # slide-out animation finishes (see _on_row_restore). _book_count is
        # decremented immediately, in lockstep with the DB write, so
        # is_expandable reflects the true count right away.
        self._book_count = 0

        self._kbdnav_row_widget: "_ExcludedRow | None" = None  # the _ExcludedRow this widget
            # itself last revealed via the keyboard — see _on_current_row_changed. Tracked by
            # WIDGET, not row index: a restore removes the current row via takeItem, which
            # shifts every later row up one index and fires currentRowChanged again pointing at
            # whatever widget now OCCUPIES the old index — retracting by index there would
            # incorrectly un-reveal a row the keyboard never actually touched. Tracking the
            # widget itself also makes on_mouse_hover_row's own retract-if-different check exact
            # (identity, not index) when the mouse takes over mid-navigation — see that method.
        self._mouse_hovered_row_widget: "_ExcludedRow | None" = None  # the _ExcludedRow a real
            # mouse enterEvent last reported — see on_mouse_hover_row/on_mouse_leave_row and
            # _on_current_row_changed's own retract-the-other-side check.
        # Drives the keyboard-cursor indicator (the eye reveal itself — see
        # _ExcludedRow.set_hovered's docstring for why there's no separate marker/fill/dot).
        # currentRowChanged fires for BOTH the keyboard's own native Up/Down (see keyPressEvent)
        # and any other path that moves currentRow() (including a restore's takeItem, above) —
        # using it rather than hand-rolling a before/after comparison in keyPressEvent means a
        # boundary-clamped move (Qt declining to go past row 0/last row, where currentRow()
        # doesn't actually change) is naturally a no-op here too, since Qt only emits this
        # signal when the row genuinely changed.
        self.currentRowChanged.connect(self._on_current_row_changed)

    def on_mouse_hover_row(self, row: "_ExcludedRow") -> None:
        """Called by _ExcludedRow.enterEvent on every genuine mouse hover — the mouse arriving
        always wins immediately over whatever the keyboard was showing, mirroring library.py's
        _on_view_entered yielding a keyboard highlight to a real mouse hover. Without this, the
        keyboard cursor and the mouse could independently reveal two DIFFERENT rows' eyes at
        once, since _ExcludedRow.set_hovered's own idempotency guard only protects a single row
        against itself, never coordinates across rows (reported live 2026-09-05)."""
        if self._kbdnav_row_widget is not None and self._kbdnav_row_widget is not row:
            self._kbdnav_row_widget.set_hovered(False)
            self._kbdnav_row_widget = None
        self._mouse_hovered_row_widget = row

    def on_mouse_leave_row(self, row: "_ExcludedRow") -> None:
        """Called by _ExcludedRow.leaveEvent — clears the mouse-hover tracking used by
        _on_current_row_changed's own retract-the-other-side check below. Guarded on identity
        (only clear if THIS row is the one currently tracked) since a fast pointer move can
        deliver a new row's enterEvent before the old row's leaveEvent, and the stale leaveEvent
        must not clobber the newer row's already-current tracking."""
        if self._mouse_hovered_row_widget is row:
            self._mouse_hovered_row_widget = None

    def _on_current_row_changed(self, row: int) -> None:
        if self._kbdnav_row_widget is not None:
            self._kbdnav_row_widget.set_hovered(False)
            self._kbdnav_row_widget = None
        # The reverse direction of on_mouse_hover_row's guard: the keyboard cursor moving must
        # ALSO yield over whatever the mouse is independently showing, or the same two-rows-open
        # bug reopens from this side (mouse resting on row X, keyboard cursor arrives on row Y —
        # no real leaveEvent ever fires for X since the cursor never physically moved, so X's
        # reveal would otherwise persist unnoticed). The keyboard arriving here also wins
        # immediately, matching the framing of "last one wins" from whichever side moved last.
        if self._mouse_hovered_row_widget is not None:
            self._mouse_hovered_row_widget.set_hovered(False)
            self._mouse_hovered_row_widget = None
        if row < 0:
            return
        item = self.item(row)
        if item is None:
            return
        new_row = self.itemWidget(item)
        if isinstance(new_row, _ExcludedRow):
            new_row.set_hovered(True)
            self._kbdnav_row_widget = new_row

    @property
    def book_count(self) -> int:
        """True excluded-book count — NOT self.count() (the live QListWidget
        item count), which is stale-by-one immediately after a restore. See
        _book_count's docstring in __init__."""
        return self._book_count

    @property
    def is_expandable(self) -> bool:
        """True when there are more books than the default view shows — the
        arrow has something to do. Used by ExcludedBooksSection to decide
        whether the arrow is a live control or a dimmed no-op."""
        return self._book_count > self.DEFAULT_VISIBLE_ROWS

    @property
    def is_expanded(self) -> bool:
        return self._expanded

    def set_theme(self, theme: dict):
        self._theme = theme
        bg_deep = theme.get('bg_deep', '#1a1a1a')
        accent = theme.get('accent', '#888888')
        # Scrollbar styling copied from chapter_dropdown's (ChapterList) QSS —
        # same popover surface pattern, same slim themed handle instead of
        # the default unthemed OS scrollbar. No ::item:selected rule needed —
        # selection is disabled entirely (NoSelection, see __init__): clicking
        # a row does nothing here, the eye button is the only per-row action.
        self.setStyleSheet(
            f"QListWidget#excluded_popup {{ background-color: {bg_deep}; "
            f"border: 1px solid {accent}; outline: none; }}"
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
        self._book_count = len(books)
        for i, (path, title, author) in enumerate(books):
            self._add_row(path, title, author, i)

    def _add_row(self, path, title, author, index):
        row = _ExcludedRow(path, title, author, index, owner=self)
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
        # _book_count drops immediately (in lockstep with the DB write the
        # restore_requested handler performs), NOT after the animation —
        # is_expandable and reposition() must reflect the true count right
        # away, since app.py's restore handler reads them synchronously.
        self._book_count = max(0, self._book_count - 1)
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
            # If the count dropped to/below the default, an expanded view has
            # nothing left to show beyond the default — collapse it rather
            # than leave it expanded-but-pointless. The owner (app.py) is
            # responsible for hiding this widget entirely if count hits 0.
            # (app.py's restore handler already does this immediately via
            # set_expanded(False)/reposition(); this is a no-op in that case
            # and only matters if some other caller skips that step.)
            if not self.is_expandable and self._expanded:
                self.set_expanded(False)

        anim = QPropertyAnimation(row, b"maximumHeight", row)
        anim.setDuration(_ExcludedRow._ANIM_MS)
        anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        anim.setStartValue(_ExcludedRow.ROW_H)
        anim.setEndValue(0)
        anim.finished.connect(_remove)
        anim.start()
        row._out_anim = anim  # keep ref

    def focusInEvent(self, event):
        # Entering the box ALWAYS lands on the FIRST row, regardless of arrival direction or
        # whatever row a previous visit left currentRow() sitting on — unlike folder_list_widget
        # (which lands on the LAST row when arriving from below), this box has no "from below"
        # arrival path: it only has neighbors ABOVE it (Persist search filter's row) and nothing
        # below it in the tab, so there is only ever one direction to land from, and every
        # re-entry should restart at the top rather than resuming a stale scroll position.
        #
        # Qt's own QAbstractItemView.focusInEvent sets currentRow() to 0 itself, but ONLY when
        # nothing was current yet (confirmed via direct isolated call: fires currentRowChanged(0)
        # once from -1, but does nothing when currentRow() is already >= 0 from a prior visit —
        # e.g. row 2 after the user arrowed down last time it was open). So super() alone
        # correctly handles first-ever-entry, but silently does NOT reset a later re-entry back
        # to row 0 — confirmed the hard way: an earlier version of this method left re-entry
        # sitting wherever the previous visit's cursor was, with no eye revealed at all (the
        # retract on the way out, in focusOutEvent, cleared _kbdnav_row_widget without moving
        # currentRow() itself, and currentRowChange never re-fires for an unchanged row). Fixed
        # by explicitly forcing row 0 on every entry when it isn't already there.
        super().focusInEvent(event)
        if not self.count():
            return
        if self.currentRow() != 0:
            self.setCurrentRow(0)  # fires currentRowChanged -> _on_current_row_changed
        elif self._kbdnav_row_widget is None:
            # Already row 0 (either super() just set it, or a prior visit left it there) but
            # nothing is currently tracked as revealed — reveal it. Guarded on
            # _kbdnav_row_widget being None so this never double-fires when super() already
            # triggered the reveal via a genuine currentRowChanged this same call.
            self._on_current_row_changed(0)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        # Leaving the box (Tab away, or Up at row 0 below) must retract whatever eye the
        # keyboard revealed — currentRow() itself is left alone (Qt's own focus-out behavior),
        # only the visual reveal needs undoing.
        if self._kbdnav_row_widget is not None:
            self._kbdnav_row_widget.set_hovered(False)
            self._kbdnav_row_widget = None

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            row = self.currentRow()
            at_top = row <= 0
            at_bottom = row == self.count() - 1
            if (key == Qt.Key.Key_Up and at_top) or (key == Qt.Key.Key_Down and at_bottom):
                # Genuinely at an end. Down at the bottom has nowhere to go (nothing below this
                # box in the Library tab, same as a plain grid row's own "last row: swallow"
                # rule) — consume it.
                #
                # Up at the top always leaves the box for whatever sits above it (Persist search
                # filter's row) — the owner's exit_upward_requested handler collapses the popup
                # FIRST if it's expanded (see app.py's _on_excluded_books_exit_upward), so the
                # exited-to focus and the box's own footprint never overlap. A no-op-while-
                # expanded variant was tried first and rejected live (2026-09-05): the user's own
                # framing was "go to Persist search filter row AND collapse the list," i.e. exit
                # always succeeds, collapsing is a side effect of leaving — not "you must
                # collapse before you may leave." See exit_upward_requested's own docstring for
                # why this is a signal rather than event.ignore().
                if key == Qt.Key.Key_Up:
                    self.exit_upward_requested.emit()
                return
            # Native Qt cursor movement — scrolls the viewport as needed (including past
            # MAX_EXPANDED_ROWS when there are more than 7 excluded books, same as a mouse drag
            # on the scrollbar would), and fires currentRowChanged, which drives the eye
            # reveal/retract (see _on_current_row_changed). No selection side effect: this list
            # is NoSelection (see __init__), so there is no ExtendedSelection-style
            # setCurrentRow-clobbers-selection trap here.
            super().keyPressEvent(event)
            return
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            # Expand/collapse — mirrors ChapterList's own Left/Right convention exactly (either
            # key does the same toggle; see chapter_list.py's keyPressEvent). Live design
            # decision 2026-09-05: scrolling (Up/Down, above) already reaches every excluded
            # book regardless of expand state, so expand/collapse stays a deliberate, separate
            # action rather than something Down auto-triggers at a visible-row boundary.
            if self.is_expandable:
                self.expand_toggle_requested.emit()
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            row = self.currentRow()
            if row >= 0:
                item = self.item(row)
                if item is not None:
                    path = item.data(Qt.UserRole)
                    if path is not None:
                        self._on_row_restore(path)
            return
        super().keyPressEvent(event)

    def set_expanded(self, expanded: bool):
        """Toggle between DEFAULT_VISIBLE_ROWS and min(count, MAX_EXPANDED_ROWS).
        A plain, instant setFixedHeight jump — NOT an animated transition.
        Animating this widget's height inside this fixed-overlay model is
        exactly the thing that worked fine for ChapterList (a real QWidget,
        not laid out by anything) and is safe here for the same reason: it's
        an overlay nobody else's layout reacts to, so a resize can't trigger
        the QVBoxLayout-fighting failure mode that ruled out the earlier
        animated-inline-widget approach."""
        self._expanded = expanded and self.is_expandable
        self._resize_to_row_count()
        self._reposition_vertically()
        # Collapsing shrinks the visible window back to DEFAULT_VISIBLE_ROWS (3) without moving
        # the keyboard cursor — if it was sitting on row 4+ (only reachable while expanded), it
        # is now scrolled out of view entirely while still being the row Space/Enter would act
        # on (reported live 2026-09-05). Scroll it back into view rather than relocating the
        # cursor to row 0: the user's actual keyboard position should never silently change
        # just because the box visually shrank around it — same principle as every other cursor
        # move in this app leaving selection/position alone unless the user explicitly acted.
        # A no-op when already visible or when nothing is current (currentRow() == -1).
        if not self._expanded:
            row = self.currentRow()
            if row >= 0:
                item = self.item(row)
                if item is not None:
                    self.scrollToItem(item, QListWidget.ScrollHint.EnsureVisible)

    def _resize_to_row_count(self):
        # Fixed at exactly two sizes — DEFAULT_VISIBLE_ROWS (3) collapsed,
        # MAX_EXPANDED_ROWS (7) expanded — regardless of the actual book
        # count, as long as there's at least 1 (count==0 hides entirely,
        # handled by callers). NOT a shrink-to-fit: 1 or 2 excluded books
        # still get the full 3-row collapsed height, just with empty rows
        # below; this also keeps the arrow's lift distance constant.
        rows = self.MAX_EXPANDED_ROWS if self._expanded else self.DEFAULT_VISIBLE_ROWS
        h_overhead = self.frameWidth() * 2
        self.setFixedHeight(rows * _ExcludedRow.ROW_H + h_overhead)

    def _reposition_vertically(self):
        """Bottom-anchored to _anchor_bottom — flush under "Excluded books"
        at the DEFAULT (3-row) height. That bottom edge never moves;
        expanding to 6 rows only moves the TOP edge upward, covering
        whatever else is there as the topmost element (same as ChapterList
        anchoring its bottom and growing up)."""
        if self._anchor_bottom is None:
            return
        self.move(self.POPUP_X, self._anchor_bottom - self.height())

    def reposition(self, anchor_widget, window):
        """Position this list inside the parent window, anchored flush BELOW
        anchor_widget's bottom edge at the list's DEFAULT height, expanding
        UPWARD from that fixed bottom edge when shown with more rows (same
        as ChapterList), and show/hide it based on whether there are any
        excluded books at all. Call after reload() and whenever the
        anchor's position might have changed (e.g. theme/layout changes).

        Uses self._book_count, NOT self.count() (the live QListWidget item
        count) — self.count() is stale-by-one immediately after a restore,
        since the just-restored row isn't removed from the widget until its
        slide-out animation finishes (see _on_row_restore). _book_count is
        decremented immediately in lockstep with the DB write instead."""
        if self._book_count == 0:
            self.hide()
            return

        self.setFixedWidth(self.POPUP_W)

        anchor_local = anchor_widget.mapTo(window, anchor_widget.rect().topLeft())
        anchor_top = anchor_local.y()
        h_overhead = self.frameWidth() * 2
        default_height = self.DEFAULT_VISIBLE_ROWS * _ExcludedRow.ROW_H + h_overhead
        self._anchor_bottom = anchor_top + anchor_widget.height() + default_height - self.ANCHOR_Y_NUDGE

        self._resize_to_row_count()
        self._reposition_vertically()
        self.show()
        self.raise_()

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

    # Emitted only when the arrow is a live control (is_expandable) and gets
    # clicked — the owner toggles ExcludedBooksPopup.set_expanded in response.
    toggle_requested = Signal()

    ARROW_W = 26    # must match self._arrow.setFixedSize(...)'s width
    ARROW_GAP = 2  # breathing room between the count label and the arrow

    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme: dict | None = None
        self._count = 0
        self._expanded = False
        self._expandable = False  # True when count > popup.DEFAULT_VISIBLE_ROWS

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._header = QLabel("Excluded books")
        self._header.setObjectName("settings_header")
        outer.addWidget(self._header)
        outer.addStretch()

        # "N books excluded" is plain, non-interactive text now — the arrow
        # is the only click target (see below). No cursor, no
        # mousePressEvent: this used to be the toggle itself, before the list
        # became always-visible instead of click-to-open.
        self._toggle = QLabel("")
        self._toggle.setObjectName("excluded_toggle")
        self._toggle.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        # Nudged down 5px — the header has its own `margin-top: 10px` (QSS
        # settings_header rule) baked into its sizeHint, so simply centering
        # the toggle within that same box reads visibly too high relative to
        # the header's actual (lower, margin-shifted) glyph position.
        self._toggle.setContentsMargins(0, 9, 0, 0)
        # Fixed height pinned to the header's own sizeHint — see the
        # commit history for why: rich text with an inline
        # <span style="font-size:..."> can report a different sizeHint()
        # between "▼" and "▲" content even at the same nominal size, and
        # since this label shares a row with the header, that fluctuation
        # used to ripple into the header row's height.
        self._toggle.setFixedHeight(self._header.sizeHint().height())
        outer.addWidget(self._toggle)

        # Fixed-width spacer reserving room for the arrow, which sits
        # absolutely positioned (NOT a layout member — see below) flush
        # against the row's right edge. Without this, the count label
        # (right-aligned, addStretch() before it) would render flush against
        # the row's right edge too and the arrow would overlap its text.
        # ARROW_W must match self._arrow.setFixedSize(...)'s width exactly;
        # ARROW_GAP (10px) is the breathing room between the count label's
        # new right edge and the arrow's left edge.
        outer.addSpacing(self.ARROW_W + self.ARROW_GAP)

        # The real toggle now — always visible whenever the section itself
        # is (count > 0), showing ▼ (collapsed) or ▲ (expanded). Dimmed and
        # inert (no cursor, no-op click) when there's nothing to expand
        # (count <= ExcludedBooksPopup.DEFAULT_VISIBLE_ROWS) — see
        # set_expandable(). Do not give it a click handler that always
        # toggles regardless of _expandable; an inert click must be a true
        # no-op, not a state change with no visible effect.
        #
        # The arrow QLabel itself is NOT a child of this widget — see
        # set_arrow_parent(). ExcludedBooksSection has no fixed height (the
        # Library tab's layout stretches it to fill leftover space), and
        # the arrow needs to travel well above this row's own bounds when
        # the list expands (up to 4 extra rows × 24px). A child positioned
        # above its parent's (0,0) gets silently clipped and never paints —
        # that's why an earlier version of this arrow (parented to self)
        # never visibly moved despite move() being called correctly. The
        # arrow is instead parented to library_tab (the same parent as
        # ExcludedBooksPopup itself), in that same absolute coordinate
        # space, and owned/positioned by this class via set_arrow_parent().
        self._arrow: QLabel | None = None

    def set_arrow_parent(self, library_tab):
        """Creates the arrow QLabel as a child of library_tab (NOT self —
        see __init__) so it can move freely above this row without being
        clipped. Must be called once, after both this section and
        library_tab exist (see app.py construction order)."""
        self._arrow = QLabel("▲", library_tab)  # collapsed default — see _apply_toggle_text
        self._arrow.setObjectName("excluded_toggle_arrow")
        self._arrow.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._arrow.setFixedSize(self.ARROW_W, 11)
        self._arrow.mousePressEvent = self._on_arrow_clicked
        self._reposition_arrow()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reposition_arrow()

    def _reposition_arrow(self):
        """Flush against the TOGGLE ROW's bottom-right corner — flush right
        against the row's right edge (zero margin), with the count label
        (right-aligned, via the ARROW_W+ARROW_GAP spacer reserved in
        __init__'s layout) sitting to its left with ARROW_GAP px of
        breathing room. Computed in library_tab's coordinate space (mapTo)
        since the arrow is parented there, not to self — see
        set_arrow_parent().

        The list (ExcludedBooksPopup) grows UPWARD from a fixed bottom edge
        when expanded — its top edge rises by (extra rows × ROW_H). The
        arrow sits flush on that top edge, so it must rise by the same
        amount when expanded, or it gets left behind at the collapsed
        position while the box grows up past it."""
        if self._arrow is None:
            return
        library_tab = self._arrow.parentWidget()
        if library_tab is None:
            return
        row_h = self._header.sizeHint().height()
        self_topleft = self.mapTo(library_tab, self.rect().topLeft())
        x = self_topleft.x() + self.width() - self._arrow.width()
        lift = 0
        if self._expanded:
            # Expanded height is always exactly MAX_EXPANDED_ROWS (fixed,
            # regardless of book count — see _resize_to_row_count), so the
            # lift distance is fixed too.
            default_rows = min(self._count, ExcludedBooksPopup.DEFAULT_VISIBLE_ROWS)
            lift = max(0, ExcludedBooksPopup.MAX_EXPANDED_ROWS - default_rows) * _ExcludedRow.ROW_H
        # ANCHOR_Y_NUDGE keeps the arrow flush with the list's top edge,
        # which is shifted up by the same amount — see reposition()'s
        # _anchor_bottom calculation.
        self._arrow.move(x, self_topleft.y() + row_h - self._arrow.height() - lift - ExcludedBooksPopup.ANCHOR_Y_NUDGE)
        self._arrow.raise_()

    def set_theme(self, theme: dict):
        self._theme = theme
        self._apply_arrow_style()
        self._apply_toggle_text()

    def _apply_arrow_style(self):
        # Filled block, same color pair chapter_expand_btn uses (themes.py),
        # so the arrow reads as one attached unit with the count label rather
        # than a separate floating glyph. Dimmed (accent_dark/text at reduced
        # opacity, via a flat lower-saturation fallback) and inert when
        # there's nothing to expand — same "exists but greyed out" treatment
        # other settings buttons use for an unavailable action, rather than
        # disappearing (which would look like a missing element).
        if self._arrow is None:
            return
        theme = self._theme or {}
        if self._expandable:
            bg = theme.get('dropdown_expand', theme.get('accent', '#888888'))
            text = theme.get('dropdown_text', theme.get('text', '#ffffff'))
            self._arrow.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            bg = theme.get('bg_deep', '#333333')
            text = theme.get('accent_dark', theme.get('text', '#888888'))
            self._arrow.setCursor(Qt.CursorShape.ArrowCursor)
        self._arrow.setStyleSheet(
            f"QLabel#excluded_toggle_arrow {{ background-color: {bg}; color: {text}; "
            f"font-size: 10px; border: none; }}"
        )

    def set_count(self, count: int):
        """Called by the owner after the popup's reload() — drives visibility
        and the toggle label. count == 0 hides this widget entirely (zero
        space allocated), matching the original "invisible when empty" rule."""
        self._count = count
        self.setVisible(count > 0)
        # The arrow is no longer a child of self (see set_arrow_parent) so
        # hiding self does NOT hide it for free — must be driven explicitly.
        if self._arrow is not None:
            self._arrow.setVisible(count > 0)
        self._apply_toggle_text()
        self._reposition_arrow()

    def set_expandable(self, expandable: bool):
        """Called by the owner whenever the count changes — drives the
        arrow's dimmed/inert vs. live appearance. Independent of set_count
        because the threshold lives on ExcludedBooksPopup
        (DEFAULT_VISIBLE_ROWS), not here."""
        self._expandable = expandable
        if not expandable:
            self._expanded = False
        self._apply_arrow_style()
        self._apply_toggle_text()
        # If count dropped to <= DEFAULT_VISIBLE_ROWS while expanded (e.g.
        # restoring a book down to exactly 3 left), _expanded just flipped
        # to False above — the arrow must drop back to its flush/collapsed
        # position, not stay lifted at the old expanded height.
        self._reposition_arrow()

    def set_expanded(self, expanded: bool):
        """Called by the owner once the list has actually expanded/collapsed,
        so the arrow glyph reflects real state rather than assuming the click
        always succeeds. The list grows UPWARD from a fixed bottom edge, so
        the arrow (which sits flush on the list's TOP edge) must move up
        with it — see _reposition_arrow."""
        self._expanded = expanded
        self._apply_toggle_text()
        self._reposition_arrow()

    def _on_arrow_clicked(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if not self._expandable:
            return  # true no-op — dimmed/inert state, not a state change
        self.toggle_requested.emit()

    def _apply_toggle_text(self):
        if self._arrow is None:
            return
        plural = "book" if self._count == 1 else "books"
        color = (self._theme or {}).get('text', '#ffffff')
        self._toggle.setText(
            f'<span style="color:{color}; font-size:11px;">{self._count} {plural} excluded</span>'
        )
        # Plain text — color comes from the stylesheet block in
        # _apply_arrow_style(), not an inline span (which would fight the
        # filled background's own text-color rule).
        #
        # Matches ChapterList._toggle_expand's exact convention: the glyph
        # shows the DIRECTION the next click will move things, not the
        # current state directly. This list grows UPWARD when expanded (same
        # as ChapterList's dropdown), so: ▲ collapsed (there's more above,
        # click to reveal it upward), ▼ expanded (click to collapse back
        # down). This is the opposite of "▲ when expanded" — verified against
        # chapter_list.py:207 (`"▼" if self._expanded else "▲"`) directly,
        # not assumed.
        self._arrow.setText("▼" if self._expanded else "▲")
