---
title: File endpoints
description: How records with file fields are created and updated with multipart requests, the download, replace and delete endpoints derived for each file field, and which access rules apply.
---

An entity with [file fields](file-fields.md) needs no extra controller keys. Its
existing routes accept uploads, and every file field gets download, replace and
delete endpoints derived from the controller's `get` and `update` routes.

## Creating and updating records

`create` (POST) and `update` (PATCH) routes of an entity with file fields accept
`multipart/form-data`:

- The record's other fields go in **one JSON part named `_data`**. It is
  validated exactly like a JSON body; for an update, only the fields it sets
  change.
- Each file is a part named after its field. An array of files repeats the part
  once per file.

```bash
curl -X POST http://127.0.0.1:8000/api/documents \
  -H "Authorization: Bearer $TOKEN" \
  -F '_data={"ownerId":"alice","title":"Report"};type=application/json' \
  -F 'cover=@cover.png;type=image/png' \
  -F 'attachments=@part-1.pdf' \
  -F 'attachments=@part-2.pdf'
```

The response is the stored record, with each file field holding its
[metadata](file-fields.md#stored-value).

- A PATCH with a part for a file field replaces that field. For an array, the
  parts sent become the whole array. Fields without a part are kept.
- Plain `application/json` is still accepted, but it cannot carry file fields
  (`422`). A JSON create of an entity with a required file fails with `422`.
- `replace` (PUT) routes stay JSON only. They keep the record's stored files.
- Entities without file fields are unchanged: JSON only.

## Derived file endpoints

For a controller with `get` at `P` (for example `/documents/{id}`) and `update`
at the same path, each file field `f` gets:

| Endpoint | Single file | Array of files | Access of |
| --- | --- | --- | --- |
| Download | `GET P/files/f` | `GET P/files/f/{fileId}` | `get` |
| Replace | `PUT P/files/f` | `PUT P/files/f` (whole array), `PUT P/files/f/{fileId}` (one item) | `update` |
| Delete | `DELETE P/files/f` | `DELETE P/files/f/{fileId}` | `update` |

- Replace and delete endpoints are not derived for `readonly` fields, nor when
  the controller has no `update` route. Download is not derived without a `get`
  route.
- Replace takes a multipart body with parts named `f`: exactly one for a single
  file or an item, 1 to `maxItems` for a whole array. Replacing an item keeps its
  position in the array.
- Replace and delete return the updated record. Download streams the bytes.
- A derived endpoint that collides with a declared route is `FILE_ROUTE_CONFLICT`.

### Download responses

A download is sent with:

| Header | Value |
| --- | --- |
| `Content-Type` | The detected content type |
| `Content-Length` | The file size |
| `Content-Disposition` | `inline` or `attachment` (see [Disposition](file-fields.md#disposition)), with `filename="<ascii>"; filename*=UTF-8''<encoded>` |
| `ETag` | The file's SHA-256 |
| `X-Content-Type-Options` | `nosniff` |
| `Content-Security-Policy` | `default-src 'none'; sandbox` |

## Access

A file endpoint applies **exactly** the access of the route it comes from:
download uses the `get` route's access, replace and delete use the `update`
route's. That includes roles, `when:` rules on the fetched record, `where`
bindings and denial reasons. A user who cannot read a record cannot download its
files, and a user who cannot update it cannot change them.

```yaml
controllers:
  documents:
    base_path: /documents
    routes:
      get:
        service: documents
        method: GET
        path: /{id}
        access:
          - given: { principal: "identity:user", document: documents }
            when: document.ownerId equals principal.sub
          - then: deny
```

Here only the owner can call `GET /documents/{id}/files/cover`. A `public`
`get` route makes its downloads public too, and only those.

A file is always looked up inside the record named by the path, so a `fileId`
that belongs to another record is `404`.

## Lifecycle

- Files are stored before the record is written. If the write fails, the files
  just stored are deleted.
- After a successful update, replace or delete, files the record no longer
  references are deleted from the datastore.
- Deleting a record deletes all of its files.

## Errors

Errors use the usual `{"detail": "..."}` body.

| Status | When |
| --- | --- |
| `400` | Malformed multipart body, or a `_data` part that is not a JSON object. |
| `404` | Unknown record, empty file field, or unknown `fileId`. |
| `413` | A file is larger than its [limit](file-fields.md#limits-and-precedence), or `_data` is larger than 1 MiB. |
| `415` | The detected content type is not allowed. |
| `422` | A required file is missing or would be removed, a part names an unknown or readonly field, too many files, or file fields in a JSON body. |

## OpenAPI

The generated OpenAPI document shows the multipart request body (with `_data`
and one binary property per file field) next to the JSON body of create and
update routes, the multipart body of replace endpoints, and binary responses for
downloads.

## See also

- [File datastores](file-datastores.md)
- [File fields](file-fields.md)
- [Access and binding grammar reference](grammar-reference.md)
