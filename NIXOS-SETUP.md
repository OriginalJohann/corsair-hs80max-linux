# NixOS Setup – Integrating corsair-hs80max-linux as a Flake Module

This guide explains how to integrate this project into a **flake-based NixOS
configuration**. A single import and a single option then install both
components:

| Component | What it does |
|---|---|
| **Service** (`hs80max.service`, systemd user unit) | Python daemon: reads the HS80 Max battery level, connection mode (dongle vs. USB-C) and microphone state via the HID protocol and exposes them over the D-Bus session (`com.corsair.hs80max`). |
| **GNOME Extension** (`hs80max@originaljohann.dev`) | Shows two icons (connection, microphone) plus the battery percentage in the GNOME top bar; clicking opens details and `pavucontrol`. |

The module creates:

1. **udev rule** – grants the `users` group read/write access to the hidraw
   node of the HS80 Max dongle (`1b1c:0a97`) so the daemon can access it as a
   regular user.
2. **D-Bus session policy** – allows the user to own the bus name
   `com.corsair.hs80max`
   (copied to `/run/dbus/session.conf.d/`).
3. **systemd user unit** – starts the daemon at login
   (`After=graphical-session.target`, `WantedBy=default.target`,
   `Restart=on-failure`) and **restarts it automatically on every
   `nixos-rebuild switch`** (NixOS does not restart user services otherwise).
4. **GNOME extension** – copies the extension files into
   `~/.local/share/gnome-shell/extensions/hs80max@originaljohann.dev/` of the
   configured user.

---

## 1. Prerequisites

- NixOS with the **flake workflow** enabled (`nix.settings.experimental-features = [ "nix-command" "flakes" ];`).
- GNOME desktop (the extension requires GNOME Shell 50, e.g. NixOS 25.05).
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
> `nixosModules.hs80max`).

## 3. Set the option in your NixOS configuration

In your `configuration.nix` (or wherever your host options live):

```nix
{
  # Installs the service AND the GNOME extension:
  services.hs80max.enable = true;

  # Optional (default: "fne"): the home into which the extension is copied.
  # The user must be defined in users.users; the target folder is resolved
  # from the user's `home` attribute (also works with NixOS store homes).
  # services.hs80max.user = "fne";
}
```

## 4. Apply

```bash
nixos-rebuild switch
```

That's it. The activation run:

- installs/updates the udev rule, the D-Bus policy, and the user unit,
- copies the extension into `~/.local/share/gnome-shell/extensions/hs80max@originaljohann.dev/`,
- **restarts** the running `hs80max` user service automatically
  (stop + start, only if a user session is running).
## 5. Enable the extension once

The copy only installs the files – **enabling** the extension is left to your
`dconf` setting and survives rebuilds. One time only:

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

# Was the extension copied?
ls ~/.local/share/gnome-shell/extensions/hs80max@originaljohann.dev/
```

## 7. Updating the project

```bash
# On the host:
nix flake update corsair-hs80max-linux
nixos-rebuild switch     # the service is restarted automatically
```

Afterwards, reload the shell (Alt+F2 → `r`) if the extension changed.

## 8. Troubleshooting

| Symptom | Cause / remedy |
|---|---|
| Service starts, reports `disconnected` permanently | Dongle not detected? Check `ls /sys/class/hidraw/hidraw*/device`; the udev rule only takes effect after reconnecting the dongle or `sudo udevadm control --reload-rules && sudo udevadm trigger`. |
| `systemctl --user status hs80max` shows an old store path | Normal only briefly after `switch`, before the activation script has finished; afterwards the path must be current. |
| Extension does not appear in GNOME settings | Is the folder `~/.local/share/gnome-shell/extensions/hs80max@originaljohann.dev/` present? `metadata.json` must cover your GNOME with `shell-version: ["50"]`. |
| Extension shows “disconnected”, but the service is running | The extension runs as a **user** – it only sees the session D-Bus of that same user. `status.json` (point 6) shows whether the daemon delivers status at all. |
| `cp: cannot create … $extDir` in the activation log | `users.users.<user>` not defined → set `services.hs80max.user` and create the user in `users.users`. |

## 9. Alternatives (short form)

- **Without a flake:** direct path import –
  `imports = [ /path/to/corsair-hs80max-linux/service/nixos/hs80max.nix ];`
  (the module references all files relative to itself and also works in
  plain evaluation mode).
- **Service only, without the extension:** not provided – `services.hs80max.enable`
  installs both.
- **Manually (without the NixOS module):** copy `service/hs80max.service`
  to `~/.config/systemd/user/` and the extension folder manually to
  `~/.local/share/gnome-shell/extensions/` – this only serves as a fallback
  for non-NixOS systems.

