import responses
from ruckus_dashboard.auth.session_store import ConnectionConfig
from ruckus_dashboard.modules._base import FetcherContext
from ruckus_dashboard.modules import wlans as wlans_mod
from ruckus_dashboard.infra.capability_gate import CapabilityGate

CFG = {"RUCKUS_TIMEOUT_SECONDS": 5, "RUCKUS_DEBUG_BYTES": 1000,
       "RUCKUS_PAGE_LIMIT": 500, "RUCKUS_HOST_ALLOWLIST": None}

WLANS = {"list": [
    {"id": "w1", "name": "Corp", "zoneName": "HQ", "zoneId": "z1",
     "vlanId": 10, "authType": "8021X", "encryption": "AES", "numClients": 0},
    {"id": "w2", "name": "Guest", "zoneName": "HQ", "zoneId": "z1",
     "vlanId": 20, "authType": "OPEN", "encryption": "None", "numClients": 0},
    {"id": "w3", "name": "Branch", "zoneName": "Branch", "zoneId": "z2",
     "vlanId": 30, "authType": "8021X", "encryption": "AES", "numClients": 0},
], "totalCount": 3, "hasMore": False}

CLIENTS = {"list": [
    {"clientMac": "a", "ssid": "Corp", "zoneId": "z1"},
    {"clientMac": "b", "ssid": "Guest", "zoneId": "z1"},
    {"clientMac": "c", "ssid": "Branch", "zoneId": "z2"},
    {"clientMac": "d", "ssid": "Corp"},        # no zoneId -> SSID join
], "totalCount": 4, "hasMore": False}


def _ctx():
    conn = ConnectionConfig(platform="smartzone",
        api_base="https://sz.example:8443/wsg/api/public",
        display_name="SZ", auth_token="t", api_version="v11_0",
        verify_tls=False, token_expires_at=9999999999)
    return FetcherContext(connection=conn, config=CFG, filters=None,
        capability_gate=CapabilityGate(set()), connection_label="SZ")


def _mock(base="https://sz.example:8443/wsg/api/public"):
    responses.add(responses.POST, f"{base}/v11_0/query/wlan",
                  json=WLANS, status=200)
    responses.add(responses.POST, f"{base}/v11_0/query/client",
                  json=CLIENTS, status=200)


@responses.activate
def test_wlans_grouped_per_site_with_client_counts():
    _mock()
    out = wlans_mod.fetch(_ctx())
    by_site = {i["site"]: i for i in out["items"]}
    assert by_site["HQ"]["wlan_count"] == 2
    # 2 clients with zoneId z1 + 1 SSID-joined (Corp, no zoneId) = 3
    assert by_site["HQ"]["clients"] == 3
    assert by_site["Branch"]["wlan_count"] == 1
    assert by_site["Branch"]["clients"] == 1
    assert "Corp" in by_site["HQ"]["ssids"]


@responses.activate
def test_wlans_site_drill_lists_site_wlans():
    _mock()
    out = wlans_mod.fetch_drill(_ctx(), "z1")
    assert out["identity"]["site"] == "HQ"
    assert out["identity"]["wlan_count"] == 2
    assert {w["ssid"] for w in out["wlans"]} == {"Corp", "Guest"}


def test_wlans_summary_totals():
    data = {"items": [{"wlan_count": 2, "clients": 30},
                      {"wlan_count": 1, "clients": 5}]}
    s = wlans_mod.summary(data)
    assert s["sites"] == 2
    assert s["total_wlans"] == 3
    assert s["total_clients"] == 35


def test_wlans_merge_concats():
    out = wlans_mod.merge([{"items": [{"id": "1"}]}, {"items": [{"id": "2"}]}])
    assert len(out["items"]) == 2


def test_wlans_registered():
    from ruckus_dashboard.modules import MODULES
    assert MODULES["wlans"].fetcher is wlans_mod.fetch
