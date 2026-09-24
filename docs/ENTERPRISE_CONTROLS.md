# Enterprise controls — v0.4

## Tenant-specific rule lifecycle

The installed package supplies a default enabled flag. A tenant administrator can override it through POST `/api/rules/configure` with `id`, `revision` and boolean `enabled`. The exact installed revision must match. The override affects that tenant only, and is audited. When package bytes/definition change enough to change the rule revision, the old override fails closed and the rule is disabled until reviewed again.

GET `/api/rules` returns effective enabled state and configuration source. The console's simulation treats a selected rule as enabled without changing live configuration. This supports testing before activation. Enabling a rule processes future/unprocessed events; it does not backfill records whose detector ledger already completed. All distributed workers must use identical package revisions. There is no centralized package rollout/rollback coordinator yet.

## Approval workflows

POST `/api/workflows` requires an analyst/admin and `{request_key, playbook, alert_id}`. The initial playbook is `triage-auth.v1`. Requests are idempotent per tenant/request key; changed input under an existing key is rejected.

POST `/api/workflows/transition` requires an administrator and `{id, revision, action}`. Actions: approve, cancel, retry. Approval requires a different configured actor name from the requester. This separates named identities; it cannot establish that two tokens are held by different physical people. Stale revision numbers are rejected.

States: pending_approval → queued → completed. A failed internal step retries with bounded delay; three failures move the workflow to failed. An admin can retry an approved failed workflow. Cancellation prevents remaining steps and preserves already committed effects; it is not compensation/undo.

The registered playbook has three steps: create/find the alert's case, set investigating, add a fixed note. A step's database changes, workflow cursor and audit entry commit together. A database savepoint rolls back partial effects before scheduling a retry. Concurrent workers serialize each workflow through database locks; PostgreSQL uses FOR UPDATE SKIP LOCKED. There are no external API calls or lease-expiry assumptions inside a step.

Local workflows run in the existing worker. The distributed gateway starts a workflow worker thread; each gateway can compete for queued jobs. Database recovery releases abandoned transaction locks. PostgreSQL behavior and concurrent gateway operation are wired but not live-tested here.

This is a durable **internal triage workflow**, not full SOAR, Temporal integration or automated endpoint/firewall containment. No arbitrary shell scripts, remote commands, notifications or vendor APIs are executed. Extending to external effects requires durable activity idempotency, fencing, target allowlists, audit, approval, compensation and provider-specific tests.

GET `/api/workflows` lists tenant jobs. GET `/api/playbooks` returns the registered definition. Workflow counts are included in `/api/health` and `/metrics`; failed workflows make health require attention.

## Linked audit history and checkpoints

New audited actions are linked per tenant using sequence, previous digest and canonical payload. Verification recomputes links and checks each linked record against its original audit table row. A transaction that rolls back cannot leave a committed audit link.

GET `/api/audit/checkpoint` verifies the linked history and returns tenant/count/root plus diagnostic fields. POST `/api/audit/verify` accepts `{anchor: checkpoint}` and checks the retained checkpoint is present. Pre-v0.4 audit rows remain untouched and are reported as unlinked.

**This is not immutable storage.** A privileged database writer can rewrite an entire unanchored chain or remove its tail. Retaining a prior checkpoint independently allows detection of changes affecting that checkpoint. It does not prove later entries that were never externally checkpointed existed.

Online verification is bounded at 10,000 linked records and returns an explicit capacity error above that; it never labels a partial verification complete. Larger local histories can use the offline tool:

```bash
python3 -m nova.audit_checkpoint --db data/nova.db --tenant demo --output checkpoint-001.json
python3 -m nova.audit_checkpoint --db data/nova.db --tenant demo --anchor checkpoint-001.json
```

Keep checkpoints outside the SIEM's administrative/storage failure domain. The offline tool creates output exclusively and refuses overwrite. Optionally sign the checkpoint with the existing Ed25519 package-signing command and keep the trust root independently. Automated external anchoring and WORM storage are not implemented.

## Case evidence

POST `/api/evidence/export` requires an analyst/admin and `{case_id}`. The console downloads JSON containing case/notes, alert and at most 100 stored evidence references. All reads are tenant-scoped. Exports are audited and include a SHA-256 digest.

This is not a complete incident search or a cross-store point-in-time snapshot. It preserves exported JSON content, not original network bytes. `may_be_truncated` is conservative when 100 references are present. A checksum detects content changes but does not establish authenticity; the offline verifier never trusts a bundle's self-asserted authenticity label.

```bash
python3 -m nova.evidence nova-case-1.json
python3 -m nova.packages sign --private-key /private/nova-signing.pem --key-id operator-1 --package nova-case-1.json
python3 -m nova.evidence nova-case-1.json --trust /private/nova-trust.json
```

## Integration operations

POST `/api/integrations/test` with `{package, events}` previews up to 100 input objects using an installed mapping and returns normalized values/errors without persisting events. It requires administrator access.

POST `/api/integrations/deactivate` with `{package}` removes the tenant activation and records the change. In local mode queued records are evaluated against current activation and may quarantine. In distributed mode previously accepted envelopes retain their package digest snapshot and can still normalize; later unactivated envelopes quarantine. Deactivation is not retroactive deletion or cancellation of accepted data.
