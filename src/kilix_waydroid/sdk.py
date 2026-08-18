"""Load the host-owned Kilix SDK without copying its implementation."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import os
from pathlib import Path
import sys


class SDKUnavailable(RuntimeError):
    """The required host SDK cannot be imported or is too old."""


@dataclass(frozen=True)
class KilixSDK:
    core: object
    paths: object
    privilege: object
    wayland: object
    xapp: object


def _host_config() -> str | None:
    root = os.environ.get("KILIX_HOME", "")
    if not root:
        return None
    candidate = Path(os.path.abspath(os.path.expanduser(root))) / "config"
    return str(candidate) if candidate.is_dir() else None


def load(required: str = "1.16") -> KilixSDK:
    """Return the compatible SDK exported by the active Kilix host."""
    config = _host_config()
    if config and config not in sys.path:
        sys.path.insert(0, config)
    try:
        core = importlib.import_module("kilix_sdk")
        core.require_compatible(required)
        return KilixSDK(
            core=core,
            paths=importlib.import_module("kilix_sdk.paths"),
            privilege=importlib.import_module("kilix_sdk.privilege"),
            wayland=importlib.import_module("kilix_sdk.wayland"),
            xapp=importlib.import_module("kilix_sdk.xapp"),
        )
    except (ImportError, ModuleNotFoundError, RuntimeError) as error:
        raise SDKUnavailable(
            f"kilix_sdk {required} or newer is required; launch through the "
            "Plebian-OS 0.2.0 Kilix host"
        ) from error


__all__ = ["KilixSDK", "SDKUnavailable", "load"]
