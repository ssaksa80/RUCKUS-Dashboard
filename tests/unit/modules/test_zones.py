import json, pathlib
import responses
from ruckus_dashboard.auth.session_store import ConnectionConfig
from ruckus_dashboard.modules._base import FetcherContext
from ruckus_dashboard.modules import zones as zones_mod
from ruckus_dashboard.infra.capability_gate import CapabilityGate

FIXTURE = json.loads(pathlib.Path("tests/fixtures/smartzone/rkszones.json").read_text())

CFG = {"RUCKUS_TIMEOUT_SECONDS": 5, "RUCKUS_DEBUG_BYTES": 1000,
       "RUCKUS_PAGE_LIMIT": 500, "RUCKUS_HOST_ALLOWLIST": None}


def _ctx(filters=None):
    conn = ConnectionConfig(platform="smartzone",
                            api_base="https://sz.example:8443/wsg/api/public",
                            display_name="SZ", auth_token="t",
                            api_version="v11_0", verify_tls=False,
                            token_expires_at=9999999999)
    return FetcherContext(connection=conn, config=CFG, filters=filters,
                          capability_gate=CapabilityGate(set()),
                          connection_label="SZ")


@responses.activate
def test_zones_fetch_returns_normalised_rows():
    base = "https://sz.example:8443/wsg/api/public"
    responses.add(responses.GET, f"{base}/v11_0/rkszones",
                  json=FIXTURE, status=200)
    out = zones_mod.fetch(_ctx())
    assert len(out["items"]) == 2
    first = out["items"][0]
    assert first["name"] == "HQ"
    assert first["ap_count"] == 24
    assert first["wlan_count"] == 8


def test_zones_summary_sums_aps_and_wlans():
    data = {"items": [
        {"ap_count": 24, "wlan_count": 8},
        {"ap_count": 6, "wlan_count": 4},
    ]}
    s = zones_mod.summary(data)
    assert s["total"] == 2
    assert s["total_aps"] == 30
    assert s["total_wlans"] == 12


def test_zones_merge_concats():
    a = {"items": [{"id": "z1"}]}
    b = {"items": [{"id": "z2"}]}
    out = zones_mod.merge([a, b])
    assert len(out["items"]) == 2


def test_zones_registered():
    from ruckus_dashboard.modules import MODULES
    assert MODULES["zones"].fetcher is zones_mod.fetch
