"""HS80 Max Wireless (1b1c:0a97) HID protocol.

Implements the proprietary receiver/headset protocol as documented in
``resources/battery-protocol.md`` (derived from the reference implementation
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

# Protocol constants (see resources/battery-protocol.md).
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

# ``wake()`` is retried this many times (with a short pause between attempts)
# before giving up.  The headset only answers the control channel shortly
# after it wakes up / reconnects and then goes quiet (emitting only periodic
# ``id=01`` status reports), so a single attempt frequently misses the
# responsive window.  Retrying improves the odds of landing inside it.
WAKE_ATTEMPTS = 3
WAKE_RETRY_PAUSE = 0.5

# Report ID of the receiver's *periodic* status reports, which arrive
# roughly every 5 s even when no command was sent (observed:
# ``01 00 02 00 00 10 76 …`` and ``01 00 02 00 97 0a …``).  These must not
# be mistaken for query responses, otherwise ``wake()`` reports a false
# positive and battery/mic reads consume the timeout on a stale report.
PERIODIC_REPORT_ID = 0x01


def _is_periodic_report(report: bytes) -> bool:
    """Return True when ``report`` is a known periodic receiver status report.

    The wireless receiver emits small status reports roughly every 5 s
    independent of any command (observed with the headset off):

    * ``01 00 02 00 00 10 76 …``  – receiver status
    * ``01 00 02 00 97 0a …``     – receiver status carrying the
      product ID ``0x0a97`` (little-endian)

    A genuine headset response to our queries is one of: a battery value
    in ``1..1000`` at bytes [4]/[5], the mic flag at byte [4], or the
    headset heartbeat reply.  None of these match the patterns above,
    so this check is a safe first-stage filter before value validation.
    """
    if len(report) < 8 or report[0] != PERIODIC_REPORT_ID:
        return False
    return report[1:4] == b"\x00\x02\x00" and (
        report[4:7] == b"\x00\x10\x76"  # status report (fixed tail)
        or report[4:7] == b"\x97\x0a\x00"  # product-ID status report
    )


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
                f"(see resources/battery-protocol.md, 'Permissions')"
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
        """Read one 64-byte IN report; ``None`` on timeout.

        Callers must validate the returned report (see
        :func:`_is_periodic_report`): the receiver emits periodic status
        reports that are *not* responses to our queries.
        """
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
            if chunk:
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

        The final read accepts any report *except* the receiver's known
        periodic status reports (report ID ``PERIODIC_REPORT_ID``), which
        arrive every ~5 s even when the headset is off and would make
        this check a false positive.
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
        # 6. Headset heartbeat → read response.
        # We cannot use the strict ``QUERY_REPORT_ID`` filter here because
        # the report ID of the genuine headset heartbeat response is not
        # documented; excluding the *known* periodic reports is the safe
        # middle ground.
        resp = self._read()
        if resp is None:
            return False
        return resp[0] != PERIODIC_REPORT_ID

    def wake_with_retries(self) -> bool:
        """Call :meth:`wake` up to ``WAKE_ATTEMPTS`` times.

        The headset answers the control channel only in a short window after
        it wakes up / reconnects, then goes quiet (periodic ``id=01`` reports
        only).  A single :meth:`wake` call often misses that window, so we
        retry with a short pause between attempts.  Returns ``True`` as soon as
        any attempt succeeds.
        """
        for attempt in range(1, WAKE_ATTEMPTS + 1):
            if self.wake():
                return True
            if attempt < WAKE_ATTEMPTS:
                time.sleep(WAKE_RETRY_PAUSE)
        return False

    def battery_percent(self) -> int | None:
        """Query the headset battery level (wakes the channel first).

        Returns an integer percentage (0–100), or ``None`` when the headset
        is not connected or the reading is implausible.
        """
        if not self.wake():
            return None
        return self._battery_query()

    def _battery_query(self) -> int | None:
        """Battery query; assumes the channel is already woken up.

        Responses are validated twice: the known periodic receiver report
        patterns are rejected outright (they are not battery responses),
        and the battery value must fall in ``1..1000`` (the reference
        implementation's primary check, which also handles the
        paired-headset-ID reply).
        """
        self._flush()
        for _ in range(BATTERY_MAX_ATTEMPTS):
            self._write(bytes([0x00, 0x02, HEADSET_ENDPOINT, 0x02, 0x0F]))
            resp = self._read()
            if resp is None:
                continue
            if _is_periodic_report(resp):
                # Periodic receiver status, not a battery answer – retry.
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
        return self._mic_query()

    def _mic_query(self) -> bool | None:
        """Mic query; assumes the channel is already woken up.

        Periodic receiver reports are rejected, so a missing headset cannot
        masquerade as a mic state.
        """
        self._flush()
        self._write(bytes([0x00, 0x02, HEADSET_ENDPOINT, 0x02, 0xA6]))
        resp = self._read()
        if resp is None or _is_periodic_report(resp):
            return None
        return resp[4] == 0x01

    def status(self) -> tuple[int | None, bool | None]:
        """One handshake, then battery + mic queries in a single cycle.

        Used by the poller: a single ``wake()`` per cycle instead of one
        per query.  Matters when the headset is off – each query without a
        prior shared wake would burn its full read timeout.
        """
        if not self.wake_with_retries():
            return None, None
        return self._battery_query(), self._mic_query()


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
        bat, mic = hid.status()
        log.info("battery: %s", f"{bat} %" if bat is not None else "unavailable")
        log.info("mic muted: %s", mic)
        return 0
    finally:
        hid.close()


if __name__ == "__main__":
    sys.exit(selftest())

