"""HS80 Max status service – daemon entry point.

Polls the connection mode (dongle presence) and the headset battery level
(HID protocol) on a timer and publishes the results on the session bus
(``com.corsair.hs80max``).

Run inside the Nix development shell (``shells/dev.nix``), which provides
``pydbus``:

    nix-shell ../shells/dev.nix --command "python3 -m hs80max_service.main"
"""

from __future__ import annotations

import logging
import logging.handlers
import signal
import sys
import threading
import time
from pathlib import Path

from pydbus import SessionBus

from . import connection
from .dbus_api import BUS_NAME, HS80Service, INTROSPECTION_XML, OBJECT_PATH, Status
from .hid_protocol import HIDError, HIDNotFound, HS80HID

log = logging.getLogger("hs80max.main")

# Poll cadence (seconds).
MODE_POLL_INTERVAL = 3.0


def _configure_logging() -> None:
    """Log to stderr and to a rotating file in $XDG_STATE_HOME."""
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        import os
        base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
        log_dir = base / "hs80max"
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / "hs80max.log", maxBytes=1_000_000, backupCount=2
        )
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
        )
        handlers.append(file_handler)
    except OSError:
        pass
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                         format="%(name)s %(levelname)s %(message)s")


class Poller:
    """Background thread keeping the published status up to date.

    Battery, mic state and connection mode are *sticky*: each is updated only
    when the device reports a fresh value (battery / mic) or the connection
    mode changes, and otherwise holds its last known value.  This matches how
    the headset behaves in practice – it answers the control channel only in
    a short window after it wakes up / reconnects and is quiet most of the
    time – so the published values stay stable and readable instead of
    flapping to ``-1`` / ``False`` on every failed handshake.

    ``disconnected`` is only entered on a *physical* disconnect (dongle
    unplugged); a mere control-channel timeout does not drop the
    connection state.

    A *powered-off* headset is a third, distinct state: the dongle stays
    plugged in (USB) while the headset is off, so dongle presence alone
    cannot express it.  Per the verified protocol the headset answers the
    handshake heartbeat only when it is on, so ``off`` is entered whenever
    the shared wake handshake fails and left as soon as one succeeds.
    """

    def __init__(self, service: HS80Service) -> None:
        self._service = service
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # Sticky state: last known values (None = never observed yet).
        self._battery: int | None = None
        self._mic_muted: bool | None = None
        self._mode: str = "disconnected"
        # Last known headset power state (only meaningful while the dongle
        # is plugged in); the first publish after a dongle insertion is
        # always preceded by a fresh handshake, so the initial value is
        # never published.
        self._headset_on: bool = False

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="hs80max-poller", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._poll_once()
            except Exception:  # keep the daemon alive on transient errors
                log.exception("poll iteration failed")
            self._stop.wait(MODE_POLL_INTERVAL)

    def _poll_once(self) -> None:
        # 1. Connection mode (fast, dongle-presence based).
        mode = connection.connection_mode()
        if mode == "disconnected":
            # The dongle is unplugged, so the last battery / mic values are
            # no longer meaningful.  Reset them to "unknown".
            self._mode = "disconnected"
            self._battery = None
            self._mic_muted = None
        else:
            # Dongle in: refresh headset power state + battery + mic.
            # 2. Try to refresh (only when the channel answers).
            self._refresh_hid()
            # ``headset_on`` means "awake": the handshake answered *or* a
            # fresh battery reading came back; "off" only when the
            # handshake failed and no battery reading is available.
            # Per-cycle fact, not sticky.
            self._mode = "connected" if self._headset_on else "off"

        # 3. Publish the sticky state (unknown values map to -1 / muted).
        self._service.publish(Status(
            self._mode,
            -1 if self._battery is None else self._battery,
            # Unknown mic state reads as *muted*: the headset is normally
            # started with the mic off, so an unreadable state must not be
            # displayed as an open microphone.
            True if self._mic_muted is None else self._mic_muted,
        ))

    def _refresh_hid(self) -> None:
        """Refresh power state, battery and mic.

        ``headset_on`` reflects *this* cycle: "on" when the handshake
        answered or a fresh battery reading came back, "off" otherwise.
        Battery and mic keep their last known values when a single query
        fails.

        A :class:`~hs80max_service.hid_protocol.HIDNotFound` (device node not
        created yet after a dongle replug) is treated differently: the last
        known power state is kept, because the node will appear within a
        fraction of a second and the headset is very likely still on.  Any
        other :class:`~hs80max_service.hid_protocol.HIDError` is a real
        unreachable channel and sets ``headset_on`` to False for this cycle.
        """
        try:
            hid = HS80HID()
            hid.open()
            try:
                headset_on, battery, mic = hid.status()
            finally:
                hid.close()
        except HIDNotFound as exc:
            # Device node not present yet (dongle replug in progress): keep
            # the last known power state so the mode does not flip to "off".
            log.warning("HID device node not found yet: %s", exc)
            return
        except HIDError as exc:
            log.warning("HID query failed: %s", exc)
            # The dongle is present but the control channel could not be
            # opened at all: treat the headset as unreachable (off) for
            # this cycle.
            self._headset_on = False
            return
        self._headset_on = headset_on
        # Update only the values the headset actually reported this cycle.
        if battery is not None:
            self._battery = battery
        if mic is not None:
            self._mic_muted = mic


def main() -> int:
    _configure_logging()
    bus = None
    # The session bus reads its policy files only at ITS start. After a plain
    # reboot the policy file (installed by the activation script into the
    # volatile /run/dbus) is absent for a short window, so owning the bus
    # name is refused even though the bus itself is reachable. Retry for a
    # bounded time: the unit is ordered After=dbus.socket (fresh bus at boot,
    # where this window is real) and Before=dbus.service (we join the very
    # first bus), and once the policy file exists the freshly started bus
    # keeps it for the whole session. A policy miss is a transient condition,
    # not a fatal one: without this the unit crash-loops at every boot.
    for _ in range(15):
        try:
            candidate = SessionBus()
            # request_name with replace=True so that, if a stale instance of
            # this service is still holding the bus name (e.g. after an unclean
            # shutdown), this instance takes ownership instead of raising
            # "name already exists on the bus" and crash-looping. allow_
            # replacement=True lets a *newer* instance take over from this
            # one as well, so the always-newest instance wins and the daemon
            # self-heals rather than failing.
            candidate.request_name(BUS_NAME, allow_replacement=True, replace=True)
            bus = candidate
            break
        except Exception:
            # Also covers a missing session bus (e.g. login race): a clean log
            # line and bounded wait instead of a raw traceback crash-loop.
            log.warning("D-Bus name %s not (yet) available, retrying in 2 s",
                        BUS_NAME)
            time.sleep(2)
    if bus is None:
        log.error("could not register D-Bus name %s", BUS_NAME)
        return 1
    service = HS80Service(bus)
    bus.register_object(OBJECT_PATH, service, INTROSPECTION_XML)

    poller = Poller(service)
    poller.start()
    log.info("service started (bus=%s path=%s)", BUS_NAME, OBJECT_PATH)

    # Run until SIGTERM/SIGINT.
    # The GLib main loop must run on the main thread to process D-Bus
    # method calls and signal emissions.
    from gi.repository import GLib

    loop = GLib.MainLoop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: GLib.idle_add(loop.quit))
    loop.run()

    log.info("shutting down")
    poller.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
