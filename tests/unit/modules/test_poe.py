import json, pathlib
import responses
from ruckus_dashboard.auth.session_store import ConnectionConfig
from ruckus_dashboard.modules._base import FetcherContext
from ruckus_dashboard.modules import poe as poe_mod
from ruckus_dashboard.infra.capability_gate import CapabilityGate

FIXTURE = json.loads(pathlib.Path("tests/fixtures/switchm/poe_utilization.json").read_text())
CFG = {"RUCKUS_TIMEOUT_SECONDS": 5, "RUCKUS_DEBUG_BYTES": 1000,
       "RUCKUS_PAGE_LIMIT": 500, "RUCKUS_HOST_ALLOWLIST": None}

def _ctx():
    conn = ConnectionConfig(platform="smartzone",
        api_base="https://sz.example:8443/wsg/api/public",
        display_name="SZ", auth_token="t", api_version="v11_0",
        verify_tls=False, token_expires_at=9999999999)
    return FetcherContext(connection=conn, config=CFG, filters=None,
        capability_gate=CapabilityGate(set()), connection_label="SZ")


@responses.activate
def test_poe_fetch_returns_normalised_rows():
    sw_base = "https://sz.example:8443/switchm/api"
    responses.add(responses.POST, f"{sw_base}/v11_0/traffic/top/poeutilization",
                  json=FIXTURE, status=200, match_querystring=False)
    out = poe_mod.fetch(_ctx())
    assert len(out["items"]) == 3
    first = out["items"][0]
    assert first["switch_name"] == "SW-1"
    assert first["budget_w"] == 740
    assert first["allocated_w"] == 320
    # util_pct: 320/740*100 = 43.243... -> 43.2
    assert first["util_pct"] == 43.2


def test_poe_summary_aggregates():
    data = {"items": [
        {"budget_w": 740, "allocated_w": 320, "ports_powered": 22, "util_pct": 43.2},
        {"budget_w": 1480, "allocated_w": 900, "ports_powered": 35, "util_pct": 60.8},
    ]}
    s = poe_mod.summary(data)
    assert s["total_switches"] == 2
    assert s["total_budget_w"] == 2220
    assert s["total_allocated_w"] == 1220
    assert s["total_ports_powered"] == 57


def test_poe_registered():
    from ruckus_dashboard.modules import MODULES
    assert MODULES["poe"].fetcher is poe_mod.fetch
