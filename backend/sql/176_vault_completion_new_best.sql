-- Migration: 176_vault_completion_new_best.sql
-- Description: vault_completions.is_pr says whether a completion was the
--              rider's new best on that climb, whichever writer records it.
-- Date: 2026-10-20
--
-- The ride page "New best" and the iOS reveal read vault_completions.is_pr
-- (vaultMatch.isPR). Migration 053 added the column and set it only inside
-- record_vault_completion_with_metadata, which assumed one row per rider per
-- Vault. The table holds one row per (vault_signature, activity_id), and none
-- of the writers that replaced that function sets the column:
-- record_vault_completion_projection (128),
-- reconcile_confirmed_vault_completion (128),
-- reconcile_confirmed_reward_threshold_release_completion (155) and the
-- repository REST fallback all leave its false default. The moment never
-- fired.
--
-- The rule now lives on the table, so every writer gets it:
--   * An effort counts toward a best when it is validated, chain-confirmed and
--     timed: the same rows the climb effort history reads.
--   * Efforts are ordered by original ride completed_at, then id. As on the
--     Record Board, processing order never decides (PROTOCOL_TRUTHS section
--     6.3): a ride recorded late, such as a held ride released after newer
--     rides, re-decides the rider's later efforts on that climb.
--   * An effort is a new best when it counts and no earlier counting effort by
--     the same wallet on the same Vault is as fast or faster. time_seconds is
--     whole seconds, so a tie is not a new best (sections 6.2 and 14.6). The
--     rider's first counting effort is a new best.
--
-- Writes that decide one rider's best on one climb serialize on a
-- transaction-scoped advisory lock, so two rides recorded at once still see
-- each other under READ COMMITTED.
--
-- No backfill: this migration writes no existing row. A row recorded before
-- it keeps its stored value until it, or an earlier effort by the same rider
-- on that climb, is written again.
-- backend/scripts/backfill_vault_completion_new_best.sql is the separate,
-- reviewed repair.
--
-- Locks: is_pr has existed since 053, so nothing here alters the table, and
-- the triggers are created or replaced in place. The strongest lock taken on
-- vault_completions is SHARE ROW EXCLUSIVE, held until commit: writes to the
-- table wait for this migration, reads never do.

-- If a long transaction holds the table, fail fast and stop the deploy rather
-- than queue ride writes behind it.
SET LOCAL lock_timeout = '5s';

CREATE OR REPLACE FUNCTION public.br_vault_completion_counts_toward_best(
    p_validated BOOLEAN,
    p_chain_confirmation_status TEXT,
    p_time_seconds BIGINT
) RETURNS BOOLEAN
LANGUAGE sql
IMMUTABLE
SET search_path = ''
AS $$
    SELECT p_validated IS TRUE
       AND p_chain_confirmation_status IS NOT DISTINCT FROM 'confirmed'
       AND p_time_seconds IS NOT NULL;
$$;

COMMENT ON FUNCTION public.br_vault_completion_counts_toward_best(
    BOOLEAN, TEXT, BIGINT
) IS
'Whether a vault completion is sporting history that can set or hold a rider''s best: validated, chain-confirmed and timed.';

-- VOLATILE on purpose: inside triggers it must see rows written earlier in
-- the same command and rows committed while it waited on the advisory lock.
CREATE OR REPLACE FUNCTION public.br_vault_completion_is_new_best(
    p_completion_id UUID,
    p_vault_signature TEXT,
    p_wallet TEXT,
    p_completed_at TIMESTAMPTZ,
    p_time_seconds BIGINT,
    p_validated BOOLEAN,
    p_chain_confirmation_status TEXT
) RETURNS BOOLEAN
LANGUAGE sql
VOLATILE
SET search_path = ''
AS $$
    SELECT public.br_vault_completion_counts_toward_best(
               p_validated, p_chain_confirmation_status, p_time_seconds
           )
       AND NOT EXISTS (
           SELECT 1
           FROM public.vault_completions AS earlier
           WHERE earlier.wallet = p_wallet
             AND earlier.vault_signature = p_vault_signature
             -- An UPDATE's BEFORE trigger can still see the row's old version.
             AND earlier.id <> p_completion_id
             AND public.br_vault_completion_counts_toward_best(
                     earlier.validated,
                     earlier.chain_confirmation_status,
                     earlier.time_seconds
                 )
             AND earlier.time_seconds <= p_time_seconds
             AND (earlier.completed_at, earlier.id)
                 < (p_completed_at, p_completion_id)
       );
$$;

COMMENT ON FUNCTION public.br_vault_completion_is_new_best(
    UUID, TEXT, TEXT, TIMESTAMPTZ, BIGINT, BOOLEAN, TEXT
) IS
'The vault_completions.is_pr rule: a counting effort with no earlier counting effort by the same wallet on the same Vault (by completed_at, then id) at an equal or faster whole-second time.';

CREATE OR REPLACE FUNCTION public.br_lock_vault_completion_new_best(
    p_wallet TEXT,
    p_vault_signature TEXT
) RETURNS VOID
LANGUAGE plpgsql
SET search_path = ''
AS $$
BEGIN
    PERFORM pg_catalog.pg_advisory_xact_lock(
        pg_catalog.hashtextextended(
            'vault-completion-new-best' || pg_catalog.chr(31) || p_wallet
                || pg_catalog.chr(31) || p_vault_signature,
            0
        )
    );
END;
$$;

COMMENT ON FUNCTION public.br_lock_vault_completion_new_best(TEXT, TEXT) IS
'Serializes, until commit, the writes that decide one rider''s best on one Vault.';

CREATE OR REPLACE FUNCTION public.br_refresh_vault_completion_new_bests_after(
    p_wallet TEXT,
    p_vault_signature TEXT,
    p_completed_at TIMESTAMPTZ,
    p_completion_id UUID
) RETURNS VOID
LANGUAGE plpgsql
SET search_path = ''
AS $$
BEGIN
    PERFORM public.br_lock_vault_completion_new_best(p_wallet, p_vault_signature);

    -- Only counting efforts after the changed position can change, and only
    -- rows whose flag actually changes are written. Each written row's BEFORE
    -- trigger re-derives the same value.
    WITH decided AS (
        SELECT later.id,
               public.br_vault_completion_is_new_best(
                   later.id,
                   later.vault_signature,
                   later.wallet,
                   later.completed_at,
                   later.time_seconds,
                   later.validated,
                   later.chain_confirmation_status
               ) AS is_new_best
        FROM public.vault_completions AS later
        WHERE later.wallet = p_wallet
          AND later.vault_signature = p_vault_signature
          AND public.br_vault_completion_counts_toward_best(
                  later.validated,
                  later.chain_confirmation_status,
                  later.time_seconds
              )
          AND (later.completed_at, later.id) > (p_completed_at, p_completion_id)
    )
    UPDATE public.vault_completions AS target
    SET is_pr = decided.is_new_best
    FROM decided
    WHERE target.id = decided.id
      AND target.is_pr IS DISTINCT FROM decided.is_new_best;
END;
$$;

COMMENT ON FUNCTION public.br_refresh_vault_completion_new_bests_after(
    TEXT, TEXT, TIMESTAMPTZ, UUID
) IS
'Re-decides is_pr for one rider''s counting efforts on one Vault after a position, writing only rows whose flag changes.';

CREATE OR REPLACE FUNCTION public.br_set_vault_completion_new_best()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    IF TG_OP = 'UPDATE'
       AND NEW.is_pr IS NOT DISTINCT FROM OLD.is_pr
       AND NEW.vault_signature IS NOT DISTINCT FROM OLD.vault_signature
       AND NEW.wallet IS NOT DISTINCT FROM OLD.wallet
       AND NEW.completed_at IS NOT DISTINCT FROM OLD.completed_at
       AND NEW.time_seconds IS NOT DISTINCT FROM OLD.time_seconds
       AND NEW.validated IS NOT DISTINCT FROM OLD.validated
       AND NEW.chain_confirmation_status
           IS NOT DISTINCT FROM OLD.chain_confirmation_status THEN
        -- Nothing the rule reads changed, for example the on-chain tx mirror.
        RETURN NEW;
    END IF;

    IF NOT public.br_vault_completion_counts_toward_best(
        NEW.validated,
        NEW.chain_confirmation_status,
        NEW.time_seconds
    ) THEN
        NEW.is_pr := false;
        RETURN NEW;
    END IF;

    PERFORM public.br_lock_vault_completion_new_best(
        NEW.wallet,
        NEW.vault_signature
    );
    NEW.is_pr := public.br_vault_completion_is_new_best(
        NEW.id,
        NEW.vault_signature,
        NEW.wallet,
        NEW.completed_at,
        NEW.time_seconds,
        NEW.validated,
        NEW.chain_confirmation_status
    );
    RETURN NEW;
END;
$$;

COMMENT ON FUNCTION public.br_set_vault_completion_new_best() IS
'BEFORE trigger: derives is_pr for the row being written; writers never set it.';

CREATE OR REPLACE FUNCTION public.br_refresh_later_vault_completion_new_bests()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        PERFORM public.br_refresh_vault_completion_new_bests_after(
            NEW.wallet, NEW.vault_signature, NEW.completed_at, NEW.id
        );
    ELSIF TG_OP = 'DELETE' THEN
        PERFORM public.br_refresh_vault_completion_new_bests_after(
            OLD.wallet, OLD.vault_signature, OLD.completed_at, OLD.id
        );
    ELSIF OLD.wallet IS DISTINCT FROM NEW.wallet
       OR OLD.vault_signature IS DISTINCT FROM NEW.vault_signature THEN
        PERFORM public.br_refresh_vault_completion_new_bests_after(
            OLD.wallet, OLD.vault_signature, OLD.completed_at, OLD.id
        );
        PERFORM public.br_refresh_vault_completion_new_bests_after(
            NEW.wallet, NEW.vault_signature, NEW.completed_at, NEW.id
        );
    ELSIF (OLD.completed_at, OLD.id) <= (NEW.completed_at, NEW.id) THEN
        PERFORM public.br_refresh_vault_completion_new_bests_after(
            OLD.wallet, OLD.vault_signature, OLD.completed_at, OLD.id
        );
    ELSE
        PERFORM public.br_refresh_vault_completion_new_bests_after(
            NEW.wallet, NEW.vault_signature, NEW.completed_at, NEW.id
        );
    END IF;
    RETURN NULL;
END;
$$;

COMMENT ON FUNCTION public.br_refresh_later_vault_completion_new_bests() IS
'AFTER trigger: re-decides the rider''s later efforts on the climb when a counting effort is added, removed, moved or re-timed.';

-- BEFORE triggers fire in name order; this one sorts after the 114 chain
-- authority trigger, so it reads the final validated value. The rule does
-- not depend on that order: unconfirmed rows never count.
CREATE OR REPLACE TRIGGER trg_vault_completion_new_best
BEFORE INSERT OR UPDATE ON public.vault_completions
FOR EACH ROW
EXECUTE FUNCTION public.br_set_vault_completion_new_best();

-- The WHEN conditions are written inline, without helper calls, so they need
-- no EXECUTE privilege from the writing role.
CREATE OR REPLACE TRIGGER trg_vault_completion_new_best_after_insert
AFTER INSERT ON public.vault_completions
FOR EACH ROW
WHEN (
    NEW.validated IS TRUE
    AND NEW.chain_confirmation_status IS NOT DISTINCT FROM 'confirmed'
    AND NEW.time_seconds IS NOT NULL
)
EXECUTE FUNCTION public.br_refresh_later_vault_completion_new_bests();

CREATE OR REPLACE TRIGGER trg_vault_completion_new_best_after_update
AFTER UPDATE ON public.vault_completions
FOR EACH ROW
WHEN (
    (
        (
            OLD.validated IS TRUE
            AND OLD.chain_confirmation_status IS NOT DISTINCT FROM 'confirmed'
            AND OLD.time_seconds IS NOT NULL
        )
        OR (
            NEW.validated IS TRUE
            AND NEW.chain_confirmation_status IS NOT DISTINCT FROM 'confirmed'
            AND NEW.time_seconds IS NOT NULL
        )
    )
    AND (
        OLD.vault_signature IS DISTINCT FROM NEW.vault_signature
        OR OLD.wallet IS DISTINCT FROM NEW.wallet
        OR OLD.completed_at IS DISTINCT FROM NEW.completed_at
        OR OLD.time_seconds IS DISTINCT FROM NEW.time_seconds
        OR OLD.validated IS DISTINCT FROM NEW.validated
        OR OLD.chain_confirmation_status IS DISTINCT FROM NEW.chain_confirmation_status
    )
)
EXECUTE FUNCTION public.br_refresh_later_vault_completion_new_bests();

CREATE OR REPLACE TRIGGER trg_vault_completion_new_best_after_delete
AFTER DELETE ON public.vault_completions
FOR EACH ROW
WHEN (
    OLD.validated IS TRUE
    AND OLD.chain_confirmation_status IS NOT DISTINCT FROM 'confirmed'
    AND OLD.time_seconds IS NOT NULL
)
EXECUTE FUNCTION public.br_refresh_later_vault_completion_new_bests();

COMMENT ON COLUMN public.vault_completions.is_pr IS
'New best: true when this validated, chain-confirmed, timed effort is strictly faster, in whole seconds, than every earlier one by the same wallet on this Vault, by original ride completed_at. The first such effort is a new best; a tie is not. Set by trg_vault_completion_new_best (migration 176), never by writers.';

-- Internal, as in 152: only the owner calls these, through the SECURITY
-- DEFINER triggers. Writers need no grant, and the API roles, service_role
-- included, cannot call the lock or the rule as an RPC.
REVOKE ALL ON FUNCTION public.br_vault_completion_counts_toward_best(
    BOOLEAN, TEXT, BIGINT
) FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.br_vault_completion_is_new_best(
    UUID, TEXT, TEXT, TIMESTAMPTZ, BIGINT, BOOLEAN, TEXT
) FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.br_lock_vault_completion_new_best(TEXT, TEXT)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.br_refresh_vault_completion_new_bests_after(
    TEXT, TEXT, TIMESTAMPTZ, UUID
) FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.br_set_vault_completion_new_best()
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.br_refresh_later_vault_completion_new_bests()
    FROM PUBLIC, anon, authenticated, service_role;
