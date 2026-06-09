# THEME_ANIM_TODO: BookDetailPanel, _ClickableLabel
import os
from datetime import datetime
from enum import Enum, auto
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTabWidget,
    QPushButton, QScrollArea, QGridLayout, QLineEdit, QCompleter, QToolButton
)
from PySide6.QtCore import Qt, Signal, QStringListModel, QTimer, QEvent, Property, QSize
from PySide6.QtGui import QColor, QPainter, QFontMetrics, QPixmap, QIcon, QRegularExpressionValidator
from PySide6.QtCore import QRegularExpression
from PySide6.QtWidgets import QApplication

from .cover_loader import to_grayscale
from .stats_panel import _RangeBar
from .flow_layout import FlowLayout
from .tag_manager import TAG_COLORS, MAX_TAG_LENGTH
from .text_context_menu import ContextIconMenu
from .icon_utils import render_logo_placeholder as _render_logo_placeholder, load_themed_icon


class _MetaActionState(Enum):
    HIDDEN = auto()
    DIRTY = auto()
    LOCKED = auto()
    UNLOCKED = auto()


class _ElidingLineEdit(QLineEdit):
    """QLineEdit that elides text on the right when read-only."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text_color = QColor()

    @Property(QColor)
    def text_color(self):
        return self._text_color

    @text_color.setter
    def text_color(self, color: QColor):
        self._text_color = color
        palette = self.palette()
        palette.setColor(self.foregroundRole(), color)
        self.setPalette(palette)
        self.update()

    def paintEvent(self, event):
        if not self.isReadOnly():
            super().paintEvent(event)
            return

        painter = QPainter(self)
        # 2 is Qt's hardcoded internal horizontal text margin for QLineEdit.
        rect = self.rect().adjusted(3, 0, -2, 0)
        fm = QFontMetrics(self.font())
        elided = fm.elidedText(self.text(), Qt.TextElideMode.ElideRight, rect.width())
        painter.setFont(self.font())
        painter.setPen(self.palette().text().color())
        painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided)
        painter.end()


class _ClickableLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class BookDetailPanel(QWidget):
    close_requested = Signal()
    history_deleted = Signal()
    metadata_saved = Signal(int, str, str, str, object)  # book_id, title, author, narrator, year (int|None)
    tags_changed = Signal()
    active_cover_changed = Signal(str, str)  # (book_path, cover_path)
    book_removed = Signal()
    tag_filter_requested = Signal(str)
    open_tag_manager_requested = Signal()

    def __init__(self, db, config, parent=None):
        super().__init__(parent)
        self.db = db
        self.config = config
        self._book_path: str | None = None
        self._book_data: dict = {}
        self._theme: dict = {}
        self._locks: dict = {'title': False, 'author': False, 'narrator': False, 'year': False}
        self._duration_show_adjusted: bool = False
        self._editing: bool = False
        self._is_archived: bool = False
        self._confirming_remove: bool = False
        self._remove_cancel_timer: QTimer | None = None
        self._delete_history_cancel_timer: QTimer | None = None
        self._context: str = ""
        self._tag_display_tags: list = []
        self._meta_state: _MetaActionState = _MetaActionState.HIDDEN
        self._pre_edit_meta_state: _MetaActionState | None = None
        self._unlock_timer: QTimer | None = None
        self.setObjectName("book_detail_panel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._assets_dir = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "assets")
        )
        self._build_ui()
        self._ctx_menu = ContextIconMenu(self)
        self._tag_suggest_timer = QTimer(self)
        self._tag_suggest_timer.setSingleShot(True)
        self._tag_suggest_timer.setInterval(200)
        self._tag_suggest_timer.timeout.connect(self._do_tag_suggestions)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget()
        header.setObjectName("book_detail_header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 10, 10, 4)
        header_layout.setSpacing(12)

        self._cover_label = QLabel()
        self._cover_label.setFixedWidth(80)
        self._cover_label.setMaximumHeight(120)
        self._cover_label.setScaledContents(False)
        header_layout.addWidget(self._cover_label)

        meta_block = QVBoxLayout()
        meta_block.setSpacing(2)

        def make_field(obj_name, placeholder=''):
            edit = _ElidingLineEdit()
            edit.setObjectName(obj_name)
            edit.setPlaceholderText(placeholder)
            edit.setMaxLength(300)
            edit.setFrame(False)
            edit.setReadOnly(True)
            edit.setCursor(Qt.CursorShape.IBeamCursor)
            edit.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            edit.textChanged.connect(self._check_dirty)
            edit.returnPressed.connect(self._on_inline_save)
            return edit

        self._title_label    = make_field("book_detail_title")
        self._author_label   = make_field("book_detail_author")
        self._narrator_label = make_field("book_detail_narrator", placeholder="Narrator")
        self._year_label     = make_field("book_detail_year",     placeholder="Year")

        for _meta_field in (self._title_label, self._author_label, self._narrator_label, self._year_label):
            _meta_field.customContextMenuRequested.connect(
                lambda pos, f=_meta_field: self._ctx_menu.show_for(f, f.mapToGlobal(pos))
            )
        self._year_label.setValidator(
            QRegularExpressionValidator(QRegularExpression(r'^-?\d*$'))
        )
        for _f in (self._narrator_label, self._year_label):
            _sp = _f.sizePolicy()
            _sp.setRetainSizeWhenHidden(True)
            _f.setSizePolicy(_sp)

        self._duration_label = _ClickableLabel()
        self._duration_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._duration_label.clicked.connect(self._toggle_duration)
        self._duration_label.setContentsMargins(3, 0, 0, 0)

        self._confirm_remove_label = _ClickableLabel("Click to remove from the library")
        self._confirm_remove_label.setObjectName("book_detail_confirm_remove")
        self._confirm_remove_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._confirm_remove_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._confirm_remove_label.clicked.connect(self._on_confirm_remove)
        self._confirm_remove_label.setVisible(False)

        self._remove_btn = QToolButton()
        self._remove_btn.setObjectName("remove_book_btn")
        self._remove_btn.setToolTip("")
        self._remove_btn.setFixedSize(24, 24)
        self._remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._remove_btn.clicked.connect(self._on_remove_clicked)
        self._remove_btn.installEventFilter(self)
        self._remove_btn.setStyleSheet("QToolButton { background: transparent; border: none; margin-right: -3px; padding-right: -3px;}")

        self._meta_action_btn = QToolButton()
        self._meta_action_btn.setObjectName("metadata_action_btn")
        self._meta_action_btn.setFixedSize(24, 24)
        _meta_btn_sp = self._meta_action_btn.sizePolicy()
        _meta_btn_sp.setRetainSizeWhenHidden(True)
        self._meta_action_btn.setSizePolicy(_meta_btn_sp)
        self._meta_action_btn.setVisible(False)
        self._meta_action_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._meta_action_btn.clicked.connect(self._on_meta_action_clicked)
        self._meta_action_btn.installEventFilter(self)
        self._meta_action_btn.setStyleSheet("QToolButton { background: transparent; border: none; margin-right: -4px; padding-right: -4px; margin-bottom: -4px; padding-bottom: -4px;}")

        self._finished_label = QLabel()
        self._finished_label.setObjectName("book_detail_finished_icon")
        self._finished_label.setFixedSize(16, 24)
        self._finished_label.setVisible(False)

        dur_save_row = QHBoxLayout()
        dur_save_row.setContentsMargins(0, 0, 0, 0)
        dur_save_row.setSpacing(4)
        dur_save_row.addWidget(self._duration_label)
        dur_save_row.addStretch()
        dur_save_row.addWidget(self._confirm_remove_label)

        meta_block.addWidget(self._title_label)
        meta_block.addWidget(self._author_label)
        meta_block.addWidget(self._narrator_label)
        meta_block.addWidget(self._year_label)
        meta_block.addLayout(dur_save_row)
        meta_block.addStretch()

        # Make fields clickable to enter edit mode
        for field in (self._title_label, self._author_label,
                      self._narrator_label, self._year_label):
            field.mousePressEvent = lambda e, f=field: self._on_field_click(e, f)

        header_layout.addLayout(meta_block, stretch=1)

        # Right column: close button + meta button at top, trash at bottom
        right_col = QVBoxLayout()
        right_col.setSpacing(4)
        right_col.setContentsMargins(0, 0, 0, 0)

        self._close_btn = QPushButton("✕")
        self._close_btn.setObjectName("book_detail_close_btn")
        self._close_btn.setFixedSize(15, 15)
        self._close_btn.clicked.connect(self._on_close_clicked)
        right_col.addWidget(self._close_btn, alignment=Qt.AlignmentFlag.AlignRight)
        right_col.addWidget(self._meta_action_btn, alignment=Qt.AlignmentFlag.AlignRight)
        right_col.addWidget(self._finished_label, alignment=Qt.AlignmentFlag.AlignRight)

        self._ghost_label = QLabel()
        self._ghost_label.setFixedSize(self._remove_btn.size())
        self._ghost_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._ghost_label.setContentsMargins(8, 0, 0, 0)
        self._ghost_label.hide()

        right_col.addStretch()
        right_col.addWidget(self._remove_btn, alignment=Qt.AlignmentFlag.AlignRight)
        right_col.addWidget(self._ghost_label, alignment=Qt.AlignmentFlag.AlignRight)
        header_layout.addLayout(right_col)

        layout.addWidget(header)

        self._tag_display_label = QLabel()
        self._tag_display_label.setObjectName("tag_display_chip")
        self._tag_display_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._tag_display_label.setWordWrap(True)
        self._tag_display_label.setContentsMargins(8, 2, 8, 2)
        self._tag_display_label.setFixedHeight(38)  # two tag lines reserved always
        self._tag_display_label.setOpenExternalLinks(False)
        self._tag_display_label.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self._tag_display_label.linkActivated.connect(self.tag_filter_requested)
        layout.addWidget(self._tag_display_label)

        from .cover_panel import CoverPanel
        self._cover_panel = CoverPanel(db=self.db, parent=self)
        self._cover_panel.active_cover_changed.connect(self._on_cover_panel_changed)
        self._cover_panel.active_cover_changed.connect(self._refresh_header_cover)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("stats_tabs")
        self.tabs.addTab(self._build_stats_tab(), "Stats")
        self.tabs.addTab(self._build_history_tab(), "History")
        self.tabs.addTab(self._build_metadata_tab(), "Tags")
        self.tabs.addTab(self._cover_panel, "Cover")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tabs, stretch=1)

        self._update_remove_btn_icon()

    def _build_stats_tab(self) -> QWidget:
        widget = QWidget()
        outer = QVBoxLayout(widget)
        outer.setContentsMargins(10, 10, 10, 20)
        outer.setSpacing(12)

        from PySide6.QtGui import QColor
        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(6)

        # Row 0: Furthest position | [bar stretches col 1] | pct
        fp_key = QLabel("Furthest position")
        fp_key.setObjectName("stats_key_label")
        self._furthest_pct_label = QLabel("")
        self._furthest_pct_label.setObjectName("stats_value_label")

        fp_bar_row = QHBoxLayout()
        fp_bar_row.setContentsMargins(0, 0, 0, 0)
        fp_bar_row.setSpacing(0)
        self._furthest_bar = _RangeBar(0, 0, 1, QColor("#888"), QColor("#333"))
        self._furthest_bar.setFixedHeight(6)
        fp_bar_row.addWidget(self._furthest_bar)
        fp_bar_container = QWidget()
        fp_bar_container.setLayout(fp_bar_row)

        grid.addWidget(fp_key,               0, 0, Qt.AlignmentFlag.AlignLeft)
        grid.addWidget(fp_bar_container,     0, 1)
        grid.addWidget(self._furthest_pct_label, 0, 2, Qt.AlignmentFlag.AlignLeft)

        stat_rows = [
            ("Remaining",      "—"),
            ("Total listened", "—"),
            ("Sessions",       "—"),
            ("Last session",   "—"),
            ("Started",        "—"),
            ("Finished",       "—"),
        ]

        self._stat_labels = []
        for i, (key, default) in enumerate(stat_rows):
            k = QLabel(key)
            k.setObjectName("stats_key_label")
            v = QLabel(default)
            v.setObjectName("stats_value_label")
            grid.addWidget(k, i + 1, 0, Qt.AlignmentFlag.AlignLeft)
            grid.addWidget(v, i + 1, 1, 1, 2, Qt.AlignmentFlag.AlignLeft)
            self._stat_labels.append(v)

        grid.setColumnStretch(1, 1)
        outer.addWidget(grid_widget, 0, Qt.AlignmentFlag.AlignTop)
        outer.addStretch(1)

        self._history_header = QLabel("Recent history")
        self._history_header.setObjectName("stats_history_header")
        self._history_header.setIndent(0)
        outer.addWidget(self._history_header, 0, Qt.AlignmentFlag.AlignTop)

        self._session_list = _RecentHistoryWidget()
        outer.addWidget(self._session_list, 0, Qt.AlignmentFlag.AlignTop)

        return widget

    def _build_history_tab(self) -> QWidget:
        widget = QWidget()
        outer = QVBoxLayout(widget)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)

        from .stats_panel import SessionListWidget
        self._history_session_list = SessionListWidget()
        outer.addWidget(self._history_session_list)

        outer.addStretch()

        self._delete_history_confirm_label = _ClickableLabel("Click to delete all history for this book")
        self._delete_history_confirm_label.setObjectName("book_detail_confirm_remove")
        self._delete_history_confirm_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._delete_history_confirm_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._delete_history_confirm_label.setFixedHeight(28)
        self._delete_history_confirm_label.clicked.connect(self._on_delete_book_stats_confirmed)
        self._delete_history_confirm_label.setVisible(False)
        outer.addWidget(self._delete_history_confirm_label)

        self._delete_history_btn = QPushButton("Delete listening history")
        self._delete_history_btn.setObjectName("stats_reset_btn")
        self._delete_history_btn.clicked.connect(self._on_delete_book_stats)
        outer.addWidget(self._delete_history_btn)

        return widget

    def _build_metadata_tab(self) -> QWidget:
        widget = QWidget()
        outer = QVBoxLayout(widget)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)


        self._tag_chip_container = QWidget()
        self._tag_chip_layout = FlowLayout(self._tag_chip_container, h_spacing=8, v_spacing=8)
        self._tag_chip_layout.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._tag_chip_container)

        self._tag_input_widget = QWidget()
        tag_input_row = QHBoxLayout(self._tag_input_widget)
        tag_input_row.setContentsMargins(0, 0, 0, 0)
        tag_input_row.setSpacing(6)
        self._tag_input = QLineEdit()
        self._tag_input.setObjectName("tag_add_field")
        self._tag_input.setPlaceholderText("Add tag…")
        self._tag_input.setMaxLength(MAX_TAG_LENGTH)
        self._tag_input.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tag_input.customContextMenuRequested.connect(
            lambda pos: self._ctx_menu.show_for(self._tag_input, self._tag_input.mapToGlobal(pos))
        )
        self._tag_input.returnPressed.connect(self._on_add_tag)

        self._tag_completer_model = QStringListModel()
        self._tag_completer = QCompleter(self._tag_completer_model, self._tag_input)
        self._tag_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._tag_completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self._tag_completer.activated.connect(self._on_tag_completer_activated)
        self._tag_input.setCompleter(self._tag_completer)
        self._tag_input.textChanged.connect(self._on_tag_input_changed)
        self._style_completer_popup()

        add_tag_btn = QPushButton("+")
        add_tag_btn.setObjectName("tag_add_btn")
        add_tag_btn.setFixedSize(32, 32)
        add_tag_btn.clicked.connect(self._on_add_tag)

        tag_input_row.addWidget(self._tag_input)
        tag_input_row.addWidget(add_tag_btn)
        outer.addWidget(self._tag_input_widget)

        outer.addStretch()

        self._tag_manager_btn = QPushButton("Tag management")
        self._tag_manager_btn.setObjectName("tag_manager_nav_btn")
        self._tag_manager_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._tag_manager_btn.clicked.connect(self.open_tag_manager_requested)
        self._tag_manager_btn.hide()
        outer.addWidget(self._tag_manager_btn)

        return widget

    def _rebuild_tag_chips(self):
        while self._tag_chip_layout.count():
            item = self._tag_chip_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        tags = self.db.get_book_tags(self._book_data['id'])
        tag_colors = {t: self.db.get_tag_color(t) for t in tags}
        for tag in tags:
            chip = QWidget()
            chip.setObjectName("tag_chip")
            chip.setAttribute(Qt.WA_StyledBackground, True)
            row = QHBoxLayout(chip)
            row.setContentsMargins(10, 5, 7, 5)
            row.setSpacing(6)
            color_hex = TAG_COLORS.get(tag_colors.get(tag)) if tag_colors.get(tag) else None
            dot = QLabel("●")
            dot.setObjectName("tag_chip_dot")
            if color_hex:
                dot.setStyleSheet(f"color: {color_hex};")
            else:
                dot.setObjectName("tag_dot_neutral")
            row.addWidget(dot)
            lbl = QLabel(tag)
            lbl.setObjectName("tag_chip_label")
            if self._context == 'library':
                chip.setCursor(Qt.CursorShape.PointingHandCursor)
                chip.mousePressEvent = lambda event, t=tag: self.tag_filter_requested.emit(t)
            x_btn = QPushButton("✕")
            x_btn.setObjectName("tag_chip_remove_btn")
            x_btn.setFixedSize(18, 18)
            x_btn.clicked.connect(lambda checked, t=tag: self._on_remove_tag(t))
            row.addWidget(lbl)
            row.addWidget(x_btn)
            self._tag_chip_layout.addWidget(chip)

        self._tag_input_widget.setVisible(len(tags) < 5)

        self._rebuild_tag_display(tags)

    def _rebuild_tag_display(self, tags: list[str]):
        self._tag_display_tags = list(tags)
        sep = "  "
        if not tags:
            self._tag_display_label.setText("")
            return
        tag_colors = {t: self.db.get_tag_color(t) for t in tags} if self._book_path else {}
        dot_color  = self._theme.get("accent_light", "#ffffff")
        text_color = self._theme.get("accent_light", "#ffffff")
        if self._context == 'library':
            self._tag_display_label.setTextFormat(Qt.TextFormat.RichText)
            parts = [
                f'<a href="{t}" style="color:{text_color};text-decoration:none;">'  
                f'<span style="color:{TAG_COLORS.get(tag_colors.get(t)) or dot_color};">&#9679;</span> {t.replace(chr(32), " ")}</a>'
                for t in tags
            ]
            self._tag_display_label.setText(sep.join(parts))
        else:
            self._tag_display_label.setTextFormat(Qt.TextFormat.RichText)
            parts = [
                f'<span style="color:{TAG_COLORS.get(tag_colors.get(t)) or dot_color};">&#9679;</span>'  
                f'<span style="color:{text_color};"> {t.replace(chr(32), " ")}</span>'
                for t in tags
            ]
            self._tag_display_label.setText(sep.join(parts))

    def _on_tag_input_changed(self, text: str):
        self._tag_suggest_timer.start()  # restarts if already running

    def _do_tag_suggestions(self):
        text = self._tag_input.text().strip()
        if text and self._book_path:
            suggestions = self.db.get_tag_suggestions(text, self._book_data['id'])
            self._tag_completer_model.setStringList(suggestions)
            self._style_completer_popup()
        else:
            self._tag_completer_model.setStringList([])

    def _on_tag_completer_activated(self, text: str):
        self._tag_input.setText(text)
        self._on_add_tag()

    def _on_add_tag(self):
        tag = self._tag_input.text().strip().lower()
        if not tag or not self._book_path:
            return
        added = self.db.add_book_tag(self._book_path, tag, book_id=self._book_data['id'])
        if added:
            self._tag_completer_model.setStringList([])
            self._tag_input.clear()
            self._rebuild_tag_chips()
            self.tags_changed.emit()
        else:
            self._tag_input.setStyleSheet("border: 1px solid red;")
            from PySide6.QtCore import QTimer
            QTimer.singleShot(800, lambda: self._tag_input.setStyleSheet(""))

    def _on_remove_tag(self, tag: str):
        if self._book_path:
            self.db.remove_book_tag(self._book_data['id'], tag)
            self._rebuild_tag_chips()
            self.tags_changed.emit()

    def _sync_header_from_fields(self):
        self._title_label.setText(self._book_data.get('title') or self._book_data.get('book_title', ''))
        self._author_label.setText(self._book_data.get('author') or self._book_data.get('book_author', ''))
        narrator = self._book_data.get('narrator', '')
        self._narrator_label.setText(narrator)
        year = self._book_data.get('year')
        self._year_label.setText(str(year) if year else '')
        if not self._editing:
            self._narrator_label.setVisible(bool(narrator))
            self._year_label.setVisible(bool(year))
            for field in (self._title_label, self._author_label,
                          self._narrator_label, self._year_label):
                field.setCursorPosition(0)

    def load_book(self, book_data: dict, tab: str = 'stats', context: str = ''):
        self._context = context
        self._tag_manager_btn.setVisible(context != 'tags')
        self._book_path = book_data.get('path') or book_data.get('book_path')
        self._book_data = book_data
        if 'duration' not in book_data:
            full = self.db.get_book(self._book_path)
            if full:
                self._book_data = {
                    'path': full.path,
                    'id': full.id,
                    'title': full.title,
                    'author': full.author,
                    'narrator': full.narrator or '',
                    'year': full.year,
                    'cover_path': full.cover_path,
                    'duration': full.duration,
                }

        _book_dict = self.db.get_book_dict(self._book_path)
        self._is_archived = (
            _book_dict is None or
            bool(_book_dict.get('is_deleted')) or
            bool(_book_dict.get('is_excluded'))
        )

        pixmap = QPixmap()
        cover_path = self.db.get_active_cover_path(self._book_path)
        if cover_path and os.path.exists(cover_path):
            pixmap.load(cover_path)
        if pixmap.isNull():
            color = self._theme.get('placeholder_stats',
                self._theme.get('placeholder_cover',
                    self._theme.get('library_narrator',
                        self._theme.get('text', '#888888'))))
            icon = _render_logo_placeholder(color, 80)
            pixmap = QPixmap(80, 120)
            pixmap.fill(Qt.transparent)
            p = QPainter(pixmap)
            p.drawPixmap(0, (140 - 100) // 2, icon)
            p.setPen(QColor(color))
            p.drawRect(pixmap.rect().adjusted(1, 1, -1, -1))
            p.end()
        if not pixmap.isNull():
            self._apply_cover(pixmap)

        self._editing = False
        self._exit_edit_mode(save=False)
        self._sync_header_from_fields()

        self._duration_show_adjusted = False
        self._update_duration_label()

        self._rebuild_tag_chips()

        for i in range(self.tabs.count()):
            if self.tabs.tabText(i).lower() == tab.lower():
                self.tabs.setCurrentIndex(i)
                break

        self._cover_panel.load_book(self._book_path)
        self._refresh_stats()
        excluded = bool(_book_dict and _book_dict.get('is_excluded'))
        self._remove_btn.setVisible(not excluded and not self._is_archived)
        self._ghost_label.setVisible(self._is_archived)
        if self._is_archived:
            pixmap = load_themed_icon("ghost.svg", self._theme.get("accent", "#888888"), 16, 0.7)
            self._ghost_label.setPixmap(pixmap)
        self._locks = self.db.get_metadata_locks(self._book_path)
        if any(self._locks.values()):
            self._set_meta_state(_MetaActionState.LOCKED)
        else:
            self._set_meta_state(_MetaActionState.HIDDEN)

    def _on_cover_panel_changed(self, cover_path: str):
        self.active_cover_changed.emit(self._book_path or "", cover_path)

    def _apply_cover(self, pixmap: QPixmap) -> None:
        if self._is_archived:
            pixmap = to_grayscale(pixmap)
        scaled = pixmap.scaled(
            80, 120,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._cover_label.setPixmap(scaled)
        self._cover_label.setFixedHeight(scaled.height())

    def _refresh_header_cover(self, file_path: str):
        pixmap = QPixmap()
        if file_path and os.path.exists(file_path):
            pixmap.load(file_path)
        if pixmap.isNull():
            color = self._theme.get('placeholder_stats',
                self._theme.get('placeholder_cover',
                    self._theme.get('library_narrator',
                        self._theme.get('text', '#888888'))))
            icon = _render_logo_placeholder(color, 80)
            pixmap = QPixmap(80, 120)
            pixmap.fill(Qt.transparent)
            p = QPainter(pixmap)
            p.drawPixmap(0, (120 - 80) // 2, icon)
            p.setPen(QColor(color))
            p.drawRect(pixmap.rect().adjusted(1, 1, -1, -1))
            p.end()
        if not pixmap.isNull():
            # TODO: verify _refresh_header_cover scaling matches load_book (setFixedHeight was absent here)
            self._apply_cover(pixmap)

    def _update_duration_label(self):
        duration = self._book_data.get('duration') or 0.0
        if not duration:
            self._duration_label.setVisible(False)
            self._duration_label.setCursor(Qt.ArrowCursor)
            return

        speed = self.config.get_book_speed(self._book_path)
        if speed is None:
            speed = self.config.get_default_speed()
        is_1x = speed is None or abs(speed - 1.0) < 1e-9
        effective_speed = 1.0 if is_1x else speed

        if self._duration_show_adjusted and not is_1x:
            text = f"{self._fmt(duration / effective_speed)} at {effective_speed:g}x"
        else:
            text = self._fmt(duration)

        self._duration_label.setText(text)
        self._duration_label.setVisible(True)
        self._duration_label.setCursor(
            Qt.ArrowCursor if is_1x else Qt.PointingHandCursor
        )

    def _set_meta_state(self, state: _MetaActionState):
        """Transitions to the given state and updates button appearance."""
        if self._unlock_timer is not None:
            self._unlock_timer.stop()
            self._unlock_timer = None

        self._meta_state = state

        if state == _MetaActionState.HIDDEN:
            self._meta_action_btn.setVisible(False)
            self._meta_action_btn.setIcon(QIcon())
        elif state == _MetaActionState.DIRTY:
            self._meta_action_btn.setVisible(True)
            color = self._theme.get("accent", "#888888")
            pixmap = load_themed_icon("save.svg", color, 16, 0.7)
            self._meta_action_btn.setIcon(QIcon(pixmap))
            self._meta_action_btn.setIconSize(QSize(16, 16))
        elif state == _MetaActionState.LOCKED:
            self._meta_action_btn.setVisible(True)
            color = self._theme.get("accent", "#888888")
            pixmap = load_themed_icon("lock.svg", color, 16, 0.7)
            self._meta_action_btn.setIcon(QIcon(pixmap))
            self._meta_action_btn.setIconSize(QSize(16, 16))
        elif state == _MetaActionState.UNLOCKED:
            self._meta_action_btn.setVisible(True)
            color = self._theme.get("accent", "#888888")
            pixmap = load_themed_icon("lock-open.svg", color, 16, 0.7)
            self._meta_action_btn.setIcon(QIcon(pixmap))
            self._meta_action_btn.setIconSize(QSize(16, 16))
            self._unlock_timer = QTimer()
            self._unlock_timer.setSingleShot(True)
            self._unlock_timer.setInterval(2500)
            self._unlock_timer.timeout.connect(lambda: self._set_meta_state(_MetaActionState.HIDDEN))
            self._unlock_timer.start()
    def _update_finished_icon(self, finished: bool) -> None:
        if not finished:
            self._finished_label.setVisible(False)
            return
        color = self._theme.get("accent", "#888888")
        pixmap = load_themed_icon("check.svg", color, 16, 0.7)
        self._finished_label.setPixmap(pixmap)
        self._finished_label.setVisible(True)

    def _on_meta_action_clicked(self):
        """Handles metadata action button click based on current state."""
        if self._meta_state == _MetaActionState.DIRTY:
            self._on_inline_save()
        elif self._meta_state == _MetaActionState.LOCKED:
            for key in self._locks:
                self._locks[key] = False
            self.db.set_metadata_locks(self._book_path, **self._locks)
            self._set_meta_state(_MetaActionState.UNLOCKED)

    def _toggle_duration(self):
        duration = self._book_data.get('duration') or 0.0
        speed = self.config.get_book_speed(self._book_path)
        if speed is None:
            speed = self.config.get_default_speed()
        is_1x = speed is None or abs(speed - 1.0) < 1e-9
        if not duration or is_1x:
            return
        self._duration_show_adjusted = not self._duration_show_adjusted
        self._update_duration_label()

    def showEvent(self, event):
        super().showEvent(event)
        QApplication.instance().installEventFilter(self)

    def hideEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        if self._editing:
            self._exit_edit_mode(save=False)
        self._cancel_remove()
        super().hideEvent(event)

    def eventFilter(self, obj, event):
        if obj is self._remove_btn:
            if not self._confirming_remove:
                if event.type() == QEvent.Type.Enter:
                    self._update_remove_btn_icon(hover=True)
                elif event.type() == QEvent.Type.Leave:
                    self._update_remove_btn_icon(hover=False)
            return False

        if obj is self._meta_action_btn:
            if event.type() == QEvent.Type.Enter:
                self._on_meta_action_hover(hover=True)
            elif event.type() == QEvent.Type.Leave:
                self._on_meta_action_hover(hover=False)
            return False

        if self._editing and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self._exit_edit_mode(save=False)
                return True

        if event.type() == QEvent.Type.MouseButtonPress:
            from PySide6.QtCore import QRect
            gpos = event.globalPosition().toPoint()

            def hits(w):
                return w.isVisible() and QRect(
                    w.mapToGlobal(w.rect().topLeft()),
                    w.mapToGlobal(w.rect().bottomRight())
                ).contains(gpos)

            if self._confirming_remove:
                confirm_safe = (self._confirm_remove_label, self._remove_btn)
                if not any(hits(w) for w in confirm_safe):
                    self._cancel_remove()

            if self._editing:
                safe = (self._title_label, self._author_label,
                        self._narrator_label, self._year_label, self._meta_action_btn,
                        self._close_btn)
                if not any(hits(w) for w in safe):
                    self._exit_edit_mode(save=False)

        return super().eventFilter(obj, event)

    def _on_tab_changed(self):
        if self._editing:
            self._exit_edit_mode(save=False)

    def _on_field_click(self, event, field):
        QLineEdit.mousePressEvent(field, event)
        self._enter_edit_mode()

    def _enter_edit_mode(self):
        if self._editing:
            return
        self._editing = True
        self._pre_edit_meta_state = self._meta_state
        self._orig_title    = self._title_label.text()
        self._orig_author   = self._author_label.text()
        self._orig_narrator = self._narrator_label.text()
        self._orig_year     = self._year_label.text()
        self._narrator_label.setVisible(True)
        self._year_label.setVisible(True)
        for field in (self._title_label, self._author_label,
                      self._narrator_label, self._year_label):
            field.setReadOnly(False)
            field.setCursor(Qt.CursorShape.IBeamCursor)
            field.setCursorPosition(0)
        self._title_label.setFocus()

    def _on_meta_action_hover(self, hover: bool):
        """Updates button opacity on hover."""
        if self._meta_state == _MetaActionState.HIDDEN:
            return
        color = self._theme.get("accent", "#888888")
        opacity = 1.0 if hover else 0.70
        if self._meta_state == _MetaActionState.DIRTY:
            pixmap = load_themed_icon("save.svg", color, 16, opacity)
        elif self._meta_state == _MetaActionState.LOCKED:
            pixmap = load_themed_icon("lock.svg", color, 16, opacity)
        elif self._meta_state == _MetaActionState.UNLOCKED:
            pixmap = load_themed_icon("lock-open.svg", color, 16, opacity)
        else:
            return
        self._meta_action_btn.setIcon(QIcon(pixmap))

    def _check_dirty(self):
        if not self._editing:
            return
        dirty = (
            self._title_label.text()    != self._orig_title    or
            self._author_label.text()   != self._orig_author   or
            self._narrator_label.text() != self._orig_narrator or
            self._year_label.text()     != self._orig_year
        )
        if dirty:
            self._set_meta_state(_MetaActionState.DIRTY)
        else:
            if any(self._locks.values()):
                self._set_meta_state(_MetaActionState.LOCKED)
            else:
                self._set_meta_state(_MetaActionState.HIDDEN)

    def _exit_edit_mode(self, save: bool):
        if not self._editing:
            return
        self._editing = False
        for field in (self._title_label, self._author_label,
                      self._narrator_label, self._year_label):
            field.setReadOnly(True)
            field.setCursor(Qt.CursorShape.IBeamCursor)
        if save:
            self._commit_inline_save()
        else:
            self._sync_header_from_fields()
            if self._pre_edit_meta_state is not None:
                self._set_meta_state(self._pre_edit_meta_state)
        narrator = self._book_data.get('narrator', '')
        year = self._book_data.get('year')
        self._narrator_label.setVisible(bool(narrator))
        self._year_label.setVisible(bool(year))

    def _on_inline_save(self):
        self._exit_edit_mode(save=True)

    def _commit_inline_save(self):
        title    = self._title_label.text().strip()
        author   = self._author_label.text().strip()
        narrator = self._narrator_label.text().strip()
        year_str = self._year_label.text().strip()

        if title != self._orig_title: self._locks['title'] = True
        if author != self._orig_author: self._locks['author'] = True
        if narrator != self._orig_narrator: self._locks['narrator'] = True
        if year_str != self._orig_year: self._locks['year'] = True

        year_int = int(year_str) if year_str.isdigit() else None
        if self.db.update_book_metadata(self._book_path, title, author, narrator, year_str):
            self.db.set_metadata_locks(self._book_path, **self._locks)
            self._book_data.update({
                'title': title, 'author': author, 'narrator': narrator, 'year': year_int
            })
            self.metadata_saved.emit(self._book_data.get('id'), title, author, narrator, year_int)
            if any(self._locks.values()):
                self._set_meta_state(_MetaActionState.LOCKED)
            else:
                self._set_meta_state(_MetaActionState.HIDDEN)
        self._sync_header_from_fields()

    def _on_close_clicked(self):
        if self._editing:
            self._exit_edit_mode(save=False)
        self._cancel_remove()
        self.close_requested.emit()

    def _refresh_stats(self):
        if not self._book_path:
            return
        day_start = self.config.get_day_start_hour()
        stats = self.db.get_book_stats(self._book_data['id'], day_start)
        duration = self._book_data.get('duration')
        if not duration:
            book = self.db.get_book(self._book_path)
            if book:
                duration = book.duration

        speed = self.config.get_book_speed(self._book_path) or 1.0

        furthest = stats['furthest_position']
        if duration and duration > 0:
            pct = min(100, round((furthest / duration) * 100))
            self._furthest_bar.update_range(0, furthest, duration)
            self._furthest_pct_label.setText(f"{pct}%")
            remaining = max(0, duration - furthest)
            if speed != 1.0:
                self._stat_labels[0].setText(
                    f"{self._fmt(remaining / speed)} at {speed:g}x"
                )
            else:
                self._stat_labels[0].setText(self._fmt(remaining))
        else:
            self._furthest_bar.update_range(0, 0, 1)
            self._furthest_pct_label.setText("—")
            self._stat_labels[0].setText("—")

        self._stat_labels[1].setText(self._fmt(stats['total_seconds']))
        self._stat_labels[2].setText(str(stats['session_count']))

        sessions = self.db.get_book_sessions(self._book_data['id'])

        has_history = bool(sessions)
        self._history_header.setVisible(has_history)
        self._session_list.setVisible(has_history)
        self._delete_history_btn.setVisible(has_history)

        if sessions:
            newest = sessions[0]
            try:
                ld = datetime.fromisoformat(newest['session_start'])
                secs = newest.get('listened_seconds') or 0.0
                self._stat_labels[3].setText(
                    f"{ld.strftime('%b')} {ld.day}  {ld.strftime('%H:%M')}  · {self._fmt(secs)}"
                )
            except Exception:
                self._stat_labels[3].setText("—")
        else:
            self._stat_labels[3].setText("—")

        if stats['first_session']:
            d = datetime.fromisoformat(stats['first_session'])
            self._stat_labels[4].setText(f"{d.strftime('%b')} {d.day}, {d.year}")
        else:
            self._stat_labels[4].setText("—")

        if stats['finished_count'] == 0:
            self._stat_labels[5].setText("—")
        elif stats['finished_count'] == 1:
            d = datetime.fromisoformat(stats['last_finished'])
            self._stat_labels[5].setText(f"{d.strftime('%b')} {d.day}, {d.year}")
        else:
            d = datetime.fromisoformat(stats['last_finished'])
            self._stat_labels[5].setText(
                f"{stats['finished_count']}× — last {d.strftime('%b')} {d.day}, {d.year}"
            )

        self._session_list.set_data(sessions[:4], duration or 0.0)
        self._update_finished_icon(stats['finished_count'] > 0)
        self._history_session_list.set_data(sessions, duration or 0.0)
        self._apply_bar_colors()

    def _on_delete_book_stats(self):
        self._delete_history_confirm_label.setVisible(True)
        if self._delete_history_cancel_timer:
            self._delete_history_cancel_timer.stop()
        self._delete_history_cancel_timer = QTimer(self)
        self._delete_history_cancel_timer.setSingleShot(True)
        self._delete_history_cancel_timer.timeout.connect(self._cancel_delete_history)
        self._delete_history_cancel_timer.start(7000)

    def _cancel_delete_history(self):
        self._delete_history_confirm_label.setVisible(False)

    def _on_delete_book_stats_confirmed(self):
        self._cancel_delete_history()
        if self._book_path:
            self.db.delete_book_stats(self._book_data['id'], self._book_path)
            self._refresh_stats()
            self.history_deleted.emit()

    def _apply_bar_colors(self):
        from PySide6.QtGui import QColor
        accent = QColor(self._theme.get('dropdown_curr_chap', '#888888'))
        bg = QColor(self._theme.get('library_slider_bg', '#333333'))
        self._session_list.set_colors(accent, bg)
        self._history_session_list.set_colors(accent, bg)  # type: ignore[attr-defined]
        self._furthest_bar.set_colors(accent, bg)

    def _style_completer_popup(self):
        t = self._theme
        bg = t.get('bg_dropdown', '#2A3A4A')
        fg = t.get('text', '#FFFFFF')
        accent = t.get('accent', '#5A8A9F')
        accent_dark = t.get('accent_dark', '#3A6A7F')
        popup = self._tag_completer.popup()
        if popup is None:
            return
        popup.setStyleSheet(f"""
            QAbstractItemView {{
                background-color: {bg};
                color: {fg};
                border: 1px solid {accent};
                border-radius: 4px;
                outline: none;
                font-size: 13px;
                padding: 2px;
            }}
            QAbstractItemView::item {{
                min-height: 24px;
                padding: 2px 6px;
            }}
            QAbstractItemView::item:selected {{
                background-color: {accent};
                color: {fg};
            }}
            QAbstractItemView::item:hover:!selected {{
                background-color: {accent_dark};
            }}
            QScrollBar:vertical {{
                width: 6px;
                background: {bg};
                border: none;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background: {accent};
                min-height: 16px;
                border-radius: 3px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
        """)

    def _update_remove_btn_icon(self, hover: bool = False) -> None:
        if hover:
            color = "#cc3333"
            opacity = 1.0
        else:
            color = self._theme.get("accent", "#888888")
            opacity = 0.70
        pixmap = load_themed_icon("trash.svg", color, 16, opacity)
        self._remove_btn.setIcon(QIcon(pixmap))
        self._remove_btn.setContentsMargins(8, 0, 0, 0)
        self._remove_btn.setIconSize(QSize(16, 16))
        


    def _on_remove_clicked(self) -> None:
        if self._confirming_remove:
            return
        self._confirming_remove = True
        self._duration_label.setVisible(False)
        self._confirm_remove_label.setVisible(True)
        self._remove_btn.setCursor(Qt.CursorShape.ArrowCursor)
        color = self._theme.get("accent", "#888888")
        pixmap = load_themed_icon("trash.svg", color, 16, 0.35)
        self._remove_btn.setIcon(QIcon(pixmap))
        if self._remove_cancel_timer:
            self._remove_cancel_timer.stop()
        self._remove_cancel_timer = QTimer(self)
        self._remove_cancel_timer.setSingleShot(True)
        self._remove_cancel_timer.timeout.connect(self._cancel_remove)
        self._remove_cancel_timer.start(7000)

    def _on_confirm_remove(self) -> None:
        self.db.set_book_excluded(self._book_path, True)
        self._cancel_remove()
        self.book_removed.emit()
        if self._context != 'library':
            self._refresh_archived_state()

    def _cancel_remove(self) -> None:
        self._confirming_remove = False
        self._confirm_remove_label.setVisible(False)
        self._duration_label.setVisible(True)
        self._remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if self._remove_cancel_timer:
            self._remove_cancel_timer.stop()
            self._remove_cancel_timer = None
        self._update_remove_btn_icon()

    def _refresh_archived_state(self) -> None:
        _book_dict = self.db.get_book_dict(self._book_path)
        self._is_archived = (
            _book_dict is None or
            bool(_book_dict.get('is_deleted')) or
            bool(_book_dict.get('is_excluded'))
        )
        self._remove_btn.setVisible(not self._is_archived)
        self._ghost_label.setVisible(self._is_archived)
        if self._is_archived:
            pixmap = load_themed_icon("ghost.svg", self._theme.get("accent", "#888888"), 16, 0.7)
            self._ghost_label.setPixmap(pixmap)
        if any(self._locks.values()):
            self._set_meta_state(_MetaActionState.LOCKED)
        else:
            self._set_meta_state(_MetaActionState.HIDDEN)
        cover_pixmap = self._cover_label.pixmap()
        if cover_pixmap and not cover_pixmap.isNull():
            self._apply_cover(QPixmap(cover_pixmap))

    def on_theme_changed(self, theme: dict):
        from PySide6.QtGui import QColor
        self._theme = theme
        self._apply_bar_colors()
        self._style_completer_popup()
        self._update_remove_btn_icon()
        self._set_meta_state(self._meta_state)
        self._update_finished_icon(self._finished_label.isVisible())
        self._cover_panel.on_theme_changed(theme)
        self._rebuild_tag_display(self._tag_display_tags)
        self._ctx_menu.apply_theme(theme)
        if self._ghost_label.isVisible():
            pixmap = load_themed_icon("ghost.svg", theme.get("accent", "#888888"), 16, 0.7)
            self._ghost_label.setPixmap(pixmap)

    @staticmethod
    def _fmt(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        if h > 0:
            return f"{h}h {m}m"
        return f"{m}m"


class _RecentHistoryWidget(QWidget):
    """Non-scrollable panel showing up to 4 recent sessions, rows stacked from the bottom."""

    # Row height (13px font + 2px top margin) × 4 rows + 6px spacing × 3 gaps
    _ROW_H = 18
    _ROW_SPACING = 6
    _MAX_ROWS = 4
    FIXED_HEIGHT = _ROW_H * _MAX_ROWS + _ROW_SPACING * (_MAX_ROWS - 1)  # 90px

    def __init__(self, parent=None):
        super().__init__(parent)
        self._accent = QColor("#9B59B6")
        self._bg = QColor("#3A1A50")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(self._ROW_SPACING)
        self._layout.addStretch()
        self.setFixedHeight(self.FIXED_HEIGHT)

    def set_colors(self, accent: QColor, bg: QColor):
        self._accent = accent
        self._bg = bg
        for i in range(self._layout.count() - 1):
            item = self._layout.itemAt(i)
            if item and item.widget():
                bar = item.widget().findChild(_RangeBar)
                if bar:
                    bar.set_colors(accent, bg)

    def set_data(self, sessions: list, duration: float):
        while self._layout.count() > 1:
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for s in sessions:
            row = self._make_row(s, duration)
            self._layout.insertWidget(self._layout.count() - 1, row)

    def _make_row(self, s: dict, duration: float) -> QWidget:
        from datetime import timedelta
        row = QWidget()
        hbox = QHBoxLayout(row)
        hbox.setContentsMargins(0, 2, 0, 0)
        hbox.setSpacing(4)

        try:
            dt_start = datetime.fromisoformat(s['session_start'])
            secs = s.get('listened_seconds') or 0.0
            dt_end = dt_start + timedelta(seconds=secs)
            ts_text = (
                f"{dt_start.strftime('%b')} {dt_start.day}"
                f" {dt_start.strftime('%H:%M')}–{dt_end.strftime('%H:%M')}"
            )
        except Exception:
            ts_text = s.get('session_start', '—')

        ts_label = QLabel(ts_text)
        ts_label.setObjectName("stats_session_label")
        ts_label.setFixedWidth(92)
        hbox.addWidget(ts_label)

        pos_start = s.get('position_start') or 0.0
        pos_end = s.get('position_end') or 0.0

        if duration > 0:
            def fmt_pct(v):
                return f"{v:.0f}%" if round(v, 1) % 1 == 0 else f"{v:.1f}%"
            raw_delta = (pos_end - pos_start) / duration * 100
            delta = min(100.0, max(-100.0, raw_delta))
            delta_str = f"+{fmt_pct(delta)}" if delta >= 0 else fmt_pct(delta)
            delta_label = QLabel(delta_str)
            pct = min(100, round((pos_end / duration) * 100))
            pct_label = QLabel(fmt_pct(pct))
        else:
            delta_label = QLabel("")
            pct_label = QLabel("")

        delta_label.setObjectName("stats_value_label")
        delta_label.setFixedWidth(36)
        delta_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        hbox.addWidget(delta_label)
        hbox.addSpacing(6)

        bar = _RangeBar(pos_start, pos_end, duration, self._accent, self._bg)
        bar.setFixedHeight(6)
        hbox.addWidget(bar, stretch=1)

        pct_label.setObjectName("stats_value_label")
        pct_label.setFixedWidth(32)
        pct_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        hbox.addWidget(pct_label)

        return row
