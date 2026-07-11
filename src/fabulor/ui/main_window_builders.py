"""UI construction helpers extracted from app.py's MainWindow.

Each function takes ``mw`` (the MainWindow instance) and assigns widgets onto it
exactly as the original ``MainWindow._build_*`` methods did. This is a pure
mechanical extraction: ``self`` became ``mw``; nothing else changed. Widgets
still live as attributes on MainWindow, so the interface classes
(VisualsInterface, UICallbackInterface, etc.) and their ``hasattr`` checks are
unaffected.

Do NOT add behavior here. These are layout builders only. The call order in
``MainWindow._setup_ui`` is load-bearing and must not change.
"""
import os

from PySide6.QtWidgets import (
    QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QStackedWidget,
    QSizePolicy, QGraphicsOpacityEffect, QTabWidget, QListWidget,
)
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QSize, QObject, QEvent
from PySide6.QtGui import QPixmap, QFont, QFontMetrics

from .title_bar import TitleBar, RightClickButton, ThemeItem
from .controls import ClickSlider, ScrollingLabel, HoverButton, FreezableLabel, ShimmerButton, RevertButton
from .carousel import CAROUSEL_STRIPE_W, CAROUSEL_STRIPE_PAD, CAROUSEL_COVER_W
from .library import LibraryPanel
from .stats_panel import StatsPanel
from .tag_manager import TagManagerWidget
from .book_detail_panel import BookDetailPanel
from .audio_controls import AudioSettingsTab
from .excluded_books import ExcludedBooksSection
from .ui_helpers import COVER_AREA_HEIGHT, _load_svg_icon


class _PathListEventFilter(QObject):
    def __init__(self, list_widget):
        super().__init__(list_widget)
        self.list_widget = list_widget

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonPress:
            index = self.list_widget.indexAt(event.pos())
            if not index.isValid():
                self.list_widget.clearSelection()
        return super().eventFilter(obj, event)


def build_status_banner(mw):
    mw.status_banner = QWidget(mw)
    mw.status_banner.setObjectName("status_banner")
    mw.status_banner.setAttribute(Qt.WA_StyledBackground, True)
    mw.status_banner.setFixedHeight(36)
    mw.status_banner.hide()

    layout = QHBoxLayout(mw.status_banner)
    layout.setContentsMargins(10, 2, 2, 2)

    mw.status_label = QLabel("")
    mw.status_label.setAlignment(Qt.AlignCenter)
    # Minimum width pinned to the longer of the two EOF-prompt strings ("Marked
    # as finished." / "Finished status reverted.") so that swapping between them
    # doesn't change the centered [status_label, eof_revert_btn] group's total
    # width — which would otherwise shift eof_revert_btn sideways when the text
    # changes. A minimum (not a hard fixed width) lets other, longer banner
    # messages (e.g. scan progress) still grow past it without clipping.
    # font-size must match the QSS rule (QWidget#status_banner QLabel, 15px)
    # since the stylesheet overrides whatever point size .font() reports here.
    _status_font = QFont(mw.status_label.font())
    _status_font.setPixelSize(15)
    mw.status_label.setMinimumWidth(QFontMetrics(_status_font).horizontalAdvance("Finished status reverted."))

    mw.eof_revert_btn = RevertButton()
    mw.eof_revert_btn.setObjectName("eof_revert_btn")
    mw.eof_revert_btn.setFixedSize(22, 22)
    mw.eof_revert_btn.setCursor(Qt.PointingHandCursor)
    mw.eof_revert_btn.setFocusPolicy(Qt.NoFocus)  # chrome button — keep out of the focus chain
    mw.eof_revert_btn.hide()

    mw.eof_close_btn = QPushButton("✕")
    mw.eof_close_btn.setObjectName("eof_close_btn")
    mw.eof_close_btn.setFixedSize(18, 18)
    mw.eof_close_btn.setCursor(Qt.PointingHandCursor)
    mw.eof_close_btn.setFocusPolicy(Qt.NoFocus)  # chrome button — keep out of the focus chain
    mw.eof_close_btn.hide()

    mw.cancel_scan_btn = QPushButton("✕")
    mw.cancel_scan_btn.setObjectName("cancel_scan_btn")
    mw.cancel_scan_btn.setFixedSize(20, 20)
    mw.cancel_scan_btn.setToolTip("Cancel scan")
    mw.cancel_scan_btn.setFocusPolicy(Qt.NoFocus)  # chrome button — keep out of the focus chain

    layout.addStretch()
    layout.addWidget(mw.status_label, 0, Qt.AlignVCenter)
    layout.addWidget(mw.eof_revert_btn, 0, Qt.AlignVCenter)
    layout.addStretch()
    layout.addWidget(mw.eof_close_btn, 0, Qt.AlignTop | Qt.AlignRight)
    layout.addWidget(mw.cancel_scan_btn, 0, Qt.AlignVCenter)


def build_title_bar(mw):
    mw.title_bar = TitleBar(mw)
    mw.root_layout.addWidget(mw.title_bar)


def build_progress_bar(mw):
    mw.progress_slider = ClickSlider(Qt.Horizontal)
    mw.progress_slider.setObjectName("overall_progress")
    mw.progress_slider.sliderPressed.connect(mw._hide_popups)
    mw.progress_slider.setRange(0, 1000)
    mw.progress_slider.setFixedHeight(24)
    mw.progress_slider.sliderPressed.connect(mw._on_slider_pressed)
    mw.progress_slider.sliderReleased.connect(mw._on_slider_released)
    mw.progress_slider.rightClicked.connect(mw._on_slider_right_clicked)
    mw.root_layout.addWidget(mw.progress_slider)

    mw.progress_percentage_label = QLabel(mw.progress_slider)
    mw.progress_percentage_label.setObjectName("percentage_label")
    mw.progress_percentage_label.setAlignment(Qt.AlignCenter)
    mw.progress_percentage_label.setAttribute(Qt.WA_TransparentForMouseEvents)


def build_cover_art(mw):
    mw.cover_art_label = QLabel()
    mw.cover_art_label.setAlignment(Qt.AlignCenter)
    mw.cover_art_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    mw.cover_art_label.setMinimumSize(0, 0)
    mw.cover_art_label.setFixedHeight(COVER_AREA_HEIGHT)
    mw.cover_art_label.mousePressEvent = mw._on_drag_area_pressed
    mw.visual_layout.addWidget(mw.cover_art_label)


def build_metadata(mw):
    # Scan section: prompt + button, spacer-positioned, claims remaining space.
    mw.scan_section = QWidget()
    scan_layout = QVBoxLayout(mw.scan_section)
    scan_layout.setContentsMargins(0, 0, 0, 0)
    scan_layout.setSpacing(0)           # spacing controlled manually via addSpacing

    mw.library_prompt_label = QLabel("No library folders.")
    mw.library_prompt_label.setAlignment(Qt.AlignCenter)
    mw.library_prompt_label.setStyleSheet("font-weight: bold; font-size: 16px;")
    scan_layout.addSpacing(80)          # label top lands at 50px from section top
    scan_layout.addWidget(mw.library_prompt_label)
    scan_layout.addSpacing(80)          # ~80px gap → button top lands at ~150px from section top
                                        # (exact value depends on label height; tune if needed)
    mw.scan_now_btn = QPushButton("Scan now")
    mw.scan_now_btn.setFixedWidth(120)
    mw.scan_now_btn.setFocusPolicy(Qt.NoFocus)  # chrome button — keep out of the focus chain
    scan_layout.addWidget(mw.scan_now_btn, 0, Qt.AlignCenter)
    scan_layout.addStretch()            # eat remaining space below the button
    mw.visual_layout.addWidget(mw.scan_section, 1)  # stretch 1: claims remaining space

    # Metadata (Book Info) — shared with player state (shows "Author - Title" for no-cover books)
    mw.metadata_label = QLabel("")
    mw.metadata_label.setAlignment(Qt.AlignCenter)
    mw.metadata_label.setWordWrap(True)
    mw.metadata_label.mousePressEvent = mw._on_drag_area_pressed
    mw.visual_layout.addWidget(mw.metadata_label)

    # No-book section — permanent fixed slot; never inserted/removed at runtime.
    mw.no_book_section = QWidget()
    nb_layout = QVBoxLayout(mw.no_book_section)
    nb_layout.setContentsMargins(0, 0, 0, 0)
    nb_layout.setSpacing(0)

    nb_layout.addSpacing(80)
    mw.no_book_label = QLabel("No book selected.")
    mw.no_book_label.setAlignment(Qt.AlignCenter)
    mw.no_book_label.setStyleSheet("font-weight: bold; font-size: 16px;")
    nb_layout.addWidget(mw.no_book_label)

    nb_layout.addSpacing(125)

    # Permanent carousel slot — always reserves height whether or not a carousel is inside.
    mw.carousel_holder = QWidget()
    mw.carousel_holder.setFixedHeight(140 + 2 * CAROUSEL_STRIPE_PAD)
    mw.carousel_holder.setFixedWidth(CAROUSEL_STRIPE_W)
    ch_layout = QVBoxLayout(mw.carousel_holder)
    ch_layout.setContentsMargins(0, 0, 0, 0)
    ch_layout.setSpacing(0)
    nb_layout.addWidget(mw.carousel_holder, 0, Qt.AlignHCenter)

    nb_layout.addSpacing(12)

    mw.go_to_library_btn = QPushButton("Go to Library")
    mw.go_to_library_btn.setObjectName("go_to_library_btn")
    mw.go_to_library_btn.setFixedWidth(110)
    mw.go_to_library_btn.setFocusPolicy(Qt.NoFocus)  # chrome button — keep out of the focus chain
    nb_layout.addWidget(mw.go_to_library_btn, 0, Qt.AlignCenter)

    nb_layout.addStretch()

    mw.no_book_section.hide()
    mw.visual_layout.addWidget(mw.no_book_section)

    # Quote section: fixed-height box, quote bottom-anchored, expands upward.
    mw.quote_section = QWidget()
    mw.quote_section.setFixedHeight(238)
    quote_layout = QVBoxLayout(mw.quote_section)
    quote_layout.setContentsMargins(0, 0, 0, 0)
    mw.quote_label = QLabel("")
    mw.quote_label.setObjectName("quote_label")
    mw.quote_label.setAlignment(Qt.AlignBottom | Qt.AlignHCenter)
    mw.quote_label.setWordWrap(True)
    quote_layout.addWidget(mw.quote_label, 0, Qt.AlignBottom)
    mw.visual_layout.addWidget(mw.quote_section)


def build_controls(mw):
    # Speed button centered above transport controls
    speed_row = QHBoxLayout()
    speed_row.addStretch()
    mw.speed_button = ShimmerButton("1.00x")
    mw.speed_button.setObjectName("speed_btn")
    mw.speed_button.setFixedWidth(60)
    mw.speed_button.setFixedHeight(33)
    # No keyboard focus: otherwise this is the first StrongFocus widget created, so Qt
    # auto-focuses it at startup and Space fires its clicked (opens speed menu) instead of
    # reaching the global play/pause shortcut. Still fully mouse-clickable. See title-bar /
    # transport buttons for the same treatment.
    mw.speed_button.setFocusPolicy(Qt.NoFocus)
    mw.speed_button.setContextMenuPolicy(Qt.CustomContextMenu)
    mw.speed_button.customContextMenuRequested.connect(mw._on_speed_right_clicked)
    mw.speed_button.clicked.connect(mw._on_speed_button_clicked)
    speed_row.addWidget(mw.speed_button)
    mw.content_layout.addLayout(speed_row)

    # Chapter preview label (dynamic visibility on hover)
    mw.preview_row = QHBoxLayout()
    mw.preview_row.setContentsMargins(0, 0, 0, 0)
    mw.chapter_preview_label = QLabel("")
    mw.chapter_preview_label.setObjectName("chapter_preview_label")
    mw.chapter_preview_label.setFixedHeight(21) # Reserve space to prevent layout jumping
    mw.chapter_preview_label.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
    mw.preview_row.addWidget(mw.chapter_preview_label)
    mw.content_layout.addLayout(mw.preview_row)

    # Setup fade animation
    mw.preview_opacity = QGraphicsOpacityEffect(mw.chapter_preview_label)
    mw.preview_opacity.setOpacity(0.0)
    mw.chapter_preview_label.setGraphicsEffect(mw.preview_opacity)

    mw.preview_anim = QPropertyAnimation(mw.preview_opacity, b"opacity")
    mw.preview_anim.setDuration(600)
    mw.preview_anim.setEasingCurve(QEasingCurve.OutCubic)

    mw.transport_controls = QWidget()
    controls_layout = QHBoxLayout(mw.transport_controls)
    controls_layout.setContentsMargins(0, 0, 0, 0)
    controls_layout.setSpacing(10)
    mw.prev_button = HoverButton()
    mw.prev_button.setObjectName("prev_btn")
    _icon = _load_svg_icon("previous.svg")
    if _icon.isNull():
        mw.prev_button.setText("|<<")
    else:
        mw.prev_button.setIcon(_icon)
    mw.prev_button.setFixedSize(46, 33)
    mw.prev_button.setIconSize(QSize(32, 22))
    mw.rewind_button = RightClickButton("")
    mw.rewind_button.setObjectName("rewind_btn")
    mw.rewind_button.setFixedSize(46, 33)
    mw.rewind_button.setIconSize(QSize(28, 17))
    mw.rewind_button.setAutoRepeat(True)
    mw.rewind_button.setAutoRepeatDelay(500)   # Wait 500ms before scanning
    mw.rewind_button.setAutoRepeatInterval(150) # Skip again every 150ms
    mw.play_pause_button = QPushButton()
    mw.play_pause_button.setObjectName("play_pause_btn")
    mw._icon_play = _load_svg_icon("play.svg")
    mw._icon_pause = _load_svg_icon("pause.svg")
    mw._icon_restart = _load_svg_icon("restart.svg")
    mw._icon_rewind  = {5: _load_svg_icon("rewind_5.svg"),  10: _load_svg_icon("rewind_10.svg"),  30: _load_svg_icon("rewind_30.svg")}
    mw._icon_forward = {5: _load_svg_icon("forward_5.svg"), 10: _load_svg_icon("forward_10.svg"), 30: _load_svg_icon("forward_30.svg")}
    if mw._icon_play.isNull():
        mw.play_pause_button.setText("Play")
    else:
        mw.play_pause_button.setIcon(mw._icon_play)
    mw.play_pause_button.setFixedSize(56, 33)
    mw.play_pause_button.setIconSize(QSize(52, 33))
    mw.forward_button = RightClickButton("")
    mw.forward_button.setObjectName("forward_btn")
    mw.forward_button.setFixedSize(46, 33)
    mw.forward_button.setIconSize(QSize(28, 17))
    mw.forward_button.setAutoRepeat(True)
    mw.forward_button.setAutoRepeatDelay(500)
    mw.forward_button.setAutoRepeatInterval(150)
    mw.next_button = HoverButton()
    mw.next_button.setObjectName("next_btn")
    _icon = _load_svg_icon("next.svg")
    if _icon.isNull():
        mw.next_button.setText(">>|")
    else:
        mw.next_button.setIcon(_icon)
    mw.next_button.setFixedSize(46, 33)
    mw.next_button.setIconSize(QSize(32, 22))
    for btn in [mw.prev_button, mw.rewind_button, mw.play_pause_button,
                mw.forward_button, mw.next_button]:
        btn.setFixedHeight(33)
        # No keyboard focus: otherwise QPushButton fires clicked on Space, swallowing the
        # global Space=play/pause shortcut whenever a transport button held focus (e.g.
        # right after being clicked). Still fully mouse-clickable. Mirrors title-bar chrome.
        btn.setFocusPolicy(Qt.NoFocus)
        controls_layout.addWidget(btn)
    mw.transport_controls.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    mw.content_layout.addWidget(mw.transport_controls)

    mw._reload_button_icons(mw.theme_manager._current_theme_name)
    mw.play_pause_button.clicked.connect(mw.toggle_play_pause)
    mw.prev_button.clicked.connect(mw.handle_prev)
    mw.prev_button.rightClicked.connect(mw._on_prev_right_click)
    mw.rewind_button.clicked.connect(mw.handle_rewind)
    mw.rewind_button.rightClicked.connect(lambda: mw.handle_rewind(long_skip=True))
    mw.forward_button.clicked.connect(mw.handle_forward)
    mw.forward_button.rightClicked.connect(lambda: mw.handle_forward(long_skip=True))
    mw.next_button.clicked.connect(mw.handle_next)

    # Hover signals for chapter previews
    mw.prev_button.hovered.connect(mw._on_prev_hover)
    mw.prev_button.unhovered.connect(mw._clear_preview)
    mw.next_button.hovered.connect(mw._on_next_hover)
    mw.next_button.unhovered.connect(mw._clear_preview)


def build_secondary_controls(mw):
    # 1. Chapter Info Row (Top of secondary stack)
    chapter_info_layout = QHBoxLayout()
    mw.chap_elapsed_label = FreezableLabel("00:00:00")
    mw.chap_elapsed_label.setObjectName("chap_elapsed_label")
    mw.chap_elapsed_label.setFixedWidth(48)
    mw.chap_elapsed_label.setFixedHeight(24)
    mw.chap_elapsed_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

    mw.chap_duration_label = FreezableLabel("00:00:00")
    mw.chap_duration_label.setObjectName("chap_duration_label")
    mw.chap_duration_label.setFixedWidth(48)
    mw.chap_duration_label.setFixedHeight(24)
    mw.chap_duration_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    mw.chap_duration_label.mousePressEvent = lambda e: mw._toggle_remaining_time(mw.chap_duration_label, e)

    mw.current_chapter_label = ScrollingLabel("")
    mw.current_chapter_label.setObjectName("chapter_selector")
    mw.current_chapter_label.setFixedHeight(24)
    mw.current_chapter_label.clicked.connect(mw._show_chapter_dropdown)
    mw.current_chapter_label.set_scroll_mode(mw.config.get_scroll_mode())
    mw._chapter_label_clickable = False
    mw.current_chapter_label.setCursor(Qt.ArrowCursor)

    chapter_info_layout.addWidget(mw.chap_elapsed_label)
    chapter_info_layout.addWidget(mw.current_chapter_label, 1)
    chapter_info_layout.addWidget(mw.chap_duration_label)
    mw.content_layout.addLayout(chapter_info_layout)

    # 2. Chapter Progress Slider
    mw.chapter_progress_slider = ClickSlider(Qt.Horizontal)
    mw.chapter_progress_slider.setObjectName("chapter_progress")
    mw.chapter_progress_slider.setRange(0, 1000)
    mw.chapter_progress_slider.setFixedHeight(13)
    mw.chapter_progress_slider.sliderPressed.connect(mw._hide_popups)
    mw.chapter_progress_slider.sliderPressed.connect(mw._on_chap_slider_pressed)
    mw.chapter_progress_slider.sliderReleased.connect(mw._on_chap_slider_released)
    mw.content_layout.addWidget(mw.chapter_progress_slider)

    # 3. Book Info Row (Elapsed - Speed - Total/Remaining)
    book_info_layout = QHBoxLayout()
    mw.current_time_label = FreezableLabel("00:00:00")
    mw.current_time_label.setObjectName("curr_time_label")
    mw.current_time_label.setFixedWidth(80)
    mw.current_time_label.setFixedHeight(24)
    mw.current_time_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)

    mw.total_time_label = FreezableLabel("00:00:00")
    mw.total_time_label.setObjectName("total_time_label")
    mw.total_time_label.setFixedWidth(80)
    mw.total_time_label.setFixedHeight(24)
    mw.total_time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    mw.total_time_label.mousePressEvent = lambda e: mw._toggle_remaining_time(mw.total_time_label, e)
    mw.total_time_label.setMouseTracking(True)
    mw.total_time_label.mouseMoveEvent = lambda e: mw._on_remaining_time_label_hover(mw.total_time_label, e)

    mw.sleep_timer_label = QPushButton("")
    mw.sleep_timer_label.setObjectName("sleep_timer_display")
    mw.sleep_timer_label.setFixedWidth(104)
    mw.sleep_timer_label.setFocusPolicy(Qt.NoFocus)  # chrome button — keep out of the focus chain
    mw.sleep_timer_label.clicked.connect(mw.sleep_panel.disable_sleep_timer)

    for lbl in [mw.current_time_label, mw.total_time_label, mw.sleep_timer_label]:
        font = lbl.font()
        font.setPointSize(12)
        lbl.setFont(font)

    mw.volume_slider = ClickSlider(Qt.Horizontal)
    mw.volume_slider.setObjectName("volume_slider")
    mw.volume_slider.setRange(0, 100)
    mw.volume_slider.setValue(mw.config.get_volume())
    mw.volume_slider.setFixedHeight(9)
    mw.volume_slider.sliderPressed.connect(mw._hide_popups)
    mw.volume_slider.sliderPressed.connect(mw._on_volume_slider_pressed)
    mw.volume_slider.valueChanged.connect(mw._on_volume_changed)

    mw.vol_stack = QStackedWidget()
    mw.vol_stack.setFixedWidth(104) # Sleep timer location
    mw.vol_stack.setFixedHeight(24)
    mw.vol_stack.addWidget(mw.sleep_timer_label)

    mw.vol_container = QWidget()
    vol_container_layout = QVBoxLayout(mw.vol_container)
    vol_container_layout.setContentsMargins(0, 8, 0, 0) # Volume bar location
    vol_container_layout.setSpacing(0)
    vol_container_layout.addWidget(mw.volume_slider)
    vol_container_layout.addStretch()
    mw.vol_stack.addWidget(mw.vol_container)

    mw.muted_icon_label = QLabel()
    mw.muted_icon_label.setObjectName("muted_icon_label")
    mw.muted_icon_label.setAlignment(Qt.AlignCenter)
    mw.vol_stack.addWidget(mw.muted_icon_label)

    book_info_layout.setSpacing(0)
    book_info_layout.addWidget(mw.current_time_label)
    book_info_layout.addStretch(1)
    book_info_layout.addWidget(mw.vol_stack)
    book_info_layout.addStretch(1)
    book_info_layout.addWidget(mw.total_time_label)
    mw.content_layout.addLayout(book_info_layout)

    # Setup Volume Overlay Animations
    mw.vol_opacity = QGraphicsOpacityEffect(mw.volume_slider)
    mw.vol_opacity.setOpacity(0.0)
    mw.volume_slider.setGraphicsEffect(mw.vol_opacity)

    mw.vol_fade_anim = QPropertyAnimation(mw.vol_opacity, b"opacity")
    mw.vol_fade_anim.setDuration(500) # Slow fade
    mw.vol_fade_anim.setEasingCurve(QEasingCurve.InOutCubic)
    mw.vol_fade_anim.finished.connect(mw._on_vol_fade_finished)

    mw.vol_hide_timer = QTimer(mw)
    mw.vol_hide_timer.setSingleShot(True)
    mw.vol_hide_timer.timeout.connect(mw._fade_out_volume)


def build_carousel_covers(mw):
    """Build (pixmaps, cover_h) for the no-book carousel from cached covers.
    Returns (None, 0) when there are too few covers to bother."""
    import random
    from PIL import Image

    cover_paths = mw.db.get_all_cover_paths()
    if not cover_paths:
        return None, 0
    random.shuffle(cover_paths)
    sample = cover_paths[:100]   # cap to bound large-library cost

    portraits, squares = [], []
    for path in sample:
        try:
            with Image.open(path) as img:
                w, h = img.size   # header-only read; do NOT call img.load()
        except Exception:
            continue
        if w <= 0:
            continue
        ratio = h / w
        if ratio >= 1.4:
            portraits.append(path)
            if len(portraits) >= 12:
                break   # enough portraits found — stop early
        else:
            squares.append(path)
            if len(squares) >= 12 and len(portraits) < 4:
                break   # squares plentiful, portraits too scarce — stop

    if len(portraits) >= 12:
        pool, cover_h = portraits, 140
    elif len(squares) >= 4:
        pool, cover_h = squares, 92
    elif len(portraits) >= 4:
        pool, cover_h = portraits, 140
    else:
        return None, 0   # not enough covers — caller skips carousel

    selected = pool[:12]
    pixmaps = []
    for path in selected:
        pm = QPixmap(path)
        if pm.isNull():
            continue
        pm = pm.scaled(CAROUSEL_COVER_W, cover_h, Qt.KeepAspectRatioByExpanding,
                       Qt.SmoothTransformation)
        if pm.width() > CAROUSEL_COVER_W or pm.height() > cover_h:
            x_off = (pm.width() - CAROUSEL_COVER_W) // 2
            y_off = (pm.height() - cover_h) // 2
            pm = pm.copy(x_off, y_off, CAROUSEL_COVER_W, cover_h)
        pixmaps.append(pm)

    if not pixmaps:
        return None, 0
    return pixmaps, cover_h


def build_sidebar(mw):
    mw.sidebar = QWidget(mw)
    mw.sidebar.setObjectName("sidebar")
    mw.sidebar.setFixedWidth(70)
    mw.sidebar_layout = QVBoxLayout(mw.sidebar)
    mw.sidebar_layout.setContentsMargins(10, 10, 2, 10)

    mw.library_trigger_btn = QPushButton("LIBRARY")
    mw.library_trigger_btn.setObjectName("sidebar_library_btn")
    mw.sidebar_layout.addWidget(mw.library_trigger_btn)

    mw.library_separator = QWidget()
    mw.library_separator.setFixedHeight(10)
    mw.sidebar_layout.addWidget(mw.library_separator)

    mw.settings_trigger_btn = QPushButton("SETTINGS")
    mw.settings_trigger_btn.setObjectName("sidebar_settings_btn")
    mw.sidebar_layout.addWidget(mw.settings_trigger_btn)

    mw.speed_trigger_btn = QPushButton("PLAYBACK")
    mw.speed_trigger_btn.setObjectName("sidebar_speed_btn")
    mw.sidebar_layout.addWidget(mw.speed_trigger_btn)

    mw.sleep_trigger_btn = QPushButton("SLEEP")
    mw.sleep_trigger_btn.setObjectName("sidebar_sleep_btn")
    mw.sidebar_layout.addWidget(mw.sleep_trigger_btn)

    mw.stats_trigger_btn = QPushButton("STATS")
    mw.stats_trigger_btn.setObjectName("sidebar_stats_btn")
    mw.sidebar_layout.addWidget(mw.stats_trigger_btn)

    mw.tags_trigger_btn = QPushButton("TAGS")
    mw.tags_trigger_btn.setObjectName("sidebar_tags_btn")
    mw.sidebar_layout.addWidget(mw.tags_trigger_btn)

    mw.sleep_cancel_btn = QPushButton("✕", mw.sleep_trigger_btn)
    mw.sleep_cancel_btn.setFixedSize(16, 16)
    mw.sleep_cancel_btn.move(34, 1)
    mw.sleep_cancel_btn.setStyleSheet("font-size: 10px; padding: 0;")
    mw.sleep_cancel_btn.clicked.connect(mw.sleep_panel.disable_sleep_timer)
    mw.sleep_cancel_btn.hide()

    # The sidebar is moved off-screen (move(-50,56)) but stays show()n when "closed", so its
    # buttons live in the keyboard focus chain permanently. Without NoFocus, arrow/Tab keys
    # cycle focus onto these hidden triggers and Space fires their clicked — opening panels
    # one by one — instead of reaching the global transport shortcuts. NoFocus keeps them
    # mouse-only; the sidebar's own open/close mechanics are untouched.
    for _btn in (mw.library_trigger_btn, mw.settings_trigger_btn, mw.speed_trigger_btn,
                 mw.sleep_trigger_btn, mw.stats_trigger_btn, mw.tags_trigger_btn,
                 mw.sleep_cancel_btn):
        _btn.setFocusPolicy(Qt.NoFocus)

    mw.sidebar_layout.addStretch()
    mw.sidebar.move(-50, 56)
    mw.sidebar.show()
    mw.sidebar_animation = QPropertyAnimation(mw.sidebar, b"pos")
    mw.sidebar_animation.setDuration(300)
    mw.sidebar_animation.setEasingCurve(QEasingCurve.OutCubic)


def build_library_panel(mw):
    mw.library_panel = LibraryPanel(mw.db, mw.config, player_instance=mw.player, parent=mw)
    mw.library_panel.hide()
    mw.library_panel.set_hover_fade_enabled(mw.config.get_hover_fade_mode())
    mw.library_panel_animation = QPropertyAnimation(mw.library_panel, b"pos")
    mw.library_panel_animation.setDuration(300)
    mw.library_panel_animation.setEasingCurve(QEasingCurve.OutCubic)


def build_stats_panel(mw):
    mw.stats_panel = StatsPanel(mw.db, mw.config, parent=mw)
    mw.theme_manager.theme_applied.connect(mw.stats_panel.on_theme_changed)
    mw.stats_panel.on_theme_changed(mw.theme_manager.get_current_theme())
    mw.stats_panel.hide()
    mw.stats_panel_animation = QPropertyAnimation(mw.stats_panel, b"pos")
    mw.stats_panel_animation.setDuration(300)
    mw.stats_panel_animation.setEasingCurve(QEasingCurve.OutCubic)


def build_tags_panel(mw):
    _assets_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "assets"))
    mw.tags_panel = TagManagerWidget(mw.db, _assets_dir, parent=mw)
    mw.tags_panel.hide()
    mw.tags_panel_animation = QPropertyAnimation(mw.tags_panel, b"pos")
    mw.tags_panel_animation.setDuration(200)
    mw.tags_panel_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
    mw.theme_manager.theme_applied.connect(mw.tags_panel.on_theme_changed)
    mw.tags_panel.on_theme_changed(mw.theme_manager.get_current_theme())


def build_book_detail_panel(mw):
    mw.book_detail_panel = BookDetailPanel(mw.db, mw.config, parent=mw)
    mw.book_detail_panel.hide()
    mw.book_detail_panel_animation = QPropertyAnimation(
        mw.book_detail_panel, b"pos"
    )
    mw.book_detail_panel_animation.setDuration(300)
    mw.book_detail_panel_animation.setEasingCurve(QEasingCurve.OutCubic)
    mw.panel_manager.book_detail_panel = mw.book_detail_panel
    mw.panel_manager.book_detail_panel_animation = mw.book_detail_panel_animation
    mw.book_detail_panel.close_requested.connect(
        mw.panel_manager._close_book_detail_flow
    )
    mw.book_detail_panel.history_deleted.connect(mw.stats_panel.refresh_all)
    mw.book_detail_panel.history_deleted.connect(mw.library_panel.refresh)
    mw.book_detail_panel.metadata_saved.connect(mw._on_book_metadata_saved)
    mw.book_detail_panel.tags_changed.connect(mw._on_book_tags_changed)
    mw.tags_panel.tag_changed.connect(mw.stats_panel._on_tag_changed)
    mw.tags_panel.detail_requested.connect(
        lambda path: mw.panel_manager.open_book_detail({"path": path}, tab="stats", context='tags')
    )
    mw.book_detail_panel.active_cover_changed.connect(mw._on_active_cover_changed)
    mw.book_detail_panel.active_cover_changed.connect(
        lambda book_path, cover_path: mw.stats_panel.on_cover_changed(book_path, cover_path)
    )
    mw.book_detail_panel.book_removed.connect(mw._on_book_detail_removed)
    mw.book_detail_panel.tag_filter_requested.connect(mw._on_tag_filter_requested)
    mw.book_detail_panel.open_tag_manager_requested.connect(mw._on_open_tag_manager_from_detail)
    mw.theme_manager.theme_applied.connect(mw.book_detail_panel.on_theme_changed)
    mw.book_detail_panel.on_theme_changed(mw.theme_manager.get_current_theme())


def build_settings_panel(mw):
    mw.settings_panel = QWidget(mw)
    mw.settings_panel.setObjectName("settings_panel")
    settings_layout = QVBoxLayout(mw.settings_panel)
    settings_layout.setContentsMargins(5, 5, 5, 5)

    mw.tabs = QTabWidget()
    mw.tabs.setObjectName("settings_tabs")

    # Intra-module calls: these tab builders live in this same module, so they are
    # plain function calls, NOT mw._build_* (no longer MainWindow methods).
    build_themes_tab(mw)
    build_appearance_tab(mw)
    build_library_tab(mw)
    build_audio_tab(mw)
    build_controls_tab(mw)

    settings_layout.addWidget(mw.tabs)
    mw.settings_panel.hide()
    mw.settings_panel_animation = QPropertyAnimation(mw.settings_panel, b"pos")
    mw.settings_panel_animation.setDuration(300)
    mw.settings_panel_animation.setEasingCurve(QEasingCurve.OutCubic)


def build_themes_tab(mw):
    themes_tab = QWidget()
    themes_layout = QVBoxLayout(themes_tab)
    themes_layout.setContentsMargins(10, 0, 10, 10)

    # Cover art based theme
    cover_header = QLabel("Cover art based theme")
    cover_header.setObjectName("settings_header")
    themes_layout.addWidget(cover_header)

    cover_row = QHBoxLayout()
    cover_row.setSpacing(4)
    cover_row.setContentsMargins(0, 0, 0, 0)
    mw.theme_manager.cover_art_mode_widgets = {}
    for mode, label in [("off", "Off"), ("with_pool", "With pool"), ("exclusive", "Exclusive")]:
        btn = QPushButton(label)
        btn.setObjectName("pattern_button")
        btn.clicked.connect(lambda _, m=mode: mw.theme_manager.set_cover_art_mode(m))
        mw.theme_manager.cover_art_mode_widgets[mode] = btn
        cover_row.addWidget(btn)
    cover_row.addStretch()
    themes_layout.addLayout(cover_row)

    # Pool + controls container (hidden when Exclusive is active)
    mw.theme_manager.pool_container = QWidget()
    pool_layout = QVBoxLayout(mw.theme_manager.pool_container)
    pool_layout.setContentsMargins(0, 0, 0, 0)
    pool_layout.setSpacing(0)

    # Theme pool
    pool_header = QLabel("Theme pool")
    pool_header.setObjectName("settings_header")
    pool_layout.addWidget(pool_header)

    # Cover art based theme entry — always present, state reflects mode and cover availability
    cover_pool_row = QHBoxLayout()
    cover_pool_row.setContentsMargins(0, 0, 0, 0)
    cover_pool_row.setSpacing(0)
    cover_pool_btn = ThemeItem("Cover art based theme")
    cover_pool_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    cover_pool_btn.clicked.connect(lambda: mw.theme_manager._on_cover_pool_btn_clicked())
    cover_pool_btn.rightClicked.connect(lambda: mw.theme_manager._on_cover_pool_btn_right_clicked())
    cover_pool_btn.hovered.connect(lambda _: mw.theme_manager._on_cover_pool_btn_hovered())
    mw.theme_manager.cover_pool_btn = cover_pool_btn
    cover_pool_row.addWidget(cover_pool_btn)
    pool_layout.addLayout(cover_pool_row)
    mw.theme_manager.theme_widgets = {}

    limit = max(230, mw.settings_panel.width() - 20)
    for row_items in mw.theme_manager.get_packed_themes(limit=limit):
        row_layout = QHBoxLayout()
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)

        for item in row_items:
            btn = ThemeItem(item['name'])
            btn.setMinimumWidth(item['width'])
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            btn.clicked.connect(lambda _, n=item['name']: mw.theme_manager.toggle_theme_selection(n))
            btn.rightClicked.connect(lambda n=item['name']: mw.theme_manager._on_theme_right_clicked(n))
            btn.hovered.connect(mw.theme_manager._on_theme_hovered)
            mw.theme_manager.theme_widgets[item['name']] = btn
            row_layout.addWidget(btn, item['width'])

        if len(row_items) == 1:
            row_layout.addStretch()

        pool_layout.addLayout(row_layout)

    themes_tab.leaveEvent = lambda _: mw.theme_manager._on_theme_unhovered()

    # Add/Remove All Buttons
    bulk_layout = QHBoxLayout()
    bulk_layout.setSpacing(10)
    mw.add_all_btn = QPushButton("Add all")
    mw.add_all_btn.setObjectName("theme_add_all")
    mw.add_all_btn.setFixedWidth(80)
    mw.remove_all_btn = QPushButton("Remove all")
    mw.remove_all_btn.setObjectName("theme_remove_all")
    mw.remove_all_btn.setFixedWidth(80)
    mw.change_now_btn = QPushButton("Change now")
    mw.change_now_btn.setObjectName("theme_change_now")

    mw.add_all_btn.clicked.connect(mw.theme_manager.select_all_themes)
    mw.remove_all_btn.clicked.connect(mw.theme_manager.deselect_all_themes)
    mw.change_now_btn.clicked.connect(lambda: mw.theme_manager._do_rotate(user_initiated=True))

    bulk_layout.addWidget(mw.add_all_btn)
    bulk_layout.addWidget(mw.remove_all_btn)
    bulk_layout.addWidget(mw.change_now_btn)
    bulk_layout.addStretch()
    pool_layout.addLayout(bulk_layout)

    # Interval Selection
    interval_row = QHBoxLayout()
    interval_row.setSpacing(10)
    interval_row.setContentsMargins(0, 10, 0, 0)

    interval_label = QLabel("Interval (min)")
    interval_label.setObjectName("theme_hint")
    interval_row.addWidget(interval_label)
    interval_row.addSpacing(13)

    intervals = [(2, "2"), (5, "5"), (10, "10"), (20, "20"), (30, "30"), (60, "60"), (120, "120"), (0, "Off")]
    for mins, text in intervals:
        lbl = QLabel(text)
        lbl.setObjectName("theme_interval_label")
        lbl.setCursor(Qt.PointingHandCursor)
        lbl.setAlignment(Qt.AlignCenter)
        # Fixed at the BOLD variant's width (always >= regular width) so the
        # selected/unselected toggle (font-weight change) never reflows siblings.
        # font-size must match the QSS rule (theme_interval_label, 12px) since the
        # stylesheet's font-size overrides whatever point size lbl.font() reports here.
        bold_font = QFont(lbl.font())
        bold_font.setPixelSize(12)
        bold_font.setBold(True)
        lbl.setFixedWidth(QFontMetrics(bold_font).horizontalAdvance(text))
        lbl.mousePressEvent = lambda _, m=mins: mw.theme_manager.set_rotation_interval(m)
        mw.theme_manager.interval_widgets[mins] = lbl
        interval_row.addWidget(lbl)
    interval_row.addStretch()
    pool_layout.addLayout(interval_row)

    mw.theme_manager.pool_container.leaveEvent = lambda _: mw.theme_manager._on_theme_unhovered()
    themes_layout.addWidget(mw.theme_manager.pool_container)
    themes_layout.addStretch()
    mw.tabs.addTab(themes_tab, "Themes")
    mw.theme_manager.update_theme_list_visuals()
    mw.theme_manager.update_interval_visuals()
    mw.theme_manager.update_cover_art_mode_visuals()


def build_appearance_tab(mw):
    appearance_tab = QWidget()
    app_layout = QVBoxLayout(appearance_tab)
    app_layout.setContentsMargins(10, 0, 10, 10)

    fade_header = QLabel("Theme hover (ms)")
    fade_header.setObjectName("settings_header")
    app_layout.addWidget(fade_header)

    fade_row = QHBoxLayout()
    mw.fade_buttons = {}
    for ms_val in [0, 500, 750, 1000, 1500]:
        label = "Off" if ms_val == 0 else str(ms_val)
        btn = QPushButton(label)
        btn.setObjectName("pattern_button")
        btn.clicked.connect(lambda _, v=ms_val: mw.fade_mode_changed.emit(v))
        fade_row.addWidget(btn)
        mw.fade_buttons[ms_val] = btn
    fade_row.addStretch()
    app_layout.addLayout(fade_row)

    blur_header = QLabel("Blur")
    blur_header.setObjectName("settings_header")
    app_layout.addWidget(blur_header)

    blur_row = QHBoxLayout()
    mw.blur_buttons = {}
    for state in ["On", "Off"]:
        btn = QPushButton(state)
        btn.setObjectName("pattern_button")
        btn.clicked.connect(lambda _, s=state: mw.blur_mode_changed.emit(s == "On"))
        blur_row.addWidget(btn)
        mw.blur_buttons[state] = btn
    blur_row.addStretch()
    app_layout.addLayout(blur_row)

    scroll_header = QLabel("Chapter scroll")
    scroll_header.setObjectName("settings_header")
    app_layout.addWidget(scroll_header)

    scroll_row = QHBoxLayout()
    mw.scroll_buttons = {}
    for mode in ["Slow", "Normal", "Off"]:
        btn = QPushButton(mode)
        btn.setObjectName("pattern_button") # Re-use styling for consistency
        btn.clicked.connect(lambda _, m=mode: mw.scroll_mode_changed.emit(m))
        scroll_row.addWidget(btn)
        mw.scroll_buttons[mode] = btn
    scroll_row.addStretch()
    app_layout.addLayout(scroll_row)

    hover_fade_header = QLabel("Library hover trail")
    hover_fade_header.setObjectName("settings_header")
    app_layout.addWidget(hover_fade_header)

    hover_fade_row = QHBoxLayout()
    mw.hover_fade_buttons = {}
    for mode in ["Slow", "Normal", "Fast", "Off"]:
        btn = QPushButton(mode)
        btn.setObjectName("pattern_button")
        btn.clicked.connect(lambda _, m=mode: mw.hover_fade_changed.emit(m))
        hover_fade_row.addWidget(btn)
        mw.hover_fade_buttons[mode] = btn
    hover_fade_row.addStretch()
    app_layout.addLayout(hover_fade_row)

    hints_header = QLabel("Chapter hints")
    hints_header.setObjectName("settings_header")
    app_layout.addWidget(hints_header)

    hints_row = QHBoxLayout()
    mw.hints_buttons = {}
    for mode in ["Sticky", "Transient", "Off"]:
        btn = QPushButton(mode)
        btn.setObjectName("pattern_button")
        btn.clicked.connect(lambda _, m=mode: mw.hints_mode_changed.emit(m))
        hints_row.addWidget(btn)
        mw.hints_buttons[mode] = btn
    hints_row.addStretch()
    app_layout.addLayout(hints_row)

    notches_header_row = QHBoxLayout()
    notches_label = QLabel("Chapter notches")
    notches_label.setObjectName("settings_header")
    notches_header_row.addWidget(notches_label)
    notches_header_row.addStretch()

    mw.notches_anim_header_label = QLabel("Animation")
    mw.notches_anim_header_label.setObjectName("settings_header")
    mw.notches_anim_header_label.setVisible(False)
    notches_header_row.addWidget(mw.notches_anim_header_label)
    app_layout.addLayout(notches_header_row)

    notches_row = QHBoxLayout()
    mw.notches_buttons = {}
    for mode in ["On", "Off"]:
        btn = QPushButton(mode)
        btn.setObjectName("pattern_button")
        btn.clicked.connect(lambda _, m=mode: mw.notches_mode_changed.emit(m == "On"))
        notches_row.addWidget(btn)
        mw.notches_buttons[mode] = btn
    notches_row.addStretch()

    mw.notch_animation_buttons = {}
    for mode in ["On", "Off"]:
        btn = QPushButton(mode)
        btn.setObjectName("pattern_button")
        btn.setVisible(False)
        btn.clicked.connect(lambda _, m=mode: mw.notch_animation_mode_changed.emit(m == "On"))
        notches_row.addWidget(btn)
        mw.notch_animation_buttons[mode] = btn

    app_layout.addLayout(notches_row)

    app_layout.addStretch()
    mw.tabs.addTab(appearance_tab, "Look")
    # Visual initialization moved to after SettingsController binding


def build_library_tab(mw):
    library_tab = QWidget()
    lib_layout = QVBoxLayout(library_tab)
    lib_layout.setContentsMargins(10, 0, 10, 10)

    folders_header = QLabel("Manage folders")
    folders_header.setObjectName("settings_header")
    lib_layout.addWidget(folders_header)

    mw.folder_list_widget = QListWidget()
    mw.folder_list_widget.setObjectName("settings_folder_list")
    mw.folder_list_widget.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
    # Height halved (was max 120) to ~fit 4 paths; the reclaimed space below
    # holds the restored Naming pattern section.
    mw.folder_list_widget.setMinimumHeight(45)
    mw.folder_list_widget.setMaximumHeight(70)
    # No horizontal scrollbar — a long path just elides (ElideRight) rather than
    # forcing a scrollbar that breaks the box's layout. The user can still see
    # most of the path and where it leads; full path is in the tooltip.
    mw.folder_list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    mw.folder_list_widget.setTextElideMode(Qt.TextElideMode.ElideRight)
    mw._path_list_ef = _PathListEventFilter(mw.folder_list_widget)
    mw.folder_list_widget.viewport().installEventFilter(mw._path_list_ef)
    lib_layout.addWidget(mw.folder_list_widget)

    folder_btns_layout = QHBoxLayout()
    mw.add_folder_btn = QPushButton("Add")
    mw.add_folder_btn.setObjectName("library_add_folder_btn")
    mw.remove_folder_btn = QPushButton("Remove")
    mw.remove_folder_btn.setObjectName("library_remove_folder_btn")
    mw.refresh_library_btn = QPushButton("Rescan")
    mw.refresh_library_btn.setObjectName("library_rescan_btn")
    folder_btns_layout.addWidget(mw.add_folder_btn)
    folder_btns_layout.addWidget(mw.remove_folder_btn)
    folder_btns_layout.addWidget(mw.refresh_library_btn)
    lib_layout.addLayout(folder_btns_layout)

    pattern_header = QLabel("Naming pattern")
    pattern_header.setObjectName("settings_header")
    lib_layout.addWidget(pattern_header)

    pattern_row = QHBoxLayout()
    mw.at_pattern_btn = QPushButton("Author - Title")
    mw.ta_pattern_btn = QPushButton("Title - Author")
    mw.at_pattern_btn.setObjectName("pattern_button")
    mw.ta_pattern_btn.setObjectName("pattern_button")
    mw.at_pattern_btn.setToolTip("Folders are named like 'Author - Title' (e.g. 'Stephen King - The Shining')")
    mw.ta_pattern_btn.setToolTip("Folders are named like 'Title - Author' (e.g. 'The Shining - Stephen King')")
    pattern_row.addWidget(mw.at_pattern_btn)
    pattern_row.addWidget(mw.ta_pattern_btn)
    pattern_row.addStretch()
    lib_layout.addLayout(pattern_row)

    mw.at_pattern_btn.clicked.connect(lambda: mw.naming_pattern_changed.emit("Author - Title"))
    mw.ta_pattern_btn.clicked.connect(lambda: mw.naming_pattern_changed.emit("Title - Author"))

    chap_source_header = QLabel("Chapter source")
    chap_source_header.setObjectName("settings_header")
    lib_layout.addWidget(chap_source_header)

    chap_source_row = QHBoxLayout()
    mw.chapter_source_buttons = {}
    for source, label in [("embedded", "Embedded"), ("cue", ".cue")]:
        btn = QPushButton(label)
        btn.setObjectName("pattern_button")
        btn.clicked.connect(lambda _, s=source: mw.chapter_list_source_changed.emit(s))
        chap_source_row.addWidget(btn)
        mw.chapter_source_buttons[source] = btn
    chap_source_row.addStretch()
    lib_layout.addLayout(chap_source_row)

    persist_header = QLabel("Persist search filter")
    persist_header.setObjectName("settings_header")
    lib_layout.addWidget(persist_header)

    persist_row = QHBoxLayout()
    mw.persist_filter_buttons = {}
    for val, label in [(False, "Off"), (True, "On")]:
        btn = QPushButton(label)
        btn.setObjectName("pattern_button")
        btn.clicked.connect(lambda _, v=val: mw._on_persist_filter_master(v))
        persist_row.addWidget(btn)
        mw.persist_filter_buttons[val] = btn
    persist_row.addStretch()

    if mw.config.get_persist_filter_enabled() and not any([
        mw.config.get_persist_filter_tag(),
        mw.config.get_persist_filter_text(),
        mw.config.get_persist_filter_year(),
    ]):
        mw.config.set_persist_filter_enabled(False)
    _master_on = mw.config.get_persist_filter_enabled()
    mw.persist_filter_sub_buttons = {}
    for key, label in [("tag", "Tag"), ("text", "Text"), ("year", "Year")]:
        btn = QPushButton(label)
        btn.setObjectName("pattern_button")
        btn.setVisible(_master_on)
        btn.clicked.connect(lambda _, k=key: mw._on_persist_filter_sub(k))
        persist_row.addWidget(btn)
        mw.persist_filter_sub_buttons[key] = btn
    lib_layout.addLayout(persist_row)

    # Excluded Books toggle — invisible (zero space) when no books are excluded.
    # Rechecked on each settings-panel open via _reload_excluded_books(). The
    # actual list (mw.excluded_books_popup, constructed in app.py) is parented
    # to mw.library_tab (this page), NOT added to lib_layout — absolutely
    # positioned within it via setGeometry, not a layout member, so it never
    # asks the tab's QVBoxLayout for space (the thing that caused the original
    # rendering wall — see excluded_books.py's module docstring). Being a
    # child of the tab page (not MainWindow) means it moves/hides for free
    # when the settings panel slides or the user switches tabs — no manual
    # position-tracking needed.
    mw.library_tab = library_tab
    mw.excluded_books_section = ExcludedBooksSection()
    mw.excluded_books_section.toggle_requested.connect(mw._on_excluded_toggle_clicked)
    lib_layout.addWidget(mw.excluded_books_section)

    # Library controller connections are consolidated in __init__
    lib_layout.addStretch()
    mw.tabs.addTab(library_tab, "Library")
    mw._update_pattern_visuals()
    mw._update_persist_filter_visuals()


def build_audio_tab(mw):
    mw.audio_tab = AudioSettingsTab(mw.player, mw.config, mw)
    mw.tabs.addTab(mw.audio_tab, "Audio")


def build_controls_tab(mw):
    # TAB 4: SHORTCUTS
    shortcuts_tab = QWidget()
    short_layout = QVBoxLayout(shortcuts_tab)
    short_layout.setContentsMargins(10, 0, 10, 10)
    short_layout.setSpacing(6)

    digit_header = QLabel("Chapter number keys")
    digit_header.setObjectName("settings_header")
    short_layout.addWidget(digit_header)

    digit_row = QHBoxLayout()
    mw.digit_mode_buttons = {}
    for mode, label in [("by_name", "By name"), ("by_index", "By index")]:
        btn = QPushButton(label)
        btn.setObjectName("pattern_button")
        btn.clicked.connect(lambda _, m=mode: mw.chapter_digit_mode_changed.emit(m))
        digit_row.addWidget(btn)
        mw.digit_mode_buttons[mode] = btn
    digit_row.addStretch()
    mw.digit_autoplay_buttons = {}
    for val, label in [(True, "Auto-play"), (False, "Jump only")]:
        btn = QPushButton(label)
        btn.setObjectName("pattern_button")
        btn.clicked.connect(lambda _, v=val: mw.chapter_digit_autoplay_changed.emit(v))
        digit_row.addWidget(btn)
        mw.digit_autoplay_buttons[val] = btn
    short_layout.addLayout(digit_row)
    short_layout.addStretch()
    mw.tabs.addTab(shortcuts_tab, "Controls")
