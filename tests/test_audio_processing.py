"""Regression net for ``Player.apply_audio_processing`` and the EQ config accessors.

Written after mono/swap/balance were found completely broken (silent mpv -12 COMMAND
error, no console visibility beyond a bare print) because the code called mpv's
unqualified "pan" filter, which resolves to mpv's own NATIVE "pan" filter (legacy
MPlayer libaf, incompatible coefficient syntax) rather than ffmpeg's "pan" of the same
name — fixed by wrapping the filter string as "lavfi=[pan=...]" (see CLAUDE.md/player.py
comments). These tests exist to pin the exact filter strings issued for every
norm/mono/swap/balance/EQ combination so that class of silent breakage can't recur
without a test failing — no mpv, no QApplication, a fake ``instance`` capturing
``.command()`` calls, same pattern as test_smart_rewind.py / test_undo_position.py.
"""
import math

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from fabulor.config import Config
from fabulor.player import Player


class _FakeMpvInstance:
    """Minimal stand-in for python-mpv's Handle — only what apply_audio_processing touches."""
    def __init__(self):
        self.commands = []

    def command(self, *args):
        self.commands.append(args)


def make_player():
    p = Player(db=None, config=None)
    p.instance = _FakeMpvInstance()
    return p


def af_add_calls(player):
    """The ('af', 'add', <filter string>) calls, in issued order, filter string only."""
    return [c[2] for c in player.instance.commands if c[0] == 'af' and c[1] == 'add']


def test_all_flat_issues_no_af_add():
    p = make_player()
    p.apply_audio_processing()
    assert p.instance.commands == [('af', 'clr', '')]


def test_single_band_boosted():
    p = make_player()
    p.apply_audio_processing(eq_1000=3.0)
    assert af_add_calls(p) == ["equalizer=f=1000:width_type=o:width=2:g=3.0"]


def test_all_five_bands_distinct_values_ascending_order():
    p = make_player()
    p.apply_audio_processing(eq_100=1.0, eq_300=-2.5, eq_1000=6.0, eq_3000=-6.0, eq_8000=0.5)
    assert af_add_calls(p) == [
        "equalizer=f=100:width_type=o:width=2:g=1.0",
        "equalizer=f=300:width_type=o:width=2:g=-2.5",
        "equalizer=f=1000:width_type=o:width=2:g=6.0",
        "equalizer=f=3000:width_type=o:width=2:g=-6.0",
        "equalizer=f=8000:width_type=o:width=2:g=0.5",
    ]


def test_near_zero_gain_is_treated_as_flat_and_omitted():
    p = make_player()
    p.apply_audio_processing(eq_100=0.005, eq_1000=3.0)
    # 0.005 is within the same abs_tol=0.01 tolerance is_default uses in audio_controls.py —
    # must not emit a filter for a gain the UI itself would call "flat".
    assert af_add_calls(p) == ["equalizer=f=1000:width_type=o:width=2:g=3.0"]


def test_negative_gain_formatting():
    p = make_player()
    p.apply_audio_processing(eq_300=-4.5)
    assert af_add_calls(p) == ["equalizer=f=300:width_type=o:width=2:g=-4.5"]


def test_eq_plus_voice_boost_plus_balance_combined_order_and_math():
    p = make_player()
    p.apply_audio_processing(eq_1000=2.0, voice_boost=True, balance=-0.5)
    calls = af_add_calls(p)
    assert calls == [
        "equalizer=f=1000:width_type=o:width=2:g=2.0",
        "equalizer=f=500:width_type=o:width=2:g=3",
        "equalizer=f=2000:width_type=o:width=2:g=5",
        "equalizer=f=4000:width_type=o:width=2:g=3",
        "lavfi=[pan=stereo|c0=1.00*c0|c1=0.50*c1]",
    ]


def test_mono_still_overrides_swap_and_balance_with_eq_present():
    p = make_player()
    p.apply_audio_processing(eq_100=1.0, mono=True, swap=True, balance=0.5)
    calls = af_add_calls(p)
    assert calls == [
        "equalizer=f=100:width_type=o:width=2:g=1.0",
        "lavfi=[pan=mono|c0=0.5*c0+0.5*c1]",
    ]
    # No stereo pan filter alongside mono's.
    assert not any("pan=stereo" in c for c in calls)


def test_af_is_always_cleared_first():
    p = make_player()
    p.apply_audio_processing(eq_100=1.0)
    assert p.instance.commands[0] == ('af', 'clr', '')


# --- Config round-trips for the 5 new EQ gain keys ---
#
# QSettings isolation: QSettings.setDefaultFormat/setPath was found NOT to isolate on
# this platform/PySide6 build (confirmed live in test_sidebar_hotspot.py's module
# docstring — Config()'s hardcoded QSettings("Fabulor", "Fabulor") kept resolving to the
# real ~/.config/Fabulor/Fabulor.conf regardless). Reusing that file's verified-working
# fixture shape: monkeypatch fabulor.config.QSettings so Config()'s construction resolves
# to a throwaway tmp_path .ini file instead.

_EQ_FREQS = ["100", "300", "1000", "3000", "8000"]


@pytest.fixture
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def config(qapp, tmp_path, monkeypatch):
    ini_path = str(tmp_path / "test_audio_eq_settings.ini")

    class _IsolatedQSettings(QSettings):
        def __init__(self, *_args, **_kwargs):
            super().__init__(ini_path, QSettings.IniFormat)

    import fabulor.config as config_mod
    monkeypatch.setattr(config_mod, "QSettings", _IsolatedQSettings)
    return Config()


def test_eq_gain_defaults_to_flat(config):
    for freq in _EQ_FREQS:
        assert getattr(config, f"get_eq_gain_{freq}")() == 0.0


def test_eq_gain_set_get_round_trip(config):
    for i, freq in enumerate(_EQ_FREQS):
        value = 2.5 + i
        getattr(config, f"set_eq_gain_{freq}")(value)
        assert math.isclose(getattr(config, f"get_eq_gain_{freq}")(), value, abs_tol=1e-9)
