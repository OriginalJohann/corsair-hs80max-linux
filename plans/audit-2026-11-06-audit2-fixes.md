# Plan: Audit fixes (audit-2026-11-06, round 2)

Source: `/ponytail-audit` report, findings 1–4 (finding 5 excluded on user request).

## Subtasks

- [x] **Fix 1** – `service/hs80max_service/main.py`: raise `Poller.stop()` join budget
      from 25 s to 90 s (true worst-case cycle ≈ 81 s: 3 wakes × 4 writes ×
      5 s + reads) and correct the comment.
- [x] **Fix 2** – `extension/extension.js`: convert `_readStatus()` from
      synchronous `bus.call_sync` (4 s timeout can stall the shell main loop)
      to asynchronous `bus.call` with a result callback.
- [x] **Fix 3** – `install.sh`: escape sed replacement metacharacters
      (`\`, `&`, `|`) in `$REPO_DIR` before injecting `Environment=PYTHONPATH`,
      so unusual checkout paths cannot corrupt the installed unit.
- [x] **Fix 4** – `service/test_hid_protocol.py` + `service/test_dbus_signal.py`:
      delete the dead `if __name__ == "__main__":` runner blocks.
- [x] **Verify** – `pytest service/ -q` → 27 passed; `bash -n install.sh` OK;
      `node --check extension/extension.js` OK; sed escaping verified against a
      hostile path (`/tmp/my|repo&x/y\z` → unit line byte-exact, see
      `scratchpad/test_escape.sh`).
- [~] **Commit** – skipped at user request ("lass alles wie es ist").

## Status

Done. Changes left uncommitted on user request.
