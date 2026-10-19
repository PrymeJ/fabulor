import cProfile
import io
import logging
import os
import pstats
import time
from typing import TYPE_CHECKING
from PySide6.QtWidgets import QWidget, QHBoxLayout, QGridLayout, QLabel
from PySide6.QtWidgets import QApplication, QListWidget, QAbstractSpinBox, QScrollArea
from PySide6.QtCore import QPoint, QRect, QPropertyAnimation, QAbstractAnimation, QTimer, Qt, QObject, QEvent
from PySide6.QtGui import QCursor, QPixmap, QPainter, QColor
from .title_bar import ThemeItem
from .transport_bar_blur import TransportBarBlurOverlay, panel_rect_in_common_space
from .stats_panel import StatsRowListView

if TYPE_CHECKING:
    from .book_detail_panel import BookDetailPanel

logger = logging.getLogger(__name__)

# TEMPORARY (library-panel stutter investigation, 2026-07-17): profile the exact
# library-open window (_start_library_entry through _on_library_shown) to find what's
# actually consuming wall-clock time, rather than guessing which function to instrument.
# Enabled via env var so it never runs unless explicitly requested. Remove once the
# stutter's root cause is found. See NOTES.md / TODO.md 2026-07-16/17 entry.
_STUTTER_PROFILE_ENABLED = os.environ.get("FABULOR_STUTTER_PROFILE") == "1"

# TEMPORARY (Book-Detail-from-Stats slowness investigation, 2026-09-22 — TODO.md
# "Book Detail slide-in feels less smooth from Library than from Stats", now
# redirected by real timing data: Stats is the slower/spikier caller, not
# Library). Same shape as _STUTTER_PROFILE_ENABLED above, scoped to the
# open_book_detail -> _start_book_detail_entry -> slide-finished window instead
# of the library-open window. Remove once the investigation is resolved.
_BOOKDETAIL_PROFILE_ENABLED = os.environ.get("FABULOR_BOOKDETAIL_PROFILE", "1") != "0"

# Same gate as transport_bar_blur.py's [DIRTY-TRACE]/[GRAB-ENTRY]/[GRAB-DPR] —
# reused here for [SEAM-TRACE] so one env var covers the whole grab/blur/clip
# investigation without a second switch to remember.
_GRAB_TRACE_ENABLED = os.environ.get("FABULOR_GRAB_TRACE") == "1"

# TEMPORARY (Book-Detail-slide-smoothness investigation, 2026-09-22 — TODO.md
# "Book Detail slide-in feels less smooth from Library than from Stats").
# Logs wall-clock duration + real max frame gap for every panel-open/close
# QPropertyAnimation, so this can be answered with real timing data instead of
# a plausible-sounding guess about the underlay's own concurrent animation.
# Wired generically over every panel's animation object (install_panel_timing_probe,
# called once from app.py after PanelManager + book_detail_panel are both built) so
# no per-panel edits were needed. Remove once the investigation is resolved.
_PANEL_TIMING_ENABLED = os.environ.get("FABULOR_PANEL_TIMING", "1") != "0"

# Moved up from its original position further down this file (immediately after
# _wire_timing_probe) on 2026-09-26 so _wire_text_stall_probe — defined earlier in this file —
# can reference it directly instead of duplicating the literal. A plain module-level assignment
# referencing a name defined LATER in the same file raises NameError at import time, not just at
# call time, since Python evaluates top-level statements in order — this was caught by the full
# test suite failing collection on every test file that imports panels.py at all, not just ones
# exercising the new probe.
_JANK_FRAME_BUDGET_MS = 16.7  # one 60fps frame; a gap wider than this is a dropped/late frame


def _book_detail_probe_context(panel_manager: "PanelManager") -> str:
    """Richer replacement for the bare `panel_manager._book_detail_underlay` string every
    probe log line used to read directly, added 2026-09-25 after a live test round couldn't be
    reconciled against Pryme's own lived experience ("Tags with a few thumbnails opens Book
    Detail less jankily than Stats") — the existing log lines recorded WHICH underlay but
    neither OPEN-vs-CLOSE direction nor, for Tags specifically, how many thumbnails were
    actually loaded at the time. Both turned out to matter: re-analysis of that round found
    OPEN is ~3.7x more filter-dispatch-expensive than CLOSE regardless of source (real, not
    noise — see NOTES.md), and Tags' book count was never recorded at all, so "was this a
    heavily-loaded tag or a small one" could not be answered after the fact. Returns a single
    formatted string (not a tuple/dict) so every existing `from={ctx!r}` call site needs no
    structural change — only this function's own body needs to grow if a future investigation
    needs another dimension recorded.

    Direction is read from the animation's OWN end value, not inferred from before/after state,
    per this file's established preference for reading intent from where it's actually decided
    (`_open_book_detail`/`_close_book_detail_flow` each call `setEndValue` before `start()` —
    see those methods) rather than guessing from a snapshot taken after the fact."""
    underlay = panel_manager._book_detail_underlay
    anim = panel_manager.book_detail_panel_animation
    direction = "?"
    if anim is not None:
        try:
            direction = "open" if anim.endValue().x() == 0 else "close"
        except (RuntimeError, AttributeError):
            direction = "?"
    detail = ""
    if underlay == "tags":
        tags_panel = getattr(panel_manager, "tags_panel", None)
        book_grid = getattr(tags_panel, "_book_grid", None) if tags_panel is not None else None
        thumbs = getattr(book_grid, "_thumbs", None) if book_grid is not None else None
        current_tag = getattr(tags_panel, "_current_tag", None) if tags_panel is not None else None
        if thumbs is not None:
            detail = f", tag={current_tag!r}, books={len(thumbs)}"
    return f"{underlay}({direction}{detail})"


def _stats_probe_context(panel_manager: "PanelManager") -> str:
    """Which Stats tab is active at the moment the stats panel's own slide starts, added
    2026-09-26 to close a real measurement gap: Pryme asked to measure the panel opening with
    Month/Week/Themes as the active tab (a panel reopens on whichever tab it was last closed on
    — this is about the SLIDE cost with that tab loaded, not the tab-switch itself), but the
    stats `[PANEL-TIMING]`/`[PAINT]` lines carried no tab label, so a run with several stats
    open/closes couldn't be split back into "which pair was Month, which was Week" after the
    fact — confirmed live the same night: a run logged 12 stats open/close pairs with no way to
    attribute any of them to a specific tab without an exact click-order transcript, which
    Pryme correctly declined to reconstruct from memory. Read the SAME way
    _book_detail_probe_context reads direction — off real Qt state at start time, not inferred
    from history — via `stats_panel.tabs.tabText(currentIndex())`."""
    tabs = getattr(panel_manager.stats_panel, "tabs", None)
    if tabs is None:
        return "?"
    try:
        return tabs.tabText(tabs.currentIndex())
    except (RuntimeError, AttributeError):
        return "?"


def install_panel_timing_probe(panel_manager: "PanelManager") -> None:
    """See _PANEL_TIMING_ENABLED's comment above. No-op unless that env var is set.

    Hooks QPropertyAnimation.start()/finished/valueChanged on every panel-open/close
    animation generically (name -> animation object), logging wall-clock duration AND
    per-frame jank (max gap between consecutive valueChanged emissions, and a count of
    gaps that blew past one 60fps frame budget).

    An earlier version of this probe sampled a per-frame-gap QTimer at ~4ms per running
    animation to catch event-loop stalls the wall-clock number alone wouldn't show.
    Dropped (2026-09-22) after a live run reported heavier stutter than usual with the
    probe active — 7 concurrent 4ms QTimers, torn down and recreated on every single
    panel open/close, is real per-frame Python-level work injected into the exact event
    loop being measured, and was almost certainly distorting the thing it was trying to
    observe rather than revealing something true about the app.

    Re-added the SAME session, later (2026-09-23), in a different shape: wall-clock alone
    was then checked directly against a live report — Pryme opened Book Detail
    repeatedly from Library for a window he confirmed felt smooth, and the wall-clock
    numbers (327-436ms) landed in the exact same band as every "sluggish" round measured
    all night. The wall-clock timer cannot tell smooth from janky; it only ever answers
    "how long did the whole animation take," and a visually choppy 350ms slide and a
    silky 350ms slide are indistinguishable to a start/finish timer. Pryme's own
    description of the symptom: "Visual stutter/jank during the slide" — not overall
    duration, not input lag, not general app unresponsiveness at that moment.

    valueChanged is NOT the same mechanism as the reverted QTimer sampler: Qt already
    emits it once per real animation tick as part of its own event loop — this hooks a
    signal Qt was already going to fire, adding no new timer, no new polling, and no
    per-animation thread contention. It should not reproduce the "probe distorts the
    thing it measures" failure the QTimer version had, but has not yet been checked
    against a live report of felt stutter — that check is the reason this was added."""
    if not _PANEL_TIMING_ENABLED:
        return

    animations = {
        "library": panel_manager.library_panel_animation,
        "settings": panel_manager.settings_panel_animation,
        "speed": panel_manager.speed_panel_animation,
        "sleep": panel_manager.sleep_panel_animation,
        "sprint": panel_manager.sprint_panel_animation,
        "stats": panel_manager.stats_panel_animation,
        "tags": panel_manager.tags_panel_animation,
        "book_detail": panel_manager.book_detail_panel_animation,
    }

    for name, anim in animations.items():
        if anim is None:
            continue
        # book_detail is the one panel openable from two different underlays
        # (Library or Stats/Tags) — this is exactly what the investigation this
        # probe was built for needs to distinguish, so it gets a context
        # callback read at start time rather than a static name. stats gets the
        # same treatment as of 2026-09-26 (see _stats_probe_context) — a panel
        # reopens on whichever tab it was last closed on, and a run with several
        # stats open/closes had no way to attribute any single pair to a specific
        # tab (Month/Week/Day/...) after the fact without an exact click-order
        # transcript, which isn't a reasonable thing to ask Pryme to reconstruct
        # from memory.
        if name == "book_detail":
            context_fn = lambda pm=panel_manager: _book_detail_probe_context(pm)
        elif name == "stats":
            context_fn = lambda pm=panel_manager: _stats_probe_context(pm)
        else:
            context_fn = None
        _wire_timing_probe(name, anim, context_fn)

    # INSTALL-ORDER NOTE: both diagnostic probes below wrap book_detail_panel_animation.start()
    # AFTER _wire_slide_paint_suppression already has (that production hook is wired in
    # main_window_builders.build_book_detail_panel, which runs before this function is ever
    # called — see that call site's own comment). This is required, not incidental: each
    # wrapper's orig_start closure captures whatever anim.start currently IS at install time, so
    # installing suppression first means a probe's own timing correctly includes the
    # suppression's setup cost (the grab + proxy positioning is real work that belongs in the
    # measured wall-clock number). Installing a probe BEFORE suppression would have the
    # suppression's grab/proxy-setup run AFTER the probe's own START log line, making the
    # logged context appear to fire before the panel is actually ready to slide. Do not reorder
    # main_window_builders.py's call relative to this function without re-checking this.
    # 2026-09-25 correction: an earlier version of this wiring pointed _wire_paint_probe at
    # Library/Stats/Tags' OWN open/close slides, on the assumption that was what Pryme's
    # "Stats worst, Library best, Tags between" report meant. Pryme corrected this directly:
    # "It's not these panel openings, but the book details opening over these panels." The
    # thing to measure is Book Detail's OWN slide, split out by which panel it opened over —
    # which this probe already runs (it's the one panel _wire_paint_probe covered from the
    # start), just without the underlay recorded in its log line. Fixed below by passing a
    # context_fn through, same mechanism _wire_timing_probe already uses for this exact panel
    # (pm._book_detail_underlay) — see install_panel_timing_probe's book_detail wiring above.
    if panel_manager.book_detail_panel_animation is not None:
        _wire_paint_probe("book_detail", panel_manager.book_detail_panel_animation,
                           panel_manager.book_detail_panel,
                           context_fn=lambda pm=panel_manager: _book_detail_probe_context(pm))
        # 2026-09-25: paint cost was checked (above) and ruled out — identical across
        # Library/Stats/Tags. The real signal is in _wire_timing_probe's max_frame_gap/
        # jank_frame_rate, which DOES track the reported Stats > Tags > Library ranking. This
        # probe tests the next candidate: are Stats'/Tags' app-wide QApplication event filters
        # (StatsPanel.eventFilter, TagManagerWidget.eventFilter, hover_tracker.py's
        # ScrollHoverTracker/GridHoverTracker) competing for main-thread time DURING the slide,
        # delaying the animation's own ticks. See NOTES.md, "Severity ranking now measured..."
        _wire_event_filter_cost_probe(panel_manager.book_detail_panel_animation, panel_manager,
                                       name="book_detail")
        # 2026-09-25, third pass: paint cost, app-level event-filter dispatch cost, and every
        # Stats-owned periodic timer have all been checked and ruled out (see NOTES.md). None of
        # them explain why Stats' underlay produces worse frame-delivery timing than Library's or
        # Tags'. Next candidate, a different MECHANISM than anything checked so far: does Qt's
        # own event dispatch — walking a deeper widget tree to deliver ordinary events (resize,
        # move, polish requests, hover-related events, etc.), independent of what any single
        # widget's OWN handler code does with them — cost measurably more for Stats' tree than
        # Library's during the slide? This is about DISPATCH VOLUME/COST, not paint cost or
        # filter cost, which is why a new probe is needed rather than reusing either existing one.
        _wire_event_dispatch_probe("book_detail", panel_manager.book_detail_panel_animation,
                                    panel_manager.book_detail_panel,
                                    context_fn=lambda pm=panel_manager: _book_detail_probe_context(pm))
        # 2026-09-26: Pryme described a symptom none of the above can see — "text briefly stuck
        # in places" specifically on CLOSE, which read as clean on _wire_paint_probe's per-widget
        # TOTALS (a widget that stalls then catches up produces the same total as one that
        # painted evenly). See _wire_text_stall_probe's own docstring.
        _wire_text_stall_probe("book_detail", panel_manager.book_detail_panel_animation,
                                panel_manager.book_detail_panel,
                                context_fn=lambda pm=panel_manager: _book_detail_probe_context(pm))

    # Library's/Stats' OWN slide, added 2026-09-25 — a genuinely new question, not a repeat of
    # the "paint cost identical across all three" finding above. That finding was about Book
    # Detail's OWN widget tree painting the same regardless of which panel it opened over; it
    # never measured Library's or Stats' own panel-open animation directly, because the whole
    # investigation up to this point was specifically about Book Detail's slide (Pryme's own
    # correction, 2026-09-25: "It's not these panel openings, but the book details opening over
    # these panels" — see the comment block above). Tonight's Library-List/Timeline-Streak
    # thread is different: those ARE about the panel's own open/close, with no Book Detail
    # involved, and have never been measured past the wall-clock/frame-gap numbers
    # _wire_timing_probe already gives every panel above. Reuses the exact same three probes,
    # unmodified — all three already take `anim`/`panel` generically, none of their internals
    # assume book_detail specifically.
    if panel_manager.library_panel_animation is not None and panel_manager.library_panel is not None:
        _wire_paint_probe("library", panel_manager.library_panel_animation, panel_manager.library_panel)
        _wire_event_filter_cost_probe(panel_manager.library_panel_animation, panel_manager,
                                       name="library")
        _wire_event_dispatch_probe("library", panel_manager.library_panel_animation, panel_manager.library_panel)
    if panel_manager.stats_panel_animation is not None and panel_manager.stats_panel is not None:
        _wire_paint_probe("stats", panel_manager.stats_panel_animation, panel_manager.stats_panel,
                           context_fn=lambda pm=panel_manager: _stats_probe_context(pm))
        _wire_event_filter_cost_probe(panel_manager.stats_panel_animation, panel_manager,
                                       name="stats")
        _wire_event_dispatch_probe("stats", panel_manager.stats_panel_animation, panel_manager.stats_panel,
                                    context_fn=lambda pm=panel_manager: _stats_probe_context(pm))


def _wire_paint_probe(name: str, anim: QPropertyAnimation, panel: QWidget, context_fn=None) -> None:
    """Per-widget Paint-event cost during a single panel animation, added
    2026-09-23 after four other measurement layers (wall-clock duration,
    valueChanged frame-gap, own-process CPU%, external compositor-load
    sampling) all failed to correlate with Pryme's live-reported Book Detail
    stutter — see NOTES.md "General app sluggishness investigation"
    (2026-09-22/23) for the full trace. Every one of those measured something
    ABOVE the paint layer (the animation's own tick delivery, or the process
    as a whole); none looked at what the widget tree actually spends time
    PAINTING on each frame. This does.

    Scoped narrowly: installs a QObject event filter on the panel and every
    current descendant ONLY between this animation's start and finish
    (removed in _on_finished, never left installed), and only intercepts
    QEvent.Type.Paint — a real event Qt was already going to deliver, not a
    new timer. Descendants are snapshotted once at start via findChildren();
    widgets created mid-animation (should not normally happen for an
    already-built panel, but not assumed impossible) will not be tracked —
    acceptable for this diagnostic, not correctness-critical.

    context_fn (added 2026-09-25, mirrors _wire_timing_probe's identical parameter): called
    once at start and its result stashed, so the finish-time PAINT log line can report WHICH
    underlay this Book Detail slide opened over (Library/Stats/Tags) — captured at start, not
    finish, same reasoning as _wire_timing_probe: the underlay is the thing that was true when
    the slide began, not whatever might be true by the time it settles.

    Times the widget's real paintEvent via a monkey-patched wrapper (same
    start/finished shape as _wire_timing_probe's QPropertyAnimation.start
    hook) rather than the event filter alone — the filter tells us Paint
    events ARRIVED and roughly when, but not how long the widget's own
    paintEvent took to run, which is the actual cost being hunted."""
    state = {"active": False, "per_widget_ms": None, "per_widget_calls": None,
             "orig_paint_events": None, "context": None}

    def _on_start():
        if not _PANEL_TIMING_ENABLED:
            return
        state["context"] = context_fn() if context_fn is not None else None
        widgets = [panel] + panel.findChildren(QWidget)
        per_widget_ms = {}
        per_widget_calls = {}
        orig_paint_events = {}
        for w in widgets:
            key = f"{type(w).__name__}#{w.objectName() or id(w)}"
            per_widget_ms[key] = 0.0
            per_widget_calls[key] = 0
            orig = w.paintEvent
            orig_paint_events[w] = orig

            def _make_wrapper(widget, orig_fn, k):
                def _wrapped(event, _orig=orig_fn, _k=k):
                    t0 = time.perf_counter()
                    result = _orig(event)
                    dt_ms = (time.perf_counter() - t0) * 1000
                    per_widget_ms[_k] += dt_ms
                    per_widget_calls[_k] += 1
                    return result
                return _wrapped

            w.paintEvent = _make_wrapper(w, orig, key)

        state["active"] = True
        state["per_widget_ms"] = per_widget_ms
        state["per_widget_calls"] = per_widget_calls
        state["orig_paint_events"] = orig_paint_events

    def _on_finished():
        if not state["active"]:
            return
        state["active"] = False
        # Restore every wrapped paintEvent before doing anything else — a log
        # line failing must never leave a widget permanently wrapped.
        for w, orig in state["orig_paint_events"].items():
            try:
                w.paintEvent = orig
            except RuntimeError:
                pass  # widget was deleted mid-animation; nothing to restore

        per_ms = state["per_widget_ms"]
        per_calls = state["per_widget_calls"]
        total_ms = sum(per_ms.values())
        total_calls = sum(per_calls.values())
        top = sorted(per_ms.items(), key=lambda kv: kv[1], reverse=True)[:8]
        top_str = ", ".join(f"{k}={v:.1f}ms/{per_calls[k]}x" for k, v in top if v > 0)
        ctx = f" from={state['context']!r}" if state["context"] is not None else ""
        logger.warning(
            f"[PANEL-TIMING] {name} PAINT total_paint_ms={total_ms:.1f} "
            f"total_paint_calls={total_calls}{ctx} top={top_str}")
        state["per_widget_ms"] = None
        state["per_widget_calls"] = None
        state["orig_paint_events"] = None
        state["context"] = None

    orig_start = anim.start

    def _traced_start(*args, **kwargs):
        _on_start()
        return orig_start(*args, **kwargs)

    anim.start = _traced_start
    anim.finished.connect(_on_finished)


# Widget-type prefixes this probe watches per-tick, added 2026-09-26 after Pryme described a
# symptom _wire_paint_probe's totals-only PAINT line cannot show: "text briefly stuck in places"
# during a Book Detail CLOSE that otherwise measured clean on wall/max_frame_gap. A per-widget
# TOTAL across the whole animation cannot distinguish "painted evenly throughout" from "painted
# nothing for 100ms then caught up" — both produce the same total. This probe logs every
# individual paintEvent call's timestamp (ms since animation start) and the gap since THAT SAME
# widget's own previous paint, so a stall specific to one widget — while its siblings and the
# panel's own position keep moving — becomes visible in the data instead of averaged away.
# Scoped to text-bearing widgets specifically (matched by class-name prefix, not exact
# objectName, so it survives an object being unnamed or renamed) since "text stuck" names the
# content class, not a specific instance.
_TEXT_STALL_WIDGET_PREFIXES = ("_ElidingLineEdit", "QLabel", "ScrollingLabel", "FreezableLabel")
# A gap this wide between a widget's own consecutive paints, DURING an otherwise-active
# animation, is what "stuck" would actually look like — matches _JANK_FRAME_BUDGET_MS's own
# one-frame-at-60fps standard, since a single missed frame for one widget is already the
# visible unit Pryme is describing (not a multi-frame freeze).
_TEXT_STALL_GAP_MS = _JANK_FRAME_BUDGET_MS


def _wire_text_stall_probe(name: str, anim: QPropertyAnimation, panel: QWidget, context_fn=None) -> None:
    """Per-tick paint timeline for text-bearing widgets during a single panel animation — see
    the module-level comment above _TEXT_STALL_WIDGET_PREFIXES for why this exists and what gap
    _wire_paint_probe's totals-only PAINT line cannot show.

    Same install/teardown shape as _wire_paint_probe (monkeypatched paintEvent per widget,
    wrapped/restored around anim.start()/finished, never left installed) — deliberately a
    SEPARATE probe rather than folded into _wire_paint_probe, so this stays optional/removable
    without touching the already-relied-on totals probe, and so its extra per-call bookkeeping
    (a timestamp list per widget, not just a running sum) doesn't add overhead to every panel
    _wire_paint_probe already covers when this diagnostic isn't the question being asked.

    Logs ONE line per animation: which watched widgets had a stall (a gap between two of their
    own consecutive paints wider than _TEXT_STALL_GAP_MS), when in the slide it happened (ms
    since anim start), and how wide. A clean run (no widget ever stalled) logs a single
    confirming line rather than nothing, so a quiet log can be read as "checked, found nothing"
    rather than mistaken for "never ran"."""
    state = {"active": False, "per_widget_ticks": None, "orig_paint_events": None,
             "context": None, "t0": None}

    def _on_start():
        if not _PANEL_TIMING_ENABLED:
            return
        state["context"] = context_fn() if context_fn is not None else None
        state["t0"] = time.perf_counter()
        widgets = [panel] + panel.findChildren(QWidget)
        per_widget_ticks = {}
        orig_paint_events = {}
        for w in widgets:
            cls_name = type(w).__name__
            if not any(cls_name.startswith(p) for p in _TEXT_STALL_WIDGET_PREFIXES):
                continue
            key = f"{cls_name}#{w.objectName() or id(w)}"
            per_widget_ticks[key] = []
            orig = w.paintEvent
            orig_paint_events[w] = orig

            def _make_wrapper(orig_fn, k):
                def _wrapped(event, _orig=orig_fn, _k=k):
                    result = _orig(event)
                    if state["active"]:
                        per_widget_ticks[_k].append((time.perf_counter() - state["t0"]) * 1000)
                    return result
                return _wrapped

            w.paintEvent = _make_wrapper(orig, key)

        state["active"] = True
        state["per_widget_ticks"] = per_widget_ticks
        state["orig_paint_events"] = orig_paint_events

    def _on_finished():
        if not state["active"]:
            return
        state["active"] = False
        for w, orig in state["orig_paint_events"].items():
            try:
                w.paintEvent = orig
            except RuntimeError:
                pass  # widget was deleted mid-animation; nothing to restore

        stalls = []
        for key, ticks in state["per_widget_ticks"].items():
            for prev, cur in zip(ticks, ticks[1:]):
                gap = cur - prev
                if gap > _TEXT_STALL_GAP_MS:
                    stalls.append((key, prev, gap))

        ctx = f" from={state['context']!r}" if state["context"] is not None else ""
        if stalls:
            stalls.sort(key=lambda s: -s[2])
            stalls_str = ", ".join(f"{k}@{t:.0f}ms+{g:.0f}ms" for k, t, g in stalls[:8])
            logger.warning(
                f"[PANEL-TIMING] {name} TEXTSTALL n={len(stalls)}{ctx} "
                f"watched={len(state['per_widget_ticks'])} stalls={stalls_str}")
        else:
            logger.warning(
                f"[PANEL-TIMING] {name} TEXTSTALL n=0{ctx} "
                f"watched={len(state['per_widget_ticks'])} (no stall > {_TEXT_STALL_GAP_MS}ms found)")
        state["per_widget_ticks"] = None
        state["orig_paint_events"] = None
        state["context"] = None
        state["t0"] = None

    orig_start = anim.start

    def _traced_start(*args, **kwargs):
        _on_start()
        return orig_start(*args, **kwargs)

    anim.start = _traced_start
    anim.finished.connect(_on_finished)


def _wire_event_filter_cost_probe(anim: QPropertyAnimation, panel_manager: "PanelManager",
                                   name: str = "book_detail") -> None:
    """Measures app-wide QApplication event filter dispatch cost DURING a single panel-slide
    animation — originally Book Detail-only (added 2026-09-25, see below), generalized the same
    day to also cover Library's/Stats' OWN slide (`name` parameter, default `"book_detail"` for
    backward compatibility with the original call site) once the Book-Detail-specific
    investigation this was built for gave way to a broader question: is the SAME app-wide filter
    cost also present during Library's/Stats' own open/close, not just while Book Detail slides
    over them? `name` controls both the log line's prefix and whether Book-Detail-specific
    context (`_book_detail_probe_context`, meaningless for a non-Book-Detail slide) is read.

    Original motivation (2026-09-25, Book-Detail-specific): added after _wire_paint_probe ruled
    out paint cost as the explanation for Pryme's reported Stats > Tags > Library jank severity
    ranking (paint cost was identical across all three; _wire_timing_probe's max_frame_gap/
    jank_frame_rate tracked the ranking instead — see NOTES.md, "Severity ranking now measured,
    not just felt"). This probe tests the next candidate directly: do StatsPanel.eventFilter /
    TagManagerWidget.eventFilter / hover_tracker.py's ScrollHoverTracker/GridHoverTracker — all
    installed via QApplication.instance().installEventFilter(self), confirmed app-wide, confirmed
    still live during a Book Detail slide (Book Detail occludes rather than hides its underlay,
    so hideEvent never fires — see StatsPanel's own OCCLUSION GUARD comment) — actually cost
    measurable main-thread time WHILE the slide's own animation ticks are trying to run.

    Wraps each candidate's live INSTANCE eventFilter method (never the class — see this
    session's own earlier finding: class-level monkeypatching of an already-installed
    eventFilter is silently invisible to Qt's C++ dispatch, which binds to the method resolved
    at installEventFilter() call time) with a timing wrapper, ONLY between this animation's
    start and finish — same scoped-install/scoped-remove shape as _wire_paint_probe, so nothing
    is left wrapped outside the measurement window.

    Candidates: StatsPanel.eventFilter (panel_manager.stats_panel), TagManagerWidget.eventFilter
    (panel_manager.tags_panel), Tags' own two hover trackers (_row_hover, _thumb_hover — both
    ScrollHoverTracker/GridHoverTracker instances, also app-wide, per this file's TODO.md
    "Remaining open question" note on hover_tracker.py never having gotten an occlusion guard),
    and (added same day, second pass) StatsPanel._tassel._on_sway_tick — a ~30fps QTimer tick
    unique to Stats, checked after the eventFilter-only version of this probe ruled out filter
    cost as the severity-ranking explanation. Stats has no hover_tracker instance of its own
    (confirmed by grep, 2026-09-25 — see NOTES.md's "RETRACTED... Stats installs TWO app-wide
    filters" correction).
    """
    candidates = []  # (key, obj, attr_name) — attr_name lets the wrapper generalize past eventFilter
    stats_panel = getattr(panel_manager, "stats_panel", None)
    if stats_panel is not None and hasattr(stats_panel, "eventFilter"):
        candidates.append(("stats_panel", stats_panel, "eventFilter"))
    tags_panel = getattr(panel_manager, "tags_panel", None)
    if tags_panel is not None and hasattr(tags_panel, "eventFilter"):
        candidates.append(("tags_panel", tags_panel, "eventFilter"))
        for tracker_attr in ("_row_hover", "_thumb_hover"):
            tracker = getattr(tags_panel, tracker_attr, None)
            if tracker is not None and hasattr(tracker, "eventFilter"):
                candidates.append((f"tags_panel.{tracker_attr}", tracker, "eventFilter"))
    # 2026-09-25, added after the eventFilter-only version of this probe ruled out filter cost
    # as the explanation (Tags' filter cost is 7x Stats' yet Tags is LESS janky — see NOTES.md).
    # Next candidate: TasselOverlay._sway_timer, a ~30fps (33ms) QTimer independent of the
    # shared 200ms ui_timer, unique to Stats (Library/Tags have no equivalent). Its own
    # _on_sway_tick has an isVisible() safety net, but that checks the TasselOverlay WIDGET's
    # own Qt visibility flag, not whether Book Detail is occluding it — and per this session's
    # established finding, occlusion never fires hideEvent, so this timer may keep ticking (and
    # calling self.update(), a real repaint request) the entire time Book Detail is open on top
    # of Stats. Checking whether it actually does, not assuming.
    tassel = getattr(stats_panel, "_tassel", None) if stats_panel is not None else None
    if tassel is not None and hasattr(tassel, "_on_sway_tick"):
        candidates.append(("stats_panel._tassel._on_sway_tick", tassel, "_on_sway_tick"))

    state = {"active": False, "per_obj_ms": None, "per_obj_calls": None, "orig_methods": None}

    def _on_start():
        if not _PANEL_TIMING_ENABLED:
            return
        per_obj_ms = {}
        per_obj_calls = {}
        orig_methods = {}
        for key, obj, attr_name in candidates:
            per_obj_ms[key] = 0.0
            per_obj_calls[key] = 0
            orig = getattr(obj, attr_name)
            orig_methods[(obj, attr_name)] = orig

            if attr_name == "eventFilter":
                def _make_wrapper(orig_fn, k):
                    def _wrapped(watched, event, _orig=orig_fn, _k=k):
                        t0 = time.perf_counter()
                        result = _orig(watched, event)
                        dt_ms = (time.perf_counter() - t0) * 1000
                        per_obj_ms[_k] += dt_ms
                        per_obj_calls[_k] += 1
                        return result
                    return _wrapped
            else:
                # A timer-tick callback (e.g. TasselOverlay._on_sway_tick) — no args, no
                # QObject.eventFilter signature to preserve.
                def _make_wrapper(orig_fn, k):
                    def _wrapped(_orig=orig_fn, _k=k):
                        t0 = time.perf_counter()
                        result = _orig()
                        dt_ms = (time.perf_counter() - t0) * 1000
                        per_obj_ms[_k] += dt_ms
                        per_obj_calls[_k] += 1
                        return result
                    return _wrapped

            setattr(obj, attr_name, _make_wrapper(orig, key))

        state["active"] = True
        state["per_obj_ms"] = per_obj_ms
        state["per_obj_calls"] = per_obj_calls
        state["orig_methods"] = orig_methods

    def _on_finished():
        if not state["active"]:
            return
        state["active"] = False
        for (obj, attr_name), orig in state["orig_methods"].items():
            try:
                setattr(obj, attr_name, orig)
            except RuntimeError:
                pass  # object was deleted mid-animation; nothing to restore

        per_ms = state["per_obj_ms"]
        per_calls = state["per_obj_calls"]
        total_ms = sum(per_ms.values())
        total_calls = sum(per_calls.values())
        # ctx is only meaningful for book_detail (which underlay, open/close, tag/book-count —
        # see _book_detail_probe_context's own docstring); for library/stats measuring their
        # OWN slide there is no "underlay" concept, so ctx stays empty rather than misleadingly
        # calling into book-detail-specific state that has nothing to do with this animation.
        ctx = _book_detail_probe_context(panel_manager) if name == "book_detail" else None
        ctx_str = f" from={ctx!r}" if ctx is not None else ""
        detail = ", ".join(f"{k}={per_ms[k]:.2f}ms/{per_calls[k]}x" for k in per_ms if per_calls[k] > 0)
        logger.warning(
            f"[PANEL-TIMING] {name} EVENTFILTER total_filter_ms={total_ms:.2f} "
            f"total_filter_calls={total_calls}{ctx_str} detail={detail}")
        state["per_obj_ms"] = None
        state["per_obj_calls"] = None
        state["orig_methods"] = None

    orig_start = anim.start

    def _traced_start(*args, **kwargs):
        _on_start()
        return orig_start(*args, **kwargs)

    anim.start = _traced_start
    anim.finished.connect(_on_finished)


class _EventDispatchCounter(QObject):
    """Counts every event Qt dispatches to a watched widget, by QEvent.Type, and times the
    total filter-chain overhead of intercepting them. Real installEventFilter usage (unlike
    _wire_paint_probe, which wraps paintEvent directly and whose own docstring's "installs a
    QObject event filter" line is a leftover from an earlier draft — not a bug worth a separate
    fix commit, noted here so the discrepancy isn't mistaken for something broken). A genuine
    eventFilter is the right tool here because the question is Qt's OWN event-dispatch volume
    across every event type, not any one widget's paintEvent/eventFilter handler cost — those
    were already checked and ruled out (see NOTES.md, 2026-09-25 entries) and are a different
    mechanism than what this class measures."""

    def __init__(self, counts: dict, total_ms_box: list):
        super().__init__()
        self._counts = counts
        self._total_ms_box = total_ms_box

    def eventFilter(self, watched, event):
        t0 = time.perf_counter()
        etype = event.type()
        self._counts[etype] = self._counts.get(etype, 0) + 1
        result = super().eventFilter(watched, event)
        self._total_ms_box[0] += (time.perf_counter() - t0) * 1000
        return result


def _wire_event_dispatch_probe(name: str, anim: QPropertyAnimation, panel: QWidget, context_fn=None) -> None:
    """Total Qt event-dispatch VOLUME and filter-chain overhead across every descendant of
    `panel`, for every event type, during a single panel animation — added 2026-09-25 as the
    fourth measurement layer in the Stats > Tags > Library severity-ranking investigation, after
    paint cost, app-level event-filter dispatch cost, and every Stats-owned periodic timer were
    all checked and ruled out (see NOTES.md). Tests a different mechanism than any of those:
    does Qt's own per-event dispatch cost more for a deeper widget tree (Stats) than a shallow
    one (Library), independent of what any single widget's own handler does with an event once
    it arrives. `QEvent.Type.Paint` is INCLUDED here (unlike being the sole focus of
    _wire_paint_probe) since the question this time is total dispatch volume across ALL types,
    not paint-specifically.

    Scoped narrowly, same shape as _wire_paint_probe: one _EventDispatchCounter installed on the
    panel and every descendant snapshotted via findChildren() at animation start, removed at
    finish. Real installEventFilter/removeEventFilter (not a monkeypatch) — the correct mechanism
    for "how many events of each type does Qt actually deliver here," which a paintEvent/
    eventFilter wrapper cannot answer since it can only observe the one method/event type it
    replaces.

    context_fn: same contract as _wire_paint_probe's/_wire_timing_probe's identical parameter —
    called once at start, result stashed, included in the finish-time log line."""
    state = {"active": False, "counter": None, "watched": None, "total_ms_box": None,
             "context": None}

    def _on_start():
        if not _PANEL_TIMING_ENABLED:
            return
        state["context"] = context_fn() if context_fn is not None else None
        counts = {}
        total_ms_box = [0.0]
        counter = _EventDispatchCounter(counts, total_ms_box)
        watched = [panel] + panel.findChildren(QWidget)
        for w in watched:
            w.installEventFilter(counter)
        state["active"] = True
        state["counter"] = counter
        state["watched"] = watched
        state["counts"] = counts
        state["total_ms_box"] = total_ms_box

    def _on_finished():
        if not state["active"]:
            return
        state["active"] = False
        counter = state["counter"]
        for w in state["watched"]:
            try:
                w.removeEventFilter(counter)
            except RuntimeError:
                pass  # widget was deleted mid-animation; filter is already gone with it

        counts = state["counts"]
        total_events = sum(counts.values())
        total_ms = state["total_ms_box"][0]
        # Top event types by count, named via QEvent.Type's enum repr for readability.
        top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:8]
        top_str = ", ".join(f"{QEvent.Type(etype).name}={n}" for etype, n in top)
        ctx = f" from={state['context']!r}" if state["context"] is not None else ""
        logger.warning(
            f"[PANEL-TIMING] {name} EVENTDISPATCH total_events={total_events} "
            f"total_dispatch_ms={total_ms:.2f} watched_widgets={len(state['watched'])}{ctx} "
            f"top={top_str}")
        state["counter"] = None
        state["watched"] = None
        state["counts"] = None
        state["total_ms_box"] = None
        state["context"] = None

    orig_start = anim.start

    def _traced_start(*args, **kwargs):
        _on_start()
        return orig_start(*args, **kwargs)

    anim.start = _traced_start
    anim.finished.connect(_on_finished)


def _system_load_snapshot() -> str:
    """stdlib-only system-load reading (no psutil dependency) — os.getloadavg()'s
    1-minute average (system-wide, includes every other process, not just Fabulor)
    plus this process's own CPU seconds consumed so far (os.times(), covers this
    process and its reaped children). Added 2026-09-23 to check whether felt jank
    correlates with system-level contention, after two Qt-internal timing probes
    (wall-clock duration, then per-frame valueChanged gaps) both failed to
    correlate with live-reported smooth/janky verdicts — see TODO.md, "Book Detail
    open cost". Deliberately NOT psutil-based: not currently a project dependency,
    and both of these stdlib calls are already sufficient to see gross contention."""
    try:
        load1, _, _ = os.getloadavg()
    except OSError:
        load1 = -1.0
    times = os.times()
    proc_cpu_s = times.user + times.system
    return f"loadavg1={load1:.2f} proc_cpu_s={proc_cpu_s:.2f}"


def _wire_timing_probe(name: str, anim: QPropertyAnimation, context_fn=None) -> None:
    state = {"t0": None, "last_tick": None, "max_gap": 0.0, "jank_frames": 0, "n_ticks": 0,
             "cpu_s_at_start": None}

    def _on_start():
        state["t0"] = time.perf_counter()
        state["last_tick"] = state["t0"]
        state["max_gap"] = 0.0
        state["jank_frames"] = 0
        state["n_ticks"] = 0
        times = os.times()
        state["cpu_s_at_start"] = times.user + times.system
        target = anim.endValue()
        ctx = f" from={context_fn()!r}" if context_fn is not None else ""
        logger.warning(
            f"[PANEL-TIMING] {name} START target={target} nominal_duration={anim.duration()}ms{ctx} "
            f"{_system_load_snapshot()}")

    def _on_value_changed(_value):
        # Rides Qt's own animation tick — no new timer, no polling. See this
        # function's module-level docstring for why this is not a repeat of the
        # reverted QTimer sampler.
        if state["last_tick"] is None:
            return
        now = time.perf_counter()
        gap_ms = (now - state["last_tick"]) * 1000
        state["last_tick"] = now
        state["n_ticks"] += 1
        if gap_ms > state["max_gap"]:
            state["max_gap"] = gap_ms
        if gap_ms > _JANK_FRAME_BUDGET_MS:
            state["jank_frames"] += 1

    def _on_finished():
        if state["t0"] is None:
            return
        wall_ms = (time.perf_counter() - state["t0"]) * 1000
        # own_cpu_pct: how much of the wall-clock window Fabulor's OWN process spent
        # actually running (vs. idle/blocked/preempted). Low own_cpu_pct alongside a
        # long wall_ms or a wide max_frame_gap points AWAY from this app's own code
        # and toward something external — another process, the compositor, thermal
        # throttling — since Fabulor wasn't the one using the CPU during the stall.
        times = os.times()
        cpu_s_now = times.user + times.system
        own_cpu_ms = (cpu_s_now - state["cpu_s_at_start"]) * 1000 if state["cpu_s_at_start"] is not None else -1
        own_cpu_pct = (own_cpu_ms / wall_ms * 100) if wall_ms > 0 else -1
        logger.warning(
            f"[PANEL-TIMING] {name} FINISHED wall={wall_ms:.1f}ms "
            f"max_frame_gap={state['max_gap']:.1f}ms jank_frames={state['jank_frames']}/{state['n_ticks']} "
            f"own_cpu_ms={own_cpu_ms:.1f} own_cpu_pct={own_cpu_pct:.0f} {_system_load_snapshot()}")
        state["t0"] = None
        state["last_tick"] = None
        state["cpu_s_at_start"] = None

    orig_start = anim.start

    def _traced_start(*args, **kwargs):
        _on_start()
        return orig_start(*args, **kwargs)

    anim.start = _traced_start
    anim.valueChanged.connect(_on_value_changed)
    anim.finished.connect(_on_finished)

# visual_area blur-in / blur-out durations. Deliberately ASYMMETRIC:
# blurring IN is a slow build matched to TransportBarBlurOverlay._FADE_IN_MS
# (1500) so both halves of the window blur together; clearing OUT stays snappy
# so the live view returns immediately as the panel starts sliding away, which
# also mirrors the transport bar's instant dismiss. Both are applied per
# direction because the two paths share one QPropertyAnimation object.
_BLUR_IN_MS = 1500
# Themes-tab exception (2026-07-28). Opening Settings onto the Themes tab uses a
# much shorter blur-in, because that is the one surface where the user's next
# action is expected to be a HOVER, and a hover cannot preview until the blur has
# settled (ThemeManager._on_theme_changed's animation guard — a restyle landing
# mid-tween freezes the blur for ~240ms, measured, so the guard must stay).
#
# Reported live: the first hover after opening Settings was dead for ~1.1s and
# "would make the user wonder if it is broken". Measured dead window, hover
# arriving 430ms after open (the real repro): 1091ms at 1500ms -> 0ms at 400ms.
# Worst case, hovering 50ms after open: 366ms. Crucially this introduces NO
# stall — worst frame gap stays ~17ms, identical to blur-alone baseline, because
# it moves the settle point earlier rather than letting a restyle collide with a
# running tween.
#
# Deliberately NOT a global reduction of _BLUR_IN_MS: every other panel keeps the
# 1500ms feel, since nowhere else is the user racing the blur. Revert by deleting
# this constant and its use in _start_visual_area_blur if the shorter blur-in
# reads as abrupt on that tab.
_BLUR_IN_THEMES_TAB_MS = 400
_BLUR_OUT_MS = 500

# Re-check cadence for call_when_panels_settled's settle watch. One frame at
# 60fps: caps the overshoot past the true settle instant at ~16ms, versus the
# up-to-700ms overshoot the theme guard's _PANEL_ANIM_GUARD_MS poll used to add
# on top of a 1500ms blur-in. Each tick is nine cheap QAbstractAnimation.state()
# reads, so ~90 wakeups across a blur-in is negligible.
_SETTLE_POLL_MS = 16

# Corner-hotspot sidebar trigger (review/Plan_260809_corner_hotspot_sidebar_trigger.md).
# Dismisses the sidebar after this long with no mouse movement anywhere in the window,
# regardless of which method opened it. Value locked in per the approved plan.
_SIDEBAR_IDLE_DISMISS_MS = 10000
# Poll cadence for the cursor-position check driving the above — see
# _sidebar_idle_poll_timer's own comment for why this is a poll, not a move-event
# listener. 500ms is frequent enough that the dismiss fires within half a second of
# its stated deadline, and cheap: one QCursor.pos() read + a comparison, only while
# the sidebar is open.
_SIDEBAR_IDLE_POLL_MS = 500

# Additional pause after a genuine hover-out snapback visibly settles, before the
# Settings-dismiss action it was blocking actually proceeds (2026-08-05, corrected
# snapback-timing spec v2 — see review/Design_260805_snapback_timing_v2.md).
# Makes the revert read as its own perceptible step ("revert, THEN close") rather
# than the dismiss's first frame landing in the same tick the fade completes.
# Starting value per Pryme's own stated range (100-200ms) — tune by live feel, not
# fixed by measurement; this is a UX-feel constant, not a correctness one. ONLY
# paid when a genuine snapback fade actually ran — see _close_settings_flow's own
# _fade_in_flight check, which the ordinary no-hover dismiss skips entirely.
_SNAPBACK_SETTLE_GAP_MS = 150

# Settings tabs wired for arrow navigation — covered by settings_tab_button_rows() +
# MainWindow._handle_settings_arrows. Membership is the ONE switch for turning it on for a tab:
# both the row extraction and the arrow handler are generic over rows, so a tab whose controls
# are QHBoxLayout rows and/or single full-width widgets needs nothing else. Audio qualifies
# because its balance slider and Reset button become one-item rows (see settings_tab_button_rows).
#
# Library qualifies too: its Manage-folders QListWidget is a one-item row like Audio's slider,
# and _handle_settings_arrows hands Up/Down back to the widget except at its first/last item, so
# the box owns its own path selection while the row grid owns entering and leaving it.
#
# Themes joined 2026-09-06. It does NOT reuse settings_tab_button_rows()'s generic per-row
# walk — its button rows (mode, bulk, interval) sit nested inside pool_container, a single
# opaque QWidget item in themes_tab's own top-level layout, so the generic walk (which only
# ever looks at themes_tab's OWN layout items) can't see inside it; and its swatch grid is a
# bin-packed, variable-width-per-row layout with its own preview-on-arrival/select semantics
# that don't fit "a row of clickable buttons" at all. PanelManager.themes_tab_rows() is a
# second, Themes-specific row source; MainWindow._handle_settings_arrows dispatches to it
# instead of settings_tab_button_rows() specifically for this tab. The swatch grid itself is
# a single opaque stop in that row list (like folder_list_widget is in Library's), entered
# and internally navigated by MainWindow._handle_themes_swatch_arrows — see that method and
# panel_tab_widgets's ThemeItem exclusion (the swatch grid deliberately never becomes a Tab
# stop or a traveling-marker target; a real hover-style highlight is the sole affordance).
_ARROW_NAV_TABS = frozenset(("Look", "Controls", "Audio", "Library", "Themes"))


class _ThemesTabBarInterceptor(QObject):
    """Event filter installed on Settings' tab bar (`mw.tabs.tabBar()`) — intercepts a
    switch to a DIFFERENT tab while the theme has not genuinely settled onto the
    committed value, and defers the actual switch until it has
    (2026-08-05, tab-switch snapback interception; extended to the keyboard path 2026-09-03).

    Covers BOTH input paths, because both switch the tab before `currentChanged` can
    veto anything:
      * mouse — the switch happens inside `QTabBar.mousePressEvent`, on PRESS (not release)
      * keyboard — Left/Right, handled natively by `QTabBar.keyPressEvent`

    WHY an event filter and not `currentChanged`: `QTabWidget.currentChanged` fires
    AFTER the tab has already switched — there is no Qt "veto this change" signal.
    So this filter must intercept the originating `MouseButtonPress`/`KeyPress` and
    return `True` to consume it before Qt's own handler runs — anything later
    (release, `currentChanged`) is too late. Reverting from `currentChanged` was tried
    for the keyboard path (2026-09-03) and, while functionally correct, played the
    ~200ms snapback fade over the tab the user had just landed on rather than the one
    they were leaving; deferring the switch instead is what makes the revert read as
    "finish, then move."

    WHY `_theme_genuinely_settled_on_committed()`, not `_is_hover_active` alone
    (CORRECTED 2026-08-05, live-reported by Pryme: "Doesn't work for the Change now
    button. It continues to fade and during that time I can switch multiple tabs."):
    the first version of this filter gated on `_is_hover_active`, which is only
    ever `True` while the last APPLIED theme was a HOVER preview. Clicking
    "Change now" is a genuine SELECTION, not a hover — `_do_rotate` calls
    `_on_theme_changed(chosen, ..., user_initiated=True)` with `hover` defaulting
    `False`, so `_is_hover_active` stays `False` for the entire duration of its
    fade. `_mark_theme_applied` (which sets `_active_display_theme_internal` to
    match the new committed theme) runs BEFORE `_fade_anim.start()` in the
    themes-tab-overlay branch, so the committed-theme identity check alone would
    already read "settled" while the fade is still visually animating —
    `_fade_in_flight` is what actually stays `True` for the fade's full visual
    duration. `_theme_genuinely_settled_on_committed()` already checks all three
    (`not _fade_in_flight`, the committed-identity match, `not _is_hover_active`)
    together, so switching to it fixes the selection case for free without
    weakening the hover case at all — a hover mid-fade already fails this
    predicate too (`_is_hover_active=True`), exactly as before.

    WHY NOT a live cursor-geometry check for the hover case specifically:
    `get_displayed_theme()` computes its answer from `QCursor.pos()` AT CALL TIME
    — by the time this filter runs, the cursor has already moved from the swatch
    to the tab bar, so a geometry-based check would always (wrongly) report "no
    hover in progress" and do nothing.

    Reuses the EXACT mechanism Esc/gutter-dismiss already uses and has verified
    live: `_on_theme_unhovered()` (interrupts any in-flight fade and starts the
    real snapback — a no-op for a genuine selection's own fade, since that fade
    is not a hover preview to revert; see below) + `ThemeManager.
    call_when_theme_settled()` (the identity-checked predicate wait). No second,
    parallel wait mechanism is introduced.

    NOTE on the selection case specifically: `_on_theme_unhovered()` only starts a
    NEW snapback fade if `_cover_theme_active`/`_current_theme_name` differs from
    what's currently painted — for "Change now"'s own fade (already painting the
    correct, newly-committed theme), calling it is a harmless no-op call into
    `_on_theme_changed` that the no-op guard short-circuits immediately;
    `call_when_theme_settled` then simply waits for "Change now"'s OWN
    already-running fade to finish naturally, which is exactly the desired
    behavior — no new fade is started, the existing one is just allowed to
    complete before the tab switches."""

    def __init__(self, panel_manager):
        super().__init__(panel_manager.main_window)
        self._pm = panel_manager

    def eventFilter(self, obj, event):
        if event.type() not in (QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress):
            return False
        mw = self._pm.main_window
        tabs = getattr(mw, 'tabs', None)
        tm = getattr(mw, 'theme_manager', None)
        if tabs is None or tm is None:
            return False
        tab_bar = tabs.tabBar()
        if obj is not tab_bar:
            return False
        target_index = self._target_index_for(event, tabs, tab_bar)
        if target_index is None or target_index == tabs.currentIndex():
            return False  # not a tab-switching event, or already on that tab
        # THE COMMON CASE — theme already genuinely settled on the committed value
        # (covers both "nothing was ever previewed/changed" and "a previous
        # preview/selection already fully settled"). Let the event pass through
        # completely unmodified: zero behavior change, zero added cost, identical
        # to today.
        if tm._theme_genuinely_settled_on_committed():
            return False
        # Either a hover preview is genuinely the last-painted state, OR a genuine
        # selection's own fade (e.g. "Change now") is still visually in flight.
        # Consume the event (Qt never sees it, so the tab does not switch yet),
        # revert any hover via the exact mechanism the dismiss fix already
        # verified (a no-op for the selection case — see class docstring), then
        # switch once settled.
        tm._on_theme_unhovered()
        tm.call_when_theme_settled(lambda idx=target_index: tabs.setCurrentIndex(idx))
        return True

    @staticmethod
    def _target_index_for(event, tabs, tab_bar):
        """Which tab index this event is about to switch to, or None if it isn't a tab switch.

        Mouse: the tab under the cursor (None when the press missed every tab).

        Keyboard: QTabBar switches on Left/Right ONLY, and does NOT wrap — measured directly
        against a real QTabBar (2026-09-03): Up/Down leave currentIndex untouched and come back
        `accepted=False`, Left at index 0 stays at 0, Right at the last index stays there. So the
        target is a plain +/-1 step, and returning an out-of-range step as None makes the
        boundary cases fall through untouched rather than being consumed for a switch that
        would never have happened."""
        if event.type() == QEvent.Type.MouseButtonPress:
            idx = tab_bar.tabAt(event.position().toPoint())
            return idx if idx >= 0 else None
        key = event.key()
        if key == Qt.Key.Key_Left:
            step = -1
        elif key == Qt.Key.Key_Right:
            step = 1
        else:
            return None
        idx = tabs.currentIndex() + step
        return idx if 0 <= idx < tabs.count() else None


class PanelManager:
    def __init__(self, main_window):
        self.main_window = main_window
        self.config = main_window.config # Access config through main_window
        
        # State variables
        self.sidebar_expanded = False
        self._pending_panel_open = None
        self._sidebar_panel_signal_connected = False
        # List-mode-only slide-paint-suppression proxy — see _start_library_entry,
        # _on_library_shown, _close_library_flow, and _teardown_library_list_proxy.
        self._library_list_proxy: "QLabel | None" = None
        # True only during the first-open deferral gap between _start_library_entry
        # scheduling _finish_library_entry_animation and that call actually running —
        # see both methods and _close_library_flow's own guard.
        self._library_entry_animation_pending = False
        
        # Widgets (references passed from MainWindow)
        self.sidebar = main_window.sidebar
        self.library_panel = main_window.library_panel
        self.settings_panel = main_window.settings_panel
        self.speed_panel = main_window.speed_panel
        self.sleep_panel = main_window.sleep_panel
        self.sprint_panel = main_window.sprint_panel
        self.stats_panel = main_window.stats_panel
        self.blur_effect = main_window.blur_effect # Reference to the blur effect
        self.blur_animation = main_window.blur_animation # Reference to the blur animation

        # Animations (initialized in MainWindow, referenced here)
        self.sidebar_animation = main_window.sidebar_animation
        self.library_panel_animation = main_window.library_panel_animation
        self.settings_panel_animation = main_window.settings_panel_animation
        self.speed_panel_animation = main_window.speed_panel_animation
        self.sleep_panel_animation = main_window.sleep_panel_animation
        self.sprint_panel_animation = main_window.sprint_panel_animation
        self.stats_panel_animation = main_window.stats_panel_animation
        self.tags_panel_animation = main_window.tags_panel_animation
        self.tags_panel = main_window.tags_panel
        self.book_detail_panel: "BookDetailPanel | None" = None
        self.book_detail_panel_animation: QPropertyAnimation | None = None
        # Which panel Book Detail was opened ON TOP OF, as a string key ('stats' /
        # 'tags' / 'library' / None). Written in open_book_detail, consumed once in
        # _resume_blur_after_book_detail. A key, not a widget, so the Library and
        # no-underlay cases stay explicit rather than silently falling through
        # generic panel handling.
        self._book_detail_underlay: str | None = None
        # Periodic re-frost while Book Detail stays open with Frosty backdrop mode on — see
        # _arm_book_detail_frost_refresh's own docstring for why this exists (the progress-bar
        # strip is now included in the frost rect, and a ONE-SHOT static frost would freeze its
        # fill for the panel's whole open duration otherwise). Armed at open-start, disarmed on
        # close — never left running with no panel open.
        self._book_detail_frost_refresh_timer = QTimer(main_window)
        self._book_detail_frost_refresh_timer.timeout.connect(
            self._on_book_detail_frost_refresh_tick)
        # The widget that held real Qt focus at the moment Book Detail opened, so closing it
        # (Esc/close button) can hand focus back to the EXACT control the user was on — added
        # 2026-09-09 for Stats' Day/Week/Month row lists (live report: Esc from Book Detail
        # landed on the tab bar instead of the book's own row). Was previously a known,
        # explicitly-flagged gap (see _on_book_detail_hidden's own old comment, now replaced):
        # focus was released but never handed back to the underlay at all, leaving Qt's own
        # focus-fallback behavior to land wherever it pleased — consistent with the tab-bar
        # symptom, since the tab bar is the underlay's own first StrongFocus candidate. A widget
        # reference (not a row index) so it works for ANY future underlay's focus target, not
        # just Stats' row lists specifically. Consuming read, same shape as _book_detail_underlay
        # — a stale reference (the widget's own panel closed/rebuilt meanwhile) must never
        # survive into the next Book Detail open, and a deleted-widget guard is required at the
        # consuming site since Qt C++ objects can be destroyed between the two events.
        self._book_detail_return_focus_widget = None
        # Set by reclip_visual_area_for_layout_change when the layout reflows
        # underneath an open panel; consumed once by
        # _resume_blur_after_book_detail to decide whether the visual_area blur
        # should animate back in (new, never-blurred content underneath) or snap
        # (the same backdrop that was already blurred).
        self._layout_reflowed_under_panel: bool = False
        self.sidebar_animation.finished.connect(self._on_sidebar_hidden)

        # Settle watch for call_when_panels_settled (see that method). Deliberately
        # a predicate re-check rather than a `finished` subscription — QPropertyAnimation
        # .stop() does NOT emit `finished` (verified empirically 2026-07-28; also
        # asserted at theme_manager.py's three stop()-related comments), and
        # blur_animation.stop() runs unconditionally on every panel open
        # (_start_visual_area_blur) and on blur-toggle-off, so a signal-based resume
        # would be silently dropped exactly as it was three times against _fade_anim.
        #
        # timeout is connected ONCE, here, permanently: there is no per-call connect
        # anywhere in this mechanism, so a stale connection is unrepresentable and a
        # double-fire is structurally impossible.
        self._settled_watch_timer = QTimer(main_window)
        self._settled_watch_timer.setSingleShot(True)
        self._settled_watch_timer.setInterval(_SETTLE_POLL_MS)
        self._settled_watch_timer.timeout.connect(self._on_settled_watch_tick)
        self._settled_watch_armed = False
        # List of (coalesce_key, callback) tuples. coalesce_key is None for an
        # ordinary, always-appended waiter; a non-None key replaces any existing
        # waiter with the same key IN PLACE instead of appending a second entry —
        # see call_when_panels_settled's coalesce_key parameter.
        self._panels_settled_waiters: list = []
        # Deferred sidebar state for clicks arriving mid-slide — see _toggle_sidebar.
        # _sidebar_pending_target is the desired FINAL state (absolute), not a queued
        # toggle (relative); queueing toggles produced a runaway open/close cycle.
        self._sidebar_toggle_queued = False
        self._sidebar_pending_target = None

        # Corner-hotspot sidebar trigger (see review/Plan_260809_corner_hotspot_sidebar_trigger.md).
        # opened_via records which method opened the bare sidebar — "right_click" or
        # "hotspot_hover" — read by the hover-out dismiss check (only applies to the
        # hotspot path) and set at the two open call sites (handle_drag_area_right_click's
        # sidebar branch, and SidebarHotspot's fire callback). Cleared in _toggle_sidebar's
        # closing branch, the one site every dismiss path already funnels through.
        self._sidebar_opened_via = None
        # Idle-dismiss timer: a POLL, not a move-event listener. "Any mouse movement
        # anywhere in the window resets the timer" was originally going to be a new
        # QEvent.MouseMove branch on MainWindow's QApplication-level eventFilter, but Qt
        # only ever GENERATES MouseMove events for a widget that has setMouseTracking(True)
        # (or a button held) — confirmed live, offscreen, before writing this — and almost
        # nothing in this app's widget tree has tracking enabled (only total_time_label).
        # A move-event branch would therefore only fire during drags, not ordinary cursor
        # movement, silently failing the "any movement" requirement for the common case.
        # Cascading setMouseTracking onto every relevant widget was the plan's own
        # explicitly-rejected alternative (touches too much). A cheap repeating poll of
        # QCursor.pos() sidesteps the whole tracking-cascade problem and touches nothing
        # else. Armed/disarmed at the same _toggle_sidebar open/close sites as
        # _sidebar_opened_via — mirrors _swatch_leave_backstop_timer's convention
        # (theme_manager.py): a repeating QTimer, started/stopped only on one boolean's
        # transition edges (here, sidebar_expanded), never scattered start/stop calls.
        self._sidebar_idle_poll_timer = QTimer(main_window)
        self._sidebar_idle_poll_timer.setInterval(_SIDEBAR_IDLE_POLL_MS)
        self._sidebar_idle_poll_timer.timeout.connect(self._on_sidebar_idle_poll_tick)
        self._sidebar_last_cursor_pos = None
        self._sidebar_last_movement_ts = None

        # Connect sidebar buttons to panel opening methods
        self.main_window.library_trigger_btn.clicked.connect(self._open_library_flow)
        self.main_window.go_to_library_btn.clicked.connect(self._open_library_flow)
        self.main_window.settings_trigger_btn.clicked.connect(self._open_settings_flow)
        self.main_window.speed_trigger_btn.clicked.connect(self._open_speed_flow)
        self.main_window.sleep_trigger_btn.clicked.connect(self._open_sleep_flow)
        self.main_window.sprint_trigger_btn.clicked.connect(self._open_sprint_flow)
        self.main_window.stats_trigger_btn.clicked.connect(self._open_stats_flow)
        self.main_window.tags_trigger_btn.clicked.connect(self._open_tags_flow)

        # Composited-overlay transport-bar blur (see ui/transport_bar_blur.py and the
        # accepted plan). Comparison branch — see blur-direct-widget for the
        # per-widget-effect alternative.
        self._transport_bar_blur = TransportBarBlurOverlay(main_window)
        # CACHED-FRAME REWORK (2026-07-20): a settings-tab switch (Themes/Look/
        # Library/Audio/Controls) changes what's visible inside settings_panel
        # itself, not inside the transport bar's own tracked widgets — the
        # overlay's _DirtyRectTracker would never see it as a Paint event on any
        # tracked widget, so it needs its own explicit one-time forced refresh.
        # force_refresh_now() itself no-ops if the overlay isn't currently active
        # (e.g. Stats/Tags/Speed/Sleep panels are open instead — mw.tabs only
        # exists inside settings_panel), so this connection is safe to leave
        # permanently wired regardless of which panel is actually open.
        main_window.tabs.currentChanged.connect(
            lambda _index: self._transport_bar_blur.force_refresh_now()
        )

        # Themes-tab frost suppression (2026-08-16): the transport-bar frost is a
        # STATIC grab, re-blurred only on real Paint events from the tracked
        # widgets themselves (see _DirtyRectTracker above) or this file's own
        # force_refresh_now() calls — it has no live-tracking of a theme
        # hover-preview repainting content_container underneath it, and
        # ThemeManager deliberately WITHHOLDS grabs during a preview anyway
        # (hover_active_gate, transport_bar_blur.py ~:1023 — a real, necessary
        # fix for a worse bug: the previewed colors baking permanently into the
        # frost). Net effect on the Themes tab specifically: the frost shows a
        # stale pre-preview frame for the whole preview, snapping to the new
        # colors only in one atomic jump on unhover/commit — visible as a seam
        # (confirmed live, 2026-08-16 session, screenshot). Every other Settings
        # tab (Look/Library/Audio/Controls) has no comparable live-recoloring
        # surface, so the existing static-frost behavior is correct there.
        # Fix is narrower than fixing the staleness: don't show a frost over the
        # Themes tab's content at all, since it's the one tab where "static" is
        # actively misleading. hide_for_panel()/_apply_transport_bar_blur() are
        # both idempotent/self-guarding (see their own docstrings), so toggling
        # on every tab change is safe even if the previous state already
        # matched. Guarded on settings_panel.isVisible() because mw.tabs only
        # exists inside settings_panel and currentChanged should never act while
        # Settings itself isn't the open panel (nothing programmatically calls
        # tabs.setCurrentIndex today, but this keeps the handler inert if that
        # ever changes, rather than relying on that absence).
        main_window.tabs.currentChanged.connect(self._on_settings_tab_changed)

        # Tab-switch snapback interception (2026-08-05) — see
        # _ThemesTabBarInterceptor's own docstring for the full mechanism and why
        # an event filter is required (no Qt "veto this tab change" signal exists).
        # Installed once, permanently, on the tab bar itself — safe to leave wired
        # regardless of which panel is open, since it only ever acts on presses
        # delivered to `mw.tabs.tabBar()` specifically.
        self._themes_tab_bar_interceptor = _ThemesTabBarInterceptor(self)
        main_window.tabs.tabBar().installEventFilter(self._themes_tab_bar_interceptor)

    def _on_settings_tab_changed(self, index: int):
        """Suppress the transport-bar frost on the Themes tab specifically —
        see the connection site's own comment (PanelManager.__init__) for why.
        Only reachable while Settings is the visible panel (mw.tabs lives
        inside settings_panel; nothing else drives its currentChanged).

        Deliberately does NOT revert a live theme hover preview. An earlier version of this
        method did, to cover arrow-key tab switching (which _ThemesTabBarInterceptor could not
        see while it filtered MouseButtonPress only). That worked but looked wrong: currentChanged
        fires AFTER Qt has already switched, so the ~200ms snapback fade played over the tab the
        user had just arrived on, instead of finishing on the tab they were leaving.
        _ThemesTabBarInterceptor now handles the keyboard path too, deferring the switch until
        the revert has settled — so reverting here as well would both double-fire and reintroduce
        the exact after-the-switch timing this was moved away from (its own deferred
        setCurrentIndex re-enters this handler)."""
        if not self.settings_panel.isVisible():
            return
        self._sync_transport_bar_blur_for_settings_tab()

    def _sync_transport_bar_blur_for_settings_tab(self):
        """Show or suppress the transport-bar frost for whichever Settings tab
        is CURRENTLY active, right now. Shared by _on_settings_tab_changed
        (fires on an actual tab switch) and _start_settings_entry's
        slide-finished handler (fires on panel OPEN, where the tab index may
        be unchanged from last time — e.g. Settings was last closed on Themes
        and is reopened still on Themes, so no currentChanged signal will ever
        fire to correct an unconditional show). index == 0 is Themes — same
        identification the rest of this file already uses
        (tabs.currentIndex() == 0, e.g. _BLUR_IN_THEMES_TAB_MS's use site, and
        ThemeManager's own themes_tab_active check)."""
        if self.main_window.tabs.currentIndex() == 0:
            self._transport_bar_blur.hide_for_panel()
        else:
            self._apply_transport_bar_blur(self.settings_panel)

    def _apply_transport_bar_blur(self, panel):
        # Clip to `panel`'s own geometry — nothing renders blurred outside what
        # the panel actually covers (e.g. total_time_label sits at the far right
        # of the content area by layout design, past settings_panel's narrower
        # 90%-width edge; that sliver must stay crisp, not just "technically
        # correct blur that peeks past the panel." Confirmed live, 2026-07-19.)
        if self.config.get_blur_enabled():
            self._transport_bar_blur.show_for_panel(panel)

    # Book Detail sits at y=32; the window is 300x564. See _book_detail_frost_rect.
    _BOOK_DETAIL_FROST_TOP_UNDER_TITLEBAR = 32
    _BOOK_DETAIL_FROST_BOTTOM_INSET = 10
    # 10s: cheap enough to be a non-concern at this cadence (one panel.grab() + one blur
    # pass every 10s, not per-frame), generous enough that the progress bar's fill is never
    # visibly stale for more than a few seconds — Pryme's own call, 2026-09-24 ("it doesn't
    # even need to be fast... 10 second refresh is more than plenty").
    _BOOK_DETAIL_FROST_REFRESH_MS = 10_000

    def _book_detail_frost_rect(self) -> QRect:
        """The region Book Detail's frost should cover, in MAIN_WINDOW coords.

        Differs by what it opened over, because the two cases genuinely look
        different underneath (confirmed live 2026-08-01):

        - Over STATS (or any 90%-width panel): the player screen behind is
          already blurred by that panel's own visual_area blur, but the Stats
          panel ITSELF is sharp — and Stats is most of what is behind Book
          Detail. So the frost must run down to 10px off the bottom, capturing
          Stats as content to be blurred; the bottom 10px is the panel's own
          padding.
        - Over LIBRARY: the library is full-width and opaque, so everything is
          real content that must be frosted.

        WIDTH previously differed here (narrower over a 90%-width underlay, to keep its
        right-hand gutter live and sharp rather than frozen — see git history, fixed
        2026-08-14, superseded 2026-09-24). **Superseded 2026-09-24**: with Book Detail's slide
        now driven by a static-pixmap proxy (`PanelManager._wire_slide_paint_suppression`), the
        frost only firing once the panel was fully on-screen (settle-time) used to mask this
        gutter never getting a live, sharp look until then anyway — moving the frost to
        open-START (same session, for the sliding-proxy fix) made the gutter's absence visible
        for the WHOLE slide, reading as an abrupt late pop rather than the brief flash it used
        to be. Pryme's own call: blur the gutter immediately, matching everywhere else. Full
        width now, in both branches — no more gutter exclusion.

        TOP previously excluded the progress-bar strip (y=32..56) entirely, in both branches —
        the bar genuinely animates while Book Detail is open, and a ONE-SHOT static frost
        covering it would freeze its fill for the panel's whole open duration, visibly JUMPING
        to the real position on close if playback moved during that window (found and fixed
        2026-08-14, "blurred smear across the bar in a screen recording"). **Superseded
        2026-09-24, second correction**: Pryme reported this exclusion ITSELF as a bug — the
        strip should be blurred like everywhere else, not left showing live-but-unblurred
        content while the rest of the backdrop is frosted. A true one-shot static frost can't
        satisfy both "blurred" and "never visibly stale on close" at the same time — the fix
        is `_arm_book_detail_frost_refresh` (below): the WHOLE frost (this strip included) now
        re-grabs and re-composites on a periodic timer while Book Detail stays open, so it's
        blurred from the first frame AND never goes more than one refresh interval stale. `top`
        is now always `_BOOK_DETAIL_FROST_TOP_UNDER_TITLEBAR` (32) in both branches — the
        progress bar is included, not excluded.
        """
        mw = self.main_window
        top = self._BOOK_DETAIL_FROST_TOP_UNDER_TITLEBAR
        bottom_inset = 0 if self._book_detail_underlay == 'library' else self._BOOK_DETAIL_FROST_BOTTOM_INSET
        return QRect(0, top, mw.width(), mw.height() - top - bottom_inset)

    def _apply_transport_bar_blur_full(self, panel):
        """Frost/wash Book Detail's own backdrop. See
        TransportBarBlurOverlay.frost_panel_backdrop for why this cannot reuse the
        shared overlay (Z-order: that overlay is a child of content_container and
        can never rise above a panel parented to main_window).

        Gate CHANGED 2026-09-24, SECOND TIME (was `get_blur_enabled()` alone; briefly widened
        same-session to run for Frosty+Transparent, excluding only Opaque — see git history on
        this branch for that version's own reasoning). REVERTED to Frosty-only per the A/B plan
        settled with Pryme: Transparent mode's brief excursion onto this grab mechanism
        introduced two confirmed regressions — a moving backdrop (this compositing bakes a
        STATIC frost, which reads as visibly wrong once Transparent's whole design premise is a
        backdrop that tracks the live window, not a frozen snapshot) and it did not reduce, by
        any measurement Pryme trusted, the felt jank the paint-suppression proxy was meant to
        fix. Transparent goes back to relying entirely on the panel's own live paint — i.e. no
        static backdrop compositing at all — which is honest to what "Transparent" has always
        meant in this app. Opaque now ALSO runs this (newly added, cleaner A/B benchmark per
        Pryme: "Opaque definitely could use grab rather than native paint. Nothing to lose there"
        [SUPERSEDED 2026-10-20: Opaque removed again — there WAS something to lose; see the
        comment at the gate below]
        — an opaque panel has no translucent wash, so this call degrades to a plain unblurred
        grab of the underlay, harmless and skippable in effect but kept symmetric with Frosty's
        code path rather than special-cased out).

        `extra_mouse_blocked_widgets`: protects the underlay's own hoverable widgets (currently
        just Stats' tab bar — Library has no tab bar, see `_resume_blur_after_book_detail`'s own
        note) from a real hit-testing leak during this call's hide/show grab. See
        `TransportBarBlurOverlay._grab_and_blur`'s docstring for the full mechanism this closes:
        a brief `panel.hide()` (this runs at open-start, slide-finish, and every 10s via the
        refresh timer) un-covers the underlay for the grab instant, and a cursor resting over a
        tab during one of those ticks gets a genuine, un-Leave'd hover that then reads as a
        highlight "appearing from nothing" once Book Detail actually closes (live-reported
        2026-09-24)."""
        backdrop = self.config.get_panel_backdrop()
        # FROSTY ONLY (changed 2026-10-20). Opaque was added to this grab 2026-09-24 as an A/B
        # benchmark arm; that A/B concluded (TODO.md, "source, not mode") that backdrop mode
        # barely moves Book Detail's open cost, and Opaque only paid EXTRA grab cost over
        # Stats. Under an opaque panel the frost is invisible (it composites to solid
        # bg_main), so the grab bought nothing while every one of its hide-based grabs tore
        # down Book Detail's in-progress edits/confirms/tag popup — see
        # TransportBarBlurOverlay._grab_and_blur's `exclude_by_move` note.
        if backdrop != "frosty":
            return
        stats_panel = getattr(self.main_window, 'stats_panel', None)
        extra_widgets = None
        if stats_panel is not None and stats_panel.isVisible():
            extra_widgets = [stats_panel.tabs.tabBar()]
        self._transport_bar_blur.frost_panel_backdrop(
            panel, self._book_detail_frost_rect(), blur=(backdrop == "frosty"),
            extra_mouse_blocked_widgets=extra_widgets)

    def _arm_book_detail_frost_refresh(self) -> None:
        """Start periodic re-frosting while Book Detail is open, added 2026-09-24 alongside
        widening `_book_detail_frost_rect` to include the progress-bar strip. That strip
        genuinely animates during playback — a ONE-SHOT static frost covering it (taken once
        at open-start, refreshed once more at slide-finish, per the existing calls in
        `_start_book_detail_entry`/`_on_book_detail_slide_finished`) would freeze its fill for
        the panel's entire open duration, visibly jumping to the real position on close if
        playback moved meanwhile — this is the EXACT bug `_book_detail_frost_rect`'s old
        progress-bar exclusion existed to prevent (found and fixed 2026-08-14), reintroduced
        the moment the strip was folded into the frost rect.

        Fixed not by excluding the strip again (Pryme's own bug report: it should be blurred
        like everywhere else, not left live-but-unblurred) but by periodically RE-frosting the
        whole rect while the panel stays open — `_BOOK_DETAIL_FROST_REFRESH_MS` (10s) is cheap
        at this cadence (one `panel.grab()` + one blur pass every 10s, not per-frame) and
        generous enough that the fill is never visibly stale for more than a few seconds
        (Pryme's own call: "it doesn't even need to be fast... 10 second refresh is more than
        plenty").

        GATE CHANGED 2026-09-24, SECOND TIME (was `get_blur_enabled()` alone, briefly widened
        same-session to exclude only Opaque — see git history on this branch). REVERTED to
        excluding TRANSPARENT instead, matching `_apply_transport_bar_blur_full`'s own reverted
        gate — see that method's docstring for the full A/B-plan reasoning. Transparent mode
        relies entirely on the panel's own live paint again, so there is no static frost for
        this timer to keep fresh. [SUPERSEDED 2026-10-20: Frosty only now — see
        `_apply_transport_bar_blur_full`'s gate comment.] Opaque now runs it (harmless — see
        `_apply_transport_bar_blur_full`'s reasoning for why an opaque panel tolerates a frost
        child it never shows).

        Called from `_start_book_detail_entry`, once, at open-start — paired with
        `_disarm_book_detail_frost_refresh` in both close paths
        (`_close_book_detail_flow`/`_on_book_detail_hidden`), so the timer is NEVER left
        running once Book Detail is closed."""
        # FROSTY ONLY (2026-10-20) — must match _apply_transport_bar_blur_full's gate; see
        # its comment. tests/test_book_detail_frost_gate.py pins the pair.
        if self.config.get_panel_backdrop() != "frosty":
            return
        self._book_detail_frost_refresh_timer.start(self._BOOK_DETAIL_FROST_REFRESH_MS)

    def _disarm_book_detail_frost_refresh(self) -> None:
        """Stop the periodic re-frost armed by _arm_book_detail_frost_refresh. Safe to call
        unconditionally (QTimer.stop() on an already-stopped timer is a harmless no-op) — every
        close path calls this regardless of whether blur was ever on, so there's no risk of a
        stray running timer surviving a backdrop-mode change mid-session."""
        self._book_detail_frost_refresh_timer.stop()

    def _on_book_detail_frost_refresh_tick(self) -> None:
        """QTimer.timeout handler for the periodic re-frost. Guards against a stray tick
        landing after Book Detail has already closed (e.g. a tick queued just before close,
        delivered after) — re-frosting a hidden/gone panel would be wasted work at best, so
        this bails out via the same isVisible() check every other book_detail-open predicate
        in this class already uses."""
        if not (self.book_detail_panel and self.book_detail_panel.isVisible()):
            self._disarm_book_detail_frost_refresh()
            return
        self._apply_transport_bar_blur_full(self.book_detail_panel)

    def _wire_slide_paint_suppression(self, panel: QWidget, anim: QPropertyAnimation,
                                       proxy: QLabel) -> None:
        """Suppresses `panel`'s own per-frame repaint cost during `anim` by showing a static
        pixmap proxy on top of it instead. Added 2026-09-23 after `_wire_paint_probe` found
        Book Detail's slide repainting individual child widgets dozens to ~200 times in one
        ~300ms slide — see NOTES.md, "General app sluggishness investigation" (2026-09-22/23).

        A REJECTED first design (hide the real panel, swap to the proxy) would have broken
        active_full_panel()/is_any_full_panel_visible() (both read panel.isVisible() directly,
        relied on app-wide for shortcut/overlay gating). This version keeps `panel` visible and
        moving EXACTLY as before this method existed — `anim` still targets `panel`'s own `pos`;
        `panel.isVisible()`/`.pos()` are never touched here. `panel.setUpdatesEnabled(False)`
        stops IT from processing paint events (it still moves; Qt just doesn't repaint its
        contents) while `proxy` — a plain QLabel, raised above `panel`, followed via
        `valueChanged` — is the only thing that visibly repaints each tick.

        NAMED, UNRESOLVED RISK: whether the panel's own vacated backing-store position can
        produce a one-frame trail before the proxy's valueChanged-driven move catches up (Qt's
        exact internal ordering here was not verified from documentation). Live-check this
        explicitly (frame-stepped screen recording) — do not assume it's clean.

        OPEN vs. CLOSE need different pixmap sources (found live, corrected same session):
        Book Detail's `rgba(bg_main, panel_opacity_hover)` background (WA_StyledBackground) is
        genuinely translucent — it blends against whatever's already in the window's backing
        store behind it. A plain `panel.grab()` renders the panel in ISOLATION, with nothing to
        blend against, so the wash reads flatly opaque until the panel's own live paint (or the
        settle-time `frost_panel_backdrop`, Frosty-mode only) resumes. On CLOSE this is a
        non-issue — the panel has already been open/settled with a correct blend baked into its
        live paint, so `panel.grab()` there is already correct. On OPEN, nothing has been
        blended yet for this open cycle, so this method instead grabs the UNDERLAY at the
        panel's destination rect (no hide/show needed — confirmed the real panel sits off-screen
        at `x=panel_w` at this exact moment, per `_start_book_detail_entry`'s
        `.move(panel_w, ...)` before `.show()`) and composites Book Detail's own wash onto it —
        blurred first if Frosty mode (via `_blur_pixmap`, the STANDALONE function, deliberately
        NOT `_grab_and_blur`'s hide/show-coupled wrapper — that primitive carries dated fixes
        for cursor/focus/hit-testing side effects of hiding an ALREADY-OPEN, interactive panel,
        none of which apply or have been verified at this new, off-screen, pre-slide moment).
        Opaque mode skips the wash compositing entirely (a plain grab is already correct — an
        opaque panel has no translucency to lose).

        THIRD CORRECTION (2026-09-24, live-reported): Transparent mode is the deliberate control
        group for the A/B this whole mechanism exists to run (see _apply_transport_bar_blur_full's
        own docstring) — it must NOT get a static backdrop at all, blurred or not, or it stops
        being a clean "does paint suppression help" control and starts testing something else.
        But `panel.grab()`'s isolation problem (documented above: a translucent wash has nothing
        to blend against in an isolated grab) doesn't go away just because Transparent has no
        static backdrop layer to fix it with — the proxy would read flatly opaque for the whole
        slide, then visibly pop transparent once live paint resumed at finish. Rather than solve
        that with more compositing (which is exactly the static-backdrop machinery Transparent is
        supposed to be free of), this method now skips the whole proxy/suppression mechanism for
        Transparent mode: `panel` keeps live-painting through the slide, unmodified, exactly as it
        did before this feature existed. This is what makes Transparent a genuine control — its
        child-repaint cost is real and unsuppressed, which is the whole point of comparing it
        against Frosty/Opaque."""
        state = {"active": False}

        def _on_start():
            if self.config.get_panel_backdrop() == "transparent":
                return
            # Opening iff the animation's END value's x is 0 (the panel's on-screen rest
            # position) — closing targets x=panel_w (off-screen), per _start_book_detail_entry/
            # _close_book_detail_flow's own setEndValue calls.
            #
            # SECOND CORRECTION (2026-09-23, live-reported with screenshots): a prior version
            # of this branch grabbed the underlay and composited the panel's translucent wash
            # onto it for the OPEN case specifically, to fix an opaque-then-pop regression the
            # FIRST correction introduced. That produced a WORSE bug — the composited pixmap
            # never had the panel's own real CONTENT (cover/title/stats/tags) painted into it,
            # so the proxy showed a tinted, empty backdrop for the whole slide. Pryme's own
            # correction: the backdrop was never supposed to slide at all — it's meant to be
            # STATIC (matching frost_panel_backdrop's own established behavior: "STATIC while
            # the panel is open, an accepted tradeoff"). The fix is NOT in this pixmap — it's
            # that the EXISTING frost/wash backdrop (self._apply_transport_bar_blur_full) must
            # now fire at slide-START too (see _start_book_detail_entry's own open-start
            # call, added alongside this fix), not only at slide-finish. Once that static
            # backdrop exists as its own layer (a child of `panel`, unaffected by
            # setUpdatesEnabled(False) below since it's a sibling in panel's child stack, not
            # something panel.paintEvent itself draws), this proxy needs nothing more than the
            # panel's own real content — a plain panel.grab() is correct for BOTH directions,
            # same as before either correction. Do not re-introduce underlay compositing here.
            # (Transparent mode never reaches this point — see THIRD CORRECTION above.)
            pixmap = panel.grab()
            proxy.setPixmap(pixmap)
            proxy.setFixedSize(panel.size())
            proxy.move(panel.pos())
            proxy.raise_()
            proxy.show()
            panel.setUpdatesEnabled(False)
            state["active"] = True

        def _on_value_changed(value):
            if not state["active"]:
                return
            proxy.move(value)

        def _on_finished():
            if not state["active"]:
                return
            state["active"] = False
            panel.setUpdatesEnabled(True)
            panel.update()
            proxy.hide()

        orig_start = anim.start

        def _traced_start(*args, **kwargs):
            _on_start()
            return orig_start(*args, **kwargs)

        anim.start = _traced_start
        anim.valueChanged.connect(_on_value_changed)
        anim.finished.connect(_on_finished)

    def _clear_transport_bar_blur(self):
        self._transport_bar_blur.hide_for_panel()

    def _park_blur_for_book_detail(self):
        """Stop grabbing when Book Detail opens over a panel, but KEEP the
        transport overlay's last frame on screen as a static backdrop.

        Book Detail is full window width at y=32 and content_container starts at
        y=56, so it covers the cover art, the transport bar, the carousel AND the
        underlying panel entirely — nothing NEW the underlay's blur produces can
        be seen, which is why the grabbing must stop.

        Leaving grabbing running is not merely wasted work. The transport
        overlay's _active_panel is still the UNDERLYING panel, so _grab_and_blur
        keeps hiding Stats (not Book Detail) and grabbing main_window — which
        photographs Book Detail INTO the cached pixmap and composites it back
        underneath itself. Measured self-sustaining at ~64ms / ~15 grabs per
        second (NOTES.md, 2026-07-27, "grab feedback loop").

        But DISCARDING the already-grabbed frame was never required by that, and
        it is what produced a visible crisp frame on both the open and the close
        (reported live 2026-08-14). park_for_panel stops the grabbing and leaves
        the frame up; Book Detail's own geometry occludes it on the way in and
        uncovers it on the way out, with no mask and no per-frame work, because
        the overlay is a child of content_container while Book Detail is a child
        of main_window raised above it.

        THE VISUAL_AREA BLUR IS LEFT UP ENTIRELY — no setBlurRadius(0), no
        _clear_visual_area_clip, here or anywhere on the Book Detail path. Only
        the ANIMATION is stopped, so no tween is left running under the panel.

        Zeroing it at open-START is what actually produced the reported crisp
        flash (2026-08-14): the parked overlay only covers the transport strip
        (measured QRect(10, 300, 260, 198)), while visual_area owns everything
        from y=56 up to it — so dropping that radius snapped ~2/3 of the window
        sharp while Book Detail was still sliding over it.

        The "double blur" this teardown was believed to prevent — _grab_and_blur
        baking a blurred visual_area into Book Detail's frost, then blurring it
        again — does not occur on this path. frost_panel_backdrop's grab hides
        only _active_panel (Book Detail itself), so what it photographs is the
        UNDERLAY, and Stats/Library are opaque over the whole visual_area region.
        A live visual_area blur is simply not in that grab. Verified live: moving
        the teardown to slide-FINISHED (immediately before the grab) fixed the
        open but made the CLOSE read crisp-then-blur; removing it altogether is
        correct on both transitions.

        Unconditional on get_blur_enabled(): both calls below are a no-op when
        blur is off (park_for_panel early-exits on _active=False, and stopping an
        idle animation is free), so a mid-session backdrop-mode change cannot
        strand a live blur.

        blur_animation.stop() here emits no `finished` — nothing subscribes to
        learn about it (see the _settled_watch_timer note in __init__), and it is
        the same call _start_visual_area_blur already makes.

        Symmetric with _resume_blur_after_book_detail.
        """
        self._transport_bar_blur.park_for_panel()
        self.blur_animation.stop()

    def _resume_blur_after_book_detail(self):
        """Re-arm the underlying panel's blur once Book Detail is fully hidden.
        Symmetric with _park_blur_for_book_detail.

        Runs from _on_book_detail_hidden (AFTER .hide()), never from
        _close_book_detail_flow: a grab taken while Book Detail is still sliding
        out would photograph it into the cache, because _active_panel would by then
        be the underlying panel again and _grab_and_blur only ever hides
        _active_panel. That constraint is why the RE-GRAB waits until here — the
        parked frame itself stays on screen throughout the slide-out and needs no
        grab at all, which is what removes the close-side crisp flash.

        The isVisible() re-check is load-bearing, not defensive padding.
        _on_open_tag_manager_from_detail (app.py) calls hide_all_panels() — closing
        BOTH Book Detail and Stats — then opens Tags 320ms later; and
        _on_tag_filter_requested closes Book Detail then opens Library. Without the
        check those paths would re-blur a panel that is mid-close or already hidden,
        stranding a frozen overlay over the transport bar with _active_panel
        pointing at an invisible widget.

        Cache invalidation is NOT free any more (it was, while this method always
        went through hide_for_panel + a fresh show_for_panel — that pairing was
        itself the invalidation). Under parking the pixmap survives the whole Book
        Detail session, so:
          - the reuse path (unpark_for_panel) re-arms tracking and then issues one
            force_refresh_now() to reconcile anything that changed while parked;
          - the early-return path MUST call discard_parked_frame(), or those
            hide_all_panels flows above leave a frozen blurred band over the
            transport bar with nothing left to clear it. discard_parked_frame()
            rather than hide_for_panel(): by the time this fires the overlay may
            legitimately belong to another panel (Library), and dropping a park
            that is no longer ours would kill that panel's live overlay.
        Stale-frame invalidation WHILE parked (book excluded / cover changed from
        inside Book Detail) is deliberately not implemented — see TODO.md.

        Library is deliberately absent from the map: it is full-width and opaque and
        never had either blur on open (see _apply_visual_area_clip's LIBRARY-PANEL
        EXCLUSION), so there is nothing to restore for it.
        """
        # Consuming read — same shape as take_dirty_union. A stale key must never
        # survive into the next Book Detail open.
        key, self._book_detail_underlay = self._book_detail_underlay, None
        panel = {
            'stats': self.stats_panel,
            'tags': self.tags_panel,
            'settings': self.settings_panel,
            'speed': self.speed_panel,
            'sleep': self.sleep_panel,
            'sprint': self.sprint_panel,
        }.get(key)
        if panel is None or not panel.isVisible():
            self._transport_bar_blur.discard_parked_frame()
            return
        if not self._transport_bar_blur.unpark_for_panel(panel):
            # Nothing reusable was parked (blur was off, the underlay was opaque,
            # or the park was already dropped) — fall back to the original path.
            self._apply_transport_bar_blur(panel)
        # Re-assert the visual_area clip and radius. Normally a no-op — the Book
        # Detail path never drops them (see _park_blur_for_book_detail) and
        # _apply_visual_area_clip recomputes from live geometry — but it is what
        # recovers the blur if anything else zeroed it while Book Detail was open.
        #
        # animate=False for an ORDINARY close: the backdrop being returned to was
        # already blurred the whole time, so replaying the 1500ms build reads as a
        # re-render rather than a softening.
        #
        # animate=True when the layout REFLOWED while the panel was open (the
        # playing book was removed, so the ambient carousel now occupies a region
        # that never had blur on it). That content is genuinely new and unblurred,
        # and snapping it to full radius in one frame is the abrupt transition
        # reported live 2026-08-14 — main animates here and reads better for
        # exactly this case. The flag is consumed so the next close goes back to
        # the snap.
        reflowed, self._layout_reflowed_under_panel = (
            self._layout_reflowed_under_panel, False)
        self._start_visual_area_blur(panel, animate=reflowed, from_zero=reflowed)

    def _start_visual_area_blur(self, panel, animate: bool = True,
                                from_zero: bool = False):
        """Set the clip and run the visual_area blur-in — called ONLY from a
        panel's slide-FINISHED callback, never at panel-open.

        TIMING IS LOAD-BEARING (found live 2026-07-27): starting this at
        panel-open meant the cover art / theme background / quote card began
        blurring while the panel was still sliding, so the blur visibly ran
        ahead of the panel and briefly exposed a hard-edged clip boundary over
        content the panel had not covered yet. The transport bar has always
        applied its blur from the slide-finished callback
        (_apply_transport_bar_blur); this matches that, so the two halves of the
        window blur together once the panel is settled. Panel CLOSE is
        unaffected — clearing immediately at close-start is correct and already
        matches the transport bar.

        `animate=False` snaps straight to the target radius instead of tweening.
        For RE-establishing a blur the user has already seen — returning from
        Book Detail to the Stats/Tags panel underneath — the softening
        transition is what makes a genuine panel-open feel gentle, but on the
        way back the blurred backdrop is already what they expect to find, so
        replaying the 1500ms build reads as a needless re-render. Genuine opens
        keep the default. The clip is still applied either way; only the ramp is
        skipped.
        """
        if not self.config.get_blur_enabled():
            return
        self._apply_visual_area_clip(panel)
        target = 8 if panel is self.tags_panel else 10
        if not animate:
            self.blur_animation.stop()
            self.blur_effect.setBlurRadius(target)
            # The carousel must get the FINAL radius here, not the current one —
            # passing an intermediate value would leave it sharp for a frame,
            # which is the very thing the sync call below exists to prevent.
            self.main_window.sync_carousel_blur(target, True)
            return
        # from_zero: force the ramp to start at 0 instead of the effect's current
        # radius. Needed when the blur was never dropped but the CONTENT beneath
        # it is new — the playing book removed, the ambient carousel now under a
        # region that was blurred for the old layout. The radius is already at
        # target in that case, so the default setStartValue(blurRadius()) makes
        # this a 10->10 no-op that renders as a snap (reported live 2026-08-14;
        # main gets a real fade here only because it zeroes the radius at
        # panel-open, which this branch deliberately does not).
        start = 0.0 if from_zero else self.blur_effect.blurRadius()
        if from_zero:
            self.blur_effect.setBlurRadius(0.0)
        # The carousel is a sibling of visual_area with its own effect — set its
        # clip now so it blurs in step rather than staying sharp.
        self.main_window.sync_carousel_blur(start, True)
        self.blur_animation.stop()
        self.blur_animation.setDuration(self._blur_in_duration_for(panel))
        self.blur_animation.setStartValue(start)
        self.blur_animation.setEndValue(target)
        self.blur_animation.start()

    def _blur_in_duration_for(self, panel):
        """Blur-in duration for `panel` — shorter when opening onto the Themes tab.

        See _BLUR_IN_THEMES_TAB_MS for the measurements and the rationale. In short:
        a theme hover cannot preview until the blur settles (the animation guard in
        ThemeManager._on_theme_changed, which must stay — a restyle landing mid-tween
        freezes the blur ~240ms), so on the one tab where hovering is the expected
        next action the 1500ms blur-in reads as a broken first hover.

        Only the tab ACTIVE AT OPEN TIME matters: switching to the Themes tab while
        Settings is already open starts no blur-in, so there is nothing to shorten.

        Tab test mirrors ThemeManager._on_theme_changed's own `themes_tab_active`
        (Themes is index 0) rather than inventing a second convention — but without
        its `settings_panel.isVisible()` clause, since this runs from the
        slide-finished callback where the panel's visibility state is not the thing
        being asked about.
        """
        if panel is not self.settings_panel:
            return _BLUR_IN_MS
        tabs = getattr(self.main_window, 'tabs', None)
        if tabs is not None and tabs.currentIndex() == 0:
            return _BLUR_IN_THEMES_TAB_MS
        return _BLUR_IN_MS

    def blurred_panel(self):
        """The panel the visual_area blur is currently clipped to, or None.

        Used by MainWindow._carousel_clip_rect: the carousel is a SIBLING of
        visual_area with its own effect, so it needs to know which panel edge to
        clip against. Returns None for the library panel — it is full-width and
        opaque, so nothing behind it blurs (see _apply_visual_area_clip).

        BOOK DETAIL WINS over whatever it is covering (2026-08-14). It is
        full-width from y=32 down, so when it is open it — not the underlay — is
        the panel whose edge the carousel must clip against. Checking it first
        matters because Book Detail opens OVER another panel and both are
        visible at once: returning the underlay (Stats) made
        _carousel_clip_rect intersect the carousel's rect with STATS' rect,
        which do not overlap, yielding an EMPTY clip. An empty clip means "blur
        nothing" (ClippedBlurEffect.draw draws the source straight through), so
        a carousel built while Book Detail was open came up sharp inside an
        otherwise-blurred region — the stale band reported live 2026-08-14 after
        removing the playing book from Book Detail over Stats, which builds the
        carousel underneath the still-open panel.
        """
        if self.book_detail_panel.isVisible():
            return self.book_detail_panel
        for panel in (self.settings_panel, self.speed_panel, self.sleep_panel, self.sprint_panel,
                      self.stats_panel, self.tags_panel):
            if panel.isVisible():
                return panel
        return None

    def _apply_visual_area_clip(self, panel):
        """Confine visual_area's blur to the region `panel` actually occludes, so
        the sliver beside the panel stays sharp (cover art / theme bg_image /
        quotes all live in that one widget). Called from _start_visual_area_blur
        at slide-finished; paired with _clear_visual_area_clip on close.

        LIBRARY-PANEL EXCLUSION — the library panel is full window width
        (setFixedWidth(window_w) in _update_panel_geometry, unlike every other
        panel's int(width * 0.9)) and fully opaque, so it occludes everything:
        there is no sliver to keep sharp and nothing blurred under it is ever
        visible. It is therefore skipped ENTIRELY (null clip = no blur), not
        given a full-rect clip.

        That distinction is load-bearing, not an optimization (found live
        2026-07-27): a full-rect clip made the ambient CoverCarousel — which
        scrolls at ~30fps beneath visual_area in the no-book state — ghost and
        then freeze in place while the unblurred sliver kept animating. Blurring
        a region nobody can see, over live scrolling content, bought nothing and
        broke the carousel. Keeping this as its own explicit branch also means a
        future change to the library panel's width cannot silently reroute it
        into generic clip math.
        """
        mw = self.main_window
        effect = getattr(mw, 'blur_effect', None)
        if effect is None or not hasattr(effect, 'set_clip_rect'):
            return
        if panel is self.library_panel:
            effect.set_clip_rect(None)   # null = blur nothing
            return

        va = mw.visual_area
        common = mw.content_container
        panel_rect = panel_rect_in_common_space(panel, common)
        # panel_rect is in content_container space; the effect's clip must be in
        # visual_area-LOCAL space.
        va_top_left = va.mapTo(common, QPoint(0, 0))
        local = panel_rect.translated(-va_top_left.x(), -va_top_left.y())
        clip = local.intersected(va.rect())
        effect.set_clip_rect(clip)
        # [SEAM-TRACE] temporary, env-gated (2026-08-15) — chasing a horizontal
        # seam under the cover art in the no-book/carousel state, panel open, no
        # Book Detail involved. Logs the clip actually applied and va's own
        # geometry so it can be checked against what's visually seen. Remove
        # once the seam is found.
        if _GRAB_TRACE_ENABLED:
            logger.warning(
                f"[SEAM-TRACE] _apply_visual_area_clip panel={panel.objectName()!r} "
                f"va_size={va.size()} va_top_left={va_top_left} clip={clip}"
            )

    def _clear_visual_area_clip(self):
        effect = getattr(self.main_window, 'blur_effect', None)
        if effect is not None and hasattr(effect, 'set_clip_rect'):
            effect.set_clip_rect(None)
        # Clear the sibling carousel's clip too, or it keeps a blurred band after
        # the panel is gone.
        self.main_window.sync_carousel_blur(0.0, False)

    def reclip_visual_area_for_layout_change(self):
        """Recompute both blur clips against the CURRENT layout, panel unchanged.

        _apply_visual_area_clip has exactly one other caller
        (_start_visual_area_blur, at panel slide-finish), so the clips are
        computed once when a panel opens and never revisited. That is fine while
        the layout underneath is static — but removing the playing book reflows
        it while a panel is still open, and both clips then describe geometry
        that no longer exists.

        Measured live 2026-08-14, at the instant the book was excluded with Book
        Detail open over Stats:

            va_clip  = QRect(0, 0, 260, 280)   <- COVER_AREA_HEIGHT, has-book layout
            car_clip = QRect(0, 0, 0, 0)       <- empty: carousel blurs nothing

        visual_area then grows to 454px for the no-book state and the carousel
        appears, but nothing recomputes either clip until the panel closes and
        _start_visual_area_blur finally runs (measured: va_clip 454 by then). In
        between, visual_area is blurred only in its top 280px with everything
        below sharp, and the carousel is entirely sharp — the "top part
        scrolling without blur, bottom stale" artifact.

        Deliberately NOT a clear: the panel is still open and its backdrop
        should still be blurred. This recomputes against the new geometry rather
        than dropping the blur, so nothing is grabbed and nothing flashes.
        """
        panel = self.blurred_panel()
        if panel is None or not self.config.get_blur_enabled():
            return
        self._apply_visual_area_clip(panel)
        # Radius is already correct and unchanged — only the clips are stale.
        self.main_window.sync_carousel_blur(self.blur_effect.blurRadius(), True)
        # Tell the close path that what is underneath is no longer the backdrop
        # the user last saw blurred — see _resume_blur_after_book_detail, which
        # animates rather than snaps when this is set.
        self._layout_reflowed_under_panel = True

    def apply_blur_live(self, enabled: bool):
        """Apply or clear blur on the ALREADY-OPEN Settings panel the instant the
        Settings > Blur toggle is clicked, without needing a close/reopen. The
        toggle lives in the Settings panel, so settings_panel is the only panel
        this is ever reachable from — scope to it, don't try to handle others.

        Covers both blur mechanisms: the transport-bar composited overlay (the
        primary one — _apply/_clear_transport_bar_blur) AND the cover-image
        blur_effect (blur_animation 0<->10). The blur_effect ON side mirrors the
        existing OFF side in MainWindow.set_blur_selection (which already zeroes
        the radius when the toggle goes Off); this adds the missing ON direction so
        Off->On also re-blurs the cover image live (previously only On->Off worked).

        REQUIRED animation guard: bail if any panel/sidebar slide is running.
        Applying/clearing blur mid-animation is not something the two-button toggle
        UI should ever trigger, but 'this state is unreachable so no guard needed'
        is exactly the assumption that caused three regressions this session — the
        guard is one cheap line, so it's here, not assumed."""
        if not self.settings_panel.isVisible():
            return
        if self.is_any_panel_animating():
            return
        if enabled:
            # Themes-tab frost suppression (2026-08-16) — see
            # _sync_transport_bar_blur_for_settings_tab's own docstring. Toggling
            # Blur On while sitting on the Themes tab must not show the frost
            # there either.
            self._sync_transport_bar_blur_for_settings_tab()
            # Immediate (not deferred to a slide-finished callback) is correct
            # here: the panel is already open and settled — this is the live
            # Settings > Blur toggle, not a panel-open transition.
            self._start_visual_area_blur(self.settings_panel)
        else:
            self._clear_transport_bar_blur()
            self.blur_animation.stop()
            self.blur_effect.setBlurRadius(0)
            self._clear_visual_area_clip()

    def _toggle_sidebar(self):
        """Slides the sidebar in or out.

        A toggle requested while the slide is running defers to a TARGET STATE, not a
        queued toggle (2026-07-28, second iteration — the first shipped a worse bug).

        History, because the first attempt is an instructive failure. Originally this
        returned early and silently discarded the click: measured live, 5 of 25 sidebar
        right-clicks (20%) vanished, four of them arriving inside the 300ms slide
        against a 408ms median click interval. Queueing the toggle instead fixed the
        drop and introduced something worse: each replay STARTED A NEW SLIDE, which
        then caught the next click, which queued, which replayed... Measured in the
        very next session: eight consecutive toggles at 306-322ms intervals, the
        sidebar sliding open/closed continuously and always one step behind the user,
        while the log cheerfully reported 26 clicks -> 26 toggles with zero losses.
        Reported as "26 clicks, 26 toggles is a problem by itself" — correctly.

        The root error was queueing a RELATIVE operation. A toggle means "invert
        whatever the state is"; deferring several of them makes the outcome depend on
        how many happened to land mid-slide, which is not what the user is expressing.
        They are asking for the sidebar to END UP somewhere. So the deferred value is
        now the desired FINAL state, and repeated clicks during one slide simply
        overwrite it — two clicks during a slide cancel out (target flips back), which
        is what "I clicked twice, it should be where it started" actually means.

        This also stops the self-perpetuating cycle at its source: if the pending
        target already matches where the running slide is heading, there is nothing to
        replay and no new slide is started.
        """
        if self.sidebar_animation.state() == QAbstractAnimation.State.Running:
            # Where the running slide is heading — NOT the current flag, which has
            # already been flipped by whoever started it.
            in_flight_target = self.sidebar_expanded
            # Each click during the slide inverts the pending target. First click:
            # opposite of the in-flight target. Second: back to it (a no-op, cancelled).
            base = (self._sidebar_pending_target
                    if self._sidebar_pending_target is not None else in_flight_target)
            self._sidebar_pending_target = not base
            logger.debug(
                f"t={time.perf_counter():.6f} [_toggle_sidebar] DEFERRED — slide in "
                f"flight heading to expanded={in_flight_target}; "
                f"pending_target={self._sidebar_pending_target}"
            )
            if self._sidebar_toggle_queued:
                return          # a replay is already scheduled; it reads the target
            self._sidebar_toggle_queued = True

            def _replay():
                self._sidebar_toggle_queued = False
                target = self._sidebar_pending_target
                self._sidebar_pending_target = None
                if target is None:
                    return
                # Re-check rather than assuming: the settle may arrive with another
                # animation still running (call_when_panels_settled waits on ALL of
                # them), or state may have changed via another path in the meantime.
                if self.sidebar_animation.state() == QAbstractAnimation.State.Running:
                    return
                if target == self.sidebar_expanded:
                    # Already where the user asked for — an even number of clicks
                    # landed during the slide and cancelled out. Starting a slide here
                    # is what produced the runaway open/close cycle.
                    logger.debug(
                        f"t={time.perf_counter():.6f} [_toggle_sidebar] deferred target "
                        f"already satisfied (expanded={self.sidebar_expanded}) — no slide"
                    )
                    return
                logger.debug(
                    f"t={time.perf_counter():.6f} [_toggle_sidebar] applying deferred "
                    f"target={target} (expanded={self.sidebar_expanded})"
                )
                self._toggle_sidebar()

            self.call_when_panels_settled(_replay)
            return
        logger.debug(
            f"t={time.perf_counter():.6f} [_toggle_sidebar ENTRY] "
            f"sidebar_expanded(pre)={self.sidebar_expanded} "
            f"branch={'opening' if not self.sidebar_expanded else 'closing'}"
        )
        # Opening the sidebar (the gateway to every panel, and the target of a
        # right-click on the drag area / future panel hotkeys) while a main-
        # window theme fade is in flight must complete that fade cleanly first
        # — otherwise the fade's slider color animation is left stranded at an
        # old/intermediate color while the rest of the UI is already the new
        # theme ("mulatto theme"). complete_main_fade is a no-op if no fade is
        # running. See NOTES.md 2026-06-19. NOTE: this is the main-window path —
        # do NOT substitute snap_theme_forward here (that's Settings-oriented).
        tm = getattr(self.main_window, 'theme_manager', None)
        if tm:
            tm.complete_main_fade()

        sidebar_y = 32 + 24
        width = self.sidebar.width()

        if not self.sidebar_expanded:
            logger.debug(f"t={time.perf_counter():.6f} [sidebar.raise_ BEFORE]")
            self.sidebar.raise_()
            logger.debug(f"t={time.perf_counter():.6f} [sidebar.raise_ AFTER]")
            self.sidebar_animation.setStartValue(QPoint(-width, sidebar_y))
            self.sidebar_animation.setEndValue(QPoint(0, sidebar_y))
            self.sidebar_expanded = True
            # Idle-dismiss poll arms on every open, regardless of opened_via — see
            # _SIDEBAR_IDLE_DISMISS_MS and _sidebar_idle_poll_timer's own comment.
            self._sidebar_last_cursor_pos = QCursor.pos()
            self._sidebar_last_movement_ts = time.monotonic()
            self._sidebar_idle_poll_timer.start()
            # Disarm the hotspot's re-arm gate if the cursor is currently resting inside
            # it — this must happen on ANY open transition, not just a hotspot-triggered
            # one, or the idle-timer-close loop the re-arm rule exists to prevent can
            # still occur via a right-click open. See sidebar_hotspot.py's docstring.
            hotspot = getattr(self.main_window, 'sidebar_hotspot', None)
            if hotspot is not None:
                hotspot.disarm_if_cursor_inside()
        else:
            self.sidebar_animation.setStartValue(QPoint(0, sidebar_y))
            self.sidebar_animation.setEndValue(QPoint(-width, sidebar_y))
            self.sidebar_expanded = False
            self._sidebar_idle_poll_timer.stop()
            self._sidebar_opened_via = None

        self.sidebar_animation.start()
        # SIDEBAR-VISIBILITY PROBE (2026-07-28). "App start: right click, no sidebar,
        # right click, no sidebar, right click, finally sidebar" — the flag flips and
        # the animation runs on ALL THREE, so the failure is between starting the
        # slide and the widget being on screen. Records what the animation was
        # actually told to do and where the widget is when it finishes, since three
        # hypotheses (width==0, _on_sidebar_hidden, resize_panels) have already been
        # ruled out by reading code alone.
        def _probe(_pre=self.sidebar_expanded):
            try:
                logger.warning(
                    f"[SIDEBAR-VIS] settled expanded={_pre} "
                    f"pos={self.sidebar.pos()} size={self.sidebar.size()} "
                    f"visible={self.sidebar.isVisible()} hidden={self.sidebar.isHidden()} "
                    f"parent_visible={self.sidebar.parentWidget().isVisible() if self.sidebar.parentWidget() else None} "
                    f"end={self.sidebar_animation.endValue()} "
                    f"opacity={self.sidebar.windowOpacity()}"
                )
            except (AttributeError, RuntimeError):
                pass
        QTimer.singleShot(340, _probe)
        logger.warning(
            f"[SIDEBAR-VIS] start expanded={self.sidebar_expanded} "
            f"from={self.sidebar_animation.startValue()} to={self.sidebar_animation.endValue()} "
            f"pos_now={self.sidebar.pos()} visible={self.sidebar.isVisible()} "
            f"raised_above={self.sidebar.parentWidget().children().index(self.sidebar) if self.sidebar.parentWidget() else None}"
        )

    def _open_library_flow(self):
        # One overlay at a time: drop this open if any overlay is already present, mid-slide,
        # or a sidebar-handoff open is committed. A settled-open sidebar with nothing pending
        # is NOT blocked (that's the legitimate sidebar-button path). See is_overlay_open_or_committed.
        if self.is_overlay_open_or_committed():
            return
        self.main_window.library_panel.clear_tag_filter_if_active()
        self._complete_main_fade()
        self.library_panel.cancel_preload()
        self.main_window._save_current_progress()
        if self.sidebar_expanded:
            self._pending_panel_open = "library"
            if not self._sidebar_panel_signal_connected:
                self.sidebar_animation.finished.connect(self._on_sidebar_closed_for_panel)
                self._sidebar_panel_signal_connected = True
            self._toggle_sidebar()
        else:
            self._start_library_entry()

    def _start_library_entry(self):
        logger.debug(f"[STUTTER-TRACE] t={time.perf_counter():.6f} _start_library_entry: ENTRY")
        if _STUTTER_PROFILE_ENABLED:
            self._stutter_profiler = cProfile.Profile()
            self._stutter_profiler.enable()
        self._flush_pending_restyle()  # before show() — see _flush_pending_restyle
        # Sync folder-button state to the live scan status — a scan may already be
        # running when the panel opens, in which case the buttons open disabled.
        self.main_window._set_scan_buttons_enabled(
            not self.main_window.scanner.is_running()
        )
        panel_w = self.main_window.width()
        sidebar_y = 32 # Start right under the TitleBar, covering the progress bar
        self.library_panel.setFixedWidth(panel_w)
        self.library_panel.setFixedHeight(self.main_window.height() - sidebar_y)
        self.library_panel.move(-panel_w, sidebar_y)
        self.library_panel.show()
        self.library_panel.raise_()

        # On a process's FIRST-EVER Library show, LibraryPanel.showEvent defers a
        # geometry-correcting re-run of _apply_view_mode by one event-loop tick (see
        # that method's own comment — a pre-existing, unrelated fix for List/Square
        # mode's top-margin remainder math needing real, settled layout to compute
        # correctly). Grabbing the viewport for the slide-paint-suppression proxy
        # BEFORE that correction lands captures a viewport 1px short — confirmed live,
        # 2026-09-25: only reproduces on a process's first Library open, and produces a
        # visible ~1-2px vertical pop at handoff once the corrected viewport takes
        # over. So: defer the grab (and the animation start with it) by that same one
        # tick, but ONLY on this first-open case — every subsequent open already reads
        # correct geometry synchronously (confirmed live) and stays on the fast,
        # zero-added-latency path.
        if self.library_panel._first_show_geometry_settled:
            self._finish_library_entry_animation(panel_w, sidebar_y)
        else:
            # A DEDICATED flag, not _is_animating: _is_animating stays True for
            # library_panel's whole open transition, INCLUDING scenarios (a stuck
            # `finished` connection) that _close_library_flow's own teardown must be
            # able to recover from — reusing it here to guard this narrow pre-start
            # gap would also block that recovery path for the rest of the session.
            # This flag is true ONLY between scheduling the deferred call below and
            # _finish_library_entry_animation actually running, and is checked by
            # _close_library_flow as an ADDITIONAL condition alongside its existing
            # animation.state() == Running check (see that method).
            self._library_entry_animation_pending = True
            QTimer.singleShot(
                0, lambda: self._finish_library_entry_animation(panel_w, sidebar_y)
            )

    def _finish_library_entry_animation(self, panel_w, sidebar_y):
        """Sets up the slide-paint-suppression proxy (List mode only) and starts the
        library_panel_animation slide. Split out of _start_library_entry so the first-
        open case can defer this whole block by one event-loop tick — see that
        method's own comment for why."""
        self._library_entry_animation_pending = False
        # List-mode-only slide paint suppression: grab the viewport NOW (content is already
        # current — see NOTES.md/the design plan for why open-start beats close-and-store) with
        # hover suppressed, and show a static proxy over the viewport for the duration of the
        # slide instead of letting QListView repaint its full, expensive delegate-painted content
        # on every position tick. Measured: QListView paint cost in List mode was 149-187ms of a
        # ~300ms slide; the grab itself costs ~25-38ms steady-state, paid once up front. Any
        # failure here must not prevent the slide itself from starting — see the except below.
        if self.config.get_library_view_mode() == "List":
            delegate = self.library_panel._delegate
            try:
                delegate._suppress_hover_for_grab = True
                try:
                    pixmap = self.library_panel._list_view.viewport().grab()
                finally:
                    delegate._suppress_hover_for_grab = False
                top_left = self.library_panel._list_view.viewport().mapTo(
                    self.library_panel, QPoint(0, 0)
                )
                viewport_size = self.library_panel._list_view.viewport().size()
                proxy = QLabel(self.library_panel)
                proxy.setPixmap(pixmap)
                proxy.setGeometry(QRect(top_left, viewport_size))
                proxy.raise_()
                proxy.show()
                self._library_list_proxy = proxy
                self.library_panel._list_view.viewport().setUpdatesEnabled(False)
            except Exception:
                logger.exception(
                    "[LIST-PROXY] grab/proxy setup failed, falling back to live slide"
                )
                self._teardown_library_list_proxy()

        # Set animation guard to prevent layout updates during slide
        self.library_panel._is_animating = True
        self.library_panel_animation.finished.connect(self._on_library_shown)

        self.library_panel_animation.setStartValue(QPoint(-panel_w, sidebar_y))
        self.library_panel_animation.setEndValue(QPoint(0, sidebar_y))
        logger.debug(f"[STUTTER-TRACE] t={time.perf_counter():.6f} library_panel_animation.start() "
                     f"duration={self.library_panel_animation.duration()}ms")
        self.library_panel_animation.start()

    def _on_library_shown(self):
        logger.debug(f"[STUTTER-TRACE] t={time.perf_counter():.6f} _on_library_shown: "
                     f"library_panel_animation FINISHED")
        if _STUTTER_PROFILE_ENABLED:
            self._stop_stutter_profile()
        try:
            self.library_panel_animation.finished.disconnect(self._on_library_shown)
        except RuntimeError:
            pass
        self.library_panel._is_animating = False
        self.library_panel._list_view.setUpdatesEnabled(True)
        # The slide-paint-suppression proxy (if one was created) disabled updates on the
        # VIEWPORT specifically, not the QListView itself — the line above alone does not
        # restore that. Idempotent/harmless if no proxy was ever created this open.
        self.library_panel._list_view.viewport().setUpdatesEnabled(True)
        logger.debug(f"[STUTTER-TRACE] t={time.perf_counter():.6f} _on_library_shown: "
                     f"calling refresh()")
        self.library_panel.refresh()
        logger.debug(f"[STUTTER-TRACE] t={time.perf_counter():.6f} _on_library_shown: "
                     f"refresh() returned")

        def _settle_and_teardown_proxy():
            self.library_panel._list_view.viewport().update()
            # Tear down the proxy only after requesting the live repaint above, so the
            # handoff from frozen pixmap to live paint has no visible gap. Idempotent —
            # safe even if _close_library_flow already tore it down first.
            self._teardown_library_list_proxy()

        # Small delay lets the event loop settle before first paint
        QTimer.singleShot(16, _settle_and_teardown_proxy)

    def _stop_stutter_profile(self):
        """TEMPORARY (library-panel stutter investigation, 2026-07-17): stop the profiler
        started in _start_library_entry and dump the top time-consumers to the log. Brackets
        exactly the slide-in animation window (_start_library_entry through
        library_panel_animation.finished), where the user reports the stutter/pause actually
        happens — not after the panel is open."""
        prof = getattr(self, '_stutter_profiler', None)
        if prof is None:
            return
        prof.disable()
        self._stutter_profiler = None
        stream = io.StringIO()
        stats = pstats.Stats(prof, stream=stream).sort_stats('cumulative')
        stats.print_stats(40)
        logger.debug(f"[STUTTER-PROFILE] library-open window profile:\n{stream.getvalue()}")

    def _stop_bookdetail_profile(self):
        """TEMPORARY — see _BOOKDETAIL_PROFILE_ENABLED's comment above. Brackets
        _start_book_detail_entry through the slide-finished callback (same window
        _apply_transport_bar_blur_full runs in), same shape as _stop_stutter_profile."""
        prof = getattr(self, '_bookdetail_profiler', None)
        if prof is None:
            return
        prof.disable()
        self._bookdetail_profiler = None
        stream = io.StringIO()
        stats = pstats.Stats(prof, stream=stream).sort_stats('cumulative')
        stats.print_stats(40)
        logger.warning(f"[BOOKDETAIL-PROFILE] open window profile:\n{stream.getvalue()}")

    def _reveal_list_rows(self):
        view = self.library_panel._list_view
        # Find visible row range
        viewport = view.viewport()
        first = view.indexAt(viewport.rect().topLeft())
        last  = view.indexAt(viewport.rect().bottomRight())
        if not first.isValid():
            view.setUpdatesEnabled(True)
            viewport.update()
            return
        first_row = first.row()
        last_row  = last.row() if last.isValid() else first_row + 20
        
        self._reveal_rows = list(range(first_row, last_row + 1))
        if hasattr(self, '_reveal_timer') and self._reveal_timer is not None:
            self._reveal_timer.stop()
            self._reveal_timer.timeout.disconnect()
        self._reveal_timer = QTimer(self)
        self._reveal_timer.setInterval(16)  # ~60fps, one row per frame
        self._reveal_timer.timeout.connect(lambda: self._reveal_next_row(view))
        view.setUpdatesEnabled(True)
        view.viewport().update()  # blank canvas ready
        self._reveal_timer.start()

    def _reveal_next_row(self, view):
        if not self._reveal_rows:
            self._reveal_timer.stop()
            return
        row = self._reveal_rows.pop(0)
        idx = self.library_panel._book_model.index(row, 0)
        view.update(view.visualRect(idx))

    def _open_settings_flow(self):
        # One overlay at a time — see is_overlay_open_or_committed / _open_library_flow.
        if self.is_overlay_open_or_committed():
            return
        # NOT snap_theme_forward (Settings-tuned, explicitly wrong for a main-window-in-
        # flight fade — see _toggle_sidebar's comment). complete_main_fade is what actually
        # re-polishes the slider colors; matches every other _open_*_flow (2026-07-10 fix).
        self._complete_main_fade()
        """Hides sidebar first, then shows settings panel."""
        logger.debug(
            f"t={time.perf_counter():.6f} [_open_settings_flow ENTRY] "
            f"sidebar_expanded={self.sidebar_expanded} "
            f"sidebar_animation.state()={self.sidebar_animation.state()} "
            f"_sidebar_panel_signal_connected={self._sidebar_panel_signal_connected}"
        )
        if self.sidebar_expanded:
            self._pending_panel_open = "settings"
            if not self._sidebar_panel_signal_connected:
                self.sidebar_animation.finished.connect(self._on_sidebar_closed_for_panel)
                self._sidebar_panel_signal_connected = True
            logger.debug(f"t={time.perf_counter():.6f} [_open_settings_flow] queued: calling _toggle_sidebar to close first")
            self._toggle_sidebar()
        else:
            logger.debug(f"t={time.perf_counter():.6f} [_open_settings_flow] sidebar already collapsed: entering directly")
            self._start_settings_entry()

    def _start_settings_entry(self):
        """Starts the settings panel slide-in animation. This is called directly or via _on_sidebar_closed_for_panel."""
        self._flush_pending_restyle()  # before show() — see _flush_pending_restyle
        logger.debug(
            f"t={time.perf_counter():.6f} [_start_settings_entry ENTRY] "
            f"sidebar_expanded={self.sidebar_expanded} "
            f"sidebar.pos()={self.sidebar.pos()} "
            f"sidebar.isVisible()={self.sidebar.isVisible()} "
            f"sidebar_animation.state()={self.sidebar_animation.state()}"
        )
        self.main_window._sync_persist_filter_on_open()
        # excluded_books_popup is now parented to library_tab (not
        # MainWindow), so its position is relative to its own parent and
        # stays correct regardless of where the settings panel currently is
        # mid-slide — no need to wait for the slide-in animation to finish
        # before repositioning (that was only needed under the old
        # MainWindow-relative-coordinates architecture).
        self.main_window._reload_excluded_books()
        panel_w = int(self.main_window.width() * 0.9)
        sidebar_y = 56
        self.settings_panel.setFixedWidth(panel_w)
        self.settings_panel.move(-panel_w, sidebar_y)
        logger.debug(
            f"t={time.perf_counter():.6f} [_start_settings_entry] "
            f"BEFORE settings_panel.show()/raise_ "
            f"sidebar.pos()={self.sidebar.pos()} sidebar.isVisible()={self.sidebar.isVisible()}"
        )
        self.settings_panel.show()
        self.settings_panel.raise_()
        self._claim_panel_focus(self.settings_panel, panel_key="settings")
        logger.debug(
            f"t={time.perf_counter():.6f} [_start_settings_entry] "
            f"AFTER settings_panel.show()/raise_ "
            f"sidebar.pos()={self.sidebar.pos()} sidebar.isVisible()={self.sidebar.isVisible()}"
        )

        self.settings_panel_animation.setStartValue(QPoint(-panel_w, sidebar_y))
        self.settings_panel_animation.setEndValue(QPoint(0, sidebar_y))

        def _log_settings_slide_frame(value):
            logger.debug(
                f"t={time.perf_counter():.6f} [settings_panel_animation valueChanged] "
                f"panel_pos={value} "
                f"sidebar.pos()={self.sidebar.pos()} sidebar.isVisible()={self.sidebar.isVisible()} "
                f"sidebar_expanded={self.sidebar_expanded}"
            )

        def _on_settings_slide_finished():
            logger.debug(f"t={time.perf_counter():.6f} [settings_panel_animation finished]")
            try:
                self.settings_panel_animation.valueChanged.disconnect(_log_settings_slide_frame)
                self.settings_panel_animation.finished.disconnect(_on_settings_slide_finished)
            except (TypeError, RuntimeError):
                pass
            # Themes-tab frost suppression (2026-08-16) — see
            # _sync_transport_bar_blur_for_settings_tab's own docstring for why
            # this can't be an unconditional _apply_transport_bar_blur call.
            self._sync_transport_bar_blur_for_settings_tab()
            # visual_area blur starts HERE (not at panel-open) so it matches the
            # transport bar's timing — see _start_visual_area_blur.
            self._start_visual_area_blur(self.settings_panel)

        self.settings_panel_animation.valueChanged.connect(_log_settings_slide_frame)
        self.settings_panel_animation.finished.connect(_on_settings_slide_finished)

        self.settings_panel_animation.start()
        logger.debug(
            f"t={time.perf_counter():.6f} [_start_settings_entry] "
            f"settings_panel_animation.start() called "
            f"sidebar.pos()={self.sidebar.pos()} sidebar.isVisible()={self.sidebar.isVisible()}"
        )

        if not self.config.get_blur_enabled():

            self.blur_effect.setBlurRadius(0)

            self._clear_visual_area_clip()

    def switch_to_speed_panel(self) -> bool:
        """Dismiss whatever full panel is open and open Speed once it has closed.

        For the Speed button only. That button sits in the always-on transport
        chrome and protrudes ~20px past the 90%-width panels into the sliver, so it
        stays clickable while Stats/Tags/Settings is open — by design, it has looked
        that way for months. But the click landed on _open_speed_flow's
        one-overlay gate and was DROPPED: the button styled itself pressed and
        nothing happened. This restores the pre-df98cef behaviour, where clicking it
        closed the open panel and opened Speed.

        This is NOT a hole in the one-overlay gate. The gate's policy — drop the
        second request, never switch or queue — is about two OPENS colliding inside
        an animation window, which is not legitimate intent. A deliberate click on a
        visible chrome button is legitimate intent, and it is served the way the
        gate's own text prescribes: QUEUE the open, then close, then open when the
        close has finished. Nothing is opened concurrently with a close, so this
        cannot reproduce the close-slide-fights-open-slide overlap bug that
        _hide_popups()-then-open caused.

        Dispatches via _start_speed_entry (not _open_speed_flow) once the close
        lands — the same reason the sidebar handoff does: it is a continuation of an
        already-granted request, so re-consulting the gate would block it against
        its own committed state.

        Returns True if a switch was started, False if there was nothing to switch
        away from (caller should then open normally).
        """
        key = self.active_full_panel()
        if key is None or key not in dict(self._CLOSE_ANIMS):
            return False
        if key == "speed":
            return False  # self-toggle is the caller's job, not a switch
        anim = getattr(self, dict(self._CLOSE_ANIMS)[key], None)
        if anim is None:
            return False

        def _on_closed():
            try:
                anim.finished.disconnect(_on_closed)
            except (TypeError, RuntimeError):
                pass
            self._pending_panel_open = None
            # Re-check: the user may have dismissed or changed things during the
            # ~300ms close. Only open if nothing else claimed the slot meanwhile.
            if self.active_full_panel() is None and not self.sidebar_expanded:
                self._start_speed_entry()

        self._pending_panel_open = "speed"
        closer = {
            "library": self._close_library_flow,
            "settings": self._close_settings_flow,
            "speed": self._close_speed_flow,
            "sleep": self._close_sleep_flow,
            "stats": self._close_stats_flow,
            "tags": self._close_tags_flow,
        }[key]
        closer()
        # CONNECT AFTER closer(), never before. Qt fires `finished` slots in
        # connection order, and each _close_*_flow connects its own _on_*_hidden
        # (which calls .hide()) inside closer(). Connecting first put _on_closed
        # ahead of that hide, so the re-check below still saw the panel as visible,
        # active_full_panel() still named it, and the open was skipped every time —
        # the panel dismissed and Speed never appeared.
        anim.finished.connect(_on_closed)
        # If the close did not actually start, nothing will ever emit `finished` —
        # which would strand _pending_panel_open and wedge is_overlay_open_or_committed
        # permanently, blocking EVERY panel for the rest of the session. Unwind now
        # rather than leave that possible. (active_full_panel already excludes a
        # mid-close panel, so reaching here should mean the close really started;
        # this is the belt to that braces.)
        if anim.state() != QAbstractAnimation.State.Running:
            try:
                anim.finished.disconnect(_on_closed)
            except (TypeError, RuntimeError):
                pass
            self._pending_panel_open = None
            return False
        return True

    def _open_speed_flow(self):
        # One overlay at a time — see is_overlay_open_or_committed / _open_library_flow.
        if self.is_overlay_open_or_committed():
            return
        self._complete_main_fade()
        if self.sidebar_expanded:
            self._pending_panel_open = "speed"
            if not self._sidebar_panel_signal_connected:
                self.sidebar_animation.finished.connect(self._on_sidebar_closed_for_panel)
                self._sidebar_panel_signal_connected = True
            self._toggle_sidebar()
        else:
            self._start_speed_entry()

    def _start_speed_entry(self):
        """Starts the speed panel slide-in animation. This is called directly or via _on_sidebar_closed_for_panel."""
        self._flush_pending_restyle()  # before show() — see _flush_pending_restyle
        self.main_window.speed_panel.sync_smart_rewind_visuals()
        self.main_window.speed_panel._rebuild_def_speed_row()
        panel_w = int(self.main_window.width() * 0.9)
        sidebar_y = 56
        self.speed_panel.setFixedWidth(panel_w)
        self.speed_panel.move(-panel_w, sidebar_y)
        self.speed_panel.show()
        self.speed_panel.raise_()
        self._claim_panel_focus(self.speed_panel, panel_key="speed")

        self.speed_panel_animation.setStartValue(QPoint(-panel_w, sidebar_y))
        self.speed_panel_animation.setEndValue(QPoint(0, sidebar_y))

        def _on_speed_slide_finished():
            try:
                self.speed_panel_animation.finished.disconnect(_on_speed_slide_finished)
            except (TypeError, RuntimeError):
                pass
            self._apply_transport_bar_blur(self.speed_panel)
            # visual_area blur starts HERE (not at panel-open) so it matches the
            # transport bar's timing — see _start_visual_area_blur.
            self._start_visual_area_blur(self.speed_panel)

        self.speed_panel_animation.finished.connect(_on_speed_slide_finished)
        self.speed_panel_animation.start()

    def _on_sidebar_closed_for_panel(self):
        """Handler for sidebar animation finishing when a panel needs to open.

        Re-arm guard (fixes the sidebar-bleed-through bug — see NOTES.md 2026-07-01):
        the queued-open pattern in the six `_open_*_flow` methods calls `_toggle_sidebar()`
        to close the sidebar, but that call SILENTLY NO-OPS if a sidebar animation from a
        prior toggle is still running (its `state() == Running` guard). If that happens,
        the close never starts, yet this handler is still wired to `finished` — so the
        already-running (OPENING) animation's `finished` would otherwise dispatch the panel
        with the sidebar still fully expanded at x=0, visible through the panel's
        semi-transparent background.

        Fix: only dispatch once the sidebar is ACTUALLY collapsed. If `finished` fires while
        `sidebar_expanded` is still True (the dropped close never happened / this `finished`
        belonged to an opening animation), re-issue the close and keep waiting for the next
        `finished` — do not dispatch, do not disconnect.

        Termination: each re-arm issues exactly one `_toggle_sidebar()` close and returns;
        it is driven by the `finished` signal, not recursion. `sidebar_expanded` can only flip
        back to True via an OPENING `_toggle_sidebar()`, whose sole reachable trigger during
        the wait is a physical user right-click on the drag area — nothing re-opens
        automatically, so this cannot self-perpetuate. A stray extra user toggle mid-wait just
        costs one more re-arm cycle and converges once toggling stops and a close lands with
        `sidebar_expanded == False`. Even if a re-issued toggle were itself a no-op, the
        handler simply re-arms again on the next `finished`; the invariant "never dispatch
        while `sidebar_expanded`" holds regardless.
        """
        logger.debug(
            f"t={time.perf_counter():.6f} [_on_sidebar_closed_for_panel ENTRY] "
            f"sidebar_expanded={self.sidebar_expanded} "
            f"pending_panel_open={self._pending_panel_open!r}"
        )

        if self.sidebar_expanded:
            # The close we queued was dropped (or this `finished` came from an opening
            # animation). Stay armed, re-issue the close, and wait for the next `finished`.
            logger.debug(
                f"t={time.perf_counter():.6f} [_on_sidebar_closed_for_panel RE-ARM] "
                f"sidebar still expanded — re-issuing close, not dispatching"
            )
            self._toggle_sidebar()
            return

        if self._sidebar_panel_signal_connected:
            self.sidebar_animation.finished.disconnect(self._on_sidebar_closed_for_panel)
            self._sidebar_panel_signal_connected = False

        if self._pending_panel_open == "library": self._start_library_entry()
        elif self._pending_panel_open == "settings": self._start_settings_entry()
        elif self._pending_panel_open == "speed": self._start_speed_entry()
        elif self._pending_panel_open == "sleep": self._start_sleep_entry()
        elif self._pending_panel_open == "sprint": self._start_sprint_entry()
        elif self._pending_panel_open == "stats": self._start_stats_entry()
        elif self._pending_panel_open == "tags": self._start_tags_entry()
        logger.debug(
            f"t={time.perf_counter():.6f} [_on_sidebar_closed_for_panel EXIT] "
            f"dispatched={self._pending_panel_open!r} sidebar_expanded={self.sidebar_expanded}"
        )
        self._pending_panel_open = None

    def _close_library_flow(self):
        # The second condition covers the brief window (first-open case only, see
        # _start_library_entry) between that method deferring _finish_library_entry_
        # animation and that deferred call actually starting the real animation —
        # library_panel_animation.state() reads Stopped for that whole window since
        # nothing has called .start() yet. Deliberately NOT _is_animating: that flag
        # stays True for library_panel's entire open transition, including scenarios
        # (a stuck `finished` connection) that _close_library_flow's own teardown must
        # remain able to recover from — reusing it here would also block that recovery
        # path for the rest of the session, not just this narrow pre-start gap.
        if (self.library_panel_animation.state() == QAbstractAnimation.State.Running
                or self._library_entry_animation_pending):
            logger.debug("[BOOKSWITCH-TRACE] _close_library_flow: already running, no-op return")
            return
        logger.debug(f"t={time.perf_counter():.6f} [BOOKSWITCH-TRACE] _close_library_flow: entry")
        panel_w = self.library_panel.width()
        sidebar_y = 32

        # Set animation guard
        self.library_panel._is_animating = True
        self.library_panel._list_view.setUpdatesEnabled(True)
        # Owns the OTHER end of the slide-paint-suppression proxy's lifecycle (the open path
        # owns the normal case). Idempotent — a no-op if no proxy is currently up, which is
        # the ordinary case (open already finished cleanly and tore its own proxy down). If a
        # proxy WAS still up — e.g. a close landing between the open animation's finish and the
        # 16ms settle callback, or a stuck `finished` connection that never fired
        # _on_library_shown at all — this is what prevents it from sliding out frozen over the
        # live list, and prevents a second proxy being created on top of an orphaned first one
        # at the next open. See the design plan for the full reasoning.
        self._teardown_library_list_proxy()

        self.library_panel_animation.setStartValue(QPoint(0, sidebar_y))
        self.library_panel_animation.setEndValue(QPoint(-panel_w, sidebar_y))
        self.library_panel_animation.finished.connect(self._on_library_hidden)
        self.library_panel_animation.start()

        if self.config.get_blur_enabled():
            self.blur_animation.setStartValue(self.blur_effect.blurRadius())
            self.blur_animation.setDuration(_BLUR_OUT_MS)
            self.blur_animation.setEndValue(0)
            self.blur_animation.start()
            self._clear_visual_area_clip()

    def _teardown_library_list_proxy(self):
        """Idempotent teardown for the List-mode slide-paint-suppression proxy (see
        _start_library_entry). Safe to call whether or not a proxy currently exists — both
        _on_library_shown's settle callback and _close_library_flow call this unconditionally,
        so the proxy can never strand regardless of which transition actually runs."""
        proxy = self._library_list_proxy
        if proxy is None:
            return
        self._library_list_proxy = None
        proxy.hide()
        proxy.deleteLater()
        self.library_panel._list_view.viewport().setUpdatesEnabled(True)

    def _on_library_hidden(self):
        logger.debug(f"t={time.perf_counter():.6f} [BOOKSWITCH-TRACE] _on_library_hidden: entry")
        try:
            self.library_panel_animation.finished.disconnect(self._on_library_hidden)
        except RuntimeError:
            pass
        self.library_panel._is_animating = False
        self.library_panel._list_view.setUpdatesEnabled(True)
        self.library_panel.hide()
        # Symmetric with showEvent's _list_view.setFocus(): hiding a widget does NOT clear
        # Qt focus from it, so without this every subsequent keypress silently routes to the
        # now-invisible list view instead of MainWindow — the whole shortcut dispatcher goes
        # dead. MUST run AFTER hide() (confirmed live, traced): hide() on a still-focused
        # descendant makes Qt fall back and re-grant focus to that same (now hidden) widget —
        # clearing focus BEFORE hide() gets silently undone by hide() itself. Also must target
        # the actual focused widget (e.g. _list_view or search_field), not library_panel
        # itself — clearFocus() only acts on `self`, and the panel container never holds
        # focus directly, only its descendants do.
        focused = QApplication.focusWidget()
        if focused is not None and self.library_panel.isAncestorOf(focused):
            focused.clearFocus()
        mw = self.main_window
        # LOADING → RESTORING: the library slide-out is done, so the deadzone ends.
        mw._switch.library_revealed()
        player = getattr(mw, 'player', None)
        logger.debug(f"t={time.perf_counter():.6f} [BOOKSWITCH-TRACE] _on_library_hidden: "
                     f"about to call ungate_play, current_file={getattr(mw, 'current_file', None)!r} "
                     f"file_ready_deferred={mw._switch.file_ready_deferred} chaps_deferred={mw._switch.chaps_deferred}")
        if player:
            player.ungate_play()
        self._notify_panel_closed()
        if mw._switch.file_ready_deferred or mw._switch.chaps_deferred:
            QTimer.singleShot(50, mw._drain_deferred_file_ready)
        else:
            mw._apply_pending_cover_theme()

    def _clear_focus_marker_for_close(self) -> None:
        """Hide the traveling focus marker immediately, before a panel's slide-out animation
        starts — not after. Without this, the marker keeps patrolling whatever control it was
        tracking for the ENTIRE close animation, and since that control is still a live,
        positioned widget until the panel's own `.hide()` runs at animation-finished, the
        marker visibly travels off-screen WITH the sliding panel — reads as "the marker spilled
        into the main window" (reported live 2026-09-07, Sleep panel; Settings never showed
        this because `_close_settings_flow` already clears the marker at its own entry, for
        exactly this reason — see that method's comment, which this helper factors out so
        Speed/Sleep/Sprint's own close flows get the identical fix instead of three copies of
        the same fix arriving independently, or at different times, the way it almost did.
        Idempotent (marker.clear() is a safe no-op if already clear); safe no-op before the
        marker exists at all."""
        marker = getattr(self.main_window, 'focus_marker', None)
        if marker is not None:
            marker.clear()

    def _close_speed_flow(self):
        """Slides the speed panel back out."""
        if self.speed_panel_animation.state() == QAbstractAnimation.State.Running:
            return
        self._clear_focus_marker_for_close()
        panel_w = self.speed_panel.width()
        sidebar_y = 56
        self.speed_panel_animation.setStartValue(QPoint(0, sidebar_y))
        self.speed_panel_animation.setEndValue(QPoint(-panel_w, sidebar_y))
        self.speed_panel_animation.finished.connect(self._on_speed_hidden)
        self.main_window._validate_smart_rewind_settings()
        self.speed_panel_animation.start()
        self._clear_transport_bar_blur()

        if self.config.get_blur_enabled():
            self.blur_animation.setStartValue(self.blur_effect.blurRadius())
            self.blur_animation.setDuration(_BLUR_OUT_MS)
            self.blur_animation.setEndValue(0)
            self.blur_animation.start()
            self._clear_visual_area_clip()

    def _on_speed_hidden(self):
        try:
            self.speed_panel_animation.finished.disconnect(self._on_speed_hidden)
        except RuntimeError:
            pass
        self.speed_panel.hide()
        self._release_panel_focus(self.speed_panel)
        self._notify_panel_closed()

    def _open_stats_flow(self):
        # One overlay at a time — see is_overlay_open_or_committed / _open_library_flow.
        if self.is_overlay_open_or_committed():
            return
        self._complete_main_fade()
        if self.sidebar_expanded:
            self._pending_panel_open = "stats"
            if not self._sidebar_panel_signal_connected:
                self.sidebar_animation.finished.connect(self._on_sidebar_closed_for_panel)
                self._sidebar_panel_signal_connected = True
            self._toggle_sidebar()
        else:
            self._start_stats_entry()

    def _start_stats_entry(self):
        self._flush_pending_restyle()  # before show() — see _flush_pending_restyle
        panel_w = int(self.main_window.width() * 0.9)
        sidebar_y = 56
        self.stats_panel.setFixedWidth(panel_w)
        self.stats_panel.move(-panel_w, sidebar_y)
        self.stats_panel.show()
        self.stats_panel.refresh_current_tab()
        self.stats_panel.raise_()
        # Timeline grid content is fully determined by refresh_current_tab() above, before the
        # slide even starts — nothing legitimate changes it while the panel is merely sliding
        # into view. See StatsPanel.suspend_timeline_paint's own docstring for the measured
        # cost this avoids (StreakGrid.paintEvent: 20-27ms/call, 6-12 calls per slide).
        self.stats_panel.suspend_timeline_paint()
        # panel_key="stats" (2026-09-08, first keyboard-nav pass): lands initial focus on
        # Stats' own tab bar (via panel_tab_widgets("stats")'s first entry) instead of the
        # panel root — same shape as Settings. Without this, _claim_panel_focus's default
        # fallback grants the panel ROOT StrongFocus, which is what StatsPanel.keyPressEvent's
        # own docstring documents as today's (pre-this-pass) behavior.
        self._claim_panel_focus(self.stats_panel, panel_key="stats")

        self.stats_panel_animation.setStartValue(QPoint(-panel_w, sidebar_y))
        self.stats_panel_animation.setEndValue(QPoint(0, sidebar_y))

        def _on_stats_slide_finished():
            try:
                self.stats_panel_animation.finished.disconnect(_on_stats_slide_finished)
            except (TypeError, RuntimeError):
                pass
            self.stats_panel.resume_timeline_paint()
            self._apply_transport_bar_blur(self.stats_panel)
            # visual_area blur starts HERE (not at panel-open) so it matches the
            # transport bar's timing — see _start_visual_area_blur.
            self._start_visual_area_blur(self.stats_panel)

        self.stats_panel_animation.finished.connect(_on_stats_slide_finished)
        self.stats_panel_animation.start()

        if not self.config.get_blur_enabled():

            self.blur_effect.setBlurRadius(0)

            self._clear_visual_area_clip()

    def _open_sleep_flow(self):
        # One overlay at a time — see is_overlay_open_or_committed / _open_library_flow.
        if self.is_overlay_open_or_committed():
            return
        self._complete_main_fade()
        """Hides sidebar first, then shows sleep panel."""
        if self.sidebar_expanded:
            self._pending_panel_open = "sleep"
            if not self._sidebar_panel_signal_connected:
                self.sidebar_animation.finished.connect(self._on_sidebar_closed_for_panel)
                self._sidebar_panel_signal_connected = True
            self._toggle_sidebar()
        else:
            self._start_sleep_entry()

    def _start_sleep_entry(self):
        """Starts the sleep panel slide-in animation."""
        self._flush_pending_restyle()  # before show() — see _flush_pending_restyle
        # Sync the disable-button's visibility here, at panel-open time, not
        # during arming — see SleepTimerPanel._do_arm_sleep_timer's comment for
        # why (a same-call-stack .show() during arm flashes visibly for one
        # frame before the panel's own close-on-arm animation starts). Same
        # deferred-reconciliation shape as _sync_persist_filter_on_open.
        self.sleep_panel.sync_disable_button_visibility()
        panel_w = int(self.main_window.width() * 0.9)
        sidebar_y = 56
        self.sleep_panel.setFixedWidth(panel_w)
        self.sleep_panel.move(-panel_w, sidebar_y)
        self.sleep_panel.show()
        self.sleep_panel.raise_()
        self._claim_panel_focus(self.sleep_panel, panel_key="sleep")

        self.sleep_panel_animation.setStartValue(QPoint(-panel_w, sidebar_y))
        self.sleep_panel_animation.setEndValue(QPoint(0, sidebar_y))

        def _on_sleep_slide_finished():
            try:
                self.sleep_panel_animation.finished.disconnect(_on_sleep_slide_finished)
            except (TypeError, RuntimeError):
                pass
            self._apply_transport_bar_blur(self.sleep_panel)
            # visual_area blur starts HERE (not at panel-open) so it matches the
            # transport bar's timing — see _start_visual_area_blur.
            self._start_visual_area_blur(self.sleep_panel)

        self.sleep_panel_animation.finished.connect(_on_sleep_slide_finished)
        self.sleep_panel_animation.start()

    def _close_sleep_flow(self):
        """Slides the sleep panel back out."""
        if self.sleep_panel_animation.state() == QAbstractAnimation.State.Running:
            return
        self._clear_focus_marker_for_close()
        panel_w = self.sleep_panel.width()
        sidebar_y = 56
        self.sleep_panel_animation.setStartValue(QPoint(0, sidebar_y))
        self.sleep_panel_animation.setEndValue(QPoint(-panel_w, sidebar_y))
        self.sleep_panel_animation.finished.connect(self._on_sleep_hidden)
        self.sleep_panel_animation.start()
        self._clear_transport_bar_blur()

        if self.config.get_blur_enabled():
            self.blur_animation.setStartValue(self.blur_effect.blurRadius())
            self.blur_animation.setDuration(_BLUR_OUT_MS)
            self.blur_animation.setEndValue(0)
            self.blur_animation.start()
            self._clear_visual_area_clip()

    def _on_sleep_hidden(self):
        try:
            self.sleep_panel_animation.finished.disconnect(self._on_sleep_hidden)
        except RuntimeError:
            pass
        self.sleep_panel.hide()
        self._release_panel_focus(self.sleep_panel)
        self._notify_panel_closed()

    def _open_sprint_flow(self):
        # One overlay at a time — see is_overlay_open_or_committed / _open_library_flow.
        if self.is_overlay_open_or_committed():
            return
        self._complete_main_fade()
        """Hides sidebar first, then shows sprint panel."""
        if self.sidebar_expanded:
            self._pending_panel_open = "sprint"
            if not self._sidebar_panel_signal_connected:
                self.sidebar_animation.finished.connect(self._on_sidebar_closed_for_panel)
                self._sidebar_panel_signal_connected = True
            self._toggle_sidebar()
        else:
            self._start_sprint_entry()

    def _start_sprint_entry(self):
        """Starts the sprint panel slide-in animation. Mirrors _start_sleep_entry exactly."""
        self._flush_pending_restyle()  # before show() — see _flush_pending_restyle
        # Refresh has-data BEFORE sync_disable_button_visibility, so that call's own
        # visibility recompute (Reset = not sprint_active AND has_sprint_data) uses fresh
        # data rather than whatever was last known — see SprintPanel.set_has_sprint_data's
        # docstring for why this specific read lives here (SprintPanel has no db by
        # design). Reaches self.main_window.db the same way _start_speed_entry already
        # reaches self.main_window.config for a panel-open-time read.
        self.sprint_panel.set_has_sprint_data(self.main_window.db.has_sprint_data())
        self.sprint_panel.sync_disable_button_visibility()
        panel_w = int(self.main_window.width() * 0.9)
        sidebar_y = 56
        self.sprint_panel.setFixedWidth(panel_w)
        self.sprint_panel.move(-panel_w, sidebar_y)
        self.sprint_panel.show()
        self.sprint_panel.raise_()
        self._claim_panel_focus(self.sprint_panel, panel_key="sprint")

        self.sprint_panel_animation.setStartValue(QPoint(-panel_w, sidebar_y))
        self.sprint_panel_animation.setEndValue(QPoint(0, sidebar_y))

        def _on_sprint_slide_finished():
            try:
                self.sprint_panel_animation.finished.disconnect(_on_sprint_slide_finished)
            except (TypeError, RuntimeError):
                pass
            self._apply_transport_bar_blur(self.sprint_panel)
            self._start_visual_area_blur(self.sprint_panel)

        self.sprint_panel_animation.finished.connect(_on_sprint_slide_finished)
        self.sprint_panel_animation.start()

    def _close_sprint_flow(self):
        """Slides the sprint panel back out. Mirrors _close_sleep_flow exactly."""
        if self.sprint_panel_animation.state() == QAbstractAnimation.State.Running:
            return
        self._clear_focus_marker_for_close()
        self.sprint_panel._cancel_reset_sprint_data()
        panel_w = self.sprint_panel.width()
        sidebar_y = 56
        self.sprint_panel_animation.setStartValue(QPoint(0, sidebar_y))
        self.sprint_panel_animation.setEndValue(QPoint(-panel_w, sidebar_y))
        self.sprint_panel_animation.finished.connect(self._on_sprint_hidden)
        self.sprint_panel_animation.start()
        self._clear_transport_bar_blur()

        if self.config.get_blur_enabled():
            self.blur_animation.setStartValue(self.blur_effect.blurRadius())
            self.blur_animation.setDuration(_BLUR_OUT_MS)
            self.blur_animation.setEndValue(0)
            self.blur_animation.start()
            self._clear_visual_area_clip()

    def _on_sprint_hidden(self):
        try:
            self.sprint_panel_animation.finished.disconnect(self._on_sprint_hidden)
        except RuntimeError:
            pass
        self.sprint_panel.hide()
        self._release_panel_focus(self.sprint_panel)
        self._notify_panel_closed()

    def _close_stats_flow(self):
        if self.stats_panel_animation.state() == QAbstractAnimation.State.Running:
            return
        # Stats never had this call — same regression Sleep/Speed/Sprint already had fixed
        # (2026-09-07, see _clear_focus_marker_for_close's own docstring): without it, the
        # marker keeps patrolling the last-focused Stats control for the whole slide-out
        # animation and visibly spills onto the main window with it. Reported live 2026-09-08
        # against Stats specifically, the first panel to add keyboard nav after that fix landed.
        self._clear_focus_marker_for_close()
        self.stats_panel._cancel_reset_stats()
        panel_w = self.stats_panel.width()
        sidebar_y = 56
        self.stats_panel_animation.setStartValue(QPoint(0, sidebar_y))
        self.stats_panel_animation.setEndValue(QPoint(-panel_w, sidebar_y))
        # Same cost, same fix as the open path (_start_stats_entry) — the Timeline grid's
        # content doesn't change while the panel is merely sliding out either. _on_stats_hidden
        # calls hide() at finish, which stops paint delivery on its own regardless, but resuming
        # explicitly there keeps the grid's updatesEnabled state consistent for the NEXT open
        # rather than relying on hide()'s side effect to leave it in a sane state.
        self.stats_panel.suspend_timeline_paint()
        self.stats_panel_animation.finished.connect(self._on_stats_hidden)
        self.stats_panel_animation.start()
        self._clear_transport_bar_blur()

        if self.config.get_blur_enabled():
            self.blur_animation.setStartValue(self.blur_effect.blurRadius())
            self.blur_animation.setDuration(_BLUR_OUT_MS)
            self.blur_animation.setEndValue(0)
            self.blur_animation.start()
            self._clear_visual_area_clip()
        else:
            self.blur_effect.setBlurRadius(0)
            self._clear_visual_area_clip()

    def _on_stats_hidden(self):
        try:
            self.stats_panel_animation.finished.disconnect(self._on_stats_hidden)
        except RuntimeError:
            pass
        self.stats_panel.hide()
        self.stats_panel.resume_timeline_paint()
        self._release_panel_focus(self.stats_panel)
        self._notify_panel_closed()

    def _open_tags_flow(self):
        # One overlay at a time — see is_overlay_open_or_committed / _open_library_flow.
        # NOTE: the tag-manager-from-book-detail transition (app.py
        # _on_open_tag_manager_from_detail) calls hide_all_panels() then
        # call_when_panels_settled(_open_tags_flow) — a predicate re-check (see that
        # method's docstring), not a fixed delay, so it can't race the close animations
        # regardless of their duration. Previously a QTimer.singleShot(320, ...) magic
        # number tuned to "just clears the 300ms position slide" — that raced live
        # (NOTES.md 2026-05-26 "hide_all_panels then open: timer vs signal"; fixed
        # 2026-08-13) whenever a hitch or the 500ms blur fade ate the ~20ms margin.
        if self.is_overlay_open_or_committed():
            return
        self._complete_main_fade()
        if self.sidebar_expanded:
            self._pending_panel_open = "tags"
            if not self._sidebar_panel_signal_connected:
                self.sidebar_animation.finished.connect(self._on_sidebar_closed_for_panel)
                self._sidebar_panel_signal_connected = True
            self._toggle_sidebar()
        else:
            self._start_tags_entry()

    def _start_tags_entry(self):
        self._flush_pending_restyle()  # before show() — see _flush_pending_restyle
        mw = self.main_window
        panel_w = self.tags_panel.width()
        sidebar_y = 56
        self.tags_panel.move(-panel_w, sidebar_y)
        self.tags_panel.show()
        self.tags_panel.refresh()
        self.tags_panel.raise_()
        # Claims focus on _tag_scroll directly (2026-09-08, tag-list keyboard nav),
        # not the panel root — refresh() always lands on the list view, and the
        # list's own arrow-key handling (TagManagerWidget.eventFilter) is gated on
        # `obj is self._tag_scroll`, so real focus has to land there for a key
        # press to ever reach it. _claim_panel_focus's own fallback (grant
        # StrongFocus + setFocus) applies unchanged; _tag_scroll already has
        # StrongFocus by Qt's QAbstractScrollArea default.
        self._claim_panel_focus(self.tags_panel.tag_scroll_widget())
        self.tags_panel_animation.setStartValue(QPoint(-panel_w, sidebar_y))
        self.tags_panel_animation.setEndValue(QPoint(0, sidebar_y))

        def _on_tags_slide_finished():
            try:
                self.tags_panel_animation.finished.disconnect(_on_tags_slide_finished)
            except (TypeError, RuntimeError):
                pass
            self._apply_transport_bar_blur(self.tags_panel)
            # visual_area blur starts HERE (not at panel-open) so it matches the
            # transport bar's timing — see _start_visual_area_blur.
            self._start_visual_area_blur(self.tags_panel)

        self.tags_panel_animation.finished.connect(_on_tags_slide_finished)
        self.tags_panel_animation.start()

    def _close_tags_flow(self):
        if self.tags_panel_animation.state() == QAbstractAnimation.State.Running:
            return
        panel_w = self.tags_panel.width()
        sidebar_y = 56
        self.tags_panel_animation.setStartValue(QPoint(0, sidebar_y))
        self.tags_panel_animation.setEndValue(QPoint(-panel_w, sidebar_y))
        self.tags_panel_animation.finished.connect(self._on_tags_hidden)
        self.tags_panel_animation.start()
        self._clear_transport_bar_blur()
        if self.main_window.config.get_blur_enabled():
            self.blur_animation.setStartValue(self.blur_animation.currentValue() or 8)
            self.blur_animation.setEndValue(0)
            self.blur_animation.start()
            self._clear_visual_area_clip()

    def _on_tags_hidden(self):
        try:
            self.tags_panel_animation.finished.disconnect(self._on_tags_hidden)
        except RuntimeError:
            pass
        self.tags_panel.hide()
        self._release_panel_focus(self.tags_panel)
        self._notify_panel_closed()

    def open_book_detail(self, book_data: dict, tab: str = 'stats', context: str = ''):
        # If the panel is already showing ANY book, a new open request is dropped entirely —
        # not just re-animated, not re-targeted to a different book. Without this, a book
        # already open in the background list could be swapped out from under the visible
        # panel (e.g. right-click a book to open detail, then arrow-key to a DIFFERENT book
        # and press Alt+Enter — that reused this same unconditional path and hijacked the
        # open panel onto the new book while still only ever showing one panel at a time).
        # The user must close the current panel first via an existing close path
        # (_close_book_detail_flow / the panel's own close button) before opening another.
        panel = self.main_window.book_detail_panel
        if panel.isVisible():
            return
        # Remember what this is opening ON TOP OF, for the blur suspend/resume pair.
        # Written AFTER the early-return above so a dropped duplicate open can never
        # clobber a live value. active_full_panel() already excludes mid-close panels
        # via _is_closing, which is exactly the state we must not "restore" blur to.
        self._book_detail_underlay = self.active_full_panel()
        # Library hover-bleed fix (2026-09-24, live-reported). Book Detail is a real, opaque,
        # natively-painted widget in Transparent mode (no grab/proxy in that mode — see
        # _wire_slide_paint_suppression's THIRD CORRECTION), so once it's shown and raised, Qt
        # correctly stops delivering mouse events to whatever's underneath. The bug is a TIMING
        # gap, not a hit-testing leak: opening a book highlighted a library row (mouse-hover or
        # the solid keyboard-selection fill, depending on view mode); the highlight then stayed
        # frozen/visible until the user's FIRST mouse movement after Book Detail was already up
        # — at which point Qt finally resolves the library viewport's real Leave (it was
        # occluded, never actually left, until that first post-open move forces Qt to
        # re-evaluate hit-testing) and `_on_view_left` fires, clearing it. Pryme's own diagnosis:
        # the highlight should never survive into the open Book Detail panel at all — clear it
        # proactively, before the panel ever appears, rather than waiting for Qt's occlusion
        # bookkeeping to catch up on its own schedule. `_on_view_left` is the library's own
        # existing full-teardown method (clears the model's _hovered_path AND the delegate's
        # list-mode/keyboard-fill state), so this reuses it rather than duplicating its effect.
        # Scoped to when Library is actually the underlay — calling it harmlessly no-ops
        # otherwise (nothing to clear), but the guard makes the intent explicit.
        if self._book_detail_underlay == 'library':
            self.library_panel._on_view_left()
        self._book_detail_return_focus_widget = QApplication.focusWidget()
        self._complete_main_fade()
        # Snapshot of the library's current search text, so tag chips (library context only)
        # can tell whether a given tag is already the active filter and render inert. A
        # snapshot (not a live callback) is sufficient: the library's search text cannot change
        # while the detail panel is open — reaching this panel requires leaving the library view
        # first, and there is no other UI path that edits the search field meanwhile.
        active_search_text = self.library_panel.search_field.text()
        panel.load_book(
            book_data, tab=tab, context=context, active_search_text=active_search_text)
        self._start_book_detail_entry()

    def _start_book_detail_entry(self):
        if _BOOKDETAIL_PROFILE_ENABLED:
            self._bookdetail_profiler = cProfile.Profile()
            self._bookdetail_profiler.enable()
        self._flush_pending_restyle()  # before show() — see _flush_pending_restyle
        # Immediately, at open-START: the underlay is about to be fully covered, so
        # its GRABBING must stop now rather than at slide-finish — but its last
        # frame stays on screen as a static backdrop. This and the blur START
        # below are two SEPARATE moments and must not be merged — see
        # _park_blur_for_book_detail.
        self._park_blur_for_book_detail()
        panel_w = self.main_window.width()
        book_detail_panel_y = 32 # Position under the titlebar
        self.book_detail_panel.setFixedWidth(panel_w)
        self.book_detail_panel.setFixedHeight(self.main_window.height() - book_detail_panel_y)
        self.book_detail_panel.move(panel_w, book_detail_panel_y)
        # setFixedWidth/setFixedHeight only update the PANEL's own geometry — Qt does not
        # synchronously re-layout child widgets in response (confirmed live, 2026-08-13: a
        # child QLabel still reported width()==640, its un-laid-out default, immediately
        # after this setFixedWidth call, even with no show()/processEvents() in between).
        # layout().activate() forces the pending layout pass through immediately, so
        # refresh_tag_display() below sees the real ~284px usable width instead of the
        # stale default — without it, the "+N more" fit calculation silently measured
        # against the wrong width and could under-truncate.
        self.book_detail_panel.layout().activate()
        self.book_detail_panel.refresh_tag_display()
        self.book_detail_panel.show()
        self.book_detail_panel.raise_()
        self._claim_panel_focus(self.book_detail_panel)
        # Frost/wash backdrop now fires HERE too (2026-09-23, moved from slide-finish-only),
        # so the static backdrop behind the sliding proxy (see
        # _wire_slide_paint_suppression's _on_start) is correct from the very first frame,
        # not just once settled. Unlike _start_visual_area_blur's cross-referenced
        # "TIMING IS LOAD-BEARING" warning (a live ANIMATED blur-in tween that visibly ran
        # ahead of a still-sliding panel when moved to open-start, 2026-07-27), this frost is
        # a ONE-SHOT STATIC grab — nothing about it continues to run/animate after this call
        # returns, so the specific failure mode that warning describes (blur racing ahead of
        # motion) does not apply here. _book_detail_frost_rect() depends only on mw.width()/
        # mw.height()/self._book_detail_underlay, all already valid at this point — not on
        # the panel's own (still off-screen) position. Live-verified 2026-09-23 that this does
        # not reproduce the same-shaped bug the visual_area case had.
        self._apply_transport_bar_blur_full(self.book_detail_panel)
        self._arm_book_detail_frost_refresh()

        def _on_book_detail_slide_finished():
            try:
                self.book_detail_panel_animation.finished.disconnect(
                    _on_book_detail_slide_finished)
            except (TypeError, RuntimeError):
                pass
            # NO visual_area teardown here, and none at open-start either — see
            # _park_blur_for_book_detail. The frost grab below hides only
            # _active_panel (Book Detail itself), so what it photographs is the
            # UNDERLAY — Stats/Library — which is opaque and covers the
            # visual_area region entirely. A live visual_area blur is therefore
            # not in the grab at all, and the "double blur" it was zeroed to
            # prevent cannot occur on this path. Confirmed live 2026-08-14:
            # dropping the radius here made the close transition read
            # crisp-then-blur; leaving it up is correct on both transitions.
            # Book Detail spans BOTH blur regions, so it frosts via the grab overlay
            # over its whole area rather than visual_area's paint-time effect:
            # ClippedBlurEffect lives on visual_area, which is inset 10px inside
            # content_container and does not contain the transport bar at all, so it
            # structurally CANNOT cover this panel's backdrop. Hence no
            # _start_visual_area_blur call here — that asymmetry vs. the other five
            # panels is deliberate, not an omission.
            #
            # KEPT DELIBERATELY, even though _start_book_detail_entry now ALSO calls this at
            # open-start (2026-09-23, for the sliding-proxy static-backdrop fix — see that call
            # site's own comment): re-grabbing here refreshes the frost against whatever the
            # underlay looks like NOW, at settle, vs. whatever it looked like at open-start —
            # not proven redundant, since the underlay could have repainted during the slide
            # (a live-updating stat, its own animation). Cutting this second call was
            # considered and NOT done without live verification that nothing depends on the
            # refresh; the two calls are cheap and harmless to run twice (frost_panel_backdrop
            # is idempotent — same rect in, same frost child updated).
            self._apply_transport_bar_blur_full(self.book_detail_panel)
            if _BOOKDETAIL_PROFILE_ENABLED:
                self._stop_bookdetail_profile()

        # Blur starts at slide-FINISHED, matching every other panel — see
        # _start_visual_area_blur's TIMING IS LOAD-BEARING note.
        #
        # This connects to `finished` to START an effect, which is what the other
        # five panels do; it is NOT the pattern the "do not resume a panel-animation
        # wait via finished" rule forbids (that targets resuming a PREDICATE WAIT,
        # because stop() emits no finished). Safe here because
        # book_detail_panel_animation is never stop()ed — _close_book_detail_flow
        # early-returns on Running rather than stopping it. IF A FUTURE CHANGE ADDS A
        # stop() (e.g. interrupt-and-reverse close), this frost silently never
        # appears.
        self.book_detail_panel_animation.finished.connect(_on_book_detail_slide_finished)
        self.book_detail_panel_animation.setStartValue(QPoint(panel_w, book_detail_panel_y))
        self.book_detail_panel_animation.setEndValue(QPoint(0, book_detail_panel_y))
        self.book_detail_panel_animation.start()

    def _close_book_detail_flow(self):
        if self.book_detail_panel_animation.state() == QAbstractAnimation.State.Running:
            return
        self._disarm_book_detail_frost_refresh()
        panel_w = self.main_window.width()
        book_detail_panel_y = 32 # Position under the titlebar
        self.book_detail_panel_animation.setStartValue(QPoint(0, book_detail_panel_y))
        self.book_detail_panel_animation.setEndValue(QPoint(panel_w, book_detail_panel_y))
        self.book_detail_panel_animation.finished.connect(self._on_book_detail_hidden)
        self.book_detail_panel_animation.start()
        # NO _clear_transport_bar_blur() here, deliberately — unlike every other
        # _close_*_flow. The underlay's frame is PARKED (see
        # _park_blur_for_book_detail): it is already the correct blurred backdrop
        # and Book Detail is about to slide off it. Clearing it here is what used
        # to snap the window crisp for the whole slide-out and then rebuild with a
        # 1500ms fade. Re-arming waits for _resume_blur_after_book_detail, which
        # runs after .hide() so no grab can photograph the still-sliding panel.
        # The frost is a child of the panel and would otherwise slide out still
        # showing a stale backdrop through the translucent wash.
        self._transport_bar_blur.clear_panel_backdrop_frost(self.book_detail_panel)

    def _on_book_detail_hidden(self):
        try:
            self.book_detail_panel_animation.finished.disconnect(self._on_book_detail_hidden)
        except (TypeError, RuntimeError):
            pass
        self.book_detail_panel.hide()
        # RETRACTED 2026-09-24: a forced `_resync_tab_bar_hover` call used to live here,
        # reasoning that Qt's QTabBar hover tracking would be left STALE (stuck on whatever tab
        # was hovered BEFORE Book Detail opened) once the bar became hit-testable again. That
        # theory does not match what Pryme actually reported: there is no hover on the tabs
        # before Book Detail opens; he deliberately hovers a tab WHILE it is covered, and only
        # THEN closes the panel — and that tab lights up for ~0.5s on close. That is the cursor's
        # CURRENT resting position being resolved, not a stale pre-open one — and forcing a
        # QHoverEvent(HoverMove) at that exact instant is precisely what manufactures the paint,
        # since Qt's real hover requires actual mouse MOVEMENT over the widget, not merely resting
        # over where it will appear once revealed. The fix was the bug. Removed outright rather
        # than reworked — the real cause of the highlight-appears-from-nothing symptom is still
        # unidentified (see TODO.md); do not re-add a resync call here without first confirming,
        # live, that native Qt event delivery alone (no manual resync) still leaves something
        # stale — it may not.
        self._release_panel_focus(self.book_detail_panel)
        # Hand focus back to whatever specifically held it when Book Detail opened —
        # 2026-09-09, closing the gap this comment used to flag as known/deferred (see
        # _book_detail_return_focus_widget's own docstring in __init__ for the full history).
        # Consuming read; a deleted C++ widget (its panel closed or rebuilt while Book Detail
        # was open) raises RuntimeError on ANY method call, not just a specific one, so the
        # guard is a broad try/except rather than an isinstance/None check alone.
        widget, self._book_detail_return_focus_widget = self._book_detail_return_focus_widget, None
        if widget is not None:
            try:
                if widget.isVisible():
                    widget.setFocus(Qt.FocusReason.OtherFocusReason)
            except RuntimeError:
                pass  # underlying C++ object was destroyed — nothing to restore focus to
        self._resume_blur_after_book_detail()
        self._notify_panel_closed()

    def _close_settings_flow(self):
        """Slides the settings panel back out.

        BLOCKS on the hover-out snapback visibly settling before the slide starts
        (2026-08-05, corrected snapback-timing spec v2 — see
        review/Design_260805_snapback_timing_v2.md — this SUPERSEDES a same-day
        earlier attempt, 2abeab5, reverted the same session). The earlier attempt
        called `_on_theme_unhovered()` then `snap_theme_forward()` synchronously,
        back-to-back, exactly as the pre-fix code below did — `snap_theme_forward()`
        immediately `.stop()`s whatever fade `_on_theme_unhovered()` just started
        and force-applies it INSTANTLY (`fade_ms=0`), so by the time
        `call_when_theme_settled` was reached, `_fade_in_flight` was already False
        and the wait branch was never entered at all. The visible result was not a
        blocked event loop (the wait mechanism itself is a non-blocking
        `QTimer`-based re-check, same shape as `PanelManager.
        call_when_panels_settled`, and never stalls painting) — it was that
        `_apply_stylesheets`'s own ~700-810ms synchronous cost
        (review/Investigation_260804_animation_latency.md) ran with NO animation
        on screen at all, which reads as a freeze, followed by the sudden correct
        colors the instant it finishes, which reads as a jump.

        The fix: do NOT call `snap_theme_forward()` up front. `_on_theme_unhovered()`
        alone already starts the correct, real, animated 200ms snapback fade
        (confirmed instant-interrupt of any preceding preview fade via
        `_snapback_in_progress` — see `_hover_may_interrupt` in `_on_theme_changed`).
        This method waits for THAT fade to genuinely settle via
        `call_when_theme_settled` before proceeding — during the wait, Qt's event
        loop keeps running normally, so the fade overlay stays visible and the
        200ms fade visibly plays once `_apply_stylesheets` completes underneath it.
        `snap_theme_forward()` is still reachable, but only as
        `call_when_theme_settled`'s own internal termination guarantee (a
        generous, 2000ms bound) for the abnormal case where a fade genuinely never
        settles — see that method's docstring. It must never be called
        unconditionally from this method again.

        RE-ENTRANCY GUARD (`_settings_close_pending`): a second Esc/gutter-click
        while the first call is still waiting on `call_when_theme_settled` must
        NOT re-issue `_on_theme_unhovered()` a second time. `active_full_panel()`
        still reports "settings" as open throughout the settle-wait (the slide
        animation genuinely hasn't started yet, so `_is_closing("settings")` is
        correctly False), so a spammed dismiss WILL re-enter this method without
        this guard. The guard is a plain no-op on re-entry, not a queue: the one
        in-flight close is already going to finish and hide the panel; a second
        request while it's pending adds nothing."""
        # Hide the traveling focus marker immediately — before the snapback-settle wait and
        # slide-out below, not after (see _on_settings_hidden, which used to own this and left
        # the marker visibly patrolling the tab border throughout the whole close animation).
        # Mirrors a tab switch's own _update_focus_marker() clear: the marker disappears the
        # instant the widget it was tracking is going away, not once the transition finishes.
        # Factored into _clear_focus_marker_for_close 2026-09-07 so Speed/Sleep/Sprint's own
        # close flows share this exact fix rather than reimplementing it — see that method's
        # docstring for the live report that found the gap on Sleep. Idempotent, so safe to
        # call again on the re-entrancy early-return path below.
        self._clear_focus_marker_for_close()
        if getattr(self, '_settings_close_pending', False):
            logger.warning("[CLOSE-SETTINGS-TRACE] _close_settings_flow: EARLY-RETURN, "
                            "already pending (re-entrancy guard)")
            return
        tm = getattr(self.main_window, 'theme_manager', None)
        logger.warning(
            f"[CLOSE-SETTINGS-TRACE] _close_settings_flow ENTRY has_tm={tm is not None} "
            f"_is_hover_active={getattr(tm, '_is_hover_active', None)} "
            f"_fade_in_flight_BEFORE={getattr(tm, '_fade_in_flight', None)} "
            f"settings_visible={self.settings_panel.isVisible()} "
            f"themes_tab_active={self.main_window.tabs.currentIndex() == 0 if hasattr(self.main_window, 'tabs') else None}"
        )
        if tm:
            self._settings_close_pending = True
            tm._on_theme_unhovered()
            # A settle gap only makes sense — and should only cost anything — when
            # a fade was GENUINELY started by the call above (a real hover-out).
            # Check _fade_in_flight HERE, before call_when_theme_settled's own
            # immediate-vs-deferred branch runs, so the ordinary no-hover dismiss
            # (the overwhelming majority of dismisses) proceeds with truly zero
            # added delay rather than a gap that happens to be scheduled for 0ms.
            _was_fading = bool(getattr(tm, '_fade_in_flight', False))
            logger.warning(
                f"[CLOSE-SETTINGS-TRACE] after _on_theme_unhovered(): "
                f"_fade_in_flight_AFTER={_was_fading} "
                f"_is_hover_active={getattr(tm, '_is_hover_active', None)} "
                f"_active_display_theme_internal={getattr(tm, '_active_display_theme_internal', None)!r}"
            )
            if _was_fading:
                logger.warning("[CLOSE-SETTINGS-TRACE] waiting via call_when_theme_settled")
                tm.call_when_theme_settled(self._finish_close_settings_flow_with_gap)
            else:
                logger.warning("[CLOSE-SETTINGS-TRACE] no fade started — proceeding immediately")
                self._close_settings_flow_after_settle_gap()
        else:
            self._close_settings_flow_after_settle_gap()

    def _finish_close_settings_flow_with_gap(self):
        """Reached only when a genuine hover-out snapback was actually settled
        (see _close_settings_flow's docstring). A small additional settle gap runs
        first so the revert is perceptible as its own step before the panel starts
        moving, rather than the slide's first frame landing in the same tick the
        fade completes."""
        logger.warning("[CLOSE-SETTINGS-TRACE] settled — starting settle gap timer")
        QTimer.singleShot(_SNAPBACK_SETTLE_GAP_MS, self._close_settings_flow_after_settle_gap)

    def _close_settings_flow_after_settle_gap(self):
        logger.warning("[CLOSE-SETTINGS-TRACE] _close_settings_flow_after_settle_gap: "
                        "starting slide-out animation now")
        # Clear the re-entrancy guard from _close_settings_flow HERE, unconditionally
        # (both the early-return-if-already-running path below and the normal path) —
        # once this method runs, either the slide is about to start (after which
        # _is_closing("settings") takes over as the correct re-entrancy signal) or it
        # was already running (an unrelated stale race, not this guard's concern).
        # Stranding this True would permanently block every future Settings dismiss.
        self._settings_close_pending = False
        # Hide and collapse the excluded-books list explicitly on close —
        # belt-and-suspenders (reload() on the next open also collapses it),
        # and avoids it lingering visible for a frame while the panel starts
        # its slide-out.
        popup = getattr(self.main_window, 'excluded_books_popup', None)
        if popup and popup.isVisible():
            popup.set_expanded(False)
            popup.hide()
            self.main_window.excluded_books_section.set_expanded(False)
        if self.settings_panel_animation.state() == QAbstractAnimation.State.Running:
            return
        panel_w = self.settings_panel.width()
        sidebar_y = 56
        self.settings_panel_animation.setStartValue(QPoint(0, sidebar_y))
        self.settings_panel_animation.setEndValue(QPoint(-panel_w, sidebar_y))
        self.settings_panel_animation.finished.connect(self._on_settings_hidden)
        self.settings_panel_animation.start()
        self._clear_transport_bar_blur()

        if self.config.get_blur_enabled():
            self.blur_animation.setStartValue(self.blur_effect.blurRadius())
            self.blur_animation.setDuration(_BLUR_OUT_MS)
            self.blur_animation.setEndValue(0)
            self.blur_animation.start()
            self._clear_visual_area_clip()
        else:
            self.blur_effect.setBlurRadius(0)
            self._clear_visual_area_clip()

    def _on_settings_hidden(self):
        try:
            self.settings_panel_animation.finished.disconnect(self._on_settings_hidden)
        except:
            pass
        self.settings_panel.hide()
        self._release_panel_focus(self.settings_panel)
        self._notify_panel_closed()

    def _on_sidebar_hidden(self):
        logger.debug(
            f"t={time.perf_counter():.6f} [_on_sidebar_hidden ENTRY] "
            f"sidebar_expanded={self.sidebar_expanded}"
        )
        if not self.sidebar_expanded:
            self._notify_panel_closed()

    def _notify_panel_closed(self):
        if self.is_any_panel_visible():
            return
        tm = getattr(self.main_window, 'theme_manager', None)
        if tm:
            tm._fire_pending_rotation()

    def _complete_main_fade(self):
        """Main-window theme-fade-in-flight guard for every panel-open flow that can be
        reached WITHOUT going through _toggle_sidebar (direct-open branch of each
        _open_*_flow, and open_book_detail). complete_main_fade is the same call
        _toggle_sidebar already makes before a right-click-driven sidebar open — it fully
        re-polishes the slider @Property colors via _apply_stylesheets, unlike
        abort_theme_fade (stops animations but never re-polishes, stranding sliders at an
        intermediate color) or snap_theme_forward (Settings-panel-tuned, explicitly wrong
        for the main window per _toggle_sidebar's own comment). No-op if no fade is running
        (ThemeManager.complete_main_fade's own guard). Was previously named
        _abort_theme_fade and called theme_manager.abort_theme_fade() — renamed and
        rewired 2026-07-10 after confirming via live focus-trace-style investigation that
        the keyboard-shortcut panel-open path (T then L/G/P/A/S/Z) bypasses
        _toggle_sidebar entirely when the sidebar is collapsed, so it never reached
        complete_main_fade and left sliders stranded mid-fade under the newly-opened
        panel — a gap anticipated in NOTES.md 2026-06-19 but not caught when the six
        shortcuts were added, because abort_theme_fade's name was conflated with
        complete_main_fade's actual behavior without diffing the two bodies."""
        tm = getattr(self.main_window, 'theme_manager', None)
        if tm:
            tm.complete_main_fade()

    def _flush_pending_restyle(self):
        """Run any pending deferred invisible-surface theme batch synchronously NOW,
        before a panel paints. Called at the top of every _start_*_entry (before
        show()) to cover the SIDEBAR-QUEUED open path: there _complete_main_fade runs
        early (in _open_*_flow) but the actual show() is dispatched ~200ms later from
        _on_sidebar_closed_for_panel, a window in which a book-load batch could arm and
        not-yet-run. Direct opens are already covered by _complete_main_fade's flush;
        this closes the queued gap at the true pre-show() instant. No-op if nothing
        pending. See plans/going-forward-on-this-twinkly-corbato.md §3."""
        tm = getattr(self.main_window, 'theme_manager', None)
        if tm:
            _was_pending = getattr(tm, '_deferred_restyle_pending', False)
            logger.debug(f"[STUTTER-TRACE] t={time.perf_counter():.6f} _flush_pending_restyle: "
                         f"CALLED was_pending={_was_pending}")
            tm.flush_deferred_restyle()
            # Separate catch-up, same pre-show() instant: _apply_stylesheets skips a
            # HIDDEN settings/speed/sleep/sprint panel (see apply_pending_panel_sheet for
            # the measurement), and flush_deferred_restyle above does NOT cover those —
            # it drains the library/stats/tags/book_detail batch only. Without this a
            # panel hidden across a theme change would open with stale colours.
            if hasattr(tm, 'apply_pending_panel_sheet'):
                for _attr in ('settings_panel', 'speed_panel', 'sleep_panel', 'sprint_panel'):
                    _p = getattr(self.main_window, _attr, None)
                    if _p is not None and not _p.isVisible():
                        tm.apply_pending_panel_sheet(_p)

    def _any_panel_animating(self):
        """Returns True if any sliding panel or blur animation is currently running."""
        animations = [
            self.sidebar_animation,
            self.library_panel_animation,
            self.settings_panel_animation,
            self.speed_panel_animation,
            self.sleep_panel_animation,
            self.sprint_panel_animation,
            self.stats_panel_animation,
            self.tags_panel_animation,
            self.blur_animation,
        ]
        if self.book_detail_panel_animation:
            animations.append(self.book_detail_panel_animation)
        return any(anim.state() == QAbstractAnimation.State.Running for anim in animations)

    def call_when_panels_settled(self, callback, coalesce_key=None):
        """Invoke `callback` once nothing in `_any_panel_animating()` is running.
        Synchronous and immediate when nothing is running — the panel-side analogue
        of ClickSlider.when_animations_done (ui/controls.py).

        `coalesce_key` (added 2026-08-03, snapback-stuck-theme fix): when given a
        non-None key, this call REPLACES any already-queued waiter with the same
        key in place, instead of appending a second entry. Without this, a burst of
        calls that all arrive while `_any_panel_animating()` is True (e.g. a theme
        hover immediately followed by an unhover, both issued before the settings
        panel's own open animation finishes) queue as independent FIFO entries and
        replay in ISSUE order rather than INTENT order — so an earlier hover-preview
        call can resume and apply AFTER a later unhover-snapback call, leaving the
        theme stuck on the hover preview. Confirmed live (see
        review/Investigation_260803_fallback_necessity.md and the snapback fix design
        that superseded its "fallback is load-bearing" attribution): the existing
        `snap_theme_forward` fallback does NOT catch this — it guards on
        `_fade_overlay.isVisible()`, which is False throughout this mechanism, since
        no `_fade_anim` ever starts. Only `ThemeManager` passes a key today
        (`"theme_change"`); every other caller passes None and keeps today's
        append-only FIFO behavior unchanged.

        WHY THIS EXISTS (2026-07-28). `ThemeManager._on_theme_changed`'s animation
        guard used to defer via a flat 700ms retry timer (`_PANEL_ANIM_GUARD_MS`).
        Against a 1500ms blur-in that guarantees at least two retry rounds and adds
        up to 700ms of pure polling overshoot: the first theme hover after opening
        Settings took ~2.1s to preview, every time (live-traced 03:34:44-47). Slides
        are only 200-300ms AND finish before the blur starts (`_start_visual_area_blur`
        is called FROM the slide-finished callback), so the blur is the long pole.

        WHY A PREDICATE RE-CHECK AND NOT `finished`. Mirroring the `_fade_running`
        branch's signal-based resume is the obvious move and it is WRONG here:
        `QPropertyAnimation.stop()` does not emit `finished` (verified empirically,
        2026-07-28), and `blur_animation.stop()` runs unconditionally on every panel
        open (`_start_visual_area_blur`) and on blur-toggle-off. A `finished`-based
        resume would be silently dropped — the exact failure already diagnosed three
        times against `_fade_anim`. `stateChanged` fails differently: it fires on that
        same `stop()`, i.e. mid-panel-open BEFORE the replacement blur starts, which is
        precisely the window the guard protects (a 300ms restyle landing mid-tween
        freezes the blur for ~310ms — measured).

        So: event-driven in EFFECT (fires within one frame of the true settle instant),
        predicate-driven in MECHANISM (immune to `stop()` by construction). Same
        property transport_bar_blur.py relies on after its own polled→event-driven
        migration: never try to cancel an armed callback; let it fire and make the
        callback cheap to re-evaluate.

        Measured against the shipped mechanism: a restyle fired by this watch leaves the
        blur tween byte-identical to running it alone (94 frames, 17.0ms worst gap, both
        cases), versus a 316.2ms freeze for one landing mid-tween.
        """
        if not self._any_panel_animating():
            callback()
            return
        if coalesce_key is not None:
            for i, (key, _cb) in enumerate(self._panels_settled_waiters):
                if key == coalesce_key:
                    self._panels_settled_waiters[i] = (coalesce_key, callback)
                    self._arm_settled_watch()
                    return
        self._panels_settled_waiters.append((coalesce_key, callback))
        self._arm_settled_watch()

    def has_settled_waiter(self, coalesce_key):
        """True if a waiter with this coalesce_key is currently queued in
        `_panels_settled_waiters` (added 2026-08-03, snapback-stuck-theme fix).

        Needed because `_on_theme_changed`'s early no-op guard (theme_manager.py, near
        its top) compares the requested `theme_name`/`hover` against
        `_active_display_theme_internal`/`_is_hover_active` — values that are ONLY
        updated by `_mark_theme_applied`, called from inside the branch that actually
        ran `_apply_stylesheets`. A call deferred into this queue (e.g. a hover preview
        issued while `_any_panel_animating()` is True) has NOT reached that point yet —
        `_active_display_theme_internal` still reflects whatever was active BEFORE the
        deferred call, not the deferred call's own target. If a second call for a
        DIFFERENT theme/hover-state (e.g. the unhover snapback, reverting to the
        original active theme) arrives while that first call is still queued, it can
        coincidentally match the still-stale `_active_display_theme_internal` and get
        silently swallowed by the no-op guard — dropping the snapback entirely and
        leaving the queued preview to apply, unopposed, once it resumes. The guard must
        skip itself whenever this returns True for the "theme_change" key, since
        `_active_display_theme_internal` cannot be trusted as ground truth while a
        same-key call is still in flight through this queue.
        """
        return any(key == coalesce_key for key, _cb in self._panels_settled_waiters)

    def _arm_settled_watch(self):
        """Arm the settle tick if it is not already armed.

        The early-return is load-bearing, not an optimisation: it means the timer is
        NEVER restarted while running. `_panel_guard_timer` — the mechanism this
        replaces — did `stop()` then `start()` on every re-arm, so its 700ms deadline
        was retriggerable; because re-arming was driven by mouse motion (hover sweeps
        produce enter/leave pairs far faster than 700ms apart), a queued call could be
        starved indefinitely. That was the 2026-07-22 "snapback hangs" incident, whose
        fix addressed the entry into the branch but left this property intact. Here the
        deadline is absolute and additional waiters simply join the queue.
        """
        if self._settled_watch_armed:
            return
        self._settled_watch_armed = True
        self._settled_watch_timer.start()

    def _on_settled_watch_tick(self):
        if self._any_panel_animating():
            self._settled_watch_armed = False
            self._arm_settled_watch()
            return
        self._settled_watch_armed = False
        # Swap BEFORE invoking: a callback may synchronously re-enter
        # call_when_panels_settled (ThemeManager._on_theme_changed resumes via a full
        # re-call, which can re-defer), and that new waiter must land in a fresh list
        # rather than one being iterated.
        waiters, self._panels_settled_waiters = self._panels_settled_waiters, []
        logger.debug(
            f"t={time.perf_counter():.6f} [settle-watch] panels settled, "
            f"draining {len(waiters)} waiter(s)"
        )
        for _key, cb in waiters:
            cb()

    def is_any_full_panel_visible(self):
        """Returns True if any full panel or the chapter-list overlay is open — i.e.
        everything is_any_panel_visible checks EXCEPT the sidebar. The L shortcut
        (SHOW_LIBRARY) uses this to no-op when a panel is already up while still
        allowing the sidebar-open case to flow through _open_library_flow's queued
        close-then-open."""
        return any([
            self.library_panel.isVisible(),
            self.settings_panel.isVisible(),
            self.speed_panel.isVisible(),
            self.sleep_panel.isVisible(),
            self.sprint_panel.isVisible(),
            self.stats_panel.isVisible(),
            self.tags_panel.isVisible(),
            self.book_detail_panel.isVisible() if self.book_detail_panel else False,
            self.main_window.chapter_list_widget.isVisible(),
        ])

    def is_any_panel_visible(self):
        """Returns True if the sidebar or any configuration panel is currently open."""
        return self.sidebar_expanded or self.is_any_full_panel_visible()

    def is_any_panel_animating(self):
        """Returns True if any panel/sidebar slide animation is currently running.

        Gate for the idle cover preloader: panel SLIDE animation is the confirmed
        interference source (see the library slide-in jank investigation) — a background
        sized-cover LANCZOS batch landing mid-slide stalls the motion. This is distinct
        from is_any_panel_visible: an already-open, static panel is NOT interference
        (tested), so the preloader gates on animating, not on visible. book_detail_panel's
        animation is created lazily, so it's guarded with getattr."""
        anims = [
            self.sidebar_animation,
            self.library_panel_animation,
            self.settings_panel_animation,
            self.speed_panel_animation,
            self.sleep_panel_animation,
            self.sprint_panel_animation,
            self.stats_panel_animation,
            self.tags_panel_animation,
            self.book_detail_panel_animation,
        ]
        return any(
            a is not None and a.state() == QAbstractAnimation.State.Running
            for a in anims
        )

    def is_overlay_open_or_committed(self):
        """The single gate for 'ignore a second overlay-open request'. True if any full
        overlay is present or mid-animation, OR a panel-open is already committed but the
        panel hasn't shown yet (the sidebar-queued handoff sub-window).

        Deliberately EXCLUDES a bare expanded sidebar with nothing pending: opening the
        sidebar is not itself an overlay, and the queued-open path (_open_*_flow ->
        _toggle_sidebar close -> _on_sidebar_closed_for_panel dispatch) depends on being
        able to open a panel FROM the sidebar. `is_any_full_panel_visible` already excludes
        the sidebar; `is_any_panel_animating` reads the sidebar animation True only while it
        is actually sliding, so a settled-open sidebar with no _pending_panel_open is False.

        Every overlay-OPEN entry point must consult this first and drop (early-return) the
        request if it's True — see the entry-point guards in panels.py/app.py. `open_book_detail`
        is the one intentional exception: it opens only from within an already-open panel
        (library/stats/tags), never races a fresh open, so it is left ungated."""
        return (self.is_any_full_panel_visible()
                or self.is_any_panel_animating()
                or self._pending_panel_open is not None)

    # ── App-wide Tab/Escape policy support ───────────────────────────────────
    # These back the Tab/Escape branch in MainWindow.eventFilter. Kept here because
    # PanelManager already owns every _close_*_flow and the visible-panel priority chain
    # (handle_drag_area_right_click), so close-logic and "which panel is open" stay in one place.

    _CLOSE_ANIMS = (
        ("library", "library_panel_animation"),
        ("settings", "settings_panel_animation"),
        ("speed", "speed_panel_animation"),
        ("sleep", "sleep_panel_animation"),
        ("sprint", "sprint_panel_animation"),
        ("stats", "stats_panel_animation"),
        ("tags", "tags_panel_animation"),
    )

    def _is_closing(self, key):
        """True while `key`'s panel is mid-slide — still isVisible(), but on its way
        out (2026-07-28).

        A panel stays isVisible() for the WHOLE close animation, so
        active_full_panel used to keep naming it for another ~300ms after the user
        had already dismissed it. A right-click arriving in that window was routed
        to that panel's close flow, which early-returns while its own animation runs
        — so the click was silently swallowed instead of falling through to the
        sidebar toggle. Reported live: "close the panel, right click gets
        swallowed."

        Same shape as the sidebar drop fixed earlier today, in four more places
        (_close_speed_flow / _close_sleep_flow / _close_stats_flow /
        _close_tags_flow all guard identically). Fixed here rather than in each
        flow: those guards are correct — restarting a running slide would break it —
        the bug is that the DISPATCHER treated a closing panel as an open one.
        """
        anim = getattr(self, dict(self._CLOSE_ANIMS).get(key, ""), None)
        return anim is not None and anim.state() == QAbstractAnimation.State.Running

    def active_full_panel(self):
        """Which single full panel/overlay is currently open, as a string key
        ('library'/'settings'/'speed'/'sleep'/'sprint'/'stats'/'tags'/'book_detail'/'chapter_list'),
        or None. Same visibility checks and priority order as handle_drag_area_right_click —
        there is no existing single accessor, so this centralizes it.

        A panel that is mid-CLOSE does not count as open — see _is_closing.

        book_detail_panel IS CHECKED FIRST (2026-09-24 reorder, live-reported regression trace —
        see the CLAUDE.md rule this fix produced, and NOTES.md, for the full mechanism). Book
        Detail is the one panel that can be visible SIMULTANEOUSLY with another (it opens over
        Stats or Library — see the class docstring/CLAUDE.md's "Book detail uniquely enters from
        the right"/"can open over Stats or Library" notes), and it is always the topmost,
        actually-interactive one when both are visible — it raises above the underlay rather than
        hiding it. Checking library/settings/etc. first (the original order) meant this method
        reported the UNDERLAY's key for the whole time Book Detail was open, which several real
        consumers either had to work around with their own extra book_detail_panel.isVisible()
        check (MainWindow._handle_tab_escape's library branch) or simply never reached at all
        because Book Detail's own event filter wins the dispatch race first (escape_active_panel,
        _handle_tab_escape's Tab branch) — masking the wrong answer rather than it mattering. But
        at least two consumers were NOT masked and were genuinely wrong: (1) a right-click on the
        cover art while Book Detail was open over Stats/Library closed the WRONG panel (Stats/
        Library, via handle_drag_area_right_click's now-dead-until-this-fix `elif panel ==
        "book_detail":` branch) instead of Book Detail itself; (2) MainWindow._kbdnav_active_panel_key
        (app.py) resolved to "stats"/"settings" while Book Detail was open over Stats, which let
        _set_keyboard_nav_active dispatch a SYNTHETIC QHoverEvent(HoverMove) at the real, occluded
        Stats tab bar (via _resync_tab_bar_hover) using the cursor's live position — the cursor was
        genuinely over Book Detail, not the tab bar, but the synthetic event doesn't know that and
        Qt's native QTabBar hover state doesn't either. This produced a real, crisp (not blurred/
        stale-pixmap) tab highlight that appeared to "come from nothing" on Book Detail close,
        live-reported and traced via a focusChanged/hover-event tracer 2026-09-24 — the fix that
        was tried first (protecting the tab bar during frost_panel_backdrop's own hide/show grab
        window) made no difference because that was never the actual mechanism; this reorder is.
        No consumer's behavior is worsened by this reorder — every call site was audited: two are
        now MORE correct (the two bugs above), the rest either check `is None` (unaffected by
        which non-None key is returned), are scoped to panels that can never coexist with Book
        Detail (Settings/Speed/Sleep/Sprint — mutually exclusive with it), or already had their
        own explicit book_detail_panel.isVisible() workaround (now redundant but harmless)."""
        if self.book_detail_panel and self.book_detail_panel.isVisible():
            return "book_detail"
        if self.library_panel.isVisible() and not self._is_closing("library"):
            return "library"
        if self.settings_panel.isVisible() and not self._is_closing("settings"):
            return "settings"
        if self.speed_panel.isVisible() and not self._is_closing("speed"):
            return "speed"
        if self.sleep_panel.isVisible() and not self._is_closing("sleep"):
            return "sleep"
        if self.sprint_panel.isVisible() and not self._is_closing("sprint"):
            return "sprint"
        if self.stats_panel.isVisible() and not self._is_closing("stats"):
            return "stats"
        if self.tags_panel.isVisible() and not self._is_closing("tags"):
            return "tags"
        if self.main_window.chapter_list_widget.isVisible():
            return "chapter_list"
        return None

    def escape_active_panel(self) -> bool:
        """Close whichever full panel is open, reusing its existing _close_*_flow. Returns True
        if something was closed, False if nothing was open. Invents no new close path — mirrors
        handle_drag_area_right_click's chain.

        Two deliberate exclusions (both return False, i.e. 'not handled here'):
        - book_detail: BookDetailPanel installs its OWN QApplication event filter in showEvent
          (after MainWindow's), so its Escape handler runs first and already closes/cancels —
          this method is never reached for Escape while detail is open.
        - chapter_list: it grabs keyboard focus when open and has its own keyPressEvent Escape
          (which also clears the digit-jump buffer/timer before fading out). Deferring to it
          preserves that cleanup and matches pre-existing behavior exactly."""
        panel = self.active_full_panel()
        if panel == "library":
            self._close_library_flow()
        elif panel == "settings":
            self._close_settings_flow()
        elif panel == "speed":
            self._close_speed_flow()
        elif panel == "sleep":
            self._close_sleep_flow()
        elif panel == "sprint":
            self._close_sprint_flow()
        elif panel == "stats":
            self._close_stats_flow()
        elif panel == "tags":
            self._close_tags_flow()
        else:
            # None, book_detail, or chapter_list — see docstring; not closed here.
            return False
        return True

    def panel_tab_widgets(self, panel: str) -> list:
        """Focusable controls of `panel`, in tab order, for Tab cycling. Only settings/speed/
        sleep/sprint participate; every other context is a Tab no-op (returns []). Filters to
        widgets currently visible within the panel and whose focus policy accepts Tab, in
        findChildren order (== creation == visual order for these, confirmed). Settings is
        scoped to the active tab; on the Themes tab the N generated theme swatches (ThemeItem —
        mode/bulk buttons are plain QPushButton) are excluded, since swatch-grid keyboard nav is
        deferred to a later arrows+space design.

        For settings/stats, the tab bar itself is prepended as the first Tab stop (it lives on
        the QTabWidget, not inside currentWidget(), so findChildren under the active tab would
        miss it): Tab then cycles tab-bar -> the active tab's controls -> back to the tab bar,
        and the traveling focus marker (ui/focus_marker.py) can trace the tab-header shape too.
        Stats added 2026-09-08 (first pass): it has its OWN QTabWidget instance
        (`self.stats_panel.tabs`, separate from `self.main_window.tabs`), so it gets the same
        tab-bar-as-first-stop treatment as settings, scoped to Stats' own tab bar."""
        if panel == "settings":
            root = self.main_window.tabs.currentWidget()
        elif panel == "speed":
            root = self.speed_panel
        elif panel == "sleep":
            root = self.sleep_panel
        elif panel == "sprint":
            root = self.sprint_panel
        elif panel == "stats":
            stats_panel = getattr(self.main_window, 'stats_panel', None)
            root = stats_panel.tabs.currentWidget() if stats_panel is not None else None
        else:
            return []
        if root is None:
            return []
        if panel in ("speed", "sleep", "sprint"):
            # Delegate to flat_panel_rows' own layout-order walk instead of findChildren
            # below — found live 2026-09-10 (Speed's Tab order: grid -> Step -> Undo ->
            # Skip -> Smart rewind -> Default speed -> wraps to grid, skipping Default
            # speed's real visual position right after the grid). Root cause: Speed's
            # Default speed row is DELETED AND RECREATED on every panel open
            # (_rebuild_def_speed_row, called from _start_speed_entry) so its buttons
            # become the NEWEST entries in Qt's internal child-object list — findChildren
            # order reflects recreation order, not visual/layout order, the moment any
            # widget in the panel gets rebuilt after construction. flat_panel_rows'
            # _walk reads the actual QVBoxLayout/QHBoxLayout/QGridLayout structure
            # directly (lay.itemAt(i) in real layout order), so it's immune to this by
            # construction — it already gets Speed's arrow-key navigation right; Tab was
            # the only consumer still using the fragile findChildren walk. Flattening its
            # row-of-rows shape (one row per grid row's grouping doesn't apply here — a
            # grid row IS one opaque list of every navigable cell already, so flattening
            # is just concatenation, no cell reordering) gives Tab the same order arrows
            # already use.
            return [w for row in self.flat_panel_rows(panel) for w in row]
        result = []
        if panel == "settings":
            tab_bar = self.main_window.tabs.tabBar()
            if tab_bar.isVisible() and (tab_bar.focusPolicy() & Qt.FocusPolicy.TabFocus):
                result.append(tab_bar)
        elif panel == "stats":
            tab_bar = self.main_window.stats_panel.tabs.tabBar()
            if tab_bar.isVisible() and (tab_bar.focusPolicy() & Qt.FocusPolicy.TabFocus):
                result.append(tab_bar)
        for w in root.findChildren(QWidget):
            if isinstance(w, ThemeItem):
                continue  # deferred: theme swatches get their own arrows+space nav later
            if panel == "stats" and isinstance(w, QScrollArea):
                # Overall's stat-grid QScrollArea (and any other purely structural scroll
                # container in Stats) is excluded 2026-09-09 — live-reported root cause of
                # "tab twice from Overall reaches the cover-art carousel": these containers are
                # real StrongFocus-eligible widgets with no visible focus indicator of their own
                # (no highlight, nothing painted), so landing on one via Tab was invisible —
                # and once real Qt focus was ON one, a SECOND Tab press did not reliably route
                # back through this hand-rolled cycle the way a plain QWidget/QPushButton does,
                # instead falling through to Qt's own native Tab-order chain, which reached a
                # completely unrelated MainWindow-level widget (the carousel). No QScrollArea in
                # Stats is ever meant to be a real keyboard stop — Day/Week/Month's actual
                # content lives in StatsRowListView (excluded just below for its own, related
                # reason), not the scroll container itself.
                continue
            if isinstance(w, StatsRowListView):
                # Day/Week/Month's row list is deliberately OUT of the generic Tab-cycle,
                # 2026-09-09 — same shape as LibraryPanel's own QListView, which was removed
                # from ITS Tab cycle for the identical reason (2026-07-10, see that method's
                # own comment): before this exclusion, Tab from the row list picked up
                # whatever OTHER real widget findChildren happened to find next in the tab
                # (a QScrollArea, or worse — live-reported 2026-09-09 landing on the main
                # window's cover-art carousel entirely), none of which is a sensible "next
                # stop" for a list that already owns Up/Down internally. The row list is
                # reachable only via Down from the tab bar (MainWindow._handle_stats_arrows)
                # and left only via Up/Shift+Tab back to the tab bar (StatsRowListView's own
                # keyPressEvent) — never via this generic cycle in either direction.
                continue
            if w.objectName() == "stats_nav_btn":
                # The Day/Week/Month period ‹/› buttons (_day_prev_btn/_day_next_btn etc.) —
                # excluded from the Tab cycle 2026-09-09, live design call: Left/Right always
                # cycle the period directly (StatsPanel.keyPressEvent's own _NAV_METHODS), so
                # these buttons must never become a keyboard stop at all — no highlight, no
                # Tab target, matching how the row list itself is excluded just above for the
                # analogous "this has its own dedicated keyboard path, stay out of the generic
                # cycle" reason. Matched by objectName rather than a class check since these
                # are plain QPushButtons with no dedicated subclass.
                continue
            if isinstance(w.parentWidget(), QAbstractSpinBox):
                # A QSpinBox's internal QLineEdit (its text-entry sub-widget) is itself
                # TabFocus-eligible (Qt.FocusPolicy.WheelFocus, which includes TabFocus),
                # findChildren(QWidget) walks INTO the spin box and picks it up as a SEPARATE
                # Tab stop from the spin box itself — duplicating one control into two entries.
                # Reported live 2026-09-08 (Stats' day_start_spin, the app's only QSpinBox):
                # Tab appeared to be a no-op, actually landing on this invisible-from-the-
                # spinbox-itself internal child instead of advancing to the next real control.
                # The QSpinBox itself is the real, single Tab stop; its internal line-edit is
                # never a separate one.
                continue
            if not w.isVisibleTo(root):
                continue
            if not w.isEnabled():
                # Qt's own Tab order skips disabled widgets; this cycle is hand-rolled, so it
                # has to skip them explicitly or Tab would land on something unusable (Library's
                # Remove/Rescan while no folders are configured). Keeps Tab and arrow navigation
                # agreeing — settings_tab_button_rows applies the same rule.
                continue
            if not (w.focusPolicy() & Qt.FocusPolicy.TabFocus):
                continue
            result.append(w)
        return result

    def settings_tab_button_rows(self) -> list:
        """The active settings tab's controls grouped into VISUAL rows, for arrow-key navigation
        (see MainWindow._handle_settings_arrows). Each entry is a list of widgets on one line,
        left-to-right; rows are top-to-bottom. Empty list on a tab not yet wired for arrow
        navigation (see _ARROW_NAV_TABS).

        Derived LIVE from the layout rather than from mw's per-group dicts (fade_buttons,
        blur_buttons, digit_mode_buttons, ...) or any build-time snapshot, for two reasons:
          * Controls are hidden and shown at runtime — Look's Chapter-notches line hides its
            Animation pair when notches are Off, and Audio's "Reset to defaults" is hidden
            whenever every audio setting is already at its default (AudioSettingsTab.
            update_visuals). A fixed structure would offer a keyboard stop on something that is
            not on screen, so visibility has to be re-read per keypress.
          * Row membership then follows whatever the builder actually lays out — add or reorder
            a row and this keeps working with no second place to update.

        TWO ROW SHAPES, because the tabs genuinely have two:
          * a QHBoxLayout of controls — the common case. Two logical groups sharing ONE layout
            are deliberately ONE row, matching what the user sees: Look's notches line
            (notches + Animation) and Controls' digit line (By name/By index + Auto-play/Jump
            only) are both this shape.
          * a single widget added straight to the tab's QVBoxLayout via addWidget — Audio's L/R
            balance slider and its full-width "Reset to defaults" button. These become one-item
            rows, so Up/Down reach them like any other row and Left/Right have something
            meaningful to do (the arrow handler steps a slider's value rather than moving focus).

        Membership is by focus policy, not by class: any widget that accepts focus counts, which
        is what lets a ClickSlider and a non-#pattern_button QPushButton participate without
        being special-cased here. Non-focusable decoration (header QLabels, the trailing
        stretch) is skipped for free.

        Two Library list boxes are deliberately NOT in `rows` at all, even though both are fully
        arrow-navigable: `folder_list_widget` (a real member of `lib_layout`, but handled entirely
        by `_handle_settings_arrows`'s own `isinstance(focus, QListWidget)` branch once focus
        reaches it — Up/Down inside it must never be treated as a row-to-row grid move) and
        `excluded_books_popup` (not even in `lib_layout` — it's an absolutely-positioned overlay
        parented to `library_tab` — with its own self-contained `keyPressEvent`, entered via a
        special-cased Down/Right from Persist search filter's row in `_handle_settings_arrows`).
        Both are still real Tab stops via `panel_tab_widgets`'s separate `findChildren` walk.

        Themes is NOT handled by the generic walk below — it delegates to `themes_tab_rows()`
        instead (see that method's docstring for why the generic shape doesn't fit it). Every
        caller of this method (the arrow handler, the marker hand-back check) gets Themes' real
        rows this way with no second call site to remember."""
        tabs = getattr(self.main_window, 'tabs', None)
        if tabs is None or tabs.tabText(tabs.currentIndex()) not in _ARROW_NAV_TABS:
            return []
        if tabs.tabText(tabs.currentIndex()) == "Themes":
            return self.themes_tab_rows()
        root = tabs.currentWidget()
        if root is None:
            return []
        layout = root.layout()
        if layout is None:
            return []

        def _navigable(w) -> bool:
            # isEnabled matters as much as visibility: Library disables Remove/Rescan while no
            # folders are configured (app.py's _update_folder_list_widget), and Qt already skips
            # disabled widgets in Tab order — arrow navigation has to agree, or the marker would
            # stop on a dimmed control that cannot be activated.
            if (w is None
                    or not w.isVisibleTo(root)
                    or not w.isEnabled()
                    or not (w.focusPolicy() & Qt.FocusPolicy.TabFocus)):
                return False
            # An EMPTY list box is not worth stopping on — there is nothing in it to select, so
            # the keyboard should pass straight over it (Library's Manage folders with no
            # folders added). It becomes a stop again the moment it has content.
            if isinstance(w, QListWidget) and w.count() == 0:
                return False
            return True

        rows = []
        for i in range(layout.count()):
            item = layout.itemAt(i)
            sub = item.layout()
            if sub is not None:
                row = [w for j in range(sub.count())
                       if _navigable(w := sub.itemAt(j).widget())]
                if row:
                    rows.append(row)
                continue
            # A widget sitting directly in the tab's own column (no inner QHBoxLayout) is its
            # own single-item row — Audio's balance slider and Reset button.
            w = item.widget()
            if _navigable(w):
                rows.append([w])
        return rows

    def themes_tab_rows(self) -> list:
        """Themes-tab-specific row source (see settings_tab_button_rows's docstring for why
        that generic walk delegates here instead of handling Themes itself). Returns rows in
        the same shape settings_tab_button_rows produces — a list of left-to-right widget
        lists, top-to-bottom — so MainWindow._handle_settings_arrows's row-stepping (Up/Down
        to the next/previous row's first widget, Left/Right native-within-row) works
        unmodified for everything EXCEPT the swatch grid, which is deliberately represented
        as a single ONE-ITEM row holding `swatch_box` itself — mirroring exactly how
        `folder_list_widget` is a one-item row that then owns its own internal Up/Down/Left/
        Right once focus reaches it (see _handle_settings_arrows's QListWidget branch and,
        here, MainWindow._handle_themes_swatch_arrows).

        Row order top-to-bottom, matching what's on screen:
          1. the cover-art mode row (Off / With pool / Exclusive) — always present.
          2. `swatch_box` as a single opaque stop — only when `pool_container` is visible
             (hidden entirely in Exclusive mode, along with everything below it).
          3. the bulk-action row (Add all / Remove all / Change now) — same visibility gate.
          4. the interval row, as one item per QLabel (they act as buttons via a
             mousePressEvent monkeypatch, not real QPushButtons, but are keyboard-navigable
             once given TabFocus — see main_window_builders.build_themes_tab) — same gate.

        `swatch_box` itself needs `Qt.FocusPolicy.StrongFocus` for this to work as a stop;
        the individual ThemeItem swatches inside it deliberately do NOT participate in Tab
        order or this row list (see panel_tab_widgets's ThemeItem exclusion) — the grid is
        entered as one unit and navigated internally, never as N separate stops."""
        mw = self.main_window
        tm = mw.theme_manager
        rows = []
        mode_row = [btn for btn in tm.cover_art_mode_widgets.values()
                    if btn.isVisibleTo(mw) and btn.isEnabled()]
        if mode_row:
            rows.append(mode_row)
        if tm.pool_container is not None and tm.pool_container.isVisible():
            if tm.swatch_box is not None and tm.swatch_box.isVisibleTo(mw):
                rows.append([tm.swatch_box])
            bulk_row = [btn for btn in (mw.add_all_btn, mw.remove_all_btn, mw.change_now_btn)
                        if btn is not None and btn.isVisibleTo(mw) and btn.isEnabled()]
            if bulk_row:
                rows.append(bulk_row)
            interval_row = [lbl for lbl in tm.interval_widgets.values()
                            if lbl.isVisibleTo(mw) and lbl.isEnabled()]
            if interval_row:
                rows.append(interval_row)
        return rows

    def stats_tab_button_rows(self) -> list:
        """Stats' own equivalent of settings_tab_button_rows, scoped ONLY to the Settings ("⚙")
        tab — first pass (2026-09-08), Overall/Timeline/Day/Week/Month have no arrow-navigable
        button rows yet (Day/Week/Month's row-list keyboard nav is deferred to its own pass; see
        TODO.md). Not folded into settings_tab_button_rows itself because that method reads
        `self.main_window.tabs` specifically (Settings' own QTabWidget) and has Themes-specific
        branching that doesn't apply here — Stats has a SEPARATE QTabWidget instance
        (`self.stats_panel.tabs`) with no swatch-grid-shaped tab to special-case.

        Same generic walk shape as settings_tab_button_rows (a QHBoxLayout of controls is one
        row; a bare widget added straight to the tab's QVBoxLayout is its own one-item row;
        membership is by focus policy, not by class), derived live from the layout for the same
        reason: Stats' Settings tab hides/shows nothing dynamically today, but deriving from the
        live layout costs nothing and keeps this correct if that ever changes.

        `self.day_start_spin` (the day-start-hour QSpinBox) is the tab's LAST row as of this
        pass (moved from first — see build_options_tab in stats_panel.py) — Pryme's call: it's
        the hardest control here to give a clear keyboard-cursor indicator to, so it goes last
        rather than being the first thing arrow navigation encounters."""
        stats_panel = getattr(self.main_window, 'stats_panel', None)
        if stats_panel is None:
            return []
        tabs = getattr(stats_panel, 'tabs', None)
        if tabs is None or tabs.tabText(tabs.currentIndex()) != "⚙":
            return []
        root = tabs.currentWidget()
        if root is None:
            return []
        layout = root.layout()
        if layout is None:
            return []

        def _navigable(w) -> bool:
            return (w is not None
                    and w.isVisibleTo(root)
                    and w.isEnabled()
                    and bool(w.focusPolicy() & Qt.FocusPolicy.TabFocus))

        rows = []
        for i in range(layout.count()):
            item = layout.itemAt(i)
            sub = item.layout()
            if sub is not None:
                row = [w for j in range(sub.count())
                       if _navigable(w := sub.itemAt(j).widget())]
                if row:
                    rows.append(row)
                continue
            w = item.widget()
            if _navigable(w):
                rows.append([w])
        return rows

    def flat_panel_rows(self, panel_key: str) -> list:
        """Row source for Speed/Sleep/Sprint arrow navigation (added 2026-09-07) — the
        equivalent of settings_tab_button_rows()/themes_tab_rows() for a panel with no tabs at
        all, just one flat QVBoxLayout. Same generic-per-row-shape approach and the same reason
        for it (controls hide/show at runtime — e.g. Sleep's disable button, Sprint's grace-
        period submenu rows — so membership is re-read live on every keypress, never cached).

        THREE row shapes here, one more than settings_tab_button_rows' two, because these
        panels' preset grids are a genuine QGridLayout (Speed's 12 speed buttons, Sleep's 14
        duration presets + End of chapter, Sprint's 10 duration presets + End of chapter) —
        unlike anything on a Settings tab:
          * a QHBoxLayout of controls — the common case (Sleep's custom-time-input row, its
            Fade-out row; Sprint's backward-compensation/grace-mode rows).
          * a single widget added straight to the panel's own QVBoxLayout — Sleep's/Sprint's
            disable button, Sprint's Reset-all-sprint-data button, any conflict-confirm label
            currently shown.
          * a QGridLayout — represented as a SINGLE opaque row (one list containing every
            navigable cell in the grid, in `itemAt` order) rather than one row per grid ROW.
            `MainWindow._handle_panel_grid_arrows` owns the real 2-D movement once focus
            reaches the grid, reading the live QGridLayout structure directly (row/column
            counts, `itemAtPosition`, and cell spans — End of chapter spans 2 columns) rather
            than trying to flatten it into `flat_panel_rows`' own row-of-rows shape, which has
            no way to represent a span. Same architecture as Themes' swatch_box: one opaque
            stop in the row list, its own internal navigation once entered.

        Grid cell membership within the opaque row is still filtered by `_navigable` below —
        an item without a widget (an empty grid cell — Sleep's grid has two: End of chapter's
        span leaves (3,0) and (3,1) real slots, occupied; no empty cells today, but a future
        grid might) is skipped the same way a hidden button is."""
        mw = self.main_window
        panel = {"speed": getattr(mw, "speed_panel", None),
                 "sleep": getattr(mw, "sleep_panel", None),
                 "sprint": getattr(mw, "sprint_panel", None)}.get(panel_key)
        if panel is None:
            return []
        layout = panel.layout()
        if layout is None:
            return []

        def _navigable(w) -> bool:
            return (w is not None and w.isVisibleTo(panel) and w.isEnabled()
                    and bool(w.focusPolicy() & Qt.FocusPolicy.TabFocus))

        def _walk(lay, out: list) -> None:
            for i in range(lay.count()):
                item = lay.itemAt(i)
                sub = item.layout()
                if isinstance(sub, QGridLayout):
                    grid_row = [w for j in range(sub.count())
                                if _navigable(w := sub.itemAt(j).widget())]
                    if grid_row:
                        out.append(grid_row)
                    continue
                if sub is not None:
                    row = [w for j in range(sub.count())
                           if _navigable(w := sub.itemAt(j).widget())]
                    if row:
                        out.append(row)
                    continue
                w = item.widget()
                if w is None:
                    continue
                # A bare CONTAINER widget with its OWN internal layout (e.g. Sprint's
                # _grace_submenu, added via addWidget rather than addLayout — a QWidget
                # wrapper used purely to give a group of rows one shared show/hide toggle) is
                # recursed into rather than treated as a single navigable leaf — added
                # 2026-09-07 after this exact case (the grace-period percentage/fixed/custom
                # sub-rows) was silently skipped in full: `_navigable(w)` on the wrapper itself
                # is always False (a plain QWidget has no TabFocus), so nothing inside it was
                # ever reachable at all, live-reported as "skips the second row... and moves to
                # Reset all sprint data" — it wasn't skipping ONE row, the whole submenu was
                # invisible to this walk. Only recurses into a VISIBLE wrapper — an entirely
                # hidden submenu (grace mode not "custom"/"percentage"/"fixed") must stay fully
                # absent from the rows list, same as any other hidden control.
                if not w.isVisibleTo(panel):
                    continue
                inner = w.layout()
                if isinstance(inner, QHBoxLayout) and inner.count() > 0:
                    # The wrapper exists ONLY to hold a single row's worth of buttons side by
                    # side (e.g. _grace_pct_row/_grace_fixed_row) — its contents are ONE row,
                    # not N one-item rows. Collect them directly rather than recursing, which
                    # would otherwise split each button into its own separate row (confirmed
                    # live 2026-09-07: recursing unconditionally here produced one row PER
                    # PERCENTAGE BUTTON instead of one row of six).
                    row = [iw for k in range(inner.count())
                           if _navigable(iw := inner.itemAt(k).widget())]
                    if row:
                        out.append(row)
                    continue
                if inner is not None and inner.count() > 0:
                    # A QVBoxLayout (or anything else stacking sub-rows vertically) — e.g.
                    # _grace_submenu's own submenu_layout, which holds THREE further row
                    # wrappers, one per grace-mode sub-option. Recurse so each of those
                    # becomes its own row in turn.
                    _walk(inner, out)
                    continue
                if _navigable(w):
                    out.append([w])

        rows = []
        _walk(layout, rows)
        return rows

    def grid_layout_for(self, panel_key: str, widget) -> "QGridLayout | None":
        """The real QGridLayout `widget` sits in, if it's one of `panel_key`'s preset grids —
        used by MainWindow._handle_panel_grid_arrows once flat_panel_rows has identified that
        focus is inside a grid-shaped row and real 2-D navigation needs the grid ITSELF, not
        just its flattened widget list.

        Walks the panel's own top-level layout the same way flat_panel_rows does (matching
        detection logic — a QGridLayout item, found via `item.layout()`) rather than asking
        `widget.parentWidget().layout()`: that looks like it should work but does NOT — a
        QWidget has only ONE top-level `.layout()`, which for these panels is always the outer
        QVBoxLayout, never a sub-layout added via `addLayout()` (confirmed live 2026-09-07,
        caught before shipping: `panel.layout() is grid` is False even for a widget added
        directly into that grid). This is the correct way to recover a sub-layout a widget
        belongs to; there is no Qt API that goes the other direction from a plain widget."""
        mw = self.main_window
        panel = {"speed": getattr(mw, "speed_panel", None),
                 "sleep": getattr(mw, "sleep_panel", None),
                 "sprint": getattr(mw, "sprint_panel", None)}.get(panel_key)
        if panel is None:
            return None
        layout = panel.layout()
        if layout is None:
            return None
        for i in range(layout.count()):
            sub = layout.itemAt(i).layout()
            if isinstance(sub, QGridLayout) and sub.indexOf(widget) >= 0:
                return sub
        return None

    # ── Panel-local keyboard focus ownership ─────────────────────────────────
    # Enforces the invariant that MainWindow.keyPressEvent's _focus_allows_global_shortcuts
    # relies on: whenever a panel/overlay is open, SOME widget inside it must hold real Qt
    # focus, so a) that widget (not global shortcuts) has first-and-final say over every key,
    # and b) no OTHER panel's stale-focused widget can bleed through from underneath (Z-order
    # via raise_()/show() has zero effect on keyboard focus — only setFocus()/clearFocus() do).
    # Library and ChapterList already self-manage this (their own showEvent/show_above grab
    # focus); every other panel routes through these two helpers instead of duplicating the
    # isAncestorOf/ordering logic six times.

    # Panels whose keyboard nav participates in the _kbdnav_cursor_anchor/hover-pickup
    # machinery (app.py's MainWindow._pickup_hover_target) — all five panels
    # MainWindow._kbdnav_active_panel_key recognises. "stats" was added 2026-09-15
    # (Live design call: its own "⚙" tab's button rows should pick up from hover too,
    # matching the other four) — Day/Week/Month's row lists are UNAFFECTED by this: they
    # use their own separate, independent poll (StatsRowListView._kbdnav_hover_poll),
    # not this shared anchor at all.
    _HOVER_PICKUP_PANEL_KEYS = frozenset(("settings", "speed", "sleep", "sprint", "stats"))

    def _claim_panel_focus(self, panel_widget, panel_key: str = None):
        """Call once a panel/overlay has been shown and raised, to give it real Qt focus.
        Prefers the first Tab-order-eligible child (panel_tab_widgets, panel_key given) —
        the same target Tab-cycling already treats as "first" — so opening a panel and then
        pressing Tab immediately continues into its SECOND control, not its first, matching
        the existing Tab-cycle's own notion of order. Falls back to the panel widget itself
        (granting it StrongFocus if it doesn't already accept focus) when there's no
        Tab-order list for it (stats/tags/book_detail) or the list is empty."""
        target = None
        if panel_key is not None:
            widgets = self.panel_tab_widgets(panel_key)
            if widgets:
                target = widgets[0]
        if target is None:
            if not (panel_widget.focusPolicy() & Qt.FocusPolicy.StrongFocus):
                panel_widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            target = panel_widget
        target.setFocus(Qt.FocusReason.OtherFocusReason)
        # Hover-pickup baseline (2026-09-15). Stamps `_pickup_cursor_anchor` — NOT
        # `_kbdnav_cursor_anchor` (see that attribute's own __init__ comment in app.py
        # for why the two must never be conflated: _set_keyboard_nav_active(True) fires
        # on EVERY qualifying keypress, including the first, and overwrites
        # _kbdnav_cursor_anchor to the mouse's CURRENT position before
        # _pickup_hover_target ever runs — a first attempt at this stamped that shared
        # anchor and was silently defeated by exactly that overwrite, confirmed live:
        # "Yet to pick up from the mouse... in the settings buttons" persisted even
        # after that fix landed). Without this stamp, `_pickup_cursor_anchor` stays
        # None until the first successful pickup writes it, so a mouse that moved
        # before ANY key was pressed would never be detected as having moved. Stamping
        # here, at panel-open, establishes wherever the mouse was BEFORE any key was
        # ever pressed as the baseline.
        if panel_key in self._HOVER_PICKUP_PANEL_KEYS:
            self.main_window._pickup_cursor_anchor = QCursor.pos()

    def _release_panel_focus(self, panel_widget):
        """Call AFTER panel_widget.hide(), symmetric with _claim_panel_focus. Ordering is
        load-bearing (confirmed live): hide() on a still-focused descendant makes Qt fall
        back and re-grant focus to that same now-hidden widget, so clearing BEFORE hide()
        gets silently undone by hide() itself. Must target the actual focused widget, not
        panel_widget — clearFocus() only acts on `self`, and a container rarely holds focus
        directly, only its descendants do."""
        focused = QApplication.focusWidget()
        if focused is not None and panel_widget.isAncestorOf(focused):
            focused.clearFocus()

    def dismiss_sidebar(self):
        """Closes the sidebar if it's expanded; no-op otherwise. Idempotent (safe to call
        from an action that doesn't know the sidebar's current state). For actions that
        should get the sidebar out of the way WITHOUT closing an already-open panel (which
        is_overlay_open_or_committed already prevents from coexisting) — e.g. opening the
        chapter list, toggling the time label, wheel-scrolling the speed label or the
        chapter-progress slider. Mirrors the `if sidebar_expanded: _toggle_sidebar()` line
        inside hide_all_panels(); pulled out so single-purpose callers don't need the whole
        close-everything sweep."""
        if self.sidebar_expanded:
            self._toggle_sidebar()

    def _on_sidebar_idle_poll_tick(self):
        """Ticks every _SIDEBAR_IDLE_POLL_MS while the sidebar is open (armed/disarmed
        alongside sidebar_expanded in _toggle_sidebar — see _sidebar_idle_poll_timer's
        comment for why this is a poll rather than a MouseMove listener). Compares the
        global cursor position against the last-seen one: any change resets the
        movement clock; no change for _SIDEBAR_IDLE_DISMISS_MS dismisses the sidebar.
        Applies regardless of opened_via, by design (see the plan's section 4)."""
        if not self.sidebar_expanded:
            return
        pos = QCursor.pos()
        if pos != self._sidebar_last_cursor_pos:
            self._sidebar_last_cursor_pos = pos
            self._sidebar_last_movement_ts = time.monotonic()
            return
        elapsed_ms = (time.monotonic() - self._sidebar_last_movement_ts) * 1000
        if elapsed_ms >= _SIDEBAR_IDLE_DISMISS_MS:
            self._toggle_sidebar()

    def on_sidebar_hover_out(self):
        """Called when the cursor leaves the sidebar widget's own rect while it is open.
        Only dismisses when the sidebar was opened via the hotspot — a right-click-opened
        sidebar has no hover-based signal to lose, so hover-out never applies to it (see
        review/Plan_260809_corner_hotspot_sidebar_trigger.md section 4). Also guards
        against a leaveEvent firing mid-slide (the widget's geometry is moving during its
        own open/close animation, which is not a real 'cursor left' signal)."""
        if not self.sidebar_expanded:
            return
        if self._sidebar_opened_via != "hotspot_hover":
            return
        if self.sidebar_animation.state() == QAbstractAnimation.State.Running:
            return
        self._toggle_sidebar()

    def hide_all_panels(self):
        """Closes any open panels."""
        if self.main_window.chapter_list_widget.isVisible():
            self.main_window.chapter_list_widget.fade_out()
        if self.sidebar_expanded:
            self._toggle_sidebar()
        if self.library_panel.isVisible():
            self._close_library_flow()
        if self.settings_panel.isVisible():
            self._close_settings_flow()
        if self.speed_panel.isVisible():
            self._close_speed_flow()
        if self.sleep_panel.isVisible():
            self._close_sleep_flow()
        if self.sprint_panel.isVisible():
            self._close_sprint_flow()
        if self.stats_panel.isVisible():
            self._close_stats_flow()
        if self.tags_panel.isVisible():
            self._close_tags_flow()
        if self.book_detail_panel and self.book_detail_panel.isVisible():
            self._close_book_detail_flow()

    def handle_mouse_press(self, event):
        """Handles mouse press events to prevent panel dismissal when clicking inside."""
        panels = [self.library_panel, self.settings_panel, self.speed_panel, self.sleep_panel,
                  self.sprint_panel, self.stats_panel]
        if self.book_detail_panel:
            panels.append(self.book_detail_panel)
        for panel in panels:
            if panel.isVisible() and panel.geometry().contains(event.pos()):
                return True
        return False

    def handle_drag_area_right_click(self, event):
        """Handles right-click on drag area to dismiss panels or toggle sidebar."""
        logger.debug(
            f"t={time.perf_counter():.6f} [handle_drag_area_right_click ENTRY] "
            f"library={self.library_panel.isVisible()} "
            f"settings={self.settings_panel.isVisible()} "
            f"speed={self.speed_panel.isVisible()} "
            f"sleep={self.sleep_panel.isVisible()} "
            f"sprint={self.sprint_panel.isVisible()} "
            f"stats={self.stats_panel.isVisible()} "
            f"tags={self.tags_panel.isVisible()} "
            f"book_detail={bool(self.book_detail_panel and self.book_detail_panel.isVisible())} "
            f"chapter_list={self.main_window.chapter_list_widget.isVisible()} "
            f"sidebar_expanded={self.sidebar_expanded}"
        )
        self.library_panel.cancel_preload()
        # Route through active_full_panel rather than re-deriving the chain here.
        # This used to be a duplicated isVisible() ladder, which meant a panel
        # mid-CLOSE (still isVisible() for its whole ~300ms slide) was treated as
        # open: the right-click went to that panel's close flow, which early-returns
        # while its own animation runs, and the click vanished instead of falling
        # through to the sidebar. Reported live as "close the panel, right click gets
        # swallowed". active_full_panel now excludes a closing panel — see
        # _is_closing — so this chain must not be re-inlined.
        panel = self.active_full_panel()
        # DISPATCH PROBE (2026-07-28) at WARNING — pairs with [RCLICK] in app.py.
        # An [RCLICK] with no [RCLICK-BRANCH] means the press never reached here;
        # a branch that changes nothing visible means it was swallowed downstream.
        # `closing` is the field that matters for the "close the panel, right click
        # gets swallowed" report: a panel mid-slide must NOT be dispatched to.
        logger.warning(
            f"[RCLICK-BRANCH] panel={panel!r} "
            f"closing={[k for k, _ in self._CLOSE_ANIMS if self._is_closing(k)]} "
            f"sidebar_expanded={self.sidebar_expanded}"
        )
        if panel == "library":
            logger.debug(f"t={time.perf_counter():.6f} [handle_drag_area_right_click] branch=close_library")
            self._close_library_flow()
        elif panel == "settings":
            logger.debug(f"t={time.perf_counter():.6f} [handle_drag_area_right_click] branch=close_settings")
            self._close_settings_flow()
        elif panel == "speed":
            logger.debug(f"t={time.perf_counter():.6f} [handle_drag_area_right_click] branch=close_speed")
            self._close_speed_flow()
        elif panel == "sleep":
            logger.debug(f"t={time.perf_counter():.6f} [handle_drag_area_right_click] branch=close_sleep")
            self._close_sleep_flow()
        elif panel == "sprint":
            logger.debug(f"t={time.perf_counter():.6f} [handle_drag_area_right_click] branch=close_sprint")
            self._close_sprint_flow()
        elif panel == "stats":
            logger.debug(f"t={time.perf_counter():.6f} [handle_drag_area_right_click] branch=close_stats")
            self._close_stats_flow()
        elif panel == "tags":
            logger.debug(f"t={time.perf_counter():.6f} [handle_drag_area_right_click] branch=close_tags")
            self._close_tags_flow()
        elif panel == "book_detail":
            logger.debug(f"t={time.perf_counter():.6f} [handle_drag_area_right_click] branch=close_book_detail")
            self._close_book_detail_flow()
        elif panel == "chapter_list":
            logger.debug(f"t={time.perf_counter():.6f} [handle_drag_area_right_click] branch=chapter_list_fade_out")
            self.main_window.chapter_list_widget.fade_out()
        else:
            logger.debug(f"t={time.perf_counter():.6f} [handle_drag_area_right_click] branch=toggle_sidebar (no panel visible)")
            _pre = self.sidebar_expanded
            self._toggle_sidebar()
            if not _pre and self.sidebar_expanded:
                # Opened (was closed, now open) — record the method for the hover-out
                # dismiss check. _toggle_sidebar's closing branch clears this on dismiss.
                self._sidebar_opened_via = "right_click"
            logger.warning(
                f"[RCLICK-BRANCH] -> toggle_sidebar {_pre} -> {self.sidebar_expanded}"
                f"{'  <-- NO CHANGE' if _pre == self.sidebar_expanded else ''}"
            )

    def resize_panels(self):
        """Adjusts panel positions and sizes on window resize."""
        sidebar_y = 56 # 32 title + 24 progress for most panels
        library_y = 32 # 32 title for Library panel
        window_w = self.main_window.width()
        panel_w = int(self.main_window.width() * 0.9)
        
        # Hardcoded heights as requested
        self.sidebar.setFixedHeight(200)
        self.library_panel.setFixedWidth(window_w)
        self.library_panel.setFixedHeight(self.main_window.height() - library_y)

        for panel in [self.settings_panel, self.speed_panel, self.sleep_panel, self.sprint_panel,
                      self.stats_panel, self.tags_panel]:
            panel.setFixedWidth(panel_w)

        self.settings_panel.setFixedHeight(500)
        self.speed_panel.setFixedHeight(500)
        self.sleep_panel.setFixedHeight(500)
        self.sprint_panel.setFixedHeight(500)
        self.stats_panel.setFixedHeight(500)
        self.tags_panel.setFixedHeight(500)

        # Update Speed Panel position if not animating
        if self.speed_panel_animation.state() != QAbstractAnimation.State.Running:
            x = 0 if self.speed_panel.isVisible() else -panel_w
            self.speed_panel.move(x, sidebar_y)

        # Ensure sidebar position is maintained during resize
        sidebar_x = 0 if self.sidebar_expanded else -self.sidebar.width()
        self.sidebar.move(sidebar_x, sidebar_y)
            
        # Update Library Panel position if not animating
        if self.library_panel_animation.state() != QAbstractAnimation.State.Running:
            x = 0 if self.library_panel.isVisible() else -window_w
            self.library_panel.move(x, library_y)
            
        # Update Settings Panel position if not animating
        if self.settings_panel_animation.state() != QAbstractAnimation.State.Running:
            x = 0 if self.settings_panel.isVisible() else -panel_w
            self.settings_panel.move(x, sidebar_y)

        # Update Sleep Panel position if not animating
        if self.sleep_panel_animation.state() != QAbstractAnimation.State.Running:
            x = 0 if self.sleep_panel.isVisible() else -panel_w
            self.sleep_panel.move(x, sidebar_y)

        # Update Sprint Panel position if not animating
        if self.sprint_panel_animation.state() != QAbstractAnimation.State.Running:
            x = 0 if self.sprint_panel.isVisible() else -panel_w
            self.sprint_panel.move(x, sidebar_y)

        # Update Stats Panel position if not animating
        if self.stats_panel_animation.state() != QAbstractAnimation.State.Running:
            x = 0 if self.stats_panel.isVisible() else -panel_w
            self.stats_panel.move(x, sidebar_y)

        # Update Tags Panel position if not animating
        if self.tags_panel_animation.state() != QAbstractAnimation.State.Running:
            x = 0 if self.tags_panel.isVisible() else -panel_w
            self.tags_panel.move(x, sidebar_y)

        # Update Book Detail Panel position if not animating
        if self.book_detail_panel and self.book_detail_panel_animation and \
                self.book_detail_panel_animation.state() != QAbstractAnimation.State.Running:
            if self.book_detail_panel.isVisible():
                self.book_detail_panel.setFixedWidth(self.main_window.width())
                self.book_detail_panel.move(0, 32)
            self.book_detail_panel.setFixedHeight(self.main_window.height() - 32)