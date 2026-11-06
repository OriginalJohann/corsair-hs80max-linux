# Plan: Fix the 2026-11-06 Audit Findings

Findings from the `/ponytail-audit` report. Finding 2's scope was confirmed
with the user: **remove the `StatusChanged` signal completely**.

## Subtasks

- [ ] 1. `install.sh`: root must get an empty privilege prefix (`SUDO=""`),
      not `true` (which silently no-ops the udev rule write).
- [ ] 2. Remove the dead `StatusChanged` D-Bus signal:
      - `service/hs80max_service/dbus_api.py`: drop the `_dbus_signal` import,
        the `<signal>` block in `INTROSPECTION_XML`, the `StatusChanged`
        attribute and the emission in `publish()`.
      - `service/test_dbus_signal.py`: drop the signal test +
        `RecordingSignal`; keep the status-file and concurrency tests;
        update module docstring.
      - `README.md`: remove the signal from the D-Bus API description.
      - `extension/extension.js`: header comment no longer lists the signal.
- [ ] 3. New test: `find_control_hidraw()` positive path – a fake
      `/sys/class/hidraw` tree (via `monkeypatch` on `os.listdir` /
      `os.readlink` / `os.path.realpath`) must yield the interface-4 node.
- [ ] 4. New test: Poller "off" → "connected" transition – fake
      `HS80HID.status()` returning `(True, 87, False)` must set
      `_mode == "connected"`, `_battery == 87`, `_mic_muted == False`.
- [ ] 5. `.gitignore`: add `.venv/` and `.pytest_cache/`.
- [ ] 6. Run the full pytest suite (`service/.venv/bin/python -m pytest service/ -v`).
- [ ] 7. `bash -n install.sh` syntax check.
- [ ] 8. Update `STRUCTURE.md` (test file description).
- [ ] 9. Commit – **requires user confirmation** (per AGENTS.md).

## Status

In progress.
