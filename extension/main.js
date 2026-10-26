// Corsair HS80 Max Status – GNOME Shell 50 extension.
//
// Shows a headphone icon in the top bar with battery percentage in the
// tooltip. Clicking opens a popup with connection mode, battery level,
// and a menu entry to launch pavucontrol.
//
// All status data comes from the hs80max D-Bus service
// (com.corsair.hs80max on the session bus).

import * as Main from 'gi-main.js';
import * as PanelMenu from 'shell-panel-menu.js';
import * as PopoverMenu from 'shell-popover-menu.js';
import * as Utils from 'shell-utils.js';

const { Gio, GLib, Glib, St, GObject } = imports.gi;

const BUS_NAME = 'com.corsair.hs80max';
const OBJECT_PATH = '/com/corsair/hs80max';
const INTERFACE = 'com.corsair.hs80max';

// Icon names for each connection mode.
const ICONS = {
    disconnected: 'headset-disconnected-symbolic',
    wired: 'headset-connected-symbolic',
    wireless: 'headset-wireless-symbolic',
};

const DEFAULT_ICON = 'headset-disconnected-symbolic';


var Hs80MaxExtension = class Hs80MaxExtension extends Main.Extension {
    enable() {
        this._proxy = null;
        this._statusButton = null;
        this._mode = 'disconnected';
        this._battery = -1;
        this._micMuted = false;

        this._connectDbus();
        this._createStatusIcon();
    }

    disable() {
        if (this._statusButton) {
            this._statusButton.destroy();
            this._statusButton = null;
        }
        if (this._proxy) {
            this._proxy = null;
        }
    }

    // ---------------------------------------------------------- D-Bus proxy

    _connectDbus() {
        const bus = Gio.bus_get_sync(Gio.BusType.SESSION, null);
        try {
            this._proxy = new Gio.DBusProxySync(
                bus,
                {
                    busName: BUS_NAME,
                    objectPath: OBJECT_PATH,
                    interfaceName: INTERFACE,
                }
            );
            this._updateFromProxy();
            this._proxy.connect('g-properties-changed', () => this._updateFromProxy());
            this._proxy.connect('notify::Mode', () => this._updateFromProxy());
            this._proxy.connect('notify::Battery', () => this._updateFromProxy());
            this._proxy.connect('notify::MicMuted', () => this._updateFromProxy());
        } catch (e) {
            console.warn(`hs80max: D-Bus proxy failed: ${e.message}`);
            this._proxy = null;
        }
    }

    _updateFromProxy() {
        if (!this._proxy)
            return;
        try {
            this._mode = this._proxy.get_cached_property('Mode').toString();
            this._battery = this._proxy.get_cached_property('Battery').toInt32();
            this._micMuted = this._proxy.get_cached_property('MicMuted').boolean;
        } catch (e) {
            // Service not ready – keep defaults.
            return;
        }
        this._refreshUi();
    }

    // -------------------------------------------------------- status icon

    _createStatusIcon() {
        this._statusButton = new PanelMenu.Button(0, {
            accessibleLabel: 'Corsair HS80 Max',
        });
        this._icon = new St.Icon({
            style_class: 'system-status-icon',
            icon_name: DEFAULT_ICON,
        });
        this._statusButton.add_child(this._icon);

        // Popup menu with details + volume control.
        const menuManager = new PanelMenu.MenuManager(this._statusButton);
        this._modeLabel = new St.Label({ text: 'No connection' });
        this._batteryLabel = new St.Label({ text: 'Battery: n/a' });
        this._micLabel = new St.Label({ text: 'Mic: on' });
        menuManager.addMenuItem(new PopoverMenu.PopupMenuItem({ label: '' }));
        // Add a separator + info labels.
        const infoBox = new St.BoxLayout({ vertical: true, style_class: 'hs80max-info' });
        infoBox.add_child(this._modeLabel);
        infoBox.add_child(this._batteryLabel);
        infoBox.add_child(this._micLabel);
        menuManager.menu.addActor(infoBox);

        // Volume control menu item.
        const volItem = new PopoverMenu.PopupMenuItem({ label: 'Volume Control' });
        volItem.connect('activate', () => {
            Utils.spawn(['pavucontrol']);
        });
        menuManager.addMenuItem(volItem);

        Main.uiGroup.main.panel.addToStatusArea('hs80max', this._statusButton);
        this._refreshUi();
    }

    _refreshUi() {
        if (!this._icon)
            return;

        // Pick the icon for the current mode.
        const iconName = ICONS[this._mode] || DEFAULT_ICON;
        this._icon.set_icon_name(iconName);

        // Tooltip: battery percentage if available.
        const tip = this._battery >= 0
            ? `HS80 Max – ${this._battery}%`
            : 'HS80 Max – no battery info';
        this._statusButton.setTooltipText(tip);

        // Popup labels.
        if (this._modeLabel)
            this._modeLabel.set_text(`Mode: ${this._mode}`);
        if (this._batteryLabel)
            this._batteryLabel.set_text(
                this._battery >= 0 ? `Battery: ${this._battery}%` : 'Battery: n/a'
            );
        if (this._micLabel)
            this._micLabel.set_text(this._micMuted ? 'Mic: muted' : 'Mic: on');
    }
};
