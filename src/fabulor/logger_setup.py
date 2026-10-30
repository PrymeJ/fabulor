"""Application logging setup.

Configures the root ``fabulor`` logger once at startup with a rotating file
handler. File sink only — no stdout/console handler. Call ``setup_logging()``
as early as possible in the application entry point.

Log directory: ``platformdirs.user_log_dir("fabulor")``. See the NOTES.md
Windows-port entry for the one-arg vs two-arg ``platformdirs`` discrepancy.
"""

import logging
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

import platformdirs

logger = logging.getLogger("fabulor")

_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s — %(message)s"
_VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}
_DEFAULT_LEVEL = logging.WARNING

TRIPWIRE_FILE = "TRIPWIRES.txt"


def tripwire_path() -> Path:
    """In a source checkout, the repo root: an untracked file there shows up in `git status`
    and the editor's file tree, where it gets noticed. Otherwise, next to the logs."""
    repo = Path(__file__).resolve().parents[2]       # src/fabulor/logger_setup.py -> repo
    if (repo / ".git").exists():
        return repo / TRIPWIRE_FILE
    return Path(platformdirs.user_log_dir("fabulor")) / TRIPWIRE_FILE


def record_tripwire(tag: str, message: str) -> None:
    """Append one line to TRIPWIRES.txt (see tripwire_path). For a guard that catches a rare,
    unreproducible race: the regular log rotates within days and nobody reads it, so the
    catch goes to a file that never rotates, and the file existing at all is the evidence.
    TODO.md lists what to check it for. Never raises: a guard must not break the UI."""
    try:
        path = tripwire_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} [{tag}] {message}\n")
    except OSError as e:
        logger.warning(f"could not write tripwire [{tag}]: {e}")


# Guards against double-configuration if setup_logging() is called twice.
_configured = False


def _resolve_level() -> int:
    """Read FABULOR_LOG_LEVEL (case-insensitive), falling back to WARNING."""
    raw = os.environ.get("FABULOR_LOG_LEVEL", "").strip().upper()
    if raw in _VALID_LEVELS:
        return getattr(logging, raw)
    return _DEFAULT_LEVEL


def setup_logging() -> None:
    """Configure the ``fabulor`` root logger once. Idempotent."""
    global _configured
    if _configured:
        return

    log_dir = Path(platformdirs.user_log_dir("fabulor"))
    log_dir.mkdir(parents=True, exist_ok=True)

    # FABULOR_LOG_MAX_BYTES: override for bulk DEBUG-level capture sessions (e.g. repeated
    # cold-launch benchmarking) where the 2 MB production default rotates mid-run and silently
    # drops earlier samples. Unset in normal use — production default is unchanged.
    max_bytes = int(os.environ.get("FABULOR_LOG_MAX_BYTES", 2 * 1024 * 1024))
    handler = RotatingFileHandler(
        log_dir / "fabulor.log",
        maxBytes=max_bytes,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))

    logger.setLevel(_resolve_level())
    logger.addHandler(handler)
    logger.propagate = False  # file sink only — do not leak to root/stderr

    _configured = True

    logger.warning("Fabulor started")
