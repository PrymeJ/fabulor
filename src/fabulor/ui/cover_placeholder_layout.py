"""Title/author text layout for the no-cover placeholder.

Pure logic: no widgets, no QApplication, no painting. All font knowledge is
injected (``supports_char`` and ``text_width``) so this is headless-testable
with fakes. ``cover_placeholder.py`` supplies the real QFontMetrics/QRawFont
implementations and does the painting.

The layout is two discrete, fixed states (ONE_LINE_TITLE / TWO_LINE_TITLE),
not continuous re-centering from measured heights — the per-state logo
position below is the knob.
"""
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Dict, Sequence, Tuple

# ---------------------------------------------------------------------------
# Fonts — bundled in assets/fonts/, registered in main.py alongside Open Sans
# Condensed. Family names are as reported by
# QFontDatabase.applicationFontFamilies() for these files (checked 2026-10-27).
# ---------------------------------------------------------------------------
PLACEHOLDER_FONT_FILES = (
    "FrancoisOne-Regular.ttf",
    "SairaSemiCondensed-ExtraBold.ttf",
    "Exo2-ExtraBold.ttf",
    "Roboto-Medium.ttf",
    "Roboto-Black.ttf",
)
TITLE_FAMILY = "Francois One"
AUTHOR_FAMILY = "Saira SemiCondensed"
# Cyrillic fallback for the author line: same weight class and close in size
# to Saira (which has no Cyrillic). Exo 2 has no Greek.
AUTHOR_CYRILLIC_FAMILY = "Exo 2"
# Last resort for both lines: Cyrillic and Greek (Medium for the title,
# Black for the author — see ROLE_WEIGHTS).
FALLBACK_FAMILY = "Roboto"

# Per-STRING fallback chains (never per-glyph): the first family that can
# render every character of the string is used for the whole string.
# François One and Saira cover Latin + Latin Extended, not Cyrillic or Greek.
TITLE_FONT_CHAIN = (TITLE_FAMILY, FALLBACK_FAMILY)
AUTHOR_FONT_CHAIN = (AUTHOR_FAMILY, AUTHOR_CYRILLIC_FAMILY, FALLBACK_FAMILY)

# Faces registered as one weight of a larger family need that weight asked for
# explicitly; QFont(family) alone could resolve to another installed weight.
FAMILY_WEIGHTS = {
    AUTHOR_FAMILY: 800,            # Saira Semi Condensed ExtraBold
    AUTHOR_CYRILLIC_FAMILY: 800,   # Exo 2 ExtraBold
    FALLBACK_FAMILY: 500,          # Roboto Medium
}

ROLE_TITLE = "title"
ROLE_AUTHOR = "author"

# Per-role overrides of FAMILY_WEIGHTS. Roboto Black on the author line
# matches the stroke weight of Saira/Exo 2 ExtraBold (measured ink density
# of caps: Saira 0.60, Exo 2 0.56, Roboto Black 0.53, Bold 0.47).
ROLE_WEIGHTS = {
    (FALLBACK_FAMILY, ROLE_AUTHOR): 900,
}
# Per-family pixel-size overrides, so caps come out the same height as the
# primary's. Roboto's caps are taller per px: at 14px they paint 11px tall vs
# Saira's/Exo 2's 9; at 13px Roboto paints 9.
ROLE_PX_SIZES = {
    (FALLBACK_FAMILY, ROLE_AUTHOR): 13,
}

ELLIPSIS = "…"
UNKNOWN_TITLE = "Unknown book"

# ---------------------------------------------------------------------------
# Tunable layout constants. Coordinates are in cover_art_label's own space:
# 280 wide (300px window − 2×10 content margin) × COVER_AREA_HEIGHT (280) tall.
# Starting values are taken from Pryme's Photopea mockup, calibrated against
# the real widget geometry (see NOTES.md, 2026-10-27).
# ---------------------------------------------------------------------------
# 190, not 200: with greedy wrapping, the mockup's break ("Colorless Tsukuru
# Tazaki" / "and His Years of Pilgrimage") only reproduces between ~182 and ~191.
TEXT_MAX_WIDTH_PX = 190

TITLE_PX_SIZE = 16              # François One 16px matches the mockup's widths
AUTHOR_PX_SIZE = 14
# Author letter-spacing, tried in order: the first that fits the whole name
# wins. If none does, the first is used and the name is elided. Only spacing
# tightens — never the size.
AUTHOR_LETTER_SPACING_STEPS_PX = (0.5, 0.0)


class LayoutState(Enum):
    ONE_LINE_TITLE = 1
    TWO_LINE_TITLE = 2


LOGO_SIZE_PX = {
    LayoutState.ONE_LINE_TITLE: 182,   # = int(COVER_AREA_HEIGHT * 0.65), as before
    LayoutState.TWO_LINE_TITLE: 182,
}
# Old (single dash line) placeholder: logo top at 49, i.e. vertically centered.
# The text block is anchored to the bottom of the area, so the logo moves up by
# one title-line pitch when the title needs a second line.
LOGO_TOP_PX = {
    LayoutState.ONE_LINE_TITLE: 31,
    LayoutState.TWO_LINE_TITLE: 12,
}
LOGO_TITLE_GAP_PX = 26      # logo box bottom → first title line's cap top
TITLE_LINE_PITCH_PX = 19    # title baseline → next title baseline
TITLE_AUTHOR_GAP_PX = 15    # last title baseline → author cap top


SupportsChar = Callable[[str, str], bool]   # (family, ch) -> bool
TextWidth = Callable[..., float]  # (text, family, role, spacing=0.0) -> px


@dataclass(frozen=True)
class PlaceholderLayout:
    title_lines: Tuple[str, ...]
    author_text: str
    title_family: str
    author_family: str
    state: LayoutState
    author_letter_spacing: float = AUTHOR_LETTER_SPACING_STEPS_PX[0]


def pick_font(text: str, chain: Sequence[str],
              supports_char: SupportsChar) -> str:
    """Return the first family in ``chain`` that can render every
    non-whitespace character of ``text`` — used for the whole string, never
    mixed. If none can, the last is still returned; Qt's system fallback
    covers those rare scripts."""
    chars = [ch for ch in text if not ch.isspace()]
    for family in chain[:-1]:
        if all(supports_char(family, ch) for ch in chars):
            return family
    return chain[-1]


def elide_end(text: str, family: str, role: str, max_width_px: int,
              text_width: TextWidth, spacing: float = 0.0) -> str:
    """Return ``text`` unchanged if it fits, else the longest prefix that fits
    with "…" appended. Returns "…" alone if nothing else fits."""
    if text_width(text, family, role, spacing) <= max_width_px:
        return text
    for end in range(len(text) - 1, 0, -1):
        candidate = text[:end].rstrip() + ELLIPSIS
        if (candidate != ELLIPSIS
                and text_width(candidate, family, role, spacing) <= max_width_px):
            return candidate
    return ELLIPSIS


# Combining marks dropped from Greek letters in all-caps text: tonos/oxia,
# varia, perispomeni, psili, dasia, ypogegrammeni. The diaeresis (U+0308) stays.
_GREEK_CAPS_DROPPED_MARKS = {"\u0301", "\u0300", "\u0342", "\u0313", "\u0314", "\u0345"}
# Vowel pairs that read as one sound. If the first carries the accent they are
# two sounds, and in caps the second takes a diaeresis instead: τσάι → ΤΣΑΪ.
_GREEK_DIPHTHONG_FIRSTS = {"Α": "ΙΥ", "Ε": "ΙΥ", "Ο": "ΙΥ", "Υ": "Ι", "Η": "Υ"}


def _is_greek(ch: str) -> bool:
    return "\u0370" <= ch <= "\u03ff" or "\u1f00" <= ch <= "\u1fff"


def caps(text: str) -> str:
    """Upper-case for display. Same as str.upper(), except Greek follows the
    all-caps convention: accents and breathings are dropped (ΚΑΛΗΜΕΡΑ, not
    ΚΑΛΗΜΈΡΑ), and an accent that split a diphthong becomes a diaeresis on
    its second vowel. Non-Greek accents (Á, Ă, Ö) are untouched."""
    out = []          # list of [base, marks]
    split_pending = False
    for ch in unicodedata.normalize("NFD", text.upper()):
        if unicodedata.combining(ch) and out:
            base, marks = out[-1]
            if _is_greek(base) and ch in _GREEK_CAPS_DROPPED_MARKS:
                split_pending = ch in ("\u0301", "\u0300", "\u0342")
                continue
            marks.append(ch)
            continue
        if (split_pending and out and ch in _GREEK_DIPHTHONG_FIRSTS.get(out[-1][0], "")):
            out.append([ch, ["\u0308"]])
        else:
            out.append([ch, []])
        split_pending = False
    return unicodedata.normalize(
        "NFC", "".join(base + "".join(dict.fromkeys(marks)) for base, marks in out))


def compute_placeholder_layout(title: str, author: str, max_width_px: int,
                               text_width: TextWidth,
                               supports_char: SupportsChar) -> PlaceholderLayout:
    # Author: one line, upper-cased. Tighten the letter-spacing step by step
    # if that makes the whole name fit; otherwise default spacing + elision.
    author_text = caps((author or "").strip())
    author_family = pick_font(author_text, AUTHOR_FONT_CHAIN, supports_char)
    author_spacing = AUTHOR_LETTER_SPACING_STEPS_PX[0]
    if author_text:
        for step in AUTHOR_LETTER_SPACING_STEPS_PX:
            if text_width(author_text, author_family, ROLE_AUTHOR, step) <= max_width_px:
                author_spacing = step
                break
        else:
            author_text = elide_end(author_text, author_family, ROLE_AUTHOR,
                                    max_width_px, text_width, author_spacing)

    # Title: 1-2 lines, greedy word wrap, line 2 elided.
    title_text = re.sub(r"\s+", " ", (title or "").strip()) or UNKNOWN_TITLE
    title_family = pick_font(title_text, TITLE_FONT_CHAIN, supports_char)

    def fits(s):
        return text_width(s, title_family, ROLE_TITLE) <= max_width_px

    def elide(s):
        return elide_end(s, title_family, ROLE_TITLE, max_width_px, text_width)

    if fits(title_text):
        lines = (title_text,)
    else:
        words = title_text.split(" ")
        n = 1
        while n < len(words) and fits(" ".join(words[:n + 1])):
            n += 1
        line1 = " ".join(words[:n])
        rest = " ".join(words[n:])
        # A single word wider than the limit is elided on its own line.
        lines = (elide(line1), elide(rest)) if rest else (elide(line1),)

    state = (LayoutState.TWO_LINE_TITLE if len(lines) == 2
             else LayoutState.ONE_LINE_TITLE)
    return PlaceholderLayout(
        title_lines=lines,
        author_text=author_text,
        title_family=title_family,
        author_family=author_family,
        state=state,
        author_letter_spacing=author_spacing,
    )


class PlaceholderLayoutCache:
    """In-memory layout cache keyed on (title, author, max_width_px). Theme
    changes don't affect layout, so a recolor reuses the cached entry."""

    def __init__(self):
        self._entries: Dict[Tuple[str, str, int], PlaceholderLayout] = {}

    def get(self, title: str, author: str, max_width_px: int,
            text_width: TextWidth, supports_char: SupportsChar) -> PlaceholderLayout:
        key = (title, author, max_width_px)
        layout = self._entries.get(key)
        if layout is None:
            layout = compute_placeholder_layout(title, author, max_width_px,
                                                text_width, supports_char)
            self._entries[key] = layout
        return layout
