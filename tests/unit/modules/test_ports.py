import responses
from ruckus_dashboard.auth.session_store import ConnectionConfig
from ruckus_dashboard.modules._base import FetcherContext
from ruckus_dashboard.modules import ports as ports_mod
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
def test_ports_per_switch_summary_from_switch_list():
    # Derived from the switch inventory (no fabric-wide per-port list on 7.1.1).
    sw_base = "https://sz.example:8443/switchm/api"
    responses.add(responses.POST, f"{sw_base}/v11_0/switch",
                  json={"list": [
                      {"id": "s1", "switchName": "SW-1", "ipAddress": "10.0.0.1",
                       "model": "ICX7550-24",
                       "portStatus": {"up": 24, "down": 25, "warning": 3, "total": 52},
                       "poe": {"total": 740, "free": 500, "percent": 32.4}},
                  ], "totalCount": 1, "hasMore": False},
                  status=200, match_querystring=False)
    out = ports_mod.fetch(_ctx())
    assert len(out["items"]) == 1
    row = out["items"][0]
    assert row["switch"] == "SW-1"
    assert row["ports_total"] == 52
    assert row["ports_up"] == 24
    assert row["poe_used_w"] == 240


def test_ports_summary_aggregates_port_counts():
    data = {"items": [
        {"ports_total": 52, "ports_up": 24, "ports_down": 25, "ports_warning": 3},
        {"ports_total": 24, "ports_up": 10, "ports_down": 14, "ports_warning": 0},
    ]}
    s = ports_mod.summary(data)
    assert s["switches"] == 2
    assert s["ports_total"] == 76
    assert s["ports_up"] == 34
    assert s["ports_down"] == 39


def test_ports_registered():
    from ruckus_dashboard.modules import MODULES
    assert MODULES["ports"].fetcher is ports_mod.fetch
