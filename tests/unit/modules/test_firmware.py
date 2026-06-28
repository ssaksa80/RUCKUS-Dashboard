import json
import pathlib
import responses
from ruckus_dashboard.auth.session_store import ConnectionConfig
from ruckus_dashboard.modules._base import FetcherContext
from ruckus_dashboard.modules import firmware as firmware_mod
from ruckus_dashboard.infra.capability_gate import CapabilityGate

ZONES_FIX = {"list": [{"id": "z1", "name": "HQ"}], "totalCount": 1, "hasMore": False}
ZONE_FW = json.loads(pathlib.Path("tests/fixtures/smartzone/zone_apfirmware.json").read_text())

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
def test_firmware_fetch_returns_per_zone_catalog():
    base = "https://sz.example:8443/wsg/api/public"
    responses.add(responses.GET, f"{base}/v11_0/rkszones",
                  json=ZONES_FIX, status=200, match_querystring=False)
    responses.add(responses.GET, f"{base}/v11_0/rkszones/z1/apFirmware",
                  json=ZONE_FW, status=200, match_querystring=False)
    out = firmware_mod.fetch(_ctx())
    assert len(out["items"]) == 1
    z = out["items"][0]
    assert z["zone_name"] == "HQ"
    assert z["latest_supported"] == "7.0.0.300"
    assert len(z["catalog"]) == 2


def test_firmware_summary_aggregates():
    data = {"items": [
        {"catalog": [{"version": "7.0.0", "supported": True},
                     {"version": "6.1.2", "supported": False}]},
        {"catalog": [{"version": "7.0.0", "supported": True}]},
    ]}
    s = firmware_mod.summary(data)
    assert s["total_zones"] == 2
    assert s["total_supported_versions"] == 2
    assert s["unsupported_count"] == 1


def test_firmware_registered():
    from ruckus_dashboard.modules import MODULES
    assert MODULES["firmware"].fetcher is firmware_mod.fetch
