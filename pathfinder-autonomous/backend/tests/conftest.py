import os

import pytest
from fastapi.testclient import TestClient
from pymongo import MongoClient

from app.db import ensure_indexes, get_database
from app.main import app

TEST_MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
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
    app.dependency_overrides[get_database] = lambda: db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
