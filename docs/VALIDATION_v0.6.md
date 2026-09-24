# Validation — v0.6

264 tests passed in the final suite. Full log: `test-output-v0.6.txt`. Tests include legacy functionality, strict Sigma import/execution, OCSF projection, native acquisition/cursor transactions, external approval/RBAC/lease fencing/retry, actual TLS transport, Object Lock acknowledgement logic and fail-closed HA preflight decisions.

| Evidence | Executed here | What it does not establish |
|---|---|---|
| Unit/API suite | 264 passing tests | Live provider behavior or production load |
| HTTPS webhook | Real localhost TLS certificate verification, bearer request and completion acknowledgement | Vendor containment/idempotency semantics |
| Native journal | Cursor/parser and subprocess-interface fixtures; installed binary accepts an empty query | Populated-journal ingestion, permissions, vacuum/rotation continuity |
| CloudTrail | Mocked native API pages and durable tokens | Live account/region completeness, late-arrival coverage |
| OCSF | Selected 1.4.0 authentication projection fixtures | Complete upstream schema conformance |
| Sigma | Supported subset compiled, installed and executed | Unsupported modifiers/correlation or full rule-corpus parity |
| S3 Object Lock | Fake provider contracts, conditional retry, wrong-mode/content rejection, receipt ordering | AWS IAM/KMS/enforcement, deletion denial or real SDK serialization |
| Crash/restore | Actual SIGKILL, idempotent durable provider simulator, isolated SQLite restore | Disk/power failure, real external action, cross-store cluster restore |
| HA preflight | Decision tests with metadata doubles | Actual replication/failover/fencing |
| HA fault harness | Configuration validation only, explicit not_run report | No live fault scenario ran |

`benchmarks/recovery-v0.6.json` records 500 accepted events recovered, one provider effect across two activity claims, and restored audit checkpoint verification. The lease-expiry test advances the injected clock 61 seconds. Its measured duration is not a production RTO.

Python source compiled and JavaScript syntax checked. No browser rendering/accessibility QA ran. Installed cryptography 46.0.0 and PyYAML 6.0.3 supplied actual tests. The optional cryptography deployment pin 50.0.1 remains uninstalled/unvalidated here; boto3 installation failed because the runtime package source offered no distribution. AWS requirements are a range, not a production lockfile. Docker build and CI definitions were not executed remotely.

Test doubles are labeled as such. Production HA/DR, immutable retention enforcement, deployment dependency security and commercial superiority remain unproven.
