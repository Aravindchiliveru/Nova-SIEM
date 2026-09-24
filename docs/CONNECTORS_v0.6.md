> Latest Sigma behavior and migration: see [0.7.2 upgrade](UPGRADE_v0.7.2.md). New exists imports check presence, including null; legacy compiled predicates retain their original semantics.

# Direct collection and interoperability

## Linux journal

Activate Process JSON, then acquire native journal records:

```bash
python3 -m nova.native journald --spool data/journal.db --source linux-journal
python3 -m nova.collector send --spool data/journal.db --source linux-journal --adapter process-json --tokens-json data/local-tokens.json
```

Each acquisition invocation reads up to 1,000 records, resuming after its committed journal cursor. Repeat acquisition and sending under your process supervisor/timer. The native and sender commands share an exclusive spool lock: schedule sequentially, not concurrently. Run the acquisition account with journal read privileges. A missing cursor starts at the beginning of the available journal, not at an invented timestamp. Cursor and queued record commit together with FULL WAL; spool capacity, malformed or oversized records stop advancement. Source journal vacuum can remove unread data; this collector cannot recover removed journal entries and does not prove gap-free journal rotation. Inspect journal continuity separately.

These are process-originated log messages with `action=log`, not process-creation telemetry. The native record is retained as `original`; real journal timestamps and cursors are used. Binary messages or records without usable process identity stop acquisition for inspection. They are not silently converted into authentication or process-start events. The existing OpenSSH export adapter remains separate. Native Windows Event Log, eBPF, firewall/syslog receiver and endpoint fleet management are not implemented.

## AWS CloudTrail management events

Install the optional SDK in a development environment using `requirements-aws.txt`; resolve/lock/scan dependencies for deployment. Use the standard AWS credential chain with least-privilege `cloudtrail:LookupEvents`; do not put credentials in rules or source payloads.

```bash
python3 -m nova.native cloudtrail --spool data/aws.db --source aws-management --region us-east-1 --start 2026-09-20T00:00:00Z --end 2026-09-21T00:00:00Z
python3 -m nova.collector send --spool data/aws.db --source aws-management --adapter cloud-json --tokens-json data/local-tokens.json
```

Activate Cloud JSON first. Use a stable, distinct source identifier for each AWS account/region. This collector pages the native LookupEvents API, retaining continuation token and page records atomically. It uses a fixed region/time interval per spool and a half-open time filter. Repeating a completed interval does not query again; use a new spool for another interval or a deliberate late-arrival rescan, retaining the same source for stable downstream deduplication. This is a bounded interval collector, not a complete continuous cloud ingestion service. It does not collect CloudTrail data events, S3 trail delivery, all accounts/regions or events older than the API history. Late-arriving records require deliberate rescan; do not treat a completed query as an eternal completeness guarantee. The SDK was unavailable in this runtime; provider calls were tested through a contract double only.

CloudTrail LookupEvents supports recent regional history and limits request rate; the implementation uses pages of 50 and a 0.6-second inter-page delay. Source: [AWS LookupEvents](https://docs.aws.amazon.com/awscloudtrail/latest/APIReference/API_LookupEvents.html).

## OCSF

Activate **OCSF authentication logon** and ingest `ocsf-auth-json` using the regular batch API or the spool collector. An example is `examples/ocsf-auth.ndjson`. `GET /api/event/ocsf?id=EVENT_ID` exports a tenant-authorized normalized authentication/login event.

Implemented scope: OCSF **1.4.0, class 3002, activity 1, type 300201** projection, integer epoch milliseconds, user identity, source IP, status and product metadata checks. Other classes/activities/versions and unknown authentication outcomes fail explicitly. Source JSON remains in the raw event. Export sets producer metadata to Nova and severity to unknown because normalized severity is not retained. Export is a lossy projection, not round-trip preservation of every source field.

This is not a complete OCSF schema validator, all-class mapper or a conformance certification. Pinned full upstream schema retrieval was unavailable; mapping was checked against accessible official authentication/base-event definitions and local fixtures. Independent pinned-schema validation remains open. References: [OCSF authentication](https://github.com/ocsf/ocsf-schema/blob/main/events/iam/authentication.json), [base event](https://github.com/ocsf/ocsf-schema/blob/main/events/base_event.json).

## Sigma import

```bash
python3 -m pip install -r requirements-interop.txt
python3 -m nova.sigma examples/sigma/shell.yml --binding examples/sigma/binding.json --output rules/imported-shell.json
```

Import does not overwrite an existing file. Sign the generated package if required by policy, restart relevant app/detector roles, then simulate and enable its exact revision for the intended tenant in Detection rules. The sample binding intentionally requires source `linux-agent`, category `process`, action `start`; journald `action=log` will not satisfy it.

Supported subset (updated in 0.7): YAML map/map-list selections; case-insensitive strings with Sigma `*`, `?` and backslash escapes; equality, contains, startswith, endswith and all; integer values converted to strings; scalar null and boolean exists; and/or/not, parentheses, 1/all of selection patterns and condition lists (OR). `them` excludes underscore-prefixed selections; explicit wildcard selection patterns can include them. Empty string is distinct from null; missing/null fields satisfy null, while exists requires a present non-null value. Native normalization often fills optional fields with empty strings, so raw-source absence is not always observable through normalized fields.

An operator binding must exactly match the rule logsource and explicitly bind source identifiers, category and fields. Unknown fields, regex, null within lists, floats, arbitrary modifier stacks, encodings, aggregations/correlation, filters, scope and alternate taxonomy are rejected. Expression depth/node/value limits remain; wildcard matching uses a bounded greedy algorithm rather than regex. YAML duplicate keys, unsafe tags, aliases and anchors fail. The nine native fields still limit which third-party rules can be represented.

Imported rules start disabled and retain existing bounded native alert grouping/evidence semantics: events with the same grouping within a one-second bucket can share an alert. This is not full Sigma compatibility or a validated SigmaHQ corpus. Reference: [Sigma specification 2.1.0](https://sigmahq.io/sigma-specification/specification/sigma-rules-specification.html).
