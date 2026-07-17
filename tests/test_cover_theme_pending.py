"""Behavior contract for the Direction-2 deferred cover-theme apply
(`MainWindow._apply_pending_cover_theme` / `_apply_main_cover`'s stand-down).

Root cause + design: see plans/Findings_260714_coldlaunch_fix_interactions.md and
plans/Plan_260714_surgical_coldlaunch_theme_fix.md. The cover-theme apply on cold-launch
and book-switch is deferred to the end of `_on_file_ready` (after `defer_vt_restore` —
Race 3 — and after the flow animation starts — Regime B). Two behaviors are pinned here:

1. The pending flag stays TRUE across the `when_animations_done` wait window, cleared only
   when the apply actually runs — so a post-scan cover reload firing DURING the wait sees a
   pending apply and stands down (the Regime-B regression was the flag being cleared too
   early, letting the reload apply mid-flow).
2. The deferred apply re-resolves the cover from the DB at apply time (does NOT carry a
   stash-time pixmap), and applies even when no flow animation is running (the
   `new_val is None` duration-race branch — a cover-present book still gets themed, no
   silent "never themed" failure).

MainWindow needs mpv + DB + the full widget tree, so — following
tests/test_vt_file_switched_guard.py — these bind the REAL unbound methods to tiny fakes
supplying exactly the collaborators they touch.
"""
from fabulor.app import MainWindow


class _FakeSlider:
    """A slider whose when_animations_done fires the callback only when told to —
    lets the test control the 'wait window' precisely."""
    def __init__(self):
        self._cb = None
        self.running = False

    def when_animations_done(self, cb):
        if self.running:
            self._cb = cb          # hold until finish() is called
        else:
            cb()                   # nothing animating -> fire immediately

    def finish(self):
        self.running = False
        cb, self._cb = self._cb, None
        if cb:
            cb()


class _FakeThemeManager:
    def __init__(self):
        self.applied = []          # list of source_keys applied

    def apply_cover_theme(self, pixmap, source_key=None):
        self.applied.append(source_key)


class _FakeMW:
    def __init__(self, *, progress_running, chapter_running, resolved):
        self.current_file = "/book/A"
        self._cover_theme_apply_pending = True
        self._cover_apply_wait_inflight = False
        self.progress_slider = _FakeSlider()
        self.progress_slider.running = progress_running
        self.chapter_progress_slider = _FakeSlider()
        self.chapter_progress_slider.running = chapter_running
        self.theme_manager = _FakeThemeManager()
        self._resolved = resolved   # (pixmap, source_key) returned by _resolve_cover_source

    # bind the real methods
    _apply_pending_cover_theme = MainWindow._apply_pending_cover_theme

    def _resolve_cover_source(self, file_path):
        return self._resolved

    # stand-down branch of _apply_main_cover, isolated to its flag logic
    def _immediate_or_standdown(self):
        """Mirror _apply_main_cover's immediate/stand-down decision for the
        no-panel, not-startup caller (the post-scan reload)."""
        if getattr(self, '_cover_theme_apply_pending', False):
            return "standdown"
        return "apply"


def test_no_animation_running_applies_immediately():
    """new_val is None branch: no flow animation, pending flag set — the cover
    still themes (no silent 'never themed'), and the flag clears."""
    pm = object()
    mw = _FakeMW(progress_running=False, chapter_running=False,
                 resolved=(pm, ("/book/A", "active", "/c.jpg")))
    mw._apply_pending_cover_theme()
    assert mw.theme_manager.applied == [("/book/A", "active", "/c.jpg")]
    assert mw._cover_theme_apply_pending is False
    assert mw._cover_apply_wait_inflight is False


def test_flag_stays_true_across_wait_then_clears_on_apply():
    """The regression fix: pending flag must stay True while the slider wait is in
    flight (so a post-scan reload stands down), and clear only when apply runs."""
    pm = object()
    mw = _FakeMW(progress_running=True, chapter_running=False,
                 resolved=(pm, ("/book/A", "active", "/c.jpg")))
    mw._apply_pending_cover_theme()
    # Wait in flight: nothing applied yet, and the flag is STILL True.
    assert mw.theme_manager.applied == []
    assert mw._cover_theme_apply_pending is True
    assert mw._cover_apply_wait_inflight is True
    # A post-scan reload arriving now must stand down.
    assert mw._immediate_or_standdown() == "standdown"
    # Animation finishes -> apply runs, flag clears.
    mw.progress_slider.finish()
    assert mw.theme_manager.applied == [("/book/A", "active", "/c.jpg")]
    assert mw._cover_theme_apply_pending is False
    assert mw._cover_apply_wait_inflight is False


def test_reentrancy_guard_no_double_wait():
    """Calling _apply_pending_cover_theme twice while a wait is in flight must not
    register a second wait or double-apply."""
    pm = object()
    mw = _FakeMW(progress_running=True, chapter_running=False,
                 resolved=(pm, ("/book/A", "active", "/c.jpg")))
    mw._apply_pending_cover_theme()
    mw._apply_pending_cover_theme()   # second call -> re-entrancy guard returns early
    mw.progress_slider.finish()
    assert mw.theme_manager.applied == [("/book/A", "active", "/c.jpg")]  # applied once


def test_rapid_switch_stale_callback_does_not_apply_or_clear_new_pending():
    """If the current book changes while an apply is waiting, the stale callback must
    NOT apply the old book's cover and must NOT clear the new book's pending flag."""
    pm = object()
    mw = _FakeMW(progress_running=True, chapter_running=False,
                 resolved=(pm, ("/book/A", "active", "/a.jpg")))
    mw._apply_pending_cover_theme()          # waiting on book A
    # User switches to book B while A's apply is still waiting.
    mw.current_file = "/book/B"
    mw._cover_theme_apply_pending = True      # B set its own pending flag
    mw._resolved = (pm, ("/book/B", "active", "/b.jpg"))  # DB now resolves B
    mw.progress_slider.finish()               # A's stale callback fires
    # A's cover must NOT have been applied; B's apply should have re-triggered and,
    # with no animation now running on the fresh (already-finished) slider, applied B.
    assert ("/book/A", "active", "/a.jpg") not in mw.theme_manager.applied
    assert mw.theme_manager.applied == [("/book/B", "active", "/b.jpg")]
    assert mw._cover_theme_apply_pending is False
