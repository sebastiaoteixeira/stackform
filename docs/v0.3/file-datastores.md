---
title: File datastores
description: Store uploaded file bytes on the filesystem or in S3-compatible storage, bind repositories to them, and configure them through environment variables.
---

A record datastore (`mongodb`, `postgres`) holds records. A **file datastore**
holds the bytes of uploaded files. Records only keep each file's metadata, so a
`document` row in PostgreSQL can point at a PDF that lives in an S3 bucket.

File datastores are v0.3 behavior. They are implemented by `stackform run` and by
the generated FastAPI backend. The DRF and raw ASGI targets, and
`stackform run --raw`, reject specs with file fields (see
[Supported targets](#supported-targets)).

## Declaring file datastores

File datastores are declared in `datastores:` next to the record datastores:

```yaml
datastores:
  main:
    type: postgres
    dsn: ${DATABASE_URL:-postgresql+asyncpg://localhost:5432/app}
  disk:
    type: filesystem
    path: ${FILES_DIR:-./data/uploads}
    files: { maxSize: 5MB }
  media:
    type: s3
    bucket: ${S3_BUCKET:-media}
    endpoint: ${S3_ENDPOINT:-http://localhost:9000}
    region: us-east-1
    accessKey: ${S3_ACCESS_KEY:-minioadmin}
    secretKey: ${S3_SECRET_KEY:-minioadmin}
    prefix: uploads/
    default: true
    files: { types: [image/*] }
```

Every value accepts `${VAR}` and `${VAR:-default}` interpolation, like the rest
of the spec. Keep credentials in environment variables.

### `type: filesystem`

| Field | Type | Description |
| --- | --- | --- |
| `path` | string | Required. Directory that holds the files. It is created on startup. |
| `files` | object | Optional limits for files in this datastore (see [File limits](file-fields.md#limits-and-precedence)). |
| `default` | boolean | Optional. The default file datastore. |

Files are written to a temporary file inside `path/.tmp` and moved into place
only once the upload has passed every check, so a rejected or interrupted upload
never leaves a partial file behind.

### `type: s3`

Any S3-compatible service works, including AWS S3 and MinIO.

| Field | Type | Description |
| --- | --- | --- |
| `bucket` | string | Required. Bucket name. |
| `endpoint` | string | Optional. Service URL, for example `http://localhost:9000` for MinIO. Omit it for AWS. |
| `region` | string | Optional. Region name. |
| `accessKey` / `secretKey` | string | Optional. Credentials. Omitted credentials fall back to the standard AWS credential chain. |
| `prefix` | string | Optional. Key prefix prepended to every object, for example `uploads/`. |
| `files` | object | Optional limits for files in this datastore. |
| `default` | boolean | Optional. The default file datastore. |

When `endpoint` points at `localhost` or `127.0.0.1`, the app treats it as a
development MinIO and creates the bucket on startup if it is missing. Remote
endpoints never get a bucket created for them.

## Two families, two defaults

Datastores form two independent families:

| Family | Types | Used by |
| --- | --- | --- |
| Record | `mongodb`, `mongo`, `postgres`, `postgresql` | `repositories.<name>.datastore` |
| File | `filesystem`, `s3` | `repositories.<name>.files` |

Each family picks its own default, with the same rules:

- The entry marked `default: true` is the default of its family.
- A family with a single entry uses it as the default automatically.
- Two `default: true` entries in the same family is an error.
- Several entries and no default is an error only when something needs the default.

Adding a file datastore never changes which record datastore is the default.

## Binding a repository

A repository stores its records in `datastore:` and its files in `files:`. Both
fall back to their family's default.

```yaml
repositories:
  documents: { entity: document }                   # default record and file datastores
  assets: { entity: asset, datastore: main, files: media }
```

`files:` matters only when the entity has [file fields](file-fields.md). An
entity without file fields ignores it.

## Environment variables

### `stackform run`

`stackform run` reads the spec values as written, after interpolation. Use
`${VAR:-default}` in the spec to make them configurable, as in the example
above.

### Generated FastAPI backend

Every file datastore used by an entity becomes a group of settings in the
generated `settings.py`. `<NAME>` is the datastore name, uppercased, with
non-identifier characters replaced by `_` (`disk` gives `FILES_DISK_PATH`).

| Variable | Datastore | Default |
| --- | --- | --- |
| `FILES_<NAME>_PATH` | filesystem | The spec's `path` |
| `FILES_<NAME>_BUCKET` | s3 | The spec's `bucket` |
| `FILES_<NAME>_ENDPOINT` | s3 | The spec's `endpoint`; empty means AWS |
| `FILES_<NAME>_REGION` | s3 | The spec's `region` |
| `FILES_<NAME>_PREFIX` | s3 | The spec's `prefix` |
| `FILES_<NAME>_ACCESS_KEY` | s3 | Secret. Only written to the generated `.env` |
| `FILES_<NAME>_SECRET_KEY` | s3 | Secret. Only written to the generated `.env` |
| `FILES_<NAME>_CREATE_BUCKET` | s3 | `true` for a local endpoint, otherwise `false` |

The generated `requirements.txt` adds `python-multipart`, `puremagic` and
`anyio` when the spec has file fields, plus `aiobotocore` when an S3 datastore
is used.

### Docker deploy

`stackform build ... deploy` wires file datastores into `docker-compose.yml`:

- **filesystem:** a named volume `files_<name>` is mounted in the app at
  `/data/files/<name>`, and `FILES_<NAME>_PATH` points at it.
- **s3 with a local endpoint:** a `minio` service is added (`minio-<name>` when
  there are several), with its own data volume. Its root user and password come
  from `accessKey`/`secretKey` (default `minioadmin`). The app depends on it,
  reaches it at `http://<service>:9000` and creates the bucket on startup.
- **s3 with a remote endpoint:** only the environment variables are set.

systemd deploys receive `FILES_<NAME>_PATH` for filesystem datastores.

## Supported targets

| Target | File datastores |
| --- | --- |
| `stackform run` | Yes |
| Generated FastAPI | Yes |
| `stackform run --raw`, DRF, raw ASGI | No: `BACKEND_FEATURE_UNSUPPORTED`, "file fields are not supported by target '<target>'" |

## Diagnostics

| Code | Condition |
| --- | --- |
| `DATASTORE_FILE_MISSING_PATH` | `type: filesystem` without `path`. |
| `DATASTORE_FILE_MISSING_BUCKET` | `type: s3` without `bucket`. |
| `FILE_DATASTORE_MULTIPLE_DEFAULTS` | Two file datastores are marked `default: true`. |
| `FILE_DATASTORE_NO_DEFAULT` | Several file datastores, none is the default, and a repository with file fields omits `files:`. |
| `FILE_DATASTORE_REQUIRED` | An entity has file fields but the spec declares no file datastore. |
| `FILE_DATASTORE_UNKNOWN_REFERENCE` | `repositories.<name>.files` names no datastore. |
| `DATASTORE_NOT_FILE` | `repositories.<name>.files` names a record datastore. |
| `DATASTORE_NOT_RECORD` | `repositories.<name>.datastore` names a file datastore. |
| `FILE_SIZE_INVALID` | A `maxSize` is not a positive size. |

The JSON schema already requires `path` and `bucket`, so a spec missing them is
usually reported as `SCHEMA_VALIDATION_ERROR` first.

## See also

- [File fields](file-fields.md): the `file` field type and its limits
- [File endpoints](file-endpoints.md): uploads, downloads and access
- `examples/v03/files`: a complete spec with both datastore types
