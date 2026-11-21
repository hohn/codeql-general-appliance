BEGIN;

CREATE SCHEMA IF NOT EXISTS cgactl;

CREATE TABLE IF NOT EXISTS cgactl.jobs (
    job_id text PRIMARY KEY,
    cve text NOT NULL,
    variant text NOT NULL CHECK (variant IN
        ('vulnerable', 'patched', 'most-recent')),
    mode text NOT NULL CHECK (mode IN ('trace', 'none')),
    source_digest text NOT NULL,
    toolchain_digest text NOT NULL,
    priority integer NOT NULL DEFAULT 100,
    spec jsonb NOT NULL DEFAULT '{}'::jsonb,
    status text NOT NULL DEFAULT 'queued' CHECK (status IN (
        'queued', 'claimed', 'preparing', 'building', 'validating',
        'succeeded', 'succeeded-after-repair', 'failed-source',
        'failed-dependencies', 'failed-build', 'failed-extraction',
        'failed-validation', 'timed-out', 'infrastructure-error')),
    claimed_by text,
    lease_token text,
    lease_expires_at timestamptz,
    attempt_count integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (cve, variant, mode, source_digest, toolchain_digest)
);

ALTER TABLE cgactl.jobs ADD COLUMN IF NOT EXISTS lane text NOT NULL
    DEFAULT 'static' CHECK (lane IN ('static', 'llm-repair', 'master-recovery'));
ALTER TABLE cgactl.jobs ADD COLUMN IF NOT EXISTS disposition text NOT NULL
    DEFAULT 'ready' CHECK (disposition IN (
        'ready', 'running', 'awaiting-llm', 'escalated',
        'awaiting-promotion', 'completed'));
ALTER TABLE cgactl.jobs ADD COLUMN IF NOT EXISTS base_snapshot text;
ALTER TABLE cgactl.jobs ADD COLUMN IF NOT EXISTS resource_profile text
    NOT NULL DEFAULT 'default';
ALTER TABLE cgactl.jobs ADD COLUMN IF NOT EXISTS exclusive_host boolean
    NOT NULL DEFAULT false;

CREATE TABLE IF NOT EXISTS cgactl.builders (
    builder_id text PRIMARY KEY,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    registered_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    last_heartbeat_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS cgactl.attempts (
    job_id text NOT NULL REFERENCES cgactl.jobs(job_id),
    attempt integer NOT NULL,
    builder_id text NOT NULL REFERENCES cgactl.builders(builder_id),
    lease_token text NOT NULL UNIQUE,
    status text NOT NULL,
    started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    finished_at timestamptz,
    result jsonb NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (job_id, attempt)
);

ALTER TABLE cgactl.attempts ADD COLUMN IF NOT EXISTS lane text NOT NULL
    DEFAULT 'static';
ALTER TABLE cgactl.attempts ADD COLUMN IF NOT EXISTS base_snapshot text;
ALTER TABLE cgactl.attempts ADD COLUMN IF NOT EXISTS container_name text;
ALTER TABLE cgactl.attempts ADD COLUMN IF NOT EXISTS resource_profile text
    NOT NULL DEFAULT 'default';
ALTER TABLE cgactl.attempts ADD COLUMN IF NOT EXISTS environment jsonb
    NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE cgactl.attempts ADD COLUMN IF NOT EXISTS exclusive_host boolean
    NOT NULL DEFAULT false;

CREATE TABLE IF NOT EXISTS cgactl.job_events (
    event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_id text NOT NULL REFERENCES cgactl.jobs(job_id),
    attempt integer,
    builder_id text,
    status text NOT NULL,
    detail jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS cgactl.artifacts (
    job_id text NOT NULL,
    attempt integer NOT NULL,
    name text NOT NULL,
    uri text NOT NULL,
    sha256 text,
    size_bytes bigint,
    retention_class text,
    PRIMARY KEY (job_id, attempt, name),
    FOREIGN KEY (job_id, attempt)
        REFERENCES cgactl.attempts(job_id, attempt)
);

CREATE TABLE IF NOT EXISTS cgactl.insights (
    insight_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_id text NOT NULL,
    attempt integer NOT NULL,
    scope jsonb NOT NULL DEFAULT '{}'::jsonb,
    body text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (job_id, attempt)
        REFERENCES cgactl.attempts(job_id, attempt)
);

CREATE TABLE IF NOT EXISTS cgactl.recipes (
    recipe_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_id text NOT NULL REFERENCES cgactl.jobs(job_id),
    attempt integer,
    recipe jsonb NOT NULL,
    promoted boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (job_id, attempt)
        REFERENCES cgactl.attempts(job_id, attempt)
);

CREATE TABLE IF NOT EXISTS cgactl.promotions (
    job_id text PRIMARY KEY REFERENCES cgactl.jobs(job_id),
    collection_path text NOT NULL,
    archive_path text NOT NULL,
    provenance_path text NOT NULL,
    resource_report_path text,
    promoted_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS cgactl.base_snapshots (
    snapshot_id text PRIMARY KEY,
    container_name text NOT NULL,
    snapshot_name text NOT NULL,
    toolchain_digest text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    active boolean NOT NULL DEFAULT true,
    registered_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (container_name, snapshot_name)
);

CREATE TABLE IF NOT EXISTS cgactl.resource_profiles (
    profile_name text PRIMARY KEY,
    cpu_count integer CHECK (cpu_count IS NULL OR cpu_count > 0),
    memory_bytes bigint CHECK (memory_bytes IS NULL OR memory_bytes > 0),
    disk_bytes bigint CHECK (disk_bytes IS NULL OR disk_bytes > 0),
    exclusive_host boolean NOT NULL DEFAULT false,
    max_concurrent integer CHECK (max_concurrent IS NULL OR max_concurrent > 0),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

ALTER TABLE cgactl.resource_profiles ADD COLUMN IF NOT EXISTS
    max_concurrent integer CHECK (max_concurrent IS NULL OR max_concurrent > 0);

INSERT INTO cgactl.resource_profiles(profile_name)
VALUES ('default') ON CONFLICT DO NOTHING;
UPDATE cgactl.resource_profiles SET max_concurrent = 1
WHERE profile_name = 'default' AND max_concurrent IS NULL;

CREATE TABLE IF NOT EXISTS cgactl.promotion_queue (
    job_id text PRIMARY KEY REFERENCES cgactl.jobs(job_id),
    status text NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending', 'promoting', 'completed', 'failed')),
    attempts integer NOT NULL DEFAULT 0,
    last_error text,
    queued_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

UPDATE cgactl.jobs SET disposition = CASE
    WHEN status IN ('succeeded', 'succeeded-after-repair') THEN 'completed'
    WHEN status = 'queued' THEN 'ready'
    WHEN status IN ('claimed', 'preparing', 'building', 'validating')
        THEN 'running'
    ELSE 'awaiting-llm' END
WHERE disposition = 'ready' AND status <> 'queued';

INSERT INTO cgactl.promotion_queue(job_id, status)
SELECT j.job_id, CASE WHEN p.job_id IS NULL THEN 'pending' ELSE 'completed' END
FROM cgactl.jobs j LEFT JOIN cgactl.promotions p USING (job_id)
WHERE j.status IN ('succeeded', 'succeeded-after-repair')
ON CONFLICT (job_id) DO NOTHING;

CREATE UNIQUE INDEX IF NOT EXISTS jobs_one_active_per_builder
ON cgactl.jobs (claimed_by)
WHERE claimed_by IS NOT NULL AND status IN
    ('claimed', 'preparing', 'building', 'validating');

CREATE INDEX IF NOT EXISTS jobs_queue_order
ON cgactl.jobs (priority, job_id) WHERE status = 'queued';
CREATE INDEX IF NOT EXISTS jobs_expired_leases
ON cgactl.jobs (lease_expires_at) WHERE claimed_by IS NOT NULL;
CREATE INDEX IF NOT EXISTS jobs_lane_queue_order
ON cgactl.jobs (lane, priority, job_id) WHERE status = 'queued';
CREATE INDEX IF NOT EXISTS promotion_queue_order
ON cgactl.promotion_queue (status, queued_at);

CREATE OR REPLACE FUNCTION cgactl.load_jobs(doc jsonb) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE
    inserted_count integer;
    input_count integer;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('cgactl.load_jobs'));
    IF COALESCE((doc->>'schema_version')::integer, 0) <> 1 THEN
        RAISE EXCEPTION 'unsupported manifest schema version';
    END IF;
    input_count := jsonb_array_length(COALESCE(doc->'jobs', '[]'::jsonb));
    IF input_count <> (SELECT count(DISTINCT x.job_id)
        FROM jsonb_to_recordset(COALESCE(doc->'jobs', '[]'::jsonb))
        AS x(job_id text)) THEN
        RAISE EXCEPTION 'manifest contains duplicate job ids';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM jsonb_to_recordset(COALESCE(doc->'jobs', '[]'::jsonb)) AS x(
            job_id text, cve text, variant text, mode text,
            source_digest text, toolchain_digest text, priority integer,
            spec jsonb)
        JOIN cgactl.jobs j ON j.job_id = x.job_id
        WHERE (j.cve, j.variant, j.mode, j.source_digest,
               j.toolchain_digest, j.priority, j.spec)
          IS DISTINCT FROM
              (x.cve, x.variant, x.mode, x.source_digest,
               x.toolchain_digest, COALESCE(x.priority, 100),
               COALESCE(x.spec, '{}'::jsonb))) THEN
        RAISE EXCEPTION 'manifest conflicts with an existing job id';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM jsonb_to_recordset(COALESCE(doc->'jobs', '[]'::jsonb)) AS x(
            job_id text, cve text, variant text, mode text,
            source_digest text, toolchain_digest text)
        JOIN cgactl.jobs j
          ON (j.cve, j.variant, j.mode, j.source_digest,
              j.toolchain_digest) =
             (x.cve, x.variant, x.mode, x.source_digest,
              x.toolchain_digest)
        WHERE j.job_id <> x.job_id) THEN
        RAISE EXCEPTION 'manifest identity exists under another job id';
    END IF;
    INSERT INTO cgactl.jobs (
        job_id, cve, variant, mode, source_digest, toolchain_digest,
        priority, spec)
    SELECT x.job_id, x.cve, x.variant, x.mode, x.source_digest,
           x.toolchain_digest, COALESCE(x.priority, 100),
           COALESCE(x.spec, '{}'::jsonb)
    FROM jsonb_to_recordset(COALESCE(doc->'jobs', '[]'::jsonb)) AS x(
        job_id text, cve text, variant text, mode text, source_digest text,
        toolchain_digest text, priority integer, spec jsonb)
    ON CONFLICT DO NOTHING;
    GET DIAGNOSTICS inserted_count = ROW_COUNT;
    RETURN jsonb_build_object('input', input_count, 'inserted', inserted_count,
                              'existing', input_count - inserted_count);
END $$;

CREATE OR REPLACE FUNCTION cgactl.register_builder(
    p_builder text, p_metadata jsonb DEFAULT '{}'::jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, cgactl AS $$
BEGIN
    INSERT INTO cgactl.builders(builder_id, metadata)
    VALUES (p_builder, COALESCE(p_metadata, '{}'::jsonb))
    ON CONFLICT (builder_id) DO UPDATE
    SET metadata = cgactl.builders.metadata || EXCLUDED.metadata,
        last_heartbeat_at = clock_timestamp();
    RETURN jsonb_build_object('builder_id', p_builder, 'registered', true);
END $$;

CREATE OR REPLACE FUNCTION cgactl.claim_job(
    p_builder text, p_token text, p_lease_seconds integer,
    p_metadata jsonb DEFAULT '{}'::jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, cgactl AS $$
DECLARE
    picked cgactl.jobs%ROWTYPE;
BEGIN
    IF p_lease_seconds < 10 OR p_lease_seconds > 86400 THEN
        RAISE EXCEPTION 'lease must be between 10 and 86400 seconds';
    END IF;
    PERFORM cgactl.register_builder(p_builder, p_metadata);
    PERFORM 1 FROM cgactl.builders WHERE builder_id = p_builder FOR UPDATE;

    SELECT * INTO picked FROM cgactl.jobs
    WHERE claimed_by = p_builder
      AND status IN ('claimed', 'preparing', 'building', 'validating')
      AND lease_expires_at > clock_timestamp();
    IF FOUND THEN
        RETURN to_jsonb(picked);
    END IF;

    PERFORM pg_advisory_xact_lock(hashtext('cgactl.claim.scheduler'));
    SELECT j.* INTO picked FROM cgactl.jobs j
    WHERE j.status = 'queued' AND j.lane = 'static'
      AND EXISTS (SELECT 1 FROM cgactl.base_snapshots s
          WHERE s.snapshot_id = j.base_snapshot AND s.active
            AND s.toolchain_digest = j.toolchain_digest)
      AND (p_metadata->>'container' IS NULL OR EXISTS (
          SELECT 1 FROM cgactl.base_snapshots s
          WHERE s.snapshot_id = j.base_snapshot
            AND s.container_name = p_metadata->>'container'))
      AND ((SELECT max_concurrent FROM cgactl.resource_profiles
            WHERE profile_name = j.resource_profile) IS NULL OR
           (SELECT count(*) FROM cgactl.jobs active
            WHERE active.status IN
              ('claimed', 'preparing', 'building', 'validating')
              AND active.resource_profile = j.resource_profile) <
           (SELECT max_concurrent FROM cgactl.resource_profiles
            WHERE profile_name = j.resource_profile))
      AND NOT EXISTS (SELECT 1 FROM cgactl.jobs active
          WHERE active.status IN ('claimed', 'preparing', 'building', 'validating')
            AND active.exclusive_host)
      AND (NOT j.exclusive_host OR NOT EXISTS (
          SELECT 1 FROM cgactl.jobs active WHERE active.status IN
              ('claimed', 'preparing', 'building', 'validating')))
    ORDER BY j.priority, j.job_id
    FOR UPDATE SKIP LOCKED LIMIT 1;
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;

    UPDATE cgactl.jobs SET status = 'claimed', disposition = 'running',
        claimed_by = p_builder,
        lease_token = p_token,
        lease_expires_at = clock_timestamp() +
            make_interval(secs => p_lease_seconds),
        attempt_count = attempt_count + 1,
        updated_at = clock_timestamp()
    WHERE job_id = picked.job_id RETURNING * INTO picked;
    INSERT INTO cgactl.attempts(
        job_id, attempt, builder_id, lease_token, status, lane,
        base_snapshot, resource_profile, exclusive_host)
    VALUES (picked.job_id, picked.attempt_count, p_builder,
            p_token, 'claimed', picked.lane, picked.base_snapshot,
            picked.resource_profile, picked.exclusive_host);
    INSERT INTO cgactl.job_events(
        job_id, attempt, builder_id, status)
    VALUES (picked.job_id, picked.attempt_count, p_builder, 'claimed');
    RETURN to_jsonb(picked);
END $$;

CREATE OR REPLACE FUNCTION cgactl.claim_job_v2(
    p_builder text, p_token text, p_lease_seconds integer, p_lane text,
    p_metadata jsonb DEFAULT '{}'::jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, cgactl AS $$
DECLARE picked cgactl.jobs%ROWTYPE;
BEGIN
    IF p_lease_seconds < 10 OR p_lease_seconds > 86400 THEN
        RAISE EXCEPTION 'lease must be between 10 and 86400 seconds';
    END IF;
    IF p_lane NOT IN ('static', 'llm-repair', 'master-recovery') THEN
        RAISE EXCEPTION 'invalid execution lane %', p_lane;
    END IF;
    PERFORM cgactl.register_builder(p_builder, p_metadata);
    PERFORM 1 FROM cgactl.builders WHERE builder_id = p_builder FOR UPDATE;

    SELECT * INTO picked FROM cgactl.jobs
    WHERE claimed_by = p_builder
      AND status IN ('claimed', 'preparing', 'building', 'validating')
      AND lease_expires_at > clock_timestamp();
    IF FOUND THEN RETURN to_jsonb(picked); END IF;

    PERFORM pg_advisory_xact_lock(hashtext('cgactl.claim.scheduler'));
    SELECT j.* INTO picked FROM cgactl.jobs j
    WHERE j.status = 'queued' AND j.lane = p_lane
      AND EXISTS (SELECT 1 FROM cgactl.base_snapshots s
          WHERE s.snapshot_id = j.base_snapshot AND s.active
            AND s.toolchain_digest = j.toolchain_digest)
      AND (p_metadata->>'container' IS NULL OR EXISTS (
          SELECT 1 FROM cgactl.base_snapshots s
          WHERE s.snapshot_id = j.base_snapshot
            AND s.container_name = p_metadata->>'container'))
      AND ((SELECT max_concurrent FROM cgactl.resource_profiles
            WHERE profile_name = j.resource_profile) IS NULL OR
           (SELECT count(*) FROM cgactl.jobs active
            WHERE active.status IN
              ('claimed', 'preparing', 'building', 'validating')
              AND active.resource_profile = j.resource_profile) <
           (SELECT max_concurrent FROM cgactl.resource_profiles
            WHERE profile_name = j.resource_profile))
      AND NOT EXISTS (SELECT 1 FROM cgactl.jobs active
          WHERE active.status IN ('claimed', 'preparing', 'building', 'validating')
            AND active.exclusive_host)
      AND (NOT j.exclusive_host OR NOT EXISTS (
          SELECT 1 FROM cgactl.jobs active WHERE active.status IN
              ('claimed', 'preparing', 'building', 'validating')))
    ORDER BY j.priority, j.job_id FOR UPDATE SKIP LOCKED LIMIT 1;
    IF NOT FOUND THEN RETURN NULL; END IF;

    UPDATE cgactl.jobs SET status = 'claimed', disposition = 'running',
        claimed_by = p_builder, lease_token = p_token,
        lease_expires_at = clock_timestamp() +
            make_interval(secs => p_lease_seconds),
        attempt_count = attempt_count + 1, updated_at = clock_timestamp()
    WHERE job_id = picked.job_id RETURNING * INTO picked;
    INSERT INTO cgactl.attempts(
        job_id, attempt, builder_id, lease_token, status, lane,
        base_snapshot, resource_profile, exclusive_host)
    VALUES (picked.job_id, picked.attempt_count, p_builder, p_token, 'claimed',
            picked.lane, picked.base_snapshot, picked.resource_profile,
            picked.exclusive_host);
    INSERT INTO cgactl.job_events(job_id, attempt, builder_id, status, detail)
    VALUES (picked.job_id, picked.attempt_count, p_builder, 'claimed',
            jsonb_build_object('lane', picked.lane,
                'resource_profile', picked.resource_profile,
                'base_snapshot', picked.base_snapshot,
                'exclusive_host', picked.exclusive_host));
    RETURN to_jsonb(picked);
END $$;

CREATE OR REPLACE FUNCTION cgactl.renew_lease(
    p_builder text, p_job text, p_token text, p_lease_seconds integer)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, cgactl AS $$
DECLARE renewed cgactl.jobs%ROWTYPE;
BEGIN
    UPDATE cgactl.jobs SET
        lease_expires_at = clock_timestamp() +
            make_interval(secs => p_lease_seconds),
        updated_at = clock_timestamp()
    WHERE job_id = p_job AND claimed_by = p_builder
      AND lease_token = p_token
      AND status IN ('claimed', 'preparing', 'building', 'validating')
      AND lease_expires_at > clock_timestamp()
    RETURNING * INTO renewed;
    IF NOT FOUND THEN RAISE EXCEPTION 'lease is not current'; END IF;
    UPDATE cgactl.builders SET last_heartbeat_at = clock_timestamp()
    WHERE builder_id = p_builder;
    RETURN to_jsonb(renewed);
END $$;

CREATE OR REPLACE FUNCTION cgactl.set_phase(
    p_builder text, p_job text, p_token text, p_status text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, cgactl AS $$
DECLARE changed cgactl.jobs%ROWTYPE;
BEGIN
    IF p_status NOT IN ('preparing', 'building', 'validating') THEN
        RAISE EXCEPTION 'invalid active phase %', p_status;
    END IF;
    UPDATE cgactl.jobs SET status = p_status,
        updated_at = clock_timestamp()
    WHERE job_id = p_job AND claimed_by = p_builder
      AND lease_token = p_token AND lease_expires_at > clock_timestamp()
      AND status IN ('claimed', 'preparing', 'building', 'validating')
    RETURNING * INTO changed;
    IF NOT FOUND THEN RAISE EXCEPTION 'lease is not current'; END IF;
    UPDATE cgactl.attempts SET status = p_status
    WHERE job_id = p_job AND attempt = changed.attempt_count;
    UPDATE cgactl.builders SET last_heartbeat_at = clock_timestamp()
    WHERE builder_id = p_builder;
    INSERT INTO cgactl.job_events(job_id, attempt, builder_id, status)
    VALUES (p_job, changed.attempt_count, p_builder, p_status);
    RETURN to_jsonb(changed);
END $$;

CREATE OR REPLACE FUNCTION cgactl.finish_job(
    p_builder text, p_job text, p_token text, p_status text,
    p_result jsonb DEFAULT '{}'::jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, cgactl AS $$
DECLARE changed cgactl.jobs%ROWTYPE;
BEGIN
    IF p_status NOT IN (
        'succeeded', 'succeeded-after-repair', 'failed-source',
        'failed-dependencies', 'failed-build', 'failed-extraction',
        'failed-validation', 'timed-out', 'infrastructure-error') THEN
        RAISE EXCEPTION 'invalid terminal status %', p_status;
    END IF;
    UPDATE cgactl.jobs SET status = p_status, lease_token = NULL,
        lease_expires_at = NULL,
        disposition = CASE
          WHEN p_status IN ('succeeded', 'succeeded-after-repair')
            THEN 'awaiting-promotion'
          WHEN lane = 'static' THEN 'awaiting-llm'
          ELSE 'escalated'
        END,
        updated_at = clock_timestamp()
    WHERE job_id = p_job AND claimed_by = p_builder
      AND lease_token = p_token AND lease_expires_at > clock_timestamp()
      AND status IN ('claimed', 'preparing', 'building', 'validating')
    RETURNING * INTO changed;
    IF NOT FOUND THEN RAISE EXCEPTION 'lease is not current'; END IF;
    UPDATE cgactl.attempts SET status = p_status,
        finished_at = clock_timestamp(), result = COALESCE(p_result, '{}'::jsonb)
    WHERE job_id = p_job AND attempt = changed.attempt_count;
    UPDATE cgactl.builders SET last_heartbeat_at = clock_timestamp()
    WHERE builder_id = p_builder;
    INSERT INTO cgactl.job_events(
        job_id, attempt, builder_id, status, detail)
    VALUES (p_job, changed.attempt_count, p_builder, p_status,
            COALESCE(p_result, '{}'::jsonb));
    INSERT INTO cgactl.artifacts(
        job_id, attempt, name, uri, sha256, size_bytes, retention_class)
    SELECT p_job, changed.attempt_count, item.key, item.value->>'uri',
           item.value->>'sha256', (item.value->>'size_bytes')::bigint,
           item.value->>'retention_class'
    FROM jsonb_each(COALESCE(p_result->'artifacts', '{}'::jsonb)) item
    WHERE item.value ? 'uri';
    INSERT INTO cgactl.insights(job_id, attempt, scope, body)
    SELECT p_job, changed.attempt_count,
           COALESCE(item.value->'scope', '{}'::jsonb), item.value->>'body'
    FROM jsonb_array_elements(
        COALESCE(p_result->'insights', '[]'::jsonb)) item
    WHERE item.value ? 'body';
    IF p_result ? 'recipe' THEN
        INSERT INTO cgactl.recipes(job_id, attempt, recipe, promoted)
        VALUES (p_job, changed.attempt_count, p_result->'recipe',
                COALESCE((p_result->>'promote_recipe')::boolean, false));
    END IF;
    IF p_status IN ('succeeded', 'succeeded-after-repair') THEN
        INSERT INTO cgactl.promotion_queue(job_id, status, last_error)
        VALUES (p_job, 'pending', NULL)
        ON CONFLICT (job_id) DO UPDATE SET status = 'pending',
            last_error = NULL, updated_at = clock_timestamp();
    END IF;
    RETURN to_jsonb(changed) || jsonb_build_object('result', p_result);
END $$;

CREATE OR REPLACE FUNCTION cgactl.retry_job(
    p_job text, p_reason text) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE changed cgactl.jobs%ROWTYPE;
BEGIN
    UPDATE cgactl.jobs SET status = 'queued', disposition = 'ready',
        claimed_by = NULL,
        lease_token = NULL, lease_expires_at = NULL,
        updated_at = clock_timestamp()
    WHERE job_id = p_job AND status NOT IN
        ('queued', 'claimed', 'preparing', 'building', 'validating')
    RETURNING * INTO changed;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'job is not in a terminal state';
    END IF;
    INSERT INTO cgactl.job_events(job_id, attempt, status, detail)
    VALUES (p_job, changed.attempt_count, 'queued',
            jsonb_build_object('reason', p_reason, 'action', 'retry'));
    RETURN to_jsonb(changed);
END $$;

CREATE OR REPLACE FUNCTION cgactl.advance_failures(
    p_from_lane text, p_to_lane text, p_reason text, p_limit integer DEFAULT 100,
    p_resource_profile text DEFAULT NULL, p_base_snapshot text DEFAULT NULL,
    p_exclusive_host boolean DEFAULT NULL) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE n integer;
BEGIN
    IF (p_from_lane, p_to_lane) NOT IN (
        ('static', 'llm-repair'), ('llm-repair', 'master-recovery'),
        ('master-recovery', 'master-recovery')) THEN
        RAISE EXCEPTION 'invalid lane transition % -> %', p_from_lane, p_to_lane;
    END IF;
    IF p_limit < 1 THEN RAISE EXCEPTION 'limit must be positive'; END IF;
    IF p_resource_profile IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM cgactl.resource_profiles
        WHERE profile_name = p_resource_profile) THEN
        RAISE EXCEPTION 'unknown resource profile %', p_resource_profile;
    END IF;
    WITH selected AS (
        SELECT job_id FROM cgactl.jobs
        WHERE lane = p_from_lane
          AND disposition = CASE WHEN p_from_lane = 'static'
                                 THEN 'awaiting-llm' ELSE 'escalated' END
        ORDER BY priority, job_id FOR UPDATE SKIP LOCKED LIMIT p_limit
    ), changed AS (
        UPDATE cgactl.jobs j SET status = 'queued', disposition = 'ready',
            lane = p_to_lane, claimed_by = NULL, lease_token = NULL,
            lease_expires_at = NULL,
            resource_profile = COALESCE(p_resource_profile, j.resource_profile),
            base_snapshot = COALESCE(p_base_snapshot, j.base_snapshot),
            exclusive_host = COALESCE(
                p_exclusive_host,
                (SELECT exclusive_host FROM cgactl.resource_profiles
                 WHERE profile_name = p_resource_profile),
                j.exclusive_host),
            updated_at = clock_timestamp()
        FROM selected s WHERE j.job_id = s.job_id RETURNING j.job_id
    )
    INSERT INTO cgactl.job_events(job_id, attempt, status, detail)
    SELECT job_id, (SELECT attempt_count FROM cgactl.jobs WHERE
        cgactl.jobs.job_id = changed.job_id), 'queued',
        jsonb_build_object('action', 'advance-failure', 'reason', p_reason,
            'from_lane', p_from_lane, 'to_lane', p_to_lane,
            'resource_profile', p_resource_profile,
            'base_snapshot', p_base_snapshot,
            'exclusive_host', p_exclusive_host)
    FROM changed;
    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN jsonb_build_object('advanced', n, 'from_lane', p_from_lane,
                              'to_lane', p_to_lane);
END $$;

CREATE OR REPLACE FUNCTION cgactl.configure_job(
    p_job text, p_lane text, p_resource_profile text,
    p_base_snapshot text, p_exclusive_host boolean) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE changed cgactl.jobs%ROWTYPE;
BEGIN
    IF p_lane NOT IN ('static', 'llm-repair', 'master-recovery') THEN
        RAISE EXCEPTION 'invalid execution lane %', p_lane;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM cgactl.resource_profiles
                   WHERE profile_name = p_resource_profile) THEN
        RAISE EXCEPTION 'unknown resource profile %', p_resource_profile;
    END IF;
    IF p_base_snapshot IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM cgactl.base_snapshots
        WHERE snapshot_id = p_base_snapshot AND active) THEN
        RAISE EXCEPTION 'unknown or inactive base snapshot %', p_base_snapshot;
    END IF;
    UPDATE cgactl.jobs SET lane = p_lane,
        resource_profile = p_resource_profile,
        base_snapshot = p_base_snapshot,
        exclusive_host = p_exclusive_host OR (SELECT exclusive_host
            FROM cgactl.resource_profiles
            WHERE profile_name = p_resource_profile),
        updated_at = clock_timestamp()
    WHERE job_id = p_job AND status = 'queued' RETURNING * INTO changed;
    IF NOT FOUND THEN RAISE EXCEPTION 'job is not queued'; END IF;
    RETURN to_jsonb(changed);
END $$;

CREATE OR REPLACE FUNCTION cgactl.configure_queued_jobs(
    p_lane text, p_resource_profile text, p_base_snapshot text,
    p_exclusive_host boolean, p_limit integer DEFAULT 100000) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE n integer;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM cgactl.resource_profiles
                   WHERE profile_name = p_resource_profile) THEN
        RAISE EXCEPTION 'unknown resource profile %', p_resource_profile;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM cgactl.base_snapshots
        WHERE snapshot_id = p_base_snapshot AND active) THEN
        RAISE EXCEPTION 'unknown or inactive base snapshot %', p_base_snapshot;
    END IF;
    WITH selected AS (
        SELECT job_id FROM cgactl.jobs WHERE status = 'queued' AND lane = p_lane
        ORDER BY priority, job_id FOR UPDATE SKIP LOCKED LIMIT p_limit
    )
    UPDATE cgactl.jobs j SET resource_profile = p_resource_profile,
        base_snapshot = p_base_snapshot,
        exclusive_host = p_exclusive_host OR (SELECT exclusive_host
            FROM cgactl.resource_profiles
            WHERE profile_name = p_resource_profile),
        updated_at = clock_timestamp()
    FROM selected s WHERE j.job_id = s.job_id;
    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN jsonb_build_object('configured', n, 'lane', p_lane,
        'resource_profile', p_resource_profile,
        'base_snapshot', p_base_snapshot);
END $$;

CREATE OR REPLACE FUNCTION cgactl.record_attempt_environment(
    p_builder text, p_job text, p_token text, p_container text,
    p_environment jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, cgactl AS $$
DECLARE changed cgactl.attempts%ROWTYPE;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM cgactl.jobs WHERE job_id = p_job
        AND claimed_by = p_builder AND lease_token = p_token
        AND lease_expires_at > clock_timestamp()
        AND status IN ('claimed', 'preparing', 'building', 'validating')) THEN
        RAISE EXCEPTION 'lease is not current';
    END IF;
    UPDATE cgactl.attempts SET container_name = p_container,
        environment = COALESCE(p_environment, '{}'::jsonb)
    WHERE job_id = p_job AND attempt = (
        SELECT attempt_count FROM cgactl.jobs WHERE job_id = p_job)
    RETURNING * INTO changed;
    RETURN to_jsonb(changed);
END $$;

CREATE OR REPLACE FUNCTION cgactl.requeue_expired() RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE n integer;
BEGIN
    WITH expired AS (
        UPDATE cgactl.jobs SET status = 'queued', disposition = 'ready',
            claimed_by = NULL,
            lease_token = NULL, lease_expires_at = NULL,
            updated_at = clock_timestamp()
        WHERE status IN ('claimed', 'preparing', 'building', 'validating')
          AND lease_expires_at <= clock_timestamp()
        RETURNING job_id, attempt_count
    ), closed AS (
        UPDATE cgactl.attempts a SET status = 'infrastructure-error',
            finished_at = clock_timestamp(),
            result = jsonb_build_object('reason', 'lease expired')
        FROM expired e WHERE a.job_id = e.job_id
          AND a.attempt = e.attempt_count
        RETURNING a.job_id, a.attempt, a.builder_id
    )
    INSERT INTO cgactl.job_events(job_id, attempt, builder_id, status, detail)
    SELECT job_id, attempt, builder_id, 'infrastructure-error',
           jsonb_build_object('reason', 'lease expired') FROM closed;
    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN jsonb_build_object('requeued', n);
END $$;

CREATE OR REPLACE FUNCTION cgactl.record_promotion(
    p_job text, p_collection text, p_archive text, p_provenance text,
    p_report text DEFAULT '') RETURNS jsonb LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO cgactl.promotions(
        job_id, collection_path, archive_path, provenance_path,
        resource_report_path)
    VALUES (p_job, p_collection, p_archive, p_provenance,
            NULLIF(p_report, ''))
    ON CONFLICT (job_id) DO UPDATE SET
        collection_path = EXCLUDED.collection_path,
        archive_path = EXCLUDED.archive_path,
        provenance_path = EXCLUDED.provenance_path,
        resource_report_path = EXCLUDED.resource_report_path,
        promoted_at = clock_timestamp();
    INSERT INTO cgactl.promotion_queue(job_id, status, updated_at)
    VALUES (p_job, 'completed', clock_timestamp())
    ON CONFLICT (job_id) DO UPDATE SET status = 'completed',
        last_error = NULL, updated_at = clock_timestamp();
    UPDATE cgactl.jobs SET disposition = 'completed',
        updated_at = clock_timestamp() WHERE job_id = p_job;
    RETURN jsonb_build_object('job_id', p_job, 'recorded', true);
END $$;

CREATE OR REPLACE FUNCTION cgactl.claim_promotion() RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE picked cgactl.promotion_queue%ROWTYPE;
BEGIN
    SELECT * INTO picked FROM cgactl.promotion_queue
    WHERE status = 'pending'
    ORDER BY queued_at FOR UPDATE SKIP LOCKED LIMIT 1;
    IF NOT FOUND THEN RETURN NULL; END IF;
    UPDATE cgactl.promotion_queue SET status = 'promoting',
        attempts = attempts + 1, updated_at = clock_timestamp()
    WHERE job_id = picked.job_id RETURNING * INTO picked;
    RETURN to_jsonb(picked);
END $$;

CREATE OR REPLACE FUNCTION cgactl.fail_promotion(
    p_job text, p_error text) RETURNS jsonb LANGUAGE plpgsql AS $$
BEGIN
    UPDATE cgactl.promotion_queue SET status = 'failed',
        last_error = left(p_error, 8000), updated_at = clock_timestamp()
    WHERE job_id = p_job;
    RETURN jsonb_build_object('job_id', p_job, 'status', 'failed');
END $$;

CREATE OR REPLACE FUNCTION cgactl.requeue_stale_promotions(
    p_age_seconds integer DEFAULT 3600) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE n integer;
BEGIN
    UPDATE cgactl.promotion_queue SET status = 'pending',
        last_error = 'promotion claim expired', updated_at = clock_timestamp()
    WHERE status = 'promoting' AND updated_at < clock_timestamp() -
        make_interval(secs => p_age_seconds);
    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN jsonb_build_object('requeued', n);
END $$;

CREATE OR REPLACE FUNCTION cgactl.register_snapshot(
    p_snapshot text, p_container text, p_name text, p_toolchain text,
    p_metadata jsonb DEFAULT '{}'::jsonb) RETURNS jsonb LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO cgactl.base_snapshots(
        snapshot_id, container_name, snapshot_name, toolchain_digest, metadata)
    VALUES (p_snapshot, p_container, p_name, p_toolchain,
            COALESCE(p_metadata, '{}'::jsonb))
    ON CONFLICT (snapshot_id) DO UPDATE SET
        container_name = EXCLUDED.container_name,
        snapshot_name = EXCLUDED.snapshot_name,
        toolchain_digest = EXCLUDED.toolchain_digest,
        metadata = EXCLUDED.metadata, active = true;
    RETURN jsonb_build_object('snapshot_id', p_snapshot, 'registered', true);
END $$;

DROP FUNCTION IF EXISTS cgactl.set_resource_profile(
    text, integer, bigint, bigint, boolean, jsonb);
CREATE OR REPLACE FUNCTION cgactl.set_resource_profile(
    p_name text, p_cpu integer, p_memory bigint, p_disk bigint,
    p_exclusive boolean, p_max_concurrent integer,
    p_metadata jsonb DEFAULT '{}'::jsonb)
RETURNS jsonb LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO cgactl.resource_profiles(
        profile_name, cpu_count, memory_bytes, disk_bytes, exclusive_host,
        max_concurrent, metadata)
    VALUES (p_name, p_cpu, p_memory, p_disk, p_exclusive,
            p_max_concurrent, COALESCE(p_metadata, '{}'::jsonb))
    ON CONFLICT (profile_name) DO UPDATE SET cpu_count = EXCLUDED.cpu_count,
        memory_bytes = EXCLUDED.memory_bytes, disk_bytes = EXCLUDED.disk_bytes,
        exclusive_host = EXCLUDED.exclusive_host,
        max_concurrent = EXCLUDED.max_concurrent,
        metadata = EXCLUDED.metadata, updated_at = clock_timestamp();
    RETURN jsonb_build_object('profile_name', p_name, 'configured', true);
END $$;

DROP VIEW IF EXISTS cgactl.job_dashboard;
CREATE VIEW cgactl.job_dashboard AS
SELECT j.job_id, j.cve, j.variant, j.mode, j.status, j.priority, j.claimed_by,
       j.lease_expires_at, j.attempt_count, j.updated_at,
       j.spec->>'package' AS package, j.spec->>'version' AS version,
       CASE WHEN p.resource_report_path IS NOT NULL THEN
         '/collection/' || regexp_replace(
           p.resource_report_path, '^' || regexp_replace(
             p.collection_path, '([.\\+*?\[\](){}|^$])', '\\\1', 'g') || '/?', '')
       END AS resource_report_url,
       j.lane, j.disposition, j.base_snapshot, j.resource_profile,
       j.exclusive_host, q.status AS promotion_status,
       COALESCE(a.result->'failure'->>'message', a.result->>'reason')
           AS failure_reason,
       q.last_error AS promotion_error
FROM cgactl.jobs j
LEFT JOIN cgactl.promotions p ON p.job_id = j.job_id
LEFT JOIN cgactl.promotion_queue q ON q.job_id = j.job_id
LEFT JOIN cgactl.attempts a
  ON a.job_id = j.job_id AND a.attempt = j.attempt_count;

CREATE OR REPLACE VIEW cgactl.builder_dashboard AS
SELECT b.builder_id, b.metadata, b.last_heartbeat_at,
       j.job_id AS current_job, j.status AS phase, j.lease_expires_at
FROM cgactl.builders b
LEFT JOIN cgactl.jobs j ON j.claimed_by = b.builder_id
 AND j.status IN ('claimed', 'preparing', 'building', 'validating');

REVOKE ALL ON SCHEMA cgactl FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA cgactl FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA cgactl FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA cgactl FROM PUBLIC;

COMMIT;
