# HS80 Max – Extension- & Service-Installation: Revamp-Plan

## Problem

Das aktuelle Modul installiert die GNOME-Extension und startet den User-Service
per `system.activationScripts`. Beide Skripte brechen den Boot:

```
Switch root target contains no usable init
```

Root-Cause: Activation-Skripte laufen in einer restriktiven Umgebung
(eingeschränkter PATH, kein User-Session-Kontext). `runuser` +
`systemctl --user` in dieser Phase ist fragil – selbst ohne `set -e`
kann `runuser` den Switch abbrechen, wenn der User-Systemd-Instance
nicht verfügbar ist.

## Nixpkgs-Referenz: `buildGnomeExtension.nix`

```nix
stdenv.mkDerivation {
  pname = "gnome-shell-extension-${pname}";
  installPhase = ''
    mkdir -p $out/share/gnome-shell/extensions/
    cp -r -T . $out/share/gnome-shell/extensions/${uuid}
  '';
}
```

**Schlüsselprinzip:** Die Extension wird als **Nix-Paket** gebaut, das
`$out/share/gnome-shell/extensions/<uuid>` enthält. Es wird über
`environment.systemPackages` ins System installiert. GNOME Shell findet
sie unter `/run/current-system/sw/share/gnome-shell/extensions/<uuid>`.

**Kein Activation-Skript. Kein Home-Verzeichnis. Kein Copy.**

## Revamp: Neues Modul-Design

### 1. Extension → Nix-Paket (kein Activation-Skript)

```nix
# In der let-Bindung des Moduls:
extensionPkg = pkgs.stdenvNoCC.mkDerivation {
  pname = "gnome-shell-extension-hs80max";
  version = "1.0.0";
  src = extensionDir;  # ../../extension
  dontBuild = true;
  installPhase = ''
    mkdir -p $out/share/gnome-shell/extensions
    cp -r -T . $out/share/gnome-shell/extensions/hs80max@originaljohann.dev
  '';
};
```

Installation:
```nix
environment.systemPackages = [ extensionPkg ];
```

GNOME Shell findet die Extension automatisch unter
`/run/current-system/sw/share/gnome-shell/extensions/hs80max@originaljohann.dev`.
Das `dconf`-`enabled-extensions`-Setting aktiviert sie.

**Vorteile:**
- Kein Activation-Skript → kein Boot-Risiko
- Atomar (Store-Pfad, kein Copy)
- Überlebt jeden `home-manager switch`
- Funktioniert für **alle** User gleichzeitig (kein `cfg.user`-Hardcode)

### 2. Service-Restart → NixOS-einbau (kein `runuser`-Skript)

NixOS **reloaded bereits User-Units** beim Switch (sichtbar in der
Switch-Ausgabe: `reloading user units for fne...`). Das `hs80max-restart`-Skript
mit `runuser` + `systemctl --user` ist **redundant**.

Der User-Service startet automatisch beim Login (via `wantedBy = [ "default.target" ]`).
Beim Switch reloaded NixOS die User-Unit-Dateien. Ein manueller
`daemon-reload` + `stop`/`start` ist nicht nötig.

**Lösung: `hs80max-restart`-Activation-Skript komplett entfernen.**

### 3. D-Bus-Policy → NixOS-einbau (kein Activation-Skript)

Die D-Bus-Session-Policy-Datei wird nach `/etc/dbus-1/session.conf.d/`
installiert (systemweit, nicht in `/run`):

```nix
environment.etc."dbus-1/session.conf.d/com.corsair.hs80max.conf".source = dbusConf;
```

Das ist ein statischer Datei-Symlink – kein Skript, kein Boot-Risiko.

### 4. Udev-Regel (bleibt unverändert)

```nix
services.udev.extraRules = ''
  SUBSYSTEM=="hidraw", ATTRS{idVendor}=="1b1c", ATTRS{idProduct}=="0a97", MODE="0660", GROUP="users"
'';
```

Bereits boot-sicher (wird von `udev` beim Start geladen).

## Zusammenfassung: Vorher → Nachher

| Komponente | Vorher | Nachher |
|---|---|---|
| Extension | `activationScripts` → `cp` nach `~/.local/share` | Nix-Paket → `environment.systemPackages` |
| Service-Restart | `activationScripts` → `runuser` + `systemctl --user` | **Entfernt** (NixOS reloaded User-Units selbst) |
| D-Bus-Policy | `activationScripts` → `cp` nach `/run/dbus/` | `environment.etc` (statischer Symlink) |
| Udev-Regel | `services.udev.extraRules` | Unverändert |
| User-Unit | `systemd.user.services.hs80max` | Unverändert |

**Null Activation-Skripte.** Null Boot-Risiko.

## Offene Fragen

1. **`cfg.user`-Option:** Wird überflüssig (Extension ist systemweit, Service
   startet für jeden User mit der Unit). Kann entfernt werden.
2. **Multi-User:** Das alte Design installierte die Extension nur für
   `cfg.user`. Das neue Design macht sie für **alle** User verfügbar.
   Das ist in der Praxis besser (jeder User kann die Extension aktivieren).
3. **`gnome.shell.extensions`-Option:** Falls NixOS 26.11 die Option
   `gnome.shell.extensions.<uuid>.enable` hat, kann man sie direkt setzen
   statt `dconf`. Falls nicht, bleibt `dconf` via home-manager.

## Implementierungsschritte

- [x] `extensionPkg` in `let` definieren
- [x] `environment.systemPackages = [ extensionPkg ]` setzen
- [x] `environment.etc."dbus-1/session.conf.d/..."` setzen
- [x] Alle drei `activationScripts`-Blöcke entfernen
- [x] `systemd.user.services.hs80max` reaktivieren
- [x] `cfg.user`-Option entfernen
- [x] `nixos-rebuild switch` + Reboot-Test
- [x] Extension-Prüfung: `ls /run/current-system/sw/share/gnome-shell/extensions/`
- [x] Service-Prüfung: `systemctl --user status hs80max`

## Status

- [x] Bisection: Boot-Fehler auf `hs80max-restart`-Skript isoliert
- [x] Nixpkgs-Referenz analysiert
- [x] Revamp implementiert
- [x] Boot-Test bestanden
- [x] Extension-Test bestanden
- [x] Service-Test bestanden
