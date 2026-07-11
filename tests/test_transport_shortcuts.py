"""Behavior contract for the MainWindow-level transport shortcut handlers
(`_nudge_volume` / `_nudge_speed` / `_nudge_chapter` / `_nudge_long_skip` / `_toggle_mute` /
`_undo_shortcut` in app.py).

The hard requirement for these shortcuts is REUSE, not a parallel implementation: each
must drive the SAME path the on-screen button or wheel already uses. Standing up a real
MainWindow needs mpv + the DB + the full widget tree, so — following the pattern in
`test_panel_exclusion.py` — these tests bind the REAL unbound methods to a tiny fake that
supplies exactly the collaborators each method reads (the volume slider, `_set_speed`,
`handle_prev`/`handle_next`/`handle_rewind`/`handle_forward`, `_perform_undo`, the undo
overlay's visibility). That pins the reuse contract:

- `_nudge_volume` steps ±5 and writes through `volume_slider.setValue()` (the wheel's path).
- `_nudge_speed` steps ±speed_increment through `_set_speed()` (the wheel's path), and
  self-throttles held-key (autorepeat) calls while applying every single tap.
- `_nudge_chapter` calls `handle_prev()`/`handle_next()` — the same methods the chapter nav
  buttons and progress-slider wheel use — and self-throttles held-key repeats to
  `_CHAPTER_NUDGE_THROTTLE_S` (its own constant, independent of speed's).
- `_nudge_long_skip` calls `handle_rewind(long_skip=True)`/`handle_forward(long_skip=True)` —
  the same methods the rewind/forward buttons' right-click uses — and self-throttles held-key
  repeats to `_LONG_SKIP_THROTTLE_S` (also its own constant).
- `_toggle_mute` stores/restores volume purely via `volume_slider.setValue()`.
- `_undo_shortcut` no-ops unless `undo_overlay.isVisible()`, then calls `_perform_undo()`.

The dispatcher-side wiring (which key maps to which action, modifier disambiguation,
autorepeat gating) is covered in test_shortcuts.py. End-to-end audible/visual behavior is
verified live per the project rule that live behavior is ground truth.
"""
import time

import pytest

from fabulor.app import (
    MainWindow, _SPEED_NUDGE_THROTTLE_S, _CHAPTER_NUDGE_THROTTLE_S, _LONG_SKIP_THROTTLE_S,
)


class _FakeSlider:
    def __init__(self, value):
        self._value = value
        self.set_calls = []

    def value(self):
        return self._value

    def setValue(self, v):
        # Mirror a real slider: setValue updates the reported value. (In the app this also
        # emits valueChanged -> _on_volume_changed; we only assert the setValue path here.)
        self.set_calls.append(v)
        self._value = v


class _FakeConfig:
    def __init__(self, increment=0.1, default_speed=1.0):
        self._increment = increment
        self._default_speed = default_speed

    def get_speed_increment(self):
        return self._increment

    def get_default_speed(self):
        return self._default_speed


class _FakePlayer:
    def __init__(self, speed=1.0):
        self.speed = speed


class _FakeShortcuts:
    def __init__(self, is_autorepeat=False):
        self.is_autorepeat = is_autorepeat


class _FakeOverlay:
    def __init__(self, visible):
        self._visible = visible

    def isVisible(self):
        return self._visible


class _FakeMW:
    """Supplies exactly the collaborators the transport handlers read off self."""
    def __init__(self, *, current_file="book.m4b", volume=50, speed=1.0,
                 increment=0.1, is_autorepeat=False, undo_visible=True):
        self.current_file = current_file
        self.volume_slider = _FakeSlider(volume)
        self.player = _FakePlayer(speed) if speed is not None else None
        self.config = _FakeConfig(increment=increment)
        self.shortcuts = _FakeShortcuts(is_autorepeat=is_autorepeat)
        self._pre_mute_volume = None
        self._last_speed_nudge_ts = 0.0
        self._last_chapter_nudge_ts = 0.0
        self._last_long_skip_nudge_ts = 0.0
        self.undo_overlay = _FakeOverlay(undo_visible)
        self.set_speed_calls = []
        self.perform_undo_calls = 0
        self.handle_prev_calls = 0
        self.handle_next_calls = 0
        self.handle_rewind_calls = []   # list of long_skip kwargs passed
        self.handle_forward_calls = []

    def _set_speed(self, value):
        # Mirror the real app: applying a speed updates player.speed, so a subsequent
        # nudge reads the new value (in the app, SpeedControls.set_speed sets player.speed).
        self.set_speed_calls.append(value)
        if self.player is not None:
            self.player.speed = value

    def _perform_undo(self):
        self.perform_undo_calls += 1

    def handle_prev(self):
        self.handle_prev_calls += 1

    def handle_next(self):
        self.handle_next_calls += 1

    def handle_rewind(self, long_skip=False):
        self.handle_rewind_calls.append(long_skip)

    def handle_forward(self, long_skip=False):
        self.handle_forward_calls.append(long_skip)


# ── _nudge_volume: reuse the slider path ─────────────────────────────────────────

def test_nudge_volume_steps_through_slider():
    mw = _FakeMW(volume=50)
    MainWindow._nudge_volume(mw, 1)
    assert mw.volume_slider.set_calls == [55]     # +5, via setValue (the wheel's path)
    MainWindow._nudge_volume(mw, -1)
    assert mw.volume_slider.set_calls == [55, 50]  # -5


def test_nudge_volume_clamps_and_is_inert_without_book():
    mw = _FakeMW(volume=98)
    MainWindow._nudge_volume(mw, 1)
    assert mw.volume_slider.set_calls == [100]    # clamp to 100

    mw2 = _FakeMW(volume=3)
    MainWindow._nudge_volume(mw2, -1)
    assert mw2.volume_slider.set_calls == [0]     # clamp to 0

    # At the ceiling/floor already: no redundant setValue.
    mw3 = _FakeMW(volume=100)
    MainWindow._nudge_volume(mw3, 1)
    assert mw3.volume_slider.set_calls == []

    # No book -> inert.
    mw4 = _FakeMW(current_file=None, volume=50)
    MainWindow._nudge_volume(mw4, 1)
    assert mw4.volume_slider.set_calls == []


# ── _nudge_speed: reuse _set_speed + throttle held repeats ───────────────────────

def test_nudge_speed_steps_through_set_speed():
    mw = _FakeMW(speed=1.0, increment=0.1)
    MainWindow._nudge_speed(mw, 1)
    assert mw.set_speed_calls == [pytest.approx(1.1)]   # via _set_speed (the wheel's path)
    MainWindow._nudge_speed(mw, -1)
    assert mw.set_speed_calls[-1] == pytest.approx(1.0)


def test_nudge_speed_clamps():
    mw = _FakeMW(speed=7.98, increment=0.1)
    MainWindow._nudge_speed(mw, 1)
    assert mw.set_speed_calls == [8.0]                  # clamp to 8.0

    mw2 = _FakeMW(speed=0.3, increment=0.1)
    MainWindow._nudge_speed(mw2, -1)
    assert mw2.set_speed_calls == [pytest.approx(0.25)]  # clamp to 0.25


def test_nudge_speed_inert_without_player():
    mw = _FakeMW(speed=None)   # player is None
    MainWindow._nudge_speed(mw, 1)
    assert mw.set_speed_calls == []


def test_nudge_speed_tap_always_applies_even_when_recent():
    # A single tap (is_autorepeat False) must NEVER be throttled, even immediately after
    # a prior step — the throttle is repeat-only.
    mw = _FakeMW(speed=1.0, increment=0.1, is_autorepeat=False)
    mw._last_speed_nudge_ts = time.monotonic()   # "just applied"
    MainWindow._nudge_speed(mw, 1)
    assert len(mw.set_speed_calls) == 1


def test_nudge_speed_autorepeat_is_throttled():
    # A repeat-sourced call arriving within the throttle window is swallowed; one arriving
    # after the window applies. The tap above and this repeat share one code path.
    mw = _FakeMW(speed=1.0, increment=0.1, is_autorepeat=True)
    mw._last_speed_nudge_ts = time.monotonic()   # window just opened
    MainWindow._nudge_speed(mw, 1)
    assert mw.set_speed_calls == []              # throttled

    # Simulate the window having elapsed.
    mw._last_speed_nudge_ts = time.monotonic() - (_SPEED_NUDGE_THROTTLE_S + 0.01)
    MainWindow._nudge_speed(mw, 1)
    assert len(mw.set_speed_calls) == 1          # now applies


# ── _nudge_chapter: reuse handle_prev/handle_next + its own throttle ─────────────

def test_nudge_chapter_calls_handle_prev_and_next():
    mw = _FakeMW()
    MainWindow._nudge_chapter(mw, -1)
    assert mw.handle_prev_calls == 1
    assert mw.handle_next_calls == 0
    MainWindow._nudge_chapter(mw, 1)
    assert mw.handle_next_calls == 1


def test_nudge_chapter_tap_always_applies_even_when_recent():
    mw = _FakeMW(is_autorepeat=False)
    mw._last_chapter_nudge_ts = time.monotonic()   # "just applied"
    MainWindow._nudge_chapter(mw, 1)
    assert mw.handle_next_calls == 1


def test_nudge_chapter_autorepeat_is_throttled_independently_of_speed():
    mw = _FakeMW(is_autorepeat=True)
    mw._last_chapter_nudge_ts = time.monotonic()
    MainWindow._nudge_chapter(mw, 1)
    assert mw.handle_next_calls == 0                # throttled

    mw._last_chapter_nudge_ts = time.monotonic() - (_CHAPTER_NUDGE_THROTTLE_S + 0.01)
    MainWindow._nudge_chapter(mw, 1)
    assert mw.handle_next_calls == 1                 # window elapsed -> applies

    # Own constant, not derived from / shared with speed's.
    assert _CHAPTER_NUDGE_THROTTLE_S != _SPEED_NUDGE_THROTTLE_S


# ── _nudge_long_skip: reuse handle_rewind/handle_forward(long_skip=True) + its own throttle ──

def test_nudge_long_skip_calls_handle_rewind_and_forward_with_long_skip_true():
    mw = _FakeMW()
    MainWindow._nudge_long_skip(mw, -1)
    assert mw.handle_rewind_calls == [True]
    assert mw.handle_forward_calls == []
    MainWindow._nudge_long_skip(mw, 1)
    assert mw.handle_forward_calls == [True]


def test_nudge_long_skip_tap_always_applies_even_when_recent():
    mw = _FakeMW(is_autorepeat=False)
    mw._last_long_skip_nudge_ts = time.monotonic()
    MainWindow._nudge_long_skip(mw, 1)
    assert mw.handle_forward_calls == [True]


def test_nudge_long_skip_autorepeat_is_throttled_independently_of_speed_and_chapter():
    mw = _FakeMW(is_autorepeat=True)
    mw._last_long_skip_nudge_ts = time.monotonic()
    MainWindow._nudge_long_skip(mw, 1)
    assert mw.handle_forward_calls == []             # throttled

    mw._last_long_skip_nudge_ts = time.monotonic() - (_LONG_SKIP_THROTTLE_S + 0.01)
    MainWindow._nudge_long_skip(mw, 1)
    assert mw.handle_forward_calls == [True]          # window elapsed -> applies

    # Own constant, not derived from / shared with speed's or chapter-nav's.
    assert _LONG_SKIP_THROTTLE_S != _SPEED_NUDGE_THROTTLE_S
    assert _LONG_SKIP_THROTTLE_S != 0.12  # not accidentally hardcoded to speed's literal


# ── _toggle_mute: store then restore via the slider path ─────────────────────────

def test_toggle_mute_stores_and_restores():
    mw = _FakeMW(volume=70)
    MainWindow._toggle_mute(mw)                  # mute
    assert mw.volume_slider.value() == 0
    assert mw._pre_mute_volume == 70
    MainWindow._toggle_mute(mw)                  # unmute -> restore
    assert mw.volume_slider.value() == 70
    assert mw._pre_mute_volume is None


def test_toggle_mute_manual_move_off_zero_counts_as_unmuted():
    # If the user drags the slider off 0 while "muted", the next m must store fresh, not
    # restore the stale pre-mute value.
    mw = _FakeMW(volume=70)
    MainWindow._toggle_mute(mw)                  # mute -> 0, pre_mute=70
    mw.volume_slider.setValue(20)                # user moved it up manually
    MainWindow._toggle_mute(mw)                  # current(20) > 0 -> treated as a fresh mute
    assert mw.volume_slider.value() == 0
    assert mw._pre_mute_volume == 20


def test_toggle_mute_inert_without_book():
    mw = _FakeMW(current_file=None, volume=70)
    MainWindow._toggle_mute(mw)
    assert mw.volume_slider.set_calls == []
    assert mw._pre_mute_volume is None


# ── _undo_shortcut: reuse _perform_undo, gated on overlay visibility ─────────────

def test_undo_shortcut_fires_only_when_overlay_visible():
    shown = _FakeMW(undo_visible=True)
    MainWindow._undo_shortcut(shown)
    assert shown.perform_undo_calls == 1         # reuses the button's exact path

    hidden = _FakeMW(undo_visible=False)
    MainWindow._undo_shortcut(hidden)
    assert hidden.perform_undo_calls == 0        # no affordance shown -> no-op
