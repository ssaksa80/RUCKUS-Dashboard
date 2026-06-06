from ruckus_dashboard.modules import overview as overview_mod
from ruckus_dashboard.modules._base import FetcherContext
from ruckus_dashboard.infra.capability_gate import CapabilityGate


def test_overview_fetch_returns_empty_marker():
    ctx = FetcherContext(connection=None, config={}, filters=None,
                         capability_gate=CapabilityGate(set()),
                         connection_label="")
    out = overview_mod.fetch(ctx)
    assert out["items"] == []
    assert out["_overview"] is True


def test_overview_summary_is_empty_dict():
    assert overview_mod.summary({}) == {}


def test_overview_registered_no_caps():
    from ruckus_dashboard.modules import MODULES
    assert MODULES["overview"].requires_capabilities == ()
    assert MODULES["overview"].fetcher is overview_mod.fetch
