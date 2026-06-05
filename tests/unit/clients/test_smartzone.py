import responses
from ruckus_dashboard.auth.session_store import ConnectionConfig
from ruckus_dashboard.clients.smartzone import (
    authenticate_smartzone,
    fetch_inventory,
    normalize_smartzone_base,
)

CFG = {
    "RUCKUS_SMARTZONE_PORT": 8443,
    "RUCKUS_TIMEOUT_SECONDS": 5,
    "RUCKUS_DEBUG_BYTES": 1000,
    "RUCKUS_VERIFY_TLS": False,
    "RUCKUS_PAGE_LIMIT": 500,
    "RUCKUS_FETCH_AP_DETAILS": False,
    "RUCKUS_MAX_DETAIL_REQUESTS": 50,
    "RUCKUS_HOST_ALLOWLIST": None,
}


def test_normalize_smartzone_base_adds_default_path():
    assert (
        normalize_smartzone_base("sz.example")
        == "https://sz.example:8443/wsg/api/public"
    )


def test_normalize_rejects_http():
    import pytest

    with pytest.raises(ValueError):
        normalize_smartzone_base("http://sz.example")


@responses.activate
def test_authenticate_smartzone_happy():
    base = "https://sz.example:8443/wsg/api/public"
    responses.add(
        responses.GET,
        f"{base}/apiInfo",
        json={"apiSupportVersions": ["v9_0", "v10_0", "v11_0"]},
        status=200,
    )
    responses.add(
        responses.POST,
        f"{base}/v11_0/serviceTicket",
        json={"serviceTicket": "ticket-abc", "controllerVersion": "6.1.2"},
        status=200,
    )
    form = {
        "smartzone_host": "sz.example",
        "smartzone_username": "u",
        "smartzone_password": "p",
        "smartzone_api_version": "auto",
        "smartzone_skip_tls_verify": "1",
    }
    conn = authenticate_smartzone(form, CFG)
    assert conn.platform == "smartzone"
    assert conn.api_version == "v11_0"
    assert conn.auth_token == "ticket-abc"
    assert conn.controller_version == "6.1.2"


@responses.activate
def test_fetch_inventory_uses_query_ap():
    base = "https://sz.example:8443/wsg/api/public"
    responses.add(
        responses.GET,
        f"{base}/v11_0/rkszones",
        json={"list": []},
        status=200,
    )
    responses.add(
        responses.POST,
        f"{base}/v11_0/query/ap",
        json={
            "list": [
                {
                    "apMac": "AA:BB:CC:DD:EE:01",
                    "deviceName": "AP-1",
                    "model": "R650",
                    "firmwareVersion": "7.0.0",
                    "zoneId": "z1",
                }
            ],
            "totalCount": 1,
            "hasMore": False,
        },
        status=200,
    )
    conn = ConnectionConfig(
        platform="smartzone",
        api_base=base,
        display_name="SZ",
        auth_token="t",
        api_version="v11_0",
        verify_tls=False,
        token_expires_at=9999999999,
    )
    out = fetch_inventory(conn, CFG)
    assert len(out["assets"]) == 1
    assert out["assets"][0]["model"] == "R650"
