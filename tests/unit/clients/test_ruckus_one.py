import responses
from ruckus_dashboard.clients.ruckus_one import (
    authenticate_ruckus_one,
    normalize_ruckus_one_base,
)

CFG = {
    "RUCKUS_TIMEOUT_SECONDS": 5,
    "RUCKUS_DEBUG_BYTES": 1000,
    "RUCKUS_HOST_ALLOWLIST": None,
}


def test_normalize_region_na():
    assert normalize_ruckus_one_base("na") == "https://api.ruckus.cloud"


def test_normalize_region_eu():
    assert normalize_ruckus_one_base("eu") == "https://api.eu.ruckus.cloud"


def test_normalize_rejects_http():
    import pytest

    with pytest.raises(ValueError):
        normalize_ruckus_one_base("http://api.ruckus.cloud")


@responses.activate
def test_authenticate_ruckus_one_happy():
    # Auth base strips the `api.` subdomain — OAuth lives at bare ruckus.cloud,
    # API endpoints live at api.ruckus.cloud. Matches monolith _ruckus_one_auth_base.
    responses.add(
        responses.POST,
        "https://ruckus.cloud/oauth2/token/tenant-1",
        json={"access_token": "tok", "expires_in": 3600},
        status=200,
    )
    form = {
        "tenant_id": "tenant-1",
        "client_id": "cid",
        "client_secret": "csec",
        "ruckus_one_region": "na",
    }
    conn = authenticate_ruckus_one(form, CFG)
    assert conn.platform == "ruckus_one"
    assert conn.auth_token == "tok"
    assert conn.tenant_id == "tenant-1"
