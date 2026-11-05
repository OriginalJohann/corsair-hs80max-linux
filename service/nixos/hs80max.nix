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
#   1. udev rule  – user read/write access to the HS80 MAX receiver hidraw node
#   2. D-Bus session policy – allows owning com.corsair.hs80max
#   3. systemd user unit – starts the Python daemon at login
#   4. GNOME Shell extension – installed into the user's extensions dir
#
# After `nixos-rebuild switch` the user service is restarted automatically by an
# activation script (see below), so no manual `systemctl --user` is needed.

{ config, lib, pkgs, ... }:

let
  cfg = config.services.hs80max;

  # Paths are relative to this file (service/nixos/hs80max.nix).
  # ./..   →  service/
  # ../../ →  repo root
  serviceDir   = ./..;
  extensionDir = ../../extension;
  dbusConf     = ../dbus/com.corsair.hs80max.conf;

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

  options.services.hs80max.user =
    lib.mkOption {
      type = lib.types.str;
      default = "fne";
      description = "User whose home the GNOME extension is installed into";
    };

  config = lib.mkIf cfg.enable {
    # ------------------------------------------------------------------ udev
    # Grant the 'users' group access to the HS80 MAX receiver HID interface.
    # (Membership of the service user in 'users' is the admin's responsibility:
    # NixOS desktop users are typically in 'users' already; home-manager users
    # can set it via `home.packages`/`programs` – this module must not
    # reference `users.users.<name>` because the user may only exist via
    # home-manager, where the option does not exist.)
    services.udev.extraRules = ''
      SUBSYSTEM=="hidraw", ATTRS{idVendor}=="1b1c", ATTRS{idProduct}=="0a97", MODE="0660", GROUP="users"
    '';

    # ============================================================
    # ALL COMPONENTS BELOW ARE TEMPORARILY DISABLED for boot-regression
    # bisection. Only the udev rule above remains active.
    # Re-enable incrementally to identify the boot-breaking component.
    # ============================================================

    # --- hs80max-restart (DISABLED) ---
    # system.activationScripts.hs80max-restart.text = ''
    #   set -e
    #   uid=$(id -u ${cfg.user} 2>/dev/null) || exit 0
    #   [ -d /run/user/$uid ] || exit 0
    #   env=/run/current-system/sw/bin/env
    #   systemctl=/run/current-system/sw/bin/systemctl
    #   runuser -u ${cfg.user} -- "$env" XDG_RUNTIME_DIR=/run/user/$uid "$systemctl" --user daemon-reload || true
    #   runuser -u ${cfg.user} -- "$env" XDG_RUNTIME_DIR=/run/user/$uid "$systemctl" --user stop hs80max.service || true
    #   runuser -u ${cfg.user} -- "$env" XDG_RUNTIME_DIR=/run/user/$uid "$systemctl" --user start hs80max.service || true
    #   exit 0
    # '';

    # --- hs80max-dbus (DISABLED) ---
    # system.activationScripts.hs80max-dbus.text = ''
    #   mkdir -p /run/dbus/session.conf.d || exit 0
    #   cp ${dbusConf} /run/dbus/session.conf.d/ || exit 0
    #   exit 0
    # '';

    # --- systemd user unit (DISABLED) ---
    # systemd.user.services.hs80max = {
    #   description = "Corsair HS80 Max status service (battery, connection mode)";
    #   after = [ "graphical-session.target" "dbus.socket" ];
    #   before = [ "dbus.service" ];
    #   wantedBy = [ "default.target" ];
    #   serviceConfig = {
    #     Type = "simple";
    #     ExecStart = "${wrapper}/bin/hs80max-service";
    #     Restart = "on-failure";
    #     RestartSec = 5;
    #   };
    # };

    # --- hs80max-extension (DISABLED) ---
    # system.activationScripts.hs80max-extension.text = ''
    #   [ -f ${extensionDir}/metadata.json ] || exit 0
    #   extDir=/home/${cfg.user}/.local/share/gnome-shell/extensions/hs80max@originaljohann.dev
    #   [ -d /home/${cfg.user} ] || exit 0
    #   mkdir -p "$extDir" || exit 0
    #   if ! cp -r ${extensionDir}/. "$extDir"/ 2>/dev/null; then
    #     rm -rf "$extDir"
    #     exit 0
    #   fi
    #   exit 0
    # '';
  };
}
