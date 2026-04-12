from PySide6.QtCore import QSettings

class Config:
    """Handles persistent application configuration and user preferences."""
    def __init__(self):
        self.settings = QSettings("Fabulor", "Fabulor") # Org, App

    def get_theme(self):
        return self.settings.value("theme", "default")

    def set_theme(self, name):
        self.settings.setValue("theme", name)

    def get_blur_enabled(self):
        return self.settings.value("blur_enabled", "false") == "true"

    def set_blur_enabled(self, enabled):
        self.settings.setValue("blur_enabled", str(enabled).lower())

    def get_theme_fade_duration(self):
        return int(self.settings.value("theme_fade_duration", 750))

    def set_theme_fade_duration(self, ms):
        self.settings.setValue("theme_fade_duration", ms)

    def get_volume(self):
        return int(self.settings.value("volume", 100))

    def set_volume(self, value):
        self.settings.setValue("volume", value)

    def get_skip_duration(self):
        return int(self.settings.value("skip_duration", 10))

    def set_skip_duration(self, seconds):
        self.settings.setValue("skip_duration", seconds)

    def get_speed_increment(self):
        return float(self.settings.value("speed_increment", 0.1))

    def set_speed_increment(self, value):
        self.settings.setValue("speed_increment", float(value))

    def get_default_speed(self):
        return float(self.settings.value("default_speed", 1.0))

    def set_default_speed(self, value):
        self.settings.setValue("default_speed", float(value))

    def get_book_speed(self, file_path):
        val = self.settings.value(f"speed_{file_path}")
        return float(val) if val is not None else None

    def set_book_speed(self, file_path, speed):
        self.settings.setValue(f"speed_{file_path}", speed)

    def get_day_start_hour(self):
        return int(self.settings.value("day_start_hour", 0))

    def get_last_position(self, file_path):
        val = self.settings.value(f"pos_{file_path}", 0)
        return float(val) if val is not None else 0.0

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
        return int(self.settings.value("sleep_duration", 30)) # Default to 30 minutes

    def set_sleep_duration(self, minutes):
        self.settings.setValue("sleep_duration", minutes)

    def get_sleep_mode(self):
        """Returns the last set sleep mode ('timed', 'end_of_chapter', 'end_of_book')."""
        return self.settings.value("sleep_mode", "timed")

    def set_sleep_mode(self, mode):
        self.settings.setValue("sleep_mode", mode)

    def get_sleep_fade_duration(self):
        return int(self.settings.value("sleep_fade_duration", 0))

    def set_sleep_fade_duration(self, seconds):
        self.settings.setValue("sleep_fade_duration", seconds)

    def get_theme_rotation_interval(self):
        return int(self.settings.value("theme_rotation_interval", 0)) # 0 means Off

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