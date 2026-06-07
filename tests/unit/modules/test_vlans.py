import json, pathlib
import responses
from ruckus_dashboard.auth.session_store import ConnectionConfig
from ruckus_dashboard.modules._base import FetcherContext
from ruckus_dashboard.modules import vlans as vlans_mod
from ruckus_dashboard.infra.capability_gate import CapabilityGate

FIXTURE = json.loads(pathlib.Path("tests/fixtures/switchm/vlan_list.json").read_text())
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
def test_vlans_fetch_returns_normalised_rows():
    sw_base = "https://sz.example:8443/switchm/api/public"
    responses.add(responses.POST, f"{sw_base}/v11_0/vlan/list",
                  json=FIXTURE, status=200, match_querystring=False)
    out = vlans_mod.fetch(_ctx())
    assert len(out["items"]) == 3
    corp = next(i for i in out["items"] if i["vlan_id"] == 10)
    assert corp["name"] == "Corp"
    assert corp["member_switch_count"] == 2
    assert corp["tagged_ports"] == 4


def test_vlans_summary_aggregates():
    data = {"items": [
        {"tagged_ports": 0, "untagged_ports": 48},
        {"tagged_ports": 4, "untagged_ports": 22},
    ]}
    s = vlans_mod.summary(data)
    assert s["total_vlans"] == 2
    assert s["total_tagged_ports"] == 4
    assert s["total_untagged_ports"] == 70


def test_vlans_registered():
    from ruckus_dashboard.modules import MODULES
    assert MODULES["vlans"].fetcher is vlans_mod.fetch
