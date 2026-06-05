import time
from ruckus_dashboard.infra.cache import ModuleResultCache

def test_put_then_get_returns_value():
    c = ModuleResultCache()
    c.put(("conn-a",), "aps", {"zone": "z1"}, ttl=10, value={"data": 1})
    assert c.get(("conn-a",), "aps", {"zone": "z1"}) == {"data": 1}

def test_miss_returns_none():
    c = ModuleResultCache()
    assert c.get(("conn-a",), "aps", {}) is None

def test_ttl_expires():
    c = ModuleResultCache()
    c.put(("c",), "x", {}, ttl=0, value={"a": 1})
    time.sleep(0.01)
    assert c.get(("c",), "x", {}) is None

def test_different_filters_dont_collide():
    c = ModuleResultCache()
    c.put(("c",), "aps", {"zone": "a"}, ttl=10, value={"v": "a"})
    c.put(("c",), "aps", {"zone": "b"}, ttl=10, value={"v": "b"})
    assert c.get(("c",), "aps", {"zone": "a"}) == {"v": "a"}
    assert c.get(("c",), "aps", {"zone": "b"}) == {"v": "b"}

def test_invalidate_connection():
    c = ModuleResultCache()
    c.put(("c",), "aps", {}, ttl=60, value={"v": 1})
    c.invalidate_connection_set(("c",))
    assert c.get(("c",), "aps", {}) is None
