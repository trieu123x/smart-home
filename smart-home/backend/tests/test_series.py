from datetime import datetime, timedelta

from app import analytics, services
from conftest import add_reading


def _ts(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _seven_days(db, device, now):
    """One reading every 10 minutes for 7 days."""
    start = now - timedelta(days=7)
    for step in range(7 * 24 * 6):
        add_reading(db, device, "temperature", 25 + step % 7, start + timedelta(minutes=10 * step))
    db.commit()
    analytics.run_rollups(db, now)
    db.commit()


def test_168_hours_spans_more_than_6_days(db, device, client):
    now = services.utcnow()
    _seven_days(db, device, now)

    response = client.get("/api/series?metrics=temperature&hours=168")

    assert response.status_code == 200
    [series] = response.json()
    points = series["points"]
    assert series["metric"] == "temperature"
    assert 10 <= len(points) <= 60
    span = _ts(points[-1]["ts"]) - _ts(points[0]["ts"])
    assert span > timedelta(days=6)
    assert points[0]["ts"].endswith("Z")


def test_24_hours_uses_minute_rollups(db, device, client):
    now = services.utcnow()
    _seven_days(db, device, now)

    [series] = client.get("/api/series?metrics=temperature&hours=24&points=100").json()

    span = _ts(series["points"][-1]["ts"]) - _ts(series["points"][0]["ts"])
    assert timedelta(hours=22) < span <= timedelta(hours=24)
    assert len(series["points"]) <= 100


def test_6_hours_reads_raw_rows_over_the_whole_range(db, device, client):
    now = services.utcnow()
    for second in range(0, 6 * 3600 - 60, 10):  # 10 s data, as the ESP32 sends it
        add_reading(db, device, "humidity", 60.0, now - timedelta(seconds=second))
    db.commit()

    [series] = client.get("/api/series?metrics=humidity&hours=6&points=60").json()

    span = _ts(series["points"][-1]["ts"]) - _ts(series["points"][0]["ts"])
    assert span > timedelta(hours=5)
    assert len(series["points"]) <= 60


def test_analytics_endpoints(db, device, client):
    now = services.utcnow()
    _seven_days(db, device, now)

    rollups = client.get("/api/analytics/rollups?metric=temperature&bucket=1h&hours=168")
    assert rollups.status_code == 200
    rows = rollups.json()
    assert 166 <= len(rows) <= 168
    assert set(rows[0]) == {"bucket_start", "min", "max", "avg", "count"}
    assert all(row["min"] <= row["avg"] <= row["max"] for row in rows)

    assert client.get("/api/analytics/rollups?metric=temperature&bucket=5m").status_code == 422
    assert client.get("/api/analytics/rollups?metric=temperature&hours=0").status_code == 422
    assert client.get("/api/analytics/rollups?metric=temperature&hours=721").status_code == 422

    stats = client.get("/api/analytics/stats?hours=24").json()
    assert stats == [
        {
            "metric": "temperature",
            "min": 25.0,
            "max": 31.0,
            "avg": stats[0]["avg"],
            "count": stats[0]["count"],
            "anomalies": 0,
        }
    ]
    assert 143 <= stats[0]["count"] <= 145

    assert client.get("/api/analytics/lake").json() == []


def test_analytics_endpoints_on_empty_database(client):
    assert client.get("/api/analytics/rollups?metric=temperature").json() == []
    assert client.get("/api/analytics/stats").json() == []
    assert client.get("/api/series?metrics=temperature&hours=168").json() == [
        {"metric": "temperature", "points": []}
    ]
