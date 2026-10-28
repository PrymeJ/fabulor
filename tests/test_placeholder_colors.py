"""Colour resolution for the no-cover placeholder's logo, title and author."""
from fabulor.themes import (THEMES, _resolve_theme, derive_placeholder_title_color,
                            placeholder_colors)


def _hsv_value(hex_color):
    h = hex_color.lstrip('#')
    return max(int(h[i:i + 2], 16) for i in (0, 2, 4))


def test_author_defaults_to_logo_and_title_is_derived_from_it():
    logo, title, author = placeholder_colors({"placeholder_cover": "#7A9BB5", "text": "#ffffff"})
    assert logo == author == "#7A9BB5"
    assert title == derive_placeholder_title_color("#7A9BB5")
    assert _hsv_value(title) > _hsv_value(logo)


def test_logo_fallback_chain_unchanged():
    assert placeholder_colors({"library_narrator": "#123456", "text": "#ffffff"})[0] == "#123456"
    assert placeholder_colors({"text": "#abcdef"})[0] == "#abcdef"


def test_overrides_win_and_title_derives_from_author_override():
    t = {"placeholder_cover": "#222D38", "placeholder_author": "#8CB9E6"}
    logo, title, author = placeholder_colors(t)
    assert (logo, author) == ("#222D38", "#8CB9E6")
    assert title == derive_placeholder_title_color("#8CB9E6")
    t["placeholder_title"] = "#B3D9FE"
    assert placeholder_colors(t)[1] == "#B3D9FE"


def test_text_keys_never_inherit_from_the_base_theme():
    # "The Color Purple" is the base every theme is resolved on top of.
    for name in THEMES:
        own = THEMES[name]
        resolved = _resolve_theme(name)
        for key in ("placeholder_title", "placeholder_author"):
            assert resolved.get(key) == own.get(key), (name, key)
