"""The library row's whole-number percentage must agree with the transport bar's label.

Two displays of one number. The transport bar (`app.py` `_update_ui_sync`) shows
`f"{(pos/dur)*100:.1f}%"`; the library delegate shows a whole number. The library used to
truncate the RAW value, so whenever the true percentage landed in [N.95, N+1) the label had
already rounded up to (N+1).0% while the library still showed N% — reported live 2026-07-31
as a 6.0% header over a 5% library row.

Fix: derive from the same number the label displays (`round(x, 1)`), then drop the decimal.
Truncation is deliberate and preserved — 0.6% reads 0%, 1.9% reads 1%.

Same defect class as the percentage-label tween in CLAUDE.md ("DO NOT animate a UI count-up
toward a target derived from a coarser/truncated value than what live tracking will show").
"""

import pytest

from fabulor.ui.library import BookDelegate


def _header(pos: float, dur: float) -> str:
    """What the transport bar's label shows (app.py `_update_ui_sync`)."""
    return f"{(pos / dur) * 100:.1f}%"


def _library(pos: float, dur: float) -> str:
    """What the library row shows (`BookDelegate._resolve_playback` -> `_pct_str`)."""
    return BookDelegate._pct_str(min(1.0, pos / dur))


def _library_from_pct(true_pct: float) -> str:
    """Convenience for the readable table below. NOTE: dividing a percentage by 100 to fake a
    ratio injects float error the real pipeline never has (both displays divide pos/dur exactly
    once, and share that result) — so this helper is only safe for values that survive the round
    trip. The exhaustive agreement test drives real pos/dur pairs instead, deliberately."""
    return BookDelegate._pct_str(true_pct / 100.0)


@pytest.mark.parametrize("true_pct,expected", [
    (0.0, "0%"),
    (0.4, "0%"),
    (0.6, "0%"),      # NOT 1% — the decimal is dropped, not rounded
    (0.94, "0%"),
    (0.99, "1%"),     # header reads 1.0% here, so the library must too
    (1.0, "1%"),
    (1.4, "1%"),
    (1.6, "1%"),      # NOT 2%
    (1.9, "1%"),
    (1.99, "2%"),
    (2.0, "2%"),
    (5.94, "5%"),
    (5.95, "6%"),     # the reported bug: header 6.0%, library used to show 5%
    (5.97, "6%"),
    (6.0, "6%"),
    (27.9, "27%"),
    (99.95, "100%"),
    (100.0, "100%"),
])
def test_library_percentage_drops_the_decimal(true_pct, expected):
    assert _library_from_pct(true_pct) == expected


def test_the_reported_case():
    """Header showed 6.0% while the library row showed 5%. A 1h44m position in a 29h book."""
    pos, dur = 6285.0, 105280.0
    assert _header(pos, dur) == "6.0%"
    assert _library(pos, dur) == "6%"


def test_never_disagrees_with_the_header():
    """The invariant the bug violated: the library always equals the header with its decimal
    dropped.

    Driven from real pos/dur pairs, NOT synthesized percentages. Both displays divide pos/dur
    exactly once and share that float; a test that instead builds a ratio as `pct/100` injects
    error neither display has, and reports failures that cannot occur in the app (it produced
    five, all at .x95 boundaries, when this file was first written)."""
    import random
    rng = random.Random(7)
    for _ in range(50_000):
        dur = rng.uniform(60.0, 200_000.0)
        pos = rng.uniform(0.0, dur)
        header_without_decimal = int(float(_header(pos, dur)[:-1]))
        assert _library(pos, dur) == f"{header_without_decimal}%", (pos, dur)


def test_boundary_positions_agree():
    """Exact .x95 boundaries built as real positions — the band where the old truncation and
    the header disagreed."""
    dur = 10_000.0
    for whole in range(0, 100):
        for frac in (0.94, 0.95, 0.99):
            pos = (whole + frac) / 100.0 * dur
            header_without_decimal = int(float(_header(pos, dur)[:-1]))
            assert _library(pos, dur) == f"{header_without_decimal}%", (whole, frac)


def test_truncation_is_preserved_not_replaced_by_rounding():
    """Guard against 'fixing' this with a plain round() — that would make 0.6% read 1%."""
    assert _library_from_pct(0.6) == "0%"
    assert _library_from_pct(1.6) == "1%"
    assert _library_from_pct(49.9) == "49%"
