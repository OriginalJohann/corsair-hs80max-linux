// Corsair HS80 Max Status - GNOME Shell 50 extension.
//
// Shows *two* small symbolic icons in the top bar (per spec: "two small icons
// next to each other"): a connection icon (headset connected / disconnected)
// and a microphone icon (mic muted / unmuted), followed by the battery
// percentage as the button label. Clicking the button opens a popup with the
// connection mode, battery level and microphone state, plus a menu entry to
// launch pavucontrol (the system volume mixer).
//
// Status data is read from the hs80max-service daemon over the *session*
// D-Bus (name `com.corsair.hs80max`, object `/com/corsair/hs80max`):
//   * `GetStatus() -> a{sv}` carrying {Mode, Battery, MicMuted, UpdatedAt}
//   * signal `StatusChanged(mode: s, battery: i, mic_muted: b)`
//
// Refresh strategy (matches the spec: "update whenever the service updates
// them or after 30 minutes"):
//   1. one initial `GetStatus` read on enable,
//   2. a D-Bus match on `StatusChanged` for instant updates,
//   3. a 30-minute safety-fallback poll in case a signal is missed.
// A D-Bus error on a read is treated as "daemon unreachable" -> the
// extension falls back to the "disconnected" presentation.
//
// D-Bus transport notes (verified against this system's GLib 2.88 / GJS 1.88):
// the high-level proxy API (Gio.DBusProxy, connection.get_object /
// get_object_proxy) has been *removed* from GLib, and the connection's
// watch_name() callback conversion is broken in this GJS build. This
// extension therefore talks to the daemon exclusively through the low-level
// `call_sync()` / `signal_subscribe()` / `signal_unsubscribe()` APIs.

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import St from 'gi://St';
import Clutter from 'gi://Clutter';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

const BUS_NAME = 'com.corsair.hs80max';
const OBJECT_PATH = '/com/corsair/hs80max';
const INTERFACE = 'com.corsair.hs80max';

// Status file the daemon rewrites on every change (see dbus_api.py). We watch
// it with a GFile monitor for live updates because this GJS build drops D-Bus
// signal callbacks. Must stay in sync with HS80Service._status_file_path.
const STATUS_FILE =
    `${GLib.getenv('XDG_RUNTIME_DIR') || '/run/user/1000'}/hs80max/status.json`;

// systemd user unit that provides the D-Bus service. enable() makes sure it
// is running so the extension is self-contained; disable() intentionally does
// NOT stop it (independent user service, survives reloads, reusable by other
// clients). The NixOS module installs the unit under this plain name.
const SERVICE_UNIT = 'hs80max.service';
const SYSTEMCTL = '/run/current-system/sw/bin/systemctl';

// Symbolic icon names - the matching SVGs live in extension/icons/.
const ICON_DISCONNECTED = 'headset-disconnected-symbolic';
const ICON_CONNECTED = 'headset-connected-symbolic';
const ICON_MIC_MUTED = 'mic-mute-symbolic';
const ICON_MIC_UNMUTED = 'mic-unmute-symbolic';

// Volume mixer launched from the menu (system-standard app).
const VOLUME_APP = 'pavucontrol';

// Refresh cadence. The daemon emits StatusChanged, but this GJS build does
// not reliably deliver that signal to the extension (see the header note on
// the broken GDBus wrapper), so the extension re-reads status on this
// interval. Kept at 1 min so the icon self-heals quickly without the signal.
const REFRESH_INTERVAL_S = 60;
// Per-call timeout (ms) so a wedged daemon cannot stall a read.
const CALL_TIMEOUT_MS = 4000;
// Startup race: enable() may run before the daemon owns the bus name, so the
// first read can fail. Retry a few times (every RETRY_INTERVAL_S) so the UI
// self-heals within seconds instead of waiting for the 30-min poll.
const RETRY_INTERVAL_S = 2;
const RETRY_MAX = 5;
// Size (px) of the two status icons shown side by side in the panel.
const ICON_SIZE = 16;


// ---- Small process-spawn helpers -----------------------------------------
// GJS 1.88 removed Utils.spawn_sync / Utils.spawn_async and changed the
// Gio.Subprocess API, so we drive the classic GLib spawn functions directly.
// These wrap the "run a command, get its exit status" case used for systemctl.

// Synchronously run `args`, return { ok, status } where `status` is the
// process exit code. `args` are simple tokens (no unquoted spaces) - our
// callers only pass systemctl subcommands.
function _spawnSync(args) {
    const [ok, , , waitStatus] =
        GLib.spawn_command_line_sync(args.join(' '));
    return { ok, status: (waitStatus >> 8) & 0xff };
}

// Fire-and-forget spawn. Returns true on success, false on failure. Used for
// launching a GUI app (pavucontrol) so the shell keeps running.
function _spawnDetached(args) {
    try {
        return GLib.spawn_command_line_async(args.join(' '));
    } catch (e) {
        console.warn('hs80max: spawn failed for ' + JSON.stringify(args)
            + ': ' + e.message);
        return false;
    }
}


export default class Hs80MaxExtension extends Extension {
    enable() {
        this._mode = 'disconnected';
        this._battery = -1;
        this._micMuted = false;
        this._updatedAt = 0;
        this._wasReachable = false;

        this._iconBox = null;
        this._connectionIcon = null;
        this._micIcon = null;
        this._statusButton = null;
        this._clickGesture = null;
        this._menu = null;
        this._menuStatus = null;
        this._menuMode = null;
        this._menuBattery = null;
        this._menuMic = null;
        this._menuUpdated = null;
        this._fileMonitor = null;
        this._pollId = 0;
        this._retries = 0;
        this._retryId = 0;
        this._connectionIconName = null;
        this._micIconName = null;

        // The status icon is cosmetic: a failure creating it must never take
        // down the shell or block the D-Bus / refresh setup below.
        try {
            this._createStatusIcon();
        } catch (e) {
            console.warn('hs80max: status icon creation failed: ' + e.message);
        }

        // A failure here must never take down the shell: enable() runs
        // synchronously at shell startup. Keep the bar in its
        // "disconnected" state and log instead of throwing.
        try {
            // Make sure the daemon is running first (one-shot start if not).
            this._ensureDaemon();
            // Read once now, then react to StatusChanged and a 30-min fallback.
            this._readStatus();
            console.log('hs80max: DBG after readStatus');
            this._startSignalMatch();
            console.log('hs80max: DBG after startSignalMatch');
            this._startPolling();
            console.log('hs80max: DBG after startPolling');
        } catch (e) {
            console.warn('hs80max: enable failed: ' + e.message);
        }
    }

    disable() {
        this._stopSignalMatch();
        this._stopPolling();
        if (this._retryId > 0) {
            GLib.source_remove(this._retryId);
            this._retryId = 0;
        }

        // Intentionally do NOT stop the daemon: it is an independent user
        // service that other D-Bus clients may use, and it must survive
        // shell restarts and extension reloads.
        this._destroyStatusIcon();
    }

    // Load one of the extension's own symbolic SVGs by base name (without the
    // ".svg" suffix) and return a Gio.Icon (a Gio.FileIcon pointing at the
    // file inside extension/icons/). Loading by absolute path bypasses the
    // system icon theme - which does NOT search the extension folder - and is
    // what makes the custom SVGs render reliably.
    _loadIcon(name) {
        const uri = 'file://' + this.path + '/icons/' + name + '.svg';
        const file = Gio.file_new_for_uri(uri);
        return new Gio.FileIcon({ file });
    }

    // Resolve the right-hand status container of the top bar. In this shell
    // build `Main.panel._rightBox` is not exposed, so we fall back to walking
    // `Main.panel.box` and picking the last horizontal box whose children do
    // not all x_expand (that skips the centre clock box). Appending to it lets
    // our indicator order dynamically next to the other status icons.
    _panelStatusContainer() {
        const panel = Main.panel;
        if (!panel)
            return null;
        if (panel._rightBox)
            return panel._rightBox;

        const box = panel.box;
        if (box && box.get_children) {
            const children = box.get_children();
            for (let i = children.length - 1; i >= 0; i--) {
                const c = children[i];
                if (!c || !c.get_children)
                    continue;
                const kids = c.get_children();
                if (kids.length === 0)
                    continue;
                const allExpand = kids.every((k) => k && k.x_expand);
                if (!allExpand)
                    return c;
            }
        }
        return box || null;
    }


    _createStatusIcon() {
        // Re-entrancy guard: if a previous status icon is still around
        // (e.g. a failed enable left one behind), tear it down first so we
        // never end up with two top-bar items.
        if (this._statusButton)
            this._destroyStatusIcon();

        // Two symbolic icons side by side: connection + microphone. Both are
        // loaded by absolute file path (see _loadIcon) so they render from the
        // extension's own icons/ folder regardless of the icon theme.
        this._connectionIcon = new St.Icon({
            'gicon': this._loadIcon(ICON_DISCONNECTED),
            'style_class': 'hs80max-icon',
            'width': ICON_SIZE,
            'height': ICON_SIZE,
            'y_align': 0.5,
        });
        this._micIcon = new St.Icon({
            'gicon': this._loadIcon(ICON_MIC_UNMUTED),
            'style_class': 'hs80max-icon',
            'width': ICON_SIZE,
            'height': ICON_SIZE,
            'y_align': 0.5,
        });
        this._iconBox = new St.BoxLayout();
        this._iconBox.orientation = 0;
        this._iconBox.style_class = 'hs80max-icon-box';
        this._iconBox.halign = 0.5;
        this._iconBox.valign = 0.5;
        this._iconBox.add_child(this._connectionIcon);
        this._iconBox.add_child(this._micIcon);

        // Create the panel button as a plain St.Button. This is the reliable
        // path: in GNOME Shell 50 a PanelMenu.Button added to the panel's
        // right box gets wrapped in an St.Bin that is never laid out (0x0,
        // unmapped), so it never renders. A plain St.Button with the
        // "status-button" style class renders identically to the shell's own
        // status indicators (verified).
        const button = new St.Button({ label: '' });
        // style_classes is not accepted in the St.Button constructor in this
        // shell version, so add the class directly.
        try { button.add_style_class('status-button'); }
        catch (e) { /* cosmetic */ }
        button.x_expand = false;
        button.y_expand = true;
        // A Clutter.ClickGesture is what turns a click on the button into a
        // menu open/close - exactly how the shell's own PanelMenuButton works
        // (verified against GNOME Shell 50's panelMenu.js). The menu is
        // created eagerly below; the handler toggles it (a click before the
        // menu exists is a harmless no-op).
        this._clickGesture = new Clutter.ClickGesture();
        this._clickGesture.set_recognize_on_press(true);
        this._clickGesture.connect('recognize', () => {
            if (this._menu)
                this._menu.toggle();
        });
        button.add_action(this._clickGesture);
        // The button renders through its `child`; the icon box becomes the
        // content so the panel shows "<headset icon><mic icon><battery %>".
        button.child = this._iconBox;
        this._statusButton = button;

        // Build the popup menu eagerly. The menu's actor is a BoxPointer that
        // anchors to the button; per the shell's own PanelMenuButton the menu
        // actor must be added to Main.uiGroup (the shell's UI overlay group)
        // and hidden until opened. The ClickGesture above toggles it.
        this._menu = new PopupMenu.PopupMenu(this._statusButton,
            St.Side.LEFT, St.Side.TOP);
        this._menu.actor.add_style_class_name('panel-menu');
        Main.uiGroup.add_child(this._menu.actor);
        this._menu.actor.hide();
        this._buildMenu();

        // Insert into the top panel, on the RIGHT side, so it orders next to
        // the other status indicators.
        const container = this._panelStatusContainer();
        if (container) {
            container.add_child(this._statusButton);
        } else {
            console.warn('hs80max: could not find a panel container '
                + '(Main.panel); status icon disabled.');
            return;
        }

        this._updateLabel();
        this._refreshUi();
    }

    // Build the menu contents: a live status summary, a detailed breakdown
    // (mode / battery / mic / last update) and a control entry that opens the
    // system volume mixer (pavucontrol).
    _buildMenu() {
        const menu = this._menu;

        // --- Live status summary (updated on every status change) ---
        this._menuStatus = new PopupMenu.PopupMenuItem('…');
        this._menuStatus.actor.set_reactive(false);
        menu.addMenuItem(this._menuStatus);

        menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        // --- Detailed status rows (live) ---
        this._menuMode = new PopupMenu.PopupMenuItem('Modus: –');
        this._menuMode.actor.set_reactive(false);
        menu.addMenuItem(this._menuMode);

        this._menuBattery = new PopupMenu.PopupMenuItem('Akku: –');
        this._menuBattery.actor.set_reactive(false);
        menu.addMenuItem(this._menuBattery);

        this._menuMic = new PopupMenu.PopupMenuItem('Mikrofon: –');
        this._menuMic.actor.set_reactive(false);
        menu.addMenuItem(this._menuMic);

        this._menuUpdated = new PopupMenu.PopupMenuItem('Aktualisiert: –');
        this._menuUpdated.actor.set_reactive(false);
        menu.addMenuItem(this._menuUpdated);

        menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());

        // --- Control section: open the system volume mixer ---
        menu.addAction('Lautstärke (PulseAudio)', () => this._openVolumeApp());

        // Reflect the current state on first build.
        this._updateMenuStatus();
    }


    // Refresh the status summary + the detailed rows (mode / battery / mic /
    // last update) inside the menu. Any mode other than "disconnected"
    // (e.g. "connected" / "wireless") is treated as "verbunden".
    _updateMenuStatus() {
        if (!this._menuStatus)
            return;

        const connected = this._mode !== 'disconnected';
        const batteryText = this._battery >= 0 ? this._battery + ' %' : '-- %';

        // Summary line.
        let summary;
        if (connected) {
            summary = 'Verbunden · ' + batteryText
                + (this._micMuted ? ' · Mikro stumm' : '');
        } else {
            summary = 'Getrennt';
        }
        this._menuStatus.label.set_text(summary);

        // Detailed rows.
        if (this._menuMode)
            this._menuMode.label.set_text(
                'Modus: ' + (connected ? 'verbunden (' + this._mode + ')'
                    : 'getrennt'));
        if (this._menuBattery)
            this._menuBattery.label.set_text('Akku: ' + batteryText);
        if (this._menuMic)
            this._menuMic.label.set_text(
                'Mikrofon: ' + (this._micMuted ? 'stumm' : 'aktiv'));
        if (this._menuUpdated)
            this._menuUpdated.label.set_text('Aktualisiert: '
                + this._formatUpdatedAt());
    }

    // Format the daemon's epoch-ms update timestamp as a relative age.
    _formatUpdatedAt() {
        if (!this._updatedAt || this._updatedAt <= 0)
            return '–';
        const ageMs = Date.now() - this._updatedAt;
        if (ageMs < 15000)
            return 'gerade eben';
        const s = Math.round(ageMs / 1000);
        if (s < 60)
            return 'vor ' + s + ' s';
        const m = Math.floor(s / 60);
        if (m < 60)
            return 'vor ' + m + ' min';
        const h = Math.floor(m / 60);
        return 'vor ' + h + ' h';
    }

    _destroyStatusIcon() {
        // Close and destroy the popup menu before tearing the button down.
        // Destroying the PopupMenu tears down its items and its BoxPointer
        // actor (a child of Main.uiGroup).
        if (this._menu) {
            try { this._menu.close(); } catch (e) { /* cosmetic */ }
            try { this._menu.destroy(); } catch (e) { /* cosmetic */ }
        }
        this._menu = null;
        this._menuStatus = null;
        this._menuMode = null;
        this._menuBattery = null;
        this._menuMic = null;
        this._menuUpdated = null;
        this._uiActor = null;

        if (this._statusButton) {
            if (this._statusButton.parent)
                this._statusButton.parent.remove_child(this._statusButton);
            this._statusButton.destroy();
            this._statusButton = null;
        }
        this._iconBox = null;
        this._connectionIcon = null;
        this._micIcon = null;
        this._clickGesture = null;
    }


    // ---- D-Bus refresh ------------------------------------------------------

    // Read the current status from the daemon once. A successful GetStatus
    // means the daemon is reachable (and carries the live status); a D-Bus
    // error means the daemon is not reachable right now, so we present
    // "disconnected".
    _readStatus() {
        const bus = Gio.DBus.session;
        if (!bus)
            return;

        let ok = false;
        let status = null;

        try {
            const reply = bus.call_sync(
                BUS_NAME,
                OBJECT_PATH,
                INTERFACE,
                'GetStatus',
                new GLib.Variant('()', []),
                null,
                0,
                CALL_TIMEOUT_MS,
                null,
            );
            if (reply) {
                // The reply is a `a{sv}` dictionary. Note: `get_dict()` is NOT
                // available on GLib.Variant in modern GJS (the old wrapper
                // helper was removed), so unpack the variant recursively
                // into plain JS values. For a dictionary variant this yields
                // an array with the dictionary object as its single element.
                const dict = reply.recursiveUnpack()[0] ?? {};
                status = {
                    mode: typeof dict['Mode'] === 'string'
                        ? dict['Mode'] : 'disconnected',
                    battery: typeof dict['Battery'] === 'number'
                        ? dict['Battery'] : -1,
                    micMuted: typeof dict['MicMuted'] === 'boolean'
                        ? dict['MicMuted'] : false,
                    updatedAt: typeof dict['UpdatedAt'] === 'number'
                        ? dict['UpdatedAt'] : 0,
                };
                ok = true;
            }
        } catch (e) {
            // Expected while the daemon is down (name not known, service not
            // known, timeout). Treated as "disconnected" below.
            ok = false;
        }

        if (ok) {
            this._applyStatus(status.mode, status.battery, status.micMuted,
                status.updatedAt);
            this._retries = 0;
            if (this._retryId > 0) {
                GLib.source_remove(this._retryId);
                this._retryId = 0;
            }
        } else {
            this._applyStatus('disconnected', -1, false, 0);
            if (this._retries < RETRY_MAX) {
                this._retries += 1;
                if (this._retryId === 0) {
                    this._retryId = GLib.timeout_add_seconds(
                        GLib.PRIORITY_DEFAULT, RETRY_INTERVAL_S, () => {
                            this._retryId = 0;
                            this._readStatus();
                            return false;
                        });
                }
            }
        }

        if (ok !== this._wasReachable) {
            console.log('hs80max: ' + (ok ? 'daemon reachable'
                : 'daemon unreachable'));
            this._wasReachable = ok;
        }
    }

    // Watch the daemon's status file for live updates. This GJS build drops
    // D-Bus signal callbacks (signal_subscribe never fires, and
    // add_match_rule / the connection "message" signal are not exposed),
    // so a GFile monitor is the reliable wake-up: the daemon rewrites
    // status.json on every change, we re-read status on each monitor fire.
    _startSignalMatch() {
        if (this._signalConnected)
            return;
        try {
            const file = Gio.File.new_for_path(STATUS_FILE, null);
            this._fileMonitor = file.monitor(Gio.FileMonitorFlags.NONE, null);
            this._fileMonitor.connect('changed',
                (f, other, ev) => this._onStatusFileChanged());
            this._signalConnected = true;
        } catch (e) {
            console.warn('hs80max: watching status file failed: '
                + e.message);
            this._signalConnected = false;
        }
    }

    _stopSignalMatch() {
        if (this._fileMonitor) {
            try {
                this._fileMonitor.cancel_monitor();
            } catch (e) { /* cosmetic */ }
        }
        this._fileMonitor = null;
        this._signalConnected = false;
    }

    // A monitor event means the daemon's status file changed: re-read the
    // live status (the file is only the wake-up, not the data source).
    _onStatusFileChanged() {
        this._readStatus();
    }

    // Start the 30-minute safety-fallback poll (spec: "or after 30 minutes").
    // The callback returns true so the source keeps firing until
    // _stopPolling() removes it.
    _startPolling() {
        if (this._pollId > 0)
            return;
        this._pollId = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT,
            REFRESH_INTERVAL_S, () => {
                // Re-ensure the daemon: if it died, start it again so the
                // re-read below has something to talk to.
                this._ensureDaemon();
                this._readStatus();
                return true;
            });
    }

    _stopPolling() {
        if (this._pollId > 0) {
            GLib.source_remove(this._pollId);
            this._pollId = 0;
        }
    }


    // ---- UI updates ---------------------------------------------------------

    // Apply a status snapshot and refresh the UI only when it changed.
    _applyStatus(mode, battery, micMuted, updatedAt) {
        const changed =
            mode !== this._mode ||
            battery !== this._battery ||
            micMuted !== this._micMuted;
        this._mode = mode;
        this._battery = battery;
        this._micMuted = micMuted;
        this._updatedAt = updatedAt;
        if (changed)
            this._refreshUi();
    }

    // Update the two panel icons from the current state. The connection icon
    // tracks `Mode` (anything but "disconnected" counts as connected); the mic
    // icon tracks `MicMuted` and is only meaningful while connected. Icons are
    // swapped via set_gicon() using absolute file icons (see _loadIcon).
    _updateIcons() {
        if (!this._connectionIcon || !this._micIcon)
            return;

        const connected = (this._mode !== 'disconnected');
        const connectionName = connected ? ICON_CONNECTED : ICON_DISCONNECTED;
        const micName = connected
            ? (this._micMuted ? ICON_MIC_MUTED : ICON_MIC_UNMUTED)
            : ICON_MIC_MUTED;

        // Only touch the icon when it actually changes to avoid needless
        // relayout of the panel on every refresh. Log the swap so state
        // transitions are visible in the shell log (changes are rare).
        if (this._connectionIconName !== connectionName) {
            this._connectionIconName = connectionName;
            console.log('hs80max: connection icon -> ' + connectionName);
            this._connectionIcon.set_gicon(this._loadIcon(connectionName));
        }
        if (this._micIconName !== micName) {
            this._micIconName = micName;
            console.log('hs80max: mic icon -> ' + micName);
            this._micIcon.set_gicon(this._loadIcon(micName));
        }
    }

    _updateLabel() {
        if (!this._statusButton)
            return;

        const text = (this._battery >= 0) ? String(this._battery) : '';
        // The button label is what the top bar renders next to the icons.
        try {
            if (this._statusButton.label)
                this._statusButton.label.set_text(text);
        } catch (e) { /* label update is cosmetic */ }
    }

    _refreshUi() {
        this._updateIcons();
        this._updateMenuStatus();
        this._updateLabel();
    }

    // Open the system volume mixer (pavucontrol). Spawned detached so the
    // shell keeps running while the app is in the foreground.
    _openVolumeApp() {
        _spawnDetached([VOLUME_APP]);
    }

    // Make sure the daemon is running. It is a long-lived systemd user
    // service; if it is not active we start it as a one-shot (Start) and let
    // the initial read + signal match pick it up once it owns the bus name.
    _ensureDaemon() {
        let active = false;
        try {
            const { status } = _spawnSync(
                [SYSTEMCTL, '--user', 'is-active', SERVICE_UNIT]);
            active = (status === 0);
        } catch (e) {
            active = false;
        }

        if (active)
            return;

        try {
            _spawnSync([SYSTEMCTL, '--user', 'start', SERVICE_UNIT]);
            console.log('hs80max: started ' + SERVICE_UNIT);
        } catch (e) {
            // systemd user bus unavailable (e.g. during early boot).
            console.warn('hs80max: could not start daemon: ' + e.message);
        }
    }
}

