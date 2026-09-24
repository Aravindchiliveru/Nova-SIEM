# Validation — v0.5

222 automated tests passed; complete output is `test-output-v0.5.txt`. Twelve typed-event tests and one real HTTP typed ingestion/search/isolation test extend the previous 209-test suite. Coverage includes all five new categories, quarantine for malformed fields, optional context, migration/idempotent restart, tenant boundaries, bound queries, legacy wire compatibility, native rule simulation/activation/evidence and durable collector routing with verified acknowledgement. Existing package fixtures exercise startup validation.

Three HTTP runs, three five-category engine runs, six fixed/advanced engine runs, and 50 internal workflows were executed. A saved v0.4 HTTP rerun measured the same environment; v0.5 was slower in this sample. See BENCHMARKS.md for exact scope and caveats. JavaScript syntax checked successfully.

No live Kafka/PostgreSQL/ClickHouse infrastructure, Docker runtime, browser rendering/accessibility, production IdP, external vendor collection/response, immutable storage, multi-node recovery or commercial comparison was tested. Distributed serialization, query generation and adapter behavior are code paths with test doubles. They are not proof of live database/queue semantics or migration success.

Installed cryptography 46.0.0 provided actual crypto tests. The optional deployment pin 50.0.1 is not installed or validated here. Existing process-kill recovery results are from v0.3; v0.5 did not repeat physical crash/disk/power tests. Category metadata defaults assume all prior normalized rows came from the original authentication-only contract. Original raw parsed JSON remains available; wire-byte/WORM preservation is not implemented.
