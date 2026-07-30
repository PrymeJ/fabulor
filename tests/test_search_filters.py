"""Search-filter operator grammar: parsing, the input validator, and end-to-end matching.

Covers the operator set as of 2026-07-30: `#tag`, `_title-prefix`, `@author`, `=year`, `>year`,
`<year`, and the two range orderings. Pure-function tests where possible; the end-to-end block
drives a real `BookModel` because the branch ORDER in `_apply_filter_and_sort` is load-bearing
(the range test must precede the bare-operator tests) and only an end-to-end run pins it.
"""

import pytest

from PySide6.QtGui import QValidator

from fabulor.ui.library import (
    BookModel,
    _YearFilterValidator,
    _is_incomplete_year_filter,
    _is_year_number,
    _parse_exact_year,
    _parse_year_range,
)
from fabulor.models.book import Book


def _mk(book_id, title, author, narrator, year):
    b = Book.__new__(Book)
    for key, val in dict(
        id=book_id, path=f"/books/{book_id}", title=title, author=author, narrator=narrator,
        year=year, progress=0.0, duration=1000, cover_path=None, last_played=None,
        folder_name_raw="",
    ).items():
        setattr(b, key, val)
    return b


# Chosen so every collision the operators exist to resolve is present:
#   - "1984" is both a TITLE (year 1949) and a YEAR (two other books)
#   - "James Baldwin" is both an AUTHOR and part of a TITLE
#   - The Odyssey / Meditations have negative and sub-1000 years
_LIBRARY = [
    _mk(1, "Giovanni's Room", "James Baldwin", "Kevin Free", 1956),
    _mk(2, "James Baldwin: A Biography", "David Leeming", "Bob Reader", 1994),
    _mk(3, "1984", "George Orwell", "Simon Prebble", 1949),
    _mk(4, "A History of 1984", "Some Historian", "Tim Reynolds", 1984),
    _mk(5, "Brave New World", "Aldous Huxley", "Simon Vance", 1984),
    _mk(6, "The Odyssey", "Homer", "Dan Stevens", -750),
    _mk(7, "Meditations", "Marcus Aurelius", "Robin Field", 180),
]


@pytest.fixture
def model():
    # No QApplication needed — BookModel is a QAbstractListModel with no widgets, and
    # _YearFilterValidator is a pure QValidator (mirrors test_library_shortcuts.py's approach).
    m = BookModel()
    m.set_books(list(_LIBRARY))
    return m


def _titles(model, text):
    """Run a filter and return the resulting titles, plus whether the field would go red."""
    model.filter_books(text.lower().strip())
    return ([model._filtered[i].title for i in range(len(model._filtered))],
            model.filter_empty)


# ── Parsers ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    (">2000<2010", (2000, 2010)),
    ("<2010>2000", (2000, 2010)),      # both operator orderings normalize the same
    ("<1984>1984", (1984, 1984)),      # degenerate range is ADMITTED (lo <= hi, not lo < hi)
    (">-500<-100", (-500, -100)),      # negative (BCE) years on both sides
    (">2010<2000", None),              # impossible range rejected
    (">2000<", None),                  # incomplete
    ("1984", None),
    ("=1984", None),                   # exact year is a different parser
])
def test_parse_year_range(text, expected):
    assert _parse_year_range(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("=1984", 1984),
    ("=-282", -282),                   # BCE
    ("=0", 0),
    ("=12345", None),                  # 5 digits rejected
    ("=", None),
    ("=abc", None),
    ("1984", None),                    # bare number is not an exact-year filter
])
def test_parse_exact_year(text, expected):
    assert _parse_exact_year(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("1984", True),
    ("-500", True),                    # the isdigit() bug: this used to be False
    ("0", True),
    ("12345", False),
    ("", False),
    ("-", False),
    ("abc", False),
])
def test_is_year_number(text, expected):
    assert _is_year_number(text) is expected


def test_negative_years_are_not_treated_as_text():
    """Regression: `str.isdigit()` is False for '-500', so every negative-year filter silently
    fell through to a text search. Same defect as the Year field's, fixed 2026-07-30."""
    assert _is_year_number("-500")
    assert _parse_exact_year("=-750") == -750
    assert _parse_year_range(">-1000<200") == (-1000, 200)


# ── Input validator (the 4-digit grammar cap) ────────────────────────────────────────

@pytest.fixture
def validator():
    return _YearFilterValidator()


def _state(validator, text):
    return validator.validate(text, 0)[0]


@pytest.mark.parametrize("text", ["", "d", "#tag", "_dune", "@feist", "tim g", "dune 1984"])
def test_validator_passes_non_year_filters_untouched(validator, text):
    """One validator sits on a field accepting EVERY filter type — it must only constrain
    strings already committed to being a year expression (leading <, > or =)."""
    assert _state(validator, text) == QValidator.State.Acceptable


@pytest.mark.parametrize("text", [
    "=", "=1", "=1984", "=-282", "=-1234",
    "<", "<2", "<2000", "<-500",
    ">2000<", ">2000<2010", "<1984>1984",
])
def test_validator_accepts_valid_year_expressions(validator, text):
    assert _state(validator, text) != QValidator.State.Invalid


@pytest.mark.parametrize("text", [
    "=19845",         # 5 digits
    "=-12345",        # 5 digits, negative
    "<20000",
    ">2000<20105",
    "=1984<",         # '=' has no range form — nothing may follow a complete exact year
    ">2000>",         # a repeated operator is never valid
    ">2000<2010x",
])
def test_validator_rejects(validator, text):
    assert _state(validator, text) == QValidator.State.Invalid


def test_minus_does_not_consume_a_digit_of_the_budget(validator):
    """A BCE year gets the same 4 digits a CE year does."""
    assert _state(validator, "=-1234") != QValidator.State.Invalid
    assert _state(validator, "=-12345") == QValidator.State.Invalid


# ── Incomplete-year neutrality ───────────────────────────────────────────────────────

@pytest.mark.parametrize("text", ["<", ">", "=", "<2", "<20", "=-", ">2010<", ">2010<20"])
def test_incomplete_year_filters_stay_neutral(text):
    """Year filters never go red; these transient states must not either. Whether '<50' is
    complete or a half-typed '<500' is undecidable from the input alone — see the docstring."""
    assert _is_incomplete_year_filter(text) is True


@pytest.mark.parametrize("text", ["dune", "#tag", "_d", "@feist", ">2010>"])
def test_complete_or_non_year_filters_are_not_incomplete(text):
    assert _is_incomplete_year_filter(text) is False


# ── End-to-end (pins branch ORDER in _apply_filter_and_sort) ─────────────────────────

def test_bare_text_searches_title_author_and_narrator(model):
    titles, red = _titles(model, "james baldwin")
    assert set(titles) == {"Giovanni's Room", "James Baldwin: A Biography"}
    assert red is False


def test_author_operator_resolves_the_title_collision(model):
    """The case '@' exists for: a bare name matches the biography ABOUT Baldwin as well as
    the novel BY him."""
    titles, red = _titles(model, "@james baldwin")
    assert titles == ["Giovanni's Room"]
    assert red is False


def test_author_operator_reddens_on_no_match(model):
    titles, red = _titles(model, "@nobody at all")
    assert red is True
    assert len(titles) == len(_LIBRARY)      # no-match falls back to the full list


def test_bare_year_digits_still_match_title_or_year(model):
    """Unchanged behaviour: a bare 4-digit number matches the year OR the title text."""
    titles, _ = _titles(model, "1984")
    assert set(titles) == {"1984", "A History of 1984", "Brave New World"}


def test_exact_year_operator_resolves_the_title_collision(model):
    """'=1984' drops the book TITLED 1984 (published 1949) and keeps the two published in 1984."""
    titles, _ = _titles(model, "=1984")
    assert set(titles) == {"A History of 1984", "Brave New World"}


def test_exact_year_agrees_with_the_degenerate_range(model):
    """'=1984' is the readable spelling of '<1984>1984' — they must return the same set."""
    exact, _ = _titles(model, "=1984")
    degenerate, _ = _titles(model, "<1984>1984")
    assert set(exact) == set(degenerate)


def test_range_branch_precedes_bare_operator_branch(model):
    """Order regression: '>1950<1990' must parse as a RANGE. If the bare '>' branch were tested
    first it would fail _is_year_number('1950<1990') and fall through to a text search."""
    titles, _ = _titles(model, ">1950<1990")
    assert set(titles) == {"Giovanni's Room", "A History of 1984", "Brave New World"}
    # And the falling-through-to-text outcome it must NOT produce (no title contains the
    # literal string, so a text search would redden and show everything).
    assert len(titles) < len(_LIBRARY)


@pytest.mark.parametrize("text,expected", [
    (">1990", {"James Baldwin: A Biography"}),
    ("<0", {"The Odyssey"}),
    ("<200", {"Meditations", "The Odyssey"}),
    ("=-750", {"The Odyssey"}),
    (">-1000<200", {"Meditations", "The Odyssey"}),
])
def test_year_filters_including_bce(model, text, expected):
    titles, _ = _titles(model, text)
    assert set(titles) == expected


def test_year_filters_never_redden(model):
    """Every year branch sets _filter_no_match = False, deliberately — a year filter that
    matches nothing shows the full list without the red field."""
    titles, red = _titles(model, "=1111")
    assert red is False
    assert len(titles) == len(_LIBRARY)


def test_title_prefix_operator(model):
    titles, red = _titles(model, "_a history")
    assert titles == ["A History of 1984"]
    assert red is False


def test_title_prefix_reddens_on_no_match(model):
    _, red = _titles(model, "_zzz")
    assert red is True


def test_empty_filter_shows_everything(model):
    titles, red = _titles(model, "")
    assert len(titles) == len(_LIBRARY)
    assert red is False


# ── Persistence classification ───────────────────────────────────────────────────────

@pytest.mark.parametrize("text,kind", [
    ("#malazan", "tag"),
    ("#", "tag"),
    ("=1984", "year"),
    ("=-282", "year"),
    (">2000", "year"),
    ("<2000", "year"),
    ("<-500", "year"),
    (">2000<2010", "year"),
    ("<1984>1984", "year"),
    ("@feist", "text"),       # field-scoped, but still a text search
    ("_dune", "text"),
    ("dune", "text"),
])
def test_classify_filter(text, kind):
    """Drives which "Persist search filter" toggle governs the string. '=1984' and negative
    years were misfiled as 'text' before 2026-07-30, so the user's year preference was ignored
    for them."""
    from fabulor.ui.library import LibraryPanel
    assert LibraryPanel._classify_filter(text) == kind
