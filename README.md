# Kilix Waydroid

Kilix Waydroid presents a Waydroid Android session inside a Kilix graphical
pane, a Kilix 95 application window, or an IceWM application window. It is a
Plebian-OS 0.2.2 application candidate. Its selected revision is currently a
provenance pin: managed application provisioning, catalog adoption and Android
target acceptance remain pending. Enabling it requires the matching host SDK
and OS provisioning.

Waydroid is a containerized Android runtime, not a CPU or hardware emulator.
Android therefore uses the host kernel and is available only on a compatible
Linux system.

## Architecture

The app does not implement another capture, input, process, or compositor
stack. Those responsibilities remain in the owning Kilix modules:

```text
Waydroid client
    │ private Wayland socket
    ▼
kilix_sdk.wayland (supervised Weston X11 backend)
    │ one ordinary X window
    ▼
Kilix run / Kilix 95 XPane / IceWM display
    │ existing Kilix capture + input path
    ▼
terminal pane or desktop window
```

`kilix_sdk.wayland.NestedWaylandSession` owns the private runtime directory,
Weston compatibility, startup readiness, global instance lock, client-first
shutdown, and preservation of the host audio sockets. `kilix_sdk.xapp`
continues to own the private X display, terminal frame presentation, and input
injection. This repository contains only Waydroid state checks, first-use
handoff, and launch policy.

## Commands

```bash
kilix-waydroid                 # choose the correct surface
kilix-waydroid pane            # present through kilix run
kilix-waydroid window          # use the current X display
kilix-waydroid doctor          # explain every prerequisite
kilix-waydroid doctor --json   # stable machine-readable report
kilix-waydroid status
kilix-waydroid stop            # explicit user-requested session stop
```

`--size WIDTHxHEIGHT` is accepted by `auto`, `pane`, and `window`. A pane with
no fixed size follows the provider-owned X display. `--no-install` makes a
launch diagnostic-only when the runtime is absent.

The default command chooses a pane when invoked from an ordinary Kilix terminal
and uses the current display when a Kilix desktop has already created an XPane
or IceWM window surface.

## Runtime contract

The Plebian-OS image must provide:

- Kilix SDK 1.19 or newer;
- a Binder-capable kernel and the Waydroid Binder devices;
- a user D-Bus session, xterm, and sudo;
- the installed Kilix private-bus supervisor and its systemd/polkit boundary; and
- the root-owned Plebian-OS Waydroid installer closure.

On the first real launch, missing Waydroid, Weston, or Android initialization
or an inactive container service causes the app to request the fixed
Plebian-OS installer through `kilix_sdk.privilege`, with explicit confirmation
before elevation. A terminal launch uses its current terminal; Kilix 95,
IceWM, and other graphical launches open the prompt and progress in `xterm`
inside their existing X surface. The app then reruns its complete read-only
preflight and starts Android only if every required check passes. Cancellation
or failure leaves no success marker, so the next launch offers a clean retry.
An unrelated blocker such as an incompatible Binder kernel or missing session
bus is reported before any installation is requested.

The app itself never adds repositories, chooses packages, downloads images,
or runs `waydroid init`. Those operations remain in one root-owned,
release-pinned Plebian-OS helper. `doctor`, `status`, and `stop` never install.

Only one Kilix Waydroid session may run at a time. Launch refuses to rebind an
already-running external Waydroid session to a different compositor. Closing
the Kilix pane or desktop window terminates the session process started by that
window; an unrelated pre-existing session is never stopped implicitly.

## Desktop integration

[`packaging/kilix-content.json`](packaging/kilix-content.json) is the shared
schema-3 catalog record. It declares a system application with `xpane` launch
mode and single-instance lifecycle. Once the Plebian-OS 0.2.2 catalog consumes
that record, the existing generic application menus expose it in both Kilix 95
and IceWM without provider-specific launch code.

## Development

Point the app at the matching Kilix worktree that exports SDK 1.19, then run:

```bash
export KILIX_HOME=/path/to/kilix
make test
make check
./kilix-waydroid --version
./kilix-waydroid doctor
```

The unit suite does not require Waydroid or Weston. A full host smoke test does,
and `doctor` is expected to fail clearly on a machine where the required
runtime packages and Android images have not been installed. The currently
selected OS first-use closure targets AMD64; ARM64 requires separately selected
and qualified runtime artifacts.

`make install PREFIX=/usr/local` installs the launcher and its standard-library
Python package. Plebian-OS separately stages the immutable first-use closure.

The optional ownership tests use fixture executables, not Android or Weston:

```bash
TMPDIR=/tmp KILIX_WAYDROID_TEST_KILIX_HOME=/path/to/kilix make test
```

They require the installed host containment service matching the SDK source.
They cover real process ownership and descendant cleanup, not Android graphics,
audio, input, first-use downloads, or physical/ISO acceptance.

## License

Kilix Waydroid is licensed under GPL-3.0-or-later. Waydroid and Weston are
external system programs and are not vendored here; see
[`THIRD-PARTY-NOTICES.md`](THIRD-PARTY-NOTICES.md).
