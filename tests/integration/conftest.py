import pytest

from tests.integration.support.file_apps import BACKENDS, CLIENT_ID, serve
from tests.integration.support.minio import MINIO
from tests.integration.support.mongo import MONGO
from tests.integration.support.oidc import live_issuer
from tests.integration.support.postgres import POSTGRES


@pytest.fixture(scope="session")
def s3_endpoint():
    with MINIO.endpoint() as endpoint:
        yield endpoint


@pytest.fixture(scope="session")
def mongo_uri():
    with MONGO.endpoint() as uri:
        yield uri


@pytest.fixture(scope="session")
def postgres_uri():
    with POSTGRES.endpoint() as uri:
        yield uri


@pytest.fixture(scope="session")
def issuer():
    with live_issuer(CLIENT_ID) as issuer:
        yield issuer


@pytest.fixture(scope="session", params=BACKENDS, ids=lambda backend: backend.name)
def file_api(request, tmp_path_factory, issuer, s3_endpoint, mongo_uri):
    workdir = tmp_path_factory.mktemp(request.param.name)
    with serve(request.param, workdir, discovery_url=issuer.discovery_url, s3_endpoint=s3_endpoint, mongo_uri=mongo_uri) as api:
        yield api


ROLES = {"alice": "editor", "bob": "editor", "carol": "reader"}


@pytest.fixture(scope="session")
def bearer(issuer):
    """Authorization headers of a named user, whose IdP token carries their role."""
    return lambda name: issuer.bearer(name, email=f"{name}@example.com", role=ROLES[name])


@pytest.fixture
async def client(file_api):
    async with file_api.client() as client:
        yield client
