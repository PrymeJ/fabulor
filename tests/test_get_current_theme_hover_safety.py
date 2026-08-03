"""get_current_theme()/clear_stale_hover_state hover-confinement fix (pure, headless).

2026-08-03 confinement-gap fix: get_current_theme() previously read
_active_display_theme_internal directly with no hover check, so it could return a
hover-preview-only theme to any external caller for as long as _is_hover_active stayed
True — including indefinitely, if a hover completed and the swatch's leaveEvent was
then classified as a blur-grab synthetic (fires while hidden by a panel transition)
rather than a genuine mouse-out, since in that case _on_theme_unhovered() never runs to
correct it. Seven runtime call sites were confirmed leaking this way (Library's
per-cover delegate colors and search-error color, the panel-backdrop frost wash,
Sleep/Speed panel preset-ramp colors, the Excluded Books popup, the Speed
right-click shimmer). See review/Investigation_260803_settings_open_hover_preview_
inconsistency.md and the design doc that followed it.

Fix: get_current_theme() now resolves through get_active_theme() (the existing,
already-hover-safe accessor built 2026-07-20 for the same class of bug, see
review/Review_260720_theme_reach.md) instead of reading the raw internal field.
clear_stale_hover_state() additionally corrects the underlying bookkeeping
(_is_hover_active/_active_display_theme_internal) whenever Settings becomes hidden,
regardless of how the close happened, via PanelManager._on_settings_hidden — the sole
settings_panel.hide() call site anywhere in the codebase (confirmed by grep).
"""
import pytest

from fabulor.ui.theme_manager import ThemeManager
from fabulor import themes


class _FakeTimer:
    def __init__(self):
        self.running = False

    def start(self):
        self.running = True

    def stop(self):
        self.running = False


class _FakeMainWindow:
    """Stand-in exposing exactly what clear_stale_hover_state's repaint call
    touches: _refresh_panel_visuals, the bound entry point
    SettingsController.sync_all_settings_visuals uses in the real app."""

    def __init__(self):
        self.refresh_calls = []

    def _refresh_panel_visuals(self, theme_name):
        self.refresh_calls.append(theme_name)


class _FakeTM:
    """Minimal stand-in exposing exactly what get_current_theme()/get_active_theme()/
    _mark_theme_applied()/clear_stale_hover_state() touch. get_active_theme and
    _mark_theme_applied are bound to the REAL unbound ThemeManager methods (not
    re-faked) since they are the exact production code get_current_theme() and
    clear_stale_hover_state() call through -- this test is about THOSE two methods'
    own logic, not about re-verifying their dependencies.

    get_displayed_theme is faked here (2026-08-04, step 2 of the hover-state
    migration): get_active_theme() now shadow-checks against it, but this test
    file is about get_active_theme()/get_current_theme()'s OWN pre-existing
    logic, not get_displayed_theme()'s (that has its own dedicated test file).
    Standing up real Qt widgets (settings_panel/tabs/swatch_box) here would
    test the wrong thing -- the fake simply mirrors whatever the old path is
    about to compute, so the shadow check always agrees and never distracts
    from what this file actually verifies."""

    get_active_theme = ThemeManager.get_active_theme
    _mark_theme_applied = ThemeManager._mark_theme_applied

    def __init__(self, active_display_theme_internal, current_theme_name,
                 is_hover_active, cover_theme_active=False, cover_theme=None):
        self._active_display_theme_internal = active_display_theme_internal
        self._current_theme_name = current_theme_name
        self._is_hover_active = is_hover_active
        self._cover_theme_active = cover_theme_active
        self._cover_theme = cover_theme
        self._swatch_leave_backstop_timer = _FakeTimer()
        self.main_window = _FakeMainWindow()
        self.apply_stylesheets_calls = []

    def get_displayed_theme(self):
        # Mirror exactly what get_active_theme()'s OLD path computes, so the
        # shadow check added in get_active_theme() always agrees in this test
        # file and never logs a spurious [SHADOW-CHECK] warning during tests.
        if self._is_hover_active:
            if self._cover_theme_active and self._cover_theme is not None:
                return self._cover_theme
            return self._current_theme_name
        return self._active_display_theme_internal or self._current_theme_name

    def _apply_stylesheets(self, theme_name, hover=False, force_all_panels=False):
        # Stand-in for the real (heavy, Qt-widget-touching) _apply_stylesheets --
        # this test is about clear_stale_hover_state's OWN call sequence/logic,
        # not about re-verifying _apply_stylesheets itself.
        self.apply_stylesheets_calls.append((theme_name, hover))


def _get_current_theme(fake):
    return ThemeManager.get_current_theme(fake)


def _get_active_theme(fake):
    return ThemeManager.get_active_theme(fake)


def _clear_stale_hover_state(fake):
    return ThemeManager.clear_stale_hover_state(fake)


ACTIVE = "Fire and Blood"
HOVER = "Alzabo"  # customizes button_speed_shimmer -- a genuinely discriminating theme


def test_get_current_theme_returns_active_theme_while_hover_is_stuck():
    # THE CORE FIX. Before 2026-08-03 this read _active_display_theme_internal
    # (the HOVER theme name) directly with no hover check at all.
    fake = _FakeTM(active_display_theme_internal=HOVER, current_theme_name=ACTIVE,
                   is_hover_active=True)
    result = _get_current_theme(fake)
    expected = themes._resolve_theme(ACTIVE)
    assert result == expected
    # And explicitly NOT the hover theme -- the exact regression this pins.
    assert result != themes._resolve_theme(HOVER)


def test_get_current_theme_matches_get_active_theme_resolved_in_non_hover_case():
    # Regression check: the redefinition must not change behavior for the
    # overwhelming majority of calls, where nothing is stuck.
    fake = _FakeTM(active_display_theme_internal=ACTIVE, current_theme_name=ACTIVE,
                   is_hover_active=False)
    assert _get_current_theme(fake) == themes._resolve_theme(_get_active_theme(fake))
    assert _get_current_theme(fake) == themes._resolve_theme(ACTIVE)


def test_get_current_theme_respects_live_cover_theme_while_hovering():
    # get_active_theme()'s own documented behavior: while hovering, return the
    # cover theme (if one is active) rather than _current_theme_name. Confirm
    # get_current_theme() inherits this correctly through the resolve step.
    cover_dict = {"bg_main": "#123456", "accent": "#abcdef"}
    fake = _FakeTM(active_display_theme_internal=HOVER, current_theme_name=ACTIVE,
                   is_hover_active=True, cover_theme_active=True, cover_theme=cover_dict)
    result = _get_current_theme(fake)
    assert result["bg_main"] == "#123456"


def test_clear_stale_hover_state_corrects_fields_and_stops_backstop_timer():
    fake = _FakeTM(active_display_theme_internal=HOVER, current_theme_name=ACTIVE,
                   is_hover_active=True)
    fake._swatch_leave_backstop_timer.running = True  # armed, as _mark_theme_applied would have

    _clear_stale_hover_state(fake)

    assert fake._is_hover_active is False
    assert fake._active_display_theme_internal == ACTIVE
    assert fake._swatch_leave_backstop_timer.running is False


def test_clear_stale_hover_state_repaints_sleep_speed_ramps_when_correcting():
    # 2026-08-03, live-reported regression in the FIRST version of this fix:
    # bookkeeping alone does not repaint Sleep/Speed's preset-ramp buttons --
    # they only redraw on their own state-change methods or the theme-apply
    # TAIL, neither of which a plain field correction triggers. Confirms the
    # fix now also re-triggers that TAIL (main_window._refresh_panel_visuals)
    # so an already-painted-wrong ramp gets corrected, not just future reads.
    fake = _FakeTM(active_display_theme_internal=HOVER, current_theme_name=ACTIVE,
                   is_hover_active=True)

    _clear_stale_hover_state(fake)

    assert fake.main_window.refresh_calls == [ACTIVE]


def test_clear_stale_hover_state_repaints_the_main_window_when_correcting():
    # 2026-08-03, SECOND live-reported regression: the ramp fix above still left
    # mw.setStyleSheet(...) itself uncorrected, since that only happens inside
    # _apply_stylesheets, which the first fix never called. Confirms the second
    # correction actually calls it, with the real active theme and hover=False
    # (so its own internal `if not hover:` branch also schedules the deferred
    # Library/Stats/Tags/Book-Detail restyle, not just the fast-path surfaces).
    fake = _FakeTM(active_display_theme_internal=HOVER, current_theme_name=ACTIVE,
                   is_hover_active=True)

    _clear_stale_hover_state(fake)

    assert fake.apply_stylesheets_calls == [(ACTIVE, False)]


def test_clear_stale_hover_state_is_a_no_op_when_hover_is_not_active():
    fake = _FakeTM(active_display_theme_internal=ACTIVE, current_theme_name=ACTIVE,
                   is_hover_active=False)
    fake._swatch_leave_backstop_timer.running = False

    _clear_stale_hover_state(fake)

    assert fake._is_hover_active is False
    assert fake.main_window.refresh_calls == []  # no-op means no repaint either
    assert fake.apply_stylesheets_calls == []  # no-op means no main-window repaint either
    assert fake._active_display_theme_internal == ACTIVE
    assert fake._swatch_leave_backstop_timer.running is False
