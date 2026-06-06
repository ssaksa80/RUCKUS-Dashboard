import json, pathlib
import responses
from ruckus_dashboard.auth.session_store import ConnectionConfig
from ruckus_dashboard.modules._base import FetcherContext
from ruckus_dashboard.modules import controller as controller_mod
from ruckus_dashboard.infra.capability_gate import CapabilityGate

CLUSTER = json.loads(pathlib.Path("tests/fixtures/smartzone/cluster_state.json").read_text())
DEVICES = json.loads(pathlib.Path("tests/fixtures/smartzone/devicesSummary.json").read_text())
LICENSES = json.loads(pathlib.Path("tests/fixtures/smartzone/licensesSummary.json").read_text())

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
def test_controller_fetch_combines_three_endpoints():
    base = "https://sz.example:8443/wsg/api/public"
    responses.add(responses.GET, f"{base}/v11_0/cluster/state",
                  json=CLUSTER, status=200, match_querystring=False)
    responses.add(responses.GET, f"{base}/v11_0/system/devicesSummary",
                  json=DEVICES, status=200, match_querystring=False)
    responses.add(responses.GET, f"{base}/v11_0/licensesSummary",
                  json=LICENSES, status=200, match_querystring=False)
    out = controller_mod.fetch(_ctx())
    assert out["cluster"]["clusterName"] == "sz-cluster"
    assert out["devices"]["apCount"] == 30
    assert "summary" in out["licenses"] or isinstance(out["licenses"], (list, dict))


def test_controller_summary_aggregates_counts():
    data = {
        "cluster": {"currentNodes": 3, "totalNodes": 3},
        "devices": {"apCount": 30, "switchCount": 8, "clientCount": 142},
        "licenses": {"summary": [
            {"totalCount": 100, "consumedCount": 30},
            {"totalCount": 25, "consumedCount": 8},
        ]},
    }
    s = controller_mod.summary(data)
    assert s["nodes_online"] == 3
    assert s["nodes_total"] == 3
    assert s["license_used"] == 38
    assert s["license_total"] == 125


def test_controller_summary_handles_missing_pieces():
    s = controller_mod.summary({})
    assert s["nodes_online"] == 0
    assert s["license_total"] == 0


def test_controller_registered():
    from ruckus_dashboard.modules import MODULES
    assert MODULES["controller"].fetcher is controller_mod.fetch
