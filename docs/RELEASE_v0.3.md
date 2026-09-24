# Release and upgrade — v0.3

## Capability status

| Area | Implemented in this release | Remaining enterprise work |
|---|---|---|
| Processing | Bounded local batches; shared declarative rule evaluator; PostgreSQL detector commits a batch atomically | True multi-node throughput/failover validation; partition-aware stateful processing |
| Integrations | JSON mappings; disk spool; three additional authentication export adapters | Native EVTX, cloud API collection, syslog listeners, general firewall/EDR/SaaS catalog, automatic rotation |
| Detection | Four shipped rules; exact filters; fixed windows; distinct counts; sample simulation | Sliding windows, sequences, Sigma engine, ATT&CK coverage validation, UEBA |
| Identity | Opaque credentials; expiry/revocation flags; opt-in pinned-JWKS RS256 access-token validation | Browser OIDC/PKCE flow, discovery/rotation, live IdP validation, delegation and enterprise policy |
| Package trust | Operator Ed25519 signatures and fail-closed required mode | Trusted marketplace, revocation feed, downgrade prevention, sandboxed executable plugins |
| Investigation | Event drill-down; case status/notes; tenant-scoped audit trail | Evidence export workflows, assignments/SLA, tamper-evident audit anchoring, collaboration |
| Recovery | Retry/circuit breaking, quarantine, worker restart policies, diagnostics, local snapshot/restore | Durable SOAR workflows, automated containment, distributed backups/DR, WORM evidence |
| Benchmark | Local comparative engine tests; real HTTP concurrency; process-kill recovery | Production load, HA/DR, independent vendor comparison |

## Upgrade precautions and semantics

Back up v0.2 data before upgrading. The local schema change is additive (`rule_hits`, `case_notes`); PostgreSQL initialization adds corresponding rule and note tables. No data is intentionally deleted. Back up credentials, integration/rule packages and archives separately from the SQLite snapshot.

The rule state and alert identity now include a hash of the rule definition. Existing v0.2 alerts/cases remain untouched. New events in an already-alerted bucket can create a new v0.3 alert because the identity scheme changed. Already-processed events are **not automatically re-evaluated** under new rules. Existing incomplete buckets do not automatically receive historical rule-hit state. For deterministic migration, pause sources, drain v0.2 queues, take a backup, then switch versions at a fixed-window boundary. Do not delete processing ledgers to perform an undocumented backfill.

Rules are loaded from operator-controlled JSON files at process startup. All detector workers must receive the same signed package set and restart together after a rule change. Mixed rule revisions between workers can cause incomplete correlation; coordinated rollout is required. There is no hot rule publishing API or historical re-evaluation service yet.

Collector identities are derived from path, device/inode, line offset and line content. The same spool handles append/retry without duplicates. Copying a file to another path or importing it through a fresh spool after rotation can generate new identities; this is not a global semantic deduplication service. Keep source files immutable behind the stored cursor.

## Release boundary

This is a substantial development upgrade. It does not implement every feature in the target product specification and is not certified for production. HA/DR, native broad integrations, OCSF/Sigma conformance, advanced correlation/UEBA, full SOAR, complete SSO, immutable evidence and distributed benchmark gates remain open. No claim of being the world's best or outperforming established SIEMs is supported.
