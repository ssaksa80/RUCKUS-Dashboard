"""Integration test for the ``--dump`` headless CLI mode.

Exercises ``_run_dump_mode`` end-to-end: SmartZone auth (apiInfo +
serviceTicket) is mocked with ``responses``; module query endpoints are left
unmatched so they surface as per-module ``error`` entries in the dump (which is
fine — the contract is "write one valid JSON snapshot of whatever we collected").
"""
from __future__ import annotations

import json

import pytest
import responses

from ruckus_dashboard.cli import _run_dump_mode, _parse_args
from ruckus_dashboard.modules import MODULES


def _args(argv):
    return _parse_args(argv)


def test_dump_mode_writes_valid_json(tmp_path):
    out = tmp_path / "d.json"
    base = "https://sz.example:8443/wsg/api/public"

    with responses.RequestsMock(assert_all_requests_are_fired=False) as r:
        r.add(responses.GET, f"{base}/apiInfo",
              json={"apiSupportVersions": ["v11_0"]}, status=200)
        r.add(responses.POST, f"{base}/v11_0/serviceTicket",
              json={"serviceTicket": "t", "controllerVersion": "7.1.1"}, status=200)
        # OpenAPI capability probes -> 404 (no caps discovered).
        r.add(responses.GET, "https://sz.example:8443/wsg/apiDoc/openapi", status=404)
        r.add(responses.GET, "https://sz.example:8443/switchm/api/openapi", status=404)

        args = _args([
            "--dump", "--platform", "smartzone",
            "--smartzone-host", "sz.example",
            "--smartzone-user", "u",
            "--smartzone-pass", "p",
            "--smartzone-skip-tls-verify",
            "--dump-file", str(out),
        ])
        rc = _run_dump_mode(args)

    assert rc == 0
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    for key in ("dumped_at", "app_version", "controller", "capabilities", "modules"):
        assert key in data
    assert data["controller"]["platform"] == "smartzone"
    assert data["controller"]["version"] == "7.1.1"
    # Every registered module must appear in the dump.
    assert set(data["modules"].keys()) == set(MODULES.keys())
    assert len(data["modules"]) == 19


def test_dump_mode_missing_creds_returns_nonzero(tmp_path):
    out = tmp_path / "d.json"
    args = _args([
        "--dump", "--platform", "smartzone",
        "--dump-file", str(out),
    ])
    rc = _run_dump_mode(args)
    assert rc == 1
    assert not out.exists()
