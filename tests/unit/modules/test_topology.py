import responses
from ruckus_dashboard.auth.session_store import ConnectionConfig
from ruckus_dashboard.modules._base import FetcherContext
from ruckus_dashboard.modules import topology as topology_mod
from ruckus_dashboard.infra.capability_gate import CapabilityGate

CFG = {"RUCKUS_TIMEOUT_SECONDS": 5, "RUCKUS_DEBUG_BYTES": 1000,
       "RUCKUS_PAGE_LIMIT": 500, "RUCKUS_HOST_ALLOWLIST": None}

CLUSTER = {"clusterName": "AHD-SZ", "clusterState": "In_Service"}
ZONES = [{"id": "z1", "name": "HQ"}]
APS = [{"apMac": "a1", "zoneId": "z1", "status": "Online"},
       {"apMac": "a2", "zoneId": "z1", "status": "Offline"}]
SWITCHES = [{"id": "s1", "switchName": "SW-1", "groupId": "g1",
             "groupName": "Core", "status": "online"}]


def _ctx():
    conn = ConnectionConfig(platform="smartzone",
        api_base="https://sz.example:8443/wsg/api/public", display_name="SZ",
        auth_token="t", api_version="v11_0", verify_tls=False, token_expires_at=9999999999)
    return FetcherContext(connection=conn, config=CFG, filters=None,
        capability_gate=CapabilityGate(set()), connection_label="SZ")


def test_build_graph_shapes_nodes_and_edges():
    g = topology_mod._build_graph(CLUSTER, ZONES, APS, SWITCHES, {"s1": 1024})
    types = {n["type"] for n in g["nodes"]}
    assert {"controller", "zone", "group", "switch"} <= types
    ctrl = next(n for n in g["nodes"] if n["type"] == "controller")
    assert ctrl["status"] == "online"
    zone = next(n for n in g["nodes"] if n["type"] == "zone")
    assert zone["meta"]["ap_total"] == 2 and zone["meta"]["ap_down"] == 1
    assert zone["status"] == "flagged"
    pairs = {(e["source"], e["target"]) for e in g["edges"]}
    assert ("controller", "z1") in pairs
    assert ("controller", "g1") in pairs
    assert ("g1", "s1") in pairs
    sw_edge = next(e for e in g["edges"] if e["target"] == "s1")
    assert sw_edge["label"]


def test_summary_counts():
    g = topology_mod._build_graph(CLUSTER, ZONES, APS, SWITCHES, {"s1": 1024})
    s = topology_mod.summary(g)
    assert s["nodes"] == len(g["nodes"])
    assert s["switches"] == 1


def test_merge_preserves_graph():
    g = topology_mod._build_graph(CLUSTER, ZONES, APS, SWITCHES, {})
    merged = topology_mod.merge([g])
    assert merged["nodes"] == g["nodes"]
    assert merged["edges"] == g["edges"]


@responses.activate
def test_topology_fetch_assembles_graph():
    base = "https://sz.example:8443/wsg/api/public"
    sw = "https://sz.example:8443/switchm/api"
    responses.add(responses.GET, f"{base}/v11_0/cluster/state",
                  json=CLUSTER, status=200)
    responses.add(responses.GET, f"{base}/v11_0/rkszones",
                  json={"list": ZONES, "totalCount": 1, "hasMore": False}, status=200)
    responses.add(responses.POST, f"{base}/v11_0/query/ap",
                  json={"list": APS, "totalCount": 2}, status=200)
    responses.add(responses.POST, f"{sw}/v11_0/switch",
                  json={"list": SWITCHES, "totalCount": 1, "hasMore": False},
                  status=200, match_querystring=False)
    responses.add(responses.POST, f"{sw}/v11_0/traffic/top/usage",
                  json={"list": [{"key": "s1", "value": 2048}]},
                  status=200, match_querystring=False)
    out = topology_mod.fetch(_ctx())
    assert any(n["type"] == "controller" for n in out["nodes"])
    assert any(n["type"] == "switch" for n in out["nodes"])
    assert any(n["type"] == "zone" for n in out["nodes"])


def test_build_graph_meta_and_alarm_badges():
    g = topology_mod._build_graph(
        CLUSTER, ZONES, APS,
        [{"id": "B0:7C:51:19:52:6C", "switchName": "AHDSP-CORE", "groupId": "g1",
          "groupName": "Core", "status": "online", "ipAddress": "10.0.0.2",
          "model": "ICX7550", "firmwareVersion": "GZR10010"}],
        {"B0:7C:51:19:52:6C": 2048}, alarms_by_name={"ahdsp-core": 2})
    sw = next(n for n in g["nodes"] if n["type"] == "switch")
    assert sw["meta"]["ip"] == "10.0.0.2"
    assert sw["meta"]["model"] == "ICX7550"
    assert sw["meta"]["alarm_count"] == 2
    assert sw["status"] == "flagged"   # online + alarms -> flagged


def test_build_graph_zone_expansion_caps_and_orders():
    aps = ([{"apMac": f"AA:{i:04X}", "deviceName": f"AP{i}", "zoneId": "z1",
             "status": "Online"} for i in range(70)] +
           [{"apMac": "BB:01", "deviceName": "AP-DOWN", "zoneId": "z1",
             "status": "Offline"}])
    g = topology_mod._build_graph(CLUSTER, ZONES, aps, [], {}, expand={"z1"})
    ap_nodes = [n for n in g["nodes"] if n["type"] == "ap"]
    assert len(ap_nodes) == 60
    assert ap_nodes[0]["status"] == "offline"      # offline first
    more = [n for n in g["nodes"] if n["type"] == "more"]
    assert more and "+11 more" in more[0]["label"]
    assert any(e["source"] == "z1" and e["target"] == ap_nodes[0]["id"]
               for e in g["edges"])


def test_topology_registered():
    from ruckus_dashboard.modules import MODULES
    assert MODULES["topology"].fetcher is topology_mod.fetch


def test_expanded_ap_nodes_carry_avg_signal():
    aps = [{"apMac": "AA:01", "deviceName": "AP-LOBBY", "zoneId": "z1",
            "status": "Online"}]
    g = topology_mod._build_graph(CLUSTER, ZONES, aps, [], {}, expand={"z1"},
                                  rssi_by_ap={"aa:01": -62})
    ap = next(n for n in g["nodes"] if n["type"] == "ap")
    assert ap["meta"]["rssi_avg"] == -62
    assert "(-62 dB)" in ap["label"]
