# Nova SIEM — development release 0.2

Clean-sheet security platform. Working name only. Updated 18 September 2026.

**This release adds code for an optional distributed development profile.** The existing dependency-free local mode remains runnable. The distributed profile has not been run against real services in the current environment: Docker, PostgreSQL/ClickHouse server binaries and Kafka client installation were unavailable. It is not a production release or a capacity claim.

## What is implemented

- Tenant-bound HTTP API and console; collector, analyst, viewer and administrator permissions.
- Durable acceptance, stable event identity, duplicate retry handling and conflicting-ID rejection.
- Declarative integration examples and fixtures, normalization, quarantine and bounded replay.
- Authentication-failure detection, evidence-linked alerts, minimal cases and audit records.
- **New:** PostgreSQL ingress receipts and transactional outbox; raw payloads leave staging after Kafka delivery confirmation.
- **New:** Kafka relay plus independent normalization, analytics, detection, quarantine and archive consumer groups.
- **New:** ClickHouse HTTP batch writer and tenant-bound parameterized search with query limits and query-time deduplication.
- **New:** Filesystem archive with content-addressed files, fsync, redelivery handling and checksum verification.
- **New:** Stage receipts, worker heartbeats, unavailable-analytics state, source-restricted credentials and metrics fixes.
- **New:** Docker Compose profile, launcher, real-cluster verification/fault-test harness and CI workflow definition.

**Validation:** 93 automated tests passed. Kafka/ClickHouse/PostgreSQL adapter tests use test doubles; they do not establish live service compatibility or distributed durability. See `docs/VALIDATION.md`.

## Run the local mode

Requires Python 3.12+. No additional Python packages or external services.

```bash
python3 run.py
```

Windows: `py run.py`. Open http://127.0.0.1:8787. Copy the `admin` token from `data/local-tokens.json`, connect, select **Send test sequence**, then refresh. Five synthetic failures produce a detection; open it as a case. Credentials are generated randomly and never printed into logs.

This mode continues to use SQLite and in-process workers. Its detailed behavior is preserved in `docs/LOCAL_REFERENCE_v0.1.md`.

## Run the distributed lab on a Docker-capable machine

The local mode and lab both use port 8787; run one at a time. Requires Docker Engine/Desktop with Compose v2 and access to the image/package registries. This release is not an offline bundle.

```bash
python3 tools/cluster.py doctor
python3 tools/cluster.py start
python3 tools/cluster.py verify
```

Open http://127.0.0.1:8787 using the admin token in `deploy/.lab/local-tokens.json`. The lab creates its own credentials, separate from local mode. Keep the entire `deploy/.lab` directory for subsequent starts; do not regenerate database passwords against existing volumes.

`start` creates credentials and runs Compose. `verify` waits for the gateway and verifies live staging, broker processing, ClickHouse search, detection, case requests, permissions and quarantine. It fails if these services do not work; it never substitutes mocks.

```bash
python3 tools/cluster.py fault-test
python3 tools/cluster.py status
python3 tools/cluster.py stop
```

`fault-test` temporarily stops the indexer and then ClickHouse in this named local project, verifies detection continues, restores the services and verifies search catches up. It uses synthetic events. These scenarios have been authored but **not executed here**. `stop` preserves all volumes and evidence. No reset/delete-volumes command is provided.

## Distributed delivery contract

1. Gateway commits receipt + outbox in PostgreSQL before acknowledging HTTP acceptance.
2. Relay publishes raw events, waits for Kafka delivery confirmation, then deletes staging payloads.
3. Normalizer publishes normalized events or quarantine records, then records its stage receipt and advances explicit Kafka offsets.
4. Independent consumers write ClickHouse, update detection state, preserve raw archive or store quarantine.
5. Each consumer commits only after its destination confirms success. A failure can redeliver a batch; it must not skip it.

HTTP acceptance is **PostgreSQL staging durability**, not confirmation that Kafka, search, detection or archive has finished. The lab has one broker and one instance of each database; it does not survive their permanent data loss. PostgreSQL is still shared by stage receipts and the sample detector, so its failure can stop several workers. This is an intermediate integration profile, not the final high-throughput architecture.

Every ClickHouse query uses `FINAL` to account for retry duplicates. Immutable event identity/time keep retries in the same partition and key. This is at-least-once delivery with idempotent effects, not a universal exactly-once claim.

## Limits and security

Loopback host port bindings; internal development traffic uses plaintext. The gateway has static development tokens, not production OIDC/TLS. Backend credentials are shared service credentials in this lab, not database-enforced tenant isolation. Do not expose these ports or use this profile for untrusted tenants.

Both modes cap accepted events at 100,000 per tenant. Request limits are 500 events, 1 MiB per batch, and 32 KiB per individual event. No automated receipt/state retention exists yet. The distributed query service caps returned rows at 500 and scanned rows at one million; complex queries can fail on the budget rather than return partial results.

The detector is a custom fixed five-minute bucket rule, not Flink/Sigma. The sample packages are JSON mapping examples, not vendor-certified collectors or full OCSF mappings. The archive stores canonical JSON, not original wire bytes, and is not immutable/WORM storage. No external containment actions run.

## Project map

| Path | Purpose |
|---|---|
| `nova/core.py`, `nova/server.py` | Local reference and shared API/console server |
| `nova/distributed/` | Wire contracts, real adapters, PostgreSQL metadata and worker entry points |
| `deploy/` | SQL schemas, Compose configuration and runtime credentials generated locally |
| `integrations/` | Declarative sample mapping packages |
| `web/` | Browser console |
| `tests/` | Local regression and distributed contract/failure tests |
| `tools/cluster.py`, `tools/check_cluster.py` | Lab lifecycle and live-cluster checks |
| `docs/DISTRIBUTED_LAB.md` | Architecture details, failure semantics and remaining limitations |
| `docs/VALIDATION.md` | Actual checks performed and unexecuted gates |
| `docs/ROADMAP.md` | Current implementation status |

Run tests with `python3 -m unittest discover -s tests -v`. The next release gate is executing and fixing the real cluster profile, then load/fault tests, before integrating Vector, production identity and Flink.
