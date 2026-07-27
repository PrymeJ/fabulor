"""Hover-preview interrupt rules and the swatch-leave discriminator (pure, headless).

Three bugs are pinned here, all found from live DEBUG traces on 2026-07-28 (full
sequences in NOTES.md):

BUG 1 — a hover arriving during a SNAPBACK fade was stashed and then discarded, so the
preview never appeared at all and nothing retried it. Root cause: the interrupt
predicate asked `_is_hover_active` ("was the last APPLIED theme a preview?") instead of
what the RUNNING fade actually is. A snapback applies with hover=False, so it looked
identical to a genuine user selection — the one fade a preview must never interrupt.
Fixed by letting a genuine hover interrupt any in-flight fade. (An intermediate fix
kept a `_fade_is_selection` flag to still protect a genuine selection's settle-fade;
that protection was removed the same day — it had no requirement behind it and
swallowed real previews for 750ms after every click.)

BUG 2 — the "superseded snapback" discard (048ae3a) was reverted. `_is_hover_active`
does not mean "a hover is live now", so after a genuine mouse-out it stays True and the
guard ate the legitimate snapback, stranding the UI on a preview. Test 8 is the direct
pin for that: a stashed snapback must now be REPLAYED in exactly the state the removed
guard discarded it.

BUG 3 — `_on_themes_tab_left` read `isVisible()` live, so a genuine leave landing inside
one of the blur grab's ~15/sec hide windows was silently dropped (the intermittent
sliver snapback). Now discriminated by cursor movement instead.

Qt paint/widget behaviour is NOT covered here and must be live-verified — see the plan's
blocking items. These tests pin decision logic only: which branch ran, not what painted.

Harness follows tests/test_deferred_restyle.py — bind the real unbound method to a
minimal fake supplying only the collaborators it touches. No QApplication.
"""
import pytest

from fabulor.ui.theme_manager import ThemeManager, _MOUSE_JITTER_PX


# --- fakes -----------------------------------------------------------------

class _FakeAnim:
    """Stand-in for _fade_anim exposing only state()/stop()/setDuration()/start()."""

    def __init__(self, running=False):
        from PySide6.QtCore import QAbstractAnimation
        self._running = running
        self._Running = QAbstractAnimation.State.Running
        self._Stopped = QAbstractAnimation.State.Stopped
        self.stopped = False

    def state(self):
        return self._Running if self._running else self._Stopped

    def stop(self):
        self.stopped = True
        self._running = False

    def setDuration(self, ms):
        pass

    def start(self):
        self._running = True


class _FakePanelManager:
    def _any_panel_animating(self):
        return False

    def is_any_full_panel_visible(self):
        return False


class _FakeConfig:
    def get_theme_fade_duration(self):
        return 750


class _FakeMainWindow:
    def __init__(self):
        self.panel_manager = _FakePanelManager()
        self.tabs = None
        self.theme_manager = None


class _Pos:
    """Minimal QPoint stand-in for the cursor-position discriminator."""

    def __init__(self, x, y):
        self._x, self._y = x, y

    def x(self):
        return self._x

    def y(self):
        return self._y


def _make_tm(*, fade_in_flight=False, is_hover_active=False,
             anim_running=False, pending=None):
    """Build a ThemeManager with only the state _on_theme_changed's guard block reads."""
    # ThemeManager subclasses QObject, so object.__new__ is rejected — use the class's
    # own __new__ to get an uninitialised instance without running __init__ (which would
    # build real widgets and need a QApplication).
    tm = ThemeManager.__new__(ThemeManager)
    tm.main_window = _FakeMainWindow()
    tm.config = _FakeConfig()
    tm._fade_in_flight = fade_in_flight
    tm._is_hover_active = is_hover_active
    tm._pending_fade_call = pending
    tm._active_display_theme_internal = "Active"
    tm._fade_anim = _FakeAnim(running=anim_running)
    tm._applied = []
    # Everything below this point in _on_theme_changed is real painting; stub it so the
    # method returns right after the branch decision we are testing.
    tm._apply_stylesheets = lambda name, hover=False: tm._applied.append((name, hover))
    return tm


def _branch(tm, theme, *, hover, user_initiated=True, fade_ms=200, bypass=True):
    """Run the real guard block far enough to observe which branch it took.

    Returns 'stashed' | 'fellthrough'. The apply path past the branch touches real Qt
    painting, so we let it raise there and treat reaching that point as fall-through —
    the branch decision (the thing under test) has already been made by then.
    """
    try:
        ThemeManager._on_theme_changed(
            tm, theme, save=False, fade_ms=fade_ms, hover=hover,
            user_initiated=user_initiated, bypass_panel_open_guard=bypass,
        )
    except Exception:
        pass
    return 'stashed' if tm._pending_fade_call is not None else 'fellthrough'


# --- BUG 1: which fades a hover may interrupt ------------------------------

def test_hover_interrupts_a_snapback_fade():
    # THE BUG. Snapback fade running (_is_hover_active
    # False because the snapback applied with hover=False). Before the fix this stashed
    # and was then discarded, so no preview ever appeared. It must now fall through.
    tm = _make_tm(fade_in_flight=True, is_hover_active=False, anim_running=True)
    assert _branch(tm, "Razorgirl", hover=True) == 'fellthrough'


def test_hover_interrupts_another_hover_fade():
    # The 2026-07-21 fix must survive the predicate rename.
    tm = _make_tm(fade_in_flight=True, is_hover_active=True, anim_running=True)
    assert _branch(tm, "Area X", hover=True) == 'fellthrough'


def test_hover_interrupts_a_genuine_selection_fade():
    # CHANGED 2026-07-28. A hover used to be stashed (then discarded) during a genuine
    # selection's 750ms settle-fade, on the 2026-07-21 assertion that "a preview must
    # never interrupt a real selection". That assertion had no requirement or recorded
    # symptom behind it — the entry preserved it as scope discipline — and it was
    # live-confirmed to swallow real previews for the whole fade after every click
    # (01:50:17,921 'Fire and Blood' -> 01:50:18,653 DISCARDING hover-flagged).
    #
    # The click has already applied AND persisted the theme by the time the fade starts;
    # the settle-fade is cosmetic. The requirement this was believed to protect — a
    # preview must not survive panel dismissal — lives at snap_theme_forward /
    # complete_main_fade, not here.
    tm = _make_tm(fade_in_flight=True, is_hover_active=False, anim_running=True)
    assert _branch(tm, "Area X", hover=True) == 'fellthrough'


def test_hover_interrupts_a_rotation_fade():
    # Deliberate widening (not an accident): an automatic rotation is not a genuine
    # selection, so a hover may interrupt it. Pinned so it is not later "fixed".
    tm = _make_tm(fade_in_flight=True, is_hover_active=False, anim_running=True)
    assert _branch(tm, "Solaris", hover=True) == 'fellthrough'


def test_non_hover_call_still_stashes_during_any_fade():
    # Only `hover` matters now: a snapback, selection, or rotation arriving mid-fade
    # stashes and replays via the drain sites exactly as before.
    tm = _make_tm(fade_in_flight=True, anim_running=True)
    assert _branch(tm, "Wasp Factory", hover=False) == 'stashed'


# --- BUG 2's structural replacement: superseded-stash clear ----------------

def test_interrupt_clears_a_superseded_stash():
    # _fade_anim.stop() emits no `finished`, so nothing would ever drain a stash left
    # against the fade being stopped — it would fire against the NEXT fade instead (the
    # 775ms flash-then-revert). The interrupt must drop it.
    stale = ("Not the Only Fruit", False, 200, False, True, True)
    tm = _make_tm(fade_in_flight=True, is_hover_active=True, anim_running=True, pending=stale)
    _branch(tm, "Eyes of Ibad", hover=True)
    assert tm._pending_fade_call is None
    assert tm._fade_anim.stopped is True


# --- BUG 3: swatch-leave discriminator ------------------------------------

class _FakeWidget:
    def __init__(self, visible=True):
        self._visible = visible

    def isVisible(self):
        return self._visible


def _leave(tm, cursor_pos, widget_visible=True, monkeypatch=None):
    """Run the real _on_themes_tab_left with a pinned cursor position."""
    import fabulor.ui.theme_manager as mod
    calls = []
    tm._on_theme_unhovered = lambda: calls.append(True)

    class _FakeCursor:
        @staticmethod
        def pos():
            return cursor_pos

    original = mod.QCursor
    mod.QCursor = _FakeCursor
    try:
        ThemeManager._on_themes_tab_left(tm, _FakeWidget(widget_visible))
    finally:
        mod.QCursor = original
    return bool(calls)


def test_synthetic_leave_with_unmoved_cursor_is_suppressed():
    # The blur grab hides settings_panel (an ANCESTOR of swatch_box) ~15x/sec, firing a
    # leave each time with the cursor never having moved. Must not snap back.
    tm = _make_tm()
    tm._last_swatch_pos = _Pos(242, 266)
    assert _leave(tm, _Pos(242, 266), widget_visible=False) is False


def test_genuine_leave_is_honoured_even_while_hidden():
    # THE SLIVER BUG: a real mouse-out landing inside a grab window used to be dropped
    # by the live isVisible() check. Cursor moved => genuine => snapback must fire,
    # regardless of visibility.
    tm = _make_tm()
    tm._last_swatch_pos = _Pos(242, 266)
    assert _leave(tm, _Pos(330, 266), widget_visible=False) is True


def test_jitter_below_threshold_is_treated_as_unmoved():
    # Sub-pixel/±1px OS mouse-reporting jitter must not read as real movement.
    tm = _make_tm()
    tm._last_swatch_pos = _Pos(242, 266)
    assert _leave(tm, _Pos(242 + _MOUSE_JITTER_PX, 266), widget_visible=False) is False


def test_movement_just_above_jitter_threshold_is_genuine():
    # Upper-boundary pin — catches a wrong constant or a `<`/`<=` slip.
    tm = _make_tm()
    tm._last_swatch_pos = _Pos(242, 266)
    assert _leave(tm, _Pos(242 + _MOUSE_JITTER_PX + 1, 266), widget_visible=True) is True


def test_leave_with_no_recorded_enter_is_honoured():
    # No reference point (never hovered a swatch, or already consumed): fall back to
    # honouring the leave. Failing open here costs at most a redundant snapback;
    # failing closed would strand a preview, which is the bug being fixed.
    tm = _make_tm()
    tm._last_swatch_pos = None
    assert _leave(tm, _Pos(100, 100)) is True


def test_genuine_leave_updates_the_reference_instead_of_clearing_it():
    # REGRESSION PIN (live-found 2026-07-28, 01:36:15-20). The first implementation
    # CONSUMED the reference (set it to None) on a genuine leave. Every subsequent
    # blur-grab synthetic leave then hit the `seen is None` fallback and fired a
    # snapback: ~70 of them in 5 seconds with the cursor provably frozen at
    # pos=(222,271). Invisible only because the no-op guard caught each one — with a
    # live preview showing, every one would have killed it.
    #
    # The reference must roll forward to the current position, so the NEXT leave still
    # has something to compare against.
    tm = _make_tm()
    tm._last_swatch_pos = _Pos(242, 266)
    _leave(tm, _Pos(330, 266))
    assert tm._last_swatch_pos is not None
    assert (tm._last_swatch_pos.x(), tm._last_swatch_pos.y()) == (330, 266)


def test_synthetic_leaves_after_a_genuine_leave_are_still_suppressed():
    # The end-to-end shape of the same regression: one real mouse-out, then a burst of
    # grab-synthetic leaves at a frozen cursor. Only the first may snap back.
    tm = _make_tm()
    tm._last_swatch_pos = _Pos(242, 266)
    assert _leave(tm, _Pos(222, 271), widget_visible=False) is True   # genuine mouse-out
    for _ in range(10):                                               # grab burst, frozen
        assert _leave(tm, _Pos(222, 271), widget_visible=False) is False
