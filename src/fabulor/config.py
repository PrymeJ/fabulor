from PySide6.QtCore import QSettings

class Config:
    """Handles persistent application configuration and user preferences."""
    def __init__(self):
        self.settings = QSettings("Fabulor", "Fabulor")

    def get_theme(self):
        return self.settings.value("theme", "default")

    def set_theme(self, name):
        self.settings.setValue("theme", name)

    def get_skip_duration(self):
        return int(self.settings.value("skip_duration", 10))

    def set_skip_duration(self, seconds):
        self.settings.setValue("skip_duration", seconds)

    def get_speed_increment(self):
        return float(self.settings.value("speed_increment", 0.1))

    def get_day_start_hour(self):
        return int(self.settings.value("day_start_hour", 0))

    def sync(self):
        self.settings.sync()