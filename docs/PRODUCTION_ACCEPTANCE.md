# Production acceptance and remaining implementation

Status: **NOT ACCEPTED**. Nova remains a development product. This document defines completion criteria; it is not evidence that the architecture is provisioned or the features are implemented.

## Scope of a defensible compatibility claim

A claim must name a version and a tested scope. The immediate conformance targets are OCSF 1.4.0 and Sigma detection specification 2.1.0, with correlations and filters listed separately. Support for every future version cannot be promised. Today OCSF supports only the authentication-logon projection; Sigma supports a bounded subset over nine native fields. Those are implementation gaps, not just missing infrastructure tests.

Before claiming OCSF compatibility, package a verified upstream schema snapshot and license/provenance, validate all supported classes and nested objects, enforce enumerations and cross-field semantics, handle profiles/extensions explicitly, retain lossless structured events, support field-path search and mappings, and test import/export with independent upstream examples. Reject unsupported versions without silently projecting away evidence. Every class needs valid, invalid and round-trip fixtures. Zero unexpected conformance failures is the release gate.

Before claiming Sigma compatibility, use the upstream parsing/model ecosystem or demonstrate equivalent conformance with a pinned corpus; implement the full declared modifier, value, condition, field and logsource semantics; then add correlation/filter execution, event-time/watermark handling and migration of detection state. Report supported, rejected and mismatched rules separately. A rule that compiles but cannot access its required fields is not supported. Expected-match and expected-nonmatch datasets must agree with a reference implementation; passing the local starter rules is insufficient.

## Isolated environment required for live proof

Provide an accessible, nonproduction deployment under a dedicated cloud project/account or equivalent isolated VMs. Access should use a workload role/secret manager or an existing authenticated execution environment; do not paste long-lived credentials into chat.

The deployment must provide:

- Three independent failure domains, and a separate disaster-recovery environment with independent credentials and restore storage.
- PostgreSQL primary/standby replication with synchronous commit policy, leader election and fencing; continuous recoverable backups and WAL archives.
- At least three Kafka replicas for required topics, minimum ISR two, verified TLS, durable volumes and appropriate retention for maximum repair/backfill time.
- Replicated ClickHouse tables and a three-member Keeper quorum; isolated replica loss and rebuild testing. A replicated table is not itself a backup.
- Multiple gateways/workers, a health-aware ingress endpoint, verified TLS and identities, and instrumentation from outside the application failure domain.
- An S3 bucket with versioning and Object Lock COMPLIANCE, a dedicated writer role, recovery-reader role, retained version inventory and recoverable KMS key permissions. Use a dedicated synthetic test bucket for mutation-denial probes.
- Vendor sandbox tenants and explicitly disposable/authorized endpoint IDs for isolation tests. Provider license, API permissions and OAuth/token lifecycle must be validated independently.

Sizing is a measurement outcome. Do not use the local 1,871 EPS benchmark to size this deployment. Record machine models, CPU/memory, disk latency/IOPS, network, record-size distribution, enabled rules, retention, replication and query workload before comparing results.

## Test sequence and exit criteria

1. Run local correctness tests and preserve the exact package digest, dependency lockfile, build provenance and SBOM. Resolve security findings before accepting a production build.
2. Deploy the replicated infrastructure and run `nova.distributed.readiness`. Its result is a durability preflight, not certification. Demonstrate correct TLS identities and enforce least privilege. Verify that metadata, broker and analytics roles cannot bypass tenant restrictions.
3. Establish a reference load and latency budget. Proposed first qualification target: 10,000 EPS sustained with concurrent investigations, then a 72-hour soak. Measure p50/p95/p99 acceptance-to-search and acceptance-to-detection latency, CPU, memory, disk, archive delay and error counts. These are test targets, not current product capabilities. Choose fixed acceptance thresholds before running.
4. Execute the five scenarios in `tools/qualify_ha.py`: gateway loss, broker loss, metadata-primary loss, analytics-replica loss and isolated restore. Replace example argv placeholders with reviewed commands and independent fault verifiers. Preserve orchestrator logs and verify faults really occurred. Its twenty-event probe is only an initial check; repeat under sustained load, partitions and resource exhaustion.
5. Reconcile every acknowledged event by stable ID and digest after failure. Require no lost or conflicting acknowledged events in a single-failure-domain test. Verify no split-brain metadata writes, false duplicate side effects, lost alerts or lost approval/audit history. Measure service RTO separately from cleanup. No passing result may be inferred from application uptime alone.
6. Restore to the separate environment using a recorded PostgreSQL backup/WAL recovery point, Kafka retention or immutable raw archive, package/rule versions and explicit replay boundaries. Rebuild analytics as necessary. Reconcile raw IDs, processing receipts, detection state, alerts, cases, approvals and external-operation records. Do not reset all consumers and call that a restore. Cross-store coordination/replay automation is still not implemented in Nova.
7. Execute `tools/qualify_retention.py` only against the isolated bucket. Preserve AWS request IDs and independent audit evidence. Verify exact-version content and retry reuse, deletion/shortening denial, owner/KMS mismatches, legal hold and recovery-reader access. A writer IAM deny alone is not independent proof of Object Lock. Test intended privileges separately and verify AWS retention metadata. Do not shorten actual evidence retention or destroy KMS keys.
8. Run vendor sandbox contract and end-to-end tests: permitted and forbidden assets/tenants; asynchronous success/failure; timeout before/after acceptance; process death; reconciliation; rate limits; credential expiry/rotation; rollback/compensation where supported. No automatic retry of an uncertain non-idempotent action is acceptable.
9. Conduct independent security review and tenant isolation testing, browser/identity lifecycle tests, rolling upgrade/rollback drills, alerting-on-monitoring-failure tests and dependency/build validation. Preserve all evidence with the release.

## Commands available now

From the project root:

```bash
python -m unittest discover -s tests -v
python -m compileall -q nova tools
node --check web/app.js
python tools/qualify_ha.py --config deploy/ha/qualification.example.json --output ha-plan.json
python tools/qualify_retention.py --output retention-plan.json
```

The last two commands intentionally produce `not_run` and exit 2. Do not treat their report creation as test completion. The explicit execution flags are `--execute-faults` and `--execute-isolated-probe`, respectively; use them only after provisioning and reviewing the dedicated test environment. Report paths must be new files.

## Other gaps before the full enterprise target

Broader native and response connectors; rich schema/search support; complete Sigma semantics; tenant database/storage policies and quotas; browser OIDC/PKCE and identity lifecycle; streaming state TTL/watermarks; infrastructure deployment and cross-store DR automation; legal-hold/case lifecycle; independent audit anchoring; fleet upgrades; threat intelligence/behavior analytics; accessible product onboarding; dependency/build security; and controlled commercial comparison remain open. Defender reconciliation alone does not close them.

To establish superiority, compare named alternatives with the same licensed capabilities, datasets, hardware/cost envelope, rules, durability, queries and failure scenarios. Publish limitations and raw results. No such comparison has been performed.

## Primary references

- [PostgreSQL 17 standby/replication](https://www.postgresql.org/docs/17/warm-standby.html)
- [AWS S3 Object Lock](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html)
- [Microsoft Defender machine-action identity and states](https://learn.microsoft.com/en-us/defender-endpoint/api/machineaction)
- [Sigma detection specification](https://sigmahq.io/sigma-specification/specification/sigma-rules-specification.html)
- [OCSF schema project](https://github.com/ocsf/ocsf-schema)
