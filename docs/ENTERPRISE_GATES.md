# Enterprise product readiness — still blocked

The user target is enterprise superiority over commercial SIEMs. That target has **not been achieved or demonstrated**. The following are release requirements, not claims that documentation/configuration substitutes for implementation.

| Required capability | Current state | Evidence needed to close |
|---|---|---|
| Broad collection | Direct journald/CloudTrail interval adapters plus NDJSON contracts | Native endpoint/cloud/network collectors, backpressure, rotation, vendor fixture matrices and upgrade lifecycle |
| Common schema | Six native categories, lossless nested document retrieval/search, Nova typed schema contracts and three OCSF projection profiles | Richer structured fields, validated OCSF mappings and live distributed migration |
| Detection coverage | Nine native rules plus a strict Sigma subset importer | Full Sigma support, broad tested rule corpus, ATT&CK mapping, field false-positive/negative studies |
| Streaming scale | Bounded SQLite/PG rule state; development Kafka pipeline | Partition-aware checkpoints, bounded lateness/TTL, high-cardinality state, live throughput and recovery |
| Tenant security | Application tenant binding, roles, source-bound collectors and tenant rule overrides | Database/storage policy enforcement, tenant quotas/fairness, MSSP delegation, independent isolation testing |
| Identity | Opt-in pinned-JWKS resource-server validation | Browser OIDC/PKCE, session lifecycle, rotation/discovery, enterprise IdP integration and logout testing |
| Response | Internal workflows, approved HTTPS actions and Defender isolate/unisolate with durable intent | Broad vendor actions, live Defender qualification, uncertain-action reconciliation, compensation and provider tests |
| Evidence | Checksums, linked audit and remote Object Lock adapter | Original-wire preservation, automatic independent anchoring, object-lock/WORM, chain-of-custody operations |
| Storage lifecycle | Object Lock retention adapter; local capacity; no automatic deletion | Tenant retention, legal holds, tiering, encrypted object archive, query/restore, deletion verification |
| Reliability | Local crash/restore, durability preflight and live fault harness | Real HA topology, rolling upgrades, backup/restore across stores, multi-node/region DR, SLO and error-budget evidence |
| Analytics | Typed event search and nine starter rules | Threat intelligence, entity graph, behavioral analytics, investigation pivots and coverage evaluation |
| Product operations | Local console, external action review, metrics, case notes and parser previews | Accessibility, onboarding, API versioning/SDK, supportability, fleet upgrades, licensing and metering |
| Supply chain | Optional package signatures and dependency pins | Full SBOM, tested current dependencies, advisory scanning, build provenance, key revocation/anti-rollback |
| Market superiority | No commercial comparison | Same dataset/hardware/durability/query/rule workloads against named alternatives; independently reviewable functional, operational and cost outcomes |

A feature checkbox or synthetic EPS score cannot close these gates. The immediate infrastructure blocker remains unavailable Docker/PostgreSQL/Kafka/ClickHouse services in this environment. Implementation gaps remain as well; obtaining infrastructure alone will not make this enterprise-ready.

Prioritize richer schema mappings and native collection, then the production streaming/storage/isolation path, then full identity and external response. Prove each with live integration/recovery tests and a long-duration benchmark. Do not deploy this development server as a public production SIEM.
