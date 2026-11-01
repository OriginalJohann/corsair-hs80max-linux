#!/usr/bin/env bash
# Installs the HS80 Max service and GNOME extension on non-NixOS systems.
#
# Mirrors the four pieces of service/nixos/hs80max.nix:
#   1. udev rule        -> /etc/udev/rules.d/99-hs80max.rules        (root)
#   2. D-Bus policy     -> /etc/dbus-1/session.conf.d/               (root)
#   3. systemd user unit -> ~/.config/systemd/user/hs80max.service
#   4. GNOME extension   -> ~/.local/share/gnome-shell/extensions/
#
# Usage: ./install.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UUID="hs80max@originaljohann.dev"

# Use sudo only when not already root, so the script also works as root.
SUDO="$(command -v sudo || echo true)"
[ "$(id -u)" -eq 0 ] && SUDO=true

echo "==> 1/6 Checking dependencies"
command -v python3 >/dev/null || { echo "python3 not found" >&2; exit 1; }
if ! python3 -c 'import pydbus, gi' 2>/dev/null; then
  echo "Missing Python packages: pydbus / python3-gi."
  echo "Install them for your distro (e.g. 'sudo apt install python3-pydbus python3-gi')"
  echo "or 'python3 -m pip install pydbus', then re-run this script."
  exit 1
fi

echo "==> 2/6 Installing udev rule (HS80 Max receiver hidraw access)"
# User read/write access to the receiver's control interface.
RULE_FILE="/etc/udev/rules.d/99-hs80max.rules"
"$SUDO" tee "$RULE_FILE" >/dev/null <<'EOF'
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="1b1c", ATTRS{idProduct}=="0a97", MODE="0660", GROUP="users"
EOF
"$SUDO" udevadm control --reload-rules && "$SUDO" udevadm trigger

echo "==> 3/6 Installing D-Bus session policy"
# No per-user session.conf.d exists, so the policy goes system-wide.
DBUS_DIR="/etc/dbus-1/session.conf.d"
"$SUDO" install -m 0644 "$REPO_DIR/service/dbus/com.corsair.hs80max.conf" "$DBUS_DIR/"
# The session bus only reads policies at daemon start, so the change takes
# effect at the next login (existing sessions keep the old policy).

echo "==> 4/6 Installing systemd user unit + wrapper"
# The committed unit points at the NixOS store path, so generate a user
# wrapper that runs the daemon straight from this checkout.
mkdir -p "$HOME/.local/bin"
cat > "$HOME/.local/bin/hs80max-service" <<EOF
#!/usr/bin/env python3
import sys
sys.path.insert(0, "$REPO_DIR/service")
from hs80max_service.main import main
sys.exit(main())
EOF
chmod +x "$HOME/.local/bin/hs80max-service"

mkdir -p "$HOME/.config/systemd/user"
sed "s|^ExecStart=.*|ExecStart=$HOME/.local/bin/hs80max-service|" \
  "$REPO_DIR/service/hs80max.service" > "$HOME/.config/systemd/user/hs80max.service"

systemctl --user daemon-reload
systemctl --user enable --now hs80max.service

echo "==> 5/6 Installing GNOME extension"
if command -v gnome-shell >/dev/null; then
  GNOME_VER="$(gnome-shell --version | grep -oE '[0-9]+' | head -1)"
  [ "$GNOME_VER" = "50" ] || echo "    warning: GNOME Shell $GNOME_VER, extension expects 50"
fi
EXT_DIR="$HOME/.local/share/gnome-shell/extensions/$UUID"
mkdir -p "$EXT_DIR"
cp -r "$REPO_DIR/extension/." "$EXT_DIR/"

echo "==> 6/6 Done"
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
echo "Note: the wrapper pins this checkout at $REPO_DIR."
echo "After updating the repo, re-run this script."
