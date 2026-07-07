"""Truth table for PanelManager.is_overlay_open_or_committed — the single gate that
enforces 'one overlay open at a time' (drop the second open request).

The predicate is a pure boolean composition of three inputs:
  is_any_full_panel_visible()  — any full overlay present or mid-animation (panels are
                                 shown at slide start, hidden only when the close-slide
                                 finishes, so this is True for the whole lifecycle)
  is_any_panel_animating()     — any panel/sidebar slide running (covers the sidebar)
  _pending_panel_open          — a sidebar-handoff open committed but not shown yet

Standing up a real PanelManager needs the whole MainWindow, so these tests bind the
REAL unbound method to a tiny fake that supplies those three inputs — pinning the
composition (including the load-bearing 'a bare expanded sidebar is NOT blocked' case)
without the app. The end-to-end drop behavior is animation/timing-heavy and is verified
live, per the project rule that live timing behavior is ground truth.
"""
import pytest

from fabulor.ui.panels import PanelManager


class _FakeGate:
    """Supplies exactly the three things is_overlay_open_or_committed reads off self."""
    def __init__(self, full_visible=False, animating=False, pending=None):
        self._full_visible = full_visible
        self._animating = animating
        self._pending_panel_open = pending

    def is_any_full_panel_visible(self):
        return self._full_visible

    def is_any_panel_animating(self):
        return self._animating


def _gate(**kwargs):
    # Invoke the REAL method against the fake (unbound-method call), so any future change
    # to the composition is caught here.
    return PanelManager.is_overlay_open_or_committed(_FakeGate(**kwargs))


def test_all_clear_allows_open():
    assert _gate() is False


def test_full_panel_visible_blocks():
    assert _gate(full_visible=True) is True


def test_panel_animating_blocks():
    assert _gate(animating=True) is True


def test_committed_pending_open_blocks():
    assert _gate(pending="library") is True


def test_bare_expanded_sidebar_does_not_block():
    # THE load-bearing case: an expanded, settled sidebar with nothing pending must NOT
    # block — the sidebar-queued open path depends on opening a panel FROM the sidebar.
    # A settled sidebar is not full-visible, not animating, nothing pending → allowed.
    assert _gate(full_visible=False, animating=False, pending=None) is False


def test_any_one_input_is_sufficient_to_block():
    # OR semantics: each input alone blocks; combinations block.
    assert _gate(full_visible=True, animating=False, pending=None) is True
    assert _gate(full_visible=False, animating=True, pending=None) is True
    assert _gate(full_visible=False, animating=False, pending="stats") is True
    assert _gate(full_visible=True, animating=True, pending="tags") is True
