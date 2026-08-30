"""Read-only Waydroid and host readiness probes.

Every host surface these probes touch is reached through :class:`Host`, so a
test can seal the whole world the probes see into one directory and prove the
read-only guarantee by construction rather than by inspection.  That guarantee
is the point of this module: `doctor` and `status` mirror the OS helper's
``--verify`` contract and must never install, elevate, or write.
"""

from __future__ import annotations

import configparser
from dataclasses import asdict, dataclass, field, replace
import gzip
import os
from pathlib import Path
import shutil
import subprocess
from types import MappingProxyType
from typing import Callable, Iterable, Mapping

from . import sdk


Run = Callable[..., subprocess.CompletedProcess]

REQUIRED_SDK = "1.17"

#: Paths the application must never write.  Named here so the non-installing
#: proof asserts the design document's own list rather than a paraphrase.
PROTECTED_ROOTS = (
    "/usr",
    "/var/lib/waydroid",
    "/usr/share/waydroid-extra",
    "/etc/modprobe.d",
    "/etc/modules-load.d",
)


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

    def record(self) -> dict[str, object]:
        return asdict(self)


def _environment() -> Mapping[str, str]:
    return MappingProxyType(dict(os.environ))


@dataclass(frozen=True)
class Host:
    """The complete host surface the read-only probes are allowed to read."""

    workdir: str = "/var/lib/waydroid"
    dev_root: str = "/dev"
    boot_root: str = "/boot"
    proc_config: str = "/proc/config.gz"
    runtime_root: str = "/run/user"
    release: str = field(default_factory=lambda: os.uname().release)
    uid: int = field(default_factory=os.getuid)
    environ: Mapping[str, str] = field(default_factory=_environment)
    runner: Run = subprocess.run
    which: Callable[[str], str | None] = shutil.which
    load_sdk: Callable[[str], object] = sdk.load

    def sealed(self, root: str) -> "Host":
        """Return a view whose every path lives under ``root``."""
        base = Path(root)
        return replace(
            self,
            workdir=str(base / "var/lib/waydroid"),
            dev_root=str(base / "dev"),
            boot_root=str(base / "boot"),
            proc_config=str(base / "proc/config.gz"),
            runtime_root=str(base / "run/user"),
        )


def resolve_command(command: str, *, which: Callable[[str], str | None] = shutil.which) -> str | None:
    if not command:
        return None
    if os.path.isabs(command):
        return command if os.path.isfile(command) and os.access(command, os.X_OK) else None
    if os.sep in command or (os.path.altsep and os.path.altsep in command):
        return None
    return which(command)


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
    return (result.stdout or "").strip().splitlines()[0] if result.returncode == 0 else ""


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
    """Ask Waydroid for its session state. This reads; it never starts anything."""
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


def _kernel_config(host: Host) -> dict[str, str] | None:
    candidates = (
        Path(host.boot_root) / f"config-{host.release}",
        Path(host.proc_config),
    )
    for path in candidates:
        try:
            if path.suffix == ".gz":
                with gzip.open(path, "rt", encoding="utf-8") as handle:
                    lines = handle.readlines()
            else:
                lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, EOFError, gzip.BadGzipFile):
            continue
        values = {}
        for line in lines:
            if line.startswith("CONFIG_") and "=" in line:
                key, value = line.split("=", 1)
                values[key] = value.strip()
        return values
    return None


def configured_binder_nodes(config: Path) -> tuple[str, ...]:
    """Follow the helper's configured device names rather than the legacy trio."""
    names = ("binder", "vndbinder", "hwbinder")
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(config, encoding="utf-8")
        section = parser["waydroid"]
    except (OSError, KeyError, configparser.Error):
        return names
    return tuple(section.get(name, name).strip() or name for name in names)


def _missing_binder_nodes(names: Iterable[str], *, dev_root: str) -> tuple[str, ...]:
    root = Path(dev_root)
    missing = []
    for name in names:
        choices = (root / name, root / "binderfs" / name)
        if not any(path.exists() for path in choices):
            missing.append(name)
    return tuple(missing)


def _initialized(host: Host) -> bool:
    root = Path(host.workdir)
    return (root / "waydroid.cfg").is_file() and (root / "rootfs").is_dir()


def _service_check(host: Host) -> Check:
    systemctl = host.which("systemctl")
    if not systemctl:
        return Check(
            "container-service",
            "warning",
            "systemd service state could not be checked",
            "Waydroid's container service must be available at launch.",
            required=False,
        )
    try:
        result = host.runner(
            [systemctl, "is-active", "waydroid-container.service"],
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


def _audio_check(host: Host) -> Check:
    """Report the host audio runtime the nested session will reuse."""
    runtime = host.environ.get("XDG_RUNTIME_DIR", "")
    if not runtime or not os.path.isabs(runtime):
        return Check(
            "audio-runtime",
            "warning",
            "host audio runtime directory is not set",
            "Android audio reuses the session's existing PipeWire or PulseAudio "
            "sockets; without XDG_RUNTIME_DIR there is nothing to carry across.",
            required=False,
        )
    if host.environ.get("PIPEWIRE_RUNTIME_DIR") or os.path.exists(
        os.path.join(runtime, "pipewire-0")
    ):
        return Check("audio-runtime", "ok", "PipeWire session audio is available")
    if host.environ.get("PULSE_RUNTIME_PATH") or os.path.isdir(
        os.path.join(runtime, "pulse")
    ):
        return Check("audio-runtime", "ok", "PulseAudio session audio is available")
    return Check(
        "audio-runtime",
        "warning",
        "no session audio socket was found",
        "Android will start without sound until the session audio service runs.",
        required=False,
    )


def doctor_checks(
    *,
    waydroid: str = "waydroid",
    weston: str = "weston",
    host: Host | None = None,
    require_display: bool = False,
    require_kilix: bool = False,
) -> list[Check]:
    """Probe every launch prerequisite. Reads only; installs and writes nothing."""
    host = host or Host()
    checks: list[Check] = []
    for check_id, command, label in (
        ("waydroid-command", waydroid, "Waydroid"),
        ("weston-command", weston, "Weston"),
    ):
        path = resolve_command(command, which=host.which)
        if path:
            version = command_version(path, runner=host.runner)
            detail = version or path
            checks.append(Check(check_id, "ok", f"{label} command is available", detail))
        else:
            checks.append(Check(
                check_id,
                "error",
                f"{label} command is missing",
                f"Plebian-OS first-use setup will install {command!r}.",
            ))

    try:
        host_sdk = host.load_sdk(REQUIRED_SDK)
    except sdk.SDKUnavailable as error:
        checks.append(Check("kilix-sdk", "error", "compatible Kilix SDK is missing", str(error)))
    else:
        checks.append(Check(
            "kilix-sdk",
            "ok",
            "Kilix nested-Wayland SDK is available",
            getattr(getattr(host_sdk, "core", None), "SDK_VERSION", f"{REQUIRED_SDK}+"),
        ))

    root = Path(host.workdir)
    config = root / "waydroid.cfg"
    initialized = _initialized(host)
    if initialized:
        checks.append(Check("initialized", "ok", "Waydroid is initialized"))
    else:
        checks.append(Check(
            "initialized",
            "error",
            "Waydroid is not initialized",
            "Plebian-OS first-use setup initializes the pinned Android images.",
        ))

    session_bus = bool(host.environ.get("DBUS_SESSION_BUS_ADDRESS")) or Path(
        host.runtime_root, str(host.uid), "bus").exists()
    checks.append(Check(
        "session-bus",
        "ok" if session_bus else "error",
        "user D-Bus session is available" if session_bus else "user D-Bus session is missing",
        "Waydroid manages its user session over D-Bus." if not session_bus else "",
    ))

    kernel = _kernel_config(host)
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
            "Plebian-OS 0.2.0 needs a Binder-capable kernel.",
        ))

    missing_nodes = _missing_binder_nodes(
        configured_binder_nodes(config), dev_root=host.dev_root
    )
    if not missing_nodes:
        checks.append(Check("binder-devices", "ok", "configured Binder devices are present"))
    elif initialized:
        # Once first-use setup has run, nothing else is going to create these.
        # Reporting them as a warning here would conceal a launch failure, which
        # is precisely what the read-only contract forbids.
        checks.append(Check(
            "binder-devices",
            "error",
            "Binder device nodes are absent: " + ", ".join(missing_nodes),
            "The installed runtime configures binder_linux to expose these at "
            "boot. Reboot, or re-run Plebian-OS Waydroid setup, before launching.",
        ))
    else:
        checks.append(Check(
            "binder-devices",
            "warning",
            "Binder device nodes are not currently present",
            "Plebian-OS first-use setup loads binder_linux and creates: "
            + ", ".join(missing_nodes),
            required=False,
        ))

    checks.append(_service_check(host))
    checks.append(_audio_check(host))

    if require_display:
        display = host.environ.get("DISPLAY", "")
        checks.append(Check(
            "x-display",
            "ok" if display else "error",
            f"parent X display is {display}" if display else "parent X display is missing",
            "Use the pane command or launch from a Kilix desktop." if not display else "",
        ))

    if require_kilix:
        launcher = None
        home = host.environ.get("KILIX_HOME", "")
        if home:
            candidate = os.path.join(os.path.abspath(os.path.expanduser(home)), "kilix")
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                launcher = candidate
        launcher = launcher or host.which("kilix")
        checks.append(Check(
            "kilix-launcher",
            "ok" if launcher else "error",
            "Kilix launcher is available" if launcher else "Kilix launcher is missing",
            launcher or "The pane surface requires the Plebian-OS Kilix host.",
        ))
    return checks


def required_failures(checks: Iterable[Check]) -> list[Check]:
    return [check for check in checks if check.required and check.status == "error"]


__all__ = [
    "Check",
    "Host",
    "PROTECTED_ROOTS",
    "REQUIRED_SDK",
    "WaydroidStatus",
    "command_version",
    "configured_binder_nodes",
    "doctor_checks",
    "parse_status",
    "required_failures",
    "resolve_command",
    "waydroid_status",
]
