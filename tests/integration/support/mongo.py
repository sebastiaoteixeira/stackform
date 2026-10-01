"""A real MongoDB: YAML_API_TEST_MONGO_URI when set, otherwise a throwaway container."""

from pymongo import MongoClient
from pymongo.errors import PyMongoError

from .docker import Service


def _pingable(uri: str) -> bool:
    try:
        with MongoClient(uri, serverSelectionTimeoutMS=500) as client:
            client.admin.command("ping")
        return True
    except PyMongoError:
        return False


MONGO = Service(
    name="mongo",
    image="mongo:7",
    port=27017,
    scheme="mongodb",
    override="YAML_API_TEST_MONGO_URI",
    ready=_pingable,
)
