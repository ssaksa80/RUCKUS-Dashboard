import responses
from ruckus_dashboard.auth.session_store import ConnectionConfig
from ruckus_dashboard.modules._base import FetcherContext
from ruckus_dashboard.modules import controller as controller_mod
from ruckus_dashboard.infra.capability_gate import CapabilityGate

CFG = {"RUCKUS_TIMEOUT_SECONDS": 5, "RUCKUS_DEBUG_BYTES": 1000,
       "RUCKUS_PAGE_LIMIT": 500, "RUCKUS_HOST_ALLOWLIST": None}

CLUSTER = {"clusterName": "AHD-SZ-WLC", "clusterState": "In_Service",
           "clusterRole": "Leader",
           "nodeStateList": [
               {"nodeId": "n1", "nodeName": "WLC-Pr1", "nodeState": "In_Service"},
               {"nodeId": "n2", "nodeName": "WLC-Pr2", "nodeState": "Out_Of_Service"},
           ]}
DEVICES = {"aps": 340, "totalAps": 932, "switches": 39, "totalSwitches": 77}


def _ctx():
    conn = ConnectionConfig(platform="smartzone",
        api_base="https://sz.example:8443/wsg/api/public",
        display_name="SZ", auth_token="t", api_version="v11_0",
        verify_tls=False, token_expires_at=9999999999)
    return FetcherContext(connection=conn, config=CFG, filters=None,
        capability_gate=CapabilityGate(set()), connection_label="SZ")


@responses.activate
def test_controller_fetch_lists_nodes_and_keeps_devices():
    base = "https://sz.example:8443/wsg/api/public"
    responses.add(responses.GET, f"{base}/v11_0/cluster/state",
                  json=CLUSTER, status=200, match_querystring=False)
    responses.add(responses.GET, f"{base}/v11_0/system/devicesSummary",
                  json=DEVICES, status=200, match_querystring=False)
    out = controller_mod.fetch(_ctx())
    assert len(out["items"]) == 2
    assert out["items"][0]["node"] == "WLC-Pr1"
    assert out["items"][0]["state"] == "In_Service"
    assert out["devices"]["totalAps"] == 932


def test_controller_summary_from_cluster_and_devices():
    data = {"cluster": CLUSTER, "devices": DEVICES}
    s = controller_mod.summary(data)
    assert s["cluster_state"] == "In_Service"
    assert s["nodes_total"] == 2
    assert s["nodes_online"] == 1  # one In_Service, one Out_Of_Service
    assert s["aps_connected"] == 340
    assert s["total_aps"] == 932
    assert s["total_switches"] == 77


def test_controller_summary_handles_missing_pieces():
    s = controller_mod.summary({})
    assert s["nodes_online"] == 0
    assert s["nodes_total"] == 0
    assert s["total_aps"] == 0


def test_controller_merge_preserves_cluster_and_devices():
    # Default merge keeps only items; controller.merge must keep cluster/devices
    # so the KPI summary is not zeroed out by the data route.
    merged = controller_mod.merge([
        {"items": [{"node": "n1"}], "cluster": CLUSTER, "devices": DEVICES},
    ])
    assert merged["cluster"]["clusterState"] == "In_Service"
    assert merged["devices"]["totalAps"] == 932
    s = controller_mod.summary(merged)
    assert s["total_aps"] == 932


def test_controller_registered():
    from ruckus_dashboard.modules import MODULES
    assert MODULES["controller"].fetcher is controller_mod.fetch
