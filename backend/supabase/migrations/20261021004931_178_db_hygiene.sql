SET LOCAL lock_timeout = '5s';

-- Keep migration 155's settlement evidence rule, using the rides UUID key.
CREATE OR REPLACE FUNCTION public.br_refresh_ride_finalized_at(
    p_activity_id TEXT
) RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    v_finalized_at TIMESTAMPTZ;
    v_ride_id UUID;
BEGIN
    IF p_activity_id IS NULL OR p_activity_id = '' THEN
        RETURN;
    END IF;
    -- activity_id is text and can contain legacy non-UUID identifiers.
    BEGIN
        v_ride_id := p_activity_id::UUID;
    EXCEPTION WHEN invalid_text_representation THEN
        RETURN;
    END;
    -- Preserve the old id::TEXT equality: alternative UUID spellings did
    -- not match a ride. Normalize neither the lookup nor completion evidence.
    IF v_ride_id::TEXT <> p_activity_id THEN
        RETURN;
    END IF;

    WITH confirmed_completions AS (
        SELECT
            completion.completion_evidence_hash,
            completion.completion_evidence_version,
            completion.cal_tribute,
            indexed_vault.id AS vault_id
        FROM public.vault_completions AS completion
        LEFT JOIN public.indexed_vaults AS indexed_vault
          ON indexed_vault.signature_hex = completion.vault_signature
        WHERE completion.activity_id = p_activity_id
          AND completion.chain_confirmation_status = 'confirmed'
    )
    SELECT CASE
        WHEN pg_catalog.count(*) > 0
         AND pg_catalog.count(flow.credited_settlement_week) =
                pg_catalog.count(*)
         AND pg_catalog.count(*) FILTER (WHERE flow.cal_tributed > 0) > 0
         AND pg_catalog.count(distribution.finalized_at)
                FILTER (WHERE flow.cal_tributed > 0)
             = pg_catalog.count(*) FILTER (WHERE flow.cal_tributed > 0)
            THEN pg_catalog.max(distribution.finalized_at)
                FILTER (WHERE flow.cal_tributed > 0)
        ELSE NULL
    END
    INTO v_finalized_at
    FROM confirmed_completions AS completion
    LEFT JOIN public.indexed_climb_completion_flows AS flow
      ON flow.completion_evidence_hash = completion.completion_evidence_hash
     AND flow.vault_id = completion.vault_id
     AND flow.completion_evidence_version =
            completion.completion_evidence_version
     AND flow.completion_evidence_version IN (2, 3)
     AND flow.cal_tributed = completion.cal_tribute
    LEFT JOIN LATERAL (
        SELECT pg_catalog.min(indexed_distribution.finalized_at) AS finalized_at
        FROM public.indexed_epoch_distributions AS indexed_distribution
        WHERE indexed_distribution.vault_id = flow.vault_id
          AND indexed_distribution.epoch = flow.credited_settlement_week
          AND indexed_distribution.finalized_at IS NOT NULL
    ) AS distribution ON true;

    UPDATE public.rides
    SET finalized_at = v_finalized_at
    WHERE id = v_ride_id
      AND finalized_at IS DISTINCT FROM v_finalized_at;
END;
$$;

-- 051 duplicates 047's non-unique (wallet, vault_signature) index. Keep the
-- earlier index used by the trigger-stack fixture; neither backs a constraint.
-- No CASCADE: any unexpected dependency must fail the transaction safely.
DROP INDEX IF EXISTS public.idx_vault_completions_wallet_signature;
