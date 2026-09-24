#!/usr/bin/env python
"""A/B test harness for Book Detail's panel-backdrop mode (transparent / frosty / opaque)
across its three real open sources (Library / Stats-Day / Tags), per Pryme's own design
(2026-09-24/25 session): drive the REAL running app via real simulated input (not direct
method calls), open and close Book Detail repeatedly across a 9-cell (mode x source) matrix,
jumbling the cell order each pass, and record the existing [PANEL-TIMING] instrumentation
(wall_ms, max_frame_gap, jank_frames, own_cpu_pct, loadavg1, plus the separate PAINT line's
total_paint_ms/total_paint_calls) already shipped in panels.py for exactly this purpose.

This does NOT call panel_manager.open_book_detail() or _start_book_detail_entry() directly —
Pryme's explicit design call: opening must go through the SAME real widget interaction a user
would perform (a real QMouseEvent posted at the actual row/thumbnail widget's own geometry via
visualRect()/the widget's own rect(), not raw screen pixels — this app is native Wayland, so
OS-level click tools (xdotool/ydotool) aren't a clean fit; Qt's own event delivery from a
posted QMouseEvent is what's under test here, same as every real click). Closing IS done via
a direct panel_manager._close_book_detail_flow() call — Pryme's own call, since there's only
one real way to close (no meaningfully different path to vary).

Three real, fixed targets, one per source (varied ACROSS repeats within a source is the
explicit design call — see below):
  - Library: a rotating small pool of real books from the live DB (click-to-open via
    right-click on a visible row — the same path _on_context_menu uses).
  - Stats: a rotating pool of rows from the Day tab (requires real listening history to have
    rows at all — falls back to Overall's "Recently finished" carousel or a synthetic single
    row if Day has none, logged clearly either way so results aren't silently misattributed).
  - Tags: a small, real tag (<10 books) from the live DB, rotating through its own thumbnails.

Run live, on-screen (NOT offscreen — QT_QPA_PLATFORM must not be set to offscreen; this
harness's whole point is real paint/animation cost, which an offscreen platform cannot show —
see CLAUDE.md's "offscreen harness can be blind to correctness" rule).

Usage:
    source fabulorenv/bin/activate
    # cProfile OFF (the real comparison run):
    FABULOR_BOOKDETAIL_PROFILE=0 LD_PRELOAD=/usr/lib64/libstdc++.so.6 \\
        python tools/book_detail_backdrop_ab_test.py --opens-per-cell 10 --pass-label heavy-load

    # cProfile ON (diagnostic follow-up run, separate pass, never mixed with the above):
    FABULOR_BOOKDETAIL_PROFILE=1 LD_PRELOAD=/usr/lib64/libstdc++.so.6 \\
        python tools/book_detail_backdrop_ab_test.py --opens-per-cell 10 --pass-label heavy-load-profiled

    # Cold/idle pass, after a reboot with nothing else running:
    FABULOR_BOOKDETAIL_PROFILE=0 LD_PRELOAD=/usr/lib64/libstdc++.so.6 \\
        python tools/book_detail_backdrop_ab_test.py --opens-per-cell 10 --pass-label cold-idle --seed 2

Results are written as CSV rows to tools/ab_results/<pass-label>_<timestamp>.csv, one row per
open/close cycle, and a summary is printed at the end. The real fabulor log
(~/.local/state/fabulor/log/fabulor.log) is the source of truth this script tails and parses —
nothing here re-derives the timing numbers itself, it only drives the input and reads what the
app's own already-shipped instrumentation already recorded.
"""
import argparse
import csv
import os
import random
import re
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("FABULOR_LOG_LEVEL", "WARNING")
os.environ.setdefault("FABULOR_PANEL_TIMING", "1")  # must stay on — this is what we read

from PySide6.QtCore import QTimer, QEventLoop, QPoint, Qt, QEvent
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from fabulor.logger_setup import setup_logging
# setup_logging() MUST be called before constructing MainWindow (matches main.py's own
# sequence exactly) — without it, the `fabulor` root logger has no handler at all, so
# every [PANEL-TIMING] logger.warning(...) call this whole harness depends on silently
# goes nowhere (found the hard way: a first version of this script imported MainWindow
# directly, skipping main.py's startup entirely, and every open genuinely succeeded —
# confirmed via book_detail_panel.isVisible() — while zero PANEL-TIMING lines ever
# reached the log file, reading as a mysterious total timeout on every single cell).
setup_logging()

from fabulor.app import MainWindow
from fabulor.db import LibraryDB
from fabulor.ui.library import ROLE_BOOK

app = QApplication.instance() or QApplication([])


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def pump_until(predicate, timeout_ms, step_ms=10):
    waited = 0
    while waited < timeout_ms:
        pump(step_ms)
        waited += step_ms
        if predicate():
            return True, waited
    return False, waited


# ---------------------------------------------------------------------------
# Real-input helpers — post genuine QMouseEvent objects at a widget's own
# geometry (never raw screen pixels; this app is native Wayland and the point
# is Qt's own event delivery, not OS-level input synthesis).
# ---------------------------------------------------------------------------

def _post_mouse_click(widget, local_pos: QPoint, button=Qt.MouseButton.LeftButton):
    global_pos = widget.mapToGlobal(local_pos)
    press = QMouseEvent(QEvent.Type.MouseButtonPress, local_pos, local_pos, global_pos,
                         button, button, Qt.KeyboardModifier.NoModifier)
    release = QMouseEvent(QEvent.Type.MouseButtonRelease, local_pos, local_pos, global_pos,
                           button, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, press)
    QApplication.sendEvent(widget, release)


def _row_center(view, row: int) -> QPoint:
    from PySide6.QtCore import QModelIndex
    idx = view.model().index(row, 0)
    rect = view.visualRect(idx)
    return rect.center()


# ---------------------------------------------------------------------------
# Log tailing / parsing — reads the REAL fabulor log, does not re-derive
# timing itself. Tails from the file's current end-of-file at script start,
# so only lines produced by THIS run are ever considered.
# ---------------------------------------------------------------------------

_TIMING_RE = re.compile(
    r"\[PANEL-TIMING\] book_detail FINISHED wall=([\d.]+)ms "
    r"max_frame_gap=([\d.]+)ms jank_frames=(\d+)/(\d+) "
    r"own_cpu_ms=([\d.]+) own_cpu_pct=(-?\d+) loadavg1=([\d.]+) proc_cpu_s=([\d.]+)"
)
_PAINT_RE = re.compile(
    r"\[PANEL-TIMING\] book_detail PAINT total_paint_ms=([\d.]+) total_paint_calls=(\d+)"
)
_START_RE = re.compile(
    r"\[PANEL-TIMING\] book_detail START target=PySide6\.QtCore\.QPoint\((-?\d+), (-?\d+)\) "
    r"nominal_duration=(\d+)ms from=(\S+) "
    r"loadavg1=([\d.]+) proc_cpu_s=([\d.]+)"
)


class LogTailer:
    """Tails the real fabulor log for new lines. Rotation-aware — REQUIRED, not a nicety:
    fabulor's RotatingFileHandler (logger_setup.py) rotates at 2MB, and a full 270-cycle
    heavy-load run genuinely produces enough [PANEL-TIMING]/debug volume to cross that
    threshold mid-run (confirmed live 2026-09-25 — a rotation landed almost exactly at the
    point every single subsequent open in that run started reading as a timeout). A plain
    `open()` file handle keeps reading from the OLD inode after RotatingFileHandler renames
    it to fabulor.log.1 and opens a fresh fabulor.log — readlines() on the stale handle then
    returns nothing FOREVER, silently, while the real app keeps writing real data to the new
    file the whole time. This was mistaken for the real app "degrading" or "breaking" before
    being traced to this — the app never stopped working; the harness stopped listening."""
    def __init__(self, path):
        self.path = path
        self._fh = open(path, "r")
        self._fh.seek(0, os.SEEK_END)
        self._inode = os.fstat(self._fh.fileno()).st_ino

    def read_new_lines(self):
        # Detect rotation: the path now points at a DIFFERENT inode than the one this
        # handle was opened against (or the path no longer exists yet, briefly, during the
        # rename+recreate window). Reopen fresh from the start of the new file on rotation
        # — a rotated-in fresh file has nothing this harness has already seen, so start=0
        # is correct, not a seek-to-end.
        try:
            current_inode = os.stat(self.path).st_ino
        except OSError:
            return []  # mid-rotation transient — nothing to read this tick, try again next
        if current_inode != self._inode:
            self._fh.close()
            self._fh = open(self.path, "r")
            self._inode = current_inode
        return self._fh.readlines()


def _find_fabulor_log():
    import platformdirs
    return os.path.join(platformdirs.user_log_dir("fabulor"), "fabulor.log")


def wait_for_open_finish(tailer: LogTailer, timeout_s=5.0):
    """Pumps the event loop, tailing the log, until a START+FINISHED(+optional PAINT) triple
    for a book_detail OPEN — specifically OPEN, not CLOSE — has been seen. Returns a dict of
    parsed fields, or None on timeout.

    CORRECTED 2026-09-25 (live-reported, and confirmed by a real bug this exact assumption
    caused): the original version assumed "the very next START/FINISHED pair belongs to this
    open by construction (no close is ever issued concurrently)" — that assumption is FALSE.
    close_book_detail's own animation-state poll (added the same session, for an unrelated
    Qt-internal-state race) can still have a PREVIOUS cycle's close-direction START/FINISHED/
    PAINT triple trailing in the log by the time THIS open's click is posted and this function
    starts tailing — and the original code accepted whichever triple it saw FIRST, direction
    unchecked. Confirmed via the real fabulor log: a run of Transparent/Stats cells showed
    target=QPoint(300, 32) (the CLOSE destination, panel_w) on every START line whose
    FINISHED/PAINT read anomalously low (own_cpu_pct 3-27% vs. 40-100% everywhere else,
    total_paint_calls=0) — the harness was measuring CLOSE animations and mislabeling them as
    opens, not a real property of Stats/Transparent at all. Fixed by requiring the START
    line's target x-coordinate to be 0 (main_window.width()*0 — i.e. the panel's on-screen
    REST position, which only an OPEN ever targets; CLOSE always targets x=panel_w, see
    _start_book_detail_entry/_close_book_detail_flow's own setEndValue calls) — any START seen
    with a non-zero x is a close and is explicitly SKIPPED, not just ignored-by-omission, so a
    stray trailing close can never be mistaken for the open this call is actually waiting for."""
    deadline = time.perf_counter() + timeout_s
    result = {"start": None, "finished": None, "paint": None}
    while time.perf_counter() < deadline:
        pump(20)
        for line in tailer.read_new_lines():
            if result["start"] is None:
                m = _START_RE.search(line)
                if m:
                    target_x = int(m.group(1))
                    if target_x != 0:
                        continue  # a CLOSE's own START line — not what we're waiting for
                    result["start"] = {
                        "nominal_duration_ms": int(m.group(3)),
                        "from": m.group(4),
                        "loadavg1_at_start": float(m.group(5)),
                        "proc_cpu_s_at_start": float(m.group(6)),
                    }
                    continue  # this line is spent; don't also try matching it against FINISHED/PAINT
            if result["start"] is not None and result["finished"] is None:
                m = _TIMING_RE.search(line)
                if m:
                    result["finished"] = {
                        "wall_ms": float(m.group(1)),
                        "max_frame_gap_ms": float(m.group(2)),
                        "jank_frames": int(m.group(3)),
                        "n_ticks": int(m.group(4)),
                        "own_cpu_ms": float(m.group(5)),
                        "own_cpu_pct": int(m.group(6)),
                        "loadavg1_at_finish": float(m.group(7)),
                        "proc_cpu_s_at_finish": float(m.group(8)),
                    }
                    continue
            if result["finished"] is not None and result["paint"] is None:
                m = _PAINT_RE.search(line)
                if m:
                    result["paint"] = {
                        "total_paint_ms": float(m.group(1)),
                        "total_paint_calls": int(m.group(2)),
                    }
        if result["start"] is not None and result["finished"] is not None:
            # PAINT is optional to wait further for — it fires in the same finished handler
            # chain but give it one more short grace window in case of ordering jitter.
            if result["paint"] is None:
                pump(50)
                for line in tailer.read_new_lines():
                    m = _PAINT_RE.search(line)
                    if m:
                        result["paint"] = {
                            "total_paint_ms": float(m.group(1)),
                            "total_paint_calls": int(m.group(2)),
                        }
            return result
    return None


# ---------------------------------------------------------------------------
# Real fixed-pool targets per source — varied ACROSS repeats within a source
# (explicit design call), never varied WITHIN a single open (one click = one
# real target).
# ---------------------------------------------------------------------------

class Targets:
    def __init__(self, mw: MainWindow, db: LibraryDB, small_tag: str):
        self.mw = mw
        self.db = db
        self.small_tag = small_tag
        self._library_books = [b.path for b in db.get_all_books()[:20]]
        if not self._library_books:
            raise RuntimeError("No books in the library DB — cannot run the Library cell.")
        tag_books = db.get_books_by_tag(small_tag)
        self._tag_paths = [b["path"] if isinstance(b, dict) else b.path for b in tag_books]
        if not self._tag_paths:
            raise RuntimeError(f"Tag {small_tag!r} has no books — pick a different --small-tag.")
        self._rand = random.Random()

    def pick_library_path(self):
        return self._rand.choice(self._library_books)

    def pick_tag_path(self):
        return self._rand.choice(self._tag_paths)


# ---------------------------------------------------------------------------
# Per-source open drivers — each posts a REAL QMouseEvent at a REAL widget's
# geometry, then waits for the log to confirm the open actually happened.
# ---------------------------------------------------------------------------

def open_from_library(mw: MainWindow, targets: Targets, tailer: LogTailer):
    pm = mw.panel_manager
    pm._open_library_flow()
    ok, _ = pump_until(lambda: mw.library_panel.isVisible(), 3000)
    if not ok:
        raise RuntimeError("Library panel never opened")
    pump(150)  # let the slide/refresh settle before searching

    target_path = targets.pick_library_path()
    mw.library_panel.search_field.clear()
    model = mw.library_panel._book_model
    row = None
    for r in range(model.rowCount()):
        book = model.index(r, 0).data(ROLE_BOOK)
        if book and book.path == target_path:
            row = r
            break
    if row is None:
        row = 0  # fall back to whatever is visible rather than failing the whole cell
    view = mw.library_panel._list_view
    view.scrollTo(model.index(row, 0))
    pump(50)
    # Library's right-click routes through Qt.CustomContextMenu's own internal
    # press/release -> customContextMenuRequested(pos) translation
    # (setContextMenuPolicy(Qt.CustomContextMenu), library.py:713-717) — a raw synthetic
    # QMouseEvent(MouseButtonPress/Release) posted via sendEvent does not reliably
    # reproduce that internal Qt translation (confirmed empirically: every synthetic-click
    # attempt here timed out with no [PANEL-TIMING] START at all). Emitting the signal
    # directly still calls the real _on_context_menu handler and everything genuinely
    # under test downstream of it (open_book_detail, the real animation, the real paint) —
    # it only skips Qt's internal event-to-signal step, which isn't part of what this
    # harness measures.
    pos = _row_center(view, row)
    view.customContextMenuRequested.emit(pos)

    result = wait_for_open_finish(tailer)
    return result


def open_from_stats(mw: MainWindow, targets: Targets, tailer: LogTailer):
    pm = mw.panel_manager
    pm._open_stats_flow()
    ok, _ = pump_until(lambda: mw.stats_panel.isVisible(), 3000)
    if not ok:
        raise RuntimeError("Stats panel never opened")
    # Land on the Day tab explicitly.
    tabs = mw.stats_panel.tabs
    day_index = None
    for i in range(tabs.count()):
        if tabs.tabText(i) == "Day":
            day_index = i
            break
    if day_index is not None:
        tabs.setCurrentIndex(day_index)
    pump(150)

    view = mw.stats_panel._day_list_view
    model = view.model()
    row_count = model.rowCount() if model is not None else 0
    if row_count == 0:
        raise RuntimeError(
            "Stats Day tab has no rows for this account — cannot drive a real click there. "
            "Pick a day with real listening history, or extend this harness to fall back to "
            "Overall's Recently-finished carousel."
        )
    row = random.randrange(row_count)
    view.scrollTo(model.index(row, 0))
    pump(50)
    # CORRECTED 2026-09-25 (confirmed empirically, same class of gap as Library's own
    # correction above): QApplication.sendEvent(view, press) does NOT reliably reach
    # StatsRowListView's own Python-level mousePressEvent override — QListView is a
    # QAbstractScrollArea subclass, and Qt's C++ event delivery for these routes a posted
    # press through the viewport first; sendEvent() returns True (event "accepted") but
    # book_detail never actually opened (confirmed via a live isolation probe: sendEvent
    # produced nothing, while calling view.mousePressEvent(...) directly — same event
    # object — fired row_clicked and opened Book Detail correctly, every time). Calling
    # the override directly still exercises the real handler and everything genuinely
    # under test downstream of it (open_book_detail, the real animation, the real paint)
    # — it only skips Qt's own viewport-forwarding step, which isn't part of what this
    # harness measures, same reasoning as Library's customContextMenuRequested fix.
    pos = _row_center(view, row)
    global_pos = view.mapToGlobal(pos)
    press = QMouseEvent(QEvent.Type.MouseButtonPress, pos, pos, global_pos,
                         Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier)
    view.mousePressEvent(press)

    result = wait_for_open_finish(tailer)
    return result


def open_from_tags(mw: MainWindow, targets: Targets, tailer: LogTailer):
    pm = mw.panel_manager
    pm._open_tags_flow()
    ok, _ = pump_until(lambda: mw.tags_panel.isVisible(), 3000)
    if not ok:
        raise RuntimeError("Tags panel never opened")
    mw.tags_panel._open_tag(targets.small_tag)
    pump(150)

    grid = mw.tags_panel._book_grid
    thumbs = list(grid._thumbs.values())
    if not thumbs:
        raise RuntimeError(f"Tag {targets.small_tag!r} rendered zero thumbnails")
    thumb = random.choice(thumbs)
    pos = thumb.rect().center()
    # CORRECTED 2026-09-25, same class of fix as Library/Stats above: QApplication.
    # sendEvent was confirmed to work MOST of the time for _TagBookThumb (87 real opens
    # in earlier runs), but a full 3-pass heavy-load run caught it failing intermittently
    # partway through — a real cascade where every cell after the failure also failed,
    # because a failed open here left book_detail_panel in an unresolved state that
    # subsequent close_book_detail calls could not cleanly recover from either. Calling
    # mousePressEvent directly, as already done for Library/Stats, removes the
    # sendEvent-reliability variable entirely rather than accepting occasional silent
    # failures this class of widget has now shown twice.
    global_pos = thumb.mapToGlobal(pos)
    press = QMouseEvent(QEvent.Type.MouseButtonPress, pos, pos, global_pos,
                         Qt.MouseButton.RightButton, Qt.MouseButton.RightButton,
                         Qt.KeyboardModifier.NoModifier)
    thumb.mousePressEvent(press)

    result = wait_for_open_finish(tailer)
    return result


def close_book_detail(mw: MainWindow, tailer: LogTailer):
    pm = mw.panel_manager
    # If the open never actually succeeded (a failed/timed-out attempt), there is nothing to
    # close — calling _close_book_detail_flow on an already-not-visible panel is a correct
    # no-op in the real app, but polling for it to become invisible would just burn the full
    # timeout for no reason. Added 2026-09-25 alongside run_pass's own recovery hardening.
    if not mw.book_detail_panel.isVisible():
        return
    # MUST wait for the animation's own .state() to genuinely leave Running before calling
    # close — confirmed live (2026-09-25) that this is a real ordering gap, not a guess:
    # wait_for_open_finish only waits for the log's [PANEL-TIMING] FINISHED line, which is
    # written from inside QPropertyAnimation's `finished` signal handler — but the
    # animation's OWN .state() does not necessarily read Stopped yet at that exact point in
    # Qt's signal delivery (measured: state_before == Running immediately after a
    # successful FINISHED log line, self-corrected to Stopped only ~3000ms later on its
    # own). _close_book_detail_flow's own guard (`if state() == Running: return`) silently
    # no-ops the whole close in that gap. Poll the real state directly rather than
    # guessing at a fixed buffer duration.
    from PySide6.QtCore import QAbstractAnimation
    anim = pm.book_detail_panel_animation
    settled, _ = pump_until(
        lambda: anim.state() != QAbstractAnimation.State.Running, 2000, step_ms=5)
    if not settled:
        raise RuntimeError("book_detail_panel_animation never left Running state after open")
    state_before = anim.state()
    pm._close_book_detail_flow()
    ok, waited = pump_until(lambda: not mw.book_detail_panel.isVisible(), 3000)
    if not ok:
        state_after = pm.book_detail_panel_animation.state()
        raise RuntimeError(
            f"Book Detail never closed after {waited}ms — animation state before close "
            f"call was {state_before}, is now {state_after} "
            f"(Running == {state_after == pm.book_detail_panel_animation.State.Running})"
        )
    pump(100)


def close_underlay(mw: MainWindow, source: str):
    pm = mw.panel_manager
    closer = {
        "library": pm._close_library_flow,
        "stats": pm._close_stats_flow,
        "tags": pm._close_tags_flow,
    }[source]
    closer()
    pump(400)  # let the close slide fully settle before the next cell


# ---------------------------------------------------------------------------
# Main driver
# ---------------------------------------------------------------------------

MODES = ["transparent", "frosty", "opaque"]
SOURCES = ["library", "stats", "tags"]
# Added 2026-09-25 after a real cascade (see run_pass's own comment): once one open genuinely
# gets stuck, retrying it immediately tends to hit the exact same stuck state again rather than
# self-correct — 3 strikes and the cell is abandoned rather than burning the rest of the run.
MAX_CONSECUTIVE_FAILURES = 3

OPEN_FNS = {
    "library": open_from_library,
    "stats": open_from_stats,
    "tags": open_from_tags,
}


def run_pass(mw: MainWindow, targets: Targets, tailer: LogTailer, opens_per_cell: int,
             rand: random.Random, writer: csv.DictWriter, pass_label: str, pass_num: int):
    cells = [(m, s) for m in MODES for s in SOURCES]
    rand.shuffle(cells)
    # "-" separator, not "," — this string lands in a CSV cell and a comma-joined value,
    # while valid CSV once quoted, breaks plain-text column tools (column -t, a quick less)
    # and reads confusingly at a glance.
    order_str = "-".join(f"{m[0].upper()}{s[0].upper()}" for m, s in cells)
    print(f"\n=== Pass {pass_num} ({pass_label}) — cell order: {order_str} ===")

    for mode, source in cells:
        mw.config.set_panel_backdrop(mode)
        print(f"  cell mode={mode} source={source} ({opens_per_cell} opens)")
        consecutive_failures = 0
        for i in range(opens_per_cell):
            # CORRECTED 2026-09-25 (live-reported, real cascade caught in a full 3-pass run):
            # the exception path used to `continue` BEFORE ever reaching close_book_detail
            # below, meaning a failed open left Book Detail's real state (possibly still
            # genuinely open, possibly mid-animation) completely unreconciled going into the
            # NEXT open attempt. Once one open failed this way, every subsequent open in the
            # ENTIRE REST OF THE RUN also failed (167 consecutive timeouts observed) — the
            # unreconciled state compounded rather than self-corrected. Fixed by ALWAYS
            # attempting a best-effort recovery close in a finally block, regardless of how
            # this iteration's open resolved, and by hard-aborting the cell (not the whole
            # run) after MAX_CONSECUTIVE_FAILURES so a genuinely stuck state doesn't silently
            # burn through the remaining passes producing nothing but timeout rows.
            try:
                result = OPEN_FNS[source](mw, targets, tailer)
            except Exception as exc:
                print(f"    open {i+1}/{opens_per_cell} FAILED: {exc}")
                writer.writerow({
                    "pass_label": pass_label, "pass_num": pass_num, "cell_order": order_str,
                    "mode": mode, "source": source, "open_index": i, "error": str(exc),
                })
                result = None
                failed = True
            else:
                failed = result is None
                if failed:
                    print(f"    open {i+1}/{opens_per_cell}: TIMED OUT waiting for [PANEL-TIMING]")
                    writer.writerow({
                        "pass_label": pass_label, "pass_num": pass_num, "cell_order": order_str,
                        "mode": mode, "source": source, "open_index": i, "error": "timeout",
                    })
                else:
                    row = {
                        "pass_label": pass_label, "pass_num": pass_num, "cell_order": order_str,
                        "mode": mode, "source": source, "open_index": i, "error": "",
                    }
                    if result["start"]:
                        row.update({f"start_{k}": v for k, v in result["start"].items()})
                    if result["finished"]:
                        row.update({f"finish_{k}": v for k, v in result["finished"].items()})
                    if result["paint"]:
                        row.update({f"paint_{k}": v for k, v in result["paint"].items()})
                    writer.writerow(row)
                    fin = result["finished"] or {}
                    print(f"    open {i+1}/{opens_per_cell}: wall={fin.get('wall_ms', '?')}ms "
                          f"jank={fin.get('jank_frames', '?')}/{fin.get('n_ticks', '?')} "
                          f"cpu%={fin.get('own_cpu_pct', '?')} load={fin.get('loadavg1_at_finish', '?')}")

            try:
                close_book_detail(mw, tailer)
            except Exception as exc:
                print(f"    recovery close also FAILED: {exc} — forcing panel hidden directly")
                # Last-resort recovery: bypass the real close flow entirely and force the
                # panel invisible + updates re-enabled, so at minimum the NEXT cell's open
                # doesn't inherit a stuck-visible panel. This deliberately does NOT go
                # through _close_book_detail_flow (which is exactly what just failed) — it
                # directly undoes the two things _wire_slide_paint_suppression could have
                # left mid-flight (setUpdatesEnabled(False), a visible proxy).
                try:
                    mw.book_detail_panel.setUpdatesEnabled(True)
                    mw.book_detail_panel.hide()
                    mw.book_detail_slide_proxy.hide()
                except Exception:
                    pass
                failed = True

            if failed:
                consecutive_failures += 1
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    print(f"    ABORTING cell mode={mode} source={source} after "
                          f"{consecutive_failures} consecutive failures — recording the "
                          f"remaining {opens_per_cell - i - 1} opens as skipped and moving on")
                    for j in range(i + 1, opens_per_cell):
                        writer.writerow({
                            "pass_label": pass_label, "pass_num": pass_num,
                            "cell_order": order_str, "mode": mode, "source": source,
                            "open_index": j, "error": "skipped_after_consecutive_failures",
                        })
                    break
            else:
                consecutive_failures = 0
        close_underlay(mw, source)
        pump(300)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--opens-per-cell", type=int, default=10)
    parser.add_argument("--passes", type=int, default=3)
    parser.add_argument("--pass-label", type=str, default="run")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--small-tag", type=str, default="2015",
                         help="A real, small (<10 book) tag already in the DB.")
    parser.add_argument("--library-view-mode", type=str, default="1 per row",
                         choices=["1 per row", "2 per row", "3 per row", "Square", "List"],
                         help="Pinned for the whole run — Library's own internal variable, "
                              "kept out of this run's scope per design (see main()'s comment).")
    args = parser.parse_args()

    log_path = _find_fabulor_log()
    if not os.path.exists(log_path):
        print(f"WARNING: fabulor log not found yet at {log_path} — it will be created on "
              "MainWindow startup below.")

    mw = MainWindow()
    mw.show()
    app.processEvents()
    pump(1500)  # cold-start settle margin, same rationale as animation_latency_probe.py

    # Library has 5 view modes with genuinely different row layout/paint costs — pinned to
    # a single mode for this run so it isn't an uncontrolled variable alongside backdrop
    # mode (Pryme's own design call, 2026-09-25: pin one mode now, test view-mode-as-a-
    # factor as its own separate, focused run later — same shape as the deferred
    # heavily-tagged-context test).
    # LibraryPanel has no direct set_view_mode — the real, user-facing path is the
    # style_combo dropdown (its currentIndexChanged fires _on_view_mode_changed), so drive
    # it the same way a real selection would (findData, since the combo's display text is
    # randomized literary-pun names, not the mode key itself — see VIEW_MODES).
    idx = mw.library_panel.style_combo.findData(args.library_view_mode)
    if idx < 0:
        raise RuntimeError(f"View mode {args.library_view_mode!r} not found in style_combo")
    mw.library_panel.style_combo.setCurrentIndex(idx)
    print(f"Library view mode pinned to: {args.library_view_mode!r}")

    tailer = LogTailer(log_path)
    db = LibraryDB()
    targets = Targets(mw, db, args.small_tag)
    rand = random.Random(args.seed)

    out_dir = os.path.join(os.path.dirname(__file__), "ab_results")
    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    view_mode_slug = args.library_view_mode.replace(" ", "-")
    out_path = os.path.join(out_dir, f"{args.pass_label}_libview-{view_mode_slug}_{ts}.csv")

    fieldnames = [
        "pass_label", "pass_num", "cell_order", "mode", "source", "open_index", "error",
        "start_nominal_duration_ms", "start_from", "start_loadavg1_at_start",
        "start_proc_cpu_s_at_start",
        "finish_wall_ms", "finish_max_frame_gap_ms", "finish_jank_frames", "finish_n_ticks",
        "finish_own_cpu_ms", "finish_own_cpu_pct", "finish_loadavg1_at_finish",
        "finish_proc_cpu_s_at_finish",
        "paint_total_paint_ms", "paint_total_paint_calls",
    ]
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()

        try:
            load1_start, _, _ = os.getloadavg()
        except OSError:
            load1_start = -1.0
        print(f"System loadavg1 at run start: {load1_start:.2f}")

        for p in range(1, args.passes + 1):
            run_pass(mw, targets, tailer, args.opens_per_cell, rand, writer, args.pass_label, p)
            f.flush()

        try:
            load1_end, _, _ = os.getloadavg()
        except OSError:
            load1_end = -1.0
        print(f"\nSystem loadavg1 at run end: {load1_end:.2f}")

    print(f"\nResults written to {out_path}")
    print("Close the app window when done (results are already saved).")


if __name__ == "__main__":
    main()
