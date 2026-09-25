"""Regression net for StatsPanel.suspend_timeline_paint/resume_timeline_paint (2026-09-25).

Added after live instrumentation (_wire_paint_probe, generalized the same night to cover
Stats' own slide, not just Book Detail's — see NOTES.md, "General app sluggishness
investigation") found StreakGrid.paintEvent costing 20-27ms per call and firing 6-12 times
during a single ~300ms Stats slide, even though the grid's content is already fully
determined by refresh_current_tab()/_refresh_time() before the slide ever starts (see
_start_stats_entry, panels.py). The fix suspends whichever Timeline grid is currently
visible (_streak_grid or _heatmap, per _show_streak_grid) for the duration of the slide.

A FIRST version of this fix (bare setUpdatesEnabled(False), no proxy) shipped a real visual
regression, live-reported by Pryme with screenshots: the grid slid in visibly BLANK, then
popped fully-painted the instant resume ran. The corrected version grabs a pixmap of the
grid's already-correct content BEFORE disabling updates and shows that via a QLabel proxy —
these tests specifically cover the proxy half, not just updatesEnabled toggling, since that's
exactly the part the first version was missing and a proxy-blind test wouldn't have caught.

Uses a light fake standing in for `self`, same shape as test_stats_panel_occlusion_guard.py
— real QWidgets for the two grids, parented to a real shared container (so grid.parentWidget()
resolves the way it does in the real StatsPanel, not to None) — no full StatsPanel construction.
"""
from PySide6.QtWidgets import QApplication, QWidget

from fabulor.ui.stats_panel import StatsPanel


def _qapp():
    return QApplication.instance() or QApplication([])


class _FakeTimelineHost:
    def __init__(self, show_streak_grid):
        self._show_streak_grid = show_streak_grid
        self._container = QWidget()
        self._streak_grid = QWidget(self._container)
        self._streak_grid.setGeometry(10, 20, 242, 448)
        self._heatmap = QWidget(self._container)
        self._heatmap.setGeometry(10, 20, 242, 336)
        # isVisible() is ancestor-chain-dependent — a widget's own show() is not enough if its
        # parent was never shown. The real StatsPanel's stats_time_tab IS shown by the time
        # suspend_timeline_paint runs (see _start_stats_entry's ordering); mirror that here.
        self._container.show()


def test_suspend_disables_updates_on_streak_grid_when_it_is_the_visible_one():
    _qapp()
    host = _FakeTimelineHost(show_streak_grid=True)
    StatsPanel.suspend_timeline_paint(host)
    assert host._streak_grid.updatesEnabled() is False
    assert host._heatmap.updatesEnabled() is True


def test_suspend_disables_updates_on_heatmap_when_it_is_the_visible_one():
    _qapp()
    host = _FakeTimelineHost(show_streak_grid=False)
    StatsPanel.suspend_timeline_paint(host)
    assert host._heatmap.updatesEnabled() is False
    assert host._streak_grid.updatesEnabled() is True


def test_resume_re_enables_updates_on_the_same_grid_suspend_targeted():
    _qapp()
    host = _FakeTimelineHost(show_streak_grid=True)
    StatsPanel.suspend_timeline_paint(host)
    assert host._streak_grid.updatesEnabled() is False
    StatsPanel.resume_timeline_paint(host)
    assert host._streak_grid.updatesEnabled() is True


def test_resume_targets_heatmap_when_it_was_the_visible_one():
    _qapp()
    host = _FakeTimelineHost(show_streak_grid=False)
    StatsPanel.suspend_timeline_paint(host)
    StatsPanel.resume_timeline_paint(host)
    assert host._heatmap.updatesEnabled() is True


def test_suspend_missing_show_streak_grid_attribute_defaults_to_heatmap():
    """Mirrors the getattr(self, '_show_streak_grid', False) default already used elsewhere in
    stats_panel.py (e.g. _inject_active_covers's sibling reads) — a host that hasn't set the
    flag yet must not raise, and must fall back to the heatmap (the config default, per
    get_default_timeline_view())."""
    _qapp()
    class _BareHost:
        def __init__(self):
            self._container = QWidget()  # kept as an attribute so it isn't GC'd mid-test
            self._streak_grid = QWidget(self._container)
            self._heatmap = QWidget(self._container)
            self._container.show()
    host = _BareHost()
    StatsPanel.suspend_timeline_paint(host)
    assert host._heatmap.updatesEnabled() is False
    assert host._streak_grid.updatesEnabled() is True


def test_suspend_shows_a_proxy_holding_the_grids_content_at_its_geometry():
    """The regression this whole file exists to prevent: a bare setUpdatesEnabled(False) with
    no proxy left the grid visibly blank for the suspended window. The fix must show SOMETHING
    in the grid's place immediately — a QLabel proxy, positioned at the grid's own geometry
    (same parent, so the coordinates line up), holding a non-null pixmap, raised above it."""
    _qapp()
    host = _FakeTimelineHost(show_streak_grid=True)
    StatsPanel.suspend_timeline_paint(host)
    proxy = host._timeline_paint_proxy
    assert proxy.isVisible() is True
    assert proxy.parentWidget() is host._container
    assert proxy.geometry() == host._streak_grid.geometry()
    assert proxy.pixmap() is not None
    assert not proxy.pixmap().isNull()


def test_resume_hides_the_proxy():
    _qapp()
    host = _FakeTimelineHost(show_streak_grid=True)
    StatsPanel.suspend_timeline_paint(host)
    assert host._timeline_paint_proxy.isVisible() is True
    StatsPanel.resume_timeline_paint(host)
    assert host._timeline_paint_proxy.isVisible() is False


def test_suspend_reuses_the_same_proxy_across_calls_rather_than_leaking_a_new_one_each_time():
    """A fresh QLabel per suspend() call (rather than lazily building one and reusing it) would
    leak a widget on every panel open/close cycle — a real, if slow, memory leak over a long
    session. Confirms the lazy-build-once shape actually reuses the same instance."""
    _qapp()
    host = _FakeTimelineHost(show_streak_grid=True)
    StatsPanel.suspend_timeline_paint(host)
    first_proxy = host._timeline_paint_proxy
    StatsPanel.resume_timeline_paint(host)
    StatsPanel.suspend_timeline_paint(host)
    assert host._timeline_paint_proxy is first_proxy


def test_suspend_positions_proxy_at_heatmap_geometry_when_heatmap_is_visible():
    _qapp()
    host = _FakeTimelineHost(show_streak_grid=False)
    StatsPanel.suspend_timeline_paint(host)
    assert host._timeline_paint_proxy.geometry() == host._heatmap.geometry()
