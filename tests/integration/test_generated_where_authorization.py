import compileall
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from yaml_api_generator.generators.backend.context_builder import build_context
from yaml_api_generator.generators.backend.drf.generator import DRFGenerator
from yaml_api_generator.generators.backend.fastapi.generator import FastAPIGenerator
from yaml_api_generator.generators.backend.raw.generator import RawASGIGenerator
from yaml_api_generator.parsers.yaml_parser import ConfigErrors, load_and_generate_ir


_EXAMPLE = Path(__file__).parents[2] / "examples" / "v03" / "where-authorization.yaml"


_SPEC = """
version: "0.3"
api:
  basePath: /api
mongo:
  uri: mongodb://localhost:27017
  database: testdb
entities:
  user:
    type: auth
    auth: { identifier: email, via: password }
    fields:
      id: { type: id }
      email: { type: string }
  organization:
    fields:
      id: { type: id }
      ownerId: { type: string }
  team:
    fields:
      id: { type: id }
      ownerId: { type: string }
  report:
    fields:
      id: { type: id }
      organizationId: { type: string }
      title: { type: string }
repositories:
  users: { entity: user }
  organizations: { entity: organization }
  teams: { entity: team }
  reports: { entity: report }
services:
  reports: { repository: reports }
  audit: { handler: app.handlers.audit }
controllers:
  reports:
    base_path: /reports
    routes:
      list:
        service: reports
        method: GET
        path: /{organizationId}
        access:
          - given:
              principal: identity:user
              organization: organizations where id = $organizationId
            when: organization.ownerId equals principal.sub
          - given:
              principal: identity:user
              organization: teams where id = $organizationId
            when: organization.ownerId equals principal.sub
      get:
        service: reports
        method: GET
        path: /{organizationId}/{id}
        access:
          - given:
              principal: identity:user
              organization: organizations where id = $organizationId
              report: reports
            when: organization.ownerId equals principal.sub and report.organizationId equals organization.id
  audit:
    base_path: /audit
    routes:
      run:
        service: audit
        method: POST
        path: /{organizationId}
        access:
          - given:
              principal: identity:user
              organization: organizations where id = $organizationId
            when: organization.ownerId equals principal.sub
"""


def _context(tmp_path):
    spec_path = tmp_path / "where.yaml"
    spec_path.write_text(textwrap.dedent(_SPEC))
    try:
        return build_context(load_and_generate_ir(spec_path).ir)
    except ConfigErrors as exc:
        pytest.fail("\n".join(f"{error.code}: {error.message}" for error in exc.errors))


def test_compile_context_preserves_complete_where_bindings(tmp_path):
    route = next(
        route
        for route in _context(tmp_path).routes
        if route.collection == "reports" and route.operation == "list"
    )

    first, second = route.access_rules
    assert first.document_bindings[0].name == "organization"
    assert first.document_bindings[0].collection == "organizations"
    assert first.document_bindings[0].where == {
        "id": {"symbol": ["organizationId"]}
    }
    assert second.document_bindings[0].collection == "teams"
    assert route.where_collections == ["organizations", "teams"]


@pytest.mark.parametrize(
    ("generator", "route_path", "handler_path"),
    [
        (FastAPIGenerator(), "routes/reports.py", "routes/_handlers.py"),
        (RawASGIGenerator(), "routes/reports.py", "routes/handlers.py"),
        (DRFGenerator(), "api/views/reports.py", "api/views/_handlers.py"),
    ],
)
def test_generated_where_authorization_compiles(
    generator, route_path, handler_path, tmp_path
):
    output = tmp_path / generator.__class__.__name__
    generator.generate(_context(tmp_path), output)

    assert compileall.compile_dir(str(output), quiet=1)
    source = (output / route_path).read_text()
    assert 'find_one(' in source
    assert "OrganizationsRepository" in source or "get_organizations_repository" in source
    assert "TeamsRepository" in source or "get_teams_repository" in source
    assert source.count("organization is not None") == 3
    handler_source = (output / handler_path).read_text()
    assert "find_one(" in handler_source
    assert "organization is not None" in handler_source


def test_generated_fastapi_enforces_where_per_rule(tmp_path):
    output = tmp_path / "fastapi"
    FastAPIGenerator().generate(_context(tmp_path), output)
    script = textwrap.dedent(
        f"""
        import os
        import sys
        import types

        os.environ["JWT_SECRET"] = "test-secret-at-least-thirty-two-bytes"
        sys.path.insert(0, {str(output)!r})

        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from dependencies.auth import require_principal
        from dependencies.repositories import get_organizations_repository, get_teams_repository
        from dependencies.services import get_reports_service
        from routes._handlers import router as handlers_router
        from routes.reports import router

        class Lookup:
            def __init__(self, document):
                self.document = document
                self.criteria = []

            async def find_one(self, criteria):
                self.criteria.append(criteria)
                return self.document

        class Reports:
            organization_id = "org-1"

            async def list(self, primitives, predicate):
                return [row for row in [{{"id": "r1", "organizationId": "org-1", "title": "visible"}}] if predicate.matches(row)]

            async def get(self, record_id):
                return {{"id": record_id, "organizationId": "org-1", "title": "visible"}}

            async def get_by(self, criteria):
                return {{
                    **criteria,
                    "organizationId": self.organization_id,
                    "title": "visible",
                }}

        principal = {{"sub": "u1", "identity_collection": "users", "roles": []}}
        organizations = Lookup(None)
        teams = Lookup({{"id": "org-1", "ownerId": "u1"}})
        reports = Reports()

        async def current_principal():
            return principal

        app = FastAPI()
        app.include_router(router)
        app.include_router(handlers_router)
        app.dependency_overrides[require_principal] = current_principal
        app.dependency_overrides[get_reports_service] = lambda: reports
        app.dependency_overrides[get_organizations_repository] = lambda: organizations
        app.dependency_overrides[get_teams_repository] = lambda: teams
        client = TestClient(app)

        response = client.get("/reports/org-1")
        assert response.status_code == 200, response.text
        assert response.json()[0]["id"] == "r1"
        assert organizations.criteria == [{{"id": "org-1"}}]
        assert teams.criteria == [{{"id": "org-1"}}]

        teams.document = None
        response = client.get("/reports/org-1")
        assert response.status_code == 403, response.text

        organizations.document = {{"id": "org-1", "ownerId": "u1"}}
        response = client.get("/reports/org-1")
        assert response.status_code == 200, response.text

        response = client.get("/reports/org-1/r1")
        assert response.status_code == 200, response.text

        reports.organization_id = "other"
        response = client.get("/reports/org-1/r1")
        assert response.status_code == 403, response.text
        reports.organization_id = "org-1"

        organizations.document = {{"id": "org-1", "ownerId": "other"}}
        response = client.get("/reports/org-1/r1")
        assert response.status_code == 403, response.text

        application_module = types.ModuleType("app")
        handlers_module = types.ModuleType("app.handlers")

        async def audit(request):
            return {{"authorized": True}}

        handlers_module.audit = audit
        application_module.handlers = handlers_module
        sys.modules["app"] = application_module
        sys.modules["app.handlers"] = handlers_module

        organizations.document = None
        response = client.post("/audit/org-1")
        assert response.status_code == 403, response.text

        organizations.document = {{"id": "org-1", "ownerId": "u1"}}
        response = client.post("/audit/org-1")
        assert response.status_code == 200, response.text
        assert response.json() == {{"authorized": True}}
        """
    )

    subprocess.run([sys.executable, "-c", script], check=True)


def test_where_example_logs_in_and_authorizes_without_identity_list(tmp_path):
    output = tmp_path / "fastapi-example"
    FastAPIGenerator().generate(
        build_context(load_and_generate_ir(_EXAMPLE).ir), output
    )
    script = textwrap.dedent(
        f"""
        import os
        import sys

        os.environ["JWT_SECRET"] = "test-secret-at-least-thirty-two-bytes"
        sys.path.insert(0, {str(output)!r})

        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from dependencies.auth import hash_password
        from dependencies.repositories import get_organizations_repository, get_users_repository
        from dependencies.services import get_reports_service
        from routes.login import router as login_router
        from routes.reports import router as reports_router

        class UsersRepository:
            def __init__(self):
                self.lookups = []
                self.user = {{
                    "id": "u1",
                    "email": "owner@example.test",
                    "_auth": {{"passwordHash": hash_password("correct-password")}},
                }}

            async def find_by(self, field, value):
                self.lookups.append((field, value))
                return self.user if self.user.get(field) == value else None

        class OrganizationsRepository:
            async def find_one(self, criteria):
                assert criteria == {{"id": "org-1"}}
                return {{"id": "org-1", "ownerId": "u1", "name": "Example"}}

        class ReportsService:
            async def list(self, primitives, predicate):
                rows = [{{"id": "report-1", "organizationId": "org-1", "title": "Observed"}}]
                return [row for row in rows if predicate.matches(row)]

        users = UsersRepository()
        app = FastAPI()
        app.include_router(login_router)
        app.include_router(reports_router)
        app.dependency_overrides[get_users_repository] = lambda: users
        app.dependency_overrides[get_organizations_repository] = OrganizationsRepository
        app.dependency_overrides[get_reports_service] = ReportsService
        client = TestClient(app)

        login = client.post(
            "/users/login",
            json={{"email": "owner@example.test", "password": "correct-password"}},
        )
        assert login.status_code == 200, login.text
        token = login.json()["token"]

        reports = client.get(
            "/organizations/org-1/reports",
            headers={{"Authorization": f"Bearer {{token}}"}},
        )
        assert reports.status_code == 200, reports.text
        assert reports.json()[0]["title"] == "Observed"
        assert users.lookups == [("email", "owner@example.test"), ("id", "u1")]
        """
    )

    subprocess.run([sys.executable, "-c", script], check=True)


def test_generated_raw_asgi_enforces_where_per_rule(tmp_path):
    output = tmp_path / "raw"
    RawASGIGenerator().generate(_context(tmp_path), output)
    script = textwrap.dedent(
        f"""
        import asyncio
        import os
        import sys
        import types

        os.environ["JWT_SECRET"] = "test-secret-at-least-thirty-two-bytes"
        sys.path.insert(0, {str(output)!r})

        import routes.reports as routes
        import routes.handlers as handlers

        class Cursor:
            def __init__(self, documents):
                self.documents = documents

            async def to_list(self, length=None):
                return list(self.documents)

        class Collection:
            def __init__(self, documents):
                self.documents = documents
                self.criteria = []

            async def find_one(self, criteria):
                self.criteria.append(criteria)
                alternatives = criteria.get("$or")
                if alternatives is not None:
                    return next(
                        (
                            doc
                            for doc in self.documents
                            if any(
                                all(doc.get(k) == v for k, v in alternative.items())
                                for alternative in alternatives
                            )
                        ),
                        None,
                    )
                return next(
                    (doc for doc in self.documents if all(doc.get(k) == v for k, v in criteria.items())),
                    None,
                )

            def find(self, criteria):
                return Cursor(self.documents)

        class Database(dict):
            def __getitem__(self, key):
                return dict.__getitem__(self, key)

        db = Database(
            organizations=Collection([]),
            teams=Collection([{{"id": "org-1", "ownerId": "u1"}}]),
            reports=Collection([{{"id": "r1", "organizationId": "org-1", "title": "visible"}}]),
        )

        async def principal(headers, database):
            return {{"sub": "u1", "identity_collection": "users", "roles": []}}

        routes.resolve_principal = principal
        handlers.resolve_principal = principal

        application_module = types.ModuleType("app")
        handlers_module = types.ModuleType("app.handlers")

        async def audit(request):
            return {{"authorized": True}}

        handlers_module.audit = audit
        application_module.handlers = handlers_module
        sys.modules["app"] = application_module
        sys.modules["app.handlers"] = handlers_module

        async def verify():
            status, body = await routes.handle_get_reports__organizationId_(
                {{"organizationId": "org-1"}}, None, {{}}, db
            )
            assert status == 200, body
            assert body[0]["id"] == "r1"
            assert db["organizations"].criteria == [{{"id": "org-1"}}]
            assert db["teams"].criteria == [{{"id": "org-1"}}]

            db["organizations"].documents = []
            status, body = await handlers.handle_post_audit__organizationId_(
                {{"organizationId": "org-1"}}, None, {{}}, db
            )
            assert status == 403, body

            db["organizations"].documents = [{{"id": "org-1", "ownerId": "u1"}}]
            status, body = await handlers.handle_post_audit__organizationId_(
                {{"organizationId": "org-1"}}, None, {{}}, db
            )
            assert status == 200, body
            assert body == {{"authorized": True}}

            status, body = await routes.handle_get_reports__organizationId___id_(
                {{"organizationId": "org-1", "id": "r1"}}, None, {{}}, db
            )
            assert status == 200, body
            assert body["organizationId"] == "org-1"

            db["organizations"].documents = [{{"id": "org-1", "ownerId": "other"}}]
            status, body = await routes.handle_get_reports__organizationId___id_(
                {{"organizationId": "org-1", "id": "r1"}}, None, {{}}, db
            )
            assert status == 403, body

            db["organizations"].documents = []
            db["teams"].documents = []
            status, body = await routes.handle_get_reports__organizationId_(
                {{"organizationId": "org-1"}}, None, {{}}, db
            )
            assert status == 403, body

            db["organizations"].documents = [{{"id": "org-1", "ownerId": "u1"}}]
            status, body = await routes.handle_get_reports__organizationId_(
                {{"organizationId": "org-1"}}, None, {{}}, db
            )
            assert status == 200, body

        asyncio.run(verify())
        """
    )

    subprocess.run([sys.executable, "-c", script], check=True)


def test_generated_drf_enforces_where_per_rule(tmp_path):
    output = tmp_path / "drf"
    DRFGenerator().generate(_context(tmp_path), output)
    script = textwrap.dedent(
        f"""
        import asyncio
        import os
        import sys
        import types
        from types import SimpleNamespace

        os.environ["JWT_SECRET"] = "test-secret-at-least-thirty-two-bytes"
        sys.path.insert(0, {str(output)!r})

        rest_framework = types.ModuleType("rest_framework")
        rest_status = SimpleNamespace(
            HTTP_200_OK=200,
            HTTP_201_CREATED=201,
            HTTP_401_UNAUTHORIZED=401,
            HTTP_403_FORBIDDEN=403,
            HTTP_404_NOT_FOUND=404,
            HTTP_409_CONFLICT=409,
            HTTP_422_UNPROCESSABLE_ENTITY=422,
        )
        response_module = types.ModuleType("rest_framework.response")
        adrf_module = types.ModuleType("adrf")
        views_module = types.ModuleType("adrf.views")
        spectacular_module = types.ModuleType("drf_spectacular")
        spectacular_utils = types.ModuleType("drf_spectacular.utils")
        auth_module = types.ModuleType("api.authentication.auth")
        mongodb_module = types.ModuleType("api.authentication.mongodb")

        class Response:
            def __init__(self, data, status=200):
                self.data = data
                self.status_code = status

        class APIView:
            pass

        def extend_schema(**kwargs):
            return lambda function: function

        rest_framework.status = rest_status
        response_module.Response = Response
        views_module.APIView = APIView
        spectacular_utils.extend_schema = extend_schema
        auth_module._principal_has_role = lambda principal, role: role in principal.get("roles", [])
        auth_module.ROLE_HIERARCHIES = {{}}

        async def anonymous(headers, database):
            return None

        auth_module.resolve_principal = anonymous
        auth_module.hash_password = lambda password: password
        mongodb_module.get_database = lambda: None
        sys.modules.update({{
            "rest_framework": rest_framework,
            "rest_framework.response": response_module,
            "adrf": adrf_module,
            "adrf.views": views_module,
            "drf_spectacular": spectacular_module,
            "drf_spectacular.utils": spectacular_utils,
            "api.authentication.auth": auth_module,
            "api.authentication.mongodb": mongodb_module,
        }})
        import api.views.reports as views
        import api.views._handlers as handler_views

        class Cursor:
            def __init__(self, documents):
                self.documents = documents

            async def to_list(self, length=None):
                return list(self.documents)

        class Collection:
            def __init__(self, documents):
                self.documents = documents

            async def find_one(self, criteria):
                alternatives = criteria.get("$or")
                if alternatives is not None:
                    return next(
                        (
                            doc
                            for doc in self.documents
                            if any(
                                all(doc.get(k) == v for k, v in alternative.items())
                                for alternative in alternatives
                            )
                        ),
                        None,
                    )
                return next(
                    (doc for doc in self.documents if all(doc.get(k) == v for k, v in criteria.items())),
                    None,
                )

            def find(self, criteria):
                return Cursor(self.documents)

        db = {{
            "organizations": Collection([]),
            "teams": Collection([{{"id": "org-1", "ownerId": "u1"}}]),
            "reports": Collection([{{"id": "r1", "organizationId": "org-1", "title": "visible"}}]),
        }}
        views.get_database = lambda: db
        async def member(headers, database):
            return {{"sub": "u1", "identity_collection": "users", "roles": []}}

        views.resolve_principal = member
        handler_views.get_database = lambda: db
        handler_views.resolve_principal = principal
        request = SimpleNamespace(data={{}}, body=b"", query_params={{}}, headers={{}}, COOKIES={{}})

        application_module = types.ModuleType("app")
        handlers_module = types.ModuleType("app.handlers")

        async def audit(request):
            return {{"authorized": True}}

        handlers_module.audit = audit
        application_module.handlers = handlers_module
        sys.modules["app"] = application_module
        sys.modules["app.handlers"] = handlers_module

        async def verify():
            response = await views.ReportsByOrganizationIdView().get(
                request, organizationId="org-1"
            )
            assert response.status_code == 200, response.data
            assert response.data[0]["id"] == "r1"

            db["organizations"].documents = []
            response = await handler_views.AuditByOrganizationIdView().post(
                request, organizationId="org-1"
            )
            assert response.status_code == 403, response.data

            db["organizations"].documents = [{{"id": "org-1", "ownerId": "u1"}}]
            response = await handler_views.AuditByOrganizationIdView().post(
                request, organizationId="org-1"
            )
            assert response.status_code == 200, response.data
            assert response.data == {{"authorized": True}}

            response = await views.ReportsByOrganizationIdByIdView().get(
                request, organizationId="org-1", id="r1"
            )
            assert response.status_code == 200, response.data
            assert response.data["organizationId"] == "org-1"

            db["organizations"].documents = [{{"id": "org-1", "ownerId": "other"}}]
            response = await views.ReportsByOrganizationIdByIdView().get(
                request, organizationId="org-1", id="r1"
            )
            assert response.status_code == 403, response.data

            db["organizations"].documents = []
            db["teams"].documents = []
            response = await views.ReportsByOrganizationIdView().get(
                request, organizationId="org-1"
            )
            assert response.status_code == 403, response.data

            db["organizations"].documents = [{{"id": "org-1", "ownerId": "u1"}}]
            response = await views.ReportsByOrganizationIdView().get(
                request, organizationId="org-1"
            )
            assert response.status_code == 200, response.data

        asyncio.run(verify())
        """
    )

    subprocess.run([sys.executable, "-c", script], check=True)
