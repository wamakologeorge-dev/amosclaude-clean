CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS logs (
  event_id UUID PRIMARY KEY,
  timestamp TIMESTAMPTZ NOT NULL,
  ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  level TEXT NOT NULL CHECK (level IN ('TRACE','DEBUG','INFO','WARNING','ERROR','CRITICAL')),
  message TEXT NOT NULL,
  service TEXT NOT NULL,
  environment TEXT NOT NULL,
  tenant_id TEXT NOT NULL,
  user_id TEXT,
  request_id TEXT,
  trace_id TEXT,
  tags JSONB NOT NULL DEFAULT '{}'::jsonb,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  schema_version TEXT NOT NULL DEFAULT '1.0',
  event_fingerprint TEXT NOT NULL,
  redis_stream_id TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS logs_tenant_time_idx ON logs (tenant_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS logs_tenant_level_time_idx ON logs (tenant_id, level, timestamp DESC);
CREATE INDEX IF NOT EXISTS logs_tenant_service_time_idx ON logs (tenant_id, service, timestamp DESC);
CREATE INDEX IF NOT EXISTS logs_trace_idx ON logs (tenant_id, trace_id) WHERE trace_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS logs_request_idx ON logs (tenant_id, request_id) WHERE request_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS logs_message_search_idx ON logs USING gin (to_tsvector('simple', message));
CREATE INDEX IF NOT EXISTS logs_tags_idx ON logs USING gin (tags);

CREATE TABLE IF NOT EXISTS incidents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id TEXT NOT NULL,
  fingerprint TEXT NOT NULL,
  severity TEXT NOT NULL,
  service TEXT NOT NULL,
  title TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',
  first_seen_at TIMESTAMPTZ NOT NULL,
  last_seen_at TIMESTAMPTZ NOT NULL,
  occurrence_count BIGINT NOT NULL DEFAULT 1,
  sample_event JSONB NOT NULL,
  fixee_proposal JSONB,
  UNIQUE (tenant_id, fingerprint)
);
CREATE INDEX IF NOT EXISTS incidents_tenant_status_idx ON incidents (tenant_id, status, last_seen_at DESC);
