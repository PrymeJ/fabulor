import logging
import random
import time
import warnings
from PySide6.QtWidgets import QLabel, QGraphicsOpacityEffect, QPushButton, QComboBox
from PySide6.QtCore import Qt, QPropertyAnimation, QTimer, Signal, QObject, QEasingCurve
from PySide6.QtGui import QFont, QFontMetrics, QColor
from ..themes import (
    get_base_stylesheet, get_title_bar_stylesheet, get_player_stylesheet,
    get_library_stylesheet, get_settings_stylesheet, get_sidebar_stylesheet,
    get_stats_stylesheet, THEMES
)

logger = logging.getLogger(__name__)

# Spurious-enterEvent guard window (2026-07-20) — see the try/finally block
# around settings_panel.setStyleSheet() in _apply_stylesheets for the full
# mechanism. Sized with real margin over the measured ~8-15ms gap between that
# call completing and the spurious enterEvent/leaveEvent pair firing.
_SPURIOUS_ENTER_GUARD_S = 0.05

def _theme_distance(name_a: str, name_b: str) -> float:
    """
    Perceptual distance between two themes based on bg_main hue, saturation,
    lightness delta, and accent hue. Returns 0.0–1.0 (higher = more different).
    """
    import colorsys

    def hex_to_hsl(hex_color: str):
        hex_color = hex_color.lstrip('#')
        r, g, b = [int(hex_color[i:i+2], 16) / 255.0 for i in (0, 2, 4)]
        h, lum, s = colorsys.rgb_to_hls(r, g, b)
        return h * 360, s, lum

    def hue_dist(h1, h2):
        d = abs(h1 - h2)
        return min(d, 360 - d) / 180.0

    t_a = THEMES.get(name_a, {})
    t_b = THEMES.get(name_b, {})
    bg_a = t_a.get('bg_main', '#1A1A1A')
    bg_b = t_b.get('bg_main', '#1A1A1A')
    acc_a = t_a.get('accent', '#FFFFFF')
    acc_b = t_b.get('accent', '#FFFFFF')

    h_bg_a, s_bg_a, l_bg_a = hex_to_hsl(bg_a)
    h_bg_b, s_bg_b, l_bg_b = hex_to_hsl(bg_b)
    h_acc_a = hex_to_hsl(acc_a)[0]
    h_acc_b = hex_to_hsl(acc_b)[0]

    return (hue_dist(h_bg_a, h_bg_b) * 0.45 +
            abs(s_bg_a - s_bg_b)      * 0.15 +
            abs(l_bg_a - l_bg_b)      * 0.25 +
            hue_dist(h_acc_a, h_acc_b) * 0.15)


_THEME_SWITCH_FADE_MS = 750       # fade duration for non-hover theme switches
_SNAPBACK_FADE_MS     = 200       # fade duration when reverting a hover preview
_PANEL_ANIM_GUARD_MS  = 700       # delay before retrying a theme change mid-panel-animation
_HOVER_DEBOUNCE_MS    = 80        # coalesce rapid hover sweeps into one preview restyle



class ThemeComboBox(QComboBox):
    """Custom QComboBox that provides signals for popup visibility events."""
    aboutToShowPopup = Signal()
    aboutToHidePopup = Signal()

    def showPopup(self):
        # Ensure mouse tracking is enabled for the popup view to trigger highlighted signals
        self.view().setMouseTracking(True)
        self.view().viewport().setMouseTracking(True)
        self.aboutToShowPopup.emit()
        super().showPopup()

    def hidePopup(self):
        super().hidePopup()
        self.aboutToHidePopup.emit()

class ThemeManager(QObject):
    """Manages theme application, previews, and multi-selection pool."""
    theme_applied = Signal(dict)

    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.config = main_window.config
        self._is_hover_active = False
        
        # Load selection pool from config
        saved = self.config.get_theme()
        if "," in saved:
            self.selected_themes = [t.strip() for t in saved.split(",") if t.strip()]
        else:
            self.selected_themes = [saved] if saved else ["The Color Purple"]
            
        # Filter invalid themes and ensure fallback
        self.selected_themes = [t for t in self.selected_themes if t in THEMES]
        if not self.selected_themes:
            self.selected_themes = ["The Color Purple"]

        # Initial selection for this session: pick a random one from the pool
        if len(self.selected_themes) > 1:
            self._current_theme_name = random.choice(self.selected_themes)
        else:
            self._current_theme_name = self.selected_themes[0]

        from collections import deque
        self._recent_themes: deque[str] = deque(maxlen=10)

        self._theme_fade_anim = None
        self.theme_widgets = {} # theme_name -> QPushButton
        self.interval_widgets = {} # minutes -> QPushButton
        self.cover_art_mode_widgets = {} # mode -> QPushButton
        self.pool_container = None # QWidget hidden when exclusive mode is active
        self.cover_pool_btn = None # ThemeItem for cover art entry in the pool first row
        self._packed_themes_cache = None
        self._packed_themes_limit = None
        self._active_display_theme_internal = self._current_theme_name

        # Cover-art derived theme (dict or None)
        self._cover_theme: dict | None = None
        self._cover_theme_active = False  # True when cover theme is currently displayed

        # Rotation Timer
        self._pending_rotation = False
        self._pending_clear_cover_theme = False  # set by request_clear_cover_theme while a panel is open
        # Stashed _on_theme_changed call, set only by the _fade_in_flight guard branch
        # (never by the _any_animating branch, which uses _panel_guard_timer instead).
        # Resumed by _on_fade_finished via a full re-call to _on_theme_changed — see
        # that guard branch's comment for why a full re-call (not a direct apply) is
        # required for race safety between the two defer-and-resume mechanisms.
        self._pending_fade_call = None
        self.rotation_timer = QTimer()
        self.rotation_timer.timeout.connect(self._rotate_theme)
        self.set_rotation_interval(self.config.get_theme_rotation_interval())

        # Panel animation guard timer — deduplicated, replaces QTimer.singleShot in _on_theme_changed
        self._panel_guard_timer = QTimer(self)
        self._panel_guard_timer.setSingleShot(True)
        self._panel_guard_timer.setInterval(_PANEL_ANIM_GUARD_MS)

        # Hover-preview debounce: sweeping the cursor across several theme names
        # fires one enterEvent per name crossed. Coalesce them so the (heavy)
        # restyle pipeline runs once, for the name the cursor settles on.
        self._hover_debounce_timer = QTimer(self)
        self._hover_debounce_timer.setSingleShot(True)
        self._hover_debounce_timer.setInterval(_HOVER_DEBOUNCE_MS)
        self._hover_debounce_timer.timeout.connect(self._fire_pending_hover)
        self._pending_hover_theme = None
        self._hover_seen_at = None  # perf_counter of the most recent enterEvent

        self._save_on_fade = False
        self._fade_in_flight = False

        # perf_counter() timestamp bracketing the most recent _apply_stylesheets()
        # call — stamped at BOTH entry and exit of that method (not just exit; a
        # 2026-07-19 live bug showed exit-only stamping leaves a restyle
        # IN PROGRESS invisible to any reader, since the previous call's stale
        # exit stamp is all that's available until the current call finishes).
        # Read (never written here) by ui/transport_bar_blur.py's refresh_dirty()
        # to skip a tick while Qt's post-restyle repaint/repolish backlog is still
        # likely mid-flight OR still settling — main_window.grab() forces that
        # backlog to resolve synchronously if called too soon after, measured
        # live at 250-350ms per occurrence (vs. a normal 5-10ms grab). This is a
        # pure observation point: nothing here changes when/how often
        # _apply_stylesheets itself runs.
        self._last_apply_stylesheets_at = None

        # Deferred invisible-surface restyle batch (see _schedule_deferred_restyle /
        # plans/going-forward-on-this-twinkly-corbato.md). _pending is the coalescing
        # flag; _theme is the last-write-wins theme to apply when the batch runs.
        self._deferred_restyle_pending = False
        self._deferred_restyle_theme = None

    def get_current_theme(self) -> dict:
        from ..themes import _resolve_theme
        active = self._active_display_theme_internal or self._current_theme_name
        return _resolve_theme(active)

    def get_active_theme(self):
        """Sole sanctioned way for code outside theme_manager.py to read the
        current theme. Resolved against hover state — NEVER returns a
        hover-preview-only value to an external caller. While a hover preview
        is live (_is_hover_active), returns the last non-preview active theme
        (_current_theme_name, or the live cover theme if one is active)
        instead of the hovered theme name. Return type matches
        _active_display_theme_internal's own type: a str theme name, or a
        dict (a cover-derived theme) when a cover theme is active.

        Added 2026-07-20 (theme-bleed audit, Mechanism A / Pass 1) to close
        the one confirmed cross-file read of the old (pre-rename) bare
        _active_display_theme field (app.py's _set_bg_suppressed), which read
        it directly with no hover check and could paint content_container with
        a previewed theme. See Audit_ThemeReach_260720.md."""
        if self._is_hover_active:
            if self._cover_theme_active and self._cover_theme is not None:
                return self._cover_theme
            return self._current_theme_name
        return self._active_display_theme_internal or self._current_theme_name
    
    def initialize_fade_overlay(self):
        self._fade_overlay = QLabel(self.main_window)
        self._fade_overlay.setObjectName("theme_fade_overlay")
        self._fade_overlay.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._fade_overlay.hide()

        self._fade_effect = QGraphicsOpacityEffect(self._fade_overlay)
        self._fade_overlay.setGraphicsEffect(self._fade_effect)

        self._fade_anim = QPropertyAnimation(self._fade_effect, b"opacity", self._fade_overlay)
        self._fade_anim.setStartValue(1.0)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.finished.connect(self._on_fade_finished)

    def abort_theme_fade(self):
        if hasattr(self, '_fade_anim') and self._fade_anim.state() == QPropertyAnimation.Running:
            self._fade_anim.stop()
            self._fade_overlay.hide()
            self._fade_effect.setOpacity(0.0)
        self._unfreeze_fade_labels()
        if hasattr(self, '_slider_anims'):
            for anims in self._slider_anims.values():
                for anim in anims.values():
                    if anim.state() == QPropertyAnimation.Running:
                        anim.stop()

    def _on_fade_finished(self):
        # TEMP VERIFICATION LOGGING (2026-07-20): this method previously had ZERO
        # logging of its own, which is why the no-op-guard-masks-stashed-apply
        # investigation (Investigation_NoOpGuardMasksStashedApply_260720.md)
        # could not confirm whether THIS is the drain path that hits the guard.
        # Remove once confirmed.
        logger.warning(
            f"[FADE-FINISHED-TRACE] _on_fade_finished ENTRY "
            f"_pending_fade_call={getattr(self, '_pending_fade_call', None)!r} "
            f"_active_display_theme_internal={getattr(self, '_active_display_theme_internal', None)!r} "
            f"_is_hover_active={getattr(self, '_is_hover_active', None)!r}"
        )
        self._fade_in_flight = False
        self._fade_overlay.hide()
        self._unfreeze_fade_labels()
        if self._save_on_fade:
            self._cached_theme_pixmap = self.main_window.grab()
        # Mirror the flow animation's own finished->_run_deferred_restyle wiring
        # (app.py) for the fade: a deferred restyle held back ONLY by
        # _fade_in_flight (no flow animation running at all) must be re-checked
        # here, or it stays pending forever. See _run_deferred_restyle's docstring.
        self._run_deferred_restyle()
        # Resume a theme-change call that arrived while this fade was still running
        # (_on_theme_changed's _fade_running guard branch). A FULL re-call, not a
        # direct apply — _on_theme_changed re-checks _any_animating fresh, so if a
        # panel animation started in the meantime, it correctly re-defers into the
        # panel_guard_timer branch instead of applying here. See the race-safety
        # note on that guard block for why this matters.
        if self._pending_fade_call is not None:
            pending = self._pending_fade_call
            self._pending_fade_call = None
            # Hover-preview confinement (2026-07-21, see CLAUDE.md "Hover-preview theme
            # application must never reach _schedule_deferred_restyle or any panel-level
            # stylesheet"): a stashed call whose hover flag is True is an abandoned
            # preview, not a genuine selection — by the time this drain runs the user
            # has moved on (cursor elsewhere, panel dismissed), so there is no correct
            # later moment to apply it. Discard rather than replay. pending[3] is hover
            # (the 6-tuple is theme_name, save, fade_ms, hover, user_initiated,
            # bypass_panel_open_guard — widened 2026-07-22 so a stashed snapback's
            # bypass_panel_open_guard=True survives to replay; see the CLAUDE.md rule on
            # this stash for why omitting it stranded snapbacks behind the panel-guard timer).
            if pending[3]:
                logger.warning(
                    f"[FADE-FINISHED-TRACE] _on_fade_finished DISCARDING hover-flagged "
                    f"pending_fade_call={pending!r} (confinement — not replayed)"
                )
            else:
                logger.warning(
                    f"[FADE-FINISHED-TRACE] _on_fade_finished DRAINING pending_fade_call={pending!r} "
                    f"— about to re-call _on_theme_changed; watch for its own [BLEED-TRACE] entry line "
                    f"and whether it EARLY-RETURNs via the no-op guard"
                )
                self._on_theme_changed(*pending)
        else:
            logger.warning("[FADE-FINISHED-TRACE] _on_fade_finished: nothing pending, no drain")

    def snap_theme_forward(self):
        if not hasattr(self, '_fade_anim'):
            return
        if self._fade_anim.state() == QPropertyAnimation.Running:
            self._fade_anim.stop()
        # Clear _fade_in_flight UNCONDITIONALLY, right after the stop above —
        # NOT only inside the `_pending_fade_call is not None` drain branch below.
        # QPropertyAnimation.stop() does NOT emit `finished`, so _on_fade_finished
        # (the only other clearer) never runs for a fade stopped here; if we left
        # the flag set whenever there was nothing to drain, it would strand True
        # with no live fade — and the NEXT non-bypass _on_theme_changed (e.g. a T-key
        # rotation) would hit the _fade_running guard, stash itself into
        # _pending_fade_call, and orphan there forever with no fade to drain it.
        # That is exactly the "T does nothing" bug found live 2026-07-21: the
        # settings-close snap-back (_on_theme_unhovered) starts a real 750ms fade
        # via the themes-tab-visible path, this method immediately stops it, and
        # with no pending call the old in-branch-only clear left _fade_in_flight
        # stranded. The stop guarantees no fade is running past this point, so the
        # flag MUST be False regardless of whether a drain happened. Mirrors
        # complete_main_fade, which also clears the flag before/independently of its
        # own stop. See NOTES.md, 2026-07-21.
        self._fade_in_flight = False
        # Drain any stash left by _on_theme_changed's _fade_running guard branch
        # (e.g. an unhover snapback that arrived while THIS fade was still
        # running) via a FULL re-call to _on_theme_changed(*pending) — mirroring
        # complete_main_fade's own drain exactly — rather than a hand-rolled
        # partial apply. history: the first version of this fix (2026-07-20)
        # manually set _active_display_theme_internal/_is_hover_active and called
        # _apply_stylesheets directly, discarding fade_ms/save/user_initiated,
        # specifically to get an INSTANT apply with no new animation left running
        # past this method's return. That was only half the fix: _on_theme_changed
        # ALSO schedules the deferred invisible-surface batch (_schedule_deferred_
        # restyle, theme_manager.py ~line 667, which drives library_panel/
        # stats_panel/tags_panel/book_detail_panel's own restyle, the theme_applied
        # signal, and _refresh_panel_visuals -> sleep/speed panels' per-button
        # colors) — the hand-rolled apply skipped that call entirely, so a theme
        # settled via THIS drain path never propagated to those surfaces. Confirmed
        # live (2026-07-20, same session): a Rose Code selection resolved via this
        # drain left Stats/Tags/Library/Sleep's preset buttons showing the PREVIOUS
        # theme indefinitely — not a hover-preview bleed, a plain stale-theme bug,
        # reproducible on pre-blur code too. See
        # Investigation_SnapDrainDeferredGap_260720.md for the full trace.
        #
        # Forcing fade_ms=0 gets back the same "instant, no new animation" behavior
        # the original fix needed (theme_manager.py's fade_ms==0 branch applies
        # _apply_stylesheets synchronously, no _fade_anim.start()) while ALSO
        # reaching the shared _schedule_deferred_restyle call that every branch of
        # _on_theme_changed falls through to afterward — one correct call instead
        # of two partial ones. save/user_initiated are NOT reused from the stash
        # (matching the original fix's own reasoning: this is a forced instant
        # settle, not a replay of the original animated intent) — save=False (no
        # cache-pixmap side effect wanted here) and user_initiated=True (the safe
        # default; this drain doesn't need the auto-rotation/themes-tab special
        # case, which only ever narrows fade_ms, already 0 here).
        #
        # (_fade_in_flight is already cleared unconditionally above — the
        # _on_theme_changed(*pending) re-call below therefore won't re-hit the
        # _fade_running guard and re-stash itself. This is required for the drain
        # to work: this method runs immediately after _on_theme_unhovered(), in the
        # same call stack with no intervening event-loop turn, so without the clear
        # above _fade_in_flight would still be True here.)
        #
        # This closes the settings-panel-dismiss theme-bleed race: _close_settings_flow
        # (panels.py) calls _on_theme_unhovered() then this method, synchronously,
        # before starting the panel slide-out/blur-reduction animations. The FAST-
        # pass surfaces (main_window/content_container/sidebar/settings/speed/sleep
        # panel-level QSS) still apply synchronously here, before
        # _schedule_deferred_restyle is even reached — the panel-dismiss/blur-grab
        # constraint from the original fix is unaffected; only the deferred batch,
        # which was never part of that constraint, is now correctly scheduled too.
        if self._pending_fade_call is not None:
            pending = self._pending_fade_call
            self._pending_fade_call = None
            pending_theme_name, _save, _fade_ms, pending_hover, _user_initiated, pending_bypass = pending
            # Hover-preview confinement (2026-07-21, see CLAUDE.md "Hover-preview theme
            # application must never reach _schedule_deferred_restyle or any panel-level
            # stylesheet"): a stashed call whose hover flag is True is an abandoned
            # preview (e.g. the cursor merely transited a swatch on its way to
            # dismissing the panel) — discard rather than replay it. Confirmed live
            # (screen-recorded repro, 2026-07-21): without this check, this exact site
            # applied a never-selected, merely-transited-over theme to every panel on
            # settings-dismiss.
            if pending_hover:
                logger.warning(
                    f"[SNAP-DRAIN-TRACE] snap_theme_forward DISCARDING hover-flagged "
                    f"pending_fade_call theme_name={pending_theme_name!r} (confinement — not replayed)"
                )
            else:
                # TEMP VERIFICATION LOGGING (2026-07-20): confirms the drain actually
                # engaged during live testing, not just that no visible bug occurred —
                # absence of a symptom on one run is weaker evidence than confirming
                # this branch ran. Remove once live-verified against the settings-
                # dismiss repro sequence.
                logger.warning(
                    f"[SNAP-DRAIN-TRACE] snap_theme_forward DRAINING pending_fade_call "
                    f"theme_name={pending_theme_name!r} hover={pending_hover!r} "
                    f"bypass_panel_open_guard={pending_bypass!r} via _on_theme_changed(fade_ms=0)"
                )
                self._on_theme_changed(pending_theme_name, save=False, fade_ms=0,
                                        hover=pending_hover, user_initiated=True,
                                        bypass_panel_open_guard=pending_bypass)
        self._unfreeze_fade_labels()
        if hasattr(self, '_slider_anims'):
            for anims in self._slider_anims.values():
                for anim in anims.values():
                    if anim.state() == QPropertyAnimation.Running:
                        anim.stop()
                        end = anim.endValue()
                        if end is not None:
                            anim.targetObject().setProperty(
                                anim.propertyName().data().decode(), end
                            )
        if hasattr(self, '_fade_overlay') and self._fade_overlay.isVisible():
            self._fade_overlay.hide()
            self._apply_stylesheets(self._active_display_theme_internal, hover=self._is_hover_active)
            if hasattr(self.main_window, '_refresh_panel_visuals'):
                self.main_window._refresh_panel_visuals(self._active_display_theme_internal)

    def get_packed_themes(self, limit=230, spacing=0, padding=0):
        if self._packed_themes_cache is not None and self._packed_themes_limit == limit:
            return self._packed_themes_cache
        self._packed_themes_limit = limit

        bold_font = QFont()
        bold_font.setBold(True)
        bold_font.setPixelSize(12)
        metrics = QFontMetrics(bold_font)

        themes_to_pack = [
            {'name': name, 'width': metrics.horizontalAdvance(name) + padding}
            for name in THEMES.keys()
        ]
        themes_to_pack.sort(key=lambda x: x['width'], reverse=True)

        rows = []
        remaining = list(themes_to_pack)
        while remaining:
            row = []
            current_w = 0
            idx = 0
            while idx < len(remaining):
                item = remaining[idx]
                needed = item['width'] + (spacing if current_w > 0 else 0)
                if current_w + needed <= limit:
                    row.append(item)
                    current_w += needed
                    remaining.pop(idx)
                else:
                    idx += 1

            # Safety break: If the limit is so small that no item can fit, 
            # force the first remaining item into its own row to prevent an infinite loop.
            if not row and remaining:
                row.append(remaining.pop(0))

            rows.append(row)

        self._packed_themes_cache = rows
        return rows

    def _rotate_theme(self):
        # TEMP INSTRUMENTATION (2026-07-21, [T-KEY-TRACE]): see app.py's keyPressEvent
        # instrumentation — investigating T sometimes swallowed/firing late while a panel
        # is open. Remove once the mechanism is confirmed/fixed.
        logger.warning(f"[T-KEY-TRACE] _rotate_theme ENTRY t={time.perf_counter():.6f}")
        mode = self.config.get_cover_art_theme_mode()
        if mode == "exclusive" and self._cover_theme:
            logger.warning("[T-KEY-TRACE] _rotate_theme EARLY-RETURN reason=exclusive_cover_theme")
            return
        if self.main_window.panel_manager and self.main_window.panel_manager.is_any_panel_visible():
            self._pending_rotation = True
            logger.warning(
                f"[T-KEY-TRACE] _rotate_theme DEFERRED (panel open) t={time.perf_counter():.6f} "
                f"_pending_rotation=True"
            )
            return
        self._do_rotate()

    def _do_rotate(self, user_initiated=False):
        self._pending_rotation = False
        mode = self.config.get_cover_art_theme_mode()
        candidates = list(self.selected_themes)
        if mode == "with_pool" and self._cover_theme:
            candidates.append(None)
        if len(candidates) > 1:
            current = None if self._cover_theme_active else self._current_theme_name
            pool = [c for c in candidates if c != current]

            _EXCLUSION_THRESHOLD = 0.5
            _MIN_POOL = 4

            named = [c for c in pool if c is not None]
            has_cover = None in pool

            # Step 1: calculate recent exclusion window from full available pool
            full_named_count = len(named)
            recent_exclude_n = min(full_named_count // 4, 8)

            # Step 2: remove recently shown themes
            recent_set = set(list(self._recent_themes)[-recent_exclude_n:]) if recent_exclude_n > 0 else set()
            named_after_recent = [c for c in named if c not in recent_set]

            # Step 3: relax recent exclusion if pool would drop below _MIN_POOL
            if len(named_after_recent) < _MIN_POOL:
                # Re-admit oldest recent themes until we have enough
                recent_ordered = list(self._recent_themes)  # oldest first
                for candidate in recent_ordered:
                    if candidate in named and candidate not in named_after_recent:
                        named_after_recent.append(candidate)
                    if len(named_after_recent) >= _MIN_POOL:
                        break
            named = named_after_recent

            # Step 4: distance exclusion — only when pool large enough
            if current is not None and len(named) > _MIN_POOL:
                distances = {c: _theme_distance(current, c) for c in named}
                filtered = [c for c in named if distances[c] <= _EXCLUSION_THRESHOLD]
                if len(filtered) >= _MIN_POOL:
                    named = filtered
                    distances = {c: distances[c] for c in named}
            else:
                distances = {c: _theme_distance(current, c)
                             for c in named} if current is not None else {}

            # Step 5: inverse-distance weights with power curve
            epsilon = 1e-6
            weights = [1.0 / (distances.get(c, 0.25) ** 1.0 + epsilon)
                       for c in named]

            if has_cover:
                cover_weight = sorted(weights)[len(weights) // 2] if weights else 1.0
                named.append(None)
                weights.append(cover_weight)

            chosen = random.choices(named, weights=weights, k=1)[0]
            # user_initiated already correctly distinguishes the automatic rotation
            # timer (_rotate_theme -> _do_rotate(), default False — a GENERAL
            # trigger, must stay blocked while a panel is open) from the "Change
            # now" button (main_window_builders.py:730,
            # _do_rotate(user_initiated=True) — a Themes-tab-local click, must
            # apply live while its own panel is open). Found live 2026-07-21:
            # without this, "Change now" set _current_theme_name synchronously
            # then got its own _on_theme_changed call deferred by the panel-open
            # guard — an unrelated hover-unhover side effect (leaving whatever
            # swatch the cursor happened to be over) then read the
            # already-mutated _current_theme_name and applied IT instead, with
            # its own (correct, but coincidental) bypass — producing exactly the
            # haphazard "sometimes works, underline doesn't move, panel flickers"
            # symptom reported. See NOTES.md.
            if chosen is None:
                self._cover_theme_active = True
                self._on_theme_changed(self._cover_theme, save=False, user_initiated=user_initiated,
                                        bypass_panel_open_guard=user_initiated)
            else:
                self._current_theme_name = chosen
                self._cover_theme_active = False
                self._on_theme_changed(chosen, save=False, user_initiated=user_initiated,
                                        bypass_panel_open_guard=user_initiated)
            # Record chosen theme in recent history (named themes only)
            if chosen is not None:
                self._recent_themes.append(chosen)
            self._restart_rotation_timer()

    def _restart_rotation_timer(self):
        interval = self.config.get_theme_rotation_interval()
        if interval > 0:
            self.rotation_timer.start(interval * 60 * 1000)

    def _fire_pending_rotation(self):
        # Two independent checks, not elif: a rotation AND a cover-theme clear can both
        # be pending at once (e.g. a rotation was already queued when the book got
        # excluded too) — each fires its own 3s-after-close timer. _on_theme_changed's
        # own _any_animating/_fade_in_flight guard (not this method) is what prevents
        # the two resulting fades from ever overlapping if they land close together.
        # TEMP INSTRUMENTATION (2026-07-21, [T-KEY-TRACE]): see app.py's keyPressEvent /
        # _rotate_theme instrumentation. Remove once the mechanism is confirmed/fixed.
        if self._pending_rotation:
            logger.warning(
                f"[T-KEY-TRACE] _fire_pending_rotation: panel closed, ARMING 3s delayed "
                f"_rotate_theme t={time.perf_counter():.6f}"
            )
            self._pending_rotation = False
            QTimer.singleShot(3000, self._rotate_theme)
        if self._pending_clear_cover_theme:
            self._pending_clear_cover_theme = False
            QTimer.singleShot(3000, self.clear_cover_theme)

    def request_clear_cover_theme(self):
        """Revert to the pool theme, deferring like _rotate_theme if a panel is open —
        used when a book's cover disappears (excluded/removed) while a panel is still
        showing, so the revert doesn't visibly snap into an open panel. Mirrors
        _rotate_theme / _fire_pending_rotation exactly; do not invent a second
        deferral mechanism. Call sites: app.py's _load_cover_art empty-file_path
        (teardown) branch only — the book-SWITCH no-cover case
        (_show_no_cover_state) already has its own, different, correct deferral
        (_pending_cover_pixmap / _apply_pending_cover_theme) — do not route that
        call site through this method too."""
        if self.main_window.panel_manager and self.main_window.panel_manager.is_any_panel_visible():
            self._pending_clear_cover_theme = True
            return
        self.clear_cover_theme()

    def _mark_theme_applied(self, theme_name, hover):
        """Sole writer of _active_display_theme_internal/_is_hover_active. Call
        ONLY immediately after _apply_stylesheets has genuinely run for
        (theme_name, hover) — never before. This is what makes the no-op guard's
        comparison (_active_display_theme_internal == theme_name and
        _is_hover_active == hover, near the top of _on_theme_changed) correct by
        construction: these fields must only ever reflect a theme/hover pair that
        was actually painted, not merely requested.

        Added 2026-07-20 to fix the guard-masking bug: previously both fields were
        written unconditionally BEFORE _on_theme_changed decided whether to apply
        or stash the call (the _any_animating/_fade_running branches). A call that
        got stashed still left the fields claiming the new theme/hover was already
        active, so when the stash was later drained and replayed with the same
        theme_name/hover, the guard matched and silently skipped the real apply —
        confirmed live to strand a theme's stylesheet unapplied for 75+ seconds,
        across Library/Stats/Tags/Book-Detail and Sleep/Speed's per-button colors.
        See Investigation_NoOpGuardMasksStashedApply_260720.md for the original
        diagnosis and the plan file's audit for the full write/read-site trace
        that confirmed no code path depends on the old (pre-apply) write timing.

        Every real-apply call site calls this immediately after its own
        _apply_stylesheets call: _on_theme_changed's three branches (themes-tab
        overlay fade, slider-animated fade via _do_fade_with_slider_animation,
        instant/no-fade) and apply_full_pass (a separate startup-only path with
        its own direct _apply_stylesheets call, reached both from
        _on_theme_changed's pre-fade-overlay early branch and directly from
        app.py). Do NOT add a fifth inline assignment anywhere else — route any
        new real-apply path through this method instead, at the point its own
        paint call has genuinely completed."""
        self._active_display_theme_internal = theme_name
        self._is_hover_active = hover

    def apply_full_pass(self, theme_name, hover=False):
        """Apply BOTH the fast visible-surface pass and the deferred invisible-surface
        batch, synchronously, in one call. This is the complete "first styling" a theme
        must receive at least once — the visible pass alone (_apply_stylesheets) never
        touches library_panel/stats_panel/book_detail_panel; only the deferred pass
        does. (settings_panel/speed_panel/sleep_panel live on the fast/visible pass
        itself as of the hover-regression fix below, so they're already covered
        without this helper — this docstring's panel list reflects the CURRENT split,
        not the one at the time this helper was written.) Two callers, both
        startup-only contexts where nothing is animating/interactive and there's no
        panel-open race to avoid: (1) _on_theme_changed's early branch, before
        initialize_fade_overlay exists; (2) _setup_ui, directly after all panels are
        constructed.

        BUG (found 2026-07-17, live-traced): _setup_ui used to call _apply_stylesheets
        alone at that point, setting _active_display_theme_internal to the pool theme
        name. Any LATER startup call into _on_theme_changed with that SAME theme name
        (e.g. clear_cover_theme() when cover-theme mode is "off", or when a book has no
        cover) hit the "already this theme" no-op guard and returned immediately,
        NEVER reaching the deferred pass — so every invisible-surface panel stayed
        completely unstyled (bare Qt chrome) for the whole session, until something
        unrelated (manual theme rotation, hover, a genuinely different cover theme)
        first called _on_theme_changed with a different theme name. Confirmed live via
        a temporary trace on the no-op guard: it fired at startup with
        theme_name==_active_display_theme_internal=='<pool theme>', proving _apply_stylesheets_
        deferred was never reached. Fix: _setup_ui now calls this shared helper too, so
        the invisible pass runs once at true startup regardless of cover-theme mode —
        the later same-name no-op guard is then correct to skip re-styling, because
        nothing was actually skipped."""
        self._apply_stylesheets(theme_name, hover=hover)
        self._mark_theme_applied(theme_name, hover)
        if not hover:
            self._apply_stylesheets_deferred(theme_name)
            if hasattr(self.main_window, '_refresh_panel_visuals'):
                self.main_window._refresh_panel_visuals(theme_name)
            from ..themes import _resolve_theme
            self.theme_applied.emit(_resolve_theme(theme_name))
            self.update_theme_list_visuals()

    def _on_theme_changed(self, theme_name, save=True, fade_ms=None, hover=False, user_initiated=True,
                           bypass_panel_open_guard=False):
        """Update the appearance with a subtle fade transition.

        bypass_panel_open_guard: True ONLY for calls that are themselves a direct,
        Themes-tab-local user action or settle-step (hover excepted — already exempt
        via `hover`) — i.e. a call that must reach the currently-open Settings panel
        immediately, because that panel IS the thing the call is about. Set from
        exactly 7 call sites (see the per-site audit in NOTES.md /
        Investigation_PanelOpenThemeGuard_260721.md): toggle_theme_selection,
        _on_theme_right_clicked, _on_theme_unhovered (x2), set_cover_art_mode (x2,
        incl. its internal clear_cover_theme() call), _on_cover_pool_btn_right_clicked,
        _on_cover_pool_btn_clicked's clear_cover_theme() call, and
        snap_theme_forward's drain. Every other caller (rotation, deferred-rotation
        replay, _on_fade_finished's drain, complete_main_fade's drain, cover-theme
        changes driven by book-load) is a GENERAL trigger with no relationship to
        whatever panel happens to be open — those must NOT bypass. Do not set this
        True from a new call site without confirming, by name, which category it
        is — this parameter exists specifically because conflating `hover=False`
        with 'safe while a panel is open' caused a real regression once already
        (2026-07-21)."""

        if fade_ms is None:
            fade_ms = _THEME_SWITCH_FADE_MS if not hover else self.config.get_theme_fade_duration()

        # Only guard if both the theme and hover state match
        if (getattr(self, "_active_display_theme_internal", None) == theme_name
                and self._is_hover_active == hover):
            # TEMP VERIFICATION LOGGING (2026-07-20): _theme_ever_applied (set ONLY
            # at the point _apply_stylesheets actually runs, below) distinguishes a
            # genuine duplicate-call no-op (theme really was already painted) from
            # the no-op-guard-masks-stashed-apply bug (theme_name was only ever
            # assigned to _active_display_theme_internal by a call that got
            # stashed and never reached _apply_stylesheets) — see
            # Investigation_NoOpGuardMasksStashedApply_260720.md. Remove once
            # confirmed/fixed.
            _ever_applied = getattr(self, '_theme_ever_applied', None)
            _suspect_masked_stash = (_ever_applied != theme_name)
            logger.warning(
                f"[GUARD-MASK-TRACE] _on_theme_changed: EARLY-RETURN no-op guard "
                f"theme_name={theme_name!r} hover={hover} "
                f"_theme_ever_applied={_ever_applied!r} "
                f"SUSPECT_MASKED_STASH={_suspect_masked_stash!r} "
                f"— _apply_stylesheets NEVER CALLED this invocation"
            )
            logger.debug(f"[STUTTER-TRACE] t={time.perf_counter():.6f} _on_theme_changed: "
                         f"EARLY-RETURN no-op guard theme_name={theme_name!r} "
                         f"_active_display_theme_internal={getattr(self, '_active_display_theme_internal', None)!r} "
                         f"hover={hover} _is_hover_active={self._is_hover_active} "
                         f"— _apply_stylesheets NEVER CALLED this invocation")
            return

        # Guard against theme changes during panel animation (hitches) AND, for
        # calls that are NOT hover and NOT a Themes-tab-local action/settle-step
        # (bypass_panel_open_guard), while a full panel is simply open and settled —
        # themes must never visibly change while the user has an unrelated panel
        # open. See bypass_panel_open_guard's docstring above for the full
        # category breakdown and why `hover` alone was NOT a sufficient
        # discriminator (found live 2026-07-21 — see NOTES.md).
        _any_animating = bool(
            self.main_window.panel_manager and self.main_window.panel_manager._any_panel_animating()
        )
        _panel_open = bool(
            not hover
            and not bypass_panel_open_guard
            and self.main_window.panel_manager
            and self.main_window.panel_manager.is_any_full_panel_visible()
        )
        _fade_running = getattr(self, '_fade_in_flight', False)
        # hover-interrupts-hover exception (2026-07-21) — see the elif branch below for
        # the full mechanism. Computed here too so the GUARD/BLEED-TRACE log lines
        # correctly report "interrupting" instead of the misleading "stashing" when this
        # call is about to skip the stash and fall through to a fresh apply instead.
        _hover_interrupts_hover = bool(hover and self._is_hover_active)
        logger.debug(
            f"t={time.perf_counter():.6f} [_on_theme_changed GUARD] "
            f"any_panel_animating={_any_animating} panel_open={_panel_open} "
            f"bypass_panel_open_guard={bypass_panel_open_guard} "
            f"fade_in_flight={_fade_running} "
            f"hover_interrupts_hover={_hover_interrupts_hover}"
            + (" -> queuing deferred retry (panel_guard_timer)" if _any_animating or _panel_open
               else " -> interrupting in-flight hover fade" if _fade_running and _hover_interrupts_hover
               else " -> stashing for fade completion" if _fade_running else "")
        )
        # INVESTIGATION LOGGING (2026-07-20, Option A bleed-trace) — same info as
        # the DEBUG line above, at WARNING so it's visible without full DEBUG mode.
        logger.warning(
            f"[BLEED-TRACE] _on_theme_changed theme_name={theme_name!r} hover={hover} "
            f"any_panel_animating={_any_animating} panel_open={_panel_open} "
            f"bypass_panel_open_guard={bypass_panel_open_guard} "
            f"fade_in_flight={_fade_running} "
            f"hover_interrupts_hover={_hover_interrupts_hover}"
        )
        # if/elif, NOT two independent ifs: a single call must only ever be claimed by
        # ONE of the two defer-and-resume mechanisms below, never both (which could fire
        # it twice). Both mechanisms resume via a FULL re-call to _on_theme_changed
        # (never a direct apply) — see each branch's comment — so ownership correctly
        # transfers to whichever condition is still true at resume time; neither branch
        # needs to know about the other.
        if _any_animating or _panel_open:
            self._panel_guard_timer.stop()
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", RuntimeWarning)
                    self._panel_guard_timer.timeout.disconnect()
            except (TypeError, RuntimeError):
                pass
            self._panel_guard_timer.timeout.connect(
                lambda: self._on_theme_changed(theme_name, save, fade_ms, hover, user_initiated,
                                                bypass_panel_open_guard)
            )
            self._panel_guard_timer.start()
            return
        elif _fade_running and not _hover_interrupts_hover:
            # A theme fade is already in flight. A flat-timer retry (like the panel-
            # animation branch above) would be a real mismatch here — _PANEL_ANIM_GUARD_MS
            # (700ms) is SHORTER than _THEME_SWITCH_FADE_MS (750ms), so a blind retry would
            # almost always fire ~50ms too early and need a second full wait, taking up to
            # ~1400ms instead of landing right at 750ms. Resume via the fade's own
            # `finished` signal instead (_on_fade_finished re-calls _on_theme_changed with
            # these stashed args) — zero polling delay, fires exactly when it's safe.
            # last-write-wins if something is already stashed (mirrors _schedule_deferred_
            # restyle's own coalescing comment elsewhere in this file — nothing invisible
            # was shown in between, so only the latest request matters).
            #
            # EXCEPTION carved out by the `not (hover and self._is_hover_active)` clause
            # (2026-07-21, see Investigation_HoverInterruptsHover_260721.md): a genuine,
            # debounce-cleared hover arriving while the CURRENTLY-RUNNING fade is ITSELF a
            # hover preview must NOT be stashed here — it falls through instead to the
            # normal stop-and-apply flow below (the `_fade_anim.stop()` at the "Clear any
            # in-progress animation" block a few lines down, then a fresh fade for the new
            # theme). Confirmed live: hovering theme A, then genuinely resting on theme B
            # while A's preview fade was still running, silently stashed B's call — and,
            # per the hover-confinement discard fix shipped earlier the same night, that
            # stash then got discarded at drain time rather than ever previewing, leaving
            # the user staring at A's stale colors while deliberately hovering B. This
            # exception is scoped tightly: `self._is_hover_active` reflects whether the
            # LAST GENUINELY APPLIED call (i.e. whatever started the fade now running) was
            # itself a hover — set by _mark_theme_applied at the point that fade's own
            # apply ran, so it's accurate even though the fade animation itself hasn't
            # finished yet. If the in-flight fade is a GENUINE SELECTION's settle-fade
            # (_is_hover_active False), a new hover must NOT interrupt it — that case still
            # falls through to the stash below, unchanged, exactly as before this fix.
            #
            # 6-tuple as of 2026-07-22 (was a 5-tuple: theme_name, save, fade_ms, hover,
            # user_initiated). bypass_panel_open_guard is now carried through too — see
            # CLAUDE.md's rule on this stash. Without it, a stashed _on_theme_unhovered()
            # snapback (always bypass_panel_open_guard=True) replayed with the default
            # False at every drain site (_on_fade_finished / snap_theme_forward /
            # complete_main_fade), so the replay incorrectly hit the _panel_open guard
            # while the Settings/Themes panel was still open and got queued into the
            # single-slot _panel_guard_timer instead of applying — which then kept getting
            # clobbered/re-armed by ongoing hover activity, so the snapback could hang
            # indefinitely instead of firing once the fade ended. Confirmed via live DEBUG
            # trace, 2026-07-22 (see the [BLEED-TRACE]/[FADE-FINISHED-TRACE] logs from that
            # session). Exclusivity checked before this fix, both statically (every direct
            # _on_theme_changed call site enumerated) and empirically (every observed
            # hover=True call in the trace carried bypass_panel_open_guard=False, no
            # exceptions): no call site ever passes hover=True and
            # bypass_panel_open_guard=True together, so widening this tuple cannot let an
            # abandoned hover preview bypass the panel-open guard on replay — the
            # hover-preview confinement discard rule (pending[3], unchanged) still catches
            # every hover-flagged stash before it would ever reach the bypass path.
            self._pending_fade_call = (theme_name, save, fade_ms, hover, user_initiated, bypass_panel_open_guard)
            return

        if not hasattr(self, '_fade_anim'):
            # Called before initialize_fade_overlay (e.g. on startup cover load) — apply
            # silently and FULLY SYNCHRONOUSLY (both the fast visible half and the
            # deferred invisible half + TAIL). At startup nothing is animating or
            # interactive, so there is no stutter to avoid and no panel-open race — the
            # deferred split's whole reason (keep invisible work off the animation path)
            # doesn't apply here. Do NOT route this through _schedule_deferred_restyle.
            self.apply_full_pass(theme_name, hover=hover)
            return

        # Clear any in-progress animation
        if self._fade_anim.state() == QPropertyAnimation.Running:
            self._fade_anim.stop()

        # Automatic theme changes (cover art, rotation) snap instantly when the Themes tab
        # is active — avoids the overlay dissolving the tab's live preview widgets. Other
        # tabs are already tamed (no custom-painted widgets), so the overlay runs normally.
        pm = getattr(self.main_window, 'panel_manager', None)
        tabs = getattr(self.main_window, 'tabs', None)
        themes_tab_active = (tabs is not None and tabs.currentIndex() == 0
                             and hasattr(self.main_window, 'settings_panel')
                             and self.main_window.settings_panel.isVisible())
        if not user_initiated and fade_ms > 0 and themes_tab_active:
            fade_ms = 0

        _dbg = logger.isEnabledFor(logging.DEBUG)
        _pipe_t0 = time.perf_counter()
        _fade_started_at = None

        if fade_ms > 0 and themes_tab_active:
            # Themes tab visible — user is deliberately previewing themes, nothing is
            # moving. Full overlay fade including sliders (original behavior).
            pix = self.main_window.grab()
            self._fade_overlay.setPixmap(pix)
            self._fade_overlay.setGeometry(self.main_window.rect())

            from PySide6.QtGui import QRegion
            if pm and pm.is_any_panel_visible():
                logger.debug(
                    f"t={time.perf_counter():.6f} [mask-build themes-tab-visible path] "
                    f"sidebar_expanded={pm.sidebar_expanded} "
                    f"sidebar.geometry()={pm.sidebar.geometry()}"
                )
                mask = QRegion(self.main_window.rect())
                panels = ['library_panel', 'tags_panel', 'speed_panel',
                          'sleep_panel', 'stats_panel', 'book_detail_panel']
                for attr in panels:
                    p = getattr(pm, attr, None)
                    if p and p.isVisible():
                        mask -= QRegion(p.geometry())
                if pm.sidebar_expanded:
                    mask -= QRegion(pm.sidebar.geometry())
                self._fade_overlay.setMask(mask)
                logger.debug(f"t={time.perf_counter():.6f} [mask-build themes-tab-visible path] mask set")
            else:
                self._fade_overlay.clearMask()

            self._fade_overlay.show()
            logger.debug(f"t={time.perf_counter():.6f} [fade_overlay.raise_ BEFORE themes-tab-visible path]")
            self._fade_overlay.raise_()
            logger.debug(f"t={time.perf_counter():.6f} [fade_overlay.raise_ AFTER themes-tab-visible path]")

            self._save_on_fade = save
            self._fade_in_flight = True
            self._fade_sliders = []   # themes-tab path animates no sliders separately
            self._fade_anim.setDuration(fade_ms)
            self._theme_fade_anim = self._fade_anim
            # Restyle happens invisibly beneath the raised overlay; start the fade
            # AFTER it so the animation clock isn't consumed by the synchronous
            # restyle block (previously the fade could fully elapse before the
            # first rendered frame, degrading it to a late snap).
            self._apply_stylesheets(theme_name, hover=hover)
            self._mark_theme_applied(theme_name, hover)
            self._fade_anim.start()
            _fade_started_at = time.perf_counter()
        elif fade_ms > 0:
            # Auto-rotation (or any non-themes-tab fade): sliders may be mid-interaction.
            # Exclude them from the overlay and animate their color properties instead.
            self._do_fade_with_slider_animation(theme_name, hover, save, fade_ms)
        else:
            self._fade_overlay.hide()
            if save:
                self._cached_theme_pixmap = self.main_window.grab()
            self._apply_stylesheets(theme_name, hover=hover)
            self._mark_theme_applied(theme_name, hover)

        # Hidden-panel visual sync (settings-button states, tags/book-detail/stats
        # via theme_applied, theme-list dimming) is skipped on hover: none of it is
        # visible during a themes-tab preview, and the hover-exit full restyle
        # re-runs all of it before any of those surfaces can be shown again.
        #
        # NARROWED: this whole block (the "TAIL") plus the invisible-panel QSS work
        # (_apply_stylesheets_deferred) now runs in ONE deferred batch off the
        # synchronous visible-apply path — after the flow animation on book-load, or
        # on the next event-loop turn for rotation/T. See _schedule_deferred_restyle.
        # The fast visible surfaces were already applied synchronously above.
        if not hover:
            self._schedule_deferred_restyle(theme_name)

        if _dbg:
            now = time.perf_counter()
            total_ms = (now - _pipe_t0) * 1000
            if _fade_started_at is not None:
                fade_delay_ms = (_fade_started_at - _pipe_t0) * 1000
                logger.debug(
                    f"[_on_theme_changed hover={hover}] pipeline={total_ms:.1f}ms  "
                    f"fade_anim.start() at +{fade_delay_ms:.1f}ms (after restyle)  "
                    f"fade_ms={fade_ms}"
                )
            else:
                logger.debug(
                    f"[_on_theme_changed hover={hover}] pipeline={total_ms:.1f}ms  "
                    f"(no themes-tab overlay fade this call)  fade_ms={fade_ms}"
                )

    def _get_slider_anims(self, slider) -> dict:
        """Lazily create and cache QPropertyAnimation instances for a slider's color properties."""
        if not hasattr(self, '_slider_anims'):
            self._slider_anims = {}
        sid = id(slider)
        if sid not in self._slider_anims:
            self._slider_anims[sid] = {
                'bg':    QPropertyAnimation(slider, b"bg_color",    self),
                'fill':  QPropertyAnimation(slider, b"fill_color",  self),
                'notch': QPropertyAnimation(slider, b"notch_color", self),
            }
            for anim in self._slider_anims[sid].values():
                anim.setEasingCurve(QEasingCurve.OutCubic)
        return self._slider_anims[sid]

    # All five labels frozen for the full fade: text cannot change under the overlay,
    # eliminating ghosts. Chapter label is force-refreshed on unfreeze in case a chapter
    # change was missed while frozen.
    _FADE_LABEL_ATTRS = ('current_chapter_label', 'current_time_label', 'total_time_label',
                         'chap_elapsed_label', 'chap_duration_label')

    def _freeze_fade_labels(self):
        self._frozen_labels = []
        for attr in self._FADE_LABEL_ATTRS:
            w = getattr(self.main_window, attr, None)
            if w is not None and hasattr(w, 'freeze'):
                w.freeze()
                self._frozen_labels.append(w)

    def _unfreeze_fade_labels(self):
        for w in getattr(self, '_frozen_labels', ()):
            w.unfreeze()
        self._frozen_labels = []
        # Force chapter label to reflect current chapter, in case it changed while frozen.
        mw = self.main_window
        if hasattr(mw, '_update_chapter_label_from_index') and hasattr(mw, 'player') and mw.player:
            chaps = mw.player.chapter_list
            pos = mw.player.time_pos
            if chaps and pos is not None:
                idx = next((i for i in range(len(chaps) - 1, -1, -1)
                            if chaps[i].get('time', 0) <= pos + 0.35), 0)
                mw._update_chapter_label_from_index(idx)

    def _do_fade_with_slider_animation(self, theme_name, hover, save, fade_ms):
        """Auto-rotation fade: exclude sliders from the overlay via mask and animate their
        colors. Labels are frozen (text pinned) for the fade so their text cannot change
        under the overlay, eliminating the ghost without any overlay trick."""
        mw = self.main_window

        # Freeze labels BEFORE the grab so screenshot text == live text.
        self._freeze_fade_labels()

        # Read start colors before anything changes
        sliders = []
        start_colors = {}
        for attr in ('progress_slider', 'chapter_progress_slider'):
            s = getattr(mw, attr, None)
            if s is not None and s.isVisible():
                if attr == 'chapter_progress_slider' and not mw._chapter_ui_active:
                    continue   # inactive (ghosted) — keep covered by overlay, no punch-through
                sliders.append(s)
                start_colors[id(s)] = {
                    'bg':    QColor(s.bg_color),
                    'fill':  QColor(s.fill_color),
                    'notch': QColor(s.notch_color),
                }

        pix = mw.grab()
        self._fade_overlay.setPixmap(pix)
        self._fade_overlay.setGeometry(mw.rect())

        from PySide6.QtGui import QRegion
        from PySide6.QtCore import QPoint
        pm = getattr(mw, 'panel_manager', None)
        if pm and pm.is_any_panel_visible():
            logger.debug(
                f"t={time.perf_counter():.6f} [mask-build slider-animation path] "
                f"sidebar_expanded={pm.sidebar_expanded} "
                f"sidebar.geometry()={pm.sidebar.geometry()}"
            )
            mask = QRegion(mw.rect())
            panels = ['library_panel', 'tags_panel', 'speed_panel',
                      'sleep_panel', 'stats_panel', 'book_detail_panel']
            for attr in panels:
                p = getattr(pm, attr, None)
                if p and p.isVisible():
                    mask -= QRegion(p.geometry())
            if pm.sidebar_expanded:
                mask -= QRegion(pm.sidebar.geometry())
        else:
            mask = QRegion(mw.rect())

        # Punch slider regions out of the overlay so new colors show through immediately
        for s in sliders:
            top_left = s.mapTo(mw, QPoint(0, 0))
            mask -= QRegion(top_left.x(), top_left.y(), s.width(), s.height())
        self._fade_overlay.setMask(mask)
        logger.debug(f"t={time.perf_counter():.6f} [mask-build slider-animation path] mask set")

        self._fade_overlay.show()
        logger.debug(f"t={time.perf_counter():.6f} [fade_overlay.raise_ BEFORE slider-animation path]")
        self._fade_overlay.raise_()
        logger.debug(f"t={time.perf_counter():.6f} [fade_overlay.raise_ AFTER slider-animation path]")
        self._save_on_fade = save
        self._fade_anim.setDuration(fade_ms)
        self._fade_anim.start()
        self._theme_fade_anim = self._fade_anim

        # Apply new stylesheet — qproperty colors land on next event loop tick
        self._apply_stylesheets(theme_name, hover=hover)
        self._mark_theme_applied(theme_name, hover)

        # Track the in-flight fade so it can be completed cleanly if a panel
        # opens before it finishes (see complete_main_fade). _fade_in_flight
        # also gates the deferred _start_color_anims below — if the fade was
        # already completed/cancelled in this same event-loop turn, the
        # deferred callback must NOT then re-reset the sliders to the OLD
        # start colors and re-animate (which was the stranding bug).
        self._fade_in_flight = True
        self._fade_sliders = list(sliders)

        # Defer color animation until QSS has applied
        def _start_color_anims():
            if not self._fade_in_flight:
                return  # fade already completed/interrupted; do not re-strand sliders
            remaining_ms = max(50, fade_ms - 16)
            for s in sliders:
                sid = id(s)
                if sid not in start_colors:
                    continue
                start = start_colors[sid]
                end = {
                    'bg':    QColor(s.bg_color),
                    'fill':  QColor(s.fill_color),
                    'notch': QColor(s.notch_color),
                }
                # Reset to start so the qproperty snap is invisible
                s.bg_color    = start['bg']
                s.fill_color  = start['fill']
                s.notch_color = start['notch']

                anims = self._get_slider_anims(s)
                for key in ('bg', 'fill', 'notch'):
                    anim = anims[key]
                    if anim.state() == QPropertyAnimation.Running:
                        anim.stop()
                    anim.setDuration(remaining_ms)
                    anim.setStartValue(start[key])
                    anim.setEndValue(end[key])
                    anim.start()

        QTimer.singleShot(0, _start_color_anims)

    def complete_main_fade(self):
        """Instantly finish an in-flight main-window theme fade, leaving every
        slider on its correct NEW-theme color. Safe to call any time (no-op if
        no fade is in flight). This is the main-window counterpart to the
        Settings-panel-oriented snap_theme_forward — it must be called whenever
        a panel/sidebar opens mid-fade, because opening a panel while the fade's
        slider color animation is mid-flight (or its deferred start is still
        queued) otherwise strands the slider at an old/intermediate color while
        the rest of the UI is already the new theme. The new-theme slider colors
        live in the applied QSS (as qproperty-bg_color/etc.), so re-applying the
        stylesheet for _active_display_theme_internal re-polishes them to the correct
        values, overriding whatever the stopped animation left behind."""
        # INVESTIGATION LOGGING (2026-07-20 — Option A confirmed NOT sufficient
        # under blur-on live testing; tracing why). Read-only, no logic change.
        logger.warning(
            f"[BLEED-TRACE] complete_main_fade ENTRY "
            f"_fade_in_flight={getattr(self, '_fade_in_flight', None)!r} "
            f"_pending_fade_call={getattr(self, '_pending_fade_call', None)!r} "
            f"_active_display_theme_internal={getattr(self, '_active_display_theme_internal', None)!r} "
            f"_current_theme_name={getattr(self, '_current_theme_name', None)!r} "
            f"_is_hover_active={getattr(self, '_is_hover_active', None)!r}"
        )
        # Panel-open compensation (deferred-restyle narrowing): flush any pending
        # invisible-surface batch synchronously NOW, before the opening panel paints.
        # MUST be before the _fade_in_flight early-return below — a deferred restyle can
        # be pending with NO fade in flight (e.g. rotation with panels closed, then a
        # panel opened), and every panel-open flow routes through here before show().
        self.flush_deferred_restyle()
        if not getattr(self, '_fade_in_flight', False):
            logger.warning("[BLEED-TRACE] complete_main_fade EARLY-RETURN (no fade in flight)")
            return
        self._fade_in_flight = False
        if hasattr(self, '_fade_anim') and self._fade_anim.state() == QPropertyAnimation.Running:
            self._fade_anim.stop()
        # Stop any slider color animations where they are — the repolish below
        # is what actually sets the final color, so their stopped value is moot.
        if hasattr(self, '_slider_anims'):
            for anims in self._slider_anims.values():
                for anim in anims.values():
                    if anim.state() == QPropertyAnimation.Running:
                        anim.stop()
        if hasattr(self, '_fade_overlay'):
            self._fade_overlay.hide()
        self._unfreeze_fade_labels()

        # Fix for a live-traced bug (2026-07-20 — "theme bleeds into the live
        # main window," reproduced independent of blur; NOT YET COMMITTED as of
        # this comment): QPropertyAnimation.stop()
        # (above) does NOT emit `finished`, so _on_fade_finished — the ONLY code
        # that resumes a theme-change call stashed in _pending_fade_call while a
        # fade was in flight (see the _fade_running branch in _on_theme_changed)
        # — never ran. Any hover-preview call queued right as a panel opened was
        # silently orphaned forever: this method's own fallback reapplication
        # below then re-applied self._active_display_theme_internal/_is_hover_active,
        # both STALE (still holding the last hover-preview theme name and
        # hover=True, since the one call that would have corrected them is the
        # one now stuck in _pending_fade_call). That stale reapplication runs
        # through the fast synchronous path (main_window/content_container/
        # sidebar/settings/speed/sleep) — never the deferred path
        # (library/stats/book_detail) — which is why the symptom looked like
        # "Stats/Tags/Library show the wrong theme, Speed/Sleep don't": every
        # panel-open flow calls this method, so every one of them re-triggered
        # the same stale reapplication, but it was only ever visibly wrong next
        # to a deferred-path panel still showing the correct theme.
        #
        # Fix: if a call is pending, hand off to it via a full _on_theme_changed
        # re-call — mirroring _on_fade_finished's own resume pattern exactly —
        # INSTEAD OF this method's own stale fallback reapplication below. The
        # pending call's args are always more authoritative than
        # _active_display_theme_internal/_is_hover_active at this point, for the same
        # reason _on_fade_finished already treats it that way.
        #
        # Safety (verified against the actual guard conditions in
        # _on_theme_changed, not assumed by analogy to _on_fade_finished): the
        # resumed call re-checks _any_animating/_fade_running fresh, and both
        # are guaranteed False here — _fade_in_flight was just cleared two lines
        # above (mirroring _on_fade_finished's own clear-before-resume order),
        # and _any_animating (a panel SLIDE animation) is guaranteed False
        # because every caller of complete_main_fade() is gated by
        # is_overlay_open_or_committed() (panels.py), which already blocks entry
        # if any panel animation is running — complete_main_fade() cannot be
        # reached mid-panel-slide. So the resumed call always falls through both
        # guard branches and applies directly; it cannot loop or re-stash here.
        if self._pending_fade_call is not None:
            pending = self._pending_fade_call
            self._pending_fade_call = None
            # Hover-preview confinement (2026-07-21, see CLAUDE.md "Hover-preview theme
            # application must never reach _schedule_deferred_restyle or any panel-level
            # stylesheet"): a stashed call whose hover flag is True is an abandoned
            # preview — discard rather than replay it. pending[3] is hover (the 6-tuple
            # is theme_name, save, fade_ms, hover, user_initiated, bypass_panel_open_guard
            # — widened 2026-07-22, see the matching comment in _on_fade_finished).
            if pending[3]:
                logger.warning(
                    f"[BLEED-TRACE] complete_main_fade DISCARDING hover-flagged "
                    f"pending call args={pending!r} (confinement — not replayed)"
                )
                return
            logger.warning(
                f"[BLEED-TRACE] complete_main_fade RESUMING pending call args={pending!r}"
            )
            self._on_theme_changed(*pending)
            logger.warning(
                f"[BLEED-TRACE] complete_main_fade RESUME RETURNED "
                f"_active_display_theme_internal={getattr(self, '_active_display_theme_internal', None)!r} "
                f"_is_hover_active={getattr(self, '_is_hover_active', None)!r} "
                f"_pending_fade_call={getattr(self, '_pending_fade_call', None)!r}"
            )
            return

        # Re-polish the slider qproperty colors to the new theme (overrides any
        # stranded intermediate value left by a stopped animation).
        logger.warning(
            f"[BLEED-TRACE] complete_main_fade FALLBACK reapplying "
            f"_active_display_theme_internal={getattr(self, '_active_display_theme_internal', None)!r} "
            f"_is_hover_active={getattr(self, '_is_hover_active', None)!r}"
        )
        self._apply_stylesheets(self._active_display_theme_internal, hover=self._is_hover_active)

    def _apply_stylesheets(self, theme_name, hover=False):
        # TEMP VERIFICATION LOGGING (2026-07-20): marks theme_name as GENUINELY
        # applied — see the no-op guard's [GUARD-MASK-TRACE] logging in
        # _on_theme_changed, which compares against this to distinguish a real
        # duplicate-call no-op from the guard masking a stashed-but-never-applied
        # theme. Only meaningful for non-hover applies (a hover preview applying
        # doesn't mean the pool theme itself was ever painted) — only set when
        # hover is False, matching what the guard actually cares about (the stash
        # scenario under investigation is always hover=False, a snap-back/click).
        # Remove once confirmed/fixed.
        if not hover:
            self._theme_ever_applied = theme_name
        # Stamped at ENTRY, not just at exit (see the exit-side write below for
        # the original rationale) — found live 2026-07-19 that transport_bar_blur.py's
        # cooldown gate was missing every collision where refresh_dirty() landed
        # WHILE a restyle was still running: the exit-side stamp doesn't exist yet
        # at that point, so the gate was still comparing against the PREVIOUS
        # (already-stale, >cooldown-old) restyle's timestamp and passing through.
        # Stamping at entry closes that gap; the exit-side stamp still re-stamps a
        # fresh "just completed" time so the post-completion settle window is
        # still covered from the correct (later, more accurate) instant.
        self._last_apply_stylesheets_at = time.perf_counter()

        # DEBUG perf instrumentation: per-step wall-clock, only computed when the
        # fabulor logger is at DEBUG. `hover` skips the hidden stats/book-detail
        # panels — those are covered by the full hover=False restyle that fires on
        # every hover exit (unhover snapback, click-to-activate, tab-leave), so
        # they can never be opened stale (a panel open requires the sidebar, which
        # requires leaving the themes tab first → leaveEvent → unhover).
        _dbg = logger.isEnabledFor(logging.DEBUG)
        _steps = []
        _t = time.perf_counter()

        def _mark(label, skipped=False):
            nonlocal _t
            if _dbg:
                now = time.perf_counter()
                _steps.append((label, 0.0 if skipped else (now - _t) * 1000, skipped))
                _t = now

        mw = self.main_window
        mw.setStyleSheet(get_base_stylesheet(theme_name))
        _mark("mw.setStyleSheet(base)")
        if hasattr(mw, 'title_bar'):
            mw.title_bar.setStyleSheet(get_title_bar_stylesheet(theme_name))
        if hasattr(mw, 'content_container'):
            # Honor the no-book/empty-state bg-image suppression so a theme change
            # in those states doesn't re-introduce the stripped image.
            mw.content_container.setStyleSheet(
                get_player_stylesheet(theme_name, suppress_bg_image=getattr(mw, '_bg_suppressed', False))
            )
        _mark("title_bar + content_container")
        if hasattr(mw, '_reload_button_icons'):
            mw._reload_button_icons(theme_name)
        _mark("_reload_button_icons")
        # chapter_list_widget stays on the FAST path unconditionally: update_theme() is
        # ~0.1ms (delegate color set + update()) and it's a real overlay that CAN be open
        # during a theme change, so keeping it fast removes the "chapter list opened before
        # the deferred batch ran" staleness case for free. (Was previously not-hover-gated;
        # now runs on hover too — harmless at 0.1ms, and it can be visible under the fade.)
        if hasattr(mw, 'chapter_list_widget'):
            # theme_name (this call's own argument), NOT self.get_current_theme() —
            # get_current_theme() resolves _active_display_theme_internal, which
            # _mark_theme_applied only writes AFTER this method returns (see the
            # call sites), so it still holds the PREVIOUS apply's theme at this
            # point. Reading it here made dropdown_text/dropdown_time_text/
            # dropdown_curr_chap always lag one theme change behind. Fixed
            # 2026-07-21 — see NOTES.md.
            from ..themes import _resolve_theme
            theme_dict = _resolve_theme(theme_name)
            mw.chapter_list_widget.update_theme(theme_dict)
            _mark("chapter_list_widget")
        else:
            _mark("chapter_list_widget", skipped=True)
        if hasattr(mw, 'sidebar'):
            logger.debug(f"t={time.perf_counter():.6f} [apply_stylesheets sidebar BEFORE]")
            mw.sidebar.setStyleSheet(get_sidebar_stylesheet(theme_name))
            logger.debug(f"t={time.perf_counter():.6f} [apply_stylesheets sidebar AFTER]")
        _mark("sidebar")
        if hasattr(mw, '_set_chapter_ui_active'):
            mw._set_chapter_ui_active(mw._chapter_ui_active)
        _mark("_set_chapter_ui_active")
        # settings_panel/speed_panel/sleep_panel (+ excluded-books, which lives on the
        # settings panel) stay on the FAST path unconditionally, same reasoning as
        # chapter_list_widget above: the Themes tab IS settings_panel, so a hover
        # preview that skips it silently defeats the whole point of hovering (the
        # preview never shows on the very panel the user is looking at). This must
        # run on every hover, not just non-hover — do NOT move it into
        # _apply_stylesheets_deferred (which is not-hover-gated) again.
        #
        # REGRESSION (found 2026-07-18, live-reported): the RANK-1 deferred-restyle
        # narrowing moved this whole block into _apply_stylesheets_deferred alongside
        # library_panel/stats_panel/book_detail_panel, which WERE already correctly
        # hover-gated before the narrowing. settings_panel/speed_panel/sleep_panel had
        # NO hover gate before the narrowing (confirmed via `git show <narrowing
        # commit>^` — the old loop ran unconditionally) — moving it into the
        # always-not-hover deferred method silently added a hover-skip that never
        # existed, breaking the Themes tab's own hover preview. Moved back here to
        # restore the original, intentional behavior.
        ss_panels = get_settings_stylesheet(theme_name)
        # SPURIOUS-ENTEREVENT GUARD (2026-07-20 — the "heartbeat" bug; see
        # NOTES.md for the full confirmed mechanism). settings_panel
        # .setStyleSheet() below forces Qt to re-run its style/geometry cascade
        # through the whole settings_panel subtree — including every ThemeItem
        # theme-pool button — which re-evaluates hit-testing for whatever's
        # under the cursor and can fire a SPURIOUS, fully realistic-looking
        # leaveEvent+enterEvent pair on a widget the cursor never actually left.
        # Confirmed live: the spurious pair is indistinguishable from a real
        # quick leave-and-return by shape alone (both fire, same cursor
        # position) — leave-presence is NOT a reliable discriminator on its
        # own. _spurious_enter_guard_until (a perf_counter() deadline, mirroring
        # the feedback-loop guard's _grab_suppress_until pattern from earlier
        # tonight) is the load-bearing signal instead, since it's derived from
        # code we control precisely rather than from event shape. ThemeItem
        # checks this window AND compares cursor position against the position
        # its own leaveEvent reported moments earlier, so a genuine same-widget
        # re-hover that happens to land in this narrow (~15ms) window by pure
        # coincidence is not swallowed — only an enter at the SAME position as
        # the immediately-preceding leave, inside this window, is treated as
        # synthetic.
        #
        # try/finally guarantees the flag is always cleared, even if something
        # in this block raises — mirrors the feedback-loop guard fix earlier
        # tonight exactly, for the same reason: a stuck-True guard here would
        # silently and permanently swallow real enterEvents on every theme
        # button, which given how routinely _apply_stylesheets(hover=False)
        # fires in normal use would break hover-preview entirely, not just the
        # spurious case.
        try:
            self.main_window._spurious_enter_guard_until = time.perf_counter() + _SPURIOUS_ENTER_GUARD_S
            for attr in ('settings_panel', 'speed_panel', 'sleep_panel'):
                w = getattr(mw, attr, None)
                if w:
                    w.setStyleSheet(ss_panels)
        finally:
            self.main_window._spurious_enter_guard_until = time.perf_counter() + _SPURIOUS_ENTER_GUARD_S
        _mark("settings/speed/sleep panels")
        section = getattr(mw, 'excluded_books_section', None)
        popup = getattr(mw, 'excluded_books_popup', None)
        if section or popup:
            from ..themes import _resolve_theme
            theme = _resolve_theme(theme_name)
            if section:
                section.set_theme(theme)
            if popup:
                popup.set_theme(theme)

        # Re-stamp at exit too (see the entry-side stamp above for why BOTH sites
        # are needed, added 2026-07-19). This second write moves the timestamp
        # forward to the actual completion instant, so the post-completion settle
        # window transport_bar_blur.py's cooldown gate gives Qt's repaint/repolish
        # backlog is measured from when the restyle really finished, not from when
        # it started.
        self._last_apply_stylesheets_at = time.perf_counter()

        if _dbg:
            total = sum(ms for _, ms, _ in _steps)
            parts = "  ".join(
                f"{lbl}={'SKIP' if sk else f'{ms:.1f}ms'}" for lbl, ms, sk in _steps
            )
            logger.debug(
                f"[_apply_stylesheets hover={hover}] total={total:.1f}ms  {parts}"
            )

    def _apply_stylesheets_deferred(self, theme_name):
        """The invisible-surface half of the theme apply, extracted from
        _apply_stylesheets so it can run in a deferred batch AFTER the flow animation
        (book-load) or on the next event-loop turn (rotation/T), instead of blocking
        the synchronous visible apply. Styles only currently-hidden, hover-agnostic
        surfaces: library, stats/book_detail. (settings/speed/sleep panels moved BACK
        to the fast path — see the REGRESSION comment there — because unlike these
        three, they must restyle on hover too.) Runs only for non-hover theme changes
        (hover keeps its own narrowing + _on_theme_unhovered restyle)."""
        _dbg = logger.isEnabledFor(logging.DEBUG)
        _steps = []
        _t = time.perf_counter()

        def _mark(label):
            nonlocal _t
            if _dbg:
                now = time.perf_counter()
                _steps.append((label, (now - _t) * 1000))
                _t = now

        mw = self.main_window
        if hasattr(mw, 'library_panel'):
            mw.library_panel.setStyleSheet(get_library_stylesheet(theme_name))
            mw.library_panel.update_progress_bar_theme()
        _mark("library_panel")
        ss_stats = get_stats_stylesheet(theme_name)
        for attr in ('stats_panel', 'book_detail_panel'):
            target = getattr(mw, attr, None)
            if target:
                target.setStyleSheet(ss_stats)
        # The "Recently finished" scroll rows' edge-scroll arrows use per-widget
        # instance stylesheets that the plain QSS repolish above does NOT reach —
        # they're refreshed by stats_panel.on_theme_changed, driven on every live
        # (non-hover) theme change by the theme_applied signal connection (see the
        # TAIL in _run_deferred_restyle). Do NOT re-add a direct call here — the
        # signal path is the single owner (see NOTES.md).
        _mark("stats + book_detail panels")

        if _dbg:
            total = sum(ms for _, ms in _steps)
            parts = "  ".join(f"{lbl}={ms:.1f}ms" for lbl, ms in _steps)
            logger.debug(f"[_apply_stylesheets_deferred] total={total:.1f}ms  {parts}")

    def _schedule_deferred_restyle(self, theme_name):
        """Arm the invisible-surface restyle batch to run once, off the synchronous
        visible apply path. Coalescing: multiple rapid triggers collapse to one batch
        with the last-requested theme (nothing invisible was shown in between). Uses a
        uniform singleShot(0); _run_deferred_restyle itself defers if a flow animation
        is still running (see there) so the ~355ms batch never lands mid-animation."""
        self._deferred_restyle_theme = theme_name  # last-write-wins
        if self._deferred_restyle_pending:
            return                                  # already queued — coalesce
        self._deferred_restyle_pending = True
        QTimer.singleShot(0, self._run_deferred_restyle)

    def _run_deferred_restyle(self):
        """Run the pending invisible-surface batch + the TAIL, once. No-op if nothing
        pending. CRITICAL: if a book-load flow animation is still running, do NOT run
        now — leave the flag armed and return; the progress-slider _flow_anim.finished
        connection (wired in MainWindow) re-invokes this after the animation completes,
        so the ~355ms batch lands AFTER the animation, never freezing it. rotation/T
        fire with no animation, so they run immediately on the singleShot(0) turn.

        ALSO defers while a theme FADE (_fade_in_flight, set by
        _do_fade_with_slider_animation) is running — found 2026-07-18: this guard used
        to check ONLY the flow animation, so a fade (750ms) that outlasted a book's own
        flow animation (as short as ~300ms — a plain MP3 with no cover reaches
        _on_file_ready fast enough to have already finished by the time this method's
        flow-animation wait clears) still got its flush landed mid-fade, producing a
        visible jump partway through the transition. _on_fade_finished re-invokes this
        method when the fade ends, mirroring the flow animation's own finished-signal
        wiring (app.py) — required so a restyle held back ONLY by the fade (no flow
        animation involved, e.g. a plain rotation from an idle screen) isn't stranded
        pending forever."""
        if not self._deferred_restyle_pending:
            return
        mw = self.main_window
        slider = getattr(mw, 'progress_slider', None)
        flow = getattr(slider, '_flow_anim', None)
        if flow is not None and flow.state() == QPropertyAnimation.Running:
            logger.debug(f"[STUTTER-TRACE] t={time.perf_counter():.6f} _run_deferred_restyle: "
                         f"DEFERRED (flow_anim still Running)")
            return  # animation still running — stay armed; _flow_anim.finished re-fires us
        if getattr(self, '_fade_in_flight', False):
            logger.debug(f"[STUTTER-TRACE] t={time.perf_counter():.6f} _run_deferred_restyle: "
                         f"DEFERRED (fade still in flight)")
            return  # fade still running — stay armed; _on_fade_finished re-fires us
        logger.debug(f"[STUTTER-TRACE] t={time.perf_counter():.6f} _run_deferred_restyle: "
                     f"proceeding via NATURAL path (flow_anim.finished or no-anim turn)")
        self._flush_deferred_restyle_now()

    def flush_deferred_restyle(self):
        """Force the pending batch to run synchronously NOW, bypassing the animation
        wait. This is the panel-open compensation: called before any panel's show()
        (from complete_main_fade and each _start_*_entry) so a panel opened before the
        deferred batch ran can never paint stale colors. Correctness wins over the rare
        mid-animation freeze here — it only fires when a panel-open genuinely races a
        still-pending batch, and only for that first open. No-op if nothing pending."""
        if not self._deferred_restyle_pending:
            logger.debug(f"[STUTTER-TRACE] t={time.perf_counter():.6f} flush_deferred_restyle: "
                         f"NOOP (nothing pending)")
            return
        logger.debug(f"[STUTTER-TRACE] t={time.perf_counter():.6f} flush_deferred_restyle: "
                     f"FORCING (was pending) — this is the panel-open compensation firing")
        self._flush_deferred_restyle_now()

    def _flush_deferred_restyle_now(self):
        """Run the batch + TAIL exactly once and clear the flag. Shared by the deferred
        path (_run_deferred_restyle) and the forced path (flush_deferred_restyle)."""
        _t0 = time.perf_counter()
        self._deferred_restyle_pending = False
        theme_name = self._deferred_restyle_theme
        self._deferred_restyle_theme = None
        if theme_name is None:
            logger.debug(f"[STUTTER-TRACE] t={_t0:.6f} _flush_deferred_restyle_now: NOOP (theme_name None)")
            return
        logger.debug(f"[STUTTER-TRACE] t={_t0:.6f} _flush_deferred_restyle_now: ENTRY theme={theme_name!r}")
        self._apply_stylesheets_deferred(theme_name)
        # TAIL (moved out of _on_theme_changed): hidden-panel visual sync.
        if hasattr(self.main_window, '_refresh_panel_visuals'):
            self.main_window._refresh_panel_visuals(theme_name)
        from ..themes import _resolve_theme
        self.theme_applied.emit(_resolve_theme(theme_name))
        self.update_theme_list_visuals()
        logger.debug(f"[_run_deferred_restyle] flushed batch for theme")
        _t1 = time.perf_counter()
        logger.debug(f"[STUTTER-TRACE] t={_t1:.6f} _flush_deferred_restyle_now: EXIT "
                     f"total={(_t1 - _t0) * 1000:.1f}ms")

    def toggle_theme_selection(self, theme_name):
        """Toggle a theme's presence in the rotation pool."""
        if theme_name in self.selected_themes:
            if len(self.selected_themes) > 1: # Ensure we don't make the list empty
                self.selected_themes.remove(theme_name)
                # If we removed the session theme, pick a new one from the remaining pool
                if self._current_theme_name == theme_name:
                    self._current_theme_name = random.choice(self.selected_themes)
                    self._on_theme_changed(self._current_theme_name, save=False,
                                            bypass_panel_open_guard=True)
            # If it's the last selected theme, we don't remove it (pool cannot be empty)
        else:
            # Add to pool, but do NOT change the session active theme on left-click
            self.selected_themes.append(theme_name) 

        # Save the pool as a comma-separated string
        self.config.set_theme(",".join(self.selected_themes))
        self.update_theme_list_visuals()

    def select_all_themes(self):
        self.selected_themes = list(THEMES.keys())
        self.config.set_theme(",".join(self.selected_themes))
        self.update_theme_list_visuals()

    def deselect_all_themes(self):
        # Fallback to the current theme or a default so the list is never empty
        self.selected_themes = [self._current_theme_name]
        self.config.set_theme(",".join(self.selected_themes))
        self.update_theme_list_visuals()

    def set_rotation_interval(self, minutes):
        """Update the rotation interval and restart the timer if necessary."""
        self.config.set_theme_rotation_interval(minutes)
        self.rotation_timer.stop()
        
        if minutes > 0:
            # Convert minutes to milliseconds
            self.rotation_timer.start(minutes * 60 * 1000)
        
        self.update_interval_visuals()
    def _on_theme_right_clicked(self, theme_name):
        """Selects a theme and immediately activates it."""
        # A hover preview may still be queued (debounce hasn't fired yet) or
        # in flight for this or another swatch the cursor swept over en route.
        # Cancel it so a stale delayed preview can't land after this commit and
        # win the last-write race on _active_display_theme_internal / the underline.
        self._hover_debounce_timer.stop()
        self._pending_hover_theme = None
        if theme_name not in self.selected_themes:
            self.selected_themes.append(theme_name)
            self.config.set_theme(",".join(self.selected_themes))
        self._current_theme_name = theme_name
        self._recent_themes.append(theme_name)
        self._cover_theme_active = False
        self._on_theme_changed(theme_name, save=False, bypass_panel_open_guard=True)
        self._restart_rotation_timer()
        self.update_theme_list_visuals()
        self.update_interval_visuals()

    def update_interval_visuals(self):
        current_interval = self.config.get_theme_rotation_interval()
        for mins, btn in self.interval_widgets.items():
            btn.setProperty("selected", mins == current_interval)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _on_theme_hovered(self, theme_name):
        """Queue a debounced theme preview. Sweeping across several names only
        restyles for the one the cursor settles on (see _fire_pending_hover)."""
        self._pending_hover_theme = theme_name
        self._hover_seen_at = time.perf_counter()
        self._hover_debounce_timer.start()  # restart on each enter → coalesces the sweep

    def _fire_pending_hover(self):
        """Debounce timer elapsed without a newer hover — run the real preview."""
        theme_name = self._pending_hover_theme
        if theme_name is None:
            return
        self._pending_hover_theme = None
        if logger.isEnabledFor(logging.DEBUG) and self._hover_seen_at is not None:
            wait_ms = (time.perf_counter() - self._hover_seen_at) * 1000
            logger.debug(
                f"[hover debounce] firing preview for {theme_name!r} "
                f"{wait_ms:.1f}ms after last enterEvent"
            )
        fade = int(self.config.get_theme_fade_duration() * 0.5)
        self._on_theme_changed(theme_name, save=False, fade_ms=fade, hover=True)

    def _on_theme_unhovered(self):
        # Cancel any hover preview still queued by the debounce so a stale name
        # can't fire its restyle after the cursor has already left the tab.
        self._hover_debounce_timer.stop()
        self._pending_hover_theme = None
        if self._cover_theme_active and self._cover_theme:
            self._on_theme_changed(self._cover_theme, save=False, fade_ms=_SNAPBACK_FADE_MS,
                                    hover=False, bypass_panel_open_guard=True)
        else:
            self._on_theme_changed(self._current_theme_name, save=False, fade_ms=_SNAPBACK_FADE_MS,
                                    hover=False, bypass_panel_open_guard=True)

    def _on_themes_tab_left(self, tab_widget):
        """`themes_tab`'s AND `pool_container`'s leaveEvent handler (both wired in
        main_window_builders.py as bare lambdas). Skips the unhover snapback when the
        leave fires while `tab_widget` itself is not visible — i.e. a synthetic leave
        caused by the transport-bar blur grab's `_active_panel.hide()`
        (transport_bar_blur.py's `_grab_and_blur`), NOT a real mouse-out. Mirrors
        `ThemeItem`'s own `_last_leave_was_synthetic` check (title_bar.py, the 2026-07-21
        "heartbeat" fix) but simplified: unlike a single swatch, this tab-level widget has
        no `enterEvent` to pair against (hover is driven entirely by each `ThemeItem.hovered`
        signal), so there's no "same position" check to make — a real mouse-out of the whole
        tab always happens while the tab is visible, and a leave that fires while it is NOT
        visible is never a genuine user action to react to.

        `pool_container` (the innermost container directly holding the `ThemeItem` swatch
        grid) needed this fix too — confirmed live 2026-07-22, NOT assumed from the shared
        lambda shape: a caller-identifying trace on `_on_theme_unhovered` showed 133/134
        calls in one hover session came from `pool_container.leaveEvent`
        (main_window_builders.py:768), not `themes_tab.leaveEvent` — `pool_container` is
        the INNER widget, so its own `leaveEvent` fires first on the blur grab's synthetic
        hide, before the cursor's hit-test ever reaches `themes_tab` itself. Fixing only
        `themes_tab` (the first pass of this bug) left the bug fully intact in practice.

        Without this guard, the blur grab's hide/show cycle (~200ms while a book plays) calls
        _on_theme_unhovered() -> _hover_debounce_timer.stop() every cycle; a cycle landing
        inside a swatch's 80ms hover-debounce window kills the timer before it can fire,
        silently dropping a genuinely-still-hovered theme's preview. Confirmed live
        2026-07-22 (see NOTES.md) — a genuine ThemeItem.enterEvent PASSED followed 7ms later
        by a synthetic-recorded leaveEvent, well inside the debounce window, with no
        `[hover debounce]` fire ever appearing for that hover."""
        if not tab_widget.isVisible():
            return
        self._on_theme_unhovered()

    def update_theme_list_visuals(self):
        """Dim unselected themes and highlight selected ones."""
        # NOT the cause of the "heartbeat" bug (an earlier theory, disproven
        # 2026-07-20 — see NOTES.md; the real cause was settings_panel
        # .setStyleSheet() in _apply_stylesheets, fixed there via
        # _spurious_enter_guard_until). This unpolish()/polish()-only-when-
        # changed guard is kept anyway as a harmless, legitimate minor
        # optimization (skips repolishing buttons whose visual state didn't
        # actually change) — read each button's CURRENT live property values
        # via btn.property(...) and compare against the freshly computed
        # target, never a separately-tracked "previous" value, so it can't
        # drift out of sync with whatever else might set these properties. A
        # brand-new/never-polished button reads back None for a property never
        # explicitly set, which never equals a real bool target, so first-time
        # polish always happens.
        for name, btn in self.theme_widgets.items():
            is_selected = name in self.selected_themes
            is_active_display = (name == self._current_theme_name) and not self._cover_theme_active

            changed = (
                btn.property("selected") != is_selected
                or btn.property("active_display") != is_active_display
            )

            btn.setProperty("selected", is_selected)
            btn.setProperty("active_display", is_active_display)
            if changed:
                btn.style().unpolish(btn)
                btn.style().polish(btn)
        self._update_cover_pool_btn()

    # ── Cover-art theme ─────────────────────────────────────────────────────

    def apply_cover_theme(self, pixmap, user_initiated=False):
        """Build a theme dict from the cover pixmap and apply it if the mode calls for it."""
        import traceback
        _caller_frame = traceback.extract_stack()[-2]
        logger.debug(f"[STUTTER-TRACE] t={time.perf_counter():.6f} apply_cover_theme: ENTRY "
                     f"user_initiated={user_initiated} "
                     f"caller={_caller_frame.filename.split('/')[-1]}:{_caller_frame.lineno} "
                     f"in {_caller_frame.name}")
        from .cover_theme import build_cover_theme
        mode = self.config.get_cover_art_theme_mode()
        if mode == "off":
            # BUG FIX (2026-07-17): this used to bare-return here with no theme applied at all.
            # This is the ONLY code path that ever calls _on_theme_changed for a book WITH a
            # cover (ThemeManager.__init__ never applies a theme itself, and app.py's startup
            # has no other trigger) — so "Off" silently meant "no theme, ever" for any such
            # book: the whole app rendered as unstyled bare Qt chrome for the entire session,
            # until something unrelated (manual theme rotation, etc.) happened to call
            # _on_theme_changed for the first time. The no-cover case already gets this right
            # via clear_cover_theme() (_load_cover_art -> _show_no_cover_state). "Off" is
            # supposed to mean "plain pool theme, no cover-derived tinting" — not "no theme" —
            # so route through the same call the no-cover case already uses correctly.
            logger.debug(f"[STUTTER-TRACE] t={time.perf_counter():.6f} apply_cover_theme: "
                         f"mode=off, applying plain pool theme via clear_cover_theme")
            self.clear_cover_theme(bypass_panel_open_guard=user_initiated)
            logger.debug(f"[STUTTER-TRACE] t={time.perf_counter():.6f} apply_cover_theme: EXIT (mode=off)")
            return
        theme_dict = build_cover_theme(pixmap)
        if not theme_dict:
            logger.debug(f"[STUTTER-TRACE] t={time.perf_counter():.6f} apply_cover_theme: EXIT (no theme_dict)")
            return
        self._cover_theme = theme_dict
        self._cover_theme_active = True
        logger.debug(f"[STUTTER-TRACE] t={time.perf_counter():.6f} apply_cover_theme: "
                     f"calling _on_theme_changed")
        # user_initiated already correctly distinguishes a deliberate Themes-tab
        # action (set_cover_art_mode passes True) from a book-load-driven call
        # (app.py's default False) — reuse it directly rather than adding a
        # separate parameter with the same meaning.
        self._on_theme_changed(theme_dict, save=False, user_initiated=user_initiated,
                                bypass_panel_open_guard=user_initiated)
        self._update_cover_pool_btn()
        logger.debug(f"[STUTTER-TRACE] t={time.perf_counter():.6f} apply_cover_theme: EXIT (applied)")

    def clear_cover_theme(self, bypass_panel_open_guard=False):
        """Revert to the pool theme. _cover_theme stays None so cover_pool_btn greys out.

        bypass_panel_open_guard: forwarded to _on_theme_changed. Default False is
        correct for this method's GENERAL-trigger callers (_fire_pending_rotation's
        deferred timer, request_clear_cover_theme — both book-cover-removed paths
        with no relationship to any open panel). Pass True only from a
        Themes-tab-local caller (currently: _on_cover_pool_btn_clicked, and
        set_cover_art_mode's own internal call) — see _on_theme_changed's
        bypass_panel_open_guard docstring for the full category rule."""
        self._cover_theme = None
        self._cover_theme_active = False
        self._on_theme_changed(self._current_theme_name, save=False,
                                bypass_panel_open_guard=bypass_panel_open_guard)
        self._update_cover_pool_btn()

    def set_cover_art_mode(self, mode: str):
        """Switch cover art mode ('off', 'with_pool', 'exclusive') and reapply."""
        self.config.set_cover_art_theme_mode(mode)
        self.update_cover_art_mode_visuals()
        if mode == "off":
            if self._cover_theme_active:
                self.clear_cover_theme(bypass_panel_open_guard=True)
            else:
                self._on_theme_changed(self._current_theme_name, save=False,
                                        bypass_panel_open_guard=True)
        else:
            pixmap = getattr(self.main_window, 'current_cover_pixmap', None)
            if self._cover_theme is None and pixmap and not pixmap.isNull():
                self.apply_cover_theme(pixmap, user_initiated=True)
            elif self._cover_theme:
                self._cover_theme_active = True
                self._on_theme_changed(self._cover_theme, save=False, bypass_panel_open_guard=True)

    def update_cover_art_mode_visuals(self):
        current = self.config.get_cover_art_theme_mode()
        for mode, btn in self.cover_art_mode_widgets.items():
            btn.setProperty("selected", mode == current)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        if self.pool_container is not None:
            self.pool_container.setVisible(current != "exclusive")
        self._update_cover_pool_btn()

    def _update_cover_pool_btn(self):
        # Same fix, same reasoning as update_theme_list_visuals() above (the
        # "heartbeat" bug) — only repolish when the button's live state is
        # actually changing, checked against btn's own current property/enabled
        # values, never a cached copy.
        btn = self.cover_pool_btn
        if btn is None:
            return
        mode = self.config.get_cover_art_theme_mode()
        has_cover = self._cover_theme is not None
        in_pool = (mode == "with_pool")
        should_be_enabled = mode == "off" or has_cover  # always clickable in Off; needs cover in With pool

        changed = (
            btn.isEnabled() != should_be_enabled
            or btn.property("selected") != in_pool
            or btn.property("active_display") != self._cover_theme_active
        )

        btn.setEnabled(should_be_enabled)
        btn.setProperty("selected", in_pool)
        btn.setProperty("active_display", self._cover_theme_active)
        if changed:
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _on_cover_pool_btn_clicked(self):
        mode = self.config.get_cover_art_theme_mode()
        if mode == "off":
            # Add to pool: switch to With pool mode
            self.set_cover_art_mode("with_pool")
        else:
            # Remove from pool: deactivate if active, switch back to Off. Route
            # through clear_cover_theme() (not a manual _cover_theme_active +
            # _on_theme_changed inline) so _cover_theme is actually reset to
            # None, not left stale — see clear_cover_theme's own docstring.
            if self._cover_theme_active:
                self.clear_cover_theme(bypass_panel_open_guard=True)
            self.set_cover_art_mode("off")

    def _on_cover_pool_btn_right_clicked(self):
        # Same race as _on_theme_right_clicked: cancel any queued/in-flight hover
        # preview so it can't fire after this click and clobber the committed state.
        self._hover_debounce_timer.stop()
        self._pending_hover_theme = None
        mode = self.config.get_cover_art_theme_mode()
        if not self._cover_theme:
            return
        # Ensure it's in the pool
        if mode == "off":
            self.config.set_cover_art_theme_mode("with_pool")
            self.update_cover_art_mode_visuals()
        # Activate the cover theme
        self._cover_theme_active = True
        self._on_theme_changed(self._cover_theme, save=False, bypass_panel_open_guard=True)
        self._update_cover_pool_btn()

    def _on_cover_pool_btn_hovered(self):
        # Moving from a theme name onto the cover-pool button: drop any queued
        # theme hover so it can't fire its preview after this one.
        self._hover_debounce_timer.stop()
        self._pending_hover_theme = None
        if not self._cover_theme:
            return
        fade = int(self.config.get_theme_fade_duration() * 0.5)
        self._on_theme_changed(self._cover_theme, save=False, fade_ms=fade, hover=True)