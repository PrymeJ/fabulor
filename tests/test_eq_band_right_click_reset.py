"""Regression net for right-click-to-reset on the 5 Settings > Audio EQ sliders
(added 2026-09-22, small feature request — not a bug fix).

ClickSlider.mousePressEvent already emits rightClicked(ratio) unconditionally
for every right click, used elsewhere (progress slider) for seek-to-position —
the 5 EQ sliders simply never connected it to anything, so a right click was
silently inert. AudioSettingsTab now connects each band's rightClicked to
_reset_eq_band(freq_key), which resets ONLY that one band's slider value to 0
— the existing valueChanged -> _on_eq_changed connection then handles the
config write / sync_player / update_visuals exactly as a manual drag would,
so _reset_eq_band itself only needs to touch the slider.

QSettings isolation follows test_audio_processing.py's verified-working
fixture shape exactly (see that file's own comment on why
setDefaultFormat/setPath alone doesn't isolate on this platform) — monkeypatch
fabulor.config.QSettings so Config()'s hardcoded QSettings("Fabulor",
"Fabulor") resolves to a throwaway tmp_path .ini file instead of the real,
live ~/.config/Fabulor/Fabulor.conf.
"""
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from fabulor.config import Config
from fabulor.ui.audio_controls import AudioSettingsTab

_EQ_FREQS = ["100", "300", "1000", "3000", "8000"]


@pytest.fixture
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def config(qapp, tmp_path, monkeypatch):
    ini_path = str(tmp_path / "test_eq_reset_settings.ini")

    class _IsolatedQSettings(QSettings):
        def __init__(self, *_args, **_kwargs):
            super().__init__(ini_path, QSettings.IniFormat)

    import fabulor.config as config_mod
    monkeypatch.setattr(config_mod, "QSettings", _IsolatedQSettings)
    return Config()


@pytest.fixture
def tab(qapp, config):
    return AudioSettingsTab(player=None, config=config)


def test_right_click_resets_only_the_clicked_band(tab, config):
    # Slider range is +/-6.0dB (setRange(-60, 60) in tenths) — stay within it.
    values = [1.0, 2.0, 3.0, -2.0, -4.5]
    for freq, value in zip(_EQ_FREQS, values):
        getattr(config, f"set_eq_gain_{freq}")(value)
        tab.eq_sliders[freq].setValue(int(value * 10))

    tab.eq_sliders["1000"].rightClicked.emit(0.5)  # ratio value is irrelevant to reset

    assert tab.eq_sliders["1000"].value() == 0
    assert config.get_eq_gain_1000() == 0.0
    # every other band must be completely untouched
    assert config.get_eq_gain_100() == 1.0
    assert config.get_eq_gain_300() == 2.0
    assert config.get_eq_gain_3000() == -2.0
    assert config.get_eq_gain_8000() == -4.5


def test_right_click_on_each_band_resets_that_band_independently(tab, config):
    for freq in _EQ_FREQS:
        getattr(config, f"set_eq_gain_{freq}")(1.0)
        tab.eq_sliders[freq].setValue(10)

    for freq in _EQ_FREQS:
        tab.eq_sliders[freq].rightClicked.emit(0.5)
        assert tab.eq_sliders[freq].value() == 0
        assert getattr(config, f"get_eq_gain_{freq}")() == 0.0


def test_right_click_on_an_already_zero_band_is_a_harmless_noop(tab, config):
    assert config.get_eq_gain_300() == 0.0
    tab.eq_sliders["300"].rightClicked.emit(0.5)
    assert tab.eq_sliders["300"].value() == 0
    assert config.get_eq_gain_300() == 0.0


def test_direct_reset_eq_band_call_matches_the_right_click_path(tab, config):
    """_reset_eq_band is what the keyboard-generalizable right-click signal
    routes to — pin it directly too, independent of the signal wiring."""
    config.set_eq_gain_8000(4.0)
    tab.eq_sliders["8000"].setValue(40)

    tab._reset_eq_band("8000")

    assert tab.eq_sliders["8000"].value() == 0
    assert config.get_eq_gain_8000() == 0.0


def test_balance_slider_right_click_resets_to_centered(tab, config):
    """L/R balance gets the same right-click-reset treatment as the EQ bands
    (2026-09-22) — single slider, no freq-key indirection needed."""
    config.set_balance(0.35)
    tab.balance_slider.setValue(35)

    tab.balance_slider.rightClicked.emit(0.5)

    assert tab.balance_slider.value() == 0
    assert config.get_balance() == 0.0
