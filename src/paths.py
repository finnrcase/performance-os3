"""Shared filesystem paths for local and hosted deployments."""

from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def data_root() -> Path:
    """Return the writable data directory.

    Local development uses ``data/`` in the repository. Hosted backends can set
    ``PERFORMANCE_OS_DATA_DIR`` to a mounted persistent volume.
    """
    configured = os.getenv("PERFORMANCE_OS_DATA_DIR", "").strip()
    return Path(configured).expanduser() if configured else PROJECT_ROOT / "data"


def processed_data_path(filename: str) -> Path:
    return data_root() / "processed" / filename


def raw_data_path(*parts: str) -> Path:
    return data_root() / "raw" / Path(*parts)
