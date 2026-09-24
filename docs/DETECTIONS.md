> v0.4: Current behavior and remaining gates are documented in ENTERPRISE_CONTROLS.md, CORRELATION.md, VALIDATION.md and ENTERPRISE_GATES.md. Newer guides take precedence over this historical description.

# Detection and investigation guide

## Rule format

Operator-owned JSON files in `rules/` define: id, title, severity, enabled, window_seconds, threshold, group_by, match, and optional distinct/description/tags. Values under match are exact string alternatives; fields are ANDed. No executable code, regular expressions or arbitrary SQL are accepted.

Allowed fields: source, actor, ip, outcome, message. Grouping and distinct fields exclude message. Windows range 1–86,400 seconds; threshold 1–100,000; at most 100 rule files. Shipped rules use 300-second windows.

```json
{"id":"example.failures.v1","title":"Repeated failures","severity":"medium","enabled":true,"window_seconds":300,"threshold":5,"group_by":["source","actor","ip"],"match":{"outcome":["failure"]}}
```

A window is `floor(event_time / window_seconds)`. Its interval is inclusive at the start and exclusive at the end. Late events enter their original bucket. Events on opposite sides of a boundary do not combine. There is no lateness cutoff or rule-state TTL in this development release. Duplicate event IDs do not count twice within a rule revision. Distinct rules count unique actors/IPs, rather than the total number of failures.

Alerts are one per tenant/rule revision/group/window. Evidence is limited to 100 deterministic event IDs. PostgreSQL alerts also retain full event_count; local alerts expose only the bounded evidence list. Large groups should be investigated through Event explorer, not assumed to contain only 100 events.

The privileged-login rule matches exactly `root` or `Administrator`; this is a demonstration rule and is not a complete inventory of privileged identities. CloudTrail ARNs are retained as identities when userName is absent and therefore do not automatically match that rule. Tune rule packages to your source identity conventions.

## Console

Detection rules lists the active configuration and signature status. Simulate opens an editable JSON sample of normalized events. Simulations are limited to 500 sample events, write no data, and evaluate the sample alone; they are not historical searches. Only administrators can simulate. All tenant viewers can inspect the installed global rule catalog.

Detections → Open case creates an idempotent investigation case. Cases → Investigate supports open, investigating, resolved and closed, plus 8 KiB analyst notes. Analysts/admins can edit; viewers can read. Notes and changes are tenant-scoped and recorded in the application audit log. This log is not externally anchored or immutable.

Event explorer filters message/actor text, exact IP/outcome, and a half-open time range. Time inputs are interpreted in the browser's local timezone and sent as UTC ISO timestamps. Inspect shows raw/normalized state; distributed raw availability depends on the search/quarantine projection. The filesystem archive does not yet have a query API.

## APIs

GET /api/rules; POST /api/rules/simulate with {rule,events}; GET /api/case?id=ID; POST /api/cases/update with {id,status,note}. The existing /api/events, /api/search, /api/event, /api/alerts and /api/cases APIs remain. Server-side credentials determine the tenant; request bodies cannot select it.
