"""_apply_stylesheets excludes speed_panel/sleep_panel from hover entirely (2026-08-04).

See NOTES.md 2026-08-04 "the actual root cause" and
review/Design_260804_write_path_confinement.md. Confirmed live: Settings' Themes tab is the ONLY
panel ever visible during a hover preview (Settings/Speed/Sleep/Library/Stats/Tags are mutually
exclusive — see CLAUDE.md), yet `_apply_stylesheets` built and unconditionally stashed
speed_panel/sleep_panel's sheets on every hover tick via `self._pending_panel_sheet = dict(panel_
sheets)` (a full replace, not a hover-gated write). If a genuine unhover was ever suppressed
(e.g. a real leaveEvent misclassified as a blur-grab synthetic by `_on_themes_tab_left`'s hidden-
widget branch — logged by `[SWATCH-LEAVE-SUSPECT]` but never corrected), the stash stayed
contaminated with the last-hovered theme until an unrelated event forced a fresh hover=False apply
— confirmed live at over 90 seconds of staleness in one session.

Fix: when hover=True, `panel_sheets` (and therefore both the live-paint loop and the stash) never
contains speed_panel/sleep_panel entries at all — they are omitted from the call entirely, not
visibility-checked or corrected after the fact. The stash write became `dict.update(...)` instead
of a bare replace, so a hover's narrower `panel_sheets` cannot wipe out speed_panel/sleep_panel's
already-correct, previously-committed stash entries.

These tests exercise the REAL `_apply_stylesheets` against a real (headless) QApplication and real
QWidget stand-ins for the three panels — not a fake, since the bug lived in exactly how this method
builds and writes its own stash dict, which a bound-method fake would risk re-encoding rather than
catching.
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
    mw.tabs = None

    # Settings visible, Speed/Sleep hidden — matches the real app's one-overlay
    # gate: Settings' Themes tab is the only panel ever visible during a hover,
    # and speed_panel/sleep_panel stay hidden throughout every test here, same
    # as they always are for the real duration of any hover.
    mw.settings_panel.show()

    tm = ThemeManager(mw)
    tm._current_theme_name = "Fire and Blood"
    return tm


COMMITTED = "Fire and Blood"
HOVER = "Cerulean Sea"


def test_hover_apply_never_touches_speed_or_sleep_live_stylesheet(theme_manager):
    tm = theme_manager
    mw = tm.main_window
    tm._apply_stylesheets(COMMITTED, hover=False)
    speed_sheet_before = mw.speed_panel.styleSheet()
    sleep_sheet_before = mw.sleep_panel.styleSheet()

    tm._apply_stylesheets(HOVER, hover=True)

    assert mw.speed_panel.styleSheet() == speed_sheet_before
    assert mw.sleep_panel.styleSheet() == sleep_sheet_before
    # Settings, the only panel visible during a hover, DOES get the hover sheet live.
    assert mw.settings_panel.styleSheet() != ""


def test_hover_apply_never_touches_speed_or_sleep_stash(theme_manager):
    tm = theme_manager
    tm._apply_stylesheets(COMMITTED, hover=False)
    speed_stash_before = tm._pending_panel_sheet.get("speed_panel")
    sleep_stash_before = tm._pending_panel_sheet.get("sleep_panel")
    assert speed_stash_before is not None  # sanity: the committed apply did stash something

    tm._apply_stylesheets(HOVER, hover=True)

    assert tm._pending_panel_sheet.get("speed_panel") == speed_stash_before
    assert tm._pending_panel_sheet.get("sleep_panel") == sleep_stash_before
    # settings_panel's stash DOES update to the hover sheet.
    assert tm._pending_panel_sheet.get("settings_panel") != speed_stash_before


def test_non_hover_apply_still_stashes_all_three_panels(theme_manager):
    # Confirms the fix is scoped to hover=True ONLY — a genuine committed theme
    # change must still build and stash settings/speed/sleep's sheets exactly as
    # before. (Live setStyleSheet() calls are separately gated on w.isVisible()
    # for BOTH hover and non-hover — "applies to snapback too" per the real
    # method's own comment — so the stash, not the live paint, is the correct
    # thing to assert here; speed_panel/sleep_panel stay hidden throughout this
    # fixture, matching the real app.)
    tm = theme_manager
    tm._apply_stylesheets(COMMITTED, hover=False)
    first_speed_stash = tm._pending_panel_sheet.get("speed_panel")
    first_sleep_stash = tm._pending_panel_sheet.get("sleep_panel")

    tm._apply_stylesheets(HOVER, hover=False)

    for attr in ("settings_panel", "speed_panel", "sleep_panel"):
        assert attr in tm._pending_panel_sheet
    # A genuine (non-hover) theme change DOES update speed/sleep's stash —
    # unlike the hover case, which must leave it untouched.
    assert tm._pending_panel_sheet.get("speed_panel") != first_speed_stash
    assert tm._pending_panel_sheet.get("sleep_panel") != first_sleep_stash
