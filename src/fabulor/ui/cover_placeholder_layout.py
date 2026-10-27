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
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Dict, Tuple

# ---------------------------------------------------------------------------
# Fonts — bundled in assets/fonts/, registered in main.py alongside Open Sans
# Condensed. Family names are as reported by
# QFontDatabase.applicationFontFamilies() for these files (checked 2026-10-27).
# ---------------------------------------------------------------------------
PLACEHOLDER_FONT_FILES = (
    "FrancoisOne-Regular.ttf",
    "Versa.otf",
    "Oswald-Regular.ttf",
)
TITLE_FAMILY = "Francois One"
AUTHOR_FAMILY = "Versa"
# Per-STRING fallback (never per-glyph) for text the primary can't fully
# render — François One and Versa cover Latin + Latin Extended, not Cyrillic.
FALLBACK_FAMILY = "Oswald"

ROLE_TITLE = "title"
ROLE_AUTHOR = "author"

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
AUTHOR_LETTER_SPACING_PX = 0    # mockup's width corresponds to roughly -2


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
TextWidth = Callable[[str, str, str], int]  # (text, family, role) -> px


@dataclass(frozen=True)
class PlaceholderLayout:
    title_lines: Tuple[str, ...]
    author_text: str
    title_family: str
    author_family: str
    state: LayoutState


def pick_font(text: str, primary: str, fallback: str,
              supports_char: SupportsChar) -> str:
    """Return ``primary`` if it can render every non-whitespace character of
    ``text``, otherwise ``fallback`` — for the whole string, never mixed. If
    the fallback also lacks a character it is still returned; Qt's system
    fallback covers those rare scripts."""
    for ch in text:
        if ch.isspace():
            continue
        if not supports_char(primary, ch):
            return fallback
    return primary


def elide_end(text: str, family: str, role: str, max_width_px: int,
              text_width: TextWidth) -> str:
    """Return ``text`` unchanged if it fits, else the longest prefix that fits
    with "…" appended. Returns "…" alone if nothing else fits."""
    if text_width(text, family, role) <= max_width_px:
        return text
    for end in range(len(text) - 1, 0, -1):
        candidate = text[:end].rstrip() + ELLIPSIS
        if candidate != ELLIPSIS and text_width(candidate, family, role) <= max_width_px:
            return candidate
    return ELLIPSIS


def compute_placeholder_layout(title: str, author: str, max_width_px: int,
                               text_width: TextWidth,
                               supports_char: SupportsChar) -> PlaceholderLayout:
    # Author: one line, upper-cased, elided. No wrapping.
    author_text = (author or "").strip().upper()
    author_family = pick_font(author_text, AUTHOR_FAMILY, FALLBACK_FAMILY, supports_char)
    if author_text:
        author_text = elide_end(author_text, author_family, ROLE_AUTHOR,
                                max_width_px, text_width)

    # Title: 1-2 lines, greedy word wrap, line 2 elided.
    title_text = re.sub(r"\s+", " ", (title or "").strip()) or UNKNOWN_TITLE
    title_family = pick_font(title_text, TITLE_FAMILY, FALLBACK_FAMILY, supports_char)

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
