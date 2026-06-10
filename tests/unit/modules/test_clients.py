import responses
from ruckus_dashboard.auth.session_store import ConnectionConfig
from ruckus_dashboard.modules._base import FetcherContext
from ruckus_dashboard.modules import clients as clients_mod
from ruckus_dashboard.infra.capability_gate import CapabilityGate

CFG = {"RUCKUS_TIMEOUT_SECONDS": 5, "RUCKUS_DEBUG_BYTES": 1000,
       "RUCKUS_PAGE_LIMIT": 500, "RUCKUS_HOST_ALLOWLIST": None}

ROW = {"clientMac": "BC:F1:05:36:2F:F4", "hostname": "laptop-1",
       "ipAddress": "10.1.2.3", "userName": "shoaib", "ssid": "CORP",
       "apName": "AP-Lobby", "radioType": "11ax-5G", "channel": 56,
       "vlanId": 20, "rssi": -62, "snr": 38, "rxBytes": 1024, "txBytes": 2048,
       "osType": "Windows", "sessionStartTime": 0}


def _ctx():
    conn = ConnectionConfig(platform="smartzone",
        api_base="https://sz.example:8443/wsg/api/public", display_name="SZ",
        auth_token="t", api_version="v11_0", verify_tls=False,
        token_expires_at=9999999999)
    return FetcherContext(connection=conn, config=CFG, filters=None,
        capability_gate=CapabilityGate(set()), connection_label="SZ")


def _mock_list():
    base = "https://sz.example:8443/wsg/api/public"
    responses.add(responses.POST, f"{base}/v11_0/query/client",
                  json={"list": [ROW], "totalCount": 1, "hasMore": False},
                  status=200)


@responses.activate
def test_clients_fetch_normalises_and_keeps_raw_rows():
    _mock_list()
    out = clients_mod.fetch(_ctx())
    c = out["items"][0]
    assert c["band"] == "5 GHz"
    assert c["quality"] == "good"        # -62 dBm
    assert c["user"] == "shoaib"
    assert c["vlan"] == 20
    assert out["raw_rows"][0]["clientMac"] == ROW["clientMac"]


@responses.activate
def test_clients_drill_matches_mac_from_list():
    _mock_list()
    out = clients_mod.fetch_drill(_ctx(), "bc:f1:05:36:2f:f4")
    assert out["identity"]["hostname"] == "laptop-1"
    assert out["connection"]["band"] == "5 GHz"
    assert out["connection"]["quality"] == "good"
    assert out["usage"]["tx_bytes"] == 2048
    assert out["raw"]["clientMac"] == ROW["clientMac"]
    assert "error" not in out


@responses.activate
def test_clients_drill_not_found_is_friendly():
    _mock_list()
    out = clients_mod.fetch_drill(_ctx(), "00:00:00:00:00:00")
    assert "not currently connected" in out["identity"]["note"]
    assert "error" not in out


def test_band_and_quality_derivations():
    assert clients_mod._band({"radioType": "11ax (6GHz)"}) == "6 GHz"
    assert clients_mod._band({"radioType": "11g/n"}) == "2.4 GHz"
    assert clients_mod._band({}) == "—"
    assert clients_mod._quality(-62) == "good"
    assert clients_mod._quality(-70) == "fair"
    assert clients_mod._quality(-80) == "poor"
    assert clients_mod._quality(30) == "good"   # positive SNR-like scale
    assert clients_mod._quality(10) == "poor"
    assert clients_mod._quality(0) == "unknown"


def test_clients_summary_bands_poor_and_top_talker():
    data = {"items": [
        {"band": "5 GHz", "quality": "good", "rx_bytes": 10, "tx_bytes": 10,
         "hostname": "a"},
        {"band": "2.4 GHz", "quality": "poor", "rx_bytes": 500, "tx_bytes": 600,
         "hostname": "big-talker"},
    ]}
    s = clients_mod.summary(data)
    assert s["total"] == 2
    assert s["band_5"] == 1 and s["band_2_4"] == 1
    assert s["poor_signal"] == 1
    assert s["top_talker"] == "big-talker"


def test_clients_registered():
    from ruckus_dashboard.modules import MODULES
    assert MODULES["clients"].fetcher is clients_mod.fetch
    assert [t.slug for t in MODULES["clients"].drill_tabs] == [
        "summary", "connection", "usage", "raw"]
