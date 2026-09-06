import logging
import math
import time
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGridLayout, QLineEdit
from PySide6.QtCore import Qt, QEvent, QRect, QRegularExpression, Signal, QTimer
from PySide6.QtGui import QRegularExpressionValidator, QColor
from ..themes import preset_ramp_rgb
from ..player import _CHAPTER_WALK_TOLERANCE
from mpv import ShutdownError
from .line_edit_dragfix import DragSafeLineEdit

logger = logging.getLogger(__name__)


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
    sprint_expired = Signal(int)  # fired only on natural completion, not cancel — carries elapsed_s
    display_text_updated = Signal(str)
    # Emitted only on a True<->False TRANSITION of the grace_remaining <= 3s
    # threshold while paused — not every tick. app.py owns the actual pulsation
    # animation (it targets sleep_timer_label, a widget SprintPanel doesn't have
    # a handle to), so this is a pure state-transition signal, not a display
    # value — deliberately not derived by app.py parsing the "Grace MM:SS" text
    # (SprintPanel already has the precise float; re-deriving it via string
    # parsing would be fragile and duplicate work).
    grace_warning_changed = Signal(bool)
    # SprintPanel has no db reference by design (matches SleepTimerPanel, which
    # also has none) — app.py owns the actual DB call and any follow-up stats
    # refresh, mirroring how every other app.py-coordination need here already
    # goes through a signal (sprint_started/sprint_stopped/sprint_expired).
    reset_sprint_stats_requested = Signal()

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
        # End-of-chapter mode: None = duration-based sprint (the only mode before
        # this pass), 'end_of_chapter' = anchor-pinned. _sprint_eoc_anchor is the
        # chapter index sprint was armed on, mirroring SleepTimerPanel's own
        # panel-local _sleep_eoc_anchor (NOT a Player attribute — Player has no
        # EOC-anchor state of its own; both panels track their own anchor
        # independently). A forward crossing past the anchor is handled by
        # _on_chapter_changed, distinguishing a user-driven seek
        # (player.user_seek_pending, set at the seek SOURCE in Player.seek_async)
        # from natural playback reaching it — same mechanism as sleep's, see that
        # method's docstring in sleep_timer.py for the full rationale.
        self._sprint_mode = None
        self._sprint_eoc_anchor = None
        # Previous tick's player.is_seeking, so update_sprint_state can detect a
        # True->False transition (a seek settling) across 200ms polls — used to
        # consume a stale user_seek_pending flag left by a seek that stayed within
        # the anchor chapter (no chapter_changed emit, so _on_chapter_changed never
        # runs to consume it itself). Mirrors sleep_timer.py's _was_seeking exactly
        # — without this, EOC sprint would reintroduce the exact bug sleep's EOC
        # mode had until 2026-08-10 (a stale flag surviving to falsely tag the
        # next, entirely natural, chapter transition as seek-driven).
        self._sprint_was_seeking = False
        # True while grace_remaining <= 3s (paused, grace draining toward
        # exhaustion) — tracked so grace_warning_changed only emits on a real
        # transition, not every 200ms tick. Reset on unpause and on every
        # disarm path via disable_sprint() (see its own comment).
        self._grace_warning_active = False
        # pos value from the previous update_sprint_state tick, for backward-seek
        # detection (Pass 3). Reset to None on arm and disarm so a stale pre-arm/
        # post-disarm position is never diffed against the next sprint's first tick.
        self._last_known_pos = None
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
        # Backward-seek compensation (Pass 3 gated behind a setting, default Off,
        # 2026-08-11): the pure tick-to-tick _last_known_pos diff cannot tell a
        # genuine rewind from "seeked forward then came back" — the latter reads
        # as a large backward jump relative to the elevated post-forward-seek
        # position, even though net audio progress is zero. Confirmed live: a
        # 10-minute sprint, seek forward 20 minutes, seek back to the same spot,
        # became a 30-minute sprint. Off by default until that's fixed properly.
        self._backward_compensation = self.config.get_sprint_backward_seek_compensation()
        # Shared with app.py's _INDICATOR_DISMISS_MS — how long "Sprint failed"/
        # "Sprint completed" show in the indicator zone before clearing.
        self._dismiss_ms = dismiss_ms
        self._cancel_timer = QTimer(self)
        self._cancel_timer.setSingleShot(True)
        self._cancel_timer.timeout.connect(self._on_cancel_message_timeout)
        self.player.chapter_changed.connect(self._on_chapter_changed)
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
        # 10 presets fill cells (0,0)-(2,1); (2,2)-(2,3) are otherwise empty —
        # End of chapter spans them rather than adding a new row. No
        # Styled by the same ramp/default QSS as the duration presets, NOT "pattern_button" —
        # matches SleepTimerPanel.end_chap_btn's resting/hover appearance exactly. Given the
        # SAME objectName as that button (2026-09-07) so the keyboard-focus QSS rule
        # (get_sprint_stylesheet) can target this ONE grid cell specifically, instead of a bare
        # QPushButton type selector — that was tried first and wrongly matched every other
        # plain button in the panel, including #stats_reset_btn (reported live: it silently
        # gained the same fill it was explicitly supposed to be excluded from, since it had no
        # :focus rule of its own to out-rank the generic one).
        self._eoc_btn = QPushButton("End of chapter")
        self._eoc_btn.setObjectName("panel_grid_eoc_btn")
        self._eoc_btn.setFixedHeight(30)
        # Grid column-width negotiation for a 2-column span left this 1px short
        # of flush with the preset buttons above it (57+8+57=122) — reported
        # live, 2026-08-11. setMinimumWidth forces it to claim the full span.
        self._eoc_btn.setMinimumWidth(122)
        self._eoc_btn.clicked.connect(self._on_eoc_sprint_clicked)
        grid.addWidget(self._eoc_btn, 2, 2, 1, 2)
        layout.addLayout(grid)
        layout.addSpacing(2)

        # Custom time input
        custom_time_layout = QHBoxLayout()
        self.custom_sprint_input = DragSafeLineEdit()
        self.custom_sprint_input.setPlaceholderText("min")
        self.custom_sprint_input.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.custom_sprint_input.customContextMenuRequested.connect(lambda _: self.custom_sprint_input.clear())
        self.custom_sprint_input.setFixedWidth(39)
        self.custom_sprint_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
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

        # Backward seek compensation toggle — always exactly two rows (label +
        # button row), no submenu/foldable content, so Grace period below it
        # never shifts position when this is toggled.
        backward_header = QLabel("Backward seek compensation")
        backward_header.setObjectName("settings_header")
        layout.addWidget(backward_header)

        backward_layout = QHBoxLayout()
        backward_layout.setSpacing(5)
        self._backward_compensation_btns = {}
        for enabled, text in [(False, "Off"), (True, "On")]:
            btn = QPushButton(text)
            btn.setObjectName("pattern_button")
            btn.clicked.connect(lambda _, e=enabled: self._set_backward_compensation(e))
            backward_layout.addWidget(btn)
            self._backward_compensation_btns[enabled] = btn
        backward_layout.addStretch()
        layout.addLayout(backward_layout)

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
        submenu_layout.setContentsMargins(0, 1, 0, 0)
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
        self.custom_grace_input.setFixedWidth(39)
        self.custom_grace_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.custom_grace_input.setValidator(QRegularExpressionValidator(QRegularExpression("[1-9][0-9]{0,2}"), self))
        # Live validation — no Set button. textChanged fires on every keystroke;
        # editingFinished (focus-out and Enter) is belt-and-suspenders in case a
        # future change makes textChanged not fire for some input path.
        self.custom_grace_input.textChanged.connect(self._on_custom_grace_changed)
        self.custom_grace_input.editingFinished.connect(self._on_custom_grace_changed)
        if self._grace_custom_s > 0:
            self.custom_grace_input.setText(str(self._grace_custom_s))

        def _grace_input_key(e):
            if e.key() == Qt.Key.Key_Escape:
                self.custom_grace_input.clear()
                self.custom_grace_input.clearFocus()
            else:
                DragSafeLineEdit.keyPressEvent(self.custom_grace_input, e)
        self.custom_grace_input.keyPressEvent = _grace_input_key
        custom_grace_layout.addWidget(self.custom_grace_input)
        # Without a trailing stretch, the lone fixed-width child was centered
        # in the row instead of staying left-anchored where the Set button
        # used to visually pin it — reported live, 2026-08-12.
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

        # Reset all sprint data — pinned to the bottom of the panel via the
        # stretch above (matches Stats' "Reset all listening stats" / Book
        # Detail's "Delete listening history"). Confirm label is added to the
        # layout BEFORE the button, exactly like both of those — it is a real
        # widget in the normal vertical flow, occupying its own space above the
        # button, NOT a swap-in-place replacement of the button. The button
        # itself is never hidden or disabled during confirm; only the label's
        # setVisible toggles (verified directly against StatsPanel._on_reset_stats/
        # _cancel_reset_stats, which never call anything but setVisible on the
        # label and never touch the button at all — confirmed via screenshot,
        # 2026-08-12, after two earlier wrong guesses at this same mechanism).
        self._reset_sprint_confirm_label = _ClickableLabel("Confirm to delete all sprint data")
        self._reset_sprint_confirm_label.setObjectName("sprint_reset_confirm")
        self._reset_sprint_confirm_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._reset_sprint_confirm_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._reset_sprint_confirm_label.setFixedHeight(28)
        self._reset_sprint_confirm_label.clicked.connect(self._on_reset_sprint_data_confirmed)
        self._reset_sprint_confirm_label.setVisible(False)
        layout.addWidget(self._reset_sprint_confirm_label)

        self._reset_sprint_btn = QPushButton("Reset all sprint data")
        self._reset_sprint_btn.setObjectName("stats_reset_btn")
        self._reset_sprint_btn.clicked.connect(self._on_reset_sprint_data_clicked)
        layout.addWidget(self._reset_sprint_btn)
        self._reset_sprint_cancel_timer = QTimer(self)
        self._reset_sprint_cancel_timer.setSingleShot(True)
        self._reset_sprint_cancel_timer.timeout.connect(self._cancel_reset_sprint_data)

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

    def _set_backward_compensation(self, enabled):
        self._backward_compensation = enabled
        self.config.set_sprint_backward_seek_compensation(enabled)
        self.update_panel_styling()

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

    def _on_custom_grace_changed(self):
        """Live validation on textChanged/editingFinished — no Set button.
        Empty field: sets the in-memory value to 0 (no grace this session) but
        deliberately does NOT overwrite config, so a last valid value restores
        on next launch even if the user cleared the field without meaning to
        discard it permanently. Invalid mid-type input (e.g. a bare "-", which
        the validator regex still lets through as an intermediate state) is a
        no-op — the last valid in-memory value is left untouched rather than
        reset to 0, so a momentarily-invalid keystroke doesn't zero the grace
        pool before the user finishes typing."""
        text = self.custom_grace_input.text().strip()
        if text == '':
            self._grace_custom_s = 0
            return
        try:
            val = int(text)
            if val > 0:
                self._grace_custom_s = val
                self.config.set_sprint_grace_custom_s(val)
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

    def _on_reset_sprint_data_clicked(self):
        # Button is NOT touched — matches StatsPanel._on_reset_stats exactly,
        # which only ever calls setVisible(True) on the confirm label.
        self._reset_sprint_confirm_label.setVisible(True)
        self._reset_sprint_cancel_timer.start(7000)

    def _cancel_reset_sprint_data(self):
        self._reset_sprint_cancel_timer.stop()
        self._reset_sprint_confirm_label.setVisible(False)

    def _on_reset_sprint_data_confirmed(self):
        self._cancel_reset_sprint_data()
        self.reset_sprint_stats_requested.emit()

    def keyPressEvent(self, event):
        # Minimal, single-purpose override — NOT a full eventFilter priority
        # chain like BookDetailPanel's (that exists to arbitrate FOUR
        # concurrent confirm/edit states across a much larger panel; this
        # panel has exactly one Escape-cancellable state today). Reuses the
        # same _cancel_reset_sprint_data the 7s timer and the click-outside
        # eventFilter below both already call.
        if event.key() == Qt.Key.Key_Escape and self._reset_sprint_confirm_label.isVisible():
            self._cancel_reset_sprint_data()
            return
        super().keyPressEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        QApplication.instance().installEventFilter(self)

    def hideEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        super().hideEvent(event)

    def eventFilter(self, obj, event):
        # Matches StatsPanel's own click-outside-dismisses eventFilter exactly
        # (same shape, same install/remove lifecycle) — reported live,
        # 2026-08-12, that the confirm should behave identically to Stats'
        # "Reset all listening stats" for visual/behavioral consistency.
        if (
            event.type() == QEvent.Type.MouseButtonPress
            and self._reset_sprint_confirm_label.isVisible()
        ):
            gpos = event.globalPosition().toPoint()

            def hits(w):
                return w.isVisible() and QRect(
                    w.mapToGlobal(w.rect().topLeft()),
                    w.mapToGlobal(w.rect().bottomRight())
                ).contains(gpos)

            if not hits(self._reset_sprint_confirm_label) and not hits(self._reset_sprint_btn):
                self._cancel_reset_sprint_data()
        return super().eventFilter(obj, event)

    def set_sprint(self, duration_minutes=None):
        if not duration_minutes or duration_minutes <= 0:
            return
        proceed = lambda: self._do_arm_sprint(duration_minutes)
        if self._arm_gate:
            self._arm_gate(proceed)
        else:
            proceed()

    def _resolve_grace_pool(self, sprint_duration_s):
        """Shared by _do_arm_sprint and _do_arm_eoc_sprint — EOC sprints get a
        grace pool too (update_sprint_state's pause/grace-drain block runs for
        both modes unconditionally). sprint_duration_s is only meaningful for
        'percentage' mode; EOC sprints have no fixed duration, so percentage
        mode there is computed against 0 (mirrors passing None-safe math.ceil(0)
        = 0 rather than crashing — percentage grace on an EOC sprint is
        therefore always 0, same as if "None" were selected; Fixed/Custom still
        work normally since they don't depend on sprint_duration_s)."""
        if self._grace_mode == "percentage":
            return math.ceil((sprint_duration_s or 0) * self._grace_percentage / 100)
        elif self._grace_mode == "fixed":
            return self._grace_fixed_s
        elif self._grace_mode == "custom":
            return self._grace_custom_s if self._grace_custom_s > 0 else 0
        else:  # "none"
            return 0

    def _current_chapter_index(self):
        """Derives the current chapter index the same way Player._on_time_pos_change
        does (same _CHAPTER_WALK_TOLERANCE), for arming the end-of-chapter anchor.
        Mirrors SleepTimerPanel._current_chapter_index exactly — kept as a local
        copy rather than shared, matching how this codebase already duplicates
        small panel-local helpers (e.g. _ClickableLabel) between the two panels."""
        chaps = self.player.chapter_list or []
        pos = self.player.time_pos or 0.0
        curr = 0
        for i, chap in enumerate(chaps):
            if chap.get('time', 0) <= pos + _CHAPTER_WALK_TOLERANCE:
                curr = i
        return curr

    def _do_arm_sprint(self, duration_minutes):
        self._sprint_duration_s = duration_minutes * 60
        self._sprint_mode = None
        self._grace_pool_s = self._resolve_grace_pool(self._sprint_duration_s)
        self._sprint_paused_at = None
        self._grace_used_s = 0.0
        self._last_known_pos = None
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

    def _on_eoc_sprint_clicked(self):
        proceed = lambda: self._do_arm_eoc_sprint()
        if self._arm_gate:
            self._arm_gate(proceed)
        else:
            proceed()

    def _do_arm_eoc_sprint(self):
        self._sprint_duration_s = None
        self._sprint_mode = 'end_of_chapter'
        self._sprint_eoc_anchor = self._current_chapter_index()
        # A seek right before arming shouldn't count toward the first post-arm
        # transition — matches SleepTimerPanel._do_arm_sleep_timer's identical line.
        self.player.user_seek_pending = False
        self._sprint_was_seeking = False
        self._grace_pool_s = self._resolve_grace_pool(self._sprint_duration_s)
        self._sprint_paused_at = None
        self._grace_used_s = 0.0
        self._last_known_pos = None
        self._sprint_start_time = time.time()
        self._sprint_active = True
        if self.player:
            try:
                self.player.pause = False
            except (ShutdownError, AttributeError, SystemError):
                pass
        self.update_panel_styling()
        # disable_sprint_btn.show() deliberately NOT called here — same deferred-
        # visibility mechanism as _do_arm_sprint above.
        self.sprint_started.emit()
        self.display_text_updated.emit(self._format_display(0, None))

    def sync_disable_button_visibility(self):
        """Called from PanelManager._start_sprint_entry, before the panel becomes
        visible — NOT from the arm path itself. See _do_arm_sprint's comment for
        why the button's visibility is deferred to panel-open time instead of
        being set synchronously during arming.

        Also owns Reset all sprint data's visibility (inverse of the disable
        button's — only meaningful when no sprint is active) for the same
        deferred-to-panel-open reason, and unconditionally cancels any armed
        reset confirmation on panel (re)open rather than leaving a stale 7s
        timer running against a panel the user just reopened."""
        self.disable_sprint_btn.setVisible(self._sprint_active)
        self._reset_sprint_btn.setVisible(not self._sprint_active)
        self._cancel_reset_sprint_data()

    def disable_sprint(self, was_cancelled=False):
        was_active = self._sprint_active
        self._sprint_active = False
        self._sprint_duration_s = None
        self._sprint_start_time = None
        self._sprint_paused_at = None
        self._grace_pool_s = None
        self._grace_used_s = 0.0
        self._last_known_pos = None
        self._sprint_mode = None
        self._sprint_eoc_anchor = None
        self.player.user_seek_pending = False
        self._sprint_was_seeking = False
        self._cancel_timer.stop()
        self._cancel_message_active = False
        self.disable_sprint_btn.hide()
        # Symmetric with the hide above — safe to do synchronously here (unlike
        # showing it on ARM, which shares a call stack with sprint_started's
        # panel-close animation and would flash; disable_sprint() is not called
        # from that same path). Without this, _reset_sprint_btn stayed hidden
        # forever after a sprint ended while the panel was already open —
        # sync_disable_button_visibility only runs at panel-OPEN time, so
        # nothing ever re-showed it on disarm. Reported live (screenshots),
        # 2026-08-12.
        self._reset_sprint_btn.show()
        # Single safety-catch reset for the grace-warning pulsation, covering
        # EVERY disarm path in one place (_trigger_cancel, _trigger_complete,
        # cancel_for_book_switch, and every bare manual disable_sprint() call) —
        # all of them already call disable_sprint(), so a per-call-site reset
        # would just duplicate this same check at each one.
        if self._grace_warning_active:
            self._grace_warning_active = False
            self.grace_warning_changed.emit(False)
        if was_active:
            self.sprint_stopped.emit()
        self.display_text_updated.emit("")
        self.update_panel_styling()

    def update_sprint_state(self, current_time, is_paused, pos, dur, is_eof):
        if not self._sprint_active:
            return
        # Detect a seek settling (is_seeking True->False) since the last poll. A seek
        # that lands back in the anchor chapter never fires chapter_changed (the
        # index didn't move), so _on_chapter_changed never runs to consume the
        # user_seek_pending flag that seek_async set — left uncleared, it would
        # falsely tag the NEXT chapter transition (possibly a natural one) as
        # seek-driven. Mirrors SleepTimerPanel.update_timer_state's identical block.
        currently_seeking = self.player.is_seeking
        if self._sprint_was_seeking and not currently_seeking:
            if (self._sprint_mode == 'end_of_chapter'
                    and self._sprint_eoc_anchor is not None
                    and self._current_chapter_index() == self._sprint_eoc_anchor):
                self.player.user_seek_pending = False
        self._sprint_was_seeking = currently_seeking
        if self._cancel_message_active:
            return

        # Backward-seek accounting: if pos moved backward since last tick, the
        # user re-listened to content. _sprint_duration_s and elapsed/remaining
        # are all WALL-CLOCK seconds (current_time is time.time()) — but the
        # rewind distance measured via pos is AUDIO-position seconds. These are
        # different units whenever speed != 1.0: rewinding 40s of audio at 8x
        # only costs 5s of the user's actual wall-clock time to re-listen to.
        # Divide by speed to convert the audio-distance penalty into the
        # wall-clock unit _sprint_duration_s is measured in. Confirmed live
        # 2026-08-11: adding the raw (unconverted) audio delta made an 8x-speed
        # 5s backward seek add 40s to the sprint duration instead of 5s — an
        # 8x-inflated penalty, not the reported "doubling" it first looked like.
        # Counted regardless of pause state (a backward seek while paused is
        # still a backward seek; the grace pool drains independently of this).
        #
        # Gated behind _backward_compensation (default Off, config-backed) —
        # confirmed live 2026-08-11 that a pure tick-to-tick diff cannot tell a
        # genuine rewind from "seeked forward then came back": a 10-minute
        # sprint, forward-seek 20 minutes, then back to the same spot, became a
        # 30-minute sprint even though net audio progress was zero. See
        # __init__'s _backward_compensation comment. EOC mode ignores backward
        # seeks entirely — its clock is elapsed wall-time toward a fixed chapter
        # boundary, not a duration budget that could be "extended" by a rewind.
        if self._backward_compensation and self._sprint_mode != 'end_of_chapter':
            if (self._last_known_pos is not None
                    and pos is not None
                    and pos < self._last_known_pos):
                rewind_delta = self._last_known_pos - pos
                speed = self.player.speed or 1.0
                self._sprint_duration_s += rewind_delta / speed
                # TEMPORARY (Pass 3 VT-boundary verification, 2026-08-11): confirms
                # whether a natural VT file-boundary crossing can present as a false
                # backward-seek reading here. Remove once verified — see NOTES.md.
                logger.warning(
                    f"SPRINT-REWIND-TRACE: pos={pos:.3f} "
                    f"prev={self._last_known_pos:.3f} "
                    f"delta={rewind_delta:.3f} speed={speed:.2f} "
                    f"wall_clock_penalty={rewind_delta / speed:.3f} "
                    f"new_duration={self._sprint_duration_s:.1f}")
        # _last_known_pos updates unconditionally on every tick where pos is not
        # None, regardless of direction AND regardless of the gate above — so
        # toggling compensation On mid-sprint compares against the immediately
        # preceding tick, not a stale pre-toggle position.
        if pos is not None:
            self._last_known_pos = pos

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
                # Unpausing before grace exhausted must stop the warning
                # pulsation immediately — it only ever applies to the paused
                # grace-drain state.
                if self._grace_warning_active:
                    self._grace_warning_active = False
                    self.grace_warning_changed.emit(False)

        if not is_paused:
            elapsed = (current_time - self._sprint_start_time) - self._grace_used_s
            if self._sprint_mode == 'end_of_chapter':
                # Fire only when position reaches the ANCHOR chapter's own end
                # boundary — not "whatever chapter is current". A forward
                # crossing past the anchor (whether natural or seek-driven) is
                # detected via chapter_changed and handled by
                # _on_chapter_changed, which decides whether to cancel with a
                # message (seek-driven) or leave this branch to fire normally
                # (natural — user_seek_pending stays False, so
                # _on_chapter_changed no-ops and this boundary check fires
                # exactly as it always has). Mirrors SleepTimerPanel's
                # identical end_of_chapter branch in update_timer_state,
                # including the -0.5 tolerance and the is_eof fallback (a book
                # that ends slightly before anchor_end-0.5 must still complete).
                if self._sprint_eoc_anchor is not None and dur:
                    chaps = self.player.chapter_list or []
                    anchor = self._sprint_eoc_anchor
                    if chaps and anchor < len(chaps) - 1:
                        anchor_end = chaps[anchor + 1].get('time', dur)
                        reached_end = (pos is not None and pos >= anchor_end - 0.5) or is_eof
                    else:
                        reached_end = (pos is not None and pos >= dur - 0.5) or is_eof
                    if reached_end:
                        self._trigger_complete(elapsed)
                        return
                self.display_text_updated.emit(self._format_display(elapsed, None))
            else:
                remaining = self._sprint_duration_s - elapsed
                if remaining <= 0:
                    self._trigger_complete(elapsed)
                    return
                self.display_text_updated.emit(self._format_display(elapsed, remaining))
        else:
            grace_remaining = max(0.0,
                self._grace_pool_s - self._grace_used_s
                - (current_time - self._sprint_paused_at))
            # Emit only on a True<->False transition, not every 200ms tick —
            # app.py's animation start()/stop() calls are idempotent-adjacent
            # but there's no reason to invoke them every tick regardless.
            is_warning = grace_remaining <= self._grace_warn_threshold()
            if is_warning != self._grace_warning_active:
                self._grace_warning_active = is_warning
                self.grace_warning_changed.emit(is_warning)
            self.display_text_updated.emit(self._format_grace_display(grace_remaining))

    def _format_display(self, elapsed_s, remaining_s):
        if self._sprint_mode == 'end_of_chapter':
            elapsed_s = max(0, int(elapsed_s))
            e_m, e_s = divmod(elapsed_s, 60)
            return f"{e_m:02d}:{e_s:02d} · chapter"
        remaining_s = max(0, int(remaining_s))
        rem_m, rem_s = divmod(remaining_s, 60)
        total_s = int(self._sprint_duration_s)
        tot_m, tot_s = divmod(total_s, 60)
        return f"-{rem_m:02d}:{rem_s:02d} · {tot_m:02d}:{tot_s:02d}"

    def _format_grace_display(self, grace_remaining_s):
        grace_remaining_s = max(0, int(grace_remaining_s))
        g_m, g_s = divmod(grace_remaining_s, 60)
        return f"Grace {g_m:02d}:{g_s:02d}"

    def _grace_warn_threshold(self) -> float:
        """Warning-pulsation threshold, binned by grace pool size — a fixed 3s
        warning window would be nearly the whole pool for a short grace period
        and barely noticeable for a long one, so the window scales with the
        pool instead."""
        pool = self._grace_pool_s or 0
        if pool >= 120:
            return 15.0
        elif pool >= 15:
            return 10.0
        else:
            return 5.0

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

    def _trigger_complete(self, elapsed_s):
        # elapsed_s must be passed in by the caller (update_sprint_state), computed
        # BEFORE this is called — disable_sprint() below nulls _sprint_start_time/
        # _grace_used_s, so this method has no way to derive elapsed itself once
        # it runs. Same ordering fix as _trigger_cancel otherwise — see its comment.
        self.disable_sprint(was_cancelled=False)
        self._cancel_message_active = True
        self.sprint_expired.emit(int(elapsed_s))
        self.display_text_updated.emit("Sprint completed")
        self._cancel_timer.start(self._dismiss_ms)

    def cancel_for_book_switch(self):
        """Disarms the sprint with a "Sprint cancelled" message. Originally added
        for a book switch mid-sprint (2026-08-11: previously the sprint silently
        carried over to the newly selected book instead of disarming at all);
        also reused by _on_chapter_changed for a seek-driven forward crossing
        past an end-of-chapter sprint's anchor — both are the same category of
        event (an external interruption, not a grace-pool failure and not a
        deliberate manual cancel), so they share this method and its wording.
        Distinct from both other disarm paths: a grace-pool failure
        ("Sprint failed", _trigger_cancel) and a deliberate manual cancel (bare
        disable_sprint(), silent — the sidebar X / panel cancel button /
        conflict-gate paths must all stay silent, unchanged by this method).
        No-ops if no sprint is active, so callers don't need to check is_active
        first."""
        if not self._sprint_active:
            return
        # Same ordering as _trigger_cancel/_trigger_complete — disable_sprint()
        # FIRST, then set the guard, or its own reset clobbers it right back.
        self.disable_sprint(was_cancelled=True)
        self._cancel_message_active = True
        self.display_text_updated.emit("Sprint cancelled")
        self._cancel_timer.start(self._dismiss_ms)

    def _on_chapter_changed(self, index):
        """Connected to Player.chapter_changed — the single universal chapter-index
        signal (see CLAUDE.md invariant 25 / _on_time_pos_change). Only end-of-chapter
        mode cares, and only about a forward crossing past the anchor. Mirrors
        SleepTimerPanel._on_chapter_changed exactly — see that method's docstring
        for the full user_seek_pending rationale (why a flag set at the seek
        SOURCE is used instead of inferring seek-vs-natural from is_seeking's
        asynchronous settle timing).

        Natural playback reaching the anchor's own end is handled entirely by
        update_sprint_state's boundary-fire check; this method does nothing for
        that case (user_seek_pending stays False, so the branch below no-ops)."""
        if self._sprint_mode != 'end_of_chapter' or self._sprint_eoc_anchor is None:
            return
        # Consume the flag on EVERY chapter transition this method sees, not only a
        # forward crossing — see SleepTimerPanel._on_chapter_changed's identical
        # comment for why (a seek landing <= anchor still sets user_seek_pending;
        # left uncleared it would falsely tag the next, possibly natural, crossing).
        seek_driven = self.player.user_seek_pending
        self.player.user_seek_pending = False
        if index <= self._sprint_eoc_anchor:
            return
        if seek_driven:
            # "Sprint cancelled", not "Sprint failed" — a seek-driven forward
            # crossing is an external interruption (same category as a book
            # switch), not a grace-pool exhaustion. See cancel_for_book_switch's
            # docstring.
            self.cancel_for_book_switch()
        # else: natural arrival — update_sprint_state's boundary check owns this

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
                # Keyboard focus + keyboard-mode hover suppression — mirrors
                # SleepTimerPanel._apply_preset_ramp_colors exactly (2026-09-07 fix; see that
                # method's comments for the full reasoning). Reported live: this grid showed
                # the marker with no hover-style highlight underneath it, unlike Sleep's.
                f"QPushButton:focus {{ background-color: rgb({hover_c.red()}, {hover_c.green()}, {hover_c.blue()}); }}"
                f"QWidget#sprint_panel[kbdnav=\"true\"] QPushButton:hover {{ "
                f"background-color: rgb({c.red()}, {c.green()}, {c.blue()}); }}"
                f"QWidget#sprint_panel[kbdnav=\"true\"] QPushButton:focus:hover {{ "
                f"background-color: rgb({hover_c.red()}, {hover_c.green()}, {hover_c.blue()}); }}"
            )

    def update_panel_styling(self):
        """Full sync: the ramp (see _apply_preset_ramp_colors) plus the grace mode
        buttons' and the per-mode preset buttons' selected Qt PROPERTY. Mirrors
        SleepTimerPanel.update_panel_styling. All three preset rows are synced
        unconditionally (not just the currently-visible one) — cheap, and avoids a
        stale 'selected' property if the mode is switched away and back."""
        self._apply_preset_ramp_colors()

        for enabled, btn in self._backward_compensation_btns.items():
            is_active = (enabled == self._backward_compensation)
            btn.setProperty("selected", "true" if is_active else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

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
