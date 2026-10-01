import math
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGraphicsOpacityEffect
from PySide6.QtCore import Qt
from .controls import ClickSlider

# ClickSlider is fully custom-painted (see controls.py's paintEvent) and never reads
# isEnabled() — dimming it needs an explicit post-composite opacity effect, not just
# setEnabled(). 0.35 is a starting value, not measured against anything in this app yet
# (other QGraphicsOpacityEffect uses here are fade-animation endpoints, 0.0/1.0, not a
# static "dimmed but still legible" level) — tune live against the real panel background.
_EQ_DIMMED_OPACITY = 0.35

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
        self.eq_enable_buttons = {}
        self.eq_sliders = {}
        self.eq_opacity_effects = {}
        self.eq_label_opacity_effects = {}

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

        # --- Stereo / Mono + Channel Swap ---
        # Merged onto one row, Channel swap right-aligned via a middle stretch — same shape
        # as Look tab's "Chapter notches / Animation" line (notches_header_row/notches_row in
        # main_window_builders.py), which panels.settings_tab_button_rows() already documents
        # as "two logical groups sharing ONE layout are deliberately ONE row." Unlike that
        # pair, Channel swap's visibility never depends on Stereo/Mono's state — it's simply
        # placed to the right, freeing a full header+button row of vertical space for the
        # Equalizer's own new On/Off toggle below.
        mono_swap_header_row = QHBoxLayout()
        mono_header = QLabel("Stereo / Mono")
        mono_header.setObjectName("settings_header")
        mono_swap_header_row.addWidget(mono_header)
        mono_swap_header_row.addStretch()
        swap_header = QLabel("Channel swap")
        swap_header.setObjectName("settings_header")
        mono_swap_header_row.addWidget(swap_header)
        layout.addLayout(mono_swap_header_row)

        mono_swap_row = QHBoxLayout()
        for mode in ["Stereo", "Mono"]:
            btn = QPushButton(mode)
            btn.setObjectName("pattern_button")
            btn.clicked.connect(lambda _, m=mode: self._update_setting("mono", m == "Mono"))
            mono_swap_row.addWidget(btn)
            self.mono_buttons[mode] = btn
        mono_swap_row.addStretch()
        for state in ["Normal", "Swapped"]:
            btn = QPushButton(state)
            btn.setObjectName("pattern_button")
            btn.clicked.connect(lambda _, s=state: self._update_setting("swap", s == "Swapped"))
            mono_swap_row.addWidget(btn)
            self.swap_buttons[state] = btn
        layout.addLayout(mono_swap_row)

        # --- Equalizer ---
        # Order is Voice/Stereo/Swap/EQ/Balance (not importance order, which would put EQ
        # first) — EQ's 5 rows would cost 5 extra Down-presses to reach Voice boost from the
        # top of the tab if it opened the list. See CLAUDE.md/SESSION.md for the live-feedback
        # trail; this ordering was Pryme's own explicit call over the importance-first one.
        eq_header = QLabel("Equalizer")
        eq_header.setObjectName("settings_header")
        layout.addWidget(eq_header)

        # On/Off toggle, default Off — dims (never hides) the 5 bands below when Off, so an
        # A/B comparison is a single click on this row rather than a layout jump. The 5 bands
        # stay in place and keep their own saved gains either way; Off only stops them being
        # SENT to the player (see sync_player/apply_audio_processing below) — right-clicking a
        # band to reset it, or dragging one, both still work while Off, exactly like editing a
        # muted track.
        eq_enable_row = QHBoxLayout()
        for state in ["Off", "On"]:
            btn = QPushButton(state)
            btn.setObjectName("pattern_button")
            btn.clicked.connect(lambda _, s=state: self._update_setting("eq_enabled", s == "On"))
            eq_enable_row.addWidget(btn)
            self.eq_enable_buttons[state] = btn
        eq_enable_row.addStretch()
        layout.addLayout(eq_enable_row)

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
            # Right-click resets just this one band — ClickSlider's own mousePressEvent
            # already emits rightClicked(ratio) unconditionally (used elsewhere for
            # seek-to-position on the transport sliders); these 5 EQ sliders simply
            # weren't connecting it to anything before, so the click was silently inert.
            slider.rightClicked.connect(lambda _ratio, k=freq: self._reset_eq_band(k))
            # Dimming lives on an effect, not the widget's own paint — see _EQ_DIMMED_OPACITY.
            opacity_effect = QGraphicsOpacityEffect(slider)
            opacity_effect.setOpacity(1.0)
            slider.setGraphicsEffect(opacity_effect)
            self.eq_opacity_effects[freq] = opacity_effect
            eq_row.setSpacing(4)
            eq_row.addWidget(slider, stretch=1, alignment=Qt.AlignmentFlag.AlignVCenter)
            freq_label = QLabel(label)
            freq_label.setObjectName("eq_freq_label")
            # 16, not 20 — narrowed 4px so the slider (stretch=1, claims whatever this
            # label doesn't) extends further right, per live feedback 2026-09-19.
            # The label stays right-aligned so its own text position doesn't move.
            freq_label.setFixedWidth(16)
            # Right-aligned so the label's own text sits flush against the slider's own
            # right edge instead of floating left inside its fixed-width box — a
            # left-aligned label in a fixed box left visibly more empty space between the
            # slider and the label than the slider's own left margin (live report,
            # 2026-09-19: "the right side has more space than the left").
            freq_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            eq_row.addWidget(freq_label, alignment=Qt.AlignmentFlag.AlignVCenter)
            label_opacity_effect = QGraphicsOpacityEffect(freq_label)
            label_opacity_effect.setOpacity(1.0)
            freq_label.setGraphicsEffect(label_opacity_effect)
            self.eq_label_opacity_effects[freq] = label_opacity_effect
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
        # Right-click resets to centered — same mechanism as the EQ bands above (2026-09-22).
        self.balance_slider.rightClicked.connect(lambda _ratio: self.balance_slider.setValue(0))
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
        elif kind == "eq_enabled": self.config.set_eq_enabled(value)
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

    def _reset_eq_band(self, freq_key):
        """Right-click on a single EQ slider resets just that band to 0dB — setValue's own
        valueChanged emit routes through _on_eq_changed exactly as a manual drag would, so
        this doesn't need to touch config/sync_player/update_visuals itself. A no-op if the
        band is already at 0 (setValue doesn't re-emit for an unchanged value), matching
        ClickSlider's own general behavior elsewhere."""
        self.eq_sliders[freq_key].setValue(0)

    def _reset_settings(self):
        self.config.set_voice_boost_enabled(False)
        self.config.set_mono_enabled(False)
        self.config.set_channels_swapped(False)
        self.config.set_eq_enabled(False)
        self.config.set_balance(0.0)
        self.balance_slider.setValue(0)
        for freq, slider in self.eq_sliders.items():
            getattr(self.config, f"set_eq_gain_{freq}")(0.0)
            slider.setValue(0)
        self.sync_player()
        self.update_visuals()

    def sync_player(self):
        if self.player:
            eq_on = self.config.get_eq_enabled()
            self.player.apply_audio_processing(
                voice_boost=self.config.get_voice_boost_enabled(),
                mono=self.config.get_mono_enabled(),
                swap=self.config.get_channels_swapped(),
                balance=self.config.get_balance(),
                eq_100=self.config.get_eq_gain_100() if eq_on else 0.0,
                eq_300=self.config.get_eq_gain_300() if eq_on else 0.0,
                eq_1000=self.config.get_eq_gain_1000() if eq_on else 0.0,
                eq_3000=self.config.get_eq_gain_3000() if eq_on else 0.0,
                eq_8000=self.config.get_eq_gain_8000() if eq_on else 0.0,
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

        eq_on = self.config.get_eq_enabled()
        for s, btn in self.eq_enable_buttons.items():
            btn.setProperty("selected", "true" if (s == "On" if eq_on else s == "Off") else "false")
            btn.style().unpolish(btn); btn.style().polish(btn)

        # Dimmed (never hidden) while Off, so the 5 bands stay a stable visual reference for
        # A/B comparison instead of the layout jumping on every toggle — see the toggle row's
        # own comment above. Dimming is via QGraphicsOpacityEffect (ClickSlider is fully
        # custom-painted and never reads isEnabled() — see _EQ_DIMMED_OPACITY). setEnabled
        # also blocks drag/wheel/right-click-reset input while Off and removes the slider from
        # arrow-key navigation (panels.settings_tab_button_rows' _navigable gates on
        # isEnabled()) — consistent with every other disabled control in the app, even though
        # this is the first ClickSlider to use setEnabled(False) at all.
        for freq, slider in self.eq_sliders.items():
            slider.setEnabled(eq_on)
            opacity = 1.0 if eq_on else _EQ_DIMMED_OPACITY
            self.eq_opacity_effects[freq].setOpacity(opacity)
            self.eq_label_opacity_effects[freq].setOpacity(opacity)
            slider.style().unpolish(slider)
            slider.style().polish(slider)

        balance = self.config.get_balance()
        eq_gains = [getattr(self.config, f"get_eq_gain_{freq}")() for freq in self.eq_sliders]
        # Gains only count as "dirty" while eq_on is True — while Off they have zero effect on
        # playback (sync_player sends 0.0 to the player regardless of the stored value), so a
        # book with saved gains but EQ Off is, in practice, already at its default audio.
        # Turning EQ back On with those same gains still saved immediately re-dirties it, since
        # `eq_on` gates the whole check — no separate "eq_on by itself" branch is needed.
        gains_dirty = eq_on and any(not math.isclose(g, 0.0, abs_tol=0.01) for g in eq_gains)
        is_default = (
            not voice and not mono and not swap and not gains_dirty
            and math.isclose(balance, 0.0, abs_tol=0.01)
        )
        self.reset_audio_btn.setVisible(not is_default)