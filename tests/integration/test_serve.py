"""Tests for the WSGI-server selection + dispatch (cli._serve).

These must NOT start a blocking server: app.run and waitress.serve are
monkeypatched to record their call. waitress is imported lazily inside the
waitress branch so these tests pass even when waitress is not installed.
"""
import sys
import pathlib
import types

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent / "RUCKUS"))
from ruckus_dashboard import cli  # noqa: E402


# ─── arg / env selection ─────────────────────────────────────────────

def test_server_arg_defaults_to_werkzeug(monkeypatch):
    # Raw arg is None (so env can be honored when the flag is absent); the
    # *effective* default resolves to werkzeug.
    monkeypatch.delenv("RUCKUS_WSGI_SERVER", raising=False)
    args = cli._parse_args([])
    assert args.server is None
    assert cli._resolve_server(args) == "werkzeug"


def test_server_arg_parses_waitress():
    args = cli._parse_args(["--server", "waitress"])
    assert args.server == "waitress"


def test_server_arg_rejects_unknown():
    with pytest.raises(SystemExit):
        cli._parse_args(["--server", "gunicorn"])


def test_resolve_server_arg_wins_over_env(monkeypatch):
    monkeypatch.setenv("RUCKUS_WSGI_SERVER", "waitress")
    args = cli._parse_args(["--server", "werkzeug"])
    # Explicit --server on the command line beats the env var.
    assert cli._resolve_server(args) == "werkzeug"


def test_resolve_server_env_used_when_arg_absent(monkeypatch):
    monkeypatch.setenv("RUCKUS_WSGI_SERVER", "waitress")
    args = cli._parse_args([])
    assert cli._resolve_server(args) == "waitress"


def test_resolve_server_default_when_neither(monkeypatch):
    monkeypatch.delenv("RUCKUS_WSGI_SERVER", raising=False)
    args = cli._parse_args([])
    assert cli._resolve_server(args) == "werkzeug"


# ─── dispatch ────────────────────────────────────────────────────────

class _FakeApp:
    def __init__(self):
        self.run_calls = []

    def run(self, **kwargs):
        self.run_calls.append(kwargs)


def test_serve_werkzeug_passes_ssl_context():
    app = _FakeApp()
    cli._serve(app, "127.0.0.1", 8444, "werkzeug",
               cert_file="cert.pem", key_file="key.pem", threads=4)
    assert len(app.run_calls) == 1
    kw = app.run_calls[0]
    assert kw["ssl_context"] == ("cert.pem", "key.pem")
    assert kw["host"] == "127.0.0.1"
    assert kw["port"] == 8444
    assert kw["threaded"] is True
    assert kw["use_reloader"] is False


def test_serve_waitress_calls_waitress_serve_without_ssl(monkeypatch):
    app = _FakeApp()
    calls = []
    fake_waitress = types.ModuleType("waitress")
    fake_waitress.serve = lambda application, **kw: calls.append((application, kw))
    monkeypatch.setitem(sys.modules, "waitress", fake_waitress)

    cli._serve(app, "127.0.0.1", 8080, "waitress",
               cert_file="cert.pem", key_file="key.pem", threads=7)

    # waitress path must NOT touch Werkzeug's app.run (no TLS there).
    assert app.run_calls == []
    assert len(calls) == 1
    application, kw = calls[0]
    assert application is app
    assert kw["host"] == "127.0.0.1"
    assert kw["port"] == 8080
    assert kw["threads"] == 7
    assert "ssl_context" not in kw


def test_serve_waitress_missing_dependency_exits_nonzero(monkeypatch):
    app = _FakeApp()
    # Simulate waitress not installed: import inside the branch raises.
    monkeypatch.setitem(sys.modules, "waitress", None)
    with pytest.raises(SystemExit) as exc:
        cli._serve(app, "127.0.0.1", 8080, "waitress",
                   cert_file="c", key_file="k", threads=4)
    assert exc.value.code != 0
