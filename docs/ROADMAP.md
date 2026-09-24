> v0.4: Current behavior and remaining gates are documented in ENTERPRISE_CONTROLS.md, CORRELATION.md, VALIDATION.md and ENTERPRISE_GATES.md. Newer guides take precedence over this historical description.

> v0.3 update: see [RELEASE_v0.3.md](RELEASE_v0.3.md) and [VALIDATION.md](VALIDATION.md) for current implementation status. The previous single-rule detector is replaced by the shared declarative rule evaluator; package signatures and JWT access-token validation are optional additions. Distributed runtime validation remains open.

# Execution roadmap and honest feature status — updated for 0.2

No artificial delivery dates: timing depends on staffing, infrastructure and the supported integration breadth. The decision order is fixed enough to proceed without repeated preference questions.

| Milestone | Deliverable | Current state | Exit gate |
|---|---|---|---|
| 0 | Research, product requirements, entity model, architecture decisions | Initial pass complete | Revisit choices against measured workload |
| 1 | Runnable correctness reference and local console | Implemented | Tests pass; browser review still outstanding |
| 2 | Kafka ingress, separate normalization/detection/sink workers, ClickHouse, PostgreSQL | Service/adaptor code, SQL, Compose and live test harness implemented in 0.2; live runtime unverified | Execute container/cluster integration and failure tests |
| 3 | Vector enrollment, vendor collection, OCSF conformance, signed package lifecycle | Sample local package mechanism only | Real vendor fixtures and signed upgrade/rollback |
| 4 | Sigma compiler, Flink sequences/windows, rule shadowing | One custom fixed-bucket rule only | Golden detection corpus and late/replay/state tests |
| 5 | Complete cases, entity timelines, threat intel, response workflows | Minimal case creation only | End-to-end analyst and response tests |
| 6 | Independent monitoring and safe remediation | Local metrics plus distributed stage receipts, heartbeats, bounded retries and replay | Fault injection, action ledger and rollback validation |
| 7 | SSO, tenant hardening, HA, regional/offline profiles, commercial operations | Requirements defined | Security, soak, restore and support certification |
| 8 | Explainable UEBA and optional AI assistance | Planned | Measured usefulness, isolation and safety evaluation |

## Immediate next implementation tasks

- Create production service schemas and API specification from the reference contracts.
- Execute the new staging/Kafka path against real services; source enrollment remains planned.
- Run the implemented normalized publishing and independent ClickHouse/archive writers under real partial-batch, redelivery and outage conditions.
- Validate one Vector source end-to-end through restart, outage and full-buffer conditions.
- Add the first real source package based on vendor documentation and representative fixtures, not only sample JSON.
- Port the existing correctness tests to the distributed test harness; expand for quorum and network failures.
- Add OIDC identity and bounded query compilation before any external exposure.

## Build vs adopt

Adopt durable log, analytical storage, identity primitives and workflow orchestration. Build the integration contract, detection mapping/compiler, tenant policies, operational explanations and unified analyst experience. Avoid writing a custom broker, database, identity provider or general-purpose regex engine.

## Source and evidence status

The local build has no external runtime dependencies. The optional distributed profile has explicitly pinned external clients and container images; those were not installed or executed in the restricted authoring environment. Product name and source licensing remain owner decisions before public distribution; no public repository, deployment or account was created. The research does not transfer any employer data or configuration into the new project.
