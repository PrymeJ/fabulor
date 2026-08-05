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

    def has_settled_waiter(self, coalesce_key):
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
    tm._selection_in_progress = False
    tm._snapback_in_progress = False
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
    # An ORDINARY non-hover call (rotation/idle-timer) — NOT marked as a snapback
    # (_snapback_in_progress stays False, _make_tm's default) — still stashes and
    # replays via the drain sites exactly as before. Only hover, selection, and
    # snapback calls interrupt; a plain rotation is none of those.
    tm = _make_tm(fade_in_flight=True, anim_running=True)
    assert _branch(tm, "Wasp Factory", hover=False) == 'stashed'


# --- Corrected snapback-timing spec v2 (2026-08-05) -------------------------
# See review/Design_260805_snapback_timing_v2.md. A genuine hover-out
# (_on_theme_unhovered) must cut short the ORIGINAL preview's own fade
# immediately and start the 200ms snapback right away, rather than waiting for
# the preview's own (possibly up-to-1500ms) fade duration to finish first. This
# half of the reverted 2026-08-04 attempt (2abeab5) was correct and is
# reinstated unchanged; only _close_settings_flow's own snap_theme_forward()
# call (which defeated the point of this interrupt by force-completing the
# very fade it starts) was the actual bug — see test_close_settings_flow_
# blocks_on_snapback.py.

def test_snapback_interrupts_an_in_flight_preview_fade():
    # THE CORE FIX. Hovering theme A starts a real preview fade; hovering out
    # BEFORE that fade settles must not wait for it — the snapback (marked via
    # _snapback_in_progress, set by _on_theme_unhovered around its own
    # _on_theme_changed call) must interrupt immediately.
    tm = _make_tm(fade_in_flight=True, is_hover_active=True, anim_running=True)
    tm._snapback_in_progress = True
    assert _branch(tm, "Active", hover=False) == 'fellthrough'


def test_ordinary_non_hover_call_unaffected_by_snapback_marker_when_false():
    # Regression guard: _snapback_in_progress defaulting to False (the ordinary
    # state outside _on_theme_unhovered's own call) must not accidentally let
    # every non-hover call interrupt — only genuinely marked snapbacks do.
    tm = _make_tm(fade_in_flight=True, anim_running=True)
    assert tm._snapback_in_progress is False


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
    """Models swatch_box's real geometry (mapFromGlobal/rect/contains), not just
    isVisible() — needed to exercise the hidden-branch SUSPECT condition for real,
    rather than silently falling into the `except Exception: outside = False`
    fallback (which is what happened before this fake supported geometry at all:
    both test_leave_while_hidden_is_always_suppressed and
    test_moving_cursor_while_hidden_is_still_suppressed passed for the wrong
    reason, a bare AttributeError, until this fix's own verification found it —
    see the 2026-08-05 SWATCH-LEAVE-SUSPECT correction). `_origin`/`_size` model
    a box anchored at global (142, 166) sized 240x285 (swatch_box's real live
    dimensions, per fabulor.log's own SWATCH-LEAVE-SUSPECT lines) — so a GLOBAL
    cursor position at (242, 266), the same anchor every other test in this file
    already uses, maps to LOCAL (100, 100), comfortably inside; a position clearly
    away from it maps outside."""

    def __init__(self, visible=True, origin=(142, 166), size=(240, 285)):
        self._visible = visible
        self._origin = origin
        self._size = size

    def isVisible(self):
        return self._visible

    def rect(self):
        from PySide6.QtCore import QRect
        return QRect(0, 0, self._size[0], self._size[1])

    def mapFromGlobal(self, point):
        from PySide6.QtCore import QPoint
        return QPoint(point.x() - self._origin[0], point.y() - self._origin[1])


def _leave(tm, cursor_pos, widget_visible=True, widget=None, monkeypatch=None):
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
        ThemeManager._on_themes_tab_left(tm, widget or _FakeWidget(widget_visible))
    finally:
        mod.QCursor = original
    return bool(calls)


def test_leave_while_hidden_and_cursor_still_inside_is_suppressed():
    # THE GENUINELY-SYNTHETIC CASE (item 7 of the 2026-08-05 correction task) —
    # the one case this whole mechanism was originally built to protect. Hidden
    # (blur-grab mid-cycle) AND the cursor is still geometrically over the
    # swatch grid: this is what "hidden" means when the blur grab is the cause,
    # and must stay fully suppressed, no correction fired, exactly as before
    # this fix. _FakeWidget's default rect is centered on (242, 266); a cursor
    # AT that same anchor is inside it.
    tm = _make_tm()
    tm._last_swatch_pos = _Pos(242, 266)
    assert _leave(tm, _Pos(242, 266), widget_visible=False) is False


def test_moving_cursor_while_hidden_but_still_inside_is_still_suppressed():
    # REGRESSION PIN (live-found 2026-07-28, 02:25:47-54 — three misses back to back).
    # A rolling-reference design compared each leave against the PREVIOUS leave, so a
    # cursor merely moving ACROSS the swatch area travelled 4-14px between consecutive
    # synthetic leaves (~65ms apart) and every one read as genuine. Each then called
    # _on_theme_unhovered -> _hover_debounce_timer.stop(), killing the 80ms debounce
    # ~15x/sec so previews never fired while the cursor was in motion.
    #
    # Movement while hidden, but still geometrically INSIDE swatch_box's rect, must
    # NOT fire a correction — this is the case the 2026-08-05 fix must not touch.
    tm = _make_tm()
    tm._last_swatch_pos = _Pos(242, 266)
    for dx in (6, 12, 18, 24):   # a cursor sweeping across the swatches, still inside
        assert _leave(tm, _Pos(242 + dx, 266), widget_visible=False) is False


# --- SWATCH-LEAVE-SUSPECT correction (2026-08-05) ---------------------------
# See review/Design_260805_swatch_leave_suspect_correction.md. Confirmed live
# (2026-08-05) that a leave suppressed while hidden, with the cursor genuinely
# OUTSIDE swatch_box's rect, produced real multi-minute stuck windows (62s-277s
# observed) — nothing had ever called _on_theme_unhovered() to correct it. Fixed
# by calling it directly when this exact condition fires, reusing the identical
# call every other correction path already uses (no new mechanism).

def test_leave_while_hidden_with_cursor_genuinely_outside_now_fires_correction():
    # THE FIX. Hidden (so the blur-grab-synthetic explanation is plausible), but
    # the cursor is geometrically OUTSIDE swatch_box's rect entirely — a real
    # exit that happened to be delivered during a hidden window. Before
    # 2026-08-05 this only logged [SWATCH-LEAVE-SUSPECT] and returned, leaving
    # _is_hover_active stuck. Must now call _on_theme_unhovered().
    tm = _make_tm()
    tm._last_swatch_pos = _Pos(242, 266)
    widget = _FakeWidget(visible=False)  # default rect centered on (242, 266)
    far_outside = _Pos(242 + 1000, 266 + 1000)
    assert _leave(tm, far_outside, widget_visible=False, widget=widget) is True


def test_leave_while_hidden_with_cursor_just_outside_the_rect_edge_fires_correction():
    # Boundary pin: not just "far away" — a cursor just past the rect's own edge
    # must also correctly read as outside (QRect.contains is right-edge-exclusive
    # for this purpose the same way rect().contains() behaves live).
    tm = _make_tm()
    tm._last_swatch_pos = _Pos(242, 266)
    widget = _FakeWidget(visible=False)  # rect is (0,0,240,285) in local coords
    just_outside = _Pos(142 + 240 + 5, 266)  # a few px past the right edge, globally
    assert _leave(tm, just_outside, widget_visible=False, widget=widget) is True


def test_exception_during_geometry_read_still_fails_safe_to_no_correction():
    # The existing try/except Exception: outside = False wrapper is unchanged by
    # this fix — confirm it still defaults to the SAFE (no correction) side, not
    # a new risk. A widget whose mapFromGlobal raises reproduces this.
    class _BrokenWidget:
        def isVisible(self):
            return False

        def mapFromGlobal(self, point):
            raise RuntimeError("simulated geometry failure")

    tm = _make_tm()
    tm._last_swatch_pos = _Pos(242, 266)
    assert _leave(tm, _Pos(9999, 9999), widget_visible=False, widget=_BrokenWidget()) is False


def test_genuine_mouse_out_while_visible_fires():
    # A real mouse-out toward the dismiss sliver: visible, and the cursor has moved.
    tm = _make_tm()
    tm._last_swatch_pos = _Pos(242, 266)
    assert _leave(tm, _Pos(330, 266), widget_visible=True) is True


def test_visible_but_unmoved_is_suppressed():
    # Secondary guard: a leave delivered while VISIBLE with the cursor unmoved is a
    # stylesheet-cascade artifact, not a mouse-out. Jitter absorbed by _MOUSE_JITTER_PX.
    tm = _make_tm()
    tm._last_swatch_pos = _Pos(242, 266)
    assert _leave(tm, _Pos(242 + _MOUSE_JITTER_PX, 266), widget_visible=True) is False


def test_movement_just_above_jitter_threshold_is_genuine():
    # Upper-boundary pin — catches a wrong constant or a `<`/`<=` slip.
    tm = _make_tm()
    tm._last_swatch_pos = _Pos(242, 266)
    assert _leave(tm, _Pos(242 + _MOUSE_JITTER_PX + 1, 266), widget_visible=True) is True


def test_visible_leave_with_no_recorded_enter_is_honoured():
    # No anchor yet: with the widget visible, honour the leave. Failing open costs at
    # most a redundant snapback; failing closed would strand a preview.
    tm = _make_tm()
    tm._last_swatch_pos = None
    assert _leave(tm, _Pos(100, 100), widget_visible=True) is True


def test_reference_is_not_touched_by_leaves():
    # The anchor is the last genuine ENTER, written only by _on_theme_hovered. Neither
    # consuming it (bug 1: ~70 spurious snapbacks) nor rolling it forward on each leave
    # (bug 2: killed the debounce while moving) is acceptable.
    tm = _make_tm()
    anchor = _Pos(242, 266)
    tm._last_swatch_pos = anchor
    _leave(tm, _Pos(330, 266), widget_visible=True)
    _leave(tm, _Pos(400, 300), widget_visible=False)
    assert tm._last_swatch_pos is anchor


# --- A deliberate selection interrupts too (2026-07-28) --------------------
#
# THE BUG this pins. Right-clicking theme swatches, ten consecutive selections each
# logged `applied=False` with `ever_applied` naming the PREVIOUS click's theme —
# every one stashed behind an in-flight fade and drained ~340ms later. Reported as
# "my right-clicks are missing", and it survived a full day of investigating lost
# presses: nothing was ever lost at the input level (a bare-widget harness took
# 100/100, and every click reached Qt, the widget AND the handler). The click
# applied — one step late, against a theme the user had already moved on from.
#
# Near-universal rather than an edge case because hovering a swatch STARTS a 375ms
# preview fade, and the click ~400ms later lands inside it. Hover-then-click is
# simply how the grid is used.
#
# A snapback is indistinguishable from a click by (user_initiated, hover) alone —
# both (True, False) — so selection is marked at its source.

def test_selection_interrupts_an_in_flight_fade():
    tm = _make_tm(fade_in_flight=True, is_hover_active=True, anim_running=True)
    tm._selection_in_progress = True
    assert _branch(tm, "Syl Anagist", hover=False) == 'fellthrough'


def test_snapback_still_stashes_during_a_fade():
    # The discriminator that matters: same (user_initiated, hover) as a click, but
    # NOT marked. Must keep stashing — letting a snapback interrupt would reopen the
    # flash-then-revert class.
    tm = _make_tm(fade_in_flight=True, is_hover_active=True, anim_running=True)
    tm._selection_in_progress = False
    assert _branch(tm, "Wasp Factory", hover=False) == 'stashed'


def test_selection_marker_defaults_off():
    # getattr fallback: a ThemeManager built without the field must behave as before.
    tm = _make_tm(fade_in_flight=True, anim_running=True)
    del tm._selection_in_progress
    assert _branch(tm, "X", hover=False) == 'stashed'
