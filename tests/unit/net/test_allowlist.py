import pytest

from ruckus_dashboard.clients.base import RuckusClientError
from ruckus_dashboard.net import allowlist as allowlist_mod
from ruckus_dashboard.net.allowlist import HostAllowList, assert_host_allowed


@pytest.fixture
def fake_dns(monkeypatch):
    """Make hostname resolution hermetic for the allow-list tests."""
    mapping = {
        "sz.example.com": {"10.0.0.5"},
        "evil.example.com": {"203.0.113.9"},
    }

    def fake_getaddrinfo(host, *_args, **_kwargs):
        host = (host or "").lower()
        if host in mapping:
            # socket.getaddrinfo returns 5-tuples; only sockaddr[0] is used.
            return [(0, 0, 0, "", (ip, 0)) for ip in mapping[host]]
        raise OSError("unknown host")

    monkeypatch.setattr(allowlist_mod.socket, "getaddrinfo", fake_getaddrinfo)
    return mapping


def test_empty_list_allows_everything():
    al = HostAllowList("")
    assert not al.enabled
    assert_host_allowed("anything.example.com", {"RUCKUS_HOST_ALLOWLIST": al})


def test_exact_hostname_match(fake_dns):
    al = HostAllowList("sz.example.com, 10.0.0.5")
    assert al.enabled
    assert_host_allowed("sz.example.com", {"RUCKUS_HOST_ALLOWLIST": al})
    # 10.0.0.5 is a literal IP entry, but the verbatim policy requires literal
    # IPs to also fall inside one of the configured networks. Add a /32 net.
    al2 = HostAllowList("10.0.0.5/32")
    assert_host_allowed("10.0.0.5", {"RUCKUS_HOST_ALLOWLIST": al2})


def test_cidr_match():
    al = HostAllowList("10.0.0.0/24")
    assert_host_allowed("10.0.0.55", {"RUCKUS_HOST_ALLOWLIST": al})


def test_disallowed_raises(fake_dns):
    al = HostAllowList("sz.example.com")
    with pytest.raises(RuckusClientError):
        assert_host_allowed("evil.example.com", {"RUCKUS_HOST_ALLOWLIST": al})


def test_loopback_bind_allows_empty_allowlist():
    from ruckus_dashboard.net.allowlist import require_allowlist_for_bind
    require_allowlist_for_bind("127.0.0.1", HostAllowList(""))   # no raise


def test_non_loopback_bind_requires_allowlist():
    from ruckus_dashboard.net.allowlist import require_allowlist_for_bind
    with pytest.raises(RuntimeError, match="RUCKUS_ALLOWED_HOSTS"):
        require_allowlist_for_bind("0.0.0.0", HostAllowList(""))


def test_non_loopback_bind_ok_when_allowlist_configured():
    from ruckus_dashboard.net.allowlist import require_allowlist_for_bind
    require_allowlist_for_bind("0.0.0.0", HostAllowList("10.0.0.0/8"))   # no raise
