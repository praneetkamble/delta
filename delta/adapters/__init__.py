from __future__ import annotations

import logging
import sys

from .base import Adapter, AdapterError, DEFAULT_APPS, APP_PROCESSES

log = logging.getLogger("delta")


def get_adapter(config) -> Adapter:
    choice = str(config.get("adapter", "auto")).lower()
    if choice == "windows" or (choice == "auto" and sys.platform == "win32"):
        from .windows import WindowsAdapter
        return WindowsAdapter()
    from .mock import MockAdapter
    if choice == "auto":
        log.warning("Not running on Windows: using the MOCK adapter (nothing real is controlled).")
    return MockAdapter(trash_dir=config.data_dir / "mock_trash", demo_motion=True)  # demo: gently moving simulated vitals


__all__ = ["Adapter", "AdapterError", "DEFAULT_APPS", "APP_PROCESSES", "get_adapter"]
