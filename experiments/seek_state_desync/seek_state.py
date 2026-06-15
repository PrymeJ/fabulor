"""
SHELVED DESIGN ARTIFACT — NOT WIRED INTO THE APP. Targets a secondary seek-state
desync class (is_seeking/_seek_target), NOT the VT _file_offset freeze that was the
actual reported bug (that one is _current_vt_index/_file_offset set speculatively in
seek_async and never reconciled to the file mpv loads — see NOTES). Kept because the
desync it solves is real and characterized; if it ever surfaces as a real symptom,
this design is ready rather than re-derived. Do NOT treat as live coverage.

---

Single seek-state authority for Fabulor's playback path.

The bug class we're killing: _is_seeking and _seek_target were two free-floating
attributes mutated across the mpv-event thread and the Qt main thread. Every
red-team round found another pair that could desync:
  - coord-space: target stored LOCAL, compared GLOBAL
  - gen-clobber:  a stale seek's follow-up adopted a newer seek's identity
                  because the gen was carried in a separate mutable field
  - ungated slot: _on_vt_file_switched cleared is_seeking without the target

This module makes those states UNREPRESENTABLE rather than guarded-against:

  * There is exactly ONE attribute on the player: `_seek` : SeekState.
  * SeekState is either NotSeeking() or Seeking(target_global, gen).
    There is no way to hold is_seeking=True with target=None, or vice versa,
    because they are not separate fields.
  * The generation is INTRINSIC to the Seeking value. A follow-up seek does not
    carry a gen through a side field — it is handed the SAME Seeking value it
    is continuing, so it cannot be relabelled by a newer seek that ran in
    between. The newer seek simply produced a different Seeking value with a
    higher gen; the older continuation still references the older value.

Coordinate space is enforced by construction: Seeking.target is GLOBAL, always.
The mpv command stays LOCAL at the call site; that's a command argument, never
stored here.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Union, Optional


@dataclass(frozen=True)
class NotSeeking:
    """No seek in flight. UI guards are open."""
    __slots__ = ()


@dataclass(frozen=True)
class Seeking:
    """
    A seek in flight.

    target : GLOBAL position the settle compares against. Never local.
    gen    : monotonic id of THIS seek. Intrinsic — not stored anywhere else.
    """
    target: float
    gen: int
    __slots__ = ("target", "gen")


SeekState = Union[NotSeeking, Seeking]


class SeekAuthority:
    """
    The one owner of seek state. All reads/writes route through here.

    Thread note: this object does NOT make the two threads safe on its own.
    The frozen values mean a reader always sees a *consistent* (target, gen)
    pair — never a torn half-update — which is the desync class. Liveness
    (does the final seek's settle ever arrive) and true memory visibility
    across threads remain the soak's job; see EXPERIMENT_NOTES.
    """

    def __init__(self) -> None:
        self._state: SeekState = NotSeeking()
        self._gen_counter: int = 0

    # ---- queries -------------------------------------------------------
    @property
    def is_seeking(self) -> bool:
        return isinstance(self._state, Seeking)

    @property
    def target(self) -> Optional[float]:
        return self._state.target if isinstance(self._state, Seeking) else None

    @property
    def state(self) -> SeekState:
        return self._state

    # ---- transitions ---------------------------------------------------
    def begin(self, target_global: float) -> Seeking:
        """
        Start a NEW logical seek. Returns the Seeking value so the caller can
        hand it to a continuation (cross-file follow-up) WITHOUT going through
        any shared field. This return value IS the gen-carry mechanism.
        """
        self._gen_counter += 1
        s = Seeking(target=float(target_global), gen=self._gen_counter)
        self._state = s
        return s

    def continue_as(self, original: Seeking, new_target_global: float) -> Seeking:
        """
        Continue an EXISTING logical seek across a file-load hop, keeping its
        gen, but updating the target to the now-known global landing.

        Crucially: if a newer seek has begun since `original`, this is a no-op
        on the live state — we do NOT install an older gen over a newer one.
        The continuation still returns a value bound to the old gen so the
        caller's later settle(old_gen) is correctly recognised as stale.
        """
        cont = Seeking(target=float(new_target_global), gen=original.gen)
        if isinstance(self._state, Seeking) and self._state.gen == original.gen:
            self._state = cont
        # else: a newer seek owns the state; leave it. cont is still returned
        # so the caller can settle/clear against the old gen as a no-op.
        return cont

    def settle(self, gen: int) -> bool:
        """
        Clear the seek IFF `gen` is the live seek. A stale settle (older gen,
        from a superseded seek or a late mpv-thread callback) is a no-op.
        Returns True if it actually cleared.
        """
        if isinstance(self._state, Seeking) and self._state.gen == gen:
            self._state = NotSeeking()
            return True
        return False

    def clear(self, gen: Optional[int] = None) -> bool:
        """
        Force-clear. gen=None clears unconditionally (load_book reset, stop).
        gen=int clears only if it matches the live seek (gated slot clear).
        """
        if gen is None:
            self._state = NotSeeking()
            return True
        if isinstance(self._state, Seeking) and self._state.gen == gen:
            self._state = NotSeeking()
            return True
        return False

    # ---- invariant (for tests) ----------------------------------------
    def assert_consistent(self) -> None:
        s = self._state
        assert isinstance(s, (NotSeeking, Seeking)), f"bad state {s!r}"
        if isinstance(s, Seeking):
            assert s.target is not None
            assert s.gen >= 1
