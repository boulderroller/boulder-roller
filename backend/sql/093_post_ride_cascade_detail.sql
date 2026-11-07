-- ============================================================================
-- Post-ride cascade detail
-- ============================================================================
-- Mirrors supabase migration 20260422_102. Keeps the local SQL bundle aligned
-- with the production migration path.

ALTER TABLE vault_completions
    ADD COLUMN IF NOT EXISTS cal_tribute NUMERIC NOT NULL DEFAULT 0;

COMMENT ON COLUMN vault_completions.cal_tribute IS
    'CAL credited to this ride/climb completion. Used by client.v1 RideStatus '
    'post-ride cascade rows; zero means no tribute or legacy pre-column row.';

DROP FUNCTION IF EXISTS record_vault_completion_projection(
    TEXT,
    TEXT,
    TEXT,
    INTEGER,
    TIMESTAMPTZ,
    BOOLEAN,
    TEXT
);

CREATE OR REPLACE FUNCTION record_vault_completion_projection(
    p_vault_signature TEXT,
    p_wallet TEXT,
    p_activity_id TEXT,
    p_time_seconds INTEGER DEFAULT NULL,
    p_completed_at TIMESTAMPTZ DEFAULT now(),
    p_validated BOOLEAN DEFAULT true,
    p_validation_notes TEXT DEFAULT NULL,
    p_cal_tribute NUMERIC DEFAULT 0
) RETURNS TABLE(inserted BOOLEAN, completion JSONB) AS $$
DECLARE
    v_row vault_completions%ROWTYPE;
BEGIN
    INSERT INTO vault_completions (
        vault_signature,
        wallet,
        activity_id,
        time_seconds,
        completed_at,
        validated,
        validation_notes,
        cal_tribute,
        best_time_seconds,
        best_time_achieved_at,
        total_completions
    ) VALUES (
        p_vault_signature,
        p_wallet,
        p_activity_id,
        p_time_seconds,
        p_completed_at,
        p_validated,
        p_validation_notes,
        COALESCE(p_cal_tribute, 0),
        p_time_seconds,
        CASE WHEN p_time_seconds IS NOT NULL THEN p_completed_at ELSE NULL END,
        1
    )
    ON CONFLICT (vault_signature, activity_id) DO NOTHING
    RETURNING * INTO v_row;

    IF FOUND THEN
        PERFORM increment_vault_completions(p_vault_signature);
        RETURN QUERY SELECT true, to_jsonb(v_row);
        RETURN;
    END IF;

    SELECT *
    INTO v_row
    FROM vault_completions
    WHERE vault_signature = p_vault_signature
      AND activity_id = p_activity_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'vault completion projection missing after conflict: vault_signature=%, activity_id=%',
            p_vault_signature,
            p_activity_id;
    END IF;

    RETURN QUERY SELECT false, to_jsonb(v_row);
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION record_vault_completion_projection IS
'Idempotently records a vault completion projection, including per-ride CAL tribute, and increments indexed_vaults exactly once per (vault_signature, activity_id).';
