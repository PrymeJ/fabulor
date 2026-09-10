"""db.has_sprint_data — drives Sprint panel's "Reset all sprint data" dim-when-empty
state (2026-09-10 live ask). Pinned separately from the button/UI wiring since this is
the one piece that's meaningfully unit-testable in isolation (SprintPanel has no db
reference by design; the query itself is what needs to stay correct)."""
from fabulor.db import LibraryDB


def test_has_sprint_data_false_when_empty(tmp_path):
    db = LibraryDB(tmp_path / "library.db")
    assert db.has_sprint_data() is False


def test_has_sprint_data_true_after_an_attempt(tmp_path):
    db = LibraryDB(tmp_path / "library.db")
    db.record_sprint_attempt()
    assert db.has_sprint_data() is True


def test_has_sprint_data_true_after_a_completed_session(tmp_path):
    db = LibraryDB(tmp_path / "library.db")
    db.record_sprint_session(600)
    assert db.has_sprint_data() is True


def test_has_sprint_data_false_again_after_reset(tmp_path):
    db = LibraryDB(tmp_path / "library.db")
    db.record_sprint_attempt()
    db.record_sprint_session(600)
    assert db.has_sprint_data() is True

    db.reset_sprint_stats()

    assert db.has_sprint_data() is False
