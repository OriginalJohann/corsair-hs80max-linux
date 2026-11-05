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
    # absolute `env`, guaranteeing the user bus is found.
    #
    # FAIL-SAFE: activation scripts also run at boot (after `nixos-rebuild
    # boot`) and a non-zero exit aborts the whole activation, which can make
    # the machine unbootable. At boot the user session, D-Bus and the unit are
    # often not ready yet, so `start` can fail. Every command that can fail is
    # therefore guarded so this script ALWAYS exits 0 and can never break a
    # boot or a switch.
    system.activationScripts.hs80max-restart.text = ''
      set -e
      uid=$(id -u ${cfg.user} 2>/dev/null) || exit 0
      [ -d /run/user/$uid ] || exit 0
      env=/run/current-system/sw/bin/env
      systemctl=/run/current-system/sw/bin/systemctl
      runuser -u ${cfg.user} -- "$env" XDG_RUNTIME_DIR=/run/user/$uid "$systemctl" --user daemon-reload || true
      runuser -u ${cfg.user} -- "$env" XDG_RUNTIME_DIR=/run/user/$uid "$systemctl" --user stop hs80max.service || true
      runuser -u ${cfg.user} -- "$env" XDG_RUNTIME_DIR=/run/user/$uid "$systemctl" --user start hs80max.service || true
      exit 0
    '';

    # ------------------------------------------------------- D-Bus session
    # Install the session-bus policy file so the user can own the bus name.
    # NixOS has no first-class option for session bus policies, and the
    # session bus only reads policies from /etc/dbus-1/session.conf.d and
    # /run/dbus/session.conf.d, so the activation script copies it to the
    # latter (read by the daemon at session-bus start).
    #
    # FAIL-SAFE: guard the copy so a transient failure can never abort the
    # activation (see the hs80max-restart note above).
    system.activationScripts.hs80max-dbus.text = ''
      mkdir -p /run/dbus/session.conf.d || exit 0
      cp ${dbusConf} /run/dbus/session.conf.d/ || exit 0
      exit 0
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
      after = [ "graphical-session.target" "dbus.socket" ];
      # Join the FIRST session bus of the boot: the bus reads its policy
      # files only at its own start, and the policy file lands in the
      # volatile /run/dbus only via the activation script (absent right
      # after a plain reboot). Being ordered Before=dbus.service means we
      # are the one that triggers the fresh bus and thus get a bus whose
      # policy load includes our file as soon as it exists (the daemon
      # retries owning the name for up to ~30 s in the meantime).
      before = [ "dbus.service" ];
      wantedBy = [ "default.target" ];
      serviceConfig = {
        Type = "simple";
        ExecStart = "${wrapper}/bin/hs80max-service";
        Restart = "on-failure";
        RestartSec = 5;
      };
    };

    # ------------------------------------------------------- GNOME extension
    # The extension is plain source files (not a built package), so NixOS's
    # `gnome.gnome-shell.extensions` list cannot be used. It is installed the
    # same way as the D-Bus policy above: an activation script copies it into
    # the user's extensions directory, where GNOME finds it by the UUID in
    # metadata.json. The destination is the standard /home/<user> (the user
    # may only exist via home-manager, so `users.users.<user>.home` must not
    # be referenced). The shell picks the new files up on the next restart
    # (Alt+F2 → r).
    #
    # FAIL-SAFE: the home directory may not exist yet at boot (the user may be
    # created only via home-manager, which materialises the home at login). A
    # failing copy must never abort the activation, so every step is guarded
    # and the script always exits 0.
    #
    # NO EMPTY LEFTOVERS: a previous version ran `mkdir -p` before `cp`, so a
    # failing copy (e.g. the flake input predates the extension/ directory)
    # left an EMPTY extension directory behind. GNOME then finds the UUID
    # (via dconf enabled-extensions) but fails with "Missing metadata.json".
    # The source is therefore validated first, and any incomplete copy is
    # rolled back so a half-installed extension can never be loaded.
    system.activationScripts.hs80max-extension.text = ''
      # Validate the source BEFORE touching the home dir: if the flake input
      # does not contain the extension, leave the system completely alone.
      [ -f ${extensionDir}/metadata.json ] || exit 0
      extDir=/home/${cfg.user}/.local/share/gnome-shell/extensions/hs80max@originaljohann.dev
      [ -d /home/${cfg.user} ] || exit 0
      mkdir -p "$extDir" || exit 0
      if ! cp -r ${extensionDir}/. "$extDir"/ 2>/dev/null; then
        # Roll back: never leave an incomplete extension set behind.
        rm -rf "$extDir"
        exit 0
      fi
      exit 0
    '';
  };
}
