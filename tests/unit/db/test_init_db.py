"""db.init_db wiring: engine/session on the app, on-disk schema + 0600 chmod.

Uses a bare Flask app (not the full create_app) to isolate the db layer.
"""
from __future__ import annotations

import stat
import sys
from pathlib import Path

import pytest
from flask import Flask

from ruckus_dashboard import db as dbmod
from ruckus_dashboard.db.models import Tenant


def _bare_app(instance_path: str, url: str | None = None) -> Flask:
    app = Flask(__name__)
    app.instance_path = instance_path
    app.config["RUCKUS_DATABASE_URL"] = url
    return app


def test_default_database_url_points_into_instance(tmp_path):
    url = dbmod.default_database_url(str(tmp_path))
    assert url.startswith("sqlite:///")
    assert url.endswith("ruckus.db")
    # forward-slashed even on Windows
    assert "\\" not in url


def test_init_db_creates_file_and_tables(tmp_path):
    app = _bare_app(str(tmp_path))
    dbmod.init_db(app)
    db_file = tmp_path / "ruckus.db"
    assert db_file.exists()
    # engine + session wired onto the app
    assert app.db_engine is not None
    s = app.db_session()
    s.add(Tenant(name="default"))
    s.commit()
    assert s.query(Tenant).count() == 1
    app.db_session.remove()


def test_init_db_records_resolved_url(tmp_path):
    app = _bare_app(str(tmp_path))  # url None -> resolved to default
    dbmod.init_db(app)
    assert app.config["RUCKUS_DATABASE_URL"].endswith("ruckus.db")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX perms not meaningful on Windows")
def test_init_db_chmods_sqlite_file_0600(tmp_path):
    app = _bare_app(str(tmp_path))
    dbmod.init_db(app)
    mode = stat.S_IMODE(Path(tmp_path / "ruckus.db").stat().st_mode)
    assert mode == 0o600


def test_init_db_memory_url_has_no_file(tmp_path):
    app = _bare_app(str(tmp_path), url="sqlite:///:memory:")
    dbmod.init_db(app)
    assert not (tmp_path / "ruckus.db").exists()
    # still usable
    s = app.db_session()
    s.add(Tenant(name="mem"))
    s.commit()
    assert s.query(Tenant).count() == 1
    app.db_session.remove()
