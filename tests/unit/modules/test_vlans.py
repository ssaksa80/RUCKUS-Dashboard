import responses
from ruckus_dashboard.auth.session_store import ConnectionConfig
from ruckus_dashboard.modules._base import FetcherContext
from ruckus_dashboard.modules import vlans as vlans_mod
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
def test_vlans_groups_per_switch_rows_by_vlan():
    # Rows are per-switch: VLAN 10 appears on two switches with ports each.
    sw_base = "https://sz.example:8443/switchm/api"
    responses.add(responses.POST, f"{sw_base}/v11_0/vlans/query",
                  json={"list": [
                      {"vlanId": 10, "name": "Corp", "switchId": "SW-A",
                       "ports": ["1", "2", "3"]},
                      {"vlanId": 10, "name": "Corp", "switchId": "SW-B",
                       "ports": ["1"]},
                      {"vlanId": 20, "name": "Voice", "switchId": "SW-A",
                       "ports": ["4", "5"]},
                  ], "totalCount": 3}, status=200, match_querystring=False)
    out = vlans_mod.fetch(_ctx())
    assert len(out["items"]) == 2
    corp = next(i for i in out["items"] if i["vlan_id"] == 10)
    assert corp["name"] == "Corp"
    assert corp["member_switch_count"] == 2
    assert corp["port_count"] == 4


def test_vlans_summary_aggregates():
    data = {"items": [
        {"member_switch_count": 2, "port_count": 48},
        {"member_switch_count": 1, "port_count": 22},
    ]}
    s = vlans_mod.summary(data)
    assert s["total_vlans"] == 2
    assert s["total_switch_links"] == 3
    assert s["total_ports"] == 70


def test_vlans_registered():
    from ruckus_dashboard.modules import MODULES
    assert MODULES["vlans"].fetcher is vlans_mod.fetch
