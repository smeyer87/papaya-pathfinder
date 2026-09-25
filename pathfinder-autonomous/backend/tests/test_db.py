import pytest
from pymongo import MongoClient

from app import db as db_module


def test_get_client_returns_cached_singleton():
    """A new MongoClient per request means a new DNS/TLS handshake and a new
    connection pool on every HTTP call -- get_client must hand back one shared
    client instead."""
    first = db_module.get_client()
    second = db_module.get_client()

    assert isinstance(first, MongoClient)
    assert first is second


def test_get_client_requires_mongo_uri(monkeypatch):
    """No silent fallback to a local mongod: a missing MONGO_URI must fail loudly."""
    monkeypatch.setattr(db_module, "_client", None)
    monkeypatch.delenv("MONGO_URI", raising=False)

    with pytest.raises(KeyError):
        db_module.get_client()
