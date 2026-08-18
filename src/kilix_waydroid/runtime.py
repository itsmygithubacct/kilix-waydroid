"""Waydroid-specific orchestration on the host-owned Wayland bridge."""

from __future__ import annotations

from contextlib import contextmanager
import os
import signal
import subprocess

from . import system


class LaunchError(RuntimeError):
    """The Android session could not safely be presented."""


class LaunchInterrupted(BaseException):
    def __init__(self, signum: int):
        self.signum = int(signum)
        super().__init__(f"interrupted by signal {self.signum}")


@contextmanager
def cleanup_signals():
    """Turn terminating signals into stack unwinds so SDK cleanup always runs."""
    previous = {}

    def interrupt(signum, _frame):
        raise LaunchInterrupted(signum)

    for signum in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        previous[signum] = signal.getsignal(signum)
        signal.signal(signum, interrupt)
    try:
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def run_window(
    host_sdk,
    *,
    width: int,
    height: int,
    waydroid: str,
    weston: str,
) -> int:
    """Run one owned Waydroid session until its Weston window closes."""
    session_name = f"waydroid-{os.getpid()}"
    with cleanup_signals(), host_sdk.wayland.NestedWaylandSession(
        session_name,
        exclusive="waydroid",
    ) as nested:
        before = system.waydroid_status(waydroid)
        if before.returncode != 0:
            raise LaunchError(
                "could not determine Waydroid session state before launch; "
                "run `kilix-waydroid doctor`"
            )
        if before.running:
            display = f" on {before.wayland_display}" if before.wayland_display else ""
            raise LaunchError(
                "a Waydroid session is already running" + display + "; stop it "
                "explicitly before moving Android into a new Kilix surface"
            )

        nested.start_x11(width, height, executable=weston)
        debug = os.environ.get("KILIX_WAYDROID_DEBUG") == "1"
        output = None if debug else subprocess.DEVNULL
        command = [waydroid]
        if debug:
            command.append("--details-to-stdout")
        command.append("show-full-ui")
        client = nested.launch_client(
            "waydroid",
            command,
            stdout=output,
            stderr=output,
        )
        exited = nested.wait(client)
        if exited.source == "compositor":
            if exited.returncode != 0:
                diagnostic = nested.compositor_diagnostic()
                suffix = f": {diagnostic}" if diagnostic else ""
                raise LaunchError(
                    f"nested Wayland window exited with rc={exited.returncode}{suffix}"
                )
            return 0
        if exited.returncode != 0:
            raise LaunchError(
                f"Waydroid session exited with rc={exited.returncode}; run `waydroid log`"
            )
        after = system.waydroid_status(waydroid)
        if after.running:
            raise LaunchError(
                "Waydroid attached to a session outside this Kilix window; "
                "stop that session explicitly and try again"
            )
        raise LaunchError(
            "Waydroid ended before the Android window closed; run `waydroid log`"
        )


__all__ = ["LaunchError", "LaunchInterrupted", "cleanup_signals", "run_window"]
