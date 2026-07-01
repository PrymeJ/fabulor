"""Application logging setup.

Configures the root ``fabulor`` logger once at startup with a rotating file
handler. File sink only — no stdout/console handler. Call ``setup_logging()``
as early as possible in the application entry point.

Log directory: ``platformdirs.user_log_dir("fabulor")``. See the NOTES.md
Windows-port entry for the one-arg vs two-arg ``platformdirs`` discrepancy.
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

import platformdirs

logger = logging.getLogger("fabulor")

_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s — %(message)s"
_VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}
_DEFAULT_LEVEL = logging.WARNING

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

    handler = RotatingFileHandler(
        log_dir / "fabulor.log",
        maxBytes=2 * 1024 * 1024,  # 2 MB
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))

    logger.setLevel(_resolve_level())
    logger.addHandler(handler)
    logger.propagate = False  # file sink only — do not leak to root/stderr

    _configured = True

    logger.warning("Fabulor started")
