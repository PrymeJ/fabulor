class SettingsController:
    """Handles logic for application settings and synchronizes visual states."""
    def __init__(self, config, visuals, library, player):
        self.config = config
        self.visuals = visuals
        self.library = library
        self.player = player

    def bind_mainwindow_handlers(self, main):
        """Rebinds MainWindow local methods to controller implementations."""
        main._update_naming_pattern = self._update_naming_pattern
        main._update_scroll_mode = self._update_scroll_mode
        main._update_hints_mode = self._update_hints_mode
        main._update_undo_mode = self._update_undo_mode
        main._update_fade_mode = self._update_fade_mode
        main._update_blur_mode = self._update_blur_mode
        main._update_speed_grid_styling = self._update_speed_grid_styling
        main._validate_smart_rewind_settings = self._validate_smart_rewind_settings

    def _update_naming_pattern(self, pattern):
        """Changes the folder parsing pattern and triggers a database re-parse."""
        #print(f"[SettingsController] _update_naming_pattern called with: {pattern}")
        self.config.set_naming_pattern(pattern)
        self.library.reparse_db(pattern)
        self._update_pattern_visuals()
        self.library.refresh_library_panel(force=True)
        current_file = self.player.get_current_file()
        if current_file:
            self.player.load_cover_art(current_file)
        #self._debug_settings_state()

    def _update_pattern_visuals(self):
        """Updates the highlight/dim state of naming pattern buttons."""
        current = self.config.get_naming_pattern()
        self.visuals.set_naming_pattern_selection(current)

    def _update_scroll_mode(self, mode):
        #print(f"[SettingsController] _update_scroll_mode called with: {mode}")
        self.config.set_scroll_mode(mode)
        self._update_scroll_mode_visuals()
        #self._debug_settings_state()

    def _update_scroll_mode_visuals(self):
        current = self.config.get_scroll_mode()
        if hasattr(self.visuals, 'set_scroll_selection'):
            self.visuals.set_scroll_selection(current)

    def _update_hints_mode(self, enabled):
        #print(f"[SettingsController] _update_hints_mode called with: {enabled}")
        """Changes the chapter hint visibility setting."""
        self.config.set_chapter_hints_enabled(enabled)
        self._update_hints_visuals()
        #self._debug_settings_state()

    def _update_hints_visuals(self):
        """Updates the highlight state of hint toggle buttons."""
        enabled = self.config.get_chapter_hints_enabled()
        if hasattr(self.visuals, 'set_hints_selection'):
            self.visuals.set_hints_selection(enabled)

    def _update_undo_mode(self, val):
        #print(f"[SettingsController] _update_undo_mode called with: {val}")
        self.config.set_undo_duration(val)
        self._update_undo_visuals()
        #self._debug_settings_state()

    def _update_undo_visuals(self):
        current = self.config.get_undo_duration()
        if hasattr(self.visuals, 'set_undo_selection'):
            self.visuals.set_undo_selection(current)

    def _update_fade_mode(self, ms):
        #print(f"[SettingsController] _update_fade_mode called with: {ms}")
        """Changes the theme hover fade duration."""
        self.config.set_theme_fade_duration(ms)
        self._update_fade_visuals()
        #self._debug_settings_state()

    def _update_fade_visuals(self):
        """Updates the highlight state of fade buttons."""
        current = self.config.get_theme_fade_duration()
        if hasattr(self.visuals, 'set_fade_selection'):
            self.visuals.set_fade_selection(current)

    def _update_blur_mode(self, enabled):
        #print(f"[SettingsController] _update_blur_mode called with: {enabled}")
        """Changes the blur setting."""
        self.config.set_blur_enabled(enabled)
        self._update_blur_visuals()
        #self._debug_settings_state()

    def _update_blur_visuals(self):
        """Updates the highlight state of blur buttons."""
        enabled = self.config.get_blur_enabled()
        if hasattr(self.visuals, 'set_blur_selection'):
            self.visuals.set_blur_selection(enabled)

    def _update_speed_grid_styling(self, theme_name=None):
        """Applies current theme's styling to various settings components."""
        self._update_pattern_visuals()
        self._update_scroll_mode_visuals()
        self._update_hints_visuals()
        self._update_fade_visuals()
        self._update_blur_visuals()
        self._update_undo_visuals()
        if hasattr(self.visuals, 'update_speed_panel_visuals'):
            self.visuals.update_speed_panel_visuals(theme_name)

    def _validate_smart_rewind_settings(self):
        """Delegates validation to the speed panel via UI interface."""
        if hasattr(self.visuals, 'validate_speed_panel_settings'):
            self.visuals.validate_speed_panel_settings()

    # def _debug_settings_state(self):
    #     print("[Settings] scroll:", self.config.get_scroll_mode())
    #     print("[Settings] hints:", self.config.get_chapter_hints_enabled())
    #     print("[Settings] undo:", self.config.get_undo_duration())
    #     print("[Settings] fade:", self.config.get_theme_fade_duration())
    #     print("[Settings] blur:", self.config.get_blur_enabled())