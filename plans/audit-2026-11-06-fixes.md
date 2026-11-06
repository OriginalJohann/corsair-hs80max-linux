# Audit 2026-11-06 – Implementation Plan

Implements all audit findings except #4 (vscode_shell.nix) and #5
(scratchpad/*.nix) – those are handled manually by the user.

## Subtasks

- [x] #1 extension.js: remove `_ensureDaemon()` from the 60 s poll tick (shell main-loop block)
- [x] #2 install.sh: drop silent `usermod -aG users`, print hint instead
- [x] #3 delete `service/dbus/` + install.sh step 3/6, renumber steps
- [x] #6 test_dbus.sh: policy `user="*"` (was `fne`), wait-loop instead of `sleep 10`
- [x] #7 install.sh: guard `sed` against unit without `ExecStart=`, confirm before overwriting
- [x] #8 install.sh: unit runs `python3 -m hs80max_service.main` with `PYTHONPATH`, drop wrapper script
- [x] #9 main.py: call `connection.dongle_present()` directly, delete `connection_mode()` wrapper
- [x] #10 test_dbus.sh: run via `service/.venv/bin/python` (no nix-shell), clean up `/tmp/dbus-test.conf`
- [x] tests: `service/.venv/bin/python -m pytest service/ -q` (23 passed)
- [x] `bash -n` on install.sh / test_dbus.sh, `node --check` on extension.js
- [x] STRUCTURE.md updated (service/dbus/ removed)
