"""Argparse-driven launcher."""
from __future__ import annotations
import argparse
import threading
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
    return p.parse_args(argv)


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
