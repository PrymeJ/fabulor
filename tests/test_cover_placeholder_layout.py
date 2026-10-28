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

    def __call__(self, text, family, role, spacing=0.0):
        self.calls += 1
        return sum(16 if ch in "WM" else PX for ch in text) + spacing * max(len(text) - 1, 0)


def latin_only(family, ch):
    """Primaries support Latin incl. Latin Extended; only the fallback does
    Cyrillic."""
    if "Ѐ" <= ch <= "ӿ":
        return family == FALLBACK_FAMILY
    return True


def layout(title, author, tw=None):
    return compute_placeholder_layout(title, author, MAX, tw or FakeWidth(), latin_only)


def width(s, spacing=0.0):
    return FakeWidth()(s, "", "", spacing)


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
    assert lay.author_text.startswith("MARGARE")
    # Elided names go back to the default spacing, and fit at that spacing.
    assert lay.author_letter_spacing == L.AUTHOR_LETTER_SPACING_STEPS_PX[0]
    assert width(lay.author_text, lay.author_letter_spacing) <= MAX


# Fake widths: 10px per char (16 for W), plus spacing between chars; MAX 100.
# Steps are read from the module so retuning them doesn't break these tests.
STEPS = L.AUTHOR_LETTER_SPACING_STEPS_PX


def test_author_fitting_at_default_spacing_keeps_it():
    lay = layout("T", "ABCDEFGHI")          # 90 + 8×step ≤ 100 for any step ≤ 1.25
    assert lay.author_text == "ABCDEFGHI"
    assert lay.author_letter_spacing == STEPS[0]


def test_author_tightens_to_last_step_when_only_that_fits():
    lay = layout("T", "ABCDEFGHIJ")         # 100 + 9×step: fits only at 0
    assert STEPS[-1] == 0.0
    assert lay.author_text == "ABCDEFGHIJ"
    assert lay.author_letter_spacing == 0.0


def test_author_too_long_even_at_last_step_uses_default_spacing_and_elides():
    lay = layout("T", "ABCDEFGHIJK")        # 110 even at 0
    assert lay.author_text.endswith(ELLIPSIS)
    assert lay.author_letter_spacing == STEPS[0]
    assert width(lay.author_text, STEPS[0]) <= MAX


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
    ("Καλημέρα", "ΚΑΛΗΜΕΡΑ"),                     # tonos dropped in caps
    ("Νίκος Καζαντζάκης", "ΝΙΚΟΣ ΚΑΖΑΝΤΖΑΚΗΣ"),
    ("τσάι", "ΤΣΑΪ"),                             # accent split a diphthong
    ("ρολόι", "ΡΟΛΟΪ"),
    ("Μαΐου", "ΜΑΪΟΥ"),                           # existing diaeresis kept
    ("Ὅμηρος", "ΟΜΗΡΟΣ"),                         # polytonic breathing+accent
    ("Αυγή", "ΑΥΓΗ"),                             # real diphthong, no diaeresis
    ("Ζορμπάς Éric", "ΖΟΡΜΠΑΣ ÉRIC"),             # Latin accent untouched
])
def test_upper_fixtures(raw, expected):
    lay = compute_placeholder_layout("T", raw, 10_000, FakeWidth(), latin_only)
    assert lay.author_text == expected


def test_font_choice_latin_extended_uses_primary():
    assert pick_font("CĂRTĂRESCU LÁSZLÓ ÖĞİŞE", ("P", FALLBACK_FAMILY), latin_only) == "P"


@pytest.mark.parametrize("text", ["Достоевский", "Стругацкий", "Dostoevsky Достоевский"])
def test_font_choice_cyrillic_or_mixed_uses_fallback(text):
    assert pick_font(text, ("P", FALLBACK_FAMILY), latin_only) == FALLBACK_FAMILY


def test_font_choice_empty_uses_primary():
    assert pick_font("   ", ("P", FALLBACK_FAMILY), latin_only) == "P"


def test_fallback_returned_even_if_it_lacks_char():
    assert pick_font("漢字", ("P", "M", "F"), lambda fam, ch: False) == "F"


def cyrillic_in_middle(family, ch):
    """Primary: Latin only. Middle: adds Cyrillic. Last: everything."""
    if "Ѐ" <= ch <= "ӿ":
        return family in ("M", "F")
    if "Ͱ" <= ch <= "Ͽ":
        return family == "F"
    return True


@pytest.mark.parametrize("text,expected", [
    ("SMITH", "P"),
    ("ДОСТОЕВСКИЙ", "M"),               # Cyrillic → middle of the chain
    ("SMITH ДОСТОЕВСКИЙ", "M"),         # mixed: whole string, never per-glyph
    ("ΚΑΖΑΝΤΖΑΚΗΣ", "F"),               # middle lacks Greek → last
    ("ДОСТОЕВСКИЙ Ω", "F"),             # one char the middle lacks → last
])
def test_font_chain_picks_first_full_cover(text, expected):
    assert pick_font(text, ("P", "M", "F"), cyrillic_in_middle) == expected


def test_author_chain_is_saira_exo_roboto():
    assert L.AUTHOR_FONT_CHAIN == (L.AUTHOR_FAMILY, L.AUTHOR_CYRILLIC_FAMILY, FALLBACK_FAMILY)


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


def test_real_fallback_covers_cyrillic_and_greek(measurer):
    for s in ("Достоевский", "Стругацкий", "ДОСТОЕВСКИЙ", "Καζαντζάκης", "ΚΑΖΑΝΤΖΑΚΗΣ"):
        assert _covers(measurer, FALLBACK_FAMILY, s) == []


def test_real_author_chain_routes_cyrillic_to_exo2_and_greek_to_roboto(measurer):
    def author_family(name):
        return compute_placeholder_layout("T", name, 10_000, measurer.text_width,
                                          measurer.supports_char).author_family
    assert author_family("Mircea Cărtărescu") == L.AUTHOR_FAMILY
    assert author_family("Виктор Пелевин") == L.AUTHOR_CYRILLIC_FAMILY
    assert author_family("Ivan Вазов") == L.AUTHOR_CYRILLIC_FAMILY
    assert author_family("Νίκος Καζαντζάκης") == FALLBACK_FAMILY


def test_log_other_script_coverage(measurer, caplog):
    """Logged, not asserted — makes a future font swap visible."""
    samples = {"greek": "Οδύσσεια", "cyrillic": "Достоевский", "cjk": "村上春樹"}
    with caplog.at_level(logging.INFO):
        for fam in (L.TITLE_FAMILY, L.AUTHOR_FAMILY, L.AUTHOR_CYRILLIC_FAMILY, FALLBACK_FAMILY):
            for name, s in samples.items():
                missing = _covers(measurer, fam, s)
                logging.getLogger(__name__).info(
                    "%s %s: %s", fam, name, "ok" if not missing else f"missing {''.join(missing)}")
