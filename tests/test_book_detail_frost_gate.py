"""Pins the backdrop-mode gate on PanelManager._apply_transport_bar_blur_full and
_arm_book_detail_frost_refresh — Book Detail's paint-suppression static-backdrop mechanism.

As of 2026-09-24 (A/B plan settled with Pryme, see TODO.md): Frosty and Opaque use the grab
mechanism (a static frost/wash composited once at open-start and periodically refreshed);
Transparent does NOT — it relies entirely on the panel's own live paint, matching what
"Transparent" has always meant in this app. This is a REVERT of a same-session, briefly-shipped
version that excluded only Opaque (i.e. ran the mechanism for Frosty+Transparent) — that version
is what caused the live-reported moving-backdrop regression in Transparent mode. Both methods
share one gate shape (skip iff a specific mode string), so a future edit to one drifting out of
sync with the other is exactly the kind of bug this file exists to catch — see the
upsert_book/upsert_books_batch "keep two related call sites in sync" pattern in CLAUDE.md for the
general shape of why a paired-gate test like this earns its keep.

Uses real (unbound) PanelManager methods bound to a light fake, same pattern as
test_panel_exclusion.py's _FakeGate — standing up a real PanelManager needs the whole
MainWindow, and these two methods only ever read `self.config` and call through to
`self._transport_bar_blur`/`self._book_detail_frost_refresh_timer`, both of which a fake can
supply cheaply.
"""
import pytest

from fabulor.ui.panels import PanelManager


class _FakeConfig:
    def __init__(self, backdrop):
        self._backdrop = backdrop

    def get_panel_backdrop(self):
        return self._backdrop


class _FakeTransportBarBlur:
    def __init__(self):
        self.calls = []

    def frost_panel_backdrop(self, panel, rect, blur):
        self.calls.append((panel, rect, blur))


class _FakeTimer:
    def __init__(self):
        self.started_with = None
        self.stopped = False

    def start(self, ms):
        self.started_with = ms

    def stop(self):
        self.stopped = True


class _FakeHost:
    """Supplies exactly what _apply_transport_bar_blur_full / _arm_book_detail_frost_refresh
    read off self: config, _transport_bar_blur, _book_detail_frost_rect(), and the refresh
    timer + its interval constant."""
    _BOOK_DETAIL_FROST_REFRESH_MS = 10_000

    def __init__(self, backdrop):
        self.config = _FakeConfig(backdrop)
        self._transport_bar_blur = _FakeTransportBarBlur()
        self._book_detail_frost_refresh_timer = _FakeTimer()

    def _book_detail_frost_rect(self):
        return "RECT-SENTINEL"


@pytest.mark.parametrize("backdrop", ["frosty", "opaque"])
def test_transport_bar_blur_full_runs_for_frosty_and_opaque(backdrop):
    host = _FakeHost(backdrop)
    PanelManager._apply_transport_bar_blur_full(host, "PANEL-SENTINEL")
    assert len(host._transport_bar_blur.calls) == 1
    panel, rect, blur = host._transport_bar_blur.calls[0]
    assert panel == "PANEL-SENTINEL"
    assert rect == "RECT-SENTINEL"
    assert blur == (backdrop == "frosty")


def test_transport_bar_blur_full_skips_transparent():
    host = _FakeHost("transparent")
    PanelManager._apply_transport_bar_blur_full(host, "PANEL-SENTINEL")
    assert host._transport_bar_blur.calls == []


@pytest.mark.parametrize("backdrop", ["frosty", "opaque"])
def test_frost_refresh_arms_for_frosty_and_opaque(backdrop):
    host = _FakeHost(backdrop)
    PanelManager._arm_book_detail_frost_refresh(host)
    assert host._book_detail_frost_refresh_timer.started_with == 10_000


def test_frost_refresh_skips_transparent():
    host = _FakeHost("transparent")
    PanelManager._arm_book_detail_frost_refresh(host)
    assert host._book_detail_frost_refresh_timer.started_with is None


def test_disarm_is_unconditional_regardless_of_mode():
    for backdrop in ("transparent", "frosty", "opaque"):
        host = _FakeHost(backdrop)
        PanelManager._disarm_book_detail_frost_refresh(host)
        assert host._book_detail_frost_refresh_timer.stopped is True
