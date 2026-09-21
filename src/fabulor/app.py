# THEME_ANIM_TODO: MainWindow, TitleBar, ChapterList, SpeedControlsPanel,
# AudioSettingsTab, SleepTimerPanel, StatsPanel, BookDetailPanel,
# status_banner, sidebar, vol_container
import logging
import os
from datetime import datetime, timedelta
from PySide6.QtWidgets import (
    QFileDialog,
    QWidget, QPushButton, QVBoxLayout, QListWidget, QListWidgetItem,
    QApplication, QGraphicsBlurEffect, QGraphicsOpacityEffect, QLineEdit, QLabel, QSpinBox,
)
from PySide6.QtCore import (
    Qt, QTimer, QPoint, QPointF, QRect, QEvent, QPropertyAnimation, QEasingCurve,
    Signal, QObject, QElapsedTimer, QSize, QVariantAnimation, QThreadPool,
    QItemSelectionModel,
)
from PySide6.QtGui import QPixmap, QColor, QIcon, QPainter, QKeyEvent, QCursor, QHoverEvent

from .player import Player, _CHAPTER_BOUNDARY_EPSILON, _CHAPTER_WALK_TOLERANCE
from .config import Config
from . import themes
from .themes import _resolve_theme, get_player_stylesheet
from .ui.chapter_list import ChapterList # Keep ChapterList here as it's a direct child of MainWindow
from .ui.excluded_books import ExcludedBooksPopup # Same reason — direct child of MainWindow, not nested in the settings tab
from .ui.speed_controls import SpeedControlsPanel
from .ui.sleep_timer import SleepTimerPanel
from .ui.sprint_panel import SprintPanel
from .ui.theme_manager import ThemeManager
import time # For sleep timer
from .library_controller import LibraryController
from .ui.controls import ClickSlider # arrow-key adjustment of a focused settings slider
from .ui.panels import PanelManager # New import for PanelManager
from .ui.visual_area_blur import ClippedBlurEffect
from .ui import scrollbar_jump
from .ui.carousel import CoverCarousel, CAROUSEL_STRIPE_W
from .ui.sidebar_hotspot import SidebarHotspot
from .ui import main_window_builders as builders
from .db import LibraryDB
from .library.scanner import LibraryScanner
from mpv import ShutdownError
from .settings_controller import SettingsController
from .session_recorder import SessionRecorder
from .book_switch import BookSwitchState
from .shortcuts import Action, ShortcutDispatcher

# Shared low-level UI helpers (moved to ui/ui_helpers.py so the extracted
# main_window_builders module can use them without importing app.py).
# Re-imported here so existing references in this module keep working unchanged.
from .ui.ui_helpers import COVER_AREA_HEIGHT, _load_svg_icon, _load_svg_pixmap
from .ui.cover_placeholder import CoverPlaceholder

logger = logging.getLogger(__name__)

# Same gate as transport_bar_blur.py/panels.py's grab/blur/clip trace probes —
# reused here for [SEAM-TRACE] on the carousel's own clip (2026-08-15,
# temporary). One env var covers the whole investigation.
_GRAB_TRACE_ENABLED = os.environ.get("FABULOR_GRAB_TRACE") == "1"

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

# Minimum seconds between held-key (Alt+Up/Down autorepeat) speed steps. Raw OS repeat rate
# would blow past a meaningful speed value in under a second at 0.05 increments, so
# _nudge_speed swallows repeat-sourced calls that arrive faster than this. Single taps are
# never throttled. Hand-tunable by feel — start conservative and adjust after live testing.
_SPEED_NUDGE_THROTTLE_S = 0.12

# Same shape as _SPEED_NUDGE_THROTTLE_S (held-key autorepeat only; single taps never
# throttled — see _nudge_chapter/_nudge_long_skip), but each is its OWN constant, tuned
# separately and NOT derived from _SPEED_NUDGE_THROTTLE_S's value: a chapter-nav or
# long-skip repeat is a whole chapter or a large skip per step, not a small continuous
# adjustment, so blowing through several in under a second is a real problem, not just
# mildly fast — these start meaningfully slower than speed's 0.12s. Hand-tunable by feel;
# adjust independently after live testing.
_CHAPTER_NUDGE_THROTTLE_S = 0.15
_LONG_SKIP_THROTTLE_S = 0.18

# How long after a physical MouseButtonPress a TabFocusReason focus event is still attributed to
# that press rather than to real keyboard navigation — see _update_focus_marker's MODALITY
# OWNERSHIP notes. Qt reports a mouse click ON A TAB as TabFocusReason (measured live 2026-09-03:
# press at 23:03:55,452 -> TabFocusReason FocusIn at 23:03:55,455, a 3ms gap), so the reason alone
# cannot distinguish "user pressed Tab" from "user clicked a tab" and the unambiguous press has to
# win. 0.05s is ~17x the measured gap — comfortably wide for a slow frame, far below any plausible
# press-then-deliberately-Tab interval.
_MOUSE_PRESS_FOCUS_WINDOW_S = 0.05

# Cursor poll driving "the mouse is being used again", which ends keyboard mode and restores
# QSS :hover highlights (see MainWindow._set_keyboard_nav_active). Deliberately much faster than
# PanelManager's 500ms sidebar idle poll: that one backs a 10s deadline where half a second of
# slack is invisible, whereas this one gates a highlight the user expects back the instant they
# move the mouse — 500ms there would read as the hover being broken. Cheap for the same reason
# the sidebar's is (one QCursor.pos() read + a comparison) and, like it, runs only while needed.
_KBDNAV_CURSOR_POLL_MS = 60
# Movement below this many pixels does not count as "the user moved the mouse" — absorbs
# sub-pixel/±1px OS-level cursor jitter, the same concern _MOUSE_JITTER_PX handles for the
# Themes-tab swatch leave check (ui/theme_manager.py).
_KBDNAV_CURSOR_JITTER_PX = 3
# Value step for Left/Right on a keyboard-focused settings slider (Audio's L/R balance, range
# -100..100). 5 gives 40 presses end-to-end — fine-grained enough to land on a deliberate value,
# coarse enough to cross the range without holding the key forever. The slider snaps to centre on
# its own (snap_to_center), so 0 stays easy to hit.
_BALANCE_ARROW_STEP = 5

# Keys that assert keyboard mode on press (see MainWindow.eventFilter's KeyPress branch). The
# keys that MOVE THE SELECTION or ACT ON IT — pressing one means the user is driving with the
# keyboard, whether or not it happens to generate a focus event Qt labels TabFocusReason.
# Return/Enter are included because activating a control is as much "I am using the keyboard" as
# moving between them: without it, pressing Enter while the mouse happened to rest on a control
# would let hover reassert itself mid-interaction.
_KBDNAV_ASSERT_KEYS = frozenset((
    Qt.Key.Key_Tab, Qt.Key.Key_Backtab,
    Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Left, Qt.Key.Key_Right,
    Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space,
))

# Shared dismiss duration for the indicator zone's two transient states: the volume-slider
# preview (vol_hide_timer) and the sleep-just-armed-while-muted confirmation
# (sleep_confirm_timer). Both revert to whatever _settle_vol_stack() resolves to next.
_INDICATOR_DISMISS_MS = 2000


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
    def refresh_excluded_books(self) -> None: self._main._reload_excluded_books()

class BrowserInterface:
    def __init__(self, main):
        self._main = main

    def get_current_folder(self): return self._main._get_current_folder_path()
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

    def restyle_for_backdrop_change(self):
        """One full stylesheet pass, for a panel-backdrop MODE CHANGE only.

        Restyles whatever is ACTUALLY DISPLAYED — get_active_theme() returns a dict
        for a live cover-derived theme, or the pool theme name otherwise. Passing
        _current_theme_name here instead was a real bug (2026-07-28): with cover-art
        mode Exclusive the panel-background setting reverted the app to the pool
        theme, so switching Opaque/Frosty visibly changed the COLOURS. A backdrop
        setting must never change which theme is applied.

        Deliberately separate from set_blur_selection: that one is a visual sync
        called from the settings refresh batch, and a restyle there fires on every
        sync (~250ms each, three per second — it stuttered the panel slide and
        crashed the app, 2026-07-28).

        SCOPED, not a full pass (2026-08-02). This used to call apply_full_pass,
        which rebuilds every stylesheet in the app: measured at ~1040ms per click,
        so the mode button visibly lagged its own selection by a full second. A
        backdrop change only moves the panel alpha and sets no colours, so
        apply_panel_alpha_pass restyles just the five surfaces that actually read
        panel_opacity_hover — see its docstring for the verification method and for
        why mw.setStyleSheet(base) (482ms of that 1040ms) is provably redundant
        here."""
        tm = getattr(self._main, 'theme_manager', None)
        if tm is not None:
            tm.apply_panel_alpha_pass(tm.get_active_theme())

    def set_blur_selection(self, mode):
        """Paint the panel-backdrop button states. Panel backdrop is
        "transparent" | "frosty" | "opaque" (2026-07-28; this used to take a bool).

        VISUAL SYNC ONLY — no restyle here. This is called from the settings
        visual-refresh batch (see _finish_startup and sync_all_settings_visuals),
        not just on a mode change, so anything expensive in here runs on every
        sync. An earlier version of this method called apply_full_pass, which made
        every refresh a ~250ms blocking restyle: measured at three per second,
        ~75% of the main thread, which made the settings panel slide visibly stutter
        and then took the app down. The restyle belongs on the mode-change path
        only — see SettingsController._update_panel_backdrop.
        """
        m = self._main
        if hasattr(m, 'blur_buttons'):
            for state, btn in m.blur_buttons.items():
                btn.setProperty("selected", "true" if state == mode else "false")
                btn.style().unpolish(btn)
                btn.style().polish(btn)
        if mode != "frosty":
            m.blur_effect.setBlurRadius(0)
            # Drop any stale clip too, so a later re-enable starts clean.
            if m.panel_manager is not None:
                m.panel_manager._clear_visual_area_clip()

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

    def set_sidebar_hotspot_selection(self, enabled):
        m = self._main
        if hasattr(m, 'hotspot_enabled_buttons'):
            for mode, btn in m.hotspot_enabled_buttons.items():
                is_selected = (mode == "On" if enabled else mode == "Off")
                btn.setProperty("selected", "true" if is_selected else "false")
                btn.style().unpolish(btn)
                btn.style().polish(btn)

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

    def set_keyboard_marker_style_selection(self, style):
        m = self._main
        if not hasattr(m, 'keyboard_marker_style_buttons'): return
        for st, btn in m.keyboard_marker_style_buttons.items():
            btn.setProperty("selected", "true" if st == style else "false")
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
    def __init__(self, speed_panel, sleep_panel, sprint_panel, audio_tab, main):
        self._speed = speed_panel
        self._sleep = sleep_panel
        self._sprint = sprint_panel
        self._audio = audio_tab
        # panel_manager is created AFTER this interface (see _setup_ui ordering),
        # so hold `main` and read main.panel_manager lazily at call time.
        self._main = main
    def validate_speed_panel_settings(self):
        if self._speed: self._speed._validate_smart_rewind_settings(finalize=True)
    def update_speed_panel_visuals(self, theme_name=None):
        # Theme-apply path only, via sync_all_settings_visuals -> here. Calls the
        # narrow ramp-only method, not the full update_visuals() -- a theme change
        # never changes which preset/step/undo/etc. is selected, so update_visuals()'s
        # property-sync half would be redundant work here. See
        # _apply_preset_ramp_colors' docstring and
        # review/Investigation_260803_c4c5_dispatcher_isolation.md.
        if self._speed: self._speed._apply_preset_ramp_colors()
    def update_sleep_panel_visuals(self):
        # Theme-apply path only -- see update_speed_panel_visuals' comment above,
        # same reasoning applies to Sleep's _apply_preset_ramp_colors.
        if self._sleep: self._sleep._apply_preset_ramp_colors()
    def update_sprint_panel_visuals(self):
        # Theme-apply path only -- same reasoning as update_sleep_panel_visuals.
        if self._sprint: self._sprint._apply_preset_ramp_colors()
    def update_audio_panel_visuals(self):
        if self._audio: self._audio.update_visuals()
    def apply_blur_live(self, enabled):
        pm = getattr(self._main, 'panel_manager', None)
        if pm: pm.apply_blur_live(enabled)


class UICallbackInterface:
    def __init__(self, main):
        self._main = main
    def set_folder_list(self, folders): self._main._update_folder_list_widget(folders)
    def open_folder_dialog(self): return self._main._get_new_folder_path()
    def update_status_banner(self, *a, **kw): self._main._update_status_banner_ui(*a, **kw)
    def update_metadata(self, *a, **kw): self._main._update_metadata_ui(*a, **kw)
    def set_chapter_title(self, text): self._main._update_chapter_title_text(text)
    def refresh_notches(self, skip_animation=False): self._main._refresh_notches(skip_animation=skip_animation)
    def get_book_quote(self): return self._main.book_quotes if hasattr(self._main, 'book_quotes') else None
    def clear_focus_marker(self):
        marker = getattr(self._main, 'focus_marker', None)
        if marker is not None:
            marker.clear()
    def refresh_kbdnav_style_property(self):
        self._main.refresh_kbdnav_style_property()
    def clear_all_kbdnav_fill_active(self):
        self._main.clear_all_kbdnav_fill_active()


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


# Sentinel for _pending_cover_pixmap, distinguishing "revert to pool theme is pending"
# (_show_no_cover_state's book-switch case) from "apply this cover's theme is pending"
# (a real QPixmap) and "nothing pending" (None). A plain object() so `is` comparisons
# are unambiguous — never compares equal to None, a QPixmap, or anything else.
_PENDING_CLEAR_COVER_THEME = object()


class MainWindow(QWidget):  # QWidget, not QMainWindow
    naming_pattern_changed = Signal(str)
    scroll_mode_changed = Signal(str)
    hints_mode_changed = Signal(str)
    notches_mode_changed = Signal(bool)
    notch_animation_mode_changed = Signal(bool)
    undo_mode_changed = Signal(int)
    fade_mode_changed = Signal(int)
    blur_mode_changed = Signal(bool)          # legacy; kept for any external caller
    panel_backdrop_changed = Signal(str)      # "transparent" | "frosty" | "opaque"
    hover_fade_changed = Signal(str)
    chapter_digit_mode_changed = Signal(str)
    chapter_digit_autoplay_changed = Signal(bool)
    chapter_list_source_changed = Signal(str)
    sidebar_hotspot_enabled_changed = Signal(bool)
    keyboard_marker_style_changed = Signal(str)  # "traveling" | "fill_highlight"

    def __init__(self, parent=None):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.current_cover_pixmap = QPixmap()
        self._pending_cover_pixmap = None
        self._cover_fit_mode = 'fit'
        self._cover_placeholder = CoverPlaceholder()
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
        # Volume before a keyboard mute (m); None = not muted. Any manual move off 0 while
        # "muted" is treated as unmuted, so the next m stores fresh (see _toggle_mute).
        self._pre_mute_volume = None
        # True for a brief window right after the sleep timer is (re)armed while muted —
        # lets the sleep text show as a confirmation before reverting to the mute icon.
        # See _on_sleep_display_text_updated / _settle_vol_stack / sleep_confirm_timer.
        self._sleep_just_set = False
        # Same shape as _sleep_just_set, for sprint's own arm-while-muted confirmation.
        # See _on_sprint_display_text_updated / _settle_vol_stack / sprint_confirm_timer.
        self._sprint_just_set = False
        # monotonic() of the last applied speed nudge, for throttling Alt+Up/Down autorepeat.
        self._last_speed_nudge_ts = 0.0
        # Same shape as _last_speed_nudge_ts, one per throttled action (chapter-nav and
        # long-skip each self-throttle independently — see _nudge_chapter/_nudge_long_skip).
        self._last_chapter_nudge_ts = 0.0
        self._last_long_skip_nudge_ts = 0.0
        self._undo_timer = QTimer(self)
        self._last_saved_pct = -1
        self._last_saved_pos = 0.0
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
        # Book-load deferred-restyle flush: when the flow animation completes, run any
        # pending invisible-surface theme batch (ThemeManager._run_deferred_restyle
        # defers itself while this animation is Running, so this is where a book-load
        # batch actually lands — AFTER the animation, never freezing it). Separate
        # connection from _resume_ui_timer above; no when_animations_done slot contention.
        self.progress_slider._flow_anim.finished.connect(
            self.theme_manager._run_deferred_restyle,
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
        self.folder_list_widget.itemSelectionChanged.connect(self._update_remove_folder_btn_enabled)
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
        self.undo_overlay.setFocusPolicy(Qt.NoFocus)  # chrome button — keep out of the focus chain
        self.undo_overlay.hide()
        self.undo_overlay.clicked.connect(self._perform_undo)
        self.undo_anim = QPropertyAnimation(self.undo_overlay, b"pos")
        self.undo_anim.setDuration(400)
        self.undo_anim.setEasingCurve(QEasingCurve.OutCubic)
        self.undo_anim.finished.connect(self._on_undo_anim_finished)

        # Dedupe set for the [RCLICK] delivery probe in eventFilter.
        self._rclick_seen = set()
        self._rclick_n = 0

        QApplication.instance().installEventFilter(self)

        # Right-click any scrollbar gutter to jump the handle there, replacing
        # the native style's system-themed context menu. Application-wide rather
        # than per-widget: scrollbars here come from QScrollArea/QListWidget/
        # QListView/QComboBox popups, several created internally by Qt with no
        # construction site to patch. See ui/scrollbar_jump.py.
        scrollbar_jump.install(QApplication.instance())

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
        # Populate the library model from already-known DB state on startup, decoupled
        # from both the (now scan-gated) launch scan and from the panel's own open event.
        # Previously, library_panel.refresh() only ever fired as a side effect of a panel
        # open (panels.py:_on_library_shown) or a scan completing (_on_scan_finished) — so
        # once scan-on-launch was correctly removed (see handle_background_tasks), the
        # FIRST library open after a fresh launch showed a real empty-then-populate flash
        # (confirmed live, 2026-07-17): the model was still empty because nothing had ever
        # populated it. Calling refresh() synchronously ON panel-open was tried and
        # rejected — it stutters the panel's own slide-in animation. The fix is neither
        # "scan on launch" nor "refresh on open": refresh() already reads directly from the
        # DB (self.db.get_all_books()) — it does not need a scan to have run. Queuing it
        # here, one event-loop turn after startup via singleShot(0), keeps it off the
        # book-load flow-animation's critical path (the STUTTER-PROBE-monitored window)
        # while ensuring _book_model/_filtered are populated well before the user can
        # possibly open the library panel. _load_visible_covers (called at the end of
        # refresh()) no-ops while the panel is hidden (isVisible() guard), so no cover
        # I/O is wasted — covers still dispatch for real on the panel's actual first open.
        QTimer.singleShot(0, self.library_panel.refresh)
        self.ui_timer.start(200)

        # Wire SettingsController with explicit, minimal interfaces (defined at module level).
        visuals = VisualsInterface(self)
        panels = PanelInterface(self.speed_panel, self.sleep_panel, self.sprint_panel, self.audio_tab, self)
        ui_callbacks = UICallbackInterface(self)
        library = LibraryInterface(self.db, self.library_panel)
        player = PlayerInterface(self)
        self.settings_controller = SettingsController(self.config, visuals, panels, ui_callbacks, library, player)

        self.settings_controller.bind_mainwindow_handlers(self)

        # Global MainWindow key bindings (C / T / Q, + L). The dispatcher owns the
        # spam-guard timing (T's leading-fire-then-coalesce cooldown used to live here
        # as _theme_rotate_cooldown/_theme_rotate_pending); each handler still owns its
        # own app-state gating. See shortcuts.py and KEYBINDINGS.md.
        self.shortcuts = ShortcutDispatcher(self)
        self.shortcuts.register(Action.OPEN_CHAPTER_LIST, self._show_chapter_dropdown)
        self.shortcuts.register(Action.TOGGLE_THEME, self.theme_manager._rotate_theme)
        self.shortcuts.register(Action.ROTATE_QUOTE, self._rotate_quote_shortcut)
        self.shortcuts.register(Action.SHOW_LIBRARY, self._open_library_shortcut)
        self.shortcuts.register(Action.SHOW_TAGS, self._open_tags_shortcut)
        self.shortcuts.register(Action.SHOW_PLAYBACK, self._open_playback_shortcut)
        self.shortcuts.register(Action.SHOW_STATS, self._open_stats_shortcut)
        self.shortcuts.register(Action.SHOW_SETTINGS, self._open_settings_shortcut)
        self.shortcuts.register(Action.SHOW_SLEEP, self._open_sleep_shortcut)
        self.shortcuts.register(Action.SHOW_SPRINT, self._open_sprint_shortcut)
        # Transport / player keys. Each wires to the SAME method the on-screen button or
        # wheel uses (no reimplemented playback logic); volume/speed share the extracted
        # _nudge_* step helpers with wheelEvent. App-state gating lives in the handlers.
        self.shortcuts.register(Action.PLAY_PAUSE, self.toggle_play_pause)
        self.shortcuts.register(Action.VOLUME_UP, lambda: self._nudge_volume(1))
        self.shortcuts.register(Action.VOLUME_DOWN, lambda: self._nudge_volume(-1))
        self.shortcuts.register(Action.SEEK_BACK, lambda: self.handle_rewind(long_skip=False))
        self.shortcuts.register(Action.SEEK_FORWARD, lambda: self.handle_forward(long_skip=False))
        self.shortcuts.register(Action.LONG_SKIP_BACK, lambda: self._nudge_long_skip(-1))
        self.shortcuts.register(Action.LONG_SKIP_FORWARD, lambda: self._nudge_long_skip(1))
        self.shortcuts.register(Action.CHAPTER_PREV, lambda: self._nudge_chapter(-1))
        self.shortcuts.register(Action.CHAPTER_NEXT, lambda: self._nudge_chapter(1))
        self.shortcuts.register(Action.SPEED_UP, lambda: self._nudge_speed(1))
        self.shortcuts.register(Action.SPEED_DOWN, lambda: self._nudge_speed(-1))
        self.shortcuts.register(Action.MUTE, self._toggle_mute)
        self.shortcuts.register(Action.UNDO, self._undo_shortcut)

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
        # Traveling-border-marker keyboard-focus indicator (ui/focus_marker.py). Wired for the
        # Settings panel's Look tab only this pass; driven from the app-wide eventFilter's
        # FocusIn/FocusOut branch via _update_focus_marker().
        from .ui.focus_marker import TravelingFocusMarker
        self.focus_marker = TravelingFocusMarker(self)
        # Input-modality flag: True while the last real input was keyboard navigation, False
        # after a mouse click. Read as the marker's show-gate in _update_focus_marker. The marker
        # is a keyboard affordance — a mouse click must hide it rather than re-anchor it to
        # whatever was clicked.
        self._keyboard_nav_active: bool = False
        # The ClickSlider currently painting its "fill highlight" brightened background
        # (fill_highlight keyboard-nav style only), or None. Tracked so _update_focus_marker
        # can clear the PREVIOUS slider when focus moves elsewhere — only one slider can be
        # kbd_fill_active at a time app-wide, since only one widget holds real Qt focus.
        self._kbd_fill_slider: "ClickSlider | None" = None
        # perf_counter() of the last MouseButtonPress the app-wide eventFilter saw, or None.
        # _update_focus_marker uses it to reject a TabFocusReason that is really just the focus
        # change a mouse click on the tab bar produced — see _MOUSE_PRESS_FOCUS_WINDOW_S and
        # that method's MODALITY OWNERSHIP notes.
        self._last_mouse_press_t: float | None = None
        # Cursor position sampled when keyboard mode was entered, and the poll that watches it.
        # While the keyboard is driving, QSS :hover highlights are suppressed (see
        # _set_keyboard_nav_active) so only ONE affordance answers "where am I?" at a time; the
        # first real cursor movement hands the UI back to the mouse.
        #
        # A POLL, not a QEvent.MouseMove filter branch: Qt only GENERATES MouseMove for widgets
        # with setMouseTracking(True), which almost nothing in this app sets, so a move-event
        # listener would silently never fire for ordinary cursor motion. This is the same trap
        # (and the same QCursor.pos() workaround) documented for the sidebar hotspot's idle
        # dismiss — see PanelManager._sidebar_idle_poll_timer. Runs ONLY while suppression is
        # active, and stops the moment the mouse takes over.
        self._kbdnav_cursor_anchor = None
        self._kbdnav_cursor_poll = QTimer(self)
        self._kbdnav_cursor_poll.setInterval(_KBDNAV_CURSOR_POLL_MS)
        self._kbdnav_cursor_poll.timeout.connect(self._on_kbdnav_cursor_poll)
        # SEPARATE from _kbdnav_cursor_anchor above — do not merge these (2026-09-15,
        # found live after two failed attempts assumed they could share one anchor).
        # _kbdnav_cursor_anchor answers "where was the mouse when keyboard mode BEGAN"
        # and is deliberately fixed for the FULL duration of a keyboard-nav session
        # (only _set_keyboard_nav_active's False->True transition writes it) — that is
        # exactly what makes _on_kbdnav_cursor_poll's hand-back check work at all.
        # Hover-PICKUP needs a different question answered: "has the mouse moved since
        # the LAST time pickup was checked" — and _set_keyboard_nav_active(True) fires
        # on EVERY qualifying keypress (it only SKIPS the anchor write when already
        # active, but still runs unconditionally before _handle_settings_arrows/
        # _handle_flat_panel_arrows/_handle_stats_arrows on every press). On the very
        # FIRST arrow press after a panel opens, _keyboard_nav_active is False, so that
        # call IS the active==False->True transition and overwrites _kbdnav_cursor_
        # anchor to the CURRENT cursor position one line before _pickup_hover_target
        # ever runs — silently erasing the exact "mouse moved before this press" signal
        # pickup needs, on precisely the press it needs it most. This stranded a
        # from-scratch _claim_panel_focus stamp the same way (confirmed live:
        # "Yet to pick up from the mouse... in the settings buttons" persisted even
        # after that fix). _pickup_cursor_anchor is stamped ONLY by _claim_panel_focus
        # (panel-open baseline) and by _pickup_hover_target itself after a successful
        # pickup (so the NEXT check is "moved since the last pickup", not "moved since
        # panel open" forever) — _set_keyboard_nav_active never touches it.
        self._pickup_cursor_anchor = None
        # Themes-tab rotation-interval digit shortcut buffer — see _handle_themes_shortcuts.
        # Mirrors ChapterList's own digit-jump debounce (chapter_list.py) exactly: 800ms
        # single-shot, restarted on every digit, buffer read and cleared only when it fires.
        self._themes_digit_buffer = ""
        self._themes_digit_timer = QTimer(self)
        self._themes_digit_timer.setSingleShot(True)
        self._themes_digit_timer.setInterval(800)
        self._themes_digit_timer.timeout.connect(self._commit_themes_digit_buffer)
        # Switching settings tabs keeps focus ON the tab bar (no FocusIn/FocusOut fires), so
        # re-evaluate marker scope on tab change: leaving Look clears it, and landing on Look
        # while the tab bar is focused re-anchors the marker to Look's tab rect.
        if hasattr(self, 'tabs'):
            self.tabs.currentChanged.connect(lambda _idx: self._update_focus_marker())
        # Same wiring for Stats' own QTabWidget, added 2026-09-09 — missed when Stats joined
        # the keyboard-nav system (2026-09-08): without it, Left/Right on Stats' tab bar moves
        # currentIndex() but produces no FocusIn/FocusOut (the tab bar itself never loses real
        # Qt focus), so _update_focus_marker was never re-triggered — reported live as the
        # marker only ever showing on "⚙" (wherever it happened to be from the last GENUINE
        # focus transition, e.g. Tab/arrow-Up into the tab bar from its content) and visibly
        # continuing to animate on a tab already navigated away from.
        if hasattr(self, 'stats_panel'):
            self.stats_panel.tabs.currentChanged.connect(lambda _idx: self._update_focus_marker())
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
        self.sleep_panel = SleepTimerPanel(self.player, self.config, self.theme_manager, self,
                                            dismiss_ms=_INDICATOR_DISMISS_MS)
        self.sleep_panel.hide()
        self.sleep_panel_animation = QPropertyAnimation(self.sleep_panel, b"pos")
        self.sleep_panel_animation.setDuration(300)
        self.sleep_panel_animation.setEasingCurve(QEasingCurve.OutCubic)

        self.sprint_panel = SprintPanel(self.player, self.config, self.theme_manager, self,
                                         dismiss_ms=_INDICATOR_DISMISS_MS)
        self.sprint_panel.hide()
        self.sprint_panel_animation = QPropertyAnimation(self.sprint_panel, b"pos")
        self.sprint_panel_animation.setDuration(300)
        self.sprint_panel_animation.setEasingCurve(QEasingCurve.OutCubic)

        self.sleep_panel.set_arm_gate(self._sleep_arm_gate)
        self.sprint_panel.set_arm_gate(self._sprint_arm_gate)

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

        # Corner-hotspot sidebar trigger (review/Plan_260809_corner_hotspot_sidebar_trigger.md).
        # Parented to MainWindow, not visual_area — sidebar.y() is in MainWindow-local
        # coordinates (sidebar is also a direct MainWindow child), and visual_area's own
        # local origin sits 10px lower (content_layout's margin), which would put a
        # visual_area-local y derived from sidebar.y() off the top of visual_area entirely
        # (confirmed live: sidebar.y()=56, visual_area's own top=66 in mw-local coords).
        # Parenting here instead keeps the coordinate space identical to sidebar's own, so
        # x=0 sits flush with the sidebar's own left edge and no cross-space translation is
        # needed. y is read from mw.sidebar.y() itself (not hardcoded) so the two stay
        # coupled if that value ever changes.
        self.sidebar_hotspot = SidebarHotspot(
            self.config, on_fire=self._on_sidebar_hotspot_fired, parent=self
        )
        self.sidebar_hotspot.move(0, self.sidebar.y())
        self.sidebar_hotspot.show()
        self.sidebar_hotspot.raise_()

        builders.build_library_panel(self)
        builders.build_settings_panel(self)
        # Parented to library_tab (the tab PAGE, not MainWindow) so it moves
        # with the settings panel for free when it slides, and is
        # automatically clipped/hidden by Qt when another tab becomes
        # current — no manual position-tracking or tab-change guards needed.
        # Must be constructed after build_settings_panel, since library_tab
        # doesn't exist until then. Absolutely positioned within the page via
        # setGeometry (see ExcludedBooksPopup.reposition), never added to the
        # tab's own QVBoxLayout — that's what avoids the original rendering
        # wall (see excluded_books.py's module docstring / NOTES.md).
        self.excluded_books_popup = ExcludedBooksPopup(self.library_tab)
        self.excluded_books_popup.restore_requested.connect(self._on_excluded_book_restored)
        self.excluded_books_popup.expand_toggle_requested.connect(self._on_excluded_toggle_clicked)
        self.excluded_books_popup.exit_upward_requested.connect(self._on_excluded_books_exit_upward)
        self.excluded_books_popup.collapse_requested.connect(self._collapse_excluded_books)
        # The arrow QLabel is parented to library_tab too (not
        # excluded_books_section) so it can travel above the section's own
        # row bounds without being clipped — see ExcludedBooksSection's
        # set_arrow_parent() docstring.
        self.excluded_books_section.set_arrow_parent(self.library_tab)
        self._library_tab_shown_once = False  # see eventFilter's Show-event hook

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

        # Pulse Animation for active sprint — mirrors sleep's exactly.
        self.sprint_opacity_effect = QGraphicsOpacityEffect(self.sprint_trigger_btn)
        self.sprint_opacity_effect.setOpacity(1.0)
        self.sprint_trigger_btn.setGraphicsEffect(self.sprint_opacity_effect)
        self.sprint_pulse_anim = QPropertyAnimation(self.sprint_opacity_effect, b"opacity")
        self.sprint_pulse_anim.setDuration(4000)
        self.sprint_pulse_anim.setStartValue(1.0)
        self.sprint_pulse_anim.setKeyValueAt(0.5, 0.4)
        self.sprint_pulse_anim.setEndValue(1.0)
        self.sprint_pulse_anim.setLoopCount(-1)
        self.sprint_pulse_anim.setEasingCurve(QEasingCurve.InOutSine)

        # Grace-exhaustion warning pulsation on the indicator label itself
        # (sleep_timer_label / vol_stack page 0) — distinct animation from
        # sprint_pulse_anim above (that one pulses the sidebar trigger button
        # while ANY sprint is active; this one pulses the shared indicator text
        # only in the last 3s of grace while paused). sleep_timer_label had no
        # QGraphicsOpacityEffect before this — confirmed no conflict with
        # vol_opacity/vol_fade_anim, which target volume_slider, a different
        # widget entirely. Faster/shallower than the sidebar pulse (1500ms,
        # dips to 0.3 vs 4000ms/0.4) — deliberately more urgent, matching an
        # imminent-cancellation warning rather than a general "active" pulse.
        self.grace_warn_opacity_effect = QGraphicsOpacityEffect(self.sleep_timer_label)
        self.grace_warn_opacity_effect.setOpacity(1.0)
        self.sleep_timer_label.setGraphicsEffect(self.grace_warn_opacity_effect)
        self.grace_warn_anim = QPropertyAnimation(self.grace_warn_opacity_effect, b"opacity")
        self.grace_warn_anim.setDuration(1500)
        self.grace_warn_anim.setKeyValueAt(0.0, 1.0)
        self.grace_warn_anim.setKeyValueAt(0.5, 0.3)
        self.grace_warn_anim.setKeyValueAt(1.0, 1.0)
        self.grace_warn_anim.setLoopCount(-1)
        self.grace_warn_anim.setEasingCurve(QEasingCurve.InOutSine)

        # Speed/grid visual initialization moved to after SettingsController binding

        # Initialize Blur Effect for background depth.
        # ClippedBlurEffect (not a plain QGraphicsBlurEffect) so the blur can be
        # confined to the region an open panel actually occludes — the sliver
        # beside the panel stays sharp. A null clip (the resting state) draws the
        # source through unblurred, so this is safe to leave permanently
        # attached. PanelManager owns the clip rect; see ui/visual_area_blur.py
        # for why this is a paint-time mask and NOT a grab-based overlay.
        self.blur_effect = ClippedBlurEffect(self.visual_area)
        self.blur_effect.setBlurHints(QGraphicsBlurEffect.AnimationHint)
        self.blur_effect.setBlurRadius(0)
        self.visual_area.setGraphicsEffect(self.blur_effect)

        self.blur_animation = QPropertyAnimation(self.blur_effect, b"blurRadius")
        # Duration/curve are tuned against TransportBarBlurOverlay's own fade-in
        # (_FADE_IN_MS = 1500, ui/transport_bar_blur.py) so the cover area and the
        # transport bar blur in together rather than at visibly different rates.
        #
        # Was 500ms/OutCubic and read as an abrupt snap once the blur was moved to
        # start at slide-finished (2026-07-27): OutCubic front-loads hard —
        # measured 58% of the radius applied by 25% of the animation and 88% by
        # halfway — so at 500ms the whole visible change happened in roughly the
        # first 150ms. That is most noticeable on the cover art, which is exactly
        # where the eye already is. InOutQuad eases in gently instead (2% at 10%,
        # 12% at 25%) so the blur builds rather than snapping.
        self.blur_animation.setDuration(1500)
        self.blur_animation.setEasingCurve(QEasingCurve.InOutQuad)
        # Drive the carousel's own effect from the same animation. The carousel
        # is a SIBLING of visual_area (see _show_carousel) so it is not covered
        # by blur_effect; without this it stays sharp while everything around it
        # blurs. No-op whenever no carousel exists.
        self.blur_animation.valueChanged.connect(
            lambda v: self._sync_carousel_radius(v)
        )
        
        # Initialize PanelManager after all relevant widgets are created
        self.panel_manager = PanelManager(self)
        builders.build_book_detail_panel(self)
        self.stats_panel.set_panel_manager(self.panel_manager)

        # Connect Sleep Timer signals after panel_manager is initialized
        self.sleep_panel.timer_started.connect(self._on_sleep_timer_started)
        self.sleep_panel.timer_stopped.connect(self._on_sleep_timer_stopped)
        self.sleep_panel.timer_expired.connect(self._on_sleep_timer_expired)
        self.sleep_panel.display_text_updated.connect(self._on_sleep_display_text_updated)
        self.sleep_panel.timer_started.connect(self.panel_manager._close_sleep_flow)
        # Connect Sprint signals — mirrors the sleep block above exactly, including the
        # panel-close-on-arm connection (armed sprint should close its own panel just
        # like an armed sleep timer does).
        self.sprint_panel.sprint_started.connect(self._on_sprint_started)
        self.sprint_panel.sprint_stopped.connect(self._on_sprint_stopped)
        self.sprint_panel.sprint_expired.connect(self._on_sprint_expired)
        self.sprint_panel.display_text_updated.connect(self._on_sprint_display_text_updated)
        self.sprint_panel.grace_warning_changed.connect(self._on_sprint_grace_warning)
        self.sprint_panel.reset_sprint_stats_requested.connect(self._on_reset_sprint_stats_requested)
        self.sprint_panel.sprint_started.connect(self.panel_manager._close_sprint_flow)
        # Delegate speed display update to a dedicated slot to ensure reliability
        self.speed_panel.speed_changed.connect(self._on_player_speed_changed)
        self.speed_panel.skip_duration_changed.connect(lambda _: self._update_skip_icons())
        self.speed_panel.close_requested.connect(
            lambda: self.panel_manager._close_speed_flow() if self.panel_manager else None
        )
        self.library_panel.back_requested.connect(self.panel_manager._close_library_flow)

        # Apply the saved panel-backdrop alpha BEFORE the first full stylesheet pass
        # below, or an "opaque" setting would not take effect until the user next
        # touched the control. _resolve_theme reads this while building every sheet.
        themes.set_panel_alpha_override(self.config.get_panel_alpha_override())
        self.theme_manager.apply_full_pass(self.theme_manager._current_theme_name)
        self._settle_vol_stack()

        # Idle cover preloader: do NOT run at app start (startup work interferes with the
        # cover-art flow animation). Instead ARM the idle-detection machinery once, here —
        # this only starts the 5s idle timer; it does not itself run a preload. The first
        # preload run happens only after 5s of genuine no-interaction (the eventFilter
        # resets this timer on every mouse/key event), identical to every subsequent
        # resume-after-inactivity cycle. A user who opens the library as their very first
        # action after launch therefore sees today's behavior — no preloader contention —
        # until the app has actually been idle for 5s.
        self._arm_preload_idle()

    def _arm_preload_idle(self):
        """(Re)start the 5s idle timer that eventually triggers start_idle_preload. Called
        once after startup to arm the machinery, and again from the eventFilter on every
        user interaction so the first (and every) preload run only fires after 5s of
        genuine inactivity. Idempotent: restarting a running single-shot timer just resets
        its countdown."""
        if not hasattr(self, '_preload_restart_timer'):
            self._preload_restart_timer = QTimer(self)
            self._preload_restart_timer.setSingleShot(True)
            self._preload_restart_timer.timeout.connect(self.library_panel.start_idle_preload)
        self._preload_restart_timer.start(5000)

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

    def _reload_excluded_books(self):
        """Recheck the excluded-book set and rebuild the list's contents plus
        the toggle line's count/arrow state. Called on each settings-panel
        open. Always collapses back to the default view first — the count or
        the rows themselves may have changed (e.g. a rescan flagged more
        books missing since this was last open), so any previous expanded
        state is stale."""
        if not hasattr(self, 'excluded_books_section'):
            return
        self.excluded_books_popup.set_expanded(False)
        self.excluded_books_section.set_expanded(False)
        # get_committed_theme() (2026-08-04, write-path confinement fix — see
        # review/Design_260804_write_path_confinement.md), NOT
        # get_current_theme(). This popup lives on Settings' Library tab,
        # invisible whenever the Themes tab (the only place a hover can be
        # live) is the one showing — mutually exclusive tabs within the same
        # panel, same reasoning as the cross-panel exclusion in CLAUDE.md.
        theme = self.theme_manager.get_committed_theme()
        theme = _resolve_theme(theme)
        self.excluded_books_section.set_theme(theme)
        self.excluded_books_popup.set_theme(theme)
        books = self.db.get_excluded_books()
        self.excluded_books_popup.reload(books)
        self.excluded_books_section.set_count(len(books))
        self.excluded_books_section.set_expandable(self.excluded_books_popup.is_expandable)
        # Positioned relative to library_tab (its own parent now, not
        # MainWindow) — meaningful regardless of which settings tab happens
        # to be current, since Qt clips/hides it automatically if Library
        # isn't the visible page. No tab-text guard needed anymore.
        #
        # On the VERY FIRST Settings open in a session, library_tab has never
        # been shown before (built at startup, stays hidden in the QTabWidget
        # until now) — querying its/the section's geometry here, before Qt's
        # first real layout pass on the now-visible page, is unreliable
        # (confirmed live: invisible + badly mispositioned on the first open
        # only). That first-open case is handled by eventFilter's one-shot
        # hook on library_tab's Show event instead — skip this call here so
        # it isn't done twice.
        if self._library_tab_shown_once:
            # set_count() above can flip excluded_books_section from
            # hidden to visible (count was 0 before this call) — Qt does
            # not guarantee the section's height() reflects its final
            # laid-out size immediately after setVisible(True) returns;
            # the real layout pass can land on a LATER event-loop tick.
            # reposition() reads anchor_widget.height() synchronously right
            # after this, so without forcing the pending layout to resolve
            # first, it can compute geometry from a stale/zero height —
            # confirmed live (2026-06-28): the box stayed invisible despite
            # a correct count, and in a worse case (6 books) the arrow
            # stayed clickable and expanding grew the list DOWNWARD with
            # the arrow moving UP — both directions inverted, consistent
            # with _anchor_bottom being computed from garbage geometry.
            self.library_tab.layout().activate()
            self.excluded_books_popup.reposition(self.excluded_books_section, self.library_tab)

    def _on_excluded_toggle_clicked(self):
        """Arrow click — toggles between the default and expanded row count.
        The list itself is always visible (when count > 0); this only
        changes how many rows are shown, never show/hide."""
        expanded = not self.excluded_books_popup.is_expanded
        self.excluded_books_popup.set_expanded(expanded)
        self.excluded_books_section.set_expanded(self.excluded_books_popup.is_expanded)
        # Mouse-driven expand can cover Persist search filter's row while a PSF button already
        # holds keyboard focus (no FocusIn fires here at all — focus doesn't move, only the
        # box's geometry does), which the FocusIn-based redirect in eventFilter cannot see.
        # Same fix, same reasoning, different trigger — see that branch's own comment. Only
        # relevant for the expand direction; collapsing never covers anything new.
        if expanded:
            focus = QApplication.focusWidget()
            psf_buttons = (set(self.persist_filter_buttons.values())
                           | set(self.persist_filter_sub_buttons.values()))
            if focus in psf_buttons:
                self.excluded_books_popup.setFocus(Qt.FocusReason.OtherFocusReason)

    def _on_excluded_books_exit_upward(self):
        """Up at row 0 of the Excluded Books popup — collapses it if expanded (so its footprint
        never overlaps whatever focus lands on above it — a live design pass 2026-09-05 settled
        on exit ALWAYS succeeding with collapse as a side effect, not "must collapse before you
        may leave") and moves focus back to Persist search filter's row, the row directly above
        it in the Library tab (the mirror of how _handle_settings_arrows entered the popup in
        the first place: Down/Right from that exact row — see the entry logic there). Lands on
        the row's FIRST button, matching every other row-to-row Up (`from_below=True` is for a
        list box's own last-item convention, which doesn't apply to a plain button row)."""
        self._collapse_excluded_books()
        rows = self.panel_manager.settings_tab_button_rows()
        if rows:
            self._focus_settings_control(rows[-1][0])

    def _collapse_excluded_books(self):
        """Collapse back to the default view without hiding the list —
        used for outside-clicks and panel-close, which used to dismiss the
        popup entirely but now just end an expanded view."""
        if self.excluded_books_popup.is_expanded:
            self.excluded_books_popup.set_expanded(False)
            self.excluded_books_section.set_expanded(False)

    def _on_excluded_book_restored(self, path: str):
        """Restore a user-excluded book (is_excluded=0) and refresh every view
        the same way a rescan completion would."""
        self.db.set_book_excluded(path, False)
        self.library_panel.refresh(force=True)
        self.book_detail_panel._refresh_stats()
        self.stats_panel.refresh_current_tab()
        self.tags_panel.refresh_books()
        # The popup already animated the row out itself and decremented its
        # own _book_count immediately (see ExcludedBooksPopup._on_row_restore
        # — NOT self.count(), which is stale-by-one until the slide-out
        # animation finishes removing the item). Just keep the toggle line's
        # count/arrow state in sync and reposition; reposition() hides the
        # list entirely once the count hits 0.
        is_expandable = self.excluded_books_popup.is_expandable
        # If the count dropped to <= DEFAULT_VISIBLE_ROWS, force the popup's
        # own _expanded flag back to False too — its internal state would
        # otherwise stay stuck expanded (nothing else clears it in time), so
        # reposition() below would still size to MAX_EXPANDED_ROWS even
        # though the section's arrow has already flipped to collapsed.
        if not is_expandable:
            self.excluded_books_popup.set_expanded(False)
        self.excluded_books_section.set_count(self.excluded_books_popup.book_count)
        self.excluded_books_section.set_expandable(is_expandable)
        self.excluded_books_section.set_expanded(self.excluded_books_popup.is_expanded)
        # Restoring the LAST excluded book drops book_count to 0, and reposition() below
        # hides the popup entirely in that case (see its own docstring). If the popup itself
        # currently holds real Qt focus (the normal case: the user pressed Enter/Space on its
        # own focused row to trigger this restore), hide() strands focus on a now-hidden
        # widget with nothing to reclaim it — QApplication.focusWidget() is then neither None
        # nor MainWindow, which _focus_allows_global_shortcuts() reads as "a panel-local widget
        # still owns this key," permanently blocking every global shortcut until a mouse click
        # elsewhere resets focus. Reported live 2026-09-08: "hit Enter to un-exclude a book,
        # then Esc to close Settings — after that, no keyboard shortcut works... until
        # clicking somewhere." Same root cause class as the "clear focus AFTER hide(), never
        # before" CLAUDE.md rule, just the opposite failure mode — here nothing reclaims focus
        # at all, in either order. Fixed by redirecting to the SAME target
        # _on_excluded_books_exit_upward already uses when the user leaves the popup via Up
        # (Persist search filter's row, directly above it) — functionally the popup vanishing
        # out from under focus is the same "the user is no longer in the popup" event.
        had_focus = QApplication.focusWidget() is self.excluded_books_popup
        self.excluded_books_popup.reposition(self.excluded_books_section, self.library_tab)
        if had_focus and not self.excluded_books_popup.isVisible():
            rows = self.panel_manager.settings_tab_button_rows()
            if rows:
                self._focus_settings_control(rows[-1][0])

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

    def _on_sprint_started(self):
        self._dismiss_eof_prompt()
        self.sprint_cancel_btn.show()
        self.sprint_pulse_anim.start()
        self.db.record_sprint_attempt()
        if self.current_file:
            if not self.session_recorder.is_active:
                self.session_recorder.open()
            else:
                self.session_recorder.resume()

    def _on_sprint_stopped(self):
        self.sprint_cancel_btn.hide()
        self.sprint_pulse_anim.stop()
        self.sprint_opacity_effect.setOpacity(1.0)

    def _on_sprint_grace_warning(self, active: bool):
        """SprintPanel.grace_warning_changed only fires on a True<->False
        transition (grace_remaining crossing the 3s threshold while paused),
        so this doesn't need its own idempotency guard."""
        if active:
            self.grace_warn_anim.start()
        else:
            self.grace_warn_anim.stop()
            self.grace_warn_opacity_effect.setOpacity(1.0)

    def _on_reset_sprint_stats_requested(self):
        self.db.reset_sprint_stats()
        # Hide the button live — the reset-confirm flow is entirely self-contained
        # inside the panel (no auto-close on confirm, unlike arming a sprint), so it's
        # always visible right when this runs. has_sprint_data() is always False here
        # in practice (reset just wiped both tables) — still queried rather than
        # hardcoded, so this stays correct if reset_sprint_stats ever becomes partial.
        self.sprint_panel.set_has_sprint_data(self.db.has_sprint_data())
        if hasattr(self, 'stats_panel') and self.stats_panel.isVisible():
            self.stats_panel.refresh_overall()

    def _on_sprint_expired(self, duration_s):
        """Called only on natural sprint completion. Unlike sleep, a sprint completing
        does NOT pause playback — the user keeps listening — so this deliberately does
        NOT mirror _on_sleep_timer_expired's library_panel.set_is_playing(False) or
        session_recorder.pause() calls; pausing the recorder here would silently stop
        listening-time tracking for a session that's still live."""
        self._save_current_progress()
        self.db.record_sprint_session(duration_s)
        # Without this, the Overall tab's Sprints row only picked up a natural
        # completion on the NEXT tab switch or panel reopen — reported live,
        # 2026-08-11. Mirrors the EOF book-finished handler's own
        # stats_panel.isVisible() + refresh_current_tab() pattern (app.py, the
        # write_book_event('finished') call site) rather than an unconditional
        # refresh, so this is a no-op when Stats isn't open.
        if hasattr(self, 'stats_panel') and self.stats_panel.isVisible():
            self.stats_panel.refresh_current_tab()
        # No live Reset-button update needed here: while a sprint is active/completing,
        # _sprint_active gates it hidden regardless of data (Cancel-the-sprint owns that
        # slot instead — the two are mutually exclusive). Reset only ever becomes visible
        # again on the NEXT panel open, which already re-queries has_sprint_data() fresh
        # in _start_sprint_entry.

    @staticmethod
    def _indicator_label_text_rect(lbl):
        """sleep_timer_label's actual rendered TEXT rect, centered within its full
        104x24 button geometry — the button's background is fully transparent (QSS), so
        only the text is ever visibly drawn; the rest of the button is real, clickable
        (QPushButton convention), but invisible. Reported live 2026-09-16: the hand
        cursor/click zone reaching into that invisible space, left of the text, read as
        a bug even though the button's full rect being clickable is correct by
        QPushButton's own convention — narrowed to match what's actually on screen, same
        shape as _muted_icon_rect but from text metrics instead of a fixed icon size.
        Empty text (inactive) returns an empty rect — nothing to hit-test against, which
        also naturally keeps the inactive state fully inert without a separate check."""
        text = lbl.text()
        if not text:
            return QRect()
        text_width = lbl.fontMetrics().horizontalAdvance(text)
        text_height = lbl.fontMetrics().height()
        x = (lbl.width() - text_width) // 2
        y = (lbl.height() - text_height) // 2
        return QRect(x, y, text_width, text_height)

    def _on_indicator_label_pressed(self, event):
        """Only lets a press that lands on the actual rendered text reach QPushButton's
        real mousePressEvent (which starts its internal press-tracking, so .clicked
        fires on release) — a press in the invisible surrounding space is swallowed
        here and never becomes a click. See _indicator_label_text_rect."""
        if self._indicator_label_text_rect(self.sleep_timer_label).contains(event.position().toPoint()):
            QPushButton.mousePressEvent(self.sleep_timer_label, event)

    def _on_indicator_label_hover(self, event):
        """Hand cursor only over the actual rendered text — mirrors
        _on_muted_icon_hover's pattern for the same reason."""
        self._resync_indicator_label_cursor(event.position().toPoint())

    def _resync_indicator_label_cursor(self, local_pos=None):
        """Re-evaluates sleep_timer_label's cursor against `local_pos`, or against the
        CURRENT real cursor position via QCursor.pos() when called from a text-change
        handler rather than a real mouseMoveEvent — same reasoning as
        _resync_muted_icon_cursor: the label's TEXT (and therefore its hit rect) can
        change shape under a stationary mouse as the sleep/sprint countdown ticks, and
        nothing else would re-evaluate the cursor for that case."""
        if local_pos is None:
            local_pos = self.sleep_timer_label.mapFromGlobal(QCursor.pos())
        if self._indicator_label_text_rect(self.sleep_timer_label).contains(local_pos):
            self.sleep_timer_label.setCursor(Qt.PointingHandCursor)
        else:
            self.sleep_timer_label.unsetCursor()

    def _on_sprint_display_text_updated(self, text):
        old_text = self.sleep_timer_label.text()
        was_armed = bool(old_text)
        self.sleep_timer_label.setText(text)
        self._resync_indicator_label_cursor()
        newly_armed = bool(text) and not was_armed
        # Entering the grace countdown ("Grace MM:SS", shown while paused mid-sprint)
        # is its OWN transient-confirmation trigger while muted, same as arming —
        # was_armed alone can't catch this, since both the running countdown and the
        # grace text are non-empty, so the plain empty->non-empty check never re-fires
        # for this transition. Reported live, 2026-08-11 ("same for the grace").
        entered_grace = text.startswith("Grace ") and not old_text.startswith("Grace ")
        if (newly_armed or entered_grace) and self.volume_slider.value() == 0:
            self._sprint_just_set = True
            self.sprint_confirm_timer.start(_INDICATOR_DISMISS_MS)
        elif not text:
            self.sprint_confirm_timer.stop()
            self._sprint_just_set = False
        if self.vol_stack.currentIndex() != 1:
            self._settle_vol_stack()

    def _on_sprint_confirm_timeout(self):
        self._sprint_just_set = False
        if self.vol_stack.currentIndex() != 1:
            self._settle_vol_stack()

    def _sleep_arm_gate(self, proceed):
        """Passed to SleepTimerPanel.set_arm_gate(). If sprint is active, defer
        arming behind a confirm shown IN THE SLEEP PANEL (the panel the user is
        currently interacting with) — confirming cancels sprint, then arms sleep.
        No conflict: proceed immediately."""
        if self.sprint_panel.is_active:
            self.sleep_panel.show_conflict_confirm(
                "This will cancel your active sprint. Confirm?",
                lambda: (self.sprint_panel.disable_sprint(), proceed())
            )
        else:
            proceed()

    def _sprint_arm_gate(self, proceed):
        """Passed to SprintPanel.set_arm_gate(). Mirrors _sleep_arm_gate exactly,
        checking sleep instead of sprint, confirming in the sprint panel."""
        if self.sleep_panel.is_active:
            self.sprint_panel.show_conflict_confirm(
                "This will cancel your active sleep timer. Confirm?",
                lambda: (self.sleep_panel.disable_sleep_timer(), proceed())
            )
        else:
            proceed()

    def _on_indicator_label_clicked(self):
        """sleep_timer_label (vol_stack page 0) is shared between sleep and sprint
        display. Clicking it must disable whichever of the two is actually
        active, not always sleep — replaces the old direct
        sleep_timer_label.clicked -> sleep_panel.disable_sleep_timer connection
        (main_window_builders.py), which predates sprint's existence."""
        if self.sleep_panel.is_active:
            self.sleep_panel.disable_sleep_timer()
        elif self.sprint_panel.is_active:
            self.sprint_panel.disable_sprint()

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
        self._reload_excluded_books()
        if path == self.current_file:
            self._on_book_removed()

    def _carousel_clip_rect(self):
        """The carousel's blur clip, in CAROUSEL-local coordinates.

        Mirrors PanelManager._apply_visual_area_clip's rule (blur only what the
        open panel actually occludes) but for the carousel's own geometry, which
        differs: the carousel is full window width while visual_area is inset
        10px each side, so the same panel edge lands at a different local x.
        Returns None (= blur nothing) when no panel is open or blur is off.
        """
        car = getattr(self, '_carousel', None)
        if car is None:
            return None
        pm = getattr(self, 'panel_manager', None)
        if pm is None or not self.config.get_blur_enabled():
            return None
        panel = pm.blurred_panel()
        if panel is None:
            return None
        from .ui.transport_bar_blur import panel_rect_in_common_space
        panel_rect = panel_rect_in_common_space(panel, self.content_container)
        car_tl = car.mapTo(self.content_container, QPoint(0, 0))
        local = panel_rect.translated(-car_tl.x(), -car_tl.y())
        result = local.intersected(car.rect())
        if _GRAB_TRACE_ENABLED:
            logger.warning(
                f"[SEAM-TRACE] _carousel_clip_rect car_size={car.size()} "
                f"car_tl={car_tl} panel={panel.objectName()!r} clip={result}"
            )
        return result

    def _sync_carousel_radius(self, radius):
        """Per-frame radius follower for the carousel's own effect, driven by
        blur_animation.valueChanged. Only touches the radius — the clip is owned
        by sync_carousel_blur so an in-flight animation can't resurrect a clip
        that was just cleared on panel close.

        `radius is None` guard: valueChanged can deliver an invalid QVariant,
        which arrives here as None and made float() raise
        `TypeError: float() argument must be a string or a real number, not
        'NoneType'` (reported live 2026-08-14; the line dates to dcef0e7,
        2026-07-27, and is unguarded on main too — pre-existing, not a
        regression, though the Book Detail blur-park work made the path more
        reachable by leaving a blur live while the carousel is built). Qt's
        default handling for an exception in a Python slot keeps the app
        running, but the raise aborts this slot, so the carousel silently stops
        following the animation for the rest of that tween. Skipping the tick is
        correct: there is no meaningful radius to apply, and the next real
        valueChanged — or sync_carousel_blur, which owns the authoritative
        value — sets it."""
        if radius is None:
            return
        eff = getattr(self, '_carousel_blur', None)
        if eff is not None and getattr(self, '_carousel', None) is not None:
            eff.setBlurRadius(float(radius))

    def sync_carousel_blur(self, radius, clip):
        """Keep the carousel's own effect in step with visual_area's blur.

        Called from PanelManager on every blur radius change and on clip
        set/clear, since the carousel is a sibling and is not covered by
        visual_area's effect. No-op when no carousel exists (the common case —
        it only lives in the no-book state)."""
        eff = getattr(self, '_carousel_blur', None)
        if eff is None or getattr(self, '_carousel', None) is None:
            return
        eff.setBlurRadius(radius)
        eff.set_clip_rect(self._carousel_clip_rect() if clip else None)

    def _on_book_removed(self):
        """Helper for controller when the currently playing folder is removed from library."""
        # close() MUST fire while _current_book / current_file are still valid and
        # the player is still live: its get_book_fn lambda reads self._current_book,
        # and its position read reads the live player. Nulling these first made
        # close() receive None for the book and silently discard every active
        # session on removal regardless of duration (confirmed data loss for long
        # sessions). terminate() still runs after, below.
        self.session_recorder.close()
        self.current_file = ""
        self._current_book = None
        # Per-book state: a pause armed on the removed book must not carry into
        # whatever book is selected next — see _on_book_selected_from_library.
        self._last_pause_timestamp = None
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
        self._last_saved_pos = 0.0

        self._set_chapter_ui_active(False)
        self._load_cover_art("")
        self.library_panel.set_playing_path("")
        self.library_panel.set_is_playing(False)
        self.config.set_last_book("")
        # Reconcile chrome now that the book is gone — without this, callers that
        # don't independently re-run the gate (e.g. the book-detail trash button)
        # leave stale player chrome visible.
        self.library_controller.apply_current_state()

        # The reconcile above HIDES the transport chrome. If a panel is open with
        # blur on, that chrome sits behind the blur overlay's cached snapshot —
        # and a widget being hidden emits no Paint event, so _DirtyRectTracker
        # never observes the change and never schedules a refresh. The overlay
        # then keeps showing blurred transport buttons that are no longer there
        # (found live 2026-07-27: removing the last scan location while the
        # Settings panel was open left ghost buttons over the quote screen until
        # the panel was closed and reopened).
        #
        # force_refresh_now() is the mechanism already built for exactly this
        # class of event — "a content change that doesn't produce a Paint event
        # on any of the 12 tracked widgets" — and it no-ops when the overlay
        # isn't active, so this is safe on every other path into here.
        pm = getattr(self, 'panel_manager', None)
        if pm is not None:
            pm._transport_bar_blur.force_refresh_now()
            # This reconcile reflowed the layout underneath any open panel:
            # visual_area grows from COVER_AREA_HEIGHT to the no-book height and
            # the ambient carousel appears. Both blur clips were computed at
            # panel-open against the old geometry and nothing else revisits them
            # until the panel closes, so recompute them now — see
            # reclip_visual_area_for_layout_change for the measured before/after.
            pm.reclip_visual_area_for_layout_change()

    def get_current_file(self):
        """Return the currently loaded file path."""
        return self.current_file

    def _update_folder_list_widget(self, paths):
        self.folder_list_widget.clear()
        for loc in paths:
            item = QListWidgetItem(loc)
            item.setToolTip(loc)  # full path on hover, since long paths now elide instead of scrolling
            self.folder_list_widget.addItem(item)
        # Rescan means nothing with no folders configured. Disabling rather than hiding: hiding
        # would strand Add alone on the left, and stretching it across the row would make the
        # layout jump as folders come and go. setEnabled also does the whole job in one step —
        # Qt dims via the :disabled QSS rule, drops :hover/:pressed, ignores clicks, and takes
        # them out of Tab and arrow navigation so the keyboard skips straight past them (see
        # _handle_settings_arrows, which filters on isEnabled()).
        self.refresh_library_btn.setEnabled(bool(paths))
        # Remove additionally needs an actual SELECTION, not just a non-empty list — reload just
        # emptied/repopulated the widget, which drops any prior selection, so this must be
        # re-evaluated here too, not only from itemSelectionChanged.
        self._update_remove_folder_btn_enabled()

    def _update_remove_folder_btn_enabled(self):
        """Remove is a no-op with nothing selected (`_on_remove_folder_clicked` already guards
        it), but it stayed clickable and undimmed the whole time regardless — reported live
        2026-09-05 as misleading, since an empty selection also changes what Rescan does (it
        rescans every configured path rather than just the selected one). Single source of truth
        for Remove's enabled state, called on selection change and on any list repopulation."""
        self.remove_folder_btn.setEnabled(bool(self.folder_list_widget.selectedItems()))

    def _get_current_folder_path(self):
        """The CURRENT-ROW path (Qt's currentItem()), independent of selection — a path can be
        highlighted while unselected, or while OTHER rows are separately selected. Named
        distinctly from _get_selected_folder_paths (plural, the real multi-selection) since a
        2026-09-05 design pass split cursor position and selection into two genuinely different
        facts (see _move_list_current_row's docstring); the old name here used to say "selected"
        for what was always actually the current row, which read as a duplicate of the plural
        method rather than the different thing it is."""
        item = self.folder_list_widget.currentItem()
        return item.text() if item else None

    def _get_selected_folder_paths(self):
        return [item.text() for item in self.folder_list_widget.selectedItems()]

    def _get_new_folder_path(self):
        path = QFileDialog.getExistingDirectory(None, "Select Library Folder")
        self._dialog_close_time.restart()
        return path

    def _update_status_banner_ui(self, text=None, show_banner=None, show_cancel=None, auto_hide=False,
                                 auto_hide_ms=3000, retire_eof_prompt=True):
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

        if retire_eof_prompt and show_banner is True:
            # A fresh banner is being presented — it takes over the banner the same
            # way a starting scan already does (see show_cancel branch below).
            # Retires any stale EOF revert/close buttons so they don't visually
            # stack onto an unrelated message. Does NOT clear _eof_book_id: that's
            # EOF-prompt-specific bookkeeping (guards _on_revert_finish /
            # _dismiss_eof_prompt), and since the buttons driving those code paths
            # are now hidden, a stale _eof_book_id is inert — it gets overwritten by
            # the next real EOF event or cleared by a subsequent
            # _dismiss_eof_prompt() call. Contrast the show_cancel=True branch below,
            # which additionally clears _eof_book_id because a scan start is a more
            # definitive "this EOF prompt is retired" event than a generic banner.
            self.eof_revert_btn.hide()
            self.eof_close_btn.hide()

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
        """Flags a book whose backing file/folder is confirmed gone via the
        dedicated is_missing flag — NOT is_excluded (user-trash). The two used
        to be conflated (this method used to call set_book_excluded(path, True)
        directly): a book the scanner auto-flagged as missing would land in the
        Excluded Books popup with a "restore" eye that just un-excluded it with
        no file behind it — the user would try to load it, _mark_book_missing
        would fire again, and it ping-ponged back into Excluded Books forever.
        is_missing is what's now used for this; get_excluded_books() filters it
        out entirely (no restore action makes sense for a book that isn't
        there), and it self-heals (cleared automatically) the next time the
        scanner rediscovers the folder — see upsert_book/upsert_books_batch.

        The book stays in the DB (progress, history, tags survive); only
        Cover/Tags editing and active playback are gone while missing, same as
        a user-trashed book.

        Call this ONLY at a confirmed-missing point — i.e. after os.path.exists(path)
        has returned False, or mpv itself reported the load failed. Do not call it
        speculatively (e.g. on a transient I/O hiccup) — that would hide a book the
        user could otherwise still play once a drive remounts.

        This is the LAZY, single-book detector (fires when the user selects/loads a
        gone book). The scanner's force-rescan path (db.mark_books_missing, called
        from ScannerWorker.run_scan) is a SECOND confirmed-missing detector with the
        same is_missing contract — it batch-flags books under a scanned-and-reachable
        location whose folders weren't rediscovered, and refreshes the UI via the
        scanner's `finished` signal rather than the inline refresh calls below.

        If the missing book is the active one, also tears down playback via
        _on_book_removed so the UI doesn't keep showing a ghost now-playing state."""
        book = self.db.get_book(path)
        if book is None:
            return
        self.db.set_book_missing(path, True)
        self.library_panel.refresh(force=True)
        self.tags_panel.refresh_books()
        self.stats_panel.refresh_current_tab()
        self._reload_excluded_books()
        if path == self.current_file:
            self._on_book_removed()

    def _on_book_metadata_saved(self, book_id: int, title: str, author: str, narrator: str, year: object):
        self.library_panel._book_model.update_book_metadata(book_id, title, author, narrator, year)
        self.library_panel._refresh_search_match_state()
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
        """Build and place the carousel synchronously. Safe to call multiple times.

        The no-book test is `self.current_file` ONLY — deliberately NOT
        `no_book_section.isVisible()`. Qt reports isVisible() == False for every
        child widget until its top-level window has been shown, and
        `_check_library_status()` runs in `__init__` (app.py, ~line 494) well
        before `self.show()` (~line 571) — so an isVisible() test here always
        early-returns at startup and the carousel never appears on a fresh
        no-book launch. That was a live bug for ten days (bisected to cd5ec5b,
        2026-07-17): before that commit an unconditional launch scan happened to
        fire `_on_scan_finished` -> `apply_current_state()` a second time AFTER
        the window was up, which re-ran this path with the guard now passing.
        Removing that scan was correct, but the carousel had been silently
        riding it as its only post-show trigger.

        `current_file` is the same authoritative value `compute_library_state`
        derives `state["has_book"]` from, and the sole caller
        (`apply_library_state`'s `not has_book` branch, library_controller.py)
        has already established that state before calling here — so this reads
        the real state directly instead of re-deriving it from a widget's paint
        status. Do NOT reintroduce a visibility-based guard here."""
        if self._carousel is not None:
            return   # already showing — do not reshuffle mid-display
        if self.current_file:
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

        # The carousel needs its OWN blur effect: it is a SIBLING of visual_area
        # (parented to content_container above), so visual_area's ClippedBlurEffect
        # cannot reach it — without this the stripe and the "Go to Library" button
        # blur behind an open panel while the cover thumbnails stay sharp.
        #
        # It cannot simply be reparented into visual_area to inherit that effect:
        # the carousel is CAROUSEL_STRIPE_W (300px, full window width, bleeding to
        # both edges by design — see ad15f53) while visual_area is only 280px,
        # inset 10px each side. carousel_holder is 300px but overflows its 280px
        # parent and is clipped, which is why the real carousel was made a sibling
        # in the first place. Reparenting would shave 20px off the stripe.
        #
        # Verified safe on a scrolling widget before wiring: the strip keeps
        # repainting normally under the effect (no freeze — unlike the reverted
        # cached-pixmap overlay approach), the clip region blurs, and the sliver
        # stays sharp.
        self._carousel_blur = ClippedBlurEffect(self._carousel)
        self._carousel_blur.setBlurHints(QGraphicsBlurEffect.AnimationHint)
        self._carousel_blur.setBlurRadius(self.blur_effect.blurRadius())
        self._carousel_blur.set_clip_rect(self._carousel_clip_rect())
        self._carousel.setGraphicsEffect(self._carousel_blur)

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
        #
        # Routed through ThemeManager.get_active_theme() (not the raw
        # _active_display_theme_internal field) as of 2026-07-20 — this call
        # site has no coupling to ThemeManager's fade/hover state machine and
        # can fire at any moment, including mid-hover-preview; the raw field
        # holds the PREVIEWED theme name for the duration of a hover, so a
        # direct read could paint content_container with a theme the user was
        # only hovering, not the actual active one. get_active_theme() resolves
        # against hover state so this can never happen. See
        # review/Review_260720_theme_reach.md (Mechanism A / Pass 1).
        theme_name = self.theme_manager.get_active_theme()
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
        # Sleep, Sprint, and Playback panels have no function without an active book.
        self.sleep_trigger_btn.setVisible(visible)
        self.sprint_trigger_btn.setVisible(visible)
        self.speed_trigger_btn.setVisible(visible)

    def _set_scan_buttons_enabled(self, enabled):
        """Enable/disable the Library panel's folder-management buttons.
        Disabled (but still visible) while a scan is in progress."""
        self.add_folder_btn.setEnabled(enabled)
        # Remove is additionally gated on selection (_update_remove_folder_btn_enabled) — re-
        # enabling it unconditionally here on scan-finish would undo that gate and make it
        # clickable again with nothing selected. Disabling for the scan-in-progress case is still
        # unconditional, same as the other two buttons.
        if enabled:
            self._update_remove_folder_btn_enabled()
        else:
            self.remove_folder_btn.setEnabled(False)
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
            self.current_chapter_label.set_clickable(False)
            self.chap_duration_label.setCursor(Qt.ArrowCursor)
            self._chapter_label_clickable = False

    def _save_current_progress(self):
        """Saves the current playback position to both DB and Config."""
        if self.current_file and self.player.is_initialized:
            pos = self.player.time_pos
            logger.debug(f"[PERSIST-TRACE] _save_current_progress: current_file={self.current_file!r} "
                         f"pos={pos!r} is_seeking={self.player.is_seeking} "
                         f"_logical_pos={self.player._logical_pos!r} _cached_time_pos={self.player._cached_time_pos!r}")
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
        self.panel_manager.call_when_panels_settled(self.panel_manager._open_tags_flow)

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
        logger.debug(f"[BOOKSWITCH-TRACE] _on_book_selected_from_library: entry path={path!r} "
                     f"current_file={self.current_file!r}")
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
        # Smart rewind is per-book: a pause timestamp armed on the outgoing book must
        # never survive into the incoming book's first resume (it would rewind the new
        # book based on how long the OLD book sat paused, possibly past its own chapter
        # boundaries). player.load_book() resets its own per-book state but does not
        # own this timestamp (it lives on MainWindow), so it must be cleared here.
        self._last_pause_timestamp = None
        # A sprint targets THIS book's listening session — switching books mid-sprint
        # must not silently carry the countdown/grace pool over to the new book.
        # Distinct from a deliberate manual cancel (sidebar X / panel button), which
        # stays silent — this shows "Sprint cancelled" (2026-08-11).
        self.sprint_panel.cancel_for_book_switch()
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
        # Seed from the incoming book's own saved position, NOT 0.0. _restore_position
        # (called later via load_book) will seek here, but mpv reports a near-zero
        # transient (0.0, or a residual like 1e-08) for a few ticks before that seek
        # lands. If this were reset to 0.0, the monotonic guard in _sync_persistence
        # (pos < _last_saved_pos) would never trip during that window — 0.0 is never
        # less than 0.0 — letting the transient overwrite a real saved position. Seeding
        # from the real prior position gives the guard an actual floor to protect
        # during exactly the window it exists for. See NOTES.md/CLAUDE.md for the fix
        # this closes (M4B progress silently resetting to ~0 on repeated book-switch).
        incoming_book_data = self.db.get_book(path)
        self._last_saved_pos = incoming_book_data.progress if incoming_book_data and incoming_book_data.progress else 0.0
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
        """Lightweight handler for VT file switches. Does not restore position.

        Only clears is_seeking when no seek is genuinely pending (_seek_target is
        None). A seek issued in the same _on_file_loaded call that emitted
        file_switched is settled by _on_time_pos_change's settle branch, which is
        the sole correct owner of that transition — this handler unconditionally
        clearing is_seeking raced that settle and could clobber a landed (or
        still-landing) seek. See NOTES.md "_on_file_loaded's general... race"
        (2026-07-13) for the full mechanism and why this guard is safe now (both
        prior attempts at this exact guard were tested only against seeks that
        could never land at all — a separate, since-fixed bug — not against a
        seek proven capable of settling, which is the case this guard now covers).

        Deliberately does NOT touch _vt_restore_pending / _vt_file_loaded_awaiting_restore
        (the VT restore-on-load rendezvous, see Player.defer_vt_restore / _on_file_loaded's
        VT branch): this handler can fire before, during, or after that rendezvous resolves
        (confirmed via live trace, 2026-07-16 — the library-still-animating deferred-restore
        path can delay _restore_position/defer_vt_restore past this handler's QueuedConnection
        delivery), so it must stay fully orthogonal to that state rather than trying to
        infer anything about it from _seek_target/is_seeking. See NOTES.md 2026-07-16 ("Book
        progress silently resetting to ~0...", Bug 2 fix) for why an earlier version of this
        method that DID inspect _vt_restore_pending here was reverted — it assumed an
        ordering relative to defer_vt_restore that turned out not to be structural.
        """
        if self.player._seek_target is None:
            self.player.is_seeking = False

    def _on_file_ready(self):
        """Called when mpv confirms the file is loaded and ready."""
        logger.debug(f"[BOOKSWITCH-TRACE] _on_file_ready: entry current_file={self.current_file!r} "
                     f"library_is_animating={getattr(self.library_panel, '_is_animating', False)}")
        if getattr(self.library_panel, '_is_animating', False):
            logger.debug("[BOOKSWITCH-TRACE] _on_file_ready: DEFERRED (library still animating)")
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
        _kind = "clear" if pixmap is _PENDING_CLEAR_COVER_THEME else ("cover" if pixmap is not None else "none")
        logger.debug(f"[STUTTER-TRACE] t={time.perf_counter():.6f} _apply_pending_cover_theme: "
                     f"ENTRY pending={_kind}")
        if pixmap is None:
            return
        self._pending_cover_pixmap = None
        # Chain through both sliders' when_animations_done before starting the
        # theme fade. The chapter progress slider is punch-through-exposed during
        # theme fades; if its value animation (animate_to) is still running when
        # the fade overlay is captured, the moving fill produces a ghost image.
        # Waiting for both sliders to settle eliminates the overlap. Covers BOTH the
        # has-cover case (apply_cover_theme(pixmap)) and the no-cover case
        # (clear_cover_theme(), reverting to the pool theme — see the
        # _PENDING_CLEAR_COVER_THEME sentinel note at _show_no_cover_state).
        def _apply():
            if pixmap is _PENDING_CLEAR_COVER_THEME:
                logger.debug(f"[STUTTER-TRACE] t={time.perf_counter():.6f} _apply_pending_cover_theme: "
                             f"_apply() firing (both sliders settled) — calling clear_cover_theme")
                self.theme_manager.clear_cover_theme()
            else:
                logger.debug(f"[STUTTER-TRACE] t={time.perf_counter():.6f} _apply_pending_cover_theme: "
                             f"_apply() firing (both sliders settled) — calling apply_cover_theme")
                self.theme_manager.apply_cover_theme(pixmap)
        def _after_progress():
            if hasattr(self, 'chapter_progress_slider') and hasattr(self.chapter_progress_slider, 'when_animations_done'):
                logger.debug(f"[STUTTER-TRACE] t={time.perf_counter():.6f} _apply_pending_cover_theme: "
                             f"progress_slider settled, chaining chapter_progress_slider.when_animations_done")
                self.chapter_progress_slider.when_animations_done(_apply)
            else:
                _apply()
        logger.debug(f"[STUTTER-TRACE] t={time.perf_counter():.6f} _apply_pending_cover_theme: "
                     f"chaining progress_slider.when_animations_done")
        if hasattr(self.progress_slider, 'when_animations_done'):
            self.progress_slider.when_animations_done(_after_progress)
        else:
            _after_progress()

    def _on_load_failed(self, reason):
        """Called when mpv fires end-file with a non-normal reason (error/unknown),
        or when _resolve_playlist determined the folder has no audio files, or when
        a VT cross-file seek targeted a file missing from disk
        (Player._abandon_seek_missing_file, reason == "File missing.")."""
        self._update_status_banner_ui(text=f"Failed to load: {reason}.", show_banner=True, auto_hide=True)
        if reason in ("no audio files in folder", "File missing.") and self.current_file:
            self._mark_book_missing(self.current_file)

    def _update_chapter_label_clickability(self):
        """Enable the chapter label as a clickable link only when there are 2+ chapters.
        ScrollingLabel.set_clickable owns the cursor now (hand only over the actual
        rendered/scrolling text, not the whole widget — see its docstring); this no
        longer sets the cursor directly."""
        chaps = self.player.chapter_list or [] if self.player else []
        clickable = len(chaps) >= 2
        self.current_chapter_label.set_clickable(clickable)
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
        logger.debug(f"[BOOKSWITCH-TRACE] _restore_position: entry current_file={self.current_file!r} "
                     f"_virtual_timeline_set={self.player._virtual_timeline is not None}")
        QTimer.singleShot(0, lambda: self.player.set_volume_from_slider(self.volume_slider.value()))
        config_pos = self.config.get_last_position(self.current_file)
        if config_pos > 0:
            self.db.update_progress(self.current_file, config_pos)
        book_data = self.db.get_book(self.current_file)
        logger.debug(f"[BOOKSWITCH-TRACE] _restore_position: book_data.progress="
                     f"{book_data.progress if book_data else None!r}")
        if book_data and book_data.progress > 0:
            # Restore to the exact saved position for all book types. This is NOT
            # chapter navigation — there is no boundary to clear — so no epsilon is
            # added. The old non-VT `+ _CHAPTER_BOUNDARY_EPSILON` caused position
            # creep: the 200ms persistence sync saved the epsilon-inflated landing,
            # which became the next restore's input, nudging ~0.35s forward every
            # restart until EOF. The VT branch never added it and never crept.
            if book_data.duration and book_data.duration - book_data.progress < 2.0:
                # A book saved at/near its own end (left at 100% EOF, then reselected) must
                # NOT reach seek_async at all here — for EITHER book type. seek_async's own
                # near-EOF guard ("too close to EOF — let natural EOF handle it") silently
                # no-ops in exactly this case, on both its VT and non-VT branches (the VT
                # path reaches the same guard indirectly, via defer_vt_restore ->
                # _on_file_loaded -> seek_async once mpv confirms load). Two live-found bugs
                # from getting this branch wrong, in order:
                #
                # 1. The ORIGINAL bug this fix targets: both branches used to pre-set
                #    is_seeking=True immediately before calling into seek_async (directly for
                #    non-VT, or via the deferred call for VT). Since the near-EOF guard
                #    returns before ever reaching its own is_seeking=True/_seek_target=pos
                #    assignment, that pre-set was left permanently stranded — is_seeking stuck
                #    True with _seek_target staying None forever (the settle branch in
                #    _on_time_pos_change requires _seek_target is not None to ever clear it) —
                #    which froze the app on the next Play (TODO.md, "Resuming an M4B after
                #    unfinishing it freezes the app", 2026-09-19).
                # 2. A FIRST FIX ATTEMPT for (1) just skipped the seek and left it at that —
                #    wrong, found live: mpv loads every fresh file at position 0 regardless
                #    (or, for VT, at the start of whichever file the saved position falls in),
                #    so skipping the seek entirely silently reset the visible position to 0%/
                #    chapter-start instead of leaving it at its true saved 100%. This is what
                #    produced the VT report "progress retreats back to the beginning of the
                #    last chapter" and the M4B report "goes to 0%" — same underlying gap,
                #    reached via the VT and non-VT branches respectively.
                #
                # The correct fix: synthesize the SAME `_eof = True` state `_advance_or_finish`
                # sets on genuine natural completion (player.py) — no mpv command of any kind
                # (no seek, no `time_pos =` direct assignment either — that setter still issues
                # `self.instance.time_pos = value`, an mpv property write that IS a seek and
                # carries the identical hang risk). `_update_ui_sync`'s existing is_eof branch
                # already reads this flag every tick and renders the finished slider/
                # percentage/"Restart" state correctly regardless of mpv's actual (irrelevant,
                # since the book is done) position — this is the exact state a book that
                # genuinely just finished playing already ends up in, not a new one.
                #
                # Checking book_data.duration (scanner-sourced, always available with no mpv
                # round-trip) here — rather than relying on seek_async's own guard, which reads
                # the async-populated _cached_duration and can race it — closes the hole
                # outright instead of narrowing the window. Applies to VT and non-VT alike, so
                # this check runs BEFORE the VT/non-VT split below, not duplicated in both arms.
                #
                # _eof_event_written must ALSO be set True here, not just _eof — without this,
                # _update_ui_sync's is_eof branch reads _eof_event_written freshly False (reset
                # on every book load, _on_file_ready) and treats this synthesized restore as a
                # BRAND NEW completion: it writes a second 'finished' book_event to the DB and
                # re-shows the "Marked as finished" revert-prompt banner, every single time the
                # book is reselected — live report, 2026-09-21 (VT): "Revert the finished
                # status, load another book, come back, it asks again whether to revert... I am
                # assuming that it finishes it again just because it is going back to 100%
                # although it wasn't even playing." That side effect belongs ONLY to genuinely
                # crossing into EOF via live playback (a completely different code path,
                # _update_ui_sync's own is_eof branch reached through _advance_or_finish, never
                # through this method) — marking it already-written here suppresses it
                # correctly for a mere reselect. _eof_book_id is deliberately left untouched
                # (None) so the revert button/banner machinery it gates never arms for this
                # synthetic case either.
                self.player._eof = True
                self._eof_event_written = True
                self.player.is_seeking = False
                # _logical_pos must ALSO be set here, not just _eof — without this, the
                # book's TRUE position (its own saved duration) is never recorded anywhere
                # player-side. player.time_pos's getter returns _logical_pos when set, but
                # falls back to raw _cached_time_pos otherwise — and _cached_time_pos is
                # still whatever load_book's reset left it (None/effectively 0), since mpv
                # loads every fresh file at position 0 regardless of this flag. The very
                # next switch-away calls _save_current_progress (app.py), which reads
                # player.time_pos and writes IT to the DB's progress column — silently
                # overwriting the book's correct saved duration with ~0. Live report,
                # 2026-09-21: "Library not showing 100% anymore, there are two sources of
                # truth. Then it incorrectly catches up and goes to 0% on a click on the
                # same book or another book" — the transport view read the (correct)
                # in-memory _eof flag while the Library grid read the (now-corrupted) DB
                # column, and the very next save made the corruption permanent. Setting
                # _logical_pos directly is a plain Python attribute write, same as _eof —
                # NOT an mpv property/command call, so it carries none of seek_async's
                # near-EOF hang risk; every _logical_pos write site in player.py is this
                # same shape (see _on_time_pos_change's settle branch). GLOBAL, matching
                # _logical_pos's own established convention (never add _file_offset) —
                # correct for VT here too, since book_data.duration/progress are already
                # whole-book (global) values, not any one VT file's own local duration.
                # Deliberately does NOT also touch _cached_time_pos — CLAUDE.md is
                # explicit that the two must stay decoupled ("Do NOT couple a
                # _logical_pos write to any _cached_time_pos write") and that
                # _cached_time_pos is FILE-LOCAL for VT (this value is global), so
                # writing it here would be wrong for VT specifically. time_pos's own
                # getter already checks _logical_pos first, before ever falling back to
                # _cached_time_pos, so this alone is sufficient — no fallback path is
                # reachable once _logical_pos is set.
                self.player._logical_pos = book_data.duration
            elif self.player._virtual_timeline is not None:
                # VT restore-on-load race fix: book_ready (which triggers this call) fires
                # BEFORE instance.play() for VT books, so calling seek_async here directly
                # can reach mpv before it has loaded the file, and the seek is silently
                # dropped. Defer the actual seek to _on_file_loaded's VT branch, which only
                # runs once mpv has confirmed the file is loaded. is_seeking is explicitly
                # set False (not left at load_book's True) because load_book's assignment
                # was never designed with this window in mind (see CLAUDE.md/the fix plan) —
                # seek_async, called later inside _on_file_loaded, is the sole place that
                # sets is_seeking True, together with _seek_target, exactly as for every
                # other seek.
                self.player.is_seeking = False
                self.player.defer_vt_restore(book_data.progress)
            else:
                self.player.is_seeking = True
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
        """Left click toggles the speed (PLAYBACK) panel."""
        # Own panel visible → close it (self-toggle, always allowed). Otherwise delegate to
        # _open_speed_flow, which owns the one-overlay-at-a-time gate and the sidebar-queued
        # handoff. This replaces the old unconditional _hide_popups() (which closed every
        # other panel first — the close-vs-open fight that produced the overlap bug).
        if self.speed_panel.isVisible():
            self.panel_manager._close_speed_flow()
        elif self.panel_manager.switch_to_speed_panel():
            # Another full panel was open: it is closing now and Speed opens once
            # that close lands. The button protrudes past the 90%-width panels, so
            # it stays clickable while one is open — without this the click hit
            # _open_speed_flow's one-overlay gate and was silently dropped, leaving
            # the button styled as pressed with nothing happening.
            pass
        else:
            self.panel_manager._open_speed_flow()

    def _on_sleep_button_clicked(self):
        if self.sleep_panel.isVisible():
            self.panel_manager._close_sleep_flow()
        else:
            self.panel_manager._open_sleep_flow()

    def _show_chapter_dropdown(self):
        """Positions and shows the floating chapter list."""
        if not getattr(self, '_chapter_label_clickable', False):
            return

        if self.chapter_list_widget.isVisible():
            logger.debug(
                f"t={time.perf_counter():.6f} [_show_chapter_dropdown] "
                f"already visible -> fade_out"
            )
            self.chapter_list_widget.fade_out()
            return

        # One overlay at a time: if any OTHER overlay is present or mid-animation, drop this
        # open rather than the old hide_all_panels()-then-open (which started a close-slide
        # that fought the other panel's still-running open-slide — the overlap bug). The
        # own-list-visible toggle above runs first, so this never blocks closing our own list.
        if self.panel_manager.is_overlay_open_or_committed():
            return
        self.panel_manager.dismiss_sidebar()

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
        logger.debug(
            f"t={time.perf_counter():.6f} [_show_chapter_dropdown] "
            f"pos={pos} is_seeking={self.player.is_seeking} -> active_idx={active_idx} "
            f"(queuing deferred scroll_to_active)"
        )
        self.chapter_list_widget.show_above(self.current_chapter_label, self)

        # Apply selection and scroll after the widget is shown and laid out
        self.chapter_list_widget.setCurrentRow(active_idx)
        QTimer.singleShot(0, lambda: self.chapter_list_widget.scroll_to_active(active_idx))

    def _update_ui_sync(self):
        # [SETTINGS-DUMP] probe (2026-08-15, bisect harness) — env-gated,
        # independent of playback state and of the transport-bar blur overlay
        # entirely, so this same probe works unmodified on `main` (needed to
        # bisect a regression against it). Piggybacks on the existing 200ms
        # ui_timer rather than adding a new timer. Saves settings_panel's own
        # grab() to PNG every tick while both the env var is set and the panel
        # is visible — re-saves each tick (not one-shot) so a manual bisect
        # session can just re-run and re-check the same file without
        # restarting the app between commits.
        if os.environ.get("FABULOR_DUMP_SETTINGS") == "1":
            sp = getattr(self, 'settings_panel', None)
            if sp is not None and sp.isVisible():
                # Whole WINDOW, not just the panel — sample coordinates given
                # for this bisect are in window space (they include the right
                # sliver past the panel's 90%-width edge), so grabbing only
                # settings_panel would put those x-coords out of bounds.
                self.grab().save("/tmp/fabulor_settings_dump.png", "PNG")
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
                        retire_eof_prompt=False,
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
                # Force the percentage label alongside the slider — without this it can go
                # stale at whatever transient value the live 200ms tick last computed right
                # before is_eof flipped True (e.g. a near-zero pos sample during the book's
                # duration-race window — see CLAUDE.md's "Duration race corollary"), since
                # nothing else revisits this label once the EOF branch takes over the
                # slider. Same "force to the known-correct EOF value" treatment the slider
                # and time labels below already get.
                self.progress_percentage_label.setText("100.0%")
                self.current_time_label.setText(self.player.format_time(pos / speed))
                if self.show_remaining_time:
                    self.total_time_label.setText("-00:00:00")
                    self.chap_duration_label.setText("-00:00:00")
                else:
                    self.total_time_label.setText(self.player.format_time(dur / speed))
                # Force the CHAPTER slider/labels too, same reasoning as the overall
                # progress ones above — this branch never falls through to
                # _sync_chapter_ui (it returns below), so without this the chapter
                # slider is left wherever the book-switch reset (_on_book_removed's
                # chapter_progress_slider.setValue(0)) or the fresh load happened to
                # leave it, reading as "retreated to the start of the last chapter"
                # even though the overall progress correctly shows finished. Live
                # report, 2026-09-21 (VT): "progress retreats back to the beginning
                # of the last chapter" — same gap, surfaced by the new near-EOF
                # restore path (_restore_position) synthesizing is_eof=True at a
                # moment the chapter slider was never driven to 100% by real
                # playback, unlike natural EOF (reached by playing forward, which
                # already ticks the chapter slider to its end before EOF fires).
                if self.player.chapter_list:
                    self.chapter_progress_slider.setValue(1000)
                    last_chap = self.player.chapter_list[-1]
                    chap_dur = max(0.0, dur - last_chap.get('time', 0))
                    self.chap_elapsed_label.setText(self.player.format_time(chap_dur / speed))
                    if self.show_remaining_time:
                        self.chap_duration_label.setText("-00:00:00")
                    else:
                        self.chap_duration_label.setText(self.player.format_time(chap_dur / speed))
                    # Force the chapter NAME label (and list-overlay selection) to the
                    # last chapter too — live report, 2026-09-21 (both VT and M4B):
                    # "the chapter shown in the main window and the chapter list do not
                    # agree. Main window shows chapter[0]." This branch never fires a
                    # real seek (no mpv command issued for a restore-time EOF synthesis
                    # — see _restore_position), so chapter_changed never emits and
                    # _update_chapter_label_from_index is never called by anything else
                    # here; the label is left at whatever the previous book, or the
                    # fresh load's initial state, last wrote. Call it directly with the
                    # true last-chapter index, same "force to the known-correct EOF
                    # value" treatment as the slider/time labels immediately above.
                    self._update_chapter_label_from_index(len(self.player.chapter_list) - 1)
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
        # Delegate Sprint Logic
        self.sprint_panel.update_sprint_state(current_time, self.player.pause if self.current_file else True, pos, dur, self.player.eof_reached)

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
        if hasattr(self, 'muted_icon_label'):
            muted_color = t.get('slider_vol_fill', t['text'])
            self.muted_icon_label.setPixmap(_load_svg_pixmap("muted.svg", muted_color, QSize(14, 14)))
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
        self._cover_placeholder.refresh(self.cover_art_label, self._placeholder_color())
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
        logger.debug(
            f"_sync_chapter_ui: syncing to chapter={curr_chap} pos={pos} "
            f"prev_ui_row={self.chapter_list_widget.currentRow()}"
        )
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
                # Monotonic guard: while a seek is in flight, mpv can report a
                # transient pos far below the last-saved position (e.g. 0.0 right
                # after a restore-seek is issued but before it lands). Writing that
                # transient to config, followed by _restore_position's config-to-DB
                # copy on the next load, permanently launders the bad value — see
                # CLAUDE.md/NOTES.md. Self-clearing: once the seek settles, pos
                # advances past _last_saved_pos again and saving resumes normally.
                # Deliberately NOT a plain `is_seeking` guard — if is_seeking ever
                # strands True (a documented failure mode elsewhere in this file),
                # a plain guard would stop saving entirely; this one only skips
                # saves that would regress, so it can never fully strand.
                if self.player.is_seeking and pos < self._last_saved_pos:
                    logger.debug(f"[PERSIST-TRACE] _sync_persistence: SKIP (monotonic guard) "
                                 f"current_file={self.current_file!r} pos={pos!r} last_saved_pos={self._last_saved_pos!r}")
                    return
                percent = (pos / dur) * 100
                # Update config every 0.1% (live cache)
                new_pct = int(percent * 10)
                if new_pct != self._last_saved_pct:
                    logger.debug(f"[PERSIST-TRACE] _sync_persistence: WRITE current_file={self.current_file!r} "
                                 f"pos={pos!r} is_seeking={self.player.is_seeking} last_saved_pos(prev)={self._last_saved_pos!r}")
                    self._last_saved_pct = new_pct
                    self._last_saved_pos = pos
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
                self._trigger_undo(old_pos, new_pos)
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

            self._trigger_undo(old_pos, new_pos)

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

                self._trigger_undo(old_pos, new_pos)

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
        self._show_volume_overlay()

    def _on_volume_slider_pressed(self):
        """Pressing/holding the slider (even without moving it) counts as
        interaction — extend the auto-hide timer so it doesn't fade out
        from underneath the user's cursor."""
        if self.vol_stack.currentIndex() == 1:
            self.vol_hide_timer.start(_INDICATOR_DISMISS_MS)

    def _set_speed(self, value, save=True):
        """Applies a specific speed value."""
        if self.speed_panel:
            self.speed_panel.set_speed(value, self.current_file, save)

    def _nudge_volume(self, direction):
        """Steps volume by ±5 (direction +1/-1) and routes through the volume slider —
        the same path the cover-area wheel uses. Inert with no book loaded. Shared by
        wheelEvent and the Up/Down shortcuts so the step/clamp lives in one place."""
        if not self.current_file:  # no book loaded — volume control inert
            return
        current = self.volume_slider.value()
        step = 5
        if direction > 0:
            new_vol = min(100, current + step)
        else:
            new_vol = max(0, current - step)
        if new_vol != current:
            self.volume_slider.setValue(new_vol)  # -> _on_volume_changed + overlay

    def _nudge_speed(self, direction):
        """Steps speed by ±speed_increment (direction +1/-1) via _set_speed — the same
        path the speed-button wheel uses. Shared by wheelEvent and the Alt+Up/Down
        shortcuts. Held-key (autorepeat) calls self-throttle to _SPEED_NUDGE_THROTTLE_S;
        a single tap always applies exactly one step."""
        if not self.player:
            return
        if self.shortcuts.is_autorepeat:
            now = time.monotonic()
            if now - self._last_speed_nudge_ts < _SPEED_NUDGE_THROTTLE_S:
                return
        step = self.config.get_speed_increment()
        current = self.player.speed or self.config.get_default_speed()
        if direction > 0:
            new_speed = min(8.0, current + step)
        else:
            new_speed = max(0.25, current - step)
        if new_speed != current:
            self._set_speed(new_speed)
            self._last_speed_nudge_ts = time.monotonic()

    def _nudge_chapter(self, direction):
        """Chapter prev/next (direction -1/+1) via handle_prev/handle_next — the same
        methods the chapter nav buttons and progress-slider wheel already use. Bound to
        Ctrl+Left/Ctrl+Right with allow_autorepeat=True; held-key calls self-throttle to
        _CHAPTER_NUDGE_THROTTLE_S (each repeat is a whole chapter, not a small continuous
        adjustment, so this is deliberately much slower than _SPEED_NUDGE_THROTTLE_S — see
        that constant's comment). A single tap always applies exactly one step; handle_prev/
        handle_next themselves already no-op cleanly at the first/last chapter boundary, so
        no boundary check is needed here."""
        if self.shortcuts.is_autorepeat:
            now = time.monotonic()
            if now - self._last_chapter_nudge_ts < _CHAPTER_NUDGE_THROTTLE_S:
                return
        if direction > 0:
            self.handle_next()
        else:
            self.handle_prev()
        self._last_chapter_nudge_ts = time.monotonic()

    def _nudge_long_skip(self, direction):
        """Long skip back/forward (direction -1/+1) via handle_rewind/handle_forward
        (long_skip=True) — the same methods the rewind/forward buttons' right-click
        already use. Bound to Shift+Left/Shift+Right with allow_autorepeat=True; held-key
        calls self-throttle to _LONG_SKIP_THROTTLE_S (each repeat is a large skip, not a
        small continuous adjustment — deliberately much slower than
        _SPEED_NUDGE_THROTTLE_S). A single tap always applies exactly one step."""
        if self.shortcuts.is_autorepeat:
            now = time.monotonic()
            if now - self._last_long_skip_nudge_ts < _LONG_SKIP_THROTTLE_S:
                return
        if direction > 0:
            self.handle_forward(long_skip=True)
        else:
            self.handle_rewind(long_skip=True)
        self._last_long_skip_nudge_ts = time.monotonic()

    def _toggle_mute(self):
        """Keyboard mute (m): drop volume to 0, restore on next press. Minimal, built on
        the existing volume-slider path (no dedicated mute control exists). Inert with no
        book. If the user moved the slider off 0 while 'muted', that counts as unmuted and
        the next press stores fresh rather than restoring a stale pre-mute value."""
        if not self.current_file:  # no book loaded — matches volume inertness
            return
        current = self.volume_slider.value()
        if current > 0:
            # Store then mute. (current > 0 also covers the "moved off 0 while muted" case.)
            self._pre_mute_volume = current
            self.volume_slider.setValue(0)  # -> _on_volume_changed + overlay
        else:
            self._restore_from_mute()

    def _restore_from_mute(self):
        """Shared restore-to-pre-mute-value step: `_toggle_mute`'s un-mute half,
        scroll-up over the muted icon (wheelEvent), and a click on the muted icon
        (_on_muted_icon_clicked). All three mean the same thing ("bring volume back to
        what it was"), so all go through one place rather than duplicating the
        `_pre_mute_volume`-or-100 fallback."""
        restore = self._pre_mute_volume if self._pre_mute_volume else 100
        self._pre_mute_volume = None
        self.volume_slider.setValue(restore)  # -> _on_volume_changed + overlay

    @staticmethod
    def _muted_icon_rect(lbl):
        """The icon's actual rendered rect within muted_icon_label — the label itself
        fills the whole 104x24 vol_stack page (so QStackedWidget's pages stay uniformly
        sized), but the pixmap it centers (AlignCenter, see the theme-apply site that
        calls setPixmap) is a small 14x14 glyph. Click/wheel/cursor must all hit-test
        against THIS rect, not the whole label, or the interactive zone reads as far
        larger than what's visually there — reported live 2026-09-16, the wheel/click
        fix's hit zone matched the slider page's full width instead of the icon."""
        pm = lbl.pixmap()
        if pm is None or pm.isNull():
            return lbl.rect()  # no icon set yet — fall back to the full label
        w, h = pm.width(), pm.height()
        x = (lbl.width() - w) // 2
        y = (lbl.height() - h) // 2
        return QRect(x, y, w, h)

    def _on_muted_icon_clicked(self, event):
        """Click on the muted icon restores volume — same target as `m`/scroll-up (see
        _restore_from_mute). Left-click only, same as every other clickable label in
        this app (_toggle_remaining_time). Gated to the icon's own small rendered rect,
        not the whole vol_stack-sized label — see _muted_icon_rect."""
        if event.button() != Qt.LeftButton:
            return
        if not self.current_file:  # no book loaded — matches volume inertness
            return
        if not self._muted_icon_rect(self.muted_icon_label).contains(event.position().toPoint()):
            return
        self._restore_from_mute()

    def _on_muted_icon_hover(self, event):
        """Hand cursor only over the icon's own small rect, not the whole label —
        mirrors _on_remaining_time_label_hover's pattern for the same reason."""
        self._resync_muted_icon_cursor(event.position().toPoint())

    def _resync_muted_icon_cursor(self, local_pos=None):
        """Re-evaluates muted_icon_label's cursor against `local_pos` (its own local
        coordinates), or against the CURRENT real cursor position via QCursor.pos() when
        no event supplied it. The event-driven path (_on_muted_icon_hover) only runs on
        an actual mouseMoveEvent — but _settle_vol_stack can swap the muted-icon page in
        under a perfectly STATIONARY mouse (e.g. scrolling the slider down to 0 mutes it
        without the cursor moving at all), so the label's cursor property is left stale
        from whenever it was last explicitly set, with nothing to correct it. Reported
        live 2026-09-16: the hand cursor stayed lit at the SLIDER's last cursor position
        after a scroll-to-mute, well outside the icon's small rect on the new page.
        Called from _settle_vol_stack right after switching TO the muted-icon page, per
        this app's own documented QCursor.pos()-poll pattern for exactly this class of
        'a page/state changed under a stationary mouse' gap (see CLAUDE.md's
        sidebar-hotspot MouseMove-generation rule)."""
        if local_pos is None:
            local_pos = self.muted_icon_label.mapFromGlobal(QCursor.pos())
        if self._muted_icon_rect(self.muted_icon_label).contains(local_pos):
            self.muted_icon_label.setCursor(Qt.PointingHandCursor)
        else:
            self.muted_icon_label.unsetCursor()

    def _undo_shortcut(self):
        """Undo (u): reuses the on-screen undo affordance's exact path and its visibility
        gate — a no-op unless the undo overlay is currently shown, matching the button."""
        if self.undo_overlay.isVisible():
            self._perform_undo()

    @staticmethod
    def _label_click_in_text(lbl, x):
        """True if x (in lbl's local coords) falls within the label's
        rendered, right-aligned text rather than its reserved empty space.
        The box is sized for worst-case hour counts the text rarely reaches."""
        text_width = lbl.fontMetrics().horizontalAdvance(lbl.text())
        return x >= lbl.width() - text_width

    def _toggle_remaining_time(self, lbl, event):
        if event.button() != Qt.LeftButton:
            return
        if not self._label_click_in_text(lbl, event.position().x()):
            return
        self.panel_manager.dismiss_sidebar()
        self.show_remaining_time = not self.show_remaining_time
        self.config.set_show_remaining_time(self.show_remaining_time)
        self._update_ui_sync()

    def _on_remaining_time_label_hover(self, lbl, event):
        if self._label_click_in_text(lbl, event.position().x()):
            lbl.setCursor(Qt.PointingHandCursor)
        else:
            lbl.unsetCursor()

    def _on_speed_right_clicked(self, pos):
        """Right click sets the current playback speed as the default speed."""
        self._hide_popups()
        if not self.player: return
        current = self.player.speed or self.config.get_default_speed()
        # Compare BEFORE calling set_default_speed — this is what already_default means:
        # "did this click actually change the stored default," not "is current speed 1.0x".
        already_default = current == self.config.get_default_speed()
        if self.speed_panel:
            self.speed_panel.set_default_speed(current)
        t = self.theme_manager.get_current_theme()
        self.speed_button.shimmer_opacity = t.get("button_speed_shimmer", 0.55)
        self.speed_button.play_shimmer(reverse=already_default)

    def _on_player_speed_changed(self, value):
        """Slot to sync the main UI speed button text with the player engine."""
        if hasattr(self, 'speed_button'):
            self.speed_button.setText(f"{value:.2f}x")

    def _focus_allows_global_shortcuts(self) -> bool:
        """True iff no panel-local widget holds real keyboard focus — i.e. the shortcut
        dispatcher may act on this key. False whenever an open panel/overlay's own widget
        (a text field, the library list, etc.) currently has focus; that widget gets first
        AND FINAL say over the key, even if it declines it (leaves it unaccepted) — the key
        must NOT fall through to global shortcuts just because the local widget didn't want
        it. Every chrome widget in the always-on transport view is Qt.NoFocus (transport
        buttons, speed button, sidebar triggers, sleep label, undo overlay, status/no-book
        buttons), and every panel now explicitly claims focus for one of its own widgets on
        open (see PanelManager._claim_panel_focus) — so "focus is not None and not
        MainWindow itself" is equivalent to "focus is panel-local" by construction; no panel
        enumeration is needed here, and it can't drift out of sync with the panel list."""
        focus = QApplication.focusWidget()
        allowed = focus is None or focus is self
        if not allowed and hasattr(self, 'panel_manager') and self.panel_manager.active_full_panel() is None:
            # [FOCUS-STRAND-TRACE] temporary — 2026-09-08, diagnosing an intermittent live
            # report: closing Settings via Esc WHILE a library rescan is still running left
            # global shortcuts (Space, arrows) dead on the main window afterward. Neither side
            # has reproduced it on demand. Gated on active_full_panel() being None — a
            # panel-local focus while a panel IS genuinely open is normal, constant, correct
            # behavior and would drown this in noise; the actual bug signature is specifically
            # "no panel is open, yet something still holds real focus," which is what this logs
            # the moment it happens — remove once root-caused.
            ancestors = []
            p = focus.parentWidget()
            while p is not None:
                ancestors.append(type(p).__name__)
                p = p.parentWidget()
            scanner = getattr(getattr(self, 'library_controller', None), 'scanner', None)
            scanner_running = scanner.is_running() if scanner is not None else None
            logger.warning(
                f"[FOCUS-STRAND-TRACE] blocked with NO panel open — focus={focus!r} "
                f"visible={focus.isVisible()} enabled={focus.isEnabled()} "
                f"parent_chain={ancestors} scanner_running={scanner_running}"
            )
        return allowed

    def keyPressEvent(self, event):
        # All global key bindings route through the dispatcher (shortcuts.py). It owns
        # binding + spam-guard; the registered handlers own app-state gating. A bound
        # key is consumed even if its handler no-ops on the current state — harmless,
        # MainWindow is the top-level widget so an un-consumed key went nowhere anyway.
        # Gated on _focus_allows_global_shortcuts: a panel-local focused widget (a text
        # field, the library list) owns the key even when it doesn't accept it — see that
        # method's docstring.
        # TEMP INSTRUMENTATION (2026-07-21, [T-KEY-TRACE]): investigating a user-reported
        # regression where T (theme rotate) is sometimes swallowed or fires late while a
        # panel is open. Scoped to Key_T only, not every key, to stay quiet. Remove once
        # the mechanism is confirmed/fixed.
        if event.key() == Qt.Key.Key_T:
            allows = self._focus_allows_global_shortcuts()
            focus = QApplication.focusWidget()
            logger.warning(
                f"[T-KEY-TRACE] keyPressEvent t={time.perf_counter():.6f} "
                f"focus_allows_global_shortcuts={allows} "
                f"focusWidget={focus!r} "
                f"panel_visible={self.panel_manager.is_any_panel_visible() if getattr(self, 'panel_manager', None) else None} "
                f"isAutoRepeat={event.isAutoRepeat()}"
            )
        if self._focus_allows_global_shortcuts() and self.shortcuts.handle_key_event(event):
            return
        super().keyPressEvent(event)

    def _rotate_quote_shortcut(self):
        # TODO: remove before release — testing only
        if not self.current_file and self.quote_section.isVisible():
            self.library_controller._rotate_quote()

    def _open_library_shortcut(self):
        # Open-only: L is a no-op when any overlay is already up, mid-animation, or a
        # sidebar-handoff open is committed (is_overlay_open_or_committed — the same gate
        # _open_library_flow itself now enforces; checked here too so L drops silently
        # rather than delegating). A bare expanded sidebar is NOT blocked: that case flows
        # through _open_library_flow's queued close-then-open. The button being hidden marks
        # the empty-library state (set only there by apply_library_state) — nothing to
        # browse, so no-op. The COOLDOWN_DROP binding guard also drops repeat L during the slide.
        if self.library_trigger_btn.isHidden():
            return
        if self.panel_manager.is_overlay_open_or_committed():
            return
        self.panel_manager._open_library_flow()

    # G/P/A/S/Z mirror _open_library_shortcut exactly: open-only (no toggle-closed
    # branch — pressing the key again while the panel is already open does nothing),
    # gated on is_overlay_open_or_committed() plus that panel's own availability check
    # (mirroring its sidebar button's actual mouse-reachability), then delegate to the
    # matching _open_*_flow (which re-gates and handles the sidebar-queued handoff).

    def _open_tags_shortcut(self):
        if self.db.get_book_count() == 0:
            return
        if self.panel_manager.is_overlay_open_or_committed():
            return
        self.panel_manager._open_tags_flow()

    def _open_playback_shortcut(self):
        # speed_trigger_btn is hidden whenever no book is loaded (_set_interface_visible).
        if self.speed_trigger_btn.isHidden():
            return
        if self.panel_manager.is_overlay_open_or_committed():
            return
        self.panel_manager._open_speed_flow()

    def _open_stats_shortcut(self):
        if self.db.get_book_count() == 0:
            return
        if self.panel_manager.is_overlay_open_or_committed():
            return
        self.panel_manager._open_stats_flow()

    def _open_settings_shortcut(self):
        if self.db.get_book_count() == 0:
            return
        if self.panel_manager.is_overlay_open_or_committed():
            return
        self.panel_manager._open_settings_flow()

    def _open_sleep_shortcut(self):
        # sleep_trigger_btn is hidden whenever no book is loaded (_set_interface_visible).
        if self.sleep_trigger_btn.isHidden():
            return
        if self.panel_manager.is_overlay_open_or_committed():
            return
        self.panel_manager._open_sleep_flow()

    def _open_sprint_shortcut(self):
        # sprint_trigger_btn is hidden whenever no book is loaded (_set_interface_visible).
        # Mirrors _open_sleep_shortcut exactly.
        if self.sprint_trigger_btn.isHidden():
            return
        if self.panel_manager.is_overlay_open_or_committed():
            return
        self.panel_manager._open_sprint_flow()

    def mousePressEvent(self, event):
        # Do not hide popups if clicking inside the panels
        for panel in [self.library_panel, self.settings_panel, self.speed_panel, self.sleep_panel,
                      self.sprint_panel, self.stats_panel, self.tags_panel, self.book_detail_panel]:
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
            # Also sync the list selection visually — but only while the dropdown is actually
            # visible. setCurrentRow() is a real QAbstractItemView selection-model update +
            # repaint-scheduling cost, and this method fires from multiple triggers in quick
            # succession during book-load (populate-driven call + chapter_changed re-fire after
            # seek-settle) while the list is provably hidden — landing in the flow animation's
            # opening frames (Regime A, see NOTES.md 2026-07-14/17). Skipping it while hidden is
            # safe: _show_chapter_dropdown always re-derives and re-sets the row itself from a
            # fresh position walk when it actually opens the list, so no stale selection can leak
            # through here.
            if self.chapter_list_widget.isVisible():
                logger.debug(
                    f"t={time.perf_counter():.6f} [_update_chapter_label_from_index] "
                    f"setCurrentRow({index}) isVisible=True "
                    f"scroll_before={self.chapter_list_widget.verticalScrollBar().value()}"
                )
                self.chapter_list_widget.setCurrentRow(index)
                logger.debug(
                    f"t={time.perf_counter():.6f} [_update_chapter_label_from_index] "
                    f"scroll_after={self.chapter_list_widget.verticalScrollBar().value()}"
                )

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
        self._cover_placeholder.clear()
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
        import traceback
        _caller_frame = traceback.extract_stack()[-2]
        logger.debug(f"[STUTTER-TRACE] t={time.perf_counter():.6f} _load_cover_art: ENTRY "
                     f"file_path={file_path!r} "
                     f"caller={_caller_frame.filename.split('/')[-1]}:{_caller_frame.lineno} "
                     f"in {_caller_frame.name}")
        if not file_path:
            self.current_cover_pixmap = QPixmap()
            self._cover_placeholder.clear()
            self.cover_art_label.hide()
            self.metadata_label.hide()
            # request_clear_cover_theme (not clear_cover_theme directly): this teardown
            # path can run while a panel is still visibly open/animating-closed (e.g.
            # excluding the playing book from Book Detail opened via Stats, or from the
            # Library — _close_book_detail_flow's slide-out is not synchronous, so the
            # panel is still isVisible()==True when _on_book_removed reaches here).
            # Mirrors _rotate_theme's existing panel-open deferral — see
            # ThemeManager.request_clear_cover_theme.
            self.theme_manager.request_clear_cover_theme()
            return
        book = self.db.get_book(file_path)
        active = self.db.get_active_cover(file_path)
        self._cover_fit_mode = active['fit_mode'] if active else 'fit'

        active_path   = active['file_path'] if active else None
        fallback_path = book.cover_path if book else None

        # No cover source at all → show placeholder logo + author/title
        if not active_path and not fallback_path:
            self._show_no_cover_state(book)
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
            self._show_no_cover_state(book)

    def _show_no_cover_state(self, book) -> None:
        """Clear cover state and show the placeholder + text metadata for a
        book with no available cover art. Used both when there's no cover
        source (no active/fallback path) and when extract_cover found nothing.
        The two former call sites were byte-for-byte identical."""
        self.current_cover_pixmap = QPixmap()
        # Same stand-down _apply_main_cover already has for the has-cover case: if a
        # panel is still visible (including still mid-slide-closing, e.g. the book-switch
        # flow's hide_all_panels() call, whose animation is often still finishing when
        # _load_cover_art runs off the queued singleShot(0)), defer the theme revert
        # instead of calling clear_cover_theme() immediately. Without this, switching TO
        # a placeholder (no-cover) book had NO stand-down at all — clear_cover_theme()
        # always fired synchronously, unlike apply_cover_theme()'s already-deferred path,
        # so only that one direction of a book switch could land the ~150-300ms
        # _apply_stylesheets/_flush_deferred_restyle_now cost mid-flow-animation (found
        # 2026-07-18 via a live, direction-specific repro: cover->placeholder stuttered,
        # placeholder->cover did not — see NOTES.md). _PENDING_CLEAR_COVER_THEME is a
        # distinct sentinel (not a pixmap) so _apply_pending_cover_theme's drain knows to
        # call clear_cover_theme() instead of apply_cover_theme() for this case.
        if self.panel_manager and self.panel_manager.is_any_panel_visible():
            self._pending_cover_pixmap = _PENDING_CLEAR_COVER_THEME
        else:
            self.theme_manager.clear_cover_theme()
            self._pending_cover_pixmap = None
        self._show_cover_placeholder()
        self.metadata_label.show()
        if book:
            text = f"{book.author} - {book.title}" if book.author else (book.title or "")
        else:
            text = "Unknown book"
        self.metadata_label.setText(text)

    def _placeholder_color(self):
        t = _resolve_theme(self.theme_manager._current_theme_name)
        return t.get('placeholder_cover', t.get('library_narrator', t.get('text', '#888888')))

    def _show_cover_placeholder(self):
        self._cover_placeholder.show(self.cover_art_label, self._placeholder_color())

    def _on_cover_error(self, message: str) -> None:
        """CoverPanel's add-cover flow failed (too large, unreadable, or a
        save/DB failure). Transient (non-sticky) banner, 3s default — matches
        the old _error_label's own timeout."""
        self._update_status_banner_ui(
            text=message,
            show_banner=True, auto_hide=True,
        )

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

    def _on_sidebar_hotspot_fired(self):
        """SidebarHotspot's on_fire callback, after its hover-intent delay elapses.
        Re-checks hotspot-enabled (the setting may have been toggled off during the
        delay window) and the one-overlay-at-a-time gate (same gate every _open_*_flow
        uses) before opening — cheap insurance against a race with another open path
        firing during the same ~200ms window. Mirrors the empty-library guard the
        right-click path already has."""
        if not self.config.get_sidebar_hotspot_enabled():
            return
        if self.db.get_book_count() == 0:
            return
        pm = self.panel_manager
        if pm.is_overlay_open_or_committed():
            return
        pm._toggle_sidebar()
        pm._sidebar_opened_via = "hotspot_hover"

    def _on_drag_area_pressed(self, event):
        if event.button() == Qt.LeftButton:
            if self.db.get_book_count() == 0:
                return # Do not hide popups if just dragging window in empty state
            
            if self.panel_manager.is_any_panel_visible():
                self.panel_manager.hide_all_panels()
            elif self.current_file:
                self.toggle_play_pause()
        elif event.button() == Qt.RightButton:
            # TEMP INSTRUMENTATION (2026-07-28, user-requested): right-click on the
            # main window to toggle the sidebar "also has misses, especially after
            # the panel was closed". Both early-returns below are silent, so a
            # swallowed click currently leaves no trace at all. At WARNING so it is
            # greppable without DEBUG; pairs with handle_drag_area_right_click's own
            # existing branch logging (DEBUG) in panels.py.
            _elapsed = (self._dialog_close_time.elapsed()
                        if self._dialog_close_time.isValid() else None)
            if self._dialog_close_time.isValid() and self._dialog_close_time.elapsed() < 500:
                logger.warning(
                    f"[SIDEBAR-TRACE] right-click SWALLOWED by the post-dialog guard "
                    f"({_elapsed}ms < 500ms since a file dialog closed) "
                    f"t={time.perf_counter():.6f}"
                )
                return
            # Guard: Only allow sidebar right-click toggle if books are indexed
            _count = self.db.get_book_count()
            if _count > 0:
                pm = self.panel_manager
                logger.warning(
                    f"[SIDEBAR-TRACE] right-click ACCEPTED "
                    f"sidebar_expanded={pm.sidebar_expanded} "
                    f"any_panel_visible={pm.is_any_panel_visible()} "
                    f"any_animating={pm._any_panel_animating()} "
                    f"dialog_guard_elapsed={_elapsed} t={time.perf_counter():.6f}"
                )
                self.panel_manager.handle_drag_area_right_click(event)
                logger.warning(
                    f"[SIDEBAR-TRACE] right-click DONE "
                    f"sidebar_expanded={pm.sidebar_expanded} "
                    f"any_panel_visible={pm.is_any_panel_visible()} "
                    f"t={time.perf_counter():.6f}"
                )
            else:
                logger.warning(
                    f"[SIDEBAR-TRACE] right-click SWALLOWED — no indexed books "
                    f"(get_book_count()={_count}) t={time.perf_counter():.6f}"
                )

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
            # Any pending smart rewind belongs to whatever pause armed it, not to a
            # fresh restart-from-0 of this book — see the same guard in
            # _on_book_selected_from_library.
            self._last_pause_timestamp = None
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
                rewound = self.player.apply_smart_rewind(self._last_pause_timestamp, self.config.get_smart_rewind_wait(), self.config.get_smart_rewind_duration())
                if rewound:
                    self._last_pause_timestamp = None

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
            # Called unconditionally (not just for long_skip): a single regular-skip
            # tap stays silent on its own (default 10s < the 60s gate), but repeated
            # taps or a held button/key (both auto-repeat — see the button/Binding
            # setup) accumulate via save_seek_position's coalescing anchor exactly
            # like the chapter-slider wheel scrub, so a spree of regular skips now
            # also earns Undo once it crosses 60s cumulative. Read the position BACK
            # from the player rather than using the pre-computed new_pos: seek_async
            # silently no-ops within 2s of EOF/near a VT file's own end (see "DO NOT
            # seek within 2 seconds of a file's duration"), and near the start-of-book
            # floor here it still seeks, just to a small, undo-unworthy distance.
            # Either way, the ACTUAL resulting position (time_pos, which only updates
            # when seek_async genuinely set _seek_target/_logical_pos) is what the
            # undo-worthiness distance check must be measured against, not the
            # requested target — using the target would show Undo for a skip that
            # never moved playback at all. Standard distance gate (not threshold=0.0):
            # see _trigger_undo's docstring.
            self._trigger_undo(old_pos, self.player.time_pos or old_pos)

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
            # See handle_rewind's matching comment: called unconditionally now (a
            # spree of regular-skip taps/holds earns Undo the same way a wheel scrub
            # spree does), and reads the position back rather than using new_pos, so a
            # skip that seek_async silently refused (within 2s of EOF) doesn't show
            # Undo for a jump that never happened.
            self._trigger_undo(old_pos, self.player.time_pos or old_pos)

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
            # Standard distance gate (not threshold=0.0): restarting from a position
            # already at/near 0:00 is a genuine but undo-unworthy no-op-ish seek —
            # showing Undo there is confusing since there's nothing meaningful to
            # undo back to. See handle_rewind/handle_forward's matching fix.
            self._trigger_undo(old_pos, 0.0)

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
                self._trigger_undo(old_pos, target)

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
                self._trigger_undo(old_pos, target)

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
        self._trigger_undo(old_pos, self.player.time_pos or 0)

    def _trigger_undo(self, old_pos, new_pos, threshold=None):
        """Slides in the floating undo button.

        Always calls save_seek_position — it decides internally, from the
        CUMULATIVE distance since the current undo anchor, whether this seek
        is worth showing the overlay for; it is not gated by the caller on
        this single seek's own displacement. See save_seek_position's
        docstring for why: a caller-side gate on the single seek's own
        displacement was the 2026-09-16 bug (a spree of small seeks, e.g.
        Next through several short chapters, could clear the threshold in
        aggregate while never once qualifying individually — the anchor
        captured by the first qualifying press was a mid-spree position, not
        the position before the spree began).

        `threshold` defaults to the standard 60s-at-speed distance gate used
        by every seek-driven call site (slider release/right-click, chapter
        nav, chapter-slider release/wheel). Pass `threshold=0.0` for a call
        site whose own semantics are already "always show undo regardless of
        distance" (the long-skip buttons) — passing 0.0 here still routes
        through save_seek_position so the anchor-capture/coalescing behavior
        stays identical, it just never suppresses the overlay.
        """
        duration = self.config.get_undo_duration()
        if threshold is None:
            speed = self.player.speed or 1.0
            threshold = 60 * speed

        if not self.player.save_seek_position(old_pos, new_pos, duration, threshold=threshold):
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
            self.panel_manager.dismiss_sidebar()
            if not self.current_file:  # no book loaded — volume control inert
                return
            self._nudge_volume(1 if event.angleDelta().y() > 0 else -1)
            event.accept()
        elif self.volume_slider.underMouse():
            # underMouse() is only True while this specific vol_stack page is the one
            # actually showing (QStackedWidget only shows one page at a time), so this
            # deliberately does NOT also catch scroll over the empty vol_stack area when
            # the slider isn't visible — see the TODO entry this closes for why that
            # distinction was made on purpose (scrolling nothing shouldn't change volume).
            if not self.current_file:
                return
            self._nudge_volume(1 if event.angleDelta().y() > 0 else -1)
            event.accept()
        elif (self.muted_icon_label.underMouse()
                and self._muted_icon_rect(self.muted_icon_label).contains(
                    self.muted_icon_label.mapFrom(self, event.position().toPoint()))):
            # Scroll up restores to the pre-mute value (same target _toggle_mute's 'm'
            # restore uses — see _restore_from_mute). Scroll down is a deliberate no-op:
            # there's nothing to decrease from 0, and un-muting on a DOWN scroll would
            # read backwards (see CLAUDE.md/this TODO entry for the design decision).
            # Gated to the icon's own small rendered rect, not the whole vol_stack-sized
            # label — see _muted_icon_rect (the click/cursor handlers use the same gate).
            if not self.current_file:
                return
            if event.angleDelta().y() > 0:
                self._restore_from_mute()
            event.accept()
        elif self.speed_button.underMouse():
            if not self.player: return
            self.panel_manager.dismiss_sidebar()
            self._nudge_speed(1 if event.angleDelta().y() > 0 else -1)
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
            self.panel_manager.dismiss_sidebar()
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
                # Backward scroll while already parked exactly on the current
                # chapter's own start (landed there via a prior boundary-clamped
                # scroll, or via Prev/a chapter-list click) must act on the
                # PREVIOUS chapter instead — otherwise curr_chap_idx keeps
                # resolving to the same chapter and the clamp below re-snaps to
                # the same spot forever, permanently stalling backward scroll at
                # every boundary. Forward doesn't need the mirror case: landing
                # on chap_end (== the next chapter's start) already re-resolves
                # curr_chap_idx into that next chapter on the following scroll.
                ref_idx = curr_chap_idx
                if (delta < 0 and curr_chap_idx > 0
                        and current_pos <= chap_list[curr_chap_idx].get('time', 0) + _CHAPTER_WALK_TOLERANCE):
                    ref_idx = curr_chap_idx - 1
                chap_start = chap_list[ref_idx].get('time', 0)
                if ref_idx + 1 < len(chap_list):
                    chap_end = chap_list[ref_idx + 1].get('time', 0)
                else:
                    chap_end = self.player.duration or 0
                chap_dur = chap_end - chap_start
                # Step is a fraction of the reference chapter's own (logical) length —
                # already speed-independent, since chapter_list times don't move with
                # speed. Do NOT scale by speed here (see NOTES.md 2026-07-12 "Chapter
                # slider wheel step scaled by speed twice").
                skip = max(10.0, chap_dur * 0.10)
                if delta > 0:
                    # Never overshoot past this chapter's own end in one scroll — land
                    # exactly on the next chapter's start instead, even if less than a
                    # full step remains. A second scroll continues from there.
                    new_pos = min(current_pos + skip, chap_end)
                else:
                    # Mirror image: never undershoot past the reference chapter's own
                    # start in one scroll — land exactly on it instead of crossing
                    # further back. A second scroll continues from there.
                    new_pos = max(current_pos - skip, chap_start)
            else:
                # No chapters: falls back to the flat configured skip, same
                # semantics as the skip/long-skip buttons — a fixed amount of
                # *listened* content, so this one DOES scale by speed.
                speed = self.player.speed or 1.0
                skip = self.config.get_skip_duration() * speed
                if delta > 0:
                    new_pos = current_pos + skip
                else:
                    new_pos = current_pos - skip
            new_pos = max(0, min(self.player.duration or 0, new_pos))
            self.player.seek_async(new_pos)
            # Standard distance gate (not threshold=0.0): this is a fine intra-chapter
            # scrub, not a deliberate big jump — a single tick on a short chapter (e.g.
            # a 4m04s chapter's 10%-of-length step is only ~24s) showed Undo for a
            # trivial nudge. Read the position back rather than using new_pos, same
            # reasoning as handle_rewind/handle_forward: a step clamped to within 2s of
            # EOF is silently refused by seek_async and must not show Undo either.
            self._trigger_undo(current_pos, self.player.time_pos or current_pos)
            event.accept()
        else:
            super().wheelEvent(event)

    def _show_volume_overlay(self):
        """Triggers the volume slider fade-in and starts the auto-hide timer.
        Skipped when volume just hit 0 — that case jumps straight to whatever
        _settle_vol_stack() resolves to (mute icon, or a sleep-just-armed
        confirmation) instead of previewing an empty slider first."""
        if self.volume_slider.value() == 0:
            self.vol_hide_timer.stop()
            self.vol_fade_anim.stop()
            self.vol_opacity.setOpacity(0.0)
            self._settle_vol_stack()
            return
        self.vol_hide_timer.stop()
        self.vol_stack.setCurrentIndex(1)
        if self.vol_opacity.opacity() < 1.0:
            self.vol_fade_anim.stop()
            self.vol_fade_anim.setStartValue(self.vol_opacity.opacity())
            self.vol_fade_anim.setEndValue(1.0)
            self.vol_fade_anim.start()
        self.vol_hide_timer.start(_INDICATOR_DISMISS_MS)

    def _fade_out_volume(self):
        """Starts the volume slider fade-out."""
        self.vol_fade_anim.stop()
        self.vol_fade_anim.setStartValue(self.vol_opacity.opacity())
        self.vol_fade_anim.setEndValue(0.0)
        self.vol_fade_anim.start()

    def _on_vol_fade_finished(self):
        if self.vol_opacity.opacity() == 0:
            self._settle_vol_stack()

    def _settle_vol_stack(self):
        """Picks the vol_stack page to rest on: the muted icon if volume is 0,
        else the shared sleep/sprint indicator label (which may be empty text —
        sleep and sprint are mutually exclusive, see _sleep_arm_gate/_sprint_arm_gate,
        so the label never needs to show both at once). Mute takes priority over
        the label — the one exception is a freshly-armed sleep timer OR sprint
        while muted, which shows a transient confirmation first (see
        _sleep_just_set/_sprint_just_set / _on_sleep_display_text_updated /
        _on_sprint_display_text_updated). Callers that must not disturb an
        in-progress volume overlay should check vol_stack.currentIndex() == 1
        themselves first."""
        muted = self.volume_slider.value() == 0
        if muted and not self._sleep_just_set and not self._sprint_just_set:
            self.vol_stack.setCurrentIndex(2)
            # The page can swap in under a stationary mouse (e.g. wheel-scrolling the
            # slider down to 0) — nothing else re-evaluates the icon's cursor in that
            # case. See _resync_muted_icon_cursor's docstring.
            self._resync_muted_icon_cursor()
        else:
            self.vol_stack.setCurrentIndex(0)

    def _on_sleep_display_text_updated(self, text):
        was_armed = bool(self.sleep_timer_label.text())
        self.sleep_timer_label.setText(text)
        self._resync_indicator_label_cursor()
        newly_armed = bool(text) and not was_armed
        if newly_armed and self.volume_slider.value() == 0:
            # Sleep was just (re)armed while muted — show the sleep text as a
            # confirmation for _INDICATOR_DISMISS_MS, then revert to the mute icon.
            self._sleep_just_set = True
            self.sleep_confirm_timer.start(_INDICATOR_DISMISS_MS)
        elif not text:
            # Sleep disarmed — drop any stale pending confirmation so a later
            # mute doesn't incorrectly re-show old sleep text.
            self.sleep_confirm_timer.stop()
            self._sleep_just_set = False
        if self.vol_stack.currentIndex() != 1:
            # Volume overlay (index 1) takes precedence over both the sleep
            # label and the muted icon; otherwise re-settle now so a sleep
            # timer starting/stopping immediately shows/hides its countdown
            # even if the muted icon was resting.
            self._settle_vol_stack()

    def _on_sleep_confirm_timeout(self):
        self._sleep_just_set = False
        if self.vol_stack.currentIndex() != 1:
            self._settle_vol_stack()

    def _handle_tab_escape(self, event) -> bool:
        """App-wide Tab/Escape policy. Returns True iff this consumed the event.

        Runs from the app-level eventFilter (before the focused widget's own keyPressEvent
        during dispatch), so it must DEFER to focused text fields rather than preempt them.
        BookDetailPanel's own QApplication filter is installed later (in its showEvent) and so
        runs BEFORE this one — its Escape (edit-cancel / close) fires first while detail is open,
        and this method is never reached for that case.
        """
        key = event.key()
        if key not in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab, Qt.Key.Key_Escape):
            return False
        if not hasattr(self, 'panel_manager'):
            return False

        # Defer to a focused text field: the library search / sleep custom-minutes / tag-name
        # editors own Escape (clear+defocus) and, for the search field, Tab (list toggle) via
        # their own keyPressEvent. Never preempt them.
        focus = QApplication.focusWidget()
        if isinstance(focus, QLineEdit):
            return False

        if key == Qt.Key.Key_Escape:
            # Close whichever panel is open (book_detail handled by its own earlier filter).
            # If nothing is open, do nothing (main-window Escape is deliberately deferred).
            return self.panel_manager.escape_active_panel()

        # Tab / Backtab.
        panel = self.panel_manager.active_full_panel()
        if panel == "library":
            # search_field owns Tab-away-from-itself (clearFocus(), landing in a "nothing
            # focused" state — see library.py's event() override on search_field), deferred
            # above via the isinstance(focus, QLineEdit) check. Every OTHER focus state while
            # Library is open — nothing focused, or (shouldn't normally happen anymore, but
            # handled the same way for safety) the list itself — sends Tab to search_field,
            # completing a QLineEdit <-> nothing two-state cycle. QListView is deliberately NOT
            # part of the Tab cycle (2026-07-10): tabbing there used to call scrollTo() on
            # whatever currentIndex() happened to be, and since mouse hover also sets
            # currentIndex(), tabbing while the mouse hovered a partially-visible book silently
            # scrolled the list — confirmed live, removed. The list is reachable by arrow keys
            # only now (see the arrow-key branch below).
            #
            # Drop the keyboard-selection highlight instantly (no fade) whenever Tab moves
            # focus away from the list — the user's own framing: leaving the list via Tab
            # should not leave a highlight lingering on its own ~2.5s timer, since Tab reads as
            # "I'm done with the list" rather than a momentary pause. Deliberately does NOT
            # touch mouse hover (timeless regardless of Tab, per the user) or List mode's own
            # fade-based keyboard highlight (_clear_keyboard_selection only touches
            # _kbd_selected_path/_kbd_alpha — the tint/overlay other modes use — never
            # _kbd_hover_path, which is what List mode reads; calling it is already a no-op for
            # List, so no mode check is needed here).
            self.library_panel._clear_keyboard_selection()
            self.library_panel.search_field.setFocus(Qt.FocusReason.TabFocusReason)
            return True
        # "sprint" was missing here until 2026-09-07 (reported live: "Tab and Shift+Tab don't
        # work" while testing Sprint's new arrow navigation) — a pre-existing gap, not
        # something this session's arrow-nav work introduced: panel_tab_widgets("sprint") and
        # _focus_settings_control both already worked generically for any panel, this dispatch
        # tuple was simply never updated when SprintPanel was added.
        if panel in ("settings", "speed", "sleep", "sprint", "stats"):
            widgets = self.panel_manager.panel_tab_widgets(panel)
            if not widgets:
                return True  # nothing focusable — still swallow so Tab can't escape the panel
            # Shift+Tab arrives as Key_Backtab on most platforms, but some deliver Key_Tab with
            # the Shift modifier — treat either as a backward move.
            backward = (key == Qt.Key.Key_Backtab
                        or bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier))
            forward = not backward
            try:
                idx = widgets.index(focus)
                nxt = widgets[(idx + (1 if forward else -1)) % len(widgets)]
            except ValueError:
                # Current focus isn't one of the panel's widgets: enter at the first (Tab) or
                # last (Backtab).
                nxt = widgets[0] if forward else widgets[-1]
            # Leaving the Excluded Books popup via Tab/Shift+Tab must collapse it too, same as
            # the arrow-key exit path (ExcludedBooksPopup.keyPressEvent's Up-at-row-0 ->
            # _on_excluded_books_exit_upward) — Tab-cycling is a second, independent way to
            # leave this widget that bypassed that collapse entirely (reported live 2026-09-05:
            # an expanded popup stayed expanded, covering ground the next Tab stop's own focus
            # then shared the screen with). `nxt is not focus` guards the pathological
            # single-widget-panel case where Tab/Backtab would otherwise "leave" onto itself.
            if focus is self.excluded_books_popup and nxt is not focus:
                self._collapse_excluded_books()
            # Leaving the Themes swatch grid via Tab/Shift+Tab must stop its preview too, same
            # as every arrow-key exit already does (_handle_themes_swatch_arrows's four
            # kbdnav_exit_swatch_grid() call sites) — Tab-cycling is a second, independent way
            # to leave this widget that bypassed the stop entirely, same shape as the Excluded
            # Books collapse fix immediately above (reported live 2026-09-06: "leaving the
            # swatch with a Tab or arrow should stop the preview, similar to how mouse preview
            # works" — the arrow half was already correct, only Tab was missing it).
            if focus is self.theme_manager.swatch_box and nxt is not focus:
                self.theme_manager.kbdnav_exit_swatch_grid()
            # Via _focus_settings_control so a list box lands ON a path rather than merely
            # focusing the empty box — same reason the arrow navigation routes through it.
            # Backtab arrives from below, so it should land on the box's LAST path.
            self._focus_settings_control(nxt, from_below=backward)
            return True
        # tags / book_detail / chapter_list / no panel open: Tab is a full no-op. Swallow it so
        # (together with the NoFocus chrome buttons) it can never move focus anywhere.
        return True

    def _pickup_hover_target(self, focus, rows: list, panel_key: str = "settings"):
        """Hover-pickup: on every arrow-key press (not merely when focus is somewhere
        invalid — see the CORRECTION note below), check whether the mouse has genuinely
        moved since the last pickup check (via `_pickup_cursor_anchor`/
        _KBDNAV_CURSOR_JITTER_PX — see the SECOND correction note below for why this is
        a dedicated anchor, not `_kbdnav_cursor_anchor`) and, if so, ask Qt directly
        what real widget it is over now (QApplication.widgetAt(QCursor.pos())). If
        that's a recognised member of `rows` (or the panel's tab bar, for
        "settings"/"stats"), give it real Qt focus so the caller's own lookup finds it
        and proceeds exactly as if focus had started there. Returns `focus` unchanged
        when there's nothing to pick up.

        CORRECTION (2026-09-15, live-reported): the first version of this method only
        ran when `focus` wasn't already a recognised row member — reasoning that a
        "pickup" only makes sense when focus is somewhere invalid. That is wrong for
        this app's actual modality: real Qt focus is ALWAYS on a valid row member while
        a keyboard-navigable panel is open (_claim_panel_focus's own invariant — some
        widget always holds focus), so that gate was permanently false and pickup could
        never fire at all except in a corner case that doesn't occur in practice.
        Reported live as "it picks up from the place from where key nav was last in, not
        the mouse." The actual signal needed is most-recent-input-wins: has the mouse
        moved since the keyboard last drove, REGARDLESS of whether current focus is
        otherwise perfectly valid. `[kbdnav="true"]` suppresses native `:hover` on these
        buttons while keyboard mode is active, so the mouse resting somewhere produces no
        visible feedback at all until it actually MOVES — which is exactly what the
        jitter check answers, and why a plain "is the mouse over something different"
        check (with no movement requirement) would be wrong too: it would hijack focus
        away from a stationary keyboard cursor just because the mouse happens to rest
        over some other button, which was explicitly rejected in this plan's own design
        notes ("On panel open, arrows always start from the default... until the mouse
        genuinely moves").

        Uses `_pickup_cursor_anchor` — a SEPARATE variable from `_kbdnav_cursor_anchor`,
        READ AND ADVANCED here, never touched by _set_keyboard_nav_active (see that
        attribute's own __init__ comment for exactly why the two can't share one
        anchor: _set_keyboard_nav_active(True) fires on EVERY qualifying keypress, not
        just the first, and overwrites _kbdnav_cursor_anchor to the CURRENT mouse
        position on the very press this method would otherwise need "before this
        press" data from). Two prior attempts at this exact feature (TODO.md,
        "Attempt 1"/"Attempt 2") broke hover suppression app-wide by writing to THAT
        shared anchor from a pickup site; this method writes to a wholly separate one
        instead, so it can never step on _on_kbdnav_cursor_poll's own hand-back check.
        QApplication.widgetAt is the live hit-test itself (confirmed directly,
        2026-09-15; also already used elsewhere in this app, transport_bar_blur.py).

        Mirrors Tags' own ScrollHoverTracker-driven pickup (_handle_tag_list_keys): confirmed
        directly against that method that it moves PAST the hovered row on the very first
        press, not landing ON it first — so this does the same: redirect focus, then let the
        rest of the caller's method run unmodified on the very same keypress."""
        anchor = self._pickup_cursor_anchor
        if anchor is None:
            return focus
        pos = QCursor.pos()
        if (abs(pos.x() - anchor.x()) < _KBDNAV_CURSOR_JITTER_PX
                and abs(pos.y() - anchor.y()) < _KBDNAV_CURSOR_JITTER_PX):
            return focus  # hasn't moved since the last pickup check
        widget = QApplication.widgetAt(pos)
        if widget is None or widget is focus:
            return focus
        if panel_key in ("settings", "stats"):
            tab_bar = self._kbdnav_tab_bar_for(panel_key)
            if widget is tab_bar:
                self._pickup_cursor_anchor = pos
                widget.setFocus(Qt.FocusReason.OtherFocusReason)
                return widget
        if not any(widget is w for row in rows for w in row):
            return focus  # not a control this caller recognises — nothing to pick up
        self._pickup_cursor_anchor = pos
        widget.setFocus(Qt.FocusReason.OtherFocusReason)
        return widget

    def _handle_settings_arrows(self, event) -> bool:
        """Arrow-key navigation for the button-row settings tabs (Look, Controls, Audio,
        Library, Themes — see panels._ARROW_NAV_TABS). Returns True iff this consumed the
        event. Called from the app-level eventFilter, same contract as _handle_tab_escape.

        Themes' rows come from panels.themes_tab_rows(), not the generic per-tab-layout walk
        (see that method) — its swatch grid is a single one-item row here (`swatch_box`,
        same shape as folder_list_widget) that then owns its own internal 2-D position once
        focus reaches it; see _handle_themes_swatch_arrows for that internal navigation.

        Overrides Qt's native arrow behaviour, which treats a QHBoxLayout of buttons as a flat
        chain: natively Up/Down do the same thing as Left/Right (step one button sideways),
        which is useless on a tab of stacked rows. Here (as of 2026-09-10 — see below for why
        Left/Right changed from deferring to Qt's native chain):

            Down   from the tab bar -> first button of the FIRST row
                   from a button    -> first button of the NEXT row
                   from the LAST row -> wraps to the tab bar
            Up     from the tab bar -> first button of the LAST row
                   from a button    -> first button of the PREVIOUS row
                   from row 0       -> back to the tab bar
            Left   at row 0's first button -> back to the tab bar
                   otherwise                -> previous button in the row; at a row's first
                                                button, previous row's LAST button
            Right  at the LAST row's last button -> wraps to the tab bar
                   otherwise                       -> next button in the row; at a row's last
                                                       button, next row's FIRST button

        Full reading-order wrap on all four directions — the tab bar sits at both ends, reachable
        from any edge of the grid, mirroring Speed/Sleep/Sprint's own _handle_flat_panel_arrows
        (which has no tab bar to wrap to, so it swallows at its own edges instead).

        Up/Down always land on the row's FIRST button rather than trying to preserve a column:
        row widths differ both within and across tabs (Look runs 5, 3, 3, 4, 3 and 2-or-4;
        Controls runs 4 and 2), so there is no honest column to preserve and a clamped guess
        would land unpredictably.

        Return/Enter activate the focused control, alongside the Space that Qt already provides
        (see the branch below for why Enter needed adding and Space did not).

        Tab/Shift+Tab are deliberately NOT touched — _handle_tab_escape still owns those, and
        their flat cycle through every control stays exactly as it was.

        Fully generic over the rows: everything is derived per keypress from
        PanelManager.settings_tab_button_rows(), which reads the live layout. A row whose buttons
        are currently hidden (Look's Chapter-notches Animation pair when notches are Off) is
        simply not a stop, and a tab is opted in purely by joining _ARROW_NAV_TABS — no
        per-tab code lives here."""
        key = event.key()
        if key not in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Left, Qt.Key.Key_Right,
                       Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space, Qt.Key.Key_Delete):
            return False
        if not self._settings_is_active():
            return False
        focus = QApplication.focusWidget()
        if isinstance(focus, QLineEdit):
            return False  # never preempt a text field's own cursor keys
        rows = self.panel_manager.settings_tab_button_rows()
        if not rows:
            return False
        # Hover pickup (2026-09-15): checked on EVERY qualifying keypress, not just when
        # focus is somewhere invalid — real Qt focus is always on a valid control while
        # this panel is open, so gating on "focus not found" never fired in practice
        # (see _pickup_hover_target's own CORRECTION note for the live report that
        # caught this). The method itself is the real gate: it only redirects focus when
        # the mouse has genuinely moved since keyboard mode last asserted.
        focus = self._pickup_hover_target(focus, rows, "settings")

        # Space AND Return/Enter both toggle the current row's selection on a focused LIST BOX —
        # deliberately the SAME action on both keys, not split into "add"/"remove". A live report
        # (2026-09-05) said as much directly after an earlier version tried the split: Qt's own
        # native Space on this widget only ever grows the selection (confirmed live, never
        # verified to reproduce this specific widget's real behaviour in an offscreen harness —
        # see the CLAUDE.md scope note on trusting headless verification for settings-panel
        # widgets), so Space is claimed here too instead of left to fall through to Qt.
        # Consumes both keys unconditionally on this widget so neither ever reaches Qt's own
        # (different, non-toggling) handling.
        # Scoped to folder_list_widget specifically, NOT any QListWidget: ExcludedBooksPopup is
        # also a QListWidget (found live 2026-09-05, before it ever reached the user — this
        # branch would have intercepted Space/Enter meant for the popup's own restore action,
        # since setSelected is a harmless no-op under its NoSelection mode but the unconditional
        # `return True` still would have swallowed the key before ExcludedBooksPopup's own
        # keyPressEvent ever saw it). ExcludedBooksPopup manages its own keys entirely — this
        # method must never intercept anything meant for it.
        if focus is self.folder_list_widget and key in (
                Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            row = focus.currentRow()
            if row >= 0:
                item = focus.item(row)
                if item is not None:
                    item.setSelected(not item.isSelected())
            return True

        # Del removes the CURRENT-ROW path immediately — deliberately independent of the
        # selection Space/Enter builds above. Requiring a Space-select first before Del could act
        # would be redundant with a dedicated delete key's whole purpose (reported live
        # 2026-09-05: "it should delete the highlighted path without requiring the user to select
        # it with Space first"). Routes through the same _remove_folders core the Remove button
        # uses, just with a single-path list built from the cursor instead of from selection —
        # see LibraryController._remove_folder_at_cursor.
        if focus is self.folder_list_widget and key == Qt.Key.Key_Delete:
            self.library_controller._remove_folder_at_cursor()
            return True

        # Return/Enter activate the focused button, alongside Space. Qt gives a QPushButton
        # Space for free but ignores Return/Enter unless it is a dialog's default button
        # (measured 2026-09-05: Space fires clicked(), Return and Enter do not; autoDefault and
        # isDefault are both False here, and there is no dialog to set them). So Enter was doing
        # nothing at all, and accepting it costs no existing behaviour.
        #
        # Matches every other keyboard-navigable surface in the app — chapter_list, library and
        # book_detail_panel all already treat Space/Return/Enter as one activation set; Settings
        # was the outlier. Space is deliberately NOT handled here: Qt's own handling is correct
        # and intercepting it would only risk diverging from it.
        # Only for things that can actually be clicked: the balance slider is a row member too,
        # and ClickSlider has no click() — Enter on it would raise. A slider has no "activate"
        # meaning anyway; its keyboard affordance is Left/Right, below.
        # The interval row's items are QLabels acting as buttons (a mousePressEvent
        # monkeypatch, not a real clicked() signal — see build_themes_tab), so the generic
        # hasattr(focus, "click") branch just below can never reach them. Handled here,
        # ahead of it, on the same two keys.
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            for minutes, lbl in self.theme_manager.interval_widgets.items():
                if focus is lbl:
                    self.theme_manager.set_rotation_interval(minutes)
                    return True

        # swatch_box is a real row member (see themes_tab_rows) but has no click() of its own
        # — Enter/Return on it must fall through to _handle_themes_swatch_arrows below, which
        # owns activation for whatever swatch is actually focused inside the grid, not be
        # rejected here as "not clickable".
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and focus is not self.theme_manager.swatch_box:
            if any(focus is w for row in rows for w in row) and hasattr(focus, "click"):
                focus.click()
                return True
            return False  # not clickable, or not one of our controls — leave it to Qt
        tab_bar = self.tabs.tabBar()

        # On the tab bar: Down enters the buttons at row 0, Up enters at the LAST row —
        # added 2026-09-10, symmetric with Down/Up's wrap at the other end of the grid (see
        # below: Down at the last row and Right past the last row's last item both now wrap
        # back UP to the tab bar). Left/Right must stay native so they keep switching tabs
        # (via _ThemesTabBarInterceptor).
        if focus is tab_bar:
            if key == Qt.Key.Key_Down:
                self._focus_settings_control(rows[0][0])
                return True
            if key == Qt.Key.Key_Up:
                self._focus_settings_control(rows[-1][0], from_below=True)
                return True
            return False

        # Locate the focused control in the grid.
        pos = next((( r, c) for r, row in enumerate(rows)
                    for c, w in enumerate(row) if w is focus), None)
        if pos is None:
            return False  # focus is on some other control — leave it to Qt
        row_i, col_i = pos

        # The Themes swatch grid owns ALL arrow/Enter/Space keys once focus is on swatch_box —
        # it is a one-item row here (like folder_list_widget) but has its own internal 2-D
        # position (row, col) rather than a QListWidget's single currentRow(), so it needs its
        # own dispatch rather than reusing the QListWidget branch below.
        if focus is self.theme_manager.swatch_box:
            return self._handle_themes_swatch_arrows(key, row_i, tab_bar)

        # A focused LIST BOX owns Up/Down for its own row selection (Library's Manage folders).
        # Only hand the key onward at the ends: Up on the first item leaves upward, Down on the
        # last item leaves downward. Everything in between is Qt's to handle, so return False and
        # let the widget move its own selection.
        #
        # Qt reports accepted=False for a boundary arrow (measured), but that cannot be relied on
        # here: this runs from the app-wide eventFilter, BEFORE the widget sees the key at all,
        # so the boundary has to be detected up front rather than inferred from propagation.
        if isinstance(focus, QListWidget):
            row = focus.currentRow()
            if row < 0:
                # Focus arrived without a selection — Qt leaves currentRow() at -1 when a list
                # is focused programmatically, so the box was "entered" with nothing highlighted
                # and the very first arrow was read as a boundary. Select the end the user is
                # arriving from and consume this keypress as the act of entering: Down from
                # above lands on the first path, Up from below lands on the last.
                #
                # This was invisible with several paths (Down happened to fall through to Qt,
                # which moved -1 to 0) but fatal with exactly ONE, where -1 satisfied both
                # boundary tests and every arrow bounced straight back out (reported live
                # 2026-09-05: "when there is one path remaining, I can never activate it").
                self._move_list_current_row(focus, 0 if key == Qt.Key.Key_Down else focus.count() - 1)
                self._keep_marker_awake()
                return True
            at_top = row == 0
            at_bottom = row == focus.count() - 1
            if ((key == Qt.Key.Key_Down and not at_bottom)
                    or (key == Qt.Key.Key_Up and not at_top)):
                # Move the CURSOR here and consume the key, rather than returning False and
                # letting Qt do it. The marker traces the current ROW, so it has to re-map after
                # the row changes — deferring to Qt would run _keep_marker_awake against the OLD
                # row and leave the marker a row behind. Focus stays on the box, so this also
                # supplies the keep-awake the slider needs for the same reason.
                self._move_list_current_row(focus, row + (1 if key == Qt.Key.Key_Down else -1))
                self._keep_marker_awake()
                return True
            # Genuinely at an end: leave the box. Selection is deliberately left exactly as the
            # user built it — a live design pass 2026-09-05 settled on Space/Enter as the ONLY
            # way selection ever changes (cursor movement, including entry and exit, never
            # touches it), specifically so the user can select rows, leave the box, and Tab to
            # Remove and have it act on what was actually chosen. This used to clearSelection()
            # unconditionally on exit, from back when leaving the box and "losing the selection"
            # was assumed harmless; it is no longer harmless — it would silently make Remove a
            # no-op every time it's reached via keyboard.

            # Left/Right have no meaning INSIDE a list box (no horizontal concept for a folder
            # path row) — Left leaves the box for the tab bar (same as Up on the first row/Left
            # on any other row-0 control), Right is swallowed as a plain no-op rather than left
            # to Qt's own native handling, which is not guaranteed to be a no-op either (reported
            # live 2026-09-05: both keys were doing something inside the box instead of nothing).
            if key == Qt.Key.Key_Left:
                tab_bar.setFocus(Qt.FocusReason.TabFocusReason)
                return True
            if key == Qt.Key.Key_Right:
                return True

        # Excluded Books is a self-managed overlay (own keyPressEvent, see excluded_books.py) —
        # not a normal grid row settings_tab_button_rows() ever reports, since it navigates
        # internally (Up/Down scroll rows, Left/Right expand/collapse) rather than being stepped
        # through like a button row. It sits directly below Library's LAST row (Persist search
        # filter), so it's entered from there specifically: Down from any button in that row, or
        # Right from that row's rightmost button (reported live 2026-09-05: "Down arrow to go
        # the next row from any button, right arrow to go down from the rightmost button" — the
        # same convention every other row-to-row Down already follows, plus the Right addition
        # this one specific row needs since it's the last row with nothing below it otherwise).
        # `is_expandable`'s underlying count also gates this — an empty popup (0 excluded books)
        # is entirely hidden (see reposition()) and must never become a keyboard stop, same as
        # folder_list_widget skipping itself when count()==0 (settings_tab_button_rows'
        # _navigable).
        is_library_last_row = (row_i == len(rows) - 1
                                and self.tabs.tabText(self.tabs.currentIndex()) == "Library")
        excluded_popup_available = self.excluded_books_popup.book_count > 0
        if is_library_last_row and excluded_popup_available and (
                key == Qt.Key.Key_Down
                or (key == Qt.Key.Key_Right and col_i == len(rows[row_i]) - 1)):
            self.excluded_books_popup.setFocus(Qt.FocusReason.TabFocusReason)
            return True

        if key == Qt.Key.Key_Down:
            if row_i + 1 < len(rows):
                self._focus_settings_control(rows[row_i + 1][0])
            else:
                # Last row: wrap to the tab bar — added 2026-09-10, symmetric with Up at
                # row 0 already going to the tab bar just below. Previously swallowed
                # (a dead end); the Library-popup special case above already claims Down
                # on Library's own last row, so this only ever fires on the OTHER tabs'
                # last row, or Library when the popup is empty/unavailable.
                tab_bar.setFocus(Qt.FocusReason.TabFocusReason)
            return True
        if key == Qt.Key.Key_Up:
            if row_i > 0:
                # from_below: arriving upward, so a list box should land on its LAST path.
                self._focus_settings_control(rows[row_i - 1][0], from_below=True)
            else:
                tab_bar.setFocus(Qt.FocusReason.TabFocusReason)
            return True

        # Left/Right between interval-row QLabels needs explicit handling — unlike QPushButton
        # (which Qt's own style gives native arrow-key focus chaining between siblings, see
        # the "native within-row stepping" comment below), a plain QLabel has NO such native
        # behaviour even with Qt.FocusPolicy.TabFocus set (confirmed live and synthetically
        # 2026-09-06: Right arrow silently did nothing, focus never left the first label).
        # Moves focus manually via _focus_settings_control-equivalent setFocus, WITHIN the row
        # only — at either end it falls through to the generic row-edge handling below (Right
        # continuing reading-order into the next row/tab-bar, Left into the previous row/tab-
        # bar), exactly like every other row now does. Previously swallowed Right at the row's
        # end as a dead end — that was correct only by coincidence, back when every OTHER row's
        # Right-at-the-end also went nowhere (Qt's unreliable native chain); now that reading-
        # order wrap is the real, deliberate model app-wide, this row must not be the one
        # exception left behind.
        if isinstance(focus, QLabel) and key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            row = rows[row_i]
            new_col = col_i + (1 if key == Qt.Key.Key_Right else -1)
            if 0 <= new_col < len(row):
                row[new_col].setFocus(Qt.FocusReason.TabFocusReason)
                self._keep_marker_awake()
                return True
            # At either end: fall through to the generic row-edge handling below.

        # Left/Right on a focused SLIDER adjust its value instead of moving focus — a slider's
        # own affordance is its position, so stepping off it sideways would leave the keyboard
        # unable to actually set the thing it just selected. Checked before the row-edge rules
        # below so a slider never falls through to them (it is always a one-item row, so
        # col_i == 0 would otherwise send Left back to the tab bar).
        if isinstance(focus, ClickSlider):
            step = -_BALANCE_ARROW_STEP if key == Qt.Key.Key_Left else _BALANCE_ARROW_STEP
            # step_by (not a plain += clamp) so a step that would cross the midpoint lands
            # on it exactly first — see ClickSlider.step_by's own docstring.
            focus.step_by(step)
            self._keep_marker_awake()
            return True

        # Reading-order wrap — added 2026-09-10, replacing reliance on Qt's native
        # sibling-focus-chain stepping (construction order, not `rows`' visual order —
        # confirmed live inconsistent: "Right arrow is mostly no-op, from Look and Controls
        # it goes to the tab" — the same class of bug _handle_flat_panel_arrows' own comment
        # already documents and fixed for Speed/Sleep/Sprint). Right past a row's last item
        # continues onto the NEXT row's first item; past the LAST row's last item, wraps to
        # the tab bar (mirroring Up-from-tab-bar landing on the last row, added just above).
        # Left mirrors this in the other direction; Left before row 0's first item already
        # went to the tab bar (unchanged, folded into this block for one shared code path).
        if key == Qt.Key.Key_Right:
            row = rows[row_i]
            if col_i + 1 < len(row):
                row[col_i + 1].setFocus(Qt.FocusReason.TabFocusReason)
            elif row_i + 1 < len(rows):
                self._focus_settings_control(rows[row_i + 1][0])
            else:
                tab_bar.setFocus(Qt.FocusReason.TabFocusReason)
            return True
        if key == Qt.Key.Key_Left:
            row = rows[row_i]
            if col_i > 0:
                row[col_i - 1].setFocus(Qt.FocusReason.TabFocusReason)
            elif row_i > 0:
                self._focus_settings_control(rows[row_i - 1][-1], from_below=True)
            else:
                tab_bar.setFocus(Qt.FocusReason.TabFocusReason)
            return True
        return False

    def _handle_stats_arrows(self, event) -> bool:
        """Arrow-key/Enter/Space navigation for the Stats panel. Returns True iff consumed.
        Called from the app-level eventFilter, same contract as _handle_settings_arrows.

        First pass (2026-09-08): only the "⚙" tab has arrow-navigable button rows
        (PanelManager.stats_tab_button_rows) — Overall/Day/Week/Month/Timeline have no
        down-target yet (Day/Week/Month's own row-list keyboard nav is a later, separate pass;
        Overall's carousel and Timeline's heatmap-hover popups are explicitly deferred per
        Pryme's own call — see TODO.md). Down/Tab from the tab bar on any OTHER tab is
        therefore a no-op this pass: there is nothing to enter, so the key is simply not
        claimed here and the marker/highlight stays on the tab.

        Left/Right tab-bar CYCLING needs no code here at all — QTabBar already handles
        Left/Right natively once it holds real Qt focus (confirmed via panels.py's
        _ThemesTabBarInterceptor docstring: "keyboard — Left/Right, handled natively by
        QTabBar.keyPressEvent"). This method only adds what Qt does NOT do natively: Down from
        the tab bar into the "⚙" tab's rows, and row-to-row Up/Down/Left/Right/Enter once
        inside — same shape as _handle_settings_arrows, but deliberately NOT reusing that
        method: Stats has none of Settings' special cases (no folder list, no theme swatch
        grid, no interval-row QLabels), so a fresh, narrower method avoids importing
        irrelevant complexity.

        The day-start-hour QSpinBox (this tab's last row, see stats_panel.py's
        _build_options_tab) is deliberately NOT treated like a generic row member for
        Up/Down/Right: those stay NATIVE (Qt's own QSpinBox increments/decrements the value on
        Up/Down and moves the text cursor on Right) — this method does not intercept them at
        all while focus is on the spinbox, simply returning False so Qt's own handling runs.
        Left is the one exception, repurposed (Pryme's explicit call) to leave the spinbox
        for the row above, exactly like every other row's Left-at-column-0 behavior — a
        QSpinBox's native Left already just moves the text cursor, which is a paper cut
        the user wouldn't reasonably want on a 2-digit field anyway.
        No visual "you are here" marker/highlight is applied to the spinbox itself this pass —
        Pryme's own read: moving keyboard focus into it already highlights its text natively,
        which already answers "where is the cursor" without a second affordance.

        Reading-order wrap (added 2026-09-10, mirroring the identical fix in
        _handle_settings_arrows): Up from the tab bar -> "⚙" tab's last row (Down already went
        to row 0); Down at the last row -> wraps to the tab bar (previously swallowed); Right
        past a row's last item -> next row's first item, past the LAST row's last item -> wraps
        to the tab bar; Left mirrors this backward. Replaces the same stale reliance on Qt's
        native sibling-focus-chain stepping this pass fixed in Settings."""
        key = event.key()
        if key not in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Left, Qt.Key.Key_Right,
                       Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space,
                       Qt.Key.Key_Delete):
            return False
        if self.panel_manager.active_full_panel() != "stats":
            return False
        stats_panel = getattr(self, 'stats_panel', None)
        if stats_panel is None:
            return False
        tab_bar = stats_panel.tabs.tabBar()
        focus = QApplication.focusWidget()

        # Delete on "Reset all stats" — added 2026-09-09, app-wide Delete-key-arms-a-
        # destructive-confirmation pass (Book Detail's per-tab equivalents landed the same
        # session; see that panel's _history_key_event for the sibling design). Live design
        # correction, same day: an earlier version scoped this to focus being ON the button
        # itself — "it beats the purpose. Delete should work without requiring me to go to
        # the button itself, but anywhere on the panel." Rescoped to "anywhere the ⚙ tab is
        # active", not literally the whole Stats panel — the button only exists on that one
        # tab, so Delete pressed on Overall/Day/Week/Month/Timeline has nothing to arm.
        # X was dropped as a synonym in the same correction ("hasn't been used anywhere else"
        # in this app, and "easier to press by mistake than Del") — Delete only, here and at
        # every other Delete-key site added this session.
        if key == Qt.Key.Key_Delete and tab_bar.tabText(tab_bar.currentIndex()) == "⚙":
            reset_btn = getattr(stats_panel, '_reset_stats_btn', None)
            if reset_btn is not None:
                reset_btn.click()
            return True

        # Timeline's tassel: Space/Enter toggles the Streak<->Heatmap view directly while the
        # tab bar holds focus and Timeline is current — see StatsPanel._on_tassel_clicked, the
        # exact method the tassel's own mousePressEvent already calls, so keyboard and mouse
        # activation share one code path. Must be checked BEFORE Qt's native tab-bar handling
        # ever sees the key: Qt's own QTabBar treats Space/Enter as "activate the focused tab",
        # a no-op since it's already the active tab, silently swallowing the key otherwise.
        # Pryme's explicit design intent: this works identically whether Timeline was reached
        # by keyboard (Left/Right) or mouse click — real Qt focus stays on the tab itself in
        # both cases (TasselOverlay is Qt.NoFocus, confirmed — a tassel click cannot steal
        # focus away from the tab bar), so checking `focus is tab_bar` covers both paths with
        # no separate mouse-vs-keyboard branch needed.
        if (focus is tab_bar and key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space)
                and tab_bar.tabText(tab_bar.currentIndex()) == "Timeline"):
            stats_panel._on_tassel_clicked()
            return True

        if focus is tab_bar:
            if key == Qt.Key.Key_Down:
                current_tab = tab_bar.tabText(tab_bar.currentIndex())
                if current_tab == "⚙":
                    rows = self.panel_manager.stats_tab_button_rows()
                    if rows:
                        self._focus_settings_control(rows[0][0])
                    return True
                # Day/Week/Month's row list (2026-09-09 pass) — a single Tab-stop, same shape
                # as every other "enter this widget, it owns its own internal navigation from
                # here" case in this app (folder_list_widget, swatch_box). _enter_from_tab_bar
                # seeds the keyboard cursor from the mouse's CURRENT hover position (or row 0
                # if the mouse isn't over any row) before real focus lands, so the highlight is
                # never missing on arrival — Pryme's own framing: "down arrow goes to the first
                # row, highlights using the current mouse hover".
                list_view = {
                    "Day": getattr(stats_panel, '_day_list_view', None),
                    "Week": getattr(stats_panel, '_week_list_view', None),
                    "Month": getattr(stats_panel, '_month_list_view', None),
                }.get(current_tab)
                if list_view is not None:
                    list_view._enter_from_tab_bar()
                    list_view.setFocus(Qt.FocusReason.TabFocusReason)
                    return True
                return True  # Overall/Timeline: no down-target this pass — swallow, no-op
            if key == Qt.Key.Key_Up:
                # Mirrors Down's own per-tab behavior — added 2026-09-10, alongside the
                # matching Down-at-last-row/Right-at-grid-end wrap just below, for the same
                # reading-order-wrap consistency pass done on Settings' tabs (see
                # _handle_settings_arrows). Only "⚙" has real navigable rows to land on;
                # every other tab has no up-target, same as Down has no down-target for
                # Overall/Timeline.
                current_tab = tab_bar.tabText(tab_bar.currentIndex())
                if current_tab == "⚙":
                    rows = self.panel_manager.stats_tab_button_rows()
                    if rows:
                        self._focus_settings_control(rows[-1][0], from_below=True)
                return True
            return False  # every other tab-bar key (incl. native Left/Right) is Qt's to handle

        rows = self.panel_manager.stats_tab_button_rows()
        if not rows:
            return False
        # Hover pickup (2026-09-15) — same mechanism as _handle_settings_arrows'/
        # _handle_flat_panel_arrows' own pickup call; see _pickup_hover_target's
        # docstring. Checked on every qualifying keypress; the method itself gates on
        # whether the mouse has genuinely moved since keyboard mode last asserted.
        focus = self._pickup_hover_target(focus, rows, "stats")
        pos = next(((r, c) for r, row in enumerate(rows)
                    for c, w in enumerate(row) if w is focus), None)
        if pos is None:
            return False  # focus is on some other control — leave it to Qt
        row_i, col_i = pos

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if hasattr(focus, "click"):
                focus.click()
                return True
            return False

        if isinstance(focus, QSpinBox):
            if key == Qt.Key.Key_Left:
                if row_i > 0:
                    self._focus_settings_control(rows[row_i - 1][0])
                else:
                    tab_bar.setFocus(Qt.FocusReason.TabFocusReason)
                return True
            if key == Qt.Key.Key_Right:
                # Same reasoning as Left (repurposed — native Right just moves the text cursor
                # on a 2-digit field, a paper cut, and never leaves the widget). Live-reported
                # gap 2026-09-08: Right (and Tab, see below) were no-ops here, but Reset all
                # stats sits one row below and should be reachable with either.
                if row_i + 1 < len(rows):
                    self._focus_settings_control(rows[row_i + 1][0])
                return True
            return False  # Up/Down/Space stay native (value edit)

        if key == Qt.Key.Key_Down:
            if row_i + 1 < len(rows):
                self._focus_settings_control(rows[row_i + 1][0])
            else:
                # Last row: wrap to the tab bar — added 2026-09-10, symmetric with Up at
                # row 0 already going to the tab bar just below, and matching the identical
                # fix in _handle_settings_arrows (see that method's docstring for the full
                # reading-order-wrap design this mirrors). Previously swallowed.
                tab_bar.setFocus(Qt.FocusReason.TabFocusReason)
            return True
        if key == Qt.Key.Key_Up:
            if row_i > 0:
                self._focus_settings_control(rows[row_i - 1][0])
            else:
                tab_bar.setFocus(Qt.FocusReason.TabFocusReason)
            return True
        # Reading-order wrap — added 2026-09-10, same fix and same reasoning as
        # _handle_settings_arrows' identical block (replacing reliance on Qt's native
        # sibling-focus-chain stepping, which is construction order, not `rows`' visual
        # order). Right past a row's last item continues onto the NEXT row's first item;
        # past the LAST row's last item, wraps to the tab bar. Left mirrors this backward;
        # Left before row 0's first item already went to the tab bar (unchanged, folded in).
        if key == Qt.Key.Key_Right:
            row = rows[row_i]
            if col_i + 1 < len(row):
                row[col_i + 1].setFocus(Qt.FocusReason.TabFocusReason)
            elif row_i + 1 < len(rows):
                self._focus_settings_control(rows[row_i + 1][0])
            else:
                tab_bar.setFocus(Qt.FocusReason.TabFocusReason)
            return True
        if key == Qt.Key.Key_Left:
            row = rows[row_i]
            if col_i > 0:
                row[col_i - 1].setFocus(Qt.FocusReason.TabFocusReason)
            elif row_i > 0:
                self._focus_settings_control(rows[row_i - 1][-1], from_below=True)
            else:
                tab_bar.setFocus(Qt.FocusReason.TabFocusReason)
            return True
        return False

    def _handle_themes_swatch_arrows(self, key, outer_row_i: int, tab_bar) -> bool:
        """Arrow/Enter/Space navigation INSIDE the Themes swatch grid, once `swatch_box`
        holds real Qt focus (see _handle_settings_arrows's dispatch to this method, and
        _focus_settings_control for how the grid is entered). `outer_row_i` is swatch_box's
        own position within themes_tab_rows() — needed only to know there is nothing below
        it to fall through to (it is always the tab's last or second-to-last outer row).

        Treated as a genuine 2-D grid (ThemeManager.swatch_grid_rows(), bin-packed — rows can
        have different lengths), unlike the flat button rows _handle_settings_arrows itself
        steps through:
          * Left/Right — READING-ORDER wrap: past a row's last column, Right continues onto
            the NEXT row's first column (and off the grid's last row, exits downward exactly
            like Down does); past a row's first column, Left continues onto the PREVIOUS
            row's last column (and off row 0, exits to the tab bar). This replaced an earlier
            clamp-at-row-end design reported live as wrong 2026-09-06 ("it doesn't go down to
            the next row from the rightmost theme").
          * Up/Down — move to the SAME column index on the row above/below, clamped to that
            row's own (possibly shorter) length. Deliberately NOT the same wrap Left/Right
            use: Up/Down are the "move vertically, keep roughly the same horizontal position"
            gesture and Left/Right are the "read through everything" gesture — conflating them
            would make one of the two directions redundant.

        Arrival at any new position re-previews via ThemeManager.kbdnav_enter_swatch — the
        same debounced pipeline a mouse hover uses (2026-09-06 design: keyboard arrival
        previews automatically, no separate keypress needed).

        Space and Enter are DELIBERATELY different actions, mirroring the mouse exactly —
        corrected live 2026-09-06 after an earlier version made them identical: Space toggles
        pool membership (the left-click action, kbdnav_toggle_swatch), Enter/Return selects
        the swatch AND activates it immediately (the right-click action,
        kbdnav_select_swatch). Do not merge these back into one branch."""
        rows = self.theme_manager.swatch_grid_rows()
        if not rows:
            return True  # nothing to navigate; swallow so the key doesn't leak anywhere
        pos = self.theme_manager._kbdnav_swatch_pos
        if pos is None or pos[0] >= len(rows) or pos[1] >= len(rows[pos[0]]):
            pos = (0, 0)  # defensive: grid content changed under us (e.g. pool edited elsewhere)
        row_i, col_i = pos

        def _land(new_row: int, new_col: int) -> None:
            new_col = max(0, min(new_col, len(rows[new_row]) - 1))
            self.theme_manager._kbdnav_swatch_pos = (new_row, new_col)
            self.theme_manager.kbdnav_enter_swatch(rows[new_row][new_col])

        if key == Qt.Key.Key_Space:
            self.theme_manager.kbdnav_toggle_swatch(rows[row_i][col_i])
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.theme_manager.kbdnav_select_swatch(rows[row_i][col_i])
            return True
        if key == Qt.Key.Key_Right:
            # Reading-order wrap (2026-09-06, corrected from an earlier clamp-at-row-end
            # design that was reported live as wrong: "it doesn't go down to the next row
            # from the rightmost theme"). Rightmost column of a row wraps to the FIRST
            # column of the NEXT row, same as text wrapping — not a clamp, and not the
            # same thing as Down (which preserves column index; this always lands at
            # column 0). Off the last row entirely, exits the grid downward exactly like
            # Down does at the bottom.
            if col_i + 1 < len(rows[row_i]):
                _land(row_i, col_i + 1)
            elif row_i + 1 < len(rows):
                _land(row_i + 1, 0)
            else:
                self.theme_manager.kbdnav_exit_swatch_grid()
                outer_rows = self.panel_manager.settings_tab_button_rows()
                if outer_row_i + 1 < len(outer_rows):
                    self._focus_settings_control(outer_rows[outer_row_i + 1][0])
            return True
        if key == Qt.Key.Key_Left:
            # Mirror of Right's wrap: leftmost column of a row wraps to the LAST column of
            # the PREVIOUS row. Off row 0 entirely (the cover-pool row, itself always a
            # one-item row so col_i is always 0 there), leaves to the tab bar — same
            # convention every other grid's top-left Left uses.
            if col_i > 0:
                _land(row_i, col_i - 1)
            elif row_i > 0:
                _land(row_i - 1, len(rows[row_i - 1]) - 1)
            else:
                self.theme_manager.kbdnav_exit_swatch_grid()
                tab_bar.setFocus(Qt.FocusReason.TabFocusReason)
            return True
        if key == Qt.Key.Key_Down:
            if row_i + 1 < len(rows):
                _land(row_i + 1, col_i)
                return True
            # Last row of the grid: leave downward to whatever follows (bulk row), exactly
            # like Down already does at the bottom of any other button row.
            self.theme_manager.kbdnav_exit_swatch_grid()
            outer_rows = self.panel_manager.settings_tab_button_rows()
            if outer_row_i + 1 < len(outer_rows):
                self._focus_settings_control(outer_rows[outer_row_i + 1][0])
            return True
        if key == Qt.Key.Key_Up:
            if row_i > 0:
                _land(row_i - 1, col_i)
                return True
            # Row 0 (cover-pool row): leave upward to the mode row above, or the tab bar if
            # the grid is somehow the very first row (not reachable today, but matches every
            # other row-0 Up's "tab bar" fallback rather than assuming a row above exists).
            self.theme_manager.kbdnav_exit_swatch_grid()
            if outer_row_i > 0:
                outer_rows = self.panel_manager.settings_tab_button_rows()
                self._focus_settings_control(outer_rows[outer_row_i - 1][0], from_below=True)
            else:
                tab_bar.setFocus(Qt.FocusReason.TabFocusReason)
            return True
        return False

    # The full set of values a typed digit sequence can resolve to — matches the interval
    # row's own on-screen values/order exactly (build_themes_tab's `intervals` list). 0 means
    # Off, same convention the row's own "Off" label already uses via minutes=0.
    _THEMES_INTERVAL_VALUES = frozenset((0, 2, 5, 10, 20, 30, 60, 120))

    def _handle_themes_shortcuts(self, event) -> bool:
        """Letter/digit shortcuts scoped to the Themes tab (2026-09-06 design), alongside the
        arrow/Enter/Space navigation in _handle_settings_arrows/_handle_themes_swatch_arrows.
        Returns True iff consumed. Called right after _handle_settings_arrows from the same
        eventFilter KeyPress branch.

        Unlike the swatch grid's own keys, these work regardless of which control inside the
        tab currently has focus — they are TAB-scoped shortcuts, not row/grid-local ones,
        mirroring how Library's t/a/r/d/y/p/f and 1-5 (LibraryPanel._SORT_KEY_SHORTCUTS/
        _VIEW_MODE_SHORTCUTS) work regardless of which book is selected. Never claims a key
        while a text field has focus (there are none on this tab today, but the guard costs
        nothing and matches every sibling method's convention), and every branch carries its
        own isAutoRepeat() guard so holding a key doesn't fire the action repeatedly — these
        are one-shot actions (add all / remove all / rotate now / set an interval), not
        something a repeat should ever drive.

        Digits are buffered rather than mapped one key -> one interval: several intervals
        are two/three digits (20, 30, 60, 120), so a single keypress can't disambiguate "2"
        (heading toward 20) from a genuine "2" (the 2-minute interval) — the exact ambiguity
        the 2026-09-06 design calls out ("the window should be set well enough not to cause
        20 to be interpreted as 2 and 0"). `_themes_digit_buffer`/`_themes_digit_timer`
        mirror ChapterList's own digit-jump debounce (chapter_list.py) exactly: each digit
        keypress appends to the buffer and restarts an 800ms single-shot timer; the timer
        firing (_commit_themes_digit_buffer) is what actually calls set_rotation_interval,
        using whatever was typed if and only if it names a real interval — an unmatched
        buffer (typing "9", or "121") is silently dropped rather than doing something
        surprising with a number that isn't one of the eight real choices."""
        key = event.key()
        if not self._settings_is_active():
            return False
        if self.tabs.tabText(self.tabs.currentIndex()) != "Themes":
            return False
        if isinstance(QApplication.focusWidget(), QLineEdit):
            return False
        mods = event.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)

        if key == Qt.Key.Key_A and not event.isAutoRepeat():
            # A (bare) and Ctrl+A both mean Add all — Ctrl+A is included because that chord
            # is muscle memory from "select all" elsewhere and there is no text field on this
            # tab for it to collide with.
            self.theme_manager.select_all_themes()
            return True
        if key == Qt.Key.Key_R and not ctrl and not event.isAutoRepeat():
            self.theme_manager.deselect_all_themes()
            return True
        if key == Qt.Key.Key_D and ctrl and not event.isAutoRepeat():
            # Ctrl+D for Remove all (the D is "remove" read as its own chord, not a bare
            # letter — R alone already means Remove all, so Ctrl+D is the second binding for
            # it, not a second action).
            self.theme_manager.deselect_all_themes()
            return True
        if key in (Qt.Key.Key_T, Qt.Key.Key_C) and not ctrl and not event.isAutoRepeat():
            self.theme_manager._do_rotate(user_initiated=True)
            return True
        if Qt.Key.Key_0 <= key <= Qt.Key.Key_9 and not ctrl and not event.isAutoRepeat():
            self._themes_digit_buffer += event.text()
            self._themes_digit_timer.start()
            return True
        return False

    def _commit_themes_digit_buffer(self) -> None:
        """_themes_digit_timer fired 800ms after the last digit — see _handle_themes_shortcuts
        for why this is a buffer-and-debounce rather than a one-key-per-interval map."""
        typed = self._themes_digit_buffer
        self._themes_digit_buffer = ""
        try:
            minutes = int(typed)
        except ValueError:
            return
        if minutes in self._THEMES_INTERVAL_VALUES:
            self.theme_manager.set_rotation_interval(minutes)

    # ── Speed / Sleep / Sprint arrow navigation (added 2026-09-07) ────────────────────────
    # These three panels have no tabs — one flat row-of-rows per panel (PanelManager.
    # flat_panel_rows), with each panel's own QGridLayout preset grid represented as a single
    # opaque stop that owns its own internal 2-D navigation (_handle_panel_grid_arrows),
    # mirroring exactly how Themes' swatch_box works inside Settings (_handle_settings_arrows/
    # _handle_themes_swatch_arrows). Kept as a SEPARATE method rather than folded into
    # _handle_settings_arrows: that method is keyed throughout on Settings-specific concepts
    # (tabs, settings_tab_button_rows, the folder-list/Excluded-Books special cases) that don't
    # apply here, and touching it risked the exact kind of regression the modality machinery
    # has already caused twice (2026-09-03/04) — a parallel method costs some duplication but
    # leaves Settings' own navigation completely unchanged.
    #
    # Per-panel-key grid cursor state, since Speed/Sleep/Sprint each have their own grid and
    # only one is ever open at a time but all three can independently remember a position
    # across a close-then-reopen within the same app session (not persisted, just in-memory —
    # same "no memory across a full exit" scope as Themes' swatch grid, see
    # ThemeManager._kbdnav_swatch_pos's docstring, just multiplied by three panels).
    _FLAT_PANEL_KEYS = ("speed", "sleep", "sprint")

    def _handle_flat_panel_arrows(self, event) -> bool:
        """Arrow-key navigation for Speed/Sleep/Sprint. Returns True iff consumed. Called from
        the app-level eventFilter, same contract as _handle_settings_arrows.

        Down enters/advances a row, landing on its first control; Up leaves to the previous
        row. Left/Right are handled EXPLICITLY here (reading-order wrap across rows) rather
        than deferring to Qt's native sibling stepping the way _handle_settings_arrows does —
        see the Left/Right branches below for why that native-deferral shape is actually a bug
        waiting to happen, not a harmless shortcut, on this specific set of panels. The one
        shape Settings doesn't have at all: a QGridLayout preset grid, represented as ONE row
        here (see PanelManager.flat_panel_rows) that hands off to _handle_panel_grid_arrows for
        its own internal movement once focus reaches it.

        A focused TEXT FIELD (the custom-duration input) is deliberately NOT deferred to for
        Left/Right the way Settings' text fields are — live design correction 2026-09-07:
        "this is not a field where we'll write an article... let the arrows treat it as any
        other button. No need to dwell there." Up/Down already work correctly with no special
        case (they act on ROW position, never the field's own text cursor); Left/Right are
        explicitly swallowed instead of left to native text-cursor movement.

        Space/Enter both activate a plain click (Qt gives Space for a QPushButton for free —
        this method deliberately never touches plain Space, same as _handle_settings_arrows;
        Enter needs adding, same reasoning there too). Shift+Enter/Shift+Space (or, as of
        2026-09-10, Alt+Enter/Alt+Space — the two modifiers are accepted as full synonyms, a
        zero-cost superset now applied everywhere either existed alone: Library already used
        Alt+Enter for its own "open detail" action, Tags already accepted both) are the
        keyboard equivalent of a RIGHT click, on whichever focused control actually has a
        `rightClicked` signal (Sleep's Fade-out row today; consumed as a no-op on anything
        else, so a Shift/Alt-held press never falls through and fires a plain click instead) —
        2026-09-07 live design call, mirroring how Themes split plain Enter (right-click
        equivalent) from Space (left-click equivalent) for its swatch grid, generalized here to
        a MODIFIER on the shared activation keys instead of two different bare keys, since
        these panels' buttons already use plain Enter/Space for their own single click action
        and only a few controls have a second (right-click) action at all.

        Digit redirect into the panel's own custom-duration/grace QLineEdit is handled
        separately, in the eventFilter's KeyPress branch (see _redirect_digit_to_panel_input)
        — it must run BEFORE this method's own key-gate, since a digit is not one of the keys
        this method itself claims, and it must apply regardless of what currently has focus on
        the panel (not just when focus already sits in one of `rows`)."""
        key = event.key()
        if key not in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Left, Qt.Key.Key_Right,
                       Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space,
                       Qt.Key.Key_Delete):
            return False
        panel_key = self.panel_manager.active_full_panel()
        if panel_key not in self._FLAT_PANEL_KEYS:
            return False
        focus = QApplication.focusWidget()

        # Delete on Sprint's "Reset all sprint data" — added 2026-09-09, the same app-wide
        # Delete-key-arms-a-destructive-confirmation pass as Stats' _handle_stats_arrows
        # equivalent and Book Detail's per-tab ones (see those for the sibling design). Live
        # design correction, same day: an earlier version required focus to be ON the button
        # itself — "it beats the purpose. Delete should work without requiring me to go to
        # the button itself, but anywhere on the panel." Sprint has no tabs, so "anywhere on
        # the panel" here just means "regardless of which row currently has focus" — fires as
        # long as Sprint is the active panel and the button is genuinely showing.
        # isVisible() is the SAME gate sync_disable_button_visibility() itself uses
        # (`not self._sprint_active`) — Pryme's explicit call: Delete should only arm the
        # confirmation when the button is genuinely the reset action, never while a sprint is
        # active (Speed/Sleep have no equivalent control today, hence no matching branch here
        # for them). X was dropped as a synonym in the same correction ("hasn't been used
        # anywhere else" in this app, and "easier to press by mistake than Del") — Delete
        # only, here and at every other Delete-key site added this session.
        # Deliberately skipped while focus is a QLineEdit (the custom sprint/grace duration
        # field): Delete there is the field's own native delete-character-forward, which must
        # keep working — unlike Left/Right, which this method's docstring already explains
        # are intentionally NOT deferred to the text field, Delete has no panel-navigation
        # meaning worth stealing it for.
        if (key == Qt.Key.Key_Delete and panel_key == "sprint"
                and not isinstance(focus, QLineEdit)):
            sprint_panel = getattr(self, 'sprint_panel', None)
            reset_btn = getattr(sprint_panel, '_reset_sprint_btn', None) if sprint_panel else None
            if reset_btn is not None and reset_btn.isVisible():
                reset_btn.click()
            return True

        rows = self.panel_manager.flat_panel_rows(panel_key)
        if not rows:
            return False
        # Hover pickup (2026-09-15): same shape as _handle_settings_arrows' own pickup call
        # — checked on EVERY qualifying keypress, not gated on "focus not found" (see
        # _pickup_hover_target's CORRECTION note). Done once here, before grid_layout_for
        # below, so BOTH downstream paths (a preset-grid cell and an ordinary flat row)
        # benefit from a single pickup site rather than needing the fix twice.
        focus = self._pickup_hover_target(focus, rows, panel_key)
        # Alt added 2026-09-10 as a synonym for Shift here — Library already used Alt+Enter
        # for its own "open detail" action and Tags already accepted both (see
        # _handle_thumb_grid_keys in tag_manager.py); this closes the gap so Speed/Sleep/Sprint
        # accept either modifier too, a zero-cost superset since nothing else uses Alt here.
        shift = bool(event.modifiers() & (Qt.KeyboardModifier.ShiftModifier
                                           | Qt.KeyboardModifier.AltModifier))

        grid = self.panel_manager.grid_layout_for(panel_key, focus)
        if grid is not None:
            return self._handle_panel_grid_arrows(key, shift, grid, panel_key, rows)

        pos = next(((r, c) for r, row in enumerate(rows)
                    for c, w in enumerate(row) if w is focus), None)
        if pos is None:
            return False  # focus is on some other control — leave it to Qt
        row_i, col_i = pos

        # A focused TEXT FIELD (the custom-duration input) is treated as an ORDINARY one-item
        # row here, deliberately NOT deferred to like Settings' text fields are elsewhere —
        # live design correction 2026-09-07: "this is not a field where we'll write an
        # article... let the arrows treat it as any other button. No need to dwell there."
        # Left/Right must NOT be left to native handling (which would move the text cursor
        # instead of navigating) — but swallowing them outright was ALSO rejected live
        # ("swallowing the right and left arrows is worse. Just let them continue the
        # navigation"): since the field is always the only item in its row, Left/Right
        # continue the SAME direction Up/Down would — Right/Left both just mean "keep moving
        # through the panel" here, there being no horizontal sibling to distinguish them from
        # vertical movement. Remapped to Down/Up respectively and handled by the exact same
        # branches below, rather than duplicating their logic.
        if isinstance(focus, QLineEdit) and key == Qt.Key.Key_Right:
            key = Qt.Key.Key_Down
        elif isinstance(focus, QLineEdit) and key == Qt.Key.Key_Left:
            key = Qt.Key.Key_Up

        # Shift+Enter and Shift+Space both mean "right-click equivalent" — checked before the
        # plain-Enter/plain-Space handling below so a Shift-held press never also fires a plain
        # click. Space is caught here specifically because Qt's own native Space-clicks-a-
        # button behavior has no way to know about Shift; without this branch Shift+Space
        # would silently fall through to Qt and fire an ordinary click, not a right-click.
        if shift and key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            if hasattr(focus, "rightClicked"):
                focus.rightClicked.emit()
            return True  # consumed either way — a Shift-held press on a control with no
            # rightClicked signal should not fall through and fire a plain click instead
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if hasattr(focus, "click"):
                focus.click()
                return True
            return False  # not clickable (e.g. the text field itself) — leave it to Qt,
            # matching _handle_settings_arrows' own "not clickable" fallback
        # Plain Space is deliberately NOT handled here at all — Qt already fires clicked() on
        # Space for a focused QPushButton natively (same as _handle_settings_arrows, which
        # never touches Space for exactly this reason); explicitly calling click() for it here
        # too would double-fire it.

        if key == Qt.Key.Key_Down:
            if row_i + 1 < len(rows):
                self._focus_flat_panel_control(rows[row_i + 1][0], panel_key)
                return True
            return True  # last row: swallow, so Down can't fall out of the panel
        if key == Qt.Key.Key_Up:
            if row_i > 0:
                self._focus_flat_panel_control(rows[row_i - 1][0], panel_key, from_below=True)
                return True
            return True  # first row: swallow — no tab bar to leave to on these panels
        # Left/Right are handled explicitly, in full, rather than deferring to Qt's native
        # sibling-focus stepping the way _handle_settings_arrows does for Settings' rows. This
        # was a REAL BUG, not a stylistic choice: "native within-row stepping" is not actually
        # scoped to the row at all — it's Qt's global native Tab-order chain, which QPushButton
        # happens to also honor for arrow keys (the same mechanism that made Themes' interval
        # QLabels correctly NOT move, since QLabel has no such native behavior). At the last
        # widget of a row, that chain simply continues into whatever the NEXT widget in the
        # panel's construction order is — not the next row's first widget `rows` would say, and
        # not a stop at all — so Right at the end of ANY row silently escaped into a later row
        # picked by Qt, not by this navigation model (confirmed live 2026-09-07: Right on the
        # Smart Rewind duration row's "60" jumped to "Default speed", an EARLIER row than
        # Smart Rewind — Qt's native chain and `rows`' visual order had simply diverged).
        # Settings' own rows happen to never hit this because Look/Controls/Audio's rows are
        # always followed by MORE rows below them in construction order too, so the escape
        # landed somewhere plausible-looking often enough not to be caught — it was never
        # actually safe there either, just lucky. Reading-order wrap, matching the grid's own
        # model and the live-requested "let them continue the navigation" for Left/Right in
        # general: past a row's last item, Right continues onto the NEXT row's first; past a
        # row's first item, Left continues onto the PREVIOUS row's last. Off the panel
        # entirely in either direction, swallow (no tab bar to leave to on these panels).
        if key == Qt.Key.Key_Right:
            if col_i + 1 < len(rows[row_i]):
                self._focus_flat_panel_control(rows[row_i][col_i + 1], panel_key)
            elif row_i + 1 < len(rows):
                self._focus_flat_panel_control(rows[row_i + 1][0], panel_key)
            return True
        if key == Qt.Key.Key_Left:
            if col_i > 0:
                self._focus_flat_panel_control(rows[row_i][col_i - 1], panel_key)
            elif row_i > 0:
                self._focus_flat_panel_control(rows[row_i - 1][-1], panel_key, from_below=True)
            return True
        return False

    def _handle_panel_grid_arrows(self, key, shift: bool, grid, panel_key: str, rows: list) -> bool:
        """Internal Left/Right/Up/Down/Enter/Space navigation once focus is inside one of
        Speed/Sleep/Sprint's preset grids (see _handle_flat_panel_arrows). Reads the grid's
        REAL structure straight from Qt (rowCount/columnCount/itemAtPosition/getItemPosition)
        rather than flat_panel_rows' flattened list, so a spanning cell (Sleep's/Sprint's "End
        of chapter", which spans 2 columns) is correctly treated as ONE stop from either
        column it occupies, not two — `itemAtPosition` already resolves this identically to
        how the mouse experiences it (clicking either half activates the same button)."""
        focus = QApplication.focusWidget()
        idx = grid.indexOf(focus)
        if idx < 0:
            return False
        row_i, col_i, row_span, col_span = grid.getItemPosition(idx)

        def _widget_at(r: int, c: int):
            item = grid.itemAtPosition(r, c)
            return item.widget() if item is not None else None

        def _land(r: int, c: int) -> bool:
            w = _widget_at(r, c)
            if w is None or not w.isVisibleTo(grid.parentWidget()) or not w.isEnabled():
                return False
            w.setFocus(Qt.FocusReason.TabFocusReason)
            self._keep_marker_awake()
            return True

        # Same Shift+Enter/Shift+Space-is-right-click, plain-Space-is-Qt's-own-native-handling
        # shape as _handle_flat_panel_arrows — see that method's comments for why each branch
        # is ordered/scoped the way it is; kept in sync deliberately, not by accident.
        if shift and key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            if hasattr(focus, "rightClicked"):
                focus.rightClicked.emit()
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if hasattr(focus, "click"):
                focus.click()
                return True
            return False
        if key == Qt.Key.Key_Right:
            for c in range(col_i + col_span, grid.columnCount()):
                if _land(row_i, c):
                    return True
            # Reading-order wrap (2026-09-07, corrected from an initial clamp-at-row-end
            # design — reported live as wrong, the same correction Themes' swatch grid
            # needed for the same reason: "when you are at the rightmost button, right arrow
            # is no-op instead of going to the first button of the next row"): continue onto
            # the NEXT row's first cell rather than stopping. Off the grid's last row
            # entirely, exits downward exactly like Down does at the bottom.
            for r in range(row_i + row_span, grid.rowCount()):
                if _land(r, 0):
                    return True
            outer_row_i = next((i for i, row in enumerate(rows)
                                 if grid.itemAt(0).widget() in row), None)
            if outer_row_i is not None and outer_row_i + 1 < len(rows):
                self._focus_flat_panel_control(rows[outer_row_i + 1][0], panel_key)
            return True
        if key == Qt.Key.Key_Left:
            for c in range(col_i - 1, -1, -1):
                if _land(row_i, c):
                    return True
            # Mirror of Right's wrap: continue onto the PREVIOUS row's last cell. Off row 0
            # entirely, exits upward exactly like Up does at the top.
            for r in range(row_i - 1, -1, -1):
                if _land(r, grid.columnCount() - 1):
                    return True
            outer_row_i = next((i for i, row in enumerate(rows)
                                 if grid.itemAt(0).widget() in row), None)
            if outer_row_i is not None and outer_row_i > 0:
                self._focus_flat_panel_control(rows[outer_row_i - 1][0], panel_key, from_below=True)
            return True
        if key == Qt.Key.Key_Down:
            for r in range(row_i + row_span, grid.rowCount()):
                if _land(r, min(col_i, grid.columnCount() - 1)):
                    return True
            # Bottom of the grid: leave downward to whatever row follows it, exactly like
            # _handle_flat_panel_arrows' own Down does at any other row's bottom.
            outer_row_i = next((i for i, row in enumerate(rows)
                                 if grid.itemAt(0).widget() in row), None)
            if outer_row_i is not None and outer_row_i + 1 < len(rows):
                self._focus_flat_panel_control(rows[outer_row_i + 1][0], panel_key)
            return True
        if key == Qt.Key.Key_Up:
            for r in range(row_i - 1, -1, -1):
                if _land(r, min(col_i, grid.columnCount() - 1)):
                    return True
            # Top of the grid: leave upward, same convention.
            outer_row_i = next((i for i, row in enumerate(rows)
                                 if grid.itemAt(0).widget() in row), None)
            if outer_row_i is not None and outer_row_i > 0:
                self._focus_flat_panel_control(rows[outer_row_i - 1][0], panel_key, from_below=True)
            return True
        return False

    def _focus_flat_panel_control(self, widget, panel_key: str, from_below: bool = False) -> None:
        """Give `widget` keyboard focus as a Speed/Sleep/Sprint navigation step. Mirrors
        _focus_settings_control's shape but there is no list-box case here — every row's first
        control (including a grid's first navigable cell) is a plain widget setFocus can just
        target directly. `from_below` is accepted for call-site symmetry with
        _focus_settings_control even though nothing here currently needs to pick a DIFFERENT
        landing widget for it (a grid always lands on its own first/last real cell regardless
        of direction, handled by flat_panel_rows already filtering to navigable widgets only)."""
        widget.setFocus(Qt.FocusReason.TabFocusReason)
        self._keep_marker_awake()

    def _redirect_digit_to_panel_input(self, event) -> bool:
        """A typed digit while Sleep or Sprint is open and focus is somewhere else on the
        panel redirects into that panel's own custom-DURATION QLineEdit and starts typing
        there, rather than building a second buffered-digit mechanism like Themes' interval
        row — live design call 2026-09-06: these panels already have a real text field for
        "type an exact number," so reusing it is simpler than a second mechanism.

        Sprint has a SECOND candidate field (custom_grace_input, only present/relevant when
        grace mode is "custom") that a bare digit does NOT redirect to — explicit live design
        call 2026-09-07: a digit always means "set the duration," regardless of grace mode;
        reaching the grace field is arrow/Tab navigation's job, same as any other control that
        isn't the one-and-only obvious target for a typed number. Speed has no text field at
        all and is correctly never reached by this method.

        Stats added 2026-09-08 (live design call, same "reuse what's already there" reasoning):
        day_start_spin is a QSpinBox, not a QLineEdit, but QAbstractSpinBox exposes the same
        selectAll()/sendEvent-of-the-triggering-key shape via its own internal line edit, so it
        redirects identically — a typed digit while Stats' "⚙" tab is open and focus is
        elsewhere selects the spinbox's current value and starts a fresh number, same as
        Sleep/Sprint's duration field. Scoped to the "⚙" tab specifically (not "any Stats tab")
        since the spinbox doesn't exist/isn't reachable from the other five tabs.

        Never fires while focus is ALREADY in the target (its own keys must win, not get
        reinterpreted as "start a new redirect"), and only for genuinely bare digit keys — a
        modified digit (Ctrl/Alt+digit) is left alone in case it means something else in the
        future."""
        if event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier):
            return False
        if not (Qt.Key.Key_0 <= event.key() <= Qt.Key.Key_9):
            return False
        panel_key = self.panel_manager.active_full_panel()
        target = {
            "sleep": getattr(self.sleep_panel, "custom_sleep_input", None),
            "sprint": getattr(self.sprint_panel, "custom_sprint_input", None),
        }.get(panel_key)
        if (target is None and panel_key == "stats"
                and self.stats_panel.tabs.tabText(self.stats_panel.tabs.currentIndex()) == "⚙"):
            target = getattr(self.stats_panel, "day_start_spin", None)
        if target is None:
            return False
        focus = QApplication.focusWidget()
        if focus is target:
            return False
        target.setFocus(Qt.FocusReason.OtherFocusReason)
        target.selectAll()
        QApplication.sendEvent(target, event)
        return True

    def _focus_settings_control(self, widget, from_below: bool = False) -> None:
        """Give `widget` keyboard focus as a settings-navigation step, positioning the cursor
        first if it is a list box.

        A QListWidget focused programmatically has currentRow() == -1 — focused with no cursor
        position at all, so the marker traced the BOX and the user needed an extra arrow before
        anything showed as current (reported live 2026-09-05: entering "selects the box, not the
        first item", and Tab "skips the items"). Every path that moves focus during settings
        navigation goes through here so they all behave the same; `from_below` picks the end
        being arrived from, so Up from the buttons lands on the LAST path rather than the first.

        Deliberately does NOT select the landing row — only moves the cursor (see
        _move_list_current_row). Entering the list is itself a cursor move, and cursor moves
        never touch selection, on entry or afterward; auto-selecting the entry row was tried and
        rejected live (2026-09-05): reaching row 3 without acting on row 1 meant either living
        with a stray auto-selected row 1 or explicitly deselecting it first, which is exactly the
        "cumbersome" cost this design avoids. Nothing is selected until the user explicitly
        presses Space/Enter on a row — see the toggle branch in _handle_settings_arrows.

        `swatch_box` (the Themes-tab swatch grid, entered as one opaque row like a list box
        — see panels.themes_tab_rows) gets the equivalent treatment: real Qt focus lands on
        the box itself, never on an individual ThemeItem (they're all Qt.FocusPolicy.NoFocus
        — see build_themes_tab), and `from_below` picks which row the keyboard cursor starts
        on, same idea as a list box's last-vs-first path."""
        if isinstance(widget, QListWidget) and widget.count():
            self._move_list_current_row(widget, widget.count() - 1 if from_below else 0)
        elif widget is self.theme_manager.swatch_box:
            rows = self.theme_manager.swatch_grid_rows()
            row_i = len(rows) - 1 if from_below else 0
            self.theme_manager._kbdnav_swatch_pos = (row_i, 0) if rows else None
            if rows and rows[row_i]:
                self.theme_manager.kbdnav_enter_swatch(rows[row_i][0])
        widget.setFocus(Qt.FocusReason.TabFocusReason)

    def _move_list_current_row(self, list_widget: QListWidget, row: int) -> None:
        """Move `list_widget`'s current-row CURSOR to `row` without touching its selection.

        `QListWidget.setCurrentRow(row)` looks like plain cursor movement but is not: it calls
        `setCurrentIndex` with Qt's default `ClearAndSelect` command, which replaces the ENTIRE
        selection with just `row` — confirmed live and reproduced synthetically 2026-09-05
        (select rows 2 and 4, then `setCurrentRow(3)`: selection becomes {2, 3}, row 4 silently
        dropped). That is a real bug for `folder_list_widget` specifically now that Space/Enter
        toggle selection on the current row (see the toggle branch above): arrowing after
        building a multi-selection was destroying it as a side effect of merely moving.

        `QItemSelectionModel.setCurrentIndex(idx, NoUpdate)` moves the same current-row cursor
        (currentRow() reads it identically either way) while leaving `selectedItems()` completely
        untouched — the actual primitive this method needs. Used for EVERY cursor move on this
        list, including the entry point (`_focus_settings_control`): a live design pass
        2026-09-05 settled on cursor movement never touching selection under any circumstance,
        entry included — see that method's docstring for why an entry-row auto-select was tried
        and rejected."""
        idx = list_widget.model().index(row, 0)
        list_widget.selectionModel().setCurrentIndex(idx, QItemSelectionModel.SelectionFlag.NoUpdate)

    def _keep_marker_awake(self) -> None:
        """Restart the traveling marker's idle dwell without moving it — for keys that act on
        the focused control instead of moving to another one, where the usual "focus arrived
        somewhere new" reset never happens and the marker would otherwise fade under an actively
        working user. Used by the balance slider's Left/Right and by selecting a row inside a
        list box. Safe no-op before the marker exists.

        Also a no-op under "fill_highlight" style — that style never shows the marker at all
        (see _update_focus_marker), but this method's call sites are style-agnostic (written
        before the style toggle existed) and _target can be stale from BEFORE a live style
        switch (marker.keep_awake() itself only guards on _target being None, which it isn't
        right after switching away from "traveling" mid-session) — without this check, one of
        these call sites re-entering patrol on that stale target would resurrect the marker
        under fill_highlight. See _update_keyboard_marker_style for the complementary fix
        (clearing the marker immediately on switching TO fill_highlight)."""
        if self.config.get_keyboard_marker_style() == "fill_highlight":
            return
        marker = getattr(self, 'focus_marker', None)
        if marker is not None:
            marker.keep_awake()

    def _kbdnav_active_panel_key(self) -> str | None:
        """Which of the five keyboard-navigable panels (settings/speed/sleep/sprint/stats) is
        currently open, or None if none is. Single source of truth for "which panel does the
        modality flag/marker/kbdnav property apply to right now" — added 2026-09-07 when
        keyboard navigation extended from Settings alone to Speed/Sleep/Sprint, extended again
        2026-09-08 to Stats. Every method that used to hardcode `self.settings_panel`/`"settings"`
        (the panel-property target in _set_keyboard_nav_active, the surface check in
        _on_kbdnav_cursor_poll) now asks this instead, so adding a panel to the modality system
        means teaching THIS method about it, not re-finding every hardcoded site.

        "stats" resolves to `self.stats_panel` via _kbdnav_panel_widget's f"{panel_key}_panel"
        convention — MainWindow already has a `stats_panel` attribute (main_window_builders.py),
        so no change was needed there."""
        if not hasattr(self, 'panel_manager'):
            return None
        panel = self.panel_manager.active_full_panel()
        return panel if panel in ("settings", "speed", "sleep", "sprint", "stats") else None

    def _kbdnav_panel_widget(self, panel_key: str):
        """The QWidget the `kbdnav` QSS property is set on for `panel_key` — settings_panel/
        speed_panel/sleep_panel/sprint_panel/stats_panel. Single mapping used by
        _set_keyboard_nav_active; see _kbdnav_active_panel_key's docstring for why this
        indirection exists."""
        return getattr(self, f"{panel_key}_panel", None)

    def _kbdnav_tab_bar_for(self, panel_key: str):
        """The QTabBar for `panel_key`'s own QTabWidget, or None if that panel has no tabs
        (Speed/Sleep/Sprint) or isn't a recognised kbdnav panel at all. Single mapping added
        2026-09-09 so a tab-bar-specific check (currently only _update_focus_marker's
        fill_highlight kbdnav_tab_focused branch) needs one new entry here to support a future
        tabbed panel, rather than a second hardcoded `focus is <specific>.tabs.tabBar()` check
        at every call site — exactly the gap that let Stats' tab bar silently never work after
        Settings' was hardcoded here first."""
        if panel_key == "settings":
            return self.tabs.tabBar() if hasattr(self, 'tabs') else None
        if panel_key == "stats":
            return self.stats_panel.tabs.tabBar() if hasattr(self, 'stats_panel') else None
        return None

    def _set_keyboard_nav_active(self, active: bool) -> None:
        """Single owner of `_keyboard_nav_active` AND its visual consequences.

        Two things must move together, which is why nothing writes the flag directly:
          1. the traveling focus marker's show-gate (_update_focus_marker), and
          2. the `kbdnav` dynamic property on whichever panel is currently open
             (_kbdnav_active_panel_key), which the QSS reads to suppress :hover highlights
             while the keyboard is driving.

        (2) exists because the keyboard marker and the mouse's :hover were both lighting up at
        once — the marker on one control, :hover on whatever the cursor happened to rest over —
        so nothing on screen said which one Enter would act on (reported live 2026-09-03 with
        three screenshots: hover on the Audio TAB while the marker sat on a button, and hover on
        the "1500" BUTTON while the marker sat on "Slow"). Most-recent-input-wins: whichever
        device was used last owns the highlight. Originally Settings-only; generalized
        2026-09-07 to whichever of the four panels is open, via _kbdnav_active_panel_key —
        the mechanism itself (one property, one polish pass) is unchanged, only WHICH panel it
        targets is no longer hardcoded.

        The property is set on the active panel (not per-button) so one polish() covers every
        descendant, and each panel's own QSS gates its :hover rules on it — see
        get_settings_stylesheet/get_speed_stylesheet/get_sleep_stylesheet/get_sprint_stylesheet.
        Qt does not re-evaluate a stylesheet when a dynamic property changes, so unpolish/polish
        is required; skipped entirely when the value hasn't changed, since polishing the panel
        walks all its children."""
        if active == getattr(self, '_keyboard_nav_active', False):
            return
        self._keyboard_nav_active = active
        panel_key = self._kbdnav_active_panel_key()
        panel = self._kbdnav_panel_widget(panel_key) if panel_key is not None else None
        if panel is not None:
            panel.setProperty("kbdnav", "true" if active else "false")
            # `kbdnav_style` (2026-09-08, added alongside the fill_highlight marker style):
            # ALWAYS set here, on every transition, to whichever style is currently configured —
            # unlike kbdnav_fill_active/kbdnav_marker_active (each written only by ITS OWN
            # style's code path, so a panel that has never been under the other style never gets
            # a value for the other's property at all), this one is unconditional so QSS can
            # reliably select "is fill_highlight NOT active" via [kbdnav_style="traveling"] even
            # on a panel that has never once been in fill_highlight mode. Exists specifically to
            # fix a live regression: the pre-existing kbdnav-hover-suppression rules
            # (#pattern_button:hover -> transparent, etc.) were written for the traveling style
            # only ("the marker is the ONLY thing claiming 'you are here'") but had no style
            # gate at all, so they also suppressed hover under fill_highlight — where the FILL
            # itself needs :focus:hover to win instead, and got silently overridden right back to
            # transparent by these unconditional rules. See get_settings_stylesheet/
            # get_sleep_stylesheet/get_sprint_stylesheet for the added [kbdnav_style="traveling"]
            # guard on each suppression rule.
            panel.setProperty("kbdnav_style", self.config.get_keyboard_marker_style())
            panel.style().unpolish(panel)
            panel.style().polish(panel)
            # Polishing the panel re-resolves the PANEL's own style, but its descendants keep
            # painting from their cached style until they are polished themselves — so both the
            # tab bar and the Look buttons need explicit repolishing or their hover highlight
            # stays lit through a correct flag flip and a correct property write (both confirmed
            # live 2026-09-04: the tab bar first, then the buttons, each via a [KBDNAV] trace
            # showing clean True/False alternation while the highlight visibly persisted).
            # update() alone is not enough — the unpolish/polish pair is what re-resolves
            # [kbdnav] for them. Only for panels that HAVE a tab bar (Speed/Sleep/Sprint don't;
            # generalized 2026-09-09 via _kbdnav_tab_bar_for — was hardcoded to
            # `panel_key == "settings"` only, so Stats' own tab bar never got repolished here
            # even after Stats gained its own tab-bar-scoped kbdnav QSS rules, reproducing the
            # exact stale-cached-style bug this block exists to prevent). Repolishing a tab bar
            # while a DIFFERENT panel is the active one is still avoided — _kbdnav_tab_bar_for
            # only returns non-None for panel_key itself, never some other panel's tab bar.
            bar = self._kbdnav_tab_bar_for(panel_key)
            if bar is not None:
                bar.style().unpolish(bar)
                bar.style().polish(bar)
                bar.update()
                if not active:
                    self._resync_tab_bar_hover(bar)
            # EVERY button under the panel, not just the current tab's and not filtered by
            # object name. Two reasons, both learned the hard way:
            #   * settings_tab_button_rows() only reports the CURRENT tab, so flipping the flag
            #     while on another tab left the others' buttons holding a stale style and their
            #     hover stayed broken on return (reported live 2026-09-04).
            #   * an objectName == "pattern_button" filter silently excluded #reset_audio_btn,
            #     whose focus fill is ALSO [kbdnav]-gated — any button that grows a
            #     kbdnav-dependent rule must be repolished, so the safe default is all of them.
            # findChildren reaches them regardless of which tab is showing, and a button with no
            # kbdnav-dependent rule simply polishes to the same value.
            for btn in panel.findChildren(QPushButton):
                btn.style().unpolish(btn)
                btn.style().polish(btn)
                btn.update()
        if active:
            # Remember where the cursor was resting when the keyboard took over, so merely
            # ENTERING keyboard mode while the cursor already sits on a control doesn't
            # immediately hand it straight back — see _on_kbdnav_cursor_poll.
            self._kbdnav_cursor_anchor = QCursor.pos()
            self._kbdnav_cursor_poll.start()
        else:
            self._kbdnav_cursor_anchor = None
            self._kbdnav_cursor_poll.stop()

    def refresh_kbdnav_style_property(self) -> None:
        """Re-stamp `kbdnav_style` on the currently active kbdnav panel (if any) to match
        config.get_keyboard_marker_style() right now, without waiting for the next
        _set_keyboard_nav_active transition.

        Needed because _set_keyboard_nav_active only writes this property as a side effect of
        _keyboard_nav_active actually flipping — so switching the style TOGGLE ITSELF while
        keyboard nav is already active on the panel the toggle lives in (the Controls tab, the
        exact case that surfaced this live) would leave the property stale until some unrelated
        later transition happened to refresh it. Called from
        SettingsController._update_keyboard_marker_style right after the config write."""
        panel_key = self._kbdnav_active_panel_key()
        panel = self._kbdnav_panel_widget(panel_key) if panel_key is not None else None
        if panel is None:
            return
        value = self.config.get_keyboard_marker_style()
        if panel.property("kbdnav_style") == value:
            return
        panel.setProperty("kbdnav_style", value)
        panel.style().unpolish(panel)
        panel.style().polish(panel)
        for btn in panel.findChildren(QPushButton):
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            btn.update()

    def _on_focus_marker_dormant_changed(self, dormant: bool) -> None:
        """Called by TravelingFocusMarker itself (it holds `main_window` and calls back
        directly, no signal plumbing needed) whenever it transitions to/from being visibly
        hidden WHILE keyboard mode is still logically active — its own idle self-fade
        finishing (dormant=True), a fresh Tab/arrow-press resuming patrol on a target
        (dormant=False), or clear() firing for a reason other than [kbdnav] itself flipping
        false (dormant=True; e.g. focus moving out of the marker's tracked scope while
        keyboard mode stays on).

        Exists because `kbdnav="true"` on the panel (see _set_keyboard_nav_active) answers
        "is keyboard mode active", not "is the marker actually visible right now" — those
        are different questions once the marker's own idle-fade is in the picture. The
        ramp buttons' (Speed/Sleep/Sprint) keyboard-highlight QSS rule used to be gated on
        [kbdnav="true"] alone, which stays true through the whole idle-fade, so the
        highlight stayed lit long after the marker itself had faded to nothing — reported
        live 2026-09-08: "the marker disappears after inactivity, but the highlight
        lingers." A second property, `kbdnav_marker_active`, tracks the narrower question;
        the ramp buttons' QSS rule is now gated on BOTH properties.

        Same shape as _set_keyboard_nav_active's own repolish (set property, unpolish,
        polish every button under the panel) — deliberately not reusing that method itself,
        since this property is orthogonal to `kbdnav` and must be settable independently of
        it (dormant can flip true/false many times while `kbdnav` stays true throughout).

        Only meaningful under the "traveling" marker style — this method is the marker's own
        callback (called only from focus_marker.py's _enter_patrol/_on_fade_finished/clear), so
        it is simply never invoked at all under "fill_highlight" style, where show_for/clear are
        never called on the marker in the first place (see _update_focus_marker).

        CORRECTION (2026-09-08, live report: "traveling marker still everywhere" after switching
        TO fill_highlight — actually the traveling style that broke, not fill_highlight; my own
        first fix mis-targeted the wrong style entirely). This property, `kbdnav_marker_active`,
        is SPECIFIC to the traveling style's own ramp-button rule (see the two paragraphs above)
        and must never be read by anything that should apply only under fill_highlight — the
        fill-highlight QSS rule (get_panel_base_stylesheet) is gated on a SEPARATE property,
        `kbdnav_fill_active`, written only by _update_focus_marker's fill_highlight branch via
        _set_kbdnav_fill_active_property. Reusing this property for both styles was the bug:
        `kbdnav_marker_active` goes true here whenever the marker is genuinely patrolling under
        "traveling", which made the (wrongly shared) fill-highlight rule paint a fill ON TOP OF
        the real traveling marker every time it was actually visible."""
        panel_key = self._kbdnav_active_panel_key()
        panel = self._kbdnav_panel_widget(panel_key) if panel_key is not None else None
        if panel is None:
            return
        self._set_kbdnav_property(panel, "kbdnav_marker_active", not dormant)

    def _set_kbdnav_fill_active_property(self, panel, active: bool) -> None:
        """Fill-highlight-style-exclusive sibling of _on_focus_marker_dormant_changed's
        `kbdnav_marker_active` write — see that method's CORRECTION note for why these must be
        two distinct properties, not one shared between styles. Sole writer:
        _update_focus_marker's fill_highlight branch."""
        self._set_kbdnav_property(panel, "kbdnav_fill_active", active)

    def clear_all_kbdnav_fill_active(self) -> None:
        """Force `kbdnav_fill_active` false on ALL FOUR kbdnav panels (settings/speed/sleep/
        sprint/stats), not just whichever one is currently open.

        Live regression, 2026-09-08: switching the style toggle from fill_highlight BACK to
        traveling left the fill rendering ON TOP OF the traveling marker in Settings (Speed/
        Sleep/Sprint reported correct — consistent with fill_highlight simply never having been
        tested there yet, not evidence the cause is Settings-specific). Root cause:
        `_set_kbdnav_fill_active_property` is called ONLY from _update_focus_marker's
        fill_highlight branch — under "traveling" style nothing ever touches this property at
        all, so a panel that was left `kbdnav_fill_active="true"` from an EARLIER fill_highlight
        session stays stuck at "true" forever once the style switches back, since Qt properties
        persist on the widget instance across style changes. `_update_keyboard_marker_style`
        already had the mirror-image fix for the opposite direction (clearing the traveling
        marker on switching TO fill_highlight) but nothing symmetric for switching TO traveling.
        Iterates every panel key (not just `_kbdnav_active_panel_key()`) because the stale
        property could be sitting on a DIFFERENT panel than whichever one happens to be open
        when the switch is made. "stats" added when Stats joined the modality system (same day,
        later pass) — `kbdnav_fill_active` is the generic per-panel property every kbdnav panel
        shares, so it needs the same clear regardless of whether that panel has a tab bar.

        Also clears `kbdnav_tab_focused` for every panel that HAS a tab bar (checked via
        _kbdnav_tab_bar_for, not hardcoded to "settings" — Stats gained its own fill-highlight
        tab-bar rule the same day this comment was last wrong about that) for the identical
        reason: it is likewise written only by the fill_highlight branch and would otherwise
        survive a switch back to "traveling" stuck at "true", making the selected tab show a
        stray fill alongside the real traveling marker."""
        for panel_key in ("settings", "speed", "sleep", "sprint", "stats"):
            panel = self._kbdnav_panel_widget(panel_key)
            if panel is not None:
                self._set_kbdnav_fill_active_property(panel, False)
                if self._kbdnav_tab_bar_for(panel_key) is not None:
                    self._set_kbdnav_property(panel, "kbdnav_tab_focused", False)

    def _set_kbdnav_property(self, panel, prop_name: str, active: bool) -> None:
        """Set `prop_name` on `panel` and repolish it + every child QPushButton, skipping the
        work if the value is already correct. Shared plumbing for the three DISTINCT, never-
        simultaneously-true-for-the-same-purpose properties `kbdnav_marker_active` (traveling
        style), `kbdnav_fill_active` (fill_highlight style), and `kbdnav_tab_focused`
        (fill_highlight, tab-bar-specific) — see _on_focus_marker_dormant_changed's CORRECTION
        note for why the first two must not be the same property.

        CORRECTION (2026-09-09 live report, intermittent — worked for some themes, then didn't
        on the SAME theme moments later): the repolish loop below only ever walked
        `QPushButton` children, never the settings tab bar itself. `QTabBar`'s `::tab`
        sub-controls cache their own style state and do NOT re-resolve just because an ancestor
        was unpolish/polish'd — this exact fact is already the reason `_set_keyboard_nav_active`
        has its own separate `tabs.tabBar()` unpolish/polish block (see that method's own
        comment, 2026-09-04) — but this NEWER, more general helper never got the same
        treatment when it was added, so `kbdnav_tab_focused` changes could set the property
        correctly while the tab bar kept painting from a stale cached style, appearing to work
        only when some UNRELATED event (a theme switch, which does its own full stylesheet
        reapply) happened to repolish the tab bar for an entirely different reason first.

        SECOND CORRECTION (2026-09-09, same day): the fix above was hardcoded to
        `panel is self.settings_panel`, so Stats' tab bar reproduced the identical bug the
        moment Stats gained its own fill-highlight tab-bar rule — generalized via
        _kbdnav_tab_bar_for(panel_key) instead of a second hardcoded panel-identity check."""
        value = "true" if active else "false"
        if panel.property(prop_name) == value:
            return
        panel.setProperty(prop_name, value)
        panel.style().unpolish(panel)
        panel.style().polish(panel)
        panel_key = next((k for k in ("settings", "speed", "sleep", "sprint", "stats")
                           if self._kbdnav_panel_widget(k) is panel), None)
        bar = self._kbdnav_tab_bar_for(panel_key) if panel_key is not None else None
        if bar is not None:
            bar.style().unpolish(bar)
            bar.style().polish(bar)
            bar.update()
        for btn in panel.findChildren(QPushButton):
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            btn.update()

    def _on_focus_marker_fade_begin(self, target) -> None:
        """Called by TravelingFocusMarker._begin_fading, directly, the instant the marker
        itself starts fading (not when it finishes — _on_focus_marker_dormant_changed
        covers that). Live design ask, 2026-09-08: "can we make it fade out back to the
        ramp-up button's original color along with the marker's fade?" — the ramp button
        the marker is currently sitting on should dim in sync with the marker, not snap
        off abruptly once the marker is already gone.

        Only Speed/Sleep/Sprint's preset-ramp buttons have this animated fade (see
        ramp_highlight_fade.py) — every other keyboard target (Settings buttons, the tab
        bar, folder_list_widget, etc.) is unaffected; this is a no-op for them since none
        of those panels define begin_ramp_highlight_fade."""
        panel_key = self._kbdnav_active_panel_key()
        panel = self._kbdnav_panel_widget(panel_key) if panel_key is not None else None
        if panel is None or target is None:
            return
        begin = getattr(panel, 'begin_ramp_highlight_fade', None)
        if begin is not None:
            begin(target)

    def _on_focus_marker_fade_cancel(self) -> None:
        """Called by TravelingFocusMarker._enter_patrol, unconditionally, whenever the
        marker (re)starts patrol — a fresh arrow-press/Tab, whether landing on a NEW
        button or the SAME one whose highlight was still mid-fade. Live design ask:
        "a fresh arrow-press/mouse-hover during the fade instantly snaps the highlight
        back to full brightness." Mirrors _on_focus_marker_fade_begin's panel lookup;
        also a no-op for any panel without an animated ramp fade."""
        panel_key = self._kbdnav_active_panel_key()
        panel = self._kbdnav_panel_widget(panel_key) if panel_key is not None else None
        if panel is None:
            return
        cancel = getattr(panel, 'cancel_ramp_highlight_fade', None)
        if cancel is not None:
            cancel()

    def _on_kbdnav_cursor_poll(self) -> None:
        """Hand the UI back to the mouse when the cursor is genuinely ON a control it could
        act on — a Look-tab button or a settings tab — not merely because it moved.

        "Any movement ends keyboard mode" was tried first and rejected live (2026-09-03): a few
        pixels of drift across dead space killed the marker mid-navigation, which reads as the
        keyboard affordance being fragile. The mouse should only take over when it actually has
        something to claim, which is also what makes the handoff legible — hover lights up on
        the very control the cursor is over, in the same instant the marker goes away.

        The cursor must also have MOVED from where it rested when keyboard mode began. Without
        that, arrow-keying while the cursor happens to sit on a button would hand control back
        on the very next poll tick, making keyboard nav impossible from that position.

        See _set_keyboard_nav_active for why this is a poll rather than a MouseMove listener."""
        anchor = self._kbdnav_cursor_anchor
        if anchor is None:
            self._kbdnav_cursor_poll.stop()
            return
        # Left the surface entirely (panel closed) while keyboard mode was on: drop it here
        # rather than leaving it set for whenever the user returns. Deliberately the PANEL-level
        # check, not a per-tab one — arrowing through the TAB BAR changes the current tab by
        # definition, and clearing on that turned the tab bar's own keyboard navigation back
        # into mouse mode mid-flight (reported live 2026-09-04). Generalized 2026-09-07 from
        # Settings-only (_settings_is_active) to _kbdnav_active_panel_key, which recognises all
        # four keyboard-navigable panels — the check is otherwise unchanged.
        panel_key = self._kbdnav_active_panel_key()
        if panel_key is None:
            self._set_keyboard_nav_active(False)
            return
        pos = QCursor.pos()
        if (abs(pos.x() - anchor.x()) < _KBDNAV_CURSOR_JITTER_PX
                and abs(pos.y() - anchor.y()) < _KBDNAV_CURSOR_JITTER_PX):
            return  # hasn't left its resting spot yet
        if not self._cursor_over_navigable_control(pos, panel_key):
            return  # moved, but over dead space — keyboard keeps the highlight
        self._set_keyboard_nav_active(False)
        self._update_focus_marker()

    def _resync_tab_bar_hover(self, bar) -> None:
        """Force `bar`'s native `:hover` to repaint against the cursor's REAL current
        position, called from _set_keyboard_nav_active right after it un-suppresses hover
        (kbdnav flips false) on a tab bar. Fixes a real bug two prior QSS-only attempts
        couldn't (2026-09-10, see NOTES.md "Stats tab-bar hover-suppression port"): Qt's
        internal `QTabBar` hover tracking is driven entirely by genuine
        HoverEnter/HoverMove/HoverLeave events reaching the bar (confirmed directly,
        2026-09-15 — `QTabBar` carries `WA_Hover` by default). While the mouse rests
        somewhere else during keyboard suppression, no such event is ever delivered for it,
        so simply un-suppressing the QSS property leaves Qt's own `State_MouseOver`
        pointing at wherever it was BEFORE suppression started — stale, not re-evaluated —
        and native `:hover` keeps painting that stale answer (or nothing) until an actual
        click forces Qt to recompute it. Dispatching one real `QHoverEvent(HoverMove)` at
        the bar, targeting the cursor's actual live position, tells Qt's own hover tracking
        exactly what a genuine mouse move there would have: confirmed directly (2026-09-15)
        this correctly clears whichever tab was stale-hovered and lights the real one, via
        Qt's own native paint path — no property, no custom paintEvent, so the visual stays
        pixel-for-pixel whatever the current desktop's native `:hover` rule already renders
        everywhere else in the app. This is the ENTIRE fix for the mouse-reclaim direction;
        the keyboard-suppresses-mouse direction needs nothing here — the existing
        `[kbdnav="true"]... QTabBar::tab:hover:!selected` QSS rule already overrides the
        background regardless of Qt's internal State_MouseOver, so a stale `True` underneath
        it while suppressed is harmless.

        Safe to call whenever the cursor is off the bar entirely too: a HoverMove at a local
        position outside the bar's own rect still correctly reports "hovering nothing" to
        Qt's tracking, which is exactly what should happen if the un-suppress didn't come
        from the mouse resting on this bar in the first place (e.g. Escape closing the
        panel). Uses the (scenePos, globalPos, oldPos) constructor rather than the shorter
        (pos, oldPos) one — functionally identical (confirmed directly, 2026-09-15) but the
        shorter form is flagged deprecated by Qt itself; oldPos is left at (-1, -1) since the
        actual prior hover position doesn't matter here — Qt only needs `pos` to resolve
        which tab (if any) the state now belongs to."""
        global_pos = QCursor.pos()
        local = QPointF(bar.mapFromGlobal(global_pos))
        old = QPointF(-1, -1)
        QApplication.sendEvent(bar, QHoverEvent(QEvent.Type.HoverMove, local, global_pos, old))

    def _settings_is_active(self) -> bool:
        """Whether the Settings panel is the open panel — the surface the keyboard/mouse
        modality applies to.

        This, NOT "one particular tab is current", is the right scope for the modality flag,
        because the TAB BAR is keyboard-navigable and mouse-hoverable on every settings tab;
        only the button rows are per-tab. Scoping the modality to the Look tab alone regressed
        exactly that case (reported live 2026-09-04): arrowing through the tabs necessarily
        leaves Look, so the setter switched off mid-navigation and the poll's off-surface branch
        actively cleared the flag, leaving a hovered tab highlighted while the keys were driving.

        The invariant that matters is narrower than "one surface": the modality setter and the
        hand-back check (_cursor_over_navigable_control) must recognise the SAME set of
        controls, so the flag can never be set somewhere nothing can clear it. Both span the
        whole Settings panel — tab bar always, plus whatever settings_tab_button_rows() reports
        for the current tab."""
        return (hasattr(self, 'panel_manager') and hasattr(self, 'tabs')
                and self.panel_manager.active_full_panel() == "settings")

    def _cursor_over_navigable_control(self, global_pos, panel_key: str = "settings") -> bool:
        """Whether `global_pos` is over a control that competes with the traveling marker for
        "you are here" — i.e. something with its own :hover state the keyboard also navigates to:
        the settings tab bar, or one of the active tab's/panel's arrow-navigable buttons.

        `panel_key` generalizes this 2026-09-07 from Settings-only to Speed/Sleep/Sprint too —
        defaults to "settings" so the (many) existing call sites that only ever meant Settings
        stay unchanged. For "settings", behavior is byte-for-byte what it always was (tab bar +
        settings_tab_button_rows()); for the other four, it checks panel_manager.
        flat_panel_rows(panel_key) — Speed/Sleep/Sprint have no tab bar at all, but Stats does
        (checked via _kbdnav_tab_bar_for below, added 2026-09-15): without this, the mouse
        moving onto Stats' tab bar was never recognised as "over a navigable control" at all,
        so this poll could never hand keyboard mode back to the mouse there by any path — a
        real, separate gap from the native-:hover-stale-paint bug _resync_tab_bar_hover fixes
        (that one is about the paint never catching up once the flag DOES clear; this one is
        about the flag never clearing on Stats' tab bar in the first place).

        Uses the same live row source as the arrow navigation so the two can't disagree about
        what a button is — notably, a hidden control is not in the rows and so is correctly not
        a handoff target. That shared source is also what keeps the modality flag clearable: the
        setter and this check must recognise the same controls, or the flag can be set somewhere
        nothing can clear it (see _settings_is_active's docstring for the two live regressions
        that proved it for Settings; the same property is required of flat_panel_rows now)."""
        if not hasattr(self, 'tabs') or not hasattr(self, 'panel_manager'):
            return False
        if panel_key != "settings":
            tab_bar = self._kbdnav_tab_bar_for(panel_key)
            if tab_bar is not None and tab_bar.isVisible():
                local = tab_bar.mapFromGlobal(global_pos)
                if tab_bar.rect().contains(local) and tab_bar.tabAt(local) >= 0:
                    return True
            # Stats' "⚙" tab has its own button rows (day-start-hour spinbox, the reset
            # button, etc.) — a SEPARATE row source from flat_panel_rows, which only
            # knows about Speed/Sleep/Sprint's flat (tab-less) layouts and returns []
            # for "stats" (confirmed directly, 2026-09-15 — the actual bug behind a live
            # report: "Stats > Options... mouse hover doesn't even cancel the keyboard
            # marker"). Without checking stats_tab_button_rows() here too, hovering a
            # button INSIDE that tab was never recognised as "over a navigable control"
            # at all, so this poll could never hand keyboard mode back to the mouse for
            # any control other than the tab bar itself.
            if panel_key == "stats":
                for row in self.panel_manager.stats_tab_button_rows():
                    for w in row:
                        if w.rect().contains(w.mapFromGlobal(global_pos)):
                            return True
                return False
            for row in self.panel_manager.flat_panel_rows(panel_key):
                for w in row:
                    if w.rect().contains(w.mapFromGlobal(global_pos)):
                        return True
            return False
        tab_bar = self.tabs.tabBar()
        if tab_bar.isVisible():
            local = tab_bar.mapFromGlobal(global_pos)
            if tab_bar.rect().contains(local) and tab_bar.tabAt(local) >= 0:
                return True
        for row in self.panel_manager.settings_tab_button_rows():
            for btn in row:
                if btn.rect().contains(btn.mapFromGlobal(global_pos)):
                    return True
        return False

    def _focus_marker_in_scope(self, focus) -> bool:
        """Whether the traveling focus marker should be tracking `focus` right now: one of the
        four keyboard-navigable panels must be open, and `focus` must be one of ITS Tab-
        navigable controls (the exact same membership set Tab cycling uses — no second source
        of truth) — for Settings specifically, the tab bar also always counts.

        Scoped to the whole PANEL, not to one tab: Settings' tab bar is a marker target on
        every tab, and the marker follows Tab-cycling wherever that goes. Which tabs
        additionally get ARROW navigation is a separate, narrower question — see
        panels._ARROW_NAV_TABS. Generalized 2026-09-07 from Settings-only to also cover
        Speed/Sleep/Sprint (whose `panel_tab_widgets` keys are their own panel names, already
        supported by that method before this generalization — see PanelManager.
        panel_tab_widgets).

        `swatch_box` is a real Tab stop on Settings (see panel_tab_widgets — it isn't a
        ThemeItem, so that method's exclusion doesn't reach it) but is explicitly excluded
        HERE: a 2026-09-06 live design call settled on the grid's own synthetic-hover look
        (ThemeManager._set_kbdnav_swatch_hover) as the sole "where am I" affordance while
        inside it, same as folder_list_widget's dot delegate replaces the marker for that
        widget — except swatch_box gets no marker-family affordance at all, not even the
        fill-focus treatment folder_list_widget/excluded_popup get (_FILL_FOCUS_OBJECT_NAMES),
        since a real per-swatch hover state already exists and a second overlay on top of it
        would be redundant.

        Stats' Day/Week/Month row lists (StatsRowListView) get the identical exclusion,
        2026-09-09, for the identical reason — live design call: "no traveling marker here...
        only the same mouse highlight style." Once the row list gained real StrongFocus (for
        Up/Down row-cursor movement — see StatsRowListView.keyPressEvent), it became a real Tab
        stop that panel_tab_widgets("stats")'s generic findChildren walk picks up automatically,
        which made the marker try to trace it — same shape as swatch_box's own gap before its
        exclusion was added. The row's own hover-style highlight (delegate._hovered_row, shared
        between mouse and keyboard — see StatsRowListView's own docstring) is the sole "where am
        I" affordance here, same principle as swatch_box/folder_list_widget above."""
        if focus is None:
            return False
        panel_key = self._kbdnav_active_panel_key()
        if panel_key is None:
            return False
        if panel_key == "settings":
            if focus is self.tabs.tabBar():
                return True
            if focus is self.theme_manager.swatch_box:
                return False
        if panel_key == "stats":
            stats_panel = getattr(self, 'stats_panel', None)
            if stats_panel is not None and focus in (
                    getattr(stats_panel, '_day_list_view', None),
                    getattr(stats_panel, '_week_list_view', None),
                    getattr(stats_panel, '_month_list_view', None)):
                return False
        return focus in self.panel_manager.panel_tab_widgets(panel_key)

    def _update_focus_marker(self, reason: Qt.FocusReason | None = None) -> None:
        """Point the traveling focus marker at the currently-focused control iff it's in scope
        (see _focus_marker_in_scope) AND the last input was keyboard navigation, else clear it.
        Cheap: runs only on FocusIn/FocusOut. On a Tab move within scope this fires with the NEW
        focus already set, so the marker resumes patrol on the new widget at its carried-over
        relative position (show_for keeps self._t).

        `reason` is the originating QFocusEvent's own reason(), threaded through from the
        app-wide eventFilter's FocusIn/FocusOut branch — the one call site that actually has a
        real focus event to read it from. Together with the mouse-press clear described below it
        drives `_keyboard_nav_active` (the modality flag): the marker is a KEYBOARD-navigation
        affordance, so mouse input must hide it, not re-anchor it. The tabs.currentChanged call
        site passes nothing (None) on purpose: a tab switch is a REPOSITION trigger, not a
        modality change, so it must leave the flag exactly as the last real input set it.

        Focus reasons alone are NOT sufficient to tell mouse from keyboard on this UI — that was
        established by measurement, not assumption, after two versions of this gate shipped and
        failed live. The ownership split below is what actually works; read it before touching
        either branch.

        MODALITY OWNERSHIP — read this before changing either half:

        * CLEARING the flag is owned by the eventFilter's general MouseButtonPress branch, not by
          this method. A physical press is the ONLY unambiguous "the user is on the mouse"
          signal available; see that branch's comment for the measured reasons why no
          QFocusEvent.reason() value can stand in for it.
        * SETTING it True is owned PRIMARILY by the eventFilter's KeyPress branch, which asserts
          keyboard mode from the navigation key itself (_KBDNAV_ASSERT_KEYS). Symmetric with the
          press-based clear, and for the same reason: the press states intent, the focus event
          that may follow it does not. Two live-reported cases (2026-09-04) move the selection
          without producing any qualifying focus event at all — Left/Right on the tab bar (focus
          never leaves it) and Left/Right between sibling buttons (native moves carry no
          TabFocusReason) — so a reason-only design left a hovered control highlighted while the
          keyboard was plainly driving.
        * The TabFocusReason branch below is the SECONDARY setter, and is now largely redundant
          (the key press that caused the focus move already asserted the mode). It is kept for
          focus arriving by Tab from paths the KeyPress branch does not see, and it is still
          gated on _MOUSE_PRESS_FOCUS_WINDOW_S: Qt reports a mouse click ON A TAB as
          TabFocusReason (focus is moving to a tab; nothing to do with the Tab key), so without
          that window a tab click re-sets the flag milliseconds after the press cleared it, and
          the marker shows for a mouse click. That is exactly how the first version of this fix
          failed live (2026-09-03): press cleared at 23:03:55,452, TabFocusReason re-set at
          23:03:55,455. The press must win, so the window rejects the set rather than the clear.
        * The MouseFocusReason `elif` below is BELT-AND-SUSPENDERS only. A real press clears the
          flag before the resulting focus change is even delivered, so in practice this branch
          almost never fires first. It is kept for any focus change Qt attributes to the mouse
          without a press this filter saw. Do not treat it as the primary mechanism, and do not
          delete the press-based clear on the theory that it makes this branch redundant — the
          dependency runs the other way.
        * OtherFocusReason must stay a NO-OP here. It is genuinely ambiguous: it covers both a
          mouse click on a tab AND the legitimate keyboard two-step hop (Tab lands on the tab
          bar, then Qt forwards focus to a pattern_button ~2ms later with OtherFocusReason).
          Clearing on it would kill the marker mid-Tab-navigation."""
        if reason is Qt.FocusReason.TabFocusReason:
            # Reject a TabFocusReason that is really the focus change a just-delivered mouse
            # press produced — see MODALITY OWNERSHIP above. Only a genuine Tab/Backtab, well
            # clear of any press, may turn the marker back on.
            _press_t = self._last_mouse_press_t
            if (_press_t is None
                    or (time.perf_counter() - _press_t) > _MOUSE_PRESS_FOCUS_WINDOW_S):
                self._set_keyboard_nav_active(True)
        elif reason is Qt.FocusReason.MouseFocusReason:
            # Secondary/defensive — see MODALITY OWNERSHIP above; the MouseButtonPress branch
            # in eventFilter is what actually clears this in the common cases.
            self._set_keyboard_nav_active(False)
        # reason is None or OtherFocusReason → preserve flag unchanged (deliberately ambiguous)
        # ClickSlider (balance_slider/eq_slider_* — the Audio tab's bidirectional sliders)
        # paints itself manually (bg_color/fill_color via a custom paintEvent, not a QSS
        # `background`), so it can never match the [kbdnav_fill_active="true"]
        # QPushButton:focus rule every other control uses under fill_highlight. A first
        # version fell through to the traveling border marker for sliders under
        # fill_highlight instead; live feedback (2026-09-19) preferred a barely-brighter
        # slider background over the marker, matching every other control's own flat-fill
        # treatment under this style. ClickSlider.kbd_fill_active/set_kbd_fill_active is
        # that widget-local equivalent — synced here on every call (both styles, so
        # switching FROM fill_highlight while a slider is focused correctly clears it)
        # rather than only inside the fill_highlight branch, since a slider's own paint
        # state isn't reachable via the panel-wide QSS property this method otherwise
        # drives for every other control.
        focus_now = QApplication.focusWidget()
        wants_slider_fill = (
            self.config.get_keyboard_marker_style() == "fill_highlight"
            and self._keyboard_nav_active
            and isinstance(focus_now, ClickSlider)
            and self._focus_marker_in_scope(focus_now)
        )
        new_fill_slider = focus_now if wants_slider_fill else None
        if new_fill_slider is not self._kbd_fill_slider:
            if self._kbd_fill_slider is not None:
                self._kbd_fill_slider.set_kbd_fill_active(False)
            if new_fill_slider is not None:
                new_fill_slider.set_kbd_fill_active(True)
            self._kbd_fill_slider = new_fill_slider

        if (self.config.get_keyboard_marker_style() == "fill_highlight"
                and not isinstance(QApplication.focusWidget(), ClickSlider)):
            # Alternate style (2026-09-08 live design ask, after the ramp buttons' focus
            # color was found to be a flat theme-dict color by mistake rather than derived
            # from accent — see themes.derive_lighter_accent_rgb's docstring): no separate
            # marker widget at all. The focused control's own QSS renders the highlight
            # directly via [kbdnav="true"][kbdnav_fill_active="true"]:focus (see
            # get_panel_base_stylesheet) — a property EXCLUSIVE to this style, deliberately NOT
            # reused for the SAME purpose kbdnav_marker_active serves under "traveling" (that
            # one is the marker's own patrol-visibility flag — see
            # _on_focus_marker_dormant_changed's CORRECTION note for the live bug that came from
            # conflating the two in the QSS gate). No patrol/idle-fade lifecycle to track here —
            # a static fill has nothing to animate.
            #
            # CORRECTION (live report, same session: "rampup buttons lost their highlight along
            # the way"): Speed/Sleep/Sprint's own preset-ramp buttons keep their EXISTING
            # per-instance :focus rule under this style (Pryme's explicit call: "Keep it. Just
            # dropping the travel marker would suffice there") — but that existing rule is gated
            # on `kbdnav_marker_active`, which is normally written ONLY by
            # _on_focus_marker_dormant_changed, itself only ever called from the marker's own
            # _enter_patrol/_on_fade_finished/clear() — none of which ever run under
            # fill_highlight, since show_for/clear are never invoked on the marker in this style.
            # So kbdnav_marker_active silently never went true here, and the ramp buttons'
            # existing rule never fired. Fix: also drive kbdnav_marker_active off the same
            # `active` value the new property gets — the ramp buttons don't know or care which
            # style is active, they just need this property to keep tracking "keyboard nav is
            # genuinely driving this panel," which is exactly what it means under EITHER style.
            panel_key = self._kbdnav_active_panel_key()
            panel = self._kbdnav_panel_widget(panel_key) if panel_key is not None else None
            if panel is None:
                return
            focus = QApplication.focusWidget()
            active = self._keyboard_nav_active and self._focus_marker_in_scope(focus)
            self._set_kbdnav_fill_active_property(panel, active)
            self._set_kbdnav_property(panel, "kbdnav_marker_active", active)
            # Tab-bar case (2026-09-09 live report: "fill highlight doesn't highlight the
            # selected tab"). kbdnav_fill_active alone can't drive the tab's own QSS rule,
            # because that property means "keyboard nav is active somewhere in this panel" —
            # true even while focus is actually on a BUTTON inside a tab, which would then
            # paint the tab's fill AND the button's fill simultaneously (the exact "which one
            # does Enter act on" ambiguity this whole modality system exists to avoid — see
            # _set_keyboard_nav_active's own docstring for the 2026-09-03 incident that
            # established that principle). A narrower, tab-bar-EXCLUSIVE property is needed:
            # true only when the tab bar itself is the genuinely focused widget. The tab's own
            # QSS rule (get_settings_stylesheet) reads THIS property, not kbdnav_fill_active —
            # see that rule's comment for why a :focus pseudo-state chained onto ::tab:selected
            # was tried first and rejected (paint artifacts, 2026-09-08).
            #
            # CORRECTION (2026-09-09, second live report same day: "Highlight fill mode has no
            # impact on the tabs" — on Stats specifically): this was hardcoded to
            # self.tabs.tabBar() (Settings' own QTabWidget) only. Stats has a SEPARATE
            # QTabWidget instance (self.stats_panel.tabs) and was never checked, so
            # kbdnav_tab_focused could never go true there even once Stats joined the
            # kbdnav panel set. Generalized via _kbdnav_tab_bar_for(panel_key) so any future
            # tabbed panel needs only one new entry there, not a second hardcoded check here.
            tab_bar = self._kbdnav_tab_bar_for(panel_key)
            tab_bar_focused = active and tab_bar is not None and focus is tab_bar
            self._set_kbdnav_property(panel, "kbdnav_tab_focused", tab_bar_focused)
            return
        marker = getattr(self, 'focus_marker', None)
        if marker is None:
            return
        if not self._keyboard_nav_active:
            marker.clear()
            return
        focus = QApplication.focusWidget()
        # A ClickSlider under fill_highlight is handled entirely by the kbd_fill_active
        # sync above (this branch is only reached for one because the outer isinstance
        # check above let it through) — it must NOT also get the traveling marker, or
        # it would show both a lit background AND the border marker at once.
        if (isinstance(focus, ClickSlider)
                and self.config.get_keyboard_marker_style() == "fill_highlight"):
            marker.clear()
        elif self._focus_marker_in_scope(focus):
            marker.show_for(focus)
        else:
            marker.clear()

    def _handle_library_nothing_focused_key(self, event) -> bool:
        """Library, "nothing focused" state (see _handle_tab_escape: Tab clears focus to this
        state rather than landing on the list, so the list is never scrolled to a mouse-hovered
        book just because the user pressed Tab). Any key _list_key itself would act on (arrows,
        Enter/Space/Alt+Enter, and the sort-field/view-mode shortcut letters and digits — see
        LibraryPanel._LIST_KEY_HANDLED_KEYS, the single source of truth for this set) hands focus
        to the list — matching the existing "arrow out of the search field also lands on the
        list" precedent — then explicitly resends this SAME key event to the newly-focused
        _list_view, so its own event()/keyPressEvent() overrides (_list_key) handle it exactly
        as they already do once the list has real focus.

        Originally arrow-keys-only (2026-07-10): confirmed live that this made the sort/view-mode
        shortcuts (added the same day) and Enter/Space/Alt+Enter silently do nothing from
        "nothing focused" — they only worked after an arrow press had already moved focus to the
        list once. Broadened to _LIST_KEY_HANDLED_KEYS so every key _list_key recognizes is
        reachable directly from this state, not just navigation.

        Does NOT rely on QApplication.focusWidget() to decide whether to act — confirmed via
        isolated testing (2026-07-10) that focusWidget() does not update synchronously within
        the same call stack as setFocus(), so a guard built on it either never fires or
        recurses infinitely once the resent event loops back through this same filter. Guards
        instead on the event object's own recursion marker (a private attribute stamped on the
        QKeyEvent instance itself) — set once, checked first, so the resent copy is never
        re-forwarded a second time regardless of what focusWidget() reports."""
        if getattr(event, '_fabulor_forwarded', False):
            return False
        if not hasattr(self, 'panel_manager') or not hasattr(self, 'library_panel'):
            return False
        if self.panel_manager.active_full_panel() != "library":
            return False
        # active_full_panel() returns "library" even when the Book Detail Panel is open OVER the
        # library (both are visible; library is checked first in the priority chain). But while
        # detail is up, these keys belong to it — its tag-add field and inline metadata editors
        # are QLineEdits, and typing `t`/`a`/`1`/etc. there must NOT be stolen and forwarded to
        # the library list underneath (which would change the library's sort/view mode and yank
        # focus away mid-edit). Bail if detail is showing. (2026-07-11 fix.)
        bd = getattr(self, 'book_detail_panel', None)
        if bd is not None and bd.isVisible():
            return False
        # Defer to ANY focused text field, same as _handle_tab_escape does — if the user is
        # typing (library search, sleep minutes, a tag/metadata editor), these keys are text,
        # not library shortcuts. The two library-owned widgets below are a subset of this, but
        # keep them explicit for the "focus already on the list/search" no-op intent.
        focus = QApplication.focusWidget()
        if isinstance(focus, QLineEdit):
            return False
        if focus is self.library_panel.search_field or focus is self.library_panel._list_view:
            return False
        self.library_panel._list_view.setFocus(Qt.FocusReason.TabFocusReason)
        forwarded = QKeyEvent(QEvent.Type.KeyPress, event.key(), event.modifiers())
        forwarded._fabulor_forwarded = True
        QApplication.sendEvent(self.library_panel._list_view, forwarded)
        return True  # the original is fully replaced by the forwarded copy above

    def eventFilter(self, obj, event):
        """Global event filter to handle dismissing popups on clicks outside."""
        # [PLAYBTN-PAINT] probe (2026-08-15) — env-gated, off by default.
        # Answers "what repaints play_pause_button every ~200ms with nothing
        # moving", the same shape of bug as [CHAPTER-LABEL-PAINT]
        # (current_chapter_label's marquee). play_pause_button is a bare
        # QPushButton with no paintEvent override in Fabulor code, so an
        # event filter is the only way to see its Paint events — installed
        # here because MainWindow already filters QApplication-wide and this
        # class already branches eventFilter on obj identity for other
        # widgets (eof_revert_btn, below), so no new filter object or
        # install call is needed.
        if (_GRAB_TRACE_ENABLED and event.type() == QEvent.Type.Paint
                and hasattr(self, 'play_pause_button') and obj is self.play_pause_button):
            import traceback
            logger.debug(
                "[PLAYBTN-PAINT] rect=%s obj=%s text=%r icon_null=%s\n%s",
                event.rect(), obj.objectName(), obj.text(), obj.icon().isNull(),
                "".join(traceback.format_stack(limit=8)),
            )
        # [MUTEDICON-PAINT] probe (2026-08-15) — env-gated, off by default.
        # Same question as [PLAYBTN-PAINT], different widget: a second
        # rectangular blur artifact was reported live over the vol_stack
        # region while muted (main does not show it). muted_icon_label is a
        # bare QLabel with no paintEvent override, same shape as
        # play_pause_button, so the same event-filter approach applies.
        if (_GRAB_TRACE_ENABLED and event.type() == QEvent.Type.Paint
                and hasattr(self, 'muted_icon_label') and obj is self.muted_icon_label):
            import traceback
            logger.debug(
                "[MUTEDICON-PAINT] rect=%s obj=%s\n%s",
                event.rect(), obj.objectName(),
                "".join(traceback.format_stack(limit=8)),
            )
        # RIGHT-CLICK DELIVERY PROBE (restored 2026-07-28). Removed once when the
        # input-level question looked settled; the panel-CLOSE case was never
        # covered by that conclusion, and clicks are still going missing there.
        #
        # Installed on QApplication, so it sees every press Qt dispatches anywhere,
        # before any widget handler runs. Deduplicated on event.timestamp(): Qt
        # dispatches one physical press to several objects, and counting each was
        # what produced the bogus "236 for 100 clicks" figure the first time round.
        #
        # Read it against how many times you actually clicked:
        #   grep '\[RCLICK\]' fabulor.log | wc -l
        if event.type() == QEvent.Type.MouseButtonPress:
            # PRIMARY input-modality clear for the traveling focus marker (see
            # _update_focus_marker). ANY physical button press means the user is driving with
            # the mouse, so the keyboard-navigation affordance must stop showing. This lives at
            # the general MouseButtonPress level, NOT inside the Qt.RightButton branch below —
            # a LEFT-click is the main case, and it never reaches that branch.
            #
            # Why a press and not QFocusEvent.reason(): NO focus reason reliably identifies
            # "the user is using the mouse" here. Measured live 2026-09-03 on the Settings tab
            # bar, a single mouse click on a tab produces BOTH of these, milliseconds apart:
            #   OtherFocusReason  — also the reason for the legitimate keyboard two-step hop
            #                       (Tab lands on the tab bar, Qt forwards focus to a
            #                       pattern_button ~2ms later), so it cannot mean "mouse"
            #   TabFocusReason    — because focus is moving TO A TAB, not because Tab was
            #                       pressed; this one had to be measured to be believed, and it
            #                       is what defeated the first version of this fix (the press
            #                       cleared the flag at 23:03:55,452 and the TabFocusReason
            #                       focus event re-set it 3ms later at 23:03:55,455)
            # A physical button press is the only unambiguous signal, so it is recorded here and
            # allowed to WIN over the reason for _MOUSE_PRESS_FOCUS_WINDOW_S — see
            # _update_focus_marker.
            #
            # Deliberately OUTSIDE the try/except below: that guard exists to swallow failures
            # in the [RCLICK] probe's own panel_manager access, and a plain attribute write
            # cannot raise AttributeError/RuntimeError. Keeping it out means a future edit to
            # the probe can never silently swallow a failed modality clear.
            self._set_keyboard_nav_active(False)
            self._last_mouse_press_t = time.perf_counter()
            try:
                if event.button() == Qt.RightButton:
                    _stamp = int(event.timestamp())
                    if _stamp not in self._rclick_seen:
                        self._rclick_seen.add(_stamp)
                        self._rclick_n = getattr(self, '_rclick_n', 0) + 1
                        pm = self.panel_manager
                        logger.warning(
                            f"[RCLICK] #{self._rclick_n} "
                            f"active_panel={pm.active_full_panel() if pm else None!r} "
                            f"sidebar_expanded={pm.sidebar_expanded if pm else None} "
                            f"any_animating={pm._any_panel_animating() if pm else None} "
                            f"t={time.perf_counter():.6f}"
                        )
            except (AttributeError, RuntimeError):
                pass

        if event.type() == QEvent.Type.KeyPress:
            # Assert keyboard mode from the KEY PRESS itself, before any handler runs — the
            # mirror of the MouseButtonPress clear below, and for the same reason: a press
            # states intent unambiguously, whereas the focus event that may follow it does not.
            #
            # Inferring this downstream from TabFocusReason (the original design) missed two
            # cases reported live 2026-09-04, both of which move the SELECTION without producing
            # a qualifying focus event:
            #   * Left/Right ON THE TAB BAR — focus never leaves the tab bar, so no focus event
            #     fires at all and a hovered tab stayed highlighted while the keys drove.
            #   * Left/Right BETWEEN BUTTONS — handled natively by Qt (see
            #     _handle_settings_arrows, which deliberately returns False for those), and a
            #     native sibling focus move does not carry TabFocusReason.
            # Scoped THREE ways, each closing a real failure:
            #   * to the navigation keys, so ordinary typing and non-navigational shortcuts
            #     leave the modality alone;
            #   * skipped while a text field has focus, matching _handle_tab_escape's own
            #     deference to QLineEdit;
            #   * and only where the marker actually operates — a keyboard-navigable PANEL.
            #     Asserting app-wide stranded the flag: arrowing around a tab with no hand-back
            #     targets set it True where _cursor_over_navigable_control could never clear
            #     it, so :hover stayed dead until a button was clicked. Narrowing it to the
            #     LOOK TAB then broke the tab bar instead, since arrowing through tabs leaves
            #     Look by definition. The whole PANEL is the correct scope: it is exactly the
            #     set of controls the hand-back check also recognises (tab bar always, Look
            #     buttons when Look is up — or, for Speed/Sleep/Sprint, that panel's own rows),
            #     which is the property that makes the flag reliably clearable. Both
            #     regressions reported live 2026-09-04; generalized from Settings-only to all
            #     four panels 2026-09-07 via _kbdnav_active_panel_key — same invariant, now
            #     checked against whichever panel is actually open.
            if (event.key() in _KBDNAV_ASSERT_KEYS
                    and not isinstance(QApplication.focusWidget(), QLineEdit)
                    and self._kbdnav_active_panel_key() is not None):
                self._set_keyboard_nav_active(True)
            if self._handle_tab_escape(event):
                return True
            # Look-tab arrow navigation. After _handle_tab_escape (which owns Tab/Backtab and
            # never sees arrows) and before the library branch, whose own arrow handling is
            # gated on the Library panel being the active one, so the two cannot both claim a
            # key. Self-gating: returns False immediately unless Settings > Look is active.
            if self._handle_settings_arrows(event):
                return True
            if self._handle_themes_shortcuts(event):
                return True
            if self._redirect_digit_to_panel_input(event):
                return True
            if self._handle_flat_panel_arrows(event):
                return True
            if self._handle_stats_arrows(event):
                return True
            if (hasattr(self, 'library_panel')
                    and event.key() in self.library_panel._LIST_KEY_HANDLED_KEYS):
                if self._handle_library_nothing_focused_key(event):
                    return True

        # Persist search filter's row can end up COVERED by the Excluded Books popup when it's
        # expanded (it grows upward from a fixed bottom anchor, past DEFAULT_VISIBLE_ROWS —
        # see excluded_books.py) — reachable two ways: arriving fresh while already expanded
        # (native Left/Right stepping between PSF's own buttons never routes through
        # _handle_settings_arrows at all, so there's no key-press hook to catch it there), or
        # the box expanding out from under focus that was already sitting on a PSF button
        # (mouse-driven, no keypress at all). Both were reported live 2026-09-06 as the marker
        # showing up visually behind/under the expanded list. Checked here — right before the
        # marker would otherwise be pointed at the newly-focused control — rather than in
        # _handle_settings_arrows, since that method only ever sees keys, not every path focus
        # can actually move by. Redirecting INTO the box (its own normal entry point) rather
        # than just declining to show the marker: the box's own mouse/keyboard "most recent
        # move wins" coordination (see excluded_books.py) already handles a mouse hover
        # happening at the same moment, so this doesn't need its own separate arbitration.
        if event.type() == QEvent.Type.FocusIn and hasattr(self, 'excluded_books_popup'):
            focus = QApplication.focusWidget()
            psf_buttons = (set(getattr(self, 'persist_filter_buttons', {}).values())
                           | set(getattr(self, 'persist_filter_sub_buttons', {}).values()))
            if (focus in psf_buttons and self.excluded_books_popup.is_expanded):
                self.excluded_books_popup.setFocus(Qt.FocusReason.OtherFocusReason)
                return True

        # Traveling-border-marker keyboard-focus indicator (ui/focus_marker.py). Observe focus
        # changes app-wide and (re)point the marker at the focused control ONLY while it's in
        # scope (Settings > Look tab, this pass). Catches focus arriving by Tab, mouse click, or
        # panel open uniformly. Runs AFTER _handle_tab_escape so a Tab's setFocus has already
        # landed and QApplication.focusWidget() reflects the NEW target.
        if event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            self._update_focus_marker(reason=event.reason())

        if hasattr(self, 'eof_revert_btn') and obj is self.eof_revert_btn:
            if event.type() == QEvent.Enter:
                self.eof_revert_btn.set_icons(*self._eof_revert_pixmaps_hover)
            elif event.type() == QEvent.Leave:
                self.eof_revert_btn.set_icons(*self._eof_revert_pixmaps)

        # One-shot: library_tab is built at startup but stays hidden inside
        # the QTabWidget until the user's first-ever Settings open. Geometry
        # queried before its FIRST real Show event (and the layout pass that
        # comes with it) is unreliable — confirmed live: the excluded-books
        # list was invisible and badly mispositioned on the very first open
        # only, self-correcting every time after. singleShot(0, ...) wasn't a
        # long enough defer (it doesn't wait for this specific event); this
        # does, and only runs once.
        if (not self._library_tab_shown_once and hasattr(self, 'library_tab')
                and obj is self.library_tab and event.type() == QEvent.Type.Show):
            self._library_tab_shown_once = True
            if hasattr(self, 'excluded_books_section') and hasattr(self, 'excluded_books_popup'):
                self.excluded_books_popup.reposition(self.excluded_books_section, self.library_tab)

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
                # Excluded Books list: a click anywhere inside settings_panel
                # but outside the list itself (another tab, a button, empty
                # space) COLLAPSES it back to the default view — the list is
                # always visible now (not click-to-open/dismiss), so there's
                # nothing to "close"; an expanded view just isn't a
                # standalone modal state anymore. Never consumes the event,
                # so the underlying click (tab switch, button press) still
                # fires normally.
                if hasattr(self, 'excluded_books_popup') and self.excluded_books_popup.is_expanded:
                    local_pos = self.mapFromGlobal(event.globalPosition().toPoint())
                    # The popup is parented to library_tab now (not
                    # MainWindow), so its geometry() is in library_tab's own
                    # coordinate system — map its rect into MainWindow
                    # coordinates before comparing against local_pos.
                    popup_topleft = self.excluded_books_popup.mapTo(self, self.excluded_books_popup.rect().topLeft())
                    popup_rect = QRect(popup_topleft, self.excluded_books_popup.size())
                    inside_popup = popup_rect.contains(local_pos)
                    inside_panel = self.settings_panel.isVisible() and self.settings_panel.geometry().contains(local_pos)
                    if inside_panel and not inside_popup:
                        self._collapse_excluded_books()
        except Exception:
            pass

        if event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress):
            if hasattr(self, 'library_panel'):
                # Abort any in-flight preload so the interaction isn't contended, then
                # (re)arm the 5s idle timer. Re-arming on EVERY interaction — not only when
                # a preload is already pending — is what makes the first post-startup run
                # wait for a genuine 5s idle window (the queue is empty before the first
                # run, so preload_complete() is True then; gating on it would skip the
                # reset and let the initial run fire mid-interaction).
                self.library_panel.cancel_preload()
                self._arm_preload_idle()

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

        # Stop dispatching new cover-loader jobs, then block until every job already
        # handed to the shared QThreadPool has finished — QThreadPool has no API to
        # cancel a running QRunnable, only to drop ones not yet started, so this wait
        # is the only way to stop a worker thread from emitting into (or a queued
        # slot from touching) a widget tree Qt is about to start deleting below. All
        # CoverLoaderWorker dispatch sites (library preload, stats_panel, tag_manager)
        # share this one global pool, so this covers all of them, not just the
        # preloader. See NOTES.md 2026-08-12 "Signal source has been deleted" on close.
        self.library_panel.cancel_preload()
        QThreadPool.globalInstance().waitForDone(2000)
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
