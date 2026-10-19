"""Pins the backdrop-mode gate on PanelManager._apply_transport_bar_blur_full and
_arm_book_detail_frost_refresh — Book Detail's paint-suppression static-backdrop mechanism.

As of 2026-10-20: FROSTY ONLY. Opaque was dropped — under an opaque panel the frost is invisible,
the 2026-09-24 A/B found no performance benefit, and each grab tore down Book Detail's in-progress
edits/confirms (see test_grab_exclude_by_move.py). History below kept for context.

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

    def frost_panel_backdrop(self, panel, rect, blur, extra_mouse_blocked_widgets=None):
        self.calls.append((panel, rect, blur, extra_mouse_blocked_widgets))


class _FakeStatsPanel:
    """Stands in for main_window.stats_panel — only isVisible()/tabs.tabBar() are read by
    _apply_transport_bar_blur_full's extra_mouse_blocked_widgets wiring."""
    def __init__(self, visible=False):
        self._visible = visible
        self.tabs = type("_FakeTabs", (), {"tabBar": staticmethod(lambda: "TABBAR-SENTINEL")})()

    def isVisible(self):
        return self._visible


class _FakeMainWindow:
    def __init__(self, stats_visible=False):
        self.stats_panel = _FakeStatsPanel(visible=stats_visible)


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

    def __init__(self, backdrop, stats_visible=False):
        self.config = _FakeConfig(backdrop)
        self._transport_bar_blur = _FakeTransportBarBlur()
        self._book_detail_frost_refresh_timer = _FakeTimer()
        self.main_window = _FakeMainWindow(stats_visible=stats_visible)

    def _book_detail_frost_rect(self):
        return "RECT-SENTINEL"


@pytest.mark.parametrize("backdrop", ["frosty"])
def test_transport_bar_blur_full_runs_for_frosty(backdrop):
    host = _FakeHost(backdrop)
    PanelManager._apply_transport_bar_blur_full(host, "PANEL-SENTINEL")
    assert len(host._transport_bar_blur.calls) == 1
    panel, rect, blur, extra = host._transport_bar_blur.calls[0]
    assert panel == "PANEL-SENTINEL"
    assert rect == "RECT-SENTINEL"
    assert blur == (backdrop == "frosty")
    assert extra is None, "no extra widgets to protect when Stats isn't the underlay"


@pytest.mark.parametrize("backdrop", ["frosty"])
def test_transport_bar_blur_full_protects_stats_tab_bar_when_stats_is_underlay(backdrop):
    """Hover-bleed fix regression net (2026-09-24): when Stats is visible underneath Book
    Detail, its tab bar must be passed through as an extra mouse-blocked widget so
    _grab_and_blur's hide/show grab cannot deliver it a genuine hover during the brief window
    Book Detail is hidden to photograph the backdrop."""
    host = _FakeHost(backdrop, stats_visible=True)
    PanelManager._apply_transport_bar_blur_full(host, "PANEL-SENTINEL")
    _, _, _, extra = host._transport_bar_blur.calls[0]
    assert extra == ["TABBAR-SENTINEL"]


@pytest.mark.parametrize("backdrop", ["transparent", "opaque"])
def test_transport_bar_blur_full_skips_non_frosty(backdrop):
    host = _FakeHost(backdrop)
    PanelManager._apply_transport_bar_blur_full(host, "PANEL-SENTINEL")
    assert host._transport_bar_blur.calls == []


@pytest.mark.parametrize("backdrop", ["frosty"])
def test_frost_refresh_arms_for_frosty(backdrop):
    host = _FakeHost(backdrop)
    PanelManager._arm_book_detail_frost_refresh(host)
    assert host._book_detail_frost_refresh_timer.started_with == 10_000


@pytest.mark.parametrize("backdrop", ["transparent", "opaque"])
def test_frost_refresh_skips_non_frosty(backdrop):
    host = _FakeHost(backdrop)
    PanelManager._arm_book_detail_frost_refresh(host)
    assert host._book_detail_frost_refresh_timer.started_with is None


def test_disarm_is_unconditional_regardless_of_mode():
    for backdrop in ("transparent", "frosty", "opaque"):
        host = _FakeHost(backdrop)
        PanelManager._disarm_book_detail_frost_refresh(host)
        assert host._book_detail_frost_refresh_timer.stopped is True
