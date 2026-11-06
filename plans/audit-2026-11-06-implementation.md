# Implementation Plan – Audit Findings (2026-11-06)

Implements all 8 findings from the repo audit (see
`plans/audit-2026-11-06-fixes.md` for the report context).

## Scope

| # | Finding | Files touched | Status |
|---|---------|---------------|--------|
| 1 | Hard-coded NixOS `systemctl` path in extension | `extension/extension.js` | ✅ |
| 2 | Permission error on dongle shown as "headset off" | `service/hs80max_service/hid_protocol.py`, `service/hs80max_service/main.py`, `service/test_hid_protocol.py` | ✅ |
| 3 | `STRUCTURE.md` tree lists non-existent files | `STRUCTURE.md` | ✅ |
| 4 | Systemd unit defined in two places (install.sh sed vs NixOS module) | `service/nixos/hs80max.nix`, `service/hs80max.service`, `install.sh` | ✅ |
| 5 | "Daemon unreachable" fallback sets mic to unmuted | `extension/extension.js` | ✅ |
| 6 | ~40 s poll cycle against an off headset | `service/hs80max_service/hid_protocol.py`, `service/hs80max_service/main.py`, `service/test_hid_protocol.py` | ✅ |
| 7 | `selftest()` CLI undocumented | `README.md` | ✅ |
| 8 | `plans/` accumulates finished audits | `plans/*.md` | ✅ |

## Details

### 1. systemctl path (extension/extension.js)
- Replace the hard-coded `SYSTEMCTL` constant with a resolver:
  `GLib.find_command('systemctl')` (first hit in PATH) with fallback to
  `/run/current-system/sw/bin/systemctl`.
- `_ensureDaemon` / `_restartService` already catch spawn errors; no other
  change needed.

### 2. HIDAccessError (hid_protocol.py, main.py, tests)
- New exception `HIDAccessError(HIDError)` raised from `open()` on
  `PermissionError` (was: generic `HIDError`).
- `Poller._refresh_hid()` in `main.py`: catch `HIDAccessError` like
  `HIDNotFound` – keep last known power state, warn log. No mode flip to
  "off" while the user fixes group membership.
- New regression test in `test_hid_protocol.py`:
  `HIDAccessError` must NOT flip mode to "off" (mirrors the
  `HIDNotFound` test).

### 3. STRUCTURE.md
- Replace `dongle.py` / `poller.py` entries with the real modules
  (`main.py` incl. Poller, `connection.py`, `hid_protocol.py`,
  `dbus_api.py`).
- Add `test_dbus_signal.py` to the tree.

### 4. Single systemd unit source
- `service/hs80max.service` becomes the single source of truth:
  - committed `ExecStart` is the *install.sh* variant
    (`/usr/bin/env python3 -m hs80max_service.main`);
  - `After=graphical-session.target dbus.socket` (both install paths
    benefit; matches the NixOS module).
- `install.sh`: drop both `sed` rewrites (ExecStart + PYTHONPATH insert);
  the generated unit gets `Environment=PYTHONPATH=<checkout>` inserted
  right after the `[Service]` header (single, simple sed).
- `service/nixos/hs80max.nix`: read the committed unit, replace the
  `ExecStart=` line with the wrapper path via `replaceStrings`, write the
  result as a unit file into the store, and install it with
  `systemd.user.units.hs80max = { enable = true; unitFile = ... }`
  (replaces the inline `systemd.user.services` definition).
- Update the unit file header comment accordingly.

### 5. Mic fallback (extension/extension.js)
- `_readStatus()` failure branch: `_applyStatus('disconnected', -1, true, 0)`
  (unknown mic state reads as muted, consistent with `dbus_api.py` and
  `main.py`).

### 6. Shorter timeouts after failed wake (hid_protocol.py, main.py, tests)
- `HS80HID` gains `FAST_READ_TIMEOUT = 2.0` and a `_fast_read` flag.
- `status()`: after `wake_with_retries()` fails, set `_fast_read = True`
  before `_battery_query()`; each `_read` call uses
  `min(timeout, FAST_READ_TIMEOUT)` when the flag is set.
- `Poller.stop()` join budget 45 s → 25 s (worst case is now ≈ 21 s).
- Test: `status()` with failed handshake must call `_read` with the
  reduced timeout (extend the existing off-case test).

### 7. README
- Add the `selftest` CLI to the "Verifying" section:
  `python3 -m hs80max_service.hid_protocol`.

### 8. plans/ cleanup
- Delete finished audit/plan files whose fixes are committed:
  `audit-2026-11-01-repo-audit.md`, `audit-fixes-2026-11-01.md`,
  `audit-2026-11-02-fixes.md`, `extension-revamp.md`.
- Keep `audit-2026-11-06-fixes.md` (active: report + this plan) and this
  plan file.

## Verification
- `service/.venv/bin/python -m pytest service/ -q` (all tests pass).
- `bash -n install.sh` (syntax).
- `node --check extension/extension.js` if node is available.
- Grep checks: no remaining references to `dongle.py` / `poller.py`;
  no remaining `sed` of ExecStart in install.sh.
