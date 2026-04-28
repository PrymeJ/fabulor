import os
import time
import random
from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QGridLayout, QFrame, QPushButton, QHBoxLayout, QComboBox, QLineEdit, QProgressBar, QStyledItemDelegate, QListView,
)
from PySide6.QtCore import QThreadPool, QEvent, QAbstractListModel, QModelIndex, QSize, QTimer, QDateTime
from PySide6.QtCore import Qt, Signal, QCoreApplication, QRect, QPoint
from typing import Optional
from ..models.book import Book
from PySide6.QtGui import QPixmap, QColor, QFont

# View mode: (internal_key, [display_name_options])
ONE_PER_ROW_MODE   = ("1 per row", ["1 Flew Over", "1 Tree", "Ready Player 1", "1, None", "Power of 1", "1st Circle", "1st Law"])
TWO_PER_ROW_MODE   = ("2 per row", ["2 Cities", "2 Towers", "Swim-2-Birds", "2nd Sex", "2nd Sons"])
THREE_PER_ROW_MODE = ("3 per row", ["3 Body", "3 Stigmata", "3 Kingdoms", "Drawing of the 3", "3 Lives", "The 3rd Man", "3rd Policeman", "3 Guineas", "3 Comrades"])
SQUARE_MODE        = ("Square",    ["Washington Sq."])
LIST_MODE          = ("List",      ["Cannery Row"])
VIEW_MODES = [ONE_PER_ROW_MODE, TWO_PER_ROW_MODE, THREE_PER_ROW_MODE, SQUARE_MODE, LIST_MODE]

# Constants for Virtual Scrolling
ITEM_DIMENSIONS = {
    "3 per row": {"w": 96,  "h": 146, "cols": 3},
    "Square":    {"w": 96,  "h": 96,  "cols": 3},
    "2 per row": {"w": 140, "h": 226, "cols": 2},
    "1 per row": {"w": 292, "h": 159, "cols": 1},
    "List":      {"w": 290, "h": 28,  "cols": 1}
}

SORT_KEY_MAP = {
    "Title":       "title",
    "Author":      "author",
    "Last Played": "last_played",
    "Progress":    "progress",
    "Duration":    "duration",
    "Year":        "year",
}

MIN_PROGRESS = 1.0  # seconds — anything under 1 second is treated as zero

FONT_SIZES = {
    "1 per row": {
        "title":      (14, True),   # (px, bold)
        "author":     (14, False),
        "narrator":   (13, False),
        "year":       (14, False),
        "elapsed":    (14, False),
        "total":      (14, False),
        "percentage": (14, False),
    },
    "2 per row": {
        "title":      (13, True),
        "author":     (12, False),
        "elapsed":    (14, False),
        "total":      (14, False),
        "percentage": (14, False),
    },
    "3 per row": {
        "elapsed":    (12, False),
        "total":      (12, False),
        "percentage": (12, False),
    },
    "Square": {
        "elapsed":    (12, False),
        "total":      (12, False),
        "percentage": (12, False),
    },
    "List": {
        "title":      (14, True),
        "author":     (13, False),
        "total":      (13, False),
        "elapsed":    (13, False),
    },
}

ACTIVE_BOOK_STRIPE_WIDTH = 4 # for the List view

class BookItem(QFrame):
    clicked = Signal(str) # Emits the file path
    _total_clear_time = 0.0 # Profile accumulator

    def __init__(self, view_mode="3 per row", player_instance=None, pg_bg=None, pg_fill=None,
                 hover_bg_color=None, parent=None):
        
        super().__init__(parent)
        self._is_building_ui = True
        self.book_data = {}
        self.current_path = ""
        self.view_mode = view_mode
        self.player_instance = player_instance
        self.setObjectName("book_item")
        self._is_toggling = False
        self._show_remaining = True
        self._pg_bg = pg_bg
        self._pg_fill = pg_fill
        self._hover_bg_color = hover_bg_color or QColor(80, 80, 80, 180)
        self.setCursor(Qt.PointingHandCursor)
        
        self._build_ui()
        self._is_building_ui = False

    # ---------------- UI BUILD ----------------
    def _get_or_create_label(self, attr_name, object_name=None, style=None):
        if not hasattr(self, attr_name):
            lbl = QLabel()
            if object_name:
                lbl.setObjectName(object_name)
            if style:
                lbl.setStyleSheet(style)
            setattr(self, attr_name, lbl)
            return lbl, True
        return getattr(self, attr_name), False

    def _get_archetype(self, mode):
        """Categorizes view modes into structural archetypes for lazy rebuild."""
        if mode in ("2 per row", "3 per row", "Square"):
            return "grid"
        return mode # "1 per row" and "List" remain distinct structural types

    def set_view_mode(self, mode):
        """Re-initializes the UI for a new view mode without destroying the widget."""
        if self.view_mode == mode:
            return
        self._is_building_ui = True
        self.view_mode = mode
        self._build_ui()
        self._is_building_ui = False
        if self.book_data:
            self.bind(self.book_data)

    def _clear_layout(self):
        t0 = time.perf_counter()
        if self.layout():
            # Immediately detach the layout by setting it on a dummy widget
            QWidget().setLayout(self.layout())
            
        # Reset mode-specific attributes to avoid using dead C++ objects
        for attr in ['cover_label', 'overlay_widget', 'title_label', 'author_label',
                    'narrator_label', 'year_label', 'elapsed_label', 'total_label',
                    'pct_label', 'progress_outer', 'progress_inner', 'progress_container']:
            if hasattr(self, attr):
                try: delattr(self, attr)
                except AttributeError: pass
        BookItem._total_clear_time += (time.perf_counter() - t0)

    @staticmethod
    def _elide(label, text, width):
        text = text or ""
        fm = label.fontMetrics()
        if fm.horizontalAdvance(text) - width < fm.horizontalAdvance("…"):
            return text
        return fm.elidedText(text, Qt.ElideRight, width)

    def _make_cover(self, w, h):
        label = QLabel()
        label.setFixedSize(w, h)
        label.setStyleSheet("background:#0D001A;")
        label.setAlignment(Qt.AlignCenter)
        label.setContentsMargins(0,0,0,0)
        return label

    def _make_time_row(self):
        row = QHBoxLayout()
        row.setContentsMargins(0,0,0,0)
        row.setSpacing(0)

        self.elapsed_label = QLabel()
        self.elapsed_label.setObjectName("book_item_elapsed")
        self.elapsed_label.setContentsMargins(0,0,0,0)
        self.total_label = QLabel()
        self.total_label.setObjectName("book_item_total")
        self.total_label.setContentsMargins(0,0,0,0)

        # Hardcoded sizes
        if self.view_mode == "1 per row":
            size = 14
        elif self.view_mode == "2 per row":
            size = 13
        else: # 3 per row
            size = 12
        self.elapsed_label.setStyleSheet(f"font-size: {size}px;")
        self.total_label.setStyleSheet(f"font-size: {size}px;")

        row.addWidget(self.elapsed_label)
        row.addStretch()
        row.addWidget(self.total_label)
        return row

    def _make_progress_row(self):
        self.progress_container = QWidget()
        self.progress_container.setFixedHeight(16)
        row = QHBoxLayout(self.progress_container)
        row.setContentsMargins(0,0,0,0)
        row.setSpacing(8)

        if self.view_mode == "1 per row":
            row.addStretch()

        self.progress_outer = QFrame()
        self.progress_outer.setObjectName("book_progress_outer")
        self.progress_inner = QFrame(self.progress_outer)
        self.progress_inner.setObjectName("book_progress_inner")
        self.progress_inner.setGeometry(0, 0, 0, 6)

        self.pct_label = QLabel()
        self.pct_label.setObjectName("book_item_percentage")
        self.pct_label.setContentsMargins(0,0,0,0)

        # Hardcoded size
        if self.view_mode == "1 per row":
            size = 14
        elif self.view_mode == "2 per row":
            size = 13
        else: # 3 per row
            size = 12
        self.pct_label.setStyleSheet(f"font-size: {size}px;")

        # Styling and Constraints
        self.progress_outer.setFixedHeight(6)
        if self.view_mode == "3 per row":
            self.progress_outer.setFixedWidth(65)
        elif self.view_mode == "2 per row":
            self.progress_outer.setFixedWidth(84)
        elif self.view_mode == "1 per row":
            self.progress_outer.setFixedWidth(132)
        
        self.pct_label.setFixedWidth(35)
        self.pct_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        row.addWidget(self.progress_outer)
        row.addWidget(self.pct_label)
        return self.progress_container

    def _build_ui(self):
        mode = self.view_mode
        new_arch = self._get_archetype(mode)
        old_arch = getattr(self, "_current_arch", None)

        # Only teardown if the underlying layout archetype changed
        if new_arch != old_arch:
            self._clear_layout()
            self._current_arch = new_arch

        # -------- GRID ARCHETYPE (2 per, 3 per, Square) --------
        if new_arch == "grid":
            if not self.layout():
                layout = QVBoxLayout(self)
                layout.setSpacing(0)
            else:
                layout = self.layout()

            if mode == "3 per row":
                self.setFixedSize(96, 146)
                layout.setContentsMargins(2, 2, 1, 2)
                if not hasattr(self, 'cover_label'):
                    self.cover_label = self._make_cover(92, 142)
                    layout.addWidget(self.cover_label)
                else:
                    self.cover_label.setFixedSize(92, 142)
                    self.cover_label.show()
                if hasattr(self, 'title_label'): self.title_label.hide()
                if hasattr(self, 'author_label'): self.author_label.hide()

            elif mode == "Square":
                self.setFixedSize(96, 96)
                layout.setContentsMargins(2, 2, 1, 2)
                if not hasattr(self, 'cover_label'):
                    self.cover_label = self._make_cover(92, 92)
                    layout.addWidget(self.cover_label)
                else:
                    self.cover_label.setFixedSize(92, 92)
                    self.cover_label.show()
                if hasattr(self, 'title_label'): self.title_label.hide()
                if hasattr(self, 'author_label'): self.author_label.hide()

            elif mode == "2 per row":
                self.setFixedSize(140, 226)
                layout.setContentsMargins(13, 8, 0, 0)
                if not hasattr(self, 'cover_label'):
                    self.cover_label = self._make_cover(113, 172)
                    layout.addWidget(self.cover_label, alignment=Qt.AlignLeft)
                else:
                    self.cover_label.setFixedSize(113, 172)
                    self.cover_label.show()
                    layout.setAlignment(self.cover_label, Qt.AlignLeft)

                if not hasattr(self, 'title_label'):
                    self.title_label = QLabel()
                    self.title_label.setObjectName("book_item_title")
                    self.title_label.setStyleSheet("font-size: 14px;")
                    self.title_label.setContentsMargins(0, 0, 14, 0)
                    layout.addWidget(self.title_label)
                else:
                    self.title_label.show()

                if not hasattr(self, 'author_label'):
                    self.author_label = QLabel()
                    self.author_label.setObjectName("book_item_author")
                    self.author_label.setStyleSheet("font-size: 13px;")
                    self.author_label.setContentsMargins(0, 0, 14, 0)
                    layout.addWidget(self.author_label)
                else:
                    self.author_label.show()

            if not hasattr(self, 'overlay_widget'):
                self._overlay_has_progress = False
                self.overlay_widget = QWidget(self)
                ovl_layout = QVBoxLayout(self.overlay_widget)
                ovl_layout.setContentsMargins(4, 4, 4, 4)
                ovl_layout.setSpacing(2)
                ovl_layout.addStretch()

                self.overlay_time_row = QWidget()
                self.overlay_time_row.setAttribute(Qt.WA_TransparentForMouseEvents)
                time_row_layout = QHBoxLayout(self.overlay_time_row)
                time_row_layout.setContentsMargins(0, 0, 0, 0)
                time_row_layout.setSpacing(0)
                self.overlay_elapsed_label = QLabel()
                self.overlay_remaining_label = QLabel()
                time_row_layout.addWidget(self.overlay_elapsed_label)
                time_row_layout.addStretch()
                time_row_layout.addWidget(self.overlay_remaining_label)
                ovl_layout.addWidget(self.overlay_time_row)

                bottom_row = QWidget()
                bottom_row.setAttribute(Qt.WA_TransparentForMouseEvents)
                bottom_layout = QHBoxLayout(bottom_row)
                bottom_layout.setContentsMargins(0, 0, 0, 0)
                bottom_layout.setSpacing(4)

                self.overlay_progress_bar = QProgressBar()
                self.overlay_progress_bar.setObjectName("overlay_progress_bar")
                self.overlay_progress_bar.setFixedHeight(6)
                self.overlay_progress_bar.setTextVisible(False)
                self.overlay_progress_bar.setRange(0, 1000)
                self.overlay_progress_bar.setValue(0)
                self.overlay_progress_bar.setStyleSheet(f"""
                    QProgressBar {{ background-color: {self._pg_bg}; border: none; border-radius: 0px; }}
                    QProgressBar::chunk {{ background-color: {self._pg_fill}; border: none; border-radius: 0px; }}
                """)

                self.overlay_pct_label = QLabel()
                self.overlay_pct_label.setStyleSheet("color: white; font-size: 14px; background: transparent;")
                self.overlay_pct_label.setFixedWidth(30)
                self.overlay_pct_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

                self.overlay_progress_container = QWidget()
                progress_container_layout = QHBoxLayout(self.overlay_progress_container)
                progress_container_layout.setContentsMargins(0,0,0,0)
                progress_container_layout.setSpacing(4)
                progress_container_layout.addWidget(self.overlay_progress_bar, 1)
                progress_container_layout.addWidget(self.overlay_pct_label)

                self.overlay_total_duration_label = QLabel()
                self.overlay_total_duration_label.setStyleSheet("color: white; font-size: 14px; background: transparent;")
                self.overlay_total_duration_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

                bottom_layout.addWidget(self.overlay_progress_container)
                bottom_layout.addWidget(self.overlay_total_duration_label)
                ovl_layout.addWidget(bottom_row)
                self.overlay_widget.setStyleSheet(
                    "background: qlineargradient(x1:2, y1:2, x1:4, y1:4, stop:0 rgba(0,0,0,100), stop:1 rgba(0,0,0,230));"
                )
                self.overlay_time_row.setStyleSheet("background: transparent;")
                bottom_row.setStyleSheet("background: transparent;")
                for lbl in (self.overlay_elapsed_label, self.overlay_remaining_label, self.overlay_pct_label):
                    lbl.setStyleSheet("color: white; font-size: 12px; background: transparent;")
                self.overlay_elapsed_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                self.overlay_remaining_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

                self.overlay_widget.setAttribute(Qt.WA_TransparentForMouseEvents)
                self.overlay_widget.hide()
            self._reposition_overlay()
            return

        # -------- 1 PER ROW --------
        if mode == "1 per row":
            self.setFixedSize(292,161)
            layout = QHBoxLayout(self)
            layout.setContentsMargins(4,4,4,4)
            layout.setSpacing(8)

            self.cover_label = self._make_cover(100,151)
            layout.addWidget(self.cover_label)

            text_layout = QVBoxLayout()
            text_layout.setSpacing(2)

            self.title_label = QLabel()
            self.title_label.setObjectName("book_item_title")
            self.title_label.setStyleSheet("font-size: 14px;")
            self.author_label = QLabel()
            self.author_label.setObjectName("book_item_author")
            self.author_label.setStyleSheet("font-size: 14px;")
            self.narrator_label = QLabel()
            self.narrator_label.setObjectName("book_item_narrator")
            self.narrator_label.setStyleSheet("font-size: 14px;")
            self.year_label = QLabel()
            self.year_label.setStyleSheet("font-size: 12px;")

            for lbl in (self.title_label, self.author_label, self.narrator_label, self.year_label):
                lbl.setContentsMargins(0,0,0,0)

            text_layout.addWidget(self.title_label)
            text_layout.addWidget(self.author_label)
            text_layout.addWidget(self.narrator_label)
            text_layout.addWidget(self.year_label)

            self.time_row = self._make_time_row()
            text_layout.addLayout(self.time_row)

            self.progress_row = self._make_progress_row()
            text_layout.addWidget(self.progress_row)

            layout.addLayout(text_layout)

        # -------- LIST --------
        else:  # list
            self.setFixedSize(290,28)
            if not self.layout():
                layout = QHBoxLayout(self)
                layout.setContentsMargins(4,4,4,4)
                layout.setSpacing(6)
            else:
                layout = self.layout()

            title_lbl, is_new_t = self._get_or_create_label('title_label', "book_item_title", "font-size: 14px;")
            author_lbl, is_new_a = self._get_or_create_label('author_label', "book_item_author", "font-size: 14px;")
            if is_new_t:
                title_lbl.setContentsMargins(4,0,0,0)
                layout.addWidget(title_lbl)
                title_lbl.installEventFilter(self)
            else:
                title_lbl.show()

            if is_new_a:
                author_lbl.setAlignment(Qt.AlignRight)
                author_lbl.setContentsMargins(0,0,0,0)
                layout.addStretch()
                layout.addWidget(author_lbl)
                author_lbl.installEventFilter(self)
            else:
                author_lbl.show()

            if not hasattr(self, 'total_label'):
                self.total_label = QLabel()
                self.total_label.setObjectName("book_item_total")
                self.total_label.setStyleSheet("font-size: 14px;")
                self.total_label.setFixedWidth(46)
                self.total_label.setAlignment(Qt.AlignRight)
                self.total_label.setContentsMargins(0,0,0,0)
                layout.addWidget(self.total_label)
            else:
                self.total_label.show()

            self._title_is_elided = False
            self._author_is_elided = False

            self.title_label.installEventFilter(self)
            self.author_label.installEventFilter(self)


    def bind(self, book_data):
        """Virtual Scroll entry point: Rebinds the widget to new data."""
        self.book_data = book_data
        old_path = self.current_path
        self.current_path = book_data.path
        
        self._update_ui_content()
        return old_path != self.current_path

    def _reposition_overlay(self):
        if not hasattr(self, 'overlay_widget') or not hasattr(self, 'cover_label'):
            return

        try:
            cw = self.cover_label.width()
            ch = self.cover_label.height()

            pct = 0.30 if getattr(self, '_overlay_has_progress', False) else 0.20
            oh = int(ch * pct)

            if self.view_mode == "2 per row" and not getattr(self, '_overlay_has_progress', False):
                oh -= 9

            elif self.view_mode == "3 per row" and not getattr(self, '_overlay_has_progress', False):
                oh -= 4

            elif self.view_mode == "Square":
                if getattr(self, '_overlay_has_progress', False): 
                    oh += 12
                elif self.view_mode == "Square" and not getattr(self, '_overlay_has_progress', False):
                    oh += 4

            self.overlay_widget.resize(cw, oh)

            # Use the layout margins directly — cover_label sits at (left, top) within
            # the BookItem in both grid modes, and these values are set before any layout
            # processing, so they're always reliable.
            m = self.layout().contentsMargins()
            self.overlay_widget.move(m.left(), m.top() + ch - oh)
        except RuntimeError:
            return

    def _update_progress_bar(self):
        if not hasattr(self, 'overlay_progress_bar'):
            return
        prog = self.book_data.progress
        dur = self.book_data.duration
        pct = (prog / dur) if dur > 0 else 0
        self.overlay_progress_bar.setValue(int(pct * 1000))

    def enterEvent(self, event):
        if hasattr(self, 'overlay_widget'):
            self.overlay_widget.show()
            self.overlay_widget.raise_()
            self._update_progress_bar()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if hasattr(self, 'overlay_widget'):
            self.overlay_widget.hide()
        super().leaveEvent(event)

    def eventFilter(self, obj, event):
        if self.view_mode == "List":
            title_lbl = getattr(self, 'title_label', None)
            author_lbl = getattr(self, 'author_label', None)
            if not title_lbl or not author_lbl:
                return super().eventFilter(obj, event)

            if event.type() == QEvent.Enter:
                if obj is title_lbl and getattr(self, '_title_is_elided', False):
                    author_lbl.hide()
                    title_lbl.setText(self.book_data.title)
                elif obj is author_lbl and getattr(self, '_author_is_elided', False):
                    title_lbl.hide()
                    # Expand author to take available space (matches AVAILABLE in _update_ui_content)
                    author_lbl.setFixedWidth(218)
                    author_lbl.setText(self.book_data.author)
            elif event.type() == QEvent.Leave:
                if obj is title_lbl or obj is author_lbl:
                    title_lbl.show()
                    author_lbl.show()
                    self._update_ui_content()
        return super().eventFilter(obj, event)

    def showEvent(self, event):
        super().showEvent(event)
        self._reposition_overlay()

    def mousePressEvent(self, event):
        self._is_toggling = False
        if event.button() == Qt.LeftButton:
            prog = self.book_data.progress
            dur = self.book_data.duration

            if prog > 0 and dur > 0:
                target = None
                # If overlay is visible, it takes precedence for the hit test
                if hasattr(self, 'overlay_widget') and self.overlay_widget.isVisible():
                    target = self.overlay_remaining_label
                elif hasattr(self, 'total_label'):
                    target = self.total_label

                if target:
                    from PySide6.QtCore import QRect
                    hit_rect = QRect(target.mapToGlobal(target.rect().topLeft()), target.size())
                    if hit_rect.contains(event.globalPosition().toPoint()):
                        self._is_toggling = True
                        self._show_remaining = not self._show_remaining
                        self._update_ui_content()
                        event.accept()
                        return
        super().mousePressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if getattr(self, '_is_building_ui', False):
            return
            
        # Ensure progress inner width is updated when the layout resizes the parent
        if hasattr(self, "progress_inner") and hasattr(self, "progress_outer") and self.book_data:
            prog = self.book_data.progress
            dur = self.book_data.duration
            pct = (prog / dur) if dur > 0 else 0
            try:
                w = int(self.progress_outer.maximumWidth() * pct)
                self.progress_inner.setGeometry(0, 0, w, 6)
            except RuntimeError: pass
        self._reposition_overlay()

    def _update_ui_content(self):
        """Internal: Updates labels based on current book_data."""
        book_data = self.book_data
        title = book_data.title or ""
        author = book_data.author or ""
        narrator = book_data.narrator
        year = book_data.year

        prog = book_data.progress
        dur = book_data.duration
        pct = (prog / dur) if dur > 0 else 0
        speed = self.book_data.speed
        has_progress = prog > 0 and dur > 0

        def fmt_time(s):
            s = int(s or 0)
            return f"{s//3600}:{(s%3600)//60:02}:{s%60:02}"

        # title/author (elision by mode; List is handled in the invade block below)
        if hasattr(self, "title_label"):
            if self.view_mode == "1 per row":
                self.title_label.setText(self._elide(self.title_label, title, 176))
            elif self.view_mode == "2 per row":
                self.title_label.setText(self._elide(self.title_label, title, 113))

        if hasattr(self, "author_label"):
            if self.view_mode == "1 per row":
                self.author_label.setText(self._elide(self.author_label, author, 176))
            elif self.view_mode == "2 per row":
                self.author_label.setText(self._elide(self.author_label, author, 113))

        # narrator/year visibility
        if hasattr(self, "narrator_label"):
            if self.view_mode == "1 per row":
                self.narrator_label.setText(self._elide(self.narrator_label, narrator or "", 176))
            else:
                self.narrator_label.setText(narrator or "")
            self.narrator_label.setVisible(bool(narrator))

        if hasattr(self, "year_label"):
            self.year_label.setText(str(year) if year else "")
            self.year_label.setVisible(bool(year))

        # time row
        if hasattr(self, "elapsed_label"):
            self.elapsed_label.setText(fmt_time(prog))
            self.elapsed_label.setVisible(prog > 0)

        if hasattr(self, "total_label"):
            if has_progress and self._show_remaining:
                self.total_label.setText(f"-{fmt_time((dur - prog) / speed)}")
            else:
                self.total_label.setText(fmt_time(dur / speed))

            if self.view_mode == "1 per row" and not has_progress:
                self.total_label.setVisible(False)
            else:
                self.total_label.setVisible(True)

        # List: invade elision
        if self.view_mode == "List" and hasattr(self, "title_label") and hasattr(self, "author_label"):
            self.title_label.ensurePolished()
            self.author_label.ensurePolished()
            fm_t = self.title_label.fontMetrics()
            fm_a = self.author_label.fontMetrics()
            AVAILABLE   = 218
            AUTHOR_BASE = 100
            TITLE_CM    = 4
            BUFFER      = 4
            title_text_w  = fm_t.horizontalAdvance(title)
            author_text_w = fm_a.horizontalAdvance(author)
            # Short author donates unused space to title; buffer absorbs sub-pixel slack
            author_w     = min(author_text_w + BUFFER, AUTHOR_BASE)
            title_max_lw = AVAILABLE - author_w
            # Long author invades title's spare space
            if author_text_w + BUFFER > AUTHOR_BASE:
                spare    = max(0, title_max_lw - (title_text_w + TITLE_CM))
                author_w = min(author_text_w + BUFFER, AUTHOR_BASE + spare)
                title_max_lw = AVAILABLE - author_w
            title_avail = title_max_lw - TITLE_CM
            ew_t = fm_t.horizontalAdvance("…")
            ew_a = fm_a.horizontalAdvance("…")
            disp_title  = title  if title_text_w  - title_avail < ew_t else fm_t.elidedText(title,  Qt.ElideRight, title_avail)
            disp_author = author if author_text_w  - author_w    < ew_a else fm_a.elidedText(author, Qt.ElideRight, author_w)
            self.author_label.setFixedWidth(max(1, author_w))
            self.title_label.setText(disp_title)
            self.author_label.setText(disp_author)

            self._title_is_elided = (disp_title != title)
            self._author_is_elided = (disp_author != author)

        # progress
        show_progress = prog > 0
        if hasattr(self, "progress_outer") and hasattr(self, "pct_label"):
            self.progress_outer.setVisible(show_progress)

            if self.view_mode == "1 per row" and not show_progress:
                self.pct_label.setText(fmt_time(dur / speed))
                self.pct_label.setFixedWidth(60)
                self.pct_label.setVisible(True)
            else:
                self.pct_label.setFixedWidth(35)
                self.pct_label.setText(f"{int(pct*100)}%")
                self.pct_label.setVisible(show_progress)

        if hasattr(self, "progress_inner"):
            w = int(self.progress_outer.maximumWidth() * pct)
            self.progress_inner.setGeometry(0, 0, w, 6)

        if hasattr(self, 'overlay_widget'):

            if has_progress != self._overlay_has_progress:
                self._overlay_has_progress = has_progress
                self._reposition_overlay()

            if has_progress:
                # Show elapsed and remaining/total in the top row
                self.overlay_time_row.setVisible(True)
                if self.view_mode == "2 per row":
                    style = "color: white; font-size: 14px; background: transparent;"
                    self.overlay_elapsed_label.setStyleSheet(style)
                    self.overlay_remaining_label.setStyleSheet(style)
                    self.overlay_pct_label.setStyleSheet(style)

                self.overlay_elapsed_label.setVisible(True)
                self.overlay_remaining_label.setVisible(True)
                remaining_s = (dur - prog) / speed
                total_s = dur / speed
                self.overlay_elapsed_label.setText(fmt_time(prog))
                if self._show_remaining:
                    self.overlay_remaining_label.setText(f"-{fmt_time(remaining_s)}")
                else:
                    self.overlay_remaining_label.setText(fmt_time(total_s))
                self.overlay_remaining_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

                # Show progress bar elements in the bottom row
                self.overlay_progress_container.setVisible(True)
                self.overlay_total_duration_label.setVisible(False) # Hide total duration label
                self.overlay_pct_label.setText(f"{int(pct * 100)}%")
                self._update_progress_bar()
            else:
                self.overlay_time_row.setVisible(False)
                self.overlay_progress_container.setVisible(False) # Hide progress bar elements
                self.overlay_total_duration_label.setVisible(True) # Show total duration label
                if self.view_mode == "2 per row":
                    self.overlay_total_duration_label.setStyleSheet("color: white; font-size: 15px; background: transparent;")

                self.overlay_total_duration_label.setText(fmt_time(dur / speed))
                self.overlay_total_duration_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def set_cover(self, pixmap):
        if hasattr(self, 'cover_label'):
            if pixmap and not pixmap.isNull():
                # Fetch current screen DPR to ensure crispness without size issues
                dpr = self.screen().devicePixelRatio() if self.screen() else 1.0

                # Smart scaling: Crop if ratios are close, letterbox if they differ significantly
                cell_size = self.cover_label.size()
                if self.view_mode == "Square":
                    mode = Qt.KeepAspectRatioByExpanding
                else:
                    mode = Qt.KeepAspectRatio
                    if cell_size.height() > 0 and pixmap.height() > 0:
                        cell_ratio = cell_size.width() / cell_size.height()
                        cover_ratio = pixmap.width() / pixmap.height()
                        # If within 8% of the cell ratio, expand/crop for a cleaner look
                        if abs(cover_ratio - cell_ratio) / cell_ratio < 0.08:
                            mode = Qt.KeepAspectRatioByExpanding

                scaled = pixmap.scaled(
                    cell_size * dpr,
                    mode,
                    Qt.SmoothTransformation
                )
                scaled.setDevicePixelRatio(dpr)
                self.cover_label.setPixmap(scaled)
                self.cover_label.setProperty("placeholder", False)
                self.cover_label.setText("")
            else:
                # Fallback to placeholder if no cover is available
                display_title = self.book_data.title or "Unknown"
                self.cover_label.setText(display_title[:1])
                self.cover_label.setProperty("placeholder", True)
                self.cover_label.setPixmap(QPixmap())
            
            self.cover_label.style().unpolish(self.cover_label)
            self.cover_label.style().polish(self.cover_label)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self._is_toggling:
                self._is_toggling = False
                return
            self.clicked.emit(self.book_data.path)
        super().mouseReleaseEvent(event)


class LibraryPanel(QFrame):
    book_selected    = Signal(str)
    back_requested   = Signal()
    detail_requested = Signal(str)

    def __init__(self, db, config, player_instance=None, parent=None):
        super().__init__(parent)
        self.db              = db
        self.config          = config
        self.player_instance = player_instance

        self._active_workers = set()
        self._current_theme  = {}

        self._setup_ui()
        self._resolve_theme_colors()
        self._setup_model_view()

    # ── Theme ────────────────────────────────────────────────────────────────

    def _resolve_theme_colors(self):
        from ..themes import THEMES
        main_win = self.parent() if hasattr(self.parent(), 'theme_manager') else self.window()
        if main_win and hasattr(main_win, 'theme_manager'):
            t = THEMES.get(main_win.theme_manager._current_theme_name, THEMES["The Color Purple"])
            self._current_theme = t

    def update_progress_bar_theme(self) -> None:
        self._resolve_theme_colors()
        self._delegate.update_theme(self._current_theme)
        self._list_view.viewport().update()

    # ── Model / view setup ───────────────────────────────────────────────────

    def _setup_model_view(self):
        self._book_model = BookModel(parent=self)
        self._delegate   = BookDelegate(
            theme=self._current_theme,
            parent=self,
        )

        self._list_view = QListView(self)
        self._list_view.setModel(self._book_model)
        self._list_view.setItemDelegate(self._delegate)
        self._list_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list_view.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self._list_view.setResizeMode(QListView.ResizeMode.Adjust)
        self._list_view.setViewMode(QListView.ViewMode.ListMode)
        self._list_view.setUniformItemSizes(True)
        self._list_view.setMouseTracking(True)
        self._list_view.setContextMenuPolicy(Qt.CustomContextMenu)

        self._list_view.clicked.connect(self._on_item_clicked)
        self._list_view.customContextMenuRequested.connect(self._on_context_menu)
        self._list_view.entered.connect(self._on_view_entered)
        self._list_view.viewport().installEventFilter(self)
        self._list_view.verticalScrollBar().valueChanged.connect(self._load_visible_covers)
        self._list_view.viewport().setMouseTracking(True)
        self.main_layout.addWidget(self._list_view)

        saved_mode = self.style_combo.currentData()
        self._apply_view_mode(saved_mode)

    # ── Toolbar ──────────────────────────────────────────────────────────────

    def _setup_ui(self):
        self.setObjectName("library_panel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        self.top_bar_widget = QFrame()
        self.top_bar_widget.setObjectName("library_top_bar")
        self.top_bar_layout = QHBoxLayout(self.top_bar_widget)
        self.top_bar_layout.setContentsMargins(3, 6, 3, 6)
        self.top_bar_layout.setSpacing(3)

        self.sort_combo = QComboBox()
        for display, key in [
            ("Title",    "Title"),
            ("Author",   "Author"),
            ("Recent",   "Last Played"),
            ("Progress", "Progress"),
            ("Duration", "Duration"),
            ("Year",     "Year"),
        ]:
            self.sort_combo.addItem(display, key)
        self.sort_combo.setFixedWidth(65)
        self.sort_combo.setFixedHeight(30)
        saved_sort = self.config.get_library_sort_key()
        for i in range(self.sort_combo.count()):
            if self.sort_combo.itemData(i) == saved_sort:
                self.sort_combo.setCurrentIndex(i)
                break
        self._sort_ascending   = self.config.get_library_sort_ascending()
        self._last_filter_mode = self.sort_combo.currentData()
        self.sort_combo.currentTextChanged.connect(self._on_sort_changed)

        self.sort_dir_btn = QPushButton("↑" if self._sort_ascending else "↓")
        self.sort_dir_btn.setFixedWidth(16)
        self.sort_dir_btn.setFixedHeight(26)
        self.sort_dir_btn.clicked.connect(self._toggle_sort_direction)

        self.style_combo = QComboBox()
        for key, options in VIEW_MODES:
            self.style_combo.addItem(random.choice(options), key)
        self.style_combo.setFixedWidth(94)
        saved_mode = self.config.get_library_view_mode()
        for i in range(self.style_combo.count()):
            if self.style_combo.itemData(i) == saved_mode:
                self.style_combo.setCurrentIndex(i)
                break
        self.style_combo.currentTextChanged.connect(self._on_view_mode_changed)

        self.search_field = QLineEdit()
        self.search_field.setPlaceholderText("search #tag")
        self.search_field.setFixedWidth(63)
        self.search_field.setFixedHeight(30)
        self.search_field.textChanged.connect(self._on_search_changed)

        self.back_button = QPushButton("Back")
        self.back_button.setFixedHeight(28)
        self.back_button.clicked.connect(self.back_requested.emit)

        self.top_bar_layout.addWidget(self.sort_combo)
        self.top_bar_layout.addWidget(self.sort_dir_btn)
        self.top_bar_layout.addWidget(self.style_combo)
        self.top_bar_layout.addWidget(self.search_field)
        self.top_bar_layout.addWidget(self.back_button)
        self.main_layout.addWidget(self.top_bar_widget)

    # ── QListView slots ──────────────────────────────────────────────────────

    def _on_item_clicked(self, index):
        book = index.data(ROLE_BOOK)
        if not book:
            return
        live_pos = index.data(ROLE_LIVE_POS) or 0.0
        live_dur = index.data(ROLE_LIVE_DUR) or 0.0
        if live_pos > 0 and live_dur > 0:
            # Check if click was on time rect via delegate
            if self._delegate.last_event_was_toggle:
                self._delegate.last_event_was_toggle = False
                return
        self.book_selected.emit(book.path)

    def _on_context_menu(self, pos):
        index = self._list_view.indexAt(pos)
        if not index.isValid():
            return
        book = index.data(ROLE_BOOK)
        if book:
            self.detail_requested.emit(book.path)

    def _on_view_entered(self, index):
        book = index.data(ROLE_BOOK)
        self._book_model.set_hovered(book.path if book else None)

    def _on_view_left(self):
        self._book_model.set_hovered(None)

    def eventFilter(self, obj, event):
        if obj is self._list_view.viewport():
            if event.type() == QEvent.Type.MouseMove:
                self._delegate._hover_pos = event.position().toPoint()
                idx = self._list_view.indexAt(event.position().toPoint())
                if idx.isValid():
                    self._list_view.update(idx)
            elif event.type() == QEvent.Type.Leave:
                self._on_view_left()
        return super().eventFilter(obj, event)



    # ── View mode ────────────────────────────────────────────────────────────

    def _apply_view_mode(self, mode: str) -> None:
        self._delegate.set_view_mode(mode)
        dim = ITEM_DIMENSIONS.get(mode, ITEM_DIMENSIONS["3 per row"])
        if mode in ("3 per row", "2 per row", "Square"):
            self._list_view.setViewMode(QListView.ViewMode.IconMode)
            self._list_view.setGridSize(QSize(dim["w"], dim["h"]))
            self._list_view.setSpacing(0)
        else:
            self._list_view.setViewMode(QListView.ViewMode.ListMode)
            self._list_view.setGridSize(QSize())

    def _on_view_mode_changed(self, _):
        mode = self.style_combo.currentData()
        self.config.set_library_view_mode(mode)
        self._resolve_theme_colors()
        self._apply_view_mode(mode)
        self._book_model.set_hovered(None)

        self._list_view.reset()
        QTimer.singleShot(0, self._load_visible_covers)

    def _populate_list_widgets(self):
        playing_path = (
            getattr(self.player_instance.instance, 'path', None)
            if self.player_instance and self.player_instance.instance else None
        )
        pos_now = self.player_instance.time_pos or 0.0 if self.player_instance else 0.0
        dur_now = self.player_instance.duration  or 0.0 if self.player_instance else 0.0

        for row in range(self._book_model.rowCount()):
            index = self._book_model.index(row, 0)
            book  = index.data(ROLE_BOOK)
            if not book:
                continue

            live_pos = pos_now if book.path == playing_path else 0.0
            live_dur = dur_now if book.path == playing_path else (book.duration or 0.0)

            item = ListBookItem(
                hover_bg_color=self._hover_bg_color,
                alt_row=(row % 2 == 1),
                parent=self._list_view.viewport(),
            )
            item.bind(book, live_pos, live_dur)
            item.clicked.connect(self.book_selected.emit)
            item.context_requested.connect(self.detail_requested.emit)
            self._list_view.setIndexWidget(index, item)
            
    # ── Data / refresh ───────────────────────────────────────────────────────

    def refresh(self, force=False):
        self._resolve_theme_colors()
        books = self.db.get_all_books(sort_by="title", order="ASC")
        for book in books:
            book.speed = self.config.get_book_speed(book.path) or 1.0

        self._book_model.set_books(books)
        self._apply_current_sort_filter()

        QTimer.singleShot(0, self._load_visible_covers)

        # if self.style_combo.currentData() == "List":
        #     QTimer.singleShot(0, self._populate_list_widgets)

    def _apply_current_sort_filter(self):
        text = self.search_field.text().lower().strip()
        self._book_model.filter_books(text)

        sort_key  = self.sort_combo.currentData()
        ascending = getattr(self, '_sort_ascending', True)
        direction = "ascending" if ascending else "descending"
        self._book_model.sort_books(SORT_KEY_MAP.get(sort_key, "title"), direction)
        self.config.set_library_sort_key(sort_key)
        self.config.set_library_sort_ascending(ascending)

    # ── Cover loading ────────────────────────────────────────────────────────

    def _load_visible_covers(self):
        if not self.isVisible():
            return
        rect  = self._list_view.viewport().rect()
        first = self._list_view.indexAt(rect.topLeft())
        last  = self._list_view.indexAt(rect.bottomRight())
        if not first.isValid():
            return
        first_row = max(0, first.row() - 5)
        last_row  = min(
            self._book_model.rowCount() - 1,
            (last.row() if last.isValid() else self._book_model.rowCount() - 1) + 5,
        )
        in_flight = {getattr(w, '_book_path', None) for w in self._active_workers}
        for row in range(first_row, last_row + 1):
            index = self._book_model.index(row, 0)
            book  = index.data(ROLE_BOOK)
            if not book:
                continue
            if self._book_model._covers.get(book.path):
                continue
            if book.path in in_flight:
                continue
            self._trigger_cover_load(book)

    def _trigger_cover_load(self, book):
        from .cover_loader import CoverLoaderWorker
        worker = CoverLoaderWorker(book, self.player_instance)
        worker._book_path = book.path
        self._active_workers.add(worker)
        worker.signals.cover_loaded.connect(self._on_cover_loaded)
        worker.signals.finished.connect(lambda w=worker: self._active_workers.discard(w))
        QThreadPool.globalInstance().start(worker)

    def _on_cover_loaded(self, path, pixmap):
        if pixmap.isNull():
            return
        dpr = self.screen().devicePixelRatio() if self.screen() else 1.0
        pixmap.setDevicePixelRatio(dpr)
        self._book_model.update_cover(path, pixmap)

    # ── Sort / filter ────────────────────────────────────────────────────────

    def _toggle_sort_direction(self):
        self._sort_ascending = not getattr(self, '_sort_ascending', True)
        self.sort_dir_btn.setText("↑" if self._sort_ascending else "↓")
        sort_key  = self.sort_combo.currentData()
        direction = "ascending" if self._sort_ascending else "descending"
        self._book_model.sort_books(SORT_KEY_MAP.get(sort_key, "title"), direction)
        self.config.set_library_sort_ascending(self._sort_ascending)

    def _on_sort_changed(self):
        sort_key  = self.sort_combo.currentData()
        ascending = getattr(self, '_sort_ascending', True)
        direction = "ascending" if ascending else "descending"
        self._book_model.sort_books(SORT_KEY_MAP.get(sort_key, "title"), direction)
        self.config.set_library_sort_key(sort_key)
        self._last_filter_mode = sort_key

    def _on_search_changed(self, text):
        self._book_model.filter_books(text.lower().strip())

    # ── Live progress ────────────────────────────────────────────────────────

    def update_current_book_progress(self):
        if getattr(self, '_is_animating', False):
            return
        if not self.player_instance:
            return

        path = (
            getattr(self.player_instance.instance, 'path', None)
            if self.player_instance.instance else None
        )
        pos = self.player_instance.time_pos or 0.0
        dur = self.player_instance.duration  or 0.0

        if not path or dur <= 0:
            return

        self._book_model.update_playing_progress(path, pos, dur)

        if self.style_combo.currentData() == "List":
            for row in range(self._book_model.rowCount()):
                index  = self._book_model.index(row, 0)
                book   = index.data(ROLE_BOOK)
                widget = self._list_view.indexWidget(index)
                if book and book.path == path and isinstance(widget, ListBookItem):
                    widget.update_progress(pos, dur)
                    break

    def set_playing_path(self, path: str) -> None:
        self._delegate._playing_path = path or ""
        self._list_view.viewport().update()

    # ── Hide ─────────────────────────────────────────────────────────────────

    def _rotate_view_mode_labels(self):
        self.style_combo.blockSignals(True)
        for i, (_, options) in enumerate(VIEW_MODES):
            self.style_combo.setItemText(i, random.choice(options))
        self.style_combo.blockSignals(False)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._load_visible_covers)

    def hideEvent(self, event):
        super().hideEvent(event)
        self._book_model.set_hovered(None)
        self._rotate_view_mode_labels()


ROLE_BOOK     = Qt.UserRole + 0
ROLE_COVER    = Qt.UserRole + 1
ROLE_HOVERED  = Qt.UserRole + 2
ROLE_SHOW_REM = Qt.UserRole + 3
ROLE_LIVE_POS = Qt.UserRole + 4
ROLE_LIVE_DUR = Qt.UserRole + 5


class BookModel(QAbstractListModel):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._books: list[Book] = []
        self._filtered: list[Book] = []
        self._covers: dict[str, QPixmap] = {}
        self._show_remaining: dict[str, bool] = {}
        self._live_pos: dict[str, float] = {}
        self._live_dur: dict[str, float] = {}
        self._hovered_path: Optional[str] = None
        self._filter_text: str = ""
        self._sort_field: str = "title"
        self._sort_direction: str = "ascending"

    # ── QAbstractListModel interface ────────────────────────────────────────

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._filtered)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._filtered)):
            return None
        book = self._filtered[index.row()]
        path = book.path

        if role == ROLE_BOOK:
            return book
        if role == ROLE_COVER:
            return self._covers.get(path)
        if role == ROLE_HOVERED:
            return self._hovered_path == path
        if role == ROLE_SHOW_REM:
            return self._show_remaining.get(path, True)
        if role == ROLE_LIVE_POS:
            return self._live_pos.get(path, book.progress or 0.0)
        if role == ROLE_LIVE_DUR:
            return self._live_dur.get(path, book.duration or 0.0)
        if role == Qt.DisplayRole:
            return book.title
        return None

    # ── Data mutation ───────────────────────────────────────────────────────

    def set_books(self, books: list[Book]) -> None:
        self.beginResetModel()
        self._books = list(books)
        self._apply_filter_and_sort()
        self.endResetModel()

    def update_cover(self, path: str, pixmap: QPixmap) -> None:
        self._covers[path] = pixmap
        self._emit_for_path(path)

    def update_playing_progress(self, path: str, position: float, duration: float) -> None:
        self._live_pos[path] = position if position > MIN_PROGRESS else 0.0
        self._live_dur[path] = duration
        self._emit_for_path(path)

    def toggle_show_remaining(self, path: str) -> None:
        self._show_remaining[path] = not self._show_remaining.get(path, True)
        self._emit_for_path(path)

    def set_hovered(self, path: Optional[str]) -> None:
        previous = self._hovered_path
        self._hovered_path = path
        if previous:
            self._emit_for_path(previous)
        if path:
            self._emit_for_path(path)

    # ── Sort / filter ───────────────────────────────────────────────────────

    def sort_books(self, field: str, direction: str) -> None:
        self._sort_field = field
        self._sort_direction = direction
        self.beginResetModel()
        self._apply_filter_and_sort()
        self.endResetModel()

    def filter_books(self, text: str) -> None:
        self._filter_text = text.lower()
        self.beginResetModel()
        self._apply_filter_and_sort()
        self.endResetModel()

    # ── Internal ────────────────────────────────────────────────────────────

    def _apply_filter_and_sort(self) -> None:
        text = self._filter_text
        if text:
            books = [
                b for b in self._books
                if text in b.title.lower()
                or text in (b.author or "").lower()
                or text in (b.narrator or "").lower()
            ]
        else:
            books = list(self._books)

        # Filter "Recent" to only show books that have progress
        if self._sort_field == "last_played":
            books = [b for b in books if (b.progress or 0.0) > MIN_PROGRESS]

        reverse = self._sort_direction == "descending"
        field = self._sort_field

        from datetime import datetime as dt
        def sort_key(b):
            if field == "progress":
                pos = b.progress or 0.0
                dur = b.duration or 0.0
                return pos / dur if dur > 0 else 0.0

            val = getattr(b, field, None)
            if val is None:
                if field == "last_played": return dt.min
                # Safeguard: check first book for type hint if available
                first_b = self._books[0] if self._books else None
                if first_b and isinstance(getattr(first_b, field, None), str):
                    return ""
                return 0
            if isinstance(val, str):
                return val.lower()
            return val

        if self._sort_field in ("last_played", "progress"):
            have    = [b for b in books if (b.progress or 0.0) > MIN_PROGRESS]
            missing = [b for b in books if (b.progress or 0.0) <= MIN_PROGRESS]
            have.sort(key=sort_key, reverse=reverse)
            missing.sort(key=lambda b: (b.title or "").lower())
            books = have + missing
        else:
            books.sort(key=sort_key, reverse=reverse)
        self._filtered = books

    def _emit_for_path(self, path: str) -> None:
        for row, book in enumerate(self._filtered):
            if book.path == path:
                idx = self.index(row)
                self.dataChanged.emit(idx, idx)
                return

    def path_to_index(self, path: str) -> Optional[QModelIndex]:
        for row, book in enumerate(self._filtered):
            if book.path == path:
                return self.index(row)
        return None


class BookDelegate(QStyledItemDelegate):
    """
    QStyledItemDelegate for the model/view library rewrite.
    Accepts theme colors as constructor arguments; never resolves them itself.
    """

    def __init__(self, theme: dict, parent=None):
        super().__init__(parent)
        self._apply_theme(theme)
        self.last_event_was_toggle = False
        self._view_mode = "3 per row"
        self._alt_row_color = QColor(255, 255, 255, 10)  # overridden by _apply_theme
        self._hover_pos = QPoint()
        self._playing_path = ""

    def _apply_theme(self, theme: dict) -> None:
        def qc(hex_str, alpha=255):
            h = hex_str.lstrip('#')
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            return QColor(r, g, b, alpha)

        self._pg_bg          = theme.get('library_slider_bg',   theme.get('slider_overall_bg',   '#333333'))
        self._pg_fill        = theme.get('library_slider_fill', theme.get('slider_overall_fill', '#aaaaaa'))
        hc = theme.get('library_item_hover_color', theme.get('accent', '#ffffff'))
        ha = theme.get('library_item_hover_alpha', 0.50)
        self._hover_bg_color = qc(hc, int(ha * 255))

        self._bg_library     = qc(theme.get('bg_library',         '#1e1e1e'))
        self._grid_bg        = qc(theme.get('library_grid_bg',    theme.get('bg_library', '#1a1a1a')))
        self._row_one        = qc(theme.get('library_row_one',    '#242424'))
        self._row_two        = qc(theme.get('library_row_two',    '#2a2a2a'))
        self._color_title    = qc(theme.get('library_title',      '#ffffff'))
        self._color_author   = qc(theme.get('library_author',     '#aaaaaa'))
        self._color_narrator = qc(theme.get('library_narrator',   '#888888'))
        self._color_elapsed  = qc(theme.get('library_elapsed',    '#aaaaaa'))
        self._color_total    = qc(theme.get('library_total',      '#aaaaaa'))
        self._color_pct      = qc(theme.get('library_percentage', '#888888'))
        self._alt_row_color  = self._row_two
        self._color_accent   = qc(theme.get('accent', '#ffffff'))

    def update_theme(self, theme: dict) -> None:
        self._apply_theme(theme)

    # ── Public API ──────────────────────────────────────────────────────────

    def set_view_mode(self, mode: str) -> None:
        self._view_mode = mode

    def sizeHint(self, option, index):
        dim = ITEM_DIMENSIONS.get(self._view_mode, ITEM_DIMENSIONS["3 per row"])
        return QSize(dim["w"], dim["h"])

    # ── Paint dispatch ──────────────────────────────────────────────────────

    def paint(self, painter, option, index):
        book     = index.data(ROLE_BOOK)
        cover    = index.data(ROLE_COVER)
        hovered  = index.data(ROLE_HOVERED) or False
        show_rem = index.data(ROLE_SHOW_REM)
        if show_rem is None:
            show_rem = True
        live_pos = index.data(ROLE_LIVE_POS) or 0.0
        live_dur = index.data(ROLE_LIVE_DUR) or 0.0

        if book is None:
            return

        painter.save()
        painter.setClipRect(option.rect)

        if self._view_mode == "1 per row":
            self._paint_one_per_row(painter, option, index, book, cover, hovered, show_rem, live_pos, live_dur)
        elif self._view_mode == "2 per row":
            self._paint_two_per_row(painter, option, index, book, cover, hovered, show_rem, live_pos, live_dur)
        elif self._view_mode in ("3 per row", "Square"):
            self._paint_grid_cell(painter, option, index, book, cover, hovered, show_rem, live_pos, live_dur)
        elif self._view_mode == "List":
            self._paint_list_row(painter, option, index, book, hovered, show_rem, live_pos, live_dur)

        painter.restore()

    # ── editorEvent — toggle remaining/total on time label click ────────────

    def editorEvent(self, event, model, option, index):
        from PySide6.QtCore import QEvent as _QEvent
        if event.type() not in (_QEvent.Type.MouseButtonPress, _QEvent.Type.MouseButtonRelease):
            return False

        book = index.data(ROLE_BOOK)
        if not book:
            return False

        live_pos = index.data(ROLE_LIVE_POS) or 0.0
        live_dur = index.data(ROLE_LIVE_DUR) or 0.0
        if live_pos <= 0 or live_dur <= 0:
            return False

        hit = self._time_label_rect(option, index)
        if hit and hit.contains(event.pos()):
            if event.type() == _QEvent.Type.MouseButtonRelease:
                model.toggle_show_remaining(book.path)
                self.last_event_was_toggle = True
            return True
        return False

    # ── Playback resolution ──────────────────────────────────────────────────

    def _resolve_playback(self, book, live_pos: float, live_dur: float) -> tuple:
        """Returns (pos, dur, dur_disp, pct, has_progress, speed)"""
        has_progress = (book.progress or 0.0) > MIN_PROGRESS
        pos = live_pos if live_pos > 0 else (book.progress or 0.0)
        dur = live_dur if live_dur > 0 else (book.duration or 0.0)
        speed = book.speed or 1.0
        dur_disp = dur / speed
        pct = min(1.0, pos / dur) if has_progress and dur > 0 else 0.0
        return pos, dur, dur_disp, pct, has_progress, speed

    # ── Mode painters ───────────────────────────────────────────────────────

    def _paint_one_per_row(self, painter, option, index, book, cover, hovered, show_rem, live_pos, live_dur):
        r = option.rect

        painter.fillRect(r, self._row_one if index.row() % 2 == 0 else self._row_two)
        if hovered:
            painter.fillRect(r, self._hover_bg_color)

        # Cover (100×151, margins 4,4)
        cover_w, cover_h = 100, 151
        cover_rect = QRect(r.x() + 4, r.y() + 4, cover_w, cover_h)
        self._draw_cover(painter, cover_rect, cover, book, square=False)

        pos, dur, dur_disp, pct, has_progress, speed = self._resolve_playback(book, live_pos, live_dur)

        text_x = r.x() + 4 + cover_w + 8
        text_w = r.right() - text_x - 4

        # Zone 1 — bottom block, anchored to r.bottom()
        BAR_H  = 6
        PAD    = 4
        self._set_font(painter, mode=self._view_mode, field="elapsed")
        fm_time = painter.fontMetrics()
        bar_y  = r.bottom() - PAD - BAR_H
        time_y = bar_y - PAD - fm_time.height()

        # Zone 2 — text block fills space above bottom block
        text_y      = r.y() + PAD
        text_bottom = time_y - PAD

        fields = [("title", book.title or "")]
        if book.author:
            fields.append(("author", book.author))
        if book.narrator:
            fields.append(("narrator", book.narrator))
        if book.year:
            fields.append(("year", str(book.year)))

        available_h = text_bottom - text_y
        line_h      = available_h // len(fields) if fields else available_h

        color_map = {
            "title":    self._color_title,
            "author":   self._color_author,
            "narrator": self._color_narrator,
            "year":     self._color_author,
        }
        for field, value in fields:
            self._set_font(painter, mode=self._view_mode, field=field)
            fm = painter.fontMetrics()
            painter.setPen(color_map[field])
            painter.drawText(text_x, text_y + fm.ascent(), fm.elidedText(value, Qt.ElideRight, text_w))
            text_y += line_h -2

        # Bottom block
        HPAD = 4
        VPAD = 8
        bar_y  = r.bottom() - VPAD - BAR_H
        time_y = max(r.y() + PAD, bar_y - VPAD - fm_time.height())
        baseline     = time_y + fm_time.ascent() # vertical center against bar

        if has_progress:
            elapsed_str = self._fmt(pos / speed)
            right_str   = f"-{self._fmt((dur - pos) / speed)}" if show_rem else self._fmt(dur_disp)

            # Time row
            painter.setPen(self._color_elapsed)
            painter.drawText(text_x, baseline, elapsed_str)

            self._set_font(painter, mode=self._view_mode, field="total")
            fm_total = painter.fontMetrics()
            right_w  = fm_total.horizontalAdvance(right_str)
            painter.setPen(self._color_total)
            painter.drawText(r.right() - HPAD - right_w, baseline, right_str)

            # Bar row
            bar_rect = QRect(text_x, bar_y, 147, BAR_H)
            self._draw_progress_bar(painter, bar_rect, pct)

            # Percentage — same row as bar, right of bar
            pct_str = f"{int(pct * 100)}%"
            self._set_font(painter, mode=self._view_mode, field="percentage")
            fm_pct  = painter.fontMetrics()
            pct_y   = bar_y + (BAR_H - fm_pct.height()) // 2 + fm_pct.ascent()
            painter.setPen(self._color_pct)
            pct_w = fm_pct.horizontalAdvance(pct_str)
            painter.drawText(r.right() - HPAD - pct_w, pct_y, pct_str)
        else:
            # No progress — total time at bar row, right-aligned
            dur_str  = self._fmt(dur_disp)
            self._set_font(painter, mode=self._view_mode, field="total")
            fm_total = painter.fontMetrics()
            dur_w    = fm_total.horizontalAdvance(dur_str)
            no_prog_y = bar_y + (BAR_H - fm_total.height()) // 2 + fm_total.ascent()
            painter.setPen(self._color_total)
            painter.drawText(r.right() - HPAD - dur_w, no_prog_y, dur_str)

    def _paint_two_per_row(self, painter, option, index, book, cover, hovered, show_rem, live_pos, live_dur):
        r = option.rect
        painter.fillRect(r, self._grid_bg)

        # Cover (113×172, left margin 13, top 8)
        cover_x = r.x() + 13
        cover_y = r.y() + 8
        cover_w, cover_h = 113, 172
        cover_rect = QRect(cover_x, cover_y, cover_w, cover_h)
        self._draw_cover(painter, cover_rect, cover, book, square=False)

        # Title and author below cover
        text_x = cover_x
        text_w = cover_w - 14  # matching right margin from BookItem
        text_y = cover_y + cover_h + 2

        self._set_font(painter, mode=self._view_mode, field="title")
        fm = painter.fontMetrics()
        title_text = fm.elidedText(book.title or "", Qt.ElideRight, text_w)
        painter.setPen(self._color_title)
        painter.drawText(text_x, text_y + fm.ascent(), title_text)
        text_y += fm.height() + 2

        self._set_font(painter, mode=self._view_mode, field="author")
        fm = painter.fontMetrics()
        author_text = fm.elidedText(book.author or "", Qt.ElideRight, text_w)
        painter.setPen(self._color_author)
        painter.drawText(text_x, text_y + fm.ascent(), author_text)

        # Hover overlay over cover rect
        if hovered:
            self._draw_hover_overlay(painter, cover_rect, book, show_rem, live_pos, live_dur, large=True)

    def _paint_grid_cell(self, painter, option, index, book, cover, hovered, show_rem, live_pos, live_dur):
        r = option.rect
        painter.fillRect(r, self._grid_bg)
        square = (self._view_mode == "Square")

        # Cover fills cell with 2px margin
        cover_rect = QRect(r.x() + 2, r.y() + 2, r.width() - 4, r.height() - 4)
        self._draw_cover(painter, cover_rect, cover, book, square=square)

        if hovered:
            self._draw_hover_overlay(painter, cover_rect, book, show_rem, live_pos, live_dur, large=False)

    def _paint_list_row(self, painter, option, index, book, hovered, show_rem, live_pos, live_dur):
        r   = option.rect
        fm  = option.fontMetrics

        # Alternating row background, then hover on top
        painter.fillRect(r, self._row_one if index.row() % 2 == 0 else self._row_two)
        if hovered:
            painter.fillRect(r, self._hover_bg_color)

        if book.path == self._playing_path:
            painter.fillRect(QRect(r.x(), r.y(), ACTIVE_BOOK_STRIPE_WIDTH, r.height()), self._color_accent)

        pos, dur, dur_disp, pct, has_progress, speed = self._resolve_playback(book, live_pos, live_dur)

        # Time column width — derived from font, same rule as ListBookItem
        TIME_W    = fm.horizontalAdvance("-00:00:00") + 2
        LEFT_PAD  = 4
        RIGHT_PAD = 4
        AVAILABLE = option.rect.width() - LEFT_PAD - RIGHT_PAD - TIME_W

        AUTHOR_BASE = 100
        TITLE_CM    = 4
        BUFFER      = 4

        title  = book.title  or ""
        author = book.author or ""

        title_text_w  = fm.horizontalAdvance(title)
        author_text_w = fm.horizontalAdvance(author)

        author_w     = min(author_text_w + BUFFER, AUTHOR_BASE)
        title_max_lw = AVAILABLE - author_w

        if author_text_w + BUFFER > AUTHOR_BASE:
            spare        = max(0, title_max_lw - (title_text_w + TITLE_CM))
            author_w     = min(author_text_w + BUFFER, AUTHOR_BASE + spare)
            title_max_lw = AVAILABLE - author_w

        title_avail = title_max_lw - TITLE_CM

        ew = fm.horizontalAdvance("…")
        title_elided  = title_text_w  - title_avail >= ew
        author_elided = author_text_w - author_w    >= ew

        disp_title  = fm.elidedText(title,  Qt.ElideRight, title_avail) if title_elided  else title
        disp_author = fm.elidedText(author, Qt.ElideRight, author_w)    if author_elided else author

        # Layout geometry derived from option.rect
        left       = r.x() + LEFT_PAD + TITLE_CM
        mid        = left + title_avail
        right      = r.x() + LEFT_PAD + AVAILABLE
        title_rect = QRect(left, r.y(), title_max_lw +8, r.height()) # +8 prevents clipping with still some separation
        author_rect = QRect(mid, r.y(), author_w, r.height())
        time_rect  = QRect(right, r.y(), TIME_W, r.height())

        local_x       = self._hover_pos.x() - r.x()
        expand_title  = hovered and (left - r.x() <= local_x < mid - r.x()) and title_elided
        expand_author = hovered and (mid - r.x() <= local_x < right - r.x()) and author_elided
        full_rect     = QRect(left, r.y(), AVAILABLE - TITLE_CM, r.height())

        if expand_title:
            self._set_font(painter, mode=self._view_mode, field="title")
            painter.setPen(self._color_title)
            painter.drawText(full_rect, Qt.AlignLeft | Qt.AlignVCenter, title)
        elif expand_author:
            self._set_font(painter, mode=self._view_mode, field="author")
            painter.setPen(self._color_author)
            painter.drawText(full_rect, Qt.AlignRight | Qt.AlignVCenter, author)
        else:
            self._set_font(painter, mode=self._view_mode, field="title")
            painter.setPen(self._color_title)
            painter.drawText(title_rect, Qt.AlignLeft | Qt.AlignVCenter, disp_title)
            self._set_font(painter, mode=self._view_mode, field="author")
            painter.setPen(self._color_author)
            painter.drawText(author_rect, Qt.AlignRight | Qt.AlignVCenter, disp_author)

        # Time column — single value, right-aligned; toggle switches elapsed/remaining
        self._set_font(painter, mode=self._view_mode, field="total")
        painter.setPen(self._color_total)
        if has_progress:
            time_str = f"-{self._fmt((dur - pos) / speed)}" if show_rem else self._fmt(dur_disp)
        else:
            time_str = self._fmt(dur_disp)
        painter.drawText(time_rect, Qt.AlignRight | Qt.AlignVCenter, time_str)

    # ── Drawing helpers ─────────────────────────────────────────────────────

    def _draw_cover(self, painter, rect: QRect, cover, book, *, square: bool):
        # Background
        painter.fillRect(rect, QColor(13, 0, 26))

        if cover and not cover.isNull():
            if square:
                # Center-crop to fill rect
                src_w, src_h = cover.width(), cover.height()
                side = min(src_w, src_h)
                src_rect = QRect(
                    (src_w - side) // 2,
                    (src_h - side) // 2,
                    side, side
                )
                painter.drawPixmap(rect, cover, src_rect)
            else:
                # KeepAspectRatio — centre in rect
                pw, ph = cover.width(), cover.height()
                if pw > 0 and ph > 0:
                    scale = min(rect.width() / pw, rect.height() / ph)
                    dw = int(pw * scale)
                    dh = int(ph * scale)
                    dx = rect.x() + (rect.width() - dw) // 2
                    dy = rect.y() + (rect.height() - dh) // 2
                    painter.drawPixmap(QRect(dx, dy, dw, dh), cover, cover.rect())
        else:
            # Placeholder: first letter of title
            painter.setPen(QColor(180, 180, 180))
            f = QFont(painter.font())
            f.setPixelSize(painter.font().pixelSize() + 6 if painter.font().pixelSize() > 0
                           else painter.font().pointSize() + 6)
            f.setBold(True)
            painter.setFont(f)
            painter.drawText(rect, Qt.AlignCenter, (book.title or "?")[:1])

    def _draw_hover_overlay(self, painter, cover_rect: QRect, book, show_rem, live_pos, live_dur, *, large: bool):
        from PySide6.QtGui import QLinearGradient, QBrush

        pos, dur, dur_disp, pct, has_progress, speed = self._resolve_playback(book, live_pos, live_dur)

        overlay_mode = "2 per row" if large else "3 per row"

        # Measure content height to size overlay precisely
        BAR_H = 6
        HPAD  = 3
        VPAD  = 6

        self._set_font(painter, mode=overlay_mode, field="elapsed")
        fm_time = painter.fontMetrics()

        if has_progress:
            # time row + 2px gap + bar row, plus VPAD top and bottom
            oh = VPAD + fm_time.height() + 8 + BAR_H + VPAD
        else:
            # just bar-row height centred on total text, plus VPAD top and bottom
            self._set_font(painter, mode=overlay_mode, field="total")
            fm_total = painter.fontMetrics()
            oh = VPAD + max(BAR_H, fm_total.height()) + VPAD

        oh = max(oh, int(cover_rect.height() * 0.18))  # never shrink below ~18%
        overlay_rect = QRect(cover_rect.x(), cover_rect.bottom() - oh + 1, cover_rect.width(), oh)

        # Semi-transparent gradient background
        grad = QLinearGradient(overlay_rect.topLeft(), overlay_rect.bottomLeft())
        grad.setColorAt(0.0, QColor(0, 0, 0, 160))
        grad.setColorAt(1.0, QColor(0, 0, 0, 240))
        painter.fillRect(overlay_rect, QBrush(grad))

        inner = overlay_rect.adjusted(HPAD, VPAD, -HPAD, -VPAD)

        if has_progress:
            # Rows bottom-up: bar at inner.bottom(), time row above it
            bar_y  = inner.bottom() - BAR_H
            time_y = bar_y - 4 - fm_time.height()
            time_y = max(inner.y(), time_y)

            # Time row
            elapsed_str = self._fmt(pos / speed)
            right_str   = f"-{self._fmt((dur - pos) / speed)}" if show_rem else self._fmt(dur_disp)

            self._set_font(painter, mode=overlay_mode, field="elapsed")
            fm_time = painter.fontMetrics()
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(inner.x(), time_y + fm_time.ascent(), elapsed_str)

            self._set_font(painter, mode=overlay_mode, field="total")
            fm_total = painter.fontMetrics()
            right_w  = fm_total.horizontalAdvance(right_str)
            painter.drawText(inner.right() - right_w, time_y + fm_total.ascent(), right_str)

            # Bar + percentage on same row, percentage right-aligned
            pct_str = f"{int(pct * 100)}%"
            self._set_font(painter, mode=overlay_mode, field="percentage")
            fm_pct = painter.fontMetrics()
            pct_w  = fm_pct.horizontalAdvance(pct_str)
            bar_w  = max(10, inner.width() - pct_w - 4)
            bar_rect = QRect(inner.x(), bar_y, bar_w, BAR_H)
            self._draw_progress_bar(painter, bar_rect, pct)

            pct_y = bar_y + (BAR_H - fm_pct.height()) // 2 + fm_pct.ascent()
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(inner.right() - pct_w, pct_y, pct_str)

        else:
            # No progress — total duration vertically centred in inner, right-aligned
            self._set_font(painter, mode=overlay_mode, field="total")
            fm_total = painter.fontMetrics()
            dur_str   = self._fmt(dur_disp)
            dur_w     = fm_total.horizontalAdvance(dur_str)
            no_prog_y = inner.y() + (inner.height() - fm_total.height()) // 2 + fm_total.ascent() + 2
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(inner.right() - dur_w, no_prog_y, dur_str)

    def _draw_progress_bar(self, painter, rect: QRect, pct: float):
        # Background track
        painter.fillRect(rect, QColor(self._pg_bg))
        # Fill
        fill_w = int(rect.width() * pct)
        if fill_w > 0:
            fill_rect = QRect(rect.x(), rect.y(), fill_w, rect.height())
            painter.fillRect(fill_rect, QColor(self._pg_fill))

    # ── Utilities ───────────────────────────────────────────────────────────

    def _time_label_rect(self, option, index) -> "QRect | None":
        """Returns the hit-testable rect for the time/remaining label."""
        if self._view_mode == "1 per row":
            r = option.rect
            # Right side of the time row, matching _paint_one_per_row layout
            fm_h = 20  # approximate
            y = r.bottom() - 4 - 6 - 4 - fm_h
            return QRect(r.right() - 70, r.y() + y - r.y(), 66, fm_h)
        elif self._view_mode in ("2 per row", "3 per row", "Square"):
            # Approximate overlay height: VPAD(5) + time_row(~16) + 2 + bar(6) + VPAD(5) = ~34px
            r = option.rect
            cover_rect = self._cover_rect(r)
            oh = 34
            overlay_rect = QRect(cover_rect.x(), cover_rect.bottom() - oh + 1, cover_rect.width(), oh)
            # Hit zone: the time row at the top of inner (VPAD=5 inset)
            return QRect(overlay_rect.x(), overlay_rect.y() + 5, overlay_rect.width(), 20)
        elif self._view_mode == "List":
            r      = option.rect
            fm     = option.fontMetrics
            time_w = fm.horizontalAdvance("-00:00:00") + 2
            return QRect(r.right() - 4 - time_w, r.y(), time_w, r.height())
        return None

    def _cover_rect(self, r: QRect) -> QRect:
        if self._view_mode == "1 per row":
            return QRect(r.x() + 4, r.y() + 4, 100, 151)
        elif self._view_mode == "2 per row":
            return QRect(r.x() + 13, r.y() + 8, 113, 172)
        else:
            return QRect(r.x() + 2, r.y() + 2, r.width() - 4, r.height() - 4)

    @staticmethod
    def _fmt(seconds: float) -> str:
        s = int(seconds or 0)
        return f"{s // 3600}:{(s % 3600) // 60:02}:{s % 60:02}"

    @staticmethod
    def _set_font(painter, *, mode: str, field: str):
        size, bold = FONT_SIZES.get(mode, {}).get(field, (13, False))
        f = QFont(painter.font())
        f.setPixelSize(size)
        f.setBold(bold)
        painter.setFont(f)


class ListBookItem(QWidget):
    clicked           = Signal(str)
    context_requested = Signal(str)

    _AVAILABLE   = 218
    _AUTHOR_BASE = 100
    _TITLE_CM    = 4
    _BUFFER      = 4

    def __init__(self, hover_bg_color: QColor = None, alt_row: bool = False, parent=None):
        super().__init__(parent)
        self._hover_bg_color = hover_bg_color or QColor(80, 80, 80, 180)
        self._alt_row        = alt_row
        self._show_remaining = True
        self._title_elided   = False
        self._author_elided  = False
        self._book           = None
        self._is_toggling    = False
        self._pos            = 0.0
        self._dur            = 0.0

        self.setFixedHeight(28)
        self.setCursor(Qt.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 0, 0)
        layout.setSpacing(0)

        self.title_label = QLabel()
        self.title_label.setObjectName("book_item_title")
        self.title_label.setStyleSheet("font-size: 14px;")
        self.title_label.setContentsMargins(4, 0, 0, 0)

        self.author_label = QLabel()
        self.author_label.setObjectName("book_item_author")
        self.author_label.setStyleSheet("font-size: 14px;")
        self.author_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.author_label.setContentsMargins(0, 0, 0, 0)

        self.time_label = QLabel()
        self.time_label.setObjectName("book_item_total")
        self.time_label.setStyleSheet("font-size: 14px;")
        self.time_label.setFixedWidth(46)  # placeholder until first bind polishes the font
        self.time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.time_label.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(self.title_label)
        layout.addStretch()
        layout.addWidget(self.author_label)
        layout.addWidget(self.time_label)

    # ── Public API ──────────────────────────────────────────────────────────

    def bind(self, book, position: float, duration: float):
        self._book           = book
        self._pos            = float(position or 0.0)
        self._dur            = float(duration  or 0.0)
        self._show_remaining = True

        elision = self._calculate_elision(book.title or "", book.author or "")
        self.title_label.setText(elision["title"])
        self.author_label.setText(elision["author"])
        self.author_label.setFixedWidth(max(1, elision["author_width"]))
        self._title_elided  = elision["title_elided"]
        self._author_elided = elision["author_elided"]

        self._resize_time_label()
        self._refresh_time()

    def update_progress(self, position: float, duration: float):
        self._pos = float(position or 0.0)
        self._dur = float(duration  or 0.0)
        self._refresh_time()

    # ── Elision ─────────────────────────────────────────────────────────────

    def _calculate_elision(self, title: str, author: str) -> dict:
        self.ensurePolished()
        fm_t = self.title_label.fontMetrics()
        fm_a = self.author_label.fontMetrics()

        title_text_w  = fm_t.horizontalAdvance(title)
        author_text_w = fm_a.horizontalAdvance(author)

        author_w     = min(author_text_w + self._BUFFER, self._AUTHOR_BASE)
        title_max_lw = self._AVAILABLE - author_w

        if author_text_w + self._BUFFER > self._AUTHOR_BASE:
            spare        = max(0, title_max_lw - (title_text_w + self._TITLE_CM))
            author_w     = min(author_text_w + self._BUFFER, self._AUTHOR_BASE + spare)
            title_max_lw = self._AVAILABLE - author_w

        title_avail = title_max_lw - self._TITLE_CM
        ew_t = fm_t.horizontalAdvance("…")
        ew_a = fm_a.horizontalAdvance("…")

        disp_title  = title  if title_text_w  - title_avail < ew_t else fm_t.elidedText(title,  Qt.ElideRight, title_avail)
        disp_author = author if author_text_w  - author_w   < ew_a else fm_a.elidedText(author, Qt.ElideRight, author_w)

        return {
            "title":        disp_title,
            "author":       disp_author,
            "author_width": author_w,
            "title_elided":  disp_title  != title,
            "author_elided": disp_author != author,
        }

    # ── Time display ────────────────────────────────────────────────────────

    @staticmethod
    def _fmt(seconds: float) -> str:
        s = int(seconds or 0)
        return f"{s // 3600}:{(s % 3600) // 60:02}:{s % 60:02}"

    def _resize_time_label(self):
        self.ensurePolished()
        fm = self.time_label.fontMetrics()
        self.time_label.setFixedWidth(fm.horizontalAdvance("-00:00:00") + 2)

    def _refresh_time(self):
        pos, dur = self._pos, self._dur
        if pos > 0 and dur > 0:
            if self._show_remaining:
                self.time_label.setText(f"-{self._fmt(dur - pos)}")
            else:
                self.time_label.setText(self._fmt(dur))
        else:
            self.time_label.setText(self._fmt(dur))

    # ── Events ───────────────────────────────────────────────────────────────

    def enterEvent(self, event):
        if self._title_elided:
            self.author_label.hide()
            self.title_label.setText(self._book.title if self._book else "")
        elif self._author_elided:
            self.title_label.hide()
            self.author_label.setFixedWidth(self._AVAILABLE)
            self.author_label.setText(self._book.author if self._book else "")
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.title_label.show()
        self.author_label.show()
        if self._book:
            elision = self._calculate_elision(self._book.title or "", self._book.author or "")
            self.title_label.setText(elision["title"])
            self.author_label.setText(elision["author"])
            self.author_label.setFixedWidth(max(1, elision["author_width"]))
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        self._is_toggling = False
        if event.button() == Qt.LeftButton:
            if self._pos > 0 and self._dur > 0:
                # Safe zone for list toggle: the right 80px containing the time label
                if event.position().x() > self.width() - 80:
                    self._is_toggling = True
                    self._show_remaining = not self._show_remaining
                    self._refresh_time()
                    event.accept()
                    return
        elif event.button() == Qt.RightButton:
            if self._book:
                self.context_requested.emit(self._book.path)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self._is_toggling:
                self._is_toggling = False
                event.accept()
                return
            if self._book:
                self.clicked.emit(self._book.path)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        from PySide6.QtGui import QPainter
        painter = QPainter(self)
        if self._alt_row:
            painter.fillRect(self.rect(), QColor(255, 255, 255, 10))
        if self.underMouse():
            painter.fillRect(self.rect(), self._hover_bg_color)
        painter.end()
        super().paintEvent(event)