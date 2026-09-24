# Nova SIEM — v0.3

A new SIEM development project, independent of the previous work platform. This release adds measurable local processing improvements, reliable file collection, configurable detections, investigation workflows, and opt-in identity/package verification.

**Development release, not a complete enterprise security product.** Distributed deployment has not been executed in this environment. The measurements below are local synthetic workloads, not vendor comparisons or production capacity promises.

## Start in one command

Requires Python 3.12 on Linux for the complete collector/recovery feature set.

```bash
python3 run.py
```

Open http://127.0.0.1:8787 and use the admin token in `data/local-tokens.json`. Activate **Authentication JSON**, then choose **Send test sequence**. Review Detections, create a case, add notes, and update its status. Disconnect clears the token from the console's application state.

The default local profile requires only the Python standard library. Signature verification and JWT validation additionally need `requirements-security.txt`; they are opt-in. Do not expose this development HTTP server publicly.

## What changed

- Normalization and detection now operate in bounded transactional batches, retaining SQLite WAL and `synchronous=FULL`.
- Four JSON-configured rules: repeated failures, password spraying, account guessing from multiple IPs, and privileged authentication. Same rule evaluator is wired into local and PostgreSQL workers.
- Rule catalog and sample simulation; exact matching, fixed event-time windows, distinct counts, revisioned state and bounded evidence.
- Durable NDJSON collector with file checkpoints, acknowledgement verification, bounded retry, circuit breaking, and malformed-record quarantine.
- Adapters for exported Windows 4624/4625 JSON, CloudTrail ConsoleLogin JSON, and timestamped OpenSSH authentication messages; original source objects are retained.
- Cases support status changes and analyst notes. Event search has IP/outcome/time filters and raw event inspection.
- Optional Ed25519 signatures for integration and rule packages; required-signature mode fails closed.
- Optional RS256 JWT resource-server authentication with pinned JWKS/issuer/audience, mandatory `at+jwt` type, and locally assigned tenant/role grants. This is **not** a complete browser SSO flow.
- Request concurrency/rate bounds, credential expiry/revocation flags, local diagnostics, online SQLite snapshots, checksum-verified restore to a new path.
- Reproducible engine and real HTTP benchmarks, plus process-kill recovery checks.

## Measured results

Three runs per workload, 5,000 events each, direct local Engine calls:

| Workload | v0.2 median EPS | v0.3 median EPS | Ratio |
|---|---:|---:|---:|
| success | 299 | 15,256 | 51.1× |
| mixed | 287 | 11,600 | 40.4× |
| hot-failures | 176 | 8,305 | 47.3× |

The HTTP benchmark used four producers, two concurrent search clients, and 10,000 events per run. Median completed throughput: **3,357 EPS**. All three runs verified 10,000 accepted and normalized records, zero quarantine records, and no worker error.

Read [BENCHMARKS.md](docs/BENCHMARKS.md) for raw measurements, environment, differences between versions, and limitations. Fast short local runs do not establish sustained distributed throughput.

## Operating guides

- [Upgrade and capability matrix](docs/RELEASE_v0.3.md)
- [Collector setup and input contracts](docs/COLLECTORS.md)
- [Rules and investigation workflows](docs/DETECTIONS.md)
- [Signatures and identity configuration](docs/IDENTITY_AND_PACKAGES.md)
- [Recovery and diagnostics](docs/OPERATIONS.md)
- [Executed validation and open gates](docs/VALIDATION.md)
- [Distributed lab](docs/DISTRIBUTED_LAB.md)

```bash
python3 -m pip install -r requirements-security.txt
python3 -m unittest discover -s tests -v
python3 tools/check_recovery.py
python3 tools/benchmark_suite.py
python3 tools/benchmark_http.py
```

The security dependency's deployment pin is 50.0.1. It could not be installed from this environment's package source; crypto tests here used preinstalled 46.0.0. Rerun the suite with the deployment pin before release.

## Distributed lab

```bash
python3 tools/cluster.py start
python3 tools/cluster.py verify
python3 tools/cluster.py fault-test
```

Docker Compose provides PostgreSQL, Kafka, ClickHouse, and separate workers. These commands have **not passed a real cluster run here**. This single-node lab is not an HA topology. Existing production release gates remain open.
