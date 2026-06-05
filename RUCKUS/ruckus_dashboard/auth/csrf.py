"""CSRF token validator. Lifted from monolith _validate_csrf."""
from __future__ import annotations

import hmac

from flask import abort, request, session


def validate_csrf() -> None:
    """Abort 400 if request CSRF token missing or mismatched.

    Accepts the token from either the ``csrf_token`` form field or the
    ``X-CSRF-Token`` HTTP header. Uses :func:`hmac.compare_digest` for
    constant-time comparison against ``session['csrf_token']``.
    """
    expected = session.get("csrf_token", "")
    presented = request.form.get("csrf_token") or request.headers.get(
        "X-CSRF-Token", ""
    )
    if (
        not expected
        or not presented
        or not hmac.compare_digest(str(expected), str(presented))
    ):
        abort(400, description="Invalid CSRF token.")
