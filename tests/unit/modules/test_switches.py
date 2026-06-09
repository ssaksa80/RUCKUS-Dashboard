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
    sw_base = "https://sz.example:8443/switchm/api"
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


def test_switches_normalize_real_smartzone_711_row():
    """Field mapping against the real /switch row shape (SmartZone 7.1.1)."""
    from ruckus_dashboard.modules.switches import _normalize
    row = {
        "id": "40:B8:2D:02:EB:58", "macAddress": "40:B8:2D:02:EB:58",
        "switchName": "AHDSP-SERVER-FARM", "model": "ICX7550-24",
        "ipAddress": "172.26.200.243", "status": "ONLINE",
        "firmwareVersion": "GZR10010g_cd5", "upTime": "186 days, 21:07:29.00",
        "stackId": None, "numOfUnits": 2, "groupName": "AHD-SP-SW",
        "serialNumber": "FMK4417W00H",
        "portStatus": {"up": 24, "down": 25, "total": 52}, "ports": 52,
    }
    n = _normalize(row)
    assert n["name"] == "AHDSP-SERVER-FARM"
    assert n["ip"] == "172.26.200.243"
    assert n["status"] == "online"
    assert n["fw"] == "GZR10010g_cd5"
    assert n["ports_online"] == 24
    assert n["ports_total"] == 52
    assert n["stack"] == "AHD-SP-SW"  # falls back to group when stackId null
    assert n["serial"] == "FMK4417W00H"


def test_stack_groups_multi_unit_switch_as_stack():
    """A switch row with numOfUnits>1 (stackId null) is one stack (7.1.1 shape)."""
    from ruckus_dashboard.modules.stack import _group_by_stack
    rows = [
        {"id": "AA", "switchName": "S1", "numOfUnits": 2, "modules": "stack",
         "firmwareVersion": "GZR10010g", "groupName": "G1",
         "portStatus": {"up": 24, "total": 52}},
        {"id": "BB", "switchName": "S2", "numOfUnits": 1, "modules": "",
         "portStatus": {"up": 10, "total": 24}},
    ]
    out = _group_by_stack(rows)
    assert len(out) == 1
    assert out[0]["stack_id"] == "AA"
    assert out[0]["members"] == 2
    assert out[0]["ports_up"] == 24
