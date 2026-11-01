#!/usr/bin/env python3
"""Regression test for the HS80Max StatusChanged D-Bus signal path.

Background
----------
``HS80Service.publish()`` is called from the non-main *Poller* thread. The
original implementation dispatched the ``StatusChanged`` emission through
``GLib.idle_add``. Scheduling an idle source from a thread that is not the one
running the GLib main loop is undefined behaviour; in practice the source is
dropped and the callback never runs, so the signal was silently lost and the
GNOME extension icon went stale whenever the mic/mode/battery changed.

The fix emits the D-Bus signal directly from the Poller thread. pydbus's
``DbusSignal.__call__`` ultimately calls ``g_dbus_connection_send_message``,
which is thread-safe per the GLib documentation, so no dispatch to the main
loop is required.

This test drives ``publish()`` from a non-main thread (mirroring the real
Poller) with a recording test double standing in for the pydbus
``DbusSignal`` descriptor, and asserts the signal is delivered exactly once.
No live bus is required, so it is fast and deterministic.

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


class RecordingSignal:
    """Test double standing in for pydbus's ``DbusSignal``.

    Records every invocation with its arguments and the identifier of the
    thread that invoked it.
    """

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.caller_threads: list[int] = []

    def __call__(self, *args) -> None:
        self.calls.append(args)
        self.caller_threads.append(threading.get_ident())


def _make_service() -> tuple[object, RecordingSignal]:
    """Build an ``HS80Service`` whose ``StatusChanged`` is a recorder.

    ``DbusSignal`` is a descriptor that forbids instance assignment, so we
    shadow it by defining it as a class attribute on a subclass (this happens
    at class-creation time and does not go through ``DbusSignal.__set__``).
    """
    recorder = RecordingSignal()

    class _TestService(HS80Service):
        StatusChanged = recorder  # type: ignore[assignment]

    return _TestService(bus=None), recorder


def test_publish_from_non_main_thread_emits_signal_once() -> None:
    svc, recorder = _make_service()
    main_thread_id = threading.get_ident()

    # Baseline: publish the default status (no change expected).
    # The service default is mic_muted=True (unknown state reads as muted).
    svc.publish(Status(mode="disconnected", battery=-1, mic_muted=True))
    assert recorder.calls == [], f"unexpected baseline emission: {recorder.calls}"

    # Simulate the Poller thread publishing a CHANGED status.
    errors: list[str] = []

    def poller_work() -> None:
        try:
            svc.publish(Status(mode="disconnected", battery=-1, mic_muted=False))
        except Exception as exc:  # pragma: no cover - defensive
            errors.append(f"publish() raised: {exc!r}")

    poller = threading.Thread(target=poller_work)
    poller.start()
    poller.join(timeout=5)
    time.sleep(0.1)  # brief settle

    assert not errors, errors
    assert len(recorder.calls) == 1, f"expected 1 signal, got {recorder.calls!r}"
    assert recorder.calls[0] == ("disconnected", -1, False), recorder.calls[0]
    # The signal must have been emitted from the non-main (poller) thread,
    # proving the direct (non-idle_add) emission path is what runs.
    assert recorder.caller_threads[0] != main_thread_id, (
        "signal was emitted on the main thread; expected the poller thread"
    )


def test_publish_and_property_read_from_threads_do_not_raise() -> None:
    """Concurrent publish() and property reads must not raise.

    publish() runs on the Poller thread; D-Bus property reads run on the
    GLib main-loop thread. With the status lock in place both may race
    without raising and without a torn snapshot.
    """
    svc, _ = _make_service()
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
                _ = svc.GetBattery(), svc.GetMicMuted()
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
    test_publish_from_non_main_thread_emits_signal_once()
    test_publish_and_property_read_from_threads_do_not_raise()
    print("PASS: publish() from a non-main thread emitted StatusChanged exactly once.")
    print("PASS: concurrent publish() and property reads did not raise.")
