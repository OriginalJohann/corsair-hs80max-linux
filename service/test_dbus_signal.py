#!/usr/bin/env python3
"""Tests for the HS80Max status publishing path.

``HS80Service.publish()`` is called from the non-main *Poller* thread. The
extension's data path is the atomically written status file at
``$XDG_RUNTIME_DIR/hs80max/status.json`` (this GJS build drops D-Bus signal
delivery), so ``publish()`` must (re)write that file on every status change.

The tests pin the file location, JSON shape and values, and check that
concurrent ``publish()`` and property reads do not race. No live bus is
required, so they are fast and deterministic.

Run::

    python3 service/test_dbus_signal.py

or under pytest::

    python3 -m pytest service/test_dbus_signal.py
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

# Make the package importable when run as a plain script.
SERVICE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SERVICE_DIR))

from hs80max_service.dbus_api import HS80Service, Status  # noqa: E402


def _make_service() -> HS80Service:
    """Build a bus-less ``HS80Service`` (publishing works without a bus)."""
    return HS80Service(bus=None)


def test_publish_writes_status_file_with_current_values(tmp_path, monkeypatch) -> None:
    """publish() must (re)write the status file the extension watches.

    This GJS build drops D-Bus signal callbacks, so the file at
    ``$XDG_RUNTIME_DIR/hs80max/status.json`` is the extension's *actual*
    data path. This test pins its location, JSON shape and values, and
    checks the atomic write leaves no temp file behind.
    """
    import json
    import os

    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    svc = _make_service()

    # Publishing a changed status must write the file (default status is
    # disconnected/-1/True, so this is a change).
    svc.publish(Status(mode="connected", battery=73, mic_muted=False))

    path = tmp_path / "hs80max" / "status.json"
    assert path.is_file(), "status file was not written"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["mode"] == "connected"
    assert payload["battery"] == 73
    assert payload["mic_muted"] is False
    assert isinstance(payload["updated_at"], int)  # epoch ms
    # Atomic os.replace() must not leave the temp file behind.
    assert not path.with_name(path.name + ".tmp").exists()

    # A second publish of the SAME values must not rewrite the file:
    # the extension treats file events as "status changed" wake-ups.
    before = os.path.getmtime(path)
    svc.publish(Status(mode="connected", battery=73, mic_muted=False))
    assert os.path.getmtime(path) == before


def test_publish_and_property_read_from_threads_do_not_raise() -> None:
    """Concurrent publish() and property reads must not raise.

    publish() runs on the Poller thread; D-Bus property reads run on the
    GLib main-loop thread. With the status lock in place both may race
    without raising and without a torn snapshot.
    """
    svc = _make_service()
    errors: list[str] = []
    stop = threading.Event()

    def poller_work() -> None:
        i = 0
        while not stop.is_set():
            try:
                svc.publish(Status(
                    mode="connected", battery=i % 101, mic_muted=i % 2 == 0,
                ))
            except Exception as exc:  # pragma: no cover - defensive
                errors.append(f"publish() raised: {exc!r}")
                return
            i += 1

    def reader_work() -> None:
        while not stop.is_set():
            try:
                _ = svc.Mode, svc.Battery, svc.MicMuted, svc.UpdatedAt
                _ = svc.GetStatus()
            except Exception as exc:  # pragma: no cover - defensive
                errors.append(f"property read raised: {exc!r}")
                return

    poller = threading.Thread(target=poller_work)
    reader = threading.Thread(target=reader_work)
    poller.start()
    reader.start()
    time.sleep(0.5)
    stop.set()
    poller.join(timeout=5)
    reader.join(timeout=5)
    assert not errors, errors


if __name__ == "__main__":
    test_publish_and_property_read_from_threads_do_not_raise()
    print("PASS: concurrent publish() and property reads did not raise.")