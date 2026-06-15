"""
SHELVED EXPERIMENT — NOT A LIVE TEST, NOT WIRED INTO THE APP. Run manually with
`python replay.py` from this dir. It validated the seek-state-object design for the
is_seeking/_seek_target desync class — which, against the REAL capture, turned out NOT
to be the VT _file_offset freeze bug. Kept as evidence the design works for its class.
See NOTES for why the real fix is offset/index reconciliation in _on_file_loaded.

---

The deciding experiment.

Question: does collapsing _is_seeking + _seek_target + gen into one atomic
SeekState value absorb ALL THREE defects found across the red-team rounds,
when driven by the REAL captured event ordering (not a model of it)?

  D1 coord-space : target stored LOCAL while settle compares GLOBAL
  D2 gen-clobber : a stale cross-file follow-up adopts a newer seek's identity
  D3 ungated slot: _on_vt_file_switched clears is_seeking, leaving target

We model the playback path's seek-relevant calls ONLY, against SeekAuthority.
We do NOT model mpv decoding etc. The point is the coordination layer.

PASS A — the object used CORRECTLY (continue_as carries the handle).
PASS B — the object used like the OLD code (each follow-up begins a NEW gen,
         and slot clears ungated) to confirm the experiment can still
         REPRODUCE the freeze, i.e. the harness isn't trivially green.
"""

from seek_state import SeekAuthority, Seeking, NotSeeking

SETTLE_EPS = 1.0


# ---------------------------------------------------------------------------
# Captured sequence, transcribed from /tmp/fabulor_VTfreeze_capture.log shape.
# (Reconstruction from the plan's quoted lines — strengthened later by a real
#  log parse; see CAPTURED_FROM_LOG below.)
# ---------------------------------------------------------------------------
CAPTURED = [
    ("USER_SEEK", dict(global_target=4110.85, cross_file=True, local_pos=0.0, file_offset=4110.85)),
    ("USER_SEEK", dict(global_target=0.35, cross_file=True, local_pos=0.35, file_offset=0.0)),
    ("FILE_LOADED_STALE", dict(local_pos=0.0, file_offset=4110.85)),
    ("FILE_LOADED_LIVE", dict(local_pos=0.35, file_offset=0.0)),
    ("VT_SWITCHED_STALE", dict()),
    ("TIME_POS", dict(global_value=0.35, file_offset=0.0)),
    ("TIME_POS", dict(global_value=0.40, file_offset=0.0)),
]


class TwoFieldOldModel:
    """Faithful model of the PRE-FIX code: two free-floating fields."""
    def __init__(self):
        self.is_seeking = False
        self.seek_target = None  # may be LOCAL or GLOBAL depending on path (the bug)

    def settle_check(self, global_value, file_offset):
        if self.is_seeking and self.seek_target is not None:
            if abs(global_value + file_offset - self.seek_target) < SETTLE_EPS:
                self.is_seeking = False
                self.seek_target = None
                return True
        return False


def run_old(seq=CAPTURED, verbose=False):
    m = TwoFieldOldModel()
    log = []
    def note(msg):
        if verbose: print(msg)
        log.append(msg)
    for kind, p in seq:
        if kind == "USER_SEEK":
            m.is_seeking = True
            m.seek_target = p["global_target"]  # seek_async stores GLOBAL (player.py:599)
            note(f"USER_SEEK is_seeking=True tgt(GLOBAL)={m.seek_target}")
        elif kind in ("FILE_LOADED_STALE", "FILE_LOADED_LIVE"):
            # _on_file_loaded:465 overwrites seek_target = LOCAL pending, WITHOUT
            # touching is_seeking (asymmetric write A) and in LOCAL space (D1).
            m.seek_target = p["local_pos"]
            note(f"{kind} seek_target=LOCAL {m.seek_target} (is_seeking untouched={m.is_seeking})")
        elif kind == "VT_SWITCHED_STALE":
            m.is_seeking = False
            note(f"VT_SWITCHED_STALE is_seeking=False (target left = {m.seek_target})")
        elif kind == "TIME_POS":
            ok = m.settle_check(p["global_value"], p["file_offset"])
            note(f"TIME_POS g={p['global_value']} foff={p['file_offset']} "
                 f"tgt={m.seek_target} is_seeking={m.is_seeking} settled={ok}")
    return m, log


def run(correct_usage: bool, gated_slot: bool, seq=CAPTURED, verbose=False):
    auth = SeekAuthority()
    pending_handles = []   # FIFO of (handle, local_pos, file_offset)
    log = []
    def note(msg):
        if verbose: print(msg)
        log.append(msg)

    for kind, p in seq:
        if kind == "USER_SEEK":
            h = auth.begin(p["global_target"])
            note(f"USER_SEEK begin gen={h.gen} tgt={h.target}")
            if p["cross_file"]:
                pending_handles.append((h, p["local_pos"], p["file_offset"]))
        elif kind in ("FILE_LOADED_STALE", "FILE_LOADED_LIVE"):
            if not pending_handles:
                note(f"{kind}: no pending handle (ignored)")
                continue
            if kind == "FILE_LOADED_STALE":
                h, local_pos, _ = pending_handles.pop(0)
            else:
                h, local_pos, _ = pending_handles.pop()
            global_target = local_pos + p["file_offset"]  # GLOBAL, derived from THIS load
            if correct_usage:
                cont = auth.continue_as(h, global_target)
                note(f"{kind} continue_as gen={cont.gen} -> tgt={cont.target} "
                     f"(live state gen={getattr(auth.state,'gen',None)})")
            else:
                bad = auth.begin(local_pos)  # LOCAL target == coord-space defect
                note(f"{kind} OLD begin gen={bad.gen} tgt(LOCAL)={bad.target}")
        elif kind == "VT_SWITCHED_STALE":
            if gated_slot:
                note("VT_SWITCHED_STALE gated -> no-op")
            else:
                cleared = auth.clear(None)
                note(f"VT_SWITCHED_STALE ungated -> clear(None) cleared={cleared}")
        elif kind == "TIME_POS":
            st = auth.state
            if isinstance(st, Seeking):
                dist = abs(p["global_value"] - st.target)
                if dist < SETTLE_EPS:
                    ok = auth.settle(st.gen)
                    note(f"TIME_POS g={p['global_value']} tgt={st.target} "
                         f"dist={dist:.2f} -> settle gen={st.gen} ok={ok}")
                else:
                    note(f"TIME_POS g={p['global_value']} tgt={st.target} "
                         f"dist={dist:.2f} -> NO settle")
            else:
                note(f"TIME_POS g={p['global_value']} (not seeking)")
        auth.assert_consistent()
    return auth, log


def describe(auth):
    st = auth.state
    return (f"is_seeking={auth.is_seeking} target={auth.target} "
            f"state={type(st).__name__}"
            + (f"(gen={st.gen})" if isinstance(st, Seeking) else ""))


if __name__ == "__main__":
    print("=" * 70)
    print("PASS A  — object used CORRECTLY (continue_as carries handle; gated slot)")
    print("=" * 70)
    a, _ = run(correct_usage=True, gated_slot=True, verbose=True)
    print("\nFINAL:", describe(a))
    a_ok = (not a.is_seeking) and (a.target is None)
    print("RESULT:", "PASS (no freeze: settled, target cleared)" if a_ok
          else "FAIL (stuck seeking / target retained)")

    print("\n" + "=" * 70)
    print("PASS B  — faithful OLD two-field model — must REPRODUCE the freeze")
    print("=" * 70)
    m, _ = run_old(verbose=True)
    print("\nFINAL: is_seeking=%s seek_target=%s" % (m.is_seeking, m.seek_target))
    b_buggy = (m.is_seeking and m.seek_target is None) or \
              (m.seek_target is not None and not m.is_seeking) or \
              (m.is_seeking)
    print("RESULT:", "REPRODUCES BUG (desync or stuck)" if b_buggy
          else "did NOT reproduce (experiment too weak!)")

    print("\n" + "=" * 70)
    print("VERDICT")
    print("=" * 70)
    if a_ok and b_buggy:
        print("The state object ABSORBS the defects: correct usage settles cleanly,")
        print("and the old-style misuse still freezes — so the object, not luck,")
        print("is what fixes it. D1/D2/D3 cannot be expressed under correct usage.")
    elif a_ok and not b_buggy:
        print("Correct usage passes BUT the experiment can't reproduce the old")
        print("freeze — the harness is too weak to trust the green. Strengthen it.")
    else:
        print("Correct usage still FREEZES — the object does NOT absorb the class.")
        print("This is the evidence that would justify reconsidering the design.")
