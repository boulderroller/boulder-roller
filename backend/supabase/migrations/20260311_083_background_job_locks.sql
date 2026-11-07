-- =============================================================================
-- 083: Background job leases
--
-- Provides coarse-grained database-backed ownership for long-running background
-- workers that may be started on multiple API instances.
--
-- Current users:
--   - epoch_processor
--   - live background workers that need single-owner execution
--
-- The same owner can renew its lease by calling acquire_background_job_lock()
-- repeatedly before expires_at. A different owner can only take over once the
-- existing lease has expired.
-- =============================================================================

CREATE TABLE IF NOT EXISTS background_job_locks (
    job_name     TEXT PRIMARY KEY,
    owner_id     TEXT NOT NULL,
    acquired_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at   TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_background_job_locks_expires_at
    ON background_job_locks (expires_at);

CREATE OR REPLACE FUNCTION acquire_background_job_lock(
    p_job_name TEXT,
    p_owner_id TEXT,
    p_ttl_seconds INT DEFAULT 900
) RETURNS BOOLEAN AS $$
DECLARE
    v_now TIMESTAMPTZ := NOW();
    v_ttl_seconds INT := GREATEST(COALESCE(p_ttl_seconds, 900), 30);
    v_expires_at TIMESTAMPTZ := v_now + make_interval(secs => v_ttl_seconds);
    v_owner_id TEXT;
BEGIN
    INSERT INTO background_job_locks (
        job_name,
        owner_id,
        acquired_at,
        heartbeat_at,
        expires_at
    )
    VALUES (
        p_job_name,
        p_owner_id,
        v_now,
        v_now,
        v_expires_at
    )
    ON CONFLICT (job_name) DO UPDATE
    SET owner_id = EXCLUDED.owner_id,
        acquired_at = CASE
            WHEN background_job_locks.owner_id = EXCLUDED.owner_id
                THEN background_job_locks.acquired_at
            ELSE EXCLUDED.acquired_at
        END,
        heartbeat_at = EXCLUDED.heartbeat_at,
        expires_at = EXCLUDED.expires_at
    WHERE background_job_locks.owner_id = EXCLUDED.owner_id
       OR background_job_locks.expires_at <= v_now;

    SELECT owner_id
    INTO v_owner_id
    FROM background_job_locks
    WHERE job_name = p_job_name;

    RETURN v_owner_id = p_owner_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION acquire_background_job_lock IS
'Acquire or renew a coarse-grained lease for a named background job. A lease
can only be stolen after expires_at.';

CREATE OR REPLACE FUNCTION release_background_job_lock(
    p_job_name TEXT,
    p_owner_id TEXT
) RETURNS BOOLEAN AS $$
DECLARE
    v_deleted INT;
BEGIN
    DELETE FROM background_job_locks
    WHERE job_name = p_job_name
      AND owner_id = p_owner_id;

    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RETURN v_deleted > 0;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION release_background_job_lock IS
'Release a background job lease, but only if the caller still owns it.';
