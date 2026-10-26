"""The bind HTTP suite, served on MongoDB by the dev server and every generated backend."""

from uuid import uuid4

import pytest

from tests.unit.support.live_apps import MONGO_SERVERS, mongo, serve, write_spec
from tests.unit.test_bind_http import *  # noqa: F403
from tests.unit.test_bind_http import SPEC

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module", params=MONGO_SERVERS, ids=lambda server: server.name)
def client(request, tmp_path_factory, mongo_uri):
    server = request.param
    spec = write_spec(tmp_path_factory.mktemp(server.name), SPEC, mongo(mongo_uri, f"{server.name}_{uuid4().hex}"))
    with serve(server, spec) as client:
        yield client
