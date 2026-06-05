"""HTML page routes (shell, module pages)."""
from __future__ import annotations
from flask import Blueprint, abort, current_app, render_template, session

from ..modules import MODULES, all_modules

bp = Blueprint("pages", __name__)


@bp.get("/")
def index():
    if not current_app.config.get("RUCKUS_ENABLE_NEW_UI"):
        return render_template("legacy.html")
    return render_template("overview.html",
                           modules=all_modules(),
                           csrf_token=session.get("csrf_token", ""))


@bp.get("/m/<slug>")
def module_page(slug: str):
    spec = MODULES.get(slug)
    if spec is None:
        abort(404)
    return render_template("module.html",
                           module=spec,
                           modules=all_modules(),
                           csrf_token=session.get("csrf_token", ""))


@bp.get("/m/<slug>/<entity_id>")
def drill_page(slug: str, entity_id: str):
    spec = MODULES.get(slug)
    if spec is None:
        abort(404)
    return render_template("module.html",
                           module=spec,
                           entity_id=entity_id,
                           modules=all_modules(),
                           csrf_token=session.get("csrf_token", ""))
