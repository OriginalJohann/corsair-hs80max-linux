`# Repo Audit – corsair-hs80max-linux (2026-11-01, full-repo audit)
`
`Findings from the full-repo audit (service, extension, Nix modules, installer,
`tests). Load assumption: **one user, one GNOME session, one headset**.
`Test suite verified green at audit time: `service/.venv/bin/pytest service/`
`→ 11/11 passed; `bash -n` on shell scripts ok; `node --check extension/extension.js` ok.
`
`Each finding has a status: `[ ]` pending, `[x]` done. Ordered for
`implementation: broken install paths first, then robustness, then lean.
`
`---
`
`## Must fix
`
`### 1. NixOS module grants dongle access to the wrong group
``service/nixos/hs80max.nix` (udev block ~L60-62)
`- Udev rule: `MODE="0660", GROUP="users"`, but the module never adds
`  `${cfg.user}` to the `users` group. On NixOS the desktop user typically
`  is NOT in `users` → daemon cannot open `/dev/hidrawN` → `HIDError` →
`  headset permanently shown as "off".
`- **Fix:** add `users.users.${cfg.user}.groups = [ "users" ];` inside
`  `config = lib.mkIf cfg.enable` (one line).
`- **Verify:** `nixos-rebuild switch`, then `journalctl --user -u hs80max`
`  shows no "no permission" warnings; `status.json` reports a real battery.
`
`### 2. `install.sh` has the same udev group problem
``install.sh` (L32-35)
`- Installed udev rule uses `GROUP="users"`; the script never checks that
`  the invoking user is in `users`, nor adds them.
`- **Fix:** after writing the rule, run
`  `id -nG | grep -qw users || "$SUDO" usermod -aG users "$USER"` and print a
`  note that group membership takes effect at the next login.
`- **Verify:** `bash -n install.sh`; manual run on a non-`users` account.
`
`### 3. NixOS D-Bus session policy is installed where nothing reads it
``service/nixos/hs80max.nix` (activation `hs80max-dbus` ~L96-99)
`- Policy file is copied to `$out/lib/dbus-1/session.conf.d/`. Session bus
`  daemons read policies from `/etc/dbus-1/session.conf.d/` and
`  `/run/dbus/session.conf.d/` — never from an activation script's `$out`.
`  Result: policy never takes effect, daemon cannot own
`  `com.corsair.hs80max`, `request_name` raises, crash-loop every 5 s.
`- **Fix:** change the activation target from `$out/lib/dbus-1/session.conf.d`
`  to `/run/dbus/session.conf.d/` (read by the daemon at session-bus start).
`- **Verify:** `nixos-rebuild switch`, `systemctl --user status hs80max`
`  stable (no restarts), `dbus-send ... GetStatus` replies.
`
`## Should fix
`
`### 4. One bad hidraw entry kills the whole device scan
``service/hs80max_service/hid_protocol.py` `find_control_hidraw()` (~L110-133)
`- `except ValueError` at ~L123 does not catch `IndexError` (fewer than 3
`  `:`-separated parts, e.g. bluetooth/i2c hidraw entries) or `OSError` from
`  `os.path.realpath` (symlink loop) at ~L129 → exception escapes the scan
`  loop → poller logs "poll iteration failed" every cycle, no status at all.
`- **Fix:** widen the except to `(ValueError, IndexError, OSError)`. One line.
`- **Verify:** new unit test: fake `/sys/class/hidraw` listing containing a
`  malformed entry followed by the real control entry → `find_control_hidraw()`
`  still returns the control node.
`
`### 5. `HS80Service` mutated from two threads without a lock
``service/hs80max_service/dbus_api.py` `publish()` (L149-185)
`- `publish()` runs on the Poller thread; D-Bus method handlers
`  (`GetStatus`, properties) run on the GLib main-loop thread and read the
`  same `self._status`. A concurrent read can observe a torn snapshot
`  (e.g. new `mode` with old `battery`).
`- **Fix:** add `self._lock = threading.Lock()` in `__init__`; acquire it
`  around `self._status = ...` in `publish()` and around the reads in
`  `GetStatus`/`GetBattery`/`GetMicMuted`/properties/`_write_status_file`.
`- **Verify:** existing `test_dbus_signal.py` stays green; add an assertion
`  that `publish()` from a thread and a property read do not raise.
`
`### 6. Mic protocol path has no test
``service/hs80max_service/hid_protocol.py` `_mic_query()` (L306-317)
`- `_is_periodic_report` and `_battery_query` are well tested, but
`  `_mic_query` is not: a byte-offset change (e.g. `resp[4]` → `resp[5]`)
`  would pass the whole suite.
`- **Fix:** in `service/test_hid_protocol.py`, add tests with a fake
`  `_read`: report with `resp[4]=0x01` → `True`; `resp[4]=0x00` → `False`;
`  periodic report → `None`; no report → `None`.
`- **Verify:** `service/.venv/bin/pytest service/` green.
`### 7. Extension freezes `STATUS_FILE` at import with UID-1000 fallback
``extension/extension.js` (L45-46)
`- `const STATUS_FILE = \`${GLib.getenv('XDG_RUNTIME_DIR') || '/run/user/1000'}/...``
`  is evaluated once at module import; the `/run/user/1000` fallback is only
`  correct for UID 1000. With an empty `XDG_RUNTIME_DIR` and a different
`  UID, the GFile monitor watches a dead file and never fires.
`- **Fix:** drop the `|| '/run/user/1000'` fallback; in `_startFileMonitor()`
`  if `GLib.getenv('XDG_RUNTIME_DIR')` is null, log a warning and skip
`  monitoring (the 1-minute poll still works).
`- **Verify:** `node --check extension/extension.js`; manual reload in
`  `dbus-run-session -- gnome-shell --devkit`.
`
`### 8. `SessionBus()` crash is not handled cleanly
``service/hs80max_service/main.py` (L181)
`- `bus = SessionBus()` is outside the `try/except`. Starting without a
`  session bus (e.g. login race) raises a raw traceback → `Restart=on-failure`
`  crash-loop every 5 s.
`- **Fix:** move `bus = SessionBus()` into the existing `try/except` block
`  (L182-193).
`- **Verify:** run the daemon with `DBUS_SESSION_BUS_ADDRESS=` unset →
`  clean log line and exit code 1, no traceback.
`
`## Nice to have
`
`### 9. Dead assignment in `find_control_hidraw`
``service/hs80max_service/hid_protocol.py` L122
`- `vid, pid, iface = int(...), int(...), None` — `iface` is overwritten at
`  L129-130 immediately.
`- **Fix:** `vid, pid = int(parts[1], 16), int(parts[2].split(".")[0], 16)`.
`
`### 10. `vscode_shell.nix` does not belong to this project
`- PHP/Composer/pymysql/Node dev shell, an artifact from another
`  environment. No project code uses it.
`- **Fix:** delete `vscode_shell.nix`; remove it from `STRUCTURE.md` if
`  listed (it is not in the current tree listing — double-check).
`
`### 11. Duplicated signal handlers in `main.py`
``service/hs80max_service/main.py` L207-214
`- **Fix:** `for sig in (signal.SIGTERM, signal.SIGINT):` with one
`  `signal.signal(...)` call.
`
`### 12. Unused `selftest()` in `connection.py`
``service/hs80max_service/connection.py` L52-59
`- No caller, no documentation mention; `hid_protocol.selftest()` is the
`  useful, documented equivalent.
`- **Fix:** delete `selftest()` and the `if __name__ == "__main__"` block.
`
`### 13. `install.sh` wrapper pins the checkout path
``install.sh` L48-55
`- Generated wrapper hardcodes `sys.path.insert(0, "$REPO_DIR")`; moving the
`  checkout breaks the daemon with `ModuleNotFoundError`.
`- **Fix:** make the final warning prominent (`echo "WARNING: the wrapper
`  pins this checkout at $REPO_DIR. After moving or updating the repo,
`  re-run this script."`) — full path resolution is overkill for this flow.
`
`
`---
`
`## Implementation order
`
`1. Findings 1-3 (install-path breakage) - one commit:
`   "fix: make NixOS module and install.sh actually grant dongle + D-Bus access"
`2. Findings 4, 8 (robustness, one-line fixes) + new test for #4 - one commit:
`   "fix: harden hidraw scan and D-Bus startup against partial failures"
`3. Findings 5, 6 (threading + mic tests) - one commit:
`   "test+fix: lock service status updates; cover mic query parsing"
`4. Finding 7 (extension file monitor) - one commit:
`   "fix: do not freeze status-file path with UID-1000 fallback"
`5. Findings 9-13 (lean) - one commit:
`   "chore: drop dead code and unrelated dev shell"
`
`## Verification checklist
`
`- [ ] `service/.venv/bin/pytest service/` (all green, incl. new tests)
`- [ ] `python3 -m py_compile service/hs80max_service/*.py`
`- [ ] `bash -n install.sh service/test_dbus.sh`
`- [ ] `node --check extension/extension.js`
`- [ ] Module still evaluates: `nix-instantiate --parse service/nixos/hs80max.nix`
`- [ ] Live: `nixos-rebuild switch` + `systemctl --user status hs80max`
`      (needs dongle; ask user for hardware)
`
`## Not checked during the audit
`
`- `resources/*.hpp`, `resources/battery-protocol.md` (protocol references)
`- `resources/produktblatt.pdf` (binary)
`- Live E2E (`service/test_dbus.sh` - needs the physical dongle)
`- Extension inside a running GNOME shell (`dbus-run-session -- gnome-shell --devkit`)
`- `scratchpad/` (git-ignored, temporary)
`
`## Lean total
`
`-15 lines, -1 file (`vscode_shell.nix`).
