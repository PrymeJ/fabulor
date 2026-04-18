import random
from PySide6.QtWidgets import QLabel, QGraphicsOpacityEffect, QPushButton, QComboBox
from PySide6.QtCore import Qt, QPropertyAnimation, QTimer, Signal, QPoint
from PySide6.QtGui import QFont, QFontMetrics
from ..themes import get_stylesheet, THEMES

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

class ThemeManager:
    """Manages theme application, previews, and multi-selection pool."""
    def __init__(self, main_window):
        self.main_window = main_window
        self.config = main_window.config
        
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
        self._packed_themes_cache = None
        self._active_display_theme = self._current_theme_name

        # Rotation Timer
        self.rotation_timer = QTimer()
        self.rotation_timer.timeout.connect(self._rotate_theme)
        self.set_rotation_interval(self.config.get_theme_rotation_interval())

        self._save_on_fade = False

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

    def _on_fade_finished(self):
        self._fade_overlay.hide()
        if self._save_on_fade:
            self._cached_theme_pixmap = self.main_window.grab()

    def get_packed_themes(self, limit=290, spacing=6, padding=10):
        if self._packed_themes_cache is not None:
            return self._packed_themes_cache

        bold_font = QFont()
        bold_font.setBold(True)
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
            rows.append(row)

        self._packed_themes_cache = rows
        return rows

    def _rotate_theme(self):
        if len(self.selected_themes) > 1:
            pool = [t for t in self.selected_themes if t != self._current_theme_name]
            self._current_theme_name = random.choice(pool)
            self._on_theme_changed(self._current_theme_name, save=False)

    def _on_theme_changed(self, theme_name, save=True, fade_ms=None):
        """Update the appearance with a subtle fade transition."""
        if fade_ms is None:
            fade_ms = self.config.get_theme_fade_duration()

        # Guard against redundant style updates
        if getattr(self, "_active_display_theme", None) == theme_name:
            return

        # Guard against theme changes during panel animation to prevent hitches
        if self.main_window.panel_manager and self.main_window.panel_manager._any_panel_animating():
            QTimer.singleShot(150, lambda: self._on_theme_changed(theme_name, save, fade_ms))
            return

        self._active_display_theme = theme_name

        # Clear any in-progress animation
        if self._fade_anim.state() == QPropertyAnimation.Running:
            self._fade_anim.stop()

        if fade_ms > 0:
            pix = self.main_window.grab()
            self._fade_overlay.setPixmap(pix)
            self._fade_overlay.setGeometry(self.main_window.rect())
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

        self.main_window.setStyleSheet(get_stylesheet(theme_name))
        self.main_window._update_speed_grid_styling(theme_name)
        self.update_theme_list_visuals()

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
        # 1. Ensure it's in the selected pool
        if theme_name not in self.selected_themes:
            self.selected_themes.append(theme_name)
            self.config.set_theme(",".join(self.selected_themes)) # Save updated pool
        
        # 2. Make it the currently active theme for display and session
        self._current_theme_name = theme_name
        
        # 3. Apply the theme visually (this also sets _active_display_theme)
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
        self._on_theme_changed(theme_name, save=False, fade_ms=fade)

    def _on_theme_unhovered(self):
        """Revert preview back to the active session theme."""
        fade = int(self.config.get_theme_fade_duration() * 0.5)
        self._on_theme_changed(self._current_theme_name, save=False, fade_ms=fade)

    def update_theme_list_visuals(self):
        """Dim unselected themes and highlight selected ones."""
        for name, btn in self.theme_widgets.items():
            is_selected = name in self.selected_themes
            is_active_display = (name == self._current_theme_name)
            
            btn.setProperty("selected", is_selected) # For selected in pool
            btn.setProperty("active_display", is_active_display) # For currently displayed
            # Trigger style refresh for property change
            btn.style().unpolish(btn)
            btn.style().polish(btn)