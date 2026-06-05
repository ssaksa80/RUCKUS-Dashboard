from ruckus_dashboard.infra.capability_gate import CapabilityGate


def test_no_required_caps_always_satisfied():
    gate = CapabilityGate(available=set())
    assert gate.satisfied(())


def test_satisfied_when_all_present():
    gate = CapabilityGate(available={("GET", "/aps"), ("POST", "/query/ap")})
    assert gate.satisfied((("GET", "/aps"), ("POST", "/query/ap")))


def test_unsatisfied_when_missing():
    gate = CapabilityGate(available={("GET", "/aps")})
    assert not gate.satisfied((("GET", "/aps"), ("POST", "/missing")))


def test_missing_reports_unmet():
    gate = CapabilityGate(available={("GET", "/aps")})
    missing = gate.missing((("GET", "/aps"), ("POST", "/x")))
    assert missing == [("POST", "/x")]
