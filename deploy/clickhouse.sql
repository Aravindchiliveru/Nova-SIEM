CREATE DATABASE IF NOT EXISTS nova;
CREATE TABLE IF NOT EXISTS nova.events (
 tenant String,event_id String,source String,event_time Float64,received Float64,
 normalized_at Float64,actor String,ip String,outcome LowCardinality(String),
 message String,parser LowCardinality(String),version String,raw String
) ENGINE = ReplacingMergeTree
PARTITION BY intDiv(toInt64(event_time), 2592000)
ORDER BY (tenant,event_time,event_id);
-- Every application query uses FINAL. Immutable event_time and stable IDs keep
-- duplicate retries in one partition/key. No automatic TTL or evidence deletion.

-- Additive v0.5 migration. Run init before starting v0.5 workers.
ALTER TABLE nova.events ADD COLUMN IF NOT EXISTS category String DEFAULT 'authentication';
ALTER TABLE nova.events ADD COLUMN IF NOT EXISTS action String DEFAULT 'login';
ALTER TABLE nova.events ADD COLUMN IF NOT EXISTS host String DEFAULT '';
ALTER TABLE nova.events ADD COLUMN IF NOT EXISTS target String DEFAULT '';
