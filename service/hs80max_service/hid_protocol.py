"""HS80 Max Wireless (1b1c:0a97) HID protocol.

Implements the proprietary receiver/headset protocol as documented in
``ressourcen/battery-protocol.md`` (derived from the reference implementation
``Sapd/HeadsetControl``, class ``CorsairVoidV2W``).

The control channel is the HID interface 4 of the wireless receiver
(exposed on this system as ``/dev/hidraw1``).  Interface 0 is bound to
``snd-usb-audio`` and interfaces 1-3 are secondary HID interfaces that do
not respond to control commands.

All writes are 65 bytes (report ID ``0x00`` + 64 payload bytes); reads are
64-byte IN reports.
"""

from __future__ import annotations

import logging
import os
import re
import sys
import time

log = logging.getLogger("hs80max.hid")

# USB identity of the HS80 MAX wireless receiver.
VENDOR_ID = 0x1B1C
PRODUCT_ID = 0x0A97
# HID interface number of the control channel (see battery-protocol.md).
CONTROL_INTERFACE = 4

# Protocol constants (see resourcen/battery-protocol.md).
RECEIVER_ENDPOINT = 0x08
HEADSET_ENDPOINT = 0x09
MSG_SIZE_READ = 64
MSG_SIZE_WRITE = 65  # report ID (0x00) + 64 payload bytes

# Battery response range: 1..1000 (0.1 % resolution).
BATTERY_MIN = 1
BATTERY_MAX = 1000
BATTERY_MAX_ATTEMPTS = 3

# Read timeout for IN reports (seconds).
READ_TIMEOUT = 5.0


class HIDError(Exception):
    """Raised when the HID device cannot be opened or communicated with."""


def find_control_hidraw() -> str | None:
    """Locate the /dev/hidrawN node of the HS80 MAX control interface.

    Iterates over ``/sys/class/hidraw`` and matches devices by USB
    vendor/product id (from the ``device`` symlink target, e.g.
    ``0003:1B1C:0A97.0001``) and by USB interface number (``device/interface``).

    Returns the device path, or ``None`` when the dongle is not plugged in.
    """
    for entry in sorted(os.listdir("/sys/class/hidraw")):
        hidraw_dir = os.path.join("/sys/class/hidraw", entry)
        dev_link = os.path.join(hidraw_dir, "device")
        try:
            target = os.readlink(dev_link)  # e.g. "../../../0003:1B1C:0A97.0001"
        except OSError:
            continue
        # target format: 0003:VVVV:PPPP.XXXX
        parts = target.rsplit("/", 1)[-1].split(":")
        if len(parts) != 3:
            continue
        try:
            vid, pid, iface = int(parts[1], 16), int(parts[2].split(".")[0], 16), None
        except ValueError:
            continue
        if vid != VENDOR_ID or pid != PRODUCT_ID:
            continue
        # The USB interface number is embedded in the device path
        # (e.g. .../1-2.1:1.4/0003:1B1C:0A97.0002 → interface 4).
        m = re.search(r":1\.(\d+)$", os.path.basename(os.path.dirname(os.path.realpath(dev_link))))
        iface = int(m.group(1)) if m else -1
        if iface == CONTROL_INTERFACE:
            return os.path.join("/dev", entry)
    return None


class HS80HID:
    """Thin blocking client for the HS80 MAX receiver HID control channel."""

    def __init__(self, device_path: str | None = None):
        self.device_path = device_path or find_control_hidraw()
        self._fd: int | None = None

    # ------------------------------------------------------------------ open
    def open(self) -> None:
        """Open the hidraw device node (read/write)."""
        if self._fd is not None:
            return
        if self.device_path is None:
            raise HIDError("HS80 MAX dongle (1b1c:0a97) not found")
        try:
            self._fd = os.open(self.device_path, os.O_RDWR | os.O_NONBLOCK)
        except PermissionError as exc:
            raise HIDError(
                f"no permission on {self.device_path} – add the udev rule "
                f"(see resourcen/battery-protocol.md, 'Permissions')"
            ) from exc
        except OSError as exc:
            raise HIDError(f"cannot open {self.device_path}: {exc}") from exc
        log.debug("opened %s (fd=%d)", self.device_path, self._fd)

    def close(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    # ------------------------------------------------------------------- io
    def _write(self, payload: bytes) -> None:
        """Write a 65-byte report (report ID 0x00 + 64 payload bytes).

        ``payload`` must already include the report ID as its first byte.
        It is zero-padded to ``MSG_SIZE_WRITE`` (65) bytes.
        """
        if self._fd is None:
            raise HIDError("device not open")
        data = payload.ljust(MSG_SIZE_WRITE, b"\x00")
        written = 0
        while written < len(data):
            try:
                written += os.write(self._fd, data[written:])
            except BlockingIOError:
                time.sleep(0.005)
    def _read(self, timeout: float = READ_TIMEOUT) -> bytes | None:
        """Read one 64-byte IN report; ``None`` on timeout."""
        if self._fd is None:
            raise HIDError("device not open")
        deadline = time.monotonic() + timeout
        buf = b""
        while len(buf) < MSG_SIZE_READ and time.monotonic() < deadline:
            try:
                chunk = os.read(self._fd, MSG_SIZE_READ - len(buf))
            except BlockingIOError:
                time.sleep(0.01)
                continue
            except OSError as exc:
                raise HIDError(f"read failed: {exc}") from exc
            buf += chunk
        return buf if len(buf) == MSG_SIZE_READ else None

    def _flush(self) -> None:
        """Drain pending IN reports until the first read times out."""
        while self._read(timeout=0.05) is not None:
            time.sleep(0.005)

    # -------------------------------------------------------------- protocol
    def wake(self) -> bool:
        """Initialise the receiver/headset control channel.

        Follows the ``CorsairVoidV2W::initializeDevice`` sequence from
        HeadsetControl:

        1. Receiver firmware query
        2. Receiver software-mode enable
        3. Receiver heartbeat
        4. Headset software-mode enable
        5. Flush pending IN reports
        6. Headset heartbeat  →  read response

        Returns ``True`` when the headset is connected to the receiver,
        ``False`` otherwise (heartbeat read timed out).
        """
        # 1. Receiver firmware query
        self._write(bytes([0x00, 0x02, RECEIVER_ENDPOINT, 0x02, 0x13]))
        # 2. Receiver software-mode enable
        self._write(bytes([0x00, 0x02, RECEIVER_ENDPOINT, 0x01, 0x03, 0x00, 0x02]))
        # 3. Receiver heartbeat
        self._write(bytes([0x00, 0x02, RECEIVER_ENDPOINT, 0x02, 0x12]))
        # 4. Headset software-mode enable
        self._write(bytes([0x00, 0x02, HEADSET_ENDPOINT, 0x01, 0x03, 0x00, 0x02]))
        # 5. Flush pending IN reports
        self._flush()
        # 6. Headset heartbeat → read response
        self._write(bytes([0x00, 0x02, HEADSET_ENDPOINT, 0x02, 0x12]))
        return self._read() is not None

    def battery_percent(self) -> int | None:
        """Query the headset battery level.

        Returns an integer percentage (0–100), or ``None`` when the headset
        is not connected or the reading is implausible.
        """
        if not self.wake():
            return None
        self._flush()
        for _ in range(BATTERY_MAX_ATTEMPTS):
            self._write(bytes([0x00, 0x02, HEADSET_ENDPOINT, 0x02, 0x0F]))
            resp = self._read()
            if resp is None:
                continue
            raw = resp[4] | (resp[5] << 8)
            if BATTERY_MIN <= raw <= BATTERY_MAX:
                return raw // 10
            # Receiver replied with a paired-headset ID – retry.
        return None

    def mic_muted(self) -> bool | None:
        """Query microphone mute state (boom mic flipped up).

        Returns ``True``/``False`` on success, ``None`` when unreachable.
        """
        if not self.wake():
            return None
        self._flush()
        self._write(bytes([0x00, 0x02, HEADSET_ENDPOINT, 0x02, 0xA6]))
        resp = self._read()
        if resp is None:
            return None
        return resp[4] == 0x01


def selftest() -> int:
    """CLI selftest: open the dongle and print battery / mic status."""
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    hid = HS80HID()
    try:
        hid.open()
    except HIDError as exc:
        log.error("%s", exc)
        return 1
    try:
        bat = hid.battery_percent()
        mic = hid.mic_muted()
        log.info("battery: %s", f"{bat} %" if bat is not None else "unavailable")
        log.info("mic muted: %s", mic)
        return 0
    finally:
        hid.close()


if __name__ == "__main__":
    sys.exit(selftest())

