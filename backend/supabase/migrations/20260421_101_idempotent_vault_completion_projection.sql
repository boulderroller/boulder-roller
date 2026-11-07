-- Migration: 20260421_101_idempotent_vault_completion_projection.sql
-- Description: Make vault completion replay idempotency structural.
-- Date: 2026-04-21
--
-- Historical vault replay and live ride processing both write the same
-- vault_completions projection. The unique key is (vault_signature,
-- activity_id), but the previous repository path incremented
-- indexed_vaults.total_completions after every upsert call. Retries could
-- therefore inflate totals even when the projection row did not change.

CREATE OR REPLACE FUNCTION record_vault_completion_projection(
    p_vault_signature TEXT,
    p_wallet TEXT,
    p_activity_id TEXT,
    p_time_seconds INTEGER DEFAULT NULL,
    p_completed_at TIMESTAMPTZ DEFAULT now(),
    p_validated BOOLEAN DEFAULT true,
    p_validation_notes TEXT DEFAULT NULL
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
'Idempotently records a vault completion projection and increments indexed_vaults exactly once per (vault_signature, activity_id).';
