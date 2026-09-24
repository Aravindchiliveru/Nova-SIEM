# Benchmarks — v0.5

Executed 21 September 2026 in the shared container runtime. SQLite WAL with synchronous FULL; Python 3.12.14. No exclusive hardware, known disk guarantees, production service infrastructure, native vendor feeds, JWT/TLS overhead or commercial product is included. RSS is a cumulative process high-water mark, including any benchmark clients. Synthetic short runs do not establish sustained capacity or field detection quality.

## Measurements

| Profile | Runs / events per run | Median completed EPS | Scope |
|---|---|---:|---|
| Real HTTP | 3 / 10,000 | 1,750 | Four producers, two concurrent readers, default fixed authentication rules |
| Typed engine | 3 / 10,000 | 8,344 | Direct calls, five equally represented categories, cloud rule enabled |
| Advanced engine | 3 / 5,000 | 1,238 | Fixed plus sliding and ordered authentication rules |
| Fixed engine | 3 / 5,000 | 1,623 | Same advanced workload, fixed rules only |

These workloads do different amounts of work. Typed engine EPS is not HTTP ingress throughput and cannot be used as a claimed speedup over the authentication profile.

## HTTP run details

| Run | EPS | Search p95 ms | Accepted / normalized |
|---|---:|---:|---|
| 1 | 2,088 | 21.52 | 10000 / 10000 |
| 2 | 1,750 | 48.87 | 10000 / 10000 |
| 3 | 1,736 | 32.32 | 10000 / 10000 |

All runs assert zero quarantine and complete processing; stored receive-to-normalize lag is not first-query visibility latency.

## Same-environment v0.4 check

The saved v0.4 source was extracted and its identical HTTP harness rerun sequentially after v0.5, in the same runtime. Its median was **2,000 EPS**, against **1,750 EPS** for v0.5: the new release was **12.5% slower** in this sample. Its previous recorded median was 3,177 EPS. Runtime variation is substantial, and these are three sequential runs per version, not randomized paired trials. The result does not isolate the contribution of new columns/indexes/rules. It is an observed regression to investigate, not evidence of an optimization win.

v0.4 rerun EPS: 1,562, 2,000, 2,022. Raw rerun: `benchmarks/v0.4/http-rerun-v05-environment.json`. Historical release data remains in `benchmarks/v0.4/`.

## Typed correctness and response

Each typed run asserts exactly 10,000 raw and normalized records, zero quarantine, and exactly 100 cloud alerts. After draining, 100 category/action searches must each return the expected 100 records. SQLite integrity checks pass. This uses one tenant and straightforward exact matches; it does not test native collection, general threat coverage, high-cardinality streaming or noisy-neighbor isolation.

Typed search p95 by run: 2.00 ms, 3.00 ms, 2.13 ms.

The internal workflow benchmark completed 50 approved workflows / 150 steps in 0.118 seconds, checking exactly 50 case notes. This is database-only case automation; it measures no external service actions.

## Reproduction

```bash
python3 tools/benchmark_http.py
python3 tools/benchmark_typed.py
python3 tools/benchmark_enterprise.py
```

Raw JSON files under `benchmarks/` include per-run timing/counts; typed and advanced profiles include code hashes. The v0.3 recovery run remains historical evidence. Live Kafka/PostgreSQL/ClickHouse performance, multi-node failover, resource-cost comparison and commercial superiority remain unmeasured.
