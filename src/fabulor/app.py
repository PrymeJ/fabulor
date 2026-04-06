from PySide6.QtWidgets import (
    QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout, 
    QSizePolicy, QApplication, QComboBox, QListView
)
from PySide6.QtCore import Qt, QTimer, QPoint, QEvent, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QPixmap, QGuiApplication

from .player import Player
from .config import Config
from .themes import get_stylesheet, THEMES
from .ui.controls import ClickSlider
from .ui.chapter_list import ChapterList
from mpv import ShutdownError

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
            # This widget is part of the main window, so its parent window handles popups
            self.window()._hide_popups()
            self.window().windowHandle().startSystemMove()


class MainWindow(QWidget):  # QWidget, not QMainWindow
    def __init__(self, parent=None):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint)

        self.current_cover_pixmap = QPixmap()
        self.is_slider_dragging = False
        self.is_chapter_slider_dragging = False
        self.sidebar_expanded = False
        self.current_file = ""
        self.config = Config()
        self.player = Player()

        self._setup_ui()

        self.ui_timer = QTimer()
        self.ui_timer.timeout.connect(self._update_ui_sync)
        self.player.chapter_changed.connect(self._update_chapter_label_from_index)

        # Install event filter on the application to catch clicks outside popups
        QApplication.instance().installEventFilter(self)

        self.current_file = "/home/pryme/test.m4b"
        self.player.load_book(self.current_file)
        self.chapter_list_widget.set_player(self.player)

        self._load_cover_art(self.current_file)
        self.ui_timer.start(200)
        QTimer.singleShot(1000, lambda: self.chapter_list_widget.populate(self.player.duration or 0))
        QTimer.singleShot(500, self._restore_position)

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
        self.progress_slider.setObjectName("overall_progress")
        self.progress_slider.sliderPressed.connect(self._hide_popups)
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
        self.cover_art_label.mousePressEvent = self._on_drag_area_pressed
        self.content_layout.addWidget(self.cover_art_label)

        self.metadata_label = QLabel("Author - Title")
        self.metadata_label.setAlignment(Qt.AlignCenter)
        self.metadata_label.mousePressEvent = self._on_drag_area_pressed
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
        self.volume_slider.setObjectName("volume_slider")
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(self.config.get_volume())
        self.volume_slider.setFixedWidth(100)
        self.volume_slider.setFixedHeight(9)
        self.volume_slider.sliderPressed.connect(self._hide_popups)
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

        # Chapter Progress Bar (under secondary layout, over chapter labels)
        self.chapter_progress_slider = ClickSlider(Qt.Horizontal)
        self.chapter_progress_slider.setObjectName("chapter_progress")
        self.chapter_progress_slider.setRange(0, 1000)
        self.chapter_progress_slider.setFixedHeight(12)
        self.chapter_progress_slider.sliderPressed.connect(self._hide_popups)
        self.chapter_progress_slider.sliderPressed.connect(self._on_chap_slider_pressed)
        self.chapter_progress_slider.sliderReleased.connect(self._on_chap_slider_released)
        self.content_layout.addWidget(self.chapter_progress_slider)

        chapter_container = QHBoxLayout()
        self.chap_elapsed_label = QLabel("00:00:00")
        self.chap_duration_label = QLabel("00:00:00")
        
        # The "Trigger" for the dropdown
        self.current_chapter_label = QPushButton("Select Chapter")
        self.current_chapter_label.setObjectName("chapter_selector")
        self.current_chapter_label.clicked.connect(self._show_chapter_dropdown)

        chapter_container.addWidget(self.chap_elapsed_label)
        chapter_container.addWidget(self.current_chapter_label, 1)
        chapter_container.addWidget(self.chap_duration_label)
        self.content_layout.addLayout(chapter_container)

        self.chapter_list_widget = ChapterList(self)
        # The _update_chapter_title_text already handles setting the text with elision
        self.chapter_list_widget.chapter_changed.connect(self._update_chapter_title_text)

        # Initialize Sidebar (hidden off-screen to the left)
        self.sidebar = QWidget(self)
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(70)
        self.sidebar_layout = QVBoxLayout(self.sidebar)
        self.sidebar_layout.setContentsMargins(10, 10, 10, 10)
        
        self.settings_trigger_btn = QPushButton("Settings")
        self.settings_trigger_btn.setObjectName("sidebar_settings_btn")
        self.settings_trigger_btn.clicked.connect(self._open_settings_flow)
        self.sidebar_layout.addWidget(self.settings_trigger_btn)
        self.sidebar_layout.addStretch()
        
        # Start flush under progress bar: title (32) + progress (24) = 56
        self.sidebar.move(-50, 56)
        self.sidebar.show()
        self.sidebar_animation = QPropertyAnimation(self.sidebar, b"pos")
        self.sidebar_animation.setDuration(300)
        self.sidebar_animation.setEasingCurve(QEasingCurve.OutCubic)

        # Initialize Settings Panel (90% width)
        self.settings_panel = QWidget(self)
        self.settings_panel.setObjectName("settings_panel")
        self.settings_panel_layout = QVBoxLayout(self.settings_panel)
        self.settings_panel_layout.setContentsMargins(10, 10, 10, 10)
        
        # Appearance Section
        appearance_header = QLabel("Appearance")
        appearance_header.setObjectName("settings_header")
        self.settings_panel_layout.addWidget(appearance_header)

        theme_row = QHBoxLayout()
        theme_row.addWidget(QLabel("Theme:"))
        self.theme_dropdown = QComboBox()
        self.theme_dropdown.setView(QListView()) # Required for QSS popup background styling
        self.theme_dropdown.setMaxVisibleItems(4) # Limit visible items to 4
        self.theme_dropdown.view().setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.theme_dropdown.addItems(list(THEMES.keys()))
        self.theme_dropdown.setCurrentText(self.config.get_theme())
        self.theme_dropdown.currentTextChanged.connect(self._on_theme_changed)
        theme_row.addWidget(self.theme_dropdown)
        self.settings_panel_layout.addLayout(theme_row)

        # Controls Section
        controls_header = QLabel("Controls")
        controls_header.setObjectName("settings_header")
        self.settings_panel_layout.addWidget(controls_header)
        self.settings_panel_layout.addWidget(QLabel("Skip Interval: 10s (stub)"))

        self.settings_panel_layout.addStretch()
        self.settings_panel.hide()
        self.settings_panel_animation = QPropertyAnimation(self.settings_panel, b"pos")
        self.settings_panel_animation.setDuration(300)
        self.settings_panel_animation.setEasingCurve(QEasingCurve.OutCubic)

    def _update_chapter_title_text(self, text):
        """Update the button text with elision."""
        metrics = self.current_chapter_label.fontMetrics()
        # 160 is a safe width for the central area in a 300px window
        elided = metrics.elidedText(text, Qt.ElideRight, 160)
        self.current_chapter_label.setText(elided)

    def _restore_position(self):
        """Seeks to the saved position from config."""
        last_pos = self.config.get_last_position(self.current_file)
        if last_pos > 0:
            self.player.time_pos = last_pos
        self.player.volume = self.volume_slider.value()

    def _on_theme_changed(self, theme_name):
        """Update the configuration and apply the new stylesheet."""
        self.config.set_theme(theme_name)
        self.setStyleSheet(get_stylesheet(theme_name))

    def _hide_popups(self):
        """Closes any open floating menus."""
        if hasattr(self, 'chapter_list_widget') and self.chapter_list_widget.isVisible():
            self.chapter_list_widget.hide()
        if self.sidebar_expanded:
            self._toggle_sidebar()
        if self.settings_panel.isVisible():
            self._close_settings_flow()

    def _open_settings_flow(self):
        """Hides sidebar first, then shows settings panel."""
        if self.sidebar_expanded:
            self.sidebar_animation.finished.connect(self._start_settings_entry)
            self._toggle_sidebar()
        else:
            self._start_settings_entry()

    def _start_settings_entry(self):
        """Starts the settings panel slide-in animation."""
        try:
            self.sidebar_animation.finished.disconnect(self._start_settings_entry)
        except:
            pass
        
        panel_w = int(self.width() * 0.9)
        sidebar_y = 56
        self.settings_panel.setFixedWidth(panel_w)
        self.settings_panel.move(-panel_w, sidebar_y)
        self.settings_panel.show()
        self.settings_panel.raise_()
        
        self.settings_panel_animation.setStartValue(QPoint(-panel_w, sidebar_y))
        self.settings_panel_animation.setEndValue(QPoint(0, sidebar_y))
        self.settings_panel_animation.start()

    def _close_settings_flow(self):
        """Slides the settings panel back out."""
        if self.settings_panel_animation.state() == QPropertyAnimation.Running:
            return
        panel_w = self.settings_panel.width()
        sidebar_y = 56
        self.settings_panel_animation.setStartValue(QPoint(0, sidebar_y))
        self.settings_panel_animation.setEndValue(QPoint(-panel_w, sidebar_y))
        self.settings_panel_animation.finished.connect(self._on_settings_hidden)
        self.settings_panel_animation.start()

    def _on_settings_hidden(self):
        try:
            self.settings_panel_animation.finished.disconnect(self._on_settings_hidden)
        except:
            pass
        self.settings_panel.hide()

    def _toggle_sidebar(self):
        """Slides the sidebar in or out."""
        if self.sidebar_animation.state() == QPropertyAnimation.Running:
            return
            
        # Use explicit heights to avoid layout race conditions
        sidebar_y = 32 + 24 
        width = self.sidebar.width()

        if not self.sidebar_expanded:
            self.sidebar.raise_()
            self.sidebar_animation.setStartValue(QPoint(-width, sidebar_y))
            self.sidebar_animation.setEndValue(QPoint(0, sidebar_y))
            self.sidebar_expanded = True
        else:
            self.sidebar_animation.setStartValue(QPoint(0, sidebar_y))
            self.sidebar_animation.setEndValue(QPoint(-width, sidebar_y))
            self.sidebar_expanded = False
            
        self.sidebar_animation.start()

    def _show_chapter_dropdown(self):
        """Positions and shows the floating chapter list."""
        if self.chapter_list_widget.isVisible():
            self.chapter_list_widget.hide()
            return

        if not self.chapter_list_widget.count():
            self.chapter_list_widget.populate(self.player.duration or 0) # Populate if empty
            
        # Recalculate height and position the menu centered above the label
        # Ensure height is correct before positioning, re-populate if needed
        if self.chapter_list_widget.count() == 0: # Re-check in case populate failed
             self.chapter_list_widget.populate(self.player.duration or 0)
        label_pos = self.current_chapter_label.mapToGlobal(QPoint(0, 0))
        x = label_pos.x() + (self.current_chapter_label.width() // 2) - (self.chapter_list_widget.width() // 2)
        y = label_pos.y() - self.chapter_list_widget.height() - 5
        
        self.chapter_list_widget.move(x, y)
        self.chapter_list_widget.show()
        self.chapter_list_widget.setFocus()

    def _update_ui_sync(self):
        try:
            pos = self.player.time_pos or 0
            dur = self.player.duration or 0
        except ShutdownError:
            return

        if self.current_chapter_label.text() == "Select Chapter" and self.player.chapter_list:
             self.chapter_list_widget.populate(dur)
             self._update_chapter_label_from_index(self.player.chapter or 0)

        if dur > 0:
            if not self.is_slider_dragging:
                percent = (pos / dur) * 100
                self.progress_slider.setValue(int((pos / dur) * 1000))
                self.time_label.setText(f"{self._format_time(pos)} / {self._format_time(dur)}")
                self.progress_percentage_label.setText(f"{percent:.1f}%")

        curr_chap = self.player.chapter or 0
        chap_list = self.player.chapter_list or []
        if chap_list and curr_chap < len(chap_list):
            start = chap_list[curr_chap].get('time', 0)
            end = chap_list[curr_chap+1].get('time', dur) if curr_chap + 1 < len(chap_list) else dur
            chap_dur = end - start
            
            if not self.is_chapter_slider_dragging:
                c_elapsed = max(0, pos - start)
                self.chap_elapsed_label.setText(self._format_time(c_elapsed))
                self.chap_duration_label.setText(self._format_time(end - start))
                if chap_dur > 0:
                    self.chapter_progress_slider.setValue(int((c_elapsed / chap_dur) * 1000))

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

    def _on_chap_slider_pressed(self):
        self.is_chapter_slider_dragging = True

    def _on_chap_slider_released(self):
        if self.player and self.player.duration:
            curr_chap = self.player.chapter or 0
            chap_list = self.player.chapter_list or []
            if chap_list and curr_chap < len(chap_list):
                dur = self.player.duration
                start = chap_list[curr_chap].get('time', 0)
                end = chap_list[curr_chap+1].get('time', dur) if curr_chap + 1 < len(chap_list) else dur
                chap_dur = end - start
                if chap_dur > 0:
                    new_chap_pos = (self.chapter_progress_slider.value() / 1000) * chap_dur
                    self.player.time_pos = start + new_chap_pos
        self.is_chapter_slider_dragging = False

    def _on_volume_changed(self, value):
        self._hide_popups()
        if self.player:
            self.player.volume = value

    def _on_speed_clicked(self):
        """Cycles through speeds: 1.0, 2.0, 3.0, 4.0."""
        self._hide_popups()
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
            self._update_chapter_title_text(title)
            # Also sync the list selection visually
            self.chapter_list_widget.setCurrentRow(index)

            # Update tooltips for navigation buttons
            if index > 0:
                prev_title = chaps[index - 1].get('title') or f"Chapter {index}"
                self.prev_button.setToolTip(prev_title)
            else:
                self.prev_button.setToolTip("")

            if index < len(chaps) - 1:
                next_title = chaps[index + 1].get('title') or f"Chapter {index + 2}"
                self.next_button.setToolTip(next_title)
            else:
                self.next_button.setToolTip("")

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
        
        # Calculate height: stop before the transport controls
        # Start Y is exactly 56 (32 title + 24 progress)
        sidebar_y = 56
        
        # Hardcoded heights as requested
        self.sidebar.setFixedHeight(200)
        self.settings_panel.setFixedHeight(370)

        self.settings_panel.setFixedWidth(int(self.width() * 0.9))

        # Ensure sidebar position is maintained during resize
        if not self.sidebar_expanded:
            self.sidebar.move(-self.sidebar.width(), sidebar_y)
        else:
            self.sidebar.move(0, sidebar_y)
            
        if self.settings_panel.isVisible():
            self.settings_panel.move(0, sidebar_y)
        else:
            self.settings_panel.move(-self.settings_panel.width(), sidebar_y)

        self._update_cover_art_scaling()
        # Reposition percentage label
        if hasattr(self, 'progress_percentage_label'):
            self.progress_percentage_label.resize(self.progress_slider.size())

    def _on_drag_area_pressed(self, event):
        if event.button() == Qt.LeftButton:
            self._hide_popups()
            self.windowHandle().startSystemMove()
        elif event.button() == Qt.RightButton:
            # If settings or chapter list is open, dismiss them
            if self.settings_panel.isVisible():
                self._close_settings_flow()
            elif hasattr(self, 'chapter_list_widget') and self.chapter_list_widget.isVisible():
                self.chapter_list_widget.hide()
            else:
                # Otherwise, toggle the sidebar as usual
                self._toggle_sidebar()

    def toggle_play_pause(self):
        self._hide_popups()
        if not self.player:
            return
        if self.play_pause_button.text() == "Restart":
            self.player.time_pos = 0
            self.player.pause = False
            return
        self.player.pause = not self.player.pause

    def handle_rewind(self):
        self._hide_popups()
        if self.player:
            skip = self.config.get_skip_duration()
            self.player.time_pos = max(0, (self.player.time_pos or 0) - skip)
    def handle_forward(self):
        self._hide_popups()
        if self.player:
            skip = self.config.get_skip_duration()
            self.player.time_pos = min(self.player.duration or 0, (self.player.time_pos or 0) + skip)
    def handle_prev(self):
        self._hide_popups()
        if self.player:
            self.player.previous_chapter()
    def handle_next(self):
        self._hide_popups()
        if self.player:
            self.player.next_chapter()

    def eventFilter(self, obj, event):
        """Global event filter to handle dismissing popups on clicks outside."""
        if event.type() == QEvent.MouseButtonPress:
            if hasattr(self, 'chapter_list_widget') and self.chapter_list_widget.isVisible():
                # Convert global position to check if it's inside the dropdown
                gp = event.globalPosition().toPoint()
                if not self.chapter_list_widget.geometry().contains(gp):
                    self._hide_popups()
        return super().eventFilter(obj, event)

    def mousePressEvent(self, event):
        self._hide_popups()
        super().mousePressEvent(event)

    def closeEvent(self, event):
        if self.player:
            self.config.set_volume(self.volume_slider.value())
            self.config.set_last_position(self.current_file, self.player.time_pos)
            self.player.terminate()
        event.accept()
