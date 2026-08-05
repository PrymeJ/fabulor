import cProfile
import io
import logging
import os
import pstats
import time
from PySide6.QtWidgets import QWidget, QLabel, QPushButton, QHBoxLayout, QVBoxLayout, QGridLayout
from PySide6.QtWidgets import QLineEdit, QApplication
from PySide6.QtCore import QPoint, QRect, QPropertyAnimation, QAbstractAnimation, QTimer, Qt
from .title_bar import ThemeItem
from .transport_bar_blur import TransportBarBlurOverlay, panel_rect_in_common_space

logger = logging.getLogger(__name__)

# TEMPORARY (library-panel stutter investigation, 2026-07-17): profile the exact
# library-open window (_start_library_entry through _on_library_shown) to find what's
# actually consuming wall-clock time, rather than guessing which function to instrument.
# Enabled via env var so it never runs unless explicitly requested. Remove once the
# stutter's root cause is found. See NOTES.md / TODO.md 2026-07-16/17 entry.
_STUTTER_PROFILE_ENABLED = os.environ.get("FABULOR_STUTTER_PROFILE") == "1"

# visual_area blur-in / blur-out durations. Deliberately ASYMMETRIC:
# blurring IN is a slow build matched to TransportBarBlurOverlay._FADE_IN_MS
# (1500) so both halves of the window blur together; clearing OUT stays snappy
# so the live view returns immediately as the panel starts sliding away, which
# also mirrors the transport bar's instant dismiss. Both are applied per
# direction because the two paths share one QPropertyAnimation object.
_BLUR_IN_MS = 1500
# Themes-tab exception (2026-07-28). Opening Settings onto the Themes tab uses a
# much shorter blur-in, because that is the one surface where the user's next
# action is expected to be a HOVER, and a hover cannot preview until the blur has
# settled (ThemeManager._on_theme_changed's animation guard — a restyle landing
# mid-tween freezes the blur for ~240ms, measured, so the guard must stay).
#
# Reported live: the first hover after opening Settings was dead for ~1.1s and
# "would make the user wonder if it is broken". Measured dead window, hover
# arriving 430ms after open (the real repro): 1091ms at 1500ms -> 0ms at 400ms.
# Worst case, hovering 50ms after open: 366ms. Crucially this introduces NO
# stall — worst frame gap stays ~17ms, identical to blur-alone baseline, because
# it moves the settle point earlier rather than letting a restyle collide with a
# running tween.
#
# Deliberately NOT a global reduction of _BLUR_IN_MS: every other panel keeps the
# 1500ms feel, since nowhere else is the user racing the blur. Revert by deleting
# this constant and its use in _start_visual_area_blur if the shorter blur-in
# reads as abrupt on that tab.
_BLUR_IN_THEMES_TAB_MS = 400
_BLUR_OUT_MS = 500

# Re-check cadence for call_when_panels_settled's settle watch. One frame at
# 60fps: caps the overshoot past the true settle instant at ~16ms, versus the
# up-to-700ms overshoot the theme guard's _PANEL_ANIM_GUARD_MS poll used to add
# on top of a 1500ms blur-in. Each tick is nine cheap QAbstractAnimation.state()
# reads, so ~90 wakeups across a blur-in is negligible.
_SETTLE_POLL_MS = 16

# Additional pause after a genuine hover-out snapback visibly settles, before the
# Settings-dismiss action it was blocking actually proceeds (2026-08-05, corrected
# snapback-timing spec v2 — see review/Design_260805_snapback_timing_v2.md).
# Makes the revert read as its own perceptible step ("revert, THEN close") rather
# than the dismiss's first frame landing in the same tick the fade completes.
# Starting value per Pryme's own stated range (100-200ms) — tune by live feel, not
# fixed by measurement; this is a UX-feel constant, not a correctness one. ONLY
# paid when a genuine snapback fade actually ran — see _close_settings_flow's own
# _fade_in_flight check, which the ordinary no-hover dismiss skips entirely.
_SNAPBACK_SETTLE_GAP_MS = 150

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
        # Which panel Book Detail was opened ON TOP OF, as a string key ('stats' /
        # 'tags' / 'library' / None). Written in open_book_detail, consumed once in
        # _resume_blur_after_book_detail. A key, not a widget, so the Library and
        # no-underlay cases stay explicit rather than silently falling through
        # generic panel handling.
        self._book_detail_underlay: str | None = None
        self.sidebar_animation.finished.connect(self._on_sidebar_hidden)

        # Settle watch for call_when_panels_settled (see that method). Deliberately
        # a predicate re-check rather than a `finished` subscription — QPropertyAnimation
        # .stop() does NOT emit `finished` (verified empirically 2026-07-28; also
        # asserted at theme_manager.py's three stop()-related comments), and
        # blur_animation.stop() runs unconditionally on every panel open
        # (_start_visual_area_blur) and on blur-toggle-off, so a signal-based resume
        # would be silently dropped exactly as it was three times against _fade_anim.
        #
        # timeout is connected ONCE, here, permanently: there is no per-call connect
        # anywhere in this mechanism, so a stale connection is unrepresentable and a
        # double-fire is structurally impossible.
        self._settled_watch_timer = QTimer(main_window)
        self._settled_watch_timer.setSingleShot(True)
        self._settled_watch_timer.setInterval(_SETTLE_POLL_MS)
        self._settled_watch_timer.timeout.connect(self._on_settled_watch_tick)
        self._settled_watch_armed = False
        # List of (coalesce_key, callback) tuples. coalesce_key is None for an
        # ordinary, always-appended waiter; a non-None key replaces any existing
        # waiter with the same key IN PLACE instead of appending a second entry —
        # see call_when_panels_settled's coalesce_key parameter.
        self._panels_settled_waiters: list = []
        # Deferred sidebar state for clicks arriving mid-slide — see _toggle_sidebar.
        # _sidebar_pending_target is the desired FINAL state (absolute), not a queued
        # toggle (relative); queueing toggles produced a runaway open/close cycle.
        self._sidebar_toggle_queued = False
        self._sidebar_pending_target = None

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

    # Book Detail sits at y=32; the progress slider occupies y=32..56 and the
    # window is 300x564. See _book_detail_frost_rect.
    _BOOK_DETAIL_FROST_TOP_UNDER_PROGRESS = 56
    _BOOK_DETAIL_FROST_TOP_UNDER_TITLEBAR = 32
    _BOOK_DETAIL_FROST_BOTTOM_INSET = 10

    def _book_detail_frost_rect(self) -> QRect:
        """The region Book Detail's frost should cover, in MAIN_WINDOW coords.

        Differs by what it opened over, because the two cases genuinely look
        different underneath (confirmed live 2026-08-01):

        - Over STATS (or any 90%-width panel): the player screen behind is
          already blurred by that panel's own visual_area blur, but the Stats
          panel ITSELF is sharp — and Stats is most of what is behind Book
          Detail. So the frost must start under the PROGRESS BAR (y=56) and run
          to 10px off the bottom, capturing Stats as content to be blurred. The
          progress bar is excluded because it animates; the bottom 10px is the
          panel's own padding.
        - Over LIBRARY: the library is full-width and opaque, so everything from
          under the TITLE BAR (y=32) down is real content that must be frosted.

        Bare geometry rather than reading widget rects: these are fixed-size
        chrome (window 300x564 via setFixedSize, title bar 32, progress slider
        24), and the panel-rect helpers map SETTLED positions, which is not what
        is wanted for a region defined against the window itself.
        """
        mw = self.main_window
        if self._book_detail_underlay == 'library':
            top = self._BOOK_DETAIL_FROST_TOP_UNDER_TITLEBAR
            bottom_inset = 0
        else:
            top = self._BOOK_DETAIL_FROST_TOP_UNDER_PROGRESS
            bottom_inset = self._BOOK_DETAIL_FROST_BOTTOM_INSET
        return QRect(0, top, mw.width(), mw.height() - top - bottom_inset)

    def _apply_transport_bar_blur_full(self, panel):
        """Frost Book Detail's own backdrop. See
        TransportBarBlurOverlay.frost_panel_backdrop for why this cannot reuse the
        shared overlay (Z-order: that overlay is a child of content_container and
        can never rise above a panel parented to main_window).

        Gated here rather than inside the overlay, matching _apply_transport_bar_blur
        — one get_blur_enabled() convention across every call site."""
        if self.config.get_blur_enabled():
            self._transport_bar_blur.frost_panel_backdrop(
                panel, self._book_detail_frost_rect())

    def _clear_transport_bar_blur(self):
        self._transport_bar_blur.hide_for_panel()

    def _suspend_blur_for_book_detail(self):
        """Tear down the underlying panel's blur when Book Detail opens over it.

        Book Detail is full window width at y=32 and content_container starts at
        y=56, so it covers the cover art, the transport bar, the carousel AND the
        underlying panel entirely — nothing the underlay's blur produces can be
        seen.

        Leaving it running is not merely wasted work. The transport overlay's
        _active_panel is still the UNDERLYING panel, so _grab_and_blur keeps hiding
        Stats (not Book Detail) and grabbing main_window — which photographs Book
        Detail INTO the cached pixmap and composites it back underneath itself.
        Measured self-sustaining at ~64ms / ~15 grabs per second (NOTES.md,
        2026-07-27, "grab feedback loop").

        The visual_area half must go too: it is fully occluded, and leaving its
        1500ms tween running would let _grab_and_blur bake a PARTIALLY blurred
        visual_area into Book Detail's own grab, then blur that again — a double
        blur whose strength depends on where the tween happened to be.

        Unconditional on get_blur_enabled(): every call below is a no-op when blur
        is off (hide_for_panel early-exits on _active=False, setBlurRadius(0) on an
        already-0 effect is free, _clear_visual_area_clip nulls an already-null
        clip), and being unconditional means a mid-session backdrop-mode change
        cannot strand a live blur.

        blur_animation.stop() here emits no `finished` — nothing subscribes to
        learn about it (see the _settled_watch_timer note in __init__), and it is
        the same call _start_visual_area_blur already makes.

        Symmetric with _resume_blur_after_book_detail. Deliberately reuses the same
        teardown calls every _close_*_flow uses — no new blur path.
        """
        self._clear_transport_bar_blur()
        self.blur_animation.stop()
        self.blur_effect.setBlurRadius(0)
        self._clear_visual_area_clip()

    def _resume_blur_after_book_detail(self):
        """Re-establish the underlying panel's blur once Book Detail is fully
        hidden. Symmetric with _suspend_blur_for_book_detail.

        Runs from _on_book_detail_hidden (AFTER .hide()), never from
        _close_book_detail_flow: a grab taken while Book Detail is still sliding
        out would photograph it into the cache, because _active_panel would by then
        be the underlying panel again and _grab_and_blur only ever hides
        _active_panel. That is the same corruption this change removes, just moved
        to the close side.

        The isVisible() re-check is load-bearing, not defensive padding.
        _on_open_tag_manager_from_detail (app.py) calls hide_all_panels() — closing
        BOTH Book Detail and Stats — then opens Tags 320ms later; and
        _on_tag_filter_requested closes Book Detail then opens Library. Without the
        check those paths would re-blur a panel that is mid-close or already hidden,
        stranding a frozen overlay over the transport bar with _active_panel
        pointing at an invisible widget.

        Cache invalidation is free: hide_for_panel already nulls the pixmap and
        _bounding_rect, and _apply_transport_bar_blur -> show_for_panel takes a
        mandatory full-rect first pass. A fresh show_for_panel IS the invalidation,
        so no force_refresh_now() is needed (it would no-op anyway — _active is
        False at this point).

        Library is deliberately absent from the map: it is full-width and opaque and
        never had either blur on open (see _apply_visual_area_clip's LIBRARY-PANEL
        EXCLUSION), so there is nothing to restore for it.
        """
        # Consuming read — same shape as take_dirty_union. A stale key must never
        # survive into the next Book Detail open.
        key, self._book_detail_underlay = self._book_detail_underlay, None
        panel = {
            'stats': self.stats_panel,
            'tags': self.tags_panel,
            'settings': self.settings_panel,
            'speed': self.speed_panel,
            'sleep': self.sleep_panel,
        }.get(key)
        if panel is None or not panel.isVisible():
            return
        self._apply_transport_bar_blur(panel)
        self._start_visual_area_blur(panel)

    def _start_visual_area_blur(self, panel):
        """Set the clip and run the visual_area blur-in — called ONLY from a
        panel's slide-FINISHED callback, never at panel-open.

        TIMING IS LOAD-BEARING (found live 2026-07-27): starting this at
        panel-open meant the cover art / theme background / quote card began
        blurring while the panel was still sliding, so the blur visibly ran
        ahead of the panel and briefly exposed a hard-edged clip boundary over
        content the panel had not covered yet. The transport bar has always
        applied its blur from the slide-finished callback
        (_apply_transport_bar_blur); this matches that, so the two halves of the
        window blur together once the panel is settled. Panel CLOSE is
        unaffected — clearing immediately at close-start is correct and already
        matches the transport bar.
        """
        if not self.config.get_blur_enabled():
            return
        self._apply_visual_area_clip(panel)
        # The carousel is a sibling of visual_area with its own effect — set its
        # clip now so it blurs in step rather than staying sharp.
        self.main_window.sync_carousel_blur(self.blur_effect.blurRadius(), True)
        self.blur_animation.stop()
        self.blur_animation.setDuration(self._blur_in_duration_for(panel))
        self.blur_animation.setStartValue(self.blur_effect.blurRadius())
        self.blur_animation.setEndValue(8 if panel is self.tags_panel else 10)
        self.blur_animation.start()

    def _blur_in_duration_for(self, panel):
        """Blur-in duration for `panel` — shorter when opening onto the Themes tab.

        See _BLUR_IN_THEMES_TAB_MS for the measurements and the rationale. In short:
        a theme hover cannot preview until the blur settles (the animation guard in
        ThemeManager._on_theme_changed, which must stay — a restyle landing mid-tween
        freezes the blur ~240ms), so on the one tab where hovering is the expected
        next action the 1500ms blur-in reads as a broken first hover.

        Only the tab ACTIVE AT OPEN TIME matters: switching to the Themes tab while
        Settings is already open starts no blur-in, so there is nothing to shorten.

        Tab test mirrors ThemeManager._on_theme_changed's own `themes_tab_active`
        (Themes is index 0) rather than inventing a second convention — but without
        its `settings_panel.isVisible()` clause, since this runs from the
        slide-finished callback where the panel's visibility state is not the thing
        being asked about.
        """
        if panel is not self.settings_panel:
            return _BLUR_IN_MS
        tabs = getattr(self.main_window, 'tabs', None)
        if tabs is not None and tabs.currentIndex() == 0:
            return _BLUR_IN_THEMES_TAB_MS
        return _BLUR_IN_MS

    def blurred_panel(self):
        """The panel the visual_area blur is currently clipped to, or None.

        Used by MainWindow._carousel_clip_rect: the carousel is a SIBLING of
        visual_area with its own effect, so it needs to know which panel edge to
        clip against. Returns None for the library panel — it is full-width and
        opaque, so nothing behind it blurs (see _apply_visual_area_clip)."""
        for panel in (self.settings_panel, self.speed_panel, self.sleep_panel,
                      self.stats_panel, self.tags_panel):
            if panel.isVisible():
                return panel
        return None

    def _apply_visual_area_clip(self, panel):
        """Confine visual_area's blur to the region `panel` actually occludes, so
        the sliver beside the panel stays sharp (cover art / theme bg_image /
        quotes all live in that one widget). Called from _start_visual_area_blur
        at slide-finished; paired with _clear_visual_area_clip on close.

        LIBRARY-PANEL EXCLUSION — the library panel is full window width
        (setFixedWidth(window_w) in _update_panel_geometry, unlike every other
        panel's int(width * 0.9)) and fully opaque, so it occludes everything:
        there is no sliver to keep sharp and nothing blurred under it is ever
        visible. It is therefore skipped ENTIRELY (null clip = no blur), not
        given a full-rect clip.

        That distinction is load-bearing, not an optimization (found live
        2026-07-27): a full-rect clip made the ambient CoverCarousel — which
        scrolls at ~30fps beneath visual_area in the no-book state — ghost and
        then freeze in place while the unblurred sliver kept animating. Blurring
        a region nobody can see, over live scrolling content, bought nothing and
        broke the carousel. Keeping this as its own explicit branch also means a
        future change to the library panel's width cannot silently reroute it
        into generic clip math.
        """
        mw = self.main_window
        effect = getattr(mw, 'blur_effect', None)
        if effect is None or not hasattr(effect, 'set_clip_rect'):
            return
        if panel is self.library_panel:
            effect.set_clip_rect(None)   # null = blur nothing
            return

        va = mw.visual_area
        common = mw.content_container
        panel_rect = panel_rect_in_common_space(panel, common)
        # panel_rect is in content_container space; the effect's clip must be in
        # visual_area-LOCAL space.
        va_top_left = va.mapTo(common, QPoint(0, 0))
        local = panel_rect.translated(-va_top_left.x(), -va_top_left.y())
        effect.set_clip_rect(local.intersected(va.rect()))

    def _clear_visual_area_clip(self):
        effect = getattr(self.main_window, 'blur_effect', None)
        if effect is not None and hasattr(effect, 'set_clip_rect'):
            effect.set_clip_rect(None)
        # Clear the sibling carousel's clip too, or it keeps a blurred band after
        # the panel is gone.
        self.main_window.sync_carousel_blur(0.0, False)

    def apply_blur_live(self, enabled: bool):
        """Apply or clear blur on the ALREADY-OPEN Settings panel the instant the
        Settings > Blur toggle is clicked, without needing a close/reopen. The
        toggle lives in the Settings panel, so settings_panel is the only panel
        this is ever reachable from — scope to it, don't try to handle others.

        Covers both blur mechanisms: the transport-bar composited overlay (the
        primary one — _apply/_clear_transport_bar_blur) AND the cover-image
        blur_effect (blur_animation 0<->10). The blur_effect ON side mirrors the
        existing OFF side in MainWindow.set_blur_selection (which already zeroes
        the radius when the toggle goes Off); this adds the missing ON direction so
        Off->On also re-blurs the cover image live (previously only On->Off worked).

        REQUIRED animation guard: bail if any panel/sidebar slide is running.
        Applying/clearing blur mid-animation is not something the two-button toggle
        UI should ever trigger, but 'this state is unreachable so no guard needed'
        is exactly the assumption that caused three regressions this session — the
        guard is one cheap line, so it's here, not assumed."""
        if not self.settings_panel.isVisible():
            return
        if self.is_any_panel_animating():
            return
        if enabled:
            self._apply_transport_bar_blur(self.settings_panel)
            # Immediate (not deferred to a slide-finished callback) is correct
            # here: the panel is already open and settled — this is the live
            # Settings > Blur toggle, not a panel-open transition.
            self._start_visual_area_blur(self.settings_panel)
        else:
            self._clear_transport_bar_blur()
            self.blur_animation.stop()
            self.blur_effect.setBlurRadius(0)
            self._clear_visual_area_clip()

    def _toggle_sidebar(self):
        """Slides the sidebar in or out.

        A toggle requested while the slide is running defers to a TARGET STATE, not a
        queued toggle (2026-07-28, second iteration — the first shipped a worse bug).

        History, because the first attempt is an instructive failure. Originally this
        returned early and silently discarded the click: measured live, 5 of 25 sidebar
        right-clicks (20%) vanished, four of them arriving inside the 300ms slide
        against a 408ms median click interval. Queueing the toggle instead fixed the
        drop and introduced something worse: each replay STARTED A NEW SLIDE, which
        then caught the next click, which queued, which replayed... Measured in the
        very next session: eight consecutive toggles at 306-322ms intervals, the
        sidebar sliding open/closed continuously and always one step behind the user,
        while the log cheerfully reported 26 clicks -> 26 toggles with zero losses.
        Reported as "26 clicks, 26 toggles is a problem by itself" — correctly.

        The root error was queueing a RELATIVE operation. A toggle means "invert
        whatever the state is"; deferring several of them makes the outcome depend on
        how many happened to land mid-slide, which is not what the user is expressing.
        They are asking for the sidebar to END UP somewhere. So the deferred value is
        now the desired FINAL state, and repeated clicks during one slide simply
        overwrite it — two clicks during a slide cancel out (target flips back), which
        is what "I clicked twice, it should be where it started" actually means.

        This also stops the self-perpetuating cycle at its source: if the pending
        target already matches where the running slide is heading, there is nothing to
        replay and no new slide is started.
        """
        if self.sidebar_animation.state() == QAbstractAnimation.State.Running:
            # Where the running slide is heading — NOT the current flag, which has
            # already been flipped by whoever started it.
            in_flight_target = self.sidebar_expanded
            # Each click during the slide inverts the pending target. First click:
            # opposite of the in-flight target. Second: back to it (a no-op, cancelled).
            base = (self._sidebar_pending_target
                    if self._sidebar_pending_target is not None else in_flight_target)
            self._sidebar_pending_target = not base
            logger.debug(
                f"t={time.perf_counter():.6f} [_toggle_sidebar] DEFERRED — slide in "
                f"flight heading to expanded={in_flight_target}; "
                f"pending_target={self._sidebar_pending_target}"
            )
            if self._sidebar_toggle_queued:
                return          # a replay is already scheduled; it reads the target
            self._sidebar_toggle_queued = True

            def _replay():
                self._sidebar_toggle_queued = False
                target = self._sidebar_pending_target
                self._sidebar_pending_target = None
                if target is None:
                    return
                # Re-check rather than assuming: the settle may arrive with another
                # animation still running (call_when_panels_settled waits on ALL of
                # them), or state may have changed via another path in the meantime.
                if self.sidebar_animation.state() == QAbstractAnimation.State.Running:
                    return
                if target == self.sidebar_expanded:
                    # Already where the user asked for — an even number of clicks
                    # landed during the slide and cancelled out. Starting a slide here
                    # is what produced the runaway open/close cycle.
                    logger.debug(
                        f"t={time.perf_counter():.6f} [_toggle_sidebar] deferred target "
                        f"already satisfied (expanded={self.sidebar_expanded}) — no slide"
                    )
                    return
                logger.debug(
                    f"t={time.perf_counter():.6f} [_toggle_sidebar] applying deferred "
                    f"target={target} (expanded={self.sidebar_expanded})"
                )
                self._toggle_sidebar()

            self.call_when_panels_settled(_replay)
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
        # SIDEBAR-VISIBILITY PROBE (2026-07-28). "App start: right click, no sidebar,
        # right click, no sidebar, right click, finally sidebar" — the flag flips and
        # the animation runs on ALL THREE, so the failure is between starting the
        # slide and the widget being on screen. Records what the animation was
        # actually told to do and where the widget is when it finishes, since three
        # hypotheses (width==0, _on_sidebar_hidden, resize_panels) have already been
        # ruled out by reading code alone.
        def _probe(_pre=self.sidebar_expanded):
            try:
                logger.warning(
                    f"[SIDEBAR-VIS] settled expanded={_pre} "
                    f"pos={self.sidebar.pos()} size={self.sidebar.size()} "
                    f"visible={self.sidebar.isVisible()} hidden={self.sidebar.isHidden()} "
                    f"parent_visible={self.sidebar.parentWidget().isVisible() if self.sidebar.parentWidget() else None} "
                    f"end={self.sidebar_animation.endValue()} "
                    f"opacity={self.sidebar.windowOpacity()}"
                )
            except (AttributeError, RuntimeError):
                pass
        QTimer.singleShot(340, _probe)
        logger.warning(
            f"[SIDEBAR-VIS] start expanded={self.sidebar_expanded} "
            f"from={self.sidebar_animation.startValue()} to={self.sidebar_animation.endValue()} "
            f"pos_now={self.sidebar.pos()} visible={self.sidebar.isVisible()} "
            f"raised_above={self.sidebar.parentWidget().children().index(self.sidebar) if self.sidebar.parentWidget() else None}"
        )

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
            # visual_area blur starts HERE (not at panel-open) so it matches the
            # transport bar's timing — see _start_visual_area_blur.
            self._start_visual_area_blur(self.settings_panel)

        self.settings_panel_animation.valueChanged.connect(_log_settings_slide_frame)
        self.settings_panel_animation.finished.connect(_on_settings_slide_finished)

        self.settings_panel_animation.start()
        logger.debug(
            f"t={time.perf_counter():.6f} [_start_settings_entry] "
            f"settings_panel_animation.start() called "
            f"sidebar.pos()={self.sidebar.pos()} sidebar.isVisible()={self.sidebar.isVisible()}"
        )

        if not self.config.get_blur_enabled():

            self.blur_effect.setBlurRadius(0)

            self._clear_visual_area_clip()

    def switch_to_speed_panel(self) -> bool:
        """Dismiss whatever full panel is open and open Speed once it has closed.

        For the Speed button only. That button sits in the always-on transport
        chrome and protrudes ~20px past the 90%-width panels into the sliver, so it
        stays clickable while Stats/Tags/Settings is open — by design, it has looked
        that way for months. But the click landed on _open_speed_flow's
        one-overlay gate and was DROPPED: the button styled itself pressed and
        nothing happened. This restores the pre-df98cef behaviour, where clicking it
        closed the open panel and opened Speed.

        This is NOT a hole in the one-overlay gate. The gate's policy — drop the
        second request, never switch or queue — is about two OPENS colliding inside
        an animation window, which is not legitimate intent. A deliberate click on a
        visible chrome button is legitimate intent, and it is served the way the
        gate's own text prescribes: QUEUE the open, then close, then open when the
        close has finished. Nothing is opened concurrently with a close, so this
        cannot reproduce the close-slide-fights-open-slide overlap bug that
        _hide_popups()-then-open caused.

        Dispatches via _start_speed_entry (not _open_speed_flow) once the close
        lands — the same reason the sidebar handoff does: it is a continuation of an
        already-granted request, so re-consulting the gate would block it against
        its own committed state.

        Returns True if a switch was started, False if there was nothing to switch
        away from (caller should then open normally).
        """
        key = self.active_full_panel()
        if key is None or key not in dict(self._CLOSE_ANIMS):
            return False
        if key == "speed":
            return False  # self-toggle is the caller's job, not a switch
        anim = getattr(self, dict(self._CLOSE_ANIMS)[key], None)
        if anim is None:
            return False

        def _on_closed():
            try:
                anim.finished.disconnect(_on_closed)
            except (TypeError, RuntimeError):
                pass
            self._pending_panel_open = None
            # Re-check: the user may have dismissed or changed things during the
            # ~300ms close. Only open if nothing else claimed the slot meanwhile.
            if self.active_full_panel() is None and not self.sidebar_expanded:
                self._start_speed_entry()

        self._pending_panel_open = "speed"
        closer = {
            "library": self._close_library_flow,
            "settings": self._close_settings_flow,
            "speed": self._close_speed_flow,
            "sleep": self._close_sleep_flow,
            "stats": self._close_stats_flow,
            "tags": self._close_tags_flow,
        }[key]
        closer()
        # CONNECT AFTER closer(), never before. Qt fires `finished` slots in
        # connection order, and each _close_*_flow connects its own _on_*_hidden
        # (which calls .hide()) inside closer(). Connecting first put _on_closed
        # ahead of that hide, so the re-check below still saw the panel as visible,
        # active_full_panel() still named it, and the open was skipped every time —
        # the panel dismissed and Speed never appeared.
        anim.finished.connect(_on_closed)
        # If the close did not actually start, nothing will ever emit `finished` —
        # which would strand _pending_panel_open and wedge is_overlay_open_or_committed
        # permanently, blocking EVERY panel for the rest of the session. Unwind now
        # rather than leave that possible. (active_full_panel already excludes a
        # mid-close panel, so reaching here should mean the close really started;
        # this is the belt to that braces.)
        if anim.state() != QAbstractAnimation.State.Running:
            try:
                anim.finished.disconnect(_on_closed)
            except (TypeError, RuntimeError):
                pass
            self._pending_panel_open = None
            return False
        return True

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
            # visual_area blur starts HERE (not at panel-open) so it matches the
            # transport bar's timing — see _start_visual_area_blur.
            self._start_visual_area_blur(self.speed_panel)

        self.speed_panel_animation.finished.connect(_on_speed_slide_finished)
        self.speed_panel_animation.start()

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
            self.blur_animation.setDuration(_BLUR_OUT_MS)
            self.blur_animation.setEndValue(0)
            self.blur_animation.start()
            self._clear_visual_area_clip()

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
            self.blur_animation.setDuration(_BLUR_OUT_MS)
            self.blur_animation.setEndValue(0)
            self.blur_animation.start()
            self._clear_visual_area_clip()

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
            # visual_area blur starts HERE (not at panel-open) so it matches the
            # transport bar's timing — see _start_visual_area_blur.
            self._start_visual_area_blur(self.stats_panel)

        self.stats_panel_animation.finished.connect(_on_stats_slide_finished)
        self.stats_panel_animation.start()

        if not self.config.get_blur_enabled():

            self.blur_effect.setBlurRadius(0)

            self._clear_visual_area_clip()

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
            # visual_area blur starts HERE (not at panel-open) so it matches the
            # transport bar's timing — see _start_visual_area_blur.
            self._start_visual_area_blur(self.sleep_panel)

        self.sleep_panel_animation.finished.connect(_on_sleep_slide_finished)
        self.sleep_panel_animation.start()

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
            self.blur_animation.setDuration(_BLUR_OUT_MS)
            self.blur_animation.setEndValue(0)
            self.blur_animation.start()
            self._clear_visual_area_clip()

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
            self.blur_animation.setDuration(_BLUR_OUT_MS)
            self.blur_animation.setEndValue(0)
            self.blur_animation.start()
            self._clear_visual_area_clip()
        else:
            self.blur_effect.setBlurRadius(0)
            self._clear_visual_area_clip()

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
            # visual_area blur starts HERE (not at panel-open) so it matches the
            # transport bar's timing — see _start_visual_area_blur.
            self._start_visual_area_blur(self.tags_panel)

        self.tags_panel_animation.finished.connect(_on_tags_slide_finished)
        self.tags_panel_animation.start()

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
            self._clear_visual_area_clip()

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
        # Remember what this is opening ON TOP OF, for the blur suspend/resume pair.
        # Written AFTER the early-return above so a dropped duplicate open can never
        # clobber a live value. active_full_panel() already excludes mid-close panels
        # via _is_closing, which is exactly the state we must not "restore" blur to.
        self._book_detail_underlay = self.active_full_panel()
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
        # Immediately, at open-START: the underlay is about to be fully covered, so
        # its blur must stop now rather than at slide-finish. This and the blur START
        # below are two SEPARATE moments and must not be merged — see
        # _suspend_blur_for_book_detail.
        self._suspend_blur_for_book_detail()
        panel_w = self.main_window.width()
        book_detail_panel_y = 32 # Position under the titlebar
        self.book_detail_panel.setFixedWidth(panel_w)
        self.book_detail_panel.setFixedHeight(self.main_window.height() - book_detail_panel_y)
        self.book_detail_panel.move(panel_w, book_detail_panel_y)
        self.book_detail_panel.show()
        self.book_detail_panel.raise_()
        self._claim_panel_focus(self.book_detail_panel)

        def _on_book_detail_slide_finished():
            try:
                self.book_detail_panel_animation.finished.disconnect(
                    _on_book_detail_slide_finished)
            except (TypeError, RuntimeError):
                pass
            # Book Detail spans BOTH blur regions, so it frosts via the grab overlay
            # over its whole area rather than visual_area's paint-time effect:
            # ClippedBlurEffect lives on visual_area, which is inset 10px inside
            # content_container and does not contain the transport bar at all, so it
            # structurally CANNOT cover this panel's backdrop. Hence no
            # _start_visual_area_blur call here — that asymmetry vs. the other five
            # panels is deliberate, not an omission.
            self._apply_transport_bar_blur_full(self.book_detail_panel)

        # Blur starts at slide-FINISHED, matching every other panel — see
        # _start_visual_area_blur's TIMING IS LOAD-BEARING note.
        #
        # This connects to `finished` to START an effect, which is what the other
        # five panels do; it is NOT the pattern the "do not resume a panel-animation
        # wait via finished" rule forbids (that targets resuming a PREDICATE WAIT,
        # because stop() emits no finished). Safe here because
        # book_detail_panel_animation is never stop()ed — _close_book_detail_flow
        # early-returns on Running rather than stopping it. IF A FUTURE CHANGE ADDS A
        # stop() (e.g. interrupt-and-reverse close), this frost silently never
        # appears.
        self.book_detail_panel_animation.finished.connect(_on_book_detail_slide_finished)
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
        # At close-START, matching _close_stats_flow: the transport bar returns to
        # live view right away instead of staying frosted through the whole slide-out
        # (see hide_for_panel's contract). The underlay's blur is deliberately NOT
        # restored here — see _resume_blur_after_book_detail.
        self._clear_transport_bar_blur()
        # The frost is a child of the panel and would otherwise slide out still
        # showing a stale backdrop through the translucent wash.
        self._transport_bar_blur.clear_panel_backdrop_frost(self.book_detail_panel)

    def _on_book_detail_hidden(self):
        try:
            self.book_detail_panel_animation.finished.disconnect(self._on_book_detail_hidden)
        except (TypeError, RuntimeError):
            pass
        self.book_detail_panel.hide()
        self._release_panel_focus(self.book_detail_panel)
        # NOTE: focus is released but never handed back to the still-open underlay,
        # leaving that panel with no focus owner. Known, deliberately out of scope for
        # this blur change — recorded in DEBT_INVENTORY.md for the Stats keyboard-nav pass.
        self._resume_blur_after_book_detail()
        self._notify_panel_closed()

    def _close_settings_flow(self):
        """Slides the settings panel back out.

        BLOCKS on the hover-out snapback visibly settling before the slide starts
        (2026-08-05, corrected snapback-timing spec v2 — see
        review/Design_260805_snapback_timing_v2.md — this SUPERSEDES a same-day
        earlier attempt, 2abeab5, reverted the same session). The earlier attempt
        called `_on_theme_unhovered()` then `snap_theme_forward()` synchronously,
        back-to-back, exactly as the pre-fix code below did — `snap_theme_forward()`
        immediately `.stop()`s whatever fade `_on_theme_unhovered()` just started
        and force-applies it INSTANTLY (`fade_ms=0`), so by the time
        `call_when_theme_settled` was reached, `_fade_in_flight` was already False
        and the wait branch was never entered at all. The visible result was not a
        blocked event loop (the wait mechanism itself is a non-blocking
        `QTimer`-based re-check, same shape as `PanelManager.
        call_when_panels_settled`, and never stalls painting) — it was that
        `_apply_stylesheets`'s own ~700-810ms synchronous cost
        (review/Investigation_260804_animation_latency.md) ran with NO animation
        on screen at all, which reads as a freeze, followed by the sudden correct
        colors the instant it finishes, which reads as a jump.

        The fix: do NOT call `snap_theme_forward()` up front. `_on_theme_unhovered()`
        alone already starts the correct, real, animated 200ms snapback fade
        (confirmed instant-interrupt of any preceding preview fade via
        `_snapback_in_progress` — see `_hover_may_interrupt` in `_on_theme_changed`).
        This method waits for THAT fade to genuinely settle via
        `call_when_theme_settled` before proceeding — during the wait, Qt's event
        loop keeps running normally, so the fade overlay stays visible and the
        200ms fade visibly plays once `_apply_stylesheets` completes underneath it.
        `snap_theme_forward()` is still reachable, but only as
        `call_when_theme_settled`'s own internal termination guarantee (a
        generous, 2000ms bound) for the abnormal case where a fade genuinely never
        settles — see that method's docstring. It must never be called
        unconditionally from this method again.

        RE-ENTRANCY GUARD (`_settings_close_pending`): a second Esc/gutter-click
        while the first call is still waiting on `call_when_theme_settled` must
        NOT re-issue `_on_theme_unhovered()` a second time. `active_full_panel()`
        still reports "settings" as open throughout the settle-wait (the slide
        animation genuinely hasn't started yet, so `_is_closing("settings")` is
        correctly False), so a spammed dismiss WILL re-enter this method without
        this guard. The guard is a plain no-op on re-entry, not a queue: the one
        in-flight close is already going to finish and hide the panel; a second
        request while it's pending adds nothing."""
        if getattr(self, '_settings_close_pending', False):
            logger.warning("[CLOSE-SETTINGS-TRACE] _close_settings_flow: EARLY-RETURN, "
                            "already pending (re-entrancy guard)")
            return
        tm = getattr(self.main_window, 'theme_manager', None)
        logger.warning(
            f"[CLOSE-SETTINGS-TRACE] _close_settings_flow ENTRY has_tm={tm is not None} "
            f"_is_hover_active={getattr(tm, '_is_hover_active', None)} "
            f"_fade_in_flight_BEFORE={getattr(tm, '_fade_in_flight', None)} "
            f"settings_visible={self.settings_panel.isVisible()} "
            f"themes_tab_active={self.main_window.tabs.currentIndex() == 0 if hasattr(self.main_window, 'tabs') else None}"
        )
        if tm:
            self._settings_close_pending = True
            tm._on_theme_unhovered()
            # A settle gap only makes sense — and should only cost anything — when
            # a fade was GENUINELY started by the call above (a real hover-out).
            # Check _fade_in_flight HERE, before call_when_theme_settled's own
            # immediate-vs-deferred branch runs, so the ordinary no-hover dismiss
            # (the overwhelming majority of dismisses) proceeds with truly zero
            # added delay rather than a gap that happens to be scheduled for 0ms.
            _was_fading = bool(getattr(tm, '_fade_in_flight', False))
            logger.warning(
                f"[CLOSE-SETTINGS-TRACE] after _on_theme_unhovered(): "
                f"_fade_in_flight_AFTER={_was_fading} "
                f"_is_hover_active={getattr(tm, '_is_hover_active', None)} "
                f"_active_display_theme_internal={getattr(tm, '_active_display_theme_internal', None)!r}"
            )
            if _was_fading:
                logger.warning("[CLOSE-SETTINGS-TRACE] waiting via call_when_theme_settled")
                tm.call_when_theme_settled(self._finish_close_settings_flow_with_gap)
            else:
                logger.warning("[CLOSE-SETTINGS-TRACE] no fade started — proceeding immediately")
                self._close_settings_flow_after_settle_gap()
        else:
            self._close_settings_flow_after_settle_gap()

    def _finish_close_settings_flow_with_gap(self):
        """Reached only when a genuine hover-out snapback was actually settled
        (see _close_settings_flow's docstring). A small additional settle gap runs
        first so the revert is perceptible as its own step before the panel starts
        moving, rather than the slide's first frame landing in the same tick the
        fade completes."""
        logger.warning("[CLOSE-SETTINGS-TRACE] settled — starting settle gap timer")
        QTimer.singleShot(_SNAPBACK_SETTLE_GAP_MS, self._close_settings_flow_after_settle_gap)

    def _close_settings_flow_after_settle_gap(self):
        logger.warning("[CLOSE-SETTINGS-TRACE] _close_settings_flow_after_settle_gap: "
                        "starting slide-out animation now")
        # Clear the re-entrancy guard from _close_settings_flow HERE, unconditionally
        # (both the early-return-if-already-running path below and the normal path) —
        # once this method runs, either the slide is about to start (after which
        # _is_closing("settings") takes over as the correct re-entrancy signal) or it
        # was already running (an unrelated stale race, not this guard's concern).
        # Stranding this True would permanently block every future Settings dismiss.
        self._settings_close_pending = False
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
            self.blur_animation.setDuration(_BLUR_OUT_MS)
            self.blur_animation.setEndValue(0)
            self.blur_animation.start()
            self._clear_visual_area_clip()
        else:
            self.blur_effect.setBlurRadius(0)
            self._clear_visual_area_clip()

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
            # Separate catch-up, same pre-show() instant: _apply_stylesheets skips a
            # HIDDEN settings/speed/sleep panel (see apply_pending_panel_sheet for the
            # measurement), and flush_deferred_restyle above does NOT cover those three
            # — it drains the library/stats/tags/book_detail batch only. Without this a
            # panel hidden across a theme change would open with stale colours.
            if hasattr(tm, 'apply_pending_panel_sheet'):
                for _attr in ('settings_panel', 'speed_panel', 'sleep_panel'):
                    _p = getattr(self.main_window, _attr, None)
                    if _p is not None and not _p.isVisible():
                        tm.apply_pending_panel_sheet(_p)

    def _any_panel_animating(self):
        """Returns True if any sliding panel or blur animation is currently running."""
        animations = [
            self.sidebar_animation,
            self.library_panel_animation,
            self.settings_panel_animation,
            self.speed_panel_animation,
            self.sleep_panel_animation,
            self.stats_panel_animation,
            self.tags_panel_animation,
            self.blur_animation,
        ]
        if self.book_detail_panel_animation:
            animations.append(self.book_detail_panel_animation)
        return any(anim.state() == QAbstractAnimation.State.Running for anim in animations)

    def call_when_panels_settled(self, callback, coalesce_key=None):
        """Invoke `callback` once nothing in `_any_panel_animating()` is running.
        Synchronous and immediate when nothing is running — the panel-side analogue
        of ClickSlider.when_animations_done (ui/controls.py).

        `coalesce_key` (added 2026-08-03, snapback-stuck-theme fix): when given a
        non-None key, this call REPLACES any already-queued waiter with the same
        key in place, instead of appending a second entry. Without this, a burst of
        calls that all arrive while `_any_panel_animating()` is True (e.g. a theme
        hover immediately followed by an unhover, both issued before the settings
        panel's own open animation finishes) queue as independent FIFO entries and
        replay in ISSUE order rather than INTENT order — so an earlier hover-preview
        call can resume and apply AFTER a later unhover-snapback call, leaving the
        theme stuck on the hover preview. Confirmed live (see
        review/Investigation_260803_fallback_necessity.md and the snapback fix design
        that superseded its "fallback is load-bearing" attribution): the existing
        `snap_theme_forward` fallback does NOT catch this — it guards on
        `_fade_overlay.isVisible()`, which is False throughout this mechanism, since
        no `_fade_anim` ever starts. Only `ThemeManager` passes a key today
        (`"theme_change"`); every other caller passes None and keeps today's
        append-only FIFO behavior unchanged.

        WHY THIS EXISTS (2026-07-28). `ThemeManager._on_theme_changed`'s animation
        guard used to defer via a flat 700ms retry timer (`_PANEL_ANIM_GUARD_MS`).
        Against a 1500ms blur-in that guarantees at least two retry rounds and adds
        up to 700ms of pure polling overshoot: the first theme hover after opening
        Settings took ~2.1s to preview, every time (live-traced 03:34:44-47). Slides
        are only 200-300ms AND finish before the blur starts (`_start_visual_area_blur`
        is called FROM the slide-finished callback), so the blur is the long pole.

        WHY A PREDICATE RE-CHECK AND NOT `finished`. Mirroring the `_fade_running`
        branch's signal-based resume is the obvious move and it is WRONG here:
        `QPropertyAnimation.stop()` does not emit `finished` (verified empirically,
        2026-07-28), and `blur_animation.stop()` runs unconditionally on every panel
        open (`_start_visual_area_blur`) and on blur-toggle-off. A `finished`-based
        resume would be silently dropped — the exact failure already diagnosed three
        times against `_fade_anim`. `stateChanged` fails differently: it fires on that
        same `stop()`, i.e. mid-panel-open BEFORE the replacement blur starts, which is
        precisely the window the guard protects (a 300ms restyle landing mid-tween
        freezes the blur for ~310ms — measured).

        So: event-driven in EFFECT (fires within one frame of the true settle instant),
        predicate-driven in MECHANISM (immune to `stop()` by construction). Same
        property transport_bar_blur.py relies on after its own polled→event-driven
        migration: never try to cancel an armed callback; let it fire and make the
        callback cheap to re-evaluate.

        Measured against the shipped mechanism: a restyle fired by this watch leaves the
        blur tween byte-identical to running it alone (94 frames, 17.0ms worst gap, both
        cases), versus a 316.2ms freeze for one landing mid-tween.
        """
        if not self._any_panel_animating():
            callback()
            return
        if coalesce_key is not None:
            for i, (key, _cb) in enumerate(self._panels_settled_waiters):
                if key == coalesce_key:
                    self._panels_settled_waiters[i] = (coalesce_key, callback)
                    self._arm_settled_watch()
                    return
        self._panels_settled_waiters.append((coalesce_key, callback))
        self._arm_settled_watch()

    def has_settled_waiter(self, coalesce_key):
        """True if a waiter with this coalesce_key is currently queued in
        `_panels_settled_waiters` (added 2026-08-03, snapback-stuck-theme fix).

        Needed because `_on_theme_changed`'s early no-op guard (theme_manager.py, near
        its top) compares the requested `theme_name`/`hover` against
        `_active_display_theme_internal`/`_is_hover_active` — values that are ONLY
        updated by `_mark_theme_applied`, called from inside the branch that actually
        ran `_apply_stylesheets`. A call deferred into this queue (e.g. a hover preview
        issued while `_any_panel_animating()` is True) has NOT reached that point yet —
        `_active_display_theme_internal` still reflects whatever was active BEFORE the
        deferred call, not the deferred call's own target. If a second call for a
        DIFFERENT theme/hover-state (e.g. the unhover snapback, reverting to the
        original active theme) arrives while that first call is still queued, it can
        coincidentally match the still-stale `_active_display_theme_internal` and get
        silently swallowed by the no-op guard — dropping the snapback entirely and
        leaving the queued preview to apply, unopposed, once it resumes. The guard must
        skip itself whenever this returns True for the "theme_change" key, since
        `_active_display_theme_internal` cannot be trusted as ground truth while a
        same-key call is still in flight through this queue.
        """
        return any(key == coalesce_key for key, _cb in self._panels_settled_waiters)

    def _arm_settled_watch(self):
        """Arm the settle tick if it is not already armed.

        The early-return is load-bearing, not an optimisation: it means the timer is
        NEVER restarted while running. `_panel_guard_timer` — the mechanism this
        replaces — did `stop()` then `start()` on every re-arm, so its 700ms deadline
        was retriggerable; because re-arming was driven by mouse motion (hover sweeps
        produce enter/leave pairs far faster than 700ms apart), a queued call could be
        starved indefinitely. That was the 2026-07-22 "snapback hangs" incident, whose
        fix addressed the entry into the branch but left this property intact. Here the
        deadline is absolute and additional waiters simply join the queue.
        """
        if self._settled_watch_armed:
            return
        self._settled_watch_armed = True
        self._settled_watch_timer.start()

    def _on_settled_watch_tick(self):
        if self._any_panel_animating():
            self._settled_watch_armed = False
            self._arm_settled_watch()
            return
        self._settled_watch_armed = False
        # Swap BEFORE invoking: a callback may synchronously re-enter
        # call_when_panels_settled (ThemeManager._on_theme_changed resumes via a full
        # re-call, which can re-defer), and that new waiter must land in a fresh list
        # rather than one being iterated.
        waiters, self._panels_settled_waiters = self._panels_settled_waiters, []
        logger.debug(
            f"t={time.perf_counter():.6f} [settle-watch] panels settled, "
            f"draining {len(waiters)} waiter(s)"
        )
        for _key, cb in waiters:
            cb()

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

    _CLOSE_ANIMS = (
        ("library", "library_panel_animation"),
        ("settings", "settings_panel_animation"),
        ("speed", "speed_panel_animation"),
        ("sleep", "sleep_panel_animation"),
        ("stats", "stats_panel_animation"),
        ("tags", "tags_panel_animation"),
    )

    def _is_closing(self, key):
        """True while `key`'s panel is mid-slide — still isVisible(), but on its way
        out (2026-07-28).

        A panel stays isVisible() for the WHOLE close animation, so
        active_full_panel used to keep naming it for another ~300ms after the user
        had already dismissed it. A right-click arriving in that window was routed
        to that panel's close flow, which early-returns while its own animation runs
        — so the click was silently swallowed instead of falling through to the
        sidebar toggle. Reported live: "close the panel, right click gets
        swallowed."

        Same shape as the sidebar drop fixed earlier today, in four more places
        (_close_speed_flow / _close_sleep_flow / _close_stats_flow /
        _close_tags_flow all guard identically). Fixed here rather than in each
        flow: those guards are correct — restarting a running slide would break it —
        the bug is that the DISPATCHER treated a closing panel as an open one.
        """
        anim = getattr(self, dict(self._CLOSE_ANIMS).get(key, ""), None)
        return anim is not None and anim.state() == QAbstractAnimation.State.Running

    def active_full_panel(self):
        """Which single full panel/overlay is currently open, as a string key
        ('library'/'settings'/'speed'/'sleep'/'stats'/'tags'/'book_detail'/'chapter_list'),
        or None. Same visibility checks and priority order as handle_drag_area_right_click —
        there is no existing single accessor, so this centralizes it.

        A panel that is mid-CLOSE does not count as open — see _is_closing."""
        if self.library_panel.isVisible() and not self._is_closing("library"):
            return "library"
        if self.settings_panel.isVisible() and not self._is_closing("settings"):
            return "settings"
        if self.speed_panel.isVisible() and not self._is_closing("speed"):
            return "speed"
        if self.sleep_panel.isVisible() and not self._is_closing("sleep"):
            return "sleep"
        if self.stats_panel.isVisible() and not self._is_closing("stats"):
            return "stats"
        if self.tags_panel.isVisible() and not self._is_closing("tags"):
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
        # Route through active_full_panel rather than re-deriving the chain here.
        # This used to be a duplicated isVisible() ladder, which meant a panel
        # mid-CLOSE (still isVisible() for its whole ~300ms slide) was treated as
        # open: the right-click went to that panel's close flow, which early-returns
        # while its own animation runs, and the click vanished instead of falling
        # through to the sidebar. Reported live as "close the panel, right click gets
        # swallowed". active_full_panel now excludes a closing panel — see
        # _is_closing — so this chain must not be re-inlined.
        panel = self.active_full_panel()
        # DISPATCH PROBE (2026-07-28) at WARNING — pairs with [RCLICK] in app.py.
        # An [RCLICK] with no [RCLICK-BRANCH] means the press never reached here;
        # a branch that changes nothing visible means it was swallowed downstream.
        # `closing` is the field that matters for the "close the panel, right click
        # gets swallowed" report: a panel mid-slide must NOT be dispatched to.
        logger.warning(
            f"[RCLICK-BRANCH] panel={panel!r} "
            f"closing={[k for k, _ in self._CLOSE_ANIMS if self._is_closing(k)]} "
            f"sidebar_expanded={self.sidebar_expanded}"
        )
        if panel == "library":
            logger.debug(f"t={time.perf_counter():.6f} [handle_drag_area_right_click] branch=close_library")
            self._close_library_flow()
        elif panel == "settings":
            logger.debug(f"t={time.perf_counter():.6f} [handle_drag_area_right_click] branch=close_settings")
            self._close_settings_flow()
        elif panel == "speed":
            logger.debug(f"t={time.perf_counter():.6f} [handle_drag_area_right_click] branch=close_speed")
            self._close_speed_flow()
        elif panel == "sleep":
            logger.debug(f"t={time.perf_counter():.6f} [handle_drag_area_right_click] branch=close_sleep")
            self._close_sleep_flow()
        elif panel == "stats":
            logger.debug(f"t={time.perf_counter():.6f} [handle_drag_area_right_click] branch=close_stats")
            self._close_stats_flow()
        elif panel == "tags":
            logger.debug(f"t={time.perf_counter():.6f} [handle_drag_area_right_click] branch=close_tags")
            self._close_tags_flow()
        elif panel == "book_detail":
            logger.debug(f"t={time.perf_counter():.6f} [handle_drag_area_right_click] branch=close_book_detail")
            self._close_book_detail_flow()
        elif panel == "chapter_list":
            logger.debug(f"t={time.perf_counter():.6f} [handle_drag_area_right_click] branch=chapter_list_fade_out")
            self.main_window.chapter_list_widget.fade_out()
        else:
            logger.debug(f"t={time.perf_counter():.6f} [handle_drag_area_right_click] branch=toggle_sidebar (no panel visible)")
            _pre = self.sidebar_expanded
            self._toggle_sidebar()
            logger.warning(
                f"[RCLICK-BRANCH] -> toggle_sidebar {_pre} -> {self.sidebar_expanded}"
                f"{'  <-- NO CHANGE' if _pre == self.sidebar_expanded else ''}"
            )

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