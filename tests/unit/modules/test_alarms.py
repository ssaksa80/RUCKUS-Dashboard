import json, pathlib
import responses
from ruckus_dashboard.auth.session_store import ConnectionConfig
from ruckus_dashboard.modules._base import FetcherContext
from ruckus_dashboard.modules import alarms as alarms_mod
from ruckus_dashboard.infra.capability_gate import CapabilityGate

SUMMARY_FIX = json.loads(pathlib.Path("tests/fixtures/smartzone/alarm_summary.json").read_text())
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
def test_alarms_fetch_combines_summary_and_list():
    base = "https://sz.example:8443/wsg/api/public"
    responses.add(responses.POST, f"{base}/v11_0/alert/alarmSummary",
                  json=SUMMARY_FIX, status=200)
    responses.add(responses.POST, f"{base}/v11_0/alert/alarm/list",
                  json=LIST_FIX, status=200)
    out = alarms_mod.fetch(_ctx())
    assert len(out["items"]) == 2
    assert out["summary_raw"]["critical"] == 2
    first = out["items"][0]
    assert first["severity"] == "critical"
    assert first["source"] == "AP-Lobby"


def test_alarms_summary_reads_summary_raw_when_present():
    data = {"items": [{"severity": "critical"}],
            "summary_raw": {"critical": 2, "major": 5, "minor": 8,
                            "warning": 12, "total": 27}}
    s = alarms_mod.summary(data)
    assert s["critical"] == 2
    assert s["total"] == 27


def test_alarms_summary_falls_back_to_items_when_no_summary_raw():
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
