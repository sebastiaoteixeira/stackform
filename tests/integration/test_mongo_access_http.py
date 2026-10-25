"""The access HTTP suite, served on MongoDB by the dev server and every generated backend."""

import itertools
from uuid import uuid4

import pytest

from tests.unit.support.live_apps import MONGO_SERVERS, mongo
from tests.unit.test_access_http import *  # noqa: F403
from tests.unit.test_access_http import VERSIONS, case_id, serving

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module", params=list(itertools.product(MONGO_SERVERS, VERSIONS)), ids=case_id)
def client(request, tmp_path_factory, mongo_uri):
    server, version = request.param
    name = case_id(request.param)
    datastore = mongo(mongo_uri, f"{name.replace('.', '')}_{uuid4().hex}")
    with serving(server, version, tmp_path_factory.mktemp(name), datastore) as client:
        yield client
