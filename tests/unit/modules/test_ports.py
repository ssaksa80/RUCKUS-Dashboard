import json, pathlib
import responses
from ruckus_dashboard.auth.session_store import ConnectionConfig
from ruckus_dashboard.modules._base import FetcherContext
from ruckus_dashboard.modules import ports as ports_mod
from ruckus_dashboard.infra.capability_gate import CapabilityGate

FIXTURE = json.loads(pathlib.Path("tests/fixtures/switchm/ports_summary.json").read_text())
CFG = {"RUCKUS_TIMEOUT_SECONDS": 5, "RUCKUS_DEBUG_BYTES": 1000,
       "RUCKUS_PAGE_LIMIT": 500, "RUCKUS_HOST_ALLOWLIST": None}

def _ctx():
    conn = ConnectionConfig(platform="smartzone",
        api_base="https://sz.example:8443/wsg/api/public",
        display_name="SZ", auth_token="t", api_version="v11_0",
        verify_tls=False, token_expires_at=9999999999)
    return FetcherContext(connection=conn, config=CFG, filters=None,
        capability_gate=CapabilityGate(set()), connection_label="SZ")


@responses.activate
def test_ports_fetch_returns_normalised_rows():
    sw_base = "https://sz.example:8443/switchm/api"
    responses.add(responses.POST, f"{sw_base}/v11_0/switch/ports/summary",
                  json=FIXTURE, status=200, match_querystring=False)
    out = ports_mod.fetch(_ctx())
    assert len(out["items"]) == 3
    assert out["items"][0]["status"] == "up"
    assert out["items"][2]["poe_on"] is True
    assert out["items"][2]["errors"] == 5


def test_ports_summary_counts_status_and_errors():
    data = {"items": [
        {"status": "up", "poe_on": False, "errors": 0},
        {"status": "down", "poe_on": False, "errors": 0},
        {"status": "up", "poe_on": True, "errors": 5},
    ]}
    s = ports_mod.summary(data)
    assert s["total"] == 3
    assert s["up"] == 2
    assert s["down"] == 1
    assert s["poe_on"] == 1
    assert s["errors_total"] == 5
    assert s["errors_ports"] == 1


def test_ports_registered():
    from ruckus_dashboard.modules import MODULES
    assert MODULES["ports"].fetcher is ports_mod.fetch
