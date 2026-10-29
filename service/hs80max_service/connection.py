"""Connection detection for the HS80 Max.

Two observable states, both derived from the dongle (1b1c:0a97):

* ``connected``    – the wireless dongle is plugged in (headset reachable).
* ``disconnected`` – the dongle is not present.

Battery and mic state are provided separately by :mod:`hid_protocol` and are
*always* sourced from the dongle.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger("hs80max.connection")

DONGLE_VENDOR = "1b1c"
DONGLE_PRODUCT = "0a97"

USB_DEVICES_DIR = "/sys/bus/usb/devices"


def dongle_present() -> bool:
    """Return True when the HS80 MAX wireless dongle is plugged in.

    Scans ``/sys/bus/usb/devices`` for the dongle's vendor/product ids – a
    cheap sysfs lookup (no subprocess, no external dependency).
    """
    for entry in os.listdir(USB_DEVICES_DIR):
        dev = os.path.join(USB_DEVICES_DIR, entry)
        try:
            vid = open(os.path.join(dev, "idVendor"), encoding="ascii").read().strip()
            pid = open(os.path.join(dev, "idProduct"), encoding="ascii").read().strip()
        except OSError:
            continue
        if vid.lower() == DONGLE_VENDOR and pid.lower() == DONGLE_PRODUCT:
            return True
    return False


def connection_mode() -> str:
    """Return ``connected`` when the dongle is present, else ``disconnected``."""
    return "connected" if dongle_present() else "disconnected"


def selftest() -> None:
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    log.info("dongle present: %s", dongle_present())
    log.info("connection mode: %s", connection_mode())


if __name__ == "__main__":
    selftest()
