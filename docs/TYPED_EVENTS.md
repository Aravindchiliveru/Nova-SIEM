# Native typed events — v0.5

Nova now accepts authentication, process, network, DNS, file and cloud events. This is Nova's own flat schema, not validated OCSF or ECS conformance. The OCSF project defines a substantially richer category/class/object framework; genuine compatibility requires versioned mappings and schema validation, not just similar field names. Reference: https://github.com/ocsf/ocsf-schema

## Ingest and explore

Run `python3 run.py`. Connect with the admin token and activate **Process JSON** in Integrations. Then, from the project directory:

```bash
python3 -m nova.collector import --spool data/process-spool.db --source endpoint-demo --adapter process-json --file examples/process.ndjson
python3 -m nova.collector send --spool data/process-spool.db --source endpoint-demo --adapter process-json --tokens-json data/local-tokens.json
```

Open Event explorer and filter Category by `process`. Inspect the event to see its normalized fields and retained raw JSON. The same commands work with `network-json`, `dns-json`, `file-json` or `cloud-json` and the corresponding example file. Use a separate spool for each source/adapter pair. These adapters read supplied NDJSON; they do not subscribe to an endpoint agent, cloud API, DNS server or firewall. Collector acknowledgement confirms durable acceptance, not successful normalization; watch Data quality and processing metrics.

## Input contract

Each of the five new packages uses `nova.mapping.v2`. Required keys:

| Input key | Normalized meaning |
|---|---|
| `timestamp` | ISO 8601 time with explicit timezone; numeric event time stored |
| `action` | Exact action string, 1–128 characters; case is preserved |
| `target` | Affected resource/path/domain/destination string, 1–8192 characters |
| `message` | Human-readable text, at most 8192 characters |

Optional keys are `actor` (at most 256 characters), `host` (at most 256), `src_ip` (IP literal), and `outcome` (`success`, `failure`, `unknown`). Absent actor/host/IP are empty strings; absent outcome is `unknown`. Empty string means not supplied, never a fabricated user or address. Explicit malformed/null values are rejected into quarantine. Resource strings are not parsed into process trees, destination-port objects, DNS answers or cloud resource graphs.

Category comes from the activated package, not the payload. Source, tenant and event identity remain controlled by the existing ingestion/authentication envelope. Original parsed JSON is retained, including vendor fields that have no normalized projection. Original wire bytes are not an immutable evidence archive.

All mapping targets are literal top-level JSON keys. Required mapped fields must exist; `optional` can contain only mapped actor/IP/host/outcome keys. Packages are loaded and fixtures checked at startup; existing optional signature policy also applies to v2 packages. This is not live hot-loading or a connector marketplace.

## Detection and search

Rules can match and group by `category`, `action`, `host` and `target`, alongside existing fields. Matching remains bounded, case-sensitive, exact string lists. Fixed/sliding/sequence semantics remain unchanged. Simulation supports the new fields; omitted fields in historical simulation samples default to authentication/login with empty host/target.

All six bundled authentication rules now explicitly select authentication events, including the success side of the ordered rule. Three additional rules are installed **disabled**, ready for tenant review, simulation and activation:

| Rule | Exact condition | Threshold/window |
|---|---|---|
| `cloud.logging-disabled.v1` | Cloud action `StopLogging` or `DeleteTrail` | 1 per source/target per 300-second bucket |
| `file.credential-write.v1` | File action `write`/`delete`, target `/etc/passwd` or `/etc/shadow` | 1 per source/host/target per bucket |
| `network.fanout.v1` | Network action `connect` | 100 distinct targets per source/host/IP per bucket |

These are starter signals, not confirmed compromises or comprehensive attack coverage. Review legitimate administrative activity and normalization conventions before enabling. In particular, source/host/IP grouping quality depends on the data supplied; absent host/IP cannot identify an endpoint reliably.

`GET /api/search` now also accepts exact category/action/host/target filters. Local SQL and ClickHouse bind values independently of query text and retain tenant predicates. The console exposes these filters and shows category/action/target columns. Category has a local tenant/time index; other added predicates have no new dedicated index. Broad high-volume searches still require production query/storage engineering.

## Upgrade from v0.4

1. Stop ingestion and workers and take a verified snapshot using the existing operations tooling. Keep the prior release separately.
2. Start v0.5 locally. It adds category/action/host/target columns under a write transaction, defaults historical rows to authentication/login, and creates a category index. Restart is idempotent; events, cases and audit rows are preserved. Allow disk space/time for index creation.
3. Review tenant rule settings. Authentication rule revisions changed because category selectors changed. Previous overrides become stale and package defaults apply until the administrator configures the new revision. Existing processed events are not automatically re-detected; old correlation state is retained.
4. Distributed lab: stop all app producers/consumers, run the updated `init` role to apply additive ClickHouse columns, and upgrade all app roles before resuming. The v1 normalized envelope gains additive fields; v0.5 consumers default old messages to authentication. Old consumers are not compatible with typed events. Live service migration has not been tested here.
5. Rollback requires restoring a pre-upgrade snapshot consistently with the previous code and queued data. Do not point v0.4 at the extended SQLite table: its positional insertion is incompatible. No automated cross-store rollback is provided.

TLS/public deployment, native collection, OCSF/Sigma, storage tenant policies, immutable retention, production HA/DR and enterprise browser identity remain open requirements.
