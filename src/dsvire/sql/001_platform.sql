CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS dsvire_tenant (
    tenant_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug text NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9][a-z0-9-]{1,62}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS dsvire_api_key (
    key_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES dsvire_tenant(tenant_id) ON DELETE CASCADE,
    label text NOT NULL CHECK (length(label) BETWEEN 1 AND 100),
    token_sha256 char(64) NOT NULL UNIQUE CHECK (token_sha256 ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    last_used_at timestamptz,
    revoked_at timestamptz
);

CREATE TABLE IF NOT EXISTS dsvire_document (
    document_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES dsvire_tenant(tenant_id),
    sha256 char(64) NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    byte_size bigint NOT NULL CHECK (byte_size BETWEEN 8 AND 67108864),
    object_key text NOT NULL,
    content_type text NOT NULL CHECK (content_type = 'application/pdf'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (tenant_id, sha256)
);

DO $$
BEGIN
    CREATE TYPE dsvire_job_state AS ENUM
        ('queued', 'running', 'succeeded', 'failed', 'cancelled');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END
$$;

DO $$
DECLARE
    labels text[];
BEGIN
    SELECT array_agg(e.enumlabel ORDER BY e.enumsortorder)
      INTO labels
      FROM pg_enum e
      JOIN pg_type t ON t.oid = e.enumtypid
     WHERE t.typname = 'dsvire_job_state';
    IF labels IS DISTINCT FROM ARRAY['queued', 'running', 'succeeded', 'failed', 'cancelled'] THEN
        RAISE EXCEPTION 'dsvire_job_state has unexpected labels: %', labels;
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS dsvire_job (
    job_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES dsvire_tenant(tenant_id),
    document_id uuid NOT NULL REFERENCES dsvire_document(document_id),
    idempotency_key text NOT NULL CHECK (length(idempotency_key) BETWEEN 8 AND 200),
    state dsvire_job_state NOT NULL DEFAULT 'queued',
    stage text NOT NULL DEFAULT 'queued',
    request jsonb NOT NULL,
    attempt integer NOT NULL DEFAULT 0 CHECK (attempt >= 0),
    max_attempts integer NOT NULL CHECK (max_attempts BETWEEN 1 AND 20),
    lease_owner text,
    lease_expires_at timestamptz,
    cancel_requested boolean NOT NULL DEFAULT false,
    result jsonb,
    error_code text,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    completed_at timestamptz,
    UNIQUE (tenant_id, idempotency_key),
    CHECK ((state = 'running') = (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)),
    CHECK (state NOT IN ('succeeded', 'failed', 'cancelled') OR completed_at IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS dsvire_job_lease_queue
    ON dsvire_job (created_at, job_id)
    WHERE state = 'queued';
CREATE INDEX IF NOT EXISTS dsvire_job_expired_lease
    ON dsvire_job (lease_expires_at)
    WHERE state = 'running';

CREATE TABLE IF NOT EXISTS dsvire_job_event (
    event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_id uuid NOT NULL REFERENCES dsvire_job(job_id) ON DELETE CASCADE,
    tenant_id uuid NOT NULL REFERENCES dsvire_tenant(tenant_id),
    kind text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS dsvire_job_event_replay ON dsvire_job_event (job_id, event_id);

CREATE TABLE IF NOT EXISTS dsvire_outbox (
    outbox_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    topic text NOT NULL,
    aggregate_id uuid NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    published_at timestamptz,
    lock_owner text,
    lock_expires_at timestamptz,
    attempts integer NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS dsvire_outbox_pending ON dsvire_outbox (outbox_id)
    WHERE published_at IS NULL;

CREATE OR REPLACE FUNCTION dsvire_touch_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = clock_timestamp();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS dsvire_job_touch ON dsvire_job;
CREATE TRIGGER dsvire_job_touch BEFORE UPDATE ON dsvire_job
    FOR EACH ROW EXECUTE FUNCTION dsvire_touch_updated_at();
