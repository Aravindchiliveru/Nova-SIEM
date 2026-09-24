# Implementation research — 20 September 2026

Decisions rely on primary documentation; measurements come from this project's runnable tests. No benchmark superiority was inferred from vendor marketing.

- SQLite documents WAL commit synchronization under FULL: retain FULL and optimize transaction batching instead of weakening durability. https://www.sqlite.org/wal.html and https://sqlite.org/pragma.html
- Sigma describes a broader detection/correlation format. Nova's exact-match fixed-window rule JSON is explicitly a native subset of capabilities, not a Sigma interpreter or conformance claim. https://sigmahq.io/
- Microsoft documents Event 4625 and its account/address fields. Nova requires an explicit JSON export contract and does not claim every Windows authentication has a source IP. https://learn.microsoft.com/en-us/previous-versions/windows/it-pro/windows-10/security/threat-protection/auditing/event-4625
- AWS documents ConsoleLogin event objects, responseElements and userIdentity. Nova consumes one such object per line and does not fetch CloudTrail itself. https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-event-reference-aws-console-sign-in-events.html
- PyCA documents Ed25519 sign/verify and RSA primitives. Nova uses that implementation, not custom cryptography. https://cryptography.io/en/latest/hazmat/primitives/asymmetric/ed25519/
- RFC 8725/7519 inform algorithm allowlisting, strict JSON, pinned issuer/audience, subject validation, token type separation and claim checks. This is not third-party security certification. https://www.rfc-editor.org/rfc/rfc8725.html and https://www.rfc-editor.org/rfc/rfc7519.html
- Upstream cryptography changelog lists 50.0.1 (2026-08-25) and intervening security fixes. This is the deployment pin; the available test runtime contains 46.0.0. Installing 50.0.1 failed because the package source returned no distributions, so release compatibility remains unverified. https://cryptography.io/en/latest/changelog/

The distributed component choices remain hypotheses to validate through live cluster benchmarks. The current PostgreSQL staging/detection path is intentionally bounded and is not the final high-throughput streaming architecture.
