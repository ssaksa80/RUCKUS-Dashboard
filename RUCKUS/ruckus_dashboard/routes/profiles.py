"""Connection-profile management UI (Component 1).

Surfaces the tenant-scoped, DB-backed :class:`~ruckus_dashboard.auth.profiles.ProfileStore`
(PB3) as a server-rendered page — no new client JS, matching the current
look. Operator+ only; every operation is scoped to the app-user's tenant
(``g.tenant_id``), never a client-supplied tenant, so tenant A can neither see
nor delete tenant B's profiles.

Routes:
  * ``GET  /profiles``               — list this tenant's saved profiles + a
    save/new form (plain fields + secret fields; the password uses the
    ``__profile_password__`` sentinel so an unchanged secret is preserved).
  * ``POST /profiles``               — save (create/update) a profile.
  * ``POST /profiles/<name>/delete`` — delete a profile by name.

The profile form also carries a RUCKUS One ``tenant_id`` *credential* field
(the controller's tenant), which is stored as a plain profile field but is
NEVER used to scope the row — scoping is always ``g.tenant_id``.
"""
from __future__ import annotations

import logging

from flask import (
    Blueprint,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from ..auth.audit import record_audit
from ..auth.csrf import validate_csrf
from ..auth.profiles import PROFILE_PLAIN_FIELDS, PROFILE_SECRET_FIELDS
from ..auth.rbac import require_role
from ..modules import all_modules

LOG = logging.getLogger("ruckus_dashboard.profiles")

bp = Blueprint("profiles", __name__)

# Sentinel the form pre-fills for a saved secret so leaving it untouched
# preserves the stored ciphertext (mirrors ProfileStore._PROFILE_PW_SENTINEL).
_PW_SENTINEL = "__profile_password__"


@bp.get("/profiles")
@require_role("operator")
def profiles():
    profiles = current_app.profile_store.list_masked(g.tenant_id)
    return render_template(
        "profiles.html",
        profiles=profiles,
        plain_fields=PROFILE_PLAIN_FIELDS,
        secret_fields=list(PROFILE_SECRET_FIELDS.keys()),
        pw_sentinel=_PW_SENTINEL,
        modules=all_modules(),
        csrf_token=session.get("csrf_token", ""),
    )


@bp.post("/profiles")
@require_role("operator")
def save_profile():
    validate_csrf()
    name = (request.form.get("name") or "").strip()
    try:
        # Scope is ALWAYS the app-user's tenant — never trust a form tenant_id
        # (that field is a RUCKUS One credential stored as a plain profile field).
        current_app.profile_store.save(name, request.form, g.tenant_id)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("profiles.profiles"))
    record_audit(current_app, action="profile_saved", user_id=g.user_id,
                 tenant_id=g.tenant_id, detail={"name": name})
    flash(f"Saved profile {name}.", "success")
    return redirect(url_for("profiles.profiles"))


@bp.post("/profiles/<name>/delete")
@require_role("operator")
def delete_profile(name: str):
    validate_csrf()
    current_app.profile_store.delete(name, g.tenant_id)
    record_audit(current_app, action="profile_deleted", user_id=g.user_id,
                 tenant_id=g.tenant_id, detail={"name": name})
    flash(f"Deleted profile {name}.", "success")
    return redirect(url_for("profiles.profiles"))
