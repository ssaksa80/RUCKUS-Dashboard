import responses
from ruckus_dashboard.auth.session_store import ConnectionConfig
from ruckus_dashboard.modules._base import FetcherContext
from ruckus_dashboard.modules import switch_groups as sg_mod
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
def test_switch_groups_derived_from_switch_list():
    # SmartZone 7.1.1 has no POST /group; groups are derived from the switch
    # inventory (each switch carries groupId/groupName).
    sw_base = "https://sz.example:8443/switchm/api"
    responses.add(responses.POST, f"{sw_base}/v11_0/switch",
                  json={"list": [
                      {"id": "a", "groupId": "g1", "groupName": "HQ-Switches"},
                      {"id": "b", "groupId": "g1", "groupName": "HQ-Switches"},
                      {"id": "c", "groupId": "g2", "groupName": "Branch"},
                  ], "totalCount": 3, "hasMore": False},
                  status=200, match_querystring=False)
    out = sg_mod.fetch(_ctx())
    by_name = {g["name"]: g for g in out["items"]}
    assert by_name["HQ-Switches"]["switch_count"] == 2
    assert by_name["Branch"]["switch_count"] == 1


def test_switch_groups_summary_counts_roots():
    data = {"items": [
        {"switch_count": 4, "parent_id": None},
        {"switch_count": 2, "parent_id": None},
        {"switch_count": 2, "parent_id": "g1"},
    ]}
    s = sg_mod.summary(data)
    assert s["total"] == 3
    assert s["total_switches"] == 8
    assert s["root_groups"] == 2


def test_switch_groups_registered():
    from ruckus_dashboard.modules import MODULES
    assert MODULES["switch-groups"].fetcher is sg_mod.fetch
