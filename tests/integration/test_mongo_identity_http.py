"""The identity HTTP suite, served on MongoDB by the dev server and every generated backend."""

from uuid import uuid4

import pytest
from pymongo import MongoClient

from tests.unit.support.live_apps import MONGO_SERVERS, mongo, serve, write_spec
from tests.unit.test_identity_http import *  # noqa: F403
from tests.unit.test_identity_http import _SPEC, seed_admin

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module", params=MONGO_SERVERS, ids=lambda server: server.name)
def client(request, tmp_path_factory, mongo_uri):
    server = request.param
    database = f"{server.name}_{uuid4().hex}"
    spec = write_spec(tmp_path_factory.mktemp(server.name), _SPEC, mongo(mongo_uri, database))
    with serve(server, spec) as client, MongoClient(mongo_uri) as store:
        seed_admin(client, lambda email: store[database].users.update_one({"email": email}, {"$set": {"role": "admin"}}))
        yield client
