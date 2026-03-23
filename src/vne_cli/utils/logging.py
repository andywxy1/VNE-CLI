"""Structured logging setup for VNE-CLI."""

from __future__ import annotations

import logging
import sys


def setup_logging(*, verbose: bool = False) -> None:
    """Configure logging for the CLI.

    Args:
        verbose: If True, set level to DEBUG. Otherwise INFO.
    """
    level = logging.DEBUG if verbose else logging.INFO
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
    )

    root = logging.getLogger("vne_cli")
    root.setLevel(level)
    # Avoid duplicate handlers on repeated calls
    if not root.handlers:
        root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Get a logger namespaced under vne_cli.

    Args:
        name: Logger name (typically __name__ from the calling module).

    Returns:
        A configured logger.
    """
    return logging.getLogger(f"vne_cli.{name}")
