from fabulor import themes
class SettingsController:
    """Handles logic for application settings and synchronizes visual states."""
    def __init__(self, config, visuals, panels, ui_callbacks, library, player):
        self.config = config
        self.visuals = visuals
        self.panels = panels
        self.ui_callbacks = ui_callbacks
        self.library = library
        self.player = player

    def bind_mainwindow_handlers(self, main):
        """Connects MainWindow signals to controller handler methods."""
        main.naming_pattern_changed.connect(self._update_naming_pattern)
        main.scroll_mode_changed.connect(self._update_scroll_mode)
        main.hints_mode_changed.connect(self._update_hints_mode)
        main.notches_mode_changed.connect(self._update_notches_mode)
        main.notch_animation_mode_changed.connect(self._update_notch_animation_mode)
        main.undo_mode_changed.connect(self._update_undo_mode)
        main.fade_mode_changed.connect(self._update_fade_mode)
        main.blur_mode_changed.connect(self._update_blur_mode)
        main.panel_backdrop_changed.connect(self._update_panel_backdrop)
        main.hover_fade_changed.connect(self._update_hover_fade)
        main.chapter_digit_mode_changed.connect(self._update_chapter_digit_mode)
        main.chapter_digit_autoplay_changed.connect(self._update_chapter_digit_autoplay)
        main.chapter_list_source_changed.connect(self._update_chapter_list_source)
        main._refresh_panel_visuals = self.sync_all_settings_visuals
        main._validate_smart_rewind_settings = self._validate_smart_rewind_settings

    def _update_naming_pattern(self, pattern):
        """Changes the folder parsing pattern and triggers a database re-parse."""
        self.config.set_naming_pattern(pattern)
        self.library.reparse_db(pattern)
        self._update_pattern_visuals()
        self.library.refresh_library_panel(force=True)
        current_file = self.player.get_current_file()
        if current_file:
            self.player.load_cover_art(current_file)

    def _update_pattern_visuals(self):
        """Updates the highlight/dim state of naming pattern buttons."""
        current = self.config.get_naming_pattern()
        self.visuals.set_naming_pattern_selection(current)

    def _update_scroll_mode(self, mode):
        self.config.set_scroll_mode(mode)
        self._update_scroll_mode_visuals()

    def _update_scroll_mode_visuals(self):
        current = self.config.get_scroll_mode()
        self.visuals.set_scroll_selection(current)

    def _update_hints_mode(self, mode):
        """Changes the chapter hint visibility setting."""
        self.config.set_chapter_hints_mode(mode)
        self._update_hints_visuals()

    def _update_hints_visuals(self):
        """Updates the highlight state of hint toggle buttons."""
        mode = self.config.get_chapter_hints_mode()
        self.visuals.set_hints_selection(mode)

    def _update_notches_mode(self, enabled):
        self.config.set_chapter_notches_enabled(enabled)
        self._update_notches_visuals()
        self.ui_callbacks.refresh_notches(skip_animation=True)

    def _update_notches_visuals(self):
        enabled = self.config.get_chapter_notches_enabled()
        self.visuals.set_notches_selection(enabled)

    def _update_notch_animation_mode(self, enabled):
        self.config.set_chapter_notch_animation_enabled(enabled)
        self._update_notch_animation_visuals()
        self.ui_callbacks.refresh_notches(skip_animation=True)

    def _update_notch_animation_visuals(self):
        enabled = self.config.get_chapter_notch_animation_enabled()
        self.visuals.set_notch_animation_selection(enabled)

    def _update_undo_mode(self, val):
        self.config.set_undo_duration(val)
        self._update_undo_visuals()

    def _update_undo_visuals(self):
        current = self.config.get_undo_duration()
        self.visuals.set_undo_selection(current)

    def _update_fade_mode(self, ms):
        """Changes the theme hover fade duration."""
        self.config.set_theme_fade_duration(ms)
        self._update_fade_visuals()

    def _update_fade_visuals(self):
        """Updates the highlight state of fade buttons."""
        current = self.config.get_theme_fade_duration()
        self.visuals.set_fade_selection(current)

    def _update_blur_mode(self, enabled):
        """Legacy On/Off entry point. Maps onto the three-state backdrop so any
        remaining caller of blur_mode_changed still works."""
        self._update_panel_backdrop("frosty" if enabled else "transparent")

    def _update_panel_backdrop(self, mode):
        """Panel backdrop: transparent | frosty | opaque (2026-07-28).

        Only 'frosty' runs the blur — get_blur_enabled() is defined as
        `mode == "frosty"`, which is why widening to three states did not have to
        touch any of the eleven blur call sites. 'opaque' deliberately does NOT
        blur: a fully opaque panel hides what is behind it, so blurring would be
        invisible work.

        The restyle lives HERE, on the mode-change path, and nowhere else.
        set_blur_selection is a visual sync called from the settings refresh batch;
        putting the restyle there made every sync a ~250ms blocking full pass
        (three per second — enough to stutter the panel slide and crash the app).
        """
        self.config.set_panel_backdrop(mode)
        # Applied BEFORE the restyle below — _resolve_theme reads the override while
        # building every stylesheet.
        themes.set_panel_alpha_override(self.config.get_panel_alpha_override())
        self._update_blur_visuals()
        # Repaint the already-open panels so the change lands immediately rather
        # than on the next open — the control lives inside Settings, so the user is
        # looking at the surface being changed.
        self.visuals.restyle_for_backdrop_change()
        # Covers the transport-bar overlay AND the cover-image blur.
        self.panels.apply_blur_live(self.config.get_blur_enabled())

    def _update_blur_visuals(self):
        self.visuals.set_blur_selection(self.config.get_panel_backdrop())

    def _update_hover_fade(self, mode):
        self.config.set_hover_fade_mode(mode)
        self._update_hover_fade_visuals()

    def _update_hover_fade_visuals(self):
        mode = self.config.get_hover_fade_mode()
        self.visuals.set_hover_fade_selection(mode)

    def _update_chapter_digit_mode(self, mode):
        self.config.set_chapter_digit_mode(mode)
        self._update_digit_mode_visuals()

    def _update_digit_mode_visuals(self):
        self.visuals.set_digit_mode_selection(self.config.get_chapter_digit_mode())

    def _update_chapter_digit_autoplay(self, enabled):
        self.config.set_chapter_digit_autoplay(enabled)
        self._update_digit_autoplay_visuals()

    def _update_digit_autoplay_visuals(self):
        self.visuals.set_digit_autoplay_selection(self.config.get_chapter_digit_autoplay())

    def _update_chapter_list_source(self, source):
        self.config.set_chapter_list_source(source)
        self._update_chapter_source_visuals()

    def _update_chapter_source_visuals(self):
        self.visuals.set_chapter_source_selection(self.config.get_chapter_list_source())

    def sync_all_settings_visuals(self, theme_name=None):
        """Syncs all settings button states and panel visuals to current config."""
        self._update_pattern_visuals()
        self._update_scroll_mode_visuals()
        self._update_hints_visuals()
        self._update_notches_visuals()
        self._update_notch_animation_visuals()
        self._update_fade_visuals()
        self._update_blur_visuals()
        self._update_hover_fade_visuals()
        self._update_undo_visuals()
        self._update_digit_mode_visuals()
        self._update_digit_autoplay_visuals()
        self._update_chapter_source_visuals()
        self.panels.update_speed_panel_visuals(theme_name)
        self.panels.update_sleep_panel_visuals()
        self.panels.update_audio_panel_visuals()

    def _validate_smart_rewind_settings(self):
        self.panels.validate_speed_panel_settings()