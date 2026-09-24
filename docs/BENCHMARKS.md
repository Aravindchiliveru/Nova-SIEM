# Benchmarks — v0.7

Shared container, Python 3.12.14, SQLite FULL WAL. Synthetic loopback HTTP data; four producers and two concurrent search clients. Three runs of 10,000 events, measuring acceptance through drained normalization/detection queues. No live external response jobs or immutable archive operations in this workload.

Current median: **1,871 completed events/second**. The 0.6 release was rerun from its unchanged delivered archive in this same runtime and measured **1,825 median EPS**. The difference is 2.5%. These sequential short trials are not statistically sufficient to claim a performance improvement.

| Run | Completed EPS | Search p95 ms | Accepted / normalized |
|---|---:|---:|---|
| 1 | 1,871 | 26.61 | 10000 / 10000 |
| 2 | 1,818 | 23.60 | 10000 / 10000 |
| 3 | 1,879 | 25.11 | 10000 / 10000 |

All runs had zero quarantine and no worker error. RSS includes clients and cumulative process high-water usage. This is not sustained capacity, first-search-visible latency, resource sizing or production HA throughput.

The earlier 0.6 run measured 2,728 median EPS in a different runtime session. The current 0.6 rerun demonstrates why that historical number cannot be used directly to assert a regression or optimization. Raw current and baseline results are `benchmarks/http-results.json` and `benchmarks/v0.6/http-rerun-v07-environment.json`; the original baseline is preserved alongside them.

Historical typed/advanced result files describe 0.5 code. They were not rerun or relabeled as 0.7. `benchmarks/recovery-v0.7.json` records the repeated local crash/SQLite restore drill. Actual process-kill Defender ambiguity handling is also tested in `tests/test_vendors.py`. Neither establishes production RTO/RPO.

Reproduce throughput with `python tools/benchmark_http.py`. Live HA and retention reports remain explicitly **not_run** in `benchmarks/ha-qualification-v0.7.json` and `benchmarks/retention-qualification-v0.7.json`.

## Structured-event microbenchmark — 0.8

`python tools/benchmark_structured.py` processes 3,000 schema-validated nested events locally and executes 100 nested-field queries with complete documents returned. Raw evidence: `benchmarks/structured-v0.8.json`. This is a single-process SQLite microbenchmark, not the HTTP workload above or a production sizing result. It checks returned document values and event counts; no distributed service participates.
