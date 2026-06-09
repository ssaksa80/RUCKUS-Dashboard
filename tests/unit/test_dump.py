"""Unit tests for the headless data-dump (``ruckus_dashboard.dump.run_dump``).

These tests do NOT touch the network or a real controller. ``MODULES`` is
monkeypatched with a tiny registry of synthetic ModuleSpecs (one healthy, one
failing, one drillable) and ``discover_capabilities`` is stubbed.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

import ruckus_dashboard.dump as dump_mod
from ruckus_dashboard.dump import run_dump
from ruckus_dashboard.modules._base import ModuleSpec
from ruckus_dashboard.clients.base import RuckusClientError


@dataclass
class FakeConnection:
    platform: str = "smartzone"
    display_name: str = "SmartZone test"
    controller_version: str = "7.1.1"
    api_base: str = "https://sz.example:8443/wsg/api/public"


def _spec(slug, fetcher, *, drill_fetcher=None, summary_fn=None):
    return ModuleSpec(
        slug=slug,
        title=slug.title(),
        group="Wireless",
        icon="x",
        poll_seconds=30,
        fetcher=fetcher,
        drill_fetcher=drill_fetcher,
        drill_tabs=(),
        summary_fn=summary_fn or (lambda data: {"total": len(data.get("items", []))}),
        requires_platforms=("smartzone",),
        requires_capabilities=(),
        supports_views=("table",),
    )


@pytest.fixture
def config():
    return {"RUCKUS_TIMEOUT_SECONDS": 5, "RUCKUS_DEBUG_BYTES": 2000}


@pytest.fixture(autouse=True)
def stub_capabilities(monkeypatch):
    monkeypatch.setattr(dump_mod, "discover_capabilities",
                        lambda conn, cfg: {"available_ops": set()})


def _good_fetcher(ctx):
    return {"items": [{"id": "a1", "name": "AP-1"}, {"id": "a2", "name": "AP-2"}]}


def _failing_fetcher(ctx):
    raise RuckusClientError("query/wlan failed with HTTP 400.", 400,
                            {"raw": '{"message":"bad request body"}'})


def _drill_fetcher(ctx, entity_id):
    return {"identity": {"id": entity_id, "password": "hunter2"}}


def test_dump_top_level_shape(monkeypatch, config):
    monkeypatch.setattr(dump_mod, "MODULES", {"good": _spec("good", _good_fetcher)})
    result = run_dump(FakeConnection(), config)
    for key in ("dumped_at", "app_version", "controller", "capabilities", "modules"):
        assert key in result
    assert result["controller"]["platform"] == "smartzone"
    assert result["controller"]["version"] == "7.1.1"
    assert result["capabilities"]["op_count"] == 0


def test_good_module_complete(monkeypatch, config):
    monkeypatch.setattr(dump_mod, "MODULES", {"good": _spec("good", _good_fetcher)})
    result = run_dump(FakeConnection(), config)
    entry = result["modules"]["good"]
    assert entry["status"] == "complete"
    assert entry["item_count"] == 2
    assert len(entry["items"]) == 2
    assert entry["error"] is None
    assert entry["summary"] == {"total": 2}


def test_failing_module_error_includes_raw_body(monkeypatch, config):
    monkeypatch.setattr(dump_mod, "MODULES", {"bad": _spec("bad", _failing_fetcher)})
    result = run_dump(FakeConnection(), config)
    entry = result["modules"]["bad"]
    assert entry["status"] == "error"
    assert "query/wlan failed" in entry["error"]
    assert "bad request body" in entry["error"]


def _raw_fetcher(ctx):
    return {"items": [{"id": "a1"}],
            "raw_rows": [{"weirdKey": 1, "switchName": "SW-1"}],
            "secret": "topsecret"}


def test_dump_captures_raw_sample(monkeypatch, config):
    monkeypatch.setattr(dump_mod, "MODULES", {"x": _spec("x", _raw_fetcher)})
    result = run_dump(FakeConnection(), config)
    entry = result["modules"]["x"]
    assert entry["raw_sample"]["raw_rows"][0]["weirdKey"] == 1
    assert "items" not in entry["raw_sample"]  # items captured separately
    assert entry["raw_sample"]["secret"] == "[redacted]"  # redaction applied


def test_truncate_caps_list_and_depth():
    big = {"rows": list(range(10))}
    out = dump_mod._truncate(big, depth=4, max_items=3)
    assert out["rows"][:3] == [0, 1, 2]
    assert "more" in out["rows"][3]


def test_drillable_module_populates_sample_drill_and_redacts(monkeypatch, config):
    monkeypatch.setattr(
        dump_mod, "MODULES",
        {"drillable": _spec("drillable", _good_fetcher, drill_fetcher=_drill_fetcher)},
    )
    result = run_dump(FakeConnection(), config)
    entry = result["modules"]["drillable"]
    assert entry["sample_drill"] is not None
    assert entry["sample_drill"]["entity_id"] == "a1"
    # _redact must scrub the password field from the drill payload.
    assert entry["sample_drill"]["data"]["identity"]["password"] == "[redacted]"
