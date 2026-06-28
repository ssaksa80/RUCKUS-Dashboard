import socket
import ssl
import subprocess
import sys
import time
import urllib.request

def _wait_port(host, port, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.1)
    return False

def test_app_boots_and_serves_healthz(tmp_path):
    """End-to-end smoke: launch CLI, hit /healthz over self-signed HTTPS."""
    proc = subprocess.Popen(
        [sys.executable, "-m", "ruckus_dashboard",
         "--bind", "127.0.0.1", "--port", "0", "--no-browser"],
        cwd="RUCKUS",
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        port = None
        deadline = time.time() + 10
        while time.time() < deadline:
            line = proc.stdout.readline()
            if not line:
                break
            if "Opening dashboard:" in line:
                port = int(line.rsplit(":", 1)[1].strip())
                break
        assert port, "CLI did not print port within 10s"
        assert _wait_port("127.0.0.1", port, timeout=10)

        ctx = ssl._create_unverified_context()
        with urllib.request.urlopen(f"https://127.0.0.1:{port}/healthz",
                                     context=ctx, timeout=5) as r:
            assert r.status == 200
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_warmup_status_endpoint_reachable_when_unauthenticated(tmp_path):
    """Boot CLI, hit /api/warmup/status — expect 401 (proves blueprint registered)."""
    import subprocess
    import sys
    import socket
    import time
    import ssl
    import urllib.request
    import urllib.error
    proc = subprocess.Popen(
        [sys.executable, "-m", "ruckus_dashboard",
         "--bind", "127.0.0.1", "--port", "0", "--no-browser"],
        cwd="RUCKUS",
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        port = None
        deadline = time.time() + 10
        while time.time() < deadline:
            line = proc.stdout.readline()
            if not line:
                break
            if "Opening dashboard:" in line:
                port = int(line.rsplit(":", 1)[1].strip())
                break
        assert port, "CLI did not print port within 10s"

        for _ in range(30):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    break
            except OSError:
                time.sleep(0.1)

        ctx = ssl._create_unverified_context()
        req = urllib.request.Request(f"https://127.0.0.1:{port}/api/warmup/status")
        try:
            urllib.request.urlopen(req, context=ctx, timeout=5)
            assert False, "expected 401"
        except urllib.error.HTTPError as e:
            assert e.code == 401
    finally:
        proc.terminate()
        proc.wait(timeout=5)
