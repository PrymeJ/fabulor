"""Regression net for ClickSlider.jump_shift_left/jump_shift_right (added
2026-09-22, live feature request for the Settings > Audio EQ bands and L/R
balance slider — both are ClickSlider instances with a bidirectional
±range/midpoint shape).

Spec, in Pryme's own words: "Shift + right arrow: all the way to max (+6)
when it is not on the negative side. Still goes to the max from the
mid-point. Shift + right arrow: reset to 0 when it is on the negative side.
Shift + left arrow: all the way to left (-6) when it is not on the positive
side. Still goes all the way left from the mid-point. Shift + left arrow:
reset to 0 when it is on the positive side. So, from anywhere falling to the
right side of the middle, Shift+left first takes it to the mid-point, then
all the way to the left."

No QApplication is strictly required for ClickSlider (a plain QWidget
subclass with no native widget dependency in its constructor), but Qt still
needs a QApplication instance alive to construct any QWidget — matches this
file's neighbors (test_audio_processing.py, etc.) that construct real
widgets.
"""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from fabulor.ui.controls import ClickSlider


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def make_slider(qapp, minimum=-60, maximum=60):
    s = ClickSlider(Qt.Horizontal)
    s.setRange(minimum, maximum)
    return s


# --------------------------------------------------------------------------- #
# jump_shift_right
# --------------------------------------------------------------------------- #
def test_shift_right_from_midpoint_jumps_to_max(qapp):
    s = make_slider(qapp)
    s.setValue(0)
    s.jump_shift_right()
    assert s.value() == 60


def test_shift_right_from_positive_side_jumps_to_max(qapp):
    s = make_slider(qapp)
    s.setValue(30)
    s.jump_shift_right()
    assert s.value() == 60


def test_shift_right_from_negative_side_resets_to_midpoint(qapp):
    s = make_slider(qapp)
    s.setValue(-30)
    s.jump_shift_right()
    assert s.value() == 0


def test_shift_right_at_max_is_a_noop(qapp):
    s = make_slider(qapp)
    s.setValue(60)
    s.jump_shift_right()
    assert s.value() == 60


# --------------------------------------------------------------------------- #
# jump_shift_left (mirror image)
# --------------------------------------------------------------------------- #
def test_shift_left_from_midpoint_jumps_to_min(qapp):
    s = make_slider(qapp)
    s.setValue(0)
    s.jump_shift_left()
    assert s.value() == -60


def test_shift_left_from_negative_side_jumps_to_min(qapp):
    s = make_slider(qapp)
    s.setValue(-30)
    s.jump_shift_left()
    assert s.value() == -60


def test_shift_left_from_positive_side_resets_to_midpoint(qapp):
    s = make_slider(qapp)
    s.setValue(30)
    s.jump_shift_left()
    assert s.value() == 0


def test_shift_left_at_min_is_a_noop(qapp):
    s = make_slider(qapp)
    s.setValue(-60)
    s.jump_shift_left()
    assert s.value() == -60


# --------------------------------------------------------------------------- #
# the exact walk Pryme described: from the positive side, Shift+Left stops
# at the midpoint before a SECOND press goes all the way to the minimum
# --------------------------------------------------------------------------- #
def test_shift_left_twice_from_positive_side_stops_at_mid_then_goes_to_min(qapp):
    s = make_slider(qapp)
    s.setValue(30)
    s.jump_shift_left()
    assert s.value() == 0, "first Shift+Left from the positive side must stop at the midpoint"
    s.jump_shift_left()
    assert s.value() == -60, "second Shift+Left (now at/left-of mid) must go all the way to the minimum"


def test_shift_right_twice_from_negative_side_stops_at_mid_then_goes_to_max(qapp):
    s = make_slider(qapp)
    s.setValue(-30)
    s.jump_shift_right()
    assert s.value() == 0, "first Shift+Right from the negative side must stop at the midpoint"
    s.jump_shift_right()
    assert s.value() == 60, "second Shift+Right (now at/right-of mid) must go all the way to the maximum"


# --------------------------------------------------------------------------- #
# a different range (balance slider is -100..100, not EQ's -60..60) — must
# not be hardcoded to the EQ's specific bounds
# --------------------------------------------------------------------------- #
def test_works_against_balance_sliders_wider_range(qapp):
    s = make_slider(qapp, minimum=-100, maximum=100)
    s.setValue(0)
    s.jump_shift_right()
    assert s.value() == 100
    s.jump_shift_left()
    assert s.value() == 0
    s.jump_shift_left()
    assert s.value() == -100
