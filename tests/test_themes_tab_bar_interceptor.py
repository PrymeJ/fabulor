"""_ThemesTabBarInterceptor decision logic (pure, headless).

See review/Design_260805_snapback_timing_v2.md's tab-switch section. Pins the
branch decisions only — which case passes through, which case gets intercepted, and
that the exact existing settle mechanism (_on_theme_unhovered() +
ThemeManager.call_when_theme_settled()) is reused rather than a second, parallel
wait mechanism being introduced. Live paint/compositing verification is covered by
tools/tab_switch_snapback_check.py, not here.
"""
import pytest

from fabulor.ui.panels import _ThemesTabBarInterceptor
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent


class _FakeTabBar:
    def __init__(self, tab_at_result):
        self._tab_at_result = tab_at_result

    def tabAt(self, point):
        return self._tab_at_result


class _FakeTabs:
    def __init__(self, current_index, tab_bar):
        self._current_index = current_index
        self._tab_bar = tab_bar

    def currentIndex(self):
        return self._current_index

    def tabBar(self):
        return self._tab_bar

    def setCurrentIndex(self, index):
        self._current_index = index


class _FakeThemeManager:
    def __init__(self, is_hover_active):
        self._is_hover_active = is_hover_active
        self.unhovered_calls = 0
        self.settled_callbacks = []

    def _on_theme_unhovered(self):
        self.unhovered_calls += 1

    def call_when_theme_settled(self, callback):
        self.settled_callbacks.append(callback)


class _FakeMainWindow:
    def __init__(self, tabs, theme_manager):
        self.tabs = tabs
        self.theme_manager = theme_manager


class _FakePanelManager:
    def __init__(self, main_window):
        self.main_window = main_window


def _make_interceptor(current_index, clicked_index, is_hover_active):
    tab_bar = _FakeTabBar(tab_at_result=clicked_index)
    tabs = _FakeTabs(current_index=current_index, tab_bar=tab_bar)
    tm = _FakeThemeManager(is_hover_active=is_hover_active)
    mw = _FakeMainWindow(tabs=tabs, theme_manager=tm)
    pm = _FakePanelManager(main_window=mw)
    interceptor = _ThemesTabBarInterceptor.__new__(_ThemesTabBarInterceptor)
    interceptor._pm = pm
    return interceptor, tab_bar, tabs, tm


def _press_event():
    return QMouseEvent(
        QMouseEvent.Type.MouseButtonPress, QPointF(5, 5), QPointF(5, 5),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)


def test_non_press_events_pass_through_untouched():
    interceptor, tab_bar, tabs, tm = _make_interceptor(current_index=0, clicked_index=1, is_hover_active=True)
    release = QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease, QPointF(5, 5), QPointF(5, 5),
        Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    assert interceptor.eventFilter(tab_bar, release) is False
    assert tm.unhovered_calls == 0


def test_press_on_a_different_widget_passes_through():
    interceptor, tab_bar, tabs, tm = _make_interceptor(current_index=0, clicked_index=1, is_hover_active=True)
    not_the_tab_bar = object()
    assert interceptor.eventFilter(not_the_tab_bar, _press_event()) is False
    assert tm.unhovered_calls == 0


def test_press_on_the_already_active_tab_passes_through():
    interceptor, tab_bar, tabs, tm = _make_interceptor(current_index=0, clicked_index=0, is_hover_active=True)
    assert interceptor.eventFilter(tab_bar, _press_event()) is False
    assert tm.unhovered_calls == 0


def test_press_outside_any_tab_passes_through():
    interceptor, tab_bar, tabs, tm = _make_interceptor(current_index=0, clicked_index=-1, is_hover_active=True)
    assert interceptor.eventFilter(tab_bar, _press_event()) is False
    assert tm.unhovered_calls == 0


def test_press_on_a_different_tab_with_no_hover_active_passes_through_unmodified():
    # THE COMMON CASE. Must be a pure pass-through: zero behavior change, no
    # settle mechanism touched at all.
    interceptor, tab_bar, tabs, tm = _make_interceptor(current_index=0, clicked_index=1, is_hover_active=False)
    assert interceptor.eventFilter(tab_bar, _press_event()) is False
    assert tm.unhovered_calls == 0
    assert tm.settled_callbacks == []
    assert tabs.currentIndex() == 0  # untouched -- Qt's own handler would switch it


def test_press_on_a_different_tab_with_hover_active_is_intercepted_and_reuses_the_existing_settle_mechanism():
    # THE FIX. Consumes the event (returns True), calls the SAME
    # _on_theme_unhovered()/call_when_theme_settled() pair the Esc/gutter dismiss
    # fix already uses and verified -- no second, parallel wait mechanism.
    interceptor, tab_bar, tabs, tm = _make_interceptor(current_index=0, clicked_index=1, is_hover_active=True)
    consumed = interceptor.eventFilter(tab_bar, _press_event())
    assert consumed is True
    assert tm.unhovered_calls == 1
    assert len(tm.settled_callbacks) == 1
    assert tabs.currentIndex() == 0  # not switched yet -- deferred to the settle callback

    # Simulate the theme genuinely settling: the queued callback fires.
    tm.settled_callbacks[0]()
    assert tabs.currentIndex() == 1
