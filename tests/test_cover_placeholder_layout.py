"""No-cover placeholder title/author layout (ui/cover_placeholder_layout.py).

Pure logic with injected fakes — no QApplication. Fake width: a fixed px per
character, with a wider value for "W"/"M" so wide-glyph cases are exercised.
The last two tests use the real bundled fonts and skip if no
QGuiApplication can be created.
"""
import logging
import os

import pytest

from fabulor.ui import cover_placeholder_layout as L
from fabulor.ui.cover_placeholder_layout import (
    ELLIPSIS, FALLBACK_FAMILY, LayoutState, PlaceholderLayoutCache,
    compute_placeholder_layout, pick_font,
)

MAX = 100
PX = 10   # per normal char → 10 chars per line


class FakeWidth:
    def __init__(self):
        self.calls = 0

    def __call__(self, text, family, role):
        self.calls += 1
        return sum(16 if ch in "WM" else PX for ch in text)


def latin_only(family, ch):
    """Primaries support Latin incl. Latin Extended; only the fallback does
    Cyrillic."""
    if "Ѐ" <= ch <= "ӿ":
        return family == FALLBACK_FAMILY
    return True


def layout(title, author, tw=None):
    return compute_placeholder_layout(title, author, MAX, tw or FakeWidth(), latin_only)


def width(s):
    return FakeWidth()(s, "", "")


def test_short_title_and_author_is_one_line():
    lay = layout("Dune", "Frank Herbert")
    assert lay.title_lines == ("Dune",)
    assert lay.state is LayoutState.ONE_LINE_TITLE
    assert lay.author_text.startswith("FRANK")


def test_author_upper_cased_when_it_fits():
    lay = layout("Dune", "Herbert")
    assert lay.author_text == "HERBERT"


def test_title_wrapping_to_exactly_two_lines():
    lay = layout("aaaa bbbb cccc dddd", "")
    assert lay.state is LayoutState.TWO_LINE_TITLE
    assert lay.title_lines == ("aaaa bbbb", "cccc dddd")
    assert not any(ELLIPSIS in line for line in lay.title_lines)


def test_title_needing_three_lines_elides_line_two():
    lay = layout("aaaa bbbb cccc dddd eeee ffff", "")
    assert lay.state is LayoutState.TWO_LINE_TITLE
    assert lay.title_lines[0] == "aaaa bbbb"
    assert lay.title_lines[1].endswith(ELLIPSIS)
    assert width(lay.title_lines[1]) <= MAX


def test_single_huge_word_is_elided():
    lay = layout("Supercalifragilisticexpialidocious", "")
    assert len(lay.title_lines) == 1
    assert lay.title_lines[0].endswith(ELLIPSIS)
    assert width(lay.title_lines[0]) <= MAX


def test_huge_first_word_then_more_words():
    lay = layout("Supercalifragilistic is long", "")
    assert lay.state is LayoutState.TWO_LINE_TITLE
    assert lay.title_lines[0].endswith(ELLIPSIS)
    assert lay.title_lines[1] == "is long"


def test_ellipsis_alone_when_nothing_fits():
    lay = compute_placeholder_layout("Anything", "Anyone", 5, FakeWidth(), latin_only)
    assert lay.title_lines == (ELLIPSIS,)
    assert lay.author_text == ELLIPSIS


def test_wide_author_is_elided():
    lay = layout("Dune", "Margaret Weis, Tracy Hickman")
    assert lay.author_text.endswith(ELLIPSIS)
    assert lay.author_text.startswith("MARGARET")
    assert width(lay.author_text) <= MAX


def test_empty_author_and_empty_title():
    lay = layout("   ", "  ")
    assert lay.author_text == ""
    assert " ".join(lay.title_lines) == "Unknown book"


def test_whitespace_runs_collapsed():
    lay = layout("  Dune \n  Two ", "")
    assert lay.title_lines == ("Dune Two",)


@pytest.mark.parametrize("raw,expected", [
    ("CĂRTĂRESCU LÁSZLÓ ÖĞİŞE", "CĂRTĂRESCU LÁSZLÓ ÖĞİŞE"),
    ("Cărtărescu László", "CĂRTĂRESCU LÁSZLÓ"),
    ("Haruki Murakami", "HARUKI MURAKAMI"),
    ("George R. R. Martin", "GEORGE R. R. MARTIN"),
])
def test_upper_fixtures(raw, expected):
    lay = compute_placeholder_layout("T", raw, 10_000, FakeWidth(), latin_only)
    assert lay.author_text == expected


def test_font_choice_latin_extended_uses_primary():
    assert pick_font("CĂRTĂRESCU LÁSZLÓ ÖĞİŞE", "P", FALLBACK_FAMILY, latin_only) == "P"


@pytest.mark.parametrize("text", ["Достоевский", "Стругацкий", "Dostoevsky Достоевский"])
def test_font_choice_cyrillic_or_mixed_uses_fallback(text):
    assert pick_font(text, "P", FALLBACK_FAMILY, latin_only) == FALLBACK_FAMILY


def test_font_choice_empty_uses_primary():
    assert pick_font("   ", "P", FALLBACK_FAMILY, latin_only) == "P"


def test_fallback_returned_even_if_it_lacks_char():
    assert pick_font("漢字", "P", "F", lambda fam, ch: False) == "F"


def test_title_and_author_fonts_chosen_independently():
    lay = layout("Crime", "Достоевский")
    assert lay.title_family == L.TITLE_FAMILY
    assert lay.author_family == FALLBACK_FAMILY
    lay = layout("Пикник", "Smith")
    assert lay.title_family == FALLBACK_FAMILY
    assert lay.author_family == L.AUTHOR_FAMILY


def test_cache_hit_does_not_remeasure_and_changes_miss():
    tw = FakeWidth()
    cache = PlaceholderLayoutCache()
    first = cache.get("Dune Messiah Children", "Frank Herbert", MAX, tw, latin_only)
    calls = tw.calls
    assert calls > 0
    assert cache.get("Dune Messiah Children", "Frank Herbert", MAX, tw, latin_only) is first
    assert tw.calls == calls
    cache.get("Dune", "Frank Herbert", MAX, tw, latin_only)
    assert tw.calls > calls
    calls = tw.calls
    cache.get("Dune", "Brian Herbert", MAX, tw, latin_only)
    assert tw.calls > calls


# --- Real bundled fonts ------------------------------------------------------

FONTS = os.path.join(os.path.dirname(__file__), "..", "src", "fabulor", "assets", "fonts")


@pytest.fixture(scope="module")
def measurer():
    try:
        from PySide6.QtGui import QGuiApplication, QFontDatabase
        app = QGuiApplication.instance() or QGuiApplication([])
    except Exception as e:  # pragma: no cover - environment dependent
        pytest.skip(f"no QGuiApplication: {e}")
    for fn in L.PLACEHOLDER_FONT_FILES:
        assert QFontDatabase.addApplicationFont(os.path.join(FONTS, fn)) != -1, fn
    from fabulor.ui.cover_placeholder import QtFontMeasurer
    return QtFontMeasurer()


def _covers(m, family, text):
    return [ch for ch in text if not ch.isspace() and not m.supports_char(family, ch)]


def test_real_primaries_cover_latin_extended(measurer):
    s = "CĂRTĂRESCU LÁSZLÓ ÖĞİŞE"
    assert _covers(measurer, L.TITLE_FAMILY, s) == []
    assert _covers(measurer, L.AUTHOR_FAMILY, s) == []


def test_real_fallback_covers_cyrillic(measurer):
    for s in ("Достоевский", "Стругацкий", "ДОСТОЕВСКИЙ"):
        assert _covers(measurer, FALLBACK_FAMILY, s) == []


def test_log_other_script_coverage(measurer, caplog):
    """Logged, not asserted — makes a future font swap visible."""
    samples = {"greek": "Οδύσσεια", "cyrillic": "Достоевский", "cjk": "村上春樹"}
    with caplog.at_level(logging.INFO):
        for fam in (L.TITLE_FAMILY, L.AUTHOR_FAMILY, FALLBACK_FAMILY):
            for name, s in samples.items():
                missing = _covers(measurer, fam, s)
                logging.getLogger(__name__).info(
                    "%s %s: %s", fam, name, "ok" if not missing else f"missing {''.join(missing)}")
