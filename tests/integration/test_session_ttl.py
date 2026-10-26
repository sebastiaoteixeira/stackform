"""Rotating sessions issue access tokens of session.ttl seconds from a generated FastAPI app on MongoDB."""

import pytest

from tests.unit.support.generated_apps import run_generated
from tests.unit.support.http_probes import TOKEN_LIFETIME_PROBE
from tests.unit.support.session_spec import ROTATING, mongo, session_spec

pytestmark = pytest.mark.integration


@pytest.mark.parametrize(("session", "lifetime"), ROTATING.items())
def test_generated_fastapi_rotating_token_lifetime(tmp_path, mongo_uri, mongo_database, session, lifetime):
    spec = session_spec(tmp_path, session, store=mongo(mongo_uri, mongo_database))
    database = {"MONGO_URI": mongo_uri, "MONGO_DB": mongo_database}
    assert run_generated(spec, "fastapi", TOKEN_LIFETIME_PROBE, database) == lifetime
