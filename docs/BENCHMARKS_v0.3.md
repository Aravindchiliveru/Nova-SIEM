# Benchmarks — v0.3

Executed 20 September 2026. Raw machine-readable results and exact scripts are included. No performance number in this report represents a production SLA or a comparison with commercial SIEMs.

## 1. Direct engine comparison

| Workload | v0.2 median EPS | v0.3 median EPS | Ratio |
|---|---:|---:|---:|
| success | 299 | 15,256 | 51.1× |
| mixed | 287 | 11,600 | 40.4× |
| hot-failures | 176 | 8,305 | 47.3× |

- 5,000 synthetic authentication events per run; 3 repetitions for each version/workload (18 runs, 90,000 events total).
- Both versions: 500-event ingestion batches, the same payloads, SQLite WAL, synchronous FULL, initially empty database, one tenant, one producer, identical host environment.
- Success workload: no detections. Mixed: 20% failures, 100 repeating actors, one IP. Hot failures: all events fail for one actor/IP in one fixed bucket.
- Event generation occurs before timing. Timing includes ingestion and complete normalization/detection draining, but excludes Engine startup, post-run search probes and integrity checks.
- v0.3 uses four rules; v0.2 uses one hardcoded rule. v0.3 caps retained alert evidence at 100 IDs; v0.2 stores all IDs. This is a whole-version comparison, not an isolated batching experiment or fully identical output contract.
- Versions alternate run order; each measurement is a new subprocess. EPS is events divided by total ingest-plus-process wall time. Ratios compare medians, not best runs.
- Each run checks accepted/normalized counts, empty pending queues, duplicate retry behavior, tenant isolation, SQLite integrity and FULL durability setting. Hot failures must produce the original repeated-failure alert.
- Raw results also include CPU seconds, peak process RSS, database bytes, ingest batch p95, and 100 post-load search timings. Small sample tail percentiles are descriptive, not statistically stable production estimates.

The preserved v0.2 core and original integration fixtures are in `benchmarks/baseline_v0_2/`. SHA-256 values identify the compared cores in `benchmarks/results.json`.

Reproduce:

```bash
python3 tools/benchmark_suite.py --events 5000 --repeats 3
```

## 2. Real HTTP and concurrent queries

Each run starts the real Nova HTTP server and background worker. Four producer threads send 100-event batches while two readers execute actual tenant-scoped search requests. Each run contains 10,000 mixed events; data is synthetic. Three runs, 30,000 events total.

| Run | Completed EPS | Completion seconds | Search p95 ms | Stored receive-to-normalize p95 ms | Process peak MiB |
|---|---:|---:|---:|---:|---:|
| 1 | 3,357 | 2.979 | 13.05 | 937.2 | 29.0 |
| 2 | 3,294 | 3.036 | 13.92 | 818.7 | 29.4 |
| 3 | 3,493 | 2.863 | 12.31 | 1629.6 | 29.4 |

Median throughput: **3,357 EPS**. Search latency is measured at the HTTP client. Receive-to-normalize uses stored timestamps and is not a measurement of first searchable visibility; normalization timestamps precede transaction commit. Completion includes empty normalization and detection queues.

Peak RSS covers the combined server/worker/client Python process, not just the SIEM. These three runs share a process, so the OS RSS high-water mark is cumulative. CPU seconds are per-run deltas. Readers poll with a 25 ms pause; this is not unlimited query load. Authentication uses local opaque test credentials; JWT performance is not benchmarked.

Reproduce: `python3 tools/benchmark_http.py`. Results: `benchmarks/http-results.json`.

## 3. Environment and interpretation

Python 3.12.14; SQLite 3.53.1; Linux-6.18.44-x86_64-with-glibc2.39. Container reports 9 logical CPUs, with a cgroup quota of 8 CPU equivalents and a 14 GiB memory limit. The workspace filesystem's underlying device, cache behavior and hardware fsync guarantees are unknown. The runtime is shared; exclusive host access was not guaranteed. No memory/disk/network isolation experiment was performed.

The primary gain is removal of per-event connection/transaction and repeated pending-query overhead through bounded batches. FULL durability remains enabled. The old reference was deliberately simple and inefficient; a large ratio against it does not establish superiority over other products.

## 4. Recovery evidence

`python3 tools/check_recovery.py` kills a real child process with SIGKILL after accepting 500 events, reopens the database, and confirms all 500 normalize with one repeated-failure alert. A second kill during an uncommitted delete confirms rollback preserves all 500 normalized events. SQLite integrity passes. Results: `benchmarks/recovery-results.json`.

This checks process failure, not power loss, media corruption recovery, PostgreSQL failover or Kafka replication.

## 5. Required production benchmark gate

Still unexecuted: actual Kafka/PostgreSQL/ClickHouse ingestion; 24-hour sustained workloads; multi-node failover; tenant fairness; realistic mixed source sizes; parser complexity; 30/90-day query datasets; retention/compaction load; archive restore; disk-full and network partitions; encryption overhead; p99 detection visibility; cost per retained TB and per 1,000 EPS. Report hardware, replication, durability, event sizes, query mix, loss/duplicates and tail latency together. There is no supported production EPS sizing number yet.
