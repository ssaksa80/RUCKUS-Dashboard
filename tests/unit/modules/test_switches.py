import json, pathlib
import responses
from ruckus_dashboard.auth.session_store import ConnectionConfig
from ruckus_dashboard.modules._base import FetcherContext
from ruckus_dashboard.modules import switches as switches_mod
from ruckus_dashboard.infra.capability_gate import CapabilityGate

FIXTURE = json.loads(pathlib.Path("tests/fixtures/switchm/switch_view_details.json").read_text())
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
def test_switches_fetch_returns_normalised_rows():
    sw_base = "https://sz.example:8443/switchm/api/public"
    responses.add(responses.POST, f"{sw_base}/v11_0/switch/view/details",
                  json=FIXTURE, status=200)
    out = switches_mod.fetch(_ctx())
    assert len(out["items"]) == 2
    assert out["items"][0]["name"] == "SW-1"
    assert out["items"][0]["status"] == "online"


def test_switches_summary_aggregates_status_and_ports():
    data = {"items": [
        {"status": "online", "ports_online": 22, "ports_total": 24},
        {"status": "offline", "ports_online": 0, "ports_total": 48},
    ]}
    s = switches_mod.summary(data)
    assert s["total"] == 2
    assert s["online"] == 1
    assert s["offline"] == 1
    assert s["ports_up"] == 22
    assert s["ports_total"] == 72


def test_switches_registered():
    from ruckus_dashboard.modules import MODULES
    assert MODULES["switches"].fetcher is switches_mod.fetch
