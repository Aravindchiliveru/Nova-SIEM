# Nova SIEM v0.5 — typed-event development release

This release expands Nova beyond authentication: process, network, DNS, file and cloud events now flow through mapping packages, durable NDJSON collection, normalization, search, detection and evidence inspection. It preserves the separate new SIEM project.

**The enterprise-superiority target is not complete.** This is an executable development product, with tested local behavior and unvalidated distributed wiring. See [remaining enterprise requirements](docs/ENTERPRISE_GATES.md).

## Start

```bash
python3 run.py
```

Requires Python 3.12. Open http://127.0.0.1:8787 and connect using the generated admin token in `data/local-tokens.json`. Standard local mode uses the Python standard library; JWT/package signatures require the optional security dependency. Collection/recovery tooling targets Linux.

1. Activate an integration. Authentication JSON supports the console test sequence; the five new typed integrations have NDJSON examples.
2. Follow [typed collection instructions](docs/TYPED_EVENTS.md) to send process/network/DNS/file/cloud data.
3. Search by category, action, host and target, then inspect normalized fields and retained raw JSON.
4. Review Detection rules. Nine native rules are installed, four enabled by default. The two advanced authentication rules and three typed rules require tenant activation.
5. Investigate alerts in Cases. Internal triage workflows require approval by a different named operator; case notes, evidence export and linked audit verification remain available.

## Upgrade notes

[Typed events and migration](docs/TYPED_EVENTS.md) documents automatic additive SQLite migration, stale rule revisions, coordinated distributed upgrade and snapshot-based rollback. Back up before upgrading. Do not run old code against the migrated SQLite table. New package category filters change authentication rule revisions; review tenant overrides.

## Validation and measured limits

**222 automated tests passed**, including legacy migration, typed event quarantine, real HTTP search/isolation, collector adapter routing and typed detection evidence. Existing authentication, workflow, audit, recovery, identity and distributed-boundary tests remain included. External infrastructure tests use doubles; they do not validate live clusters. JavaScript syntax passed; browser/accessibility QA is unperformed.

- Real concurrent HTTP benchmark: **1,750 median EPS**, 10,000 synthetic events/run.
- Five-category direct-engine benchmark: **8,344 median EPS**, exact expected counts and cloud detections.
- Advanced-correlation engine benchmark: **1,238 median EPS** on a different, alert-heavy workload.
- The same-environment v0.4 HTTP rerun measured **2,000 EPS**. v0.5 was 12.5% slower in this small sequential sample; no optimization gain is claimed.

[Benchmark report](docs/BENCHMARKS.md) includes per-run results, limitations and reproduction commands. These measurements are not production sizing or a commercial comparison.

## Documentation

- [Typed schema, packages, starter detections and migration](docs/TYPED_EVENTS.md)
- [Enterprise control behavior](docs/ENTERPRISE_CONTROLS.md)
- [Correlation semantics and state limits](docs/CORRELATION.md)
- [Validation](docs/VALIDATION.md) and [enterprise gates](docs/ENTERPRISE_GATES.md)
- Existing collection, identity/signatures, recovery and distributed-lab guides remain included. v0.5 guidance takes precedence where behavior changed.

OCSF/Sigma, broad native collectors, full enterprise browser identity, external SOAR, immutable evidence retention, storage-level tenant enforcement, production HA/DR, threat intelligence/UEBA and controlled market comparison remain unfinished.
