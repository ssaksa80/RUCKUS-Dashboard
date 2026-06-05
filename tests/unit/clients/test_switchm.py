import responses
from ruckus_dashboard.auth.session_store import ConnectionConfig
from ruckus_dashboard.clients.switchm import (
    fetch_switches,
    switch_manager_base,
    switch_query_payload,
)

CFG = {
    "RUCKUS_TIMEOUT_SECONDS": 5,
    "RUCKUS_DEBUG_BYTES": 1000,
    "RUCKUS_PAGE_LIMIT": 500,
    "RUCKUS_HOST_ALLOWLIST": None,
}


def test_switch_query_payload_shape():
    p = switch_query_payload(page=1, limit=50)
    assert p["page"] == 1
    assert p["limit"] == 50
    assert "sortColumn" in p["sortInfo"]


def test_switch_manager_base_from_smartzone_base():
    sz = "https://sz.example:8443/wsg/api/public"
    assert switch_manager_base(sz) == "https://sz.example:8443/switchm/api/public"


@responses.activate
def test_fetch_switches_paged():
    base = "https://sz.example:8443/switchm/api/public"
    responses.add(
        responses.POST,
        f"{base}/v11_0/switch/view/details",
        json={
            "list": [
                {
                    "id": "s1",
                    "name": "SW-1",
                    "model": "ICX7150",
                    "ip": "10.0.0.1",
                    "status": "Online",
                }
            ],
            "totalCount": 1,
            "hasMore": False,
        },
        status=200,
    )
    sz_base = "https://sz.example:8443/wsg/api/public"
    conn = ConnectionConfig(
        platform="smartzone",
        api_base=sz_base,
        display_name="SZ",
        auth_token="t",
        api_version="v11_0",
        verify_tls=False,
        token_expires_at=9999999999,
    )
    out = fetch_switches(conn, CFG)
    assert len(out["switches"]) == 1
    assert out["switches"][0]["name"] == "SW-1"
