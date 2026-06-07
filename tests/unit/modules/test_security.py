import responses

from ruckus_dashboard.auth.session_store import ConnectionConfig
from ruckus_dashboard.modules._base import FetcherContext
from ruckus_dashboard.modules import security as security_mod
from ruckus_dashboard.infra.capability_gate import CapabilityGate

CFG = {"RUCKUS_TIMEOUT_SECONDS": 5, "RUCKUS_DEBUG_BYTES": 1000,
       "RUCKUS_PAGE_LIMIT": 500, "RUCKUS_HOST_ALLOWLIST": None,
       "RUCKUS_SECURITY_LOOKUPS": False,
       "RUCKUS_MAX_SECURITY_LOOKUPS": 12, "RUCKUS_NVD_RESULTS": 5,
       "RUCKUS_SECURITY_CACHE_SECONDS": 21600}


def _ctx():
    conn = ConnectionConfig(platform="smartzone",
        api_base="https://sz.example:8443/wsg/api/public",
        display_name="SZ", auth_token="t", api_version="v11_0",
        verify_tls=False, token_expires_at=9999999999)
    return FetcherContext(connection=conn, config=CFG, filters=None,
        capability_gate=CapabilityGate(set()), connection_label="SZ")


@responses.activate
def test_security_fetch_with_lookups_disabled():
    base = "https://sz.example:8443/wsg/api/public"
    responses.add(responses.POST, f"{base}/v11_0/query/ap",
                  json={"list": [
                      {"apMac": "AA:BB:CC:DD:EE:01", "deviceName": "AP-1",
                       "model": "R650", "firmwareVersion": "7.0.0"}
                  ], "totalCount": 1}, status=200)
    out = security_mod.fetch(_ctx())
    assert len(out["items"]) == 1
    # each asset carries a security dict
    assert "security" in out["items"][0]
    assert out["validation"]["status"] == "disabled"


def test_security_summary_counts_by_status():
    data = {"items": [
        {"security": {"status": "critical"}},
        {"security": {"status": "watch"}},
        {"security": {"status": "ok"}},
        {"security": {"status": "ok"}},
    ]}
    s = security_mod.summary(data)
    assert s["critical"] == 1
    assert s["watch"] == 1
    assert s["ok"] == 2


def test_security_registered():
    from ruckus_dashboard.modules import MODULES
    assert MODULES["security"].fetcher is security_mod.fetch
