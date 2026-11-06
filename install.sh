#!/usr/bin/env bash
# Installs the HS80 Max service and GNOME extension on non-NixOS systems.
#
# Mirrors the three pieces of service/nixos/hs80max.nix:
#   1. udev rule        -> /etc/udev/rules.d/99-hs80max.rules        (root)
#   2. systemd user unit -> ~/.config/systemd/user/hs80max.service
#   3. GNOME extension   -> ~/.local/share/gnome-shell/extensions/
#
# (No D-Bus policy file is needed: the default session policy already
# allows owning com.corsair.hs80max – same as the NixOS module.)
#
# Usage: ./install.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UUID="hs80max@originaljohann.dev"

# No privilege prefix when already root: a `true` prefix would silently
# no-op every privileged command (the udev rule would never be written).
if [ "$(id -u)" -eq 0 ]; then
  SUDO=""
else
  SUDO="$(command -v sudo || { echo "sudo not found" >&2; exit 1; })"
fi

echo "==> 1/5 Checking dependencies"
command -v python3 >/dev/null || { echo "python3 not found" >&2; exit 1; }
if ! python3 -c 'import pydbus, gi' 2>/dev/null; then
  echo "Missing Python packages: pydbus / python3-gi."
  echo "Install them for your distro (e.g. 'sudo apt install python3-pydbus python3-gi')"
  echo "or 'python3 -m pip install pydbus', then re-run this script."
  exit 1
fi

echo "==> 2/5 Installing udev rule (HS80 Max receiver hidraw access)"
# User read/write access to the receiver's control interface.
RULE_FILE="/etc/udev/rules.d/99-hs80max.rules"
"$SUDO" tee "$RULE_FILE" >/dev/null <<'EOF'
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="1b1c", ATTRS{idProduct}=="0a97", MODE="0660", GROUP="users"
EOF
"$SUDO" udevadm control --reload-rules && "$SUDO" udevadm trigger
# The udev rule grants access to the 'users' group. Do NOT modify group
# membership here (that would need explicit user consent); just check and
# hint, so the daemon's open failure is easy to diagnose.
if ! id -nG | grep -qw users; then
  echo "    note: $USER is not in the 'users' group – the daemon cannot open"
  echo "          the dongle's hidraw node. Run: sudo usermod -aG users $USER"
  echo "          (takes effect at the next login)."
fi

echo "==> 3/5 Installing systemd user unit"
# The committed unit (service/hs80max.service) is the single source of
# truth: its ExecStart already runs the daemon straight from this checkout.
# The unit carries PYTHONPATH itself, so no wrapper script is needed.
#
# Guard: the sed below would produce an EMPTY file if the source unit had
# no [Service] section – which would clobber a working user unit.
grep -q '^\[Service\]' "$REPO_DIR/service/hs80max.service" || {
  echo "ERROR: service/hs80max.service has no [Service] section; aborting." >&2
  exit 1
}
# Never clobber an existing install without confirmation (re-running after a
# repo update is expected, so this is a single yes/no, not a per-file prompt).
if [ -f "$HOME/.config/systemd/user/hs80max.service" ]; then
  read -r -p "An existing hs80max.service unit will be overwritten. Continue? [y/N] " ans
  [ "$ans" = "y" ] || [ "$ans" = "Y" ] || { echo "Aborted."; exit 1; }
fi

mkdir -p "$HOME/.config/systemd/user"
cp "$REPO_DIR/service/hs80max.service" "$HOME/.config/systemd/user/hs80max.service"
# PYTHONPATH must land in the [Service] section: it is a service setting, not
# a unit setting, and sed inserts it right after the [Service] header.
sed -i "s|^\[Service\]|[Service]\nEnvironment=PYTHONPATH=$REPO_DIR/service|" \
  "$HOME/.config/systemd/user/hs80max.service"

systemctl --user daemon-reload
systemctl --user enable --now hs80max.service

echo "==> 4/5 Installing GNOME extension"
if command -v gnome-shell >/dev/null; then
  GNOME_VER="$(gnome-shell --version | grep -oE '[0-9]+' | head -1)"
  [ "$GNOME_VER" = "50" ] || echo "    warning: GNOME Shell $GNOME_VER, extension expects 50"
fi
EXT_DIR="$HOME/.local/share/gnome-shell/extensions/$UUID"
mkdir -p "$EXT_DIR"
cp -r "$REPO_DIR/extension/." "$EXT_DIR/"

echo "==> 5/5 Done"
echo
echo "Next steps:"
echo "  1. Activate the extension once: GNOME Settings > Extensions"
echo "     (search 'Corsair HS80 Max Status'), then restart the shell (Alt+F2, r)."
echo "  2. If the dongle is already plugged in, unplug/replug it so the"
echo "     udev rule applies to its hidraw node."
echo
echo "Verify:"
echo "  systemctl --user status hs80max"
echo "  journalctl --user -u hs80max -f"
echo
echo "WARNING: the generated unit pins this checkout at $REPO_DIR"
echo "(PYTHONPATH). After moving or updating the repo, re-run this script."
