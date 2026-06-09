"""Argparse-driven launcher."""
from __future__ import annotations
import argparse
import json
import pathlib
import sys
import threading
import time
import webbrowser
from typing import Any

from . import APP_NAME, APP_VERSION
from .app import create_app
from .certs import ensure_self_signed_cert
from .net.port_scan import select_dashboard_port, port_self_test_script_block
from .config import DEFAULT_DASHBOARD_PORT, DEFAULT_SMARTZONE_API_PORT

_BROWSER_OPENED = False


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="ruckus_dashboard",
                                description=f"{APP_NAME} v{APP_VERSION}")
    p.add_argument("--bind", help="Interface to bind (default 127.0.0.1).")
    p.add_argument("--port", type=int, help=f"HTTPS port (default {DEFAULT_DASHBOARD_PORT}).")
    p.add_argument("--smartzone-port", type=int,
                   help=f"SmartZone API port (default {DEFAULT_SMARTZONE_API_PORT}).")
    p.add_argument("--no-browser", action="store_true", help="Do not auto-open a browser.")
    p.add_argument("--no-auto-port", action="store_true",
                   help="Fail instead of scanning for a free port.")
    p.add_argument("--allowed-hosts", default=None,
                   help="SSRF allow-list (comma-separated).")
    p.add_argument("--debug", action="store_true", help="Expose API debug output.")
    p.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION}")

    # ─── headless data-dump mode (no Flask server) ──────────────────
    dump = p.add_argument_group("headless dump")
    dump.add_argument("--dump", action="store_true",
                      help="Connect, snapshot every module to JSON, then exit (no server).")
    dump.add_argument("--dump-file",
                      help="Output path (default ruckus-dump-<timestamp>.json).")
    dump.add_argument("--probe-switchm", metavar="PATH",
                      help="Diagnostic: POST this Switch Manager path (e.g. 'switch', "
                           "'vlans/query', 'group', 'switch/ports/summary') with the "
                           "standard query envelope and print the raw JSON response, "
                           "then exit. Uses the same creds as --dump.")
    dump.add_argument("--platform", default="smartzone",
                      choices=["smartzone", "ruckus_one"],
                      help="RUCKUS platform to connect to (default smartzone).")
    # SmartZone creds
    dump.add_argument("--smartzone-host", help="SmartZone host/IP.")
    dump.add_argument("--smartzone-user", help="SmartZone username.")
    dump.add_argument("--smartzone-pass",
                      help="SmartZone password. Omit to be prompted securely "
                           "(or set RUCKUS_SMARTZONE_PASSWORD).")
    dump.add_argument("--smartzone-api-version", default="auto",
                      help="SmartZone public API version (default auto).")
    dump.add_argument("--smartzone-skip-tls-verify", action="store_true",
                      help="Skip TLS verification (self-signed lab controllers).")
    # RUCKUS One creds
    dump.add_argument("--tenant-id", help="RUCKUS One tenant id.")
    dump.add_argument("--client-id", help="RUCKUS One client id.")
    dump.add_argument("--client-secret",
                      help="RUCKUS One client secret. Omit to be prompted securely "
                           "(or set RUCKUS_ONE_CLIENT_SECRET).")
    dump.add_argument("--region", default="na", help="RUCKUS One region (default na).")
    return p.parse_args(argv)


def _resolve_smartzone_password(args: argparse.Namespace, prompt=None) -> str:
    """Resolve the SmartZone password without requiring it on the command line.

    Precedence: --smartzone-pass flag > RUCKUS_SMARTZONE_PASSWORD env var >
    secure interactive prompt. Passing secrets as CLI args leaks them into shell
    history and `ps`, and trips PowerShell quoting — so an empty flag falls back
    to env then getpass.
    """
    import getpass
    import os
    if args.smartzone_pass:
        return args.smartzone_pass
    env_pw = os.getenv("RUCKUS_SMARTZONE_PASSWORD")
    if env_pw:
        return env_pw
    if prompt is not None:
        return prompt(f"SmartZone password for {args.smartzone_user or '(user)'}: ")
    if sys.stdin.isatty():
        return getpass.getpass(f"SmartZone password for {args.smartzone_user or '(user)'}: ")
    # Non-interactive with no flag/env: return empty so auth fails with a clear error.
    return ""


def _resolve_ruckus_one_secret(args: argparse.Namespace, prompt=None) -> str:
    """RUCKUS One client secret: --client-secret > RUCKUS_ONE_CLIENT_SECRET env > prompt."""
    import getpass
    import os
    if args.client_secret:
        return args.client_secret
    env_secret = os.getenv("RUCKUS_ONE_CLIENT_SECRET")
    if env_secret:
        return env_secret
    if prompt is not None:
        return prompt("RUCKUS One client secret: ")
    if sys.stdin.isatty():
        return getpass.getpass("RUCKUS One client secret: ")
    return ""


def _dump_form(args: argparse.Namespace, prompt=None) -> dict[str, str]:
    """Translate CLI dump args into the form-dict the authenticators expect.

    Secrets (SmartZone password / RUCKUS One client secret) are resolved via
    flag > env > interactive prompt so they never need to be typed on the
    command line.
    """
    if args.platform == "ruckus_one":
        return {
            "platform": "ruckus_one",
            "tenant_id": args.tenant_id or "",
            "client_id": args.client_id or "",
            "client_secret": _resolve_ruckus_one_secret(args, prompt),
            "ruckus_one_region": args.region or "na",
            "ruckus_one_custom_host": "",
        }
    return {
        "platform": "smartzone",
        "smartzone_host": args.smartzone_host or "",
        "smartzone_username": args.smartzone_user or "",
        "smartzone_password": _resolve_smartzone_password(args, prompt),
        "smartzone_api_version": args.smartzone_api_version or "auto",
        "smartzone_skip_tls_verify": "1" if args.smartzone_skip_tls_verify else "0",
    }


def _run_dump_mode(args: argparse.Namespace) -> int:
    """Headless: authenticate, run every fetcher + sample drills, write JSON. No server."""
    from .config import build_config
    from .net.allowlist import HostAllowList
    from .clients import authenticate_connection
    from .clients.base import RuckusClientError
    from .dump import run_dump

    config = build_config(str(pathlib.Path.cwd()))
    # request_json enforces the SSRF allow-list; default empty list = unrestricted,
    # which is correct for a local operator dump against their own controller.
    config["RUCKUS_HOST_ALLOWLIST"] = HostAllowList(config.get("RUCKUS_ALLOWED_HOSTS", ""))

    form = _dump_form(args)
    try:
        connection = authenticate_connection(form, config)
    except (ValueError, RuckusClientError) as exc:
        print(f"Connection failed: {exc}", file=sys.stderr)
        return 1

    result = run_dump(connection, config)

    out_path = args.dump_file or f"ruckus-dump-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, default=str)

    print(f"{APP_NAME} v{APP_VERSION}")
    print(f"Wrote dump: {out_path}")
    print(f"Controller: {result['controller']['platform']} "
          f"{result['controller']['version']} ({result['controller']['api_base']})")
    print(f"Capabilities: {result['capabilities']['op_count']} ops discovered")
    for slug, entry in result["modules"].items():
        status = entry["status"]
        detail = f" ({entry['item_count']} items)" if status == "complete" else ""
        if status == "error":
            detail = f" — {entry['error']}"
        print(f"  [{status:>8}] {slug}{detail}")
    return 0


def _run_probe_mode(args: argparse.Namespace) -> int:
    """Headless diagnostic: POST one Switch Manager path and print raw JSON."""
    import pathlib
    from .config import build_config
    from .net.allowlist import HostAllowList
    from .clients import authenticate_connection
    from .clients.base import RuckusClientError
    from .clients.switchm import switch_manager_query

    config = build_config(str(pathlib.Path.cwd()))
    config["RUCKUS_HOST_ALLOWLIST"] = HostAllowList(config.get("RUCKUS_ALLOWED_HOSTS", ""))
    form = _dump_form(args)
    try:
        connection = authenticate_connection(form, config)
    except (ValueError, RuckusClientError) as exc:
        print(f"Connection failed: {exc}", file=sys.stderr)
        return 1

    path = args.probe_switchm.lstrip("/")
    try:
        data = switch_manager_query(connection, path, config)
    except RuckusClientError as exc:
        print(f"Probe {path} failed: HTTP {exc.status_code}", file=sys.stderr)
        if isinstance(exc.debug, dict) and exc.debug.get("raw"):
            print(exc.debug["raw"], file=sys.stderr)
        return 1
    print(f"# Switch Manager POST /{path} — raw response (first 8000 chars):")
    print(json.dumps(data, indent=2, default=str)[:8000])
    return 0


def _browser_host(host: str) -> str:
    return "localhost" if host in {"0.0.0.0", "::"} else host


def open_browser_once(url: str) -> None:
    global _BROWSER_OPENED
    if _BROWSER_OPENED:
        return
    _BROWSER_OPENED = True
    threading.Thread(target=lambda: webbrowser.open(url), daemon=True).start()


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    if getattr(args, "probe_switchm", None):
        sys.exit(_run_probe_mode(args))
    if args.dump:
        sys.exit(_run_dump_mode(args))
    overrides: dict[str, Any] = {}
    if args.bind: overrides["APP_HOST"] = args.bind
    if args.port is not None: overrides["APP_PORT"] = args.port
    if args.smartzone_port is not None: overrides["RUCKUS_SMARTZONE_PORT"] = args.smartzone_port
    if args.no_browser: overrides["APP_OPEN_BROWSER"] = False
    if args.no_auto_port: overrides["APP_AUTO_PORT"] = False
    if args.allowed_hosts is not None: overrides["RUCKUS_ALLOWED_HOSTS"] = args.allowed_hosts
    if args.debug: overrides["RUCKUS_SHOW_DEBUG"] = True

    app = create_app(overrides or None)
    bind_host = app.config["APP_HOST"]
    requested_port = int(app.config["APP_PORT"])

    print(port_self_test_script_block(bind_host, requested_port))
    port, used_random_port = select_dashboard_port(
        bind_host, requested_port, app.config["APP_AUTO_PORT"],
        scan_limit=app.config["APP_PORT_SCAN_LIMIT"],
    )
    cert_file, key_file = ensure_self_signed_cert(app.instance_path)
    url = f"https://{_browser_host(bind_host)}:{port}"

    print(f"{APP_NAME} v{APP_VERSION}")
    if used_random_port:
        print(f"Requested port {requested_port} unavailable; using {port}.")
    print(f"Opening dashboard: {url}")
    if app.config["APP_OPEN_BROWSER"]:
        open_browser_once(url)

    try:
        app.run(host=bind_host, port=port,
                ssl_context=(str(cert_file), str(key_file)),
                debug=False, use_reloader=False, threaded=True)
    except KeyboardInterrupt:
        import os
        os._exit(0)
