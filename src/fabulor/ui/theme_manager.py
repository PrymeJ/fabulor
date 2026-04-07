from PySide6.QtWidgets import QLabel, QGraphicsOpacityEffect, QComboBox, QListView
from PySide6.QtCore import Qt, QPropertyAnimation, QTimer, Signal, QPoint
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
    """Manages theme application, previews, and transitions."""
    def __init__(self, main_window):
        self.main_window = main_window
        self.config = main_window.config
        self._theme_selection_made = False
        self._current_theme_name = self.config.get_theme()
        self._previous_theme = None
        self._theme_fade_anim = None

    def _on_theme_changed(self, theme_name, save=True, fade_ms=None):
        """Update the appearance with a subtle fade transition."""
        if fade_ms is None:
            fade_ms = self.config.get_theme_fade_duration()

        # If the requested theme is already what's shown, just save and exit
        if getattr(self, "_current_theme_name", None) == theme_name:
            if save: self.config.set_theme(theme_name)
            return

        # Clear existing overlays to ensure we grab the "clean" state
        for old_overlay in self.main_window.findChildren(QLabel, "theme_fade_overlay"):
            old_overlay.setObjectName("deleting_overlay")
            old_overlay.hide() 

        self._current_theme_name = theme_name

        if fade_ms > 0:
            pix = self.main_window.grab()
            overlay = QLabel(self.main_window)
            overlay.setObjectName("theme_fade_overlay")
            overlay.setPixmap(pix)
            overlay.setGeometry(self.main_window.rect())
            overlay.setAttribute(Qt.WA_TransparentForMouseEvents)
            overlay.show()
            overlay.raise_()
            
            eff = QGraphicsOpacityEffect(overlay)
            overlay.setGraphicsEffect(eff)
            
            anim = QPropertyAnimation(eff, b"opacity", overlay)
            anim.setDuration(fade_ms)
            anim.setStartValue(1.0)
            anim.setEndValue(0.0)
            anim.finished.connect(overlay.deleteLater)
            anim.start()
            self._theme_fade_anim = anim

        if save:
            self.config.set_theme(theme_name)
        self.main_window.setStyleSheet(get_stylesheet(theme_name))
        self.main_window._update_speed_grid_styling()

    def _on_theme_dropdown_about_to_show(self):
        self._previous_theme = self.config.get_theme()
        self._theme_selection_made = False

    def _on_theme_dropdown_about_to_hide(self):
        QTimer.singleShot(10, self._check_revert_theme)

    def _check_revert_theme(self):
        # Only revert if no selection was made AND the currently displayed theme (potential preview) is
        # different from the theme that was active when the dropdown was opened.
        # This prevents redundant style sheet applications and dropdown text resets.
        if not self._theme_selection_made and self._previous_theme is not None and \
           self._current_theme_name != self._previous_theme: # Added check for actual change
            fade = int(self.config.get_theme_fade_duration() * 0.66)
            self._on_theme_changed(self._previous_theme, save=False, fade_ms=fade)
            self.main_window.theme_dropdown.setCurrentText(self._previous_theme)

    def _on_theme_hovered(self, index):
        """Preview the theme visually without saving to config."""
        theme_name = self.main_window.theme_dropdown.itemText(index)
        fade = int(self.config.get_theme_fade_duration() * 0.5)
        self._on_theme_changed(theme_name, save=False, fade_ms=fade)

    def _on_theme_selected_from_dropdown(self, index):
        """Permanent selection made by user."""
        self._theme_selection_made = True
        theme_name = self.main_window.theme_dropdown.itemText(index)
        self._on_theme_changed(theme_name)