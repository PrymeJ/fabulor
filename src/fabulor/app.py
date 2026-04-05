from PySide6.QtWidgets import (
    QWidget, QLabel, QPushButton, QHBoxLayout,
    QVBoxLayout, QSizePolicy, QApplication
)
from PySide6.QtCore import Qt, QTimer, QPoint
from PySide6.QtGui import QPixmap, QGuiApplication

from .player import Player
from .config import Config
from .themes import get_stylesheet
from .ui.controls import ClickSlider
from .ui.chapter_list import ChapterList


class TitleBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(32)
        self._drag_pos = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 4, 0)
        layout.setSpacing(0)

        self.title_label = QLabel("Fabulor")
        layout.addWidget(self.title_label)
        layout.addStretch()

        for symbol, slot in [("─", self._minimize), ("□", self._maximize), ("✕", self._close)]:
            btn = QPushButton(symbol)
            btn.setFixedSize(32, 32)
            btn.clicked.connect(slot)
            layout.addWidget(btn)

    def _minimize(self): self.window().showMinimized()
    def _maximize(self):
        w = self.window()
        w.showNormal() if w.isMaximized() else w.showMaximized()
    def _close(self): self.window().close()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.window().windowHandle().startSystemMove()




class MainWindow(QWidget):  # QWidget, not QMainWindow
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint)

        self.current_cover_pixmap = QPixmap()
        self.is_slider_dragging = False
        self.config = Config()
        self.player = Player()

        self._setup_ui()

        self.ui_timer = QTimer()
        self.ui_timer.timeout.connect(self._update_ui_sync)
        self.player.chapter_changed.connect(self._update_chapter_label_from_index)

        sample_file = "/home/pryme/test.m4b"
        self.player.load_book(sample_file)
        self.chapter_list_widget.set_player(self.player)

        self._load_cover_art(sample_file)
        self.ui_timer.start(200)
        QTimer.singleShot(1000, lambda: self.chapter_list_widget.populate(self.player.duration or 0))

    def _setup_ui(self):
        self.setMinimumWidth(300)
        self.resize(300, 600)

        self.setObjectName("mainwindow")
        self.setStyleSheet(get_stylesheet(self.config.get_theme()))

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Custom title bar
        self.title_bar = TitleBar(self)
        root_layout.addWidget(self.title_bar)

        # Progress slider
        self.progress_slider = ClickSlider(Qt.Horizontal)
        self.progress_slider.setRange(0, 1000)
        self.progress_slider.setFixedHeight(24)
        self.progress_slider.sliderPressed.connect(self._on_slider_pressed)
        self.progress_slider.sliderReleased.connect(self._on_slider_released)
        root_layout.addWidget(self.progress_slider)

        self.progress_percentage_label = QLabel(self.progress_slider)
        self.progress_percentage_label.setObjectName("percentage_label")
        self.progress_percentage_label.setAlignment(Qt.AlignCenter)
        self.progress_percentage_label.setAttribute(Qt.WA_TransparentForMouseEvents)

        # Content
        content_container = QWidget()
        self.content_layout = QVBoxLayout(content_container)
        self.content_layout.setContentsMargins(10, 10, 10, 10)
        self.content_layout.setSpacing(10)
        root_layout.addWidget(content_container)

        self.cover_art_label = QLabel()
        self.cover_art_label.setAlignment(Qt.AlignCenter)
        self.cover_art_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.cover_art_label.setMinimumSize(280, 280)
        self.cover_art_label.mousePressEvent = lambda e: (self.windowHandle().startSystemMove() if e.button() == Qt.LeftButton else None)
        self.content_layout.addWidget(self.cover_art_label)

        self.metadata_label = QLabel("Author - Title")
        self.metadata_label.setAlignment(Qt.AlignCenter)
        self.metadata_label.mousePressEvent = lambda e: (self.windowHandle().startSystemMove() if e.button() == Qt.LeftButton else None)
        self.content_layout.addWidget(self.metadata_label)

        self.time_label = QLabel("00:00:00 / 00:00:00")
        self.time_label.setAlignment(Qt.AlignCenter)
        font = self.time_label.font()
        font.setPointSize(9)
        self.time_label.setFont(font)
        self.content_layout.addWidget(self.time_label)

        controls_layout = QHBoxLayout()
        self.prev_button = QPushButton("|<<")
        self.rewind_button = QPushButton("<")
        self.play_pause_button = QPushButton("Play")
        self.forward_button = QPushButton(">")
        self.next_button = QPushButton(">>|")
        for btn in [self.prev_button, self.rewind_button, self.play_pause_button,
                    self.forward_button, self.next_button]:
            controls_layout.addWidget(btn)
        self.content_layout.addLayout(controls_layout)

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
        if not self.player:
            return

        if self.current_chapter_label.text().strip() == "" and self.player.chapter_list:
             self.chapter_list_widget.populate(self.player.duration or 0)

        if not self.is_slider_dragging:
            pos = self.player.time_pos or 0
            dur = self.player.duration or 0
            if dur > 0:
                percent = (pos / dur) * 100
                self.progress_slider.setValue(int((pos / dur) * 1000))
                self.time_label.setText(f"{self._format_time(pos)} / {self._format_time(dur)}")
                self.progress_percentage_label.setText(f"{percent:.1f}%")

            curr_chap = self.player.chapter or 0
            chap_list = self.player.chapter_list or []
            if chap_list and curr_chap < len(chap_list):
                start = chap_list[curr_chap].get('time', 0)
                # End is the start of next chapter, or total duration if last
                end = chap_list[curr_chap+1].get('time', dur) if curr_chap + 1 < len(chap_list) else dur
                
                c_elapsed = max(0, pos - start)
                self.chap_elapsed_label.setText(self._format_time(c_elapsed))
                self.chap_duration_label.setText(self._format_time(end - start))

        is_eof = self.player.eof_reached
        
        if is_eof:
            self.play_pause_button.setText("Restart")
        else:
            self.play_pause_button.setText("Play" if self.player.pause else "Pause")

    def _format_time(self, seconds):
        """Converts seconds to HH:MM:SS format."""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        return f"{h:02}:{m:02}:{s:02}"

    def _on_slider_pressed(self):
        self.is_slider_dragging = True

    def _on_slider_released(self):
        if self.player and self.player.duration:
            new_pos = (self.progress_slider.value() / 1000) * self.player.duration
            self.player.time_pos = new_pos
        self.is_slider_dragging = False

    def _on_volume_changed(self, value):
        if self.player:
            self.player.volume = value

    def _on_speed_clicked(self):
        """Cycles through speeds: 1.0, 2.0, 3.0, 4.0."""
        if not self.player:
            return
        speeds = [1.0, 2.0, 3.0, 4.0]
        current = self.player.speed or 1.0
        next_speed = next((s for s in speeds if s > current + 0.01), speeds[0])
        self.player.speed = next_speed
        self.speed_button.setText(f"{next_speed:.2f}x")

    def _update_chapter_label_from_index(self, index):
        """Updates the label based on the current chapter index."""
        if not self.player:
            return
        
        # If the list is empty, trigger population now that we know we have data
        if not self.chapter_list_widget.count():
            self.chapter_list_widget.populate(self.player.duration or 0)

        chaps = self.player.chapter_list or []
        # Ensure index is non-negative to avoid Python's negative indexing (which picks the last chapter)
        if 0 <= index < len(chaps):
            title = chaps[index].get('title') or f"Chapter {index + 1}"
            self.current_chapter_label.setText(title)
            # Also sync the list selection visually
            self.chapter_list_widget.setCurrentRow(index)

    def _load_cover_art(self, file_path):
        """Extracts and displays cover art from the file tags."""
        pixmap = self.player.extract_cover(file_path)

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
        if not self.player:
            return
        if self.play_pause_button.text() == "Restart":
            self.player.time_pos = 0
            self.player.pause = False
            return
        self.player.pause = not self.player.pause

    def handle_rewind(self):
        if self.player:
            skip = self.config.get_skip_duration()
            self.player.time_pos = max(0, (self.player.time_pos or 0) - skip)
    def handle_forward(self):
        if self.player:
            skip = self.config.get_skip_duration()
            self.player.time_pos = min(self.player.duration or 0, (self.player.time_pos or 0) + skip)
    def handle_prev(self):
        if self.player: self.player.previous_chapter()
    def handle_next(self):
        if self.player: self.player.next_chapter()

    def closeEvent(self, event):
        if self.player: self.player.terminate()
        event.accept()
