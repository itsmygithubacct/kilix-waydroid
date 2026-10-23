"""Command-line surfaces for Kilix Waydroid."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from . import __version__, first_use, runtime, sdk, system


DEFAULT_SIZE = (960, 600)


def parse_size(value: str) -> tuple[int, int]:
    try:
        width, height = (int(part) for part in value.lower().split("x", 1))
    except (TypeError, ValueError) as error:
        raise argparse.ArgumentTypeError("size must be WIDTHxHEIGHT") from error
    if not 320 <= width <= 16384 or not 240 <= height <= 16384:
        raise argparse.ArgumentTypeError(
            "size must be between 320x240 and 16384x16384"
        )
    return width, height


def _surface_parser(subparsers, name: str, help_text: str):
    parser = subparsers.add_parser(name, help=help_text)
    parser.add_argument("--size", type=parse_size, metavar="WIDTHxHEIGHT")
    parser.add_argument("--waydroid", default="waydroid", metavar="COMMAND")
    parser.add_argument("--weston", default="weston", metavar="COMMAND")
    parser.add_argument(
        "--no-install",
        action="store_false",
        dest="install",
        help="do not run Plebian-OS first-use setup when the runtime is absent",
    )
    return parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kilix-waydroid",
        description="present an owned Waydroid Android session through Kilix",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="action", required=True)
    _surface_parser(subparsers, "auto", "choose a Kilix pane or current desktop window")
    _surface_parser(subparsers, "pane", "open Android through `kilix run`")
    window = _surface_parser(subparsers, "window", "use the current X display")
    window.add_argument(
        "--fit-parent",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    doctor = subparsers.add_parser("doctor", help="report launch prerequisites")
    doctor.add_argument("--json", action="store_true", dest="json_output")
    doctor.add_argument("--waydroid", default="waydroid", metavar="COMMAND")
    doctor.add_argument("--weston", default="weston", metavar="COMMAND")
    status = subparsers.add_parser("status", help="show the current Waydroid session")
    status.add_argument("--json", action="store_true", dest="json_output")
    status.add_argument("--waydroid", default="waydroid", metavar="COMMAND")
    stop = subparsers.add_parser("stop", help="explicitly stop the current Waydroid session")
    stop.add_argument("--waydroid", default="waydroid", metavar="COMMAND")
    return parser


def _launcher() -> str:
    configured = os.environ.get("KILIX_WAYDROID_LAUNCHER", "")
    if configured and os.path.isfile(configured) and os.access(configured, os.X_OK):
        return os.path.abspath(configured)
    executable = shutil.which("kilix-waydroid")
    if executable:
        return executable
    candidate = Path(sys.argv[0]).resolve()
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate)
    raise runtime.LaunchError("cannot locate the kilix-waydroid launcher for pane re-entry")


def _kilix_launcher(host_sdk) -> str:
    candidate = host_sdk.paths.launcher()
    if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
        return candidate
    executable = shutil.which("kilix")
    if executable:
        return executable
    raise runtime.LaunchError("the Kilix launcher is required for the pane surface")


def _print_checks(checks: list[system.Check]) -> None:
    marks = {"ok": "OK", "warning": "WARN", "error": "FAIL"}
    for check in checks:
        print(f"{marks.get(check.status, check.status.upper()):4}  {check.summary}")
        if check.detail:
            print(f"      {check.detail}")


def _preflight(
    *,
    host_sdk=None,
    lazy_install: bool = False,
    **kwargs,
) -> list[system.Check]:
    checks = system.doctor_checks(**kwargs)
    stock_commands = (
        kwargs.get("waydroid", "waydroid") == "waydroid"
        and kwargs.get("weston", "weston") == "weston"
    )
    if lazy_install and stock_commands and first_use.needed(checks):
        if host_sdk is None:
            raise runtime.LaunchError("first-use setup requires the Kilix host SDK")
        first_use.install(host_sdk)
        checks = system.doctor_checks(**kwargs)
    failures = system.required_failures(checks)
    if failures:
        _print_checks(failures)
        raise runtime.LaunchError("launch prerequisites are not satisfied")
    return checks


def _run_window(args) -> int:
    host_sdk = sdk.load("1.19")
    _preflight(
        host_sdk=host_sdk,
        lazy_install=getattr(args, "install", True),
        waydroid=args.waydroid,
        weston=args.weston,
        require_display=True,
    )
    waydroid = system.resolve_command(args.waydroid) or args.waydroid
    weston = system.resolve_command(args.weston) or args.weston
    if args.fit_parent:
        width, height = host_sdk.xapp.display_size()
    else:
        width, height = args.size or DEFAULT_SIZE
    return runtime.run_window(
        host_sdk,
        width=width,
        height=height,
        waydroid=waydroid,
        weston=weston,
    )


def _run_pane(args) -> int:
    host_sdk = sdk.load("1.19")
    _preflight(
        host_sdk=host_sdk,
        lazy_install=getattr(args, "install", True),
        waydroid=args.waydroid,
        weston=args.weston,
        require_kilix=True,
    )
    command = [_kilix_launcher(host_sdk), "run"]
    if args.size:
        command.append(f"--size={args.size[0]}x{args.size[1]}")
    command.extend(["--refit-windows", _launcher(), "window"])
    if args.size:
        command.extend(["--size", f"{args.size[0]}x{args.size[1]}"])
    else:
        command.append("--fit-parent")
    command.extend(["--waydroid", args.waydroid, "--weston", args.weston])
    if not getattr(args, "install", True):
        command.append("--no-install")
    os.execvpe(command[0], command, dict(os.environ))
    return 1


def _auto_surface() -> str:
    if os.environ.get("DISPLAY") and (
        os.environ.get("KILIX_IN_OVERLAY") == "1"
        or os.environ.get("KILIX_APP_SURFACE") == "window"
    ):
        return "window"
    if os.environ.get("KITTY_WINDOW_ID"):
        return "pane"
    return "window" if os.environ.get("DISPLAY") else "pane"


def _doctor(args) -> int:
    checks = system.doctor_checks(waydroid=args.waydroid, weston=args.weston)
    if args.json_output:
        print(json.dumps({
            "schema_version": 1,
            "checks": [check.record() for check in checks],
            "ready": not system.required_failures(checks),
        }, indent=2, sort_keys=True))
    else:
        _print_checks(checks)
    return 1 if system.required_failures(checks) else 0


def _status(args) -> int:
    status = system.waydroid_status(args.waydroid)
    record = {
        "running": status.running,
        "session": status.session,
        "container": status.container,
        "wayland_display": status.wayland_display,
        "returncode": status.returncode,
        "error": status.error,
    }
    if args.json_output:
        print(json.dumps(record, indent=2, sort_keys=True))
    elif status.returncode != 0:
        print(status.error or "could not read Waydroid status", file=sys.stderr)
    else:
        print(f"Session: {status.session}")
        if status.container:
            print(f"Container: {status.container}")
        if status.wayland_display:
            print(f"Wayland display: {status.wayland_display}")
    return 0 if status.returncode == 0 else 1


def _stop(args) -> int:
    executable = system.resolve_command(args.waydroid)
    if not executable:
        raise runtime.LaunchError(f"Waydroid command is missing: {args.waydroid}")
    result = subprocess.run(
        [executable, "--details-to-stdout", "session", "stop"],
        check=False,
    )
    return int(result.returncode)


def main(argv: list[str] | None = None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)
    if not values:
        values = ["auto"]
    try:
        args = build_parser().parse_args(values)
        action = args.action
        if action == "auto":
            action = _auto_surface()
        if action == "window":
            if not hasattr(args, "fit_parent"):
                args.fit_parent = False
            return _run_window(args)
        if action == "pane":
            return _run_pane(args)
        if action == "doctor":
            return _doctor(args)
        if action == "status":
            return _status(args)
        if action == "stop":
            return _stop(args)
        raise runtime.LaunchError(f"unsupported action: {action}")
    except runtime.LaunchInterrupted as interrupted:
        return 128 + interrupted.signum
    except (
        OSError,
        RuntimeError,
        sdk.SDKUnavailable,
    ) as error:
        print(f"kilix-waydroid: {error}", file=sys.stderr)
        return 1


__all__ = ["build_parser", "main", "parse_size"]
