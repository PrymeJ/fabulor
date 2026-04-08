import os
import math
from PySide6.QtWidgets import (
    QLineEdit,
    QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout, 
    QSizePolicy, QApplication, QListView, QGraphicsBlurEffect, QGridLayout, QComboBox, QGraphicsOpacityEffect
)
from PySide6.QtCore import (
    Qt, QTimer, QPoint, QEvent, QPropertyAnimation, QEasingCurve, QModelIndex, QRegularExpression, Signal
)
from PySide6.QtGui import QPixmap, QGuiApplication, QColor, QIntValidator, QRegularExpressionValidator

from .player import Player
from .config import Config
from .themes import get_stylesheet, THEMES
from .ui.controls import ClickSlider
from .ui.chapter_list import ChapterList # Keep ChapterList here as it's a direct child of MainWindow
from .ui.theme_manager import ThemeManager, ThemeComboBox # ThemeComboBox is used in _setup_ui
import time # For sleep timer
from .ui.panels import PanelManager # New import for PanelManager
from .db import LibraryDB
from .library.scanner import LibraryScanner
from mpv import ShutdownError

class TitleBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(32)
        self._drag_pos = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 4, 0)
        layout.setSpacing(0)

        self.title_label = QLabel("Fabulor")
        layout.addWidget(self.title_label)
        layout.addStretch()

        for symbol, slot in [("─", self._minimize), ("✕", self._close)]:
            btn = QPushButton(symbol)
            btn.setFixedSize(32, 32)
            btn.clicked.connect(slot)
            layout.addWidget(btn)

    def _minimize(self): self.window().showMinimized()
    def _close(self): self.window().close()

class RightClickButton(QPushButton):
    rightClicked = Signal()
    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.rightClicked.emit()
            event.accept()
        else:
            super().mousePressEvent(event)


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
        self.theme_manager = ThemeManager(self)
        self._paused_time = None
        self._is_seeking = False
        self.db = LibraryDB()
        self.scanner = LibraryScanner(self.db.db_path)
        self._sleep_timer_end_time = None # Unix timestamp when sleep timer should end
        self._sleep_mode = None # 'timed', 'end_of_chapter', 'end_of_book'
        self._current_sleep_fade = self.config.get_sleep_fade_duration()
        self.panel_manager = None # Will be initialized after widgets are created

        self._setup_ui()

        self.ui_timer = QTimer()
        self.ui_timer.timeout.connect(self._update_ui_sync)
        self.scanner.progress.connect(self._on_scan_progress)
        self.scanner.finished.connect(self._on_scan_finished)
        self.player.chapter_changed.connect(self._update_chapter_label_from_index)
        self.player.file_loaded.connect(self._on_file_ready)

        QApplication.instance().installEventFilter(self)

        # self.current_file = "/home/pryme/test.m4b"
        # self.player.load_book(self.current_file)
        self.chapter_list_widget.set_player(self.player)

        self._load_cover_art(self.current_file)
        self._check_library_status()
        self.ui_timer.start(200)

    def _setup_ui(self):
        self.setMinimumWidth(300)
        self.resize(300, 600)

        self.setObjectName("mainwindow")
        self.setStyleSheet(get_stylesheet(self.config.get_theme()))

        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(0, 0, 0, 0)
        self.root_layout.setSpacing(0)

        self._build_title_bar()
        self._build_progress_bar()

        # Content container
        self.content_container = QWidget()
        self.content_layout = QVBoxLayout(self.content_container)
        self.content_layout.setContentsMargins(10, 10, 10, 10)
        self.content_layout.setSpacing(10)
        self.root_layout.addWidget(self.content_container)

        # Visual Area for blurring (Cover Art and Metadata)
        self.visual_area = QWidget()
        self.visual_layout = QVBoxLayout(self.visual_area)
        self.visual_layout.setContentsMargins(0, 0, 0, 0)
        self.visual_layout.setSpacing(10)
        self.content_layout.addWidget(self.visual_area)

        self._build_cover_art()
        self._build_metadata()
        self._build_controls()
        self._build_secondary_controls()

        self.chapter_list_widget = ChapterList(self)
        self.chapter_list_widget.chapter_changed.connect(self._update_chapter_title_text)
        
        self._build_sidebar()
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

    def _build_status_banner(self):
        self.status_banner = QLabel("")
        self.status_banner.setObjectName("status_banner")
        self.status_banner.setAlignment(Qt.AlignCenter)
        self.status_banner.hide()
        self.root_layout.addWidget(self.status_banner)

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
        self.cover_art_label.setAlignment(Qt.AlignCenter)
        self.cover_art_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.cover_art_label.setMinimumSize(280, 280)
        self.cover_art_label.mousePressEvent = self._on_drag_area_pressed
        self.visual_layout.addWidget(self.cover_art_label)

    def _build_metadata(self):
        self.metadata_label = QLabel("Author - Title")
        self.metadata_label.setAlignment(Qt.AlignCenter)
        self.metadata_label.mousePressEvent = self._on_drag_area_pressed
        self.visual_layout.addWidget(self.metadata_label)

        self.time_label = QLabel("00:00:00 / 00:00:00")
        self.time_label.setAlignment(Qt.AlignCenter)
        font = self.time_label.font()
        font.setPointSize(9)
        self.time_label.setFont(font)
        self.visual_layout.addWidget(self.time_label)

        self.sleep_timer_label = QPushButton("")
        self.sleep_timer_label.setObjectName("sleep_timer_display")
        font = self.time_label.font()
        font.setPointSize(8)
        self.sleep_timer_label.setFont(font)
        self.sleep_timer_label.clicked.connect(self._disable_sleep_timer)
        self.visual_layout.addWidget(self.sleep_timer_label)

    def _build_controls(self):
        controls_layout = QHBoxLayout()
        self.prev_button = QPushButton("|<<")
        self.rewind_button = QPushButton("<")
        self.play_pause_button = QPushButton("Play")
        self.forward_button = QPushButton(">")
        self.next_button = QPushButton(">>|")
        for btn in [self.prev_button, self.rewind_button, self.play_pause_button,
                    self.forward_button, self.next_button]:
            controls_layout.addWidget(btn)
        self.content_layout.addLayout(controls_layout)

        self.play_pause_button.clicked.connect(self.toggle_play_pause)
        self.prev_button.clicked.connect(self.handle_prev)
        self.rewind_button.clicked.connect(self.handle_rewind)
        self.forward_button.clicked.connect(self.handle_forward)
        self.next_button.clicked.connect(self.handle_next)

    def _build_secondary_controls(self):
        secondary_layout = QHBoxLayout()
        self.speed_button = QPushButton("1.00x")
        self.speed_button.setFixedWidth(60)
        self.volume_slider = ClickSlider(Qt.Horizontal)
        self.volume_slider.setObjectName("volume_slider")
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(self.config.get_volume())
        self.volume_slider.setFixedWidth(100)
        self.volume_slider.setFixedHeight(9)
        self.volume_slider.sliderPressed.connect(self._hide_popups)
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        self.speed_button.setContextMenuPolicy(Qt.CustomContextMenu)
        self.speed_button.customContextMenuRequested.connect(self._on_speed_right_clicked)
        self.speed_button.clicked.connect(self._on_speed_button_clicked)
        secondary_layout.addWidget(QLabel("Vol:"))
        secondary_layout.addWidget(self.volume_slider)
        secondary_layout.addStretch()
        secondary_layout.addWidget(self.speed_button)
        self.content_layout.addLayout(secondary_layout)

        self.chapter_progress_slider = ClickSlider(Qt.Horizontal)
        self.chapter_progress_slider.setObjectName("chapter_progress")
        self.chapter_progress_slider.setRange(0, 1000)
        self.chapter_progress_slider.setFixedHeight(12)
        self.chapter_progress_slider.sliderPressed.connect(self._hide_popups)
        self.chapter_progress_slider.sliderPressed.connect(self._on_chap_slider_pressed)
        self.chapter_progress_slider.sliderReleased.connect(self._on_chap_slider_released)
        self.content_layout.addWidget(self.chapter_progress_slider)

        chapter_container = QHBoxLayout()
        self.chap_elapsed_label = QLabel("00:00:00")
        self.chap_duration_label = QLabel("00:00:00")
        self.current_chapter_label = QPushButton("Select Chapter")
        self.current_chapter_label.setObjectName("chapter_selector")
        self.current_chapter_label.clicked.connect(self._show_chapter_dropdown)
        chapter_container.addWidget(self.chap_elapsed_label)
        chapter_container.addWidget(self.current_chapter_label, 1)
        chapter_container.addWidget(self.chap_duration_label)
        self.content_layout.addLayout(chapter_container)

    def _build_sidebar(self):
        self.sidebar = QWidget(self)
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(70)
        self.sidebar_layout = QVBoxLayout(self.sidebar)
        self.sidebar_layout.setContentsMargins(10, 10, 10, 10)
        self.settings_trigger_btn = QPushButton("Settings")
        self.settings_trigger_btn.setObjectName("sidebar_settings_btn")
        self.sidebar_layout.addWidget(self.settings_trigger_btn)
        self.speed_trigger_btn = QPushButton("Playback")
        self.speed_trigger_btn.setObjectName("sidebar_speed_btn")
        self.sidebar_layout.addWidget(self.speed_trigger_btn)

        self.sleep_trigger_btn = QPushButton("Sleep")
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

    def _build_settings_panel(self):
        self.settings_panel = QWidget(self)
        self.settings_panel.setObjectName("settings_panel")
        self.settings_panel_layout = QVBoxLayout(self.settings_panel)
        self.settings_panel_layout.setContentsMargins(10, 10, 10, 10)
        appearance_header = QLabel("Appearance")
        appearance_header.setObjectName("settings_header")
        self.settings_panel_layout.addWidget(appearance_header)
        theme_row = QHBoxLayout()
        theme_row.addWidget(QLabel("Theme"))
        theme_row.addStretch()
        self.theme_dropdown = ThemeComboBox()
        self.theme_dropdown.setFixedWidth(160)
        self.theme_dropdown.setView(QListView())
        self.theme_dropdown.setMaxVisibleItems(4)
        self.theme_dropdown.view().setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.theme_dropdown.addItems(sorted(list(THEMES.keys())))
        self.theme_dropdown.setCurrentText(self.config.get_theme())
        self.theme_dropdown.aboutToShowPopup.connect(self.theme_manager._on_theme_dropdown_about_to_show)
        self.theme_dropdown.aboutToHidePopup.connect(self.theme_manager._on_theme_dropdown_about_to_hide)
        self.theme_dropdown.view().entered.connect(lambda idx: self.theme_manager._on_theme_hovered(idx.row()))
        self.theme_dropdown.highlighted[int].connect(self.theme_manager._on_theme_hovered)
        self.theme_dropdown.activated[int].connect(self.theme_manager._on_theme_selected_from_dropdown)
        theme_row.addWidget(self.theme_dropdown)
        self.settings_panel_layout.addLayout(theme_row)
        fade_row = QHBoxLayout()
        fade_label = QLabel("Hover fade (ms)")
        fade_row.addWidget(fade_label)
        fade_row.addStretch()
        self.fade_dropdown = ThemeComboBox()
        self.fade_dropdown.setFixedWidth(60)
        tooltip_text = "Adjust the duration of the cross-fade effect when\n" \
        "previewing or selecting themes. Set to 0 to disable."
        fade_label.setToolTip(tooltip_text)
        self.fade_dropdown.setToolTip(tooltip_text)
        self.fade_dropdown.setView(QListView())
        self.fade_dropdown.setMaxVisibleItems(4)
        self.fade_dropdown.view().setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.fade_dropdown.addItems(["0", "500", "750", "1000", "1500"])
        self.fade_dropdown.setCurrentText(str(self.config.get_theme_fade_duration()))
        self.fade_dropdown.currentTextChanged.connect(lambda v: self.config.set_theme_fade_duration(int(v)))
        fade_row.addWidget(self.fade_dropdown)
        self.settings_panel_layout.addLayout(fade_row)
        blur_row = QHBoxLayout()
        blur_row.addWidget(QLabel("Blur"))
        blur_row.addStretch()
        self.blur_dropdown = ThemeComboBox()
        self.blur_dropdown.setFixedWidth(60)
        self.blur_dropdown.setView(QListView())
        self.blur_dropdown.addItems(["On", "Off"])
        self.blur_dropdown.setCurrentText("On" if self.config.get_blur_enabled() else "Off")
        self.blur_dropdown.setToolTip("Hide the blur effect when entering the Settings page.")
        self.blur_dropdown.currentTextChanged.connect(lambda v: self.config.set_blur_enabled(v == "On"))
        blur_row.addWidget(self.blur_dropdown)
        self.settings_panel_layout.addLayout(blur_row)
        controls_header = QLabel("Controls")
        controls_header.setObjectName("settings_header")
        self.settings_panel_layout.addWidget(controls_header)
        self.settings_panel_layout.addWidget(QLabel("Skip interval"))
        self.settings_panel_layout.addStretch()
        self.settings_panel.hide()
        self.settings_panel_animation = QPropertyAnimation(self.settings_panel, b"pos")
        self.settings_panel_animation.setDuration(300)
        self.settings_panel_animation.setEasingCurve(QEasingCurve.OutCubic)

    def _build_speed_panel(self):
        self.speed_panel = QWidget(self)
        self.speed_panel.setObjectName("speed_panel")
        self.speed_panel_layout = QVBoxLayout(self.speed_panel)
        speed_header = QLabel("Playback Speed")
        speed_header.setObjectName("settings_header")
        self.speed_panel_layout.addWidget(speed_header)
        grid = QGridLayout()
        grid.setSpacing(4)
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
        def_speed_row = QHBoxLayout()
        def_speed_row.addWidget(QLabel("Default speed"))
        def_speed_row.addStretch()
        self.def_speed_dropdown = ThemeComboBox()
        self.def_speed_dropdown.setFixedWidth(60)
        self.def_speed_dropdown.addItems(["1.0", "1.5", "1.75", "2.0", "2.25", "2.5"])
        self.def_speed_dropdown.setCurrentText(str(self.config.get_default_speed()))
        self.def_speed_dropdown.currentTextChanged.connect(lambda v: self.config.set_default_speed(float(v)))
        def_speed_row.addWidget(self.def_speed_dropdown)
        self.speed_panel_layout.addLayout(def_speed_row)
        step_row = QHBoxLayout()
        step_row.addWidget(QLabel("Step"))
        step_row.addStretch()
        self.step_dropdown = ThemeComboBox()
        self.step_dropdown.setFixedWidth(60)
        self.step_dropdown.addItems(["0.05", "0.1", "0.25", "0.5"])
        self.step_dropdown.setCurrentText(str(self.config.get_speed_increment()))
        self.step_dropdown.currentTextChanged.connect(lambda v: self.config.set_speed_increment(float(v)))
        step_row.addWidget(self.step_dropdown)
        self.speed_panel_layout.addLayout(step_row)
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
        """Update the button text with elision."""
        metrics = self.current_chapter_label.fontMetrics()
        # 160 is a safe width for the central area in a 300px window
        elided = metrics.elidedText(text, Qt.ElideRight, 160)
        self.current_chapter_label.setText(elided)

    def _check_library_status(self):
        """Lazy scan on startup. Checks if locations exist but books are missing."""
        locs = self.db.get_scan_locations()
        count = self.db.get_book_count()
        
        if locs:
            self.status_banner.setText("Library scanning...")
            self.status_banner.show()
            self.scanner.start()
        elif count == 0:
            # First launch without folders
            self.status_banner.setText("No library folders. Add a folder in Settings.")
            self.status_banner.show()

    def _on_scan_progress(self, current, total):
        self.status_banner.setText(f"Loading Library... ({current}/{total})")
        if not self.status_banner.isVisible():
            self.status_banner.show()

    def _on_scan_finished(self, total):
        self.status_banner.setText(f"Library updated: {total} books.")
        QTimer.singleShot(3000, self.status_banner.hide)

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
        last_pos = self.config.get_last_position(self.current_file)
        if last_pos > 0:
            self.player.time_pos = last_pos
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
            current_time = time.time()
        except ShutdownError:
            return

        if not self.current_file or mpv_pos is None or dur is None:
            self.play_pause_button.setText("Play")
            return

        if is_paused:
            # Only update the displayed position while paused if we explicitly 
            # triggered a seek or if the drift is massive (emergency resync).
            # This prevents cumulative 'speed drift' from jumping the UI.
            if self._paused_time is None or self._is_seeking or abs(mpv_pos - self._paused_time) > 1.0:
                self._paused_time = mpv_pos
                self._is_seeking = False
            pos = self._paused_time
        else:
            self._paused_time = None
            pos = mpv_pos
        
        is_eof = self.player.eof_reached

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

        if dur > 0:
            # Update overall progress
            if not self.is_slider_dragging:
                percent = (pos / dur) * 100
                self.progress_slider.setValue(int((pos / dur) * 1000))
                self.time_label.setText(f"{self._format_time(pos)} / {self._format_time(dur)}")
                self.progress_percentage_label.setText(f"{percent:.1f}%")

        curr_chap = self.player.chapter or 0
        chap_list = self.player.chapter_list or []
        if chap_list and curr_chap < len(chap_list):
            # Update chapter progress
            start = chap_list[curr_chap].get('time', 0)
            end = chap_list[curr_chap+1].get('time', dur) if curr_chap + 1 < len(chap_list) else dur
            chap_dur = end - start
            
            if not self.is_chapter_slider_dragging:
                c_elapsed = max(0, pos - start)
                self.chap_elapsed_label.setText(self._format_time(c_elapsed))
                self.chap_duration_label.setText(self._format_time(end - start))
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
            new_pos = (self.progress_slider.value() / 1000) * self.player.duration
            self.player.time_pos = new_pos
            self._is_seeking = True
        self.is_slider_dragging = False

    def _on_chap_slider_pressed(self):
        self.is_chapter_slider_dragging = True

    def _on_chap_slider_released(self):
        if self.player and self.player.duration:
            curr_chap = self.player.chapter or 0
            chap_list = self.player.chapter_list or []
            if chap_list and curr_chap < len(chap_list):
                dur = self.player.duration
                start = chap_list[curr_chap].get('time', 0)
                end = chap_list[curr_chap+1].get('time', dur) if curr_chap + 1 < len(chap_list) else dur
                chap_dur = end - start
                if chap_dur > 0:
                    new_chap_pos = (self.chapter_progress_slider.value() / 1000) * chap_dur
                    self.player.time_pos = start + new_chap_pos
                    self._is_seeking = True
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
            self.sleep_trigger_btn.setText("Sleep") # No brackets
            self.sleep_cancel_btn.show()
            self.sleep_pulse_anim.start()
        elif mode in ['end_of_chapter', 'end_of_book']:
            self._sleep_mode = mode
            self.config.set_sleep_mode(mode)
            QTimer.singleShot(500, self.disable_sleep_btn.show)
            self.sleep_trigger_btn.setText("Sleep") # No brackets
            self.sleep_cancel_btn.show()
            self.sleep_pulse_anim.start()

        self.panel_manager._close_sleep_flow()
        self._update_ui_sync() # Force UI update

    def _disable_sleep_timer(self):
        """Disables the active sleep timer."""
        self._sleep_timer_end_time = None
        self._sleep_mode = None
        self.disable_sleep_btn.hide()
        self.sleep_trigger_btn.setText("Sleep")
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
        for panel in [self.settings_panel, self.speed_panel, self.sleep_panel]:
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

            # Update tooltips for navigation buttons
            if index > 0:
                prev_title = chaps[index - 1].get('title') or f"Chapter {index}"
                self.prev_button.setToolTip(prev_title)
            else:
                self.prev_button.setToolTip("")

            if index < len(chaps) - 1:
                next_title = chaps[index + 1].get('title') or f"Chapter {index + 2}"
                self.next_button.setToolTip(next_title)
            else:
                self.next_button.setToolTip("")

    def _load_cover_art(self, file_path):
        """Extracts and displays cover art from the file tags."""
        if not file_path:
            self.current_cover_pixmap = QPixmap()
            self.cover_art_label.hide()
            self.metadata_label.show()
            self.metadata_label.setText("No book loaded")
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

        self._update_cover_art_scaling()
        # Reposition percentage label
        if hasattr(self, 'progress_percentage_label'):
            self.progress_percentage_label.resize(self.progress_slider.size())

    def _on_drag_area_pressed(self, event):
        if event.button() == Qt.LeftButton:
            self.panel_manager.hide_all_panels() # Use panel manager's hide_all_panels
            self.windowHandle().startSystemMove()
        elif event.button() == Qt.RightButton:
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
        self.player.pause = not self.player.pause

    def handle_rewind(self):
        self.panel_manager.hide_all_panels()
        if self.player:
            skip = self.config.get_skip_duration()
            self.player.time_pos = max(0, (self.player.time_pos or 0) - skip)
            self._is_seeking = True

    def handle_forward(self):
        self.panel_manager.hide_all_panels()
        if self.player:
            skip = self.config.get_skip_duration()
            self.player.time_pos = min(self.player.duration or 0, (self.player.time_pos or 0) + skip)
            self._is_seeking = True

    def handle_prev(self):
        self.panel_manager.hide_all_panels()
        if self.player:
            self.player.previous_chapter()
            self._is_seeking = True

    def handle_next(self):
        self.panel_manager.hide_all_panels()
        if self.player:
            self.player.next_chapter()
            self._is_seeking = True

    def eventFilter(self, obj, event):
        """Global event filter to handle dismissing popups on clicks outside."""
        if event.type() == QEvent.MouseButtonPress:
            if hasattr(self, 'chapter_list_widget') and self.chapter_list_widget.isVisible():
                # Convert global position to check if it's inside the dropdown
                gp = event.globalPosition().toPoint()
                if not self.chapter_list_widget.geometry().contains(gp):
                    self.panel_manager.hide_all_panels()
        return super().eventFilter(obj, event)
    def closeEvent(self, event):
        if self.player:
            self.config.set_volume(self.volume_slider.value())
            if self.current_file and self.player.instance:
                self.config.set_last_position(self.current_file, self.player.time_pos)
            self.player.terminate()
        event.accept()
