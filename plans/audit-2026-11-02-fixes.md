# Audit Fixes – corsair-hs80max-linux (2026-11-02)

Plan for the 2026-11-02 repo audit findings (see `plans/audit-2026-11-01-repo-audit.md`
for the previous round). Implements all findings **except** the
`vscode_shell.nix` one, which is a personal VSCode dev shell the user keeps
in every project by decision.

Each step is independent and committable. Status: `[ ]` pending, `[x]` done.

## Order

### Step 1 – Fix stale D-Bus policy path in NIXOS-SETUP.md (finding 1) `[x]`

`NIXOS-SETUP.md` line 16
- The guide says the session policy is copied to
  `/run/current-system/lib/dbus-1/session.conf.d/` – the pre-fix target.
  The module (`service/nixos/hs80max.nix` activation `hs80max-dbus`) now
  copies it to `/run/dbus/session.conf.d/`.
- Fix: one-line edit of the path in line 16 (German text stays for now;
  the translation in Step 2 must carry the corrected path).
- Verify: `grep -n 'run/dbus/session.conf.d' NIXOS-SETUP.md` hits line 16;
  the old path no longer occurs anywhere in the repo
  (`grep -rn 'run/current-system/lib/dbus-1' .` -> empty).

### Step 2 – Translate NIXOS-SETUP.md to English (finding 4) `[x]`

`NIXOS-SETUP.md` (158 lines)
- Rewrite the whole file in English per AGENTS.md (docs in English).
  Content, section structure (1-9), tables, and all code blocks stay
  unchanged; only prose is translated. The corrected D-Bus path from
  Step 1 must be part of the new text.
- Verify: no German sentences remain (spot-check section headers and
  troubleshooting table); `README.md` link target unchanged.

### Step 3 – Unfreeze STATUS_FILE in the extension (finding 2) `[x]`

`extension/extension.js` (L47-48, L508)
- `const STATUS_FILE = \`${GLib.getenv('XDG_RUNTIME_DIR')}/hs80max/status.json\``
  is evaluated once at module load. If the env var is unset at shell
  startup (boot race), the constant freezes to `null/hs80max/status.json`
  for the whole shell life; only the 1-minute poll then works.
- Fix: delete the `STATUS_FILE` constant (and its comment block) and build
  the path locally inside `_startFileMonitor()` right before
  `Gio.File.new_for_path(...)`, which already guards on
  `GLib.getenv('XDG_RUNTIME_DIR') === null`.
- Verify: `node --check extension/extension.js`; `grep -n STATUS_FILE
  extension/` -> no hits.

### Step 4 – Remove unused D-Bus methods GetBattery/GetMicMuted (finding 3) `[x]`

_Extra caller found during implementation: `service/test_dbus_signal.py:137`
referenced both methods and was updated (reader loop no longer calls them)._

`service/hs80max_service/dbus_api.py` (L41-44, L123-129)
- Neither method has a client: the extension only calls `GetStatus`;
  `test_dbus.sh` uses them purely as a smoke check.
- Fix: delete both methods, their two `interface.add_method` calls, and
  the two introspection-XML blocks (`<arg name="Battery" .../>` and
  `<arg name="MicMuted" .../>` + method tags).
- `service/test_dbus.sh`: remove the two `dbus-send ... GetBattery` /
  `GetMicMuted` lines and adjust the "Methods" header count if printed.
- `plans/audit-fixes-2026-11-01.md` / `plans/audit-2026-11-01-repo-audit.md`:
  no edit needed (historical records).
- Verify: `grep -rn 'GetBattery\|GetMicMuted' service/ extension/` -> no hits;
  `service/.venv/bin/pytest service/ -q` stays green (17 tests);
  `bash -n service/test_dbus.sh` OK.

### Step 5 – Remove .vscode/settings.json (finding 6) `[x]`

`.vscode/settings.json`
- Points `cmake.sourceDirectory` at `scratchpad/headsetcontrol` – a
  git-ignored, post-commit-deleted temp copy of an unrelated project.
- Fix: delete the file (`.vscode/` is git-ignored, so no `git rm` needed;
  plain `rm` of both the file and the empty `.vscode` dir).
- Verify: `ls .vscode` -> no such directory.

### Step 6 – Remove the main.js shim (finding 7) `[x]`

`extension/main.js` (2 lines)
- Re-export shim for shell builds loading `main.js`; `metadata.json`
  pins `shell-version: ["50"]` and GNOME 50 loads `extension.js`, so no
  real target build needs the shim.
- Fix: `git rm extension/main.js`; update `STRUCTURE.md` to drop the
  `main.js` line from the extension tree.
- `install.sh` does not reference `main.js` (only copies `extension/`
  wholesale), so no install change needed.
- Verify: `grep -rn 'main.js' extension/ install.sh STRUCTURE.md` -> no hits.

### Step 7 – Final verification `[x]`

_Result: `pytest` 17 passed; `node --check`, `py_compile`, `bash -n` all OK;
all grep verifications clean (the only remaining old-path / `main.js` hits are
this plan file itself and the GNOME Shell import `resource:///org/gnome/shell/ui/main.js`)._

- `service/.venv/bin/pytest service/ -q` -> all green.
- `node --check extension/extension.js`.
- `service/.venv/bin/python -m py_compile service/hs80max_service/*.py`.
- `bash -n install.sh service/test_dbus.sh`.
- `git status` review; then ask the user for the commit (one commit per
  step, or a single combined commit – user decides).
- `STRUCTURE.md` needs no structural change beyond Step 6 (no files added;
  two removed: `main.js`, `.vscode/settings.json`).

## Skipped by decision

- **Finding 5 – `vscode_shell.nix`:** kept on purpose. It is a personal
  VSCode dev shell the user uses across all projects; out of scope.

## Expected size

- ~2 files deleted (`extension/main.js`, `.vscode/settings.json`).
- ~25 lines removed (D-Bus methods + XML, `STATUS_FILE`, test lines).
- `NIXOS-SETUP.md` rewritten (same line count, English).

