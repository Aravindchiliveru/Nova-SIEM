# Validation report — 0.1.0

Executed 17 September 2026, Python 3.12.14 in the provided development environment.

## Passed

- `python3 -m unittest discover -s tests -v`: **47 tests passed**, 8.802 seconds in the final recorded run. Full output: `test-output.txt`.
- `node --check web/app.js`: JavaScript syntax validation passed.
- Live runtime integration: sample CLI subprocess → authenticated HTTP ingestion → background normalizer/detector → alert → HTTP case creation. This is included in the 47 tests.
- Storage outage simulation: worker stops after five failed transactions, reports the error and leaves the journal intact. The test mocks waiting; it does not simulate a physical disk failure.
- Local baseline: 1,000 synthetic successful authentication events accepted and normalized with both pending counts returning to zero. One observed run: acceptance 0.01635 seconds; processing 1.49946 seconds; total 1.51582 seconds (~659.71 events/second). This is a single-process SQLite correctness baseline with tiny synthetic events, no competing queries, no replication and no distributed services. **It is not a production throughput benchmark or capacity promise.**

## Important test coverage

Tenant-isolated searches, event detail, replay, cases and detection counts; role permissions; missing/invalid credentials; payload tenant override rejection; concurrent duplicate retries; conflicting identity atomic rollback; restart persistence; half-open time filters; timezone requirements; bounded input and replay; malformed IP quarantine; late fixed-bucket events; no counting of successful logins; activation fixtures; HTTP origin/host/content-type checks; SQL-literal search; static path traversal rejection.

Tests do not establish complete security or tenant isolation in future distributed adapters. Those adapters need their own adversarial tests.

## Not verified / blockers

- Browser rendering and full browser interactions: attempted Playwright; Chromium was absent. Browser installation downloads timed out. No screenshot or completed visual QA is claimed. JavaScript syntax and HTTP/API checks are not a replacement for browser verification.
- No Docker daemon/tool, Go compiler or Rust compiler was available. Kafka, Vector, ClickHouse, Flink, PostgreSQL, Keycloak and OPA were not deployed or benchmarked here.
- No production installation, tenant migration, external account setup, public deployment or market-wide comparative benchmark was performed.
- HA, power-loss durability, network partition recovery, distributed checkpointing, package signing, OCSF/Sigma conformance, real vendor integrations, accessibility and jurisdiction-specific compliance remain unverified.

## Manual browser check for the next environment

1. Run `python3 run.py`, connect with the generated admin token.
2. Select Send test sequence, then refresh; expect five accepted/searchable records and one detection.
3. Open Detections, create a case and verify it appears under Cases.
4. Activate the second package under Integrations; check Activity.
5. Ingest an invalid sample through the API, confirm Data quality shows the reason; confirm retry attempts are bounded.
6. Check 390px mobile and 1440px desktop layouts, keyboard focus, labels and live error messages.
7. Confirm no event message is interpreted as HTML; all dynamic display uses textContent.

## Release condition

This archive is a development foundation. Do not expose its HTTP server publicly or deploy it as a customer SIEM. Advance according to `ROADMAP.md` and the production gates in `SECURITY.md`.
