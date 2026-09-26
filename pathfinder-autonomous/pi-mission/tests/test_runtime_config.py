import os

import pytest

from papaya_mission import runtime_config


def test_tick_interval_matches_tick_hz():
    assert runtime_config.TICK_INTERVAL_S == pytest.approx(1.0 / runtime_config.TICK_HZ)


def test_load_runtime_settings_reads_env(monkeypatch):
    monkeypatch.setenv("ROVER_ID", "rover-123")
    monkeypatch.setenv("BACKEND_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("LOCAL_DB_PATH", "/tmp/papaya.db")

    settings = runtime_config.load_runtime_settings()

    assert settings.rover_id == "rover-123"
    assert settings.backend_base_url == "http://localhost:8000"
    assert settings.local_db_path == "/tmp/papaya.db"


def test_load_runtime_settings_raises_on_missing_env(monkeypatch):
    monkeypatch.delenv("ROVER_ID", raising=False)
    monkeypatch.delenv("BACKEND_BASE_URL", raising=False)
    monkeypatch.delenv("LOCAL_DB_PATH", raising=False)

    with pytest.raises(KeyError):
        runtime_config.load_runtime_settings()
