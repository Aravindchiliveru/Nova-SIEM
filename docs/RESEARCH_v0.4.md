# Enterprise implementation decisions

Primary documentation informed boundaries; no superiority claim was inferred from marketing.

- Sigma specification 2.1.0 describes logsource, match modifiers, conditions and correlation beyond this implementation. Nova's native rules are explicitly not a Sigma interpreter: https://sigmahq.io/sigma-specification/specification/sigma-rules-specification.html
- Temporal documents durable workflow execution across failures. This release implements only transactional internal database actions, and does not claim Temporal or external-activity semantics: https://docs.temporal.io/workflow-execution
- PostgreSQL documents row-level security and its exceptions. Application tenant filters in this project are not presented as completed database-level isolation: https://www.postgresql.org/docs/current/ddl-rowsecurity.html

Chosen engineering boundaries: action effects and workflow progress commit together; stale approvals fail; late event-time predecessors re-evaluate affected anchors; capacity overflow fails explicitly; audit integrity requires external checkpoints to detect anchored truncation/rewrite; evidence checksums do not self-authenticate.
