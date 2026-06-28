import json
import pathlib
import responses
from ruckus_dashboard.auth.session_store import ConnectionConfig
from ruckus_dashboard.modules._base import FetcherContext
from ruckus_dashboard.modules import alarms as alarms_mod
from ruckus_dashboard.infra.capability_gate import CapabilityGate

LIST_FIX = json.loads(pathlib.Path("tests/fixtures/smartzone/query_alarm.json").read_text())

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
def test_alarms_fetch_returns_list_items():
    base = "https://sz.example:8443/wsg/api/public"
    responses.add(responses.POST, f"{base}/v11_0/alert/alarm/list",
                  json=LIST_FIX, status=200)
    out = alarms_mod.fetch(_ctx())
    assert len(out["items"]) == 2
    first = out["items"][0]
    assert first["severity"] == "critical"
    assert first["source"] == "AP-Lobby"


def test_alarms_summary_derives_from_items():
    data = {"items": [
        {"severity": "critical", "count": 2},
        {"severity": "major", "count": 1},
        {"severity": "major", "count": 1},
        {"severity": "warning", "count": 3},
    ]}
    s = alarms_mod.summary(data)
    assert s["critical"] == 2
    assert s["major"] == 2
    assert s["warning"] == 3
    assert s["total"] == 7


def test_alarms_summary_defaults_count_to_one():
    data = {"items": [
        {"severity": "critical"},
        {"severity": "critical"},
        {"severity": "warning"},
    ]}
    s = alarms_mod.summary(data)
    assert s["critical"] == 2
    assert s["warning"] == 1
    assert s["total"] == 3


def test_alarms_registered():
    from ruckus_dashboard.modules import MODULES
    assert MODULES["alarms"].fetcher is alarms_mod.fetch
