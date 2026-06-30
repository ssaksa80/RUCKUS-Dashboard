import time
from ruckus_dashboard.infra.parallel_fetch import ParallelFetcher


def test_runs_all_tasks_returns_results_keyed_by_id():
    pf = ParallelFetcher(max_workers=2, timeout=5)
    results = pf.run({
        "a": lambda: "result-a",
        "b": lambda: "result-b",
    })
    assert results["a"].ok is True
    assert results["a"].value == "result-a"
    assert results["b"].ok is True
    assert results["b"].value == "result-b"


def test_captures_exceptions_per_task():
    pf = ParallelFetcher(max_workers=2, timeout=5)
    def bad():
        raise ValueError("nope")
    results = pf.run({"good": lambda: 1, "bad": bad})
    assert results["good"].ok is True
    assert results["bad"].ok is False
    assert isinstance(results["bad"].error, ValueError)


def test_per_task_timeout():
    pf = ParallelFetcher(max_workers=2, timeout=0.05)
    def slow():
        time.sleep(0.5)
        return "late"
    results = pf.run({"slow": slow})
    assert results["slow"].ok is False
    assert results["slow"].timed_out is True


def test_empty_task_dict_returns_empty():
    pf = ParallelFetcher(max_workers=2, timeout=1)
    assert pf.run({}) == {}


def test_concurrent_execution_faster_than_sequential():
    pf = ParallelFetcher(max_workers=4, timeout=2)
    def busy():
        time.sleep(0.1)
        return 1
    start = time.time()
    pf.run({f"t{i}": busy for i in range(4)})
    elapsed = time.time() - start
    assert elapsed < 0.25


def test_run_returns_promptly_despite_hung_task():
    f = ParallelFetcher(max_workers=2, timeout=0.2)
    def hang():
        time.sleep(5)        # exceeds timeout
        return "late"
    started = time.monotonic()
    results = f.run({"fast": lambda: "ok", "slow": hang})
    elapsed = time.monotonic() - started
    assert results["fast"].ok and results["fast"].value == "ok"
    assert results["slow"].timed_out is True
    assert elapsed < 2.0      # must NOT block ~5s on the straggler's shutdown(wait=True)
