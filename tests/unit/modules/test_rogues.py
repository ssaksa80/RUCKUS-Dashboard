import json
import pathlib
import responses
from ruckus_dashboard.auth.session_store import ConnectionConfig
from ruckus_dashboard.modules._base import FetcherContext
from ruckus_dashboard.modules import rogues as rogues_mod
from ruckus_dashboard.infra.capability_gate import CapabilityGate

FIXTURE = json.loads(pathlib.Path("tests/fixtures/smartzone/query_rogues.json").read_text())
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
def test_rogues_fetch_normalises_rows():
    base = "https://sz.example:8443/wsg/api/public"
    responses.add(responses.POST, f"{base}/v11_0/query/roguesInfoList",
                  json=FIXTURE, status=200)
    out = rogues_mod.fetch(_ctx())
    assert len(out["items"]) == 3
    assert out["items"][0]["bssid"] == "DE:AD:BE:EF:00:01"
    assert out["items"][0]["classification"] == "malicious"
    assert out["items"][0]["channel"] == 6


def test_rogues_summary_counts_by_classification():
    data = {"items": [
        {"classification": "malicious"},
        {"classification": "rogue"},
        {"classification": "known"},
        {"classification": "malicious"},
    ]}
    s = rogues_mod.summary(data)
    assert s["total"] == 4
    assert s["malicious"] == 2
    assert s["rogue"] == 1
    assert s["known"] == 1


def test_rogues_registered():
    from ruckus_dashboard.modules import MODULES
    assert MODULES["rogues"].fetcher is rogues_mod.fetch
