"""Read-only Waydroid and host readiness probes."""

from __future__ import annotations

import configparser
from dataclasses import asdict, dataclass
import gzip
import os
from pathlib import Path
import shutil
import subprocess
from typing import Callable, Iterable

from . import sdk


Run = Callable[..., subprocess.CompletedProcess]


@dataclass(frozen=True)
class Check:
    check_id: str
    status: str
    summary: str
    detail: str = ""
    required: bool = True

    def record(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class WaydroidStatus:
    running: bool
    session: str
    container: str = ""
    wayland_display: str = ""
    returncode: int = 0
    error: str = ""


def resolve_command(command: str) -> str | None:
    if not command:
        return None
    if os.path.isabs(command):
        return command if os.path.isfile(command) and os.access(command, os.X_OK) else None
    if os.sep in command or (os.path.altsep and os.path.altsep in command):
        return None
    return shutil.which(command)


def command_version(
    command: str,
    *,
    runner: Run = subprocess.run,
) -> str:
    try:
        result = runner(
            [command, "--version"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    lines = (result.stdout or "").strip().splitlines()
    return lines[0] if lines else ""


def parse_status(output: str, *, returncode: int = 0) -> WaydroidStatus:
    fields: dict[str, str] = {}
    for line in output.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip().casefold()] = value.strip()
    session = fields.get("session", "UNKNOWN").upper()
    return WaydroidStatus(
        running=session == "RUNNING",
        session=session,
        container=fields.get("container", "").upper(),
        wayland_display=fields.get("wayland display", ""),
        returncode=int(returncode),
        error="" if returncode == 0 else output.strip(),
    )


def waydroid_status(
    executable: str = "waydroid",
    *,
    runner: Run = subprocess.run,
) -> WaydroidStatus:
    try:
        result = runner(
            [executable, "--details-to-stdout", "status"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return WaydroidStatus(
            False, "UNKNOWN", returncode=127, error=str(error))
    return parse_status(result.stdout or "", returncode=result.returncode)


def _kernel_config() -> dict[str, str] | None:
    release = os.uname().release
    candidates = (
        Path(f"/boot/config-{release}"),
        Path("/proc/config.gz"),
    )
    for path in candidates:
        try:
            if path.suffix == ".gz":
                with gzip.open(path, "rt", encoding="utf-8") as handle:
                    lines = handle.readlines()
            else:
                lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        values = {}
        for line in lines:
            if line.startswith("CONFIG_") and "=" in line:
                key, value = line.split("=", 1)
                values[key] = value.rstrip("\r\n")
        return values
    return None


def _configured_binder_nodes(config: Path) -> tuple[str, ...]:
    names = ("binder", "vndbinder", "hwbinder")
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(config, encoding="utf-8")
        section = parser["waydroid"]
    except (OSError, KeyError, configparser.Error):
        return names
    return tuple(section.get(name, name).strip() or name for name in names)


def _binder_paths(names: Iterable[str]) -> tuple[str, ...]:
    missing = []
    for name in names:
        choices = (Path("/dev") / name, Path("/dev/binderfs") / name)
        if not any(path.exists() for path in choices):
            missing.append(name)
    return tuple(missing)


def _service_check(*, runner: Run) -> Check:
    if not shutil.which("systemctl"):
        return Check(
            "container-service",
            "warning",
            "systemd service state could not be checked",
            "Waydroid's container service must be available at launch.",
            required=False,
        )
    try:
        result = runner(
            ["systemctl", "is-active", "waydroid-container.service"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return Check(
            "container-service", "warning", "container service probe failed",
            str(error), required=False)
    state = (result.stdout or "").strip() or "unknown"
    if result.returncode == 0 and state == "active":
        return Check("container-service", "ok", "Waydroid container service is active")
    return Check(
        "container-service",
        "error",
        f"Waydroid container service is {state}",
        "Plebian-OS must enable and start waydroid-container.service.",
    )


def doctor_checks(
    *,
    waydroid: str = "waydroid",
    weston: str = "weston",
    workdir: str = "/var/lib/waydroid",
    require_display: bool = False,
    require_kilix: bool = False,
    runner: Run = subprocess.run,
) -> list[Check]:
    checks: list[Check] = []
    for check_id, command, label in (
        ("waydroid-command", waydroid, "Waydroid"),
        ("weston-command", weston, "Weston"),
    ):
        path = resolve_command(command)
        if path:
            version = command_version(path, runner=runner)
            detail = version or path
            checks.append(Check(check_id, "ok", f"{label} command is available", detail))
        else:
            checks.append(Check(
                check_id,
                "error",
                f"{label} command is missing",
                f"Plebian-OS first-use setup will install {command!r}.",
            ))

    host_sdk = None
    try:
        host_sdk = sdk.load("1.19")
    except sdk.SDKUnavailable as error:
        checks.append(Check("kilix-sdk", "error", "compatible Kilix SDK is missing", str(error)))
    else:
        checks.append(Check(
            "kilix-sdk",
            "ok",
            "Kilix nested-Wayland SDK is available",
            getattr(host_sdk.core, "SDK_VERSION", "1.19+"),
        ))

    root = Path(workdir)
    config = root / "waydroid.cfg"
    rootfs = root / "rootfs"
    if config.is_file() and rootfs.is_dir():
        checks.append(Check("initialized", "ok", "Waydroid is initialized"))
    else:
        checks.append(Check(
            "initialized",
            "error",
            "Waydroid is not initialized",
            "Plebian-OS first-use setup initializes the pinned Android images.",
        ))

    session_bus = bool(host_sdk and host_sdk.wayland.session_bus_address())
    checks.append(Check(
        "session-bus",
        "ok" if session_bus else "error",
        "user D-Bus session is available" if session_bus else "user D-Bus session is missing",
        "Waydroid needs an explicit session-bus address or an owned socket at "
        "$XDG_RUNTIME_DIR/bus; a compatible host SDK is required to resolve it."
        if not session_bus else "",
    ))

    kernel = _kernel_config()
    if kernel is None:
        checks.append(Check(
            "binder-kernel",
            "warning",
            "kernel Binder configuration could not be read",
            "Runtime Binder nodes are checked separately.",
            required=False,
        ))
    elif kernel.get("CONFIG_ANDROID_BINDER_IPC") in {"y", "m"}:
        checks.append(Check("binder-kernel", "ok", "kernel Android Binder IPC is enabled"))
    else:
        checks.append(Check(
            "binder-kernel",
            "error",
            "kernel Android Binder IPC is disabled",
            "Plebian-OS 0.2.2 needs a Binder-capable kernel.",
        ))

    missing_nodes = _binder_paths(_configured_binder_nodes(config))
    if missing_nodes:
        checks.append(Check(
            "binder-devices",
            "warning",
            "Binder device nodes are not currently present",
            "The root-owned Waydroid container service may create: " + ", ".join(missing_nodes),
            required=False,
        ))
    else:
        checks.append(Check("binder-devices", "ok", "configured Binder devices are present"))

    checks.append(_service_check(runner=runner))

    if require_display:
        display = os.environ.get("DISPLAY", "")
        checks.append(Check(
            "x-display",
            "ok" if display else "error",
            f"parent X display is {display}" if display else "parent X display is missing",
            "Use the pane command or launch from a Kilix desktop." if not display else "",
        ))

    if require_kilix:
        launcher = None
        home = os.environ.get("KILIX_HOME", "")
        if home:
            candidate = os.path.join(os.path.abspath(os.path.expanduser(home)), "kilix")
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                launcher = candidate
        launcher = launcher or shutil.which("kilix")
        checks.append(Check(
            "kilix-launcher",
            "ok" if launcher else "error",
            "Kilix launcher is available" if launcher else "Kilix launcher is missing",
            launcher or "The pane surface requires the Plebian-OS 0.2.2 Kilix host.",
        ))
    return checks


def required_failures(checks: Iterable[Check]) -> list[Check]:
    return [check for check in checks if check.required and check.status == "error"]


__all__ = [
    "Check",
    "WaydroidStatus",
    "command_version",
    "doctor_checks",
    "parse_status",
    "required_failures",
    "resolve_command",
    "waydroid_status",
]
