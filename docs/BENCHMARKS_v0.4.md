# Benchmarks — v0.4

Executed during 20–21 September 2026 in a shared container runtime. Python 3.12.14; SQLite WAL + synchronous FULL; 9 visible CPUs with an 8-CPU-equivalent quota and a 14 GiB memory limit. Underlying storage hardware/cache guarantees and exclusive host access are unknown. These measurements are not production sizing, long-term capacity or commercial-SIEM comparisons.

## Real HTTP profile

Three runs of 10,000 synthetic mixed authentication events, four producer threads, two concurrent search clients, fixed rules enabled, new advanced rules disabled. Actual HTTP server, background processing and SQLite queries were executed. Median completed throughput: **3,177 EPS**.

| Run | Completed EPS | Search p95 ms | Accepted / normalized |
|---|---:|---:|---|
| 1 | 3,216 | 13.07 | 10000 / 10000 |
| 2 | 3,177 | 15.70 | 10000 / 10000 |
| 3 | 3,136 | 15.18 | 10000 / 10000 |

Every run verified zero quarantine records, no worker error and complete normalization/detection progress. Timing includes event acceptance through empty processing queues. Authentication uses local opaque test credentials; no JWT/TLS overhead is measured. Peak RSS in raw results is a process high-water mark, including benchmark clients; runs share a process. Stored receive-to-normalize lag is not first-searchable-visibility latency.

Reproduce: `python3 tools/benchmark_http.py`. Raw data: `benchmarks/http-results.json`.

## Advanced detection workload and its cost

Three runs each, 5,000 records and 50 entities, timestamps increasing per entity, nine failures followed by a success in each ten-event sequence. The baseline in this comparison is **v0.4 with fixed rules**, not v0.3.

| Profile | Median EPS | Additional expected alerts |
|---|---:|---|
| Fixed rules | 1,877 | None from new rules |
| Fixed + sliding + sequence | 1,427 | 4,300 sliding and 500 ordered-event alerts |

The advanced profile checks exact expected counts. It creates thousands more alerts than the fixed-only profile and uses additional persistent correlation state. The difference measures the cost of this workload, not equivalent-detection speed. Correlation recalculates only affected historical anchors while retaining late-event correctness. It remains bounded development state, not a proven high-scale streaming engine.

These are direct Engine calls: event generation and rule setup are excluded; ingestion and normalization/detection are timed. Raw CPU times and process high-water RSS are included. The host was not reserved; expect variation between runs and machines.

Reproduce: `python3 tools/benchmark_enterprise.py`. Raw data: `benchmarks/enterprise-results.json`.

## Internal workflow execution

50 pre-approved workflows executed 150 transactional steps in **0.095 seconds**, producing exactly 50 notes in one shared case. Each workflow completed, and linked audit history verified. This is a small internal database-action test; it excludes approval/request creation time and has no vendor API/network latency. It is not a SOAR throughput claim.

## Historical benchmarks

v0.3 raw results are retained in `benchmarks/v0.3/`, and its report in `docs/BENCHMARKS_v0.3.md`. The previous 40–51× figures compared v0.3 with the intentionally simple v0.2 engine. They do not describe the new advanced profile and are not a commercial comparison. The optional engine comparison script now labels current runs v0.4 and writes a separate `engine-v0.4-results.json`.

## Unexecuted requirements

No live Kafka/PostgreSQL/ClickHouse benchmark, 24-hour soak, multi-node failure, cross-region restore, WORM test, production-sized historical search, independent attack corpus, false-positive field study or vendor comparison was performed. Those are mandatory before claiming enterprise superiority.
