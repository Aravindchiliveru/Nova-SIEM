# Start here — v0.7

Run `python3 run.py`, open http://127.0.0.1:8787 and use the generated admin token from `data/local-tokens.json`.

The local console supports ingestion, typed search, detection governance, cases, internal workflows, external action requests and audit verification. External connectors require operator configuration and a different operator's approval before execution.

Read `docs/CONNECTORS_v0.6.md` for direct acquisition and OCSF/Sigma import commands; `docs/EXTERNAL_RESPONSE.md` for connector setup; `docs/IMMUTABLE_RETENTION.md` for Object Lock; `deploy/ha/README.md` for qualification prerequisites.

This is a development release. Read README.md and docs/ENTERPRISE_GATES.md for the supported boundaries and unfinished work. Remote AWS enforcement, production failover and full OCSF/Sigma compatibility have not been established.

For this upgrade, read `docs/UPGRADE_v0.7.md` and `docs/DEFENDER_RESPONSE.md` before configuring vendor actions.

Latest detection upgrade: `docs/UPGRADE_v0.7.2.md`. Read its rule-recompilation notes before adopting new Sigma modifiers.

Structured-event upgrade: `docs/STRUCTURED_EVENTS_v0.8.md`. Activate `nested-process-json` to try nested mappings, or the new OCSF process/file projection packages.
