> v0.4: Current behavior and remaining gates are documented in ENTERPRISE_CONTROLS.md, CORRELATION.md, VALIDATION.md and ENTERPRISE_GATES.md. Newer guides take precedence over this historical description.

> v0.3 update: see [RELEASE_v0.3.md](RELEASE_v0.3.md) and [VALIDATION.md](VALIDATION.md) for current implementation status. The previous single-rule detector is replaced by the shared declarative rule evaluator; package signatures and JWT access-token validation are optional additions. Distributed runtime validation remains open.

# Security boundaries and release gates

## Current local reference

Loopback only, randomly generated bearer tokens with hashed server-side credentials, role permissions, authenticated tenant binding, SQL parameters, strict body sizes, JSON duplicate-key rejection, exact static-asset allowlist, Host/Origin checks and restrictive browser CSP. No arbitrary plugin code and no shell execution. Tokens in the browser remain in memory, not localStorage. Local token file contains plaintext secrets and must stay private. Operating-system administrators can read/modify the database; audit is not tamper-proof.

No TLS/SSO/OIDC, token expiry/rotation API, online enrollment, per-second rate limiter, row-level database security, encryption layer, signed package distribution, comprehensive audit of every read, high availability or public server hardening is implemented. These omissions prohibit production/public exposure. Body limits and tenant event caps are development bounds, not complete denial-of-service protection. HTTP threads and SQL scans are not a large-scale service model.

## Threat model

Untrusted event payloads can contain adversarial strings, enormous nested objects, incorrect timestamps, secrets and misleading instructions. Treat them as data; no eval, shell or model-mediated action authorization. Restrict integration permissions and outbound destinations. Prevent source impersonation with enrollment identity rather than an arbitrary source/IP header.

Adversarial tenants may attack every query, case, export, cache, report, background job and object path. Binding tenant identity only in UI is insufficient. Delegated administrators need explicit scope and audited break-glass rules. Credentials embedded in logs/support bundles must be redacted.

Retry/replay, clock errors and partial failures can duplicate records or actions. Stable IDs, checkpoints, bounded state, immutable raw provenance and action ledgers are security controls as well as reliability controls. Detect loss of telemetry as a security-relevant coverage issue.

## Production gates

1. OIDC integration, short-lived credentials, enrollment and revocation; TLS/mTLS where appropriate.
2. Tenant enforcement in API, query compiler, database credentials/policies, object paths and background jobs; adversarial tests.
3. Signed packages and releases, provenance, dependency lockfiles/SBOM, vulnerability and license review.
4. Isolated plugin runtime, CPU/memory/time limits, secret scoping and egress restrictions.
5. Immutable or independently protected audit/evidence with tested retention/hold/restore behavior.
6. Controlled query budgets, collector/API quotas, admission control and overload behavior.
7. Independent penetration test; incident response and vulnerability disclosure process.
8. Least-privilege remediation actions; approval policy, idempotency, expiry, verification and compensation.
9. Data residency and customer-policy enforcement in backups, support, monitoring and AI.
10. Restore drills, rolling upgrades, fault injection and externally verified service monitoring.

No compliance certification is implied by this list. No automatic destructive repair is implemented in the reference.

## Distributed laboratory additions in 0.2

The optional Compose profile publishes host ports only on loopback and generates separate lab secrets. A direct gateway process also defaults to loopback; Compose explicitly changes its container bind address. Internal broker traffic is plaintext, backend service credentials are shared, and PostgreSQL tenant isolation depends on the application. This is not appropriate for untrusted tenants. TLS/OIDC, Kafka ACLs, per-service database privileges and independently enforced tenant policy remain production gates.

The pipeline adds digest checks, snapshot-bound parsers, explicit consumer offset commits and archive checksum checks. Adapter tests use doubles; they do not certify the distributed fault model. The local filesystem archive is neither tamper-proof nor a backup. The example detector and receipt registry retain bounded-lab state without an automatic cleanup policy. Refer to DISTRIBUTED_LAB.md before running the new profile.
