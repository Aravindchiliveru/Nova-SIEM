-- Development schema. No destructive migration or automatic retention.
CREATE TABLE IF NOT EXISTS nova_receipts (
 tenant TEXT NOT NULL, event_id TEXT NOT NULL, digest TEXT NOT NULL,
 source TEXT NOT NULL, integration TEXT NOT NULL, received DOUBLE PRECISION NOT NULL,
 normalized_at DOUBLE PRECISION, indexed_at DOUBLE PRECISION, detected_at DOUBLE PRECISION,
 archived_at DOUBLE PRECISION, PRIMARY KEY(tenant,event_id));
CREATE TABLE IF NOT EXISTS nova_outbox (
 id BIGSERIAL PRIMARY KEY, tenant TEXT NOT NULL, event_id TEXT NOT NULL,
 topic TEXT NOT NULL, payload TEXT NOT NULL, created DOUBLE PRECISION NOT NULL);
CREATE INDEX IF NOT EXISTS nova_outbox_tenant ON nova_outbox(tenant,id);
CREATE TABLE IF NOT EXISTS nova_activations (
 tenant TEXT NOT NULL, package TEXT NOT NULL, version TEXT NOT NULL, digest TEXT NOT NULL,
 PRIMARY KEY(tenant,package));
CREATE TABLE IF NOT EXISTS nova_quarantine (
 tenant TEXT NOT NULL,event_id TEXT NOT NULL,reason TEXT NOT NULL,raw TEXT NOT NULL,
 attempts INTEGER NOT NULL DEFAULT 0,resolved BOOLEAN NOT NULL DEFAULT FALSE,
 PRIMARY KEY(tenant,event_id));
CREATE TABLE IF NOT EXISTS nova_detection_seen (
 tenant TEXT NOT NULL,event_id TEXT NOT NULL,PRIMARY KEY(tenant,event_id));
CREATE TABLE IF NOT EXISTS nova_detection_events (
 tenant TEXT NOT NULL,event_id TEXT NOT NULL,group_key TEXT NOT NULL,
 PRIMARY KEY(tenant,event_id));
CREATE INDEX IF NOT EXISTS nova_detection_group ON nova_detection_events(tenant,group_key,event_id);
CREATE TABLE IF NOT EXISTS nova_alerts (
 id TEXT PRIMARY KEY,tenant TEXT NOT NULL,rule TEXT NOT NULL,title TEXT NOT NULL,
 severity TEXT NOT NULL,created DOUBLE PRECISION NOT NULL,evidence TEXT NOT NULL,event_count BIGINT NOT NULL);
CREATE INDEX IF NOT EXISTS nova_alerts_tenant ON nova_alerts(tenant,created);
CREATE TABLE IF NOT EXISTS nova_cases (
 id BIGSERIAL PRIMARY KEY,tenant TEXT NOT NULL,alert_id TEXT NOT NULL,
 title TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'open',created DOUBLE PRECISION NOT NULL,
 UNIQUE(tenant,alert_id));
CREATE TABLE IF NOT EXISTS nova_audit (
 id BIGSERIAL PRIMARY KEY,tenant TEXT NOT NULL,actor TEXT NOT NULL,action TEXT NOT NULL,
 detail TEXT NOT NULL,created DOUBLE PRECISION NOT NULL);
CREATE INDEX IF NOT EXISTS nova_audit_tenant ON nova_audit(tenant,id);
CREATE TABLE IF NOT EXISTS nova_workers (
 worker_id TEXT PRIMARY KEY,role TEXT NOT NULL,updated DOUBLE PRECISION NOT NULL,
 failed BOOLEAN NOT NULL,processed BIGINT NOT NULL);

CREATE TABLE IF NOT EXISTS rule_hits (
 tenant TEXT NOT NULL, revision TEXT NOT NULL, event_id TEXT NOT NULL,
 group_key TEXT NOT NULL, distinct_value TEXT NOT NULL,
 PRIMARY KEY(tenant,revision,event_id));
CREATE INDEX IF NOT EXISTS rule_hits_group ON rule_hits(tenant,revision,group_key,distinct_value,event_id);
CREATE TABLE IF NOT EXISTS nova_case_notes (
 id BIGSERIAL PRIMARY KEY,tenant TEXT NOT NULL,case_id BIGINT NOT NULL,
 actor TEXT NOT NULL,note TEXT NOT NULL,created DOUBLE PRECISION NOT NULL);
CREATE INDEX IF NOT EXISTS nova_case_notes_case ON nova_case_notes(tenant,case_id,id);


CREATE TABLE IF NOT EXISTS nova_audit_chain (
 tenant TEXT NOT NULL,seq BIGINT NOT NULL,audit_id BIGINT NOT NULL,
 payload TEXT NOT NULL,previous TEXT NOT NULL,digest TEXT NOT NULL,
 PRIMARY KEY(tenant,seq),UNIQUE(tenant,audit_id));
CREATE TABLE IF NOT EXISTS nova_workflows (
 id TEXT PRIMARY KEY,tenant TEXT NOT NULL,request_key TEXT NOT NULL,
 request_digest TEXT NOT NULL,requester TEXT NOT NULL,approver TEXT,
 alert_id TEXT NOT NULL,definition TEXT NOT NULL,state TEXT NOT NULL,
 step INTEGER NOT NULL DEFAULT 0,revision INTEGER NOT NULL DEFAULT 0,
 attempts INTEGER NOT NULL DEFAULT 0,next_try DOUBLE PRECISION NOT NULL DEFAULT 0,
 result TEXT NOT NULL,last_error TEXT,created DOUBLE PRECISION NOT NULL,
 UNIQUE(tenant,request_key));
CREATE INDEX IF NOT EXISTS nova_workflows_queue ON nova_workflows(state,next_try,created);
CREATE INDEX IF NOT EXISTS nova_workflows_tenant ON nova_workflows(tenant,created);


CREATE TABLE IF NOT EXISTS nova_correlation_events (
 tenant TEXT NOT NULL,revision TEXT NOT NULL,event_id TEXT NOT NULL,
 group_key TEXT NOT NULL,event_time DOUBLE PRECISION NOT NULL,
 first_match INTEGER NOT NULL,last_match INTEGER NOT NULL,distinct_value TEXT NOT NULL,
 PRIMARY KEY(tenant,revision,event_id));
CREATE INDEX IF NOT EXISTS nova_correlation_group ON nova_correlation_events(tenant,revision,group_key,event_time,event_id);

CREATE TABLE IF NOT EXISTS nova_rule_settings (
 tenant TEXT NOT NULL,rule_id TEXT NOT NULL,revision TEXT NOT NULL,enabled INTEGER NOT NULL,
 PRIMARY KEY(tenant,rule_id));


CREATE TABLE IF NOT EXISTS nova_external_jobs (
 id TEXT PRIMARY KEY,tenant TEXT NOT NULL,request_key TEXT NOT NULL,digest TEXT NOT NULL,
 requester TEXT NOT NULL,approver TEXT,connector TEXT NOT NULL,config_digest TEXT NOT NULL,
 payload TEXT NOT NULL,state TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 0,
 attempts INTEGER NOT NULL DEFAULT 0,lease TEXT,lease_until DOUBLE PRECISION NOT NULL DEFAULT 0,
 next_try DOUBLE PRECISION NOT NULL DEFAULT 0,last_error TEXT,created DOUBLE PRECISION NOT NULL,
 UNIQUE(tenant,request_key));
CREATE INDEX IF NOT EXISTS nova_external_ready ON nova_external_jobs(state,next_try,lease_until);

CREATE INDEX IF NOT EXISTS nova_external_tenant ON nova_external_jobs(tenant,created);

-- Existing filesystem receipts never imply remote Object Lock verification.
ALTER TABLE nova_receipts ADD COLUMN IF NOT EXISTS locked_at DOUBLE PRECISION;
CREATE TABLE IF NOT EXISTS nova_archive_objects (
 tenant TEXT NOT NULL,event_id TEXT NOT NULL,object_key TEXT NOT NULL,version_id TEXT NOT NULL,
 receipt TEXT NOT NULL,PRIMARY KEY(tenant,event_id,object_key,version_id));
