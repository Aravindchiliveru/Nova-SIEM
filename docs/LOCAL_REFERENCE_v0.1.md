# Nova SIEM — clean-sheet foundation

Working name, not trademark-cleared. Version 0.1.0, 17 September 2026.

This repository starts a new security product. It does not modify, migrate, depend on, or inherit the user's existing SIEM configuration.

**Delivered:** runnable local correctness reference, browser console, tenant-scoped HTTP API, durable ingestion journal, declarative integration examples, normalization, quarantine and bounded replay, one authentication detection, case creation, audit activity, metrics and tests. **Not delivered:** a production distributed SIEM. The target stack is researched in `docs/RESEARCH.md`; its services are not silently emulated or represented as installed.

## Start

Requires Python 3.12 or newer. No third-party Python packages, Docker, cloud account, package download or external connection is needed for the local build.

```bash
python3 run.py
```

On Windows use `py run.py`. Open http://127.0.0.1:8787 in your browser. Copy the `admin` value from `data/local-tokens.json` into the connection form. Select **Send test sequence**, then **Refresh**. Five synthetic authentication failures produce a detection. Open **Detections → Open case → Cases**.

Credentials are randomly generated per installation. Keep `data/local-tokens.json` private. `credentials.json` stores hashes; delete neither file casually. The launcher never overwrites credentials. The server binds only to loopback and intentionally does not offer a public bind option. This is a development HTTP server, not an internet-facing deployment.

Optional CLI sample:

```bash
python3 tools/send_sample.py
```

Choose another local port using `python3 run.py --port 8788` and pass `--port 8788` to the sample tool.

## Verify

```bash
python3 -m unittest discover -s tests -v
python3 tools/benchmark_local.py --events 1000
```

Tests cover crash/restart persistence, concurrent retries, conflicting identities, atomic rejection, tenant isolation, permissions, malformed input, case idempotency, replay limits, time filtering, fixed-window detections and HTTP boundaries. See `docs/VALIDATION.md` for executed checks and remaining gates.

## How this version works

Accepted JSON events enter a SQLite WAL journal. The response follows a committed transaction. A normalizer consumes unprocessed records; malformed or inactive integrations enter quarantine. A detector consumes normalized records with a separate durable processing ledger. Each stage's transaction commits its output and processed marker together. HTTP and worker threads can operate independently, but database writes serialize: this build is not distributed.

Event identity is scoped by authenticated tenant, source and caller-supplied stable ID. Identical retries do not insert another event; a conflicting payload/integration returns HTTP 409. Whole batches commit or roll back. JSON values are retained canonically; this is not byte-for-byte original wire evidence. The production collector contract must retain original bytes separately.

The example detector fires for at least five failures by the same tenant, source, actor and IP in one fixed UTC five-minute event-time bucket. It is **not** a sliding-window, Sigma, UEBA or full OCSF implementation. Late events are evaluated against retained local data. There is no external response action. Successful replay may produce a historical alert; production replay must label and suppress response by default.

The local reference caps accepted events at 100,000 per tenant and individual event payloads at 32 KiB. HTTP batches contain at most 500 records and 1 MiB. Capacity rejection is explicit; no automatic evidence deletion occurs. The local database and audit table are not an immutable archive and are not encrypted by this app.

## Integrations

`integrations/*.json` packages declare field mapping, supported outcomes and fixtures. Startup validates fixtures. Activation is tenant-specific and audited. Packages cannot execute code. New locally installed packages are loaded after restart. Packages are local trusted files; hashes show their identity but are **not signatures**. Remote installation, signature verification, version rollback and live reload are planned.

The two included packages are documented sample JSON contracts, not certified vendor connectors. Add real vendor fixtures, protocol collection, edge checkpoints, schema mappings, detection prerequisites and compatibility tests before claiming a vendor integration.

## API

Authorization: `Bearer <token>`. Tenant identity comes from the credential, never a request tenant field. Collector tokens ingest only; viewer tokens read only; analysts read/create cases; administrators also activate integrations and replay.

| Method | Path | Behavior |
|---|---|---|
| GET | `/healthz` | Process liveness only; no tenant data |
| GET | `/api/health` | Tenant counts, pending stages and worker error |
| POST | `/api/events` | Durable atomic acceptance and retry deduplication |
| GET | `/api/search` | `q`, `ip`, `outcome`, `after`, `before`, `limit` (1–500) |
| GET | `/api/event?id=...` | Tenant-scoped raw/normalized/stage detail |
| GET | `/api/integrations` | Installed packages and tenant activation |
| POST | `/api/integrations/activate` | `{"package":"auth-json"}` |
| GET | `/api/quarantine` | Latest 200 quarantined records |
| POST | `/api/quarantine/replay` | `{"event_id":"..."}`; at most 3 retries |
| GET | `/api/alerts` | Latest 200 alerts with evidence IDs |
| POST | `/api/cases` | `{"alert_id":"..."}`; idempotent for an alert |
| GET | `/api/cases` | Latest 200 cases |
| GET | `/api/audit` | Latest 200 tenant activity records |
| GET | `/metrics` | Authenticated tenant-level Prometheus exposition |

Acceptance request:

```json
{"source":"collector-1","integration":"auth-json","events":[{"id":"stable-source-id-1","data":{"timestamp":"2026-09-17T12:00:00Z","user":"alice","src_ip":"192.0.2.10","status":"failure","message":"Login denied"}}]}
```

Search uses an inclusive `after` and exclusive `before`, both timezone-qualified ISO 8601. Queries are parameterized. Local text search is literal/case-sensitive and scan-based, not a production search index. Lists are bounded but cursor pagination is not implemented yet.

## Next implementation boundary

The next milestone replaces the reference journal with Kafka ingress and independent consumers, writes analytical events to ClickHouse, and moves control metadata to PostgreSQL. Distributed fault tests and version-pinned packaging must pass before that profile is advertised. The local contracts/tests are the acceptance reference, not a promised drop-in backend abstraction.

See `docs/PRODUCT.md`, `docs/ARCHITECTURE.md`, `docs/RESEARCH.md`, `docs/SECURITY.md`, and `docs/ROADMAP.md`.
