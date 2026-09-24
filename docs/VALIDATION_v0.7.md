# Validation — v0.7

286 automated tests pass; full log: `test-output-v0.7.txt`. The 0.6 evidence matrix is preserved in `VALIDATION_v0.6.md`. The current suite includes its tests plus expanded Sigma semantics, Defender action lifecycle and qualification-harness behavior.

| Area | Executed evidence | Remaining boundary |
|---|---|---|
| Defender | Approval and asset grants; POST then polling; wrong-identity rejection; timeout behavior; durable intent; actual child-process SIGKILL after a simulated provider effect; no repeat POST after restart | No live Microsoft tenant; no automatic OAuth refresh or uncertain-action reconciliation UI |
| Sigma | Escapes, wildcard matching, Windows paths, Unicode case handling, integer string equality, null/exists, private selections, case-sensitive selection names, quantifiers and condition lists; installed-engine tests | No full Sigma corpus parity, regex/transforms, filter/correlation coverage or arbitrary field support |
| HA harness | Tests require independent fault verification and during-fault writes; default-mode not_run report | No cluster faults executed, no provisioned production topology or cross-store DR |
| Retention harness | Synthetic-provider test of exact-version probes, conditional retry, post-probe content checks and denial classification; default-mode not_run report | No real AWS request, writer IAM/KMS validation or independent remote enforcement proof |
| HTTP throughput | Three fresh 10,000-event runs; same-runtime 0.6 baseline rerun | Synthetic single-host workload, not enterprise capacity or commercial comparison |
| Existing recovery | Repeated actual ingress SIGKILL, idempotent local provider simulator and isolated SQLite restore | No disk/power failure, replicated-service failover or remote backup recovery |
| OCSF | Existing authentication projection tests continue passing | Full schema validation and all-class compatibility remain unimplemented |

Python compilation and JavaScript syntax checks passed. Browser rendering/accessibility QA was not run. Test fixtures are not provider certification. The generic webhook retains its existing real-localhost TLS test; Defender API contract tests inject a local fake transport.

An earlier environment session installed JSON Schema dependencies temporarily, but the current runtime has none; its installation retry reported no available distribution. A versioned OCSF 1.4.0 class descriptor was retrieved, but no complete schema bundle/validator was integrated. This is recorded as unfinished work, not compatibility. AWS SDK, PostgreSQL/Kafka/ClickHouse services and Docker are unavailable for live qualification here.

**Production HA/DR, remote WORM enforcement, full OCSF/Sigma compatibility and enterprise/commercial superiority remain unproven or incomplete.**
