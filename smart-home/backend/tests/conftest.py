"""Shared fixtures. Env vars are set before `app` is imported, because the settings
object and the SQLAlchemy engine are created at import time. A temp-file SQLite
database is used instead of :memory: so every connection sees the same data."""

import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="smarthome-tests-"))
os.environ.update(
    {
        "DATABASE_URL": f"sqlite:///{(_TMP / 'test.db').as_posix()}",
        "MQTT_ENABLED": "false",
        "CLOUD_SINK_ENABLED": "false",
        "DASHBOARD_PASSWORD": "",
        "AUTH_SECRET": "test-secret",
        "SEED_DEMO": "false",
        "LAKE_DIR": (_TMP / "lake").as_posix(),
    }
)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Settings read ".env" from the working directory at import time; import from the
# temp dir so a developer's backend/.env (e.g. a custom DEVICE_API_KEY) cannot leak in
_cwd = os.getcwd()
os.chdir(_TMP)
try:
    from fastapi.testclient import TestClient  # noqa: E402

    from app import analytics, cloud_sink, models, services  # noqa: E402
    from app.database import Base, SessionLocal, engine  # noqa: E402
    from app.main import app  # noqa: E402
    from app.routers import auth  # noqa: E402
finally:
    os.chdir(_cwd)

DEVICE_KEY = {"X-Device-Key": "esp32-secret-key"}


def pytest_sessionfinish(session, exitstatus):
    engine.dispose()
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture(autouse=True)
def fresh_state():
    """Empty tables and in-memory module state for every test."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    cloud_sink.reset()
    analytics.reset_state()
    auth.reset_rate_limit()
    services._last_motion.clear()
    services.auto_off_deadlines.clear()
    yield


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client():
    # Not used as a context manager: the lifespan (MQTT, background worker) stays off
    return TestClient(app)


@pytest.fixture
def device(db):
    sensor = models.Device(code="esp32-main", name="ESP32", kind="sensor", room="Phong khach")
    db.add(sensor)
    db.commit()
    return sensor


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def add_reading(db, device, metric: str, value: float, ts: datetime) -> None:
    db.add(models.Reading(device_id=device.id, metric=metric, value=value, ts=ts))
