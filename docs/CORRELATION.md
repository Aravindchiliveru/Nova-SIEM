# Sliding and ordered-event correlation

Two additional native JSON rules are installed and disabled by default: `auth.sliding-failures.v1` and `auth.failure-then-success.v1`. Enable them per tenant through the console or rule configuration API.

A native rule can now specify `window_mode` as fixed (default), sliding or sequence. Sequence additionally requires an `after` exact-match selection. Existing field, grouping, threshold and distinct-count bounds remain. These are native Nova rules, not Sigma parsing or conformance.

- Fixed: original half-open UTC buckets, one alert per group/bucket/revision.
- Sliding: matching events in `(anchor_time - window_seconds, anchor_time]`; one alert per qualifying anchor event.
- Sequence: at least the threshold number of first-stage matches in `(anchor_time - window_seconds, anchor_time)` followed by an `after` event at anchor_time. Equal timestamps do not prove order and do not qualify as predecessors.

Source timestamps determine ordering. Event IDs deduplicate stored state within each rule revision. Late predecessor arrivals re-evaluate affected stored anchors, so a success that arrived before its preceding failures can still produce a sequence alert. A new event outside an anchor's window does not trigger redundant recalculation.

Alert evidence is capped at 100 IDs and includes the anchor. Local alerts expose bounded references; PostgreSQL alerts additionally store total event_count. There is no automatic merging of overlapping sliding alerts, so high-volume failures can produce many alerts. Thresholds and downstream grouping need operational tuning.

## Explicit resource boundaries

State is persisted per tenant/rule revision/group. A group is capped at **10,000 retained relevant events**. Exceeding that bound raises an explicit error and rolls back the detector transaction; input progress is retained rather than silently discarding state. There is no event-time state TTL, allowed-lateness policy or automatic eviction yet. A hot overflowing group can therefore block its processing batch until operators resolve capacity or disable/reconfigure the rule. This is a development correctness boundary, not a production streaming-state solution.

History re-evaluation, arrival-time/event-time differences, alert amplification and group cardinality all affect throughput. See BENCHMARKS.md for the measured profile. Production-scale state and retention should move to the planned streaming runtime with tested checkpoint/rebalance behavior. Enabling these rules does not make that work complete.
