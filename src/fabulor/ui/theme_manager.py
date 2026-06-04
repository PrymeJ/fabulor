import random
import warnings
from PySide6.QtWidgets import QLabel, QGraphicsOpacityEffect, QPushButton, QComboBox
from PySide6.QtCore import Qt, QPropertyAnimation, QTimer, Signal, QObject, QEasingCurve
from PySide6.QtGui import QFont, QFontMetrics, QColor
from ..themes import (
    get_base_stylesheet, get_title_bar_stylesheet, get_player_stylesheet,
    get_library_stylesheet, get_settings_stylesheet, get_sidebar_stylesheet,
    get_stats_stylesheet, THEMES
)

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

        self._save_on_fade = False

    def get_current_theme(self) -> dict:
        active = self._active_display_theme or self._current_theme_name
        if isinstance(active, dict):
            from ..themes import _resolve_theme
            return _resolve_theme(active)
        return THEMES.get(active, THEMES["The Color Purple"])
    
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
        if self.main_window.panel_manager and self.main_window.panel_manager._any_panel_animating():
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
            if isinstance(theme_name, dict):
                from ..themes import _resolve_theme
                self.theme_applied.emit(_resolve_theme(theme_name))
            else:
                self.theme_applied.emit(THEMES.get(theme_name, THEMES["The Color Purple"]))
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

        if fade_ms > 0 and themes_tab_active:
            # Themes tab visible — user is deliberately previewing themes, nothing is
            # moving. Full overlay fade including sliders (original behavior).
            pix = self.main_window.grab()
            self._fade_overlay.setPixmap(pix)
            self._fade_overlay.setGeometry(self.main_window.rect())

            from PySide6.QtGui import QRegion
            if pm and pm.is_any_panel_visible():
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
            else:
                self._fade_overlay.clearMask()

            self._fade_overlay.show()
            self._fade_overlay.raise_()

            self._save_on_fade = save
            self._fade_anim.setDuration(fade_ms)
            self._fade_anim.start()
            self._theme_fade_anim = self._fade_anim
            self._apply_stylesheets(theme_name, hover=hover)
        elif fade_ms > 0:
            # Auto-rotation (or any non-themes-tab fade): sliders may be mid-interaction.
            # Exclude them from the overlay and animate their color properties instead.
            self._do_fade_with_slider_animation(theme_name, hover, save, fade_ms)
        else:
            self._fade_overlay.hide()
            if save:
                self._cached_theme_pixmap = self.main_window.grab()
            self._apply_stylesheets(theme_name, hover=hover)

        if hasattr(self.main_window, '_refresh_panel_visuals'):
            self.main_window._refresh_panel_visuals(theme_name)
        if isinstance(theme_name, dict):
            from ..themes import _resolve_theme
            self.theme_applied.emit(_resolve_theme(theme_name))
        else:
            self.theme_applied.emit(THEMES.get(theme_name, THEMES["The Color Purple"]))
        self.update_theme_list_visuals()

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

        self._fade_overlay.show()
        self._fade_overlay.raise_()
        self._save_on_fade = save
        self._fade_anim.setDuration(fade_ms)
        self._fade_anim.start()
        self._theme_fade_anim = self._fade_anim

        # Apply new stylesheet — qproperty colors land on next event loop tick
        self._apply_stylesheets(theme_name, hover=hover)

        # Defer color animation until QSS has applied
        def _start_color_anims():
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

    def _apply_stylesheets(self, theme_name, hover=False):
        mw = self.main_window
        mw.setStyleSheet(get_base_stylesheet(theme_name))
        if hasattr(mw, 'title_bar'):
            mw.title_bar.setStyleSheet(get_title_bar_stylesheet(theme_name))
        if hasattr(mw, 'content_container'):
            # Honor the no-book/empty-state bg-image suppression so a theme change
            # in those states doesn't re-introduce the stripped image.
            mw.content_container.setStyleSheet(
                get_player_stylesheet(theme_name, suppress_bg_image=getattr(mw, '_bg_suppressed', False))
            )
        if hasattr(mw, '_reload_button_icons'):
            mw._reload_button_icons(theme_name)
        if not hover and hasattr(mw, 'library_panel'):
            mw.library_panel.setStyleSheet(get_library_stylesheet(theme_name))
            mw.library_panel.update_progress_bar_theme()
        ss_panels = get_settings_stylesheet(theme_name)
        for attr in ('settings_panel', 'speed_panel', 'sleep_panel'):
            w = getattr(mw, attr, None)
            if w:
                w.setStyleSheet(ss_panels)
        ss_stats = get_stats_stylesheet(theme_name)
        for attr in ('stats_panel', 'book_detail_panel'):
            target = getattr(mw, attr, None)
            if target:
                target.setStyleSheet(ss_stats)
        if hasattr(mw, 'sidebar'):
            mw.sidebar.setStyleSheet(get_sidebar_stylesheet(theme_name))
        if hasattr(mw, '_set_chapter_ui_active'):
            mw._set_chapter_ui_active(mw._chapter_ui_active)

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
        """Preview the theme visually."""
        fade = int(self.config.get_theme_fade_duration() * 0.5)
        self._on_theme_changed(theme_name, save=False, fade_ms=fade, hover=True)

    def _on_theme_unhovered(self):
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
        if not self._cover_theme:
            return
        fade = int(self.config.get_theme_fade_duration() * 0.5)
        self._on_theme_changed(self._cover_theme, save=False, fade_ms=fade, hover=True)