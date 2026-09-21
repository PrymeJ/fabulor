"""Randomized adversarial-ordering fuzz tests for the EOF-restore invariants.

Context: TODO_ARCHIVE.md's "Resuming an M4B after unfinishing it freezes the
app" entry documents TEN fixes found one at a time, each via a live repro,
across a single sustained investigation (2026-09-21). Every one of those bugs
was a race or ordering assumption between:
  - `current_file` (plain string, updated synchronously)
  - `Player._eof` (plain bool, now pre-armed synchronously in `load_book`,
    but ALSO written from `_on_time_pos_change`, which runs on mpv's own
    background event-loop thread — see `Player._on_time_pos_change`'s own
    extensive comments)
  - `Player._logical_pos` / `_last_raw_global` (raw-sample-driven state)
  - `Player._last_nonvt_chapter` / `_last_vt_chapter` (chapter-walk state)

Live reproduction found these one at a time because each one required a
SPECIFIC interleaving of book switches, seeks, and raw mpv samples to
surface. Rather than trust that live testing exhausted the interleaving
space, this file drives the real `Player` class through randomized
SEQUENCES of the operations available at this layer (load a book at/near
EOF, load a book mid-book, feed a raw time_pos sample, issue a real seek)
in randomized order, and asserts a set of INVARIANTS that must hold after
every single step, not just at the end of a scripted scenario.

Uses Python's stdlib `random` with a FIXED seed (not `hypothesis`, which
isn't installed in this venv) — deterministic and reproducible across runs,
new failures always reproduce with the same seed/step index printed on
failure.
"""
import random
import types

import pytest

from fabulor.player import Player


# --------------------------------------------------------------------------- #
# a lightweight in-memory fake DB — models exactly the two Book fields the
# EOF-restore synthesis path reads (duration, progress), keyed by path.
# --------------------------------------------------------------------------- #
class _Book:
    def __init__(self, path, duration, progress):
        self.path = path
        self.duration = duration
        self.progress = progress


class _FakeDb:
    def __init__(self, books):
        self._books = {b.path: b for b in books}

    def get_book(self, path):
        return self._books.get(path)


class _FakeMpv:
    """Records every command/play call; never actually loads anything.

    chapter_list is non-empty and non-trivial by design — mpv reports its
    OWN live chapter list as soon as a file loads, independent of and
    often BEFORE Fabulor's own `cache_chapter_list()` snapshot runs (see
    `Player.chapter_list`'s property fallback to `instance.chapter_list`
    when `_chapter_list is None`). An empty fake chapter list would make
    the walk-and-emit block's `elif self.chapter_list and value is not
    None:` condition always False regardless of any `_eof` guard,
    silently hiding bug #7's entire failure mode — found the hard way
    while verifying this harness actually catches a reintroduced fix #7
    regression (it didn't, until this was fixed)."""
    def __init__(self):
        self.commands = []
        self.play_calls = []
        self.chapter_list = [
            {"title": "Chapter 1", "time": 0.0},
            {"title": "Chapter 2", "time": 600.0},
            {"title": "Chapter 3", "time": 1200.0},
            {"title": "Chapter 4", "time": 1800.0},
        ]

    def command_async(self, *args):
        self.commands.append(args)

    def play(self, path):
        self.play_calls.append(path)


BOOK_A_M4B = _Book("book_a.m4b", duration=3600.0, progress=3600.0)   # at EOF
BOOK_B_M4B = _Book("book_b.m4b", duration=1800.0, progress=900.0)    # mid-book
BOOK_C_M4B = _Book("book_c.m4b", duration=2400.0, progress=2399.5)   # within 2s of EOF
BOOKS = [BOOK_A_M4B, BOOK_B_M4B, BOOK_C_M4B]


def _new_player():
    p = Player(db=_FakeDb(BOOKS), config=None)
    p.instance = _FakeMpv()
    return p


# --------------------------------------------------------------------------- #
# Invariant checks — each must hold after EVERY operation in a fuzz sequence,
# not just at scenario boundaries.
# --------------------------------------------------------------------------- #
def _assert_invariants(p: Player, step_desc: str):
    # INVARIANT 1: is_seeking and _seek_target must never diverge — either
    # both represent "a seek is in flight" or neither does. A stranded
    # is_seeking=True with _seek_target=None is exactly bug #1's shape.
    if p.is_seeking:
        assert p._seek_target is not None or p._is_vt_file_switch, (
            f"STRANDED is_seeking: is_seeking=True but _seek_target=None "
            f"and not mid VT-file-switch, after: {step_desc}"
        )

    # INVARIANT 2: while _eof is True and no seek is in flight, _logical_pos
    # must never be a small/near-zero value when it was set to a large
    # duration — this is bug #5's shape (logical_pos silently dragged to
    # ~0 by a raw mpv sample). We can't know the "correct" duration in
    # general, but we CAN assert: _logical_pos never DECREASES while _eof
    # is True and is_seeking is False (nothing should be moving position
    # backward while the book is understood to be finished and no seek is
    # active).
    # (checked by the caller via before/after snapshots, not here)

    # INVARIANT 3: chapter_changed must never fire while _eof is True —
    # bug #7's shape. Checked via a signal-recording connection in the
    # fuzz loop itself, not here (can't inspect emitted signals from a
    # pure state snapshot).
    pass


class _EmitRecorder:
    """Records every chapter_changed emission with the _eof state at the
    moment of emission — lets the fuzz loop assert INVARIANT 3 exactly."""
    def __init__(self, player: Player):
        self.emissions_while_eof = []
        player.chapter_changed.connect(self._on_emit)
        self._player = player

    def _on_emit(self, idx):
        if self._player._eof:
            self.emissions_while_eof.append(idx)


# --------------------------------------------------------------------------- #
# The fuzz operations available at this layer, each a (name, fn) pair.
# fn(p, rng) performs one step and may read/write player state.
# --------------------------------------------------------------------------- #
def _reset_for_new_book(p: Player):
    """Mirrors load_book's own per-book state reset (player.py, the block
    right after _ensure_mpv/_is_seeking=True/_eof=False)."""
    p._is_seeking = True
    p._eof = False
    p._chapter_list = None
    p._is_embedded_m4b = False
    p._last_vt_chapter = -1
    p._last_nonvt_chapter = -1
    p._logical_pos = None
    p._last_raw_global = None
    p._just_settled = False
    p._post_settle_target = None
    p._post_settle_deadline = None
    p._seek_target = None
    p._cached_time_pos = None


def _op_load_book_at_eof(p: Player, rng: random.Random):
    """Simulates the COMPLETE synchronous sequence a real book switch
    performs at this layer for a book saved at/near its own EOF:
    load_book's pre-arm (fix #7's second half) followed by
    _restore_position's own resolution (app.py) — both run synchronously,
    back to back, on the Qt thread, with no real mpv activity possible in
    between (that's the whole point of the fix). Isolating just
    load_book's first few lines without _restore_position's resolution
    would flag a momentary, expected mid-sequence state as a false
    positive — is_seeking=True/_seek_target=None is only a BUG when it
    OUTLIVES this synchronous sequence, not while it's still completing."""
    book = rng.choice([BOOK_A_M4B, BOOK_C_M4B])
    _reset_for_new_book(p)
    # load_book's own pre-arm check:
    if book.duration and book.duration - book.progress < 2.0:
        p._eof = True
    # _restore_position's resolution (app.py), which ALWAYS runs
    # synchronously right after for this case — the near-EOF branch:
    if book.duration and book.duration - book.progress < 2.0:
        p._eof = True
        p.is_seeking = False
        p._logical_pos = book.progress
    else:
        # ordinary resume: _restore_position calls seek_async, which sets
        # is_seeking/_seek_target together (modeled by _op_real_seek_settle
        # normally, but here we mirror the same-call synchronicity)
        p.is_seeking = True
        p._seek_target = book.progress
        p._logical_pos = book.progress
    return f"load_book_at_eof({book.path})"


def _op_load_book_midbook(p: Player, rng: random.Random):
    """Same full synchronous sequence as _op_load_book_at_eof, for a book
    NOT near its own EOF — _restore_position's ordinary seek_async path."""
    _reset_for_new_book(p)
    p.is_seeking = True
    p._seek_target = BOOK_B_M4B.progress
    p._logical_pos = BOOK_B_M4B.progress
    return "load_book_midbook(book_b.m4b)"


def _op_raw_mpv_sample(p: Player, rng: random.Random):
    """Simulates mpv's own background-thread observer delivering a raw
    time_pos sample — the exact race vector for bugs #5 and #7. A fresh
    load's first sample is always near 0, regardless of Fabulor state."""
    value = rng.choice([0.0, 0.01, 0.5, rng.uniform(0, 5)])
    p._on_time_pos_change("time-pos", value)
    return f"raw_mpv_sample({value:.3f})"


def _op_real_seek_settle(p: Player, rng: random.Random):
    """Simulates a real seek_async call landing and settling — this is the
    ONLY path that should legitimately clear _eof and resume normal
    chapter-walk/logical-pos tracking."""
    target = rng.uniform(0, 3000)
    p._eof = False
    p._is_seeking = True
    p._seek_target = target
    p._logical_pos = target
    # settle sample: value must be within 1.0 of target for the settle
    # branch to fire (mirrors seek_async's non-VT command + the resulting
    # observer callback)
    p._on_time_pos_change("time-pos", target)
    return f"real_seek_settle({target:.3f})"


def _op_natural_eof_completion(p: Player, rng: random.Random):
    """Simulates _advance_or_finish's non-VT branch — genuine natural EOF
    reached via real playback, NOT restore-time synthesis."""
    p._virtual_timeline = None
    p._advance_or_finish()
    return "natural_eof_completion()"


_OPS = [
    _op_load_book_at_eof,
    _op_load_book_midbook,
    _op_raw_mpv_sample,
    _op_real_seek_settle,
    _op_natural_eof_completion,
]


@pytest.mark.parametrize("seed", range(20))
def test_eof_invariants_hold_under_randomized_operation_sequences(seed):
    """Runs 40 randomized operations per seed, asserting invariants after
    every single step. 20 seeds x 40 steps = 800 total invariant checks
    across many different adversarial orderings — deterministic per seed,
    so any failure reproduces exactly by re-running with that seed."""
    rng = random.Random(seed)
    p = _new_player()
    recorder = _EmitRecorder(p)

    history = []
    for step_num in range(40):
        op = rng.choice(_OPS)
        logical_pos_before = p._logical_pos
        eof_before = p._eof
        is_seeking_before = p._is_seeking

        desc = op(p, rng)
        history.append(f"step {step_num}: {desc}")

        _assert_invariants(p, "\n".join(history))

        # INVARIANT 2 (checked here, needs before/after): _logical_pos must
        # never silently regress toward 0 while _eof was True BEFORE this
        # step, is_seeking was False, and this step wasn't a legitimate
        # seek/completion operation. Only _op_raw_mpv_sample can violate
        # this illegitimately — the other ops are the legitimate ways
        # _logical_pos is allowed to change.
        if (eof_before and not is_seeking_before and logical_pos_before is not None
                and op is _op_raw_mpv_sample):
            assert p._logical_pos == logical_pos_before, (
                f"_logical_pos silently changed from {logical_pos_before} to "
                f"{p._logical_pos} by a raw mpv sample while _eof was True and "
                f"no seek was in flight (bug #5's exact shape). History:\n"
                + "\n".join(history)
            )

    # INVARIANT 3, checked once at the end over the whole run: chapter_changed
    # must NEVER have fired while _eof was True (bug #7's exact shape).
    assert recorder.emissions_while_eof == [], (
        f"chapter_changed fired while _eof was True (bug #7's exact shape): "
        f"emissions={recorder.emissions_while_eof!r}. History:\n" + "\n".join(history)
    )


def test_eof_invariants_hold_for_every_op_pair_directly_adjacent():
    """Narrower than the full random fuzz above: exhaustively tries every
    ORDERED PAIR of operations back-to-back (25 pairs, since 5 ops), which
    is the minimal reproducer shape for a race that only needs two
    specific consecutive calls to trigger — matches how every one of the
    ten real bugs was actually found (a specific two-step sequence), not a
    long random walk."""
    for op_a in _OPS:
        for op_b in _OPS:
            p = _new_player()
            recorder = _EmitRecorder(p)
            rng = random.Random(0)

            logical_pos_after_a = None
            eof_after_a = None
            is_seeking_after_a = None

            desc_a = op_a(p, rng)
            logical_pos_after_a = p._logical_pos
            eof_after_a = p._eof
            is_seeking_after_a = p._is_seeking

            desc_b = op_b(p, rng)

            pair_desc = f"{desc_a} -> {desc_b}"

            if p.is_seeking:
                assert p._seek_target is not None or p._is_vt_file_switch, (
                    f"STRANDED is_seeking after pair: {pair_desc}"
                )

            if (eof_after_a and not is_seeking_after_a and logical_pos_after_a is not None
                    and op_b is _op_raw_mpv_sample):
                assert p._logical_pos == logical_pos_after_a, (
                    f"_logical_pos regressed from {logical_pos_after_a} to "
                    f"{p._logical_pos} across pair: {pair_desc}"
                )

    # Re-check emission invariant across ALL pairs combined isn't meaningful
    # per-pair (each pair uses a fresh Player) — covered by the full fuzz
    # test above instead. This test is scoped to the two invariants that
    # are meaningfully pairwise-local.
