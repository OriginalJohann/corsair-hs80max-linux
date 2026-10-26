# Development Plan: Corsair HS80 Max – GNOME Extension & Background Service

## 1. Analysis Results (Live Hardware, Verified)

| Finding | Detail |
|---|---|
| **Dongle** | `Bus 001 Dev 004`, ID `1b1c:0a97`, serial `52712A9DFF4EF01A`, High-Speed |
| **Interfaces** | 0: AudioControl · 1–2: AudioStreaming (Sink + Mic) · **3: HID** (IN EP `0x84`, descriptor 147 B) · **4: HID** (OUT EP `0x02` + IN EP `0x83`, descriptor 54 B) |
| **Battery** | ⚠️ **No USB Battery SUD** – `/sys/class/power_supply/` is empty. → The HID protocol (iCUE interface) must be analyzed |
| **PipeWire** | Device 55 „CORSAIR HS80 MAX WIRELESS Gaming Receiver" with active sink (IEC958) + mono source |
| **Environment** | NixOS, GNOME Shell 50.4, Python 3.14, `pavucontrol` available, `nix-shell` available |

**Conclusion:** Battery reporting comes via the proprietary HID interface (likely interface 3, report descriptor 147 B). A targeted **protocol analysis** is required (report capture + correlation), as no official docs exist.

## 2. Target Architecture

```
┌─────────────────────────────┐      D-Bus (Session Bus)       ┌──────────────────────────────┐
│ hs80max-service (Python)    │ ◄────────────────────────────► │ GNOME Extension (Shell 50)   │
│ · Battery (HID reports)     │   com.corsair.hs80max            │ · Tray icon + tooltip        │
│ · Connection mode           │   GetBattery(), GetStatus()      │ · Popup with details         │
│ · Device watchdog (USB/WP)  │   signals: StatusChanged         │ · Menu → pavucontrol         │
└─────────────────────────────┘                                  └──────────────────────────────┘
```

## 3. Phase Plan

### Phase 0 – Setup & Protocol Analysis
- [x] Create directory structure: `./ressources/`, `./shells/`, `./plans/`, `./scratchpad/` + `STRUCTURE.md`
- [x] `shells/dev.nix` – Nix shell with `python3`, `pyusb`/`python3Packages.hidapi`, `dbus`, `pipewire-tools`, `usbutils`
- [x] **HID protocol analysis** (core piece):
  - [x] Map `hidrawN` → USB interface: `hidraw0` = IF3 (telemetry), `hidraw1` = IF4 (control, 1b1c:0a97)
  - [x] Report descriptor unavailable in sysfs → protocol from reference implementation
  - [x] Web/GitHub research: **`Sapd/HeadsetControl`** supports `0x0a97` with battery → protocol fully documented in `./ressources/battery-protocol.md`
  - [x] Correlation test: **PENDING LIVE TEST** (blocked by hidraw permissions, see below)
- [x] Verify connection-mode detection: cable mode = second USB audio device (HS80 MAX USB-C) appears in PipeWire (design verified, live test pending)

### ⚠️ BLOCKER: hidraw permissions
`/dev/hidraw0|1` are `root:root 0600`; sudo requires a password. User must add a udev rule
(NixOS `services.udev.extraRules`):
```
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="1b1c", ATTRS{idProduct}=="0a97", MODE="0660", GROUP="users"
```

### ⚠️ BLOCKER: D-Bus session policy
`com.corsair.hs80max` cannot be owned on the session bus (AccessDenied).
Policy file created: `service/dbus/com.corsair.hs80max.conf`.
User must add to NixOS config and rebuild (restarts the session D-Bus daemon):
```nix
services.dbus.enable = true;
# (or copy the .conf into /run/current-system/sw/lib/dbus-1/session.conf.d/)
```

### Phase 1 – Background Service (`./service/`)
- [x] Python daemon: HID battery polling, connection-mode detection (dongle vs. USB-C device in PipeWire), status state
- [x] **D-Bus API** on the session bus: `com.corsair.hs80max` with `GetBattery()`, `GetStatus()`, `GetMicMuted()`, signal `StatusChanged`
- [x] Clean logging (`logging`), signal handling (SIGTERM/SIGINT), fault-tolerant polling on device removal
- [x] NixOS module (`service/nixos/hs80max.nix`): udev rule + D-Bus session policy + user service
- [x] systemd user unit (`service/hs80max.service`) – references `hs80max-service` wrapper
- [ ] Live test with real hardware (blocked by hidraw permissions – user action needed)

### Phase 2 – GNOME Extension (`./extension/`)
- [x] Extension for Shell 50: `metadata.json`, `main.js`
- [x] **Tray icon** with status glyph (wired/wireless/disconnected) + battery percent in tooltip
- [x] **Popup** (click): battery level, connection mode, mic status
- [x] **Menu entry**: "Volume Control" → starts `pavucontrol`
- [x] Live status via D-Bus `GPropertiesChanged` + property notify signals
- [x] Icons: 3 symbolic SVGs (disconnected, wired, wireless)
- [ ] Load & test in live GNOME Shell (user action needed)

### Phase 3 – Testing, Docs, Commit
- [ ] Live test: dongle mode, cable mode, headset off / no signal
- [ ] Finalize `README.md` + `STRUCTURE.md` (installation, usage)
- [ ] Clean up `./scratchpad/`
- [ ] Commit with description **after user confirmation**

## 4. Risks & Assumptions

| Risk | Mitigation |
|---|---|
| Battery value in HID report not uniquely identifiable | Fallback: status „connection active, battery unknown"; correlation via charge-state tests |
| Interface 4 (OUT) might be needed for commands (iCUE-like) | Read-only (IN reports); no write access without verification |
| GNOME shell reload during tests | `al`-reload + fallback: `gnome-extensions disable/enable` |

## 5. Status Log

- 2026-10-26: Plan approved by user. Headset charged, currently on – slow discharge ongoing (user cannot force drain).
- 2026-10-26: Phase 0 started (directory structure, dev shell, HID analysis).
- 2026-10-26: Phase 1 D-Bus service implemented and verified. Root cause of D-Bus method call failures: main thread was sleeping instead of running the GLib main loop. Fixed by replacing the `while` loop with `GLib.MainLoop().run()`. All 8 D-Bus tests pass (GetStatus, GetBattery, GetMicMuted, 4× Properties.Get, Introspect).
- 2026-10-26: Continued implementation:
  - Cleaned up debug files (`check_bus*.py`, `check.nix`)
  - Created NixOS module (`service/nixos/hs80max.nix`) with udev rule, D-Bus session policy, and user service wrapper
  - Fixed systemd unit (`service/hs80max.service`) to use `hs80max-service` wrapper instead of nix-shell
  - Created `ressources/battery-protocol.md` (extracted from `corsair_void_v2w.hpp` reference)
  - Created GNOME Shell 50 extension (`extension/`): `metadata.json`, `main.js`, 3 SVG icons
  - Updated `STRUCTURE.md`
