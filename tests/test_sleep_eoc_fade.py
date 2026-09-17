"""Regression net for end-of-chapter sleep mode's fade-out (see CLAUDE.md's sleep-timer
section / the TODO_ARCHIVE.md entry this closes).

Before this fix, end-of-chapter mode had no fade at all — volume stayed at full ratio
until the exact moment sleep fired, then snapped straight to pause. Timed mode's fade
computes its ratio fresh every 200ms tick from wall-clock time remaining; end-of-chapter
mode's equivalent is remaining PLAYBACK POSITION to the anchor chapter's end, which is
seekable by the user at any time — three behaviors were explicitly decided (Pryme,
2026-09-18) and are pinned here:

1. The fade ratio is recomputed fresh every tick from live position vs. the anchor's end,
   so it's tolerant of seeks in BOTH directions within the anchor chapter: a forward seek
   (less remaining) makes the next tick more faded; a backward seek (more remaining) lets
   the volume recover — deliberately NOT a one-way ratchet.
2. The fade window is capped by `_sleep_eoc_distance_at_arm` (the distance from arm time
   to the anchor's end, frozen once at arm time) — the end-of-chapter mirror of timed
   mode's `_total_timer_duration` cap on `_current_sleep_fade`. Without this, arming close
   to a chapter's end (or a chapter shorter than the configured fade duration) would
   produce an instant near-silent jump instead of a graceful fade.
3. That cap does NOT reopen on a backward seek past the arm point — it stays frozen for
   the whole arm cycle, same as timed mode's `_total_timer_duration` never changing either.

These tests drive `SleepTimerPanel.update_timer_state`/`_do_arm_sleep_timer` directly via
the real unbound methods, bound to a lightweight fake standing in for the constructor's
Qt dependencies — the same "bind real logic to a fake object" pattern used elsewhere in
this test suite (test_book_detail_panel_keys.py) for widgets that are expensive to
construct for real but whose methods don't touch anything Qt-specific."""

from fabulor.ui.sleep_timer import SleepTimerPanel


class _FakePlayer:
    """Only the Player surface update_timer_state/_do_arm_sleep_timer's EOC path reads."""

    def __init__(self, chapter_list, duration, time_pos=0.0):
        self.chapter_list = chapter_list
        self.duration = duration
        self.time_pos = time_pos
        self.user_seek_pending = False
        self.sleep_fired = False
        self.is_seeking = False
        self._fade_ratio = 1.0
        self._pause = False

    def set_fade_ratio(self, ratio):
        self._fade_ratio = ratio

    @property
    def pause(self):
        return self._pause

    @pause.setter
    def pause(self, value):
        self._pause = value

    @staticmethod
    def format_time(seconds):
        return f"{int(seconds)}s"


class _FakeConfig:
    def set_sleep_mode(self, mode):
        pass

    def set_sleep_duration(self, minutes):
        pass


class _NoOpSignal:
    def emit(self, *args, **kwargs):
        pass


class _NoOpTimer:
    def stop(self):
        pass


class _NoOpWidget:
    def hide(self):
        pass


class _FakePanel:
    """Standing up a real SleepTimerPanel needs a QApplication (it's a QWidget
    subclass) purely for widgets these two methods never touch. Following the
    "bind the real unbound method to a lightweight fake" pattern used elsewhere
    in this suite (test_book_detail_panel_keys.py) instead — update_timer_state
    and _do_arm_sleep_timer's end-of-chapter path only read/write the plain
    attributes replicated here, never a widget."""

    def __init__(self, player, fade_duration):
        self.player = player
        self.config = _FakeConfig()
        self._sleep_timer_end_time = None
        self._sleep_mode = None
        self._total_timer_duration = 0
        self._current_sleep_fade = fade_duration
        self._sleep_eoc_anchor = None
        self._sleep_eoc_distance_at_arm = None
        self._was_seeking = False
        self._eoc_cancel_message_active = False
        self._eoc_cancel_timer = _NoOpTimer()
        self.disable_sleep_btn = _NoOpWidget()
        self.timer_started = _NoOpSignal()
        self.timer_stopped = _NoOpSignal()
        self.timer_expired = _NoOpSignal()
        self.display_text_updated = _NoOpSignal()

    # Bound to the real unbound implementations below, so the actual
    # production logic is what's under test, not a reimplementation.
    disable_sleep_timer = SleepTimerPanel.disable_sleep_timer
    _do_arm_sleep_timer = SleepTimerPanel._do_arm_sleep_timer
    _current_chapter_index = SleepTimerPanel._current_chapter_index
    update_timer_state = SleepTimerPanel.update_timer_state
    update_panel_styling = lambda self: None


def make_panel(player, fade_duration):
    return _FakePanel(player, fade_duration)


def arm_eoc(panel):
    panel._do_arm_sleep_timer(duration_minutes=None, mode='end_of_chapter')


CHAPTERS = [
    {'time': 0.0, 'title': 'Chapter 1'},
    {'time': 600.0, 'title': 'Chapter 2'},   # anchor chapter: 600s -> 900s (300s long)
    {'time': 900.0, 'title': 'Chapter 3'},
]


def test_fade_ratio_recomputes_lower_on_forward_seek():
    """Seeking forward within the anchor chapter (closer to its end) must make the
    fade MORE pronounced on the very next tick — the scenario Pryme raised directly:
    fade starts at 5 minutes left, user skips to 1 minute left within the chapter."""
    player = _FakePlayer(CHAPTERS, duration=1200.0, time_pos=600.0)  # arm at chapter start
    panel = make_panel(player, fade_duration=300)  # 5-minute fade
    arm_eoc(panel)
    assert panel._sleep_eoc_distance_at_arm == 300.0  # 900 - 600

    # 5 minutes left in the chapter (895s in) -> at the very edge of the fade window
    player.time_pos = 600.0
    panel.update_timer_state(current_time=0, is_paused=False,
                              player_pos=player.time_pos, player_dur=1200.0, is_eof=False)
    ratio_at_5min = player._fade_ratio
    assert ratio_at_5min == 1.0  # remaining=300 == effective_fade=300 -> ratio 1.0, not yet faded below full

    # user skips forward to 1 minute left in the chapter (840s in)
    player.time_pos = 840.0
    panel.update_timer_state(current_time=0, is_paused=False,
                              player_pos=player.time_pos, player_dur=1200.0, is_eof=False)
    ratio_at_1min = player._fade_ratio
    assert ratio_at_1min < ratio_at_5min
    assert abs(ratio_at_1min - (60.0 / 300.0)) < 1e-9


def test_fade_ratio_recovers_on_backward_seek():
    """A backward seek within the anchor chapter must let the volume recover — explicitly
    decided as wanted behavior, not a one-way ratchet."""
    player = _FakePlayer(CHAPTERS, duration=1200.0, time_pos=600.0)
    panel = make_panel(player, fade_duration=300)
    arm_eoc(panel)

    player.time_pos = 840.0  # 1 minute left -> faded
    panel.update_timer_state(current_time=0, is_paused=False,
                              player_pos=player.time_pos, player_dur=1200.0, is_eof=False)
    faded_ratio = player._fade_ratio
    assert faded_ratio < 1.0

    player.time_pos = 610.0  # seek back to near the start of the chapter -> should recover
    panel.update_timer_state(current_time=0, is_paused=False,
                              player_pos=player.time_pos, player_dur=1200.0, is_eof=False)
    recovered_ratio = player._fade_ratio
    assert recovered_ratio > faded_ratio
    # remaining = 900 - 610 = 290, still just inside the 300s fade window -> ratio 290/300
    assert abs(recovered_ratio - (290.0 / 300.0)) < 1e-9


def test_fade_window_capped_when_armed_close_to_chapter_end():
    """Arming with only 30s left in the chapter, but a 5-minute fade duration configured,
    must cap the fade window at 30s (the distance available at arm time) — not produce
    an instant near-silent jump from an uncapped 30/300 ratio."""
    player = _FakePlayer(CHAPTERS, duration=1200.0, time_pos=870.0)  # 30s left in chapter 2
    panel = make_panel(player, fade_duration=300)  # 5-minute fade configured
    arm_eoc(panel)
    assert panel._sleep_eoc_distance_at_arm == 30.0  # 900 - 870, NOT 300

    # Immediately after arming, remaining == distance_at_arm == effective_fade -> ratio 1.0
    panel.update_timer_state(current_time=0, is_paused=False,
                              player_pos=870.0, player_dur=1200.0, is_eof=False)
    assert player._fade_ratio == 1.0

    # Halfway through the 30s window
    panel.update_timer_state(current_time=0, is_paused=False,
                              player_pos=885.0, player_dur=1200.0, is_eof=False)
    assert abs(player._fade_ratio - 0.5) < 1e-9


def test_cap_does_not_reopen_on_backward_seek_past_arm_point():
    """Seeking backward past the original arm point must NOT widen the fade cap —
    _sleep_eoc_distance_at_arm stays frozen for the whole arm cycle."""
    player = _FakePlayer(CHAPTERS, duration=1200.0, time_pos=850.0)  # 50s left at arm
    panel = make_panel(player, fade_duration=300)
    arm_eoc(panel)
    assert panel._sleep_eoc_distance_at_arm == 50.0

    # Seek back to well before the arm point — 13 minutes left in the chapter
    player.time_pos = 120.0  # -> 900 - 120 = 780s remaining, far more than the 50s cap
    panel.update_timer_state(current_time=0, is_paused=False,
                              player_pos=120.0, player_dur=1200.0, is_eof=False)
    # remaining (780) > effective_fade (50) -> no fade applied, stays at full ratio
    assert player._fade_ratio == 1.0
    # The cap itself is unchanged, not recomputed
    assert panel._sleep_eoc_distance_at_arm == 50.0


def test_disable_sleep_timer_clears_distance_at_arm():
    player = _FakePlayer(CHAPTERS, duration=1200.0, time_pos=600.0)
    panel = make_panel(player, fade_duration=300)
    arm_eoc(panel)
    assert panel._sleep_eoc_distance_at_arm is not None

    panel.disable_sleep_timer()
    assert panel._sleep_eoc_distance_at_arm is None
