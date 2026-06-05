import socket

from ruckus_dashboard.net.port_scan import (
    can_exclusively_bind_port,
    port_has_active_listener,
    select_dashboard_port,
)


def test_can_bind_random_high_port():
    assert can_exclusively_bind_port("127.0.0.1", 0)  # 0 = OS-assigned


def test_listener_detected():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    port = s.getsockname()[1]
    try:
        assert port_has_active_listener("127.0.0.1", port)
    finally:
        s.close()


def test_select_port_falls_back_when_requested_busy():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    busy = s.getsockname()[1]
    try:
        port, used_random = select_dashboard_port(
            "127.0.0.1", busy, auto_port=True, scan_limit=10
        )
        assert port != busy
        assert used_random
    finally:
        s.close()
