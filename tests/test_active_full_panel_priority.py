"""Pins PanelManager.active_full_panel()'s priority order — specifically that
book_detail_panel is checked FIRST, ahead of every other panel (2026-09-24 reorder).

Book Detail is the one panel that can be visible SIMULTANEOUSLY with another (it opens over
Stats or Library, raised above the underlay rather than hiding it — see the class docstring).
Before this reorder, active_full_panel() reported the UNDERLAY's key for the entire time Book
Detail was open, which caused two confirmed real bugs (see active_full_panel's own docstring for
the full trace): a right-click on the cover art closed the wrong panel (the underlay instead of
Book Detail), and MainWindow._kbdnav_active_panel_key resolved to the underlay's key, letting a
synthetic hover-resync dispatch a real QHoverEvent at the occluded panel's tab bar — surfacing as
a Stats tab lighting up "from nothing" on Book Detail close, live-reported and traced 2026-09-24.

Uses a light fake standing in for `self` (real method, unbound-call pattern), same shape as
test_panel_exclusion.py's _FakeGate and test_book_detail_slide_paint_suppression.py's
_FakeActiveFullPanelGate (which this supersedes with a fuller fixture covering every panel, not
just book_detail vs. None).
"""
import pytest

from fabulor.ui.panels import PanelManager


class _FakePanel:
    def __init__(self, visible=False):
        self._visible = visible

    def isVisible(self):
        return self._visible


class _FakeChapterListWidget:
    def __init__(self, visible=False):
        self._visible = visible

    def isVisible(self):
        return self._visible


class _FakeMainWindow:
    def __init__(self, chapter_list_visible=False):
        self.chapter_list_widget = _FakeChapterListWidget(chapter_list_visible)


class _FakeActiveFullPanelHost:
    """Supplies every panel active_full_panel() reads, all defaulting to hidden."""
    def __init__(self, **visible_panels):
        for name in ("library", "settings", "speed", "sleep", "sprint", "stats", "tags",
                     "book_detail"):
            setattr(self, f"{name}_panel", _FakePanel(visible_panels.get(name, False)))
        self.main_window = _FakeMainWindow(
            chapter_list_visible=visible_panels.get("chapter_list", False))

    def _is_closing(self, key):
        return False


def test_book_detail_wins_over_every_other_panel_when_both_are_visible():
    """The core regression net: book_detail simultaneously visible with each of the panels it
    can actually open over (and, defensively, every other panel too) must always report
    'book_detail', never the underlay's key."""
    for underlay in ("library", "settings", "speed", "sleep", "sprint", "stats", "tags"):
        host = _FakeActiveFullPanelHost(**{underlay: True, "book_detail": True})
        assert PanelManager.active_full_panel(host) == "book_detail", (
            f"book_detail must win over {underlay!r} when both are visible"
        )


def test_each_panel_reported_alone():
    for key in ("library", "settings", "speed", "sleep", "sprint", "stats", "tags",
                "book_detail"):
        host = _FakeActiveFullPanelHost(**{key: True})
        assert PanelManager.active_full_panel(host) == key


def test_chapter_list_reported_when_nothing_else_is_visible():
    host = _FakeActiveFullPanelHost(chapter_list=True)
    assert PanelManager.active_full_panel(host) == "chapter_list"


def test_book_detail_wins_over_chapter_list_too():
    host = _FakeActiveFullPanelHost(book_detail=True, chapter_list=True)
    assert PanelManager.active_full_panel(host) == "book_detail"


def test_none_when_nothing_is_visible():
    host = _FakeActiveFullPanelHost()
    assert PanelManager.active_full_panel(host) is None


@pytest.mark.parametrize("key", ["library", "settings", "speed", "sleep", "sprint", "stats",
                                  "tags"])
def test_closing_panel_is_excluded_even_when_book_detail_is_not_open(key):
    """A panel mid-close doesn't count as open — unaffected by the reorder, still correct."""
    class _ClosingHost(_FakeActiveFullPanelHost):
        def _is_closing(self, k):
            return k == key

    host = _ClosingHost(**{key: True})
    assert PanelManager.active_full_panel(host) is None
