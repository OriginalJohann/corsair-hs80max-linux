# NixOS module for the HS80 Max status service + GNOME Shell extension.
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
#   1. udev rule           – user read/write access to the HS80 MAX receiver hidraw node
#   2. systemd user unit   – starts the Python daemon at login
#   3. GNOME Shell extension – installed as a system package (no activation script)
#
# No activation scripts are used. The extension is a Nix package in
# environment.systemPackages, and NixOS reloads user units on switch.
# D-Bus: the default session policy already allows owning com.corsair.hs80max.

{ config, lib, pkgs, ... }:

let
  cfg = config.services.hs80max;

  # Paths are relative to this file (service/nixos/hs80max.nix).
  # ./..   →  service/
  # ../../ →  repo root
  serviceDir   = ./..;
  extensionDir = ../../extension;

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

  # GNOME Shell extension as a Nix package.
  # Installs to $out/share/gnome-shell/extensions/hs80max@originaljohann.dev,
  # which GNOME Shell discovers via /run/current-system/sw/share/gnome-shell/extensions/.
  extensionPkg = pkgs.stdenvNoCC.mkDerivation {
    pname = "gnome-shell-extension-hs80max";
    version = "1.0.0";
    src = extensionDir;
    dontBuild = true;
    installPhase = ''
      mkdir -p $out/share/gnome-shell/extensions
      cp -r -T . $out/share/gnome-shell/extensions/hs80max@originaljohann.dev
    '';
  };
in
{
  options.services.hs80max.enable =
    lib.mkEnableOption "Corsair HS80 Max status service";

  config = lib.mkIf cfg.enable {
    # ------------------------------------------------------------------ udev
    # Grant the 'users' group access to the HS80 MAX receiver HID interface.
    # (Membership of the service user in 'users' is the admin's responsibility.)
    services.udev.extraRules = ''
      SUBSYSTEM=="hidraw", ATTRS{idVendor}=="1b1c", ATTRS{idProduct}=="0a97", MODE="0660", GROUP="users"
    '';

    # ------------------------------------------------------- GNOME extension
    # Installed as a system package. GNOME Shell finds it in
    # /run/current-system/sw/share/gnome-shell/extensions/.
    environment.systemPackages = [ extensionPkg ];

    # -------------------------------------------------------- systemd user unit
    systemd.user.services.hs80max = {
      description = "Corsair HS80 Max status service (battery, connection mode)";
      after = [ "graphical-session.target" "dbus.socket" ];
      wantedBy = [ "default.target" ];
      serviceConfig = {
        Type = "simple";
        ExecStart = "${wrapper}/bin/hs80max-service";
        Restart = "on-failure";
        RestartSec = 5;
      };
    };
  };
}
