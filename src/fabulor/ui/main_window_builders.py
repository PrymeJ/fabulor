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
from PySide6.QtWidgets import (
    QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QStackedWidget,
    QSizePolicy, QGraphicsOpacityEffect,
)
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QSize
from PySide6.QtGui import QPixmap

from .title_bar import TitleBar, RightClickButton
from .controls import ClickSlider, ScrollingLabel, HoverButton, FreezableLabel
from .carousel import CAROUSEL_STRIPE_W, CAROUSEL_STRIPE_PAD, CAROUSEL_COVER_W
from .ui_helpers import COVER_AREA_HEIGHT, _load_svg_icon


def build_status_banner(mw):
    mw.status_banner = QWidget(mw)
    mw.status_banner.setObjectName("status_banner")
    mw.status_banner.setFixedHeight(30)
    mw.status_banner.hide()

    layout = QHBoxLayout(mw.status_banner)
    layout.setContentsMargins(10, 2, 10, 2)

    mw.status_label = QLabel("")
    mw.status_label.setAlignment(Qt.AlignCenter)

    mw.cancel_scan_btn = QPushButton("✕")
    mw.cancel_scan_btn.setFixedSize(20, 20)
    mw.cancel_scan_btn.setToolTip("Cancel scan")

    layout.addStretch()
    layout.addWidget(mw.status_label)
    layout.addStretch()
    layout.addWidget(mw.cancel_scan_btn)


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
    mw.speed_button = QPushButton("1.00x")
    mw.speed_button.setObjectName("speed_btn")
    mw.speed_button.setFixedWidth(60)
    mw.speed_button.setFixedHeight(33)
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
    mw.chap_duration_label.mousePressEvent = mw._toggle_remaining_time

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
    mw.total_time_label.mousePressEvent = mw._toggle_remaining_time
    mw.total_time_label.setCursor(Qt.PointingHandCursor)

    mw.sleep_timer_label = QPushButton("")
    mw.sleep_timer_label.setObjectName("sleep_timer_display")
    mw.sleep_timer_label.setFixedWidth(104)
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
    mw.volume_slider.valueChanged.connect(mw._on_volume_changed)

    mw.vol_stack = QStackedWidget()
    mw.vol_stack.setFixedWidth(104) # Sleep timer location
    mw.vol_stack.setFixedHeight(24)
    mw.vol_stack.addWidget(mw.sleep_timer_label)

    mw.vol_container = QWidget()
    vol_container_layout = QVBoxLayout(mw.vol_container)
    vol_container_layout.setContentsMargins(0, 6, 0, 0) # Volume bar location
    vol_container_layout.setSpacing(0)
    vol_container_layout.addWidget(mw.volume_slider)
    vol_container_layout.addStretch()
    mw.vol_stack.addWidget(mw.vol_container)

    book_info_layout.addWidget(mw.current_time_label)
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
