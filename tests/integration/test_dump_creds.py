"""Credential resolution for --dump: flag > env > interactive prompt.

Passwords must never need to be passed on the command line (PowerShell
quoting hell + shell history leakage). When --smartzone-pass is empty, fall
back to the RUCKUS_SMARTZONE_PASSWORD env var, then to a secure getpass prompt.
"""
import argparse
import ruckus_dashboard.cli as cli


def _args(**kw):
    base = dict(
        platform="smartzone", smartzone_host="10.0.0.1", smartzone_user="admin",
        smartzone_pass="", smartzone_api_version="auto",
        smartzone_skip_tls_verify=True,
        tenant_id=None, client_id=None, client_secret=None, region="na",
    )
    base.update(kw)
    return argparse.Namespace(**base)


def test_password_from_flag_used_directly():
    args = _args(smartzone_pass="hunter2")
    assert cli._resolve_smartzone_password(args, prompt=lambda *_: "PROMPTED") == "hunter2"


def test_password_from_env_when_flag_empty(monkeypatch):
    monkeypatch.setenv("RUCKUS_SMARTZONE_PASSWORD", "from-env")
    args = _args(smartzone_pass="")
    assert cli._resolve_smartzone_password(args, prompt=lambda *_: "PROMPTED") == "from-env"


def test_password_prompted_when_flag_and_env_empty(monkeypatch):
    monkeypatch.delenv("RUCKUS_SMARTZONE_PASSWORD", raising=False)
    args = _args(smartzone_pass="")
    got = cli._resolve_smartzone_password(args, prompt=lambda *_: "typed-secret")
    assert got == "typed-secret"


def test_dump_form_uses_resolved_password(monkeypatch):
    monkeypatch.setenv("RUCKUS_SMARTZONE_PASSWORD", "envpass")
    args = _args(smartzone_pass="")
    form = cli._dump_form(args, prompt=lambda *_: "should-not-be-used")
    assert form["smartzone_password"] == "envpass"
    assert form["smartzone_username"] == "admin"
