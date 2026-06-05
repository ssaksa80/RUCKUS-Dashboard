from ruckus_dashboard.infra.envelope import build_envelope, ControllerError


def test_complete_envelope_no_errors():
    env = build_envelope(data={"x": 1}, summary={"count": 1}, errors=[])
    assert env["status"] == "complete"
    assert env["data"] == {"x": 1}
    assert env["controller_errors"] == []
    assert env["stale_since"] is None
    assert env["generated_at"]


def test_partial_envelope_with_one_error():
    env = build_envelope(
        data={"x": 1},
        summary={"count": 1},
        errors=[ControllerError("SZ-A", "POST /query/ap", "timeout", 504)],
    )
    assert env["status"] == "partial"
    assert env["controller_errors"][0]["connection"] == "SZ-A"
    assert env["controller_errors"][0]["status"] == 504


def test_error_envelope_no_data():
    env = build_envelope(
        data=None,
        summary={},
        errors=[ControllerError("SZ-A", "GET /apiInfo", "down", 502)],
    )
    assert env["status"] == "error"
