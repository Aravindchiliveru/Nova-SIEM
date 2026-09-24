# Structured events and schema contracts — 0.8

## What this release implements

Nova now exposes complete nested source documents, searches bounded nested paths, validates typed nested mapping packages, and supports additional OCSF projection profiles. Existing raw storage already retains canonical source JSON, so this implementation uses that record as the document source instead of duplicating it in normalized storage. No database backfill or new column is required. Existing events with retained raw records immediately support document retrieval and field search.

This is semantic JSON preservation: objects, arrays, strings, numbers, booleans, nulls and additional fields are retained. It does not preserve original network bytes, whitespace, duplicate keys or field ordering. Existing ingress limits and strict JSON parsing still apply. Normalized summary fields are projections; the original document is available separately.

## Retrieval and search

`GET /api/event?id=EVENT_ID` returns `normalized.document` for normalized events. `GET /api/search` keeps compact summaries by default. Add `include_document=true` to return matching source documents. All reads retain authenticated tenant boundaries; a document cannot override tenant identity.

Nested filters:

| Parameters | Meaning |
|---|---|
| `field=process.file.path&value="/usr/bin/bash"` | Exact string equality |
| `field=process.pid&value=42` | Integer equality |
| `field=context.allowed&value=true` | Boolean equality, distinct from integer 1 |
| `field=context.reason&value=null` | Explicit JSON null, not a missing field |
| `field=process.arguments.0&value="-c"` | First array element equals a string |
| `field=context.reason&exists=true` | Present, including null |
| `field=context.reason&exists=false` | Missing |

URL-encode query parameters using the client library. `value` is a JSON scalar, including quotes for strings. Supply exactly one of value/exists with a field. Existing category, source-IP, time and message filters can be combined with the nested filter. The event explorer adds field, JSON value and existence inputs; Inspect shows the preserved document.

Paths support 1–16 dot-separated identifier segments and zero-based array indexes, at most 512 characters. Identifiers start with a letter/underscore; subsequent characters may include digits or hyphens. Literal keys containing dots, numeric-only object keys, spaces or other punctuation remain preserved/retrievable but cannot be addressed by this path grammar. No wildcard traversal or executable path expressions. Search integers must fit signed 64 bits. Object/array equality queries are rejected. Case-sensitive string and scalar-type matching are intentional.

SQLite binds paths/values to JSON functions and joins raw storage only for document filters/returns. Ordinary summary search retains its prior no-join path. ClickHouse compiles equivalent bound JSON function queries over the raw envelope, translating array indexes to its one-based convention. That SQL path has contract tests but has not run against a live ClickHouse service. Nested filters currently scan eligible document values; there are no dedicated nested-field indexes. Use tenant/time restrictions and measure the intended workload before production sizing.

## Nested mapping packages

`integrations/nested-process-json.json` demonstrates `nova.mapping.v3`. Activate it and send `examples/nested-process.ndjson` through the regular batch ingestion API. It maps dotted source paths to the native summary fields. Required mapping paths must exist; only explicitly optional mappings may be absent.

Each v3 package embeds a **Nova schema v1** contract. This is deliberately named separately from JSON Schema and OCSF. Supported types: object, array, string, integer, number, boolean, null. Object schemas support properties, required and additional; arrays support items/max_items; strings support max_length; numbers support min/max; enum uses exact JSON values. Unknown keywords, invalid type combinations, excessive schema depth and unsupported references are rejected. There is no network schema resolution, regex execution or embedded user code.

Example contract:

```json
{"type":"object","required":["process"],"properties":{"process":{"type":"object","required":["pid"],"properties":{"pid":{"type":"integer","min":0}}}}}
```

Schemas are bounded to depth 16 and 512 nodes. Arrays default to 1,000 entries; individual documents retain the existing 32 KiB ingress limit. Additional properties default to allowed and are preserved. Set `additional:false` when a contract should reject unknown fields. A validation failure enters the existing quarantine with its source document retained. Signed package policy covers the mapping and embedded schema together. This validator does not implement JSON Schema drafts, `$ref`, allOf/anyOf, formats, profile inheritance or upstream OCSF constraints.

## OCSF scope and exact source export

| Integration | Version/class/activity | Native projection |
|---|---|---|
| `ocsf-auth-json` | 1.4.0 / 3002 / 1 | Authentication logon |
| `ocsf-process-json` | 1.4.0 / 1007 / 1 | Process launch; regular executable file |
| `ocsf-file-json` | 1.4.0 / 1001 / 1 | Regular-file creation |

The new system profiles bind the package to its class and check category/activity/type consistency, bounded epoch milliseconds, severity/status, product metadata, mapped object shapes and mapped native field limits. File type must be 1. Additional process/file/vendor fields remain in the document. These are **Nova projection profiles**, not complete upstream schema validators or OCSF conformance certification. Unmapped object properties are not comprehensively validated. Other classes/activities/extensions remain unsupported.

For these imported OCSF records, `GET /api/event/ocsf?id=...` now returns the retained source object, preserving custom/nested fields and original producer metadata. For native authentication events, the existing generated OCSF projection remains lossy. There is no generated OCSF export for arbitrary native process/file events in this release.

Pinned upstream schema retrieval and installation of the optional JSON Schema library failed in this workspace. Full all-class OCSF schema validation and independent upstream conformance fixtures therefore remain open; local profile tests cannot substitute for them.

## Upgrade and rollback

Stop application workers, retain a verified database/source/package backup, deploy 0.8 source and packages consistently and restart. No new storage column or schema migration is introduced here. New packages start inactive for each tenant; explicitly activate the desired package and grant its source to the collector. Sign new packages if signature enforcement is enabled. Do not mix older workers with active v3/system-profile packages they do not understand.

Prior records need no rewrite. Records without retained raw payloads cannot provide a source document; legacy summary search still works. Rollback uses the earlier source and earlier package directory with the verified backup. Remove/deactivate new packages before using older workers, and account for data ingested under those packages.

The next detection step is to make selected structured fields available to rule evaluation with consistent missing/type semantics. Sigma still targets the nine native summary fields in this release; nested search does not itself extend detection coverage.
