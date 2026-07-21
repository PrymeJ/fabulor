import cProfile
import io
import logging
import os
import pstats
import time
from PySide6.QtWidgets import QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QGridLayout
from PySide6.QtWidgets import QLineEdit, QApplication
from PySide6.QtCore import QPoint, QPropertyAnimation, QAbstractAnimation, QTimer, Qt
from .title_bar import ThemeItem
from .transport_bar_blur import TransportBarBlurOverlay

logger = logging.getLogger(__name__)

# TEMPORARY (library-panel stutter investigation, 2026-07-17): profile the exact
# library-open window (_start_library_entry through _on_library_shown) to find what's
# actually consuming wall-clock time, rather than guessing which function to instrument.
# Enabled via env var so it never runs unless explicitly requested. Remove once the
# stutter's root cause is found. See NOTES.md / TODO.md 2026-07-16/17 entry.
_STUTTER_PROFILE_ENABLED = os.environ.get("FABULOR_STUTTER_PROFILE") == "1"

class PanelManager:
    def __init__(self, main_window):
        self.main_window = main_window
        self.config = main_window.config # Access config through main_window
        
        # State variables
        self.sidebar_expanded = False
        self._pending_panel_open = None
        self._sidebar_panel_signal_connected = False
        
        # Widgets (references passed from MainWindow)
        self.sidebar = main_window.sidebar
        self.library_panel = main_window.library_panel
        self.settings_panel = main_window.settings_panel
        self.speed_panel = main_window.speed_panel
        self.sleep_panel = main_window.sleep_panel
        self.stats_panel = main_window.stats_panel
        self.blur_effect = main_window.blur_effect # Reference to the blur effect
        self.blur_animation = main_window.blur_animation # Reference to the blur animation

        # Animations (initialized in MainWindow, referenced here)
        self.sidebar_animation = main_window.sidebar_animation
        self.library_panel_animation = main_window.library_panel_animation
        self.settings_panel_animation = main_window.settings_panel_animation
        self.speed_panel_animation = main_window.speed_panel_animation
        self.sleep_panel_animation = main_window.sleep_panel_animation
        self.stats_panel_animation = main_window.stats_panel_animation
        self.tags_panel_animation = main_window.tags_panel_animation
        self.tags_panel = main_window.tags_panel
        self.book_detail_panel: "BookDetailPanel | None" = None
        self.book_detail_panel_animation: QPropertyAnimation | None = None
        self.sidebar_animation.finished.connect(self._on_sidebar_hidden)

        # Connect sidebar buttons to panel opening methods
        self.main_window.library_trigger_btn.clicked.connect(self._open_library_flow)
        self.main_window.go_to_library_btn.clicked.connect(self._open_library_flow)
        self.main_window.settings_trigger_btn.clicked.connect(self._open_settings_flow)
        self.main_window.speed_trigger_btn.clicked.connect(self._open_speed_flow)
        self.main_window.sleep_trigger_btn.clicked.connect(self._open_sleep_flow)
        self.main_window.stats_trigger_btn.clicked.connect(self._open_stats_flow)
        self.main_window.tags_trigger_btn.clicked.connect(self._open_tags_flow)

        # Composited-overlay transport-bar blur (see ui/transport_bar_blur.py and the
        # accepted plan). Comparison branch — see blur-direct-widget for the
        # per-widget-effect alternative.
        self._transport_bar_blur = TransportBarBlurOverlay(main_window)
        # CACHED-FRAME REWORK (2026-07-20): a settings-tab switch (Themes/Look/
        # Library/Audio/Controls) changes what's visible inside settings_panel
        # itself, not inside the transport bar's own tracked widgets — the
        # overlay's _DirtyRectTracker would never see it as a Paint event on any
        # tracked widget, so it needs its own explicit one-time forced refresh.
        # force_refresh_now() itself no-ops if the overlay isn't currently active
        # (e.g. Stats/Tags/Speed/Sleep panels are open instead — mw.tabs only
        # exists inside settings_panel), so this connection is safe to leave
        # permanently wired regardless of which panel is actually open.
        main_window.tabs.currentChanged.connect(
            lambda _index: self._transport_bar_blur.force_refresh_now()
        )

    def _apply_transport_bar_blur(self, panel):
        # Clip to `panel`'s own geometry — nothing renders blurred outside what
        # the panel actually covers (e.g. total_time_label sits at the far right
        # of the content area by layout design, past settings_panel's narrower
        # 90%-width edge; that sliver must stay crisp, not just "technically
        # correct blur that peeks past the panel." Confirmed live, 2026-07-19.)
        if self.config.get_blur_enabled():
            self._transport_bar_blur.show_for_panel(panel)

    def _clear_transport_bar_blur(self):
        self._transport_bar_blur.hide_for_panel()

    def _toggle_sidebar(self):
        """Slides the sidebar in or out."""
        if self.sidebar_animation.state() == QAbstractAnimation.State.Running:
            return
        logger.debug(
            f"t={time.perf_counter():.6f} [_toggle_sidebar ENTRY] "
            f"sidebar_expanded(pre)={self.sidebar_expanded} "
            f"branch={'opening' if not self.sidebar_expanded else 'closing'}"
        )
        # Opening the sidebar (the gateway to every panel, and the target of a
        # right-click on the drag area / future panel hotkeys) while a main-
        # window theme fade is in flight must complete that fade cleanly first
        # — otherwise the fade's slider color animation is left stranded at an
        # old/intermediate color while the rest of the UI is already the new
        # theme ("mulatto theme"). complete_main_fade is a no-op if no fade is
        # running. See NOTES.md 2026-06-19. NOTE: this is the main-window path —
        # do NOT substitute snap_theme_forward here (that's Settings-oriented).
        tm = getattr(self.main_window, 'theme_manager', None)
        if tm:
            tm.complete_main_fade()

        sidebar_y = 32 + 24
        width = self.sidebar.width()

        if not self.sidebar_expanded:
            logger.debug(f"t={time.perf_counter():.6f} [sidebar.raise_ BEFORE]")
            self.sidebar.raise_()
            logger.debug(f"t={time.perf_counter():.6f} [sidebar.raise_ AFTER]")
            self.sidebar_animation.setStartValue(QPoint(-width, sidebar_y))
            self.sidebar_animation.setEndValue(QPoint(0, sidebar_y))
            self.sidebar_expanded = True
        else:
            self.sidebar_animation.setStartValue(QPoint(0, sidebar_y))
            self.sidebar_animation.setEndValue(QPoint(-width, sidebar_y))
            self.sidebar_expanded = False

        self.sidebar_animation.start()

    def _open_library_flow(self):
        # One overlay at a time: drop this open if any overlay is already present, mid-slide,
        # or a sidebar-handoff open is committed. A settled-open sidebar with nothing pending
        # is NOT blocked (that's the legitimate sidebar-button path). See is_overlay_open_or_committed.
        if self.is_overlay_open_or_committed():
            return
        self.main_window.library_panel.clear_tag_filter_if_active()
        self._complete_main_fade()
        self.library_panel.cancel_preload()
        self.main_window._save_current_progress()
        if self.sidebar_expanded:
            self._pending_panel_open = "library"
            if not self._sidebar_panel_signal_connected:
                self.sidebar_animation.finished.connect(self._on_sidebar_closed_for_panel)
                self._sidebar_panel_signal_connected = True
            self._toggle_sidebar()
        else:
            self._start_library_entry()

    def _start_library_entry(self):
        logger.debug(f"[STUTTER-TRACE] t={time.perf_counter():.6f} _start_library_entry: ENTRY")
        if _STUTTER_PROFILE_ENABLED:
            self._stutter_profiler = cProfile.Profile()
            self._stutter_profiler.enable()
        self._flush_pending_restyle()  # before show() — see _flush_pending_restyle
        # Sync folder-button state to the live scan status — a scan may already be
        # running when the panel opens, in which case the buttons open disabled.
        self.main_window._set_scan_buttons_enabled(
            not self.main_window.scanner.is_running()
        )
        panel_w = self.main_window.width()
        sidebar_y = 32 # Start right under the TitleBar, covering the progress bar
        self.library_panel.setFixedWidth(panel_w)
        self.library_panel.setFixedHeight(self.main_window.height() - sidebar_y)
        self.library_panel.move(-panel_w, sidebar_y)
        self.library_panel.show()
        self.library_panel.raise_()

        # Set animation guard to prevent layout updates during slide
        self.library_panel._is_animating = True
        self.library_panel_animation.finished.connect(self._on_library_shown)

        self.library_panel_animation.setStartValue(QPoint(-panel_w, sidebar_y))
        self.library_panel_animation.setEndValue(QPoint(0, sidebar_y))
        logger.debug(f"[STUTTER-TRACE] t={time.perf_counter():.6f} library_panel_animation.start() "
                     f"duration={self.library_panel_animation.duration()}ms")
        self.library_panel_animation.start()
        
        if self.config.get_blur_enabled():
            self.blur_animation.setStartValue(0)
            self.blur_animation.setEndValue(10)
            self.blur_animation.start()

    def _on_library_shown(self):
        logger.debug(f"[STUTTER-TRACE] t={time.perf_counter():.6f} _on_library_shown: "
                     f"library_panel_animation FINISHED")
        if _STUTTER_PROFILE_ENABLED:
            self._stop_stutter_profile()
        try:
            self.library_panel_animation.finished.disconnect(self._on_library_shown)
        except RuntimeError:
            pass
        self.library_panel._is_animating = False
        self.library_panel._list_view.setUpdatesEnabled(True)
        logger.debug(f"[STUTTER-TRACE] t={time.perf_counter():.6f} _on_library_shown: "
                     f"calling refresh()")
        self.library_panel.refresh()
        logger.debug(f"[STUTTER-TRACE] t={time.perf_counter():.6f} _on_library_shown: "
                     f"refresh() returned")
        # Small delay lets the event loop settle before first paint
        QTimer.singleShot(16, self.library_panel._list_view.viewport().update)

    def _stop_stutter_profile(self):
        """TEMPORARY (library-panel stutter investigation, 2026-07-17): stop the profiler
        started in _start_library_entry and dump the top time-consumers to the log. Brackets
        exactly the slide-in animation window (_start_library_entry through
        library_panel_animation.finished), where the user reports the stutter/pause actually
        happens — not after the panel is open."""
        prof = getattr(self, '_stutter_profiler', None)
        if prof is None:
            return
        prof.disable()
        self._stutter_profiler = None
        stream = io.StringIO()
        stats = pstats.Stats(prof, stream=stream).sort_stats('cumulative')
        stats.print_stats(40)
        logger.debug(f"[STUTTER-PROFILE] library-open window profile:\n{stream.getvalue()}")

    def _reveal_list_rows(self):
        view = self.library_panel._list_view
        # Find visible row range
        viewport = view.viewport()
        first = view.indexAt(viewport.rect().topLeft())
        last  = view.indexAt(viewport.rect().bottomRight())
        if not first.isValid():
            view.setUpdatesEnabled(True)
            viewport.update()
            return
        first_row = first.row()
        last_row  = last.row() if last.isValid() else first_row + 20
        
        self._reveal_rows = list(range(first_row, last_row + 1))
        if hasattr(self, '_reveal_timer') and self._reveal_timer is not None:
            self._reveal_timer.stop()
            self._reveal_timer.timeout.disconnect()
        self._reveal_timer = QTimer(self)
        self._reveal_timer.setInterval(16)  # ~60fps, one row per frame
        self._reveal_timer.timeout.connect(lambda: self._reveal_next_row(view))
        view.setUpdatesEnabled(True)
        view.viewport().update()  # blank canvas ready
        self._reveal_timer.start()

    def _reveal_next_row(self, view):
        if not self._reveal_rows:
            self._reveal_timer.stop()
            return
        row = self._reveal_rows.pop(0)
        idx = self.library_panel._book_model.index(row, 0)
        view.update(view.visualRect(idx))

    def _open_settings_flow(self):
        # One overlay at a time — see is_overlay_open_or_committed / _open_library_flow.
        if self.is_overlay_open_or_committed():
            return
        # NOT snap_theme_forward (Settings-tuned, explicitly wrong for a main-window-in-
        # flight fade — see _toggle_sidebar's comment). complete_main_fade is what actually
        # re-polishes the slider colors; matches every other _open_*_flow (2026-07-10 fix).
        self._complete_main_fade()
        """Hides sidebar first, then shows settings panel."""
        logger.debug(
            f"t={time.perf_counter():.6f} [_open_settings_flow ENTRY] "
            f"sidebar_expanded={self.sidebar_expanded} "
            f"sidebar_animation.state()={self.sidebar_animation.state()} "
            f"_sidebar_panel_signal_connected={self._sidebar_panel_signal_connected}"
        )
        if self.sidebar_expanded:
            self._pending_panel_open = "settings"
            if not self._sidebar_panel_signal_connected:
                self.sidebar_animation.finished.connect(self._on_sidebar_closed_for_panel)
                self._sidebar_panel_signal_connected = True
            logger.debug(f"t={time.perf_counter():.6f} [_open_settings_flow] queued: calling _toggle_sidebar to close first")
            self._toggle_sidebar()
        else:
            logger.debug(f"t={time.perf_counter():.6f} [_open_settings_flow] sidebar already collapsed: entering directly")
            self._start_settings_entry()

    def _start_settings_entry(self):
        """Starts the settings panel slide-in animation. This is called directly or via _on_sidebar_closed_for_panel."""
        self._flush_pending_restyle()  # before show() — see _flush_pending_restyle
        logger.debug(
            f"t={time.perf_counter():.6f} [_start_settings_entry ENTRY] "
            f"sidebar_expanded={self.sidebar_expanded} "
            f"sidebar.pos()={self.sidebar.pos()} "
            f"sidebar.isVisible()={self.sidebar.isVisible()} "
            f"sidebar_animation.state()={self.sidebar_animation.state()}"
        )
        self.main_window._sync_persist_filter_on_open()
        # excluded_books_popup is now parented to library_tab (not
        # MainWindow), so its position is relative to its own parent and
        # stays correct regardless of where the settings panel currently is
        # mid-slide — no need to wait for the slide-in animation to finish
        # before repositioning (that was only needed under the old
        # MainWindow-relative-coordinates architecture).
        self.main_window._reload_excluded_books()
        panel_w = int(self.main_window.width() * 0.9)
        sidebar_y = 56
        self.settings_panel.setFixedWidth(panel_w)
        self.settings_panel.move(-panel_w, sidebar_y)
        logger.debug(
            f"t={time.perf_counter():.6f} [_start_settings_entry] "
            f"BEFORE settings_panel.show()/raise_ "
            f"sidebar.pos()={self.sidebar.pos()} sidebar.isVisible()={self.sidebar.isVisible()}"
        )
        self.settings_panel.show()
        self.settings_panel.raise_()
        self._claim_panel_focus(self.settings_panel, panel_key="settings")
        logger.debug(
            f"t={time.perf_counter():.6f} [_start_settings_entry] "
            f"AFTER settings_panel.show()/raise_ "
            f"sidebar.pos()={self.sidebar.pos()} sidebar.isVisible()={self.sidebar.isVisible()}"
        )

        self.settings_panel_animation.setStartValue(QPoint(-panel_w, sidebar_y))
        self.settings_panel_animation.setEndValue(QPoint(0, sidebar_y))

        def _log_settings_slide_frame(value):
            logger.debug(
                f"t={time.perf_counter():.6f} [settings_panel_animation valueChanged] "
                f"panel_pos={value} "
                f"sidebar.pos()={self.sidebar.pos()} sidebar.isVisible()={self.sidebar.isVisible()} "
                f"sidebar_expanded={self.sidebar_expanded}"
            )

        def _on_settings_slide_finished():
            logger.debug(f"t={time.perf_counter():.6f} [settings_panel_animation finished]")
            try:
                self.settings_panel_animation.valueChanged.disconnect(_log_settings_slide_frame)
                self.settings_panel_animation.finished.disconnect(_on_settings_slide_finished)
            except (TypeError, RuntimeError):
                pass
            self._apply_transport_bar_blur(self.settings_panel)

        self.settings_panel_animation.valueChanged.connect(_log_settings_slide_frame)
        self.settings_panel_animation.finished.connect(_on_settings_slide_finished)

        self.settings_panel_animation.start()
        logger.debug(
            f"t={time.perf_counter():.6f} [_start_settings_entry] "
            f"settings_panel_animation.start() called "
            f"sidebar.pos()={self.sidebar.pos()} sidebar.isVisible()={self.sidebar.isVisible()}"
        )

        if self.config.get_blur_enabled():
            self.blur_animation.setStartValue(0)
            self.blur_animation.setEndValue(10)
            self.blur_animation.start()
        else:
            self.blur_effect.setBlurRadius(0)

    def _open_speed_flow(self):
        # One overlay at a time — see is_overlay_open_or_committed / _open_library_flow.
        if self.is_overlay_open_or_committed():
            return
        self._complete_main_fade()
        if self.sidebar_expanded:
            self._pending_panel_open = "speed"
            if not self._sidebar_panel_signal_connected:
                self.sidebar_animation.finished.connect(self._on_sidebar_closed_for_panel)
                self._sidebar_panel_signal_connected = True
            self._toggle_sidebar()
        else:
            self._start_speed_entry()

    def _start_speed_entry(self):
        """Starts the speed panel slide-in animation. This is called directly or via _on_sidebar_closed_for_panel."""
        self._flush_pending_restyle()  # before show() — see _flush_pending_restyle
        self.main_window.speed_panel.sync_smart_rewind_visuals()
        self.main_window.speed_panel._rebuild_def_speed_row()
        panel_w = int(self.main_window.width() * 0.9)
        sidebar_y = 56
        self.speed_panel.setFixedWidth(panel_w)
        self.speed_panel.move(-panel_w, sidebar_y)
        self.speed_panel.show()
        self.speed_panel.raise_()
        self._claim_panel_focus(self.speed_panel, panel_key="speed")

        self.speed_panel_animation.setStartValue(QPoint(-panel_w, sidebar_y))
        self.speed_panel_animation.setEndValue(QPoint(0, sidebar_y))

        def _on_speed_slide_finished():
            try:
                self.speed_panel_animation.finished.disconnect(_on_speed_slide_finished)
            except (TypeError, RuntimeError):
                pass
            self._apply_transport_bar_blur(self.speed_panel)

        self.speed_panel_animation.finished.connect(_on_speed_slide_finished)
        self.speed_panel_animation.start()

        if self.config.get_blur_enabled():
            self.blur_animation.setStartValue(0)
            self.blur_animation.setEndValue(10)
            self.blur_animation.start()

    def _on_sidebar_closed_for_panel(self):
        """Handler for sidebar animation finishing when a panel needs to open.

        Re-arm guard (fixes the sidebar-bleed-through bug — see NOTES.md 2026-07-01):
        the queued-open pattern in the six `_open_*_flow` methods calls `_toggle_sidebar()`
        to close the sidebar, but that call SILENTLY NO-OPS if a sidebar animation from a
        prior toggle is still running (its `state() == Running` guard). If that happens,
        the close never starts, yet this handler is still wired to `finished` — so the
        already-running (OPENING) animation's `finished` would otherwise dispatch the panel
        with the sidebar still fully expanded at x=0, visible through the panel's
        semi-transparent background.

        Fix: only dispatch once the sidebar is ACTUALLY collapsed. If `finished` fires while
        `sidebar_expanded` is still True (the dropped close never happened / this `finished`
        belonged to an opening animation), re-issue the close and keep waiting for the next
        `finished` — do not dispatch, do not disconnect.

        Termination: each re-arm issues exactly one `_toggle_sidebar()` close and returns;
        it is driven by the `finished` signal, not recursion. `sidebar_expanded` can only flip
        back to True via an OPENING `_toggle_sidebar()`, whose sole reachable trigger during
        the wait is a physical user right-click on the drag area — nothing re-opens
        automatically, so this cannot self-perpetuate. A stray extra user toggle mid-wait just
        costs one more re-arm cycle and converges once toggling stops and a close lands with
        `sidebar_expanded == False`. Even if a re-issued toggle were itself a no-op, the
        handler simply re-arms again on the next `finished`; the invariant "never dispatch
        while `sidebar_expanded`" holds regardless.
        """
        logger.debug(
            f"t={time.perf_counter():.6f} [_on_sidebar_closed_for_panel ENTRY] "
            f"sidebar_expanded={self.sidebar_expanded} "
            f"pending_panel_open={self._pending_panel_open!r}"
        )

        if self.sidebar_expanded:
            # The close we queued was dropped (or this `finished` came from an opening
            # animation). Stay armed, re-issue the close, and wait for the next `finished`.
            logger.debug(
                f"t={time.perf_counter():.6f} [_on_sidebar_closed_for_panel RE-ARM] "
                f"sidebar still expanded — re-issuing close, not dispatching"
            )
            self._toggle_sidebar()
            return

        if self._sidebar_panel_signal_connected:
            self.sidebar_animation.finished.disconnect(self._on_sidebar_closed_for_panel)
            self._sidebar_panel_signal_connected = False

        if self._pending_panel_open == "library": self._start_library_entry()
        elif self._pending_panel_open == "settings": self._start_settings_entry()
        elif self._pending_panel_open == "speed": self._start_speed_entry()
        elif self._pending_panel_open == "sleep": self._start_sleep_entry()
        elif self._pending_panel_open == "stats": self._start_stats_entry()
        elif self._pending_panel_open == "tags": self._start_tags_entry()
        logger.debug(
            f"t={time.perf_counter():.6f} [_on_sidebar_closed_for_panel EXIT] "
            f"dispatched={self._pending_panel_open!r} sidebar_expanded={self.sidebar_expanded}"
        )
        self._pending_panel_open = None

    def _close_library_flow(self):
        if self.library_panel_animation.state() == QAbstractAnimation.State.Running:
            logger.debug("[BOOKSWITCH-TRACE] _close_library_flow: already running, no-op return")
            return
        logger.debug(f"t={time.perf_counter():.6f} [BOOKSWITCH-TRACE] _close_library_flow: entry")
        panel_w = self.library_panel.width()
        sidebar_y = 32

        # Set animation guard
        self.library_panel._is_animating = True
        self.library_panel._list_view.setUpdatesEnabled(True)

        self.library_panel_animation.setStartValue(QPoint(0, sidebar_y))
        self.library_panel_animation.setEndValue(QPoint(-panel_w, sidebar_y))
        self.library_panel_animation.finished.connect(self._on_library_hidden)
        self.library_panel_animation.start()

        if self.config.get_blur_enabled():
            self.blur_animation.setStartValue(self.blur_effect.blurRadius())
            self.blur_animation.setEndValue(0)
            self.blur_animation.start()

    def _on_library_hidden(self):
        logger.debug(f"t={time.perf_counter():.6f} [BOOKSWITCH-TRACE] _on_library_hidden: entry")
        try:
            self.library_panel_animation.finished.disconnect(self._on_library_hidden)
        except RuntimeError:
            pass
        self.library_panel._is_animating = False
        self.library_panel._list_view.setUpdatesEnabled(True)
        self.library_panel.hide()
        # Symmetric with showEvent's _list_view.setFocus(): hiding a widget does NOT clear
        # Qt focus from it, so without this every subsequent keypress silently routes to the
        # now-invisible list view instead of MainWindow — the whole shortcut dispatcher goes
        # dead. MUST run AFTER hide() (confirmed live, traced): hide() on a still-focused
        # descendant makes Qt fall back and re-grant focus to that same (now hidden) widget —
        # clearing focus BEFORE hide() gets silently undone by hide() itself. Also must target
        # the actual focused widget (e.g. _list_view or search_field), not library_panel
        # itself — clearFocus() only acts on `self`, and the panel container never holds
        # focus directly, only its descendants do.
        focused = QApplication.focusWidget()
        if focused is not None and self.library_panel.isAncestorOf(focused):
            focused.clearFocus()
        mw = self.main_window
        # LOADING → RESTORING: the library slide-out is done, so the deadzone ends.
        mw._switch.library_revealed()
        player = getattr(mw, 'player', None)
        logger.debug(f"t={time.perf_counter():.6f} [BOOKSWITCH-TRACE] _on_library_hidden: "
                     f"about to call ungate_play, current_file={getattr(mw, 'current_file', None)!r} "
                     f"file_ready_deferred={mw._switch.file_ready_deferred} chaps_deferred={mw._switch.chaps_deferred}")
        if player:
            player.ungate_play()
        self._notify_panel_closed()
        if mw._switch.file_ready_deferred or mw._switch.chaps_deferred:
            QTimer.singleShot(50, mw._drain_deferred_file_ready)
        else:
            mw._apply_pending_cover_theme()

    def _close_speed_flow(self):
        """Slides the speed panel back out."""
        if self.speed_panel_animation.state() == QAbstractAnimation.State.Running:
            return
        panel_w = self.speed_panel.width()
        sidebar_y = 56
        self.speed_panel_animation.setStartValue(QPoint(0, sidebar_y))
        self.speed_panel_animation.setEndValue(QPoint(-panel_w, sidebar_y))
        self.speed_panel_animation.finished.connect(self._on_speed_hidden)
        self.main_window._validate_smart_rewind_settings()
        self.speed_panel_animation.start()
        self._clear_transport_bar_blur()

        if self.config.get_blur_enabled():
            self.blur_animation.setStartValue(self.blur_effect.blurRadius())
            self.blur_animation.setEndValue(0)
            self.blur_animation.start()

    def _on_speed_hidden(self):
        try:
            self.speed_panel_animation.finished.disconnect(self._on_speed_hidden)
        except RuntimeError:
            pass
        self.speed_panel.hide()
        self._release_panel_focus(self.speed_panel)
        self._notify_panel_closed()

    def _open_stats_flow(self):
        # One overlay at a time — see is_overlay_open_or_committed / _open_library_flow.
        if self.is_overlay_open_or_committed():
            return
        self._complete_main_fade()
        if self.sidebar_expanded:
            self._pending_panel_open = "stats"
            if not self._sidebar_panel_signal_connected:
                self.sidebar_animation.finished.connect(self._on_sidebar_closed_for_panel)
                self._sidebar_panel_signal_connected = True
            self._toggle_sidebar()
        else:
            self._start_stats_entry()

    def _start_stats_entry(self):
        self._flush_pending_restyle()  # before show() — see _flush_pending_restyle
        panel_w = int(self.main_window.width() * 0.9)
        sidebar_y = 56
        self.stats_panel.setFixedWidth(panel_w)
        self.stats_panel.move(-panel_w, sidebar_y)
        self.stats_panel.show()
        self.stats_panel.refresh_current_tab()
        self.stats_panel.raise_()
        self._claim_panel_focus(self.stats_panel)

        self.stats_panel_animation.setStartValue(QPoint(-panel_w, sidebar_y))
        self.stats_panel_animation.setEndValue(QPoint(0, sidebar_y))

        def _on_stats_slide_finished():
            try:
                self.stats_panel_animation.finished.disconnect(_on_stats_slide_finished)
            except (TypeError, RuntimeError):
                pass
            self._apply_transport_bar_blur(self.stats_panel)

        self.stats_panel_animation.finished.connect(_on_stats_slide_finished)
        self.stats_panel_animation.start()

        if self.config.get_blur_enabled():
            self.blur_animation.setStartValue(0)
            self.blur_animation.setEndValue(10)
            self.blur_animation.start()
        else:
            self.blur_effect.setBlurRadius(0)

    def _open_sleep_flow(self):
        # One overlay at a time — see is_overlay_open_or_committed / _open_library_flow.
        if self.is_overlay_open_or_committed():
            return
        self._complete_main_fade()
        """Hides sidebar first, then shows sleep panel."""
        if self.sidebar_expanded:
            self._pending_panel_open = "sleep"
            if not self._sidebar_panel_signal_connected:
                self.sidebar_animation.finished.connect(self._on_sidebar_closed_for_panel)
                self._sidebar_panel_signal_connected = True
            self._toggle_sidebar()
        else:
            self._start_sleep_entry()

    def _start_sleep_entry(self):
        """Starts the sleep panel slide-in animation."""
        self._flush_pending_restyle()  # before show() — see _flush_pending_restyle
        panel_w = int(self.main_window.width() * 0.9)
        sidebar_y = 56
        self.sleep_panel.setFixedWidth(panel_w)
        self.sleep_panel.move(-panel_w, sidebar_y)
        self.sleep_panel.show()
        self.sleep_panel.raise_()
        self._claim_panel_focus(self.sleep_panel, panel_key="sleep")

        self.sleep_panel_animation.setStartValue(QPoint(-panel_w, sidebar_y))
        self.sleep_panel_animation.setEndValue(QPoint(0, sidebar_y))

        def _on_sleep_slide_finished():
            try:
                self.sleep_panel_animation.finished.disconnect(_on_sleep_slide_finished)
            except (TypeError, RuntimeError):
                pass
            self._apply_transport_bar_blur(self.sleep_panel)

        self.sleep_panel_animation.finished.connect(_on_sleep_slide_finished)
        self.sleep_panel_animation.start()

        if self.config.get_blur_enabled():
            self.blur_animation.setStartValue(0)
            self.blur_animation.setEndValue(10)
            self.blur_animation.start()

    def _close_sleep_flow(self):
        """Slides the sleep panel back out."""
        if self.sleep_panel_animation.state() == QAbstractAnimation.State.Running:
            return
        panel_w = self.sleep_panel.width()
        sidebar_y = 56
        self.sleep_panel_animation.setStartValue(QPoint(0, sidebar_y))
        self.sleep_panel_animation.setEndValue(QPoint(-panel_w, sidebar_y))
        self.sleep_panel_animation.finished.connect(self._on_sleep_hidden)
        self.sleep_panel_animation.start()
        self._clear_transport_bar_blur()

        if self.config.get_blur_enabled():
            self.blur_animation.setStartValue(self.blur_effect.blurRadius())
            self.blur_animation.setEndValue(0)
            self.blur_animation.start()

    def _on_sleep_hidden(self):
        try:
            self.sleep_panel_animation.finished.disconnect(self._on_sleep_hidden)
        except RuntimeError:
            pass
        self.sleep_panel.hide()
        self._release_panel_focus(self.sleep_panel)
        self._notify_panel_closed()

    def _close_stats_flow(self):
        if self.stats_panel_animation.state() == QAbstractAnimation.State.Running:
            return
        panel_w = self.stats_panel.width()
        sidebar_y = 56
        self.stats_panel_animation.setStartValue(QPoint(0, sidebar_y))
        self.stats_panel_animation.setEndValue(QPoint(-panel_w, sidebar_y))
        self.stats_panel_animation.finished.connect(self._on_stats_hidden)
        self.stats_panel_animation.start()
        self._clear_transport_bar_blur()

        if self.config.get_blur_enabled():
            self.blur_animation.setStartValue(self.blur_effect.blurRadius())
            self.blur_animation.setEndValue(0)
            self.blur_animation.start()
        else:
            self.blur_effect.setBlurRadius(0)

    def _on_stats_hidden(self):
        try:
            self.stats_panel_animation.finished.disconnect(self._on_stats_hidden)
        except RuntimeError:
            pass
        self.stats_panel.hide()
        self._release_panel_focus(self.stats_panel)
        self._notify_panel_closed()

    def _open_tags_flow(self):
        # One overlay at a time — see is_overlay_open_or_committed / _open_library_flow.
        # NOTE: the tag-manager-from-book-detail transition (app.py
        # _on_open_tag_manager_from_detail) calls hide_all_panels() then singleShot(320,
        # _open_tags_flow); the book-detail close animation is 300ms, so by the time this
        # fires the detail panel is hidden and the gate is False — the transition still
        # works. If book-detail's close duration ever grows past ~320ms, revisit that
        # coupling (drive the open off the close `finished` signal instead of a fixed delay).
        if self.is_overlay_open_or_committed():
            return
        self._complete_main_fade()
        if self.sidebar_expanded:
            self._pending_panel_open = "tags"
            if not self._sidebar_panel_signal_connected:
                self.sidebar_animation.finished.connect(self._on_sidebar_closed_for_panel)
                self._sidebar_panel_signal_connected = True
            self._toggle_sidebar()
        else:
            self._start_tags_entry()

    def _start_tags_entry(self):
        self._flush_pending_restyle()  # before show() — see _flush_pending_restyle
        mw = self.main_window
        panel_w = self.tags_panel.width()
        sidebar_y = 56
        self.tags_panel.move(-panel_w, sidebar_y)
        self.tags_panel.show()
        self.tags_panel.refresh()
        self.tags_panel.raise_()
        self._claim_panel_focus(self.tags_panel)
        self.tags_panel_animation.setStartValue(QPoint(-panel_w, sidebar_y))
        self.tags_panel_animation.setEndValue(QPoint(0, sidebar_y))

        def _on_tags_slide_finished():
            try:
                self.tags_panel_animation.finished.disconnect(_on_tags_slide_finished)
            except (TypeError, RuntimeError):
                pass
            self._apply_transport_bar_blur(self.tags_panel)

        self.tags_panel_animation.finished.connect(_on_tags_slide_finished)
        self.tags_panel_animation.start()
        if mw.config.get_blur_enabled():
            self.blur_animation.setStartValue(0)
            self.blur_animation.setEndValue(8)
            self.blur_animation.start()

    def _close_tags_flow(self):
        if self.tags_panel_animation.state() == QAbstractAnimation.State.Running:
            return
        panel_w = self.tags_panel.width()
        sidebar_y = 56
        self.tags_panel_animation.setStartValue(QPoint(0, sidebar_y))
        self.tags_panel_animation.setEndValue(QPoint(-panel_w, sidebar_y))
        self.tags_panel_animation.finished.connect(self._on_tags_hidden)
        self.tags_panel_animation.start()
        self._clear_transport_bar_blur()
        if self.main_window.config.get_blur_enabled():
            self.blur_animation.setStartValue(self.blur_animation.currentValue() or 8)
            self.blur_animation.setEndValue(0)
            self.blur_animation.start()

    def _on_tags_hidden(self):
        try:
            self.tags_panel_animation.finished.disconnect(self._on_tags_hidden)
        except RuntimeError:
            pass
        self.tags_panel.hide()
        self._release_panel_focus(self.tags_panel)
        self._notify_panel_closed()

    def open_book_detail(self, book_data: dict, tab: str = 'stats', context: str = ''):
        # If the panel is already showing ANY book, a new open request is dropped entirely —
        # not just re-animated, not re-targeted to a different book. Without this, a book
        # already open in the background list could be swapped out from under the visible
        # panel (e.g. right-click a book to open detail, then arrow-key to a DIFFERENT book
        # and press Alt+Enter — that reused this same unconditional path and hijacked the
        # open panel onto the new book while still only ever showing one panel at a time).
        # The user must close the current panel first via an existing close path
        # (_close_book_detail_flow / the panel's own close button) before opening another.
        panel = self.main_window.book_detail_panel
        if panel.isVisible():
            return
        self._complete_main_fade()
        # Snapshot of the library's current search text, so tag chips (library context only)
        # can tell whether a given tag is already the active filter and render inert. A
        # snapshot (not a live callback) is sufficient: the library's search text cannot change
        # while the detail panel is open — reaching this panel requires leaving the library view
        # first, and there is no other UI path that edits the search field meanwhile.
        active_search_text = self.library_panel.search_field.text()
        panel.load_book(
            book_data, tab=tab, context=context, active_search_text=active_search_text)
        self._start_book_detail_entry()

    def _start_book_detail_entry(self):
        self._flush_pending_restyle()  # before show() — see _flush_pending_restyle
        panel_w = self.main_window.width()
        book_detail_panel_y = 32 # Position under the titlebar
        self.book_detail_panel.setFixedWidth(panel_w)
        self.book_detail_panel.setFixedHeight(self.main_window.height() - book_detail_panel_y)
        self.book_detail_panel.move(panel_w, book_detail_panel_y)
        self.book_detail_panel.show()
        self.book_detail_panel.raise_()
        self._claim_panel_focus(self.book_detail_panel)

        self.book_detail_panel_animation.setStartValue(QPoint(panel_w, book_detail_panel_y))
        self.book_detail_panel_animation.setEndValue(QPoint(0, book_detail_panel_y))
        self.book_detail_panel_animation.start()

    def _close_book_detail_flow(self):
        if self.book_detail_panel_animation.state() == QAbstractAnimation.State.Running:
            return
        panel_w = self.main_window.width()
        book_detail_panel_y = 32 # Position under the titlebar
        self.book_detail_panel_animation.setStartValue(QPoint(0, book_detail_panel_y))
        self.book_detail_panel_animation.setEndValue(QPoint(panel_w, book_detail_panel_y))
        self.book_detail_panel_animation.finished.connect(self._on_book_detail_hidden)
        self.book_detail_panel_animation.start()

    def _on_book_detail_hidden(self):
        try:
            self.book_detail_panel_animation.finished.disconnect(self._on_book_detail_hidden)
        except:
            pass
        self.book_detail_panel.hide()
        self._release_panel_focus(self.book_detail_panel)
        self._notify_panel_closed()

    def _close_settings_flow(self):
        """Slides the settings panel back out."""
        if hasattr(self.main_window, 'theme_manager'):
            self.main_window.theme_manager._on_theme_unhovered()
            self.main_window.theme_manager.snap_theme_forward()
        # Hide and collapse the excluded-books list explicitly on close —
        # belt-and-suspenders (reload() on the next open also collapses it),
        # and avoids it lingering visible for a frame while the panel starts
        # its slide-out.
        popup = getattr(self.main_window, 'excluded_books_popup', None)
        if popup and popup.isVisible():
            popup.set_expanded(False)
            popup.hide()
            self.main_window.excluded_books_section.set_expanded(False)
        if self.settings_panel_animation.state() == QAbstractAnimation.State.Running:
            return
        panel_w = self.settings_panel.width()
        sidebar_y = 56
        self.settings_panel_animation.setStartValue(QPoint(0, sidebar_y))
        self.settings_panel_animation.setEndValue(QPoint(-panel_w, sidebar_y))
        self.settings_panel_animation.finished.connect(self._on_settings_hidden)
        self.settings_panel_animation.start()
        self._clear_transport_bar_blur()

        if self.config.get_blur_enabled():
            self.blur_animation.setStartValue(self.blur_effect.blurRadius())
            self.blur_animation.setEndValue(0)
            self.blur_animation.start()
        else:
            self.blur_effect.setBlurRadius(0)

    def _on_settings_hidden(self):
        try:
            self.settings_panel_animation.finished.disconnect(self._on_settings_hidden)
        except:
            pass
        self.settings_panel.hide()
        self._release_panel_focus(self.settings_panel)
        self._notify_panel_closed()

    def _on_sidebar_hidden(self):
        logger.debug(
            f"t={time.perf_counter():.6f} [_on_sidebar_hidden ENTRY] "
            f"sidebar_expanded={self.sidebar_expanded}"
        )
        if not self.sidebar_expanded:
            self._notify_panel_closed()

    def _notify_panel_closed(self):
        if self.is_any_panel_visible():
            return
        tm = getattr(self.main_window, 'theme_manager', None)
        if tm:
            tm._fire_pending_rotation()

    def _complete_main_fade(self):
        """Main-window theme-fade-in-flight guard for every panel-open flow that can be
        reached WITHOUT going through _toggle_sidebar (direct-open branch of each
        _open_*_flow, and open_book_detail). complete_main_fade is the same call
        _toggle_sidebar already makes before a right-click-driven sidebar open — it fully
        re-polishes the slider @Property colors via _apply_stylesheets, unlike
        abort_theme_fade (stops animations but never re-polishes, stranding sliders at an
        intermediate color) or snap_theme_forward (Settings-panel-tuned, explicitly wrong
        for the main window per _toggle_sidebar's own comment). No-op if no fade is running
        (ThemeManager.complete_main_fade's own guard). Was previously named
        _abort_theme_fade and called theme_manager.abort_theme_fade() — renamed and
        rewired 2026-07-10 after confirming via live focus-trace-style investigation that
        the keyboard-shortcut panel-open path (T then L/G/P/A/S/Z) bypasses
        _toggle_sidebar entirely when the sidebar is collapsed, so it never reached
        complete_main_fade and left sliders stranded mid-fade under the newly-opened
        panel — a gap anticipated in NOTES.md 2026-06-19 but not caught when the six
        shortcuts were added, because abort_theme_fade's name was conflated with
        complete_main_fade's actual behavior without diffing the two bodies."""
        tm = getattr(self.main_window, 'theme_manager', None)
        if tm:
            tm.complete_main_fade()

    def _flush_pending_restyle(self):
        """Run any pending deferred invisible-surface theme batch synchronously NOW,
        before a panel paints. Called at the top of every _start_*_entry (before
        show()) to cover the SIDEBAR-QUEUED open path: there _complete_main_fade runs
        early (in _open_*_flow) but the actual show() is dispatched ~200ms later from
        _on_sidebar_closed_for_panel, a window in which a book-load batch could arm and
        not-yet-run. Direct opens are already covered by _complete_main_fade's flush;
        this closes the queued gap at the true pre-show() instant. No-op if nothing
        pending. See plans/going-forward-on-this-twinkly-corbato.md §3."""
        tm = getattr(self.main_window, 'theme_manager', None)
        if tm:
            _was_pending = getattr(tm, '_deferred_restyle_pending', False)
            logger.debug(f"[STUTTER-TRACE] t={time.perf_counter():.6f} _flush_pending_restyle: "
                         f"CALLED was_pending={_was_pending}")
            tm.flush_deferred_restyle()

    def _any_panel_animating(self):
        """Returns True if any sliding panel or blur animation is currently running."""
        animations = [
            self.sidebar_animation,
            self.library_panel_animation,
            self.settings_panel_animation,
            self.speed_panel_animation,
            self.sleep_panel_animation,
            self.stats_panel_animation,
            self.blur_animation,
        ]
        if self.book_detail_panel_animation:
            animations.append(self.book_detail_panel_animation)
        return any(anim.state() == QAbstractAnimation.State.Running for anim in animations)

    def is_any_full_panel_visible(self):
        """Returns True if any full panel or the chapter-list overlay is open — i.e.
        everything is_any_panel_visible checks EXCEPT the sidebar. The L shortcut
        (SHOW_LIBRARY) uses this to no-op when a panel is already up while still
        allowing the sidebar-open case to flow through _open_library_flow's queued
        close-then-open."""
        return any([
            self.library_panel.isVisible(),
            self.settings_panel.isVisible(),
            self.speed_panel.isVisible(),
            self.sleep_panel.isVisible(),
            self.stats_panel.isVisible(),
            self.tags_panel.isVisible(),
            self.book_detail_panel.isVisible() if self.book_detail_panel else False,
            self.main_window.chapter_list_widget.isVisible(),
        ])

    def is_any_panel_visible(self):
        """Returns True if the sidebar or any configuration panel is currently open."""
        return self.sidebar_expanded or self.is_any_full_panel_visible()

    def is_any_panel_animating(self):
        """Returns True if any panel/sidebar slide animation is currently running.

        Gate for the idle cover preloader: panel SLIDE animation is the confirmed
        interference source (see the library slide-in jank investigation) — a background
        sized-cover LANCZOS batch landing mid-slide stalls the motion. This is distinct
        from is_any_panel_visible: an already-open, static panel is NOT interference
        (tested), so the preloader gates on animating, not on visible. book_detail_panel's
        animation is created lazily, so it's guarded with getattr."""
        anims = [
            self.sidebar_animation,
            self.library_panel_animation,
            self.settings_panel_animation,
            self.speed_panel_animation,
            self.sleep_panel_animation,
            self.stats_panel_animation,
            self.tags_panel_animation,
            self.book_detail_panel_animation,
        ]
        return any(
            a is not None and a.state() == QAbstractAnimation.State.Running
            for a in anims
        )

    def is_overlay_open_or_committed(self):
        """The single gate for 'ignore a second overlay-open request'. True if any full
        overlay is present or mid-animation, OR a panel-open is already committed but the
        panel hasn't shown yet (the sidebar-queued handoff sub-window).

        Deliberately EXCLUDES a bare expanded sidebar with nothing pending: opening the
        sidebar is not itself an overlay, and the queued-open path (_open_*_flow ->
        _toggle_sidebar close -> _on_sidebar_closed_for_panel dispatch) depends on being
        able to open a panel FROM the sidebar. `is_any_full_panel_visible` already excludes
        the sidebar; `is_any_panel_animating` reads the sidebar animation True only while it
        is actually sliding, so a settled-open sidebar with no _pending_panel_open is False.

        Every overlay-OPEN entry point must consult this first and drop (early-return) the
        request if it's True — see the entry-point guards in panels.py/app.py. `open_book_detail`
        is the one intentional exception: it opens only from within an already-open panel
        (library/stats/tags), never races a fresh open, so it is left ungated."""
        return (self.is_any_full_panel_visible()
                or self.is_any_panel_animating()
                or self._pending_panel_open is not None)

    # ── App-wide Tab/Escape policy support ───────────────────────────────────
    # These back the Tab/Escape branch in MainWindow.eventFilter. Kept here because
    # PanelManager already owns every _close_*_flow and the visible-panel priority chain
    # (handle_drag_area_right_click), so close-logic and "which panel is open" stay in one place.

    def active_full_panel(self):
        """Which single full panel/overlay is currently open, as a string key
        ('library'/'settings'/'speed'/'sleep'/'stats'/'tags'/'book_detail'/'chapter_list'),
        or None. Same visibility checks and priority order as handle_drag_area_right_click —
        there is no existing single accessor, so this centralizes it."""
        if self.library_panel.isVisible():
            return "library"
        if self.settings_panel.isVisible():
            return "settings"
        if self.speed_panel.isVisible():
            return "speed"
        if self.sleep_panel.isVisible():
            return "sleep"
        if self.stats_panel.isVisible():
            return "stats"
        if self.tags_panel.isVisible():
            return "tags"
        if self.book_detail_panel and self.book_detail_panel.isVisible():
            return "book_detail"
        if self.main_window.chapter_list_widget.isVisible():
            return "chapter_list"
        return None

    def escape_active_panel(self) -> bool:
        """Close whichever full panel is open, reusing its existing _close_*_flow. Returns True
        if something was closed, False if nothing was open. Invents no new close path — mirrors
        handle_drag_area_right_click's chain.

        Two deliberate exclusions (both return False, i.e. 'not handled here'):
        - book_detail: BookDetailPanel installs its OWN QApplication event filter in showEvent
          (after MainWindow's), so its Escape handler runs first and already closes/cancels —
          this method is never reached for Escape while detail is open.
        - chapter_list: it grabs keyboard focus when open and has its own keyPressEvent Escape
          (which also clears the digit-jump buffer/timer before fading out). Deferring to it
          preserves that cleanup and matches pre-existing behavior exactly."""
        panel = self.active_full_panel()
        if panel == "library":
            self._close_library_flow()
        elif panel == "settings":
            self._close_settings_flow()
        elif panel == "speed":
            self._close_speed_flow()
        elif panel == "sleep":
            self._close_sleep_flow()
        elif panel == "stats":
            self._close_stats_flow()
        elif panel == "tags":
            self._close_tags_flow()
        else:
            # None, book_detail, or chapter_list — see docstring; not closed here.
            return False
        return True

    def panel_tab_widgets(self, panel: str) -> list:
        """Focusable controls of `panel`, in tab order, for Tab cycling. Only settings/speed/
        sleep participate; every other context is a Tab no-op (returns []). Filters to widgets
        currently visible within the panel and whose focus policy accepts Tab, in findChildren
        order (== creation == visual order for these three, confirmed). Settings is scoped to the
        active tab; on the Themes tab the N generated theme swatches (ThemeItem — mode/bulk
        buttons are plain QPushButton) are excluded, since swatch-grid keyboard nav is deferred
        to a later arrows+space design."""
        if panel == "settings":
            root = self.main_window.tabs.currentWidget()
        elif panel == "speed":
            root = self.speed_panel
        elif panel == "sleep":
            root = self.sleep_panel
        else:
            return []
        if root is None:
            return []
        result = []
        for w in root.findChildren(QWidget):
            if isinstance(w, ThemeItem):
                continue  # deferred: theme swatches get their own arrows+space nav later
            if not w.isVisibleTo(root):
                continue
            if not (w.focusPolicy() & Qt.FocusPolicy.TabFocus):
                continue
            result.append(w)
        return result

    # ── Panel-local keyboard focus ownership ─────────────────────────────────
    # Enforces the invariant that MainWindow.keyPressEvent's _focus_allows_global_shortcuts
    # relies on: whenever a panel/overlay is open, SOME widget inside it must hold real Qt
    # focus, so a) that widget (not global shortcuts) has first-and-final say over every key,
    # and b) no OTHER panel's stale-focused widget can bleed through from underneath (Z-order
    # via raise_()/show() has zero effect on keyboard focus — only setFocus()/clearFocus() do).
    # Library and ChapterList already self-manage this (their own showEvent/show_above grab
    # focus); every other panel routes through these two helpers instead of duplicating the
    # isAncestorOf/ordering logic six times.

    def _claim_panel_focus(self, panel_widget, panel_key: str = None):
        """Call once a panel/overlay has been shown and raised, to give it real Qt focus.
        Prefers the first Tab-order-eligible child (panel_tab_widgets, panel_key given) —
        the same target Tab-cycling already treats as "first" — so opening a panel and then
        pressing Tab immediately continues into its SECOND control, not its first, matching
        the existing Tab-cycle's own notion of order. Falls back to the panel widget itself
        (granting it StrongFocus if it doesn't already accept focus) when there's no
        Tab-order list for it (stats/tags/book_detail) or the list is empty."""
        target = None
        if panel_key is not None:
            widgets = self.panel_tab_widgets(panel_key)
            if widgets:
                target = widgets[0]
        if target is None:
            if not (panel_widget.focusPolicy() & Qt.FocusPolicy.StrongFocus):
                panel_widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            target = panel_widget
        target.setFocus(Qt.FocusReason.OtherFocusReason)

    def _release_panel_focus(self, panel_widget):
        """Call AFTER panel_widget.hide(), symmetric with _claim_panel_focus. Ordering is
        load-bearing (confirmed live): hide() on a still-focused descendant makes Qt fall
        back and re-grant focus to that same now-hidden widget, so clearing BEFORE hide()
        gets silently undone by hide() itself. Must target the actual focused widget, not
        panel_widget — clearFocus() only acts on `self`, and a container rarely holds focus
        directly, only its descendants do."""
        focused = QApplication.focusWidget()
        if focused is not None and panel_widget.isAncestorOf(focused):
            focused.clearFocus()

    def dismiss_sidebar(self):
        """Closes the sidebar if it's expanded; no-op otherwise. Idempotent (safe to call
        from an action that doesn't know the sidebar's current state). For actions that
        should get the sidebar out of the way WITHOUT closing an already-open panel (which
        is_overlay_open_or_committed already prevents from coexisting) — e.g. opening the
        chapter list, toggling the time label, wheel-scrolling the speed label or the
        chapter-progress slider. Mirrors the `if sidebar_expanded: _toggle_sidebar()` line
        inside hide_all_panels(); pulled out so single-purpose callers don't need the whole
        close-everything sweep."""
        if self.sidebar_expanded:
            self._toggle_sidebar()

    def hide_all_panels(self):
        """Closes any open panels."""
        if self.main_window.chapter_list_widget.isVisible():
            self.main_window.chapter_list_widget.fade_out()
        if self.sidebar_expanded:
            self._toggle_sidebar()
        if self.library_panel.isVisible():
            self._close_library_flow()
        if self.settings_panel.isVisible():
            self._close_settings_flow()
        if self.speed_panel.isVisible():
            self._close_speed_flow()
        if self.sleep_panel.isVisible():
            self._close_sleep_flow()
        if self.stats_panel.isVisible():
            self._close_stats_flow()
        if self.tags_panel.isVisible():
            self._close_tags_flow()
        if self.book_detail_panel and self.book_detail_panel.isVisible():
            self._close_book_detail_flow()

    def handle_mouse_press(self, event):
        """Handles mouse press events to prevent panel dismissal when clicking inside."""
        panels = [self.library_panel, self.settings_panel, self.speed_panel, self.sleep_panel, self.stats_panel]
        if self.book_detail_panel:
            panels.append(self.book_detail_panel)
        for panel in panels:
            if panel.isVisible() and panel.geometry().contains(event.pos()):
                return True
        return False

    def handle_drag_area_right_click(self, event):
        """Handles right-click on drag area to dismiss panels or toggle sidebar."""
        logger.debug(
            f"t={time.perf_counter():.6f} [handle_drag_area_right_click ENTRY] "
            f"library={self.library_panel.isVisible()} "
            f"settings={self.settings_panel.isVisible()} "
            f"speed={self.speed_panel.isVisible()} "
            f"sleep={self.sleep_panel.isVisible()} "
            f"stats={self.stats_panel.isVisible()} "
            f"tags={self.tags_panel.isVisible()} "
            f"book_detail={bool(self.book_detail_panel and self.book_detail_panel.isVisible())} "
            f"chapter_list={self.main_window.chapter_list_widget.isVisible()} "
            f"sidebar_expanded={self.sidebar_expanded}"
        )
        self.library_panel.cancel_preload()
        if self.library_panel.isVisible():
            logger.debug(f"t={time.perf_counter():.6f} [handle_drag_area_right_click] branch=close_library")
            self._close_library_flow()
        elif self.settings_panel.isVisible():
            logger.debug(f"t={time.perf_counter():.6f} [handle_drag_area_right_click] branch=close_settings")
            self._close_settings_flow()
        elif self.speed_panel.isVisible():
            logger.debug(f"t={time.perf_counter():.6f} [handle_drag_area_right_click] branch=close_speed")
            self._close_speed_flow()
        elif self.sleep_panel.isVisible():
            logger.debug(f"t={time.perf_counter():.6f} [handle_drag_area_right_click] branch=close_sleep")
            self._close_sleep_flow()
        elif self.stats_panel.isVisible():
            logger.debug(f"t={time.perf_counter():.6f} [handle_drag_area_right_click] branch=close_stats")
            self._close_stats_flow()
        elif self.tags_panel.isVisible():
            logger.debug(f"t={time.perf_counter():.6f} [handle_drag_area_right_click] branch=close_tags")
            self._close_tags_flow()
        elif self.book_detail_panel and self.book_detail_panel.isVisible():
            logger.debug(f"t={time.perf_counter():.6f} [handle_drag_area_right_click] branch=close_book_detail")
            self._close_book_detail_flow()
        elif self.main_window.chapter_list_widget.isVisible():
            logger.debug(f"t={time.perf_counter():.6f} [handle_drag_area_right_click] branch=chapter_list_fade_out")
            self.main_window.chapter_list_widget.fade_out()
        else:
            logger.debug(f"t={time.perf_counter():.6f} [handle_drag_area_right_click] branch=toggle_sidebar (no panel visible)")
            self._toggle_sidebar()

    def resize_panels(self):
        """Adjusts panel positions and sizes on window resize."""
        sidebar_y = 56 # 32 title + 24 progress for most panels
        library_y = 32 # 32 title for Library panel
        window_w = self.main_window.width()
        panel_w = int(self.main_window.width() * 0.9)
        
        # Hardcoded heights as requested
        self.sidebar.setFixedHeight(200)
        self.library_panel.setFixedWidth(window_w)
        self.library_panel.setFixedHeight(self.main_window.height() - library_y)

        for panel in [self.settings_panel, self.speed_panel, self.sleep_panel, self.stats_panel, self.tags_panel]:
            panel.setFixedWidth(panel_w)

        self.settings_panel.setFixedHeight(500)
        self.speed_panel.setFixedHeight(500)
        self.sleep_panel.setFixedHeight(500)
        self.stats_panel.setFixedHeight(500)
        self.tags_panel.setFixedHeight(500)

        # Update Speed Panel position if not animating
        if self.speed_panel_animation.state() != QAbstractAnimation.State.Running:
            x = 0 if self.speed_panel.isVisible() else -panel_w
            self.speed_panel.move(x, sidebar_y)

        # Ensure sidebar position is maintained during resize
        sidebar_x = 0 if self.sidebar_expanded else -self.sidebar.width()
        self.sidebar.move(sidebar_x, sidebar_y)
            
        # Update Library Panel position if not animating
        if self.library_panel_animation.state() != QAbstractAnimation.State.Running:
            x = 0 if self.library_panel.isVisible() else -window_w
            self.library_panel.move(x, library_y)
            
        # Update Settings Panel position if not animating
        if self.settings_panel_animation.state() != QAbstractAnimation.State.Running:
            x = 0 if self.settings_panel.isVisible() else -panel_w
            self.settings_panel.move(x, sidebar_y)

        # Update Sleep Panel position if not animating
        if self.sleep_panel_animation.state() != QAbstractAnimation.State.Running:
            x = 0 if self.sleep_panel.isVisible() else -panel_w
            self.sleep_panel.move(x, sidebar_y)

        # Update Stats Panel position if not animating
        if self.stats_panel_animation.state() != QAbstractAnimation.State.Running:
            x = 0 if self.stats_panel.isVisible() else -panel_w
            self.stats_panel.move(x, sidebar_y)

        # Update Tags Panel position if not animating
        if self.tags_panel_animation.state() != QAbstractAnimation.State.Running:
            x = 0 if self.tags_panel.isVisible() else -panel_w
            self.tags_panel.move(x, sidebar_y)

        # Update Book Detail Panel position if not animating
        if self.book_detail_panel and self.book_detail_panel_animation and \
                self.book_detail_panel_animation.state() != QAbstractAnimation.State.Running:
            if self.book_detail_panel.isVisible():
                self.book_detail_panel.setFixedWidth(self.main_window.width())
                self.book_detail_panel.move(0, 32)
            self.book_detail_panel.setFixedHeight(self.main_window.height() - 32)