"""Regression net for ScrollHoverTracker/GridHoverTracker's app-wide event
filter install/remove lifecycle (fixed 2026-09-22, part of the general
app-slowness investigation triggered by TODO_ARCHIVE.md's "Book Detail
slide-in..." entry).

Root cause: both classes installed their QApplication-wide filter once in
__init__ and never removed it — TagManagerWidget (the sole constructor of
either class, `tag_manager.py`) is built ONCE at app startup and immediately
`.hide()`'d, so the filter stayed live from launch until Tags was opened at
least once, and even then only got a real install/remove pair for
TagManagerWidget's OWN filter, not these two trackers' — they kept walking
every Qt event in the app for the whole session regardless of whether Tags
was ever visible. Confirmed via a live cProfile capture of an UNRELATED
Book Detail open showing both trackers' eventFilter firing thousands of
times.

Fix: `install_filter()`/`remove_filter()` are now the sole entry points —
neither class installs anything in __init__ — and TagManagerWidget calls
them at every real visibility transition (showEvent/hideEvent, and the
_open_tag/_show_list sub-view toggle, which does NOT re-fire showEvent).

These tests verify the filter's actual INSTALLED state via observable
behavior (does a synthetic event reach eventFilter?), not by inspecting
Qt internals — QObject has no public "am I installed" query.
"""
import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QApplication, QScrollArea, QWidget

from fabulor.ui.hover_tracker import ScrollHoverTracker, GridHoverTracker


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _make_scroll_tracker(qapp):
    scroll = QScrollArea()
    container = QWidget()
    scroll.setWidget(container)
    tracker = ScrollHoverTracker(scroll, rows_of=lambda: [])
    return tracker


def _make_grid_tracker(qapp):
    scroll = QScrollArea()
    container = QWidget()
    scroll.setWidget(container)
    tracker = GridHoverTracker(scroll, container, is_cell=lambda w: False)
    return tracker


def _filter_sees_event(tracker, qapp) -> bool:
    """True iff `tracker` is currently reachable via QApplication's filter
    chain, checked by sending a real event of a type its eventFilter tracks
    (Enter) to a throwaway widget and seeing whether eventFilter's own
    early-init side effect (building _TRACKED_EVENTS) or hovered-state
    change occurs. Simpler and more direct: patch eventFilter to record
    whether it was ever called at all for this send."""
    calls = []
    orig = tracker.eventFilter
    tracker.eventFilter = lambda obj, event: (calls.append(1), orig(obj, event))[1]
    w = QWidget()
    ev = QEvent(QEvent.Type.Enter)
    QApplication.sendEvent(w, ev)
    tracker.eventFilter = orig
    return bool(calls)


def test_scroll_tracker_installs_nothing_at_construction(qapp):
    tracker = _make_scroll_tracker(qapp)
    assert not _filter_sees_event(tracker, qapp), (
        "ScrollHoverTracker must NOT install its filter in __init__ — the "
        "owner (TagManagerWidget) is built once at startup and hidden "
        "immediately, so an eager install here leaves the filter live from "
        "launch until the panel's first real open"
    )


def test_grid_tracker_installs_nothing_at_construction(qapp):
    tracker = _make_grid_tracker(qapp)
    assert not _filter_sees_event(tracker, qapp), (
        "GridHoverTracker must NOT install its filter in __init__ — same "
        "reasoning as ScrollHoverTracker"
    )


def test_scroll_tracker_install_then_remove_round_trips(qapp):
    tracker = _make_scroll_tracker(qapp)
    assert not _filter_sees_event(tracker, qapp)

    tracker.install_filter()
    assert _filter_sees_event(tracker, qapp), "install_filter() must make the filter reachable"

    tracker.remove_filter()
    assert not _filter_sees_event(tracker, qapp), "remove_filter() must make it unreachable again"


def test_grid_tracker_install_then_remove_round_trips(qapp):
    tracker = _make_grid_tracker(qapp)
    assert not _filter_sees_event(tracker, qapp)

    tracker.install_filter()
    assert _filter_sees_event(tracker, qapp)

    tracker.remove_filter()
    assert not _filter_sees_event(tracker, qapp)


def test_remove_filter_when_never_installed_is_a_harmless_noop(qapp):
    tracker = _make_scroll_tracker(qapp)
    tracker.remove_filter()  # must not raise
    assert not _filter_sees_event(tracker, qapp)


def test_install_filter_twice_does_not_break_removal(qapp):
    """Qt dedupes installEventFilter per-object — calling install_filter()
    twice must not require two remove_filter() calls to actually remove it."""
    tracker = _make_scroll_tracker(qapp)
    tracker.install_filter()
    tracker.install_filter()
    assert _filter_sees_event(tracker, qapp)

    tracker.remove_filter()
    assert not _filter_sees_event(tracker, qapp), (
        "a single remove_filter() must fully remove it even after two "
        "install_filter() calls — matches Qt's own documented dedup "
        "behavior for installEventFilter"
    )
