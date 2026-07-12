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
_HOVER_DEBOUNCE_MS    = 60        # coalesce rapid hover sweeps into one preview restyle



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
        self._active_display_theme = self._current_theme_name

        # Cover-art derived theme (dict or None)
        self._cover_theme: dict | None = None
        self._cover_theme_active = False  # True when cover theme is currently displayed

        # Rotation Timer
        self._pending_rotation = False
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

    def get_current_theme(self) -> dict:
        from ..themes import _resolve_theme
        active = self._active_display_theme or self._current_theme_name
        return _resolve_theme(active)
    
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
        self._fade_in_flight = False
        self._fade_overlay.hide()
        self._unfreeze_fade_labels()
        if self._save_on_fade:
            self._cached_theme_pixmap = self.main_window.grab()

    def snap_theme_forward(self):
        if not hasattr(self, '_fade_anim'):
            return
        if self._fade_anim.state() == QPropertyAnimation.Running:
            self._fade_anim.stop()
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
            self._apply_stylesheets(self._active_display_theme, hover=self._is_hover_active)
            if hasattr(self.main_window, '_refresh_panel_visuals'):
                self.main_window._refresh_panel_visuals(self._active_display_theme)

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
        mode = self.config.get_cover_art_theme_mode()
        if mode == "exclusive" and self._cover_theme:
            return
        if self.main_window.panel_manager and self.main_window.panel_manager.is_any_panel_visible():
            self._pending_rotation = True
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
            if chosen is None:
                self._cover_theme_active = True
                self._on_theme_changed(self._cover_theme, save=False, user_initiated=user_initiated)
            else:
                self._current_theme_name = chosen
                self._cover_theme_active = False
                self._on_theme_changed(chosen, save=False, user_initiated=user_initiated)
            # Record chosen theme in recent history (named themes only)
            if chosen is not None:
                self._recent_themes.append(chosen)
            self._restart_rotation_timer()

    def _restart_rotation_timer(self):
        interval = self.config.get_theme_rotation_interval()
        if interval > 0:
            self.rotation_timer.start(interval * 60 * 1000)

    def _fire_pending_rotation(self):
        if self._pending_rotation:
            self._pending_rotation = False
            QTimer.singleShot(3000, self._rotate_theme)

    def _on_theme_changed(self, theme_name, save=True, fade_ms=None, hover=False, user_initiated=True):
        """Update the appearance with a subtle fade transition."""

        if fade_ms is None:
            fade_ms = _THEME_SWITCH_FADE_MS if not hover else self.config.get_theme_fade_duration()

        # Only guard if both the theme and hover state match
        if (getattr(self, "_active_display_theme", None) == theme_name
                and self._is_hover_active == hover):
            return

        self._is_hover_active = hover

        # Guard against theme changes during panel animation to prevent hitches
        _any_animating = bool(
            self.main_window.panel_manager and self.main_window.panel_manager._any_panel_animating()
        )
        logger.debug(
            f"t={time.perf_counter():.6f} [_on_theme_changed GUARD] "
            f"any_panel_animating={_any_animating}"
            + (" -> queuing deferred retry" if _any_animating else "")
        )
        if _any_animating:
            self._panel_guard_timer.stop()
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", RuntimeWarning)
                    self._panel_guard_timer.timeout.disconnect()
            except (TypeError, RuntimeError):
                pass
            self._panel_guard_timer.timeout.connect(
                lambda: self._on_theme_changed(theme_name, save, fade_ms, hover, user_initiated)
            )
            self._panel_guard_timer.start()
            return

        self._active_display_theme = theme_name

        if not hasattr(self, '_fade_anim'):
            # Called before initialize_fade_overlay (e.g. on startup cover load) — apply silently
            self._apply_stylesheets(theme_name, hover=hover)
            if hasattr(self.main_window, '_refresh_panel_visuals'):
                self.main_window._refresh_panel_visuals(theme_name)
            from ..themes import _resolve_theme
            self.theme_applied.emit(_resolve_theme(theme_name))
            self.update_theme_list_visuals()
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

        # Hidden-panel visual sync (settings-button states, tags/book-detail/stats
        # via theme_applied, theme-list dimming) is skipped on hover: none of it is
        # visible during a themes-tab preview, and the hover-exit full restyle
        # re-runs all of it before any of those surfaces can be shown again.
        if not hover:
            if hasattr(self.main_window, '_refresh_panel_visuals'):
                self.main_window._refresh_panel_visuals(theme_name)
            from ..themes import _resolve_theme
            self.theme_applied.emit(_resolve_theme(theme_name))
            self.update_theme_list_visuals()

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
        stylesheet for _active_display_theme re-polishes them to the correct
        values, overriding whatever the stopped animation left behind."""
        if not getattr(self, '_fade_in_flight', False):
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
        # Re-polish the slider qproperty colors to the new theme (overrides any
        # stranded intermediate value left by a stopped animation).
        self._apply_stylesheets(self._active_display_theme, hover=self._is_hover_active)

    def _apply_stylesheets(self, theme_name, hover=False):
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
        if not hover and hasattr(mw, 'library_panel'):
            mw.library_panel.setStyleSheet(get_library_stylesheet(theme_name))
            mw.library_panel.update_progress_bar_theme()
            _mark("library_panel")
        else:
            _mark("library_panel", skipped=True)
        if not hover and hasattr(mw, 'chapter_list_widget'):
            theme_dict = self.get_current_theme() or {}
            mw.chapter_list_widget.update_theme(theme_dict)
            _mark("chapter_list_widget")
        else:
            _mark("chapter_list_widget", skipped=True)
        ss_panels = get_settings_stylesheet(theme_name)
        for attr in ('settings_panel', 'speed_panel', 'sleep_panel'):
            w = getattr(mw, attr, None)
            if w:
                w.setStyleSheet(ss_panels)
        _mark("settings/speed/sleep panels")
        # Excluded-books toggle + popup use per-widget instance stylesheets, so
        # retint them explicitly on theme change (the panel QSS repolish above
        # doesn't reach them — the popup isn't even a descendant of
        # settings_panel, it's parented to MainWindow directly).
        section = getattr(mw, 'excluded_books_section', None)
        popup = getattr(mw, 'excluded_books_popup', None)
        if section or popup:
            from ..themes import _resolve_theme
            theme = _resolve_theme(theme_name)
            if section:
                section.set_theme(theme)
            if popup:
                popup.set_theme(theme)
        # stats_panel + book_detail_panel are always hidden while the Themes tab
        # previews a hover; skip their QSS repolish and on_theme_changed pass on
        # hover — the hover-exit full restyle re-applies them before either can
        # ever become visible.
        if not hover:
            ss_stats = get_stats_stylesheet(theme_name)
            for attr in ('stats_panel', 'book_detail_panel'):
                target = getattr(mw, attr, None)
                if target:
                    target.setStyleSheet(ss_stats)
            # The "Recently finished" scroll rows' edge-scroll arrows use
            # per-widget instance stylesheets that the plain QSS repolish above
            # does NOT reach — they're refreshed by stats_panel.on_theme_changed,
            # which is already driven on every live (non-hover) theme change by
            # the theme_applied signal connection (main_window_builders.py, wired
            # since the ThemeManager-QObject introduction). A direct call here was
            # added later on the mistaken premise that on_theme_changed only ran
            # once at startup; it was a true duplicate of the signal path and was
            # removed (see NOTES.md). Do NOT re-add it — the signal path is the
            # single owner, matching tags_panel / book_detail_panel.
            _mark("stats + book_detail panels")
        else:
            _mark("stats + book_detail panels", skipped=True)
        if hasattr(mw, 'sidebar'):
            logger.debug(f"t={time.perf_counter():.6f} [apply_stylesheets sidebar BEFORE]")
            mw.sidebar.setStyleSheet(get_sidebar_stylesheet(theme_name))
            logger.debug(f"t={time.perf_counter():.6f} [apply_stylesheets sidebar AFTER]")
        _mark("sidebar")
        if hasattr(mw, '_set_chapter_ui_active'):
            mw._set_chapter_ui_active(mw._chapter_ui_active)
        _mark("_set_chapter_ui_active")

        if _dbg:
            total = sum(ms for _, ms, _ in _steps)
            parts = "  ".join(
                f"{lbl}={'SKIP' if sk else f'{ms:.1f}ms'}" for lbl, ms, sk in _steps
            )
            logger.debug(
                f"[_apply_stylesheets hover={hover}] total={total:.1f}ms  {parts}"
            )

    def toggle_theme_selection(self, theme_name):
        """Toggle a theme's presence in the rotation pool."""
        if theme_name in self.selected_themes:
            if len(self.selected_themes) > 1: # Ensure we don't make the list empty
                self.selected_themes.remove(theme_name)
                # If we removed the session theme, pick a new one from the remaining pool
                if self._current_theme_name == theme_name:
                    self._current_theme_name = random.choice(self.selected_themes)
                    self._on_theme_changed(self._current_theme_name, save=False)
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
        # win the last-write race on _active_display_theme / the underline.
        if logger.isEnabledFor(logging.DEBUG) and self._pending_hover_theme is not None:
            logger.debug(
                f"[right-click {theme_name!r}] cancelling pending hover preview "
                f"for {self._pending_hover_theme!r} (debounce still armed)"
            )
        self._hover_debounce_timer.stop()
        self._pending_hover_theme = None
        if theme_name not in self.selected_themes:
            self.selected_themes.append(theme_name)
            self.config.set_theme(",".join(self.selected_themes))
        self._current_theme_name = theme_name
        self._recent_themes.append(theme_name)
        self._cover_theme_active = False
        self._on_theme_changed(theme_name, save=False)
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
            self._on_theme_changed(self._cover_theme, save=False, fade_ms=_SNAPBACK_FADE_MS, hover=False)
        else:
            self._on_theme_changed(self._current_theme_name, save=False, fade_ms=_SNAPBACK_FADE_MS, hover=False)

    def update_theme_list_visuals(self):
        """Dim unselected themes and highlight selected ones."""
        for name, btn in self.theme_widgets.items():
            is_selected = name in self.selected_themes
            is_active_display = (name == self._current_theme_name) and not self._cover_theme_active

            btn.setProperty("selected", is_selected)
            btn.setProperty("active_display", is_active_display)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self._update_cover_pool_btn()

    # ── Cover-art theme ─────────────────────────────────────────────────────

    def apply_cover_theme(self, pixmap, user_initiated=False):
        """Build a theme dict from the cover pixmap and apply it if the mode calls for it."""
        from .cover_theme import build_cover_theme
        mode = self.config.get_cover_art_theme_mode()
        if mode == "off":
            return
        theme_dict = build_cover_theme(pixmap)
        if not theme_dict:
            return
        self._cover_theme = theme_dict
        self._cover_theme_active = True
        self._on_theme_changed(theme_dict, save=False, user_initiated=user_initiated)
        self._update_cover_pool_btn()

    def clear_cover_theme(self):
        """Revert to the pool theme. _cover_theme stays None so cover_pool_btn greys out."""
        self._cover_theme = None
        self._cover_theme_active = False
        self._on_theme_changed(self._current_theme_name, save=False)
        self._update_cover_pool_btn()

    def set_cover_art_mode(self, mode: str):
        """Switch cover art mode ('off', 'with_pool', 'exclusive') and reapply."""
        self.config.set_cover_art_theme_mode(mode)
        self.update_cover_art_mode_visuals()
        if mode == "off":
            if self._cover_theme_active:
                self.clear_cover_theme()
            else:
                self._on_theme_changed(self._current_theme_name, save=False)
        else:
            pixmap = getattr(self.main_window, 'current_cover_pixmap', None)
            if self._cover_theme is None and pixmap and not pixmap.isNull():
                self.apply_cover_theme(pixmap, user_initiated=True)
            elif self._cover_theme:
                self._cover_theme_active = True
                self._on_theme_changed(self._cover_theme, save=False)

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
        btn = self.cover_pool_btn
        if btn is None:
            return
        mode = self.config.get_cover_art_theme_mode()
        has_cover = self._cover_theme is not None
        in_pool = (mode == "with_pool")
        btn.setEnabled(mode == "off" or has_cover)  # always clickable in Off; needs cover in With pool
        btn.setProperty("selected", in_pool)
        btn.setProperty("active_display", self._cover_theme_active)
        btn.style().unpolish(btn)
        btn.style().polish(btn)

    def _on_cover_pool_btn_clicked(self):
        mode = self.config.get_cover_art_theme_mode()
        if mode == "off":
            # Add to pool: switch to With pool mode
            self.set_cover_art_mode("with_pool")
        else:
            # Remove from pool: deactivate if active, switch back to Off
            if self._cover_theme_active:
                self._cover_theme_active = False
                self._on_theme_changed(self._current_theme_name, save=False)
            self.set_cover_art_mode("off")

    def _on_cover_pool_btn_right_clicked(self):
        # Same race as _on_theme_right_clicked: cancel any queued/in-flight hover
        # preview so it can't fire after this click and clobber the committed state.
        if logger.isEnabledFor(logging.DEBUG) and self._pending_hover_theme is not None:
            logger.debug(
                f"[right-click cover-pool] cancelling pending hover preview "
                f"for {self._pending_hover_theme!r} (debounce still armed)"
            )
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
        self._on_theme_changed(self._cover_theme, save=False)
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