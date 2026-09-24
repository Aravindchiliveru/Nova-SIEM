# Upgrade to 0.7.1

This maintenance release adds verified reconciliation for uncertain Defender actions and explicit production acceptance instructions. It does not complete the enterprise target, OCSF/Sigma compatibility or the vendor catalog.

1. Stop app processes and take a verified backup with the matching source, packages and configuration. Keep externally executed action records; restoring a database does not reverse containment.
2. Replace the source and restart all app/worker roles together. This change requires no new database columns beyond 0.7. Earlier versions must follow their documented schema initialization steps first.
3. In an isolated vendor test tenant, create/approve a controlled action and test failure/reconciliation scenarios. The review UI now supports an operation UUID for uncertain jobs. The administrator must differ from the requester. Nova verifies the provider receipt and never repeats the POST as part of reconciliation.
4. Run the local correctness suite. See `DEFENDER_RESPONSE.md` for API and recovery semantics.
5. Follow `PRODUCTION_ACCEPTANCE.md` for infrastructure prerequisites, exact evidence requirements, execution sequence and unfinished software gates. The document is an acceptance contract, not a production deployment automation package.

Rollback uses the prior source and a verified compatible backup. Reconcile remote effects first. Pending vendor operation IDs must be preserved to prevent duplicate actions. No live infrastructure or real containment was exercised in this release.
