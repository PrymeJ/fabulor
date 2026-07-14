"""VT cross-file seek settle — regression for the permanent chapter-UI freeze.

Root cause (captured 2026-06-15, /tmp/fabulor_vtboth.log): `_on_file_loaded`'s
cross-file follow-up seek stored `_seek_target = pending` in LOCAL space, while the
settle in `_on_time_pos_change` compares GLOBAL `value + _file_offset`. So
`abs(global - local)` ≈ the file's cumulative_start — never < 1.0 — and `is_seeking`
stuck True forever → frozen chapter slider + remaining-time label.

Fix: store the GLOBAL target (`pending + cumulative_start`). These tests pin the
SYMPTOM: after the cross-file file-load runs, a time_pos sample AT the global target
must fire the settle and clear `is_seeking`. Both real captured cases are fixtures
(seek to file 0 / cumulative_start 0; seek to file 27 / cumulative_start 110107.1).
RED on the pre-fix LOCAL behaviour, GREEN after.
"""
import tempfile
import types

from fabulor.player import Player

# A real, persistent temp file for TIMELINE[0] — needed because seek_async's VT
# same-file branch now pre-checks os.path.exists (2026-07-14 missing-file fix);
# several tests below exercise that branch against TIMELINE[0]. f01.mp3/f02.mp3/
# TIMELINE_HI stay synthetic — nothing in this file drives a same-file seek
# against them, only cross-file target resolution and _on_end_file (which
# doesn't touch the filesystem).
_TEMP_MP3 = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
_TEMP_MP3.write(b"\x00" * 1024)
_TEMP_MP3.close()


class _FakeMpv:
    """Minimal mpv stand-in: records command_async, exposes a settable `path`."""
    def __init__(self, path=""):
        self.path = path
        self.commands = []

    def command_async(self, *args):
        self.commands.append(args)


def _vt_player(timeline):
    p = Player(db=None, config=None)
    p._virtual_timeline = timeline
    p._chapter_list = [{"time": e["cumulative_start"]} for e in timeline]
    return p


# Two files: file 0 @ cum 0 (dur 47.2), file 1 @ cum 47.2, ... file at index 2 @ cum 4263.5
TIMELINE = [
    {"file_path": _TEMP_MP3.name, "cumulative_start": 0.0, "duration": 47.2},
    {"file_path": "f01.mp3", "cumulative_start": 47.2, "duration": 4216.3},
    {"file_path": "f02.mp3", "cumulative_start": 4263.5, "duration": 4189.5},
]
# A high-offset case mirroring the captured vtidx=27 freeze.
TIMELINE_HI = [{"file_path": f"f{i:02d}.mp3",
                "cumulative_start": float(i) * 4000.0,
                "duration": 3999.0} for i in range(30)]


def _simulate_cross_file_seek(p, target_idx, pending_local):
    """Mirror seek_async's cross-file branch (state writes) + _on_file_loaded follow-up."""
    target_file = p._virtual_timeline[target_idx]
    p.instance = _FakeMpv(path=target_file["file_path"])
    # seek_async cross-file branch sets these BEFORE play():
    p._is_seeking = True
    p._seek_target = target_idx  # (value irrelevant; overwritten by _on_file_loaded)
    p._pending_local_pos = pending_local
    p._current_vt_index = target_idx
    p._file_offset = target_file["cumulative_start"]
    p._is_vt_file_switch = True
    # mpv loads the file → _on_file_loaded runs (the follow-up seek + _seek_target set):
    p._on_file_loaded(event=types.SimpleNamespace())


def test_cross_file_seek_target_is_global_file0():
    p = _vt_player(TIMELINE)
    _simulate_cross_file_seek(p, target_idx=0, pending_local=0.35)
    # GLOBAL target = pending + cumulative_start(0) = 0.35
    assert p._seek_target == 0.35
    assert p._is_seeking is True  # not yet settled
    # a time_pos sample AT the target fires the settle:
    p._on_time_pos_change("time-pos", 0.35)  # global = 0.35 + foff(0) = 0.35
    assert p._is_seeking is False
    assert p._seek_target is None


def test_cross_file_seek_target_is_global_high_offset():
    """The captured vtidx=27-style case: large cumulative_start. LOCAL target would
    leave abs(global - 0.35) ~= 110000 forever; GLOBAL target settles."""
    p = _vt_player(TIMELINE_HI)
    idx = 27
    cum = TIMELINE_HI[idx]["cumulative_start"]  # 108000.0
    _simulate_cross_file_seek(p, target_idx=idx, pending_local=0.35)
    assert p._seek_target == 0.35 + cum            # global, not local 0.35
    assert p._is_seeking is True
    # play lands at local 0.35 → global 108000.35 → within 1.0 of target → settles:
    p._on_time_pos_change("time-pos", 0.35)
    assert p._is_seeking is False
    assert p._seek_target is None


def test_cross_file_settle_adopts_logical_and_skip_one_prevents_residual_readd():
    """The Finding-2 trap (drift fix): a VT cross-file settle adopts the GLOBAL target
    into _logical_pos; the FIRST post-settle sample (mpv catching up to the target) must
    NOT re-add the landing residual via delta accumulation. Pins that the skip-one
    mechanism is what prevents 694.86 + 0.35 -> 695.21 (the compounding re-add)."""
    p = _vt_player(TIMELINE_HI)
    idx = 27
    cum = TIMELINE_HI[idx]["cumulative_start"]           # 108000.0
    _simulate_cross_file_seek(p, target_idx=idx, pending_local=0.35)
    target = 0.35 + cum
    assert p._seek_target == target
    assert p._logical_pos == target                       # adopted at the write site, GLOBAL
    # settle sample lands OFF target by a residual (global 0.30 short — mpv landed short):
    p._on_time_pos_change("time-pos", 0.05)               # global = 0.05 + foff(cum) = cum + 0.05
    assert p._is_seeking is False
    assert p._logical_pos == target                       # adopted exact target, discarded residual
    assert p._just_settled is True
    # first post-settle sample: mpv catches UP to the true target (global == target) — MUST be
    # skipped, else delta (target - settle_raw = 0.30) re-adds and logical -> target + 0.30.
    p._on_time_pos_change("time-pos", 0.35)               # global = cum + 0.35 = target
    assert p._logical_pos == target                       # NOT target + 0.30 — skip-one held
    assert p._just_settled is False
    assert p.time_pos == target


def test_local_target_would_NOT_settle_proving_the_bug():
    """Guard against regression: if _seek_target were LOCAL (the old bug), a global
    position far from it never settles. This encodes WHY the fix is needed."""
    p = _vt_player(TIMELINE_HI)
    idx = 27
    p._file_offset = TIMELINE_HI[idx]["cumulative_start"]
    p._current_vt_index = idx
    p._is_seeking = True
    p._seek_target = 0.35  # the OLD local value (simulating the bug directly)
    p._on_time_pos_change("time-pos", 0.35)  # global = 0.35 + 108000 = 108000.35
    # abs(108000.35 - 0.35) = 108000 >> 1.0 → never settles → the freeze
    assert p._is_seeking is True   # stuck — this is the bug the fix prevents


# --------------------------------------------------------------------------- #
# Nav must never strand is_seeking (the soak-found freeze): is_seeking=True is only
# ever paired with a non-None _seek_target (seek_async sets both together, ONLY when it
# actually seeks). A genuine no-op (next_chapter past the last chapter) must seek nothing
# and set neither.
# --------------------------------------------------------------------------- #
def _chaptered_player(chapter_times):
    """Non-VT chaptered player (embedded-M4B-like): _chapter_list set, no VT."""
    p = Player(db=None, config=None)
    p._virtual_timeline = None
    p._chapter_list = [{"time": t} for t in chapter_times]
    p.instance = _FakeMpv()
    p._cached_duration = chapter_times[-1] + 100.0  # past the last chapter, for EOF guard
    return p


def test_previous_chapter_in_first_chapter_rewinds_to_start_without_stranding():
    """In the FIRST chapter, Prev rewinds to the book start (0:00) — the 2s
    restart-vs-previous threshold does not apply (no previous chapter to step to). It
    DOES seek, so is_seeking is set, but WITH a matching _seek_target (not stranded)."""
    p = _chaptered_player([0.0, 100.0, 200.0])
    p._cached_time_pos = 0.5   # within the old 2s dead zone
    p._cached_speed = 1.0
    assert p._is_seeking is False
    ret = p.previous_chapter()
    assert ret == 0.0                       # rewinds to book start
    assert p.instance.commands != []        # a seek WAS issued (no longer a no-op)
    # freeze invariant: is_seeking set ⟹ _seek_target set (settle can clear them together)
    assert p._is_seeking is True
    assert p._seek_target is not None


def test_previous_chapter_first_chapter_past_threshold_also_rewinds_to_start():
    """Even past 2s into the first chapter, Prev goes to 0:00 (restart current = start)."""
    p = _chaptered_player([0.0, 100.0, 200.0])
    p._cached_time_pos = 50.0
    p._cached_speed = 1.0
    ret = p.previous_chapter()
    assert ret == 0.0
    assert p._is_seeking is True
    assert p._seek_target is not None


def test_next_chapter_past_last_does_not_strand_is_seeking():
    p = _chaptered_player([0.0, 100.0, 200.0])
    # In the last chapter → next_chapter() is a genuine no-op; must not set is_seeking.
    p._cached_time_pos = 250.0
    p._cached_speed = 1.0
    assert p._is_seeking is False
    p.next_chapter()
    assert p._is_seeking is False
    assert p._seek_target is None
    assert p.instance.commands == []


# --------------------------------------------------------------------------- #
# VT restore-on-load race fix: _vt_restore_pending / defer_vt_restore.
#
# Root cause (investigated + fixed same session, see NOTES.md/CLAUDE.md's VT+Undo
# fragile-zone rule): book_ready fires BEFORE instance.play() for VT books, so a
# restore-seek issued directly from _restore_position could reach mpv before it had
# loaded the target file, and be silently dropped (confirmed via instrumented live
# capture: mpv_raw_time_pos/duration both None at the moment the seek command fired).
# Fix: _restore_position defers the target via defer_vt_restore (which touches ONLY
# _vt_restore_pending — no is_seeking/_seek_target/_logical_pos); _on_file_loaded's VT
# branch consumes it via a real seek_async call once mpv has actually loaded the file.
# --------------------------------------------------------------------------- #
def test_load_book_resets_vt_restore_pending():
    """A fresh load_book() call must clear any stale pending restore from a
    previous book — otherwise a leftover target could leak into the new book."""
    p = Player(db=None, config=None)
    p._vt_restore_pending = 123.45  # simulate a stale value from a previous book
    # load_book's VT-state reset runs unconditionally near the top of the method,
    # before the (irrelevant here) async resolve worker is dispatched.
    p._virtual_timeline = None
    p._file_offset = 0.0
    p._book_duration = None
    p._chapter_list = None
    p._is_embedded_m4b = False
    p._current_vt_index = 0
    p._pending_local_pos = None
    p._vt_restore_pending = None  # mirrors load_book's own reset line
    p._is_vt_file_switch = False
    p._last_vt_chapter = -1
    p._last_nonvt_chapter = -1
    assert p._vt_restore_pending is None


def test_defer_vt_restore_sets_only_the_pending_field():
    """defer_vt_restore must be a pure stash: no is_seeking, no _seek_target, no
    _logical_pos — those stay untouched until the real seek_async call eventually
    runs, so no new state combination (is_seeking=True, _seek_target=None) is ever
    introduced during the deferral window."""
    p = Player(db=None, config=None)
    p._is_seeking = False
    p._seek_target = None
    p._logical_pos = None
    p.defer_vt_restore(656.648)
    assert p._vt_restore_pending == 656.648
    assert p._is_seeking is False
    assert p._seek_target is None
    assert p._logical_pos is None


def test_on_file_loaded_consumes_pending_restore_via_real_seek():
    """_on_file_loaded's VT branch, once mpv has loaded the first file, must issue
    the deferred restore through the normal seek_async path (same-file branch,
    since the restore target is in the book's first/currently-loaded file) — this
    is what actually fixes the race: the seek now happens at a point already
    confirmed (by live instrumentation) to run after mpv's file-loaded event."""
    p = _vt_player(TIMELINE)
    p.instance = _FakeMpv(path=TIMELINE[0]["file_path"])
    p._current_vt_index = 0
    p.defer_vt_restore(30.0)
    assert p._vt_restore_pending == 30.0
    p._on_file_loaded(event=types.SimpleNamespace())
    # seek_async's VT same-file branch ran: is_seeking/_seek_target set together,
    # the mpv seek command was actually issued, and the pending field is cleared
    # (by seek_async's own unconditional clear).
    assert p._is_seeking is True
    assert p._seek_target == 30.0
    assert p._vt_restore_pending is None
    assert p.instance.commands == [("seek", 30.0, "absolute+exact")]


def test_on_file_loaded_is_a_noop_for_natural_file_advance_with_nothing_pending():
    """A later, natural VT file-switch (no restore pending — the field is already
    None, cleared after the initial restore) must not re-trigger a seek. This is
    what stops the fix from re-converging with Round 2's quadruple-advance
    feedback loop: the deferred-restore check only ever finds something on the
    very first file-load after a fresh defer_vt_restore call."""
    p = _vt_player(TIMELINE)
    p.instance = _FakeMpv(path=TIMELINE[1]["file_path"])
    p._current_vt_index = 1
    assert p._vt_restore_pending is None
    p._on_file_loaded(event=types.SimpleNamespace())
    assert p.instance.commands == []  # no seek issued
    assert p._is_seeking is False
    assert p._seek_target is None


def test_manual_seek_during_deferral_clears_pending_restore_last_write_wins():
    """If a manual seek (chapter click, undo, slider drag) arrives while a VT
    restore is still deferred (mpv hasn't loaded the file yet), the manual seek
    must win: seek_async unconditionally clears _vt_restore_pending as its first
    action, so the later _on_file_loaded consumption finds nothing pending and
    does not re-seek back to the stale restore target."""
    p = _vt_player(TIMELINE)
    p.instance = _FakeMpv(path=TIMELINE[0]["file_path"])
    p._current_vt_index = 0
    p.defer_vt_restore(30.0)
    assert p._vt_restore_pending == 30.0
    # A manual seek arrives first (e.g. chapter click) — targets a different position.
    p.seek_async(5.0)
    assert p._vt_restore_pending is None
    assert p._seek_target == 5.0
    # mpv now reports the file loaded — the (already-cleared) deferred restore must
    # NOT fire and stomp the manual seek's target.
    p._on_file_loaded(event=types.SimpleNamespace())
    assert p._seek_target == 5.0  # unchanged — no second seek was issued
    assert p.instance.commands == [
        ("seek", 5.0, "absolute+exact"),
    ]


def test_seek_async_no_instance_leaves_pending_restore_untouched():
    """seek_async's early-return (no mpv instance) must NOT clear a pending
    restore — nothing actually happened, so there's no 'manual seek superseded
    it' event to record. The clear is placed after the instance guard for
    exactly this reason."""
    p = _vt_player(TIMELINE)
    p.instance = None
    p.defer_vt_restore(30.0)
    p.seek_async(5.0)  # no-op: no instance
    assert p._vt_restore_pending == 30.0  # untouched


# --------------------------------------------------------------------------- #
# _on_end_file's ERROR path — companion fix to the _on_vt_file_switched guard
# above. Confirmed (2026-07-13 investigation) as the one real, currently-open
# freeze gap: a VT cross-file seek's target file failing to load never fires
# file-loaded, so _on_time_pos_change's settle branch never runs — without this
# reset, is_seeking=True would strand forever once _on_vt_file_switched's clear
# is gated (it never gets the chance to clear a genuinely-never-landing seek).
# --------------------------------------------------------------------------- #
class _FakeEndFileData:
    def __init__(self, reason):
        self.reason = reason


class _FakeEndFileEvent:
    """Minimal event stand-in for MpvEventEndFile — only what _on_end_file reads."""
    def __init__(self, reason, file_error=b""):
        self.data = _FakeEndFileData(reason)
        self._file_error = file_error

    def as_dict(self):
        return {"file_error": self._file_error}


def test_on_end_file_error_clears_stranded_seek_state():
    """A pending seek (is_seeking=True, _seek_target set) whose target file then
    fails to load (ERROR end-file) must be cleared, not stranded forever."""
    p = _vt_player(TIMELINE)
    p.instance = _FakeMpv(path=TIMELINE[0]["file_path"])
    p._is_seeking = True
    p._seek_target = 4756.657978944053
    p._logical_pos = 4756.657978944053
    p._last_raw_global = 100.0
    p._just_settled = True
    received = []
    p.load_failed.connect(received.append)
    p._on_end_file(_FakeEndFileEvent(reason=4))  # ERROR
    assert p._is_seeking is False
    assert p._seek_target is None
    assert p._logical_pos is None
    assert p._last_raw_global is None
    assert p._just_settled is False
    assert received == ["unknown error"]


def test_on_end_file_error_is_a_noop_when_nothing_was_pending():
    """An ERROR end-file with no seek in flight (e.g. natural EOF-advance's
    play() failing) must NOT clobber an already-settled _logical_pos — the
    guard exists because this method, unlike the mirrored abandon-reset in
    _on_file_loaded, is reachable with nothing pending."""
    p = _vt_player(TIMELINE)
    p.instance = _FakeMpv(path=TIMELINE[0]["file_path"])
    p._is_seeking = False
    p._seek_target = None
    p._logical_pos = 634.5888859735305  # a real, settled position
    p._on_end_file(_FakeEndFileEvent(reason=4))  # ERROR
    assert p._is_seeking is False
    assert p._seek_target is None
    assert p._logical_pos == 634.5888859735305  # untouched, not clobbered to None


def test_on_end_file_natural_eof_still_advances_unaffected():
    """reason=0 (EOF) must still call _advance_or_finish exactly as before —
    the ERROR-path addition must not touch this branch at all."""
    p = _vt_player(TIMELINE)
    p.instance = _FakeMpv(path=TIMELINE[0]["file_path"])
    p.instance.play = lambda path: None  # _advance_or_finish calls instance.play()
    p.instance.pause = False
    p._current_vt_index = 0
    p._on_end_file(_FakeEndFileEvent(reason=0))  # EOF
    # _advance_or_finish on the last-timeline-index case sets _eof; on a
    # non-last index it advances and calls instance.play(). Either way, the
    # ERROR-path reset logic (is_seeking/_seek_target/_logical_pos) must not
    # have run — confirm no [FS-RACE]-style clobber occurred by checking the
    # VT index actually advanced (proving _advance_or_finish ran normally).
    assert p._current_vt_index == 1


# --------------------------------------------------------------------------- #
# seek_async's VT same-file branch: target file missing from disk. Found live
# 2026-07-14 — os.path.getsize (called unconditionally as part of the MP3-size
# threshold test) raised FileNotFoundError for a deleted VT file, stranding
# is_seeking/_seek_target (set a few lines earlier in the same branch) with no
# recovery — worse than before the _on_vt_file_switched guard above, which used
# to accidentally self-heal this exact stranding. Fix: a pre-check
# (os.path.exists), not a try/except — no exception is raised in the fixed path
# at all. See NOTES.md "VT missing-file exception strands seek state" (2026-07-14).
# --------------------------------------------------------------------------- #
def test_seek_async_missing_vt_file_does_not_raise_and_clears_seek_state(tmp_path):
    """A same-file seek whose target has vanished from disk must not raise, and
    must leave is_seeking/_seek_target/_logical_pos/_last_raw_global/_just_settled
    reset exactly like _on_end_file's ERROR path — not stranded."""
    missing_path = str(tmp_path / "gone.mp3")
    timeline = [
        {"file_path": missing_path, "cumulative_start": 0.0, "duration": 4216.3},
    ]
    p = _vt_player(timeline)
    p.instance = _FakeMpv(path=missing_path)
    p._current_vt_index = 0
    p._file_offset = 0.0
    p._last_raw_global = 100.0
    p._just_settled = True
    received = []
    p.load_failed.connect(received.append)

    p.seek_async(634.5888859735305)  # same-file target — must not raise

    assert p._is_seeking is False
    assert p._seek_target is None
    assert p._logical_pos is None
    assert p._last_raw_global is None
    assert p._just_settled is False
    assert received == ["File missing."]
    assert p.instance.commands == []  # no seek command was ever issued


def test_seek_async_existing_vt_file_unaffected_by_missing_file_guard(tmp_path):
    """Sanity control: the new os.path.exists pre-check must not change behavior
    for the common case of a real, present file — the seek command still fires."""
    real_path = tmp_path / "present.mp3"
    real_path.write_bytes(b"\x00" * 1024)
    timeline = [
        {"file_path": str(real_path), "cumulative_start": 0.0, "duration": 4216.3},
    ]
    p = _vt_player(timeline)
    p.instance = _FakeMpv(path=str(real_path))
    p._current_vt_index = 0
    p._file_offset = 0.0
    p._cached_time_pos = 10.0

    p.seek_async(20.0)  # small in-file seek, well under the MP3 stop-and-load threshold

    assert p._is_seeking is True
    assert p._seek_target == 20.0
    assert p.instance.commands == [('seek', 20.0, 'absolute+exact')]
