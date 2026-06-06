"""Concurrent fetcher with per-task timeout and exception capture."""
from __future__ import annotations
import concurrent.futures
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class TaskResult:
    ok: bool
    value: Any = None
    error: BaseException | None = None
    timed_out: bool = False


class ParallelFetcher:
    """Run a dict of `{id: callable}` concurrently with a per-task timeout.

    Returns `{id: TaskResult}`. Each TaskResult carries either a successful
    value or the captured exception. Timeouts produce `timed_out=True`.
    The fetcher does not raise - every task's outcome is reflected in the
    result dict.
    """

    def __init__(self, max_workers: int = 4, timeout: float = 30.0) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be >= 1")
        if timeout <= 0:
            raise ValueError("timeout must be > 0")
        self.max_workers = max_workers
        self.timeout = timeout

    def run(self, tasks: dict[str, Callable[[], Any]]) -> dict[str, TaskResult]:
        if not tasks:
            return {}
        results: dict[str, TaskResult] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            future_to_id = {pool.submit(fn): tid for tid, fn in tasks.items()}
            done, not_done = concurrent.futures.wait(
                future_to_id, timeout=self.timeout
            )
            for future in done:
                tid = future_to_id[future]
                try:
                    value = future.result()
                    results[tid] = TaskResult(ok=True, value=value)
                except BaseException as exc:  # noqa: BLE001
                    results[tid] = TaskResult(ok=False, error=exc)
            for future in not_done:
                tid = future_to_id[future]
                future.cancel()
                results[tid] = TaskResult(
                    ok=False,
                    error=concurrent.futures.TimeoutError(
                        f"task {tid!r} exceeded {self.timeout}s"
                    ),
                    timed_out=True,
                )
        return results
