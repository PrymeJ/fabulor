import locale
import sys
import os
os.environ["MPV_HOME"] = ""
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QLabel, QPushButton, QHBoxLayout, QSlider,
    QVBoxLayout, QWidget, QFileDialog, QListWidget, QListWidgetItem, QSizePolicy
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
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

try:
    import mutagen
except ImportError:
    mutagen = None

class ClickSlider(QSlider):
    """A slider that jumps to the position where it is clicked."""
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            val = self.minimum() + ((self.maximum() - self.minimum()) * event.position().x()) / self.width()
            self.setValue(int(val))
            self.sliderReleased.emit() # Trigger seek/update immediately
        super().mousePressEvent(event)

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

    def populate(self, total_duration=0):
        """Fetch chapters from the player and update the UI."""
        if not self.player:
            return
        self.clear()
        chapters = self.player.chapter_list or []
        for i, chap in enumerate(chapters):
            title = chap.get('title') or f"Chapter {i+1}"
            start = chap.get('time', 0)
            # Get duration by checking the start of the next chapter or the total book duration
            end = chapters[i+1].get('time', total_duration) if i+1 < len(chapters) else total_duration
            duration_str = self._format_seconds(end - start)

            item = QListWidgetItem(self)
            item.setData(Qt.UserRole, i)
            
            # Create a widget for the list item to allow right-aligned duration
            widget = QWidget()
            layout = QHBoxLayout(widget)
            layout.setContentsMargins(5, 2, 5, 2)
            
            name_label = QLabel(title)
            time_label = QLabel(duration_str)
            time_label.setStyleSheet("color: gray;") # subtle color for the duration
            
            layout.addWidget(name_label)
            layout.addStretch()
            layout.addWidget(time_label)
            
            item.setSizeHint(widget.sizeHint())
            self.addItem(item)
            self.setItemWidget(item, widget)

        # Update the UI with the current chapter name if available
        if chapters:
            # On initial population, always default to the first chapter for the label
            initial_title = chapters[0].get('title') or "Chapter 1"
            self.chapter_changed.emit(initial_title)

    def _format_seconds(self, seconds):
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        return f"{h:02}:{m:02}:{s:02}"

    def _on_item_clicked(self, item):
        """Seek to the selected chapter."""
        if self.player:
            idx = item.data(Qt.UserRole)
            self.player.chapter = idx
            # Find the title from the custom widget labels
            widget = self.itemWidget(item)
            if widget:
                title = widget.findChild(QLabel).text()
                self.chapter_changed.emit(title)

class MainWindow(QMainWindow):
    # Signal to bridge mpv observer threads to the Qt UI thread
    chapter_index_changed = Signal(int)

    def __init__(self):
        super().__init__()

        self._setup_ui()
        self.current_cover_pixmap = QPixmap()
        self.is_slider_dragging = False
        
        # Timer to keep UI elements (like buttons) in sync with mpv state
        self.ui_timer = QTimer()
        self.ui_timer.timeout.connect(self._update_ui_sync)
        self.chapter_index_changed.connect(self._update_chapter_label_from_index)

        self.mpv_player = None
        self.initialize_player()

    def _setup_ui(self):
        """Initialize the user interface components."""
        self.setWindowTitle("Fabulor")
        self.setGeometry(100, 100, 300, 600)
        self.setMinimumWidth(300)
        
        # Global Dark Theme with Brighter Button Accents
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1A002E;
            }
            QLabel {
                color: #F0F0F0;
            }
            QPushButton {
                background-color: #7B2CBF;
                color: white;
                border-radius: 4px;
                padding: 6px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #9D4EDD;
            }
            QPushButton:pressed {
                background-color: #5A189A;
            }
        """)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.layout = QVBoxLayout(central_widget)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        # Overall Progress Bar (Top, Flush)
        self.progress_slider = ClickSlider(Qt.Horizontal)
        self.progress_slider.setRange(0, 1000)
        self.progress_slider.setFixedHeight(24)
        self.progress_slider.sliderPressed.connect(self._on_slider_pressed)
        self.progress_slider.sliderReleased.connect(self._on_slider_released)
        self.progress_slider.setStyleSheet("""
            QSlider {
                background: #4B0082;
            }
            QSlider::groove:horizontal {
                border: none;
                background: #4B0082;
                height: 24px;
            }
            QSlider::sub-page:horizontal {
                background: #C8A2C8;
                height: 24px;
            }
            QSlider::handle:horizontal {
                background: #C8A2C8;
                width: 2px;
                margin: 0px;
            }
        """)
        self.layout.addWidget(self.progress_slider)

        # Percentage label inside the bar
        self.progress_percentage_label = QLabel(self.progress_slider)
        self.progress_percentage_label.setAlignment(Qt.AlignCenter)
        self.progress_percentage_label.setStyleSheet("color: rgba(255, 255, 255, 0.85); font-weight: bold; font-size: 16px; background: transparent;")
        self.progress_percentage_label.setAttribute(Qt.WA_TransparentForMouseEvents) # Don't block slider clicks

        # Content Container (Padded)
        content_container = QWidget()
        self.content_layout = QVBoxLayout(content_container)
        self.content_layout.setContentsMargins(10, 10, 10, 10)
        self.content_layout.setSpacing(10)
        self.layout.addWidget(content_container)

        self.cover_art_label = QLabel()
        self.cover_art_label.setAlignment(Qt.AlignCenter)
        self.cover_art_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.cover_art_label.setMinimumSize(280, 280)
        self.content_layout.addWidget(self.cover_art_label)

        self.metadata_label = QLabel("Author - Title")
        self.metadata_label.setAlignment(Qt.AlignCenter)
        self.content_layout.addWidget(self.metadata_label)
        
        # Total Book Time Label
        self.time_label = QLabel("00:00:00 / 00:00:00")
        self.time_label.setAlignment(Qt.AlignCenter)
        font = self.time_label.font()
        font.setPointSize(9)
        self.time_label.setFont(font)
        self.content_layout.addWidget(self.time_label)

        # Transport Controls
        controls_layout = QHBoxLayout()
        self.prev_button = QPushButton("|<<")
        self.rewind_button = QPushButton("<")
        self.play_pause_button = QPushButton("Play")
        self.forward_button = QPushButton(">")
        self.next_button = QPushButton(">>|")
        
        controls_layout.addWidget(self.prev_button)
        controls_layout.addWidget(self.rewind_button)
        controls_layout.addWidget(self.play_pause_button)
        controls_layout.addWidget(self.forward_button)
        controls_layout.addWidget(self.next_button)
        self.content_layout.addLayout(controls_layout)

        # Secondary Controls (Volume & Speed)
        secondary_layout = QHBoxLayout()
        
        self.speed_button = QPushButton("1.00x")
        self.speed_button.setFixedWidth(60)
        
        self.volume_slider = ClickSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(100)
        self.volume_slider.setFixedWidth(100)
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        self.speed_button.clicked.connect(self._on_speed_clicked)

        secondary_layout.addWidget(QLabel("Vol:"))
        secondary_layout.addWidget(self.volume_slider)
        secondary_layout.addStretch()
        secondary_layout.addWidget(self.speed_button)
        
        self.content_layout.addLayout(secondary_layout)

        self.play_pause_button.clicked.connect(self.toggle_play_pause)
        self.prev_button.clicked.connect(self.handle_prev)
        self.rewind_button.clicked.connect(self.handle_rewind)
        self.forward_button.clicked.connect(self.handle_forward)
        self.next_button.clicked.connect(self.handle_next)

        # Chapter display with elapsed/duration
        chapter_container = QHBoxLayout()
        self.chap_elapsed_label = QLabel("00:00:00")
        self.chap_duration_label = QLabel("00:00:00")
        self.current_chapter_label = QLabel(" ")
        self.current_chapter_label.setAlignment(Qt.AlignCenter)
        
        chapter_container.addWidget(self.chap_elapsed_label)
        chapter_container.addWidget(self.current_chapter_label, 1)
        chapter_container.addWidget(self.chap_duration_label)
        self.content_layout.addLayout(chapter_container)

        self.chapter_list_widget = ChapterList()
        self.content_layout.addWidget(self.chapter_list_widget)
        self.chapter_list_widget.chapter_changed.connect(self.current_chapter_label.setText)

    def _update_ui_sync(self):
        """Update UI button text and labels based on the current player state."""
        if not self.mpv_player:
            return

        # Handle initial chapter name discovery if ChapterList is now populated
        if self.current_chapter_label.text().strip() == "" and getattr(self.mpv_player, 'chapter_list', None):
             self.chapter_list_widget.populate(self.mpv_player.duration or 0)

        # Sync Progress Slider and Time Label
        if not self.is_slider_dragging:
            pos = self.mpv_player.time_pos or 0
            dur = self.mpv_player.duration or 0
            if dur > 0:
                percent = (pos / dur) * 100
                self.progress_slider.setValue(int((pos / dur) * 1000))
                self.time_label.setText(f"{self._format_time(pos)} / {self._format_time(dur)}")
                self.progress_percentage_label.setText(f"{percent:.1f}%")

            # Sync Chapter Timers
            curr_chap = self.mpv_player.chapter or 0
            chap_list = self.mpv_player.chapter_list or []
            if chap_list and curr_chap < len(chap_list):
                start = chap_list[curr_chap].get('time', 0)
                # End is the start of next chapter, or total duration if last
                end = chap_list[curr_chap+1].get('time', dur) if curr_chap + 1 < len(chap_list) else dur
                
                c_elapsed = max(0, pos - start)
                self.chap_elapsed_label.setText(self._format_time(c_elapsed))
                self.chap_duration_label.setText(self._format_time(end - start))

        is_eof = getattr(self.mpv_player, 'eof_reached', False)
        
        if is_eof:
            if self.play_pause_button.text() == "Pause":
                self.play_pause_button.setText("Play")
        else:
            self.play_pause_button.setText("Play" if self.mpv_player.pause else "Pause")

    def _format_time(self, seconds):
        """Converts seconds to HH:MM:SS format."""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        return f"{h:02}:{m:02}:{s:02}"

    def _on_slider_pressed(self):
        self.is_slider_dragging = True

    def _on_slider_released(self):
        if self.mpv_player and self.mpv_player.duration:
            new_pos = (self.progress_slider.value() / 1000) * self.mpv_player.duration
            self.mpv_player.time_pos = new_pos
        self.is_slider_dragging = False

    def _on_volume_changed(self, value):
        if self.mpv_player:
            self.mpv_player.volume = value

    def _on_speed_clicked(self):
        """Cycles through speeds: 1.0, 2.0, 3.0, 4.0."""
        if not self.mpv_player:
            return
        speeds = [1.0, 2.0, 3.0, 4.0]
        current = getattr(self.mpv_player, 'speed', 1.0)
        next_speed = next((s for s in speeds if s > current + 0.01), speeds[0])
        self.mpv_player.speed = next_speed
        self.speed_button.setText(f"{next_speed:.2f}x")

    def _on_mpv_chapter_change(self, name, value):
        """Callback from mpv thread when chapter changes."""
        if value is not None:
            self.chapter_index_changed.emit(int(value))

    def _update_chapter_label_from_index(self, index):
        """Updates the label based on the current chapter index."""
        if not self.mpv_player:
            return
        
        # If the list is empty, trigger population now that we know we have data
        if not self.chapter_list_widget.count() and self.mpv_player:
            self.chapter_list_widget.populate(self.mpv_player.duration or 0)

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
        
        self._load_cover_art(sample_file)

        self.ui_timer.start(200)
        QTimer.singleShot(1000, lambda: self.chapter_list_widget.populate(self.mpv_player.duration or 0))

    def _load_cover_art(self, file_path):
        """Extracts and displays cover art from the file tags."""
        if not mutagen:
            return

        pixmap = QPixmap()
        try:
            audio = mutagen.File(file_path)
            if audio and audio.tags:
                # Handle M4B (MP4 container)
                if 'covr' in audio.tags:
                    data = audio.tags['covr'][0]
                    pixmap.loadFromData(data)
                # Handle MP3 (ID3 tags)
                elif 'APIC:' in audio.tags:
                    data = audio.tags['APIC:'].data
                    pixmap.loadFromData(data)
        except Exception as e:
            print(f"Could not extract cover art: {e}")

        if not pixmap.isNull():
            self.current_cover_pixmap = pixmap
            self.cover_art_label.show()
            self.metadata_label.hide()
            self._update_cover_art_scaling()
        else:
            self.current_cover_pixmap = QPixmap()
            self.cover_art_label.hide()
            self.metadata_label.show()

    def _update_cover_art_scaling(self):
        """Scales the current cover pixmap to FIT the available space."""
        if not self.current_cover_pixmap.isNull() and self.cover_art_label.isVisible():
            # Fit logic: Use label width but cap it to keep aspect ratio
            # all pixels visible = KeepAspectRatio
            target_w = self.cover_art_label.width()
            target_h = self.cover_art_label.height()
            
            scaled = self.current_cover_pixmap.scaled(
                target_w, target_h,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            self.cover_art_label.setPixmap(scaled)

    def showEvent(self, event):
        """Triggers scaling once the window is rendered to prevent hidden art on startup."""
        super().showEvent(event)
        # Ensure percentage label covers the slider immediately
        if hasattr(self, 'progress_percentage_label'):
            self.progress_percentage_label.resize(self.progress_slider.size())
        self._update_cover_art_scaling()

    def resizeEvent(self, event):
        """Handle window resize to update cover art scaling."""
        super().resizeEvent(event)
        self._update_cover_art_scaling()
        # Reposition percentage label
        if hasattr(self, 'progress_percentage_label'):
            self.progress_percentage_label.resize(self.progress_slider.size())

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

    def handle_rewind(self):
        """Rewind fixed 10 seconds."""
        if self.mpv_player:
            self.mpv_player.time_pos = max(0, (self.mpv_player.time_pos or 0) - 10)

    def handle_forward(self):
        """Forward fixed 10 seconds."""
        if self.mpv_player:
            self.mpv_player.time_pos = min(self.mpv_player.duration or 0, (self.mpv_player.time_pos or 0) + 10)

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
