import math
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt
from .controls import ClickSlider

# Matches app.py's _BALANCE_ARROW_STEP (not imported directly — app.py imports FROM this
# module, so importing back would risk a circular import). Used as both the arrow-key step
# (app.py's _handle_settings_arrows, which reaches every ClickSlider generically) and the
# mouse-wheel step for these 6 sliders (ClickSlider.wheel_step) — kept the same value so
# the two input methods feel identically granular.
_SLIDER_WHEEL_STEP = 5

class AudioSettingsTab(QWidget):
    """Handles the UI and logic for audio processing settings (normalization, boost, etc.)."""
    def __init__(self, player, config, parent=None):
        super().__init__(parent)
        self.player = player
        self.config = config
        self.voice_buttons = {}
        self.mono_buttons = {}
        self.swap_buttons = {}
        self.eq_sliders = {}

        self._setup_ui()
        self.update_visuals()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 10)

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
        swap_header = QLabel("Channel swap")
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

        # --- Equalizer ---
        # Order is Voice/Stereo/Swap/EQ/Balance (not importance order, which would put EQ
        # first) — EQ's 5 rows would cost 5 extra Down-presses to reach Voice boost from the
        # top of the tab if it opened the list. See CLAUDE.md/SESSION.md for the live-feedback
        # trail; this ordering was Pryme's own explicit call over the importance-first one.
        eq_header = QLabel("Equalizer")
        eq_header.setObjectName("settings_header")
        layout.addWidget(eq_header)
        # Each band's QHBoxLayout is added directly to the tab's own top-level layout below
        # (not nested inside a shared QVBoxLayout wrapper) — panels.settings_tab_button_rows()
        # only walks ONE level of the tab's layout looking for a QHBoxLayout-of-widgets or a
        # bare widget; a QVBoxLayout-of-QHBoxLayouts wrapper is invisible to that walk, which
        # silently dropped all 5 EQ rows from arrow-key navigation (Up/Down jumped straight
        # from Channel swap to L/R balance — live report 2026-09-19). Flattening matches the
        # shape every other row in every other tab already uses, so no special-casing is
        # needed in panels.py.
        eq_freqs = [("100", "100"), ("300", "300"), ("1000", "1K"), ("3000", "3K"), ("8000", "8K")]
        for eq_i, (freq, label) in enumerate(eq_freqs):
            eq_row = QHBoxLayout()
            slider = ClickSlider(Qt.Horizontal)
            slider.setObjectName(f"eq_slider_{freq}")
            slider.center_mark = True
            slider.snap_to_center = True
            slider.fill_from_center = True
            # Darker-toward-deflection gradient (not balance's brighter-edges one) — pushing
            # an EQ band away from center should read as "pulled toward shadow", not lit up.
            slider.gradient_style = "eq"
            slider.wheel_step = _SLIDER_WHEEL_STEP
            slider.setRange(-60, 60)
            slider.setValue(int(getattr(self.config, f"get_eq_gain_{freq}")() * 10))
            slider.setFixedHeight(10)
            # Full-width (via the row's stretch=1 below) — a short slider left the freq label
            # stranded near mid-screen, visually disconnected from its own row (live feedback,
            # 2026-09-19).
            # Same reasoning as balance_slider below: ClickSlider is NoFocus by default
            # (load-bearing for the transport sliders), granted per-instance here since this
            # lives inside a panel where that rule doesn't apply.
            slider.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            slider.valueChanged.connect(lambda v, k=freq: self._on_eq_changed(k, v))
            eq_row.addWidget(slider, stretch=1, alignment=Qt.AlignmentFlag.AlignVCenter)
            freq_label = QLabel(label)
            freq_label.setObjectName("eq_freq_label")
            freq_label.setFixedWidth(20)
            eq_row.addWidget(freq_label, alignment=Qt.AlignmentFlag.AlignVCenter)
            layout.addLayout(eq_row)
            # Kept tight between EQ rows specifically (was eq_rows.setSpacing(2) before
            # flattening) — the top-level tab layout has no explicit setSpacing anywhere
            # else (every other row's gap comes purely from #settings_header's margin-top,
            # per CLAUDE.md), so an explicit small gap here is the only way to keep the 5
            # bands visually grouped tighter than a normal inter-group gap.
            if eq_i < len(eq_freqs) - 1:
                layout.addSpacing(2)
            self.eq_sliders[freq] = slider

        # --- Balance ---
        balance_header = QLabel("L/R balance")
        balance_header.setObjectName("settings_header")
        layout.addWidget(balance_header)
        self.balance_slider = ClickSlider(Qt.Horizontal)
        self.balance_slider.setObjectName("balance_slider")
        self.balance_slider.center_mark = True
        self.balance_slider.snap_to_center = True
        self.balance_slider.fill_from_center = True
        # Brighter-edges/darker-center gradient — the opposite intent of the EQ sliders'
        # "eq" style: deflecting away from center should read as lighting up, not dimming.
        self.balance_slider.gradient_style = "balance"
        self.balance_slider.wheel_step = _SLIDER_WHEEL_STEP
        self.balance_slider.setRange(-100, 100)
        self.balance_slider.setValue(int(self.config.get_balance() * 100))
        self.balance_slider.setFixedHeight(12)
        # Kept shorter than the full-width EQ sliders — full width put it close enough to
        # the cover art underneath that it started blending in (live feedback, 2026-09-19).
        self.balance_slider.setFixedWidth(140)
        # Keyboard-navigable, unlike every other ClickSlider in the app. ClickSlider is a
        # QWidget subclass and so NoFocus by default, which is deliberate and load-bearing for
        # the transport sliders (see CLAUDE.md's NoFocus sweep: a focusable chrome widget would
        # swallow Space and starve the global shortcut dispatcher). This instance lives INSIDE a
        # panel, where that rule does not apply and where it needs to be a keyboard stop like
        # any other Audio control — so the policy is granted per-instance, never on the class.
        # Left/Right adjust its value; see MainWindow._handle_settings_arrows.
        self.balance_slider.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.balance_slider.valueChanged.connect(self._on_balance_changed)
        layout.addWidget(self.balance_slider)

        layout.addSpacing(10)
        self.reset_audio_btn = QPushButton("Reset to defaults")
        self.reset_audio_btn.setObjectName("reset_audio_btn")
        self.reset_audio_btn.clicked.connect(self._reset_settings)
        self.reset_audio_btn.hide()
        layout.addWidget(self.reset_audio_btn)

        # A trailing addStretch() with no fixed-size anchor below it would let the EQ rows
        # visibly drift apart to fill the panel's leftover height whenever reset_audio_btn is
        # hidden (is_default) — addStretch(1) alone can't tell "absorb slack below the last
        # widget" from "absorb slack the last widget itself should keep tight to its
        # neighbors." Reset_audio_btn is always in the layout (just hidden), so it already
        # anchors the bottom; the stretch only needs to sit below everything, never between.
        layout.addStretch()

    def _update_setting(self, kind, value):
        if kind == "voice": self.config.set_voice_boost_enabled(value)
        elif kind == "mono": self.config.set_mono_enabled(value)
        elif kind == "swap": self.config.set_channels_swapped(value)
        self.update_visuals()
        self.sync_player()

    def _on_balance_changed(self, value):
        self.config.set_balance(value / 100.0)
        self.sync_player()
        self.update_visuals()

    def _on_eq_changed(self, freq_key, value):
        getattr(self.config, f"set_eq_gain_{freq_key}")(value / 10.0)
        self.sync_player()
        self.update_visuals()

    def _reset_settings(self):
        self.config.set_voice_boost_enabled(False)
        self.config.set_mono_enabled(False)
        self.config.set_channels_swapped(False)
        self.config.set_balance(0.0)
        self.balance_slider.setValue(0)
        for freq, slider in self.eq_sliders.items():
            getattr(self.config, f"set_eq_gain_{freq}")(0.0)
            slider.setValue(0)
        self.sync_player()
        self.update_visuals()

    def sync_player(self):
        if self.player:
            self.player.apply_audio_processing(
                voice_boost=self.config.get_voice_boost_enabled(),
                mono=self.config.get_mono_enabled(),
                swap=self.config.get_channels_swapped(),
                balance=self.config.get_balance(),
                eq_100=self.config.get_eq_gain_100(),
                eq_300=self.config.get_eq_gain_300(),
                eq_1000=self.config.get_eq_gain_1000(),
                eq_3000=self.config.get_eq_gain_3000(),
                eq_8000=self.config.get_eq_gain_8000(),
            )

    def update_visuals(self):
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

        for slider in self.eq_sliders.values():
            slider.style().unpolish(slider)
            slider.style().polish(slider)

        balance = self.config.get_balance()
        eq_gains = [getattr(self.config, f"get_eq_gain_{freq}")() for freq in self.eq_sliders]
        is_default = (
            not voice and not mono and not swap
            and math.isclose(balance, 0.0, abs_tol=0.01)
            and all(math.isclose(g, 0.0, abs_tol=0.01) for g in eq_gains)
        )
        self.reset_audio_btn.setVisible(not is_default)