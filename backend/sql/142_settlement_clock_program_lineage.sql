-- Immutable V4-A -> V4-B ProgramConfig lineage for the ratified canon runtime.
-- Canonical mirror:
-- backend/supabase/migrations/20260727_150_settlement_clock_program_lineage.sql
--
-- The settlement clock contract remains byte-for-byte bound to the V4-A
-- finalized source that established week history. This migration authorizes
-- exactly one successor ProgramConfig projection without replacing that
-- historical evidence or changing any settlement-week boundary.

CREATE TABLE IF NOT EXISTS public.settlement_clock_program_lineage (
    id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    contract_hash TEXT NOT NULL CHECK (contract_hash ~ '^[0-9a-f]{64}$'),
    predecessor_program_id TEXT NOT NULL,
    predecessor_program_config_pda TEXT NOT NULL,
    predecessor_program_config_slot NUMERIC(39, 0) NOT NULL
        CHECK (predecessor_program_config_slot >= 0),
    successor_program_id TEXT NOT NULL,
    successor_program_config_pda TEXT NOT NULL,
    successor_handoff_slot NUMERIC(39, 0) NOT NULL
        CHECK (successor_handoff_slot >= 0),
    cutover_unix BIGINT NOT NULL,
    settlement_clock_version SMALLINT NOT NULL
        CHECK (settlement_clock_version = 2),
    bridge_program_sha256 TEXT NOT NULL
        CHECK (bridge_program_sha256 ~ '^[0-9a-f]{64}$'),
    canonical_program_sha256 TEXT NOT NULL
        CHECK (canonical_program_sha256 ~ '^[0-9a-f]{64}$'),
    bridge_deploy_signature TEXT NOT NULL
        CHECK (bridge_deploy_signature ~ '^[1-9A-HJ-NP-Za-km-z]{64,88}$'),
    handoff_signature TEXT NOT NULL
        CHECK (handoff_signature ~ '^[1-9A-HJ-NP-Za-km-z]{64,88}$'),
    canonical_restore_signature TEXT NOT NULL
        CHECK (canonical_restore_signature ~ '^[1-9A-HJ-NP-Za-km-z]{64,88}$'),
    decision_reference TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT pg_catalog.now()
);

ALTER TABLE public.settlement_clock_program_lineage ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.settlement_clock_program_lineage FROM PUBLIC;
DO $$
DECLARE
    v_role TEXT;
BEGIN
    FOREACH v_role IN ARRAY ARRAY['anon', 'authenticated', 'service_role']
    LOOP
        IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = v_role) THEN
            EXECUTE pg_catalog.format(
                'REVOKE ALL ON public.settlement_clock_program_lineage FROM %I',
                v_role
            );
        END IF;
    END LOOP;
END;
$$;

DO $$
DECLARE
    v_has_lineage BOOLEAN;
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM public.settlement_clock_contract
        WHERE id = 1
          AND contract_version = 2
          AND legacy_anchor_unix = 1704020400
          AND v2_anchor_unix = 1704110400
          AND cutover_unix = 1784548800
          AND cutover_week = 133
          AND duration_seconds = 604800
          AND grace_seconds = 86400
          AND has_legacy_history IS TRUE
          AND program_config_pda =
              'DtDkrJBoEbK9PEUzG731M2MFX1tGBhL3dX2SQ9FckPD8'
          AND program_config_slot = 476802238
          AND program_config_commitment = 'finalized'
          AND contract_hash =
              '0b05fb0951a522006eb3580a2bdcf8c062ae63237635eecc19cdd17417617e93'
          AND contract_hash = public.br_settlement_clock_evidence_hash(
              cutover_unix,
              program_config_pda,
              program_config_slot,
              program_config_commitment
          )
    ) THEN
        RAISE EXCEPTION
            'ratified settlement clock predecessor contract does not match';
    END IF;

    SELECT EXISTS (
        SELECT 1
        FROM public.settlement_clock_program_lineage
        WHERE id = 1
    ) INTO v_has_lineage;

    IF v_has_lineage THEN
        IF NOT EXISTS (
            SELECT 1
            FROM public.settlement_clock_program_lineage
            WHERE id = 1
              AND contract_hash =
                  '0b05fb0951a522006eb3580a2bdcf8c062ae63237635eecc19cdd17417617e93'
              AND predecessor_program_id =
                  'HsPhhMukUKu641e9hDJUJJW4chvF5EXYzuG2xBwMrnst'
              AND predecessor_program_config_pda =
                  'DtDkrJBoEbK9PEUzG731M2MFX1tGBhL3dX2SQ9FckPD8'
              AND predecessor_program_config_slot = 476802238
              AND successor_program_id =
                  'EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH'
              AND successor_program_config_pda =
                  '59baJ2JF7WBjMp8xTtvyw5uaiN9K8R3NX868kGyWZq2D'
              AND successor_handoff_slot = 479325255
              AND cutover_unix = 1784548800
              AND settlement_clock_version = 2
              AND bridge_program_sha256 =
                  '96429b5232d408359ce906426ebaaebc163a56991e1086c9811f0df9c8a08678'
              AND canonical_program_sha256 =
                  'bd2d1f31c791c86fed57da1b3c257f9fbaa050caea31bc5de5862f663eb11452'
              AND bridge_deploy_signature =
                  '2m65dhhridexQULkWLzXP5cVdcnXs3UKNtyH3o4PgCAd57wbVKcjEiCGMKbMBnK8XqF9MhdXL76TZi7EfEV9pCbk'
              AND handoff_signature =
                  '4tnsaBQFCgfkCJqvjJ2QEwP7LvuQ3StArUFvm5W7MseMxQL72pdbAnGZ3WCGhzUxU1jJ7oCTu7yCAYmsCohQAtcW'
              AND canonical_restore_signature =
                  'TGmMuR6WHgc3u9ZkH4mcq8VZoCWbDbGAd4m4SBDYbEsWaBmMVzhiP3a2JKoMj2PwK4peTtb65y3mYW2WW86rNEE'
              AND decision_reference =
                  'history/V4_B_TRUTH_CONTRACT_CHANGE_2026-07-21.md'
        ) THEN
            RAISE EXCEPTION
                'settlement clock program lineage differs from ratified evidence';
        END IF;
    ELSE
        IF NOT EXISTS (
            SELECT 1
            FROM public.indexed_program_config
            WHERE id = 1
              AND pda = 'DtDkrJBoEbK9PEUzG731M2MFX1tGBhL3dX2SQ9FckPD8'
              AND chain_slot >= 476802238
              AND settlement_clock_v2_starts_at = 1784548800
              AND settlement_clock_version = 2
              AND settlement_clock_source_commitment = 'finalized'
        ) THEN
            RAISE EXCEPTION
                'indexed ProgramConfig does not match ratified V4-A predecessor';
        END IF;

        INSERT INTO public.settlement_clock_program_lineage (
            id,
            contract_hash,
            predecessor_program_id,
            predecessor_program_config_pda,
            predecessor_program_config_slot,
            successor_program_id,
            successor_program_config_pda,
            successor_handoff_slot,
            cutover_unix,
            settlement_clock_version,
            bridge_program_sha256,
            canonical_program_sha256,
            bridge_deploy_signature,
            handoff_signature,
            canonical_restore_signature,
            decision_reference
        ) VALUES (
            1,
            '0b05fb0951a522006eb3580a2bdcf8c062ae63237635eecc19cdd17417617e93',
            'HsPhhMukUKu641e9hDJUJJW4chvF5EXYzuG2xBwMrnst',
            'DtDkrJBoEbK9PEUzG731M2MFX1tGBhL3dX2SQ9FckPD8',
            476802238,
            'EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH',
            '59baJ2JF7WBjMp8xTtvyw5uaiN9K8R3NX868kGyWZq2D',
            479325255,
            1784548800,
            2,
            '96429b5232d408359ce906426ebaaebc163a56991e1086c9811f0df9c8a08678',
            'bd2d1f31c791c86fed57da1b3c257f9fbaa050caea31bc5de5862f663eb11452',
            '2m65dhhridexQULkWLzXP5cVdcnXs3UKNtyH3o4PgCAd57wbVKcjEiCGMKbMBnK8XqF9MhdXL76TZi7EfEV9pCbk',
            '4tnsaBQFCgfkCJqvjJ2QEwP7LvuQ3StArUFvm5W7MseMxQL72pdbAnGZ3WCGhzUxU1jJ7oCTu7yCAYmsCohQAtcW',
            'TGmMuR6WHgc3u9ZkH4mcq8VZoCWbDbGAd4m4SBDYbEsWaBmMVzhiP3a2JKoMj2PwK4peTtb65y3mYW2WW86rNEE',
            'history/V4_B_TRUTH_CONTRACT_CHANGE_2026-07-21.md'
        );
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.indexed_program_config
        WHERE id = 1
          AND (
              (
                  pda = 'DtDkrJBoEbK9PEUzG731M2MFX1tGBhL3dX2SQ9FckPD8'
                  AND chain_slot >= 476802238
              )
              OR (
                  pda = '59baJ2JF7WBjMp8xTtvyw5uaiN9K8R3NX868kGyWZq2D'
                  AND chain_slot >= 479325255
              )
          )
          AND settlement_clock_v2_starts_at = 1784548800
          AND settlement_clock_version = 2
          AND settlement_clock_source_commitment = 'finalized'
    ) THEN
        RAISE EXCEPTION
            'indexed ProgramConfig is outside ratified settlement clock lineage';
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION
    public.br_guard_settlement_clock_program_lineage_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
BEGIN
    RAISE EXCEPTION 'settlement clock program lineage is immutable';
END;
$$;

DROP TRIGGER IF EXISTS br_settlement_clock_program_lineage_guard
    ON public.settlement_clock_program_lineage;
CREATE TRIGGER br_settlement_clock_program_lineage_guard
BEFORE INSERT OR UPDATE OR DELETE
ON public.settlement_clock_program_lineage
FOR EACH ROW
EXECUTE FUNCTION public.br_guard_settlement_clock_program_lineage_mutation();

CREATE OR REPLACE FUNCTION public.br_guard_indexed_program_config_clock()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_lineage public.settlement_clock_program_lineage%ROWTYPE;
BEGIN
    IF NEW.chain_slot < OLD.chain_slot THEN
        RAISE EXCEPTION 'indexed ProgramConfig slot regression from % to %',
            OLD.chain_slot, NEW.chain_slot;
    END IF;

    SELECT * INTO v_lineage
    FROM public.settlement_clock_program_lineage
    WHERE id = 1;

    IF FOUND THEN
        IF OLD.pda = v_lineage.predecessor_program_config_pda THEN
            IF OLD.chain_slot < v_lineage.predecessor_program_config_slot
               OR OLD.settlement_clock_v2_starts_at <> v_lineage.cutover_unix
               OR OLD.settlement_clock_version <>
                  v_lineage.settlement_clock_version
               OR OLD.settlement_clock_source_commitment <> 'finalized' THEN
                RAISE EXCEPTION
                    'indexed ProgramConfig predecessor lineage state is invalid';
            END IF;
        ELSIF OLD.pda = v_lineage.successor_program_config_pda THEN
            IF OLD.chain_slot < v_lineage.successor_handoff_slot
               OR OLD.settlement_clock_v2_starts_at <> v_lineage.cutover_unix
               OR OLD.settlement_clock_version <>
                  v_lineage.settlement_clock_version
               OR OLD.settlement_clock_source_commitment <> 'finalized' THEN
                RAISE EXCEPTION
                    'indexed ProgramConfig successor lineage state is invalid';
            END IF;
        ELSE
            RAISE EXCEPTION
                'indexed ProgramConfig lineage source is neither predecessor nor successor';
        END IF;

        IF NEW.pda <> v_lineage.successor_program_config_pda THEN
            RAISE EXCEPTION
                'indexed ProgramConfig is not the ratified successor';
        END IF;
        IF NEW.chain_slot IS NULL
           OR NEW.chain_slot < v_lineage.successor_handoff_slot THEN
            RAISE EXCEPTION
                'indexed ProgramConfig successor handoff slot is below %',
                v_lineage.successor_handoff_slot;
        END IF;
        IF NEW.settlement_clock_version <>
               v_lineage.settlement_clock_version
           OR NEW.settlement_clock_v2_starts_at <> v_lineage.cutover_unix
           OR NEW.settlement_clock_source_commitment <> 'finalized' THEN
            RAISE EXCEPTION
                'indexed ProgramConfig attempted to replace immutable settlement clock';
        END IF;
        RETURN NEW;
    END IF;

    IF OLD.settlement_clock_version = 2
       AND (
           NEW.settlement_clock_version <> OLD.settlement_clock_version
           OR NEW.settlement_clock_v2_starts_at <>
              OLD.settlement_clock_v2_starts_at
           OR NEW.settlement_clock_source_commitment <>
              OLD.settlement_clock_source_commitment
       ) THEN
        RAISE EXCEPTION
            'indexed ProgramConfig attempted to replace immutable settlement clock';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.br_sync_settlement_clock_contract()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
    v_cutover BIGINT;
    v_cutover_week BIGINT;
    v_has_legacy BOOLEAN;
    v_hash TEXT;
    v_existing_hash TEXT;
    v_existing public.settlement_clock_contract%ROWTYPE;
    v_lineage public.settlement_clock_program_lineage%ROWTYPE;
    v_has_existing BOOLEAN;
    v_has_lineage BOOLEAN;
BEGIN
    IF NEW.settlement_clock_version = 0
       AND NEW.settlement_clock_v2_starts_at = 0 THEN
        RETURN NEW;
    END IF;
    IF NEW.settlement_clock_version <> 2 THEN
        RAISE EXCEPTION
            'unsupported settlement clock version %',
            NEW.settlement_clock_version;
    END IF;
    IF NEW.settlement_clock_source_commitment <> 'finalized'
       OR NEW.chain_slot IS NULL THEN
        RAISE EXCEPTION
            'settlement clock requires a finalized ProgramConfig projection';
    END IF;

    v_cutover := NEW.settlement_clock_v2_starts_at;
    v_has_legacy := v_cutover <> 1704110400;
    IF v_cutover < 1704110400
       OR MOD(v_cutover - 1704110400, 604800) <> 0 THEN
        RAISE EXCEPTION
            'invalid Monday settlement clock cutover %',
            v_cutover;
    END IF;
    v_cutover_week := (v_cutover - 1704110400) / 604800;
    IF v_has_legacy
       AND FLOOR(
           ((v_cutover - 1) - 1704020400)::NUMERIC / 604800
       )::BIGINT <> v_cutover_week THEN
        RAISE EXCEPTION
            'settlement clock cutover would renumber week %',
            v_cutover_week;
    END IF;

    v_hash := public.br_settlement_clock_evidence_hash(
        v_cutover,
        NEW.pda,
        NEW.chain_slot,
        NEW.settlement_clock_source_commitment
    );

    SELECT * INTO v_existing
    FROM public.settlement_clock_contract
    WHERE id = 1;
    v_has_existing := FOUND;

    SELECT * INTO v_lineage
    FROM public.settlement_clock_program_lineage
    WHERE id = 1;
    v_has_lineage := FOUND;

    IF v_has_existing THEN
        v_existing_hash := public.br_settlement_clock_evidence_hash(
            v_existing.cutover_unix,
            v_existing.program_config_pda,
            v_existing.program_config_slot,
            v_existing.program_config_commitment
        );

        IF v_has_lineage THEN
            IF v_existing.cutover_unix <> v_lineage.cutover_unix
               OR v_existing.cutover_week <> v_cutover_week
               OR v_existing.contract_version <>
                  v_lineage.settlement_clock_version
               OR v_existing.legacy_anchor_unix <> 1704020400
               OR v_existing.v2_anchor_unix <> 1704110400
               OR v_existing.duration_seconds <> 604800
               OR v_existing.grace_seconds <> 86400
               OR v_existing.has_legacy_history <> v_has_legacy
               OR v_existing.program_config_pda <>
                  v_lineage.predecessor_program_config_pda
               OR v_existing.program_config_slot <>
                  v_lineage.predecessor_program_config_slot
               OR v_existing.program_config_commitment <> 'finalized'
               OR v_existing.contract_hash <> v_lineage.contract_hash
               OR v_existing.contract_hash <> v_existing_hash THEN
                RAISE EXCEPTION
                    'settlement clock predecessor evidence no longer matches lineage';
            END IF;
            IF NEW.pda <> v_lineage.successor_program_config_pda THEN
                RAISE EXCEPTION
                    'indexed ProgramConfig is not the ratified successor';
            END IF;
            IF NEW.chain_slot < v_lineage.successor_handoff_slot THEN
                RAISE EXCEPTION
                    'indexed ProgramConfig successor handoff slot is below %',
                    v_lineage.successor_handoff_slot;
            END IF;
            IF NEW.settlement_clock_v2_starts_at <>
                   v_lineage.cutover_unix
               OR NEW.settlement_clock_version <>
                  v_lineage.settlement_clock_version
               OR NEW.settlement_clock_source_commitment <> 'finalized' THEN
                RAISE EXCEPTION
                    'indexed ProgramConfig attempted to replace immutable settlement clock';
            END IF;
        ELSIF v_existing.cutover_unix <> v_cutover
           OR v_existing.cutover_week <> v_cutover_week
           OR v_existing.contract_version <> 2
           OR v_existing.legacy_anchor_unix <> 1704020400
           OR v_existing.v2_anchor_unix <> 1704110400
           OR v_existing.duration_seconds <> 604800
           OR v_existing.grace_seconds <> 86400
           OR v_existing.has_legacy_history <> v_has_legacy
           OR v_existing.program_config_pda <> NEW.pda
           OR v_existing.program_config_commitment <> 'finalized'
           OR v_existing.contract_hash <> v_existing_hash THEN
            RAISE EXCEPTION
                'indexed ProgramConfig attempted to replace immutable settlement clock';
        END IF;
    ELSE
        IF v_has_lineage THEN
            RAISE EXCEPTION
                'settlement clock lineage exists without predecessor contract';
        END IF;
        IF v_has_legacy AND EXISTS (
            SELECT 1
            FROM public.settlement_week_runs
            WHERE settlement_week >= v_cutover_week
              AND source_kind = 'authoritative'
        ) THEN
            RAISE EXCEPTION
                'settlement run already exists at or after cutover week %',
                v_cutover_week;
        END IF;

        INSERT INTO public.settlement_clock_contract (
            id,
            contract_version,
            legacy_anchor_unix,
            v2_anchor_unix,
            cutover_unix,
            cutover_week,
            duration_seconds,
            grace_seconds,
            has_legacy_history,
            program_config_pda,
            program_config_slot,
            program_config_commitment,
            contract_hash,
            indexed_at
        ) VALUES (
            1,
            2,
            1704020400,
            1704110400,
            v_cutover,
            v_cutover_week,
            604800,
            86400,
            v_has_legacy,
            NEW.pda,
            NEW.chain_slot,
            NEW.settlement_clock_source_commitment,
            v_hash,
            NEW.indexed_at
        );

        UPDATE public.settlement_planning_state
        SET settlement_clock_version = 2,
            settlement_clock_v2_starts_at = v_cutover,
            settlement_clock_contract_hash = v_hash,
            updated_at = pg_catalog.now()
        WHERE id = 1;
    END IF;

    RETURN NEW;
END;
$$;

COMMENT ON TABLE public.settlement_clock_program_lineage IS
    'Immutable V4-A to V4-B ProgramConfig succession evidence for settlement clock v2.';
COMMENT ON TABLE public.settlement_clock_contract IS
    'Immutable settlement clock evidence; an authorized successor may be bound through settlement_clock_program_lineage without replacing this row.';
