from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGridLayout
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from ..themes import THEMES

class SpeedControlsPanel(QWidget):
    """Handles UI and logic for playback speed, skip intervals, and smart rewind."""
    speed_changed = Signal(float)
    close_requested = Signal()

    def __init__(self, player, config, theme_manager, parent=None):
        super().__init__(parent)
        self.player = player
        self.config = config
        self.theme_manager = theme_manager
        self.setObjectName("speed_panel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        
        self._speed_presets = [
            0.25, 0.50, 0.75, 1.00, 1.25, 1.50, 1.75, 2.00, 2.25, 2.50, 2.75, 3.00,
            3.25, 3.50, 3.75, 4.00
        ]
        self._speed_grid_buttons = []
        self.def_speed_buttons = {}
        self.step_buttons = {}
        self.skip_buttons = {}
        self.long_skip_buttons = {}
        self.smart_wait_buttons = {}
        self.smart_dur_buttons = {}

        self._setup_ui()
        self.update_visuals()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        
        speed_header = QLabel("Playback speed")
        speed_header.setObjectName("settings_header")
        layout.addWidget(speed_header)
        
        grid = QGridLayout()
        grid.setSpacing(8)
        for i, val in enumerate(self._speed_presets):
            btn = QPushButton(f"{val:.2f}x")
            btn.setFixedSize(57, 30)
            # Note: We pass None for current_file here because UI clicks usually happen on an active book.
            # The parent (MainWindow) handles the context via set_speed.
            btn.clicked.connect(lambda _, v=val: self._on_preset_clicked(v))
            grid.addWidget(btn, i // 4, i % 4)
            self._speed_grid_buttons.append(btn)
        layout.addLayout(grid)
        
        layout.addSpacing(2)

        # Default Speed Section
        def_header = QLabel("Default speed")
        def_header.setObjectName("settings_header")
        layout.addWidget(def_header)
        def_row = QHBoxLayout()
        for val in [1.0, 1.5, 1.75, 2.0, 2.25, 2.5, 3.0]:
            btn = QPushButton(f"{val}x")
            btn.setObjectName("pattern_button")
            btn.clicked.connect(lambda _, v=val: self._update_def_speed_mode(v))
            def_row.addWidget(btn)
            self.def_speed_buttons[val] = btn
        def_row.addStretch()
        layout.addLayout(def_row)

        # Increment Step Section
        step_header = QLabel("Step")
        step_header.setObjectName("settings_header")
        layout.addWidget(step_header)
        step_row_layout = QHBoxLayout()
        for val in [0.05, 0.1, 0.25, 0.5]:
            btn = QPushButton(str(val))
            btn.setObjectName("pattern_button")
            btn.clicked.connect(lambda _, v=val: self._update_step_mode(v))
            step_row_layout.addWidget(btn)
            self.step_buttons[val] = btn
        step_row_layout.addStretch()
        layout.addLayout(step_row_layout)

        # Skip & Long Skip Section
        skip_header_row = QHBoxLayout()
        skip_label = QLabel("Skip")
        skip_label.setObjectName("settings_header")
        long_skip_label = QLabel("Long skip")
        long_skip_label.setObjectName("settings_header")
        skip_header_row.addWidget(skip_label)
        skip_header_row.addStretch()
        skip_header_row.addWidget(long_skip_label)
        layout.addLayout(skip_header_row)

        skip_buttons_row = QHBoxLayout()
        for val in [5, 10, 15, 30]:
            btn = QPushButton(str(val))
            btn.setObjectName("pattern_button")
            btn.clicked.connect(lambda _, v=val: self._update_skip_mode(v))
            skip_buttons_row.addWidget(btn)
            self.skip_buttons[val] = btn
        skip_buttons_row.addStretch()

        for val in [1, 2, 5]:
            btn = QPushButton(str(val))
            btn.setObjectName("pattern_button")
            btn.clicked.connect(lambda _, v=val: self._update_long_skip_mode(v))
            skip_buttons_row.addWidget(btn)
            self.long_skip_buttons[val] = btn
        layout.addLayout(skip_buttons_row)

        # Smart Rewind Section
        smart_label = QLabel("Smart rewind")
        smart_label.setObjectName("settings_header")
        layout.addWidget(smart_label)

        smart_buttons_row = QHBoxLayout()
        for val, label in [(0, "Off"), (5, "5"), (30, "30"), (60, "60")]:
            btn = QPushButton(label)
            btn.setObjectName("pattern_button")
            btn.clicked.connect(lambda _, v=val: self._update_smart_rewind_mode(v))
            smart_buttons_row.addWidget(btn)
            self.smart_wait_buttons[val] = btn
        smart_buttons_row.addStretch()

        for val in [10, 20, 30]:
            btn = QPushButton(str(val))
            btn.setObjectName("pattern_button")
            btn.clicked.connect(lambda _, v=val: self._update_smart_rewind_duration(v))
            smart_buttons_row.addWidget(btn)
            self.smart_dur_buttons[val] = btn
        layout.addLayout(smart_buttons_row)
        layout.addStretch()

    def _on_preset_clicked(self, value):
        self.set_speed(value, getattr(self.parent(), 'current_file', None))
        self.close_requested.emit()

    def set_speed(self, value, current_file=None, save=True):
        """Applies speed to engine, config, and signals UI change."""
        if self.player:
            self.player.speed = value
            if save and current_file:
                self.config.set_book_speed(current_file, value)
            self.speed_changed.emit(value)

    def _update_def_speed_mode(self, val): self.config.set_default_speed(val); self.update_visuals()
    def _update_step_mode(self, val): self.config.set_speed_increment(val); self.update_visuals()
    def _update_skip_mode(self, val): self.config.set_skip_duration(val); self.update_visuals()
    def _update_long_skip_mode(self, val): self.config.set_long_skip_duration(val); self.update_visuals()
    def _update_smart_rewind_mode(self, val): self.config.set_smart_rewind_wait(val); self._validate_smart_rewind_settings(finalize=False)
    def _update_smart_rewind_duration(self, val): self.config.set_smart_rewind_duration(val); self._validate_smart_rewind_settings(finalize=False)

    def _validate_smart_rewind_settings(self, finalize=False):
        wait = self.config.get_smart_rewind_wait()
        dur = self.config.get_smart_rewind_duration()
        if finalize and ((wait > 0 and dur == 0) or (wait == 0 and dur > 0)):
            self.config.set_smart_rewind_wait(0)
            self.config.set_smart_rewind_duration(0)
        self.update_visuals()

    def update_visuals(self, theme_name=None):
        name = theme_name or self.theme_manager._current_theme_name
        t = THEMES.get(name, THEMES["The Color Purple"])
        accent = QColor(t['accent'])
        btn_text = t.get('button_text', t.get('text_on_light_bg', t['text']))

        for i, btn in enumerate(self._speed_grid_buttons):
            alpha = int(75 + (180 * (i / (len(self._speed_presets) - 1))))
            c = QColor(accent)
            c.setAlpha(alpha)
            btn.setStyleSheet(f"background-color: rgba({c.red()}, {c.green()}, {c.blue()}, {c.alpha()}); color: {btn_text}; border: none;")

        def sync_btn(group, current):
            for val, btn in group.items():
                btn.setProperty("selected", "true" if float(val) == float(current) else "false")
                btn.style().unpolish(btn); btn.style().polish(btn)

        sync_btn(self.def_speed_buttons, self.config.get_default_speed())
        sync_btn(self.step_buttons, self.config.get_speed_increment())
        sync_btn(self.skip_buttons, self.config.get_skip_duration())
        sync_btn(self.long_skip_buttons, self.config.get_long_skip_duration())
        sync_btn(self.smart_wait_buttons, self.config.get_smart_rewind_wait())
        sync_btn(self.smart_dur_buttons, self.config.get_smart_rewind_duration())

        # Ensure the panel's own background is refreshed
        self.style().unpolish(self); self.style().polish(self)
