import random
from PySide6.QtWidgets import QLabel, QGraphicsOpacityEffect, QPushButton, QComboBox
from PySide6.QtCore import Qt, QPropertyAnimation, QTimer, Signal, QPoint, QObject
from PySide6.QtGui import QFont, QFontMetrics, QRegion
from ..themes import (
    get_base_stylesheet, get_title_bar_stylesheet, get_player_stylesheet,
    get_library_stylesheet, get_settings_stylesheet, get_sidebar_stylesheet,
    get_stats_stylesheet, THEMES
)

_THEME_SWITCH_FADE_MS = 750       # fade duration for non-hover theme switches
_PANEL_ANIM_GUARD_MS  = 700       # delay before retrying a theme change mid-panel-animation


class ThemeComboBox(QComboBox):
    """Custom QComboBox that provides signals for popup visibility events."""
    aboutToShowPopup = Signal()
    aboutToHidePopup = Signal()

    def showPopup(self):
        # Ensure mouse tracking is enabled for the popup view to trigger highlighted signals
        self.view().setMouseTracking(True)
        self.view().viewport().setMouseTracking(True)
        self.aboutToShowPopup.emit()
        super().showPopup()

    def hidePopup(self):
        super().hidePopup()
        self.aboutToHidePopup.emit()

class ThemeManager(QObject):
    """Manages theme application, previews, and multi-selection pool."""
    theme_applied = Signal(dict)

    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.config = main_window.config
        self._is_hover_active = False
        
        # Load selection pool from config
        saved = self.config.get_theme()
        if "," in saved:
            self.selected_themes = [t.strip() for t in saved.split(",") if t.strip()]
        else:
            self.selected_themes = [saved] if saved else ["The Color Purple"]
            
        # Filter invalid themes and ensure fallback
        self.selected_themes = [t for t in self.selected_themes if t in THEMES]
        if not self.selected_themes:
            self.selected_themes = ["The Color Purple"]

        # Initial selection for this session: pick a random one from the pool
        if len(self.selected_themes) > 1:
            self._current_theme_name = random.choice(self.selected_themes)
        else:
            self._current_theme_name = self.selected_themes[0]

        self._theme_fade_anim = None
        self.theme_widgets = {} # theme_name -> QPushButton
        self.interval_widgets = {} # minutes -> QPushButton
        self.cover_art_mode_widgets = {} # mode -> QPushButton
        self.pool_container = None # QWidget hidden when exclusive mode is active
        self.cover_pool_btn = None # ThemeItem for cover art entry in the pool first row
        self._packed_themes_cache = None
        self._packed_themes_limit = None
        self._active_display_theme = self._current_theme_name

        # Cover-art derived theme (dict or None)
        self._cover_theme: dict | None = None
        self._cover_theme_active = False  # True when cover theme is currently displayed

        # Rotation Timer
        self.rotation_timer = QTimer()
        self.rotation_timer.timeout.connect(self._rotate_theme)
        self.set_rotation_interval(self.config.get_theme_rotation_interval())

        self._save_on_fade = False

    def get_current_theme(self) -> dict:
        if self._cover_theme_active and self._cover_theme:
            from ..themes import _resolve_theme
            return _resolve_theme(self._cover_theme)
        return THEMES.get(self._active_display_theme or self._current_theme_name,
                      THEMES["The Color Purple"])
    
    def initialize_fade_overlay(self):
        self._fade_overlay = QLabel(self.main_window)
        self._fade_overlay.setObjectName("theme_fade_overlay")
        self._fade_overlay.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._fade_overlay.hide()

        self._fade_effect = QGraphicsOpacityEffect(self._fade_overlay)
        self._fade_overlay.setGraphicsEffect(self._fade_effect)

        self._fade_anim = QPropertyAnimation(self._fade_effect, b"opacity", self._fade_overlay)
        self._fade_anim.setStartValue(1.0)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.finished.connect(self._on_fade_finished)

    def _apply_fade_mask(self):
        """Punch holes in the fade overlay for widgets that should not crossfade."""
        mw = self.main_window
        region = QRegion(mw.rect())
        for attr in ('progress_slider', 'progress_percentage_label'):
            w = getattr(mw, attr, None)
            if w and w.isVisible():
                region -= QRegion(w.rect().translated(w.mapTo(mw, QPoint(0, 0))))
        self._fade_overlay.setMask(region)

    def _on_fade_finished(self):
        self._fade_overlay.hide()
        if self._save_on_fade:
            self._cached_theme_pixmap = self.main_window.grab()

    def get_packed_themes(self, limit=230, spacing=0, padding=0):
        if self._packed_themes_cache is not None and self._packed_themes_limit == limit:
            return self._packed_themes_cache
        self._packed_themes_limit = limit

        bold_font = QFont()
        bold_font.setBold(True)
        bold_font.setPixelSize(12)
        metrics = QFontMetrics(bold_font)

        themes_to_pack = [
            {'name': name, 'width': metrics.horizontalAdvance(name) + padding}
            for name in THEMES.keys()
        ]
        themes_to_pack.sort(key=lambda x: x['width'], reverse=True)

        rows = []
        remaining = list(themes_to_pack)
        while remaining:
            row = []
            current_w = 0
            idx = 0
            while idx < len(remaining):
                item = remaining[idx]
                needed = item['width'] + (spacing if current_w > 0 else 0)
                if current_w + needed <= limit:
                    row.append(item)
                    current_w += needed
                    remaining.pop(idx)
                else:
                    idx += 1

            # Safety break: If the limit is so small that no item can fit, 
            # force the first remaining item into its own row to prevent an infinite loop.
            if not row and remaining:
                row.append(remaining.pop(0))

            rows.append(row)

        self._packed_themes_cache = rows
        return rows

    def _rotate_theme(self):
        mode = self.config.get_cover_art_theme_mode()
        if mode == "exclusive" and self._cover_theme:
            return  # cover theme owns the display in exclusive mode
        candidates = list(self.selected_themes)
        if mode == "with_pool" and self._cover_theme:
            candidates.append(None)  # None represents the cover theme slot
        if len(candidates) > 1:
            current = None if self._cover_theme_active else self._current_theme_name
            pool = [c for c in candidates if c != current]
            chosen = random.choice(pool)
            if chosen is None:
                self._cover_theme_active = True
                self._on_theme_changed(self._cover_theme, save=False)
            else:
                self._current_theme_name = chosen
                self._cover_theme_active = False
                self._on_theme_changed(chosen, save=False)

    def _on_theme_changed(self, theme_name, save=True, fade_ms=None, hover=False):
        """Update the appearance with a subtle fade transition."""
        
        if fade_ms is None:
            fade_ms = self.config.get_theme_fade_duration()
        
        if not hover:
            fade_ms = _THEME_SWITCH_FADE_MS

        # Only guard if both the theme and hover state match
        if (getattr(self, "_active_display_theme", None) == theme_name
                and self._is_hover_active == hover):
            return

        self._is_hover_active = hover

        # Guard against theme changes during panel animation to prevent hitches
        if self.main_window.panel_manager and self.main_window.panel_manager._any_panel_animating():
            QTimer.singleShot(_PANEL_ANIM_GUARD_MS, lambda: self._on_theme_changed(theme_name, save, fade_ms, hover))
            return

        self._active_display_theme = theme_name

        if not hasattr(self, '_fade_anim'):
            # Called before initialize_fade_overlay (e.g. on startup cover load) — apply silently
            self._apply_stylesheets(theme_name, hover=hover)
            if hasattr(self.main_window, '_update_speed_grid_styling'):
                self.main_window._update_speed_grid_styling(theme_name)
            if isinstance(theme_name, dict):
                from ..themes import _resolve_theme
                self.theme_applied.emit(_resolve_theme(theme_name))
            else:
                self.theme_applied.emit(THEMES.get(theme_name, THEMES["The Color Purple"]))
            self.update_theme_list_visuals()
            return

        # Clear any in-progress animation
        if self._fade_anim.state() == QPropertyAnimation.Running:
            self._fade_anim.stop()

        if fade_ms > 0:
            pix = self.main_window.grab()
            self._fade_overlay.setPixmap(pix)
            self._fade_overlay.setGeometry(self.main_window.rect())
            self._apply_fade_mask()
            self._fade_overlay.show()
            self._fade_overlay.raise_()

            self._save_on_fade = save
            self._fade_anim.setDuration(fade_ms)
            self._fade_anim.start()
            self._theme_fade_anim = self._fade_anim
        else:
            self._fade_overlay.hide()
            if save:
                self._cached_theme_pixmap = self.main_window.grab()

        self._apply_stylesheets(theme_name, hover=hover)
        if hasattr(self.main_window, '_update_speed_grid_styling'):
            self.main_window._update_speed_grid_styling(theme_name)
        if isinstance(theme_name, dict):
            from ..themes import _resolve_theme
            self.theme_applied.emit(_resolve_theme(theme_name))
        else:
            self.theme_applied.emit(THEMES.get(theme_name, THEMES["The Color Purple"]))
        self.update_theme_list_visuals()

    def _apply_stylesheets(self, theme_name, hover=False):
        mw = self.main_window
        mw.setStyleSheet(get_base_stylesheet(theme_name))
        if hasattr(mw, 'title_bar'):
            mw.title_bar.setStyleSheet(get_title_bar_stylesheet(theme_name))
        if hasattr(mw, 'content_container'):
            mw.content_container.setStyleSheet(get_player_stylesheet(theme_name))
        if not hover and hasattr(mw, 'library_panel'):
            mw.library_panel.setStyleSheet(get_library_stylesheet(theme_name))
            mw.library_panel.update_progress_bar_theme()
        ss_panels = get_settings_stylesheet(theme_name)
        for attr in ('settings_panel', 'speed_panel', 'sleep_panel'):
            w = getattr(mw, attr, None)
            if w:
                w.setStyleSheet(ss_panels)
        ss_stats = get_stats_stylesheet(theme_name)
        for attr in ('stats_panel', 'book_detail_panel'):
            target = getattr(mw, attr, None)
            if target:
                target.setStyleSheet(ss_stats)
        if hasattr(mw, 'sidebar'):
            mw.sidebar.setStyleSheet(get_sidebar_stylesheet(theme_name))

    def toggle_theme_selection(self, theme_name):
        """Toggle a theme's presence in the rotation pool."""
        if theme_name in self.selected_themes:
            if len(self.selected_themes) > 1: # Ensure we don't make the list empty
                self.selected_themes.remove(theme_name)
                # If we removed the session theme, pick a new one from the remaining pool
                if self._current_theme_name == theme_name:
                    self._current_theme_name = random.choice(self.selected_themes)
                    self._on_theme_changed(self._current_theme_name, save=False)
            # If it's the last selected theme, we don't remove it (pool cannot be empty)
        else:
            # Add to pool, but do NOT change the session active theme on left-click
            self.selected_themes.append(theme_name) 

        # Save the pool as a comma-separated string
        self.config.set_theme(",".join(self.selected_themes))
        self.update_theme_list_visuals()

    def select_all_themes(self):
        self.selected_themes = list(THEMES.keys())
        self.config.set_theme(",".join(self.selected_themes))
        self.update_theme_list_visuals()

    def deselect_all_themes(self):
        # Fallback to the current theme or a default so the list is never empty
        self.selected_themes = [self._current_theme_name]
        self.config.set_theme(",".join(self.selected_themes))
        self.update_theme_list_visuals()

    def set_rotation_interval(self, minutes):
        """Update the rotation interval and restart the timer if necessary."""
        self.config.set_theme_rotation_interval(minutes)
        self.rotation_timer.stop()
        
        if minutes > 0:
            # Convert minutes to milliseconds
            self.rotation_timer.start(minutes * 60 * 1000)
        
        self.update_interval_visuals()
    def _on_theme_right_clicked(self, theme_name):
        """Selects a theme and immediately activates it."""
        if theme_name not in self.selected_themes:
            self.selected_themes.append(theme_name)
            self.config.set_theme(",".join(self.selected_themes))
        self._current_theme_name = theme_name
        self._cover_theme_active = False
        self._on_theme_changed(theme_name, save=False)
        self.update_theme_list_visuals()
        self.update_interval_visuals()

    def update_interval_visuals(self):
        current_interval = self.config.get_theme_rotation_interval()
        for mins, btn in self.interval_widgets.items():
            btn.setProperty("selected", mins == current_interval)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _on_theme_hovered(self, theme_name):
        """Preview the theme visually."""
        fade = int(self.config.get_theme_fade_duration() * 0.5)
        self._on_theme_changed(theme_name, save=False, fade_ms=fade, hover=True)

    def _on_theme_unhovered(self):
        fade = int(self.config.get_theme_fade_duration() * 0.5)
        if self._cover_theme_active and self._cover_theme:
            self._on_theme_changed(self._cover_theme, save=False, fade_ms=fade, hover=False)
        else:
            self._on_theme_changed(self._current_theme_name, save=False, fade_ms=fade, hover=False)

    def update_theme_list_visuals(self):
        """Dim unselected themes and highlight selected ones."""
        for name, btn in self.theme_widgets.items():
            is_selected = name in self.selected_themes
            is_active_display = (name == self._current_theme_name) and not self._cover_theme_active

            btn.setProperty("selected", is_selected)
            btn.setProperty("active_display", is_active_display)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self._update_cover_pool_btn()

    # ── Cover-art theme ─────────────────────────────────────────────────────

    def apply_cover_theme(self, pixmap):
        """Build a theme dict from the cover pixmap and apply it if the mode calls for it."""
        from .cover_theme import build_cover_theme
        mode = self.config.get_cover_art_theme_mode()
        if mode == "off":
            return
        theme_dict = build_cover_theme(pixmap)
        if not theme_dict:
            return
        self._cover_theme = theme_dict
        self._cover_theme_active = True
        self._on_theme_changed(theme_dict, save=False)
        self._update_cover_pool_btn()

    def clear_cover_theme(self):
        """Revert to the pool theme. _cover_theme stays None so cover_pool_btn greys out."""
        self._cover_theme = None
        self._cover_theme_active = False
        self._on_theme_changed(self._current_theme_name, save=False)
        self._update_cover_pool_btn()

    def set_cover_art_mode(self, mode: str):
        """Switch cover art mode ('off', 'with_pool', 'exclusive') and reapply."""
        self.config.set_cover_art_theme_mode(mode)
        self.update_cover_art_mode_visuals()
        if mode == "off":
            if self._cover_theme_active:
                self.clear_cover_theme()
            else:
                self._on_theme_changed(self._current_theme_name, save=False)
        else:
            pixmap = getattr(self.main_window, 'current_cover_pixmap', None)
            if self._cover_theme is None and pixmap and not pixmap.isNull():
                self.apply_cover_theme(pixmap)
            elif self._cover_theme:
                self._cover_theme_active = True
                self._on_theme_changed(self._cover_theme, save=False)

    def update_cover_art_mode_visuals(self):
        current = self.config.get_cover_art_theme_mode()
        for mode, btn in self.cover_art_mode_widgets.items():
            btn.setProperty("selected", mode == current)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        if self.pool_container is not None:
            self.pool_container.setVisible(current != "exclusive")
        self._update_cover_pool_btn()

    def _update_cover_pool_btn(self):
        btn = self.cover_pool_btn
        if btn is None:
            return
        mode = self.config.get_cover_art_theme_mode()
        has_cover = self._cover_theme is not None
        in_pool = (mode == "with_pool")
        btn.setEnabled(mode == "off" or has_cover)  # always clickable in Off; needs cover in With pool
        btn.setProperty("selected", in_pool)
        btn.setProperty("active_display", self._cover_theme_active)
        btn.style().unpolish(btn)
        btn.style().polish(btn)

    def _on_cover_pool_btn_clicked(self):
        mode = self.config.get_cover_art_theme_mode()
        if mode == "off":
            # Add to pool: switch to With pool mode
            self.set_cover_art_mode("with_pool")
        else:
            # Remove from pool: deactivate if active, switch back to Off
            if self._cover_theme_active:
                self._cover_theme_active = False
                self._on_theme_changed(self._current_theme_name, save=False)
            self.set_cover_art_mode("off")

    def _on_cover_pool_btn_right_clicked(self):
        mode = self.config.get_cover_art_theme_mode()
        if not self._cover_theme:
            return
        # Ensure it's in the pool
        if mode == "off":
            self.config.set_cover_art_theme_mode("with_pool")
            self.update_cover_art_mode_visuals()
        # Activate the cover theme
        self._cover_theme_active = True
        self._on_theme_changed(self._cover_theme, save=False)
        self._update_cover_pool_btn()

    def _on_cover_pool_btn_hovered(self):
        if not self._cover_theme:
            return
        fade = int(self.config.get_theme_fade_duration() * 0.5)
        self._on_theme_changed(self._cover_theme, save=False, fade_ms=fade, hover=True)