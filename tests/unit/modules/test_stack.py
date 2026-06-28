import json
import pathlib
import responses
from ruckus_dashboard.auth.session_store import ConnectionConfig
from ruckus_dashboard.modules._base import FetcherContext
from ruckus_dashboard.modules import stack as stack_mod
from ruckus_dashboard.infra.capability_gate import CapabilityGate

FIXTURE = json.loads(pathlib.Path("tests/fixtures/switchm/stack_list.json").read_text())
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
def test_stack_fetch_groups_switches_by_stack_id():
    sw_base = "https://sz.example:8443/switchm/api"
    responses.add(responses.POST, f"{sw_base}/v11_0/switch/view/details",
                  json=FIXTURE, status=200, match_querystring=False)
    out = stack_mod.fetch(_ctx())
    assert len(out["items"]) == 2  # stack-a (2 switches) + stack-b (1 switch)
    stacks = {s["id"]: s for s in out["items"]}
    assert stacks["stack-a"]["members"] == 2
    assert stacks["stack-b"]["members"] == 1


def test_stack_summary():
    data = {"items": [
        {"members": 4, "fw_aligned": True},
        {"members": 2, "fw_aligned": False},
    ]}
    s = stack_mod.summary(data)
    assert s["total_stacks"] == 2
    assert s["total_members"] == 6
    assert s["misaligned_fw"] == 1


def test_stack_registered():
    from ruckus_dashboard.modules import MODULES
    assert MODULES["stack"].fetcher is stack_mod.fetch
