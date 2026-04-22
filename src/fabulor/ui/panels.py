from PySide6.QtWidgets import QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QGridLayout, QApplication
from PySide6.QtWidgets import QLineEdit
from PySide6.QtCore import Qt, QPoint, QPropertyAnimation, QEasingCurve, QTimer
from PySide6.QtGui import QGuiApplication

# Import necessary components from fabulor
from ..config import Config
from ..themes import THEMES # Needed for _update_speed_grid_styling if it remains in MainWindow
from ..ui.theme_manager import ThemeComboBox # Needed for dropdowns in panel setup

class PanelManager:
    def __init__(self, main_window):
        self.main_window = main_window
        self.config = main_window.config # Access config through main_window
        
        # State variables
        self.sidebar_expanded = False
        self._pending_panel_open = None
        
        # Widgets (references passed from MainWindow)
        self.sidebar = main_window.sidebar
        self.library_panel = main_window.library_panel
        self.settings_panel = main_window.settings_panel
        self.speed_panel = main_window.speed_panel
        self.sleep_panel = main_window.sleep_panel
        self.blur_effect = main_window.blur_effect # Reference to the blur effect
        self.blur_animation = main_window.blur_animation # Reference to the blur animation

        # Animations (initialized in MainWindow, referenced here)
        self.sidebar_animation = main_window.sidebar_animation
        self.library_panel_animation = main_window.library_panel_animation
        self.settings_panel_animation = main_window.settings_panel_animation
        self.speed_panel_animation = main_window.speed_panel_animation
        self.sleep_panel_animation = main_window.sleep_panel_animation

        # Connect sidebar buttons to panel opening methods
        self.main_window.library_trigger_btn.clicked.connect(self._open_library_flow)
        self.main_window.go_to_library_btn.clicked.connect(self._open_library_flow)
        self.main_window.settings_trigger_btn.clicked.connect(self._open_settings_flow)
        self.main_window.speed_trigger_btn.clicked.connect(self._open_speed_flow)
        self.main_window.sleep_trigger_btn.clicked.connect(self._open_sleep_flow)

    def _toggle_sidebar(self):
        """Slides the sidebar in or out."""
        if self.sidebar_animation.state() == QPropertyAnimation.Running:
            return
            
        sidebar_y = 32 + 24 
        width = self.sidebar.width()

        if not self.sidebar_expanded:
            self.sidebar.raise_()
            self.sidebar_animation.setStartValue(QPoint(-width, sidebar_y))
            self.sidebar_animation.setEndValue(QPoint(0, sidebar_y))
            self.sidebar_expanded = True
        else:
            self.sidebar_animation.setStartValue(QPoint(0, sidebar_y))
            self.sidebar_animation.setEndValue(QPoint(-width, sidebar_y))
            self.sidebar_expanded = False
            
        self.sidebar_animation.start()

    def _open_library_flow(self):
        self.main_window._save_current_progress()
        if self.sidebar_expanded:
            self._pending_panel_open = "library"
            self.sidebar_animation.finished.connect(self._on_sidebar_closed_for_panel)
            self._toggle_sidebar()
        else:
            self._start_library_entry()

    def _start_library_entry(self):
        panel_w = self.main_window.width()
        sidebar_y = 32 # Start right under the TitleBar, covering the progress bar
        self.library_panel.setFixedWidth(panel_w)
        self.library_panel.setFixedHeight(self.main_window.height() - sidebar_y)
        self.library_panel.move(-panel_w, sidebar_y)
        self.library_panel.show()
        self.library_panel.raise_()

        # Set animation guard to prevent layout updates during slide
        self.library_panel._is_animating = True
        self.library_panel_animation.finished.connect(self._on_library_shown)
        
        self.library_panel_animation.setStartValue(QPoint(-panel_w, sidebar_y))
        self.library_panel_animation.setEndValue(QPoint(0, sidebar_y))
        self.library_panel_animation.start()
        
        if self.config.get_blur_enabled():
            self.blur_animation.setStartValue(0)
            self.blur_animation.setEndValue(10)
            self.blur_animation.start()

    def _on_library_shown(self):
        try: self.library_panel_animation.finished.disconnect(self._on_library_shown)
        except: pass
        self.library_panel._is_animating = False
        self.library_panel.refresh()

    def _open_settings_flow(self):
        """Hides sidebar first, then shows settings panel."""
        if self.sidebar_expanded:
            self._pending_panel_open = "settings"
            self.sidebar_animation.finished.connect(self._on_sidebar_closed_for_panel)
            self._toggle_sidebar()
        else:
            self._start_settings_entry()

    def _start_settings_entry(self):
        """Starts the settings panel slide-in animation. This is called directly or via _on_sidebar_closed_for_panel."""
        panel_w = int(self.main_window.width() * 0.9)
        sidebar_y = 56
        self.settings_panel.setFixedWidth(panel_w)
        self.settings_panel.move(-panel_w, sidebar_y)
        self.settings_panel.show()
        self.settings_panel.raise_()
        
        self.settings_panel_animation.setStartValue(QPoint(-panel_w, sidebar_y))
        self.settings_panel_animation.setEndValue(QPoint(0, sidebar_y))
        self.settings_panel_animation.start()
        
        if self.config.get_blur_enabled():
            self.blur_animation.setStartValue(0)
            self.blur_animation.setEndValue(10)
            self.blur_animation.start()
        else:
            self.blur_effect.setBlurRadius(0)

    def _open_speed_flow(self):
        if self.sidebar_expanded:
            self._pending_panel_open = "speed"
            self.sidebar_animation.finished.connect(self._on_sidebar_closed_for_panel)
            self._toggle_sidebar()
        else:
            self._start_speed_entry()

    def _start_speed_entry(self):
        """Starts the speed panel slide-in animation. This is called directly or via _on_sidebar_closed_for_panel."""
        panel_w = int(self.main_window.width() * 0.9)
        sidebar_y = 56
        self.speed_panel.setFixedWidth(panel_w)
        self.speed_panel.move(-panel_w, sidebar_y)
        self.speed_panel.show()
        self.speed_panel.raise_()
        
        self.speed_panel_animation.setStartValue(QPoint(-panel_w, sidebar_y))
        self.speed_panel_animation.setEndValue(QPoint(0, sidebar_y))
        self.speed_panel_animation.start()
        
        if self.config.get_blur_enabled():
            self.blur_animation.setStartValue(0)
            self.blur_animation.setEndValue(10)
            self.blur_animation.start()

    def _on_sidebar_closed_for_panel(self):
        """Handler for sidebar animation finishing when a panel needs to open."""
        try:
            self.sidebar_animation.finished.disconnect(self._on_sidebar_closed_for_panel)
        except RuntimeError:
            pass # Already disconnected or not connected, fine.

        if self._pending_panel_open == "library": self._start_library_entry()
        elif self._pending_panel_open == "settings": self._start_settings_entry()
        elif self._pending_panel_open == "speed": self._start_speed_entry()
        elif self._pending_panel_open == "sleep": self._start_sleep_entry()
        self._pending_panel_open = None

    def _close_library_flow(self):
        if self.library_panel_animation.state() == QPropertyAnimation.Running:
            return
        panel_w = self.library_panel.width()
        sidebar_y = 32

        # Set animation guard
        self.library_panel._is_animating = True

        self.library_panel_animation.setStartValue(QPoint(0, sidebar_y))
        self.library_panel_animation.setEndValue(QPoint(-panel_w, sidebar_y))
        self.library_panel_animation.finished.connect(self._on_library_hidden)
        self.library_panel_animation.start()

        if self.config.get_blur_enabled():
            self.blur_animation.setStartValue(self.blur_effect.blurRadius())
            self.blur_animation.setEndValue(0)
            self.blur_animation.start()

    def _on_library_hidden(self):
        try: self.library_panel_animation.finished.disconnect(self._on_library_hidden)
        except: pass
        self.library_panel._is_animating = False
        self.library_panel.hide()
        self.library_panel._detach_items()

    def _close_speed_flow(self):
        """Slides the speed panel back out."""
        if self.speed_panel_animation.state() == QPropertyAnimation.Running:
            return
        panel_w = self.speed_panel.width()
        sidebar_y = 56
        self.speed_panel_animation.setStartValue(QPoint(0, sidebar_y))
        self.speed_panel_animation.setEndValue(QPoint(-panel_w, sidebar_y))
        self.speed_panel_animation.finished.connect(self._on_speed_hidden)
        self.main_window._validate_smart_rewind_settings()
        self.speed_panel_animation.start()

        if self.config.get_blur_enabled():
            self.blur_animation.setStartValue(self.blur_effect.blurRadius())
            self.blur_animation.setEndValue(0)
            self.blur_animation.start()

    def _on_speed_hidden(self):
        try: self.speed_panel_animation.finished.disconnect(self._on_speed_hidden)
        except: pass
        self.speed_panel.hide()

    def _open_sleep_flow(self):
        """Hides sidebar first, then shows sleep panel."""
        if self.sidebar_expanded:
            self._pending_panel_open = "sleep"
            self.sidebar_animation.finished.connect(self._on_sidebar_closed_for_panel)
            self._toggle_sidebar()
        else:
            self._start_sleep_entry()

    def _start_sleep_entry(self):
        """Starts the sleep panel slide-in animation."""
        panel_w = int(self.main_window.width() * 0.9)
        sidebar_y = 56
        self.sleep_panel.setFixedWidth(panel_w)
        self.sleep_panel.move(-panel_w, sidebar_y)
        self.sleep_panel.show()
        self.sleep_panel.raise_()
        
        self.sleep_panel_animation.setStartValue(QPoint(-panel_w, sidebar_y))
        self.sleep_panel_animation.setEndValue(QPoint(0, sidebar_y))
        self.sleep_panel_animation.start()
        
        if self.config.get_blur_enabled():
            self.blur_animation.setStartValue(0)
            self.blur_animation.setEndValue(10)
            self.blur_animation.start()

    def _close_sleep_flow(self):
        """Slides the sleep panel back out."""
        if self.sleep_panel_animation.state() == QPropertyAnimation.Running:
            return
        panel_w = self.sleep_panel.width()
        sidebar_y = 56
        self.sleep_panel_animation.setStartValue(QPoint(0, sidebar_y))
        self.sleep_panel_animation.setEndValue(QPoint(-panel_w, sidebar_y))
        self.sleep_panel_animation.finished.connect(self._on_sleep_hidden)
        self.sleep_panel_animation.start()

        if self.config.get_blur_enabled():
            self.blur_animation.setStartValue(self.blur_effect.blurRadius())
            self.blur_animation.setEndValue(0)
            self.blur_animation.start()

    def _on_sleep_hidden(self):
        try: self.sleep_panel_animation.finished.disconnect(self._on_sleep_hidden)
        except: pass
        self.sleep_panel.hide()
        
    def _close_settings_flow(self):
        """Slides the settings panel back out."""
        if hasattr(self.main_window, 'theme_manager'):
            self.main_window.theme_manager._on_theme_unhovered()
        if self.settings_panel_animation.state() == QPropertyAnimation.Running:
            return
        panel_w = self.settings_panel.width()
        sidebar_y = 56
        self.settings_panel_animation.setStartValue(QPoint(0, sidebar_y))
        self.settings_panel_animation.setEndValue(QPoint(-panel_w, sidebar_y))
        self.settings_panel_animation.finished.connect(self._on_settings_hidden)
        self.settings_panel_animation.start()

        if self.config.get_blur_enabled():
            self.blur_animation.setStartValue(self.blur_effect.blurRadius())
            self.blur_animation.setEndValue(0)
            self.blur_animation.start()
        else:
            self.blur_effect.setBlurRadius(0)

    def _on_settings_hidden(self):
        try:
            self.settings_panel_animation.finished.disconnect(self._on_settings_hidden)
        except:
            pass
        self.settings_panel.hide()

    def _any_panel_animating(self):
        """Returns True if any sliding panel or blur animation is currently running."""
        animations = [
            self.sidebar_animation,
            self.library_panel_animation,
            self.settings_panel_animation,
            self.speed_panel_animation,
            self.sleep_panel_animation,
            self.blur_animation
        ]
        return any(anim.state() == QPropertyAnimation.Running for anim in animations)

    def is_any_panel_visible(self):
        """Returns True if the sidebar or any configuration panel is currently open."""
        return (
            self.sidebar_expanded or
            self.library_panel.isVisible() or
            self.settings_panel.isVisible() or
            self.speed_panel.isVisible() or
            self.sleep_panel.isVisible() or
            self.main_window.chapter_list_widget.isVisible()
        )

    def hide_all_panels(self):
        """Closes any open panels."""
        if self.main_window.chapter_list_widget.isVisible():
            self.main_window.chapter_list_widget.hide()
        if self.sidebar_expanded:
            self._toggle_sidebar()
        if self.library_panel.isVisible():
            self._close_library_flow()
        if self.settings_panel.isVisible():
            self._close_settings_flow()
        if self.speed_panel.isVisible():
            self._close_speed_flow()
        if self.sleep_panel.isVisible():
            self._close_sleep_flow()

    def handle_mouse_press(self, event):
        """Handles mouse press events to prevent panel dismissal when clicking inside."""
        for panel in [self.library_panel, self.settings_panel, self.speed_panel, self.sleep_panel]:
            if panel.isVisible() and panel.geometry().contains(event.pos()):
                return True # Event handled, do not propagate
        return False # Event not handled, propagate

    def handle_drag_area_right_click(self, event):
        """Handles right-click on drag area to dismiss panels or toggle sidebar."""
        if self.library_panel.isVisible():
            self._close_library_flow()
        elif self.settings_panel.isVisible():
            self._close_settings_flow()
        elif self.speed_panel.isVisible():
            self._close_speed_flow()
        elif self.sleep_panel.isVisible():
            self._close_sleep_flow()
        elif self.main_window.chapter_list_widget.isVisible():
            self.main_window.chapter_list_widget.hide()
        else:
            self._toggle_sidebar()

    def resize_panels(self):
        """Adjusts panel positions and sizes on window resize."""
        sidebar_y = 56 # 32 title + 24 progress for most panels
        library_y = 32 # 32 title for Library panel
        window_w = self.main_window.width()
        panel_w = int(self.main_window.width() * 0.9)
        
        # Hardcoded heights as requested
        self.sidebar.setFixedHeight(200)
        self.library_panel.setFixedWidth(window_w)
        self.library_panel.setFixedHeight(self.main_window.height() - library_y)

        for panel in [self.settings_panel, self.speed_panel, self.sleep_panel]:
            panel.setFixedWidth(panel_w)

        self.settings_panel.setFixedHeight(500)
        self.speed_panel.setFixedHeight(500)
        self.sleep_panel.setFixedHeight(500)

        # Update Speed Panel position if not animating
        if self.speed_panel_animation.state() != QPropertyAnimation.Running:
            x = 0 if self.speed_panel.isVisible() else -panel_w
            self.speed_panel.move(x, sidebar_y)

        # Ensure sidebar position is maintained during resize
        sidebar_x = 0 if self.sidebar_expanded else -self.sidebar.width()
        self.sidebar.move(sidebar_x, sidebar_y)
            
        # Update Library Panel position if not animating
        if self.library_panel_animation.state() != QPropertyAnimation.Running:
            x = 0 if self.library_panel.isVisible() else -window_w
            self.library_panel.move(x, library_y)
            
        # Update Settings Panel position if not animating
        if self.settings_panel_animation.state() != QPropertyAnimation.Running:
            x = 0 if self.settings_panel.isVisible() else -panel_w
            self.settings_panel.move(x, sidebar_y)

        # Update Sleep Panel position if not animating
        if self.sleep_panel_animation.state() != QPropertyAnimation.Running:
            x = 0 if self.sleep_panel.isVisible() else -panel_w
            self.sleep_panel.move(x, sidebar_y)