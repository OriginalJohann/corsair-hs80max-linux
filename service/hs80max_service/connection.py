"""Connection detection for the HS80 Max.

The daemon's overall connection ``Mode`` has three values:

* ``connected``    – the wireless dongle is plugged in (headset reachable).
* ``off``          – the dongle is present but its control channel could not
  be opened (headset powered off); layered on by the :class:`Poller`.
* ``disconnected`` – the dongle is not present.

This module derives ``connected`` vs. ``disconnected`` from the dongle
(1b1c:0a97); the ``off`` state is added by the poller. Battery and mic state
are provided separately by :mod:`hid_protocol` and are *always* sourced from
the dongle.
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
            with open(os.path.join(dev, "idVendor"), encoding="ascii") as fh:
                vid = fh.read().strip()
            with open(os.path.join(dev, "idProduct"), encoding="ascii") as fh:
                pid = fh.read().strip()
        except OSError:
            continue
        if vid.lower() == DONGLE_VENDOR and pid.lower() == DONGLE_PRODUCT:
            return True
    return False


def connection_mode() -> str:
    """Return ``connected`` when the dongle is present, else ``disconnected``."""
    return "connected" if dongle_present() else "disconnected"
