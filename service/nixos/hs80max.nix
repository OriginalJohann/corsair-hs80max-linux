# NixOS module for the HS80 Max status service.
#
# Add to your NixOS configuration:
#   imports = [ /path/to/corsair-hs80max-linux/service/nixos/hs80max.nix ];
#   services.hs80max.enable = true;
#
# Sets up:
#   1. udev rule  – user read/write access to the HS80 MAX receiver hidraw node
#   2. D-Bus session policy – allows owning com.corsair.hs80max
#   3. systemd user unit – starts the Python daemon at login
#
# After `nixos-rebuild switch`, enable the user service:
#   systemctl --user daemon-reload
#   systemctl --user enable --now hs80max

{ config, lib, pkgs, ... }:

let
  cfg = config.services.hs80max;
  # Wrapper script that adds the service package to sys.path and runs the daemon.
  serviceDir = /Data/ai/corsair-hs80max-linux/service;
  wrapper = pkgs.writeScriptBin "hs80max-service" ''
    #!${pkgs.python3}/bin/python3
    import sys
    sys.path.insert(0, "${serviceDir}")
    from hs80max_service.main import main
    sys.exit(main())
  '';
in
{
  options.services.hs80max.enable =
    lib.mkEnableOption "Corsair HS80 Max status service";

  config = lib.mkIf cfg.enable {
    # ------------------------------------------------------------------ udev
    # Grant the 'users' group access to the HS80 MAX receiver HID interface.
    services.udev.extraRules = ''
      SUBSYSTEM=="hidraw", ATTRS{idVendor}=="1b1c", ATTRS{idProduct}=="0a97", MODE="0660", GROUP="users"
    '';

    # Make the wrapper script available system-wide.
    environment.systemPackages = [ wrapper ];

    # ------------------------------------------------------- D-Bus session
    # Install the session-bus policy file so the user can own the bus name.
    # NixOS has no first-class option for session bus policies,
    # so we use an activation script.
    system.activationScripts.hs80max-dbus.text = ''
      mkdir -p $out/lib/dbus-1/session.conf.d
      cp ${./dbus/com.corsair.hs80max.conf} $out/lib/dbus-1/session.conf.d/
    '';

    # Install the systemd user unit into the system profile.
    system.activationScripts.hs80max-unit.text = ''
      mkdir -p $out/lib/systemd/user
      cp ${./hs80max.service} $out/lib/systemd/user/
    '';
  };
}
