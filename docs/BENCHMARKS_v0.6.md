# Benchmarks — v0.6

Shared container runtime, Python 3.12.14, SQLite FULL WAL. Synthetic data; no exclusive hardware/disk guarantees, live cloud, distributed services or commercial comparator.

Fresh default HTTP profile: **2,728 median EPS**, three runs of 10,000 events, four producers and two concurrent search clients. Event acceptance through drained normalization/detection queues is measured. External action jobs are absent.

| Run | Completed EPS | Search p95 ms | Accepted / normalized |
|---|---:|---:|---|
| 1 | 2,618 | 17.26 | 10000 / 10000 |
| 2 | 2,839 | 16.70 | 10000 / 10000 |
| 3 | 2,728 | 19.16 | 10000 / 10000 |

All three runs had zero quarantine and no worker error. RSS includes benchmark clients and is cumulative process high-water usage. This is not first-search-visible latency, sustained capacity or HA throughput.

Historical v0.5 throughput and its measured regression are retained in `docs/BENCHMARKS_v0.5.md` and `benchmarks/v0.5/`. Runtime variation is substantial: do not attribute this new median to an optimization win without controlled paired trials. Root typed/advanced result files still describe the older v0.5 code and are not new v0.6 claims.

Reproduce the HTTP profile with `python3 tools/benchmark_http.py`. Run the local crash/restore drill with `python3 tools/check_recovery_v06.py`. Raw current results: `benchmarks/http-results.json`, `benchmarks/recovery-v0.6.json`.

Live HA qualification is explicitly `not_run` in `benchmarks/ha-qualification-v0.6.json`. External actions, S3 retention enforcement and CloudTrail acquisition have no live throughput or recovery benchmark here.
