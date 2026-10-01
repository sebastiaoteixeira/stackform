"""Security of every file endpoint, against a live OIDC issuer signing real JWTs, on both backends.

Assertions are on HTTP responses and on what the stores hold, never on implementation details.
"""

import re
from dataclasses import dataclass
from uuid import uuid4

import pytest

from tests.integration.support.file_apps import CLIENT_ID
from tests.integration.support.oidc import live_issuer
from tests.integration.support.payloads import (
    PDF,
    PNG,
    asset,
    content,
    document,
    upload,
)

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class Endpoint:
    """One file endpoint of a stored document, as a request builder."""

    method: str
    path: str
    parts: tuple = ()

    def request(self, client, doc: dict, headers: dict):
        path = self.path.format(id=doc["id"], attachment=doc["attachments"][0]["id"])
        files = {"files": list(self.parts)} if self.parts else {}
        return client.request(self.method, path, headers=headers, **files)


ENDPOINTS = {
    "update": Endpoint("PATCH", "/documents/{id}", (upload("scan", content(PDF), PDF),)),
    "download": Endpoint("GET", "/documents/{id}/files/cover"),
    "array-download": Endpoint("GET", "/documents/{id}/files/attachments/{attachment}"),
    "replace": Endpoint("PUT", "/documents/{id}/files/cover", (upload("cover", content(PNG), PNG),)),
    "delete": Endpoint("DELETE", "/documents/{id}/files/scan"),
    "array-delete": Endpoint("DELETE", "/documents/{id}/files/attachments/{attachment}"),
    "record-delete": Endpoint("DELETE", "/documents/{id}"),
}


@pytest.fixture
def alice(bearer):
    return bearer("alice")


@pytest.fixture
async def stored(client, alice) -> dict:
    """A document owned by alice holding a cover, a scan and one attachment, with their bytes."""
    cover, scan, attachment = content(PNG), content(PDF), content(PDF)
    response = await client.post("/documents", headers=alice, files=document(
        upload("cover", cover, PNG), upload("scan", scan, PDF), upload("attachments", attachment, PDF),
    ))
    assert response.status_code == 200, response.text
    return {**response.json(), "bytes": (cover, scan, attachment)}


def leaks(response, doc: dict) -> bool:
    return any(body in response.content for body in doc["bytes"])


@pytest.mark.parametrize("endpoint", ENDPOINTS)
async def test_every_file_endpoint_requires_a_token(client, file_api, stored, endpoint):
    before = await file_api.contents()

    response = await ENDPOINTS[endpoint].request(client, stored, {})

    assert response.status_code == 401
    assert not leaks(response, stored)
    assert await file_api.contents() == before


@pytest.mark.parametrize("token", ["not-a-jwt", "e30.e30.c2ln"])
async def test_a_malformed_token_is_unauthorised(client, stored, token):
    response = await ENDPOINTS["download"].request(client, stored, {"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    assert not leaks(response, stored)


async def test_a_token_from_another_issuer_is_unauthorised(client, stored):
    with live_issuer(CLIENT_ID) as impostor:
        response = await ENDPOINTS["download"].request(client, stored, impostor.bearer("alice", role="editor"))

    assert response.status_code == 401
    assert not leaks(response, stored)


@pytest.mark.parametrize("user", ["bob", "carol"], ids=["other-editor", "reader"])
@pytest.mark.parametrize("endpoint", ENDPOINTS)
async def test_users_without_access_cannot_touch_another_owners_files(client, file_api, bearer, stored, user, endpoint):
    before = await file_api.contents()

    response = await ENDPOINTS[endpoint].request(client, stored, bearer(user))

    assert response.status_code in {403, 404}
    assert not leaks(response, stored)
    assert await file_api.contents() == before


async def test_a_reader_cannot_create_documents(client, file_api, bearer):
    before = await file_api.contents()

    response = await client.post("/documents", headers=bearer("carol"), files=document(owner="carol"))

    assert response.status_code == 403
    assert await file_api.contents() == before


async def test_documents_cannot_be_created_anonymously(client, file_api):
    before = await file_api.contents()

    assert (await client.post("/documents", files=document())).status_code == 401
    assert await file_api.contents() == before


async def test_public_routes_stay_public_and_only_those(client, file_api):
    blob = content(PDF)
    created = await client.post("/assets", files=asset(upload("blob", blob, PDF)))
    assert created.status_code == 200, created.text
    stored = created.json()
    base = f"/assets/{stored['id']}"
    before = await file_api.contents()

    downloaded = await client.get(f"{base}/files/blob")
    patched = await client.patch(base, files=[upload("blob", content(PDF), PDF)])
    replaced = await client.put(f"{base}/files/blob", files=[upload("blob", content(PDF), PDF)])
    deleted = await client.delete(base)

    assert (downloaded.status_code, downloaded.content) == (200, blob)
    assert (patched.status_code, replaced.status_code, deleted.status_code) == (401, 401, 401)
    assert await file_api.contents() == before


TRAVERSALS = [
    "..%2F..%2Fserver.log",
    "%2e%2e%2f%2e%2e%2fserver.log",
    "..%5C..%5Cserver.log",
    "%2Fetc%2Fpasswd",
]


@pytest.mark.parametrize("file_id", TRAVERSALS)
async def test_a_traversing_file_id_never_escapes_the_store(client, file_api, alice, stored, file_id):
    sentinel = (file_api.disk.parent / "server.log").read_bytes()[:64]

    responses = [
        await client.get(f"/documents/{stored['id']}/files/attachments/{file_id}", headers=alice),
        await client.get(f"/documents/{stored['id']}/files/{file_id}", headers=alice),
    ]

    assert all(response.status_code in {400, 404, 422} for response in responses)
    assert not any(sentinel and sentinel in response.content for response in responses)
    assert b"root:" not in b"".join(response.content for response in responses)


async def test_an_uploaded_filename_with_path_segments_is_stored_inside_the_store(client, file_api, alice):
    before = await file_api.contents()

    response = await client.post(
        "/documents", headers=alice, files=document(upload("cover", content(PNG), PNG, "../../escape.png"))
    )

    assert response.status_code == 200, response.text
    cover = response.json()["cover"]
    assert cover["name"] == "escape.png"
    assert await file_api.contents() - before == {f"documents/{cover['id']}"}
    assert not any(path.name == "escape.png" for path in file_api.disk.parent.rglob("*"))


async def test_a_file_id_from_another_record_is_not_served(client, file_api, alice, stored):
    other = await client.post("/documents", headers=alice, files=document(upload("attachments", content(PDF), PDF)))
    foreign = other.json()["attachments"][0]["id"]
    base = f"/documents/{stored['id']}/files/attachments/{foreign}"

    downloaded = await client.get(base, headers=alice)
    deleted = await client.delete(base, headers=alice)

    assert (downloaded.status_code, deleted.status_code) == (404, 404)
    assert file_api.on_disk("documents", foreign)


async def test_an_unknown_file_id_is_not_found(client, alice, stored):
    response = await client.get(f"/documents/{stored['id']}/files/attachments/{uuid4()}", headers=alice)

    assert response.status_code == 404


SAFE_DISPOSITION = re.compile(r'^(inline|attachment); filename="[\x20-\x21\x23-\x5b\x5d-\x7e]*"; filename\*=UTF-8\'\'[A-Za-z0-9%._~-]*$')


@pytest.mark.parametrize(
    "filename",
    ['evil"; filename="x.exe', "line\r\nX-Injected: yes.png", "tab\tnull\x00.png", "café \u202e.png", "back\\slash.png"],
    ids=["quote", "crlf", "controls", "unicode", "backslash"],
)
async def test_the_download_filename_cannot_inject_headers(client, alice, filename):
    boundary = uuid4().hex
    body = b"".join([
        f'--{boundary}\r\nContent-Disposition: form-data; name="_data"\r\nContent-Type: application/json\r\n\r\n'.encode(),
        b'{"ownerId": "alice", "title": "Report"}\r\n',
        f'--{boundary}\r\nContent-Disposition: form-data; name="cover"; filename="'.encode(),
        filename.encode(),
        b'"\r\nContent-Type: image/png\r\n\r\n',
        content(PNG),
        f"\r\n--{boundary}--\r\n".encode(),
    ])
    headers = {**alice, "Content-Type": f"multipart/form-data; boundary={boundary}"}

    created = await client.post("/documents", headers=headers, content=body)
    assert created.status_code == 200, created.text
    response = await client.get(f"/documents/{created.json()['id']}/files/cover", headers=alice)

    assert response.status_code == 200
    assert SAFE_DISPOSITION.match(response.headers["content-disposition"])
    assert "x-injected" not in response.headers


async def test_every_download_forbids_sniffing_and_active_content(client, alice, stored):
    html = await client.post("/assets", files=asset(upload("blob", b"<html><script>alert(1)</script></html>", "text/html")))
    downloads = [
        await ENDPOINTS[name].request(client, stored, alice) for name in ("download", "array-download")
    ] + [await client.get(f"/assets/{html.json()['id']}/files/blob")]

    assert all(response.status_code == 200 for response in downloads)
    assert all(response.headers["x-content-type-options"] == "nosniff" for response in downloads)
    assert all("sandbox" in response.headers["content-security-policy"] for response in downloads)
    assert downloads[-1].headers["content-disposition"].startswith("attachment;")
