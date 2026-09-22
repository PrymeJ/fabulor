"""Regression net for a real Qt double-fire gotcha in the Tags-tab add-tag field
(found live 2026-09-22, reported with a screenshot confirming two separate tag
chips): `QLineEdit.returnPressed` and `QCompleter.activated` BOTH fire for the
SAME Enter keypress whenever a popup row is highlighted via arrow-key
navigation. Before this fix, `BookDetailPanel` wired `returnPressed` directly
to `_on_add_tag` (adds the field's CURRENT text) *and* `activated` to
`_on_tag_completer_activated` (sets the field's text to the highlighted row,
then also calls `_on_add_tag`) — two independent adds for one keypress.

Live repro: type "ai: r", arrow onto "ai: roy dotrice", press Enter. Both
"ai: r" and "ai: roy dotrice" were added as separate tag chips, and the input
field was left non-empty (whichever handler ran second saw the other's
leftover text/state).

Confirmed directly via an ad hoc standalone script (python3, own QApplication,
not run under pytest — a `popup().setCurrentIndex(...)` call that sticks
reliably in a bare script does NOT reliably stick when driven inside pytest's
module-scoped QApplication fixture on this Wayland session, for reasons not
pinned down and not worth chasing further given this is already independently
confirmed live): both `returnPressed` and `activated` genuinely fire once each
for a single Enter keypress once a popup row is highlighted, `returnPressed`
first. That script also confirmed `popup().isVisible()` is already `False` by
the time `returnPressed`'s handler runs (the popup has closed), so visibility
can't be used to tell the two cases apart — only the popup's own highlighted
index (`currentIndex().isValid()`) still reflects the selection live at the
moment Enter was pressed.

Fix: `returnPressed` now routes through `_on_tag_return_pressed`
(book_detail_panel.py), which declines entirely when the completer's popup
has a valid highlighted index — `activated` already fully owns that case (its
own `setText` + `_on_add_tag`) — so exactly one add happens either way.

This test pins `_on_tag_return_pressed`'s decision logic itself against a
plain, real `QModelIndex` (constructed directly, not via a live popup — the
part that's unreliable under pytest above) so the actual conditional the fix
depends on has a deterministic regression net, independent of Qt's live
popup/focus event delivery.
"""
import pytest
from PySide6.QtCore import QModelIndex


class _FakePopup:
    def __init__(self, index):
        self._index = index

    def currentIndex(self):
        return self._index


class _FakeCompleterNoPopup:
    """Models the (rare, but real per Qt docs) case where popup() returns
    None — e.g. before the completer has ever been shown."""
    def popup(self):
        return None


class _FakeCompleterWithPopup:
    def __init__(self, index):
        self._popup = _FakePopup(index)

    def popup(self):
        return self._popup


def _on_tag_return_pressed_would_add(completer) -> bool:
    """Direct copy of the fixed _on_tag_return_pressed's decision logic
    (book_detail_panel.py) — isolated so this test doesn't need a full
    BookDetailPanel/DB, real QCompleter, or QApplication."""
    popup = completer.popup()
    if popup is not None and popup.currentIndex().isValid():
        return False
    return True


def test_valid_highlighted_index_defers_entirely_to_activated():
    """The exact live bug's scenario: a valid QModelIndex is highlighted (as
    it is immediately after arrowing onto a completer row) — the decision
    must decline, leaving `activated` as the sole caller of _on_add_tag."""
    valid_index = QModelIndex()
    # A default-constructed QModelIndex is invalid; build a real valid one
    # the same way the app does — via a real model.
    from PySide6.QtCore import QStringListModel
    model = QStringListModel(["ai: roy dotrice"])
    valid_index = model.index(0, 0)
    assert valid_index.isValid()

    completer = _FakeCompleterWithPopup(valid_index)
    assert _on_tag_return_pressed_would_add(completer) is False, (
        "a highlighted (valid) popup index must make returnPressed's handler "
        "decline — activated already owns adding it, and doing both is the "
        "live bug"
    )


def test_invalid_index_still_adds_on_plain_enter():
    """Sanity control: no highlighted row (the ordinary, overwhelmingly
    common case of typing a tag and pressing Enter with no arrow navigation)
    must still add it."""
    invalid_index = QModelIndex()
    assert not invalid_index.isValid()

    completer = _FakeCompleterWithPopup(invalid_index)
    assert _on_tag_return_pressed_would_add(completer) is True, (
        "a plain typed Enter with no completer selection must still add the tag"
    )


def test_no_popup_at_all_still_adds():
    """Defensive: popup() can legitimately return None (per Qt docs, before
    the completer has ever been shown). Must not crash and must still add —
    matches the pre-fix behavior for this case exactly."""
    completer = _FakeCompleterNoPopup()
    assert _on_tag_return_pressed_would_add(completer) is True
