"""One 0.1 scenario exercised identically against the dev server and a generated app."""

from pymongo import MongoClient

PASSWORD = "correct-horse-battery"

SPEC = """
version: "0.1"
api: {{ pagination: {{ defaultPageSize: 2, maxPageSize: 3 }} }}
mongo: {{ uri: "{uri}", database: {database} }}
collections:
  users:
    type: auth
    auth: {{ identifier: email, via: password }}
    roles: {{ values: [reader, editor, admin], default: reader, hierarchy: {{ admin: [editor], editor: [reader] }} }}
    access: {{ create: public, list: "users:editor" }}
    fields:
      id: {{ type: id }}
      email: {{ type: string, required: true, unique: true }}
  clients:
    type: auth
    auth: {{ identifier: clientId, via: [apiKey] }}
    access: {{ create: public }}
    fields:
      id: {{ type: id }}
      clientId: {{ type: string, required: true, unique: true }}
      apiKey: {{ type: string, required: true }}
  posts:
    access: {{ list: public, create: "clients:*" }}
    fields:
      id: {{ type: id }}
      title: {{ type: string }}
"""


def exercise(client, uri: str, database: str) -> dict:
    """Drive pagination, API-key auth and the role hierarchy; return what each request observed."""
    client.post("/api/clients", json={"clientId": "importer", "apiKey": "key-1"})
    keyed = [
        client.post("/api/posts", json={"title": f"post {n}"}, headers={"X-API-Key": "key-1"}).status_code
        for n in range(4)
    ]
    anonymous = client.post("/api/posts", json={"title": "anonymous"}).status_code

    for email in ("admin@example.com", "reader@example.com"):
        client.post("/api/users", json={"email": email, "password": PASSWORD})
    with MongoClient(uri) as mongo:
        mongo[database]["users"].update_one({"email": "admin@example.com"}, {"$set": {"_auth.roles": ["admin"]}})

    def users_listing(email: str) -> int:
        token = client.post("/api/users/login", json={"email": email, "password": PASSWORD}).json()["token"]
        return client.get("/api/users", headers={"Authorization": f"Bearer {token}"}).status_code

    return {
        "keyed": keyed,
        "anonymous": anonymous,
        "default_page": len(client.get("/api/posts").json()),
        "clamped_page": len(client.get("/api/posts", params={"limit": 50}).json()),
        "admin_lists_users": users_listing("admin@example.com"),
        "reader_lists_users": users_listing("reader@example.com"),
    }


EXPECTED = {
    "keyed": [200, 200, 200, 200],
    "anonymous": 401,
    "default_page": 2,
    "clamped_page": 3,
    "admin_lists_users": 200,
    "reader_lists_users": 403,
}
