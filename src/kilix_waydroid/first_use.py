"""First-use handoff to Plebian-OS's root-owned runtime installer."""

from __future__ import annotations

import sys
from typing import Iterable

from . import runtime, system


SYSTEM_INSTALLER = (
    "/usr/lib/plebian-os/waydroid/plebian-os-waydroid-setup"
)
_INSTALL_MANAGED_CHECKS = frozenset((
    "waydroid-command",
    "weston-command",
    "initialized",
))
_INSTALL_SIDE_EFFECT_CHECKS = frozenset(("container-service",))


def needed(checks: Iterable[system.Check]) -> bool:
    """Whether setup is needed and no unrelated required check blocks it."""
    failures = tuple(
        check for check in checks
        if check.required and check.status == "error"
    )
    managed = any(
        check.check_id in _INSTALL_MANAGED_CHECKS for check in failures
    )
    blockers = any(
        check.check_id not in _INSTALL_MANAGED_CHECKS
        and check.check_id not in _INSTALL_SIDE_EFFECT_CHECKS
        for check in failures
    )
    return managed and not blockers


def install(host_sdk) -> None:
    """Request the fixed Plebian-OS installer through Kilix's shared boundary."""
    print(
        "kilix-waydroid: Android and Weston need first-use setup "
        "(about a 1 GB download); opening the Plebian-OS installer",
        file=sys.stderr,
    )
    status = host_sdk.privilege.run_helper(
        SYSTEM_INSTALLER,
        title="Install Android + Weston (about 1 GB)",
    )
    if status != 0:
        raise runtime.LaunchError(
            "first-use setup was cancelled or failed "
            f"(status {status}); launch again to retry"
        )


__all__ = ["SYSTEM_INSTALLER", "install", "needed"]
