"""D-Bus API for the HS80 Max status service.

Exposes ``com.corsair.hs80max`` on the session bus with:

* Properties: ``Mode`` (s: ``disconnected`` | ``off`` | ``connected``),
  ``Battery`` (i, -1 = unavailable),
  ``MicMuted`` (b), ``UpdatedAt`` (t, epoch ms)
* Methods:    ``GetStatus() -> a{sv}``

Built on ``pydbus`` (available in ``shells/dev.nix``).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field

from gi.repository import GLib

log = logging.getLogger("hs80max.dbus")

BUS_NAME = "com.corsair.hs80max"
OBJECT_PATH = "/com/corsair/hs80max"
INTERFACE = "com.corsair.hs80max"

# Rewrite the status file at most once per this many seconds, even when the
# status values did not change. The file's mtime is the liveness signal:
# without this, a permanently disconnected dongle (values never change
# again) would leave the file stale forever and "updated_at" in it would
# age without bound while the daemon is perfectly healthy.
STATUS_FILE_REFRESH_S = 60.0

# D-Bus introspection XML (parsed by pydbus via Gio.DBusNodeInfo).
# Defines methods and readable properties.
INTROSPECTION_XML = """
<node>
  <interface name="com.corsair.hs80max">
    <method name="GetStatus">
      <arg name="status" type="a{sv}" direction="out"/>
    </method>
    <property name="Mode" type="s" access="read"/>
    <property name="Battery" type="i" access="read"/>
    <property name="MicMuted" type="b" access="read"/>
    <property name="UpdatedAt" type="t" access="read"/>
  </interface>
</node>
"""


@dataclass
class Status:
    """Current headset status snapshot."""

    mode: str = "disconnected"  # disconnected | off | connected
    battery: int = -1  # percent 0..100, -1 = unavailable
    mic_muted: bool = True  # unknown state reads as muted (headset starts muted)
    updated_at: float = field(default_factory=time.time)


class HS80Service:
    """pydbus service object published at OBJECT_PATH."""

    def __init__(self, bus) -> None:
        self._bus = bus
        self._status = Status()
        # Guards _status: publish() runs on the Poller thread while D-Bus
        # method/property handlers run on the GLib main-loop thread.
        self._lock = threading.Lock()
        # Last time the status file was (re)written (monotonic); used to
        # keep the file fresh even when the values stop changing.
        self._last_file_write = 0.0

    # ---------------------------------------------------------- properties
    @property
    def Mode(self) -> str:
        with self._lock:
            return self._status.mode

    @property
    def Battery(self) -> int:
        with self._lock:
            return self._status.battery

    @property
    def MicMuted(self) -> bool:
        with self._lock:
            return self._status.mic_muted

    @property
    def UpdatedAt(self) -> int:
        with self._lock:
            return int(self._status.updated_at * 1000)

    def GetStatus(self) -> dict:
        """Return status as ``a{sv}``.

        pydbus does not auto-wrap dict values into ``GLib.Variant`` for
        ``a{sv}`` returns, so we wrap each value explicitly with the
        correct D-Bus type signature.
        """
        with self._lock:
            status = self._status
            return {
                "Mode": GLib.Variant("s", status.mode),
                "Battery": GLib.Variant("i", status.battery),
                "MicMuted": GLib.Variant("b", status.mic_muted),
                "UpdatedAt": GLib.Variant("t", int(status.updated_at * 1000)),
            }

    # ------------------------------------------------------ status file
    # This GJS build cannot deliver D-Bus signals to the extension (the
    # signal_subscribe wrapper drops callbacks), so the extension watches a
    # status file with a GFile monitor for live updates. We (re)write it
    # atomically on every status change.
    @property
    def _status_file_path(self) -> str:
        runtime = os.environ.get(
            "XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}",
        )
        return os.path.join(runtime, "hs80max", "status.json")

    def _write_status_file(self, status: Status | None = None) -> None:
        path = self._status_file_path
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with self._lock:
                # ``status`` is the snapshot the caller already took under
                # the lock; defaulting to the current one keeps this safe
                # when called directly.
                snapshot = status if status is not None else self._status
                payload = {
                    "mode": snapshot.mode,
                    "battery": snapshot.battery,
                    "mic_muted": snapshot.mic_muted,
                    "updated_at": int(snapshot.updated_at * 1000),
                }
            tmp = f"{path}.tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(payload, fh)
            os.replace(tmp, path)  # atomic: watchers never see a partial file
        except OSError as e:
            log.warning("failed to write status file: %s", e)

    # -------------------------------------------------------------- update
    def publish(self, status: Status) -> bool:
        """Store a new status and rewrite the status file.

        The status file is the extension's data path (this GJS build drops
        D-Bus signal delivery), so it is rewritten atomically on every
        status change – and additionally at most once per
        ``STATUS_FILE_REFRESH_S`` seconds, so the file stays fresh even when
        the values stop changing (e.g. a permanently disconnected dongle)
        and its mtime remains a liveness signal. ``updated_at`` keeps
        meaning "time of the last real status change". Returns True when
        the status changed.
        """
        changed = False
        rewrite = False
        snapshot: Status | None = None
        with self._lock:
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
            # The file needs a rewrite on a status change, or when it has
            # gone stale (values unchanged for a long time).
            rewrite = (
                changed
                or time.monotonic() - self._last_file_write
                >= STATUS_FILE_REFRESH_S
            )
            if rewrite:
                self._last_file_write = time.monotonic()
                # Snapshot under the lock so the write (which happens
                # outside it) cannot lose an interleaved status change.
                snapshot = self._status
        if rewrite:
            self._write_status_file(snapshot)
        return changed
