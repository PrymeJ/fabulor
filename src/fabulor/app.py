import locale
import sys
import os
os.environ["MPV_HOME"] = ""
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QLabel, QPushButton, QHBoxLayout,
    QVBoxLayout, QWidget, QFileDialog, QListWidget, QListWidgetItem
)
from PySide6.QtCore import Qt, QTimer, Signal
try:
    from mpv import MPV
except OSError as e:
    msg = str(e)
    if "libmpv" in msg or "libcaca" in msg or "libtinfo" in msg or "_nc_curscr" in msg:
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

class ChapterList(QListWidget):
    """Widget to display and navigate audiobook chapters."""
    chapter_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.player = None
        self.itemClicked.connect(self._on_item_clicked)

    def set_player(self, player):
        """Link the mpv player instance to this widget."""
        self.player = player

    def populate(self):
        """Fetch chapters from the player and update the UI."""
        if not self.player:
            return
        self.clear()
        chapters = self.player.chapter_list or []
        for i, chap in enumerate(chapters):
            title = chap.get('title') or f"Chapter {i+1}"
            item = QListWidgetItem(title)
            item.setData(Qt.UserRole, i)
            self.addItem(item)

        # Update the UI with the current chapter name if available
        if chapters:
            # On initial population, always default to the first chapter for the label
            initial_title = chapters[0].get('title') or "Chapter 1"
            self.chapter_changed.emit(initial_title)

    def _on_item_clicked(self, item):
        """Seek to the selected chapter."""
        if self.player:
            self.player.chapter = item.data(Qt.UserRole)
            self.chapter_changed.emit(item.text())

class MainWindow(QMainWindow):
    # Signal to bridge mpv observer threads to the Qt UI thread
    chapter_index_changed = Signal(int)

    def __init__(self):
        super().__init__()

        self._setup_ui()
        
        # Timer to keep UI elements (like buttons) in sync with mpv state
        self.ui_timer = QTimer()
        self.ui_timer.timeout.connect(self._update_ui_sync)
        self.chapter_index_changed.connect(self._update_chapter_label_from_index)

        self.mpv_player = None
        self.initialize_player()

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

        self.metadata_label = QLabel("Author - Title")
        self.metadata_label.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(self.metadata_label)

        # Transport Controls
        controls_layout = QHBoxLayout()
        self.prev_button = QPushButton("Prev")
        self.play_pause_button = QPushButton("Play")
        self.next_button = QPushButton("Next")
        
        controls_layout.addWidget(self.prev_button)
        controls_layout.addWidget(self.play_pause_button)
        controls_layout.addWidget(self.next_button)
        self.layout.addLayout(controls_layout)

        self.play_pause_button.clicked.connect(self.toggle_play_pause)
        self.prev_button.clicked.connect(self.handle_prev)
        self.next_button.clicked.connect(self.handle_next)

        self.current_chapter_label = QLabel(" ")
        self.current_chapter_label.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(self.current_chapter_label)

        self.chapter_list_widget = ChapterList()
        self.layout.addWidget(self.chapter_list_widget)
        self.chapter_list_widget.chapter_changed.connect(self.current_chapter_label.setText)

    def _update_ui_sync(self):
        """Update UI button text and labels based on the current player state."""
        if not self.mpv_player:
            return

        # Handle initial chapter name discovery if ChapterList is now populated
        if self.current_chapter_label.text().strip() == "" and getattr(self.mpv_player, 'chapter_list', None):
             self.chapter_list_widget.populate()

        is_eof = getattr(self.mpv_player, 'eof_reached', False)
        
        if is_eof:
            if self.play_pause_button.text() == "Pause":
                self.play_pause_button.setText("Play")
        else:
            self.play_pause_button.setText("Play" if self.mpv_player.pause else "Pause")

    def _on_mpv_chapter_change(self, name, value):
        """Callback from mpv thread when chapter changes."""
        if value is not None:
            self.chapter_index_changed.emit(int(value))

    def _update_chapter_label_from_index(self, index):
        """Updates the label based on the current chapter index."""
        if not self.mpv_player:
            return
        
        # If the list is empty, trigger population now that we know we have data
        if not self.chapter_list_widget.count():
            self.chapter_list_widget.populate()

        chaps = self.mpv_player.chapter_list or []
        # Ensure index is non-negative to avoid Python's negative indexing (which picks the last chapter)
        if 0 <= index < len(chaps):
            title = chaps[index].get('title') or f"Chapter {index + 1}"
            self.current_chapter_label.setText(title)
            # Also sync the list selection visually
            self.chapter_list_widget.setCurrentRow(index)

    def initialize_player(self):
        """Set up the mpv instance and load the book metadata immediately."""
        locale.setlocale(locale.LC_NUMERIC, "C")
        sample_file = "/home/pryme/test.m4b"
        self.mpv_player = MPV(
            vo='null',
            ao='pulse',
            vid=False,
            ytdl=False,
            loglevel='debug',
            keep_open=True
        )
        
        self.mpv_player.pause = True
        self.mpv_player.play(sample_file)
        self.chapter_list_widget.set_player(self.mpv_player)
        self.mpv_player.observe_property('chapter', self._on_mpv_chapter_change)

        self.ui_timer.start(200)
        QTimer.singleShot(1000, self.chapter_list_widget.populate)

    def toggle_play_pause(self):
        if not self.mpv_player:
            return

        # Check for Restart logic at the end of the file
        is_eof = getattr(self.mpv_player, 'eof_reached', False)
        if is_eof or self.play_pause_button.text() == "Restart":
            if self.play_pause_button.text() == "Play":
                self.play_pause_button.setText("Restart")
            else:
                self.mpv_player.time_pos = 0
                self.mpv_player.pause = False 
                self.play_pause_button.setText("Pause")
            return

        # Toggle the pause property
        self.mpv_player.pause = not self.mpv_player.pause

    def handle_prev(self):
        """Logic for jumping to the start of a chapter or the previous chapter."""
        if not self.mpv_player:
            return

        curr_time = self.mpv_player.time_pos or 0
        if curr_time < 0.5:  # Very beginning of file
            return

        curr_chap = self.mpv_player.chapter or 0
        chap_list = self.mpv_player.chapter_list or []
        # Safely get chapter start time
        chap_start = chap_list[curr_chap].get('time', 0) if chap_list and curr_chap < len(chap_list) else 0

        # If within the first 2 seconds of the chapter, go to previous chapter
        if curr_time < chap_start + 2.0:
            if curr_chap > 0:
                self.mpv_player.chapter = curr_chap - 1
        else:
            # Chapter is underway (> 2s elapsed), go to start of chapter
            self.mpv_player.time_pos = chap_start

    def handle_next(self):
        """Logic for jumping to the next chapter or the end of the book."""
        if not self.mpv_player:
            return

        curr_chap = self.mpv_player.chapter or 0
        total_chaps = self.mpv_player.chapters or 0

        if curr_chap < total_chaps - 1:
            self.mpv_player.chapter = curr_chap + 1
        else:
            # Last chapter logic: seek to end of file
            duration = self.mpv_player.duration
            if duration:
                self.mpv_player.time_pos = duration

    def closeEvent(self, event):
        """Clean up resources when the window is closed."""
        if self.mpv_player:
            self.mpv_player.terminate()
        event.accept()

def run():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    run()
