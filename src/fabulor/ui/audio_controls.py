import math
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt
from .controls import ClickSlider

class AudioSettingsTab(QWidget):
    """Handles the UI and logic for audio processing settings (normalization, boost, etc.)."""
    def __init__(self, player, config, parent=None):
        super().__init__(parent)
        self.player = player
        self.config = config
        self.norm_buttons = {}
        self.voice_buttons = {}
        self.mono_buttons = {}
        self.swap_buttons = {}
        
        self._setup_ui()
        self.update_visuals()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 10)

        # --- Normalization ---
        norm_header = QLabel("Speech compression (Normalization)")
        norm_header.setObjectName("settings_header")
        layout.addWidget(norm_header)
        norm_row = QHBoxLayout()
        for state in ["Off", "On"]:
            btn = QPushButton(state)
            btn.setObjectName("pattern_button")
            btn.clicked.connect(lambda _, s=state: self._update_setting("norm", s == "On"))
            norm_row.addWidget(btn)
            self.norm_buttons[state] = btn
        norm_row.addStretch()
        layout.addLayout(norm_row)

        # --- Voice Boost ---
        voice_header = QLabel("Voice boost")
        voice_header.setObjectName("settings_header")
        layout.addWidget(voice_header)
        voice_row = QHBoxLayout()
        for state in ["Off", "On"]:
            btn = QPushButton(state)
            btn.setObjectName("pattern_button")
            btn.clicked.connect(lambda _, s=state: self._update_setting("voice", s == "On"))
            voice_row.addWidget(btn)
            self.voice_buttons[state] = btn
        voice_row.addStretch()
        layout.addLayout(voice_row)

        # --- Stereo / Mono ---
        mono_header = QLabel("Stereo / Mono")
        mono_header.setObjectName("settings_header")
        layout.addWidget(mono_header)
        mono_row = QHBoxLayout()
        for mode in ["Stereo", "Mono"]:
            btn = QPushButton(mode)
            btn.setObjectName("pattern_button")
            btn.clicked.connect(lambda _, m=mode: self._update_setting("mono", m == "Mono"))
            mono_row.addWidget(btn)
            self.mono_buttons[mode] = btn
        mono_row.addStretch()
        layout.addLayout(mono_row)

        # --- Channel Swap ---
        swap_header = QLabel("Channel swap (L ↔ R)")
        swap_header.setObjectName("settings_header")
        layout.addWidget(swap_header)
        swap_row = QHBoxLayout()
        for state in ["Normal", "Swapped"]:
            btn = QPushButton(state)
            btn.setObjectName("pattern_button")
            btn.clicked.connect(lambda _, s=state: self._update_setting("swap", s == "Swapped"))
            swap_row.addWidget(btn)
            self.swap_buttons[state] = btn
        swap_row.addStretch()
        layout.addLayout(swap_row)

        # --- Balance ---
        balance_header = QLabel("L/R balance")
        balance_header.setObjectName("settings_header")
        layout.addWidget(balance_header)
        self.balance_slider = ClickSlider(Qt.Horizontal)
        self.balance_slider.setObjectName("balance_slider")
        self.balance_slider.center_mark = True
        self.balance_slider.snap_to_center = True
        self.balance_slider.setRange(-100, 100)
        self.balance_slider.setValue(int(self.config.get_balance() * 100))
        self.balance_slider.setFixedHeight(12)
        self.balance_slider.setFixedWidth(140)
        self.balance_slider.valueChanged.connect(self._on_balance_changed)
        layout.addWidget(self.balance_slider)

        layout.addSpacing(10)
        self.reset_audio_btn = QPushButton("Reset to defaults")
        self.reset_audio_btn.setObjectName("reset_audio_btn")
        self.reset_audio_btn.clicked.connect(self._reset_settings)
        self.reset_audio_btn.hide()
        layout.addWidget(self.reset_audio_btn)

        layout.addStretch()

    def _update_setting(self, kind, value):
        if kind == "norm": self.config.set_norm_enabled(value)
        elif kind == "voice": self.config.set_voice_boost_enabled(value)
        elif kind == "mono": self.config.set_mono_enabled(value)
        elif kind == "swap": self.config.set_channels_swapped(value)
        self.update_visuals()
        self.sync_player()

    def _on_balance_changed(self, value):
        self.config.set_balance(value / 100.0)
        self.sync_player()
        self.update_visuals()

    def _reset_settings(self):
        self.config.set_norm_enabled(False)
        self.config.set_voice_boost_enabled(False)
        self.config.set_mono_enabled(False)
        self.config.set_channels_swapped(False)
        self.config.set_balance(0.0)
        self.balance_slider.setValue(0)
        self.sync_player()
        self.update_visuals()

    def sync_player(self):
        if self.player:
            self.player.apply_audio_processing(
                norm=self.config.get_norm_enabled(),
                voice_boost=self.config.get_voice_boost_enabled(),
                mono=self.config.get_mono_enabled(),
                swap=self.config.get_channels_swapped(),
                balance=self.config.get_balance()
            )

    def update_visuals(self):
        norm = self.config.get_norm_enabled()
        for s, btn in self.norm_buttons.items():
            btn.setProperty("selected", "true" if (s == "On" if norm else s == "Off") else "false")
            btn.style().unpolish(btn); btn.style().polish(btn)
            
        voice = self.config.get_voice_boost_enabled()
        for s, btn in self.voice_buttons.items():
            btn.setProperty("selected", "true" if (s == "On" if voice else s == "Off") else "false")
            btn.style().unpolish(btn); btn.style().polish(btn)
            
        mono = self.config.get_mono_enabled()
        for m, btn in self.mono_buttons.items():
            btn.setProperty("selected", "true" if (m == "Mono" if mono else m == "Stereo") else "false")
            btn.style().unpolish(btn); btn.style().polish(btn)
            
        swap = self.config.get_channels_swapped()
        for s, btn in self.swap_buttons.items():
            btn.setProperty("selected", "true" if (s == "Swapped" if swap else s == "Normal") else "false")
            btn.style().unpolish(btn); btn.style().polish(btn)
            
        # Force the balance slider to re-evaluate its QSS properties (bg_color, fill_color)
        self.balance_slider.style().unpolish(self.balance_slider)
        self.balance_slider.style().polish(self.balance_slider)
            
        balance = self.config.get_balance()
        is_default = (not norm and not voice and not mono and not swap and math.isclose(balance, 0.0, abs_tol=0.01))
        self.reset_audio_btn.setVisible(not is_default)