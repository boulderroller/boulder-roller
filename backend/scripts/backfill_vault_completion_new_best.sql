-- Backfill: vault_completions.is_pr ("New best") for rows recorded before
-- migration 176_vault_completion_new_best.sql.
--
-- NOT RUN. This is a one-off repair for review, not a migration: the backend
-- migration runner reads backend/sql only, and neither CI nor the deploy runs
-- this file. Run it only after migration 176 is applied and the repair is
-- approved.
--
-- What it does: sets is_pr to the migration 176 rule
-- (public.br_vault_completion_is_new_best) on every row that disagrees with
-- it, and on no other row. Before 176 no current writer set is_pr, so every
-- confirmed completion reads false today; this turns on "New best" for the
-- efforts that were one, and clears any stale true.
--
-- Safety, all inside one transaction:
--   * It refuses to run before migration 176, or while an account deletion is
--     queued or in progress.
--   * The rows it writes still pass every vault_completions trigger. If any
--     trigger would change anything besides is_pr on a written row (for
--     example the settlement clock re-deriving settlement_week), or would move
--     rides.finalized_at, it raises and nothing is written.
--   * It checks that no row disagrees with the rule afterwards.
--   * lock_timeout keeps it from queueing behind live ride processing; rerun
--     at a quieter moment if it times out or loses a deadlock.
--
-- As written it ends in ROLLBACK: a dry run that prints the counts and a
-- NOTICE with what it would set. To apply after review, change the final
-- ROLLBACK to COMMIT and run:
--
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
--     -f backend/scripts/backfill_vault_completion_new_best.sql

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $guard$
DECLARE
    v_fence_active BOOLEAN := false;
BEGIN
    IF pg_catalog.to_regprocedure(
        'public.br_vault_completion_is_new_best(uuid,text,text,timestamp with time zone,bigint,boolean,text)'
    ) IS NULL THEN
        RAISE EXCEPTION
            'migration 176_vault_completion_new_best.sql is not applied; nothing was written';
    END IF;

    IF pg_catalog.to_regprocedure(
        'public.br_account_deletion_write_fence_active()'
    ) IS NOT NULL THEN
        EXECUTE 'SELECT public.br_account_deletion_write_fence_active()'
            INTO v_fence_active;
        IF v_fence_active THEN
            RAISE EXCEPTION
                'an account deletion is queued or in progress; run the backfill after it settles';
        END IF;
    END IF;
END;
$guard$;

-- Report: rows that disagree with the rule today.
SELECT pg_catalog.count(*) FILTER (WHERE decided.is_new_best)
           AS rows_to_new_best,
       pg_catalog.count(*) FILTER (WHERE NOT decided.is_new_best)
           AS rows_to_not_new_best,
       pg_catalog.count(DISTINCT completion.wallet || pg_catalog.chr(31)
           || completion.vault_signature)
           AS rider_climbs
FROM public.vault_completions AS completion
CROSS JOIN LATERAL (
    SELECT public.br_vault_completion_is_new_best(
        completion.id,
        completion.vault_signature,
        completion.wallet,
        completion.completed_at,
        completion.time_seconds,
        completion.validated,
        completion.chain_confirmation_status
    ) AS is_new_best
) AS decided
WHERE completion.is_pr IS DISTINCT FROM decided.is_new_best;

DO $backfill$
DECLARE
    v_to_new_best BIGINT;
    v_to_not_new_best BIGINT;
    v_updated BIGINT;
    v_changed_rows BIGINT;
    v_changed_rides BIGINT := 0;
    v_off_rule BIGINT;
BEGIN
    CREATE TEMP TABLE br_new_best_backfill ON COMMIT DROP AS
    SELECT completion.id,
           completion.activity_id,
           decided.is_new_best,
           pg_catalog.to_jsonb(completion) - 'is_pr' AS row_before
    FROM public.vault_completions AS completion
    CROSS JOIN LATERAL (
        SELECT public.br_vault_completion_is_new_best(
            completion.id,
            completion.vault_signature,
            completion.wallet,
            completion.completed_at,
            completion.time_seconds,
            completion.validated,
            completion.chain_confirmation_status
        ) AS is_new_best
    ) AS decided
    WHERE completion.is_pr IS DISTINCT FROM decided.is_new_best;

    SELECT pg_catalog.count(*) FILTER (WHERE target.is_new_best),
           pg_catalog.count(*) FILTER (WHERE NOT target.is_new_best)
    INTO v_to_new_best, v_to_not_new_best
    FROM pg_temp.br_new_best_backfill AS target;

    IF pg_catalog.to_regclass('public.rides') IS NOT NULL THEN
        CREATE TEMP TABLE br_new_best_backfill_rides ON COMMIT DROP AS
        SELECT ride.id, ride.finalized_at
        FROM public.rides AS ride
        WHERE ride.id::TEXT IN (
            SELECT target.activity_id FROM pg_temp.br_new_best_backfill AS target
        );
    END IF;

    UPDATE public.vault_completions AS completion
    SET is_pr = target.is_new_best
    FROM pg_temp.br_new_best_backfill AS target
    WHERE completion.id = target.id;
    GET DIAGNOSTICS v_updated = ROW_COUNT;

    SELECT pg_catalog.count(*) INTO v_changed_rows
    FROM pg_temp.br_new_best_backfill AS target
    LEFT JOIN public.vault_completions AS completion
        ON completion.id = target.id
    WHERE completion.id IS NULL
       OR pg_catalog.to_jsonb(completion) - 'is_pr'
          IS DISTINCT FROM target.row_before;
    IF v_changed_rows > 0 THEN
        RAISE EXCEPTION
            'backfill would change columns besides is_pr on % vault_completions rows; nothing was written',
            v_changed_rows;
    END IF;

    IF pg_catalog.to_regclass('public.rides') IS NOT NULL THEN
        SELECT pg_catalog.count(*) INTO v_changed_rides
        FROM pg_temp.br_new_best_backfill_rides AS before
        LEFT JOIN public.rides AS ride ON ride.id = before.id
        WHERE ride.id IS NULL
           OR ride.finalized_at IS DISTINCT FROM before.finalized_at;
        IF v_changed_rides > 0 THEN
            RAISE EXCEPTION
                'backfill would change rides.finalized_at on % rides besides is_pr; nothing was written',
                v_changed_rides;
        END IF;
    END IF;

    SELECT pg_catalog.count(*) INTO v_off_rule
    FROM public.vault_completions AS completion
    WHERE completion.is_pr IS DISTINCT FROM public.br_vault_completion_is_new_best(
        completion.id,
        completion.vault_signature,
        completion.wallet,
        completion.completed_at,
        completion.time_seconds,
        completion.validated,
        completion.chain_confirmation_status
    );
    IF v_off_rule > 0 THEN
        RAISE EXCEPTION
            '% vault_completions rows still disagree with the new-best rule; nothing was written',
            v_off_rule;
    END IF;

    RAISE NOTICE
        'vault_completions new-best backfill: % rows set (% to new best, % to not new best); COMMIT applies it, ROLLBACK discards it',
        v_updated, v_to_new_best, v_to_not_new_best;
END;
$backfill$;

ROLLBACK;
