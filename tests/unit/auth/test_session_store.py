import time
from ruckus_dashboard.auth.session_store import ConnectionConfig, ConnectionStore

def make_cfg(name="SZ1"):
    return ConnectionConfig(
        platform="smartzone", api_base="https://sz/wsg/api/public",
        display_name=name, auth_token="ticket",
    )

def test_put_get_round_trip():
    store = ConnectionStore(ttl_seconds=60)
    token = store.put(make_cfg())
    assert store.get(token).display_name == "SZ1"

def test_ttl_eviction():
    store = ConnectionStore(ttl_seconds=0)
    token = store.put(make_cfg())
    time.sleep(0.01)
    assert store.get(token) is None

def test_remove():
    store = ConnectionStore(ttl_seconds=60)
    token = store.put(make_cfg())
    store.remove(token)
    assert store.get(token) is None

def test_count():
    store = ConnectionStore(ttl_seconds=60)
    store.put(make_cfg("A"))
    store.put(make_cfg("B"))
    assert store.count() == 2

def test_on_evict_called_with_evicted_token():
    evicted = []
    store = ConnectionStore(ttl_seconds=0, on_evict=evicted.append)
    token = store.put(make_cfg())
    time.sleep(0.01)
    # A subsequent access triggers cleanup; the evicted token must be reported.
    assert store.get(token) is None
    assert evicted == [token]

def test_on_evict_not_called_for_live_token():
    evicted = []
    store = ConnectionStore(ttl_seconds=60, on_evict=evicted.append)
    token = store.put(make_cfg())
    assert store.get(token) is not None
    assert evicted == []
