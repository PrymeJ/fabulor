"""Clicks are ignored while the volume slider runs a mute/unmute transition.

Live 2026-10-30: clicking the slider area repeatedly during the mute drain/fade made the
bar blink, each click restarting a fade. ClickSlider.input_gate swallows presses while
MainWindow._volume_mute_transition_running is True; the muted-icon click checks the same
predicate."""
import pytest
from PySide6.QtCore import QAbstractAnimation, QPointF, Qt, QEvent
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from fabulor.app import MainWindow
from fabulor.ui.controls import ClickSlider


@pytest.fixture(autouse=True)
def qapp():
    yield QApplication.instance() or QApplication([])


def _mouse(kind, x):
    return QMouseEvent(kind, QPointF(x, 5), QPointF(x, 5), Qt.LeftButton,
                       Qt.LeftButton if kind == QEvent.Type.MouseButtonPress else Qt.NoButton,
                       Qt.NoModifier)


def _slider(gate):
    s = ClickSlider(Qt.Horizontal)
    s.setRange(0, 100)
    s.resize(100, 10)
    s.input_gate = gate
    return s


def test_gated_press_and_its_release_change_nothing():
    s = _slider(lambda: True)
    pressed = []
    s.sliderPressed.connect(lambda: pressed.append(1))
    s.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, 60))
    s.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease, 60))
    assert s.value() == 0 and pressed == []


def test_ungated_click_still_sets_the_value():
    s = _slider(lambda: False)
    s.mousePressEvent(_mouse(QEvent.Type.MouseButtonPress, 60))
    s.mouseReleaseEvent(_mouse(QEvent.Type.MouseButtonRelease, 60))
    assert s.value() == 60


class _Slider:
    def __init__(self, value, flowing):
        self._v, self._f = value, flowing

    def value(self): return self._v
    def is_flowing(self): return self._f


class _Anim:
    def __init__(self, running):
        self._r = running

    def state(self):
        return (QAbstractAnimation.State.Running if self._r
                else QAbstractAnimation.State.Stopped)


@pytest.mark.parametrize("value, flowing, fading, target, expected", [
    (40, True,  False, None, True),    # fill draining or growing
    (0,  False, True,  None, True),    # empty bar fading out after a drain
    (0,  False, True,  70,   True),    # empty bar fading in ahead of an unmute's fill
    (40, False, True,  None, False),   # ordinary auto-hide fade: still clickable
    (40, False, False, None, False),   # idle
    (0,  False, False, None, False),   # resting muted
], ids=["flow", "mute_fade_out", "unmute_fade_in", "auto_hide", "idle", "muted_idle"])
def test_transition_predicate(value, flowing, fading, target, expected):
    mw = type("MW", (), {})()
    mw.volume_slider = _Slider(value, flowing)
    mw.vol_fade_anim = _Anim(fading)
    mw._unmute_fill_target = target
    assert MainWindow._volume_mute_transition_running(mw) is expected
