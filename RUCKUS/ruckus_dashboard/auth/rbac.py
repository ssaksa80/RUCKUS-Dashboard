"""RBAC decorators + role ordering for the Phase B app-user layer (PB1).

Two decorators read the request-scoped identity that ``app.before_request``
loads (``g.user`` / ``g.role``):

* ``@require_user``        — must be a logged-in app user.
* ``@require_role(min)``   — must be logged in *and* hold at least ``min`` role.

Response shape mirrors the rest of the app: unauthenticated HTML requests get a
302 to ``/login`` (with ``?next=``), ``/api/*`` requests get a 401 JSON body;
an authenticated-but-insufficient role gets 403 (JSON for ``/api/*``, else a
plain 403). This composes *beneath* the controller-capability gate — RBAC says
"may this user use this feature", the capability gate says "does the controller
expose this op".
"""
from __future__ import annotations

import functools
from typing import Callable

from urllib.parse import urlencode

from flask import g, jsonify, redirect, request, url_for
from werkzeug.routing import BuildError

from ..db.models import Role


def role_meets(actual: "str | Role | None", minimum: "str | Role") -> bool:
    """True iff ``actual`` is at least ``minimum`` in viewer<operator<admin.

    Accepts role names or ``Role`` members. A ``None``/invalid ``actual`` never
    meets the bar (fails closed).
    """
    if actual is None:
        return False
    try:
        return Role.coerce(actual) >= Role.coerce(minimum)
    except (KeyError, ValueError):
        return False


def _wants_json() -> bool:
    """True for API requests (path under /api/) — they get JSON, not redirects."""
    return request.path.startswith("/api/")


def _login_redirect():
    # Preserve where the user was headed so the login handler can bounce back.
    nxt = request.full_path
    try:
        return redirect(url_for("auth.login", next=nxt))
    except BuildError:
        # auth blueprint not registered (e.g. isolated decorator tests) — fall
        # back to the literal path so the gate still redirects correctly.
        return redirect("/login?" + urlencode({"next": nxt}))


def _deny_unauthenticated():
    if _wants_json():
        return jsonify({"error": "Authentication required."}), 401
    return _login_redirect()


def _deny_forbidden():
    if _wants_json():
        return jsonify({"error": "Insufficient permissions."}), 403
    return ("Forbidden", 403)


def require_user(view: Callable) -> Callable:
    """Require a logged-in app user (``g.user`` set by before_request)."""

    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        if getattr(g, "user", None) is None:
            return _deny_unauthenticated()
        return view(*args, **kwargs)

    return wrapper


def require_role(min_role: "str | Role") -> Callable:
    """Require login *and* at least ``min_role`` (``g.role``)."""

    def decorator(view: Callable) -> Callable:
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            if getattr(g, "user", None) is None:
                return _deny_unauthenticated()
            if not role_meets(getattr(g, "role", None), min_role):
                return _deny_forbidden()
            return view(*args, **kwargs)

        return wrapper

    return decorator
