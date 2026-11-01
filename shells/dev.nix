{ pkgs ? import <nixpkgs> {} }:

pkgs.mkShell {
  SHELL = "${pkgs.bash}/bin/bash";

  buildInputs = with pkgs; [
    python3
    python3Packages.pydbus
    dbus
    wireplumber
    usbutils
    git
    bash
  ];

  shellHook = ''
    echo "HS80 Max development environment loaded!"

    # Convenience: quick HID inspection
    alias hidmap='for f in /sys/class/hidraw/hidraw*/device; do echo "$f -> $(readlink -f $f)"; done'
  '';
}
