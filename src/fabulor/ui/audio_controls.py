import math
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGraphicsOpacityEffect
from PySide6.QtCore import Qt, Signal
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
    def __init__(self, player, config, db=None, parent=None):
        super().__init__(parent)
        self.player = player
        self.config = config
        self.db = db
        # The currently-loaded book's path, for resolving its EQ+balance mode (2026-10-02) — this
        # tab has no other way to know which book is playing (Player itself tracks no path; only
        # MainWindow.current_file does). None means no book loaded (e.g. empty library), in which
        # case there is nothing to supersede and this tab behaves exactly as the pure-global
        # version always did. Set via set_current_book(), called from MainWindow alongside every
        # other sync_player() call site.
        self._current_book_path = None
        self.voice_buttons = {}
        self.mono_buttons = {}
        self.swap_buttons = {}
        self.eq_enable_buttons = {}
        self.eq_sliders = {}
        self.eq_opacity_effects = {}
        self.eq_label_opacity_effects = {}

        self._setup_ui()
        self.update_visuals()

    def set_current_book(self, book_path: str | None) -> None:
        """Called by MainWindow on every book load/switch (and on removal, with None) — the one
        place this tab learns which book's EQ+balance override, if any, supersedes the global
        settings shown here. Re-derives visuals (the superseded dim+note) and re-syncs the player
        immediately, since switching books can change which gains/balance actually apply."""
        self._current_book_path = book_path
        self.update_visuals()
        self.sync_player()

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

        # Superseded-indicator (2026-10-02) — shown only while the currently-loaded book has its
        # own EQ+balance override active (mode "off" or "custom" — see _book_override_active
        # below). ONE note covers both EQ and balance, placed above the EQ bands, because they
        # share a single per-book mode (one 3-state toggle on Book Detail's EQ tab governs both,
        # per the decided scope) — not two independent overrides needing two notes. Named after
        # Pryme's own observed failure mode: without this, tinkering with the global sliders while
        # a book override is active produces no audible change and reads as "the EQ is broken"
        # rather than "correctly shadowed by this book." Text only — no icon, matching every other
        # plain state label in this app. Hidden by default; update_visuals() owns both its text
        # and visibility, and also dims the balance slider below alongside the 5 EQ bands.
        self.audio_superseded_label = QLabel("")
        self.audio_superseded_label.setObjectName("audio_superseded_label")
        self.audio_superseded_label.setWordWrap(True)
        self.audio_superseded_label.hide()
        layout.addWidget(self.audio_superseded_label)

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
        self.balance_opacity_effect = QGraphicsOpacityEffect(self.balance_slider)
        self.balance_opacity_effect.setOpacity(1.0)
        self.balance_slider.setGraphicsEffect(self.balance_opacity_effect)
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

    def _book_override_mode(self) -> str:
        """"global" (no override, or no book loaded) / "off" / "custom" for the currently-loaded
        book. The sole place this tab reads get_book_eq_mode — every other method goes through
        this or _book_override_active, never the config call directly, so "no book loaded" only
        needs handling once."""
        if self._current_book_path is None:
            return "global"
        return self.config.get_book_eq_mode(self._current_book_path)

    def _book_override_active(self) -> bool:
        """True while the loaded book is shadowing the global EQ+balance settings shown on this
        tab (mode "off" or "custom") — drives the superseded dim+note. "global" mode is NOT an
        override: the book is transparently inheriting whatever this tab already shows, so there
        is nothing to flag."""
        return self._book_override_mode() in ("off", "custom")

    def _resolve_effective_audio(self) -> dict:
        """What should actually reach the player right now, resolving the current book's
        Global/Off/Custom EQ+balance mode against this tab's own global values. Voice boost/mono/
        swap are never book-overridable (see TODO.md's scope decision) and always come straight
        from config. Returns a dict matching apply_audio_processing's EQ+balance kwargs."""
        mode = self._book_override_mode()
        if mode == "off":
            return {"balance": 0.0, "eq_100": 0.0, "eq_300": 0.0, "eq_1000": 0.0,
                    "eq_3000": 0.0, "eq_8000": 0.0}
        if mode == "custom":
            path = self._current_book_path
            return {
                "balance": self.config.get_book_balance(path) or 0.0,
                "eq_100": self.config.get_book_eq_gain_100(path) or 0.0,
                "eq_300": self.config.get_book_eq_gain_300(path) or 0.0,
                "eq_1000": self.config.get_book_eq_gain_1000(path) or 0.0,
                "eq_3000": self.config.get_book_eq_gain_3000(path) or 0.0,
                "eq_8000": self.config.get_book_eq_gain_8000(path) or 0.0,
            }
        # "global" — same logic sync_player always had: EQ gains are zeroed when the GLOBAL
        # toggle is off, independent of any book mode (which is "global" here by definition).
        eq_on = self.config.get_eq_enabled()
        return {
            "balance": self.config.get_balance(),
            "eq_100": self.config.get_eq_gain_100() if eq_on else 0.0,
            "eq_300": self.config.get_eq_gain_300() if eq_on else 0.0,
            "eq_1000": self.config.get_eq_gain_1000() if eq_on else 0.0,
            "eq_3000": self.config.get_eq_gain_3000() if eq_on else 0.0,
            "eq_8000": self.config.get_eq_gain_8000() if eq_on else 0.0,
        }

    def sync_player(self):
        if self.player:
            effective = self._resolve_effective_audio()
            self.player.apply_audio_processing(
                voice_boost=self.config.get_voice_boost_enabled(),
                mono=self.config.get_mono_enabled(),
                swap=self.config.get_channels_swapped(),
                **effective,
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

        # Superseded-indicator (2026-10-02) — a book override (mode "off"/"custom") shadows the
        # global EQ+balance shown here. Deliberately does NOT name the book: an earlier version
        # quoted the title directly in the note, which could wrap to 2-3 lines for a long title
        # and push the Reset button down (live screenshot, 2026-10-02) — the user already knows
        # which book is loaded, so naming it back adds width-dependent fragility for no real
        # information gain. Fixed phrasing stays one line at this panel's width regardless of
        # which book is open. The toggle/band controls stay ENABLED throughout (only dimmed when
        # the global toggle is Off, below) — editing the global settings while superseded is
        # still a legitimate thing to do (it changes the default every OTHER book, and this
        # book's own "Global" mode if ever switched back to it).
        overridden = self._book_override_active()
        if overridden:
            self.audio_superseded_label.setText("This book has its own EQ. You can change it in Book Detail.")
            self.audio_superseded_label.show()
        else:
            self.audio_superseded_label.hide()

        # Dimmed while the GLOBAL toggle is Off, OR while a book override shadows these controls
        # — either way, nothing happening here is driving current playback right now. Dimming is
        # via QGraphicsOpacityEffect (ClickSlider is fully custom-painted and never reads
        # isEnabled() — see _EQ_DIMMED_OPACITY). setEnabled is tied to the GLOBAL toggle alone
        # (eq_on), NOT to the override — the controls stay genuinely editable while superseded
        # (see the comment above), just visually de-emphasized via opacity only, no setEnabled.
        opacity = 1.0 if (eq_on and not overridden) else _EQ_DIMMED_OPACITY
        for freq, slider in self.eq_sliders.items():
            slider.setEnabled(eq_on)
            self.eq_opacity_effects[freq].setOpacity(opacity)
            self.eq_label_opacity_effects[freq].setOpacity(opacity)
            slider.style().unpolish(slider)
            slider.style().polish(slider)
        self.balance_opacity_effect.setOpacity(opacity)
        self.balance_slider.style().unpolish(self.balance_slider)
        self.balance_slider.style().polish(self.balance_slider)

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


class BookEqualizerTab(QWidget):
    """Book Detail's EQ+balance tab (2026-10-02) — per-book override of Settings > Audio's
    global EQ+balance (voice boost/mono/swap are NOT book-overridable, see TODO.md's scope
    decision). A 3-state mode, not a plain on/off mirror of the global toggle:
      "global" — this book inherits whatever Settings > Audio currently has, live. No book-local
                 gains/balance are read in this state (config.get_book_eq_mode defaults here).
      "off"    — this book never gets EQ/balance processing, even if global is On.
      "custom" — this book uses its OWN gains/balance, set directly on the 5 bands/slider below.
    Visually mirrors AudioSettingsTab's EQ+balance section (same gradient styles, dimming
    mechanism, wheel step) rather than sharing widget instances — the two tabs edit different
    config rows and need independent slider state.
    """
    audio_settings_changed = Signal()  # this book's mode/gains/balance changed; see load_book

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._book_path = None
        self.mode_buttons = {}
        self.eq_sliders = {}
        self.eq_opacity_effects = {}
        self.eq_label_opacity_effects = {}
        self._setup_ui()
        self.update_visuals()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        # State label — plain text, no icon, matching every other state label in this app (see
        # TODO.md's "Book Detail's own state indicator — DECIDED" entry). update_visuals() owns
        # its text; it is never hidden (unlike Settings > Audio's superseded note, which only
        # appears conditionally) — there is always exactly one of three states to report here.
        self.state_label = QLabel("")
        self.state_label.setObjectName("book_eq_state_label")
        self.state_label.setWordWrap(True)
        layout.addWidget(self.state_label)

        mode_row = QHBoxLayout()
        for mode in ["Global", "Off", "Custom"]:
            btn = QPushButton(mode)
            btn.setObjectName("pattern_button")
            btn.clicked.connect(lambda _, m=mode: self._on_mode_clicked(m))
            mode_row.addWidget(btn)
            self.mode_buttons[mode] = btn
        mode_row.addStretch()
        layout.addLayout(mode_row)

        layout.addSpacing(6)
        eq_header = QLabel("Equalizer")
        eq_header.setObjectName("settings_header")
        layout.addWidget(eq_header)

        eq_freqs = [("100", "100"), ("300", "300"), ("1000", "1K"), ("3000", "3K"), ("8000", "8K")]
        for eq_i, (freq, label) in enumerate(eq_freqs):
            eq_row = QHBoxLayout()
            slider = ClickSlider(Qt.Horizontal)
            slider.setObjectName(f"book_eq_slider_{freq}")
            slider.center_mark = True
            slider.snap_to_center = True
            slider.fill_from_center = True
            slider.gradient_style = "eq"
            slider.wheel_step = _SLIDER_WHEEL_STEP
            slider.setRange(-60, 60)
            slider.setValue(0)
            slider.setFixedHeight(10)
            slider.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            slider.valueChanged.connect(lambda v, k=freq: self._on_eq_changed(k, v))
            slider.rightClicked.connect(lambda _ratio, k=freq: self._reset_eq_band(k))
            opacity_effect = QGraphicsOpacityEffect(slider)
            opacity_effect.setOpacity(1.0)
            slider.setGraphicsEffect(opacity_effect)
            self.eq_opacity_effects[freq] = opacity_effect
            eq_row.setSpacing(4)
            eq_row.addWidget(slider, stretch=1, alignment=Qt.AlignmentFlag.AlignVCenter)
            freq_label = QLabel(label)
            freq_label.setObjectName("eq_freq_label")
            freq_label.setFixedWidth(16)
            freq_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            eq_row.addWidget(freq_label, alignment=Qt.AlignmentFlag.AlignVCenter)
            label_opacity_effect = QGraphicsOpacityEffect(freq_label)
            label_opacity_effect.setOpacity(1.0)
            freq_label.setGraphicsEffect(label_opacity_effect)
            self.eq_label_opacity_effects[freq] = label_opacity_effect
            layout.addLayout(eq_row)
            if eq_i < len(eq_freqs) - 1:
                layout.addSpacing(2)
            self.eq_sliders[freq] = slider

        balance_header = QLabel("L/R balance")
        balance_header.setObjectName("settings_header")
        layout.addWidget(balance_header)
        self.balance_slider = ClickSlider(Qt.Horizontal)
        self.balance_slider.setObjectName("book_eq_balance_slider")
        self.balance_slider.center_mark = True
        self.balance_slider.snap_to_center = True
        self.balance_slider.fill_from_center = True
        self.balance_slider.gradient_style = "balance"
        self.balance_slider.wheel_step = _SLIDER_WHEEL_STEP
        self.balance_slider.setRange(-100, 100)
        self.balance_slider.setValue(0)
        self.balance_slider.setFixedHeight(12)
        self.balance_slider.setFixedWidth(140)
        self.balance_slider.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.balance_slider.valueChanged.connect(self._on_balance_changed)
        self.balance_slider.rightClicked.connect(lambda _ratio: self.balance_slider.setValue(0))
        self.balance_opacity_effect = QGraphicsOpacityEffect(self.balance_slider)
        self.balance_opacity_effect.setOpacity(1.0)
        self.balance_slider.setGraphicsEffect(self.balance_opacity_effect)
        layout.addWidget(self.balance_slider)

        layout.addStretch()

    def load_book(self, book_path: str | None) -> None:
        """Called from BookDetailPanel.load_book, same shape as CoverPanel.load_book — loads
        this book's saved mode/gains/balance (or the "global"/0.0 defaults for a book whose EQ
        has never been touched) and repaints every control. Does NOT emit
        audio_settings_changed — that signal is for a user-driven CHANGE while this tab is open
        on a specific book, not for the load itself."""
        self._book_path = book_path
        if book_path is not None:
            gains = {freq: getattr(self.config, f"get_book_eq_gain_{freq}")(book_path)
                     for freq in self.eq_sliders}
            balance = self.config.get_book_balance(book_path)
        else:
            gains = {freq: None for freq in self.eq_sliders}
            balance = None
        for freq, slider in self.eq_sliders.items():
            slider.blockSignals(True)
            slider.setValue(int((gains[freq] or 0.0) * 10))
            slider.blockSignals(False)
        self.balance_slider.blockSignals(True)
        self.balance_slider.setValue(int((balance or 0.0) * 100))
        self.balance_slider.blockSignals(False)
        self.update_visuals()

    def _on_mode_clicked(self, mode: str) -> None:
        if self._book_path is None:
            return
        self.config.set_book_eq_mode(self._book_path, mode.lower())
        self.update_visuals()
        self.audio_settings_changed.emit()

    def _on_eq_changed(self, freq_key, value):
        if self._book_path is None:
            return
        getattr(self.config, f"set_book_eq_gain_{freq_key}")(self._book_path, value / 10.0)
        # Editing a band only makes sense, and only has any effect, in Custom mode — but it does
        # NOT auto-promote Global/Off into Custom. The user drags a slider with an explicit mode
        # already chosen; silently switching modes out from under that choice would be a second,
        # surprising side effect of what looks like a plain value edit. If the mode is NOT
        # Custom, the dragged value is still saved (so it's there if Custom is picked later) but
        # has no audible effect and update_visuals' dimming will reflect that immediately.
        self.update_visuals()
        self.audio_settings_changed.emit()

    def _reset_eq_band(self, freq_key):
        self.eq_sliders[freq_key].setValue(0)

    def _on_balance_changed(self, value):
        if self._book_path is None:
            return
        self.config.set_book_balance(self._book_path, value / 100.0)
        self.update_visuals()
        self.audio_settings_changed.emit()

    def update_visuals(self):
        mode = self.config.get_book_eq_mode(self._book_path) if self._book_path else "global"
        for m, btn in self.mode_buttons.items():
            btn.setProperty("selected", "true" if m.lower() == mode else "false")
            btn.style().unpolish(btn); btn.style().polish(btn)

        state_text = {
            "global": "Using the global EQ",
            "off": "EQ off for this book",
            "custom": "Custom EQ for this book",
        }[mode]
        self.state_label.setText(state_text)

        # Dimmed (not disabled) in every mode except Custom — in Global/Off, these sliders are
        # not what's driving playback (Global defers to Settings > Audio; Off silences
        # everything regardless of slider position), but they stay fully draggable/resettable so
        # a value can be prepared before switching to Custom, same "stays a stable reference,
        # never a layout jump" reasoning as the global EQ's own On/Off dimming.
        opacity = 1.0 if mode == "custom" else _EQ_DIMMED_OPACITY
        for freq, slider in self.eq_sliders.items():
            self.eq_opacity_effects[freq].setOpacity(opacity)
            self.eq_label_opacity_effects[freq].setOpacity(opacity)
            slider.style().unpolish(slider)
            slider.style().polish(slider)
        self.balance_opacity_effect.setOpacity(opacity)
        self.balance_slider.style().unpolish(self.balance_slider)
        self.balance_slider.style().polish(self.balance_slider)