from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGridLayout
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from ..themes import THEMES, preset_ramp_rgb
from mpv import ShutdownError

# Canonical presets shown in the "Default speed" row. When a non-preset default
# is set (e.g. 2.35 via right-clicking the main speed button), it is injected as
# an ephemeral button in sorted position; 3.0x is dropped to make room so the
# row still fits. The injected button is never persisted — only the config value
# decides, at panel-open time, whether injection happens.
CANONICAL_SPEEDS = [1.0, 1.5, 1.75, 2.0, 2.25, 2.5, 3.0]

def _nearest_canonical(val):
    """Snaps val to the nearest canonical preset (within 1e-6), or to the nearest
    integer (within 1e-6) for whole-number speeds outside the canonical list."""
    for c in CANONICAL_SPEEDS:
        if abs(val - c) < 1e-6:
            return c
    rounded = round(val)
    if abs(val - rounded) < 1e-6:
        return float(rounded)
    return val

def get_default_speed_presets(default):
    default = _nearest_canonical(default)
    if default in CANONICAL_SPEEDS:
        return list(CANONICAL_SPEEDS)
    return sorted([s for s in CANONICAL_SPEEDS if s != 3.0] + [default])

class SpeedControlsPanel(QWidget):
    """Handles UI and logic for playback speed, skip intervals, and smart rewind."""
    speed_changed = Signal(float)
    close_requested = Signal()
    skip_duration_changed = Signal(int)

    def __init__(self, player, config, theme_manager, parent=None):
        super().__init__(parent)
        self.player = player
        self.config = config
        self.theme_manager = theme_manager
        self.setObjectName("speed_panel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        
        self._speed_presets = [
            1.00, 1.25, 1.50, 1.75, 2.00, 2.25, 2.50, 2.75, 3.00,
            3.25, 3.50, 4.00
        ]
        self._speed_grid_buttons = []
        self.def_speed_buttons = {}
        self.step_buttons = {}
        self.undo_buttons = {}
        self.skip_buttons = {}
        self.long_skip_buttons = {}
        self.smart_wait_buttons = {}
        self.smart_dur_buttons = {}

        self._setup_ui()
        self.update_visuals()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 10)
        
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
        self._def_row = QHBoxLayout()
        layout.addLayout(self._def_row)
        self._rebuild_def_speed_row()

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

        # Undo Seek Section
        undo_header = QLabel("Undo seek")
        undo_header.setObjectName("settings_header")
        layout.addWidget(undo_header)
        undo_row = QHBoxLayout()
        for val, label in [(0, "Off"), (3, "3"), (5, "5"), (8, "8")]:
            btn = QPushButton(label)
            btn.setObjectName("pattern_button")
            btn.clicked.connect(lambda _, v=val: self._update_undo_mode(v))
            undo_row.addWidget(btn)
            self.undo_buttons[val] = btn
        undo_row.addStretch()
        layout.addLayout(undo_row)

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

        _rewind_on = self.config.get_smart_rewind_wait() > 0
        for val in [10, 20, 30]:
            btn = QPushButton(str(val))
            btn.setObjectName("pattern_button")
            btn.setVisible(_rewind_on)
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
            try:
                self.player.speed = value
            except (ShutdownError, AttributeError, SystemError):
                return
            if save and current_file:
                self.config.set_book_speed(current_file, value)
            self.speed_changed.emit(value)

    @staticmethod
    def _fmt_speed(val):
        """Whole-number speeds keep one decimal so the buttons don't become too thin
        (1.0 -> '1.0x', 2.0 -> '2.0x', 4.0 -> '4.0x'). A fractional injected custom
        shows its natural value (2.35 -> '2.35x', 1.1 -> '1.1x')."""
        if val == int(val):
            return f"{val:.1f}x"
        return f"{('%.2f' % val).rstrip('0').rstrip('.')}x"

    def _rebuild_def_speed_row(self):
        """Rebuilds the Default speed row from the saved config value, injecting a
        custom button when the default is not a canonical preset. Called at panel
        open and whenever the default changes, so the row's evaluation point is
        the config value at that moment — never the previously-shown set."""
        while self._def_row.count():
            item = self._def_row.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self.def_speed_buttons = {}

        default = _nearest_canonical(self.config.get_default_speed())
        for val in get_default_speed_presets(default):
            btn = QPushButton(self._fmt_speed(val))
            btn.setObjectName("pattern_button")
            btn.clicked.connect(lambda _, v=val: self._update_def_speed_mode(v))
            self._def_row.addWidget(btn)
            self.def_speed_buttons[val] = btn
        self._def_row.addStretch()
        self.update_visuals()

    def set_default_speed(self, value):
        """Saves a new default speed and rebuilds the row so a non-preset value is
        injected (replacing any previously-injected custom) and highlighted."""
        self.config.set_default_speed(float(value))
        self._rebuild_def_speed_row()

    def _update_def_speed_mode(self, val): self.config.set_default_speed(val); self.update_visuals()
    def _update_step_mode(self, val): self.config.set_speed_increment(val); self.update_visuals()
    def _update_undo_mode(self, val): 
        self.config.set_undo_duration(val)
        self.update_visuals()

    def _update_skip_mode(self, val): self.config.set_skip_duration(val); self.update_visuals(); self.skip_duration_changed.emit(val)
    def _update_long_skip_mode(self, val): self.config.set_long_skip_duration(val); self.update_visuals()
    def _update_smart_rewind_mode(self, val):
        self.config.set_smart_rewind_wait(val)
        for btn in self.smart_dur_buttons.values():
            btn.setVisible(val > 0)
        self._validate_smart_rewind_settings(finalize=False)
    def _update_smart_rewind_duration(self, val): self.config.set_smart_rewind_duration(val); self._validate_smart_rewind_settings(finalize=False)

    def sync_smart_rewind_visuals(self):
        on = self.config.get_smart_rewind_wait() > 0
        for btn in self.smart_dur_buttons.values():
            btn.setVisible(on)

    def _validate_smart_rewind_settings(self, finalize=False):
        self.update_visuals()

    def _apply_preset_ramp_colors(self):
        """Per-sibling positional color ramp across the 12 speed-preset buttons.

        This is the ONLY part of this panel's coloring that cannot be expressed as
        static QSS: each button's blend ratio depends on its INDEX among its
        siblings (`preset_ramp_rgb(t, i, count)`), not on any fixed selector a
        stylesheet rule could target. Every other button in this panel — all of
        def_speed_buttons/step_buttons/undo_buttons/skip_buttons/long_skip_buttons/
        smart_wait_buttons/smart_dur_buttons — is fully theme-aware via
        get_speed_stylesheet()/get_panel_base_stylesheet() with zero contribution
        from this class. Confirmed by direct measurement, not assumption:
        review/Investigation_260803_c4c5_dispatcher_isolation.md (2026-08-03,
        `23ff3e8`) temporarily disabled this whole panel's dispatcher-bypass call
        and found every OTHER button repainted correctly on a real theme change;
        only these buttons went dark.

        Called on every theme change (via the ThemeManager TAIL, see app.py's
        PanelInterface.update_speed_panel_visuals) AND on every speed/step/undo/
        skip/smart-rewind state change via update_visuals() — the ramp itself
        doesn't depend on selection state, so re-running it on a state change is
        harmless, but a theme change never needs update_visuals()'s property-sync
        half (no selection changed), which is why the two are split into separate
        methods rather than one call always doing both.

        Reads get_committed_theme() (2026-08-04, write-path confinement fix —
        see review/Design_260804_write_path_confinement.md), NOT
        get_current_theme(). update_visuals()'s six state-change callers
        (_update_def_speed_mode/_update_step_mode/_update_undo_mode/
        _update_skip_mode/_update_long_skip_mode/_validate_smart_rewind_settings)
        are ordinary button clicks with no relationship to a theme change, and
        the Speed panel is invisible during any hover (Settings and Speed are
        mutually exclusive panels — see CLAUDE.md). The TAIL caller
        (update_speed_panel_visuals) loses nothing by this change: it only
        ever fires with hover=False (_schedule_deferred_restyle is gated `if
        not hover` at its sole call site), so it never legitimately needed the
        hover-inclusive answer either.
        """
        from ..themes import _resolve_theme
        t = _resolve_theme(self.theme_manager.get_committed_theme())
        btn_text = t.get('button_text', t.get('text_on_light_bg', t['text']))

        for i, btn in enumerate(self._speed_grid_buttons):
            # OPAQUE ramp (2026-07-28). This used to set an ALPHA ramp
            # (75..255) on the accent, which made the low buttons ~29% opaque and
            # let whatever sits behind the panel show through them — with a
            # translucent panel the cover art was legible inside the button grid.
            # preset_ramp_rgb blends the same progression in colour space instead:
            # identical look, no bleed. See its docstring for the full mechanism.
            c = QColor(*(int(v) for v in
                         preset_ramp_rgb(t, i, len(self._speed_presets)).split(',')))
            # Per-instance setStyleSheet (needed for the per-button ramp) wins over
            # the panel-level QPushButton:hover/:pressed QSS, so those states must be
            # reproduced here explicitly or these buttons never visibly react to
            # hover/press (found live 2026-07-21 — same shape as the sleep panel's
            # time-preset ramp, see sleep_timer.py's update_panel_styling).
            hover_c = c.lighter(130)
            pressed_c = c.darker(130)
            btn.setStyleSheet(
                f"QPushButton {{ background-color: rgb({c.red()}, {c.green()}, {c.blue()}); "
                f"color: {btn_text}; border: none; }}"
                f"QPushButton:hover {{ background-color: rgb({hover_c.red()}, {hover_c.green()}, {hover_c.blue()}); }}"
                f"QPushButton:pressed {{ background-color: rgb({pressed_c.red()}, {pressed_c.green()}, {pressed_c.blue()}); }}"
            )

    def update_visuals(self, theme_name=None):
        """Full sync: the ramp (see _apply_preset_ramp_colors) plus every
        pattern_button group's selected Qt PROPERTY. Their base colors are pure
        dispatcher QSS (get_speed_stylesheet's pattern_button rules) — this
        method's job for them is only to mark which one is currently selected and
        force Qt to repolish, since a property change alone doesn't repaint.
        Called from every state-change site in this class (_update_def_speed_mode/
        _update_step_mode/_update_undo_mode/_update_skip_mode/
        _update_long_skip_mode/_validate_smart_rewind_settings); NOT called from
        the theme-apply path (see app.py's PanelInterface.update_speed_panel_visuals,
        which calls _apply_preset_ramp_colors alone — a theme change never changes
        which preset is selected, so the property-sync half here would be
        redundant work on that path).

        theme_name is accepted but unused (matches update_speed_panel_visuals'
        call signature); _apply_preset_ramp_colors always reads the COMMITTED
        theme itself (theme_manager.get_committed_theme(), not
        get_current_theme() — see that method's docstring, 2026-08-04 write-
        path confinement fix) regardless of what's passed here."""
        self._apply_preset_ramp_colors()

        def sync_btn(group, current):
            for val, btn in group.items():
                btn.setProperty("selected", "true" if round(float(val), 9) == round(float(current), 9) else "false")
                btn.style().unpolish(btn); btn.style().polish(btn)

        sync_btn(self.def_speed_buttons, self.config.get_default_speed())
        sync_btn(self.step_buttons, self.config.get_speed_increment())
        sync_btn(self.undo_buttons, self.config.get_undo_duration())
        sync_btn(self.skip_buttons, self.config.get_skip_duration())
        sync_btn(self.long_skip_buttons, self.config.get_long_skip_duration())
        sync_btn(self.smart_wait_buttons, self.config.get_smart_rewind_wait())
        sync_btn(self.smart_dur_buttons, self.config.get_smart_rewind_duration())

        # Ensure the panel's own background is refreshed
        self.style().unpolish(self); self.style().polish(self)
