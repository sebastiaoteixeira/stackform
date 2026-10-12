# File datastores example

Documents keep their records in MongoDB and their files on the local
filesystem; assets keep their files in an S3 bucket. The spec shows every limit
level:

| File | Limit | Comes from |
| --- | --- | --- |
| `document.cover` | 1KB, PNG or JPEG, served inline | the field |
| `document.scan`, `document.attachments` | 2KB, PDF only, at most 2 attachments | the `disk` datastore and the fields |
| `asset.blob` | 3KB, any type | `api.files` |

Start MongoDB and MinIO from the repository root, point the spec at an OIDC
provider whose tokens carry `email` and `role` claims, and run it:

```bash
docker compose up -d mongodb minio
export OIDC_DISCOVERY_URL=https://idp.example/realms/files/.well-known/openid-configuration
stackform run examples/v03/files/spec.yaml
```

The `media` datastore's bucket (`files-demo`, override with `S3_BUCKET`) is
created on startup because its endpoint is local. Files
of the `disk` datastore land in `./data/uploads`; override it with `FILES_DIR`.

Assets are public to create and download:

```bash
curl -X POST http://127.0.0.1:8000/api/assets \
  -F '_data={"label":"Logo"};type=application/json' \
  -F 'blob=@logo.png'

curl -OJ http://127.0.0.1:8000/api/assets/<id>/files/blob
```

Documents need an editor token, and only their owner can read or change them:

```bash
curl -X POST http://127.0.0.1:8000/api/documents \
  -H "Authorization: Bearer $TOKEN" \
  -F '_data={"ownerId":"<your sub>","title":"Report"};type=application/json' \
  -F 'cover=@cover.png' \
  -F 'attachments=@notes.pdf'
```

Generate the same API as a FastAPI app:

```bash
stackform build examples/v03/files/spec.yaml backend --target fastapi --output /tmp/yaml-v03-files
```

The generated app reads its datastores from `FILES_DISK_PATH` and
`FILES_MEDIA_*`; see the [file datastores reference](../../../docs/v0.3/file-datastores.md).
The DRF and raw ASGI targets reject this spec with `BACKEND_FEATURE_UNSUPPORTED`.

`tests/integration/test_files_end_to_end.py` and
`tests/integration/test_files_security.py` run this spec on both `stackform run`
and the generated app, against real MongoDB, MinIO and a live OIDC issuer.
