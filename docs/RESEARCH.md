# Research and component decisions

Research snapshot: 17 September 2026. Sources are vendor/project primary documentation. Conclusions below are engineering decisions, not independent performance measurements. Documentation can establish capabilities and limitations; it cannot establish which product is universally fastest or cheapest. Version and distribution licensing review remain release gates.

## Evaluation method

Prioritize correctness and tenant isolation, then operating cost at the target workload, source onboarding effort, recovery behavior, query quality and commercial maintainability. Newness alone is not an advantage. No inherited technology requirement applies. An existing technology may be selected again only for a stated independent reason.

Compare candidates on identical data, retention, replicas, rules, hardware, search concurrency and failure conditions. Include full-text, structured filters, high-cardinality aggregations, rare-event hunts and historical replay. Measure query correctness as well as speed. No weighted numerical score is presented without data.

## Data collection decision

Select Vector as the initial general-purpose collector and transformation candidate. Its declarative transforms and acknowledgement design fit a packaged integration model. Validate each receiver/sink pair. Its acknowledgement documentation explicitly distinguishes sources that can acknowledge from transports that cannot. Fan-out also combines delivery status across sinks, so independent durable consumers are preferable to coupling every destination in one collector fan-out. [Vector acknowledgement design](https://vector.dev/docs/architecture/end-to-end-acknowledgements/)

Alternative: OpenTelemetry Collector for application telemetry and standard OTLP. It remains the instrumentation standard within the product. Receiver maturity and pipeline durability must be tested rather than assumed; persistent queues remain bounded by storage and retry behavior. Do not force a single collector to cover every endpoint, cloud and appliance. [OpenTelemetry resilience](https://opentelemetry.io/docs/collector/resiliency/)

Endpoint security sources such as native event subscriptions, EDR and osquery need dedicated package contracts; a generic syslog listener cannot replace their telemetry. Native protocol implementations are not yet included in the reference build.

## Transport decision

Select Apache Kafka in KRaft mode as the baseline production event log, without connecting to any old cluster. Its partitioned durable log, independent consumer positions, replay and transaction model fit high-volume security streams. Retention, ISR/ack policy and producer behavior are part of the durability contract. Kafka transactions do not automatically make an external alert or storage action exactly once. [Kafka design](https://kafka.apache.org/43/design/design/)

NATS JetStream is a legitimate alternative for simpler messaging and pull consumers. It remains a benchmark candidate for compact deployments; retaining two event backbones by default would increase complexity. [NATS pull consumers](https://docs.nats.io/learn/jetstream/pull-consumers)

Redpanda remains a candidate for Kafka-compatible deployments, subject to an exact edition/feature/distribution review and equal-workload testing. Do not assume Community and Enterprise have identical capabilities or product-distribution rights. This research did not settle the legal compatibility of a particular commercial bundle. [Redpanda licensing entry point](https://docs.redpanda.com/streaming/current/get-started/licensing/)

## Analytical store decision

Select ClickHouse as the primary structured event analytics candidate. This is a change from a search-index-first design. Its documented observability use case fits event filtering and aggregation; any storage/cost advantage remains a benchmark hypothesis. [ClickHouse observability](https://clickhouse.com/docs/guides/use-cases/observability)

Do not infer uniqueness from ReplacingMergeTree: background merging is eventual, and exact results may require query-time deduplication. Insert retry deduplication also has finite windows. The sink design must use stable identities and batch tokens, plus query semantics that remain correct when retries outlive a window. [ReplacingMergeTree](https://clickhouse.com/docs/reference/engines/table-engines/mergetree-family/replacingmergetree), [retry deduplication](https://clickhouse.com/docs/concepts/features/operations/insert/deduplicating-inserts-on-retries)

OpenSearch remains a full-text search comparator or optional secondary projection if the hunting benchmark justifies it. It should not be added automatically alongside ClickHouse. Security Analytics is an existing capability, but embedding another platform's UI is not the intended product architecture. [OpenSearch Security Analytics](https://opensearch.org/platform/security-analytics/)

Object storage holds original evidence and normalized Parquet data for longer retention. An S3-compatible interface alone does not prove immutability, lock semantics, site recovery or licensing suitability. Choose the actual storage implementation per certified deployment profile after restore and retention tests.

## Detection and workflow decisions

OCSF is the target normalized security schema, with separately versioned transport metadata. The current reference has a small authentication contract and makes no OCSF conformance claim. [OCSF](https://ocsf.io/)

Sigma is the rule interchange format. Compile a documented subset into an internal intermediate representation with typed field mappings. Reject unsupported semantics and test every translated rule. Do not label a custom threshold rule a Sigma engine. [Sigma documentation](https://sigmahq.io/docs/)

Flink is selected for the stateful production correlation engine: event-time windows, checkpointed state and keyed processing. Lateness, TTL, hot-key behavior, rule upgrades, output idempotency and failure recovery still require application design. [Flink stateful processing](https://nightlies.apache.org/flink/flink-docs-stable/docs/concepts/stateful-stream-processing/)

Temporal is the candidate for durable case/response/maintenance workflows when those workflows become multi-step. It is not the event-per-second processing path. External effects still need idempotency, expiry, authorization and compensation. [Temporal workflow execution](https://docs.temporal.io/workflow-execution)

## Identity and policy decisions

Use standard OIDC identity, with Keycloak as the self-hosted identity candidate and customer identity providers supported. Keep authentication, authorization and tenant binding distinct. OPA is a policy engine candidate for resource/action authorization; deny by default and test database/export/cache/background-job enforcement. [Keycloak guides](https://www.keycloak.org/guides), [OPA](https://www.openpolicyagent.org/docs)

PostgreSQL is the metadata/case store; it is not the raw event firehose. Go is the intended service language for custom high-throughput APIs/workers where needed; Python is appropriate for the executable reference, detection tooling and research. React/TypeScript is the intended full console. The current browser console intentionally uses dependency-free JavaScript so the foundation runs without a package manager.

## Market capability baseline

The following is a capability floor, not a vendor ranking or an assertion about feature equivalence.

| Reviewed primary source | Observed product emphasis | Requirement derived for Nova |
|---|---|---|
| [Microsoft Sentinel](https://learn.microsoft.com/en-us/azure/sentinel/overview) | Packaged content, normalization, analytics, hunting, investigation and playbooks | Integrations must ship operational and detection content; a connector count alone is insufficient |
| [Google Security Operations](https://docs.cloud.google.com/chronicle/docs/overview) | Security operations lifecycle spanning collection, detection, investigation, response and administration | Build one coherent lifecycle with clear evidence and access controls |
| [Elastic Security](https://www.elastic.co/docs/solutions/security) | Security solution spanning investigation and detection capabilities | Hunting and evidence exploration must be first-class product workflows |
| [Splunk Enterprise Security](https://www.splunk.com/en_us/products/enterprise-security.html) | Unified detection/investigation/response, detection lifecycle, behavioral analytics and automation | Rule quality, analyst workflow, entity context and automation are product workstreams |

Vendor speed, ROI and efficacy claims were not reused as benchmark evidence. No proprietary rules, source code or customer data were copied.

## What is confirmed vs unresolved

Confirmed from documentation: the selected projects provide relevant primitives; protocol acknowledgement and deduplication limitations are real; mature SIEM products cover far more than indexing and dashboards.

Chosen by engineering judgment: Vector/Kafka/ClickHouse with Flink and a separate control plane is the baseline to implement and compare. Avoid a graph database, vector database, Redis buffer and multiple analytical stores until a workload proves the need.

Unresolved until measured: exact throughput, storage compression, language advantages for a particular parser, supported hardware minimums, multi-region RPO/RTO, fuzzy full-text quality, per-tenant cost, and superiority over another SIEM. These are explicit release gates, not promised outcomes.
