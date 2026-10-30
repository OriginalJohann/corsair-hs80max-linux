// Entry-point shim for shell builds that load `main.js` by default (e.g.
// upstream GNOME Shell). This NixOS shell build (GNOME 50.4) hardcodes
// `extension.js` as the entry point, so the real implementation lives there.
// Keeping both files in sync via re-export makes the extension load on both
// kinds of builds without duplicating code.
export {default} from './extension.js';
