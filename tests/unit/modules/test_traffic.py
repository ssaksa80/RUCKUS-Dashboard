import responses
from ruckus_dashboard.auth.session_store import ConnectionConfig
from ruckus_dashboard.modules._base import FetcherContext
from ruckus_dashboard.modules import traffic as traffic_mod
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
def test_traffic_resolves_switch_name_from_mac():
    # Rows are {key: <MAC>, value: <bytes>}; name comes from the switch list.
    sw_base = "https://sz.example:8443/switchm/api"
    responses.add(responses.POST, f"{sw_base}/v11_0/switch",
                  json={"list": [{"id": "B0:7C:51:19:52:6C", "switchName": "SW-1"}],
                        "totalCount": 1, "hasMore": False},
                  status=200, match_querystring=False)
    responses.add(responses.POST, f"{sw_base}/v11_0/traffic/top/usage",
                  json={"list": [{"key": "B0:7C:51:19:52:6C", "value": 5368709120},
                                 {"key": "AA:BB:CC:DD:EE:FF", "value": 1073741824}]},
                  status=200, match_querystring=False)
    out = traffic_mod.fetch(_ctx())
    assert len(out["items"]) == 2
    assert out["items"][0]["switch_name"] == "SW-1"
    assert out["items"][0]["total_bytes"] == 5368709120
    # unknown MAC falls back to the MAC itself
    assert out["items"][1]["switch_name"] == "AA:BB:CC:DD:EE:FF"


def test_traffic_summary_top_switch():
    data = {"items": [
        {"switch_name": "SW-1", "total_bytes": 5368709120},
        {"switch_name": "SW-2", "total_bytes": 1073741824},
    ]}
    s = traffic_mod.summary(data)
    assert s["total_switches"] == 2
    assert s["total_bytes"] == 6442450944
    assert s["top_switch"] == "SW-1"


def test_traffic_registered():
    from ruckus_dashboard.modules import MODULES
    assert MODULES["traffic"].fetcher is traffic_mod.fetch
