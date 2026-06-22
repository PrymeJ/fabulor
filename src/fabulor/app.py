# THEME_ANIM_TODO: MainWindow, TitleBar, ChapterList, SpeedControlsPanel, 
# AudioSettingsTab, SleepTimerPanel, StatsPanel, BookDetailPanel, 
# status_banner, sidebar, vol_container
import os
import re
from datetime import datetime, timedelta
from PySide6.QtWidgets import (
    QFileDialog,
    QWidget, QPushButton, QVBoxLayout,
    QApplication, QGraphicsBlurEffect, QGraphicsOpacityEffect,
)
from PySide6.QtCore import (
    Qt, QTimer, QPoint, QEvent, QPropertyAnimation, QEasingCurve, QModelIndex,
    QRegularExpression, Signal, QObject, QByteArray, QElapsedTimer, QSize, QVariantAnimation
)
from PySide6.QtGui import QPixmap, QColor, QIntValidator, QRegularExpressionValidator, QIcon, QPainter
from PySide6.QtSvg import QSvgRenderer

from .player import Player, _CHAPTER_BOUNDARY_EPSILON, _CHAPTER_WALK_TOLERANCE
from .config import Config
from .themes import THEMES, _resolve_theme, get_player_stylesheet
from .ui.chapter_list import ChapterList # Keep ChapterList here as it's a direct child of MainWindow
from .ui.speed_controls import SpeedControlsPanel
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
from .ui.carousel import CoverCarousel, CAROUSEL_STRIPE_W
from .ui import main_window_builders as builders
from .db import LibraryDB
from .library.scanner import LibraryScanner
from .book_quotes import BOOK_QUOTES
from mpv import ShutdownError
from .settings_controller import SettingsController
from .session_recorder import SessionRecorder
from .book_switch import BookSwitchState

# Shared low-level UI helpers (moved to ui/ui_helpers.py so the extracted
# main_window_builders module can use them without importing app.py).
# Re-imported here so existing references in this module keep working unchanged.
from .ui.ui_helpers import _ASSETS_DIR, COVER_AREA_HEIGHT, _load_svg_icon, _load_svg_pixmap

# Chapter-slider "sliver" suppression (paused-only display fix).
# A chapter-nav seek lands at `_seek_target = nominal + offset`, where for VT/CUE the
# offset is `_CHAPTER_BOUNDARY_EPSILON` (0.35). So at a freshly-landed chapter start,
# `c_elapsed = pos - chap_start ~= 0.35` — which renders as a thin fill ("sliver") on
# the chapter slider WHILE PAUSED (live playback advances pos and swallows it within a
# frame, so it is never visible while playing). `_sliver_clamp` reads the slider value
# as 0 only when paused AND within this residue window. Tied to the boundary epsilon so
# the threshold tracks it automatically if that constant is ever retuned. Measured paused
# settle jitter is ~0.0004s, so 0.25s headroom is ~600x the real landing error.
_CHAPTER_SLIVER_EPS = _CHAPTER_BOUNDARY_EPSILON + 0.25  # 0.35 + 0.25 = 0.60


def _sliver_clamp(pause: bool, c_elapsed: float) -> float:
    """Display-only: collapse the sub-second chapter-start landing residue to 0 on the
    chapter slider while paused. Returns 0.0 when paused and within the residue window,
    else the real elapsed. Does NOT touch pos, labels, or audio. Pure for headless test."""
    if pause and c_elapsed < _CHAPTER_SLIVER_EPS:
        return 0.0
    return c_elapsed


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
    def set_bg_suppressed(self, v): self._main._set_bg_suppressed(v)
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
    def get_selected_folders(self): return self._main._get_selected_folder_paths()
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
        self._showing_placeholder = False
        self._carousel = None           # CoverCarousel widget inside carousel_holder (lazily built)
        self._carousel_slide_anim = None
        self._dialog_close_time = QElapsedTimer()
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
        self._eof_book_id: int | None = None
        self._eof_dur_fetched: bool = False

        # Session recording
        self._current_book = None
        self.session_recorder = SessionRecorder(
            db=self.db,
            get_position_fn=self._get_current_position,
            get_book_fn=lambda: self._current_book,
            get_day_start_hour_fn=self.config.get_day_start_hour,
            parent=self,
        )

        # Populate the streak grid cache once at startup (table seed + active-day
        # flip). Backend-only stand-in for the panel-open freshness refresh until
        # the streak grid UI exists. Must run after self.config exists (above);
        # reads day_start_hour directly, no SessionRecorder dependency.
        try:
            day_start = self.config.get_day_start_hour()
            today_adjusted = datetime.now() - timedelta(hours=day_start)
            self.db.build_streak_grid_cache(day_start)
            self.config.set_streak_grid_cache_date(today_adjusted.strftime('%Y-%m-%d'))
        except Exception:
            pass

        # Single authority for the book-switch transition lifecycle. Owns the
        # switch-specific flags (deadzone, pre-switch slider captures, duration-retry,
        # deferred-handler flags) that were previously scattered as raw attributes.
        self._switch = BookSwitchState()

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
        self.progress_slider._flow_anim.finished.connect(
            self._resume_ui_timer,
            Qt.UniqueConnection
        )

        self.status_hide_timer = QTimer(self)
        self.status_hide_timer.setSingleShot(True)
        self.status_hide_timer.timeout.connect(self._slide_banner_out)

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

        theme = self.theme_manager.get_current_theme()
        self._eof_revert_pixmaps = self._build_eof_revert_pixmaps(theme.get('accent', '#ffffff'))
        self._eof_revert_pixmaps_hover = self._build_eof_revert_pixmaps(theme.get('accent_light', theme.get('accent', '#ffffff')))
        self.eof_revert_btn.set_icons(*self._eof_revert_pixmaps)
        self.eof_revert_btn.installEventFilter(self)
        self.eof_revert_btn.clicked.connect(self._on_revert_finish)
        self._set_eof_close_handler(self._dismiss_eof_prompt)

        self.scan_now_btn.clicked.connect(self.library_controller._on_scan_now_clicked)
        self.add_folder_btn.clicked.connect(self.library_controller._on_scan_now_clicked)
        self.remove_folder_btn.clicked.connect(self.library_controller._on_remove_folder_clicked)
        self.refresh_library_btn.clicked.connect(self.library_controller._on_rescan_clicked)

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
            # No switch SM involvement at startup: phase stays IDLE (in_deadzone False),
            # so there is no deadzone to clear here.
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

        builders.build_title_bar(self)
        builders.build_progress_bar(self)

        # Content container
        self.content_container = QWidget()
        self.content_layout = QVBoxLayout(self.content_container)
        self.content_layout.setContentsMargins(10, 10, 10, 10) #the whole container
        self.content_layout.setSpacing(10)
        self.root_layout.addWidget(self.content_container)

        # Visual Area for blurring (Cover Art and Metadata)
        # _bg_suppressed: drives theme bg_image omission in no-book/empty states.
        # Read by ThemeManager._apply_stylesheets; owned by _set_bg_suppressed.
        self._bg_suppressed = False
        self.visual_area = QWidget()
        self.visual_area.setObjectName("visual_area")
        self.visual_layout = QVBoxLayout(self.visual_area)
        self.visual_layout.setContentsMargins(0, 0, 0, 0) # cover art area
        self.visual_layout.setSpacing(10)
        self.visual_area.mousePressEvent = self._on_drag_area_pressed
        self.content_layout.addWidget(self.visual_area, 1) # Stretch factor 1 to claim space

        builders.build_cover_art(self)
        builders.build_metadata(self)
        builders.build_controls(self)
        builders.build_secondary_controls(self)

        self.chapter_list_widget = ChapterList(self)
        self.chapter_list_widget.chapter_changed.connect(self._update_chapter_title_text)
        self.chapter_list_widget.chapter_selected.connect(self._on_chapter_list_selected)
        
        builders.build_sidebar(self)
        builders.build_library_panel(self)
        builders.build_settings_panel(self)
        builders.build_stats_panel(self)
        builders.build_tags_panel(self)

        self.speed_panel = SpeedControlsPanel(self.player, self.config, self.theme_manager, self)
        self.speed_panel.hide()
        self.speed_panel_animation = QPropertyAnimation(self.speed_panel, b"pos")
        self.speed_panel_animation.setDuration(300)
        self.speed_panel_animation.setEasingCurve(QEasingCurve.OutCubic)
        
        builders.build_status_banner(self)
        self._banner_anim = QPropertyAnimation(self.status_banner, b"pos")
        self._banner_anim.setDuration(220)
        self._banner_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._banner_sliding_out = False
        self._banner_anim.finished.connect(self._on_banner_anim_finished)

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
        builders.build_book_detail_panel(self)
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
        self._dismiss_eof_prompt()
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
        if self.book_detail_panel._context == 'library':
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

        # Clear markers and stop all in-flight animations to prevent
        # them from fighting the reset or ghosting over the next book.
        self.progress_slider.set_markers([])
        self.progress_slider._flow_anim.stop()
        if hasattr(self.progress_slider, '_reveal_anim'):
            self.progress_slider._reveal_anim.stop()
        self.chapter_progress_slider._flow_anim.stop()

        # Explicitly zero out internal values and text labels.
        # Without this, the next book load will briefly show the old book's 
        # progress labels before the new book's metadata is ready.
        self.progress_slider._value = 0
        self.chapter_progress_slider.setValue(0)  # resets _value internally
        self.progress_percentage_label.setText("")
        self.current_time_label.setText("")
        self.total_time_label.setText("")
        self.chap_elapsed_label.setText("")
        self.chap_duration_label.setText("")
        self.current_chapter_label.setText("")
        self._prev_chap_title = ""
        self._next_chap_title = ""
        self._last_saved_pct = -1

        self._set_chapter_ui_active(False)
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

    def _get_selected_folder_paths(self):
        return [item.text() for item in self.folder_list_widget.selectedItems()]

    def _get_new_folder_path(self):
        path = QFileDialog.getExistingDirectory(None, "Select Library Folder")
        self._dialog_close_time.restart()
        return path

    def _update_status_banner_ui(self, text=None, show_banner=None, show_cancel=None, auto_hide=False,
                                 auto_hide_ms=3000):
        # Cancel any pending hide if we are updating text or changing visibility
        if show_banner is not None:
            self.status_hide_timer.stop()

        if text is not None and (self.status_banner.isVisible() or show_banner):
            self.status_label.setText(text)
            fade = getattr(self.theme_manager, '_fade_overlay', None)
            if self.status_banner.isVisible() and not (fade and fade.isVisible()):
                self.status_banner.raise_()

        if show_banner is True:
            self._slide_banner_in()
        elif show_banner is False:
            self._slide_banner_out()

        if show_cancel is True:
            self.cancel_scan_btn.show()
            # A scan starting takes over the banner — intentionally retires
            # any pending EOF revert prompt (book stays finished), same
            # contract as _dismiss_eof_prompt. Inlined because the banner
            # state is already being rewritten here for the scan.
            self._eof_book_id = None
            self.eof_revert_btn.hide()
            self.eof_close_btn.hide()
        elif show_cancel is False: self.cancel_scan_btn.hide()

        if auto_hide:
            self.status_hide_timer.start(auto_hide_ms)

    def _on_banner_anim_finished(self):
        if self._banner_sliding_out:
            self.status_banner.hide()

    def _slide_banner_in(self):
        h = self.height()
        self._banner_sliding_out = False
        self._banner_anim.stop()
        self.status_banner.setGeometry(0, h, self.width(), 36)
        self.status_banner.show()
        self.status_banner.raise_()
        self._banner_anim.setStartValue(self.status_banner.pos())
        self._banner_anim.setEndValue(QPoint(0, h - 36))
        self._banner_anim.start()

    def _slide_banner_out(self):
        if not self.status_banner.isVisible():
            return
        h = self.height()
        self._banner_sliding_out = True
        self._banner_anim.stop()
        self._banner_anim.setStartValue(self.status_banner.pos())
        self._banner_anim.setEndValue(QPoint(0, h))
        self._banner_anim.start()

    def _build_eof_revert_pixmaps(self, color: str):
        """Returns (base_pixmap, checkmark_pixmap) for the finished-banner revert
        icon, both rendered in `color` at the button's icon size. The base is the
        circular-arrow only (no checkmark) — what remains once RevertButton's wipe
        animation has masked the checkmark away. See revert_arrow.svg/revert_check.svg
        (split from the original revert.svg) and RevertButton in ui/controls.py."""
        size = QSize(20, 20)
        base = _load_svg_pixmap("revert_arrow.svg", color=color, size=size)
        check = _load_svg_pixmap("revert_check.svg", color=color, size=size)
        return base, check

    def _set_eof_close_handler(self, handler) -> None:
        """(Re)points eof_close_btn's click at `handler`. The button is shared by
        two banner states with different dismiss semantics: the "Marked as
        finished." prompt (_dismiss_eof_prompt — retires the revert offer without
        touching the DB) and the post-revert "Finished status reverted." banner
        (a plain slide-out — there is no DB-affecting action left to retire)."""
        if getattr(self, '_eof_close_handler', None) is not None:
            self.eof_close_btn.clicked.disconnect(self._eof_close_handler)
        self.eof_close_btn.clicked.connect(handler)
        self._eof_close_handler = handler

    def _on_revert_finish(self) -> None:
        if self._eof_book_id is None:
            return
        # eof_close_btn stays visible/enabled throughout (just re-pointed below)
        # so the banner is always dismissable, including during the wipe+pause.
        # eof_revert_btn stays visible too (showing the wiped, arrow-only icon as
        # the "reverted" state's visual anchor) — only disabled, since there's
        # nothing left to click. It is deliberately never hidden: hiding it would
        # shrink the status_banner's QHBoxLayout's centered [status_label,
        # eof_revert_btn] group, shifting status_label sideways relative to where
        # it sits while the icon is showing.
        self.eof_revert_btn.setEnabled(False)
        self._set_eof_close_handler(self._dismiss_status_banner)

        def _finish_revert():
            book_id = self._eof_book_id
            if book_id is None:
                return
            self.db.unfinish_book(book_id, self.config.get_day_start_hour())
            self._eof_book_id = None
            # show_banner intentionally omitted (left None): the banner is already
            # visible from the "Marked as finished." prompt, so re-passing True
            # would re-run _slide_banner_in, which forces the banner off-screen
            # before sliding it back up — a jarring dismiss-then-reappear for a
            # banner that never actually left.
            self._update_status_banner_ui(
                text="Finished status reverted.",
                show_cancel=False,
                auto_hide=True,
                auto_hide_ms=5000,
            )
            self.stats_panel.refresh_all()
            self.library_panel.refresh()

        def _on_wipe_finished():
            QTimer.singleShot(450, _finish_revert)

        self.eof_revert_btn.play_wipe(on_finished=_on_wipe_finished)

    def _dismiss_status_banner(self) -> None:
        """Plain dismiss for banner states with no DB-affecting action left to
        retire (currently: the post-revert "Finished status reverted." banner).
        Contrast _dismiss_eof_prompt, which also clears _eof_book_id."""
        self._update_status_banner_ui(show_banner=False)

    def _dismiss_eof_prompt(self) -> None:
        """Hide the finished-prompt without touching the DB — the book stays
        finished. Used both for the explicit close button and for any action
        (seek away from EOF, Restart, sleep timer start, book switch) that
        should silently retire the prompt rather than offer a revert."""
        if self._eof_book_id is None:
            return
        self._eof_book_id = None
        self.eof_revert_btn.hide()
        self.eof_close_btn.hide()
        self._update_status_banner_ui(show_banner=False)

    def _mark_book_missing(self, path: str) -> None:
        """Soft-deletes a book whose backing file/folder is confirmed gone —
        mirrors the user-trash flow (set_book_excluded), not remove_scan_location's
        is_deleted. The book stays in the DB (progress, history, tags survive) and
        a future force rescan or the file's return can resurface it; only Cover/Tags
        editing and active playback are gone, exactly like a user-trashed book.

        Call this ONLY at a confirmed-missing point — i.e. after os.path.exists(path)
        has returned False, or mpv itself reported the load failed. Do not call it
        speculatively (e.g. on a transient I/O hiccup) — that would hide a book the
        user could otherwise still play once a drive remounts.

        If the missing book is the active one, also tears down playback via
        _on_book_removed so the UI doesn't keep showing a ghost now-playing state."""
        book = self.db.get_book(path)
        if book is None:
            return
        self.db.set_book_excluded(path, True)
        self.library_panel.refresh(force=True)
        self.tags_panel.refresh_books()
        self.stats_panel.refresh_current_tab()
        if path == self.current_file:
            self._on_book_removed()

    def _on_book_metadata_saved(self, book_id: int, title: str, author: str, narrator: str, year: object):
        self.library_panel._book_model.update_book_metadata(book_id, title, author, narrator, year)
        if self.stats_panel.isVisible():
            self.stats_panel.refresh_all()

    def _on_session_written(self):
        if self.stats_panel.isVisible():
            self.stats_panel.refresh_current_tab()
        if self.book_detail_panel.isVisible():
            self.book_detail_panel._refresh_stats()

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

    def _show_carousel(self):
        """Build and place the carousel synchronously. Safe to call multiple times."""
        if self._carousel is not None:
            return   # already showing — do not reshuffle mid-display
        if self.current_file or not self.no_book_section.isVisible():
            return   # not in the no-book state
        pixmaps, cover_h = builders.build_carousel_covers(self)
        if not pixmaps:
            return
        t = _resolve_theme(self.theme_manager._current_theme_name)
        bg_color = t.get('carousel_bg', t.get('slider_overall_bg', '#1a1a1a'))
        line_color = t.get('carousel_stripe') or None
        self._carousel = CoverCarousel(pixmaps, cover_h, stripe_color=bg_color, line_color=line_color)

        y = self.carousel_holder.mapTo(self.content_container, QPoint(0, 0)).y()
        self._carousel.setParent(self.content_container)
        carousel_h = self._carousel.height()
        self._carousel.setGeometry(CAROUSEL_STRIPE_W, y, CAROUSEL_STRIPE_W, carousel_h)
        self._carousel.stackUnder(self.visual_area)
        # visual_area's QSS background is already suppressed by the not-has_book
        # branch of apply_library_state (set_bg_suppressed(True)), so the stripe
        # paints through. Suppression is owned by the state machine, not here.
        self._carousel.show()

        # Slide in from the right over 200ms; covers reveal only after 325ms so they
        # always appear on the settled stripe.
        self._carousel_slide_anim = QPropertyAnimation(self._carousel, b"pos")
        self._carousel_slide_anim.setDuration(220)
        self._carousel_slide_anim.setStartValue(QPoint(CAROUSEL_STRIPE_W, y))
        self._carousel_slide_anim.setEndValue(QPoint(0, y))
        self._carousel_slide_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._carousel_slide_anim.start()

    def _hide_carousel(self):
        """Stop and remove the carousel."""
        if self._carousel_slide_anim is not None:
            self._carousel_slide_anim.stop()
            self._carousel_slide_anim = None
        if self._carousel is not None:
            self._carousel.stop()
            self._carousel.hide()
            self._carousel.setParent(None)
            self._carousel.deleteLater()
            self._carousel = None
        # Background suppression is owned by apply_library_state via
        # _set_bg_suppressed — not toggled here on teardown.

    def _set_bg_suppressed(self, suppressed: bool):
        """Single authority for the visual_area background-image suppression used
        in the no-book and empty states.

        The theme bg_image is painted by content_container's `#visual_area` QSS
        rule. It CANNOT be cancelled by overriding the child: Qt's QSS cascade
        treats `background-image: none` as "unspecified", so the ancestor rule's
        url() wins on the child anyway (verified — a child `background-color`
        override applied, but the image layered on top of it). The only reliable
        kill-switch is to regenerate content_container's stylesheet WITHOUT the
        image. `_bg_suppressed` is read by ThemeManager._apply_stylesheets so a
        theme change in these states keeps the image stripped.

        autoFillBackground(False) when suppressed lets the carousel stripe / themed
        window background show through the now-transparent visual_area."""
        self._bg_suppressed = suppressed
        self.visual_area.setAutoFillBackground(not suppressed)
        # Use the active display theme (may be a cover-art dict) rather than
        # _current_theme_name (the named pool theme). Using _current_theme_name
        # while a cover theme is active regenerates the stylesheet with pool
        # colors, causing a visible flash to the non-cover theme on every book
        # switch (apply_library_state always calls _set_bg_suppressed(False)).
        theme_name = (getattr(self.theme_manager, '_active_display_theme', None)
                      or self.theme_manager._current_theme_name)
        self.content_container.setStyleSheet(
            get_player_stylesheet(theme_name, suppress_bg_image=suppressed)
        )
        # The setStyleSheet triggers Qt to call polish() on all child widgets, which
        # re-reads the QSS and overrides the transparent bg_color/fill_color set by
        # the preemptive _set_chapter_ui_active(False). Re-assert directly without
        # the full _set_chapter_ui_active side effects (animation stop, cursor, labels).
        if not getattr(self, '_chapter_ui_active', True) and hasattr(self, 'chapter_progress_slider'):
            s = self.chapter_progress_slider
            s.bg_color = QColor("transparent")
            s.fill_color = QColor("transparent")
            s.update()

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
            # Stop any in-flight bg_color/fill_color animations before setting
            # transparent. If a theme fade started (and animated the slider colors
            # toward a non-transparent value) while this book was still chapter-active,
            # those QPropertyAnimations would immediately override the transparent
            # value we're about to set — making the background briefly visible.
            if hasattr(self, 'theme_manager'):
                tm = self.theme_manager
                if hasattr(tm, '_slider_anims'):
                    for anim in tm._slider_anims.get(id(slider), {}).values():
                        from PySide6.QtCore import QPropertyAnimation
                        if anim.state() != QPropertyAnimation.State.Stopped:
                            anim.stop()
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

        if not os.path.exists(path):
            self._update_status_banner_ui(text="Error: File missing!", show_banner=True, auto_hide=True)
            self.panel_manager.hide_all_panels()
            self._mark_book_missing(path)
            return

        self._dismiss_eof_prompt()
        self._save_current_progress()
        self._paused_time = None
        # Enter the switch lifecycle: capture the current slider values as flow-animation
        # start points, arm the deadzone, and reset the per-switch retry/deferred flags.
        self._switch.begin(
            self.progress_slider.value(),
            # Only capture a meaningful pre_chap when the chapter UI is active.
            # Capturing a stale value from a chapterless book would arm
            # flow_pending_chapter, gating _sync_chapter_ui and causing a flash
            # when take_chapter_target() later lifts the gate on the still-hidden slider.
            self.chapter_progress_slider.value() if self._chapter_ui_active else None,
        )
        self.current_chapter_label.setText("")
        self.progress_slider.set_markers([])
        self.chapter_list_widget.clear()
        self._last_saved_pct = -1
        self._eof_dur_fetched = False
        self._eof_book_id = None
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

    def _resume_ui_timer(self):
        """Resume the 200ms UI timer. Idempotent — safe to call if already running.
        Called from _flow_anim.finished (animate path) and explicitly from every
        non-animate exit in _on_file_ready (setValue, no-duration, error paths)."""
        self.ui_timer.start(200)

    def _on_vt_file_switched(self):
        """Lightweight handler for VT file switches. Does not restore position."""
        self.player.is_seeking = False

    def _on_file_ready(self):
        """Called when mpv confirms the file is loaded and ready."""
        if getattr(self.library_panel, '_is_animating', False):
            self._switch.mark_file_ready_deferred()
            return
        self._switch.clear_file_ready_deferred()
        self.ui_timer.stop()
        if not os.path.exists(self.current_file):
            self._update_status_banner_ui(text="Error: File missing!", show_banner=True, auto_hide=True)
            missing_path = self.current_file
            self._resume_ui_timer()
            self._mark_book_missing(missing_path)
            return
        self._eof_event_written = False # Temporary
        self._current_book = self.db.get_book(self.current_file)

        self._restore_position()
        # Removed self._update_ui_sync() from here.
        # The explicit call often snapped sliders to target values before the
        # flow animation could start from 0, causing the visible "flash" at startup.

        book_data = self._current_book
        new_progress = book_data.progress if book_data else 0
        pre = self._switch.take_progress_target()
        pre = pre if pre is not None else 0  # startup/EOF-restart: animate from 0
        dur = self.player.duration or (book_data.duration if book_data else None)
        if new_progress == 0:
            # Book starting from scratch — always animate to 0.
            new_val = 0
        elif not dur:
            # Duration still unavailable after DB fallback — skip animation.
            # _is_seeking guard holds the slider until seek completes, then
            # the timer snaps to the correct position.
            new_val = None
        else:
            new_val = int((new_progress / dur) * 1000)
        if new_val is None:
            self._resume_ui_timer()
        elif pre != new_val:
            self.progress_slider.animate_to(new_val, old_value=pre)
            # _resume_ui_timer fires via _flow_anim.finished
            self._animate_percentage_label(pre, new_val, new_progress, dur)
        else:
            self.progress_slider.setValue(new_val)
            end_percent = round((new_progress / dur) * 100, 1) if dur else new_val / 10
            self.progress_percentage_label.setText(f"{end_percent:.1f}%")
            self._resume_ui_timer()

    def _animate_percentage_label(self, start_val: int, end_val: int, new_progress: float, dur: float):
        """Counts the percentage label from start_val/10 to end_val/10 (both on
        the slider's 0-1000 scale) in lockstep with progress_slider.animate_to —
        same distance-scaled duration formula (see ClickSlider.animate_to), so
        the two finish together. No pause, no easing beyond the slider's own
        InOutCubic — a plain parallel tween, not a reveal animation.

        end_val (new_val in the caller) is int()-truncated to the slider's
        0-1000 scale, e.g. 739 for a true value of 739.97. The live 200ms tick
        that resumes right after instead computes percent = (pos/dur)*100 and
        rounds it with "%.1f" — for the same 739.97-ish true percentage that's
        74.0, not 73.9. The mismatch is truncate-vs-round, not a timing race,
        so a settle-delay cannot fix it (confirmed by testing one — the jump
        was identical with or without it). Fix: animate to the same rounded
        percent the live tracker will show, computed once here from the exact
        new_progress/dur the caller already has, instead of re-deriving a
        coarser value from end_val."""
        if hasattr(self, '_pct_label_anim') and self._pct_label_anim.state() == QPropertyAnimation.State.Running:
            self._pct_label_anim.stop()
        span = self.progress_slider.maximum() - self.progress_slider.minimum()
        distance = abs(end_val - start_val) / max(1, span)
        duration = int(200 + distance * 400)
        end_percent = round((new_progress / dur) * 100, 1) if dur else end_val / 10
        anim = QVariantAnimation(self)
        anim.setDuration(duration)
        anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        anim.setStartValue(start_val / 10.0)
        anim.setEndValue(end_percent)
        anim.valueChanged.connect(
            lambda v: self.progress_percentage_label.setText(f"{v:.1f}%"))
        self._pct_label_anim = anim
        anim.start()

    def _on_file_loaded_populate_chapters(self):
        if getattr(self.library_panel, '_is_animating', False):
            self._switch.mark_chaps_deferred()
            return
        self._switch.clear_chaps_deferred()
        try:
            dur = self.player.duration
            if not dur:
                # Duration not yet cached from mpv. Schedule one retry rather than
                # calling _set_chapter_ui_active(False) prematurely.
                if not self._switch.chaps_dur_retried:
                    self._switch.chaps_dur_retried = True
                    QTimer.singleShot(150, self._on_file_loaded_populate_chapters)
                    return
                # Second attempt: dur still unavailable — fall through to deactivate.
                self._switch.chaps_dur_retried = False
            else:
                self._switch.chaps_dur_retried = False
            # Cache instance.chapter_list for embedded M4B now that dur is confirmed.
            # Eliminates the live C-layer read race in _sync_chapter_ui mid-seek.
            if dur:
                self.player.cache_chapter_list()
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
        pre_chap = self._switch.take_chapter_target()
        pre_chap = pre_chap if pre_chap is not None else 0

        book_data = getattr(self, '_current_book', None)
        new_progress = book_data.progress if book_data else 0
        curr_chap_idx = 0
        if new_progress == 0:
            new_chap_val = 0
        else:
            # Compute from authoritative data (chapter list + saved progress)
            # rather than reading the stale slider value. At the time this handler
            # runs the timer has not ticked, so slider.value() holds the previous
            # book's chapter position (same as pre_chap) — making pre_chap ==
            # new_chap_val always False and degrading animate_to to setValue.
            chap_list = self.player.chapter_list or []
            chap_dur_val = self.player.duration or 0
            if chap_list and chap_dur_val:
                for i, chap in enumerate(chap_list):
                    if chap.get('time', 0) <= new_progress + _CHAPTER_WALK_TOLERANCE:
                        curr_chap_idx = i
                start = chap_list[curr_chap_idx].get('time', 0)
                end = chap_list[curr_chap_idx + 1].get('time', chap_dur_val) if curr_chap_idx + 1 < len(chap_list) else chap_dur_val
                cd = end - start
                seek_offset = 0.0 if self.player._virtual_timeline is not None else _CHAPTER_BOUNDARY_EPSILON
                c_elapsed = max(0, (new_progress + seek_offset) - start)
                # Don't flow to a paused chapter-start sliver on a book that resumes at a
                # chapter boundary. depends on load_book's _cached_pause reset above — do
                # not reorder this computation above that reset (it would read stale pause).
                slider_elapsed = _sliver_clamp(self.player.pause, c_elapsed)
                new_chap_val = int((slider_elapsed / cd) * 1000) if cd > 0 else 0
            else:
                new_chap_val = 0
        if pre_chap != new_chap_val:
            self.chapter_progress_slider.animate_to(new_chap_val, old_value=pre_chap)
        else:
            self.chapter_progress_slider.setValue(new_chap_val)
        if self.player.chapter_list and not self.player.is_seeking:
            self._update_chapter_label_from_index(curr_chap_idx)

    def _drain_deferred_file_ready(self):
        if self._switch.file_ready_deferred:
            self._on_file_ready()
        if self._switch.chaps_deferred:
            self._on_file_loaded_populate_chapters()
        self._apply_pending_cover_theme()

    def _apply_pending_cover_theme(self):
        pixmap = getattr(self, '_pending_cover_pixmap', None)
        if not pixmap:
            return
        self._pending_cover_pixmap = None
        # Chain through both sliders' when_animations_done before starting the
        # theme fade. The chapter progress slider is punch-through-exposed during
        # theme fades; if its value animation (animate_to) is still running when
        # the fade overlay is captured, the moving fill produces a ghost image.
        # Waiting for both sliders to settle eliminates the overlap.
        def _apply():
            self.theme_manager.apply_cover_theme(pixmap)
        def _after_progress():
            if hasattr(self, 'chapter_progress_slider') and hasattr(self.chapter_progress_slider, 'when_animations_done'):
                self.chapter_progress_slider.when_animations_done(_apply)
            else:
                _apply()
        if hasattr(self.progress_slider, 'when_animations_done'):
            self.progress_slider.when_animations_done(_after_progress)
        else:
            _after_progress()

    def _on_load_failed(self, reason):
        """Called when mpv fires end-file with a non-normal reason (error/unknown),
        or when _resolve_playlist determined the folder has no audio files."""
        self._update_status_banner_ui(text=f"Failed to load: {reason}.", show_banner=True, auto_hide=True)
        if reason == "no audio files in folder" and self.current_file:
            self._mark_book_missing(self.current_file)

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
            # Restore to the exact saved position for all book types. This is NOT
            # chapter navigation — there is no boundary to clear — so no epsilon is
            # added. The old non-VT `+ _CHAPTER_BOUNDARY_EPSILON` caused position
            # creep: the 200ms persistence sync saved the epsilon-inflated landing,
            # which became the next restore's input, nudging ~0.35s forward every
            # restart until EOF. The VT branch never added it and never crept.
            self.player.seek_async(book_data.progress)
        else:
            # No position to restore — clear the _is_seeking flag set by load_book.
            # Without this, _on_time_pos_change won't auto-clear it (since _seek_target
            # is None) and _sync_progress_sliders would never update the slider.
            self.player.is_seeking = False
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
                    self.db.write_book_event(self._current_book.path, 'finished', book_id=self._current_book.id, day_start_hour=self.config.get_day_start_hour())
                    self._eof_event_written = True
                    self._eof_book_id = self._current_book.id if self._current_book else None
                    self._update_status_banner_ui(
                        text="Marked as finished.",
                        show_banner=True,
                        show_cancel=False,
                        auto_hide=False,
                    )
                    self.eof_revert_btn.reset_wipe()
                    self.eof_revert_btn.setEnabled(True)
                    self.eof_revert_btn.show()
                    self.eof_close_btn.setEnabled(True)
                    self.eof_close_btn.show()
                    self._set_eof_close_handler(self._dismiss_eof_prompt)
                    self.session_recorder.close()
                    if hasattr(self, 'stats_panel') and self.stats_panel.isVisible():
                        self.stats_panel.refresh_all()
                    self.stats_panel.refresh_overall()
                    if self.book_detail_panel.isVisible():
                        self.book_detail_panel._refresh_stats()
                    if self.library_panel.isVisible():
                        self.library_panel.refresh()
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
                # Left EOF (user seeked/rewound away) — retire any pending
                # revert prompt silently; the book stays marked finished.
                self._dismiss_eof_prompt()
                if is_paused:
                    if mpv_pos is not None and not self._switch.in_deadzone:
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
                    if chap.get('time', 0) <= pos + _CHAPTER_WALK_TOLERANCE:
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
        if hasattr(self, 'eof_revert_btn'):
            self._eof_revert_pixmaps = self._build_eof_revert_pixmaps(t.get('accent', '#ffffff'))
            self._eof_revert_pixmaps_hover = self._build_eof_revert_pixmaps(t.get('accent_light', t.get('accent', '#ffffff')))
            self.eof_revert_btn.set_icons(
                *(self._eof_revert_pixmaps_hover if self.eof_revert_btn.underMouse() else self._eof_revert_pixmaps)
            )
        if self._carousel is not None:
            bg_color = t.get('carousel_bg', t.get('slider_overall_bg', '#1a1a1a'))
            line_color = t.get('carousel_stripe') or None
            self._carousel.set_stripe_color(bg_color, line_color=line_color)
        if self._showing_placeholder:
            self._show_cover_placeholder()
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
                if not slider_animating and not self.player.is_seeking and not self._switch.flow_pending_progress:
                    self.progress_slider.setValue(int((pos / dur) * 1000))
                self.current_time_label.setText(self.player.format_time(pos / speed))
                if self.show_remaining_time:
                    remaining = (dur - pos) / speed
                    self.total_time_label.setText(f"-{self.player.format_time(remaining)}")
                else:
                    self.total_time_label.setText(self.player.format_time(dur / speed))
                pct_label_animating = (hasattr(self, '_pct_label_anim')
                                        and self._pct_label_anim.state()
                                        == QPropertyAnimation.State.Running)
                if not pct_label_animating:
                    self.progress_percentage_label.setText(f"{percent:.1f}%")

    def _sync_chapter_ui(self, pos, dur, speed):
        if self.player and self.player.mp3_seek_reload_pending:
            return
        chap_list = self.player.chapter_list or []
        if not chap_list:
            return
        # Guard: skip during book-switch pre-animation window. Without this, the timer
        # fires between the pre_chap capture and the animate_to() call, writing the
        # new file's chapter-at-pos-0 to the slider and producing a visible jump
        # before the flow animation starts.
        if self._switch.flow_pending_chapter:
            return
        # Guard: skip during seeks. Intermediate time_pos values would cause the timer
        # to write a wrong chapter position to the slider (and wrong elapsed/duration
        # labels) while mpv is scanning toward the target. The timer self-corrects within
        # one 200ms tick after is_seeking clears.
        if self.player.is_seeking:
            return
        # Always derive chapter from pos so the UI stays consistent regardless
        # of when mpv's internal chapter property settles after a seek.
        curr_chap = 0
        for i, chap in enumerate(chap_list):
            if chap.get('time', 0) <= pos + _CHAPTER_WALK_TOLERANCE:
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
                # The chap_animating guard (book-switch flow animation) must stay.
                if chap_dur > 0 and not chap_animating:
                    # Suppress the paused chapter-start "sliver" (the ~0.35s VT/CUE
                    # landing residue rendered as a thin fill). Released the instant
                    # playback starts — pos is moving, so no jump. Labels keep the real
                    # c_elapsed (they already floor to 00:00 below 1s).
                    slider_elapsed = _sliver_clamp(self.player.pause, c_elapsed)
                    self.chapter_progress_slider.setValue(int((slider_elapsed / chap_dur) * 1000))

    def _sync_persistence(self, pos, dur):
        if dur is not None and dur > 0:
            if not self.is_slider_dragging and not self._switch.in_deadzone:
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
        """Right click sets the current playback speed as the default speed."""
        self._hide_popups()
        if not self.player: return
        current = self.player.speed or self.config.get_default_speed()
        if self.speed_panel:
            self.speed_panel.set_default_speed(current)
        t = self.theme_manager.get_current_theme()
        self.speed_button.shimmer_opacity = t.get("button_speed_shimmer", 0.55)
        self.speed_button.play_shimmer()

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
        # Suppress chapter label updates during seeks. Intermediate time_pos events
        # fire chapter_changed as mpv scans through chapters toward the target,
        # causing visible VU-meter oscillation between chapter names. The final
        # time_pos event that settles the seek clears _is_seeking and fires one
        # clean chapter_changed with the correct index.
        if self.player.is_seeking:
            return
        if self._switch.flow_pending_chapter:
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
        self._showing_placeholder = False
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
            self._showing_placeholder = False
            self.cover_art_label.hide()
            self.metadata_label.hide()
            self.theme_manager.clear_cover_theme()
            return
        book = self.db.get_book(file_path)
        active = self.db.get_active_cover(file_path)
        self._cover_fit_mode = active['fit_mode'] if active else 'fit'

        active_path   = active['file_path'] if active else None
        fallback_path = book.cover_path if book else None

        # No cover source at all → show placeholder logo + author/title
        if not active_path and not fallback_path:
            self.current_cover_pixmap = QPixmap()
            self._pending_cover_pixmap = None
            self.theme_manager.clear_cover_theme()
            self._show_cover_placeholder()
            self.metadata_label.show()
            self.metadata_label.setText(
                f"{book.author} - {book.title}" if book else "Unknown book"
            )
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
            self._pending_cover_pixmap = None
            self.theme_manager.clear_cover_theme()
            self._show_cover_placeholder()
            self.metadata_label.show()
            self.metadata_label.setText(
                f"{book.author} - {book.title}" if book else "Unknown book"
            )

    def _show_cover_placeholder(self):
        t = _resolve_theme(self.theme_manager._current_theme_name)
        color = t.get('placeholder_cover', t.get('library_narrator', t.get('text', '#888888')))
        try:
            logo_path = os.path.join(_ASSETS_DIR, "fabulor.svg")
            with open(logo_path) as f:
                data = f.read()
            data = re.sub(r'fill="(?!none)[^"]*"',     f'fill="{color}"',   data)
            data = re.sub(r'stroke="(?!none)[^"]*"',   f'stroke="{color}"', data)
            data = re.sub(r'(fill:)(?!none)[^;}"]*',   rf'\g<1>{color}',     data)
            data = re.sub(r'(stroke:)(?!none)[^;}"]*', rf'\g<1>{color}',     data)
            ba = QByteArray(data.encode())
            renderer = QSvgRenderer(ba)
            placeholder_size = int(COVER_AREA_HEIGHT * 0.65)
            pm = QPixmap(placeholder_size, placeholder_size)
            pm.fill(Qt.transparent)
            painter = QPainter(pm)
            renderer.render(painter)
            painter.end()
            self.cover_art_label.setPixmap(pm)
            self.cover_art_label.show()
            self._showing_placeholder = True
        except Exception:
            self.cover_art_label.hide()
            self._showing_placeholder = False

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
        if hasattr(self, 'status_banner') and self.status_banner.isVisible():
            anim = getattr(self, '_banner_anim', None)
            if anim and anim.state() == QPropertyAnimation.State.Running:
                self.status_banner.resize(self.width(), 36)
            else:
                self.status_banner.setGeometry(0, self.height() - 36, self.width(), 36)
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
            if self._dialog_close_time.isValid() and self._dialog_close_time.elapsed() < 500:
                return
            # Guard: Only allow sidebar right-click toggle if books are indexed
            if self.db.get_book_count() > 0:
                self.panel_manager.handle_drag_area_right_click(event)

    def toggle_play_pause(self):
        self.panel_manager.hide_all_panels()
        if not self.player:
            return
        
        if self.player.eof_reached or self.play_pause_button.text() == "Restart":
            if not os.path.exists(self.current_file):
                self._update_status_banner_ui(text="Error: File missing!", show_banner=True, auto_hide=True)
                self._mark_book_missing(self.current_file)
                return
            self._dismiss_eof_prompt()
            self.session_recorder.close()
            self.config.set_last_position(self.current_file, 0)
            self.db.update_progress(self.current_file, 0)
            # EOF-restart reloads the same book with no library animation and no
            # switch begin(); phase is IDLE (in_deadzone False) so no deadzone to clear.
            self.player.load_book(self.current_file, start_paused=False)
            self.player.ungate_play()
            return
        else:
            was_paused = self.player.pause
            if was_paused:
                if self.current_file and not os.path.exists(self.current_file):
                    self._update_status_banner_ui(text="Error: File missing!", show_banner=True, auto_hide=True)
                    self._mark_book_missing(self.current_file)
                    return
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
            # No is_seeking set here: seek_async sets is_seeking AND _seek_target
            # together. A redundant unconditional set here strands is_seeking=True
            # with _seek_target=None whenever the seek is a no-op (boundary), which
            # the settle can never clear -> permanent freeze. (Same class as the
            # chapter-list-click fix; see _on_chapter_list_selected.)
            self._trigger_undo(old_pos)

    def handle_prev(self):
        self.panel_manager.hide_all_panels()
        if self.config.get_chapter_hints_mode() == "Transient":
            self._clear_preview()
        if self.player:
            old_pos = self.player.time_pos or 0.0
            target = self.player.previous_chapter()
            # No is_seeking set here: previous_chapter() calls seek_async (which sets
            # is_seeking + _seek_target together) ONLY when it actually seeks. At the
            # chapter[0] boundary it no-ops without seeking; an unconditional is_seeking
            # = True here would then strand the flag (with _seek_target=None) and the
            # settle could never clear it -> permanent chapter-UI freeze (captured
            # 2026-06-15, M4B + VT). Let seek_async own the flag.
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
            # No is_seeking set here (same reason as handle_prev): next_chapter()
            # seeks only when it advances; at the last-chapter boundary it no-ops, and
            # an unconditional is_seeking = True would strand the flag -> freeze.
            if target is not None:
                speed = self.player.speed or 1.0
                if abs(target - old_pos) > 60 * speed:
                    self._trigger_undo(old_pos)

    def _on_chapter_list_selected(self, title, old_pos, force_play):
        # No is_seeking set here: activate_chapter_index -> seek_async (called in
        # _activate_item before this slot fires) already sets is_seeking AND
        # _seek_target, so the chapter-UI guard clears on settle. Setting it here
        # without a _seek_target was the old freeze (native chapter = idx path).
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
        elif self.progress_slider.underMouse():
            if not self.player or not self.current_file:
                return
            if not self.player.chapter_list:
                return  # no chapters — no-op
            delta = event.angleDelta().y()
            if delta > 0:
                self.handle_next()
            else:
                self.handle_prev()
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
                    if chap.get('time', 0) <= current_pos + _CHAPTER_WALK_TOLERANCE:
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
        if hasattr(self, 'eof_revert_btn') and obj is self.eof_revert_btn:
            if event.type() == QEvent.Enter:
                self.eof_revert_btn.set_icons(*self._eof_revert_pixmaps_hover)
            elif event.type() == QEvent.Leave:
                self.eof_revert_btn.set_icons(*self._eof_revert_pixmaps)

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
        self.status_hide_timer.stop()
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

        # Join the flush thread briefly so the close write lands, then clear the
        # checkpoint synchronously — both before event.accept() (the point of no
        # return). The synchronous clear is unconditional: even if the join times
        # out, the checkpoint must not survive into the next startup, or recovery
        # re-writes this session as a duplicate. See session_recorder.clear_checkpoint.
        flush_thread = self.session_recorder.close()
        if flush_thread is not None:
            flush_thread.join(timeout=0.5)
        self.session_recorder.clear_checkpoint()
        event.accept()

    def _validate_smart_rewind_settings(self):
        if self.speed_panel:
            self.speed_panel._validate_smart_rewind_settings()
