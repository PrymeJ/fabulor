import time
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGridLayout, QLineEdit
from PySide6.QtCore import Qt, QRegularExpression, Signal
from PySide6.QtGui import QRegularExpressionValidator, QColor
from .title_bar import RightClickButton

class SleepTimerPanel(QWidget):
    timer_started = Signal()
    timer_stopped = Signal()
    display_text_updated = Signal(str)

    def __init__(self, player, config, theme_manager, parent=None):
        super().__init__(parent)
        self.player = player
        self.config = config
        self.theme_manager = theme_manager
        self.setObjectName("sleep_panel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        
        self._sleep_timer_end_time = None # Unix timestamp when sleep timer should end
        self._sleep_mode = None # 'timed', 'end_of_chapter', 'end_of_book'
        self._current_sleep_fade = self.config.get_sleep_fade_duration()
        
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        sleep_header = QLabel("Sleep Timer")
        sleep_header.setObjectName("settings_header")
        layout.addWidget(sleep_header)

        # Time Presets Grid
        grid = QGridLayout()
        grid.setSpacing(4)
        presets_minutes = [2, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 75, 90, 120]
        self._sleep_presets_buttons = []
        for i, val in enumerate(presets_minutes):
            btn = QPushButton(f"{val} min")
            btn.setFixedSize(55, 30)
            btn.clicked.connect(lambda _, v=val: self.set_sleep_timer(duration_minutes=v))
            grid.addWidget(btn, i // 4, i % 4)
            self._sleep_presets_buttons.append(btn)
        layout.addLayout(grid)

        # Special Modes
        special_modes_layout = QHBoxLayout()
        self.end_chap_btn = QPushButton("End of chapter")
        self.end_chap_btn.clicked.connect(lambda: self.set_sleep_timer(mode='end_of_chapter'))
        special_modes_layout.addWidget(self.end_chap_btn)

        self.end_book_btn = QPushButton("End of book")
        self.end_book_btn.clicked.connect(lambda: self.set_sleep_timer(mode='end_of_book'))
        special_modes_layout.addWidget(self.end_book_btn)
        layout.addLayout(special_modes_layout)

        # Custom Time Input
        custom_time_layout = QHBoxLayout()
        self.custom_sleep_input = QLineEdit()
        self.custom_sleep_input.setPlaceholderText("min")
        self.custom_sleep_input.setFixedWidth(50)
        self.custom_sleep_input.setValidator(QRegularExpressionValidator(QRegularExpression("[1-9][0-9]{0,2}"), self))
        custom_time_layout.addWidget(self.custom_sleep_input)

        set_custom_btn = QPushButton("Set")
        set_custom_btn.clicked.connect(self._on_custom_sleep_time_set)
        custom_time_layout.addWidget(set_custom_btn)
        custom_time_layout.addStretch()
        layout.addLayout(custom_time_layout)

        # Fade out options
        fade_header = QLabel("Fade-out")
        fade_header.setObjectName("settings_header")
        layout.addWidget(fade_header)

        fade_layout = QHBoxLayout()
        fade_layout.setSpacing(5)
        self._sleep_fade_btns = {}
        fade_options = [("Off", 0), ("30s", 30), ("1m", 60), ("2m", 120), ("5m", 300)]
        for text, seconds in fade_options:
            btn = RightClickButton(text)
            btn.setFixedSize(45, 28)
            btn.setToolTip("Right-click to set as default")
            btn.clicked.connect(lambda _, s=seconds: self.set_sleep_fade(s, save=False))
            btn.rightClicked.connect(lambda s=seconds: self.set_sleep_fade(s, save=True))
            fade_layout.addWidget(btn)
            self._sleep_fade_btns[seconds] = btn
        
        layout.addLayout(fade_layout)

        # Disable Button
        layout.addSpacing(20)
        self.disable_sleep_btn = QPushButton("Disable the sleep timer")
        self.disable_sleep_btn.setObjectName("disable_sleep_btn")
        self.disable_sleep_btn.clicked.connect(self.disable_sleep_timer)
        self.disable_sleep_btn.hide()
        layout.addWidget(self.disable_sleep_btn)

        layout.addStretch()

    def _on_custom_sleep_time_set(self):
        try:
            text = self.custom_sleep_input.text()
            if text:
                minutes = int(text)
                if minutes > 0:
                    self.set_sleep_timer(duration_minutes=minutes)
        except ValueError:
            pass

    def set_sleep_timer(self, duration_minutes=None, mode=None):
        self.disable_sleep_timer()
        if self.player:
            self.player.pause = False

        if duration_minutes is not None:
            self._sleep_timer_end_time = time.time() + duration_minutes * 60
            self._sleep_mode = 'timed'
            self.config.set_sleep_duration(duration_minutes)
            self.config.set_sleep_mode('timed')
            self.disable_sleep_btn.show()
            self.timer_started.emit()
        elif mode in ['end_of_chapter', 'end_of_book']:
            self._sleep_mode = mode
            self.config.set_sleep_mode(mode)
            self.disable_sleep_btn.show()
            self.timer_started.emit()
        
        self.update_panel_styling()

    def disable_sleep_timer(self):
        was_active = self._sleep_timer_end_time is not None or self._sleep_mode is not None
        self._sleep_timer_end_time = None
        self._sleep_mode = None
        self.disable_sleep_btn.hide()
        if was_active:
            self.timer_stopped.emit()
        self.display_text_updated.emit("")
        self.update_panel_styling()

    def set_sleep_fade(self, seconds, save=False):
        self._current_sleep_fade = seconds
        if save:
            self.config.set_sleep_fade_duration(seconds)
        self.update_panel_styling()

    def update_panel_styling(self):
        t_name = self.theme_manager._current_theme_name
        from ..themes import THEMES
        t = THEMES.get(t_name, THEMES["The Color Purple"])
        accent = QColor(t['accent'])
        btn_text = t.get('button_text', t.get('text_on_light_bg', t['text']))
        default_fade = self.config.get_sleep_fade_duration()

        for i, btn in enumerate(self._sleep_presets_buttons):
            alpha = int(75 + (180 * (i / (len(self._sleep_presets_buttons) - 1))))
            c = QColor(accent)
            c.setAlpha(alpha)
            btn.setStyleSheet(f"background-color: rgba({c.red()}, {c.green()}, {c.blue()}, {c.alpha()}); color: {btn_text}; border: none;")

        for i, (seconds, btn) in enumerate(self._sleep_fade_btns.items()):
            alpha = int(75 + (180 * (i / (len(self._sleep_fade_btns) - 1))))
            c = QColor(accent)
            c.setAlpha(alpha)
            
            is_active = (seconds == self._current_sleep_fade)
            is_default = (seconds == default_fade)
            
            border = f"2px solid {t['accent_light']}" if is_default else f"1px solid {t['accent']}"
            bg = f"rgba({c.red()}, {c.green()}, {c.blue()}, {c.alpha()})" if is_active else t['bg_dropdown']
            fg = btn_text if is_active else t['text']
            
            btn.setStyleSheet(f"background-color: {bg}; color: {fg}; border: {border};")

        # Refresh the panel's own style to ensure background is updated
        self.style().unpolish(self); self.style().polish(self)

    def update_timer_state(self, current_time, is_paused, player_pos, player_dur, is_eof):
        display_text = ""
        
        # Reset fade ratio by default; it will be overwritten below if fading
        self.player.set_fade_ratio(1.0)

        if self._sleep_timer_end_time is not None:
            remaining_seconds = max(0, int(self._sleep_timer_end_time - current_time))
            if remaining_seconds <= 0 or is_eof:
                self.disable_sleep_timer()
                if self.player:
                    self.player.pause = True
            else:
                display_text = f"[{self.player.format_time(remaining_seconds)}]"
                # Volume Fade Logic
                if self._current_sleep_fade > 0 and remaining_seconds <= self._current_sleep_fade:
                    ratio = remaining_seconds / self._current_sleep_fade
                    self.player.set_fade_ratio(ratio)

        elif self._sleep_mode == 'end_of_chapter':
            display_text = "[chapter]"
            if not is_paused and self.player.chapter_list and self.player.chapter is not None:
                curr_chap = self.player.chapter
                chaps = self.player.chapter_list
                if curr_chap < len(chaps) - 1:
                    next_chap_start = chaps[curr_chap + 1].get('time', player_dur)
                    if player_pos >= next_chap_start - 0.5 or is_eof:
                        self.disable_sleep_timer()
                        if self.player:
                            self.player.pause = True
                elif curr_chap == len(chaps) - 1 and (player_pos >= player_dur - 0.5 or is_eof):
                    self.disable_sleep_timer()
                    if self.player:
                        self.player.pause = True
        elif self._sleep_mode == 'end_of_book':
            display_text = "[book]"
            if not is_paused and (player_pos >= player_dur - 0.5 or is_eof):
                self.disable_sleep_timer()
                if self.player:
                    self.player.pause = True

        self.display_text_updated.emit(display_text)
