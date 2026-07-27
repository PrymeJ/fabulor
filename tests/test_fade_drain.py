"""_on_fade_finished's stash-drain decision, post-048ae3a-revert (pure, headless).

Carries over the two still-valid tests from the deleted tests/test_superseded_snapback.py
(the hover-confinement pin and the flag-clear invariant) and adds the direct pin for the
reverted guard.

The reverted guard (048ae3a) discarded a stashed snapback when
`_is_hover_active and _pending_hover_theme is None`. That was wrong: `_is_hover_active`
means "the last APPLIED theme was a preview", NOT "a hover is live now". After a genuine
mouse-out it stays True (only an apply clears it, and a discarded snapback never
applies), so the guard ate legitimate snapbacks and stranded the UI on a preview —
live-confirmed 3x on 2026-07-28, each following a real `leaveEvent vis=True`.

`test_snapback_is_replayed_in_the_state_the_reverted_guard_discarded` is the regression
pin: it asserts the drain now REPLAYS in exactly the state that guard discarded.

Tests 2-3 pin the post-clear guarantee — that clearing `_pending_fade_call` at the
interrupt site cannot become a third way to strand the UI on a preview. See also the
CLAUDE.md rule on dismiss-path ordering, which is what makes this safe and which no
assertion here can enforce.
"""
import pytest

from fabulor.ui.theme_manager import ThemeManager


class _FakeOverlay:
    def hide(self):
        pass


class _FakeTM:
    """Minimal stand-in exposing exactly what _on_fade_finished touches."""

    def __init__(self, pending, is_hover_active=False, pending_hover_theme=None):
        self._pending_fade_call = pending
        self._is_hover_active = is_hover_active
        self._pending_hover_theme = pending_hover_theme
        self._active_display_theme_internal = "Active"
        self._fade_in_flight = True
        self._fade_is_selection = True
        self._fade_overlay = _FakeOverlay()
        self._save_on_fade = False
        self.replayed = []

    def _unfreeze_fade_labels(self):
        pass

    def _run_deferred_restyle(self):
        pass

    def _on_theme_changed(self, *args):
        self.replayed.append(args)


def _drain(fake):
    ThemeManager._on_fade_finished(fake)


# _on_theme_unhovered's exact 6-tuple shape (hover=False, bypass=True).
_SNAPBACK = ("Not the Only Fruit", False, 200, False, True, True)
_HOVER_CALL = ("Eyes of Ibad", False, 375, True, True, False)


def test_snapback_is_replayed_in_the_state_the_reverted_guard_discarded():
    # THE REGRESSION PIN. _is_hover_active True + _pending_hover_theme None is exactly
    # what 048ae3a treated as "a live preview is showing, protect it" — but it is also
    # the state left behind by a GENUINE mouse-out, because only an apply clears the
    # flag. The snapback must be replayed, or the UI strands on the preview.
    fake = _FakeTM(_SNAPBACK, is_hover_active=True, pending_hover_theme=None)
    _drain(fake)
    assert fake.replayed == [_SNAPBACK]


def test_snapback_is_replayed_when_no_hover_is_active():
    fake = _FakeTM(_SNAPBACK, is_hover_active=False)
    _drain(fake)
    assert fake.replayed == [_SNAPBACK]


def test_hover_flagged_stash_is_still_discarded():
    # Pre-existing 2026-07-21 confinement rule — an abandoned preview is never replayed.
    # This is the panel-dismiss protection the user explicitly requires not to regress.
    fake = _FakeTM(_HOVER_CALL, is_hover_active=False)
    _drain(fake)
    assert fake.replayed == []


def test_hover_flagged_stash_discarded_even_while_hover_active():
    fake = _FakeTM(_HOVER_CALL, is_hover_active=True)
    _drain(fake)
    assert fake.replayed == []


def test_nothing_pending_is_a_noop():
    fake = _FakeTM(None, is_hover_active=True)
    _drain(fake)
    assert fake.replayed == []


@pytest.mark.parametrize("pending,hover_active", [
    (_SNAPBACK, True),
    (_SNAPBACK, False),
    (_HOVER_CALL, True),
    (None, False),
])
def test_drain_always_clears_fade_flags(pending, hover_active):
    # An early-return that skipped the clear would strand every subsequent theme change
    # in the _fade_running stash branch. _fade_is_selection must clear alongside
    # _fade_in_flight — a stale True would wrongly protect the NEXT fade from a hover.
    fake = _FakeTM(pending, is_hover_active=hover_active)
    _drain(fake)
    assert fake._fade_in_flight is False
    assert fake._fade_is_selection is False


def test_stash_is_consumed_on_every_path():
    # Whether replayed or discarded, the stash must not survive the drain.
    for pending in (_SNAPBACK, _HOVER_CALL):
        fake = _FakeTM(pending, is_hover_active=True)
        _drain(fake)
        assert fake._pending_fade_call is None
