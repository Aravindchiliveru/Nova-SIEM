# Validation report — 0.2

Executed 18 September 2026. This report separates executed tests from authored but unexecuted integration checks. Version 0.1 evidence remains in `VALIDATION_v0.1.md` and `test-output.txt`.

## Executed successfully

| Check | Result | Scope |
|---|---|---|
| `python3 -m unittest discover -s tests -v` | **93 tests passed in 9.412 seconds** | Existing local tests plus new API and distributed-contract tests |
| Python compile checks | Passed | Application and tools syntax/import compilation |
| `node --check web/app.js` | Passed | Browser JavaScript syntax only |
| Compose YAML parse | Passed, 11 services | YAML structure only; not Docker Compose validation or startup |
| Local live runtime test | Passed within the suite | CLI producer → HTTP API → local worker → detection → case |
| Archive filesystem tests | Passed | Idempotent writes, checksum verification, corruption rejection and replay preservation |

Full current test output: `test-output-v0.2.txt`.

## New failure/correctness tests

- No input offset commit after failed sink write, publish acknowledgement or metadata stage update.
- Commit failure allows safe redelivery rather than skipping the input batch.
- Explicit next offsets for multiple partitions, including gaps in offset positions.
- Producer all-acks/idempotence configuration; pending queue or failed callback treated as unconfirmed delivery.
- New-group offset initialization versus existing expired offsets; auto-commit disabled.
- Invalid wire JSON, duplicate keys, nonfinite timestamps, identity overrides and raw digest mismatches rejected.
- Whole-batch validation before normalization output publication or ClickHouse write.
- Package digest snapshots and preservation of failed payloads in quarantine.
- Tenant-bound typed ClickHouse queries; bounded limits and half-open time filters.
- ClickHouse execution errors inside HTTP 200, timeout and malformed response handling.
- No database password in request URLs.
- Outbox deletion ordered after confirmed broker publication.
- Optional source-bound collector authorization and distributed worker error propagation into metrics.

**Kafka, ClickHouse and PostgreSQL adapter/failure tests use test doubles.** They validate application decisions at the boundaries; they do not execute librdkafka, PostgreSQL SQL, ClickHouse storage semantics, broker rebalances or distributed transactions.

## Environment blockers and unexecuted checks

- `python3 tools/cluster.py doctor` reported Docker unavailable (exit 2). No container or cluster was started.
- PostgreSQL, ClickHouse and broker server binaries were not available.
- Attempted installation of the pinned external Python clients failed because the available package source returned no distribution. No successful client import or service compatibility test is claimed.
- The explicit package releases were located on PyPI through research, which does not make them installed or validated in this runtime.
- Browser visual/accessibility validation was not performed for 0.2. The earlier missing Chromium/download blocker has not been resolved.
- No cluster load benchmark, disk/network partition test, image startup, schema execution, migration, HA, archive restore or production deployment was performed.
- No assertion is made that the selected image tags, their runtime permissions, or the complete Compose dependency chain have passed a live startup. The included live harness is the next gate.

## Authored real-service checks (not executed here)

`python3 tools/cluster.py verify` tests live ingestion/staging, retry/conflict behavior, ClickHouse search, detection, case identity, collector permissions and quarantine. It waits for actual services and fails if they are unavailable.

`python3 tools/cluster.py fault-test` additionally stops the indexer and then ClickHouse, verifies detection continues, restores services and checks search recovery. Only the named local nova-lab project is affected. Both commands add synthetic events. The CI workflow definition invokes these checks but has not run on a remote runner.

## What this means

The local reference still passes its regression suite. New distributed service code and deployment/test tooling are present and contract-tested. **Distributed operational readiness and performance remain unverified.** Production release gates in `SECURITY.md`, `DISTRIBUTED_LAB.md` and `ROADMAP.md` remain open.
