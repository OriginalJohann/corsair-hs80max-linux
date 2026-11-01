#!/usr/bin/env python3
"""Tests for the HS80 Max HID protocol parsing and the Poller sticky rules.

Covers the two layers that keep the published state honest:

* :func:`hid_protocol._is_periodic_report` – the first-stage filter that
  rejects the receiver's periodic status reports so they are never mistaken
  for a battery / mic response.
* :meth:`HS80HID._battery_query` – the value validation on top of that
  filter (a real percentage, a periodic report, or an out-of-range reply).
* the :class:`main.Poller` sticky rules – what happens to the published
  battery / mic / mode when the dongle is unplugged, and – critically – when
  the dongle is present but the control-channel device node has not been
  created yet after a replug (it must NOT flip the mode to ``"off"``).

No hardware is required: the HID I/O is faked with monkeypatched doubles.

Run::

    python3 -m pytest service/
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

# Make the package importable when run as a plain script.
SERVICE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SERVICE_DIR))

from hs80max_service import hid_protocol  # noqa: E402
from hs80max_service.hid_protocol import (  # noqa: E402
    BATTERY_MAX,
    BATTERY_MIN,
    HIDError,
    HIDNotFound,
    HS80HID,
    _is_periodic_report,
)


# ---------------------------------------------------------------------------
# _is_periodic_report
# ---------------------------------------------------------------------------

def test_is_periodic_report_rejects_known_receiver_reports() -> None:
    # The two periodic receiver status patterns observed with the headset off.
    status_report = b"\x01\x00\x02\x00\x00\x10\x76\x00" * 2
    product_id_report = b"\x01\x00\x02\x00\x97\x0a\x00\x00" * 2
    assert _is_periodic_report(status_report) is True
    assert _is_periodic_report(product_id_report) is True


def test_is_periodic_report_passes_genuine_responses() -> None:
    # A valid battery report: value 1..1000 at bytes [4]/[5] (little-endian),
    # on a non-periodic report ID. 500 (= 50 %) -> 0x01F4.
    battery_report = b"\x02\x00\x00\x00\xf4\x01\x00" + b"\x00" * 56
    # A paired-headset-ID reply: a value out of the 1..1000 range at [4]/[5].
    headset_id_report = b"\x02\x00\x00\x00\x00\x08\x00" + b"\x00" * 56
    # A short / non-0x01 report can never be a periodic report.
    assert _is_periodic_report(battery_report) is False
    assert _is_periodic_report(headset_id_report) is False
    assert _is_periodic_report(b"\x01\x00\x02\x00") is False  # too short


# ---------------------------------------------------------------------------
# _battery_query (fake _read)
# ---------------------------------------------------------------------------

def _battery_value_report(value: int) -> bytes:
    """Build a 64-byte battery IN report carrying ``value`` at [4]/[5]."""
    report = bytearray(64)
    report[4] = value & 0xFF
    report[5] = (value >> 8) & 0xFF
    return bytes(report)


_PERIODIC = b"\x01\x00\x02\x00\x00\x10\x76\x00" * 2


def _fake_read(responses: list, reads: list | None = None):
    """Build a fake ``_read`` for :meth:`HS80HID._battery_query`.

    ``_flush()`` drains pending reports by calling ``_read(timeout=0.05)``
    in a loop; that must return ``None`` (drain done) so the loop terminates.
    The actual battery query reads call ``_read()`` with no timeout and
    receive the queued ``responses`` in order (``None`` once exhausted).
    """
    def fake_read(self, timeout=None):
        if timeout is not None:
            # Called from _flush(): nothing pending.
            return None
        if reads is not None:
            reads.append(timeout)
        return responses.pop(0) if responses else None

    return fake_read


def _stub_hid(monkeypatch, responses: list, reads: list | None = None) -> None:
    """Fake ``_read`` and ``_write`` on :class:`HS80HID` for :meth:`_battery_query`.

    Patched on the class so ``self._read`` / ``self._write`` bind correctly.
    """
    monkeypatch.setattr(HS80HID, "_write", lambda self, payload: None)
    monkeypatch.setattr(HS80HID, "_read", _fake_read(responses, reads))


def test_battery_query_returns_percent_for_valid_report(monkeypatch) -> None:
    hid = HS80HID(device_path="/dev/none")
    _stub_hid(monkeypatch, [_battery_value_report(730)])
    assert hid._battery_query() == 73


def test_battery_query_retries_past_periodic_report(monkeypatch) -> None:
    hid = HS80HID(device_path="/dev/none")
    reads: list = []
    # A periodic report arrives first, then the real reading.
    _stub_hid(monkeypatch, [_PERIODIC, _battery_value_report(1000)], reads)
    assert hid._battery_query() == 100
    assert len(reads) == 2  # first query read was the periodic report (retried)


def test_battery_query_returns_none_when_all_reads_are_periodic(monkeypatch) -> None:
    hid = HS80HID(device_path="/dev/none")
    _stub_hid(monkeypatch, [_PERIODIC] * 3)
    assert hid._battery_query() is None


def test_battery_query_returns_none_for_out_of_range_value(monkeypatch) -> None:
    hid = HS80HID(device_path="/dev/none")
    # 0 and 1001 are both outside the valid 1..1000 battery range.
    _stub_hid(monkeypatch, [_battery_value_report(0)])
    assert hid._battery_query() is None
    _stub_hid(monkeypatch, [_battery_value_report(1001)])
    assert hid._battery_query() is None
    # Boundaries are inclusive and valid.
    _stub_hid(monkeypatch, [_battery_value_report(BATTERY_MIN)])
    assert hid._battery_query() == 0
    _stub_hid(monkeypatch, [_battery_value_report(BATTERY_MAX)])
    assert hid._battery_query() == 100


# ---------------------------------------------------------------------------
# HIDNotFound distinction
# ---------------------------------------------------------------------------

def test_open_raises_hid_not_found_when_device_node_missing(monkeypatch) -> None:
    # Force "no control device node" regardless of any real dongle present.
    monkeypatch.setattr(hid_protocol, "find_control_hidraw", lambda: None)
    hid = HS80HID(device_path=None)
    try:
        hid.open()
        assert False, "expected HIDNotFound"
    except HIDNotFound:
        pass
    # HIDNotFound is a kind of HIDError (catchable by existing handlers).
    assert issubclass(HIDNotFound, HIDError)


# ---------------------------------------------------------------------------
# Poller sticky rules
# ---------------------------------------------------------------------------

def _make_poller(monkeypatch, hid_error: Exception | None = None) -> object:
    """Build a :class:`Poller` with the D-Bus service and HID layer faked.

    ``connection.connection_mode`` is forced to ``"connected"`` (dongle
    plugged in) and :meth:`HS80HID.open` is faked to raise ``hid_error``
    (or succeed with a no-op double when ``hid_error`` is ``None``).
    """
    from hs80max_service import connection
    from hs80max_service.main import Poller

    service = types.SimpleNamespace()
    published: list = []
    service.publish = lambda status: published.append(status)

    monkeypatch.setattr(connection, "connection_mode", lambda: "connected")

    def fake_open(self) -> None:
        if hid_error is not None:
            raise hid_error
        self._fd = 0

    monkeypatch.setattr(HS80HID, "open", fake_open)
    # When open() succeeds, status() reports "headset on, 80 %, mic muted".
    monkeypatch.setattr(HS80HID, "status", lambda self: (True, 80, True))
    monkeypatch.setattr(HS80HID, "close", lambda self: None)

    poller = Poller(service)
    poller._published = published  # expose for assertions
    return poller


def test_poller_dongle_unplugged_resets_battery_and_mic(monkeypatch) -> None:
    from hs80max_service import connection
    from hs80max_service.main import Poller

    service = types.SimpleNamespace()
    published: list = []
    service.publish = lambda status: published.append(status)

    # Dongle unplugged -> connection_mode() reports "disconnected".
    monkeypatch.setattr(connection, "connection_mode", lambda: "disconnected")

    poller = Poller(service)
    # Simulate previously known values.
    poller._battery = 80
    poller._mic_muted = False
    poller._headset_on = True

    poller._poll_once()

    # Battery / mic are reset to unknown (published as -1 / muted) and the
    # mode is "disconnected".
    assert poller._mode == "disconnected"
    assert poller._battery is None
    assert poller._mic_muted is None
    assert published[-1].battery == -1
    assert published[-1].mic_muted is True
    assert published[-1].mode == "disconnected"


def test_poller_hid_not_found_does_not_flip_mode_to_off(monkeypatch) -> None:
    """Regression test for the stale-battery-on-replug bug.

    When the dongle is plugged in but the control-channel device node has
    not been created yet (``HIDNotFound``), the Poller must keep the last
    known headset power state – it must NOT conclude the headset is off.
    """
    poller = _make_poller(monkeypatch, hid_error=HIDNotFound("not found"))
    # The headset was known to be on with a fresh reading.
    poller._headset_on = True
    poller._battery = 80
    poller._mic_muted = False

    poller._poll_once()

    # Mode must stay "connected" (headset_on untouched), battery/mic sticky.
    assert poller._mode == "connected", (
        f"mode flipped to {poller._mode!r} on HIDNotFound – "
        "the replug regression"
    )
    assert poller._headset_on is True
    assert poller._battery == 80
    assert poller._mic_muted is False
    assert poller._published[-1].mode == "connected"


def test_poller_other_hid_error_sets_mode_to_off(monkeypatch) -> None:
    """A *non*-not-found HIDError (e.g. permission / open failure) is a real
    unreachable channel and must set the mode to "off"."""
    poller = _make_poller(monkeypatch, hid_error=HIDError("cannot open /dev/hidraw1"))
    poller._headset_on = True
    poller._battery = 80

    poller._poll_once()

    assert poller._mode == "off"
    assert poller._headset_on is False
    # Battery / mic keep their last known values.
    assert poller._battery == 80
    assert poller._published[-1].mode == "off"


if __name__ == "__main__":
    # Allow running without pytest (mirrors test_dbus_signal.py).
    import pytest  # type: ignore[import-not-found]

    sys.exit(pytest.main([__file__, "-v"]))