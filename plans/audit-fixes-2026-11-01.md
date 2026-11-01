# Audit Fixes – corsair-hs80max-linux (2026-11-01)

Plan for the 9 findings from the repo audit (see chat history 2026-11-01).
Ordered for implementation: safety net first, the one real bug second,
deletions and doc fixes last. Each step is independent and committable.

## Order

### Step 1 – Tests for the protocol parsing (finding 3)
`service/test_dbus_signal.py` pattern → new `service/test_hid_protocol.py`
- Test `_is_periodic_report`: the two known periodic patterns are rejected,
  a valid battery report (value 1..1000 at bytes [4]/[5]) and a
  paired-headset-ID reply pass the filter.
- Test `_battery_query` with a fake `_read` (monkeypatch): valid report →
  percent, periodic report → retry → None, out-of-range → None.
- Test Poller sticky rules in `main.py` with a fake `HS80HID`:
  - dongle unplugged → battery/mic reset to unknown, mode "disconnected"
  - dongle plugged, HID "not found" → mode must NOT flip to "off"
    (this test fails before the Step 2 fix – it is the regression test)
- No hardware needed; run: `python3 -m pytest service/`

### Step 2 – Stale battery on dongle replug (finding 1, the only must-fix)
`service/hs80max_service/main.py` (`_refresh_hid`) + `hid_protocol.py`
- Distinguish in `_refresh_hid`: `HIDError` "dongle not found" (device node
  not created yet after replug) → keep `self._headset_on` untouched;
  any other `HIDError` → `self._headset_on = False` (as today).
- Smallest implementation: raise a distinct exception (or check a message
  sentinel) from `HS80HID.open()` for the not-found case, catch it in
  `_refresh_hid`. 3–6 lines.
- Verify: Step 1 regression test now passes.

### Step 3 – Delete dead code (finding 2)
- Remove `HS80HID.battery_percent()` (`hid_protocol.py:256-264`).
  Grep-verified: no callers anywhere in the tree.

### Step 4 – Rename the misnamed "signal" code in the extension (finding 5)
`extension/extension.js`
- Verified: there is NO D-Bus signal code. `_startSignalMatch()` IS the
  GFile monitor on status.json (the only live-update path); the "D-Bus
  signal" exists only in comments. Deleting it would break live updates.
- Fix: rename `_startSignalMatch` / `_stopSignalMatch` / `_signalConnected`
  to file-monitor names (e.g. `_startFileMonitor` / `_stopFileMonitor`),
  and fix the header + inline comments to say "file monitor + 1 min poll",
  not "D-Bus signal match + 30-min fallback". Rename-only, no behavior change.

### Step 5 – Lean the dev shell (finding 6)
- `shells/dev.nix`: remove `python3Packages.pyusb` (grep-verified: no
  `import usb` in any project code).

### Step 6 – Docs and comments (findings 7, 8, 9)
- `connection.py` module docstring: describe the real three states
  (connected / off / disconnected), not the old two.
- `extension.js`: fix the two "30-minute" comments around the 60 s
  `REFRESH_INTERVAL_S` (lines ~65-69, ~528) to say 1 minute.
- `test_dbus.sh:4`: replace hardcoded `cd /Data/ai/...` with
  `cd "$(cd "$(dirname "$0")/.." && pwd)"`.

## Verification
1. `python3 -m pytest service/` (all green, including new tests)
2. `python3 -m py_compile` over `service/hs80max_service/` (syntax)
3. `bash -n service/test_dbus.sh` (syntax); full E2E run needs dongle
4. Extension: `node --check extension/extension.js` if node is available,
   otherwise manual reload in `dbus-run-session -- gnome-shell --devkit`

## Not done / skipped
- Finding 4 (`vscode_shell.nix`): dropped from this plan on purpose –
  personal VSCode dev shell, not a finding.
- No commit yet: ask the user for confirmation before committing
  (AGENTS.md §7). Suggested message:
  "fix: keep sticky state during dongle replug; add protocol tests; drop dead code and stale docs"
- Findings 7-9 are comment/doc-only; grouped into one step on purpose.
