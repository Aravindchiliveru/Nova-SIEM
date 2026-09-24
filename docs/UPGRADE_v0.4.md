# Upgrade and rollback — v0.4

1. Preserve a complete v0.3 code/package/configuration copy and take a verified data backup.
2. Drain pending ingestion/detection where practical, then stop the service.
3. Install the complete v0.4 tree. Local startup creates additive audit-chain, workflow, correlation-state and tenant-rule-setting tables. Existing data is not intentionally deleted.
4. For the distributed lab, run its initialize/migration step before starting updated gateways/workers. All workers need the same package set. Actual PostgreSQL migrations remain unexecuted in this environment.
5. Start locally, check health and tenant views, and use the synthetic workflow/approval example.
6. Review the two disabled correlation rules before enabling them. New rules do not automatically re-evaluate completed historical events.

New audit entries are linked; older audit rows are reported as unlinked rather than silently asserted to be verified. Keep an external checkpoint after reviewing the new deployment.

Rollback requires the matching prior code **and package definitions**, plus the appropriate verified snapshot/configuration. v0.3 does not understand the new correlation fields and does not execute v0.4 workflows. Do not leave queued workflows running while replacing code. Additive tables alone do not guarantee an operationally safe downgrade. No destructive migration or automatic data-pruning command is included.
