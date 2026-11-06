# NixOS Setup – Integrating corsair-hs80max-linux as a Flake Module

This guide explains how to integrate this project into a **flake-based NixOS
configuration**. A single import and a single option then install both
components:

| Component | What it does |
|---|---|
| **Service** (`hs80max.service`, systemd user unit) | Python daemon: reads the HS80 Max battery level, connection mode (dongle vs. USB-C) and microphone state via the HID protocol and exposes them over the D-Bus session (`com.corsair.hs80max`). |
| **GNOME Extension** (`hs80max@originaljohann.dev`) | Shows two icons (connection, microphone) plus the battery percentage in the GNOME top bar; clicking opens details and `pavucontrol`. |

The module (`service/nixos/hs80max.nix`) creates:

1. **udev rule** – grants the `users` group read/write access to the hidraw
   node of the HS80 Max dongle (`1b1c:0a97`) so the daemon can access it as a
   regular user.
2. **systemd user unit** – starts the daemon at login
   (`After=graphical-session.target dbus.socket`, `WantedBy=default.target`,
   `Restart=on-failure`, `RestartSec=5`). Transient boot conditions (e.g. the
   session bus not being ready yet) are ridden out by systemd's retry; the
   daemon exits non-zero on a failed start. NixOS restarts the user service
   automatically on every `nixos-rebuild switch`.
3. **GNOME extension** – built as a Nix package and installed system-wide via
   `environment.systemPackages`, so GNOME Shell discovers it in
   `/run/current-system/sw/share/gnome-shell/extensions/` without any
   activation script.

No D-Bus policy file is needed: the default session bus policy already allows
owning the `com.corsair.hs80max` name.

---

## 1. Prerequisites

- NixOS with the **flake workflow** enabled (`nix.settings.experimental-features = [ "nix-command" "flakes" ];`).
- GNOME desktop with **GNOME Shell 50** (e.g. NixOS 25.05) for the extension.
- Your user is a member of the **`users`** group (the udev rule grants the
  `users` group access to the dongle's hidraw node):
  ```bash
  sudo usermod -aG users $USER
  # log out and back in (or `newgrp users`)
  ```
- The HS80 Max dongle must be connected for the udev rule to take effect
  (without the dongle the service still starts and reports `disconnected`).

## 2. Add the flake input to your host flake

In your NixOS host flake (`flake.nix` on the machine):

```nix
{
  inputs = {
    nixos-config.url = "github:your-user/your-nixos-config";

    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.05";

    # New: the HS80 Max project
    corsair-hs80max-linux.url = "github:OriginalJohann/corsair-hs80max-linux";
  };

  outputs = { self, nixos-config, nixpkgs, corsair-hs80max-linux, ... }:
    nixosConfigurations.my-machine = nixpkgs.lib.nixosSystem {
      system = "x86_64-linux";
      modules = [
        nixos-config/modules/common.nix
        ./configuration.nix
        # New: import the module from the flake input
        corsair-hs80max-linux.nixosModules.hs80max
      ];
    };
}
```

> **Testing locally instead of from GitHub?** Just replace the `url` with a
> path:
> `corsair-hs80max-linux = { url = "/Data/ai/corsair-hs80max-linux"; };`
> The project flake works identically locally (it exposes
> `nixosModules.hs80max`). The flake has no own inputs – the module's
> `pkgs` come from your host flake, so the build always tracks your
> nixpkgs.

## 3. Set the option in your NixOS configuration

In your `configuration.nix` (or wherever your host options live):

```nix
{
  # Installs the service AND the GNOME extension:
  services.hs80max.enable = true;
}
```

That is the only option the module provides.

## 4. Apply

```bash
nixos-rebuild switch
```

Then **log out and back in** (the systemd *user* unit starts at login, and
GNOME Shell must be restarted to pick up the new system extension).
## 5. Enable the extension once

Installation only puts the files in place – **enabling** the extension is a
per-user `dconf` setting and survives rebuilds. One time only:

- toggle **GNOME Settings → Extensions → “Corsair HS80 Max Status”** on, **or**
- `gsettings set org.gnome.shell enabled-extensions "['hs80max@originaljohann.dev']"`
  (note: this replaces the whole list – first note the old value with
  `gsettings get org.gnome.shell enabled-extensions`).

If the extension is already enabled, a shell restart after an update is
enough to load the new files (Alt+F2 → `r` → Enter).

## 6. Verify

```bash
# Is the service running?
systemctl --user status hs80max

# Logs:
journalctl --user -u hs80max -f

# The status the daemon currently reports:
cat "$XDG_RUNTIME_DIR/hs80max/status.json"
# → e.g. {"mode": "connected", "battery": 87, "mic_muted": false, "updated_at": ...}

# Query D-Bus directly:
dbus-send --session --print-reply --dest=com.corsair.hs80max \
  /com/corsair/hs80max com.corsair.hs80max.GetStatus

# Is the extension installed system-wide?
ls /run/current-system/sw/share/gnome-shell/extensions/ | grep hs80max
```

## 7. Updating the project

```bash
# On the host:
nix flake update corsair-hs80max-linux
nixos-rebuild switch     # the user service is restarted automatically
```

Afterwards, reload the shell (Alt+F2 → `r`) if the extension changed.

## 8. Troubleshooting

| Symptom | Cause / remedy |
|---|---|
| Service starts, reports `disconnected` permanently | Dongle not detected? Check `ls /sys/class/hidraw/hidraw*/device`; the udev rule only takes effect after reconnecting the dongle or `sudo udevadm control --reload-rules && sudo udevadm trigger`. |
| `hs80max.service` not running | `journalctl --user -u hs80max` – check for permission errors; make sure your user is in the `users` group and you logged in again. |
| Extension does not appear in GNOME settings | Is the folder `/run/current-system/sw/share/gnome-shell/extensions/hs80max@originaljohann.dev/` present? `metadata.json` must cover your GNOME with `shell-version: ["50"]`. |
| Extension shows “disconnected”, but the service is running | The extension runs as a **user** – it only sees the session D-Bus of that same user. `status.json` (point 6) shows whether the daemon delivers status at all. |

## 9. Alternatives (short form)

- **Without a flake:** direct path import –
  `imports = [ /path/to/corsair-hs80max-linux/service/nixos/hs80max.nix ];`
  (the module references all files relative to itself and also works in
  plain evaluation mode).
- **Service only, without the extension:** not provided – `services.hs80max.enable`
  installs both.
- **Non-NixOS systems:** `./install.sh` (installs udev rule, D-Bus policy,
  systemd user unit and the extension into `~/.local/share/`).
- **Manually (without the NixOS module):** copy `service/hs80max.service`
  to `~/.config/systemd/user/` and the extension folder manually to
  `~/.local/share/gnome-shell/extensions/` – this only serves as a fallback
  for non-NixOS systems.

