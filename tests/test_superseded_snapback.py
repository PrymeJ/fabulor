"""_on_fade_finished's stash-drain decision: a snapback superseded by a live hover
preview must be discarded, not replayed.

The bug this pins (found live 2026-07-27 from a DEBUG [BLEED-TRACE]/[ENTEREVENT-TRACE]
capture, full sequence in NOTES.md): leaving the swatch area while a fade is in flight
stashes a snapback into _pending_fade_call (_on_theme_unhovered ->
_on_theme_changed(hover=False) -> the _fade_running branch). If the cursor then
re-enters and settles on a swatch before that fade finishes, the debounce fires a
genuine preview and APPLIES it — and then this drain replayed the now-obsolete
snapback on top, reverting to the active theme while the mouse sat perfectly still.
Measured in the captured repro: preview applied at t=01,265, stale snapback applied at
t=02,042 (~775ms later). The drain's own trace line already recorded
_is_hover_active=True at that moment; the site simply never looked.

This is the mirror image of the pre-existing hover-confinement discard (pending[3]):
that one drops a stashed HOVER because by drain time the user moved on; this one drops
a stashed SNAPBACK because by drain time the user moved back on.

Follows tests/test_deferred_restyle.py: binds the REAL unbound method to a minimal fake
supplying only the collaborators it touches, so no QApplication or widget tree is needed.
"""
import pytest

from fabulor.ui.theme_manager import ThemeManager


class _FakeOverlay:
    def hide(self):
        pass


class _FakeThemeManager:
    """Minimal stand-in exposing exactly what _on_fade_finished touches."""

    def __init__(self, pending, is_hover_active, pending_hover_theme=None,
                 active_display_theme="SomeTheme"):
        self._pending_fade_call = pending
        self._is_hover_active = is_hover_active
        self._pending_hover_theme = pending_hover_theme
        self._active_display_theme_internal = active_display_theme
        self._fade_in_flight = True
        self._fade_overlay = _FakeOverlay()
        self._save_on_fade = False
        # Spy: every _on_theme_changed replay the drain performs.
        self.replayed = []

    # -- collaborators the real method calls --------------------------------
    def _unfreeze_fade_labels(self):
        pass

    def _run_deferred_restyle(self):
        pass

    def _on_theme_changed(self, *args):
        self.replayed.append(args)


def _drain(fake):
    """Run the REAL _on_fade_finished against the fake."""
    ThemeManager._on_fade_finished(fake)


# A stashed snapback: hover=False, bypass_panel_open_guard=True — the exact 6-tuple
# shape _on_theme_unhovered produces (see the captured repro's
# ('Phlegethon', False, 200, False, True, True)).
_SNAPBACK = ("Phlegethon", False, 200, False, True, True)
_HOVER_CALL = ("Eyes of Ibad", False, 200, True, True, False)


def test_superseded_snapback_is_discarded():
    # THE BUG: a hover preview was genuinely applied while the snapback sat stashed.
    # Replaying it would cancel that preview with the cursor still resting on the swatch.
    fake = _FakeThemeManager(_SNAPBACK, is_hover_active=True,
                             active_display_theme="Eyes of Ibad")
    _drain(fake)
    assert fake.replayed == []
    # The stash must still be consumed, not left to fire later.
    assert fake._pending_fade_call is None


def test_snapback_replays_when_no_hover_is_active():
    # The normal case this drain exists for: user left and did NOT come back, so the
    # snapback is still the correct final state and must be applied.
    fake = _FakeThemeManager(_SNAPBACK, is_hover_active=False)
    _drain(fake)
    assert fake.replayed == [_SNAPBACK]


def test_snapback_replays_when_a_hover_is_only_queued_not_applied():
    # _is_hover_active True but a NEWER hover is still mid-debounce: the preview that
    # set the flag is about to be superseded anyway, so the snapback is not yet known
    # to be obsolete. Requiring _pending_hover_theme is None keeps the discard scoped
    # to a preview that is genuinely applied AND settled.
    fake = _FakeThemeManager(_SNAPBACK, is_hover_active=True,
                             pending_hover_theme="Turquoise Days")
    _drain(fake)
    assert fake.replayed == [_SNAPBACK]


def test_hover_flagged_stash_is_still_discarded():
    # Pre-existing confinement behaviour (pending[3]) must survive this change —
    # an abandoned preview is never replayed, regardless of hover state.
    fake = _FakeThemeManager(_HOVER_CALL, is_hover_active=False)
    _drain(fake)
    assert fake.replayed == []


def test_hover_flagged_stash_discarded_even_while_hover_active():
    # Both discard conditions true at once: the hover-confinement branch owns it.
    fake = _FakeThemeManager(_HOVER_CALL, is_hover_active=True)
    _drain(fake)
    assert fake.replayed == []


def test_nothing_pending_is_a_noop():
    fake = _FakeThemeManager(None, is_hover_active=True)
    _drain(fake)
    assert fake.replayed == []


def test_drain_always_clears_fade_in_flight():
    # Guard against a regression where an early-return skips the flag clear and
    # strands every subsequent theme change in the _fade_running stash branch.
    for pending, hover_active in [
        (_SNAPBACK, True),
        (_SNAPBACK, False),
        (_HOVER_CALL, True),
        (None, False),
    ]:
        fake = _FakeThemeManager(pending, is_hover_active=hover_active)
        _drain(fake)
        assert fake._fade_in_flight is False
