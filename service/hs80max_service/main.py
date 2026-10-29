"""HS80 Max status service – daemon entry point.

Polls the connection mode (PipeWire/USB) and the headset battery level
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
from pathlib import Path

from pydbus import SessionBus

from . import connection
from .dbus_api import BUS_NAME, HS80Service, INTROSPECTION_XML, OBJECT_PATH, Status
from .hid_protocol import HIDError, HS80HID

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
    unplugged, no audio interface); a mere control-channel timeout does not
    drop the connection state.
    """

    def __init__(self, service: HS80Service) -> None:
        self._service = service
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # Sticky state: last known values (None = never observed yet).
        self._battery: int | None = None
        self._mic_muted: bool | None = None
        self._mode: str = "disconnected"

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
        # 1. Connection mode (fast, PipeWire/USB based).
        mode = connection.connection_mode()
        if mode == "disconnected":
            # Physical disconnect: the headset is gone, so the last battery /
            # mic values are no longer meaningful.  Reset them to "unknown".
            self._mode = "disconnected"
            self._battery = None
            self._mic_muted = None
        else:
            self._mode = mode
            # 2. Try to refresh battery + mic (only when the channel answers).
            self._refresh_hid()

        # 3. Publish the sticky state (unknown values map to -1 / False).
        self._service.publish(Status(
            self._mode,
            -1 if self._battery is None else self._battery,
            False if self._mic_muted is None else self._mic_muted,
        ))

    def _refresh_hid(self) -> None:
        """Refresh battery + mic; keep the last known value on failure."""
        try:
            hid = HS80HID()
            hid.open()
            try:
                battery, mic = hid.status()
            finally:
                hid.close()
        except HIDError as exc:
            log.warning("HID query failed: %s", exc)
            return
        # Update only the values the headset actually reported this cycle.
        if battery is not None:
            self._battery = battery
        if mic is not None:
            self._mic_muted = mic


def main() -> int:
    _configure_logging()
    bus = SessionBus()
    try:
        # request_name with replace=True so that, if a stale instance of
        # this service is still holding the bus name (e.g. after an unclean
        # shutdown), this instance takes ownership instead of raising
        # "name already exists on the bus" and crash-looping. allow_
        # replacement=True lets a *newer* instance take over from this
        # one as well, so the always-newest instance wins and the daemon
        # self-heals rather than failing.
        bus.request_name(BUS_NAME, allow_replacement=True, replace=True)
    except Exception:
        log.exception("could not register D-Bus name %s", BUS_NAME)
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
    signal.signal(
        signal.SIGTERM,
        lambda *_: GLib.idle_add(loop.quit),
    )
    signal.signal(
        signal.SIGINT,
        lambda *_: GLib.idle_add(loop.quit),
    )
    loop.run()

    log.info("shutting down")
    poller.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
