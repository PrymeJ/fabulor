"""Regression net for `ThemeManager.apply_pending_panel_sheet` re-applying the
same stashed stylesheet on every panel open for the rest of the session,
instead of exactly once per genuine catch-up (found live 2026-09-22, during
the Book-Detail-panel-open performance investigation triggered by TODO.md's
"Book Detail slide-in feels less smooth from Library than from Stats").

Real cProfile capture of a live Book Detail open showed ~0.30-0.37s of a
~0.76-0.93s open window spent inside `_flush_pending_restyle` ->
`apply_pending_panel_sheet` -> `QWidget.setStyleSheet()`, called 4 times
(settings/speed/sleep/sprint) on every single Book Detail open — not just the
one open that should genuinely need to catch a hidden panel up after a theme
change. Cross-checked against the real session log: one `[PANEL-SHEET-STASH]`
write followed by 6+ `[PANEL-SHEET-CATCHUP]` re-applications of the SAME
stash entry over the next ~40 seconds of ordinary panel use, each a real
`setStyleSheet()` call on a panel nobody could see.

Root cause: `apply_pending_panel_sheet` read the stash with a plain
`dict.get(...)` and applied it, but never removed the entry — so the same
entry stayed in `_pending_panel_sheet` and got reapplied on every subsequent
open of that panel type until the NEXT genuine theme change overwrote it.
The stash is meant to be a one-shot "catch this panel up on the theme change
it missed while hidden," not a cache that keeps re-serving a stale-but-still-
correct sheet forever.

Fix: `dict.pop(panel.objectName(), None)` instead of `dict.get(...)` — the
entry is consumed (removed) the first time it's genuinely applied, so a
second call for the same panel with no new theme change in between is a
correct, cheap no-op instead of a second real `setStyleSheet()`.
"""
import pytest
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import QSettings

from fabulor.config import Config
from fabulor.ui.theme_manager import ThemeManager


@pytest.fixture
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def theme_manager(qapp, tmp_path):
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))

    mw = QWidget()
    mw.show()
    mw.config = Config()
    mw.settings_panel = QWidget(mw)
    mw.settings_panel.setObjectName("settings_panel")
    mw.speed_panel = QWidget(mw)
    mw.speed_panel.setObjectName("speed_panel")
    mw.sleep_panel = QWidget(mw)
    mw.sleep_panel.setObjectName("sleep_panel")
    mw.sprint_panel = QWidget(mw)
    mw.sprint_panel.setObjectName("sprint_panel")
    mw.tabs = None

    tm = ThemeManager(mw)
    tm._current_theme_name = "Fire and Blood"
    return tm


def test_stash_is_consumed_on_first_apply_not_reapplied_on_second_call(theme_manager):
    tm = theme_manager
    tm._pending_panel_sheet = {"speed_panel": "QWidget { background: red; }"}

    speed_panel = tm.main_window.speed_panel

    # First call: genuine catch-up, the stash entry exists and must be applied.
    tm.apply_pending_panel_sheet(speed_panel)
    assert speed_panel.styleSheet() == "QWidget { background: red; }"
    assert "speed_panel" not in tm._pending_panel_sheet, (
        "the entry must be CONSUMED (removed) once genuinely applied, not "
        "left in place to be reapplied on the next open — this is the exact "
        "live bug: 6+ redundant setStyleSheet() calls over one session for "
        "a single real theme change"
    )

    # Second call for the SAME panel, no new theme change in between: must be
    # a no-op — the stylesheet stays exactly as the first call left it, and
    # no second setStyleSheet() call happens (nothing to assert on a no-op
    # directly, but the pop-based guard means the method returns before
    # reaching panel.setStyleSheet at all).
    speed_panel.setStyleSheet("")  # simulate something else touching it meanwhile
    tm.apply_pending_panel_sheet(speed_panel)
    assert speed_panel.styleSheet() == "", (
        "a second catch-up call with nothing newly pending must not "
        "re-apply the old stash entry"
    )


def test_each_panel_keys_independently_in_the_shared_stash(theme_manager):
    """The stash is one dict shared across all 4 panels — consuming one
    panel's entry must not disturb the others still waiting for their own
    first catch-up."""
    tm = theme_manager
    tm._pending_panel_sheet = {
        "settings_panel": "QWidget { color: blue; }",
        "speed_panel": "QWidget { color: green; }",
        "sleep_panel": "QWidget { color: yellow; }",
        "sprint_panel": "QWidget { color: purple; }",
    }

    tm.apply_pending_panel_sheet(tm.main_window.settings_panel)

    assert tm.main_window.settings_panel.styleSheet() == "QWidget { color: blue; }"
    assert "settings_panel" not in tm._pending_panel_sheet
    # The other three must be untouched — still pending, still applicable.
    assert tm._pending_panel_sheet["speed_panel"] == "QWidget { color: green; }"
    assert tm._pending_panel_sheet["sleep_panel"] == "QWidget { color: yellow; }"
    assert tm._pending_panel_sheet["sprint_panel"] == "QWidget { color: purple; }"

    tm.apply_pending_panel_sheet(tm.main_window.speed_panel)
    assert tm.main_window.speed_panel.styleSheet() == "QWidget { color: green; }"
    assert "speed_panel" not in tm._pending_panel_sheet
    assert "sleep_panel" in tm._pending_panel_sheet
    assert "sprint_panel" in tm._pending_panel_sheet


def test_a_genuinely_new_theme_change_after_consumption_stashes_and_applies_again(theme_manager):
    """Consuming an entry must not prevent a LATER, real theme change from
    stashing and being caught up on normally — pop() removes the one stale
    entry, it doesn't disable the whole mechanism."""
    tm = theme_manager
    tm._pending_panel_sheet = {"sleep_panel": "QWidget { color: orange; }"}

    tm.apply_pending_panel_sheet(tm.main_window.sleep_panel)
    assert "sleep_panel" not in tm._pending_panel_sheet

    # A later, genuine theme change re-stashes (mirrors what _apply_stylesheets
    # does on each real apply — simulated directly here rather than driving
    # the full apply path, which test_hover_excludes_speed_sleep.py already
    # covers for the write side).
    tm._pending_panel_sheet["sleep_panel"] = "QWidget { color: teal; }"

    tm.apply_pending_panel_sheet(tm.main_window.sleep_panel)
    assert tm.main_window.sleep_panel.styleSheet() == "QWidget { color: teal; }"
    assert "sleep_panel" not in tm._pending_panel_sheet


def test_no_pending_stash_at_all_is_a_harmless_noop(theme_manager):
    tm = theme_manager
    tm._pending_panel_sheet = None
    tm.apply_pending_panel_sheet(tm.main_window.settings_panel)  # must not raise
    assert tm.main_window.settings_panel.styleSheet() == ""


def test_panel_none_is_a_harmless_noop(theme_manager):
    tm = theme_manager
    tm._pending_panel_sheet = {"settings_panel": "QWidget { color: pink; }"}
    tm.apply_pending_panel_sheet(None)  # must not raise
    assert tm._pending_panel_sheet == {"settings_panel": "QWidget { color: pink; }"}
