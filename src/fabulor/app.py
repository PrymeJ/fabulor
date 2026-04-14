import os
import math
import random
from PySide6.QtWidgets import (
    QLineEdit, QFileDialog, QListWidget,
    QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout, 
    QSizePolicy, QApplication, QListView, QGraphicsBlurEffect, QGridLayout, QComboBox, QGraphicsOpacityEffect,
    QScrollArea, QFrame, QTabWidget
)
from PySide6.QtCore import (
    Qt, QTimer, QPoint, QEvent, QPropertyAnimation, QEasingCurve, QModelIndex,
    QRegularExpression, Signal, QObject
)
from PySide6.QtGui import QPixmap, QGuiApplication, QColor, QIntValidator, QRegularExpressionValidator

from .player import Player
from .config import Config
from .themes import get_stylesheet, THEMES
from .ui.title_bar import TitleBar, RightClickButton, ThemeItem
from .ui.controls import ClickSlider, ScrollingLabel, HoverButton
from .ui.chapter_list import ChapterList # Keep ChapterList here as it's a direct child of MainWindow
from .ui.theme_manager import ThemeManager, ThemeComboBox
import time # For sleep timer
from .ui.cover_loader import CoverLoaderWorker # For async cover loading
from .ui.library import LibraryPanel
from .ui.panels import PanelManager # New import for PanelManager
from .db import LibraryDB
from .library.scanner import LibraryScanner
from .book_quotes import BOOK_QUOTES
from mpv import ShutdownError

class MainWindow(QWidget):  # QWidget, not QMainWindow
    def __init__(self, parent=None):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.current_cover_pixmap = QPixmap()
        self.is_slider_dragging = False
        self.is_chapter_slider_dragging = False
        self.current_file = ""
        self.config = Config()
        self.player = Player()
        # Manual override for testing
        #self.current_file = "/mnt/DriveD/Audiobooks/Adrian Selby - Snakewood/Snakewood.m4b"
        self._prev_chap_title = ""
        self._next_chap_title = ""
        #self.player.load_book(self.current_file)
        ###
        self.theme_manager = ThemeManager(self)
        self._paused_time = None
        self._is_seeking = False
        self._last_pause_timestamp = None
        self.db = LibraryDB()
        self.scanner = LibraryScanner(self.db.db_path)
        self._undo_pos = None
        self._undo_timer = QTimer(self)
        self._last_saved_pct = -1
        self._last_undo_click_time = 0
        self._undo_slide_in_connected = False
        self._undo_slide_out_connected = False
        self._sleep_timer_end_time = None # Unix timestamp when sleep timer should end
        self._sleep_mode = None # 'timed', 'end_of_chapter', 'end_of_book'
        self._current_sleep_fade = self.config.get_sleep_fade_duration()
        self.panel_manager = None # Will be initialized after widgets are created
        self.show_remaining_time = self.config.get_show_remaining_time()

        self._setup_ui()

        self.ui_timer = QTimer()
        self.quote_timer = QTimer()
        self.quote_timer.timeout.connect(self._rotate_quote)
        
        self.ui_timer.timeout.connect(self._update_ui_sync)
        self.scanner.progress.connect(self._on_scan_progress)
        self.scanner.finished.connect(self._on_scan_finished)
        self.player.chapter_changed.connect(self._update_chapter_label_from_index)
        self.player.file_loaded.connect(self._on_file_ready)

        self._undo_timer.setSingleShot(True)
        self._undo_timer.timeout.connect(self._hide_undo_banner)

        # Initialize Undo Overlay
        self.undo_overlay = QPushButton("Undo", self)
        self.undo_overlay.setObjectName("undo_overlay")
        self.undo_overlay.setFixedSize(32, 21)
        self.undo_overlay.hide()
        self.undo_overlay.clicked.connect(self._perform_undo)
        self.undo_anim = QPropertyAnimation(self.undo_overlay, b"pos")
        self.undo_anim.setDuration(400)
        self.undo_anim.setEasingCurve(QEasingCurve.OutCubic)

        QApplication.instance().installEventFilter(self)

        # Restore last played book if it exists
        last_book = self.config.get_last_book()
        # Verify the book still belongs to an active library location
        locations = self.db.get_scan_locations()
        is_valid = any(last_book.startswith(loc if loc.endswith(os.sep) else loc + os.sep) for loc in locations)
        if last_book and is_valid and os.path.exists(last_book):
            self.current_file = last_book
            self.player.load_book(self.current_file)
        self.chapter_list_widget.set_player(self.player)

        self._load_cover_art(self.current_file)
        
        # Handle selection from library
        self.library_panel.book_selected.connect(self._on_book_selected_from_library)
        
        self._check_library_status()
        self.ui_timer.start(200)

    def _setup_ui(self):
        self.setMinimumWidth(300)
        self.resize(300, 450)

        self.setObjectName("mainwindow")
        self.setStyleSheet(get_stylesheet(self.theme_manager._current_theme_name))

        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(0, 0, 0, 0)
        self.root_layout.setSpacing(0)

        self._build_title_bar()
        self._build_progress_bar()

        # Content container
        self.content_container = QWidget()
        self.content_layout = QVBoxLayout(self.content_container)
        self.content_layout.setContentsMargins(10, 10, 10, 10) #the whole container
        self.content_layout.setSpacing(10)
        self.root_layout.addWidget(self.content_container)

        # Visual Area for blurring (Cover Art and Metadata)
        self.visual_area = QWidget()
        self.visual_area.setObjectName("visual_area")
        self.visual_layout = QVBoxLayout(self.visual_area)
        self.visual_layout.setContentsMargins(0, 0, 0, 0) # cover art area
        self.visual_layout.setSpacing(10)
        self.visual_area.mousePressEvent = self._on_drag_area_pressed
        self.content_layout.addWidget(self.visual_area, 1) # Stretch factor 1 to claim space

        self._build_cover_art()
        self._build_metadata()
        self._build_controls()
        self._build_secondary_controls()

        self.chapter_list_widget = ChapterList(self)
        self.chapter_list_widget.chapter_changed.connect(self._update_chapter_title_text)
        
        self._build_sidebar()
        self._build_library_panel()
        self._build_settings_panel()
        self._build_sleep_panel()
        self._build_speed_panel()
        self._build_status_banner()

        # Pulse Animation for active sleep timer
        self.sleep_opacity_effect = QGraphicsOpacityEffect(self.sleep_trigger_btn)
        self.sleep_opacity_effect.setOpacity(1.0)
        self.sleep_trigger_btn.setGraphicsEffect(self.sleep_opacity_effect)
        self.sleep_pulse_anim = QPropertyAnimation(self.sleep_opacity_effect, b"opacity")
        self.sleep_pulse_anim.setDuration(4000) # Slower pulse
        self.sleep_pulse_anim.setStartValue(1.0)     # Bright
        self.sleep_pulse_anim.setKeyValueAt(0.5, 0.4) # Dim (Yoyo)
        self.sleep_pulse_anim.setEndValue(1.0)       # Bright
        self.sleep_pulse_anim.setLoopCount(-1)
        self.sleep_pulse_anim.setEasingCurve(QEasingCurve.InOutSine)

        self._update_speed_grid_styling()

        # Initialize Blur Effect for background depth
        self.blur_effect = QGraphicsBlurEffect(self.visual_area)
        self.blur_effect.setBlurHints(QGraphicsBlurEffect.AnimationHint)
        self.blur_effect.setBlurRadius(0)
        self.visual_area.setGraphicsEffect(self.blur_effect)

        self.blur_animation = QPropertyAnimation(self.blur_effect, b"blurRadius")
        self.blur_animation.setDuration(500)
        self.blur_animation.setEasingCurve(QEasingCurve.OutCubic)
        
        # Initialize PanelManager after all relevant widgets are created
        self.panel_manager = PanelManager(self)
        self.library_panel.back_requested.connect(self.panel_manager._close_library_flow)

    def _build_status_banner(self):
        self.status_banner = QWidget(self)
        self.status_banner.setObjectName("status_banner")
        self.status_banner.setFixedHeight(30)
        self.status_banner.hide()
        
        layout = QHBoxLayout(self.status_banner)
        layout.setContentsMargins(10, 2, 10, 2)
        
        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignCenter)
        
        self.cancel_scan_btn = QPushButton("✕")
        self.cancel_scan_btn.setFixedSize(20, 20)
        self.cancel_scan_btn.setToolTip("Cancel scan")
        self.cancel_scan_btn.clicked.connect(self._on_cancel_scan_clicked)
        
        # Temporary button for quote testing
        self.next_quote_btn = QPushButton("Next Quote")
        self.next_quote_btn.setFixedSize(70, 22)
        self.next_quote_btn.setStyleSheet("font-size: 9px; padding: 2px;")
        self.next_quote_btn.clicked.connect(self._rotate_quote)
        
        self.temp_settings_btn = QPushButton("S")
        self.temp_settings_btn.setFixedSize(22, 22)
        self.temp_settings_btn.setStyleSheet("font-size: 9px; padding: 2px;")
        # Use lambda to safely reference panel_manager which is initialized later
        self.temp_settings_btn.clicked.connect(lambda: self.panel_manager._open_settings_flow() if self.panel_manager else None)
        
        layout.addStretch()
        layout.addWidget(self.status_label)
        layout.addStretch()
        layout.addWidget(self.next_quote_btn)
        layout.addWidget(self.temp_settings_btn)
        layout.addWidget(self.cancel_scan_btn)

    def _build_title_bar(self):
        self.title_bar = TitleBar(self)
        self.root_layout.addWidget(self.title_bar)

    def _build_progress_bar(self):
        self.progress_slider = ClickSlider(Qt.Horizontal)
        self.progress_slider.setObjectName("overall_progress")
        self.progress_slider.sliderPressed.connect(self._hide_popups)
        self.progress_slider.setRange(0, 1000)
        self.progress_slider.setFixedHeight(24)
        self.progress_slider.sliderPressed.connect(self._on_slider_pressed)
        self.progress_slider.sliderReleased.connect(self._on_slider_released)
        self.root_layout.addWidget(self.progress_slider)

        self.progress_percentage_label = QLabel(self.progress_slider)
        self.progress_percentage_label.setObjectName("percentage_label")
        self.progress_percentage_label.setAlignment(Qt.AlignCenter)
        self.progress_percentage_label.setAttribute(Qt.WA_TransparentForMouseEvents)

    def _build_cover_art(self):
        self.cover_art_label = QLabel()
        self.cover_art_label.setAlignment(Qt.AlignBottom | Qt.AlignHCenter)
        self.cover_art_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.cover_art_label.setMinimumSize(280, 280)
        self.cover_art_label.mousePressEvent = self._on_drag_area_pressed
        self.visual_layout.addWidget(self.cover_art_label)

    def _build_metadata(self):
        self.library_prompt_label = QLabel("No library folders.")
        self.library_prompt_label.setAlignment(Qt.AlignCenter)
        self.library_prompt_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        self.visual_layout.addWidget(self.library_prompt_label)

        self.scan_now_btn = QPushButton("Scan now")
        self.scan_now_btn.setFixedWidth(120)
        self.scan_now_btn.clicked.connect(self._on_scan_now_clicked)
        self.visual_layout.addWidget(self.scan_now_btn, 0, Qt.AlignCenter)
        self.scan_info_label = QLabel(
            "Loading all your books may take a while. If you wish, you can instead "
            "first load fewer books, then choose your whole library later."
        )
        self.scan_info_label.setAlignment(Qt.AlignCenter)
        self.scan_info_label.setWordWrap(True)
        self.scan_info_label.setStyleSheet("color: #aaa; font-size: 13px; margin: 5px;")
        self.visual_layout.addWidget(self.scan_info_label)

        # Metadata (Book Info)
        self.metadata_label = QLabel("")
        self.metadata_label.setAlignment(Qt.AlignCenter)
        self.metadata_label.setWordWrap(True)
        self.metadata_label.mousePressEvent = self._on_drag_area_pressed
        self.visual_layout.addWidget(self.metadata_label)

        # Library button now appears AFTER the metadata label
        self.go_to_library_btn = QPushButton("Go to Library")
        self.go_to_library_btn.setObjectName("go_to_library_btn")
        self.go_to_library_btn.setFixedWidth(120)
        self.go_to_library_btn.hide() # Hide by default
        self.visual_layout.addWidget(self.go_to_library_btn, 0, Qt.AlignCenter)

        # Quote (Bottom)
        self.quote_label = QLabel("")
        self.quote_label.setObjectName("quote_label")
        self.quote_label.setAlignment(Qt.AlignCenter)
        self.quote_label.setWordWrap(True)
        self.visual_layout.addWidget(self.quote_label)

        self.sleep_timer_label = QPushButton("")
        self.sleep_timer_label.setObjectName("sleep_timer_display")
        font = self.sleep_timer_label.font()
        font.setPointSize(8)
        self.sleep_timer_label.setFont(font)
        self.sleep_timer_label.clicked.connect(self._disable_sleep_timer)
        self.visual_layout.addWidget(self.sleep_timer_label)

    def _build_controls(self):
        # Speed button centered above transport controls
        speed_row = QHBoxLayout()
        speed_row.addStretch()
        self.speed_button = QPushButton("1.00x")
        self.speed_button.setFixedWidth(60)
        self.speed_button.setContextMenuPolicy(Qt.CustomContextMenu)
        self.speed_button.customContextMenuRequested.connect(self._on_speed_right_clicked)
        self.speed_button.clicked.connect(self._on_speed_button_clicked)
        speed_row.addWidget(self.speed_button)
        self.content_layout.addLayout(speed_row)

        # Chapter preview label (dynamic visibility on hover)
        self.preview_row = QHBoxLayout()
        self.preview_row.setContentsMargins(0, 0, 0, 0)
        self.chapter_preview_label = QLabel("")
        self.chapter_preview_label.setObjectName("chapter_preview_label")
        self.chapter_preview_label.setFixedHeight(21) # Reserve space to prevent layout jumping
        self.chapter_preview_label.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.preview_row.addWidget(self.chapter_preview_label)
        self.content_layout.addLayout(self.preview_row)

        # Setup fade animation
        self.preview_opacity = QGraphicsOpacityEffect(self.chapter_preview_label)
        self.preview_opacity.setOpacity(0.0)
        self.chapter_preview_label.setGraphicsEffect(self.preview_opacity)

        self.preview_anim = QPropertyAnimation(self.preview_opacity, b"opacity")
        self.preview_anim.setDuration(600)
        self.preview_anim.setEasingCurve(QEasingCurve.OutCubic)

        controls_layout = QHBoxLayout()
        self.prev_button = HoverButton("|<<")
        self.rewind_button = RightClickButton("<")
        self.rewind_button.setAutoRepeat(True)
        self.rewind_button.setAutoRepeatDelay(500)   # Wait 500ms before scanning
        self.rewind_button.setAutoRepeatInterval(150) # Skip again every 150ms
        self.play_pause_button = QPushButton("Play")
        self.forward_button = RightClickButton(">")
        self.forward_button.setAutoRepeat(True)
        self.forward_button.setAutoRepeatDelay(500)
        self.forward_button.setAutoRepeatInterval(150)
        self.next_button = HoverButton(">>|")
        for btn in [self.prev_button, self.rewind_button, self.play_pause_button,
                    self.forward_button, self.next_button]:
            controls_layout.addWidget(btn)
        self.content_layout.addLayout(controls_layout)

        self.play_pause_button.clicked.connect(self.toggle_play_pause)
        self.prev_button.clicked.connect(self.handle_prev)
        self.rewind_button.clicked.connect(self.handle_rewind)
        self.rewind_button.rightClicked.connect(lambda: self.handle_rewind(long_skip=True))
        self.forward_button.clicked.connect(self.handle_forward)
        self.forward_button.rightClicked.connect(lambda: self.handle_forward(long_skip=True))
        self.next_button.clicked.connect(self.handle_next)

        # Hover signals for chapter previews
        self.prev_button.hovered.connect(self._on_prev_hover)
        self.prev_button.unhovered.connect(self._clear_preview)
        self.next_button.hovered.connect(self._on_next_hover)
        self.next_button.unhovered.connect(self._clear_preview)

    def _build_secondary_controls(self):
        # 1. Chapter Info Row (Top of secondary stack)
        chapter_info_layout = QHBoxLayout()
        self.chap_elapsed_label = QLabel("00:00:00")
        self.chap_elapsed_label.setFixedWidth(48)
        self.chap_elapsed_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        
        self.chap_duration_label = QLabel("00:00:00")
        self.chap_duration_label.setFixedWidth(48)
        self.chap_duration_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.chap_duration_label.mousePressEvent = self._toggle_remaining_time
        
        self.current_chapter_label = ScrollingLabel("")
        self.current_chapter_label.setObjectName("chapter_selector")
        self.current_chapter_label.clicked.connect(self._show_chapter_dropdown)
        self.current_chapter_label.set_scroll_mode(self.config.get_scroll_mode())
        
        chapter_info_layout.addWidget(self.chap_elapsed_label)
        chapter_info_layout.addWidget(self.current_chapter_label, 1)
        chapter_info_layout.addWidget(self.chap_duration_label)
        self.content_layout.addLayout(chapter_info_layout)

        # 2. Chapter Progress Slider
        self.chapter_progress_slider = ClickSlider(Qt.Horizontal)
        self.chapter_progress_slider.setObjectName("chapter_progress")
        self.chapter_progress_slider.setRange(0, 1000)
        self.chapter_progress_slider.setFixedHeight(13)
        self.chapter_progress_slider.sliderPressed.connect(self._hide_popups)
        self.chapter_progress_slider.sliderPressed.connect(self._on_chap_slider_pressed)
        self.chapter_progress_slider.sliderReleased.connect(self._on_chap_slider_released)
        self.content_layout.addWidget(self.chapter_progress_slider)

        # 3. Book Info Row (Elapsed - Speed - Total/Remaining)
        book_info_layout = QHBoxLayout()
        self.current_time_label = QLabel("00:00:00")
        self.current_time_label.setFixedWidth(80)
        self.current_time_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        
        self.total_time_label = QLabel("00:00:00")
        self.total_time_label.setFixedWidth(80)
        self.total_time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.total_time_label.mousePressEvent = self._toggle_remaining_time
        
        for lbl in [self.current_time_label, self.total_time_label]:
            font = lbl.font()
            font.setPointSize(12)
            lbl.setFont(font)

        self.volume_slider = ClickSlider(Qt.Horizontal)
        self.volume_slider.setObjectName("volume_slider")
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(self.config.get_volume())
        self.volume_slider.setFixedHeight(9)
        self.volume_slider.sliderPressed.connect(self._hide_popups)
        self.volume_slider.valueChanged.connect(self._on_volume_changed)

        book_info_layout.addWidget(self.current_time_label)
        book_info_layout.addWidget(self.volume_slider, 1)
        book_info_layout.addWidget(self.total_time_label)
        self.content_layout.addLayout(book_info_layout)

        # Setup Volume Overlay Animations
        self.vol_opacity = QGraphicsOpacityEffect(self.volume_slider)
        self.vol_opacity.setOpacity(0.0)
        self.volume_slider.setGraphicsEffect(self.vol_opacity)
        
        self.vol_fade_anim = QPropertyAnimation(self.vol_opacity, b"opacity")
        self.vol_fade_anim.setDuration(500) # Slow fade as requested
        self.vol_fade_anim.setEasingCurve(QEasingCurve.InOutCubic)
        
        self.vol_hide_timer = QTimer(self)
        self.vol_hide_timer.setSingleShot(True)
        self.vol_hide_timer.timeout.connect(self._fade_out_volume)

    def _build_sidebar(self):
        self.sidebar = QWidget(self)
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(70)
        self.sidebar_layout = QVBoxLayout(self.sidebar)
        self.sidebar_layout.setContentsMargins(10, 10, 10, 10)
        
        self.library_trigger_btn = QPushButton("LIBRARY")
        self.library_trigger_btn.setObjectName("sidebar_library_btn")
        self.sidebar_layout.addWidget(self.library_trigger_btn)
        
        self.sidebar_layout.addSpacing(10) # Separation

        self.settings_trigger_btn = QPushButton("SETTINGS")
        self.settings_trigger_btn.setObjectName("sidebar_settings_btn")
        self.sidebar_layout.addWidget(self.settings_trigger_btn)
        self.speed_trigger_btn = QPushButton("PLAYBACK")
        self.speed_trigger_btn.setObjectName("sidebar_speed_btn")
        self.sidebar_layout.addWidget(self.speed_trigger_btn)

        self.sleep_trigger_btn = QPushButton("SLEEP")
        self.sleep_trigger_btn.setObjectName("sidebar_sleep_btn")
        self.sidebar_layout.addWidget(self.sleep_trigger_btn)

        self.sleep_cancel_btn = QPushButton("✕", self.sleep_trigger_btn)
        self.sleep_cancel_btn.setFixedSize(16, 16)
        self.sleep_cancel_btn.move(34, 1)
        self.sleep_cancel_btn.setStyleSheet("font-size: 10px; padding: 0;")
        self.sleep_cancel_btn.clicked.connect(self._disable_sleep_timer)
        self.sleep_cancel_btn.hide()

        self.sidebar_layout.addStretch()
        self.sidebar.move(-50, 56)
        self.sidebar.show()
        self.sidebar_animation = QPropertyAnimation(self.sidebar, b"pos")
        self.sidebar_animation.setDuration(300)
        self.sidebar_animation.setEasingCurve(QEasingCurve.OutCubic)

    def _build_library_panel(self):
        self.library_panel = LibraryPanel(self.db, self.config, player_instance=self.player, parent=self)
        self.library_panel.hide()
        self.library_panel_animation = QPropertyAnimation(self.library_panel, b"pos")
        self.library_panel_animation.setDuration(300)
        self.library_panel_animation.setEasingCurve(QEasingCurve.OutCubic)

    def _build_settings_panel(self):
        self.settings_panel = QWidget(self)
        self.settings_panel.setObjectName("settings_panel")
        settings_layout = QVBoxLayout(self.settings_panel)
        settings_layout.setContentsMargins(5, 5, 5, 5)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("settings_tabs")

        # --- TAB 1: THEMES ---
        themes_tab = QWidget()
        themes_layout = QVBoxLayout(themes_tab)
        themes_layout.setContentsMargins(10, 10, 10, 10)
        
        theme_hint = QLabel("Select multiple to rotate randomly")
        theme_hint.setObjectName("theme_hint")
        theme_hint.setStyleSheet("margin-bottom: 4px;")
        themes_layout.addWidget(theme_hint)

        metrics = self.fontMetrics()
        limit = 290 #Adjusted for tab width
        
        # Clear widget tracker
        self.theme_manager.theme_widgets = {}
        
        themes_to_pack = []
        for name in THEMES.keys():
            w = metrics.horizontalAdvance(name) + 10 
            themes_to_pack.append({'name': name, 'width': w})
        
        # Sort by width descending to handle "large" items first
        themes_to_pack.sort(key=lambda x: x['width'], reverse=True)

        while themes_to_pack:
            row_layout = QHBoxLayout()
            row_layout.setSpacing(6)
            row_layout.setAlignment(Qt.AlignLeft)
            current_w = 0
            
            idx = 0
            while idx < len(themes_to_pack):
                item = themes_to_pack[idx]
                needed = item['width'] + (6 if current_w > 0 else 0)
                
                if current_w + needed <= limit:
                    btn = ThemeItem(item['name'])
                    btn.clicked.connect(lambda _, n=item['name']: self.theme_manager.toggle_theme_selection(n))
                    btn.rightClicked.connect(lambda n=item['name']: self.theme_manager._on_theme_right_clicked(n))
                    btn.hovered.connect(self.theme_manager._on_theme_hovered)
                    self.theme_manager.theme_widgets[item['name']] = btn
                    
                    row_layout.addWidget(btn)
                    current_w += needed
                    themes_to_pack.pop(idx)
                else:
                    idx += 1
            
            row_layout.addStretch()
            themes_layout.addLayout(row_layout)
            
        themes_tab.leaveEvent = lambda _: self.theme_manager._on_theme_unhovered()
        
        # Add/Remove All Buttons
        bulk_layout = QHBoxLayout()
        bulk_layout.setSpacing(10)
        self.add_all_btn = QPushButton("Add all")
        self.add_all_btn.setObjectName("secondary_button")
        self.add_all_btn.setFixedWidth(80)
        self.remove_all_btn = QPushButton("Remove all")
        self.remove_all_btn.setObjectName("secondary_button")
        self.remove_all_btn.setFixedWidth(80)
        self.change_now_btn = QPushButton("Change now")
        self.change_now_btn.setObjectName("secondary_button")
        self.change_now_btn.setFixedWidth(80)
        
        self.add_all_btn.clicked.connect(self.theme_manager.select_all_themes)
        self.remove_all_btn.clicked.connect(self.theme_manager.deselect_all_themes)
        self.change_now_btn.clicked.connect(self.theme_manager._rotate_theme)
        
        bulk_layout.addWidget(self.add_all_btn)
        bulk_layout.addWidget(self.remove_all_btn)
        bulk_layout.addWidget(self.change_now_btn)
        bulk_layout.addStretch()
        themes_layout.addLayout(bulk_layout)

        # Interval Selection
        interval_row = QHBoxLayout()
        interval_row.setSpacing(10)
        interval_row.setContentsMargins(0, 10, 0, 0)
        
        interval_label = QLabel("Interval (min)")
        interval_label.setObjectName("theme_hint")
        interval_row.addWidget(interval_label)

        intervals = [(2, "2"), (5, "5"), (10, "10"), (15, "15"), (30, "30"), (60, "60"), (120, "120"), (0, "Off")]
        for mins, label in intervals:
            btn = QPushButton(label)
            btn.setObjectName("theme_item") # Re-use the theme item bare style
            btn.clicked.connect(lambda _, m=mins: self.theme_manager.set_rotation_interval(m))
            self.theme_manager.interval_widgets[mins] = btn
            interval_row.addWidget(btn)
        interval_row.addStretch()
        themes_layout.addLayout(interval_row)

        themes_layout.addStretch()
        self.tabs.addTab(themes_tab, "Themes")
        self.theme_manager.update_theme_list_visuals()
        self.theme_manager.update_interval_visuals()

        # --- TAB 2: APPEARANCE ---
        appearance_tab = QWidget()
        app_layout = QVBoxLayout(appearance_tab)

        fade_header = QLabel("Theme hover (ms)")
        fade_header.setObjectName("settings_header")
        app_layout.addWidget(fade_header)

        fade_row = QHBoxLayout()
        self.fade_buttons = {}
        for ms_val in [0, 500, 750, 1000, 1500]:
            btn = QPushButton(str(ms_val))
            btn.setObjectName("pattern_button")
            btn.clicked.connect(lambda _, v=ms_val: self._update_fade_mode(v))
            fade_row.addWidget(btn)
            self.fade_buttons[ms_val] = btn
        fade_row.addStretch()
        app_layout.addLayout(fade_row)

        blur_header = QLabel("Blur")
        blur_header.setObjectName("settings_header")
        app_layout.addWidget(blur_header)

        blur_row = QHBoxLayout()
        self.blur_buttons = {}
        for state in ["On", "Off"]:
            btn = QPushButton(state)
            btn.setObjectName("pattern_button")
            btn.clicked.connect(lambda _, s=state: self._update_blur_mode(s == "On"))
            blur_row.addWidget(btn)
            self.blur_buttons[state] = btn
        blur_row.addStretch()
        app_layout.addLayout(blur_row)

        scroll_header = QLabel("Chapter scroll")
        scroll_header.setObjectName("settings_header")
        app_layout.addWidget(scroll_header)

        scroll_row = QHBoxLayout()
        self.scroll_buttons = {}
        for mode in ["Slow", "Normal", "Off"]:
            btn = QPushButton(mode)
            btn.setObjectName("pattern_button") # Re-use styling for consistency
            btn.clicked.connect(lambda _, m=mode: self._update_scroll_mode(m))
            scroll_row.addWidget(btn)
            self.scroll_buttons[mode] = btn
        scroll_row.addStretch()
        app_layout.addLayout(scroll_row)

        hints_header = QLabel("Chapter hints")
        hints_header.setObjectName("settings_header")
        app_layout.addWidget(hints_header)

        hints_row = QHBoxLayout()
        self.hints_buttons = {}
        for mode in ["On", "Off"]:
            btn = QPushButton(mode)
            btn.setObjectName("pattern_button")
            btn.clicked.connect(lambda _, m=mode: self._update_hints_mode(m == "On"))
            hints_row.addWidget(btn)
            self.hints_buttons[mode] = btn
        hints_row.addStretch()
        app_layout.addLayout(hints_row)

        undo_header = QLabel("Undo seek button")
        undo_header.setObjectName("settings_header")
        app_layout.addWidget(undo_header)

        undo_row = QHBoxLayout()
        self.undo_buttons = {}
        for val, label in [(0, "Off"), (3, "3"), (5, "5"), (8, "8")]:
            btn = QPushButton(label)
            btn.setObjectName("pattern_button")
            btn.clicked.connect(lambda _, v=val: self._update_undo_mode(v))
            undo_row.addWidget(btn)
            self.undo_buttons[val] = btn
        undo_row.addStretch()
        app_layout.addLayout(undo_row)

        app_layout.addStretch()
        self.tabs.addTab(appearance_tab, "Appearance")
        self._update_scroll_mode_visuals()
        self._update_hints_visuals()
        self._update_undo_visuals()
        self._update_fade_visuals()
        self._update_blur_visuals()

        # --- TAB 3: LIBRARY ---
        library_tab = QWidget()
        lib_layout = QVBoxLayout(library_tab)
        pattern_header = QLabel("Naming pattern")
        pattern_header.setObjectName("settings_header")
        lib_layout.addWidget(pattern_header)

        pattern_row = QHBoxLayout()
        self.at_pattern_btn = QPushButton("Author - Title")
        self.ta_pattern_btn = QPushButton("Title - Author")
        self.at_pattern_btn.setObjectName("pattern_button")
        self.ta_pattern_btn.setObjectName("pattern_button")

        self.at_pattern_btn.setToolTip("Folders are named like 'Author - Title' (e.g. 'Stephen King - The Shining')")
        self.ta_pattern_btn.setToolTip("Folders are named like 'Title - Author' (e.g. 'The Shining - Stephen King')")

        pattern_row.addWidget(self.at_pattern_btn)
        pattern_row.addWidget(self.ta_pattern_btn)
        pattern_row.addStretch()
        lib_layout.addLayout(pattern_row)

        self.at_pattern_btn.clicked.connect(lambda: self._update_naming_pattern("Author - Title"))
        self.ta_pattern_btn.clicked.connect(lambda: self._update_naming_pattern("Title - Author"))

        lib_layout.addSpacing(10)

        folders_header = QLabel("Manage folders")
        folders_header.setObjectName("settings_header")
        lib_layout.addWidget(folders_header)

        self.folder_list_widget = QListWidget()
        self.folder_list_widget.setObjectName("settings_folder_list")
        # Make height flexible: start small, grow to a cap
        self.folder_list_widget.setMinimumHeight(45)
        self.folder_list_widget.setMaximumHeight(120)
        self.folder_list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        lib_layout.addWidget(self.folder_list_widget)

        folder_btns_layout = QHBoxLayout()
        self.add_folder_btn = QPushButton("Add")
        self.remove_folder_btn = QPushButton("Remove")
        self.refresh_library_btn = QPushButton("Rescan")
        folder_btns_layout.addWidget(self.add_folder_btn)
        folder_btns_layout.addWidget(self.remove_folder_btn)
        folder_btns_layout.addWidget(self.refresh_library_btn)
        lib_layout.addLayout(folder_btns_layout)

        self.add_folder_btn.clicked.connect(self._on_scan_now_clicked)
        self.remove_folder_btn.clicked.connect(self._on_remove_folder_clicked)
        self.refresh_library_btn.clicked.connect(lambda: self._check_library_status(manual=True, force_refresh=True))
        lib_layout.addStretch()
        self.tabs.addTab(library_tab, "Library")
        self._update_pattern_visuals()

        # --- TAB 4: SHORTCUTS ---
        shortcuts_tab = QWidget()
        short_layout = QVBoxLayout(shortcuts_tab)
        short_layout.addWidget(QLabel("Shortcuts configuration coming soon..."))
        short_layout.addStretch()
        self.tabs.addTab(shortcuts_tab, "Shortcuts")

        settings_layout.addWidget(self.tabs)
        self._refresh_folder_list()
        self.settings_panel.hide()
        self.settings_panel_animation = QPropertyAnimation(self.settings_panel, b"pos")
        self.settings_panel_animation.setDuration(300)
        self.settings_panel_animation.setEasingCurve(QEasingCurve.OutCubic)

    def _update_naming_pattern(self, pattern):
        """Changes the folder parsing pattern and triggers a database re-parse."""
        self.config.set_naming_pattern(pattern)
        self.db.reparse_library(pattern)
        self._update_pattern_visuals()
        self.library_panel.refresh(force=True)
        # Refresh the current book metadata on the main screen if a book is loaded
        if self.current_file:
            self._load_cover_art(self.current_file)

    def _update_pattern_visuals(self):
        """Updates the highlight/dim state of naming pattern buttons."""
        if not hasattr(self, 'at_pattern_btn'): return
        current = self.config.get_naming_pattern()
        self.at_pattern_btn.setProperty("selected", "true" if current == "Author - Title" else "false")
        self.ta_pattern_btn.setProperty("selected", "true" if current == "Title - Author" else "false")
        for btn in [self.at_pattern_btn, self.ta_pattern_btn]:
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _build_speed_panel(self):
        self.speed_panel = QWidget(self)
        self.speed_panel.setObjectName("speed_panel")
        self.speed_panel_layout = QVBoxLayout(self.speed_panel)
        speed_header = QLabel("Playback speed")
        speed_header.setObjectName("settings_header")
        self.speed_panel_layout.addWidget(speed_header)
        grid = QGridLayout()
        grid.setSpacing(8)
        presets = [
            0.25, 0.50, 0.75, 1.00, 1.25, 1.50, 1.75, 2.00, 2.25, 2.50, 2.75, 3.00,
            3.25, 3.50, 3.75, 4.00, 5.00, 6.00, 7.00, 8.00
        ]
        self._speed_presets = presets
        self._speed_grid_buttons = []
        for i, val in enumerate(self._speed_presets):
            btn = QPushButton(f"{val:.2f}x")
            btn.setFixedSize(55, 30)
            btn.clicked.connect(lambda _, v=val: (self._set_speed(v), self.panel_manager._close_speed_flow()))
            grid.addWidget(btn, i // 4, i % 4)
            self._speed_grid_buttons.append(btn)
        self.speed_panel_layout.addLayout(grid)
        
        self.speed_panel_layout.addSpacing(10)

        # Default Speed Section
        def_header = QLabel("Default speed")
        def_header.setObjectName("settings_header")
        self.speed_panel_layout.addWidget(def_header)
        def_row = QHBoxLayout()
        self.def_speed_buttons = {}
        for val in [1.0, 1.5, 1.75, 2.0, 2.25, 2.5, 3.0]:
            btn = QPushButton(f"{val}x")
            btn.setObjectName("pattern_button")
            btn.clicked.connect(lambda _, v=val: self._update_def_speed_mode(v))
            def_row.addWidget(btn)
            self.def_speed_buttons[val] = btn
        def_row.addStretch()
        self.speed_panel_layout.addLayout(def_row)

        # Increment Step Section
        step_header = QLabel("Step")
        step_header.setObjectName("settings_header")
        self.speed_panel_layout.addWidget(step_header)
        step_row_layout = QHBoxLayout()
        self.step_buttons = {}
        for val in [0.05, 0.1, 0.25, 0.5]:
            btn = QPushButton(str(val))
            btn.setObjectName("pattern_button")
            btn.clicked.connect(lambda _, v=val: self._update_step_mode(v))
            step_row_layout.addWidget(btn)
            self.step_buttons[val] = btn
        step_row_layout.addStretch()
        self.speed_panel_layout.addLayout(step_row_layout)

        # Skip & Long Skip Section
        skip_header_row = QHBoxLayout()
        skip_label = QLabel("Skip")
        skip_label.setObjectName("settings_header")
        long_skip_label = QLabel("Long skip")
        long_skip_label.setObjectName("settings_header")
        skip_header_row.addWidget(skip_label)
        skip_header_row.addStretch()
        skip_header_row.addWidget(long_skip_label)
        self.speed_panel_layout.addLayout(skip_header_row)

        skip_buttons_row = QHBoxLayout()
        self.skip_buttons = {}
        for val in [5, 10, 15, 30]:
            btn = QPushButton(str(val))
            btn.setObjectName("pattern_button")
            btn.clicked.connect(lambda _, v=val: self._update_skip_mode(v))
            skip_buttons_row.addWidget(btn)
            self.skip_buttons[val] = btn

        skip_buttons_row.addStretch()

        self.long_skip_buttons = {}
        for val in [1, 2, 5]:
            btn = QPushButton(str(val))
            btn.setObjectName("pattern_button")
            btn.clicked.connect(lambda _, v=val: self._update_long_skip_mode(v))
            skip_buttons_row.addWidget(btn)
            self.long_skip_buttons[val] = btn
        self.speed_panel_layout.addLayout(skip_buttons_row)

        # Smart Rewind Section
        smart_header_row = QHBoxLayout()
        smart_label = QLabel("Smart rewind")
        smart_label.setObjectName("settings_header")
        smart_header_row.addWidget(smart_label)
        self.speed_panel_layout.addLayout(smart_header_row)

        smart_buttons_row = QHBoxLayout()
        self.smart_wait_buttons = {}
        for val, label in [(0, "Off"), (5, "5"), (30, "30"), (60, "60")]:
            btn = QPushButton(label)
            btn.setObjectName("pattern_button")
            btn.clicked.connect(lambda _, v=val: self._update_smart_rewind_mode(v))
            smart_buttons_row.addWidget(btn)
            self.smart_wait_buttons[val] = btn
        
        smart_buttons_row.addStretch()
        self.smart_dur_buttons = {}
        for val in [10, 20, 30]:
            btn = QPushButton(str(val))
            btn.setObjectName("pattern_button")
            btn.clicked.connect(lambda _, v=val: self._update_smart_rewind_duration(v))
            smart_buttons_row.addWidget(btn)
            self.smart_dur_buttons[val] = btn
        self.speed_panel_layout.addLayout(smart_buttons_row)

        self.speed_panel_layout.addStretch()
        self.speed_panel.hide()
        self.speed_panel_animation = QPropertyAnimation(self.speed_panel, b"pos")
        self.speed_panel_animation.setDuration(300)
        self.speed_panel_animation.setEasingCurve(QEasingCurve.OutCubic)

    def _build_sleep_panel(self):
        self.sleep_panel = QWidget(self)
        self.sleep_panel.setObjectName("sleep_panel")
        self.sleep_panel_layout = QVBoxLayout(self.sleep_panel)
        
        sleep_header = QLabel("Sleep Timer")
        sleep_header.setObjectName("settings_header")
        self.sleep_panel_layout.addWidget(sleep_header)

        # Time Presets Grid
        grid = QGridLayout()
        grid.setSpacing(4)
        presets_minutes = [2, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 75, 90, 120]
        self._sleep_presets_buttons = []
        for i, val in enumerate(presets_minutes):
            btn = QPushButton(f"{val} min")
            btn.setFixedSize(55, 30)
            btn.clicked.connect(lambda _, v=val: self._set_sleep_timer(duration_minutes=v))
            grid.addWidget(btn, i // 4, i % 4)
            self._sleep_presets_buttons.append(btn)
        self.sleep_panel_layout.addLayout(grid)

        # Special Modes
        special_modes_layout = QHBoxLayout()
        end_chap_btn = QPushButton("End of chapter")
        end_chap_btn.clicked.connect(lambda: self._set_sleep_timer(mode='end_of_chapter'))
        special_modes_layout.addWidget(end_chap_btn)

        end_book_btn = QPushButton("End of book")
        end_book_btn.clicked.connect(lambda: self._set_sleep_timer(mode='end_of_book'))
        special_modes_layout.addWidget(end_book_btn)
        self.sleep_panel_layout.addLayout(special_modes_layout)

        # Custom Time Input
        custom_time_layout = QHBoxLayout()
        self.custom_sleep_input = QLineEdit()
        self.custom_sleep_input.setPlaceholderText("min")
        self.custom_sleep_input.setFixedWidth(50)
        # Strictly allow only 1-3 digits, no commas or periods
        self.custom_sleep_input.setValidator(QRegularExpressionValidator(QRegularExpression("[1-9][0-9]{0,2}"), self))
        custom_time_layout.addWidget(self.custom_sleep_input)

        set_custom_btn = QPushButton("Set")
        set_custom_btn.clicked.connect(self._on_custom_sleep_time_set)
        custom_time_layout.addWidget(set_custom_btn)
        custom_time_layout.addStretch()
        self.sleep_panel_layout.addLayout(custom_time_layout)

        # Fade out options
        fade_header = QLabel("Fade-out")
        fade_header.setObjectName("settings_header")
        self.sleep_panel_layout.addWidget(fade_header)

        fade_layout = QHBoxLayout()
        fade_layout.setSpacing(5)
        self._sleep_fade_btns = {}
        fade_options = [("Off", 0), ("30s", 30), ("1m", 60), ("2m", 120), ("5m", 300)]
        for text, seconds in fade_options:
            btn = RightClickButton(text)
            btn.setFixedSize(45, 28)
            btn.setToolTip("Right-click to set as default")
            btn.clicked.connect(lambda _, s=seconds: self._set_sleep_fade(s, save=False))
            btn.rightClicked.connect(lambda s=seconds: self._set_sleep_fade(s, save=True))
            fade_layout.addWidget(btn)
            self._sleep_fade_btns[seconds] = btn
        
        self.sleep_panel_layout.addLayout(fade_layout)

        # Disable Button
        self.sleep_panel_layout.addSpacing(20)
        self.disable_sleep_btn = QPushButton("Disable the sleep timer")
        self.disable_sleep_btn.setObjectName("disable_sleep_btn")
        self.disable_sleep_btn.clicked.connect(self._disable_sleep_timer)
        self.disable_sleep_btn.hide() # Hide initially if no timer is active
        self.sleep_panel_layout.addWidget(self.disable_sleep_btn)

        self.sleep_panel_layout.addStretch()
        self.sleep_panel.hide()
        self.sleep_panel_animation = QPropertyAnimation(self.sleep_panel, b"pos")
        self.sleep_panel_animation.setDuration(300)
        self.sleep_panel_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._update_sleep_panel_styling() # Corrected method name

    def _on_custom_sleep_time_set(self):
        try:
            minutes = int(self.custom_sleep_input.text())
            if minutes > 0:
                self._set_sleep_timer(duration_minutes=minutes)
            else:
                print("Sleep timer: Please enter a positive number of minutes.")
        except ValueError:
            print("Sleep timer: Invalid input for custom time.")

    def _update_chapter_title_text(self, text):
        """Update the scrolling label text."""
        self.current_chapter_label.setText(text)

    def _refresh_folder_list(self):
        """Updates the folder list widget with current scan locations."""
        if hasattr(self, 'folder_list_widget'):
            self.folder_list_widget.clear()
            for loc in self.db.get_scan_locations():
                self.folder_list_widget.addItem(loc)

    def _on_remove_folder_clicked(self):
        """Removes the selected folder from the database and updates UI."""
        current_item = self.folder_list_widget.currentItem()
        if current_item:
            path = current_item.text()
            self.db.remove_scan_location(path)
            
            # Unload the book if it was inside the removed library folder
            path_p = path if path.endswith(os.sep) else path + os.sep
            if self.current_file and self.current_file.startswith(path_p):
                self.current_file = ""
                self.player.terminate()
                self._load_cover_art("")
                self.config.set_last_book("")

            self._refresh_folder_list()
            self._check_library_status(manual=True)
            self.library_panel.refresh(force=True)

    def _check_library_status(self, manual=False, force_refresh=False):
        """Lazy scan on startup. Checks if locations exist but books are missing."""
        locs = self.db.get_scan_locations()
        has_locations = len(locs) > 0
        has_indexed_books = self.db.get_book_count() > 0
        has_book = bool(self.current_file)

        self._set_interface_visible(has_book)

        if not has_locations or not has_indexed_books:
            self.quote_timer.start(60000) # Rotate every minute
            self._rotate_quote()
            self.library_prompt_label.show()
            self.scan_now_btn.show()
            self.scan_info_label.show()
            self.status_banner.show() # Keep banner visible for quote testing access
            self.metadata_label.hide()
            self.go_to_library_btn.hide() # Hide this button in empty state
        else:
            # We have at least one book! Switch to "Ready" state
            self.library_prompt_label.hide()
            self.scan_now_btn.hide()
            self.scan_info_label.hide()
            self.quote_label.hide()
            self.quote_timer.stop()
            
            if not has_book:
                self.metadata_label.setText("No book selected.") # Added period
                self.metadata_label.show()
                self.go_to_library_btn.show() # Show this button if books exist but none selected
            else:
                self.go_to_library_btn.hide() # Hide if a book is selected

        if has_locations:
            if not self.scanner._worker_thread or not self.scanner._worker_thread.isRunning():
                # Only show the banner if it's the first run (no indexed books)
                # OR if the user manually triggered a scan (added/removed a folder)
                if manual or force_refresh or not has_indexed_books:
                    self.status_label.setText("Forcing deep scan..." if force_refresh else "Library scanning...")
                    self.cancel_scan_btn.show()
                    self.status_banner.show()
                
                self.scanner.start(force_refresh=force_refresh)

    def _on_cancel_scan_clicked(self):
        self.scanner.stop()
        self.status_label.setText("Scan cancelled.")
        self.cancel_scan_btn.hide()

    def _on_scan_now_clicked(self):
        # Passing None as parent ensures the dialog uses the native OS style
        folder = QFileDialog.getExistingDirectory(None, "Select Library Folder")
        if folder:
            new_path = os.path.abspath(folder)
            existing = self.db.get_scan_locations()
            
            # Redundancy logic
            is_redundant = False
            for loc in existing:
                # Add separator to prevent /Books matching /Bookshelf
                loc_p = loc if loc.endswith(os.sep) else loc + os.sep
                new_p = new_path if new_path.endswith(os.sep) else new_path + os.sep
                
                if new_p.startswith(loc_p): 
                    is_redundant = True # User selected a subfolder of an already scanned path
                    break
                if loc_p.startswith(new_p):
                    self.db.remove_scan_location(loc) # Remove subfolders if user selected parent
            
            if not is_redundant:
                self.scanner.stop() # Stop any current silent scan to prioritize the new folder
                self.db.add_scan_location(new_path)
                self._check_library_status(manual=True)
                self._refresh_folder_list()

    def _rotate_quote(self):
        """Update metadata label with a random quote when idle."""
        if not self.db.get_scan_locations():
            text, title, text_size, title_size, color, text_align = random.choice(BOOK_QUOTES)
            # Rich text for right alignment of the author
            styled_quote = (
                f"<div style='font-size: {text_size}px; color: {color}; text-align: {text_align}; width: 100%;'>{text}</div>"
                f"<div style='text-align: right; font-size: {title_size}px; color: #ddd;'><br>{title}</div>"
            )
            self.quote_label.setText(styled_quote)
            self.quote_label.show()

    def _set_interface_visible(self, visible):
        """Toggles visibility of book-specific UI elements."""
        self.speed_button.setVisible(visible)
        self.current_time_label.setVisible(visible)
        self.total_time_label.setVisible(visible)
        self.sleep_timer_label.setVisible(visible)
        self.chapter_progress_slider.setVisible(visible)
        self.current_chapter_label.setVisible(visible)
        self.chap_elapsed_label.setVisible(visible)
        self.chap_duration_label.setVisible(visible)
        self.progress_percentage_label.setVisible(visible)
        self.chapter_preview_label.setVisible(visible)

    def _on_scan_progress(self, current, total):
        # Only update banner if it's already visible (prevents silent scans from popping up)
        if self.status_banner.isVisible():
            self.status_label.setText(f"Loading Library... ({current}/{total})")
            self.status_banner.raise_()
        
        # As soon as the very first book is indexed, enable UI access
        if current == 1:
            self._check_library_status()

    def _save_current_progress(self):
        """Saves the current playback position to both DB and Config."""
        if self.current_file and self.player.instance:
            pos = self.player.time_pos
            if pos is not None:
                self.db.update_progress(self.current_file, pos)
                self.config.set_last_position(self.current_file, pos)

    def _on_book_selected_from_library(self, path):
        """Loads a book and closes the library panel."""
        self._save_current_progress() # Save state of the book we are leaving
        self._last_saved_pct = -1
        self.current_file = path
        self.db.update_last_played(path)
        self.player.load_book(path)
        self._load_cover_art(path)
        self._check_library_status()
        self.panel_manager.hide_all_panels()
        self._update_ui_sync() # Force UI update

    def _on_scan_finished(self, total):
        if self.status_banner.isVisible():
            self.status_label.setText(f"Library updated: {total} books.")
            self.cancel_scan_btn.hide()
            QTimer.singleShot(3000, self.status_banner.hide)
        
        self.library_panel.refresh(force=True)
        self._refresh_folder_list()

    def _on_file_ready(self):
        """Called when mpv confirms the file is loaded and ready."""
        if not os.path.exists(self.current_file):
             self.status_banner.setText("Error: File missing!")
             self.status_banner.show()
             return
        self._restore_position()
        if self.player.duration:
            self.chapter_list_widget.populate(self.player.duration)
        # Force a sync immediately so labels don't wait for the next timer tick
        self._update_ui_sync()

    def _restore_position(self):
        """Seeks to the saved position from config."""
        # Crash recovery/Sync: Ensure DB is up to date with the last known config position
        config_pos = self.config.get_last_position(self.current_file)
        if config_pos > 0:
            self.db.update_progress(self.current_file, config_pos)

        book_data = self.db.get_book(self.current_file)
        if book_data:
            progress = book_data.get("progress", 0)
            if progress > 0:
                self.player.time_pos = progress
                self._is_seeking = True
        
        vol_val = self.volume_slider.value()
        if vol_val == 0:
            self.player.volume = 0
        else:
            self.player.volume = 100 * (math.log10(vol_val) / 2.0)
        
        saved_speed = self.config.get_book_speed(self.current_file)
        speed = saved_speed if saved_speed is not None else self.config.get_default_speed()
        self._set_speed(speed, save=False)

    def _hide_popups(self):
        """Closes any open floating menus."""
        self.panel_manager.hide_all_panels()

    def _on_speed_button_clicked(self):
        self._hide_popups() # Ensure other popups are hidden
        """Left click toggles the speed panel."""
        if self.speed_panel.isVisible():
            self.panel_manager._close_speed_flow()
        else:
            self.panel_manager._start_speed_entry()

    def _on_sleep_button_clicked(self):
        self._hide_popups() # Ensure other popups are hidden
        if self.sleep_panel.isVisible():
            self.panel_manager._close_sleep_flow()
        else:
            self.panel_manager._start_sleep_entry()

    def _show_chapter_dropdown(self):
        """Positions and shows the floating chapter list."""
        if self.chapter_list_widget.isVisible():
            self.chapter_list_widget.hide()
            return

        self.panel_manager.hide_all_panels()

        if not self.chapter_list_widget.count():
            self.chapter_list_widget.populate(self.player.duration or 0) # Populate if empty
            
        # Recalculate height and position the menu centered above the label
        # Ensure height is correct before positioning, re-populate if needed
        if self.chapter_list_widget.count() == 0: # Re-check in case populate failed
             self.chapter_list_widget.populate(self.player.duration or 0)
        label_pos = self.current_chapter_label.mapToGlobal(QPoint(0, 0))
        x = label_pos.x() + (self.current_chapter_label.width() // 2) - (self.chapter_list_widget.width() // 2)
        y = label_pos.y() - self.chapter_list_widget.height() - 5
        
        self.chapter_list_widget.move(x, y)
        self.chapter_list_widget.show()
        self.chapter_list_widget.setFocus()

    def _update_ui_sync(self):
        try:
            # Guard against accessing player before a file is loaded
            mpv_pos = self.player.time_pos if self.current_file else None
            dur = self.player.duration if self.current_file else None
            is_paused = self.player.pause if self.current_file else True
            speed = self.player.speed or 1.0
            current_time = time.time()
        except ShutdownError:
            return

        if not self.current_file:
            self.play_pause_button.setText("Play")
            return

        is_eof = self.player.eof_reached
        if is_eof:
            self.play_pause_button.setText("Restart")
            pos = dur or self.player.duration or 0
            # update sliders to 100% and return
            if pos and dur:
                self.progress_slider.setValue(1000)
                self.current_time_label.setText(self._format_time(pos / speed))
                if self.show_remaining_time:
                    self.total_time_label.setText("-00:00:00")
                    self.chap_duration_label.setText("-00:00:00")
                else:
                    self.total_time_label.setText(self._format_time(dur / speed))
            return

        if mpv_pos is None or dur is None:
            self.play_pause_button.setText("Play")
            return

        if is_paused:
            if self._paused_time is None or self._is_seeking or abs(mpv_pos - self._paused_time) > 1.0:
                self._paused_time = mpv_pos
                self._is_seeking = False
            pos = self._paused_time
        else:
            self._paused_time = None
            pos = mpv_pos
        
        # is_eof = self.player.eof_reached
        
        # Sleep Timer Logic
        sleep_display_text = ""
        if self._sleep_timer_end_time is not None:
            remaining_seconds = max(0, int(self._sleep_timer_end_time - current_time))
            if remaining_seconds <= 0 or is_eof:
                self._disable_sleep_timer()
                self.player.pause = True
            else:
                sleep_display_text = f"[{self._format_time(remaining_seconds)}]"
                # Volume Fade Logic
                if self._current_sleep_fade > 0 and remaining_seconds <= self._current_sleep_fade:
                    ratio = remaining_seconds / self._current_sleep_fade
                    vol_val = self.volume_slider.value()
                    if vol_val > 0:
                        # Scale current MPV volume based on the fade ratio
                        base_vol = 100 * (math.log10(vol_val) / 2.0)
                        self.player.volume = base_vol * ratio

        elif self._sleep_mode == 'end_of_chapter':
            sleep_display_text = "[chapter]"
            if not is_paused and self.player.chapter_list and self.player.chapter is not None:
                curr_chap = self.player.chapter
                chaps = self.player.chapter_list
                if curr_chap < len(chaps) - 1: # Not the last chapter
                    next_chap_start = chaps[curr_chap + 1].get('time', dur)
                    if pos >= next_chap_start - 0.5 or is_eof: # 0.5s buffer before chapter end
                        self._disable_sleep_timer()
                        self.player.pause = True
                elif curr_chap == len(chaps) - 1 and (pos >= dur - 0.5 or is_eof): # Last chapter, near end of book
                    self._disable_sleep_timer()
                    self.player.pause = True
        elif self._sleep_mode == 'end_of_book':
            sleep_display_text = "[book]"
            if not is_paused and (pos >= dur - 0.5 or is_eof): # Near end of book
                self._disable_sleep_timer()
                self.player.pause = True

        self.sleep_timer_label.setText(sleep_display_text)

        if self.current_chapter_label.text() == "Select Chapter" and self.player.chapter_list:
             self.chapter_list_widget.populate(dur)
             self._update_chapter_label_from_index(self.player.chapter or 0)

        if dur is not None and dur > 0:
            # Update overall progress
            if not self.is_slider_dragging:
                percent = (pos / dur) * 100
                self.progress_slider.setValue(int((pos / dur) * 1000))
                self.current_time_label.setText(self._format_time(pos / speed))
                if self.show_remaining_time:
                    remaining = (dur - pos) / speed
                    self.total_time_label.setText(f"-{self._format_time(remaining)}")
                else:
                    self.total_time_label.setText(self._format_time(dur / speed))
                self.progress_percentage_label.setText(f"{percent:.1f}%")

                # Update config every 0.1% (live cache)
                new_pct = int(percent * 10)
                if new_pct != self._last_saved_pct:
                    self._last_saved_pct = new_pct
                    self.config.set_last_position(self.current_file, pos)
                    if self.library_panel.isVisible():
                        self.library_panel.update_current_book_progress()

        curr_chap = self.player.chapter or 0
        chap_list = self.player.chapter_list or []
        if chap_list and curr_chap < len(chap_list):
            # Update chapter progress
            start = chap_list[curr_chap].get('time', 0)
            end = chap_list[curr_chap+1].get('time', dur) if curr_chap + 1 < len(chap_list) else dur
            chap_dur = end - start
            
            if not self.is_chapter_slider_dragging:
                c_elapsed = max(0, pos - start)
                self.chap_elapsed_label.setText(self._format_time(c_elapsed / speed))
                if self.show_remaining_time:
                    c_remaining = max(0, end - pos) / speed
                    self.chap_duration_label.setText(f"-{self._format_time(c_remaining)}")
                else:
                    self.chap_duration_label.setText(self._format_time((end - start) / speed))
                if chap_dur > 0:
                    self.chapter_progress_slider.setValue(int((c_elapsed / chap_dur) * 1000))

        if is_eof and self.current_file:
            self.play_pause_button.setText("Restart") # This will be handled by _update_ui_sync
        else:
            self.play_pause_button.setText("Play" if self.player.pause else "Pause")

    def _format_time(self, seconds):
        """Converts seconds to HH:MM:SS format."""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        return f"{h:02}:{m:02}:{s:02}" # No change here

    def _on_slider_pressed(self):
        self.is_slider_dragging = True

    def _on_slider_released(self):
        if self.player and self.player.duration:
            old_pos = self.player.time_pos
            new_pos = (self.progress_slider.value() / 1000) * self.player.duration
            speed = self.player.speed or 1.0
            if abs(new_pos - old_pos) > 60 * speed:
                self._trigger_undo(old_pos)
            self.player.time_pos = new_pos
            self._is_seeking = True
            # Immediately sync for library reactivity
            self.config.set_last_position(self.current_file, new_pos)
            if self.library_panel.isVisible():
                self.library_panel.update_current_book_progress()
        self.is_slider_dragging = False

    def _on_chap_slider_pressed(self):
        self.is_chapter_slider_dragging = True

    def _on_chap_slider_released(self):
        if self.player and self.player.duration:
            old_pos = self.player.time_pos
            curr_chap = self.player.chapter or 0
            chap_list = self.player.chapter_list or []
            if chap_list and curr_chap < len(chap_list):
                dur = self.player.duration
                start = chap_list[curr_chap].get('time', 0)
                end = chap_list[curr_chap+1].get('time', dur) if curr_chap + 1 < len(chap_list) else dur
                chap_dur = end - start
                if chap_dur > 0:
                    new_chap_pos = (self.chapter_progress_slider.value() / 1000) * chap_dur
                    new_pos = start + new_chap_pos
                    speed = self.player.speed or 1.0
                    if abs(new_pos - old_pos) > 60 * speed:
                        self._trigger_undo(old_pos)
                    self.player.time_pos = new_pos
                    self._is_seeking = True
                    # Immediately sync for library reactivity
                    self.config.set_last_position(self.current_file, new_pos)
                    if self.library_panel.isVisible():
                        self.library_panel.update_current_book_progress()
        self.is_chapter_slider_dragging = False

    def _on_volume_changed(self, value):
        self.panel_manager.hide_all_panels()
        if self.player:
            if value == 0:
                self.player.volume = 0
            else:
                # Logarithmic scale: makes the lower end of the slider more granular
                self.player.volume = 100 * (math.log10(value) / 2.0)

    def _set_speed(self, value, save=True):
        """Applies a specific speed value."""
        if self.player:
            self.player.speed = value
            self.speed_button.setText(f"{value:.2f}x")
            if save and self.current_file:
                self.config.set_book_speed(self.current_file, value)

    def _toggle_remaining_time(self, event):
        if event.button() == Qt.LeftButton:
            self.show_remaining_time = not self.show_remaining_time
            self.config.set_show_remaining_time(self.show_remaining_time)
            self._update_ui_sync()

    def _on_speed_right_clicked(self, pos):
        """Right click increments, Shift+Right click decrements."""
        self._hide_popups()
        if not self.player: return
        
        step = self.config.get_speed_increment()
        modifiers = QGuiApplication.keyboardModifiers()
        current = self.player.speed or self.config.get_default_speed()
        
        if modifiers & Qt.ShiftModifier:
            new_speed = max(0.25, current - step)
        else:
            new_speed = min(8.0, current + step)
            
        self._set_speed(new_speed)

    def _set_sleep_timer(self, duration_minutes=None, mode=None):
        """Sets the sleep timer based on duration or mode."""
        self._disable_sleep_timer() # Clear any existing timer
        if self.player:
            self.player.pause = False

        if duration_minutes is not None:
            self._sleep_timer_end_time = time.time() + duration_minutes * 60
            self._sleep_mode = 'timed'
            self.config.set_sleep_duration(duration_minutes)
            self.config.set_sleep_mode('timed')
            QTimer.singleShot(500, self.disable_sleep_btn.show)
            self.sleep_trigger_btn.setText("SLEEP") # No brackets
            self.sleep_cancel_btn.show()
            self.sleep_pulse_anim.start()
        elif mode in ['end_of_chapter', 'end_of_book']:
            self._sleep_mode = mode
            self.config.set_sleep_mode(mode)
            QTimer.singleShot(500, self.disable_sleep_btn.show)
            self.sleep_trigger_btn.setText("SLEEP") # No brackets
            self.sleep_cancel_btn.show()
            self.sleep_pulse_anim.start()

        self.panel_manager._close_sleep_flow()
        self._update_ui_sync() # Force UI update

    def _disable_sleep_timer(self):
        """Disables the active sleep timer."""
        self._sleep_timer_end_time = None
        self._sleep_mode = None
        self.disable_sleep_btn.hide()
        self.sleep_trigger_btn.setText("SLEEP")
        self.sleep_cancel_btn.hide()
        self.sleep_pulse_anim.stop()
        self.sleep_opacity_effect.setOpacity(1.0)
        
        # Restore original volume level
        self._on_volume_changed(self.volume_slider.value())
        
        self._update_ui_sync() # Force UI update

    def _set_sleep_fade(self, seconds, save=False):
        self._current_sleep_fade = seconds
        if save:
            self.config.set_sleep_fade_duration(seconds)
        self._update_sleep_panel_styling()

    def _update_speed_grid_styling(self):
        """Applies the current theme's gradient styling to the speed grid buttons."""
        t = THEMES.get(self.theme_manager._current_theme_name, THEMES["The Color Purple"])
        accent = QColor(t['accent'])
        btn_text = t.get('button_text', t.get('text_on_light_bg', t['text']))

        for i, btn in enumerate(self._speed_grid_buttons):
            # Gradient logic: Opacity increases from 30% to 100% as speed increases
            alpha = int(75 + (180 * (i / (len(self._speed_presets) - 1))))
            c = QColor(accent)
            c.setAlpha(alpha)
            btn.setStyleSheet(f"background-color: rgba({c.red()}, {c.green()}, {c.blue()}, {c.alpha()}); color: {btn_text}; border: none;")
        self._update_pattern_visuals()
        self._update_scroll_mode_visuals()
        self._update_hints_visuals()
        self._update_fade_visuals()
        self._update_blur_visuals()
        self._update_def_speed_visuals()
        self._update_step_visuals()
        self._update_skip_visuals()
        self._update_long_skip_visuals()
        self._update_smart_rewind_visuals()
        self._update_undo_visuals()
        self._update_sleep_panel_styling()

    def _update_sleep_panel_styling(self):
        """Applies the current theme's gradient styling to the sleep timer grid buttons."""
        t = THEMES.get(self.theme_manager._current_theme_name, THEMES["The Color Purple"])
        accent = QColor(t['accent'])
        btn_text = t.get('button_text', t.get('text_on_light_bg', t['text']))
        default_fade = self.config.get_sleep_fade_duration()

        # Using same presets count logic for consistent gradient look
        for i, btn in enumerate(self._sleep_presets_buttons):
            alpha = int(75 + (180 * (i / (len(self._sleep_presets_buttons) - 1))))
            c = QColor(accent)
            c.setAlpha(alpha)
            btn.setStyleSheet(f"background-color: rgba({c.red()}, {c.green()}, {c.blue()}, {c.alpha()}); color: {btn_text}; border: none;")

        # Fade buttons styling with gradient and default indicator (2px border)
        for i, (seconds, btn) in enumerate(self._sleep_fade_btns.items()):
            alpha = int(75 + (180 * (i / (len(self._sleep_fade_btns) - 1))))
            c = QColor(accent)
            c.setAlpha(alpha)
            
            is_active = (seconds == self._current_sleep_fade)
            is_default = (seconds == default_fade)
            
            # 2px border for default, 1px for others
            border = f"2px solid {t['accent_light']}" if is_default else f"1px solid {t['accent']}"
            
            # Active button uses theme accent background, inactive uses dropdown bg
            bg = f"rgba({c.red()}, {c.green()}, {c.blue()}, {c.alpha()})" if is_active else t['bg_dropdown']
            fg = btn_text if is_active else t['text']
            
            btn.setStyleSheet(f"background-color: {bg}; color: {fg}; border: {border};")


    def mousePressEvent(self, event):
        # Do not hide popups if clicking inside the panels
        for panel in [self.library_panel, self.settings_panel, self.speed_panel, self.sleep_panel]:
            if panel.isVisible() and panel.geometry().contains(event.pos()):
                return
        self._hide_popups()
        super().mousePressEvent(event)

    def _update_chapter_label_from_index(self, index):
        """Updates the label based on the current chapter index."""
        if not self.player:
            return
        
        # If the list is empty, trigger population now that we know we have data
        if not self.chapter_list_widget.count():
            self.chapter_list_widget.populate(self.player.duration or 0)

        chaps = self.player.chapter_list or []
        # Ensure index is non-negative to avoid Python's negative indexing (which picks the last chapter)
        if 0 <= index < len(chaps):
            title = chaps[index].get('title') or f"Chapter {index + 1}"
            self._update_chapter_title_text(title)
            # Also sync the list selection visually
            self.chapter_list_widget.setCurrentRow(index)

            # Save state on chapter change (natural stopping point)
            self._save_current_progress()

            # Update chapter preview labels
            metrics = self.fontMetrics()
            if index > 0:
                prev_title = chaps[index - 1].get('title') or f"Chapter {index}"
                # More space available now, using a wider elision limit
                self._prev_chap_title = metrics.elidedText(prev_title, Qt.ElideRight, 260)
            else:
                self._prev_chap_title = ""
            self.prev_button.setToolTip("") # Clear old tooltips

            if index < len(chaps) - 1:
                next_title = chaps[index + 1].get('title') or f"Chapter {index + 2}"
                self._next_chap_title = metrics.elidedText(next_title, Qt.ElideRight, 260)
            else:
                self._next_chap_title = ""
            self.next_button.setToolTip("") # Clear old tooltips

    def _on_prev_hover(self):
        if self._prev_chap_title and self.config.get_chapter_hints_enabled():
            self.preview_anim.stop()
            self.preview_row.setAlignment(self.chapter_preview_label, Qt.AlignLeft)
            self.chapter_preview_label.setAlignment(Qt.AlignLeft)
            self.chapter_preview_label.setText(self._prev_chap_title)
            self.preview_anim.setStartValue(self.preview_opacity.opacity())
            self.preview_anim.setEndValue(1.0)
            self.preview_anim.start()

    def _on_next_hover(self):
        if self._next_chap_title and self.config.get_chapter_hints_enabled():
            self.preview_anim.stop()
            self.preview_row.setAlignment(self.chapter_preview_label, Qt.AlignRight)
            self.chapter_preview_label.setAlignment(Qt.AlignRight)
            self.chapter_preview_label.setText(self._next_chap_title)
            self.preview_anim.setStartValue(self.preview_opacity.opacity())
            self.preview_anim.setEndValue(1.0)
            self.preview_anim.start()

    def _clear_preview(self):
        self.preview_anim.stop()
        self.preview_anim.setStartValue(self.preview_opacity.opacity())
        self.preview_anim.setEndValue(0.0)
        self.preview_anim.start()

    def _load_cover_art(self, file_path):
        """Extracts and displays cover art from the file tags."""
        # Get book metadata for fallback display
        book = self.db.get_book(file_path) if file_path else None
        
        if not file_path:
            self.current_cover_pixmap = QPixmap()
            self.cover_art_label.hide()
            self.metadata_label.show()
            self.metadata_label.setText("No book selected")
            return

        pixmap = self.player.extract_cover(file_path)

        if not pixmap.isNull():
            self.current_cover_pixmap = pixmap
            self.cover_art_label.show()
            self.metadata_label.hide()
            self._update_cover_art_scaling()
        else:
            self.current_cover_pixmap = QPixmap()
            self.cover_art_label.hide()
            self.metadata_label.show()
            if book:
                self.metadata_label.setText(f"{book['author']} - {book['title']}")
            else:
                self.metadata_label.setText("Unknown book")

    def _update_cover_art_scaling(self):
        """Scales the current cover pixmap to FIT the available space."""
        if not self.current_cover_pixmap.isNull() and self.cover_art_label.isVisible():
            # Fit logic: Use label width but cap it to keep aspect ratio
            # all pixels visible = KeepAspectRatio
            target_w = self.cover_art_label.width()
            target_h = self.cover_art_label.height()
            
            scaled = self.current_cover_pixmap.scaled(
                target_w, target_h,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            self.cover_art_label.setPixmap(scaled)

    def showEvent(self, event):
        """Triggers scaling once the window is rendered to prevent hidden art on startup."""
        super().showEvent(event)
        # Ensure percentage label covers the slider immediately
        if hasattr(self, 'progress_percentage_label'):
            self.progress_percentage_label.resize(self.progress_slider.size())
        self._update_cover_art_scaling()

    def resizeEvent(self, event):
        """Handle window resize to update cover art scaling."""
        super().resizeEvent(event)
        
        if self.panel_manager:
            self.panel_manager.resize_panels()

        # Position the status banner at the bottom as an overlay
        if hasattr(self, 'status_banner'):
            self.status_banner.setGeometry(0, self.height() - 30, self.width(), 30)
            if self.status_banner.isVisible():
                self.status_banner.raise_()

        self._update_cover_art_scaling()
        # Reposition percentage label
        if hasattr(self, 'progress_percentage_label'):
            self.progress_percentage_label.resize(self.progress_slider.size())

    def _on_drag_area_pressed(self, event):
        if event.button() == Qt.LeftButton:
            if self.db.get_book_count() == 0:
                return # Do not hide popups if just dragging window in empty state
            
            if self.panel_manager.is_any_panel_visible():
                self.panel_manager.hide_all_panels()
            elif self.current_file:
                self.toggle_play_pause()
        elif event.button() == Qt.RightButton:
            # Guard: Only allow sidebar right-click toggle if books are indexed
            if self.db.get_book_count() > 0:
                self.panel_manager.handle_drag_area_right_click(event)

    def toggle_play_pause(self):
        self.panel_manager.hide_all_panels()
        if not self.player:
            return
        if self.play_pause_button.text() == "Restart":
            self.player.time_pos = 0
            self._is_seeking = True
            self.player.pause = False
            return
        else:
            was_paused = self.player.pause
            if was_paused:
                if self.current_file:
                    self.db.update_last_played(self.current_file)
                
                wait_min = self.config.get_smart_rewind_wait()
                rewind_sec = self.config.get_smart_rewind_duration()
                
                if self._last_pause_timestamp and wait_min > 0 and rewind_sec > 0:
                    away_duration = time.time() - self._last_pause_timestamp
                    if away_duration >= (wait_min * 60):
                        speed = self.player.speed or 1.0
                        rewind_amt = rewind_sec * speed
                        
                        # Restrict to same chapter
                        start_limit = 0
                        curr_idx = self.player.chapter
                        chaps = self.player.chapter_list
                        if curr_idx is not None and chaps and curr_idx < len(chaps):
                            start_limit = chaps[curr_idx].get('time', 0)
                            
                        self.player.time_pos = max(start_limit, self.player.time_pos - rewind_amt)
                        self._is_seeking = True
                
                self.player.pause = False
            else:
                # Pausing: Record when we stopped
                self._last_pause_timestamp = time.time()
                self._save_current_progress()
                self.player.pause = True
                if self.library_panel.isVisible():
                    self.library_panel.update_current_book_progress()

    def handle_rewind(self, long_skip=False):
        self.panel_manager.hide_all_panels()
        if self.player:
            old_pos = self.player.time_pos
            speed = self.player.speed or 1.0
            if long_skip:
                skip = self.config.get_long_skip_duration() * 60 * speed
            else:
                skip = self.config.get_skip_duration() * speed
            new_pos = max(0, (old_pos or 0) - skip)
            self.player.time_pos = new_pos
            self._is_seeking = True

    def handle_forward(self, long_skip=False):
        self.panel_manager.hide_all_panels()
        if self.player:
            old_pos = self.player.time_pos
            speed = self.player.speed or 1.0
            if long_skip:
                skip = self.config.get_long_skip_duration() * 60 * speed
            else:
                skip = self.config.get_skip_duration() * speed
            new_pos = min(self.player.duration or 0, (old_pos or 0) + skip)
            self.player.time_pos = new_pos
            self._is_seeking = True

    def handle_prev(self):
        self.panel_manager.hide_all_panels()
        self._clear_preview()
        if self.player:
            self.player.previous_chapter()
            self._is_seeking = True

    def handle_next(self):
        self.panel_manager.hide_all_panels()
        self._clear_preview()
        if self.player:
            self.player.next_chapter()
            self._is_seeking = True

    def _trigger_undo(self, old_pos):
        """Slides in the floating undo button."""
        duration = self.config.get_undo_duration()
        if duration == 0:
            return

        now = time.time()
        # Define the window where rapid clicks are treated as a single seek sequence.
        # We use either 2 seconds or half the button visibility duration, whichever is smaller.
        #sequence_window = min(2.0, duration / 2.0)
        sequence_window = duration

        if self._undo_pos is None or (now - self._last_undo_click_time > sequence_window):
            self._undo_pos = old_pos

        self._last_undo_click_time = now
        self._undo_timer.stop()

        width = self.width()
        overlay_w = 32
        y_pos = 56
        target_x = width - overlay_w

        self.undo_anim.stop()
        if self._undo_slide_out_connected:
            self.undo_anim.finished.disconnect(self.undo_overlay.hide)
            self._undo_slide_out_connected = False
        if self._undo_slide_in_connected:
            self.undo_anim.finished.disconnect(self._on_undo_slide_in_done)
            self._undo_slide_in_connected = False

        if self.undo_overlay.isVisible() and self.undo_overlay.x() == target_x:
            self._undo_timer.start(duration * 1000)
            return

        self.undo_overlay.move(width, y_pos)
        self.undo_overlay.show()
        self.undo_overlay.raise_()

        self.undo_anim.setStartValue(QPoint(width, y_pos))
        self.undo_anim.setEndValue(QPoint(target_x, y_pos))
        self.undo_anim.finished.connect(self._on_undo_slide_in_done)
        self._undo_slide_in_connected = True
        self.undo_anim.start()

    def _on_undo_slide_in_done(self):
        self._undo_slide_in_connected = False
        duration = self.config.get_undo_duration()
        if duration > 0:
            self._undo_timer.start(duration * 1000)    

    def _perform_undo(self):
        """Seeks back and slides the button out."""
        if self.player and self._undo_pos is not None:
            self.player.time_pos = self._undo_pos
            self._is_seeking = True
            self._hide_undo_banner()

    def _hide_undo_banner(self):
        if not self.undo_overlay.isVisible():
            return

        self._undo_pos = None
        width = self.width()

        self.undo_anim.stop()
        if self._undo_slide_in_connected:
            self.undo_anim.finished.disconnect(self._on_undo_slide_in_done)
            self._undo_slide_in_connected = False
        if self._undo_slide_out_connected:
            self.undo_anim.finished.disconnect(self.undo_overlay.hide)
            self._undo_slide_out_connected = False

        self.undo_anim.setStartValue(self.undo_overlay.pos())
        self.undo_anim.setEndValue(QPoint(width, self.undo_overlay.y()))
        self.undo_anim.finished.connect(self.undo_overlay.hide)
        self._undo_slide_out_connected = True
        self.undo_anim.start()

    def wheelEvent(self, event):
        """Handles volume control via mouse wheel on the cover art area."""
        if self.visual_area.underMouse():
            delta = event.angleDelta().y()
            current = self.volume_slider.value()
            # Adjust volume in steps of 5
            step = 5
            if delta > 0:
                new_vol = min(100, current + step)
            else:
                new_vol = max(0, current - step)
            
            if new_vol != current:
                self.volume_slider.setValue(new_vol)
                self._show_volume_overlay()
            event.accept()
        elif self.speed_button.underMouse():
            if not self.player: return
            delta = event.angleDelta().y()
            step = self.config.get_speed_increment()
            current = self.player.speed or self.config.get_default_speed()
            
            if delta > 0:
                new_speed = min(8.0, current + step)
            else:
                new_speed = max(0.25, current - step)
                
            if new_speed != current:
                self._set_speed(new_speed)
            event.accept()
        else:
            super().wheelEvent(event)

    def _show_volume_overlay(self):
        """Triggers the volume slider fade-in and starts the auto-hide timer."""
        self.vol_hide_timer.stop()
        if self.vol_opacity.opacity() < 1.0:
            self.vol_fade_anim.stop()
            self.vol_fade_anim.setStartValue(self.vol_opacity.opacity())
            self.vol_fade_anim.setEndValue(1.0)
            self.vol_fade_anim.start()
        self.vol_hide_timer.start(2000) # Visible for 2 seconds

    def _fade_out_volume(self):
        """Starts the volume slider fade-out."""
        self.vol_fade_anim.stop()
        self.vol_fade_anim.setStartValue(self.vol_opacity.opacity())
        self.vol_fade_anim.setEndValue(0.0)
        self.vol_fade_anim.start()

    def eventFilter(self, obj, event):
        """Global event filter to handle dismissing popups on clicks outside."""
        try:
            if event.type() == QEvent.MouseButtonPress:
                if hasattr(self, 'chapter_list_widget') and self.chapter_list_widget.isVisible():
                    gp = event.globalPosition().toPoint()
                    if not self.chapter_list_widget.geometry().contains(gp):
                        self.panel_manager.hide_all_panels()
        except Exception:
            pass
            
        # Ensure obj is a valid QObject before calling super().eventFilter
        # Some internal Qt objects like QWidgetItem are not QObjects.
        if not isinstance(obj, QObject) or obj is None:
            return False
        return super().eventFilter(obj, event)
    def closeEvent(self, event):
        if self.player:
            self.config.set_volume(self.volume_slider.value())
            if self.current_file:
                self.config.set_last_book(self.current_file)
                self._save_current_progress()
            self.player.terminate()
        
        if self.scanner:
            self.scanner.stop()
            if self.scanner._worker_thread and self.scanner._worker_thread.isRunning():
                self.scanner._worker_thread.quit()
                self.scanner._worker_thread.wait()
                
        event.accept()

    def _update_hints_mode(self, enabled):
        """Changes the chapter hint visibility setting."""
        self.config.set_chapter_hints_enabled(enabled)
        self._update_hints_visuals()

    def _update_hints_visuals(self):
        """Updates the highlight state of hint toggle buttons."""
        if not hasattr(self, 'hints_buttons'): return
        enabled = self.config.get_chapter_hints_enabled()
        for mode, btn in self.hints_buttons.items():
            is_selected = (mode == "On" if enabled else mode == "Off")
            btn.setProperty("selected", "true" if is_selected else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _update_scroll_mode(self, mode):
        self.config.set_scroll_mode(mode)
        self.current_chapter_label.set_scroll_mode(mode)
        self._update_scroll_mode_visuals()

    def _update_scroll_mode_visuals(self):
        if not hasattr(self, 'scroll_buttons'): return
        current = self.config.get_scroll_mode()
        for mode, btn in self.scroll_buttons.items():
            btn.setProperty("selected", "true" if mode == current else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _update_undo_mode(self, val):
        self.config.set_undo_duration(val)
        self._update_undo_visuals()

    def _update_undo_visuals(self):
        if not hasattr(self, 'undo_buttons'): return
        current = self.config.get_undo_duration()
        for val, btn in self.undo_buttons.items():
            btn.setProperty("selected", "true" if val == current else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _update_fade_mode(self, ms):
        """Changes the theme hover fade duration."""
        self.config.set_theme_fade_duration(ms)
        self._update_fade_visuals()

    def _update_fade_visuals(self):
        """Updates the highlight state of fade buttons."""
        if not hasattr(self, 'fade_buttons'): return
        current = self.config.get_theme_fade_duration()
        for ms, btn in self.fade_buttons.items():
            btn.setProperty("selected", "true" if ms == current else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _update_blur_mode(self, enabled):
        """Changes the blur setting."""
        self.config.set_blur_enabled(enabled)
        # Apply setting immediately if a panel is open
        if not enabled:
            self.blur_effect.setBlurRadius(0)
        self._update_blur_visuals()

    def _update_blur_visuals(self):
        """Updates the highlight state of blur buttons."""
        if not hasattr(self, 'blur_buttons'): return
        enabled = self.config.get_blur_enabled()
        for state, btn in self.blur_buttons.items():
            is_selected = (state == "On" if enabled else state == "Off")
            btn.setProperty("selected", "true" if is_selected else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _update_def_speed_mode(self, val):
        self.config.set_default_speed(val)
        self._update_def_speed_visuals()

    def _update_def_speed_visuals(self):
        if not hasattr(self, 'def_speed_buttons'): return
        current = self.config.get_default_speed()
        for val, btn in self.def_speed_buttons.items():
            btn.setProperty("selected", "true" if float(val) == float(current) else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _update_step_mode(self, val):
        self.config.set_speed_increment(val)
        self._update_step_visuals()

    def _update_step_visuals(self):
        if not hasattr(self, 'step_buttons'): return
        current = self.config.get_speed_increment()
        for val, btn in self.step_buttons.items():
            btn.setProperty("selected", "true" if float(val) == float(current) else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _update_skip_mode(self, val):
        self.config.set_skip_duration(val)
        self._update_skip_visuals()

    def _update_skip_visuals(self):
        if not hasattr(self, 'skip_buttons'): return
        current = self.config.get_skip_duration()
        for val, btn in self.skip_buttons.items():
            btn.setProperty("selected", "true" if int(val) == int(current) else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _update_smart_rewind_mode(self, val):
        self.config.set_smart_rewind_wait(val)
        if val == 0:
            self.config.set_smart_rewind_duration(0)
        self._update_smart_rewind_visuals()

    def _update_smart_rewind_duration(self, val):
        self.config.set_smart_rewind_duration(val)
        self._update_smart_rewind_visuals()

    def _validate_smart_rewind_settings(self):
        wait = self.config.get_smart_rewind_wait()
        dur = self.config.get_smart_rewind_duration()
        if (wait > 0 and dur == 0) or (wait == 0 and dur > 0):
            self.config.set_smart_rewind_wait(0)
            self.config.set_smart_rewind_duration(0)
            self._update_smart_rewind_visuals()

    def _update_smart_rewind_visuals(self):
        if not hasattr(self, 'smart_wait_buttons'): return
        wait_curr = self.config.get_smart_rewind_wait()
        dur_curr = self.config.get_smart_rewind_duration()
        
        for val, btn in self.smart_wait_buttons.items():
            btn.setProperty("selected", "true" if val == wait_curr else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            
        for val, btn in self.smart_dur_buttons.items():
            btn.setProperty("selected", "true" if val == dur_curr else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _update_long_skip_mode(self, val):
        self.config.set_long_skip_duration(val)
        self._update_long_skip_visuals()

    def _update_long_skip_visuals(self):
        if not hasattr(self, 'long_skip_buttons'): return
        current = self.config.get_long_skip_duration()
        for val, btn in self.long_skip_buttons.items():
            btn.setProperty("selected", "true" if int(val) == int(current) else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
