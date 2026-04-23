import os
import time
import math
import random
from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QGridLayout, QScrollArea, QFrame, QSizePolicy, QApplication, QPushButton, QHBoxLayout, QComboBox, QLineEdit, QProgressBar
)
from PySide6.QtCore import QThread, QThreadPool # Added QThreadPool
from PySide6.QtCore import Qt, Signal, QCoreApplication, QRect
from PySide6.QtGui import QPixmap

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

    def __init__(self, view_mode="3 per row", player_instance=None, pg_bg=None, pg_fill=None, parent=None):
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
        self.setCursor(Qt.PointingHandCursor)
        
        self._build_ui()
        self._is_building_ui = False

    # ---------------- UI BUILD ----------------
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
        self._clear_layout()

        mode = self.view_mode

        # -------- 3 PER ROW --------
        if mode == "3 per row":
            self.setFixedSize(96,146)
            layout = QVBoxLayout(self)
            layout.setContentsMargins(2,2,1,2)
            layout.setSpacing(0)

            self.cover_label = self._make_cover(92,142)
            layout.addWidget(self.cover_label)

        # -------- SQUARE --------
        elif mode == "Square":
            self.setFixedSize(96,96)
            layout = QVBoxLayout(self)
            layout.setContentsMargins(2,2,1,2)
            layout.setSpacing(0)

            self.cover_label = self._make_cover(92,92)
            layout.addWidget(self.cover_label)

        # -------- 2 PER ROW --------
        elif mode == "2 per row":
            self.setFixedSize(140,226)
            layout = QVBoxLayout(self)
            layout.setContentsMargins(13,8,0,0)
            layout.setSpacing(0)

            self.cover_label = self._make_cover(113,172)
            layout.addWidget(self.cover_label, alignment=Qt.AlignLeft)

            self.title_label = QLabel()
            self.title_label.setObjectName("book_item_title")
            self.title_label.setStyleSheet("font-size: 14px;")
            self.author_label = QLabel()
            self.author_label.setObjectName("book_item_author")
            self.author_label.setStyleSheet("font-size: 13px;")

            for lbl in (self.title_label, self.author_label):
                lbl.setContentsMargins(0,0,14,0)

            layout.addWidget(self.title_label)
            layout.addWidget(self.author_label)

        # -------- 1 PER ROW --------
        elif mode == "1 per row":
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
            layout = QHBoxLayout(self)
            layout.setContentsMargins(4,4,4,4)
            layout.setSpacing(6)

            self.title_label = QLabel()
            self.title_label.setObjectName("book_item_title")
            self.title_label.setStyleSheet("font-size: 14px;")
            self.title_label.setContentsMargins(4,0,0,0)

            self.author_label = QLabel()
            self.author_label.setObjectName("book_item_author")
            self.author_label.setStyleSheet("font-size: 14px;")
            self.author_label.setFixedWidth(100)
            self.author_label.setAlignment(Qt.AlignRight)
            self.author_label.setContentsMargins(0,0,0,0)

            self.total_label = QLabel()
            self.total_label.setObjectName("book_item_total")
            self.total_label.setStyleSheet("font-size: 14px;")
            self.total_label.setFixedWidth(46)
            self.total_label.setAlignment(Qt.AlignRight)
            self.total_label.setContentsMargins(0,0,0,0)

            layout.addWidget(self.title_label)
            layout.addStretch()
            layout.addWidget(self.author_label)
            layout.addWidget(self.total_label)

        if mode in ("2 per row", "3 per row", "Square"):
            self._overlay_has_progress = False
            self.overlay_widget = QWidget(self)
            ovl_layout = QVBoxLayout(self.overlay_widget)
            ovl_layout.setContentsMargins(4, 4, 4, 4)
            ovl_layout.setSpacing(2)
            ovl_layout.addStretch()

            # Top row: elapsed (left) · remaining/total (right). Hidden when no progress.
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

            # Bottom row: progress bar + pct% if progress; total duration centered if no progress.
            # We use a container for progress elements and a separate label for total duration (no progress)
            # and manage their visibility.
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

            self.overlay_pct_label = QLabel()
            self.overlay_pct_label.setStyleSheet("color: white; font-size: 14px; background: transparent;")
            self.overlay_pct_label.setFixedWidth(30)
            self.overlay_pct_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

            # Container for progress bar and percentage
            self.overlay_progress_container = QWidget()
            progress_container_layout = QHBoxLayout(self.overlay_progress_container)
            progress_container_layout.setContentsMargins(0,0,0,0)
            progress_container_layout.setSpacing(4)
            progress_container_layout.addWidget(self.overlay_progress_bar, 1)
            progress_container_layout.addWidget(self.overlay_pct_label)

            # Label for total duration when no progress
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

    def bind(self, book_data):
        """Virtual Scroll entry point: Rebinds the widget to new data."""
        self.book_data = book_data
        old_path = self.current_path
        self.current_path = book_data.get("path", "")
        
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
        prog = float(self.book_data.get("progress") or 0)
        dur = float(self.book_data.get("duration") or 0)
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

    def showEvent(self, event):
        super().showEvent(event)
        self._reposition_overlay()

    def mousePressEvent(self, event):
        self._is_toggling = False
        if event.button() == Qt.LeftButton:
            prog = float(self.book_data.get("progress") or 0)
            dur = float(self.book_data.get("duration") or 0)
            
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
        if hasattr(self, "progress_inner") and hasattr(self, "progress_outer"):
            prog = float(self.book_data.get("progress") or 0)
            dur = float(self.book_data.get("duration") or 0)
            pct = (prog / dur) if dur > 0 else 0
            try:
                w = int(self.progress_outer.maximumWidth() * pct)
                self.progress_inner.setGeometry(0, 0, w, 6)
            except RuntimeError: pass
        self._reposition_overlay()

    def _update_ui_content(self):
        """Internal: Updates labels based on current book_data."""
        book_data = self.book_data
        title = book_data.get("title") or ""
        author = book_data.get("author") or ""
        narrator = book_data.get("narrator")
        year = book_data.get("year")

        prog = float(book_data.get("progress") or 0)
        dur = float(book_data.get("duration") or 0)
        pct = (prog / dur) if dur > 0 else 0
        speed = float(self.book_data.get("speed") or 1.0)
        has_progress = prog > 0 and dur > 0

        def fmt_time(s):
            s = int(s or 0)
            return f"{s//3600}:{(s%3600)//60:02}:{s%60:02}"

        # title/author
        if hasattr(self, "title_label"):
            self.title_label.setText(title)
        if hasattr(self, "author_label"):
            self.author_label.setText(author)

        # narrator/year visibility
        if hasattr(self, "narrator_label"):
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

        # progress
        show_progress = prog > 0
        if hasattr(self, "progress_outer") and hasattr(self, "pct_label"):
            self.progress_outer.setVisible(show_progress)
            self.pct_label.setVisible(show_progress)
            self.pct_label.setText(f"{int(pct*100)}%")

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
                display_title = self.book_data.get("title") or "Unknown"
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
            self.clicked.emit(self.book_data["path"])
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
                path = book['path']
                if path in self._pixmap_cache:
                    widget.set_cover(self._pixmap_cache[path])
                elif path_changed or not widget.cover_label.pixmap():
                    widget.cover_label.setPixmap(QPixmap())
                    self._trigger_cover_load(book, widget)

            # Position
            row, col = i // cols, i % cols
            widget.move(col * dim['w'], row * item_h)
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
        self._books_cache = self.db.get_all_books(sort_by="title COLLATE NOCASE ASC")
        self._data_initialized = True

        if not self.isVisible():
            return

        self._on_search_changed(self.search_field.text())

    def _trigger_cover_load(self, book, widget):
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
        mode = self.style_combo.currentData()
        self.config.set_library_view_mode(mode)
        self._resolve_theme_colors()
        for item in self._pool:
            item.set_view_mode(mode)
        self._sort_items_in_place()
        self.update_progress_bar_theme()

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
        for display, key in [("Title", "Title"), ("Author", "Author"), ("Recent", "Last Played"), ("Progress", "Progress"), ("Duration", "Duration")]:
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
                if text in (b.get('title') or '').lower() or 
                   text in (b.get('author') or '').lower()
            ]
        self._sort_items_in_place(reset_scroll=True)

    def _sort_items_in_place(self, ascending=None, reset_scroll=False):
        # Toggle direction if called from button, otherwise keep current
        if ascending is None:
            ascending = getattr(self, '_sort_ascending', True)
        self._sort_ascending = ascending

        sort_text = self.sort_combo.currentData()
        self.config.set_library_sort_key(sort_text)
        self.config.set_library_sort_ascending(ascending)

        sort_key = sort_text.lower().replace(" ", "_")
        numeric_keys = {"progress", "duration"}
        datetime_keys = {"last_played", "date_added"}

        def sort_value(book_dict):
            val = book_dict.get(sort_key)
            if val is None:
                return (1, 0 if sort_key in numeric_keys else "")
            if sort_key == "progress":
                duration = book_dict.get("duration") or 1
                return (0, float(val) / float(duration))
            if sort_key in numeric_keys:
                return (0, float(val))
            if sort_key in datetime_keys:
                return (0, str(val))
            return (0, str(val).lower())

        has_val = [b for b in self._filtered_books if b.get(sort_key) is not None]
        no_val = [b for b in self._filtered_books if b.get(sort_key) is None]

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

    def update_current_book_progress(self):
        """Live update for the currently playing book's progress and sorting."""
        if getattr(self, '_is_animating', False):
            return
        
        # Since virtualization only re-renders visible items, we just need to refresh
        # if the "Progress" sort is active, or if the current book is in the viewport.
        if self.sort_combo.currentData() == "Progress":
            self._sort_items_in_place()
        else:
            self._update_viewport()