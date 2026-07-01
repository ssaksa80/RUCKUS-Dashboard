import json
import pathlib
import responses
from ruckus_dashboard.auth.session_store import ConnectionConfig
from ruckus_dashboard.modules._base import FetcherContext
from ruckus_dashboard.modules import aps as aps_mod
from ruckus_dashboard.infra.capability_gate import CapabilityGate

FIXTURE = json.loads(pathlib.Path("tests/fixtures/smartzone/query_ap.json").read_text())

CFG = {"RUCKUS_TIMEOUT_SECONDS": 5, "RUCKUS_DEBUG_BYTES": 1000,
       "RUCKUS_PAGE_LIMIT": 500, "RUCKUS_HOST_ALLOWLIST": None}


def _ctx(conn=None, filters=None):
    if conn is None:
        conn = ConnectionConfig(platform="smartzone",
                                api_base="https://sz.example:8443/wsg/api/public",
                                display_name="SZ", auth_token="t",
                                api_version="v11_0", verify_tls=False,
                                token_expires_at=9999999999)
    return FetcherContext(connection=conn, config=CFG, filters=filters,
                          capability_gate=CapabilityGate(set()),
                          connection_label="SZ")


@responses.activate
def test_aps_fetch_returns_normalised_rows():
    base = "https://sz.example:8443/wsg/api/public"
    responses.add(responses.POST, f"{base}/v11_0/query/ap",
                  json=FIXTURE, status=200)
    out = aps_mod.fetch(_ctx())
    assert len(out["items"]) == 3
    first = out["items"][0]
    assert first["name"] == "AP-Lobby"
    assert first["mac"] == "AA:BB:CC:DD:EE:01"
    assert first["status"] == "online"
    assert first["clients"] == 12
    assert first["model"] == "R650"


def test_aps_summary_counts_by_status():
    data = {"items": [
        {"status": "online", "clients": 12},
        {"status": "online", "clients": 5},
        {"status": "offline", "clients": 0},
        {"status": "flagged", "clients": 3},
    ]}
    s = aps_mod.summary(data)
    assert s["total"] == 4
    assert s["online"] == 2
    assert s["offline"] == 1
    assert s["flagged"] == 1
    assert s["clients"] == 20


def test_aps_merge_concats_across_controllers():
    a = {"items": [{"mac": "AA"}], "raw_count": 1}
    b = {"items": [{"mac": "BB"}], "raw_count": 1}
    out = aps_mod.merge([a, b])
    assert len(out["items"]) == 2
    assert out["raw_count"] == 2


def test_aps_registered_in_modules_registry():
    from ruckus_dashboard.modules import MODULES
    assert MODULES["aps"].slug == "aps"
    assert MODULES["aps"].fetcher is aps_mod.fetch


@responses.activate
def test_aps_paginates_beyond_500():
    """800 APs are fetched across two pages, not capped at 500."""
    base = "https://sz.example:8443/wsg/api/public"
    page1 = {"list": [{"apMac": f"AA:{i:02X}", "deviceName": f"AP{i}",
                       "model": "R650", "status": "Online"} for i in range(500)],
             "totalCount": 800, "hasMore": True}
    page2 = {"list": [{"apMac": f"BB:{i:02X}", "deviceName": f"AP{500+i}",
                       "model": "R650", "status": "Online"} for i in range(300)],
             "totalCount": 800, "hasMore": False}
    responses.add(responses.POST, f"{base}/v11_0/query/ap", json=page1, status=200)
    responses.add(responses.POST, f"{base}/v11_0/query/ap", json=page2, status=200)
    out = aps_mod.fetch(_ctx())
    assert len(out["items"]) == 800


def test_aps_filter_body_from_server_token():
    from ruckus_dashboard.modules.aps import _filter_body
    body = _filter_body({"__server": {"ZONE_ID": "z1"}})
    assert body["filters"] == [{"type": "ZONE_ID", "value": "z1"}]


def test_aps_filter_body_legacy_zone():
    from ruckus_dashboard.modules.aps import _filter_body
    body = _filter_body({"zone": "z2"})
    assert body["filters"] == [{"type": "ZONE_ID", "value": "z2"}]


def test_aps_filter_body_empty_when_no_zone():
    from ruckus_dashboard.modules.aps import _filter_body
    assert _filter_body({}) == {}
    assert _filter_body(None) == {}


def test_aps_zone_column_advertises_server_filter():
    from ruckus_dashboard.modules import MODULES
    by_key = {f.key: f for f in MODULES["aps"].resolved_filters}
    assert by_key["zone"].server_filter == "ZONE_ID"
    assert by_key["zone"].kind == "select"
    # status still derives as a select from the status-kind column
    assert by_key["status"].kind == "select"
