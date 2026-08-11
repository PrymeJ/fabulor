import math
import time
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGridLayout, QLineEdit
from PySide6.QtCore import Qt, QRegularExpression, Signal, QTimer
from PySide6.QtGui import QRegularExpressionValidator, QColor
from ..themes import preset_ramp_rgb
from mpv import ShutdownError
from .line_edit_dragfix import DragSafeLineEdit


class _ClickableLabel(QLabel):
    """Same shape as book_detail_panel.py's private _ClickableLabel — a QLabel
    that emits a real Signal on left-click, for the confirm-overlay pattern used
    across this codebase (Delete listening history, Reset all stats, etc.).
    Kept as a local copy rather than imported, matching how each panel in this
    codebase already implements this pattern independently."""
    clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class SprintPanel(QWidget):
    sprint_started = Signal()
    sprint_stopped = Signal()
    sprint_expired = Signal()  # fired only on natural completion, not cancel
    display_text_updated = Signal(str)

    def __init__(self, player, config, theme_manager, parent=None, dismiss_ms=2000):
        super().__init__(parent)
        self.player = player
        self.config = config
        self.theme_manager = theme_manager
        self.setObjectName("sprint_panel")
        self.setAttribute(Qt.WA_StyledBackground, True)

        self._sprint_duration_s = None   # total sprint seconds (int)
        # time.time()-based (NOT monotonic) — must match update_sprint_state's
        # current_time parameter, which app.py always sources from time.time().
        # See _do_arm_sprint's comment for why this is load-bearing.
        self._sprint_start_time = None   # time.time() at arm time
        self._sprint_paused_at = None    # time.time() when pause began
        self._grace_pool_s = None        # total grace seconds for the active sprint (int)
        self._grace_used_s = 0.0         # cumulative pause seconds consumed
        self._sprint_active = False
        # True while "Sprint failed"/"Sprint completed" is showing — update_sprint_state
        # must not touch display_text_updated during this window, or its own per-tick emit
        # would stomp the message back to "" almost immediately. Same shape as sleep's
        # _eoc_cancel_message_active (see ui/sleep_timer.py).
        self._cancel_message_active = False
        # Grace mode selector + per-mode settings, config-backed (see config.py's
        # sprint_grace_* keys). _grace_pool_s is computed FROM these at arm time
        # (_do_arm_sprint), not stored directly — mirrors the mode/value split so
        # switching modes never loses the other modes' last-entered values.
        self._grace_mode = self.config.get_sprint_grace_mode()
        self._grace_percentage = self.config.get_sprint_grace_percentage()
        self._grace_fixed_s = self.config.get_sprint_grace_fixed_s()
        self._grace_custom_s = self.config.get_sprint_grace_custom_s()
        # Shared with app.py's _INDICATOR_DISMISS_MS — how long "Sprint failed"/
        # "Sprint completed" show in the indicator zone before clearing.
        self._dismiss_ms = dismiss_ms
        self._cancel_timer = QTimer(self)
        self._cancel_timer.setSingleShot(True)
        self._cancel_timer.timeout.connect(self._on_cancel_message_timeout)
        # Optional external gate, set by app.py via set_arm_gate(). Takes a single
        # zero-arg callable (`proceed`) and either calls it immediately or defers
        # it behind a confirm UI (see show_conflict_confirm). Defaults to None,
        # meaning arm calls proceed with no gating — this panel has no built-in
        # awareness of any other panel (e.g. sleep); app.py owns that policy.
        self._arm_gate = None
        self._conflict_confirm_timer = QTimer(self)
        self._conflict_confirm_timer.setSingleShot(True)
        self._conflict_confirm_timer.timeout.connect(self._on_conflict_confirm_timeout)
        self._conflict_on_confirm = None

        self._setup_ui()

    def set_arm_gate(self, gate_fn):
        """gate_fn(proceed) is called instead of arming directly whenever
        set_sprint() is invoked. gate_fn must eventually call proceed() (now,
        later via a confirm click, or never if the user lets it time out/cancel)."""
        self._arm_gate = gate_fn

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 10)

        sprint_header = QLabel("Listening sprint")
        sprint_header.setObjectName("settings_header")
        layout.addWidget(sprint_header)

        # Duration presets grid
        grid = QGridLayout()
        grid.setSpacing(8)
        presets_minutes = [5, 10, 15, 20, 25, 30, 45, 60, 90, 120]
        self._sprint_presets_buttons = []
        for i, val in enumerate(presets_minutes):
            btn = QPushButton(f"{val} min")
            btn.setFixedSize(57, 30)
            btn.clicked.connect(lambda _, v=val: self.set_sprint(duration_minutes=v))
            grid.addWidget(btn, i // 4, i % 4)
            self._sprint_presets_buttons.append(btn)
        layout.addLayout(grid)
        layout.addSpacing(2)

        # Custom time input
        custom_time_layout = QHBoxLayout()
        self.custom_sprint_input = DragSafeLineEdit()
        self.custom_sprint_input.setPlaceholderText("min")
        self.custom_sprint_input.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.custom_sprint_input.customContextMenuRequested.connect(lambda _: self.custom_sprint_input.clear())
        self.custom_sprint_input.setFixedWidth(50)
        self.custom_sprint_input.setValidator(QRegularExpressionValidator(QRegularExpression("[1-9][0-9]{0,2}"), self))
        self.custom_sprint_input.returnPressed.connect(self._on_custom_sprint_time_set)
        def _sprint_input_key(e):
            if e.key() == Qt.Key.Key_Escape:
                self.custom_sprint_input.clear()
                self.custom_sprint_input.clearFocus()
            else:
                QLineEdit.keyPressEvent(self.custom_sprint_input, e)
        self.custom_sprint_input.keyPressEvent = _sprint_input_key
        custom_time_layout.addWidget(self.custom_sprint_input)

        set_custom_btn = QPushButton("Set")
        set_custom_btn.setFixedHeight(25)
        set_custom_btn.clicked.connect(self._on_custom_sprint_time_set)
        custom_time_layout.addWidget(set_custom_btn)
        custom_time_layout.addStretch()
        layout.addLayout(custom_time_layout)

        # Grace period options — two-tier mode selector + submenu, matching the
        # instant show/hide (no animation) convention used for conditionally-visible
        # settings sub-rows elsewhere in this app.
        grace_header = QLabel("Grace period")
        grace_header.setObjectName("settings_header")
        layout.addWidget(grace_header)

        mode_layout = QHBoxLayout()
        mode_layout.setSpacing(5)
        self._grace_mode_btns = {}
        for mode, text in [("percentage", "Percentage"), ("fixed", "Fixed"),
                            ("custom", "Custom"), ("none", "None")]:
            btn = QPushButton(text)
            btn.setObjectName("pattern_button")
            # Natural width/height — no setFixedSize/setFixedHeight. Unlike the
            # preset buttons (2%/5%/... and 5s/10s/...), these size to their text.
            btn.clicked.connect(lambda _, m=mode: self._set_grace_mode(m))
            mode_layout.addWidget(btn)
            self._grace_mode_btns[mode] = btn
        mode_layout.addStretch()
        layout.addLayout(mode_layout)

        self._grace_submenu = QWidget()
        submenu_layout = QVBoxLayout(self._grace_submenu)
        submenu_layout.setContentsMargins(0, 4, 0, 0)
        submenu_layout.setSpacing(0)

        # Percentage preset row — 6 buttons at 36px/7px spacing = 251px, measured
        # live against the row's actual available width (45px/8px, the grid's own
        # sizing, was too wide for 6 buttons and overflowed the panel).
        self._grace_pct_row = QWidget()
        pct_layout = QHBoxLayout(self._grace_pct_row)
        pct_layout.setContentsMargins(0, 0, 0, 0)
        pct_layout.setSpacing(3)
        self._grace_pct_btns = {}
        for pct in (2, 5, 10, 15, 20, 25):
            btn = QPushButton(f"{pct}%")
            btn.setObjectName("pattern_button")
            btn.setFixedSize(39, 25)
            btn.clicked.connect(lambda _, p=pct: self._set_grace_percentage(p))
            pct_layout.addWidget(btn)
            self._grace_pct_btns[pct] = btn
        submenu_layout.addWidget(self._grace_pct_row)

        # Fixed preset row — same 36px/7px sizing as the percentage row above.
        self._grace_fixed_row = QWidget()
        fixed_layout = QHBoxLayout(self._grace_fixed_row)
        fixed_layout.setContentsMargins(0, 0, 0, 0)
        fixed_layout.setSpacing(3)
        self._grace_fixed_btns = {}
        for seconds in (5, 10, 15, 30, 45, 60):
            btn = QPushButton(f"{seconds}s")
            btn.setObjectName("pattern_button")
            btn.setFixedSize(39, 25)
            btn.clicked.connect(lambda _, s=seconds: self._set_grace_fixed(s))
            fixed_layout.addWidget(btn)
            self._grace_fixed_btns[seconds] = btn
        submenu_layout.addWidget(self._grace_fixed_row)

        # Custom input row — same Escape-clears/right-click-clears/Set-button shape
        # as the custom sprint-duration input above; also commits on Enter via
        # returnPressed (kept in addition to the Set button, per explicit
        # instruction — the sprint-duration input and SleepTimerPanel's
        # custom_sleep_input gained the same returnPressed wiring in this pass).
        self._grace_custom_row = QWidget()
        custom_grace_layout = QHBoxLayout(self._grace_custom_row)
        custom_grace_layout.setContentsMargins(0, 0, 0, 0)
        self.custom_grace_input = DragSafeLineEdit()
        self.custom_grace_input.setPlaceholderText("sec")
        self.custom_grace_input.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.custom_grace_input.customContextMenuRequested.connect(lambda _: self.custom_grace_input.clear())
        self.custom_grace_input.setFixedWidth(50)
        self.custom_grace_input.setValidator(QRegularExpressionValidator(QRegularExpression("[1-9][0-9]{0,2}"), self))
        self.custom_grace_input.returnPressed.connect(self._on_custom_grace_set)

        def _grace_input_key(e):
            if e.key() == Qt.Key.Key_Escape:
                self.custom_grace_input.clear()
                self.custom_grace_input.clearFocus()
            else:
                DragSafeLineEdit.keyPressEvent(self.custom_grace_input, e)
        self.custom_grace_input.keyPressEvent = _grace_input_key
        custom_grace_layout.addWidget(self.custom_grace_input)

        set_custom_grace_btn = QPushButton("Set")
        set_custom_grace_btn.setFixedHeight(25)
        set_custom_grace_btn.clicked.connect(self._on_custom_grace_set)
        custom_grace_layout.addWidget(set_custom_grace_btn)
        custom_grace_layout.addStretch()
        submenu_layout.addWidget(self._grace_custom_row)

        layout.addWidget(self._grace_submenu)
        self._sync_grace_submenu_visibility()

        # Disable button
        layout.addSpacing(20)
        self.disable_sprint_btn = QPushButton("Cancel the sprint")
        self.disable_sprint_btn.setObjectName("disable_sprint_btn")
        self.disable_sprint_btn.clicked.connect(self.disable_sprint)
        self.disable_sprint_btn.hide()
        layout.addWidget(self.disable_sprint_btn)

        # Conflict confirmation (shown via show_conflict_confirm when app.py's
        # arm gate detects sleep is active). Same shape as book_detail_panel.py's
        # "Delete listening history" confirm label — a hidden QLabel toggled via
        # setVisible, confirmed by a real click rather than the trigger button
        # being re-clicked.
        self._conflict_confirm_label = _ClickableLabel("")
        self._conflict_confirm_label.setObjectName("sprint_conflict_confirm")
        self._conflict_confirm_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._conflict_confirm_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._conflict_confirm_label.setFixedHeight(28)
        self._conflict_confirm_label.clicked.connect(self._on_conflict_confirm_clicked)
        self._conflict_confirm_label.hide()
        layout.addWidget(self._conflict_confirm_label)

        layout.addStretch()

        # Sync the grace mode/preset buttons' selected state to the config values
        # just loaded in __init__. Without this, the persisted mode (e.g. "fixed")
        # is correctly reflected in which submenu row is visible (that's driven by
        # _sync_grace_submenu_visibility() above, called unconditionally) but no
        # mode button shows as selected until the user clicks one — the two calls
        # that normally do this (update_sprint_panel_visuals' theme-apply pass)
        # only run _apply_preset_ramp_colors(), not the full selected-property
        # sync. Reported live: "submenu selections persist, but... the main
        # selection is gone" on every restart (2026-08-11).
        self.update_panel_styling()

    def _on_custom_sprint_time_set(self):
        try:
            text = self.custom_sprint_input.text()
            if text:
                minutes = int(text)
                if minutes > 0:
                    self.set_sprint(duration_minutes=minutes)
        except ValueError:
            pass

    def _set_grace_mode(self, mode):
        self._grace_mode = mode
        self.config.set_sprint_grace_mode(mode)
        self._sync_grace_submenu_visibility()
        self.update_panel_styling()

    def _sync_grace_submenu_visibility(self):
        """Instant show/hide, no animation. Child-row visibility MUST be settled
        BEFORE the container is shown — showing the container first let it briefly
        paint at the previous mode's size/position before the correct row's
        setVisible(True) landed, causing a visible flicker on None -> Percentage/
        Fixed. So: set all three child rows first, then show/hide the container
        last."""
        self._grace_pct_row.setVisible(self._grace_mode == "percentage")
        self._grace_fixed_row.setVisible(self._grace_mode == "fixed")
        self._grace_custom_row.setVisible(self._grace_mode == "custom")
        if self._grace_mode == "none":
            self._grace_submenu.hide()
        else:
            self._grace_submenu.show()

    def _set_grace_percentage(self, pct):
        self._grace_percentage = pct
        self.config.set_sprint_grace_percentage(pct)
        self.update_panel_styling()

    def _set_grace_fixed(self, seconds):
        self._grace_fixed_s = seconds
        self.config.set_sprint_grace_fixed_s(seconds)
        self.update_panel_styling()

    def _on_custom_grace_set(self):
        try:
            text = self.custom_grace_input.text()
            if text:
                seconds = int(text)
                if seconds > 0:
                    self._grace_custom_s = seconds
                    self.config.set_sprint_grace_custom_s(seconds)
        except ValueError:
            pass

    @property
    def is_active(self):
        return self._sprint_active

    def set_arm_gate(self, gate_fn):
        """gate_fn(proceed) is called instead of arming directly whenever
        set_sprint() is invoked. gate_fn must eventually call proceed() (now,
        later via a confirm click, or never if the user lets it time out/cancel).
        Defaults to None (no gate set), meaning arm calls proceed immediately —
        this panel has no built-in awareness of any other panel; app.py owns
        that policy entirely."""
        self._arm_gate = gate_fn

    def show_conflict_confirm(self, message, on_confirm):
        """Shows a click-to-confirm overlay with the given message; on_confirm is
        called (with no arguments) if the user clicks it before the timeout, or
        silently dropped on timeout (matching every confirm pattern in this
        codebase — Delete listening history, Reset all stats). Uses a fixed 7s
        window, the same literal every other confirm-overlay uses — NOT
        _dismiss_ms, which is the much shorter "Sprint failed" MESSAGE
        display window, a different concept entirely."""
        self._conflict_on_confirm = on_confirm
        self._conflict_confirm_label.setText(message)
        self._conflict_confirm_label.show()
        self._conflict_confirm_timer.start(7000)

    def _on_conflict_confirm_clicked(self):
        self._conflict_confirm_timer.stop()
        self._conflict_confirm_label.hide()
        callback = self._conflict_on_confirm
        self._conflict_on_confirm = None
        if callback:
            callback()

    def _on_conflict_confirm_timeout(self):
        self._conflict_confirm_label.hide()
        self._conflict_on_confirm = None

    def set_sprint(self, duration_minutes=None):
        if not duration_minutes or duration_minutes <= 0:
            return
        proceed = lambda: self._do_arm_sprint(duration_minutes)
        if self._arm_gate:
            self._arm_gate(proceed)
        else:
            proceed()

    def _do_arm_sprint(self, duration_minutes):
        self._sprint_duration_s = duration_minutes * 60
        if self._grace_mode == "percentage":
            self._grace_pool_s = math.ceil(self._sprint_duration_s * self._grace_percentage / 100)
        elif self._grace_mode == "fixed":
            self._grace_pool_s = self._grace_fixed_s
        elif self._grace_mode == "custom":
            self._grace_pool_s = self._grace_custom_s if self._grace_custom_s > 0 else 0
        else:  # "none"
            self._grace_pool_s = 0
        self._sprint_paused_at = None
        self._grace_used_s = 0.0
        # time.time(), NOT time.monotonic() — update_sprint_state's current_time
        # parameter comes from app.py's _sync_playback_state, which is always
        # time.time()-based (matches sleep_timer.py's own _sleep_timer_end_time
        # convention). Using monotonic() here computed elapsed as
        # time.time() - time.monotonic() — two incompatible clocks — which
        # instantly exceeded any sprint duration and fired completion on the
        # very first tick after arming. Confirmed live 2026-08-10.
        self._sprint_start_time = time.time()
        self._sprint_active = True
        if self.player:
            try:
                self.player.pause = False
            except (ShutdownError, AttributeError, SystemError):
                pass
        self.update_panel_styling()
        # disable_sprint_btn.show() is deliberately NOT called here — see
        # SleepTimerPanel._do_arm_sleep_timer's comment for the full mechanism
        # (a same-call-stack reorder does not work: Qt doesn't paint between two
        # Python statements, so the button flashes before the close-slide
        # regardless of emit/show ordering). Deferred to panel-open time instead —
        # see sync_disable_button_visibility(), called from
        # PanelManager._start_sprint_entry.
        self.sprint_started.emit()
        self.display_text_updated.emit(
            self._format_display(0, self._sprint_duration_s)
        )

    def sync_disable_button_visibility(self):
        """Called from PanelManager._start_sprint_entry, before the panel becomes
        visible — NOT from the arm path itself. See _do_arm_sprint's comment for
        why the button's visibility is deferred to panel-open time instead of
        being set synchronously during arming."""
        self.disable_sprint_btn.setVisible(self._sprint_active)

    def disable_sprint(self, was_cancelled=False):
        was_active = self._sprint_active
        self._sprint_active = False
        self._sprint_duration_s = None
        self._sprint_start_time = None
        self._sprint_paused_at = None
        self._grace_pool_s = None
        self._grace_used_s = 0.0
        self._cancel_timer.stop()
        self._cancel_message_active = False
        self.disable_sprint_btn.hide()
        if was_active:
            self.sprint_stopped.emit()
        self.display_text_updated.emit("")
        self.update_panel_styling()

    def update_sprint_state(self, current_time, is_paused):
        if not self._sprint_active:
            return
        if self._cancel_message_active:
            return

        if is_paused:
            if self._sprint_paused_at is None:
                self._sprint_paused_at = current_time
            grace_remaining = max(0.0,
                self._grace_pool_s - self._grace_used_s
                - (current_time - self._sprint_paused_at))
            if grace_remaining <= 0 and self._grace_pool_s is not None:
                self._grace_used_s = self._grace_pool_s
                self._trigger_cancel()
                return
        else:
            if self._sprint_paused_at is not None:
                self._grace_used_s += current_time - self._sprint_paused_at
                self._sprint_paused_at = None

        if not is_paused:
            elapsed = (current_time - self._sprint_start_time) - self._grace_used_s
            remaining = self._sprint_duration_s - elapsed
            if remaining <= 0:
                self._trigger_complete()
                return
            self.display_text_updated.emit(self._format_display(elapsed, remaining))
        else:
            grace_remaining = max(0.0,
                self._grace_pool_s - self._grace_used_s
                - (current_time - self._sprint_paused_at))
            self.display_text_updated.emit(self._format_grace_display(grace_remaining))

    def _format_display(self, elapsed_s, remaining_s):
        remaining_s = max(0, int(remaining_s))
        rem_m, rem_s = divmod(remaining_s, 60)
        total_s = int(self._sprint_duration_s)
        tot_m, tot_s = divmod(total_s, 60)
        return f"-{rem_m:02d}:{rem_s:02d} | {tot_m:02d}:{tot_s:02d}"

    def _format_grace_display(self, grace_remaining_s):
        grace_remaining_s = max(0, int(grace_remaining_s))
        g_m, g_s = divmod(grace_remaining_s, 60)
        return f"Grace {g_m:02d}:{g_s:02d}"

    def _trigger_cancel(self):
        # disable_sprint() FIRST, THEN set the guard — disable_sprint() unconditionally
        # clears _cancel_message_active as part of its own state reset, so setting the
        # guard before calling it just gets immediately clobbered back to False. That
        # left the guard never actually armed for the next update_sprint_state tick,
        # which stomped the message back to "" almost immediately (reported
        # live, 2026-08-11). Matches sleep_timer.py's _cancel_eoc_sleep ordering.
        self.disable_sprint(was_cancelled=True)
        self._cancel_message_active = True
        self.display_text_updated.emit("Sprint failed")
        self._cancel_timer.start(self._dismiss_ms)

    def _trigger_complete(self):
        # Same ordering fix as _trigger_cancel — see its comment.
        self.disable_sprint(was_cancelled=False)
        self._cancel_message_active = True
        self.sprint_expired.emit()
        self.display_text_updated.emit("Sprint completed")
        self._cancel_timer.start(self._dismiss_ms)

    def _on_cancel_message_timeout(self):
        self._cancel_message_active = False
        self.display_text_updated.emit("")

    def _apply_preset_ramp_colors(self):
        """Per-sibling positional color ramp across the 10 duration-preset buttons.
        Mirrors SleepTimerPanel._apply_preset_ramp_colors exactly — see that method's
        docstring for why this can't be expressed as static QSS (per-instance
        setStyleSheet needed for the per-button gradient wins over panel-level QSS
        pseudo-states, so hover/pressed must be reproduced here explicitly)."""
        from ..themes import _resolve_theme
        t = _resolve_theme(self.theme_manager.get_committed_theme())
        btn_text = t.get('button_text', t.get('text_on_light_bg', t['text']))

        for i, btn in enumerate(self._sprint_presets_buttons):
            c = QColor(*(int(v) for v in
                         preset_ramp_rgb(t, i, len(self._sprint_presets_buttons)).split(',')))
            hover_c = c.lighter(130)
            pressed_c = c.darker(130)
            btn.setStyleSheet(
                f"QPushButton {{ background-color: rgb({c.red()}, {c.green()}, {c.blue()}); "
                f"color: {btn_text}; border: none; }}"
                f"QPushButton:hover {{ background-color: rgb({hover_c.red()}, {hover_c.green()}, {hover_c.blue()}); }}"
                f"QPushButton:pressed {{ background-color: rgb({pressed_c.red()}, {pressed_c.green()}, {pressed_c.blue()}); }}"
            )

    def update_panel_styling(self):
        """Full sync: the ramp (see _apply_preset_ramp_colors) plus the grace mode
        buttons' and the per-mode preset buttons' selected Qt PROPERTY. Mirrors
        SleepTimerPanel.update_panel_styling. All three preset rows are synced
        unconditionally (not just the currently-visible one) — cheap, and avoids a
        stale 'selected' property if the mode is switched away and back."""
        self._apply_preset_ramp_colors()

        for mode, btn in self._grace_mode_btns.items():
            is_active = (mode == self._grace_mode)
            btn.setProperty("selected", "true" if is_active else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        for pct, btn in self._grace_pct_btns.items():
            is_active = (pct == self._grace_percentage)
            btn.setProperty("selected", "true" if is_active else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        for seconds, btn in self._grace_fixed_btns.items():
            is_active = (seconds == self._grace_fixed_s)
            btn.setProperty("selected", "true" if is_active else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        self.style().unpolish(self); self.style().polish(self)
