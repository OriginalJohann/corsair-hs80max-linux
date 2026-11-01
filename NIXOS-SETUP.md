# NixOS-Anleitung – corsair-hs80max-linux als Flake-Modul einbinden

Diese Anleitung beschreibt, wie du das Projekt in eine **flake-basierte NixOS-Konfiguration**
einbindest. Ein einziger Import und eine einzige Option installieren danach beide Komponenten:

| Komponente | Was sie macht |
|---|---|
| **Service** (`hs80max.service`, systemd-User-Unit) | Python-Daemon: liest per HID-Protokoll Akku-Stand, Verbindungsmodus (Dongle vs. USB-C) und Mikrofon-Status des HS80 Max und stellt sie über die D-Bus-Session (`com.corsair.hs80max`) bereit. |
| **GNOME-Extension** (`hs80max@originaljohann.dev`) | Zeigt in der GNOME-Top-Bar zwei Icons (Verbindung, Mikrofon) plus Akkuprozent; Klick öffnet Details und `pavucontrol`. |

Das Modul legt an:

1. **udev-Regel** – gibt der Gruppe `users` Lese-/Schreibzugriff auf das hidraw-Node des
   HS80-Max-Dongles (`1b1c:0a97`), damit der Daemon als normaler User darauf zugreifen kann.
2. **D-Bus-Session-Policy** – erlaubt dem User, den Bus-Namen `com.corsair.hs80max` zu besitzen
   (wird nach `/run/current-system/lib/dbus-1/session.conf.d/` kopiert).
3. **systemd-User-Unit** – startet den Daemon bei Login (`After=graphical-session.target`,
   `WantedBy=default.target`, `Restart=on-failure`) und **restartet ihn automatisch bei jedem
   `nixos-rebuild switch`** (NixOS restartet User-Services sonst nicht).
4. **GNOME-Extension** – kopiert die Extension-Dateien in
   `~/.local/share/gnome-shell/extensions/hs80max@originaljohann.dev/` des konfigurierten Users.

---

## 1. Voraussetzungen

- NixOS mit **Flake-Workflow** aktiviert (`nix.settings.experimental-features = [ "nix-command" "flakes" ];`).
- GNOME-Desktop (die Extension benötigt GNOME Shell 50, also z. B. NixOS 25.05).
- Der HS80-Max-Dongle muss angeschlossen sein, damit die udev-Regel greift
  (ohne Dongle startet der Service trotzdem und meldet `disconnected`).

## 2. Flake-Input im Host-Flake anlegen

In deinem NixOS-Host-Flake (`flake.nix` auf der Maschine):

```nix
{
  inputs = {
    nixos-config.url = "github:dein-user/deine-nixos-config";

    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.05";

    # Neu: das HS80-Max-Projekt
    corsair-hs80max-linux.url = "github:OriginalJohann/corsair-hs80max-linux";
  };

  outputs = { self, nixos-config, nixpkgs, corsair-hs80max-linux, ... }:
    nixosConfigurations.meine-maschine = nixpkgs.lib.nixosSystem {
      system = "x86_64-linux";
      modules = [
        nixos-config/modules/common.nix
        ./configuration.nix
        # Neu: das Modul aus dem Flake-Input importieren
        corsair-hs80max-linux.nixosModules.hs80max
      ];
    };
}
```

> **Lokal statt von GitHub testen?** Ersetze die `url` einfach durch den Pfad:
> `corsair-hs80max-linux = { url = "/Data/ai/corsair-hs80max-linux"; };`
> Das Projekt-Flake funktioniert lokal genauso (es liegt dort unter
> `nixosModules.hs80max`).

## 3. Option in der NixOS-Konfiguration setzen

In deinem `configuration.nix` (oder wo auch immer deine Host-Optionen liegen):

```nix
{
  # Installiert Service UND GNOME-Extension:
  services.hs80max.enable = true;

  # Optional (Default: "fne"): in welches Home die Extension kopiert wird.
  # Der User muss in users.users definiert sein; der Zielordner wird aus dem
  # `home`-Attribut des Users aufgelöst (funktioniert auch mit NixOS-Store-Homes).
  # services.hs80max.user = "fne";
}
```

## 4. Anwenden

```bash
nixos-rebuild switch
```

Das war's. Der Aktivierungslauf:

- installiert/updated die udev-Regel, die D-Bus-Policy und die User-Unit,
- kopiert die Extension in `~/.local/share/gnome-shell/extensions/hs80max@originaljohann.dev/`,
- **restartet** den laufenden `hs80max`-User-Service automatisch
  (stop + start, nur wenn eine User-Session läuft).

## 5. Extension einmalig aktivieren

Die Kopie installiert nur die Dateien – die **Aktivierung** der Extension bleibt
deiner `dconf`-Einstellung überlassen und übersteht Rebuilds. Einmalig:

- **GNOME-Einstellungen → Erweiterte → Erweiterungen → „Corsair HS80 Max Status“**
  anmachen, **oder**
- `gsettings set org.gnome.shell enabled-extensions "['hs80max@originaljohann.dev']"`
  (Achtung: das ersetzt die komplette Liste – vorher mit
  `gsettings get org.gnome.shell enabled-extensions` den alten Wert merken).

Ist die Extension schon aktiv, reicht nach einem Update ein Shell-Neustart
(Alt+F2 → `r` → Enter), um die neuen Dateien zu laden.

## 6. Verifizieren

```bash
# Service läuft?
systemctl --user status hs80max

# Logs:
journalctl --user -u hs80max -f

# Status, den der Daemon aktuell meldet:
cat "$XDG_RUNTIME_DIR/hs80max/status.json"
# → z. B. {"mode": "connected", "battery": 87, "mic_muted": false, "updated_at": ...}

# D-Bus direkt abfragen:
dbus-send --session --print-reply --dest=com.corsair.hs80max \
  /com/corsair/hs80max com.corsair.hs80max.GetStatus

# Extension ist kopiert?
ls ~/.local/share/gnome-shell/extensions/hs80max@originaljohann.dev/
```

## 7. Update des Projekts

```bash
# Auf dem Host:
nix flake update corsair-hs80max-linux
nixos-rebuild switch     # Service wird automatisch neu gestartet
```

Danach ggf. Shell neu laden (Alt+F2 → `r`), wenn sich die Extension geändert hat.

## 8. Troubleshooting

| Symptom | Ursache / Abhilfe |
|---|---|
| Service startet, meldet permanent `disconnected` | Dongle nicht erkannt? `ls /sys/class/hidraw/hidraw*/device` prüfen; udev-Regel greift erst nach neuem Anstecken des Dongles oder `sudo udevadm control --reload-rules && sudo udevadm trigger`. |
| `systemctl --user status hs80max` zeigt alten Store-Pfad | Normal nur kurz nach `switch` vor Abschluss des Aktivierungsskripts; danach muss der Pfad aktuell sein. |
| Extension erscheint nicht in GNOME-Einstellungen | Ordner `~/.local/share/gnome-shell/extensions/hs80max@originaljohann.dev/` vorhanden? `metadata.json` muss `shell-version: ["50"]` mit deinem GNOME abdecken. |
| Extension zeigt „getrennt“, Service läuft aber | Die Extension läuft als **User** – sie sieht nur die Session-D-Bus desselben Users. `status.json` (Punkt 6) zeigt, ob der Daemon überhaupt Status liefert. |
| `cp: cannot create … $extDir` im Aktivierungslog | `users.users.<user>` nicht definiert → `services.hs80max.user` setzen und den User in `users.users` anlegen. |

## 9. Alternativen (Kurzform)

- **Ohne Flake:** Direktpfad-Import –
  `imports = [ /pfad/zu/corsair-hs80max-linux/service/nixos/hs80max.nix ];`
  (das Modul referenziert alle Dateien relativ zu sich selbst und funktioniert
  so auch in reinem Evaluationsmodus).
- **Nur Service, ohne Extension:** Nicht vorgesehen – `services.hs80max.enable`
  installiert beides.
- **Manuell (ohne NixOS-Modul):** `service/hs80max.service` nach
  `~/.config/systemd/user/` kopieren und den Extension-Ordner manuell nach
  `~/.local/share/gnome-shell/extensions/` – dient nur als Fallback für
  Nicht-NixOS-Systeme.
