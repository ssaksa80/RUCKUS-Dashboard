"""Database engine + scoped-session factory for the Phase B identity layer.

Single-node, SQLite. The engine URL comes from ``RUCKUS_DATABASE_URL`` and
defaults to ``sqlite:///<instance>/ruckus.db``. Schema is created on boot via
``Base.metadata.create_all`` (Alembic arrives in a later slice); the SQLite
file is chmod 0600 to match the other secrets in ``instance/``.

Usage from the app:

    init_db(app)                       # creates engine, tables, scoped session
    with app.db_session() as s: ...    # request-scoped session (see helper)

The engine + ``scoped_session`` live on the Flask app (``app.db_engine`` /
``app.db_session``). ``db_session`` is a :class:`~sqlalchemy.orm.scoped_session`;
call ``app.db_session.remove()`` at teardown to return the connection.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, scoped_session, sessionmaker
from sqlalchemy.pool import StaticPool

from .models import Base

LOG = logging.getLogger("ruckus_dashboard.db")

# In-memory / shared-cache SQLite URLs need a single shared connection, or each
# pool checkout sees an empty database. StaticPool gives every session the same
# underlying connection (fine single-node; tests rely on it too).
_MEMORY_URLS = frozenset(
    {"sqlite://", "sqlite:///", "sqlite:///:memory:", "sqlite:///:memory"}
)


def default_database_url(instance_path: str) -> str:
    """The default on-disk SQLite URL under the instance dir."""
    db_path = Path(instance_path) / "ruckus.db"
    # as_posix() keeps the URL forward-slashed on Windows (SQLAlchemy-friendly).
    return f"sqlite:///{db_path.as_posix()}"


def _is_memory_url(url: str) -> bool:
    u = url.strip()
    return u in _MEMORY_URLS or ":memory:" in u


def make_engine(url: str) -> Engine:
    """Create a SQLAlchemy engine for ``url``.

    SQLite specifics: ``check_same_thread=False`` (the daemon schedulers and the
    request threads share the app engine) and a ``StaticPool`` for in-memory URLs
    so the schema persists across sessions within one process.
    """
    kwargs: dict = {"future": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if _is_memory_url(url):
            kwargs["poolclass"] = StaticPool
    return create_engine(url, **kwargs)


def make_session_factory(engine: Engine) -> scoped_session:
    """A thread-local scoped-session factory bound to ``engine``."""
    factory = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False, future=True
    )
    return scoped_session(factory)


def _chmod_sqlite_file(url: str) -> None:
    """Best-effort 0600 on the SQLite file (parity with other instance secrets).

    No-op for in-memory URLs and on platforms where chmod is meaningless
    (Windows POSIX bits don't map, but the call is harmless / guarded).
    """
    if not url.startswith("sqlite") or _is_memory_url(url):
        return
    # sqlite:///C:/path/ruckus.db  ->  C:/path/ruckus.db
    path_str = url[len("sqlite:///"):]
    if not path_str:
        return
    p = Path(path_str)
    try:
        if p.exists():
            p.chmod(0o600)
    except OSError as exc:  # pragma: no cover - platform dependent
        LOG.warning("could not chmod sqlite file %s: %s", p, exc)


def init_db(app) -> Engine:
    """Wire the engine + scoped session onto ``app`` and create the schema.

    Reads ``app.config['RUCKUS_DATABASE_URL']`` (falling back to the on-disk
    default under ``app.instance_path``), builds the engine, runs
    ``create_all``, chmods the SQLite file 0600, and stores
    ``app.db_engine`` / ``app.db_session``. Registers a teardown that returns
    the scoped session to the pool after each request. Idempotent per app.
    """
    url = app.config.get("RUCKUS_DATABASE_URL") or default_database_url(
        app.instance_path
    )
    # Make sure the instance dir exists for the on-disk default.
    if url.startswith("sqlite") and not _is_memory_url(url):
        Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    engine = make_engine(url)
    Base.metadata.create_all(engine)
    _chmod_sqlite_file(url)

    session_factory = make_session_factory(engine)

    app.db_engine = engine
    app.db_session = session_factory
    app.config["RUCKUS_DATABASE_URL"] = url  # record the resolved URL

    @app.teardown_appcontext
    def _remove_session(exc=None):  # noqa: ARG001 - Flask passes the exception
        session_factory.remove()

    return engine


def default_tenant_id(app) -> int:
    """Resolve the id of the ``default`` tenant, creating it if absent.

    PB3 uses this for the tenant-unaware entry points (file-state migration,
    the scheduler with no active connection, single-tenant callers). Seeding
    normally creates ``default`` first (id 1), but this stays correct even if
    the row was created out of order.
    """
    from .models import Tenant

    with session_scope(app) as s:
        tenant = s.query(Tenant).filter_by(name="default").one_or_none()
        if tenant is None:
            tenant = Tenant(name="default")
            s.add(tenant)
            s.flush()
        return tenant.id


@contextmanager
def session_scope(app) -> Iterator[Session]:
    """Transactional scope around ``app.db_session`` for out-of-request work.

    Commits on success, rolls back on error, always closes. Request handlers can
    just use ``app.db_session`` directly (teardown returns it); this helper is
    for schedulers / startup seeding that run without a request context.
    """
    session: Session = app.db_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
