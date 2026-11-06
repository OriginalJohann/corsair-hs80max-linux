# corsair-hs80max-linux

GNOME integration for the **Corsair HS80 Max** headset: a background service that
reads connection status, battery level and microphone state from the wireless
USB dongle, plus a GNOME Shell extension that displays them in the top bar.

The HS80 Max has no standard USB battery reporting (no Battery SUD) — the
status is read from the dongle over a proprietary HID protocol on
`/dev/hidraw` (see `resources/battery-protocol.md`).

## Features

- **Connection status** – `disconnected`, `off` (dongle present, headset off)
  or `connected`
- **Battery level** – percentage, polled from the dongle (`-1` = unavailable)
- **Microphone state** – muted / unmuted
- **GNOME top-bar icons** – two symbolic icons (connection, microphone) to the
  left of the systray, plus battery percentage; clicking opens a detail popup
- **Volume mixer** – the connection icon opens `pavucontrol`
- **Live updates** – the extension refreshes whenever the service publishes a
  status change (via a watched status file), with a 1-minute fallback poll

## Architecture

```
┌─────────────────────┐         ┌──────────────────────────────┐
│  /dev/hidraw (dongle) │  HID   │  hs80max.service (Python)    │
│  1b1c:0a97, ifc. 4   │◄──────►│  systemd *user* daemon       │
└─────────────────────┘         │  • polls & decodes status    │
                                 │  • writes status.json        │
                                 │  • exposes D-Bus API         │
                                 └───────────┬──────────────────┘
                                             │ com.corsair.hs80max (session bus)
                                             ▼
                                 ┌──────────────────────────────┐
                                 │  GNOME extension             │
                                 │  hs80max@originaljohann.dev  │
                                 │  top-bar icons + popup UI    │
                                 └──────────────────────────────┘
```

| Component | Role |
|---|---|
| `service/hs80max_service/` | Python daemon (`pydbus`): HID protocol I/O, connection-mode detection, D-Bus API `com.corsair.hs80max` (properties `Mode`, `Battery`, `MicMuted`, `UpdatedAt`) and an atomically written `$XDG_RUNTIME_DIR/hs80max/status.json` that the extension watches. |
| `service/hs80max.service` | systemd user unit (started at login, `Restart=on-failure`). |
| `service/nixos/hs80max.nix` | NixOS module: udev rule, systemd user unit and the GNOME extension as a system-wide Nix package, in one option. |
| `extension/` | GNOME Shell extension (Shell 50) — D-Bus client + top-bar UI with symbolic icons. |
| `resources/` | Protocol research, datasheet and reference sources. |
| `shells/dev.nix` | Nix development shell (python3, pydbus, gi, dbus, wireplumber). |

## Requirements

- GNOME Shell **50** (e.g. NixOS 25.05) for the extension
- Python 3 with `pydbus` and `python3-gi` (bundled automatically on NixOS)
- The HS80 Max USB dongle (a service without dongle simply reports
  `disconnected`)
- `pavucontrol` for the volume-mixer shortcut

## Deployment

Two installation paths are provided:

### NixOS (flake module)

Add the repo as a flake input to your host flake and enable one option:

```nix
# flake.nix
inputs.corsair-hs80max-linux.url = "github:OriginalJohann/corsair-hs80max-linux";

# configuration.nix
modules = [ ... corsair-hs80max-linux.nixosModules.hs80max ];
services.hs80max.enable = true;   # installs service AND extension
```

Then run `nixos-rebuild switch` — the module installs the udev rule and the
systemd user unit, and the GNOME extension as a system-wide Nix package (no
D-Bus policy is needed: the default session policy already allows owning the
bus name). The user service is restarted automatically on every switch.
Afterwards enable the extension once via GNOME Settings → Extensions.

👉 **Full guide (flakes, local testing, verification, troubleshooting):**
[`NIXOS-SETUP.md`](./NIXOS-SETUP.md)

### Non-NixOS (install script)

```bash
./install.sh
```

The script checks for `python3`/`pydbus`/`gi`, then installs the udev rule to
`/etc/udev/rules.d/`, the D-Bus policy to `/etc/dbus-1/session.conf.d/`
(takes effect at next login), a systemd user unit (with a generated wrapper
pointing at this checkout) and the extension into
`~/.local/share/gnome-shell/extensions/`. Afterwards enable the extension once
and replug the dongle so the udev rule applies to its hidraw node.

## Verifying

```bash
systemctl --user status hs80max
journalctl --user -u hs80max -f
cat "$XDG_RUNTIME_DIR/hs80max/status.json"   # {"mode": "connected", "battery": 87, ...}

dbus-send --session --print-reply --dest=com.corsair.hs80max \
  /com/corsair/hs80max com.corsair.hs80max.GetStatus
```

Quick hardware check without the daemon (opens the dongle directly and
prints battery / mic status – useful to diagnose permission or udev issues):

```bash
PYTHONPATH=service python3 -m hs80max_service.hid_protocol
```

## Development

```bash
nix shell ./shells/dev.nix        # dev environment
./service/test_dbus.sh            # E2E D-Bus test
```

Extension testing: run a separate dev shell with
`dbus-run-session -- gnome-shell --devkit` so the real session is not
disturbed.

## Project layout

See [`STRUCTURE.md`](./STRUCTURE.md) for the full annotated file tree.

