# THEME_ANIM_TODO: MainWindow, TitleBar, ChapterList, SpeedControlsPanel, 
# AudioSettingsTab, SleepTimerPanel, StatsPanel, BookDetailPanel, 
# status_banner, sidebar, vol_container
import os
import re
from PySide6.QtWidgets import (
    QLineEdit, QFileDialog, QListWidget,
    QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QStackedWidget,
    QSizePolicy, QApplication, QListView, QGraphicsBlurEffect, QGridLayout, QComboBox, QGraphicsOpacityEffect,
    QScrollArea, QFrame, QTabWidget
)
from PySide6.QtCore import (
    Qt, QTimer, QPoint, QEvent, QPropertyAnimation, QEasingCurve, QModelIndex,
    QRegularExpression, Signal, QObject, QSize, QByteArray
)
from PySide6.QtGui import QPixmap, QGuiApplication, QColor, QIntValidator, QRegularExpressionValidator, QIcon, QPainter
from PySide6.QtSvg import QSvgRenderer

from .player import Player, _CHAPTER_BOUNDARY_EPSILON
from .config import Config
from .themes import THEMES, _resolve_theme
from .ui.title_bar import TitleBar, RightClickButton, ThemeItem
from .ui.controls import ClickSlider, ScrollingLabel, HoverButton, FreezableLabel
from .ui.chapter_list import ChapterList # Keep ChapterList here as it's a direct child of MainWindow
from .ui.speed_controls import SpeedControlsPanel
from .ui.audio_controls import AudioSettingsTab
from .ui.sleep_timer import SleepTimerPanel
from .ui.theme_manager import ThemeManager, ThemeComboBox
import time # For sleep timer
from .library_controller import LibraryController
from .ui.cover_loader import CoverLoaderWorker # For async cover loading
from .ui.library import LibraryPanel
from .ui.panels import PanelManager # New import for PanelManager
from .ui.stats_panel import StatsPanel
from .ui.book_detail_panel import BookDetailPanel
from .ui.tag_manager import TagManagerWidget
from .ui.carousel import CoverCarousel
from .db import LibraryDB
from .library.scanner import LibraryScanner
from .book_quotes import BOOK_QUOTES
from mpv import ShutdownError
from .settings_controller import SettingsController
from .session_recorder import SessionRecorder

_ICONS_DIR = os.path.join(os.path.dirname(__file__), "assets", "icons")

# Fixed height of the cover-art box. The window is fixed-size; this value is the
# height the cover area occupies in the correct ("proper") layout. The cover
# pixmap is scaled to fit inside (label width x this height) preserving aspect
# ratio, and centered. A fixed height guarantees the box can never resize and
# push the transport controls out of view.
COVER_AREA_HEIGHT = 280

def _load_svg_icon(name, color="white"):
    try:
        path = os.path.join(_ICONS_DIR, name)
        with open(path) as f:
            data = f.read()
        data = re.sub(r'fill="(?!none)[^"]*"',         f'fill="{color}"',   data)
        data = re.sub(r'stroke="(?!none)[^"]*"',       f'stroke="{color}"', data)
        data = re.sub(r'(fill:)(?!none)[^;}"]*',       rf'\g<1>{color}',     data)
        data = re.sub(r'(stroke:)(?!none)[^;}"]*',     rf'\g<1>{color}',     data)
        ba = QByteArray(data.encode())
        renderer = QSvgRenderer(ba)
        size = renderer.defaultSize()
        pixmap = QPixmap(size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        return QIcon(pixmap)
    except Exception as e:
        print(f"Warning: could not load icon {name}: {e}")
        return QIcon()

class UIInterface:
    def __init__(self, main):
        self._main = main

    def set_visible(self, v): self._main._set_interface_visible(v)
    def update_folders(self, p): self._main._update_folder_list_widget(p)
    def refresh_panel(self, *a, **k): self._main.library_panel.refresh(*a, **k)
    def update_status(self, *a, **k): self._main._update_status_banner_ui(*a, **k)
    def update_metadata(self, *a, **k): self._main._update_metadata_ui(*a, **k)
    def update_prompts(self, v): self._main._update_idle_prompts_ui(v)
    def update_quote(self, *a, **k): self._main._update_quote_ui(*a, **k)
    def set_quote_rotation(self, v): self._main._set_quote_rotation(v)
    def show_carousel(self): self._main._show_carousel()
    def hide_carousel(self): self._main._hide_carousel()
    def set_scan_buttons_enabled(self, v): self._main._set_scan_buttons_enabled(v)
    def set_prompt_text(self, text): self._main.library_prompt_label.setText(text)
    def set_library_btn_visible(self, v):
        self._main.library_trigger_btn.setVisible(v)
        self._main.library_separator.setVisible(v)

class AppInterface:
    def __init__(self, main):
        self._main = main

    def get_current_file(self): return self._main.current_file
    def load_cover_art(self, path): self._main._load_cover_art(path)
    def on_book_removed(self): self._main._on_book_removed()
    def refresh_tag_manager(self) -> None: self._main.tags_panel.refresh_books()
    def refresh_stats(self) -> None: self._main.stats_panel.refresh_current_tab()

class BrowserInterface:
    def __init__(self, main):
        self._main = main

    def get_selected_folder(self): return self._main._get_selected_folder_path()
    def pick_folder(self): return self._main._get_new_folder_path()


class VisualsInterface:
    def __init__(self, main):
        self._main = main

    def set_naming_pattern_selection(self, current):
        m = self._main
        if not hasattr(m, 'at_pattern_btn'): return
        m.at_pattern_btn.setProperty("selected", "true" if current == "Author - Title" else "false")
        m.ta_pattern_btn.setProperty("selected", "true" if current == "Title - Author" else "false")
        for btn in [m.at_pattern_btn, m.ta_pattern_btn]:
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def set_scroll_selection(self, current):
        m = self._main
        if not hasattr(m, 'scroll_buttons'): return
        m.current_chapter_label.set_scroll_mode(current)
        for mode, btn in m.scroll_buttons.items():
            btn.setProperty("selected", "true" if mode == current else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def set_hints_selection(self, mode):
        m = self._main
        if not hasattr(m, 'hints_buttons'): return
        for m_val, btn in m.hints_buttons.items():
            btn.setProperty("selected", "true" if m_val == mode else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        if mode == "Off":
            m._clear_preview()
        elif m.prev_button.underMouse():
            m._on_prev_hover()
        elif m.next_button.underMouse():
            m._on_next_hover()

    def set_notch_animation_selection(self, enabled):
        m = self._main
        if not hasattr(m, 'notch_animation_buttons'): return
        for mode, btn in m.notch_animation_buttons.items():
            is_selected = (mode == "On" if enabled else mode == "Off")
            btn.setProperty("selected", "true" if is_selected else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def set_undo_selection(self, current):
        m = self._main
        if not hasattr(m, 'speed_panel'): return
        for val, btn in m.speed_panel.undo_buttons.items():
            btn.setProperty("selected", "true" if val == current else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def set_fade_selection(self, current):
        m = self._main
        if not hasattr(m, 'fade_buttons'): return
        for ms, btn in m.fade_buttons.items():
            btn.setProperty("selected", "true" if ms == current else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def set_blur_selection(self, enabled):
        m = self._main
        if not hasattr(m, 'blur_buttons'): return
        for state, btn in m.blur_buttons.items():
            is_selected = (state == "On" if enabled else state == "Off")
            btn.setProperty("selected", "true" if is_selected else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        if not enabled:
            m.blur_effect.setBlurRadius(0)

    def set_notches_selection(self, enabled):
        m = self._main
        if not hasattr(m, 'notches_buttons'): return
        for mode, btn in m.notches_buttons.items():
            is_selected = (mode == "On" if enabled else mode == "Off")
            btn.setProperty("selected", "true" if is_selected else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        # Hide animation settings when notches are off
        if hasattr(m, 'notches_anim_header_label'):
            m.notches_anim_header_label.setVisible(enabled)
        if hasattr(m, 'notch_animation_buttons'):
            for btn in m.notch_animation_buttons.values():
                btn.setVisible(enabled)

    def set_hover_fade_selection(self, mode):
        m = self._main
        if not hasattr(m, 'hover_fade_buttons'): return
        for md, btn in m.hover_fade_buttons.items():
            btn.setProperty("selected", "true" if md == mode else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        m.library_panel.set_hover_fade_enabled(mode)

    def set_digit_mode_selection(self, mode):
        m = self._main
        if not hasattr(m, 'digit_mode_buttons'): return
        for md, btn in m.digit_mode_buttons.items():
            btn.setProperty("selected", "true" if md == mode else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def set_digit_autoplay_selection(self, enabled):
        m = self._main
        if not hasattr(m, 'digit_autoplay_buttons'): return
        for v, btn in m.digit_autoplay_buttons.items():
            btn.setProperty("selected", "true" if v == enabled else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def set_chapter_source_selection(self, source):
        m = self._main
        if not hasattr(m, 'chapter_source_buttons'): return
        for src, btn in m.chapter_source_buttons.items():
            btn.setProperty("selected", "true" if src == source else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)


class PanelInterface:
    def __init__(self, speed_panel, sleep_panel, audio_tab):
        self._speed = speed_panel
        self._sleep = sleep_panel
        self._audio = audio_tab
    def validate_speed_panel_settings(self):
        if self._speed: self._speed._validate_smart_rewind_settings(finalize=True)
    def update_speed_panel_visuals(self, theme_name=None):
        if self._speed: self._speed.update_visuals(theme_name)
    def update_sleep_panel_visuals(self):
        if self._sleep: self._sleep.update_panel_styling()
    def update_audio_panel_visuals(self):
        if self._audio: self._audio.update_visuals()


class UICallbackInterface:
    def __init__(self, main):
        self._main = main
    def set_folder_list(self, folders): self._main._update_folder_list_widget(folders)
    def get_selected_folder_path(self): return self._main._get_selected_folder_path()
    def open_folder_dialog(self): return self._main._get_new_folder_path()
    def update_status_banner(self, *a, **kw): self._main._update_status_banner_ui(*a, **kw)
    def update_metadata(self, *a, **kw): self._main._update_metadata_ui(*a, **kw)
    def set_chapter_title(self, text): self._main._update_chapter_title_text(text)
    def refresh_notches(self, skip_animation=False): self._main._refresh_notches(skip_animation=skip_animation)
    def get_book_quote(self): return self._main.book_quotes if hasattr(self._main, 'book_quotes') else None


class LibraryInterface:
    def __init__(self, db, library_panel):
        self._db = db
        self._panel = library_panel
    def reparse_db(self, pattern): self._db.reparse_library(pattern)
    def refresh_library_panel(self, force=False): self._panel.refresh(force=force)


class PlayerInterface:
    def __init__(self, main):
        self._main = main
    def get_current_file(self): return self._main.get_current_file()
    def load_cover_art(self, path): self._main._load_cover_art(path)


class MainWindow(QWidget):  # QWidget, not QMainWindow
    naming_pattern_changed = Signal(str)
    scroll_mode_changed = Signal(str)
    hints_mode_changed = Signal(str)
    notches_mode_changed = Signal(bool)
    notch_animation_mode_changed = Signal(bool)
    undo_mode_changed = Signal(int)
    fade_mode_changed = Signal(int)
    blur_mode_changed = Signal(bool)
    hover_fade_changed = Signal(str)
    chapter_digit_mode_changed = Signal(str)
    chapter_digit_autoplay_changed = Signal(bool)
    chapter_list_source_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.current_cover_pixmap = QPixmap()
        self._pending_cover_pixmap = None
        self._cover_fit_mode = 'fit'
        self._carousel = None           # CoverCarousel widget inside carousel_holder (lazily built)
        self.is_slider_dragging = False
        self.is_chapter_slider_dragging = False
        self._chapter_ui_active = True
        self.current_file = ""
        self.config = Config()
        self.db = LibraryDB()
        self.player = Player(self.db, self.config)
        self._prev_chap_title = ""
        self._next_chap_title = ""
        self.theme_manager = ThemeManager(self)
        self._last_pause_timestamp = None
        self.scanner = LibraryScanner(self.db.db_path)
        self._undo_pos = None
        self._paused_time = None
        self._undo_timer = QTimer(self)
        self._last_saved_pct = -1
        self._last_undo_click_time = 0
        self._undo_sliding_in: bool | None = None
        self.audio_tab = None
        self.panel_manager = None # Will be initialized after widgets are created
        self.show_remaining_time = self.config.get_show_remaining_time()
        self._eof_event_written: bool = False
        self._eof_dur_fetched: bool = False

        # Session recording
        self._current_book = None
        self.session_recorder = SessionRecorder(
            db=self.db,
            get_position_fn=self._get_current_position,
            get_book_fn=lambda: self._current_book,
            parent=self,
        )

        self._mpv_ready = True
        self._pre_switch_slider_value = None
        self._pre_switch_chap_slider_value = None

        self._setup_ui()

        self.ui_timer = QTimer()
        self.quote_timer = QTimer()
        
        self.ui_timer.timeout.connect(self._update_ui_sync)
        self.player.chapter_changed.connect(self._update_chapter_label_from_index, Qt.ConnectionType.QueuedConnection)
        self.player.book_ready.connect(self._on_file_ready, Qt.ConnectionType.QueuedConnection)
        self.player.book_ready.connect(self._on_file_loaded_populate_chapters, Qt.ConnectionType.QueuedConnection)
        self.player.file_switched.connect(self._on_vt_file_switched, Qt.ConnectionType.QueuedConnection)
        self.player.load_failed.connect(self._on_load_failed, Qt.ConnectionType.QueuedConnection)
        self.session_recorder.session_written.connect(self._on_session_written)

        # Initialize Library Controller
        self.library_controller = LibraryController(
            self.db, self.config, self.scanner,
            UIInterface(self), 
            AppInterface(self), 
            BrowserInterface(self)
        )

        # Consolidated connections for library-related UI -> controller
        # (moved here to ensure `self.library_controller` is available)
        self.cancel_scan_btn.clicked.connect(self.library_controller._on_cancel_scan_clicked)
        self.scan_now_btn.clicked.connect(self.library_controller._on_scan_now_clicked)
        self.add_folder_btn.clicked.connect(self.library_controller._on_scan_now_clicked)
        self.remove_folder_btn.clicked.connect(self.library_controller._on_remove_folder_clicked)
        self.refresh_library_btn.clicked.connect(lambda: self.library_controller._check_library_status(manual=True, force_refresh=True))

        self.scanner.progress.connect(self.library_controller._on_scan_progress)
        self.scanner.finished.connect(self.library_controller._on_scan_finished)
        self.quote_timer.timeout.connect(self.library_controller._rotate_quote)
        self.library_controller._refresh_folder_list()

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
        self.undo_anim.finished.connect(self._on_undo_anim_finished)

        QApplication.instance().installEventFilter(self)

        # Restore last played book if it exists
        last_book = self.config.get_last_book()
        # Verify the book still belongs to an active library location
        locations = self.db.get_scan_locations()
        is_valid = any(last_book.startswith(loc if loc.endswith(os.sep) else loc + os.sep) for loc in locations)
        if last_book and is_valid and os.path.exists(last_book):
            self.current_file = last_book
            self._mpv_ready = True
            self.player.load_book(self.current_file)
            self.player.ungate_play()
            self.library_panel.set_playing_path(self.current_file)
        self.chapter_list_widget.set_player(self.player)
        self.chapter_list_widget.set_config(self.config)

        self._load_cover_art(self.current_file)
        
        # Handle selection from library
        self.library_panel.book_selected.connect(self._on_book_selected_from_library)
        self.library_panel.detail_requested.connect(self._on_library_detail_requested)
        
        self.library_controller._check_library_status()
        self.ui_timer.start(200)

        # Wire SettingsController with explicit, minimal interfaces (defined at module level).
        visuals = VisualsInterface(self)
        panels = PanelInterface(self.speed_panel, self.sleep_panel, self.audio_tab)
        ui_callbacks = UICallbackInterface(self)
        library = LibraryInterface(self.db, self.library_panel)
        player = PlayerInterface(self)
        self.settings_controller = SettingsController(self.config, visuals, panels, ui_callbacks, library, player)

        self.settings_controller.bind_mainwindow_handlers(self)

        self._theme_rotate_cooldown = QTimer(self)
        self._theme_rotate_cooldown.setSingleShot(True)
        self._theme_rotate_cooldown.setInterval(2000)
        self._theme_rotate_cooldown.timeout.connect(self._on_theme_rotate_cooldown)
        self._theme_rotate_pending = False

        # Ensure initial visuals are synchronized via the controller (was previously done
        # during _build_settings_panel when these methods existed on MainWindow).
        # Delegate to SettingsController visual updaters now that it's bound.
        try:
            self.settings_controller._update_pattern_visuals()
            self.settings_controller.sync_all_settings_visuals()
            self.settings_controller._update_scroll_mode_visuals()
            self.settings_controller._update_hints_visuals()
            self.settings_controller._update_notches_visuals()
            self.settings_controller._update_fade_visuals()
            self.settings_controller._update_blur_visuals()
            self.settings_controller._update_undo_visuals()
        except Exception:
            pass

        self.show()
        self.theme_manager.initialize_fade_overlay()
        # Pause the carousel timer during theme fades to prevent freeze/ghost artifacts.
        # stateChanged covers Running (stop), Stopped (resume), and abort paths.
        self.theme_manager._fade_anim.stateChanged.connect(self._on_fade_state_changed)

    def _on_fade_state_changed(self, new_state, old_state):
        from PySide6.QtCore import QAbstractAnimation
        if new_state == QAbstractAnimation.Running:
            if self._carousel is not None:
                self._carousel.stop()
        elif new_state == QAbstractAnimation.Stopped:
            if self._carousel is not None:
                self._carousel.start()

    def _setup_ui(self):
        self.setFixedSize(300, 564)

        # Initialize Sleep Timer Panel early to allow connections in build methods
        self.sleep_panel = SleepTimerPanel(self.player, self.config, self.theme_manager, self)
        self.sleep_panel.hide()
        self.sleep_panel_animation = QPropertyAnimation(self.sleep_panel, b"pos")
        self.sleep_panel_animation.setDuration(300)
        self.sleep_panel_animation.setEasingCurve(QEasingCurve.OutCubic)

        self.setObjectName("mainwindow")

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
        self.chapter_list_widget.chapter_selected.connect(self._on_chapter_list_selected)
        
        self._build_sidebar()
        self._build_library_panel()
        self._build_settings_panel()
        self._build_stats_panel()
        self._build_tags_panel()

        self.speed_panel = SpeedControlsPanel(self.player, self.config, self.theme_manager, self)
        self.speed_panel.hide()
        self.speed_panel_animation = QPropertyAnimation(self.speed_panel, b"pos")
        self.speed_panel_animation.setDuration(300)
        self.speed_panel_animation.setEasingCurve(QEasingCurve.OutCubic)
        
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

        # Speed/grid visual initialization moved to after SettingsController binding

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
        self._build_book_detail_panel()
        self.stats_panel.set_panel_manager(self.panel_manager)

        # Connect Sleep Timer signals after panel_manager is initialized
        self.sleep_panel.timer_started.connect(self._on_sleep_timer_started)
        self.sleep_panel.timer_stopped.connect(self._on_sleep_timer_stopped)
        self.sleep_panel.timer_expired.connect(self._on_sleep_timer_expired)
        self.sleep_panel.display_text_updated.connect(self.sleep_timer_label.setText)
        self.sleep_panel.timer_started.connect(self.panel_manager._close_sleep_flow)
        # Delegate speed display update to a dedicated slot to ensure reliability
        self.speed_panel.speed_changed.connect(self._on_player_speed_changed)
        self.speed_panel.skip_duration_changed.connect(lambda _: self._update_skip_icons())
        self.speed_panel.close_requested.connect(
            lambda: self.panel_manager._close_speed_flow() if self.panel_manager else None
        )
        self.library_panel.back_requested.connect(self.panel_manager._close_library_flow)

        self.theme_manager._apply_stylesheets(self.theme_manager._current_theme_name)

        QTimer.singleShot(4000, self.library_panel.start_idle_preload)

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

        layout.addStretch()
        layout.addWidget(self.status_label)
        layout.addStretch()
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
        self.progress_slider.rightClicked.connect(self._on_slider_right_clicked)
        self.root_layout.addWidget(self.progress_slider)

        self.progress_percentage_label = QLabel(self.progress_slider)
        self.progress_percentage_label.setObjectName("percentage_label")
        self.progress_percentage_label.setAlignment(Qt.AlignCenter)
        self.progress_percentage_label.setAttribute(Qt.WA_TransparentForMouseEvents)

    def _build_cover_art(self):
        self.cover_art_label = QLabel()
        self.cover_art_label.setAlignment(Qt.AlignCenter)
        self.cover_art_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.cover_art_label.setMinimumSize(0, 0)
        self.cover_art_label.setFixedHeight(COVER_AREA_HEIGHT)
        self.cover_art_label.mousePressEvent = self._on_drag_area_pressed
        self.visual_layout.addWidget(self.cover_art_label)

    def _build_metadata(self):
        # Scan section: prompt + button, spacer-positioned, claims remaining space.
        self.scan_section = QWidget()
        scan_layout = QVBoxLayout(self.scan_section)
        scan_layout.setContentsMargins(0, 0, 0, 0)
        scan_layout.setSpacing(0)           # spacing controlled manually via addSpacing

        self.library_prompt_label = QLabel("No library folders.")
        self.library_prompt_label.setAlignment(Qt.AlignCenter)
        self.library_prompt_label.setStyleSheet("font-weight: bold; font-size: 16px;")
        scan_layout.addSpacing(80)          # label top lands at 50px from section top
        scan_layout.addWidget(self.library_prompt_label)
        scan_layout.addSpacing(80)          # ~80px gap → button top lands at ~150px from section top
                                            # (exact value depends on label height; tune if needed)
        self.scan_now_btn = QPushButton("Scan now")
        self.scan_now_btn.setFixedWidth(120)
        scan_layout.addWidget(self.scan_now_btn, 0, Qt.AlignCenter)
        scan_layout.addStretch()            # eat remaining space below the button
        self.visual_layout.addWidget(self.scan_section, 1)  # stretch 1: claims remaining space

        # Metadata (Book Info) — shared with player state (shows "Author - Title" for no-cover books)
        self.metadata_label = QLabel("")
        self.metadata_label.setAlignment(Qt.AlignCenter)
        self.metadata_label.setWordWrap(True)
        self.metadata_label.mousePressEvent = self._on_drag_area_pressed
        self.visual_layout.addWidget(self.metadata_label)

        # No-book section — permanent fixed slot; never inserted/removed at runtime.
        self.no_book_section = QWidget()
        nb_layout = QVBoxLayout(self.no_book_section)
        nb_layout.setContentsMargins(0, 0, 0, 0)
        nb_layout.setSpacing(0)

        nb_layout.addSpacing(80)
        self.no_book_label = QLabel("No book selected.")
        self.no_book_label.setAlignment(Qt.AlignCenter)
        self.no_book_label.setStyleSheet("font-weight: bold; font-size: 16px;")
        nb_layout.addWidget(self.no_book_label)

        nb_layout.addSpacing(125)

        # Permanent carousel slot — always reserves 150px whether or not a carousel is inside.
        self.carousel_holder = QWidget()
        self.carousel_holder.setFixedHeight(150)
        self.carousel_holder.setFixedWidth(280)
        ch_layout = QVBoxLayout(self.carousel_holder)
        ch_layout.setContentsMargins(0, 0, 0, 0)
        ch_layout.setSpacing(0)
        nb_layout.addWidget(self.carousel_holder, 0, Qt.AlignHCenter)

        nb_layout.addSpacing(12)

        self.go_to_library_btn = QPushButton("Go to Library")
        self.go_to_library_btn.setObjectName("go_to_library_btn")
        self.go_to_library_btn.setFixedWidth(110)
        nb_layout.addWidget(self.go_to_library_btn, 0, Qt.AlignCenter)

        nb_layout.addStretch()

        self.no_book_section.hide()
        self.visual_layout.addWidget(self.no_book_section)

        # Quote section: fixed-height box, quote bottom-anchored, expands upward.
        self.quote_section = QWidget()
        self.quote_section.setFixedHeight(238)
        quote_layout = QVBoxLayout(self.quote_section)
        quote_layout.setContentsMargins(0, 0, 0, 0)
        self.quote_label = QLabel("")
        self.quote_label.setObjectName("quote_label")
        self.quote_label.setAlignment(Qt.AlignBottom | Qt.AlignHCenter)
        self.quote_label.setWordWrap(True)
        quote_layout.addWidget(self.quote_label, 0, Qt.AlignBottom)
        self.visual_layout.addWidget(self.quote_section)
    def _build_controls(self):
        # Speed button centered above transport controls
        speed_row = QHBoxLayout()
        speed_row.addStretch()
        self.speed_button = QPushButton("1.00x")
        self.speed_button.setObjectName("speed_btn")
        self.speed_button.setFixedWidth(60)
        self.speed_button.setFixedHeight(33)
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

        self.transport_controls = QWidget()
        controls_layout = QHBoxLayout(self.transport_controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        self.prev_button = HoverButton()
        self.prev_button.setObjectName("prev_btn")
        _icon = _load_svg_icon("previous.svg")
        if _icon.isNull():
            self.prev_button.setText("|<<")
        else:
            self.prev_button.setIcon(_icon)
        self.prev_button.setFixedSize(46, 33)
        self.prev_button.setIconSize(QSize(32, 22))
        self.rewind_button = RightClickButton("")
        self.rewind_button.setObjectName("rewind_btn")
        self.rewind_button.setFixedSize(46, 33)
        self.rewind_button.setIconSize(QSize(28, 17))
        self.rewind_button.setAutoRepeat(True)
        self.rewind_button.setAutoRepeatDelay(500)   # Wait 500ms before scanning
        self.rewind_button.setAutoRepeatInterval(150) # Skip again every 150ms
        self.play_pause_button = QPushButton()
        self.play_pause_button.setObjectName("play_pause_btn")
        self._icon_play = _load_svg_icon("play.svg")
        self._icon_pause = _load_svg_icon("pause.svg")
        self._icon_restart = _load_svg_icon("restart.svg")
        self._icon_rewind  = {5: _load_svg_icon("rewind_5.svg"),  10: _load_svg_icon("rewind_10.svg"),  30: _load_svg_icon("rewind_30.svg")}
        self._icon_forward = {5: _load_svg_icon("forward_5.svg"), 10: _load_svg_icon("forward_10.svg"), 30: _load_svg_icon("forward_30.svg")}
        if self._icon_play.isNull():
            self.play_pause_button.setText("Play")
        else:
            self.play_pause_button.setIcon(self._icon_play)
        self.play_pause_button.setFixedSize(56, 33)
        self.play_pause_button.setIconSize(QSize(52, 33))
        self.forward_button = RightClickButton("")
        self.forward_button.setObjectName("forward_btn")
        self.forward_button.setFixedSize(46, 33)
        self.forward_button.setIconSize(QSize(28, 17))
        self.forward_button.setAutoRepeat(True)
        self.forward_button.setAutoRepeatDelay(500)
        self.forward_button.setAutoRepeatInterval(150)
        self.next_button = HoverButton()
        self.next_button.setObjectName("next_btn")
        _icon = _load_svg_icon("next.svg")
        if _icon.isNull():
            self.next_button.setText(">>|")
        else:
            self.next_button.setIcon(_icon)
        self.next_button.setFixedSize(46, 33)
        self.next_button.setIconSize(QSize(32, 22))
        for btn in [self.prev_button, self.rewind_button, self.play_pause_button,
                    self.forward_button, self.next_button]:
            btn.setFixedHeight(33)
            controls_layout.addWidget(btn)
        self.content_layout.addWidget(self.transport_controls)

        self._reload_button_icons(self.theme_manager._current_theme_name)
        self.play_pause_button.clicked.connect(self.toggle_play_pause)
        self.prev_button.clicked.connect(self.handle_prev)
        self.prev_button.rightClicked.connect(self._on_prev_right_click)
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
        self.chap_elapsed_label = FreezableLabel("00:00:00")
        self.chap_elapsed_label.setObjectName("chap_elapsed_label")
        self.chap_elapsed_label.setFixedWidth(48)
        self.chap_elapsed_label.setFixedHeight(24)
        self.chap_elapsed_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        
        self.chap_duration_label = FreezableLabel("00:00:00")
        self.chap_duration_label.setObjectName("chap_duration_label")
        self.chap_duration_label.setFixedWidth(48)
        self.chap_duration_label.setFixedHeight(24)
        self.chap_duration_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.chap_duration_label.mousePressEvent = self._toggle_remaining_time

        self.current_chapter_label = ScrollingLabel("")
        self.current_chapter_label.setObjectName("chapter_selector")
        self.current_chapter_label.setFixedHeight(24)
        self.current_chapter_label.clicked.connect(self._show_chapter_dropdown)
        self.current_chapter_label.set_scroll_mode(self.config.get_scroll_mode())
        self._chapter_label_clickable = False
        self.current_chapter_label.setCursor(Qt.ArrowCursor)
        
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
        self.current_time_label = FreezableLabel("00:00:00")
        self.current_time_label.setObjectName("curr_time_label")
        self.current_time_label.setFixedWidth(80)
        self.current_time_label.setFixedHeight(24)
        self.current_time_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        
        self.total_time_label = FreezableLabel("00:00:00")
        self.total_time_label.setObjectName("total_time_label")
        self.total_time_label.setFixedWidth(80)
        self.total_time_label.setFixedHeight(24)
        self.total_time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.total_time_label.mousePressEvent = self._toggle_remaining_time
        self.total_time_label.setCursor(Qt.PointingHandCursor)
        
        self.sleep_timer_label = QPushButton("")
        self.sleep_timer_label.setObjectName("sleep_timer_display")
        self.sleep_timer_label.setFixedWidth(104)
        self.sleep_timer_label.clicked.connect(self.sleep_panel.disable_sleep_timer)
        
        for lbl in [self.current_time_label, self.total_time_label, self.sleep_timer_label]:
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

        self.vol_stack = QStackedWidget()
        self.vol_stack.setFixedWidth(104) # Sleep timer location
        self.vol_stack.setFixedHeight(24)
        self.vol_stack.addWidget(self.sleep_timer_label)

        self.vol_container = QWidget()
        vol_container_layout = QVBoxLayout(self.vol_container)
        vol_container_layout.setContentsMargins(0, 6, 0, 0) # Volume bar location
        vol_container_layout.setSpacing(0)
        vol_container_layout.addWidget(self.volume_slider)
        vol_container_layout.addStretch()
        self.vol_stack.addWidget(self.vol_container)

        book_info_layout.addWidget(self.current_time_label)
        book_info_layout.addWidget(self.vol_stack)
        book_info_layout.addStretch(1)
        book_info_layout.addWidget(self.total_time_label)
        self.content_layout.addLayout(book_info_layout)

        # Setup Volume Overlay Animations
        self.vol_opacity = QGraphicsOpacityEffect(self.volume_slider)
        self.vol_opacity.setOpacity(0.0)
        self.volume_slider.setGraphicsEffect(self.vol_opacity)
        
        self.vol_fade_anim = QPropertyAnimation(self.vol_opacity, b"opacity")
        self.vol_fade_anim.setDuration(500) # Slow fade
        self.vol_fade_anim.setEasingCurve(QEasingCurve.InOutCubic)
        self.vol_fade_anim.finished.connect(self._on_vol_fade_finished)
        
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
        
        self.library_separator = QWidget()
        self.library_separator.setFixedHeight(10)
        self.sidebar_layout.addWidget(self.library_separator)

        self.settings_trigger_btn = QPushButton("SETTINGS")
        self.settings_trigger_btn.setObjectName("sidebar_settings_btn")
        self.sidebar_layout.addWidget(self.settings_trigger_btn)

        self.speed_trigger_btn = QPushButton("PLAYBACK")
        self.speed_trigger_btn.setObjectName("sidebar_speed_btn")
        self.sidebar_layout.addWidget(self.speed_trigger_btn)

        self.sleep_trigger_btn = QPushButton("SLEEP")
        self.sleep_trigger_btn.setObjectName("sidebar_sleep_btn")
        self.sidebar_layout.addWidget(self.sleep_trigger_btn)

        self.stats_trigger_btn = QPushButton("STATS")
        self.stats_trigger_btn.setObjectName("sidebar_stats_btn")
        self.sidebar_layout.addWidget(self.stats_trigger_btn)

        self.tags_trigger_btn = QPushButton("TAGS")
        self.tags_trigger_btn.setObjectName("sidebar_tags_btn")
        self.sidebar_layout.addWidget(self.tags_trigger_btn)

        self.sleep_cancel_btn = QPushButton("✕", self.sleep_trigger_btn)
        self.sleep_cancel_btn.setFixedSize(16, 16)
        self.sleep_cancel_btn.move(34, 1)
        self.sleep_cancel_btn.setStyleSheet("font-size: 10px; padding: 0;")
        self.sleep_cancel_btn.clicked.connect(self.sleep_panel.disable_sleep_timer)
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
        self.library_panel.set_hover_fade_enabled(self.config.get_hover_fade_mode())
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

        self._build_themes_tab()
        self._build_appearance_tab()
        self._build_library_tab()
        self._build_audio_tab()
        self._build_controls_tab()

        settings_layout.addWidget(self.tabs)
        self.settings_panel.hide()
        self.settings_panel_animation = QPropertyAnimation(self.settings_panel, b"pos")
        self.settings_panel_animation.setDuration(300)
        self.settings_panel_animation.setEasingCurve(QEasingCurve.OutCubic)

    def _build_themes_tab(self):
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
        self.theme_manager.cover_art_mode_widgets = {}
        for mode, label in [("off", "Off"), ("with_pool", "With pool"), ("exclusive", "Exclusive")]:
            btn = QPushButton(label)
            btn.setObjectName("pattern_button")
            btn.clicked.connect(lambda _, m=mode: self.theme_manager.set_cover_art_mode(m))
            self.theme_manager.cover_art_mode_widgets[mode] = btn
            cover_row.addWidget(btn)
        cover_row.addStretch()
        themes_layout.addLayout(cover_row)

        # Pool + controls container (hidden when Exclusive is active)
        self.theme_manager.pool_container = QWidget()
        pool_layout = QVBoxLayout(self.theme_manager.pool_container)
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
        cover_pool_btn.clicked.connect(lambda: self.theme_manager._on_cover_pool_btn_clicked())
        cover_pool_btn.rightClicked.connect(lambda: self.theme_manager._on_cover_pool_btn_right_clicked())
        cover_pool_btn.hovered.connect(lambda _: self.theme_manager._on_cover_pool_btn_hovered())
        self.theme_manager.cover_pool_btn = cover_pool_btn
        cover_pool_row.addWidget(cover_pool_btn)
        pool_layout.addLayout(cover_pool_row)
        self.theme_manager.theme_widgets = {}

        limit = max(230, self.settings_panel.width() - 20)
        for row_items in self.theme_manager.get_packed_themes(limit=limit):
            row_layout = QHBoxLayout()
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(0)

            for item in row_items:
                btn = ThemeItem(item['name'])
                btn.setMinimumWidth(item['width'])
                btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
                btn.clicked.connect(lambda _, n=item['name']: self.theme_manager.toggle_theme_selection(n))
                btn.rightClicked.connect(lambda n=item['name']: self.theme_manager._on_theme_right_clicked(n))
                btn.hovered.connect(self.theme_manager._on_theme_hovered)
                self.theme_manager.theme_widgets[item['name']] = btn
                row_layout.addWidget(btn, item['width'])

            if len(row_items) == 1:
                row_layout.addStretch()

            pool_layout.addLayout(row_layout)

        themes_tab.leaveEvent = lambda _: self.theme_manager._on_theme_unhovered()

        # Add/Remove All Buttons
        bulk_layout = QHBoxLayout()
        bulk_layout.setSpacing(10)
        self.add_all_btn = QPushButton("Add all")
        self.add_all_btn.setObjectName("theme_add_all")
        self.add_all_btn.setFixedWidth(80)
        self.remove_all_btn = QPushButton("Remove all")
        self.remove_all_btn.setObjectName("theme_remove_all")
        self.remove_all_btn.setFixedWidth(80)
        self.change_now_btn = QPushButton("Change now")
        self.change_now_btn.setObjectName("theme_change_now")

        self.add_all_btn.clicked.connect(self.theme_manager.select_all_themes)
        self.remove_all_btn.clicked.connect(self.theme_manager.deselect_all_themes)
        self.change_now_btn.clicked.connect(lambda: self.theme_manager._do_rotate(user_initiated=True))

        bulk_layout.addWidget(self.add_all_btn)
        bulk_layout.addWidget(self.remove_all_btn)
        bulk_layout.addWidget(self.change_now_btn)
        bulk_layout.addStretch()
        pool_layout.addLayout(bulk_layout)

        # Interval Selection
        interval_row = QHBoxLayout()
        interval_row.setSpacing(10)
        interval_row.setContentsMargins(0, 10, 0, 0)

        interval_label = QLabel("Interval (min)")
        interval_label.setObjectName("theme_hint")
        interval_row.addWidget(interval_label)

        intervals = [(2, "2"), (5, "5"), (10, "10"), (30, "30"), (60, "60"), (120, "120"), (0, "Off")]
        for mins, text in intervals:
            lbl = QLabel(text)
            lbl.setObjectName("theme_interval_label")
            lbl.setCursor(Qt.PointingHandCursor)
            lbl.mousePressEvent = lambda _, m=mins: self.theme_manager.set_rotation_interval(m)
            self.theme_manager.interval_widgets[mins] = lbl
            interval_row.addWidget(lbl)
        interval_row.addStretch()
        pool_layout.addLayout(interval_row)

        self.theme_manager.pool_container.leaveEvent = lambda _: self.theme_manager._on_theme_unhovered()
        themes_layout.addWidget(self.theme_manager.pool_container)
        themes_layout.addStretch()
        self.tabs.addTab(themes_tab, "Themes")
        self.theme_manager.update_theme_list_visuals()
        self.theme_manager.update_interval_visuals()
        self.theme_manager.update_cover_art_mode_visuals()

    def _build_appearance_tab(self):
        appearance_tab = QWidget()
        app_layout = QVBoxLayout(appearance_tab)
        app_layout.setContentsMargins(10, 0, 10, 10)

        fade_header = QLabel("Theme hover (ms)")
        fade_header.setObjectName("settings_header")
        app_layout.addWidget(fade_header)

        fade_row = QHBoxLayout()
        self.fade_buttons = {}
        for ms_val in [0, 500, 750, 1000, 1500]:
            label = "Off" if ms_val == 0 else str(ms_val)
            btn = QPushButton(label)
            btn.setObjectName("pattern_button")
            btn.clicked.connect(lambda _, v=ms_val: self.fade_mode_changed.emit(v))
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
            btn.clicked.connect(lambda _, s=state: self.blur_mode_changed.emit(s == "On"))
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
            btn.clicked.connect(lambda _, m=mode: self.scroll_mode_changed.emit(m))
            scroll_row.addWidget(btn)
            self.scroll_buttons[mode] = btn
        scroll_row.addStretch()
        app_layout.addLayout(scroll_row)

        hover_fade_header = QLabel("Library hover trail")
        hover_fade_header.setObjectName("settings_header")
        app_layout.addWidget(hover_fade_header)

        hover_fade_row = QHBoxLayout()
        self.hover_fade_buttons = {}
        for mode in ["Slow", "Normal", "Fast", "Off"]:
            btn = QPushButton(mode)
            btn.setObjectName("pattern_button")
            btn.clicked.connect(lambda _, m=mode: self.hover_fade_changed.emit(m))
            hover_fade_row.addWidget(btn)
            self.hover_fade_buttons[mode] = btn
        hover_fade_row.addStretch()
        app_layout.addLayout(hover_fade_row)

        hints_header = QLabel("Chapter hints")
        hints_header.setObjectName("settings_header")
        app_layout.addWidget(hints_header)

        hints_row = QHBoxLayout()
        self.hints_buttons = {}
        for mode in ["Sticky", "Transient", "Off"]:
            btn = QPushButton(mode)
            btn.setObjectName("pattern_button")
            btn.clicked.connect(lambda _, m=mode: self.hints_mode_changed.emit(m))
            hints_row.addWidget(btn)
            self.hints_buttons[mode] = btn
        hints_row.addStretch()
        app_layout.addLayout(hints_row)

        notches_header_row = QHBoxLayout()
        notches_label = QLabel("Chapter notches")
        notches_label.setObjectName("settings_header")
        notches_header_row.addWidget(notches_label)
        notches_header_row.addStretch()

        self.notches_anim_header_label = QLabel("Animation")
        self.notches_anim_header_label.setObjectName("settings_header")
        self.notches_anim_header_label.setVisible(False)
        notches_header_row.addWidget(self.notches_anim_header_label)
        app_layout.addLayout(notches_header_row)

        notches_row = QHBoxLayout()
        self.notches_buttons = {}
        for mode in ["On", "Off"]:
            btn = QPushButton(mode)
            btn.setObjectName("pattern_button")
            btn.clicked.connect(lambda _, m=mode: self.notches_mode_changed.emit(m == "On"))
            notches_row.addWidget(btn)
            self.notches_buttons[mode] = btn
        notches_row.addStretch()

        self.notch_animation_buttons = {}
        for mode in ["On", "Off"]:
            btn = QPushButton(mode)
            btn.setObjectName("pattern_button")
            btn.setVisible(False)
            btn.clicked.connect(lambda _, m=mode: self.notch_animation_mode_changed.emit(m == "On"))
            notches_row.addWidget(btn)
            self.notch_animation_buttons[mode] = btn

        app_layout.addLayout(notches_row)

        app_layout.addStretch()
        self.tabs.addTab(appearance_tab, "Look")
        # Visual initialization moved to after SettingsController binding

    def _build_library_tab(self):
        library_tab = QWidget()
        lib_layout = QVBoxLayout(library_tab)
        lib_layout.setContentsMargins(10, 0, 10, 10)
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

        self.at_pattern_btn.clicked.connect(lambda: self.naming_pattern_changed.emit("Author - Title"))
        self.ta_pattern_btn.clicked.connect(lambda: self.naming_pattern_changed.emit("Title - Author"))

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
        self.add_folder_btn.setObjectName("library_add_folder_btn")
        self.remove_folder_btn = QPushButton("Remove")
        self.remove_folder_btn.setObjectName("library_remove_folder_btn")
        self.refresh_library_btn = QPushButton("Rescan")
        self.refresh_library_btn.setObjectName("library_rescan_btn")
        folder_btns_layout.addWidget(self.add_folder_btn)
        folder_btns_layout.addWidget(self.remove_folder_btn)
        folder_btns_layout.addWidget(self.refresh_library_btn)
        lib_layout.addLayout(folder_btns_layout)
        lib_layout.addSpacing(10)

        chap_source_header = QLabel("Chapter source")
        chap_source_header.setObjectName("settings_header")
        lib_layout.addWidget(chap_source_header)

        chap_source_row = QHBoxLayout()
        self.chapter_source_buttons = {}
        for source, label in [("embedded", "Embedded"), ("cue", ".cue")]:
            btn = QPushButton(label)
            btn.setObjectName("pattern_button")
            btn.clicked.connect(lambda _, s=source: self.chapter_list_source_changed.emit(s))
            chap_source_row.addWidget(btn)
            self.chapter_source_buttons[source] = btn
        chap_source_row.addStretch()
        lib_layout.addLayout(chap_source_row)

        lib_layout.addSpacing(10)

        persist_header = QLabel("Persist search filter")
        persist_header.setObjectName("settings_header")
        lib_layout.addWidget(persist_header)

        persist_row = QHBoxLayout()
        self.persist_filter_buttons = {}
        for val, label in [(False, "Off"), (True, "On")]:
            btn = QPushButton(label)
            btn.setObjectName("pattern_button")
            btn.clicked.connect(lambda _, v=val: self._on_persist_filter_master(v))
            persist_row.addWidget(btn)
            self.persist_filter_buttons[val] = btn
        persist_row.addStretch()

        if self.config.get_persist_filter_enabled() and not any([
            self.config.get_persist_filter_tag(),
            self.config.get_persist_filter_text(),
            self.config.get_persist_filter_year(),
        ]):
            self.config.set_persist_filter_enabled(False)
        _master_on = self.config.get_persist_filter_enabled()
        self.persist_filter_sub_buttons = {}
        for key, label in [("tag", "Tag"), ("text", "Text"), ("year", "Year")]:
            btn = QPushButton(label)
            btn.setObjectName("pattern_button")
            btn.setVisible(_master_on)
            btn.clicked.connect(lambda _, k=key: self._on_persist_filter_sub(k))
            persist_row.addWidget(btn)
            self.persist_filter_sub_buttons[key] = btn
        lib_layout.addLayout(persist_row)

        # Library controller connections are consolidated in __init__
        lib_layout.addStretch()
        self.tabs.addTab(library_tab, "Library")
        self._update_pattern_visuals()
        self._update_persist_filter_visuals()

    def _build_audio_tab(self):
        self.audio_tab = AudioSettingsTab(self.player, self.config, self)
        self.tabs.addTab(self.audio_tab, "Audio")

    def _build_controls_tab(self):
        # TAB 4: SHORTCUTS
        shortcuts_tab = QWidget()
        short_layout = QVBoxLayout(shortcuts_tab)
        short_layout.setContentsMargins(10, 0, 10, 10)
        short_layout.setSpacing(6)

        digit_header = QLabel("Chapter number keys")
        digit_header.setObjectName("settings_header")
        short_layout.addWidget(digit_header)

        digit_row = QHBoxLayout()
        self.digit_mode_buttons = {}
        for mode, label in [("by_name", "By name"), ("by_index", "By index")]:
            btn = QPushButton(label)
            btn.setObjectName("pattern_button")
            btn.clicked.connect(lambda _, m=mode: self.chapter_digit_mode_changed.emit(m))
            digit_row.addWidget(btn)
            self.digit_mode_buttons[mode] = btn
        digit_row.addStretch()
        self.digit_autoplay_buttons = {}
        for val, label in [(True, "Auto-play"), (False, "Jump only")]:
            btn = QPushButton(label)
            btn.setObjectName("pattern_button")
            btn.clicked.connect(lambda _, v=val: self.chapter_digit_autoplay_changed.emit(v))
            digit_row.addWidget(btn)
            self.digit_autoplay_buttons[val] = btn
        short_layout.addLayout(digit_row)
        short_layout.addStretch()
        self.tabs.addTab(shortcuts_tab, "Controls")

    def _build_stats_panel(self):
        self.stats_panel = StatsPanel(self.db, self.config, parent=self)
        self.theme_manager.theme_applied.connect(self.stats_panel.on_theme_changed)
        self.stats_panel.on_theme_changed(self.theme_manager.get_current_theme())
        self.stats_panel.hide()
        self.stats_panel_animation = QPropertyAnimation(self.stats_panel, b"pos")
        self.stats_panel_animation.setDuration(300)
        self.stats_panel_animation.setEasingCurve(QEasingCurve.OutCubic)

    def _build_tags_panel(self):
        _assets_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "assets"))
        self.tags_panel = TagManagerWidget(self.db, _assets_dir, parent=self)
        self.tags_panel.hide()
        self.tags_panel_animation = QPropertyAnimation(self.tags_panel, b"pos")
        self.tags_panel_animation.setDuration(200)
        self.tags_panel_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.theme_manager.theme_applied.connect(self.tags_panel.on_theme_changed)
        self.tags_panel.on_theme_changed(self.theme_manager.get_current_theme())

    def _build_book_detail_panel(self):
        self.book_detail_panel = BookDetailPanel(self.db, self.config, parent=self)
        self.book_detail_panel.hide()
        self.book_detail_panel_animation = QPropertyAnimation(
            self.book_detail_panel, b"pos"
        )
        self.book_detail_panel_animation.setDuration(300)
        self.book_detail_panel_animation.setEasingCurve(QEasingCurve.OutCubic)
        self.panel_manager.book_detail_panel = self.book_detail_panel
        self.panel_manager.book_detail_panel_animation = self.book_detail_panel_animation
        self.book_detail_panel.close_requested.connect(
            self.panel_manager._close_book_detail_flow
        )
        self.book_detail_panel.history_deleted.connect(self.stats_panel.refresh_all)
        self.book_detail_panel.metadata_saved.connect(self._on_book_metadata_saved)
        self.book_detail_panel.tags_changed.connect(self._on_book_tags_changed)
        self.tags_panel.tag_changed.connect(self.stats_panel._on_tag_changed)
        self.tags_panel.detail_requested.connect(
            lambda path: self.panel_manager.open_book_detail({"path": path}, tab="stats", context='tags')
        )
        self.book_detail_panel.active_cover_changed.connect(self._on_active_cover_changed)
        self.book_detail_panel.active_cover_changed.connect(
            lambda book_path, cover_path: self.stats_panel.on_cover_changed(book_path, cover_path)
        )
        self.book_detail_panel.book_removed.connect(self._on_book_detail_removed)
        self.book_detail_panel.tag_filter_requested.connect(self._on_tag_filter_requested)
        self.book_detail_panel.open_tag_manager_requested.connect(self._on_open_tag_manager_from_detail)
        self.theme_manager.theme_applied.connect(self.book_detail_panel.on_theme_changed)
        self.book_detail_panel.on_theme_changed(self.theme_manager.get_current_theme())

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

    def _sync_persist_filter_on_open(self):
        if not hasattr(self, 'persist_filter_sub_buttons'):
            return
        if self.config.get_persist_filter_enabled() and not any([
            self.config.get_persist_filter_tag(),
            self.config.get_persist_filter_text(),
            self.config.get_persist_filter_year(),
        ]):
            self.config.set_persist_filter_enabled(False)
        enabled = self.config.get_persist_filter_enabled()
        for btn in self.persist_filter_sub_buttons.values():
            btn.setVisible(enabled)
        self._update_persist_filter_visuals()

    def _on_persist_filter_master(self, enabled: bool):
        if enabled:
            # If all three sub-keys are False, reset them all to True before enabling
            if not any([
                self.config.get_persist_filter_tag(),
                self.config.get_persist_filter_text(),
                self.config.get_persist_filter_year(),
            ]):
                self.config.set_persist_filter_tag(True)
                self.config.set_persist_filter_text(True)
                self.config.set_persist_filter_year(True)
        self.config.set_persist_filter_enabled(enabled)
        for btn in self.persist_filter_sub_buttons.values():
            btn.setVisible(enabled)
        self._update_persist_filter_visuals()

    def _on_persist_filter_sub(self, key: str):
        getters = {"tag": self.config.get_persist_filter_tag,
                   "text": self.config.get_persist_filter_text,
                   "year": self.config.get_persist_filter_year}
        setters = {"tag": self.config.set_persist_filter_tag,
                   "text": self.config.set_persist_filter_text,
                   "year": self.config.set_persist_filter_year}
        setters[key](not getters[key]())
        self._update_persist_filter_visuals()

    def _update_persist_filter_visuals(self):
        if not hasattr(self, 'persist_filter_buttons'): return
        enabled = self.config.get_persist_filter_enabled()
        for val, btn in self.persist_filter_buttons.items():
            btn.setProperty("selected", "true" if bool(val) == enabled else "false")
            btn.style().unpolish(btn); btn.style().polish(btn)
        sub_states = {
            "tag": self.config.get_persist_filter_tag(),
            "text": self.config.get_persist_filter_text(),
            "year": self.config.get_persist_filter_year(),
        }
        for key, btn in self.persist_filter_sub_buttons.items():
            btn.setProperty("selected", "true" if sub_states[key] else "false")
            btn.style().unpolish(btn); btn.style().polish(btn)

    def _on_sleep_timer_started(self):
        self.sleep_trigger_btn.setText("SLEEP")
        self.sleep_cancel_btn.show()
        self.sleep_pulse_anim.start()
        if self.current_file:
            if not self.session_recorder.is_active:
                self.session_recorder.open()
            else:
                self.session_recorder.resume()

    def _on_sleep_timer_stopped(self):
        self.sleep_trigger_btn.setText("SLEEP")
        self.sleep_cancel_btn.hide()
        self.sleep_pulse_anim.stop()
        self.sleep_opacity_effect.setOpacity(1.0)
        self.player.set_fade_ratio(1.0)

    def _on_sleep_timer_expired(self):
        """Called only when the sleep timer fires and pauses playback (not user-cancelled)."""
        self._last_pause_timestamp = time.time()
        self._save_current_progress()
        self.library_panel.set_is_playing(False)
        if self.session_recorder.is_active:
            self.session_recorder.pause()
    def _update_chapter_title_text(self, text):
        """Update the scrolling label text."""
        self.current_chapter_label.setText(text)

    def _on_book_detail_removed(self) -> None:
        path = self.book_detail_panel._book_path
        self.panel_manager._close_book_detail_flow()
        self.library_panel.refresh(force=True)
        self.tags_panel.refresh_books()
        self.stats_panel.refresh_current_tab()
        if path == self.current_file:
            self._on_book_removed()

    def _on_book_removed(self):
        """Helper for controller when the currently playing folder is removed from library."""
        self.current_file = ""
        self._current_book = None
        self.session_recorder.close()
        if self.player:
            self.player.terminate()
        self.progress_slider.set_markers([])
        self._load_cover_art("")
        self.library_panel.set_playing_path("")
        self.library_panel.set_is_playing(False)
        self.config.set_last_book("")
        # Reconcile chrome now that the book is gone — without this, callers that
        # don't independently re-run the gate (e.g. the book-detail trash button)
        # leave stale player chrome visible.
        self.library_controller.apply_current_state()

    def get_current_file(self):
        """Return the currently loaded file path."""
        return self.current_file

    def _update_folder_list_widget(self, paths):
        self.folder_list_widget.clear()
        for loc in paths:
            self.folder_list_widget.addItem(loc)

    def _get_selected_folder_path(self):
        item = self.folder_list_widget.currentItem()
        return item.text() if item else None

    def _get_new_folder_path(self):
        return QFileDialog.getExistingDirectory(None, "Select Library Folder")

    def _update_status_banner_ui(self, text=None, show_banner=None, show_cancel=None, auto_hide=False):
        if text is not None and (self.status_banner.isVisible() or show_banner):
            self.status_label.setText(text)
            fade = getattr(self.theme_manager, '_fade_overlay', None)
            if self.status_banner.isVisible() and not (fade and fade.isVisible()):
                self.status_banner.raise_()

        if show_banner is True:
            self.status_banner.show()
            fade = getattr(self.theme_manager, '_fade_overlay', None)
            if not (fade and fade.isVisible()):
                self.status_banner.raise_()
        elif show_banner is False: self.status_banner.hide()

        if show_cancel is True: self.cancel_scan_btn.show()
        elif show_cancel is False: self.cancel_scan_btn.hide()

        if auto_hide:
            QTimer.singleShot(3000, self.status_banner.hide)

    def _on_book_metadata_saved(self, book_id: int, title: str, author: str, narrator: str, year: object):
        self.library_panel._book_model.update_book_metadata(book_id, title, author, narrator, year)
        if self.stats_panel.isVisible():
            self.stats_panel.refresh_all()

    def _on_session_written(self):
        if self.stats_panel.isVisible():
            self.stats_panel.refresh_current_tab()

    def _update_metadata_ui(self, text=None, show_metadata=None, show_go_to_lib=None):
        if text is not None:
            self.metadata_label.setStyleSheet("font-weight: bold; font-size: 16px;")
            self.metadata_label.setText(text)
        if show_metadata is True: self.metadata_label.show()
        elif show_metadata is False: self.metadata_label.hide()
        if show_go_to_lib is True: self.no_book_section.show()
        elif show_go_to_lib is False: self.no_book_section.hide()

    def _update_idle_prompts_ui(self, visible):
        # Scan section (prompt + button + info) only shows in the empty state.
        self.scan_section.setVisible(visible)

    def _build_carousel_covers(self):
        """Build (pixmaps, cover_h) for the no-book carousel from cached covers.
        Returns (None, 0) when there are too few covers to bother."""
        import random
        from PIL import Image

        cover_paths = self.db.get_all_cover_paths()
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
            pm = pm.scaled(92, cover_h, Qt.KeepAspectRatioByExpanding,
                           Qt.SmoothTransformation)
            if pm.width() > 92 or pm.height() > cover_h:
                x_off = (pm.width() - 92) // 2
                y_off = (pm.height() - cover_h) // 2
                pm = pm.copy(x_off, y_off, 92, cover_h)
            pixmaps.append(pm)

        if not pixmaps:
            return None, 0
        return pixmaps, cover_h

    def _show_carousel(self):
        """Build and place the carousel synchronously. Safe to call multiple times."""
        if self._carousel is not None:
            return   # already showing — do not reshuffle mid-display
        if self.current_file or not self.no_book_section.isVisible():
            return   # not in the no-book state
        pixmaps, cover_h = self._build_carousel_covers()
        if not pixmaps:
            return
        self._carousel = CoverCarousel(pixmaps, cover_h)
        self.carousel_holder.layout().addWidget(self._carousel)

    def _hide_carousel(self):
        """Stop and remove the carousel from its holder."""
        if self._carousel is not None:
            self._carousel.stop()
            self.carousel_holder.layout().removeWidget(self._carousel)
            self._carousel.setParent(None)
            self._carousel.deleteLater()
            self._carousel = None

    def _update_quote_ui(self, rich_text=None, show_quote=None):
        if rich_text is not None:
            self.quote_label.setText(rich_text)
        # The fixed-height quote section is only visible in the empty state.
        if show_quote is True: self.quote_section.show()
        elif show_quote is False: self.quote_section.hide()

    def _set_quote_rotation(self, enabled):
        """Starts or stops the 60s quote rotation timer."""
        if enabled:
            if not self.quote_timer.isActive():
                self.quote_timer.start(60000)
        else:
            self.quote_timer.stop()

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
        # Transport controls are inert without a book — hide the whole row.
        self.transport_controls.setVisible(visible)
        # Suppress the overall-progress fill (keep the bg groove so no layout shift).
        self.progress_slider._suppress_fill = not visible
        self.progress_slider.setEnabled(visible)
        self.progress_slider.update()
        # Sleep and Playback panels have no function without an active book.
        self.sleep_trigger_btn.setVisible(visible)
        self.speed_trigger_btn.setVisible(visible)

    def _set_scan_buttons_enabled(self, enabled):
        """Enable/disable the Library panel's folder-management buttons.
        Disabled (but still visible) while a scan is in progress."""
        self.add_folder_btn.setEnabled(enabled)
        self.remove_folder_btn.setEnabled(enabled)
        self.refresh_library_btn.setEnabled(enabled)

    def _set_chapter_ui_active(self, active):
        """Make chapter widgets interactive and visible, or ghosted (transparent, no interaction).
        Layout is never affected — widgets stay in place regardless of active state."""
        self._chapter_ui_active = active
        slider = self.chapter_progress_slider
        if active:
            slider.bg_color = QColor("transparent")  # will be overridden by QSS repolish
            slider.fill_color = QColor("transparent")
            slider.style().unpolish(slider)
            slider.style().polish(slider)
            slider.update()
            slider.setAttribute(Qt.WA_TransparentForMouseEvents, False)
            slider.setCursor(Qt.PointingHandCursor)
            self.chap_duration_label.setCursor(Qt.PointingHandCursor)
            for lbl in (self.current_chapter_label, self.chap_elapsed_label,
                        self.chap_duration_label):
                lbl.setStyleSheet("")
        else:
            slider.bg_color = QColor("transparent")
            slider.fill_color = QColor("transparent")
            slider.update()
            slider.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            for lbl in (self.current_chapter_label, self.chap_elapsed_label,
                        self.chap_duration_label):
                lbl.setStyleSheet("color: transparent;")
            self.current_chapter_label.setCursor(Qt.ArrowCursor)
            self.chap_duration_label.setCursor(Qt.ArrowCursor)
            self._chapter_label_clickable = False

    def _save_current_progress(self):
        """Saves the current playback position to both DB and Config."""
        if self.current_file and self.player.is_initialized:
            pos = self.player.time_pos
            if pos is not None:
                self.db.update_progress(self.current_file, pos)
                self.config.set_last_position(self.current_file, pos)

    def _get_current_position(self) -> float:
        try:
            return self.player.time_pos or 0.0
        except (ShutdownError, AttributeError, SystemError):
            return 0.0

    def _on_open_tag_manager_from_detail(self) -> None:
        self.panel_manager.hide_all_panels()
        QTimer.singleShot(320, self.panel_manager._open_tags_flow)

    def _on_book_tags_changed(self) -> None:
        self.stats_panel._on_tag_changed()
        search = self.library_panel.search_field.text().strip()
        if search.startswith("#"):
            self.library_panel.refresh()
        self.tags_panel.refresh_books()

    def _on_tag_filter_requested(self, tag: str) -> None:
        self.panel_manager._close_book_detail_flow()
        self.panel_manager._open_library_flow()
        self.library_panel.set_search(f"#{tag}")

    def _on_library_detail_requested(self, path: str) -> None:
        self.panel_manager.open_book_detail({"path": path}, tab="stats", context='library')

    def _on_book_selected_from_library(self, path):
        """Loads a book and closes the library panel."""
        if path == self.current_file:
            self.panel_manager.hide_all_panels()
            return

        self._save_current_progress()
        self._paused_time = None
        self._mpv_ready = False
        self._pre_switch_slider_value = self.progress_slider.value()
        self._pre_switch_chap_slider_value = self.chapter_progress_slider.value()
        self.current_chapter_label.setText("")
        self.progress_slider.set_markers([])
        self.chapter_list_widget.clear()
        self._last_saved_pct = -1
        self._eof_dur_fetched = False
        self.current_file = path
        self.session_recorder.close()
        self.panel_manager.hide_all_panels()
        QTimer.singleShot(0, lambda: (
            self.db.update_last_played(path),
            self.config.set_last_book(path),
            self.library_panel.set_playing_path(path),
            self.library_panel.set_is_playing(False),
            self._load_cover_art(path),
            self.player.load_book(path),
            # Re-run the chrome gate now that current_file is set: with has_book=True,
            # apply_library_state reveals the player chrome and hides no_book_section.
            # apply_current_state is the compute-and-apply half of _check_library_status,
            # split out so the selection path drives the gate without triggering a scan.
            self.library_controller.apply_current_state(),
        ))

    def _on_vt_file_switched(self):
        """Lightweight handler for VT file switches. Does not restore position."""
        self.player.is_seeking = False

    def _on_file_ready(self):
        """Called when mpv confirms the file is loaded and ready."""
        if getattr(self.library_panel, '_is_animating', False):
            self._file_ready_deferred = True
            return
        self._file_ready_deferred = False
        if not os.path.exists(self.current_file):
            self._update_status_banner_ui(text="Error: File missing!", show_banner=True, auto_hide=True)
            return
        self._eof_event_written = False # Temporary
        self._current_book = self.db.get_book(self.current_file)

        self._restore_position()
        self._update_ui_sync()

        book_data = self._current_book
        new_progress = book_data.progress if book_data else 0
        pre = getattr(self, '_pre_switch_slider_value', None)
        if pre is not None:
            self._pre_switch_slider_value = None
            dur = self.player.duration
            if new_progress == 0 or not dur:
                new_val = 0
            else:
                new_val = int((new_progress / dur) * 1000)
            if pre != new_val:
                self.progress_slider.animate_to(new_val, old_value=pre)
            else:
                self.progress_slider.setValue(new_val)

    def _on_file_loaded_populate_chapters(self):
        if getattr(self.library_panel, '_is_animating', False):
            self._chaps_deferred = True
            return
        self._chaps_deferred = False
        try:
            dur = self.player.duration
            if dur and self.player.chapter_list:
                self.chapter_list_widget.populate(dur, self.player.speed or 1.0)
                self._refresh_notches()
                self._set_chapter_ui_active(True)
            else:
                self.chapter_list_widget.clear()
                self.progress_slider.set_markers([])
                self._set_chapter_ui_active(False)
                self._prev_chap_title = ""
                self._next_chap_title = ""
                self._clear_preview()
            self._update_chapter_label_clickability()
        except (ShutdownError, AttributeError, SystemError):
            return
        pre_chap = getattr(self, '_pre_switch_chap_slider_value', None)
        if pre_chap is not None:
            self._pre_switch_chap_slider_value = None
            book_data = getattr(self, '_current_book', None)
            new_progress = book_data.progress if book_data else 0
            new_chap_val = 0 if new_progress == 0 else self.chapter_progress_slider.value()
            if pre_chap != new_chap_val:
                self.chapter_progress_slider.animate_to(new_chap_val, old_value=pre_chap)
            else:
                self.chapter_progress_slider.setValue(new_chap_val)

    def _drain_deferred_file_ready(self):
        if getattr(self, '_file_ready_deferred', False):
            self._on_file_ready()
        if getattr(self, '_chaps_deferred', False):
            self._on_file_loaded_populate_chapters()
        self._apply_pending_cover_theme()

    def _apply_pending_cover_theme(self):
        pixmap = getattr(self, '_pending_cover_pixmap', None)
        if not pixmap:
            return
        self._pending_cover_pixmap = None
        if hasattr(self.progress_slider, 'when_animations_done'):
            self.progress_slider.when_animations_done(
                lambda: self.theme_manager.apply_cover_theme(pixmap)
            )
        else:
            self.theme_manager.apply_cover_theme(pixmap)

    def _on_load_failed(self, reason):
        """Called when mpv fires end-file with a non-normal reason (error/unknown)."""
        self._update_status_banner_ui(text=f"Failed to load: {reason}", show_banner=True, auto_hide=True)

    def _update_chapter_label_clickability(self):
        """Enable the chapter label as a clickable link only when there are 2+ chapters."""
        chaps = self.player.chapter_list or [] if self.player else []
        clickable = len(chaps) >= 2
        self.current_chapter_label.setCursor(
            Qt.PointingHandCursor if clickable else Qt.ArrowCursor
        )
        self._chapter_label_clickable = clickable

    def _refresh_notches(self, skip_animation=False):
        """Updates the progress bar with chapter markers if enabled in settings."""
        if not self.current_file or not self.player or not self.player.chapter_list:
            self.progress_slider.set_markers([])
            return

        self.progress_slider.animationsEnabled = self.config.get_chapter_notch_animation_enabled()

        if self.config.get_chapter_notches_enabled():
            dur = self.player.duration
            if dur:
                ratios = [c.get('time', 0) / dur for c in self.player.chapter_list]
                self.progress_slider.set_markers(ratios, skip_animation=skip_animation)
        else:
            self.progress_slider.set_markers([])

    def _restore_position(self):
        QTimer.singleShot(0, lambda: self.player.set_volume_from_slider(self.volume_slider.value()))
        config_pos = self.config.get_last_position(self.current_file)
        if config_pos > 0:
            self.db.update_progress(self.current_file, config_pos)
        book_data = self.db.get_book(self.current_file)
        if book_data and book_data.progress > 0:
            self.player.is_seeking = True
            if self.player._virtual_timeline is not None:
                self.player.seek_async(book_data.progress)
            else:
                self.player.seek_async(book_data.progress + _CHAPTER_BOUNDARY_EPSILON)
        saved_speed = self.config.get_book_speed(self.current_file)
        speed = saved_speed if saved_speed is not None else self.config.get_default_speed()
        self._set_speed(speed, save=False)
        if self.audio_tab:
            self.audio_tab.sync_player()

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
        if not getattr(self, '_chapter_label_clickable', False):
            return

        if self.chapter_list_widget.isVisible():
            self.chapter_list_widget.fade_out()
            return

        self.panel_manager.hide_all_panels()

        speed = self.player.speed or 1.0
        # Pass window width so elide widths are correct before the widget is shown
        self.chapter_list_widget.populate(self.player.duration or 0, speed, self.width())

        if self.chapter_list_widget.count() == 0:
            return

        pos = self.player.time_pos or 0
        chapters = self.player.chapter_list or []
        active_idx = 0
        for i, ch in enumerate(chapters):
            if ch.get('time', 0) <= pos + 0.35:
                active_idx = i
        self.chapter_list_widget.show_above(self.current_chapter_label, self)

        # Apply selection and scroll after the widget is shown and laid out
        self.chapter_list_widget.setCurrentRow(active_idx)
        QTimer.singleShot(0, lambda: self.chapter_list_widget.scroll_to_active(active_idx))

    def _update_ui_sync(self):
        try:
            # Guard against accessing player before a file is loaded
            mpv_pos = self.player.time_pos if self.current_file else None
            dur = self.player.duration if self.current_file else None
            is_paused = (self.player.pause if self.current_file else True) and not self.player._is_vt_file_switch
            speed = self.player.speed or 1.0

            current_time = time.time()
            self.session_recorder.update_furthest_position(mpv_pos)
            is_eof = self.player.eof_reached

            # Handle the early return carefully:
            # If we are at EOF, we want to continue to update the UI even if pos is None.
            if not self.current_file:
                self._set_play_icon("play")
                return

            if is_eof and dur is None:
                if not self._eof_dur_fetched:
                    book = self.db.get_book(self.current_file)
                    dur = book.duration if book and book.duration else 0.0
                    self._eof_dur_fetched = True

            # If we aren't at EOF and don't have a position, we can't update —
            # unless we're paused and have a cached position from before the seek.
            if not is_eof and mpv_pos is None:
                if is_paused and self._paused_time is not None:
                    pass  # fall through using _paused_time below
                else:
                    self._set_play_icon("play")
                    return
            if dur is None or dur <= 0:
                self._set_play_icon("play")
                return

            # Logic for synthesized state at EOF vs normal playback
            if is_eof:
                pos = dur
                self._set_play_icon("restart")
                if not self._eof_event_written and self._current_book is not None:
                    self.db.write_book_event(self._current_book.path, 'finished', book_id=self._current_book.id)      #Temporary
                    self._eof_event_written = True
                    self.session_recorder.close()
                    if hasattr(self, 'stats_panel') and self.stats_panel.isVisible():
                        self.stats_panel.refresh_all()
                    self.stats_panel.refresh_overall()
                self._paused_time = None
                self.progress_slider.setValue(1000)
                self.current_time_label.setText(self.player.format_time(pos / speed))
                if self.show_remaining_time:
                    self.total_time_label.setText("-00:00:00")
                    self.chap_duration_label.setText("-00:00:00")
                else:
                    self.total_time_label.setText(self.player.format_time(dur / speed))
                return
            else:
                if is_paused:
                    if mpv_pos is not None and getattr(self, '_mpv_ready', True):
                        if self._paused_time is None or self.player.is_seeking or abs(mpv_pos - self._paused_time) > 1.0:
                            self._paused_time = mpv_pos
                    # if mpv_pos is None or mpv not yet ready, keep _paused_time as-is
                    pos = self._paused_time
                    if pos is None:
                        self._set_play_icon("play")
                        return
                else:
                    self._paused_time = None
                    pos = mpv_pos
                self._set_play_icon("play" if is_paused else "pause")

            # Delegate into focused helpers to reduce cognitive complexity
            self._sync_playback_state(current_time, pos, dur)
            self._sync_ui_render()
            self._sync_progress_sliders(pos, dur, speed)
            self._sync_chapter_ui(pos, dur, speed)
            self._sync_persistence(pos, dur)
        except (ShutdownError, AttributeError, SystemError):
            return

    def _sync_playback_state(self, current_time, pos, dur):
        # Delegate Sleep Timer Logic
        self.sleep_panel.update_timer_state(current_time, self.player.pause if self.current_file else True, pos, dur, self.player.eof_reached)

        if self.current_chapter_label.text() == "Select Chapter" and self.player.chapter_list:
            chap_list = self.player.chapter_list
            pos = self.player.time_pos
            if pos is not None:
                curr_chap = 0
                for i, chap in enumerate(chap_list):
                    if chap.get('time', 0) <= pos + _CHAPTER_BOUNDARY_EPSILON:
                        curr_chap = i
                self._update_chapter_label_from_index(curr_chap)

    def _set_play_icon(self, state):
        """Set play_pause_button icon. state: 'play', 'pause', or 'restart'."""
        if self.player.mp3_seek_visual_lock:
            return
        icons = {"play": self._icon_play, "pause": self._icon_pause, "restart": self._icon_restart}
        fallback = {"play": "Play", "pause": "Pause", "restart": "Restart"}
        icon = icons[state]
        if icon.isNull():
            self.play_pause_button.setIcon(QIcon())
            self.play_pause_button.setText(fallback[state])
        else:
            self.play_pause_button.setText("")
            self.play_pause_button.setIcon(icon)

    def _update_skip_icons(self):
        skip = self.config.get_skip_duration()
        rwd = self._icon_rewind.get(skip, self._icon_rewind[10])
        fwd = self._icon_forward.get(skip, self._icon_forward[10])
        if rwd.isNull():
            self.rewind_button.setIcon(QIcon())
            self.rewind_button.setText("<<")
        else:
            self.rewind_button.setText("")
            self.rewind_button.setIcon(rwd)
        if fwd.isNull():
            self.forward_button.setIcon(QIcon())
            self.forward_button.setText(">>")
        else:
            self.forward_button.setText("")
            self.forward_button.setIcon(fwd)

    def _reload_button_icons(self, theme_name):
        if not hasattr(self, 'play_pause_button'):
            return
        t = _resolve_theme(theme_name)
        play_color    = t.get('button_play',    t.get('button_text', t.get('text_on_light_bg', t['text'])))
        skip_color    = t.get('button_skip',    play_color)
        chapter_color = t.get('button_chapter', play_color)
        self._icon_play    = _load_svg_icon("play.svg",       play_color)
        self._icon_pause   = _load_svg_icon("pause.svg",      play_color)
        self._icon_restart = _load_svg_icon("restart.svg",    play_color)
        self._icon_rewind  = {5: _load_svg_icon("rewind_5.svg",   skip_color), 10: _load_svg_icon("rewind_10.svg",  skip_color), 30: _load_svg_icon("rewind_30.svg",  skip_color)}
        self._icon_forward = {5: _load_svg_icon("forward_5.svg",  skip_color), 10: _load_svg_icon("forward_10.svg", skip_color), 30: _load_svg_icon("forward_30.svg", skip_color)}
        _prev = _load_svg_icon("previous.svg", chapter_color)
        if _prev.isNull():
            self.prev_button.setText("|<")
        else:
            self.prev_button.setText("")
            self.prev_button.setIcon(_prev)
        _next = _load_svg_icon("next.svg", chapter_color)
        if _next.isNull():
            self.next_button.setText(">|")
        else:
            self.next_button.setText("")
            self.next_button.setIcon(_next)
        self._update_skip_icons()
        # Refresh whichever play/pause/restart icon is currently showing
        if self.current_file and self.player.eof_reached:
            self._set_play_icon("restart")
        elif self.current_file and not self.player.pause:
            self._set_play_icon("pause")
        else:
            self._set_play_icon("play")

    def _sync_ui_render(self):
        is_eof = self.player.eof_reached
        if is_eof and self.current_file:
            self._set_play_icon("restart")
        else:
            self._set_play_icon("pause" if not self.player.pause else "play")

    def _sync_progress_sliders(self, pos, dur, speed):
        if dur is not None and dur > 0:
            # Guard: skip setValue while flow animation is running so the timer
            # doesn't fight the animation. Preserve this check on any refactor.
            slider_animating = (hasattr(self.progress_slider, '_flow_anim')
                                and self.progress_slider._flow_anim.state()
                                == QPropertyAnimation.State.Running)
            if not self.is_slider_dragging:
                percent = (pos / dur) * 100
                if not slider_animating and not self.player.is_seeking:
                    self.progress_slider.setValue(int((pos / dur) * 1000))
                self.current_time_label.setText(self.player.format_time(pos / speed))
                if self.show_remaining_time:
                    remaining = (dur - pos) / speed
                    self.total_time_label.setText(f"-{self.player.format_time(remaining)}")
                else:
                    self.total_time_label.setText(self.player.format_time(dur / speed))
                self.progress_percentage_label.setText(f"{percent:.1f}%")

    def _sync_chapter_ui(self, pos, dur, speed):
        if self.player and self.player.mp3_seek_reload_pending:
            return
        chap_list = self.player.chapter_list or []
        if not chap_list:
            return
        # Always derive chapter from pos so the UI stays consistent regardless
        # of when mpv's internal chapter property settles after a seek.
        curr_chap = 0
        for i, chap in enumerate(chap_list):
            if chap.get('time', 0) <= pos + _CHAPTER_BOUNDARY_EPSILON:
                curr_chap = i
        if curr_chap < len(chap_list):
            # Update chapter progress
            start = chap_list[curr_chap].get('time', 0)
            end = chap_list[curr_chap+1].get('time', dur) if curr_chap + 1 < len(chap_list) else dur
            chap_dur = end - start
            # Guard: skip setValue while flow animation is running so the timer
            # doesn't fight the animation. Preserve this check on any refactor.
            chap_animating = (hasattr(self.chapter_progress_slider, '_flow_anim')
                              and self.chapter_progress_slider._flow_anim.state()
                              == QPropertyAnimation.State.Running)
            if not self.is_chapter_slider_dragging:
                c_elapsed = max(0, pos - start)
                self.chap_elapsed_label.setText(self.player.format_time(c_elapsed / speed))
                if self.show_remaining_time:
                    c_remaining = max(0, end - pos) / speed
                    self.chap_duration_label.setText(f"-{self.player.format_time(c_remaining)}")
                else:
                    self.chap_duration_label.setText(self.player.format_time((end - start) / speed))
                # No is_seeking gate here — chapter nav uses self.chapter = N
                # which never sets _seek_target, so _is_seeking clears on the
                # first time_pos callback regardless of whether the seek is done.
                # Gating on is_seeking caused the slider to retain stale values
                # while the time label (ungated) showed 00:00. The slider
                # self-corrects within one 200ms tick; that is acceptable.
                # The chap_animating guard (book-switch flow animation) must stay.
                if chap_dur > 0 and not chap_animating:
                    self.chapter_progress_slider.setValue(int((c_elapsed / chap_dur) * 1000))

    def _sync_persistence(self, pos, dur):
        if dur is not None and dur > 0:
            if not self.is_slider_dragging and getattr(self, '_mpv_ready', True):
                percent = (pos / dur) * 100
                # Update config every 0.1% (live cache)
                new_pct = int(percent * 10)
                if new_pct != self._last_saved_pct:
                    self._last_saved_pct = new_pct
                    self.config.set_last_position(self.current_file, pos)
                    if self.library_panel.isVisible():
                        self.library_panel.update_current_book_progress()

    def _on_slider_pressed(self):
        self.is_slider_dragging = True

    def _on_slider_released(self):

        if self.player and self.player.duration:
            try:
                old_pos = self.player.time_pos or 0.0
                new_pos = (self.progress_slider.value() / 1000) * self.player.duration
                speed = self.player.speed or 1.0
                if abs(new_pos - old_pos) > 60 * speed:
                    self._trigger_undo(old_pos)
                self.player.seek_async(new_pos)
                self.session_recorder.notify_seek(new_pos)
                # Immediately sync for library reactivity
                self.config.set_last_position(self.current_file, new_pos)
                if self.library_panel.isVisible():
                    self.library_panel.update_current_book_progress()
            except (ShutdownError, AttributeError, SystemError):
                pass

        self.is_slider_dragging = False

    def _on_slider_right_clicked(self, ratio):
        """Handler for right-click snapping to chapter notches."""
        if not self.player or not self.player.duration:
            return
        if self.player.mp3_seek_reload_pending:
            return

        self._hide_popups()
        try:
            old_pos = self.player.time_pos or 0.0
            # Calculate new position and add a tiny nudge (0.1s) to ensure
            # we land inside the intended chapter boundary.
            new_pos = min(self.player.duration, (ratio * self.player.duration) + 0.1)
            speed = self.player.speed or 1.0

            if abs(new_pos - old_pos) > 60 * speed:
                self._trigger_undo(old_pos)

            self.player.seek_async(new_pos)

            if self.player.pause:
                if self.current_file:
                    self.db.update_last_played(self.current_file)
                self.player.pause = False
                if not self.session_recorder.is_active:
                    self.session_recorder.open()
                else:
                    self.session_recorder.resume()
        except (ShutdownError, AttributeError, SystemError):
            return

    def _on_chap_slider_pressed(self):
        self.is_chapter_slider_dragging = True

    def _on_chap_slider_released(self):

        if self.player and self.player.duration:
            try:
                old_pos = self.player.time_pos or 0.0
                new_pos = self.player.seek_within_chapter(self.chapter_progress_slider.value() / 1000)
                if new_pos is None:
                    return

                speed = self.player.speed or 1.0
                if abs(new_pos - old_pos) > 60 * speed:
                    self._trigger_undo(old_pos)

                self.session_recorder.notify_seek(new_pos)

                self.config.set_last_position(self.current_file, new_pos)
                if self.library_panel.isVisible():
                    self.library_panel.update_current_book_progress()
            except (ShutdownError, AttributeError, SystemError):
                pass

        self.is_chapter_slider_dragging = False

    def _on_volume_changed(self, value):
        self.panel_manager.hide_all_panels()
        if self.player:
            self.player.set_volume_from_slider(value)

    def _set_speed(self, value, save=True):
        """Applies a specific speed value."""
        if self.speed_panel:
            self.speed_panel.set_speed(value, self.current_file, save)

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

    def _on_player_speed_changed(self, value):
        """Slot to sync the main UI speed button text with the player engine."""
        if hasattr(self, 'speed_button'):
            self.speed_button.setText(f"{value:.2f}x")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_C and getattr(self, '_chapter_label_clickable', False):
            self._show_chapter_dropdown()
        elif event.key() == Qt.Key.Key_T:
            if not self._theme_rotate_cooldown.isActive():
                self.theme_manager._rotate_theme()
                self._theme_rotate_cooldown.start()
            else:
                self._theme_rotate_pending = True
        elif event.key() == Qt.Key.Key_Q:
            # TODO: remove before release — testing only
            if not self.current_file and self.quote_section.isVisible():
                self.library_controller._rotate_quote()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        # Do not hide popups if clicking inside the panels
        for panel in [self.library_panel, self.settings_panel, self.speed_panel, self.sleep_panel, self.stats_panel, self.tags_panel, self.book_detail_panel]:
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
            self.chapter_list_widget.populate(self.player.duration or 0, self.player.speed or 1.0)

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

            # Refresh preview label text if a navigation button is currently hovered
            if self.config.get_chapter_hints_mode() == "Sticky":
                if self.prev_button.underMouse():
                    if self._prev_chap_title:
                        self.preview_row.setAlignment(self.chapter_preview_label, Qt.AlignLeft)
                        self.chapter_preview_label.setAlignment(Qt.AlignLeft)
                        self.chapter_preview_label.setText(self._prev_chap_title)
                    else:
                        self._clear_preview()
                elif self.next_button.underMouse():
                    if self._next_chap_title:
                        self.preview_row.setAlignment(self.chapter_preview_label, Qt.AlignRight)
                        self.chapter_preview_label.setAlignment(Qt.AlignRight)
                        self.chapter_preview_label.setText(self._next_chap_title)
                    else:
                        self._clear_preview()

    def _on_prev_hover(self):
        if self._prev_chap_title and self.config.get_chapter_hints_mode() != "Off":
            self.preview_anim.stop()
            self.preview_row.setAlignment(self.chapter_preview_label, Qt.AlignLeft)
            self.chapter_preview_label.setAlignment(Qt.AlignLeft)
            self.chapter_preview_label.setText(self._prev_chap_title)
            self.preview_anim.setStartValue(self.preview_opacity.opacity())
            self.preview_anim.setEndValue(1.0)
            self.preview_anim.start()

    def _on_next_hover(self):
        if self._next_chap_title and self.config.get_chapter_hints_mode() != "Off":
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

    def _apply_main_cover(self, pixmap):
        self.current_cover_pixmap = pixmap
        self.cover_art_label.show()
        self.metadata_label.hide()
        # Defer scaling so Qt re-layouts cover_art_label before we read its size.
        # Without this, switching from a no-cover book leaves the label at its
        # smaller (metadata_label-present) geometry, causing a misplaced/undersized cover.
        QTimer.singleShot(0, self._update_cover_art_scaling)
        if self.panel_manager and self.panel_manager.is_any_panel_visible():
            self._pending_cover_pixmap = pixmap
        else:
            self.theme_manager.apply_cover_theme(pixmap)
            self._pending_cover_pixmap = None

    def _load_cover_art(self, file_path):
        if not file_path:
            self.current_cover_pixmap = QPixmap()
            self.cover_art_label.hide()
            self.metadata_label.hide()
            self.theme_manager.clear_cover_theme()
            return
        book = self.db.get_book(file_path)
        active = self.db.get_active_cover(file_path)
        self._cover_fit_mode = active['fit_mode'] if active else 'fit'

        active_path   = active['file_path'] if active else None
        fallback_path = book.cover_path if book else None

        # No cover source at all → show author/title immediately
        if not active_path and not fallback_path:
            self.current_cover_pixmap = QPixmap()
            self.cover_art_label.hide()
            self.metadata_label.show()
            self.metadata_label.setText(
                f"{book.author} - {book.title}" if book else "Unknown book"
            )
            self._pending_cover_pixmap = None
            self.theme_manager.clear_cover_theme()
            return

        # Active cover set in book_covers → load from that path directly.
        # Skip cache: it may hold the scanner thumbnail (book.cover_path) which is
        # different from the user-selected active cover.
        if active_path:
            pixmap = QPixmap(active_path)
            if not pixmap.isNull():
                self._apply_main_cover(pixmap)
                return
            # File missing — fall through to legacy path below

        # Legacy path: no book_covers entry, use scanner thumbnail or extract_cover
        cached = self.library_panel.get_cached_cover(book.id) if book else None
        if cached is not None:
            self._apply_main_cover(cached)
            return
        pixmap = self.player.extract_cover(file_path)
        if not pixmap.isNull():
            self._apply_main_cover(pixmap)
        else:
            self.current_cover_pixmap = QPixmap()
            self.cover_art_label.hide()
            self.metadata_label.show()
            self.metadata_label.setText(
                f"{book.author} - {book.title}" if book else "Unknown book"
            )
            self._pending_cover_pixmap = None
            self.theme_manager.clear_cover_theme()

    def _on_active_cover_changed(self, book_path: str, file_path: str) -> None:
        if not book_path:
            return
        self.library_panel.refresh_book_cover(book_path)
        if book_path == self.current_file:
            book = self.db.get_book(book_path)
            if book:
                self.library_panel.evict_cover(book.id)
            if not file_path:
                # All covers removed — same fallback as a book with no cover
                self._load_cover_art(self.current_file)
                return
            active = self.db.get_active_cover(book_path)
            self._cover_fit_mode = active['fit_mode'] if active else 'fit'
            pixmap = QPixmap(file_path)
            if not pixmap.isNull():
                self._apply_main_cover(pixmap)
        self.tags_panel.refresh_books()

    def _update_cover_art_scaling(self):
        """Scales the current cover pixmap to the available space, respecting fit mode."""
        if not self.current_cover_pixmap.isNull() and self.cover_art_label.isVisible():
            target_w = self.cover_art_label.width()
            target_h = COVER_AREA_HEIGHT
            src = self.current_cover_pixmap
            fit = getattr(self, '_cover_fit_mode', 'fit')

            if fit == 'stretch':
                result = src.scaled(target_w, target_h,
                                    Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            elif fit == 'crop':
                s = src.scaled(target_w, target_h,
                               Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                x = (s.width()  - target_w) // 2
                y = (s.height() - target_h) // 2
                result = s.copy(x, y, target_w, target_h)
            elif fit == 'top':
                fitted = src.scaled(target_w, 32767,
                                    Qt.KeepAspectRatio, Qt.SmoothTransformation)
                result = QPixmap(target_w, target_h)
                result.fill(Qt.GlobalColor.black)
                painter = QPainter(result)
                painter.drawPixmap(0, 0, fitted)
                painter.end()
            else:  # 'fit'
                result = src.scaled(target_w, target_h,
                                    Qt.KeepAspectRatio, Qt.SmoothTransformation)

            self.cover_art_label.setPixmap(result)

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
        
        if self.player.eof_reached or self.play_pause_button.text() == "Restart":
            if not os.path.exists(self.current_file):
                self.status_banner.setText("Error: File missing!")
                self.status_banner.show()
                return
            self.session_recorder.close()
            self.config.set_last_position(self.current_file, 0)
            self.db.update_progress(self.current_file, 0)
            self._mpv_ready = True
            self.player.load_book(self.current_file, start_paused=False)
            self.player.ungate_play()
            return
        else:
            was_paused = self.player.pause
            if was_paused:
                if self.current_file:
                    self.db.update_last_played(self.current_file)

                # Delegate smart rewind logic to Player
                self.player.apply_smart_rewind(self._last_pause_timestamp, self.config.get_smart_rewind_wait(), self.config.get_smart_rewind_duration())

                self.player.pause = False
                self.library_panel.set_is_playing(True)
                if not self.session_recorder.is_active:
                    self.session_recorder.open()
                else:
                    self.session_recorder.resume()
            else:
                # Pausing
                self._last_pause_timestamp = time.time()
                self._save_current_progress()
                self.player.pause = True
                self.library_panel.set_is_playing(False)
                self.session_recorder.pause()
                if self.library_panel.isVisible():
                    self.library_panel.update_current_book_progress()

    def handle_rewind(self, long_skip=False):
        self.panel_manager.hide_all_panels()
        if self.player and not self.player.mp3_seek_reload_pending:
            old_pos = self.player.time_pos
            if old_pos is None:
                return
            speed = self.player.speed or 1.0
            if long_skip:
                skip = self.config.get_long_skip_duration() * 60 * speed
            else:
                skip = self.config.get_skip_duration() * speed
            new_pos = max(0, old_pos - skip)
            self.player.seek_async(new_pos)
            if long_skip:
                self._trigger_undo(old_pos)

    def handle_forward(self, long_skip=False):
        self.panel_manager.hide_all_panels()
        if self.player and not self.player.eof_reached and not self.player.mp3_seek_reload_pending:
            old_pos = self.player.time_pos
            if old_pos is None:
                return
            speed = self.player.speed or 1.0
            if long_skip:
                skip = self.config.get_long_skip_duration() * 60 * speed
            else:
                skip = self.config.get_skip_duration() * speed
            new_pos = min(self.player.duration or 0, old_pos + skip)
            self.player.seek_async(new_pos)
            if long_skip:
                self._trigger_undo(old_pos)

    def _on_prev_right_click(self):
        self.panel_manager.hide_all_panels()
        self._clear_preview()
        if self.player and self.current_file:
            old_pos = self.player.time_pos
            self.player.seek_async(0)
            self.player.is_seeking = True
            self._trigger_undo(old_pos)

    def handle_prev(self):
        self.panel_manager.hide_all_panels()
        if self.config.get_chapter_hints_mode() == "Transient":
            self._clear_preview()
        if self.player:
            old_pos = self.player.time_pos or 0.0
            target = self.player.previous_chapter()
            self.player.is_seeking = True
            if target is not None:
                speed = self.player.speed or 1.0
                if abs(target - old_pos) > 60 * speed:
                    self._trigger_undo(old_pos)

    def handle_next(self):
        self.panel_manager.hide_all_panels()
        if self.config.get_chapter_hints_mode() == "Transient":
            self._clear_preview()
        if self.player:
            old_pos = self.player.time_pos or 0.0
            target = self.player.next_chapter()
            self.player.is_seeking = True
            if target is not None:
                speed = self.player.speed or 1.0
                if abs(target - old_pos) > 60 * speed:
                    self._trigger_undo(old_pos)

    def _on_chapter_list_selected(self, title, old_pos, force_play):
        self.player.is_seeking = True
        if force_play:
            self.player.pause = False
            if self.current_file:
                if not self.session_recorder.is_active:
                    self.session_recorder.open()
                else:
                    self.session_recorder.resume()
        speed = self.player.speed or 1.0
        if abs((self.player.time_pos or 0) - old_pos) > 60 * speed:
            self._trigger_undo(old_pos)

    def _trigger_undo(self, old_pos):
        """Slides in the floating undo button."""
        duration = self.config.get_undo_duration()

        if not self.player.save_seek_position(old_pos, duration):
            return

        width = self.width()
        overlay_w = 32
        y_pos = 56
        target_x = width - overlay_w

        # Guard 1: already sliding in — let it finish.
        if self.undo_anim.state() == QPropertyAnimation.Running and self._undo_sliding_in is True:
            return

        # Guard 2: already visible and settled — just refresh the hide timer.
        if self.undo_overlay.isVisible() and self.undo_overlay.x() == target_x:
            self._undo_timer.stop()
            if duration > 0:
                self._undo_timer.start(duration * 1000)
            return

        self._undo_timer.stop()
        self.undo_anim.stop()
        self._undo_sliding_in = None

        self.undo_overlay.move(width, y_pos)
        self.undo_overlay.show()
        self.undo_overlay.raise_()

        self.undo_anim.setStartValue(QPoint(width, y_pos))
        self.undo_anim.setEndValue(QPoint(target_x, y_pos))
        self._undo_sliding_in = True
        self.undo_anim.start()

    def _on_undo_anim_finished(self):
        """Single dispatcher for undo_anim.finished. Replaces manual connect/disconnect."""
        if self._undo_sliding_in is True:
            self._undo_sliding_in = None
            self._on_undo_slide_in_done()
        elif self._undo_sliding_in is False:
            self._undo_sliding_in = None
            self.undo_overlay.hide()

    def _on_undo_slide_in_done(self):
        duration = self.config.get_undo_duration()
        if duration > 0:
            self._undo_timer.start(duration * 1000)

    def _perform_undo(self):
        """Seeks back and slides the button out."""
        # Delegate undo seek logic to Player
        self.player.undo_seek()
        self._hide_undo_banner()

    def _hide_undo_banner(self):
        if not self.undo_overlay.isVisible():
            return

        self._undo_pos = None
        width = self.width()
        overlay_w = 32
        y_pos = 56

        self.undo_anim.stop()
        self._undo_sliding_in = None

        self.undo_anim.setStartValue(QPoint(width - overlay_w, y_pos))
        self.undo_anim.setEndValue(QPoint(width, y_pos))
        self._undo_sliding_in = False
        self.undo_anim.start()

    def wheelEvent(self, event):
        """Handles volume control via mouse wheel on the cover art area."""
        if self.visual_area.underMouse():
            if not self.current_file:  # no book loaded — volume control inert
                return
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
        elif self.chapter_progress_slider.underMouse():
            if not self.player or not self.current_file:
                return
            if self.player.mp3_seek_reload_pending:
                return
            delta = event.angleDelta().y()
            chap_list = self.player.chapter_list or []
            current_pos = self.player.time_pos
            if current_pos is None:
                return
            if chap_list:
                curr_chap_idx = 0
                for i, chap in enumerate(chap_list):
                    if chap.get('time', 0) <= current_pos + _CHAPTER_BOUNDARY_EPSILON:
                        curr_chap_idx = i
                chap_start = chap_list[curr_chap_idx].get('time', 0)
                if curr_chap_idx + 1 < len(chap_list):
                    chap_dur = chap_list[curr_chap_idx + 1].get('time', 0) - chap_start
                else:
                    chap_dur = (self.player.duration or 0) - chap_start
                skip = max(10.0, chap_dur * 0.05)
            else:
                skip = self.config.get_skip_duration()
            speed = self.player.speed or 1.0
            skip *= speed
            if delta > 0:
                new_pos = min(self.player.duration or 0, current_pos + skip)
            else:
                new_pos = max(0, current_pos - skip)
            self._trigger_undo(current_pos)
            self.player.seek_async(new_pos)
            event.accept()
        else:
            super().wheelEvent(event)

    def _on_theme_rotate_cooldown(self):
        if self._theme_rotate_pending:
            self._theme_rotate_pending = False
            self.theme_manager._rotate_theme()
            self._theme_rotate_cooldown.start()

    def _show_volume_overlay(self):
        """Triggers the volume slider fade-in and starts the auto-hide timer."""
        self.vol_hide_timer.stop()
        self.vol_stack.setCurrentIndex(1)
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

    def _on_vol_fade_finished(self):
        if self.vol_opacity.opacity() == 0:
            self.vol_stack.setCurrentIndex(0)

    def eventFilter(self, obj, event):
        """Global event filter to handle dismissing popups on clicks outside."""
        try:
            if event.type() == QEvent.MouseButtonPress:
                if hasattr(self, 'chapter_list_widget') and self.chapter_list_widget.isVisible():
                    local_pos = self.mapFromGlobal(event.globalPosition().toPoint())
                    btn = self.chapter_list_widget._expand_btn
                    if btn.isVisible() and btn.geometry().contains(local_pos):
                        pass  # let the button handle its own click
                    elif not self.chapter_list_widget.geometry().contains(local_pos):
                        self.chapter_list_widget.fade_out()
                        return True
        except Exception:
            pass

        if event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress):
            if hasattr(self, 'library_panel') and not self.library_panel.preload_complete():
                self.library_panel.cancel_preload()
                if not hasattr(self, '_preload_restart_timer'):
                    self._preload_restart_timer = QTimer(self)
                    self._preload_restart_timer.setSingleShot(True)
                    self._preload_restart_timer.timeout.connect(self.library_panel.start_idle_preload)
                self._preload_restart_timer.start(5000)

        # Ensure obj is a valid QObject before calling super().eventFilter
        # Some internal Qt objects like QWidgetItem are not QObjects.
        if not isinstance(obj, QObject) or obj is None:
            return False
        return super().eventFilter(obj, event)
    
    def closeEvent(self, event):
        self.ui_timer.stop()
        self.quote_timer.stop()
        self._undo_timer.stop()
        self.library_panel.save_search_filter()
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

        self.session_recorder.close()
        event.accept()

    def _validate_smart_rewind_settings(self):
        if self.speed_panel:
            self.speed_panel._validate_smart_rewind_settings()
