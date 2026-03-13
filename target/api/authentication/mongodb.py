import os

from pymongo import MongoClient


_client: MongoClient | None = None
_db = None


def connect_db() -> None:
    global _client, _db
    uri = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
    database = os.environ.get("MONGO_DB", "yaml_api")
    _client = MongoClient(uri)
    _db = _client[database]


def close_db() -> None:
    global _client, _db
    if _client is not None:
        _client.close()
        _client = None
        _db = None


def get_database():
    if _db is None:
        raise RuntimeError("Database not connected")
    return _db
