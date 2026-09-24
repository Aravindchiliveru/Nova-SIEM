# Product requirements and entity model

## Intended global product

A vendor-neutral, distributed security operations platform for organizations and managed security providers. Deployment choices: managed service, customer-cloud/self-hosted cluster, and an offline distribution. Ship one certified cluster profile first; additional profiles require their own upgrade, backup and security certification.

The old platform creates no implementation constraint. No migration feature is part of this initial scope. The working name Nova requires trademark/domain review before commercial use.

## Must have before general availability

| Domain | Required capability | Proof |
|---|---|---|
| Collection | Syslog/TLS, HTTPS, OTLP where appropriate, cloud/API and endpoint packages, checkpointed collectors | Protocol failures and retry tests on supported versions |
| Data quality | Schema validation, raw evidence linkage, parser versions, quarantine/replay, freshness/completeness | Malformed/drift fixtures and no silent loss of acknowledged evidence |
| Security model | SSO, MFA policy integration, service identity, RBAC/ABAC, immutable tenant binding | Adversarial tenant tests across every interface |
| Detection | Single-event, thresholds, sequences, entity joins, rule testing/canary/rollback | Golden tests, lateness/replay tests, false-positive evaluation |
| Investigation | Fast hunting, saved searches, timeline, raw event access, evidence export | Usability study and query workload benchmark |
| Cases | Assignment, notes, evidence, status transitions, SLA and audit | Workflow invariants and access tests |
| Automation | Durable actions, approval policy, dry-run, retries, cooldown, idempotency | Failure/duplicate execution scenarios |
| Integrations | Signed packages, dependency/version checks, sample preview, coverage status, rollback | Install/update/rollback without core modification |
| Operations | Independent monitoring, stage delays, backlog age, cost/capacity, safe recovery | Synthetic canaries and failure injection |
| Reliability | HA, rolling upgrade, backup/restore, bounded queues and overload behavior | Documented outage and recovery drills |
| Data governance | Retention classes, residency, legal holds, auditable authorized deletion and export | Technical controls verified against contracted requirements |
| Global usability | UTC storage with user timezones, localization framework, keyboard/screen-reader support | Accessibility and locale tests |
| Commercial operation | Metering, licensing inventory, SBOM, vulnerability response, support diagnostics | Release checklist and support runbooks |
| MSSP model | Organization hierarchy and explicit delegated access, per-customer quotas | No implicit cross-customer access |

A feature plan is not a certification or compliance statement. Jurisdiction-specific requirements and customer contracts need separate review before sale.

## Should have after the core is dependable

Explainable UEBA; asset/identity risk; detection coverage linked to actual available fields; STIX/TAXII threat-intelligence exchange; EDR/NDR/vulnerability context; guided investigations; portable detection packs; customer-managed encryption keys; archive query acceleration; API/SDK integrations; regional failover; ticketing/notification integrations; notebook workflows; public integration SDK and partner certification.

AI is optional assistance: cited summaries, query drafts and parser/rule suggestions. It must respect tenant and field permissions, redact secrets, treat event text as untrusted input and never silently authorize remediation. The platform must work without an external AI service.

## Entities

| Entity | Identity and relationships |
|---|---|
| Organization | Commercial owner; explicit delegation relationships |
| Tenant | Primary authorization and residency boundary; quotas and retention |
| Workspace | Tenant-scoped analyst scope and saved views |
| Principal | Human/service identity, role grants and policy attributes |
| Collector | Authenticated tenant binding, enrollment, version, checkpoint, health |
| Source | Vendor/product instance; source identity independent of changing IP |
| Integration package | Immutable version, digest/signature, fixtures, mappings, permissions |
| Integration installation | Package version + source/collector + secret references + rollout state |
| Raw event | Stable tenant/source/event identity and original bytes/time/provenance |
| Normalized event | Schema class/version and parser lineage, linked to raw event |
| Asset / identity | Scoped entity with time-bounded aliases and provenance |
| Detection rule | Immutable rule version, prerequisites, tests and cost budget |
| Alert | Rule version, evidence IDs, evaluation window, severity and confidence |
| Incident / case | Related alerts/entities, ownership, workflow and evidence |
| Action / playbook run | Requested effect, authorization, idempotency key and expiry |
| Data-quality issue | Source/parser failure, impacted interval and recovery state |
| Retention policy / hold | Storage scope, expiry constraints and audited change history |
| Audit record | Actor/action/resource/outcome/time; externally protected trail |
| Usage record | Tenant-scoped bytes, processing/storage/query use and cost attribution |

In the initial reference, only credentials, integration activation, raw/normalized events, quarantine, a processing ledger, alerts, minimal cases and audit records are implemented.

## Convenience requirements

First-run setup discovers capacity and validates dependencies. Integration wizard asks only required connection details, validates a real sample, explains missing telemetry, previews cost and activates safely. Default dashboards work immediately. Empty states tell the user the next action. A rule's status distinguishes enabled, receiving inputs, healthy, and effective coverage.

One-click troubleshooting produces a redacted support bundle and a clear measured explanation. One-click recovery executes a known policy with verification; it is not unrestricted shell access. No silent destructive cleanup. Display estimated vs measured latency and data completeness.

Provide guided mode for routine users and advanced APIs for specialists. An installable package should carry parser, mappings, rules, dashboards, health checks, fixture tests, resource budget, version compatibility and signed rollback artifacts.

## Competitive acceptance

Declare workloads and costs, then target demonstrable reductions in integration time, analyst steps, delayed detections, storage cost and operational intervention. Do not claim that using newer databases or AI proves a better SIEM. A global product also requires maintained content, support, operational discipline and trustworthy releases.
