import os

import pytest
from fastapi.testclient import TestClient
from pymongo import MongoClient

from app.db import ensure_indexes, get_database
from app.main import app

TEST_MONGO_URI = os.environ["MONGO_URI"]
TEST_DB_NAME = "papaya_pathfinder_test"


@pytest.fixture
def db():
    mongo_client = MongoClient(TEST_MONGO_URI)
    database = mongo_client[TEST_DB_NAME]
    ensure_indexes(database)
    yield database
    mongo_client.drop_database(TEST_DB_NAME)
    mongo_client.close()


@pytest.fixture
def client(db):
    # Monkeypatch MONGO_DB_NAME to use test database during startup event
    original_db_name = os.environ.get("MONGO_DB_NAME")
    try:
        os.environ["MONGO_DB_NAME"] = TEST_DB_NAME
        app.dependency_overrides[get_database] = lambda: db
        with TestClient(app) as test_client:
            yield test_client
    finally:
        # Must run even when the test body raises: a leaked override would point
        # every later test at this already-dropped database.
        app.dependency_overrides.pop(get_database, None)
        # Restore original environment
        if original_db_name is None:
            os.environ.pop("MONGO_DB_NAME", None)
        else:
            os.environ["MONGO_DB_NAME"] = original_db_name
