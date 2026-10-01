"""The files example over real HTTP, on `yaml-api run` and on its generated FastAPI app.

Records live in MongoDB, documents' files on the filesystem and assets' files in MinIO;
every assertion is on HTTP responses or on what the stores hold.
"""

import pytest

from tests.integration.support.payloads import (
    JPEG,
    KB,
    PDF,
    PNG,
    asset,
    content,
    document,
    record,
    upload,
)

pytestmark = pytest.mark.integration

CREATES = {"/documents": document, "/assets": asset}


@pytest.fixture
def alice(bearer):
    return bearer("alice")


def created(response) -> dict:
    assert response.status_code == 200, response.text
    return response.json()


async def download(client, headers, path: str):
    response = await client.get(path, headers=headers)
    assert response.status_code == 200, response.text
    return response


async def test_create_stores_every_file_and_serves_its_bytes(client, file_api, alice):
    cover, scan, attachments = content(PNG), content(PDF), [content(PDF), content(PDF)]
    doc = created(await client.post("/documents", headers=alice, files=document(
        upload("cover", cover, PNG, "cover.png"),
        upload("scan", scan, PDF, "scan.pdf"),
        *(upload("attachments", body, PDF, f"part-{index}.pdf") for index, body in enumerate(attachments)),
    )))
    base = f"/documents/{doc['id']}/files"

    served_cover = await download(client, alice, f"{base}/cover")
    served_scan = await download(client, alice, f"{base}/scan")
    served_attachments = [
        await download(client, alice, f"{base}/attachments/{item['id']}") for item in doc["attachments"]
    ]

    assert (served_cover.content, served_scan.content) == (cover, scan)
    assert [response.content for response in served_attachments] == attachments
    assert served_cover.headers["content-type"] == PNG
    assert served_cover.headers["content-disposition"] == "inline; filename=\"cover.png\"; filename*=UTF-8''cover.png"
    assert served_scan.headers["content-disposition"] == "attachment; filename=\"scan.pdf\"; filename*=UTF-8''scan.pdf"
    assert [item["name"] for item in doc["attachments"]] == ["part-0.pdf", "part-1.pdf"]
    stored = [doc["cover"]["id"], doc["scan"]["id"], *(item["id"] for item in doc["attachments"])]
    assert all(file_api.on_disk("documents", file_id) for file_id in stored)


async def test_s3_files_live_in_the_bucket(client, file_api):
    blob = content(PDF)
    stored = created(await client.post("/assets", files=asset(upload("blob", blob, PDF, "a.pdf"))))

    served = await download(client, {}, f"/assets/{stored['id']}/files/blob")

    assert served.content == blob
    assert served.headers["content-disposition"].startswith("attachment; filename=\"a.pdf\"")
    assert await file_api.in_bucket("assets", stored["blob"]["id"])
    assert not file_api.on_disk("assets", stored["blob"]["id"])


async def test_replace_swaps_the_bytes_and_drops_the_old_file(client, file_api, alice):
    doc = created(await client.post("/documents", headers=alice, files=document(
        upload("attachments", content(PDF), PDF), upload("attachments", content(PDF), PDF),
    )))
    base = f"/documents/{doc['id']}/files"
    cover, item = content(JPEG), content(PDF)
    first, second = doc["attachments"]

    replaced = created(await client.put(f"{base}/cover", headers=alice, files=[upload("cover", cover, JPEG, "new.jpg")]))
    swapped = created(await client.put(
        f"{base}/attachments/{first['id']}", headers=alice, files=[upload("attachments", item, PDF, "swap.pdf")]
    ))

    assert replaced["cover"]["name"] == "new.jpg"
    assert (await download(client, alice, f"{base}/cover")).content == cover
    assert [entry["name"] for entry in swapped["attachments"]] == ["swap.pdf", second["name"]]
    assert (await download(client, alice, f"{base}/attachments/{swapped['attachments'][0]['id']}")).content == item
    assert not file_api.on_disk("documents", doc["cover"]["id"])
    assert not file_api.on_disk("documents", first["id"])
    assert file_api.on_disk("documents", second["id"])


async def test_update_with_a_file_part_replaces_that_file(client, file_api, alice):
    doc = created(await client.post("/documents", headers=alice, files=document(upload("scan", content(PDF), PDF))))
    scan = content(PDF)

    updated = created(await client.patch(
        f"/documents/{doc['id']}", headers=alice, files=[record(title="Renamed"), upload("scan", scan, PDF)]
    ))

    assert updated["title"] == "Renamed"
    assert updated["cover"] == doc["cover"]
    assert (await download(client, alice, f"/documents/{doc['id']}/files/scan")).content == scan
    assert not file_api.on_disk("documents", doc["scan"]["id"])


async def test_delete_removes_a_file_and_an_array_item(client, file_api, alice):
    doc = created(await client.post("/documents", headers=alice, files=document(
        upload("scan", content(PDF), PDF), upload("attachments", content(PDF), PDF), upload("attachments", content(PDF), PDF),
    )))
    base = f"/documents/{doc['id']}/files"
    first, second = doc["attachments"]

    without_scan = created(await client.delete(f"{base}/scan", headers=alice))
    without_first = created(await client.delete(f"{base}/attachments/{first['id']}", headers=alice))

    assert without_scan["scan"] is None
    assert [item["id"] for item in without_first["attachments"]] == [second["id"]]
    assert (await client.get(f"{base}/scan", headers=alice)).status_code == 404
    assert (await client.get(f"{base}/attachments/{first['id']}", headers=alice)).status_code == 404
    assert not file_api.on_disk("documents", doc["scan"]["id"])
    assert not file_api.on_disk("documents", first["id"])


async def test_a_required_file_cannot_be_deleted(client, file_api, alice):
    doc = created(await client.post("/documents", headers=alice, files=document()))

    assert (await client.delete(f"/documents/{doc['id']}/files/cover", headers=alice)).status_code == 422
    assert file_api.on_disk("documents", doc["cover"]["id"])


async def test_record_delete_removes_its_files_from_disk(client, file_api, alice):
    doc = created(await client.post("/documents", headers=alice, files=document(upload("attachments", content(PDF), PDF))))
    stored = [doc["cover"]["id"], doc["attachments"][0]["id"]]

    assert (await client.delete(f"/documents/{doc['id']}", headers=alice)).status_code == 200

    assert not any(file_api.on_disk("documents", file_id) for file_id in stored)
    assert (await client.get(f"/documents/{doc['id']}/files/cover", headers=alice)).status_code == 404


async def test_record_delete_removes_its_object_from_the_bucket(client, file_api, alice):
    stored = created(await client.post("/assets", files=asset(upload("blob", content(PNG), PNG))))

    assert (await client.delete(f"/assets/{stored['id']}", headers=alice)).status_code == 200

    assert not await file_api.in_bucket("assets", stored["blob"]["id"])


async def test_an_array_beyond_max_items_is_rejected_without_storing(client, file_api, alice):
    before = await file_api.contents()

    response = await client.post(
        "/documents", headers=alice, files=document(*(upload("attachments", content(PDF), PDF) for _ in range(3)))
    )

    assert response.status_code == 422
    assert await file_api.contents() == before


LIMITS = {
    "field": ("/documents", "cover", PNG, 1 * KB),
    "datastore": ("/documents", "scan", PDF, 2 * KB),
    "global": ("/assets", "blob", PDF, 3 * KB),
}


@pytest.mark.parametrize("level", LIMITS)
async def test_each_limit_level_admits_its_size_and_rejects_one_byte_more(client, file_api, alice, level):
    path, field, content_type, limit = LIMITS[level]
    sized = lambda size: CREATES[path](upload(field, content(content_type, size), content_type))

    fits = await client.post(path, headers=alice, files=sized(limit))
    before = await file_api.contents()
    too_large = await client.post(path, headers=alice, files=sized(limit + 1))

    assert created(fits)[field]["size"] == limit
    assert too_large.status_code == 413
    assert await file_api.contents() == before


@pytest.mark.parametrize(
    ("field", "body", "claimed"),
    [("cover", content(PDF), PNG), ("scan", content(PNG), PDF)],
    ids=["pdf-claimed-as-png", "png-claimed-as-pdf"],
)
async def test_content_that_does_not_match_the_allowed_types_is_rejected(client, file_api, alice, field, body, claimed):
    before = await file_api.contents()

    response = await client.post("/documents", headers=alice, files=document(upload(field, body, claimed)))

    assert response.status_code == 415
    assert await file_api.contents() == before


@pytest.mark.parametrize(
    ("path", "fields"),
    [("/documents", {"ownerId": "alice", "title": "No cover"}), ("/assets", {"label": "No blob"})],
    ids=["documents", "assets"],
)
async def test_a_missing_required_file_is_rejected(client, file_api, alice, path, fields):
    before = await file_api.contents()

    assert (await client.post(path, headers=alice, files=[record(**fields)])).status_code == 422
    assert (await client.post(path, headers=alice, json=fields)).status_code == 422
    assert await file_api.contents() == before


async def test_access_rules_apply_to_file_routes(client, bearer, alice):
    doc = created(await client.post("/documents", headers=alice, files=document()))
    cover = f"/documents/{doc['id']}/files/cover"

    assert (await client.post("/documents", headers=bearer("carol"), files=document(owner="carol"))).status_code == 403
    assert (await client.get(cover, headers=bearer("bob"))).status_code == 403
    assert (await client.get(cover, headers=alice)).status_code == 200
