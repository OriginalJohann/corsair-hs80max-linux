"""D-Bus API for the HS80 Max status service.

Exposes ``com.corsair.hs80max`` on the session bus with:

* Properties: ``Mode`` (s), ``Battery`` (i, -1 = unavailable),
  ``MicMuted`` (b), ``UpdatedAt`` (t, epoch ms)
* Methods:    ``GetStatus() -> a{sv}``, ``GetBattery() -> i``,
              ``GetMicMuted() -> b``
* Signal:     ``StatusChanged(mode: s, battery: i, mic_muted: b)``

Built on ``pydbus`` (available in ``shells/dev.nix``).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from pydbus.generic import signal as _dbus_signal
from gi.repository import GLib

log = logging.getLogger("hs80max.dbus")

BUS_NAME = "com.corsair.hs80max"
OBJECT_PATH = "/com/corsair/hs80max"
INTERFACE = "com.corsair.hs80max"

# D-Bus introspection XML (parsed by pydbus via Gio.DBusNodeInfo).
# Defines methods, readable properties and the StatusChanged signal.
INTROSPECTION_XML = """
<node>
  <interface name="com.corsair.hs80max">
    <method name="GetStatus">
      <arg name="status" type="a{sv}" direction="out"/>
    </method>
    <method name="GetBattery">
      <arg name="battery" type="i" direction="out"/>
    </method>
    <method name="GetMicMuted">
      <arg name="muted" type="b" direction="out"/>
    </method>
    <property name="Mode" type="s" access="read"/>
    <property name="Battery" type="i" access="read"/>
    <property name="MicMuted" type="b" access="read"/>
    <property name="UpdatedAt" type="t" access="read"/>
    <signal name="StatusChanged">
      <arg name="mode" type="s"/>
      <arg name="battery" type="i"/>
      <arg name="mic_muted" type="b"/>
    </signal>
  </interface>
</node>
"""


@dataclass
class Status:
    """Current headset status snapshot."""

    mode: str = "disconnected"
    battery: int = -1  # percent 0..100, -1 = unavailable
    mic_muted: bool = False
    updated_at: float = field(default_factory=time.time)


class HS80Service:
    """pydbus service object published at OBJECT_PATH."""

    def __init__(self, bus) -> None:
        self._bus = bus
        self._status = Status()

    # ---------------------------------------------------------- properties
    @property
    def Mode(self) -> str:
        return self._status.mode

    @property
    def Battery(self) -> int:
        return self._status.battery

    @property
    def MicMuted(self) -> bool:
        return self._status.mic_muted

    @property
    def UpdatedAt(self) -> int:
        return int(self._status.updated_at * 1000)

    # -------------------------------------------------------------- signals
    # pydbus emits the D-Bus signal when this attribute is called
    # (ObjectWrapper wires it to the connection).
    StatusChanged = _dbus_signal()

    def GetStatus(self) -> dict:
        """Return status as a{sv} (dict of GLib.Variant values for pydbus)."""
        return {
            "Mode": GLib.Variant("s", self._status.mode),
            "Battery": GLib.Variant("i", self._status.battery),
            "MicMuted": GLib.Variant("b", self._status.mic_muted),
            "UpdatedAt": GLib.Variant("x", int(self._status.updated_at * 1000)),
        }

    def GetBattery(self) -> int:
        return self._status.battery

    def GetMicMuted(self) -> bool:
        return self._status.mic_muted

    # -------------------------------------------------------------- update
    def publish(self, status: Status) -> bool:
        """Store a new status; emit StatusChanged only on changes.

        Returns True when the status changed.
        """
        changed = (
            status.mode != self._status.mode
            or status.battery != self._status.battery
            or status.mic_muted != self._status.mic_muted
        )
        if changed:
            log.info(
                "status changed: mode=%s battery=%s mic_muted=%s",
                status.mode, status.battery, status.mic_muted,
            )
            self._status = status
            # Emit D-Bus signal from the main loop to avoid deadlocks.
            # publish() is called from the Poller thread; dispatching here
            # ensures emit_signal runs in the GLib main-loop context.
            GLib.idle_add(
                lambda: self._bus.con.emit_signal(
                    OBJECT_PATH,
                    INTERFACE,
                    "StatusChanged",
                    GLib.Variant("ay", GLib.Variant("(sib)", (
                        status.mode, status.battery, status.mic_muted,
                    )).get_data_as_bytes()),
                )
            )
        else:
            # Keep the timestamp fresh even without value changes.
            self._status = Status(
                mode=self._status.mode,
                battery=self._status.battery,
                mic_muted=self._status.mic_muted,
                updated_at=status.updated_at,
            )
        return changed
