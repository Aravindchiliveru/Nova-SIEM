# Nova SIEM v0.8 — structured event foundation

This release adds complete source-document retrieval, typed nested-field search, schema-validated nested mapping packages and two additional OCSF projection profiles. See the structured-event guide for exact supported boundaries.

**Production HA/DR is not proven. Full OCSF/Sigma coverage and a broad vendor collector/response catalog are not complete.** The delivered implementations have explicit supported boundaries and executable tests; AWS and live distributed infrastructure were unavailable here.

| Area | Implemented | Validation / remaining boundary |
|---|---|---|
| Native collection | Journald cursor acquisition; CloudTrail LookupEvents pagination; transactional durable spooling | Fixture/process-interface tests. No populated live journal or AWS account test; not fleet management or all cloud events |
| OCSF | 1.4.0 authentication logon, process launch and file-create projection profiles | Tested selected fields/identity/time; not full schema validation or all classes |
| Sigma | Strict YAML importer, configured source/field binding, bounded Boolean/string predicates | Compiler and installed-engine tests; unsupported syntax rejected; not full SigmaHQ compatibility |
| External SOAR | Tenant-scoped HTTPS connector, two-operator approval, leases, retries, audit and console | Real local TLS and process-kill simulator tests; provider must guarantee idempotency; Defender isolate/unisolate contract tested; no live vendor qualification |
| Immutable retention | S3 COMPLIANCE/KMS/version checks, conditional writes, content verification, versioned receipts and hold-ON method | Test doubles only. Remote enforcement/IAM policies unvalidated |
| HA/DR | Live durability preflight, replicated-table template, quorum insert setting, operator fault harness, local crash/restore drill | Local drill passed. Real multi-node failover and cross-store/region restore not run or proven |

## Start

```bash
python3 run.py
```

Use Python 3.12. Open http://127.0.0.1:8787 and connect with the generated admin token in `data/local-tokens.json`. Activate an integration, send example events and inspect detections/cases. Optional feature dependencies are separate; see the guides below. Default local mode needs no AWS credentials and sends no external actions without a configured connector and approved job.

**External actions** is a new console view. Configure a fixed HTTPS connector and tenant grants, request an action against an alert, then review/approve as a different named administrator. Do not enable real containment until the receiving adapter's idempotency and asset authorization are verified.

## Guides

- [Structured events, schema contracts, search and 0.8 upgrade](docs/STRUCTURED_EVENTS_v0.8.md)

- [0.7.2 Sigma changes, corpus checker and migration](docs/UPGRADE_v0.7.2.md)

- [Production acceptance requirements and open implementation gates](docs/PRODUCTION_ACCEPTANCE.md)
- [0.7.1 upgrade instructions](docs/UPGRADE_v0.7.1.md)

- [0.7 changes and upgrade steps](docs/UPGRADE_v0.7.md)
- [Defender response setup and recovery](docs/DEFENDER_RESPONSE.md)

- [Native acquisition, OCSF and Sigma](docs/CONNECTORS_v0.6.md)
- [External response setup, API and failure semantics](docs/EXTERNAL_RESPONSE.md)
- [Immutable retention setup, migration and validation limits](docs/IMMUTABLE_RETENTION.md)
- [HA/DR prerequisites and executable qualification](deploy/ha/README.md)
- [Validation](docs/VALIDATION.md), [benchmarks](docs/BENCHMARKS.md), [remaining enterprise gates](docs/ENTERPRISE_GATES.md)

## Upgrade

Stop app writers/workers and take verified backups first. Local startup adds external-job tables; the local archive command adds its receipt table. Distributed users must run the updated schema initialization before restarting app roles: it adds external jobs, separate Object Lock receipts and `locked_at`. Switching to S3 archival starts a separate consumer group, so already expired Kafka data needs explicit backfill. Old filesystem timestamps never count as WORM proof. External provider effects and remote retention cannot be undone by restoring a database.

v0.5 typed columns and rule-revision upgrade guidance still applies. Imported Sigma packages require coordinated installation/restart and the configured signature policy. Use a pre-upgrade snapshot plus matching source/packages for rollback; reconcile any remotely executed actions before retrying. Do not enable mixed-version workers over these new contracts.

## Executed evidence

**313 automated tests passed.** Real TLS webhook exchange; actual process kills; restored SQLite snapshot with audit checkpoint verification. Historical 0.7 default HTTP profile (not rerun for 0.7.1): **1,871 median completed EPS**, three runs of 10,000 synthetic authentication records with concurrent reads. No throughput result measures live CloudTrail/S3 or active external containment.

The AWS SDK could not be installed from the runtime's package source. PostgreSQL/Kafka/ClickHouse/Docker services were unavailable. Native provider fixtures and storage doubles are not remote production proof. Browser rendering/accessibility was not tested. See the explicit evidence matrix before considering deployment.
