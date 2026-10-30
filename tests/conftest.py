"""Pytest configuration for Fabulor's test suite.

Puts ``src/`` on ``sys.path`` so tests can ``import fabulor.*`` without installing
the package (mirrors the pattern in ``tools/test_db.py``). Tests drive the Player's
seek-state machine directly with no mpv instance and no QApplication — see
``test_seek_state.py``.
"""
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture(autouse=True)
def _isolated_qsettings(tmp_path, monkeypatch):
    """Every Config() in every test reads and writes a throwaway INI file, never the
    real ~/.config/Fabulor/Fabulor.conf. QSettings.setDefaultFormat + setPath does NOT
    isolate here: Config builds QSettings("Fabulor", "Fabulor"), which always uses
    NativeFormat. Tests that relied on it wrote their values into the real config —
    found 2026-10-30, when every full-suite run left the Library in List view."""
    from PySide6.QtCore import QSettings
    import fabulor.config as config_mod

    ini_path = str(tmp_path / "isolated_settings.ini")

    class _IsolatedQSettings(QSettings):
        def __init__(self, *_args, **_kwargs):
            super().__init__(ini_path, QSettings.IniFormat)

    monkeypatch.setattr(config_mod, "QSettings", _IsolatedQSettings)
