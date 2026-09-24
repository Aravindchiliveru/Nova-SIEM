# Validation report — v0.3

Executed 20 September 2026. See `test-output-v0.3.txt` for full automated output.

## Executed

- **165 automated tests passed in 11.641 seconds**: existing local/API/distributed contract regressions; batched detection rollback; distinct-count rules; tenant boundaries; collector checkpoints/retention/retry/ack validation; actual collector HTTP duplicate-ack recovery; signed package tampering/unknown-key rejection; JWT signature/algorithm/type/issuer/audience/time/subject authorization; case notes/status; snapshots and restore; request limits.
- **18 direct-engine comparative benchmark runs**, 5,000 events each: original v0.2 versus v0.3; success/mixed/hot-failure workloads; three repetitions each.
- **3 real HTTP concurrent-load benchmark runs**, 10,000 events each: 4 producers and 2 search clients; verified processing completion and database integrity. Detailed results in `BENCHMARKS.md`.
- **Real SIGKILL recovery checks**: 500 acknowledged events survive restart; an interrupted uncommitted transaction rolls back; normalized count and integrity verified.
- Python compilation and JavaScript syntax checks passed.
- Collector CLI smoke test imported five OpenSSH JSON records, delivered them over the actual local HTTP API using the generated-token-file format, and confirmed five normalized events plus one alert.
- Cluster doctor was rerun and reported Docker unavailable (exit 2).
- Optional signature/JWT crypto tests used the real preinstalled cryptography 46.0.0 implementation, not cryptographic mocks.

## Not executed or proven

- Docker, PostgreSQL, ClickHouse and Kafka services remain unavailable here. Distributed adapter tests use doubles; real PostgreSQL SQL/migrations, broker behavior, image builds, permissions, Compose startup and distributed failover/performance have not been validated.
- The deployment crypto pin is 50.0.1. Attempted installation returned no matching distribution from the available package source. Tests with that version and the updated image build remain gates.
- No live identity provider, browser authorization flow, remote TLS deployment, browser rendering/accessibility run, long-duration soak, hardware power-loss test, penetration test, dependency vulnerability scan, WORM validation or regulatory certification was performed.
- CI definitions are included, but have not been published or executed on a remote runner.

One pre-existing oversized-request test exposed a client/server timing race: the server could send 413 and close while the client was still transmitting the oversized body. The test now sends an oversized declared Content-Length and checks rejection before sending a body; the server limit remains enforced.

## Reproduce

Install deployment dependencies in an isolated environment, then run:

```bash
python3 -m unittest discover -s tests -v
python3 tools/check_recovery.py
python3 tools/benchmark_suite.py
python3 tools/benchmark_http.py
python3 tools/cluster.py start
python3 tools/cluster.py verify
python3 tools/cluster.py fault-test
```

A local pass cannot substitute for the last three live-service gates. Production capability gaps are explicit in `RELEASE_v0.3.md`.
