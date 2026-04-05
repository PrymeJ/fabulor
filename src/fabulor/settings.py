from PySide6.QtCore import QSettings

class Settings:
    """Handles persistent application configuration using QSettings."""
    def __init__(self):
        self.data = QSettings("Fabulor", "Fabulor")

    def get(self, key, default=None):
        return self.data.value(key, default)

    def set(self, key, value):
        self.data.setValue(key, value)

    def sync(self):
        self.data.sync()