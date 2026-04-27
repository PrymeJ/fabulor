import os
import time
import math
import random
from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QGridLayout, QScrollArea, QFrame, QSizePolicy, QApplication, QPushButton, QHBoxLayout, QComboBox, QLineEdit, QProgressBar, QStyledItemDelegate
)
from PySide6.QtCore import QThreadPool, QEvent
from PySide6.QtCore import Qt, Signal, QCoreApplication, QRect
from PySide6.QtGui import QPixmap, QColor

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
    "1 per row": {"w": 292, "h": 161, "cols": 1},
    "List":      {"w": 290, "h": 28,  "cols": 1}
}

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
    book_selected = Signal(str)
    back_requested = Signal() # Signal to request closing the panel

    def __init__(self, db, config, player_instance=None, parent=None):
        super().__init__(parent)
        self.db = db
        self.config = config
        self.player_instance = player_instance
        
        # Virtual Pool Configuration
        self._pool_size = 30 # Default buffer
        self._pool = []
        self._books_cache = []
        self._last_book_list = []
        self._filtered_books = []
        self._pixmap_cache = {}
        
        self._data_initialized = False
        self._ignore_scroll = False
        self._active_workers = set()

        self._setup_ui()
        self._resolve_theme_colors()
        self._setup_pool()

    def _resolve_theme_colors(self):
        from ..themes import THEMES
        main_win = self.parent() if hasattr(self.parent(), 'theme_manager') else self.window()
        if main_win and hasattr(main_win, 'theme_manager'):
            t = THEMES.get(main_win.theme_manager._current_theme_name, THEMES["The Color Purple"])
            self._pg_bg = t.get('library_slider_bg', t['slider_overall_bg'])
            self._pg_fill = t.get('library_slider_fill', t['slider_overall_fill'])
            hc = t.get('library_item_hover_color', t['accent'])
            ha = t.get('library_item_hover_alpha', 0.50)
            r, g, b = int(hc[1:3], 16), int(hc[3:5], 16), int(hc[5:7], 16)
            self._hover_bg_color = QColor(r, g, b, int(ha * 255))

    def update_progress_bar_theme(self):
        self._resolve_theme_colors()
        for item in self._pool:
            if hasattr(item, 'overlay_progress_bar'):
                item.overlay_progress_bar.setStyleSheet(f"""
                    QProgressBar {{
                        background-color: {self._pg_bg};
                        border: none;
                        border-radius: 0px;
                    }}
                    QProgressBar::chunk {{
                        background-color: {self._pg_fill};
                        border: none;
                        border-radius: 0px;
                    }}
                """)
        qc = getattr(self, '_hover_bg_color', QColor(80, 80, 80, 180))
        for item in self._pool:
            item._hover_bg_color = qc

    def _setup_pool(self):
        """Creates the fixed widget pool and sets container to manual positioning."""
        # Clear existing
        for w in self._pool:
            w.deleteLater()
        self._pool.clear()

        mode = self.style_combo.currentData()
        for _ in range(self._pool_size):
            item = BookItem(
                view_mode=mode,
                player_instance=self.player_instance,
                pg_bg=self._pg_bg,
                pg_fill=self._pg_fill,
                hover_bg_color=getattr(self, '_hover_bg_color', QColor(80, 80, 80, 180)),
                parent=self.container
            )
            item.clicked.connect(self.book_selected.emit)
            item.hide()
            self._pool.append(item)

    def _update_viewport(self):
        """Repositions and rebinds pool widgets based on scroll position."""
        if not self._data_initialized or self._ignore_scroll:
            return

        mode = self.style_combo.currentData()
        dim = ITEM_DIMENSIONS[mode]
        item_h, cols = dim['h'], dim['cols']

        # Horizontal offset to balance the grid within the viewport
        offset_x = 0
        if mode == "2 per row":
            offset_x = 7
        
        scroll_y = self.scroll.verticalScrollBar().value()
        viewport_h = self.scroll.height()
        
        start_row = max(0, scroll_y // item_h)
        end_row = (scroll_y + viewport_h) // item_h + 1
        
        start_idx = start_row * cols
        end_idx = end_row * cols
        
        self.container.setUpdatesEnabled(False)
        
        pool_idx = 0
        data_count = len(self._filtered_books)
        
        for i in range(start_idx, end_idx):
            if pool_idx >= len(self._pool) or i >= data_count:
                break
                
            widget = self._pool[pool_idx]
            book = self._filtered_books[i]
            
            # Alternate row styling for lists
            if mode in ("1 per row", "List"):
                widget.setProperty("alt_row", str(i % 2))
                widget.style().unpolish(widget)
                widget.style().polish(widget)

            # Bind Data
            path_changed = widget.bind(book)
            
            # Handle Pixmap Cache
            if hasattr(widget, 'cover_label'):
                path = book.path
                if path in self._pixmap_cache:
                    widget.set_cover(self._pixmap_cache[path])
                elif path_changed or not widget.cover_label.pixmap():
                    widget.cover_label.setPixmap(QPixmap())
                    self._trigger_cover_load(book, widget)

            # Position
            row, col = i // cols, i % cols
            widget.move(offset_x + (col * dim['w']), row * item_h)
            widget.show()
            pool_idx += 1

        # Hide remaining pool
        for i in range(pool_idx, len(self._pool)):
            self._pool[i].hide()
            
        self.container.setUpdatesEnabled(True)

    def _rotate_view_mode_labels(self):
        self.style_combo.blockSignals(True)
        for i, (_, options) in enumerate(VIEW_MODES):
            self.style_combo.setItemText(i, random.choice(options))
        self.style_combo.blockSignals(False)

    def hideEvent(self, event):
        super().hideEvent(event)
        self._rotate_view_mode_labels()

    def refresh(self, force=False):
        self._resolve_theme_colors()
        new_books = self.db.get_all_books(sort_by="title", order="ASC")
        self._data_initialized = True

        if force:
            self._books_cache = new_books
            self._last_book_list = new_books
            if not self.isVisible():
                return
            self._on_search_changed(self.search_field.text())
            return

        rendered_by_path = {w.current_path: w for w in self._pool if w.current_path}
        rendered_paths = set(rendered_by_path)
        new_by_path = {b.path: b for b in new_books}
        new_paths = set(new_by_path)

        added   = new_paths - rendered_paths
        removed = rendered_paths - new_paths
        changed = {
            path for path in rendered_paths & new_paths
            if rendered_by_path[path].book_data != new_by_path[path]
        }

        self._last_book_list = new_books

        if not added and not removed and not changed:
            return

        self._books_cache = new_books

        if not added and not removed:
            if self.isVisible():
                for w in self._pool:
                    if w.current_path in changed:
                        w.bind(new_by_path[w.current_path])
            return

        if not self.isVisible():
            return
        self._on_search_changed(self.search_field.text())

    def _trigger_cover_load(self, book, widget):
        cover_path = book.path
        if cover_path in self._pixmap_cache:
            pixmap = self._pixmap_cache[cover_path]
            if widget.current_path == cover_path:
                widget.set_cover(pixmap)
            return
        from .cover_loader import CoverLoaderWorker
        worker = CoverLoaderWorker(book, self.player_instance)
        self._active_workers.add(worker)
        worker.signals.cover_loaded.connect(lambda p, pix, w=widget: self._on_cover_loaded(p, pix, w))
        worker.signals.finished.connect(lambda w=worker: self._active_workers.discard(w))
        QThreadPool.globalInstance().start(worker)

    def _on_cover_loaded(self, path, pixmap, widget):
        if not pixmap.isNull():
            dpr = self.screen().devicePixelRatio() if self.screen() else 1.0
            pixmap.setDevicePixelRatio(dpr)
            self._pixmap_cache[path] = pixmap
            if widget.current_path == path:
                widget.set_cover(pixmap)
        
        if widget.current_path == path:
            widget.set_cover(pixmap)

    def _on_view_mode_changed(self, _):
        start_time = time.perf_counter()
        mode = self.style_combo.currentData()
        self.config.set_library_view_mode(mode)
        self._resolve_theme_colors()
        
        self.container.setUpdatesEnabled(False) # Batch the massive UI rebuild
        BookItem._total_clear_time = 0.0
        loop_start = time.perf_counter()
        for item in self._pool:
            item.set_view_mode(mode)
        loop_dur = (time.perf_counter() - loop_start) * 1000

        self._sort_items_in_place()
        self.update_progress_bar_theme()
        self.container.setUpdatesEnabled(True)

        duration = (time.perf_counter() - start_time) * 1000
        print(f"[DEBUG] _clear_layout total: {BookItem._total_clear_time * 1000:.2f}ms")
        print(f"[DEBUG] set_view_mode loop: {loop_dur:.2f}ms")
        print(f"[DEBUG] View mode change to '{mode}' took {duration:.2f}ms")

    def _setup_ui(self):
        # Moved UI setup logic here for cleaner __init__
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
        for display, key in [("Title", "Title"), ("Author", "Author"), ("Recent", "Last Played"), ("Progress", "Progress"), ("Duration", "Duration"), ("Year", "Year")]:
            self.sort_combo.addItem(display, key)
        self.sort_combo.setFixedWidth(65)
        self.sort_combo.setFixedHeight(30)
        saved_sort = self.config.get_library_sort_key()
        for i in range(self.sort_combo.count()):
            if self.sort_combo.itemData(i) == saved_sort:
                self.sort_combo.setCurrentIndex(i)
                break
        self._sort_ascending = self.config.get_library_sort_ascending()
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

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.verticalScrollBar().valueChanged.connect(self._update_viewport)
        
        self.container = QWidget()
        self.container.setObjectName("library_scroll_contents")
        # Virtual scrolling uses absolute positioning; Grid layout is removed
        self.scroll.setWidget(self.container)
        self.main_layout.addWidget(self.scroll)

    def _toggle_sort_direction(self):
        self._sort_ascending = not getattr(self, '_sort_ascending', True)
        self.sort_dir_btn.setText("↑" if self._sort_ascending else "↓")
        self._sort_items_in_place(ascending=self._sort_ascending)

    def _on_sort_changed(self):
        sort_text = self.sort_combo.currentData()
        if sort_text == "Last Played" or self._last_filter_mode == "Last Played":
            self.refresh(force=True)
        else:
            self._sort_items_in_place(reset_scroll=True)
        self._last_filter_mode = sort_text

    def _on_search_changed(self, text):
        text = text.lower().strip()
        if not text:
            self._filtered_books = list(self._books_cache)
        else:
            self._filtered_books = [
                b for b in self._books_cache
                if text in (b.title or '').lower() or
                   text in (b.author or '').lower()
            ]
        self._sort_items_in_place(reset_scroll=True)

    def _sort_items_in_place(self, ascending=None, reset_scroll=False):
        start_time = time.perf_counter()
        # Toggle direction if called from button, otherwise keep current
        if ascending is None:
            ascending = getattr(self, '_sort_ascending', True)
        self._sort_ascending = ascending

        sort_text = self.sort_combo.currentData()
        self.config.set_library_sort_key(sort_text)
        self.config.set_library_sort_ascending(ascending)

        sort_key = sort_text.lower().replace(" ", "_")
        numeric_keys = {"progress", "duration", "year"}
        datetime_keys = {"last_played", "date_added"}

        if sort_key == "last_played":
            self._filtered_books = [b for b in self._filtered_books if b.progress > 0]

        def sort_value(book):
            val = getattr(book, sort_key, None)
            if val is None:
                return (1, 0 if sort_key in numeric_keys else "")
            if sort_key == "progress":
                duration = book.duration or 1
                return (0, float(val) / float(duration))
            if sort_key in numeric_keys:
                return (0, float(val))
            if sort_key in datetime_keys:
                return (0, str(val))
            return (0, str(val).lower())

        if sort_key == "progress":
            has_val = [b for b in self._filtered_books if b.progress > 0]
            no_val  = [b for b in self._filtered_books if not b.progress > 0]
        else:
            has_val = [b for b in self._filtered_books if getattr(b, sort_key, None) is not None]
            no_val  = [b for b in self._filtered_books if getattr(b, sort_key, None) is None]

        self._filtered_books = sorted(
            has_val,
            key=sort_value,
            reverse=not ascending
        ) + sorted(no_val, key=sort_value)

        # Update Logical Scroll Height
        dim = ITEM_DIMENSIONS[self.style_combo.currentData()]
        rows = math.ceil(len(self._filtered_books) / dim['cols'])
        self.container.setFixedHeight(rows * dim['h'])
        
        if reset_scroll:
            self._ignore_scroll = True
            self.scroll.verticalScrollBar().setValue(0)
            self._ignore_scroll = False
            
        self._update_viewport()
        duration = (time.perf_counter() - start_time) * 1000
        print(f"[DEBUG] Sort/Filter (key: {sort_text}, ascending: {ascending}) took {duration:.2f}ms")

    def update_current_book_progress(self):
        """Live update for the currently playing book's progress and sorting."""
        if getattr(self, '_is_animating', False):
            return

        # Model/view path (Stage 6+): push live pos/dur into BookModel so
        # dataChanged fires and BookDelegate repaints only the affected cell.
        if hasattr(self, '_book_model') and self.player_instance:
            path = getattr(self.player_instance.instance, 'path', None) if self.player_instance.instance else None
            pos  = self.player_instance.time_pos or 0.0
            dur  = self.player_instance.duration or 0.0
            if path and dur > 0:
                self._book_model.update_playing_progress(path, pos, dur)

        # Pool-based path (active until Stage 6 removes the pool).
        if self.sort_combo.currentData() == "Progress":
            self._sort_items_in_place()
        else:
            self._update_viewport()

    def _on_view_entered(self, index):
        """Slot for QListView.entered — tracks hovered book in BookModel."""
        if not hasattr(self, '_book_model'):
            return
        book = index.data(ROLE_BOOK)
        self._book_model.set_hovered(book.path if book else None)

    def _on_view_left(self):
        """Called when the cursor leaves the QListView — clears hover state."""
        if hasattr(self, '_book_model'):
            self._book_model.set_hovered(None)


# Role constants (mirrors BookModel — defined here so delegate has no cross-module dep)
ROLE_BOOK     = Qt.UserRole + 0
ROLE_COVER    = Qt.UserRole + 1
ROLE_HOVERED  = Qt.UserRole + 2
ROLE_SHOW_REM = Qt.UserRole + 3
ROLE_LIVE_POS = Qt.UserRole + 4
ROLE_LIVE_DUR = Qt.UserRole + 5


class BookDelegate(QStyledItemDelegate):
    """
    QStyledItemDelegate for the model/view library rewrite.
    Accepts theme colors as constructor arguments; never resolves them itself.
    """

    def __init__(self, pg_bg: str, pg_fill: str, hover_bg_color: QColor, parent=None):
        super().__init__(parent)
        self._pg_bg = pg_bg
        self._pg_fill = pg_fill
        self._hover_bg_color = hover_bg_color
        self._view_mode = "3 per row"

    # ── Public API ──────────────────────────────────────────────────────────

    def set_view_mode(self, mode: str) -> None:
        self._view_mode = mode

    def sizeHint(self, option, index):
        from PySide6.QtCore import QSize
        dim = ITEM_DIMENSIONS.get(self._view_mode, ITEM_DIMENSIONS["3 per row"])
        return QSize(dim["w"], dim["h"])

    # ── Paint dispatch ──────────────────────────────────────────────────────

    def paint(self, painter, option, index):
        if self._view_mode == "List":
            return  # List mode uses widgets; delegate does not paint

        book     = index.data(ROLE_BOOK)
        cover    = index.data(ROLE_COVER)   # QPixmap or None
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

        painter.restore()

    # ── editorEvent — toggle remaining/total on time label click ────────────

    def editorEvent(self, event, model, option, index):
        from PySide6.QtCore import QEvent as _QEvent
        if event.type() != _QEvent.Type.MouseButtonRelease:
            return False
        if self._view_mode == "List":
            return False

        book     = index.data(ROLE_BOOK)
        live_pos = index.data(ROLE_LIVE_POS) or 0.0
        live_dur = index.data(ROLE_LIVE_DUR) or 0.0
        if not book or live_pos <= 0 or live_dur <= 0:
            return False

        hit = self._time_label_rect(option, index)
        if hit and hit.contains(event.pos()):
            model.toggle_show_remaining(book.path)
            return True
        return False

    # ── Mode painters ───────────────────────────────────────────────────────

    def _paint_one_per_row(self, painter, option, index, book, cover, hovered, show_rem, live_pos, live_dur):
        r = option.rect

        # Row hover highlight
        if hovered:
            painter.fillRect(r, self._hover_bg_color)

        # Cover (100×151, margins 4,4)
        cover_w, cover_h = 100, 151
        cover_rect = QRect(r.x() + 4, r.y() + 4, cover_w, cover_h)
        self._draw_cover(painter, cover_rect, cover, book, square=False)

        # Text area starts right of cover
        text_x = r.x() + 4 + cover_w + 8
        text_w = r.right() - text_x - 4
        text_y = r.y() + 4

        fm = painter.fontMetrics()
        line_h = fm.height() + 2

        pos  = live_pos if live_pos > 0 else (book.progress or 0.0)
        dur  = live_dur if live_dur > 0 else (book.duration or 0.0)
        has_progress = pos > 0 and dur > 0
        pct  = min(1.0, pos / dur) if has_progress else 0.0

        # Title
        title_text = fm.elidedText(book.title or "", Qt.ElideRight, text_w)
        painter.setPen(option.palette.text().color())
        self._set_font(painter, bold=True, size_delta=0)
        painter.drawText(text_x, text_y + painter.fontMetrics().ascent(), title_text)
        text_y += line_h

        self._set_font(painter, bold=False, size_delta=-1)
        fm = painter.fontMetrics()
        line_h = fm.height() + 2

        # Author
        author_text = fm.elidedText(book.author or "", Qt.ElideRight, text_w)
        painter.setPen(option.palette.text().color())
        painter.drawText(text_x, text_y + fm.ascent(), author_text)
        text_y += line_h

        # Narrator
        if book.narrator:
            narrator_text = fm.elidedText(book.narrator, Qt.ElideRight, text_w)
            painter.drawText(text_x, text_y + fm.ascent(), narrator_text)
            text_y += line_h

        # Year
        if book.year:
            painter.drawText(text_x, text_y + fm.ascent(), str(book.year))
            text_y += line_h

        # Times
        time_y = r.bottom() - 4 - 6 - 4 - fm.height()  # bar below, then time row above
        if has_progress:
            elapsed_str = self._fmt(pos)
            if show_rem:
                right_str = f"-{self._fmt(dur - pos)}"
            else:
                right_str = self._fmt(dur)
            painter.drawText(text_x, time_y + fm.ascent(), elapsed_str)
            right_w = fm.horizontalAdvance(right_str)
            painter.drawText(r.right() - 4 - right_w, time_y + fm.ascent(), right_str)

            # Progress bar (132px wide, 6px tall)
            bar_y = r.bottom() - 4 - 6
            bar_rect = QRect(text_x, bar_y, 132, 6)
            self._draw_progress_bar(painter, bar_rect, pct)

            # Percentage label
            pct_str = f"{int(pct * 100)}%"
            painter.drawText(bar_rect.right() + 8, bar_y + fm.ascent(), pct_str)
        else:
            # No progress: show total duration only
            dur_str = self._fmt(dur)
            painter.drawText(text_x, time_y + fm.ascent(), dur_str)

    def _paint_two_per_row(self, painter, option, index, book, cover, hovered, show_rem, live_pos, live_dur):
        r = option.rect

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
        fm = painter.fontMetrics()

        self._set_font(painter, bold=False, size_delta=-1)
        fm = painter.fontMetrics()

        title_text = fm.elidedText(book.title or "", Qt.ElideRight, text_w)
        painter.setPen(option.palette.text().color())
        painter.drawText(text_x, text_y + fm.ascent(), title_text)
        text_y += fm.height() + 2

        author_text = fm.elidedText(book.author or "", Qt.ElideRight, text_w)
        painter.drawText(text_x, text_y + fm.ascent(), author_text)

        # Hover overlay over cover rect
        if hovered:
            self._draw_hover_overlay(painter, cover_rect, book, show_rem, live_pos, live_dur, large=True)

    def _paint_grid_cell(self, painter, option, index, book, cover, hovered, show_rem, live_pos, live_dur):
        r = option.rect
        square = (self._view_mode == "Square")

        # Cover fills cell with 2px margin
        cover_rect = QRect(r.x() + 2, r.y() + 2, r.width() - 3, r.height() - 4)
        self._draw_cover(painter, cover_rect, cover, book, square=square)

        if hovered:
            self._draw_hover_overlay(painter, cover_rect, book, show_rem, live_pos, live_dur, large=False)

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
            self._set_font(painter, bold=True, size_delta=6)
            painter.drawText(rect, Qt.AlignCenter, (book.title or "?")[:1])

    def _draw_hover_overlay(self, painter, cover_rect: QRect, book, show_rem, live_pos, live_dur, *, large: bool):
        from PySide6.QtGui import QLinearGradient, QBrush

        pos = live_pos if live_pos > 0 else (book.progress or 0.0)
        dur = live_dur if live_dur > 0 else (book.duration or 0.0)
        has_progress = pos > 0 and dur > 0
        pct = min(1.0, pos / dur) if has_progress else 0.0

        # Overlay height: 30% of cover if has_progress, else 20%
        pct_h = 0.30 if has_progress else 0.20
        oh = int(cover_rect.height() * pct_h)
        overlay_rect = QRect(cover_rect.x(), cover_rect.bottom() - oh + 1, cover_rect.width(), oh)

        # Semi-transparent gradient background
        grad = QLinearGradient(overlay_rect.topLeft(), overlay_rect.bottomLeft())
        grad.setColorAt(0.0, QColor(0, 0, 0, 100))
        grad.setColorAt(1.0, QColor(0, 0, 0, 230))
        painter.fillRect(overlay_rect, QBrush(grad))

        font_size = 14 if large else 12
        self._set_font(painter, bold=False, size_delta=0, absolute_size=font_size)
        fm = painter.fontMetrics()
        painter.setPen(QColor(255, 255, 255))

        pad = 4
        inner = overlay_rect.adjusted(pad, pad, -pad, -pad)
        y = inner.y()

        if has_progress:
            # Time row: elapsed left, remaining/total right
            elapsed_str = self._fmt(pos)
            right_str = f"-{self._fmt(dur - pos)}" if show_rem else self._fmt(dur)
            right_w = fm.horizontalAdvance(right_str)
            painter.drawText(inner.x(), y + fm.ascent(), elapsed_str)
            painter.drawText(inner.right() - right_w, y + fm.ascent(), right_str)
            y += fm.height() + 2

            # Progress bar + percentage
            pct_str = f"{int(pct * 100)}%"
            pct_w = fm.horizontalAdvance(pct_str) + 4
            bar_rect = QRect(inner.x(), y, inner.width() - pct_w, 6)
            self._draw_progress_bar(painter, bar_rect, pct)
            painter.drawText(bar_rect.right() + 4, y + fm.ascent(), pct_str)
        else:
            # No progress: just show total duration right-aligned
            dur_str = self._fmt(dur)
            dur_w = fm.horizontalAdvance(dur_str)
            painter.drawText(inner.right() - dur_w, y + fm.ascent(), dur_str)

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
            fm_h = 14  # approximate
            y = r.bottom() - 4 - 6 - 4 - fm_h
            return QRect(r.right() - 70, r.y() + y - r.y(), 66, fm_h)
        elif self._view_mode in ("2 per row", "3 per row", "Square"):
            # The overlay's right-side time label occupies the right half of the overlay
            r = option.rect
            cover_rect = self._cover_rect(r)
            oh = int(cover_rect.height() * 0.30)
            overlay_rect = QRect(cover_rect.x(), cover_rect.bottom() - oh + 1, cover_rect.width(), oh)
            return QRect(overlay_rect.x() + overlay_rect.width() // 2,
                         overlay_rect.y() + 4,
                         overlay_rect.width() // 2 - 4,
                         14)
        return None

    def _cover_rect(self, r: QRect) -> QRect:
        if self._view_mode == "1 per row":
            return QRect(r.x() + 4, r.y() + 4, 100, 151)
        elif self._view_mode == "2 per row":
            return QRect(r.x() + 13, r.y() + 8, 113, 172)
        else:
            return QRect(r.x() + 2, r.y() + 2, r.width() - 3, r.height() - 4)

    @staticmethod
    def _fmt(seconds: float) -> str:
        s = int(seconds or 0)
        return f"{s // 3600}:{(s % 3600) // 60:02}:{s % 60:02}"

    @staticmethod
    def _set_font(painter, *, bold: bool = False, size_delta: int = 0, absolute_size: int = 0):
        from PySide6.QtGui import QFont
        f = QFont(painter.font())
        if absolute_size:
            f.setPixelSize(absolute_size)
        elif size_delta:
            current = f.pixelSize()
            if current < 0:
                current = f.pointSize()
                f.setPointSize(max(6, current + size_delta))
            else:
                f.setPixelSize(max(6, current + size_delta))
        f.setBold(bold)
        painter.setFont(f)