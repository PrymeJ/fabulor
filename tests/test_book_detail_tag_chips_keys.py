"""Behavior contract for BookDetailPanel's Tags-tab tag chip grid keyboard navigation
(_tag_chip_key_event, _tag_chip_rows, _select_tag_chip, _enter_tag_manager_from_grid).

Design settled 2026-09-19 (TODO.md), confirmed directly by Pryme via AskUserQuestion before
implementation — see _tag_chip_key_event's own docstring in book_detail_panel.py for the
full rationale. This file exercises it against REAL _TagChip widgets laid out by a REAL
FlowLayout (so row membership is measured from actual geometry, not assumed), following the
same "bind the real method to a tiny fake" shape test_book_detail_panel_keys.py already uses
for the panel's other tabs — the hard requirement is REUSE: Del must call the exact
_on_remove_tag the mouse's own x button calls, Space/Enter must emit the exact
tag_filter_requested signal a mouse click emits.
"""
import pytest
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QKeyEvent

from fabulor.ui.book_detail_panel import BookDetailPanel, _TagChip
from fabulor.ui.flow_layout import FlowLayout


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeTagManagerBtn:
    def __init__(self, visible=True):
        self._visible = visible
        self.emit_calls = 0

    def isVisible(self):
        return self._visible

    def setProperty(self, name, value):
        pass

    def style(self):
        return self

    def unpolish(self, w):
        pass

    def polish(self, w):
        pass


class _FakeSignal:
    def __init__(self):
        self.calls = []

    def emit(self, *args):
        self.calls.append(args)


class _TagChipHarness(BookDetailPanel):
    """Real BookDetailPanel subclass (same shape as test_book_detail_panel_keys.py's
    _FakeBookDetailPanel) with a REAL FlowLayout populated with REAL _TagChip widgets, laid
    out at a fixed width so row-wrapping is real and deterministic. Each chip is given a
    fixed 50x24 size (a bare _TagChip has no internal QHBoxLayout/labels in this harness —
    unlike _rebuild_tag_chips's real construction — so FlowLayout would otherwise size it
    to (0, 0) and everything would land on one row regardless of container width, silently
    making every "multi-row" test meaningless). `chips_per_row` sizes the container width
    to force exactly that many chips onto each row (50px chip + 8px h_spacing per column)."""

    def __init__(self, tags, context='library', active_search_text='', chips_per_row=2):
        QWidget.__init__(self)
        self._tag_chip_container = QWidget()
        self._tag_chip_layout = FlowLayout(self._tag_chip_container, h_spacing=8, v_spacing=8)
        self._tag_chip_selected_index = -1
        self._tag_manager_kbd_selected = False
        self._tag_manager_btn = _FakeTagManagerBtn(visible=True)
        self._context = context
        self._active_search_text = active_search_text
        self.tag_filter_requested = _FakeSignal()
        self.open_tag_manager_requested = _FakeSignal()
        self.remove_calls = []
        for tag in tags:
            chip = _TagChip(tag)
            chip.setFixedSize(50, 24)
            self._tag_chip_layout.addWidget(chip)
        # Force a real layout pass at a width that wraps to exactly chips_per_row per line —
        # _tag_chip_rows groups by chip.y(), which is meaningless before a layout pass runs.
        # FlowLayout's default contentsMargins() is 11px each side (Qt style default, not
        # explicitly overridden here — the real _rebuild_tag_chips DOES set (0,0,0,0), but
        # that doesn't affect the wrap math this harness needs, only absolute position), so
        # width must clear chips_per_row full columns (50 + 8 spacing, minus the trailing
        # spacing) plus both margins, with a few px of slack so it doesn't sit exactly on
        # the wrap boundary (verified against FlowLayout._do_layout's real wrap condition,
        # not assumed — see this file's own commit message / NOTES for the arithmetic).
        width = 11 + chips_per_row * 50 + (chips_per_row - 1) * 8 + 5 + 11
        self._tag_chip_container.setFixedWidth(width)
        self._tag_chip_container.resize(width, 400)
        self._tag_chip_layout.setGeometry(self._tag_chip_container.rect())

    def _on_remove_tag(self, tag):
        self.remove_calls.append(tag)


def _press(obj, key):
    ev = QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier)
    return obj._tag_chip_key_event(ev.key())


def test_down_from_nothing_selected_enters_first_chip(qapp):
    h = _TagChipHarness(["alpha", "beta", "gamma"])
    assert _press(h, Qt.Key.Key_Down) is True
    assert h._tag_chip_selected_index == 0


def test_other_keys_do_not_enter_grid_from_nothing_selected(qapp):
    h = _TagChipHarness(["alpha", "beta"])
    assert _press(h, Qt.Key.Key_Right) is False
    assert h._tag_chip_selected_index == -1


def test_left_right_move_within_a_row(qapp):
    tags = ["a", "b", "c", "d", "e"]
    h = _TagChipHarness(tags, chips_per_row=2)  # rows: [a,b] [c,d] [e]
    _press(h, Qt.Key.Key_Down)  # enter at chip 0 (a)
    assert h._tag_chip_selected_index == 0
    _press(h, Qt.Key.Key_Right)
    assert h._tag_chip_selected_index == 1  # b, same row
    _press(h, Qt.Key.Key_Left)
    assert h._tag_chip_selected_index == 0
    # Left at the first chip is a no-op (text field is deliberately not arrow-reachable)
    _press(h, Qt.Key.Key_Left)
    assert h._tag_chip_selected_index == 0


def test_right_wraps_reading_order_onto_next_row(qapp):
    tags = ["a", "b", "c", "d", "e"]
    h = _TagChipHarness(tags, chips_per_row=2)  # rows: [a,b] [c,d] [e]
    h._tag_chip_selected_index = 1  # b (last of row 0)
    h._tag_chips()[1].set_keyboard_selected(True)
    _press(h, Qt.Key.Key_Right)
    assert h._tag_chip_selected_index == 2  # c, first of row 1 — reading-order wrap


def test_left_wraps_reading_order_onto_previous_row(qapp):
    tags = ["a", "b", "c", "d", "e"]
    h = _TagChipHarness(tags, chips_per_row=2)  # rows: [a,b] [c,d] [e]
    h._tag_chip_selected_index = 2  # c (first of row 1)
    h._tag_chips()[2].set_keyboard_selected(True)
    _press(h, Qt.Key.Key_Left)
    assert h._tag_chip_selected_index == 1  # b, last of row 0 — reading-order wrap


def test_down_moves_to_same_column_next_row(qapp):
    tags = ["a", "b", "c", "d", "e"]
    h = _TagChipHarness(tags, chips_per_row=2)  # rows: [a,b] [c,d] [e]
    h._tag_chip_selected_index = 1  # b, column 1
    h._tag_chips()[1].set_keyboard_selected(True)
    _press(h, Qt.Key.Key_Down)
    assert h._tag_chip_selected_index == 3  # d, same column (1) on the next row


def test_down_clamps_to_shorter_row_length(qapp):
    tags = ["a", "b", "c", "d", "e"]
    h = _TagChipHarness(tags, chips_per_row=2)  # rows: [a,b] [c,d] [e] — last row has 1 item
    h._tag_chip_selected_index = 3  # d, column 1, row 1
    h._tag_chips()[3].set_keyboard_selected(True)
    _press(h, Qt.Key.Key_Down)
    assert h._tag_chip_selected_index == 4  # e — clamped to row 2's only column (0)


def test_up_moves_to_same_column_previous_row(qapp):
    tags = ["a", "b", "c", "d", "e"]
    h = _TagChipHarness(tags, chips_per_row=2)  # rows: [a,b] [c,d] [e]
    h._tag_chip_selected_index = 3  # d, column 1
    h._tag_chips()[3].set_keyboard_selected(True)
    _press(h, Qt.Key.Key_Up)
    assert h._tag_chip_selected_index == 1  # b, same column (1) on the row above


def test_up_at_row_zero_is_noop(qapp):
    tags = ["a", "b", "c"]
    h = _TagChipHarness(tags, chips_per_row=2)
    h._tag_chip_selected_index = 0
    h._tag_chips()[0].set_keyboard_selected(True)
    handled = _press(h, Qt.Key.Key_Up)
    assert handled is True  # still claimed, just does nothing
    assert h._tag_chip_selected_index == 0


def test_down_off_last_row_enters_tag_manager(qapp):
    tags = ["a", "b", "c", "d", "e"]
    h = _TagChipHarness(tags, chips_per_row=2)  # rows: [a,b] [c,d] [e]
    h._tag_chip_selected_index = 4  # e, last row
    h._tag_chips()[4].set_keyboard_selected(True)
    _press(h, Qt.Key.Key_Down)
    assert h._tag_chip_selected_index == -1
    assert h._tag_manager_kbd_selected is True


def test_right_off_last_chip_enters_tag_manager(qapp):
    tags = ["a", "b"]
    h = _TagChipHarness(tags)
    _press(h, Qt.Key.Key_Down)
    _press(h, Qt.Key.Key_Right)  # chip 1 (last)
    assert h._tag_chip_selected_index == 1
    _press(h, Qt.Key.Key_Right)  # off the end
    assert h._tag_chip_selected_index == -1
    assert h._tag_manager_kbd_selected is True


def test_right_off_last_chip_is_noop_when_tag_manager_hidden(qapp):
    tags = ["a"]
    h = _TagChipHarness(tags)
    h._tag_manager_btn = _FakeTagManagerBtn(visible=False)
    _press(h, Qt.Key.Key_Down)
    _press(h, Qt.Key.Key_Right)
    assert h._tag_chip_selected_index == 0  # stayed put — nowhere to go
    assert h._tag_manager_kbd_selected is False


def test_up_left_from_tag_manager_returns_to_last_chip(qapp):
    tags = ["a", "b", "c"]
    h = _TagChipHarness(tags)
    _press(h, Qt.Key.Key_Down)
    _press(h, Qt.Key.Key_Right)
    _press(h, Qt.Key.Key_Right)
    _press(h, Qt.Key.Key_Right)  # off the end -> tag manager
    assert h._tag_manager_kbd_selected is True
    _press(h, Qt.Key.Key_Up)
    assert h._tag_manager_kbd_selected is False
    assert h._tag_chip_selected_index == len(tags) - 1


def test_space_enter_on_tag_manager_emits_open_signal(qapp):
    h = _TagChipHarness(["a"])
    _press(h, Qt.Key.Key_Down)
    _press(h, Qt.Key.Key_Right)  # off the end -> tag manager
    assert h._tag_manager_kbd_selected is True
    _press(h, Qt.Key.Key_Space)
    assert len(h.open_tag_manager_requested.calls) == 1


def test_delete_removes_selected_chip_via_on_remove_tag(qapp):
    h = _TagChipHarness(["alpha", "beta"])
    _press(h, Qt.Key.Key_Down)
    _press(h, Qt.Key.Key_Right)
    assert h._tag_chip_selected_index == 1
    _press(h, Qt.Key.Key_Delete)
    assert h.remove_calls == ["beta"]


def test_space_enter_emits_filter_when_clickable_in_library_context(qapp):
    h = _TagChipHarness(["alpha"], context='library', active_search_text='')
    _press(h, Qt.Key.Key_Down)
    _press(h, Qt.Key.Key_Space)
    assert h.tag_filter_requested.calls == [("alpha",)]


def test_space_enter_is_noop_when_chip_is_inert_active_filter(qapp):
    # Matches the mouse's own inert-chip rule: a chip already the active library filter
    # (exact "#tag == active_search_text" match) does not re-emit tag_filter_requested.
    h = _TagChipHarness(["alpha"], context='library', active_search_text='#alpha')
    _press(h, Qt.Key.Key_Down)
    _press(h, Qt.Key.Key_Enter)
    assert h.tag_filter_requested.calls == []


def test_space_enter_is_noop_outside_library_context(qapp):
    h = _TagChipHarness(["alpha"], context='stats', active_search_text='')
    _press(h, Qt.Key.Key_Down)
    _press(h, Qt.Key.Key_Return)
    assert h.tag_filter_requested.calls == []


def test_digit_jumps_to_nth_chip(qapp):
    tags = ["a", "b", "c", "d", "e"]
    h = _TagChipHarness(tags)
    _press(h, Qt.Key.Key_3)
    assert h._tag_chip_selected_index == 2
    _press(h, Qt.Key.Key_1)
    assert h._tag_chip_selected_index == 0


def test_digit_beyond_tag_count_is_noop(qapp):
    h = _TagChipHarness(["a", "b"])
    handled = _press(h, Qt.Key.Key_5)
    assert handled is True  # still claimed (matches every other digit press)
    assert h._tag_chip_selected_index == -1


def test_digit_from_tag_manager_exits_back_to_grid(qapp):
    h = _TagChipHarness(["a", "b", "c"])
    _press(h, Qt.Key.Key_Down)
    _press(h, Qt.Key.Key_Right)
    _press(h, Qt.Key.Key_Right)
    _press(h, Qt.Key.Key_Right)  # off the end -> tag manager
    assert h._tag_manager_kbd_selected is True
    _press(h, Qt.Key.Key_2)
    assert h._tag_manager_kbd_selected is False
    assert h._tag_chip_selected_index == 1


def test_empty_grid_down_is_noop(qapp):
    h = _TagChipHarness([])
    assert _press(h, Qt.Key.Key_Down) is False
    assert h._tag_chip_selected_index == -1
