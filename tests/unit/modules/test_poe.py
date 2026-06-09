import responses
from ruckus_dashboard.auth.session_store import ConnectionConfig
from ruckus_dashboard.modules._base import FetcherContext
from ruckus_dashboard.modules import poe as poe_mod
from ruckus_dashboard.infra.capability_gate import CapabilityGate

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
def test_poe_derived_from_switch_poe_block():
    # PoE budget is derived from each switch row's poe block (7.1.1 shape).
    sw_base = "https://sz.example:8443/switchm/api"
    responses.add(responses.POST, f"{sw_base}/v11_0/switch",
                  json={"list": [
                      {"id": "s1", "switchName": "SW-1",
                       "poe": {"total": 740, "free": 500, "percent": 32.4}},
                  ], "totalCount": 1, "hasMore": False},
                  status=200, match_querystring=False)
    out = poe_mod.fetch(_ctx())
    assert len(out["items"]) == 1
    row = out["items"][0]
    assert row["switch_name"] == "SW-1"
    assert row["budget_w"] == 740
    assert row["available_w"] == 500
    assert row["allocated_w"] == 240
    assert row["util_pct"] == 32.4


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
