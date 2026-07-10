"""Decision-table for the Library sort-field / view-mode keyboard shortcuts, and for the
List-mode keyboard title/author expand (Left/Right on the keyboard-selected row).

The keys are handled inside LibraryPanel._list_key (only while the book list has focus, not
the search field). The branch DECISIONS are factored into small methods/functions —
`_apply_sort_shortcut` / `_apply_view_mode_shortcut` / `_next_list_expand_field` — so they can
be pinned here without standing up the whole panel + QApplication.

Following tests/test_panel_exclusion.py's pattern: bind the REAL unbound methods against a
tiny fake `self` that supplies only the combos (and `_toggle_sort_direction`) they read, so any
future change to the branch logic is caught. The end-to-end key routing (autorepeat guard,
consume-vs-fall-through, focus-scoping, and the paint-time synthetic-hover_pos wiring in
_paint_list_row) is Qt-event-dispatch/paint behavior verified live, per the project rule that
live timing/focus behavior is ground truth.
"""
import pytest
from PySide6.QtCore import Qt

from fabulor.ui.library import (
    LibraryPanel, VIEW_MODES, _initial_list_expand_field, _next_list_expand_field,
)


# ── Fakes ────────────────────────────────────────────────────────────────────

class _FakeCombo:
    """Minimal stand-in for a _ThemedComboBox: an ordered list of data keys plus a current
    index. Mirrors the QComboBox methods the shortcut methods actually call."""
    def __init__(self, data_keys, current):
        self._data = list(data_keys)
        self._current = self._data.index(current) if current in self._data else -1

    def findData(self, key):
        return self._data.index(key) if key in self._data else -1

    def currentData(self):
        return self._data[self._current] if 0 <= self._current < len(self._data) else None

    def currentIndex(self):
        return self._current

    def setCurrentIndex(self, i):
        self._current = i


class _FakeSortHost:
    """Supplies exactly what _apply_sort_shortcut reads off self."""
    def __init__(self, data_keys, current):
        self.sort_combo = _FakeCombo(data_keys, current)
        self.toggled = 0
        # _apply_sort_shortcut references the class constant via self.
        self._SORT_KEY_SHORTCUTS = LibraryPanel._SORT_KEY_SHORTCUTS

    def _toggle_sort_direction(self):
        self.toggled += 1


class _FakeViewHost:
    """Supplies exactly what _apply_view_mode_shortcut reads off self."""
    def __init__(self, current_index):
        # style_combo indices == VIEW_MODES order; data keys are the mode strings.
        self.style_combo = _FakeCombo([k for k, _ in VIEW_MODES],
                                      VIEW_MODES[current_index][0])
        self._VIEW_MODE_SHORTCUTS = LibraryPanel._VIEW_MODE_SHORTCUTS


def _apply_sort(host, key):
    return LibraryPanel._apply_sort_shortcut(host, key)


def _apply_view(host, key):
    return LibraryPanel._apply_view_mode_shortcut(host, key)


# Full set of data keys when every conditional field (Progress, Finished) is present.
_ALL_SORT_KEYS = ["Progress", "Title", "Author", "Last Played", "Duration", "Year", "Finished"]
# Base set — no Progress, no Finished (fresh library, nothing played/finished).
_BASE_SORT_KEYS = ["Title", "Author", "Last Played", "Duration", "Year"]


# ── Constant-dict shape ──────────────────────────────────────────────────────

def test_sort_shortcut_letters_map_to_expected_data_keys():
    assert LibraryPanel._SORT_KEY_SHORTCUTS == {
        Qt.Key.Key_P: "Progress",
        Qt.Key.Key_T: "Title",
        Qt.Key.Key_A: "Author",
        Qt.Key.Key_R: "Last Played",   # 'r' = Recent, combo data key "Last Played"
        Qt.Key.Key_D: "Duration",
        Qt.Key.Key_Y: "Year",
        Qt.Key.Key_F: "Finished",
    }


def test_view_mode_digits_map_1to1_onto_view_modes_order():
    assert LibraryPanel._VIEW_MODE_SHORTCUTS == {
        Qt.Key.Key_1: 0, Qt.Key.Key_2: 1, Qt.Key.Key_3: 2,
        Qt.Key.Key_4: 3, Qt.Key.Key_5: 4,
    }
    # digit N → index N-1 → the expected mode key, by row count.
    expected = ["1 per row", "2 per row", "3 per row", "Square", "List"]
    for i, mode_key in enumerate(expected):
        assert VIEW_MODES[i][0] == mode_key
        assert LibraryPanel._VIEW_MODE_SHORTCUTS[getattr(Qt.Key, f"Key_{i+1}")] == i


# ── Sort-key branch decisions ────────────────────────────────────────────────

def test_sort_key_inactive_field_switches_via_combo():
    # Currently on Title; press 'a' (Author) → combo moves to Author, no direction toggle.
    host = _FakeSortHost(_ALL_SORT_KEYS, current="Title")
    _apply_sort(host, Qt.Key.Key_A)
    assert host.sort_combo.currentData() == "Author"
    assert host.toggled == 0


def test_sort_key_active_field_toggles_direction():
    # Currently on Author; press 'a' (Author) again → toggle, combo unchanged.
    host = _FakeSortHost(_ALL_SORT_KEYS, current="Author")
    _apply_sort(host, Qt.Key.Key_A)
    assert host.sort_combo.currentData() == "Author"
    assert host.toggled == 1


def test_sort_key_recent_letter_maps_to_last_played():
    host = _FakeSortHost(_ALL_SORT_KEYS, current="Title")
    _apply_sort(host, Qt.Key.Key_R)
    assert host.sort_combo.currentData() == "Last Played"


def test_sort_key_absent_progress_is_noop():
    # Base library (no Progress entry). Press 'p' → nothing changes, no toggle.
    host = _FakeSortHost(_BASE_SORT_KEYS, current="Title")
    _apply_sort(host, Qt.Key.Key_P)
    assert host.sort_combo.currentData() == "Title"
    assert host.toggled == 0


def test_sort_key_absent_finished_is_noop():
    host = _FakeSortHost(_BASE_SORT_KEYS, current="Title")
    _apply_sort(host, Qt.Key.Key_F)
    assert host.sort_combo.currentData() == "Title"
    assert host.toggled == 0


def test_sort_key_repeated_active_press_keeps_toggling():
    # asc→desc→asc→desc… never sticks or skips: each active-field press is one toggle.
    host = _FakeSortHost(_ALL_SORT_KEYS, current="Title")
    for _ in range(4):
        _apply_sort(host, Qt.Key.Key_T)
    assert host.toggled == 4
    assert host.sort_combo.currentData() == "Title"


# ── View-mode branch decisions ───────────────────────────────────────────────

@pytest.mark.parametrize("digit_key,target_idx", [
    (Qt.Key.Key_1, 0), (Qt.Key.Key_2, 1), (Qt.Key.Key_3, 2),
    (Qt.Key.Key_4, 3), (Qt.Key.Key_5, 4),
])
def test_view_mode_switch_selects_target_index(digit_key, target_idx):
    # Start on a mode that isn't the target, press the digit → combo moves to target index.
    start = (target_idx + 1) % len(VIEW_MODES)
    host = _FakeViewHost(current_index=start)
    _apply_view(host, digit_key)
    assert host.style_combo.currentIndex() == target_idx


def test_view_mode_already_active_is_noop():
    # On Square (index 3); press '4' (Square) → index unchanged, explicit no-op.
    host = _FakeViewHost(current_index=3)
    _apply_view(host, Qt.Key.Key_4)
    assert host.style_combo.currentIndex() == 3


# ── List-mode keyboard title/author expand ───────────────────────────────────
#
# Reproduces the three reference rows directly against the pure functions — no Qt paint/widget
# needed. _initial_list_expand_field gives the state a row starts at the moment it BECOMES the
# keyboard selection (before any Left/Right). _next_list_expand_field's `current_field` is the
# row's state BEFORE the press; it returns the state AFTER. Returning the same value as
# current_field is the no-op signal (covers both "already there" and the short-field guard) —
# see LibraryPanel._apply_list_expand_shortcut, which detects the no-op this same way. This is
# a 1- or 2-state machine per row, NOT a 3-state default/title/author cycle: which states are
# reachable (and where the row starts) depends on which fields are actually long.

def test_initial_state_is_title_when_title_long():
    assert _initial_list_expand_field(title_elided=True) == "title"


def test_initial_state_is_default_when_title_short():
    assert _initial_list_expand_field(title_elided=False) is None


def test_both_fields_short_left_and_right_are_noop():
    # "Titus Groan" / "Mervyn Peake" — neither field is truncated. Starts at default; every
    # press is a no-op since neither field can ever expand.
    assert _initial_list_expand_field(title_elided=False) is None
    assert _next_list_expand_field(Qt.Key.Key_Left,  None, title_elided=False, author_elided=False) is None
    assert _next_list_expand_field(Qt.Key.Key_Right, None, title_elided=False, author_elided=False) is None


def test_long_title_short_author_sequence():
    # "There Are Rivers in the Sky" / "Elif Shafak" — title truncated, author not. Starts
    # title-expanded (not default) the moment the row is keyboard-selected.
    te, ae = True, False
    f = _initial_list_expand_field(te)
    assert f == "title"
    # Right: title moves back to its place (default) — author never expands (too short).
    f = _next_list_expand_field(Qt.Key.Key_Right, f, te, ae)
    assert f is None
    # Right again (default, author short): no-op.
    assert _next_list_expand_field(Qt.Key.Key_Right, f, te, ae) is None
    # Left (from default): title expands again.
    f = _next_list_expand_field(Qt.Key.Key_Left, f, te, ae)
    assert f == "title"
    # Left again: already there, no-op.
    assert _next_list_expand_field(Qt.Key.Key_Left, f, te, ae) == "title"


def test_short_title_long_author_sequence():
    # Short title, long author — starts at default (title isn't long, so nothing pre-expands).
    te, ae = False, True
    f = _initial_list_expand_field(te)
    assert f is None
    # Right: author expands.
    f = _next_list_expand_field(Qt.Key.Key_Right, f, te, ae)
    assert f == "author"
    # Right again: already there, no-op.
    assert _next_list_expand_field(Qt.Key.Key_Right, f, te, ae) == "author"
    # Left (from author-expanded): author shrinks back to default.
    f = _next_list_expand_field(Qt.Key.Key_Left, f, te, ae)
    assert f is None
    # Left again (default, title short): no-op.
    assert _next_list_expand_field(Qt.Key.Key_Left, f, te, ae) is None


def test_long_title_long_author_sequence():
    # "This Is How You Lose the Time War" / "Amal El-Mohtar, Max Gladstone" — both truncated.
    # Starts title-expanded. Right/Left TOGGLE directly between title and author — default
    # (None) is never reached again once both fields are long.
    te, ae = True, True
    f = _initial_list_expand_field(te)
    assert f == "title"
    f = _next_list_expand_field(Qt.Key.Key_Right, f, te, ae)  # title -> author (not default)
    assert f == "author"
    f = _next_list_expand_field(Qt.Key.Key_Left, f, te, ae)   # author -> title (not default)
    assert f == "title"
    f = _next_list_expand_field(Qt.Key.Key_Right, f, te, ae)  # title -> author again
    assert f == "author"
    f = _next_list_expand_field(Qt.Key.Key_Right, f, te, ae)  # already at author: no-op
    assert f == "author"
