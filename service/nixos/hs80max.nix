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
# After `nixos-rebuild switch` the user service is restarted automatically by an
# activation script (see below), so no manual `systemctl --user` is needed.

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

    # ------------------------------------------------- auto-restart on switch
    # `nixos-rebuild switch` does NOT restart systemd *user* services (a known
    # NixOS gap), so the running unit would keep the previous store path until
    # the next login. This activation script restarts the service on every
    # switch, so it always tracks the current build.
    #
    # Only `stop`+`start` (never a bare `start`): `start` is a no-op when the
    # unit is already active, so the old instance would survive as a duplicate
    # fighting over the D-Bus name. `stop` first guarantees a single instance.
    #
    # `systemctl` is referenced by absolute path: the activation context and the
    # `runuser`'d user environment do not reliably have the NixOS store bin dir
    # on `PATH`, so a bare `systemctl` (or `env … systemctl`) fails with
    # "file not found". `runuser` also resets the target user's environment
    # (PATH, etc.), so `XDG_RUNTIME_DIR` is set *inside* each invocation via an
    # absolute `env`, guaranteeing the user bus is found. Skipped when the user
    # session is not running (logged out / server boot).
    system.activationScripts.hs80max-restart.text = ''
      set -e
      if id -u fne >/dev/null 2>&1 && [ -d /run/user/1000 ]; then
        env=/run/current-system/sw/bin/env
        systemctl=/run/current-system/sw/bin/systemctl
        runuser -u fne -- "$env" XDG_RUNTIME_DIR=/run/user/1000 "$systemctl" --user daemon-reload
        runuser -u fne -- "$env" XDG_RUNTIME_DIR=/run/user/1000 "$systemctl" --user stop hs80max.service
        runuser -u fne -- "$env" XDG_RUNTIME_DIR=/run/user/1000 "$systemctl" --user start hs80max.service
      fi
    '';

    # ------------------------------------------------------- D-Bus session
    # Install the session-bus policy file so the user can own the bus name.
    # NixOS has no first-class option for session bus policies,
    # so we use an activation script.
    system.activationScripts.hs80max-dbus.text = ''
      mkdir -p $out/lib/dbus-1/session.conf.d
      cp ${dbusConf} $out/lib/dbus-1/session.conf.d/
    '';

    # -------------------------------------------------- systemd user unit
    # Defined through NixOS's systemd integration, which installs the unit
    # with a hashed filename (e.g. "ajk15…-hs80max.service") and makes
    # `systemctl --user enable --now hs80max` resolve to it automatically.
    # We deliberately do NOT copy a plain-named "hs80max.service" into
    # /usr/lib/systemd/user: a second unit running the same daemon would
    # fight over the D-Bus name (com.corsair.hs80max) and crash-loop with
    # "name already exists on the bus".
    systemd.user.services.hs80max = {
      description = "Corsair HS80 Max status service (battery, connection mode)";
      after = [ "graphical-session.target" ];
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
