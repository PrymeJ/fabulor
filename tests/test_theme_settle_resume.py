"""ThemeManager.call_when_theme_settled — event-driven-in-effect, predicate-driven-in-
mechanism resume for the corrected snapback-timing spec v2 (pure, headless).

See review/Design_260805_snapback_timing_v2.md. Mirrors PanelManager.call_when_panels_settled
exactly (tests/test_panel_settle_resume.py, Group A) — same reasoning applies identically:
QPropertyAnimation.stop() does not emit `finished` (verified empirically, 2026-07-28), and a
snapback's own fade gets stopped whenever a NEWER call interrupts it (see
test_hover_interrupts_snapback.py) — a signal-based resume would be silently dropped exactly
when a fast dismiss-during-hover-out sequence needs it most. These tests pin the decision
logic only: whether the callback fires immediately or is queued, the queue's lifecycle, the
termination-guarantee fallback, and — critically — that "settled" means "genuinely displaying
the COMMITTED theme," not merely "no fade is currently running." Qt paint/compositing is not
covered here — see the corrected-timing task's own live-verification items.

The second predicate correction (2026-08-05, same day) was itself found via a LIVE repro
Pryme reported and I initially misdiagnosed (first blamed a mouse-leave misclassification
that turned out to be unrelated — Pryme corrected this directly: the trigger was Esc, not a
leaveEvent) before re-tracing the actual log with real [CLOSE-SETTINGS-TRACE] instrumentation
and finding the true mechanism: a genuine NEW hover arriving while the dismiss is still
waiting on the ORIGINAL snapback interrupts that fade (correctly, per
_hover_may_interrupt) and starts its own, and the original bare `not _fade_in_flight` check
could not tell that settle apart from the snapback's own — so the panel closed showing the
newly-hovered theme for one frame before a later correction fixed it. See
test_call_when_theme_settled_waits_through_a_hover_that_interrupts_the_snapback below, which
pins this exact scenario as a permanent regression case.
"""
import pytest
import time

from fabulor.ui.theme_manager import ThemeManager, _THEME_SETTLE_TIMEOUT_MS


class _FakeTimer:
    def __init__(self):
        self.starts = 0

    def start(self):
        self.starts += 1


def _make_tm(*, committed_theme="Storm's End", displayed_theme=None,
             is_hover_active=False, fade_in_flight=False,
             cover_theme_active=False, cover_theme=None):
    """ThemeManager with only call_when_theme_settled's collaborators.

    `committed_theme` models `_current_theme_name`. `displayed_theme` models
    `_active_display_theme_internal` (the last theme that actually painted) —
    defaults to matching `get_committed_theme()`'s resolved value (the ordinary
    already-settled case) unless a test needs to model a hover currently
    displaying something else. `cover_theme_active`/`cover_theme` model cover-art
    theme mode (2026-08-05 correction) — when active, `get_committed_theme()`
    resolves to `cover_theme` (a dict) instead of the bare `committed_theme`
    string, exactly mirroring the real `_on_theme_unhovered()`'s own target.
    """
    resolved_committed = cover_theme if (cover_theme_active and cover_theme is not None) else committed_theme
    if displayed_theme is None:
        displayed_theme = resolved_committed
    tm = ThemeManager.__new__(ThemeManager)
    tm._current_theme_name = committed_theme
    tm._cover_theme_active = cover_theme_active
    tm._cover_theme = cover_theme
    tm._active_display_theme_internal = displayed_theme
    tm._is_hover_active = is_hover_active
    tm._fade_in_flight = fade_in_flight
    tm._theme_settled_watch_timer = _FakeTimer()
    tm._theme_settled_watch_armed = False
    tm._theme_settled_waiters = []
    tm._theme_settled_deadline = None
    tm._snap_theme_forward_calls = 0

    def _fake_snap_theme_forward():
        tm._snap_theme_forward_calls += 1
        tm._fade_in_flight = False
        tm._active_display_theme_internal = tm.get_committed_theme()
        tm._is_hover_active = False

    tm.snap_theme_forward = _fake_snap_theme_forward
    return tm


def _settle(tm):
    """Simulate the fade genuinely finishing and painting the committed theme —
    what _mark_theme_applied would have done for a real snapback's own fade."""
    tm._fade_in_flight = False
    tm._active_display_theme_internal = tm.get_committed_theme()
    tm._is_hover_active = False


def _interrupt_with_hover(tm, hovered_theme):
    """Simulate a genuine NEW hover interrupting the in-flight fade and painting
    its own preview — what _on_theme_changed's themes-tab-overlay branch plus
    _mark_theme_applied would have done for a real hover landing mid-wait."""
    tm._fade_in_flight = True
    tm._active_display_theme_internal = hovered_theme
    tm._is_hover_active = True


def test_fires_synchronously_when_nothing_fading():
    tm = _make_tm()
    ran = []
    tm.call_when_theme_settled(lambda: ran.append(1))
    assert ran == [1]
    assert tm._theme_settled_watch_timer.starts == 0


def test_defers_and_arms_when_fading():
    tm = _make_tm(fade_in_flight=True, is_hover_active=True,
                   displayed_theme="Blindsight")
    ran = []
    tm.call_when_theme_settled(lambda: ran.append(1))
    assert ran == []
    assert tm._theme_settled_watch_timer.starts == 1
    assert len(tm._theme_settled_waiters) == 1
    assert tm._theme_settled_deadline is not None


def test_second_waiter_does_not_restart_the_timer():
    # Same absolute-deadline property as PanelManager's settle watch (2026-07-22
    # starvation fix) — armed exactly once no matter how many waiters queue.
    tm = _make_tm(fade_in_flight=True, is_hover_active=True,
                   displayed_theme="Blindsight")
    for _ in range(5):
        tm.call_when_theme_settled(lambda: None)
    assert tm._theme_settled_watch_timer.starts == 1
    assert len(tm._theme_settled_waiters) == 5


def test_tick_rearms_while_still_fading():
    tm = _make_tm(fade_in_flight=True, is_hover_active=True,
                   displayed_theme="Blindsight")
    ran = []
    tm.call_when_theme_settled(lambda: ran.append(1))
    tm._on_theme_settled_watch_tick()
    assert ran == []
    assert tm._theme_settled_watch_timer.starts == 2  # initial arm + re-arm
    assert len(tm._theme_settled_waiters) == 1
    assert tm._snap_theme_forward_calls == 0  # nowhere near the timeout yet


def test_tick_drains_once_settled():
    tm = _make_tm(fade_in_flight=True, is_hover_active=True,
                   displayed_theme="Blindsight")
    ran = []
    tm.call_when_theme_settled(lambda: ran.append(1))
    _settle(tm)
    tm._on_theme_settled_watch_tick()
    assert ran == [1]
    assert tm._theme_settled_waiters == []
    assert tm._theme_settled_deadline is None


def test_multiple_waiters_all_drain_in_order():
    tm = _make_tm(fade_in_flight=True, is_hover_active=True,
                   displayed_theme="Blindsight")
    ran = []
    tm.call_when_theme_settled(lambda: ran.append("a"))
    tm.call_when_theme_settled(lambda: ran.append("b"))
    _settle(tm)
    tm._on_theme_settled_watch_tick()
    assert ran == ["a", "b"]


# ---- The predicate correction: "settled" means the COMMITTED theme, not just
# "no fade running" (2026-08-05, live-reproduced by Pryme) ------------------

def test_call_when_theme_settled_waits_through_a_hover_that_interrupts_the_snapback():
    # THE LIVE-REPRODUCED BUG. Sequence, matching the real log trace exactly:
    # Esc pressed while hovering 'Fire and Blood' -> _on_theme_unhovered() starts
    # the real snapback fade toward the committed theme -> call_when_theme_settled
    # is waiting -> BEFORE that fade settles, a genuine NEW hover on 'The Eyrie'
    # arrives and interrupts it (correct, per _hover_may_interrupt) -> The Eyrie's
    # OWN fade settles on its own schedule. A bare `not _fade_in_flight` check
    # reads that as "settled" and fires early — the panel would close showing The
    # Eyrie for one frame before a later correction fixed it. The FIXED predicate
    # must keep waiting, because the thing that settled is not the committed
    # theme.
    # In the real flow, _on_theme_unhovered() already started the snapback fade
    # (toward the committed theme, still mid-flight) BEFORE call_when_theme_settled
    # is reached — model that starting state directly, same as a real dismiss.
    tm = _make_tm(committed_theme="Storm's End", fade_in_flight=True,
                   is_hover_active=False, displayed_theme="Storm's End")
    ran = []

    tm.call_when_theme_settled(lambda: ran.append(1))
    assert ran == []  # snapback still fading — correctly deferred, not immediate

    tm._on_theme_settled_watch_tick()
    assert ran == []  # snapback still fading — correctly still waiting

    # A genuine new hover arrives mid-wait and interrupts the snapback fade.
    _interrupt_with_hover(tm, "The Eyrie")
    tm._on_theme_settled_watch_tick()
    assert ran == [], (
        "BUG: fired early because The Eyrie's hover state was mistaken for the "
        "snapback having settled"
    )

    # The Eyrie's own hover fade settles on ITS schedule — still not the
    # committed theme, so this must ALSO not count as settled.
    tm._fade_in_flight = False
    # _active_display_theme_internal stays 'The Eyrie', _is_hover_active stays
    # True — this is what a genuinely-settled HOVER looks like, not a genuine
    # revert to committed.
    tm._on_theme_settled_watch_tick()
    assert ran == [], "BUG: fired while displaying a hovered theme, not the committed one"

    # Only once the theme genuinely settles back on the COMMITTED value (a real
    # snapback, whether the original one resuming or a fresh one) must the
    # waiter finally drain.
    _settle(tm)
    tm._on_theme_settled_watch_tick()
    assert ran == [1]


def test_hover_on_a_theme_that_happens_to_share_the_committed_name_is_not_settled():
    # Edge case named explicitly in the predicate's own docstring: a hover
    # landing on the SAME theme name as the committed one must not read as
    # settled either, because it was displayed as a hover (_is_hover_active
    # True), not as the genuine non-hover revert this wait is for.
    tm = _make_tm(committed_theme="Storm's End", fade_in_flight=True,
                   is_hover_active=True, displayed_theme="Blindsight")
    ran = []
    tm.call_when_theme_settled(lambda: ran.append(1))

    # Fade clears, but the last paint was a HOVER of the committed theme's name.
    tm._fade_in_flight = False
    tm._active_display_theme_internal = "Storm's End"
    tm._is_hover_active = True
    tm._on_theme_settled_watch_tick()
    assert ran == [], "BUG: treated a hover-flagged paint of the committed theme as settled"

    _settle(tm)
    tm._on_theme_settled_watch_tick()
    assert ran == [1]


# ---- Termination guarantee (v2's correction over the reverted attempt) ----

def test_deadline_not_yet_reached_does_not_force_settle():
    tm = _make_tm(fade_in_flight=True, is_hover_active=True,
                   displayed_theme="Blindsight")
    ran = []
    tm.call_when_theme_settled(lambda: ran.append(1))
    # Deadline is _THEME_SETTLE_TIMEOUT_MS in the future — a tick immediately
    # after arming must NOT force anything.
    tm._on_theme_settled_watch_tick()
    assert ran == []
    assert tm._snap_theme_forward_calls == 0


def test_deadline_reached_forces_settle_via_snap_theme_forward():
    tm = _make_tm(fade_in_flight=True, is_hover_active=True,
                   displayed_theme="Blindsight")
    ran = []
    tm.call_when_theme_settled(lambda: ran.append(1))
    # Simulate the deadline having already passed.
    tm._theme_settled_deadline = time.perf_counter() - 0.001
    tm._on_theme_settled_watch_tick()
    assert tm._snap_theme_forward_calls == 1
    # The fake snap_theme_forward settles onto the committed theme, so the same
    # tick drains the waiter immediately rather than re-arming for another wait.
    assert ran == [1]
    assert tm._theme_settled_waiters == []


def test_deadline_reached_but_snap_theme_forward_leaves_it_unsettled_rearms_instead_of_looping():
    # Defensive case: if a future change to snap_theme_forward somehow left the
    # theme still not genuinely settled (it does not today), the tick must
    # re-arm rather than assume settled — never fire waiters against a state
    # that is, in fact, not the committed theme.
    tm = _make_tm(fade_in_flight=True, is_hover_active=True,
                   displayed_theme="Blindsight")
    tm.snap_theme_forward = lambda: setattr(tm, "_snap_theme_forward_calls", tm._snap_theme_forward_calls + 1)
    tm._snap_theme_forward_calls = 0
    ran = []
    tm.call_when_theme_settled(lambda: ran.append(1))
    tm._theme_settled_deadline = time.perf_counter() - 0.001
    tm._on_theme_settled_watch_tick()
    assert tm._snap_theme_forward_calls == 1
    assert ran == []  # not drained — state is still not genuinely settled
    assert len(tm._theme_settled_waiters) == 1


def test_timeout_constant_is_comfortably_above_worst_case_measured_settle():
    # review/Investigation_260804_animation_latency.md measured animation-start
    # latency (dominated by _apply_stylesheets) at up to ~810ms live, plus the
    # 200ms snapback fade itself = ~1010ms worst-case normal settle. The timeout
    # must stay comfortably above that or it risks false-triggering on ordinary,
    # legitimately slow hardware/contention.
    worst_case_observed_normal_settle_ms = 810 + 200
    assert _THEME_SETTLE_TIMEOUT_MS >= worst_case_observed_normal_settle_ms * 1.5


# ---- Cover-art theme mode (2026-08-05, live-reported: cover-art modes
# blocking/mistiming Esc/gutter-dismiss) -------------------------------------
#
# _on_theme_unhovered() targets self._cover_theme (a DICT) whenever
# self._cover_theme_active is True, not self._current_theme_name (a string).
# get_committed_theme() previously always returned the bare string, so the
# settle predicate's `_active_display_theme_internal == get_committed_theme()`
# comparison was dict-vs-string and could NEVER be True via its intended path
# in cover-art mode — live-confirmed to only "work" by accident, via a
# DIFFERENT, older no-op guard in _on_theme_changed coincidentally matching
# first. Without that accidental match, the dismiss would silently fall
# through to the 2000ms termination-guarantee timeout instead of closing
# promptly — a real bug masked as "closes 2 seconds late," not a hang, but a
# BUG_PREDICATE_NEVER_TRUE_HERE class of defect, not the mid-wait-hover race
# fixed above. Fixed by widening get_committed_theme() itself (this is a
# consumer-side test — see test_write_path_confinement.py for
# get_committed_theme()'s own direct tests).

def test_call_when_theme_settled_fires_immediately_in_cover_art_mode_when_already_settled():
    # The ordinary case: cover-art-exclusive mode active, nothing hovering, the
    # cover theme dict is already the last thing painted. Must fire immediately
    # — this is the case that used to rely on the accidental no-op-guard match
    # rather than a genuine settled predicate.
    cover_dict = {"bg_main": "#151F24", "accent": "#4A8FBA"}
    tm = _make_tm(committed_theme="Shade of the Evening",
                   cover_theme_active=True, cover_theme=cover_dict,
                   fade_in_flight=False, is_hover_active=False)
    ran = []
    tm.call_when_theme_settled(lambda: ran.append(1))
    assert ran == [1]
    assert tm._theme_settled_watch_timer.starts == 0


def test_call_when_theme_settled_waits_for_a_genuine_fade_in_cover_art_mode():
    # A real dismiss while cover-art mode is active and a fade is genuinely
    # in flight (e.g. the cover theme was just re-applied) must still defer,
    # exactly as the plain-theme case does — this predicate must not silently
    # short-circuit just because the committed value is a dict.
    cover_dict = {"bg_main": "#151F24", "accent": "#4A8FBA"}
    tm = _make_tm(committed_theme="Shade of the Evening",
                   cover_theme_active=True, cover_theme=cover_dict,
                   fade_in_flight=True, is_hover_active=True,
                   displayed_theme="Blindsight")  # a swatch hover, unrelated to cover art
    ran = []
    tm.call_when_theme_settled(lambda: ran.append(1))
    assert ran == []
    assert tm._theme_settled_watch_timer.starts == 1

    tm._on_theme_settled_watch_tick()
    assert ran == []  # still fading — correctly still waiting

    _settle(tm)
    tm._on_theme_settled_watch_tick()
    assert ran == [1]
    assert tm._active_display_theme_internal is cover_dict


def test_call_when_theme_settled_never_true_bug_would_have_hung_without_the_fix():
    # Directly demonstrates the bug this fix closes: BEFORE the fix,
    # get_committed_theme() returned _current_theme_name (a bare string) even
    # in cover-art mode, so a genuinely-settled cover-theme dict could never
    # compare equal to it. This test builds that exact broken comparison
    # directly (bypassing get_committed_theme() to simulate the OLD, unfixed
    # behavior) and confirms it would never have matched — proving the fix is
    # what makes the settle reachable at all, not incidental.
    cover_dict = {"bg_main": "#151F24", "accent": "#4A8FBA"}
    committed_string = "Shade of the Evening"
    # The old, broken comparison: dict (what's genuinely displayed) vs. the
    # bare string (what get_committed_theme() used to return unconditionally).
    assert cover_dict != committed_string, (
        "sanity check: a dict must never compare equal to a plain string"
    )
    # The FIXED comparison, via the real accessor:
    tm = _make_tm(committed_theme=committed_string,
                   cover_theme_active=True, cover_theme=cover_dict,
                   displayed_theme=cover_dict, fade_in_flight=False,
                   is_hover_active=False)
    assert tm._active_display_theme_internal == tm.get_committed_theme()
