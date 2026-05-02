from PySide6.QtCore import QSettings

class Config:
    """Handles persistent application configuration and user preferences."""
    def __init__(self):
        self.settings = QSettings("Fabulor", "Fabulor") # Org, App

    def _safe_int(self, key, default):
        val = self.settings.value(key, default)
        if isinstance(val, (list, tuple)):
            val = val[0] if val else default
        return int(val)

    def _safe_float(self, key, default):
        val = self.settings.value(key, default)
        if isinstance(val, (list, tuple)):
            val = val[0] if val else default
        return float(val)

    def get_theme(self):
        return self.settings.value("theme", "default")

    def set_theme(self, name):
        self.settings.setValue("theme", name)

    def get_blur_enabled(self):
        return self.settings.value("blur_enabled", "false") == "true"

    def set_blur_enabled(self, enabled):
        self.settings.setValue("blur_enabled", str(enabled).lower())

    def get_theme_fade_duration(self):
        return self._safe_int("theme_fade_duration", 750)

    def set_theme_fade_duration(self, ms):
        self.settings.setValue("theme_fade_duration", ms)

    def get_volume(self):
        return self._safe_int("volume", 100)

    def set_volume(self, value):
        self.settings.setValue("volume", value)

    def get_skip_duration(self):
        return self._safe_int("skip_duration", 10)

    def set_skip_duration(self, seconds):
        self.settings.setValue("skip_duration", seconds)

    def get_long_skip_duration(self):
        return self._safe_int("long_skip_duration", 1)

    def set_long_skip_duration(self, minutes):
        self.settings.setValue("long_skip_duration", minutes)

    def get_smart_rewind_wait(self):
        return self._safe_int("smart_rewind_wait", 0)

    def set_smart_rewind_wait(self, minutes):
        self.settings.setValue("smart_rewind_wait", minutes)

    def get_smart_rewind_duration(self):
        return self._safe_int("smart_rewind_duration", 0)

    def set_smart_rewind_duration(self, seconds):
        self.settings.setValue("smart_rewind_duration", seconds)

    def get_speed_increment(self):
        return self._safe_float("speed_increment", 0.1)

    def set_speed_increment(self, value):
        self.settings.setValue("speed_increment", float(value))

    def get_default_speed(self):
        return self._safe_float("default_speed", 1.0)

    def set_default_speed(self, value):
        self.settings.setValue("default_speed", float(value))

    def get_book_speed(self, file_path):
        val = self.settings.value(f"speed_{file_path}")
        return float(val) if val is not None else None

    def set_book_speed(self, file_path, speed):
        self.settings.setValue(f"speed_{file_path}", speed)

    def get_day_start_hour(self):
        return int(self.settings.value("day_start_hour", 0))
    
    def set_day_start_hour(self, hour: int):
        self.settings.setValue("day_start_hour", hour)

    def get_last_position(self, file_path):

        """Returns the saved timestamp for a specific file."""
        val = self.settings.value(f"pos_{file_path}")
        if val is None:
            return 0.0
        try:
            return float(val)
        except (TypeError, ValueError):
            return 0.0


    def set_last_position(self, file_path, pos):
        """Saves the current timestamp for a specific file."""
        self.settings.setValue(f"pos_{file_path}", pos)

    def get_last_book(self):
        return self.settings.value("last_book", "")

    def set_last_book(self, file_path):
        self.settings.setValue("last_book", file_path)

    def sync(self):
        self.settings.sync()

    def get_sleep_duration(self):
        """Returns the last set sleep duration in minutes."""
        return self._safe_int("sleep_duration", 30) # Default to 30 minutes

    def set_sleep_duration(self, minutes):
        self.settings.setValue("sleep_duration", minutes)

    def get_sleep_mode(self):
        """Returns the last set sleep mode ('timed', 'end_of_chapter', 'end_of_book')."""
        return self.settings.value("sleep_mode", "timed")

    def set_sleep_mode(self, mode):
        self.settings.setValue("sleep_mode", mode)

    def get_sleep_fade_duration(self):
        return self._safe_int("sleep_fade_duration", 0)

    def set_sleep_fade_duration(self, seconds):
        self.settings.setValue("sleep_fade_duration", seconds)

    def get_theme_rotation_interval(self):
        return self._safe_int("theme_rotation_interval", 0) # 0 means Off

    def set_theme_rotation_interval(self, minutes):
        self.settings.setValue("theme_rotation_interval", minutes)

    def get_naming_pattern(self):
        return self.settings.value("naming_pattern", "Author - Title")

    def set_naming_pattern(self, pattern):
        self.settings.setValue("naming_pattern", pattern)

    def get_show_remaining_time(self):
        return self.settings.value("show_remaining_time", "true") == "true"

    def set_show_remaining_time(self, enabled):
        self.settings.setValue("show_remaining_time", str(enabled).lower())

    def get_scroll_mode(self):
        return self.settings.value("scroll_mode", "Slow")

    def set_scroll_mode(self, mode):
        self.settings.setValue("scroll_mode", mode)

    def get_hover_fade_mode(self):
        return self.settings.value("hover_fade_mode", "Slow")

    def set_hover_fade_mode(self, mode: str):
        self.settings.setValue("hover_fade_mode", mode)

    def get_chapter_hints_enabled(self):
        return self.settings.value("chapter_hints_enabled", "true") == "true"

    def set_chapter_hints_enabled(self, enabled):
        self.settings.setValue("chapter_hints_enabled", str(enabled).lower())

    def get_chapter_notches_enabled(self):
        return self.settings.value("chapter_notches_enabled", "false") == "true"

    def set_chapter_notches_enabled(self, enabled):
        self.settings.setValue("chapter_notches_enabled", str(enabled).lower())

    def get_chapter_notch_animation_enabled(self):
        return self.settings.value("chapter_notch_animation_enabled", "true") == "true"

    def set_chapter_notch_animation_enabled(self, enabled):
        self.settings.setValue("chapter_notch_animation_enabled", str(enabled).lower())

    def get_undo_duration(self):
        return self._safe_int("undo_duration", 3)

    def set_undo_duration(self, seconds):
        self.settings.setValue("undo_duration", seconds)

    def get_library_sort_key(self):
        return self.settings.value("library_sort_key", "Title")

    def set_library_sort_key(self, key):
        self.settings.setValue("library_sort_key", key)

    def get_library_sort_ascending(self):
        return self.settings.value("library_sort_ascending", "true") == "true"

    def set_library_sort_ascending(self, val):
        self.settings.setValue("library_sort_ascending", str(val).lower())

    def get_library_view_mode(self):
        return self.settings.value("library_view_mode", "3 per row")

    def set_library_view_mode(self, mode):
        self.settings.setValue("library_view_mode", mode)

    def get_voice_boost_enabled(self):
        return self.settings.value("voice_boost_enabled", "false") == "true"

    def set_voice_boost_enabled(self, enabled):
        self.settings.setValue("voice_boost_enabled", str(enabled).lower())

    def get_norm_enabled(self):
        return self.settings.value("norm_enabled", "false") == "true"

    def set_norm_enabled(self, enabled):
        self.settings.setValue("norm_enabled", str(enabled).lower())

    def get_mono_enabled(self):
        return self.settings.value("mono_enabled", "false") == "true"

    def set_mono_enabled(self, enabled):
        self.settings.setValue("mono_enabled", str(enabled).lower())

    def get_channels_swapped(self):
        return self.settings.value("channels_swapped", "false") == "true"

    def set_channels_swapped(self, enabled):
        self.settings.setValue("channels_swapped", str(enabled).lower())

    def get_balance(self):
        return self._safe_float("balance", 0.0)

    def set_balance(self, value):
        self.settings.setValue("balance", float(value))

    def get_chapter_digit_mode(self):
        return self.settings.value("chapter_digit_mode", "by_name")

    def set_chapter_digit_mode(self, mode):
        self.settings.setValue("chapter_digit_mode", mode)

    def get_chapter_digit_autoplay(self):
        return self.settings.value("chapter_digit_autoplay", "true") == "true"

    def set_chapter_digit_autoplay(self, enabled):
        self.settings.setValue("chapter_digit_autoplay", str(enabled).lower())

    def get_cover_art_theme_mode(self) -> str:
        """Returns 'off', 'with_pool', or 'exclusive'."""
        return self.settings.value("cover_art_theme_mode", "off")

    def set_cover_art_theme_mode(self, mode: str):
        self.settings.setValue("cover_art_theme_mode", mode)
