"""Concurrent duplicate-fetch deduplication.

Late callers that arrive while a call with the same key is already running
wait for the in-flight call to finish and receive its result instead of
firing a duplicate request. Once the owner finishes and the in-flight
registration is cleared, subsequent ``run`` calls execute fresh.
"""

from __future__ import annotations

import threading
from typing import Callable, TypeVar

T = TypeVar("T")


class _Slot:
    """Per-cycle holder shared between the owner thread and any waiters.

    Tying results to the slot (rather than to the dedupe key) avoids a race
    where the owner cleans up the key before waiters read the value: every
    thread that joined this cycle already holds a reference to the same
    slot, so cleanup of ``_inflight`` is safe.
    """

    __slots__ = ("event", "value", "exception")

    def __init__(self) -> None:
        self.event = threading.Event()
        self.value: object = None
        self.exception: BaseException | None = None


class InFlightDeduper:
    """Deduplicate concurrent calls keyed by a string."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._inflight: dict[str, _Slot] = {}

    def run(self, key: str, fn: Callable[[], T]) -> T:
        with self._lock:
            slot = self._inflight.get(key)
            if slot is None:
                slot = _Slot()
                self._inflight[key] = slot
                owner = True
            else:
                owner = False

        if owner:
            try:
                slot.value = fn()
            except BaseException as exc:
                slot.exception = exc
                # Surface to waiters then re-raise for the owner caller.
                with self._lock:
                    self._inflight.pop(key, None)
                slot.event.set()
                raise
            with self._lock:
                self._inflight.pop(key, None)
            slot.event.set()
            return slot.value  # type: ignore[return-value]

        slot.event.wait()
        if slot.exception is not None:
            raise slot.exception
        return slot.value  # type: ignore[return-value]
