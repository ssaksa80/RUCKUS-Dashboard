import pytest
import responses

from ruckus_dashboard.clients.base import request_json, RuckusClientError


@responses.activate
def test_request_json_happy():
    responses.add(responses.GET, "https://x/y", json={"a": 1}, status=200)
    cfg = {
        "RUCKUS_TIMEOUT_SECONDS": 5,
        "RUCKUS_DEBUG_BYTES": 1000,
        "RUCKUS_HOST_ALLOWLIST": None,
    }
    out = request_json("GET", "https://x/y", cfg, verify=True, debug_label="t")
    assert out == {"a": 1}


@responses.activate
def test_request_json_4xx_raises():
    responses.add(responses.GET, "https://x/y", json={"err": "nope"}, status=404)
    cfg = {
        "RUCKUS_TIMEOUT_SECONDS": 5,
        "RUCKUS_DEBUG_BYTES": 1000,
        "RUCKUS_HOST_ALLOWLIST": None,
    }
    with pytest.raises(RuckusClientError) as exc:
        request_json("GET", "https://x/y", cfg, verify=True, debug_label="t")
    assert exc.value.status_code == 404


@responses.activate
def test_redact_password_in_error_debug():
    responses.add(responses.POST, "https://x/login", status=500)
    cfg = {
        "RUCKUS_TIMEOUT_SECONDS": 5,
        "RUCKUS_DEBUG_BYTES": 1000,
        "RUCKUS_HOST_ALLOWLIST": None,
    }
    with pytest.raises(RuckusClientError) as exc:
        request_json(
            "POST",
            "https://x/login",
            cfg,
            json={"username": "u", "password": "hunter2"},
            verify=True,
            debug_label="t",
        )
    debug_str = str(exc.value.debug or {})
    assert "hunter2" not in debug_str


@responses.activate
def test_request_json_does_not_follow_redirects():
    # A controller (or MITM) returning a 3xx to an internal host must NOT be followed.
    responses.add(
        responses.GET, "https://ctrl.example/wsg/api/public/apiInfo",
        status=302, headers={"Location": "http://169.254.169.254/latest/meta-data"},
    )
    cfg = {"RUCKUS_TIMEOUT_SECONDS": 5, "RUCKUS_DEBUG_BYTES": 1000, "RUCKUS_HOST_ALLOWLIST": None}
    with pytest.raises(RuckusClientError) as ei:
        request_json("GET", "https://ctrl.example/wsg/api/public/apiInfo", cfg, debug_label="probe")
    assert ei.value.status_code == 302          # surfaced as an error, not followed
    assert len(responses.calls) == 1            # the redirect target was never contacted
