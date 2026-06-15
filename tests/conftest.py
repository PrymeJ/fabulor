"""Pytest configuration for Fabulor's test suite.

Puts ``src/`` on ``sys.path`` so tests can ``import fabulor.*`` without installing
the package (mirrors the pattern in ``tools/test_db.py``). Tests drive the Player's
seek-state machine directly with no mpv instance and no QApplication — see
``test_seek_state.py``.
"""
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
