import subprocess
import sys

def test_cli_help_works():
    r = subprocess.run(
        [sys.executable, "-m", "ruckus_dashboard", "--help"],
        capture_output=True, text=True, cwd="RUCKUS",
    )
    assert r.returncode == 0
    assert "--bind" in r.stdout
    assert "--port" in r.stdout
    assert "--debug" in r.stdout
    assert "--allowed-hosts" in r.stdout

def test_cli_version_works():
    r = subprocess.run(
        [sys.executable, "-m", "ruckus_dashboard", "--version"],
        capture_output=True, text=True, cwd="RUCKUS",
    )
    assert r.returncode == 0
    assert "RUCKUS" in (r.stdout + r.stderr)

def test_cli_parses_overrides():
    from ruckus_dashboard.cli import _parse_args
    args = _parse_args(["--bind", "0.0.0.0", "--port", "9999",
                        "--no-browser", "--debug",
                        "--allowed-hosts", "10.0.0.0/8"])
    assert args.bind == "0.0.0.0"
    assert args.port == 9999
    assert args.no_browser is True
    assert args.debug is True
    assert args.allowed_hosts == "10.0.0.0/8"
