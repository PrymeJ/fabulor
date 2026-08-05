"""get_current_theme()/get_active_theme() hover-confinement (pure, headless).

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

`clear_stale_hover_state()` — a same-day bookkeeping-correction backstop for this exact
gap — was DELETED 2026-08-05 (step 6 of review/Design_260804_hover_state_computed_read_
path.md), once `get_displayed_theme()` made it structurally unreachable: that method
never reads `_is_hover_active`/`_active_display_theme_internal` at all, so there is no
longer any stored value for a "clear the stale value" method to correct. Re-confirmed
safe against current code (not just the original design's snapshot) before deletion —
see review/Design_260805_snapback_timing_v2.md's step 2 for the full re-verification,
including that the Esc/gutter-dismiss path is self-healing regardless of whether
`[SWATCH-LEAVE-SUSPECT]`'s still-open gap fires, since `_close_settings_flow`
unconditionally calls `_on_theme_unhovered()` before `_on_settings_hidden` can ever run.
Its own tests were removed in the same change; this file now covers only
`get_current_theme()`/`get_active_theme()`'s own hover-safety, which is unaffected by
that deletion.
"""
import pytest

from fabulor.ui.theme_manager import ThemeManager
from fabulor import themes


class _FakeTM:
    """Minimal stand-in exposing exactly what get_current_theme()/get_active_theme()
    touch. get_active_theme is bound to the REAL unbound ThemeManager method (not
    re-faked) since it is the exact production code get_current_theme() calls through
    -- this test is about THAT method's own logic, not about re-verifying its
    dependencies.

    get_displayed_theme is faked here (2026-08-04, step 2 of the hover-state
    migration): get_active_theme() now shadow-checks against it, but this test
    file is about get_active_theme()/get_current_theme()'s OWN pre-existing
    logic, not get_displayed_theme()'s (that has its own dedicated test file).
    Standing up real Qt widgets (settings_panel/tabs/swatch_box) here would
    test the wrong thing -- the fake simply mirrors whatever the old path is
    about to compute, so the shadow check always agrees and never distracts
    from what this file actually verifies."""

    get_active_theme = ThemeManager.get_active_theme

    def __init__(self, active_display_theme_internal, current_theme_name,
                 is_hover_active, cover_theme_active=False, cover_theme=None):
        self._active_display_theme_internal = active_display_theme_internal
        self._current_theme_name = current_theme_name
        self._is_hover_active = is_hover_active
        self._cover_theme_active = cover_theme_active
        self._cover_theme = cover_theme

    def get_displayed_theme(self):
        # Mirror exactly what get_active_theme()'s OLD path computes, so the
        # shadow check added in get_active_theme() always agrees in this test
        # file and never logs a spurious [SHADOW-CHECK] warning during tests.
        if self._is_hover_active:
            if self._cover_theme_active and self._cover_theme is not None:
                return self._cover_theme
            return self._current_theme_name
        return self._active_display_theme_internal or self._current_theme_name


def _get_current_theme(fake):
    return ThemeManager.get_current_theme(fake)


def _get_active_theme(fake):
    return ThemeManager.get_active_theme(fake)


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
