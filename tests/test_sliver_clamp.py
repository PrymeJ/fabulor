"""Chapter-slider 'sliver' suppression — threshold logic (pure, headless).

The chapter progress slider showed a thin fill ("sliver") at a freshly-landed chapter
start WHILE PAUSED: a chapter-nav seek lands at `_seek_target = nominal + offset`, and for
VT/CUE that offset is `_CHAPTER_BOUNDARY_EPSILON` (0.35), so `c_elapsed = pos - chap_start
~= 0.35` renders as a few-percent fill on a short chapter. `_sliver_clamp` reads the slider
value as 0 only when paused AND within the residue window; live playback releases it (pos is
moving, so no jump). These tests pin the threshold logic — the Qt rendering is soak-verified.
"""
from fabulor.app import _sliver_clamp, _CHAPTER_SLIVER_EPS
from fabulor.player import _CHAPTER_BOUNDARY_EPSILON


def test_paused_at_chapter_start_clamps_to_zero():
    # The artifact case: paused, sub-second elapsed at the start.
    assert _sliver_clamp(True, 0.0) == 0.0
    assert _sliver_clamp(True, 0.34) == 0.0


def test_paused_vt_cue_landing_residue_is_clamped():
    # The DOMINANT arrival path: VT/CUE lands at c_elapsed ~= _CHAPTER_BOUNDARY_EPSILON.
    # The threshold must dominate it (this is the case a naive 0.45 barely covered).
    assert _sliver_clamp(True, _CHAPTER_BOUNDARY_EPSILON) == 0.0
    assert _sliver_clamp(True, _CHAPTER_BOUNDARY_EPSILON + 0.05) == 0.0


def test_just_below_threshold_clamps():
    assert _sliver_clamp(True, _CHAPTER_SLIVER_EPS - 0.01) == 0.0


def test_just_above_threshold_passes_through():
    # Upper-boundary pin: a value just ABOVE EPS must NOT clamp. Catches a wrong constant
    # or a `<`->`<=` slip that the wide 0.35..5.0 gap would otherwise let pass.
    above = _CHAPTER_SLIVER_EPS + 0.01
    assert _sliver_clamp(True, above) == above


def test_paused_well_past_start_is_untouched():
    # Real mid-chapter progress while paused must render normally.
    assert _sliver_clamp(True, 5.0) == 5.0


def test_playing_never_clamps():
    # Live playback: gate is False, so even a sub-second elapsed passes through. (In
    # practice the sliver is invisible while playing because pos advances each frame.)
    assert _sliver_clamp(False, 0.0) == 0.0  # 0.0 in == 0.0 out (passthrough, not clamp)
    assert _sliver_clamp(False, 0.1) == 0.1
    assert _sliver_clamp(False, _CHAPTER_BOUNDARY_EPSILON) == _CHAPTER_BOUNDARY_EPSILON


def test_threshold_dominates_boundary_epsilon():
    # Regression guard: if either constant is retuned, the threshold must still sit above
    # the VT/CUE landing residue, or the sliver returns on exactly the short-chapter case.
    assert _CHAPTER_SLIVER_EPS > _CHAPTER_BOUNDARY_EPSILON
