import time
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGridLayout, QLineEdit
from PySide6.QtCore import Qt, QRegularExpression, Signal, QTimer
from PySide6.QtGui import QRegularExpressionValidator, QColor
from ..themes import preset_ramp_rgb
from ..player import _CHAPTER_WALK_TOLERANCE
from .title_bar import RightClickButton
from mpv import ShutdownError
from .line_edit_dragfix import DragSafeLineEdit

class SleepTimerPanel(QWidget):
    timer_started = Signal()
    timer_stopped = Signal()
    timer_expired = Signal()  # fired only when the timer fires and pauses playback
    display_text_updated = Signal(str)

    def __init__(self, player, config, theme_manager, parent=None, dismiss_ms=2000):
        super().__init__(parent)
        self.player = player
        self.config = config
        self.theme_manager = theme_manager
        self.setObjectName("sleep_panel")
        self.setAttribute(Qt.WA_StyledBackground, True)

        self._sleep_timer_end_time = None # Unix timestamp when sleep timer should end
        self._sleep_mode = None # 'timed', 'end_of_chapter'
        self._total_timer_duration = 0 # Initial duration in seconds for the active timer
        self._current_sleep_fade = self.config.get_sleep_fade_duration()
        # End-of-chapter mode: the chapter index sleep was armed on. Forward navigation
        # past this anchor cancels sleep instead of letting it fire on whatever chapter
        # is current; backward navigation (or staying put) keeps the anchor live. See
        # _on_chapter_changed / _cancel_eoc_sleep.
        self._sleep_eoc_anchor = None
        # True while the "Sleep cancelled" confirmation is showing — update_timer_state
        # must not touch display_text_updated during this window, or its own unconditional
        # per-tick emit (every 200ms) stomps the message back to "" almost immediately.
        self._eoc_cancel_message_active = False
        # Shared with app.py's _INDICATOR_DISMISS_MS — how long the "Sleep cancelled"
        # message shows in the indicator zone before clearing.
        self._dismiss_ms = dismiss_ms
        self._eoc_cancel_timer = QTimer(self)
        self._eoc_cancel_timer.setSingleShot(True)
        self._eoc_cancel_timer.timeout.connect(self._on_eoc_cancel_timeout)
        self.player.chapter_changed.connect(self._on_chapter_changed)

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 10)
        
        sleep_header = QLabel("Sleep timer")
        sleep_header.setObjectName("settings_header")
        layout.addWidget(sleep_header)

        # Time Presets Grid
        grid = QGridLayout()
        grid.setSpacing(8)
        presets_minutes = [2, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 90]
        self._sleep_presets_buttons = []
        for i, val in enumerate(presets_minutes):
            btn = QPushButton(f"{val} min")
            btn.setFixedSize(57, 30)
            btn.clicked.connect(lambda _, v=val: self.set_sleep_timer(duration_minutes=v))
            grid.addWidget(btn, i // 4, i % 4)
            self._sleep_presets_buttons.append(btn)

        self.end_chap_btn = QPushButton("End of chapter")
        self.end_chap_btn.setFixedHeight(30)
        self.end_chap_btn.clicked.connect(lambda: self.set_sleep_timer(mode='end_of_chapter'))
        grid.addWidget(self.end_chap_btn, 3, 2, 1, 2)
        layout.addLayout(grid)
        layout.addSpacing(2)
        

        # Custom time input
        custom_time_layout = QHBoxLayout()
        self.custom_sleep_input = DragSafeLineEdit()
        self.custom_sleep_input.setPlaceholderText("min")
        self.custom_sleep_input.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.custom_sleep_input.customContextMenuRequested.connect(lambda _: self.custom_sleep_input.clear())
        self.custom_sleep_input.setFixedWidth(50)
        self.custom_sleep_input.setValidator(QRegularExpressionValidator(QRegularExpression("[1-9][0-9]{0,2}"), self))
        def _sleep_input_key(e):
            if e.key() == Qt.Key.Key_Escape:
                self.custom_sleep_input.clear()
                self.custom_sleep_input.clearFocus()
            else:
                QLineEdit.keyPressEvent(self.custom_sleep_input, e)
        self.custom_sleep_input.keyPressEvent = _sleep_input_key
        custom_time_layout.addWidget(self.custom_sleep_input)

        set_custom_btn = QPushButton("Set")
        set_custom_btn.setFixedHeight(25)
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
            btn.setObjectName("pattern_button")
            btn.setFixedSize(45, 25)
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
            try:
                self.player.pause = False
            except (ShutdownError, AttributeError, SystemError):
                pass

        if duration_minutes is not None:
            self._total_timer_duration = duration_minutes * 60
            self._sleep_timer_end_time = time.time() + duration_minutes * 60
            self._sleep_mode = 'timed'
            self.config.set_sleep_duration(duration_minutes)
            self.config.set_sleep_mode('timed')
            self.disable_sleep_btn.show()
            self.timer_started.emit()
        elif mode == 'end_of_chapter':
            self._total_timer_duration = 0
            self._sleep_mode = mode
            self._sleep_eoc_anchor = self._current_chapter_index()
            self.config.set_sleep_mode(mode)
            self.disable_sleep_btn.show()
            self.timer_started.emit()

        self.update_panel_styling()

    def _current_chapter_index(self):
        """Derives the current chapter index the same way Player._on_time_pos_change
        does (same _CHAPTER_WALK_TOLERANCE), for arming the end-of-chapter anchor."""
        chaps = self.player.chapter_list or []
        pos = self.player.time_pos or 0.0
        curr = 0
        for i, chap in enumerate(chaps):
            if chap.get('time', 0) <= pos + _CHAPTER_WALK_TOLERANCE:
                curr = i
        return curr

    def disable_sleep_timer(self):
        was_active = self._sleep_timer_end_time is not None or self._sleep_mode is not None
        self._sleep_timer_end_time = None
        self._sleep_mode = None
        self._sleep_eoc_anchor = None
        self._eoc_cancel_timer.stop()
        self._eoc_cancel_message_active = False
        self.disable_sleep_btn.hide()
        if was_active:
            self.timer_stopped.emit()
        self.display_text_updated.emit("")
        self.update_panel_styling()

    def _on_chapter_changed(self, index):
        """Connected to Player.chapter_changed — the single universal chapter-index
        signal (see CLAUDE.md invariant 25 / _on_time_pos_change). Only end-of-chapter
        mode cares. Natural sequential playback only ever advances the derived index
        by exactly one step at a time (_on_time_pos_change walks chapter_list in
        order), so an anchor -> anchor+1 transition is always arrival, never a jump —
        that case is left entirely to update_timer_state's own boundary-fire check,
        which disarms sleep before this (queued, cross-thread) signal is even
        processed. Only a jump of 2+ chapters in one step — a chapter-list click,
        Next-button skip, or seek that lands past the anchor's immediate end — is
        unambiguously a user action and cancels here. Backward navigation (or
        staying within the anchor chapter) leaves sleep armed either way."""
        if self._sleep_mode != 'end_of_chapter' or self._sleep_eoc_anchor is None:
            return
        if index > self._sleep_eoc_anchor + 1:
            self._cancel_eoc_sleep()

    def _cancel_eoc_sleep(self):
        """A chapter jump carried playback past the end-of-chapter anchor (see
        _on_chapter_changed — this never fires for natural +1 arrival). Disarms
        sleep via the normal user-cancel path, then shows a "Sleep cancelled"
        confirmation in the indicator zone for _dismiss_ms. The two
        display_text_updated emits below must stay as separate, ordered calls:
        the first (empty string, from disable_sleep_timer) clears the label so
        the second ("Sleep cancelled") is read as a fresh, non-empty transition
        by _on_sleep_display_text_updated's own newly-armed-while-muted check —
        that's what makes the message show even if the user is currently muted,
        with no separate override path needed here. _eoc_cancel_message_active
        must be set before update_timer_state's next 200ms tick can run, or its
        unconditional display_text_updated emit stomps this message almost
        immediately — see update_timer_state's own guard."""
        self.disable_sleep_timer()
        self._eoc_cancel_message_active = True
        self.display_text_updated.emit("Sleep cancelled")
        self._eoc_cancel_timer.start(self._dismiss_ms)

    def _on_eoc_cancel_timeout(self):
        self._eoc_cancel_message_active = False
        self.display_text_updated.emit("")

    def set_sleep_fade(self, seconds, save=False):
        self._current_sleep_fade = seconds
        if save:
            self.config.set_sleep_fade_duration(seconds)
        self.update_panel_styling()

    def _apply_preset_ramp_colors(self):
        """Per-sibling positional color ramp across the 14 duration-preset buttons.

        This is the ONLY part of this panel's coloring that cannot be expressed as
        static QSS: each button's blend ratio depends on its INDEX among its
        siblings (`preset_ramp_rgb(t, i, count)`), not on any fixed selector a
        stylesheet rule could target. Everything else in this panel — end_chap_btn,
        set_custom_btn, the fade buttons' base colors, disable_sleep_btn — is fully
        theme-aware via get_sleep_stylesheet()/get_panel_base_stylesheet() with zero
        contribution from this class. Confirmed by direct measurement, not
        assumption: review/Investigation_260803_c4c5_dispatcher_isolation.md
        (2026-08-03, `23ff3e8`) temporarily disabled this whole panel's dispatcher-
        bypass call and found every OTHER button repainted correctly on a real
        theme change; only these buttons went dark.

        Called on every theme change (via the ThemeManager TAIL, see app.py's
        PanelInterface.update_sleep_panel_visuals) AND on every fade/timer state
        change via update_panel_styling() — the ramp itself doesn't depend on
        selection state, so re-running it on a state change is harmless, but a
        theme change never needs update_panel_styling()'s property-sync half
        (selection didn't change), which is why the two are split into separate
        methods rather than one call always doing both.

        Reads get_committed_theme() (2026-08-04, write-path confinement fix —
        see review/Design_260804_write_path_confinement.md), NOT
        get_current_theme(). update_panel_styling()'s three state-change
        callers (set_sleep_timer/disable_sleep_timer/set_sleep_fade) are
        ordinary button clicks with no relationship to a theme change, and the
        Sleep panel is invisible during any hover (Settings and Sleep are
        mutually exclusive panels — see CLAUDE.md). The TAIL caller
        (update_sleep_panel_visuals) loses nothing by this change: it only
        ever fires with hover=False, so it never legitimately needed the
        hover-inclusive answer either.
        """
        from ..themes import _resolve_theme
        t = _resolve_theme(self.theme_manager.get_committed_theme())
        btn_text = t.get('button_text', t.get('text_on_light_bg', t['text']))

        for i, btn in enumerate(self._sleep_presets_buttons):
            # OPAQUE ramp (2026-07-28). This used to set an ALPHA ramp (75..255) on
            # the accent, which made the low buttons ~29% opaque and let whatever
            # sits behind the panel show through them — with a translucent panel the
            # cover art was legible inside the button grid. preset_ramp_rgb blends
            # the same progression in colour space instead: identical look, no
            # bleed. See its docstring for the full mechanism.
            c = QColor(*(int(v) for v in
                         preset_ramp_rgb(t, i, len(self._sleep_presets_buttons)).split(',')))
            # Per-instance setStyleSheet (needed for the per-button ramp) wins over
            # the panel-level QPushButton:hover/:pressed QSS, so those states must be
            # reproduced here explicitly or these buttons never visibly react to
            # hover/press (found live 2026-07-21 — the ramp had silently had no
            # hover state since it was introduced).
            hover_c = c.lighter(130)
            pressed_c = c.darker(130)
            btn.setStyleSheet(
                f"QPushButton {{ background-color: rgb({c.red()}, {c.green()}, {c.blue()}); "
                f"color: {btn_text}; border: none; }}"
                f"QPushButton:hover {{ background-color: rgb({hover_c.red()}, {hover_c.green()}, {hover_c.blue()}); }}"
                f"QPushButton:pressed {{ background-color: rgb({pressed_c.red()}, {pressed_c.green()}, {pressed_c.blue()}); }}"
            )

    def update_panel_styling(self):
        """Full sync: the ramp (see _apply_preset_ramp_colors) plus the fade
        buttons' selected/is_default Qt PROPERTIES. The fade buttons' base colors
        are pure dispatcher QSS (get_sleep_stylesheet's pattern_button rules) —
        this method's job for them is only to set which one is currently
        selected/default and force Qt to repolish, since a property change alone
        doesn't repaint. Called from every state-change site in this class
        (set_sleep_timer/disable_sleep_timer/set_sleep_fade); NOT called from the
        theme-apply path (see app.py's PanelInterface.update_sleep_panel_visuals,
        which calls _apply_preset_ramp_colors alone — a theme change never changes
        which fade option is selected, so the property-sync half here would be
        redundant work on that path)."""
        default_fade = self.config.get_sleep_fade_duration()

        self._apply_preset_ramp_colors()

        for i, (seconds, btn) in enumerate(self._sleep_fade_btns.items()):
            is_active = (seconds == self._current_sleep_fade)
            is_default = (seconds == default_fade)

            btn.setProperty("selected", "true" if is_active else "false")
            btn.setProperty("is_default", "true" if is_default else "false")

            # Trigger style refresh for property changes
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        # Refresh the panel's own style to ensure background is updated
        self.style().unpolish(self); self.style().polish(self)

    def update_timer_state(self, current_time, is_paused, player_pos, player_dur, is_eof):
        if not self.player:
            return
        if self._eoc_cancel_message_active:
            # A "Sleep cancelled" confirmation is showing (see _cancel_eoc_sleep /
            # _on_eoc_cancel_timeout). Sleep is already disarmed, so there is nothing
            # for this method to drive — the unconditional display_text_updated emit
            # further down would otherwise stomp the message back to "" on the very
            # next 200ms tick, well before its own dismiss timer elapses.
            return
        display_text = ""

        # Reset fade ratio by default; it will be overwritten below if fading
        self.player.set_fade_ratio(1.0)

        if self._sleep_timer_end_time is not None:
            remaining_raw = self._sleep_timer_end_time - current_time
            remaining_seconds = max(0, int(remaining_raw))
            if remaining_raw <= 0 or is_eof:
                self.disable_sleep_timer()
                try:
                    self.player.pause = True
                except (ShutdownError, AttributeError, SystemError):
                    pass
                self.timer_expired.emit()
            else:
                display_text = f"[{self.player.format_time(remaining_seconds)}]"
                # Volume Fade Logic
                # Cap the fade duration at the total length of the timer to prevent low starting volume
                effective_fade = min(self._current_sleep_fade, self._total_timer_duration)
                if effective_fade > 0 and remaining_seconds <= effective_fade:
                    ratio = remaining_seconds / effective_fade
                    self.player.set_fade_ratio(ratio)

        elif self._sleep_mode == 'end_of_chapter':
            display_text = "[chapter]"
            if not is_paused and self._sleep_eoc_anchor is not None:
                if not player_dur:
                    return
                # Fire only when position reaches the ANCHOR chapter's own end boundary —
                # not "whatever chapter is current". Forward navigation past the anchor is
                # handled separately by _on_chapter_changed, which cancels sleep before this
                # branch would ever see a later chapter's position.
                chaps = self.player.chapter_list or []
                anchor = self._sleep_eoc_anchor
                if chaps and anchor < len(chaps) - 1:
                    anchor_end = chaps[anchor + 1].get('time', player_dur)
                    reached_end = player_pos >= anchor_end - 0.5 or is_eof
                else:
                    anchor_end = player_dur
                    reached_end = player_pos >= player_dur - 0.5 or is_eof
                if reached_end:
                    self.disable_sleep_timer()
                    try:
                        self.player.pause = True
                    except (ShutdownError, AttributeError, SystemError):
                        pass
                    self.timer_expired.emit()
        self.display_text_updated.emit(display_text)
