# Diagnostics, backup and recovery

## Local diagnostics

```bash
python3 -m nova.operations doctor --db data/nova.db
```

Checks SQLite integrity, counts and normalization backlog, and prints relevant next steps. It is read-only and never creates a missing database. A growing backlog means inspect worker health/integration activation; it does not justify deleting the durable journal.

The authenticated `/api/health` and `/metrics` endpoints remain available. Local workers retry errors with bounded backoff and stop after five consecutive failures. Distributed workers retain failed-batch offsets and rely on Compose's bounded restart policy. The collector has its own persistent retry/circuit state. None of these mechanisms executes arbitrary repair scripts or automatically changes networks/storage/security policy.

## Online SQLite backup

```bash
python3 -m nova.operations backup --db data/nova.db --output backups/snapshot-001
```

Uses SQLite's online backup API and writes a consistent database snapshot plus SHA-256 manifest. Destination must not already exist. Snapshot integrity is checked. Keep a separate backup of credentials, rules, integration packages, trust configuration and archive data. The snapshot manifest detects accidental corruption; it is not an authenticated or WORM backup.

## Restore without overwriting

```bash
python3 -m nova.operations restore --snapshot backups/snapshot-001 --output recovery/nova.db
```

Restore verifies SHA-256 and SQLite integrity, then installs the output only if the destination does not exist. It never overwrites the current database. Stop the local service, preserve the existing data directory, copy the matching private credentials into a separate recovery data directory, and start with `python3 -m nova.server serve --data recovery`. Recovered pending events resume processing.

Backups and recovery are **local SQLite only**. They do not back up PostgreSQL, ClickHouse, Kafka or distributed filesystem archives. Those need independent coordinated procedures and live restore testing before production.

## Recovery evidence

`python3 tools/check_recovery.py` creates only temporary synthetic data, kills processes, verifies acknowledged data survives and incomplete transactions roll back. `benchmarks/recovery-results.json` records this release's result.

Full-disk, host-power failure, network partitions, multi-node failover and cross-region DR remain untested. Database, rule-state and archive retention are not implemented: plan capacity rather than expecting automatic deletion or tiering.
