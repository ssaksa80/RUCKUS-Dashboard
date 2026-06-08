import responses
from ruckus_dashboard.auth.session_store import ConnectionConfig
from ruckus_dashboard.modules._base import FetcherContext
from ruckus_dashboard.modules import switches as switches_mod
from ruckus_dashboard.infra.capability_gate import CapabilityGate

CFG = {"RUCKUS_TIMEOUT_SECONDS": 5, "RUCKUS_DEBUG_BYTES": 1000,
       "RUCKUS_PAGE_LIMIT": 500, "RUCKUS_HOST_ALLOWLIST": None,
       "RUCKUS_MAX_SWITCH_RECORDS": 2000}
SW_BASE = "https://sz.example:8443/switchm/api/public"


def _ctx():
    conn = ConnectionConfig(platform="smartzone",
        api_base="https://sz.example:8443/wsg/api/public",
        display_name="SZ", auth_token="t", api_version="v11_0",
        verify_tls=False, token_expires_at=9999999999)
    return FetcherContext(connection=conn, config=CFG, filters=None,
        capability_gate=CapabilityGate(set()), connection_label="SZ")


def _add_switch_list():
    # fetch_switches tries path "switch" first, then "switch/view/details".
    # Make "switch" 400 so it falls through to the detail endpoint.
    responses.add(responses.POST, f"{SW_BASE}/v11_0/switch",
                  json={"error": "bad"}, status=400, match_querystring=False)
    responses.add(responses.POST, f"{SW_BASE}/v11_0/switch/view/details",
                  json={"list": [
                      {"id": "s1", "name": "Switch-One", "model": "ICX7150",
                       "status": "online", "ip": "10.0.0.1"},
                      {"id": "s2", "name": "Switch-Two", "model": "ICX7250",
                       "status": "offline", "ip": "10.0.0.2"},
                  ], "totalCount": 2, "hasMore": False},
                  status=200, match_querystring=False)


def _add_ports(status=200):
    responses.add(responses.POST, f"{SW_BASE}/v11_0/switch/ports/summary",
                  json={"list": [
                      {"switchId": "s1", "portId": "1/1/1", "status": "up",
                       "vlan": 10, "poeClass": "Class 0"},
                      {"switchId": "s1", "portId": "1/1/2", "status": "down",
                       "vlan": 1, "poeClass": ""},
                      {"switchId": "s2", "portId": "1/1/1", "status": "up",
                       "vlan": 20, "poeClass": "Class 4"},
                  ]} if status == 200 else {"error": "bad"},
                  status=status, match_querystring=False)


def _add_health():
    responses.add(responses.POST, f"{SW_BASE}/v11_0/health/cpu/agg",
                  json={"avg": 12.5}, status=200, match_querystring=False)
    responses.add(responses.POST, f"{SW_BASE}/v11_0/health/mem/agg",
                  json={"avg": 40.0}, status=200, match_querystring=False)


@responses.activate
def test_fetch_drill_returns_identity_ports_health():
    _add_switch_list()
    _add_ports(200)
    _add_health()
    out = switches_mod.fetch_drill(_ctx(), "s1")
    assert out["identity"]["id"] == "s1"
    assert out["identity"].get("name") == "Switch-One"
    # ports filtered to s1 only
    assert len(out["ports"]) == 2
    assert all(p["switch_id"] == "s1" or p.get("port_id") for p in out["ports"])
    assert {p["port_id"] for p in out["ports"]} == {"1/1/1", "1/1/2"}
    assert out["health"]  # present
    assert "cpu" in out["health"] or "mem" in out["health"]


@responses.activate
def test_fetch_drill_ports_400_yields_empty_no_raise():
    _add_switch_list()
    _add_ports(400)
    _add_health()
    out = switches_mod.fetch_drill(_ctx(), "s1")
    assert out["identity"]["id"] == "s1"
    assert out["ports"] == []


@responses.activate
def test_fetch_drill_never_raises_on_total_failure():
    # nothing mocked → every sub-call errors, must still return shape
    out = switches_mod.fetch_drill(_ctx(), "sX")
    assert out["identity"]["id"] == "sX"
    assert out["ports"] == []
    assert out["health"] == {} or isinstance(out["health"], dict)


def test_switches_drill_tabs_registered():
    from ruckus_dashboard.modules import MODULES
    slugs = {t.slug for t in MODULES["switches"].drill_tabs}
    assert {"summary", "ports", "health", "raw"} <= slugs
