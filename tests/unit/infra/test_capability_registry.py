from ruckus_dashboard.infra.capability_registry import CapabilityRegistry


def test_ops_isolated_per_connection():
    reg = CapabilityRegistry()
    reg.set_for("connA", {("GET", "/x")})
    reg.set_for("connB", {("POST", "/y")})
    assert reg.get_for(["connA"]) == {("GET", "/x")}
    assert reg.get_for(["connB"]) == {("POST", "/y")}
    assert reg.get_for(["connA", "connB"]) == {("GET", "/x"), ("POST", "/y")}


def test_clear_one_connection_does_not_affect_other():
    reg = CapabilityRegistry()
    reg.set_for("connA", {("GET", "/x")})
    reg.set_for("connB", {("POST", "/y")})
    reg.clear("connB")
    assert reg.get_for(["connA"]) == {("GET", "/x")}
    assert reg.get_for(["connB"]) == set()


def test_unknown_connection_returns_empty():
    assert CapabilityRegistry().get_for(["nope"]) == set()
