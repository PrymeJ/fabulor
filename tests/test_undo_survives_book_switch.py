"""Regression net for the 12th bug in the EOF/book-switch investigation family
(found live 2026-09-22, immediately after the 11th): a `Player`-level Undo
anchor (`_undo_pos`) armed on one book silently survived a switch to a
DIFFERENT book, with the undo overlay still visible. Clicking it then called
`player.undo_seek()` against the NEW book's now-loaded file, seeking it to
the OLD book's anchored position.

Live report: "Scrub to make Undo appear, switch to another book, Undo is
still there. Click on it, it takes the new book to the previous book's
anchored percentage."

Root cause: `_on_book_selected_from_library` (app.py) already clears several
other per-book transients at switch time — `_last_pause_timestamp` (smart
rewind, 2026-09-16) and the sprint panel (2026-08-11) — with an explicit
comment each time explaining that per-book state must not leak into the next
book. `player._undo_pos` was the one per-book transient this teardown never
touched, so it (and the visible overlay button referencing it) rode straight
through into the next book's session.

Fix: `_on_book_selected_from_library` now also dismisses the undo overlay
(if showing) and clears `player._undo_pos` unconditionally, at the same
point as the other per-book teardown, before `_switch.begin(...)` runs.

These tests drive `Player.undo_seek` directly (no mpv/QApplication) to pin
the underlying mechanism: a cleared `_undo_pos` makes `undo_seek()` a
guaranteed no-op, regardless of which book is loaded when it's later
clicked.
"""
from fabulor.player import Player


class _FakeInstance:
    def __init__(self):
        self.seek_calls = []

    def command_async(self, *a):
        self.seek_calls.append(a)

    def terminate(self):
        pass

    def wait_for_shutdown(self):
        pass


def make_player():
    return Player(db=None, config=None)


def test_undo_seek_is_a_noop_once_undo_pos_is_cleared():
    """The exact fix under test: clearing _undo_pos (as the book-switch
    teardown now does) makes a later undo_seek() do nothing, even though the
    player still has a live instance (the new book's)."""
    p = make_player()
    p.instance = _FakeInstance()

    # Anchor an undo on the OUTGOING book, as a real scrub would.
    p.save_seek_position(old_pos=0.0, new_pos=1800.0, duration_limit=3, threshold=60.0)
    assert p._undo_pos == 0.0

    # Book-switch teardown clears the stale anchor before the new book loads.
    p._undo_pos = None

    # A stale click on the still-visible-until-just-now overlay (or any other
    # path that still calls undo_seek) must be inert against the new book.
    p.undo_seek()
    assert p.instance.seek_calls == [], (
        "undo_seek() issued a seek against the new book using the old "
        "book's stale anchor — the exact live corruption this fix closes."
    )


def test_undo_seek_without_the_fix_would_apply_the_stale_anchor_to_the_new_instance():
    """Negative control confirming the bug mechanism is real: WITHOUT clearing
    _undo_pos, undo_seek() happily seeks whatever instance is currently
    attached to the anchor captured against a previous, different book."""
    p = make_player()
    p.instance = _FakeInstance()

    p.save_seek_position(old_pos=0.0, new_pos=1800.0, duration_limit=3, threshold=60.0)
    assert p._undo_pos == 0.0

    # Simulate a book switch that reused the same Player object (as the real
    # app does) WITHOUT clearing _undo_pos — the pre-fix behavior.
    p.instance = _FakeInstance()  # "new book" loaded, fresh mpv instance

    p.undo_seek()
    assert len(p.instance.seek_calls) == 1, (
        "expected the stale anchor to be applied against the new instance — "
        "this pins the bug mechanism itself, not the fix"
    )


def test_undo_pos_survives_terminate_demonstrating_why_an_explicit_clear_is_needed():
    """Player.terminate() (used by book removal) only nulls `instance` — it
    does not clear `_undo_pos`. Confirms clearing it can't be left implicit
    to any existing teardown path and must be done explicitly at the
    book-switch site (mirrors the smart-rewind-timestamp/sprint clears)."""
    p = make_player()
    p.instance = _FakeInstance()
    p.save_seek_position(old_pos=0.0, new_pos=500.0, duration_limit=3, threshold=60.0)
    assert p._undo_pos == 0.0

    p.terminate()
    assert p._undo_pos == 0.0, "terminate() does not clear _undo_pos by itself"
