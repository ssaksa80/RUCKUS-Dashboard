import json, pathlib
import responses
from ruckus_dashboard.auth.session_store import ConnectionConfig
from ruckus_dashboard.modules._base import FetcherContext
from ruckus_dashboard.modules import clients as clients_mod
from ruckus_dashboard.infra.capability_gate import CapabilityGate

FIXTURE = json.loads(pathlib.Path("tests/fixtures/smartzone/query_client.json").read_text())
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
def test_clients_fetch_returns_normalised_rows():
    base = "https://sz.example:8443/wsg/api/public"
    responses.add(responses.POST, f"{base}/v11_0/query/client",
                  json=FIXTURE, status=200)
    out = clients_mod.fetch(_ctx())
    assert len(out["items"]) == 3
    assert out["items"][0]["mac"] == "11:22:33:44:55:01"
    assert out["items"][0]["rssi"] == -52
    assert out["items"][0]["ssid"] == "Corp"


def test_clients_summary_counts_low_rssi():
    data = {"items": [
        {"rssi": -52, "os": "Windows"},
        {"rssi": -68, "os": "iOS"},
        {"rssi": -75, "os": "Android"},
        {"rssi": -82, "os": "Android"},
    ]}
    s = clients_mod.summary(data)
    assert s["total"] == 4
    assert s["low_rssi"] == 2  # -75 + -82
    assert s["by_os"]["Android"] == 2


def test_clients_registered():
    from ruckus_dashboard.modules import MODULES
    assert MODULES["clients"].fetcher is clients_mod.fetch
