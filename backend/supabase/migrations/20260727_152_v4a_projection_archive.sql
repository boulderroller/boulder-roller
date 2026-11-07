-- Archive collision-prone V4-A numeric Vault projections before the first
-- clean-slate V4-B Vault is created.
-- Canonical mirror:
-- backend/supabase/migrations/20260727_152_v4a_projection_archive.sql

CREATE SCHEMA IF NOT EXISTS legacy_v4a_audit;
REVOKE ALL ON SCHEMA legacy_v4a_audit FROM PUBLIC;

DO $$
DECLARE
    v_role TEXT;
BEGIN
    FOREACH v_role IN ARRAY ARRAY['anon', 'authenticated', 'service_role']
    LOOP
        IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = v_role) THEN
            EXECUTE pg_catalog.format(
                'REVOKE ALL ON SCHEMA legacy_v4a_audit FROM %I',
                v_role
            );
        END IF;
    END LOOP;
END;
$$;

CREATE TABLE IF NOT EXISTS legacy_v4a_audit.cutover_manifests (
    cutover_key TEXT PRIMARY KEY,
    predecessor_program_id TEXT NOT NULL,
    successor_program_id TEXT NOT NULL,
    successor_handoff_slot BIGINT NOT NULL CHECK (successor_handoff_slot >= 0),
    legacy_vault_id_min BIGINT NOT NULL,
    legacy_vault_id_max BIGINT NOT NULL,
    archived_row_count BIGINT NOT NULL CHECK (archived_row_count >= 0),
    retained_live_row_count BIGINT NOT NULL CHECK (retained_live_row_count >= 0),
    table_counts JSONB NOT NULL,
    archive_sha256 CHAR(64) NOT NULL CHECK (
        archive_sha256 ~ '^[0-9a-f]{64}$'
    ),
    decision_reference TEXT NOT NULL,
    archived_at TIMESTAMPTZ NOT NULL DEFAULT pg_catalog.now()
);

CREATE TABLE IF NOT EXISTS legacy_v4a_audit.projection_rows (
    cutover_key TEXT NOT NULL REFERENCES legacy_v4a_audit.cutover_manifests(
        cutover_key
    ) ON DELETE RESTRICT,
    source_table TEXT NOT NULL,
    row_ordinal BIGINT NOT NULL CHECK (row_ordinal > 0),
    row_sha256 CHAR(64) NOT NULL CHECK (row_sha256 ~ '^[0-9a-f]{64}$'),
    payload JSONB NOT NULL,
    archived_at TIMESTAMPTZ NOT NULL DEFAULT pg_catalog.now(),
    PRIMARY KEY (cutover_key, source_table, row_ordinal)
);

CREATE INDEX IF NOT EXISTS idx_legacy_v4a_projection_rows_source
    ON legacy_v4a_audit.projection_rows(cutover_key, source_table);

ALTER TABLE legacy_v4a_audit.cutover_manifests ENABLE ROW LEVEL SECURITY;
ALTER TABLE legacy_v4a_audit.projection_rows ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON ALL TABLES IN SCHEMA legacy_v4a_audit FROM PUBLIC;

DO $$
DECLARE
    v_role TEXT;
BEGIN
    FOREACH v_role IN ARRAY ARRAY['anon', 'authenticated', 'service_role']
    LOOP
        IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = v_role) THEN
            EXECUTE pg_catalog.format(
                'REVOKE ALL ON ALL TABLES IN SCHEMA legacy_v4a_audit FROM %I',
                v_role
            );
        END IF;
    END LOOP;
END;
$$;

DO $archive$
DECLARE
    v_cutover_key CONSTANT TEXT := 'devnet_v4a_to_v4b_20260727';
    v_predecessor_program CONSTANT TEXT :=
        'HsPhhMukUKu641e9hDJUJJW4chvF5EXYzuG2xBwMrnst';
    v_successor_program CONSTANT TEXT :=
        'EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH';
    v_handoff_slot CONSTANT BIGINT := 479325255;
    v_spec RECORD;
    v_count BIGINT;
    v_expected_count BIGINT;
    v_total BIGINT := 0;
    v_counts JSONB := '{}'::JSONB;
    v_archive_hash TEXT;
BEGIN
    PERFORM pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(v_cutover_key, 0)
    );

    IF EXISTS (
        SELECT 1
        FROM legacy_v4a_audit.cutover_manifests
        WHERE cutover_key = v_cutover_key
    ) THEN
        IF EXISTS (
            SELECT 1
            FROM public.indexed_vaults
            WHERE canon_binding_status = 'legacy'
              AND chain_slot < v_handoff_slot
        ) THEN
            RAISE EXCEPTION
                'V4-A archive manifest exists while legacy Vault projections remain live';
        END IF;
        RETURN;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.settlement_clock_program_lineage
        WHERE predecessor_program_id = v_predecessor_program
          AND successor_program_id = v_successor_program
          AND successor_handoff_slot = v_handoff_slot
          AND cutover_unix = 1784548800
    ) THEN
        RAISE EXCEPTION 'ratified V4-A to V4-B program lineage is unavailable';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.indexed_vault_counter
        WHERE id = 1
          AND count = 0
          AND pda = '8qcexnhoo8YYfh73yLY54ng9vfpBG8YdJkA1w7E6C3dT'
          AND chain_slot >= v_handoff_slot
    ) THEN
        RAISE EXCEPTION 'V4-B VaultCounter is not the finalized zero-Vault authority';
    END IF;

    IF EXISTS (
        SELECT 1 FROM public.indexed_climbs WHERE vault_pda IS NOT NULL
    ) OR EXISTS (
        SELECT 1
        FROM public.canon_vault_activations
        WHERE activation_status = 'finalized'
    ) THEN
        RAISE EXCEPTION 'a V4-B Vault already exists; refusing legacy projection archive';
    END IF;

    SELECT pg_catalog.count(*), pg_catalog.min(id), pg_catalog.max(id)
    INTO v_count, v_expected_count, v_total
    FROM public.indexed_vaults;
    IF v_count <> 33 OR v_expected_count <> 0 OR v_total <> 32 THEN
        RAISE EXCEPTION
            'legacy indexed Vault scope is not the exact contiguous 0 through 32 set';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM public.indexed_vaults
        WHERE canon_binding_status <> 'legacy'
           OR chain_slot IS NULL
           OR chain_slot >= v_handoff_slot
    ) THEN
        RAISE EXCEPTION 'indexed Vault scope contains non-legacy or post-handoff state';
    END IF;
    v_total := 0;

    FOR v_spec IN
        SELECT *
        FROM (
            VALUES
                ('indexed_vaults', 'id BETWEEN 0 AND 32 AND canon_binding_status = ''legacy'' AND chain_slot < 479325255'),
                ('indexed_vault_activations', 'vault_id BETWEEN 0 AND 32 AND chain_slot < 479325255'),
                ('indexed_leaderboards', 'vault_id BETWEEN 0 AND 32 AND chain_slot < 479325255'),
                ('indexed_legends', 'vault_id BETWEEN 0 AND 32 AND chain_slot < 479325255'),
                ('indexed_stakes', 'vault_id BETWEEN 0 AND 32 AND chain_slot < 479325255'),
                ('indexed_completions', 'vault_id BETWEEN 0 AND 32 AND chain_slot < 479325255'),
                ('indexed_events', 'vault_id BETWEEN 0 AND 32 AND slot < 479325255'),
                ('indexed_epoch_distributions', 'vault_id BETWEEN 0 AND 32 AND slot < 479325255'),
                ('indexed_staker_allocations', 'vault_id BETWEEN 0 AND 32 AND slot < 479325255'),
                ('indexed_climb_completion_flows', 'vault_id BETWEEN 0 AND 32 AND slot < 479325255'),
                ('vault_creation_handoffs', 'vault_id BETWEEN 0 AND 32 AND updated_at < ''2026-07-27 00:00:00+00''::timestamptz'),
                ('vault_backfill_jobs', 'vault_id BETWEEN 0 AND 32 AND created_at < ''2026-07-27 00:00:00+00''::timestamptz')
        ) AS specs(table_name, predicate)
    LOOP
        IF pg_catalog.to_regclass('public.' || v_spec.table_name) IS NULL THEN
            RAISE EXCEPTION 'required legacy projection table % is unavailable',
                v_spec.table_name;
        END IF;
        EXECUTE pg_catalog.format(
            'SELECT count(*) FROM public.%I WHERE %s',
            v_spec.table_name,
            v_spec.predicate
        ) INTO v_expected_count;
        v_counts := v_counts || pg_catalog.jsonb_build_object(
            v_spec.table_name,
            v_expected_count
        );
        v_total := v_total + v_expected_count;
    END LOOP;

    IF v_total <> 375 THEN
        RAISE EXCEPTION
            'legacy collision-prone projection scope changed: expected 375 rows, found %',
            v_total;
    END IF;

    INSERT INTO legacy_v4a_audit.cutover_manifests (
        cutover_key,
        predecessor_program_id,
        successor_program_id,
        successor_handoff_slot,
        legacy_vault_id_min,
        legacy_vault_id_max,
        archived_row_count,
        retained_live_row_count,
        table_counts,
        archive_sha256,
        decision_reference
    ) VALUES (
        v_cutover_key,
        v_predecessor_program,
        v_successor_program,
        v_handoff_slot,
        0,
        32,
        v_total,
        1,
        v_counts,
        repeat('0', 64),
        'history/V4_B_TRUTH_CONTRACT_CHANGE_2026-07-21.md'
    );

    FOR v_spec IN
        SELECT *
        FROM (
            VALUES
                ('indexed_vaults', 'id BETWEEN 0 AND 32 AND canon_binding_status = ''legacy'' AND chain_slot < 479325255'),
                ('indexed_vault_activations', 'vault_id BETWEEN 0 AND 32 AND chain_slot < 479325255'),
                ('indexed_leaderboards', 'vault_id BETWEEN 0 AND 32 AND chain_slot < 479325255'),
                ('indexed_legends', 'vault_id BETWEEN 0 AND 32 AND chain_slot < 479325255'),
                ('indexed_stakes', 'vault_id BETWEEN 0 AND 32 AND chain_slot < 479325255'),
                ('indexed_completions', 'vault_id BETWEEN 0 AND 32 AND chain_slot < 479325255'),
                ('indexed_events', 'vault_id BETWEEN 0 AND 32 AND slot < 479325255'),
                ('indexed_epoch_distributions', 'vault_id BETWEEN 0 AND 32 AND slot < 479325255'),
                ('indexed_staker_allocations', 'vault_id BETWEEN 0 AND 32 AND slot < 479325255'),
                ('indexed_climb_completion_flows', 'vault_id BETWEEN 0 AND 32 AND slot < 479325255'),
                ('vault_creation_handoffs', 'vault_id BETWEEN 0 AND 32 AND updated_at < ''2026-07-27 00:00:00+00''::timestamptz'),
                ('vault_backfill_jobs', 'vault_id BETWEEN 0 AND 32 AND created_at < ''2026-07-27 00:00:00+00''::timestamptz')
        ) AS specs(table_name, predicate)
    LOOP
        EXECUTE pg_catalog.format(
            $sql$
            WITH candidates AS (
                SELECT pg_catalog.to_jsonb(source_row) AS payload
                FROM public.%I AS source_row
                WHERE %s
            ),
            ordered AS (
                SELECT payload,
                       row_number() OVER (ORDER BY payload::text) AS row_ordinal
                FROM candidates
            )
            INSERT INTO legacy_v4a_audit.projection_rows (
                cutover_key, source_table, row_ordinal,
                row_sha256, payload
            )
            SELECT %L, %L, row_ordinal,
                   pg_catalog.encode(
                       pg_catalog.sha256(
                           pg_catalog.convert_to(payload::text, 'UTF8')
                       ),
                       'hex'
                   ),
                   payload
            FROM ordered
            $sql$,
            v_spec.table_name,
            v_spec.predicate,
            v_cutover_key,
            v_spec.table_name
        );
        GET DIAGNOSTICS v_count = ROW_COUNT;
        v_expected_count := (v_counts ->> v_spec.table_name)::BIGINT;
        IF v_count <> v_expected_count THEN
            RAISE EXCEPTION 'archive count mismatch for %: expected %, wrote %',
                v_spec.table_name, v_expected_count, v_count;
        END IF;
    END LOOP;

    SELECT pg_catalog.encode(
               pg_catalog.sha256(
                   pg_catalog.convert_to(
                       pg_catalog.string_agg(
                           source_table || ':' || row_ordinal::TEXT || ':' ||
                               row_sha256::TEXT,
                           E'\n'
                           ORDER BY source_table, row_ordinal
                       ),
                       'UTF8'
                   )
               ),
               'hex'
           )
    INTO v_archive_hash
    FROM legacy_v4a_audit.projection_rows
    WHERE cutover_key = v_cutover_key;

    FOR v_spec IN
        SELECT *
        FROM (
            VALUES
                ('indexed_vaults', 'id BETWEEN 0 AND 32 AND canon_binding_status = ''legacy'' AND chain_slot < 479325255'),
                ('indexed_vault_activations', 'vault_id BETWEEN 0 AND 32 AND chain_slot < 479325255'),
                ('indexed_leaderboards', 'vault_id BETWEEN 0 AND 32 AND chain_slot < 479325255'),
                ('indexed_legends', 'vault_id BETWEEN 0 AND 32 AND chain_slot < 479325255'),
                ('indexed_stakes', 'vault_id BETWEEN 0 AND 32 AND chain_slot < 479325255'),
                ('indexed_completions', 'vault_id BETWEEN 0 AND 32 AND chain_slot < 479325255'),
                ('indexed_events', 'vault_id BETWEEN 0 AND 32 AND slot < 479325255'),
                ('indexed_epoch_distributions', 'vault_id BETWEEN 0 AND 32 AND slot < 479325255'),
                ('indexed_staker_allocations', 'vault_id BETWEEN 0 AND 32 AND slot < 479325255'),
                ('vault_backfill_jobs', 'vault_id BETWEEN 0 AND 32 AND created_at < ''2026-07-27 00:00:00+00''::timestamptz'),
                ('vault_creation_handoffs', 'vault_id BETWEEN 0 AND 32 AND updated_at < ''2026-07-27 00:00:00+00''::timestamptz')
        ) AS specs(table_name, predicate)
    LOOP
        EXECUTE pg_catalog.format(
            'DELETE FROM public.%I WHERE %s',
            v_spec.table_name,
            v_spec.predicate
        );
        GET DIAGNOSTICS v_count = ROW_COUNT;
        v_expected_count := (v_counts ->> v_spec.table_name)::BIGINT;
        IF v_count <> v_expected_count THEN
            RAISE EXCEPTION 'delete count mismatch for %: expected %, removed %',
                v_spec.table_name, v_expected_count, v_count;
        END IF;
    END LOOP;

    IF (
        SELECT pg_catalog.count(*)
        FROM public.indexed_climb_completion_flows
        WHERE vault_id BETWEEN 0 AND 32
          AND slot < v_handoff_slot
    ) <> 1 THEN
        RAISE EXCEPTION
            'immutable legacy completion-flow evidence changed during archival';
    END IF;

    UPDATE legacy_v4a_audit.cutover_manifests
    SET archive_sha256 = v_archive_hash
    WHERE cutover_key = v_cutover_key;
END;
$archive$;

COMMENT ON SCHEMA legacy_v4a_audit IS
    'Private, immutable-intent audit archive for V4-A devnet rows removed from collision-prone live V4-B numeric Vault projections.';
COMMENT ON TABLE legacy_v4a_audit.cutover_manifests IS
    'Exact V4-A to V4-B projection archive boundary, counts, and aggregate digest.';
COMMENT ON TABLE legacy_v4a_audit.projection_rows IS
    'Canonical JSONB snapshots and per-row digests for archived V4-A projection rows.';
