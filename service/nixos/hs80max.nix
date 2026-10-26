# NixOS module for the HS80 Max status service.
#
# Add to your NixOS configuration (use a path Nix can resolve):
#   imports = [ /path/to/corsair-hs80max-linux/service/nixos/hs80max.nix ];
#   services.hs80max.enable = true;
#
# All internal file references use paths relative to this module file,
# so the module works in pure evaluation mode as long as the import
# path itself is resolvable by Nix.
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

  # Paths are relative to this file (service/nixos/hs80max.nix).
  # ./..  →  service/
  serviceDir = ./..;
  dbusConf   = ../dbus/com.corsair.hs80max.conf;

  # Python environment with required third-party packages.
  pythonEnv = pkgs.python3.withPackages (ps: [
    ps.pydbus
  ]);

  # Wrapper script that adds the service package to sys.path and runs the daemon.
  wrapper = pkgs.writeScriptBin "hs80max-service" ''
    #!${pythonEnv}/bin/python3
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
      cp ${dbusConf} $out/lib/dbus-1/session.conf.d/
    '';

    # -------------------------------------------------- systemd user unit
    # Copy the unit into /usr/lib/systemd/user/ via the system profile.
    # Also create an unhashed symlink so `systemctl --user` can find it
    # by its plain name (NixOS hashes unit filenames by default).
    system.activationScripts.hs80max-unit.text = ''
      mkdir -p $out/lib/systemd/user
      cp ${../hs80max.service} $out/lib/systemd/user/hs80max.service
    '';
  };
}
