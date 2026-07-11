"""Behavior contract for BookDetailPanel.keyPressEvent (tab-switching + per-tab actions).

BookDetailPanel is granted real Qt focus while open (PanelManager._claim_panel_focus, no
panel_key — the panel itself is the claim target), so its own keyPressEvent is where
Left/Right/F/Del/X/K/Space/Enter live, same shape as ChapterList/StatsPanel. Tab/Backtab/
Escape stay entirely in the app-installed eventFilter (untouched by this feature) — this
method is never reached for those. keyPressEvent only ever runs when NOT editing: entering
edit mode gives a QLineEdit real focus instead (confirmed live), so no explicit _editing
guard is needed in the method itself.

Standing up a real BookDetailPanel needs db/config + the full widget tree, so — following
the pattern in test_stats_panel_keys.py — this binds the REAL unbound `keyPressEvent` (and
the small `_cycle_tab`/`_history_key_event`/`_move_history_selection`/`_cover_key_event`
helpers it calls) to a tiny fake supplying only what those methods actually read: `tabs`,
the confirm-state flags, `_history_rows`/`_history_selected_index`, `_meta_action_btn`, and
a fake `_cover_panel`. The hard requirement is REUSE: every action must call the exact
method the corresponding mouse control already calls
(`_on_finished_clicked`/`_on_confirm_finished`/`_on_remove_clicked`/`_on_confirm_remove`/
`_on_meta_action_clicked`/`_HistoryRow._on_trash_clicked`/`_on_confirm_clicked`/
`CoverPanel.select_adjacent`/`activate_selected`/`delete_selected`/`click_fit_button`) — no
reimplemented confirm/delete/set-cover/fit logic.
"""
import pytest
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QKeyEvent

from fabulor.ui.book_detail_panel import BookDetailPanel


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeTabs:
    _ORDER = ["Stats", "History", "Tags", "Cover"]

    def __init__(self, active="Stats"):
        self._index = self._ORDER.index(active)
        self.set_calls = []

    def count(self):
        return len(self._ORDER)

    def currentIndex(self):
        return self._index

    def setCurrentIndex(self, i):
        self._index = i
        self.set_calls.append(i)

    def tabText(self, index):
        return self._ORDER[index]


class _FakeHistoryRow:
    def __init__(self, name):
        self.name = name
        self._state = 'idle'
        self.calls = []
        self.kbd_selected_calls = []

    def _on_trash_clicked(self):
        self.calls.append("trash_clicked")

    def _on_confirm_clicked(self):
        self.calls.append("confirm_clicked")

    def set_keyboard_selected(self, selected):
        self.kbd_selected_calls.append(selected)


class _FakeHistoryScroll:
    def __init__(self):
        self.ensure_visible_calls = []

    def ensureWidgetVisible(self, widget):
        self.ensure_visible_calls.append(widget)


class _FakeCoverPanel:
    def __init__(self, has_selection=True):
        self._has_selection = has_selection
        self.select_adjacent_calls = []
        self.activate_selected_calls = 0
        self.delete_selected_calls = 0
        self.fit_calls = []

    def has_selection(self):
        return self._has_selection

    def select_adjacent(self, direction):
        self.select_adjacent_calls.append(direction)

    def activate_selected(self):
        self.activate_selected_calls += 1

    def delete_selected(self):
        self.delete_selected_calls += 1

    def click_fit_button(self, key):
        self.fit_calls.append(key)


class _FakeBookDetailPanel(BookDetailPanel):
    """A real BookDetailPanel SUBCLASS (zero-arg super() calls inside keyPressEvent/its
    helpers resolve via __class__=BookDetailPanel, requiring isinstance(obj,
    BookDetailPanel)) whose __init__ skips the heavy db/config-dependent UI build."""

    def __init__(self, active_tab="Stats", meta_btn_visible=False,
                 confirming_finished=False, confirming_remove=False,
                 history_rows=None, history_selected_index=-1,
                 confirming_history_row=None, cover_has_selection=True,
                 editing=False):
        QWidget.__init__(self)   # bypass BookDetailPanel.__init__ (needs db/config)
        self.tabs = _FakeTabs(active_tab)
        self._meta_action_btn = _FakeMetaBtn(meta_btn_visible)
        self._confirming_finished = confirming_finished
        self._confirming_remove = confirming_remove
        self._history_rows = history_rows if history_rows is not None else []
        self._history_selected_index = history_selected_index
        self._confirming_history_row = confirming_history_row
        self._history_scroll = _FakeHistoryScroll()
        self._cover_panel = _FakeCoverPanel(has_selection=cover_has_selection)
        self._editing = editing
        self.calls = []

    def _on_finished_clicked(self):
        self.calls.append("on_finished_clicked")

    def _on_confirm_finished(self):
        self.calls.append("on_confirm_finished")

    def _on_remove_clicked(self):
        self.calls.append("on_remove_clicked")

    def _on_confirm_remove(self):
        self.calls.append("on_confirm_remove")

    def _on_meta_action_clicked(self):
        self.calls.append("on_meta_action_clicked")

    def _on_history_tab(self):
        return self.tabs.tabText(self.tabs.currentIndex()) == "History"

    def _on_cover_tab(self):
        return self.tabs.tabText(self.tabs.currentIndex()) == "Cover"


class _FakeMetaBtn:
    def __init__(self, visible):
        self._visible = visible

    def isVisible(self):
        return self._visible


def _press(obj, key, mods=Qt.KeyboardModifier.NoModifier):
    ev = QKeyEvent(QEvent.Type.KeyPress, key, mods)
    obj.keyPressEvent(ev)


# ── While editing: Up/Down cycle metadata fields, everything else falls through ──
#
# Bug (found live, 2026-07-12): a single-line QLineEdit has no native handling for Up/Down,
# so it left those events unaccepted and Qt propagated them to BookDetailPanel.keyPressEvent
# — which, before this fix, dispatched them as whatever tab-local binding was active (e.g.
# History row selection), firing WHILE the user was mid-edit of a metadata field. Fixed by
# checking self._editing first and routing Up/Down through _cycle_metadata_field (the same
# method Tab/Shift-Tab already use) instead. Uses a REAL BookDetailPanel with real QLineEdit
# fields (not the tabs/confirm-state fake above) since this exercises real Qt focus transfer
# between the four fields, not just dispatch logic.

class _EditingHarness(BookDetailPanel):
    def __init__(self):
        QWidget.__init__(self)
        from PySide6.QtWidgets import QLineEdit
        self._title_label = QLineEdit(self)
        self._author_label = QLineEdit(self)
        self._narrator_label = QLineEdit(self)
        self._year_label = QLineEdit(self)
        self._editing = True
        self.tabs = _FakeTabs("History")   # would claim Up/Down for row-nav if editing didn't win
        self._history_rows = [_FakeHistoryRow("row0")]
        self._history_selected_index = -1
        self.cycle_calls = []

    # Spy on the real dispatch target rather than asserting QApplication.focusWidget()
    # directly — headless/offscreen Qt does not reliably register setFocus() synchronously
    # without a real window-manager-activated top-level window (same limitation noted
    # elsewhere in this test suite's history), so focusWidget()-based assertions here would
    # be flaky. _cycle_metadata_field itself (the real, unfaked method) is what's under test.
    def _cycle_metadata_field(self, backward):
        self.cycle_calls.append(backward)


def test_down_while_editing_calls_cycle_metadata_field_forward(qapp):
    h = _EditingHarness()
    _press(h, Qt.Key.Key_Down)
    assert h.cycle_calls == [False]          # backward=False -> next field
    assert h._history_selected_index == -1   # untouched — History row-nav did NOT fire


def test_up_while_editing_calls_cycle_metadata_field_backward(qapp):
    h = _EditingHarness()
    _press(h, Qt.Key.Key_Up)
    assert h.cycle_calls == [True]           # backward=True -> previous field
    assert h._history_selected_index == -1


def test_left_right_while_editing_do_not_cycle_tabs(qapp):
    # Left/Right must fall through to super() while editing (QLineEdit owns them for cursor
    # movement) — NOT be reinterpreted as BookDetailPanel's own tab-cycle binding.
    h = _EditingHarness()
    before = h.tabs.currentIndex()
    _press(h, Qt.Key.Key_Right)
    assert h.tabs.currentIndex() == before   # tab did not change
    assert h.cycle_calls == []               # and not misrouted to field-cycling either


def test_delete_while_editing_does_not_arm_remove(qapp):
    # Del must fall through to super() (QLineEdit's native delete-char) while editing, not
    # be reinterpreted as the top-level remove-from-library binding.
    h = _EditingHarness()
    h._confirming_remove = False
    _press(h, Qt.Key.Key_Delete)
    assert h._confirming_remove is False
    assert h.cycle_calls == []


# ── Tab switching (Left/Right) ────────────────────────────────────────────────────

def test_left_right_cycles_tabs_forward_and_wraps(qapp):
    fake = _FakeBookDetailPanel(active_tab="Stats")
    order = []
    for _ in range(5):
        _press(fake, Qt.Key.Key_Right)
        order.append(fake.tabs.tabText(fake.tabs.currentIndex()))
    assert order == ["History", "Tags", "Cover", "Stats", "History"]


def test_left_right_cycles_tabs_backward_and_wraps(qapp):
    fake = _FakeBookDetailPanel(active_tab="Stats")
    order = []
    for _ in range(5):
        _press(fake, Qt.Key.Key_Left)
        order.append(fake.tabs.tabText(fake.tabs.currentIndex()))
    assert order == ["Cover", "Tags", "History", "Stats", "Cover"]


# ── Top-level F (finished-toggle) ────────────────────────────────────────────────

def test_f_on_non_cover_tab_arms_finished_toggle(qapp):
    fake = _FakeBookDetailPanel(active_tab="Stats")
    _press(fake, Qt.Key.Key_F)
    assert fake.calls == ["on_finished_clicked"]


def test_space_confirms_finished_when_armed(qapp):
    fake = _FakeBookDetailPanel(active_tab="Stats", confirming_finished=True)
    _press(fake, Qt.Key.Key_Space)
    assert fake.calls == ["on_confirm_finished"]


def test_enter_confirms_finished_when_armed(qapp):
    fake = _FakeBookDetailPanel(active_tab="Stats", confirming_finished=True)
    _press(fake, Qt.Key.Key_Return)
    assert fake.calls == ["on_confirm_finished"]


# ── Top-level Del/X (remove-from-library) ────────────────────────────────────────

@pytest.mark.parametrize("key", [Qt.Key.Key_Delete, Qt.Key.Key_X])
def test_del_or_x_on_non_cover_tab_arms_remove(qapp, key):
    fake = _FakeBookDetailPanel(active_tab="Tags")
    _press(fake, key)
    assert fake.calls == ["on_remove_clicked"]


def test_space_confirms_remove_when_armed(qapp):
    fake = _FakeBookDetailPanel(active_tab="Stats", confirming_remove=True)
    _press(fake, Qt.Key.Key_Space)
    assert fake.calls == ["on_confirm_remove"]


def test_finished_confirm_takes_priority_over_remove_confirm_if_both_somehow_armed(qapp):
    # Mirrors _on_finished_clicked's own mutual-exclusivity (arming one cancels the other),
    # so in practice both are never simultaneously True — but keyPressEvent's own dispatch
    # order (finished checked first) is pinned here regardless.
    fake = _FakeBookDetailPanel(active_tab="Stats", confirming_finished=True, confirming_remove=True)
    _press(fake, Qt.Key.Key_Space)
    assert fake.calls == ["on_confirm_finished"]


# ── Top-level K (metadata lock button) ───────────────────────────────────────────

def test_k_fires_meta_action_when_button_visible(qapp):
    fake = _FakeBookDetailPanel(active_tab="Stats", meta_btn_visible=True)
    _press(fake, Qt.Key.Key_K)
    assert fake.calls == ["on_meta_action_clicked"]


def test_k_is_a_noop_when_meta_button_hidden(qapp):
    fake = _FakeBookDetailPanel(active_tab="Stats", meta_btn_visible=False)
    _press(fake, Qt.Key.Key_K)
    assert fake.calls == []


# ── Stray no-ops (nothing armed / no tab-local claim) ────────────────────────────

def test_space_enter_del_are_noops_with_nothing_armed_on_tags_tab(qapp):
    fake = _FakeBookDetailPanel(active_tab="Tags")  # Del here maps to remove, tested above;
    # this test specifically covers Space/Enter with nothing armed and no History/Cover claim.
    _press(fake, Qt.Key.Key_Space)
    _press(fake, Qt.Key.Key_Return)
    assert fake.calls == []


# ── History tab: Up/Down/Del/Space/Enter ─────────────────────────────────────────

def _history_fake(selected_index=-1, n=3, confirming_row=None):
    rows = [_FakeHistoryRow(f"row{i}") for i in range(n)]
    return _FakeBookDetailPanel(
        active_tab="History", history_rows=rows,
        history_selected_index=selected_index, confirming_history_row=confirming_row,
    ), rows


def test_history_down_selects_first_row_from_nothing_selected(qapp):
    fake, rows = _history_fake(selected_index=-1)
    _press(fake, Qt.Key.Key_Down)
    assert fake._history_selected_index == 0
    assert rows[0].kbd_selected_calls == [True]


def test_history_down_moves_selection_and_clears_previous_row(qapp):
    fake, rows = _history_fake(selected_index=0)
    _press(fake, Qt.Key.Key_Down)
    assert fake._history_selected_index == 1
    assert rows[0].kbd_selected_calls == [False]
    assert rows[1].kbd_selected_calls == [True]


def test_history_down_clamps_at_last_row_no_wrap(qapp):
    fake, rows = _history_fake(selected_index=2, n=3)
    _press(fake, Qt.Key.Key_Down)
    assert fake._history_selected_index == 2   # unchanged — clamped, no wrap


def test_history_up_clamps_at_first_row_no_wrap(qapp):
    fake, rows = _history_fake(selected_index=0, n=3)
    _press(fake, Qt.Key.Key_Up)
    assert fake._history_selected_index == 0   # unchanged — clamped, no wrap


def test_history_up_down_noop_with_zero_rows(qapp):
    fake, rows = _history_fake(selected_index=-1, n=0)
    _press(fake, Qt.Key.Key_Down)
    _press(fake, Qt.Key.Key_Up)
    assert fake._history_selected_index == -1


def test_history_del_arms_the_selected_rows_own_trash_click(qapp):
    fake, rows = _history_fake(selected_index=1)
    _press(fake, Qt.Key.Key_Delete)
    assert rows[1].calls == ["trash_clicked"]
    assert rows[0].calls == []
    assert rows[2].calls == []


def test_history_del_noop_with_nothing_selected(qapp):
    fake, rows = _history_fake(selected_index=-1)
    _press(fake, Qt.Key.Key_Delete)
    assert all(r.calls == [] for r in rows)


def test_history_space_confirms_the_armed_row(qapp):
    fake, rows = _history_fake(selected_index=1, confirming_row=None)
    fake._confirming_history_row = rows[1]
    _press(fake, Qt.Key.Key_Space)
    assert rows[1].calls == ["confirm_clicked"]


def test_history_space_noop_when_nothing_armed(qapp):
    fake, rows = _history_fake(selected_index=1, confirming_row=None)
    _press(fake, Qt.Key.Key_Space)
    assert all(r.calls == [] for r in rows)
    assert fake.calls == []   # does not fall through to top-level finished/remove confirm


# ── Cover tab: Up/Down/Space/Enter/Del/F-T-S-C ───────────────────────────────────

def test_cover_up_down_calls_select_adjacent(qapp):
    fake = _FakeBookDetailPanel(active_tab="Cover")
    _press(fake, Qt.Key.Key_Down)
    _press(fake, Qt.Key.Key_Up)
    assert fake._cover_panel.select_adjacent_calls == [1, -1]


def test_cover_space_and_enter_activate_selected(qapp):
    fake = _FakeBookDetailPanel(active_tab="Cover", cover_has_selection=True)
    _press(fake, Qt.Key.Key_Space)
    _press(fake, Qt.Key.Key_Return)
    assert fake._cover_panel.activate_selected_calls == 2


def test_cover_space_noop_without_selection(qapp):
    fake = _FakeBookDetailPanel(active_tab="Cover", cover_has_selection=False)
    _press(fake, Qt.Key.Key_Space)
    assert fake._cover_panel.activate_selected_calls == 0


def test_cover_del_deletes_selected(qapp):
    fake = _FakeBookDetailPanel(active_tab="Cover", cover_has_selection=True)
    _press(fake, Qt.Key.Key_Delete)
    assert fake._cover_panel.delete_selected_calls == 1


@pytest.mark.parametrize("key,fit_key", [
    (Qt.Key.Key_F, "fit"), (Qt.Key.Key_T, "top"),
    (Qt.Key.Key_S, "stretch"), (Qt.Key.Key_C, "crop"),
])
def test_cover_fit_keys_click_the_matching_fit_button(qapp, key, fit_key):
    fake = _FakeBookDetailPanel(active_tab="Cover", cover_has_selection=True)
    _press(fake, key)
    assert fake._cover_panel.fit_calls == [fit_key]


# ── The collision case: Cover-tab F wins over top-level finished-toggle F ────────

def test_cover_tab_f_does_not_arm_finished_toggle(qapp):
    fake = _FakeBookDetailPanel(active_tab="Cover", cover_has_selection=True)
    _press(fake, Qt.Key.Key_F)
    assert fake._cover_panel.fit_calls == ["fit"]
    assert fake.calls == []   # on_finished_clicked must NOT have fired


def test_non_cover_tab_f_arms_finished_toggle_normally(qapp):
    # Control case, same key, different tab — confirms the collision fix is tab-scoped,
    # not a blanket suppression of top-level F.
    fake = _FakeBookDetailPanel(active_tab="Stats")
    _press(fake, Qt.Key.Key_F)
    assert fake.calls == ["on_finished_clicked"]


# ── Regression: releasing focus from a child field must reclaim it for the panel ─
#
# Bug (found live, 2026-07-12): _clear_tag_input and _exit_edit_mode called clearFocus() on
# a child QLineEdit but never reclaimed focus for the panel itself. Qt does NOT auto-reassign
# a cleared child's focus to its parent, so QApplication.focusWidget() dropped to None —
# which MainWindow._focus_allows_global_shortcuts() reads as "no panel-local widget has
# focus," letting the GLOBAL dispatcher fire instead of this panel's own keyPressEvent. Since
# handle_rewind/handle_forward (bound to arrow keys) call hide_all_panels() unconditionally,
# every arrow press silently closed the whole panel right after tabbing out of the tag field
# or exiting metadata edit mode. These tests pin the actual widgets involved (real QLineEdits
# on a real QWidget, not the tabs/confirm-state fake above) since this is real Qt focus
# mechanics, not keyPressEvent dispatch logic — the live-focus behavior itself was confirmed
# by direct instrumented trace, not assumed from these tests alone.

# Headless-CI note: asserting QApplication.focusWidget() end-to-end needs a real window-
# manager-activated top-level window (confirmed — setFocus()/activateWindow()/raise_() alone
# do not register synchronously under the offscreen platform pytest runs under here, same
# limitation noted elsewhere in this test suite's history). The live fix was verified by
# direct instrumented trace against the real running app (3/3 deterministic runs) — see
# NOTES.md. This test instead pins the code-level contract deterministically: both methods
# must call self.setFocus() as their last focus-related action, via a spy on a real
# BookDetailPanel-method binding (isinstance(obj, BookDetailPanel) required for the zero-arg
# super() calls elsewhere in the class, same constraint as _FakeBookDetailPanel above).

class _FocusSpyBookDetailPanel(BookDetailPanel):
    def __init__(self):
        QWidget.__init__(self)   # bypass BookDetailPanel.__init__ (needs db/config)
        from PySide6.QtWidgets import QLineEdit
        self._tag_input = QLineEdit(self)
        self._title_label = QLineEdit(self)
        self._author_label = QLineEdit(self)
        self._narrator_label = QLineEdit(self)
        self._year_label = QLineEdit(self)
        self._editing = False
        self._pre_edit_meta_state = None
        self._book_data = {}
        self.setFocus_calls = 0

    def setFocus(self, *a, **kw):
        self.setFocus_calls += 1
        super().setFocus(*a, **kw)

    # Methods _exit_edit_mode calls that aren't relevant to this focus-only test.
    def _commit_inline_save(self): pass
    def _sync_header_from_fields(self): pass
    def _set_meta_state(self, state): pass


def test_clear_tag_input_reclaims_panel_focus(qapp):
    panel = _FocusSpyBookDetailPanel()
    panel._clear_tag_input()
    assert panel.setFocus_calls == 1


def test_exit_edit_mode_reclaims_panel_focus(qapp):
    panel = _FocusSpyBookDetailPanel()
    panel._editing = True
    panel._exit_edit_mode(save=False)
    assert panel.setFocus_calls == 1


def test_exit_edit_mode_is_a_noop_when_not_editing(qapp):
    # Guards the early return — must not call setFocus (or anything else) when there was
    # nothing to exit.
    panel = _FocusSpyBookDetailPanel()
    panel._editing = False
    panel._exit_edit_mode(save=False)
    assert panel.setFocus_calls == 0
