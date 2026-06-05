import threading
import time

from ruckus_dashboard.infra.inflight import InFlightDeduper


def test_single_call_executes_once():
    dedup = InFlightDeduper()
    calls = []

    def work():
        calls.append(1)
        return "ok"

    result = dedup.run("key1", work)
    assert result == "ok"
    assert len(calls) == 1


def test_concurrent_calls_share_result():
    dedup = InFlightDeduper()
    calls = []

    def slow_work():
        calls.append(1)
        time.sleep(0.05)
        return "shared"

    results = []

    def fire():
        results.append(dedup.run("k", slow_work))

    threads = [threading.Thread(target=fire) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert all(r == "shared" for r in results)
    assert len(calls) == 1  # only one actual execution


def test_different_keys_dont_dedupe():
    dedup = InFlightDeduper()
    calls = []

    def work():
        calls.append(1)
        return "x"

    dedup.run("a", work)
    dedup.run("b", work)
    assert len(calls) == 2
