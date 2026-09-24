# HA/DR qualification boundary

**Production HA/DR is not proven and this directory does not provision a production cluster.** The included Compose lab is single-node infrastructure. Its existing images, credentials and topology are unsuitable as production defaults.

New executable controls:

- Set `NOVA_REQUIRE_HA=1` for distributed app roles to require a live startup durability preflight. It requires PostgreSQL verify-full TLS, synchronous commits and an active synchronous standby; Kafka verified TLS, three replicas/two in-sync replicas for every partition, minimum ISR at least two and unclean election disabled; HTTPS ClickHouse with a writable replicated events table and two active replicas; an Object Lock/versioned S3 archive. Missing SDKs or inaccessible services fail startup. Local SQLite mode refuses this setting.
- ClickHouse writes in this mode request an insertion quorum of two. `clickhouse-replicated.sql` is an initialization template for a NEW deployment with preconfigured Keeper quorum and shard/replica macros. It will not migrate an existing nonreplicated table. Do not use the ordinary lab initializer as a production migration procedure.
- `tools/qualify_ha.py` implements five operator-controlled failure scenarios and checks ten durably accepted synthetic records per scenario, normalized/indexed/detected/archived receipts, alert evidence, and idempotent replay before running recovery commands. It writes measured outcomes rather than marking a configuration as proof.

A topology owner must supply verified TLS endpoints, at least three Kafka brokers across failure domains, a correctly fenced metadata failover cluster with synchronous standby and WAL/base-backup recovery, replicated ClickHouse/Keeper, redundant stateless app roles/gateway routing, and verified Object Lock/KMS policies. Pin and scan deployment artifacts, test their versions, and provision storage/resources using measured workload. None of that infrastructure was available in this session.

## Running failure tests

Use an isolated qualification deployment and dedicated synthetic-data tenant. Copy `qualification.example.json`; replace every command and endpoint with reviewed commands for that deployment. Commands are argv lists, run without a shell, and execute with the operator's privileges. Injection commands must leave the failed component unavailable until the recovery command, or perform the isolated restore scenario. For the restore scenario, credentials and verification endpoint must work against the isolated restored target. The configuration alone does not prove the command actually caused its named failure; retain orchestrator/database evidence independently.

```bash
# Configuration validation only: no API mutations or fault commands; returns exit 2.
python3 tools/qualify_ha.py --config reviewed.json --output preflight.json
# This intentionally executes your reviewed disruptive commands and writes synthetic events.
python3 tools/qualify_ha.py --config reviewed.json --execute-faults --output live-results.json
```

The fault tester tries recovery in a `finally` block and stops if recovery fails. It does not guarantee cleanup following host/power loss. Its short sample measures an observed recovery interval; it is not a long-duration SLO, network partition test, split-brain proof or full cross-region RPO guarantee. It does not prove continuous ingestion throughput during an outage. Never point placeholder or unreviewed commands at production.

## What was executed

`python3 tools/check_recovery_v06.py` ran actual process kills on temporary SQLite databases and a durable local provider simulator, then restored an isolated snapshot and verified the audit checkpoint. The lease clock advances by 61 seconds in the restarted test worker to exercise expiration without waiting; this is explicit in the report. Provider idempotency is simulated, not inferred for an external vendor. Files: `benchmarks/recovery-v0.6.json` and `benchmarks/ha-qualification-v0.6.json` (live scenarios **not run**).

## Remaining production gates

Live component-loss tests, network partitions/fencing, continuous load during failover, long soak, corrupted backup rejection, full multi-store restore with Kafka offsets and metadata receipts, KMS recovery, region-loss restore, WORM version-deletion denial, operating runbooks and independent review remain required. There is no automated PostgreSQL/Kafka/ClickHouse cross-store backup/restore implementation in this release. Passing startup checks must never be represented as production HA/DR certification.

## 0.7 harness changes

Every scenario now requires `verify_fault_argv`. It must independently assert the component remains unavailable (or that the restore target is isolated), not merely return success. The harness runs it before and after service checks. Ten additional events are submitted during the fault; all twenty acknowledged events must appear normalized, indexed, detected and remotely locked before success. Service recovery time is recorded before cleanup. Fault cleanup still runs on failure. These short probes are not continuous-load, regional-outage, split-brain, fencing or full cross-store DR certification. The example commands are placeholders and no live scenario ran here.
