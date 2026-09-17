import time
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGridLayout, QLineEdit, QApplication
from PySide6.QtCore import Qt, QRegularExpression, Signal, QTimer, QEvent
from PySide6.QtGui import QRegularExpressionValidator, QColor
from ..themes import preset_ramp_rgb
from ..player import _CHAPTER_WALK_TOLERANCE
from .title_bar import RightClickButton
from mpv import ShutdownError
from .line_edit_dragfix import DragSafeLineEdit
from .ramp_highlight_fade import RampHighlightFade


class _ClickableLabel(QLabel):
    """Same shape as book_detail_panel.py's private _ClickableLabel / sprint_panel.py's
    local copy — a QLabel that emits a real Signal on left-click, for the confirm-overlay
    pattern used across this codebase (Delete listening history, Reset all stats, etc.)."""
    clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


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
        # End-of-chapter mode: the chapter index sleep was armed on. A forward
        # crossing past this anchor is handled by _on_chapter_changed, which
        # distinguishes a user-driven seek (player.user_seek_pending, set at the
        # seek SOURCE in Player.seek_async) from natural playback reaching it on
        # its own — see that method's docstring.
        self._sleep_eoc_anchor = None
        # Playback-position distance from arm time to the anchor chapter's own
        # end (anchor_end - player_pos at the moment Sleep was armed) — the
        # end-of-chapter mirror of _total_timer_duration's role for timed mode:
        # caps the fade window so arming close to a chapter's end (or a chapter
        # shorter than the configured fade duration) doesn't produce an instant
        # near-silent jump the way an uncapped ratio would. Fixed for the whole
        # arm cycle, same as _total_timer_duration — a seek backward past the
        # arm point does NOT widen this cap; the fade window stays whatever it
        # was at arm time until disable_sleep_timer() clears it.
        self._sleep_eoc_distance_at_arm = None
        # Previous tick's player.is_seeking, so update_timer_state can detect a
        # True->False transition (a seek settling) across 200ms polls — used to
        # consume a stale user_seek_pending flag left by a seek that stayed within
        # the anchor chapter (no chapter_changed emit, so _on_chapter_changed never
        # runs to consume it itself). See update_timer_state's own comment.
        self._was_seeking = False
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
        # Optional external gate, set by app.py via set_arm_gate(). See SprintPanel's
        # matching mechanism (ui/sprint_panel.py) for the full rationale — this panel
        # has no built-in awareness of any other panel (e.g. sprint); app.py owns
        # that policy entirely.
        self._arm_gate = None
        self._conflict_confirm_timer = QTimer(self)
        self._conflict_confirm_timer.setSingleShot(True)
        self._conflict_confirm_timer.timeout.connect(self._on_conflict_confirm_timeout)
        self._conflict_on_confirm = None

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
        # Animated highlight fade for the ramp buttons — see ramp_highlight_fade.py
        # and SpeedControlsPanel's identical wiring for the full explanation.
        self._ramp_highlight_fade = RampHighlightFade()
        for i, val in enumerate(presets_minutes):
            btn = QPushButton(f"{val} min")
            btn.setFixedSize(57, 30)
            btn.clicked.connect(lambda _, v=val: self.set_sleep_timer(duration_minutes=v))
            grid.addWidget(btn, i // 4, i % 4)
            self._sleep_presets_buttons.append(btn)

        self.end_chap_btn = QPushButton("End of chapter")
        # Named so the keyboard-focus QSS rule (get_sleep_stylesheet) can target this ONE
        # grid cell specifically — a bare QPushButton type selector was tried first and wrongly
        # matched every other plain button in the panel (Set, and — critical bug, reported live
        # 2026-09-07 — Sprint's #stats_reset_btn had no :focus rule of its own to out-rank it,
        # so it silently inherited the same fill it was explicitly supposed to be excluded from).
        self.end_chap_btn.setObjectName("panel_grid_eoc_btn")
        self.end_chap_btn.setFixedHeight(30)
        # Grid column-width negotiation for a 2-column span left this 1px short
        # of flush with the preset buttons above it (57+8+57=122) — same fix as
        # SprintPanel's identical "End of chapter" button (2026-08-11/12).
        self.end_chap_btn.setMinimumWidth(122)
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
        self.custom_sleep_input.setFixedWidth(39)
        self.custom_sleep_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.custom_sleep_input.setValidator(QRegularExpressionValidator(QRegularExpression("[1-9][0-9]{0,2}"), self))
        self.custom_sleep_input.returnPressed.connect(self._on_custom_sleep_time_set)
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

        # Conflict confirmation (shown via show_conflict_confirm when app.py's
        # arm gate detects sprint is active). Same shape as sprint_panel.py's
        # own confirm label / book_detail_panel.py's "Delete listening history".
        self._conflict_confirm_label = _ClickableLabel("")
        self._conflict_confirm_label.setObjectName("sleep_conflict_confirm")
        self._conflict_confirm_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._conflict_confirm_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._conflict_confirm_label.setFixedHeight(28)
        self._conflict_confirm_label.clicked.connect(self._on_conflict_confirm_clicked)
        self._conflict_confirm_label.hide()
        layout.addWidget(self._conflict_confirm_label)

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

    @property
    def is_active(self):
        return self._sleep_mode is not None

    def set_arm_gate(self, gate_fn):
        """gate_fn(proceed) is called instead of arming directly whenever
        set_sleep_timer() is invoked. gate_fn must eventually call proceed()
        (now, later via a confirm click, or never if the user lets it time
        out/cancel). See SprintPanel.set_arm_gate for the full rationale."""
        self._arm_gate = gate_fn

    def show_conflict_confirm(self, message, on_confirm):
        """Shows a click-to-confirm overlay with the given message; on_confirm is
        called (with no arguments) if the user clicks it before the timeout, or
        silently dropped on timeout (matching every confirm pattern in this
        codebase — Delete listening history, Reset all stats). Fixed 7s window,
        NOT _dismiss_ms (the much shorter "Sleep cancelled" MESSAGE display
        window — a different concept entirely)."""
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

    def _cancel_conflict_confirm(self):
        """Explicit cancel — as opposed to _on_conflict_confirm_timeout, which is the timer's
        OWN fire and therefore has nothing left to stop. Used by Escape (keyPressEvent) so
        dismissing the prompt early doesn't leave the 7s timer running to fire a redundant,
        harmless-but-pointless _on_conflict_confirm_timeout after the label is already hidden."""
        self._conflict_confirm_timer.stop()
        self._conflict_confirm_label.hide()
        self._conflict_on_confirm = None

    def showEvent(self, event):
        super().showEvent(event)
        QApplication.instance().installEventFilter(self)

    def hideEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        super().hideEvent(event)

    def eventFilter(self, obj, event):
        # Added 2026-09-08, app-wide confirm-Escape-consistency pass. MUST be a QApplication-wide
        # eventFilter, NOT a keyPressEvent override on this panel widget — a keyPressEvent
        # override here was tried first and shipped dead code: MainWindow installs its OWN
        # QApplication-wide filter at __init__ time (app.py, _handle_tab_escape), and per
        # QObject::installEventFilter's documented LIFO order (confirmed directly via a small
        # synthetic test, not assumed), the MOST RECENTLY installed filter runs FIRST — so a
        # filter installed here, in showEvent (i.e. AFTER MainWindow's __init__-time install),
        # already runs before MainWindow's and is the only reliable interception point.
        # keyPressEvent on the panel WIDGET only fires if real Qt focus happens to be on the
        # panel itself, which _claim_panel_focus never grants here (it targets a child button
        # via panel_tab_widgets) — so that override was silently unreachable. Live-reported
        # 2026-09-08: "Esc on Sleep — conflict-confirm overlay closes the panel." Matches
        # SprintPanel's identical fix and identical correction in the same pass — see that
        # panel's own eventFilter for the fuller cross-panel writeup of why this shape is
        # required, not just preferred.
        # Generalized 2026-09-09 from Key_Escape specifically to ANY key other than
        # Space/Enter/Return — live design ask, app-wide: any key that isn't the confirm
        # action should dismiss an armed confirmation, swallowing that press (pure dismiss,
        # not also whatever the key would otherwise do) — matches Tags' delete-tag confirm
        # and Sprint's identical generalization in the same pass; see SprintPanel.eventFilter
        # for the fuller writeup.
        if (event.type() == QEvent.Type.KeyPress
                and event.key() not in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and self._conflict_confirm_label.isVisible()):
            self._cancel_conflict_confirm()
            return True
        return super().eventFilter(obj, event)

    def set_sleep_timer(self, duration_minutes=None, mode=None):
        proceed = lambda: self._do_arm_sleep_timer(duration_minutes, mode)
        if self._arm_gate:
            self._arm_gate(proceed)
        else:
            proceed()

    def _do_arm_sleep_timer(self, duration_minutes=None, mode=None):
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
            self.timer_started.emit()
        elif mode == 'end_of_chapter':
            self._total_timer_duration = 0
            self._sleep_mode = mode
            self._sleep_eoc_anchor = self._current_chapter_index()
            # Distance from right now to the anchor chapter's own end — same
            # anchor_end derivation update_timer_state's boundary-fire check
            # uses (next chapter's start, or total duration if the anchor is
            # the last chapter). Fixed here, once, for the fade cap — see
            # _sleep_eoc_distance_at_arm's own docstring in __init__.
            chaps = self.player.chapter_list or []
            pos = self.player.time_pos or 0.0
            anchor = self._sleep_eoc_anchor
            player_dur = self.player.duration or 0.0
            if chaps and anchor < len(chaps) - 1:
                anchor_end = chaps[anchor + 1].get('time', player_dur)
            else:
                anchor_end = player_dur
            self._sleep_eoc_distance_at_arm = max(0.0, anchor_end - pos)
            # A seek right before arming shouldn't count toward the first post-arm
            # transition.
            self.player.user_seek_pending = False
            self.config.set_sleep_mode(mode)
            self.timer_started.emit()
        # disable_sleep_btn.show() is deliberately NOT called here. timer_started
        # (above) is connected to panel_manager._close_sleep_flow, which starts the
        # slide-out synchronously in the same call stack — Qt does not paint
        # between two Python statements, so showing the button before OR after the
        # emit still lands in the same paint cycle as the close-slide, producing a
        # one-frame flash of the button just before the panel disappears (reported
        # live, 2026-08-11; a same-call-stack reorder was tried first and did not
        # fix it, confirming this mechanism). Matches the deferred-reconciliation
        # shape already used by _sync_persist_filter_on_open (app.py) for Settings'
        # persist-filter sub-buttons: the visibility fixup is deferred to the next
        # panel-OPEN instead of applied synchronously during the interaction that
        # would otherwise disturb an already-closing panel. See
        # sync_disable_button_visibility(), called from PanelManager._start_sleep_entry.

        self.update_panel_styling()

    def sync_disable_button_visibility(self):
        """Called from PanelManager._start_sleep_entry, before the panel becomes
        visible — NOT from the arm path itself. See _do_arm_sleep_timer's comment
        for why the button's visibility is deferred to panel-open time instead of
        being set synchronously during arming."""
        self.disable_sleep_btn.setVisible(self._sleep_mode is not None)

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
        self._sleep_eoc_distance_at_arm = None
        self.player.user_seek_pending = False
        self.player.sleep_fired = False
        self._was_seeking = False
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
        mode cares, and only about a forward crossing past the anchor.

        Distinguishes a user-driven seek from natural playback via
        player.user_seek_pending — a flag set at the SEEK SOURCE (the first
        statement of Player.seek_async, confirmed to be the sole entry point for
        every navigation action: Next/Prev, chapter-list click, slider drag/wheel,
        skip buttons, all keyboard shortcuts — no bypass anywhere), not inferred
        from a side effect like is_seeking's asynchronous settle timing. This is
        reliable regardless of how fast the seek settles, unlike a poll-based
        latch on is_seeking (tried and found structurally unreliable — see
        NOTES.md 2026-08-10).

        Natural playback reaching the anchor's own end is handled entirely by
        update_timer_state's boundary-fire check; this method does nothing for
        that case (user_seek_pending stays False, so the branch below no-ops)."""
        if self._sleep_mode != 'end_of_chapter' or self._sleep_eoc_anchor is None:
            return
        # Consume the flag on EVERY chapter transition this method sees, not only a
        # forward crossing. A seek that lands ON the anchor (or anywhere <= anchor —
        # e.g. VT restore-on-load, a seek within the anchor chapter, a backward seek)
        # still sets user_seek_pending; if left uncleared here, it survives to
        # falsely tag the NEXT — entirely natural — forward crossing as seek-driven.
        # Confirmed live (2026-08-10, VT book): arming, then a seek landing exactly
        # on the anchor chapter, left the flag stuck True across 5 subsequent natural
        # chapter_changed events until the real anchor->anchor+1 crossing wrongly
        # inherited it and cancelled instead of firing.
        seek_driven = self.player.user_seek_pending
        self.player.user_seek_pending = False
        if index <= self._sleep_eoc_anchor:
            return
        if seek_driven:
            self._cancel_eoc_sleep()
        # else: natural arrival — update_timer_state's boundary check owns this

    def _cancel_eoc_sleep(self):
        """A user-driven seek carried playback past the end-of-chapter anchor (see
        _on_chapter_changed — this never fires for natural arrival). Disarms sleep
        via the normal user-cancel path, then shows a "Sleep cancelled"
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
            # Cached on the button itself so begin_ramp_highlight_fade (called from
            # MainWindow when the traveling marker starts fading) doesn't need to
            # re-derive the ramp index/theme math — see ramp_highlight_fade.py.
            btn._ramp_hover_color = QColor(hover_c)
            btn._ramp_base_color = QColor(c)
            btn.setStyleSheet(
                f"QPushButton {{ background-color: rgb({c.red()}, {c.green()}, {c.blue()}); "
                f"color: {btn_text}; border: none; }}"
                f"QPushButton:hover {{ background-color: rgb({hover_c.red()}, {hover_c.green()}, {hover_c.blue()}); }}"
                f"QPushButton:pressed {{ background-color: rgb({pressed_c.red()}, {pressed_c.green()}, {pressed_c.blue()}); }}"
                # Keyboard-navigation's look for the grid's current cell. Unlike Themes' swatch
                # grid (whose ThemeItems are deliberately Qt.FocusPolicy.NoFocus, tracked by a
                # synthetic kbdnav_hover PROPERTY because they never receive real Qt focus —
                # see theme_manager.py's _set_kbdnav_swatch_hover), these buttons are ordinary
                # QPushButtons that DO receive real focus when MainWindow._handle_panel_grid_
                # arrows moves the cursor onto them. SCOPED to
                # [kbdnav="true"][kbdnav_marker_active="true"] (was a bare :focus rule until
                # 2026-09-08, then just [kbdnav="true"]) — these buttons keep real Qt focus by
                # design even after the traveling marker stops being drawn. [kbdnav="true"]
                # alone answers "is keyboard mode active", which stays true through the
                # marker's OWN idle self-fade — a different question from "is the marker
                # actually visible right now", so that alone left the highlight lit long
                # after the fade finished: reported live 2026-09-08, "the marker disappears
                # after inactivity, but the highlight lingers until I hover with mouse
                # somewhere or press arrows or Tab." kbdnav_marker_active is set by
                # MainWindow._on_focus_marker_dormant_changed, called directly from
                # TravelingFocusMarker on every dormant<->active transition. Must be its own
                # rule in THIS per-instance setStyleSheet regardless, since it wins over any
                # shared panel-level QSS — same reason :hover/:pressed need restating above.
                f"QWidget#sleep_panel[kbdnav=\"true\"][kbdnav_marker_active=\"true\"] QPushButton:focus {{ "
                f"background-color: rgb({hover_c.red()}, {hover_c.green()}, {hover_c.blue()}); }}"
                # Keyboard-mode hover suppression, same contract/reasoning as Settings'
                # #pattern_button rules (get_settings_stylesheet): while the keyboard is
                # driving, the button the MOUSE happens to rest on (a DIFFERENT one than the
                # keyboard-focused button, ordinarily) must not also light up — otherwise two
                # cells claim "you are here" at once. An ancestor-scoped selector written
                # inside a per-instance stylesheet still resolves normally against the real
                # ancestor's live property (confirmed — Qt's cascade is not scoped to where a
                # rule was SET, only to what it selects), so this can live right here instead
                # of needing a second injection point.
                f"QWidget#sleep_panel[kbdnav=\"true\"] QPushButton:hover {{ "
                f"background-color: rgb({c.red()}, {c.green()}, {c.blue()}); }}"
                f"QWidget#sleep_panel[kbdnav=\"true\"] QPushButton:focus:hover {{ "
                f"background-color: rgb({hover_c.red()}, {hover_c.green()}, {hover_c.blue()}); }}"
            )

    def begin_ramp_highlight_fade(self, btn) -> None:
        """Called by MainWindow when the traveling marker starts fading on `btn` —
        see SpeedControlsPanel.begin_ramp_highlight_fade for the full explanation
        (identical contract, mirrored here for the sleep-duration ramp)."""
        if btn not in self._sleep_presets_buttons:
            return
        hover_color = getattr(btn, '_ramp_hover_color', None)
        base_color = getattr(btn, '_ramp_base_color', None)
        if hover_color is None or base_color is None:
            return
        self._ramp_highlight_fade.begin(
            btn, hover_color, base_color,
            'QWidget#sleep_panel[kbdnav="true"][kbdnav_marker_active="true"] QPushButton:focus'
        )

    def cancel_ramp_highlight_fade(self) -> None:
        """Called by MainWindow whenever the marker resumes patrol — see
        SpeedControlsPanel.cancel_ramp_highlight_fade."""
        self._ramp_highlight_fade.cancel()

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
        # Detect a seek settling (is_seeking True->False) since the last poll. A seek
        # that lands back in the anchor chapter never fires chapter_changed (the
        # index didn't move), so _on_chapter_changed never runs to consume the
        # user_seek_pending flag that seek_async set — left uncleared, it would
        # falsely tag the NEXT chapter transition (possibly a natural one) as
        # seek-driven. Confirmed live (2026-08-10, VT book): seek_within_chapter
        # left the flag stuck True until the real end-of-chapter crossing wrongly
        # inherited it. Only consumed here when the settled seek stayed within the
        # anchor chapter — a settle that crossed OUT of it is still _on_chapter_changed's
        # to decide (real forward crossing = show the cancellation).
        currently_seeking = self.player.is_seeking
        if self._was_seeking and not currently_seeking:
            if (self._sleep_mode == 'end_of_chapter'
                    and self._sleep_eoc_anchor is not None
                    and self._current_chapter_index() == self._sleep_eoc_anchor):
                self.player.user_seek_pending = False
        self._was_seeking = currently_seeking
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
                # Set AFTER disable_sleep_timer() (which clears it for the next
                # arm/disarm cycle) so it's live for _advance_or_finish's guard at
                # the moment this pause actually lands — see sleep_fired's docstring
                # in Player.__init__.
                self.player.sleep_fired = True
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
                # not "whatever chapter is current". A forward crossing past the anchor
                # (whether natural or seek-driven) is detected via chapter_changed and
                # handled by _on_chapter_changed, which decides whether to cancel with a
                # message (seek-driven) or leave this branch to fire normally (natural —
                # user_seek_pending stays False, so _on_chapter_changed no-ops and this
                # boundary check below fires exactly as it always has).
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
                    # Set AFTER disable_sleep_timer() (which clears it for the next
                    # arm/disarm cycle) so it's live for _advance_or_finish's guard
                    # at the moment this pause actually lands — see sleep_fired's
                    # docstring in Player.__init__.
                    self.player.sleep_fired = True
                    try:
                        self.player.pause = True
                    except (ShutdownError, AttributeError, SystemError):
                        pass
                    self.timer_expired.emit()
                else:
                    # Fade Logic — mirrors the timed-mode ratio above (remaining /
                    # effective_fade), but "remaining" is playback DISTANCE to the
                    # anchor's end rather than wall-clock seconds, and the cap is
                    # _sleep_eoc_distance_at_arm (fixed at arm time) rather than
                    # _total_timer_duration. Recomputed fresh every tick from live
                    # player_pos, so it's naturally seek-tolerant both ways: a
                    # forward seek within the anchor chapter yields a lower ratio
                    # (more faded) on the very next tick, a backward seek yields a
                    # higher one (recovers) — confirmed as the wanted behavior
                    # (Pryme, 2026-09-18) rather than a one-way ratchet. The cap
                    # itself does NOT reopen on a backward seek past the arm
                    # point — deliberately frozen for the whole arm cycle, same
                    # as timed mode's _total_timer_duration never changing either.
                    remaining = anchor_end - player_pos
                    effective_fade = min(self._current_sleep_fade,
                                          self._sleep_eoc_distance_at_arm or 0.0)
                    if effective_fade > 0 and remaining <= effective_fade:
                        ratio = max(0.0, remaining / effective_fade)
                        self.player.set_fade_ratio(ratio)
        # Gated on _sleep_mode, NOT unconditional: this used to fire every single
        # 200ms tick regardless of whether sleep was armed at all, always sending
        # "" when it wasn't. That's harmless in isolation (disable_sleep_timer()
        # already emits its own "" on the actual disarm transition, so this was
        # merely redundant) — but display_text_updated feeds a label SHARED with
        # SprintPanel (sleep_timer_label / vol_stack page 0), and sleep's repeated
        # "" emits were clobbering sprint's own countdown/grace text on every tick
        # sleep wasn't armed, corrupting sprint's own old-text tracking in
        # _on_sprint_display_text_updated and disrupting its message-dismiss timing
        # and mute-transient logic. Confirmed live, 2026-08-11. Only emit here when
        # sleep actually has something to say.
        if self._sleep_mode is not None:
            self.display_text_updated.emit(display_text)
