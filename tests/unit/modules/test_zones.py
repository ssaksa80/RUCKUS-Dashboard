import responses
from ruckus_dashboard.auth.session_store import ConnectionConfig
from ruckus_dashboard.modules._base import FetcherContext
from ruckus_dashboard.modules import zones as zones_mod
from ruckus_dashboard.infra.capability_gate import CapabilityGate

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
def test_zones_fetch_enriches_from_detail_and_ap_counts():
    base = "https://sz.example:8443/wsg/api/public"
    # Sparse zone list (id + name only — real 7.1.1 shape).
    responses.add(responses.GET, f"{base}/v11_0/rkszones",
                  json={"list": [{"id": "z1", "name": "HQ"}],
                        "totalCount": 1, "hasMore": False}, status=200)
    # Per-zone detail carries country / firmware / mesh.
    responses.add(responses.GET, f"{base}/v11_0/rkszones/z1",
                  json={"id": "z1", "name": "HQ", "countryCode": "AE",
                        "version": "7.1.1.0.8002",
                        "mesh": {"enabled": False}, "description": "HQ zone"},
                  status=200, match_querystring=False)
    # AP counts derived from one bulk /query/ap.
    responses.add(responses.POST, f"{base}/v11_0/query/ap",
                  json={"list": [{"apMac": "a", "zoneId": "z1"},
                                 {"apMac": "b", "zoneId": "z1"}],
                        "totalCount": 2}, status=200)
    out = zones_mod.fetch(_ctx())
    z = out["items"][0]
    assert z["name"] == "HQ"
    assert z["ap_count"] == 2
    assert z["country"] == "AE"
    assert z["fw"] == "7.1.1.0.8002"
    assert z["mesh_mode"] == "Disabled"
    assert z["description"] == "HQ zone"


def test_zones_summary_sums_aps():
    data = {"items": [{"ap_count": 24}, {"ap_count": 6}]}
    s = zones_mod.summary(data)
    assert s["total"] == 2
    assert s["total_aps"] == 30


def test_zones_merge_concats():
    a = {"items": [{"id": "z1"}]}
    b = {"items": [{"id": "z2"}]}
    out = zones_mod.merge([a, b])
    assert len(out["items"]) == 2


def test_zones_registered():
    from ruckus_dashboard.modules import MODULES
    assert MODULES["zones"].fetcher is zones_mod.fetch
