"""One 0.1 scenario exercised identically against the dev server and a generated app."""

from pymongo import MongoClient

PASSWORD = "correct-horse-battery"

SPEC = """
version: "0.1"
api: {{ pagination: {{ defaultPageSize: 2, maxPageSize: 3 }} }}
mongo: {{ uri: "{uri}", database: {database} }}
security: {{ cors: {{ allowedOrigins: ["https://app.example"], allowCredentials: true }} }}
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
    access: {{ create: public, list: public }}
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
    """Drive pagination, credentialed CORS, API-key auth, credential storage and the role hierarchy; return what each request observed."""
    registered_client = client.post("/api/clients", json={"clientId": "importer", "apiKey": "key-1"}).json()
    keyed = [
        client.post("/api/posts", json={"title": f"post {n}"}, headers={"X-API-Key": "key-1"}).status_code
        for n in range(4)
    ]
    anonymous = client.post("/api/posts", json={"title": "anonymous"}).status_code

    registered_users = [
        client.post("/api/users", json={"email": email, "password": PASSWORD}).json()
        for email in ("admin@example.com", "reader@example.com")
    ]
    with MongoClient(uri) as mongo:
        stored_client = mongo[database]["clients"].find_one({"clientId": "importer"})
        stored_reader = mongo[database]["users"].find_one({"email": "reader@example.com"})
        mongo[database]["users"].update_one({"email": "admin@example.com"}, {"$set": {"_auth.roles": ["admin"]}})

    def users_listing(email: str) -> int:
        token = client.post("/api/users/login", json={"email": email, "password": PASSWORD}).json()["token"]
        return client.get("/api/users", headers={"Authorization": f"Bearer {token}"}).status_code

    return {
        "keyed": keyed,
        "anonymous": anonymous,
        "default_page": len(client.get("/api/posts").json()),
        "clamped_page": len(client.get("/api/posts", params={"limit": 50}).json()),
        "zero_limit": client.get("/api/posts", params={"limit": 0}).status_code,
        "blank_limit": client.get("/api/posts?limit=").status_code,
        "preflight_allows": client.options(
            "/api/posts",
            headers={
                "Origin": "https://app.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "x-api-key, content-type",
            },
        ).headers.get("access-control-allow-headers"),
        "exposed_credentials": sorted(
            {"_auth", "password", "apiKey"}
            & {key for record in [registered_client, *registered_users, *client.get("/api/clients").json()] for key in record}
        ),
        "api_key_stored_in_plaintext": stored_client["apiKey"] == "key-1",
        "default_role": stored_reader["_auth"]["roles"],
        "admin_lists_users": users_listing("admin@example.com"),
        "reader_lists_users": users_listing("reader@example.com"),
    }


EXPECTED = {
    "keyed": [200, 200, 200, 200],
    "anonymous": 401,
    "default_page": 2,
    "clamped_page": 3,
    "zero_limit": 422,
    "blank_limit": 422,
    "preflight_allows": "x-api-key, content-type",
    "exposed_credentials": [],
    "api_key_stored_in_plaintext": False,
    "default_role": "reader",
    "admin_lists_users": 200,
    "reader_lists_users": 403,
}
