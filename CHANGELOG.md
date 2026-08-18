# Changelog

## 0.2.0 — unreleased

- Add automatic Kilix pane and desktop-window presentation for Waydroid.
- Use the Kilix SDK 1.16 nested-Wayland and trusted-helper lifecycle rather than
  app-local capture, input, compositor, privilege, or process glue.
- Add prerequisite diagnostics, explicit status/stop commands, global
  single-instance protection, and a shared schema-3 desktop catalog record.
- Lazily request the root-owned, release-pinned Plebian-OS Waydroid and Weston
  installer on the first real launch, then rerun the complete preflight.
- Keep all package selection, download verification, image initialization, and
  privileged device setup in the Plebian-OS 0.2.0 release layer.
