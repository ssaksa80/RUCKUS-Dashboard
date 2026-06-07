import json, pathlib
import responses
from ruckus_dashboard.auth.session_store import ConnectionConfig
from ruckus_dashboard.modules._base import FetcherContext
from ruckus_dashboard.modules import switch_groups as sg_mod
from ruckus_dashboard.infra.capability_gate import CapabilityGate

FIXTURE = json.loads(pathlib.Path("tests/fixtures/switchm/group_list.json").read_text())
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
def test_switch_groups_fetch_returns_normalised_rows():
    sw_base = "https://sz.example:8443/switchm/api/public"
    responses.add(responses.POST, f"{sw_base}/v11_0/group/list",
                  json=FIXTURE, status=200, match_querystring=False)
    out = sg_mod.fetch(_ctx())
    assert len(out["items"]) == 3
    assert out["items"][0]["name"] == "HQ-Switches"
    assert out["items"][0]["switch_count"] == 4


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
