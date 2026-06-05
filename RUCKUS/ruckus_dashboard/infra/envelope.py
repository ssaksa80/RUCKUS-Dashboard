"""Unified envelope for module responses (status / data / errors)."""
from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class ControllerError:
    connection: str
    endpoint: str
    message: str
    status: int

    def to_dict(self) -> dict:
        return {
            "connection": self.connection,
            "endpoint": self.endpoint,
            "message": self.message,
            "status": self.status,
        }


def build_envelope(
    *,
    data,
    summary: dict,
    errors: list[ControllerError],
    stale_since: str | None = None,
) -> dict:
    if data is None:
        status = "error"
    elif errors:
        status = "partial"
    else:
        status = "complete"
    return {
        "status": status,
        "data": data,
        "summary": summary,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "controller_errors": [e.to_dict() for e in errors],
        "stale_since": stale_since,
    }
