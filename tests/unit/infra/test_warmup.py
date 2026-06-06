import time
from dataclasses import dataclass
from ruckus_dashboard.infra.warmup import WarmupScheduler, WarmupStatus
from ruckus_dashboard.modules._base import ModuleSpec, FetcherContext


@dataclass
class FakeConn:
    platform: str = "smartzone"
    display_name: str = "FAKE"
    api_base: str = "https://fake/wsg/api/public"
    auth_token: str = "t"
    verify_tls: bool = False
    api_version: str = "v11_0"
    token_expires_at: float = 9999999999
    tenant_id: str = ""
    controller_version: str = ""


def make_spec(slug, fetcher, caps=(), warmup=True, platforms=("smartzone",)):
    return ModuleSpec(
        slug=slug, title=slug, group="Wireless", icon="?",
        poll_seconds=30, fetcher=fetcher, drill_fetcher=None,
        drill_tabs=(), summary_fn=lambda d: {"total": len(d.get("items", []))},
        requires_platforms=platforms, requires_capabilities=caps,
        supports_views=("table",), warmup=warmup,
    )


def noop_fetcher(ctx):
    return {"items": [], "warmup_marker": True}


def failing_fetcher(ctx):
    raise RuntimeError("upstream down")


def test_scheduler_runs_all_warmup_eligible_modules():
    spec_a = make_spec("a", noop_fetcher)
    spec_b = make_spec("b", noop_fetcher)
    scheduler = WarmupScheduler(
        connection=FakeConn(), config={}, modules={"a": spec_a, "b": spec_b},
        available_ops=set(),
    )
    scheduler.run()
    states = scheduler.snapshot()
    assert states["a"].status == "done"
    assert states["b"].status == "done"
    assert states["a"].summary == {"total": 0}


def test_scheduler_skips_warmup_false_modules():
    spec = make_spec("explorer", noop_fetcher, warmup=False)
    scheduler = WarmupScheduler(
        connection=FakeConn(), config={}, modules={"explorer": spec},
        available_ops=set(),
    )
    scheduler.run()
    states = scheduler.snapshot()
    assert states["explorer"].status == "skipped"


def test_scheduler_marks_failed_modules():
    spec = make_spec("bad", failing_fetcher)
    scheduler = WarmupScheduler(
        connection=FakeConn(), config={}, modules={"bad": spec},
        available_ops=set(),
    )
    scheduler.run()
    states = scheduler.snapshot()
    assert states["bad"].status == "failed"
    assert "upstream down" in states["bad"].error_message


def test_scheduler_marks_disabled_when_caps_missing():
    spec = make_spec("aps", noop_fetcher, caps=(("POST", "/query/ap"),))
    scheduler = WarmupScheduler(
        connection=FakeConn(), config={}, modules={"aps": spec},
        available_ops=set(),
    )
    scheduler.run()
    states = scheduler.snapshot()
    assert states["aps"].status == "disabled"


def test_scheduler_caps_present_runs_module():
    spec = make_spec("aps", noop_fetcher, caps=(("POST", "/query/ap"),))
    scheduler = WarmupScheduler(
        connection=FakeConn(), config={}, modules={"aps": spec},
        available_ops={("POST", "/query/ap")},
    )
    scheduler.run()
    states = scheduler.snapshot()
    assert states["aps"].status == "done"


def test_scheduler_skips_modules_not_supporting_platform():
    spec = make_spec("r1only", noop_fetcher, platforms=("ruckus_one",))
    scheduler = WarmupScheduler(
        connection=FakeConn(platform="smartzone"), config={},
        modules={"r1only": spec}, available_ops=set(),
    )
    scheduler.run()
    states = scheduler.snapshot()
    assert states["r1only"].status == "skipped"


def test_cancel_stops_pending_tasks():
    started = []
    def long_fetcher(ctx):
        started.append(1)
        time.sleep(5)
        return {"items": []}
    spec_a = make_spec("a", long_fetcher)
    spec_b = make_spec("b", long_fetcher)
    scheduler = WarmupScheduler(
        connection=FakeConn(), config={},
        modules={"a": spec_a, "b": spec_b}, available_ops=set(),
        max_workers=1,
    )
    import threading
    t = threading.Thread(target=scheduler.run, daemon=True)
    t.start()
    time.sleep(0.05)
    scheduler.cancel()
    t.join(timeout=2)
    assert len(started) < 2
