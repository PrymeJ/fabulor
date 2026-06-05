"""Single authority for the book-switch transition lifecycle.

When the user picks a book in the library, six concerns run concurrently —
``book_ready`` emission, the library slide-out animation, the mpv position-restore
seek, cover load, the 200 ms UI timer, and the cover-art theme fade. Previously each
was coordinated by an ad-hoc flag read directly off ``MainWindow``/``Player``. This
object owns the *switch-specific* flags and exposes an explicit phase plus named
predicates, so every consumer reads one place instead of poking raw attributes.

Scope boundary: this owns ONLY switch-specific state. The orthogonal guards —
``player._is_seeking``/``_seek_target``, the slider-drag flags, ``_flow_anim`` running
state, and ``mp3_seek_reload_pending`` — fire for non-switch reasons (chapter nav,
manual seeks, theme color animations, MP3 stop-and-load). They stay where they are and
this object *composes* with them; absorbing them would reintroduce the documented
chapter-nav/seek bugs (see CLAUDE.md and NOTES.md).

The phase is *derived* from the sub-flags rather than stored, so there is no fragile
terminal transition to get wrong: it returns to IDLE automatically once the deadzone
ends and both ``book_ready`` handlers have consumed their captured slider values. The
post-consume animation/seek-settle window is carried by the retained orthogonal guards.
"""

from enum import IntEnum
from typing import Optional


class SwitchPhase(IntEnum):
    IDLE = 0       # no switch in progress
    LOADING = 1    # book selected → library hidden; mpv output must be ignored (deadzone)
    RESTORING = 2  # library revealed; flow animations + restore seek still in flight


class BookSwitchState:
    """Lifecycle of a single library-initiated book switch.

    Transitions: ``begin()`` (IDLE→LOADING) at selection, ``library_revealed()``
    (LOADING→RESTORING) when the library slide-out finishes, then the two
    ``take_*_target()`` consumers drain the captured values back to IDLE.
    """

    def __init__(self) -> None:
        self._in_deadzone: bool = False
        self._pre_slider: Optional[int] = None
        self._pre_chap: Optional[int] = None
        self._chaps_dur_retried: bool = False
        self._file_ready_deferred: bool = False
        self._chaps_deferred: bool = False

    # ----- derived phase -----

    @property
    def phase(self) -> SwitchPhase:
        if self._in_deadzone:
            return SwitchPhase.LOADING
        if self._pre_slider is not None or self._pre_chap is not None:
            return SwitchPhase.RESTORING
        return SwitchPhase.IDLE

    @property
    def is_active(self) -> bool:
        """True while a switch is in progress (LOADING or RESTORING)."""
        return self.phase != SwitchPhase.IDLE

    # ----- load-bearing query predicates (replace raw flag reads 1:1) -----

    @property
    def in_deadzone(self) -> bool:
        """Replaces ``_mpv_ready == False`` — mpv position output must be ignored."""
        return self._in_deadzone

    @property
    def flow_pending_progress(self) -> bool:
        """Replaces ``_pre_switch_slider_value is not None``."""
        return self._pre_slider is not None

    @property
    def flow_pending_chapter(self) -> bool:
        """Replaces ``_pre_switch_chap_slider_value is not None``."""
        return self._pre_chap is not None

    # ----- duration-race retry flag (read/write) -----

    @property
    def chaps_dur_retried(self) -> bool:
        return self._chaps_dur_retried

    @chaps_dur_retried.setter
    def chaps_dur_retried(self, value: bool) -> None:
        self._chaps_dur_retried = value

    # ----- deferred-handler flags -----

    @property
    def file_ready_deferred(self) -> bool:
        return self._file_ready_deferred

    @property
    def chaps_deferred(self) -> bool:
        return self._chaps_deferred

    def mark_file_ready_deferred(self) -> None:
        self._file_ready_deferred = True

    def clear_file_ready_deferred(self) -> None:
        self._file_ready_deferred = False

    def mark_chaps_deferred(self) -> None:
        self._chaps_deferred = True

    def clear_chaps_deferred(self) -> None:
        self._chaps_deferred = False

    # ----- transitions -----

    def begin(self, pre_slider: int, pre_chap: Optional[int]) -> None:
        """IDLE → LOADING. Called at book selection.

        Captures the current slider values as flow-animation start points, enters the
        deadzone, and resets the per-switch retry/deferred flags.

        Pass pre_chap=None when the outgoing book is chapterless (_chapter_ui_active is
        False). Capturing a meaningless slider value would set flow_pending_chapter=True,
        gating _sync_chapter_ui and preventing the slider from staying hidden during load;
        None keeps flow_pending_chapter False so the slider stays hidden throughout.
        """
        self._in_deadzone = True
        self._pre_slider = pre_slider
        self._pre_chap = pre_chap
        self._chaps_dur_retried = False
        self._file_ready_deferred = False
        self._chaps_deferred = False

    def library_revealed(self) -> None:
        """LOADING → RESTORING. Called when the library slide-out animation finishes."""
        self._in_deadzone = False

    # take_*_target() are CONSUMING reads: each captured value can be read exactly
    # once, after which the corresponding flow_pending_* predicate flips to False and
    # the phase advances toward IDLE. That coupling is intentional — it is how the
    # switch tears itself down. If a future fix needs to *inspect* a pre-value without
    # consuming it (e.g. inside a conditional that decides whether to animate), add a
    # non-consuming peek property (e.g. `pre_progress`/`pre_chapter`) alongside the
    # take method; do NOT read-then-restore via take(), and do NOT make a guard depend
    # on calling take() for its side effect.

    def take_progress_target(self) -> Optional[int]:
        """Consume the captured progress-slider start value (once). See note above."""
        val = self._pre_slider
        self._pre_slider = None
        return val

    def take_chapter_target(self) -> Optional[int]:
        """Consume the captured chapter-slider start value (once). See note above."""
        val = self._pre_chap
        self._pre_chap = None
        return val
