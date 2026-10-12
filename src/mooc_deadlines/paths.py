from __future__ import annotations

import sys
from pathlib import Path


def project_root() -> Path:
    """Return the directory that owns local user data."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def resource_root() -> Path:
    """Return bundled read-only resources without mixing in local data."""
    bundle_root = getattr(sys, "_MEIPASS", None)
    return Path(bundle_root) if bundle_root else project_root()
