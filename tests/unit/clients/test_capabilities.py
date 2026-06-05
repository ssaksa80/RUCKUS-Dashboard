"""Tests for clients/capabilities.py (Task 16).

The OpenAPI probe URLs match the monolith's ``_smartzone_openapi_urls``
(line 1760-1764) and the inline Switch Manager URL list in
``_discover_smartzone_capabilities`` (line 1595).

For an api_base of ``https://sz.example:8443/wsg/api/public`` (path starts
with ``/wsg/``), the monolith probes a single SmartZone URL:

* ``https://sz.example:8443/wsg/apiDoc/openapi``

Plus the Switch Manager URL:

* ``https://sz.example:8443/switchm/api/openapi``

The task spec's example URLs (``/wsg/api/public-openapi.json`` and
``/switchm/api/public-openapi.json``) were guesses -- the real paths are
``/wsg/apiDoc/openapi`` and ``/switchm/api/openapi``.
"""

from __future__ import annotations

import responses

from ruckus_dashboard.auth.session_store import ConnectionConfig
from ruckus_dashboard.clients.capabilities import discover_capabilities


CFG = {
    "RUCKUS_TIMEOUT_SECONDS": 5,
    "RUCKUS_DEBUG_BYTES": 1000,
    "RUCKUS_PAGE_LIMIT": 500,
    "RUCKUS_HOST_ALLOWLIST": None,
    "RUCKUS_CAPABILITY_DISCOVERY": True,
}


def _conn() -> ConnectionConfig:
    return ConnectionConfig(
        platform="smartzone",
        api_base="https://sz.example:8443/wsg/api/public",
        display_name="SZ",
        auth_token="t",
        api_version="v11_0",
        verify_tls=False,
        token_expires_at=9999999999,
    )


@responses.activate
def test_discover_returns_op_set_on_openapi():
    # SmartZone OpenAPI doc (monolith probes /wsg/apiDoc/openapi when the
    # api_base path starts with /wsg/).
    responses.add(
        responses.GET,
        "https://sz.example:8443/wsg/apiDoc/openapi",
        json={
            "paths": {
                "/v11_0/aps": {"get": {}},
                "/v11_0/rkszones": {"get": {}},
                "/v11_0/query/ap": {"post": {}},
            }
        },
        status=200,
    )
    # Switch Manager OpenAPI returns 404 -- accepted (source becomes unavailable
    # but discover_capabilities still returns the SmartZone ops).
    responses.add(
        responses.GET,
        "https://sz.example:8443/switchm/api/openapi",
        status=404,
    )

    result = discover_capabilities(_conn(), CFG)

    assert "available_ops" in result
    assert ("GET", "/aps") in result["available_ops"]
    assert ("GET", "/rkszones") in result["available_ops"]
    assert ("POST", "/query/ap") in result["available_ops"]
    assert result["status"] in {"available", "partial"}
    # Two probed sources (wireless + switchm); one available, one 404.
    assert result["summary"]["source_count"] == 2
    assert result["summary"]["available_sources"] == 1


@responses.activate
def test_discover_disabled_returns_empty():
    cfg = {**CFG, "RUCKUS_CAPABILITY_DISCOVERY": False}
    result = discover_capabilities(_conn(), cfg)
    assert result["status"] == "disabled"
    assert result["sources"] == []
    assert result["available_ops"] == set()


def test_discover_non_smartzone_unsupported():
    conn = ConnectionConfig(
        platform="ruckus_one",
        api_base="https://api.ruckus.cloud",
        display_name="R1",
        auth_token="t",
        api_version="",
        verify_tls=True,
        token_expires_at=9999999999,
    )
    result = discover_capabilities(conn, CFG)
    assert result["status"] == "unsupported"
    assert result["available_ops"] == set()
