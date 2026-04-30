"""
Derives a full theme dict from a QPixmap's dominant color.

Strategy:
  1. Downsample the image to a small thumbnail for speed.
  2. Score pixels by saturation + brightness to find a dominant accent hue.
  3. Also find a secondary hue (most prominent color that differs enough in hue).
  4. Build a dark bg palette from the dominant hue, sprinkle the secondary hue
     on a few accent-adjacent elements to break monotony.
  5. Add small per-session jitter so the same cover doesn't always map to the
     exact same palette.
"""

import random
import colorsys
from PySide6.QtGui import QPixmap, QImage


def _qpixmap_to_rgb_pixels(pixmap: QPixmap, size: int = 64) -> list[tuple[int, int, int]]:
    small = pixmap.scaled(size, size)
    img = small.toImage().convertToFormat(QImage.Format.Format_RGB32)
    pixels = []
    for y in range(img.height()):
        for x in range(img.width()):
            rgb = img.pixel(x, y)
            r = (rgb >> 16) & 0xFF
            g = (rgb >> 8) & 0xFF
            b = rgb & 0xFF
            pixels.append((r, g, b))
    return pixels


def _score_pixel(r: int, g: int, b: int) -> float:
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    if v < 0.15 or (v > 0.97 and s < 0.15):
        return 0.0
    brightness_score = 1.0 - abs(v - 0.55) / 0.55
    return s * 0.7 + brightness_score * 0.3


def _bucket_key(r: int, g: int, b: int) -> tuple[int, int, int]:
    return (r >> 5, g >> 5, b >> 5)


def _find_top_colors(pixels: list[tuple[int, int, int]], count: int = 2) -> list[tuple[int, int, int]]:
    """Return up to `count` dominant accent-worthy colors, differing by at least 30° hue."""
    buckets: dict = {}
    for r, g, b in pixels:
        key = _bucket_key(r, g, b)
        score = _score_pixel(r, g, b)
        if score > 0:
            if key not in buckets:
                buckets[key] = {"score": 0.0, "pixels": []}
            buckets[key]["score"] += score
            buckets[key]["pixels"].append((r, g, b))

    if not buckets:
        return [(120, 80, 160)]

    ranked = sorted(buckets.items(), key=lambda kv: kv[1]["score"], reverse=True)

    results: list[tuple[int, int, int]] = []
    result_hues: list[float] = []

    for _, data in ranked:
        ps = data["pixels"]
        r = sum(p[0] for p in ps) // len(ps)
        g = sum(p[1] for p in ps) // len(ps)
        b = sum(p[2] for p in ps) // len(ps)
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)

        # Only accept if sufficiently different in hue from already-accepted colors
        too_close = any(min(abs(h - rh), 1.0 - abs(h - rh)) < 0.08 for rh in result_hues)
        if not too_close:
            results.append((r, g, b))
            result_hues.append(h)
        if len(results) >= count:
            break

    if not results:
        results.append((120, 80, 160))
    return results


def _hex(r: int, g: int, b: int) -> str:
    return f"#{max(0,min(255,r)):02X}{max(0,min(255,g)):02X}{max(0,min(255,b)):02X}"


def _shift_sv(r: int, g: int, b: int, new_s: float, new_v: float) -> tuple[int, int, int]:
    h, _, _ = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    nr, ng, nb = colorsys.hsv_to_rgb(h, new_s, new_v)
    return (int(nr * 255), int(ng * 255), int(nb * 255))


def _jitter(val: float, amount: float) -> float:
    """Add a small random offset, clamped to [0, 1]."""
    return max(0.0, min(1.0, val + random.uniform(-amount, amount)))


def build_cover_theme(pixmap: QPixmap) -> dict:
    """
    Extract the dominant hue(s) from a QPixmap and return a complete theme dict.
    Small per-call jitter ensures the same cover produces slightly varied palettes.
    """
    if pixmap.isNull():
        return {}

    pixels = _qpixmap_to_rgb_pixels(pixmap)
    colors = _find_top_colors(pixels, count=2)
    dr, dg, db = colors[0]
    sr, sg, sb = colors[1] if len(colors) > 1 else colors[0]

    # Per-session jitter: subtle variation so same cover != identical theme every time
    j = lambda v, a=0.04: _jitter(v, a)

    # --- Dominant-hue palette ---
    bg_deep    = _shift_sv(dr, dg, db, j(0.55), j(0.10))
    bg_main    = _shift_sv(dr, dg, db, j(0.45), j(0.15))
    bg_sidebar = _shift_sv(dr, dg, db, j(0.50), j(0.12))
    bg_lib     = _shift_sv(dr, dg, db, j(0.45), j(0.11))
    lib_row1   = _shift_sv(dr, dg, db, j(0.40), j(0.14))
    lib_row2   = _shift_sv(dr, dg, db, j(0.40), j(0.10))
    lib_grid   = _shift_sv(dr, dg, db, j(0.45), j(0.09))
    bg_drop    = _shift_sv(dr, dg, db, j(0.35), j(0.22))

    accent       = _shift_sv(dr, dg, db, j(0.75), j(0.85))
    accent_light = _shift_sv(dr, dg, db, j(0.55), j(0.95))
    accent_dark  = _shift_sv(dr, dg, db, j(0.80), j(0.45))

    text        = _shift_sv(dr, dg, db, j(0.20), j(0.90))
    text_dim    = _shift_sv(dr, dg, db, j(0.25), j(0.70))
    text_dimmer = _shift_sv(dr, dg, db, j(0.20), j(0.55))

    slider_bg   = _shift_sv(dr, dg, db, j(0.40), j(0.28))

    # --- Secondary-hue accents (sprinkled on a few elements) ---
    sec_accent       = _shift_sv(sr, sg, sb, j(0.70), j(0.80))
    sec_accent_light = _shift_sv(sr, sg, sb, j(0.50), j(0.92))
    sec_dark         = _shift_sv(sr, sg, sb, j(0.75), j(0.40))

    return {
        # Backgrounds
        "bg_deep":                  _hex(*bg_deep),
        "bg_main":                  _hex(*bg_main),
        "bg_sidebar":               _hex(*bg_sidebar),
        "bg_dropdown":              _hex(*bg_drop),
        "bg_library":               _hex(*bg_lib),
        "library_grid_bg":          _hex(*lib_grid),
        "library_row_one":          _hex(*lib_row1),
        "library_row_two":          _hex(*lib_row2),
        # Library items
        "library_item_hover_color": _hex(*sec_accent),
        "library_item_hover_alpha": 0.40,
        "library_title":            _hex(*text),
        "library_author":           _hex(*text_dim),
        "library_narrator":         _hex(*text_dimmer),
        "library_elapsed":          _hex(*text_dim),
        "library_total":            _hex(*text_dim),
        "library_percentage":       _hex(*text_dimmer),
        "library_slider_bg":        _hex(*slider_bg),
        "library_slider_fill":      _hex(*sec_accent),     # secondary on fill
        "library_input_bg":         _hex(*bg_drop),
        "library_input_text":       _hex(*text),
        # Core colors
        "text":                     _hex(*text),
        "accent":                   _hex(*accent),
        "accent_light":             _hex(*accent_light),
        "accent_dark":              _hex(*accent_dark),
        # Main sliders — secondary hue on chapter fill for contrast
        "slider_overall_bg":        _hex(*slider_bg),
        "slider_overall_fill":      _hex(*accent),
        "slider_chapter_bg":        _hex(*_shift_sv(dr, dg, db, j(0.50), j(0.22))),
        "slider_chapter_fill":      _hex(*sec_accent_light),
        "slider_vol_bg":            _hex(*slider_bg),
        "slider_vol_fill":          _hex(*accent),
        # Sidebar
        "sidebar_text":             _hex(*accent_light),
        "sidebar_text_hover":       _hex(*sec_accent_light),
        "sidebar_opacity":          0.85,
        "panel_opacity_hover":      1.00,
        # Panels / settings
        "settings_tab_hover_bg":    _hex(*sec_accent),
        "settings_tab_hover_opacity": 0.85,
        "settings_tab_hover_text":  _hex(*bg_deep),
        "panel_theme_names_dimmed": _hex(*text_dim),
        # Misc
        "curr_chap_highlight":      _hex(*sec_dark),
        "dropdown_time_text":       _hex(*text_dim),
        "notch_color":              _hex(*sec_accent_light),
        "notch_opacity":            100,
    }
