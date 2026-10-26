"""Connection-mode detection for the HS80 Max.

Three observable states (see resourcen/battery-protocol.md):

* ``disconnected`` – the wireless dongle (1b1c:0a97) is not present.
* ``wired``        – the headset is plugged directly into the PC via USB-C:
                      a *second*, non-receiver HS80 audio device shows up in
                      PipeWire.
* ``wireless``     – the dongle is present and no direct USB-C device is seen.

Battery / mic state is provided separately by :mod:`hid_protocol`.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess

log = logging.getLogger("hs80max.connection")

DONGLE_VENDOR = "1b1c"
DONGLE_PRODUCT = "0a97"
# Substring identifying HS80 audio devices in PipeWire device names.
HS80_NAME_HINT = "HS80"
# The wireless receiver device name fragment (must NOT be counted as a
# direct USB-C device).
RECEIVER_NAME_HINT = "Gaming Receiver"


def dongle_present() -> bool:
    """Return True when the HS80 MAX wireless dongle is plugged in.

    Checks ``/sys/bus/usb/devices`` for a device with the dongle's
    vendor/product ids.
    """
    for entry in os.listdir("/sys/bus/usb/devices"):
        dev = os.path.join("/sys/bus/usb/devices", entry)
        try:
            vid = open(os.path.join(dev, "idVendor"), encoding="ascii").read().strip()
            pid = open(os.path.join(dev, "idProduct"), encoding="ascii").read().strip()
        except OSError:
            continue
        if vid.lower() == DONGLE_VENDOR and pid.lower() == DONGLE_PRODUCT:
            return True
    return False


def pipewire_hs80_devices() -> list[str]:
    """List PipeWire audio device names containing 'HS80'.

    Uses ``wpctl status`` (no external library dependency). Returns an empty
    list when wpctl is unavailable.
    """
    try:
        out = subprocess.run(
            ["wpctl", "status"],
            capture_output=True, text=True, timeout=5, check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    devices: list[str] = []
    section = ""
    for line in out.splitlines():
        stripped = line.strip()
        # Top-level sections ("Audio", "Video") have no leading whitespace
        # or box-drawing characters.
        if line[:1] not in (" ", "│", "├", "└") and stripped and ". " not in stripped:
            section = stripped
        if section != "Audio":
            continue
        # Device lines look like: "│      55. CORSAIR HS80 ... [alsa]"
        # – remove any leading box-drawing characters before matching.
        clean = stripped.lstrip("│├└─ ")
        m = re.match(r"^\d+\. (.+?) \[(\w+)\]", clean)
        if m and m.group(2) == "alsa" and HS80_NAME_HINT in m.group(1):
            devices.append(m.group(1))
    return devices


def connection_mode() -> str:
    """Determine the current connection mode.

    Returns one of ``disconnected``, ``wired``, ``wireless``.
    """
    if not dongle_present():
        return "disconnected"
    for name in pipewire_hs80_devices():
        if HS80_NAME_HINT in name and RECEIVER_NAME_HINT not in name:
            # A direct (USB-C) HS80 audio device is present.
            return "wired"
    return "wireless"


def selftest() -> None:
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    log.info("dongle present: %s", dongle_present())
    log.info("PipeWire HS80 devices: %s", pipewire_hs80_devices())
    log.info("connection mode: %s", connection_mode())


if __name__ == "__main__":
    selftest()
