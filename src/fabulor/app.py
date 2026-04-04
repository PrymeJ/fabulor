import sys
from PySide6.QtWidgets import QApplication, QMainWindow, QLabel, QPushButton, QVBoxLayout, QWidget, QFileDialog
from PySide6.QtCore import Qt
try:
    from mpv import MPV
except OSError as e:
    if "Cannot find libmpv" in str(e):
        raise SystemExit(
            "❌ libmpv not found.\n\n"
            "Install it with:\n"
            "  • openSUSE: sudo zypper install libmpv\n"
            "  • Ubuntu: sudo apt install libmpv\n"
            "  • macOS: brew install mpv\n"
            "  • Windows: choco install mpv\n"
            "Then try again."
        )
    raise

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self._setup_ui()
        self.mpv_player = None

    def _setup_ui(self):
        """Initialize the user interface components."""
        self.setWindowTitle("Fabulor")
        self.setGeometry(100, 100, 400, 300)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.layout = QVBoxLayout(central_widget)

        self.cover_art_label = QLabel("Cover Art Placeholder")
        self.cover_art_label.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(self.cover_art_label)

        self.title_label = QLabel("Title")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(self.title_label)

        self.author_label = QLabel("Author")
        self.author_label.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(self.author_label)

        self.play_pause_button = QPushButton("Play")
        self.play_pause_button.clicked.connect(self.toggle_play_pause)
        self.layout.addWidget(self.play_pause_button)

    def toggle_play_pause(self):
        if self.mpv_player is None:
            # Initialize player on first interaction
            sample_file = "/test.m4b" 
            self.mpv_player = MPV(ytdl=False) # ytdl=False speeds up local file loading
            self.mpv_player.play(sample_file)
            self.play_pause_button.setText("Pause")
            return

        # Toggle the pause property
        self.mpv_player.pause = not self.mpv_player.pause
        self.play_pause_button.setText("Play" if self.mpv_player.pause else "Pause")

    def closeEvent(self, event):
        """Clean up resources when the window is closed."""
        if self.mpv_player:
            self.mpv_player.terminate()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
