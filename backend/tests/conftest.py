"""Test harness for the BeforeYouGo backend.

Safety rules enforced here:
* The environment is pinned to the dedicated ``beforeyougo_test`` database BEFORE the app is imported.
  A guard refuses to run if the configured database is not named ``*_test`` (the dev database holds real data).
* The schema is created by running ``alembic upgrade head`` against the test database only.
* Every test starts from empty tables (TRUNCATE ... CASCADE; append-only triggers are row triggers and are not fired).
* No network: LLM and outbound fetch transports are mocked per test; ``allow_private_fetch`` is switched on only
  inside tests that feed a ``httpx.MockTransport``.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

TEST_DB_URL = os.environ.get("BYG_TEST_DATABASE_URL", "postgresql+psycopg://byg:byg_dev_password@localhost:5432/beforeyougo_test")
_UPLOAD_DIR = tempfile.mkdtemp(prefix="byg-test-uploads-")

# Hard overrides (not setdefault): nothing from the developer's shell may leak into the tests.
os.environ["BYG_ENV"] = "test"
os.environ["DATABASE_URL"] = TEST_DB_URL
os.environ["ENABLE_SCHEDULER"] = "false"
os.environ["LLM_PROVIDER"] = "none"
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production-use-0123456789"
os.environ["UPLOAD_DIR"] = _UPLOAD_DIR
os.environ["ALLOW_PRIVATE_FETCH"] = "false"
os.environ["ICS_FEED_URLS"] = ""
for _k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
    os.environ.pop(_k, None)
for _k in ("RATE_LIMIT_AUTH_PER_MIN", "RATE_LIMIT_EXPENSIVE_PER_MIN", "MAX_UPLOAD_MB", "SYNC_MAX_ATTEMPTS"):
    os.environ.pop(_k, None)
os.environ["SYNC_BACKOFF_BASE_SECONDS"] = "0"

import pytest  # noqa: E402
from sqlalchemy import text  # noqa: E402

_db_name = TEST_DB_URL.rsplit("/", 1)[-1].split("?")[0]
if not _db_name.endswith("_test"):  # pragma: no cover - safety net
    raise RuntimeError(f"Refusing to run tests against database '{_db_name}': the name must end with '_test'.")

from alembic.config import Config  # noqa: E402

from alembic import command  # noqa: E402
from app.core import db as core_db  # noqa: E402
from app.core.config import BACKEND_DIR, get_settings  # noqa: E402
from app.core.ratelimit import reset_rate_limits  # noqa: E402

assert get_settings().database_url == TEST_DB_URL, "settings did not pick up the test DATABASE_URL"
assert get_settings().env == "test"


def _alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return cfg


@pytest.fixture(scope="session", autouse=True)
def _schema() -> Iterator[None]:
    core_db.reset_engine()
    command.upgrade(_alembic_config(), "head")
    eng = core_db.get_engine()
    with eng.connect() as conn:
        assert conn.execute(text("select current_database()")).scalar() == _db_name
    yield
    core_db.reset_engine()
    shutil.rmtree(_UPLOAD_DIR, ignore_errors=True)


def _truncate_all() -> None:
    eng = core_db.get_engine()
    with eng.begin() as conn:
        assert conn.execute(text("select current_database()")).scalar() == _db_name  # never truncate anything else
        conn.execute(text("SET LOCAL lock_timeout = '15s'"))
        names = [
            r[0]
            for r in conn.execute(
                text("select tablename from pg_tables where schemaname='public' and tablename <> 'alembic_version'")
            )
        ]
        conn.execute(text("TRUNCATE " + ", ".join(f'"{n}"' for n in names) + " RESTART IDENTITY CASCADE"))


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Fresh tables, rate limiter, adapter overrides, transports and settings for every test."""
    from app.services.analyzer import llm
    from app.services.safe_fetch import clear_robots_cache, set_transport_override
    from app.services.sources.registry import set_adapter_overrides

    settings = get_settings()
    for name in (
        "allow_private_fetch", "llm_provider", "anthropic_api_key", "openai_api_key", "openai_base_url", "llm_max_retries",
        "llm_timeout_seconds", "max_upload_mb", "fetch_max_bytes", "rate_limit_per_minute_auth",
        "rate_limit_per_minute_expensive", "stale_after_days", "sync_max_attempts", "upload_dir",
    ):
        monkeypatch.setattr(settings, name, getattr(settings, name))  # restored automatically after the test
    monkeypatch.setattr(settings, "rate_limit_per_minute_expensive", 1000)  # only rate-limit tests lower these
    _truncate_all()
    reset_rate_limits()
    set_adapter_overrides(None)
    set_transport_override(None)
    llm.set_llm_transport_override(None)
    clear_robots_cache()
    yield
    set_adapter_overrides(None)
    set_transport_override(None)
    llm.set_llm_transport_override(None)
    reset_rate_limits()


@pytest.fixture
def settings():
    return get_settings()


@pytest.fixture
def db() -> Iterator[object]:
    """A session for arranging and inspecting data. Always commit after arranging; call ``db.expire_all()`` after API calls."""
    session = core_db.session_factory()()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def client():
    """HTTP client against the real ASGI app (no lifespan, so no startup seeding or scheduler)."""
    from fastapi.testclient import TestClient

    from app.main import app

    yield TestClient(app, raise_server_exceptions=False)  # not a context manager: no lifespan, so no seeding/scheduler


@pytest.fixture
def upload_dir() -> Path:
    return Path(get_settings().upload_dir)
