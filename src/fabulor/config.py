from PySide6.QtCore import QSettings

class Config:
    """Handles persistent application configuration and user preferences."""
    def __init__(self):
        self.settings = QSettings("Fabulor", "Fabulor")

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

    def get_day_start_hour(self):
        return int(self.settings.value("day_start_hour", 0))

    def get_last_position(self, file_path):
        """Returns the saved timestamp for a specific file."""
        return float(self.settings.value(f"pos_{file_path}", 0))

    def set_last_position(self, file_path, pos):
        """Saves the current timestamp for a specific file."""
        self.settings.setValue(f"pos_{file_path}", pos)

    def sync(self):
        self.settings.sync()