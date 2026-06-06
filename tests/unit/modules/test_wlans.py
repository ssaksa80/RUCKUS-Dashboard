import json, pathlib
import responses
from ruckus_dashboard.auth.session_store import ConnectionConfig
from ruckus_dashboard.modules._base import FetcherContext
from ruckus_dashboard.modules import wlans as wlans_mod
from ruckus_dashboard.infra.capability_gate import CapabilityGate

FIXTURE = json.loads(pathlib.Path("tests/fixtures/smartzone/query_wlan.json").read_text())
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
def test_wlans_fetch_returns_normalised_rows():
    base = "https://sz.example:8443/wsg/api/public"
    responses.add(responses.POST, f"{base}/v11_0/query/wlan",
                  json=FIXTURE, status=200)
    out = wlans_mod.fetch(_ctx())
    assert len(out["items"]) == 2
    assert out["items"][0]["ssid"] == "Corp"
    assert out["items"][0]["vlan"] == 10
    assert out["items"][1]["auth"] == "OPEN"


def test_wlans_summary_with_by_auth():
    data = {"items": [
        {"clients": 45, "auth": "8021X"},
        {"clients": 12, "auth": "OPEN"},
        {"clients": 3, "auth": "8021X"},
    ]}
    s = wlans_mod.summary(data)
    assert s["total"] == 3
    assert s["clients"] == 60
    assert s["by_auth"]["8021X"] == 2
    assert s["by_auth"]["OPEN"] == 1


def test_wlans_merge_concats():
    out = wlans_mod.merge([{"items": [{"id": "1"}]}, {"items": [{"id": "2"}]}])
    assert len(out["items"]) == 2


def test_wlans_registered():
    from ruckus_dashboard.modules import MODULES
    assert MODULES["wlans"].fetcher is wlans_mod.fetch
