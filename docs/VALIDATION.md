# Validation — 0.8

313 automated tests pass; log: `test-output-v0.8.txt`. Added tests cover complete document retrieval, legacy/tenant boundaries, nested arrays, exact scalar types, null versus absence, rejected paths and values, schema failures entering quarantine, schema bounds, package class binding, bound distributed SQL, distributed document decoding and source-preserving OCSF profile export.

SQLite behavior ran end to end. ClickHouse queries and reads use compiler/transport tests only; no live ClickHouse or replicated service was available. New OCSF profiles have local fixtures, not full upstream schema conformance tests. Upstream schema retrieval and JSON Schema dependency installation failed; the delivered Nova schema v1 contract is explicitly not a JSON Schema implementation.

Python compilation and JavaScript syntax checks passed. Browser rendering/accessibility was not tested. The structured microbenchmark is separately scoped in `benchmarks/structured-v0.8.json`; old HTTP throughput reports remain historical. Production HA/DR, remote immutability and full OCSF/Sigma conformance are still unproven or incomplete.
