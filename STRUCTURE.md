# Project Structure – corsair-hs80max-linux

GNOME extension + background service for the Corsair HS80 Max headset:
connection status, battery level, and volume-app integration in the GNOME systray.

```
corsair-hs80max-linux/
├── AGENTS.md                  # Agent instructions & workflow guidelines
├── INSTRUCTIONS.md            # Original task specification
├── NIXOS-SETUP.md             # Guide: module integration into a flake NixOS config
├── README.md                  # Project overview (updated in Phase 3)
├── STRUCTURE.md               # This file – keep in sync with changes
├── plans/                     # Planning files (currently empty)
├── resources/
│   ├── battery-protocol.md    # HS80 Max HID battery protocol (verified)
│   ├── produktblatt.pdf       # Product datasheet
│   ├── reference_corsair_device.hpp     # Protocol reference (Sapd/HeadsetControl)
│   └── reference_corsair_void_v2w.hpp   # Protocol reference (Sapd/HeadsetControl)
├── shells/
│   └── dev.nix                # Nix development shell (python3, pydbus, dbus, wireplumber)
├── service/                   # Background service (Python, D-Bus) – Phase 1
│   ├── hs80max_service/
│   │   ├── __init__.py
│   │   ├── main.py            # Daemon entry point
│   │   ├── hid_protocol.py    # HID wake/battery/mic commands
│   │   ├── connection.py      # Connection-mode detection (dongle vs. USB-C)
│   │   └── dbus_api.py        # D-Bus interface com.corsair.hs80max
│   ├── dbus/
│   │   └── com.corsair.hs80max.conf  # D-Bus session policy
│   ├── nixos/
│   │   └── hs80max.nix        # NixOS module (udev + D-Bus + user service + GNOME extension)
│   ├── hs80max.service        # systemd user unit
│   └── test_dbus.sh           # E2E D-Bus test script
├── extension/                 # GNOME Shell extension (Shell 50) – Phase 2
│   ├── metadata.json
│   ├── extension.js           # D-Bus client (com.corsair.hs80max) + tray UI
│   │                          # (PanelMenu.Button via Main.panel.addToStatusArea,
│   │                          #  left box, like the appindicator extension)
│   ├── main.js                # Re-export shim (upstream builds load main.js)
│   ├── stylesheet.css
│   └── icons/
│       ├── headset-disconnected-symbolic.svg
│       ├── headset-connected-symbolic.svg
│       ├── mic-mute-symbolic.svg
│       └── mic-unmute-symbolic.svg
└── scratchpad/                # Temporary files (deleted before final commit)
```

## Key Facts

- Dongle: USB `1b1c:0a97`, HID control on **interface 4** → `/dev/hidraw1`
- Battery: proprietary HID protocol (see `resources/battery-protocol.md`), no USB Battery SUD
- D-Bus service name: `com.corsair.hs80max` (session bus)
- Volume app: `pavucontrol`
- Extension UUID: `hs80max@originaljohann.dev`
