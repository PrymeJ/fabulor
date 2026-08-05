"""Write-path confinement fix (2026-08-04, pure, headless, synthetic).

See review/Design_260804_write_path_confinement.md. Confirmed live (2026-08-03/04) that hovering a
Themes-tab swatch could leak into Library's cached colors and Speed/Sleep's preset-ramp buttons, with
nothing to ever correct it except an unrelated later theme-apply cycle (measured up to 78s of
staleness). Root cause: several consumers call get_current_theme() directly from ordinary UI events
(a view-mode click, typing in search, a preset-button click) that have no relationship to a theme
change and no confinement — get_current_theme() now resolves through the hover-INCLUSIVE
get_displayed_theme(), so any of those unrelated events could bake a live hover into a panel that is
structurally invisible while any hover is possible (Settings and Library/Speed/Sleep are mutually
exclusive panels — see CLAUDE.md).

Fix: these consumers now read get_committed_theme() (a thin accessor over _current_theme_name, which
is written ONLY by a deliberate right-click/rotation/pool-edit, never by any hover path) instead of
get_current_theme().

Verification here is SYNTHETIC by necessity, not preference: per CLAUDE.md, Settings and
Library/Speed/Sleep can never be visible at the same time, so a live manual repro can only ever
observe "hover, then close Settings, then trigger the site" — by which point the hover has already
ended and there is no way to distinguish "the fix worked" from "the hover ended for an unrelated
reason before the site fired." These tests instead force _is_hover_active=True with
_active_display_theme_internal set to a theme DIFFERENT from _current_theme_name, call each fixed
consumer directly, and assert the committed theme was used, never the forced hover value.
"""
import pytest

from fabulor.ui.theme_manager import ThemeManager
from fabulor import themes


COMMITTED = "Fire and Blood"
HOVER = "Cerulean Sea"  # a genuinely discriminating theme (different accent/library colors)


class _FakeTM:
    """Minimal stand-in exposing exactly what get_committed_theme() touches. Deliberately does
    NOT bind get_active_theme()/get_current_theme()/get_displayed_theme() — this test suite is
    about confirming consumers no longer call those at all, not about re-verifying their own
    hover-safety (covered by test_get_current_theme_hover_safety.py)."""

    get_committed_theme = ThemeManager.get_committed_theme

    def __init__(self, current_theme_name, is_hover_active=False, active_display_theme_internal=None,
                 cover_theme_active=False, cover_theme=None):
        self._current_theme_name = current_theme_name
        self._is_hover_active = is_hover_active
        self._active_display_theme_internal = active_display_theme_internal
        self._cover_theme_active = cover_theme_active
        self._cover_theme = cover_theme


def _hovering_fake_tm():
    """A ThemeManager stand-in mid-hover: committed theme is Fire and Blood, but a hover preview
    (Cerulean Sea) is genuinely, currently showing on the Themes tab."""
    return _FakeTM(
        current_theme_name=COMMITTED,
        is_hover_active=True,
        active_display_theme_internal=HOVER,
    )


def test_get_committed_theme_ignores_a_live_hover():
    # THE CORE FIX'S FOUNDATION. get_committed_theme() must return the committed value
    # regardless of what hover state claims is currently displayed.
    tm = _hovering_fake_tm()
    assert tm.get_committed_theme() == COMMITTED
    assert tm.get_committed_theme() != HOVER


def test_get_committed_theme_matches_current_theme_name_when_not_hovering():
    tm = _FakeTM(current_theme_name=COMMITTED, is_hover_active=False)
    assert tm.get_committed_theme() == COMMITTED


# ── Cover-art theme mode (2026-08-05, live-reported: cover-art modes blocking/
# mistiming Esc/gutter-dismiss) ─────────────────────────────────────────────

def test_get_committed_theme_returns_the_cover_theme_dict_when_cover_art_active():
    # THE FIX. _on_theme_unhovered() targets self._cover_theme (a dict) whenever
    # self._cover_theme_active is True, exactly mirroring get_displayed_theme()'s
    # own existing check. get_committed_theme() must return the SAME value, or a
    # dict-vs-string comparison downstream (ThemeManager.
    # _theme_genuinely_settled_on_committed) can never see a genuine settle in
    # cover-art mode.
    cover_dict = {"bg_main": "#151F24", "accent": "#4A8FBA"}
    tm = _FakeTM(
        current_theme_name=COMMITTED,  # the underlying pool theme name, irrelevant here
        is_hover_active=False,
        cover_theme_active=True,
        cover_theme=cover_dict,
    )
    result = tm.get_committed_theme()
    assert result is cover_dict
    assert result != COMMITTED  # confirms this is NOT falling back to the bare string


def test_get_committed_theme_falls_back_to_current_theme_name_when_cover_theme_active_but_none():
    # Edge case named in get_displayed_theme()'s own equivalent check: _cover_theme_active
    # can theoretically be True with _cover_theme not yet populated (e.g. mid-transition).
    # Must fall back to the plain committed string, not return None.
    tm = _FakeTM(
        current_theme_name=COMMITTED,
        is_hover_active=False,
        cover_theme_active=True,
        cover_theme=None,
    )
    assert tm.get_committed_theme() == COMMITTED


def test_get_committed_theme_ignores_a_live_hover_even_in_cover_art_mode():
    # The hover-confinement guarantee must hold in BOTH modes: a hover currently
    # displaying something else (a swatch preview, say) must never leak into
    # get_committed_theme()'s answer, whether the underlying committed state is
    # a plain theme name or a cover-art dict.
    cover_dict = {"bg_main": "#151F24", "accent": "#4A8FBA"}
    tm = _FakeTM(
        current_theme_name=COMMITTED,
        is_hover_active=True,
        active_display_theme_internal=HOVER,  # a hovered swatch, unrelated to cover art
        cover_theme_active=True,
        cover_theme=cover_dict,
    )
    result = tm.get_committed_theme()
    assert result is cover_dict
    assert result != HOVER


# ── LibraryPanel._resolve_theme_colors ──────────────────────────────────────────────────────────

class _FakeLibraryParent:
    def __init__(self, theme_manager):
        self.theme_manager = theme_manager


class _FakeLibraryPanel:
    """Exercises the REAL _resolve_theme_colors logic (bound from LibraryPanel) against a fake
    parent exposing only theme_manager, mirroring the real method's own
    `self.parent() if hasattr(self.parent(), 'theme_manager') else self.window()` lookup."""
    from fabulor.ui.library import LibraryPanel
    _resolve_theme_colors = LibraryPanel._resolve_theme_colors

    def __init__(self, theme_manager):
        self._parent = _FakeLibraryParent(theme_manager)
        self._current_theme = None

    def parent(self):
        return self._parent

    def window(self):
        return self._parent


def test_library_resolve_theme_colors_ignores_a_live_hover():
    tm = _hovering_fake_tm()
    panel = _FakeLibraryPanel(tm)
    panel._resolve_theme_colors()
    assert panel._current_theme == themes._resolve_theme(COMMITTED)
    assert panel._current_theme != themes._resolve_theme(HOVER)


def test_library_resolve_theme_colors_matches_committed_when_not_hovering():
    tm = _FakeTM(current_theme_name=COMMITTED, is_hover_active=False)
    panel = _FakeLibraryPanel(tm)
    panel._resolve_theme_colors()
    assert panel._current_theme == themes._resolve_theme(COMMITTED)


# ── LibraryPanel._refresh_search_match_state ────────────────────────────────────────────────────

class _FakeSearchField:
    def __init__(self):
        self.stylesheet = None

    def text(self):
        return ""

    def setStyleSheet(self, sheet):
        self.stylesheet = sheet


class _FakeBookModel:
    filter_empty = True


class _FakeSearchLibraryPanel:
    from fabulor.ui.library import LibraryPanel
    _refresh_search_match_state = LibraryPanel._refresh_search_match_state

    def __init__(self, theme_manager):
        self._parent = _FakeLibraryParent(theme_manager)
        self._book_model = _FakeBookModel()
        self.search_field = _FakeSearchField()

    def parent(self):
        return self._parent


def test_library_refresh_search_match_state_ignores_a_live_hover():
    tm = _hovering_fake_tm()
    panel = _FakeSearchLibraryPanel(tm)
    panel._refresh_search_match_state()
    committed_error_color = themes._resolve_theme(COMMITTED).get('search_error_text', '#ffaaaa')
    hover_error_color = themes._resolve_theme(HOVER).get('search_error_text', '#ffaaaa')
    assert committed_error_color in panel.search_field.stylesheet
    if committed_error_color != hover_error_color:
        assert hover_error_color not in panel.search_field.stylesheet


# ── SpeedControls._apply_preset_ramp_colors ─────────────────────────────────────────────────────

class _FakeSpeedButton:
    def __init__(self):
        self.stylesheet = None

    def setStyleSheet(self, sheet):
        self.stylesheet = sheet


class _FakeSpeedControls:
    from fabulor.ui.speed_controls import SpeedControlsPanel
    _apply_preset_ramp_colors = SpeedControlsPanel._apply_preset_ramp_colors

    def __init__(self, theme_manager):
        self.theme_manager = theme_manager
        self._speed_presets = [1.0, 1.25, 1.5]
        self._speed_grid_buttons = [_FakeSpeedButton() for _ in self._speed_presets]


def test_speed_apply_preset_ramp_colors_ignores_a_live_hover():
    tm = _hovering_fake_tm()
    speed = _FakeSpeedControls(tm)
    speed._apply_preset_ramp_colors()
    committed_text = themes._resolve_theme(COMMITTED)
    committed_btn_text = committed_text.get('button_text', committed_text.get('text_on_light_bg', committed_text['text']))
    for btn in speed._speed_grid_buttons:
        assert f"color: {committed_btn_text}" in btn.stylesheet


# ── SleepTimerPanel._apply_preset_ramp_colors ───────────────────────────────────────────────────

class _FakeSleepButton:
    def __init__(self):
        self.stylesheet = None

    def setStyleSheet(self, sheet):
        self.stylesheet = sheet


class _FakeSleepTimer:
    from fabulor.ui.sleep_timer import SleepTimerPanel
    _apply_preset_ramp_colors = SleepTimerPanel._apply_preset_ramp_colors

    def __init__(self, theme_manager):
        self.theme_manager = theme_manager
        self._sleep_presets_buttons = [_FakeSleepButton() for _ in range(3)]


def test_sleep_apply_preset_ramp_colors_ignores_a_live_hover():
    tm = _hovering_fake_tm()
    sleep = _FakeSleepTimer(tm)
    sleep._apply_preset_ramp_colors()
    committed_text = themes._resolve_theme(COMMITTED)
    committed_btn_text = committed_text.get('button_text', committed_text.get('text_on_light_bg', committed_text['text']))
    for btn in sleep._sleep_presets_buttons:
        assert f"color: {committed_btn_text}" in btn.stylesheet


# ── app._reload_excluded_books ──────────────────────────────────────────────────────────────────

class _FakeThemedWidget:
    def __init__(self):
        self.theme = None
        self.expanded = None

    def set_theme(self, theme):
        self.theme = theme

    def set_expanded(self, expanded):
        self.expanded = expanded

    def set_count(self, n):
        pass

    def reload(self, books):
        pass

    @property
    def is_expandable(self):
        return False

    def set_expandable(self, v):
        pass


class _FakeDb:
    def get_excluded_books(self):
        return []


class _FakeMainWindowForExcluded:
    from fabulor.app import MainWindow
    _reload_excluded_books = MainWindow._reload_excluded_books

    def __init__(self, theme_manager):
        self.theme_manager = theme_manager
        self.excluded_books_section = _FakeThemedWidget()
        self.excluded_books_popup = _FakeThemedWidget()
        self.db = _FakeDb()
        # Skips the geometry-repositioning tail (real-widget-only, irrelevant
        # to this test's concern: only the theme-application half above it).
        self._library_tab_shown_once = False


def test_reload_excluded_books_ignores_a_live_hover():
    tm = _hovering_fake_tm()
    mw = _FakeMainWindowForExcluded(tm)
    mw._reload_excluded_books()
    assert mw.excluded_books_section.theme == themes._resolve_theme(COMMITTED)
    assert mw.excluded_books_popup.theme == themes._resolve_theme(COMMITTED)
    assert mw.excluded_books_section.theme != themes._resolve_theme(HOVER)
