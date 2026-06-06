"""WarmupScheduler — runs every applicable module fetcher once per session.

Triggered by successful /connect. Iterates the MODULES registry, filters by
platform + capability, dispatches surviving fetchers onto ParallelFetcher,
records per-module status on a thread-safe `_states` dict that the SSE
endpoint observes.
"""
from __future__ import annotations
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from ..modules._base import FetcherContext, ModuleSpec
from .capability_gate import CapabilityGate
from .parallel_fetch import ParallelFetcher

LOG = logging.getLogger("ruckus_dashboard")


@dataclass
class WarmupStatus:
    slug: str
    status: str = "pending"
    summary: dict | None = None
    error_message: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0
    missing_capabilities: list[tuple[str, str]] = field(default_factory=list)


class WarmupScheduler:
    def __init__(
        self,
        connection: Any,
        config: dict,
        modules: dict[str, ModuleSpec],
        available_ops: set[tuple[str, str]],
        max_workers: int = 4,
        timeout: float = 30.0,
    ) -> None:
        self.connection = connection
        self.config = config
        self.modules = modules
        self.gate = CapabilityGate(available=available_ops)
        self._states: dict[str, WarmupStatus] = {
            slug: WarmupStatus(slug=slug) for slug in modules
        }
        self._lock = threading.Lock()
        self._cancelled = threading.Event()
        self._fetcher = ParallelFetcher(max_workers=max_workers, timeout=timeout)
        self._complete = threading.Event()
        self._listeners: list[threading.Event] = []

    def run(self) -> None:
        tasks: dict[str, Any] = {}
        for slug, spec in self.modules.items():
            if self._cancelled.is_set():
                self._set(slug, status="skipped", error_message="cancelled")
                continue
            if not spec.warmup:
                self._set(slug, status="skipped")
                continue
            if self.connection.platform not in spec.requires_platforms:
                self._set(slug, status="skipped")
                continue
            if not self.gate.satisfied(spec.requires_capabilities):
                self._set(
                    slug, status="disabled",
                    missing_capabilities=self.gate.missing(spec.requires_capabilities),
                )
                continue
            tasks[slug] = self._make_task(spec)
            self._set(slug, status="running", started_at=time.time())

        if not tasks or self._cancelled.is_set():
            self._complete.set()
            self._wake_listeners()
            return

        results = self._fetcher.run(tasks)
        for slug, result in results.items():
            if result.ok:
                spec = self.modules[slug]
                summary = spec.summary_fn(result.value) if spec.summary_fn else {}
                self._set(slug, status="done", summary=summary, completed_at=time.time())
            elif result.timed_out:
                self._set(slug, status="timed_out",
                          error_message="upstream timeout", completed_at=time.time())
            else:
                self._set(slug, status="failed",
                          error_message=str(result.error), completed_at=time.time())
            self._wake_listeners()

        self._complete.set()
        self._wake_listeners()

    def run_in_thread(self) -> threading.Thread:
        t = threading.Thread(target=self.run, name="warmup", daemon=True)
        t.start()
        return t

    def cancel(self) -> None:
        self._cancelled.set()
        self._complete.set()
        self._wake_listeners()

    def snapshot(self) -> dict[str, WarmupStatus]:
        with self._lock:
            return dict(self._states)

    def is_complete(self) -> bool:
        return self._complete.is_set()

    def wait(self, timeout: float | None = None) -> bool:
        return self._complete.wait(timeout=timeout)

    def add_listener(self) -> threading.Event:
        ev = threading.Event()
        with self._lock:
            self._listeners.append(ev)
        return ev

    def remove_listener(self, ev: threading.Event) -> None:
        with self._lock:
            if ev in self._listeners:
                self._listeners.remove(ev)

    def _make_task(self, spec: ModuleSpec):
        ctx = FetcherContext(
            connection=self.connection, config=self.config, filters=None,
            capability_gate=self.gate,
            connection_label=getattr(self.connection, "display_name", ""),
        )
        return lambda: spec.fetcher(ctx)

    def _set(self, slug: str, **fields) -> None:
        with self._lock:
            current = self._states[slug]
            for k, v in fields.items():
                setattr(current, k, v)

    def _wake_listeners(self) -> None:
        with self._lock:
            for ev in self._listeners:
                ev.set()
