"""Behavior contract for CoverPanel's keyboard navigation (select_adjacent / activate_selected /
delete_selected / click_fit_button / has_selection), added alongside Book Detail's Cover-tab
shortcuts.

The navigable sequence is: cover 0, cover 1, ..., cover N-1, then the '+' add-cover slot IF
it's visible (fewer than 4 custom covers) — clamped, no wrap. With exactly 4 covers (the '+'
slot hidden), Down from the last cover wraps to the first NON-active cover instead of no-op'ing
(landing back on the cover already shown as active would be a wasted, indistinguishable wrap).

'+' selection is a plain boolean (_add_btn_selected) + a QSS dynamic property (kbdSelected),
NOT real Qt focus — confirmed live that granting the QPushButton real focus broke
BookDetailPanel's own Left/Right tab-cycling (a QPushButton with real focus starts owning key
events itself). CoverPanel is constructed directly (only needs `db` at construction time, not
a live connection until load_book) rather than faked, since its navigation logic is the thing
under test here — unlike BookDetailPanel's dispatch tests (test_book_detail_panel_keys.py),
which fake CoverPanel entirely to isolate keyPressEvent's routing.
"""
import pytest
from PySide6.QtWidgets import QApplication

from fabulor.ui.cover_panel import CoverPanel


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _cover(id_, locked=False, active=False, sort_order=0):
    return {
        "id": id_, "file_path": "", "is_locked": int(locked), "is_active": int(active),
        "fit_mode": "fit", "sort_order": sort_order,
    }


def _panel_with_covers(covers, add_visible, selected=None):
    panel = CoverPanel(db=None)
    # QWidget.isVisible() reflects EFFECTIVE on-screen visibility (the whole ancestor chain
    # must be shown), not just this widget's own setVisible() flag — confirmed live: an
    # unshown CoverPanel makes _add_btn.isVisible() report False regardless of
    # setVisible(True). select_adjacent's real production logic reads .isVisible() (matching
    # how it's actually used live, where the panel IS shown), so tests need panel.show() too.
    panel.show()
    panel._covers = list(covers)
    panel._add_btn.setVisible(add_visible)
    panel._selected = selected
    return panel


# ── Cover-to-cover stepping (no '+' involved) ────────────────────────────────────

def test_down_steps_through_covers_in_order(qapp):
    covers = [_cover(1), _cover(2), _cover(3)]
    panel = _panel_with_covers(covers, add_visible=True, selected=covers[0])
    panel.select_adjacent(1)
    assert panel._selected["id"] == 2
    panel.select_adjacent(1)
    assert panel._selected["id"] == 3


def test_up_steps_backward_and_clamps_at_first(qapp):
    covers = [_cover(1), _cover(2), _cover(3)]
    panel = _panel_with_covers(covers, add_visible=True, selected=covers[0])
    panel.select_adjacent(-1)
    assert panel._selected["id"] == 1   # clamped, no wrap


def test_no_selection_yet_down_selects_first(qapp):
    covers = [_cover(1), _cover(2)]
    panel = _panel_with_covers(covers, add_visible=True, selected=None)
    panel.select_adjacent(1)
    assert panel._selected["id"] == 1


def test_no_covers_and_add_hidden_is_a_total_noop(qapp):
    panel = _panel_with_covers([], add_visible=False, selected=None)
    panel.select_adjacent(1)
    panel.select_adjacent(-1)
    assert panel._selected is None
    assert panel._add_btn_selected is False


# ── Reaching and leaving the '+' slot (< 4 covers) ───────────────────────────────

def test_down_past_last_cover_selects_add_button_when_visible(qapp):
    covers = [_cover(1), _cover(2)]
    panel = _panel_with_covers(covers, add_visible=True, selected=covers[-1])
    panel.select_adjacent(1)
    assert panel._add_btn_selected is True
    assert panel._selected is None   # cleared when '+' becomes the target
    assert panel._add_btn.property("kbdSelected") is True


def test_no_covers_down_selects_add_button_directly(qapp):
    panel = _panel_with_covers([], add_visible=True, selected=None)
    panel.select_adjacent(1)
    assert panel._add_btn_selected is True


def test_down_from_add_button_is_a_noop(qapp):
    covers = [_cover(1)]
    panel = _panel_with_covers(covers, add_visible=True, selected=None)
    panel._set_add_button_selected(True)
    panel.select_adjacent(1)
    assert panel._add_btn_selected is True   # unchanged — clamped, no wrap past '+'


def test_up_from_add_button_returns_to_last_cover(qapp):
    covers = [_cover(1), _cover(2), _cover(3)]
    panel = _panel_with_covers(covers, add_visible=True, selected=None)
    panel._set_add_button_selected(True)
    panel.select_adjacent(-1)
    assert panel._add_btn_selected is False
    assert panel._selected["id"] == 3
    assert panel._add_btn.property("kbdSelected") is False


def test_up_from_add_button_with_zero_covers_is_a_noop(qapp):
    panel = _panel_with_covers([], add_visible=True, selected=None)
    panel._set_add_button_selected(True)
    panel.select_adjacent(-1)
    assert panel._add_btn_selected is True   # nothing to return to — stays on '+'


# ── The 4-cover wrap, skipping the active cover ──────────────────────────────────

def test_four_covers_add_hidden_down_from_last_wraps_to_first_non_active(qapp):
    covers = [
        _cover(1, locked=True, active=True, sort_order=0),
        _cover(2, sort_order=1),
        _cover(3, sort_order=2),
        _cover(4, sort_order=3),
    ]
    panel = _panel_with_covers(covers, add_visible=False, selected=covers[-1])
    panel.select_adjacent(1)
    assert panel._selected["id"] == 2   # first non-active, NOT the active cover (id 1)
    assert panel._add_btn_selected is False


def test_four_covers_wrap_skips_active_even_if_active_is_not_first(qapp):
    covers = [
        _cover(1, sort_order=0),
        _cover(2, locked=True, active=True, sort_order=1),
        _cover(3, sort_order=2),
        _cover(4, sort_order=3),
    ]
    panel = _panel_with_covers(covers, add_visible=False, selected=covers[-1])
    panel.select_adjacent(1)
    assert panel._selected["id"] == 1   # first non-active in list order, skips id 2


def test_normal_stepping_still_visits_the_active_cover_along_the_way(qapp):
    # The skip-active rule is ONLY for the wrap boundary — regular step-by-step Up/Down must
    # still land ON the active cover like any other, per the docstring's explicit scope note.
    covers = [
        _cover(1, sort_order=0),
        _cover(2, locked=True, active=True, sort_order=1),
        _cover(3, sort_order=2),
    ]
    panel = _panel_with_covers(covers, add_visible=False, selected=covers[0])
    panel.select_adjacent(1)
    assert panel._selected["id"] == 2   # lands on the active cover normally mid-list


# ── activate_selected / delete_selected / click_fit_button route correctly for '+' ──

def test_activate_selected_on_add_button_calls_on_add_cover(qapp, monkeypatch):
    panel = _panel_with_covers([_cover(1)], add_visible=True, selected=None)
    panel._set_add_button_selected(True)
    calls = []
    monkeypatch.setattr(panel, "_on_add_cover", lambda: calls.append(1))
    panel.activate_selected()
    assert calls == [1]


def test_activate_selected_on_cover_calls_on_thumb_set_active(qapp, monkeypatch):
    covers = [_cover(1)]
    panel = _panel_with_covers(covers, add_visible=True, selected=covers[0])
    calls = []
    monkeypatch.setattr(panel, "_on_thumb_set_active", lambda cid: calls.append(cid))
    panel.activate_selected()
    assert calls == [1]


def test_delete_selected_is_a_noop_on_add_button(qapp, monkeypatch):
    panel = _panel_with_covers([_cover(1)], add_visible=True, selected=None)
    panel._set_add_button_selected(True)
    calls = []
    monkeypatch.setattr(panel, "_on_thumb_delete", lambda cid: calls.append(cid))
    panel.delete_selected()
    assert calls == []


def test_click_fit_button_is_a_noop_on_add_button(qapp):
    panel = _panel_with_covers([_cover(1)], add_visible=True, selected=None)
    panel._set_add_button_selected(True)
    panel.click_fit_button("top")   # must not raise, must not check a fit button
    assert panel._fit_buttons["top"].isChecked() is False


def test_has_selection_true_for_add_button_too(qapp):
    panel = _panel_with_covers([], add_visible=True, selected=None)
    assert panel.has_selection() is False
    panel._set_add_button_selected(True)
    assert panel.has_selection() is True
